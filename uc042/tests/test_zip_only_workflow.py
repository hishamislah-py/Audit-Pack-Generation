"""ZIP-only operation and submission isolation (consolidated remediation, 17 Nov 2026).

Group A: the individual-document upload / confirm / process / reconcile / document-review workflow is retired from active use
(the backend refuses it, not only the UI); the retired endpoints can never act on a ZIP package; submission final packs and
documents never feed the legacy period calculations; the shared engine still runs through the ZIP path; historical records
stay readable and verifiable.

Group B: identical submissions share the content-addressed pack but nothing else: their investigations, decisions, reviews,
final-pack versions, preview state, retries and exception history are scoped by submission (submission_id / run_id).

Offline: temporary folders, a temporary SQLite database (or the disposable PostgreSQL test database), the real OpenAI
investigator with its HTTP client mocked. Run from uc042/: python -m unittest tests.test_zip_only_workflow -v"""
import io
import json
import unittest
from unittest import mock

from tests.api_support import AI_OK
from tests.final_pack_support import sha_tree
from tests.test_api_monthly import S05_PACK, scenario_files
from tests import test_zip_submissions as zs  # module alias: its TestCase classes are not collected twice
from tests.test_zip_submissions import FILES, IdenticalAnswers, make_zip, files

PERIOD = "PER-2026-09"


class Helpers:
    def runs(self):
        return self.svc.repos.runs.list()

    def legacy_upload(self, files_, expect=None):
        r = self.client.post(f"/api/v1/periods/{PERIOD}/uploads",
                             files=[("files", (n, io.BytesIO(d), "application/octet-stream")) for n, d in files_])
        if expect is not None:
            self.assertEqual(r.status_code, expect, r.text)
        return r

    def zip_packages(self):
        """A passed (VALIDATED), an incomplete, a rejected and a processed ZIP package of the period."""
        passed = self.upload_zip(make_zip(FILES))
        incomplete = self.upload_zip(make_zip(files(skip=(next(n for n in FILES if n.startswith("transactions_")),))))
        rejected = self.upload_zip(make_zip(files(extra={"notes.txt": b"x"})))
        processed = self.upload_zip(make_zip(FILES))
        run = self.finish(self.submit(processed["batch"]["batch_id"]))
        self.assertEqual(run["status"], "SUCCEEDED", run)
        return {"VALIDATED": passed, "PACKAGE_INCOMPLETE": incomplete, "PACKAGE_REJECTED": rejected, "PROCESSED": processed}


