"""Canonical schema definition model (Module E).

A definition is pure data (JSON). Every definition carries its own
``verification_status`` and ``definition_source`` so the system can never
present an unverified contract as authoritative.
"""
from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from ..mapping.names import normalise_name


class SchemaVerification(StrEnum):
    VERIFIED = "verified"        # taken from the authoritative UC-042 manifest
    PROVISIONAL = "provisional"  # proposed, NOT authoritative - flagged on every result
    MISSING = "missing"          # no definition available yet (stub)


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    CURRENCY_CODE = "currency_code"   # ISO 4217 alpha-3


class FieldConstraints(BaseModel):
    allowed_values: list[str] | None = None
    pattern: str | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    min_length: int | None = None
    max_length: int | None = None
    max_decimal_places: int | None = None

    @model_validator(mode="after")
    def _check_pattern(self):
        if self.pattern is not None:
            re.compile(self.pattern)
        return self


class FieldDefinition(BaseModel):
    name: str
    type: FieldType
    required: bool = False   # column must be present in the source
    nullable: bool = True    # cells may be empty
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    constraints: FieldConstraints = Field(default_factory=FieldConstraints)
    # --- provenance of a field generated from an authoritative definition (all optional) ---
    position: int | None = None              # 0-based column position in the canonical header
    source_type: str | None = None           # the source's own type code (UC-042: id, str, date, ts, ...)
    requiredness: str | None = None          # the source's value requiredness (UC-042: M / C / O)
    condition: str | None = None             # conditional requirement, as the source states it
    provenance: list[str] = Field(default_factory=list)


class MatchPolicy(StrEnum):
    SCORED = "scored"                # tiers 1-3 header scoring (synthetic/provisional schemas)
    EXACT_HEADER = "exact_header"    # the header row must equal the canonical header exactly (UC-042 rule)


class CsvClassificationHints(BaseModel):
    # Fields whose presence is required before this category is even a candidate.
    signature_fields: list[str] = Field(default_factory=list)
    match_policy: MatchPolicy = MatchPolicy.SCORED


DEFAULT_NULL_TOKENS = ["", "NULL", "null", "Null", "N/A", "n/a", "#N/A"]


class CsvContract(BaseModel):
    """File-level CSV contract taken from the authoritative definition."""
    header: list[str]                        # canonical header, exact order and casing
    encoding: str                            # as the source reads it
    delimiter: str
    primary_key: list[str] = Field(default_factory=list)
    empty_allowed: bool = False              # may legitimately contain no data rows
    scope_file: bool = False                 # any invalid row makes the whole file unusable
    provenance: list[str] = Field(default_factory=list)


class PolicyVersionInfo(BaseModel):
    version: str
    effective: str                           # ISO date
    classification: str
    required_markings: list[str]
    description: str = ""
    decision: str = ""


class PdfLabel(BaseModel):
    label: str
    role: str | None = None                  # documented meaning, if the source documents one
    value_type: str | None = None            # None: the source does not define a type (never invented)


class PdfContract(BaseModel):
    """PDF identification contract taken from the authoritative definition."""
    labels: list[PdfLabel]
    label_pattern: str                       # regex template applied per label, {label} = re.escape(label)
    identification_rule: str
    shared_label_group: list[str] = Field(default_factory=list)  # categories with an identical label set
    slot_account_id: str | None = None       # account whose letter fills this slot (IN-15/IN-16)
    slot_resolution: str | None = None       # how the account-specific slot is chosen
    policy_versions: list[PolicyVersionInfo] = Field(default_factory=list)  # IN-17 recognised versions
    policy_recognition_rule: str | None = None
    text_normalisation: str | None = None    # IN-17 markings comparison
    period_note: str | None = None
    provenance: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    """A cross-document relationship as documented in the source (recorded, not enforced in Phase 1)."""
    field: str
    target_category: str | list[str]
    target_field: str | None = None
    kind: str
    description: str
    provenance: str


class SchemaDefinition(BaseModel):
    category: str
    title: str
    evidence_format: str                     # "csv" | "pdf"
    optional_evidence: bool = False
    schema_version: str = "0.0.0"
    verification_status: SchemaVerification = SchemaVerification.MISSING
    definition_source: str | None = None     # e.g. "UC-042 schema manifest v1"
    notes: str = ""
    fields: list[FieldDefinition] = Field(default_factory=list)
    unique_key: list[str] = Field(default_factory=list)
    null_tokens: list[str] = Field(default_factory=lambda: list(DEFAULT_NULL_TOKENS))
    classification: CsvClassificationHints = Field(default_factory=CsvClassificationHints)
    # --- authoritative-definition content (all optional; synthetic schemas leave them empty) ---
    official_name: str | None = None
    requirement: str | None = None            # REQUIRED / OPTIONAL in the upload contract
    canonical_filename_pattern: str | None = None   # informational only: never used to classify
    csv: CsvContract | None = None
    pdf: PdfContract | None = None
    period_rule: dict | None = None
    period_rule_note: str | None = None
    relationships: list[Relationship] = Field(default_factory=list)
    consumed_by_checks: list[str] = Field(default_factory=list)
    recurring_document: bool | None = None
    unresolved: list[str] = Field(default_factory=list)
    provenance: dict | None = None

    @property
    def is_defined(self) -> bool:
        if self.verification_status == SchemaVerification.MISSING:
            return False
        return bool(self.fields) or (self.evidence_format == "pdf" and self.pdf is not None)

    def field(self, name: str) -> FieldDefinition | None:
        return next((f for f in self.fields if f.name == name), None)

    @model_validator(mode="after")
    def _consistency(self):
        if self.evidence_format not in ("csv", "pdf"):
            raise ValueError(f"{self.category}: evidence_format must be csv or pdf")
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.category}: duplicate field names")
        for key in self.unique_key + self.classification.signature_fields:
            if key not in names:
                raise ValueError(f"{self.category}: '{key}' referenced but not defined")
        if self.verification_status != SchemaVerification.MISSING and not self.fields and self.pdf is None:
            raise ValueError(f"{self.category}: non-missing schema must define fields")
        if self.csv is not None:
            if self.evidence_format != "csv":
                raise ValueError(f"{self.category}: csv contract on a {self.evidence_format} schema")
            if self.csv.header != [f.name for f in sorted(self.fields, key=lambda f: (f.position is None, f.position))]:
                raise ValueError(f"{self.category}: csv header does not match the field list/positions")
            if len(set(self.csv.header)) != len(self.csv.header):
                raise ValueError(f"{self.category}: duplicate column in canonical header")
        if self.pdf is not None and self.evidence_format != "pdf":
            raise ValueError(f"{self.category}: pdf contract on a {self.evidence_format} schema")
        if self.classification.match_policy == MatchPolicy.EXACT_HEADER and self.csv is None:
            raise ValueError(f"{self.category}: exact_header matching needs a csv contract")
        if self.verification_status == SchemaVerification.VERIFIED and not self.definition_source:
            raise ValueError(f"{self.category}: verified schema must state definition_source")
        # An alias/name that normalises to the same token for two different fields
        # would make mapping ambiguous by construction - reject at load time.
        owner: dict[str, str] = {}
        for f in self.fields:
            for token in {normalise_name(f.name), *(normalise_name(a) for a in f.aliases)}:
                if token in owner and owner[token] != f.name:
                    raise ValueError(
                        f"{self.category}: '{token}' matches both '{owner[token]}' and '{f.name}'"
                    )
                owner[token] = f.name
        return self
