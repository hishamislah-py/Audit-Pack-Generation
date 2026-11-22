"""Phase 3B-3 - handoff eligibility: a separate, explicit 14-point checklist over a reprocessed result.

An approved proposal does not make a file eligible: only a deterministic result that passes every check below is.
Eligibility is for PREVIEW generation only - submission to UC-042 is not authorised (see HandoffPolicy).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..csv_engine.reader import read_csv
from ..models.enums import MappingStatus, MatchMethod
from ..schemas.registry import SchemaRegistry
from .reprocess import ReprocessResult

DETERMINISTIC_CATEGORY_METHODS = {"csv_exact_header", "csv_controlled_mapping"}
ALLOWED_METHODS = {MatchMethod.EXACT, MatchMethod.POLICY_NORMALISED, MatchMethod.ALIAS, MatchMethod.APPROVED_LAYOUT,
                   MatchMethod.APPROVED_FILE_MAPPING}
RULE_METHODS = {MatchMethod.ALIAS, MatchMethod.APPROVED_LAYOUT, MatchMethod.APPROVED_FILE_MAPPING}
CANONICAL_ENCODINGS = {"utf-8", "utf-8-sig"}


@dataclass(frozen=True)
class HandoffPolicy:
    allow_noncanonical_serialisation: bool = False   # D-1: unchanged - non-canonical files stay ineligible
    submission_enabled: bool = False                 # owner decision pending: never submit to UC-042


@dataclass
class Check:
    check_id: int
    name: str
    passed: bool
    detail: str = ""


@dataclass
class HandoffEligibility:
    eligible: bool
    checks: list[Check] = field(default_factory=list)
    submission_authorised: bool = False
    note: str = "eligibility allows a PREVIEW only; submission to UC-042 is not authorised"

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


def _active_rule(rules, method, rule_id, version) -> tuple[bool, str]:
    if method == MatchMethod.ALIAS:
        hits = [a for a in rules.aliases if a.alias_id == rule_id and a.rule_version == version]
        status = hits[0].status if hits else None
    elif method == MatchMethod.APPROVED_LAYOUT:
        hits = [x for x in rules.layouts if x.layout_id == rule_id and x.rule_version == version]
        status = hits[0].lifecycle.status if hits else None
    else:
        hits = [x for x in rules.file_mappings if x.file_mapping_id == rule_id and x.rule_version == version
                and rules.file_identity == (x.intake_id, x.source_sha256)]
        status = hits[0].lifecycle.status if hits else None
    if status is None:
        return False, f"{rule_id} v{version} is not a known rule for this file"
    return status == "active", f"{rule_id} v{version} is {status}"


def check_handoff(rr: ReprocessResult, registry: SchemaRegistry,
                  policy: HandoffPolicy = HandoffPolicy()) -> HandoffEligibility:
    r = rr.result
    checks: list[Check] = []
    add = lambda i, n, ok, d="": checks.append(Check(i, n, bool(ok), d))   # noqa: E731
    cls, mapping = r.classification, r.mapping
    schema = registry.get(rr.category) if rr.category else None

    method = cls.method.value if cls else "none"
    cat_ok = bool(rr.category) and r.metadata.classification_status == "identified" and (
        method in DETERMINISTIC_CATEGORY_METHODS or (method == "manual" and rr.confirmation_id is not None))
    add(1, "category deterministic or human-confirmed", cat_ok, f"{rr.category} via {method} ({rr.category_basis})")
    complete = mapping is not None and mapping.status == MappingStatus.COMPLETE
    add(2, "mapping complete", complete, mapping.status.value if mapping else "no mapping")
    mapped = [m.canonical_field for m in (mapping.mappings if mapping else [])]
    fields = [f.name for f in schema.fields] if schema else []
    add(3, "every canonical field mapped exactly once", schema is not None and sorted(mapped) == sorted(fields),
        f"{len(mapped)} mapped / {len(fields)} fields")
    dup = sorted({f for f in mapped if mapped.count(f) > 1})
    add(4, "no duplicate targets", not dup, ", ".join(dup))
    required = {f.name for f in schema.fields if f.requiredness == "M" or f.required} if schema else set()
    missing = sorted(required - set(mapped)) or (mapping.missing_required_fields if mapping else [])
    add(5, "no required field missing", schema is not None and not missing, ", ".join(missing))
    raw = r.csv_extraction.raw_headers if r.csv_extraction else []
    unmapped = (mapping.unmapped_columns if mapping else list(raw))
    ignored = list(mapping.ignored_columns) if mapping else []
    ignored_pos = {x["source_position"] for x in ignored}
    mapped_pos = {m.source_index for m in (mapping.mappings if mapping else [])}
    ignored_ok = all(x.get("rule_id") and (x.get("reason") or "").strip() for x in ignored) and not (ignored_pos & mapped_pos)
    add(6, "no unmapped source column (governed IGNORE decisions count as resolved, never as mapped)",
        mapping is not None and not unmapped and ignored_ok and len(mapped_pos | ignored_pos) == len(raw)
        and len(mapped) + len(ignored) == len(raw),
        ", ".join(unmapped) or (f"{len(ignored)} column(s) excluded by governed reviewer decision" if ignored else ""))
    bad_methods = [f"{m.source_column}:{m.method.value}" for m in (mapping.mappings if mapping else [])
                   if m.method not in ALLOWED_METHODS or (m.method in RULE_METHODS and not m.rule_id)]
    add(7, "every mapping exact, policy-normalised or backed by an approved rule", mapping is not None and not bad_methods,
        ", ".join(bad_methods))
    rule_findings, inactive = [], []
    for m in (mapping.mappings if mapping else []):
        if m.method in RULE_METHODS:
            ok, why = _active_rule(rr.rules, m.method, m.rule_id, m.rule_version)
            rule_findings.append(why)
            if not ok:
                inactive.append(why)
    for x in ignored:                         # an exclusion is only valid while its file-mapping rule is active
        ok, why = _active_rule(rr.rules, MatchMethod.APPROVED_FILE_MAPPING, x.get("rule_id"), x.get("rule_version"))
        rule_findings.append(why)
        if not ok:
            inactive.append(why)
    add(8, "rule IDs and versions valid", all("not a known rule" not in w for w in rule_findings),
        "; ".join(sorted(set(rule_findings))) or "no rule used")
    add(9, "no revoked or superseded rule used", not inactive, "; ".join(sorted(set(inactive))))
    v = r.validation
    add(10, "normalisation and validation without errors", v is not None and v.error_count == 0,
        f"{v.error_count} error(s)" if v else "not validated")
    cc = (cls.content_check or {}) if cls else {}
    # DIV-E2E-02: a file with NO data rows is only acceptable where the evidence contract allows it (registry
    # csv.empty_allowed, imported from UC-042 schema.EMPTY_ALLOWED: IN-04, IN-14); UC-042 reports every other one EMPTY
    empty_allowed = bool(schema and schema.csv and schema.csv.empty_allowed)
    no_rows = cc.get("rows_checked") == 0 and not empty_allowed
    add(11, "content check: zero nonconforming rows", cc.get("rows_checked") is not None and cc.get("nonconforming_rows") == 0
        and not no_rows,
        f"no data rows: {rr.category} may not be empty (UC-042 reports EMPTY_FILE)" if no_rows else
        f"{cc.get('nonconforming_rows')} of {cc.get('rows_checked')}")
    preserved, why = _source_cells_preserved(rr)
    add(12, "source values (incl. money) unmodified", preserved, why)
    prov_ok = (bool(rr.source_sha256 and rr.original_intake_id) and mapping is not None
               and all(m.original_header is not None and m.source_index is not None for m in mapping.mappings)
               and all(rec.source_line and rec.row_number for rec in r.records))
    add(13, "provenance complete", prov_ok, f"{len(r.records)} record(s) with line numbers")
    ident = r.identification
    serial_dev = []
    if ident is None or ident.encoding not in CANONICAL_ENCODINGS:
        serial_dev.append(f"encoding {ident.encoding if ident else None}")
    if ident is None or ident.delimiter != ",":
        serial_dev.append(f"delimiter {ident.delimiter if ident else None!r}")
    if r.csv_extraction and r.csv_extraction.preamble_lines:
        serial_dev.append("lines before the header")
    add(14, "serialisation policy (D-1)", not serial_dev or policy.allow_noncanonical_serialisation,
        "; ".join(serial_dev) or "UTF-8, comma, header on line 1")
    # submission_authorised stays False whatever the policy says: the UC-042 submission gate is not implemented.
    return HandoffEligibility(eligible=all(c.passed for c in checks), checks=checks, submission_authorised=False)


def source_rows(rr: ReprocessResult) -> list[list[str]]:
    ident = rr.result.identification
    table = read_csv(rr.source_bytes, ident.encoding, ident.delimiter)
    return [row.cells for row in table.rows]


def _source_cells_preserved(rr: ReprocessResult) -> tuple[bool, str]:
    """Every record's original cells equal the cells re-read from the stored source bytes (nothing reinterpreted)."""
    r = rr.result
    if r.identification is None or r.mapping is None or not r.csv_extraction:
        return False, "no source table"
    rows = source_rows(rr)
    if len(rows) != len(r.records):
        return False, f"{len(rows)} source rows vs {len(r.records)} records"
    width = len(r.csv_extraction.raw_headers)
    for rec, cells in zip(r.records, rows):
        if len(cells) != width:
            # DEF-E2E-01: a row with fewer (or more) cells than the header is never read past its end; the check fails
            # (fail-closed) instead of raising, so the file becomes FAILED_VALIDATION and other files keep processing
            return False, (f"row {rec.row_number} has {len(cells)} cell(s), the header has {width}: the source row is "
                           "malformed and is not repaired")
        for m in r.mapping.mappings:
            if rec.original.get(m.source_column) != cells[m.source_index]:
                return False, f"row {rec.row_number} column {m.source_column!r} differs from the source"
    return True, f"{len(rows)} row(s) x {len(r.mapping.mappings)} column(s) identical to the source"
