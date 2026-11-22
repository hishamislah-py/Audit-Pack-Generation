"""Generate the UC-042 January–August 2026 ILLUSTRATIVE SYNTHETIC historical demonstration datasets.

Reads the UC-042 project read-only (schemas, money helpers, the September 2026 opening positions and the existing
synthetic standing documents). Writes only inside this package. Nothing in the project is modified.

    python generator/generate_history.py --project /path/to/uc042 --out .

Design (see README.md):
- New monthly activity is generated with the project's business conventions (flows, references, fee rules, 17:00
  Europe/London reconciliation point, convention D8 timings). No September record is copied.
- One seed per month. Months chain: each month opens on the previous month's closing positions.
- January opens on a documented synthetic position as at 31 Dec 2025 17:00.
- August closes exactly on the existing September 2026 opening positions (31 Aug 2026), which are read, never changed.
- Planted scenarios are explicit mutations of the generated clean month (recorded in mutations.json).
"""
import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

LON = ZoneInfo("Europe/London")
MONTHS = [f"2026-{m:02d}" for m in range(1, 9)]
# England & Wales bank holidays relevant to the window (synthetic calendar basis, same as the project's).
UK_BANK_HOLIDAYS = {date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
                    date(2026, 5, 4), date(2026, 5, 25), date(2026, 8, 31)}
SYNTHETIC = "ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS"
WATERMARK = "ILLUSTRATIVE SYNTHETIC DOCUMENT — NOT AN OFFICIAL RECORD"
ACCOUNTS = ["SGA-GBP-01", "SGA-EUR-01", "OWN-GBP-01", "OWN-EUR-01"]
CLIENTS = {"GBP": [f"C{n:04d}" for n in range(1, 9)], "EUR": [f"C{n:04d}" for n in range(101, 105)]}
FEE_RATE_ACQ, FEE_RATE_SCHEME = Decimal("0.0030"), Decimal("0.00155")  # project convention (GENERATION_NOTES)

# Synthetic demonstration opening position as at 31 Dec 2025 17:00 (GMT), cents. Documented in continuity_report.md.
JAN_OPENING_CLIENTS = {
    "GBP": dict(zip(CLIENTS["GBP"], [3612500, 3108040, 2895575, 2702010, 2681960, 2534215, 2440380, 2365320])),
    "EUR": dict(zip(CLIENTS["EUR"], [2214060, 1786300, 1597425, 1512215])),
}

# Month scenario plan (from the brief; S04 grounded in tests/test_baseline.py::test_equal_amount_is_not_a_link).
PLAN = {
    "2026-01": [], "2026-02": ["MISSING_EUR_STATEMENT"], "2026-03": ["UNEXPLAINED_GBP_DIFFERENCE"], "2026-04": [],
    "2026-05": ["MISSING_EUR_STATEMENT", "UNEXPLAINED_GBP_DIFFERENCE"], "2026-06": ["INCONSISTENT_SETTLEMENT_REFERENCE"],
    "2026-07": ["MISSING_EUR_STATEMENT", "INCONSISTENT_SETTLEMENT_REFERENCE"],
    "2026-08": ["MISSING_EUR_STATEMENT", "UNEXPLAINED_GBP_DIFFERENCE", "INCONSISTENT_SETTLEMENT_REFERENCE"],
}
UNEXPLAINED = {"2026-03": ("517.30", "SETTLE 0263"), "2026-05": ("1093.65", "SETTLE 0391"), "2026-08": ("276.90", "SETTLE 0528")}


def ts(d, h, m, s=0):
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=LON).isoformat()


def cents_str(c):
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"


def half_up_cents(gross, rate):
    v = (Decimal(gross) * rate).quantize(Decimal("1"), rounding="ROUND_HALF_UP")
    return int(v)


def to_cents(s):
    d = Decimal(s)
    return int((d * 100).to_integral_value())


