"""Renderer 3.0 and final-pack schema 1.3: the regression matrix (A-K), the audit-integrity checks (1-15), the frozen
renderer-2.x builder and the NOT_REQUIRED closing summary. Offline: investigations and closing summaries come from the mocked
HTTP layer of the real OpenAI client (tests.final_pack_support); nothing is sent to a provider. Run from uc042/:
python -m unittest tests.test_renderer_v3 -v"""
import json
import re
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tests.final_pack_support import PACK, resealed
from tests.renderer_v3_support import (REVIEWER, SCENARIO_A_PACK, SCENARIO_A_ROOT, audit_integrity, build, norm, pdf_text,
                                       render_all, section_blocks)
from uc042lib.final_pack import (ClosingSummary, FinalPackValidationError, closing_summary_required, publish_final_pack,
                                 render_html, render_pdf, validate_closing_summary, verify_final_pack)
from uc042lib.final_pack.model import (CURRENT_RENDERER_VERSION, OUTCOME_FINAL_PACK_SCHEMA_VERSION, RESERVED_FINAL_PACK_SCHEMA_VERSIONS,
                                       SPLITTING_RENDERER_VERSION, ClosingSummaryOutput)
from uc042lib.final_pack.report import block_texts, build_report, build_report_v2
from uc042lib.final_pack.report_v3 import money, unformat

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL = ROOT / "docs" / "token_optimisation" / "zip_submission" / "pdf_fix" / "live3" / "final_packs"
OLD_PREVIEW = SCENARIO_A_ROOT / "scenario_a_preview_renderer_2_1.json"


class MatrixCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # the actual Scenario A source pack (copied from the demo environment, read-only) under a temporary packs root:
        # investigation retrieval refuses roots inside the repository's own folders
        self.scenario_a = self.tmp / "packs"
        shutil.copytree(SCENARIO_A_ROOT / SCENARIO_A_PACK, self.scenario_a / SCENARIO_A_PACK)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, final, pack, snap=None):
        pdf, html = render_all(final)
        self.assertEqual(render_pdf(final), pdf, "PDF not byte-reproducible")
        problems = audit_integrity(final, pack, pdf, html, snap)
        self.assertEqual(problems, [], problems)
        blocks = build_report(final)
        return blocks, block_texts(blocks), pdf, html

    def assert_no_ai_sections(self, texts):
        for t in ("AI investigative assessments", "Confirmed observations", "Hypotheses (not established)",
                  "Suggested next steps (recommendations, not completed actions)", "AI-generated content in this report"):
            self.assertNotIn(t, texts)


