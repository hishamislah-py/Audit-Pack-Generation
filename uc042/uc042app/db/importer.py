"""Controlled import of file-backed application state (an earlier UC042_APP_STATE_DIR) into the database.

    python -m uc042app.admin import-file-state --from <state_dir> [--dry-run]

Rules: the source folder is only read (nothing is moved, rewritten or deleted); a record already in the database with
identical content is reported as unchanged; a record that exists with DIFFERENT content is reported as a conflict and
left as it is (never overwritten); everything else is inserted. Running it twice imports nothing the second time.
Controlled artefacts (packs, investigations, final packs) are not application state and are not touched."""
from pathlib import Path

from ..repositories.files import FileRepositories
from ..storage import read_json


class Report:
    def __init__(self):
        self.rows = []

    def add(self, kind, key, outcome, note=""):
        self.rows.append((kind, key, outcome, note))

    def count(self, outcome):
        return sum(1 for r in self.rows if r[2] == outcome)

    @property
    def conflicts(self):
        return [r for r in self.rows if r[2] == "CONFLICT"]


def _read_only_file_repositories(state_dir):
    state_dir = Path(state_dir)
    if not state_dir.is_dir():
        raise FileNotFoundError(f"{state_dir} is not a directory")
    for sub in ("jobs", "reviews", "final_pack_records", "registry"):  # FileRepositories would create missing folders
        if not (state_dir / sub).is_dir():
            raise FileNotFoundError(f"{state_dir} does not look like an application-state folder (no {sub}/)")
    return FileRepositories(state_dir)


def import_file_state(state_dir, target, dry_run=False):
    """Copy jobs, review sessions, decisions, previews, final-pack records and registry entries into `target`
    (SqlRepositories). Returns a Report; nothing in `state_dir` is modified."""
    src = _read_only_file_repositories(state_dir)
    report = Report()

    def put(kind, key, existing, record, insert):
        if existing is None:
            if not dry_run:
                insert()
            report.add(kind, key, "IMPORTED" if not dry_run else "WOULD_IMPORT")
        elif existing == record:
            report.add(kind, key, "UNCHANGED")
        else:
            report.add(kind, key, "CONFLICT", "database record differs; left unchanged")

    for job in src.jobs.list():
        put("job", job["job_id"], target.jobs.get(job["job_id"]), job, lambda job=job: target.jobs.create(job))

    for session in src.reviews.list():
        rid = session["review_id"]
        put("review", rid, target.reviews.get(rid), session, lambda session=session: target.reviews.create(session))
        existing_decisions = target.reviews.decisions(rid)
        file_decisions = src.reviews.decisions(rid)
        known = {d["review_decision_id"]: d for d in existing_decisions}
        if [d["review_decision_id"] for d in existing_decisions] != [d["review_decision_id"] for d in file_decisions][:len(existing_decisions)]:
            report.add("decisions", rid, "CONFLICT", "decision order differs; none imported for this review")
        else:
            for d in file_decisions:
                put("decision", d["review_decision_id"], known.get(d["review_decision_id"]), d,
                    lambda d=d, rid=rid: target.reviews.append_decision(rid, d))
        for pdir in sorted((Path(state_dir) / "reviews" / rid / "previews").glob("*")):
            meta, document = read_json(pdir / "meta.json"), read_json(pdir / "preview.json")
            if meta is None or document is None:
                report.add("preview", f"{rid}/{pdir.name}", "SKIPPED", "incomplete preview folder")
                continue
            have = target.reviews.get_preview(rid, pdir.name)
            put("preview", f"{rid}/{pdir.name}", None if have == (None, None) else have, (meta, document),
                lambda rid=rid, pid=pdir.name, meta=meta, document=document: target.reviews.save_preview(rid, pid, meta, document))

    for rec in src.final_packs.list():
        key = rec["review_decision_id"]
        put("final_pack_record", key, target.final_packs.get(key), rec, lambda rec=rec: target.final_packs.create(rec))

    existing = {e["seq"]: e for e in target.registry.entries()}
    for entry in src.registry.entries():
        put("registry", f"seq {entry['seq']} {entry['investigation_id']}", existing.get(entry["seq"]), entry,
            lambda entry=entry: target.registry.append(entry))
    return report
