"""Audit-pack generation (docs/audit_pack/01-04). Run from the uc042/ folder:  python -m unittest -v

Expected values are taken from the design documents and the verified engine outputs, not from the pack itself.
"""
import copy
import csv
import html
import json
import re
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from uc042lib import schema
from uc042lib.pack import config, model, registry
from uc042lib.pack.assemble import load_sources, run_engine
from uc042lib.pack.generate import ImmutabilityError, build, generate
from uc042lib.pack.render_html import render_html
from uc042lib.pack.validate_pack import validate_pack
from uc042lib.validate import DEFAULT_SET, Validator

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "uc042_dataset"
NAMES = list(dict.fromkeys(r["dataset"] for r in json.loads((DATASETS / "scenario_index.json").read_text())["scenarios"]))
BUILT = {}


def setUpModule():
    for n in NAMES:
        BUILT[n] = build(DATASETS / n)


def pack(name):
    return BUILT[name][1]


class D1Registry(unittest.TestCase):
    def test_every_name_is_verbatim_from_the_matrix_line(self):
        lines = (ROOT / registry.MATRIX).read_text(encoding="utf-8").splitlines()
        for code, (name, line, phrase) in registry.CONTROLS.items():
            self.assertIn(phrase, lines[line - 1], code)

    def test_unnamed_codes_are_labelled_not_invented(self):
        self.assertEqual(registry.control_name("INTEGRITY"), "INTEGRITY (not named in the source-to-control matrix)")

    def test_every_engine_control_code_has_a_name(self):
        for n in NAMES:
            for c in pack(n)["control_register"]:
                self.assertEqual(c["control_name"], registry.control_name(c["control_code"]))


class D3StructuredFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = {n: run_engine(DATASETS / n) for n in ("set_01_clean_baseline", "scn_SC2_settlement_timing", "scn_SC3C_short_settlement",
                                                      "scn_S02_missing_eur_statement")}

    def test_resource_fields_match_the_existing_computed_text(self):
        for n, v in self.v.items():
            for r in v.results:
                if r["check_id"] == "C05-RESOURCE" and r["outcome"] != "INSUFFICIENT_EVIDENCE":
                    s = r["structured"]
                    self.assertEqual(r["computed"], f"item A {s['item_a']}; resource {s['resource']}", n)
                    self.assertEqual(r["reported"], f"item A {s['item_a_reported']}; resource {s['resource_reported']}", n)

    def test_booking_lag_structured(self):
        lags = {r["scope"]: r["structured"]["booking_lag_business_days"] for r in self.v["scn_SC2_settlement_timing"].results
                if r["check_id"] == "C11-BATCH-BANK" and r["structured"]}
        self.assertEqual(lags.pop("SB-GBP-20260915"), 1)
        self.assertEqual(set(lags.values()), {0})
        r = next(r for r in self.v["scn_SC2_settlement_timing"].results if r["scope"] == "SB-GBP-20260915" and r["check_id"] == "C11-BATCH-BANK")
        self.assertEqual((r["outcome"], r["structured"]["within_one_business_day_allowance"], r["structured"]["timing_status"]),
                         ("PASS", True, "INFORMATIONAL"))

    def test_timing_structured_consistent_with_the_difference(self):
        for n in ("scn_SC2_settlement_timing", "scn_SC3C_short_settlement"):
            for r in self.v[n].results:
                if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] == "FAIL":
                    s = r["structured"]
                    self.assertEqual(Decimal(s["explained_by_timing"]) + Decimal(s["residual_unexplained"]), Decimal(r["computed"]))
        sc2 = next(r for r in self.v["scn_SC2_settlement_timing"].results if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] == "FAIL")
        self.assertEqual([(i["ledger_entry_id"], i["bank_entry_id"], i["item_status"]) for i in sc2["structured"]["timing_items"]],
                         [("LE-GBP-0915-0005", "BE-GBP-0916-T01", "IN_WINDOW")])

    def test_pdf_details_are_only_what_was_extracted(self):
        v = self.v["set_01_clean_baseline"]
        self.assertEqual(sorted(v.pdf), sorted(schema.PDF_FILES))
        for fid, d in v.pdf.items():
            self.assertTrue(set(d) <= set(schema.PDF_FILES[fid][3]), fid)

    def test_insufficient_results_carry_no_structured_figures(self):
        v = self.v["scn_S02_missing_eur_statement"]
        self.assertFalse([r for r in v.results if r["outcome"] == "INSUFFICIENT_EVIDENCE" and r["structured"]])


