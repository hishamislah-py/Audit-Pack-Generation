"""Stage 7, DR-12: the citation-class rule distinguishes a hypothesis's own contradictory_evidence field (a candidate MAY
be cited there, as hypothesis evidence) from the top-level contradictory_evidence list (a candidate is never cited there).
Prompt versions 1.7 / 2.7-tools. Validation is unchanged (validation.py byte-identical to Clone E): a candidate as one side
of a top-level contradiction is still refused. Also states the DR-04 amounts column correctly (signed, one-to-one, null).
Offline. Run: python -m unittest tests.test_stage7_dr12_prompt -v"""
import re
import unittest
from pathlib import Path

from tests.test_phase1_reliability import CandidateCitationClasses
from uc042lib.investigation import config
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parent.parent


class Versions(unittest.TestCase):
    def test_prompt_versions_bumped(self):
        self.assertEqual((config.PROMPT_VERSION, config.TOOLS_PROMPT_VERSION),
                         ("uc042-investigator-prompt/1.12", "uc042-investigator-prompt/2.12-tools"))


class Wording(unittest.TestCase):
    def test_both_contradictory_evidence_meanings_are_named(self):
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            flat = re.sub(r"\s+", " ", prompt)
            self.assertIn("that hypothesis's own supporting_evidence or contradictory_evidence", flat)
            self.assertIn("TOP-LEVEL contradictory_evidence list", flat)
            self.assertNotIn("and never in contradictory_evidence.", flat)  # the ambiguous 1.6 wording
            self.assertIn("never one side of a contradiction", flat)

    def test_amounts_column_described_as_in_the_view(self):
        flat = re.sub(r"\s+", " ", SYSTEM_PROMPT)
        self.assertNotIn("amounts_agree", flat)
        self.assertIn("signed amounts", flat)
        self.assertIn("only for one-to-one links", flat)
        self.assertIn("null means not compared", flat)


class ValidationUnchanged(CandidateCitationClasses):
    # reuse the SC5A helpers only; the inherited tests already run in tests.test_phase1_reliability
    test_model_sees_candidates_as_hypotheses_only = None
    test_sc5a_valid_when_the_candidate_is_only_a_hypothesis = None
    test_candidate_in_a_confirmed_finding_is_still_refused = None

    def test_validator_keeps_every_clone_e_rule(self):
        """DR-12 changed prompts only (validation byte-identical to Clone E). Findings schema 1.5 (20 Nov 2026) changes the
        validation deliberately (evidence_basis, traceable completeness results, absence claims); this guard now proves
        that every refusal message of the Clone E validator is still produced by the current one, so no rule was removed."""
        clone_e = Path("C:/Users/artlptp263user/p10/uc042_e/uc042lib/investigation/validation.py")
        if clone_e.is_file():
            current = (ROOT / "uc042lib" / "investigation" / "validation.py").read_text(encoding="utf-8")
            old = clone_e.read_text(encoding="utf-8")
            messages = re.findall(r'errors\.append\(f?"([^"]+)"', old)
            fragments = [s.strip() for m in messages for s in re.split(r"\{[^}]*\}", m) if len(s.strip()) >= 12]
            self.assertGreater(len(fragments), 15)
            for s in fragments:
                self.assertIn(s, current, s)

    def test_candidate_in_a_hypothesis_contradictory_evidence_is_valid(self):
        out = self.sc5a_output()
        out["hypotheses"][0]["supporting_evidence"] = ["IN-13:SL-SB-GBP-20260915-0003"]
        out["hypotheses"][0]["contradictory_evidence"] = ["CAND-SC5A-01"]
        s, _ = self.run_tools([__import__("tests.test_tool_calling", fromlist=["final"]).final(out)], scenario="SC5A", exception_id="EXC-SC5A-01")
        self.assertEqual(s["result"]["validation_status"], "VALID", s["result"]["validation_findings"])

    def test_candidate_as_one_side_of_a_top_level_contradiction_is_still_refused(self):
        out = self.sc5a_output()
        out["contradictory_evidence"] = [{"item_id": "C-01", "description": "The candidate and the settlement line disagree.",
                                          "evidence_ids": ["IN-13:SL-SB-GBP-20260915-0003"],
                                          "compared_evidence": ["CAND-SC5A-01", "IN-13:SL-SB-GBP-20260915-0003"],
                                          "same_measure_and_scope": "Both concern the same GBP amount on 15 September 2026."}]
        s, _ = self.run_tools([__import__("tests.test_tool_calling", fromlist=["final"]).final(out)], scenario="SC5A", exception_id="EXC-SC5A-01")
        self.assertEqual(s["result"]["validation_status"], "REJECTED")
        self.assertTrue(any("unverified evidence" in v for v in s["result"]["validation_findings"]), s["result"]["validation_findings"])


if __name__ == "__main__":
    unittest.main()