# ------------------------------------------------------------------------------------------------------------ A
class A_Clean(MatrixCase):
    def test_actual_scenario_a_pack(self):
        final, pack, snap = build(None, {}, self.tmp, summary="not_required", packs_root=self.scenario_a, pack_id=SCENARIO_A_PACK)
        self.assertFalse(closing_summary_required(snap))
        g = final["outcome_summary"]["figures"]
        self.assertEqual((g["control_results_total"], g["control_results_passed"], g["control_results_failed"], g["checks_total"],
                          g["checks_with_results"], g["checks_no_findings"], g["exceptions_total"], g["required_files_present"],
                          g["required_files_total"], g["missing_evidence_items"], g["ai_investigations_included"]),
                         (1886, 1886, 0, 33, 32, ["BANK-CASH-LINK"], 0, 17, 17, 0, 0))
        # the engine's evidence register: 17 REQUIRED + 2 OPTIONAL (IN-18, IN-19), all 19 PRESENT (not "19 required")
        self.assertEqual((g["source_files_total"], g["optional_files_total"], g["optional_files_present"]), (19, 2, 2))
        self.assertEqual(final["outcome_summary"]["headline"].split(" Zero")[0], "1,886 of 1,886 control results passed across 33 checks.")
        self.assertIn("Zero failed control results. Zero exceptions raised. No AI investigation was required.", final["outcome_summary"]["headline"])
        self.assertIn("All 17 required source files were present (and 2 of 2 optional files).", final["outcome_summary"]["statements"])
        blocks, texts, pdf, html = self.check(final, pack, snap)
        self.assertEqual([b["title"] for b in blocks if b["type"] == "section"],
                         ["Executive outcome", "Reconciliation overview", "Account-level results", "Financial and daily details",
                          "Evidence completeness and source inventory", "Analyst review and decision record",
                          "Limitations and disclosures", "Technical appendix"])
        self.assertEqual([b["number"] for b in blocks if b["type"] == "section"], list(range(1, 9)))  # no gap
        self.assert_no_ai_sections(texts)
        joined = "\n".join(texts)
        for bad in ("invalid_summary", "No confirmed observations", "No hypotheses were reported", "the analyst's reasons are in",
                    "0 ()", "AI_IDENTIFIED", "Each selected AI investigation was reviewed"):
            self.assertNotIn(bad, joined)
        self.assertNotIn("AI requests use the OpenAI Responses API", "\n".join(block_texts(section_blocks(blocks, "limitations"))))
        self.assertIn("AI requests use the OpenAI Responses API", "\n".join(block_texts(section_blocks(blocks, "appendix"))))
        # page 1: outcome panel, figures, disclosures
        first = pdf_text(pdf).split("Page 1 of")[0]
        for t in ("CLEAN", "1,886 of 1,886", "Failed control results", "Checks performed", "17 of 17", "2 of 2 optional","1,886 of 1,886 control results passed across 33 checks.",
                  "ILLUSTRATIVE SYNTHETIC DATA", "not a compliance opinion", "not an independent audit conclusion"):
            self.assertIn(norm(t), norm(first), t)
        self.assertIn("No AI closing summary was required", joined)
        self.assertEqual(final["closing_summary"]["status"], "NOT_REQUIRED")
        self.assertEqual(final["closing_summary"]["model_metadata"], {})

    def test_bank_cash_link_no_findings_is_explained_from_the_engine_note(self):
        final, pack, _ = build(None, {}, self.tmp, summary="not_required", packs_root=self.scenario_a, pack_id=SCENARIO_A_PACK)
        engine = next(c for c in pack["control_register"] if c["check_id"] == "BANK-CASH-LINK")
        self.assertEqual((engine["check_outcome"], engine["results"], engine["result_counts"]), ("NO_FINDINGS", [], {}))
        item = next(b for b in build_report(final) if b["type"] == "item" and b["heading"].startswith("BANK-CASH-LINK"))
        self.assertEqual(dict(item["fields"])["Engine note (copied)"], engine["check_outcome_note"])

    def test_s01_clean_with_not_applicable_results(self):
        final, pack, snap = build("S01", {}, self.tmp, summary="not_required")
        self.assertTrue(final["outcome_summary"]["headline"].startswith("1,798 of 1,886 control results passed across 33 checks. "
                                                                        "Of the remaining results, 88 were not applicable."))
        self.check(final, pack, snap)

    def test_not_required_is_refused_when_a_summary_is_required(self):
        with self.assertRaises(Exception):
            build("SC2", {"EXC-SC2-01": "ACCEPT"}, self.tmp, summary="not_required")


# ------------------------------------------------------------------------------------------------------------ B / H
class B_ExceptionWithoutAI(MatrixCase):
    def test_not_investigated_with_missing_evidence(self):
        final, pack, snap = build("S02", {}, self.tmp, summary="ai")
        blocks, texts, _, _ = self.check(final, pack, snap)
        x = pack["exception_register"]["exceptions"][0]
        item = next(b for b in blocks if b["type"] == "item" and b["kind"] == "unresolved")
        f = dict(item["fields"])
        self.assertEqual(f["Severity (engine)"], x["severity"])
        self.assertEqual(f["Root cause key (engine)"], x["root_cause"])
        self.assertIn(x["evidence"].split(";")[0], f["Source evidence (engine)"])  # source evidence traceable
        self.assertTrue(f["AI investigation"].startswith("Not investigated"))
        self.assertIn("No further reason was recorded", f["AI investigation"])
        self.assertEqual(final["ai_investigations"], [])
        self.assert_no_ai_sections(texts)
        # H: missing evidence identified with its impact and exception, never as present
        joined = "\n".join(texts)
        self.assertIn("MISS-01", joined)
        self.assertIn(pack["missing_evidence_register"]["items"][0]["completeness_impact"], joined)
        self.assertIn("The engine recorded 1 missing-evidence item(s)", joined)
        self.assertNotIn("All 17 required source files were present. The engine recorded no missing evidence.", joined)

    def test_excluded_by_analyst_shows_the_recorded_reason(self):
        final, pack, snap = build("S02", {"EXC-S02-01": ("EXCLUDED", "Bank statement for 15 Sept requested from the bank.")}, self.tmp)
        _, texts, _, _ = self.check(final, pack, snap)
        self.assertIn("Excluded from AI investigation by the analyst. Reason (as recorded): Bank statement for 15 Sept requested from the bank.",
                      "\n".join(texts))


