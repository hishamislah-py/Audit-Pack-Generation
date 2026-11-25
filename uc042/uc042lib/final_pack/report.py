"""Report view model: final_pack.json -> an ordered list of typed blocks. The HTML and PDF renderers lay out these blocks
and read nothing else, so the two reports cannot interpret the canonical JSON differently. Values are shown as stored;
missing explanatory fields are shown as not supplied, never filled in.

Block types: title, section (number, title, anchor), sub, para (cls), notice (cls), kv (pairs), table (headers, rows,
widths, code_cols), item (kind, heading, badge, fields), bullets (items), toc (entries), footer.
"""
import json

from ..pack.model import canonical

NOT_SUPPLIED = "Not supplied by this investigation (findings schema {v}); not back-filled."
SECTIONS = [("overview", "Audit overview"), ("executive", "Executive summary"), ("sources", "Source data inventory"),
            ("reconciliation", "Deterministic reconciliation results"), ("exceptions", "Exception register"),
            ("evidence", "Supporting evidence"), ("ai-summary", "AI investigation summary"),
            ("ai-assessments", "AI investigative assessments"), ("observations", "Confirmed observations"),
            ("hypotheses", "Hypotheses (not established)"), ("gaps", "Evidence gaps and conflicts"),
            ("next-steps", "Suggested next steps"), ("review", "Human review record"), ("limitations", "Limitations and exclusions"),
            ("provenance", "Audit trail and provenance"), ("closing-summary", "AI-Generated Closing Summary")]


def _v(x, default="-"):
    if x is None or x == "" or x == []:
        return default
    if isinstance(x, (list, tuple)):
        return ", ".join(str(i) for i in x)
    if isinstance(x, dict):
        return "; ".join(f"{k}: {v}" for k, v in x.items())
    return str(x)


def _table(headers, rows, widths=None, code_cols=(), layout="grid"):
    """layout is a presentation hint: 'records' lets the PDF show each row as a labelled card (dense evidence rows);
    the HTML table and the block's text are the same either way."""
    return {"type": "table", "headers": headers, "rows": [[_v(c) for c in r] for r in rows], "widths": widths or [1] * len(headers),
            "code_cols": list(code_cols), "layout": layout}


def _dict_table(items, keys):
    return _table(keys, [[i.get(k) for k in keys] for i in items])


def build_report(final):
    # Always render the canonical JSON form (sorted keys), so a report rendered from memory and one rendered from the stored
    # final_pack.json are byte-identical (verify_final_pack relies on this).
    final = json.loads(canonical(final))
    m = final["metadata"]
    preview = m["status"] == "PREVIEW"
    blocks = [{"type": "title", "text": f"UC-042 Final Audit Pack - {m['final_pack_id']}",
               "subtitle": f"Reporting period {m['reporting_period']['period_id']} ({m['reporting_period']['start']} to "
                           f"{m['reporting_period']['end']}) - version {m['version']} - {m['status']}"}]
    if preview:
        blocks.append({"type": "notice", "cls": "bad", "text": "PREVIEW - not a final audit pack. No human decision has been recorded."})
    blocks += [{"type": "notice", "cls": "info", "text": final["statements"]["synthetic_notice"]},
               {"type": "notice", "cls": "info", "text": final["statements"]["not_a_compliance_opinion"]},
               {"type": "toc", "entries": [(i + 1, t, a) for i, (a, t) in enumerate(SECTIONS)]}]
    for i, (anchor, title) in enumerate(SECTIONS):
        blocks.append({"type": "section", "number": i + 1, "title": title, "anchor": anchor})
        blocks += globals()[f"_s_{anchor.replace('-', '_')}"](final)
    blocks.append({"type": "footer", "text": f"Document provenance: final_content_sha256 {final['final_content_sha256']} - "
                                            f"source pack {m['source_pack']['pack_id']} ({m['source_pack']['pack_content_sha256']}) - "
                                            f"generated {m['generated_at']}"})
    return blocks


