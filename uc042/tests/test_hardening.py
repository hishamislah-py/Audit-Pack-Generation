"""Engine-hardening tests (Phase 1). Run from the uc042/ folder:  python -m unittest -v

Every test works on a temporary copy; the committed datasets are never modified.
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
from uc042lib.structure import field_error
from uc042lib.validate import DEFAULT_SET, Validator, case_status

DATASETS = DEFAULT_SET.parent
GOLDEN = Path(__file__).parent / "golden"
SETS = ["set_01_clean_baseline", "scn_S02_missing_eur_statement", "scn_S05_unexplained_gbp_difference"]


def run(root):
    v = Validator(root)
    v.run()
    return v


def mutate(root, fid, fn):
    path = Path(root) / "source_data" / schema.CSV_FILES[fid][0]
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n")
        w.writeheader()
        w.writerows(fn(rows))


def set_field(root, fid, match, **values):
    mutate(root, fid, lambda rows: [dict(r, **values) if match(r) else r for r in rows])


def remove(root, fid):
    sub = "source_data" if fid in schema.CSV_FILES else "supporting_documents"
    (Path(root) / sub / (schema.CSV_FILES.get(fid) or schema.PDF_FILES.get(fid))[0]).unlink()


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "case"
        shutil.copytree(DEFAULT_SET, self.root)
        (self.root / "manifest.csv").unlink()  # edited copies are validated without a manifest

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def assert_one_exception(self, v, root_cause):
        self.assertEqual([x["root_cause"] for x in v.exceptions], [root_cause], v.exceptions)

    def assert_no_dependent_pass(self, v, fid):
        """No check that depends on `fid` may PASS; independent checks must still produce PASS results."""
        dependent = {c for c, deps in schema.DEPENDS.items() if fid in deps}
        passed = {r["check_id"] for r in v.results if r["outcome"] == "PASS"}
        self.assertFalse(passed & dependent, passed & dependent)
        self.assertTrue(passed - dependent, "independent checks should keep running")
        for c in dependent:
            gated = [r for r in v.results if r["check_id"] == c]
            self.assertEqual(len(gated), 1, f"{c}: expected one gated result, got {len(gated)}")
            self.assertEqual(gated[0]["outcome"], "INSUFFICIENT_EVIDENCE")


class GoldenRegression(unittest.TestCase):
    """The three committed datasets keep exactly their approved results and exceptions."""

    def test_golden_results_and_exceptions_unchanged(self):
        for name in SETS:
            golden = json.loads((GOLDEN / f"{name}.json").read_text())
            v = run(DATASETS / name)
            got = [[r["check_id"], r["scope"], r["outcome"], r["computed"], r["reported"], r["root_cause"]] for r in v.results]
            gx = [[x["exception_id"], x["severity"], x["root_cause"], str(x["affected_results"]), x["flags"]] for x in v.exceptions]
            self.assertEqual(got, golden["results"], name)
            self.assertEqual(gx, golden["exceptions"], name)

    def test_case_status(self):
        expected = {"set_01_clean_baseline": "CLEAN", "scn_S02_missing_eur_statement": "EVIDENCE_INCOMPLETE",
                    "scn_S05_unexplained_gbp_difference": "EXCEPTIONS_OPEN"}
        for name, status in expected.items():
            self.assertEqual(case_status(run(DATASETS / name)), status, name)


class FormatRules(unittest.TestCase):
    def test_documented_amount_rule(self):
        self.assertIsNone(field_error("amount", "1000.00"))
        for bad in ("1,000.00", "1000,00", "1000", "1000.0", "+1000.00", "£1000.00", " 1000.00", "1e3"):
            self.assertIsNotNone(field_error("amount", bad), bad)

    def test_dates_identifiers_enums(self):
        self.assertIsNotNone(field_error("date", "15/09/2026"))
        self.assertIsNotNone(field_error("date", "2026-09-31"))
        self.assertIsNotNone(field_error("ts", "2026-09-15T17:00:00"))  # no offset
        self.assertIsNone(field_error("ts", "2026-09-15T17:00:00+01:00"))
        self.assertIsNotNone(field_error("id", "TX 0908"))
        self.assertIsNone(field_error("id", "TX-0908-00001"))
        self.assertIsNotNone(field_error("enum", "X", {"C", "D"}))
        self.assertIsNotNone(field_error("int", "-1"))


class MalformedRows(TempCase):
    """Invalid rows are excluded, reported with file/line/field/raw value, and never crash validation."""

    def check_finding(self, v, fid, field, raw):
        f = [r for r in v.results if r["check_id"] == "DQ-FIELD" and r["scope"].startswith(fid) and r["scope"].endswith(field)]
        self.assertEqual(len(f), 1, f)
        self.assertEqual(f[0]["reported"], raw)
        self.assertRegex(f[0]["evidence"], rf"{fid}:[^#]+#L\d+")
        return f[0]

    def test_bad_debit_credit_code(self):
        set_field(self.root, "IN-09", lambda r: r["bank_entry_id"] == "BE-GBP-0908-L01", dc_indicator="X")
        v = run(self.root)
        self.check_finding(v, "IN-09", "dc_indicator", "X")
        self.assert_one_exception(v, "INVALID_ROWS|IN-09")
        stmt = [r for r in v.results if r["check_id"] == "DQ23-STATEMENT" and r["scope"] == "ST-SGA-GBP-01-20260908-EOD"]
        self.assertEqual(stmt[0]["outcome"], "INSUFFICIENT_EVIDENCE")
        other = [r for r in v.results if r["check_id"] == "DQ23-STATEMENT" and r["scope"] == "ST-SGA-GBP-01-20260909-EOD"]
        self.assertEqual(other[0]["outcome"], "PASS")

    def test_amount_with_thousands_separator_is_rejected_not_converted(self):
        set_field(self.root, "IN-09", lambda r: r["bank_entry_id"] == "BE-GBP-0908-L01", amount="1,000.00")
        v = run(self.root)
        self.check_finding(v, "IN-09", "amount", "1,000.00")
        self.assert_one_exception(v, "INVALID_ROWS|IN-09")
        # The excluded entry must not count as zero: its cash-book counterpart is insufficient evidence, not a pass or fail.
        cb = [r for r in v.results if r["check_id"] == "CASH-BANK-LINK" and r["root_cause"] == "INVALID_ROWS|IN-09"]
        self.assertEqual([r["outcome"] for r in cb], ["INSUFFICIENT_EVIDENCE"])
        self.assertFalse([r for r in v.results if r["check_id"] == "CASH-BANK-LINK" and r["outcome"] == "FAIL"])

    def test_unknown_batch_direction(self):
        set_field(self.root, "IN-12", lambda r: r["batch_id"] == "SB-GBP-20260910", direction="SIDEWAYS")
        v = run(self.root)
        self.check_finding(v, "IN-12", "direction", "SIDEWAYS")
        self.assert_one_exception(v, "INVALID_ROWS|IN-12")
        self.assertFalse([r for r in v.results if r["scope"] == "SB-GBP-20260910" and r["outcome"] == "PASS"])
        cover = [r for r in v.results if r["scope"] == "IN-12 2026-09-10/GBP/SCHEME"]
        self.assertEqual(cover[0]["outcome"], "INSUFFICIENT_EVIDENCE")

    def test_bad_date_taints_every_scope_it_might_touch(self):
        set_field(self.root, "IN-10", lambda r: r["payment_reference"] == "E2E-EUR-0915-L01", posted_ts="15/09/2026 10:00")
        v = run(self.root)
        self.check_finding(v, "IN-10", "posted_ts", "15/09/2026 10:00")
        self.assert_one_exception(v, "INVALID_ROWS|IN-10")
        eur = [r for r in v.results if r["check_id"] == "C05-RESOURCE" and r["scope"].endswith("/EUR")]
        gbp = [r for r in v.results if r["check_id"] == "C05-RESOURCE" and r["scope"].endswith("/GBP")]
        self.assertTrue(all(r["outcome"] == "INSUFFICIENT_EVIDENCE" for r in eur))  # date unknown: every EUR day
        self.assertTrue(all(r["outcome"] == "PASS" for r in gbp))                  # other account unaffected

    def test_bad_identifier(self):
        set_field(self.root, "IN-11", lambda r: r["payment_reference"] == "E2E-GBP-0908-L01", txn_id="TX 0908 BAD")
        v = run(self.root)
        self.check_finding(v, "IN-11", "txn_id", "TX 0908 BAD")
        self.assert_one_exception(v, "INVALID_ROWS|IN-11")
        self.assertFalse([r for r in v.results if r["outcome"] == "FAIL" and r["check_id"] not in ("DQ-FIELD", "V01-SCHEMA")])

    def test_wrong_number_of_fields(self):
        path = self.root / "source_data" / schema.CSV_FILES["IN-07"][0]
        lines = path.read_text().splitlines()
        lines[3] = lines[3] + ",extra"
        path.write_text("\n".join(lines) + "\n")
        v = run(self.root)
        self.assertTrue([r for r in v.results if r["check_id"] == "DQ-FIELD" and "wrong number of fields" in r["computed"]])
        self.assert_one_exception(v, "INVALID_ROWS|IN-07")

    def test_invalid_row_in_scope_file_makes_it_unusable(self):
        set_field(self.root, "IN-01", lambda r: r["calendar_date"] == "2026-09-15", is_recon_day="yes")
        v = run(self.root)
        self.assert_one_exception(v, "INVALID_ROWS|IN-01")
        self.assert_no_dependent_pass(v, "IN-01")


class MissingEvidence(TempCase):
    """A missing file is one evidence issue: one exception, dependent checks gated, independent checks running."""

    def check_missing(self, fid):
        remove(self.root, fid)
        v = run(self.root)
        self.assert_one_exception(v, f"MISSING_FILE|{fid}")
        self.assert_no_dependent_pass(v, fid)
        self.assertEqual(case_status(v), "EVIDENCE_INCOMPLETE")
        return v

    def test_missing_calendar(self):
        v = self.check_missing("IN-01")
        self.assertEqual([r["outcome"] for r in v.results if r["check_id"] == "C11-BATCH-ARITH"], ["PASS"] * 88)

    def test_missing_account_inventory(self):
        v = self.check_missing("IN-02")
        self.assertEqual(Counter(r["outcome"] for r in v.results if r["check_id"] == "C12-REFUND"), Counter({"PASS": 2}))

    def test_missing_cash_book(self):
        v = self.check_missing("IN-10")
        self.assertEqual(Counter(r["outcome"] for r in v.results if r["check_id"] == "C04-REQUIREMENT"), Counter({"PASS": 44}))

    def test_missing_policy_pdf(self):
        v = self.check_missing("IN-17")
        self.assertEqual(Counter(r["outcome"] for r in v.results if r["check_id"] == "C07-BANK-EVIDENCE"), Counter({"PASS": 44}))

    def test_present_but_empty_required_file(self):
        mutate(self.root, "IN-07", lambda rows: [])
        v = run(self.root)
        self.assert_one_exception(v, "EMPTY_FILE|IN-07")
        self.assert_no_dependent_pass(v, "IN-07")
        schema_row = [r for r in v.results if r["check_id"] == "V01-SCHEMA" and r["scope"] == "IN-07"][0]
        self.assertEqual(schema_row["note"], "file present but contains no data rows")

    def test_empty_allowed_file_is_not_an_issue(self):
        mutate(self.root, "IN-04", lambda rows: [])
        v = run(self.root)
        self.assertNotIn("EMPTY_FILE|IN-04", [x["root_cause"] for x in v.exceptions])

    def test_wrong_header_is_unusable_not_missing(self):
        path = self.root / "source_data" / schema.CSV_FILES["IN-10"][0]
        text = path.read_text().replace("payment_reference", "reference", 1)
        path.write_text(text)
        v = run(self.root)
        self.assert_one_exception(v, "INVALID_FILE|IN-10")
        self.assert_no_dependent_pass(v, "IN-10")


class CasePreparation(unittest.TestCase):
    """A case can be prepared from arbitrary file names and validated without the generator's manifest."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inp = self.tmp / "inbox"
        (self.inp / "sub").mkdir(parents=True)
        files = sorted((DEFAULT_SET / "source_data").glob("*.csv")) + sorted((DEFAULT_SET / "supporting_documents").glob("*.pdf"))
        for i, f in enumerate(files):  # meaningless names, mixed folders
            shutil.copyfile(f, (self.inp / ("sub" if i % 2 else "")) / f"upload_{i:02d}{f.suffix}")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def decisions(self, intake):
        return Counter(r["decision"] for r in intake)

    def test_prepared_case_validates_identically_to_baseline(self):
        shutil.copyfile(DEFAULT_SET / "manifest.csv", self.inp / "manifest.csv")              # user manifest: never trusted
        shutil.copyfile(self.inp / "upload_00.csv", self.inp / "sub" / "same_again.csv")     # duplicate content
        (self.inp / "notes.txt").write_text("not evidence\n")
        (self.inp / "export.xlsx").write_bytes(b"PK\x03\x04 not supported")
        intake = prepare_case(self.inp, self.tmp / "case")
        self.assertEqual(self.decisions(intake), Counter({"ACCEPTED": 19, "REJECTED": 3, "DUPLICATE": 1}))
        self.assertIn("manifest.csv", [r["original_path"] for r in intake if r["decision"] == "REJECTED"])
        v = run(self.tmp / "case")
        golden = json.loads((GOLDEN / "set_01_clean_baseline.json").read_text())
        got = [[r["check_id"], r["scope"], r["outcome"], r["computed"], r["reported"], r["root_cause"]] for r in v.results]
        self.assertEqual(got, golden["results"])

    def test_identification_ignores_misleading_names(self):
        cash = DEFAULT_SET / "source_data" / schema.CSV_FILES["IN-10"][0]
        for f in self.inp.rglob("*"):
            if f.is_file() and f.read_bytes() == cash.read_bytes():
                f.rename(f.parent / "bank_balance_confirmations_2026-09.csv")
        intake = prepare_case(self.inp, self.tmp / "case")
        row = [r for r in intake if r["original_path"].endswith("bank_balance_confirmations_2026-09.csv")][0]
        self.assertEqual((row["decision"], row["file_id"]), ("ACCEPTED", "IN-10"))

    def test_ambiguous_candidates_are_not_selected(self):
        src = DEFAULT_SET / "source_data" / schema.CSV_FILES["IN-07"][0]
        lines = src.read_text().splitlines()
        (self.inp / "second_confirmations.csv").write_text("\n".join(lines[:-1]) + "\n")  # same header, different content
        intake = prepare_case(self.inp, self.tmp / "case")
        amb = [r for r in intake if r["decision"] == "AMBIGUOUS"]
        self.assertEqual(len(amb), 2)
        self.assertFalse((self.tmp / "case" / "source_data" / schema.CSV_FILES["IN-07"][0]).exists())
        v = run(self.tmp / "case")
        self.assertEqual([x["root_cause"] for x in v.exceptions], ["AMBIGUOUS_FILE|IN-07"])

    def test_missing_types_are_recorded(self):
        for f in self.inp.rglob("*"):
            if f.is_file() and f.read_bytes() == (DEFAULT_SET / "supporting_documents" / schema.PDF_FILES["IN-17"][0]).read_bytes():
                f.unlink()
        intake = prepare_case(self.inp, self.tmp / "case")
        self.assertIn(("MISSING", "IN-17"), [(r["decision"], r["file_id"]) for r in intake])
        v = run(self.tmp / "case")
        self.assertEqual([x["root_cause"] for x in v.exceptions], ["MISSING_FILE|IN-17"])

    def test_validator_runs_without_any_manifest(self):
        case = self.tmp / "nomanifest"
        shutil.copytree(DEFAULT_SET, case)
        (case / "manifest.csv").unlink()
        v = run(case)
        self.assertEqual(case_status(v), "CLEAN")


if __name__ == "__main__":
    unittest.main()