# ------------------------------------------------------------------------------------------------------------ C / E / I
class C_OneExceptionWithAI(MatrixCase):
    def test_accepted_investigation_with_conflict(self):
        final, pack, snap = build("SC2", {"EXC-SC2-01": ("ACCEPT", "Agrees with the bank statement.")}, self.tmp)
        blocks, texts, _, _ = self.check(final, pack, snap)
        joined = "\n".join(texts)
        inv = final["ai_investigations"][0]
        self.assertTrue(inv["confirmed_findings"])
        for fnd in inv["confirmed_findings"]:
            self.assertTrue(any(b["type"] == "item" and b["kind"] == "confirmed" and b["heading"].startswith(fnd["ref"]) for b in blocks))
        # E: acceptance attributed, comment kept, exception still UNRESOLVED
        acc = next(b for b in section_blocks(blocks, "review") if b["type"] == "item" and b["kind"] == "accepted")
        f = dict(acc["fields"])
        self.assertEqual((f["Analyst decision"], f["Analyst comment"], f["Reviewer"]), ("ACCEPT", "Agrees with the bank statement.",
                                                                                         "Matrix Analyst (analyst-7)"))
        self.assertIn("UNRESOLVED", f["Exception status"])
        # I: both sides of the conflict identified; no source preferred
        conflicts = [b for b in blocks if b["type"] == "item" and b["kind"] == "conflict"]
        self.assertEqual(len(conflicts), len(inv["conflicts"]))
        self.assertTrue(conflicts)
        self.assertIn("no source is preferred", joined)
        for c, b in zip(inv["conflicts"], conflicts):
            self.assertEqual(dict(b["fields"])["Description"], c["description"])
        # suggested steps are recommendations, not completed actions
        steps = [b for b in blocks if b["type"] == "item" and b["kind"] == "step"]
        self.assertTrue(steps and all(b["badge"] == "SUGGESTED - NOT DONE" for b in steps))
        self.assertIn("AI-generated content in this report (investigation assessments", joined)

    def test_hypotheses_and_gap_classes(self):
        final, pack, snap = build("SC5A", {"EXC-SC5A-01": "ACCEPT"}, self.tmp)
        blocks, texts, _, _ = self.check(final, pack, snap)
        hyps = [b for b in blocks if b["type"] == "item" and b["kind"] == "hypothesis"]
        self.assertEqual(len(hyps), sum(len(i["hypotheses"]) for i in final["ai_investigations"]))
        self.assertTrue(all(dict(b["fields"])["Verification status"] == "NOT_ESTABLISHED" for b in hyps))
        gaps = [b for b in blocks if b["type"] == "item" and b["kind"] == "gap"]
        for g in (g for i in final["ai_investigations"] for g in i["evidence_gaps"]):
            self.assertTrue(any(b["heading"].startswith(g["ref"]) and b["badge"].split(" - ")[1] in g["subtypes"] for b in gaps))
        if any(i["not_found_searches"] for i in final["ai_investigations"]):
            self.assertIn("does not mean the record never existed", "\n".join(texts))


