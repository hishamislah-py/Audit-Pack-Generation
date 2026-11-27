"""Data-row conformity of a CSV identified by its exact header, against the registry's field rules.

Informational only: UC-042 identifies a CSV by its header, and row-level type/enum errors surface later as data-quality
findings, so a nonconforming row never changes the category. The rules applied are the ones the registry carries
(generated from UC-042): mandatory values, pattern, allowed values, and the date/timestamp parse rules of
uc042lib.structure.field_error / parse_ts.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from ..schemas.model import SchemaDefinition

MAX_EXAMPLES = 5


def _value_error(source_type: str | None, pattern: str | None, allowed: list[str] | None, value: str) -> str | None:
    if allowed is not None and value not in allowed:
        return f"not one of {allowed}"
    if pattern is not None and not re.match(pattern, value):
        return f"does not match {pattern}"
    try:
        if source_type == "date":
            date.fromisoformat(value)
        elif source_type == "ts":
            if datetime.fromisoformat(value).tzinfo is None:
                return "timestamp without UTC offset"
    except ValueError:
        return f"invalid {source_type}"
    return None


def check_rows(schema: SchemaDefinition, header: list[str], rows: list[list[str]]) -> dict:
    """rows: data rows as lists of cells in file order. Returns a summary (no exceptions raised)."""
    fields = {f.name: f for f in schema.fields}
    width = len(header)
    by_field: dict[str, int] = {}
    examples: list[dict] = []
    bad_rows = 0
    for i, cells in enumerate(rows, start=1):
        errs = []
        if len(cells) != width:
            errs.append(("(row)", "", f"{len(cells)} fields, header has {width}"))
        else:
            row = dict(zip(header, cells))
            for name, f in fields.items():
                v = row.get(name, "")
                if v == "":
                    if f.requiredness == "M":
                        errs.append((name, v, "mandatory value missing"))
                    continue
                e = _value_error(f.source_type, f.constraints.pattern, f.constraints.allowed_values, v)
                if e:
                    errs.append((name, v, e))
        if errs:
            bad_rows += 1
            for name, v, e in errs:
                by_field[name] = by_field.get(name, 0) + 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append({"row": i, "field": name, "value": v, "error": e})
    return {"rows_checked": len(rows), "nonconforming_rows": bad_rows, "by_field": by_field, "examples": examples,
            "empty_allowed": bool(schema.csv and schema.csv.empty_allowed),
            "note": "informational: UC-042 identifies CSVs by header; row errors are data-quality findings"}
