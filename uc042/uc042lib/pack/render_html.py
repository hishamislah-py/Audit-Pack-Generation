"""Render pack.html from the canonical pack only (no other input). Presentation; never the record."""
from html import escape


def _t(x):
    return escape(str(x))


def _table(cols, rows, cls=""):
    head = "".join(f"<th>{_t(c)}</th>" for c, _ in cols)
    body = "".join("<tr>" + "".join(f"<td>{_t(fn(r))}</td>" for _, fn in cols) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


CSS = """
:root{--bg:#ffffff;--fg:#1d1d1f;--muted:#5f6368;--line:#d9dce1;--panel:#f6f7f9;--ok:#1e7d3c;--warn:#a15c00;--bad:#b3261e;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#16181b;--fg:#e8eaed;--muted:#9aa0a6;--line:#3c4043;--panel:#202327;--ok:#7cc48f;--warn:#f0b35a;--bad:#f28b82;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px}h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:16px;margin:18px 0 6px}.muted{color:var(--muted)}.notice{background:var(--panel);border:1px solid var(--line);padding:10px 14px;border-radius:6px;margin:8px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.card b{display:block;font-size:13px;color:var(--muted);font-weight:500}.card span{font-size:17px;font-weight:600}
.scroll{overflow-x:auto;max-width:100%}table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}th,td{border:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{background:var(--panel)}details{margin:6px 0}summary{cursor:pointer;font-weight:600}code{font-size:12px;word-break:break-all}
"""


def render_html(pack):
    m, s = pack["metadata"], pack["executive_summary"]
    co, rec = s["control_outcomes"], pack["reconciliation_summary"]
    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           f"<title>{_t(m['pack_id'])}</title><style>{CSS}</style></head><body><main>",
           f"<h1>Audit pack {_t(m['pack_id'])}</h1>",
           f"<p class='muted'>Dataset {_t(m['source_dataset']['dataset'])} (scenario {_t(m['source_dataset']['scenario_id'])}) · "
           f"period {_t(m['reporting_period']['period_id'])} ({_t(m['reporting_period']['start'])} to {_t(m['reporting_period']['end'])}) · "
           f"processing run {_t(m['processing_run_id'])} · schema {_t(m['pack_schema_version'])}</p>",
           f"<div class='notice'>{_t(pack['statements']['synthetic_notice'])}</div>",
           f"<div class='notice'>{_t(pack['statements']['not_a_compliance_opinion'])}</div>",
           "<h2>Executive summary</h2><div class='grid'>"]
    for label, value in (("Generation status", s["generation_status"]), ("Evidence completeness", s["evidence_completeness"]),
                         ("Control outcomes", co["summary"]), ("Exception review", s["exception_review"]),
                         ("Results", f"{co['total_results']} across {co['check_types']} checks"),
                         ("Results by outcome", ", ".join(f"{k} {v}" for k, v in co["by_outcome"].items())),
                         ("Open exceptions", s["exceptions"]["open"]), ("Investigation groups", s["investigation_groups"]),
                         ("Candidate relationships (unverified)", s["candidate_relationships"]),
                         ("Missing evidence items", s["missing_evidence_items"]), ("Engine case status", s["engine_case_status"]),
                         ("Pack review status", s["pack_review_status"])):
        out.append(f"<div class='card'><b>{_t(label)}</b><span>{_t(value)}</span></div>")
    out.append("</div>")
    out.append(f"<h3>Scope</h3><p>Entity {_t(m['entity']['entity_id'])} <span class='muted'>({_t(m['entity']['notice'])})</span> · "
               f"pool {_t(m['asset_pool_id'])} · currencies {_t(', '.join(m['currency_scope']))} · "
               f"{len(m['reconciliation_days'])} reconciliation days</p>")
    out.append(_table([("Account", lambda a: a["account_id"]), ("Class", lambda a: a["account_class"]), ("Currency", lambda a: a["currency"]),
                       ("Number", lambda a: a["account_number_masked"]), ("Designation", lambda a: a["designation_name"]),
                       ("Evidence", lambda a: a["evidence_id"])], m["accounts"]))

    out.append("<h2>Reconciliation summary</h2><p class='muted'>Values are the deterministic engine's results; the pack calculates nothing.</p>")
    out.append("<details><summary>Internal reconciliation by currency and day</summary>" + _table(
        [("Date", lambda r: r["date"]), ("Ccy", lambda r: r["currency"]), ("Requirement", lambda r: r["requirement"]),
         ("Reported", lambda r: r["requirement_reported"]), ("Item A", lambda r: r["item_a"]), ("Resource", lambda r: r["resource"]),
         ("Difference", lambda r: r["difference"]), ("Outcomes", lambda r: f"{r['requirement_outcome']} / {r['resource_outcome']} / {r['difference_outcome']}")],
        rec["internal_by_currency_day"]) + "</details>")
    out.append("<details><summary>External reconciliation by account and day</summary>" + _table(
        [("Date", lambda r: r["date"]), ("Account", lambda r: r["account_id"]), ("Ccy", lambda r: r["currency"]),
         ("Bank", lambda r: r["bank_balance"]), ("Ledger", lambda r: r["ledger_balance"]), ("Difference", lambda r: r["difference"]),
         ("Outcome", lambda r: r["difference_outcome"]), ("Evidence status", lambda r: r["evidence_status"])],
        rec["external_by_account_day"]) + "</details>")
    op = rec["opening_positions"]
    out.append("<details><summary>Opening positions (source records)</summary>" +
               _table([("Evidence", lambda r: r["evidence_id"]), ("Account", lambda r: r["account_id"]), ("Amount", lambda r: r["amount"]),
                       ("D/C", lambda r: r["dc_indicator"]), ("Ccy", lambda r: r["currency"])], op["cash_book"]) +
               _table([("Evidence", lambda r: r["evidence_id"]), ("Account", lambda r: r["account_id"]),
                       ("Opening", lambda r: r["opening_balance_amount"]), ("D/C", lambda r: r["opening_balance_dc"]), ("Ccy", lambda r: r["currency"])],
                      op["bank_first_statement"]) +
               _table([("Evidence", lambda r: r["evidence_id"]), ("Client", lambda r: r["client_id"]), ("Balance", lambda r: r["balance"]),
                       ("Ccy", lambda r: r["currency"])], op["client_snapshots"]) +
               f"<p class='muted'>{_t(rec['client_balances_note'])}</p></details>")

    out.append("<h2>Control register</h2>")
    out.append(_table([("Check", lambda c: c["check_id"]), ("Control", lambda c: c["control_code"]), ("Name", lambda c: c["control_name"]),
                       ("Results", lambda c: ", ".join(f"{k} {v}" for k, v in c["result_counts"].items())), ("Check outcome", lambda c: c["check_outcome"]),
                       ("Exceptions", lambda c: ", ".join(c["related_exception_ids"]) or "none")], pack["control_register"]))
    for c in pack["control_register"]:
        out.append(f"<details><summary>{_t(c['check_id'])}: {len(c['results'])} result(s)</summary>" + _table(
            [("Result", lambda r: r["result_id"]), ("Outcome", lambda r: r["outcome"]), ("Computed", lambda r: r["computed"]),
             ("Reported", lambda r: r["reported"]), ("Evidence status", lambda r: r["evidence_status"]), ("Note", lambda r: r["note"]),
             ("Evidence", lambda r: "; ".join(r["evidence_ids"]))], c["results"]) + "</details>")

    out.append("<h2>Settlement register</h2>" + "<details><summary>"
               f"{len(pack['settlement_register'])} settlement batches</summary>" + _table(
        [("Batch", lambda b: b["batch_id"]), ("Date", lambda b: b["settlement_date"]), ("Ccy", lambda b: b["currency"]),
         ("Gross", lambda b: b["gross_amount"]), ("Fees", lambda b: b["total_fees"]), ("Adjustments", lambda b: b["total_adjustments"]),
         ("Net reported", lambda b: b["net_amount_reported"]), ("Lines", lambda b: b["lines_result"].get("outcome", "")),
         ("Bank", lambda b: b["bank_result"].get("outcome", "")), ("Bank amount", lambda b: b["bank_result"].get("reported", "")),
         ("Booking lag (business days)", lambda b: b["bank_result"].get("structured", {}).get("booking_lag_business_days", "")),
         ("Bank entry", lambda b: ", ".join(b["bank_result"].get("bank_entry_ids", [])))], pack["settlement_register"]) + "</details>")

    ex = pack["exception_register"]
    out.append(f"<h2>Exception register</h2><p>{_t(ex['statement'])}</p>")
    if ex["exceptions"]:
        out.append(_table([("Exception", lambda x: x["exception_id"]), ("Severity", lambda x: x["severity"]), ("Category", lambda x: x["category"]),
                           ("Controls", lambda x: ", ".join(x["control_codes"])), ("Account", lambda x: x["account_id"]),
                           ("Ccy", lambda x: x["currency"]), ("Amount", lambda x: x["amount"]), ("Dates", lambda x: f"{x['first_date']} to {x['last_date']}"),
                           ("Evidence status", lambda x: x["evidence_status"]), ("Status", lambda x: x["status"]),
                           ("Review", lambda x: x["review_status"]), ("Group", lambda x: x["investigation_group_id"]),
                           ("Affected results", lambda x: x["affected_results"])], ex["exceptions"]))
    gr = pack["investigation_group_register"]
    out.append(f"<h2>Investigation groups</h2><p>{_t(gr['statement'])}</p>")
    if gr["groups"]:
        out.append(_table([("Group", lambda g: g["group_id"]), ("Exceptions", lambda g: g["exception_ids"]), ("Link types", lambda g: g["link_types"]),
                           ("Links", lambda g: g["links"]), ("Status", lambda g: g["status"])], gr["groups"]))
    out.append(f"<h3>Candidate relationships</h3><p>{_t(gr['candidate_statement'])}</p>")
    if gr["candidate_relationships"]:
        out.append(_table([("Candidate", lambda c: c["candidate_id"]), ("Exceptions", lambda c: c["exception_ids"]), ("Label", lambda c: c["label"]),
                           ("Basis", lambda c: c["basis"]), ("Detail", lambda c: c["detail"])], gr["candidate_relationships"]))
    mi = pack["missing_evidence_register"]
    out.append(f"<h2>Missing evidence register</h2><p>{_t(mi['statement'])}</p>")
    if mi["items"]:
        out.append(_table([("Item", lambda x: x["item_id"]), ("Expected evidence", lambda x: x["expected_evidence"]),
                           ("Value", lambda x: x["value_shown"]), ("Exception", lambda x: x["related_exception_id"]),
                           ("Impact", lambda x: x["completeness_impact"])], mi["items"]))
    if mi["optional_not_provided"]:
        out.append(f"<p class='muted'>Optional documents not provided: {_t(', '.join(mi['optional_not_provided']))}</p>")

    ev = pack["evidence_register"]
    out.append(f"<h2>Evidence register</h2><p>{len(ev['files'])} files; {len(ev['records'])} cited source records.</p>")
    out.append(_table([("Evidence", lambda f: f["evidence_id"]), ("File", lambda f: f["source_file"]), ("Requirement", lambda f: f["requirement"]),
                       ("Availability", lambda f: f["availability"]), ("Records", lambda f: f"{f['record_count']} {f['record_unit']}"),
                       ("SHA-256", lambda f: f["sha256"])], ev["files"]))
    out.append("<details><summary>Cited source records</summary>" + _table(
        [("Evidence", lambda r: r["evidence_id"]), ("File", lambda r: r["source_file"]), ("Line", lambda r: r["source_line"]),
         ("Business date", lambda r: r["business_date"]), ("Account", lambda r: r["account_id"]), ("Ccy", lambda r: r["currency"]),
         ("Cited by", lambda r: len(r["cited_by"]))], ev["records"]) + "</details>")

    at = pack["audit_trail"]
    out.append("<h2>Audit trail</h2>" + _table([("Item", lambda r: r[0]), ("Value", lambda r: r[1])], [
        ("Pack content SHA-256", at["pack_content_sha256"]), ("Processing run", m["processing_run_id"]),
        ("Engine fingerprint", at["engine_fingerprint"]), ("Configuration fingerprint", at["configuration_fingerprint"]),
        ("Pack-layer fingerprint", at["pack_layer_fingerprint"]),
        ("Correlation version", at["correlation_version"]), ("Baseline manifest SHA-256", at["baseline_manifest_sha256"] or "(baseline)"),
        ("Review events", "none (human review not implemented)"), ("Narrative", "none (AI narrative not implemented)")]))
    out.append(_table([("Input", lambda i: i["file_id"]), ("Path", lambda i: i["relative_path"]), ("SHA-256", lambda i: i["sha256_actual"]),
                       ("Matches manifest", lambda i: i["matches"])], at["inputs"]))
    out.append(_table([("Processing output", lambda r: r[0]), ("SHA-256", lambda r: r[1])], sorted(at["processing_outputs"].items())))
    out.append("<h2>Limitations</h2><ul>" + "".join(f"<li>{_t(x)}</li>" for x in pack["statements"]["limitations"]) + "</ul>")
    out.append("</main></body></html>\n")
    return "".join(out)
