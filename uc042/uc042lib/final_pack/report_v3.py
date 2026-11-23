"""Renderer 3.0 report view model (final-pack schema 1.3): final_pack.json -> ordered blocks, outcome first.

Sections (numbered as rendered; a conditional section that is not shown leaves no gap):
  1 Executive outcome             2 Reconciliation overview      3 Account-level results
  4 Financial and daily details   5 Evidence completeness and source inventory
  6 Exceptions and investigations (only when the engine raised exceptions)
  7 Analyst review and decision record   8 Limitations and disclosures   9 Technical appendix

Rules: values are the stored values. Amounts may be shown with a currency symbol and thousands separators, but only when the
formatted text converts back to exactly the stored decimal (money()); otherwise the stored text is shown. Counts of stored
rows made by the report are labelled as such. Nothing is recalculated, no AI text is written here, no AI section is shown
without AI content, and a rejected investigation contributes only the analyst's decision. Section 6 parts are shown only
when they have content. Every limitation in the pack appears exactly once (main body or appendix).

The renderer-2.x builder (report.build_report_v2) is frozen and separate; this module never changes how a published 1.x / 2.x
pack renders.
"""
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from ..pack.model import canonical
from .model import DATA_HANDLING

SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]
DERIVED_NOTE = "Counts of stored rows made by the report (derived counts). No amount is recalculated."
ENGINE_NOTE = "Values as reported by the deterministic engine."

# Limitation texts -> category. Unknown texts are shown in the main body under "Other limitations": nothing is hidden.
CATEGORIES = [("data", "Data and synthetic-data limitations"), ("scope", "Reconciliation scope limitations"),
              ("extraction", "Evidence extraction limitations"), ("ai", "AI limitations"),
              ("provenance", "Technical provenance"), ("other", "Other limitations")]
KNOWN_LIMITATIONS = {
    "Resource items B-D are taken as reported (0.00); no independent source exists.": "scope",
    "The D+1 comparison is not performed (synthetic convention).": "scope",
    "PDF key details are parsed from a fixed synthetic layout; no human confirmation of extracted fields.": "extraction",
    "Results show the internal consistency of illustrative synthetic data, not operational truth or compliance.": "data",
    "Monthly totals are not included: the engine does not calculate them and the pack performs no financial calculation (D4).": "scope",
    "AI investigations examine one exception at a time; there is no group-level AI investigation.": "ai",
    "Supporting PDF documents (IN-15..IN-19) are not used as AI evidence.": "ai",
    "Reported values are copied from the deterministic engine and source records; this report recalculates nothing.": "provenance",
    DATA_HANDLING: "ai",
}
SUMMARY_FAILURE_TEXT = {
    "invalid_summary": "its output did not pass the deterministic validation rules, so it was refused",
    "configuration": "no AI provider was configured",
    "unsupported_provider": "the configured AI provider does not support closing summaries",
}


# --------------------------------------------------------------------------------------------------------------- helpers
def _v(x, default="-"):
    """As report._v, except that an empty dict also shows the default (renderer 2.x printed it as an empty string)."""
    if x is None or x == "" or x == [] or x == {}:
        return default
    if isinstance(x, (list, tuple)):
        return ", ".join(str(i) for i in x)
    if isinstance(x, dict):
        return "; ".join(f"{k}: {v}" for k, v in x.items())
    return str(x)


def _n(x):
    return f"{x:,}" if isinstance(x, int) else str(x)


def _counts(d, default="none"):
    return "; ".join(f"{k} {_n(v)}" for k, v in d.items()) if d else default


def money(value, currency):
    """A stored decimal amount with its currency symbol and thousands separators. The digits are never changed: the result is
    returned only if it converts back to exactly the stored decimal (same value and the same number of decimal places);
    otherwise (for example 'not available') the stored text is returned unchanged."""
    if value is None or value == "":
        return "-"
    s = str(value).strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        return str(value)
    if not d.is_finite() or "e" in s.lower():
        return str(value)
    sign = "-" if d.is_signed() and d != 0 else ""
    body = format(abs(d), ",f")
    sym = SYMBOL.get(currency or "")
    out = f"{sign}{sym}{body}" if sym else f"{sign}{body}" + (f" {currency}" if currency else "")
    back = unformat(out, currency)
    try:
        same = Decimal(back) == d and _places(back) == _places(s)
    except InvalidOperation:
        same = False
    return out if same else str(value)


def _places(s):
    s = s.strip().lstrip("+-")
    return len(s.split(".", 1)[1]) if "." in s else 0


def unformat(text, currency):
    """The plain decimal text of a money() result (used by the integrity tests)."""
    t = str(text)
    sym = SYMBOL.get(currency or "")
    if sym:
        t = t.replace(sym, "")
    if currency:
        t = t.replace(f" {currency}", "")
    return t.replace(",", "").strip()


def _table(headers, rows, widths=None, code_cols=(), layout="grid"):
    return {"type": "table", "headers": headers, "rows": [[_v(c) for c in r] for r in rows], "widths": widths or [1] * len(headers),
            "code_cols": list(code_cols), "layout": layout}


def _para(text, cls=None):
    b = {"type": "para", "text": text}
    if cls:
        b["cls"] = cls
    return b


def _sub(text):
    return {"type": "sub", "text": text}


def _notice(cls, text):
    return {"type": "notice", "cls": cls, "text": text}


def _period_name(rp):
    try:
        y, m = rp["start"][:4], int(rp["start"][5:7])
        return f"{MONTHS[m - 1]} {y}"
    except (KeyError, ValueError, IndexError):
        return rp.get("period_id", "")


def _summary_kind(reason):
    m = re.search(r"\(([a-z_]+)\)\s*$", reason or "")
    return m.group(1) if m else None


def ai_request_made(f):
    """Whether this pack's preparation involved an AI request (disclosures). Conservative: any exception (investigations
    run per exception) or any closing summary that was not NOT_REQUIRED counts."""
    return bool(f["exception_register"]) or f["closing_summary"]["status"] != "NOT_REQUIRED"


def ai_content_types(f):
    out = []
    if f["ai_investigations"]:
        out.append("investigation assessments")
        if any(i["confirmed_findings"] for i in f["ai_investigations"]):
            out.append("observations")
        if any(i["hypotheses"] for i in f["ai_investigations"]):
            out.append("hypotheses")
        if any(i["next_steps"] for i in f["ai_investigations"]):
            out.append("suggested next steps")
    if f["closing_summary"]["status"] == "GENERATED":
        out.append("the closing summary")
    return out


