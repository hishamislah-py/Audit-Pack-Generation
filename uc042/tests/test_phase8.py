"""Phase 8: safe navigation, pre-execution AI authorisation, reassessment with verified original sources and lineage,
lineage-aware final-pack versions, investigation visibility, dashboard counts and the other functional corrections.

Disposable state only (temporary roots with COPIES of real packs, datasets, investigations and the February final pack;
a temporary SQLite database or the disposable PostgreSQL test database). Offline: the provider is the test mock and a
live provider is refused (api_support guards). No live AI call is made. ILLUSTRATIVE SYNTHETIC DATA."""
import threading
from unittest import mock
import unittest

from tests import TEST_DATABASE_URL
from tests.api_support import AI_OK, ApiCase, reset_test_database
from tests.final_pack_support import sha_tree
from tests.test_api_monthly import DATASETS, S05, S05_PACK, MonthlyCase, scenario_files
from tests.test_unification import (FEB_EXC, FEB_INV_REGISTERED, FEB_INV_UNREGISTERED, FEB_PACK, SC5A_EXC, SC5A_PACK,
                                    UnifiedBackendCase)
from uc042app.services.monthly import processing_limitation, processing_supported

CLEAN = DATASETS / "set_01_clean_baseline"
SC5A_URL = f"/api/v1/packs/{SC5A_PACK}/exceptions/{SC5A_EXC}/investigations"


def generate_final_pack(case, pack_id):
    """Open a review explicitly, preview (authorised; mock summary), GENERATE. Returns the final pack record."""
    s = case.post(f"/api/v1/packs/{pack_id}/reviews").json()
    j = case.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK})
    case.assertEqual(j.status_code, 202, j.text)
    case.assertEqual(case.wait_job(j.json()["job_id"])["status"], "COMPLETED")
    s = case.get(f"/api/v1/reviews/{s['review_id']}").json()
    r = case.post(f"/api/v1/reviews/{s['review_id']}/decision",
                  {"decision": "GENERATE", "comment": "phase 8 test", "snapshot_sha256": s["current_preview"]["snapshot_sha256"],
                   "acknowledgement_accepted": True, "acknowledged_summary_unavailable": True})
    case.assertEqual(r.status_code, 201, r.text)
    return r.json()["final_pack"]


