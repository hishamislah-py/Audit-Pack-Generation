"""U2 reporting-period rules and U3 header diagnosis. Run from the uc042/ folder:  python -m unittest -v

All tests use temporary copies; the committed datasets are never modified.
"""
import csv
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from uc042lib import schema
from uc042lib.prepare import prepare_case
from uc042lib.structure import check_period, diagnose_header
from uc042lib.validate import DEFAULT_SET, Validator, case_status

DATASETS = DEFAULT_SET.parent
GOLDEN = Path(__file__).parent / "golden"


def run(root):
    v = Validator(root)
    v.run()
    return v


def src(root, fid):
    return Path(root) / "source_data" / schema.CSV_FILES[fid][0]


def append_row(root, fid, row):
    path = src(root, fid)
    with open(path, "a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n").writerow(row)


def results(v, check, prefix=""):
    return [r for r in v.results if r["check_id"] == check and r["scope"].startswith(prefix)]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "case"
        shutil.copytree(DEFAULT_SET, self.root)
        (self.root / "manifest.csv").unlink()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def roots(self, v):
        return [x["root_cause"] for x in v.exceptions]


class ReportingPeriod(Case):
    def test_1_valid_september_dataset_has_no_period_findings(self):
        for name in ("set_01_clean_baseline", "scn_S02_missing_eur_statement", "scn_S05_unexplained_gbp_difference"):
            v = run(DATASETS / name)
            self.assertEqual(results(v, "DQ-PERIOD"), [], name)

    def test_2_august_bank_confirmation_file_is_one_wrong_period_exception(self):
        path = src(self.root, "IN-07")
        path.write_text(path.read_text().replace("2026-09-", "2026-08-").replace("202609", "202608"))
        v = run(self.root)
        self.assertEqual(self.roots(v), ["WRONG_PERIOD|IN-07"])
        self.assertEqual(v.exceptions[0]["severity"], "Critical")
        finding = results(v, "DQ-PERIOD")
        self.assertEqual(len(finding), 1)  # one file-level finding, not one per row
        self.assertIn("2026-08-01 to 2026-08-30", finding[0]["reported"])
        self.assertNotIn("MISSING_BANK_EVIDENCE", " ".join(r["root_cause"] for r in v.results))
        dependent = {c for c, d in schema.DEPENDS.items() if "IN-07" in d}
        self.assertFalse({r["check_id"] for r in v.results if r["outcome"] == "PASS"} & dependent)
        self.assertEqual(Counter(r["outcome"] for r in results(v, "C11-BATCH-ARITH")), Counter({"PASS": 88}))  # independent
        self.assertEqual(case_status(v), "EVIDENCE_INCOMPLETE")

    def test_3_single_stray_august_row_is_excluded_and_reported(self):
        append_row(self.root, "IN-09", {
            "bank_entry_id": "BE-GBP-0828-X01", "statement_id": "ST-SGA-GBP-01-20260828-EOD", "account_id": "SGA-GBP-01",
            "booking_date": "2026-08-28", "booking_ts": "2026-08-28T10:00:00+01:00", "value_date": "2026-08-28",
            "amount": "500.00", "dc_indicator": "C", "currency": "GBP", "bank_reference": "AUG-STRAY-1",
            "end_to_end_ref": "", "counterparty_name": "Stray payer", "narrative_text": "STRAY"})
        v = run(self.root)
        self.assertEqual(self.roots(v), ["OUT_OF_PERIOD_ROWS|IN-09"])
        f = results(v, "DQ-PERIOD", "IN-09")
        self.assertTrue(f)
        self.assertRegex(f[0]["evidence"], r"IN-09:bank_statement_entries_2026-09.csv#L\d+")
        self.assertIn("outside the reporting period", f[0]["computed"])
        self.assertEqual(f[0]["reported"], "2026-08-28")
        self.assertIn("Bank statement entries", f[0]["note"])
        self.assertEqual(results(v, "C11-BANK-ENTRY")[0]["outcome"], "PASS")  # excluded row not treated as unexplained

    def test_3b_excluded_row_cannot_influence_the_ledger(self):
        append_row(self.root, "IN-10", {
            "ledger_entry_id": "LE-GBP-0828-0001", "account_id": "SGA-GBP-01", "posted_ts": "2026-08-28T10:00:00+01:00",
            "entry_type": "BANK_LOAD", "amount": "5000.00", "dc_indicator": "D", "currency": "GBP", "payment_reference": "AUG-STRAY-2"})
        v = run(self.root)
        self.assertEqual(self.roots(v), ["OUT_OF_PERIOD_ROWS|IN-10"])
        # Had the row been used, every GBP item A would be 5,000.00 too high and fail.
        self.assertEqual(Counter(r["outcome"] for r in results(v, "C05-RESOURCE") if r["scope"].endswith("GBP")), Counter({"PASS": 22}))

    def test_4_permitted_opening_balance_is_used(self):
        with open(src(self.root, "IN-10"), encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        opening = [r for r in rows if r["entry_type"] == "OPENING_BALANCE"]
        self.assertEqual({r["posted_ts"] for r in opening}, {"2026-08-31T17:00:00+01:00"})
        kept, findings, counts = check_period("IN-10", [dict(r, _line=i) for i, r in enumerate(rows, 2)])
        self.assertEqual((findings, counts["permitted"]), ([], 2))

    def test_4b_opening_balance_on_another_date_is_not_permitted(self):
        path = src(self.root, "IN-10")
        path.write_text(path.read_text().replace("SGA-GBP-01,2026-08-31T17:00:00+01:00,OPENING_BALANCE",
                                                 "SGA-GBP-01,2026-08-30T17:00:00+01:00,OPENING_BALANCE"))
        v = run(self.root)
        self.assertEqual(self.roots(v), ["OUT_OF_PERIOD_ROWS|IN-10"])
        gbp = [r for r in results(v, "C05-RESOURCE") if r["scope"].endswith("GBP")]
        self.assertTrue(all(r["outcome"] == "INSUFFICIENT_EVIDENCE" and r["root_cause"] == "OUT_OF_PERIOD_ROWS|IN-10" for r in gbp))
        self.assertTrue(all(r["outcome"] == "PASS" for r in results(v, "C05-RESOURCE") if r["scope"].endswith("EUR")))

    def test_4c_file_with_only_the_opening_row_is_wrong_period(self):
        path = src(self.root, "IN-10")
        text = path.read_text().replace("2026-09-", "2026-08-")
        path.write_text(text)
        v = run(self.root)
        self.assertEqual(self.roots(v), ["WRONG_PERIOD|IN-10"])
        self.assertIn("2 permitted boundary row(s) do not count", results(v, "DQ-PERIOD")[0]["note"])

    def test_5_other_documented_boundary_dates_are_not_findings(self):
        # Account open dates (2024), the policy effective date, letter dates and the August return period are
        # document attributes. A value date in October for a 30 Sep booking is not period-checked (not used).
        path = src(self.root, "IN-09")
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        target = next(r for r in rows if r["booking_date"] == "2026-09-30")
        target["value_date"] = "2026-10-01"
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=schema.columns("IN-09"), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        v = run(self.root)
        self.assertEqual(results(v, "DQ-PERIOD"), [])
        self.assertEqual(v.exceptions, [])
        self.assertEqual(case_status(v), "CLEAN")

    def test_6_malformed_date_is_a_structure_finding_not_a_period_finding(self):
        path = src(self.root, "IN-07")
        path.write_text(path.read_text().replace("2026-09-15T17:00:00+01:00", "15/09/2026 17:00", 1))
        v = run(self.root)
        self.assertEqual(self.roots(v), ["INVALID_ROWS|IN-07"])
        self.assertTrue(results(v, "DQ-FIELD", "IN-07"))
        self.assertEqual(results(v, "DQ-PERIOD"), [])

    def test_7_mixed_file_keeps_september_rows(self):
        path = src(self.root, "IN-07")
        lines = path.read_text().splitlines()
        lines.append("ST-SGA-GBP-01-20260828-1700,SGA-GBP-01,2026-08-28T17:00:00+01:00,GBP,1.00,C,BC/STRAY")
        path.write_text("\n".join(lines) + "\n")
        v = run(self.root)
        self.assertEqual(self.roots(v), ["OUT_OF_PERIOD_ROWS|IN-07"])
        self.assertEqual(Counter(r["outcome"] for r in results(v, "C07-BANK-EVIDENCE")), Counter({"PASS": 44}))
        self.assertEqual(len(results(v, "DQ-PERIOD")), 1)

    # The former A1 placeholder test (an allocation after 30 Sep was excluded) is superseded by the A1 decision:
    # receipt and allocation are separate facts (tests/test_period_decisions.py).

    def test_8_existing_datasets_keep_approved_results(self):
        for name in ("set_01_clean_baseline", "scn_S02_missing_eur_statement", "scn_S05_unexplained_gbp_difference"):
            golden = json.loads((GOLDEN / f"{name}.json").read_text())
            v = run(DATASETS / name)
            self.assertEqual([[r["check_id"], r["scope"], r["outcome"], r["computed"], r["reported"], r["root_cause"]] for r in v.results],
                             golden["results"], name)
            self.assertEqual([[x["exception_id"], x["severity"], x["root_cause"], str(x["affected_results"]), x["flags"]]
                              for x in v.exceptions], golden["exceptions"], name)


class HeaderDiagnosis(unittest.TestCase):
    H = schema.columns("IN-07")

    def test_missing_column(self):
        d = diagnose_header([c for c in self.H if c != "balance_dc_indicator"])
        self.assertEqual((d["status"], d["file_id"], d["missing"]), ("LIKELY", "IN-07", ["balance_dc_indicator"]))
        self.assertIn("add the missing column(s) balance_dc_indicator", d["message"])
        self.assertEqual(d["expected"], self.H)

    def test_extra_column(self):
        d = diagnose_header(self.H + ["note"])
        self.assertEqual((d["file_id"], d["extra"]), ("IN-07", ["note"]))
        self.assertIn("remove the extra column(s) note", d["message"])

    def test_misordered_columns(self):
        d = diagnose_header([self.H[1], self.H[0]] + self.H[2:])
        self.assertEqual(d["file_id"], "IN-07")
        self.assertEqual(d["misordered"][:2], ["statement_id", "account_id"])
        self.assertIn("put the columns in the expected order", d["message"])

    def test_case_difference_is_named_not_accepted(self):
        d = diagnose_header(["Statement_ID"] + self.H[1:])
        self.assertEqual(d["case_or_spacing"], ["Statement_ID -> statement_id"])
        self.assertEqual(d["status"], "LIKELY")  # never MATCH

    def test_ambiguous_header_is_not_guessed(self):
        merged = list(dict.fromkeys(schema.columns("IN-08") + schema.columns("IN-09")))
        d = diagnose_header(merged)
        self.assertEqual((d["status"], d["file_id"]), ("AMBIGUOUS", ""))
        self.assertEqual(sorted(d["candidates"]), ["IN-08", "IN-09"])
        self.assertIn("cannot be determined", d["message"])

    def test_unrelated_header(self):
        d = diagnose_header(["name", "address", "phone"])
        self.assertEqual((d["status"], d["file_id"]), ("UNKNOWN", ""))

    def test_intake_rejects_near_match_with_actionable_detail(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            inbox = tmp / "inbox"
            inbox.mkdir()
            for f in list((DEFAULT_SET / "source_data").glob("*.csv")) + list((DEFAULT_SET / "supporting_documents").glob("*.pdf")):
                shutil.copyfile(f, inbox / f.name)
            p = inbox / schema.CSV_FILES["IN-08"][0]
            p.write_text(p.read_text().replace("statement_id,account_id", "account_id,statement_id", 1))
            intake = prepare_case(inbox, tmp / "case")
            rej = [r for r in intake if r["decision"] == "REJECTED"][0]
            self.assertEqual(rej["probable_file_id"], "IN-08")
            self.assertEqual(rej["expected_header"], ",".join(schema.columns("IN-08")))
            self.assertTrue(rej["received_header"].startswith("account_id,statement_id"))
            self.assertIn("expected order", rej["reason"])
            missing = [r for r in intake if r["decision"] == "MISSING"][0]
            self.assertEqual(missing["file_id"], "IN-08")
            self.assertIn(rej["original_path"], missing["reason"])
            self.assertFalse((tmp / "case" / "source_data" / schema.CSV_FILES["IN-08"][0]).exists())  # not accepted
            v = run(tmp / "case")
            self.assertEqual([x["root_cause"] for x in v.exceptions], ["MISSING_FILE|IN-08"])
            self.assertIn("rejected at intake", next(r for r in v.results if r["check_id"] == "V00-FILE")["note"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
