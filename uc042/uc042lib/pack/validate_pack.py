"""Pack validation inside generation (docs/audit_pack/04, levels V1-V6 and V8). Any finding means FAILED."""
import re

from .. import schema
from ..period import PeriodConfig
from . import config, model

INSUF, FAIL = "INSUFFICIENT_EVIDENCE", "FAIL"
# Checks whose computed value is the balance or difference being assessed: when evidence is missing it must stay
# blank (never a substituted number). Other checks may carry a known source figure (e.g. the fee being evidenced).
# (DQ22/DQ23 are excluded: their computed value is the bank-statement side, which is present evidence, e.g. the bank
# opening balance when the cash-book opening is missing.)
BALANCE_CHECKS = {"C04-REQUIREMENT", "C05-RESOURCE", "C06-DIFFERENCE", "C07-BANK-EVIDENCE", "RC2-LEDGER", "C08-DIFFERENCE",
                  "BC-VS-EOD", "CBAL-ROLLFWD"}


def validate_pack(pack, v, rows=None):
    """Return a list of findings (empty = valid). `v` is the same engine run the pack was assembled from."""
    f = []

    def err(level, msg):
        if len(f) < 200:
            f.append(f"{level}: {msg}")

    # V1 structure
    for section, keys in model.REQUIRED.items():
        if section not in pack:
            err("V1", f"missing section {section}")
            continue
        for k in keys:
            if k not in pack[section]:
                err("V1", f"missing {section}.{k}")
    if f:
        return f
    # V2 references
    evid = {e["evidence_id"] for e in pack["evidence_register"]["files"]} | {e["evidence_id"] for e in pack["evidence_register"]["records"]}
    results = {e["result_id"]: e for c in pack["control_register"] for e in c["results"]}
    excs = {x["exception_id"]: x for x in pack["exception_register"]["exceptions"]}
    groups = {g["group_id"]: g for g in pack["investigation_group_register"]["groups"]}
    for e in results.values():
        for i in e["evidence_ids"]:
            if i not in evid:
                err("V2", f"result {e['result_id']} cites unknown evidence {i}")
        if e["exception_id"] and e["exception_id"] not in excs:
            err("V2", f"result {e['result_id']} points to unknown exception {e['exception_id']}")
        if e["investigation_group_id"] and e["investigation_group_id"] not in groups:
            err("V2", f"result {e['result_id']} points to unknown group")
    for x in excs.values():
        for i in x["evidence_ids"]:
            if i not in evid:
                err("V2", f"exception {x['exception_id']} cites unknown evidence {i}")
        for r in x["affected_result_ids"]:
            if r not in results:
                err("V2", f"exception {x['exception_id']} lists unknown result {r}")
        if x["investigation_group_id"] and x["investigation_group_id"] not in groups:
            err("V2", f"exception {x['exception_id']} points to unknown group")
    for g in groups.values():
        for m in g["exception_ids"].split("; "):
            if m not in excs:
                err("V2", f"group {g['group_id']} lists unknown exception {m}")
    for c in pack["investigation_group_register"]["candidate_relationships"]:
        for m in c["exception_ids"].split("; "):
            if m not in excs:
                err("V2", f"candidate {c['candidate_id']} lists unknown exception {m}")
    for m in pack["missing_evidence_register"]["items"]:
        for r in m["related_result_ids"]:
            if r not in results:
                err("V2", f"missing item {m['item_id']} lists unknown result {r}")
    if rows is not None:
        for e in pack["evidence_register"]["records"]:
            r = rows.get((e["source_file"].split("/", 1)[1], e["source_line"]))
            pk = schema.CSV_FILES[e["file_id"]][2][0][0]
            if r is None or r[pk] != e["primary_key"]:
                err("V2", f"evidence {e['evidence_id']} does not resolve to {e['source_file']}#L{e['source_line']}")
    # V3 value fidelity (byte-identical to the same engine run)
    eng = {model.result_id(r): r for r in v.results}
    for k, e in results.items():
        r = eng.get(k)
        if r is None:
            err("V3", f"result {k} is not an engine result")
            continue
        for fld in ("outcome", "computed", "reported", "evidence_status", "note", "root_cause"):
            if e[fld] != r[fld]:
                err("V3", f"{k}.{fld}: pack {e[fld]!r} != engine {r[fld]!r}")
        if e["structured"] != r["structured"]:
            err("V3", f"{k}.structured differs from engine")
        if e["evidence_refs"] != r["evidence"]:
            err("V3", f"{k}.evidence_refs differ from engine")
    for x in v.exceptions:
        p = excs.get(x["exception_id"])
        if p is None:
            err("V3", f"engine exception {x['exception_id']} missing from pack")
            continue
        for fld, val in x.items():
            if p.get(fld) != val:
                err("V3", f"{x['exception_id']}.{fld}: pack {p.get(fld)!r} != engine {val!r}")
    for g in v.groups:
        p = groups.get(g["group_id"])
        if p is None or any(p.get(k) != val for k, val in g.items()):
            err("V3", f"group {g['group_id']} differs from engine")
    pc = {c["candidate_id"]: c for c in pack["investigation_group_register"]["candidate_relationships"]}
    for c in v.candidates:
        if c["candidate_id"] not in pc or any(pc[c["candidate_id"]].get(k) != val for k, val in c.items()):
            err("V3", f"candidate {c['candidate_id']} differs from engine")
    na = config.NOT_AVAILABLE
    for row in pack["reconciliation_summary"]["internal_by_currency_day"]:
        scope = f"{row['date']}/{row['currency']}"
        for fld, check, key in (("requirement", "C04-REQUIREMENT", None), ("item_a", "C05-RESOURCE", "item_a"),
                                ("resource", "C05-RESOURCE", "resource"), ("difference", "C06-DIFFERENCE", None)):
            r = eng.get(f"{check}|{scope}")
            want = na if r is None or r["outcome"] == INSUF else (r["structured"].get(key, na) if key else r["computed"])
            if row[fld] != want:
                err("V3", f"internal {scope}.{fld}: {row[fld]!r} != engine {want!r}")
    for row in pack["reconciliation_summary"]["external_by_account_day"]:
        scope = f"{row['date']}/{row['account_id']}"
        for fld, check in (("bank_balance", "C07-BANK-EVIDENCE"), ("ledger_balance", "RC2-LEDGER"), ("difference", "C08-DIFFERENCE")):
            r = eng.get(f"{check}|{scope}")
            want = na if r is None or r["outcome"] == INSUF else r["computed"]
            if row[fld] != want:
                err("V3", f"external {scope}.{fld}: {row[fld]!r} != engine {want!r}")
    if rows is not None:
        by_id = {}
        for (fname, line), r in rows.items():
            for fid, (fn, _, cols) in PeriodConfig.from_id(pack["metadata"]["reporting_period"]["period_id"]).csv_files.items():
                if fn == fname:
                    by_id[f"{fid}:{r[cols[0][0]]}"] = r
        for s in pack["settlement_register"]:
            src = by_id.get(s["evidence_id"])
            for k in ("gross_amount", "total_fees", "total_adjustments", "net_amount_reported", "settlement_date", "currency", "direction"):
                if src is None or s[k] != src[k]:
                    err("V3", f"settlement {s['batch_id']}.{k} differs from source")
        for group in pack["reconciliation_summary"]["opening_positions"].values():
            for o in group:
                src = by_id.get(o["evidence_id"])
                for k, val in o.items():
                    if k != "evidence_id" and (src is None or src.get(k) != val):
                        err("V3", f"opening {o['evidence_id']}.{k} differs from source")
    # V4 counts
    s = pack["executive_summary"]
    if s["control_outcomes"]["total_results"] != len(results) or len(results) != len(v.results):
        err("V4", "result count mismatch")
    if s["exceptions"]["total"] != len(excs) or len(excs) != len(v.exceptions):
        err("V4", "exception count mismatch")
    if s["investigation_groups"] != len(groups) or s["candidate_relationships"] != len(pc) or s["missing_evidence_items"] != len(pack["missing_evidence_register"]["items"]):
        err("V4", "register count mismatch")
    for x in excs.values():
        if int(x["affected_results"]) != len(x["affected_result_ids"]):
            err("V4", f"{x['exception_id']} affected count mismatch")
    # V5 status semantics
    for x in excs.values():
        if x["status"] != "OPEN" or x["review_status"] != "AWAITING_HUMAN_REVIEW" or x["cause_category"]:
            err("V5", f"{x['exception_id']} shown as resolved, reviewed or with a cause")
        if x["evidence_status"] == "NOT_EVIDENCED" and (not x["category"].startswith("Unexplained") or "explained by timing" in x["evidence_status_detail"]):
            err("V5", f"{x['exception_id']} unexplained difference described as explained")
        if x["evidence_status"] == "TIMING_EVIDENCED" and "not resolved" not in x["evidence_status_detail"]:
            err("V5", f"{x['exception_id']} timing evidence described as resolved")
    for g in groups.values():
        if g["status"] != "OPEN" or g["cause"] or g["statement"] != config.GROUP_STATEMENT:
            err("V5", f"group {g['group_id']} presented as a cause or closed")
    grouped = {g["group_id"]: set(g["exception_ids"].split("; ")) for g in groups.values()}
    for c in pc.values():
        if "UNVERIFIED" not in c["label"] or any(set(c["exception_ids"].split("; ")) <= m for m in grouped.values()):
            err("V5", f"candidate {c['candidate_id']} not labelled unverified or treated as a group")
    if s["evidence_completeness"] not in ("COMPLETE", "INCOMPLETE") or s["generation_status"] != "GENERATED":
        err("V5", "status fields invalid")
    # V6 completeness
    listed = {c["check_id"]: c for c in pack["control_register"]}
    for check in schema.DEPENDS:
        if any(r["check_id"] == check for r in v.results):
            continue
        c = listed.get(check)
        if not (check in config.FAILURE_ONLY_CHECKS and v._gate.get(check) and c and c["check_outcome"] == "NO_FINDINGS" and not c["results"]):
            err("V6", f"no result for check {check}: control result missing")
    referenced = {r for m in pack["missing_evidence_register"]["items"] for r in m["related_result_ids"]}
    for k, e in results.items():
        if e["outcome"] == INSUF:
            if k not in referenced:
                err("V6", f"insufficient-evidence result {k} not in the missing-evidence register")
            if k.split("|")[0] in BALANCE_CHECKS and (e["computed"] or "") != "":
                err("V6", f"insufficient-evidence result {k} shows a value for evidence that is not available")
    for m in pack["missing_evidence_register"]["items"]:
        if m["value_shown"] != config.NOT_AVAILABLE:
            err("V6", f"missing item {m['item_id']} shows a value")
    for row in pack["reconciliation_summary"]["external_by_account_day"] + pack["reconciliation_summary"]["internal_by_currency_day"]:
        for k, val in row.items():
            if isinstance(val, str) and val not in (na, "") and k not in ("date", "currency", "account_id", "requirement_composition",
                                                                          "evidence_status") and not k.endswith("_outcome") and not model.MONEY.match(val):
                err("V6", f"reconciliation value {k}={val!r} is neither money nor 'not available'")
    for x in excs.values():
        if not x["evidence_ids"]:
            err("V6", f"exception {x['exception_id']} has no supporting evidence")
    # V8 provenance
    for i in pack["audit_trail"]["inputs"]:
        if not i["matches"]:
            err("V8", f"input {i['file_id']} hash differs from the manifest")
    for k in ("engine_fingerprint", "configuration_fingerprint", "pack_layer_fingerprint"):
        if not pack["audit_trail"][k]:
            err("V8", f"{k} missing")
    return f