# --------------------------------------------------------------------------------------------------------------- build
def build_report_v3(final):
    final = json.loads(canonical(final))  # canonical form: rendering from memory or from the stored file is identical
    m = final["metadata"]
    sections = [("outcome", "Executive outcome", _s_outcome), ("overview", "Reconciliation overview", _s_overview),
                ("accounts", "Account-level results", _s_accounts), ("details", "Financial and daily details", _s_details),
                ("evidence", "Evidence completeness and source inventory", _s_evidence)]
    if final["exception_register"]:
        sections.append(("exceptions", "Exceptions and investigations", _s_exceptions))
    if final.get("relationship_assessments") is not None:   # evidence-bearing relationships; absent in every older pack
        sections.append(("relationships", "Engine relationships and AI assessments", _s_relationships))
    sections += [("review", "Analyst review and decision record", _s_review),
                 ("limitations", "Limitations and disclosures", _s_limitations),
                 ("appendix", "Technical appendix", _s_appendix)]
    toc = {"type": "toc", "columns": 1, "entries": [(i + 1, t, a) for i, (a, t, _) in enumerate(sections)]}
    blocks = []
    for i, (anchor, title, fn) in enumerate(sections):
        blocks.append({"type": "section", "number": i + 1, "title": title, "anchor": anchor, "keep_mm": 40})
        part = fn(final)
        if anchor == "outcome":
            part.append(toc)
        blocks += part
    blocks.insert(0, {"type": "title", "text": f"UC-042 Final Audit Pack - {_period_name(m['reporting_period'])}",
                      "subtitle": f"Reporting period {m['reporting_period']['period_id']} ({m['reporting_period']['start']} to "
                                  f"{m['reporting_period']['end']}) - dataset {final['source_inventory']['dataset']['dataset']} - "
                                  f"version {m['version']} - {m['status']}"})
    blocks.append({"type": "footer", "text": f"Document provenance: final_content_sha256 {final['final_content_sha256']} - "
                                            f"source pack {m['source_pack']['pack_id']} ({m['source_pack']['pack_content_sha256']}) - "
                                            f"generated {m['generated_at']} - {m['report_renderer']}"})
    return blocks


# --------------------------------------------------------------------------------------------------------------- 1
def _s_outcome(f):
    m, o = f["metadata"], f["outcome_summary"]
    g = o["figures"]
    out = []
    if m["status"] == "PREVIEW":
        out.append(_notice("bad", "PREVIEW - not a final audit pack. No decision to generate the final audit pack has been recorded."))
    else:
        out.append(_notice("info", f"Final audit pack {m['final_pack_id']}, version {m['version']}, generated {m['generated_at']}. "
                                   "The generation record is in 'Analyst review and decision record'."))
    req = g["required_files_total"]
    out.append({"type": "outcome", "badge": g["engine_case_status"],
                "label": "Deterministic engine case status - the engine's result for these checks, not an independent audit conclusion",
                "tiles": [("Control results passed", f"{_n(g['control_results_passed'])} of {_n(g['control_results_total'])}"),
                          ("Failed control results", _n(g["control_results_failed"])),
                          ("Checks performed", _n(g["checks_total"])),
                          ("Exceptions raised", _n(g["exceptions_total"])),
                          ("Required files present" + (f" (+{_n(g['optional_files_present'])} of {_n(g['optional_files_total'])} optional)"
                                                       if g["optional_files_total"] else ""),
                           f"{_n(g['required_files_present'])} of {_n(req)}")],
                "headline": o["headline"]})
    out += [_sub("What this outcome means"),
            {"type": "bullets", "items": o["statements"]},
            _para(o["generated_by"], "muted")]
    cs = f["closing_summary"]
    if not f["exception_register"] and cs["status"] != "NOT_REQUIRED":
        out += _closing_summary_blocks(f)  # only possible for a pack assembled with a summary despite no exception
    elif cs["status"] == "NOT_REQUIRED":
        out.append(_para("No AI closing summary was required: no exceptions were raised and no AI investigation is included. "
                         "No AI request was made for this summary."))
    else:
        out.append(_para("The AI-generated closing summary (or the statement that it is unavailable) is in "
                         "'Exceptions and investigations'."))
    out += [_sub("Disclosures"),
            _notice("info", f["statements"]["synthetic_notice"]),
            _notice("info", f["statements"]["not_a_compliance_opinion"]),
            _notice("info", f"{g['engine_case_status']} is the deterministic engine's case status for the checks it ran. It is not a "
                            "statement that an audit is clean, and it is not an audit opinion or a compliance certification.")]
    return out


# --------------------------------------------------------------------------------------------------------------- 2
def _s_overview(f):
    r = f["reconciliation_results"]
    co, g = r["control_outcomes"], f["outcome_summary"]["figures"]
    out = [_para(ENGINE_NOTE, "muted"),
           {"type": "kv", "pairs": [
               ("Engine case status", g["engine_case_status"]), ("Evidence completeness (engine)", g["evidence_completeness"]),
               ("Control outcome summary (engine)", co["summary"]),
               ("Control results (engine)", f"{_n(co['total_results'])} results: {_counts(co['by_outcome'])}"),
               ("Checks (engine)", f"{_n(co['check_types'])} checks; {_n(co['check_types_with_results'])} with results"
                                   + (f"; no findings: {', '.join(co.get('checks_no_findings', []))}" if co.get("checks_no_findings") else "")),
               ("Checks with failed results", _v(co.get("checks_with_failures"), "none")),
               ("Checks not fully assessed", _v(co.get("checks_not_fully_assessed"), "none")),
               ("Exceptions", f"{_n(g['exceptions_total'])}" + (f" (by severity: {_counts(g['exceptions_by_severity'])})"
                                                                if g["exceptions_total"] else "")),
               ("Applicable controls (engine)", _v(co.get("applicable_controls"), "none"))]}]
    nf = [c for c in r["control_checks"] if c["check_outcome"] == "NO_FINDINGS"]
    if nf:
        out.append(_sub("Checks that reported no findings"))
        for c in nf:
            out.append({"type": "item", "kind": "info", "heading": f"{c['check_id']} - {c['control_name']} ({c['control_code']})",
                        "badge": "NO FINDINGS", "fields": [
                            ("Engine note (copied)", c.get("check_outcome_note") or "No engine note was recorded for this check."),
                            ("How it is reported", "It ran and found no problem. It emits a result only when it finds one, so it "
                                                   "has no PASS results and is not counted as passed; it is not a failure and is "
                                                   "not 'not applicable'.")]})
    internal, external = r["internal_by_currency_day"], r["external_by_account_day"]
    rows = [["Internal: requirement vs resource, per currency and day", _n(len(internal)),
             _counts(Counter(x["difference_outcome"] for x in internal)), _n(sum(_nonzero(x["difference_reported"]) for x in internal))],
            ["External: ledger vs bank, per account and day", _n(len(external)),
             _counts(Counter(x["difference_outcome"] for x in external)), _n(sum(_nonzero(x["difference_reported"]) for x in external))]]
    out += [_sub("Daily reconciliation at a glance"), _para(DERIVED_NOTE, "muted"),
            _table(["Reconciliation", "Rows", "Difference outcome (engine), counted", "Rows with a non-zero reported difference"],
                   rows, [3, 1, 2.5, 2])]
    return out


