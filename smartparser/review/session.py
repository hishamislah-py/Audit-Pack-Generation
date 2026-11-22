"""Phase 3B-2 - the review state machine around a Phase 3B-1 ProposalRecord.

States: PROPOSED -> UNDER_REVIEW -> PARTIALLY_DECIDED -> APPROVED / REJECTED / REVISION_REQUESTED (see TRANSITIONS).

Per column a reviewer may APPROVE the proposed field, CHANGE it to another field of the SAME confirmed category, REJECT
it, or LEAVE it unmapped. Every chosen field is re-validated with the deterministic Phase 3B-1 validator
(`validate_proposal`) against the file - wrong category field, duplicate target, field already resolved, value-rule
conflict are refused. A NO_MATCH or CONFLICT column (this includes explicit UNMAPPABLE, either form) can never be
APPROVED as proposed: a field must be chosen explicitly with CHANGE, which is validated like any other choice.

Decisions may be saved partially; nothing in a session is ever applied to a file. APPROVED means every column has a
decision and no blocking conflict remains - it does NOT mean the file is complete or eligible for handoff (missing
required fields and unmapped columns are recorded in `final_summary`). Rule creation is a separate step
(review.approvals), with its own authority.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..mapping.proposals import (
    ColumnAssessment, ProposalRecord, ProposalRequest, ProposalResponse, ProposedColumnIn, ValidationClass,
    validate_proposal,
)
from .audit import AuditLog
from .authority import AuthorityPolicy, Reviewer


class ReviewState(StrEnum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PARTIALLY_DECIDED = "PARTIALLY_DECIDED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


TRANSITIONS = {
    ReviewState.PROPOSED: {ReviewState.UNDER_REVIEW},
    ReviewState.UNDER_REVIEW: {ReviewState.PARTIALLY_DECIDED, ReviewState.APPROVED, ReviewState.REJECTED,
                               ReviewState.REVISION_REQUESTED},
    ReviewState.PARTIALLY_DECIDED: {ReviewState.PARTIALLY_DECIDED, ReviewState.APPROVED, ReviewState.REJECTED,
                                    ReviewState.REVISION_REQUESTED},
    ReviewState.REVISION_REQUESTED: set(),
    ReviewState.APPROVED: set(),
    ReviewState.REJECTED: set(),
}
APPROVABLE_AS_PROPOSED = {ValidationClass.CLEAR, ValidationClass.PLAUSIBLE, ValidationClass.AMBIGUOUS}


class ReviewError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColumnDecision(_Strict):
    decision_id: str
    source_index: int = Field(ge=0)
    source_header: str
    action: Literal["APPROVE", "CHANGE", "REJECT", "LEAVE_UNMAPPED"]
    proposed_field: str | None
    final_field: str | None
    validation_class_at_decision: str
    reviewer_id: str
    reviewer_role: str
    approval_kind: Literal["TEST", "BUSINESS"]
    decided_at: str
    basis: str = Field(min_length=1)


class Transition(_Strict):
    from_state: str
    to_state: str
    at: str
    actor_id: str
    note: str = ""


class ReviewSession(_Strict):
    session_id: str
    proposal_id: str
    intake_id: str
    source_sha256: str
    category: str
    registry_definition_sha256: str
    mapping_rules: str
    headers: list[str]
    resolved_columns: list[dict]
    columns: list[ColumnAssessment]
    state: ReviewState = ReviewState.PROPOSED
    decisions: dict[str, ColumnDecision] = Field(default_factory=dict)
    history: list[Transition] = Field(default_factory=list)
    final_summary: dict | None = None
    rejection_reason: str | None = None
    revision_note: str | None = None
    revision_proposal_id: str | None = None

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ReviewSession":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def column(self, source_index: int) -> ColumnAssessment:
        hits = [c for c in self.columns if c.source_index == source_index]
        if len(hits) != 1:
            raise ReviewError(f"column {source_index} is not a single reviewable column of this proposal")
        return hits[0]


@dataclass
class ReviewContext:
    """Transient file context for re-validating decisions (never stored in the session: holds sample values)."""
    request: ProposalRequest
    schema: object
    raw_headers: list[str]
    samples: dict[int, list[str]]


def start_session(record: ProposalRecord, request: ProposalRequest, headers: list[str], log: AuditLog) -> ReviewSession:
    if record.request_id != request.request_id:
        raise ReviewError("the request does not belong to this proposal")
    s = ReviewSession(
        session_id=str(uuid.uuid4()), proposal_id=record.proposal_id, intake_id=record.intake_id,
        source_sha256=record.source_sha256, category=record.confirmed_category,
        registry_definition_sha256=record.registry_definition_sha256, mapping_rules=record.mapping_rules,
        headers=list(headers), resolved_columns=[c.model_dump() for c in request.resolved_columns],
        columns=[c for c in record.columns if c.source_index < len(headers)])
    return s


def _move(s: ReviewSession, to: ReviewState, actor: str, log: AuditLog, note: str = "") -> None:
    if to not in TRANSITIONS[s.state]:
        raise ReviewError(f"invalid transition {s.state} -> {to}")
    s.history.append(Transition(from_state=s.state.value, to_state=to.value, at=log.clock(), actor_id=actor, note=note))
    s.state = to


def _audit(log: AuditLog, s: ReviewSession, event: str, reviewer: Reviewer | None, kind: str | None, **details):
    log.append(event, actor_id=reviewer.reviewer_id if reviewer else None, actor_role=reviewer.role if reviewer else None,
               approval_kind=kind, proposal_id=s.proposal_id, session_id=s.session_id, intake_id=s.intake_id,
               source_sha256=s.source_sha256, details=details)


def open_review(s: ReviewSession, reviewer: Reviewer, policy: AuthorityPolicy, log: AuditLog) -> None:
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    _move(s, ReviewState.UNDER_REVIEW, reviewer.reviewer_id, log)
    _audit(log, s, "PROPOSAL_REVIEW_OPENED", reviewer, kind)


def _chosen(s: ReviewSession, override: tuple[int, str | None] | None = None) -> dict[int, str]:
    chosen = {int(i): d.final_field for i, d in s.decisions.items() if d.final_field}
    if override is not None:
        idx, fld = override
        chosen.pop(idx, None)
        if fld:
            chosen[idx] = fld
    return chosen


def _revalidate(s: ReviewSession, ctx: ReviewContext, chosen: dict[int, str]) -> dict[int, ColumnAssessment]:
    if ctx.request.category != s.category or ctx.raw_headers != s.headers:
        raise ReviewError("the review context does not belong to this file and category")
    resp = ProposalResponse(response_schema="smartparser-mapping-proposal/1.0", category=s.category, columns=[
        ProposedColumnIn(source_index=i, source_header=ctx.raw_headers[i], canonical_field=f, assessment="PLAUSIBLE")
        for i, f in sorted(chosen.items())])
    cols, _ = validate_proposal(ctx.request, ctx.schema, resp, ctx.raw_headers, ctx.samples)
    return {c.source_index: c for c in cols if c.source_index in chosen}


def decide_column(s: ReviewSession, source_index: int, action: str, reviewer: Reviewer, basis: str,
                  policy: AuthorityPolicy, log: AuditLog, ctx: ReviewContext, final_field: str | None = None) -> ColumnDecision:
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    if s.state not in (ReviewState.UNDER_REVIEW, ReviewState.PARTIALLY_DECIDED):
        raise ReviewError(f"decisions are only possible under review, not in {s.state}")
    col = s.column(source_index)
    if action == "APPROVE":
        if col.validation_class not in APPROVABLE_AS_PROPOSED or not col.proposed_field:
            raise ReviewError(f"column {source_index} is {col.validation_class}: it cannot be approved as proposed; "
                              "choose a field explicitly (CHANGE) or leave it unmapped")
        final = col.proposed_field
    elif action == "CHANGE":
        if not final_field:
            raise ReviewError("CHANGE needs a final_field")
        if ctx.schema.field(final_field) is None:
            raise ReviewError(f"{final_field!r} is not a field of the confirmed category {s.category}")
        final = final_field
    elif action in ("REJECT", "LEAVE_UNMAPPED"):
        final = None
    else:
        raise ReviewError(f"unknown action {action!r}")
    if final:
        check = _revalidate(s, ctx, _chosen(s, (source_index, final)))
        a = check[source_index]
        if a.validation_class in (ValidationClass.CONFLICT_INCOMPLETE, ValidationClass.NO_MATCH):
            raise ReviewError(f"{final!r} for column {source_index} fails deterministic validation: "
                              + "; ".join(d.code for d in a.diagnostics))
    d = ColumnDecision(decision_id=str(uuid.uuid4()), source_index=source_index, source_header=col.source_header,
                       action=action, proposed_field=col.proposed_field, final_field=final,
                       validation_class_at_decision=col.validation_class.value, reviewer_id=reviewer.reviewer_id,
                       reviewer_role=reviewer.role, approval_kind=kind, decided_at=log.clock(), basis=basis)
    s.decisions[str(source_index)] = d
    _move(s, ReviewState.PARTIALLY_DECIDED, reviewer.reviewer_id, log, f"column {source_index}: {action}")
    _audit(log, s, "COLUMN_DECIDED", reviewer, kind, decision_id=d.decision_id, source_index=source_index,
           action=action, proposed_field=col.proposed_field, final_field=final)
    return d


def approve_proposal(s: ReviewSession, reviewer: Reviewer, basis: str, policy: AuthorityPolicy, log: AuditLog,
                     ctx: ReviewContext) -> dict:
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    if ReviewState.APPROVED not in TRANSITIONS[s.state]:
        raise ReviewError(f"invalid transition {s.state} -> {ReviewState.APPROVED}")
    undecided = [c.source_index for c in s.columns if str(c.source_index) not in s.decisions]
    if undecided:
        raise ReviewError(f"columns without a decision: {undecided}")
    chosen = _chosen(s)
    if chosen:
        bad = {i: a for i, a in _revalidate(s, ctx, chosen).items()
               if a.validation_class in (ValidationClass.CONFLICT_INCOMPLETE, ValidationClass.NO_MATCH)}
        if bad:
            raise ReviewError(f"blocking conflicts remain: {{{', '.join(f'{i}: ' + ','.join(d.code for d in a.diagnostics) for i, a in bad.items())}}}")
    resolved = {c["canonical_field"] for c in s.resolved_columns}
    required = {f.name for f in ctx.schema.fields if f.requiredness == "M" or f.required}
    summary = {"complete": False, "missing_required_fields": sorted(required - resolved - set(chosen.values())),
               "unmapped_columns": [s.headers[c.source_index] for c in s.columns if not chosen.get(c.source_index)]}
    summary["complete"] = not summary["missing_required_fields"] and not summary["unmapped_columns"]
    s.final_summary = summary
    _move(s, ReviewState.APPROVED, reviewer.reviewer_id, log, basis)
    _audit(log, s, "PROPOSAL_APPROVED", reviewer, kind, basis=basis, **summary)
    return summary


def reject_proposal(s: ReviewSession, reviewer: Reviewer, reason: str, policy: AuthorityPolicy, log: AuditLog) -> None:
    if not reason or not reason.strip():
        raise ReviewError("a rejection needs a reason")
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    _move(s, ReviewState.REJECTED, reviewer.reviewer_id, log, reason)
    s.rejection_reason = reason
    _audit(log, s, "PROPOSAL_REJECTED", reviewer, kind, reason=reason)


def request_revision(s: ReviewSession, reviewer: Reviewer, note: str, policy: AuthorityPolicy, log: AuditLog) -> None:
    if not note or not note.strip():
        raise ReviewError("a revision request needs a note")
    kind = policy.authorise("FILE_MAPPING", [reviewer])
    _move(s, ReviewState.REVISION_REQUESTED, reviewer.reviewer_id, log, note)
    s.revision_note = note
    _audit(log, s, "REVISION_REQUESTED", reviewer, kind, note=note)


def link_revision(old: ReviewSession, new_record: ProposalRecord, log: AuditLog) -> None:
    """Record that `new_record` (a new proposal identity) revises the proposal of `old`."""
    if old.state != ReviewState.REVISION_REQUESTED:
        raise ReviewError("a revision can only follow a revision request")
    if new_record.revision_of != old.proposal_id or new_record.proposal_id == old.proposal_id:
        raise ReviewError("the new proposal must have its own identity and reference the revised proposal")
    old.revision_proposal_id = new_record.proposal_id
    log.append("REVISION_CREATED", proposal_id=new_record.proposal_id, session_id=old.session_id,
               intake_id=old.intake_id, source_sha256=old.source_sha256,
               details={"revision_of": old.proposal_id, "note": old.revision_note})