class Scenario1Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.status, cls.p, cls.html, cls.outputs, cls.findings = BUILT["set_01_clean_baseline"]
        cls.v = run_engine(DEFAULT_SET)

    def test_generated_without_findings(self):
        self.assertEqual((self.status, self.findings), ("GENERATED", []))

    def test_ac1_period(self):
        m = self.p["metadata"]
        self.assertEqual(m["reporting_period"], {"period_id": "PER-2026-09", "start": "2026-09-01", "end": "2026-09-30"})
        self.assertEqual(len(m["reconciliation_days"]), 22)

    def test_ac2_currency_and_accounts(self):
        m = self.p["metadata"]
        self.assertEqual(m["currency_scope"], ["EUR", "GBP"])
        self.assertEqual([(a["account_id"], a["currency"]) for a in m["accounts"]],
                         [("OWN-EUR-01", "EUR"), ("OWN-GBP-01", "GBP"), ("SGA-EUR-01", "EUR"), ("SGA-GBP-01", "GBP")])
        self.assertEqual((m["asset_pool_id"], m["entity"]["entity_id"]), ("POOL-EMONEY", "SYN-EMI-001"))
        self.assertIn("not a confirmed Moorwand production identifier", m["entity"]["notice"])

    def test_ac3_ac4_all_results_and_outcomes(self):
        co = self.p["executive_summary"]["control_outcomes"]
        self.assertEqual((co["total_results"], co["by_outcome"], co["check_types_with_results"]),
                         (1886, {"NOT_APPLICABLE": 88, "PASS": 1798}, 32))
        ids = [e["result_id"] for c in self.p["control_register"] for e in c["results"]]
        self.assertEqual(sorted(ids), sorted(model.result_id(r) for r in self.v.results))
        na = {c["check_id"]: c["result_counts"] for c in self.p["control_register"] if "NOT_APPLICABLE" in c["result_counts"]}
        self.assertEqual(na, {"C06-DIFFERENCE": {"NOT_APPLICABLE": 44}, "C08-DIFFERENCE": {"NOT_APPLICABLE": 44}})
        self.assertEqual(co["checks_no_findings"], ["BANK-CASH-LINK"])  # emits results only on failure; never shown as PASS
        expected = {"V01-SCHEMA": 14, "V01-PDF": 5, "C03-POLICY": 1, "C03-POINT": 3, "C01-COVER": 44, "C14-COVER": 484, "C07-COVER": 44,
                    "DQ23-STATEMENT": 88, "DQ22-CONTINUITY": 86, "BC-VS-EOD": 44, "CASH-BANK-LINK": 222, "C04-REQUIREMENT": 44,
                    "C05-RESOURCE": 44, "C07-BANK-EVIDENCE": 44, "RC2-LEDGER": 44, "C11-BATCH-ARITH": 88, "C11-BATCH-BANK": 88,
                    "C11-TXN-LINE": 1, "FUND-TOPUP": 44, "RC4-DIRECT": 90, "C09-ALLOCATION": 2, "C11-BANK-ENTRY": 1, "C12-REFUND": 2,
                    "CBAL-NONNEG": 1, "CBAL-ROLLFWD": 264, "C13-CURRENCY": 1, "C10-DESIGNATION": 2, "C16-GOVERNANCE": 1, "C16-RETURN": 1,
                    "DISC-LOG": 1}
        got = {c["check_id"]: c["result_counts"].get("PASS", 0) for c in self.p["control_register"] if "PASS" in c["result_counts"]}
        self.assertEqual(got, expected)

    def test_ac5_reconciliation_summaries(self):
        rec = self.p["reconciliation_summary"]
        self.assertEqual((len(rec["internal_by_currency_day"]), len(rec["external_by_account_day"])), (44, 44))
        i = {(r["date"], r["currency"]): r for r in rec["internal_by_currency_day"]}
        e = {(r["date"], r["account_id"]): r for r in rec["external_by_account_day"]}
        g, eu = i[("2026-09-30", "GBP")], i[("2026-09-30", "EUR")]
        self.assertEqual((g["requirement"], g["item_a"], g["resource"], g["difference"]), ("395844.86", "395844.86", "395844.86", "0.00"))
        self.assertEqual((eu["requirement"], eu["resource"]), ("118555.00", "118555.00"))
        for acct, amt in (("SGA-GBP-01", "395844.86"), ("SGA-EUR-01", "118555.00")):
            x = e[("2026-09-30", acct)]
            self.assertEqual((x["bank_balance"], x["ledger_balance"], x["difference"]), (amt, amt, "0.00"))
        op = rec["opening_positions"]
        self.assertEqual([(o["evidence_id"], o["amount"]) for o in op["cash_book"]],
                         [("IN-10:LE-EUR-0831-0000", "80000.00"), ("IN-10:LE-GBP-0831-0000", "250000.00")])
        self.assertEqual(len(op["client_snapshots"]), 12)

    def test_ac6_ac10_evidence_register(self):
        ev = self.p["evidence_register"]
        self.assertEqual(len(ev["files"]), 19)
        self.assertTrue(all(f["availability"] == "PRESENT" for f in ev["files"]))
        self.assertEqual(len(ev["records"]), 1920)
        rows, _, _ = load_sources(DEFAULT_SET)
        for r in ev["records"]:
            src = rows[(r["source_file"].split("/", 1)[1], r["source_line"])]
            self.assertEqual(src[schema.CSV_FILES[r["file_id"]][2][0][0]], r["primary_key"])

    def test_ac7_provenance(self):
        at = self.p["audit_trail"]
        self.assertEqual(len(at["inputs"]), 19)
        self.assertTrue(all(i["matches"] for i in at["inputs"]))
        self.assertTrue(at["engine_fingerprint"] and at["configuration_fingerprint"] and at["pack_layer_fingerprint"])
        self.assertEqual(sorted(at["processing_outputs"]), sorted(self.outputs))
        self.assertEqual(self.p["metadata"]["source_dataset"]["scenario_id"], "S01")

    def test_ac8_ac9_empty_registers_are_explicit(self):
        self.assertEqual(self.p["exception_register"], {"exceptions": [], "statement": "No exceptions were raised for this period."})
        g = self.p["investigation_group_register"]
        self.assertEqual((g["groups"], g["candidate_relationships"], g["statement"]), ([], [], "No investigation groups were formed."))
        self.assertEqual(self.p["missing_evidence_register"]["items"], [])

    def test_ac11_ac12_references_and_fidelity(self):
        rows, _, _ = load_sources(DEFAULT_SET)
        self.assertEqual(validate_pack(self.p, self.v, rows), [])

    def test_ac13_reproducible(self):
        again = build(DEFAULT_SET)
        self.assertEqual(model.canonical(again[1]), model.canonical(self.p))
        self.assertEqual(again[2], self.html)

    def test_ac14_non_empty_and_useful(self):
        s = self.p["executive_summary"]
        self.assertEqual((s["generation_status"], s["evidence_completeness"], s["control_outcomes"]["summary"], s["exception_review"],
                          s["engine_case_status"], s["pack_review_status"]),
                         ("GENERATED", "COMPLETE", "ALL_PASSED_OR_NOT_APPLICABLE", "NONE", "CLEAN", "NOT_REVIEWED"))
        st = {s_["batch_id"]: (s_["lines_result"]["outcome"], s_["bank_result"]["outcome"], s_["fee_top_up_result"].get("outcome"))
              for s_ in self.p["settlement_register"]}
        self.assertEqual(len(st), 88)
        self.assertTrue(all(a == b == "PASS" for a, b, _ in st.values()))
        self.assertEqual(sum(1 for _, _, t in st.values() if t == "PASS"), 44)
        self.assertEqual(self.p["statements"]["limitations"], config.LIMITATIONS)


