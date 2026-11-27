"""Phase 3 (token-optimisation copy): per-request API telemetry.

Every Responses request records, in provider_response (excluded from the investigation identity): turn, response and
request IDs, model, status, incomplete reason, its own usage, latency, max_output_tokens and the size of what was sent
(item count and characters; never the content). The aggregate usage equals the sum of the per-request usage. Failures keep
their billed usage (the fixed mode used to lose it). The closing summary's request IDs and usage flow into its metadata.
Offline (mocked client). Run: python -m unittest tests.test_phase3_telemetry -v"""
import json
import unittest

from tests.test_phase1_reliability import make
from tests.test_tool_calling import PACK, Temp, bad_final, calls, fc, final, offline_output, raw, setup_case, status_body, USAGE
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.persistence import investigation_id_from_findings

KEYS = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "total_tokens")


def per_request_sum(responses):
    return {k: sum((r.get("usage") or {}).get(k) or 0 for r in responses) for k in KEYS}


class ToolsModeTelemetry(Temp):
    def test_multi_request_records_each_turn_and_the_aggregate_is_their_sum(self):
        out = offline_output("SC2", "EXC-SC2-01")
        s, _ = self.run_tools([calls(fc("a1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})),
                               calls(fc("a2", "get_cashbook_entries", {"account_id": "SGA-GBP-01", "date_from": "2026-09-15",
                                                                       "date_to": "2026-09-15", "payment_reference": None})),
                               final(out)])
        self.assertEqual(s["persist_outcome"], "PUBLISHED", s["result"]["validation_findings"])
        m = s["result"]["model_metadata"]
        resp = m["provider_response"]["responses"]
        self.assertEqual([r["turn"] for r in resp], [1, 2, 3])
        for r in resp:
            for k in ("response_id", "request_id", "model", "status", "usage", "latency_seconds", "input_items", "input_chars", "max_output_tokens"):
                self.assertIn(k, r)
            self.assertEqual(r["max_output_tokens"], 12000)
        self.assertGreater(resp[2]["input_items"], resp[0]["input_items"])  # the history grows each turn
        self.assertEqual({k: m["usage"][k] for k in KEYS}, per_request_sum(resp))
        self.assertNotIn("<evidence_packet>", json.dumps(resp))  # sizes only, never the prompt content

    def test_identity_is_unaffected_by_telemetry(self):
        out = offline_output("SC2", "EXC-SC2-01")
        s, _ = self.run_tools([final(out)])
        res = s["result"]
        pid = res["evidence_packet_sha256"]
        stripped = json.loads(json.dumps(res))
        stripped["model_metadata"]["provider_response"] = {}
        stripped["model_metadata"]["usage"] = {}
        self.assertEqual(investigation_id_from_findings(res, pid), investigation_id_from_findings(stripped, pid))
        self.assertEqual(res["investigation_id"], investigation_id_from_findings(res, pid))

    def test_truncated_turn_is_recorded_with_its_reason_and_usage(self):
        s, _ = self.run_tools([calls(fc("t1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})),
                               status_body("incomplete", incomplete_details={"reason": "max_output_tokens"})])
        m = s["result"]["model_metadata"]
        resp = m["provider_response"]["responses"]
        self.assertEqual([(r["turn"], r["status"], r["incomplete_reason"]) for r in resp],
                         [(1, "completed", None), (2, "incomplete", "max_output_tokens")])
        self.assertEqual(m["usage"]["input_tokens"], 2 * USAGE["input_tokens"])  # billed usage kept on failure
        self.assertEqual(s["persist_outcome"], "NOT_PUBLISHED")


class FixedModeTelemetry(Temp):
    def test_single_request(self):
        _, packet, _ = setup_case("SC2", "EXC-SC2-01")
        inv = make([final(offline_output("SC2", "EXC-SC2-01"))])
        _, meta = inv.investigate(packet)
        resp = meta["provider_response"]["responses"]
        self.assertEqual(len(resp), 1)
        self.assertEqual({k: meta["usage"][k] for k in KEYS}, per_request_sum(resp))

    def test_corrective_retry_records_both_attempts(self):
        _, packet, _ = setup_case("SC2", "EXC-SC2-01")
        inv = make([bad_final(), final(offline_output("SC2", "EXC-SC2-01"))])
        _, meta = inv.investigate(packet)
        resp = meta["provider_response"]["responses"]
        self.assertEqual([r["turn"] for r in resp], [1, 2])
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual({k: meta["usage"][k] for k in KEYS}, per_request_sum(resp))

    def test_fixed_mode_failure_keeps_usage_and_records(self):
        inv = make([status_body("incomplete", incomplete_details={"reason": "max_output_tokens"})])
        s = run_investigation(PACK["SC2"], "EXC-SC2-01", inv, investigations_root=self.tmp, mode="fixed")
        m = s["result"]["model_metadata"]
        self.assertEqual(m["usage"]["input_tokens"], USAGE["input_tokens"])  # previously lost
        self.assertEqual(m["provider_response"]["responses"][0]["incomplete_reason"], "max_output_tokens")
        self.assertEqual(s["persist_outcome"], "NOT_PUBLISHED")


class ClosingSummaryTelemetry(unittest.TestCase):
    def test_request_ids_and_usage_of_each_attempt(self):
        from pydantic import BaseModel

        class Tiny(BaseModel):
            text: str
        r = raw({"id": "resp_sum", "model": "gpt-6-luna", "status": "completed", "output": [], "usage": USAGE}, parsed=Tiny(text="ok"))
        inv = make([r])
        _, meta = inv.structured_request("instr", "content", Tiny)
        pr = meta["provider_response"]
        self.assertEqual((pr["response_id"], pr["request_id"]), ("resp_sum", "req_x"))
        self.assertEqual(len(pr["responses"]), 1)
        self.assertEqual((pr["responses"][0]["max_output_tokens"], pr["responses"][0]["usage"]["input_tokens"]), (8000, 1000))
        self.assertEqual({k: meta["usage"][k] for k in KEYS}, per_request_sum(pr["responses"]))


if __name__ == "__main__":
    unittest.main()
