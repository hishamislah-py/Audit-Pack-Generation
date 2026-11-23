"""Findings schema 1.5 / prompts 1.8 / 2.8-tools (20 Nov 2026): citation rules for missing-evidence findings.

The first live investigation on the Ringfence server (M3 / Fenmore, EXC-CASE-01 MISSING_BANK_EVIDENCE) was refused:
F-01 cited only the exception ID and the completeness item MISS-01, which the model view advertised as
"confirmed_finding_ids" although the validation never accepted them as support. The fixture is that run's stored
evidence ledger and model output, copied read-only (tests/fixtures/m3_exc01_live_refused.json).

Rules under test (validation.py, packet_view.py, prompts.py):
- every citable ID has a deterministic class: support (source records, control results, searches), completeness
  (MISS- items), context only (exception, related exception, group and conflict IDs), hypotheses only (CAND-);
- a completeness item supports only an EVIDENCE_ABSENCE finding, and only when it belongs to the investigated exception
  and every related result is an INSUFFICIENT_EVIDENCE control result of that exception present in the evidence;
- an exception reference never supports a finding; supporting_records stays source-records-only;
- a declared evidence_basis must match what is cited; an absence claim needs absence evidence;
- findings without evidence_basis (schema <= 1.4) keep the earlier rules; publication stays all-or-nothing."""
import copy
import json
import unittest
from pathlib import Path

from openai.lib._pydantic import to_strict_json_schema

from tests.final_pack_support import PACK, investigation_output, packet_for
from uc042lib.investigation import config
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case
from uc042lib.investigation.packet_view import citation_class_ids, reconstruct_packet, render_model_view
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT, citation_classes
from uc042lib.investigation.retrieval import load_pack
from uc042lib.investigation.validation import evidence_classes, validate_output

FX = json.loads((Path(__file__).parent / "fixtures" / "m3_exc01_live_refused.json").read_text(encoding="utf-8"))
LEDGER, CASE = FX["ledger"], FX["case"]
CTRL = "C07-BANK-EVIDENCE|2026-09-15/SGA-EUR-01"       # INSUFFICIENT_EVIDENCE result of EXC-CASE-01
REC = "IN-06:ERL-SGA-EUR-01-20260915"                  # the firm's external reconciliation record for the day
UNRELATED_REC = "IN-10:LE-EUR-0915-0001"               # a real cash-book record: exists, shows nothing about absence
NOT_FOUND, FOUND = "SEARCH-01", "SEARCH-04"            # 17:00 confirmation NOT_FOUND / external recon record FOUND
ABSENT_CLAIM = "No 2026-09-15 bank confirmation or end-of-day statement for SGA-EUR-01 is in the supplied data."


def output(edit=None):
    o = copy.deepcopy(FX["output"])
    if edit:
        edit(o)
    return LLMInvestigationOutput.model_validate(o)


def f01(**changes):
    def edit(o):
        next(f for f in o["confirmed_findings"] if f["finding_id"] == "F-01").update(**changes)
    return edit


def errors(edit=None, packet=LEDGER):
    return validate_output(output(edit), packet, CASE)[0]


def f01_errors(edit=None, packet=LEDGER):
    return [e for e in errors(edit, packet) if e.startswith("F-01")]


def ledger_with(mutate):
    led = copy.deepcopy(LEDGER)
    mutate(led)
    return led


class LiveM3Fixture(unittest.TestCase):
    def test_fixture_is_the_refused_live_run(self):
        self.assertEqual(FX["validation_status"], "REJECTED")
        self.assertEqual(FX["model"]["model"], "gpt-6-luna")
        self.assertEqual(LEDGER["exception"]["exception_id"], "EXC-CASE-01")
        self.assertEqual([m["item_id"] for m in LEDGER["missing_evidence"]], ["MISS-01"])

    def test_the_original_output_is_still_refused(self):
        """History is not rewritten: the stored F-01 (exception + MISS-01, exception in supporting_records) stays refused."""
        errs = errors()
        self.assertTrue(errs)
        self.assertTrue(any(e.startswith("F-01: confirmed finding cites no source record, control result or search") for e in errs))
        self.assertIn("F-01: supporting_records must be source record IDs from the packet", errs)
        self.assertTrue(any("EXC-CASE-01 is an exception reference" in e for e in errs), errs)
        self.assertEqual([e for e in errs if not e.startswith("F-01")], [])  # F-02..F-04 (no evidence_basis) still pass

    def test_evidence_classes_are_deterministic_and_never_widen_the_packet(self):
        cls = evidence_classes(LEDGER)
        self.assertEqual(cls["context"], {"EXC-CASE-01"})
        self.assertEqual(cls["completeness"], {"MISS-01"})
        self.assertEqual(cls["traceable_completeness"], {"MISS-01"})
        self.assertEqual(len(cls["absence_results"]), 13)
        self.assertEqual(cls["not_found_searches"], {"SEARCH-01", "SEARCH-02", "SEARCH-03", "SEARCH-05", "SEARCH-06"})
        cc = citation_class_ids(LEDGER)
        self.assertNotIn("EXC-CASE-01", cc["support_ids"])
        self.assertNotIn("MISS-01", cc["support_ids"])
        self.assertEqual(cc["completeness_ids"], ["MISS-01"])
        self.assertEqual(cc["context_only_ids"], ["EXC-CASE-01"])
        self.assertEqual(sorted(sum(cc.values(), [])), sorted(LEDGER["allowed_citation_ids"]))


