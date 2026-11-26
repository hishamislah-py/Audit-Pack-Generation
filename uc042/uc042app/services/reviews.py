"""Human review sessions (spec 06 §6): selections, readiness, closing summary + preview (a background job), and the
append-only HOLD / GENERATE decisions. All review logic that exists in the library is reused: Selection validation,
build_review_snapshot (verification and eligibility), generate_closing_summary / unavailable_closing_summary,
assemble_preview, ReviewRecord, and final assembly/publication via FinalPackService.

State machine: OPEN -> ON_HOLD -> OPEN ...; OPEN -> GENERATING -> GENERATED | GENERATION_FAILED -> OPEN.
One active (not GENERATED) session per pack. A GENERATE decision must carry the snapshot hash of the current preview,
and the inputs are re-verified at decision time; any change means 409 PREVIEW_STALE.
"""
import hashlib
import logging

from pydantic import ValidationError

from uc042lib.final_pack import (ClosingSummary, ClosingSummaryError, FinalPackInputError, FinalPackValidationError, Reviewer,
                                 ReviewRecord, Selection, build_review_snapshot, assemble_preview, closing_summary_required,
                                 generate_closing_summary, not_required_closing_summary, summary_sha256,
                                 unavailable_closing_summary)
from uc042lib.final_pack.model import ACKNOWLEDGEMENT_TEXT, SUMMARY_PROMPT_VERSION, SUMMARY_SCHEMA_VERSION, PriorDecision
from uc042lib.final_pack.render_pdf import PdfGlyphError, unsupported_characters
from uc042lib.investigation.llm import LLMConfigurationError, redact
from uc042lib.pack.model import canonical

from .. import ids
from ..errors import AppError, Conflict, InvalidInput, NotFound
from ..jobs import safe_error
from ..repositories import ConcurrentUpdate
from ..clock import now_iso
from .ai_authorization import AUTHORIZED, CLOSING_SUMMARY, period_of
from .monthly import SUBMISSION_ID_RE

log = logging.getLogger("uc042app.reviews")
ACTIVE_STATES = ("OPEN", "ON_HOLD", "GENERATING", "GENERATION_FAILED")
EDITABLE_STATES = ("OPEN", "ON_HOLD", "GENERATION_FAILED")


def summary_failure_record(error, investigator):
    """The stored record of a failed closing summary (review DR-09): kind and redacted detail as before, plus the billed
    telemetry when a request was made, in the same model_metadata shape as a successful summary's (attempts,
    provider_response with per-request responses, usage, provider, model, simulated, prompt and schema versions).
    Telemetry source: the LLMCallError the summary error wraps (provider / transport failure); for an output refused by
    validation (invalid_summary) the call succeeded and was billed, so the investigator's last structured request. A
    failure before any request (configuration, unsupported provider) records no telemetry; nothing is ever reused."""
    kind = getattr(error, "kind", "configuration")
    telemetry = getattr(error.__cause__, "telemetry", None) if error.__cause__ is not None else None
    if telemetry is None and kind == "invalid_summary":
        telemetry = getattr(investigator, "last_structured_request", None)
    meta = None
    if telemetry:
        meta = dict(telemetry, provider=getattr(investigator, "provider", "") or "", model=getattr(investigator, "model", "") or "",
                    simulated=getattr(investigator, "simulated", False), prompt_version=SUMMARY_PROMPT_VERSION,
                    summary_schema_version=SUMMARY_SCHEMA_VERSION)
    return {"kind": kind, "detail": redact(str(error))[:500], "telemetry_available": meta is not None, "model_metadata": meta}


def _selection_error(e):
    msgs = [err.get("msg", "") for err in e.errors()] if isinstance(e, ValidationError) else [str(e)]
    return "; ".join(m.removeprefix("Value error, ") for m in msgs)[:500]


