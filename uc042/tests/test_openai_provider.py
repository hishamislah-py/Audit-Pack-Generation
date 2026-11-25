"""OpenAI provider adapter (Responses API + Pydantic structured output). Run from the uc042/ folder: python -m unittest -v

Every provider response here is a mocked SDK object; no test needs a real API key or makes a network call. Real SDK
exception classes are used so that error mapping is tested against the installed openai package.
"""
import glob
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx2
import openai
from pydantic import ValidationError

from uc042lib.investigation import config
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import (AnthropicInvestigator, LLMCallError, LLMConfigurationError, OfflineSimulatedInvestigator,
                                        OpenAIInvestigator, investigator_from_env, redact)
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for

ROOT = Path(__file__).resolve().parent.parent
PACK = {os.path.basename(p).split("-")[1]: os.path.basename(p) for p in glob.glob(str(ROOT / "packs" / "PACK-*"))}
OFFLINE = OfflineSimulatedInvestigator()
FAKE_KEY = "sk-test-NOT-A-REAL-KEY-0123456789"
ENV = {config.ENV_OPENAI_KEY: FAKE_KEY}
REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def packet_for(scenario, exception_id):
    pack = load_pack(PACK[scenario])
    case = build_case(pack, exception_id)
    route = route_for(case["exception"], case["candidates"], case["results"])
    return build_packet(case, build_scope(case), route, retrieve(route, case, EvidenceStore(pack)))


def body(status="completed", content=None, usage=None, incomplete=None, error=None, model="gpt-6-luna-2026-10-01"):
    return {"id": "resp_test_001", "model": model, "status": status, "incomplete_details": incomplete, "error": error,
            "output": [{"type": "reasoning"}, {"type": "message", "content": content or [{"type": "output_text", "text": "{}"}]}],
            "usage": usage if usage is not None else {"input_tokens": 15000, "output_tokens": 2100, "total_tokens": 17100,
                                                      "input_tokens_details": {"cached_tokens": 0},
                                                      "output_tokens_details": {"reasoning_tokens": 900}}}


def raw(b, parsed=None, parse_error=None):
    r = mock.Mock()
    r.http_response.json.return_value = b
    r.http_response.headers = {"x-request-id": "req_test_001"}
    if parse_error:
        r.parse.side_effect = parse_error
    else:
        r.parse.return_value = mock.Mock(output_parsed=parsed)
    return r


def status_error(cls, status, message, code=None):
    return cls(message, response=httpx2.Response(status, request=REQ), body={"message": message, "code": code})


def schema_error():
    try:
        LLMInvestigationOutput.model_validate_json('{"investigation_summary": "truncated')
    except ValidationError as e:
        return e


class OpenAITestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = packet_for("S05", "EXC-S05-01")
        cls.good = OFFLINE.investigate(cls.packet)[0]

    def make(self, responses, **kw):
        """An OpenAIInvestigator whose SDK client is a mock returning/raising the given items in order."""
        with mock.patch.dict(os.environ, ENV, clear=True), mock.patch("openai.OpenAI") as client_cls:
            inv = OpenAIInvestigator(**kw)
        inv._client = client_cls.return_value
        inv._client.responses.with_raw_response.parse.side_effect = responses
        return inv

    def calls(self, inv):
        return inv._client.responses.with_raw_response.parse.call_args_list


