"""Structural validation of evidence rows, applied before any financial calculation.

One place for the rules, shared by the validator (uc042lib.validate) and case preparation (uc042lib.prepare).

Accepted formats (documented rules, nothing is guessed or converted):
  amount   unsigned decimal with exactly 2 dp, '.' as decimal separator: 1000.00
           Rejected: thousands separators (1,000.00), decimal commas (1000,00), signs, currency symbols,
           spaces, scientific notation. A thousands comma is ambiguous with European decimal commas,
           so exports must be normalised before upload.
  signed   as amount, optionally with a leading '-'
  date     ISO 8601 calendar date: 2026-09-15
  ts       ISO 8601 date-time with an explicit UTC offset: 2026-09-15T17:00:00+01:00
  bool     true / false
  int      digits only
  ccy      GBP or EUR (the currencies this POC supports)
  id       letters, digits and . _ : - ; starts with a letter or digit; at most 64 characters
  enum     one of the values listed in schema.ENUMS
"""
import csv
import re
from datetime import date, datetime

from . import schema
from .money import MoneyFormatError, parse_signed, parse_unsigned

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
INT_RE = re.compile(r"^\d+$")
CURRENCIES = {"GBP", "EUR"}
DATE_FIELDS = ("statement_date", "booking_date", "recon_date", "settlement_date", "calendar_date", "receipt_date",
               "cycle_date", "value_date")
TS_FIELDS = ("posted_ts", "executed_ts", "as_at_ts", "booking_ts", "receipt_ts", "logged_ts", "reconciliation_point_ts")
REF_FIELDS = ("bank_reference", "end_to_end_ref", "payment_reference", "expected_bank_reference", "recon_ref")


def parse_ts(text):
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp without offset")
    return dt


def field_error(ftype, value, allowed=None):
    """Return an error message if a non-empty value is invalid for its type, else None."""
    try:
        if allowed is not None and value not in allowed:
            return f"not one of {sorted(allowed)}"
        if ftype == "amount":
            parse_unsigned(value)
        elif ftype == "signed":
            parse_signed(value)
        elif ftype == "date":
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                raise ValueError
            date.fromisoformat(value)
        elif ftype == "ts":
            parse_ts(value)
        elif ftype == "bool" and value not in ("true", "false"):
            return "not true/false"
        elif ftype == "int" and not INT_RE.match(value):
            return "not a whole number"
        elif ftype == "ccy" and value not in CURRENCIES:
            return "unsupported currency"
        elif ftype == "id" and not ID_RE.match(value):
            return "invalid identifier"
    except (ValueError, MoneyFormatError):
        return {"amount": "invalid amount (2 dp, '.' decimal, no separators)", "signed": "invalid signed amount",
                "date": "invalid date (YYYY-MM-DD)", "ts": "invalid timestamp (ISO 8601 with offset)"}.get(ftype, f"invalid {ftype}")
    return None


