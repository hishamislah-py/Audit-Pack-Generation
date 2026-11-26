"""Fix8 D4 - financial fields in mapping review: classification, clarification requirement and value / relationship checks.

Classification (from the registry, nothing hard-coded per header):
  * MONEY      source_type `amount` (unsigned) or `signed`;
  * PERSPECTIVE an enum whose allowed values are a debit/credit or direction pair (the same rule as
               mapping.proposals.is_sign_sensitive);
  * a money field is INTERCHANGEABLE when its category has more than one money field (e.g. IN-12 gross / fees /
    adjustments / net), i.e. a wrong choice still passes every per-value rule.

Clarification: an AI-proposed mapping onto a financial field that is AMBIGUOUS (by the deterministic validator) or onto an
interchangeable money field is never accepted with a one-click MAP: the analyst must name the field explicitly (CLARIFY,
audited ANALYST_MAPPING_CLARIFIED). Deterministic, unambiguous mappings are unchanged.

Relationships (only where the registry + engine semantics define one):
  IN-12 settlement batches: gross_amount - total_fees - total_adjustments = net_amount_reported, per row (unsigned
  amounts). Engine basis: uc042lib.validate C11-BATCH-ARITH (TXN lines = gross, FEE lines = fees, REFUND lines =
  adjustments, signed lines = signed net) and uc042lib.generate (net = gross - fees - adjustments for both directions).

A mapping is FINANCIALLY CONTRADICTORY (refused) when its relationship fails on rows AND either (a) it fails on more than
half of the rows checked, or (b) another assignment of the SAME source columns to the relationship's fields fails on
fewer rows (the mapping is explained better by a swap). Isolated failures that no re-assignment explains are reported as
a warning and left to reconciliation (they may be genuine data exceptions, which the engine must see).
"""
from __future__ import annotations

import itertools
from decimal import Decimal, InvalidOperation

from .proposals import is_sign_sensitive

MONEY_TYPES = ("amount", "signed")
RELATIONSHIPS = {
    "IN-12": [{"id": "IN-12/NET", "fields": ("gross_amount", "total_fees", "total_adjustments", "net_amount_reported"),
               "text": "gross_amount - total_fees - total_adjustments = net_amount_reported",
               "basis": "uc042lib C11-BATCH-ARITH semantics (lines: TXN = gross, FEE = fees, REFUND = adjustments, "
                        "signed lines = signed net)"}],
}
MAX_EXAMPLES = 3


def money_fields(schema) -> list[str]:
    return [f.name for f in schema.fields if f.source_type in MONEY_TYPES]


def is_financial(schema, field: str | None) -> bool:
    return bool(field) and is_sign_sensitive(schema, field)


def interchangeable(schema, field: str | None) -> bool:
    f = schema.field(field) if field else None
    return f is not None and f.source_type in MONEY_TYPES and len(money_fields(schema)) > 1


def clarification(schema, row: dict) -> str | None:
    """Why this review row needs an explicit field choice, or None. `row`: suggested_field, suggestion_basis,
    validation (validator class) - the analyst application's review row."""
    fld = row.get("suggested_field")
    if row.get("suggestion_basis") != "proposal" or not is_financial(schema, fld):
        return None
    reasons = []
    if (row.get("validation") or "") == "AMBIGUOUS" or (row.get("proposal_assessment") or "") == "AMBIGUOUS":
        reasons.append("the proposal is AMBIGUOUS")
    if interchangeable(schema, fld):
        others = [m for m in money_fields(schema) if m != fld]
        reasons.append(f"{fld} is interchangeable with {', '.join(others)} (every value rule passes either way)")
    elif schema.field(fld).source_type not in MONEY_TYPES:
        reasons.append(f"{fld} carries debit/credit or direction perspective")
    if not reasons:
        reasons.append(f"{fld} is a money field")
    return ("financial mapping needs an explicit choice: " + "; ".join(reasons) +
            " - choose the field explicitly (Clarify) or ignore the column")


