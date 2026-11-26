"""Phase B (stage B2) minimal backend changes for the redesigned UI:

BE1 submission-scoped investigation views (?submission_id= on the exception / pack investigation lists, the investigation
    detail and the auto-investigation status); unscoped responses unchanged.
BE2 GET /packages and GET /submissions/{submission_id} (read-only status and stage through a submission's lifecycle).
BE3 package display names (upload form field, PATCH /packages/{batch_id}, batch detail).
BE4 a submission's analyst decisions are locked once its final pack is generated.
BE5 submission review readiness: running retries block, "eligible investigation exists" is submission-scoped, neutral label.

Offline: temporary folders and a temporary SQLite database, the real OpenAI investigator with its HTTP client mocked (the
fixtures of tests.test_zip_only_workflow / tests.test_zip_submissions). Never PostgreSQL, never a network provider.
Run from uc042/: python -m unittest tests.test_phase_b_backend -v"""
import io
import threading
import unittest
from unittest import mock

from tests.api_support import AI_OK
from tests.test_api_monthly import scenario_files
from tests import test_zip_only_workflow as zw  # module alias: its TestCase classes are not collected twice
from tests.test_zip_submissions import FILES, files, make_zip

PERIOD = "PER-2026-09"
UNKNOWN_SUB = "SUB-" + "0" * 24
IN11 = next(n for n in FILES if n.startswith("transactions_"))


class Case(zw.IsolationCase):
    def scoped(self, url, sub):
        sep = "&" if "?" in url else "?"
        return self.get(f"{url}{sep}submission_id={sub}")

    def packages(self):
        r = self.get("/api/v1/packages")
        self.assertEqual(r.status_code, 200, r.text)
        return {p["batch_id"]: p for p in r.json()}

    def package(self, batch_id):
        return self.packages()[batch_id]

    def wait_items(self, run_id):
        run = self.get(f"/api/v1/processing-runs/{run_id}").json()
        for i in (run["result"].get("auto_investigation") or {}).get("items") or []:
            if i.get("job_id"):
                self.svc.runner.wait(i["job_id"], 120)


