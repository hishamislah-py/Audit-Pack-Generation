"""Independent figures for the scenario specifications (own arithmetic; does not import or run the UC-042 engine).

Roll-forward per client: snapshot(d) = snapshot(prev recon day) + sum(signed txn executed in (prev 17:00, d 17:00]).
Sign rule restated from the published convention: CR = +, DR = -.
"""
import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

B = Path(sys.argv[1]) / "source_data"
rd = lambda f: list(csv.DictReader(open(B / f, encoding="utf-8", newline="")))
snaps = {(r["recon_date"], r["client_id"], r["currency"]): Decimal(r["balance"]) for r in rd("client_balance_snapshots_2026-09.csv")}
txns = rd("transactions_2026-09.csv")
days = ["2026-08-31"] + [r["calendar_date"] for r in rd("recon_calendar_2026-09.csv") if r["is_recon_day"] == "true"]
pt = lambda d: datetime.fromisoformat(f"{d}T17:00:00+01:00")


def rollforward(client, ccy, d, overrides=None, removed=()):
    prev = days[days.index(d) - 1]
    mv = Decimal("0.00")
    for t in txns:
        if t["client_id"] != client or t["currency"] != ccy or t["txn_id"] in removed:
            continue
        if pt(prev) < datetime.fromisoformat(t["executed_ts"]) <= pt(d):
            amt = Decimal((overrides or {}).get(t["txn_id"], t["amount"]))
            mv += amt if t["direction"] == "CR" else -amt
    return prev, snaps[(prev, client, ccy)], mv, snaps[(prev, client, ccy)] + mv, snaps[(d, client, ccy)]


cases = [
    ("TC02 C0006 08 Sep, TX-0908-00002 3053.61", "C0006", "GBP", "2026-09-08", {"TX-0908-00002": "3053.61"}, ()),
    ("TC02 C0006 09 Sep (next pair)", "C0006", "GBP", "2026-09-09", {"TX-0908-00002": "3053.61"}, ()),
    ("TC05 C0101 24 Sep, spends removed", "C0101", "EUR", "2026-09-24", None, ("TX-0924-00018", "TX-0924-00019", "TX-0924-00020")),
    ("TC05 C0104 24 Sep, spends removed", "C0104", "EUR", "2026-09-24", None, ("TX-0924-00018", "TX-0924-00019", "TX-0924-00020")),
    ("TC05 C0102 24 Sep (control)", "C0102", "EUR", "2026-09-24", None, ("TX-0924-00018", "TX-0924-00019", "TX-0924-00020")),
    ("TC06A C0007 17 Sep, TX-0917-00002 1480.07", "C0007", "GBP", "2026-09-17", {"TX-0917-00002": "1480.07"}, ()),
    ("TC06A C0007 18 Sep (next pair)", "C0007", "GBP", "2026-09-18", {"TX-0917-00002": "1480.07"}, ()),
    ("TC06B C0004 17 Sep (baseline roll-forward)", "C0004", "GBP", "2026-09-17", None, ()),
    ("TC06B C0004 18 Sep (baseline roll-forward)", "C0004", "GBP", "2026-09-18", None, ()),
]
for label, c, ccy, d, ov, rm in cases:
    prev, p, mv, exp, snap = rollforward(c, ccy, d, ov, rm)
    print(f"{label}: prev {prev} {p} + moves {mv} = {exp}; snapshot {snap}; expected-snapshot {exp - snap}")
# Sum of GBP client balances 17 Sep (requirement check for TC06B)
tot = sum(v for (d, c, ccy), v in snaps.items() if d == "2026-09-17" and ccy == "GBP")
print("GBP client total 17 Sep", tot)
