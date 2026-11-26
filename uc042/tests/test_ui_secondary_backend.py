"""Secondary UI fixes, backend part (token-optimisation copy):
DEF-06  GET /packs/{id} returns the pack's unverified candidate relationships (read-only) for the pack page.
DEF-09  A failed attempt whose job already reported the failure appears ONCE in the review history (the unpublished
        record is merged into the job event instead of being listed a second time).
Offline (mocked provider). Run: python -m unittest tests.test_ui_secondary_backend -v"""
import unittest

from tests.api_support import ApiCase
from tests.final_pack_support import PACK

SC5A = PACK["SC5A"]


def cite_candidate(d):
    d["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")  # refused by validation (unchanged rule)


class PackCandidates(ApiCase):
    def test_pack_payload_lists_candidates_unverified(self):
        r = self.get(f"/api/v1/packs/{SC5A}")
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()["candidate_relationships"]
        self.assertEqual([x["candidate_id"] for x in c], ["CAND-SC5A-01"])
        self.assertEqual(c[0]["basis"], "DATE_AND_AMOUNT_COINCIDENCE")
        self.assertIn("UNVERIFIED", c[0]["label"])
        clean = self.get(f"/api/v1/packs/{PACK['S01']}").json()
        self.assertEqual(clean["candidate_relationships"], [])


class HistoryDeduplicated(ApiCase):
    def test_one_event_per_failed_attempt(self):
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01", edit=cite_candidate)
        self.assertEqual(job["status"], "FAILED", job)
        h = self.get(f"/api/v1/packs/{SC5A}/exceptions/EXC-SC5A-01/review-history").json()
        kinds = [e["kind"] for e in h["events"]]
        self.assertEqual(kinds.count("AI_INVESTIGATION_FAILED"), 1, kinds)
        self.assertNotIn("AI_INVESTIGATION_NOT_PUBLISHED", kinds)  # merged into the job event
        failed = next(e for e in h["events"] if e["kind"] == "AI_INVESTIGATION_FAILED")
        self.assertIn("unverified candidate relationship", failed["details"]["error"])
        self.assertEqual(failed["details"].get("validation_status"), "REJECTED")


if __name__ == "__main__":
    unittest.main()
