"""V2 bounded tool calling: tool registry, tool execution and provenance, the evidence ledger, the nested LangGraph
tool loop, finding validation against the ledger, and persistence. Run from uc042/: python -m unittest -v

The Responses API is mocked with raw response bodies in the real function_call / function_call_output shapes and the real
openai exception classes; the actual OpenAIInvestigator adapter, tool-loop subgraph and outer graph run unchanged. No API
key or network access is needed. Artefacts are written to temporary folders only.
"""
import copy
import glob
import hashlib
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

from uc042lib.investigation import config, tools
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import AnthropicInvestigator, OfflineSimulatedInvestigator, OpenAIInvestigator
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import Collector, build_case, build_ledger, build_packet, build_scope, collector_from_packet, retrieve
from uc042lib.investigation.prompts import TOOLS_SYSTEM_PROMPT
from uc042lib.pack.model import canonical
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.investigation.validation import validate_output

ROOT = Path(__file__).resolve().parent.parent
PACK = {os.path.basename(p).split("-")[1]: os.path.basename(p) for p in glob.glob(str(ROOT / "packs" / "PACK-*"))}
OFFLINE = OfflineSimulatedInvestigator()
REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")
LIMITS = {"max_tool_calls": 8, "max_rounds": 4, "max_records_per_call": 25, "max_input_tokens": 150000,
          "max_total_records": 160, "total_timeout": 300.0}


def setup_case(scenario, exception_id):
    pack = load_pack(PACK[scenario])
    case = build_case(pack, exception_id)
    route = route_for(case["exception"], case["candidates"], case["results"])
    store = EvidenceStore(pack)
    return case, build_packet(case, build_scope(case), route, retrieve(route, case, store)), store


def req(name, **args):
    a, err = tools.parse_request(name, json.dumps(args))
    if err:
        raise AssertionError(err)
    return a


# -- mocked Responses API ---------------------------------------------------------------------------------------
def fc(call_id, name, args):
    return {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id, "name": name, "status": "completed",
            "arguments": args if isinstance(args, str) else json.dumps(args)}


REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "ENCRYPTED"}
USAGE = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200, "output_tokens_details": {"reasoning_tokens": 50},
         "input_tokens_details": {"cached_tokens": 0}}


def raw(body, parsed=None, parse_error=None):
    r = mock.Mock()
    r.http_response.json.return_value = body
    r.http_response.headers = {"x-request-id": "req_x"}
    if parse_error:
        r.parse.side_effect = parse_error
    else:
        r.parse.return_value = mock.Mock(output_parsed=parsed)
    return r


def calls(*items):
    return raw({"id": "resp_c", "model": "gpt-6-luna", "status": "completed", "output": [REASONING, *items], "usage": USAGE})


def final(output):
    parsed = LLMInvestigationOutput.model_validate(output)
    msg = {"type": "message", "id": "msg_1", "role": "assistant", "content": [{"type": "output_text", "text": parsed.model_dump_json()}]}
    return raw({"id": "resp_f", "model": "gpt-6-luna", "status": "completed", "output": [REASONING, msg], "usage": USAGE}, parsed=parsed)


def bad_final():
    try:
        LLMInvestigationOutput.model_validate_json('{"investigation_summary": "cut')
    except ValidationError as e:
        err = e
    msg = {"type": "message", "id": "msg_2", "role": "assistant", "content": [{"type": "output_text", "text": "{bad"}]}
    return raw({"id": "resp_b", "model": "gpt-6-luna", "status": "completed", "output": [msg], "usage": USAGE}, parse_error=err)


def status_body(status, **kw):
    return raw(dict({"id": "resp_s", "model": "gpt-6-luna", "status": status, "output": [], "usage": USAGE}, **kw))


def openai_inv(responses):
    with mock.patch.dict(os.environ, {config.ENV_OPENAI_KEY: "sk-test-NOT-REAL-0000"}, clear=True), mock.patch("openai.OpenAI") as cls:
        inv = OpenAIInvestigator(model="gpt-6-luna", reasoning_effort="")
    inv._client = cls.return_value
    inv._client.responses.with_raw_response.parse.side_effect = responses
    return inv


def requests_of(inv):
    return [c.kwargs for c in inv._client.responses.with_raw_response.parse.call_args_list]


def offline_output(scenario, exception_id):
    _, packet, _ = setup_case(scenario, exception_id)
    return OFFLINE.investigate(packet)[0].model_dump()


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_tools(self, responses, scenario="SC2", exception_id="EXC-SC2-01", limits=None, inv=None):
        inv = inv or openai_inv(responses)
        s = run_investigation(PACK[scenario], exception_id, inv, investigations_root=self.tmp, mode="tools",
                              tool_limits=dict(LIMITS, **(limits or {})))
        return s, inv


