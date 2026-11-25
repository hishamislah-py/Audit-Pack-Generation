"""File-backed repositories. Layout under the application-state directory:

    jobs/<job_id>.json                         final_pack_records/<decision_id>.json
    reviews/<review_id>/session.json           reviews/<review_id>/decisions.jsonl                 (append-only)
    reviews/<review_id>/previews/<preview_id>/{meta.json, preview.json}                            (write-once)
    registry/investigation_registry.json       the publication registry (rewritten atomically on each append)

Every whole-file write is atomic (stage + fsync + os.replace); appends are fsynced. Each repository serialises its own
reads and writes with an in-process lock (on Windows, reading a file while os.replace swaps it fails); the backend runs as a single process (enforced by storage.InstanceLock).
"""
import threading
from pathlib import Path

from ..storage import append_line, atomic_write_json, create_json, read_json, read_lines
from .base import (AiAuthorizationRepository, ConcurrentUpdate, DuplicateRecord, FinalPackRecordRepository, JobRepository,
                   RegistryRepository, ReviewRepository)


class _Dir:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, key):
        return self.root / f"{key}.json"

    def _all(self):
        with self.lock:
            return [r for r in (read_json(p) for p in sorted(self.root.glob("*.json"))) if r is not None]


class FileJobRepository(_Dir, JobRepository):
    def create(self, job):
        with self.lock:
            create_json(self._path(job["job_id"]), job)
            return job

    def get(self, job_id):
        with self.lock:  # reads share the writers' lock: on Windows a read during os.replace fails
            return read_json(self._path(job_id))

    def update(self, job_id, changes):
        with self.lock:
            job = self.get(job_id)
            if job is None:
                raise KeyError(job_id)
            job.update(changes)
            atomic_write_json(self._path(job_id), job)
            return job

    def list(self, pack_id=None, exception_id=None, statuses=None):
        return sorted((j for j in self._all() if (pack_id is None or j["pack_id"] == pack_id)
                       and (exception_id is None or j.get("exception_id") == exception_id)
                       and (statuses is None or j["status"] in statuses)), key=lambda j: j["submitted_at"])


class FileReviewRepository(_Dir, ReviewRepository):
    def _dir(self, review_id):
        return self.root / review_id

    def create(self, session):
        with self.lock:
            create_json(self._dir(session["review_id"]) / "session.json", session)
            return session

    def get(self, review_id):
        with self.lock:
            return read_json(self._dir(review_id) / "session.json")

    def save(self, session, expected_revision):
        with self.lock:
            stored = self.get(session["review_id"])
            if stored is None or stored["revision"] != expected_revision:
                raise ConcurrentUpdate(f"review {session['review_id']} changed (revision {stored and stored['revision']})")
            session = dict(session, revision=expected_revision + 1)
            atomic_write_json(self._dir(session["review_id"]) / "session.json", session)
            return session

    def list(self, pack_id=None):
        with self.lock:
            out = [s for s in (read_json(p) for p in sorted(self.root.glob("RS-*/session.json"))) if s]
        return sorted((s for s in out if pack_id is None or s["pack_id"] == pack_id), key=lambda s: s["created_at"])

    def append_decision(self, review_id, decision):
        with self.lock:
            append_line(self._dir(review_id) / "decisions.jsonl", decision)
            return decision

    def decisions(self, review_id):
        with self.lock:
            return read_lines(self._dir(review_id) / "decisions.jsonl")

    def save_preview(self, review_id, preview_id, meta, document):
        d = self._dir(review_id) / "previews" / preview_id
        with self.lock:
            create_json(d / "preview.json", document)
            create_json(d / "meta.json", meta)

    def get_preview(self, review_id, preview_id):
        d = self._dir(review_id) / "previews" / preview_id
        with self.lock:
            return read_json(d / "meta.json"), read_json(d / "preview.json")


class FileFinalPackRecordRepository(_Dir, FinalPackRecordRepository):
    def create(self, record):
        with self.lock:
            try:
                create_json(self._path(record["review_decision_id"]), record)
            except FileExistsError:
                raise DuplicateRecord(record["review_decision_id"]) from None
            return record

    def get(self, decision_id):
        with self.lock:
            return read_json(self._path(decision_id))

    def update(self, decision_id, changes):
        with self.lock:
            record = self.get(decision_id)
            record.update(changes)
            atomic_write_json(self._path(decision_id), record)
            return record

    def list(self, pack_id=None):
        return sorted((r for r in self._all() if pack_id is None or r["pack_id"] == pack_id), key=lambda r: r["created_at"])


class FileRegistryRepository(_Dir, RegistryRepository):
    """The whole registry is one small JSON file, rewritten atomically on each append: a crash leaves either the old or
    the new file, never a partial entry."""

    def _file(self):
        return self.root / "investigation_registry.json"

    def append(self, entry):
        with self.lock:
            atomic_write_json(self._file(), {"entries": self.entries() + [entry]})

    def entries(self):
        with self.lock:
            data = read_json(self._file(), {"entries": []})
        return list(data["entries"])

    def signature(self):
        try:
            st = self._file().stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None


class FileAiAuthorizationRepository(_Dir, AiAuthorizationRepository):
    """Pre-execution AI authorisations as fsynced JSON lines (append-only; there is no update or delete)."""

    def _file(self):
        return self.root / "ai_execution_authorizations.jsonl"

    def record(self, rec):
        with self.lock:
            rec = dict(rec, id=len(read_lines(self._file())) + 1)
            append_line(self._file(), rec)
            return rec

    def get(self, authorization_id):
        return next((r for r in self.list() if r["authorization_id"] == authorization_id), None)

    def list(self, pack_id=None, exception_id=None, review_id=None, job_id=None, period_id=None):
        with self.lock:
            rows = read_lines(self._file())
        want = {"pack_id": pack_id, "exception_id": exception_id, "review_id": review_id, "job_id": job_id, "period_id": period_id}
        return [r for r in rows if all(v is None or r.get(k) == v for k, v in want.items())]


class FileRepositories:
    """All repositories over one application-state directory."""

    def __init__(self, state_dir):
        root = Path(state_dir)
        self.jobs = FileJobRepository(root / "jobs")
        self.reviews = FileReviewRepository(root / "reviews")
        self.final_packs = FileFinalPackRecordRepository(root / "final_pack_records")
        self.registry = FileRegistryRepository(root / "registry")
        # Pre-execution AI authorisations are kept in both modes: every paid AI operation is confirmed and recorded first.
        self.ai_authorizations = FileAiAuthorizationRepository(root / "ai_authorizations")
        # Monthly document management (periods, uploads, processing runs, activity), exception investigation cases,
        # investigation authorisation decisions and reassessment lineage require the database.
        self.activity = self.periods = self.uploads = self.runs = self.cases = self.authorizations = self.lineage = None
