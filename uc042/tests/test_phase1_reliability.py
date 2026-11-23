"""Phase 1 (token-optimisation copy): AI investigation correctness.

1A  Investigations have their own output budget (UC042_INVESTIGATION_MAX_OUTPUT_TOKENS, default 12000), separate from
    the closing-summary budget (UC042_LLM_MAX_TOKENS); concise-output guidance keeps every required field and rule; a
    truncated (max_output_tokens) response is never published.
1B  Candidate relationships (CAND-*) are offered to the model as hypotheses-only; validation is unchanged (a candidate in a
    confirmed finding is still refused), and an SC5A investigation whose confirmed findings cite real evidence while a
    hypothesis discusses the candidate is VALID.
Offline: the OpenAI client is mocked. Run: python -m unittest tests.test_phase1_reliability -v"""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.test_tool_calling import (LIMITS, PACK, Temp, calls, fc, final, offline_output, openai_inv, raw, requests_of,
                                     setup_case, status_body, USAGE)
from uc042lib.investigation import config
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import OpenAIInvestigator
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT, citation_classes, tools_user_message, user_message

KEY = {config.ENV_OPENAI_KEY: "sk-test-NOT-REAL-0000"}


def make(responses, env=None, **kw):
    with mock.patch.dict(os.environ, dict(KEY, **(env or {})), clear=True), mock.patch("openai.OpenAI") as cls:
        inv = OpenAIInvestigator(model="gpt-6-luna", reasoning_effort="", **kw)
    inv._client = cls.return_value
    inv._client.responses.with_raw_response.parse.side_effect = responses
    return inv


class OutputBudget(unittest.TestCase):
    def test_defaults_are_separate(self):
        inv = make([])
        self.assertEqual((inv.investigation_max_tokens, inv.max_tokens), (12000, 8000))

    def test_environment_sets_each_budget_independently(self):
        inv = make([], env={config.ENV_INVESTIGATION_MAX_TOKENS: "15000"})
        self.assertEqual((inv.investigation_max_tokens, inv.max_tokens), (15000, 8000))
        inv = make([], env={config.ENV_MAX_TOKENS: "6000"})
        self.assertEqual((inv.investigation_max_tokens, inv.max_tokens), (12000, 6000))  # the summary budget never moves the investigation one

    def test_tool_turns_and_fixed_requests_use_the_investigation_budget(self):
        _, packet, _ = setup_case("SC2", "EXC-SC2-01")
        good = offline_output("SC2", "EXC-SC2-01")
        inv = make([final(good)])
        inv.investigate(packet)
        self.assertEqual(requests_of(inv)[0]["max_output_tokens"], 12000)
        inv = make([final(good)])
        inv.tool_turn([{"role": "user", "content": "x"}], [], timeout=30)
        self.assertEqual(requests_of(inv)[0]["max_output_tokens"], 12000)

    def test_closing_summary_keeps_its_budget(self):
        from pydantic import BaseModel

        class Tiny(BaseModel):
            text: str
        r = raw({"id": "resp_s", "model": "gpt-6-luna", "status": "completed", "output": [], "usage": USAGE}, parsed=Tiny(text="ok"))
        inv = make([r])
        inv.structured_request("instr", "content", Tiny)
        self.assertEqual(requests_of(inv)[0]["max_output_tokens"], 8000)
        self.assertIs(requests_of(inv)[0]["store"], False)


class ConciseOutputGuidance(unittest.TestCase):
    def test_required_explanatory_fields_are_still_required(self):
        schema = LLMInvestigationOutput.model_json_schema()
        finding = schema["$defs"]["ConfirmedFinding"]
        for f in ("claim", "explanation", "evidence_ids"):
            self.assertIn(f, finding["required"])
        for f in ("title", "audit_relevance", "establishes", "does_not_establish"):
            # schema 1.4: a non-empty string in the model-facing schema (strict structured output makes every property required)
            self.assertEqual((finding["properties"][f]["type"], finding["properties"][f]["minLength"] >= 5), ("string", True))

    def test_guidance_present_and_every_existing_rule_kept(self):
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            for phrase in ("claim: one concise factual sentence", "establishes: at most two sentences", "do not repeat the claim",
                           "ONE finding citing the daily records", "does_not_establish",
                           # rules that must survive unchanged
                           "Never treat it as zero", "Do not state a cause as fact", "Candidate relationships are UNVERIFIED",
                           "Do not resolve, close, approve", "untrusted data", "Actual contradiction", "Causal wording is refused",
                           "If any required evidence is missing, do not use EVIDENCE_SUFFICIENT"):
                self.assertIn(phrase, prompt)