def _nonzero(v):
    try:
        return Decimal(str(v)) != 0
    except (InvalidOperation, ValueError):
        return False


# --------------------------------------------------------------------------------------------------------------- 3
def _s_accounts(f):
    r = f["reconciliation_results"]
    rows = []
    for a in f["metadata"]["accounts"]:
        ext = [x for x in r["external_by_account_day"] if x["account_id"] == a["account_id"]]
        st = [b for b in r["settlements"] if b["account_id"] == a["account_id"]]
        if ext:
            days = f"{_n(len(ext))} days; {_counts(Counter(x['difference_outcome'] for x in ext))}"
            nonzero = _n(sum(_nonzero(x["difference_reported"]) for x in ext))
            ev = _counts(Counter(x["evidence_status"] for x in ext if x["evidence_status"]), "none recorded")
        else:
            days, nonzero, ev = "no external daily rows in the engine results", "-", "-"
        sett = (f"{_n(len(st))} batches; lines {_counts(Counter(b['lines_outcome'] for b in st))}; "
                f"bank {_counts(Counter(b['bank_outcome'] for b in st))}") if st else "none"
        rows.append([a["account_id"], a["currency"], a["account_class"], days, nonzero, ev, sett])
    return [_para(DERIVED_NOTE, "muted"),
            _table(["Account", "Ccy", "Class", "External daily reconciliation (engine outcomes, counted)",
                    "Days with a non-zero reported difference", "Evidence status (engine), counted", "Settlement batches (counted)"],
                   rows, [1.4, 0.6, 1.6, 2.2, 1.3, 1.4, 2.2], [0])]


# --------------------------------------------------------------------------------------------------------------- 4
def _s_details(f):
    r = f["reconciliation_results"]
    ccy = {a["account_id"]: a["currency"] for a in f["metadata"]["accounts"]}
    out = [_para("Amounts are the engine's stored values, shown with the currency symbol and thousands separators; the digits "
                 "are unchanged and nothing is recalculated.", "muted"),
           _sub("Internal reconciliation by currency and day"),
           _table(["Date", "Ccy", "Requirement", "Resource", "Difference", "Reported difference", "Outcome"],
                  [[x["date"], x["currency"], money(x["requirement"], x["currency"]), money(x["resource"], x["currency"]),
                    money(x["difference"], x["currency"]), money(x["difference_reported"], x["currency"]), x["difference_outcome"]]
                   for x in r["internal_by_currency_day"]], [1.2, 0.6, 1.5, 1.5, 1.2, 1.3, 1]),
           _sub("External reconciliation by account and day"),
           _table(["Date", "Account", "Ledger", "Bank", "Difference", "Reported difference", "Outcome", "Evidence status"],
                  [[x["date"], x["account_id"], money(x["ledger_balance"], x.get("currency") or ccy.get(x["account_id"])),
                    money(x["bank_balance"], x.get("currency") or ccy.get(x["account_id"])),
                    money(x["difference"], x.get("currency") or ccy.get(x["account_id"])),
                    money(x["difference_reported"], x.get("currency") or ccy.get(x["account_id"])), x["difference_outcome"],
                    _v(x["evidence_status"], "none")] for x in r["external_by_account_day"]],
                  [1.2, 1.4, 1.4, 1.4, 1.1, 1.2, 1, 1.4]),
           _sub("Client balances"), _para(r["client_balances_note"]),
           _sub("Opening positions")]
    for name, items in r["opening_positions"].items():
        if items:
            keys = list(dict.fromkeys(k for i in items for k in i))
            out += [_para(name.replace("_", " ").capitalize() + " (as stored)"),
                    _table(keys, [[i.get(k) for k in keys] for i in items])]
    if not any(r["opening_positions"].values()):
        out.append(_para("No opening positions were recorded by the engine."))
    out += [_sub("Control checks"),
            _table(["Check", "Control", "Name", "Outcome (engine)", "Results (engine)"],
                   [[c["check_id"], c["control_code"], c["control_name"], c["check_outcome"],
                     _counts(c["result_counts"], "no results (see note)" if c["check_outcome"] == "NO_FINDINGS" else "none")]
                    for c in r["control_checks"]], [1.6, 1, 3, 2, 2]),
            _sub("Settlement batches"),
            _table(["Batch", "Type", "Date", "Account", "Ccy", "Net reported", "Lines", "Bank", "Top-up"],
                   [[b["batch_id"], b["counterparty_type"], b["settlement_date"], b["account_id"], b["currency"],
                     money(b["net_amount_reported"], b["currency"]), b["lines_outcome"], b["bank_outcome"], _v(b["fee_top_up_outcome"], "n/a")]
                    for b in r["settlements"]], [1.8, 1, 1.1, 1.2, 0.6, 1.1, 0.9, 0.9, 0.9])]
    return out


# --------------------------------------------------------------------------------------------------------------- 5
def _s_evidence(f):
    s, g = f["source_inventory"], f["outcome_summary"]["figures"]
    items = s["missing_evidence"]["items"]
    req, pres = g["required_files_total"], g["required_files_present"]
    head = (f"All {_n(req)} required source files were present." if req and req == pres
            else f"{_n(pres)} of {_n(req)} required source files were present.")
    if g["optional_files_total"]:
        head += f" {_n(g['optional_files_present'])} of {_n(g['optional_files_total'])} optional files were present."
    out = [_notice("ok" if req == pres and not items else "warn", head + (
        " The engine recorded no missing evidence." if not items else
        f" The engine recorded {_n(len(items))} missing-evidence item(s): evidence it expected for a date or record was not "
        "available. The affected results are shown as not available, never as zero."))]
    if items:
        out += [_sub("Missing evidence recorded by the deterministic engine"),
                _table(["Item", "Expected evidence", "Impact (engine)", "Related controls", "Exception"],
                       [[i["item_id"], i["expected_evidence"], i["completeness_impact"], i.get("related_controls"), i["related_exception_id"]]
                        for i in items], [1, 2.6, 4, 1.6, 1.4], [0]),
                _para(s["missing_evidence"]["statement"], "muted")]
    out += [_sub("Source inventory"),
            _table(["ID", "File", "Description", "Records", "Requirement", "Availability"],
                    [[x["evidence_id"], x["source_file"], x["description"], f"{x['record_count']} {x['record_unit']}", x["requirement"],
                      x["availability"]] for x in s["files"]], [0.8, 3.6, 3, 1.4, 1.3, 1.3], [0]),
            _para("Each file's SHA-256 and the dataset fingerprints are in the technical appendix; every reported figure traces to "
                  "its source file through the engine's result IDs and these hashes.", "muted"),
            {"type": "kv", "pairs": [("Dataset", s["dataset"]["dataset"]),
                                     ("Scenario (synthetic test label)", f"{s['dataset']['scenario_id']}: {_v(s['dataset']['scenario_name'], 'no name')}"),
                                     ("Processing run", s["processing_run_id"])]}]
    return out


