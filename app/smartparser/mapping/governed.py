"""Phase 3B-2 - governed mapping rule records (strict): approved source-system layouts and approved file-specific
mappings, plus the approval and lifecycle metadata shared with governed aliases.

A rule never contains model output: it holds the final field choices made by authorised people. Rules are never
deleted; revocation and supersession change `lifecycle.status` and record who/when/why, and only `active` rules match.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RuleStatus = Literal["active", "revoked", "superseded"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def header_fingerprint(headers: list[str]) -> str:
    """Fingerprint of the EXACT ordered header list (no trimming, no case folding, no normalisation)."""
    return hashlib.sha256(json.dumps(list(headers), ensure_ascii=False).encode("utf-8")).hexdigest()


def definition_sha256(schema) -> str:
    """Hash of one category's registry definition; rules are valid only for the definition they were approved on."""
    return hashlib.sha256(schema.model_dump_json().encode("utf-8")).hexdigest()


class Approval(_Strict):
    approver_id: str = Field(min_length=1)
    approver_role: str = Field(min_length=1)
    approval_kind: Literal["TEST", "BUSINESS", "POC_AUTO"]   # POC_AUTO: Phase 3B-6 policy, not a person
    approved_at: str = Field(min_length=1)
    basis: str = Field(min_length=1)


class Lifecycle(_Strict):
    status: RuleStatus = "active"
    revoked_at: str | None = None
    revoked_by: str | None = None
    revoked_role: str | None = None
    revocation_reason: str | None = None
    superseded_by: str | None = None
    superseded_at: str | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "revoked" and not (self.revoked_at and self.revoked_by and self.revocation_reason):
            raise ValueError("a revoked rule needs revoked_at, revoked_by and revocation_reason")
        if self.status == "superseded" and not (self.superseded_by and self.superseded_at):
            raise ValueError("a superseded rule needs superseded_by and superseded_at")
        return self


class ColumnRule(_Strict):
    source_index: int = Field(ge=0)
    source_header: str
    canonical_field: str | None        # None: left unmapped by the reviewer (file mappings only)
    # Phase 3B-7: an explicit reviewer exclusion of this column from the canonical output (file mappings only). The
    # column stays in the source, the records and the provenance; it never satisfies a canonical field.
    disposition: Literal["MAP", "IGNORE"] = "MAP"
    ignore_reason: str | None = None

    @model_validator(mode="after")
    def _ignore(self):
        if self.disposition == "IGNORE" and (self.canonical_field is not None or not (self.ignore_reason or "").strip()):
            raise ValueError("an IGNORE column has no canonical field and needs a reason")
        if self.disposition == "MAP" and self.ignore_reason:
            raise ValueError("ignore_reason is only for IGNORE columns")
        return self


class _HeaderRule(_Strict):
    rule_version: int = Field(ge=1)
    category: str
    headers: list[str] = Field(min_length=1)
    header_fingerprint: str
    columns: list[ColumnRule]
    approvals: list[Approval] = Field(min_length=1)
    registry_definition_sha256: str
    mapping_rules_version: str
    proposal_id: str | None = None
    decision_ids: list[str] = Field(default_factory=list)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)

    @model_validator(mode="after")
    def _columns(self):
        if self.header_fingerprint != header_fingerprint(self.headers):
            raise ValueError("header_fingerprint does not match the exact header list")
        if [c.source_index for c in self.columns] != list(range(len(self.headers))):
            raise ValueError("columns must list every source column exactly once, in order")
        if [c.source_header for c in self.columns] != self.headers:
            raise ValueError("column headers differ from the header list")
        fields = [c.canonical_field for c in self.columns if c.canonical_field is not None]
        if len(fields) != len(set(fields)):
            raise ValueError("two columns map to the same canonical field")
        if not SHA256_RE.match(self.registry_definition_sha256):
            raise ValueError("registry_definition_sha256 must be 64 lowercase hex characters")
        return self

    @property
    def approval_kind(self) -> str:
        return "TEST" if any(a.approval_kind == "TEST" for a in self.approvals) else "BUSINESS"


class LayoutRule(_HeaderRule):
    """B. A named source system's complete, ordered header layout, approved as a whole."""
    layout_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_system_version: str = Field(min_length=1)
    sign_sensitive_acknowledged: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _complete(self):
        if any(c.canonical_field is None or c.disposition != "MAP" for c in self.columns):
            raise ValueError("a layout must map every source column (IGNORE is for one-upload file mappings only)")
        return self

    @property
    def rule_id(self) -> str:
        return self.layout_id


class FileMappingRule(_HeaderRule):
    """C. A one-off decision for exactly one upload (intake ID + source SHA-256). Never reused."""
    file_mapping_id: str = Field(min_length=1)
    intake_id: str = Field(min_length=1)
    source_sha256: str
    review_session_id: str = Field(min_length=1)

    @field_validator("source_sha256")
    @classmethod
    def _sha(cls, v):
        if not SHA256_RE.match(v):
            raise ValueError("source_sha256 must be 64 lowercase hex characters")
        return v

    @model_validator(mode="after")
    def _traceable(self):
        if not self.proposal_id or not self.decision_ids:
            raise ValueError("a file mapping must reference its proposal and review decisions")
        return self

    @property
    def rule_id(self) -> str:
        return self.file_mapping_id