# ===============================================================================================================
# A. Tool registry
# ===============================================================================================================
class Registry(unittest.TestCase):
    def test_exactly_the_eight_read_only_tools(self):
        self.assertEqual(set(tools.REGISTRY), {"get_source_record", "search_bank_entries", "get_cashbook_entries",
                                               "get_settlement_batch", "search_customer_transactions",
                                               "get_customer_balance_snapshots", "get_reconciliation_evidence",
                                               "follow_relationship"})
        self.assertEqual(set(tools.RELATIONSHIPS), {"settlement_line_to_transaction", "settlement_line_to_batch",
                                                    "transaction_to_batch", "refund_to_original_transaction",
                                                    "settlement_batch_to_bank_entry", "cashbook_to_bank_entry",
                                                    "bank_entry_to_statement", "external_recon_to_confirmation"})

    def test_strict_function_definitions(self):
        defs = openai_inv([]).tool_definitions()
        self.assertEqual(len(defs), 8)
        for d in defs:
            p = d["parameters"]
            self.assertEqual((d["type"], d["strict"], p["additionalProperties"]), ("function", True, False), d["name"])
            self.assertEqual(set(p["required"]), set(p["properties"]), d["name"])
            for banned in ("retrieved_via", "source_file", "source_line", "file_sha256", "join_key", "path", "query", "where"):
                self.assertNotIn(banned, p["properties"], d["name"])

    def test_valid_requests(self):
        for name, args in (("get_source_record", {"evidence_id": "IN-09:BE-GBP-0916-T01"}),
                           ("search_bank_entries", {"account_id": "SGA-GBP-01", "bank_reference": "SB-GBP-20260915", "date_from": None, "date_to": None}),
                           ("get_cashbook_entries", {"account_id": "SGA-GBP-01", "payment_reference": None, "date_from": "2026-09-15", "date_to": "2026-09-16"}),
                           ("get_settlement_batch", {"batch_id": "SB-GBP-20260915"}),
                           ("search_customer_transactions", {"client_id": "C0002", "txn_id": None, "date_from": "2026-09-01", "date_to": "2026-09-30", "transaction_type": "REFUND"}),
                           ("get_customer_balance_snapshots", {"client_id": "C0002", "currency": "GBP", "date_from": "2026-09-14", "date_to": "2026-09-15"}),
                           ("get_reconciliation_evidence", {"account_id": "SGA-EUR-01", "currency": "EUR", "date": "2026-09-15"}),
                           ("follow_relationship", {"evidence_id": "IN-10:LE-GBP-0915-0005", "relationship": "cashbook_to_bank_entry"})):
            a, err = tools.parse_request(name, json.dumps(args))
            self.assertIsNone(err, name)

    def test_rejections(self):
        cases = [("read_file", {"path": "uc042_dataset/scn_SC2_settlement_timing/answer_key.json"}, "unknown tool"),
                 ("run_sql", {"query": "select * from bank"}, "unknown tool"),
                 ("get_settlement_batch", {"batch_id": 42}, "Input should be a valid string"),
                 ("search_bank_entries", {"account_id": "../../uc042_dataset", "bank_reference": "X", "date_from": None, "date_to": None}, "pattern"),
                 ("get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "USD", "date": "2026-09-15"}, "currency"),
                 ("get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": "2026-02-30"}, "invalid date"),
                 ("get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": "15/09/2026"}, "pattern"),
                 ("get_settlement_batch", {}, "Field required"),
                 ("get_source_record", {"evidence_id": "IN-09:../../answer_key.json"}, "pattern"),
                 ("get_source_record", {"evidence_id": "IN-15:ack_letter_SGA-GBP-01.pdf"}, "pattern"),
                 ("get_source_record", {"evidence_id": "/etc/passwd"}, "pattern"),
                 ("search_bank_entries", {"account_id": "SGA-GBP-01", "bank_reference": None, "date_from": None, "date_to": None,
                                          "where": "amount > 0"}, "Extra inputs are not permitted"),
                 ("get_settlement_batch", {"batch_id": "SB-GBP-20260915", "retrieved_via": "trust me"}, "Extra inputs"),
                 ("search_bank_entries", {"account_id": "SGA-GBP-01", "bank_reference": None, "date_from": None, "date_to": None}, "required"),
                 ("get_cashbook_entries", {"account_id": "SGA-GBP-01", "payment_reference": None, "date_from": "2026-09-01", "date_to": "2026-09-30"}, "longer than"),
                 ("search_customer_transactions", {"client_id": None, "txn_id": None, "date_from": None, "date_to": None, "transaction_type": None}, "give txn_id"),
                 ("search_customer_transactions", {"client_id": "C0002", "txn_id": "TX-1", "date_from": None, "date_to": None, "transaction_type": None}, "on its own"),
                 ("get_customer_balance_snapshots", {"client_id": "C0002", "currency": "GBP", "date_from": "2026-09-15", "date_to": "2026-09-14"}, "before"),
                 ("follow_relationship", {"evidence_id": "IN-10:LE-GBP-0915-0005", "relationship": "any_join"}, "relationship"),
                 ("get_settlement_batch", "{not json", "not valid JSON"),
                 ("get_settlement_batch", "[1, 2]", "JSON object")]
        for name, args, expect in cases:
            with self.subTest(name=name, args=args):
                a, err = tools.parse_request(name, args if isinstance(args, str) else json.dumps(args))
                self.assertIsNone(a)
                self.assertIn(expect, err)

    def test_dataset_level_rejections(self):
        case, packet, store = setup_case("SC2", "EXC-SC2-01")
        col = collector_from_packet(packet)
        for name, args, expect in (("search_bank_entries", dict(account_id="SGA-USD-99", bank_reference="X", date_from=None, date_to=None), "unknown account"),
                                   ("get_reconciliation_evidence", dict(account_id="SGA-GBP-01", currency="EUR", date="2026-09-15"), "GBP account"),
                                   ("follow_relationship", dict(evidence_id="IN-11:TX-0915-00009", relationship="transaction_to_batch"), "not in the evidence"),
                                   ("follow_relationship", dict(evidence_id="IN-10:LE-GBP-0915-0005", relationship="bank_entry_to_statement"), "starts from a IN-09")):
            with self.subTest(name=name), self.assertRaises(tools.ToolInputError) as cm:
                tools.execute(name, req(name, **args), store, col)
            self.assertIn(expect, str(cm.exception))


