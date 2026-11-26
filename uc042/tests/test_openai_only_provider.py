"""OpenAI is the only live provider of UC-042 (Groq and the automatic provider fallback were removed on 12 Nov 2026).
Replaces tests/test_provider_fallback.py. Run from uc042/: python -m unittest tests.test_openai_only_provider -v

Offline: the real OpenAIInvestigator with its HTTP client mocked; provider failures are the real openai exception classes
(SIMULATED failures for repeatable tests, not live provider results). What is checked:
  * the factory always builds a plain OpenAIInvestigator, even when legacy fallback variables are still set, and only one
    HTTP client (OpenAI's, default base URL) is ever constructed;
  * "groq" is no longer an accepted provider;
  * every availability failure (exhausted credits / 429, timeout, connection, 5xx) is reported as it is: one request,
    no switch, no second provider, and an investigation fails visibly instead of publishing;
  * the closing summary fails the same way (no fallback text, no other provider);
  * the AI configuration API carries no fallback, and a confirmation dialog that still showed a fallback is refused."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx2
import openai

from tests.api_support import AI_OK, ApiCase
from tests.final_pack_support import PACK as FP_PACK
from tests.test_tool_calling import LIMITS, PACK, Temp
from uc042lib.investigation import config, llm
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import LLMCallError, LLMConfigurationError, OpenAIInvestigator, investigator_from_env

REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")
KEY = {config.ENV_OPENAI_KEY: "sk-test-NOT-REAL-0000"}
LEGACY_FALLBACK_ENV = {"UC042_LLM_FALLBACK_PROVIDER": "groq", "UC042_LLM_FALLBACK_MODEL": "openai/gpt-oss-120b",
                       "GROQ_API_KEY": "gsk_test_NOT_REAL_0000", "GROQ_BASE_URL": "https://api.groq.com/openai/v1"}


def credit_exhausted():
    return openai.RateLimitError("You have no credits remaining.", response=httpx2.Response(429, request=REQ),
                                 body={"message": "You have no credits remaining.", "code": "credit_balance_exhausted"})


def availability_failures():
    return [("rate_limit", credit_exhausted()), ("timeout", openai.APITimeoutError(request=REQ)),
            ("connection", openai.APIConnectionError(request=REQ)),
            ("provider_unavailable", openai.InternalServerError("down", response=httpx2.Response(500, request=REQ), body=None))]


def openai_mock(responses):
    with mock.patch.dict(os.environ, KEY, clear=True), mock.patch("openai.OpenAI") as cls:
        inv = OpenAIInvestigator(model="gpt-6-luna", reasoning_effort="")
    inv._client = cls.return_value
    inv._client.responses.with_raw_response.parse.side_effect = responses
    return inv


def sent(inv):
    return [c.kwargs for c in inv._client.responses.with_raw_response.parse.call_args_list]


class Configuration(unittest.TestCase):
    def test_no_fallback_api_remains(self):
        for name in ("fallback_settings", "ENV_FALLBACK_PROVIDER", "ENV_GROQ_KEY", "FALLBACK_PROVIDERS"):
            self.assertFalse(hasattr(config, name), name)
        for name in ("GroqInvestigator", "fallback_from_env"):
            self.assertFalse(hasattr(llm, name), name)
        self.assertNotIn("groq", config.DEFAULT_MODELS)
        with self.assertRaises(ImportError):
            import uc042lib.investigation.fallback  # noqa: F401

    def test_factory_builds_only_openai_even_with_legacy_fallback_variables(self):
        with mock.patch.dict(os.environ, dict(LEGACY_FALLBACK_ENV, **KEY), clear=True), mock.patch("openai.OpenAI") as cls:
            inv = investigator_from_env()
        self.assertIs(type(inv), OpenAIInvestigator)
        self.assertEqual((inv.provider, inv.model), ("openai", "gpt-6-luna"))
        self.assertEqual(cls.call_count, 1)  # one client: OpenAI's
        self.assertNotIn("base_url", cls.call_args.kwargs)  # the default OpenAI endpoint, never Groq's
        self.assertFalse(hasattr(inv, "fallback_record"))

    def test_groq_is_not_an_accepted_provider(self):
        with mock.patch.dict(os.environ, {"UC042_LLM_PROVIDER": "groq", "GROQ_API_KEY": "gsk_test_NOT_REAL_0000"}, clear=True):
            with self.assertRaises(LLMConfigurationError) as e:
                investigator_from_env()
        self.assertIn("unsupported provider 'groq'", str(e.exception))


class FailuresAreReportedNotRerouted(unittest.TestCase):
    def test_each_availability_failure_is_reported_after_one_request(self):
        for kind, exc in availability_failures():
            with self.subTest(kind=kind):
                inv = openai_mock([exc])
                with self.assertRaises(LLMCallError) as e:
                    inv.tool_turn([{"role": "user", "content": "x"}], [], timeout=30)
                self.assertEqual(e.exception.kind, kind)
                self.assertEqual(len(sent(inv)), 1)
                self.assertNotIn("fallback", str(e.exception).lower())
                self.assertEqual((inv.provider, inv.model), ("openai", "gpt-6-luna"))


class InvestigationFailsVisibly(Temp):
    def test_credit_exhaustion_fails_the_investigation_without_another_provider(self):
        inv = openai_mock([credit_exhausted()])
        s = run_investigation(PACK["SC2"], "EXC-SC2-01", inv, investigations_root=self.tmp, mode="tools", tool_limits=dict(LIMITS))
        self.assertNotEqual(s["persist_outcome"], "PUBLISHED")
        self.assertEqual(len(sent(inv)), 1)  # no retry loop for exhausted credits
        self.assertIn("rate_limit", json.dumps(s.get("errors") or s.get("result") or {}, default=str))


class ClosingSummaryHasNoFallback(unittest.TestCase):
    def test_summary_fails_with_the_openai_error(self):
        from tests.final_pack_support import make_investigation
        from uc042lib.final_pack import build_review_snapshot, generate_closing_summary
        tmp = Path(tempfile.mkdtemp())
        try:
            inv_id = make_investigation("SC5A", "EXC-SC5A-01", tmp)
            snap = build_review_snapshot(FP_PACK["SC5A"], [{"exception_id": "EXC-SC5A-01", "inclusion": "INCLUDED", "investigation_id": inv_id},
                                                           {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}], investigations_root=tmp)
            inv = openai_mock([credit_exhausted()])
            try:
                summary = generate_closing_summary(snap, inv)
            except Exception as e:  # either an explicit error or an explicit unavailable summary; never another provider's text
                self.assertIn("rate_limit", str(e))
            else:
                self.assertNotEqual(summary.status, "GENERATED")
                self.assertNotIn("fallback", summary.model_metadata)
            self.assertEqual(len(sent(inv)), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ApiConfigurationAndAuthorisation(ApiCase):
    def test_configuration_has_no_fallback_and_a_stale_fallback_confirmation_is_refused(self):
        from uc042app.services.ai_authorization import AiAuthorizationService
        env = dict(LEGACY_FALLBACK_ENV, OPENAI_API_KEY="sk-test-NOT-REAL-0000", UC042_LLM_PROVIDER="openai")
        with mock.patch.dict(os.environ, env):
            c = self.get("/api/v1/ai/configuration").json()
            self.assertNotIn("fallback", c)
            self.assertEqual((c["provider"], c["model"], c["provider_configured"]), ("openai", "gpt-6-luna", True))
            self.assertNotIn("fallback", json.dumps(c["statements"]).lower())
            self.assertNotIn("gsk_", json.dumps(c))
            self.assertNotIn("sk-test", json.dumps(c))
            _, problem = self.svc.ai_authorizations.require("INVESTIGATION", dict(AI_OK, fallback_provider="groq", fallback_model="openai/gpt-oss-120b"))
            self.assertIn("there is no automatic fallback provider", problem)
            _, problem = self.svc.ai_authorizations.require("INVESTIGATION", dict(AI_OK, fallback_provider="none", fallback_model="none"))
            self.assertIsNone(problem)
            _, problem = self.svc.ai_authorizations.require("INVESTIGATION", dict(AI_OK))
            self.assertIsNone(problem)


if __name__ == "__main__":
    unittest.main()