def _num(v):
    try:
        return Decimal(str(v).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _evaluate(rel: dict, cols: dict[str, int], values: dict[int, list[str]]) -> dict:
    a, b, c, d = (cols[f] for f in rel["fields"])
    n = min(len(values.get(i, [])) for i in (a, b, c, d))
    checked, failed, unparsable, examples = 0, 0, 0, []
    for r in range(n):
        x = [_num(values[i][r]) for i in (a, b, c, d)]
        if any(v is None for v in x):
            unparsable += 1
            continue
        checked += 1
        if x[0] - x[1] - x[2] != x[3]:
            failed += 1
            if len(examples) < MAX_EXAMPLES:
                examples.append({"row": r + 1, "values": [str(v) for v in x], "difference": str(x[0] - x[1] - x[2] - x[3])})
    return {"rows_checked": checked, "rows_failed": failed, "rows_unparsable": unparsable, "examples": examples}


def check_relationships(category: str, headers: list[str], mapping: dict[int, str],
                        values: dict[int, list[str]]) -> list[dict]:
    """Every relationship of the category under `mapping` (position -> field). NOT_EVALUATED until all its fields are
    mapped. Values are the full source columns (local only; never sent anywhere)."""
    out = []
    by_field = {f: i for i, f in mapping.items()}
    for rel in RELATIONSHIPS.get(category, []):
        res = {"relationship": rel["id"], "text": rel["text"], "basis": rel["basis"]}
        missing = [f for f in rel["fields"] if f not in by_field]
        if missing:
            out.append({**res, "status": "NOT_EVALUATED", "detail": f"not yet mapped: {', '.join(missing)}"})
            continue
        cols = {f: by_field[f] for f in rel["fields"]}
        ev = _evaluate(rel, cols, values)
        res.update(ev, columns={f: f"#{i + 1} {headers[i]!r}" for f, i in cols.items()})
        if ev["rows_checked"] == 0:
            out.append({**res, "status": "NOT_EVALUATED", "detail": "no row with four numeric values"})
            continue
        best = None
        if ev["rows_failed"]:
            positions = [cols[f] for f in rel["fields"]]
            for perm in itertools.permutations(positions):
                if list(perm) == positions:
                    continue
                alt = _evaluate(rel, dict(zip(rel["fields"], perm)), values)
                moved = sum(1 for a, b in zip(perm, positions) if a != b)
                # fewest failures first, then the smallest re-assignment (a swap explains more than a rotation)
                if alt["rows_failed"] < ev["rows_failed"] and (best is None or (alt["rows_failed"], moved) <
                                                               (best[1]["rows_failed"], best[2])):
                    best = (perm, alt, moved)
        if not ev["rows_failed"]:
            out.append({**res, "status": "PASS", "detail": f"holds on all {ev['rows_checked']} row(s)"})
            continue
        majority = ev["rows_failed"] * 2 > ev["rows_checked"]
        if best is not None or majority:
            hint = ""
            if best is not None:
                swap = [f"{headers[p]!r} -> {f}" for f, p in zip(rel["fields"], best[0]) if cols[f] != p]
                hint = (f"; the same columns assigned as {', '.join(swap)} fail on {best[1]['rows_failed']} row(s) "
                        "instead")
            out.append({**res, "status": "FAIL", "contradictory": True,
                        "detail": f"{rel['text']} fails on {ev['rows_failed']} of {ev['rows_checked']} row(s){hint}",
                        "better_assignment": None if best is None else
                        {f: f"#{p + 1} {headers[p]!r}" for f, p in zip(rel["fields"], best[0])}})
        else:
            out.append({**res, "status": "WARN", "contradictory": False,
                        "detail": f"{rel['text']} fails on {ev['rows_failed']} of {ev['rows_checked']} row(s); no other "
                                  "assignment of these columns explains the data better - left to reconciliation"})
    return out


def contradictions(results: list[dict]) -> list[dict]:
    return [r for r in results if r.get("status") == "FAIL" and r.get("contradictory")]


def read_columns(data: bytes, filename: str) -> tuple[list[str], dict[int, list[str]]]:
    """(raw headers, position -> every cell value) of a stored CSV original, with the existing identification + reader."""
    from ..csv_engine.reader import read_csv
    from ..identify.detect import identify
    ident = identify(data, filename)
    t = read_csv(data, ident.encoding, ident.delimiter)
    return list(t.raw_headers), {i: [(r.cells[i] if i < len(r.cells) else "") for r in t.rows]
                                 for i in range(len(t.raw_headers))}