class TruncationNeverPublishes(Temp):
    def test_final_turn_cut_at_the_output_budget_is_failed_and_unpublished(self):
        s, inv = self.run_tools([calls(fc("t1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})),
                                 status_body("incomplete", incomplete_details={"reason": "max_output_tokens"})])
        self.assertEqual(s["persist_outcome"], "NOT_PUBLISHED")
        self.assertEqual((s["result"]["investigation_status"], s["result"]["validation_status"]), ("FAILED", "NOT_VALIDATED"))
        self.assertIn("max_output_tokens", s["result"]["failure_reason"])
        self.assertEqual(list(self.tmp.rglob("findings.json")), [])
        self.assertTrue(all(r["max_output_tokens"] == 12000 for r in requests_of(inv)))

    def test_fixed_mode_truncation_is_failed_and_unpublished(self):
        inv = make([status_body("incomplete", incomplete_details={"reason": "max_output_tokens"})])
        s = run_investigation(PACK["SC2"], "EXC-SC2-01", inv, investigations_root=self.tmp, mode="fixed")
        self.assertEqual(s["persist_outcome"], "NOT_PUBLISHED")
        self.assertIn("max_output_tokens", s["result"]["failure_reason"])
        self.assertEqual(len(requests_of(inv)), 1)  # truncation is not retried
        self.assertEqual(list(self.tmp.rglob("findings.json")), [])


class CandidateCitationClasses(Temp):
    def sc5a_output(self):
        out = offline_output("SC5A", "EXC-SC5A-01")
        for f in out["confirmed_findings"]:
            f["evidence_ids"] = [i for i in f["evidence_ids"] if not i.startswith("CAND-")]
            f["supporting_records"] = [i for i in f["supporting_records"] if not i.startswith("CAND-")]
        out["hypotheses"] = [{"hypothesis_id": "H-01", "status": "HYPOTHESIS",
                              "possible_explanation": "The orphan settlement line could relate to client C0002's roll-forward difference.",
                              "supporting_evidence": ["CAND-SC5A-01", "IN-13:SL-SB-GBP-20260915-0003"], "contradictory_evidence": [],
                              "limitations": "Only a date and amount coincidence; no record links the transaction to C0002.",
                              "rationale": "The amounts and dates coincide, which is why the possibility is considered."}]
        return out

    def test_model_sees_candidates_as_hypotheses_only(self):
        _, packet, _ = setup_case("SC5A", "EXC-SC5A-01")
        cc = citation_classes(packet)
        self.assertEqual(cc["hypotheses_only_ids"], ["CAND-SC5A-01"])
        others = cc["support_ids"] + cc["completeness_ids"] + cc["context_only_ids"]  # view / prompt 1.3 classes
        self.assertNotIn("CAND-SC5A-01", others)
        self.assertEqual(sorted(others + cc["hypotheses_only_ids"]), sorted(packet["allowed_citation_ids"]))  # never widened
        for msg in (user_message(packet), tools_user_message(packet, LIMITS)):
            block = json.loads(msg.split("CITATION CLASSES:\n", 1)[1].split("\n\n", 1)[0])
            self.assertEqual(block["hypotheses_only_ids"], ["CAND-SC5A-01"])

    def test_sc5a_valid_when_the_candidate_is_only_a_hypothesis(self):
        out = self.sc5a_output()
        s, _ = self.run_tools([final(out)], scenario="SC5A", exception_id="EXC-SC5A-01")
        self.assertEqual(s["result"]["validation_status"], "VALID", s["result"]["validation_findings"])
        self.assertEqual(s["persist_outcome"], "PUBLISHED")
        self.assertEqual(s["result"]["classification_summary"]["unverified_candidate_relationships"], ["CAND-SC5A-01"])

    def test_candidate_in_a_confirmed_finding_is_still_refused(self):
        """The 16 Nov SC5A refusal reproduced: a correct roll-forward finding that also lists CAND-SC5A-01 in evidence_ids."""
        out = self.sc5a_output()
        out["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")
        s, _ = self.run_tools([final(out)], scenario="SC5A", exception_id="EXC-SC5A-01")
        self.assertEqual(s["result"]["validation_status"], "REJECTED")
        self.assertTrue(any("unverified candidate relationship is cited as confirmed evidence" in v for v in s["result"]["validation_findings"]))
        self.assertNotEqual(s["persist_outcome"], "PUBLISHED")


if __name__ == "__main__":
    unittest.main()