def block_texts(blocks):
    """Every piece of text the renderers must show (used by the consistency tests)."""
    out = []
    for b in blocks:
        t = b["type"]
        if t in ("title", "para", "notice", "footer", "sub"):
            out += [b["text"]] + ([b["subtitle"]] if b.get("subtitle") else [])
        elif t == "section":
            out.append(b["title"])
        elif t == "kv":
            out += [x for pair in b["pairs"] for x in pair]
        elif t == "table":
            out += b["headers"] + [c for r in b["rows"] for c in r]
        elif t == "item":
            out += [b["heading"], b["badge"]] + [x for pair in b["fields"] for x in pair]
        elif t == "bullets":
            out += b["items"]
    return [x for x in out if x]


# ---------------------------------------------------------------------------------------------------------------
def _s_overview(f):
    m = f["metadata"]
    c = m["completeness"]
    cov = c["investigation_coverage"]
    return [{"type": "kv", "pairs": [
        ("Final pack ID", m["final_pack_id"]), ("Version", str(m["version"])), ("Status", m["status"]),
        ("Generated at", m["generated_at"]), ("Supersedes", _v(m["supersedes_final_pack_id"], "none")),
        ("Reporting period", f"{m['reporting_period']['period_id']}: {m['reporting_period']['start']} to {m['reporting_period']['end']}"),
        ("Reconciliation days", str(m["reconciliation_days_count"])),
        ("Entity", f"{m['entity']['entity_id']} ({m['entity']['notice']})"), ("Asset pool", m["asset_pool_id"]),
        ("Currencies", _v(m["currency_scope"])),
        ("Accounts", "; ".join(f"{a['account_id']} ({a['currency']}, {a['account_class']})" for a in m["accounts"])),
        ("Source deterministic pack", f"{m['source_pack']['pack_id']} (schema {m['source_pack']['pack_schema_version']})"),
        ("Evidence completeness", c["evidence_completeness"]), ("Engine case status", c["engine_case_status"]),
        ("AI investigation coverage", f"{cov['included']} of {cov['exceptions']} exception(s) included; "
                                      f"{cov['not_investigated']} not investigated; {cov['excluded_by_analyst']} excluded by the analyst"),
        ("Closing summary", c["closing_summary"])]}]


def _s_executive(f):
    e = f["executive_summary"]
    d = e["deterministic"]
    out = [{"type": "para", "text": e["statement"]},
           {"type": "kv", "pairs": [
               ("Overall reconciliation status (engine)", f"{d['engine_case_status']}; control outcomes {d['control_outcomes']['summary']}"),
               ("Control results", f"{d['control_outcomes']['total_results']} results: {_v(d['control_outcomes']['by_outcome'])}"),
               ("Exceptions", f"{e['exceptions']['total']} total; {e['exceptions']['unresolved']} UNRESOLVED; by severity {_v(e['exceptions']['by_severity'], 'none')}"),
               ("AI investigations included", f"{e['investigations']['included']} ({_v(e['investigations']['modes'], 'none')})"),
               ("Evidence assessments", _v(e["investigations"]["by_assessment"], "none")),
               ("Outstanding evidence gaps", f"engine missing-evidence items {e['outstanding_evidence_gaps']['engine_missing_items']}; "
                                             f"AI-reported gaps {_v(e['outstanding_evidence_gaps']['by_subtype'])}")]}]
    out.append({"type": "sub", "text": "Key confirmed observations"})
    out.append(_table(["Reference", "Observation"], [[k["ref"], k["title"] or k["description"]] for k in e["key_confirmed_observations"]],
                      [2, 5], [0]) if e["key_confirmed_observations"] else {"type": "para", "text": "No confirmed observations."})
    out.append({"type": "sub", "text": "Material unexplained differences"})
    out.append(_table(["Exception", "Amount", "Currency", "Category", "Engine evidence status"],
                      [[x["exception_id"], x["amount"], x["currency"], x["category"], x["evidence_status"]]
                       for x in e["material_unexplained_differences"]], [2, 1, 1, 3, 2], [0])
               if e["material_unexplained_differences"] else {"type": "para", "text": "None reported by the engine."})
    return out


