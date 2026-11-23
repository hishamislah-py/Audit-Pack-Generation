"""Negation-aware resolution rule (23 Nov 2026): the live TC06-06 investigation was refused for the correctly negated
"It does not establish bank movement for this settlement line or resolve the discrepancy." The rule must accept negation
that a VERB negator carries across or/nor coordination in the same clause, and keep refusing every affirmative or
contrastive resolution claim. The real preserved model output is replayed against its rebuilt evidence packet."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from uc042lib.final_pack.validate import _text_checks
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.investigation.validation import asserts_resolution, validate_output
from uc042lib.pack.generate import generate
from uc042lib.validate import ENRICHED_RULES

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tc06_06_live_prompt19_output_20261123.json"
SUITE = Path(r"C:\Users\artlptp263user\Downloads\UC042_RECONCILIATION_TEST_SUITE_V2")

NEGATED = [
    "It does not establish bank movement for this settlement line or resolve the discrepancy.",   # the live TC06-06 text
    "This does not resolve the exception.",
    "The records neither establish the movement nor resolve the discrepancy.",
    "The analyst cannot close the exception on this evidence.",
    "Without the bank file the review cannot resolve the discrepancy.",
    "These records do not show the payment, the batch or approve the exception.",
]
AFFIRMATIVE = [
    "The correction resolves the discrepancy.",
    "The exception is resolved.",
    "The difference has been cleared.",
    "It is not a timing item, but the payment resolved the discrepancy.",           # contrast cancels the earlier negation
    "The amount was not material and the payment resolved the discrepancy.",        # bare 'not' + 'and': still a claim
    "No further action: the transfer closed the exception.",                        # new clause after ':'
    "It does not establish X; the refund resolved the discrepancy.",                # new clause after ';'
    "Neither file is missing and the refund closed the exception.",                 # 'and' breaks the negation
    "No evidence shows that the difference has been resolved.",                     # bare 'No' is not a verb negator (unchanged)
]


class ResolutionRule(unittest.TestCase):
    def test_correctly_negated_statements_are_not_resolution_claims(self):
        for t in NEGATED:
            self.assertFalse(asserts_resolution(t), t)

    def test_affirmative_and_contrastive_resolution_claims_are_still_refused(self):
        for t in AFFIRMATIVE:
            self.assertTrue(asserts_resolution(t), t)

    def test_final_pack_text_check_uses_the_same_rule(self):
        final = {"ai_investigations": [{"confirmed_findings": [
            {"ref": "F-1", "title": None, "description": NEGATED[0], "establishes": None},
            {"ref": "F-2", "title": None, "description": AFFIRMATIVE[0], "establishes": None}]}]}
        self.assertEqual(_text_checks(final), ["F-2: resolution stated in a confirmed observation"])


class LiveTC0606Replay(unittest.TestCase):
    """The preserved live output (response resp_0a464105...) replayed against TC06-06's evidence packet, rebuilt from the
    suite dataset with the same deterministic code."""

    @classmethod
    def setUpClass(cls):
        if not SUITE.is_dir():
            raise unittest.SkipTest("TC suite not available")
        cls.tmp = Path(tempfile.mkdtemp(prefix="res_neg_"))
        case_dir = cls.tmp / "datasets" / "tc06_independent_causes"
        shutil.copytree(SUITE / "TC06_INDEPENDENT_CAUSES" / "initial_submission", case_dir)
        (cls.tmp / "packs").mkdir()
        generate(case_dir, cls.tmp / "packs", rules=ENRICHED_RULES)
        pid = next(p.name for p in (cls.tmp / "packs").iterdir() if p.name.startswith("PACK-"))
        pack = load_pack(pid, cls.tmp / "packs")
        cls.case = build_case(pack, "EXC-TC06-06")
        route = route_for(cls.case["exception"], cls.case["candidates"], cls.case["results"])
        cls.packet = build_packet(cls.case, build_scope(cls.case), route,
                                  retrieve(route, cls.case, EvidenceStore(pack, cls.tmp / "datasets")))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_live_output_now_validates(self):
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
        out = LLMInvestigationOutput.model_validate(fx["output"])
        f05 = next(f for f in out.confirmed_findings if f.finding_id == "F-05")
        self.assertIn("or resolve the discrepancy", f05.does_not_establish)
        errors, notes, refs = validate_output(out, self.packet, self.case)
        self.assertEqual(errors, [])

    def test_an_affirmative_rewrite_of_the_same_output_is_still_refused(self):
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data = fx["output"]
        f = next(x for x in data["confirmed_findings"] if x["finding_id"] == "F-05")
        f["does_not_establish"] = "The settlement line match resolves the discrepancy involving TX-0917-00002."
        errors, _, _ = validate_output(LLMInvestigationOutput.model_validate(data), self.packet, self.case)
        self.assertTrue(any("F-05: does_not_establish states or implies the exception is resolved" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
