"""A1 and A2 reporting-period decisions. Run from the uc042/ folder:  python -m unittest -v

A1: an unallocated receipt belongs to the period if it was open at some point in it (RC1 formula). Receipt and
    allocation are separate facts; a September receipt allocated in October stays open at every later September point.
    Convention P1: an allocation after the period end is a subsequent event; its timeliness is judged from the register.
A2: a discrepancy-log entry belongs to the period of the reconciliation it refers to. Convention P2: an entry logged
    after the period end counts as investigation evidence and is labelled subsequent-recorded.
"""
import csv
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from uc042lib import schema
from uc042lib.structure import check_period
from uc042lib.validate import DEFAULT_SET, Validator, case_status

S05 = DEFAULT_SET.parent / "scn_S05_unexplained_gbp_difference"
X = Decimal("250.00")


def rows_of(root, fid):
    with open(Path(root) / "source_data" / schema.CSV_FILES[fid][0], encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(root, fid, rows):
    with open(Path(root) / "source_data" / schema.CSV_FILES[fid][0], "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def plus(v, amt=X):
    return f"{Decimal(v) + amt:.2f}"


def add_sept30_receipt(root, allocated=("2026-10-01", "2026-10-01T09:30:00+01:00"), alloc_txn=False):
    """A consistent EUR receipt of 250.00 at 16:30 on 30 Sep: bank, cash book, register, and reported reconciliations."""
    e2e = "E2E-EUR-0930-U01"
    entries = rows_of(root, "IN-09")
    entries.append({"bank_entry_id": "BE-EUR-0930-U01", "statement_id": "ST-SGA-EUR-01-20260930-EOD", "account_id": "SGA-EUR-01",
                    "booking_date": "2026-09-30", "booking_ts": "2026-09-30T16:30:00+01:00", "value_date": "2026-09-30",
                    "amount": str(X), "dc_indicator": "C", "currency": "EUR", "bank_reference": e2e, "end_to_end_ref": e2e,
                    "counterparty_name": "Unknown remitter", "narrative_text": "INBOUND TRANSFER"})
    write(root, "IN-09", entries)
    stmts = rows_of(root, "IN-08")
    for s in stmts:
        if s["statement_id"] == "ST-SGA-EUR-01-20260930-EOD":
            s["closing_balance_amount"], s["entry_count"] = plus(s["closing_balance_amount"]), str(int(s["entry_count"]) + 1)
    write(root, "IN-08", stmts)
    bcs = rows_of(root, "IN-07")
    for b in bcs:
        if b["statement_id"] == "ST-SGA-EUR-01-20260930-1700":
            b["balance_amount"] = plus(b["balance_amount"])
    write(root, "IN-07", bcs)
    cash = rows_of(root, "IN-10")
    cash.append({"ledger_entry_id": "LE-EUR-0930-0999", "account_id": "SGA-EUR-01", "posted_ts": "2026-09-30T16:30:00+01:00",
                 "entry_type": "UNALLOCATED_RECEIPT", "amount": str(X), "dc_indicator": "D", "currency": "EUR", "payment_reference": e2e})
    write(root, "IN-10", cash)
    reg = rows_of(root, "IN-04")
    reg.append({"receipt_id": "UR-0003", "bank_reference": e2e, "receipt_date": "2026-09-30", "receipt_ts": "2026-09-30T16:30:00+01:00",
                "amount": str(X), "currency": "EUR", "classification": "UNALLOCATED", "identified_date": "",
                "allocated_date": allocated[0] if allocated else "", "allocated_ts": allocated[1] if allocated else "",
                "client_id": "C0101" if allocated else ""})
    write(root, "IN-04", reg)
    irr = rows_of(root, "IN-05")
    for r in irr:
        if r["recon_run_id"] == "IRR-EMONEY-EUR-20260930":
            for k in ("requirement_reported", "resource_reported", "item_a"):
                r[k] = plus(r[k])
    write(root, "IN-05", irr)
    erl = rows_of(root, "IN-06")
    for r in erl:
        if r["ext_recon_id"] == "ERL-SGA-EUR-01-20260930":
            r["ledger_balance_reported"], r["bank_balance_reported"] = plus(r["ledger_balance_reported"]), plus(r["bank_balance_reported"])
    write(root, "IN-06", erl)
    if alloc_txn:
        txns = rows_of(root, "IN-11")
        txns.append({"txn_id": "TX-1001-00001", "client_id": "C0101", "txn_type": "LOAD_BANK", "status": "EXECUTED", "auth_ts": "",
                     "clearing_date": "", "executed_ts": allocated[1], "amount": str(X), "direction": "CR", "currency": "EUR",
                     "settlement_batch_id": "", "payment_reference": e2e, "original_txn_id": ""})
        write(root, "IN-11", txns)


class Case(unittest.TestCase):
    source = DEFAULT_SET

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "case"
        shutil.copytree(self.source, self.root)
        (self.root / "manifest.csv").unlink()
        for name in ("answer_key.json", "scenario.json"):
            if (self.root / name).exists() and name == "answer_key.json":
                (self.root / name).unlink()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_case(self):
        v = Validator(self.root)
        v.run()
        return v

    def one(self, v, check, scope):
        r = [x for x in v.results if x["check_id"] == check and x["scope"] == scope]
        self.assertEqual(len(r), 1, (check, scope, r))
        return r[0]


class A1UnallocatedReceipts(Case):
    def test_september_receipt_allocated_1_october_counts_as_open_on_30_september(self):
        add_sept30_receipt(self.root)
        v = self.run_case()
        self.assertEqual([x for x in v.results if x["check_id"] == "DQ-PERIOD"], [])
        req = self.one(v, "C04-REQUIREMENT", "2026-09-30/EUR")
        self.assertEqual(req["outcome"], "PASS")
        self.assertIn("1 open unallocated receipt(s)", req["note"])
        self.assertIn("unallocated_register_2026-09.csv#L4", req["evidence"])  # UR-0003 cited
        c09 = self.one(v, "C09-ALLOCATION", "UR-0003")
        self.assertEqual(c09["outcome"], "PASS")
        self.assertIn("allocated after the period end (2026-10-01): a subsequent event", c09["note"])
        self.assertEqual(v.exceptions, [])
        self.assertEqual(case_status(v), "CLEAN")

    def test_allocation_transaction_in_october_is_reported_but_not_required(self):
        add_sept30_receipt(self.root, alloc_txn=True)
        v = self.run_case()
        self.assertEqual([x["root_cause"] for x in v.exceptions], ["OUT_OF_PERIOD_ROWS|IN-11"])
        self.assertEqual(self.one(v, "C09-ALLOCATION", "UR-0003")["outcome"], "PASS")
        self.assertTrue(all(x["outcome"] in ("PASS", "NOT_APPLICABLE") for x in v.results if x["check_id"].startswith(("C04", "CBAL"))))

    def test_late_allocation_after_period_end_fails_timeliness(self):
        add_sept30_receipt(self.root, allocated=("2026-10-02", "2026-10-02T09:30:00+01:00"))
        v = self.run_case()
        c09 = self.one(v, "C09-ALLOCATION", "UR-0003")
        self.assertEqual(c09["outcome"], "FAIL")
        self.assertIn("allocated after 2026-10-01", c09["note"])

    def test_receipt_still_open_at_period_end_within_deadline(self):
        add_sept30_receipt(self.root, allocated=None)
        v = self.run_case()
        c09 = self.one(v, "C09-ALLOCATION", "UR-0003")
        self.assertEqual(c09["outcome"], "PASS")
        self.assertIn("open at the period end", c09["note"])
        self.assertEqual(self.one(v, "C04-REQUIREMENT", "2026-09-30/EUR")["outcome"], "PASS")

    def test_receipt_received_in_october_is_out_of_period_and_does_not_affect_september(self):
        reg = rows_of(self.root, "IN-04")
        reg.append({"receipt_id": "UR-0004", "bank_reference": "E2E-GBP-1001-U01", "receipt_date": "2026-10-01",
                    "receipt_ts": "2026-10-01T10:00:00+01:00", "amount": "900.00", "currency": "GBP", "classification": "UNALLOCATED",
                    "identified_date": "", "allocated_date": "", "allocated_ts": "", "client_id": ""})
        write(self.root, "IN-04", reg)
        v = self.run_case()
        self.assertEqual([x["root_cause"] for x in v.exceptions], ["OUT_OF_PERIOD_ROWS|IN-04"])
        f = [x for x in v.results if x["check_id"] == "DQ-PERIOD"]
        self.assertTrue(f and all("received after the period end" in x["computed"] for x in f))
        self.assertEqual({x["outcome"] for x in v.results if x["check_id"] == "C04-REQUIREMENT"}, {"PASS"})
        self.assertFalse([x for x in v.results if x["check_id"] == "C09-ALLOCATION" and x["scope"] == "UR-0004"])

    def test_overdue_receipt_never_allocated_fails(self):
        # Defect fixed with A1: an unallocated receipt was reported as "allocated by the next business day".
        reg = rows_of(self.root, "IN-04")
        reg.append({"receipt_id": "UR-0005", "bank_reference": "E2E-GBP-0910-U09", "receipt_date": "2026-09-10",
                    "receipt_ts": "2026-09-10T10:00:00+01:00", "amount": "100.00", "currency": "GBP", "classification": "UNALLOCATED",
                    "identified_date": "", "allocated_date": "", "allocated_ts": "", "client_id": ""})
        write(self.root, "IN-04", reg)
        v = self.run_case()
        c09 = self.one(v, "C09-ALLOCATION", "UR-0005")
        self.assertEqual(c09["outcome"], "FAIL")
        self.assertIn("not allocated; allocation was due by 2026-09-11", c09["note"])

    def test_open_during_period_rule(self):
        def row(line, rd, rts, ad="", ats=""):
            return {"receipt_id": f"UR-9{line}", "bank_reference": f"R{line}", "receipt_date": rd, "receipt_ts": rts, "amount": "1.00",
                    "currency": "GBP", "classification": "UNALLOCATED", "identified_date": "", "allocated_date": ad,
                    "allocated_ts": ats, "client_id": "C0001" if ad else "", "_line": line}
        rows = [row(2, "2026-08-31", "2026-08-31T16:00:00+01:00", "2026-09-01", "2026-09-01T09:30:00+01:00"),  # open into September
                row(3, "2026-08-20", "2026-08-20T10:00:00+01:00", "2026-08-21", "2026-08-21T10:00:00+01:00"),  # closed before
                row(4, "2026-09-30", "2026-09-30T16:30:00+01:00", "2026-10-01", "2026-10-01T09:30:00+01:00"),  # A1
                row(5, "2026-10-01", "2026-10-01T10:00:00+01:00")]                                             # after
        kept, findings, _ = check_period("IN-04", rows)
        self.assertEqual([r["_line"] for r in kept], [2, 4])
        self.assertEqual(sorted({f["line"] for f in findings}), [3, 5])


class A2DiscrepancyLog(Case):
    source = S05

    def add_log(self, recon_ref, logged_ts, other_valid_entry=False):
        rows = rows_of(self.root, "IN-14") + [{
            "discrepancy_id": "DL-0001", "logged_ts": logged_ts, "recon_ref": recon_ref, "account_id": "SGA-GBP-01", "currency": "GBP",
            "amount": "-812.40", "description": "Unexplained debit SETTLE 0417", "cause_category": "", "cause_evidence_ref": "",
            "funding_reference": "", "status": "OPEN", "resolved_ts": "", "approver_id": ""}]
        if other_valid_entry:  # an unrelated, valid September entry, so the file is mixed rather than wholly out of period
            rows.append({"discrepancy_id": "DL-0002", "logged_ts": "2026-09-10T18:00:00+01:00", "recon_ref": "ERL-SGA-EUR-01-20260910",
                         "account_id": "SGA-EUR-01", "currency": "EUR", "amount": "0.00", "description": "Review note, no difference",
                         "cause_category": "", "cause_evidence_ref": "", "funding_reference": "", "status": "RESOLVED",
                         "resolved_ts": "2026-09-10T18:30:00+01:00", "approver_id": "U-04"})
        write(self.root, "IN-14", rows)

    def disc(self, v):
        return self.one(v, "DISC-LOG", "SGA-GBP-01 from 2026-09-17")

    def test_entry_logged_after_period_end_counts_and_is_labelled(self):
        self.add_log("ERL-SGA-GBP-01-20260917", "2026-10-02T11:00:00+01:00")
        v = self.run_case()
        self.assertEqual([x for x in v.results if x["check_id"] == "DQ-PERIOD"], [])
        d = self.disc(v)
        self.assertEqual(d["outcome"], "PASS")
        self.assertIn("subsequent-recorded", d["note"])
        self.assertIn("discrepancy_log_2026-09.csv#L2", d["evidence"])
        e1 = next(x for x in v.exceptions if x["root_cause"].startswith("BANK_LEDGER_DIFFERENCE"))
        self.assertIn("INVESTIGATION_RECORDED_AFTER_PERIOD_END", e1["flags"])
        self.assertNotIn("NO_INVESTIGATION_LOGGED", e1["flags"])
        self.assertEqual(e1["affected_results"], 10)  # the 10 daily differences; the log finding no longer fails
        # September calculations are unchanged: the difference stays unexplained and the exception stays open.
        self.assertEqual(sum(1 for x in v.results if x["check_id"] == "C08-DIFFERENCE" and x["outcome"] == "FAIL"), 10)

    def test_entry_logged_in_september_is_not_labelled(self):
        self.add_log("ERL-SGA-GBP-01-20260917", "2026-09-17T18:10:00+01:00")
        v = self.run_case()
        d = self.disc(v)
        self.assertEqual(d["outcome"], "PASS")
        self.assertNotIn("subsequent-recorded", d["note"])

    def test_entry_logged_before_the_reconciliation_is_excluded(self):
        self.add_log("ERL-SGA-GBP-01-20260917", "2026-09-10T09:00:00+01:00", other_valid_entry=True)
        v = self.run_case()
        self.assertIn("OUT_OF_PERIOD_ROWS|IN-14", [x["root_cause"] for x in v.exceptions])
        self.assertTrue(any("logged before the reconciliation" in x["computed"] for x in v.results if x["check_id"] == "DQ-PERIOD"))
        d = self.disc(v)  # the entry is about this difference but unusable: insufficient evidence, not "not logged"
        self.assertEqual((d["outcome"], d["root_cause"]), ("INSUFFICIENT_EVIDENCE", "OUT_OF_PERIOD_ROWS|IN-14"))

    def test_entry_for_a_non_september_reconciliation_is_excluded(self):
        self.add_log("ERL-SGA-GBP-01-20260828", "2026-08-28T18:00:00+01:00", other_valid_entry=True)
        v = self.run_case()
        self.assertIn("OUT_OF_PERIOD_ROWS|IN-14", [x["root_cause"] for x in v.exceptions])
        self.assertTrue(any("does not refer to a reconciliation record" in x["computed"] for x in v.results if x["check_id"] == "DQ-PERIOD"))
        self.assertEqual(self.disc(v)["outcome"], "FAIL")

    def test_log_with_no_september_entries_is_wrong_period(self):
        self.add_log("ERL-SGA-GBP-01-20260828", "2026-08-28T18:00:00+01:00")
        v = self.run_case()
        self.assertIn("WRONG_PERIOD|IN-14", [x["root_cause"] for x in v.exceptions])
        gated = [x for x in v.results if x["check_id"] == "DISC-LOG"]
        self.assertEqual([x["outcome"] for x in gated], ["INSUFFICIENT_EVIDENCE"])


if __name__ == "__main__":
    unittest.main()