# ===============================================================================================================
# B. Tool execution, provenance and the evidence ledger (real packs and data)
# ===============================================================================================================
class Execution(unittest.TestCase):
    def assertProvenance(self, record, pack, dataset):
        manifest = {i["file_id"]: i["sha256_actual"] for i in pack["audit_trail"]["inputs"]}
        self.assertEqual(record["file_sha256"], manifest[record["file_id"]])
        line = (ROOT / "uc042_dataset" / dataset / record["source_file"]).read_text().splitlines()[record["source_line"] - 1]
        self.assertTrue(line.startswith(record["evidence_id"].split(":", 1)[1] + ","), record["evidence_id"])
        self.assertTrue(record["retrieved_via"].startswith("tool ") and record["join_key"])

    def test_bank_cashbook_and_relationships_with_provenance(self):
        case, packet, store = setup_case("SC2", "EXC-SC2-01")
        pack = load_pack(PACK["SC2"])
        col = collector_from_packet(packet)
        r = tools.execute("search_bank_entries", req("search_bank_entries", account_id="SGA-GBP-01", bank_reference=None,
                                                     date_from="2026-09-17", date_to="2026-09-17"), store, col)
        self.assertEqual(r["status"], "OK")
        self.assertTrue(r["new_evidence_ids"] and all(e.startswith("IN-09:") for e in r["evidence_ids"]))
        for e in r["new_evidence_ids"]:
            self.assertProvenance(col.records[e], pack, "scn_SC2_settlement_timing")
        r = tools.execute("get_cashbook_entries", req("get_cashbook_entries", account_id="SGA-GBP-01", payment_reference="SB-GBP-20260915",
                                                      date_from=None, date_to=None), store, col)
        self.assertEqual(r["evidence_ids"], ["IN-10:LE-GBP-0915-0005"])
        r = tools.execute("follow_relationship", req("follow_relationship", evidence_id="IN-10:LE-GBP-0915-0005",
                                                     relationship="cashbook_to_bank_entry"), store, col)
        self.assertEqual(r["evidence_ids"], ["IN-09:BE-GBP-0916-T01"])
        rel = next(r for r in col.relationships if r["relationship"] == tools.RELATIONSHIPS["cashbook_to_bank_entry"][4])
        self.assertEqual((rel["from"], rel["to"]), ("IN-10:LE-GBP-0915-0005", "IN-09:BE-GBP-0916-T01"))
        self.assertIn("SB-GBP-20260915", rel["join_key"])
        for rel, src, expect in (("bank_entry_to_statement", "IN-09:BE-GBP-0916-T01", "IN-08:ST-SGA-GBP-01-20260916-EOD"),
                                 ("external_recon_to_confirmation", "IN-06:ERL-SGA-GBP-01-20260915", "IN-07:ST-SGA-GBP-01-20260915-1700"),
                                 ("settlement_batch_to_bank_entry", "IN-12:SB-GBP-20260915", "IN-09:BE-GBP-0916-T01")):
            r = tools.execute("follow_relationship", req("follow_relationship", evidence_id=src, relationship=rel), store, col)
            self.assertEqual(r["evidence_ids"], [expect], rel)

    def test_settlement_batch_lines_transactions_and_missing_transaction(self):
        case, packet, store = setup_case("SC5A", "EXC-SC5A-01")
        pack = load_pack(PACK["SC5A"])
        col = Collector()  # empty evidence, so every record below is newly retrieved by the tool
        r = tools.execute("get_settlement_batch", req("get_settlement_batch", batch_id="SB-GBP-20260915"), store, col)
        files = {e.split(":")[0] for e in r["evidence_ids"]}
        self.assertEqual(files, {"IN-12", "IN-13", "IN-11"})
        missing = [s for s in col.searches if s["result"] == "NOT_FOUND"]
        self.assertTrue(any("TX-0915-00009" in s["description"] for s in missing))
        for e in r["new_evidence_ids"]:
            self.assertProvenance(col.records[e], pack, "scn_SC5A_missing_transaction")
        line = next(e for e in r["evidence_ids"] if e.startswith("IN-13:"))
        r2 = tools.execute("follow_relationship", req("follow_relationship", evidence_id=line, relationship="settlement_line_to_batch"), store, col)
        self.assertEqual(r2["evidence_ids"], ["IN-12:SB-GBP-20260915"])
        r3 = tools.execute("follow_relationship", req("follow_relationship", evidence_id="IN-13:SL-SB-GBP-20260915-0003",
                                                     relationship="settlement_line_to_transaction"), store, col)
        self.assertEqual((r3["status"], r3["evidence_ids"]), ("NOT_FOUND", []))
        self.assertEqual(col.searches[-1]["result"], "NOT_FOUND")
        r4 = tools.execute("search_customer_transactions", req("search_customer_transactions", txn_id="TX-0915-00009", client_id=None,
                                                               date_from=None, date_to=None, transaction_type=None), store, col)
        self.assertEqual((r4["status"], len(r4["search_ids"])), ("NOT_FOUND", 1))

    def test_customer_transactions_snapshots_and_refund_link(self):
        case, packet, store = setup_case("SC5C", "EXC-SC5C-01")
        col = collector_from_packet(packet)
        refund = next(r for r in packet["source_records"] if r["file_id"] == "IN-11" and r["fields"]["txn_type"] == "REFUND")
        r = tools.execute("follow_relationship", req("follow_relationship", evidence_id=refund["evidence_id"],
                                                     relationship="refund_to_original_transaction"), store, col)
        self.assertEqual(r["evidence_ids"], [f"IN-11:{refund['fields']['original_txn_id']}"])
        client, ccy = refund["fields"]["client_id"], refund["fields"]["currency"]
        r = tools.execute("search_customer_transactions", req("search_customer_transactions", client_id=client, txn_id=None, date_from="2026-09-01",
                                                              date_to="2026-09-30", transaction_type="REFUND"), store, col)
        self.assertIn(refund["evidence_id"], r["evidence_ids"])
        self.assertTrue(all(col.records[e]["fields"]["txn_type"] == "REFUND" for e in r["evidence_ids"]))
        r = tools.execute("get_customer_balance_snapshots", req("get_customer_balance_snapshots", client_id=client, currency=ccy,
                                                                date_from="2026-09-08", date_to="2026-09-10"), store, col)
        snaps = [col.records[e]["fields"] for e in r["evidence_ids"]]
        self.assertTrue(snaps and all(s["currency"] == ccy and s["client_id"] == client for s in snaps))
        r = tools.execute("follow_relationship", req("follow_relationship", evidence_id=refund["evidence_id"],
                                                     relationship="transaction_to_batch"), store, col)
        self.assertIn(r["status"], ("OK", "NOT_FOUND"))

    def test_reconciliation_evidence_and_missing_bank_evidence(self):
        case, packet, store = setup_case("S02", "EXC-S02-01")
        col = collector_from_packet(packet)
        r = tools.execute("get_reconciliation_evidence", req("get_reconciliation_evidence", account_id="SGA-EUR-01", currency="EUR",
                                                             date="2026-09-15"), store, col)
        by_desc = {s["description"]: s for s in col.searches if s["search_id"] in r["search_ids"]}
        self.assertEqual(by_desc["17:00 bank balance confirmation for SGA-EUR-01 on 2026-09-15"]["result"], "NOT_FOUND")
        self.assertEqual(by_desc["End-of-day bank statement for SGA-EUR-01 on 2026-09-15"]["result"], "NOT_FOUND")
        self.assertEqual(by_desc["External reconciliation record for SGA-EUR-01 on 2026-09-15"]["result"], "FOUND")
        for e in r["evidence_ids"]:  # no fabricated or zero records for the missing day
            self.assertNotIn("20260915-1700", e)

    def test_ledger_update_citations_conflicts_and_hash(self):
        case, full, store = setup_case("SC2", "EXC-SC2-01")
        route = full["investigation_route"]
        col = retrieve(route, case, store)
        col.records.pop("IN-14:DL-0001")  # start from a packet without the log entry, so a tool has to find it
        col.relationships = [r for r in col.relationships if r["to"] != "IN-14:DL-0001"]
        packet = build_packet(case, build_scope(case), route, col)
        self.assertFalse(any("DL-0001" in c["description"] for c in packet["conflicts"]))
        led0 = build_ledger(packet, case, collector_from_packet(packet))
        lcol = collector_from_packet(packet)
        r = tools.execute("get_reconciliation_evidence", req("get_reconciliation_evidence", account_id="SGA-GBP-01", currency="GBP",
                                                             date="2026-09-15"), store, lcol)
        self.assertIn("IN-14:DL-0001", r["new_evidence_ids"])
        led = build_ledger(packet, case, lcol)
        self.assertTrue(set(r["evidence_ids"]) | set(r["search_ids"]) <= set(led["allowed_citation_ids"]))
        self.assertNotEqual(led["ledger_sha256"], led0["ledger_sha256"])
        conflict = next(c for c in led["conflicts"] if "DL-0001" in c["description"])  # conflicting evidence, detected deterministically
        self.assertIn(conflict["conflict_id"], led["allowed_citation_ids"])
        body = {k: v for k, v in led.items() if k != "ledger_sha256"}
        self.assertEqual(hashlib.sha256(canonical(body).encode()).hexdigest(), led["ledger_sha256"])
        self.assertEqual(led["initial_packet_sha256"], packet["packet_sha256"])

    def test_per_call_and_total_record_limits(self):
        case, packet, store = setup_case("SC2", "EXC-SC2-01")
        col = collector_from_packet(packet)
        a = req("search_bank_entries", account_id="SGA-GBP-01", bank_reference=None, date_from="2026-09-01", date_to="2026-09-07")
        r = tools.execute("search_bank_entries", a, store, col, max_records=3)
        self.assertEqual((len(r["evidence_ids"]), r["truncated"]), (3, True))
        with mock.patch.object(config, "MAX_RECORDS", len(col.records) + 2):
            r = tools.execute("get_cashbook_entries", req("get_cashbook_entries", account_id="SGA-GBP-01", payment_reference=None,
                                                          date_from="2026-09-01", date_to="2026-09-07"), store, col)
        self.assertEqual(len(r["new_evidence_ids"]), 2)
        self.assertTrue(r["not_added_evidence_limit"])
        self.assertIn("evidence limit", r["note"])

    def test_forbidden_files_never_opened_by_tools(self):
        import builtins
        real_open, opened = builtins.open, []

        def spy(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)
        case, packet, store = setup_case("SC5A", "EXC-SC5A-01")
        col = collector_from_packet(packet)
        with mock.patch("builtins.open", spy):
            for name, args in (("get_settlement_batch", {"batch_id": "SB-GBP-20260915"}),
                               ("get_source_record", {"evidence_id": "IN-01:2026-09-15"}),
                               ("get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": "2026-09-15"})):
                tools.execute(name, req(name, **args), store, col)
        self.assertEqual([p for p in opened if os.path.basename(p) in config.FORBIDDEN_NAMES or "golden" in p], [])


