"""Analyst review of AI investigations, in the Exception Workspace: the analyst ACCEPTS or REJECTS one published
investigation, for the exact findings it holds (findings SHA-256 and schema version).

  ACCEPT   an optional comment; the investigation's AI content may then be reported in the final audit pack.
  REJECT   a mandatory reason for rejection, stored exactly as written (never trimmed, reworded or summarised). The AI
           content is not reported; the reason is the review content for that exception in the final audit pack.

Decisions are append-only: a changed decision is a new record with the next revision and a reference to the decision it
supersedes; the latest is the active decision. The caller states the revision it decided on (expected_revision), so a
decision made on an out-of-date view is refused (409 REVIEW_DECISION_CONFLICT) instead of silently overriding a newer one.

A decision never changes the investigation artefact, the deterministic pack, an engine result or the exception's status
(OPEN / UNRESOLVED): it is a separate record. The final review reads the active decisions (ReviewService), and a changed
decision makes an earlier preview stale.

The exception's review history (exception_history) is read-only and assembled from the records the application already
keeps: investigation jobs, published and unpublished investigation artefacts, and these decisions. It is application data
and never part of a final audit pack."""
import re
from datetime import datetime, timezone

from uc042lib.final_pack.render_pdf import unsupported_in_text
from uc042lib.final_pack.sources import load_bundle
from uc042lib.investigation.persistence import verify_published

from .. import ids
from ..clock import now_iso, utc_iso
from ..errors import Conflict, IntegrityFailure, InvalidInput, NotFound
from ..repositories.base import ConcurrentUpdate
from .ai_authorization import period_of

ACCEPT, REJECT = "ACCEPT", "REJECT"
DECISIONS = (ACCEPT, REJECT)
MAX_TEXT = 8000
PENDING = "PENDING"
_NOT_PUBLISHED_AT = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2})(\d{2})(\d{2})([+-]\d{4}|Z)?")


def _sort_key(at):
    """Timestamps of different records (UTC ISO strings, some with milliseconds) in one chronological order."""
    try:
        dt = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _seconds_apart(a, b):
    """Absolute seconds between two ISO timestamps, or None when either is missing or malformed."""
    try:
        return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds())
    except (TypeError, ValueError):
        return None


def _within(a, b, seconds):
    """Two ISO timestamps no more than `seconds` apart (False when either is missing or malformed)."""
    d = _seconds_apart(a, b)
    return d is not None and d <= seconds


LEGACY_MATCH_SECONDS = 10  # time-based fallback, only for job events recorded before jobs named their record (DR-10)


def _not_published_at(record_name):
    """The time an unpublished attempt was stored, from its record name (persistence: <time without colons>-<hash>.json)."""
    m = _NOT_PUBLISHED_AT.match(record_name or "")
    if not m:
        return ""
    tz = m.group(4) or "+0000"
    return f"{m.group(1)}:{m.group(2)}:{m.group(3)}{tz[:3]}:{tz[3:]}" if tz != "Z" else f"{m.group(1)}:{m.group(2)}:{m.group(3)}+00:00"