class AllScenarios(unittest.TestCase):
    EXPECTED = {  # from docs/audit_pack/04 section 2 and the verified answer keys
        "set_01_clean_baseline": ("COMPLETE", "ALL_PASSED_OR_NOT_APPLICABLE", 0, 0, 0, 0, {}),
        "scn_SC2_settlement_timing": ("COMPLETE", "FAILURES_PRESENT", 1, 0, 0, 0, {"EXC-SC2-01": "TIMING_EVIDENCED"}),
        "scn_SC3B_fee_not_itemised": ("COMPLETE", "FAILURES_PRESENT", 1, 0, 0, 0, {}),
        "scn_SC3C_short_settlement": ("COMPLETE", "FAILURES_PRESENT", 3, 1, 0, 0, {"EXC-SC3C-01": "NOT_EVIDENCED"}),
        "scn_S02_missing_eur_statement": ("INCOMPLETE", "NOT_FULLY_ASSESSED", 1, 0, 0, 1, {}),
        "scn_SC5A_missing_transaction": ("COMPLETE", "FAILURES_PRESENT", 2, 0, 1, 0, {}),
        "scn_SC5C_refund_double_posted": ("COMPLETE", "FAILURES_PRESENT", 17, 1, 0, 0, {}),
        "scn_SC5D_closing_snapshot_mismatch": ("COMPLETE", "FAILURES_PRESENT", 3, 1, 0, 0, {}),
        "scn_S05_unexplained_gbp_difference": ("COMPLETE", "FAILURES_PRESENT", 2, 1, 0, 0, {"EXC-S05-01": "NOT_EVIDENCED"}),
    }

    def test_every_dataset_generates_with_expected_summary(self):
        for n, (ev, co, exc, grp, cand, miss, es) in self.EXPECTED.items():
            status, p, _, _, findings = BUILT[n]
            self.assertEqual((status, findings), ("GENERATED", []), n)
            s = p["executive_summary"]
            self.assertEqual((s["evidence_completeness"], s["control_outcomes"]["summary"], s["exceptions"]["total"],
                              s["investigation_groups"], s["candidate_relationships"], s["missing_evidence_items"]),
                             (ev, co, exc, grp, cand, miss), n)
            self.assertEqual({x["exception_id"]: x["evidence_status"] for x in p["exception_register"]["exceptions"] if x["evidence_status"]}, es, n)

    def test_scenario_specific_content(self):
        sc2 = pack("scn_SC2_settlement_timing")
        b = next(x for x in sc2["settlement_register"] if x["batch_id"] == "SB-GBP-20260915")
        self.assertEqual((b["bank_result"]["structured"]["booking_lag_business_days"], b["bank_result"]["bank_entry_ids"]),
                         (1, ["IN-09:BE-GBP-0916-T01"]))
        x = sc2["exception_register"]["exceptions"][0]
        self.assertEqual((x["status"], x["review_status"]), ("OPEN", "AWAITING_HUMAN_REVIEW"))
        self.assertIn("not resolved", x["evidence_status_detail"])
        sc3b = pack("scn_SC3B_fee_not_itemised")
        a = next(x for x in sc3b["settlement_register"] if x["batch_id"] == "AQ-GBP-20260908")
        self.assertEqual((a["total_fees"], a["lines_result"]["outcome"]), ("45.50", "FAIL"))
        base = next(x for x in pack("set_01_clean_baseline")["settlement_register"] if x["batch_id"] == "AQ-GBP-20260908")
        self.assertEqual((base["gross_amount"], base["total_fees"], base["net_amount_reported"], base["lines_result"]["outcome"],
                          base["bank_result"]["outcome"], base["fee_top_up_result"]["outcome"]), ("10000.00", "45.50", "9954.50", "PASS", "PASS", "PASS"))
        s02 = pack("scn_S02_missing_eur_statement")
        item = s02["missing_evidence_register"]["items"][0]
        self.assertEqual((item["expected_evidence"], len(item["related_result_ids"]), item["value_shown"], item["related_exception_id"]),
                         ("MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-09-15", 13, "not available", "EXC-S02-01"))
        row = next(r for r in s02["reconciliation_summary"]["external_by_account_day"] if r["date"] == "2026-09-15" and r["account_id"] == "SGA-EUR-01")
        self.assertEqual((row["bank_balance"], row["difference"]), ("not available", "not available"))
        s5a = pack("scn_SC5A_missing_transaction")["investigation_group_register"]
        self.assertEqual((s5a["groups"], [c["exception_ids"] for c in s5a["candidate_relationships"]]), ([], ["EXC-SC5A-01; EXC-SC5A-02"]))
        for n, gid, size in (("scn_SC3C_short_settlement", "GRP-SC3C-01", 3), ("scn_SC5C_refund_double_posted", "GRP-SC5C-01", 17),
                             ("scn_SC5D_closing_snapshot_mismatch", "GRP-SC5D-01", 3), ("scn_S05_unexplained_gbp_difference", "GRP-S05-01", 2)):
            g = pack(n)["investigation_group_register"]["groups"]
            self.assertEqual([(x["group_id"], x["size"], x["statement"], x["cause"]) for x in g], [(gid, size, config.GROUP_STATEMENT, "")], n)
        s05 = {x["exception_id"]: x for x in pack("scn_S05_unexplained_gbp_difference")["exception_register"]["exceptions"]}
        self.assertEqual((s05["EXC-S05-01"]["amount"], s05["EXC-S05-01"]["cause_category"]), ("-812.40", ""))
        self.assertTrue(s05["EXC-S05-01"]["category"].startswith("Unexplained"))

    def test_every_pack_validates_against_its_own_engine_run(self):
        for n in NAMES:
            v = run_engine(DATASETS / n)
            rows, _, _ = load_sources(DATASETS / n)
            self.assertEqual(validate_pack(pack(n), v, rows), [], n)


