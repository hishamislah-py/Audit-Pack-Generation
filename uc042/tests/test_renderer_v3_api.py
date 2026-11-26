"""Renderer 3.0 / schema 1.3 through the API (offline, mocked provider): a clean pack's preview makes no AI request and needs
no AI authorisation, GENERATE needs no "summary unavailable" acknowledgement and the final pack verifies; an exception pack
still requires the authorisation, and a refused or failed closing summary is disclosed neutrally with its details kept for
the technical appendix. Run from uc042/: python -m unittest tests.test_renderer_v3_api -v
(UC042_TEST_REPOSITORIES=sqlite for the SQL repositories)."""
import json
import unittest
import unittest.mock

from tests.api_support import AI_OK, ApiCase
from tests.final_pack_support import PACK, raw
from tests.renderer_v3_support import norm, pdf_text
from uc042lib.final_pack import summary as summary_module, verify_final_pack
from uc042lib.final_pack.model import ClosingSummaryOutput, CURRENT_RENDERER_VERSION, OUTCOME_FINAL_PACK_SCHEMA_VERSION
from uc042lib.investigation.llm import LLMCallError

S01, SC5A = PACK["S01"], PACK["SC5A"]


class V3Case(ApiCase):
    def open(self, pack):
        r = self.post(f"/api/v1/packs/{pack}/reviews")
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()

    def request_preview(self, review_id, body):
        r = self.post(f"/api/v1/reviews/{review_id}/preview", body)
        if r.status_code != 202:
            return r, None
        job = self.wait_job(r.json()["job_id"])
        self.assertEqual(job["status"], "COMPLETED", job)
        return r, self.get(f"/api/v1/reviews/{review_id}").json()

    def generate(self, session, **overrides):
        body = {"decision": "GENERATE", "snapshot_sha256": session["current_preview"]["snapshot_sha256"],
                "acknowledgement_accepted": True, "comment": "Reviewed the preview."}
        body.update(overrides)
        return self.post(f"/api/v1/reviews/{session['review_id']}/decision", body)

    def authorisations(self):
        return [a for a in self.svc.ai_authorizations.list() if a.get("operation") == "CLOSING_SUMMARY"]