def _s_sources(f):
    s = f["source_inventory"]
    ds = s["dataset"]
    out = [_table(["ID", "File", "Description", "Records", "Requirement", "Availability", "SHA-256"],
                  [[x["evidence_id"], x["source_file"], x["description"], f"{x['record_count']} {x['record_unit']}", x["requirement"],
                    x["availability"], x["sha256"]] for x in s["files"]], [1, 3, 3, 1.2, 1.3, 1.3, 4], [0, 1, 6]),
           {"type": "kv", "pairs": [("Dataset", ds["dataset"]), ("Scenario (synthetic test label)", f"{ds['scenario_id']}: {ds['scenario_name']}"),
                                    ("Baseline", ds["baseline"]), ("Processing run", s["processing_run_id"])] +
                                   [(k.replace("_", " "), str(v)) for k, v in s["fingerprints"].items()]}]
    items = s["missing_evidence"]["items"]
    out.append({"type": "sub", "text": "Missing required evidence (deterministic engine)"})
    out.append(_table(["Item", "Expected evidence", "Impact", "Exception"],
                      [[i["item_id"], i["expected_evidence"], i["completeness_impact"], i["related_exception_id"]] for i in items],
                      [1, 3, 5, 1.5], [0]) if items else {"type": "para", "text": s["missing_evidence"]["statement"]})
    return out


def _s_reconciliation(f):
    r = f["reconciliation_results"]
    out = [{"type": "kv", "pairs": [("Control outcome summary", r["control_outcomes"]["summary"]),
                                    ("Results by outcome", _v(r["control_outcomes"]["by_outcome"]))]},
           {"type": "sub", "text": "Internal reconciliation by currency and day"},
           _table(["Date", "Ccy", "Requirement", "Resource", "Difference", "Reported", "Outcome"],
                  [[x["date"], x["currency"], x["requirement"], x["resource"], x["difference"], x["difference_reported"], x["difference_outcome"]]
                   for x in r["internal_by_currency_day"]]),
           {"type": "sub", "text": "External reconciliation by account and day"},
           _table(["Date", "Account", "Ledger", "Bank", "Difference", "Reported", "Outcome", "Evidence status"],
                  [[x["date"], x["account_id"], x["ledger_balance"], x["bank_balance"], x["difference"], x["difference_reported"],
                    x["difference_outcome"], x["evidence_status"]] for x in r["external_by_account_day"]], [1.2, 1.4, 1.3, 1.3, 1.1, 1.1, 1.3, 1.6]),
           {"type": "para", "text": r["client_balances_note"]},
           {"type": "sub", "text": "Opening positions"}]
    for name, items in r["opening_positions"].items():
        if items:
            keys = list(dict.fromkeys(k for i in items for k in i))
            out += [{"type": "para", "text": name.replace("_", " ")}, _dict_table(items, keys)]
    out += [{"type": "sub", "text": "Control checks"},
            _table(["Check", "Control", "Name", "Outcome", "Results"],
                   [[c["check_id"], c["control_code"], c["control_name"], c["check_outcome"], _v(c["result_counts"])] for c in r["control_checks"]],
                   [1.6, 1, 3, 2, 2]),
            {"type": "sub", "text": "Settlement batches"},
            _table(["Batch", "Type", "Date", "Account", "Ccy", "Net reported", "Lines", "Bank", "Top-up"],
                   [[b["batch_id"], b["counterparty_type"], b["settlement_date"], b["account_id"], b["currency"], b["net_amount_reported"],
                     b["lines_outcome"], b["bank_outcome"], b["fee_top_up_outcome"]] for b in r["settlements"]], [1.8, 1, 1.1, 1.2, 0.6, 1, 1, 1, 1])]
    return out


