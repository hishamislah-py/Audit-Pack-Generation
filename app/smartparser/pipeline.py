"""Orchestrator: the only module that knows about all the others.

Flow for one file:
  intake (hash/store/duplicates) -> identification -> CSV read (extraction)
  -> classification -> mapping -> normalisation -> validation -> status roll-up

Each stage's outcome is recorded as a StepResult, and each stage's status is
kept separate in the metadata (classification / extraction / mapping /
validation), so "recognised but not extracted" and similar states are visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ai.interface import AIAssistant, NullAssistant
from .classify.content_check import check_rows
from .classify.csv_classifier import classify_csv, default_rules
from .classify.pdf_classifier import classify_pdf
from .pdf_engine import PdfEngineError, extract_pdf
from .csv_engine.reader import CsvReadError, CsvTable, profile, read_csv
from .identify.detect import IdentificationError, identify
from .intake.store import (
    DEFAULT_MAX_BYTES, EvidenceStore, display_filename, sha256_bytes, validate_reporting_period,
)
from .mapping.controlled import MappingRules, controlled_map, is_controlled, to_mapping_result
from .mapping.engine import map_columns
from .mapping.templates import TemplateRegistry, layout_fingerprint
from .models.enums import (
    ClassificationMethod, ClassificationStatus, ExtractionStatus, FileFormat, IssueCode,
    MappingStatus, ProcessingStatus, Severity, StepStatus, ValidationStatus,
)
from .models.results import (
    ClassificationResult, EvidenceMetadata, EvidenceResult, Issue, MappingResult,
    SourceProvenance, StepResult,
)
from .normalise.engine import normalise_table, raw_records
from .schemas.model import SchemaVerification
from .schemas.registry import SchemaRegistry
from .validation.validator import ValidationConfig, validate_csv


@dataclass
class ParserConfig:
    max_file_bytes: int = DEFAULT_MAX_BYTES
    default_date_order: str = "dmy"   # UK default; always reported when applied
    validation: ValidationConfig = field(default_factory=ValidationConfig)


class SmartParser:
    def __init__(self, schemas: SchemaRegistry | None = None,
                 templates: TemplateRegistry | None = None,
                 store: EvidenceStore | None = None,
                 ai: AIAssistant | None = None,
                 config: ParserConfig | None = None,
                 mapping_rules: MappingRules | None = None):
        self.schemas = schemas or SchemaRegistry.from_directory()
        self.mapping_rules = mapping_rules   # None: the shipped active controlled-mapping rules
        self.templates = templates or TemplateRegistry()
        self.store = store or EvidenceStore()
        self.ai = ai or NullAssistant()   # not consulted until Phase 6
        self.config = config or ParserConfig()

    # ------------------------------------------------------------------ public
    def process_bytes(self, data: bytes, filename: str, reporting_period: str | None = None,
                      forced_category: str | None = None,
                      manual_mapping: dict[str, str] | None = None,
                      provenance: SourceProvenance | None = None,
                      letter_refs: dict[str, str] | None = None) -> EvidenceResult:
        """letter_refs: {letter reference: category} from an account inventory (IN-02), used only to resolve the
        acknowledgement-letter slot of a PDF (see classify.pdf_classifier). None: no inventory available."""
        period = validate_reporting_period(reporting_period)
        prov = provenance or SourceProvenance()
        issues: list[Issue] = []
        steps: list[StepResult] = []

        # ---- Module A: intake
        digest = sha256_bytes(data)
        dup = self.store.check_duplicate(digest, period)
        rec = self.store.save(data, filename, period, upload_id=prov.upload_id)
        prov.stored_path = rec.stored_path
        meta = EvidenceMetadata(
            evidence_id=rec.evidence_id, original_filename=display_filename(filename),
            sha256=digest, size_bytes=len(data), reporting_period=period,
            processing_status=ProcessingStatus.FAILED, provenance=prov)
        result = EvidenceResult(metadata=meta)
        # pydantic copies list arguments, so bind to the model's own lists.
        issues, steps = result.issues, result.steps

        if dup.same_period:
            issues.append(Issue(code=IssueCode.DUPLICATE_UPLOAD, severity=Severity.WARNING, step="intake",
                                message=f"Identical file already uploaded for this period "
                                        f"(evidence {dup.same_period[0].evidence_id}, "
                                        f"'{dup.same_period[0].original_filename}')"))
        if dup.other_periods:
            periods = sorted({str(r.reporting_period) for r in dup.other_periods})
            issues.append(Issue(code=IssueCode.DUPLICATE_UPLOAD_OTHER_PERIOD, severity=Severity.WARNING,
                                step="intake",
                                message=f"Identical file was uploaded for other period(s): {periods}"))
        if len(data) > self.config.max_file_bytes:
            return self._reject(result, IssueCode.FILE_TOO_LARGE,
                                f"File exceeds {self.config.max_file_bytes} bytes", "intake")
        steps.append(StepResult(step="intake", status=StepStatus.WARNING if dup.same_period or
                                dup.other_periods else StepStatus.SUCCESS,
                                message=f"sha256 {digest[:12]}..., {len(data)} bytes"))

        # ---- Module B: identification
        try:
            ident = identify(data, filename)
        except IdentificationError as exc:
            code = {"empty": IssueCode.EMPTY_FILE, "unsupported": IssueCode.UNSUPPORTED_FILE,
                    "corrupted": IssueCode.CORRUPTED_FILE}[exc.kind]
            return self._reject(result, code, str(exc), "identification")
        result.identification = ident
        meta.file_format = ident.detected_format
        if not ident.extension_matches:
            issues.append(Issue(code=IssueCode.EXTENSION_MISMATCH, severity=Severity.WARNING,
                                step="identification",
                                message=f"Extension '{ident.extension}' does not match detected "
                                        f"content '{ident.detected_format}'; content wins"))
        if ident.encoding_method == "charset_normalizer":
            issues.append(Issue(code=IssueCode.ENCODING_FALLBACK, severity=Severity.WARNING,
                                step="identification",
                                message=f"Not UTF-8; encoding detected heuristically as {ident.encoding}"))
        if ident.delimiter_confidence is not None and ident.delimiter_confidence < 0.9:
            issues.append(Issue(code=IssueCode.DELIMITER_UNCERTAIN, severity=Severity.WARNING,
                                step="identification",
                                message=f"Delimiter {ident.delimiter!r} chosen with consistency "
                                        f"{ident.delimiter_confidence}"))
        steps.append(StepResult(step="identification", status=StepStatus.SUCCESS,
                                message=f"{ident.detected_format}"
                                        + (f", {ident.encoding}, delimiter {ident.delimiter!r}"
                                           if ident.detected_format == FileFormat.CSV else "")))

        if ident.detected_format == FileFormat.CSV:
            self._process_csv(result, data, forced_category, manual_mapping)
        elif ident.detected_format == FileFormat.PDF:
            self._classify_pdf(result, data, letter_refs)
            meta.extraction_status = ExtractionStatus.NOT_IMPLEMENTED
            meta.processing_status = ProcessingStatus.NOT_IMPLEMENTED
            issues.append(Issue(code=IssueCode.NOT_IMPLEMENTED, severity=Severity.INFO, step="extraction",
                                message="PDF classified by its key-detail labels (Phase 1); document-field "
                                        "extraction and validation are Phase 3"))
            steps.append(StepResult(step="extraction", status=StepStatus.NOT_IMPLEMENTED,
                                    message="Phase 3 (PDF engine)"))
        else:
            phase = "Phase 3 (PDF engine)" if ident.detected_format == FileFormat.PDF \
                else "Phase 4 (ZIP packages)"
            meta.extraction_status = ExtractionStatus.NOT_IMPLEMENTED
            meta.processing_status = ProcessingStatus.NOT_IMPLEMENTED
            issues.append(Issue(code=IssueCode.NOT_IMPLEMENTED, severity=Severity.INFO,
                                step="extraction", message=f"{ident.detected_format} handled in {phase}"))
            steps.append(StepResult(step="extraction", status=StepStatus.NOT_IMPLEMENTED, message=phase))
        self._roll_up(result)
        return result

    # ------------------------------------------------------------------ CSV
    def _process_csv(self, result: EvidenceResult, data: bytes, forced_category: str | None,
                     manual_mapping: dict[str, str] | None) -> None:
        meta, ident, issues, steps = result.metadata, result.identification, result.issues, result.steps

        # ---- Module D: extraction (structural read)
        try:
            table: CsvTable = read_csv(data, ident.encoding, ident.delimiter)
        except CsvReadError as exc:
            meta.extraction_status = ExtractionStatus.FAILED
            issues.append(Issue(code=IssueCode.MALFORMED_CSV, severity=Severity.ERROR,
                                step="extraction", message=str(exc), source_line=exc.line))
            steps.append(StepResult(step="extraction", status=StepStatus.FAILED, message=str(exc)))
            return
        result.csv_extraction = profile(table)
        if table.error:
            meta.extraction_status = ExtractionStatus.PARTIAL
            issues.append(Issue(code=IssueCode.MALFORMED_CSV, severity=Severity.ERROR,
                                step="extraction", source_line=table.stopped_at_line,
                                message=f"Reading stopped early: {table.error}; "
                                        f"{len(table.rows)} rows before that point were read"))
            steps.append(StepResult(step="extraction", status=StepStatus.WARNING,
                                    message=f"partial: {len(table.rows)} rows"))
        else:
            meta.extraction_status = ExtractionStatus.SUCCESS
            steps.append(StepResult(step="extraction", status=StepStatus.SUCCESS,
                                    message=f"{len(table.headers)} columns, {len(table.rows)} rows"))

        # ---- Module C: classification
        if forced_category:
            forced = self.schemas.get(forced_category)
            if forced is None:
                raise ValueError(f"Unknown category '{forced_category}'")
            if is_controlled(forced) or forced.evidence_format != "csv":
                # A supplied category is a claim about the evidence type, not about the columns: the header must
                # still pass that category's controlled mapping rules (Phase 3B-0).
                self._refuse_manual_mapping(manual_mapping, forced)
                cls = self._confirm_forced_category(table, forced)
            else:   # synthetic / provisional / stub schemas: unchanged generic behaviour
                cls = ClassificationResult(status=ClassificationStatus.IDENTIFIED, category=forced_category,
                                           method=ClassificationMethod.MANUAL, confidence=None,
                                           reason="Category supplied by user")
        else:
            cls = classify_csv(table.headers, self.schemas, self.templates, raw_headers=table.raw_headers,
                               rows=[r.cells for r in table.rows], rules=self.mapping_rules)
            if cls.category:
                self._refuse_manual_mapping(manual_mapping, self.schemas.get(cls.category))
        result.classification = cls
        meta.classification_status = cls.status
        meta.evidence_category = cls.category
        if cls.status != ClassificationStatus.IDENTIFIED:
            if cls.details.get("forced_category"):
                issues.append(Issue(code=IssueCode.FORCED_CATEGORY_REJECTED, severity=Severity.ERROR,
                                    step="classification", message=cls.reason))
            else:
                code = IssueCode.AMBIGUOUS_CATEGORY if cls.status == ClassificationStatus.AMBIGUOUS \
                    else IssueCode.UNKNOWN_CATEGORY
                issues.append(Issue(code=code, severity=Severity.WARNING, step="classification",
                                    message=cls.reason))
            steps.append(StepResult(step="classification", status=StepStatus.FAILED, message=cls.reason))
            result.records = raw_records(table)  # originals preserved even when unclassified
            result.mapping = MappingResult(status=MappingStatus.NOT_ATTEMPTED,
                                           layout_fingerprint=layout_fingerprint(table.headers),
                                           unmapped_columns=list(table.headers))
            meta.mapping_status = MappingStatus.NOT_ATTEMPTED
            return
        steps.append(StepResult(step="classification", status=StepStatus.SUCCESS,
                                message=f"{cls.category} via {cls.method}"))

        schema = self.schemas.get(cls.category)
        if schema.verification_status == SchemaVerification.PROVISIONAL:
            issues.append(Issue(code=IssueCode.SCHEMA_UNVERIFIED, severity=Severity.WARNING,
                                step="mapping",
                                message=f"Schema for {schema.category} is PROVISIONAL, not verified "
                                        "against the UC-042 manifest"))

        # ---- Module F: mapping
        if is_controlled(schema):
            # One mapping authority for UC-042 CSV categories, whatever decided the category (exact header, controlled
            # mapping, or a supplied category): the controlled rules. map_columns' looser tiers are never used here.
            cm = controlled_map(table.raw_headers, schema, self._rules())
            if not cm.accepted:   # cannot happen after classification/confirmation; refuse rather than guess
                raise RuntimeError(f"{schema.category}: controlled mapping rejected a classified file: {cm.rejections}")
            mapping = to_mapping_result(cm.mappings, schema, table.headers, cm.ignored_columns)
        else:
            mapping = map_columns(table.headers, schema, self.templates, manual_mapping)
        result.mapping = mapping
        meta.mapping_status = mapping.status
        if mapping.status == MappingStatus.SCHEMA_UNAVAILABLE:
            issues.append(Issue(code=IssueCode.SCHEMA_UNAVAILABLE, severity=Severity.WARNING,
                                step="mapping",
                                message=f"{schema.category} is recognised but has no canonical schema "
                                        "definition yet; original values preserved, not mapped"))
            steps.append(StepResult(step="mapping", status=StepStatus.SKIPPED,
                                    message="schema unavailable"))
            result.records = raw_records(table)
            return
        steps.append(StepResult(
            step="mapping",
            status=StepStatus.SUCCESS if mapping.status == MappingStatus.COMPLETE else StepStatus.WARNING,
            message=f"{len(mapping.mappings)} mapped, {len(mapping.unmapped_columns)} unmapped, "
                    f"{len(mapping.missing_required_fields)} required missing, "
                    f"{len(mapping.ambiguities)} ambiguous"))

        # ---- Module H: normalisation
        norm = normalise_table(table, mapping, schema, self.config.default_date_order)
        result.records = norm.records
        bad = sum(1 for cells in norm.cells for c in cells.values() if c.parsed and not c.parsed.ok)
        steps.append(StepResult(step="normalisation",
                                status=StepStatus.WARNING if bad else StepStatus.SUCCESS,
                                message=f"{bad} value(s) could not be normalised" if bad else "ok"))

        # ---- Module I: validation
        val = validate_csv(table, mapping, schema, norm, self.config.validation)
        result.validation = val
        meta.validation_status = val.status
        invalid: dict[int, set[str]] = {}
        for i in val.issues:
            if i.row is not None and i.field and i.severity == Severity.ERROR:
                invalid.setdefault(i.row, set()).add(i.field)
        for r in result.records:
            r.invalid_fields = sorted(invalid.get(r.row_number, ()))
        steps.append(StepResult(
            step="validation",
            status={ValidationStatus.VALID: StepStatus.SUCCESS,
                    ValidationStatus.VALID_WITH_WARNINGS: StepStatus.WARNING}.get(val.status, StepStatus.FAILED),
            message=f"{val.error_count} error(s), {val.warning_count} warning(s)"))

    # ------------------------------------------------------------------ supplied categories (Phase 3B-0)
    def _rules(self) -> MappingRules:
        return self.mapping_rules or default_rules(self.schemas)

    @staticmethod
    def _refuse_manual_mapping(manual_mapping, schema) -> None:
        if manual_mapping and is_controlled(schema):
            raise ValueError(f"manual_mapping is not accepted for {schema.category}: UC-042 categories are mapped only "
                             "by the controlled rules (canonical names, policy whitespace/case, approved aliases)")

    def _confirm_forced_category(self, table: CsvTable, schema) -> ClassificationResult:
        """Accept a supplied UC-042 category only if the header maps under that category's controlled rules."""
        rows = [r.cells for r in table.rows]
        content = classify_csv(table.headers, self.schemas, self.templates, raw_headers=table.raw_headers,
                               rows=rows, rules=self.mapping_rules)
        by_content = {"status": content.status.value, "category": content.category, "method": content.method.value}
        if schema.evidence_format != "csv":
            return ClassificationResult(
                status=ClassificationStatus.UNKNOWN,
                details={"forced_category": schema.category, "content_classification": by_content},
                reason=f"Supplied category {schema.category} rejected: it is a {schema.evidence_format.upper()} "
                       "evidence category and this file is CSV")
        cm = controlled_map(table.raw_headers, schema, self._rules())
        if not cm.accepted:
            return ClassificationResult(
                status=ClassificationStatus.UNKNOWN, diagnosis={"controlled_mapping": cm.as_dict()},
                details={"forced_category": schema.category, "content_classification": by_content},
                reason=f"Supplied category {schema.category} rejected: the header does not map under the "
                       f"{schema.category} controlled mapping rules: " + "; ".join(cm.rejections)
                       + (f". By content the file identifies as {content.category} ({content.method.value}); the "
                          "supplied category is not replaced automatically" if content.category else ""))
        res = ClassificationResult(
            status=ClassificationStatus.IDENTIFIED, category=schema.category, method=ClassificationMethod.MANUAL,
            confidence=None,
            details={"forced_category": schema.category, "category_source": "supplied",
                     "controlled_mapping": cm.as_dict(), "mapping_rules": self._rules().source,
                     "aliases_used": sorted({m["alias_id"] for m in cm.mappings if m["alias_id"]}),
                     "content_classification": by_content},
            reason=f"Category supplied by caller; header verified against the {schema.category} controlled mapping "
                   f"rules (variations: {', '.join(cm.variations) or 'none'})")
        # positional header over ALL source columns: a governed IGNORE position (3B-7) gets a placeholder that is never a
        # field name, so the remaining cells stay aligned with their fields and the row width matches the file
        positional = [f"<ignored column {i}>" for i in range(len(table.raw_headers))]
        for m in cm.mappings:
            positional[m["source_position"]] = m["canonical_field"]
        cc = check_rows(schema, positional, rows)
        res.content_check = cc
        if cc["rows_checked"] and cc["nonconforming_rows"]:
            res.warnings.append(f"{cc['nonconforming_rows']} of {cc['rows_checked']} data row(s) break the "
                                f"{schema.category} field rules")
        if content.category and content.category != schema.category:
            res.warnings.append(f"by content the file identifies as {content.category}")
        return res

    # ------------------------------------------------------------------ PDF (classification only)
    def _classify_pdf(self, result: EvidenceResult, data: bytes, letter_refs: dict[str, str] | None) -> None:
        meta, ident, issues, steps = result.metadata, result.identification, result.issues, result.steps
        try:
            ext = extract_pdf(data)
        except PdfEngineError as exc:
            cls = ClassificationResult(status=ClassificationStatus.UNKNOWN, reason=str(exc),
                                       unsupported="pdf_unreadable")
            issues.append(Issue(code=IssueCode.PDF_UNREADABLE, severity=Severity.ERROR, step="classification",
                                message=str(exc)))
        else:
            ident.pdf_page_count, ident.pdf_has_text = ext.page_count, ext.has_text
            ident.ocr_required = ext.image_only
            cls = classify_pdf(ext, self.schemas, letter_refs)
            if ext.image_only:
                issues.append(Issue(code=IssueCode.PDF_IMAGE_ONLY, severity=Severity.ERROR, step="classification",
                                    message=cls.reason))
            elif not ext.has_text:
                issues.append(Issue(code=IssueCode.PDF_NO_TEXT, severity=Severity.ERROR, step="classification",
                                    message=cls.reason))
            elif (cls.diagnosis or {}).get("status") == "POLICY_NOT_RECOGNISED":
                issues.append(Issue(code=IssueCode.PDF_POLICY_NOT_RECOGNISED, severity=Severity.ERROR,
                                    step="classification", message=cls.reason))
            result.document_fields = [{"label": k, "value": v} for k, v in cls.details.get("labels_found", {}).items()]
        result.classification = cls
        meta.classification_status = cls.status
        meta.evidence_category = cls.category
        if cls.status == ClassificationStatus.AMBIGUOUS:
            issues.append(Issue(code=IssueCode.AMBIGUOUS_CATEGORY, severity=Severity.WARNING, step="classification",
                                message=cls.reason))
        elif cls.status == ClassificationStatus.UNKNOWN and not cls.unsupported:
            issues.append(Issue(code=IssueCode.UNKNOWN_CATEGORY, severity=Severity.WARNING, step="classification",
                                message=cls.reason))
        steps.append(StepResult(step="classification",
                                status=StepStatus.SUCCESS if cls.status == ClassificationStatus.IDENTIFIED
                                else StepStatus.FAILED,
                                message=f"{cls.category} via {cls.method}" if cls.category else cls.reason))

    # ------------------------------------------------------------------ helpers
    def _reject(self, result: EvidenceResult, code: IssueCode, message: str, step: str) -> EvidenceResult:
        result.issues.append(Issue(code=code, severity=Severity.ERROR, step=step, message=message))
        result.steps.append(StepResult(step=step, status=StepStatus.FAILED, message=message))
        result.metadata.processing_status = ProcessingStatus.REJECTED
        result.metadata.extraction_status = ExtractionStatus.NOT_ATTEMPTED
        self._roll_up(result)
        return result

    @staticmethod
    def _roll_up(result: EvidenceResult) -> None:
        m, f = result.metadata, result.flags
        codes = {i.code for i in result.all_issues()}
        f.unknown_category = m.classification_status in (ClassificationStatus.UNKNOWN,
                                                          ClassificationStatus.AMBIGUOUS)
        f.missing_required_fields = bool(result.mapping and result.mapping.missing_required_fields)
        f.unmapped_columns = bool(result.mapping and result.mapping.unmapped_columns
                                  and m.mapping_status not in (MappingStatus.NOT_ATTEMPTED,))
        f.invalid_values = bool(codes & {IssueCode.INVALID_VALUE, IssueCode.NULL_NOT_ALLOWED,
                                         IssueCode.CONSTRAINT_VIOLATION, IssueCode.DUPLICATE_RECORD})
        f.partially_parsed = (m.extraction_status == ExtractionStatus.PARTIAL
                              or (m.extraction_status == ExtractionStatus.SUCCESS
                                  and bool(codes & {IssueCode.INVALID_VALUE, IssueCode.RAGGED_ROW})))
        f.parsed_successfully = (m.extraction_status == ExtractionStatus.SUCCESS
                                 and not f.partially_parsed)
        f.needs_resolution = (f.unknown_category
                              or m.mapping_status in (MappingStatus.AMBIGUOUS, MappingStatus.SCHEMA_UNAVAILABLE)
                              or IssueCode.INCONSISTENT_DATE_ORDER in codes
                              or IssueCode.INCONSISTENT_DECIMAL_FORMAT in codes)

        if m.processing_status in (ProcessingStatus.REJECTED, ProcessingStatus.NOT_IMPLEMENTED):
            return
        if m.extraction_status == ExtractionStatus.FAILED:
            m.processing_status = ProcessingStatus.FAILED
        elif f.needs_resolution:
            m.processing_status = ProcessingStatus.NEEDS_RESOLUTION
        elif m.validation_status == ValidationStatus.INVALID or m.extraction_status == ExtractionStatus.PARTIAL:
            m.processing_status = ProcessingStatus.COMPLETED_WITH_ERRORS
        elif m.validation_status == ValidationStatus.VALID_WITH_WARNINGS or any(
                i.severity == Severity.WARNING for i in result.issues):
            m.processing_status = ProcessingStatus.COMPLETED_WITH_WARNINGS
        else:
            m.processing_status = ProcessingStatus.COMPLETED