def read_csv(path):
    """Read a CSV as text (UTF-8, optional BOM). Returns (header, rows with _line). Raises UnicodeDecodeError/csv.Error."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = []
        for i, r in enumerate(reader, start=2):
            r["_line"] = i
            rows.append(r)
    return header, rows


def check_rows(fid, rows):
    """Split rows into (valid_rows, findings). A finding: {line, field, raw, error}.

    A row with any finding is excluded from all calculations; its raw values are kept in the finding.
    Later duplicates of a primary key are excluded (the first occurrence is kept, DQ09)."""
    cols = schema.CSV_FILES[fid][2]
    types = {c[0]: c[1] for c in cols}
    mandatory = [c[0] for c in cols if c[2] == "M"]
    pk = cols[0][0]
    valid, findings, seen = [], [], {}
    for r in rows:
        errs = []
        if None in r or any(r.get(c) is None for c in types):
            errs.append(("(row)", "", "wrong number of fields"))
        else:
            for c in mandatory:
                if r[c] == "":
                    errs.append((c, "", "required value missing"))
            for c, t in types.items():
                v = r[c]
                if v == "":
                    continue
                e = field_error(t, v, schema.ENUMS.get((fid, c)))
                if e:
                    errs.append((c, v, e))
            for f, c, cond, desc in schema.CONDITIONAL:
                if f == fid and r[c] == "" and cond(r):
                    errs.append((c, "", f"required value missing ({desc})"))
            if not errs and r[pk] in seen:
                errs.append((pk, r[pk], f"duplicate key (first at line {seen[r[pk]]})"))
        if errs:
            for c, v, e in errs:
                findings.append({"line": r["_line"], "field": c, "raw": v, "error": e, "row": r})
        else:
            seen[r[pk]] = r["_line"]
            valid.append(r)
    return valid, findings


def taint_scope(row):
    """What an excluded row could have affected, from whichever of its fields are themselves valid.
    A key set to None means 'unknown', which callers treat as matching everything (conservative)."""
    def ok(field, ftype):
        v = row.get(field)
        if not isinstance(v, str):
            return None          # field absent or row malformed: unknown
        if v == "":
            return ""            # known to be empty: matches nothing
        return v if field_error(ftype, v) is None else None
    d = None
    for f in DATE_FIELDS:
        if ok(f, "date"):
            d = date.fromisoformat(row[f])
            break
    if d is None:
        for f in TS_FIELDS:
            if ok(f, "ts"):
                d = parse_ts(row[f]).date()
                break
    malformed = None in row or any(v is None for v in row.values())
    refs = None if malformed else {row[f] for f in REF_FIELDS if isinstance(row.get(f), str) and row.get(f)}
    return {"account": ok("account_id", "id"), "currency": ok("currency", "ccy"), "date": d,
            "batch": ok("batch_id", "id") or ok("settlement_batch_id", "id"), "client": ok("client_id", "id"),
            "pk": None if malformed else next(iter(row.values())), "refs": refs}


# --- Reporting period (U2) -------------------------------------------------------------------------
def _local_date(ftype, value):
    from zoneinfo import ZoneInfo
    if ftype == "ts":
        return parse_ts(value).astimezone(ZoneInfo(schema.TZ)).date()
    return date.fromisoformat(value)


def _is_permitted(row, rule):
    for permitted in rule.get("permitted", []):
        ok = True
        for field, expected in permitted.items():
            if field.endswith("_ts"):
                ok = ok and row.get(field, "") != "" and parse_ts(row[field]) == parse_ts(expected)
            else:
                ok = ok and row.get(field) == expected
        if ok:
            return True
    return False


def check_period(fid, rows, refs=None, period=None):
    """Apply the reporting-period rules of `period` (uc042lib.period.PeriodConfig) to structurally valid rows.
    Without `period`, the baseline period described by uc042lib.schema is used (callers that process a case always
    pass the case's period: see uc042lib.validate.Validator).

    Returns (kept_rows, findings, counts). A finding: {line, field, raw, error, row}.
    counts = {"applicable": rows inside the period, "permitted": permitted boundary rows, "outside": excluded rows,
              "subsequent": kept rows recorded after the period end}.
    refs: {record id: business date} for rules that follow another record's date (event_ref).
    Kept rows recorded after the period end carry row["_subsequent"] = True.
    Files without a rule are returned unchanged."""
    from .period import BASELINE
    period = period or BASELINE
    rule = period.period_rules.get(fid)
    counts = {"applicable": 0, "permitted": 0, "outside": 0, "subsequent": 0}
    if rule is None:
        counts["applicable"] = len(rows)
        return rows, [], counts
    types = {c[0]: c[1] for c in schema.CSV_FILES[fid][2]}
    start, end = period.start, period.end
    kept, findings = [], []
    for r in rows:
        if _is_permitted(r, rule):
            counts["permitted"] += 1
            kept.append(r)
            continue
        errs = []
        for field, expected in rule.get("equals", {}).items():
            if r[field] != expected:
                errs.append((field, r[field], f"not the case period {expected}"))
        for field in rule.get("in_period", []):
            if r[field] == "":
                continue
            d = _local_date(types[field], r[field])
            if not start <= d <= end:
                errs.append((field, r[field], f"{d} is outside the reporting period {start} to {end}"))
        odp = rule.get("open_during_period")
        if odp:  # relevant if open at some point in the period: received by the end, not allocated before the start
            for field in odp["start"]:
                if r[field] != "" and _local_date(types[field], r[field]) > end:
                    errs.append((field, r[field], f"received after the period end {end}; not open at any point in the period"))
            for field in odp["end"]:
                if r[field] != "" and _local_date(types[field], r[field]) < start:
                    errs.append((field, r[field], f"allocated before the period start {start}; not open at any point in the period"))
        ev = rule.get("event_ref")
        event_date = None
        if ev:
            ref = r[ev["field"]]
            event_date = (refs or {}).get(ref)
            if event_date is None:
                errs.append((ev["field"], ref, "does not refer to a reconciliation record in this case's evidence, so the "
                             "entry's period cannot be established"))
            elif not start <= event_date <= end:
                errs.append((ev["field"], ref, f"refers to a reconciliation dated {event_date}, outside the reporting period"))
            else:
                for field in rule.get("not_before_event", []):
                    if r[field] != "" and _local_date(types[field], r[field]) < event_date:
                        errs.append((field, r[field], f"logged before the reconciliation it refers to ({event_date})"))
        if errs:
            counts["outside"] += 1
            for field, raw, err in errs:
                findings.append({"line": r["_line"], "field": field, "raw": raw, "error": err, "row": r})
        else:
            counts["applicable"] += 1
            if any(r[f] != "" and _local_date(types[f], r[f]) > end for f in rule.get("subsequent_after_end", [])):
                r["_subsequent"] = True
                counts["subsequent"] += 1
            kept.append(r)
    return kept, findings, counts


# --- Header diagnosis (U3) -------------------------------------------------------------------------
def diagnose_header(received):
    """Explain why a CSV header does not match. Never used to accept a file: matching stays exact.

    Returns {"status": "MATCH" | "LIKELY" | "AMBIGUOUS" | "UNKNOWN", "file_id", "candidates", "expected",
             "received", "missing", "extra", "misordered", "case_or_spacing", "message"}."""
    received = list(received or [])
    norm = lambda c: (c or "").strip().lower()
    scores = []
    for fid in schema.CSV_FILES:
        expected = schema.columns(fid)
        if received == expected:
            return {"status": "MATCH", "file_id": fid, "candidates": [fid], "expected": expected, "received": received,
                    "missing": [], "extra": [], "misordered": [], "case_or_spacing": [], "message": "header matches"}
        a, b = {norm(c) for c in expected}, {norm(c) for c in received}
        scores.append((len(a & b) / len(a | b) if a | b else 0.0, fid))
    scores.sort(reverse=True)
    best, best_fid = scores[0]
    near = [f for s, f in scores if s >= 0.5 and best - s < 0.1]
    base = {"expected": [], "received": received, "missing": [], "extra": [], "misordered": [], "case_or_spacing": []}
    if best < 0.5:
        return dict(base, status="UNKNOWN", file_id="", candidates=[],
                    message="This CSV does not resemble any supported evidence type. Check that the right file was "
                            "exported and that it uses the documented column names.")
    if len(near) > 1:
        return dict(base, status="AMBIGUOUS", file_id="", candidates=near,
                    message=f"This header is equally close to {' and '.join(near)}, so the evidence type cannot be "
                            "determined. Export the file again with the exact header of the intended type.")
    expected = schema.columns(best_fid)
    exp_norm = {norm(c): c for c in expected}
    rec_norm = {norm(c): c for c in received}
    case_or_spacing = [(rec_norm[k], exp_norm[k]) for k in exp_norm if k in rec_norm and rec_norm[k] != exp_norm[k]]
    missing = [c for c in expected if norm(c) not in rec_norm]
    extra = [c for c in received if norm(c) not in exp_norm]
    common_exp = [norm(c) for c in expected if norm(c) in rec_norm]
    common_rec = [norm(c) for c in received if norm(c) in exp_norm]
    misordered = [exp_norm[k] for i, k in enumerate(common_exp) if i >= len(common_rec) or common_rec[i] != k]
    steps = []
    if case_or_spacing:
        steps.append("rename " + ", ".join(f"'{r}' to '{e}'" for r, e in case_or_spacing))
    if missing:
        steps.append("add the missing column(s) " + ", ".join(missing))
    if extra:
        steps.append("remove the extra column(s) " + ", ".join(extra))
    if misordered and not missing and not extra:
        steps.append("put the columns in the expected order")
    elif misordered:
        steps.append("then put the columns in the expected order")
    name = schema.CSV_FILES[best_fid][1]
    return dict(base, status="LIKELY", file_id=best_fid, candidates=[best_fid], expected=expected,
                missing=missing, extra=extra, misordered=misordered,
                case_or_spacing=[f"{r} -> {e}" for r, e in case_or_spacing],
                message=f"This looks like {best_fid} ({name}) but the header is not exact. To fix it: "
                        + "; ".join(steps) + ". Headers must match exactly, including case and column order.")
