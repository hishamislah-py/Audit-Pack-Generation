"""Automatic AI investigation after an authorised reconciliation run (and for an existing pack): one recorded authorisation,
one job per applicable exception through the existing InvestigationService / LangGraph graph, per-exception outcomes,
failure isolation, no automatic retry of refused requests, explicit retry, idempotency, the case entry point and the
processing-run trigger. Run from uc042/: python -m unittest tests.test_auto_investigations -v

Offline CONTROLLED FIXTURES: the provider is the real OpenAIInvestigator with its HTTP client mocked (MockProvider-style),
answering per exception. These are not real provider calls."""
import json

import httpx2
import openai

from tests.api_support import AI_OK, ApiCase
from tests.final_pack_support import PACK, investigation_output, raw
from tests.test_api_monthly import MonthlyCase, scenario_files
from tests.view_fixtures import packet_from_message

REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def too_large():
    return openai.APIStatusError("Request too large for model on tokens per minute (TPM): Limit 8000, Requested 26406",
                                 response=httpx2.Response(413, request=REQ), body={"code": "rate_limit_exceeded"})


class PerException:
    """Answers each investigation request by the exception named in its packet: a valid output, or an exception."""

    def __init__(self, provider, scenario):
        self.scenario, self.answers, self.calls = scenario, {}, {}
        provider.respond = self.respond

    def respond(self, kw):
        # the exception under investigation is the packet's own "exception" (its group lists the related ones too)
        content = kw["input"][0]["content"]
        packet = packet_from_message(content)
        exc = packet["exception"]["exception_id"]
        self.calls[exc] = self.calls.get(exc, 0) + 1
        answer = self.answers.get(exc, ("error", openai.APIConnectionError(request=REQ)))
        if answer[0] == "error":
            raise answer[1]
        return raw(investigation_output(self.scenario, exc))


class AutoCase(ApiCase):
    def start(self, scenario, body=None, expect=202):
        r = self.post(f"/api/v1/packs/{PACK[scenario]}/auto-investigations", body if body is not None else {"authorization": AI_OK})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def finish(self, result):
        for i in result["items"]:
            if i.get("job_id"):
                self.wait_job(i["job_id"], 120)

    def status(self, scenario):
        return self.get(f"/api/v1/packs/{PACK[scenario]}/auto-investigations").json()

    def jobs(self, scenario):
        return [j for j in self.svc.runner.repo.list(pack_id=PACK[scenario]) if j["operation"] == "INVESTIGATION"]