# ---------------------------------------------------------------------------------------------- BE1
class ScopedInvestigationViews(Case):
    def test_scoped_views_show_only_the_submission_and_its_decisions(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        _, b = self.submitted(data)
        pack_id, sa, sb = a["result"]["pack_id"], self.sub(a), self.sub(b)
        pa, pb = self.produced(a), self.produced(b)
        self.decide_all(a, "ACCEPT")
        e = sorted(pa)[0]
        url = f"/api/v1/packs/{pack_id}/exceptions/{e}/investigations"

        # unscoped: unchanged (both submissions' artefacts, legacy decision scope -> no decision shown, no submission_id)
        un = self.get(url).json()
        rows = {r["investigation_id"]: r for r in un["published"]}
        self.assertTrue({pa[e], pb[e]} <= set(rows))
        self.assertIsNone(rows[pa[e]]["analyst_review"])
        self.assertIsNone(un.get("submission_id"))

        sc = self.scoped(url, sa).json()
        self.assertEqual([r["investigation_id"] for r in sc["published"]], [pa[e]])
        self.assertEqual((sc["published"][0]["analyst_review"]["decision"], sc["published"][0]["analyst_review"]["submission_id"]),
                         ("ACCEPT", sa))
        self.assertEqual(sc["submission_id"], sa)
        sc_b = self.scoped(url, sb).json()
        self.assertEqual([r["investigation_id"] for r in sc_b["published"]], [pb[e]])
        self.assertIsNone(sc_b["published"][0]["analyst_review"])  # A's decision never shows in B

        # the whole pack, scoped
        for row in self.scoped(f"/api/v1/packs/{pack_id}/investigations", sa).json():
            self.assertEqual([r["investigation_id"] for r in row["published"]], [pa[row["exception_id"]]] if row["exception_id"] in pa else [])
            self.assertTrue(all(r["analyst_review"]["decision"] == "ACCEPT" for r in row["published"]))
        self.assertEqual(len(self.get(f"/api/v1/packs/{pack_id}/investigations").json()[0]["published"]), 2)  # unscoped unchanged

        # the investigation detail
        d = self.get(f"/api/v1/investigations/{pa[e]}").json()
        self.assertEqual((d["analyst_review"], d["submission_id"]), (None, sa))
        d = self.scoped(f"/api/v1/investigations/{pa[e]}", sa).json()
        self.assertEqual(d["analyst_review"]["decision"], "ACCEPT")
        r = self.scoped(f"/api/v1/investigations/{pa[e]}", sb)
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVESTIGATION_NOT_IN_SUBMISSION"))

        # the auto-investigation status
        st_a = self.scoped(f"/api/v1/packs/{pack_id}/auto-investigations", sa).json()
        self.assertEqual((st_a["submission_id"], st_a["run_id"], st_a["can_start"]), (sa, a["run_id"], False))
        self.assertEqual({x["state"] for x in st_a["exceptions"]}, {"ACCEPTED"})
        self.assertTrue(st_a["authorizations"] and all(x["authorization_id"] == a["result"]["auto_investigation"]["authorization_id"]
                                                       for x in st_a["authorizations"]))
        r = self.post(f"/api/v1/investigations/{pb[e]}/analyst-review",
                      {"decision": "REJECT", "rejection_reason": "not supported", "expected_revision": 0, "submission_id": sb})
        self.assertEqual(r.status_code, 201, r.text)
        st_b = {x["exception_id"]: x["state"] for x in self.scoped(f"/api/v1/packs/{pack_id}/auto-investigations", sb).json()["exceptions"]}
        self.assertEqual(st_b[e], "REJECTED")
        self.assertTrue(all(s == "READY_FOR_REVIEW" for x, s in st_b.items() if x != e))
        un = self.get(f"/api/v1/packs/{pack_id}/auto-investigations").json()
        self.assertNotIn("submission_id", un)
        self.assertEqual({x["state"] for x in un["exceptions"]}, {"READY_FOR_REVIEW"})  # legacy scope: no decision

    def test_invalid_unknown_and_mismatched_submissions(self):
        _, a = self.submitted(make_zip(FILES))
        pack_id = a["result"]["pack_id"]
        e, inv = sorted(self.produced(a).items())[0]
        other = next(p["pack_id"] for p in self.get(f"/api/v1/periods/{PERIOD}").json()["period"]["packs"] if p["pack_id"] != pack_id)
        for url in (f"/api/v1/packs/{pack_id}/exceptions/{e}/investigations", f"/api/v1/packs/{pack_id}/investigations",
                    f"/api/v1/packs/{pack_id}/auto-investigations", f"/api/v1/investigations/{inv}"):
            with self.subTest(url=url):
                r = self.scoped(url, "not-an-id")
                self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_ID"))
                self.assertEqual(self.scoped(url, UNKNOWN_SUB).status_code, 404)
        for url in (f"/api/v1/packs/{other}/investigations", f"/api/v1/packs/{other}/auto-investigations"):
            r = self.scoped(url, self.sub(a))
            self.assertEqual((r.status_code, r.json()["code"]), (409, "SUBMISSION_PACK_MISMATCH"), url)

    def test_failed_attempts_and_jobs_are_scoped(self):
        self.answers.fail = True
        _, a = self.submitted(make_zip(FILES))
        self.answers.fail = False
        _, b = self.submitted(make_zip(FILES))
        pack_id = a["result"]["pack_id"]
        own_a = self.svc.auto_investigations.submission_artefacts(self.svc.repos.runs.get(a["run_id"]))
        for row in self.scoped(f"/api/v1/packs/{pack_id}/investigations", self.sub(a)).json():
            self.assertEqual(row["published"], [])
            self.assertTrue(all(x.get("record") in own_a["not_published"] for x in row["not_published"]))
        for row in self.scoped(f"/api/v1/packs/{pack_id}/investigations", self.sub(b)).json():
            self.assertEqual(row["not_published"], [])  # A's failed attempts never show in B
            self.assertEqual(len(row["published"]), 1)
        st = self.scoped(f"/api/v1/packs/{pack_id}/auto-investigations", self.sub(a)).json()
        self.assertEqual({x["state"] for x in st["exceptions"]}, {"FAILED"})
        self.assertTrue(st["can_retry"])


# ---------------------------------------------------------------------------------------------- BE2 / BE3
class PackagesAndSubmissions(Case):
    def test_package_stages_through_a_submission_lifecycle(self):
        rejected = self.upload_zip(make_zip(files(extra={"notes.txt": b"x"})), name="bad.zip")
        incomplete = self.upload_zip(make_zip(files(skip=(IN11,))), name="sept_incomplete-2026.zip")
        good = self.client.post(f"/api/v1/periods/{PERIOD}/packages", data={"display_name": "  September main pack  "},
                                files=[("file", ("september.zip", io.BytesIO(make_zip(FILES)), "application/zip"))])
        self.assertEqual(good.status_code, 201, good.text)
        good = good.json()
        bid = good["batch"]["batch_id"]
        self.assertEqual(good["batch"]["summary"]["package"]["display_name"], "September main pack")
        self.assertEqual(good["batch"]["display_name"], "September main pack")

        pk = self.packages()
        self.assertEqual(set(pk), self.svc.monthly.zip_batch_ids())  # ZIP packages only (no legacy / scenario batches)
        created = [p["created_at"] for p in self.get("/api/v1/packages").json()]
        self.assertEqual(created, sorted(created, reverse=True))  # newest first
        r = pk[rejected["batch"]["batch_id"]]
        self.assertEqual((r["stage"], r["status"], r["gate"]["passed"], r["latest_submission"], r["document_count"]),
                         ("PACKAGE_REJECTED", "PACKAGE_REJECTED", False, None, 0))
        self.assertEqual((r["display_name"], r["display_name_source"]), ("Bad", "DERIVED"))
        self.assertTrue(r["gate"]["reason"])
        i = pk[incomplete["batch"]["batch_id"]]
        self.assertEqual((i["stage"], i["gate"]["missing_required"], i["display_name"]),
                         ("PACKAGE_INCOMPLETE", ["IN-11"], "Sept incomplete 2026"))
        self.assertEqual(i["gate"]["present_required"], i["gate"]["required_total"] - 1)
        g = pk[bid]
        self.assertEqual((g["stage"], g["display_name"], g["display_name_source"], g["submissions_count"], g["latest_submission"]),
                         ("READY_TO_SUBMIT", "September main pack", "STORED", 0, None))
        self.assertEqual((g["gate"]["passed"], g["gate"]["present_required"]), (True, g["gate"]["required_total"]))
        self.assertEqual((g["document_count"], g["zip_name"], g["period_id"]), (19, "september.zip", PERIOD))

        # submitted: AI investigations held while running
        self.answers.hold = threading.Event()
        run = self.submit(bid)
        self.svc.runner.wait(run["job_id"], 180)
        s = self.package(bid)["latest_submission"]
        self.assertEqual((s["submission_id"], s["run_id"], s["run_status"]), (run["result"]["submission_id"], run["run_id"], "SUCCEEDED"))
        self.assertEqual(s["stage"], "AI_INVESTIGATING")
        self.assertGreater(s["investigations"]["running"], 0)
        self.answers.hold.set()
        self.wait_items(run["run_id"])
        run = self.get(f"/api/v1/processing-runs/{run['run_id']}").json()
        n = run["result"]["exceptions"]
        p = self.package(bid)
        s = p["latest_submission"]
        self.assertEqual((p["stage"], s["stage"], s["exception_count"], s["pack_id"], s["outcome"]),
                         ("FINDINGS_TO_REVIEW", "FINDINGS_TO_REVIEW", n, run["result"]["pack_id"], run["result"]["outcome"]))
        self.assertEqual(s["investigations"], {"total": n, "completed": n, "failed": 0, "running": 0, "not_started": 0})
        self.assertEqual(s["decisions"], {"accepted": 0, "rejected": 0, "pending": n})
        self.assertEqual((s["review"], s["final_pack"], p["submission_ids"]), (None, None, [s["submission_id"]]))

        self.decide_all(run, "ACCEPT")
        s = self.package(bid)["latest_submission"]
        self.assertEqual((s["stage"], s["decisions"]), ("READY_FOR_FINAL_REVIEW", {"accepted": n, "rejected": 0, "pending": 0}))
        rv = self.open_review(run)
        s = self.package(bid)["latest_submission"]
        self.assertEqual((s["stage"], s["review"]), ("FINAL_REVIEW_IN_PROGRESS", {"review_id": rv["review_id"], "status": "OPEN"}))
        fp = self.generate(self.preview(rv["review_id"]))
        s = self.package(bid)["latest_submission"]
        self.assertEqual((s["stage"], s["final_pack"]["final_pack_id"], s["review"]["status"]), ("FINAL_PACK_GENERATED", fp, "GENERATED"))

        # the submission detail: the same object plus its package
        d = self.get(f"/api/v1/submissions/{s['submission_id']}").json()
        self.assertEqual({k: d[k] for k in s}, s)
        self.assertEqual((d["batch_id"], d["display_name"], d["period_id"], d["zip_name"]), (bid, "September main pack", PERIOD, "september.zip"))
        self.assertEqual(self.get(f"/api/v1/submissions/{UNKNOWN_SUB}").status_code, 404)
        r = self.get("/api/v1/submissions/not-an-id")
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_ID"))

    def test_audit_running_and_failed_stages(self):
        d = self.upload_zip(make_zip(FILES))
        bid = d["batch"]["batch_id"]
        with mock.patch("uc042app.services.monthly.build", return_value=("FAILED", None, None, None, ["ASSEMBLY: simulated"])):
            failed = self.finish(self.submit(bid))
        self.assertEqual(failed["status"], "FAILED")
        s = self.package(bid)["latest_submission"]
        self.assertEqual((s["stage"], s["run_status"], s["exception_count"], s["review"]), ("AUDIT_FAILED", "FAILED", None, None))
        self.assertTrue(s["run_error"])
        with mock.patch.object(self.svc.runner, "submit"):  # the run stays QUEUED
            queued = self.submit(bid)
        p = self.package(bid)
        self.assertEqual((p["stage"], p["latest_submission"]["submission_id"], p["submissions_count"]),
                         ("AUDIT_RUNNING", queued["result"]["submission_id"], 2))
        self.assertEqual(p["submission_ids"], [queued["result"]["submission_id"], failed["result"]["submission_id"]])

    def test_display_name_patch_and_validation(self):
        d = self.upload_zip(make_zip(FILES), name="sept.zip")
        bid = d["batch"]["batch_id"]
        self.assertEqual(d["batch"]["display_name"], "Sept")
        self.assertNotIn("display_name", d["batch"]["summary"]["package"])
        r = self.client.patch(f"/api/v1/packages/{bid}", json={"display_name": "  Final September  "})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["display_name"], r.json()["display_name_source"]), ("Final September", "STORED"))
        b = self.get(f"/api/v1/uploads/{bid}").json()["batch"]
        self.assertEqual((b["display_name"], b["summary"]["package"]["display_name"]), ("Final September", "Final September"))
        self.assertTrue(b["summary"]["package"]["gate"]["passed"])  # the rest of the package report is kept
        events = [e for e in self.get("/api/v1/activity").json() if e["action"] == "PACKAGE_RENAMED"]
        self.assertEqual((events[0]["entity_id"], events[0]["details"]["display_name"]), (bid, "Final September"))
        self.assertEqual(self.get(f"/api/v1/packages/{bid}").json()["display_name"], "Final September")
        r = self.client.patch(f"/api/v1/packages/{bid}", json={"display_name": "   "})  # empty clears
        self.assertEqual((r.json()["display_name"], r.json()["display_name_source"]), ("Sept", "DERIVED"))
        r = self.client.patch(f"/api/v1/packages/{bid}", json={"display_name": "x" * 201})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_DISPLAY_NAME"))
        self.assertEqual(self.client.patch(f"/api/v1/packages/{bid}", json={"display_name": "x" * 200}).status_code, 200)
        r = self.client.patch("/api/v1/packages/UPL-" + "0" * 24, json={"display_name": "x"})
        self.assertEqual(r.status_code, 404)
        r = self.client.patch("/api/v1/packages/nope", json={"display_name": "x"})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_ID"))
        # an over-long name at upload is refused before anything is stored
        before = len(self.svc.monthly.zip_batch_ids())
        r = self.client.post(f"/api/v1/periods/{PERIOD}/packages", data={"display_name": "y" * 201},
                             files=[("file", ("s.zip", io.BytesIO(make_zip(FILES)), "application/zip"))])
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_DISPLAY_NAME"))
        self.assertEqual(len(self.svc.monthly.zip_batch_ids()), before)
        # a rejected package keeps its name
        r = self.client.post(f"/api/v1/periods/{PERIOD}/packages", data={"display_name": "Broken one"},
                             files=[("file", ("b.zip", io.BytesIO(b"not a zip"), "application/zip"))])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["batch"]["status"], r.json()["batch"]["display_name"]), ("PACKAGE_REJECTED", "Broken one"))


