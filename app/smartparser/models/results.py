"""Output contract: common evidence metadata + per-file processing result.

These models are the boundary between modules and the eventual integration
point with the UC-042 application. Decimal values serialise to JSON as strings
(pydantic default), so no precision is lost.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    ClassificationMethod,
    ClassificationStatus,
    ExtractionStatus,
    FileFormat,
    IssueCode,
    MappingStatus,
    MatchMethod,
    ProcessingStatus,
    Severity,
    StepStatus,
    ValidationStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Issue(BaseModel):
    code: IssueCode
    severity: Severity
    message: str
    step: str | None = None
    row: int | None = None            # 1-based data-row number
    source_line: int | None = None    # physical line in the source file
    column: str | None = None         # original source column name
    field: str | None = None          # canonical field name
    value: str | None = None          # original source value


class StepResult(BaseModel):
    step: str
    status: StepStatus
    message: str = ""


# --------------------------------------------------------------------------- metadata

class SourceProvenance(BaseModel):
    received_at: datetime = Field(default_factory=utcnow)
    upload_id: str | None = None             # groups files uploaded together
    stored_path: str | None = None           # preserved original (content-addressed)
    container_filename: str | None = None    # ZIP the file came from (Phase 4)
    path_in_container: str | None = None
    submitted_by: str | None = None


class EvidenceMetadata(BaseModel):
    """Common metadata - identical for all 19 categories."""
    evidence_id: str
    evidence_category: str | None = None
    original_filename: str
    sha256: str
    size_bytes: int
    reporting_period: str | None = None      # YYYY-MM, supplied by uploader
    file_format: FileFormat = FileFormat.UNKNOWN
    processing_status: ProcessingStatus
    classification_status: ClassificationStatus = ClassificationStatus.NOT_ATTEMPTED
    extraction_status: ExtractionStatus = ExtractionStatus.NOT_ATTEMPTED
    mapping_status: MappingStatus = MappingStatus.NOT_ATTEMPTED
    validation_status: ValidationStatus = ValidationStatus.NOT_VALIDATED
    provenance: SourceProvenance = Field(default_factory=SourceProvenance)


# --------------------------------------------------------------------------- stage outputs

class FileIdentification(BaseModel):
    detected_format: FileFormat
    extension: str | None = None
    extension_format: FileFormat = FileFormat.UNKNOWN
    extension_matches: bool = False
    readable: bool = False
    encoding: str | None = None
    encoding_method: str | None = None       # bom | utf8_strict | charset_normalizer
    has_bom: bool = False
    delimiter: str | None = None
    delimiter_confidence: float | None = None
    # PDF facts are filled in Phase 3.
    pdf_page_count: int | None = None
    pdf_has_text: bool | None = None
    ocr_required: bool | None = None
    notes: list[str] = Field(default_factory=list)


class ClassificationCandidate(BaseModel):
    category: str
    score: float
    required_coverage: float
    header_coverage: float
    matched_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    signature_satisfied: bool = True


class ClassificationResult(BaseModel):
    status: ClassificationStatus
    category: str | None = None
    method: ClassificationMethod = ClassificationMethod.NONE
    confidence: float | None = None
    candidates: list[ClassificationCandidate] = Field(default_factory=list)
    reason: str = ""
    # Content evidence behind the decision (all optional):
    diagnosis: dict[str, Any] | None = None       # why a near-miss header/label set was NOT accepted
    content_check: dict[str, Any] | None = None   # data rows checked against the identified category's field rules
    details: dict[str, Any] = Field(default_factory=dict)   # PDF labels found, policy version, letter slot, ...
    warnings: list[str] = Field(default_factory=list)
    unsupported: str | None = None                # e.g. "image_only_pdf", "zip", "empty", "binary"


class ColumnProfile(BaseModel):
    index: int
    name: str                      # header after trimming
    raw_name: str                  # header exactly as in the file
    inferred_type: str
    non_empty_count: int
    empty_count: int
    sample_values: list[str] = Field(default_factory=list)


class CsvExtraction(BaseModel):
    headers: list[str]
    raw_headers: list[str]
    header_line: int
    data_row_count: int
    preamble_lines: list[str] = Field(default_factory=list)
    columns: list[ColumnProfile] = Field(default_factory=list)
    empty_rows: list[int] = Field(default_factory=list)       # source lines
    ragged_rows: list[int] = Field(default_factory=list)      # source lines
    stopped_at_line: int | None = None                        # set if reading aborted


class ColumnMapping(BaseModel):
    source_column: str
    source_index: int
    canonical_field: str
    method: MatchMethod
    template_id: str | None = None
    # Phase 2 controlled mapping provenance (None for other mapping paths):
    variation: str | None = None          # exact / whitespace / case / case+whitespace / alias
    original_header: str | None = None    # header cell exactly as in the file
    alias_id: str | None = None           # active approved alias used, if any
    rule_id: str | None = None            # Phase 3B-2: governed rule (alias / layout / file mapping) used
    rule_version: int | None = None


class AmbiguousMapping(BaseModel):
    source_columns: list[str]
    candidate_fields: list[str]
    reason: str


class MappingResult(BaseModel):
    status: MappingStatus
    category: str | None = None
    schema_version: str | None = None
    schema_verification: str | None = None
    layout_fingerprint: str | None = None
    template_id: str | None = None
    mappings: list[ColumnMapping] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    missing_optional_fields: list[str] = Field(default_factory=list)
    ambiguities: list[AmbiguousMapping] = Field(default_factory=list)
    ai_suggestions: list[dict[str, Any]] = Field(default_factory=list)  # advisory only
    ignored_columns: list[dict[str, Any]] = Field(default_factory=list)  # Phase 3B-7 governed exclusions


class Record(BaseModel):
    """One extracted row. ``values`` are normalised canonical values (None when
    null or invalid); ``original`` keeps every source cell keyed by original
    column name, so nothing is lost and every value is traceable."""
    row_number: int
    source_line: int
    values: dict[str, Any] = Field(default_factory=dict)
    original: dict[str, str] = Field(default_factory=dict)
    unmapped: dict[str, str] = Field(default_factory=dict)
    invalid_fields: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    status: ValidationStatus
    error_count: int = 0
    warning_count: int = 0
    issues: list[Issue] = Field(default_factory=list)


class OutcomeFlags(BaseModel):
    """The separate states required by the spec, all independently visible."""
    parsed_successfully: bool = False
    partially_parsed: bool = False
    missing_required_fields: bool = False
    invalid_values: bool = False
    unmapped_columns: bool = False
    unknown_category: bool = False
    needs_resolution: bool = False


class EvidenceResult(BaseModel):
    metadata: EvidenceMetadata
    identification: FileIdentification | None = None
    classification: ClassificationResult | None = None
    csv_extraction: CsvExtraction | None = None
    mapping: MappingResult | None = None
    records: list[Record] = Field(default_factory=list)
    document_fields: list[dict[str, Any]] = Field(default_factory=list)  # PDF, Phase 3
    validation: ValidationResult | None = None
    issues: list[Issue] = Field(default_factory=list)   # non-validation issues
    steps: list[StepResult] = Field(default_factory=list)
    flags: OutcomeFlags = Field(default_factory=OutcomeFlags)

    def all_issues(self) -> list[Issue]:
        return self.issues + (self.validation.issues if self.validation else [])
