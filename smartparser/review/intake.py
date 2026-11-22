"""Phase 3B-7 - column-review (intake) cases: direct Human-in-the-Loop resolution of a file, column by column.

A case covers EVERY incoming column, identified by its POSITION (never by header text alone - two columns may share a
name). It is opened:
  * HEADER_COUNT_MISMATCH: the file's column count differs from the confirmed category's field count. The header-count
    gate (orchestration) opens it BEFORE any mapping or proposal; suggestions are DIAGNOSTIC name matches only
    (canonical name, or the same name under the active whitespace/case policy) and are never applied by themselves;
  * HEADER_VARIANT (owner decision O2): the category is established deterministically (the header maps one-to-one
    onto exactly one category), but at least one column matches its canonical field only through a variant (letter
    case, whitespace or an approved alias), never automatically recognised. Exact headers are suggested as recognised;
    every variant column needs an explicit analyst decision.
  * DETERMINISTIC_CONFLICT: equal counts, but more than one incoming column claims the same canonical field. Suggestions
    come from the deterministic rules and from the validated proposal.

Reviewer decisions (all need FILE_MAPPING authority and a reason; each is validated, appended - never overwritten - and
audited; the latest decision for a position is the effective one until the case is finalised):
  MAP                      take the column's suggested field
  CHANGE                   choose another field of the confirmed category
  CHOOSE_DUPLICATE_SOURCE  name the authoritative column for a field claimed by several columns; every other claimant
                           receives an explicit IGNORE_COLUMN disposition with the reviewer's reason
  IGNORE_COLUMN            exclude the column from the canonical output (kept in the source, records and provenance; it
                           can never satisfy a canonical field)
  LEAVE_UNRESOLVED         the column stays unresolved -> the case is HELD when finalised
  REJECT (reject_case)     the case is REJECTED
Two columns can never be mapped to one field (DUPLICATE_TARGET), a field must satisfy the column's sample values
(VALUE_INCOMPATIBLE), and a column whose header deterministically matches a field (canonical name, whitespace/case
policy, approved alias) can only be mapped to that field or ignored (RULE_CONTRADICTION - the 3B-2 invariant).

Finalising: every column decided; any LEAVE_UNRESOLVED or any required field not mapped -> HELD (nothing written);
otherwise -> RESOLVED: a category confirmation and a governed FILE-SPECIFIC mapping (MAP / IGNORE per position) are
written for exactly this intake + SHA-256, ready for deterministic reprocessing.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..classify.content_check import _value_error
from ..csv_engine.reader import read_csv
from ..identify.detect import identify
from ..classify.csv_classifier import default_rules
from ..mapping.controlled import MappingRules, _key, controlled_map
from ..mapping.governed import Approval, ColumnRule, FileMappingRule, definition_sha256, header_fingerprint
from ..mapping.rule_store import RuleStore
from .approvals import CategoryConfirmation, confirm_category
from .audit import AuditLog
from .authority import AuthorityPolicy, Reviewer
from .session import ReviewError


class CaseState(StrEnum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    HELD = "HELD"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


TRANSITIONS = {
    CaseState.OPEN: {CaseState.UNDER_REVIEW, CaseState.REJECTED},
    CaseState.UNDER_REVIEW: {CaseState.UNDER_REVIEW, CaseState.HELD, CaseState.RESOLVED, CaseState.REJECTED},
    CaseState.HELD: {CaseState.UNDER_REVIEW, CaseState.REJECTED},       # a held case can be revisited
    CaseState.RESOLVED: set(),
    CaseState.REJECTED: set(),
}
ACTIONS = ("MAP", "CHANGE", "CHOOSE_DUPLICATE_SOURCE", "IGNORE_COLUMN", "LEAVE_UNRESOLVED")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseColumn(_Strict):
    source_index: int = Field(ge=0)
    source_header: str
    suggested_field: str | None = None
    suggestion_basis: Literal["deterministic", "diagnostic_name_match", "proposal", "none"] = "none"
    same_header_positions: list[int] = Field(default_factory=list)    # other positions with the identical header text
    # 3B-11: what the validated LLM proposal said about this column (None when no proposal covered it)
    proposal_field: str | None = None
    proposal_assessment: str | None = None            # the proposer's own assessment (CLEAR / ... / UNMAPPABLE)
    validation_class: str | None = None               # the deterministic validator's class (CLEAR ... NO_MATCH)
    proposal_note: str | None = None


class CaseDecision(_Strict):
    decision_id: str
    source_index: int = Field(ge=0)
    source_header: str
    action: Literal["MAP", "CHANGE", "CHOOSE_DUPLICATE_SOURCE", "IGNORE_COLUMN", "LEAVE_UNRESOLVED"]
    canonical_field: str | None
    reason: str = Field(min_length=1)
    reviewer_id: str
    reviewer_role: str
    approval_kind: Literal["TEST", "BUSINESS"]
    decided_at: str
    group_id: str | None = None             # CHOOSE_DUPLICATE_SOURCE: links the chosen and the ignored claimants
    supersedes: str | None = None           # the earlier decision for the same position, if any


class CaseTransition(_Strict):
    from_state: str
    to_state: str
    at: str
    actor_id: str
    note: str = ""


class ColumnReviewCase(_Strict):
    case_id: str
    kind: Literal["HEADER_COUNT_MISMATCH", "DETERMINISTIC_CONFLICT", "UNMAPPABLE_PROPOSAL", "HEADER_VARIANT"]
    review_reason: str = ""
    intake_id: str
    source_sha256: str
    original_filename: str | None
    category: str
    registry_definition_sha256: str
    mapping_rules: str
    incoming_header_count: int
    expected_field_count: int
    count_difference: int                   # incoming - expected
    headers: list[str]
    columns: list[CaseColumn]
    missing_fields_diagnostic: list[str]    # canonical fields no column is suggested for
    extra_headers_diagnostic: list[dict]    # columns with no suggestion: {source_index, source_header}
    duplicate_incoming_headers: dict[str, list[int]]   # identical header text at several positions
    potential_duplicate_claims: dict[str, list[int]]   # canonical field -> positions suggested for it
    content_classification: dict | None = None         # e.g. the file's header exactly matches another category
    proposal_id: str | None = None
    state: CaseState = CaseState.OPEN
    decisions: list[CaseDecision] = Field(default_factory=list)       # append-only history
    history: list[CaseTransition] = Field(default_factory=list)
    final_summary: dict | None = None
    rejection_reason: str | None = None
    file_mapping_id: str | None = None
    confirmation_id: str | None = None

    def effective(self) -> dict[int, CaseDecision]:
        out: dict[int, CaseDecision] = {}
        for d in self.decisions:
            out[d.source_index] = d
        return out

    def mapped(self) -> dict[int, str]:
        return {i: d.canonical_field for i, d in self.effective().items() if d.canonical_field}


@dataclass
class CaseContext:
    """Transient, from the STORED original (SHA-256 verified): the schema and local sample values. Never persisted."""
    schema: object
    raw_headers: list[str]
    samples: dict[int, list[str]]
    deterministic: dict[int, str]       # position -> field the deterministic rules (name, policy, alias) match


# ------------------------------------------------------------------------------------------------ opening
def name_diagnostics(raw_headers: list[str], schema, rules: MappingRules) -> list[tuple[str | None, str]]:
    """Diagnostic name matches only (canonical name, or equal under the whitespace/case policy). No aliases, layouts or
    file rules, and nothing is accepted: this is NOT the mapping stage."""
    by_key = {}
    for f in schema.fields:
        by_key.setdefault(_key(f.name, rules.policy), f.name)
    out = []
    for h in raw_headers:
        f = by_key.get(_key(h, rules.policy))
        out.append((f, "diagnostic_name_match") if f else (None, "none"))
    return out


def open_case(kind: str, intake_id: str, source_sha256: str, original_filename: str | None, schema, raw_headers: list[str],
              rules: MappingRules, log: AuditLog, suggestions: list[tuple[str | None, str]] | None = None,
              content_classification: dict | None = None, proposal_id: str | None = None,
              proposal_columns=None, review_reason: str = "") -> ColumnReviewCase:
    suggestions = suggestions or name_diagnostics(raw_headers, schema, rules)
    findings = {}
    for pc in proposal_columns or []:                 # 3B-11: show the reviewer what the proposal concluded
        vc = str(pc.validation_class)
        note = ("the LLM found no defensible mapping (UNMAPPABLE)" if pc.proposer_assessment == "UNMAPPABLE" else
                "no valid canonical field was proposed" if vc == "NO_MATCH" else
                f"proposal {pc.proposed_field} ({pc.proposer_assessment}) validated as {vc}")
        findings[pc.source_index] = dict(proposal_field=pc.proposed_field, proposal_assessment=pc.proposer_assessment,
                                         validation_class=vc, proposal_note=note)
    same: dict[str, list[int]] = {}
    for i, h in enumerate(raw_headers):
        same.setdefault(h, []).append(i)
    claims: dict[str, list[int]] = {}
    for i, (f, _) in enumerate(suggestions):
        if f:
            claims.setdefault(f, []).append(i)
    cols = [CaseColumn(source_index=i, source_header=h, suggested_field=suggestions[i][0],
                       suggestion_basis=suggestions[i][1], same_header_positions=[p for p in same[h] if p != i],
                       **findings.get(i, {}))
            for i, h in enumerate(raw_headers)]
    case = ColumnReviewCase(
        case_id=f"CRC-{uuid.uuid4().hex[:12]}", kind=kind, intake_id=intake_id, source_sha256=source_sha256,
        original_filename=original_filename, category=schema.category,
        registry_definition_sha256=definition_sha256(schema), mapping_rules=rules.source,
        incoming_header_count=len(raw_headers), expected_field_count=len(schema.fields),
        count_difference=len(raw_headers) - len(schema.fields), headers=list(raw_headers), columns=cols,
        missing_fields_diagnostic=[f.name for f in schema.fields if f.name not in claims],
        extra_headers_diagnostic=[{"source_index": c.source_index, "source_header": c.source_header}
                                  for c in cols if not c.suggested_field],
        duplicate_incoming_headers={h: p for h, p in same.items() if len(p) > 1},
        potential_duplicate_claims={f: p for f, p in claims.items() if len(p) > 1},
        content_classification=content_classification, proposal_id=proposal_id, review_reason=review_reason)
    log.append("INTAKE_CASE_OPENED", intake_id=intake_id, source_sha256=source_sha256, proposal_id=proposal_id,
               details={"case_id": case.case_id, "kind": kind, "category": schema.category,
                        "incoming_header_count": case.incoming_header_count,
                        "expected_field_count": case.expected_field_count,
                        "duplicate_incoming_headers": case.duplicate_incoming_headers,
                        "potential_duplicate_claims": case.potential_duplicate_claims})
    return case


def case_context(case: ColumnReviewCase, evidence, registry, rules: MappingRules | None = None) -> CaseContext:
    data = evidence.read_original(case.source_sha256)
    if data is None or hashlib.sha256(data).hexdigest() != case.source_sha256:
        raise ReviewError("the stored original is missing or does not match the case's SHA-256")
    rec = evidence.find(case.intake_id)
    if rec is None or rec.sha256 != case.source_sha256:
        raise ReviewError("the case does not belong to a known intake with this SHA-256")
    ident = identify(data, rec.original_filename)
    table = read_csv(data, ident.encoding, ident.delimiter)
    if list(table.raw_headers) != case.headers:
        raise ReviewError("the stored file's header differs from the case")
    samples = {i: [v for v in table.column_values(i) if v != ""][:5] for i in range(len(case.headers))}
    schema = registry.get(case.category)
    rules = (rules or default_rules(registry)).without_file_identity()
    det = {m["source_position"]: m["canonical_field"] for m in controlled_map(case.headers, schema, rules).mappings}
    return CaseContext(schema, list(table.raw_headers), samples, det)


# ------------------------------------------------------------------------------------------------ decisions
def _move(case: ColumnReviewCase, to: CaseState, actor: str, log: AuditLog, note: str = "") -> None:
    if to not in TRANSITIONS[case.state]:
        raise ReviewError(f"invalid transition {case.state} -> {to}")
    case.history.append(CaseTransition(from_state=case.state.value, to_state=to.value, at=log.clock(), actor_id=actor,
                                       note=note))
    case.state = to


def _check_field(case: ColumnReviewCase, ctx: CaseContext, pos: int, fld: str, allow_positions: set[int]) -> None:
    f = ctx.schema.field(fld)
    if f is None:
        raise ReviewError(f"{fld!r} is not a field of the confirmed category {case.category}")
    det = ctx.deterministic.get(pos)
    if det is not None and det != fld:
        # 3B-2 invariant: a governed file rule never contradicts a deterministic name/alias match (the reprocessing
        # would refuse it). The column can be IGNOREd, or the file rejected for a corrected export.
        raise ReviewError(f"RULE_CONTRADICTION: column {pos} ({case.headers[pos]!r}) matches {det!r} deterministically; "
                          f"it cannot be mapped to {fld!r} (use IGNORE_COLUMN or reject the file)")
    others = [i for i, m in case.mapped().items() if m == fld and i != pos and i not in allow_positions]
    if others:
        raise ReviewError(f"DUPLICATE_TARGET: {fld} is already mapped from column(s) {others}; use "
                          "CHOOSE_DUPLICATE_SOURCE to pick one authoritative column")
    bad = [v for v in ctx.samples.get(pos, []) if _value_error(f.source_type, f.constraints.pattern,
                                                                f.constraints.allowed_values, v)]
    if bad:
        raise ReviewError(f"VALUE_INCOMPATIBLE: {len(bad)} sample value(s) of column {pos} break the {fld} rule")


def _record(case, log, reviewer, kind, pos, action, fld, reason, group_id=None) -> CaseDecision:
    prev = case.effective().get(pos)
    d = CaseDecision(decision_id=str(uuid.uuid4()), source_index=pos, source_header=case.headers[pos], action=action,
                     canonical_field=fld, reason=reason, reviewer_id=reviewer.reviewer_id, reviewer_role=reviewer.role,
                     approval_kind=kind, decided_at=log.clock(), group_id=group_id,
                     supersedes=prev.decision_id if prev else None)
    case.decisions.append(d)
    log.append("INTAKE_DECISION", actor_id=reviewer.reviewer_id, actor_role=reviewer.role, approval_kind=kind,
               intake_id=case.intake_id, source_sha256=case.source_sha256, proposal_id=case.proposal_id,
               details={"case_id": case.case_id, "decision_id": d.decision_id, "source_index": pos,
                        "source_header": case.headers[pos], "action": action, "canonical_field": fld,
                        "reason": reason, "group_id": group_id, "supersedes": d.supersedes})
    return d


def decide(case: ColumnReviewCase, action: str, reviewer: Reviewer, reason: str, policy: AuthorityPolicy,
           log: AuditLog, ctx: CaseContext, source_index: int, canonical_field: str | None = None,
           others_reason: str | None = None) -> list[CaseDecision]:
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    if action not in ACTIONS:
        raise ReviewError(f"unknown action {action!r}")
    if not reason or not reason.strip():
        raise ReviewError("every decision needs a reason")
    if case.state not in (CaseState.OPEN, CaseState.UNDER_REVIEW, CaseState.HELD):
        raise ReviewError(f"decisions are not possible in {case.state}")
    if not 0 <= source_index < len(case.headers):
        raise ReviewError(f"column {source_index} is not a column of this file")
    if ctx.raw_headers != case.headers:
        raise ReviewError("the review context does not belong to this file")
    if case.state != CaseState.UNDER_REVIEW:
        _move(case, CaseState.UNDER_REVIEW, reviewer.reviewer_id, log, f"decision {action}")
    col = case.columns[source_index]
    if action == "MAP":
        if not col.suggested_field:
            raise ReviewError(f"column {source_index} has no suggested field; use CHANGE to choose one")
        _check_field(case, ctx, source_index, col.suggested_field, set())
        return [_record(case, log, reviewer, kind, source_index, "MAP", col.suggested_field, reason)]
    if action == "CHANGE":
        if not canonical_field:
            raise ReviewError("CHANGE needs a canonical_field")
        _check_field(case, ctx, source_index, canonical_field, set())
        return [_record(case, log, reviewer, kind, source_index, "CHANGE", canonical_field, reason)]
    if action == "IGNORE_COLUMN":
        return [_record(case, log, reviewer, kind, source_index, "IGNORE_COLUMN", None, reason)]
    if action == "LEAVE_UNRESOLVED":
        return [_record(case, log, reviewer, kind, source_index, "LEAVE_UNRESOLVED", None, reason)]
    # CHOOSE_DUPLICATE_SOURCE
    fld = canonical_field or col.suggested_field
    claimants = set(case.potential_duplicate_claims.get(fld, [])) | {i for i, m in case.mapped().items() if m == fld}
    if source_index not in claimants or len(claimants) < 2:
        raise ReviewError(f"column #{source_index + 1} is not one of several claimants of {fld!r} "
                          f"(claimant columns: {['#%d' % (i + 1) for i in sorted(claimants)]})")
    if not others_reason or not others_reason.strip():
        raise ReviewError("every other claimant needs an explicit disposition: give others_reason")
    _check_field(case, ctx, source_index, fld, claimants)
    gid = f"DUP-{uuid.uuid4().hex[:8]}"
    out = [_record(case, log, reviewer, kind, source_index, "CHOOSE_DUPLICATE_SOURCE", fld, reason, gid)]
    for other in sorted(claimants - {source_index}):
        out.append(_record(case, log, reviewer, kind, other, "IGNORE_COLUMN", None,
                           f"duplicate claimant of {fld}; authoritative column is #{source_index + 1} "
                           f"({next(c.source_header for c in case.columns if c.source_index == source_index)}): {others_reason}",
                           gid))
    return out


def reject_case(case: ColumnReviewCase, reviewer: Reviewer, reason: str, policy: AuthorityPolicy,
                log: AuditLog) -> None:
    if not reason or not reason.strip():
        raise ReviewError("a rejection needs a reason")
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    _move(case, CaseState.REJECTED, reviewer.reviewer_id, log, reason)
    case.rejection_reason = reason
    log.append("INTAKE_CASE_REJECTED", actor_id=reviewer.reviewer_id, actor_role=reviewer.role, approval_kind=kind,
               intake_id=case.intake_id, source_sha256=case.source_sha256,
               details={"case_id": case.case_id, "reason": reason})


# ------------------------------------------------------------------------------------------------ finalising
def finalise_case(case: ColumnReviewCase, reviewers: list[Reviewer], basis: str, policy: AuthorityPolicy,
                  store: RuleStore, log: AuditLog, registry, ctx: CaseContext,
                  category_reviewer: Reviewer | None = None) -> tuple[FileMappingRule | None,
                                                                      CategoryConfirmation | None]:
    """HELD (returns (None, None)) or RESOLVED (writes a category confirmation and a governed file mapping)."""
    kind = policy.authorise("FILE_MAPPING", reviewers)
    if case.state != CaseState.UNDER_REVIEW:
        raise ReviewError(f"only a case under review can be finalised, not {case.state}")
    eff = case.effective()
    undecided = [i for i in range(len(case.headers)) if i not in eff]
    if undecided:
        raise ReviewError(f"columns without a decision: {undecided}")
    schema = registry.get(case.category)
    if definition_sha256(schema) != case.registry_definition_sha256:
        raise ReviewError("the registry definition changed since the case was opened")
    mapped = case.mapped()
    fields = list(mapped.values())
    dup = sorted({f for f in fields if fields.count(f) > 1})
    if dup:
        raise ReviewError(f"DUPLICATE_TARGET at finalisation: {dup}")
    for pos, fld in mapped.items():                 # re-validate every mapped column against the stored file
        _check_field(case, ctx, pos, fld, set())
    unresolved = sorted(i for i, d in eff.items() if d.action == "LEAVE_UNRESOLVED")
    required = {f.name for f in schema.fields if f.requiredness == "M" or f.required}
    missing = sorted(required - set(fields))
    ignored = sorted(i for i, d in eff.items() if d.action == "IGNORE_COLUMN")
    summary = {"mapped": {str(k): v for k, v in sorted(mapped.items())}, "ignored_positions": ignored,
               "unresolved_positions": unresolved, "missing_required_fields": missing}
    case.final_summary = summary
    if unresolved or missing:
        _move(case, CaseState.HELD, reviewers[0].reviewer_id, log,
              f"unresolved {unresolved}; missing required {missing}")
        log.append("INTAKE_CASE_HELD", actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role,
                   approval_kind=kind, intake_id=case.intake_id, source_sha256=case.source_sha256,
                   details={"case_id": case.case_id, **summary})
        return None, None
    content_cat = (case.content_classification or {}).get("category")
    conf = confirm_category(case.intake_id, case.source_sha256, case.category, category_reviewer or reviewers[0],
                            basis, policy, log, registry, content_category=content_cat)
    rule = FileMappingRule(
        file_mapping_id=f"FM-CRC-{uuid.uuid4().hex[:10]}", rule_version=1, category=case.category,
        intake_id=case.intake_id, source_sha256=case.source_sha256, review_session_id=case.case_id,
        headers=case.headers, header_fingerprint=header_fingerprint(case.headers),
        columns=[ColumnRule(source_index=i, source_header=h, canonical_field=mapped.get(i),
                            disposition="IGNORE" if i in ignored else "MAP",
                            ignore_reason=eff[i].reason if i in ignored else None)
                 for i, h in enumerate(case.headers)],
        approvals=[Approval(approver_id=r.reviewer_id, approver_role=r.role, approval_kind=r.kind,
                            approved_at=log.clock(), basis=basis) for r in reviewers],
        registry_definition_sha256=case.registry_definition_sha256, mapping_rules_version=case.mapping_rules,
        proposal_id=case.proposal_id or f"column-review:{case.case_id}",
        decision_ids=[d.decision_id for _, d in sorted(eff.items())])
    store.add_file_mapping(rule)
    for ev in ("RULE_CREATED", "RULE_ACTIVATED"):
        log.append(ev, actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role, approval_kind=kind,
                   rule_id=rule.file_mapping_id, intake_id=case.intake_id, source_sha256=case.source_sha256,
                   details={"scope": "FILE_MAPPING", "source": "column_review_case", "case_id": case.case_id,
                            "ignored_positions": ignored})
    case.file_mapping_id, case.confirmation_id = rule.file_mapping_id, conf.confirmation_id
    _move(case, CaseState.RESOLVED, reviewers[0].reviewer_id, log, basis)
    log.append("INTAKE_CASE_RESOLVED", actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role,
               approval_kind=kind, intake_id=case.intake_id, source_sha256=case.source_sha256,
               rule_id=rule.file_mapping_id, details={"case_id": case.case_id, "confirmation_id": conf.confirmation_id,
                                                      "file_mapping_id": rule.file_mapping_id, **summary})
    return rule, conf


def deterministic_suggestions(raw_headers: list[str], schema, rules: MappingRules,
                              proposal_columns=None) -> list[tuple[str | None, str]]:
    """Suggestions for a DETERMINISTIC_CONFLICT case: what the deterministic rules matched per position, and for the
    remaining columns a validated (non-conflicting) proposal."""
    cm = controlled_map(raw_headers, schema, rules)
    out: list[tuple[str | None, str]] = [(None, "none")] * len(raw_headers)
    for m in cm.mappings:
        out[m["source_position"]] = (m["canonical_field"], "deterministic")
    for c in proposal_columns or []:
        if out[c.source_index][0] is None and c.validation_class.value in ("CLEAR", "PLAUSIBLE", "AMBIGUOUS"):
            out[c.source_index] = (c.proposed_field, "proposal")
    return out