class Orchestration(AutoCase):
    def test_1_zero_exceptions_zero_jobs(self):
        res = self.start("S01")
        self.assertEqual((res["items"], self.jobs("S01")), ([], []))

    def test_2_one_exception_one_job_validated_and_registered(self):
        p = PerException(self.provider, "SC2")
        p.answers["EXC-SC2-01"] = ("ok",)
        res = self.start("SC2")
        self.assertEqual([(i["exception_id"], i["outcome"]) for i in res["items"]], [("EXC-SC2-01", "QUEUED")])
        self.finish(res)
        job = self.get(f"/api/v1/jobs/{res['items'][0]['job_id']}").json()
        self.assertEqual((job["status"], job["result"]["registered"], job["result"]["validation_status"]), ("COMPLETED", True, "VALID"))
        st = self.status("SC2")["exceptions"][0]
        self.assertEqual((st["state"], st["label"], st["exception_resolution"]), ("READY_FOR_REVIEW", "Findings ready for review", "UNRESOLVED"))
        self.assertEqual(self.get(f"/api/v1/packs/{PACK['SC2']}/exceptions/EXC-SC2-01").json()["exception"]["status"], "OPEN")

    def test_3_6_multiple_exceptions_each_accounted_one_failure_does_not_stop_the_others(self):
        p = PerException(self.provider, "SC3C")
        p.answers.update({"EXC-SC3C-01": ("ok",), "EXC-SC3C-02": ("error", openai.APIConnectionError(request=REQ)), "EXC-SC3C-03": ("ok",)})
        res = self.start("SC3C")
        self.assertEqual(sorted((i["exception_id"], i["outcome"]) for i in res["items"]),
                         [("EXC-SC3C-01", "QUEUED"), ("EXC-SC3C-02", "QUEUED"), ("EXC-SC3C-03", "QUEUED")])
        self.assertEqual(len({i["job_id"] for i in res["items"]}), 3)
        self.finish(res)
        st = {e["exception_id"]: e for e in self.status("SC3C")["exceptions"]}
        self.assertEqual(st["EXC-SC3C-01"]["state"], "READY_FOR_REVIEW")
        self.assertEqual(st["EXC-SC3C-03"]["state"], "READY_FOR_REVIEW")
        self.assertEqual(st["EXC-SC3C-02"]["state"], "FAILED")
        self.assertIn("connect", st["EXC-SC3C-02"]["job"]["error_summary"])  # the exact reason is kept
        self.assertEqual(self.get(f"/api/v1/packs/{PACK['SC3C']}/exceptions/EXC-SC3C-02/investigations").json()["published"], [])  # 5
        self.assertEqual(res["summary"], {"QUEUED": 3})
        if self.svc.repos.activity is not None:  # with the database: the per-exception outcomes are in the activity log
            events = self.svc.repos.activity.recent(entity_type="pack", entity_id=PACK["SC3C"])
            self.assertEqual([i["exception_id"] for i in events[0]["details"]["items"]], ["EXC-SC3C-01", "EXC-SC3C-02", "EXC-SC3C-03"])

    def test_7_token_limit_rejection_is_not_retried_and_nothing_is_cut(self):
        p = PerException(self.provider, "SC2")
        p.answers["EXC-SC2-01"] = ("error", too_large())
        res = self.start("SC2")
        self.finish(res)
        job = self.get(f"/api/v1/jobs/{res['items'][0]['job_id']}").json()
        self.assertEqual(job["status"], "FAILED")
        self.assertIn("request_too_large", job["error_summary"])
        self.assertEqual(p.calls["EXC-SC2-01"], 1)  # one request: no automatic retry of a refused request
        again = self.start("SC2")  # a second automatic run does not re-send it either
        self.assertEqual([i["outcome"] for i in again["items"]], ["PREVIOUS_ATTEMPT_FAILED"])
        self.assertEqual(p.calls["EXC-SC2-01"], 1)

    def test_8_explicit_retry_after_capacity_is_available(self):
        p = PerException(self.provider, "SC2")
        p.answers["EXC-SC2-01"] = ("error", too_large())
        first = self.start("SC2")
        self.finish(first)
        p.answers["EXC-SC2-01"] = ("ok",)
        retry = self.start("SC2", {"authorization": AI_OK, "retry": True})
        self.assertEqual(retry["items"][0]["outcome"], "QUEUED")
        self.finish(retry)
        job = self.get(f"/api/v1/jobs/{retry['items'][0]['job_id']}").json()
        self.assertEqual((job["status"], job["retry_of"]), ("COMPLETED", first["items"][0]["job_id"]))
        self.assertEqual(self.status("SC2")["exceptions"][0]["state"], "READY_FOR_REVIEW")

    def test_9_repeated_requests_create_no_duplicate_jobs(self):
        p = PerException(self.provider, "SC2")
        p.answers["EXC-SC2-01"] = ("ok",)
        from tests.api_support import gate
        self.provider.gate = gate()
        orig = p.respond

        def held(kw):
            self.provider.gate.wait(30)
            return orig(kw)
        self.provider.respond = held
        first = self.start("SC2")
        second = self.start("SC2")
        self.assertEqual(second["items"][0]["outcome"], "ALREADY_ACTIVE")
        self.assertEqual(second["items"][0]["job_id"], first["items"][0]["job_id"])
        # 11: the case entry point (CaseService.request_ai) calls this same InvestigationService.start, whose
        # one-active-job guard refuses a second job (cases need the database; the guard is exercised directly here)
        from uc042app.errors import Conflict
        with self.assertRaises(Conflict) as e:
            self.svc.investigations.start(PACK["SC2"], "EXC-SC2-01", confirmation=AI_OK, case_id="CASE-test")
        self.assertEqual(e.exception.code, "INVESTIGATION_ACTIVE")
        r = self.post(f"/api/v1/packs/{PACK['SC2']}/exceptions/EXC-SC2-01/investigations", {"authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "INVESTIGATION_ACTIVE"))  # the manual entry point too
        self.provider.gate.set()
        self.finish(first)
        third = self.start("SC2")
        self.assertEqual(third["items"][0]["outcome"], "ALREADY_INVESTIGATED")
        self.assertEqual(len(self.jobs("SC2")), 1)

    def test_authorisation_is_required_recorded_and_linked(self):
        r = self.post(f"/api/v1/packs/{PACK['SC2']}/auto-investigations", {})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "AUTHORIZATION_REQUIRED"))
        self.assertEqual(self.jobs("SC2"), [])
        PerException(self.provider, "SC2").answers["EXC-SC2-01"] = ("ok",)
        res = self.start("SC2")
        self.finish(res)
        rec = self.get(f"/api/v1/ai/confirmations/{res['authorization_id']}").json()
        self.assertEqual((rec["operation"], rec["result"], rec["pack_id"], rec["period_id"], rec["authorized_by"]),
                         ("AUTO_INVESTIGATION", "AUTHORIZED", PACK["SC2"], "PER-2026-09", "analyst-1"))
        self.assertIn("automatic AI investigations", rec["details"]["statement"])
        job = self.get(f"/api/v1/jobs/{res['items'][0]['job_id']}").json()
        self.assertEqual(job["authorization_id"], res["authorization_id"])


