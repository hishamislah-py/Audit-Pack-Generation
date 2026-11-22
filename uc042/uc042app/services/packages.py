"""ZIP submission packages across every period, and one submission's status (read-only), plus the package's display name.

A package is an upload batch of origin ZIP_SUBMISSION (legacy UPLOAD batches and POC scenario imports are never listed).
Submissions have no table of their own: each is recorded in the batch summary ("submissions") and on its audit run
(processing_runs.result.submission_id). Everything here is derived from those records, the submission's own investigation
jobs (AutoInvestigationService.own_jobs), its scoped analyst decisions, its review sessions and its final packs. Nothing
is written except the display name (summary["package"]["display_name"]; no schema change) and its activity event."""
import re

from uc042lib.period import PeriodConfig, PeriodError

from ..errors import Conflict, NotFound
from .monthly import (BATCH_ID_RE, PACKAGE_INCOMPLETE, PACKAGE_REJECTED, SUBMISSION_ID_RE, ZIP_ORIGIN, _check,
                      package_display_name)
from .reviews import ACTIVE_STATES

STAGES = ("PACKAGE_REJECTED", "PACKAGE_INCOMPLETE", "READY_TO_SUBMIT", "AUDIT_RUNNING", "AUDIT_FAILED", "AI_INVESTIGATING",
          "FINDINGS_TO_REVIEW", "READY_FOR_FINAL_REVIEW", "FINAL_REVIEW_IN_PROGRESS", "FINAL_PACK_GENERATED")


def derived_display_name(zip_name, batch_id):
    """A readable name from the ZIP file name ("september_2026-09.zip" -> "September 2026 09"), used when none is set."""
    stem = re.sub(r"\.zip$", "", str(zip_name or ""), flags=re.IGNORECASE)
    stem = re.sub(r"[_\-.\s]+", " ", stem).strip()
    if not stem:
        return f"Package {batch_id[-6:]}"
    return stem[0].upper() + stem[1:]