# ============================================================================================ C: AI authorisation (file and SQL)
class AiAuthorization(ApiCase):
    def setUp(self):
        super().setUp()
        self.provider.investigate("SC5A", SC5A_EXC)

    def records(self, **f):
        return self.get("/api/v1/ai/confirmations" + ("?" + "&".join(f"{k}={v}" for k, v in f.items()) if f else "")).json()

    def test_no_job_and_no_model_call_without_an_explicit_confirmation(self):
        for body in ({"mode": "tools"}, {"mode": "tools", "authorization": {"confirmed": False}}):  # cancel = never confirmed
            r = self.post(SC5A_URL, body)
            self.assertEqual((r.status_code, r.json()["code"]), (422, "AUTHORIZATION_REQUIRED"))
            self.assertIn("configuration", r.json())  # what the dialog must show
        self.assertEqual((self.svc.repos.jobs.list(), self.provider.calls["investigation"], self.records()), ([], 0, []))

    def test_the_authorisation_is_recorded_before_the_model_is_called_and_stays_traceable(self):
        seen = []
        respond = self.provider.respond

        def checking(kw):  # at the moment of the model call, the authorisation must already exist, linked to the job
            seen.append([(r["result"], r["job_id"]) for r in self.svc.ai_authorizations.list(exception_id=SC5A_EXC)])
            return respond(kw)
        self.provider.respond = checking
        r = self.post(SC5A_URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        job = self.wait_job(r.json()["job_id"])
        self.assertEqual(job["status"], "COMPLETED", job)
        self.assertTrue(seen and seen[0] == [("AUTHORIZED", job["job_id"])], seen)
        rec = self.records(job_id=job["job_id"])[0]
        self.assertEqual((rec["operation"], rec["pack_id"], rec["exception_id"], rec["period_id"], rec["authorized_by"]),
                         ("INVESTIGATION", SC5A_PACK, SC5A_EXC, "PER-2026-09", self.svc.settings.analyst_id))
        self.assertEqual(job["authorization_id"], rec["authorization_id"])
        self.assertIn("may incur charges", rec["details"]["statement"])
        self.assertEqual(self.get(f"/api/v1/ai/confirmations/{rec['authorization_id']}").json(), rec)

    def test_repeated_clicks_never_start_a_second_job_and_each_refusal_is_recorded(self):
        self.provider.gate = threading.Event()
        first = self.post(SC5A_URL, {"mode": "tools", "authorization": AI_OK}).json()
        r = self.post(SC5A_URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"], r.json()["job_id"]), (409, "INVESTIGATION_ACTIVE", first["job_id"]))
        self.provider.gate.set()
        self.wait_job(first["job_id"])
        self.assertEqual(len(self.svc.repos.jobs.list()), 1)
        self.assertEqual([x["result"] for x in self.records(exception_id=SC5A_EXC)], ["AUTHORIZED", "REFUSED_INVESTIGATION_ACTIVE"])

    def test_missing_provider_and_changed_configuration_are_refused_clearly(self):
        from uc042lib.investigation.llm import LLMConfigurationError
        factory = self.svc.investigations.investigator_factory
        self.svc.investigations.investigator_factory = lambda: (_ for _ in ()).throw(LLMConfigurationError("no key (test)"))
        r = self.post(SC5A_URL, {"mode": "tools", "authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (503, "PROVIDER_NOT_CONFIGURED"))
        self.svc.investigations.investigator_factory = factory
        r = self.post(SC5A_URL, {"mode": "tools", "authorization": {"confirmed": True, "model": "a-model-never-shown"}})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "AI_CONFIGURATION_CHANGED"))
        self.assertEqual(self.svc.repos.jobs.list(), [])
        self.assertEqual([x["result"] for x in self.records()], ["REFUSED_PROVIDER_NOT_CONFIGURED", "REFUSED_AI_CONFIGURATION_CHANGED"])

    def test_an_interrupted_job_stays_traceable_to_its_authorisation(self):
        # The process "dies" right after the authorised job was submitted: the job never runs.
        with mock.patch.object(self.svc.runner, "submit", side_effect=lambda job, fn: job):
            job = self.post(SC5A_URL, {"mode": "tools", "authorization": AI_OK}).json()
        self.restart()  # start-up recovery: the job is interrupted, never re-run
        job = self.get(f"/api/v1/jobs/{job['job_id']}").json()
        self.assertEqual((job["status"], self.provider.calls["investigation"]), ("INTERRUPTED", 0))
        self.assertEqual(self.records(job_id=job["job_id"])[0]["authorization_id"], job["authorization_id"])

    def test_records_are_append_only(self):
        repo = self.svc.repos.ai_authorizations
        self.assertFalse([m for m in ("update", "delete", "save", "remove") if hasattr(repo, m)])

    def test_the_closing_summary_needs_its_own_authorisation(self):
        s = self.post(f"/api/v1/packs/{SC5A_PACK}/reviews").json()
        r = self.post(f"/api/v1/reviews/{s['review_id']}/preview")
        self.assertEqual((r.status_code, r.json()["code"]), (422, "AUTHORIZATION_REQUIRED"))
        self.assertEqual((self.provider.calls["summary"], self.svc.repos.jobs.list()), (0, []))
        job = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK}).json()
        self.assertEqual(self.wait_job(job["job_id"])["status"], "COMPLETED")
        rec = self.records(review_id=s["review_id"])
        self.assertEqual([(x["operation"], x["result"], x["job_id"]) for x in rec], [("CLOSING_SUMMARY", "AUTHORIZED", job["job_id"])])
        self.assertTrue(rec[0]["details"]["model_call_expected"])
        self.assertEqual(self.provider.calls["summary"], 1)

    def test_without_a_provider_the_summary_is_unavailable_and_the_authorisation_says_so(self):
        from uc042lib.investigation.llm import LLMConfigurationError
        s = self.post(f"/api/v1/packs/{SC5A_PACK}/reviews").json()
        self.svc.reviews.investigator_factory = lambda: (_ for _ in ()).throw(LLMConfigurationError("no key (test)"))
        job = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK}).json()
        self.assertEqual(self.wait_job(job["job_id"])["status"], "COMPLETED")
        s = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertEqual(s["current_preview"]["closing_summary"]["status"], "UNAVAILABLE")
        self.assertFalse(self.records(review_id=s["review_id"])[0]["details"]["model_call_expected"])

    def test_configuration_endpoint_shows_what_is_authorised(self):
        c = self.get("/api/v1/ai/configuration").json()
        self.assertEqual(set(c["statements"]), {"INVESTIGATION", "CLOSING_SUMMARY"})
        self.assertIn("charges", c["charges_notice"])


