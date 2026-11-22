"""Experiment A - value rules for the five UC-042 PDF evidence categories.

The generated registry deliberately records no value type for PDF labels (``PdfLabel.value_type`` is None: the UC-042
schema defines none). The rules below are therefore NOT schema facts: each one restates a rule that a UC-042 consumer
applies to the parsed value, with the consumer cited, so an extracted value can be checked against what UC-042 will do
with it. Nothing here changes the registry.

Levels:
  PARSE      UC-042 treats the document as unusable when the rule fails (intake or Validator.setup).
  CROSS_DOC  UC-042 compares the value with another document (here: the account inventory, IN-02).
  CONTROL    a UC-042 control (C10 / C03 / C16) evaluates the value; failing it is a business result, not a parse error.
A detail starting 'FORMAT:' means the value is not in the form UC-042 can read at all (routed to
human review); any other CONTROL failure is a business result for UC-042 to report.
Rules UC-042 does not have are not invented: such labels are reported as NOT_EVALUATED with the reason.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

PARSE, CROSS_DOC, CONTROL = "PARSE", "CROSS_DOC", "CONTROL"


@dataclass(frozen=True)
class Context:
    """What a rule may compare with. Every member is optional; a rule that needs a missing one is NOT_EVALUATED."""
    period_id: str | None = None                    # PER-YYYY-MM
    inventory_row: dict | None = None               # the IN-02 row of the letter's slot account
    policy_version: dict | None = None              # the registered policy version (registry PolicyVersionInfo dump)
    policy_successor_effective: str | None = None   # effective date of the next registered version, if any

    @property
    def period_start(self) -> date | None:
        end = self.period_end
        return end.replace(day=1) if end else None

    @property
    def period_end(self) -> date | None:
        m = re.fullmatch(r"PER-(\d{4})-(\d{2})", self.period_id or "")
        if not m:
            return None
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, calendar.monthrange(y, mo)[1])

    @property
    def previous_token(self) -> str | None:
        m = re.fullmatch(r"PER-(\d{4})-(\d{2})", self.period_id or "")
        if not m:
            return None
        y, mo = int(m.group(1)), int(m.group(2))
        y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
        return f"{y:04d}-{mo:02d}"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    level: str
    source: str                                     # the UC-042 code that applies the rule
    description: str
    check: Callable[[str, Context], tuple[str, str]]  # -> (PASS | FAIL | NOT_EVALUATED, detail)


def _iso_date(v: str) -> date | None:
    """As uc042lib.validate._date_or_none: a YYYY-MM-DD date, else None."""
    try:
        return date.fromisoformat(v) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v or "") else None
    except ValueError:
        return None


def _iso_ts(v: str) -> datetime | None:
    """As uc042lib.structure.parse_ts: ISO 8601 with an explicit offset, else None."""
    try:
        dt = datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else None


def _equals_inventory(column: str):
    def check(v: str, c: Context):
        if c.inventory_row is None:
            return "NOT_EVALUATED", "no account inventory (IN-02) row supplied for the slot account"
        expected = c.inventory_row.get(column, "")
        return ("PASS", f"equals IN-02 {column}") if v == expected else \
            ("FAIL", f"IN-02 {column} is {expected!r}")
    return check


def _date_not_after_period_end(v: str, c: Context):
    d = _iso_date(v)
    if d is None:
        return "FAIL", "FORMAT: not a YYYY-MM-DD date: UC-042 cannot evaluate it (the date check is skipped there)"
    if c.period_end is None:
        return "NOT_EVALUATED", "no reporting period supplied"
    return ("PASS", f"{d} is on or before {c.period_end}") if d <= c.period_end else \
        ("FAIL", f"{d} is after the period end {c.period_end}")


def _equals(expected: str):
    return lambda v, c: ("PASS", f"equals {expected!r}") if v == expected else ("FAIL", f"expected {expected!r}")


def _policy_field(key: str):
    def check(v: str, c: Context):
        if c.policy_version is None:
            return "FAIL", "not a registered policy version"
        expected = c.policy_version[key]
        return ("PASS", f"equals the registered {key} {expected!r}") if v == expected else \
            ("FAIL", f"registered {key} is {expected!r}")
    return check


def _policy_applies(v: str, c: Context):
    if c.policy_version is None:
        return "FAIL", "not a registered version"
    if c.period_end is None:
        return "NOT_EVALUATED", "no reporting period supplied"
    eff = date.fromisoformat(c.policy_version["effective"])
    if eff > c.period_end:
        return "FAIL", f"v{v} takes effect on {eff}, after the period"
    if c.policy_successor_effective and date.fromisoformat(c.policy_successor_effective) <= c.period_start:
        return "FAIL", f"v{v} is superseded from {c.policy_successor_effective}, before the period"
    return "PASS", f"v{v} (effective {eff}) applies to the period"


LETTER_RULES = {
    "Letter reference": [Rule("LETTER-REF", CROSS_DOC, "uc042lib.prepare.prepare_case (slot) + validate.check_designation",
                              "equals IN-02 acknowledgement_letter_ref of the slot account",
                              _equals_inventory("acknowledgement_letter_ref"))],
    "Account number": [Rule("LETTER-ACCOUNT-NUMBER", CROSS_DOC, "uc042lib.validate.check_designation",
                            "equals IN-02 account_number_masked", _equals_inventory("account_number_masked"))],
    "Currency": [Rule("LETTER-CURRENCY", CROSS_DOC, "uc042lib.validate.check_designation", "equals IN-02 currency",
                      _equals_inventory("currency"))],
    "Account name": [
        Rule("LETTER-ACCOUNT-NAME", CROSS_DOC, "uc042lib.validate.check_designation", "equals IN-02 designation_name",
             _equals_inventory("designation_name")),
        Rule("LETTER-SAFEGUARDING-WORDING", CONTROL, "uc042lib.validate.check_designation (C10)",
             "the designation contains 'Safeguarding'",
             lambda v, c: ("PASS", "contains 'Safeguarding'") if "Safeguarding" in v else ("FAIL", "lacks 'Safeguarding'")),
    ],
    "Letter date": [Rule("LETTER-DATE", CONTROL, "uc042lib.validate.check_designation (C10)",
                         "YYYY-MM-DD and not after the period end", _date_not_after_period_end)],
}

RULES: dict[str, dict[str, list[Rule]]] = {
    "IN-15": LETTER_RULES,
    "IN-16": LETTER_RULES,
    "IN-17": {
        "Document version": [
            Rule("POLICY-VERSION", PARSE, "uc042lib.policy.recognise", "a registered policy version",
                 lambda v, c: ("PASS", f"registered v{v}") if c.policy_version else ("FAIL", "not a registered version")),
            Rule("POLICY-APPLIES", PARSE, "uc042lib.policy.applicability (analysis.analyse_policy: POLICY_NOT_APPLICABLE)",
                 "effective by the period end and not superseded on or before the period start", _policy_applies),
        ],
        "Effective date": [
            Rule("POLICY-EFFECTIVE", PARSE, "uc042lib.policy.recognise", "equals the registered effective date",
                 _policy_field("effective")),
            Rule("POLICY-EFFECTIVE-BY-PERIOD-END", PARSE, "uc042lib.validate.Validator.setup",
                 "effective on or before the period end (else the engine drops the policy)", _date_not_after_period_end),
        ],
        "Reconciliation point": [Rule("POLICY-POINT", PARSE, "uc042lib.validate.Validator.setup",
                                      "matches 'HH:MM Europe/London'",
                                      lambda v, c: ("PASS", "HH:MM Europe/London") if re.fullmatch(r"\d{2}:\d{2} Europe/London", v)
                                      else ("FAIL", "FORMAT: not 'HH:MM Europe/London': the engine marks IN-17 unusable"))],
        "Reconciliation method": [Rule("POLICY-METHOD", CONTROL, "uc042lib.validate.check_policy_and_points (C03-POLICY)",
                                       "STANDARD for C03-POLICY to pass", _equals("STANDARD"))],
        "Internal reconciliation basis": [Rule("POLICY-BASIS", CONTROL, "uc042lib.validate.check_policy_and_points (C03-POLICY)",
                                               "'Per currency' for C03-POLICY to pass", _equals("Per currency"))],
    },
    "IN-18": {
        "Accountable person": [Rule("GOV-PERSON", CONTROL, "uc042lib.validate.check_checklist (C16-GOVERNANCE)", "non-empty",
                                    lambda v, c: ("PASS", "present") if v.strip() else ("FAIL", "empty"))],
        "Allocated from": [Rule("GOV-ALLOCATED-FROM", CONTROL, "uc042lib.validate.check_checklist (C16-GOVERNANCE)",
                                "YYYY-MM-DD and not after the period end", _date_not_after_period_end)],
    },
    "IN-19": {
        "Period": [Rule("RETURN-PERIOD", CONTROL, "uc042lib.validate.check_checklist (C16-RETURN); ingest.analysis.analyse_pdf",
                        "the previous month (YYYY-MM)",
                        lambda v, c: ("NOT_EVALUATED", "no reporting period supplied") if c.previous_token is None else
                        (("PASS", f"equals {c.previous_token}") if v == c.previous_token else ("FAIL", f"expected {c.previous_token}")))],
        "Submitted at": [Rule("RETURN-SUBMITTED-AT", CONTROL, "uc042lib.validate.check_checklist (C16-RETURN, parse_ts)",
                              "ISO 8601 timestamp with an explicit offset",
                              lambda v, c: ("PASS", "ISO timestamp with offset") if _iso_ts(v) else
                              ("FAIL", "FORMAT: not an ISO timestamp with an offset: C16-RETURN fails"))],
        "Due date": [Rule("RETURN-DUE-DATE-FORMAT", CONTROL, "uc042lib.validate.check_checklist (C16-RETURN)",
                          "YYYY-MM-DD (the business-day value itself is computed and compared by UC-042, not here)",
                          lambda v, c: ("PASS", "YYYY-MM-DD") if _iso_date(v) else ("FAIL", "FORMAT: not a YYYY-MM-DD date"))],
    },
}

# Labels for which UC-042 has no value rule: reported, never given an invented one.
NO_RULE_REASON = {
    ("IN-15", "Institution"): "not compared by UC-042 (check_designation does not read it)",
    ("IN-16", "Institution"): "not compared by UC-042 (check_designation does not read it)",
    ("IN-17", "Safeguarding method"): "not read by any UC-042 calculation",
    ("IN-17", "Frequency"): "not read by any UC-042 calculation",
    ("IN-18", "Role"): "not read by any UC-042 calculation",
    ("IN-19", "Return"): "not read by any UC-042 calculation",
    ("IN-19", "Submission reference"): "not read by any UC-042 calculation",
}


def document_rules(category: str, fields: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """Rules that span fields: (rule_id, level, result, detail)."""
    out = []
    if category == "IN-19" and "Submitted at" in fields and "Due date" in fields:
        ts, due = _iso_ts(fields["Submitted at"]), _iso_date(fields["Due date"])
        if ts and due:
            out.append(("RETURN-SUBMITTED-BY-STATED-DUE", CONTROL, "PASS" if ts.date() <= due else "FAIL",
                        f"submitted {ts.date()} vs stated due {due} (UC-042 compares with its computed due date)"))
    return out
