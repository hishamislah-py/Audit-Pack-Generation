"""Verify the validator's generated outputs against the source data, independently of the engine.

Reads each dataset's validation outputs (control_results.csv, exceptions.csv, investigation_groups.csv,
candidate_relationships.csv, VALIDATION_REPORT.md) and the trace command output, and checks them against the source
CSV files using the standalone helpers in tools/verify_datasets.py. The engine's calculation code is not imported.

Usage (from the uc042/ folder; run `python -m uc042lib.validate <dataset>` first):
    python tools/verify_outputs.py [--json out.json]
"""
import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATASETS = PROJECT / "uc042_dataset"
spec = importlib.util.spec_from_file_location("verify_datasets", HERE / "verify_datasets.py")
vd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vd)
LON = ZoneInfo("Europe/London")
REF = re.compile(r"IN-\d\d:([^#;\]\s,]+)(?:#L(\d+)(?:-L(\d+))?)?")
RECORD_ID = re.compile(r"\b(?:BE|LE|TX|ERL|ST|AQ|SB|CBS|UR|DL|IRR|SL)-[A-Z0-9-]+\b")


def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def verify(name, base=None):
    ds = Path(base or DATASETS) / name
    out = ds / "validation"
    findings = defaultdict(Counter)
    problems = defaultdict(list)

    def chk(area, ok, detail=""):
        findings[area]["OK" if ok else "PROBLEM"] += 1
        if not ok and len(problems[area]) < 10:
            problems[area].append(detail)

    results = read(out / "control_results.csv")
    exc = read(out / "exceptions.csv")
    groups = read(out / "investigation_groups.csv")
    cands = read(out / "candidate_relationships.csv")
    report = (ds / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    src = vd.load(ds)
    line_counts = {f: len(rows) + 1 for f, rows in src.items()}
    pdfs = {p.name for p in (ds / "supporting_documents").glob("*.pdf")}
    scenario_id = json.loads((ds / "scenario.json").read_text())["scenario_id"] if (ds / "scenario.json").exists() else "CASE"

    # O1 every cited row resolves to an existing file and line
    texts = [r["evidence"] for r in results] + [x["evidence"] for x in exc] + [g["links"] for g in groups] + [c["evidence"] for c in cands]
    for t in texts:
        for m in REF.finditer(t):
            f, a, b = m.group(1), m.group(2), m.group(3)
            if f in pdfs:
                chk("O1 citations resolve", a is None, m.group(0))
                continue
            ok = f in line_counts and (a is None or 2 <= int(a) <= line_counts[f] and (b is None or int(a) <= int(b) <= line_counts[f]))
            chk("O1 citations resolve", ok, m.group(0))

    # O2 displayed amounts equal independent recomputation from source
    t = src
    cal = [date.fromisoformat(r["calendar_date"]) for r in t["recon_calendar_2026-09.csv"] if r["is_recon_day"] == "true"]
    sga = {r["account_id"]: r["currency"] for r in t["account_inventory.csv"] if r["account_class"] == "RELEVANT_FUNDS_BANK"}
    acct_of = {c: a for a, c in sga.items()}
    point = lambda d: datetime.combine(d, time(17, 0), tzinfo=LON)
    cash = t["sga_cashbook_entries_2026-09.csv"]
    ledger = lambda a, d: sum((vd.cashbook(x["amount"], x["dc_indicator"]) for x in cash if x["account_id"] == a
                               and vd.ts(x["posted_ts"]) <= point(d)), vd.Z)
    bc = {(b["account_id"], vd.ts(b["as_at_ts"]).date()): vd.bank(b["balance_amount"], b["balance_dc_indicator"])
          for b in t["bank_balance_confirmations_2026-09.csv"]}
    snaps = defaultdict(list)
    for s in t["client_balance_snapshots_2026-09.csv"]:
        snaps[(s["recon_date"], s["currency"])].append(s)
    ureg = t["unallocated_register_2026-09.csv"]
    bats = {b["batch_id"]: b for b in t["settlement_batches_2026-09.csv"]}
    by_ref = defaultdict(list)
    for e in t["bank_statement_entries_2026-09.csv"]:
        by_ref[(e["account_id"], e["bank_reference"])].append(e)
    for r in results:
        if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] in ("FAIL", "NOT_APPLICABLE"):
            d, a = r["scope"].split("/")
            d = date.fromisoformat(d)
            chk("O2 amounts: C08 bank - ledger", Decimal(r["computed"]) == bc[(a, d)] - ledger(a, d), r["scope"])
        elif r["check_id"] == "C04-REQUIREMENT" and r["outcome"] in ("PASS", "FAIL"):
            d, c = r["scope"].split("/")
            dd = date.fromisoformat(d)
            req = sum((max(vd.Z, Decimal(s["balance"])) for s in snaps[(d, c)]), vd.Z) + sum(
                (Decimal(u["amount"]) for u in ureg if u["currency"] == c and vd.ts(u["receipt_ts"]) <= point(dd)
                 and (not u["allocated_ts"] or vd.ts(u["allocated_ts"]) > point(dd))), vd.Z)
            chk("O2 amounts: C04 requirement", Decimal(r["computed"]) == req, r["scope"])
        elif r["check_id"] == "C05-RESOURCE" and r["outcome"] in ("PASS", "FAIL"):
            d, c = r["scope"].split("/")
            chk("O2 amounts: C05 item A", r["computed"].startswith(f"item A {ledger(acct_of[c], date.fromisoformat(d))};"), r["scope"])
        elif r["check_id"] == "C11-BATCH-BANK" and r["outcome"] in ("PASS", "FAIL"):
            b = bats[r["scope"]]
            net = Decimal(b["net_amount_reported"]) * (1 if b["direction"] == "TO_FIRM" else -1)
            e = by_ref[(b["account_id"], b["expected_bank_reference"])][0]
            chk("O2 amounts: C11 batch net / bank amount", Decimal(r["computed"]) == net and Decimal(r["reported"]) == vd.bank(e["amount"], e["dc_indicator"]), r["scope"])

    # O3 exception records: identity, counts, amounts, currencies, dates, statuses
    ids = [x["exception_id"] for x in exc]
    chk("O3 exceptions: unique IDs", len(ids) == len(set(ids)), str(ids))
    chk("O3 exceptions: one per root cause", len({x["root_cause"] for x in exc}) == len(exc))
    by_root = defaultdict(list)
    for r in results:
        if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE"):
            by_root[r["root_cause"]].append(r)
    chk("O3 exceptions: every non-passing result belongs to an exception", set(by_root) == {x["root_cause"] for x in exc})
    for x in exc:
        chk("O3 exceptions: ID prefix matches scenario", x["exception_id"].startswith(f"EXC-{scenario_id}-"), x["exception_id"])
        chk("O3 exceptions: affected count", int(x["affected_results"]) == len(by_root[x["root_cause"]]), x["exception_id"])
        chk("O3 exceptions: OPEN, awaiting human review, no cause", x["status"] == "OPEN" and x["review_status"] == "AWAITING_HUMAN_REVIEW"
            and x["cause_category"] == "", x["exception_id"])
        if x["root_cause"].startswith("BANK_LEDGER_DIFFERENCE"):
            c08 = sorted(r["scope"] for r in by_root[x["root_cause"]] if r["check_id"] == "C08-DIFFERENCE")
            first = next(r for r in by_root[x["root_cause"]] if r["scope"] == c08[0])
            chk("O3 exceptions: amount, currency and dates match the results", x["amount"] == first["computed"]
                and x["currency"] == sga[x["account_id"]] and x["first_date"] == c08[0].split("/")[0] and x["last_date"] == c08[-1].split("/")[0],
                x["exception_id"])

    # O4 wording never overstates the evidence
    for x in exc:
        st = x["evidence_status"]
        if st == "NOT_EVIDENCED":
            chk("O4 wording: unexplained stays unexplained", x["category"].startswith("Unexplained") and "explained by timing" not in x["evidence_status_detail"], x["exception_id"])
        if st == "TIMING_EVIDENCED":
            chk("O4 wording: timing explained but not resolved", "awaiting human confirmation" in x["category"]
                and "not resolved" in x["evidence_status_detail"], x["exception_id"])
    for g in groups:
        chk("O4 wording: groups set no cause and stay open", g["status"] == "OPEN" and g["cause"] == "" and "cause" not in g["links"].lower(), g["group_id"])
    for c in cands:
        chk("O4 wording: candidates labelled unverified", "UNVERIFIED" in c["label"] and "NOT EVIDENCE-BACKED" in c["label"], c["candidate_id"])

    # O5 group and candidate cross-references
    exc_ids = set(ids)
    for g in groups:
        members = g["exception_ids"].split("; ")
        chk("O5 groups: members exist and point back", all(m in exc_ids for m in members)
            and all(x["investigation_group_id"] == g["group_id"] for x in exc if x["exception_id"] in members)
            and int(g["size"]) == len(members), g["group_id"])
    chk("O5 groups: every grouped exception's group exists", {x["investigation_group_id"] for x in exc} - {""} == {g["group_id"] for g in groups})
    for c in cands:
        a, b = c["exception_ids"].split("; ")
        ga = next(x["investigation_group_id"] for x in exc if x["exception_id"] == a)
        gb = next(x["investigation_group_id"] for x in exc if x["exception_id"] == b)
        chk("O5 candidates: not grouped together", not (ga and ga == gb), c["candidate_id"])

    # O6 no record from another scenario: every record ID shown exists in this dataset's sources
    known = {v for rows in src.values() for r in rows for v in r.values()}
    shown = set()
    for x in exc:
        shown |= set(RECORD_ID.findall(" ".join([x["root_cause"], x["related_records"], x["evidence_status_detail"], x["affected"]])))
    for g in groups:
        shown |= set(RECORD_ID.findall(g["links"].split("[")[0] if "[" in g["links"] else g["links"]))
    for c in cands:
        shown |= set(RECORD_ID.findall(c["detail"]))
    for r in results:
        if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE"):
            shown |= set(RECORD_ID.findall(r["note"] + " " + r["scope"]))
    for rid in sorted(shown):
        chk("O6 no foreign records", rid in known, rid)

    # O7 summary report agrees with the detailed outputs
    totals = Counter(r["outcome"] for r in results)
    m = re.search(r"\*\*Overall:\*\* (\d+) check results — (.+)", report)
    rep_tot = dict((k, int(v)) for v, k in [] ) if not m else {kv.split(" ")[0]: int(kv.split(" ")[1]) for kv in m.group(2).split(", ")}
    chk("O7 report: outcome totals", m and int(m.group(1)) == len(results) and rep_tot == dict(totals), str(m.group(0) if m else "missing"))
    chk("O7 report: exception IDs", re.findall(r"^### (EXC-[A-Z0-9]+-\d+)", report, re.M) == ids)
    chk("O7 report: group IDs", re.findall(r"^### (GRP-[A-Z0-9]+-\d+)", report, re.M) == [g["group_id"] for g in groups])
    chk("O7 report: answer key MATCH", "MATCH: results and exceptions are exactly as expected." in report)

    # O8 trace output agrees with exceptions.csv and groups
    for x in exc:
        tr = subprocess.run([sys.executable, "-m", "uc042lib.trace", x["exception_id"], "--set", str(ds)], cwd=PROJECT,
                            capture_output=True, text=True).stdout
        n = re.search(r"Affected results \((\d+)\)", tr)
        listed = len(re.findall(r"^  (?:FAIL|INSUFFICIENT_EVIDENCE) ", tr, re.M))
        chk("O8 trace: affected results agree", n and int(n.group(1)) == int(x["affected_results"]) == listed, x["exception_id"])
        chk("O8 trace: evidence status agrees", (f"evidence_status: {x['evidence_status']}" in tr) if x["evidence_status"] else "evidence_status:" not in tr, x["exception_id"])
    for g in groups:
        tr = subprocess.run([sys.executable, "-m", "uc042lib.trace", g["group_id"], "--set", str(ds)], cwd=PROJECT,
                            capture_output=True, text=True).stdout
        chk("O8 trace: group members agree", all(f"  {m}  " in tr for m in g["exception_ids"].split("; ")), g["group_id"])
    return {"checks": {k: dict(v) for k, v in sorted(findings.items())}, "problems": {k: v for k, v in problems.items() if v}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    names = list(dict.fromkeys(r["dataset"] for r in json.loads((DATASETS / "scenario_index.json").read_text())["scenarios"]))
    allres = {}
    for n in names:
        res = verify(n)
        allres[n] = res
        total = sum(sum(v.values()) for v in res["checks"].values())
        bad = sum(v.get("PROBLEM", 0) for v in res["checks"].values())
        print(f"== {n}: {total} output checks, {bad} problems")
        for k, v in res["problems"].items():
            print(f"   {k}: {v[:3]}")
    if a.json:
        Path(a.json).write_text(json.dumps(allres, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