@unittest.skipUnless(TEST_DATABASE_URL, "UC042_TEST_DATABASE_URL is not set")
class AiAuthorizationImmutableInPostgres(unittest.TestCase):
    def test_update_and_delete_are_refused_by_the_database(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from uc042app.db import make_engine, make_sessions
        from uc042app.db.repositories import SqlRepositories
        reset_test_database(TEST_DATABASE_URL)
        engine = make_engine(TEST_DATABASE_URL)
        try:
            repo = SqlRepositories(make_sessions(engine)).ai_authorizations
            rec = repo.record({"authorization_id": "AIA-" + "a" * 24, "operation": "INVESTIGATION", "result": "AUTHORIZED",
                               "period_id": "PER-2026-09", "pack_id": SC5A_PACK, "exception_id": SC5A_EXC, "review_id": None,
                               "case_id": None, "job_id": "JOB-" + "b" * 24, "provider": "openai", "model": "m", "authorized_by": "a",
                               "authorized_at": "2026-11-04T12:00:00+00:00", "details": {}})
            for sql in ("UPDATE audit.ai_execution_authorizations SET result = 'X'", "DELETE FROM audit.ai_execution_authorizations"):
                with self.assertRaises(DBAPIError):
                    with engine.begin() as conn:
                        conn.execute(text(sql))
            self.assertEqual(repo.get(rec["authorization_id"])["result"], "AUTHORIZED")
        finally:
            engine.dispose()
            reset_test_database(TEST_DATABASE_URL)


# ============================================================================================ B: reviews are opened explicitly
class ExplicitReviews(MonthlyCase):
    def sessions(self):
        return self.svc.repos.reviews.list(S05_PACK)

    def test_reading_never_creates_a_review_and_opening_creates_exactly_one(self):
        for url in (f"/api/v1/reviews?pack_id={S05_PACK}", "/api/v1/reviews", f"/api/v1/packs/{S05_PACK}",
                    f"/api/v1/final-packs?pack_id={S05_PACK}&lineage=true", "/api/v1/periods/PER-2026-09"):
            self.assertEqual(self.get(url).status_code, 200, url)
            self.get(url)  # a refresh
        self.assertEqual(self.sessions(), [])
        r = self.post(f"/api/v1/packs/{S05_PACK}/reviews")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.post(f"/api/v1/packs/{S05_PACK}/reviews").status_code, 200)  # the active session, not a second
        self.assertEqual(len(self.sessions()), 1)
        opened = [a for a in self.svc.repos.activity.recent(entity_type="review", entity_id=r.json()["review_id"])]
        self.assertEqual([a["action"] for a in opened], ["REVIEW_OPENED"])
        self.assertEqual((opened[0]["details"]["period_id"], opened[0]["details"]["pack_id"]), ("PER-2026-09", S05_PACK))

    def test_a_generated_review_is_never_replaced_by_reading_and_hold_generate_are_logged(self):
        fp = generate_final_pack(self, S05_PACK)
        for url in (f"/api/v1/reviews?pack_id={S05_PACK}", f"/api/v1/reviews/{self.sessions()[0]['review_id']}"):
            self.get(url)
        self.assertEqual([s["status"] for s in self.sessions()], ["GENERATED"])
        actions = [a["action"] for a in self.svc.repos.activity.recent(entity_type="review")]
        self.assertTrue({"REVIEW_OPENED", "PREVIEW_REQUESTED", "REVIEW_GENERATED"} <= set(actions), actions)
        generated = next(a for a in self.svc.repos.activity.recent(entity_type="review") if a["action"] == "REVIEW_GENERATED")
        self.assertEqual(generated["details"]["final_pack_id"], fp["final_pack_id"])


