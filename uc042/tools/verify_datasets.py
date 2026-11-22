"""Independent verification of UC-042 scenario datasets.

Standalone: imports nothing from uc042lib. It re-implements the documented conventions (data dictionary sign
rules, 17:00 Europe/London point, September 2026 period with the two documented 31 Aug opening records) and
checks every dataset directly from its CSV files with Decimal arithmetic. Currencies are never combined.

Usage (from the uc042/ folder):
    python tools/verify_datasets.py                    # all datasets listed in uc042_dataset/scenario_index.json
    python tools/verify_datasets.py --json out.json    # also write the machine-readable summary

Each check returns a status per scope: OK, PROBLEM (evidence contradicts) or INSUFFICIENT (evidence absent).
Scenario datasets are expected to show PROBLEM / INSUFFICIENT exactly where their mutation was applied.
"""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent / "uc042_dataset"
LON = ZoneInfo("Europe/London")
Z = Decimal("0.00")
FILES = {  # file -> primary key
    "recon_calendar_2026-09.csv": "calendar_date", "account_inventory.csv": "account_id",
    "client_balance_snapshots_2026-09.csv": "snapshot_id", "unallocated_register_2026-09.csv": "receipt_id",
    "internal_recon_records_2026-09.csv": "recon_run_id", "external_recon_records_2026-09.csv": "ext_recon_id",
    "bank_balance_confirmations_2026-09.csv": "statement_id", "bank_statements_eod_2026-09.csv": "statement_id",
    "bank_statement_entries_2026-09.csv": "bank_entry_id", "sga_cashbook_entries_2026-09.csv": "ledger_entry_id",
    "transactions_2026-09.csv": "txn_id", "settlement_batches_2026-09.csv": "batch_id",
    "settlement_lines_2026-09.csv": "line_id", "discrepancy_log_2026-09.csv": "discrepancy_id"}
MONEY_U = re.compile(r"^\d+\.\d{2}$")
MONEY_S = re.compile(r"^-?\d+\.\d{2}$")


def ts(s):
    return datetime.fromisoformat(s)


def D(s):
    return Decimal(s)


def bank(a, dc):
    return D(a) if dc == "C" else -D(a)


def cashbook(a, dc):
    return D(a) if dc == "D" else -D(a)


def client(a, d):
    return D(a) if d == "CR" else -D(a)


def line(a, dc):
    return D(a) if dc == "C" else -D(a)


