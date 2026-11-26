"""Stage 5: telemetry completeness.

DR-08  max_retries=2 is kept (behaviour unchanged). The OpenAI SDK's own HTTP retries (429 / 5xx / connection) happen
       inside one client call and are NOT separate application telemetry entries: each entry records the SDK retry
       allowance (sdk_max_retries) so a reader knows one entry can stand for up to 1 + sdk_max_retries HTTP attempts.
DR-09  a failed closing summary keeps its telemetry: from the LLMCallError the summary error wraps (provider / transport
       failure), or from the investigator's last structured request (output refused by validation after a billed call).
       The failure record keeps kind and detail and stores model_metadata in the same shape as a successful summary's.
Offline (mocked OpenAI client). Run: python -m unittest tests.test_stage5_telemetry -v"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import openai

from tests import test_api_reviews as api_reviews
from tests.final_pack_support import PACK, USAGE, make_investigation, openai_investigator, raw, summary_investigator
from uc042app.services.reviews import summary_failure_record
from uc042lib.final_pack import ClosingSummaryError, build_review_snapshot, default_selections, generate_closing_summary, load_pack
from uc042lib.final_pack.model import SUMMARY_PROMPT_VERSION, SUMMARY_SCHEMA_VERSION
from uc042lib.investigation import config, llm
from uc042lib.investigation.llm import LLMCallError, LLMConfigurationError, OpenAIInvestigator

META_KEYS = {"attempts", "provider_response", "usage", "provider", "model", "simulated", "prompt_version", "summary_schema_version"}


class DR08SdkRetries(unittest.TestCase):
    def test_retry_behaviour_unchanged_and_documented(self):
        self.assertEqual(llm.SDK_MAX_RETRIES, 2)
        with mock.patch.dict(os.environ, {config.ENV_OPENAI_KEY: "sk-test-NOT-REAL-0000"}, clear=True), mock.patch("openai.OpenAI") as cls:
            OpenAIInvestigator(model="gpt-6-luna", reasoning_effort="")
        self.assertEqual(cls.call_args.kwargs["max_retries"], 2)
        doc = llm.__doc__ or ""
        self.assertIn("SDK", doc)
        self.assertIn("not separate", doc)

    def test_every_telemetry_entry_states_the_sdk_retry_allowance(self):
        inv = openai_investigator(lambda kw: raw(_summary_out()))
        _, meta = inv.structured_request("instructions", "content", type(_summary_out()))
        self.assertEqual([r["sdk_max_retries"] for r in meta["provider_response"]["responses"]], [2])
        inv = openai_investigator(lambda kw: (_ for _ in ()).throw(openai.APIConnectionError(request=mock.Mock())))
        with self.assertRaises(LLMCallError) as cm:
            inv.structured_request("instructions", "content", type(_summary_out()))
        self.assertEqual([r["sdk_max_retries"] for r in cm.exception.telemetry["provider_response"]["responses"]], [2])


_SNAP = {}


def _snapshot():
    if not _SNAP:
        root = tempfile.mkdtemp(prefix="uc042-s5-")
        make_investigation("SC5A", "EXC-SC5A-01", root)
        _SNAP["root"] = root
        _SNAP["snap"] = build_review_snapshot(PACK["SC5A"], default_selections(load_pack(PACK["SC5A"]), root), investigations_root=root)
    return _SNAP["snap"]


def _summary_out():
    _, out = summary_investigator(_snapshot())
    return out


def tearDownModule():
    if _SNAP:
        shutil.rmtree(_SNAP["root"], ignore_errors=True)


class DR09SummaryTelemetry(unittest.TestCase):
    def test_success_records_the_last_structured_request(self):
        inv, _ = summary_investigator(_snapshot())
        s = generate_closing_summary(_snapshot(), inv)
        self.assertEqual(s.status, "GENERATED")
        self.assertEqual(META_KEYS, set(s.model_metadata) & META_KEYS)
        self.assertEqual(inv.last_structured_request["usage"]["input_tokens"], s.model_metadata["usage"]["input_tokens"])
        self.assertEqual(len(inv.last_structured_request["provider_response"]["responses"]), 1)

    def test_provider_failure_keeps_telemetry(self):
        out = _summary_out()
        inv = openai_investigator(lambda kw: raw(out, status="incomplete"))
        with self.assertRaises(ClosingSummaryError) as cm:
            generate_closing_summary(_snapshot(), inv)
        rec = summary_failure_record(cm.exception, inv)
        self.assertEqual(rec["kind"], "incomplete")
        self.assertIn("incomplete", rec["detail"])
        self.assertTrue(rec["telemetry_available"])
        m = rec["model_metadata"]
        self.assertEqual(META_KEYS, set(m) & META_KEYS)  # the same shape as a successful summary's metadata
        self.assertEqual(m["usage"]["input_tokens"], USAGE["input_tokens"])
        self.assertEqual((m["provider"], m["model"], m["prompt_version"], m["summary_schema_version"]),
                         ("openai", "gpt-6-luna", SUMMARY_PROMPT_VERSION, SUMMARY_SCHEMA_VERSION))
        self.assertEqual([r["status"] for r in m["provider_response"]["responses"]], ["incomplete"])

    def test_validation_failure_keeps_the_billed_usage(self):
        """The call succeeded and was billed; the output was refused by validation (no LLMCallError to carry telemetry)."""
        inv, _ = summary_investigator(_snapshot(), lambda d: d.update(overall_position="The difference arose due to timing."))
        with self.assertRaises(ClosingSummaryError) as cm:
            generate_closing_summary(_snapshot(), inv)
        self.assertEqual(cm.exception.kind, "invalid_summary")
        rec = summary_failure_record(cm.exception, inv)
        self.assertTrue(rec["telemetry_available"])
        self.assertEqual(rec["model_metadata"]["usage"]["input_tokens"], USAGE["input_tokens"])
        self.assertEqual(rec["model_metadata"]["attempts"], 1)

    def test_transport_failure_without_a_response_body(self):
        inv = openai_investigator(lambda kw: (_ for _ in ()).throw(openai.APIConnectionError(request=mock.Mock())))
        with self.assertRaises(ClosingSummaryError) as cm:
            generate_closing_summary(_snapshot(), inv)
        rec = summary_failure_record(cm.exception, inv)
        self.assertEqual(rec["kind"], "connection")
        self.assertTrue(rec["telemetry_available"])
        self.assertEqual([r["status"] for r in rec["model_metadata"]["provider_response"]["responses"]], ["error"])
        self.assertEqual(rec["model_metadata"]["usage"], {})

    def test_no_telemetry_when_no_request_was_made(self):
        for err, inv in ((LLMConfigurationError("OPENAI_API_KEY is not set"), None),
                         (ClosingSummaryError("provider 'x' does not support structured summaries", "unsupported_provider"), object())):
            with self.subTest(err.__class__.__name__):
                rec = summary_failure_record(err, inv)
                self.assertFalse(rec["telemetry_available"])
                self.assertIsNone(rec["model_metadata"])
                self.assertTrue(rec["kind"] and rec["detail"])

    def test_stale_telemetry_is_never_reused(self):
        """The investigator's last request is used only for a refused OUTPUT (invalid_summary), never for a failure that
        happened before any request: a previous call's usage is not attributed to a request that was never made."""
        inv, _ = summary_investigator(_snapshot())
        generate_closing_summary(_snapshot(), inv)  # leaves last_structured_request from an earlier, successful call
        rec = summary_failure_record(ClosingSummaryError("provider unsupported", "unsupported_provider"), inv)
        self.assertFalse(rec["telemetry_available"])
        self.assertIsNone(rec["model_metadata"])
        fresh = openai_investigator(lambda kw: raw(_summary_out()))
        self.assertIsNone(fresh.last_structured_request)


class DR09ThroughThePreviewJob(api_reviews.ReviewCase):
    def test_failed_summary_preview_stores_telemetry(self):
        self.provider.summary_error = RuntimeError("socket closed")
        s = self.preview(self.open()["review_id"])
        cs = s["current_preview"]["closing_summary"]
        self.assertEqual(cs["status"], "UNAVAILABLE")
        f = cs["failure"]
        self.assertTrue(f["kind"] and f["detail"] and f["telemetry_available"], f)
        self.assertEqual(META_KEYS, set(f["model_metadata"]) & META_KEYS)
        self.assertEqual([r["status"] for r in f["model_metadata"]["provider_response"]["responses"]], ["error"])

    def test_successful_summary_preview_unchanged(self):
        s = self.preview(self.open()["review_id"])
        cs = s["current_preview"]["closing_summary"]
        self.assertEqual(cs["status"], "GENERATED")
        self.assertIsNone(cs["failure"])


if __name__ == "__main__":
    unittest.main()
