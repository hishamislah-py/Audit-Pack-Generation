"""Session 1 citation fix (23 Nov 2026): supporting_records normalisation.

Fixture: the REAL live output refused in the official Fix8 E2E (22 Nov 2026, gpt-6-luna, Kestrel RF-2026-09-001,
EXC-CASE-01, tools mode) with its evidence ledger, copied unchanged from the run's _not_published folder. F-02 cited two
engine control results correctly in evidence_ids but also copied them into supporting_records, so the whole
investigation was refused ("supporting_records must be source record IDs from the packet").
"""
import copy
import json
import unittest
from pathlib import Path

from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.validation import normalise_supporting_records, validate_output

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kestrel_exc01_live_refused_20261122.json"
RESULTS = ["C04-REQUIREMENT|2026-09-30/GBP", "C06-DIFFERENCE|2026-09-30/GBP"]


def load():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fields = set(LLMInvestigationOutput.model_fields)
    out = LLMInvestigationOutput.model_validate({k: v for k, v in d["result"].items() if k in fields})
    led = d["evidence_ledger"]
    return out, led, {"pack_id": led["pack_id"], "pack_content_sha256": led["pack_content_sha256"]}


def with_f02(out, **upd):
    fs = [f.model_copy(update=upd) if f.finding_id == "F-02" else f for f in out.confirmed_findings]
    return out.model_copy(update={"confirmed_findings": fs})


class LiveRefusalReplay(unittest.TestCase):
    def test_the_old_rule_reproduces_the_live_refusal(self):
        out, ledger, case = load()
        errors = validate_output(out, ledger, case)[0]
        self.assertIn("F-02: supporting_records must be source record IDs from the packet", errors)

    def test_normalised_output_validates_and_the_change_is_recorded(self):
        out, ledger, case = load()
        before = {f.finding_id: (list(f.evidence_ids), list(f.supporting_records)) for f in out.confirmed_findings}
        norm, notes = normalise_supporting_records(out, ledger)
        errors, vnotes, _ = validate_output(norm, ledger, case)
        self.assertEqual(errors, [])
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("F-02: supporting_records normalised"))
        for r in RESULTS:
            self.assertIn(r, notes[0])
        after = {f.finding_id: (list(f.evidence_ids), list(f.supporting_records)) for f in norm.confirmed_findings}
        self.assertEqual(after["F-02"], (before["F-02"][0], ["IN-05:IRR-EMONEY-GBP-20260930"]))   # evidence_ids untouched
        self.assertEqual({k: v for k, v in after.items() if k != "F-02"}, {k: v for k, v in before.items() if k != "F-02"})
        self.assertEqual(norm.investigation_summary, out.investigation_summary)

    def test_nothing_to_normalise_returns_the_same_object(self):
        out, ledger, _ = load()
        clean = with_f02(out, supporting_records=["IN-05:IRR-EMONEY-GBP-20260930"])
        self.assertIs(normalise_supporting_records(clean, ledger)[0], clean)


class StillRejected(unittest.TestCase):
    """The normalisation never widens what counts as support."""

    def refuse(self, **upd):
        out, ledger, case = load()
        bad = with_f02(out, **upd)
        norm, _ = normalise_supporting_records(bad, ledger)
        return validate_output(norm, ledger, case)[0]

    def test_an_id_not_in_the_packet_is_rejected(self):
        e = self.refuse(supporting_records=["IN-05:IRR-EMONEY-GBP-20260930", "IN-11:TX-DOES-NOT-EXIST"])
        self.assertTrue(any("not present in the evidence packet" in x for x in e), e)

    def test_a_result_not_cited_in_evidence_ids_stays_and_is_rejected(self):
        e = self.refuse(evidence_ids=["IN-05:IRR-EMONEY-GBP-20260930"],
                        supporting_records=["IN-05:IRR-EMONEY-GBP-20260930", RESULTS[0]])
        self.assertIn("F-02: supporting_records must be source record IDs from the packet", e)

    def test_exception_and_group_ids_are_not_moved_and_are_rejected(self):
        out, ledger, _ = load()
        ctx = ledger["exception"]["exception_id"]
        e = self.refuse(evidence_ids=list(out.confirmed_findings[1].evidence_ids) + [ctx],
                        supporting_records=["IN-05:IRR-EMONEY-GBP-20260930", ctx])
        self.assertIn("F-02: supporting_records must be source record IDs from the packet", e)

    def test_a_finding_supported_only_by_context_is_still_refused(self):
        out, ledger, _ = load()
        ctx = ledger["exception"]["exception_id"]
        e = self.refuse(evidence_ids=[ctx], supporting_records=[])
        self.assertTrue(any("F-02: confirmed finding cites no source record, control result or search" in x for x in e), e)


if __name__ == "__main__":
    unittest.main()