# ------------------------------------------------------------------------------------------------------------ D
class D_MultipleExceptions(MatrixCase):
    def test_three_exceptions_each_once_with_the_right_investigation(self):
        plan = {"EXC-SC3C-01": "ACCEPT", "EXC-SC3C-02": "ACCEPT", "EXC-SC3C-03": "ACCEPT"}
        final, pack, snap = build("SC3C", plan, self.tmp)
        blocks, texts, _, _ = self.check(final, pack, snap)
        for inv in final["ai_investigations"]:
            item = next(b for b in blocks if b["type"] == "item" and b["heading"] == f"{inv['exception_id']} - investigation {inv['investigation_id']}")
            self.assertIsNotNone(item)
            sel = next(s for s in snap.selections if s.investigation_id == inv["investigation_id"])
            self.assertEqual(sel.exception_id, inv["exception_id"])
        self.assertEqual(final["outcome_summary"]["figures"]["control_results_failed"], pack["executive_summary"]["control_outcomes"]["by_outcome"]["FAIL"])


# ------------------------------------------------------------------------------------------------------------ F / G
REASON = ("  The 17 Sep debit and the recurring difference are the same £812.40;\nthe cash book is missing the entry.  ")


class F_G_Reject(MatrixCase):
    def test_reject_reason_exact_no_ai_content(self):
        final, pack, snap = build("SC3B", {"EXC-SC3B-01": ("REJECT", REASON)}, self.tmp)
        blocks, texts, pdf, _ = self.check(final, pack, snap)
        self.assertEqual(final["ai_investigations"], [])
        rej = next(b for b in section_blocks(blocks, "review") if b["type"] == "item" and b["kind"] == "rejected")
        f = dict(rej["fields"])
        self.assertEqual(f["Reason for rejection (exactly as recorded by the analyst)"], REASON)
        self.assertEqual(f["Reviewer"], "Matrix Analyst (analyst-7)")
        self.assertIn("UNRESOLVED", f["Exception status"])
        inv_id = snap.selections[0].investigation_id
        self.assertEqual(f["Rejected investigation (reference kept for traceability)"], inv_id)
        self.assertIn(inv_id, snap.bundles)  # original investigation preserved and referenced
        self.assertIn("REJECTED BY ANALYST", "\n".join(texts))
        # the only AI content left is the (validated) closing summary: the disclaimer names nothing else
        disclaimer = next(t for t in texts if t.startswith("AI-generated content in this report"))
        self.assertIn("(the closing summary)", disclaimer)
        self.assertIn(norm("£812.40;"), norm(pdf_text(pdf)))

    def test_mixed_accept_and_reject_s05(self):
        plan = {"EXC-S05-01": ("REJECT", REASON), "EXC-S05-02": ("ACCEPT", "Supported by the cited records.")}
        final, pack, snap = build("S05", plan, self.tmp)
        blocks, texts, _, _ = self.check(final, pack, snap)
        self.assertEqual([i["exception_id"] for i in final["ai_investigations"]], ["EXC-S05-02"])
        review = section_blocks(blocks, "review")
        self.assertEqual([(b["heading"], b["kind"]) for b in review if b["type"] == "item"],
                         [("EXC-S05-01 - REJECTED BY ANALYST", "rejected"), ("EXC-S05-02 - AI investigation accepted by the analyst", "accepted")])
        reg = {b["heading"].split(" - ")[0]: dict(b["fields"])["AI investigation"] for b in blocks if b["type"] == "item" and b["kind"] == "unresolved"}
        self.assertIn("REJECTED BY ANALYST", reg["EXC-S05-01"])
        self.assertIn("accepted by the analyst", reg["EXC-S05-02"])
        g = final["outcome_summary"]["figures"]
        self.assertEqual((g["analyst_decisions_accept"], g["analyst_decisions_reject"], g["control_results_failed"]), (1, 1, 13))


