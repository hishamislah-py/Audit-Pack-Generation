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
                                 ReviewRecord, Selection, build_review_snapshot, assemble_preview, generate_closing_summary,
                                 summary_sha256, unavailable_closing_summary)
from uc042lib.final_pack.model import ACKNOWLEDGEMENT_TEXT, PriorDecision
from uc042lib.investigation.llm import LLMConfigurationError, redact
from uc042lib.pack.model import canonical

from .. import ids
from ..errors import AppError, Conflict, InvalidInput, NotFound
from ..jobs import safe_error
from ..repositories import ConcurrentUpdate
from ..clock import now_iso
from .ai_authorization import AUTHORIZED, CLOSING_SUMMARY, period_of

log = logging.getLogger("uc042app.reviews")
ACTIVE_STATES = ("OPEN", "ON_HOLD", "GENERATING", "GENERATION_FAILED")
EDITABLE_STATES = ("OPEN", "ON_HOLD", "GENERATION_FAILED")


def _selection_error(e):
    msgs = [err.get("msg", "") for err in e.errors()] if isinstance(e, ValidationError) else [str(e)]
    return "; ".join(m.removeprefix("Value error, ") for m in msgs)[:500]


class ReviewService:
    def __init__(self, settings, repos, packs, investigations, final_packs, runner, locks, investigator_factory=None,
                 ai_authorizations=None):
        self.settings, self.repo, self.packs, self.investigations = settings, repos.reviews, packs, investigations
        self.final_packs, self.runner, self.locks = final_packs, runner, locks
        self.investigator_factory = investigator_factory
        self.activity = repos.activity  # None without a database (the activity log is a database feature)
        self.ai_authorizations = ai_authorizations

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

    def open(self, pack_id):
        """Return (session, created). An existing active session for the pack is returned instead of a second one. This is
        only ever called by the explicit "open a review" action (POST): reading or navigating never creates a session."""
        with self.locks.hold(pack_id):
            pack = self.packs.load(pack_id)
            existing = [s for s in self.repo.list(pack_id) if s["status"] in ACTIVE_STATES]
            if existing:
                return existing[-1], False
            session = {"review_id": ids.new_id("RS"), "pack_id": pack_id,
                       "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"], "status": "OPEN",
                       "created_at": now_iso(), "created_by": self.settings.analyst_id, "updated_at": now_iso(), "revision": 1,
                       "selections": self._default_selections(pack), "selections_version": 1, "current_preview_id": None,
                       "preview_job_id": None, "final_pack_id": None, "last_decision_id": None}
            self.repo.create(session)
        self._activity("REVIEW_OPENED", session)
        return session, True

    def _default_selections(self, pack):
        """Library default rule (newest eligible tools-mode, else newest eligible) applied to registry-eligible ones."""
        out = []
        for eid in self.packs.exception_ids(pack):
            eligible = [i for i in self.investigations.published(pack, eid)["published"] if i["eligible"]]
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
            parsed = self._validate_selections(pack, selections)
            session = self._save(session, selections=[s.model_dump() for s in parsed], status="OPEN",
                                 selections_version=session["selections_version"] + 1, current_preview_id=None)
        self._activity("REVIEW_SELECTIONS_CHANGED", session, selections_version=session["selections_version"])
        return session

    def _validate_selections(self, pack, selections):
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
            elif s.inclusion == "NOT_INVESTIGATED" and any(r["library_eligible"] for r in rows):
                raise InvalidInput(f"{s.exception_id}: eligible investigations exist; include one or use EXCLUDED_BY_ANALYST "
                                   "with a reason", code="NOT_INVESTIGATED_WITH_ELIGIBLE")
        return [next(s for s in parsed if s.exception_id == e) for e in exc_ids]

    # ---------------------------------------------------------------- readiness
    def _preview_running(self, session):
        job = self.runner.repo.get(session["preview_job_id"]) if session.get("preview_job_id") else None
        return job is not None and job["status"] in ("QUEUED", "RUNNING")

    def readiness(self, session, pack=None):
        pack = pack or self.packs.load(session["pack_id"])
        blockers, warnings, info = [], [], []
        for j in self.runner.active(session["pack_id"], operation="INVESTIGATION"):
            blockers.append({"code": "INVESTIGATION_RUNNING", "detail": f"an investigation of {j['exception_id']} is {j['status']}"})
        for s in session["selections"]:
            rows = self.investigations.published(pack, s["exception_id"])["published"]
            if s["inclusion"] == "INCLUDED":
                row = next((r for r in rows if r["investigation_id"] == s["investigation_id"]), None)
                if row is None or not row["eligible"]:
                    blockers.append({"code": "INELIGIBLE_SELECTION", "detail": f"{s['exception_id']}: {s['investigation_id']} is no longer "
                                     "eligible: " + "; ".join((row or {}).get("ineligible_reasons") or ["not found"])})
            elif s["inclusion"] == "NOT_INVESTIGATED":
                if any(r["library_eligible"] for r in rows):
                    blockers.append({"code": "NOT_INVESTIGATED_WITH_ELIGIBLE", "detail": f"{s['exception_id']}: a verified investigation "
                                     "exists; include it (if registered) or exclude it with a reason"})
                else:
                    warnings.append({"code": "NOT_INVESTIGATED", "detail": f"{s['exception_id']} will be reported as not investigated"})
        if self._preview_running(session):
            blockers.append({"code": "PREVIEW_IN_PROGRESS", "detail": "a preview is being generated"})
        if session["status"] in EDITABLE_STATES and not session.get("current_preview_id"):
            blockers.append({"code": "PREVIEW_REQUIRED", "detail": "generate a preview (with the closing summary) before deciding"})
        meta = self.preview_meta(session)
        if meta and meta["closing_summary"]["status"] == "UNAVAILABLE":
            warnings.append({"code": "CLOSING_SUMMARY_UNAVAILABLE", "detail": "the AI closing summary could not be generated: "
                             f"{meta['closing_summary']['unavailable_reason']}. GENERATE requires acknowledging this."})
        if self.final_packs.list(session["pack_id"], lineage=True):
            version, supersedes = self.final_packs.next_version(session["pack_id"])
            warnings.append({"code": "FINAL_PACK_EXISTS", "detail": f"a final pack already exists for this reporting-period lineage; "
                             f"a new one will be version {version}, superseding {supersedes}"})
        open_exc = pack["executive_summary"]["exceptions"]["open"]
        info.append({"code": "UNRESOLVED_EXCEPTIONS", "detail": f"{open_exc} exception(s) are unresolved and will appear as UNRESOLVED"}
                    if open_exc else {"code": "NO_EXCEPTIONS", "detail": "the engine raised no exceptions"})
        return {"blockers": blockers, "warnings": warnings, "info": info, "ready": not blockers}

    # ---------------------------------------------------------------- preview (closing summary + assembled preview)
    def _inputs_fingerprint(self, pack, snapshot_sha256):
        """Snapshot hash plus every published investigation of the pack and its eligibility: a new or altered artefact
        makes an earlier preview stale even when the selections did not change."""
        published = {eid: sorted((r["investigation_id"], r["eligible"]) for r in self.investigations.published(pack, eid)["published"])
                     for eid in self.packs.exception_ids(pack)}
        return hashlib.sha256(canonical({"snapshot": snapshot_sha256, "published": published}).encode("utf-8")).hexdigest()

    def _snapshot(self, session, pack):
        """build_review_snapshot (library verification and eligibility) plus the registry check of included ones."""
        try:
            roots = self.packs.root_set(session["pack_id"])  # the storage root set holding this pack
            snapshot = build_review_snapshot(session["pack_id"], session["selections"], packs_root=roots.packs_root,
                                             investigations_root=roots.investigations_root)
        except FinalPackInputError as e:
            raise Conflict(str(e), code="BLOCKED") from None
        # Other attempts are reported in the final pack by the application's eligibility (registry and authorisation), not by
        # the library check alone: an unregistered or discrepant artefact is "ineligible", never "eligible, not selected".
        # (attempts are not part of the snapshot content, so the snapshot hash is unchanged.)
        for eid, attempts in snapshot.attempts.items():
            app = {r["investigation_id"]: r for r in self.investigations.published(pack, eid)["published"]}
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
            blockers = [b for b in self.readiness(session, pack)["blockers"] if b["code"] != "PREVIEW_REQUIRED"]
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

    def _build_preview(self, job):
        review_id = job["inputs"]["review_id"]
        session = self.get(review_id)
        pack = self.packs.load(session["pack_id"])
        try:
            snapshot = self._snapshot(session, pack)
        except AppError as e:
            return "FAILED", None, e.detail
        summary_failure = None
        try:
            investigator = self.investigator_factory() if self.investigator_factory else None
            summary = generate_closing_summary(snapshot, investigator)
        except (ClosingSummaryError, LLMConfigurationError) as e:
            kind = getattr(e, "kind", "configuration")
            summary_failure = {"kind": kind, "detail": redact(str(e))[:500]}
            summary = unavailable_closing_summary(snapshot, f"closing summary generation failed ({kind})")
        try:
            preview = assemble_preview(snapshot, summary)
        except FinalPackValidationError as e:
            return "FAILED", None, f"the preview failed final-pack validation: {'; '.join(e.errors[:5])}"[:500]
        preview_id = ids.new_id("PV")
        meta = {"preview_id": preview_id, "review_id": review_id, "selections_version": job["inputs"]["selections_version"],
                "snapshot_sha256": snapshot.sha256, "inputs_fingerprint": self._inputs_fingerprint(pack, snapshot.sha256),
                "preview_final_pack_id": preview["metadata"]["final_pack_id"], "preview_content_sha256": preview["final_content_sha256"],
                "closing_summary": {"status": summary.status, "sha256": summary_sha256(summary), "unavailable_reason": summary.unavailable_reason,
                                    "failure": summary_failure, "model": summary.model_metadata.get("model"),
                                    "provider": summary.model_metadata.get("provider"), "created_at": summary.created_at},
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
        if self._inputs_fingerprint(pack, meta["snapshot_sha256"]) != meta["inputs_fingerprint"]:
            raise Conflict("the investigations changed since the preview; generate a new preview", code="PREVIEW_STALE")
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
            fp = self.final_packs.generate(snapshot, summary, review)
        except Exception as e:
            session = self._save(self.get(session["review_id"]), status="GENERATION_FAILED")
            self._activity("REVIEW_GENERATION_FAILED", session, review_decision_id=record["review_decision_id"], error=safe_error(e)[:200])
            raise AppError(f"generation failed; nothing was published: {safe_error(e)}", code="GENERATION_FAILED", status=500,
                           extra={"review_decision_id": record["review_decision_id"]}) from None
        session = self._save(self.get(session["review_id"]), status="GENERATED", final_pack_id=fp["final_pack_id"])
        self._activity("REVIEW_GENERATED", session, review_decision_id=record["review_decision_id"], final_pack_id=fp["final_pack_id"],
                       version=fp.get("version"), supersedes_final_pack_id=fp.get("supersedes_final_pack_id"))
        return {"decision": record, "session_status": session["status"], "final_pack": fp}

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
