"""Phase 3B-6 / 3B-7 - deterministic-first, LLM-assisted mapping orchestration (integration of existing components).

    CSV bytes -> [3B-7 HEADER-COUNT GATE, only when a category is supplied and it is a controlled UC-042 CSV category]
       |- incoming column count != the category's field count -> DIRECT HUMAN_REVIEW: a column-review case
       |     (review.intake) is opened; NO deterministic mapping, NO proposal / LLM call, NO policy, NO rule, NO preview
       '- equal counts -> pipeline (classification + controlled mapping; supplied category goes through the 3B-0 check)
       |- fully mapped ---------------------------------------------> DETERMINISTIC -> reprocess -> handoff check -> preview
       |- not mapped, no category supplied -------------------------> REJECT_OR_HOLD (the LLM never decides a category)
       '- not mapped, category supplied -> ProposalGateway (3B-4: eligibility, dedup, budget, audit; ONLY unresolved
          headers, no values) -> validate_proposal (3B-1) -> POC policy (orchestration.policy)
             |- AUTO_ACCEPT    -> file-specific mapping (approval kind POC_AUTO) + POC category confirmation
             |                    -> deterministic reprocess (no LLM) -> 14-point handoff check -> PREVIEW
             |- HUMAN_REVIEW   -> a review session (3B-2 state machine) is opened as PROPOSED; nothing applied
             '- REJECT_OR_HOLD -> nothing applied; reasons returned

Equal counts with deterministic duplicate claims (several columns claim one canonical field) also open a column-review
case (kind DETERMINISTIC_CONFLICT) and route to HUMAN_REVIEW whatever the proposal outcome (3B-7). A decided case is
completed by `complete_case`: governed file mapping (MAP / IGNORE per position) -> deterministic reprocess -> handoff
check -> preview only when everything passes.

Nothing here creates a reusable alias or layout, touches the production rules or authority policy, or sends a value.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..ai.gateway import ProposalGateway
from ..csv_engine.reader import CsvReadError, read_csv
from ..handoff.eligibility import HandoffEligibility, HandoffPolicy, check_handoff
from ..handoff.reprocess import ReprocessResult, reprocess
from ..handoff.writer import write_preview
from ..identify.detect import IdentificationError, identify
from ..intake.store import EvidenceStore, validate_reporting_period
from ..mapping.controlled import controlled_map, is_controlled
from ..mapping.governed import Approval, ColumnRule, FileMappingRule, header_fingerprint
from ..mapping.proposal_runner import ProposalOutcome, build_request
from ..mapping.rule_store import RuleStore
from ..models.enums import FileFormat
from ..models.results import EvidenceResult
from ..pipeline import SmartParser
from ..review.approvals import CategoryConfirmation
from ..review.audit import AuditLog
from ..review.intake import (CaseContext, CaseState, ColumnReviewCase, case_context, deterministic_suggestions,
                             finalise_case, open_case)
from ..review.session import ReviewError, ReviewSession, start_session
from .policy import POC_ACTOR, POC_ROLE, Decision, PocAutoAcceptPolicy, decide


@dataclass
class WorkflowResult:
    decision: Decision
    reasons: list[str]
    intake_id: str
    source_sha256: str
    supplied_category: str | None
    category: str | None
    initial: EvidenceResult | None = None      # None when the header-count gate stopped the file before the pipeline
    route: str = ""        # HEADER_COUNT_GATE | DETERMINISTIC | NO_CATEGORY | PROPOSAL | CASE_RESOLVED | CASE_HELD
    intake_case: ColumnReviewCase | None = None
    unresolved_headers: list[str] = field(default_factory=list)
    resolved_columns: dict[str, str] = field(default_factory=dict)   # header -> canonical field (deterministic)
    proposer_calls: int = 0
    proposal: ProposalOutcome | None = None
    review_session: ReviewSession | None = None
    file_mapping: FileMappingRule | None = None
    confirmation: CategoryConfirmation | None = None
    reprocessed: ReprocessResult | None = None
    eligibility: HandoffEligibility | None = None
    preview: dict | None = None


class MappingOrchestrator:
    def __init__(self, registry, store: RuleStore, evidence: EvidenceStore, gateway: ProposalGateway,
                 poc_policy: PocAutoAcceptPolicy, log: AuditLog, preview_dir: str | Path | None = None,
                 handoff_policy: HandoffPolicy = HandoffPolicy()):
        if evidence.root is None:
            raise ValueError("the orchestrator needs a persistent evidence store (originals are reprocessed)")
        self.registry, self.store, self.evidence, self.gateway = registry, store, evidence, gateway
        self.poc, self.log, self.preview_dir, self.handoff_policy = poc_policy, log, preview_dir, handoff_policy

    # ------------------------------------------------------------------ main entry
    def process(self, data: bytes, filename: str, reporting_period: str | None = None,
                category: str | None = None) -> WorkflowResult:
        rules = self.store.load()
        if category is not None:
            gated = self._header_count_gate(data, filename, reporting_period, category, rules)
            if gated is not None:
                return gated
        res = SmartParser(schemas=self.registry, store=self.evidence, mapping_rules=rules).process_bytes(
            data, filename, reporting_period, forced_category=category)
        m = res.metadata
        wr = WorkflowResult(decision=Decision.REJECT_OR_HOLD, reasons=[], intake_id=m.evidence_id,
                            source_sha256=m.sha256, supplied_category=category, category=m.evidence_category,
                            initial=res, route="PROPOSAL")
        if m.classification_status == "identified" and m.mapping_status == "complete":
            variants = self._variant_columns(res, m.evidence_category, rules)
            if variants:                          # O2: a variant is never recognised automatically at intake
                return self._open_variant_case(wr, res, m.evidence_category, rules, variants, None)
            wr.decision, wr.route = Decision.DETERMINISTIC, "DETERMINISTIC"
            wr.reasons = [f"mapped by the deterministic rules ({res.classification.method.value}); no proposal requested"]
            return self._finish(wr, rules, confirmation=None)
        if category is None:
            wr.route = "NO_CATEGORY"
            wr.reasons = ["not mapped deterministically and no category was supplied: the LLM never decides the "
                          "evidence category; a person must confirm it"]
            return wr
        oc = self.gateway.propose(res, self.registry, rules)
        wr.proposal, wr.proposer_calls = oc, int(oc.proposer_called)
        request = oc.request
        if request is None and oc.eligible:
            # no call was made (gate denied): the unresolved set and resolved context are still known deterministically,
            # so a person reviewing the held file sees exactly what is unresolved
            request = build_request(res, self.registry.get(category), rules)[0]
        if request is not None:
            wr.unresolved_headers = [u.source_header for u in request.unresolved_columns]
            wr.resolved_columns = {c.source_header: c.canonical_field for c in request.resolved_columns}
        dup = self._deterministic_duplicates(res, category, rules)
        variants = self._variant_columns(res, category, rules)
        if variants and not dup and oc.eligible and oc.record is not None and not oc.record.response_error:
            # O2: variant columns would otherwise enter the proposal session as fixed "resolved" context (or be
            # auto-accepted by an enabled POC policy). They go to a column review with the proposal as suggestions.
            return self._open_variant_case(wr, res, category, rules, variants, oc.record)
        if not oc.eligible:
            wr.reasons = [oc.reason]
            if dup:     # 3B-7: duplicate claims go to a person even when no proposal can be made
                return self._open_conflict_case(wr, res, category, rules, dup, None)
            return wr
        pd = decide(oc.record, self.poc, error=None if oc.record else oc.reason)
        if dup and pd.decision != Decision.HUMAN_REVIEW:
            # 3B-7: a deterministic conflict is a human decision whatever the proposal outcome (never HOLD, never AUTO)
            pd.decision, pd.reasons = Decision.HUMAN_REVIEW, [
                f"deterministic conflict: more than one incoming column claims {dup}"] + pd.reasons
        if pd.decision == Decision.AUTO_ACCEPT and not self.poc.accept_supplied_category:
            pd.decision, pd.reasons = Decision.HUMAN_REVIEW, [
                "the category was supplied by the caller; the POC policy does not accept a supplied category as "
                "confirmed - a person must confirm it"]
        wr.decision, wr.reasons = pd.decision, pd.reasons
        self.log.append("POC_AUTO_DECISION", actor_id=f"{POC_ACTOR}:{self.poc.policy_id}", actor_role=POC_ROLE,
                        approval_kind="POC_AUTO" if pd.decision == Decision.AUTO_ACCEPT else None,
                        proposal_id=oc.record.proposal_id if oc.record else None, intake_id=m.evidence_id,
                        source_sha256=m.sha256, details={"decision": pd.decision.value, "reasons": pd.reasons,
                                                         "policy_id": self.poc.policy_id})
        no_match = [c for c in (oc.record.columns if oc.record else []) if str(c.validation_class) == "NO_MATCH"]
        if pd.decision == Decision.HUMAN_REVIEW and no_match and not dup:
            # 3B-11: UNMAPPABLE -> one column-review case (MAP / CHANGE / IGNORE / LEAVE_UNRESOLVED / REJECT) seeded with
            # the deterministic matches and the validated proposal; no parallel proposal session
            return self._open_unmappable_case(wr, res, category, rules, oc.record, no_match)
        if pd.decision == Decision.HUMAN_REVIEW:
            if oc.record is not None and not oc.record.response_error and oc.request is not None:
                wr.review_session = start_session(oc.record, oc.request, list(res.csv_extraction.raw_headers),
                                                  self.log)
            if dup:
                return self._open_conflict_case(wr, res, category, rules, dup, oc.record, keep_reasons=True)
            return wr
        if pd.decision == Decision.REJECT_OR_HOLD:
            return wr
        wr.file_mapping, wr.confirmation = self._auto_accept(oc, res, pd.accepted_columns, pd.reasons)
        self.gateway.dedup.close(oc.record.proposal_id)          # accepted: no longer pending
        return self._finish(wr, self.store.load(), wr.confirmation)

    # ------------------------------------------------------------------ 3B-7 header-count gate
    def _header_count_gate(self, data: bytes, filename: str, reporting_period: str | None, category: str,
                           rules) -> WorkflowResult | None:
        """None -> equal counts (or the gate does not apply): the normal pipeline runs. Otherwise the file is stored as
        an intake and a HEADER_COUNT_MISMATCH case is opened; nothing is mapped, proposed or applied."""
        schema = self.registry.get(category)
        if schema is None:
            raise ValueError(f"Unknown category '{category}'")
        if not is_controlled(schema):
            return None               # synthetic / provisional / stub schemas keep the existing behaviour
        try:
            ident = identify(data, filename)
            if ident.detected_format != FileFormat.CSV:
                return None           # not a CSV: the pipeline reports it (unsupported / PDF / ...)
            table = read_csv(data, ident.encoding, ident.delimiter)
        except (IdentificationError, CsvReadError):
            return None               # unreadable: the pipeline reports the precise error
        if table.error:
            return None               # malformed CSV: the pipeline reports it; no count decision on a partial read
        raw = list(table.raw_headers)
        if len(raw) == len(schema.fields):
            return None
        period = validate_reporting_period(reporting_period)
        rec = self.evidence.save(data, filename, period)
        content_cat = self.registry.exact_header_index().get(tuple(table.headers))
        content = {"category": content_cat, "method": "csv_exact_header"} if content_cat else None
        case = open_case("HEADER_COUNT_MISMATCH", rec.evidence_id, rec.sha256, rec.original_filename, schema, raw,
                         rules, self.log, content_classification=content)
        diff = len(raw) - len(schema.fields)
        reasons = [f"header-count gate: the file has {len(raw)} column(s), {category} has {len(schema.fields)} "
                   f"field(s) ({diff:+d}); routed directly to a person - no deterministic mapping, no LLM proposal, "
                   "no automatic decision"]
        if case.duplicate_incoming_headers:
            reasons.append(f"duplicate incoming headers: {case.duplicate_incoming_headers}")
        if content_cat and content_cat != category:
            reasons.append(f"by its exact header the file identifies as {content_cat}; the supplied category is not "
                           "replaced automatically")
        return WorkflowResult(decision=Decision.HUMAN_REVIEW, reasons=reasons, intake_id=rec.evidence_id,
                              source_sha256=rec.sha256, supplied_category=category, category=None,
                              initial=None, route="HEADER_COUNT_GATE", intake_case=case)

    def _deterministic_duplicates(self, res: EvidenceResult, category: str, rules) -> dict[str, list[str]]:
        schema = self.registry.get(category)
        if res.csv_extraction is None or not is_controlled(schema):
            return {}
        return controlled_map(list(res.csv_extraction.raw_headers), schema, rules).duplicate_fields

    def _open_conflict_case(self, wr: WorkflowResult, res: EvidenceResult, category: str, rules,
                            dup: dict[str, list[str]], record, keep_reasons: bool = False) -> WorkflowResult:
        schema = self.registry.get(category)
        raw = list(res.csv_extraction.raw_headers)
        usable = record if record is not None and not record.response_error else None
        sugg = deterministic_suggestions(raw, schema, rules, usable.columns if usable else None)
        cc = (res.classification.details or {}).get("content_classification") if res.classification else None
        content = {"category": cc["category"], "method": cc["method"]} if cc and cc.get("category") else None
        wr.intake_case = open_case("DETERMINISTIC_CONFLICT", wr.intake_id, wr.source_sha256,
                                   res.metadata.original_filename, schema, raw, rules, self.log, suggestions=sugg,
                                   content_classification=content,
                                   proposal_id=usable.proposal_id if usable else None)
        wr.decision = Decision.HUMAN_REVIEW
        if not keep_reasons:
            wr.reasons = [f"deterministic conflict: more than one incoming column claims {dup}; a person chooses the "
                          "authoritative column"] + wr.reasons
        return wr

    # ------------------------------------------------------------------ owner decision O2 (intake)
    VARIANT_MATCHES = ("case", "whitespace", "case+whitespace", "alias")

    def _variant_columns(self, res: EvidenceResult, category: str | None, rules) -> list[dict]:
        """Columns the controlled rules match to a canonical field only through a variant (letter case, whitespace or an
        approved alias). Exact headers, reordering, and the analyst's own file-specific mapping for THIS upload (applied
        only at reprocessing) are not variants. File-specific mappings never take part here (no file identity)."""
        schema = self.registry.get(category) if category else None
        if res.csv_extraction is None or not is_controlled(schema):
            return []
        cm = controlled_map(list(res.csv_extraction.raw_headers), schema, rules.without_file_identity())
        return [m for m in cm.mappings if m["match"] in self.VARIANT_MATCHES]

    def _open_variant_case(self, wr: WorkflowResult, res: EvidenceResult, category: str, rules, variants: list[dict],
                           record) -> WorkflowResult:
        schema = self.registry.get(category)
        raw = list(res.csv_extraction.raw_headers)
        usable = record if record is not None and not record.response_error else None
        sugg = deterministic_suggestions(raw, schema, rules.without_file_identity(), usable.columns if usable else None)
        cls = res.classification
        content = {"category": cls.category, "method": cls.method.value} if cls and cls.category and cls.method else None
        listed = ", ".join(f"#{v['source_position'] + 1} {v['source_header']!r} ~ {v['canonical_field']} ({v['match']})"
                           for v in variants)
        reason = (f"header variant(s) not recognised automatically (owner decision O2): {listed}; the category "
                  f"{category} is established by the complete header, a person decides each variant column")
        wr.intake_case = open_case("HEADER_VARIANT", wr.intake_id, wr.source_sha256, res.metadata.original_filename,
                                   schema, raw, rules.without_file_identity(), self.log, suggestions=sugg,
                                   content_classification=content,
                                   proposal_id=usable.proposal_id if usable else None,
                                   proposal_columns=usable.columns if usable else None, review_reason=reason)
        wr.decision, wr.route = Decision.HUMAN_REVIEW, "HEADER_VARIANT"
        wr.reasons = [reason] + [r for r in wr.reasons if r != reason]
        return wr

    def _open_unmappable_case(self, wr: WorkflowResult, res: EvidenceResult, category: str, rules, record,
                              no_match) -> WorkflowResult:
        schema = self.registry.get(category)
        raw = list(res.csv_extraction.raw_headers)
        sugg = deterministic_suggestions(raw, schema, rules, record.columns)
        reason = ("the LLM proposal found no defensible canonical field for: " +
                  ", ".join(c.source_header for c in no_match) +
                  (f"; required field(s) not covered: {record.summary.required_fields_unresolved}"
                   if record.summary.required_fields_unresolved else "") + " - a person decides")
        wr.intake_case = open_case("UNMAPPABLE_PROPOSAL", wr.intake_id, wr.source_sha256,
                                   res.metadata.original_filename, schema, raw, rules, self.log, suggestions=sugg,
                                   proposal_id=record.proposal_id, proposal_columns=record.columns,
                                   review_reason=reason)
        wr.decision = Decision.HUMAN_REVIEW
        wr.reasons = [reason] + [r for r in wr.reasons if r != reason]
        return wr

    # ------------------------------------------------------------------ 3B-7 completing a column-review case
    def case_context(self, case: ColumnReviewCase) -> CaseContext:
        return case_context(case, self.evidence, self.registry, self.store.load())

    def complete_case(self, case: ColumnReviewCase, reviewers, basis: str, authority, ctx: CaseContext | None = None,
                      category_reviewer=None) -> WorkflowResult:
        """Finalise a decided case. HELD -> REJECT_OR_HOLD (nothing written). RESOLVED -> governed file mapping +
        category confirmation -> deterministic reprocess (no LLM) -> handoff check -> preview only if eligible.

        3B-8: the stored original is ALWAYS re-verified here (SHA-256, intake, header) before anything is written, so a
        file changed after review can no longer leave an active rule, a category confirmation and a RESOLVED case behind
        (previously a context computed before the change was trusted and only reprocessing noticed it)."""
        fresh = self.case_context(case)                     # raises ReviewError on a changed / missing original
        if ctx is not None and (ctx.raw_headers != fresh.raw_headers or ctx.samples != fresh.samples):
            raise ReviewError("the review context no longer matches the stored original")
        ctx = fresh
        rule, conf = finalise_case(case, reviewers, basis, authority, self.store, self.log, self.registry, ctx,
                                   category_reviewer=category_reviewer)
        wr = WorkflowResult(decision=Decision.REJECT_OR_HOLD, reasons=[], intake_id=case.intake_id,
                            source_sha256=case.source_sha256, supplied_category=case.category, category=None,
                            route="CASE_HELD", intake_case=case)
        if case.state == CaseState.HELD:
            s = case.final_summary
            wr.reasons = [f"case {case.case_id} HELD: unresolved column(s) {s['unresolved_positions']}, required "
                          f"field(s) not mapped {s['missing_required_fields']}"]
            return wr
        wr.decision, wr.route, wr.file_mapping, wr.confirmation = Decision.HUMAN_REVIEW, "CASE_RESOLVED", rule, conf
        wr.reasons = [f"case {case.case_id} RESOLVED by {', '.join(r.reviewer_id for r in reviewers)}: file mapping "
                      f"{rule.file_mapping_id}, {len(case.final_summary['ignored_positions'])} column(s) ignored"]
        return self._finish(wr, self.store.load(), conf)

    # ------------------------------------------------------------------ 3B-9 completing an APPROVED proposal session
    def complete_session(self, session: ReviewSession, reviewers, basis: str, authority,
                         category_reviewer=None, content_category: str | None = None) -> WorkflowResult:
        """The proposal-review counterpart of complete_case (3B-8 finding P1-7): an APPROVED session whose decisions
        cover every column and required field -> category confirmation + governed file mapping -> deterministic
        reprocess -> handoff -> preview. An approved but INCOMPLETE session writes nothing (REJECT_OR_HOLD). The stored
        original is re-verified first. Reuses review.approvals unchanged (same authority scopes)."""
        from ..review.approvals import approve_file_mapping, confirm_category
        from ..review.session import ReviewState
        if session.state != ReviewState.APPROVED:
            raise ReviewError(f"only an APPROVED session can be completed, not {session.state}")
        rec = self.evidence.find(session.intake_id)
        data = self.evidence.read_original(session.source_sha256)
        if rec is None or rec.sha256 != session.source_sha256 or data is None \
                or hashlib.sha256(data).hexdigest() != session.source_sha256:
            raise ReviewError("the stored original is missing or does not match the session's SHA-256")
        wr = WorkflowResult(decision=Decision.REJECT_OR_HOLD, reasons=[], intake_id=session.intake_id,
                            source_sha256=session.source_sha256, supplied_category=session.category, category=None,
                            route="SESSION_HELD", review_session=session)
        summary = session.final_summary or {}
        if not summary.get("complete"):
            wr.reasons = [f"session {session.session_id} approved but incomplete: missing required "
                          f"{summary.get('missing_required_fields')}, unmapped {summary.get('unmapped_columns')}"]
            return wr
        conf = confirm_category(session.intake_id, session.source_sha256, session.category,
                                category_reviewer or reviewers[0], basis, authority, self.log, self.registry,
                                content_category=content_category)
        rule = approve_file_mapping(session, reviewers, basis, authority, self.store, self.log)
        self.gateway.dedup.close(session.proposal_id)
        wr.decision, wr.route, wr.file_mapping, wr.confirmation = Decision.HUMAN_REVIEW, "SESSION_RESOLVED", rule, conf
        wr.reasons = [f"session {session.session_id} approved by {', '.join(r.reviewer_id for r in reviewers)}: "
                      f"file mapping {rule.file_mapping_id}"]
        return self._finish(wr, self.store.load(), conf)

    # ------------------------------------------------------------------ helpers
    def _auto_accept(self, oc: ProposalOutcome, res: EvidenceResult, accepted: dict[int, str], reasons: list[str]):
        rec, req = oc.record, oc.request
        headers = list(res.csv_extraction.raw_headers)
        resolved = {c.source_index: c.canonical_field for c in req.resolved_columns}
        at = self.log.clock()
        actor = f"{POC_ACTOR}:{self.poc.policy_id}"
        basis = "; ".join(reasons)
        rule = FileMappingRule(
            file_mapping_id=f"FM-POC-{uuid.uuid4().hex[:10]}", rule_version=1, category=rec.confirmed_category,
            intake_id=rec.intake_id, source_sha256=rec.source_sha256, review_session_id=f"poc-auto:{rec.proposal_id}",
            headers=headers, header_fingerprint=header_fingerprint(headers),
            columns=[ColumnRule(source_index=i, source_header=h, canonical_field=resolved.get(i, accepted.get(i)))
                     for i, h in enumerate(headers)],
            approvals=[Approval(approver_id=actor, approver_role=POC_ROLE, approval_kind="POC_AUTO", approved_at=at,
                                basis=basis)],
            registry_definition_sha256=rec.registry_definition_sha256, mapping_rules_version=rec.mapping_rules,
            proposal_id=rec.proposal_id, decision_ids=[f"poc-auto-decision:{rec.proposal_id}"])
        self.store.add_file_mapping(rule)
        for ev in ("RULE_CREATED", "RULE_ACTIVATED"):
            self.log.append(ev, actor_id=actor, actor_role=POC_ROLE, approval_kind="POC_AUTO", proposal_id=rec.proposal_id,
                            rule_id=rule.file_mapping_id, intake_id=rec.intake_id, source_sha256=rec.source_sha256,
                            details={"scope": "FILE_MAPPING", "rule_version": 1, "category": rec.confirmed_category,
                                     "reusable": False})
        conf = CategoryConfirmation(
            confirmation_id=f"POC-{uuid.uuid4().hex[:12]}", intake_id=rec.intake_id, source_sha256=rec.source_sha256,
            category=rec.confirmed_category, reviewer_id=actor, reviewer_role=POC_ROLE, approval_kind="POC_AUTO",
            confirmed_at=at, basis="category supplied by the caller and accepted as confirmed by the POC policy")
        self.log.append("CATEGORY_CONFIRMED", actor_id=actor, actor_role=POC_ROLE, approval_kind="POC_AUTO",
                        intake_id=rec.intake_id, source_sha256=rec.source_sha256,
                        details={"confirmation_id": conf.confirmation_id, "category": conf.category,
                                 "scope": "POC_SUPPLIED_CATEGORY"})
        return rule, conf

    def _finish(self, wr: WorkflowResult, rules, confirmation) -> WorkflowResult:
        rr = reprocess(wr.intake_id, self.evidence, self.registry, rules, confirmation)
        wr.reprocessed, wr.category = rr, rr.category
        wr.eligibility = check_handoff(rr, self.registry, self.handoff_policy)
        # 3B-8: the declared REPROCESSED / HANDOFF_* event types were never emitted - outcomes are now auditable
        actor = {"actor_id": "smartparser-orchestrator", "actor_role": "system", "intake_id": wr.intake_id,
                 "source_sha256": wr.source_sha256}
        self.log.append("REPROCESSED", **actor, details={
            "category": rr.category, "category_basis": rr.category_basis, "confirmation_id": rr.confirmation_id,
            "rules_used": rr.rules_used, "provider_calls": rr.provider_calls, "route": wr.route,
            "case_id": wr.intake_case.case_id if wr.intake_case else None})
        self.log.append("HANDOFF_EVALUATED", **actor, details={
            "eligible": wr.eligibility.eligible, "failed_checks": [c.check_id for c in wr.eligibility.failed],
            "submission_authorised": False})
        if wr.eligibility.eligible and self.preview_dir is not None:
            wr.preview = write_preview(rr, wr.eligibility, self.registry,
                                       Path(self.preview_dir) / wr.intake_id)
            side = json.loads(wr.preview["sidecar"].read_text(encoding="utf-8"))
            side["workflow_decision"] = {"decision": wr.decision.value, "reasons": wr.reasons,
                                         "poc_policy_id": self.poc.policy_id,
                                         "approval_kind": "POC_AUTO" if wr.decision == Decision.AUTO_ACCEPT else None}
            wr.preview["sidecar"].write_text(json.dumps(side, indent=1, ensure_ascii=False), encoding="utf-8")
            wr.preview["sidecar_doc"] = side
            self.log.append("HANDOFF_PREVIEW_WRITTEN", **actor, details={
                "output_sha256": wr.preview["output_sha256"], "csv": wr.preview["csv"].name,
                "sidecar": wr.preview["sidecar"].name, "status": "PREVIEW_ONLY_NOT_AUTHORISED_FOR_UC042_SUBMISSION"})
        return wr