# --------------------------------------------------------------------------------------------------------------- 6
def _inv_status(e):
    i, x = e["investigation"], e["exception"]
    review = i.get("analyst_review") or {}
    if i["inclusion"] == "INCLUDED" and review.get("decision") == "REJECT":
        return (f"{i['investigation_id']}: REJECTED BY ANALYST - its AI content is excluded from this report; the analyst's "
                "reason is in 'Analyst review and decision record'")
    if i["inclusion"] == "INCLUDED":
        return f"{i['investigation_id']} ({i['investigation_mode']}): included - accepted by the analyst"
    if i["inclusion"] == "EXCLUDED_BY_ANALYST":
        return f"Excluded from AI investigation by the analyst. Reason (as recorded): {i['reason']}"
    return ("Not investigated: no AI investigation is included; the exception is reported from the deterministic results only"
            + (f". Reason (as recorded): {i['reason']}" if i["reason"] else ". No further reason was recorded."))


def _s_exceptions(f):
    reg = f["exception_register"]
    invs = f["ai_investigations"]
    out = [_notice("bad", "Every exception below remains UNRESOLVED. Neither AI investigation, an analyst's decision on an AI "
                          "investigation, nor report generation resolves an exception.")]
    out.append(_sub("Exception register (deterministic engine)"))
    for e in reg:
        x, i = e["exception"], e["investigation"]
        out.append({"type": "item", "kind": "unresolved", "heading": f"{x['exception_id']} - {x['category']}", "badge": e["resolution_status"],
                    "fields": [("Dates", f"{x['first_date']} to {x['last_date']}"), ("Account / currency", f"{x['account_id']} / {x['currency']}"),
                               ("Amount (engine)", money(x["amount"], x["currency"]) if x["amount"] != "" else "none recorded"),
                               ("Severity (engine)", x["severity"]), ("Root cause key (engine)", x["root_cause"]),
                               ("Deterministic status", f"{x['status']}; review {x['review_status']}; evidence {_v(x['evidence_status'], 'n/a')}"),
                               ("Affected results (engine)", f"{_n(x.get('affected_results', 0))}: " + _v(x.get("affected_result_ids"), "none")),
                               ("Source evidence (engine)", _v(x.get("evidence"), "none recorded")),
                               ("AI investigation", _inv_status(e)),
                               ("Other investigation attempts", f"ineligible {_v(i['other_attempts']['published_ineligible'], 'none')}; "
                                                                f"eligible not selected {_v(i['other_attempts']['published_not_selected'], 'none')}; "
                                                                f"unpublished {i['other_attempts']['not_published']}")]})
    mud = f["executive_summary"]["material_unexplained_differences"]
    if mud:
        out += [_sub("Material unexplained differences (engine evidence status)"),
                _table(["Exception", "Amount", "Category", "Engine evidence status"],
                       [[x["exception_id"], money(x["amount"], x["currency"]), x["category"], x["evidence_status"]] for x in mud],
                       [2, 1.4, 3, 2], [0])]
    rel = f["relationships"]
    if rel["investigation_groups"] or rel["candidate_relationships"]:
        out.append(_sub("Investigation groups and candidate relationships (engine)"))
        out.append(_table(["Group", "Exceptions", "Link types", "Links"], [[g["group_id"], g["exception_ids"], g["link_types"], g["links"]]
                                                                         for g in rel["investigation_groups"]], [1.3, 2, 1.2, 6], [0])
                   if rel["investigation_groups"] else _para(rel["group_statement"]))
        out.append(_table(["Candidate", "Exceptions", "Basis", "Detail", "Label"], [[c["candidate_id"], c["exception_ids"], c["basis"],
                                                                                    c["detail"], c["label"]] for c in rel["candidate_relationships"]],
                          [1.3, 2, 1.6, 4, 2], [0]) if rel["candidate_relationships"] else _para(rel["candidate_statement"]))
    if not invs:
        out += [_sub("AI investigations"),
                _para("No AI investigation content is included in this report. The status of each exception's AI investigation "
                      "is shown in the exception register above.")]
    else:
        out += _ai_parts(f)
    out += _closing_summary_blocks(f)
    return out


def _na(text, inv):
    return text if text is not None else f"Not supplied by this investigation (findings schema {inv['versions']['findings_schema']}); not back-filled."