# ============================================================================================ D: reassessment and lineage
class ReassessmentLineage(MonthlyCase):
    """An uploaded month: INITIAL processing, a published v1, a correction, a reassessment, a v2 superseding v1."""

    def test_correction_reassessment_lineage_and_v2_superseding_v1(self):
        b = self.upload("PER-2026-09", scenario_files(CLEAN))
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        run = self.process(b["batch"]["batch_id"])
        self.assertEqual(run["status"], "SUCCEEDED", run)
        first_pack = run["result"]["pack_id"]
        v1 = generate_final_pack(self, first_pack)
        self.assertEqual((v1["version"], v1["supersedes_final_pack_id"]), (1, None))
        v1_bytes = sha_tree(self.svc.final_packs.root_for(first_pack) / v1["final_pack_id"])
        r = self.post("/api/v1/periods/PER-2026-09/reconciliation", {"purpose": "REASSESSMENT", "reason": "nothing new"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NOTHING_TO_REASSESS"))
        # A correction of the bank statement entries (IN-09): the same month's file from the S05 data set.
        docs = self.get("/api/v1/periods/PER-2026-09").json()["documents"]
        in09 = next(d for d in docs if d["evidence_id"] == "IN-09" and d["batch_id"] == b["batch"]["batch_id"])
        name = "bank_statement_entries_2026-09.csv"
        r = self.client.post("/api/v1/periods/PER-2026-09/uploads",
                             data={"submission_kind": "CORRECTION", "reason": "corrected bank statement entries from the bank",
                                   "replaces_document_id": in09["document_id"]},
                             files=[("files", ("bank_statement_entries_corrected.csv", (S05 / "source_data" / name).read_bytes(),
                                               "text/csv"))])
        self.assertEqual(r.status_code, 201, r.text)
        corr = r.json()
        for d in corr["documents"]:
            if d["checks"].get("decision_required"):
                self.post(f"/api/v1/documents/{d['document_id']}/review", {"decision": "INCLUDE", "comment": "the corrected file"})
        self.assertEqual(self.post(f"/api/v1/uploads/{corr['batch']['batch_id']}/confirm").status_code, 200)
        r = self.post(f"/api/v1/uploads/{corr['batch']['batch_id']}/process")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "REASSESSMENT_REQUIRED"))
        plan = self.get("/api/v1/periods/PER-2026-09/reassessment").json()
        self.assertTrue(plan["can_reassess"], plan["blockers"])
        self.assertIsNone(plan["baseline"])  # an uploaded month: its latest confirmed documents are the set
        self.assertEqual(plan["effective_set"]["IN-09"]["document_id"], corr["documents"][0]["document_id"])
        r = self.post("/api/v1/periods/PER-2026-09/reconciliation", {"purpose": "REASSESSMENT", "reason": "bank correction"})
        self.assertEqual(r.status_code, 202, r.text)
        self.svc.runner.wait(r.json()["job_id"], timeout=180)
        run = self.get(f"/api/v1/processing-runs/{r.json()['run_id']}").json()
        self.assertEqual((run["status"], run["result"]["predecessor_pack_id"]), ("SUCCEEDED", first_pack), run)
        second_pack = run["result"]["pack_id"]
        self.assertNotEqual(second_pack, first_pack)
        lineage = self.get("/api/v1/periods/PER-2026-09/lineage").json()
        self.assertEqual([(x["pack_id"], x["predecessor_pack_id"], x["lineage_root_pack_id"]) for x in lineage],
                         [(second_pack, first_pack, first_pack)])
        self.assertIn("IN-09", lineage[0]["change_summary"]["inputs_changed"])
        refs = {x["pack_id"]: x for x in self.get("/api/v1/periods/PER-2026-09").json()["period"]["packs"]}
        self.assertEqual(refs[second_pack]["predecessor_pack_id"], first_pack)
        v2 = generate_final_pack(self, second_pack)
        self.assertEqual((v2["version"], v2["supersedes_final_pack_id"]), (2, v1["final_pack_id"]))
        versions = self.get(f"/api/v1/final-packs?pack_id={second_pack}&lineage=true").json()
        self.assertEqual([(f["version"], f["pack_id"]) for f in versions], [(1, first_pack), (2, second_pack)])
        self.assertEqual(sha_tree(self.svc.final_packs.root_for(first_pack) / v1["final_pack_id"]), v1_bytes)  # v1 untouched
        self.assertTrue(self.get(f"/api/v1/final-packs/{v1['final_pack_id']}/verify").json()["verified"])
        # After v2, nothing is pending: the documents precede it (times compared as instants, whatever their UTC offset).
        plan = self.get("/api/v1/periods/PER-2026-09/reassessment").json()
        self.assertEqual((plan["latest_final_pack_id"], plan["new_documents"], plan["pending_reassessment"]), (v2["final_pack_id"], [], False))

    def test_independent_scenarios_keep_separate_version_sequences(self):
        generate_final_pack(self, S05_PACK)
        other = next(p["pack_id"] for p in self.get("/api/v1/periods/PER-2026-09").json()["period"]["packs"] if p["pack_id"] != S05_PACK)
        self.assertEqual(self.svc.final_packs.next_version(other), (1, None))
        self.assertEqual(self.svc.final_packs.lineage_packs(S05_PACK), [S05_PACK])
        self.assertEqual(self.svc.final_packs.next_version(S05_PACK)[0], 2)


