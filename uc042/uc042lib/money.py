"""Decimal-safe money handling and sign normalisation for UC-042.

Rules (see docs/UC042_INPUT_EVIDENCE_SPEC_V1.md, section 6):
  amount_signed is positive when the balance it belongs to increases.

  Source                         Raw indicator    Rule
  Bank balances and entries      C / D (bank)     C -> +amount, D -> -amount
  Cash book (firm asset ledger)  D / C (ledger)   D -> +amount, C -> -amount
  Transactions                   CR / DR (client) CR -> +amount, DR -> -amount
  Settlement lines               C / D (account)  C -> +amount, D -> -amount
  Settlement batch net           TO_FIRM/FROM_FIRM +net / -net

Raw values are never modified; these functions only derive.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

UNSIGNED_RE = re.compile(r"^\d+\.\d{2}$")
SIGNED_RE = re.compile(r"^-?\d+\.\d{2}$")
CENT = Decimal("0.01")


class MoneyFormatError(ValueError):
    pass


def parse_unsigned(text):
    """Parse an unsigned 2-dp decimal string. Rejects signs, separators and floats."""
    if not isinstance(text, str) or not UNSIGNED_RE.match(text):
        raise MoneyFormatError(f"not an unsigned 2dp amount: {text!r}")
    return Decimal(text)


def parse_signed(text):
    if not isinstance(text, str) or not SIGNED_RE.match(text):
        raise MoneyFormatError(f"not a signed 2dp amount: {text!r}")
    return Decimal(text)


def fmt(value):
    """Format a Decimal as a 2dp string. The value must already be exact to the cent."""
    if value != value.quantize(CENT):
        raise MoneyFormatError(f"value has more than 2dp: {value}")
    return f"{value.quantize(CENT):f}"


def round_half_up(value):
    """Documented rounding for computed fees: half-up to the cent."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


_RULES = {
    "bank": {"C": 1, "D": -1},
    "cashbook": {"D": 1, "C": -1},
    "client": {"CR": 1, "DR": -1},
    "settlement": {"C": 1, "D": -1},
}


def signed(amount_text, indicator, perspective):
    """Derive a signed Decimal from a raw unsigned amount and its source indicator."""
    rules = _RULES[perspective]
    if indicator not in rules:
        raise MoneyFormatError(f"indicator {indicator!r} not valid for {perspective}")
    return parse_unsigned(amount_text) * rules[indicator]


def batch_net_signed(net_text, direction):
    if direction == "TO_FIRM":
        return parse_unsigned(net_text)
    if direction == "FROM_FIRM":
        return -parse_unsigned(net_text)
    raise MoneyFormatError(f"unknown direction {direction!r}")
