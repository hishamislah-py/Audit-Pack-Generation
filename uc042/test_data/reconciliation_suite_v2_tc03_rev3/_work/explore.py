"""Read-only exploration of the shared_baseline copy to pick scenario records. Writes nothing."""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

B = Path(sys.argv[1]) / "source_data"
F = {"IN-01": "recon_calendar_2026-09.csv", "IN-03": "client_balance_snapshots_2026-09.csv", "IN-04": "unallocated_register_2026-09.csv",
     "IN-05": "internal_recon_records_2026-09.csv", "IN-06": "external_recon_records_2026-09.csv", "IN-07": "bank_balance_confirmations_2026-09.csv",
     "IN-08": "bank_statements_eod_2026-09.csv", "IN-09": "bank_statement_entries_2026-09.csv", "IN-10": "sga_cashbook_entries_2026-09.csv",
     "IN-11": "transactions_2026-09.csv", "IN-12": "settlement_batches_2026-09.csv", "IN-13": "settlement_lines_2026-09.csv"}
D = {k: list(csv.DictReader(open(B / v, encoding="utf-8", newline=""))) for k, v in F.items()}

def show(title, rows, cols=None):
    print(f"--- {title} ({len(rows)})")
    for r in rows:
        print("   ", {k: r[k] for k in (cols or r.keys())})

days = [r["calendar_date"] for r in D["IN-01"] if r["is_recon_day"] == "true"]
print("recon days", len(days), days)

# equal-amount pairs (legitimate repeats?)
for fid, key in (("IN-11", ("client_id", "amount")), ("IN-10", ("account_id", "amount")), ("IN-09", ("account_id", "amount"))):
    c = Counter(tuple(r[k] for k in key) for r in D[fid])
    print(fid, "repeated", key, [k for k, n in c.items() if n > 1][:10])
c = Counter(r["amount"] for r in D["IN-11"])
print("IN-11 any repeated amount", [(k, n) for k, n in c.items() if n > 1][:10])

for d in ("0928", "0908", "0917", "0930"):
    show(f"IN-10 GBP {d}", [r for r in D["IN-10"] if r["ledger_entry_id"].startswith(f"LE-GBP-{d}")])
for d in ("0930",):
    show(f"IN-09 GBP {d}", [r for r in D["IN-09"] if r["statement_id"] == f"ST-SGA-GBP-01-2026{d}-EOD"],
         ["bank_entry_id", "booking_ts", "amount", "dc_indicator", "bank_reference", "end_to_end_ref", "narrative_text"])
    show(f"IN-09 EUR {d}", [r for r in D["IN-09"] if r["statement_id"] == f"ST-SGA-EUR-01-2026{d}-EOD"],
         ["bank_entry_id", "booking_ts", "amount", "dc_indicator", "bank_reference", "end_to_end_ref", "counterparty_name", "narrative_text"])
show("IN-12 0930", [r for r in D["IN-12"] if r["settlement_date"] == "2026-09-30"])
show("IN-13 SB-GBP-20260930", [r for r in D["IN-13"] if r["batch_id"] == "SB-GBP-20260930"])
show("IN-11 SB-GBP-20260930", [r for r in D["IN-11"] if r["settlement_batch_id"] == "SB-GBP-20260930"])
show("IN-11 LOAD_BANK 0908/0917/0928", [r for r in D["IN-11"] if r["txn_type"] == "LOAD_BANK" and r["executed_ts"][5:10] in ("09-08", "09-17", "09-28")])
for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-09-17", "2026-09-08", "2026-09-16", "2026-09-18"):
    for t in ("IN-05", "IN-06"):
        show(f"{t} {d}", [r for r in D[t] if r["recon_date"] == d],
             [k for k in D[t][0] if k not in ("actions_taken_text", "asset_pool_id", "method", "item_b", "item_c", "item_d", "d1_requirement", "d1_resource")])
# EUR scheme batches: spends per day and per client
for b in [r for r in D["IN-12"] if r["batch_id"].startswith("SB-EUR")]:
    tx = [t for t in D["IN-11"] if t["settlement_batch_id"] == b["batch_id"]]
    print(b["batch_id"], b["gross_amount"], b["total_adjustments"], b["net_amount_reported"], [(t["txn_id"], t["client_id"], t["txn_type"], t["amount"]) for t in tx])
show("IN-04", D["IN-04"])
show("refunds", [t for t in D["IN-11"] if t["txn_type"] == "REFUND"])
show("snap 0916-0918 GBP", [r for r in D["IN-03"] if r["recon_date"] in ("2026-09-16", "2026-09-17", "2026-09-18") and r["currency"] == "GBP"],
     ["snapshot_id", "balance"])
