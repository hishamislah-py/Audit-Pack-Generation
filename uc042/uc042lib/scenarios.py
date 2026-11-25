"""Build the two approved scenario datasets from the validated clean baseline.

Usage (from the uc042/ folder):
    python -m uc042lib.scenarios          # builds both scenarios next to the baseline

Each scenario is: a copy of the baseline + an explicit list of record operations (mutations.json),
each identified by primary key and, for field changes, carrying the old value it expects.
The baseline is never modified: its SHA-256 manifest is checked before and after every build.
Expected outcomes (answer_key.json) are derived from the mutation plan and the baseline files,
not from the validator.
"""
import csv
import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path

from . import schema
from .generate import DEFAULT_OUT as BASELINE, write_manifest
from .money import fmt

DATASETS = BASELINE.parent
S02_DIR = DATASETS / "scn_S02_missing_eur_statement"
S05_DIR = DATASETS / "scn_S05_unexplained_gbp_difference"
NOT_COPIED = {"validation", "VALIDATION_REPORT.md", "answer_key.json"}
SYNTHETIC_NOTICE = ("ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are "
                    "illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.")


def read(root, fid):
    with open(Path(root) / "source_data" / schema.CSV_FILES[fid][0], encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(root, fid, rows):
    with open(Path(root) / "source_data" / schema.CSV_FILES[fid][0], "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def apply(root, ops):
    """Apply operations in order. Fails loudly if a target record or old value is not as expected."""
    for op in ops:
        fid, pk = op["file_id"], schema.columns(op["file_id"])[0]
        rows = read(root, fid)
        idx = {r[pk]: i for i, r in enumerate(rows)}
        if op["op"] == "delete_record":
            if op["key"] not in idx:
                raise ValueError(f"delete target not found: {op}")
            rows.pop(idx[op["key"]])
        elif op["op"] == "set_field":
            r = rows[idx[op["key"]]]
            if r[op["field"]] != op["old"]:
                raise ValueError(f"old value mismatch: {op} (found {r[op['field']]})")
            r[op["field"]] = op["new"]
        elif op["op"] == "add_record":
            rec = op["record"]
            if rec[pk] in idx:
                raise ValueError(f"record already exists: {rec[pk]}")
            after = op.get("insert_after")
            rows.insert(idx[after] + 1 if after else len(rows), rec)
        else:
            raise ValueError(f"unknown op {op['op']}")
        write(root, fid, rows)


def baseline_hashes():
    with open(BASELINE / "manifest.csv", encoding="utf-8") as f:
        return [(r["file_id"], r["sha256"]) for r in csv.DictReader(f)]


def build(out, scenario, ops, answer_key, notes):
    before = baseline_hashes()
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(BASELINE, out, ignore=lambda d, names: [n for n in names if n in NOT_COPIED])
    apply(out, ops)
    write_manifest(out)
    scenario = dict(scenario, baseline="set_01_clean_baseline",
                    baseline_manifest_sha256=hashlib.sha256((BASELINE / "manifest.csv").read_bytes()).hexdigest(),
                    synthetic_notice=SYNTHETIC_NOTICE)
    notes = f"> {SYNTHETIC_NOTICE}\n\n" + notes
    (out / "scenario.json").write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    (out / "mutations.json").write_text(json.dumps(ops, indent=2) + "\n", encoding="utf-8")
    (out / "answer_key.json").write_text(json.dumps(answer_key, indent=2) + "\n", encoding="utf-8")
    (out / "SCENARIO_NOTES.md").write_text(notes, encoding="utf-8")
    if baseline_hashes() != before:
        raise RuntimeError("baseline changed during scenario build")
    return out


# --- Scenario A: S02 missing EUR bank evidence on 15 Sep 2026 -----------------------------------
def s02_definition():
    acct, ymd, iso = "SGA-EUR-01", "20260915", "2026-09-15"
    bc_id, eod_id = f"ST-{acct}-{ymd}-1700", f"ST-{acct}-{ymd}-EOD"
    entries = [e for e in read(BASELINE, "IN-09") if e["statement_id"] == eod_id]
    ops = [{"op": "delete_record", "file_id": "IN-07", "key": bc_id, "why": "17:00 confirmation not provided"},
           {"op": "delete_record", "file_id": "IN-08", "key": eod_id, "why": "end-of-day statement not provided"}]
    ops += [{"op": "delete_record", "file_id": "IN-09", "key": e["bank_entry_id"], "why": "entry of the missing statement"} for e in entries]
    # Expected outcomes, from the mutation plan section 3, using baseline records
    e2e = {e["end_to_end_ref"] for e in entries if e["end_to_end_ref"]}
    cash = [c for c in read(BASELINE, "IN-10") if c["account_id"] == acct and c["posted_ts"].startswith(iso)]
    direct = [t for t in read(BASELINE, "IN-11") if t["txn_type"] in ("LOAD_BANK", "REDEMPTION") and t["payment_reference"] in e2e]
    I = "INSUFFICIENT_EVIDENCE"
    expected = [["C14-COVER", f"IN-07 {iso}/{acct}", I], ["C14-COVER", f"IN-08 {iso}/{acct}", I],
                ["C07-BANK-EVIDENCE", f"{iso}/{acct}", I], ["C08-DIFFERENCE", f"{iso}/{acct}", I],
                ["DQ22-CONTINUITY", f"ST-{acct}-20260916-EOD", I],
                ["C11-BATCH-BANK", "SB-EUR-20260915", I], ["C11-BATCH-BANK", "AQ-EUR-20260915", I],
                ["FUND-TOPUP", "AQ-EUR-20260915", I]]
    expected += [["CASH-BANK-LINK", c["ledger_entry_id"], I] for c in cash]
    expected += [["RC4-DIRECT", t["txn_id"], I] for t in direct]
    root = f"MISSING_BANK_EVIDENCE|{acct}|{iso}"
    key = {"scenario_id": "S02", "description": "Missing EUR bank evidence for 15 Sep 2026",
           "non_passing_results": sorted(expected),
           "exceptions": [{"exception_id": "EXC-S02-01", "severity": "Critical", "root_cause": root, "affected_results": len(expected)}],
           "evidence_statuses": {}, "investigation_groups": [], "candidate_relationships": [],
           "must_hold": ["No bank balance is substituted for 15 Sep EUR (C07 computed value is empty)",
                         "Internal reconciliation for EUR 15 Sep passes (ledger values unaffected)",
                         "External reconciliation for SGA-EUR-01 from 16 Sep passes"]}
    scenario = {"scenario_id": "S02", "name": "Missing EUR bank evidence, 15 Sep 2026", "derived_from": "set_01_clean_baseline",
                "plan": "docs/UC042_SCENARIO_MUTATION_PLAN.md section 3"}
    notes = f"""# Scenario S02 — Missing EUR bank evidence, 15 Sep 2026 (synthetic)

**Changes vs the clean baseline** (exact list in `mutations.json`):

- Removed the 17:00 balance confirmation `{bc_id}` (IN-07).
- Removed the end-of-day statement `{eod_id}` (IN-08).
- Removed its {len(entries)} entries (IN-09).

**Kept unchanged on purpose:**

- `ERL-{acct}-{ymd}` (IN-06) still cites `{bc_id}` and still reports a bank balance. The claim stays; its support is gone.
- The cash book (IN-10), transactions, settlement batches and lines.
- The own-funds account statement for 15 Sep.

**Expected result:** one Critical exception, `EXC-S02-01` (missing bank evidence). It groups {len(expected)} INSUFFICIENT_EVIDENCE results; full list in `answer_key.json`. No bank balance is substituted and nothing passes for SGA-EUR-01 external reconciliation on 15 Sep. The internal reconciliation for EUR on 15 Sep still passes because it uses ledger values. The reviewer decides on CASS 15.8.60R(4) notification; the system does not.
"""
    return scenario, ops, key, notes


# --- Scenario B: S05 unexplained GBP difference of 812.40 from 17 Sep 2026 -----------------------
def s05_definition():
    acct, amt = "SGA-GBP-01", Decimal("812.40")
    days = [r["calendar_date"] for r in read(BASELINE, "IN-01") if r["is_recon_day"] == "true" and r["calendar_date"] >= "2026-09-17"]
    sub = lambda v: fmt(Decimal(v) - amt)
    eod = {r["statement_id"]: r for r in read(BASELINE, "IN-08")}
    bc = {r["statement_id"]: r for r in read(BASELINE, "IN-07")}
    erl = {r["ext_recon_id"]: r for r in read(BASELINE, "IN-06")}
    first_stmt = f"ST-{acct}-20260917-EOD"
    entries = [e for e in read(BASELINE, "IN-09") if e["statement_id"] == first_stmt]
    insert_after = [e for e in entries if e["booking_ts"] <= "2026-09-17T15:20:00+01:00"][-1]["bank_entry_id"]
    ops = [{"op": "add_record", "file_id": "IN-09", "insert_after": insert_after, "why": "unexplained debit on the bank statement",
            "record": {"bank_entry_id": "BE-GBP-0917-X01", "statement_id": first_stmt, "account_id": acct, "booking_date": "2026-09-17",
                       "booking_ts": "2026-09-17T15:20:00+01:00", "value_date": "2026-09-17", "amount": "812.40", "dc_indicator": "D",
                       "currency": "GBP", "bank_reference": "SETTLE 0417", "end_to_end_ref": "", "counterparty_name": "",
                       "narrative_text": "SETTLE 0417"}}]
    for i, iso in enumerate(days):
        ymd = iso.replace("-", "")
        s = eod[f"ST-{acct}-{ymd}-EOD"]
        for fld in (["closing_balance_amount"] if i == 0 else ["opening_balance_amount", "closing_balance_amount"]):
            assert s[fld.replace("amount", "dc")] == "C"
            ops.append({"op": "set_field", "file_id": "IN-08", "key": s["statement_id"], "field": fld, "old": s[fld], "new": sub(s[fld])})
        if i == 0:
            ops.append({"op": "set_field", "file_id": "IN-08", "key": s["statement_id"], "field": "entry_count",
                        "old": s["entry_count"], "new": str(int(s["entry_count"]) + 1)})
        b = bc[f"ST-{acct}-{ymd}-1700"]
        ops.append({"op": "set_field", "file_id": "IN-07", "key": b["statement_id"], "field": "balance_amount", "old": b["balance_amount"], "new": sub(b["balance_amount"])})
        e = erl[f"ERL-{acct}-{ymd}"]
        ops.append({"op": "set_field", "file_id": "IN-06", "key": e["ext_recon_id"], "field": "bank_balance_reported",
                    "old": e["bank_balance_reported"], "new": sub(e["bank_balance_reported"])})
        ops.append({"op": "set_field", "file_id": "IN-06", "key": e["ext_recon_id"], "field": "difference_reported",
                    "old": e["difference_reported"], "new": fmt(Decimal(e["difference_reported"]) - amt)})
    F = "FAIL"
    diff_results = [["C08-DIFFERENCE", f"{iso}/{acct}", F] for iso in days] + [["DISC-LOG", f"{acct} from 2026-09-17", F]]
    entry_results = [["C11-BANK-ENTRY", "BE-GBP-0917-X01", F], ["BANK-CASH-LINK", "BE-GBP-0917-X01", F]]
    key = {"scenario_id": "S05", "description": "Unexplained GBP bank-ledger difference of 812.40 persisting 17-30 Sep 2026",
           "non_passing_results": sorted(diff_results + entry_results),
           "exceptions": [
               {"exception_id": "EXC-S05-01", "severity": "Critical", "root_cause": f"BANK_LEDGER_DIFFERENCE|{acct}|2026-09-17|-812.40",
                "affected_results": len(diff_results)},
               {"exception_id": "EXC-S05-02", "severity": "High", "root_cause": "UNMATCHED_BANK_ENTRY|BE-GBP-0917-X01",
                "affected_results": len(entry_results)}],
           "evidence_statuses": {"EXC-S05-01": "NOT_EVIDENCED"},
           "investigation_groups": [["EXC-S05-01", "EXC-S05-02"]], "candidate_relationships": [],
           "target_outcome": ("Two individual exceptions kept, linked in one investigation group (bank entry BE-GBP-0917-X01 is inside the "
                              "17 Sep balance where the -812.40 difference begins). NOT_EVIDENCED as timing; unresolved; no cause set; "
                              "no resolving evidence added; awaiting human review."),
           "must_hold": ["Internal reconciliation for GBP passes on every day (ledger unchanged, CASS 15.8.15R)",
                         "No cause is set: not labelled fee or timing",
                         "BE-GBP-0917-X01 is not linked to any batch or transaction"]}
    scenario = {"scenario_id": "S05", "name": "Unexplained GBP difference of 812.40 from 17 Sep 2026", "derived_from": "set_01_clean_baseline",
                "plan": "docs/UC042_SCENARIO_MUTATION_PLAN.md section 4 (persists to period end, decision D5)"}
    notes = f"""# Scenario S05 — Unexplained GBP difference of £812.40 from 17 Sep 2026 (synthetic)

**Changes vs the clean baseline** (exact list, with old and new values, in `mutations.json`):

- Added bank entry `BE-GBP-0917-X01`: £812.40 debit at 15:20 on 17 Sep, reference `SETTLE 0417` (IN-09).
- SGA-GBP-01 end-of-day statements from 17 Sep: closing balances reduced by 812.40; later openings reduced to match; 17 Sep `entry_count` + 1 (IN-08).
- 17:00 confirmations reduced by 812.40 on the {len(days)} reconciliation days 17–30 Sep (IN-07).
- External reconciliation records for those days now report the lower bank balance and a difference of −812.40, with no timing claim (IN-06).

**Kept unchanged on purpose:**

- The cash book (the ledger), client balances and internal reconciliation records.
- Transactions, settlement batches and lines (nothing carries `SETTLE 0417`).
- The discrepancy log (no investigation entry).

**Expected result:**

- `EXC-S05-01` (Critical): unexplained bank-ledger difference on {len(days)} days. Flags: own-funds top-up indicated (CASS 15.8.57R) and no investigation logged.
- `EXC-S05-02` (High): the bank entry has no counterpart.

The entry is listed as related to EXC-S05-01 because it sits on the statement where the difference first appears. It is not linked by amount. No cause is set; closing requires evidence and a reviewer.
"""
    return scenario, ops, key, notes


# --- Shared helpers for the gap-closure scenarios ---------------------------------------------------
GBP_ACCT = "SGA-GBP-01"


def recon_days(start=None):
    days = [r["calendar_date"] for r in read(BASELINE, "IN-01") if r["is_recon_day"] == "true"]
    return [d for d in days if start is None or d >= start]


def index(fid):
    pk = schema.columns(fid)[0]
    return {r[pk]: r for r in read(BASELINE, fid)}


def shift(value, delta):
    return fmt(Decimal(value) + Decimal(delta))


def set_op(fid, key, field, old, new, why=""):
    return {"op": "set_field", "file_id": fid, "key": key, "field": field, "old": old, "new": new, "why": why}


def key(sid, desc, non_passing, exceptions, target, limitations, groups=(), candidates=(), evidence=None):
    """Expected results, derived from the scenario design (not from validator output)."""
    return {"scenario_id": sid, "description": desc, "non_passing_results": sorted(non_passing), "exceptions": exceptions,
            "evidence_statuses": evidence or {}, "investigation_groups": [list(g) for g in groups],
            "candidate_relationships": [list(c) for c in candidates],
            "expected_outcome_basis": "scenario design; engine changes E1 (timing evidence) and E2 (investigation groups) implemented",
            "target_outcome": target, "engine_limitations": limitations}


# --- Scenario 2: settlement timing difference (SC2) ----------------------------------------------------
def sc2_definition():
    amount = Decimal("2868.50")
    entries = read(BASELINE, "IN-09")
    old = next(e for e in entries if e["bank_entry_id"] == "BE-GBP-0915-SB1")
    assert old["amount"] == "2868.50" and old["bank_reference"] == "SB-GBP-20260915" and old["dc_indicator"] == "D"
    rest = [e for e in entries if e["bank_entry_id"] != "BE-GBP-0915-SB1"]
    first_16 = next(i for i, e in enumerate(rest) if e["statement_id"] == "ST-SGA-GBP-01-20260916-EOD")
    new = dict(old, bank_entry_id="BE-GBP-0916-T01", statement_id="ST-SGA-GBP-01-20260916-EOD", booking_date="2026-09-16",
               booking_ts="2026-09-16T08:00:00+01:00", value_date="2026-09-16")
    eod, bc, erl = index("IN-08"), index("IN-07"), index("IN-06")
    s15, s16 = eod["ST-SGA-GBP-01-20260915-EOD"], eod["ST-SGA-GBP-01-20260916-EOD"]
    b15, e15 = bc["ST-SGA-GBP-01-20260915-1700"], erl["ERL-SGA-GBP-01-20260915"]
    ops = [
        {"op": "delete_record", "file_id": "IN-09", "key": "BE-GBP-0915-SB1", "why": "bank did not book the settlement on 15 Sep"},
        {"op": "add_record", "file_id": "IN-09", "insert_after": rest[first_16 - 1]["bank_entry_id"], "record": new,
         "why": "bank booked the 15 Sep settlement on 16 Sep 08:00, same reference and amount"},
        set_op("IN-08", s15["statement_id"], "closing_balance_amount", s15["closing_balance_amount"], shift(s15["closing_balance_amount"], amount)),
        set_op("IN-08", s15["statement_id"], "entry_count", s15["entry_count"], str(int(s15["entry_count"]) - 1)),
        set_op("IN-08", s16["statement_id"], "opening_balance_amount", s16["opening_balance_amount"], shift(s16["opening_balance_amount"], amount)),
        set_op("IN-08", s16["statement_id"], "entry_count", s16["entry_count"], str(int(s16["entry_count"]) + 1)),
        set_op("IN-07", b15["statement_id"], "balance_amount", b15["balance_amount"], shift(b15["balance_amount"], amount)),
        set_op("IN-06", e15["ext_recon_id"], "bank_balance_reported", e15["bank_balance_reported"], shift(e15["bank_balance_reported"], amount)),
        set_op("IN-06", e15["ext_recon_id"], "difference_reported", e15["difference_reported"], fmt(amount)),
        set_op("IN-06", e15["ext_recon_id"], "timing_difference_claimed", "false", "true"),
        {"op": "add_record", "file_id": "IN-14", "why": "the firm's own investigation record", "record": {
            "discrepancy_id": "DL-0001", "logged_ts": "2026-09-15T18:05:00+01:00", "recon_ref": "ERL-SGA-GBP-01-20260915",
            "account_id": GBP_ACCT, "currency": "GBP", "amount": fmt(amount),
            "description": "Scheme settlement SB-GBP-20260915 not debited by the bank by 17:00", "cause_category": "TIMING",
            "cause_evidence_ref": "BE-GBP-0916-T01", "funding_reference": "", "status": "RESOLVED",
            "resolved_ts": "2026-09-16T09:00:00+01:00", "approver_id": "U-04"}},
    ]
    k = key("SC2", "Settlement timing difference: SB-GBP-20260915 (2,868.50) recorded 15 Sep, booked by the bank 16 Sep 08:00",
            [["C08-DIFFERENCE", f"2026-09-15/{GBP_ACCT}", "FAIL"]],
            [{"exception_id": "EXC-SC2-01", "severity": "Critical", "root_cause": f"BANK_LEDGER_DIFFERENCE|{GBP_ACCT}|2026-09-15|2868.50",
              "affected_results": 1}],
            "15 Sep difference +2,868.50 detected (C08 FAIL while the difference exists); evidence status TIMING_EVIDENCED via cash-book "
            "entry LE-GBP-0915-0005 and clearing entry BE-GBP-0916-T01 (same account, currency, reference SB-GBP-20260915 and amount, "
            "booked the next business day, within D1); exception stays OPEN awaiting human confirmation; batch-to-bank reports the "
            "1-business-day lag as information.",
            [], evidence={"EXC-SC2-01": "TIMING_EVIDENCED"})
    notes = """# Scenario 2 — Settlement timing difference (SC2)

The firm recorded scheme settlement `SB-GBP-20260915` (debit 2,868.50) in its cash book and client balances at 15:00 on 15 Sep. The bank booked it at 08:00 on 16 Sep as `BE-GBP-0916-T01`, with the same reference and amount.

- The 15 Sep statement, 17:00 confirmation and external record show the bank balance 2,868.50 higher than the ledger.
- The 16 Sep figures agree again.
- The firm logged the difference as timing (`DL-0001`).

Unchanged: cash book, transactions, settlement batch and lines, client snapshots, internal records. Exact changes: `mutations.json`.

Engine limitation (E1): the validator detects the difference but cannot yet accept the clearing entry as timing evidence. See `answer_key.json` `target_outcome`.
"""
    return {"scenario_id": "SC2", "name": "Settlement timing difference (SB-GBP-20260915, 2,868.50)", "assessment_scenario": "2"}, ops, k, notes


# --- Scenario 3b: fee not itemised (SC3B) -----------------------------------------------------------
def sc3b_definition():
    lines = index("IN-13")
    for lid, code, amt in (("SL-AQ-GBP-20260908-0005", "ACQ_FEE", "30.00"), ("SL-AQ-GBP-20260908-0006", "SCHEME_FEE", "15.50")):
        assert lines[lid]["fee_code"] == code and lines[lid]["amount"] == amt
    ops = [{"op": "delete_record", "file_id": "IN-13", "key": lid, "why": "fee not itemised in the acquirer report"}
           for lid in ("SL-AQ-GBP-20260908-0005", "SL-AQ-GBP-20260908-0006")]
    k = key("SC3B", "Fee not itemised: AQ-GBP-20260908 header states fees 45.50 but carries no fee lines",
            [["C11-BATCH-ARITH", "AQ-GBP-20260908", "FAIL"]],
            [{"exception_id": "EXC-SC3B-01", "severity": "High", "root_cause": "C11-BATCH-ARITH|AQ-GBP-20260908", "affected_results": 1}],
            "Fee partially supported: header fees 45.50, bank credit 9,954.50 and own-funds top-up 45.50 agree, but no itemised fee lines.",
            [])
    notes = """# Scenario 3b — Fee not itemised (SC3B)

The two fee lines of acquirer batch `AQ-GBP-20260908` (`ACQ_FEE` 30.00, `SCHEME_FEE` 15.50) are removed. The batch header still states gross 10,000.00, fees 45.50 and net 9,954.50. The bank credit and the same-day own-funds top-up are unchanged.

The fee is therefore **partially supported**: it is asserted and paid, but not evidenced line by line.

Scenario 3a (correctly supported fee) is the same batch, unchanged, in the clean baseline.
"""
    return {"scenario_id": "SC3B", "name": "Fee not itemised (AQ-GBP-20260908)", "assessment_scenario": "3b"}, ops, k, notes


# --- Scenario 3c: short settlement, unexplained gross-to-net (SC3C) ----------------------------------
def sc3c_definition():
    entry = index("IN-09")["BE-GBP-0908-AQ1"]
    assert entry["amount"] == "9954.50" and entry["bank_reference"] == "AQ-GBP-20260908"
    eod, bc, erl = index("IN-08"), index("IN-07"), index("IN-06")
    days = recon_days("2026-09-08")
    ops = [set_op("IN-09", "BE-GBP-0908-AQ1", "amount", "9954.50", "9950.00", "acquirer credited 4.50 less than its reported net")]
    for i, d in enumerate(days):
        ymd = d.replace("-", "")
        s_ = eod[f"ST-{GBP_ACCT}-{ymd}-EOD"]
        if i:
            ops.append(set_op("IN-08", s_["statement_id"], "opening_balance_amount", s_["opening_balance_amount"], shift(s_["opening_balance_amount"], "-4.50")))
        ops.append(set_op("IN-08", s_["statement_id"], "closing_balance_amount", s_["closing_balance_amount"], shift(s_["closing_balance_amount"], "-4.50")))
        b = bc[f"ST-{GBP_ACCT}-{ymd}-1700"]
        ops.append(set_op("IN-07", b["statement_id"], "balance_amount", b["balance_amount"], shift(b["balance_amount"], "-4.50")))
        e = erl[f"ERL-{GBP_ACCT}-{ymd}"]
        ops.append(set_op("IN-06", e["ext_recon_id"], "bank_balance_reported", e["bank_balance_reported"], shift(e["bank_balance_reported"], "-4.50")))
        ops.append(set_op("IN-06", e["ext_recon_id"], "difference_reported", e["difference_reported"], "-4.50"))
    non_passing = [["C08-DIFFERENCE", f"{d}/{GBP_ACCT}", "FAIL"] for d in days] + [
        ["C11-BATCH-BANK", "AQ-GBP-20260908", "FAIL"], ["CASH-BANK-LINK", "LE-GBP-0908-0003", "FAIL"],
        ["DISC-LOG", f"{GBP_ACCT} from 2026-09-08", "FAIL"]]
    k = key("SC3C", f"Unexplained gross-to-net: AQ-GBP-20260908 credited 9,950.00 against reported net 9,954.50; -4.50 persists {len(days)} days",
            non_passing,
            [{"exception_id": "EXC-SC3C-01", "severity": "Critical", "root_cause": f"BANK_LEDGER_DIFFERENCE|{GBP_ACCT}|2026-09-08|-4.50",
              "affected_results": len(days) + 1},
             {"exception_id": "EXC-SC3C-02", "severity": "High", "root_cause": "C11-BATCH-BANK|AQ-GBP-20260908", "affected_results": 1},
             {"exception_id": "EXC-SC3C-03", "severity": "High", "root_cause": "CASH-BANK-LINK|LE-GBP-0908-0003", "affected_results": 1}],
            "Three individual exceptions kept, linked in one investigation group (reference AQ-GBP-20260908; bank entry BE-GBP-0908-AQ1 "
            "inside the 8 Sep balance where the difference begins). The -4.50 is NOT_EVIDENCED as timing and stays unexplained: "
            "9,954.50 expected (10,000.00 - 45.50), 9,950.00 received; own-funds top-up indicated; awaiting human review.",
            [], groups=[["EXC-SC3C-01", "EXC-SC3C-02", "EXC-SC3C-03"]], evidence={"EXC-SC3C-01": "NOT_EVIDENCED"})
    notes = f"""# Scenario 3c — Unexplained gross-to-net difference (SC3C)

The acquirer credited 9,950.00 for batch `AQ-GBP-20260908`, while its own report states net 9,954.50 (gross 10,000.00 − fees 45.50).

- The firm's cash book recorded the reported net (`LE-GBP-0908-0003`).
- The bank balance is therefore 4.50 below the ledger from 8 Sep to 30 Sep ({len(days)} reconciliation days).
- Statements, 17:00 confirmations and external records are adjusted consistently.

Nothing explains the 4.50. Engine limitation (E2): this one cause currently produces 3 exceptions.
"""
    return {"scenario_id": "SC3C", "name": "Short settlement, unexplained gross-to-net (AQ-GBP-20260908, -4.50)", "assessment_scenario": "3c"}, ops, k, notes


# --- Scenario 5a: transaction missing (SC5A) -----------------------------------------------------------
def sc5a_definition():
    t = index("IN-11")["TX-0915-00009"]
    assert (t["client_id"], t["amount"], t["txn_type"], t["settlement_batch_id"]) == ("C0002", "443.55", "SPEND", "SB-GBP-20260915")
    ops = [{"op": "delete_record", "file_id": "IN-11", "key": "TX-0915-00009", "why": "transaction missing from the platform export"}]
    k = key("SC5A", "Transaction TX-0915-00009 (C0002 spend 443.55) missing from the transaction export",
            [["C11-BATCH-ARITH", "SB-GBP-20260915", "FAIL"], ["CBAL-ROLLFWD", "GBP/C0002 2026-09-15", "FAIL"]],
            [{"exception_id": "EXC-SC5A-01", "severity": "High", "root_cause": "C11-BATCH-ARITH|SB-GBP-20260915", "affected_results": 1},
             {"exception_id": "EXC-SC5A-02", "severity": "High", "root_cause": "CBAL-ROLLFWD|GBP/C0002 2026-09-15", "affected_results": 1}],
            "Two separate exceptions and NO confirmed investigation group: the missing transaction's ID appears only on a settlement "
            "line, which carries no client, so no record links it to C0002. One candidate relationship is recorded, labelled UNVERIFIED "
            "(basis: same date and the 443.55 amount), for the human reviewer.",
            ["Evidence limitation, not an engine defect: the relationship cannot be confirmed without matching by amount"],
            candidates=[["EXC-SC5A-01", "EXC-SC5A-02"]])
    notes = """# Scenario 5a — Transaction missing (SC5A)

Spend `TX-0915-00009` (client C0002, 443.55, scheme batch `SB-GBP-20260915`) is removed from `transactions_2026-09.csv`. The settlement line that references it, the client snapshots and the bank records are unchanged.

C0002's 15 Sep roll-forward from transactions is therefore 443.55 above the snapshot. Engine limitation (E2): 2 exceptions for one cause.
"""
    return {"scenario_id": "SC5A", "name": "Transaction missing (TX-0915-00009, 443.55)", "assessment_scenario": "5a"}, ops, k, notes


# --- Scenario 5c: refund counted twice (SC5C) --------------------------------------------------------------
def sc5c_definition():
    r = index("IN-11")["TX-0909-0R001"]
    assert (r["client_id"], r["amount"], r["txn_type"]) == ("C0002", "60.00", "REFUND")
    snaps, irr = index("IN-03"), index("IN-05")
    days = recon_days("2026-09-09")
    ops = []
    for d in days:
        ymd = d.replace("-", "")
        sn = snaps[f"CBS-{ymd}-C0002-GBP"]
        ops.append(set_op("IN-03", sn["snapshot_id"], "balance", sn["balance"], shift(sn["balance"], "60.00"),
                          "refund TX-0909-0R001 posted twice in the client ledger"))
        ir = irr[f"IRR-EMONEY-GBP-{ymd}"]
        ops.append(set_op("IN-05", ir["recon_run_id"], "requirement_reported", ir["requirement_reported"], shift(ir["requirement_reported"], "60.00"),
                          "firm's reconciliation used its client ledger"))
        ops.append(set_op("IN-05", ir["recon_run_id"], "difference_reported", ir["difference_reported"], shift(ir["difference_reported"], "-60.00")))
    non_passing = [["C06-DIFFERENCE", f"{d}/GBP", "FAIL"] for d in days] + [["CBAL-ROLLFWD", "GBP/C0002 2026-09-09", "FAIL"]]
    exceptions = [{"exception_id": f"EXC-SC5C-{n:02d}", "severity": "Critical", "root_cause": f"INTERNAL_DIFFERENCE|{d}/GBP", "affected_results": 1}
                  for n, d in enumerate(days, 1)]
    exceptions.append({"exception_id": f"EXC-SC5C-{len(days) + 1:02d}", "severity": "High",
                       "root_cause": "CBAL-ROLLFWD|GBP/C0002 2026-09-09", "affected_results": 1})
    k = key("SC5C", f"Refund TX-0909-0R001 (60.00) counted twice in C0002's balance from 9 Sep; reported shortfall -60.00 on {len(days)} days",
            non_passing, exceptions,
            f"{len(days) + 1} individual exceptions kept, linked in one investigation group (the same -60.00 internal difference on "
            "consecutive days; C0002's 9 Sep snapshot, which fails the roll-forward, is an input to the 9 Sep requirement). Unresolved "
            "pending the client-ledger detail and human review; no cause set.",
            [], groups=[[e["exception_id"] for e in exceptions]])
    notes = f"""# Scenario 5c — Refund counted twice (SC5C)

Refund `TX-0909-0R001` (C0002, 60.00, of spend `TX-0902-00044`) appears once in the transactions. The client ledger counted it twice, so C0002's snapshots are 60.00 higher from 9 Sep ({len(days)} days).

The firm's internal reconciliation used that ledger: the reported requirement is +60.00 and the reported difference is −60.00 (a shortfall) each day. Transactions, cash book and bank are unchanged.

Engine limitation (E2): {len(days) + 1} exceptions for one cause.
"""
    return {"scenario_id": "SC5C", "name": "Refund counted twice (C0002, TX-0909-0R001, 60.00)", "assessment_scenario": "5c"}, ops, k, notes


# --- Scenario 5d: closing snapshot mismatch (SC5D) --------------------------------------------------------
def sc5d_definition():
    sn = index("IN-03")["CBS-20260930-C0003-GBP"]
    assert sn["balance"] == "49374.75"
    ops = [set_op("IN-03", sn["snapshot_id"], "balance", sn["balance"], shift(sn["balance"], "-250.00"),
                  "closing snapshot 250.00 below the transaction roll-forward")]
    k = key("SC5D", "Closing snapshot C0003 30 Sep 49,124.75 against an independent roll-forward of 49,374.75",
            [["C04-REQUIREMENT", "2026-09-30/GBP", "FAIL"], ["C06-DIFFERENCE", "2026-09-30/GBP", "FAIL"],
             ["CBAL-ROLLFWD", "GBP/C0003 2026-09-30", "FAIL"]],
            [{"exception_id": "EXC-SC5D-01", "severity": "Critical", "root_cause": "INTERNAL_DIFFERENCE|2026-09-30/GBP", "affected_results": 1},
             {"exception_id": "EXC-SC5D-02", "severity": "High", "root_cause": "CBAL-ROLLFWD|GBP/C0003 2026-09-30", "affected_results": 1},
             {"exception_id": "EXC-SC5D-03", "severity": "High", "root_cause": "C04-REQUIREMENT|2026-09-30/GBP", "affected_results": 1}],
            "Three individual exceptions kept, linked in one investigation group (C0003's 30 Sep snapshot is an input to the 30 Sep "
            "requirement; the internal difference uses that requirement). 250.00 unexplained; no cause set; awaiting human review.",
            [], groups=[["EXC-SC5D-01", "EXC-SC5D-02", "EXC-SC5D-03"]])
    notes = """# Scenario 5d — Closing snapshot mismatch (SC5D)

C0003's 30 Sep closing snapshot is 49,124.75, while the transaction roll-forward from 29 Sep gives 49,374.75 (a −250.00 difference).

The firm's reported internal reconciliation (requirement 395,844.86) is unchanged, so the recomputed requirement disagrees with it. Engine limitation (E2): 3 exceptions for one cause.
"""
    return {"scenario_id": "SC5D", "name": "Closing snapshot mismatch (C0003, -250.00)", "assessment_scenario": "5d"}, ops, k, notes


SCENARIOS = [
    # (assessment scenario, directory, definition or None for the baseline itself)
    ("1 Clean audit pack", BASELINE, None),
    ("2 Settlement timing difference", DATASETS / "scn_SC2_settlement_timing", sc2_definition),
    ("3a Correctly supported fee", BASELINE, None),
    ("3b Fee not itemised", DATASETS / "scn_SC3B_fee_not_itemised", sc3b_definition),
    ("3c Unexplained gross-to-net (short settlement)", DATASETS / "scn_SC3C_short_settlement", sc3c_definition),
    ("4 Missing or incomplete evidence", S02_DIR, s02_definition),
    ("5a Transaction missing", DATASETS / "scn_SC5A_missing_transaction", sc5a_definition),
    ("5c Refund counted twice", DATASETS / "scn_SC5C_refund_double_posted", sc5c_definition),
    ("5d Closing snapshot mismatch", DATASETS / "scn_SC5D_closing_snapshot_mismatch", sc5d_definition),
    ("6 Unexplained GBP difference 812.40", S05_DIR, s05_definition),
]


def write_index():
    rows = [{"assessment_scenario": a, "dataset": Path(d).name,
             "kind": "baseline" if fn is None else "mutation of set_01_clean_baseline"} for a, d, fn in SCENARIOS]
    (DATASETS / "scenario_index.json").write_text(json.dumps({"synthetic_notice": SYNTHETIC_NOTICE, "scenarios": rows}, indent=2) + "\n",
                                                  encoding="utf-8")
    lines = ["# UC-042 scenario datasets", "", f"> {SYNTHETIC_NOTICE}", "",
             "Every scenario dataset is built from `set_01_clean_baseline` by `python -m uc042lib.scenarios`. The baseline is never "
             "modified. Each scenario folder holds `mutations.json` (exact record changes), `answer_key.json` (expected results "
             "from the current engine, the intended business outcome, and known engine limitations) and `SCENARIO_NOTES.md`.", "",
             "| Assessment scenario | Dataset | Kind |", "| --- | --- | --- |"]
    lines += [f"| {r['assessment_scenario']} | `{r['dataset']}` | {r['kind']} |" for r in rows]
    lines += ["", "Scenario 3a uses acquirer batch `AQ-GBP-20260908` in the clean baseline unchanged. "
              "Deferred (not built): 3d wrong fee rate (D2), 5b adjustment not reflected (D3)."]
    (DATASETS / "SCENARIO_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    for label, out, fn in SCENARIOS:
        if fn is None:
            continue
        scenario, ops, key_, notes = fn()
        build(out, scenario, ops, key_, notes)
        print(f"Built {Path(out).name}: {len(ops)} operations; expected {len(key_['exceptions'])} exception(s), "
              f"{len(key_['non_passing_results'])} non-passing results")
    write_index()


if __name__ == "__main__":
    main()