# ---------------------------------------------------------------------------------------------- A1 / A2 / A3: ZIP-only
class ZipOnlyOperation(Helpers, zs.ZipCase):
    def setUp(self):
        super().setUp()
        self.provider.respond = lambda kw: (_ for _ in ()).throw(RuntimeError("provider unreachable (offline test)"))

    def test_a_complete_zip_submission_runs_the_shared_engine(self):
        d = self.upload_zip(make_zip(FILES))
        run = self.finish(self.submit(d["batch"]["batch_id"]))
        self.assertEqual((run["status"], run["result"]["outcome"]), ("SUCCEEDED", "PUBLISHED"), run)
        pack_id = run["result"]["pack_id"]
        listed = {p["pack_id"]: p for p in self.get("/api/v1/packs").json()}
        self.assertTrue(listed[pack_id]["verified"])  # written, verified and registered by the existing engine path
        self.assertTrue(self.get(f"/api/v1/packs/{pack_id}/exceptions").json())

    def test_retired_individual_document_entry_points_refuse(self):
        before = (len(self.runs()), len(self.svc.repos.uploads.batches(PERIOD)))
        r = self.legacy_upload(scenario_files())
        self.assertEqual((r.status_code, r.json()["code"]), (410, "LEGACY_WORKFLOW_RETIRED"))
        r = self.post(f"/api/v1/periods/{PERIOD}/reconciliation", {"purpose": "INITIAL", "ai_authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (410, "LEGACY_WORKFLOW_RETIRED"))
        r = self.post(f"/api/v1/periods/{PERIOD}/reconciliation", {"purpose": "REASSESSMENT", "reason": "x", "ai_authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (410, "LEGACY_WORKFLOW_RETIRED"))
        self.assertEqual((len(self.runs()), len(self.svc.repos.uploads.batches(PERIOD))), before)  # nothing created

    def test_retired_endpoints_never_act_on_a_zip_package(self):
        pkgs = self.zip_packages()
        runs_before = len(self.runs())
        for status, d in pkgs.items():
            batch_id = d["batch"]["batch_id"]
            before = self.get(f"/api/v1/uploads/{batch_id}").json()
            with self.subTest(status=status):
                for url in (f"/api/v1/uploads/{batch_id}/confirm", f"/api/v1/uploads/{batch_id}/process"):
                    r = self.post(url, {"ai_authorization": AI_OK} if url.endswith("process") else None)
                    self.assertEqual((r.status_code, r.json()["code"]), (409, "ZIP_PACKAGE_USE_SUBMIT"), url)
                for doc in before["documents"][:2]:
                    r = self.post(f"/api/v1/documents/{doc['document_id']}/review", {"decision": "EXCLUDE", "comment": "should be refused"})
                    self.assertEqual((r.status_code, r.json()["code"]), (409, "ZIP_PACKAGE_USE_SUBMIT"))
                after = self.get(f"/api/v1/uploads/{batch_id}").json()
                self.assertEqual(after["batch"]["status"], before["batch"]["status"])
                self.assertEqual(after["batch"]["summary"].get("package"), before["batch"]["summary"].get("package"))  # gate unchanged
                self.assertEqual([x["review_decision"] for x in after["documents"]], [x["review_decision"] for x in before["documents"]])
        self.assertEqual(len(self.runs()), runs_before)  # no audit run created by any retired endpoint

    def test_historical_records_remain_readable_and_verifiable(self):
        periods = self.get("/api/v1/periods").json()
        self.assertIn(PERIOD, [p["period_id"] for p in periods])
        detail = self.get(f"/api/v1/periods/{PERIOD}").json()
        self.assertTrue(any(p["pack_id"] == S05_PACK for p in detail["period"]["packs"]))
        listed = {p["pack_id"]: p for p in self.get("/api/v1/packs").json()}
        self.assertTrue(listed[S05_PACK]["verified"])
        self.assertEqual(self.get(f"/api/v1/packs/{S05_PACK}/exceptions").status_code, 200)
        self.assertEqual(self.get(f"/api/v1/periods/{PERIOD}/reassessment").status_code, 200)  # read-only views stay available


class RetiredEndpointsRefuseZipEvenWithTheRetiredWorkflowEnabled(Helpers, zs.ZipCase):
    """The original H1 reproduction: with legacy documents present, /process on an incomplete ZIP package created a run over
    the legacy set under the package's ID. The ZIP guard applies whatever the retired-workflow switch says."""
    LEGACY_ENTRY_POINTS = True

    def test_process_on_an_incomplete_zip_package_with_legacy_documents_present(self):
        b = self.legacy_upload(scenario_files(), expect=201).json()
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        inc = self.upload_zip(make_zip(files(skip=(next(n for n in FILES if n.startswith("transactions_")),))))
        self.assertEqual(inc["batch"]["status"], "PACKAGE_INCOMPLETE")
        before = len(self.runs())
        r = self.post(f"/api/v1/uploads/{inc['batch']['batch_id']}/process", {"ai_authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "ZIP_PACKAGE_USE_SUBMIT"))
        self.assertEqual(len(self.runs()), before)
        self.assertEqual(self.get(f"/api/v1/uploads/{inc['batch']['batch_id']}").json()["batch"]["status"], "PACKAGE_INCOMPLETE")


# ---------------------------------------------------------------------------------------------- A4: no legacy influence
class SubmissionsDoNotAffectLegacyPeriodCalculations(Helpers, zs.SubmissionReview):
    test_identical_submissions_get_separate_reviews_decisions_and_final_packs = None  # run in tests.test_zip_submissions
    test_submission_scoping_is_enforced = None
    """Historical-style legacy period data (the retired workflow enabled in code, as for historical records) next to a ZIP
    submission with a published final pack: the legacy calculations ignore the submission entirely."""
    LEGACY_ENTRY_POINTS = True

    def test_a_submission_final_pack_and_documents_never_feed_the_legacy_period(self):
        _, run = self.submitted(make_zip(FILES))
        fp, _ = self.review_to_final_pack(run)
        zip_docs = {d["document_id"] for d in self.get(f"/api/v1/uploads/{run['batch_id']}").json()["documents"]}
        m = self.svc.monthly
        self.assertEqual(m.published_final_packs(PERIOD), [])  # the submission's final pack is not a legacy publication
        self.assertEqual(m.reassessment_target(PERIOD), (None, None))  # never a legacy predecessor
        view = self.get(f"/api/v1/periods/{PERIOD}").json()["period"]
        self.assertEqual((view["pending_reassessment"], view["documents_after_publication"]), (False, 0))
        plan = self.get(f"/api/v1/periods/{PERIOD}/reassessment").json()
        self.assertIsNone(plan["target_pack_id"])
        self.assertFalse({d["document_id"] for d in plan["new_documents"]} & zip_docs)
        # a legacy upload of the same files is never a duplicate of, nor "received after", the submission
        b = self.legacy_upload(scenario_files(), expect=201).json()
        codes = {m_["code"] for d in b["documents"] for m_ in d["checks"]["messages"]}
        self.assertFalse(codes & {"DUPLICATE_OF_EARLIER_UPLOAD", "SAME_NAME_DIFFERENT_CONTENT", "RECEIVED_AFTER_PUBLICATION"}, codes)
        self.assertFalse({m_.get("duplicate_of") for d in b["documents"] for m_ in d["checks"]["messages"]} & zip_docs)
        # legacy initial processing is not blocked by the submission's final pack (REASSESSMENT_REQUIRED before the fix)
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        r = self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/process", {"ai_authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        legacy_run = self.finish(r.json())
        self.assertEqual(legacy_run["status"], "SUCCEEDED", legacy_run)
        self.assertIsNone(legacy_run["result"].get("predecessor_pack_id"))
        self.assertEqual(self.get(f"/api/v1/final-packs/{fp}/verify").json()["verified"], True)



# ---------------------------------------------------------------------------------------------- Group B: isolation
class FlakyIdenticalAnswers(IdenticalAnswers):
    """Identical findings for identical evidence; `fail` makes investigation calls fail (a provider error)."""
    fail = False

    def respond(self, kw):
        if self.fail and "<audit_pack_input>" not in kw["input"][0]["content"]:
            raise RuntimeError("provider unavailable (controlled test failure)")
        return super().respond(kw)


class IsolationCase(Helpers, zs.SubmissionReview):
    # the inherited SubmissionReview tests run in tests.test_zip_submissions; only this module's isolation tests run here
    test_identical_submissions_get_separate_reviews_decisions_and_final_packs = None
    test_submission_scoping_is_enforced = None

    def setUp(self):
        super().setUp()
        self.answers = FlakyIdenticalAnswers(self.provider)

    def sub(self, run):
        return run["result"]["submission_id"]

    def open_review(self, run, expect=201):
        r = self.post(f"/api/v1/packs/{run['result']['pack_id']}/reviews", {"submission_id": self.sub(run)})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def decide_all(self, run, decision="ACCEPT"):
        for inv in self.produced(run).values():
            body = {"decision": decision, "expected_revision": 0, "submission_id": self.sub(run)}
            if decision == "REJECT":
                body["rejection_reason"] = f"Rejected in {self.sub(run)}"
            r = self.post(f"/api/v1/investigations/{inv}/analyst-review", body)
            self.assertEqual(r.status_code, 201, r.text)

    def preview(self, review_id):
        r = self.post(f"/api/v1/reviews/{review_id}/preview", {"authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        self.wait_job(r.json()["job_id"], 120)
        return self.get(f"/api/v1/reviews/{review_id}").json()

    def generate(self, s):
        g = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                     "snapshot_sha256": s["current_preview"]["snapshot_sha256"]})
        self.assertEqual(g.status_code, 201, g.text)
        return g.json()["final_pack"]["final_pack_id"]

    def final_dir(self, fp):
        return next(r / fp for r in self.svc.final_packs.roots() if (r / fp).is_dir())

    def blockers(self, review_id):
        return [b["code"] for b in self.get(f"/api/v1/reviews/{review_id}").json()["readiness"]["blockers"]]


class SubmissionIsolation(IsolationCase):
    def test_identical_submissions_share_content_identity_only(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        _, b = self.submitted(data)
        self.assertEqual(a["result"]["pack_id"], b["result"]["pack_id"])  # content identity
        self.assertNotEqual((self.sub(a), a["run_id"]), (self.sub(b), b["run_id"]))
        pa, pb = self.produced(a), self.produced(b)
        self.assertTrue(set(pa.values()).isdisjoint(pb.values()))  # different investigation executions
        # A's review is put ON_HOLD; B can still open and finish its own review (keyed by pack AND submission)
        self.decide_all(a, "ACCEPT")
        ra = self.open_review(a)
        ra = self.preview(ra["review_id"])
        held = self.post(f"/api/v1/reviews/{ra['review_id']}/decision", {"decision": "HOLD", "comment": "waiting for the bank"})
        self.assertEqual(held.json()["session_status"], "ON_HOLD", held.text)
        rb = self.open_review(b)  # before the fix: 409 REVIEW_OTHER_SUBMISSION
        self.assertNotEqual(rb["review_id"], ra["review_id"])
        self.assertEqual(rb["submission_id"], self.sub(b))
        self.assertEqual({x["investigation_id"] for x in rb["selections"] if x["inclusion"] == "INCLUDED"}, set(pb.values()))
        self.assertIn("AI_REVIEW_PENDING", [x["code"] for x in rb["readiness"]["blockers"]])  # A's decisions do not count for B
        self.decide_all(b, "REJECT")
        fp_b = self.generate(self.preview(rb["review_id"]))
        # A finishes afterwards: separate records, no Version 2 / Supersedes chain, no cross-submission attempts
        fp_a = self.generate(self.preview(ra["review_id"]))
        before_b = sha_tree(self.final_dir(fp_b))
        for fp, mine, other in ((fp_a, pa, pb), (fp_b, pb, pa)):
            final = self.get(f"/api/v1/final-packs/{fp}/json").json()
            self.assertEqual((final["metadata"]["version"], final["metadata"]["supersedes_final_pack_id"]), (1, None), fp)
            text = json.dumps(final)
            self.assertFalse([inv for inv in other.values() if inv in text], fp)  # the other submission's investigations never appear
            self.assertTrue(all(inv in text for inv in mine.values()))
        listing = {f["final_pack_id"]: f for f in self.get("/api/v1/final-packs").json()}
        self.assertEqual((listing[fp_a]["submission_id"], listing[fp_b]["submission_id"]), (self.sub(a), self.sub(b)))
        self.assertEqual(sha_tree(self.final_dir(fp_b)), before_b)  # an earlier final pack is unchanged

    def test_another_submissions_progress_never_makes_a_preview_stale(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        self.decide_all(a)
        ra = self.preview(self.open_review(a)["review_id"])
        calls_before = summary_calls(self.provider)
        _, b = self.submitted(data)  # B's investigations complete while A's preview is current
        self.assertTrue(self.produced(b))
        self.assertNotIn("PREVIEW_STALE", self.blockers(ra["review_id"]))
        self.generate(self.get(f"/api/v1/reviews/{ra['review_id']}").json())  # before the fix: 409 PREVIEW_STALE
        self.assertEqual(summary_calls(self.provider), calls_before)  # no repeat closing-summary call


def summary_calls(provider):
    return provider.respond.__self__.mock.calls["summary"] if hasattr(provider.respond, "__self__") else None


class SubmissionRetryAndRecovery(IsolationCase):
    def failed_submission(self):
        self.answers.fail = True
        _, run = self.submitted(make_zip(FILES))
        self.answers.fail = False
        jobs = self.svc.auto_investigations.submission_jobs(self.svc.repos.runs.get(run["run_id"]))
        self.assertTrue(jobs and all(j["status"] == "FAILED" for j in jobs.values()), jobs)
        self.assertEqual(self.produced(run), {})
        return run

    def retry(self, run, expect=202, **body):
        r = self.post(f"/api/v1/submissions/{self.sub(run)}/investigations/retry", dict({"authorization": AI_OK}, **body))
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def finish_items(self, res):
        for i in res["items"]:
            if i.get("job_id"):
                self.svc.runner.wait(i["job_id"], 120)

    def test_failed_investigations_are_retried_within_their_submission(self):
        run = self.failed_submission()
        pack_id = run["result"]["pack_id"]
        exc = sorted(self.svc.auto_investigations.submission_jobs(self.svc.repos.runs.get(run["run_id"])))
        # pack-wide (unscoped) investigation starts are refused on a submission's pack
        r = self.post(f"/api/v1/packs/{pack_id}/auto-investigations", {"authorization": AI_OK, "retry": True})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "SUBMISSION_PACK_USE_SUBMISSION_RETRY"))
        r = self.post(f"/api/v1/packs/{pack_id}/exceptions/{exc[0]}/investigations", {"mode": "tools", "authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "SUBMISSION_PACK_USE_SUBMISSION_RETRY"))
        s = self.open_review(run)
        self.assertIn("INVESTIGATION_FAILED_NO_DISPOSITION", [b["code"] for b in s["readiness"]["blockers"]])
        res = self.retry(run)
        self.assertEqual(sorted(i["exception_id"] for i in res["items"] if i["outcome"] == "QUEUED"), exc)
        self.finish_items(res)
        rec = self.get(f"/api/v1/ai/confirmations/{res['authorization_id']}").json()  # a new recorded authorisation
        self.assertNotEqual(res["authorization_id"], run["result"]["auto_investigation"]["authorization_id"])
        self.assertEqual((rec["operation"], rec["result"], rec["details"]["submission_id"], rec["details"]["run_id"]),
                         ("AUTO_INVESTIGATION", "AUTHORIZED", self.sub(run), run["run_id"]))
        produced = self.produced(run)  # the retry counts for its own submission
        self.assertEqual(sorted(produced), exc)
        for inv in produced.values():
            f = json.loads((next(p for p in self.inv_root.rglob(inv) if p.is_dir()) / "findings.json").read_text(encoding="utf-8"))
            self.assertEqual((f["execution"]["submission_id"], f["execution"]["run_id"], f["execution"]["authorization_id"]),
                             (self.sub(run), run["run_id"], res["authorization_id"]))
        s = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertNotIn("INVESTIGATION_FAILED_NO_DISPOSITION", [b["code"] for b in s["readiness"]["blockers"]])
        self.assertEqual({x["investigation_id"] for x in s["selections"] if x["inclusion"] == "INCLUDED"} or set(produced.values()),
                         set(produced.values()))
        r = self.post(f"/api/v1/submissions/{self.sub(run)}/investigations/retry", {"authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NOTHING_TO_RETRY"))
        # another submission is unaffected by A's retry
        _, b = self.submitted(make_zip(FILES))
        self.assertTrue(set(self.produced(b).values()).isdisjoint(produced.values()))

    def test_interrupted_investigations_are_recovered_within_their_submission(self):
        run = self.failed_submission()
        jobs = self.svc.auto_investigations.submission_jobs(self.svc.repos.runs.get(run["run_id"]))
        first = sorted(jobs)[0]
        self.svc.runner.repo.update(jobs[first]["job_id"], {"status": "INTERRUPTED"})  # as start-up recovery marks it
        res = self.retry(run)
        queued = {i["exception_id"]: i for i in res["items"] if i["outcome"] == "QUEUED"}
        self.assertIn(first, queued)
        self.finish_items(res)
        self.assertEqual(sorted(self.produced(run)), sorted(jobs))
        new = self.get(f"/api/v1/jobs/{queued[first]['job_id']}").json()
        self.assertEqual(new["retry_of"], jobs[first]["job_id"])

    def test_a_run_whose_investigations_were_never_enqueued_is_recovered(self):
        with mock.patch.object(self.svc.auto_investigations, "after_run", side_effect=RuntimeError("crashed before enqueueing")):
            _, run = self.submitted(make_zip(FILES))
        self.assertEqual(run["status"], "SUCCEEDED")
        self.assertEqual(self.svc.auto_investigations.submission_jobs(self.svc.repos.runs.get(run["run_id"])), {})
        res = self.retry(run)
        self.finish_items(res)
        pack = self.svc.packs.load(run["result"]["pack_id"])
        self.assertEqual(sorted(self.produced(run)), sorted(self.svc.packs.exception_ids(pack)))


class DecisionAndHistoryIsolation(IsolationCase):
    def test_submission_investigations_need_submission_scoped_decisions_and_reviews(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        _, b = self.submitted(data)
        pa, pb = self.produced(a), self.produced(b)
        e = sorted(pa)[0]
        rows = {r["investigation_id"]: r for r in
                self.get(f"/api/v1/packs/{a['result']['pack_id']}/exceptions/{e}/investigations").json()["published"]}
        self.assertEqual((rows[pa[e]]["submission_id"], rows[pb[e]]["submission_id"]), (self.sub(a), self.sub(b)))
        r = self.post(f"/api/v1/investigations/{pa[e]}/analyst-review", {"decision": "ACCEPT", "expected_revision": 0})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "DECISION_BELONGS_TO_SUBMISSION"))  # no legacy decision
        r = self.post(f"/api/v1/investigations/{pa[e]}/analyst-review", {"decision": "ACCEPT", "expected_revision": 0,
                                                                         "submission_id": self.sub(b)})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVESTIGATION_NOT_IN_SUBMISSION"))  # a real, different submission
        r = self.post(f"/api/v1/packs/{a['result']['pack_id']}/reviews")  # a period-level review of a submission-only pack
        self.assertEqual((r.status_code, r.json()["code"]), (409, "SUBMISSION_PACK_NEEDS_SUBMISSION"))
        s = self.open_review(a)
        pending = [x["detail"] for x in s["readiness"]["blockers"] if x["code"] == "AI_REVIEW_PENDING"]
        self.assertTrue(pending and all("this submission's review" in d for d in pending), pending)
        self.assertEqual(self.svc.repos.investigation_reviews.list(investigation_id=pa[e]), [])

    def test_exception_history_is_scoped_by_investigation_and_submission(self):
        _, a = self.submitted(make_zip(FILES))
        e, inv = sorted(self.produced(a).items())[0]
        repo = self.svc.repos.investigation_reviews
        base = self.svc.investigation_reviews
        rec = {"analyst_review_id": "AR-" + "1" * 24, "period_id": PERIOD, "pack_id": a["result"]["pack_id"], "exception_id": e,
               "investigation_id": inv, "findings_sha256": "a" * 64, "findings_schema_version": "uc042-investigation-findings/1.4",
               "decision": "ACCEPT", "comment": "", "rejection_reason": "", "reviewer_id": "analyst-1", "reviewer_name": "Test Analyst",
               "decided_at": "2026-11-17T10:00:00+00:00", "revision": 1, "supersedes_review_id": None, "submission_id": None}
        repo.append(dict(rec), 0)  # a historical period-level decision on the same artefact
        repo.append(dict(rec, analyst_review_id="AR-" + "2" * 24, submission_id=self.sub(a), decided_at="2026-11-17T11:00:00+00:00"), 0)
        h = self.get(f"/api/v1/packs/{a['result']['pack_id']}/exceptions/{e}/review-history").json()
        decisions = [x for x in h["events"] if x["kind"].startswith("ANALYST_DECISION_")]
        self.assertEqual(sorted((x["details"]["submission_id"] or "", x["details"]["active"]) for x in decisions),
                         [("", True), (self.sub(a), True)])  # each active in its own scope; neither supersedes the other
        self.assertEqual(h["active_submission_decisions"][self.sub(a)][inv]["analyst_review_id"], "AR-" + "2" * 24)
        jobs = [x for x in h["events"] if x["kind"] == "AI_INVESTIGATION_REQUESTED"]
        self.assertTrue(jobs and all(x["details"]["submission_id"] == self.sub(a) for x in jobs))
        del base


# ---------------------------------------------------------------------------------------------- Group E: API and status
class ApiAndStatus(IsolationCase):
    def test_submissions_response_is_typed(self):
        _, run = self.submitted(make_zip(FILES))
        spec = self.get("/openapi.json").json()
        schema = spec["paths"]["/api/v1/periods/{period_id}/submissions"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["type"], "array")
        self.assertIn("$ref", schema["items"])  # a declared model, not list[dict]
        model = spec["components"]["schemas"][schema["items"]["$ref"].rsplit("/", 1)[1]]
        self.assertTrue({"batch_id", "zip_sha256", "gate", "submissions"} <= set(model["properties"]))
        hist = self.get(f"/api/v1/periods/{PERIOD}/submissions").json()
        sub = hist[0]["submissions"][0]
        self.assertEqual((sub["submission_id"], sub["run_id"], sub["status"]), (self.sub(run), run["run_id"], "SUCCEEDED"))

    def test_invalid_and_unknown_submission_ids(self):
        _, run = self.submitted(make_zip(FILES))
        inv = next(iter(self.produced(run).values()))
        for url in (f"/api/v1/investigations/{inv}/analyst-reviews?submission_id=not-an-id",
                    "/api/v1/submissions/not-an-id/investigations/retry"):
            r = self.post(url, {"authorization": AI_OK}) if url.endswith("retry") else self.get(url)
            self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_ID"), url)
        unknown = "SUB-" + "0" * 24
        self.assertEqual(self.get(f"/api/v1/investigations/{inv}/analyst-reviews?submission_id={unknown}").status_code, 404)
        self.assertEqual(self.post(f"/api/v1/submissions/{unknown}/investigations/retry", {"authorization": AI_OK}).status_code, 404)
        self.assertEqual(self.post(f"/api/v1/packs/{run['result']['pack_id']}/reviews", {"submission_id": unknown}).status_code, 404)

    def test_submission_run_lookup_is_indexed_and_correct(self):
        data = make_zip(FILES)
        runs = [self.submitted(data)[1] for _ in range(3)]
        m = self.svc.monthly
        with mock.patch.object(m.repos.runs, "list", wraps=m.repos.runs.list) as scans:
            for r in runs:
                self.assertEqual(m.submission_run(self.sub(r))["run_id"], r["run_id"])
            self.assertLessEqual(scans.call_count, 1)  # at most the one scan that builds the index
            scans.reset_mock()
            for r in runs * 3:
                self.assertEqual(m.submission_run(self.sub(r))["run_id"], r["run_id"])
            self.assertIsNone(m.submission_run("SUB-" + "0" * 24))
            self.assertEqual(scans.call_count, 0)  # every further lookup is direct: no scan of every run
        self.restart()  # a fresh process: the index is rebuilt once, then every lookup is direct
        m = self.svc.monthly
        with mock.patch.object(m.repos.runs, "list", wraps=m.repos.runs.list) as scans:
            for r in runs:
                self.assertEqual(m.submission_run(self.sub(r))["run_id"], r["run_id"])
            self.assertLessEqual(scans.call_count, 1)

    def test_a_failed_resubmission_never_hides_an_earlier_success(self):
        d = self.upload_zip(make_zip(FILES))
        first = self.finish(self.submit(d["batch"]["batch_id"]))
        self.assertEqual(first["status"], "SUCCEEDED")
        with mock.patch("uc042app.services.monthly.build", return_value=("FAILED", None, None, None, ["ASSEMBLY: simulated"])):
            second = self.finish(self.submit(d["batch"]["batch_id"]))
        self.assertEqual(second["status"], "FAILED")
        batch = self.get(f"/api/v1/uploads/{d['batch']['batch_id']}").json()["batch"]
        self.assertEqual(batch["status"], "PROCESSED")  # derived from every run of the package: one succeeded
        self.assertEqual(self.get(f"/api/v1/periods/{PERIOD}").json()["period"]["status"], "PROCESSED")
        subs = {s["submission_id"]: s["status"] for p in self.get(f"/api/v1/periods/{PERIOD}/submissions").json() for s in p["submissions"]}
        self.assertEqual((subs[self.sub(first)], subs[self.sub(second)]), ("SUCCEEDED", "FAILED"))  # each outcome stays visible

    def test_each_submission_checklist_shows_only_its_own_state(self):
        data = make_zip(FILES)
        _, a = self.submitted(data)
        _, b = self.submitted(data)
        self.decide_all(a, "ACCEPT")
        ra, rb = self.open_review(a), self.open_review(b)
        rows_a = {r["exception_id"]: r for r in ra["readiness"]["checklist"]["exceptions"]}
        rows_b = {r["exception_id"]: r for r in rb["readiness"]["checklist"]["exceptions"]}
        pa, pb = self.produced(a), self.produced(b)
        for e in pa:
            self.assertEqual((rows_a[e]["ai_state"], rows_a[e]["disposition"], rows_a[e]["usable_investigations"]),
                             ("ACCEPTED", "ACCEPTED", [pa[e]]))
            self.assertEqual((rows_b[e]["ai_state"], rows_b[e]["disposition"], rows_b[e]["usable_investigations"]),
                             ("READY_FOR_REVIEW", "AWAITING_DECISION", [pb[e]]))
            self.assertEqual(rows_a[e]["ai_label"], "Accepted by analyst")
        # another submission's queued job never shows as this submission's state
        self.answers.hold = __import__("threading").Event()
        d_c = self.upload_zip(data)
        c = self.submit(d_c["batch"]["batch_id"])
        self.svc.runner.wait(c["job_id"], 180)
        rb2 = self.get(f"/api/v1/reviews/{rb['review_id']}").json()
        self.assertFalse([r for r in rb2["readiness"]["checklist"]["exceptions"] if r["ai_state"] in ("QUEUED", "IN_PROGRESS")])
        self.assertNotIn("INVESTIGATION_RUNNING", [x["code"] for x in rb2["readiness"]["blockers"]])
        self.answers.hold.set()
        c = self.get(f"/api/v1/processing-runs/{c['run_id']}").json()
        for i in c["result"]["auto_investigation"]["items"]:
            self.svc.runner.wait(i["job_id"], 120)


# ---------------------------------------------------------------------------------------------- Group F: continuity
class ContinuityStaysWithinItsWorkflow(Helpers, zs.ZipCase):
    """F3: previous-period continuity compares a legacy run with the previous period's legacy run only, and a ZIP submission
    run with the previous period's submission run only; the comparator is recorded (basis)."""
    LEGACY_ENTRY_POINTS = True  # historical-style legacy records next to ZIP submissions

    def setUp(self):
        super().setUp()
        self.provider.respond = lambda kw: (_ for _ in ()).throw(RuntimeError("provider unreachable (offline test)"))

    def test_continuity_never_crosses_workflows(self):
        from uc042lib.period import PeriodConfig
        m = self.svc.monthly
        october = PeriodConfig(2026, 10)
        # the previous period (September) has a ZIP submission only
        zip_run = self.finish(self.submit(self.upload_zip(make_zip(FILES))["batch"]["batch_id"]))
        case = m.store.cases_root / zip_run["result"]["case"]
        legacy = m._continuity(october, case, workflow="LEGACY")
        self.assertEqual(legacy["status"], "NOT_VERIFIABLE")  # never compared with the unrelated ZIP case
        self.assertEqual(legacy["basis"], {"workflow": "LEGACY", "previous_period": "PER-2026-09", "previous_run_id": None})
        sub = m._continuity(october, case, workflow="SUBMISSION")
        self.assertEqual(sub["basis"]["previous_run_id"], zip_run["run_id"])
        # a later legacy run of September is the legacy comparator; the submission comparator is unchanged
        b = self.legacy_upload(scenario_files(), expect=201).json()
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        legacy_run = self.finish(self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/process", {"ai_authorization": AI_OK}).json())
        self.assertEqual(legacy_run["status"], "SUCCEEDED", legacy_run)
        self.assertEqual(m._continuity(october, case, workflow="LEGACY")["basis"]["previous_run_id"], legacy_run["run_id"])
        self.assertEqual(m._continuity(october, case, workflow="SUBMISSION")["basis"]["previous_run_id"], zip_run["run_id"])
        # every run records the workflow its continuity was assessed in
        self.assertEqual(self.get(f"/api/v1/processing-runs/{zip_run['run_id']}").json()["result"]["continuity"]["basis"]["workflow"],
                         "SUBMISSION")
        self.assertEqual(legacy_run["result"]["continuity"]["basis"]["workflow"], "LEGACY")

if __name__ == "__main__":
    unittest.main()
