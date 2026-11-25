"""Generate the UC-042 clean synthetic baseline (Set 1).

Usage (from the uc042/ folder):
    python -m uc042lib.generate                      # writes uc042_dataset/set_01_clean_baseline
    python -m uc042lib.generate --out /tmp/somewhere

All data is synthetic. Nothing here describes Moorwand or any real firm, bank, client or account.
Money is handled as integer cents internally and written as 2dp decimal strings.
"""
import argparse
import csv
import hashlib
import json
import random
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from . import schema
from .money import fmt, round_half_up

LON = ZoneInfo(schema.TZ)
SEED = 20260930
PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT / "uc042_dataset" / "set_01_clean_baseline"

UK_BANK_HOLIDAYS = {date(2026, 8, 31), date(2026, 12, 25), date(2026, 12, 28)}  # synthetic list; none in September
PERIOD_DAYS = [date(2026, 9, d) for d in range(1, 31)]
RECON_DAYS = [d for d in PERIOD_DAYS if d.weekday() < 5 and d not in UK_BANK_HOLIDAYS]

CLIENTS = {
    "GBP": dict(zip([f"C{n:04d}" for n in range(1, 9)],
                    [4000000, 3500000, 3250000, 3000000, 3000000, 2850000, 2750000, 2650000])),
    "EUR": dict(zip([f"C{n:04d}" for n in range(101, 105)], [2500000, 2000000, 1800000, 1700000])),
}
OPEN_SGA = {"GBP": 25000000, "EUR": 8000000}       # 31 Aug 2026 17:00, cents
OPEN_OWN = {"GBP": 50000000, "EUR": 15000000}
ACCOUNTS = {
    "SGA-GBP-01": ("RELEVANT_FUNDS_BANK", "GBP", "****4471", "Synthetic EMI Ltd Safeguarding Account (GBP)", "ACK-INST01-4471"),
    "SGA-EUR-01": ("RELEVANT_FUNDS_BANK", "EUR", "****8823", "Synthetic EMI Ltd Safeguarding Account (EUR)", "ACK-INST01-8823"),
    "OWN-GBP-01": ("OWN_FUNDS", "GBP", "****1190", "", ""),
    "OWN-EUR-01": ("OWN_FUNDS", "EUR", "****1206", "", ""),
}
INSTITUTION = ("INST-01", "Example Bank plc", "1 Example Street, London EC0A 0AA (fictional)",
               "safeguarding@example-bank.invalid", "+44 20 0000 0000", "RELEVANT_FUNDS_BANK")
UNALLOCATED_PLAN = [  # receipt id, ccy, receipt (day, h, m), cents, allocation (day, h, m), client
    ("UR-0001", "GBP", (11, 16, 30), 75000, (14, 9, 30), "C0007"),
    ("UR-0002", "EUR", (23, 16, 10), 40000, (24, 9, 15), "C0102"),
]
FEE_RATE_ACQ = Decimal("0.0030")
FEE_RATE_SCHEME = Decimal("0.00155")


def money(cents):
    return fmt(Decimal(cents).scaleb(-2))


def ts(d, h, m, s=0):
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=LON).isoformat()


