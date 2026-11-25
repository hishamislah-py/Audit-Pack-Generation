"""Investigation jobs through the API: successful V2 tools-mode job, failed job, duplicate submissions, polling, restart
recovery (INTERRUPTED, never re-run), explicit retry without overwriting, provider configuration, and proof that no live
provider is reachable. Offline. Run from uc042/: python -m unittest -v"""
import threading
import unittest

from tests.api_support import AI_OK, ApiCase, gate
from tests.final_pack_support import PACK, sha_tree
from uc042lib.investigation.llm import LLMConfigurationError, OfflineSimulatedInvestigator

URL = f"/api/v1/packs/{PACK['SC5A']}/exceptions/EXC-SC5A-01/investigations"


class Jobs(ApiCase):
    def test_successful_v2_job_and_polling(self):
        self.provider.investigate("SC5A", "EXC-SC5A-01")
        r = self.post(URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual(r.status_code, 202)
        job = r.json()
        self.assertIn(job["status"], ("QUEUED", "RUNNING", "COMPLETED"))
        done = self.wait_job(job["job_id"])
        self.assertEqual(done["status"], "COMPLETED", done)
        self.assertTrue(done["started_at"] and done["completed_at"])
        res = done["result"]
        self.assertEqual((res["persist_outcome"], res["validation_status"], res["registered"]), ("PUBLISHED", "VALID", True))
        self.assertEqual(res["tool_summary"]["status"], "COMPLETED")  # the V2 tool loop ran
        inv = self.get(f"/api/v1/investigations/{res['investigation_id']}").json()
        self.assertEqual((inv["investigation_mode"], inv["eligible"]), ("tools", True))
        findings = self.get(f"/api/v1/investigations/{res['investigation_id']}/findings").json()
        self.assertEqual(findings["investigation_id"], res["investigation_id"])
        ev = self.get(f"/api/v1/investigations/{res['investigation_id']}/evidence?limit=5").json()
        self.assertEqual((ev["source"], len(ev["source_records"])), ("evidence_ledger", 5))
        one = ev["source_records"][0]["evidence_id"]
        self.assertEqual(self.get(f"/api/v1/investigations/{res['investigation_id']}/evidence?evidence_id={one}").json()["total_records"], 1)
        self.assertEqual(self.get(f"/api/v1/investigations/{res['investigation_id']}/evidence?evidence_id=IN-99:NOPE").status_code, 404)
        self.assertEqual(self.provider.calls["investigation"], 1)

    def test_failed_job_is_isolated_and_reported(self):
        self.provider.error = RuntimeError("upstream unavailable sk-live-SECRET-1234 at C:\\internal\\path\\x")
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        self.assertEqual(job["status"], "FAILED")
        self.assertEqual(job["result"]["persist_outcome"], "NOT_PUBLISHED")
        self.assertNotIn("SECRET", job["error_summary"])
        listing = self.get(URL).json()
        self.assertEqual(listing["published"], [])
        self.assertEqual(len(listing["not_published"]), 1)  # the failed attempt is kept by the library, not hidden

    def test_duplicate_request_while_active_is_refused(self):
        self.provider.investigate("SC5A", "EXC-SC5A-01")
        self.provider.gate = gate()  # hold the first job RUNNING
        first = self.post(URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual(first.status_code, 202)
        other = self.post(URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual((other.status_code, other.json()["code"]), (409, "INVESTIGATION_ACTIVE"))
        self.assertEqual(other.json()["job_id"], first.json()["job_id"])
        self.provider.gate.set()
        self.assertEqual(self.wait_job(first.json()["job_id"])["status"], "COMPLETED")
        self.assertEqual(len(self.svc.repos.jobs.list()), 1)

    def test_concurrent_submissions_create_one_job(self):
        self.provider.investigate("SC5A", "EXC-SC5A-01")
        self.provider.gate = gate()
        results = []

        def submit():
            results.append(self.post(URL, {"mode": "tools", "authorization": AI_OK}).status_code)
        threads = [threading.Thread(target=submit) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [202, 409, 409, 409])
        self.provider.gate.set()

    def test_restart_marks_running_jobs_interrupted_and_never_reruns(self):
        self.provider.investigate("SC5A", "EXC-SC5A-01")
        job = self.svc.runner.create("INVESTIGATION", PACK["SC5A"], "analyst-1", "EXC-SC5A-01", {"mode": "tools"})
        self.svc.repos.jobs.update(job["job_id"], {"status": "RUNNING", "started_at": "2026-11-03T10:00:00+00:00"})
        before = sha_tree(self.inv_root)
        self.restart()
        j = self.get(f"/api/v1/jobs/{job['job_id']}").json()
        self.assertEqual(j["status"], "INTERRUPTED")
        self.assertIn("not re-run automatically", j["error_summary"])
        self.assertEqual(self.provider.calls["investigation"], 0)  # no live call was replayed
        self.assertEqual(sha_tree(self.inv_root), before)
        # explicit retry creates a new job; the earlier job record is unchanged
        r = self.post(URL, {"mode": "tools", "retry_of": job["job_id"], "authorization": AI_OK})
        self.assertEqual(r.status_code, 202)
        retry = self.wait_job(r.json()["job_id"])
        self.assertEqual((retry["status"], retry["retry_of"]), ("COMPLETED", job["job_id"]))
        self.assertEqual(self.get(f"/api/v1/jobs/{job['job_id']}").json()["status"], "INTERRUPTED")

    def test_retry_never_overwrites_an_existing_artefact(self):
        first = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        d = next(self.inv_root.rglob(first["result"]["investigation_id"]))
        before = sha_tree(d)
        # Same model output again: same investigation ID. Write-once persistence either recognises an identical rerun
        # (ALREADY_PUBLISHED_IDENTICAL: only a new run record is appended) or, when per-call metadata differs, refuses it
        # (ImmutabilityError). Both are correct; what must never happen is a replaced file.
        second = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        if second["status"] == "COMPLETED":
            self.assertEqual(second["result"]["persist_outcome"], "ALREADY_PUBLISHED_IDENTICAL")
        else:
            self.assertEqual(second["status"], "FAILED")
            self.assertIn("never overwritten", second["error_summary"])
            self.assertNotIn(str(self.tmp), second["error_summary"])
        self.assertEqual({k: v for k, v in sha_tree(d).items() if k in before}, before)
        self.assertEqual(len(self.svc.registry.entries()), 1)

    def test_retry_of_must_reference_the_same_exception(self):
        r = self.post(URL, {"mode": "tools", "retry_of": "JOB-" + "0" * 24, "authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "VALIDATION_ERROR"))

    def test_provider_not_configured_or_simulated(self):
        def unconfigured():
            raise LLMConfigurationError("OPENAI_API_KEY is not set")
        self.svc.investigations.investigator_factory = unconfigured
        r = self.post(URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (503, "PROVIDER_NOT_CONFIGURED"))
        self.svc.investigations.investigator_factory = OfflineSimulatedInvestigator
        r = self.post(URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (503, "PROVIDER_NOT_CONFIGURED"))
        self.assertEqual(self.svc.repos.jobs.list(), [])

    def test_unknown_exception_and_missing_job(self):
        r = self.post(f"/api/v1/packs/{PACK['SC5A']}/exceptions/EXC-SC5A-09/investigations", {"mode": "tools", "authorization": AI_OK})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.get("/api/v1/jobs/JOB-" + "0" * 24).status_code, 404)

    def test_pack_level_listing(self):
        rows = self.get(f"/api/v1/packs/{PACK['SC5A']}/investigations").json()
        self.assertEqual([r["exception_id"] for r in rows], ["EXC-SC5A-01", "EXC-SC5A-02"])


if __name__ == "__main__":
    unittest.main()
