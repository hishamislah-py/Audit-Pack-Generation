"""Enriched scenario datasets (dataset gap closure). Run from the uc042/ folder:  python -m unittest -v

Correctness is checked three ways: the scenario answer keys (derived from the scenario design), the engine,
and the standalone verifier tools/verify_datasets.py (no shared code with the engine).
"""
import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

from uc042lib import scenarios, schema
from uc042lib.validate import DEFAULT_SET, Validator, case_status, compare_answer_key

ROOT = Path(__file__).resolve().parent.parent
DATASETS = DEFAULT_SET.parent
spec = importlib.util.spec_from_file_location("verify_datasets", ROOT / "tools" / "verify_datasets.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

BUILT = [(label, Path(d), fn) for label, d, fn in scenarios.SCENARIOS if fn is not None]


def not_ok(result):
    return {k: v for k, v in result["checks"].items() if set(v) - {"OK"}}


class ScenarioDatasets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_hash = hashlib.sha256((DEFAULT_SET / "manifest.csv").read_bytes()).hexdigest()
        cls.results = {}
        for name in ["set_01_clean_baseline"] + [d.name for _, d, _ in BUILT]:
            v = Validator(DATASETS / name)
            v.run()
            cls.results[name] = (v, verifier.verify(DATASETS / name))

    def test_every_answer_key_matches(self):
        for name, (v, _) in self.results.items():
            matched, diffs = compare_answer_key(DATASETS / name, v.results, v.exceptions)
            self.assertTrue(matched, (name, diffs))

    def test_case_status(self):
        expected = {"set_01_clean_baseline": "CLEAN", "scn_S02_missing_eur_statement": "EVIDENCE_INCOMPLETE"}
        for name, (v, _) in self.results.items():
            self.assertEqual(case_status(v), expected.get(name, "EXCEPTIONS_OPEN"), name)

    def test_rebuild_identical_diff_equals_mutations_and_baseline_untouched(self):
        for label, out, fn in BUILT:
            with open(out / "manifest.csv", encoding="utf-8") as f:
                committed = [r["sha256"] for r in csv.DictReader(f)]
            with tempfile.TemporaryDirectory() as t:
                scenario, ops, key, notes = fn()
                fresh = scenarios.build(Path(t) / out.name, scenario, ops, key, notes)
                with open(fresh / "manifest.csv", encoding="utf-8") as f:
                    self.assertEqual([r["sha256"] for r in csv.DictReader(f)], committed, label)
            ops = json.loads((out / "mutations.json").read_text())
            diff = verifier.diff_vs_baseline(verifier.load(out), verifier.load(DEFAULT_SET))
            fname = {fid: v[0] for fid, v in schema.CSV_FILES.items()}
            expect = {}
            for op in ops:
                d = expect.setdefault(fname[op["file_id"]], {"added": set(), "removed": set(), "modified": set()})
                if op["op"] == "delete_record":
                    d["removed"].add(op["key"])
                elif op["op"] == "add_record":
                    d["added"].add(op["record"][schema.columns(op["file_id"])[0]])
                else:
                    d["modified"].add(op["key"])
            self.assertEqual({f: {k: set(v) for k, v in d.items()} for f, d in diff.items()}, expect, label)
        self.assertEqual(hashlib.sha256((DEFAULT_SET / "manifest.csv").read_bytes()).hexdigest(), self.base_hash)

    def test_provenance_and_synthetic_labelling(self):
        for label, out, _ in BUILT:
            sc = json.loads((out / "scenario.json").read_text())
            self.assertEqual(sc["baseline_manifest_sha256"], self.base_hash, label)
            self.assertIn("ILLUSTRATIVE SYNTHETIC DATA", sc["synthetic_notice"])
            self.assertIn("ILLUSTRATIVE SYNTHETIC DATA", (out / "SCENARIO_NOTES.md").read_text())
        self.assertIn("ILLUSTRATIVE SYNTHETIC CONVENTIONS", (DEFAULT_SET / "GENERATION_NOTES.md").read_text())
        index = json.loads((DATASETS / "scenario_index.json").read_text())
        self.assertEqual([r["assessment_scenario"][:2].strip() for r in index["scenarios"]],
                         ["1", "2", "3a", "3b", "3c", "4", "5a", "5c", "5d", "6"])

    def test_opening_client_snapshot(self):
        with open(DEFAULT_SET / "source_data" / schema.CSV_FILES["IN-03"][0], encoding="utf-8") as f:
            opening = [r for r in csv.DictReader(f) if r["recon_date"] == "2026-08-31"]
        self.assertEqual(len(opening), 12)
        totals = Counter()
        for r in opening:
            totals[r["currency"]] += Decimal(r["balance"])
        self.assertEqual(totals, Counter({"GBP": Decimal("250000.00"), "EUR": Decimal("80000.00")}))
        v, ind = self.results["set_01_clean_baseline"]
        first_day = [r for r in v.results if r["check_id"] == "CBAL-ROLLFWD" and r["scope"].endswith("2026-09-01")]
        self.assertEqual([r["outcome"] for r in first_day], ["PASS"] * 12)
        self.assertEqual(ind["checks"]["opening: client total = cash-book opening = 1 Sep bank opening"], {"OK": 2})

    def test_baseline_independently_clean(self):
        _, ind = self.results["set_01_clean_baseline"]
        self.assertEqual(not_ok(ind), {})
        self.assertEqual(ind["csv_rows"], 1952)

    def test_independent_verifier_finds_exactly_the_intended_situation(self):
        expected = {
            "scn_SC2_settlement_timing": {"bank - ledger = 0": {"OK": 43, "PROBLEM": 1},
                                          "batch booked on its settlement date": {"OK": 87, "PROBLEM": 1}},
            "scn_SC3B_fee_not_itemised": {"batch: lines = reported totals (gross, fees, adjustments, net)": {"OK": 87, "PROBLEM": 1}},
            "scn_SC3C_short_settlement": {"bank - ledger = 0": {"OK": 27, "PROBLEM": 17},
                                          "batch -> bank entry by reference, same signed amount": {"OK": 87, "PROBLEM": 1},
                                          "cash book -> one bank entry by reference": {"OK": 221, "PROBLEM": 1},
                                          "difference fully evidenced as timing": {"PROBLEM": 17}},
            "scn_SC5A_missing_transaction": {"batch: lines = reported totals (gross, fees, adjustments, net)": {"OK": 87, "PROBLEM": 1},
                                             "client roll-forward": {"OK": 263, "PROBLEM": 1},
                                             "reference: line -> transaction": {"OK": 331, "PROBLEM": 1}},
            "scn_SC5C_refund_double_posted": {"client roll-forward": {"OK": 263, "PROBLEM": 1},
                                              "internal difference (resource - requirement) = 0": {"OK": 28, "PROBLEM": 16}},
            "scn_SC5D_closing_snapshot_mismatch": {"client roll-forward": {"OK": 263, "PROBLEM": 1},
                                                   "internal difference (resource - requirement) = 0": {"OK": 43, "PROBLEM": 1},
                                                   "requirement recomputed = reported": {"OK": 43, "PROBLEM": 1}},
            "scn_S05_unexplained_gbp_difference": {"bank - ledger = 0": {"OK": 34, "PROBLEM": 10},
                                                   "bank entry -> cash book by reference": {"OK": 222, "PROBLEM": 1},
                                                   "difference fully evidenced as timing": {"PROBLEM": 10}},
        }
        for name, want in expected.items():
            self.assertEqual(not_ok(self.results[name][1]), want, name)

    def test_missing_evidence_is_insufficient_never_problem_or_zero(self):
        _, ind = self.results["scn_S02_missing_eur_statement"]
        flagged = not_ok(ind)
        self.assertEqual(len(flagged), 6)
        self.assertTrue(all(set(v) == {"OK", "INSUFFICIENT"} for v in flagged.values()), flagged)

    def test_timing_difference_evidenced_within_one_business_day(self):
        _, ind = self.results["scn_SC2_settlement_timing"]
        self.assertEqual(ind["timing_items"], [{"ledger_entry": "LE-GBP-0915-0005", "bank_entry": "BE-GBP-0916-T01",
                                                "reference": "SB-GBP-20260915", "account": "SGA-GBP-01", "amount": "-2868.50",
                                                "posted": "2026-09-15", "booked": "2026-09-16", "within_one_business_day": True}])
        self.assertEqual(ind["checks"]["difference fully evidenced as timing"], {"OK": 1})
        v, _ = self.results["scn_SC2_settlement_timing"]
        c08 = [r for r in v.results if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] == "FAIL"]
        self.assertEqual([(r["scope"], r["computed"]) for r in c08], [("2026-09-15/SGA-GBP-01", "2868.50")])
        # E1 implemented (D-E1a): still FAIL on the day, now evidenced as timing, explicitly not resolved.
        self.assertEqual(c08[0]["evidence_status"], "TIMING_EVIDENCED")
        self.assertIn("awaiting human confirmation; not resolved", c08[0]["note"])

    def test_one_business_day_allowance_does_not_resolve_other_differences(self):
        for name in ("scn_S05_unexplained_gbp_difference", "scn_SC3C_short_settlement"):
            _, ind = self.results[name]
            self.assertEqual(ind["timing_items"], [], name)
            self.assertNotIn("OK", ind["checks"]["difference fully evidenced as timing"], name)

    def test_812_40_remains_unresolved(self):
        v, _ = self.results["scn_S05_unexplained_gbp_difference"]
        e1 = next(x for x in v.exceptions if x["exception_id"] == "EXC-S05-01")
        self.assertEqual((e1["amount"], e1["status"], e1["cause_category"]), ("-812.40", "OPEN", ""))
        with open(DATASETS / "scn_S05_unexplained_gbp_difference" / "source_data" / schema.CSV_FILES["IN-14"][0], encoding="utf-8") as f:
            self.assertEqual(list(csv.DictReader(f)), [])  # no resolving evidence added

    def test_supported_fee_3a_in_baseline(self):
        v, _ = self.results["set_01_clean_baseline"]
        for check in ("C11-BATCH-ARITH", "C11-BATCH-BANK", "FUND-TOPUP"):
            r = next(r for r in v.results if r["check_id"] == check and r["scope"] == "AQ-GBP-20260908")
            self.assertEqual(r["outcome"], "PASS", check)


if __name__ == "__main__":
    unittest.main()
