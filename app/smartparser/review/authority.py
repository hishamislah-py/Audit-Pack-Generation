"""Phase 3B-2 - configurable approval authority.

Who may approve what is an OWNER DECISION that has not been made. The shipped policy
(`review/authority_policy.json`) therefore enables NO role for any scope: every approval attempt is refused until the
owner configures the policy and marks it OWNER_APPROVED.

Test fixtures may load a TEST_ONLY policy (provisional roles from the Phase 3A design) with test identities. Every
approval records whether it is a TEST or a BUSINESS approval; a BUSINESS approval is only possible under an
OWNER_APPROVED policy, and a TEST identity is only accepted by a policy that explicitly allows test identities.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_PATH = Path(__file__).parent / "authority_policy.json"
SCOPES = ("FILE_MAPPING", "ALIAS", "LAYOUT", "CATEGORY_CONFIRMATION", "CATEGORY_CONFLICT", "REVOCATION")


class AuthorityError(PermissionError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reviewer(_Strict):
    reviewer_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    kind: Literal["TEST", "BUSINESS"]


class ScopeRule(_Strict):
    roles: list[str] = Field(default_factory=list)
    approvers_required: int = Field(default=1, ge=1)
    roles_required_together: list[str] = Field(default_factory=list)   # e.g. data_owner AND system_owner


class AuthorityPolicy(_Strict):
    policy_id: str
    status: Literal["PRODUCTION_UNCONFIGURED", "TEST_ONLY", "OWNER_APPROVED"]
    note: str = ""
    allow_test_identities: bool = False
    allow_sign_sensitive_reusable: bool = False     # owner decision (3B-1 §13.3); default: aliases may not
    scopes: dict[str, ScopeRule] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = POLICY_PATH) -> "AuthorityPolicy":
        p = cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
        unknown = set(p.scopes) - set(SCOPES)
        if unknown:
            raise ValueError(f"unknown scope(s) {sorted(unknown)}")
        if p.status == "PRODUCTION_UNCONFIGURED" and any(r.roles for r in p.scopes.values()):
            raise ValueError("an unconfigured production policy may not enable roles")
        return p

    def authorise(self, scope: str, reviewers: list[Reviewer]) -> str:
        """Raise AuthorityError unless `reviewers` may jointly approve in `scope`. Returns TEST or BUSINESS."""
        if scope not in SCOPES:
            raise AuthorityError(f"unknown scope {scope}")
        rule = self.scopes.get(scope)
        if rule is None or not rule.roles:
            raise AuthorityError(f"{scope}: no role is authorised by policy {self.policy_id} ({self.status}); "
                                 "this is an open owner decision")
        if not reviewers:
            raise AuthorityError(f"{scope}: no reviewer")
        for r in reviewers:
            if r.role not in rule.roles:
                raise AuthorityError(f"{scope}: role {r.role!r} of {r.reviewer_id} is not authorised")
            if r.kind == "TEST" and not self.allow_test_identities:
                raise AuthorityError(f"{scope}: test identity {r.reviewer_id} is not accepted by {self.policy_id}")
            if r.kind == "BUSINESS" and self.status != "OWNER_APPROVED":
                raise AuthorityError(f"{scope}: business approvals need an OWNER_APPROVED policy, "
                                     f"{self.policy_id} is {self.status}")
        if len({r.reviewer_id for r in reviewers}) < rule.approvers_required:
            raise AuthorityError(f"{scope}: {rule.approvers_required} distinct approver(s) required")
        missing = set(rule.roles_required_together) - {r.role for r in reviewers}
        if missing:
            raise AuthorityError(f"{scope}: approval by role(s) {sorted(missing)} is also required")
        return "TEST" if any(r.kind == "TEST" for r in reviewers) else "BUSINESS"