class AfterReconciliationRun(MonthlyCase):
    def confirmed(self):
        b = self.upload("PER-2026-09", scenario_files())
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        return b["batch"]["batch_id"]

    def run_processing(self, batch_id, body):
        r = self.post(f"/api/v1/uploads/{batch_id}/process", body)
        self.assertEqual(r.status_code, 202, r.text)
        self.svc.runner.wait(r.json()["job_id"], timeout=180)
        return self.get(f"/api/v1/processing-runs/{r.json()['run_id']}").json()

    def test_10_authorised_run_enqueues_every_exception_of_its_new_pack_only(self):
        self.provider.respond = lambda kw: (_ for _ in ()).throw(openai.APIConnectionError(request=REQ))
        batch = self.confirmed()
        run = self.run_processing(batch, {"ai_authorization": AI_OK})
        self.assertEqual(run["status"], "SUCCEEDED", run)
        pack_id, auto = run["result"]["pack_id"], run["result"]["auto_investigation"]
        exceptions = [x["exception_id"] for x in self.get(f"/api/v1/packs/{pack_id}/exceptions").json()]
        self.assertTrue(len(exceptions) >= 2)
        self.assertEqual((auto["status"], sorted(i["exception_id"] for i in auto["items"])), ("ENQUEUED", sorted(exceptions)))
        self.assertTrue(all(i["outcome"] == "QUEUED" for i in auto["items"]))
        rec = self.get(f"/api/v1/ai/confirmations/{auto['authorization_id']}").json()
        self.assertEqual((rec["operation"], rec["pack_id"], rec["details"]["processing_run_id"]), ("AUTO_INVESTIGATION", "", run["run_id"]))
        for i in auto["items"]:
            self.svc.runner.wait(i["job_id"], 120)
        jobs = [j for j in self.svc.runner.repo.list() if j["operation"] == "INVESTIGATION"]
        self.assertEqual({j["pack_id"] for j in jobs}, {pack_id})  # no job for the original scenario packs
        self.assertTrue(all(self.get(f"/api/v1/packs/{pack_id}/exceptions/{e}/investigations").json()["published"] == [] for e in exceptions))
        # the same document set again: the identical pack (ALREADY_EXISTS) gets no duplicate jobs
        again = self.run_processing(batch, {"ai_authorization": AI_OK})
        self.assertEqual(again["result"]["pack_id"], pack_id)
        self.assertTrue(all(i["outcome"] == "PREVIOUS_ATTEMPT_FAILED" for i in again["result"]["auto_investigation"]["items"]))
        self.assertEqual(len([j for j in self.svc.runner.repo.list() if j["operation"] == "INVESTIGATION"]), len(jobs))

    def test_investigation_is_mandatory_no_opt_in_needed(self):
        """Every run investigates its pack: the processing confirmation is the run-level authorisation (no checkbox, no
        second step). It is recorded, with the policy and whether the disclosure was shown."""
        self.provider.respond = lambda kw: (_ for _ in ()).throw(openai.APIConnectionError(request=REQ))
        run = self.run_processing(self.confirmed(), None)  # no ai_authorization at all
        self.assertEqual(run["status"], "SUCCEEDED")
        auto = run["result"]["auto_investigation"]
        self.assertEqual((auto["status"], auto["policy"]), ("ENQUEUED", "MANDATORY_AUTO_INVESTIGATION"))
        exceptions = [x["exception_id"] for x in self.get(f"/api/v1/packs/{run['result']['pack_id']}/exceptions").json()]
        self.assertEqual(sorted(i["exception_id"] for i in auto["items"] if i["outcome"] == "QUEUED"), sorted(exceptions))
        rec = self.get(f"/api/v1/ai/confirmations/{auto['authorization_id']}").json()
        self.assertEqual((rec["operation"], rec["result"], rec["details"]["basis"], rec["details"]["policy"], rec["details"]["disclosure_shown"]),
                         ("AUTO_INVESTIGATION", "AUTHORIZED", "PROCESSING_CONFIRMATION", "MANDATORY_AUTO_INVESTIGATION", False))
        for i in auto["items"]:
            self.svc.runner.wait(i["job_id"], 120)

    def test_without_a_provider_the_configuration_problem_is_visible_never_skipped_silently(self):
        from uc042lib.investigation.llm import LLMConfigurationError

        def unconfigured():
            raise LLMConfigurationError("OPENAI_API_KEY is not set")
        self.svc.investigations.investigator_factory = unconfigured
        run = self.run_processing(self.confirmed(), {"ai_authorization": AI_OK})
        self.assertEqual(run["status"], "SUCCEEDED")  # the deterministic result never depends on AI
        auto = run["result"]["auto_investigation"]
        self.assertEqual(auto["status"], "NOT_STARTED")
        self.assertIn("AI investigations cannot run", auto["error"])
        self.assertNotIn("items", auto)  # nothing reported as investigated
        self.assertEqual([j for j in self.svc.runner.repo.list() if j["operation"] == "INVESTIGATION"], [])
        rec = self.get(f"/api/v1/ai/confirmations/{auto['authorization_id']}").json()
        self.assertTrue(rec["result"].startswith("REFUSED_"), rec)  # the refusal is recorded
        st = self.get(f"/api/v1/packs/{run['result']['pack_id']}/auto-investigations").json()
        self.assertTrue(st["can_start"])  # the explicit action stays available once AI is configured

    def test_a_configuration_changed_since_the_confirmation_refuses_processing(self):
        batch = self.confirmed()
        r = self.post(f"/api/v1/uploads/{batch}/process", {"ai_authorization": dict(AI_OK, model="another-model")})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "AI_CONFIGURATION_CHANGED"))
        self.assertEqual(self.get(f"/api/v1/uploads/{batch}").json()["batch"]["status"], "CONFIRMED")  # no run started
