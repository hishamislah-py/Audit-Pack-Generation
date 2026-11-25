"""Verification of all nine datasets and of the generated processing outputs. Run from uc042/: python -m unittest -v

- Schema contract: exact headers, no blank mandatory fields, valid field types, optional files flagged as optional.
- Output verification (tools/verify_outputs.py): citations resolve, displayed amounts equal independent recomputation,
  exception records consistent, wording never overstates evidence, groups/candidates consistent, no foreign records,
  report and trace agree with the CSV outputs.
- The verifier is proven able to fail: tampered copies of the outputs must be detected.
"""
import csv
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from uc042lib import schema
from uc042lib.structure import field_error

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "uc042_dataset"
spec = importlib.util.spec_from_file_location("verify_outputs", ROOT / "tools" / "verify_outputs.py")
vo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vo)
NAMES = list(dict.fromkeys(r["dataset"] for r in json.loads((DATASETS / "scenario_index.json").read_text())["scenarios"]))


def problems(result):
    return {k: v for k, v in result["checks"].items() if v.get("PROBLEM")}


class SchemaContract(unittest.TestCase):
    def test_every_dataset_matches_the_file_contract(self):
        for name in NAMES:
            ds = DATASETS / name
            for fid, (fname, _, cols) in schema.CSV_FILES.items():
                with open(ds / "source_data" / fname, encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    self.assertEqual(reader.fieldnames, [c[0] for c in cols], (name, fname))
                    for line, row in enumerate(reader, start=2):
                        for col, ftype, req, _ in cols:
                            v = row[col]
                            if req == "M":
                                self.assertNotEqual(v, "", (name, fname, line, col))
                            if v:
                                self.assertIsNone(field_error(ftype, v, schema.ENUMS.get((fid, col))), (name, fname, line, col, v))
            for fid, (fname, _, req, _) in schema.PDF_FILES.items():
                self.assertTrue((ds / "supporting_documents" / fname).read_bytes().startswith(b"%PDF-"), (name, fname))
            with open(ds / "manifest.csv", encoding="utf-8") as f:
                manifest = {r["file_id"]: r["requirement"] for r in csv.DictReader(f)}
            self.assertEqual({k for k, v in manifest.items() if v == "OPTIONAL"}, {"IN-18", "IN-19"}, name)
            self.assertEqual(len(manifest), 19, name)


class OutputVerification(unittest.TestCase):
    def test_all_outputs_verified_without_problems(self):
        for name in NAMES:
            res = vo.verify(name)
            self.assertEqual(problems(res), {}, (name, res["problems"]))
            self.assertGreater(sum(sum(v.values()) for v in res["checks"].values()), 4000, name)


class VerifierCanFail(unittest.TestCase):
    """Tamper with a copy of SC3C's outputs; each defect must be reported."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(DATASETS / "scn_SC3C_short_settlement", self.tmp / "scn_SC3C_short_settlement")
        self.ds = self.tmp / "scn_SC3C_short_settlement"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def tamper(self, fname, fn):
        p = self.ds / "validation" / fname
        with open(p, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            cols, rows = reader.fieldnames, list(reader)
        fn(rows)
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

    def found(self, area):
        res = vo.verify("scn_SC3C_short_settlement", base=self.tmp)
        return any(k.startswith(area) for k in problems(res))

    def test_wrong_amount_detected(self):
        self.tamper("control_results.csv", lambda rows: next(r for r in rows if r["check_id"] == "C08-DIFFERENCE"
                                                            and r["outcome"] == "FAIL").update(computed="-5.50"))
        self.assertTrue(self.found("O2"))

    def test_exception_shown_as_resolved_detected(self):
        self.tamper("exceptions.csv", lambda rows: rows[0].update(status="RESOLVED"))
        self.assertTrue(self.found("O3"))

    def test_unexplained_described_as_explained_detected(self):
        self.tamper("exceptions.csv", lambda rows: rows[0].update(evidence_status_detail="difference explained by timing"))
        self.assertTrue(self.found("O4"))

    def test_foreign_record_detected(self):
        self.tamper("exceptions.csv", lambda rows: rows[0].update(related_records="BE-GBP-0916-T01 (from another scenario)"))
        self.assertTrue(self.found("O6"))

    def test_broken_citation_detected(self):
        self.tamper("control_results.csv", lambda rows: rows[0].update(evidence="IN-09:bank_statement_entries_2026-09.csv#L99999"))
        self.assertTrue(self.found("O1"))

    def test_report_mismatch_detected(self):
        p = self.ds / "VALIDATION_REPORT.md"
        p.write_text(p.read_text().replace("FAIL 20", "FAIL 19"))
        self.assertTrue(self.found("O7"))


if __name__ == "__main__":
    unittest.main()