# ---------------------------------------------------------------------------------------------------------------
class ProviderSelectionAndConfig(unittest.TestCase):
    def test_openai_is_the_default_provider(self):
        with mock.patch.dict(os.environ, ENV, clear=True), mock.patch("openai.OpenAI"):
            inv = investigator_from_env()
        self.assertIsInstance(inv, OpenAIInvestigator)
        self.assertEqual((inv.provider, inv.model, inv.simulated), ("openai", config.DEFAULT_MODELS["openai"], False))

    def test_explicit_provider_selection(self):
        with mock.patch.dict(os.environ, dict(ENV, **{config.ENV_PROVIDER: "OpenAI", config.ENV_MODEL: "gpt-alt"}), clear=True), \
                mock.patch("openai.OpenAI"):
            self.assertEqual(investigator_from_env().model, "gpt-alt")
        with mock.patch.dict(os.environ, {config.ENV_PROVIDER: "offline"}, clear=True):
            self.assertTrue(investigator_from_env().simulated)
        with mock.patch.dict(os.environ, {config.ENV_PROVIDER: "anthropic", config.ENV_ANTHROPIC_KEY: "x" * 20}, clear=True), \
                mock.patch("anthropic.Anthropic"):
            a = investigator_from_env()
        self.assertIsInstance(a, AnthropicInvestigator)
        self.assertEqual(a.model, config.DEFAULT_MODELS["anthropic"])
        with mock.patch.dict(os.environ, {config.ENV_PROVIDER: "gemini"}, clear=True):
            with self.assertRaises(LLMConfigurationError):
                investigator_from_env()

    def test_client_construction(self):
        env = dict(ENV, **{config.ENV_TIMEOUT: "45", config.ENV_MAX_TOKENS: "9000"})
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("openai.OpenAI") as client_cls:
            inv = OpenAIInvestigator()
        client_cls.assert_called_once_with(api_key=FAKE_KEY, timeout=45.0, max_retries=2)
        self.assertEqual((inv.timeout, inv.max_tokens, inv.total_timeout), (45.0, 9000, 300.0))

    def test_missing_or_blank_api_key(self):
        for env in ({}, {config.ENV_OPENAI_KEY: "   "}):
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(LLMConfigurationError) as cm:
                    OpenAIInvestigator()
                self.assertIn("OPENAI_API_KEY is not set", str(cm.exception))
                self.assertFalse(config.api_key_configured())

    def test_malformed_settings_are_configuration_errors(self):
        for name, value in ((config.ENV_TIMEOUT, "fast"), (config.ENV_MAX_TOKENS, "-5"), (config.ENV_REASONING_EFFORT, "extreme")):
            with mock.patch.dict(os.environ, dict(ENV, **{name: value}), clear=True), mock.patch("openai.OpenAI"):
                with self.assertRaises(LLMConfigurationError, msg=name):
                    investigator_from_env()

    def test_local_env_file_loading_never_overrides_the_process_environment(self):
        d = Path(tempfile.mkdtemp())
        try:
            f = d / ".env"
            f.write_text("UC042_TEST_FROM_FILE=file-value\nUC042_TEST_ALREADY_SET=file-value\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"UC042_TEST_ALREADY_SET": "process-value"}, clear=True):
                self.assertTrue(config.load_local_env(f))
                self.assertEqual(os.environ["UC042_TEST_FROM_FILE"], "file-value")
                self.assertEqual(os.environ["UC042_TEST_ALREADY_SET"], "process-value")
            self.assertFalse(config.load_local_env(d / "missing.env"))
        finally:
            shutil.rmtree(d)

    def test_env_example_template_has_no_secret_and_parses(self):
        from dotenv import dotenv_values
        v = dotenv_values(ROOT / ".env.example")
        self.assertEqual((v["UC042_LLM_PROVIDER"], v["UC042_LLM_MODEL"], v["OPENAI_API_KEY"]), ("openai", "gpt-6-luna", ""))
        self.assertIn(".env", (ROOT / ".gitignore").read_text().splitlines())


# ---------------------------------------------------------------------------------------------------------------
class ResponsesRequest(OpenAITestCase):
    def test_valid_parsed_response_and_request_shape(self):
        inv = self.make([raw(body(), parsed=self.good)], reasoning_effort="medium")
        out, meta = inv.investigate(self.packet)
        self.assertEqual(out, self.good)
        kw = self.calls(inv)[0].kwargs
        self.assertIs(kw["text_format"], LLMInvestigationOutput)
        self.assertEqual((kw["model"], kw["max_output_tokens"], kw["store"], kw["reasoning"]),
                         (inv.model, inv.max_tokens, False, {"effort": "medium"}))
        self.assertIn("financial discrepancy investigator", kw["instructions"])
        self.assertEqual([m["role"] for m in kw["input"]], ["user"])
        self.assertIn(self.packet["packet_sha256"], kw["input"][0]["content"])
        for unsupported in ("temperature", "top_p"):
            self.assertNotIn(unsupported, kw)

    def test_reasoning_effort_sent_only_when_configured(self):
        inv = self.make([raw(body(), parsed=self.good)], reasoning_effort="")
        inv.investigate(self.packet)
        self.assertNotIn("reasoning", self.calls(inv)[0].kwargs)

    def test_token_usage_and_provider_metadata_captured(self):
        inv = self.make([raw(body(), parsed=self.good)])
        _, meta = inv.investigate(self.packet)
        u = meta["usage"]
        self.assertEqual((u["input_tokens"], u["output_tokens"], u["reasoning_tokens"], u["total_tokens"]), (15000, 2100, 900, 17100))
        self.assertIn("latency_seconds", u)
        self.assertEqual(meta["provider_response"], {"response_id": "resp_test_001", "resolved_model": "gpt-6-luna-2026-10-01",
                                                     "status": "completed", "request_id": "req_test_001"})
        self.assertEqual(meta["attempts"], 1)


class ResponseFailures(OpenAITestCase):
    def assertKind(self, inv, kind, text=None, calls=1):
        with self.assertRaises(LLMCallError) as cm:
            inv.investigate(self.packet)
        self.assertEqual(cm.exception.kind, kind, str(cm.exception))
        if text:
            self.assertIn(text, str(cm.exception))
        self.assertEqual(len(self.calls(inv)), calls)
        return cm.exception

    def test_refusal(self):
        b = body(content=[{"type": "refusal", "refusal": "I can't help with that."}])
        self.assertKind(self.make([raw(b)]), "refusal", "I can't help with that.")

    def test_max_output_tokens_is_not_reported_as_invalid_json(self):
        b = body(status="incomplete", incomplete={"reason": "max_output_tokens"})
        e = self.assertKind(self.make([raw(b, parse_error=schema_error())]), "max_output_tokens", "max_output_tokens")
        self.assertNotIn("JSON", str(e))

    def test_other_incomplete_response(self):
        b = body(status="incomplete", incomplete={"reason": "content_filter"})
        self.assertKind(self.make([raw(b)]), "incomplete", "content_filter")

    def test_failed_response_status(self):
        b = body(status="failed", error={"code": "server_error", "message": "boom"})
        self.assertKind(self.make([raw(b)]), "response_failed", "server_error")

    def test_absent_parsed_output_is_retried_once_then_fails(self):
        self.assertKind(self.make([raw(body(), parsed=None), raw(body(), parsed=None)]), "invalid_output", "no parsed", calls=2)

    def test_malformed_structured_output_retried_then_success(self):
        inv = self.make([raw(body(), parse_error=schema_error()), raw(body(), parsed=self.good)])
        out, meta = inv.investigate(self.packet)
        self.assertEqual((out, meta["attempts"]), (self.good, 2))
        self.assertEqual(meta["usage"]["input_tokens"], 30000)  # both attempts counted

    def test_authentication_failure_is_mapped_and_redacted(self):
        err = status_error(openai.AuthenticationError, 401, f"Incorrect API key provided: {FAKE_KEY}", "invalid_api_key")
        with mock.patch.dict(os.environ, ENV):
            e = self.assertKind(self.make([err]), "authentication", "401")
        self.assertNotIn(FAKE_KEY, str(e))
        self.assertNotIn("0123456789", str(e))

    def test_invalid_model(self):
        self.assertKind(self.make([status_error(openai.NotFoundError, 404, "The model `gpt-x` does not exist", "model_not_found")]),
                        "model_unavailable", "model_not_found")
        self.assertKind(self.make([status_error(openai.BadRequestError, 400, "The requested model 'gpt-x' does not exist.")]),
                        "model_unavailable")

    def test_bad_request_keeps_the_provider_detail(self):
        self.assertKind(self.make([status_error(openai.BadRequestError, 400, "Unsupported parameter: 'reasoning.effort'")]),
                        "bad_request", "Unsupported parameter")

    def test_rate_limit(self):
        self.assertKind(self.make([status_error(openai.RateLimitError, 429, "Rate limit reached")]), "rate_limit", "429")

    def test_timeout_and_connection(self):
        self.assertKind(self.make([openai.APITimeoutError(request=REQ)]), "timeout", "timed out")
        self.assertKind(self.make([openai.APIConnectionError(request=REQ)]), "connection")

    def test_unexpected_sdk_exception(self):
        self.assertKind(self.make([TypeError("parse() got an unexpected keyword argument 'x'")]), "unexpected", "TypeError")

    def test_overall_time_budget(self):
        inv = self.make([raw(body(), parse_error=schema_error()), raw(body(), parsed=self.good)], total_timeout=50)
        with mock.patch("uc042lib.investigation.llm.time.monotonic", side_effect=[0, 0, 10, 60]):
            self.assertKind(inv, "timeout_budget", calls=1)

    def test_per_request_timeout_never_exceeds_remaining_budget(self):
        inv = self.make([raw(body(), parsed=self.good)], timeout=120, total_timeout=30)
        inv.investigate(self.packet)
        self.assertLessEqual(self.calls(inv)[0].kwargs["timeout"], 30)

    def test_redact(self):
        self.assertEqual(redact("key sk-proj-abcDEF123_xyz and Bearer abc.def"), "key [REDACTED] and [REDACTED]")

    def test_availability_check(self):
        inv = self.make([])
        inv._client.models.retrieve.return_value = mock.Mock(id="gpt-6-luna")
        self.assertEqual(inv.check_availability()["available"], True)
        inv._client.models.retrieve.side_effect = status_error(openai.NotFoundError, 404, "model not found", "model_not_found")
        with self.assertRaises(LLMCallError) as cm:
            inv.check_availability()
        self.assertEqual(cm.exception.kind, "model_unavailable")


# ---------------------------------------------------------------------------------------------------------------
class GraphWithMockedOpenAI(OpenAITestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_full_graph_publishes_a_live_labelled_artefact(self):
        inv = self.make([raw(body(), parsed=self.good)])
        s = run_investigation(PACK["S05"], "EXC-S05-01", inv, investigations_root=self.tmp)
        r = s["result"]
        self.assertEqual((r["investigation_status"], r["validation_status"], s["persist_outcome"]), ("COMPLETED", "VALID", "PUBLISHED"))
        m = json.loads((Path(s["artefact_path"]) / "findings.json").read_text())["model_metadata"]
        self.assertEqual((m["provider"], m["simulated"], m["provider_response"]["response_id"]), ("openai", False, "resp_test_001"))
        self.assertEqual(r["exception_resolution"], "NOT_RESOLVED_BY_INVESTIGATION")

    def test_provider_failure_is_a_failed_unpublished_investigation(self):
        inv = self.make([status_error(openai.RateLimitError, 429, "slow down")])
        s = run_investigation(PACK["S05"], "EXC-S05-01", inv, investigations_root=self.tmp)
        r = s["result"]
        self.assertEqual((r["investigation_status"], r["validation_status"], s["persist_outcome"]), ("FAILED", "NOT_VALIDATED", "NOT_PUBLISHED"))
        self.assertIn("[rate_limit]", r["failure_reason"])
        self.assertEqual((r["original_exception_status"], r["model_metadata"]["provider"]), ("OPEN", "openai"))
        self.assertFalse((self.tmp / PACK["S05"]).exists())


if __name__ == "__main__":
    unittest.main()