def _s_exceptions(f):
    reg = f["exception_register"]
    if not reg:
        return [{"type": "para", "text": "No exceptions were raised by the deterministic engine."}]
    out = [{"type": "notice", "cls": "bad", "text": "Every exception below remains UNRESOLVED. Neither AI investigation nor report "
                                                    "generation resolves an exception."}]
    for e in reg:
        x, i = e["exception"], e["investigation"]
        inv = (f"{i['investigation_id']} ({i['investigation_mode']}); assessment {i['overall_evidence_assessment']}"
               if i["inclusion"] == "INCLUDED" else f"{i['inclusion']}" + (f": {i['reason']}" if i["reason"] else ""))
        other = i["other_attempts"]
        out.append({"type": "item", "kind": "unresolved", "heading": f"{x['exception_id']} - {x['category']}",
                    "badge": e["resolution_status"], "fields": [
                        ("Dates", f"{x['first_date']} to {x['last_date']}"), ("Account / currency", f"{x['account_id']} / {x['currency']}"),
                        ("Amount", x["amount"]), ("Severity", x["severity"]), ("Root cause (engine key)", x["root_cause"]),
                        ("Deterministic status", f"{x['status']}; review {x['review_status']}; evidence {_v(x['evidence_status'], 'n/a')}"),
                        ("AI investigation", inv),
                        ("Other investigation attempts", f"ineligible {_v(other['published_ineligible'], 'none')}; eligible not selected "
                                                         f"{_v(other['published_not_selected'], 'none')}; unpublished {other['not_published']}")]})
    rel = f["relationships"]
    out += [{"type": "sub", "text": "Investigation groups and candidate relationships"},
            _table(["Group", "Exceptions", "Link types", "Links"], [[g["group_id"], g["exception_ids"], g["link_types"], g["links"]]
                                                                   for g in rel["investigation_groups"]], [1.3, 2, 1.2, 6], [0])
            if rel["investigation_groups"] else {"type": "para", "text": rel["group_statement"]},
            _table(["Candidate", "Exceptions", "Basis", "Detail", "Label"], [[c["candidate_id"], c["exception_ids"], c["basis"], c["detail"], c["label"]]
                                                                          for c in rel["candidate_relationships"]], [1.3, 2, 1.6, 4, 2], [0])
            if rel["candidate_relationships"] else {"type": "para", "text": rel["candidate_statement"]}]
    return out


def _s_evidence(f):
    idx = f["evidence_index"]
    if not idx:
        return [{"type": "para", "text": "No source records are cited by included AI content."}]
    return [{"type": "para", "text": "Cited source records only; full source files remain in the controlled dataset (hashes in section 3)."},
            _table(["Evidence ID", "Record type", "Source (file:line)", "File SHA-256", "Retrieved via / join key", "Key values", "Cited by"],
                   [[eid, e["record_type"], f"{e['source_file']}:{e['source_line']}", e["file_sha256"], f"{e['retrieved_via']} [{e['join_key']}]",
                     "; ".join(f"{k}={v}" for k, v in e["fields"].items() if v), _v(e["cited_by"])] for eid, e in idx.items()],
                   [2, 1.6, 2.2, 2.6, 2.4, 3.4, 2], [0, 2, 3, 6], layout="records")]


def _per_exception_note(f):
    return [{"type": "para", "text": f"{e['exception']['exception_id']}: {e['investigation']['inclusion']}" +
             (f" ({e['investigation']['reason']})" if e["investigation"]["reason"] else "")}
            for e in f["exception_register"] if e["investigation"]["inclusion"] != "INCLUDED"]


def _na(text, inv):
    return text if text is not None else NOT_SUPPLIED.format(v=inv["versions"]["findings_schema"])


