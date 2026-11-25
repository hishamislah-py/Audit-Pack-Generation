"""Investigations: listing, eligibility, findings and evidence views over the published artefacts (read-only), and
starting V2 tools-mode investigations as background jobs through the existing graph (uc042lib.investigation).

Eligibility for a final pack = the library's check (verify_published, same pack and hash, COMPLETED/VALID, not simulated,
current validation rules) AND the backend's publication registry (the files are the ones registered)."""
import copy
from pathlib import Path

from uc042lib.final_pack.sources import check_eligibility, list_investigations, load_bundle
from uc042lib.investigation import config as inv_config
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import LLMConfigurationError, investigator_from_env, redact
from uc042lib.investigation.persistence import verify_published

from .. import ids
from ..clock import now_iso
from ..errors import Conflict, IntegrityFailure, InvalidInput, NotFound, ServiceUnavailable
from .ai_authorization import AUTHORIZED, INVESTIGATION
from .registry import RegistrationRefused, registry_summary

APPROVED, AUTHORIZATION_DISCREPANCY = "APPROVED", "AUTHORIZATION_DISCREPANCY"
AUTHORIZATION_STATUSES = (APPROVED, AUTHORIZATION_DISCREPANCY)

EVIDENCE_SECTIONS = ("searches", "relationships", "control_results", "conflicts", "missing_evidence", "candidate_relationships")
PUBLISHED_FIELDS = ("investigation_id", "investigation_mode", "investigated_at", "validation_status", "simulated", "provider",
                    "model", "findings_schema_version", "overall_evidence_assessment")


