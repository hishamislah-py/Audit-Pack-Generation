"""UC-042 milestone-1 tests. Run from the uc042/ folder:  python -m unittest -v

The 'ChecksCanFail' tests break a temporary copy of the baseline in one place each and confirm the
right check catches it. They prove the clean PASS results are earned, not copied. Temporary copies are
deleted after each test; they are test fixtures, not the scenario datasets (those await review).
"""
import csv
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from uc042lib import generate, money, schema
from uc042lib.validate import DEFAULT_SET, Validator

BASE = DEFAULT_SET


def results_for(root):
    return Validator(root).run()


def find(results, check, scope):
    return [r for r in results if r["check_id"] == check and r["scope"] == scope]


def mutate_csv(root, fid, fn):
    """Apply fn(rows) -> rows to one CSV in a dataset copy (manifest is deliberately left stale)."""
    path = Path(root) / "source_data" / schema.CSV_FILES[fid][0]
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows = fn(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


class SignRules(unittest.TestCase):
    def test_bank(self):
        self.assertEqual(money.signed("10.00", "C", "bank"), Decimal("10.00"))
        self.assertEqual(money.signed("10.00", "D", "bank"), Decimal("-10.00"))

    def test_cashbook_is_opposite_of_bank(self):
        self.assertEqual(money.signed("10.00", "D", "cashbook"), Decimal("10.00"))
        self.assertEqual(money.signed("10.00", "C", "cashbook"), Decimal("-10.00"))

    def test_client_and_settlement(self):
        self.assertEqual(money.signed("5.50", "CR", "client"), Decimal("5.50"))
        self.assertEqual(money.signed("5.50", "DR", "client"), Decimal("-5.50"))
        self.assertEqual(money.signed("5.50", "D", "settlement"), Decimal("-5.50"))
        self.assertEqual(money.signed("5.50", "C", "settlement"), Decimal("5.50"))
        self.assertEqual(money.batch_net_signed("9.00", "FROM_FIRM"), Decimal("-9.00"))
        self.assertEqual(money.batch_net_signed("9.00", "TO_FIRM"), Decimal("9.00"))

    def test_rejects_bad_input(self):
        for bad in ("10", "10.0", "-10.00", "1,000.00", "10.001", " 10.00"):
            with self.assertRaises(money.MoneyFormatError):
                money.parse_unsigned(bad)
        with self.assertRaises(money.MoneyFormatError):
            money.signed("1.00", "CR", "bank")
        with self.assertRaises(money.MoneyFormatError):
            money.batch_net_signed("1.00", "SIDEWAYS")

    def test_fee_rounding_half_up(self):
        self.assertEqual(money.round_half_up(Decimal("0.125")), Decimal("0.13"))
        self.assertEqual(money.round_half_up(Decimal("0.124")), Decimal("0.12"))


class Determinism(unittest.TestCase):
    def test_two_runs_identical_and_match_committed_baseline(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            a = generate.generate(Path(t1) / "a")
            b = generate.generate(Path(t2) / "b")
        self.assertEqual([r[10] for r in a], [r[10] for r in b])
        with open(BASE / "manifest.csv", encoding="utf-8") as f:
            committed = [r["sha256"] for r in csv.DictReader(f)]
        self.assertEqual([r[10] for r in a], committed, "committed baseline differs from a fresh generation")


class CleanBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = results_for(BASE)
        with open(BASE / "manifest.csv", encoding="utf-8") as f:
            cls.manifest = {r["file_id"]: r for r in csv.DictReader(f)}

    def test_inventory_and_structural_counts(self):
        self.assertEqual(len(self.manifest), 19)
        expected = {"IN-01": 30, "IN-02": 4, "IN-03": 276,  # 264 September rows + 12 opening rows (decision D4) "IN-04": 2, "IN-05": 44, "IN-06": 44, "IN-07": 44,
                    "IN-08": 88, "IN-12": 88, "IN-14": 0}
        for fid, n in expected.items():
            self.assertEqual(int(self.manifest[fid]["record_count"]), n, fid)
        self.assertEqual({fid for fid, m in self.manifest.items() if m["requirement"] == "OPTIONAL"}, {"IN-18", "IN-19"})

    def test_no_failures_or_missing_evidence(self):
        bad = [r for r in self.results if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE")]
        self.assertEqual(bad, [], bad[:5])

    def test_essential_checks_ran_on_every_scope(self):
        counts = {}
        for r in self.results:
            counts.setdefault(r["check_id"], []).append(r["outcome"])
        self.assertEqual(counts["C04-REQUIREMENT"].count("PASS"), 44)
        self.assertEqual(counts["C05-RESOURCE"].count("PASS"), 44)
        self.assertEqual(counts["C07-BANK-EVIDENCE"].count("PASS"), 44)
        self.assertEqual(counts["RC2-LEDGER"].count("PASS"), 44)
        self.assertEqual(counts["C11-BATCH-BANK"].count("PASS"), 88)
        self.assertEqual(counts["C11-BATCH-ARITH"].count("PASS"), 88)
        self.assertEqual(counts["DQ23-STATEMENT"].count("PASS"), 88)

    def test_every_citation_resolves(self):
        lengths = {}
        for fid, (fname, _, _) in schema.CSV_FILES.items():
            with open(BASE / "source_data" / fname, encoding="utf-8") as f:
                lengths[fname] = sum(1 for _ in f)
        pdfs = {v[0] for v in schema.PDF_FILES.values()}
        for r in self.results:
            if r["outcome"] == "PASS":
                self.assertTrue(r["evidence"], f"PASS without evidence: {r}")
            for ref in filter(None, (x.strip() for x in r["evidence"].split(";"))):
                if ref == "all CSV inputs":
                    continue
                fid, rest = ref.split(":", 1)
                fname = rest.split("#")[0].split(" ")[0]
                self.assertTrue(fname in lengths or fname in pdfs, ref)
                if "#L" in rest:
                    for part in rest.split("#L")[1].split(" ")[0].split("-L"):
                        self.assertLessEqual(int(part), lengths[fname], ref)

    def test_spec_key_records(self):
        def row(fid, key):
            with open(BASE / "source_data" / schema.CSV_FILES[fid][0], encoding="utf-8") as f:
                return next(r for r in csv.DictReader(f) if r[schema.columns(fid)[0]] == key)
        aq = row("IN-12", "AQ-GBP-20260908")
        self.assertEqual((aq["gross_amount"], aq["total_fees"], aq["net_amount_reported"]), ("10000.00", "45.50", "9954.50"))
        self.assertEqual(row("IN-12", "SB-GBP-20260910")["net_amount_reported"], "3412.75")
        self.assertEqual(row("IN-09", "BE-GBP-0908-TU1")["amount"], "45.50")
        sp = row("IN-11", "TX-0902-00044")
        self.assertEqual((sp["client_id"], sp["amount"], sp["settlement_batch_id"]), ("C0002", "60.00", "SB-GBP-20260902"))
        self.assertEqual(row("IN-11", "TX-0909-0R001")["original_txn_id"], "TX-0902-00044")


class Regressions(unittest.TestCase):
    """One test per bug fixed in the 29 Oct review."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "copy"
        shutil.copytree(BASE, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_manifest_counts_are_data_rows_excluding_header(self):
        with open(BASE / "manifest.csv", encoding="utf-8") as f:
            manifest = list(csv.DictReader(f))
        total = 0
        for m in manifest:
            if m["format"] != "CSV":
                continue
            with open(BASE / m["relative_path"], encoding="utf-8") as f:
                physical = sum(1 for _ in f)
            self.assertEqual(m["record_unit"], "data_rows")
            self.assertEqual(int(m["record_count"]), physical - 1, m["filename"])
            total += int(m["record_count"])
        self.assertEqual(total, 1952)  # 1,940 + 12 opening client snapshot rows (decision D4)

    def test_not_applicable_only_where_documented(self):
        allowed = {"C06-DIFFERENCE", "C08-DIFFERENCE", "V00-FILE", "C16-GOVERNANCE", "C16-RETURN"}
        na = {r["check_id"] for r in results_for(BASE) if r["outcome"] == "NOT_APPLICABLE"}
        self.assertTrue(na <= allowed, na - allowed)

    def test_missing_bank_entry_with_statement_present_is_fail(self):
        mutate_csv(self.root, "IN-09", lambda rows: [r for r in rows if r["bank_entry_id"] != "BE-GBP-0908-L01"])
        res = results_for(self.root)
        with open(BASE / "source_data" / schema.CSV_FILES["IN-11"][0], encoding="utf-8") as f:
            txn = next(t for t in csv.DictReader(f) if t["payment_reference"] == "E2E-GBP-0908-L01")
        self.assertEqual(find(res, "RC4-DIRECT", txn["txn_id"])[0]["outcome"], "FAIL")

    def test_topup_with_missing_statement_is_insufficient(self):
        mutate_csv(self.root, "IN-08", lambda rows: [r for r in rows if r["statement_id"] != "ST-SGA-GBP-01-20260908-EOD"])
        mutate_csv(self.root, "IN-09", lambda rows: [r for r in rows if r["statement_id"] != "ST-SGA-GBP-01-20260908-EOD"])
        res = results_for(self.root)
        self.assertEqual(find(res, "FUND-TOPUP", "AQ-GBP-20260908")[0]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(find(res, "DQ22-CONTINUITY", "ST-SGA-GBP-01-20260909-EOD")[0]["outcome"], "INSUFFICIENT_EVIDENCE")

    def test_unmatched_bank_entry_reported_once_per_check(self):
        def add(rows):
            extra = dict(rows[0], bank_entry_id="BE-GBP-0901-X99", bank_reference="UNKNOWN", end_to_end_ref="")
            return rows + [extra]
        mutate_csv(self.root, "IN-09", add)
        res = results_for(self.root)
        c11 = [r for r in res if r["check_id"] == "C11-BANK-ENTRY" and r["outcome"] == "FAIL"]
        self.assertEqual([r["scope"] for r in c11], ["BE-GBP-0901-X99"])
        self.assertEqual(find(res, "C11-BANK-ENTRY", "all safeguarding bank entries"), [])

    def test_every_non_passing_result_has_evidence_and_one_exception(self):
        mutate_csv(self.root, "IN-07", lambda rows: [r for r in rows if r["statement_id"] != "ST-SGA-EUR-01-20260915-1700"])
        v = Validator(self.root)
        res = v.run()
        bad = [r for r in res if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE")]
        self.assertTrue(bad)
        roots = {x["root_cause"] for x in v.exceptions}
        for r in bad:
            self.assertTrue(r["evidence"] or r["note"], r)
            self.assertIn(r["root_cause"], roots)


class ChecksCanFail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "copy"
        shutil.copytree(BASE, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_reported_requirement_is_not_trusted(self):
        def bump(rows):
            for r in rows:
                if r["recon_run_id"] == "IRR-EMONEY-GBP-20260915":
                    r["requirement_reported"] = str(Decimal(r["requirement_reported"]) + Decimal("0.01"))
            return rows
        mutate_csv(self.root, "IN-05", bump)
        res = results_for(self.root)
        self.assertEqual(find(res, "C04-REQUIREMENT", "2026-09-15/GBP")[0]["outcome"], "FAIL")
        self.assertEqual(find(res, "C04-REQUIREMENT", "2026-09-14/GBP")[0]["outcome"], "PASS")

    def test_cashbook_change_breaks_resource_and_ledger(self):
        def bump(rows):
            for r in rows:
                if r["payment_reference"] == "E2E-GBP-0908-L01":
                    r["amount"] = str(Decimal(r["amount"]) + Decimal("1.00"))
            return rows
        mutate_csv(self.root, "IN-10", bump)
        res = results_for(self.root)
        self.assertEqual(find(res, "C05-RESOURCE", "2026-09-07/GBP")[0]["outcome"], "PASS")
        self.assertEqual(find(res, "C05-RESOURCE", "2026-09-08/GBP")[0]["outcome"], "FAIL")
        self.assertEqual(find(res, "RC2-LEDGER", "2026-09-30/SGA-GBP-01")[0]["outcome"], "FAIL")
        self.assertTrue(any(r["check_id"] == "CASH-BANK-LINK" and r["outcome"] == "FAIL" for r in res))

    def test_missing_bank_confirmation_is_insufficient_not_zero(self):
        mutate_csv(self.root, "IN-07", lambda rows: [r for r in rows if r["statement_id"] != "ST-SGA-EUR-01-20260915-1700"])
        res = results_for(self.root)
        c07 = find(res, "C07-BANK-EVIDENCE", "2026-09-15/SGA-EUR-01")[0]
        self.assertEqual(c07["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(c07["computed"], "", "no bank balance may be substituted")
        self.assertEqual(find(res, "C08-DIFFERENCE", "2026-09-15/SGA-EUR-01")[0]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(find(res, "C14-COVER", "IN-07 2026-09-15/SGA-EUR-01")[0]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(find(res, "C07-BANK-EVIDENCE", "2026-09-16/SGA-EUR-01")[0]["outcome"], "PASS")

    def test_equal_amount_is_not_a_link(self):
        def reref(rows):
            for r in rows:
                if r["bank_entry_id"] == "BE-GBP-0910-SB1":
                    r["bank_reference"] = "SB-GBP-20260901"
            return rows
        mutate_csv(self.root, "IN-09", reref)
        res = results_for(self.root)
        self.assertEqual(find(res, "C11-BATCH-BANK", "SB-GBP-20260910")[0]["outcome"], "FAIL")
        self.assertEqual(find(res, "C11-BATCH-BANK", "SB-GBP-20260901")[0]["outcome"], "FAIL")

    def test_fee_lines_required_for_gross_to_net(self):
        mutate_csv(self.root, "IN-13", lambda rows: [r for r in rows if not (r["batch_id"] == "AQ-GBP-20260908" and r["line_type"] == "FEE")])
        res = results_for(self.root)
        self.assertEqual(find(res, "C11-BATCH-ARITH", "AQ-GBP-20260908")[0]["outcome"], "FAIL")

    def test_renamed_text_file_is_not_a_pdf(self):
        (self.root / "supporting_documents" / schema.PDF_FILES["IN-17"][0]).write_text("Reconciliation point: 17:00 Europe/London\n")
        res = results_for(self.root)
        self.assertEqual(find(res, "V01-PDF", "IN-17")[0]["outcome"], "FAIL")
        # Hardening phase: a check gated by unusable evidence returns one result with scope "all scopes".
        gated = find(res, "C03-POINT", "all scopes")
        self.assertEqual(len(gated), 1)
        self.assertEqual(gated[0]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(gated[0]["root_cause"], "INVALID_FILE|IN-17")


if __name__ == "__main__":
    unittest.main()


class Scenarios(unittest.TestCase):
    """Built scenario datasets: answer keys match, baseline untouched, diff equals the mutation list."""

    @classmethod
    def setUpClass(cls):
        from uc042lib import scenarios
        cls.sc = scenarios
        cls.base_hashes = scenarios.baseline_hashes()
        cls.out = {}
        for sid, d in (("S02", scenarios.S02_DIR), ("S05", scenarios.S05_DIR)):
            v = Validator(d)
            res = v.run()
            cls.out[sid] = (d, res, v.exceptions)

    def test_answer_keys_match(self):
        from uc042lib.validate import compare_answer_key
        for sid, (d, res, exc) in self.out.items():
            matched, diffs = compare_answer_key(d, res, exc)
            self.assertTrue(matched, (sid, diffs))

    def test_rebuild_is_identical_and_baseline_untouched(self):
        for sid, fn, d in (("S02", self.sc.s02_definition, self.sc.S02_DIR), ("S05", self.sc.s05_definition, self.sc.S05_DIR)):
            with open(d / "manifest.csv", encoding="utf-8") as f:
                committed = [r["sha256"] for r in csv.DictReader(f)]
            with tempfile.TemporaryDirectory() as t:
                scenario, ops, key, notes = fn()
                out = self.sc.build(Path(t) / sid, scenario, ops, key, notes)
                with open(out / "manifest.csv", encoding="utf-8") as f:
                    fresh = [r["sha256"] for r in csv.DictReader(f)]
            self.assertEqual(fresh, committed, sid)
        self.assertEqual(self.sc.baseline_hashes(), self.base_hashes)

    def test_diff_equals_mutation_list(self):
        import json
        for sid, (d, _, _) in self.out.items():
            ops = json.loads((d / "mutations.json").read_text())
            touched = {op["file_id"] for op in ops}
            with open(BASE / "manifest.csv", encoding="utf-8") as f:
                base = {r["file_id"]: r["sha256"] for r in csv.DictReader(f)}
            with open(d / "manifest.csv", encoding="utf-8") as f:
                scen = {r["file_id"]: r["sha256"] for r in csv.DictReader(f)}
            changed = {fid for fid in base if base[fid] != scen[fid]}
            self.assertEqual(changed, touched, sid)
            for fid in touched:
                pk = schema.columns(fid)[0]
                with open(BASE / "source_data" / schema.CSV_FILES[fid][0], encoding="utf-8") as f:
                    b = {r[pk]: r for r in csv.DictReader(f)}
                with open(d / "source_data" / schema.CSV_FILES[fid][0], encoding="utf-8") as f:
                    s_ = {r[pk]: r for r in csv.DictReader(f)}
                expect_deleted = {op["key"] for op in ops if op["file_id"] == fid and op["op"] == "delete_record"}
                expect_added = {op["record"][pk] for op in ops if op["file_id"] == fid and op["op"] == "add_record"}
                expect_changed = {op["key"] for op in ops if op["file_id"] == fid and op["op"] == "set_field"}
                self.assertEqual(set(b) - set(s_), expect_deleted, (sid, fid))
                self.assertEqual(set(s_) - set(b), expect_added, (sid, fid))
                self.assertEqual({k for k in b if k in s_ and b[k] != s_[k]}, expect_changed, (sid, fid))

    def test_trace_finds_results_citing_a_record(self):
        import io, contextlib
        from uc042lib.trace import trace
        cases = ((BASE, "IRR-EMONEY-GBP-20260911", "PASS"), (self.sc.S02_DIR, "ERL-SGA-EUR-01-20260915", "INSUFFICIENT_EVIDENCE"),
                 (self.sc.S05_DIR, "BE-GBP-0917-X01", "FAIL"), (self.sc.S05_DIR, "EXC-S05-01", "FAIL"))
        for root, term, outcome in cases:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                trace(term, root)
            self.assertIn(outcome, buf.getvalue(), term)

    def test_every_non_passing_result_cites_source_rows(self):
        for sid, (d, res, exc) in self.out.items():
            for r in res:
                if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE"):
                    self.assertRegex(r["evidence"], r"IN-\d\d:[^#;]+#L\d+", (sid, r["check_id"], r["scope"]))

    def test_s02_must_hold(self):
        _, res, exc = self.out["S02"]
        self.assertEqual(find(res, "C07-BANK-EVIDENCE", "2026-09-15/SGA-EUR-01")[0]["computed"], "")
        self.assertEqual(find(res, "C04-REQUIREMENT", "2026-09-15/EUR")[0]["outcome"], "PASS")
        self.assertEqual(find(res, "C05-RESOURCE", "2026-09-15/EUR")[0]["outcome"], "PASS")
        self.assertEqual(find(res, "C07-BANK-EVIDENCE", "2026-09-16/SGA-EUR-01")[0]["outcome"], "PASS")
        self.assertFalse([r for r in res if r["outcome"] == "PASS" and "2026-09-15/SGA-EUR-01" in r["scope"]
                          and r["check_id"] in ("C07-BANK-EVIDENCE", "C08-DIFFERENCE")])

    def test_s05_must_hold(self):
        _, res, exc = self.out["S05"]
        self.assertTrue(all(r["outcome"] == "PASS" for r in res if r["check_id"] in ("C04-REQUIREMENT", "C05-RESOURCE")))
        self.assertTrue(all(r["outcome"] == "PASS" for r in res if r["check_id"] in ("C07-BANK-EVIDENCE", "RC2-LEDGER")))
        self.assertTrue(all(x["cause_category"] == "" for x in exc))
        self.assertFalse([r for r in res if "BE-GBP-0917-X01" in r["evidence"] and r["check_id"].startswith("C11-BATCH")])
        e1 = next(x for x in exc if x["exception_id"] == "EXC-S05-01")
        self.assertIn("OWN_FUNDS_REQUIRED", e1["flags"])
        self.assertIn("NO_INVESTIGATION_LOGGED", e1["flags"])
        self.assertEqual(e1["amount"], "-812.40")
        self.assertEqual((e1["first_date"], e1["last_date"]), ("2026-09-17", "2026-09-30"))