def next_business_day(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class Check:
    def __init__(self):
        self.res = defaultdict(Counter)
        self.examples = defaultdict(list)

    def __call__(self, name, status, example=""):
        self.res[name][status] += 1
        if status != "OK" and len(self.examples[name]) < 25:
            self.examples[name].append(example)


def load(ds):
    out = {}
    for f in FILES:
        p = ds / "source_data" / f
        with open(p, encoding="utf-8", newline="") as h:
            out[f] = list(csv.DictReader(h))
    return out


def diff_vs_baseline(data, base):
    """Added / removed / modified records per file, by primary key (no amount matching)."""
    out = {}
    for f, pk in FILES.items():
        a = {r[pk]: r for r in base[f]}
        b = {r[pk]: r for r in data[f]}
        added, removed = sorted(set(b) - set(a)), sorted(set(a) - set(b))
        modified = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        if added or removed or modified:
            out[f] = {"added": added, "removed": removed, "modified": modified}
    return out


def verify(ds):
    t = load(ds)
    c = Check()
    cal, acc = t["recon_calendar_2026-09.csv"], t["account_inventory.csv"]
    snaps, ureg = t["client_balance_snapshots_2026-09.csv"], t["unallocated_register_2026-09.csv"]
    irr, erl = t["internal_recon_records_2026-09.csv"], t["external_recon_records_2026-09.csv"]
    bcs, eods, ents = t["bank_balance_confirmations_2026-09.csv"], t["bank_statements_eod_2026-09.csv"], t["bank_statement_entries_2026-09.csv"]
    cash, txns = t["sga_cashbook_entries_2026-09.csv"], t["transactions_2026-09.csv"]
    bats, lins, log = t["settlement_batches_2026-09.csv"], t["settlement_lines_2026-09.csv"], t["discrepancy_log_2026-09.csv"]
    days = [date.fromisoformat(r["calendar_date"]) for r in cal if r["is_recon_day"] == "true"]
    sga = {r["account_id"]: r["currency"] for r in acc if r["account_class"] == "RELEVANT_FUNDS_BANK"}
    own = {r["account_id"]: r["currency"] for r in acc if r["account_class"] == "OWN_FUNDS"}
    ccy_of = {**sga, **own}
    acct_of = {v: k for k, v in sga.items()}
    point = lambda d: datetime.combine(d, time(17, 0), tzinfo=LON)

    # -- identifiers, references, formats, currency, period
    for f, pk in FILES.items():
        for k, n in Counter(r[pk] for r in t[f]).items():
            c("duplicate ids", "OK" if n == 1 else "PROBLEM", f"{f}:{k}")
    eod_ids, bc_ids = {s["statement_id"] for s in eods}, {b["statement_id"] for b in bcs}
    bat_ids, txn_ids = {b["batch_id"] for b in bats}, {x["txn_id"] for x in txns}
    rec_ids = {r["recon_run_id"] for r in irr} | {r["ext_recon_id"] for r in erl}
    for e in ents:
        c("reference: entry -> statement", "OK" if e["statement_id"] in eod_ids else "PROBLEM", e["bank_entry_id"])
    for f in ("bank_statement_entries_2026-09.csv", "bank_statements_eod_2026-09.csv", "bank_balance_confirmations_2026-09.csv",
              "sga_cashbook_entries_2026-09.csv", "settlement_batches_2026-09.csv", "external_recon_records_2026-09.csv"):
        for r in t[f]:
            c("reference: account -> inventory", "OK" if r["account_id"] in ccy_of else "PROBLEM", f"{f}:{r[FILES[f]]}")
            c("currency = account currency", "OK" if r["currency"] == ccy_of.get(r["account_id"]) else "PROBLEM", f"{f}:{r[FILES[f]]}")
    for e in erl:
        c("reference: external record -> confirmation", "OK" if e["bank_statement_id"] in bc_ids else "INSUFFICIENT", e["ext_recon_id"])
    for ln in lins:
        c("reference: line -> batch", "OK" if ln["batch_id"] in bat_ids else "PROBLEM", ln["line_id"])
        if ln["txn_id"]:
            c("reference: line -> transaction", "OK" if ln["txn_id"] in txn_ids else "PROBLEM", f"{ln['line_id']} -> {ln['txn_id']}")
    for x in txns:
        if x["settlement_batch_id"]:
            c("reference: transaction -> batch", "OK" if x["settlement_batch_id"] in bat_ids else "PROBLEM", x["txn_id"])
        if x["original_txn_id"]:
            c("reference: refund -> original", "OK" if x["original_txn_id"] in txn_ids else "PROBLEM", x["txn_id"])
    for r in log:
        c("reference: log -> reconciliation record", "OK" if r["recon_ref"] in rec_ids else "PROBLEM", r["discrepancy_id"])
    bad_money = [(f, k) for f, rows in t.items() for r in rows for k, v in r.items()
                 if v and (k in ("amount", "balance_amount", "opening_balance_amount", "closing_balance_amount", "gross_amount",
                                 "total_fees", "total_adjustments", "net_amount_reported") and not MONEY_U.match(v)
                           or k in ("balance", "requirement_reported", "resource_reported", "difference_reported",
                                    "ledger_balance_reported", "bank_balance_reported") and not MONEY_S.match(v))]
    c("money format (2 dp)", "OK" if not bad_money else "PROBLEM", str(bad_money[:3]))
    for f, rows in t.items():
        for r in rows:
            for k, v in r.items():
                if v and (k.endswith("_ts") or k in ("recon_date", "statement_date", "booking_date", "settlement_date", "receipt_date")):
                    d = ts(v).astimezone(LON).date() if k.endswith("_ts") else date.fromisoformat(v)
                    permitted = (f == "sga_cashbook_entries_2026-09.csv" and r.get("entry_type") == "OPENING_BALANCE"
                                 or f == "client_balance_snapshots_2026-09.csv" and r.get("recon_date") == "2026-08-31") \
                        and v.startswith("2026-08-31")
                    c("dates in September 2026 (or documented 31 Aug opening)",
                      "OK" if date(2026, 9, 1) <= d <= date(2026, 9, 30) or permitted
                      or k in ("resolved_ts",) else "PROBLEM", f"{f}:{r[FILES[f]]}:{k}={v}")

    # -- bank statements
    ent_by = defaultdict(list)
    for e in ents:
        ent_by[e["statement_id"]].append(e)
    eod_by = {(s["account_id"], s["statement_date"]): s for s in eods}
    bc_by = {(b["account_id"], ts(b["as_at_ts"]).date().isoformat()): b for b in bcs}
    for s in eods:
        es = ent_by[s["statement_id"]]
        ok = bank(s["opening_balance_amount"], s["opening_balance_dc"]) + sum((bank(e["amount"], e["dc_indicator"]) for e in es), Z) \
            == bank(s["closing_balance_amount"], s["closing_balance_dc"]) and int(s["entry_count"]) == len(es)
        c("statement arithmetic", "OK" if ok else "PROBLEM", s["statement_id"])
    for a in ccy_of:
        for d in days:
            if (a, d.isoformat()) not in eod_by:
                c("statement present for every reconciliation day", "INSUFFICIENT", f"{a} {d}")
            else:
                c("statement present for every reconciliation day", "OK")
        st = sorted((s for s in eods if s["account_id"] == a), key=lambda s: s["statement_date"])
        for p, n in zip(st, st[1:]):
            gap = [d for d in days if p["statement_date"] < d.isoformat() < n["statement_date"]]
            if gap:
                c("statement continuity", "INSUFFICIENT", f"{a} gap {gap[0]}")
            else:
                c("statement continuity", "OK" if bank(p["closing_balance_amount"], p["closing_balance_dc"]) ==
                  bank(n["opening_balance_amount"], n["opening_balance_dc"]) else "PROBLEM", n["statement_id"])
    for (a, d), b in bc_by.items():
        s = eod_by.get((a, d))
        if s is None:
            c("17:00 confirmation = opening + entries to 17:00", "INSUFFICIENT", b["statement_id"])
            continue
        upto = sum((bank(e["amount"], e["dc_indicator"]) for e in ent_by[s["statement_id"]] if ts(e["booking_ts"]) <= ts(b["as_at_ts"])), Z)
        c("17:00 confirmation = opening + entries to 17:00",
          "OK" if bank(b["balance_amount"], b["balance_dc_indicator"]) == bank(s["opening_balance_amount"], s["opening_balance_dc"]) + upto
          else "PROBLEM", b["statement_id"])

    # -- ledger, requirement, external comparison
    def ledger(a, when):
        return sum((cashbook(x["amount"], x["dc_indicator"]) for x in cash if x["account_id"] == a and ts(x["posted_ts"]) <= when), Z)
    snap_by = defaultdict(list)
    for s in snaps:
        snap_by[(s["recon_date"], s["currency"])].append(s)
    ext_diff = {}
    for r in irr:
        d, cc = date.fromisoformat(r["recon_date"]), r["currency"]
        req = sum((max(Z, D(s["balance"])) for s in snap_by[(r["recon_date"], cc)]), Z) + sum(
            (D(u["amount"]) for u in ureg if u["currency"] == cc and ts(u["receipt_ts"]) <= point(d)
             and (not u["allocated_ts"] or ts(u["allocated_ts"]) > point(d))), Z)
        c("requirement recomputed = reported", "OK" if req == D(r["requirement_reported"]) else "PROBLEM",
          f"{d}/{cc}: recomputed {req} reported {r['requirement_reported']}")
        res = ledger(acct_of[cc], point(d))
        c("item A from cash book = reported", "OK" if res == D(r["item_a"]) else "PROBLEM", f"{d}/{cc}")
        c("internal difference (resource - requirement) = 0", "OK" if res - req == Z else "PROBLEM", f"{d}/{cc}: {res - req}")
    for e in erl:
        d, a = date.fromisoformat(e["recon_date"]), e["account_id"]
        led = ledger(a, point(d))
        c("ledger recomputed = reported", "OK" if led == D(e["ledger_balance_reported"]) else "PROBLEM", e["ext_recon_id"])
        b = bc_by.get((a, d.isoformat()))
        if b is None:
            c("bank - ledger = 0", "INSUFFICIENT", f"{d}/{a}: no bank confirmation")
            continue
        diff = bank(b["balance_amount"], b["balance_dc_indicator"]) - led
        ext_diff[(a, d)] = diff
        c("reported bank balance = confirmation", "OK" if bank(b["balance_amount"], b["balance_dc_indicator"]) == D(e["bank_balance_reported"])
          else "PROBLEM", e["ext_recon_id"])
        c("bank - ledger = 0", "OK" if diff == Z else "PROBLEM", f"{d}/{a}: {diff}")

    # -- cash book <-> bank by reference; cross-day timing (D1: up to one business day)
    by_ref = defaultdict(list)
    for e in ents:
        for rf in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
            by_ref[(e["account_id"], rf)].append(e)
    timing = []
    for x in cash:
        if x["entry_type"] == "OPENING_BALANCE":
            continue
        hits = by_ref.get((x["account_id"], x["payment_reference"]), [])
        if len(hits) != 1:
            c("cash book -> one bank entry by reference", "INSUFFICIENT" if not hits else "PROBLEM", x["ledger_entry_id"])
            continue
        h = hits[0]
        same = cashbook(x["amount"], x["dc_indicator"]) == bank(h["amount"], h["dc_indicator"])
        c("cash book -> one bank entry by reference", "OK" if same else "PROBLEM",
          f"{x['ledger_entry_id']}: ledger {cashbook(x['amount'], x['dc_indicator'])} bank {bank(h['amount'], h['dc_indicator'])}")
        posted, booked = ts(x["posted_ts"]).date(), date.fromisoformat(h["booking_date"])
        if booked != posted:
            within = booked == next_business_day(posted)
            timing.append({"ledger_entry": x["ledger_entry_id"], "bank_entry": h["bank_entry_id"], "reference": x["payment_reference"],
                           "account": x["account_id"], "amount": str(cashbook(x["amount"], x["dc_indicator"])),
                           "posted": str(posted), "booked": str(booked), "within_one_business_day": within})
            c("cross-day items within one business day (D1)", "OK" if within else "PROBLEM", h["bank_entry_id"])
    # a day's bank-ledger difference is timing-evidenced only if the cross-day items fully explain it
    for (a, d), diff in sorted(ext_diff.items()):
        if diff == Z:
            continue
        open_items = sum((-D(i["amount"]) for i in timing if i["account"] == a and i["within_one_business_day"]
                          and date.fromisoformat(i["posted"]) <= d < date.fromisoformat(i["booked"])), Z)
        c("difference fully evidenced as timing", "OK" if open_items == diff else "PROBLEM",
          f"{d}/{a}: difference {diff}; timing-evidenced {open_items}")
    for e in ents:
        if e["account_id"] in sga:
            refs = {e["bank_reference"], e["end_to_end_ref"]} - {""}
            c("bank entry -> cash book by reference", "OK" if any(x["payment_reference"] in refs and x["account_id"] == e["account_id"]
                                                                  for x in cash) else "PROBLEM", f"{e['bank_entry_id']} ({e['bank_reference']})")

    # -- settlement
    lines_by = defaultdict(list)
    for ln in lins:
        lines_by[ln["batch_id"]].append(ln)
    txn_by = {x["txn_id"]: x for x in txns}
    for b in bats:
        ls = lines_by[b["batch_id"]]
        tot = lambda kind: sum((D(x["amount"]) for x in ls if x["line_type"] == kind), Z)
        net = D(b["net_amount_reported"]) * (1 if b["direction"] == "TO_FIRM" else -1)
        ok = tot("TXN") == D(b["gross_amount"]) and tot("FEE") == D(b["total_fees"]) and tot("REFUND") == D(b["total_adjustments"]) \
            and sum((line(x["amount"], x["dc_indicator"]) for x in ls), Z) == net \
            and all(x["txn_id"] in txn_by for x in ls if x["line_type"] in ("TXN", "REFUND"))
        c("batch: lines = reported totals (gross, fees, adjustments, net)", "OK" if ok else "PROBLEM",
          f"{b['batch_id']}: TXN {tot('TXN')} / gross {b['gross_amount']}; FEE {tot('FEE')} / fees {b['total_fees']}")
        gross_net = D(b["gross_amount"]) - (D(b["total_fees"]) if b["counterparty_type"] == "ACQUIRER" else D(b["total_adjustments"]))
        c("batch: gross - fees (acquirer) or - refunds (scheme) = reported net", "OK" if gross_net == D(b["net_amount_reported"]) else "PROBLEM", b["batch_id"])
        hits = by_ref.get((b["account_id"], b["expected_bank_reference"]), [])
        if not hits:
            c("batch -> bank entry by reference, same signed amount", "INSUFFICIENT", b["batch_id"])
        else:
            h = hits[0]
            c("batch -> bank entry by reference, same signed amount", "OK" if len(hits) == 1 and bank(h["amount"], h["dc_indicator"]) == net
              else "PROBLEM", f"{b['batch_id']}: reported {net} banked {bank(h['amount'], h['dc_indicator'])}")
            lag = (date.fromisoformat(h["booking_date"]) - date.fromisoformat(b["settlement_date"])).days
            c("batch booked on its settlement date", "OK" if lag == 0 else "PROBLEM", f"{b['batch_id']}: booked {h['booking_date']}")
    for x in txns:
        if x["txn_type"] in ("LOAD_CARD", "SPEND", "REFUND"):
            n = sum(1 for ln in lines_by.get(x["settlement_batch_id"], []) if ln["txn_id"] == x["txn_id"])
            c("card transaction in exactly one line of its batch", "OK" if n == 1 else "PROBLEM", x["txn_id"])
    for x in txns:
        if x["txn_type"] == "REFUND":
            o = txn_by.get(x["original_txn_id"])
            c("refund: original exists, same client/currency, not exceeded",
              "OK" if o and o["client_id"] == x["client_id"] and o["currency"] == x["currency"] and D(x["amount"]) <= D(o["amount"]) else "PROBLEM",
              x["txn_id"])

    # -- client roll-forward from the earliest snapshot (31 Aug opening when present)
    by_client = defaultdict(dict)
    for s in snaps:
        by_client[(s["currency"], s["client_id"])][date.fromisoformat(s["recon_date"])] = D(s["balance"])
    opening_present = any(d == date(2026, 8, 31) for v in by_client.values() for d in v)
    c("opening client snapshot (31 Aug) present", "OK" if opening_present else "INSUFFICIENT")
    for (cc, cl), bal in by_client.items():
        snap_days = sorted(bal)
        for p, n in zip(snap_days, snap_days[1:]):
            mv = sum((client(x["amount"], x["direction"]) for x in txns if x["currency"] == cc and x["client_id"] == cl
                      and point(p) < ts(x["executed_ts"]) <= point(n)), Z)
            c("client roll-forward", "OK" if bal[p] + mv == bal[n] else "PROBLEM",
              f"{cc}/{cl} {n}: expected {bal[p] + mv} snapshot {bal[n]} (difference {bal[n] - bal[p] - mv})")
    for cc, acct in acct_of.items():
        op = sum((v[date(2026, 8, 31)] for (c2, _), v in by_client.items() if c2 == cc and date(2026, 8, 31) in v), Z)
        cash_open = sum((cashbook(x["amount"], x["dc_indicator"]) for x in cash if x["account_id"] == acct and x["entry_type"] == "OPENING_BALANCE"), Z)
        first = min((s for s in eods if s["account_id"] == acct), key=lambda s: s["statement_date"])
        c("opening: client total = cash-book opening = 1 Sep bank opening",
          "OK" if opening_present and op == cash_open == bank(first["opening_balance_amount"], first["opening_balance_dc"]) else "INSUFFICIENT"
          if not opening_present else "PROBLEM", f"{cc}: clients {op}, cash {cash_open}")

    summary = {name: dict(cnt) for name, cnt in sorted(c.res.items())}
    return {"checks": summary, "examples": {k: v for k, v in c.examples.items() if v}, "timing_items": timing,
            "files": {f: len(rows) for f, rows in t.items()}, "csv_rows": sum(len(r) for r in t.values()),
            "pdf_files": len(list((ds / "supporting_documents").glob("*.pdf")))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    index = json.loads((ROOT / "scenario_index.json").read_text())
    base = load(ROOT / "set_01_clean_baseline")
    out = {}
    for name in dict.fromkeys(r["dataset"] for r in index["scenarios"]):
        ds = ROOT / name
        res = verify(ds)
        res["diff_vs_baseline"] = diff_vs_baseline(load(ds), base) if name != "set_01_clean_baseline" else {}
        out[name] = res
        problems = {k: v for k, v in res["checks"].items() if set(v) - {"OK"}}
        print(f"\n== {name}: {res['pdf_files']} PDF + {len(res['files'])} CSV, {res['csv_rows']} rows; "
              f"{sum(sum(v.values()) for v in res['checks'].values())} checks; {len(problems)} check type(s) not all OK")
        for k, v in problems.items():
            print(f"   {k}: {v} e.g. {res['examples'][k][:2]}")
        for f, d in res["diff_vs_baseline"].items():
            print(f"   diff {f}: +{len(d['added'])} -{len(d['removed'])} ~{len(d['modified'])}")
        for i in res["timing_items"]:
            print(f"   timing item: {i}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