# ------------------------------------------------------------------------------------------------------------ J
class J_SummaryFailure(MatrixCase):
    def test_invalid_summary_disclosed_neutrally_details_in_appendix(self):
        final, pack, snap = build("SC2", {"EXC-SC2-01": "ACCEPT"}, self.tmp, summary="invalid", final=True)
        blocks, texts, _, _ = self.check(final, pack, snap)
        main = "\n".join(t for a in ("outcome", "overview", "accounts", "details", "evidence", "exceptions", "review", "limitations")
                         for t in block_texts(section_blocks(blocks, a)))
        appendix = "\n".join(block_texts(section_blocks(blocks, "appendix")))
        self.assertNotIn("invalid_summary", main)
        self.assertIn("An AI closing summary was attempted but is not included: its output did not pass the deterministic validation rules", main)
        self.assertIn("No substitute text has been written", main)
        self.assertIn("closing summary generation failed (invalid_summary)", appendix)
        self.assertIn("references not in the supplied input", appendix)
        self.assertTrue(final["human_review"]["acknowledged_summary_unavailable"])
        self.assertIn("the reviewer acknowledged that it was unavailable", main)
        self.assertIsNone(final["closing_summary"]["output"])

    def test_unavailable_without_acknowledgement_is_refused(self):
        from tests.final_pack_support import review_for
        from uc042lib.final_pack import assemble_final_pack, unavailable_closing_summary
        _, _, snap = build("SC2", {"EXC-SC2-01": "ACCEPT"}, self.tmp)
        s = unavailable_closing_summary(snap, "closing summary generation failed (timeout)")
        with self.assertRaises(FinalPackValidationError):
            assemble_final_pack(snap, s, review_for(snap, s))

    def test_empty_string_reference_is_refused_and_prompt_rules(self):
        from uc042lib.final_pack.summary import SUMMARY_INSTRUCTIONS, closing_summary_input
        _, _, snap = build("SC2", {"EXC-SC2-01": "ACCEPT"}, self.tmp)
        data = closing_summary_input(snap)
        out = ClosingSummaryOutput.model_validate({
            "overall_position": "The deterministic engine reports one exception that remains unresolved.",
            "summary_text": "One exception remains unresolved; the supplied records are summarised for the reviewer here.",
            "key_observations": [], "unresolved_items": [{"exception_id": "EXC-SC2-01", "text": "Remains unresolved."}],
            "unverified_hypotheses": [], "evidence_gaps": [],
            "suggested_next_steps": [{"text": "Obtain the bank advice for the item.", "source_refs": [""]}], "limitations": []})
        problems = validate_closing_summary(out, data)
        self.assertTrue(any("an empty reference is not evidence" in p for p in problems), problems)
        self.assertIn("If allowed_refs is empty, return key_observations, unverified_hypotheses, evidence_gaps and suggested_next_steps as\n  empty lists", SUMMARY_INSTRUCTIONS)
        self.assertIn("An empty string is never a reference.", SUMMARY_INSTRUCTIONS)


# ------------------------------------------------------------------------------------------------------------ K
class K_FinalGenerated(MatrixCase):
    def test_final_pack_publishes_verifies_and_agrees(self):
        plan = {"EXC-S05-01": ("REJECT", REASON), "EXC-S05-02": "ACCEPT"}
        final, pack, snap = build("S05", plan, self.tmp, final=True)
        self.assertEqual((final["final_pack_schema_version"], final["metadata"]["report_renderer"]),
                         (OUTCOME_FINAL_PACK_SCHEMA_VERSION, CURRENT_RENDERER_VERSION))
        blocks, texts, _, _ = self.check(final, pack, snap)
        kv = dict(next(b for b in section_blocks(blocks, "review") if b["type"] == "kv")["pairs"])
        self.assertEqual((kv["Decision"], kv["Reviewer"]), ("GENERATE - authorised assembly of this report", "Matrix Analyst (analyst-7)"))
        self.assertNotIn("approved", "\n".join(block_texts(section_blocks(blocks, "review"))).lower().replace("not approved", ""))
        d = publish_final_pack(final, root=self.tmp / "fp")
        self.assertEqual(verify_final_pack(d), [])
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["renderer_version"], CURRENT_RENDERER_VERSION)
        stored = json.loads((d / "final_pack.json").read_text(encoding="utf-8"))
        self.assertEqual((d / "report.pdf").read_bytes(), render_pdf(stored))  # JSON, PDF and HTML agree
        self.assertEqual((d / "report.html").read_text(encoding="utf-8"), render_html(stored))
        with self.assertRaises(Exception):
            publish_final_pack(final, root=self.tmp / "fp")  # immutable: never overwritten
        (d / "report.pdf").write_bytes((d / "report.pdf").read_bytes() + b" ")
        self.assertTrue(verify_final_pack(d))  # tampering detected

    def test_clean_final_pack_needs_no_unavailable_acknowledgement(self):
        final, pack, snap = build(None, {}, self.tmp, summary="not_required", final=True, packs_root=self.scenario_a, pack_id=SCENARIO_A_PACK)
        self.assertFalse(final["human_review"]["acknowledged_summary_unavailable"])
        self.assertEqual(final["human_review"]["closing_summary_status"], "NOT_REQUIRED")
        self.check(final, pack, snap)
        self.assertEqual(verify_final_pack(publish_final_pack(final, root=self.tmp / "fp")), [])


