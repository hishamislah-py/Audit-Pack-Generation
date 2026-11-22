"""Deterministic audit-pack assembly (design: docs/audit_pack/02).

Runs the existing engine once (D6) and assembles the pack from that run's in-memory outputs and the source records.
It copies values, counts records and builds identifiers and reverse indexes. It performs no financial calculation,
never changes an outcome, status or wording, and never reads answer keys or golden snapshots.
"""
import csv
import hashlib
import json
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from .. import schema
from ..period import resolve
from ..structure import read_csv
from ..validate import CONTROL_OF, Validator, case_status
from . import config, model, registry

PERIOD_FIELD = {fid: (rule.get("in_period") or rule.get("open_during_period", {}).get("start") or
                      rule.get("not_before_event") or [None])[0] for fid, rule in schema.PERIOD_RULES.items()}


class PackError(Exception):
    """Assembly cannot produce a trustworthy pack (generation FAILED)."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_sources(case_dir, period=None):
    """Source rows by (file name, line) and file ID by name; PDFs by name. File names are the period's canonical names
    (`period`, else the period the case declares: uc042lib.period.resolve)."""
    period = resolve(case_dir, period)  # also the policy version the case supplies, unless `period` selects one
    rows, fid_of, pk_of = {}, {}, {}
    for fid, (fname, _, cols) in period.csv_files.items():
        fid_of[fname], pk_of[fid] = fid, cols[0][0]
        p = Path(case_dir) / "source_data" / fname
        if p.exists():
            try:
                _, data = read_csv(p)
            except Exception:  # unreadable files are reported by the engine; nothing to index
                continue
            for r in data:
                rows[(fname, r["_line"])] = r
    for fid, v in period.pdf_files.items():
        fid_of[v[0]] = fid
    return rows, fid_of, pk_of


def parse_citations(text):
    """[(file_id, file_name, first_line or None, last_line or None)] for IN-xx citations in a text."""
    out = []
    for m in model.CITATION.finditer(text or ""):
        a = int(m.group(3)) if m.group(3) else None
        b = int(m.group(4)) if m.group(4) else a
        out.append((f"IN-{m.group(1)}", m.group(2), a, b))
    return out


def run_engine(case_dir, period=None, rules=None):
    v = Validator(case_dir, period, rules=rules)
    v.run()
    return v


def assemble(case_dir, v=None, period=None, rules=None):
    """Return (pack dict, engine run) for the case's reporting period (`period`, else the one the case declares).
    Raises PackError when inputs or engine results are unusable."""
    case_dir = Path(case_dir)
    if not (case_dir / "source_data").is_dir():
        raise PackError(f"case directory has no source_data: {case_dir}")
    v = v or run_engine(case_dir, period, rules)
    period = v.period
    rows, fid_of, pk_of = load_sources(case_dir, period)
    results = v.results
    rid = {model.result_id(r): r for r in results}
    if len(rid) != len(results):
        raise PackError("engine results are not uniquely identified by check_id|scope")
    exc_by_root = {x["root_cause"]: x for x in v.exceptions}

    # --- metadata -----------------------------------------------------------------------------------------
    manifest = []
    if (case_dir / "manifest.csv").exists():
        with open(case_dir / "manifest.csv", encoding="utf-8", newline="") as f:
            manifest = list(csv.DictReader(f))
    scenario = json.loads((case_dir / "scenario.json").read_text(encoding="utf-8")) if (case_dir / "scenario.json").exists() else {}
    scenario_id = scenario.get("scenario_id", "S01" if case_dir.name == "set_01_clean_baseline" else "CASE")
    accounts = []
    for (fname, line), r in rows.items():
        if fid_of[fname] == "IN-02":
            accounts.append({"account_id": r["account_id"], "account_class": r["account_class"], "currency": r["currency"],
                             "account_number_masked": r["account_number_masked"], "designation_name": r["designation_name"],
                             "evidence_id": f"IN-02:{r['account_id']}"})
    accounts.sort(key=lambda a: a["account_id"])
    currency_scope = sorted({a["currency"] for a in accounts if a["account_class"] == "RELEVANT_FUNDS_BANK"})

    # --- evidence register ---------------------------------------------------------------------------------
    files = []
    for m in manifest:
        st = v.state.get(m["file_id"])
        files.append({"evidence_id": m["file_id"], "source_file": m["relative_path"], "sha256": m["sha256"],
                      "record_count": m["record_count"], "record_unit": m["record_unit"], "requirement": m["requirement"],
                      "evidence_kind": m["evidence_kind"], "description": m["description"],
                      "availability": st[0] if st else "PRESENT",
                      "key_details": dict(sorted(v.pdf.get(m["file_id"], {}).items())) if m["format"] == "PDF" else {}})
    listed = {f["evidence_id"] for f in files}
    for fid in list(schema.CSV_FILES) + list(schema.PDF_FILES):  # unavailable files the manifest does not list
        if fid not in listed and fid in v.state:
            files.append({"evidence_id": fid, "source_file": "", "sha256": "", "record_count": "", "record_unit": "",
                          "requirement": "REQUIRED" if fid in schema.CSV_FILES or schema.PDF_FILES[fid][2] == "REQUIRED" else "OPTIONAL",
                          "evidence_kind": "", "description": (period.csv_files.get(fid) or period.pdf_files[fid])[1],
                          "availability": v.state[fid][0], "key_details": {}})
    files.sort(key=lambda f: f["evidence_id"])

    records = OrderedDict()
    cites_of = defaultdict(set)   # evidence_id -> result ids / exception ids citing it

    def resolve(text, owner):
        """Evidence IDs for the citations in a text; records are added to the register."""
        ids = []
        for fid, fname, a, b in parse_citations(text):
            if a is None:
                ids.append(fid)
                cites_of[fid].add(owner)
                continue
            for line in range(a, b + 1):
                r = rows.get((fname, line))
                if r is None:
                    raise PackError(f"citation does not resolve to a source record: {fid}:{fname}#L{line} (cited by {owner})")
                eid = f"{fid}:{r[pk_of[fid]]}"
                if eid not in records:
                    pf = PERIOD_FIELD.get(fid)
                    records[eid] = {"evidence_id": eid, "file_id": fid, "source_file": f"source_data/{fname}", "source_line": line,
                                    "primary_key": r[pk_of[fid]], "record_type": schema.CSV_FILES[fid][1],
                                    "business_date_field": pf or "", "business_date": r.get(pf, "") if pf else "",
                                    "account_id": r.get("account_id", ""), "currency": r.get("currency", "")}
                ids.append(eid)
                cites_of[eid].add(owner)
        return ids

    # --- control register ----------------------------------------------------------------------------------
    by_check = OrderedDict()
    for r in results:
        by_check.setdefault(r["check_id"], []).append(r)
    control_register = []
    result_index = {}
    for check, rs in by_check.items():
        entries = []
        for r in rs:
            x = exc_by_root.get(r["root_cause"]) if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE") else None
            e = {"result_id": model.result_id(r), "scope": r["scope"], "outcome": r["outcome"], "computed": r["computed"],
                 "reported": r["reported"], "evidence_status": r["evidence_status"], "structured": r["structured"],
                 "note": r["note"], "root_cause": r["root_cause"], "evidence_refs": r["evidence"],
                 "evidence_ids": resolve(r["evidence"], model.result_id(r)) if r["evidence"] != "all CSV inputs"
                 else sorted(schema.CSV_FILES),
                 "exception_id": x["exception_id"] if x else "", "investigation_group_id": x["investigation_group_id"] if x else ""}
            entries.append(e)
            result_index[e["result_id"]] = e
        counts = Counter(r["outcome"] for r in rs)
        control_register.append({"check_id": check, "control_code": rs[0]["control"], "control_name": registry.control_name(rs[0]["control"]),
                                 "result_counts": dict(sorted(counts.items())),
                                 "check_outcome": "FAILURES_PRESENT" if counts.get("FAIL") else "NOT_FULLY_ASSESSED"
                                 if counts.get("INSUFFICIENT_EVIDENCE") else "ALL_PASSED_OR_NOT_APPLICABLE",
                                 "related_exception_ids": sorted({e["exception_id"] for e in entries if e["exception_id"]}),
                                 "related_group_ids": sorted({e["investigation_group_id"] for e in entries if e["investigation_group_id"]}),
                                 "results": entries})

    for check, why in config.FAILURE_ONLY_CHECKS.items():  # ran, found nothing: listed, never shown as PASS
        if check not in by_check and v._gate.get(check):
            control = CONTROL_OF[check]
            control_register.append({"check_id": check, "control_code": control, "control_name": registry.control_name(control),
                                     "result_counts": {}, "check_outcome": "NO_FINDINGS",
                                     "check_outcome_note": f"The engine ran this check (evidence gate open) and it {why}; none were found.",
                                     "related_exception_ids": [], "related_group_ids": [], "results": []})

    # --- reconciliation summary (engine values only) -------------------------------------------------------
    def val(r, key=None):
        if r is None or r["outcome"] == "INSUFFICIENT_EVIDENCE":
            return config.NOT_AVAILABLE
        return r["structured"].get(key, config.NOT_AVAILABLE) if key else r["computed"]
    internal = []
    for r in by_check.get("C04-REQUIREMENT", []) + [x for x in by_check.get("C05-RESOURCE", []) if f"C04-REQUIREMENT|{x['scope']}" not in rid]:
        scope = r["scope"]
        if "/" not in scope:  # gated check ("all scopes"): no daily row exists
            continue
        c04, c05, c06 = rid.get(f"C04-REQUIREMENT|{scope}"), rid.get(f"C05-RESOURCE|{scope}"), rid.get(f"C06-DIFFERENCE|{scope}")
        d, ccy = scope.split("/")
        internal.append({"date": d, "currency": ccy,
                         "requirement": val(c04), "requirement_reported": c04["reported"] if c04 else config.NOT_AVAILABLE,
                         "requirement_outcome": c04["outcome"] if c04 else "", "requirement_composition": c04["note"] if c04 else "",
                         "item_a": val(c05, "item_a"), "items_b_to_d": val(c05, "items_b_to_d"), "resource": val(c05, "resource"),
                         "resource_outcome": c05["outcome"] if c05 else "",
                         "difference": val(c06), "difference_reported": c06["reported"] if c06 else config.NOT_AVAILABLE,
                         "difference_outcome": c06["outcome"] if c06 else "",
                         "result_ids": [model.result_id(x) for x in (c04, c05, c06) if x]})
    external = []
    for r in by_check.get("C07-BANK-EVIDENCE", []):
        scope = r["scope"]
        if "/" not in scope:
            continue
        c07, rc2, c08 = r, rid.get(f"RC2-LEDGER|{scope}"), rid.get(f"C08-DIFFERENCE|{scope}")
        d, acct = scope.split("/")
        external.append({"date": d, "account_id": acct, "currency": v.ccy_of.get(acct, ""),
                         "bank_balance": val(c07), "bank_balance_reported": c07["reported"], "bank_outcome": c07["outcome"],
                         "ledger_balance": val(rc2), "ledger_outcome": rc2["outcome"] if rc2 else "",
                         "difference": val(c08), "difference_reported": c08["reported"] if c08 else config.NOT_AVAILABLE,
                         "difference_outcome": c08["outcome"] if c08 else "", "evidence_status": c08["evidence_status"] if c08 else "",
                         "timing": c08["structured"] if c08 else {},
                         "result_ids": [model.result_id(x) for x in (c07, rc2, c08) if x]})
    opening = {"cash_book": [], "bank_first_statement": [], "client_snapshots": []}
    first_stmt = {}
    for (fname, line), r in rows.items():
        fid = fid_of[fname]
        if fid == "IN-10" and r["entry_type"] == "OPENING_BALANCE":
            opening["cash_book"].append({"evidence_id": f"IN-10:{r['ledger_entry_id']}", "account_id": r["account_id"],
                                         "posted_ts": r["posted_ts"], "amount": r["amount"], "dc_indicator": r["dc_indicator"],
                                         "currency": r["currency"]})
        elif fid == "IN-08" and r["statement_date"] < first_stmt.get(r["account_id"], ("9999", None))[0]:
            first_stmt[r["account_id"]] = (r["statement_date"], r)
        elif fid == "IN-03" and r["recon_date"] == period.previous_end.isoformat():
            opening["client_snapshots"].append({"evidence_id": f"IN-03:{r['snapshot_id']}", "client_id": r["client_id"],
                                                "currency": r["currency"], "balance": r["balance"], "as_at_ts": r["as_at_ts"]})
    for acct, (_, r) in sorted(first_stmt.items()):
        opening["bank_first_statement"].append({"evidence_id": f"IN-08:{r['statement_id']}", "account_id": acct,
                                                "statement_date": r["statement_date"], "opening_balance_amount": r["opening_balance_amount"],
                                                "opening_balance_dc": r["opening_balance_dc"], "currency": r["currency"]})
    for k in opening:
        opening[k].sort(key=lambda x: x["evidence_id"])

    # --- settlement register ---------------------------------------------------------------------------------
    settlement = []
    for (fname, line), b in rows.items():
        if fid_of[fname] != "IN-12":
            continue
        ar, br, tr = rid.get(f"C11-BATCH-ARITH|{b['batch_id']}"), rid.get(f"C11-BATCH-BANK|{b['batch_id']}"), rid.get(f"FUND-TOPUP|{b['batch_id']}")
        settlement.append({"evidence_id": f"IN-12:{b['batch_id']}",
                           **{k: b[k] for k in ("batch_id", "counterparty_type", "cycle_date", "settlement_date", "account_id", "currency",
                                                "direction", "gross_amount", "total_fees", "total_adjustments", "net_amount_reported",
                                                "expected_bank_reference")},
                           "lines_result": {"result_id": model.result_id(ar), "outcome": ar["outcome"], "computed": ar["computed"],
                                            "reported": ar["reported"]} if ar else {},
                           "bank_result": {"result_id": model.result_id(br), "outcome": br["outcome"], "computed": br["computed"],
                                           "reported": br["reported"], "structured": br["structured"],
                                           "bank_entry_ids": [e for e in result_index[model.result_id(br)]["evidence_ids"] if e.startswith("IN-09:")]} if br else {},
                           "fee_top_up_result": {"result_id": model.result_id(tr), "outcome": tr["outcome"]} if tr else {}})
    settlement.sort(key=lambda s: (s["settlement_date"], s["batch_id"]))

    # --- exceptions, groups, candidates ------------------------------------------------------------------------
    exc_rows = []
    for x in v.exceptions:
        members = [r for r in results if r["root_cause"] == x["root_cause"] and r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE")]
        e = dict(x)
        e["control_codes"] = sorted({r["control"] for r in members})
        e["affected_result_ids"] = [model.result_id(r) for r in members]
        e["evidence_ids"] = resolve(x["evidence"], x["exception_id"])
        exc_rows.append(e)
    groups = []
    for g in v.groups:
        e = dict(g)
        e["statement"] = config.GROUP_STATEMENT
        e["evidence_ids"] = resolve(g["links"], g["group_id"])
        groups.append(e)
    cands = []
    for c in v.candidates:
        e = dict(c)
        e["evidence_ids"] = resolve(c["evidence"], c["candidate_id"])
        cands.append(e)

    # --- missing evidence ----------------------------------------------------------------------------------------
    insuf = OrderedDict()
    for r in results:
        if r["outcome"] == "INSUFFICIENT_EVIDENCE":
            insuf.setdefault(r["root_cause"], []).append(r)
    missing = []
    for n, (root, rs) in enumerate(insuf.items(), 1):
        x = exc_by_root.get(root)
        missing.append({"item_id": f"MISS-{n:02d}", "expected_evidence": root,
                        "related_result_ids": [model.result_id(r) for r in rs],
                        "related_controls": sorted({r["control"] for r in rs}),
                        "related_exception_id": x["exception_id"] if x else "",
                        "completeness_impact": f"{len(rs)} check result(s) could not be assessed: " + ", ".join(sorted({r['check_id'] for r in rs})),
                        "value_shown": config.NOT_AVAILABLE})
    optional_missing = sorted(fid for fid, (st, _) in v.state.items() if fid in schema.PDF_FILES and schema.PDF_FILES[fid][2] == "OPTIONAL")

    # --- executive summary (separate status dimensions) ----------------------------------------------------------
    totals = Counter(r["outcome"] for r in results)
    required_unavailable = [fid for fid, (st, _) in v.state.items() if fid in schema.CSV_FILES or schema.PDF_FILES[fid][2] == "REQUIRED"]
    summary = {
        "generation_status": "GENERATED",
        "evidence_completeness": "INCOMPLETE" if totals.get("INSUFFICIENT_EVIDENCE") or required_unavailable else "COMPLETE",
        "control_outcomes": {"summary": "FAILURES_PRESENT" if totals.get("FAIL") else "NOT_FULLY_ASSESSED"
                             if totals.get("INSUFFICIENT_EVIDENCE") else "ALL_PASSED_OR_NOT_APPLICABLE",
                             "total_results": len(results), "by_outcome": dict(sorted(totals.items())),
                             "check_types": len(control_register),
                             "checks_no_findings": [c["check_id"] for c in control_register if c["check_outcome"] == "NO_FINDINGS"],
                             "checks_all_passed_or_not_applicable": [c["check_id"] for c in control_register if c["check_outcome"] == "ALL_PASSED_OR_NOT_APPLICABLE"],
                             "check_types_with_results": sum(1 for c in control_register if c["results"]),
                             "checks_with_failures": [c["check_id"] for c in control_register if c["check_outcome"] == "FAILURES_PRESENT"],
                             "checks_not_fully_assessed": [c["check_id"] for c in control_register if c["check_outcome"] == "NOT_FULLY_ASSESSED"],
                             "applicable_controls": sorted({c["control_code"] for c in control_register})},
        "exceptions": {"total": len(exc_rows), "open": sum(1 for x in exc_rows if x["status"] == "OPEN"),
                       "by_severity": dict(sorted(Counter(x["severity"] for x in exc_rows).items()))},
        "exception_review": "NONE" if not exc_rows else "AWAITING_HUMAN_REVIEW",
        "investigation_groups": len(groups), "candidate_relationships": len(cands),
        "missing_evidence_items": len(missing), "engine_case_status": case_status(v), "pack_review_status": "NOT_REVIEWED",
    }

    # --- audit trail -----------------------------------------------------------------------------------------------
    inputs = []
    for m in manifest:
        p = case_dir / m["relative_path"]
        actual = _sha(p) if p.exists() else ""
        inputs.append({"file_id": m["file_id"], "relative_path": m["relative_path"], "sha256_manifest": m["sha256"],
                       "sha256_actual": actual, "matches": actual == m["sha256"]})
    intake = []
    if (case_dir / "intake.csv").exists():
        with open(case_dir / "intake.csv", encoding="utf-8", newline="") as f:
            intake = [{k: r[k] for k in ("original_path", "sha256", "decision", "file_id", "reason")} for r in csv.DictReader(f)]
    engine_fp = model.engine_fingerprint()
    config_fp = model.configuration_fingerprint({k: list(v_) for k, v_ in registry.CONTROLS.items()}, v.rules.recorded())
    pack_fp = model.pack_layer_fingerprint()
    run = model.run_id(sorted((i["file_id"], i["sha256_actual"]) for i in inputs), engine_fp, config_fp, pack_fp)

    pack = {
        "metadata": {"pack_id": "", "pack_schema_version": config.PACK_SCHEMA_VERSION,
                     "reporting_period": {"period_id": period.period_id, "start": str(period.start), "end": str(period.end)},
                     "reconciliation_days": [str(d) for d in v.recon_days],
                     "entity": {"entity_id": config.ENTITY_ID, "notice": config.ENTITY_NOTICE},
                     "asset_pool_id": schema.POOL_ID, "currency_scope": currency_scope, "accounts": accounts,
                     "source_dataset": {"dataset": case_dir.name, "scenario_id": scenario_id, "scenario_name": scenario.get("name", ""),
                                        "baseline": scenario.get("baseline", ""), "baseline_manifest_sha256": scenario.get("baseline_manifest_sha256", "")},
                     "processing_run_id": run, "generation_status": "GENERATED",
                     "synthetic_notice": scenario.get("synthetic_notice", config.SYNTHETIC_NOTICE)},
        "executive_summary": summary,
        "reconciliation_summary": {"internal_by_currency_day": internal, "external_by_account_day": external,
                                   "opening_positions": opening,
                                   "client_balances_note": ("Client balances are represented by the C04 requirement (with its composition note) "
                                                            "and the CBAL results; the pack computes no client totals.")},
        "control_register": control_register,
        "evidence_register": {"files": files, "records": list(records.values())},
        "settlement_register": settlement,
        "exception_register": {"exceptions": exc_rows,
                               "statement": "No exceptions were raised for this period." if not exc_rows else
                               f"{len(exc_rows)} exception(s) raised; all OPEN and awaiting human review."},
        "investigation_group_register": {"groups": groups,
                                         "statement": "No investigation groups were formed." if not groups else config.GROUP_STATEMENT,
                                         "candidate_relationships": cands,
                                         "candidate_statement": "No candidate relationships were recorded." if not cands else
                                         "Candidate relationships are UNVERIFIED and NOT EVIDENCE-BACKED; they are not investigation groups."},
        "missing_evidence_register": {"items": missing, "optional_not_provided": optional_missing,
                                      "statement": "No required evidence is missing." if not missing else
                                      "Missing evidence is shown as 'not available'; it is never treated as zero."},
        "audit_trail": {"inputs": inputs, "intake": intake, "baseline_manifest_sha256": scenario.get("baseline_manifest_sha256", ""),
                        "engine_fingerprint": engine_fp, "configuration_fingerprint": config_fp, "pack_layer_fingerprint": pack_fp,
                        "correlation_version": groups[0]["correlation_version"] if groups else config.CORRELATION_VERSION,
                        "processing_outputs": {}, "pack_content_sha256": "", "review_events": [], "narrative": []},
        "statements": {"synthetic_notice": scenario.get("synthetic_notice", config.SYNTHETIC_NOTICE), "entity_notice": config.ENTITY_NOTICE,
                       "not_a_compliance_opinion": config.NOT_A_COMPLIANCE_OPINION, "limitations": config.LIMITATIONS},
    }
    for e in pack["evidence_register"]["records"]:
        e["cited_by"] = sorted(cites_of[e["evidence_id"]])
    for f in pack["evidence_register"]["files"]:
        f["cited_by_count"] = len(cites_of.get(f["evidence_id"], ()))
    return pack, v


def processing_outputs(v):
    """The engine run's outputs as CSV texts (same columns as the engine's own writer)."""
    from ..validate import CANDIDATE_COLS, EXC_COLS, GROUP_COLS
    import io

    def to_csv(cols, rows):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()
    rcols = ["check_id", "control", "scope", "outcome", "computed", "reported", "evidence", "note", "root_cause", "evidence_status", "structured"]
    return {"control_results.csv": to_csv(rcols, [dict(r, structured=json.dumps(r["structured"], sort_keys=True) if r["structured"] else "")
                                                  for r in v.results]),
            "exceptions.csv": to_csv(EXC_COLS, v.exceptions), "investigation_groups.csv": to_csv(GROUP_COLS, v.groups),
            "candidate_relationships.csv": to_csv(CANDIDATE_COLS, v.candidates),
            "document_details.csv": to_csv(["file_id", "label", "value"], [{"file_id": fid, "label": k, "value": val}
                                                                           for fid in sorted(v.pdf) for k, val in sorted(v.pdf[fid].items())])}


def finalise(pack, outputs):
    """Record processing-output hashes, then the content hash and pack ID (deterministic)."""
    pack["audit_trail"]["processing_outputs"] = {k: model.sha256_text(t) for k, t in sorted(outputs.items())}
    chash = model.content_hash(pack)
    pack["audit_trail"]["pack_content_sha256"] = chash
    pack["metadata"]["pack_id"] = model.pack_id(pack["metadata"]["source_dataset"]["scenario_id"],
                                                pack["metadata"]["reporting_period"]["period_id"], chash)
    return pack
