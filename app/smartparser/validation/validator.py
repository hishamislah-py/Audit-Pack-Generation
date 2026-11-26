"""Module I - deterministic validation.

Validation never fills, corrects or guesses values. It only reports.
An unmapped (additional) column is INFO and never invalidates a file.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from ..csv_engine.reader import CsvTable
from ..models.enums import IssueCode, Severity, ValidationStatus
from ..models.results import Issue, MappingResult, ValidationResult
from ..normalise.engine import NormalisedTable
from ..schemas.model import FieldDefinition, SchemaDefinition

STEP = "validation"


@dataclass
class ValidationConfig:
    strict_date_order: bool = False      # ambiguous DD/MM vs MM/DD -> error instead of warning
    max_issues_per_group: int = 200      # cap per (code, field) to keep results readable


class _Collector:
    def __init__(self, cap: int):
        self.cap = cap
        self.issues: list[Issue] = []
        self._counts: dict[tuple, int] = defaultdict(int)

    def add(self, code: IssueCode, severity: Severity, message: str, **kw):
        key = (code, kw.get("field") or kw.get("column"))
        self._counts[key] += 1
        if self._counts[key] <= self.cap:
            self.issues.append(Issue(code=code, severity=severity, message=message, step=STEP, **kw))

    def finalise(self):
        for (code, target), n in self._counts.items():
            if n > self.cap:
                sev = next(i.severity for i in self.issues if i.code == code)
                self.issues.append(Issue(
                    code=code, severity=sev, step=STEP, field=target,
                    message=f"{n - self.cap} further '{code}' issues for '{target}' not listed "
                            f"({n} in total)"))


def _check_constraints(f: FieldDefinition, value, raw: str) -> list[str]:
    c = f.constraints
    errs = []
    if c.allowed_values is not None and str(value) not in c.allowed_values:
        errs.append(f"value not in allowed values {c.allowed_values}")
    if c.pattern is not None and not re.fullmatch(c.pattern, raw.strip()):
        errs.append(f"value does not match pattern {c.pattern!r}")
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        if c.min_value is not None and value < c.min_value:
            errs.append(f"value below minimum {c.min_value}")
        if c.max_value is not None and value > c.max_value:
            errs.append(f"value above maximum {c.max_value}")
    if isinstance(value, Decimal) and c.max_decimal_places is not None:
        exp = value.as_tuple().exponent
        if isinstance(exp, int) and -exp > c.max_decimal_places:
            errs.append(f"more than {c.max_decimal_places} decimal places")
    if isinstance(value, str):
        if c.min_length is not None and len(value) < c.min_length:
            errs.append(f"shorter than {c.min_length} characters")
        if c.max_length is not None and len(value) > c.max_length:
            errs.append(f"longer than {c.max_length} characters")
    return errs


def validate_csv(table: CsvTable, mapping: MappingResult, schema: SchemaDefinition,
                 norm: NormalisedTable, config: ValidationConfig | None = None) -> ValidationResult:
    cfg = config or ValidationConfig()
    col = _Collector(cfg.max_issues_per_group)
    E, W, I = Severity.ERROR, Severity.WARNING, Severity.INFO

    # ---- mapping-level
    for f in mapping.missing_required_fields:
        col.add(IssueCode.MISSING_REQUIRED_FIELD, E, f"Required field '{f}' has no source column", field=f)
    for f in mapping.missing_optional_fields:
        col.add(IssueCode.MISSING_OPTIONAL_FIELD, I, f"Optional field '{f}' not present", field=f)
    for a in mapping.ambiguities:
        col.add(IssueCode.AMBIGUOUS_MAPPING, E,
                f"Ambiguous mapping: columns {a.source_columns} -> fields {a.candidate_fields} ({a.reason})",
                field=a.candidate_fields[0] if len(a.candidate_fields) == 1 else None,
                column=a.source_columns[0] if len(a.source_columns) == 1 else None)
    for c in mapping.unmapped_columns:
        col.add(IssueCode.UNMAPPED_COLUMN, I, f"Additional column '{c}' preserved but not mapped", column=c)

    # ---- structural
    if table.preamble:
        col.add(IssueCode.PREAMBLE_ROWS, I, f"{len(table.preamble)} line(s) before the header row skipped")
    for i in table.blank_header_indexes:
        col.add(IssueCode.BLANK_HEADER, W, f"Column {i + 1} has a blank header",
                column=table.headers[i])
    for h in table.duplicate_headers:
        col.add(IssueCode.DUPLICATE_HEADER, W, f"Header '{h}' appears more than once", column=h)
    for ln in table.empty_row_lines:
        col.add(IssueCode.EMPTY_ROW, I, "Empty row skipped", source_line=ln)
    for r in table.rows:
        if len(r.cells) != len(table.headers):
            col.add(IssueCode.RAGGED_ROW, E,
                    f"Row has {len(r.cells)} values but the header has {len(table.headers)}; "
                    "column alignment for this row is unreliable",
                    row=r.row_number, source_line=r.source_line)
    if not table.rows:
        col.add(IssueCode.NO_DATA_ROWS, W, "File has a header but no data rows")
    for i, h in enumerate(table.headers):
        if table.rows and not any(v.strip() for v in table.column_values(i)):
            col.add(IssueCode.EMPTY_COLUMN, I, f"Column '{h}' has no values", column=h)

    # ---- column-level normalisation decisions
    for ctx in norm.columns.values():
        if ctx.date_problem == "ambiguous":
            col.add(IssueCode.AMBIGUOUS_DATE_ORDER, E if cfg.strict_date_order else W,
                    f"No value in '{ctx.source_column}' disambiguates day/month order; "
                    f"{ctx.date_order.upper()} applied", field=ctx.field, column=ctx.source_column)
        elif ctx.date_problem == "inconsistent":
            col.add(IssueCode.INCONSISTENT_DATE_ORDER, E,
                    f"Column '{ctx.source_column}' mixes DD/MM and MM/DD dates",
                    field=ctx.field, column=ctx.source_column)
        if ctx.decimal_problem == "ambiguous":
            col.add(IssueCode.AMBIGUOUS_DECIMAL_FORMAT, W,
                    f"Values like '1,234' in '{ctx.source_column}' could be thousands-grouped or "
                    "decimal-comma; thousands grouping applied", field=ctx.field, column=ctx.source_column)
        elif ctx.decimal_problem == "inconsistent":
            col.add(IssueCode.INCONSISTENT_DECIMAL_FORMAT, E,
                    f"Column '{ctx.source_column}' mixes decimal-point and decimal-comma numbers",
                    field=ctx.field, column=ctx.source_column)

    # ---- cell-level
    two_digit: dict[str, int] = defaultdict(int)
    for row, cells in zip(table.rows, norm.cells):
        for fname, cell in cells.items():
            f = schema.field(fname)
            ctx = norm.columns[fname]
            loc = dict(row=row.row_number, source_line=row.source_line,
                       column=ctx.source_column, field=fname)
            if cell.is_null:
                if not f.nullable:
                    col.add(IssueCode.NULL_NOT_ALLOWED, E, f"'{fname}' must not be empty",
                            value=cell.original, **loc)
                continue
            p = cell.parsed
            if not p.ok:
                col.add(IssueCode.INVALID_VALUE, E, f"Invalid {f.type.value}: {p.error}",
                        value=cell.original, **loc)
                continue
            if "unknown_iso4217_code" in p.notes:
                col.add(IssueCode.UNKNOWN_CURRENCY_CODE, W,
                        f"'{p.value}' is not in the ISO 4217 list", value=cell.original, **loc)
            if "two_digit_year_assumed_20xx" in p.notes:
                two_digit[fname] += 1
            for err in _check_constraints(f, p.value, cell.original):
                col.add(IssueCode.CONSTRAINT_VIOLATION, E, err, value=cell.original, **loc)
    for fname, n in two_digit.items():
        col.add(IssueCode.TWO_DIGIT_YEAR, W, f"{n} value(s) with a two-digit year; 20xx assumed",
                field=fname, column=norm.columns[fname].source_column)

    # ---- duplicates
    if schema.unique_key and all(k in norm.columns for k in schema.unique_key):
        seen: dict[tuple, int] = {}
        for row, rec in zip(table.rows, norm.records):
            key = tuple(rec.values.get(k) for k in schema.unique_key)
            if any(v is None for v in key):
                continue
            if key in seen:
                col.add(IssueCode.DUPLICATE_RECORD, E,
                        f"Duplicate key {dict(zip(schema.unique_key, map(str, key)))} "
                        f"(first seen in row {seen[key]})", row=row.row_number, source_line=row.source_line)
            else:
                seen[key] = row.row_number
    seen_rows: dict[tuple, int] = {}
    for row in table.rows:
        k = tuple(row.cells)
        if k in seen_rows:
            col.add(IssueCode.DUPLICATE_ROW, W, f"Row identical to row {seen_rows[k]}",
                    row=row.row_number, source_line=row.source_line)
        else:
            seen_rows[k] = row.row_number

    col.finalise()
    errors = sum(1 for i in col.issues if i.severity == E)
    warnings = sum(1 for i in col.issues if i.severity == W)
    status = (ValidationStatus.INVALID if errors else
              ValidationStatus.VALID_WITH_WARNINGS if warnings else ValidationStatus.VALID)
    return ValidationResult(status=status, error_count=errors, warning_count=warnings, issues=col.issues)
