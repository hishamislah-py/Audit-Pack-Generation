"""Application context: the EXISTING services wired on one workspace, a staging area for uploads, and background jobs
whose progress is taken only from real service results and recorded audit events (never from timers)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import threading
import traceback
import uuid
import zipfile
import zlib
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from ..ai.config import AIConfig
from ..ai.gateway import DisabledLiveProvider, ProposalGateway
from ..ai.proposer import RecordedResponseStub
from ..csv_engine.reader import read_csv
from ..identify.detect import identify
from ..intake.store import EvidenceStore
from ..mapping.rule_store import RuleStore
from ..orchestration.orchestrator import MappingOrchestrator
from ..orchestration.policy import PocAutoAcceptPolicy
from ..packages.service import PackageService, Submission
from ..packages.store import PackageStore, _read_text, _retry_sharing
from ..reconciliation.uc042_adapter import run_reconciliation
from ..review.audit import AuditLog
from ..review.authority import AuthorityPolicy, Reviewer
from ..schemas import SchemaRegistry
from . import identity

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_ZIP_ENTRIES = 500
SAMPLE_ROWS = 6


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_error_kind(exc: BaseException) -> str:
    """A stable label for why one ZIP member could not be read (display / outstanding work; the exact error is kept)."""
    msg = str(exc)
    if isinstance(exc, zipfile.BadZipFile) and "CRC" in msg:
        return "CRC_FAILURE"
    if isinstance(exc, (zlib.error, EOFError)):
        return "DECOMPRESSION_ERROR"
    if isinstance(exc, NotImplementedError):
        return "UNSUPPORTED_COMPRESSION"
    if isinstance(exc, RuntimeError) and "encrypt" in msg.lower():
        return "ENCRYPTED"
    return "READ_ERROR"


def sniff_kind(data: bytes, name: str) -> str:
    """Display-only file type from the content signature (classification is done by the service, not here)."""
    if data[:5] == b"%PDF-":
        return "PDF"
    if data[:4] == b"PK\x03\x04":
        return "ZIP"
    if name.lower().endswith((".csv", ".txt")) or (data and b"\x00" not in data[:4096]):
        return "CSV / text"
    return "unsupported"


@dataclass
class AppContext:
    root: Path
    authority_path: Path | None
    reviewer: Reviewer
    uc042_root: Path | None
    recorded: list[Path] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    jobs: dict = field(default_factory=dict)
    job_listeners: list = field(default_factory=list)      # callables(job) run after a job reaches a final state
    mapping_ai: object = None                               # Fix8 D1: ai.live_config.MappingAISettings (None = off)

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        reg = SchemaRegistry.from_directory()
        self.reg = reg
        self.log = AuditLog(self.root / "audit.jsonl")
        if self.recorded:
            self.stub = RecordedResponseStub([json.loads(Path(p).read_text(encoding="utf-8")) for p in self.recorded])
            gw = ProposalGateway(proposer=self.stub, config=AIConfig(enabled=True, provider="recorded_stub"), log=self.log)
            self.llm_mode = {"mode": "RECORDED", "label": "Recorded LLM responses (offline test fixtures)",
                             "fixtures": [Path(p).name for p in self.recorded]}
        elif self.mapping_ai is not None and self.mapping_ai.enabled:
            self.stub = None
            gw, self.llm_mode = self._live_mapping_gateway()
        else:
            self.stub = None
            gw = ProposalGateway(proposer=DisabledLiveProvider(), config=AIConfig(), log=self.log)
            self.llm_mode = {"mode": "DISABLED", "label": "AI proposals disabled", "fixtures": []}
        self.gateway = gw
        rules_dir = self.root / "rules"
        rules = RuleStore(rules_dir, reg) if rules_dir.is_dir() and any(rules_dir.iterdir()) else \
            RuleStore.initialise(rules_dir, reg)          # a workspace copy of the packaged rules (never written back)
        # Fix8 D1/DEF-A1: a file whose unresolved columns get no usable proposal (AI off, denied, provider failure,
        # invalid proposal) opens a MANUAL column review instead of a FAILED_VALIDATION dead end; a live AI proposal is
        # reviewed in a column-review case (MAP / CHANGE / IGNORE / reject). The POC auto-accept policy is unchanged.
        orch = MappingOrchestrator(reg, rules, EvidenceStore(self.root / "evidence"), gw, PocAutoAcceptPolicy.load(),
                                   self.log, manual_review_fallback=True,
                                   proposals_as_cases=self.llm_mode.get("mode") == "LIVE")
        self.authority = AuthorityPolicy.load(self.authority_path) if self.authority_path else AuthorityPolicy.load()
        self.svc = PackageService(PackageStore(self.root / "pk"), orch, self.authority)
        self.staging = self.root / "staging"
        self.runs = self.root / "runs"
        self.jobdir = self.root / "jobs"
        for d in (self.staging, self.runs, self.jobdir):
            d.mkdir(exist_ok=True)
        self.job_load_errors = []                                 # unreadable job records: kept visible, never guessed
        for p in sorted(self.jobdir.glob("*.json")):              # job records survive a restart (read-only)
            try:                                                  # (*.tmp files of an interrupted write never match)
                j = json.loads(_read_text(p))                     # Fix8 D-recon-io: a sharing violation is retried
                if j.get("state") in ("queued", "running"):
                    j["state"], j["error"] = "interrupted", "the server stopped while this job was running"
                self.jobs[j["job_id"]] = j
            except (OSError, ValueError, KeyError) as exc:
                self.job_load_errors.append({"file": p.name, "error": f"{type(exc).__name__}: {exc}"[:300]})
        from .cases import CaseService                            # Ringfence case registry (additive)
        self.cases = CaseService(self)

    def _live_mapping_gateway(self):
        """Fix8 D1: the existing ProposalGateway around the existing OpenAI mapping proposer, configured from the
        server's AI env file (exact allowlist). The usage ledger is kept in the workspace, so the daily cap survives
        a restart."""
        from ..ai.live_config import build_mapping_gateway
        return build_mapping_gateway(self.mapping_ai, self.log, self.root / "ai_mapping_usage.json")

    # ============================================================================================ identity (Fix8 D6, I-1)
    @property
    def server_reviewer(self) -> Reviewer:
        """The reviewer fixed at server start-up (--reviewer-id/--reviewer-role/--reviewer-kind)."""
        return self.__dict__["_server_reviewer"]

    # ============================================================================================ staging
    def stage(self, name: str, data: bytes) -> list[dict]:
        """Stage an upload. A ZIP is expanded into its file entries (directories, hidden / macOS metadata entries are
        skipped and listed). Nothing is classified here.

        Whole-archive problems (not a ZIP, cannot be opened, too many entries, an entry over the size limit) raise and
        nothing is staged. ONE unreadable member of a readable archive (bad CRC-32, decompression error, encrypted,
        unsupported compression...) is isolated: it is returned as an `unreadable` entry with its central-directory
        name and size and the exact error, its bytes are never staged, and every other member is staged normally.
        The integrity checks themselves are unchanged (zipfile still verifies every member's CRC-32 on read)."""
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"FILE_TOO_LARGE: {name} exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB")
        if data[:4] == b"PK\x03\x04" and name.lower().endswith(".zip"):
            out = []
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as exc:
                raise ValueError(f"INVALID_ZIP: {name} is not a readable ZIP archive") from exc
            infos = [i for i in z.infolist() if not i.is_dir()]
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError(f"ZIP_TOO_LARGE: {len(infos)} entries (limit {MAX_ZIP_ENTRIES})")
            for i in infos:                              # whole-archive limits first: nothing is staged if one fails
                if i.file_size > MAX_FILE_BYTES:
                    raise ValueError(f"FILE_TOO_LARGE: {i.filename} in {name}")
            staged_dirs = []
            try:
                for i in infos:
                    base = PurePosixPath(i.filename.replace("\\", "/")).name
                    if i.filename.startswith("__MACOSX/") or base.startswith(".") or not base:
                        out.append({"staging_id": None, "name": i.filename, "skipped": "system / hidden entry",
                                    "from_zip": name})
                        continue
                    try:
                        member = z.read(i)                   # CRC-32 and size are verified by zipfile on a full read
                    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError,
                            ValueError, OSError) as exc:
                        out.append({"staging_id": None, "name": i.filename, "unreadable": True,
                                    "error_kind": _read_error_kind(exc), "error": f"{type(exc).__name__}: {exc}"[:500],
                                    "size": i.file_size, "compressed_size": i.compress_size, "from_zip": name})
                        continue
                    meta = self._stage_one(base, member, from_zip=name)    # only a fully read member is staged
                    staged_dirs.append(self.staging / meta["staging_id"])
                    out.append(meta)
            except BaseException:                            # never leave a partial staging set behind
                for d in staged_dirs:
                    shutil.rmtree(d, ignore_errors=True)
                raise
            return out
        return [self._stage_one(name, data)]

    def _stage_one(self, name: str, data: bytes, from_zip: str | None = None) -> dict:
        sid = f"STG-{uuid.uuid4().hex[:12]}"
        meta = {"staging_id": sid, "name": PurePosixPath(name.replace("\\", "/")).name, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "kind": sniff_kind(data, name), "from_zip": from_zip,
                "staged_at": now()}
        d = self.staging / sid
        d.mkdir()
        (d / "data").write_bytes(data)
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def staged(self, sid: str) -> tuple[dict, bytes]:
        if not sid or not sid.startswith("STG-") or not sid[4:].isalnum():
            raise ValueError(f"INVALID_STAGING_ID: {sid!r}")
        d = self.staging / sid
        if not (d / "meta.json").is_file():
            raise LookupError(f"staged file {sid} not found")
        return json.loads((d / "meta.json").read_text(encoding="utf-8")), (d / "data").read_bytes()

    # ============================================================================================ audit
    def events(self) -> list[dict]:
        """Tolerant read of the audit log for display (a line being appended right now is skipped, never repaired)."""
        out = []
        p = self.log.path
        if not p.is_file():
            return out
        # Fix8 D-recon-io: a transient Windows sharing violation is retried; a half-appended (possibly mid-character)
        # last line decodes with a replacement character, fails json and ends the read like any partial line.
        raw = _retry_sharing(lambda: p.read_bytes())
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break
        return out

    def last_seq(self) -> int:
        ev = self.events()
        return ev[-1]["seq"] if ev else 0

    # ============================================================================================ jobs
    def _save_job(self, j: dict) -> None:
        """Fix8 D-recon-io: ATOMIC job-record write. The record is serialised first, written to a private temporary
        file and moved into place with os.replace, so a reader (restart recovery, a tool) only ever sees the previous
        or the new complete record - never a truncated one. Transient Windows sharing violations (PermissionError on
        open/replace while another process - indexer, antivirus, a reader - holds the file) are retried; a persistent
        failure propagates to the caller and the temporary file is removed."""
        p = self.jobdir / f"{j['job_id']}.json"
        text = json.dumps(j, indent=1, default=str)
        tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            _retry_sharing(lambda: tmp.write_text(text, encoding="utf-8"))
            _retry_sharing(lambda: os.replace(tmp, p))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _new_job(self, kind: str, package_id: str, **extra) -> dict:
        j = {"job_id": f"JOB-{uuid.uuid4().hex[:10]}", "kind": kind, "package_id": package_id, "state": "queued",
             "created_at": now(), "started_at": None, "finished_at": None, "error": None,
             "audit_seq_start": self.last_seq() + 1, "audit_seq_end": None, **extra}
        self._save_job(j)                       # persisted first: a job that cannot be recorded is never registered
        self.jobs[j["job_id"]] = j              # (else it would stay 'queued' in memory and look busy forever)
        return j

    def _case_view_lock(self):
        """The case registry's lock (Fix8 D-recon-io). CaseService.detail() decides the case status (_refresh) and
        then computes progress/current_operation under this lock, both from the LIVE job dicts. A job therefore
        publishes its terminal state - and runs the listeners that act on it - under the same lock, so a case view
        sees either 'job running' or 'job finished AND the case refreshed', never the torn mix 'no running job, case
        still IN_PROGRESS' (observed under load). Lock order stays case lock -> ctx.lock: a job takes it only after it
        has released ctx.lock."""
        cases = getattr(self, "cases", None)
        return getattr(cases, "lock", None) or nullcontext()

    def _job_running(self, j: dict) -> None:
        j["state"], j["started_at"] = "running", now()
        self._save_job(j)

    def _job_finish(self, j: dict, **terminal) -> None:
        """Publish a job's terminal state (completed / failed) atomically for case views, persist it, then notify the
        listeners. A persistence or audit-read failure here never leaves the job looking busy and never skips the
        listeners: the in-memory terminal state stands, the failure is kept on the record (persist_error) and on
        stderr, and on a restart the on-disk 'running' record is reported as interrupted."""
        with self._case_view_lock():
            try:
                seq = self.last_seq()
            except Exception as exc:                                # recorded, never hidden
                seq = None
                j["persist_error"] = f"audit read: {type(exc).__name__}: {exc}"[:300]
            j.update(terminal)
            j["finished_at"], j["audit_seq_end"] = now(), seq
            try:
                self._save_job(j)
            except Exception as exc:
                j["persist_error"] = f"{type(exc).__name__}: {exc}"[:300]
                print(f"[job {j['job_id']}] terminal state {j['state']} could not be persisted: {j['persist_error']}",
                      file=sys.stderr, flush=True)
            self._notify(j)

    def start_intake(self, package_id: str, items: list[dict], resubmission: dict | None = None) -> dict:
        """items: [{staging_id, declared_category}] (initial intake) - or one item with resubmission={category, reason}.
        Files are processed one service call at a time, in the service's own order (CSV before PDF, so the package's
        IN-02 can resolve the acknowledgement letters) - identical semantics to one submit() call, with real per-file
        progress."""
        self.svc.load(package_id)                                   # 404 early
        files = []
        for it in items:
            meta, data = self.staged(it["staging_id"])
            files.append({"staging_id": meta["staging_id"], "name": meta["name"], "size": meta["size"],
                          "sha256": meta["sha256"], "kind": meta["kind"],
                          "declared_category": it.get("declared_category") or None, "state": "queued",
                          "started_at": None, "finished_at": None, "outcome": None})
        files.sort(key=lambda f: f["name"].lower().endswith(".pdf") or f["kind"] == "PDF")
        j = self._new_job("resubmission" if resubmission else "intake", package_id, files=files,
                          resubmission=resubmission, validation=None)
        self._spawn(self._run_intake, j)
        return j

    def _spawn(self, fn, j: dict) -> None:
        """Fix8 D6 (I-1): the job thread runs under the actor captured at job creation (the analyst whose request
        started it, or the system actor when nothing did). The actor is also recorded on the job record."""
        target = identity.bind(fn)
        j["actor"] = target.actor.as_record()
        self._save_job(j)
        threading.Thread(target=target, args=(j,), daemon=True).start()

    def _outcome(self, o) -> dict:
        v = o.file_version
        return {"evidence_category": o.evidence_category, "refused_reason": o.refused_reason,
                "file_version_id": v.file_version_id if v else None, "version_number": v.version_number if v else None,
                "version_status": v.version_status if v else None, "processing_status": v.processing_status if v else None,
                "content_category": v.content_category if v else None, "intake_id": v.intake_id if v else None,
                "reasons": v.reasons[:4] if v else [o.refused_reason], "missing_fields": v.missing_fields if v else [],
                "preview": bool(v and v.handoff and v.handoff.preview_csv),
                "review": "case" if v and v.review_case_id else "proposal" if v and v.review_session_id else None}

    def _run_intake(self, j: dict) -> None:
        try:
            self._job_running(j)                # inside the try: a job that cannot start ends 'failed', never stuck
            for f in j["files"]:
                f["state"], f["started_at"] = "running", now()
                self._save_job(j)
                try:
                    meta, data = self.staged(f["staging_id"])
                    with self.lock:
                        if j["resubmission"]:
                            o = self.svc.resubmit(j["package_id"], j["resubmission"]["category"], data, meta["name"],
                                                  j["resubmission"]["reason"])
                        else:
                            o = self.svc.submit(j["package_id"], [Submission(data, meta["name"],
                                                                             f["declared_category"])])[0]
                    f["outcome"], f["state"] = self._outcome(o), "done"
                except Exception as exc:                            # recorded on the file, never hidden
                    f["state"], f["outcome"] = "error", {"error": f"{type(exc).__name__}: {exc}"[:500]}
                f["finished_at"] = now()
                self._save_job(j)
            j["validation_started_at"] = now()
            self._save_job(j)
            with self.lock:
                res = self.svc.validate(j["package_id"])           # the real PV-01..PV-09 over the current candidate
            terminal = {"state": "completed",
                        "validation": {"validation_id": res.validation_id, "passed": res.passed, "at": res.at,
                                       "failed": [c.check_id for c in res.checks if not c.passed]}}
        except Exception as exc:
            terminal = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"[:800],
                        "trace": traceback.format_exc()[-2000:]}
        self._job_finish(j, **terminal)

    def _notify(self, j: dict) -> None:
        """Tell listeners (the case registry) that a job reached a final state. A listener failure never changes the
        job record; it is kept on the job for inspection."""
        for fn in list(self.job_listeners):
            try:
                fn(j)
            except Exception as exc:                                # recorded, never hidden
                j.setdefault("listener_errors", []).append(f"{type(exc).__name__}: {exc}"[:300])
                try:
                    self._save_job(j)
                except Exception as exc2:                           # the remaining listeners still run
                    j["persist_error"] = f"{type(exc2).__name__}: {exc2}"[:300]

    def start_reconciliation(self, package_id: str, snapshot_id: str) -> dict:
        if self.uc042_root is None:
            raise ValueError("NO_ENGINE: the server was started without --uc042-root; reconciliation is unavailable")
        pkg = self.svc.load(package_id)
        if not pkg.active_snapshot_id or snapshot_id != pkg.active_snapshot_id:
            raise ValueError(f"NOT_ELIGIBLE: {snapshot_id} is not the active snapshot ({pkg.active_snapshot_id})")
        j = self._new_job("reconciliation", package_id, snapshot_id=snapshot_id, run_id=None, result=None)
        self._spawn(self._run_recon, j)
        return j

    def _run_recon(self, j: dict) -> None:
        """Fix8 D-recon-io: the run id, result and 'completed' are published together (_job_finish, under the case
        view lock) - never 'completed' first and the case refresh later - and any exception, including one while
        recording 'running', ends the job 'failed' with its error and trace."""
        try:
            self._job_running(j)
            with self.lock:
                rec = run_reconciliation(self.svc, j["package_id"], j["snapshot_id"], self.uc042_root, self.runs)
            terminal = {"state": "completed", "run_id": rec["run_id"],
                        "result": {"case_status": rec["result"]["case_status"], "outcomes": rec["result"]["outcomes"],
                                   "exceptions": len(rec["result"]["exceptions"]), "checks": rec["checks"]}}
        except Exception as exc:
            terminal = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"[:800],
                        "trace": traceback.format_exc()[-2000:]}
        self._job_finish(j, **terminal)

    # ============================================================================================ review support
    def column_profile(self, package_id: str, file_version_id: str) -> dict:
        """Sample values per SOURCE column, read from the stored original (SHA-256 verified) with the existing
        identification + CSV reader. Read-only; nothing is normalised or converted."""
        pkg = self.svc.load(package_id)
        v = pkg.versions[file_version_id]
        data = self.svc.evidence.read_original(v.source_sha256)
        if data is None or hashlib.sha256(data).hexdigest() != v.source_sha256:
            raise ValueError("SOURCE_UNAVAILABLE: the stored original is missing or does not match its SHA-256")
        if data[:5] == b"%PDF-":
            return {"kind": "PDF", "columns": []}
        ident = identify(data, v.original_filename)
        t = read_csv(data, ident.encoding, ident.delimiter)
        cols = []
        for i, h in enumerate(t.raw_headers):
            vals = [r.cells[i] if i < len(r.cells) else None for r in t.rows]
            present = [x for x in vals if x is not None]
            cols.append({"source_index": i, "source_position": i + 1, "source_header": h,
                         "samples": [x for x in present[:SAMPLE_ROWS]],
                         "rows": len(vals), "empty": sum(1 for x in present if x == ""),
                         "missing_cells": sum(1 for x in vals if x is None),
                         "distinct": len(set(present)) if len(present) <= 20000 else None,
                         "negative_values": sum(1 for x in present if x.strip().startswith("-")),
                         "first_line": 2})
        return {"kind": "CSV", "encoding": ident.encoding, "delimiter": ident.delimiter, "rows": len(t.rows),
                "columns": cols, "source_sha256": v.source_sha256, "intake_id": v.intake_id}


def _reviewer_get(self) -> Reviewer:
    """I-1: while a request (or a job started by one) runs as a user, the reviewer is that user with the server's
    reviewer role (or the user's configured reviewer_role) and kind; otherwise the server reviewer."""
    srv = self.__dict__["_server_reviewer"]
    a = identity.current()
    if a is None or a.system or a.user == srv.reviewer_id:
        return srv
    return Reviewer(reviewer_id=a.user, role=a.reviewer_role or srv.role, kind=srv.kind)


def _reviewer_set(self, r: Reviewer) -> None:
    self.__dict__["_server_reviewer"] = r


AppContext.reviewer = property(_reviewer_get, _reviewer_set)   # the dataclass __init__ assigns through the setter