class ReviewService:
    def __init__(self, settings, repos, packs, investigations, final_packs, runner, locks, investigator_factory=None,
                 ai_authorizations=None, analyst_reviews=None):
        self.settings, self.repo, self.packs, self.investigations = settings, repos.reviews, packs, investigations
        self.final_packs, self.runner, self.locks = final_packs, runner, locks
        self.investigator_factory = investigator_factory
        self.activity = repos.activity  # None without a database (the activity log is a database feature)
        self.ai_authorizations = ai_authorizations
        # The analyst's ACCEPT / REJECT decision per investigation (InvestigationReviewService). Only an ACCEPTED
        # investigation's AI content is reported; a REJECTED one is reported by the analyst's reason; a pending one blocks.
        self.analyst_reviews = analyst_reviews
        self.auto_investigations = None  # set by Services: each exception's investigation status for the readiness checklist
        self.monthly = None  # set by Services: the audit run of a ZIP submission (independent submissions, 17 Nov 2026)

    # ---------------------------------------------------------------- analyst reviews of the selected investigations
    def _active_reviews(self, pack_id, submission_id=None):
        """Active analyst decisions in one scope: a submission's review sees only that submission's decisions (migration
        0006); a legacy review (submission_id None) sees the legacy decisions exactly as before."""
        return self.analyst_reviews.active_for_pack(pack_id, submission_id) if self.analyst_reviews is not None else {}

    def _produced(self, session):
        """{exception_id: investigation_id} produced for the session's submission, or None for a legacy review."""
        sid = session.get("submission_id")
        if not sid:
            return None
        run = self.monthly.submission_run(sid) if self.monthly is not None else None
        return self.auto_investigations.submission_investigations(run) if run is not None and self.auto_investigations else {}

    def _reviews_fingerprint(self, session, active=None):
        """The active decision on each INCLUDED investigation: any change (a new decision, a changed one) makes a preview
        built before it stale."""
        active = self._active_reviews(session["pack_id"], session.get("submission_id")) if active is None else active
        decided = {s["investigation_id"]: (active[s["investigation_id"]]["analyst_review_id"], active[s["investigation_id"]]["decision"])
                   if s["investigation_id"] in active else None for s in session["selections"] if s["inclusion"] == "INCLUDED"}
        return hashlib.sha256(canonical(decided).encode("utf-8")).hexdigest()

    def _activity(self, action, session, **details):
        """Review lifecycle events in the activity log, with the period, pack and review they concern."""
        if self.activity is not None:
            self.activity.append({"at": now_iso(), "actor": self.settings.analyst_id, "action": action, "entity_type": "review",
                                  "entity_id": session["review_id"],
                                  "details": dict(details, period_id=period_of(session["pack_id"]), pack_id=session["pack_id"],
                                                  review_id=session["review_id"])})

    # ---------------------------------------------------------------- sessions
    def get(self, review_id):
        ids.check("review_id", review_id)
        session = self.repo.get(review_id)
        if session is None:
            raise NotFound("review session not found")
        return session

    def _save(self, session, **changes):
        try:
            return self.repo.save(dict(session, updated_at=now_iso(), **changes), session["revision"])
        except ConcurrentUpdate:
            raise Conflict("the review session was changed by another request; reload it", code="REVIEW_CONFLICT") from None

    def open(self, pack_id, submission_id=None):
        """Return (session, created). An existing active session for the pack is returned instead of a second one. This is
        only ever called by the explicit "open a review" action (POST): reading or navigating never creates a session.

        submission_id: the review of one independent ZIP submission (its audit run produced this pack). The session records
        the submission, its run and batch; its selections and analyst decisions are limited to that submission's own
        investigations. Active reviews are keyed by (pack, submission): another submission's review of the same
        content-addressed pack, whatever its state (ON_HOLD, GENERATION_FAILED...), never blocks this one. Writes stay
        serialised per pack (the pack lock). A period-level review (no submission) of a pack produced only by ZIP
        submissions is refused: its final pack would belong to no submission."""
        trace = self._submission_trace(pack_id, submission_id) if submission_id is not None else {}
        if submission_id is None and self.monthly is not None and self.monthly.is_submission_only_pack(pack_id):
            raise Conflict("this pack was produced by ZIP submissions: open the review of a submission (submission_id)",
                           code="SUBMISSION_PACK_NEEDS_SUBMISSION")
        with self.locks.hold(pack_id):
            pack = self.packs.load(pack_id)
            existing = [s for s in self.repo.list(pack_id) if s["status"] in ACTIVE_STATES and s.get("submission_id") == submission_id]
            if existing:
                return existing[-1], False
            produced = trace.get("produced")
            session = {"review_id": ids.new_id("RS"), "pack_id": pack_id,
                       "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"], "status": "OPEN",
                       "created_at": now_iso(), "created_by": self.settings.analyst_id, "updated_at": now_iso(), "revision": 1,
                       "selections": self._default_selections(pack, submission_id, produced), "selections_version": 1,
                       "current_preview_id": None, "preview_job_id": None, "final_pack_id": None, "last_decision_id": None,
                       **{k: trace[k] for k in ("submission_id", "run_id", "batch_id") if trace.get(k)}}
            self.repo.create(session)
        self._activity("REVIEW_OPENED", session, **({"submission_id": submission_id} if submission_id else {}))
        return session, True

    def _submission_trace(self, pack_id, submission_id):
        """The submission's audit run, which must have succeeded and produced this pack."""
        if not isinstance(submission_id, str) or not SUBMISSION_ID_RE.match(submission_id):
            raise InvalidInput("invalid submission id", code="INVALID_ID")
        run = self.monthly.submission_run(submission_id) if self.monthly is not None else None
        if run is None:
            raise NotFound("submission not found")
        if run["status"] != "SUCCEEDED" or (run.get("result") or {}).get("pack_id") != pack_id:
            raise Conflict("this submission's audit run has not produced this pack", code="SUBMISSION_PACK_MISMATCH",
                           extra={"run_status": run["status"], "pack_id": (run.get("result") or {}).get("pack_id")})
        produced = self.auto_investigations.submission_investigations(run) if self.auto_investigations is not None else {}
        return {"submission_id": submission_id, "run_id": run["run_id"], "batch_id": run["batch_id"], "produced": produced}

    def _default_selections(self, pack, submission_id=None, produced=None):
        """Library default rule (newest eligible tools-mode, else newest eligible) applied to registry-eligible ones,
        preferring an investigation the analyst has already reviewed (accepted or rejected) over a pending one.
        A submission's review (produced given) only ever selects the investigation produced for that submission."""
        out = []
        active = self._active_reviews(pack["metadata"]["pack_id"], submission_id)
        for eid in self.packs.exception_ids(pack):
            eligible = [i for i in self.investigations.published(pack, eid)["published"] if i["eligible"]]
            if produced is not None:
                eligible = [i for i in eligible if i["investigation_id"] == produced.get(eid)]
            else:  # a period-level review never selects an investigation that belongs to a ZIP submission
                eligible = [i for i in eligible if not i.get("submission_id")]
            eligible = [i for i in eligible if i["investigation_id"] in active] or eligible
            pick = next((i for i in eligible if i["investigation_mode"] == "tools"), None) or (eligible[0] if eligible else None)
            sel = Selection(exception_id=eid, inclusion="INCLUDED", investigation_id=pick["investigation_id"]) if pick else \
                Selection(exception_id=eid, inclusion="NOT_INVESTIGATED")
            out.append(sel.model_dump())
        return out

    def set_selections(self, review_id, selections, expected_revision=None):
        session = self.get(review_id)
        with self.locks.hold(session["pack_id"]):
            session = self.get(review_id)
            if session["status"] not in EDITABLE_STATES:
                raise Conflict(f"the review session is {session['status']} and cannot be changed", code="SESSION_NOT_EDITABLE")
            if expected_revision is not None and expected_revision != session["revision"]:
                raise Conflict("the review session was changed by another request; reload it", code="REVIEW_CONFLICT")
            if self._preview_running(session):
                raise Conflict("a preview is being generated; wait for it to finish", code="PREVIEW_IN_PROGRESS")
            pack = self.packs.load(session["pack_id"])
            parsed = self._validate_selections(pack, selections, self._produced(session))
            session = self._save(session, selections=[s.model_dump() for s in parsed], status="OPEN",
                                 selections_version=session["selections_version"] + 1, current_preview_id=None)
        self._activity("REVIEW_SELECTIONS_CHANGED", session, selections_version=session["selections_version"])
        return session

    def _validate_selections(self, pack, selections, produced=None):
        """produced: a submission's review may only include the investigation produced for that submission's run."""
        try:
            parsed = [Selection.model_validate(s) for s in selections]
        except ValidationError as e:
            raise InvalidInput(_selection_error(e), code="SELECTION_INVALID") from None
        exc_ids = self.packs.exception_ids(pack)
        given = [s.exception_id for s in parsed]
        if sorted(given) != sorted(exc_ids) or len(set(given)) != len(given):
            raise InvalidInput("every exception in the pack needs exactly one selection", code="SELECTION_INCOMPLETE",
                               extra={"exception_ids": exc_ids})
        for s in parsed:
            rows = self.investigations.published(pack, s.exception_id)["published"]
            if s.inclusion == "INCLUDED":
                row = next((r for r in rows if r["investigation_id"] == s.investigation_id), None)
                if row is None:
                    raise InvalidInput(f"{s.exception_id}: {s.investigation_id} is not a published investigation of this exception",
                                       code="INELIGIBLE_SELECTION")
                if not row["eligible"]:
                    raise InvalidInput(f"{s.exception_id}: {s.investigation_id} is not eligible: " + "; ".join(row["ineligible_reasons"]),
                                       code="INELIGIBLE_SELECTION")
                if produced is not None and produced.get(s.exception_id) != s.investigation_id:
                    raise InvalidInput(f"{s.exception_id}: {s.investigation_id} was not produced for this submission's audit run",
                                       code="INVESTIGATION_NOT_IN_SUBMISSION")
                if produced is None and row.get("submission_id"):
                    raise InvalidInput(f"{s.exception_id}: {s.investigation_id} belongs to ZIP submission {row['submission_id']}; "
                                       "it is reviewed only in that submission's review", code="INVESTIGATION_BELONGS_TO_SUBMISSION")
            elif s.inclusion == "NOT_INVESTIGATED" and any(r["library_eligible"] for r in rows):
                # pack-wide, as the protected final-pack library checks it: in a submission's review an investigation of
                # another submission cannot be included, so the exception is excluded with a documented reason instead
                raise InvalidInput(f"{s.exception_id}: eligible investigations exist; " + (
                    "none was produced for this submission: use EXCLUDED_BY_ANALYST with a reason" if produced is not None
                    else "include one or use EXCLUDED_BY_ANALYST with a reason"), code="NOT_INVESTIGATED_WITH_ELIGIBLE")
        return [next(s for s in parsed if s.exception_id == e) for e in exc_ids]

    # ---------------------------------------------------------------- readiness
    def _preview_running(self, session):
        job = self.runner.repo.get(session["preview_job_id"]) if session.get("preview_job_id") else None
        return job is not None and job["status"] in ("QUEUED", "RUNNING")

    def readiness(self, session, pack=None):
        pack = pack or self.packs.load(session["pack_id"])
        blockers, warnings, info = [], [], []
        run = self.monthly.submission_run(session["submission_id"]) if session.get("submission_id") and self.monthly is not None else None
        # this submission's own jobs: the run's jobs AND its submission-scoped retries (matched by the execution context's
        # run, not only by the run's original authorisation; AutoInvestigationService.own_jobs)
        own_jobs = {j["job_id"] for j in self.auto_investigations.own_jobs(run)} if run and self.auto_investigations else set()
        for j in self.runner.active(session["pack_id"], operation="INVESTIGATION"):
            if session.get("submission_id") and j["job_id"] not in own_jobs:
                continue  # another submission's execution never blocks (or feeds) this submission's review
            blockers.append({"code": "INVESTIGATION_RUNNING", "detail": f"an investigation of {j['exception_id']} is {j['status']}"})
        active = self._active_reviews(session["pack_id"], session.get("submission_id"))
        produced = self._produced(session)
        ai_states = {e: self.auto_investigations.exception_status(session["pack_id"], e, pack)
                     for e in self.packs.exception_ids(pack)} if self.auto_investigations is not None else {}
        if produced is not None:  # a submission's checklist: its own jobs, investigations and decisions only (never pack-wide)
            run = self.monthly.submission_run(session["submission_id"])
            ai_states = {}
            for e in self.packs.exception_ids(pack):
                eligible = {r["investigation_id"]: r["eligible"] for r in self.investigations.published(pack, e)["published"]}
                ai_states[e] = self.auto_investigations.submission_exception_status(run, e, active, eligible)
        for s in session["selections"]:
            rows = self.investigations.published(pack, s["exception_id"])["published"]
            if s["inclusion"] == "INCLUDED":
                row = next((r for r in rows if r["investigation_id"] == s["investigation_id"]), None)
                if row is None or not row["eligible"]:
                    blockers.append({"code": "INELIGIBLE_SELECTION", "detail": f"{s['exception_id']}: {s['investigation_id']} is no longer "
                                     "eligible: " + "; ".join((row or {}).get("ineligible_reasons") or ["not found"])})
                elif self.analyst_reviews is not None:
                    decision = active.get(s["investigation_id"])
                    if decision is None:  # never silently treated as accepted
                        where = ("in this submission's review (This submission's analyst decisions)" if session.get("submission_id")
                                 else "in the Exception Workspace")
                        blockers.append({"code": "AI_REVIEW_PENDING", "detail": f"{s['exception_id']}: {s['investigation_id']} is pending "
                                         f"analyst review; ACCEPT or REJECT it {where} (or exclude it with a reason)"})
                    elif decision["decision"] == "REJECT":
                        info.append({"code": "AI_REJECTED_BY_ANALYST", "detail": f"{s['exception_id']}: {s['investigation_id']} was rejected by "
                                     "the analyst; its AI content is excluded and the analyst's reason is reported instead"})
                    if decision is not None and decision.get("pdf_unsupported_characters"):
                        chars = ", ".join(f"{c['character']} ({c['codepoint']})" for c in decision["pdf_unsupported_characters"][:6])
                        blockers.append({"code": "PDF_GLYPHS_UNSUPPORTED", "detail": f"{s['exception_id']}: the analyst's wording contains "
                                         f"characters the audit PDF fonts cannot draw ({chars}); configure a fallback font that covers "
                                         "them or record a new decision. Characters are never substituted."})
            elif s["inclusion"] == "NOT_INVESTIGATED" and produced is not None:
                blocker, warning = self._submission_not_investigated(s["exception_id"], rows, produced, ai_states)
                if blocker:
                    blockers.append(blocker)
                if warning:
                    warnings.append(warning)
            elif s["inclusion"] == "NOT_INVESTIGATED":
                state = ai_states.get(s["exception_id"], {}).get("state")
                if produced is not None and state in ("FAILED", "NOT_USABLE", None) and any(r["library_eligible"] for r in rows):
                    why = ((ai_states.get(s["exception_id"]) or {}).get("job") or {}).get("error_summary") or "no usable result"
                    blockers.append({"code": "INVESTIGATION_FAILED_NO_DISPOSITION", "detail": f"{s['exception_id']}: this submission's AI "
                                     f"investigation did not produce a usable result ({why[:200]}); an investigation from another "
                                     "submission cannot be used here: retry it within this submission, or exclude it from this "
                                     "final pack with a documented reason"})
                elif any(r["library_eligible"] for r in rows):
                    blockers.append({"code": "NOT_INVESTIGATED_WITH_ELIGIBLE", "detail": f"{s['exception_id']}: a verified investigation "
                                     "exists; include it (if registered) or exclude it with a reason"})
                elif state in ("FAILED", "NOT_USABLE"):
                    # An attempt was made and produced nothing usable: "not investigated" would misstate it. The analyst
                    # retries it or records an exclusion with a reason (EXCLUDED_BY_ANALYST); nothing is fabricated.
                    retry = "retry it within this submission" if produced is not None else "retry it"
                    blockers.append({"code": "INVESTIGATION_FAILED_NO_DISPOSITION", "detail": f"{s['exception_id']}: its AI investigation "
                                     f"{'failed' if state == 'FAILED' else 'produced no usable result'}; {retry}, or exclude it from the "
                                     "final pack with a documented reason"})
                else:
                    warnings.append({"code": "NOT_INVESTIGATED", "detail": f"{s['exception_id']} will be reported as not investigated"})
        if self._preview_running(session):
            blockers.append({"code": "PREVIEW_IN_PROGRESS", "detail": "a preview is being generated"})
        if session["status"] in EDITABLE_STATES and not session.get("current_preview_id"):
            blockers.append({"code": "PREVIEW_REQUIRED", "detail": "generate a preview (with the AI closing summary) before deciding"
                             if self._summary_required(session, pack) else
                             "generate a preview before deciding (no AI closing summary is needed: no exceptions were raised)"})
        meta = self.preview_meta(session)
        if meta and self.analyst_reviews is not None and meta.get("analyst_reviews_sha256") != self._reviews_fingerprint(session, active):
            blockers.append({"code": "PREVIEW_STALE", "detail": "an analyst review decision changed after this preview was generated; "
                             "generate a new preview before deciding"})
        if meta and meta["closing_summary"]["status"] == "UNAVAILABLE":
            warnings.append({"code": "CLOSING_SUMMARY_UNAVAILABLE", "detail": "the AI closing summary could not be generated: "
                             f"{meta['closing_summary']['unavailable_reason']}. GENERATE requires acknowledging this."})
        if self.final_packs.scoped_final_packs(session["pack_id"], session.get("submission_id")):
            version, supersedes = self.final_packs.next_version(session["pack_id"], session.get("submission_id"))
            scope = "this submission" if session.get("submission_id") else "this reporting-period lineage"
            warnings.append({"code": "FINAL_PACK_EXISTS", "detail": f"a final pack already exists for {scope}; "
                             f"a new one will be version {version}, superseding {supersedes}"})
        open_exc = pack["executive_summary"]["exceptions"]["open"]
        info.append({"code": "UNRESOLVED_EXCEPTIONS", "detail": f"{open_exc} exception(s) are unresolved and will appear as UNRESOLVED"}
                    if open_exc else {"code": "NO_EXCEPTIONS", "detail": "the engine raised no exceptions"})
        out = {"blockers": blockers, "warnings": warnings, "info": info, "ready": not blockers}
        out["checklist"] = self._checklist(session, active, ai_states, meta, blockers)
        return out

    @staticmethod
    def _submission_not_investigated(eid, rows, produced, ai_states):
        """(blocker, warning) for a NOT_INVESTIGATED selection in a SUBMISSION's review. "An eligible investigation exists"
        means one produced for THIS submission; another submission's eligible investigation can never be included here,
        but the protected final-pack library still refuses NOT_INVESTIGATED while any eligible one exists for the
        exception, so the analyst is told to investigate within this submission or exclude it with a reason."""
        st = ai_states.get(eid) or {}
        state = st.get("state")
        own = produced.get(eid)
        if own and any(r["eligible"] for r in rows if r["investigation_id"] == own):
            return {"code": "NOT_INVESTIGATED_WITH_ELIGIBLE", "detail": f"{eid}: this submission's verified investigation {own} "
                    "exists; include it, or exclude it with a reason"}, None
        others = any(r["library_eligible"] for r in rows)
        if state in ("FAILED", "NOT_USABLE", None) and others:
            why = (st.get("job") or {}).get("error_summary") or "no usable result"
            return {"code": "INVESTIGATION_FAILED_NO_DISPOSITION", "detail": f"{eid}: this submission's AI investigation did not "
                    f"produce a usable result ({why[:200]}); an investigation from another submission cannot be used here: retry "
                    "it within this submission, or exclude it from this final pack with a documented reason"}, None
        if state in ("FAILED", "NOT_USABLE"):
            return {"code": "INVESTIGATION_FAILED_NO_DISPOSITION", "detail": f"{eid}: its AI investigation "
                    f"{'failed' if state == 'FAILED' else 'produced no usable result'}; retry it within this submission, or "
                    "exclude it from the final pack with a documented reason"}, None
        if others:
            return {"code": "NOT_INVESTIGATED_WITH_ELIGIBLE", "detail": f"{eid}: this submission has no investigation of it, but "
                    "another submission has an eligible one, so it cannot be reported as not investigated; investigate it "
                    "within this submission (retry), or exclude it with a documented reason"}, None
        return None, {"code": "NOT_INVESTIGATED", "detail": f"{eid} will be reported as not investigated"}

    # Per-exception disposition in the final review: what is reported for it, and the analyst's next action.
    DISPOSITIONS = {
        "ACCEPTED": "AI findings accepted by the analyst; eligible content is reported",
        "REJECTED": "Rejected by the analyst; reported by the analyst's reason, AI content excluded",
        "AWAITING_DECISION": "Findings ready for review: ACCEPT or REJECT in the Exception Workspace",
        "EXCLUDED": "Excluded from the final pack by the analyst (reason recorded)",
        "IN_PROGRESS": "Investigation queued or in progress",
        "SELECTION_NEEDED": "A usable investigation exists but is not selected: include it, or exclude it with a reason",
        "FAILED_ACTION_NEEDED": "Investigation failed or not usable: retry it, or exclude it with a reason",
        "NOT_INVESTIGATED": "No AI investigation was attempted; reported from the deterministic results only",
    }
    # A submission's review: the decision is made for that submission (never "in the Exception Workspace").
    SUBMISSION_DISPOSITIONS = dict(DISPOSITIONS, AWAITING_DECISION="Findings ready for review: ACCEPT or REJECT the AI finding "
                                                                   "for this submission")

    def _checklist(self, session, active, ai_states, meta, blockers):
        """Readiness as the analyst's checklist: every exception's AI status, its final-review disposition and the next
        action, with the counts. Financial exceptions stay UNRESOLVED whatever the disposition."""
        rows = []
        labels = self.SUBMISSION_DISPOSITIONS if session.get("submission_id") else self.DISPOSITIONS
        for s in session["selections"]:
            st = ai_states.get(s["exception_id"]) or {}
            decision = (active.get(s["investigation_id"]) or {}).get("decision") if s["inclusion"] == "INCLUDED" else None
            if s["inclusion"] == "INCLUDED":
                disp = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED"}.get(decision, "AWAITING_DECISION")
            elif s["inclusion"] == "EXCLUDED_BY_ANALYST":
                disp = "EXCLUDED"
            elif st.get("state") in ("QUEUED", "IN_PROGRESS"):
                disp = "IN_PROGRESS"
            elif st.get("usable_investigations"):
                disp = "SELECTION_NEEDED"
            elif st.get("state") in ("FAILED", "NOT_USABLE"):
                disp = "FAILED_ACTION_NEEDED"
            else:
                disp = "NOT_INVESTIGATED"
            rows.append({"exception_id": s["exception_id"], "inclusion": s["inclusion"], "investigation_id": s["investigation_id"],
                         "reason": s["reason"], "ai_state": st.get("state"), "ai_label": st.get("label"),
                         "job_error": ((st.get("job") or {}).get("error_summary") or "")[:300] if st.get("state") == "FAILED" else "",
                         "usable_investigations": st.get("usable_investigations", []), "decision": decision, "disposition": disp,
                         "disposition_label": labels[disp],
                         "action_needed": disp in ("AWAITING_DECISION", "IN_PROGRESS", "SELECTION_NEEDED", "FAILED_ACTION_NEEDED"),
                         "exception_resolution": "UNRESOLVED"})
        count = lambda *d: sum(r["disposition"] in d for r in rows)  # noqa: E731
        stale = any(b["code"] == "PREVIEW_STALE" for b in blockers)
        return {"exceptions": rows, "counts": {
            "total": len(rows),
            "investigations_completed": sum(bool(r["usable_investigations"]) for r in rows),
            "in_progress": count("IN_PROGRESS"), "awaiting_review": count("AWAITING_DECISION"), "accepted": count("ACCEPTED"),
            "rejected": count("REJECTED"), "failed_or_not_usable": sum(r["ai_state"] in ("FAILED", "NOT_USABLE") for r in rows),
            "failed_needing_action": count("FAILED_ACTION_NEEDED"), "selection_needed": count("SELECTION_NEEDED"),
            "excluded": count("EXCLUDED"), "not_investigated": count("NOT_INVESTIGATED")},
            "preview": "CURRENT" if meta and not stale else "STALE" if meta else "NONE",
            "closing_summary": (meta or {}).get("closing_summary", {}).get("status") if meta and not stale else None,
            "closing_summary_required": bool(rows),  # schema 1.3: no exception -> NOT_REQUIRED, no AI request, no authorisation
            "ready": not blockers}

    # ---------------------------------------------------------------- preview (closing summary + assembled preview)
    def _in_scope(self, session):
        """A predicate on published-investigation rows: the review's own scope. A submission's review sees only its own
        executions' artefacts; a period-level review never sees a submission's."""
        if session.get("submission_id"):
            run = self.monthly.submission_run(session["submission_id"]) if self.monthly is not None else None
            own = self.auto_investigations.submission_artefacts(run)["published"] if run and self.auto_investigations else set()
            return lambda row: row["investigation_id"] in own
        return lambda row: not row.get("submission_id")

    def _inputs_fingerprint(self, pack, snapshot_sha256, session=None):
        """Snapshot hash plus every published investigation IN THE REVIEW'S SCOPE and its eligibility: a new or altered
        artefact makes an earlier preview stale even when the selections did not change; another submission's progress never
        does (no repeat closing-summary call because of it)."""
        keep = self._in_scope(session) if session is not None else (lambda row: True)
        published = {eid: sorted((r["investigation_id"], r["eligible"]) for r in self.investigations.published(pack, eid)["published"]
                                 if keep(r))
                     for eid in self.packs.exception_ids(pack)}
        return hashlib.sha256(canonical({"snapshot": snapshot_sha256, "published": published}).encode("utf-8")).hexdigest()

    def _snapshot(self, session, pack):
        """build_review_snapshot (library verification and eligibility) plus the registry check of included ones."""
        try:
            roots = self.packs.root_set(session["pack_id"])  # the storage root set holding this pack
            # The analyst's active decisions are snapshot inputs: only ACCEPTED AI content is reported, a pending
            # investigation is refused, and a changed decision changes the snapshot hash (an earlier preview is stale).
            reviews = None if self.analyst_reviews is None else [
                self.analyst_reviews.library_review(v) for v in self._active_reviews(session["pack_id"], session.get("submission_id")).values()]
            snapshot = build_review_snapshot(session["pack_id"], session["selections"], packs_root=roots.packs_root,
                                             investigations_root=roots.investigations_root, analyst_reviews=reviews)
        except FinalPackInputError as e:
            raise Conflict(str(e), code="BLOCKED") from None
        # Other attempts are reported in the final pack by the application's eligibility (registry and authorisation), not by
        # the library check alone: an unregistered or discrepant artefact is "ineligible", never "eligible, not selected".
        # (attempts are not part of the snapshot content, so the snapshot hash is unchanged.)
        # Only the review's own scope is reported as "other attempts": a submission's final pack never lists another
        # submission's investigations or attempt records, and a period-level one never lists a submission's.
        keep = self._in_scope(session)
        own_records = None
        if session.get("submission_id"):
            run = self.monthly.submission_run(session["submission_id"]) if self.monthly is not None else None
            own_records = self.auto_investigations.submission_artefacts(run)["not_published"] if run and self.auto_investigations else set()
        for eid, attempts in snapshot.attempts.items():
            app = {r["investigation_id"]: r for r in self.investigations.published(pack, eid)["published"]}
            attempts["published"] = [i for i in attempts["published"]
                                     if i["investigation_id"] in app and keep(app[i["investigation_id"]])]
            if own_records is not None:
                attempts["not_published"] = [a for a in attempts["not_published"] if a.get("record") in own_records]
            for info in attempts["published"]:
                row = app.get(info["investigation_id"])
                if row is not None:
                    info["eligible"], info["reasons"] = row["eligible"], row["ineligible_reasons"]
        for s in session["selections"]:
            if s["inclusion"] == "INCLUDED":
                row = next((r for r in self.investigations.published(pack, s["exception_id"])["published"]
                            if r["investigation_id"] == s["investigation_id"]), None)
                if row is None or not row["eligible"]:
                    raise Conflict(f"{s['exception_id']}: {s['investigation_id']} is not eligible", code="BLOCKED")
        return snapshot

    def request_preview(self, review_id, confirmation=None):
        """Queue the closing summary + preview job, only with the analyst's explicit authorisation of the closing-summary
        call (recorded before the job is submitted; a refused request is recorded with its reason). Without a configured
        provider the authorisation is still recorded and the preview is built with the closing summary UNAVAILABLE."""
        auth = self.ai_authorizations
        session = self.get(review_id)
        if not self._summary_required(session):
            return self._request_preview_without_ai(review_id)
        with self.locks.hold(session["pack_id"]):
            session = self.get(review_id)
            config, changed = auth.require(CLOSING_SUMMARY, confirmation)
            pack_id = session["pack_id"]
            context = {"review_id": review_id,
                       "selected_investigations": [s["investigation_id"] for s in session["selections"] if s["inclusion"] == "INCLUDED"]}
            if changed:
                auth.changed(CLOSING_SUMMARY, changed, pack_id, config, **context)
            if session["status"] not in EDITABLE_STATES:
                auth.refuse(CLOSING_SUMMARY, Conflict(f"the review session is {session['status']}", code="SESSION_NOT_EDITABLE"),
                            pack_id, config, **context)
            if self._preview_running(session):
                auth.refuse(CLOSING_SUMMARY, Conflict("a preview is already being generated", code="PREVIEW_IN_PROGRESS",
                                                      extra={"job_id": session["preview_job_id"]}), pack_id, config, **context)
            pack = self.packs.load(pack_id)
            blockers = [b for b in self.readiness(session, pack)["blockers"] if b["code"] not in ("PREVIEW_REQUIRED", "PREVIEW_STALE")]
            if blockers:
                auth.refuse(CLOSING_SUMMARY, Conflict("the preview is blocked: " + "; ".join(b["detail"] for b in blockers),
                                                      code="BLOCKED", extra={"blockers": blockers}), pack_id, config, **context)
            try:  # which provider the summary call will use; without one the summary will be UNAVAILABLE (no model call)
                investigator = self.investigator_factory() if self.investigator_factory else None
            except LLMConfigurationError:
                investigator = None
            live = investigator is not None and not getattr(investigator, "simulated", False)
            authorization_id = ids.new_id("AIA")
            job = self.runner.create("PREVIEW", pack_id, self.settings.analyst_id, inputs={"review_id": review_id,
                                                                                    "selections_version": session["selections_version"],
                                                                                    "authorization_id": authorization_id})
            try:
                auth.record(CLOSING_SUMMARY, AUTHORIZED, pack_id, config, job_id=job["job_id"], authorization_id=authorization_id,
                            provider=getattr(investigator, "provider", None), model=getattr(investigator, "model", None),
                            model_call_expected=live, **context)
            except Exception:  # no recorded authorisation: the job never runs
                self.runner.repo.update(job["job_id"], {"status": "FAILED", "completed_at": now_iso(),
                                                        "error_summary": "the authorisation could not be recorded; nothing was run"})
                raise
            session = self._save(session, preview_job_id=job["job_id"], current_preview_id=None)
            self.runner.submit(job, self._build_preview)
        self._activity("PREVIEW_REQUESTED", session, job_id=job["job_id"], authorization_id=authorization_id)
        return job

    def _summary_required(self, session, pack=None):
        """Whether the preview needs an AI closing summary (schema 1.3): only when the pack has exceptions. A pack without
        exceptions has no investigation to include, so its summary is NOT_REQUIRED: no AI request, no authorisation."""
        pack = pack if pack is not None else self.packs.load(session["pack_id"])
        return bool(self.packs.exception_ids(pack))

    def _request_preview_without_ai(self, review_id):
        """Queue a preview whose closing summary is NOT_REQUIRED. No AI authorisation is asked for or recorded, because no
        AI request is made; the same state checks as an AI preview apply."""
        session = self.get(review_id)
        with self.locks.hold(session["pack_id"]):
            session = self.get(review_id)
            if session["status"] not in EDITABLE_STATES:
                raise Conflict(f"the review session is {session['status']}", code="SESSION_NOT_EDITABLE")
            if self._preview_running(session):
                raise Conflict("a preview is already being generated", code="PREVIEW_IN_PROGRESS", extra={"job_id": session["preview_job_id"]})
            pack = self.packs.load(session["pack_id"])
            blockers = [b for b in self.readiness(session, pack)["blockers"] if b["code"] not in ("PREVIEW_REQUIRED", "PREVIEW_STALE")]
            if blockers:
                raise Conflict("the preview is blocked: " + "; ".join(b["detail"] for b in blockers), code="BLOCKED",
                               extra={"blockers": blockers})
            job = self.runner.create("PREVIEW", session["pack_id"], self.settings.analyst_id,
                                     inputs={"review_id": review_id, "selections_version": session["selections_version"],
                                             "authorization_id": None, "closing_summary_required": False})
            session = self._save(session, preview_job_id=job["job_id"], current_preview_id=None)
            self.runner.submit(job, self._build_preview)
        self._activity("PREVIEW_REQUESTED", session, job_id=job["job_id"], authorization_id=None, closing_summary="NOT_REQUIRED")
        return job

    def _build_preview(self, job):
        review_id = job["inputs"]["review_id"]
        session = self.get(review_id)
        pack = self.packs.load(session["pack_id"])
        try:
            snapshot = self._snapshot(session, pack)
        except AppError as e:
            return "FAILED", None, e.detail
        summary_failure, investigator = None, None
        if not closing_summary_required(snapshot):  # schema 1.3: no exception, no included investigation -> no AI request
            summary = not_required_closing_summary(snapshot)
        else:
            try:
                investigator = self.investigator_factory() if self.investigator_factory else None
                summary = generate_closing_summary(snapshot, investigator)
            except (ClosingSummaryError, LLMConfigurationError) as e:
                summary_failure = summary_failure_record(e, investigator)  # DR-09: keeps the billed telemetry
                kind = summary_failure["kind"]
                # The reason keeps the internal kind (technical appendix only); a refused output also keeps its validation
                # findings (redacted). The report's main body states the failure neutrally (renderer 3.0).
                summary = unavailable_closing_summary(snapshot, f"closing summary generation failed ({kind})",
                                                      [redact(str(x)) for x in getattr(e, "findings", [])])
        try:
            preview = assemble_preview(snapshot, summary)
        except FinalPackValidationError as e:
            return "FAILED", None, f"the preview failed final-pack validation: {'; '.join(e.errors[:5])}"[:500]
        glyphs = unsupported_characters(preview)  # the PDF would be refused at GENERATE: say so now, never substitute
        if glyphs:
            return "FAILED", None, str(PdfGlyphError(glyphs))[:500]
        preview_id = ids.new_id("PV")
        meta = {"preview_id": preview_id, "review_id": review_id, "selections_version": job["inputs"]["selections_version"],
                "snapshot_sha256": snapshot.sha256, "inputs_fingerprint": self._inputs_fingerprint(pack, snapshot.sha256, session),
                "analyst_reviews_sha256": self._reviews_fingerprint(session),
                "preview_final_pack_id": preview["metadata"]["final_pack_id"], "preview_content_sha256": preview["final_content_sha256"],
                "closing_summary": {"status": summary.status, "sha256": summary_sha256(summary), "unavailable_reason": summary.unavailable_reason,
                                    "failure": summary_failure, "model": summary.model_metadata.get("model"),
                                    "provider": summary.model_metadata.get("provider"), "created_at": summary.created_at,
                                    "fallback": summary.model_metadata.get("fallback")},
                "closing_summary_record": summary.model_dump(), "created_at": now_iso(), "created_by": job["submitted_by"]}
        self.repo.save_preview(review_id, preview_id, meta, preview)
        with self.locks.hold(session["pack_id"]):
            session = self.get(review_id)
            current = session["selections_version"] == meta["selections_version"] and session["status"] in EDITABLE_STATES
            if current:
                self._save(session, current_preview_id=preview_id)
        return "COMPLETED", {"review_id": review_id, "preview_id": preview_id, "snapshot_sha256": snapshot.sha256,
                             "closing_summary_status": summary.status, "current": current}, ""

    def preview_meta(self, session):
        if not session.get("current_preview_id"):
            return None
        meta, _ = self.repo.get_preview(session["review_id"], session["current_preview_id"])
        return meta

    def preview(self, review_id):
        """(meta, preview document) of the current preview."""
        session = self.get(review_id)
        if not session.get("current_preview_id"):
            raise NotFound("this review has no current preview; request one", code="NO_PREVIEW")
        return self.repo.get_preview(review_id, session["current_preview_id"])

    # ---------------------------------------------------------------- decisions
    def decide(self, review_id, body):
        decision = body["decision"]
        session = self.get(review_id)
        timeout = 30 if decision == "HOLD" else 0
        with self.locks.hold(session["pack_id"], timeout=timeout, busy_code="GENERATION_IN_PROGRESS"):
            session = self.get(review_id)
            if session["status"] == "GENERATING":
                raise Conflict("this review is being generated", code="GENERATION_IN_PROGRESS")
            if session["status"] == "GENERATED":
                raise Conflict("this review has already produced a final pack", code="SESSION_CLOSED",
                               extra={"final_pack_id": session["final_pack_id"]})
            if decision == "HOLD":
                return self._hold(session, body)
            return self._generate(session, body)

    def _decision_record(self, session, body, meta):
        return {"review_decision_id": ids.new_id("RD"), "review_id": session["review_id"], "pack_id": session["pack_id"],
                "decision": body["decision"], "decided_at": now_iso(),
                "reviewer": dict(self.settings.reviewer),
                "comment": (body.get("comment") or "").strip(), "acknowledgement_accepted": bool(body.get("acknowledgement_accepted")),
                "acknowledgement_text": ACKNOWLEDGEMENT_TEXT if body["decision"] == "GENERATE" else "",
                "acknowledged_summary_unavailable": bool(body.get("acknowledged_summary_unavailable")),
                "snapshot_sha256": (meta or {}).get("snapshot_sha256", ""), "preview_id": (meta or {}).get("preview_id", ""),
                "closing_summary_sha256": (meta or {}).get("closing_summary", {}).get("sha256", "")}

    def _hold(self, session, body):
        if not (body.get("comment") or "").strip():
            raise InvalidInput("HOLD requires a comment giving the reason", code="COMMENT_REQUIRED")
        meta = self.preview_meta(session)
        if body.get("snapshot_sha256") and (meta is None or body["snapshot_sha256"] != meta["snapshot_sha256"]):
            raise Conflict("the preview has changed; reload it", code="PREVIEW_STALE")
        record = self._decision_record(session, body, meta)
        self.repo.append_decision(session["review_id"], record)
        session = self._save(session, status="ON_HOLD", last_decision_id=record["review_decision_id"], current_preview_id=None)
        self._activity("REVIEW_HOLD", session, review_decision_id=record["review_decision_id"], comment=record["comment"][:200])
        return {"decision": record, "session_status": session["status"], "final_pack": None}

    def _generate(self, session, body):
        meta = self.preview_meta(session)
        if meta is None:
            raise Conflict("no current preview; generate and read a preview first", code="PREVIEW_REQUIRED")
        if body.get("snapshot_sha256") != meta["snapshot_sha256"]:
            raise Conflict("the decision does not match the current preview; reload the preview", code="PREVIEW_STALE")
        if body.get("acknowledgement_accepted") is not True:
            raise InvalidInput("GENERATE requires accepting: " + ACKNOWLEDGEMENT_TEXT, code="ACKNOWLEDGEMENT_REQUIRED")
        if meta["closing_summary"]["status"] == "UNAVAILABLE" and body.get("acknowledged_summary_unavailable") is not True:
            raise InvalidInput("the AI closing summary is unavailable; GENERATE requires acknowledging that",
                               code="SUMMARY_UNAVAILABLE_ACK_REQUIRED")
        pack = self.packs.load(session["pack_id"])
        if self._inputs_fingerprint(pack, meta["snapshot_sha256"], session) != meta["inputs_fingerprint"]:
            raise Conflict("the investigations changed since the preview; generate a new preview", code="PREVIEW_STALE")
        if self.analyst_reviews is not None and meta.get("analyst_reviews_sha256") != self._reviews_fingerprint(session):
            raise Conflict("an analyst review decision changed since the preview; generate a new preview", code="PREVIEW_STALE")
        blockers = self.readiness(session, pack)["blockers"]
        if blockers:
            raise Conflict("generation is blocked: " + "; ".join(b["detail"] for b in blockers), code="BLOCKED",
                           extra={"blockers": blockers})
        snapshot = self._snapshot(session, pack)  # re-verified now (library + registry), from the same stored selections
        if snapshot.sha256 != meta["snapshot_sha256"]:
            raise Conflict("the inputs changed since the preview; generate a new preview", code="PREVIEW_STALE")
        summary = ClosingSummary.model_validate(meta["closing_summary_record"])
        record = self._decision_record(session, body, meta)
        prior = [PriorDecision(review_decision_id=d["review_decision_id"], decision="HOLD", decided_at=d["decided_at"], comment=d["comment"])
                 for d in self.repo.decisions(session["review_id"]) if d["decision"] == "HOLD"]
        review = ReviewRecord(review_decision_id=record["review_decision_id"], review_session_id=session["review_id"], decision="GENERATE",
                              reviewer=Reviewer(**record["reviewer"]), decided_at=record["decided_at"], comment=record["comment"],
                              acknowledgement_accepted=True, snapshot_sha256=snapshot.sha256, closing_summary_sha256=summary_sha256(summary),
                              acknowledged_summary_unavailable=record["acknowledged_summary_unavailable"], prior_decisions=prior)
        self.repo.append_decision(session["review_id"], record)
        session = self._save(session, status="GENERATING", last_decision_id=record["review_decision_id"])
        try:
            fp = self.final_packs.generate(snapshot, summary, review,
                                          trace={k: session.get(k) for k in ("submission_id", "run_id", "batch_id")})
        except Exception as e:
            session = self._save(self.get(session["review_id"]), status="GENERATION_FAILED")
            self._activity("REVIEW_GENERATION_FAILED", session, review_decision_id=record["review_decision_id"], error=safe_error(e)[:200])
            raise AppError(f"generation failed; nothing was published: {safe_error(e)}", code="GENERATION_FAILED", status=500,
                           extra={"review_decision_id": record["review_decision_id"]}) from None
        session = self._save(self.get(session["review_id"]), status="GENERATED", final_pack_id=fp["final_pack_id"])
        self._activity("REVIEW_GENERATED", session, review_decision_id=record["review_decision_id"], final_pack_id=fp["final_pack_id"],
                       version=fp.get("version"), supersedes_final_pack_id=fp.get("supersedes_final_pack_id"))
        return {"decision": record, "session_status": session["status"], "final_pack": fp}

    def locked_sessions(self, pack_id, submission_id):
        """Review sessions of (pack, submission) whose final pack is generated or being generated, oldest first: the
        submission's analyst decisions are then locked (InvestigationReviewService)."""
        return [s for s in self.repo.list(pack_id) if s.get("submission_id") == submission_id and s["status"] in ("GENERATED", "GENERATING")]

    def submission_session(self, pack_id, submission_id):
        """The (pack, submission) review session to show: the active one, else the latest; None when none was opened."""
        sessions = [s for s in self.repo.list(pack_id) if s.get("submission_id") == submission_id]
        active = [s for s in sessions if s["status"] in ACTIVE_STATES]
        return active[-1] if active else (sessions[-1] if sessions else None)

    def list(self, pack_id=None, status=None):
        """Review sessions (newest first), read-only: listing never opens or changes a session."""
        if pack_id is not None:
            ids.check("pack_id", pack_id)
        out = []
        for s in reversed(self.repo.list(pack_id)):
            if status is not None and s["status"] != status:
                continue
            decisions = self.repo.decisions(s["review_id"])
            last = decisions[-1] if decisions else None
            out.append({"review_id": s["review_id"], "pack_id": s["pack_id"], "status": s["status"], "created_at": s["created_at"],
                        "updated_at": s["updated_at"], "has_preview": bool(s.get("current_preview_id")), "final_pack_id": s.get("final_pack_id"),
                        "submission_id": s.get("submission_id"), "run_id": s.get("run_id"), "batch_id": s.get("batch_id"),
                        "last_decision": {k: last[k] for k in ("review_decision_id", "decision", "decided_at", "comment")} if last else None})
        return out

    def history(self, review_id):
        session = self.get(review_id)
        return {"review_id": review_id, "decisions": self.repo.decisions(review_id),
                "final_pack_records": [r for r in self.final_packs.records.list(session["pack_id"]) if r["review_id"] == review_id]}

    def recover(self):
        """Start-up (after FinalPackService.recover): a session left GENERATING takes the outcome of its decision's
        final-pack record; with no record, generation never started and the session is GENERATION_FAILED."""
        for session in self.repo.list():
            if session["status"] != "GENERATING":
                continue
            r = self.final_packs.records.get(session["last_decision_id"])
            status = r["status"] if r and r["status"] in ("GENERATED", "GENERATION_FAILED") else "GENERATION_FAILED"
            self._save(session, status=status, final_pack_id=(r or {}).get("final_pack_id"))