class Baseline:
    def __init__(self, seed=SEED):
        self.rng = random.Random(seed)
        self.client = {c: dict(v) for c, v in CLIENTS.items()}
        self.cash = dict(OPEN_SGA)
        self.bank = {"SGA-GBP-01": OPEN_SGA["GBP"], "SGA-EUR-01": OPEN_SGA["EUR"],
                     "OWN-GBP-01": OPEN_OWN["GBP"], "OWN-EUR-01": OPEN_OWN["EUR"]}
        self.unalloc_open = {"GBP": 0, "EUR": 0}
        self.rows = {fid: [] for fid in schema.CSV_FILES}
        self.first_eur_spend = None
        self._cash_seq = {}

    # --- record helpers -------------------------------------------------
    def bank_entry(self, d, acct, suffix, h, m, cents, dc, ref, e2e="", counterparty="", narrative=""):
        ccy = ACCOUNTS[acct][1]
        prefix = f"BE-{ccy}" if acct.startswith("SGA") else f"BE-OWN-{ccy}"
        self.day_entries[acct].append({
            "bank_entry_id": f"{prefix}-{d:%m%d}-{suffix}", "statement_id": f"ST-{acct}-{d:%Y%m%d}-EOD",
            "account_id": acct, "booking_date": d.isoformat(), "booking_ts": ts(d, h, m), "value_date": d.isoformat(),
            "amount": money(cents), "dc_indicator": dc, "currency": ccy, "bank_reference": ref,
            "end_to_end_ref": e2e, "counterparty_name": counterparty, "narrative_text": narrative or ref})
        self.bank[acct] += cents if dc == "C" else -cents

    def cash_entry(self, d, acct, h, m, entry_type, cents, dc, ref):
        ccy = ACCOUNTS[acct][1]
        key = (ccy, d)
        self._cash_seq[key] = self._cash_seq.get(key, 0) + 1
        self.rows["IN-10"].append({
            "ledger_entry_id": f"LE-{ccy}-{d:%m%d}-{self._cash_seq[key]:04d}", "account_id": acct,
            "posted_ts": ts(d, h, m), "entry_type": entry_type, "amount": money(cents), "dc_indicator": dc,
            "currency": ccy, "payment_reference": ref})
        self.cash[ccy] += cents if dc == "D" else -cents

    def next_txn(self, d):
        self._txn_seq += 1
        if d == date(2026, 9, 2) and self._txn_seq == 44:  # reserved for the spec key record
            self._txn_seq += 1
        return f"TX-{d:%m%d}-{self._txn_seq:05d}"

    def txn(self, txn_id, client, ccy, ttype, status, executed, cents, direction, auth="", clearing="", batch="", pref="", orig=""):
        self.rows["IN-11"].append({
            "txn_id": txn_id, "client_id": client, "txn_type": ttype, "status": status, "auth_ts": auth,
            "clearing_date": clearing, "executed_ts": executed, "amount": money(cents), "direction": direction,
            "currency": ccy, "settlement_batch_id": batch, "payment_reference": pref, "original_txn_id": orig})
        delta = cents if direction == "CR" else -cents
        self.client[ccy][client] += delta
        if self.client[ccy][client] < 0:
            raise AssertionError(f"client {client} would go negative on {txn_id}")

    def line(self, batch, n, ltype, cents, dc, ccy, txn_id="", fee=""):
        self.rows["IN-13"].append({"line_id": f"SL-{batch}-{n:04d}", "batch_id": batch, "line_type": ltype,
                                   "txn_id": txn_id, "fee_code": fee, "amount": money(cents), "dc_indicator": dc, "currency": ccy})

    def batch(self, batch_id, ctype, d, acct, ccy, direction, gross, fees, adj, net):
        self.rows["IN-12"].append({
            "batch_id": batch_id, "counterparty_type": ctype, "cycle_date": d.isoformat(), "settlement_date": d.isoformat(),
            "account_id": acct, "currency": ccy, "direction": direction, "gross_amount": money(gross),
            "total_fees": money(fees), "total_adjustments": money(adj), "net_amount_reported": money(net),
            "expected_bank_reference": batch_id})

    # --- one reconciliation day -----------------------------------------
    def run_day(self, i, d):
        self._txn_seq = 0
        self.day_entries = {a: [] for a in ACCOUNTS}
        for ccy in ("GBP", "EUR"):
            self.run_currency(i, d, ccy)
        point = ts(d, 17, 0)
        for ccy in ("GBP", "EUR"):
            acct = f"SGA-{ccy}-01"
            for c, bal in self.client[ccy].items():
                self.rows["IN-03"].append({"snapshot_id": f"CBS-{d:%Y%m%d}-{c}-{ccy}", "recon_date": d.isoformat(),
                                           "as_at_ts": point, "client_id": c, "asset_pool_id": schema.POOL_ID,
                                           "currency": ccy, "balance": money(bal)})
            requirement = sum(max(0, b) for b in self.client[ccy].values()) + self.unalloc_open[ccy]
            item_a = self.cash[ccy]
            if requirement != item_a or self.bank[acct] != item_a:
                raise AssertionError(f"baseline invariant broken {d} {ccy}: req {requirement} cash {item_a} bank {self.bank[acct]}")
            self.rows["IN-05"].append({
                "recon_run_id": f"IRR-EMONEY-{ccy}-{d:%Y%m%d}", "recon_date": d.isoformat(), "reconciliation_point_ts": point,
                "performed_at_ts": ts(d, 17, 35), "asset_pool_id": schema.POOL_ID, "currency": ccy, "method": "STANDARD",
                "requirement_reported": money(requirement), "resource_reported": money(item_a), "item_a": money(item_a),
                "item_b": "0.00", "item_c": "0.00", "item_d": "0.00", "difference_reported": money(item_a - requirement),
                "d1_requirement": "", "d1_resource": "",
                "actions_taken_text": "Client ledger extract and safeguarding cash book taken at 17:00; requirement and resource compared; no difference. D+1 comparison not performed (synthetic convention, gap G-R05).",
                "preparer_id": "U-12", "reviewer_id": "U-04"})
            self.rows["IN-07"].append({"statement_id": f"ST-{acct}-{d:%Y%m%d}-1700", "account_id": acct, "as_at_ts": point,
                                       "currency": ccy, "balance_amount": money(abs(self.bank[acct])),
                                       "balance_dc_indicator": "C" if self.bank[acct] >= 0 else "D",
                                       "bank_statement_ref": f"BC/{acct}/{d:%Y%m%d}"})
            self.rows["IN-06"].append({
                "ext_recon_id": f"ERL-{acct}-{d:%Y%m%d}", "recon_date": d.isoformat(), "performed_at_ts": ts(d, 17, 50),
                "account_id": acct, "currency": ccy, "ledger_balance_reported": money(self.cash[ccy]),
                "bank_statement_id": f"ST-{acct}-{d:%Y%m%d}-1700", "bank_balance_reported": money(self.bank[acct]),
                "difference_reported": money(self.bank[acct] - self.cash[ccy]), "timing_difference_claimed": "false",
                "preparer_id": "U-12"})
        for acct in ACCOUNTS:  # end-of-day statements, all four accounts
            entries = sorted(self.day_entries[acct], key=lambda e: e["booking_ts"])
            closing = self.bank[acct]
            opening = closing - sum(int(Decimal(e["amount"]) * 100) * (1 if e["dc_indicator"] == "C" else -1) for e in entries)
            self.rows["IN-08"].append({
                "statement_id": f"ST-{acct}-{d:%Y%m%d}-EOD", "account_id": acct, "statement_date": d.isoformat(),
                "as_at_ts": ts(d, 23, 59, 59), "currency": ACCOUNTS[acct][1],
                "opening_balance_amount": money(abs(opening)), "opening_balance_dc": "C" if opening >= 0 else "D",
                "closing_balance_amount": money(abs(closing)), "closing_balance_dc": "C" if closing >= 0 else "D",
                "entry_count": str(len(entries)), "bank_statement_ref": f"EOD/{acct}/{d:%Y%m%d}"})
            self.rows["IN-09"].extend(entries)

    def run_currency(self, i, d, ccy):
        rng, acct, own = self.rng, f"SGA-{ccy}-01", f"OWN-{ccy}-01"
        clients = list(CLIENTS[ccy])
        gbp = ccy == "GBP"
        # Allocation of earlier unallocated receipts (client credited at allocation time)
        for rid, rc, (rday, rh, rm), cents, (aday, ah, am), client in UNALLOCATED_PLAN:
            if rc == ccy and d.day == aday:
                e2e = f"E2E-{ccy}-09{rday:02d}-U01"
                self.txn(self.next_txn(d), client, ccy, "LOAD_BANK", "EXECUTED", ts(d, ah, am), cents, "CR", pref=e2e)
                self.unalloc_open[ccy] -= cents
        # 1:1 bank-transfer loads
        for k, (h, m) in enumerate([(9, 10), (11, 40)] if gbp else [(10, 0)], start=1):
            cents = rng.randint(50000, 400000) if gbp else rng.randint(40000, 250000)
            client, e2e = rng.choice(clients), f"E2E-{ccy}-{d:%m%d}-L{k:02d}"
            self.bank_entry(d, acct, f"L{k:02d}", h, m, cents, "C", e2e, e2e, "Synthetic payer", "INBOUND TRANSFER")
            self.cash_entry(d, acct, h, m, "BANK_LOAD", cents, "D", e2e)
            self.txn(self.next_txn(d), client, ccy, "LOAD_BANK", "EXECUTED", ts(d, h, m), cents, "CR", pref=e2e)
        # Card loads settled by the acquirer, net of fees, topped up from own funds
        aq = f"AQ-{ccy}-{d:%Y%m%d}"
        if gbp and d.day == 8:
            loads = [(c, 250000) for c in ("C0001", "C0002", "C0003", "C0004")]
        else:
            loads = [(rng.choice(clients), rng.randint(10000, 260000) if gbp else rng.randint(10000, 130000))
                     for _ in range(4 if gbp else 2)]
        n = 0
        for k, (client, cents) in enumerate(loads):
            t = ts(d, 8, 5 + 10 * k)
            tid = self.next_txn(d)
            self.txn(tid, client, ccy, "LOAD_CARD", "SETTLED", t, cents, "CR", auth=t, clearing=d.isoformat(), batch=aq)
            n += 1
            self.line(aq, n, "TXN", cents, "C", ccy, txn_id=tid)
        gross = sum(c for _, c in loads)
        if gbp and d.day == 8:
            fee_acq, fee_sch = 3000, 1550
        else:
            fee_acq = int(round_half_up(Decimal(gross) / 100 * FEE_RATE_ACQ) * 100)
            fee_sch = int(round_half_up(Decimal(gross) / 100 * FEE_RATE_SCHEME) * 100)
        for code, fee in (("ACQ_FEE", fee_acq), ("SCHEME_FEE", fee_sch)):
            n += 1
            self.line(aq, n, "FEE", fee, "D", ccy, fee=code)
        fees, net = fee_acq + fee_sch, gross - fee_acq - fee_sch
        self.batch(aq, "ACQUIRER", d, acct, ccy, "TO_FIRM", gross, fees, 0, net)
        self.bank_entry(d, acct, "AQ1", 14, 0, net, "C", aq, "", "Synthetic Acquirer Ltd", f"CARD LOAD SETTLEMENT {aq}")
        self.cash_entry(d, acct, 14, 0, "ACQUIRER_SETTLEMENT", net, "D", aq)
        topup = f"TOPUP-{ccy}-{d:%Y%m%d}"
        self.bank_entry(d, own, "TU1", 14, 30, fees, "D", topup, "", "Synthetic EMI Ltd", "TRANSFER TO SAFEGUARDING")
        self.bank_entry(d, acct, "TU1", 14, 30, fees, "C", topup, "", "Synthetic EMI Ltd", "OWN FUNDS TOP-UP")
        self.cash_entry(d, acct, 14, 30, "OWN_FUNDS_TOPUP", fees, "D", topup)
        # Card spends and refunds settled to the scheme at 15:00 (client balance changes then, convention D8)
        sb, settle = f"SB-{ccy}-{d:%Y%m%d}", ts(d, 15, 0)
        count = 6 if gbp else 3
        amounts = [rng.randint(2000, 90000) if gbp else rng.randint(1500, 60000) for _ in range(count)]
        if gbp and d.day == 10:  # spec key record: net debit 3,412.75
            amounts = [rng.randint(2000, 90000) for _ in range(5)]
            while not (2000 <= 341275 - sum(amounts) <= 150000):
                amounts = [rng.randint(2000, 60000) for _ in range(5)]
            amounts.append(341275 - sum(amounts))
        n, spend_total = 0, 0
        for k, cents in enumerate(amounts):
            if gbp and d.day == 2 and k == 0:
                tid, client, cents = "TX-0902-00044", "C0002", 6000
            else:
                tid, client = self.next_txn(d), rng.choice(clients)
            auth = ts(d, 7 + k, 15)
            self.txn(tid, client, ccy, "SPEND", "SETTLED", settle, cents, "DR", auth=auth, clearing=d.isoformat(), batch=sb)
            if ccy == "EUR" and d.day == 3 and self.first_eur_spend is None:
                self.first_eur_spend = (tid, client, cents)
            n += 1
            spend_total += cents
            self.line(sb, n, "TXN", cents, "D", ccy, txn_id=tid)
        refunds = []
        if gbp and d.day == 9:
            refunds.append(("TX-0909-0R001", "TX-0902-00044", "C0002", 6000))
        if ccy == "EUR" and d.day == 16:
            tid, client, cents = self.first_eur_spend
            refunds.append(("TX-0916-0R001", tid, client, cents))
        for rid, orig, client, cents in refunds:
            self.txn(rid, client, ccy, "REFUND", "SETTLED", settle, cents, "CR", clearing=d.isoformat(), batch=sb, orig=orig)
            n += 1
            self.line(sb, n, "REFUND", cents, "C", ccy, txn_id=rid)
        refund_total = sum(r[3] for r in refunds)
        net = spend_total - refund_total
        self.batch(sb, "SCHEME", d, acct, ccy, "FROM_FIRM", spend_total, 0, refund_total, net)
        self.bank_entry(d, acct, "SB1", 15, 0, net, "D", sb, "", "Synthetic Card Scheme", f"SCHEME SETTLEMENT {sb}")
        self.cash_entry(d, acct, 15, 0, "SCHEME_SETTLEMENT", net, "C", sb)
        # Redemption on alternate reconciliation days
        if i % 2 == 1:
            cents = rng.randint(30000, 250000) if gbp else rng.randint(20000, 120000)
            client = max(clients, key=lambda c: (self.client[ccy][c], c))
            e2e = f"E2E-{ccy}-{d:%m%d}-R01"
            self.bank_entry(d, acct, "R01", 16, 0, cents, "D", e2e, e2e, "Synthetic payee", "REDEMPTION")
            self.cash_entry(d, acct, 16, 0, "REDEMPTION", cents, "C", e2e)
            self.txn(self.next_txn(d), client, ccy, "REDEMPTION", "EXECUTED", ts(d, 16, 0), cents, "DR", pref=e2e)
        # Unallocated receipts (cash received, not yet attributed to a client)
        for rid, rc, (rday, rh, rm), cents, (aday, ah, am), client in UNALLOCATED_PLAN:
            if rc == ccy and d.day == rday:
                e2e = f"E2E-{ccy}-{d:%m%d}-U01"
                self.bank_entry(d, acct, "U01", rh, rm, cents, "C", e2e, e2e, "Unknown remitter", "INBOUND TRANSFER")
                self.cash_entry(d, acct, rh, rm, "UNALLOCATED_RECEIPT", cents, "D", e2e)
                self.unalloc_open[ccy] += cents
                ad = date(2026, 9, aday)
                self.rows["IN-04"].append({
                    "receipt_id": rid, "bank_reference": e2e, "receipt_date": d.isoformat(), "receipt_ts": ts(d, rh, rm),
                    "amount": money(cents), "currency": ccy, "classification": "UNALLOCATED", "identified_date": "",
                    "allocated_date": ad.isoformat(), "allocated_ts": ts(ad, ah, am), "client_id": client})

    def build(self):
        for d in PERIOD_DAYS:
            recon = d in RECON_DAYS
            self.rows["IN-01"].append({"calendar_date": d.isoformat(), "period_id": schema.PERIOD_ID,
                                       "is_recon_day": "true" if recon else "false",
                                       "non_recon_reason": "" if recon else ("WEEKEND" if d.weekday() >= 5 else "UK_BANK_HOLIDAY"),
                                       "calendar_basis": "SYNTHETIC: UK weekends and bank holidays; no foreign-market closures assumed"})
        for acct, (cls, ccy, num, desig, ack) in ACCOUNTS.items():
            self.rows["IN-02"].append({
                "account_id": acct, "account_class": cls, "currency": ccy,
                "asset_pool_id": schema.POOL_ID if cls == "RELEVANT_FUNDS_BANK" else "", "account_number_masked": num,
                "designation_name": desig, "acknowledgement_letter_ref": ack, "institution_id": INSTITUTION[0],
                "institution_full_name": INSTITUTION[1], "institution_postal_address": INSTITUTION[2],
                "institution_email": INSTITUTION[3], "institution_phone": INSTITUTION[4], "institution_role": INSTITUTION[5],
                "open_date": "2024-03-01", "close_date": ""})
        for ccy, acct in (("GBP", "SGA-GBP-01"), ("EUR", "SGA-EUR-01")):
            self.rows["IN-10"].append({"ledger_entry_id": f"LE-{ccy}-0831-0000", "account_id": acct,
                                       "posted_ts": ts(date(2026, 8, 31), 17, 0), "entry_type": "OPENING_BALANCE",
                                       "amount": money(OPEN_SGA[ccy]), "dc_indicator": "D", "currency": ccy,
                                       "payment_reference": "OPENING"})
        opening_day = date(2026, 8, 31)  # D4: opening client positions at the 31 Aug 17:00 reconciliation point
        for ccy in ("GBP", "EUR"):
            for c, bal in self.client[ccy].items():
                self.rows["IN-03"].append({"snapshot_id": f"CBS-{opening_day:%Y%m%d}-{c}-{ccy}", "recon_date": opening_day.isoformat(),
                                           "as_at_ts": ts(opening_day, 17, 0), "client_id": c, "asset_pool_id": schema.POOL_ID,
                                           "currency": ccy, "balance": money(bal)})
            if sum(self.client[ccy].values()) != OPEN_SGA[ccy]:
                raise AssertionError(f"opening client total {ccy} does not equal the opening safeguarding position")
        for i, d in enumerate(RECON_DAYS):
            self.run_day(i, d)
        self.rows["IN-11"].sort(key=lambda r: (r["executed_ts"], r["txn_id"]))
        return self.rows