# ===============================================================================================================
# C. Responses API tool loop (mocked API; real adapter, subgraph and outer graph)
# ===============================================================================================================
class ToolLoop(Temp):
    def setUp(self):
        super().setUp()
        self.good = offline_output("SC2", "EXC-SC2-01")

    def with_line_finding(self):
        out = copy.deepcopy(self.good)
        out["confirmed_findings"].append({"finding_id": "F-09", "claim": "Settlement batch SB-GBP-20260915 has settlement line SL-SB-GBP-20260915-0001.",
                                          "explanation": "Shown by the settlement line record retrieved by a tool.",
                                          "evidence_ids": ["IN-13:SL-SB-GBP-20260915-0001"], "supporting_records": ["IN-13:SL-SB-GBP-20260915-0001"]})
        return out

    def test_no_tool_call_final_answer(self):
        s, inv = self.run_tools([final(self.good)])
        r = s["result"]
        self.assertEqual((r["investigation_status"], r["validation_status"], r["investigation_mode"]), ("COMPLETED", "VALID", "tools"))
        self.assertEqual((r["tool_summary"]["tool_calls_requested"], r["tool_summary"]["llm_calls"]), (0, 1))
        k = requests_of(inv)[0]
        self.assertEqual((k["tool_choice"], k["store"], k["include"], k["instructions"]),
                         ("auto", False, ["reasoning.encrypted_content"], TOOLS_SYSTEM_PROMPT))
        self.assertEqual(len(k["tools"]), 8)
        self.assertIs(k["text_format"], LLMInvestigationOutput)
        for p in ("temperature", "top_p"):
            self.assertNotIn(p, k)

    def test_one_tool_call_history_and_call_id_linkage(self):
        call = fc("call_A", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})
        s, inv = self.run_tools([calls(call), final(self.with_line_finding())])
        r = s["result"]
        self.assertEqual((r["validation_status"], s["persist_outcome"]), ("VALID", "PUBLISHED"))
        second = requests_of(inv)[1]["input"]
        self.assertEqual(second[0]["role"], "user")
        self.assertEqual(second[1:3], [REASONING, call])  # complete prior output preserved, unchanged
        out = second[3]
        self.assertEqual((out["type"], out["call_id"]), ("function_call_output", "call_A"))
        payload = json.loads(out["output"])
        self.assertEqual(payload["status"], "OK")
        self.assertIn("IN-13:SL-SB-GBP-20260915-0001", payload["evidence_ids"])
        rec = next(x for x in payload["records"] if x["evidence_id"] == "IN-13:SL-SB-GBP-20260915-0001")
        self.assertTrue(rec["retrieved_via"].startswith("tool get_settlement_batch"))
        t = s["tool_calls"][0]
        self.assertEqual((t["call_id"], t["tool"], t["status"], t["arguments"]), ("call_A", "get_settlement_batch", "OK", {"batch_id": "SB-GBP-20260915"}))
        for k in ("requested_at", "latency_ms", "evidence_ids", "records_returned", "deduplicated", "error"):
            self.assertIn(k, t)

    def test_multiple_calls_in_one_response_and_multiple_rounds(self):
        a = fc("c1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})
        b = fc("c2", "get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": "2026-09-14"})
        c = fc("c3", "follow_relationship", {"evidence_id": "IN-09:BE-GBP-0916-T01", "relationship": "bank_entry_to_statement"})
        s, inv = self.run_tools([calls(a, b), calls(c), final(self.with_line_finding())])
        reqs = requests_of(inv)
        outs = [i for i in reqs[1]["input"] if i.get("type") == "function_call_output"]
        self.assertEqual([o["call_id"] for o in outs], ["c1", "c2"])
        self.assertEqual([i.get("call_id") for i in reqs[2]["input"] if i.get("type") == "function_call_output"], ["c1", "c2", "c3"])
        ts = s["result"]["tool_summary"]
        self.assertEqual((ts["tool_rounds"], ts["tool_calls_requested"], ts["tools_executed"], ts["llm_calls"]), (2, 3, 3, 3))
        self.assertGreater(ts["records_final"], ts["records_initial"])

    def test_unknown_tool_invalid_json_and_tool_failure_are_reported_to_the_model(self):
        bad = [fc("u1", "delete_exception", {"exception_id": "EXC-SC2-01"}), fc("u2", "get_settlement_batch", "{oops"),
               fc("u3", "get_cashbook_entries", {"account_id": "SGA-GBP-01", "payment_reference": "SB-GBP-20260915",
                                                 "date_from": None, "date_to": None})]
        with mock.patch.dict(tools.REGISTRY, {"get_cashbook_entries": tools.Tool("get_cashbook_entries", "x", tools.GetCashbookEntriesArgs,
                                                                                mock.Mock(side_effect=RuntimeError("disk")))}), \
                self.assertLogs("uc042.investigation", level="ERROR"):
            s, inv = self.run_tools([calls(*bad), final(self.good)])
        payloads = {o["call_id"]: json.loads(o["output"]) for o in requests_of(inv)[1]["input"] if o.get("type") == "function_call_output"}
        self.assertEqual({k: v["status"] for k, v in payloads.items()}, {"u1": "REJECTED", "u2": "REJECTED", "u3": "ERROR"})
        self.assertIn("unknown tool", payloads["u1"]["error"])
        self.assertNotIn("disk", payloads["u3"]["error"])  # internal details stay in the transcript, not in the model context
        self.assertEqual(s["result"]["validation_status"], "VALID")
        self.assertEqual(sorted(t["status"] for t in s["tool_calls"]), ["ERROR", "REJECTED", "REJECTED"])

    def test_provider_failures(self):
        for responses, reason in (([status_body("completed", output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}])], "refusal"),
                                  ([status_body("incomplete", incomplete_details={"reason": "content_filter"})], "incomplete"),
                                  ([status_body("incomplete", incomplete_details={"reason": "max_output_tokens"})], "max_output_tokens"),
                                  ([openai.AuthenticationError("bad key", response=httpx2.Response(401, request=REQ), body=None)], "authentication"),
                                  ([openai.RateLimitError("slow", response=httpx2.Response(429, request=REQ), body=None)], "rate_limit"),
                                  ([openai.APITimeoutError(request=REQ)], "timeout")):
            with self.subTest(reason=reason):
                s, _ = self.run_tools(responses)
                r = s["result"]
                self.assertEqual((r["investigation_status"], s["persist_outcome"], r["tool_summary"]["stop_reason"]), ("FAILED", "NOT_PUBLISHED", reason))
                self.assertIn(f"ToolLoop[{reason}]", r["failure_reason"])

    def test_max_tool_calls(self):
        three = [fc(f"m{i}", "get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": f"2026-09-0{i + 1}"}) for i in range(3)]
        s, inv = self.run_tools([calls(*three), final(self.good)], limits={"max_tool_calls": 2})
        self.assertEqual([t["status"] for t in s["tool_calls"]], ["OK", "OK", "BUDGET_EXHAUSTED"])
        payloads = [json.loads(o["output"]) for o in requests_of(inv)[1]["input"] if o.get("type") == "function_call_output"]
        self.assertTrue(all("budget" in p for p in payloads))
        self.assertEqual(s["result"]["validation_status"], "VALID")
        s, _ = self.run_tools([calls(*three), calls(fc("m9", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"}))],
                              limits={"max_tool_calls": 2})
        self.assertEqual((s["result"]["investigation_status"], s["result"]["tool_summary"]["stop_reason"]),
                         ("FAILED", "budget_exhausted_without_findings"))

    def test_max_rounds(self):
        a = fc("r1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})
        b = fc("r2", "get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": "2026-09-14"})
        s, _ = self.run_tools([calls(a), calls(b)], limits={"max_rounds": 1})
        self.assertEqual(s["result"]["tool_summary"]["stop_reason"], "budget_exhausted_without_findings")
        self.assertEqual([t["status"] for t in s["tool_calls"]], ["OK"])  # the second request was never executed
        s, _ = self.run_tools([calls(a), final(self.with_line_finding())], limits={"max_rounds": 1})
        self.assertEqual((s["result"]["validation_status"], s["result"]["tool_summary"]["tool_rounds"]), ("VALID", 1))

    def test_total_timeout_and_input_token_budget_stop_before_any_request(self):
        for limits, reason in (({"total_timeout": 1.0}, "timeout_budget"), ({"max_input_tokens": 100}, "input_token_budget")):
            with self.subTest(reason=reason):
                s, inv = self.run_tools([final(self.good)], limits=limits)
                self.assertEqual((s["result"]["investigation_status"], s["result"]["tool_summary"]["stop_reason"]), ("FAILED", reason))
                self.assertEqual(requests_of(inv), [])

    def test_timeout_during_the_loop(self):
        a = fc("t1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})
        clock = iter([0.0, 0.0, 400.0, 400.0, 400.0, 400.0])
        with mock.patch("uc042lib.investigation.tool_loop._clock", side_effect=lambda: next(clock, 400.0)):
            s, inv = self.run_tools([calls(a), final(self.good)])
        self.assertEqual(s["result"]["tool_summary"]["stop_reason"], "timeout_budget")
        self.assertEqual(len(requests_of(inv)), 1)

    def test_duplicate_tool_calls_are_not_re_executed_but_count(self):
        args = {"batch_id": "SB-GBP-20260915"}
        counted = mock.Mock(wraps=tools.get_settlement_batch)
        with mock.patch.dict(tools.REGISTRY, {"get_settlement_batch": tools.Tool("get_settlement_batch", "x", tools.GetSettlementBatchArgs, counted)}):
            s, inv = self.run_tools([calls(fc("d1", "get_settlement_batch", args), fc("d2", "get_settlement_batch", args)),
                                     calls(fc("d3", "get_settlement_batch", dict(args))), final(self.good)])
        self.assertEqual(counted.call_count, 1)
        self.assertEqual([(t["call_id"], t["status"], t["deduplicated"]) for t in s["tool_calls"]],
                         [("d1", "OK", False), ("d2", "DEDUPLICATED", True), ("d3", "DEDUPLICATED", True)])
        self.assertEqual(s["result"]["tool_summary"]["tool_calls_requested"], 3)
        dup = json.loads([o for o in requests_of(inv)[2]["input"] if o.get("call_id") == "d3" and o["type"] == "function_call_output"][0]["output"])
        self.assertEqual(dup["status"], "DEDUPLICATED")
        self.assertIn("IN-12:SB-GBP-20260915", dup["evidence_ids"])

    def test_invalid_final_answer_gets_one_correction(self):
        s, inv = self.run_tools([bad_final(), final(self.good)])
        self.assertEqual(s["result"]["validation_status"], "VALID")
        self.assertIn("did not match the required JSON schema", requests_of(inv)[1]["input"][-1]["content"])
        s, _ = self.run_tools([bad_final(), bad_final()])
        self.assertEqual(s["result"]["tool_summary"]["stop_reason"], "invalid_final_output")

    def test_tools_mode_requires_a_tool_capable_provider(self):
        for inv in (OFFLINE, AnthropicInvestigator.__new__(AnthropicInvestigator)):
            with self.subTest(provider=inv.provider):
                s, _ = self.run_tools([], inv=inv)
                self.assertEqual(s["result"]["investigation_status"], "FAILED")
                self.assertIn("does not support UC042_INVESTIGATION_MODE=tools", s["result"]["failure_reason"])

    def test_fixed_mode_is_the_default_and_unchanged(self):
        s = run_investigation(PACK["SC2"], "EXC-SC2-01", OFFLINE, investigations_root=self.tmp)
        r = s["result"]
        self.assertEqual((r["investigation_mode"], r["evidence_ledger_sha256"], r["model_metadata"]["workflow_version"]),
                         ("fixed", "", config.WORKFLOW_VERSION))
        self.assertNotIn("ledger", s)
        self.assertFalse((Path(s["artefact_path"]) / "evidence_ledger.json").exists())
        with mock.patch.dict(os.environ, {config.ENV_MODE: ""}, clear=False):
            self.assertEqual(config.investigation_mode(), "fixed")
        with mock.patch.dict(os.environ, {config.ENV_MODE: "agents"}):
            with self.assertRaises(ValueError):
                config.investigation_mode()


# ===============================================================================================================
# D. Finding validation against the accumulated ledger
# ===============================================================================================================
class LedgerValidation(Temp):
    def test_tool_returned_citation_is_valid_only_with_the_ledger(self):
        case, packet, store = setup_case("SC2", "EXC-SC2-01")
        col = collector_from_packet(packet)
        tools.execute("get_settlement_batch", req("get_settlement_batch", batch_id="SB-GBP-20260915"), store, col)
        ledger = build_ledger(packet, case, col)
        out = OFFLINE.investigate(packet)[0].model_dump()
        out["confirmed_findings"][0]["evidence_ids"].append("IN-13:SL-SB-GBP-20260915-0002")
        o = LLMInvestigationOutput.model_validate(out)
        self.assertTrue(any("not present" in e for e in validate_output(o, packet, case)[0]))
        self.assertEqual(validate_output(o, ledger, case)[0], [])

    def test_rule_violations_are_rejected_and_not_published(self):
        base = offline_output("SC2", "EXC-SC2-01")
        sc5a = offline_output("SC5A", "EXC-SC5A-01")
        s02 = offline_output("S02", "EXC-S02-01")

        def edit(d, f):
            d = copy.deepcopy(d)
            f(d)
            return d
        cases = [("SC2", "EXC-SC2-01", edit(base, lambda d: d["confirmed_findings"][0]["evidence_ids"].append("IN-09:BE-INVENTED-1")), "not present"),
                 ("SC5A", "EXC-SC5A-01", edit(sc5a, lambda d: d["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")), "candidate"),
                 ("SC2", "EXC-SC2-01", edit(base, lambda d: d["confirmed_findings"][0].update(claim="The difference was caused by bank processing delay.")), "cause"),
                 ("SC2", "EXC-SC2-01", edit(base, lambda d: d["confirmed_findings"][0].update(explanation="This may be due to a delay; the root cause is timing.")), "cause"),
                 ("S02", "EXC-S02-01", edit(s02, lambda d: d.update(missing_evidence=[m for m in d["missing_evidence"] if "MISS-01" not in m["related_ids"]])), "missing evidence not preserved"),
                 ("SC2", "EXC-SC2-01", edit(base, lambda d: d.update(investigation_summary="The exception has been resolved and closed by this investigation.")), "resolved"),
                 ("S02", "EXC-S02-01", edit(s02, lambda d: d["confirmed_findings"][0].update(claim="The EUR bank balance was 0.00 on 15 September.")), "zero"),
                 ("S02", "EXC-S02-01", edit(s02, lambda d: d["missing_evidence"][0].update(description="The 15 September statement does not exist.")), "does not exist")]
        for scenario, eid, out, expect in cases:
            with self.subTest(expect=expect):
                s, _ = self.run_tools([final(out)], scenario=scenario, exception_id=eid)
                r = s["result"]
                self.assertEqual((r["validation_status"], s["persist_outcome"]), ("REJECTED", "NOT_PUBLISHED"))
                self.assertTrue(any(expect in e for e in r["validation_findings"]), r["validation_findings"])
        ok = edit(s02, lambda d: d["missing_evidence"][0].update(description="The statement does not exist in the supplied data."))
        s, _ = self.run_tools([final(ok)], scenario="S02", exception_id="EXC-S02-01")
        self.assertEqual(s["result"]["validation_status"], "VALID")

    def test_nonexistence_rule_accepts_negated_statements(self):
        from uc042lib.investigation.validation import claims_nonexistence
        # this sentence came from a live gpt-6-luna run (S02) and was wrongly rejected before the negation check
        self.assertFalse(claims_nonexistence("This establishes an evidence gap, not that such records never existed."))
        self.assertFalse(claims_nonexistence("A NOT_FOUND search does not prove the statement never existed."))
        self.assertFalse(claims_nonexistence("The statement does not exist in the supplied data."))
        self.assertTrue(claims_nonexistence("The 15 September statement never existed."))
        self.assertTrue(claims_nonexistence("The confirmation does not exist."))

    def test_classification_summary_distinguishes_gap_types(self):
        s, _ = self.run_tools([final(offline_output("S02", "EXC-S02-01"))], scenario="S02", exception_id="EXC-S02-01")
        c = s["result"]["classification_summary"]
        self.assertTrue(c["evidence_gaps"]["engine_missing_evidence"] and c["evidence_gaps"]["searched_not_found"])
        self.assertTrue(set(c) >= {"EVIDENCE_BACKED", "HYPOTHESIS", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"})
        s, _ = self.run_tools([final(offline_output("SC5A", "EXC-SC5A-01"))], scenario="SC5A", exception_id="EXC-SC5A-01")
        self.assertEqual(s["result"]["classification_summary"]["unverified_candidate_relationships"], ["CAND-SC5A-01"])
        self.assertEqual(s["result"]["classification_summary"]["HYPOTHESIS"], ["H-01"])


# ===============================================================================================================
# E. Persistence and audit trail
# ===============================================================================================================
class ToolPersistence(Temp):
    def published(self):
        out = offline_output("SC2", "EXC-SC2-01")
        out["confirmed_findings"].append({"finding_id": "F-09", "claim": "Settlement line SL-SB-GBP-20260915-0001 belongs to batch SB-GBP-20260915.",
                                          "explanation": "Shown by the retrieved settlement line.", "evidence_ids": ["IN-13:SL-SB-GBP-20260915-0001"],
                                          "supporting_records": ["IN-13:SL-SB-GBP-20260915-0001"]})
        s, _ = self.run_tools([calls(fc("p1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})), final(out)])
        return s, out

    def test_ledger_transcript_and_hashes_are_persisted(self):
        s, _ = self.published()
        d = Path(s["artefact_path"])
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["evidence_ledger.json", "evidence_packet.json", "findings.json", "runs", "tool_calls.json"])
        findings = json.loads((d / "findings.json").read_text())
        ledger = json.loads((d / "evidence_ledger.json").read_text())
        packet = json.loads((d / "evidence_packet.json").read_text())
        body = {k: v for k, v in ledger.items() if k != "ledger_sha256"}
        recomputed = hashlib.sha256((json.dumps(body, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode()).hexdigest()
        self.assertEqual(recomputed, ledger["ledger_sha256"])
        self.assertEqual(findings["evidence_ledger_sha256"], ledger["ledger_sha256"])
        self.assertEqual((ledger["initial_packet_sha256"], findings["evidence_packet_sha256"]), (packet["packet_sha256"], packet["packet_sha256"]))
        self.assertIn("IN-13:SL-SB-GBP-20260915-0001", {r["evidence_id"] for r in ledger["source_records"]})
        pack = load_pack(PACK["SC2"])
        self.assertEqual((findings["pack_id"], findings["pack_content_sha256"], findings["exception_id"]),
                         (PACK["SC2"], pack["audit_trail"]["pack_content_sha256"], "EXC-SC2-01"))
        m = findings["model_metadata"]
        self.assertEqual((m["investigation_mode"], m["tool_registry_version"], m["prompt_version"], m["workflow_version"]),
                         ("tools", tools.TOOL_REGISTRY_VERSION, config.TOOLS_PROMPT_VERSION, config.TOOLS_WORKFLOW_VERSION))
        self.assertEqual(m["usage"]["input_tokens"], 2000)
        transcript = json.loads((d / "tool_calls.json").read_text())
        self.assertEqual(transcript["tool_calls"][0]["call_id"], "p1")
        run = json.loads((d / "runs" / "0001.json").read_text())
        for name in ("evidence_ledger.json", "tool_calls.json"):
            self.assertEqual(run["artefact_sha256"][name], hashlib.sha256((d / name).read_bytes()).hexdigest())
        self.assertEqual(run["investigation_mode"], "tools")

    def test_failed_tool_run_keeps_transcript_unpublished(self):
        s, _ = self.run_tools([calls(fc("f1", "get_settlement_batch", {"batch_id": "SB-GBP-20260915"})),
                               status_body("incomplete", incomplete_details={"reason": "max_output_tokens"})])
        self.assertEqual(s["persist_outcome"], "NOT_PUBLISHED")
        rec = json.loads(Path(s["artefact_path"]).read_text())
        self.assertEqual((rec["result"]["validation_status"], rec["tool_calls"]["tool_calls"][0]["call_id"]), ("NOT_VALIDATED", "f1"))
        self.assertEqual(list(self.tmp.rglob("findings.json")), [])

    def test_atomic_publication_failure_leaves_nothing(self):
        real = os.replace

        def fail(src, dst):
            if Path(src).is_dir():
                raise PermissionError("simulated")
            return real(src, dst)
        with mock.patch("uc042lib.investigation.persistence.os.replace", side_effect=fail):
            s, _ = self.published()
        self.assertEqual(s["persist_outcome"], "PERSIST_FAILED")
        self.assertEqual([p for p in self.tmp.rglob("*") if p.is_file()], [])

    def test_different_tool_runs_never_overwrite_each_other(self):
        a, _ = self.published()
        b, _ = self.run_tools([final(offline_output("SC2", "EXC-SC2-01"))])
        self.assertNotEqual(a["result"]["investigation_id"], b["result"]["investigation_id"])
        self.assertEqual((a["persist_outcome"], b["persist_outcome"]), ("PUBLISHED", "PUBLISHED"))
        self.assertTrue((Path(a["artefact_path"]) / "evidence_ledger.json").exists())


# ===============================================================================================================
# F. Opt-in live smoke test (spends tokens): UC042_RUN_LIVE_TESTS=1 with OPENAI_API_KEY configured
# ===============================================================================================================
@unittest.skipUnless(os.environ.get("UC042_RUN_LIVE_TESTS") == "1" and config.api_key_configured(),
                     "live test: set UC042_RUN_LIVE_TESTS=1 and OPENAI_API_KEY to run (makes real API calls)")
class LiveSmoke(Temp):
    def test_live_tools_mode_investigation(self):
        from uc042lib.investigation.llm import investigator_from_env
        inv = investigator_from_env()
        self.assertTrue(inv.check_availability()["available"])
        s = run_investigation(PACK["SC2"], "EXC-SC2-01", inv, investigations_root=self.tmp, mode="tools", tool_limits=config.tool_limits())
        r = s["result"]
        self.assertEqual((r["investigation_status"], r["model_metadata"]["simulated"]), ("COMPLETED", False), r["failure_reason"])
        self.assertEqual(r["exception_resolution"], "NOT_RESOLVED_BY_INVESTIGATION")


if __name__ == "__main__":
    unittest.main()