def _s_ai_summary(f):
    out = []
    if not f["ai_investigations"]:
        out.append({"type": "para", "text": "No AI investigation is included in this pack."})
    for inv in f["ai_investigations"]:
        ev = inv["evidence_examined"]
        established = [f"{x['ref']}: {x['title'] or x['description']}" for x in inv["confirmed_findings"]] or ["No confirmed observations."]
        unknown = [f"{x['ref']}: {x['does_not_establish']}" for x in inv["confirmed_findings"] if x["does_not_establish"]]
        unknown += [f"{g['ref']}: {g['description']}" for g in inv["evidence_gaps"]]
        out += [{"type": "item", "kind": "info", "heading": f"{inv['exception_id']} - investigation {inv['investigation_id']}",
                 "badge": inv["investigation_mode"].upper() + " MODE", "fields": [
                     ("Model", f"{inv['provider']} {inv['model']} (prompt {inv['versions']['prompt']}, findings schema {inv['versions']['findings_schema']})"),
                     ("Investigated at", _v(inv["investigated_at"])), ("Route", _v(inv["route"])),
                     ("Evidence examined", f"{ev['records_initial']} records in the initial packet, {ev['records_final']} after tool retrieval; "
                                           f"files {_v(ev['source_files'])}; {ev['searches']} searches"),
                     ("Tool activity", f"{_v(ev['tool_calls_requested'], '0')} tool call(s) over {_v(ev['tool_rounds'], '0')} round(s): {_v(ev['tools_used'], 'none')}"),
                     ("Validation", f"{inv['validation']['status']}; re-validated under the current rules")]},
                {"type": "sub", "text": f"{inv['exception_id']}: what the investigation established"}, {"type": "bullets", "items": established},
                {"type": "sub", "text": f"{inv['exception_id']}: what remains unknown"},
                {"type": "bullets", "items": unknown or ["Nothing further was reported as unknown."]}]
    return out + _per_exception_note(f)


def _s_ai_assessments(f):
    out = [{"type": "notice", "cls": "ai", "text": "AI investigative assessments are the model's interpretation of the evidence. They are "
                                                  "not established facts; confirmed observations are listed separately in section 9."}]
    for inv in f["ai_investigations"]:
        a = inv["assessment"]
        out.append({"type": "item", "kind": "assessment", "heading": f"{inv['exception_id']} - {a['ref']}", "badge": "AI ASSESSMENT",
                    "fields": [("Assessment", a["summary"]), ("Overall evidence assessment", a["overall_evidence_assessment"])]})
    return out if f["ai_investigations"] else out + [{"type": "para", "text": "No AI investigation is included."}]


def _s_observations(f):
    out = [{"type": "para", "text": "Evidence-confirmed observations: validated findings whose citations resolve to the evidence ledger."}]
    any_ = False
    for inv in f["ai_investigations"]:
        for x in inv["confirmed_findings"]:
            any_ = True
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
                            ("Supporting evidence", _v(evidence)), ("Linked relationships", _v(rels)),
                            ("Related open items", _v(x["related_open_items"]))]})
    return out if any_ else out + [{"type": "para", "text": "No confirmed observations."}]


def _s_hypotheses(f):
    out = [{"type": "notice", "cls": "warn", "text": "Hypotheses are possible explanations that the evidence does not establish. "
                                                    "None is an established cause."}]
    hs = [(inv, h) for inv in f["ai_investigations"] for h in inv["hypotheses"]]
    for inv, h in hs:
        out.append({"type": "item", "kind": "hypothesis", "heading": f"{h['ref']} ({inv['exception_id']})", "badge": "HYPOTHESIS - NOT ESTABLISHED",
                    "fields": [("Possible explanation", h["description"]), ("Why it was considered", _na(h["rationale"], inv)),
                               ("Supporting evidence", _v(h["supporting_evidence"], "none")),
                               ("Contradicting evidence", _v(h["contradictory_evidence"], "none")), ("Limitations", h["limitations"]),
                               ("Verification status", h["verification_status"])]})
    return out if hs else out + [{"type": "para", "text": "No hypotheses were reported."}]