class DisplayNameOnLegacyBatch(zw.Helpers, zw.zs.ZipCase):
    LEGACY_ENTRY_POINTS = True  # a historical-style individual-document batch

    def test_a_legacy_batch_is_not_a_package(self):
        b = self.upload(PERIOD, scenario_files())
        r = self.client.patch(f"/api/v1/packages/{b['batch']['batch_id']}", json={"display_name": "x"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NOT_A_PACKAGE"))
        self.assertIsNone(b["batch"].get("display_name"))
        self.assertNotIn(b["batch"]["batch_id"], {p["batch_id"] for p in self.get("/api/v1/packages").json()})


# ---------------------------------------------------------------------------------------------- BE4
class DecisionLock(Case):
    def test_decisions_are_locked_after_the_submission_final_pack_is_generated(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        _, b = self.submitted(data)
        pa = self.produced(a)
        e = sorted(pa)[0]
        self.decide_all(a, "ACCEPT")
        # allowed before generation: a changed decision is recorded (revision 2), then changed back
        for decision, rev in (("REJECT", 1), ("ACCEPT", 2)):
            body = {"decision": decision, "expected_revision": rev, "submission_id": self.sub(a)}
            if decision == "REJECT":
                body["rejection_reason"] = "changed my mind"
            r = self.post(f"/api/v1/investigations/{pa[e]}/analyst-review", body)
            self.assertEqual(r.status_code, 201, r.text)
        fp = self.generate(self.preview(self.open_review(a)["review_id"]))
        before = len(self.svc.repos.investigation_reviews.list(investigation_id=pa[e]))
        r = self.post(f"/api/v1/investigations/{pa[e]}/analyst-review",
                      {"decision": "REJECT", "rejection_reason": "too late", "expected_revision": 3, "submission_id": self.sub(a)})
        self.assertEqual((r.status_code, r.json()["code"], r.json()["final_pack_id"]), (409, "DECISION_LOCKED_FINAL_PACK_GENERATED", fp))
        self.assertIn(fp, r.json()["detail"])
        self.assertEqual(len(self.svc.repos.investigation_reviews.list(investigation_id=pa[e])), before)  # nothing recorded
        # another submission of the identical pack is not locked
        self.decide_all(b, "ACCEPT")

    def test_a_generating_review_also_locks(self):
        _, a = self.submitted(make_zip(FILES))
        rv = self.open_review(a)
        session = self.svc.repos.reviews.get(rv["review_id"])
        self.svc.repos.reviews.save(dict(session, status="GENERATING"), session["revision"])
        inv = next(iter(self.produced(a).values()))
        r = self.post(f"/api/v1/investigations/{inv}/analyst-review",
                      {"decision": "ACCEPT", "expected_revision": 0, "submission_id": self.sub(a)})
        self.assertEqual((r.status_code, r.json()["code"], r.json()["final_pack_id"]), (409, "DECISION_LOCKED_FINAL_PACK_GENERATED", None))


# ---------------------------------------------------------------------------------------------- BE5
class SubmissionReadiness(Case):
    def test_a_running_retry_blocks_as_investigation_running(self):
        self.answers.fail = True
        _, run = self.submitted(make_zip(FILES))
        self.answers.fail = False
        rv = self.open_review(run)
        self.answers.hold = threading.Event()
        r = self.post(f"/api/v1/submissions/{self.sub(run)}/investigations/retry", {"authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        try:
            self.assertIn("INVESTIGATION_RUNNING", self.blockers(rv["review_id"]))  # before the fix: the retry was ignored
        finally:
            self.answers.hold.set()
            for i in r.json()["items"]:
                if i.get("job_id"):
                    self.svc.runner.wait(i["job_id"], 120)
        self.assertNotIn("INVESTIGATION_RUNNING", self.blockers(rv["review_id"]))

    def test_another_submissions_eligible_investigation_is_never_offered_for_inclusion(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        self.assertTrue(self.produced(a))
        with mock.patch.object(self.svc.auto_investigations, "after_run", side_effect=RuntimeError("crashed before enqueueing")):
            _, b = self.submitted(data)
        rv = self.open_review(b)
        self.assertTrue(all(s["inclusion"] == "NOT_INVESTIGATED" for s in rv["selections"]))
        found = [x["detail"] for x in rv["readiness"]["blockers"] if x["code"] == "NOT_INVESTIGATED_WITH_ELIGIBLE"]
        self.assertTrue(found)
        self.assertTrue(all("another submission" in d and "include it (if registered)" not in d for d in found), found)

    def test_submission_checklist_wording_is_neutral(self):
        _, run = self.submitted(make_zip(FILES))
        rows = self.open_review(run)["readiness"]["checklist"]["exceptions"]
        waiting = [r for r in rows if r["disposition"] == "AWAITING_DECISION"]
        self.assertTrue(waiting)
        for r in waiting:
            self.assertEqual(r["disposition_label"], "Findings ready for review: ACCEPT or REJECT the AI finding for this submission")
            self.assertNotIn("Exception Workspace", r["disposition_label"])


if __name__ == "__main__":
    unittest.main()
