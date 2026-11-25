"""Independent data-quality and continuity verification of the January–August historical demo (reads files only).

Checks each month's files against the UC-042 file contract, dates and timezone offsets, calendar, references, arithmetic,
balances, currencies, duplicates and missing evidence, then month-to-month continuity and the August→September boundary
against the existing (unchanged) September 2026 baseline. Planted scenario effects are identified from mutations.json,
so expected findings are separated from errors.

    python verification/verify_history.py --project /path/to/uc042
"""
import argparse
import csv
import json
import sys
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
LON = ZoneInfo("Europe/London")
MONTHS = [f"2026-{m:02d}" for m in range(1, 9)]
HOLIDAYS = {date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25), date(2026, 8, 31)}
ACCOUNTS = ["SGA-GBP-01", "SGA-EUR-01", "OWN-GBP-01", "OWN-EUR-01"]


def cents(s):
    neg = s.startswith("-")
    a, b = s.lstrip("-").split(".")
    v = int(a) * 100 + int(b)
    return -v if neg else v


def signed_bank(amount, dc):
    return cents(amount) if dc == "C" else -cents(amount)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    sys.path.insert(0, a.project)
    from uc042lib import schema
    from uc042lib.structure import field_error
    report, all_pks = {}, defaultdict(lambda: defaultdict(list))
    for period in MONTHS:
        mdir = PKG / period / "source_documents"
        muts = json.loads((PKG / period / "mutations.json").read_text())
        planted_entries = {o["record"]["bank_entry_id"] for o in muts if o["op"] == "add_record" and o["file_id"] == "IN-09"}
        reref = {o["key"]: (o["old"], o["new"]) for o in muts if o["op"] == "set_field" and o["field"] == "bank_reference"}
        missing_stmt = {o["key"] for o in muts if o["op"] == "delete_record" and o["file_id"] == "IN-08"}
        diff_recs = {o["key"] for o in muts if o["op"] == "set_field" and o["file_id"] == "IN-06" and o["field"] == "difference_reported"}
        y, m = map(int, period.split("-"))
        start, end = date(y, m, 1), date(y, m, monthrange(y, m)[1])
        prev_end = start - timedelta(days=1)
        R = {}
        C = defaultdict(Counter)
        ex = defaultdict(list)

        def chk(name, ok, detail=""):
            C[name]["ok" if ok else "PROBLEM"] += 1
            if not ok and len(ex[name]) < 5:
                ex[name].append(detail)
        # 1-2 files, headers, types, mandatory fields
        for fid, (fname, _, cols) in schema.CSV_FILES.items():
            p = mdir / "source_data" / fname.replace("_2026-09", f"_{period}")
            chk("file present", p.exists(), str(p.name))
            with open(p, encoding="utf-8", newline="") as f:
                rd = csv.DictReader(f)
                chk("header matches contract", rd.fieldnames == [c[0] for c in cols], fname)
                R[fid] = list(rd)
            for i, row in enumerate(R[fid], start=2):
                for col, typ, req, _ in cols:
                    v = row[col]
                    if req == "M":
                        chk("mandatory field populated", v != "", f"{fid} L{i} {col}")
                    if v:
                        err = field_error(typ, v, schema.ENUMS.get((fid, col)))
                        chk("field type valid", err is None, f"{fid} L{i} {col}={v} ({err})")
            pk = cols[0][0]
            dup = [k for k, n in Counter(r[pk] for r in R[fid]).items() if n > 1]
            chk("primary keys unique in month", not dup, f"{fid} {dup[:3]}")
            chk("no exact duplicate rows", len({tuple(r.values()) for r in R[fid]}) == len(R[fid]), fid)
            for r in R[fid]:
                all_pks[fid][r[pk]].append((period, tuple(r.values())))
        # 3 dates, timestamps and offsets
        offsets = Counter()
        for fid, (_, _, cols) in schema.CSV_FILES.items():
            for row in R[fid]:
                for col, typ, _, _ in cols:
                    v = row[col]
                    if not v or typ not in ("date", "ts"):
                        continue
                    if typ == "ts":
                        t = datetime.fromisoformat(v)
                        expected = datetime(t.year, t.month, t.day, t.hour, t.minute, t.second, tzinfo=LON).utcoffset()
                        chk("timestamp offset correct for Europe/London", t.utcoffset() == expected, f"{fid} {col}={v} expected {expected}")
                        offsets["GMT +00:00" if t.utcoffset() == timedelta(0) else "BST +01:00"] += 1
                        d = t.astimezone(LON).date()
                    else:
                        d = date.fromisoformat(v)
                    if fid == "IN-02":
                        continue  # static account master data (open_date 2024-03-01)
                    opening_row = (fid == "IN-03" and row["recon_date"] == prev_end.isoformat()) or (fid == "IN-10" and row["entry_type"] == "OPENING_BALANCE")
                    chk("date within the reporting month (or documented opening row)", start <= d <= end or (opening_row and d == prev_end), f"{fid} {col}={v}")
        for r in R["IN-09"]:
            chk("booking_ts local date = booking_date", datetime.fromisoformat(r["booking_ts"]).astimezone(LON).date().isoformat() == r["booking_date"], r["bank_entry_id"])
            chk("value_date = booking_date", r["value_date"] == r["booking_date"], r["bank_entry_id"])
        for r in R["IN-03"] + R["IN-05"]:
            ts_ = r.get("as_at_ts") or r.get("reconciliation_point_ts")
            t = datetime.fromisoformat(ts_).astimezone(LON)
            chk("17:00 Europe/London point matches its date", (t.hour, t.minute) == (17, 0) and t.date().isoformat() == r["recon_date"], ts_)
        # 4 calendar
        cal = R["IN-01"]
        days = [date(y, m, d) for d in range(1, end.day + 1)]
        recon = [d for d in days if d.weekday() < 5 and d not in HOLIDAYS]
        chk("calendar has every day of the month", [r["calendar_date"] for r in cal] == [d.isoformat() for d in days], period)
        chk("calendar reconciliation days = weekdays minus bank holidays", [r["calendar_date"] for r in cal if r["is_recon_day"] == "true"] == [d.isoformat() for d in recon], period)
        chk("calendar period_id", {r["period_id"] for r in cal} == {f"PER-{period}"}, period)
        # 5 references
        by_ref = defaultdict(list)
        for e in R["IN-09"]:
            for ref in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
                by_ref[(e["account_id"], ref)].append(e)
        txns = {t["txn_id"]: t for t in R["IN-11"]}
        planted_refs = {new for _, new in reref.values()} | {old for old, _ in reref.values()}
        for c in R["IN-10"]:
            if c["entry_type"] == "OPENING_BALANCE":
                continue
            hits = by_ref.get((c["account_id"], c["payment_reference"]), [])
            if c["payment_reference"] in planted_refs:
                chk("planted reference mismatch present", len(hits) != 1, c["ledger_entry_id"])
                continue
            day = datetime.fromisoformat(c["posted_ts"]).astimezone(LON).date().strftime("%Y%m%d")
            if not hits and f"ST-{c['account_id']}-{day}-EOD" in missing_stmt:
                C["cash-book entries whose bank entry is on the missing statement (expected)"]["ok"] += 1
                continue
            chk("cash-book entry links to exactly one bank entry by reference", len(hits) == 1, c["ledger_entry_id"])
            if len(hits) == 1:
                chk("linked amounts equal (cash D/C opposite to bank)", cents(c["amount"]) == cents(hits[0]["amount"]) and (c["dc_indicator"] == "D") == (hits[0]["dc_indicator"] == "C"), c["ledger_entry_id"])
                chk("cash posting date = bank booking date (no timing difference)", datetime.fromisoformat(c["posted_ts"]).astimezone(LON).date().isoformat() == hits[0]["booking_date"], c["ledger_entry_id"])
        for e in R["IN-09"]:
            if e["account_id"].startswith("SGA") and e["bank_entry_id"] not in planted_entries:
                refs = {e["bank_reference"], e["end_to_end_ref"]} - {""}
                chk("bank entry links to a cash-book entry by reference", any(c["payment_reference"] in refs for c in R["IN-10"]), e["bank_entry_id"])
        lines = defaultdict(list)
        for ln in R["IN-13"]:
            lines[ln["batch_id"]].append(ln)
            if ln["txn_id"]:
                chk("settlement line → transaction", ln["txn_id"] in txns, ln["line_id"])
        for b in R["IN-12"]:
            ls = lines[b["batch_id"]]
            tot = lambda t: sum(cents(x["amount"]) for x in ls if x["line_type"] == t)
            chk("batch lines = header totals", tot("TXN") == cents(b["gross_amount"]) and tot("FEE") == cents(b["total_fees"]) and tot("REFUND") == cents(b["total_adjustments"]), b["batch_id"])
            gn = cents(b["gross_amount"]) - (cents(b["total_fees"]) if b["counterparty_type"] == "ACQUIRER" else cents(b["total_adjustments"]))
            chk("gross − fees/refunds = net", gn == cents(b["net_amount_reported"]), b["batch_id"])
            hits = by_ref.get((b["account_id"], b["expected_bank_reference"]), [])
            if b["expected_bank_reference"] in planted_refs:
                C["batches affected by the planted reference mismatch (expected)"]["ok"] += 1
                continue
            if not hits and f"ST-{b['account_id']}-{b['settlement_date'].replace('-', '')}-EOD" in missing_stmt:
                C["batches whose bank entry is on the missing statement (expected)"]["ok"] += 1
                continue
            chk("batch → one bank entry with its reference and net amount", len(hits) == 1 and cents(hits[0]["amount"]) == cents(b["net_amount_reported"]), b["batch_id"])
        for t in R["IN-11"]:
            if t["settlement_batch_id"]:
                chk("transaction → batch", any(b["batch_id"] == t["settlement_batch_id"] for b in R["IN-12"]), t["txn_id"])
            if t["original_txn_id"]:
                o = txns.get(t["original_txn_id"])
                chk("refund → original (same client and currency, not exceeded)", bool(o) and o["client_id"] == t["client_id"] and o["currency"] == t["currency"] and cents(t["amount"]) <= cents(o["amount"]), t["txn_id"])
        for u in R["IN-04"]:
            chk("unallocated receipt → bank entry", bool(by_ref.get((f"SGA-{u['currency']}-01", u["bank_reference"]))), u["receipt_id"])
            chk("unallocated receipt allocated within the month", u["allocated_ts"] > u["receipt_ts"] and u["allocated_date"] <= end.isoformat(), u["receipt_id"])
        # 6 arithmetic and balances
        ent_by = defaultdict(list)
        for e in R["IN-09"]:
            ent_by[e["statement_id"]].append(e)
        eod = sorted(R["IN-08"], key=lambda s: (s["account_id"], s["statement_date"]))
        for s in eod:
            es = ent_by[s["statement_id"]]
            ok = signed_bank(s["opening_balance_amount"], s["opening_balance_dc"]) + sum(signed_bank(e["amount"], e["dc_indicator"]) for e in es) == signed_bank(s["closing_balance_amount"], s["closing_balance_dc"]) and int(s["entry_count"]) == len(es)
            chk("statement arithmetic (opening + entries = closing; entry count)", ok, s["statement_id"])
        for acct in ACCOUNTS:
            st = [s for s in eod if s["account_id"] == acct]
            days_present = [s_["statement_date"] for s_ in st]
            for p_, n_ in zip(st, st[1:]):
                spans_gap = any(p_["statement_date"] < d.isoformat() < n_["statement_date"] for d in recon)
                if spans_gap:
                    C["statement continuity not assessable across the missing day (expected)"]["ok"] += 1
                    continue
                chk("statement continuity (closing = next opening)", p_["closing_balance_amount"] == n_["opening_balance_amount"], n_["statement_id"])
            expected_days = [d.isoformat() for d in recon]
            present = [s["statement_date"] for s in st]
            gap = sorted(set(expected_days) - set(present))
            if gap:
                chk("missing statement days are the planted ones", all(f"ST-{acct}-{g.replace('-', '')}-EOD" in missing_stmt for g in gap), f"{acct} {gap}")
                C["statement days missing by design (not zero-filled)"]["ok"] += len(gap)
        bc_by = {b["statement_id"]: b for b in R["IN-07"]}
        for s in eod:
            b = bc_by.get(s["statement_id"].replace("-EOD", "-1700"))
            if b:
                upto = signed_bank(s["opening_balance_amount"], s["opening_balance_dc"]) + sum(signed_bank(e["amount"], e["dc_indicator"]) for e in ent_by[s["statement_id"]] if e["booking_ts"] <= b["as_at_ts"] or datetime.fromisoformat(e["booking_ts"]) <= datetime.fromisoformat(b["as_at_ts"]))
                chk("17:00 confirmation = opening + entries to 17:00", signed_bank(b["balance_amount"], b["balance_dc_indicator"]) == upto, b["statement_id"])
        snaps = defaultdict(int)
        for r in R["IN-03"]:
            snaps[(r["recon_date"], r["currency"])] += max(0, cents(r["balance"]))
        cash = sorted(R["IN-10"], key=lambda c: c["posted_ts"])
        for r in R["IN-05"]:
            point = datetime.fromisoformat(r["reconciliation_point_ts"])
            open_un = sum(cents(u["amount"]) for u in R["IN-04"] if u["currency"] == r["currency"] and datetime.fromisoformat(u["receipt_ts"]) <= point < datetime.fromisoformat(u["allocated_ts"]))
            led = sum((cents(c["amount"]) if c["dc_indicator"] == "D" else -cents(c["amount"])) for c in cash if c["currency"] == r["currency"] and datetime.fromisoformat(c["posted_ts"]) <= point)
            chk("requirement (snapshots + open unallocated) = reported", snaps[(r["recon_date"], r["currency"])] + open_un == cents(r["requirement_reported"]), r["recon_run_id"])
            chk("item A (cash book to 17:00) = reported = requirement (internal difference 0)", led == cents(r["item_a"]) == cents(r["requirement_reported"]), r["recon_run_id"])
        for r in R["IN-06"]:
            b = bc_by.get(r["bank_statement_id"])
            if not b:
                C["external records without a confirmation (missing evidence, expected)"]["ok"] += 1
                continue
            diff = signed_bank(b["balance_amount"], b["balance_dc_indicator"]) - cents(r["ledger_balance_reported"])
            if r["ext_recon_id"] in diff_recs:
                chk("planted bank-ledger difference present and reported", diff != 0 and diff == cents(r["difference_reported"]), r["ext_recon_id"])
            else:
                chk("bank − ledger = 0 and reported 0", diff == 0 and cents(r["difference_reported"]) == 0, r["ext_recon_id"])
        # 7 currency
        accts = {x["account_id"]: x["currency"] for x in R["IN-02"]}
        for fid in ("IN-06", "IN-07", "IN-08", "IN-09", "IN-10", "IN-12"):
            for r in R[fid]:
                chk("currency = account currency", r["currency"] == accts[r["account_id"]], f"{fid} {r}")
        # 8 natural-key duplicates
        nk = Counter((e["account_id"], e["booking_ts"], e["amount"], e["dc_indicator"], e["bank_reference"]) for e in R["IN-09"])
        chk("no natural-key duplicate bank entries", all(n == 1 for n in nk.values()), str([k for k, n in nk.items() if n > 1][:2]))
        # Closing / opening positions
        last = recon[-1]
        closing = {"clients": {r["client_id"] + "/" + r["currency"]: r["balance"] for r in R["IN-03"] if r["recon_date"] == last.isoformat()},
                   "cash": {ccy: str(sum((cents(c["amount"]) if c["dc_indicator"] == "D" else -cents(c["amount"])) for c in R["IN-10"] if c["currency"] == ccy)) for ccy in ("GBP", "EUR")},
                   "bank": {acct: max((s for s in eod if s["account_id"] == acct), key=lambda s: s["statement_date"])["closing_balance_amount"] for acct in ACCOUNTS}}
        opening = {"clients": {r["client_id"] + "/" + r["currency"]: r["balance"] for r in R["IN-03"] if r["recon_date"] == prev_end.isoformat()},
                   "cash": {c["currency"]: str(cents(c["amount"])) for c in R["IN-10"] if c["entry_type"] == "OPENING_BALANCE"},
                   "bank": {acct: min((s for s in eod if s["account_id"] == acct), key=lambda s: s["statement_date"])["opening_balance_amount"] for acct in ACCOUNTS}}
        report[period] = {"checks": {k: dict(v) for k, v in C.items()}, "examples": dict(ex), "offsets": dict(offsets),
                          "rows": {fid: len(R[fid]) for fid in R}, "recon_days": len(recon), "days": len(days),
                          "opening": opening, "closing": closing, "last_recon_day": last.isoformat(), "prev_end": prev_end.isoformat()}
    # Continuity month to month
    cont = []
    for p1, p2 in zip(MONTHS, MONTHS[1:]):
        c1, o2 = report[p1]["closing"], report[p2]["opening"]
        cont.append({"from": p1, "to": p2, "clients_equal": c1["clients"] == o2["clients"], "cash_equal": {k: str(int(c1["cash"][k])) == o2["cash"][k] for k in c1["cash"]},
                     "bank_equal": {k: c1["bank"][k] == o2["bank"][k] for k in c1["bank"]}})
    # August -> September (existing, unchanged baseline)
    base = Path(a.project) / "uc042_dataset" / "set_01_clean_baseline" / "source_data"
    rd = lambda f: list(csv.DictReader(open(base / f, encoding="utf-8", newline="")))
    s_snap = {r["client_id"] + "/" + r["currency"]: r["balance"] for r in rd("client_balance_snapshots_2026-09.csv") if r["recon_date"] == "2026-08-31"}
    s_cash = {r["currency"]: str(cents(r["amount"])) for r in rd("sga_cashbook_entries_2026-09.csv") if r["entry_type"] == "OPENING_BALANCE"}
    s_eod = rd("bank_statements_eod_2026-09.csv")
    s_bank = {acct: min((s for s in s_eod if s["account_id"] == acct), key=lambda s: s["statement_date"])["opening_balance_amount"] for acct in ACCOUNTS}
    aug = report["2026-08"]["closing"]
    boundary = {"clients_equal": aug["clients"] == s_snap, "cash_equal": {k: str(int(aug["cash"][k])) == s_cash[k] for k in s_cash},
                "bank_equal": {k: aug["bank"][k] == s_bank[k] for k in s_bank},
                "august_closing": aug, "september_opening": {"clients": s_snap, "cash": s_cash, "bank": s_bank}}
    # Cross-month identifier uniqueness (identical carried-forward opening snapshots are reported separately)
    cross = {}
    for fid, ids in all_pks.items():
        multi = {k: v for k, v in ids.items() if len({p for p, _ in v}) > 1}
        carried = {k: v for k, v in multi.items() if fid == "IN-03" and len({row for _, row in v}) == 1}
        cross[fid] = {"ids_in_more_than_one_month": len(multi), "identical_carried_forward_opening_snapshots": len(carried),
                      "conflicting": sorted(set(multi) - set(carried))[:5]}
    problems = {p: {k: v for k, v in r["checks"].items() if v.get("PROBLEM")} for p, r in report.items()}
    out = {"months": report, "continuity": cont, "august_to_september": boundary, "cross_month_ids": cross, "problems": problems}
    (HERE / "data_quality_results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for p, r in report.items():
        total = sum(sum(v.values()) for v in r["checks"].values())
        print(f"{p}: {total} checks, problems {sum(v.get('PROBLEM', 0) for v in r['checks'].values())} | offsets {r['offsets']}")
    for c in cont:
        print("continuity", c["from"], "->", c["to"], c["clients_equal"], c["cash_equal"], c["bank_equal"])
    print("August -> September:", boundary["clients_equal"], boundary["cash_equal"], boundary["bank_equal"])
    print("cross-month IDs:", {k: (v["ids_in_more_than_one_month"], v["identical_carried_forward_opening_snapshots"], v["conflicting"]) for k, v in cross.items() if v["ids_in_more_than_one_month"]})
    print("problems:", {p: v for p, v in problems.items() if v})


if __name__ == "__main__":
    main()