def _s_gaps(f):
    invs = f["ai_investigations"]
    engine = f["source_inventory"]["missing_evidence"]["items"]
    gaps = [(inv, g) for inv in invs for g in inv["evidence_gaps"]]
    out = [{"type": "sub", "text": "Missing evidence identified by the deterministic engine"},
           _table(["Item", "Expected evidence", "Exception"], [[i["item_id"], i["expected_evidence"], i["related_exception_id"]] for i in engine], [1, 4, 1.5])
           if engine else {"type": "para", "text": "None."},
           {"type": "sub", "text": "Searches that found nothing in the supplied data"},
           _table(["Search", "Description", "Investigation"], [[s["search_id"], s["description"], inv["investigation_id"]]
                                                                for inv in invs for s in inv["not_found_searches"]], [1, 5, 2.5], [0, 2])
           if any(inv["not_found_searches"] for inv in invs) else {"type": "para", "text": "None."},
           {"type": "para", "text": "'Not found in the supplied data' means the record was not in the dataset supplied; it does not mean the record never existed."}]
    for label, sub in (("Gaps tied to engine missing evidence", "ENGINE_MISSING"), ("Gaps from searches that found nothing", "SEARCHED_NOT_FOUND"),
                       ("Additional gaps identified by the AI", "AI_IDENTIFIED")):
        items = [(inv, g) for inv, g in gaps if sub in g["subtypes"]]
        out.append({"type": "sub", "text": label})
        out += [{"type": "item", "kind": "gap", "heading": f"{g['ref']} ({inv['exception_id']})", "badge": "EVIDENCE GAP",
                 "fields": [("Description", g["description"]), ("Expected source", g["expected_source"]), ("Impact", g["impact"]),
                            ("Related IDs", _v(g["related_ids"]))]} for inv, g in items] or [{"type": "para", "text": "None."}]
    insufficient = [inv for inv in invs if inv["assessment"]["overall_evidence_assessment"] in ("INSUFFICIENT_EVIDENCE", "PARTIALLY_SUFFICIENT")]
    out += [{"type": "sub", "text": "Insufficient evidence"},
            {"type": "bullets", "items": [f"{inv['exception_id']}: {inv['assessment']['overall_evidence_assessment']}" for inv in insufficient]}
            if insufficient else {"type": "para", "text": "None reported."},
            {"type": "sub", "text": "Conflicting evidence"}]
    conflicts = [(inv, c) for inv in invs for c in inv["conflicts"]]
    out += [{"type": "item", "kind": "conflict", "heading": f"{c['ref']} ({inv['exception_id']})", "badge": f"CONFLICT ({c['source']})",
             "fields": [("Description", c["description"]), ("Compared evidence", _v(c["compared_evidence"], "deterministic conflict")),
                        ("Why the same measure and scope", _v(c["same_measure_and_scope"], "detected by deterministic rules")),
                        ("Evidence", _v(c["evidence_refs"]))]} for inv, c in conflicts] or [{"type": "para", "text": "None reported."}]
    cands = f["relationships"]["candidate_relationships"]
    out += [{"type": "sub", "text": "Unverified relationships"},
            {"type": "bullets", "items": [f"{c['candidate_id']} ({c['exception_ids']}): UNVERIFIED - NOT EVIDENCE-BACKED; {c['basis']}" for c in cands]}
            if cands else {"type": "para", "text": "None recorded."}]
    return out


def _s_next_steps(f):
    out = [{"type": "notice", "cls": "info", "text": "Recommendations for further investigation, not completed actions."}]
    for inv in f["ai_investigations"]:
        out += [{"type": "item", "kind": "step", "heading": f"{s['ref']} ({inv['exception_id']})", "badge": "SUGGESTED",
                 "fields": [("Action", s["action"]), ("Rationale", s["rationale"]), ("Evidence needed", s["evidence_needed"])]}
                for s in inv["next_steps"]]
        if inv["open_questions"]:
            out += [{"type": "sub", "text": f"Open questions ({inv['exception_id']})"},
                    {"type": "bullets", "items": [f"{q['ref']}: {q['text']}" for q in inv["open_questions"]]}]
    return out if f["ai_investigations"] else out + [{"type": "para", "text": "No AI investigation is included."}]


def _s_review(f):
    r = f["human_review"]
    if r.get("status") == "PENDING_DECISION":
        return [{"type": "notice", "cls": "bad", "text": "Pending decision: " + r["note"]}]
    out = [{"type": "kv", "pairs": [("Decision", r["decision"]), ("Reviewer", f"{r['reviewer']['display_name']} ({r['reviewer']['user_id']})"),
                                    ("Decided at", r["decided_at"]), ("Comment", _v(r["comment"], "none")),
                                    ("Acknowledgement", ("accepted: " if r["acknowledgement_accepted"] else "NOT accepted: ") + r["acknowledgement_text"]),
                                    ("Review decision ID", r["review_decision_id"]), ("Review snapshot", r["snapshot_sha256"]),
                                    ("Closing summary reviewed", f"{r['closing_summary_status']} ({r['closing_summary_sha256']})")]},
           {"type": "notice", "cls": "info", "text": f["statements"]["generate_meaning"]}]
    if r["prior_decisions"]:
        out += [{"type": "sub", "text": "Earlier decisions"},
                _table(["Decision ID", "Decision", "Decided at", "Comment"], [[p["review_decision_id"], p["decision"], p["decided_at"], p["comment"]]
                                                                             for p in r["prior_decisions"]], [2, 1, 2, 4])]
    return out