# --- writing ---------------------------------------------------------------
def write_csvs(rows, src_dir):
    src_dir.mkdir(parents=True, exist_ok=True)
    for fid, (fname, _, cols) in schema.CSV_FILES.items():
        with open(src_dir / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[c[0] for c in cols], lineterminator="\n")
            w.writeheader()
            w.writerows(rows[fid])


def write_pdfs(doc_dir):
    from reportlab import rl_config
    rl_config.invariant = 1  # deterministic output (no timestamps or random IDs)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    doc_dir.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    footer = "SYNTHETIC DOCUMENT - UC-042 POC - not a real bank or firm document"

    def on_page(canvas, _doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(56, 28, footer)

    def make(fname, title, intro, details, body):
        story = [Paragraph(title, styles["Title"]), Paragraph(intro, styles["Normal"]), Spacer(1, 12),
                 Paragraph("Key details", styles["Heading2"])]
        story += [Paragraph(f"{k}: {v}", styles["Normal"]) for k, v in details]
        story.append(Spacer(1, 12))
        story += [Paragraph(p, styles["Normal"]) for p in body]
        SimpleDocTemplate(str(doc_dir / fname), pagesize=A4, title=title, author="UC-042 synthetic generator",
                          creator="UC-042 synthetic generator").build(story, onFirstPage=on_page, onLaterPages=on_page)

    for acct in ("SGA-GBP-01", "SGA-EUR-01"):
        cls, ccy, num, desig, ack = ACCOUNTS[acct]
        make(f"ack_letter_{acct}.pdf", "Safeguarding account acknowledgement (synthetic)",
             "Issued by Example Bank plc (fictional) to Synthetic EMI Ltd (fictional).",
             [("Letter reference", ack), ("Institution", INSTITUTION[1]), ("Account name", desig),
              ("Account number", num), ("Currency", ccy), ("Letter date", "2024-03-01")],
             ["Generic synthetic wording: the institution acknowledges that the account is held for the purpose of "
              "safeguarding relevant funds of the account holder's clients and is designated accordingly. "
              "This text is illustrative only; the CASS 15.7 template wording has not been reviewed (gap G-R04)."])
    make("safeguarding_reconciliation_policy_v1.2.pdf", "Safeguarding reconciliation policy (synthetic)",
         "Synthetic EMI Ltd (fictional). Approved 2026-04-30 by the synthetic board.",
         [("Document version", "1.2"), ("Effective date", "2026-05-07"), ("Safeguarding method", "SEGREGATION"),
          ("Reconciliation method", "STANDARD"), ("Reconciliation point", "17:00 Europe/London"),
          ("Frequency", "Each reconciliation day"), ("Internal reconciliation basis", "Per currency")],
         ["Internal reconciliation compares the safeguarding requirement with the safeguarding resource using the "
          "firm's own records at the reconciliation point. External reconciliation compares the firm's record of each "
          "safeguarding account with the bank's balance at the same point, one currency at a time.",
          "Any difference is investigated the same day. A shortfall is funded from own funds by the end of the day."])
    make("governance_register_2026-09.pdf", "Governance register extract (synthetic)",
         "Synthetic EMI Ltd (fictional). Optional supporting evidence.",
         [("Accountable person", "A. Example (synthetic)"), ("Role", "Chief Financial Officer (synthetic)"),
          ("Allocated from", "2026-05-07")],
         ["Critical individuals for safeguarding operations: U-12 (preparer), U-04 (reviewer). Synthetic identifiers."])
    make("rep027_submission_receipt_2026-08.pdf", "Monthly safeguarding return - submission receipt (synthetic)",
         "Synthetic receipt. Optional supporting evidence. The REP027 template itself has not been reviewed (gap G-R06).",
         [("Return", "REP027 monthly safeguarding return"), ("Period", "2026-08"), ("Due date", "2026-09-21"),
          ("Submitted at", "2026-09-17T11:02:00+01:00"), ("Submission reference", "SYN-RD-2026-08-0001")],
         ["Generated for the UC-042 POC. Not a real regulatory submission."])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(out):
    from pypdf import PdfReader
    rows = []
    for fid, (fname, desc, _) in schema.CSV_FILES.items():
        p = out / "source_data" / fname
        with open(p, encoding="utf-8") as f:
            n = sum(1 for _ in f) - 1
        rows.append([fid, fname, f"source_data/{fname}", "CSV", "RAW_SOURCE", "REQUIRED", desc, schema.PERIOD_ID, n, "data_rows", sha256(p), "YES"])
    for fid, (fname, desc, req, _) in schema.PDF_FILES.items():
        p = out / "supporting_documents" / fname
        rows.append([fid, fname, f"supporting_documents/{fname}", "PDF", "SUPPORTING_DOCUMENT", req, desc, schema.PERIOD_ID,
                     len(PdfReader(str(p)).pages), "pages", sha256(p), "YES"])
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["file_id", "filename", "relative_path", "format", "evidence_kind", "requirement", "description",
                    "reporting_period", "record_count", "record_unit", "sha256", "synthetic"])
        w.writerows(rows)
    return rows