class InvestigationReviewService:
    def __init__(self, settings, repo, packs, investigations, runner, locks, activity=None):
        self.settings, self.repo, self.packs, self.investigations = settings, repo, packs, investigations
        self.runner, self.locks, self.activity = runner, locks, activity

    # ---------------------------------------------------------------- reads
    # A decision's scope (migration 0006): None = the legacy, period-level decisions; a submission ID = the decisions made in
    # that independent ZIP submission's review. Scopes never mix: a submission never inherits another scope's decision.
    submission_resolver = None  # set by Services: submission_id -> {exception_id: investigation_id} of that submission

    @staticmethod
    def _scoped(rows, submission_id):
        return [r for r in rows if r.get("submission_id") == submission_id]

    def history(self, investigation_id, submission_id=None):
        """Every decision on one investigation in one scope, oldest first, with the active (latest) one marked."""
        ids.check("investigation_id", investigation_id)
        rows = self._scoped(self.repo.list(investigation_id=investigation_id), submission_id)
        return [self.view(r, active=(i == len(rows) - 1)) for i, r in enumerate(rows)]

    def latest(self, investigation_id, submission_id=None):
        rows = self._scoped(self.repo.list(investigation_id=investigation_id), submission_id)
        return self.view(rows[-1], active=True) if rows else None

    def active_for_pack(self, pack_id, submission_id=None):
        """{investigation_id: the active decision} for every reviewed investigation of a pack, in one scope."""
        out = {}
        for r in self._scoped(self.repo.list(pack_id=pack_id), submission_id):
            out[r["investigation_id"]] = r  # oldest first: the last one per investigation wins
        return {k: self.view(v, active=True) for k, v in out.items()}

    def _check_submission(self, submission_id, investigation_id):
        """A submission-scoped decision is accepted only for an investigation produced for that submission."""
        if not isinstance(submission_id, str) or not re.match(r"^SUB-[0-9a-f]{24}$", submission_id):
            raise InvalidInput("invalid submission id", code="INVALID_ID")
        produced = self.submission_resolver(submission_id) if self.submission_resolver else None
        if produced is None:
            raise NotFound("submission not found")
        return produced

    @staticmethod
    def _scope_of_findings(findings, investigation_id, submission_id, produced):
        """Decisions follow the investigation's own scope: a submission's investigation (findings.execution) is decided
        only in that submission's review; a pack-level / legacy investigation only at period level."""
        owner = (findings.get("execution") or {}).get("submission_id")
        if submission_id is None:
            if owner:
                raise Conflict(f"{investigation_id} belongs to ZIP submission {owner}: record the decision in that submission's "
                               "review", code="DECISION_BELONGS_TO_SUBMISSION", extra={"submission_id": owner})
            return
        if owner != submission_id and not (owner is None and investigation_id in (produced or {}).values()):
            raise InvalidInput(f"{investigation_id} was not produced for submission {submission_id}; a submission's review "
                               "only decides on its own investigations", code="INVESTIGATION_NOT_IN_SUBMISSION")

    @staticmethod
    def view(r, active=False):
        return {"analyst_review_id": r["analyst_review_id"], "period_id": r["period_id"], "pack_id": r["pack_id"],
                "exception_id": r["exception_id"], "investigation_id": r["investigation_id"],
                "findings_sha256": r["findings_sha256"], "findings_schema_version": r["findings_schema_version"],
                "decision": r["decision"], "comment": r["comment"], "rejection_reason": r["rejection_reason"],
                "reviewer": {"user_id": r["reviewer_id"], "display_name": r["reviewer_name"]}, "decided_at": utc_iso(r["decided_at"]),
                "revision": r["revision"], "supersedes_review_id": r.get("supersedes_review_id"), "active": active,
                "submission_id": r.get("submission_id"),  # None: a legacy (period-level) decision
                # characters the audit PDF's fonts cannot draw (the final pack is then blocked, never substituted)
                "pdf_unsupported_characters": unsupported_in_text(r["comment"] + r["rejection_reason"])}

    @staticmethod
    def library_review(v):
        """The decision as the final-pack library's AnalystReview input."""
        return {k: v[k] for k in ("analyst_review_id", "investigation_id", "exception_id", "decision", "findings_sha256",
                                  "findings_schema_version", "comment", "rejection_reason", "reviewer", "decided_at", "revision")}

    # Owner decision (Phase B): once a submission's final pack is generated (or being generated), that WHOLE submission's
    # analyst decisions are locked. Set by Services: (pack_id, submission_id) -> review sessions GENERATED / GENERATING.
    locked_sessions = None

    def _refuse_if_locked(self, pack_id, submission_id):
        sessions = self.locked_sessions(pack_id, submission_id) if self.locked_sessions is not None else []
        if not sessions:
            return
        generated = [s for s in sessions if s["status"] == "GENERATED" and s.get("final_pack_id")]
        s = generated[-1] if generated else sessions[-1]
        what = (f"final pack {s['final_pack_id']} has been generated" if s.get("final_pack_id")
                else "a final pack is being generated")
        raise Conflict(f"the analyst decisions of submission {submission_id} are locked: {what} from its review {s['review_id']}",
                       code="DECISION_LOCKED_FINAL_PACK_GENERATED",
                       extra={"final_pack_id": s.get("final_pack_id"), "review_id": s["review_id"], "review_status": s["status"]})

    # ---------------------------------------------------------------- the decision
    def record(self, investigation_id, decision, comment="", rejection_reason="", expected_revision=None, submission_id=None):
        """submission_id: the decision is made in that ZIP submission's review and counts only there (migration 0006);
        None keeps the legacy, period-level behaviour unchanged."""
        ids.check("investigation_id", investigation_id)
        produced = self._check_submission(submission_id, investigation_id) if submission_id is not None else None
        if decision not in DECISIONS:
            raise InvalidInput("decision must be ACCEPT or REJECT", code="DECISION_INVALID")
        if not isinstance(comment, str) or not isinstance(rejection_reason, str):
            raise InvalidInput("comment and rejection_reason must be text", code="DECISION_INVALID")
        if len(comment) > MAX_TEXT or len(rejection_reason) > MAX_TEXT:
            raise InvalidInput(f"the comment or reason may have at most {MAX_TEXT} characters", code="TEXT_TOO_LONG")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise InvalidInput("expected_revision is required: the review revision the decision was made on (0 for the first)",
                               code="REVISION_REQUIRED")
        if decision == REJECT:
            if not rejection_reason.strip():  # enforced here, whatever the client does
                raise InvalidInput("a REJECT decision requires a reason for rejection; an empty or blank reason is not accepted",
                                   code="REJECTION_REASON_REQUIRED")
            # An optional analyst comment is kept separately from the mandatory reason (both exactly as written); the
            # reason is what the final pack reports as the reason for rejection, the comment is shown apart from it.
            comment = comment if comment.strip() else ""
        else:
            if rejection_reason.strip():
                raise InvalidInput("an ACCEPT decision has no reason for rejection", code="REASON_NOT_ALLOWED")
            rejection_reason = ""
            comment = comment if comment.strip() else ""
        inv_dir = self.investigations.locate(investigation_id)  # 404 if it is not a published investigation
        pack_id, exception_id = inv_dir.parent.parent.name, inv_dir.parent.name
        with self.locks.hold(pack_id, busy_code="PACK_BUSY"):  # serialised with the final review's GENERATE
            if submission_id is not None:
                self._refuse_if_locked(pack_id, submission_id)
            problems = verify_published(inv_dir)
            if problems:
                raise IntegrityFailure("the investigation artefact does not verify; it cannot be reviewed: " + "; ".join(problems[:3]),
                                       code="ARTEFACT_UNVERIFIED")
            bundle = load_bundle(inv_dir)
            f = bundle["findings"]
            pack = self.packs.load(pack_id)
            if f.get("pack_id") != pack_id or f.get("exception_id") != exception_id or \
                    f.get("pack_content_sha256") != pack["audit_trail"]["pack_content_sha256"]:
                raise IntegrityFailure("the investigation does not belong to this pack and exception", code="ARTEFACT_UNVERIFIED")
            self._scope_of_findings(f, investigation_id, submission_id, produced)
            previous = self.latest(investigation_id, submission_id)  # the active decision in THIS scope only
            current = previous["revision"] if previous else 0
            if expected_revision != current:
                raise Conflict(f"the review of {investigation_id} has changed (revision {current}); reload it and decide again",
                               code="REVIEW_DECISION_CONFLICT", extra={"current_revision": current, "current": previous})
            rec = {"analyst_review_id": ids.new_id("AR"), "period_id": period_of(pack_id), "pack_id": pack_id,
                   "exception_id": exception_id, "investigation_id": investigation_id, "findings_sha256": bundle["findings_sha256"],
                   "findings_schema_version": (f.get("model_metadata") or {}).get("findings_schema_version") or "",
                   "decision": decision, "comment": comment, "rejection_reason": rejection_reason,
                   "reviewer_id": self.settings.analyst_id, "reviewer_name": self.settings.analyst_name, "decided_at": now_iso(),
                   "revision": current + 1, "supersedes_review_id": previous["analyst_review_id"] if previous else None,
                   **({"submission_id": submission_id} if submission_id is not None else {})}
            try:
                stored = self.repo.append(rec, current)
            except ConcurrentUpdate:
                raise Conflict(f"another decision on {investigation_id} was recorded at the same time; reload it and decide again",
                               code="REVIEW_DECISION_CONFLICT") from None
        out = self.view(stored, active=True)
        if self.activity is not None:
            self.activity.append({"at": out["decided_at"], "actor": self.settings.analyst_id,
                                  "action": "AI_REVIEW_ACCEPTED" if decision == ACCEPT else "AI_REVIEW_REJECTED",
                                  "entity_type": "investigation", "entity_id": investigation_id,
                                  "details": {"period_id": out["period_id"], "pack_id": pack_id, "exception_id": exception_id,
                                              "analyst_review_id": out["analyst_review_id"], "revision": out["revision"],
                                              "supersedes_review_id": out["supersedes_review_id"], "decision": decision,
                                              "submission_id": submission_id}})
        return out

    # ---------------------------------------------------------------- the exception's review history (read-only)
    def exception_history(self, pack_id, exception_id):
        """Chronological, read-only events of one exception's AI investigations and the analyst's decisions on them."""
        pack = self.packs.load(pack_id)
        self.packs.exception(pack, exception_id)
        events = []

        def add(at, kind, label, investigation_id=None, actor=None, **details):
            events.append({"at": at, "kind": kind, "label": label, "actor": actor, "pack_id": pack_id, "exception_id": exception_id,
                           "investigation_id": investigation_id, "details": details})
        for j in self.runner.repo.list(pack_id=pack_id, exception_id=exception_id):
            if j["operation"] != "INVESTIGATION":
                continue
            ctx = {"job_id": j["job_id"], "authorization_id": (j.get("inputs") or {}).get("authorization_id"), "retry_of": j.get("retry_of"),
                   "submission_id": ((j.get("inputs") or {}).get("execution") or {}).get("submission_id")}
            add(j["submitted_at"], "AI_INVESTIGATION_REQUESTED", "AI investigation requested", actor=j.get("submitted_by"), **ctx)
            if j.get("started_at"):
                add(j["started_at"], "AI_INVESTIGATION_STARTED", "AI investigation started", **ctx)
            if j.get("completed_at"):
                result = j.get("result") or {}
                ok = j["status"] == "COMPLETED"
                named = {"not_published_record": result["not_published_record"]} if "not_published_record" in result else {}
                add(j["completed_at"], "AI_INVESTIGATION_COMPLETED" if ok else f"AI_INVESTIGATION_{j['status']}",
                    "AI investigation completed" if ok else f"AI investigation {j['status'].lower()}",
                    investigation_id=result.get("investigation_id"), error=j.get("error_summary") or "",
                    validation_status=result.get("validation_status"), **named, **ctx)
        found = self.investigations.published(pack, exception_id)
        for p in found["published"]:
            add(p.get("investigated_at") or "", "AI_INVESTIGATION_PUBLISHED", "AI investigation published", investigation_id=p["investigation_id"],
                submission_id=p.get("submission_id"),
                investigation_mode=p.get("investigation_mode"), findings_schema_version=p.get("findings_schema_version"),
                validation_status=p.get("validation_status"), overall_evidence_assessment=p.get("overall_evidence_assessment"),
                eligible=p.get("eligible"))
        # DEF-09 / DR-10: the stored record of an attempt whose job already reported the failure is the same event (one
        # line). Exact first: a job that names its record (not_published_record) matches that record only. Fallback for
        # legacy job events that name none: within LEGACY_MATCH_SECONDS, nearest first, one record per job event.
        failed_events = [e for e in events if e["kind"] in ("AI_INVESTIGATION_FAILED", "AI_INVESTIGATION_INTERRUPTED")]
        by_record = {e["details"]["not_published_record"]: e for e in failed_events if e["details"].get("not_published_record")}
        legacy = [e for e in failed_events if "not_published_record" not in e["details"]]
        records = list(found["not_published"])
        match = {}  # index of record -> job event
        for i, a in enumerate(records):
            if a.get("record") in by_record:
                match[i] = by_record[a["record"]]
        pairs = []
        for i, a in enumerate(records):
            if i in match or a.get("record") in by_record:
                continue
            at = _not_published_at(a.get("record"))
            for k, e in enumerate(legacy):
                d = _seconds_apart(e["at"], at)
                if d is not None and d <= LEGACY_MATCH_SECONDS:
                    pairs.append((d, i, k))
        used = set()
        for d, i, k in sorted(pairs):
            if i not in match and k not in used:
                match[i] = legacy[k]
                used.add(k)
                legacy[k]["details"]["not_published_record"] = records[i].get("record")
        for i, a in enumerate(records):
            same = match.get(i)
            if same is not None:
                if same["details"].get("validation_status") is None:  # assign when the job's own value is None
                    same["details"]["validation_status"] = a.get("validation_status")
                continue
            add(_not_published_at(a.get("record")), "AI_INVESTIGATION_NOT_PUBLISHED", "AI investigation failed or was rejected by validation",
                investigation_status=a.get("investigation_status"), validation_status=a.get("validation_status"),
                failure_reason=a.get("failure_reason", ""))
        rows = self.repo.list(pack_id=pack_id, exception_id=exception_id)
        latest = {}  # the active decision per (investigation, submission scope): scopes never supersede each other
        for r in rows:
            latest[(r["investigation_id"], r.get("submission_id"))] = r["analyst_review_id"]
        for r in rows:
            v = self.view(r, active=latest[(r["investigation_id"], r.get("submission_id"))] == r["analyst_review_id"])
            add(v["decided_at"], f"ANALYST_DECISION_{v['decision']}",
                "Analyst accepted the AI investigation" if v["decision"] == ACCEPT else "Analyst rejected the AI investigation",
                investigation_id=v["investigation_id"], actor=v["reviewer"]["user_id"], reviewer=v["reviewer"], decision=v["decision"],
                comment=v["comment"], rejection_reason=v["rejection_reason"], analyst_review_id=v["analyst_review_id"],
                revision=v["revision"], supersedes_review_id=v["supersedes_review_id"], active=v["active"],
                findings_sha256=v["findings_sha256"], findings_schema_version=v["findings_schema_version"],
                submission_id=v["submission_id"])
        events.sort(key=lambda e: _sort_key(e["at"]))
        # pending: no decision in the investigation's OWN scope (its submission, or period level for a legacy artefact)
        pending = [p["investigation_id"] for p in found["published"] if (p["investigation_id"], p.get("submission_id")) not in latest]
        by_submission = {}
        for inv, sub in latest:
            if sub:
                by_submission.setdefault(sub, {})[inv] = self.latest(inv, sub)
        return {"pack_id": pack_id, "exception_id": exception_id, "events": events,
                "active_decisions": {inv: self.latest(inv) for inv, sub in latest if sub is None},
                "active_submission_decisions": by_submission, "pending_investigations": pending,
                "exception_status": "UNRESOLVED",
                "note": "Read-only application history. It is not part of the final audit pack; an analyst decision never "
                        "resolves the exception or changes the investigation."}