class CleanPack(V3Case):
    def test_clean_preview_needs_no_authorisation_and_makes_no_ai_request(self):
        s = self.open(S01)
        self.assertIs(s["readiness"]["checklist"]["closing_summary_required"], False)
        self.assertIn("no AI closing summary is needed", next(b["detail"] for b in s["readiness"]["blockers"] if b["code"] == "PREVIEW_REQUIRED"))
        r, s = self.request_preview(s["review_id"], {})  # no authorisation in the request
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(self.provider.calls["summary"], 0)  # no AI request was made
        self.assertEqual(self.authorisations(), [])  # nothing to authorise, nothing recorded
        cs = s["current_preview"]["closing_summary"]
        self.assertEqual((cs["status"], cs["failure"], cs["model"]), ("NOT_REQUIRED", None, None))
        self.assertNotIn("CLOSING_SUMMARY_UNAVAILABLE", [w["code"] for w in s["readiness"]["warnings"]])
        doc = self.get(f"/api/v1/reviews/{s['review_id']}/preview/json").json()
        self.assertEqual((doc["final_pack_schema_version"], doc["metadata"]["report_renderer"]),
                         (OUTCOME_FINAL_PACK_SCHEMA_VERSION, CURRENT_RENDERER_VERSION))
        pdf = pdf_text(self.get(f"/api/v1/reviews/{s['review_id']}/preview/pdf").content)
        self.assertIn(norm("No decision to generate the final audit pack has been recorded"), norm(pdf))
        self.assertNotIn("invalid_summary", pdf)
        # GENERATE: no "summary unavailable" acknowledgement is needed
        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]
        final = self.get(f"/api/v1/final-packs/{fp['final_pack_id']}/json").json()
        self.assertEqual((final["closing_summary"]["status"], final["human_review"]["closing_summary_status"],
                          final["human_review"]["acknowledged_summary_unavailable"]), ("NOT_REQUIRED", "NOT_REQUIRED", False))
        d = self.settings.final_packs_root / fp["final_pack_id"]
        self.assertEqual(verify_final_pack(d), [])
        self.assertEqual(json.loads((d / "manifest.json").read_text(encoding="utf-8"))["renderer_version"], CURRENT_RENDERER_VERSION)
        text = pdf_text((d / "report.pdf").read_bytes())
        self.assertIn(norm("GENERATE - authorised assembly of this report"), norm(text))
        self.assertEqual(self.provider.calls["summary"], 0)

    def test_an_authorisation_sent_anyway_is_not_needed_and_not_recorded(self):
        s = self.open(S01)
        r, s = self.request_preview(s["review_id"], {"authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual((self.provider.calls["summary"], self.authorisations()), (0, []))
        self.assertEqual(s["current_preview"]["closing_summary"]["status"], "NOT_REQUIRED")


class ExceptionPack(V3Case):
    """The AI closing-summary path, kept testable although the summary is off by the 23 Nov 2026 owner decision."""
    def setUp(self):
        super().setUp()
        p = unittest.mock.patch.object(summary_module, "AI_CLOSING_SUMMARY_ENABLED", True)
        p.start()
        self.addCleanup(p.stop)
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        self.assertEqual(job["status"], "COMPLETED", job)
        self.accept_investigation(job["result"]["investigation_id"], comment="Agrees with the records.")

    def test_exception_pack_still_requires_the_authorisation(self):
        s = self.open(SC5A)
        self.assertIs(s["readiness"]["checklist"]["closing_summary_required"], True)
        r, _ = self.request_preview(s["review_id"], {})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "AUTHORIZATION_REQUIRED"))
        r, s = self.request_preview(s["review_id"], {"authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual((self.provider.calls["summary"], s["current_preview"]["closing_summary"]["status"]), (1, "GENERATED"))
        self.assertEqual(len(self.authorisations()), 1)

    def test_refused_summary_output_is_disclosed_neutrally_with_details_in_the_appendix(self):
        bad = ClosingSummaryOutput.model_validate({
            "overall_position": "The deterministic engine reports exceptions that remain unresolved for review.",
            "summary_text": "The supplied records are summarised here for the reviewer; every exception remains unresolved.",
            "key_observations": [], "unresolved_items": [{"exception_id": "EXC-SC5A-01", "text": "Remains unresolved."},
                                                         {"exception_id": "EXC-SC5A-02", "text": "Remains unresolved."}],
            "unverified_hypotheses": [], "evidence_gaps": [],
            "suggested_next_steps": [{"text": "Obtain the bank advice for the item.", "source_refs": [""]}], "limitations": []})
        respond = self.provider.respond
        self.provider.respond = lambda kw: raw(bad) if kw.get("text_format") is ClosingSummaryOutput else respond(kw)
        s = self.open(SC5A)
        _, s = self.request_preview(s["review_id"], {"authorization": AI_OK})
        cs = s["current_preview"]["closing_summary"]
        self.assertEqual((cs["status"], cs["failure"]["kind"]), ("UNAVAILABLE", "invalid_summary"))
        r = self.generate(s)
        self.assertEqual((r.status_code, r.json()["code"]), (422, "SUMMARY_UNAVAILABLE_ACK_REQUIRED"))
        r = self.generate(s, acknowledged_summary_unavailable=True)
        self.assertEqual(r.status_code, 201, r.text)
        fid = r.json()["final_pack"]["final_pack_id"]
        final = self.get(f"/api/v1/final-packs/{fid}/json").json()
        self.assertEqual(final["closing_summary"]["unavailable_reason"], "closing summary generation failed (invalid_summary)")
        self.assertTrue(any("an empty reference is not evidence" in v for v in final["closing_summary"]["validation_findings"]))
        text = pdf_text((self.settings.final_packs_root / fid / "report.pdf").read_bytes())
        main, appendix = text.rsplit("Technical appendix", 1)[0], text.split("A.6 Closing-summary record")[-1]  # last = the heading
        self.assertNotIn("invalid_summary", main.split("Contents")[-1])  # not in the main body
        self.assertIn(norm("An AI closing summary was attempted but is not included"), norm(main))
        self.assertIn("invalid_summary", appendix)
        self.assertEqual(verify_final_pack(self.settings.final_packs_root / fid), [])

    def test_provider_failure_is_unavailable_and_needs_acknowledgement(self):
        self.provider.summary_error = LLMCallError("the request timed out", "timeout")
        s = self.open(SC5A)
        _, s = self.request_preview(s["review_id"], {"authorization": AI_OK})
        self.assertEqual(s["current_preview"]["closing_summary"]["status"], "UNAVAILABLE")
        self.assertEqual(self.generate(s).json()["code"], "SUMMARY_UNAVAILABLE_ACK_REQUIRED")


if __name__ == "__main__":
    unittest.main()