class ValidationCanFail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = run_engine(DATASETS / "scn_SC3C_short_settlement")
        cls.rows, _, _ = load_sources(DATASETS / "scn_SC3C_short_settlement")

    def found(self, mutate, level):
        p = copy.deepcopy(pack("scn_SC3C_short_settlement"))
        mutate(p)
        return [f for f in validate_pack(p, self.v, self.rows) if f.startswith(level)]

    def first_fail(self, p):
        return next(e for c in p["control_register"] for e in c["results"] if e["outcome"] == "FAIL")

    def test_v1_missing_section(self):
        self.assertTrue(self.found(lambda p: p.pop("settlement_register"), "V1"))

    def test_v2_unknown_evidence(self):
        self.assertTrue(self.found(lambda p: self.first_fail(p)["evidence_ids"].append("IN-09:NOPE"), "V2"))

    def test_v3_changed_amount(self):
        self.assertTrue(self.found(lambda p: self.first_fail(p).update(computed="-5.50"), "V3"))

    def test_v3_changed_reconciliation_figure(self):
        self.assertTrue(self.found(lambda p: p["reconciliation_summary"]["external_by_account_day"][10].update(bank_balance="1.00"), "V3"))

    def test_v4_removed_result(self):
        self.assertTrue(self.found(lambda p: p["control_register"][0]["results"].pop(), "V4"))

    def test_v5_exception_shown_resolved(self):
        self.assertTrue(self.found(lambda p: p["exception_register"]["exceptions"][0].update(status="RESOLVED"), "V5"))

    def test_v5_unexplained_described_as_explained(self):
        self.assertTrue(self.found(lambda p: p["exception_register"]["exceptions"][0].update(evidence_status_detail="explained by timing"), "V5"))

    def test_v5_group_with_a_cause(self):
        self.assertTrue(self.found(lambda p: p["investigation_group_register"]["groups"][0].update(cause="fee error"), "V5"))

    def test_v6_missing_value_shown_as_zero(self):
        p = copy.deepcopy(pack("scn_S02_missing_eur_statement"))
        p["missing_evidence_register"]["items"][0]["value_shown"] = "0.00"
        v = run_engine(DATASETS / "scn_S02_missing_eur_statement")
        rows, _, _ = load_sources(DATASETS / "scn_S02_missing_eur_statement")
        self.assertTrue([f for f in validate_pack(p, v, rows) if f.startswith("V6")])

    def test_v5_candidate_promoted_to_group(self):
        p = copy.deepcopy(pack("scn_SC5A_missing_transaction"))
        v = run_engine(DATASETS / "scn_SC5A_missing_transaction")
        p["investigation_group_register"]["groups"].append({"group_id": "GRP-SC5A-99", "exception_ids": "EXC-SC5A-01; EXC-SC5A-02",
                                                            "status": "OPEN", "cause": "", "statement": config.GROUP_STATEMENT})
        self.assertTrue([f for f in validate_pack(p, v) if f.startswith(("V3", "V5"))])