class PackageService:
    def __init__(self, monthly, auto_investigations, investigation_reviews, reviews, final_packs):
        self.monthly, self.auto, self.decisions = monthly, auto_investigations, investigation_reviews
        self.reviews, self.final_packs = reviews, final_packs

    # ---------------------------------------------------------------- reads
    def _finals_by_submission(self):
        out = {}
        for f in self.final_packs.list():
            if f.get("submission_id"):
                out.setdefault(f["submission_id"], []).append(f)
        for v in out.values():
            v.sort(key=lambda f: f["generated_at"])
        return out

    def list(self):
        """Every ZIP package of every period, newest first."""
        m = self.monthly
        m._require()
        finals = self._finals_by_submission()
        out = [self._item(b, finals) for p in m.repos.periods.list() for b in m.repos.uploads.batches(p["period_id"])
               if b.get("origin") == ZIP_ORIGIN]
        out.sort(key=lambda x: (x["created_at"], x["batch_id"]), reverse=True)
        return out

    def _batch(self, batch_id):
        m = self.monthly
        m._require()
        _check(BATCH_ID_RE, batch_id, "batch id")
        batch = m.repos.uploads.batch(batch_id)
        if batch is None:
            raise NotFound("upload batch not found")
        if batch.get("origin") != ZIP_ORIGIN:
            raise Conflict(f"{batch_id} is not a ZIP submission package", code="NOT_A_PACKAGE")
        return batch

    def item(self, batch_id):
        return self._item(self._batch(batch_id), self._finals_by_submission())

    @staticmethod
    def display_name(batch):
        """(display_name, source): the stored name ("STORED") or the one derived from the ZIP file name ("DERIVED")."""
        pkg = (batch.get("summary") or {}).get("package") or {}
        if pkg.get("display_name"):
            return pkg["display_name"], "STORED"
        return derived_display_name(pkg.get("zip_name"), batch["batch_id"]), "DERIVED"

    @staticmethod
    def _gate(batch):
        pkg = (batch.get("summary") or {}).get("package") or {}
        g = pkg.get("gate") or {}
        total = g.get("required_total")
        if total is None:
            try:
                total = len(PeriodConfig.from_id(batch["period_id"]).required_ids)
            except (PeriodError, ValueError):
                total = 0
        return {"passed": bool(g.get("passed")), "missing_required": list(g.get("missing_required") or []),
                "present_required": len(g.get("present_required") or []), "required_total": total,
                "reason": g.get("reason") or (pkg.get("error") or {}).get("message") or None}

    def _item(self, batch, finals):
        pkg = (batch.get("summary") or {}).get("package") or {}
        subs = (batch.get("summary") or {}).get("submissions") or []
        name, source = self.display_name(batch)
        gate = self._gate(batch)
        latest = self._submission(batch, subs[-1], finals) if subs else None
        if batch["status"] == PACKAGE_REJECTED:
            stage = "PACKAGE_REJECTED"
        elif batch["status"] == PACKAGE_INCOMPLETE or not gate["passed"]:
            stage = "PACKAGE_INCOMPLETE"
        else:
            stage = latest["stage"] if latest else "READY_TO_SUBMIT"
        return {"batch_id": batch["batch_id"], "display_name": name, "display_name_source": source,
                "zip_name": pkg.get("zip_name"), "zip_sha256": pkg.get("zip_sha256"), "period_id": batch["period_id"],
                "created_at": batch["created_at"], "status": batch["status"], "gate": gate, "document_count": batch.get("file_count") or 0,
                "submissions_count": len(subs), "submission_ids": [s["submission_id"] for s in reversed(subs)],
                "latest_submission": latest, "stage": stage}

    def _submission(self, batch, entry, finals):
        """One submission's status from its audit run, its own jobs and investigations, its scoped decisions, its review
        session and its final packs."""
        run = self.monthly.repos.runs.get(entry["run_id"]) or {}
        res = run.get("result") or {}
        sid, pack_id, status = entry["submission_id"], res.get("pack_id"), run.get("status")
        investigations = {"total": 0, "completed": 0, "failed": 0, "running": 0, "not_started": 0}
        decisions = {"accepted": 0, "rejected": 0, "pending": 0}
        review = final = None
        exception_count = res.get("exceptions") if status == "SUCCEEDED" else None
        if status == "SUCCEEDED" and pack_id:
            jobs = self.auto.submission_jobs(run) if self.auto is not None else {}
            produced = self.auto.submission_investigations(run) if self.auto is not None else {}
            for e in set(jobs) | set(produced):
                j = jobs.get(e)
                if j is not None and j["status"] in ("QUEUED", "RUNNING"):
                    investigations["running"] += 1
                elif e in produced:
                    investigations["completed"] += 1
                elif j is not None and j["status"] in ("FAILED", "INTERRUPTED"):
                    investigations["failed"] += 1
            total = exception_count if isinstance(exception_count, int) else len(set(jobs) | set(produced))
            investigations["total"] = total
            investigations["not_started"] = max(0, total - investigations["running"] - investigations["completed"] - investigations["failed"])
            active = self.decisions.active_for_pack(pack_id, sid) if self.decisions is not None else {}
            for inv in produced.values():
                d = (active.get(inv) or {}).get("decision")
                decisions["accepted" if d == "ACCEPT" else "rejected" if d == "REJECT" else "pending"] += 1
            session = self.reviews.submission_session(pack_id, sid) if self.reviews is not None else None
            review = {"review_id": session["review_id"], "status": session["status"]} if session else None
            mine = finals.get(sid) or []
            if mine:
                f = mine[-1]
                final = {"final_pack_id": f["final_pack_id"], "generated_at": f["generated_at"], "version": f.get("version")}
        if status in ("QUEUED", "RUNNING"):
            stage = "AUDIT_RUNNING"
        elif status != "SUCCEEDED" or not pack_id:
            stage = "AUDIT_FAILED"
        elif final is not None or (review and review["status"] == "GENERATED"):
            stage = "FINAL_PACK_GENERATED"
        elif review and review["status"] == "GENERATING":
            stage = "FINAL_REVIEW_IN_PROGRESS"
        elif investigations["running"]:
            stage = "AI_INVESTIGATING"
        elif decisions["pending"]:
            stage = "FINDINGS_TO_REVIEW"
        elif review and review["status"] in ACTIVE_STATES:
            stage = "FINAL_REVIEW_IN_PROGRESS"
        else:
            stage = "READY_FOR_FINAL_REVIEW"
        return {"submission_id": sid, "run_id": entry["run_id"], "run_status": status, "run_error": run.get("error") or "",
                "submitted_at": entry.get("submitted_at"), "submitted_by": entry.get("submitted_by"),
                "completed_at": run.get("completed_at"), "pack_id": pack_id, "outcome": res.get("outcome"),
                "exception_count": exception_count,
                "auto_investigation_status": (res.get("auto_investigation") or {}).get("status"),
                "investigations": investigations, "decisions": decisions, "review": review, "final_pack": final, "stage": stage}

    def submission(self, submission_id):
        """One submission's status plus its package (batch_id, display_name, period_id, zip_name)."""
        m = self.monthly
        m._require()
        _check(SUBMISSION_ID_RE, submission_id, "submission id")
        run = m.submission_run(submission_id)
        if run is None:
            raise NotFound("submission not found")
        batch = m.repos.uploads.batch(run["batch_id"])
        if batch is None:
            raise NotFound("submission not found")
        entry = next((s for s in (batch.get("summary") or {}).get("submissions") or [] if s["submission_id"] == submission_id),
                     {"submission_id": submission_id, "run_id": run["run_id"], "submitted_at": run.get("created_at"),
                      "submitted_by": run.get("created_by")})
        name, source = self.display_name(batch)
        pkg = (batch.get("summary") or {}).get("package") or {}
        return dict(self._submission(batch, entry, self._finals_by_submission()), batch_id=batch["batch_id"],
                    display_name=name, display_name_source=source, period_id=batch["period_id"], zip_name=pkg.get("zip_name"))

    # ---------------------------------------------------------------- the display name (the only write)
    def rename(self, batch_id, display_name):
        """Set (or, with an empty name, clear) the package's display name. Returns the package item."""
        m = self.monthly
        name = package_display_name(display_name)
        self._batch(batch_id)
        with m._lock:
            batch = m.repos.uploads.batch(batch_id)
            summary = dict(batch.get("summary") or {})
            package = dict(summary.get("package") or {})
            previous = package.get("display_name")
            if name:
                package["display_name"] = name
            else:
                package.pop("display_name", None)
            summary["package"] = package
            m.repos.uploads.update_batch(batch_id, {"summary": summary})
        m._activity("PACKAGE_RENAMED", "batch", batch_id, period_id=batch["period_id"], previous_display_name=previous,
                    display_name=name)
        return self.item(batch_id)
