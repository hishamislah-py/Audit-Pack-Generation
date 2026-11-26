"""CF-1 (20 Nov 2026, found by independent verification): the final-pack validator (FV7/FV8) must apply the same
support rule as the investigation validator (findings schema 1.5). Before the correction, an EVIDENCE_ABSENCE finding that
cites only the engine's traceable completeness result (MISS-01) was published and could be accepted, but the closing
preview / final pack was then refused ("confirmed observation has no supporting source record, control result or
search"), so the case could not be closed.

Scenario S02 (missing EUR bank evidence, 15 Sep): the same pattern as the Ringfence M3 / Fenmore case. Offline: the
investigations are published through the real graph with a mocked OpenAI client (tests.final_pack_support)."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.final_pack_support import PACK, investigation_output, make_investigation, resealed, review_for, summary_investigator
from uc042lib.final_pack import (FinalPackValidationError, GenerationInfo, assemble_final_pack, assemble_preview,
                                 build_review_snapshot, generate_closing_summary, render_pdf)
from uc042lib.final_pack import validate as fv
import io

from pypdf import PdfReader
from uc042lib.final_pack.sources import default_selections, load_pack
from uc042lib.final_pack.validate import validate_final_pack

ABSENCE_F = {"finding_id": "F-09", "evidence_basis": "EVIDENCE_ABSENCE", "evidence_ids": ["MISS-01"], "supporting_records": [],
             "claim": "The engine's completeness register lists the EUR bank evidence for 15 Sep as not available.",
             "explanation": "The completeness result records the expected bank evidence as not available in the supplied data.",
             "title": "EUR bank evidence for 15 Sep not available",
             "audit_relevance": "The missing evidence prevents the affected checks from being assessed.",
             "establishes": "The engine records this bank evidence as not available in the supplied data.",
             "does_not_establish": "Whether the evidence exists outside the supplied data is not established."}
NO_SUPPORT = "confirmed observation has no supporting source record, control result or search"


def with_finding(finding):
    def edit(o):
        o["confirmed_findings"].append(copy.deepcopy(finding))
    return edit


class FinalPackEvidenceBasis(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inv_root = self.tmp / "investigations"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def closing(self, scenario, exception_id, edit=None):
        """Publish an investigation, include it, generate the closing summary and assemble preview + final pack."""
        iid = make_investigation(scenario, exception_id, self.inv_root, edit)
        pack = load_pack(PACK[scenario])
        snap = build_review_snapshot(PACK[scenario], default_selections(pack, self.inv_root), investigations_root=self.inv_root)
        inv, _ = summary_investigator(snap)
        summary = generate_closing_summary(snap, inv)
        preview = assemble_preview(snap, summary)
        final = assemble_final_pack(snap, summary, review_for(snap, summary), GenerationInfo())
        return iid, snap, summary, preview, final

    def finding(self, final, finding_id):
        return next(f for inv in final["ai_investigations"] for f in inv["confirmed_findings"] if f["finding_id"] == finding_id)

    # -- the CF-1 case --------------------------------------------------------------------------------------------
    def test_absence_finding_citing_only_miss01_passes_preview_and_final_pack(self):
        iid, snap, summary, preview, final = self.closing("S02", "EXC-S02-01", with_finding(ABSENCE_F))
        self.assertEqual(self.finding(final, "F-09")["evidence_refs"], ["MISS-01"])
        self.assertEqual(validate_final_pack(final, snap, summary, review_for(snap, summary)), [])
        text = " ".join(" ".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(render_pdf(final))).pages).split())
        self.assertIn("EUR bank evidence for 15 Sep not available", text)
        self.assertIn("MISS-01", text)
        self.assertIn("[UNRESOLVED]", text)

    # -- the rule is the investigation validator's, not a whitelist -------------------------------------------------
    def assert_refused(self, snap, summary, final, mutate_evidence):
        """Re-validate the same final pack against altered evidence (as if MISS-01 had different relationships)."""
        real = fv.evidence_of

        def altered(bundle):
            e = copy.deepcopy(real(bundle))
            mutate_evidence(e)
            return e
        with mock.patch.object(fv, "evidence_of", altered):
            errs = validate_final_pack(final, snap, summary, review_for(snap, summary))
        self.assertTrue(any("#F-09" in e and NO_SUPPORT in e for e in errs), errs)

    def test_completeness_result_of_another_exception_is_refused(self):
        _, snap, summary, _, final = self.closing("S02", "EXC-S02-01", with_finding(ABSENCE_F))
        self.assert_refused(snap, summary, final, lambda e: e["missing_evidence"][0].update(related_exception_id="EXC-S02-99"))

    def test_completeness_result_whose_checks_are_not_unassessable_is_refused(self):
        _, snap, summary, _, final = self.closing("S02", "EXC-S02-01", with_finding(ABSENCE_F))

        def assessed(e):
            rid = e["missing_evidence"][0]["related_result_ids"][0]
            next(r for r in e["control_results"] if r["result_id"] == rid)["outcome"] = "PASS"
        self.assert_refused(snap, summary, final, assessed)

    def test_completeness_result_whose_checks_are_not_in_the_evidence_is_refused(self):
        _, snap, summary, _, final = self.closing("S02", "EXC-S02-01", with_finding(ABSENCE_F))
        self.assert_refused(snap, summary, final, lambda e: e["missing_evidence"][0].update(
            related_result_ids=["C07-BANK-EVIDENCE|2026-09-16/SGA-EUR-01"]))

    def test_ordinary_finding_cannot_use_miss01(self):
        """A CONTROL_RESULT finding whose references are reduced to MISS-01 is refused by the final-pack check (the
        investigation validator already refuses to publish it: test_citation_evidence_basis case 8)."""
        cr = dict(ABSENCE_F, finding_id="F-09", evidence_basis="CONTROL_RESULT",
                  evidence_ids=["C07-BANK-EVIDENCE|2026-09-15/SGA-EUR-01"])
        _, snap, summary, _, final = self.closing("S02", "EXC-S02-01", with_finding(cr))

        def to_miss(f):
            next(x for inv in f["ai_investigations"] for x in inv["confirmed_findings"] if x["finding_id"] == "F-09")["evidence_refs"] = ["MISS-01"]
        errs = validate_final_pack(resealed(final, to_miss), snap, summary, review_for(snap, summary))
        self.assertTrue(any("#F-09" in e and NO_SUPPORT in e for e in errs), errs)

    def test_exception_reference_alone_is_refused(self):
        _, snap, summary, _, final = self.closing("S02", "EXC-S02-01", with_finding(ABSENCE_F))

        def to_exc(f):
            next(x for inv in f["ai_investigations"] for x in inv["confirmed_findings"] if x["finding_id"] == "F-09")["evidence_refs"] = ["EXC-S02-01"]
        errs = validate_final_pack(resealed(final, to_exc), snap, summary, review_for(snap, summary))
        self.assertTrue(any("#F-09" in e and NO_SUPPORT in e for e in errs), errs)

    # -- ordinary findings unchanged --------------------------------------------------------------------------------
    def test_source_control_and_search_findings_still_pass(self):
        from tests.final_pack_support import packet_for
        from uc042lib.investigation.validation import evidence_classes
        cls = evidence_classes(packet_for("S02", "EXC-S02-01"))
        record, search = sorted(cls["records"])[0], sorted(cls["not_found_searches"])[0]

        def edit(o):
            o["confirmed_findings"][0]["evidence_basis"] = "CONTROL_RESULT"   # offline finding 1 cites a control result
            o["confirmed_findings"].append(dict(ABSENCE_F, finding_id="F-08", evidence_basis="SOURCE_EVIDENCE",
                                                claim="The supplied data contains the cited firm record for the day.",
                                                evidence_ids=[record], supporting_records=[record]))
            o["confirmed_findings"].append(dict(ABSENCE_F, finding_id="F-09", evidence_ids=[search]))
            o["evidence_references"] = sorted(set(o["evidence_references"]) | {record, search})
        _, snap, summary, _, final = self.closing("S02", "EXC-S02-01", edit)
        self.assertEqual(validate_final_pack(final, snap, summary, review_for(snap, summary)), [])
        self.assertEqual(self.finding(final, "F-08")["evidence_refs"], [record])
        self.assertEqual(self.finding(final, "F-09")["evidence_refs"], [search])
        # SC5A (FAIL exceptions, candidate relationship) with a declared basis
        _, snap, summary, _, final = self.closing("SC5A", "EXC-SC5A-01",
                                                  lambda o: o["confirmed_findings"][0].update(evidence_basis="CONTROL_RESULT"))
        self.assertEqual(validate_final_pack(final, snap, summary, review_for(snap, summary)), [])

    def test_unchanged_behaviour_without_evidence_basis(self):
        """Findings without evidence_basis (schema <= 1.4) keep the earlier final-pack rule."""
        _, snap, summary, _, final = self.closing("SC5A", "EXC-SC5A-01")
        self.assertEqual(validate_final_pack(final, snap, summary, review_for(snap, summary)), [])

    def test_final_pack_validator_shares_the_investigation_rule(self):
        import inspect
        src = inspect.getsource(fv._investigation_checks)
        self.assertIn('evidence_classes(evidence)["traceable_completeness"]', src)
        self.assertIn('s.evidence_basis == "EVIDENCE_ABSENCE"', src)


if __name__ == "__main__":
    unittest.main()