class Project:
    """Read-only access to the UC-042 project: schemas and the September 2026 opening positions."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        sys.path.insert(0, str(self.root))
        from uc042lib import schema  # noqa: E402
        self.schema = schema
        base = self.root / "uc042_dataset" / "set_01_clean_baseline"
        self.base = base
        rd = lambda f: list(csv.DictReader(open(base / "source_data" / f, encoding="utf-8", newline="")))
        snaps = [r for r in rd("client_balance_snapshots_2026-09.csv") if r["recon_date"] == "2026-08-31"]
        self.sept_clients = {ccy: {r["client_id"]: to_cents(r["balance"]) for r in snaps if r["currency"] == ccy} for ccy in ("GBP", "EUR")}
        cash = [r for r in rd("sga_cashbook_entries_2026-09.csv") if r["entry_type"] == "OPENING_BALANCE"]
        self.sept_cash = {r["currency"]: to_cents(r["amount"]) for r in cash}
        eod = rd("bank_statements_eod_2026-09.csv")
        self.sept_bank = {}
        for acct in ACCOUNTS:
            first = min((s for s in eod if s["account_id"] == acct), key=lambda s: s["statement_date"])
            v = to_cents(first["opening_balance_amount"])
            self.sept_bank[acct] = v if first["opening_balance_dc"] == "C" else -v
        self.accounts = rd("account_inventory.csv")
        self.sept_opening_evidence = {
            "client_snapshots": [f"IN-03:{r['snapshot_id']}" for r in snaps],
            "cash_book_opening": [f"IN-10:{r['ledger_entry_id']}" for r in cash],
            "bank_first_statements": {a: min((s for s in eod if s["account_id"] == a), key=lambda s: s["statement_date"])["statement_id"] for a in ACCOUNTS}}

    def columns(self, fid):
        return [c[0] for c in self.schema.CSV_FILES[fid][2]]

    def filename(self, fid, period):
        return self.schema.CSV_FILES[fid][0].replace("_2026-09", f"_{period}")


class Month:
    """Generates one clean month of coherent activity from an opening state (cents)."""

    def __init__(self, proj, period, opening, seed, own_opening, final_targets=None):
        self.p, self.period, self.seed = proj, period, seed
        y, m = map(int, period.split("-"))
        self.days = [date(y, m, d) for d in range(1, monthrange(y, m)[1] + 1)]
        self.recon_days = [d for d in self.days if d.weekday() < 5 and d not in UK_BANK_HOLIDAYS]
        self.prev_end = self.days[0] - timedelta(days=1)
        self.rng = random.Random(seed)
        self.client = {c: dict(v) for c, v in opening["clients"].items()}
        self.cash = {"GBP": sum(self.client["GBP"].values()), "EUR": sum(self.client["EUR"].values())}
        self.bank = {"SGA-GBP-01": self.cash["GBP"], "SGA-EUR-01": self.cash["EUR"], **own_opening}
        self.opening = {"clients": {c: dict(v) for c, v in self.client.items()}, "cash": dict(self.cash), "bank": dict(self.bank)}
        self.unalloc_open = {"GBP": 0, "EUR": 0}
        self.rows = {fid: [] for fid in proj.schema.CSV_FILES}
        self.final_targets = final_targets  # August only: the September opening positions
        self.topups = {"GBP": 0, "EUR": 0}
        self.spends = {"GBP": [], "EUR": []}
        self._cash_seq, self._txn_seq = {}, 0
        start_total = {c: sum(v.values()) for c, v in self.client.items()}
        self.month_end_target = opening["month_end_target"]
        self.start_total = start_total
        # Unallocated receipt plan: one per currency on some months (receipt ~ a third into the month, allocated next recon day)
        self.unalloc_plan = []
        k = len(self.recon_days) // 3
        for ccy, months in (("GBP", {"2026-01", "2026-03", "2026-05", "2026-07"}), ("EUR", {"2026-02", "2026-04", "2026-06", "2026-08"})):
            if period in months:
                cents = self.rng.randint(20000, 120000) if ccy == "GBP" else self.rng.randint(15000, 60000)
                client = self.rng.choice(CLIENTS[ccy])
                self.unalloc_plan.append((f"UR-{period.replace('-', '')}-{ccy[0]}01", ccy, self.recon_days[k], (16, 20), cents, self.recon_days[k + 1], (9, 25), client))
        # Refund plan: one per currency per month, on a recon day after the 5th, refunding an earlier spend this month
        self.refund_day = {"GBP": self.recon_days[min(6, len(self.recon_days) - 3)], "EUR": self.recon_days[min(9, len(self.recon_days) - 2)]}

    # --- record helpers (same ID patterns and meanings as the project) -------------------------------------------
    def bank_entry(self, d, acct, suffix, h, m, cents, dc, ref, e2e="", counterparty="", narrative=""):
        ccy = acct.split("-")[1]
        prefix = f"BE-{ccy}" if acct.startswith("SGA") else f"BE-OWN-{ccy}"
        self.day_entries[acct].append({
            "bank_entry_id": f"{prefix}-{d:%m%d}-{suffix}", "statement_id": f"ST-{acct}-{d:%Y%m%d}-EOD", "account_id": acct,
            "booking_date": d.isoformat(), "booking_ts": ts(d, h, m), "value_date": d.isoformat(), "amount": cents_str(cents),
            "dc_indicator": dc, "currency": ccy, "bank_reference": ref, "end_to_end_ref": e2e, "counterparty_name": counterparty,
            "narrative_text": narrative or ref})
        self.bank[acct] += cents if dc == "C" else -cents

    def cash_entry(self, d, ccy, h, m, entry_type, cents, dc, ref):
        key = (ccy, d)
        self._cash_seq[key] = self._cash_seq.get(key, 0) + 1
        self.rows["IN-10"].append({"ledger_entry_id": f"LE-{ccy}-{d:%m%d}-{self._cash_seq[key]:04d}", "account_id": f"SGA-{ccy}-01",
                                   "posted_ts": ts(d, h, m), "entry_type": entry_type, "amount": cents_str(cents), "dc_indicator": dc,
                                   "currency": ccy, "payment_reference": ref})
        self.cash[ccy] += cents if dc == "D" else -cents

    def next_txn(self, d):
        self._txn_seq += 1
        return f"TX-{d:%m%d}-{self._txn_seq:05d}"

    def txn(self, tid, client, ccy, ttype, status, executed, cents, direction, auth="", clearing="", batch="", pref="", orig=""):
        self.rows["IN-11"].append({"txn_id": tid, "client_id": client, "txn_type": ttype, "status": status, "auth_ts": auth,
                                   "clearing_date": clearing, "executed_ts": executed, "amount": cents_str(cents), "direction": direction,
                                   "currency": ccy, "settlement_batch_id": batch, "payment_reference": pref, "original_txn_id": orig})
        self.client[ccy][client] += cents if direction == "CR" else -cents
        if self.client[ccy][client] < 0:
            raise AssertionError(f"{self.period}: client {client} would go negative on {tid}")

    def line(self, batch, n, ltype, cents, dc, ccy, txn_id="", fee=""):
        self.rows["IN-13"].append({"line_id": f"SL-{batch}-{n:04d}", "batch_id": batch, "line_type": ltype, "txn_id": txn_id,
                                   "fee_code": fee, "amount": cents_str(cents), "dc_indicator": dc, "currency": ccy})

    def batch(self, bid, ctype, d, ccy, direction, gross, fees, adj, net):
        self.rows["IN-12"].append({"batch_id": bid, "counterparty_type": ctype, "cycle_date": d.isoformat(), "settlement_date": d.isoformat(),
                                   "account_id": f"SGA-{ccy}-01", "currency": ccy, "direction": direction, "gross_amount": cents_str(gross),
                                   "total_fees": cents_str(fees), "total_adjustments": cents_str(adj), "net_amount_reported": cents_str(net),
                                   "expected_bank_reference": bid})

    def target_total(self, ccy, i):
        """Planned client total after recon day i (linear path to the month-end target; keeps balances stable)."""
        a, b = self.start_total[ccy], self.month_end_target[ccy]
        return a + (b - a) * (i + 1) // len(self.recon_days)

    # --- one day --------------------------------------------------------------------------------------------------
    def run_day(self, i, d):
        self._txn_seq = 0
        self.day_entries = {a: [] for a in ACCOUNTS}
        for ccy in ("GBP", "EUR"):
            self.run_currency(i, d, ccy)
        point = ts(d, 17, 0)
        for ccy in ("GBP", "EUR"):
            acct = f"SGA-{ccy}-01"
            for c in CLIENTS[ccy]:
                self.rows["IN-03"].append({"snapshot_id": f"CBS-{d:%Y%m%d}-{c}-{ccy}", "recon_date": d.isoformat(), "as_at_ts": point,
                                           "client_id": c, "asset_pool_id": self.p.schema.POOL_ID, "currency": ccy,
                                           "balance": cents_str(self.client[ccy][c])})
            req = sum(max(0, b) for b in self.client[ccy].values()) + self.unalloc_open[ccy]
            item_a = self.cash[ccy]
            if req != item_a or self.bank[acct] != item_a:
                raise AssertionError(f"{self.period} {d} {ccy}: requirement {req} ledger {item_a} bank {self.bank[acct]}")
            self.rows["IN-05"].append({
                "recon_run_id": f"IRR-EMONEY-{ccy}-{d:%Y%m%d}", "recon_date": d.isoformat(), "reconciliation_point_ts": point,
                "performed_at_ts": ts(d, 17, 35), "asset_pool_id": self.p.schema.POOL_ID, "currency": ccy, "method": "STANDARD",
                "requirement_reported": cents_str(req), "resource_reported": cents_str(item_a), "item_a": cents_str(item_a),
                "item_b": "0.00", "item_c": "0.00", "item_d": "0.00", "difference_reported": cents_str(item_a - req),
                "d1_requirement": "", "d1_resource": "",
                "actions_taken_text": "Client ledger extract and safeguarding cash book taken at 17:00; requirement and resource compared; no difference. D+1 comparison not performed (synthetic convention, gap G-R05).",
                "preparer_id": "U-12", "reviewer_id": "U-04"})
            self.rows["IN-07"].append({"statement_id": f"ST-{acct}-{d:%Y%m%d}-1700", "account_id": acct, "as_at_ts": point, "currency": ccy,
                                       "balance_amount": cents_str(abs(self.bank[acct])), "balance_dc_indicator": "C" if self.bank[acct] >= 0 else "D",
                                       "bank_statement_ref": f"BC/{acct}/{d:%Y%m%d}"})
            self.rows["IN-06"].append({
                "ext_recon_id": f"ERL-{acct}-{d:%Y%m%d}", "recon_date": d.isoformat(), "performed_at_ts": ts(d, 17, 50), "account_id": acct,
                "currency": ccy, "ledger_balance_reported": cents_str(self.cash[ccy]), "bank_statement_id": f"ST-{acct}-{d:%Y%m%d}-1700",
                "bank_balance_reported": cents_str(self.bank[acct]), "difference_reported": cents_str(self.bank[acct] - self.cash[ccy]),
                "timing_difference_claimed": "false", "preparer_id": "U-12"})
        for acct in ACCOUNTS:
            entries = sorted(self.day_entries[acct], key=lambda e: (e["booking_ts"], e["bank_entry_id"]))
            closing = self.bank[acct]
            opening = closing - sum(to_cents(e["amount"]) * (1 if e["dc_indicator"] == "C" else -1) for e in entries)
            self.rows["IN-08"].append({
                "statement_id": f"ST-{acct}-{d:%Y%m%d}-EOD", "account_id": acct, "statement_date": d.isoformat(), "as_at_ts": ts(d, 23, 59, 59),
                "currency": acct.split("-")[1], "opening_balance_amount": cents_str(abs(opening)), "opening_balance_dc": "C" if opening >= 0 else "D",
                "closing_balance_amount": cents_str(abs(closing)), "closing_balance_dc": "C" if closing >= 0 else "D",
                "entry_count": str(len(entries)), "bank_statement_ref": f"EOD/{acct}/{d:%Y%m%d}"})
            self.rows["IN-09"].extend(entries)

    def run_currency(self, i, d, ccy):
        rng, acct, own, gbp = self.rng, f"SGA-{ccy}-01", f"OWN-{ccy}-01", ccy == "GBP"
        clients = CLIENTS[ccy]
        for rid, rc, rday, _, cents, aday, (ah, am), client in self.unalloc_plan:  # allocation (client credited)
            if rc == ccy and d == aday:
                self.txn(self.next_txn(d), client, ccy, "LOAD_BANK", "EXECUTED", ts(d, ah, am), cents, "CR", pref=f"E2E-{ccy}-{rday:%m%d}-U01")
                self.unalloc_open[ccy] -= cents
        for k, (h, m) in enumerate([(9, 10), (11, 40)] if gbp else [(10, 0)], start=1):  # 1:1 bank-transfer loads
            cents = rng.randint(50000, 400000) if gbp else rng.randint(40000, 250000)
            client, e2e = rng.choice(clients), f"E2E-{ccy}-{d:%m%d}-L{k:02d}"
            self.bank_entry(d, acct, f"L{k:02d}", h, m, cents, "C", e2e, e2e, "Synthetic payer", "INBOUND TRANSFER")
            self.cash_entry(d, ccy, h, m, "BANK_LOAD", cents, "D", e2e)
            self.txn(self.next_txn(d), client, ccy, "LOAD_BANK", "EXECUTED", ts(d, h, m), cents, "CR", pref=e2e)
        aq = f"AQ-{ccy}-{d:%Y%m%d}"  # card loads, acquirer net settlement, own-funds top-up of fees
        loads = [(rng.choice(clients), rng.randint(10000, 260000) if gbp else rng.randint(10000, 130000)) for _ in range(4 if gbp else 2)]
        n = 0
        for k, (client, cents) in enumerate(loads):
            t, tid = ts(d, 8, 5 + 10 * k), self.next_txn(d)
            self.txn(tid, client, ccy, "LOAD_CARD", "SETTLED", t, cents, "CR", auth=t, clearing=d.isoformat(), batch=aq)
            n += 1
            self.line(aq, n, "TXN", cents, "C", ccy, txn_id=tid)
        gross = sum(c for _, c in loads)
        fee_acq, fee_sch = half_up_cents(gross, FEE_RATE_ACQ), half_up_cents(gross, FEE_RATE_SCHEME)
        for code, fee in (("ACQ_FEE", fee_acq), ("SCHEME_FEE", fee_sch)):
            n += 1
            self.line(aq, n, "FEE", fee, "D", ccy, fee=code)
        fees, net = fee_acq + fee_sch, gross - fee_acq - fee_sch
        self.batch(aq, "ACQUIRER", d, ccy, "TO_FIRM", gross, fees, 0, net)
        self.bank_entry(d, acct, "AQ1", 14, 0, net, "C", aq, "", "Synthetic Acquirer Ltd", f"CARD LOAD SETTLEMENT {aq}")
        self.cash_entry(d, ccy, 14, 0, "ACQUIRER_SETTLEMENT", net, "D", aq)
        topup = f"TOPUP-{ccy}-{d:%Y%m%d}"
        self.bank_entry(d, own, "TU1", 14, 30, fees, "D", topup, "", "Synthetic EMI Ltd", "TRANSFER TO SAFEGUARDING")
        self.bank_entry(d, acct, "TU1", 14, 30, fees, "C", topup, "", "Synthetic EMI Ltd", "OWN FUNDS TOP-UP")
        self.cash_entry(d, ccy, 14, 30, "OWN_FUNDS_TOPUP", fees, "D", topup)
        self.topups[ccy] += fees
        sb, settle = f"SB-{ccy}-{d:%Y%m%d}", ts(d, 15, 0)  # card spends and refunds settled to the scheme at 15:00 (D8)
        n, spend_total = 0, 0
        for k in range(6 if gbp else 3):
            cents = rng.randint(2000, 90000) if gbp else rng.randint(1500, 60000)
            eligible = [c for c in clients if self.client[ccy][c] >= cents + 50000]
            client, tid = rng.choice(eligible), self.next_txn(d)
            self.txn(tid, client, ccy, "SPEND", "SETTLED", settle, cents, "DR", auth=ts(d, 7 + k, 15), clearing=d.isoformat(), batch=sb)
            self.spends[ccy].append((tid, client, cents, d))
            n += 1
            spend_total += cents
            self.line(sb, n, "TXN", cents, "D", ccy, txn_id=tid)
        refund_total = 0
        if d == self.refund_day[ccy]:
            otid, oclient, ocents, _ = self.spends[ccy][rng.randrange(0, max(1, len(self.spends[ccy]) - (6 if gbp else 3)))]
            rcents = ocents if rng.random() < 0.5 else max(100, ocents // 2)
            rid = f"TX-{d:%m%d}-0R001"
            self.txn(rid, oclient, ccy, "REFUND", "SETTLED", settle, rcents, "CR", clearing=d.isoformat(), batch=sb, orig=otid)
            n += 1
            self.line(sb, n, "REFUND", rcents, "C", ccy, txn_id=rid)
            refund_total = rcents
        net = spend_total - refund_total
        self.batch(sb, "SCHEME", d, ccy, "FROM_FIRM", spend_total, 0, refund_total, net)
        self.bank_entry(d, acct, "SB1", 15, 0, net, "D", sb, "", "Synthetic Card Scheme", f"SCHEME SETTLEMENT {sb}")
        self.cash_entry(d, ccy, 15, 0, "SCHEME_SETTLEMENT", net, "C", sb)
        # Redemptions at 16:00: keep client totals on the planned path (balanced monthly flows)
        excess = sum(self.client[ccy].values()) - self.target_total(ccy, i)
        cap = 600000 if gbp else 250000
        k = 0
        while excess > 5000 and k < 2:
            k += 1
            client = max(clients, key=lambda c: (self.client[ccy][c], c))
            cents = min(excess, cap, self.client[ccy][client] - 100000)
            if cents <= 0:
                break
            e2e = f"E2E-{ccy}-{d:%m%d}-R{k:02d}"
            self.bank_entry(d, acct, f"R{k:02d}", 16, 0 + k, cents, "D", e2e, e2e, "Synthetic payee", "REDEMPTION")
            self.cash_entry(d, ccy, 16, 0 + k, "REDEMPTION", cents, "C", e2e)
            self.txn(self.next_txn(d), client, ccy, "REDEMPTION", "EXECUTED", ts(d, 16, 0 + k), cents, "DR", pref=e2e)
            excess -= cents
        for rid, rc, rday, (rh, rm), cents, aday, (ah, am), client in self.unalloc_plan:  # unallocated receipt (16:20)
            if rc == ccy and d == rday:
                e2e = f"E2E-{ccy}-{d:%m%d}-U01"
                self.bank_entry(d, acct, "U01", rh, rm, cents, "C", e2e, e2e, "Unknown remitter", "INBOUND TRANSFER")
                self.cash_entry(d, ccy, rh, rm, "UNALLOCATED_RECEIPT", cents, "D", e2e)
                self.unalloc_open[ccy] += cents
                self.rows["IN-04"].append({"receipt_id": rid, "bank_reference": e2e, "receipt_date": d.isoformat(), "receipt_ts": ts(d, rh, rm),
                                           "amount": cents_str(cents), "currency": ccy, "classification": "UNALLOCATED", "identified_date": "",
                                           "allocated_date": aday.isoformat(), "allocated_ts": ts(aday, ah, am), "client_id": client})
        if self.final_targets and d == self.recon_days[-1]:  # August only: close exactly on the September opening positions
            for j, c in enumerate(clients, start=1):
                diff = self.final_targets[ccy][c] - self.client[ccy][c]
                if diff == 0:
                    continue
                e2e = f"E2E-{ccy}-{d:%m%d}-B{j:02d}"
                if diff > 0:
                    self.bank_entry(d, acct, f"B{j:02d}", 16, 40, diff, "C", e2e, e2e, "Synthetic payer", "INBOUND TRANSFER")
                    self.cash_entry(d, ccy, 16, 40, "BANK_LOAD", diff, "D", e2e)
                    self.txn(self.next_txn(d), c, ccy, "LOAD_BANK", "EXECUTED", ts(d, 16, 40), diff, "CR", pref=e2e)
                else:
                    self.bank_entry(d, acct, f"B{j:02d}", 16, 40, -diff, "D", e2e, e2e, "Synthetic payee", "REDEMPTION")
                    self.cash_entry(d, ccy, 16, 40, "REDEMPTION", -diff, "C", e2e)
                    self.txn(self.next_txn(d), c, ccy, "REDEMPTION", "EXECUTED", ts(d, 16, 40), -diff, "DR", pref=e2e)

    def build(self):
        pid = f"PER-{self.period}"
        for d in self.days:
            recon = d in self.recon_days
            self.rows["IN-01"].append({"calendar_date": d.isoformat(), "period_id": pid, "is_recon_day": "true" if recon else "false",
                                       "non_recon_reason": "" if recon else ("WEEKEND" if d.weekday() >= 5 else "UK_BANK_HOLIDAY"),
                                       "calendar_basis": "SYNTHETIC: UK weekends and England & Wales bank holidays; no foreign-market closures assumed"})
        self.rows["IN-02"] = [dict(r) for r in self.p.accounts]  # standing account master data (unchanged accounts)
        for ccy in ("GBP", "EUR"):
            self.rows["IN-10"].append({"ledger_entry_id": f"LE-{ccy}-{self.prev_end:%m%d}-0000", "account_id": f"SGA-{ccy}-01",
                                       "posted_ts": ts(self.prev_end, 17, 0), "entry_type": "OPENING_BALANCE", "amount": cents_str(self.cash[ccy]),
                                       "dc_indicator": "D", "currency": ccy, "payment_reference": "OPENING"})
            for c in CLIENTS[ccy]:
                self.rows["IN-03"].append({"snapshot_id": f"CBS-{self.prev_end:%Y%m%d}-{c}-{ccy}", "recon_date": self.prev_end.isoformat(),
                                           "as_at_ts": ts(self.prev_end, 17, 0), "client_id": c, "asset_pool_id": self.p.schema.POOL_ID,
                                           "currency": ccy, "balance": cents_str(self.client[ccy][c])})
        for i, d in enumerate(self.recon_days):
            self.run_day(i, d)
        if self.unalloc_open != {"GBP": 0, "EUR": 0}:
            raise AssertionError("unallocated receipts must be allocated within the month")
        self.rows["IN-11"].sort(key=lambda r: (r["executed_ts"], r["txn_id"]))
        self.closing = {"clients": {c: dict(v) for c, v in self.client.items()}, "cash": dict(self.cash), "bank": dict(self.bank)}
        return self.rows


# --- scenario mutations (explicit, recorded; same op vocabulary as uc042lib/scenarios.py) --------------------------------
def first_on_or_after(days, day):
    return next(d for d in days if d.day >= day)


def mutations_for(month, kinds):
    rows, days, period = month.rows, month.recon_days, month.period
    pk = lambda fid, r: r[month.p.columns(fid)[0]]
    find = lambda fid, key: next(r for r in rows[fid] if pk(fid, r) == key)
    ops, expect = [], []

    def setf(fid, key, field, new, why):
        ops.append({"op": "set_field", "file_id": fid, "key": key, "field": field, "old": find(fid, key)[field], "new": new, "why": why})

    for kind in kinds:
        if kind == "MISSING_EUR_STATEMENT":
            d = first_on_or_after(days, 15)
            st = f"ST-SGA-EUR-01-{d:%Y%m%d}"
            ents = [e["bank_entry_id"] for e in rows["IN-09"] if e["statement_id"] == f"{st}-EOD"]
            ops += [{"op": "delete_record", "file_id": "IN-07", "key": f"{st}-1700", "why": "17:00 confirmation missing"},
                    {"op": "delete_record", "file_id": "IN-08", "key": f"{st}-EOD", "why": "end-of-day statement missing"}]
            ops += [{"op": "delete_record", "file_id": "IN-09", "key": e, "why": "entries of the missing statement"} for e in ents]
            expect.append({"scenario": kind, "date": d.isoformat(), "account": "SGA-EUR-01", "removed": {"IN-07": 1, "IN-08": 1, "IN-09": len(ents)},
                           "financial_impact": "none — evidence missing for one day; balances continue on the next statement",
                           "expected_engine": f"INSUFFICIENT_EVIDENCE on SGA-EUR-01 {d} (bank evidence); one Critical MISSING_BANK_EVIDENCE exception; "
                                              "evidence_completeness INCOMPLETE; no balance substituted"})
        elif kind == "UNEXPLAINED_GBP_DIFFERENCE":
            amt, ref = UNEXPLAINED[period]
            c = to_cents(amt)
            d1 = first_on_or_after(days, 17)
            d2 = days[days.index(d1) + 3]
            span = days[days.index(d1):days.index(d2)]
            deb = {"bank_entry_id": f"BE-GBP-{d1:%m%d}-X01", "statement_id": f"ST-SGA-GBP-01-{d1:%Y%m%d}-EOD", "account_id": "SGA-GBP-01",
                   "booking_date": d1.isoformat(), "booking_ts": ts(d1, 15, 20), "value_date": d1.isoformat(), "amount": amt, "dc_indicator": "D",
                   "currency": "GBP", "bank_reference": ref, "end_to_end_ref": "", "counterparty_name": "", "narrative_text": ref}
            rev = dict(deb, bank_entry_id=f"BE-GBP-{d2:%m%d}-X02", statement_id=f"ST-SGA-GBP-01-{d2:%Y%m%d}-EOD", booking_date=d2.isoformat(),
                       booking_ts=ts(d2, 10, 5), value_date=d2.isoformat(), dc_indicator="C", narrative_text=f"RETURN {ref}")
            ops += [{"op": "add_record", "file_id": "IN-09", "record": deb, "why": "bank debit with no internal counterpart (unexplained)"},
                    {"op": "add_record", "file_id": "IN-09", "record": rev, "why": "bank return of the same amount before month end (keeps month-end continuity)"}]
            for d in span:
                s = f"ST-SGA-GBP-01-{d:%Y%m%d}"
                eod = find("IN-08", f"{s}-EOD")
                if d != d1:
                    setf("IN-08", f"{s}-EOD", "opening_balance_amount", cents_str(to_cents(eod["opening_balance_amount"]) - c), "bank balance lower")
                setf("IN-08", f"{s}-EOD", "closing_balance_amount", cents_str(to_cents(eod["closing_balance_amount"]) - c), "bank balance lower")
                bc = find("IN-07", f"{s}-1700")
                setf("IN-07", f"{s}-1700", "balance_amount", cents_str(to_cents(bc["balance_amount"]) - c), "bank balance lower at 17:00")
                er = find("IN-06", f"ERL-SGA-GBP-01-{d:%Y%m%d}")
                setf("IN-06", er["ext_recon_id"], "bank_balance_reported", cents_str(to_cents(er["bank_balance_reported"]) - c), "firm reports the bank balance")
                setf("IN-06", er["ext_recon_id"], "difference_reported", cents_str(to_cents(er["difference_reported"]) - c), "firm reports the difference")
            e1 = find("IN-08", f"ST-SGA-GBP-01-{d1:%Y%m%d}-EOD")
            setf("IN-08", e1["statement_id"], "entry_count", str(int(e1["entry_count"]) + 1), "debit added")
            e2 = find("IN-08", f"ST-SGA-GBP-01-{d2:%Y%m%d}-EOD")
            setf("IN-08", e2["statement_id"], "opening_balance_amount", cents_str(to_cents(e2["opening_balance_amount"]) - c), "bank balance lower overnight")
            setf("IN-08", e2["statement_id"], "entry_count", str(int(e2["entry_count"]) + 1), "return added")
            expect.append({"scenario": kind, "account": "SGA-GBP-01", "amount": f"-{amt}", "bank_reference": ref, "counterparty": "(blank)",
                           "difference_days": [d.isoformat() for d in span], "debit_entry": deb["bank_entry_id"], "return_entry": rev["bank_entry_id"],
                           "financial_impact": f"bank balance {amt} below the ledger from {d1} 15:20 until the return at {d2} 10:05; nil at month end",
                           "expected_engine": f"C08 FAIL −{amt} on {len(span)} day(s) {span[0]}..{span[-1]} (NOT_EVIDENCED); unmatched bank entries "
                                              f"{deb['bank_entry_id']} and {rev['bank_entry_id']}; DISC-LOG FAIL (no log); cause unexplained"})
        elif kind == "INCONSISTENT_SETTLEMENT_REFERENCE":
            x = first_on_or_after(days, 10)
            target = f"SB-GBP-{days[0]:%Y%m%d}"
            entry = f"BE-GBP-{x:%m%d}-SB1"
            setf("IN-09", entry, "bank_reference", target, "bank entry for this batch carries an earlier batch's reference (amount unchanged)")
            expect.append({"scenario": kind, "account": "SGA-GBP-01", "batch_without_bank_reference": f"SB-GBP-{x:%Y%m%d}",
                           "batch_with_two_bank_entries": target, "bank_entry": entry,
                           "financial_impact": "none — amount and balances unchanged; only the reference is wrong",
                           "expected_engine": f"C11-BATCH-BANK FAIL for SB-GBP-{x:%Y%m%d} and {target} (no amount-only matching); "
                                              "cash-book link exceptions for the affected references"})
    return ops, expect


def apply(rows, ops, proj):
    for op in ops:
        fid = op["file_id"]
        pkc = proj.columns(fid)[0]
        if op["op"] == "delete_record":
            before = len(rows[fid])
            rows[fid] = [r for r in rows[fid] if r[pkc] != op["key"]]
            assert len(rows[fid]) == before - 1, op
        elif op["op"] == "add_record":
            rows[fid].append(dict(op["record"]))
        elif op["op"] == "set_field":
            hit = [r for r in rows[fid] if r[pkc] == op["key"]]
            assert len(hit) == 1 and hit[0][op["field"]] == op["old"], op
            hit[0][op["field"]] = op["new"]
    rows["IN-09"].sort(key=lambda e: (e["statement_id"].split("-")[-2], e["account_id"], e["booking_ts"], e["bank_entry_id"]))


# --- documents ------------------------------------------------------------------------------------------------------
def make_policy_v11(path):
    """Illustrative synthetic policy v1.1 (assumption A1): same rules as v1.2, effective before it. Watermarked."""
    from reportlab import rl_config
    rl_config.invariant = 1
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    st = getSampleStyleSheet()

    def on_page(c, _d):
        c.saveState()
        c.setFont("Helvetica-Bold", 13)
        c.setFillGray(0.55)
        c.translate(300, 430)
        c.rotate(35)
        c.drawCentredString(0, 0, WATERMARK)
        c.restoreState()
        c.setFont("Helvetica", 8)
        c.drawString(56, 28, "SYNTHETIC DOCUMENT - UC-042 POC - not a real bank or firm document")
    story = [Paragraph(WATERMARK, st["Heading2"]), Paragraph("Safeguarding reconciliation policy (synthetic)", st["Title"]),
             Paragraph("Synthetic EMI Ltd (fictional). Illustrative predecessor of policy v1.2, created for the January-August 2026 "
                       "historical demonstration. Its contents are an assumption (same rules as v1.2), not a recovered document.", st["Normal"]),
             Spacer(1, 12), Paragraph("Key details", st["Heading2"])]
    for k, v in [("Document version", "1.1"), ("Effective date", "2025-10-01"), ("Safeguarding method", "SEGREGATION"),
                 ("Reconciliation method", "STANDARD"), ("Reconciliation point", "17:00 Europe/London"),
                 ("Frequency", "Each reconciliation day"), ("Internal reconciliation basis", "Per currency")]:
        story.append(Paragraph(f"{k}: {v}", st["Normal"]))
    story += [Spacer(1, 12), Paragraph("Superseded by v1.2 from 2026-05-07. " + WATERMARK, st["Normal"])]
    SimpleDocTemplate(str(path), pagesize=A4, title="Safeguarding reconciliation policy v1.1 (ILLUSTRATIVE SYNTHETIC)",
                      author="UC-042 historical demo generator", creator="UC-042 historical demo generator").build(story, onFirstPage=on_page, onLaterPages=on_page)


def documents_for(period, proj, docs_dir):
    """Supporting PDFs per month: reuse applicable existing synthetic standing documents; mark the rest unavailable."""
    y, m = map(int, period.split("-"))
    start, end = date(y, m, 1), date(y, m, monthrange(y, m)[1])
    base = proj.base / "supporting_documents"
    inv = []
    for fid, fname in (("IN-15", "ack_letter_SGA-GBP-01.pdf"), ("IN-16", "ack_letter_SGA-EUR-01.pdf")):
        shutil.copyfile(base / fname, docs_dir / fname)
        inv.append({"file_id": fid, "filename": fname, "status": "REUSED_STANDING_DOCUMENT",
                    "basis": "existing synthetic acknowledgement letter dated 2024-03-01; account open since 2024-03-01, unchanged"})
    v12, v11 = date(2026, 5, 7), None
    if start < v12:
        fname = "safeguarding_reconciliation_policy_v1.1.pdf"
        make_policy_v11(docs_dir / fname)
        inv.append({"file_id": "IN-17", "filename": fname, "status": "ILLUSTRATIVE_SYNTHETIC_DOCUMENT",
                    "applies": f"{start} to {min(end, v12 - timedelta(days=1))}",
                    "basis": "assumption A1: no pre-v1.2 policy exists in the project; watermarked illustrative v1.1 with v1.2's rules"})
    if end >= v12:
        fname = "safeguarding_reconciliation_policy_v1.2.pdf"
        shutil.copyfile(base / fname, docs_dir / fname)
        inv.append({"file_id": "IN-17", "filename": fname, "status": "REUSED_STANDING_DOCUMENT",
                    "applies": f"{max(start, v12)} to {end}", "basis": "existing synthetic policy v1.2, effective 2026-05-07"})
    inv.append({"file_id": "IN-18", "filename": "", "status": "UNAVAILABLE",
                "basis": "no governance register for this month exists; the only register is the September 2026 document "
                         "(allocation from 2026-05-07); not reused or fabricated (optional evidence)"})
    prev = f"{y}-{m - 1:02d}" if m > 1 else "2025-12"
    inv.append({"file_id": "IN-19", "filename": "", "status": "UNAVAILABLE",
                "basis": f"no REP027 receipt for the {prev} return exists; regulatory receipts are not fabricated (optional evidence)"})
    return inv


# --- writing ----------------------------------------------------------------------------------------------------------
def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_month(proj, month, out, ops, expect, doc_inv):
    period = month.period
    mdir = out / period
    src = mdir / "source_documents" / "source_data"
    docs = mdir / "source_documents" / "supporting_documents"
    if mdir.exists():
        shutil.rmtree(mdir)
    src.mkdir(parents=True)
    docs.mkdir(parents=True)
    for fid in proj.schema.CSV_FILES:
        with open(src / proj.filename(fid, period), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=proj.columns(fid), lineterminator="\n")
            w.writeheader()
            w.writerows(month.rows[fid])
    doc_inv = documents_for(period, proj, docs)
    pid = f"PER-{period}"
    man = []
    for fid, (fname, desc, _) in proj.schema.CSV_FILES.items():
        fn = proj.filename(fid, period)
        man.append({"file_id": fid, "filename": fn, "relative_path": f"source_data/{fn}", "format": "CSV", "evidence_kind": "RAW_SOURCE",
                    "requirement": "REQUIRED", "description": desc, "reporting_period": pid, "record_count": str(len(month.rows[fid])),
                    "record_unit": "data_rows", "sha256": sha256(src / fn), "synthetic": "YES"})
    from pypdf import PdfReader
    for d in doc_inv:
        if d["filename"]:
            p = docs / d["filename"]
            man.append({"file_id": d["file_id"], "filename": d["filename"], "relative_path": f"supporting_documents/{d['filename']}", "format": "PDF",
                        "evidence_kind": "SUPPORTING_DOCUMENT", "requirement": proj.schema.PDF_FILES[d["file_id"]][2],
                        "description": proj.schema.PDF_FILES[d["file_id"]][1] if d["file_id"] != "IN-17" else f"Safeguarding reconciliation policy {d['filename'].split('_v')[1][:-4]}",
                        "reporting_period": pid, "record_count": str(len(PdfReader(str(p)).pages)), "record_unit": "pages", "sha256": sha256(p), "synthetic": "YES"})
    with open(mdir / "source_documents" / "manifest.csv", "w", encoding="utf-8", newline="") as f:  # engine-format manifest
        w = csv.DictWriter(f, fieldnames=list(man[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(man)
    (mdir / "mutations.json").write_text(json.dumps(ops, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return man, doc_inv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    proj, out = Project(a.project), Path(a.out)
    # Planned month-end client totals: linear path from the 31 Dec 2025 opening to the existing 31 Aug 2026 position.
    jan_tot = {c: sum(v.values()) for c, v in JAN_OPENING_CLIENTS.items()}
    sep_tot = {c: sum(v.values()) for c, v in proj.sept_clients.items()}
    ends = {p: {c: jan_tot[c] + (sep_tot[c] - jan_tot[c]) * (k + 1) // 8 for c in jan_tot} for k, p in enumerate(MONTHS)}
    # Seeded, non-round variation of the Jan–Jul month-end targets (August stays exactly on the September opening).
    wiggle = random.Random(20251231)
    for p in MONTHS[:-1]:
        ends[p] = {"GBP": ends[p]["GBP"] + wiggle.randint(-420000, 420000), "EUR": ends[p]["EUR"] + wiggle.randint(-160000, 160000)}
    # Pass 1: total own-funds top-ups (independent of own-funds balances), so August closes on September's own-funds opening.
    def run_all(own_open):
        state = {"clients": JAN_OPENING_CLIENTS}
        own = dict(own_open)
        months = []
        for k, p in enumerate(MONTHS):
            seed = int(p.replace("-", "")) * 100 + 42
            mo = Month(proj, p, dict(state, month_end_target=ends[p]), seed, own,
                       final_targets=proj.sept_clients if p == "2026-08" else None)
            mo.build()
            months.append(mo)
            state = {"clients": mo.closing["clients"]}
            own = {a_: mo.closing["bank"][a_] for a_ in ("OWN-GBP-01", "OWN-EUR-01")}
        return months
    probe = run_all({"OWN-GBP-01": 0, "OWN-EUR-01": 0})
    tops = {c: sum(m.topups[c] for m in probe) for c in ("GBP", "EUR")}
    own_open = {"OWN-GBP-01": proj.sept_bank["OWN-GBP-01"] + tops["GBP"], "OWN-EUR-01": proj.sept_bank["OWN-EUR-01"] + tops["EUR"]}
    months = run_all(own_open)
    summary = {}
    for mo in months:
        clean_closing = mo.closing
        ops, expect = mutations_for(mo, PLAN[mo.period])
        apply(mo.rows, ops, proj)
        man, doc_inv = write_month(proj, mo, out, ops, expect, None)
        summary[mo.period] = {"month": mo, "ops": ops, "expect": expect, "manifest": man, "documents": doc_inv,
                              "opening": mo.opening, "closing": clean_closing, "seed": mo.seed}
    (out / "generator" / "_last_run.json").write_text(json.dumps({p: {
        "seed": s["seed"], "opening": s["opening"], "closing": s["closing"], "expect": s["expect"], "documents": s["documents"],
        "recon_days": [d.isoformat() for d in s["month"].recon_days], "days": len(s["month"].days), "prev_end": s["month"].prev_end.isoformat(),
        "topups": s["month"].topups, "manifest": s["manifest"], "ops_count": len(s["ops"])} for p, s in summary.items()},
        indent=1, default=str) + "\n", encoding="utf-8")
    print("own-funds opening (31 Dec 2025):", {k: cents_str(v) for k, v in own_open.items()})
    for p, s in summary.items():
        print(p, "recon days", len(s["month"].recon_days), "| rows", sum(len(v) for v in s["month"].rows.values()), "| ops", len(s["ops"]),
              "| scenarios", PLAN[p] or ["CLEAN"])


if __name__ == "__main__":
    main()