def _ai_parts(f):
    invs = f["ai_investigations"]
    out = [_sub("AI investigation summary (accepted by the analyst)"),
           _notice("ai", "AI-generated content follows, each investigation accepted by the analyst. Confirmed observations, AI "
                         "assessments and hypotheses are kept separate; none of them is a finding of the deterministic engine.")]
    for inv in invs:
        ev = inv["evidence_examined"]
        established = [f"{x['ref']}: {x['title'] or x['description']}" for x in inv["confirmed_findings"]]
        unknown = [f"{x['ref']}: {x['does_not_establish']}" for x in inv["confirmed_findings"] if x["does_not_establish"]]
        unknown += [f"{g['ref']}: {g['description']}" for g in inv["evidence_gaps"]]
        out.append({"type": "item", "kind": "info", "heading": f"{inv['exception_id']} - investigation {inv['investigation_id']}",
                    "badge": "AI-GENERATED - " + inv["investigation_mode"].upper() + " MODE", "fields": [
                        ("Model", f"{inv['provider']} {inv['model']} (prompt {inv['versions']['prompt']}, findings schema {inv['versions']['findings_schema']})"),
                        ("Investigated at", _v(inv["investigated_at"])), ("Route", _v(inv["route"])),
                        ("Evidence examined", f"{ev['records_initial']} records in the initial packet, {ev['records_final']} after tool retrieval; "
                                              f"files {_v(ev['source_files'])}; {ev['searches']} searches"),
                        ("Tool activity", f"{_v(ev['tool_calls_requested'], '0')} tool call(s) over {_v(ev['tool_rounds'], '0')} round(s): {_v(ev['tools_used'], 'none')}"),
                        ("Validation", f"{inv['validation']['status']}; re-validated under the current rules"),
                        ("What it established (confirmed observations)", "; ".join(established) or "No confirmed observations."),
                        ("What remains unknown", "; ".join(unknown) or "Nothing further was reported as unknown.")]})
    out += [_sub("AI investigative assessments"),
            _notice("ai", "AI investigative assessments are the model's interpretation of the evidence. They are not established "
                          "facts; confirmed observations are listed separately.")]
    for inv in invs:
        a = inv["assessment"]
        out.append({"type": "item", "kind": "assessment", "heading": f"{inv['exception_id']} - {a['ref']}", "badge": "AI ASSESSMENT",
                    "fields": [("Assessment", a["summary"]), ("Overall evidence assessment", a["overall_evidence_assessment"])]})
    obs = [(inv, x) for inv in invs for x in inv["confirmed_findings"]]
    if obs:
        out += [_sub("Confirmed observations"),
                _para("Evidence-confirmed observations: validated findings whose citations resolve to the evidence ledger.")]
        for inv, x in obs:
            amounts = "; ".join(f"{a['evidence_id']} {a['field']} = {a['value']}" for a in x["amounts_and_dates"])
            evidence = "; ".join(f"{e} ({f['evidence_index'][e]['source_file']}:{f['evidence_index'][e]['source_line']})"
                                 if e in f["evidence_index"] else e for e in dict.fromkeys(x["evidence_refs"] + x["supporting_records"]))
            rels = "; ".join(f"{r['from']} -> {r['to']} ({r['relationship']})" for r in x["linked_relationships"])
            out.append({"type": "item", "kind": "confirmed", "heading": f"{x['ref']} - {_na(x['title'], inv) if x['title'] else x['description']}",
                        "badge": "EVIDENCE-CONFIRMED OBSERVATION", "fields": [
                            ("Exception", f"{inv['exception_id']} (UNRESOLVED)"), ("Description", x["description"]),
                            ("Why it is relevant", _na(x["audit_relevance"], inv)), ("What it establishes", _na(x["establishes"], inv)),
                            ("What it does not establish", _na(x["does_not_establish"], inv)),
                            ("Evidence relationship", x["evidence_relationship"]), ("Exact amounts and dates (copied)", _v(amounts)),
                            ("Supporting evidence (citations)", _v(evidence)), ("Linked relationships", _v(rels)),
                            ("Related open items", _v(x["related_open_items"]))]})
    hs = [(inv, h) for inv in invs for h in inv["hypotheses"]]
    if hs:
        out += [_sub("Hypotheses (not established)"),
                _notice("warn", "Hypotheses are possible explanations that the evidence does not establish. None is an established cause.")]
        for inv, h in hs:
            out.append({"type": "item", "kind": "hypothesis", "heading": f"{h['ref']} ({inv['exception_id']})", "badge": "HYPOTHESIS - NOT ESTABLISHED",
                        "fields": [("Possible explanation", h["description"]), ("Why it was considered", _na(h["rationale"], inv)),
                                   ("Supporting evidence", _v(h["supporting_evidence"], "none")),
                                   ("Contradicting evidence", _v(h["contradictory_evidence"], "none")), ("Limitations", h["limitations"]),
                                   ("Verification status", h["verification_status"])]})
    out += _gap_parts(f)
    idx = f["evidence_index"]
    if idx:
        out += [_sub("Cited source records"),
                _para("Only the source records cited by included AI content; full source files remain in the controlled dataset "
                      "(hashes in the technical appendix)."),
                _table(["Evidence ID", "Record type", "Source (file:line)", "File SHA-256", "Retrieved via / join key", "Key values", "Cited by"],
                       [[eid, e["record_type"], f"{e['source_file']}:{e['source_line']}", e["file_sha256"], f"{e['retrieved_via']} [{e['join_key']}]",
                         "; ".join(f"{k}={v}" for k, v in e["fields"].items() if v), _v(e["cited_by"])] for eid, e in idx.items()],
                       [2, 1.6, 2.2, 2.6, 2.4, 3.4, 2], [0, 2, 3, 6], layout="records")]
    steps = [(inv, s) for inv in invs for s in inv["next_steps"]]
    questions = [(inv, q) for inv in invs for q in inv["open_questions"]]
    if steps or questions:
        out += [_sub("Suggested next steps (recommendations, not completed actions)"),
                _notice("info", "AI recommendations for further investigation. None of them has been carried out.")]
        out += [{"type": "item", "kind": "step", "heading": f"{s['ref']} ({inv['exception_id']})", "badge": "SUGGESTED - NOT DONE",
                 "fields": [("Action", s["action"]), ("Rationale", s["rationale"]), ("Evidence needed", s["evidence_needed"])]}
                for inv, s in steps]
        if questions:
            out += [{"type": "bullets", "items": [f"Open question {q['ref']} ({inv['exception_id']}): {q['text']}" for inv, q in questions]}]
    return out


def _gap_parts(f):
    invs = f["ai_investigations"]
    engine = f["source_inventory"]["missing_evidence"]["items"]
    gaps = [(inv, g) for inv in invs for g in inv["evidence_gaps"]]
    searches = [(inv, s) for inv in invs for s in inv["not_found_searches"]]
    insufficient = [inv for inv in invs if inv["assessment"]["overall_evidence_assessment"] in ("INSUFFICIENT_EVIDENCE", "PARTIALLY_SUFFICIENT")]
    conflicts = [(inv, c) for inv in invs for c in inv["conflicts"]]
    cands = f["relationships"]["candidate_relationships"]
    out = [_sub("Evidence gaps, searches and conflicts")]
    if not (engine or gaps or searches or insufficient or conflicts or cands):
        return out + [_para("No missing evidence, evidence gaps, unsuccessful searches, conflicts or unverified relationships were reported.")]
    if engine:
        out.append(_para("Missing evidence recorded by the deterministic engine (details in 'Evidence completeness and source "
                         "inventory'): " + "; ".join(f"{i['item_id']} ({i['expected_evidence']}; exception {i['related_exception_id'] or 'none'})"
                                                     for i in engine) + "."))
    if searches:
        out += [_para("Searches that found nothing in the supplied data:"),
                _table(["Search", "Description", "Investigation"], [[s["search_id"], s["description"], inv["investigation_id"]] for inv, s in searches],
                       [1, 5, 2.5], [0, 2]),
                _notice("info", "'Not found in the supplied data' means the record was not in the dataset supplied; it does not mean "
                                "the record never existed.")]
    for label, sub in (("Gaps tied to engine missing evidence", "ENGINE_MISSING"), ("Gaps from searches that found nothing", "SEARCHED_NOT_FOUND"),
                       ("Additional gaps identified by the AI", "AI_IDENTIFIED")):
        items = [(inv, g) for inv, g in gaps if sub in g["subtypes"]]
        if items:
            out.append(_para(label + ":"))
            out += [{"type": "item", "kind": "gap", "heading": f"{g['ref']} ({inv['exception_id']})", "badge": f"EVIDENCE GAP - {sub}",
                     "fields": [("Description", g["description"]), ("Expected source", g["expected_source"]), ("Impact", g["impact"]),
                                ("Related IDs", _v(g["related_ids"]))]} for inv, g in items]
    if insufficient:
        out += [_para("Insufficient evidence (AI assessment):"),
                {"type": "bullets", "items": [f"{inv['exception_id']}: {inv['assessment']['overall_evidence_assessment']}" for inv in insufficient]}]
    if conflicts:
        out.append(_para("Conflicting evidence (no source is preferred; the conflict is reported as found):"))
        out += [{"type": "item", "kind": "conflict", "heading": f"{c['ref']} ({inv['exception_id']})", "badge": f"CONFLICT ({c['source']})",
                 "fields": [("Description", c["description"]), ("Compared evidence", _v(c["compared_evidence"], "deterministic conflict")),
                            ("Why the same measure and scope", _v(c["same_measure_and_scope"], "detected by deterministic rules")),
                            ("Evidence", _v(c["evidence_refs"]))]} for inv, c in conflicts]
    if cands:
        out += [_para("Unverified relationships:"),
                {"type": "bullets", "items": [f"{c['candidate_id']} ({c['exception_ids']}): UNVERIFIED - NOT EVIDENCE-BACKED; {c['basis']}" for c in cands]}]
    return out


