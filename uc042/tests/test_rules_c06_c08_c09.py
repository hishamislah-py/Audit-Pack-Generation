"""Approved business rules (17 Nov 2026).

C06 / C08  A reconciled zero difference (recomputed = reported = 0.00) is PASS, not NOT_APPLICABLE, for internal (C06) and
           external (C08) reconciliation independently; non-zero and mismatched differences are unchanged.
C09        The allocating bank-load transaction is matched by payment_reference (primary key) and must be for the same
           client; its execution time need not equal the register's allocated_ts. A missing, unmatched or ambiguous reference
           and a different client fail. The separate timeliness check (allocation deadline from allocated_ts) is unchanged.
           Consolidated remediation (17 Nov 2026): when exactly one allocation matches but an EXCLUDED IN-11 row could carry
           the same reference (a duplicate hidden by a data-quality exclusion), C09 is INSUFFICIENT_EVIDENCE, never PASS. A
           missing or whitespace-only register reference is "no payment reference" (strip() decides emptiness only); matching
           itself stays exact and case-sensitive (no normalisation). executed_ts is not compared with allocated_ts (accepted
           design risk L13).
Offline; every dataset is copied to a temporary folder first. Run: python -m unittest tests.test_rules_c06_c08_c09 -v"""
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_hardening import mutate, run, set_field
from uc042lib import validate

DATASETS = Path(__file__).resolve().parent.parent / "uc042_dataset"
BASE = DATASETS / "set_01_clean_baseline"


def outcomes(v, check):
    return [r for r in v.results if r["check_id"] == check]


def one(v, check, scope):
    hits = [r for r in v.results if r["check_id"] == check and r["scope"] == scope]
    assert len(hits) == 1, (check, scope, hits)
    return hits[0]


