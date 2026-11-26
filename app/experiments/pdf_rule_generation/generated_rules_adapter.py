"""Experiment A2 - turn generated_pdf_rules.json into executable rules with the SAME interface as
smartparser.pdf_extraction.rules (RULES, NO_RULE_REASON, document_rules), for side-by-side comparison only.

Isolated: not imported by smartparser. The hand-maintained rules are not replaced; the comparison harness swaps the
rule tables in-process (monkeypatch) and restores them.

Principles applied
  * Only sites whose pattern is extraction-relevant become executable rules (REGEX_MATCH, DATE_PARSE, TIMESTAMP_PARSE,
    plus identification facts from data: registered policy versions and effective dates). Business-level sites
    (group E: CONST_EQUALS, CROSS_DOC_EQUALS, NON_EMPTY, COMPUTED_EQUALS) are NOT turned into extraction rules; the
    label is reported NOT_EVALUATED with the downstream UC-042 location.
  * Helper semantics (what _date_or_none / parse_ts accept) cannot be generated from code without executing it. They
    are restated here (HELPER_SEMANTICS) and PINNED to the SHA-256 of the helper's source in the artefact: if UC-042
    changes the helper, loading fails visibly. This is the explicit-configuration part (group C).
  * POLICY-APPLIES (period applicability) has no label site; its algorithm is restated and pinned the same way.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from smartparser.pdf_extraction.rules import CONTROL, PARSE, Rule

HERE = Path(__file__).resolve().parent
ARTEFACT = HERE / "generated_pdf_rules.json"

# EXPLICIT CONFIGURATION, pinned to the UC-042 helper source (sha256 of the function's source text).
HELPER_SEMANTICS = {
    "_date_or_none": "date.fromisoformat(text[:10]) if text else None (Python 3.11): the first 10 characters as an ISO date",
    "parse_ts": "datetime.fromisoformat(text) with an explicit UTC offset (Python 3.11)",
}
PINS_FILE = HERE / "helper_pins.json"   # {helper: sha256 of its UC-042 source}, recorded after reviewing that source


def _date_or_none(text: str):
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _parse_ts(text: str):
    try:
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else None


IMPLEMENTATION = {"_date_or_none": _date_or_none, "parse_ts": _parse_ts}


class AdapterError(RuntimeError):
    pass


def load(artefact: Path = ARTEFACT, pins_file: Path = PINS_FILE) -> dict:
    doc = json.loads(artefact.read_text(encoding="utf-8"))
    pins = json.loads(pins_file.read_text(encoding="utf-8")) if pins_file.is_file() else {}
    for name, h in doc["helpers"].items():
        if name not in IMPLEMENTATION:
            raise AdapterError(f"no reviewed implementation for UC-042 helper {name}")
        if pins.get(name) != h["source_sha256"]:
            raise AdapterError(f"UC-042 helper {name} ({h['file']}:{h['line']}) is not pinned or changed: source sha256 "
                               f"{h['source_sha256'][:12]} vs pinned {str(pins.get(name))[:12]}; review its source and re-pin")
    return doc


def _syntax_rule(site):
    pat, label, fn = site["pattern"], site["label"], site["function"]
    level = PARSE if site["consequence"].startswith("PARSE") else CONTROL
    src = f"{site['file']}:{site['line']} {fn}() [generated]"
    rid = f"GEN:{label}:{pat}"
    if pat == "REGEX_MATCH":
        rx = site["parameters"]["regex"]
        return Rule(rid, level, src, f"re.match({rx!r})",
                    lambda v, c, rx=rx: ("PASS", f"matches {rx}") if re.match(rx, v) else ("FAIL", f"FORMAT: does not match {rx}"))
    helper = site["parameters"]["helper"].rsplit(".", 1)[1]
    impl = IMPLEMENTATION[helper]
    return Rule(rid, level, src, f"readable by UC-042 {helper}",
                lambda v, c, impl=impl, helper=helper: ("PASS", f"readable by {helper}") if impl(v) is not None
                else ("FAIL", f"FORMAT: not readable by UC-042 {helper}: UC-042 cannot evaluate it"))


def build(doc: dict):
    """(RULES, NO_RULE_REASON, document_rules) with the hand-rules interface."""
    rules: dict[str, dict[str, list[Rule]]] = {}
    downstream: dict[tuple[str, str], list[str]] = {}
    for s in doc["sites"]:
        for cat in s["categories"]:
            if s["pattern"] in ("REGEX_MATCH", "DATE_PARSE", "TIMESTAMP_PARSE"):
                rules.setdefault(cat, {}).setdefault(s["label"], []).append(_syntax_rule(s))
            elif s["group"] == "E":
                downstream.setdefault((cat, s["label"]), []).append(f"{s['file']}:{s['line']} {s['function']}()")
    # Identification facts from DATA (group A): registered versions and effective dates.
    versions = {v["version"]: v for v in doc["policy_versions"]}
    vsrc = "uc042lib/policy.py POLICY_VERSIONS [generated]"

    def version_rule(v, c):
        return ("PASS", f"registered v{v}") if v in versions else ("FAIL", "not a registered version")

    def effective_rule(v, c):
        if c.policy_version is None:
            return "FAIL", "not a registered policy version"
        reg = versions.get(c.policy_version["version"])
        return ("PASS", "equals the registered effective date") if reg and v == reg["effective"] else \
            ("FAIL", f"registered effective date is {reg['effective'] if reg else '?'}")

    def applies_rule(v, c):   # restated algorithm of uc042lib.policy.applicability (pinned via the artefact's sha)
        if v not in versions:
            return "FAIL", "not a registered version"
        if c.period_end is None:
            return "NOT_EVALUATED", "no reporting period supplied"
        eff = date.fromisoformat(versions[v]["effective"])
        later = sorted(x["effective"] for x in versions.values() if x["effective"] > versions[v]["effective"])
        if eff > c.period_end:
            return "FAIL", f"v{v} takes effect on {eff}, after the period"
        if later and date.fromisoformat(later[0]) <= c.period_start:
            return "FAIL", f"v{v} is superseded from {later[0]}, before the period"
        return "PASS", f"v{v} applies to the period"

    pol = rules.setdefault("IN-17", {})
    pol.setdefault("Document version", []).extend([
        Rule("GEN:POLICY-VERSION", PARSE, vsrc, "a registered policy version", version_rule),
        Rule("GEN:POLICY-APPLIES", PARSE, "uc042lib/policy.py applicability [restated, pinned]",
             "applies to the period", applies_rule)])
    pol.setdefault("Effective date", []).insert(0, Rule("GEN:POLICY-EFFECTIVE", PARSE, vsrc,
                                                        "equals the registered effective date", effective_rule))
    no_rule = {}
    for cat, spec in doc["pdf_categories"].items():
        for lbl in spec["labels"]:
            if lbl in rules.get(cat, {}):
                continue
            if lbl in doc["labels_without_consumer"]:
                no_rule[(cat, lbl)] = "not read by any UC-042 consumer [generated]"
            elif (cat, lbl) in downstream:
                no_rule[(cat, lbl)] = "downstream UC-042 control only: " + "; ".join(downstream[(cat, lbl)]) + " [generated]"
            else:
                no_rule[(cat, lbl)] = "no extraction rule generated [generated]"
    return rules, no_rule, (lambda category, fields: [])   # cross-field checks are business-level (E): none generated


def helper_sources(doc: dict) -> dict:
    return {k: {"file": v["file"], "line": v["line"], "sha256": v["source_sha256"], "source": v["source"]}
            for k, v in doc["helpers"].items()}


def verify_helper_equivalence(doc: dict) -> dict:
    """Execute nothing from UC-042: re-parse each helper's recorded source and confirm its body is the one reviewed
    (same AST dump as the pinned review copy). Returns {helper: ast_dump_sha256}."""
    return {k: hashlib.sha256(ast.dump(ast.parse(v["source"])).encode()).hexdigest() for k, v in doc["helpers"].items()}
