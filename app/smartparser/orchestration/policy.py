"""Phase 3B-6 - the POC automated decision policy over a VALIDATED proposal (deterministic; separate configuration).

Routing (checked in this order; the first that applies wins; every finding is listed in the reasons):
  1 REJECT_OR_HOLD  no usable proposal (provider disabled / budget denied / provider error / malformed response) or a
                    rejected proposal (e.g. wrong category)
  2 HUMAN_REVIEW    a deterministic conflict: more than one incoming column claims the same canonical field, or a
                    proposal targets such a field (DETERMINISTIC_CONFLICT) - Phase 3B-6.1; never AUTO_ACCEPT.
                    Phase 3B-7: checked BEFORE the required-field HOLD - choosing the authoritative duplicate column is
                    a human decision even when another required field is still unresolved (the person sees both)
  3 REJECT_OR_HOLD  any other CONFLICT_INCOMPLETE column (duplicate proposal target, field already resolved, header or
                    index mismatch, value-rule conflict): the proposal itself is invalid
  4 HUMAN_REVIEW    a NO_MATCH column: an incoming header with no valid mapping (explicit UNMAPPABLE, invalid canonical
                    field, unaddressed column) - a person decides in a column-review case (UNMAPPABLE_PROPOSAL); it is
                    never dropped silently (3B-6.1). Phase 3B-11: checked BEFORE the required-field HOLD
  5 REJECT_OR_HOLD  a required canonical field is still unresolved (HOLD: nothing in this file can supply it)
  6 HUMAN_REVIEW    any AMBIGUOUS column (multiple plausible targets, sign/perspective-sensitive money or debit/credit
                    fields), any PLAUSIBLE column (unless the policy accepts PLAUSIBLE), or the policy is not enabled
  7 AUTO_ACCEPT     the policy is enabled, no deterministic conflict, every proposed column CLEAR (or PLAUSIBLE when
                    allowed), every required field covered

The proposer's confidence is never used: classes are computed by mapping.proposals.validate_proposal. AUTO_ACCEPT only
ever produces a FILE-SPECIFIC mapping (approval kind POC_AUTO); it never creates a reusable alias or layout.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..mapping.proposals import ProposalRecord, ValidationClass

POLICY_PATH = Path(__file__).parent / "poc_auto_accept_policy.json"
POC_ACTOR = "POC_AUTO_ACCEPT_POLICY"
POC_ROLE = "poc_auto_accept"


class Decision(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"      # no proposal needed: the deterministic rules mapped the file
    AUTO_ACCEPT = "AUTO_ACCEPT"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REJECT_OR_HOLD = "REJECT_OR_HOLD"


class PocAutoAcceptPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str
    status: Literal["DISABLED", "POC_TEST_ONLY", "POC_OWNER_ENABLED"]
    note: str = ""
    enabled: bool = False
    accept_plausible: bool = False
    accept_supplied_category: bool = False

    @classmethod
    def load(cls, path: str | Path = POLICY_PATH) -> "PocAutoAcceptPolicy":
        p = cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
        if p.status == "DISABLED" and (p.enabled or p.accept_supplied_category or p.accept_plausible):
            raise ValueError("a DISABLED policy may not enable anything")
        return p


@dataclass
class PolicyDecision:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    accepted_columns: dict[int, str] = field(default_factory=dict)   # source index -> canonical field (AUTO_ACCEPT)


def decide(record: ProposalRecord | None, policy: PocAutoAcceptPolicy, error: str | None = None) -> PolicyDecision:
    if record is None or record.response_error or error:
        return PolicyDecision(Decision.REJECT_OR_HOLD, [error or (record.response_error if record else
                                                                  "no proposal was produced")])
    s = record.summary
    reasons = []                                   # every blocking finding is reported, whatever decides the route
    det_conflicts = dict(s.deterministic_conflicts)
    if det_conflicts:
        reasons.append(f"deterministic conflict: more than one incoming column claims {det_conflicts}")
    blocked = [c for c in record.columns if any(d.code == "DETERMINISTIC_CONFLICT" for d in c.diagnostics)]
    if blocked:
        reasons.append("proposal(s) onto a deterministically conflicted field: " + ", ".join(
            f"{c.source_header} -> {c.proposed_field}" for c in blocked))
    conflicts = [c for c in record.columns if c.validation_class == ValidationClass.CONFLICT_INCOMPLETE
                 and c not in blocked]
    no_match = [c for c in record.columns if c.validation_class == ValidationClass.NO_MATCH]
    if conflicts:
        reasons.append("conflicting or invalid assignments: " + "; ".join(
            f"{c.source_header} ({','.join(d.code for d in c.diagnostics)})" for c in conflicts))
    if no_match:
        reasons.append("no valid canonical field for: " + "; ".join(
            f"{c.source_header} ({','.join(d.code for d in c.diagnostics)})" for c in no_match))
    if s.required_fields_unresolved:
        reasons.append(f"required fields unresolved: {s.required_fields_unresolved}")
    # routing (Phase 3B-6.1): HOLD what a person cannot fix inside this file; HITL what a person must decide
    if s.overall == "REJECTED":
        return PolicyDecision(Decision.REJECT_OR_HOLD, [f"proposal rejected: {r}" for r in s.reasons] + reasons)
    if det_conflicts or blocked:
        return PolicyDecision(Decision.HUMAN_REVIEW, reasons)            # duplicate field claims -> HITL, never AUTO (3B-7: first)
    if conflicts:
        return PolicyDecision(Decision.REJECT_OR_HOLD, reasons)          # invalid proposal assignments -> HOLD
    if no_match:
        # 3B-11: an UNMAPPABLE / no-valid-field column goes to a person (a column-review case) even when a required
        # field is consequently uncovered; the person may map it, leave it unresolved or reject the file. It is never
        # auto-accepted, and a still-uncovered required field keeps the file from being validated (HELD at review).
        return PolicyDecision(Decision.HUMAN_REVIEW, reasons)
    if s.required_fields_unresolved:
        return PolicyDecision(Decision.REJECT_OR_HOLD, reasons)          # unresolved required fields -> HOLD
    ambiguous = [c for c in record.columns if c.validation_class == ValidationClass.AMBIGUOUS]
    plausible = [c for c in record.columns if c.validation_class == ValidationClass.PLAUSIBLE]
    review = []
    if ambiguous:
        review.append("ambiguous (needs a person): " + "; ".join(
            f"{c.source_header}{' [sign/perspective-sensitive]' if c.sign_sensitive else ''}" for c in ambiguous))
    if plausible and not policy.accept_plausible:
        review.append("plausible but not verified: " + ", ".join(c.source_header for c in plausible))
    if not policy.enabled:
        review.append(f"POC auto-accept policy {policy.policy_id} is not enabled")
    if review:
        return PolicyDecision(Decision.HUMAN_REVIEW, review)
    return PolicyDecision(Decision.AUTO_ACCEPT, ["every unresolved column is CLEAR (deterministically validated), "
                                                 "no conflict, no ambiguity, every required field covered"],
                          {c.source_index: c.proposed_field for c in record.columns})