# Dedicated block kinds (styled like assessment / hypothesis / rejected in the PDF): investigation hypotheses keep the
# 'hypothesis' kind for themselves, so the two are never mixed in the report structure.
GROUP_VERDICT_KIND = {"EVIDENCE_BACKED": "relationship_backed", "UNVERIFIED": "relationship_unverified",
                      "COINCIDENCE_REJECTED": "relationship_rejected"}
GROUP_VERDICT_TEXT = {"EVIDENCE_BACKED": "EVIDENCE-BACKED RELATIONSHIP - CAUSE NOT ESTABLISHED",
                      "UNVERIFIED": "UNVERIFIED RELATIONSHIP - NOT ESTABLISHED",
                      "COINCIDENCE_REJECTED": "COINCIDENCE - RELATIONSHIP REJECTED"}


COMMON_CAUSE_TEXT = {"EVIDENCE_BACKED": "COMMON CAUSE EVIDENCE-BACKED", "UNVERIFIED": "COMMON CAUSE UNVERIFIED",
                     "NOT_ESTABLISHED": "COMMON CAUSE NOT ESTABLISHED"}
RELATIONSHIP_VERDICT_TEXT = {"EVIDENCE_BACKED": "EVIDENCE-BACKED RELATIONSHIP", "UNVERIFIED": "UNVERIFIED RELATIONSHIP - NOT ESTABLISHED",
                             "COINCIDENCE_REJECTED": "COINCIDENCE - RELATIONSHIP REJECTED"}


def _assessment_badge(a):
    """Summary schema 1.3: the relationship and the common cause are two separate verdicts, so the badge states both. A 1.2
    assessment (no common_cause_status) keeps its exact earlier badge."""
    if a.get("common_cause_status") is None:
        return GROUP_VERDICT_TEXT.get(a["relationship_verdict"], a["relationship_verdict"])
    return (f"{RELATIONSHIP_VERDICT_TEXT.get(a['relationship_verdict'], a['relationship_verdict'])} - "
            f"{COMMON_CAUSE_TEXT.get(a['common_cause_status'], a['common_cause_status'])}")


def _group_assessment_blocks(o):
    """Closing-summary schema 1.2 group assessments. Absent (a summary written before 1.2): nothing is rendered, so stored
    packs re-render byte for byte. Present: every assessment is rendered (none can disappear), an empty list says so."""
    if o.get("group_assessments") is None:
        return []
    gas = o["group_assessments"]
    out = [_para("Group assessments (related exceptions and possible common causes; AI-generated, a common cause is always a "
                 "hypothesis):")]
    if not gas:
        return out + [_para("No investigation group or candidate relationship was supplied for this pack, so no relationship "
                            "between exceptions was assessed.")]
    for a in gas:
        out.append({"type": "item", "kind": GROUP_VERDICT_KIND.get(a["relationship_verdict"], "info"),
                    "heading": f"{a['group_id']}: {', '.join(a['exception_ids'])}",
                    "badge": _assessment_badge(a), "fields": [
                        ("Related exceptions", ", ".join(a["exception_ids"] + [x for x in a["related_exception_ids"]
                                                                               if x not in a["exception_ids"]])),
                        ("Relationship verdict", f"{a['relationship_verdict']} (confidence {a['confidence']})"),
                        *([("Common cause status (separate from the relationship)", a["common_cause_status"])]
                          if a.get("common_cause_status") is not None else []),
                        ("Likely common cause (HYPOTHESIS - NOT ESTABLISHED)", a["common_cause_hypothesis"]),
                        ("Supporting evidence (source records)", ", ".join(a["supporting_evidence"]) or "None cited."),
                        ("Contradicting evidence (source records)", ", ".join(a["contradicting_evidence"]) or "None cited."),
                        ("Missing evidence", "; ".join(a["missing_evidence"]) or "None stated."),
                        ("Recommended analyst action (not done)", a["analyst_action"]),
                        ("Rationale", a["rationale"])]})
    return out


def _proof_fields(p):
    if not p:
        return [("Engine proof", "None recorded.")]
    return [("Engine rule", p["rule"]), ("Faulty record", p["faulty_record"] or "Not identified by this rule."),
            ("Figures", "; ".join(f"{q['name']}: {q['value']}" + (f" [{q['record']}]" if q["record"] else "")
                                  for q in p["quantities"]) or "None."),
            ("Calculation", p["calculation"] or "None."), ("Result", p["result"]),
            ("Chronology", "; ".join(f"{c['date']}: {c['event']}" for c in p["chronology"]) or "None."),
            ("Effect on the requirement / resource", p["requirement_effect"] or "None stated."),
            ("Corroboration", "; ".join(p["corroboration"]) or "None."),
            ("Established by the engine", "; ".join(p["established"]) or "None."),
            ("NOT established", "; ".join(p["not_established"]) or "None stated."),
            ("Missing evidence", "; ".join(p["missing_evidence"]) or "None stated."),
            ("Limitations", "; ".join(p["limitations"]) or "None."),
            ("Records", ", ".join(p["records"]) or "None.")]


