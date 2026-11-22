"""Exception investigation cases: the analyst's own, explicitly opened investigation of ONE exception of ONE pack.

A case records, append-only: supporting evidence, evidence gaps, notes, confirmed observations (always citing evidence),
hypotheses (always labelled as such), human decisions and AI investigation requests. It never changes the pack: the
deterministic exception (its status, review status and every engine result) is shown as recorded and stays as it is.

The case's human_resolution starts UNRESOLVED and changes only through an explicit DECISION entry with a comment. Nothing
resolves a case automatically: not evidence being added, not an explanation (human or AI) being recorded, not an AI
investigation completing. Nothing opens a case automatically either: there is no case for an exception until an analyst
opens one.

AI assistance is requested per case (request_ai): it starts the existing V2 tools-mode investigation job for that one
exception (InvestigationService.start: provider check, one active job per exception, explicit retries) and records the
request in the case. The AI's findings stay in the investigation artefact; the case lists them with their eligibility."""
import re

from .. import ids
from ..clock import now_iso
from ..errors import Conflict, InvalidInput, NotFound, ServiceUnavailable
from ..repositories.base import ConcurrentUpdate, DuplicateRecord

NOTE, EVIDENCE, EVIDENCE_GAP, OBSERVATION, HYPOTHESIS, DECISION, AI_REQUEST = (
    "NOTE", "EVIDENCE", "EVIDENCE_GAP", "OBSERVATION", "HYPOTHESIS", "DECISION", "AI_REQUEST")
ANALYST_KINDS = (NOTE, EVIDENCE, EVIDENCE_GAP, OBSERVATION, HYPOTHESIS, DECISION)
CITING_KINDS = (EVIDENCE, OBSERVATION)  # a confirmed observation or a piece of evidence must cite at least one record
UNRESOLVED, EXPLAINED_BY_ANALYST, ESCALATED = "UNRESOLVED", "EXPLAINED_BY_ANALYST", "ESCALATED"
RESOLUTIONS = (UNRESOLVED, EXPLAINED_BY_ANALYST, ESCALATED)
OPEN, CLOSED = "OPEN", "CLOSED"
DOCUMENT_ID_RE = re.compile(r"^DOC-[0-9a-f]{24}$")
MAX_REFS = 50


