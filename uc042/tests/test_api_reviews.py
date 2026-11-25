"""Human review workflow and final packs through the API: sessions, selections and eligibility, closing summary and
preview (including summary failure), HOLD and GENERATE, stale previews, acknowledgement, duplicate and concurrent
GENERATE, blocking investigations, generation failure and recovery, versioning, file retrieval and immutability.
Uses the existing final-pack library throughout. Offline. Run from uc042/: python -m unittest -v"""
import json
import threading
import unittest
from unittest import mock

from tests.api_support import AI_OK, ROOT, ApiCase, gate
from tests.final_pack_support import OFFLINE, PACK, make_investigation, sha_tree
from uc042lib.final_pack.model import ACKNOWLEDGEMENT_TEXT
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import LLMCallError

SC5A = PACK["SC5A"]


class ReviewCase(ApiCase):
    def setUp(self):
        super().setUp()
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        self.assertEqual(job["status"], "COMPLETED", job)
        self.inv_id = job["result"]["investigation_id"]

    def open(self, pack=SC5A):
        r = self.post(f"/api/v1/packs/{pack}/reviews")
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()

    def generate(self, session, **overrides):
        body = {"decision": "GENERATE", "snapshot_sha256": session["current_preview"]["snapshot_sha256"],
                "acknowledgement_accepted": True, "comment": "Reviewed the preview."}
        body.update(overrides)
        return self.post(f"/api/v1/reviews/{session['review_id']}/decision", body)

    def hold(self, session, comment="Waiting for the bank trace."):
        return self.post(f"/api/v1/reviews/{session['review_id']}/decision", {"decision": "HOLD", "comment": comment})

    def final_dirs(self):
        root = self.settings.final_packs_root
        return sorted(p.name for p in root.glob("FAP-*")) if root.is_dir() else []