def _s_relationships(f):
    """Evidence-bearing relationships: each CONFIRMED engine relationship with its proof (the ENGINE's decision), followed by
    the AI's acknowledgement or challenge and the analyst's explanation, each in its own clearly labelled block. A challenge
    is never presented as changing the engine's status."""
    ra = f["relationship_assessments"]
    out = [_notice("info", ra["notice"])]
    if not ra["items"]:
        return out + [_para("The engine confirmed no relationship between exceptions in this pack.")]
    for it in ra["items"]:
        out.append(_sub(f"{it['relationship_id']}: {', '.join(it['exception_ids'])}"))
        out.append({"type": "item", "kind": "engine_relationship",
                    "heading": f"Engine decision - {it['relationship_type']}",
                    "badge": f"ENGINE: {it['engine_status']} (deterministic)",
                    "fields": [("Engine status", it["engine_status"]), ("Register status", it["register_status"])]
                    + _proof_fields(it["proof"])})
        d = it["ai_disposition_detail"]
        if d is None:
            out.append(_notice("warn", "AI assessment of this relationship: NOT AVAILABLE (no AI closing summary in this pack)."))
        elif d["disposition"] == "ACKNOWLEDGED":
            out.append({"type": "item", "kind": "relationship_backed", "heading": "AI assessment", "badge": "AI: ACKNOWLEDGED",
                        "fields": [("Reason", d["reason"]), ("Cited records", ", ".join(d["cited_evidence"]) or "None cited."),
                                   ("Missing evidence", "; ".join(d["missing_evidence"]) or "None stated."),
                                   ("Confidence", d["confidence"])]})
        else:
            out.append({"type": "item", "kind": "ai_challenge", "heading": "AI challenge - not accepted by the engine",
                        "badge": "AI: CHALLENGED - ENGINE STATUS UNCHANGED",
                        "fields": [("Reason", d["reason"]), ("Cited records", ", ".join(d["cited_evidence"])),
                                   ("Contradicting records", ", ".join(d["contradicting_evidence"])),
                                   ("Why the engine evidence is insufficient (AI view)", d["why_engine_evidence_insufficient"]),
                                   ("Missing evidence", "; ".join(d["missing_evidence"])),
                                   ("Confidence", d["confidence"]), ("Limitations", "; ".join(d["limitations"]))]})
        for a in it["common_cause_assessments"]:
            out.append(_para(f"Common-cause assessment ({a['group_id']}: {', '.join(a['exception_ids'])}): relationship "
                             f"{a['relationship_verdict']}; common cause {a.get('common_cause_status') or 'not stated'}. "
                             f"{a['common_cause_hypothesis']}"))
        n = it["analyst_explanation"]
        if d is not None and d["disposition"] == "CHALLENGED":
            out.append(_para("Analyst explanation: " + (f"{n['analyst_position']} - {n['analyst_explanation']}" if n
                                                        else "not recorded.")))
    return out


def _closing_summary_blocks(f):
    s = f["closing_summary"]
    if s["status"] == "NOT_REQUIRED":
        return []
    out = [_sub("AI-generated closing summary")]
    if s["status"] != "GENERATED":
        kind = _summary_kind(s["unavailable_reason"])
        why = SUMMARY_FAILURE_TEXT.get(kind, "the AI provider request did not complete" if kind else None)
        return out + [_notice("warn", ("An AI closing summary was attempted but is not included: " + why + "." if why else
                                       "The AI closing summary is unavailable.") +
                              " No substitute text has been written. The deterministic outcome summary in 'Executive outcome' is "
                              "unaffected. Technical details are in the technical appendix.")]
    o = s["output"]

    def items(xs):
        return [f"{x['text']} [{', '.join(x['source_refs'])}]" for x in xs] or ["None."]
    meta = s["model_metadata"]
    return out + [_notice("ai", f["statements"]["closing_summary_notice"]),
                  _para("Overall reconciliation position: " + o["overall_position"]), _para(o["summary_text"]),
                  _para("Most important evidence-supported observations:"), {"type": "bullets", "items": items(o["key_observations"])},
                  _para("Important unresolved exceptions:"),
                  {"type": "bullets", "items": [f"{u['exception_id']}: {u['text']}" for u in o["unresolved_items"]] or ["None."]},
                  *_group_assessment_blocks(o),
                  _para("Hypotheses that remain unverified:"), {"type": "bullets", "items": items(o["unverified_hypotheses"])},
                  _para("Material evidence gaps:"), {"type": "bullets", "items": items(o["evidence_gaps"])},
                  _para("Suggested next actions (recommendations, not completed actions):"), {"type": "bullets", "items": items(o["suggested_next_steps"])},
                  _para("Important limitations:"), {"type": "bullets", "items": o["limitations"] or ["None."]},
                  _para(f"Generated by {meta.get('provider')} {meta.get('model')} with {s['prompt_version']} at {s['created_at']}; "
                        f"input fingerprint {s['source_fingerprint']}.", "muted")]


# --------------------------------------------------------------------------------------------------------------- 7
def _analyst_items(f):
    out = []
    for e in f["exception_register"]:
        x, i = e["exception"], e["investigation"]
        r = i.get("analyst_review")
        if not r:
            continue
        common = [("Reviewer", f"{r['reviewer']['display_name']} ({r['reviewer']['user_id']})"), ("Reviewed at", r["decided_at"]),
                  ("Investigation reviewed", f"{r['investigation_id']} (findings {r['findings_sha256']}; review {r['analyst_review_id']}, "
                                             f"revision {r['revision']})"),
                  ("Exception status", "UNRESOLVED - an analyst review of an AI investigation does not resolve the exception")]
        if r["decision"] == "REJECT":
            out.append({"type": "item", "kind": "rejected", "heading": f"{x['exception_id']} - REJECTED BY ANALYST",
                        "badge": "REJECTED BY ANALYST", "fields": [
                            ("Analyst decision", "REJECTED BY ANALYST"),
                            ("Reason for rejection (exactly as recorded by the analyst)", r["rejection_reason"]),
                            ("Analyst comment (optional, separate from the reason)", _v(r.get("comment"), "none")),
                            ("Rejected investigation (reference kept for traceability)", r["investigation_id"]),
                            *common,
                            ("AI content", "Excluded from this report: the AI summary, findings, hypotheses and recommendations of this "
                                           "investigation are not reported and are not accepted evidence. The original investigation "
                                           "artefact is kept unchanged in the investigation record.")]})
        else:
            out.append({"type": "item", "kind": "accepted", "heading": f"{x['exception_id']} - AI investigation accepted by the analyst",
                        "badge": "ANALYST DECISION: ACCEPT", "fields": [
                            ("Analyst decision", "ACCEPT"), ("Analyst comment", _v(r.get("comment"), "none")), *common,
                            ("AI content", "Included in 'Exceptions and investigations', labelled AI-generated, with its citations.")]})
    return out


def _s_review(f):
    out = [_sub("Decisions on individual AI investigations")]
    items = _analyst_items(f)
    if items:
        out += [_notice("info", f["analyst_reviews"]["notice"])] + items
    elif not f["exception_register"]:
        out.append(_para("No exceptions were raised, so there was no AI investigation and no decision on an AI investigation."))
    else:
        out.append(_para("No AI investigation was selected for an analyst decision in this pack (see the AI investigation status "
                         "of each exception in 'Exceptions and investigations')."))
    out.append(_sub("Decision to generate the final audit pack"))
    r = f["human_review"]
    if r.get("status") == "PENDING_DECISION":
        return out + [_notice("bad", "Not yet decided. This is a preview: no decision to generate the final audit pack has been "
                                     "recorded, and a preview is not a final audit pack.")]
    out += [{"type": "kv", "pairs": [
        ("Decision", f"{r['decision']} - authorised assembly of this report" if r["decision"] == "GENERATE" else r["decision"]),
        ("Reviewer", f"{r['reviewer']['display_name']} ({r['reviewer']['user_id']})"),
        ("Decided at", r["decided_at"]), ("Comment", _v(r["comment"], "none")),
        ("Acknowledgement", ("accepted: " if r["acknowledgement_accepted"] else "NOT accepted: ") + r["acknowledgement_text"]),
        ("Closing summary at the time of the decision", r["closing_summary_status"] + (
            "; the reviewer acknowledged that it was unavailable" if r.get("acknowledged_summary_unavailable") else "")),
        ("Review decision ID", r["review_decision_id"])]},
        _notice("info", f["statements"]["generate_meaning"])]
    if r["prior_decisions"]:
        out += [_para("Earlier decisions on this review:"),
                _table(["Decision ID", "Decision", "Decided at", "Comment"], [[p["review_decision_id"], p["decision"], p["decided_at"], p["comment"]]
                                                                             for p in r["prior_decisions"]], [2, 1, 2, 4])]
    return out