class PublishingAndImmutability(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_write_once_and_generation_history(self):
        r1 = generate(DEFAULT_SET, self.tmp)
        r2 = generate(DEFAULT_SET, self.tmp)
        self.assertEqual((r1["outcome"], r2["outcome"]), ("PUBLISHED", "ALREADY_GENERATED_IDENTICAL"))
        self.assertEqual(r1["pack_id"], r2["pack_id"])
        d = self.tmp / r1["pack_id"]
        self.assertEqual(len(list((d / "generations").glob("*.json"))), 2)
        self.assertNotIn("generated_at", (d / "pack.json").read_text())
        (d / "pack.json").write_text((d / "pack.json").read_text().replace("395844.86", "395844.87", 1))
        with self.assertRaises(ImmutabilityError):
            generate(DEFAULT_SET, self.tmp)

    def test_processing_outputs_hashes_recorded(self):
        r = generate(DEFAULT_SET, self.tmp)
        d = self.tmp / r["pack_id"]
        p = json.loads((d / "pack.json").read_text())
        for name, h in p["audit_trail"]["processing_outputs"].items():
            self.assertEqual(model.sha256_text((d / "processing" / name).read_text()), h)

    def test_failed_generation_publishes_nothing(self):
        r = generate(self.tmp / "no_such_case", self.tmp)
        self.assertEqual((r["status"], r["outcome"]), ("FAILED", "NOT_PUBLISHED"))
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.name.startswith("PACK-")], [])
        self.assertTrue(list((self.tmp / "_failed").rglob("*.json")))

    def test_missing_required_file_gives_incomplete_pack_not_failure(self):
        case = self.tmp / "case"
        shutil.copytree(DEFAULT_SET, case)
        (case / "source_data" / schema.CSV_FILES["IN-10"][0]).unlink()
        with open(case / "manifest.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with open(case / "manifest.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(r for r in rows if r["file_id"] != "IN-10")
        status, p, _, _, findings = build(case)
        self.assertEqual((status, findings), ("GENERATED", []))
        self.assertEqual(p["executive_summary"]["evidence_completeness"], "INCOMPLETE")
        item = next(i for i in p["missing_evidence_register"]["items"] if i["expected_evidence"] == "MISSING_FILE|IN-10")
        self.assertEqual(item["value_shown"], "not available")
        self.assertEqual(next(f for f in p["evidence_register"]["files"] if f["evidence_id"] == "IN-10")["availability"], "MISSING")

    def test_pack_layer_never_reads_answer_keys_or_golden(self):
        for f in (ROOT / "uc042lib" / "pack").glob("*.py"):
            text = f.read_text()
            self.assertNotIn("answer_key.json", text, f.name)
            self.assertNotIn("golden/", text, f.name)
            self.assertNotIn("compare_answer_key", text, f.name)


class HtmlFidelity(unittest.TestCase):
    def text(self, h):
        return html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", h, flags=re.S)))

    def test_every_figure_and_identifier_in_the_html_comes_from_the_pack(self):
        for n in NAMES:
            status, p, h, _, _ = BUILT[n]
            canon = model.canonical(p)
            t = self.text(h)
            for num in set(re.findall(r"(?<![\w.])-?\d+\.\d{2}(?![\d])", t)):
                self.assertTrue(num in canon, (n, num))  # every displayed figure exists in the canonical pack
            for ident in set(re.findall(r"\b(?:EXC|GRP|CAND|MISS|PACK|RUN)-[A-Za-z0-9-]+\b", t)):
                self.assertIn(ident, canon, (n, ident))

    def test_html_carries_statuses_statements_and_no_resolution(self):
        for n in NAMES:
            p, h = BUILT[n][1], BUILT[n][2]
            t = self.text(h)
            s = p["executive_summary"]
            for v in (s["generation_status"], s["evidence_completeness"], s["control_outcomes"]["summary"], s["exception_review"],
                      p["metadata"]["pack_id"], p["statements"]["not_a_compliance_opinion"], p["exception_register"]["statement"]):
                self.assertIn(str(v), t, n)
            self.assertNotIn("RESOLVED", t, n)
            for x in p["exception_register"]["exceptions"]:
                self.assertIn(x["exception_id"], t)
            for g in p["investigation_group_register"]["groups"]:
                self.assertIn(g["group_id"], t)

    def test_html_is_rendered_only_from_the_pack(self):
        p = pack("scn_SC2_settlement_timing")
        self.assertEqual(render_html(json.loads(model.canonical(p))), BUILT["scn_SC2_settlement_timing"][2])


if __name__ == "__main__":
    unittest.main()