def _s_limitations(f):
    return [{"type": "bullets", "items": [f"[{x['source']}] {x['text']}" for x in f["limitations"]]},
            {"type": "notice", "cls": "ai", "text": f["statements"]["ai_disclaimer"]}]


def _s_provenance(f):
    a, m = f["audit_trail"], f["metadata"]
    cs = a["closing_summary"]
    out = [{"type": "kv", "pairs": [("Final pack", f"{m['final_pack_id']} v{m['version']}"), ("Final content SHA-256", f["final_content_sha256"]),
                                    ("Original pack", a["source_pack"]["pack_id"]), ("Original pack content SHA-256", a["source_pack"]["pack_content_sha256"]),
                                    ("Review snapshot SHA-256", a["review_snapshot_sha256"]), ("Assembler", a["assembler_version"]),
                                    ("Validation rules", a["validation_rules_version"]),
                                    ("Closing summary", f"{cs['status']}; fingerprint {cs['source_fingerprint']}; record {cs['closing_summary_sha256']}; "
                                                        f"{_v(cs['provider'], 'no provider')} {_v(cs['model'], '')} ({cs['prompt_version']})")]}]
    if a["investigations"]:
        out.append(_table(["Investigation", "Findings SHA-256", "Packet SHA-256", "Ledger SHA-256", "Versions"],
                          [[i["investigation_id"], i["findings_sha256"], i["evidence_packet_sha256"], _v(i["evidence_ledger_sha256"], "fixed mode"),
                            _v(i["versions"])] for i in a["investigations"]], [2, 2.6, 2.6, 2.6, 3], [0, 1, 2, 3]))
    out.append({"type": "para", "text": "Traceability: " + a["traceability"]})
    return out


def _s_closing_summary(f):
    s = f["closing_summary"]
    out = [{"type": "notice", "cls": "ai", "text": f["statements"]["closing_summary_notice"]}]
    if s["status"] != "GENERATED":
        return out + [{"type": "notice", "cls": "warn", "text": f"The AI-generated closing summary is unavailable: {s['unavailable_reason']}. "
                                                                "No substitute text has been provided."}]
    o = s["output"]

    def items(xs):
        return [f"{x['text']} [{', '.join(x['source_refs'])}]" for x in xs] or ["None."]
    meta = s["model_metadata"]
    return out + [{"type": "sub", "text": "Overall reconciliation position"}, {"type": "para", "text": o["overall_position"]},
                  {"type": "sub", "text": "Summary"}, {"type": "para", "text": o["summary_text"]},
                  {"type": "sub", "text": "Most important evidence-supported observations"}, {"type": "bullets", "items": items(o["key_observations"])},
                  {"type": "sub", "text": "Important unresolved exceptions"},
                  {"type": "bullets", "items": [f"{u['exception_id']}: {u['text']}" for u in o["unresolved_items"]] or ["None."]},
                  {"type": "sub", "text": "Hypotheses that remain unverified"}, {"type": "bullets", "items": items(o["unverified_hypotheses"])},
                  {"type": "sub", "text": "Material evidence gaps"}, {"type": "bullets", "items": items(o["evidence_gaps"])},
                  {"type": "sub", "text": "Suggested next actions"}, {"type": "bullets", "items": items(o["suggested_next_steps"])},
                  {"type": "sub", "text": "Important limitations"}, {"type": "bullets", "items": o["limitations"] or ["None."]},
                  {"type": "para", "cls": "muted", "text": f"Generated by {meta.get('provider')} {meta.get('model')} with {s['prompt_version']} "
                                                           f"at {s['created_at']}; input fingerprint {s['source_fingerprint']}."}]