# --------------------------------------------------------------------------------------------------------------- 8
def classify_limitations(f):
    """(main, appendix): lists of (category, text). Every limitation of the pack appears exactly once."""
    ai_used = ai_request_made(f)
    main, appendix = [], []
    for x in f["limitations"]:
        text = x["text"]
        cat = KNOWN_LIMITATIONS.get(text)
        if cat is None:
            cat = "ai" if x["source"] in ("INVESTIGATION",) or (x["source"] == "ASSEMBLER" and "AI investigation" in text) else "other"
        if cat == "ai" and not ai_used:
            appendix.append((cat, text))
        else:
            main.append((cat, text))
    return main, appendix


def _s_limitations(f):
    main, _ = classify_limitations(f)
    out = []
    for cat, title in CATEGORIES:
        texts = [t for c, t in main if c == cat]
        if texts:
            out += [_sub(title), {"type": "bullets", "items": texts}]
    types = ai_content_types(f)
    if types:
        out += [_sub("AI-generated content"),
                _notice("ai", f"AI-generated content in this report ({', '.join(types)}) was produced by a language model from the "
                              "supplied reconciliation and investigation records and validated by deterministic rules. It is an aid to "
                              "human review, not an audit or compliance opinion.")]
    elif not ai_request_made(f):
        out += [_sub("AI use"), _para("This report contains no AI-generated content, and no AI request was made in preparing it. "
                                      "AI limitations that do not apply are listed in the technical appendix.")]
    else:
        out += [_sub("AI use"), _para("This report contains no AI-generated content.")]
    return out


# --------------------------------------------------------------------------------------------------------------- 9
def _s_appendix(f):
    m, a, s = f["metadata"], f["audit_trail"], f["source_inventory"]
    cs = a["closing_summary"]
    out = [_sub("A.1 Pack identity and versions"),
           {"type": "kv", "pairs": [
               ("Final pack ID", m["final_pack_id"]), ("Version", str(m["version"])), ("Status", m["status"]),
               ("Generated at", m["generated_at"]), ("Supersedes", _v(m["supersedes_final_pack_id"], "none")),
               ("Final-pack schema", f["final_pack_schema_version"]), ("Report renderer", m["report_renderer"]),
               ("Assembler", a["assembler_version"]), ("Validation rules", a["validation_rules_version"]),
               ("Outcome summary rules", f["outcome_summary"]["version"]),
               ("Final content SHA-256", f["final_content_sha256"]),
               ("Source deterministic pack", f"{m['source_pack']['pack_id']} (schema {m['source_pack']['pack_schema_version']})"),
               ("Source pack content SHA-256", a["source_pack"]["pack_content_sha256"]),
               ("Review snapshot SHA-256", a["review_snapshot_sha256"]),
               ("Entity", f"{m['entity']['entity_id']} ({m['entity']['notice']})"), ("Asset pool", m["asset_pool_id"]),
               ("Currencies", _v(m["currency_scope"])), ("Reconciliation days", str(m["reconciliation_days_count"])),
               ("Accounts", "; ".join(f"{x['account_id']} ({x['currency']}, {x['account_class']})" for x in m["accounts"]))]},
           _sub("A.2 Source file hashes"),
           _table(["ID", "File", "SHA-256"], [[x["evidence_id"], x["source_file"], x["sha256"]] for x in s["files"]], [0.8, 4, 5.2], [0, 2]),
           _sub("A.3 Dataset and engine fingerprints"),
           {"type": "kv", "pairs": [("Dataset", s["dataset"]["dataset"]),
                                    ("Scenario (synthetic test label)", f"{s['dataset']['scenario_id']}: {_v(s['dataset']['scenario_name'], 'no name')}"),
                                    ("Baseline", _v(s["dataset"]["baseline"], "none")), ("Processing run", s["processing_run_id"])] +
                                   [(k.replace("_", " "), _v(v, "none")) for k, v in s["fingerprints"].items()]}]
    if a["investigations"]:
        out += [_sub("A.4 Included AI investigation artefacts"),
                _table(["Investigation", "Findings SHA-256", "Packet SHA-256", "Ledger SHA-256", "Versions"],
                       [[i["investigation_id"], i["findings_sha256"], i["evidence_packet_sha256"], _v(i["evidence_ledger_sha256"], "fixed mode"),
                         _v(i["versions"])] for i in a["investigations"]], [2, 2.6, 2.6, 2.6, 3], [0, 1, 2, 3])]
    if a.get("analyst_reviews"):
        out += [_sub("A.5 Analyst decisions on AI investigations (provenance)"),
                _table(["Review", "Investigation", "Decision", "Findings SHA-256", "Revision", "Decided at"],
                       [[r["analyst_review_id"], r["investigation_id"], r["decision"], r["findings_sha256"], str(r["revision"]), r["decided_at"]]
                        for r in a["analyst_reviews"]], [2, 2.4, 1, 3, 0.8, 2], [0, 1, 3])]
    rec = f["closing_summary"]
    pairs = [("Status", cs["status"]), ("Summary schema", rec["summary_schema_version"]), ("Prompt version", cs["prompt_version"]),
             ("Input fingerprint", cs["source_fingerprint"]), ("Record SHA-256", cs["closing_summary_sha256"])]
    if cs["status"] == "NOT_REQUIRED":
        pairs.append(("Provider request", "none: no AI closing summary was required (no exception, no included investigation)"))
    else:
        pairs.append(("Provider / model", f"{_v(cs['provider'], 'none recorded')} {_v(cs['model'], '')}".strip()))
    if cs["status"] == "UNAVAILABLE":
        pairs.append(("Failure (internal reason code)", rec["unavailable_reason"]))
        if rec.get("validation_findings"):
            pairs.append(("Validation findings", "; ".join(rec["validation_findings"])))
    out += [_sub("A.6 Closing-summary record"), {"type": "kv", "pairs": pairs}]
    _, technical = classify_limitations(f)
    if technical:
        out += [_sub("A.7 AI limitations that do not apply to this pack (no AI request was made)"),
                {"type": "bullets", "items": [t for _, t in technical]}]
    out += [_sub("A.8 Traceability"), _para(a["traceability"]),
            _para("Every limitation recorded in the pack is shown either in 'Limitations and disclosures' or in this appendix.", "muted")]
    return out