class InvestigationService:
    def __init__(self, settings, packs, registry, runner, locks, investigator_factory=None, authorizations=None, ai_authorizations=None):
        self.settings, self.packs, self.registry, self.runner = settings, packs, registry, runner
        self.locks = locks
        self.investigator_factory = investigator_factory or investigator_from_env
        self.authorizations = authorizations  # decisions about PUBLISHED investigations (None without a database)
        self.ai_authorizations = ai_authorizations  # pre-execution authorisations of AI runs (AiAuthorizationService)
        self._eligibility_cache = {}

    def root_for(self, pack_id):
        """The investigations root of the storage root set holding the pack (published and failed attempts live there)."""
        return Path(self.packs.root_set(pack_id).investigations_root)

    def authorization(self, investigation_id):
        """The authorisation decision in force for a published investigation, or None (the registry alone decides)."""
        return self.authorizations.current(investigation_id) if self.authorizations is not None else None

    def _authorization_signature(self):
        return tuple(sorted((a["investigation_id"], a["id"]) for a in self.authorizations.list())) if self.authorizations else ()

    # ---------------------------------------------------------------- lookup and eligibility
    def locate(self, investigation_id):
        ids.check("investigation_id", investigation_id)
        exception_id = investigation_id[4:-13]
        found = [d for root in self.packs.layout.investigation_roots() for d in root.glob(f"PACK-*/{exception_id}/{investigation_id}")
                 if d.is_dir()]
        if not found:
            raise NotFound("investigation not found")
        if len(found) > 1:
            raise IntegrityFailure("the investigation ID is published under more than one pack", code="DUPLICATE_INVESTIGATION")
        return found[0]

    def _pack_for(self, inv_dir):
        return self.packs.load(inv_dir.parent.parent.name)

    def reasons(self, pack, info):
        """All reasons an investigation is not eligible (library first, then the registry)."""
        reasons = list(info.get("reasons") or [])
        reasons += [f"publication registry: {p}" for p in self.registry.check(Path(info["path"]), pack)]
        return reasons + self.authorization_reasons(info["investigation_id"])

    def authorization_reasons(self, investigation_id):
        a = self.authorization(investigation_id)
        if a is None or a["status"] == APPROVED:
            return []
        return [f"authorisation: {a['status']} - not in the approved published set ({a['basis'][:200]})"]

    def _signature(self, pack, exception_id):
        """Everything eligibility depends on: the artefact files (stat), the registry file (stat), the pack hash and the
        current validation rules. Any change invalidates the cached result."""
        def stat(path):
            try:
                st = path.stat()
                return (str(path), st.st_mtime_ns, st.st_size)
            except OSError:
                return (str(path), None, None)
        root = self.root_for(pack["metadata"]["pack_id"])
        files = sorted(stat(f) for f in (root / pack["metadata"]["pack_id"] / exception_id).rglob("*") if f.is_file())
        failed = sorted(stat(f) for f in (root / "_not_published" / pack["metadata"]["pack_id"] / exception_id).glob("*.json"))
        return (pack["audit_trail"]["pack_content_sha256"], inv_config.FINDINGS_SCHEMA_VERSION, tuple(files), tuple(failed),
                self.registry.signature(), self._authorization_signature())

    def published(self, pack, exception_id):
        """Published investigations of one exception with combined eligibility, plus failed/rejected attempts.
        Cached per (pack, exception) under a signature of every input; the result is recomputed when anything changes."""
        key = (pack["metadata"]["pack_id"], exception_id)
        sig = self._signature(pack, exception_id)
        hit = self._eligibility_cache.get(key)
        if hit and hit[0] == sig:
            return copy.deepcopy(hit[1])
        out = self._published(pack, exception_id)
        self._eligibility_cache[key] = (sig, out)
        return copy.deepcopy(out)

    def _published(self, pack, exception_id):
        found = list_investigations(pack, exception_id, self.root_for(pack["metadata"]["pack_id"]))
        rows = []
        for info in found["published"]:
            reasons = self.reasons(pack, info)
            rows.append(dict({k: info.get(k) for k in PUBLISHED_FIELDS}, eligible=not reasons, ineligible_reasons=reasons,
                             library_eligible=info["eligible"], registry=self._registry_row(info["investigation_id"]),
                             authorization=self._authorization_view(info["investigation_id"])))
        return {"published": rows, "not_published": found["not_published"]}

    def _authorization_view(self, investigation_id):
        a = self.authorization(investigation_id)
        return None if a is None else {k: a[k] for k in ("status", "basis", "recorded_at", "recorded_by")}

    def _registry_row(self, investigation_id):
        try:
            return registry_summary(self.registry.entry_for(investigation_id))
        except IntegrityFailure:
            return None

    def for_exception(self, pack_id, exception_id, pack=None):
        pack = pack if pack is not None else self.packs.load(pack_id)
        self.packs.exception(pack, exception_id)
        out = self.published(pack, exception_id)
        out["active_jobs"] = [self.job_view(j) for j in self.runner.active(pack_id, exception_id, "INVESTIGATION")]
        return dict(out, pack_id=pack_id, exception_id=exception_id)

    def for_pack(self, pack_id, pack=None):
        """Every exception's investigations. The pack is loaded (verified and copied) once, not once per exception: the
        period list and archive call this for every pack of every month. A caller may pass the pack it already loaded."""
        pack = pack if pack is not None else self.packs.load(pack_id)
        return [self.for_exception(pack_id, e, pack) for e in self.packs.exception_ids(pack)]

    # ---------------------------------------------------------------- reads
    def detail(self, investigation_id):
        d = self.locate(investigation_id)
        pack = self._pack_for(d)
        bundle = load_bundle(d)
        f = bundle["findings"]
        library = check_eligibility(bundle, pack)
        registry = [f"publication registry: {p}" for p in self.registry.check(d, pack)]
        registry += self.authorization_reasons(investigation_id)
        m = f.get("model_metadata") or {}
        return {"investigation_id": investigation_id, "pack_id": f.get("pack_id"), "exception_id": f.get("exception_id"),
                "investigation_mode": f.get("investigation_mode", "fixed"), "investigated_at": f.get("investigated_at"),
                "investigation_status": f.get("investigation_status"), "validation_status": f.get("validation_status"),
                "overall_evidence_assessment": f.get("overall_evidence_assessment"),
                "investigation_summary": f.get("investigation_summary"), "exception_resolution": f.get("exception_resolution"),
                "model": {k: m.get(k) for k in ("provider", "model", "prompt_version", "findings_schema_version",
                                                "workflow_version", "simulated")},
                "tool_summary": f.get("tool_summary"), "classification_summary": f.get("classification_summary"),
                "findings_sha256": bundle["findings_sha256"], "eligible": not (library or registry),
                "ineligible_reasons": library + registry, "registry": self._registry_row(investigation_id),
                "authorization": self._authorization_view(investigation_id)}

    def findings(self, investigation_id):
        """The findings exactly as stored (a read; nothing is recomputed)."""
        return load_bundle(self.locate(investigation_id))["findings"]

    def evidence(self, investigation_id, offset=0, limit=50, evidence_id=None):
        """Evidence the findings were validated against: the accumulated ledger (tools mode) or the packet (fixed mode).
        Only records already in that artefact are returned; there is no search over source files."""
        bundle = load_bundle(self.locate(investigation_id))
        source = bundle["ledger"] or bundle["packet"]
        records = source.get("source_records") or []
        if evidence_id is not None:
            records = [r for r in records if r.get("evidence_id") == evidence_id]
            if not records:
                raise NotFound("evidence ID not in this investigation's evidence")
        return {"investigation_id": investigation_id, "source": "evidence_ledger" if bundle["ledger"] else "evidence_packet",
                "sha256": source.get("ledger_sha256") or source.get("packet_sha256"), "total_records": len(records),
                "offset": offset, "limit": limit, "source_records": records[offset:offset + limit],
                "allowed_citation_ids": source.get("allowed_citation_ids", []),
                **{k: source.get(k, []) for k in EVIDENCE_SECTIONS}}

    def tool_calls(self, investigation_id):
        """The recorded tool calls of a tools-mode investigation (metadata only: tool, arguments, status, evidence IDs; the
        records themselves are in the evidence ledger). Fixed-mode investigations made none."""
        bundle = load_bundle(self.locate(investigation_id))
        t = bundle["tool_calls"] or {}
        return {"investigation_id": investigation_id, "tool_registry_version": t.get("tool_registry_version"),
                "summary": t.get("summary") or bundle["findings"].get("tool_summary"), "tool_calls": t.get("tool_calls") or []}

    def source_evidence(self, pack_id, exception_id):
        """The exception's supporting source records WITHOUT any AI: the deterministic, approved retrieval an investigation
        starts from (uc042lib.investigation.packet: the exception's cited records and the route's verified joins over the
        pack's hash-checked source files; no answer keys or verification material can be read). Nothing is written."""
        from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
        from uc042lib.investigation.retrieval import EvidenceStore, RetrievalError
        from uc042lib.investigation.routing import route_for
        pack = self.packs.load(pack_id)
        self.packs.exception(pack, exception_id)
        case = build_case(pack, exception_id)
        route = route_for(case["exception"], case["candidates"], case["results"])
        try:
            col = retrieve(route, case, EvidenceStore(pack, self.datasets_root_for(pack_id)))
        except RetrievalError as e:
            raise Conflict(f"the source records cannot be retrieved: {e}", code="SOURCE_UNAVAILABLE") from None
        packet = build_packet(case, build_scope(case), route, col)
        records = packet.get("source_records") or []
        return {"pack_id": pack_id, "exception_id": exception_id, "source": "deterministic_retrieval", "route": route,
                "sha256": packet.get("packet_sha256"), "total_records": len(records), "offset": 0, "limit": len(records),
                "source_records": records, "allowed_citation_ids": packet.get("allowed_citation_ids", []),
                **{k: packet.get(k, []) for k in EVIDENCE_SECTIONS}}

    def verify(self, investigation_id):
        d = self.locate(investigation_id)
        pack = self._pack_for(d)
        bundle = load_bundle(d)
        artefact = verify_published(d)
        registry = self.registry.check(d, pack)
        library = check_eligibility(bundle, pack)
        authorization = self.authorization_reasons(investigation_id)
        return {"investigation_id": investigation_id, "artefact_verified": not artefact, "artefact_problems": artefact,
                "registry_verified": not registry, "registry_problems": registry,
                "eligible": not (library or registry or authorization),
                "ineligible_reasons": library + [f"publication registry: {p}" for p in registry] + authorization}

    # ---------------------------------------------------------------- jobs
    @staticmethod
    def job_view(job):
        return dict({k: job.get(k) for k in ("job_id", "operation", "pack_id", "exception_id", "status", "submitted_at", "started_at",
                                             "completed_at", "error_summary", "result", "retry_of")},
                    authorization_id=(job.get("inputs") or {}).get("authorization_id"))

    def _investigator(self):
        try:
            inv = self.investigator_factory()
        except LLMConfigurationError as e:
            raise ServiceUnavailable(f"the AI provider is not configured: {redact(str(e))[:200]}", code="PROVIDER_NOT_CONFIGURED") from None
        if getattr(inv, "simulated", False):
            raise ServiceUnavailable("the offline simulated provider cannot produce AI analysis; configure "
                                     "UC042_LLM_PROVIDER=openai", code="PROVIDER_NOT_CONFIGURED")
        if not getattr(inv, "supports_tools", False):
            raise InvalidInput(f"provider {getattr(inv, 'provider', '?')!r} does not support tools mode", code="MODE_UNSUPPORTED")
        return inv

    def start(self, pack_id, exception_id, retry_of=None, confirmation=None, case_id=None):
        """Queue a V2 tools-mode investigation (one active job per exception), only with the analyst's explicit
        authorisation (ai_authorization). The authorisation is recorded before the job is submitted, so no model call can
        start without it; a refused request is recorded with its reason."""
        auth = self.ai_authorizations
        with self.locks.hold(pack_id):
            pack = self.packs.load(pack_id)
            self.packs.exception(pack, exception_id)
            config, changed = auth.require(INVESTIGATION, confirmation)
            context = {"exception_id": exception_id, "case_id": case_id}
            if changed:
                auth.changed(INVESTIGATION, changed, pack_id, config, **context)
            active = self.runner.active(pack_id, exception_id, "INVESTIGATION")
            if active:
                auth.refuse(INVESTIGATION, Conflict("an investigation of this exception is already queued or running",
                                                    code="INVESTIGATION_ACTIVE", extra={"job_id": active[0]["job_id"]}),
                            pack_id, config, active_job_id=active[0]["job_id"], **context)
            if retry_of is not None:
                previous = self.runner.repo.get(ids.check("job_id", retry_of))
                if previous is None or previous["pack_id"] != pack_id or previous.get("exception_id") != exception_id:
                    raise InvalidInput("retry_of must name an earlier job for the same exception")
            try:
                investigator = self._investigator()
            except (ServiceUnavailable, InvalidInput) as e:
                auth.refuse(INVESTIGATION, e, pack_id, config, **context)
            authorization_id = ids.new_id("AIA")
            job = self.runner.create("INVESTIGATION", pack_id, self.settings.analyst_id, exception_id,
                                     {"mode": "tools", "workflow_version": inv_config.TOOLS_WORKFLOW_VERSION,
                                      "authorization_id": authorization_id}, retry_of)
            try:
                auth.record(INVESTIGATION, AUTHORIZED, pack_id, config, job_id=job["job_id"], authorization_id=authorization_id,
                            provider=getattr(investigator, "provider", None), model=getattr(investigator, "model", None),
                            retry_of=retry_of, **context)
            except Exception:  # no recorded authorisation: the job never runs
                self.runner.repo.update(job["job_id"], {"status": "FAILED", "completed_at": now_iso(),
                                                        "error_summary": "the authorisation could not be recorded; nothing was run"})
                raise
            self.runner.submit(job, lambda j: self._execute(j, investigator))
        return job

    def datasets_root_for(self, pack_id):
        """Where the pack's source rows are: the POC scenario datasets, or (for a pack produced by a monthly processing
        run) that run's prepared case folder in the document store. Only prepared source files are in a case folder."""
        dataset = self.packs.load(pack_id)["metadata"]["source_dataset"].get("dataset", "")
        datasets_root = Path(self.packs.root_set(pack_id).datasets_root)
        store = self.settings.document_store
        if dataset and store and not (datasets_root / dataset).is_dir() and (Path(store) / "cases" / dataset / "source_data").is_dir():
            return Path(store) / "cases"
        return datasets_root

    def _execute(self, job, investigator):
        roots = self.packs.root_set(job["pack_id"])
        state = run_investigation(job["pack_id"], job["exception_id"], investigator, packs_root=roots.packs_root,
                                  datasets_root=self.datasets_root_for(job["pack_id"]),
                                  investigations_root=Path(roots.investigations_root), mode="tools",
                                  tool_limits=inv_config.tool_limits())
        outcome, res = state.get("persist_outcome"), state.get("result") or {}
        result = {"persist_outcome": outcome, "investigation_status": res.get("investigation_status"),
                  "validation_status": res.get("validation_status"), "investigation_id": None, "registered": False,
                  "tool_summary": res.get("tool_summary")}
        if outcome not in ("PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL"):
            reason = res.get("failure_reason") or "; ".join((res.get("validation_findings") or [])[:3]) or str(outcome)
            return "FAILED", result, redact(reason)[:500]
        inv_dir = Path(state["artefact_path"])
        result["investigation_id"] = inv_dir.name
        try:
            entry, _ = self.registry.register_new(inv_dir, self.packs.load(job["pack_id"]), job["submitted_by"])
        except (RegistrationRefused, IntegrityFailure) as e:
            return "FAILED", result, f"published but not registered: {getattr(e, 'detail', str(e))[:300]}"
        result.update(registered=True, registry_seq=entry["seq"], registry_record_type=entry["record_type"])
        return "COMPLETED", result, ""