class HistoricalReassessment(UnifiedBackendCase):
    def test_letters_match_the_verified_pack_inventory_and_mismatches_stay_errors(self):
        letters = sorted((self.profile_roots["datasets"] / "2026-02" / "supporting_documents").glob("ack_letter_*.pdf"))
        r = self.client.post("/api/v1/periods/PER-2026-02/uploads",
                             data={"submission_kind": "ADDITIONAL_EVIDENCE", "reason": "re-sent acknowledgement letter"},
                             files=[("files", (letters[0].name, letters[0].read_bytes(), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        doc = r.json()["documents"][0]
        codes = {m["code"] for m in doc["checks"]["messages"]}
        self.assertNotIn("LETTER_NOT_MATCHED", codes)
        self.assertIn(doc["evidence_id"], ("IN-15", "IN-16"))
        self.assertIn(FEB_PACK, doc["checks"]["slot_resolved_by"])
        # September holds two independent scenario packs: no single inventory, so a letter is not assigned by guesswork.
        r = self.client.post("/api/v1/periods/PER-2026-09/uploads",
                             data={"submission_kind": "ADDITIONAL_EVIDENCE", "reason": "letter"},
                             files=[("files", (letters[0].name, letters[0].read_bytes(), "application/pdf"))])
        self.assertIn("LETTER_NOT_MATCHED", {m["code"] for m in r.json()["documents"][0]["checks"]["messages"]})
        self.assert_history_unchanged()

    def test_a_baseline_file_that_does_not_verify_stops_the_reassessment(self):
        extra = self.client.post("/api/v1/periods/PER-2026-02/uploads",
                                 data={"submission_kind": "ADDITIONAL_EVIDENCE", "reason": "bank e-mail"},
                                 files=[("files", ("bank_email.pdf", b"%PDF-1.4 synthetic e-mail", "application/pdf"))]).json()
        self.post(f"/api/v1/uploads/{extra['batch']['batch_id']}/confirm")
        target = self.profile_roots["datasets"] / "2026-02" / "source_data" / "account_inventory.csv"
        target.write_bytes(target.read_bytes() + b"\n")  # a copy in the temporary profile, never the original
        plan = self.get("/api/v1/periods/PER-2026-02/reassessment").json()
        self.assertFalse(plan["can_reassess"])
        self.assertTrue(any("IN-02" in p for p in plan["baseline_problems"]), plan)
        r = self.post("/api/v1/periods/PER-2026-02/reconciliation", {"purpose": "REASSESSMENT", "reason": "bank e-mail"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "BASELINE_UNVERIFIABLE"))
        self.assertEqual([r for p in self.svc.monthly.repos.periods.list() for r in self.svc.monthly.repos.runs.list(period_id=p["period_id"])], [])

    # ---------------------------------------------------------------------------------------- F, G, I on February
    def test_investigation_detail_tool_calls_and_snapshot_eligibility(self):
        self.register_feb()
        calls = self.get(f"/api/v1/investigations/{FEB_INV_REGISTERED}/tool-calls").json()
        self.assertEqual(len(calls["tool_calls"]), 8)
        self.assertTrue(all({"tool", "status", "evidence_ids"} <= set(c) for c in calls["tool_calls"]))
        s = self.post(f"/api/v1/packs/{FEB_PACK}/reviews").json()
        job = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK}).json()
        self.assertEqual(self.wait_job(job["job_id"])["status"], "COMPLETED")
        s = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        doc = self.get(f"/api/v1/reviews/{s['review_id']}/preview/json?snapshot={s['current_preview']['snapshot_sha256']}").json()
        other = doc["exception_register"][0]["investigation"]["other_attempts"]
        self.assertEqual((other["published_not_selected"], other["published_ineligible"]), ([], [FEB_INV_UNREGISTERED]))

    def test_dashboard_counts_come_from_the_records(self):
        self.register_feb()
        d = self.get("/api/v1/dashboard?period_id=PER-2026-02").json()
        self.assertEqual((d["packs"], d["exceptions"], d["exceptions_with_eligible_investigation"]), (1, 1, 1))
        self.assertEqual({k: d["investigations"][k] for k in ("published", "eligible", "unregistered", "running")},
                         {"published": 1, "eligible": 1, "unregistered": 1, "running": 0})
        self.assertEqual((d["final_packs_period"], d["final_packs_global"]), (1, 1))
        d = self.get("/api/v1/dashboard?period_id=PER-2026-09").json()
        self.assertEqual((d["final_packs_period"], d["final_packs_global"]), (0, 1))  # the global total is labelled global

    def test_the_month_exception_overview_is_one_read_only_response(self):
        self.register_feb()
        jobs = self.svc.runner.repo.list()
        rows = self.get("/api/v1/periods/PER-2026-02/exception-overview").json()
        self.assertEqual([r["pack_id"] for r in rows], [FEB_PACK])
        self.assertEqual([x["exception_id"] for x in rows[0]["exceptions"]], [FEB_EXC])
        self.assertEqual({i["investigation_id"]: i["eligible"] for i in rows[0]["investigations"][0]["published"]},
                         {FEB_INV_REGISTERED: True, FEB_INV_UNREGISTERED: False})
        self.assertEqual(self.svc.runner.repo.list(), jobs)

    def test_source_evidence_is_inspectable_without_ai(self):
        before = (self.provider.calls["investigation"], self.svc.runner.repo.list())
        ev = self.get(f"/api/v1/packs/{FEB_PACK}/exceptions/{FEB_EXC}/source-evidence").json()
        self.assertEqual(ev["source"], "deterministic_retrieval")
        self.assertGreater(ev["total_records"], 0)
        self.assertTrue(all(r["evidence_id"].startswith("IN-") for r in ev["source_records"]))
        # Provenance: every record is a line of an approved source file of THIS pack, with that file's registered hash.
        register = {f["evidence_id"]: f for f in self.svc.packs.load(FEB_PACK)["evidence_register"]["files"]}
        for r in ev["source_records"]:
            self.assertRegex(r["source_file"], r"^(source_data/[^/]+\.csv|supporting_documents/[^/]+\.pdf)$")
            self.assertEqual(r["file_sha256"], register[r["file_id"]]["sha256"], r["evidence_id"])
            self.assertTrue(r.get("source_line"))
            self.assertFalse(str(r.get("retrieved_via", "")).startswith("tool "))  # engine retrieval, never an AI tool call
        self.assertEqual((self.provider.calls["investigation"], self.svc.runner.repo.list()), before)
        self.assert_history_unchanged()


class Corrections(MonthlyCase):
    def test_header_only_files_need_no_cross_month_decision(self):
        for period in ("PER-2026-08", "PER-2026-07"):
            self.open_period(2026, int(period[-2:]))
        log = next(n for n, _ in scenario_files() if n.startswith("discrepancy_log"))
        data = dict(scenario_files())[log]
        header = data.splitlines(keepends=True)[0]
        first = self.upload("PER-2026-08", [("discrepancy_log_2026-08.csv", header)])
        second = self.upload("PER-2026-07", [("discrepancy_log_2026-07.csv", header)])
        doc = second["documents"][0]
        codes = {m["code"] for m in doc["checks"]["messages"]}
        if doc["evidence_id"]:  # identified as IN-14 with no records
            self.assertIn("HEADER_ONLY_SAME_AS_OTHER_PERIOD", codes)
            self.assertNotIn("SAME_CONTENT_AS_OTHER_PERIOD", codes)
            self.assertFalse(doc["checks"].get("decision_required"))
        self.assertTrue(first["documents"])

    def test_processing_support_follows_policy_coverage(self):
        self.assertTrue(processing_supported("PER-2026-02"))
        self.assertFalse(processing_supported("PER-2025-06"))
        self.assertIn("policy", processing_limitation("PER-2025-06"))
        self.assertIsNone(processing_limitation("PER-2026-09"))


if __name__ == "__main__":
    unittest.main()