# ------------------------------------------------------------------------------------------------------------ validation
class OutcomeValidation(MatrixCase):
    def test_tampered_outcome_summary_is_refused(self):
        from uc042lib.final_pack.validate import validate_final_pack
        final, _, snap = build("S01", {}, self.tmp, summary="not_required")
        s = ClosingSummary.model_validate(final["closing_summary"])
        bad = resealed(final, lambda f: f["outcome_summary"].update(headline="1,886 of 1,886 control results passed across 33 checks."))
        self.assertIn("outcome_summary differs from the deterministic outcome rules applied to this pack",
                      validate_final_pack(bad, snap, s, None, preview=True))
        bad2 = resealed(final, lambda f: f["reconciliation_results"]["control_checks"][-1].update(check_outcome_note="invented"))
        self.assertTrue(validate_final_pack(bad2, snap, s, None, preview=True))

    def test_schema_versions(self):
        self.assertEqual(OUTCOME_FINAL_PACK_SCHEMA_VERSION, "uc042-final-pack/1.3")
        self.assertIn("uc042-final-pack/1.2", RESERVED_FINAL_PACK_SCHEMA_VERSIONS)  # A1, not used
        self.assertEqual(CURRENT_RENDERER_VERSION, "uc042-final-report-renderer/3.0-unicode")


class MoneyFormatting(unittest.TestCase):
    def test_digits_never_change(self):
        for raw, ccy, shown in (("1795.59", "EUR", "€1,795.59"), ("-812.40", "GBP", "-£812.40"), ("0.00", "GBP", "£0.00"),
                                ("261822.25", "GBP", "£261,822.25"), ("1000000", "EUR", "€1,000,000"), ("12.5", "USD", "$12.5"),
                                ("not available", "GBP", "not available"), ("", "GBP", "-"), ("1E+3", "GBP", "1E+3"),
                                ("5.00", "CHF", "5.00 CHF"), ("7.10", None, "7.10")):
            self.assertEqual(money(raw, ccy), shown, raw)
            if shown not in ("-", "not available", "1E+3"):
                self.assertEqual(Decimal(unformat(shown, ccy)), Decimal(raw))


# ------------------------------------------------------------------------------------------------------------ history
class HistoricalPacks(unittest.TestCase):
    def test_renderer_2_1_packs_still_verify_byte_for_byte(self):
        dirs = sorted(HISTORICAL.glob("FAP-*"))
        self.assertTrue(dirs)
        for d in dirs:
            self.assertEqual(verify_final_pack(d), [], d.name)
            f = json.loads((d / "final_pack.json").read_text(encoding="utf-8"))
            self.assertEqual(f["metadata"]["report_renderer"], SPLITTING_RENDERER_VERSION)
            self.assertEqual(build_report(f), build_report_v2(f))

    def test_old_scenario_a_preview_renders_with_the_frozen_layout(self):
        f = json.loads(OLD_PREVIEW.read_text(encoding="utf-8"))
        blocks = build_report(f)
        self.assertEqual(len([b for b in blocks if b["type"] == "section"]), 16)  # never silently re-laid-out
        self.assertIn("closing summary generation failed (invalid_summary)", "\n".join(block_texts(blocks)))

    def test_unknown_renderer_is_refused(self):
        f = json.loads(OLD_PREVIEW.read_text(encoding="utf-8"))
        f["metadata"]["report_renderer"] = "uc042-final-report-renderer/9.9"
        with self.assertRaises(ValueError):
            build_report(f)


if __name__ == "__main__":
    unittest.main()