class CaseService:
    def __init__(self, settings, repos, packs, investigations):
        self.settings, self.repos, self.packs, self.investigations = settings, repos, packs, investigations

    def _require(self):
        if self.repos.cases is None:
            raise ServiceUnavailable("exception investigation cases need the PostgreSQL database (UC042_DATABASE_URL)",
                                     code="DATABASE_REQUIRED")

    def _activity(self, action, case_id, **details):
        """A case event in the activity log, with the period, pack and exception the case concerns."""
        case = self.repos.cases.get(case_id) or {}
        context = {k: case.get(k) for k in ("period_id", "pack_id", "exception_id") if case.get(k)}
        self.repos.activity.append({"at": now_iso(), "actor": self.settings.analyst_id, "action": action, "entity_type": "case",
                                    "entity_id": case_id, "details": dict(context, **details)})

    def _case(self, case_id):
        self._require()
        case = self.repos.cases.get(ids.check("case_id", case_id))
        if case is None:
            raise NotFound("case not found")
        return case

    # ------------------------------------------------------------------ open and read
    def open(self, pack_id, exception_id):
        """Open the case for one exception, or return the existing one (one case per exception; never a second).
        Returns (case_view, created)."""
        self._require()
        pack = self.packs.load(pack_id)
        self.packs.exception(pack, exception_id)
        existing = self.repos.cases.find(pack_id, exception_id)
        if existing is not None:
            return self.view(existing["case_id"]), False
        period_id = pack["metadata"]["reporting_period"]["period_id"]
        if self.repos.periods.get(period_id) is None:
            raise Conflict(f"the pack's period {period_id} is not registered in the monthly archive", code="PERIOD_NOT_REGISTERED")
        now = now_iso()
        case = {"case_id": ids.new_id("CASE"), "period_id": period_id, "pack_id": pack_id, "exception_id": exception_id,
                "status": OPEN, "human_resolution": UNRESOLVED, "revision": 0, "created_at": now,
                "created_by": self.settings.analyst_id, "updated_at": now}
        try:
            self.repos.cases.create(case)
        except DuplicateRecord:  # opened concurrently: the other request's case is the case
            return self.view(self.repos.cases.find(pack_id, exception_id)["case_id"]), False
        self._activity("CASE_OPENED", case["case_id"], pack_id=pack_id, exception_id=exception_id, period_id=period_id)
        return self.view(case["case_id"]), True

    def list(self, period_id=None, pack_id=None):
        self._require()
        if pack_id is not None:
            ids.check("pack_id", pack_id)
        return self.repos.cases.list(period_id=period_id, pack_id=pack_id)

    def view(self, case_id):
        """The case, its history and the deterministic exception as recorded in the pack (read-only), with the AI
        investigations of the exception and their eligibility. Grouped lists keep confirmed observations, hypotheses,
        evidence gaps and human decisions apart."""
        case = self._case(case_id)
        entries = self.repos.cases.entries(case_id)
        pack = self.packs.load(case["pack_id"])
        exception = self.packs.exception_view(self.packs.exception(pack, case["exception_id"]))
        ai = self.investigations.for_exception(case["pack_id"], case["exception_id"])
        jobs = [self.investigations.job_view(j) for j in self.investigations.runner.repo.list(
            pack_id=case["pack_id"], exception_id=case["exception_id"]) if j["operation"] == "INVESTIGATION"]

        def kind(k):
            return [e for e in entries if e["kind"] == k]
        return dict(case, exception=exception, entries=entries,
                    supporting_evidence=kind(EVIDENCE), evidence_gaps=kind(EVIDENCE_GAP), notes=kind(NOTE),
                    confirmed_observations=kind(OBSERVATION), hypotheses=kind(HYPOTHESIS), human_decisions=kind(DECISION),
                    ai_requests=kind(AI_REQUEST), ai_jobs=jobs,
                    ai_investigations={"published": ai["published"], "not_published": ai["not_published"]},
                    missing_evidence_in_pack=pack["missing_evidence_register"].get("items", []))

    # ------------------------------------------------------------------ entries
    def _valid_refs(self, case, refs):
        """Evidence references must exist: a record or file evidence ID of the pack, a document uploaded for the case's
        period, or a published investigation of this exception. Nothing else is accepted (no free-text evidence)."""
        if not isinstance(refs, list) or len(refs) > MAX_REFS or not all(isinstance(r, str) and 0 < len(r) <= 128 for r in refs):
            raise InvalidInput(f"evidence_refs must be a list of at most {MAX_REFS} identifiers", code="INVALID_EVIDENCE_REF")
        pack = self.packs.load(case["pack_id"])
        known = {r["evidence_id"] for r in pack["evidence_register"]["records"]}
        known |= {f["evidence_id"] for f in pack["evidence_register"]["files"]}
        unknown = []
        for ref in dict.fromkeys(refs):
            if ref in known:
                continue
            if DOCUMENT_ID_RE.match(ref):
                d = self.repos.uploads.document(ref)
                batch = self.repos.uploads.batch(d["batch_id"]) if d else None
                if batch and batch["period_id"] == case["period_id"]:
                    continue
            elif ref.startswith("INV-"):
                published = self.investigations.published(pack, case["exception_id"])["published"]
                if any(p["investigation_id"] == ref for p in published):
                    continue
            unknown.append(ref)
        if unknown:
            raise InvalidInput("unknown evidence reference(s) for this case: " + ", ".join(unknown[:5]), code="INVALID_EVIDENCE_REF",
                               extra={"unknown": unknown})
        return list(dict.fromkeys(refs))

    def add_entry(self, case_id, kind, text, evidence_refs=(), expected_revision=None, resolution=None, close=None):
        case = self._case(case_id)
        if kind not in ANALYST_KINDS:
            raise InvalidInput(f"kind must be one of {', '.join(ANALYST_KINDS)}", code="INVALID_KIND")
        text = re.sub(r"[ \t]+", " ", str(text or "")).strip()
        if not 3 <= len(text) <= 4000:
            raise InvalidInput("text must be 3 to 4000 characters", code="TEXT_REQUIRED")
        if expected_revision is None:
            raise InvalidInput("expected_revision is required (the case revision the entry was written against)",
                               code="REVISION_REQUIRED")
        refs = self._valid_refs(case, list(evidence_refs or []))
        if kind in CITING_KINDS and not refs:
            raise InvalidInput(f"a {kind.lower()} entry must cite at least one evidence reference", code="EVIDENCE_REQUIRED")
        changes, details = {}, {}
        if kind == DECISION:
            if resolution not in RESOLUTIONS:
                raise InvalidInput(f"a decision must set resolution to one of {', '.join(RESOLUTIONS)}", code="RESOLUTION_REQUIRED")
            details = {"resolution": resolution, "previous_resolution": case["human_resolution"],
                       "close": bool(close), "previous_status": case["status"]}
            changes = {"human_resolution": resolution, "status": CLOSED if close else OPEN}
        elif resolution is not None or close is not None:
            raise InvalidInput("only a DECISION entry can set the resolution or close the case", code="DECISION_ONLY")
        elif case["status"] == CLOSED:
            raise Conflict("the case is closed; record a DECISION to reopen it before adding entries", code="CASE_CLOSED")
        entry = {"entry_id": ids.new_id("CE"), "kind": kind, "text": text, "evidence_refs": refs, "details": details,
                 "created_at": now_iso(), "created_by": self.settings.analyst_id}
        try:
            case, entry = self.repos.cases.append_entry(case_id, entry, expected_revision, changes)
        except ConcurrentUpdate:
            raise Conflict("the case has changed since it was read; reload it and try again", code="CASE_CHANGED") from None
        self._activity(f"CASE_{kind}_ADDED" if kind != DECISION else "CASE_DECISION_RECORDED", case_id, entry_id=entry["entry_id"],
                       **({"resolution": resolution, "closed": bool(close)} if kind == DECISION else {}))
        return entry

    # ------------------------------------------------------------------ AI assistance (one case, explicitly requested)
    def request_ai(self, case_id, retry_of=None, note="", confirmation=None):
        """Start the V2 AI investigation of this case's exception, with the analyst's explicit authorisation (recorded
        before the job is submitted). The investigation service refuses a second active job for the exception (duplicate
        submission) and an unconfigured or simulated provider; a retry names the earlier job. The exception and the case
        resolution are not changed by the request or by its result."""
        case = self._case(case_id)
        if case["status"] == CLOSED:
            raise Conflict("the case is closed; reopen it with a DECISION before requesting AI assistance", code="CASE_CLOSED")
        job = self.investigations.start(case["pack_id"], case["exception_id"], retry_of=retry_of, confirmation=confirmation,
                                        case_id=case_id)
        entry = {"entry_id": ids.new_id("CE"), "kind": AI_REQUEST, "text": (str(note or "").strip()[:500] or "AI investigation requested"),
                 "evidence_refs": [], "details": {"job_id": job["job_id"], "retry_of": retry_of}, "created_at": now_iso(),
                 "created_by": self.settings.analyst_id}
        for _ in range(5):  # a system entry: appended at the current revision, whatever the analyst is editing
            try:
                self.repos.cases.append_entry(case_id, entry, self.repos.cases.get(case_id)["revision"])
                break
            except ConcurrentUpdate:
                continue
        self._activity("CASE_AI_REQUESTED", case_id, job_id=job["job_id"], retry_of=retry_of)
        return job
