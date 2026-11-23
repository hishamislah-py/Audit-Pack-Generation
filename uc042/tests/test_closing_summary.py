"""AI-generated closing summary: controlled input, structured output validation, fingerprinting, failure handling (no
fabricated fallback) and its relationship with assembly. The provider is mocked; no network. Run: python -m unittest -v"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import httpx2
import openai

from tests.final_pack_support import (PACK, make_investigation, openai_investigator, raw, review_for, summary_investigator,
                                      summary_output)
from uc042lib.final_pack import (ClosingSummaryError, FinalPackValidationError, GenerationInfo, Selection, assemble_final_pack,
                                 assemble_preview, build_review_snapshot, closing_summary_input, default_selections,
                                 generate_closing_summary, load_pack, summary_fingerprint, validate_closing_summary)
from uc042lib.final_pack.model import ClosingSummaryOutput
from uc042lib.final_pack.summary import SUMMARY_INSTRUCTIONS
from tests.final_pack_support import OFFLINE

REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")


class SummaryCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.inv_root = cls.tmp / "investigations"
        make_investigation("SC5A", "EXC-SC5A-01", cls.inv_root)
        cls.snap = build_review_snapshot(PACK["SC5A"], default_selections(load_pack(PACK["SC5A"]), cls.inv_root), investigations_root=cls.inv_root)
        cls.input = closing_summary_input(cls.snap)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def errors(self, edit):
        return validate_closing_summary(summary_output(self.input, edit), self.input)


class ControlledInput(SummaryCase):
    def test_input_is_controlled_and_traceable(self):
        text = json.dumps(self.input)
        pack = load_pack(PACK["SC5A"])
        for forbidden in (pack["metadata"]["source_dataset"]["dataset"], pack["metadata"]["source_dataset"]["scenario_name"],
                          "uc042_dataset", "answer_key", "mutations", "SCENARIO_NOTES", str(self.inv_root), "source_records"):
            self.assertNotIn(forbidden, text)
        self.assertEqual([x["resolution_status"] for x in self.input["exceptions"]], ["UNRESOLVED", "UNRESOLVED"])
        refs = set(self.input["allowed_refs"])
        self.assertTrue({"EXC-SC5A-01", "EXC-SC5A-02", "CAND-SC5A-01"} <= refs)
        self.assertTrue(any(r.endswith("#F-01") for r in refs) and any(r.endswith("#H-01") for r in refs))
        self.assertEqual(summary_fingerprint(self.input), summary_fingerprint(closing_summary_input(self.snap)))  # deterministic

    def test_changed_selection_changes_the_fingerprint(self):
        other = build_review_snapshot(PACK["SC5A"], [Selection(exception_id="EXC-SC5A-01", inclusion="EXCLUDED_BY_ANALYST", reason="Not needed."),
                                                     Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")],
                                      investigations_root=self.inv_root)
        self.assertNotEqual(summary_fingerprint(closing_summary_input(other)), summary_fingerprint(self.input))


class OutputValidation(SummaryCase):
    def test_valid_summary(self):
        self.assertEqual(self.errors(None), [])

    def test_unsupported_claims_are_rejected(self):
        cases = [
            (lambda d: d["key_observations"][0].update(source_refs=["INV-EXC-SC5A-01-000000000000#F-09"]), "not in the supplied input"),
            (lambda d: d["key_observations"].append({"text": "The relationship between the exceptions is shown.", "source_refs": ["CAND-SC5A-01"]}),
             "cites only hypotheses"),
            (lambda d: d["unverified_hypotheses"][0].update(source_refs=["EXC-SC5A-01"]), "must reference a hypothesis"),
            (lambda d: d.update(unresolved_items=[]), "unresolved_items is empty"),
            (lambda d: d["unresolved_items"].append({"exception_id": "EXC-SC9-01", "text": "An exception from elsewhere."}), "not an unresolved exception"),
            (lambda d: d.update(summary_text="The reconciliation is fully compliant with the safeguarding requirements, as reviewed today."), "compliance"),
            (lambda d: d.update(summary_text="This report constitutes an audit opinion that the safeguarding position is acceptable."), "audit-opinion"),
            (lambda d: d.update(overall_position="The audit is clean and all discrepancies have been resolved by the firm."), "clean"),
            (lambda d: d["limitations"].append("We certify that the records are complete and accurate."), "certification"),
            (lambda d: d["key_observations"][0].update(text="The difference was caused by a missing transaction export."), "states a cause"),
            (lambda d: d.update(summary_text="The exception has been resolved by the settlement records reviewed in this pack."), "resolved"),
            (lambda d: d["evidence_gaps"].append({"text": "Transaction TX-0915-00009 does not exist.", "source_refs": ["EXC-SC5A-01"]}), "does not exist"),
        ]
        for edit, expect in cases:
            with self.subTest(expect=expect):
                errs = self.errors(edit)
                self.assertTrue(any(expect in e for e in errs), errs)

    def test_correct_disclaimers_are_accepted(self):
        def edit(d):
            d["summary_text"] = ("This summary is not an audit opinion and does not certify compliance. No exception is resolved; "
                                 "the missing transaction was not found in the supplied data.")
        self.assertEqual(self.errors(edit), [])

    def test_prompt_states_the_negation_scope_the_validation_applies(self):
        """12 Nov 2026 live run: gpt-6-luna wrote a limitation negating a long list ("... opinion or certification") and the
        validation (unchanged: a negation covers about 40 characters) refused the summary. The prompt now says so."""
        from uc042lib.final_pack.summary import SUMMARY_INSTRUCTIONS, _asserts, COMPLIANCE_PATTERNS
        self.assertIn("negate each term in its own short clause", SUMMARY_INSTRUCTIONS)
        long_list = "No compliance conclusion, assurance opinion or certification is given."
        split = "This is not an audit opinion. It does not certify compliance."
        self.assertTrue(any(_asserts(p, long_list) for p in COMPLIANCE_PATTERNS))  # still refused: validation not weakened
        self.assertFalse(any(_asserts(p, s) for s in split.split(". ") for p in COMPLIANCE_PATTERNS))

    def test_clean_pack_rules(self):
        snap = build_review_snapshot(PACK["S01"], [], investigations_root=self.inv_root)
        inp = closing_summary_input(snap)
        self.assertEqual(validate_closing_summary(summary_output(inp), inp), [])
        bad = summary_output(inp, lambda d: d["unresolved_items"].append({"exception_id": "EXC-S01-01", "text": "Something unresolved here."}))
        self.assertTrue(any("no exceptions" in e for e in validate_closing_summary(bad, inp)))

    def test_structured_output_schema(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(ClosingSummaryOutput)
        # summary schema 1.2 (Session 1, 23 Nov 2026): group_assessments is part of the structured output (1.4 adds only the
        # nullable common_cause_status inside each assessment; the withdrawn 1.3 draft's AI dispositions are gone)
        self.assertEqual(set(schema["required"]), {"overall_position", "summary_text", "key_observations", "unresolved_items",
                                                   "unverified_hypotheses", "evidence_gaps", "suggested_next_steps", "limitations",
                                                   "group_assessments"})
        self.assertIn("not an audit opinion", SUMMARY_INSTRUCTIONS)


class GenerationAndFailures(SummaryCase):
    def test_generated_summary_record(self):
        inv, out = summary_investigator(self.snap)
        s = generate_closing_summary(self.snap, inv)
        self.assertEqual((s.status, s.output, s.snapshot_sha256, s.source_fingerprint),
                         ("GENERATED", out, self.snap.sha256, summary_fingerprint(self.input)))
        self.assertEqual((s.model_metadata["provider"], s.model_metadata["model"], s.model_metadata["simulated"]), ("openai", "gpt-6-luna", False))
        self.assertEqual(s.model_metadata["prompt_version"], "uc042-closing-summary-prompt/1.8")   # 1.8: evidence-bearing relationships, simplified
        kw = inv._client.responses.with_raw_response.parse.call_args.kwargs
        self.assertIs(kw["text_format"], ClosingSummaryOutput)
        self.assertEqual((kw["store"], kw["instructions"]), (False, SUMMARY_INSTRUCTIONS))
        self.assertIn(self.input["pack_id"], kw["input"][0]["content"])  # the controlled input is what was sent

    def test_provider_failures_raise_and_never_fabricate(self):
        failures = [(openai.RateLimitError("slow", response=httpx2.Response(429, request=REQ), body=None), "rate_limit"),
                    (openai.AuthenticationError("bad key", response=httpx2.Response(401, request=REQ), body=None), "authentication"),
                    (openai.APITimeoutError(request=REQ), "timeout")]
        for exc, kind in failures:
            with self.subTest(kind=kind), self.assertRaises(ClosingSummaryError) as cm:
                generate_closing_summary(self.snap, openai_investigator(lambda kw, e=exc: (_ for _ in ()).throw(e)))
            self.assertEqual(cm.exception.kind, kind)
        refusal = raw(summary_output(self.input))
        refusal.http_response.json.return_value["output"] = [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]
        with self.assertRaises(ClosingSummaryError) as cm:
            generate_closing_summary(self.snap, openai_investigator(lambda kw: refusal))
        self.assertEqual(cm.exception.kind, "refusal")
        invalid = summary_output(self.input, lambda d: d.update(summary_text="All discrepancies have been resolved and the audit is clean."))
        with self.assertRaises(ClosingSummaryError) as cm:
            generate_closing_summary(self.snap, openai_investigator(lambda kw: raw(invalid)))
        self.assertEqual(cm.exception.kind, "invalid_summary")
        self.assertTrue(cm.exception.findings)
        with self.assertRaises(ClosingSummaryError) as cm:
            generate_closing_summary(self.snap, OFFLINE)  # no structured-summary support: explicit error, no stand-in text
        self.assertEqual(cm.exception.kind, "unsupported_provider")

    def test_stale_summary_is_rejected_by_the_assembler(self):
        inv, _ = summary_investigator(self.snap)
        summary = generate_closing_summary(self.snap, inv)
        other = build_review_snapshot(PACK["SC5A"], [Selection(exception_id="EXC-SC5A-01", inclusion="EXCLUDED_BY_ANALYST", reason="Not needed."),
                                                     Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")],
                                      investigations_root=self.inv_root)
        with self.assertRaises(FinalPackValidationError) as cm:
            assemble_preview(other, summary)
        self.assertIn("source fingerprint mismatch", str(cm.exception))
        with self.assertRaises(FinalPackValidationError):
            assemble_final_pack(other, summary, review_for(other, summary), GenerationInfo())
        final = assemble_final_pack(self.snap, summary, review_for(self.snap, summary), GenerationInfo())  # matching inputs
        self.assertEqual(final["closing_summary"]["source_fingerprint"], summary.source_fingerprint)


if __name__ == "__main__":
    unittest.main()