class Sessions(ReviewCase):
    def test_open_defaults_and_single_active_session(self):
        s = self.open()
        self.assertEqual(s["status"], "OPEN")
        self.assertEqual(s["acknowledgement_text"], ACKNOWLEDGEMENT_TEXT)
        sel = {x["exception_id"]: x for x in s["selections"]}
        self.assertEqual(sel["EXC-SC5A-01"], {"exception_id": "EXC-SC5A-01", "inclusion": "INCLUDED", "investigation_id": self.inv_id, "reason": ""})
        self.assertEqual(sel["EXC-SC5A-02"]["inclusion"], "NOT_INVESTIGATED")
        self.assertEqual([b["code"] for b in s["readiness"]["blockers"]], ["PREVIEW_REQUIRED"])
        again = self.post(f"/api/v1/packs/{SC5A}/reviews")
        self.assertEqual((again.status_code, again.json()["review_id"]), (200, s["review_id"]))

    def test_sessions_persist_across_restart(self):
        s = self.preview(self.open()["review_id"])
        self.restart()
        again = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertEqual((again["status"], again["current_preview"]["preview_id"]), ("OPEN", s["current_preview"]["preview_id"]))

    def test_selection_validation(self):
        s = self.open()
        url = f"/api/v1/reviews/{s['review_id']}/selections"
        unregistered = make_investigation("SC5A", "EXC-SC5A-01", self.inv_root,
                                          edit=lambda o: o.update(investigation_summary=o["investigation_summary"] + " Second run."))
        simulated = run_investigation(SC5A, "EXC-SC5A-01", OFFLINE, investigations_root=self.inv_root)["result"]["investigation_id"]
        for inv, needle in ((unregistered, "publication registry"), (simulated, "simulated")):
            r = self.client.patch(url, json={"selections": [
                {"exception_id": "EXC-SC5A-01", "inclusion": "INCLUDED", "investigation_id": inv},
                {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}]})
            self.assertEqual((r.status_code, r.json()["code"]), (422, "INELIGIBLE_SELECTION"))
            self.assertIn(needle, r.json()["detail"])
        cases = [([{"exception_id": "EXC-SC5A-01", "inclusion": "EXCLUDED_BY_ANALYST"},
                   {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}], "SELECTION_INVALID"),
                 ([{"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}], "SELECTION_INCOMPLETE"),
                 ([{"exception_id": "EXC-SC5A-01", "inclusion": "NOT_INVESTIGATED"},
                   {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}], "NOT_INVESTIGATED_WITH_ELIGIBLE")]
        for selections, code in cases:
            r = self.client.patch(url, json={"selections": selections})
            self.assertEqual((r.status_code, r.json()["code"]), (422, code), code)
        ok = self.client.patch(url, json={"selections": [
            {"exception_id": "EXC-SC5A-01", "inclusion": "EXCLUDED_BY_ANALYST", "reason": "Analyst excluded for the test."},
            {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}]})
        self.assertEqual(ok.status_code, 200, ok.text)
        stale = self.client.patch(url, json={"selections": ok.json()["selections"], "expected_revision": 1})
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "REVIEW_CONFLICT"))


class Preview(ReviewCase):
    def test_preview_with_generated_closing_summary_and_renderings(self):
        s = self.preview(self.open()["review_id"])
        p = s["current_preview"]
        self.assertEqual(p["closing_summary"]["status"], "GENERATED")
        self.assertTrue(p["preview_final_pack_id"].startswith("PREVIEW-"))
        self.assertTrue(s["readiness"]["ready"], s["readiness"])
        self.assertEqual(self.provider.calls["summary"], 1)
        base = f"/api/v1/reviews/{s['review_id']}/preview"
        html = self.get(base + "/html")
        self.assertIn("PREVIEW - not a final audit pack", html.text)
        self.assertIn("sandbox", html.headers["content-security-policy"])
        self.assertEqual(html.headers["x-snapshot-sha256"], p["snapshot_sha256"])
        self.assertTrue(self.get(base + "/pdf").content.startswith(b"%PDF"))
        doc = self.get(base + "/json").json()
        self.assertEqual(doc["final_content_sha256"], p["preview_content_sha256"])
        self.assertEqual(self.get(base + "?x=1").json()["preview_id"], p["preview_id"])
        stale = self.get(base + "/html?snapshot=" + "0" * 64)
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "PREVIEW_STALE"))
        self.assertEqual(self.final_dirs(), [])  # previews are never published

    def test_selection_change_invalidates_summary_and_preview(self):
        s = self.preview(self.open()["review_id"])
        r = self.client.patch(f"/api/v1/reviews/{s['review_id']}/selections", json={"selections": s["selections"]})
        after = r.json()
        self.assertIsNone(after["current_preview"])
        self.assertIn("PREVIEW_REQUIRED", [b["code"] for b in after["readiness"]["blockers"]])
        self.assertEqual(self.get(f"/api/v1/reviews/{s['review_id']}/preview").json()["code"], "NO_PREVIEW")
        g = self.generate(s)
        self.assertEqual((g.status_code, g.json()["code"]), (409, "PREVIEW_REQUIRED"))

    def test_summary_failure_is_recorded_never_fabricated_and_needs_acknowledgement(self):
        self.provider.summary_error = LLMCallError("the model refused", "refusal")
        s = self.preview(self.open()["review_id"])
        cs = s["current_preview"]["closing_summary"]
        self.assertEqual(cs["status"], "UNAVAILABLE")
        self.assertTrue(cs["failure"]["kind"] and "refused" in cs["failure"]["detail"], cs)
        self.assertIn("CLOSING_SUMMARY_UNAVAILABLE", [w["code"] for w in s["readiness"]["warnings"]])
        r = self.generate(s)
        self.assertEqual((r.status_code, r.json()["code"]), (422, "SUMMARY_UNAVAILABLE_ACK_REQUIRED"))
        r = self.generate(s, acknowledged_summary_unavailable=True)
        self.assertEqual(r.status_code, 201, r.text)
        final = self.get(f"/api/v1/final-packs/{r.json()['final_pack']['final_pack_id']}/json").json()
        self.assertEqual(final["closing_summary"]["status"], "UNAVAILABLE")
        self.assertIsNone(final["closing_summary"]["output"])


