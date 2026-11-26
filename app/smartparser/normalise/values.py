"""Module H - value normalisation.

Rules:
* Financial amounts are parsed into ``Decimal`` - never ``float`` - and are never
  rounded. Scientific notation is rejected.
* Ambiguities (day/month order, decimal-comma vs thousands-comma) are resolved
  per *column* from unambiguous evidence in that column. When the column gives
  no evidence, the configured default is applied and a warning is reported -
  the assumption is never silent.
* Every parse returns a ``Parsed`` object with notes, so callers can keep the
  original value alongside the normalised one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from .currencies import ISO_4217


@dataclass
class Parsed:
    ok: bool
    value: Any = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- strings / nulls

def is_null(raw: str, null_tokens: list[str]) -> bool:
    return raw.strip() in null_tokens


def parse_string(raw: str) -> Parsed:
    v = raw.strip()
    return Parsed(True, v, notes=["whitespace_trimmed"] if v != raw else [])


# --------------------------------------------------------------------------- decimals

_CURRENCY_SYMBOLS = "£€$¥"
_CCY_AFFIX = re.compile(r"^(?P<pre>[A-Z]{3})\s*(?P<body>.*)$|^(?P<body2>.*?)\s*(?P<post>[A-Z]{3})$")
_DOT_STYLE = re.compile(r"^(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_COMMA_STYLE = re.compile(r"^(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
# Values only valid under one convention (used for column-level evidence)
_ONLY_DOT = re.compile(r"^(\d{1,3}(,\d{3})+\.\d+|\d+\.\d{1,2}|\d+\.\d{4,}|\d{4,}\.\d+)$")
_ONLY_COMMA = re.compile(r"^(\d{1,3}(\.\d{3})+,\d+|\d+,\d{1,2}|\d+,\d{4,}|\d{4,},\d+)$")
_AMBIG_GROUP = re.compile(r"^\d{1,3}[.,]\d{3}$")  # 1,234 / 1.234


def _strip_decimal_decorations(raw: str) -> tuple[str, bool, list[str]] | str:
    """Return (body, negative, notes) or an error string."""
    s = raw.strip().replace(" ", " ").replace(" ", " ")
    notes: list[str] = []
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
        notes.append("accounting_parentheses_negative")
    m = _CCY_AFFIX.match(s)
    if m and (m.group("pre") or m.group("post")):
        code = m.group("pre") or m.group("post")
        s = (m.group("body") if m.group("pre") else m.group("body2")).strip()
        notes.append(f"currency_code_stripped:{code}")
    if s and s[0] in "+-":
        if s[0] == "-":
            if negative:
                return "double negative sign"
            negative = True
        s = s[1:].strip()
    elif s.endswith("-"):
        negative, s = True, s[:-1].strip()
        notes.append("trailing_minus_negative")
    if s and s[0] in _CURRENCY_SYMBOLS:
        notes.append(f"currency_symbol_stripped:{s[0]}")
        s = s[1:].strip()
        if s[:1] == "-" and not negative:
            negative, s = True, s[1:].strip()
    if re.search(r"\d \d", s):
        if not re.fullmatch(r"\d{1,3}( \d{3})+([.,]\d+)?", s):
            return "irregular digit spacing"
        s = s.replace(" ", "")
        notes.append("space_grouping_removed")
    return s, negative, notes


def detect_decimal_convention(values: list[str]) -> tuple[str, str | None]:
    """Return (convention, problem) where convention is '.' or ','.

    problem is 'ambiguous' (no evidence and grouping-style values present) or
    'inconsistent' (evidence for both conventions) or None.
    """
    dot = comma = ambiguous = 0
    for raw in values:
        r = _strip_decimal_decorations(raw)
        if isinstance(r, str):
            continue
        body = r[0]
        if _ONLY_DOT.match(body):
            dot += 1
        elif _ONLY_COMMA.match(body):
            comma += 1
        elif _AMBIG_GROUP.match(body):
            ambiguous += 1
    if dot and comma:
        return ".", "inconsistent"
    if comma:
        return ",", None
    if not dot and ambiguous:
        return ".", "ambiguous"
    return ".", None


def parse_decimal(raw: str, convention: str = ".") -> Parsed:
    r = _strip_decimal_decorations(raw)
    if isinstance(r, str):
        return Parsed(False, error=r)
    body, negative, notes = r
    if not body:
        return Parsed(False, error="no digits")
    if re.search(r"[eE]", body):
        return Parsed(False, error="scientific notation is not accepted for financial values")
    if convention == ".":
        if not _DOT_STYLE.match(body):
            return Parsed(False, error="not a valid decimal number")
        canonical = body.replace(",", "")
    else:
        if not _COMMA_STYLE.match(body):
            return Parsed(False, error="not a valid decimal number (decimal-comma convention)")
        canonical = body.replace(".", "").replace(",", ".")
        notes.append("decimal_comma_converted")
    if canonical != body and convention == ".":
        notes.append("thousands_separator_removed")
    try:
        value = Decimal(canonical)
    except InvalidOperation:
        return Parsed(False, error="not a valid decimal number")
    return Parsed(True, -value if negative else value, notes=notes)


def parse_integer(raw: str) -> Parsed:
    p = parse_decimal(raw, ".")
    if not p.ok:
        return p
    if p.value != p.value.to_integral_value() or "." in raw:
        return Parsed(False, error="not an integer")
    return Parsed(True, int(p.value), notes=p.notes)


# --------------------------------------------------------------------------- dates

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_YMD = re.compile(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_NUMERIC = re.compile(r"^(\d{1,2})([/.-])(\d{1,2})\2(\d{4}|\d{2})$")
_DAY_MON = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+([A-Za-z]{3,9})\.?[\s\-/,]+(\d{4}|\d{2})$")
_MON_DAY = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")


def _month(name: str) -> int | None:
    n = name.lower()
    if n == "sept":
        n = "sep"
    m = _MONTHS.get(n[:3])
    # Accept 3-letter abbreviations or full names only
    full = ["january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december"]
    if m and (len(n) == 3 or n == "sept" or n == full[m - 1]):
        return m
    return None


def _year(y: str, notes: list[str]) -> int:
    if len(y) == 2:
        notes.append("two_digit_year_assumed_20xx")
        return 2000 + int(y)
    return int(y)


def detect_date_order(values: list[str]) -> tuple[str, str | None]:
    """For numeric a/b/yyyy dates: return ('dmy'|'mdy', problem).

    problem: 'ambiguous' when no value disambiguates, 'inconsistent' when the
    column contains evidence for both orders, else None.
    """
    dmy = mdy = numeric = 0
    for raw in values:
        m = _NUMERIC.match(raw.strip())
        if not m:
            continue
        numeric += 1
        a, b = int(m.group(1)), int(m.group(3))
        if a > 12 >= b:
            dmy += 1
        elif b > 12 >= a:
            mdy += 1
    if dmy and mdy:
        return "dmy", "inconsistent"
    if mdy:
        return "mdy", None
    if dmy:
        return "dmy", None
    return "dmy", ("ambiguous" if numeric else None)


def parse_date(raw: str, order: str = "dmy") -> Parsed:
    s = raw.strip()
    notes: list[str] = []
    try:
        if m := _ISO.match(s) or _YMD.match(s) or _COMPACT.match(s):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif m := _NUMERIC.match(s):
            a, b = int(m.group(1)), int(m.group(3))
            d, mo = (a, b) if order == "dmy" else (b, a)
            y = _year(m.group(4), notes)
            if a <= 12 and b <= 12 and a != b:
                notes.append(f"date_order_{order}_applied")
        elif m := _DAY_MON.match(s):
            mo = _month(m.group(2))
            if mo is None:
                return Parsed(False, error="unrecognised month name")
            d, y = int(m.group(1)), _year(m.group(3), notes)
        elif m := _MON_DAY.match(s):
            mo = _month(m.group(1))
            if mo is None:
                return Parsed(False, error="unrecognised month name")
            d, y = int(m.group(2)), int(m.group(3))
        else:
            return Parsed(False, error="unrecognised date format")
        return Parsed(True, date(y, mo, d), notes=notes)
    except ValueError as exc:
        return Parsed(False, error=f"impossible date: {exc}")


_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?$")


def parse_datetime(raw: str, order: str = "dmy") -> Parsed:
    s = raw.strip()
    try:
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", iso):
            return Parsed(True, datetime.fromisoformat(iso))
    except ValueError:
        pass
    parts = s.rsplit(" ", 1)
    if len(parts) == 2 and (tm := _TIME.match(parts[1])):
        d = parse_date(parts[0], order)
        if not d.ok:
            return d
        try:
            t = time(int(tm.group(1)), int(tm.group(2)), int(tm.group(3) or 0),
                     int((tm.group(4) or "0").ljust(6, "0")))
        except ValueError as exc:
            return Parsed(False, error=f"impossible time: {exc}")
        return Parsed(True, datetime.combine(d.value, t), notes=d.notes)
    d = parse_date(s, order)
    if d.ok:
        return Parsed(False, error="date without time where datetime is required")
    return Parsed(False, error="unrecognised datetime format")


# --------------------------------------------------------------------------- other types

_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}


def parse_boolean(raw: str) -> Parsed:
    v = raw.strip().casefold()
    if v in _TRUE:
        return Parsed(True, True)
    if v in _FALSE:
        return Parsed(True, False)
    return Parsed(False, error="not a recognised boolean")


def parse_currency_code(raw: str) -> Parsed:
    v = raw.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", v):
        return Parsed(False, error="currency code must be 3 letters (ISO 4217)")
    notes = [] if v == raw else ["currency_code_case_or_space_normalised"]
    if v not in ISO_4217:
        notes.append("unknown_iso4217_code")
    return Parsed(True, v, notes=notes)
