"""Module H - apply value normalisation to a mapped CSV table.

Pure transformation: produces normalised values next to originals and records
column-level decisions (date order, decimal convention). It does not judge
validity - that is the validation module's job.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..csv_engine.reader import column_keys, CsvTable
from ..models.results import MappingResult, Record
from ..schemas.model import FieldType, SchemaDefinition
from . import values as nv


@dataclass
class ColumnContext:
    field: str
    source_column: str
    index: int
    type: FieldType
    date_order: str | None = None
    date_problem: str | None = None        # ambiguous | inconsistent
    decimal_convention: str | None = None
    decimal_problem: str | None = None


@dataclass
class Cell:
    original: str | None          # None when the row has no cell at this index
    is_null: bool
    parsed: nv.Parsed | None      # None when null / absent


@dataclass
class NormalisedTable:
    columns: dict[str, ColumnContext]
    cells: list[dict[str, Cell]]            # parallel to table.rows
    records: list[Record] = field(default_factory=list)


_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$")


def _parse(raw: str, ctx: ColumnContext, default_order: str) -> nv.Parsed:
    t = ctx.type
    if t == FieldType.STRING:
        return nv.parse_string(raw)
    if t == FieldType.INTEGER:
        return nv.parse_integer(raw)
    if t == FieldType.DECIMAL:
        return nv.parse_decimal(raw, ctx.decimal_convention or ".")
    if t == FieldType.BOOLEAN:
        return nv.parse_boolean(raw)
    if t == FieldType.CURRENCY_CODE:
        return nv.parse_currency_code(raw)
    if t in (FieldType.DATE, FieldType.DATETIME):
        order = ctx.date_order or default_order
        if ctx.date_problem == "inconsistent":
            m = _NUMERIC_DATE.match(raw.strip().split(" ")[0])
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if a > 12:
                    order = "dmy"
                elif b > 12:
                    order = "mdy"
                elif a != b:
                    return nv.Parsed(False, error="day/month order cannot be determined "
                                                   "(column mixes DD/MM and MM/DD)")
        fn = nv.parse_date if t == FieldType.DATE else nv.parse_datetime
        return fn(raw, order)
    raise ValueError(f"unsupported field type {t}")


def normalise_table(table: CsvTable, mapping: MappingResult, schema: SchemaDefinition,
                    default_date_order: str = "dmy") -> NormalisedTable:
    nulls = schema.null_tokens
    columns: dict[str, ColumnContext] = {}
    for m in mapping.mappings:
        fdef = schema.field(m.canonical_field)
        ctx = ColumnContext(field=fdef.name, source_column=m.source_column,
                            index=m.source_index, type=fdef.type)
        vals = [v for v in table.column_values(m.source_index) if not nv.is_null(v, nulls)]
        if fdef.type in (FieldType.DATE, FieldType.DATETIME):
            order, problem = nv.detect_date_order([v.strip().split(" ")[0] for v in vals])
            ctx.date_order = order if problem != "ambiguous" else default_date_order
            ctx.date_problem = problem
        elif fdef.type == FieldType.DECIMAL:
            ctx.decimal_convention, ctx.decimal_problem = nv.detect_decimal_convention(vals)
        columns[fdef.name] = ctx

    mapped_idx = {m.source_index for m in mapping.mappings}
    keys = column_keys(table.headers)          # unique per position: duplicate names never overwrite a cell
    out = NormalisedTable(columns=columns, cells=[])
    for row in table.rows:
        cells: dict[str, Cell] = {}
        values = {}
        for fname, ctx in columns.items():
            raw = row.cells[ctx.index] if ctx.index < len(row.cells) else None
            if raw is None or nv.is_null(raw, nulls):
                cells[fname] = Cell(raw, True, None)
                values[fname] = None
                continue
            p = _parse(raw, ctx, default_date_order)
            cells[fname] = Cell(raw, False, p)
            values[fname] = p.value if p.ok else None
        original = {keys[i]: c for i, c in enumerate(row.cells) if i < len(keys)}
        unmapped = {keys[i]: c for i, c in enumerate(row.cells) if i < len(keys) and i not in mapped_idx}
        for j, extra in enumerate(row.cells[len(table.headers):], 1):
            original[f"__extra_value_{j}"] = extra
            unmapped[f"__extra_value_{j}"] = extra
        out.cells.append(cells)
        out.records.append(Record(row_number=row.row_number, source_line=row.source_line,
                                  values=values, original=original, unmapped=unmapped))
    return out


def raw_records(table: CsvTable) -> list[Record]:
    """Records with originals only - used when no schema/mapping is available."""
    recs = []
    keys = column_keys(table.headers)
    for row in table.rows:
        original = {keys[i]: c for i, c in enumerate(row.cells) if i < len(keys)}
        for j, extra in enumerate(row.cells[len(table.headers):], 1):
            original[f"__extra_value_{j}"] = extra
        recs.append(Record(row_number=row.row_number, source_line=row.source_line,
                           original=original, unmapped=dict(original)))
    return recs