class Decisions(ReviewCase):
    def test_hold_then_resume_then_generate(self):
        s = self.preview(self.open()["review_id"])
        r = self.hold(s, comment="  ")
        self.assertEqual((r.status_code, r.json()["code"]), (422, "COMMENT_REQUIRED"))
        before = sha_tree(self.inv_root)
        r = self.hold(s)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["session_status"], "ON_HOLD")
        self.assertEqual(self.final_dirs(), [])
        self.assertEqual(sha_tree(self.inv_root), before)  # HOLD touches no artefact
        held = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertIsNone(held["current_preview"])  # a new preview is required on resume
        g = self.generate(s)
        self.assertEqual(g.json()["code"], "PREVIEW_REQUIRED")
        s = self.preview(s["review_id"])
        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]
        self.assertEqual((g.json()["session_status"], fp["status"], fp["version"]), ("GENERATED", "GENERATED", 1))
        hist = self.get(f"/api/v1/reviews/{s['review_id']}/history").json()
        self.assertEqual([d["decision"] for d in hist["decisions"]], ["HOLD", "GENERATE"])
        final = self.get(f"/api/v1/final-packs/{fp['final_pack_id']}/json").json()
        self.assertEqual(final["human_review"]["decision"], "GENERATE")
        self.assertEqual([d["decision"] for d in final["human_review"]["prior_decisions"]], ["HOLD"])
        self.assertEqual(final["human_review"]["reviewer"], {"user_id": "analyst-1", "display_name": "Test Analyst"})  # configured reference
        # unresolved exceptions are never blocked and stay UNRESOLVED in the final pack
        reg = final["exception_register"]
        self.assertEqual([x["exception"]["exception_id"] for x in reg], ["EXC-SC5A-01", "EXC-SC5A-02"])
        self.assertTrue(all(x["resolution_status"] == "UNRESOLVED" for x in reg))

    def test_generate_requires_acknowledgement_and_current_snapshot(self):
        s = self.preview(self.open()["review_id"])
        r = self.generate(s, acknowledgement_accepted=False)
        self.assertEqual((r.status_code, r.json()["code"]), (422, "ACKNOWLEDGEMENT_REQUIRED"))
        r = self.generate(s, snapshot_sha256="0" * 64)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "PREVIEW_STALE"))
        r = self.generate(s, snapshot_sha256=None)
        self.assertEqual(r.json()["code"], "PREVIEW_STALE")
        self.assertEqual(self.final_dirs(), [])

    def test_new_investigation_after_preview_makes_it_stale(self):
        s = self.preview(self.open()["review_id"])
        job = self.run_investigation_job("SC5A", "EXC-SC5A-02")
        self.assertEqual(job["status"], "COMPLETED", job)
        r = self.generate(s)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "PREVIEW_STALE"))

    def test_running_investigation_blocks_generate_and_preview(self):
        s = self.preview(self.open()["review_id"])
        self.provider.investigate("SC5A", "EXC-SC5A-02")
        self.provider.gate = gate()
        job = self.post(f"/api/v1/packs/{SC5A}/exceptions/EXC-SC5A-02/investigations", {"mode": "tools", "authorization": AI_OK}).json()
        r = self.generate(s)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "BLOCKED"))
        self.assertIn("INVESTIGATION_RUNNING", [b["code"] for b in r.json()["blockers"]])
        r = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK})
        self.assertEqual(r.json()["code"], "BLOCKED")
        self.provider.gate.set()
        self.wait_job(job["job_id"])

    def test_duplicate_generate_never_creates_a_second_pack(self):
        s = self.preview(self.open()["review_id"])
        first = self.generate(s)
        self.assertEqual(first.status_code, 201)
        other = self.generate(s)
        self.assertEqual((other.status_code, other.json()["code"]), (409, "SESSION_CLOSED"))
        self.assertEqual(other.json()["final_pack_id"], first.json()["final_pack"]["final_pack_id"])
        self.assertEqual(len(self.final_dirs()), 1)

    def test_concurrent_generate_publishes_exactly_one_pack(self):
        s = self.preview(self.open()["review_id"])
        out = []
        barrier = threading.Barrier(4)

        def go():
            barrier.wait()
            out.append(self.generate(s))
        threads = [threading.Thread(target=go) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        codes = sorted(r.status_code for r in out)
        self.assertEqual(codes, [201, 409, 409, 409], [r.json() for r in out])
        self.assertTrue(all(r.json()["code"] in ("GENERATION_IN_PROGRESS", "SESSION_CLOSED") for r in out if r.status_code == 409))
        self.assertEqual(len(self.final_dirs()), 1)

    def test_generation_failure_publishes_nothing_and_can_be_retried(self):
        s = self.preview(self.open()["review_id"])
        with mock.patch("uc042app.services.final_packs.publish_final_pack", side_effect=OSError("disk full")):
            r = self.generate(s)
        self.assertEqual((r.status_code, r.json()["code"]), (500, "GENERATION_FAILED"))
        self.assertEqual(self.final_dirs(), [])
        self.assertEqual(self.get(f"/api/v1/reviews/{s['review_id']}").json()["status"], "GENERATION_FAILED")
        retry = self.generate(s)  # a new GENERATE decision
        self.assertEqual(retry.status_code, 201, retry.text)
        hist = self.get(f"/api/v1/reviews/{s['review_id']}/history").json()
        self.assertEqual([d["decision"] for d in hist["decisions"]], ["GENERATE", "GENERATE"])
        self.assertEqual(sorted(r["status"] for r in hist["final_pack_records"]), ["GENERATED", "GENERATION_FAILED"])


class FinalPacks(ReviewCase):
    def test_published_pack_retrieval_verification_and_immutability(self):
        s = self.preview(self.open()["review_id"])
        fid = self.generate(s).json()["final_pack"]["final_pack_id"]
        listing = self.get("/api/v1/final-packs").json()
        self.assertEqual([f["final_pack_id"] for f in listing], [fid])
        detail = self.get(f"/api/v1/final-packs/{fid}").json()
        self.assertEqual((detail["status"], detail["record"]["status"]), ("GENERATED", "GENERATED"))
        self.assertEqual(self.get(f"/api/v1/final-packs/{fid}/verify").json(), {"final_pack_id": fid, "verified": True, "problems": []})
        html, pdf, js = (self.get(f"/api/v1/final-packs/{fid}/{k}") for k in ("html", "pdf", "json"))
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(js.json()["metadata"]["final_pack_id"], fid)
        self.assertEqual(html.headers["etag"].strip('"'), detail["files"]["html"]["sha256"])
        self.assertNotIn(str(self.tmp), json.dumps(detail))
        for method in ("put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(f"/api/v1/final-packs/{fid}").status_code, 405)
        (self.settings.final_packs_root / fid / "report.html").write_text("<p>altered</p>", encoding="utf-8")
        r = self.get(f"/api/v1/final-packs/{fid}/html")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "FINAL_PACK_INTEGRITY_FAILED"))
        self.assertFalse(self.get(f"/api/v1/final-packs/{fid}/verify").json()["verified"])

    def test_second_session_produces_the_next_version(self):
        s1 = self.preview(self.open()["review_id"])
        v1 = self.generate(s1).json()["final_pack"]
        s2 = self.preview(self.open()["review_id"])
        self.assertNotEqual(s2["review_id"], s1["review_id"])
        self.assertIn("FINAL_PACK_EXISTS", [w["code"] for w in s2["readiness"]["warnings"]])
        v2 = self.generate(s2).json()["final_pack"]
        self.assertEqual((v2["version"], v2["supersedes_final_pack_id"]), (2, v1["final_pack_id"]))
        self.assertEqual(len(self.final_dirs()), 2)

    def test_restart_recovers_interrupted_generation(self):
        s = self.preview(self.open()["review_id"])
        fid = self.generate(s).json()["final_pack"]["final_pack_id"]
        decision = self.get(f"/api/v1/reviews/{s['review_id']}").json()["last_decision_id"]
        # simulate a crash after publication but before the records were updated
        self.svc.repos.final_packs.update(decision, {"status": "GENERATING", "final_pack_id": None})
        session = self.svc.repos.reviews.get(s["review_id"])
        self.svc.repos.reviews.save(dict(session, status="GENERATING", final_pack_id=None), session["revision"])
        (self.settings.final_packs_root / ".tmp-abandoned").mkdir()
        self.restart()
        self.assertEqual(self.svc.repos.final_packs.get(decision)["status"], "GENERATED")
        self.assertEqual(self.get(f"/api/v1/reviews/{s['review_id']}").json()["final_pack_id"], fid)
        self.assertFalse((self.settings.final_packs_root / ".tmp-abandoned").exists())
        # a crash before publication: the record becomes GENERATION_FAILED, nothing is invented
        s2 = self.preview(self.open()["review_id"])
        session = self.svc.repos.reviews.get(s2["review_id"])
        self.svc.repos.reviews.save(dict(session, status="GENERATING", last_decision_id="RD-" + "1" * 24), session["revision"])
        self.svc.repos.final_packs.create({"review_decision_id": "RD-" + "1" * 24, "review_id": s2["review_id"], "pack_id": SC5A,
                                           "status": "GENERATING", "version": 2, "supersedes_final_pack_id": fid,
                                           "created_at": "2026-11-03T10:00:00+00:00"})
        self.restart()
        self.assertEqual(self.get(f"/api/v1/reviews/{s2['review_id']}").json()["status"], "GENERATION_FAILED")
        self.assertEqual(len(self.final_dirs()), 1)

    def test_clean_pack_end_to_end(self):
        s = self.preview(self.open(PACK["S01"])["review_id"])
        self.assertEqual(s["selections"], [])
        r = self.generate(s)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json()["final_pack"]["final_pack_id"].startswith("FAP-S01-"))


class ProtectedArtefacts(unittest.TestCase):
    def test_backend_tests_leave_controlled_folders_unchanged(self):
        """The backend suites write only to temporary folders; the project never gains a final_packs/ directory."""
        self.assertFalse((ROOT / "final_packs").exists())
        self.assertFalse((ROOT / "app_state").exists())


if __name__ == "__main__":
    unittest.main()