GENERATION_NOTES = '# Generation notes — Set 1 clean baseline\n\n> **ILLUSTRATIVE SYNTHETIC CONVENTIONS (decision D6).** Every value, timing rule, reference pattern, fee treatment and\n> account arrangement below is an illustrative convention for the UC-042 POC. None is a confirmed Moorwand practice.\n\n**Command:** `python -m uc042lib.generate` (from `uc042/`). Seed `20260930`. The PDFs are written with ReportLab invariant mode, so repeated runs produce byte-identical files. `tests/test_baseline.py::Determinism` checks this against `manifest.csv`.\n\n**Money.** Integer cents internally; written as 2 dp decimal strings. Acquirer fees are 0.30% and 0.155% of gross, rounded half-up to the cent. The exception is `AQ-GBP-20260908`, fixed by the spec at £30.00 and £15.50. No binary floating point is used for money.\n\n## Scope (synthetic conventions)\n\n- **Entity:** `SYN-EMI-001`, pool `POOL-EMONEY`, segregation, standard method.\n- **Period:** 1–30 Sep 2026, with 22 reconciliation days (UK weekdays; no UK bank holidays in September; no foreign-market closures assumed).\n- **Reconciliation point:** 17:00 Europe/London.\n- **Accounts:** at Example Bank plc (fictional): `SGA-GBP-01`, `SGA-EUR-01`, `OWN-GBP-01`, `OWN-EUR-01`.\n- **Opening position, 31 Aug 2026 17:00:** SGA-GBP-01 £250,000.00 and SGA-EUR-01 €80,000.00 (equal to client totals, ledger and bank). Own funds: £500,000.00 and €150,000.00, synthetic.\n- **Opening client snapshot (D4):** 12 rows `CBS-20260831-<client>-<ccy>` at 31 Aug 17:00 in `client_balance_snapshots_2026-09.csv`. GBP C0001–C0008 total £250,000.00; EUR C0101–C0104 total €80,000.00. This is a permitted boundary record for the September period, so the 1 Sep client roll-forward can be checked.\n\n## Daily activity (each reconciliation day)\n\n| Flow | GBP | EUR | Records produced |\n| --- | --- | --- | --- |\n| Bank-transfer loads (1:1) | 2 (09:10, 11:40) | 1 (10:00) | Bank credit, cash-book debit and LOAD_BANK transaction, all sharing an end-to-end reference |\n| Card loads | 4 | 2 | LOAD_CARD transactions (client credited at load); acquirer batch `AQ-*` credited at 14:00 net of two fee lines |\n| Own-funds top-up of acquirer fees | 14:30 | 14:30 | Own-account debit, safeguarding credit and cash-book debit, all with reference `TOPUP-<ccy>-<date>` |\n| Card spends | 6 | 3 | SPEND transactions; scheme batch `SB-*` debited at 15:00; client debited at 15:00 (convention D8) |\n| Refunds | `TX-0909-0R001` (refunds `TX-0902-00044`) | `TX-0916-0R001` | REFUND line in the scheme batch; client credited at 15:00 |\n| Redemptions | alternate days, 16:00 | alternate days, 16:00 | Bank debit, cash-book credit and REDEMPTION transaction |\n| Unallocated receipts | `UR-0001` £750.00, 11 Sep 16:30 → C0007 on 14 Sep 09:30 | `UR-0002` €400.00, 23 Sep 16:10 → C0102 on 24 Sep 09:15 | Bank credit and cash-book entry on receipt; register row; LOAD_BANK transaction on allocation |\n\nScheme fees on spends are assumed to be billed to own-funds accounts outside this dataset. No record for them is generated.\n\n## Roll-forward\n\nFor each currency, all three views move together:\n\n- the cash book balance at 17:00 (item A);\n- the bank balance;\n- Σ client balances + open unallocated receipts (the requirement).\n\nSo requirement = resource and bank = ledger at every point. The generator asserts this while building. The validator independently re-derives it from the files.\n\nAll baseline bank entries book before 17:00, so each 17:00 confirmation equals the end-of-day closing balance.\n\n## Known limitations (synthetic, by design)\n\n- Reported values in IN-05 and IN-06 come from the same simulation that produced the source records. Validation proves the files are mutually consistent; it cannot prove operational truth.\n- Items B–D are 0.00 and D+1 columns are blank (gaps G-S04, G-R05).\n- PDFs use generic, labelled wording. The CASS 15.7 letter template and the REP027 template were not reviewed.\n'


