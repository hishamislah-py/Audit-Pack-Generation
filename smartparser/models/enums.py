"""Status vocabularies shared by every module.

The spec requires several outcome states to be kept *separate* (parsed, partially
parsed, missing required fields, invalid values, unmapped columns, unknown
category, needs resolution). Each processing stage therefore has its own status
enum instead of a single overloaded "status" field.
"""
from enum import StrEnum


class FileFormat(StrEnum):
    CSV = "csv"
    PDF = "pdf"
    ZIP = "zip"
    UNKNOWN = "unknown"


class ProcessingStatus(StrEnum):
    COMPLETED = "completed"                          # valid, no warnings
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # processed, validation found errors
    NEEDS_RESOLUTION = "needs_resolution"            # human/AI decision required
    FAILED = "failed"                                # extraction failed
    REJECTED = "rejected"                            # unsupported / corrupt / unsafe input
    NOT_IMPLEMENTED = "not_implemented"              # format handled in a later phase


class ClassificationStatus(StrEnum):
    IDENTIFIED = "identified"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    NOT_ATTEMPTED = "not_attempted"


class ClassificationMethod(StrEnum):
    CSV_HEADER_MATCH = "csv_header_match"
    CSV_EXACT_HEADER = "csv_exact_header"     # header row equals one canonical header exactly
    CSV_CONTROLLED_MAPPING = "csv_controlled_mapping"  # Phase 2: reorder / policy whitespace+case / approved alias
    MAPPING_TEMPLATE = "mapping_template"
    PDF_TEXT_PATTERN = "pdf_text_pattern"
    AI_SUGGESTION = "ai_suggestion"
    MANUAL = "manual"
    NONE = "none"


class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"
    NOT_IMPLEMENTED = "not_implemented"


class MappingStatus(StrEnum):
    COMPLETE = "complete"                      # every required field mapped, no ambiguity
    INCOMPLETE = "incomplete"                  # one or more required fields missing
    AMBIGUOUS = "ambiguous"                    # conflicting candidates recorded, not resolved
    SCHEMA_UNAVAILABLE = "schema_unavailable"  # category known but no verified definition
    NOT_ATTEMPTED = "not_attempted"


class ValidationStatus(StrEnum):
    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    INVALID = "invalid"
    NOT_VALIDATED = "not_validated"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class StepStatus(StrEnum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_IMPLEMENTED = "not_implemented"


class MatchMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    NORMALISED = "normalised"
    TEMPLATE = "template"
    MANUAL = "manual"
    POLICY_NORMALISED = "policy_normalised"   # Phase 2: whitespace/case only, under the explicit mapping policy
    APPROVED_LAYOUT = "approved_layout"       # Phase 3B-2: governed source-system layout (exact header list)
    APPROVED_FILE_MAPPING = "approved_file_mapping"  # Phase 3B-2: governed one-upload mapping
    # AI suggestions are never applied automatically; they are recorded separately.


class IssueCode(StrEnum):
    # intake / identification
    EMPTY_FILE = "empty_file"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE = "unsupported_file"
    CORRUPTED_FILE = "corrupted_file"
    EXTENSION_MISMATCH = "extension_mismatch"
    ENCODING_FALLBACK = "encoding_fallback"
    DELIMITER_UNCERTAIN = "delimiter_uncertain"
    DUPLICATE_UPLOAD = "duplicate_upload"
    DUPLICATE_UPLOAD_OTHER_PERIOD = "duplicate_upload_other_period"
    NOT_IMPLEMENTED = "not_implemented"
    # extraction
    MALFORMED_CSV = "malformed_csv"
    NO_DATA_ROWS = "no_data_rows"
    PREAMBLE_ROWS = "preamble_rows"
    EMPTY_ROW = "empty_row"
    EMPTY_COLUMN = "empty_column"
    RAGGED_ROW = "ragged_row"
    BLANK_HEADER = "blank_header"
    DUPLICATE_HEADER = "duplicate_header"
    # classification / schema
    UNKNOWN_CATEGORY = "unknown_category"
    AMBIGUOUS_CATEGORY = "ambiguous_category"
    SCHEMA_UNAVAILABLE = "schema_unavailable"
    SCHEMA_UNVERIFIED = "schema_unverified"
    FORCED_CATEGORY_REJECTED = "forced_category_rejected"   # supplied category fails its controlled mapping rules
    NON_EXACT_HEADER = "non_exact_header"           # near a canonical header but not equal: not accepted
    NON_CANONICAL_SERIALISATION = "non_canonical_serialisation"  # exact header, but not UTF-8 / comma / line 1
    CONTENT_NONCONFORMING = "content_nonconforming"  # exact header, some rows break the field rules
    PDF_UNREADABLE = "pdf_unreadable"
    PDF_IMAGE_ONLY = "pdf_image_only"               # scanned / image-only: OCR is not supported
    PDF_NO_TEXT = "pdf_no_text"
    PDF_POLICY_NOT_RECOGNISED = "pdf_policy_not_recognised"
    # mapping
    UNMAPPED_COLUMN = "unmapped_column"
    AMBIGUOUS_MAPPING = "ambiguous_mapping"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    MISSING_OPTIONAL_FIELD = "missing_optional_field"
    # normalisation / validation
    INVALID_VALUE = "invalid_value"
    NULL_NOT_ALLOWED = "null_not_allowed"
    CONSTRAINT_VIOLATION = "constraint_violation"
    AMBIGUOUS_DATE_ORDER = "ambiguous_date_order"
    INCONSISTENT_DATE_ORDER = "inconsistent_date_order"
    AMBIGUOUS_DECIMAL_FORMAT = "ambiguous_decimal_format"
    INCONSISTENT_DECIMAL_FORMAT = "inconsistent_decimal_format"
    TWO_DIGIT_YEAR = "two_digit_year"
    UNKNOWN_CURRENCY_CODE = "unknown_currency_code"
    DUPLICATE_RECORD = "duplicate_record"
    DUPLICATE_ROW = "duplicate_row"