class RequiredCases(unittest.TestCase):
    """The eleven cases of the implementation brief, on the live M3 evidence."""

    def test_01_missing_evidence_finding_citing_a_valid_completeness_result_passes(self):
        self.assertEqual(errors(f01(evidence_ids=["MISS-01"], supporting_records=[], evidence_basis="EVIDENCE_ABSENCE")), [])
        self.assertEqual(errors(f01(evidence_ids=["MISS-01", CTRL, "EXC-CASE-01"], supporting_records=[],
                                    evidence_basis="EVIDENCE_ABSENCE")), [])  # the exception may accompany real evidence

    def test_02_finding_citing_an_actual_source_record_passes(self):
        self.assertEqual(errors(f01(claim="The firm's external reconciliation record reports 98,500.35 for SGA-EUR-01.",
                                    evidence_ids=[REC], supporting_records=[REC], evidence_basis="SOURCE_EVIDENCE")), [])

    def test_03_finding_citing_a_relevant_control_result_passes(self):
        self.assertEqual(errors(f01(evidence_ids=[CTRL], supporting_records=[], evidence_basis="CONTROL_RESULT")), [])

    def test_04_finding_citing_a_relevant_search_result_passes(self):
        self.assertEqual(errors(f01(claim=ABSENT_CLAIM, evidence_ids=[NOT_FOUND, "SEARCH-02"], supporting_records=[],
                                    evidence_basis="EVIDENCE_ABSENCE")), [])

    def test_05_finding_citing_only_an_exception_id_fails(self):
        for basis in ("EVIDENCE_ABSENCE", "CONTROL_RESULT", "SOURCE_EVIDENCE", None):
            with self.subTest(basis=basis):
                errs = f01_errors(f01(evidence_ids=["EXC-CASE-01"], supporting_records=[], evidence_basis=basis))
                self.assertTrue(any("cites no source record, control result or search" in e for e in errs), errs)
                self.assertTrue(any("EXC-CASE-01 is an exception reference (context only" in e for e in errs), errs)

    def test_06_finding_citing_a_nonexistent_evidence_id_fails(self):
        errs = errors(f01(evidence_ids=["IN-07:ST-SGA-EUR-01-20260915-1700"], supporting_records=[],
                          evidence_basis="EVIDENCE_ABSENCE"))
        self.assertTrue(any("cites IDs not present in the evidence packet" in e for e in errs), errs)

    def test_07_finding_citing_unrelated_but_existing_evidence_fails(self):
        # an absence finding supported only by a real, unrelated record
        errs = f01_errors(f01(claim=ABSENT_CLAIM, evidence_ids=[UNRELATED_REC], supporting_records=[UNRELATED_REC],
                              evidence_basis="EVIDENCE_ABSENCE"))
        self.assertTrue(any("classified EVIDENCE_ABSENCE but cites no absence evidence" in e for e in errs), errs)
        # the same claim without evidence_basis (schema <= 1.4 content): the absence-claim rule refuses it
        errs = f01_errors(f01(claim=ABSENT_CLAIM, evidence_ids=[UNRELATED_REC], supporting_records=[UNRELATED_REC],
                              evidence_basis=None))
        self.assertTrue(any("states that evidence is absent or could not be assessed" in e for e in errs), errs)

    def test_08_finding_citing_evidence_that_does_not_support_its_claim_fails(self):
        cases = [
            (f01(claim=ABSENT_CLAIM, evidence_ids=[FOUND], supporting_records=[], evidence_basis="EVIDENCE_ABSENCE"),
             "classified EVIDENCE_ABSENCE but cites no absence evidence"),           # a FOUND search does not show absence
            (f01(evidence_ids=[REC], supporting_records=[REC], evidence_basis="CONTROL_RESULT"),
             "classified CONTROL_RESULT but cites no control result"),
            (f01(evidence_ids=[CTRL], supporting_records=[], evidence_basis="SOURCE_EVIDENCE"),
             "classified SOURCE_EVIDENCE but cites no source record"),
            (f01(evidence_ids=["MISS-01"], supporting_records=[], evidence_basis="CONTROL_RESULT"),
             "MISS-01 is a completeness result: it supports only an EVIDENCE_ABSENCE finding"),
        ]
        for edit, expect in cases:
            with self.subTest(expect=expect):
                self.assertTrue(any(expect in e for e in f01_errors(edit)), f01_errors(edit))

    def test_09_mixed_valid_and_invalid_citations_reject_the_whole_output(self):
        # one finding mixing a valid completeness item and a nonexistent ID
        self.assertTrue(errors(f01(evidence_ids=["MISS-01", "IN-07:DOES-NOT-EXIST"], supporting_records=[],
                                   evidence_basis="EVIDENCE_ABSENCE")))
        # valid evidence_ids but an exception ID in supporting_records
        self.assertIn("F-01: supporting_records must be source record IDs from the packet",
                      errors(f01(evidence_ids=["MISS-01"], supporting_records=["EXC-CASE-01"], evidence_basis="EVIDENCE_ABSENCE")))
        # one invalid finding among valid ones: any error rejects the output (graph.validate_findings: REJECTED), so the
        # valid findings are never published on their own
        errs = errors(f01(evidence_ids=["EXC-CASE-01"], supporting_records=[], evidence_basis="EVIDENCE_ABSENCE"))
        self.assertTrue(errs)
        self.assertEqual({e.split(":")[0] for e in errs}, {"F-01"})

    def test_10_completeness_result_without_supporting_controls_fails(self):
        def sole(led):
            return f01_errors(f01(evidence_ids=["MISS-01"], supporting_records=[], evidence_basis="EVIDENCE_ABSENCE"), led)
        mutations = {
            "no related results": lambda led: led["missing_evidence"][0].update(related_result_ids=[]),
            "related result not in the evidence": lambda led: led["missing_evidence"][0].update(
                related_result_ids=["C07-BANK-EVIDENCE|2026-09-16/SGA-EUR-01"]),
            "related result not INSUFFICIENT_EVIDENCE": lambda led: next(
                r for r in led["control_results"] if r["result_id"] == CTRL).update(outcome="PASS"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label):
                errs = sole(ledger_with(mutate))
                self.assertTrue(any("not traceable to INSUFFICIENT_EVIDENCE control results of EXC-CASE-01" in e for e in errs), errs)

    def test_11_wrong_cases_completeness_result_fails(self):
        # a completeness item of another exception, present in the evidence
        led = ledger_with(lambda d: d["missing_evidence"][0].update(related_exception_id="EXC-CASE-02"))
        errs = f01_errors(f01(evidence_ids=["MISS-01"], supporting_records=[], evidence_basis="EVIDENCE_ABSENCE"), led)
        self.assertTrue(any("not traceable" in e for e in errs), errs)
        # a completeness item that is not in this investigation's evidence at all
        errs = errors(f01(evidence_ids=["MISS-07"], supporting_records=[], evidence_basis="EVIDENCE_ABSENCE"))
        self.assertTrue(any("cites IDs not present in the evidence packet" in e for e in errs), errs)


class OrdinaryFindingsAreNotWeakened(unittest.TestCase):
    """Findings that do not concern missing evidence (SC5A, a FAIL scenario with a candidate relationship)."""

    def setUp(self):
        self.case = build_case(load_pack(PACK["SC5A"]), "EXC-SC5A-01")
        self.packet = packet_for("SC5A", "EXC-SC5A-01")

    def errs(self, edit=None):
        return validate_output(investigation_output("SC5A", "EXC-SC5A-01", edit), self.packet, self.case)[0]

    def test_existing_valid_output_still_passes(self):
        self.assertEqual(self.errs(), [])

    def test_declared_basis_must_match_the_citations(self):
        cls = evidence_classes(self.packet)
        out = investigation_output("SC5A", "EXC-SC5A-01")
        f = out.confirmed_findings[0]
        records, results = sorted(set(f.evidence_ids) & cls["records"]), sorted(set(f.evidence_ids) & cls["results"])
        if records:
            self.assertEqual(self.errs(lambda o: o["confirmed_findings"][0].update(evidence_basis="SOURCE_EVIDENCE")), [])
        if results:
            self.assertEqual(self.errs(lambda o: o["confirmed_findings"][0].update(evidence_basis="CONTROL_RESULT")), [])
        # a FAIL result is not absence evidence
        fail = sorted(i for i in cls["results"] if i not in cls["absence_results"])
        self.assertTrue(fail)
        e = self.errs(lambda o: o["confirmed_findings"][0].update(evidence_ids=[fail[0]], supporting_records=[],
                                                                   evidence_basis="EVIDENCE_ABSENCE"))
        self.assertTrue(any("classified EVIDENCE_ABSENCE but cites no absence evidence" in x for x in e), e)

    def test_candidate_and_exception_rules_unchanged(self):
        e = self.errs(lambda o: o["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01"))
        self.assertTrue(any("unverified candidate relationship" in x for x in e), e)
        e = self.errs(lambda o: o["confirmed_findings"][0].update(evidence_ids=["EXC-SC5A-01"], supporting_records=[]))
        self.assertTrue(any("cites no source record, control result or search" in x for x in e), e)


class SchemaPromptAndView(unittest.TestCase):
    def test_versions(self):
        self.assertEqual((config.PROMPT_VERSION, config.TOOLS_PROMPT_VERSION, config.FINDINGS_SCHEMA_VERSION),
                         ("uc042-investigator-prompt/1.11", "uc042-investigator-prompt/2.11-tools", "uc042-investigation-findings/1.5"))

    def test_strict_schema_requires_evidence_basis_from_the_model(self):
        finding = to_strict_json_schema(LLMInvestigationOutput)["$defs"]["ConfirmedFinding"]
        self.assertIn("evidence_basis", finding["required"])
        self.assertEqual(finding["properties"]["evidence_basis"]["enum"], ["SOURCE_EVIDENCE", "CONTROL_RESULT", "EVIDENCE_ABSENCE"])

    def test_findings_without_evidence_basis_load_and_serialise_unchanged(self):
        """Artefacts written under findings schema <= 1.4 have no evidence_basis: they load with None and dump without the
        key, so their bytes and investigation IDs are unchanged; a supplied value round-trips."""
        legacy = FX["output"]
        out = LLMInvestigationOutput.model_validate(legacy)
        self.assertTrue(all(f.evidence_basis is None for f in out.confirmed_findings))
        self.assertTrue(all("evidence_basis" not in f for f in out.model_dump()["confirmed_findings"]))
        self.assertEqual(out.model_dump()["confirmed_findings"], legacy["confirmed_findings"])
        o = output(f01(evidence_basis="EVIDENCE_ABSENCE"))
        self.assertEqual(o.model_dump()["confirmed_findings"][0]["evidence_basis"], "EVIDENCE_ABSENCE")
        self.assertEqual(LLMInvestigationOutput.model_validate(o.model_dump()), o)

    def test_prompts_describe_the_evidence_types_and_classes(self):
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            for text in ("evidence_basis", "SOURCE_EVIDENCE", "CONTROL_RESULT", "EVIDENCE_ABSENCE", "context_only_ids",
                         "completeness_ids", "support_ids", "an exception reference alone never supports a finding",
                         "Not retrieved", "Never invent an ID"):
                self.assertIn(text, prompt)
            self.assertNotIn("confirmed_finding_ids", prompt)
        cc = citation_classes(LEDGER)
        self.assertEqual(cc["context_only_ids"], ["EXC-CASE-01"])
        self.assertEqual(cc["completeness_ids"], ["MISS-01"])

    def test_model_view_carries_the_classes_and_still_reconstructs_the_packet_exactly(self):
        for scenario, exc in (("SC5A", "EXC-SC5A-01"), ("S02", "EXC-S02-01")):
            with self.subTest(scenario):
                p = packet_for(scenario, exc)
                v = render_model_view(p)
                self.assertEqual(set(v["citation_classes"]), {"support_ids", "completeness_ids", "context_only_ids", "hypotheses_only_ids"})
                self.assertIn(exc, v["citation_classes"]["context_only_ids"])
                self.assertEqual(reconstruct_packet(json.loads(json.dumps(v)))["allowed_citation_ids"], p["allowed_citation_ids"])


if __name__ == "__main__":
    unittest.main()