def write_data_dictionary(out):
    lines = ["# Data dictionary — UC-042 Set 1 (clean baseline)", "",
             "Generated from `uc042lib/schema.py`. All data is synthetic. Field names are POC conventions, not Moorwand's.", "",
             "## Conventions", "",
             "- Money: decimal strings with exactly 2 dp. `amount` columns are unsigned; `signed` columns may carry a leading `-`. No thousands separators.",
             "- Currency: ISO 4217 (GBP, EUR). One currency per row; amounts in different currencies are never combined.",
             "- Time: ISO 8601 with offset, Europe/London (`2026-09-08T17:00:00+01:00`).",
             "- Requiredness: M mandatory, C conditional (rule in description), O optional.", "",
             "## Sign rules (`uc042lib/money.py`, unit-tested)", "",
             "| Source | Raw indicator | Signed value |", "| --- | --- | --- |",
             "| Bank balances and entries (IN-07, IN-08, IN-09) | C / D, bank perspective | C → +amount, D → −amount |",
             "| Cash book (IN-10) | D / C, firm asset-ledger perspective | D → +amount, C → −amount |",
             "| Transactions (IN-11) | CR / DR, client perspective | CR → +amount, DR → −amount |",
             "| Settlement lines (IN-13) | C / D, settlement-account perspective | C → +amount, D → −amount |",
             "| Settlement batch net (IN-12) | direction | TO_FIRM → +net, FROM_FIRM → −net |", ""]
    for fid, (fname, desc, cols) in schema.CSV_FILES.items():
        lines += [f"## {fid} `{fname}`", "", desc, "", "| Column | Type | Req | Meaning |", "| --- | --- | --- | --- |"]
        lines += [f"| {c} | {t} | {r} | {m} |" for c, t, r, m in cols]
        lines.append("")
    lines += ["## Supporting documents (PDF)", "",
              "Each PDF has a **Key details** block of `Label: value` lines, parsed deterministically by the validator.", "",
              "| File ID | File | Requirement | Key details |", "| --- | --- | --- | --- |"]
    lines += [f"| {fid} | `{f}` | {req} | {', '.join(keys)} |" for fid, (f, _, req, keys) in schema.PDF_FILES.items()]
    (out / "DATA_DICTIONARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate(out=DEFAULT_OUT, seed=SEED):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    rows = Baseline(seed).build()
    write_csvs(rows, out / "source_data")
    write_pdfs(out / "supporting_documents")
    write_data_dictionary(out)
    (out / "GENERATION_NOTES.md").write_text(GENERATION_NOTES, encoding="utf-8")
    (out / "answer_key.json").write_text(json.dumps(
        {"scenario_id": "S01", "description": "Clean baseline: no FAIL or INSUFFICIENT_EVIDENCE results and no exceptions",
         "non_passing_results": [], "exceptions": [], "evidence_statuses": {}, "investigation_groups": [],
         "candidate_relationships": []}, indent=2) + "\n", encoding="utf-8")
    return write_manifest(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    manifest = generate(args.out, args.seed)
    print(f"Generated {len(manifest)} files in {args.out}")
    for r in manifest:
        print(f"  {r[0]}  {r[1]:<46} {r[8]:>5} {r[9]}")


if __name__ == "__main__":
    main()
