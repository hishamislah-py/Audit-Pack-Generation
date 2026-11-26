"""Prompt 1.11 / 2.11-tools (23 Nov 2026, live TC06-04 on the readable-prompt build): the model listed its OWN item IDs
(F-01, H-01, C-01, M-01, S-01) in evidence_references and the whole investigation was refused as citing unknown IDs.
Own IDs in evidence_references are now dropped with a note; a genuinely unknown packet ID is still refused, and an own ID
used as a citation inside a finding is still refused."""
import unittest

from tests.final_pack_support import investigation_output, packet_for
from uc042lib.investigation.packet import build_case
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
from uc042lib.investigation.retrieval import load_pack
from uc042lib.investigation.validation import validate_output
from tests.final_pack_support import PACK


class OwnIdsInReferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = packet_for("SC5A", "EXC-SC5A-01")
        cls.case = build_case(load_pack(PACK["SC5A"]), "EXC-SC5A-01")

    def run_with(self, edit):
        return validate_output(investigation_output("SC5A", "EXC-SC5A-01", edit), self.packet, self.case)

    def test_baseline_is_valid(self):
        self.assertEqual(self.run_with(None)[0], [])

    def test_own_item_ids_in_references_are_dropped_not_refused(self):
        def edit(o):
            own = [f["finding_id"] for f in o["confirmed_findings"]] + [h["hypothesis_id"] for h in o["hypotheses"]] + \
                  [m["item_id"] for m in o["missing_evidence"]] + [s["step_id"] for s in o["recommended_next_steps"]]
            o["evidence_references"] = list(o["evidence_references"]) + own
        errors, notes, refs = self.run_with(edit)
        self.assertEqual(errors, [])
        self.assertTrue(any("own item IDs" in n for n in notes))
        self.assertFalse({r for r in refs if r[:2] in ("F-", "H-", "C-", "M-", "S-")})

    def test_unknown_packet_id_is_still_refused(self):
        def edit(o):
            o["evidence_references"] = list(o["evidence_references"]) + ["IN-10:LE-DOES-NOT-EXIST"]
        self.assertTrue(any("not present in the evidence packet" in e for e in self.run_with(edit)[0]))

    def test_own_id_cited_inside_a_finding_is_still_refused(self):
        def edit(o):
            o["confirmed_findings"][0]["evidence_ids"] = list(o["confirmed_findings"][0]["evidence_ids"]) + ["H-01"]
        self.assertTrue(any("not present in the evidence packet" in e for e in self.run_with(edit)[0]))

    def test_prompt_names_the_rules(self):
        for p in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            self.assertIn("never\n  your own item IDs", p)
            self.assertIn("WHEN THE ENGINE HAS ESTABLISHED IT", p)
            self.assertIn("£ for GBP, € for EUR", p)


if __name__ == "__main__":
    unittest.main()