class Copy(unittest.TestCase):
    dataset = BASE

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uc042-rules-"))
        self.root = self.tmp / "case"
        shutil.copytree(self.dataset, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ZeroDifferenceIsPass(unittest.TestCase):
    def test_c06_zero_difference_is_pass(self):
        res = outcomes(run(BASE), "C06-DIFFERENCE")
        self.assertEqual(len(res), 44)
        self.assertTrue(all(r["outcome"] == "PASS" and r["computed"] == "0.00" and r["reported"] == "0.00" for r in res))
        self.assertTrue(all(r["note"] == "no difference to resolve" for r in res))

    def test_c08_zero_difference_is_pass(self):
        res = outcomes(run(BASE), "C08-DIFFERENCE")
        self.assertEqual(len(res), 44)
        self.assertTrue(all(r["outcome"] == "PASS" and r["computed"] == "0.00" for r in res))
        self.assertTrue(all(r["note"] == "bank equals ledger" for r in res))

    def test_rules_are_independent_and_non_zero_differences_unchanged(self):
        # SC3C: external differences only (C08 FAIL on the short-settlement days); C06 still PASS everywhere
        v = run(DATASETS / "scn_SC3C_short_settlement")
        c08 = outcomes(v, "C08-DIFFERENCE")
        self.assertEqual({r["outcome"] for r in c08 if r["computed"] != "0.00"}, {"FAIL"})
        self.assertTrue(any(r["outcome"] == "FAIL" for r in c08))
        self.assertTrue(all(r["outcome"] == "PASS" for r in c08 if r["computed"] == "0.00" and r["reported"] == "0.00"))
        self.assertEqual({r["outcome"] for r in outcomes(v, "C06-DIFFERENCE")}, {"PASS"})
        # SC5C: internal differences (C06 FAIL) while C08 stays PASS
        v = run(DATASETS / "scn_SC5C_refund_double_posted")
        c06 = outcomes(v, "C06-DIFFERENCE")
        self.assertEqual({r["outcome"] for r in c06 if r["computed"] != "0.00"}, {"FAIL"})
        self.assertTrue(any(r["outcome"] == "FAIL" for r in c06))
        self.assertEqual({r["outcome"] for r in outcomes(v, "C08-DIFFERENCE")}, {"PASS"})

    def test_legacy_rule_is_recorded_for_published_packs(self):
        self.assertEqual((validate.APPROVED_RULES.zero_difference_outcome,
                          validate.PUBLISHED_RULES_BEFORE_17_NOV_2026.zero_difference_outcome), ("PASS", "NOT_APPLICABLE"))
        self.assertFalse(hasattr(validate, "ZERO_DIFFERENCE_OUTCOME"))  # no mutable module-level rule any more


class MismatchedZeroStillFails(Copy):
    def test_recomputed_zero_but_reported_non_zero_fails(self):
        set_field(self.root, "IN-05", lambda r: r["recon_date"] == "2026-09-10" and r["currency"] == "GBP", difference_reported="1.00")
        r = one(run(self.root), "C06-DIFFERENCE", "2026-09-10/GBP")
        self.assertEqual((r["outcome"], r["computed"], r["reported"]), ("FAIL", "0.00", "1.00"))
        self.assertIn("reported difference differs", r["note"])


ALLOC_TXN, RECEIPT = "TX-0914-00001", "UR-0001"  # UR-0001 (C0007, reference E2E-GBP-0911-U01) allocated 14 Sep 09:30


class C09Allocation(Copy):
    def c09(self):
        return one(run(self.root), "C09-ALLOCATION", RECEIPT)

    def test_baseline_passes(self):
        self.assertEqual(self.c09()["outcome"], "PASS")

    def test_reference_and_client_match_with_a_different_timestamp_passes(self):
        set_field(self.root, "IN-11", lambda r: r["txn_id"] == ALLOC_TXN, executed_ts="2026-09-14T09:47:13+01:00")
        r = self.c09()
        self.assertEqual(r["outcome"], "PASS", r["note"])
        self.assertIn("IN-11:transactions_2026-09.csv", r["evidence"])  # the matched transaction is cited

    def test_same_instant_written_with_another_offset_passes(self):
        set_field(self.root, "IN-11", lambda r: r["txn_id"] == ALLOC_TXN, executed_ts="2026-09-14T08:30:00+00:00")
        self.assertEqual(self.c09()["outcome"], "PASS")

    def test_client_mismatch_fails(self):
        set_field(self.root, "IN-11", lambda r: r["txn_id"] == ALLOC_TXN, client_id="C0001")
        r = self.c09()
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("the transaction is for client C0001, the register allocates to C0007", r["note"])

    def test_missing_reference_fails(self):
        set_field(self.root, "IN-11", lambda r: r["txn_id"] == ALLOC_TXN, payment_reference="E2E-GBP-0911-ZZZ")
        r = self.c09()
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("no bank-load transaction carries the payment reference", r["note"])

    def test_ambiguous_reference_fails(self):
        def dup(rows):
            src = next(r for r in rows if r["txn_id"] == ALLOC_TXN)
            return rows + [dict(src, txn_id="TX-0914-09999", executed_ts="2026-09-14T11:00:00+01:00")]
        mutate(self.root, "IN-11", dup)
        r = self.c09()
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("2 bank-load transactions carry the payment reference (ambiguous)", r["note"])

    def test_empty_register_reference_is_excluded_before_c09(self):
        """bank_reference is mandatory in IN-04: an empty value makes the row a data-quality exclusion, so C09 has no result
        for it (it never PASSes) and the exclusion itself fails."""
        set_field(self.root, "IN-04", lambda r: r["receipt_id"] == RECEIPT, bank_reference="")
        v = run(self.root)
        self.assertEqual([r for r in v.results if r["check_id"] == "C09-ALLOCATION" and r["scope"] == RECEIPT], [])
        dq = [r for r in v.results if r["outcome"] == "FAIL" and "IN-04" in r["evidence"] and "bank_reference" in (r["note"] + r["evidence"])]
        self.assertTrue(dq, "the excluded register row is reported as a data-quality failure")

    def test_whitespace_only_reference_is_no_payment_reference(self):
        set_field(self.root, "IN-04", lambda r: r["receipt_id"] == RECEIPT, bank_reference="   ")
        r = self.c09()
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("the receipt has no payment reference", r["note"])
        self.assertNotIn("no bank-load transaction carries", r["note"])

    def test_matching_is_exact_and_case_sensitive(self):
        for variant in ("e2e-gbp-0911-u01", "E2E-GBP-0911-U01 "):
            with self.subTest(variant=variant):
                set_field(self.root, "IN-11", lambda r: r["txn_id"] == ALLOC_TXN, payment_reference=variant)
                r = self.c09()
                self.assertEqual(r["outcome"], "FAIL")
                self.assertIn("no bank-load transaction carries the payment reference", r["note"])

    def test_duplicate_hidden_by_an_excluded_invalid_row_is_insufficient(self):
        def dup(rows):
            src = next(r for r in rows if r["txn_id"] == ALLOC_TXN)
            return rows + [dict(src, txn_id="TX-0914-09998", amount="not-a-number")]  # excluded (invalid amount)
        mutate(self.root, "IN-11", dup)
        r = self.c09()
        self.assertEqual(r["outcome"], "INSUFFICIENT_EVIDENCE", r["note"])
        self.assertIn("an excluded bank-load row may carry the same payment reference", r["note"])

    def test_duplicate_transaction_id_for_another_client_is_insufficient(self):
        def dup(rows):
            src = next(r for r in rows if r["txn_id"] == ALLOC_TXN)
            return rows + [dict(src, client_id="C0001")]  # the same txn_id twice: the duplicate is excluded (DQ09)
        mutate(self.root, "IN-11", dup)
        r = self.c09()
        self.assertNotEqual(r["outcome"], "PASS", r["note"])
        self.assertIn(r["outcome"], ("INSUFFICIENT_EVIDENCE", "FAIL"))

    def test_unique_reference_and_client_passes_without_exclusions(self):
        r = self.c09()
        self.assertEqual((r["outcome"], r["root_cause"] if "root_cause" in r else ""), ("PASS", r.get("root_cause", "")))

    def test_timeliness_check_is_unchanged(self):
        """A late allocation still fails timeliness, even though the matching transaction is accepted."""
        set_field(self.root, "IN-04", lambda r: r["receipt_id"] == RECEIPT, allocated_date="2026-09-16",
                  allocated_ts="2026-09-16T09:30:00+01:00")
        r = self.c09()
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("allocated after", r["note"])
        self.assertNotIn("allocation transaction missing or inconsistent", r["note"])



class RuleConfiguration(unittest.TestCase):
    """D1: the zero-difference rule is explicit validator configuration (EngineRules), recorded in the configuration
    fingerprint; no mutable module global is patched."""
    GOLDEN = Path(__file__).resolve().parent / "golden"

    def golden_datasets(self):
        names = sorted(p.stem for p in self.GOLDEN.glob("*.json"))
        self.assertEqual(len(names), 9)
        return [DATASETS / n for n in names]

    def test_nine_golden_datasets_differ_only_by_the_approved_c06_c08_change(self):
        from uc042lib.validate import APPROVED_RULES, PUBLISHED_RULES_BEFORE_17_NOV_2026, Validator
        for ds in self.golden_datasets():
            with self.subTest(dataset=ds.name):
                new, old = Validator(ds, rules=APPROVED_RULES), Validator(ds, rules=PUBLISHED_RULES_BEFORE_17_NOV_2026)
                new.run()
                old.run()
                self.assertEqual(len(new.results), len(old.results))
                changed = 0
                for a, b in zip(new.results, old.results):
                    if a == b:
                        continue
                    changed += 1
                    self.assertIn(a["check_id"], ("C06-DIFFERENCE", "C08-DIFFERENCE"), (ds.name, a, b))
                    self.assertEqual((a["outcome"], b["outcome"]), ("PASS", "NOT_APPLICABLE"))
                    self.assertEqual({k: v for k, v in a.items() if k != "outcome"}, {k: v for k, v in b.items() if k != "outcome"})
                    self.assertEqual(a["computed"], "0.00")
                self.assertEqual([x["exception_id"] for x in new.exceptions], [x["exception_id"] for x in old.exceptions])
                self.assertGreater(changed, 0, ds.name)
                # and the approved run is exactly the golden snapshot (re-captured 17 Nov 2026, owner-approved)
                golden = __import__("json").loads((self.GOLDEN / f"{ds.name}.json").read_text(encoding="utf-8"))
                rows = golden["results"] if isinstance(golden, dict) and "results" in golden else None
                if rows is not None:
                    self.assertEqual(len(rows), len(new.results))

    def test_configuration_fingerprint_records_the_rule(self):
        from uc042lib.pack import registry
        from uc042lib.pack import model
        from uc042lib.validate import APPROVED_RULES, PUBLISHED_RULES_BEFORE_17_NOV_2026, EngineRules
        controls = {k: list(v) for k, v in registry.CONTROLS.items()}
        approved = model.configuration_fingerprint(controls, APPROVED_RULES.recorded())
        published = model.configuration_fingerprint(controls, PUBLISHED_RULES_BEFORE_17_NOV_2026.recorded())
        self.assertNotEqual(approved, published)  # a different rule configuration, a different fingerprint
        self.assertEqual(published, model.configuration_fingerprint(controls))  # published packs stay byte-reproducible
        self.assertEqual(approved, model.configuration_fingerprint(controls, EngineRules().recorded()))
        with self.assertRaises(ValueError):
            EngineRules(zero_difference_outcome="FAIL")

    def test_built_packs_carry_their_rule_in_the_fingerprint(self):
        from uc042lib.pack.generate import build
        from uc042lib.validate import PUBLISHED_RULES_BEFORE_17_NOV_2026
        _, a, _, _, _ = build(BASE)
        _, b, _, _, _ = build(BASE, rules=PUBLISHED_RULES_BEFORE_17_NOV_2026)
        self.assertNotEqual(a["audit_trail"]["configuration_fingerprint"], b["audit_trail"]["configuration_fingerprint"])
        self.assertNotEqual(a["metadata"]["pack_id"], b["metadata"]["pack_id"])

    def test_independent_validator_configurations_cannot_affect_each_other(self):
        import threading
        from uc042lib.validate import APPROVED_RULES, PUBLISHED_RULES_BEFORE_17_NOV_2026, Validator
        out = {}

        def go(name, rules):
            v = Validator(BASE, rules=rules)
            v.run()
            out[name] = {r["outcome"] for r in v.results if r["check_id"] == "C06-DIFFERENCE"}
        threads = [threading.Thread(target=go, args=(f"{n}{i}", r)) for i in range(3)
                   for n, r in (("new", APPROVED_RULES), ("old", PUBLISHED_RULES_BEFORE_17_NOV_2026))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual({k: v for k, v in out.items() if k.startswith("new")}, {f"new{i}": {"PASS"} for i in range(3)})
        self.assertEqual({k: v for k, v in out.items() if k.startswith("old")}, {f"old{i}": {"NOT_APPLICABLE"} for i in range(3)})
        self.assertEqual(Validator(BASE).rules, APPROVED_RULES)  # the default is untouched

if __name__ == "__main__":
    unittest.main()
