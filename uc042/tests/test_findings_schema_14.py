"""Findings schema 1.4 (additive explanatory fields) and backward compatibility with schema 1.3 artefacts.
Run from uc042/: python -m unittest -v"""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openai.lib._pydantic import to_strict_json_schema

from tests.final_pack_support import PACK, investigation_output, make_investigation, packet_for
from uc042lib.investigation import config
from uc042lib.investigation.models import InvestigationResult, LLMInvestigationOutput
from uc042lib.investigation.packet import build_case
from uc042lib.investigation.persistence import verify_published
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
from uc042lib.investigation.retrieval import load_pack
from uc042lib.investigation.validation import validate_output

NEW_FINDING_FIELDS = ("title", "audit_relevance", "establishes", "does_not_establish")


def schema_13(output):
    """The same output as an artefact written under findings schema 1.3 would hold it (no 1.4 fields)."""
    d = copy.deepcopy(output.model_dump())
    for f in d["confirmed_findings"]:
        for k in NEW_FINDING_FIELDS:
            f.pop(k)
    for h in d["hypotheses"]:
        h.pop("rationale")
    return d


class SchemaCompatibility(unittest.TestCase):
    def test_schema_13_findings_still_load_and_round_trip_without_fabrication(self):
        legacy = schema_13(investigation_output("SC5A", "EXC-SC5A-01"))
        out = LLMInvestigationOutput.model_validate(legacy)
        self.assertTrue(all(getattr(f, k) is None for f in out.confirmed_findings for k in NEW_FINDING_FIELDS))
        self.assertTrue(all(h.rationale is None for h in out.hypotheses))
        self.assertEqual(LLMInvestigationOutput.model_validate(out.model_dump()), out)  # explicit None round-trips
        case = build_case(load_pack(PACK["SC5A"]), "EXC-SC5A-01")
        self.assertEqual(validate_output(out, packet_for("SC5A", "EXC-SC5A-01"), case)[0], [])  # 1.3 content re-validates

    def test_schema_14_fields_load_and_are_preserved_through_persistence(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            iid = make_investigation("SC5A", "EXC-SC5A-01", tmp)
            d = next(tmp.rglob(iid))
            stored = json.loads((d / "findings.json").read_text())
            self.assertEqual(stored["model_metadata"]["findings_schema_version"], "uc042-investigation-findings/1.4")
            f = stored["confirmed_findings"][0]
            self.assertTrue(all(isinstance(f[k], str) and f[k] for k in NEW_FINDING_FIELDS))
            self.assertTrue(stored["hypotheses"][0]["rationale"])
            self.assertEqual(verify_published(d), [])
            self.assertEqual(InvestigationResult.model_validate(stored).confirmed_findings[0].title, f["title"])
        finally:
            shutil.rmtree(tmp)

    def test_strict_schema_requires_the_new_fields_from_the_model(self):
        defs = to_strict_json_schema(LLMInvestigationOutput)["$defs"]
        finding, hyp = defs["ConfirmedFinding"], defs["Hypothesis"]
        for k in NEW_FINDING_FIELDS:
            self.assertIn(k, finding["required"])
            self.assertEqual(finding["properties"][k]["type"], "string")  # never null in model output
        self.assertIn("rationale", hyp["required"])
        self.assertEqual(defs["ContradictoryItem"]["properties"]["compared_evidence"]["minItems"], 2)  # 1.3 rule kept

    def test_new_field_rules(self):
        case = build_case(load_pack(PACK["SC5A"]), "EXC-SC5A-01")
        packet = packet_for("SC5A", "EXC-SC5A-01")

        def errors(edit):
            return validate_output(investigation_output("SC5A", "EXC-SC5A-01", edit), packet, case)[0]
        self.assertEqual(errors(None), [])
        cases = [(lambda o: o["confirmed_findings"][0].update(title="Difference caused by a missing transaction"), "title states a cause"),
                 (lambda o: o["confirmed_findings"][0].update(establishes="It establishes the balance was due to a refund."), "establishes states a cause"),
                 (lambda o: o["confirmed_findings"][0].update(audit_relevance="It shows the exception has been resolved by the refund."), "resolved"),
                 (lambda o: o["confirmed_findings"][0].update(does_not_establish="The transaction never existed in any system."), "does not exist"),
                 (lambda o: o["confirmed_findings"][0].update(title="          "), "blank"),
                 (lambda o: o["hypotheses"][0].update(rationale="This discrepancy was closed by the analyst earlier."), "resolved")]
        for edit, expect in cases:
            with self.subTest(expect=expect):
                self.assertTrue(any(expect in e for e in errors(edit)), errors(edit))
        # what the evidence does not establish may legitimately mention the cause
        self.assertEqual(errors(lambda o: o["confirmed_findings"][0].update(
            does_not_establish="The cause of the difference is not established by these records.")), [])

    def test_prompts_and_versions(self):
        self.assertEqual((config.PROMPT_VERSION, config.TOOLS_PROMPT_VERSION, config.FINDINGS_SCHEMA_VERSION),
                         ("uc042-investigator-prompt/1.2", "uc042-investigator-prompt/2.2-tools", "uc042-investigation-findings/1.4"))
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            for word in ("audit_relevance", "does_not_establish", "rationale", "title"):
                self.assertIn(word, prompt)


if __name__ == "__main__":
    unittest.main()
