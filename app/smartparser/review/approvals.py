"""Phase 3B-2 - governed approvals in three SEPARATE scopes, plus category confirmation and rule lifecycle.

  A. file-specific mapping  approve_file_mapping   one upload (intake ID + SHA-256), never reused; FILE_MAPPING authority
  B. header alias           approve_alias          one header -> one field in one category; ALIAS authority
  C. source-system layout   approve_layout         a named system's exact ordered header list; LAYOUT authority
     revoke_rule / approve_layout(supersedes=...)  lifecycle changes; REVOCATION / LAYOUT authority

None of these is a side effect of another: approving a file mapping never creates an alias or a layout. Every function
checks the AuthorityPolicy (the shipped policy authorises nobody), writes through a RuleStore (never the packaged
production rules), and appends audit events.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from ..mapping.governed import (
    Approval, ColumnRule, FileMappingRule, LayoutRule, Lifecycle, definition_sha256, header_fingerprint,
)
from ..mapping.proposals import is_sign_sensitive
from ..mapping.rule_store import RuleStore
from .audit import AuditLog
from .authority import AuthorityPolicy, Reviewer
from .session import ReviewError, ReviewSession, ReviewState


class CategoryConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_id: str
    intake_id: str
    source_sha256: str
    category: str
    reviewer_id: str
    reviewer_role: str
    approval_kind: str
    confirmed_at: str
    basis: str = Field(min_length=1)
    conflicting_content_category: str | None = None


def _approvals(reviewers: list[Reviewer], kind_at: str, basis: str) -> list[Approval]:
    return [Approval(approver_id=r.reviewer_id, approver_role=r.role, approval_kind=r.kind, approved_at=kind_at,
                     basis=basis) for r in reviewers]


def confirm_category(intake_id: str, source_sha256: str, category: str, reviewer: Reviewer, basis: str,
                     policy: AuthorityPolicy, log: AuditLog, registry,
                     content_category: str | None = None) -> CategoryConfirmation:
    """Record a human confirmation of an evidence category. Confirming a category that CONFLICTS with what the content
    identifies needs the separate CATEGORY_CONFLICT authority."""
    if registry.get(category) is None:
        raise ReviewError(f"unknown category {category}")
    scope = "CATEGORY_CONFLICT" if content_category and content_category != category else "CATEGORY_CONFIRMATION"
    kind = policy.authorise(scope, [reviewer])
    c = CategoryConfirmation(confirmation_id=str(uuid.uuid4()), intake_id=intake_id, source_sha256=source_sha256,
                             category=category, reviewer_id=reviewer.reviewer_id, reviewer_role=reviewer.role,
                             approval_kind=kind, confirmed_at=log.clock(), basis=basis,
                             conflicting_content_category=content_category if scope == "CATEGORY_CONFLICT" else None)
    log.append("CATEGORY_CONFIRMED", actor_id=reviewer.reviewer_id, actor_role=reviewer.role, approval_kind=kind,
               intake_id=intake_id, source_sha256=source_sha256,
               details={"confirmation_id": c.confirmation_id, "category": category, "scope": scope, "basis": basis})
    return c


def _columns_from_session(s: ReviewSession) -> list[ColumnRule]:
    resolved = {c["source_index"]: c["canonical_field"] for c in s.resolved_columns}
    chosen = {int(i): d.final_field for i, d in s.decisions.items()}
    return [ColumnRule(source_index=i, source_header=h, canonical_field=resolved.get(i, chosen.get(i)))
            for i, h in enumerate(s.headers)]


def approve_file_mapping(s: ReviewSession, reviewers: list[Reviewer], basis: str, policy: AuthorityPolicy,
                         store: RuleStore, log: AuditLog) -> FileMappingRule:
    if s.state != ReviewState.APPROVED:
        raise ReviewError(f"a file mapping needs an APPROVED review, not {s.state}")
    kind = policy.authorise("FILE_MAPPING", reviewers)
    schema = store.registry.get(s.category)
    if definition_sha256(schema) != s.registry_definition_sha256:
        raise ReviewError("the registry definition changed since the proposal was made")
    rule = FileMappingRule(
        file_mapping_id=f"FM-{uuid.uuid4().hex[:12]}", rule_version=1, category=s.category, intake_id=s.intake_id,
        source_sha256=s.source_sha256, review_session_id=s.session_id, headers=s.headers,
        header_fingerprint=header_fingerprint(s.headers), columns=_columns_from_session(s),
        approvals=_approvals(reviewers, log.clock(), basis), registry_definition_sha256=s.registry_definition_sha256,
        mapping_rules_version=s.mapping_rules, proposal_id=s.proposal_id,
        decision_ids=[d.decision_id for d in s.decisions.values()])
    store.add_file_mapping(rule)
    for ev in ("RULE_CREATED", "RULE_ACTIVATED"):
        log.append(ev, actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role, approval_kind=kind,
                   proposal_id=s.proposal_id, session_id=s.session_id, rule_id=rule.file_mapping_id,
                   intake_id=s.intake_id, source_sha256=s.source_sha256,
                   details={"scope": "FILE_MAPPING", "rule_version": 1, "category": s.category})
    return rule


def approve_alias(category: str, header: str, canonical_field: str, reviewers: list[Reviewer], basis: str,
                  policy: AuthorityPolicy, store: RuleStore, log: AuditLog, source_reference: str,
                  reason: str, risk: str) -> dict:
    """Approve ONE reusable header alias. The catalogue entry and the active alias are written together."""
    kind = policy.authorise("ALIAS", reviewers)
    schema = store.registry.get(category)
    if schema is None or schema.field(canonical_field) is None:
        raise ReviewError(f"{canonical_field!r} is not a field of {category}")
    if is_sign_sensitive(schema, canonical_field) and not policy.allow_sign_sensitive_reusable:
        raise ReviewError(f"{canonical_field} carries amount sign or debit/credit perspective: a reusable alias for it "
                          "is not allowed by the authority policy (owner decision)")
    at = log.clock()
    approver = ", ".join(f"{r.reviewer_id} ({r.role}, {r.kind})" for r in reviewers)
    pid = f"AP-REV-{uuid.uuid4().hex[:10]}"
    proposal = {"proposal_id": pid, "category": category, "canonical_field": canonical_field,
                "proposed_header": header, "reason": reason, "risk": risk, "origin": source_reference,
                "status": "approved", "decision": {"decided_by": approver, "decided_at": at, "basis": basis}}
    alias = {"alias_id": f"AA-{uuid.uuid4().hex[:10]}", "category": category, "canonical_field": canonical_field,
             "alias": header, "proposal_id": pid, "rule_version": 1,
             "approval": [a.model_dump() for a in _approvals(reviewers, at, basis)],
             "registry_definition_sha256": definition_sha256(schema), "lifecycle": {"status": "active"},
             "source_reference": source_reference}
    store.add_alias(proposal, alias)
    for ev in ("RULE_CREATED", "RULE_ACTIVATED"):
        log.append(ev, actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role, approval_kind=kind,
                   rule_id=alias["alias_id"], details={"scope": "ALIAS", "category": category, "header": header,
                                                       "canonical_field": canonical_field, "proposal_id": pid,
                                                       "source_reference": source_reference})
    return alias


def approve_layout(columns: list[ColumnRule], category: str, source_system: str, source_system_version: str,
                   reviewers: list[Reviewer], basis: str, policy: AuthorityPolicy, store: RuleStore, log: AuditLog,
                   proposal_id: str | None = None, decision_ids: list[str] | None = None,
                   acknowledge_sign_sensitive: bool = False, supersedes: str | None = None) -> LayoutRule:
    """Approve a complete source-system layout (every column mapped, every required field present). Sign-sensitive
    fields must be acknowledged explicitly by the approvers."""
    kind = policy.authorise("LAYOUT", reviewers)
    schema = store.registry.get(category)
    headers = [c.source_header for c in columns]
    mapped = [c.canonical_field for c in columns]
    if any(f is None for f in mapped):
        raise ReviewError("a layout must map every source column")
    missing = sorted({f.name for f in schema.fields if f.requiredness == "M" or f.required} - set(mapped))
    if missing:
        raise ReviewError(f"a layout must cover every required field; missing {missing}")
    sign = sorted(f for f in mapped if is_sign_sensitive(schema, f))
    if sign and not acknowledge_sign_sensitive:
        raise ReviewError(f"sign/perspective-sensitive fields {sign} need an explicit acknowledgement")
    version, layout_id = 1, f"LY-{uuid.uuid4().hex[:10]}"
    at = log.clock()
    backup = store.path("layouts").read_bytes()      # supersession + addition succeed together or not at all
    try:
        return _approve_layout(store, log, kind, reviewers, basis, schema, columns, headers, category, source_system,
                               source_system_version, proposal_id, decision_ids, sign, supersedes, version, layout_id,
                               at)
    except Exception:
        store.path("layouts").write_bytes(backup)
        raise


def _approve_layout(store, log, kind, reviewers, basis, schema, columns, headers, category, source_system,
                    source_system_version, proposal_id, decision_ids, sign, supersedes, version, layout_id, at):
    if supersedes:
        old = [x for x in store.find("layouts", supersedes) if (x.get("lifecycle") or {}).get("status") == "active"]
        if len(old) != 1:
            raise ReviewError(f"no active layout {supersedes} to supersede")
        layout_id, version = supersedes, int(old[0]["rule_version"]) + 1
        store.set_lifecycle("layouts", supersedes, version - 1,
                            Lifecycle(status="superseded", superseded_by=f"{supersedes} v{version}", superseded_at=at))
        log.append("RULE_SUPERSEDED", actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role,
                   approval_kind=kind, rule_id=supersedes, details={"scope": "LAYOUT", "old_version": version - 1,
                                                                    "new_version": version})
    rule = LayoutRule(layout_id=layout_id, rule_version=version, category=category, source_system=source_system,
                      source_system_version=source_system_version, headers=headers,
                      header_fingerprint=header_fingerprint(headers), columns=columns,
                      approvals=_approvals(reviewers, at, basis), registry_definition_sha256=definition_sha256(schema),
                      mapping_rules_version=str(store.path("aliases")), proposal_id=proposal_id,
                      decision_ids=decision_ids or [], sign_sensitive_acknowledged=sign)
    store.add_layout(rule)
    for ev in ("RULE_CREATED", "RULE_ACTIVATED"):
        log.append(ev, actor_id=reviewers[0].reviewer_id, actor_role=reviewers[0].role, approval_kind=kind,
                   proposal_id=proposal_id, rule_id=layout_id,
                   details={"scope": "LAYOUT", "rule_version": version, "source_system": source_system,
                            "source_system_version": source_system_version, "approvers": [r.reviewer_id for r in reviewers]})
    return rule


def revoke_rule(kind_name: str, rule_id: str, rule_version: int, reviewer: Reviewer, reason: str,
                policy: AuthorityPolicy, store: RuleStore, log: AuditLog) -> None:
    """Stop a rule matching future files. History (the rule record, its usage, the audit trail) is never rewritten."""
    if not reason or not reason.strip():
        raise ReviewError("a revocation needs a reason")
    kind = policy.authorise("REVOCATION", [reviewer])
    store.set_lifecycle(kind_name, rule_id, rule_version,
                        Lifecycle(status="revoked", revoked_at=log.clock(), revoked_by=reviewer.reviewer_id,
                                  revoked_role=reviewer.role, revocation_reason=reason))
    log.append("RULE_REVOKED", actor_id=reviewer.reviewer_id, actor_role=reviewer.role, approval_kind=kind,
               rule_id=rule_id, details={"kind": kind_name, "rule_version": rule_version, "reason": reason})
