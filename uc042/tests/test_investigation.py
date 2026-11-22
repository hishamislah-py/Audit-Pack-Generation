"""AI investigation layer (LangGraph V1). Run from the uc042/ folder:  python -m unittest -v

Uses the real scenario packs and datasets. Model output comes from the offline SIMULATED investigator or scripted test
doubles (no live LLM). Investigation artefacts are written to temporary folders only.
"""
import builtins
import copy
import glob
import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from uc042lib.investigation import config
from uc042lib.investigation.graph import build_graph, run_investigation
from uc042lib.investigation.llm import (AnthropicInvestigator, LLMCallError, LLMConfigurationError, OfflineSimulatedInvestigator,
                                        ScriptedInvestigator, investigator_from_env, parse_json_object)
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.persistence import ImmutabilityError, persist
from uc042lib.investigation.retrieval import EvidenceStore, RetrievalError, _inside, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.investigation.run import investigate_pack
from uc042lib.investigation.validation import validate_output

ROOT = Path(__file__).resolve().parent.parent
PACK = {os.path.basename(p).split("-")[1]: os.path.basename(p) for p in glob.glob(str(ROOT / "packs" / "PACK-*"))}
OFFLINE = OfflineSimulatedInvestigator()


def sha_tree(*globs):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for g in globs for p in sorted(ROOT.glob(g)) if p.is_file()}


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_case(self, scenario, exception_id, investigator=OFFLINE, **kw):
        return run_investigation(PACK[scenario], exception_id, investigator, investigations_root=self.tmp, **kw)


def packet_for(scenario, exception_id):
    pack = load_pack(PACK[scenario])
    case = build_case(pack, exception_id)
    route = route_for(case["exception"], case["candidates"], case["results"])
    col = retrieve(route, case, EvidenceStore(pack))
    return pack, case, build_packet(case, build_scope(case), route, col)


# ---------------------------------------------------------------------------------------------------------------
class GraphStructure(unittest.TestCase):
    def test_fixed_graph_nodes_and_edges(self):
        g = build_graph().get_graph()
        nodes = set(g.nodes)
        for n in ("load_investigation_case", "identify_investigation_scope", "route_investigation", "build_evidence_packet",
                  "ai_investigation", "validate_findings", "persist_findings"):
            self.assertIn(n, nodes)
        self.assertEqual({n for n in nodes if n.startswith("retrieve_")},
                         {f"retrieve_{r}" for r in ("bank_ledger_mismatch", "settlement_discrepancy", "missing_bank_evidence",
                                                     "customer_balance_discrepancy", "unmatched_bank_entry",
                                                     "unverified_relationship", "insufficient_evidence", "generic")})
        edges = {(e.source, e.target) for e in g.edges}
        for e in [("__start__", "load_investigation_case"), ("identify_investigation_scope", "route_investigation"),
                  ("build_evidence_packet", "ai_investigation"), ("ai_investigation", "validate_findings"),
                  ("validate_findings", "persist_findings"), ("persist_findings", "__end__")]:
            self.assertIn(e, edges)


class LoadAndScope(TempRoot):
    def test_load_case_and_scope(self):
        pack, case, packet = packet_for("SC2", "EXC-SC2-01")
        scope = build_scope(case)
        self.assertEqual((scope["root_cause_kind"], scope["keys"], scope["evidence_status"], scope["amount"]),
                         ("BANK_LEDGER_DIFFERENCE", {"account_id": "SGA-GBP-01", "date": "2026-09-15"}, "TIMING_EVIDENCED", "2868.50"))
        self.assertEqual(case["pack_content_sha256"], pack["audit_trail"]["pack_content_sha256"])

    def test_invalid_ids_and_traversal_rejected(self):
        for pid in ("../packs", "PACK-SC2-PER-2026-09-../../x", "", "PACK-S01-PER-2026-09-ZZZ"):
            with self.assertRaises(RetrievalError):
                load_pack(pid)
        s = run_investigation(PACK["SC2"], "../../etc", OFFLINE, investigations_root=self.tmp)
        self.assertEqual((s["result"]["investigation_status"], s["persist_outcome"]), ("FAILED", "NOT_PUBLISHED"))

    def test_unknown_exception_fails_without_findings(self):
        s = self.run_case("SC2", "EXC-SC2-99")
        r = s["result"]
        self.assertEqual((r["investigation_status"], r["validation_status"], r["confirmed_findings"]), ("FAILED", "NOT_VALIDATED", []))
        self.assertIn("not found", r["failure_reason"])

    def test_modified_pack_is_refused(self):
        packs = self.tmp / "packs"
        shutil.copytree(ROOT / "packs" / PACK["SC2"], packs / PACK["SC2"])
        p = packs / PACK["SC2"] / "pack.json"
        p.write_text(p.read_text().replace("2868.50", "2868.51", 1))
        with self.assertRaises(RetrievalError):
            load_pack(PACK["SC2"], packs)

    def test_changed_source_file_is_refused(self):
        ds = self.tmp / "ds"
        shutil.copytree(ROOT / "uc042_dataset" / "scn_SC2_settlement_timing", ds / "scn_SC2_settlement_timing")
        f = ds / "scn_SC2_settlement_timing" / "source_data" / "transactions_2026-09.csv"
        f.write_text(f.read_text() + "\n")
        with self.assertRaises(RetrievalError):
            EvidenceStore(load_pack(PACK["SC2"]), ds)

    def test_forbidden_files_cannot_be_opened_via_retrieval(self):
        for name in ("answer_key.json", "mutations.json", "SCENARIO_NOTES.md", "scenario.json"):
            with self.assertRaises(RetrievalError):
                _inside(ROOT / "uc042_dataset" / "scn_SC2_settlement_timing" / name, ROOT / "uc042_dataset")


class Routing(unittest.TestCase):
    def test_routes_for_every_real_exception(self):
        expected = {"SC2": {"EXC-SC2-01": "bank_ledger_mismatch"}, "SC3B": {"EXC-SC3B-01": "settlement_discrepancy"},
                    "SC3C": {"EXC-SC3C-01": "bank_ledger_mismatch", "EXC-SC3C-02": "settlement_discrepancy",
                             "EXC-SC3C-03": "settlement_discrepancy"},
                    "S02": {"EXC-S02-01": "missing_bank_evidence"},
                    "SC5A": {"EXC-SC5A-01": "unverified_relationship", "EXC-SC5A-02": "unverified_relationship"},
                    "SC5D": {"EXC-SC5D-01": "customer_balance_discrepancy", "EXC-SC5D-02": "customer_balance_discrepancy",
                             "EXC-SC5D-03": "customer_balance_discrepancy"},
                    "S05": {"EXC-S05-01": "bank_ledger_mismatch", "EXC-S05-02": "unmatched_bank_entry"}}
        for sc, m in expected.items():
            pack = load_pack(PACK[sc])
            for eid, route in m.items():
                case = build_case(pack, eid)
                self.assertEqual(route_for(case["exception"], case["candidates"], case["results"]), route, eid)

    def test_fallback_and_insufficient_paths(self):
        self.assertEqual(route_for({"root_cause": "SOMETHING-NEW|x"}, [], [{"outcome": "FAIL"}]), "generic")
        self.assertEqual(route_for({"root_cause": "OTHER|x"}, [], [{"outcome": "INSUFFICIENT_EVIDENCE"}]), "insufficient_evidence")


class RetrievalAndPacket(unittest.TestCase):
    def test_provenance_on_every_record(self):
        pack, case, packet = packet_for("SC3C", "EXC-SC3C-02")
        manifest = {i["file_id"]: i["sha256_actual"] for i in pack["audit_trail"]["inputs"]}
        ds = ROOT / "uc042_dataset" / "scn_SC3C_short_settlement"
        for r in packet["source_records"]:
            self.assertEqual(r["file_sha256"], manifest[r["file_id"]])
            line = (ds / r["source_file"]).read_text().splitlines()[r["source_line"] - 1]
            self.assertTrue(line.startswith(r["evidence_id"].split(":", 1)[1] + ","), r["evidence_id"])
            self.assertTrue(r["retrieved_via"] and r["join_key"])

    def test_verified_relationship_paths(self):
        _, _, p = packet_for("SC2", "EXC-SC2-01")
        rels = {(r["from"], r["to"]) for r in p["relationships"]}
        self.assertIn(("IN-10:LE-GBP-0915-0005", "IN-09:BE-GBP-0916-T01"), rels)
        self.assertIn(("IN-10:LE-GBP-0915-0005", "IN-12:SB-GBP-20260915"), rels)
        self.assertIn("IN-14:DL-0001", {r["evidence_id"] for r in p["source_records"]})

    def test_negative_searches_are_recorded(self):
        _, _, p = packet_for("SC5A", "EXC-SC5A-01")
        s = {x["description"]: x["result"] for x in p["searches"]}
        self.assertEqual(s["Transaction TX-0915-00009 referenced by settlement line SL-SB-GBP-20260915-0003"], "NOT_FOUND")
        _, _, p = packet_for("S05", "EXC-S05-02")
        s = next(x for x in p["searches"] if "SETTLE 0417" in x["description"])
        self.assertEqual((s["result"], s["found"]), ("NOT_FOUND", []))
        be = next(r for r in p["source_records"] if r["evidence_id"] == "IN-09:BE-GBP-0917-X01")
        self.assertEqual(be["fields"]["counterparty_name"], "")

    def test_customer_refund_evidence_shows_single_refund_and_no_ledger(self):
        _, _, p = packet_for("SC5C", "EXC-SC5C-01")
        refunds = [r for r in p["source_records"] if r["file_id"] == "IN-11" and r["fields"]["txn_type"] == "REFUND"]
        self.assertEqual([r["evidence_id"] for r in refunds], ["IN-11:TX-0909-0R001"])
        self.assertIn("IN-11:TX-0902-00044", {r["evidence_id"] for r in p["source_records"]})
        ledger = next(x for x in p["searches"] if "Posting-level client ledger" in x["description"])
        self.assertEqual(ledger["result"], "NOT_FOUND")

    def test_missing_evidence_and_conflicts_in_packet(self):
        _, _, p = packet_for("S02", "EXC-S02-01")
        self.assertEqual([m["item_id"] for m in p["missing_evidence"]], ["MISS-01"])
        self.assertEqual({x["result"] for x in p["searches"][:3]}, {"NOT_FOUND"})
        _, _, p = packet_for("SC5D", "EXC-SC5D-01")
        self.assertTrue(any("395594.86" in c["description"] and "395844.86" in c["description"] for c in p["conflicts"]))

    def test_packet_contains_no_planted_answer_material_and_is_deterministic(self):
        leak = re.compile(r"scn_|set_01|answer_key|mutation|SCENARIO_NOTES|refund_double|missing_transaction|"
                          r"short_settlement|unexplained_gbp|settlement_timing|fee_not_itemised|closing_snapshot|missing_eur", re.I)
        for sc, eid in (("SC2", "EXC-SC2-01"), ("SC5C", "EXC-SC5C-01"), ("S05", "EXC-S05-01"), ("SC5A", "EXC-SC5A-02")):
            _, _, a = packet_for(sc, eid)
            _, _, b = packet_for(sc, eid)
            self.assertEqual(leak.findall(json.dumps(a)), [], sc)
            self.assertEqual(a["packet_sha256"], b["packet_sha256"], sc)
            self.assertLess(len(json.dumps(a)), 150_000, sc)

    def test_forbidden_files_never_opened_during_a_run(self):
        opened = []
        real_open = builtins.open

        def spy(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)
        tmp = tempfile.mkdtemp()
        try:
            def read_text(self, *a, **k):
                opened.append(str(self))
                with real_open(self, encoding="utf-8") as fh:
                    return fh.read()
            with mock.patch("builtins.open", spy), mock.patch("pathlib.Path.read_text", autospec=True, side_effect=read_text):
                run_investigation(PACK["SC5C"], "EXC-SC5C-01", OFFLINE, investigations_root=tmp)
        finally:
            shutil.rmtree(tmp)
        bad = [p for p in opened if os.path.basename(p) in config.FORBIDDEN_NAMES or "/golden/" in p]
        self.assertEqual(bad, [])


class Validation(unittest.TestCase):
    def base(self, scenario="S02", eid="EXC-S02-01"):
        pack, case, packet = packet_for(scenario, eid)
        out, _ = OFFLINE.investigate(packet)
        return case, packet, out.model_dump()

    def check(self, data, packet, case):
        return validate_output(LLMInvestigationOutput.model_validate(data), packet, case)[0]

    def test_simulated_output_is_valid(self):
        case, packet, d = self.base()
        self.assertEqual(self.check(d, packet, case), [])

    def test_invalid_citation_rejected(self):
        case, packet, d = self.base()
        d["confirmed_findings"][0]["evidence_ids"].append("IN-09:BE-INVENTED-001")
        self.assertTrue(any("not present" in e for e in self.check(d, packet, case)))

    def test_finding_without_source_rejected(self):
        case, packet, d = self.base()
        d["confirmed_findings"][0]["evidence_ids"] = ["EXC-S02-01"]
        d["confirmed_findings"][0]["supporting_records"] = []
        self.assertTrue(any("cites no source record" in e for e in self.check(d, packet, case)))

    def test_candidate_promoted_to_confirmed_rejected(self):
        case, packet, d = self.base("SC5A", "EXC-SC5A-01")
        d["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")
        self.assertTrue(any("candidate" in e for e in self.check(d, packet, case)))

    def test_cause_stated_as_fact_rejected(self):
        case, packet, d = self.base("S05", "EXC-S05-01")
        d["confirmed_findings"][0]["claim"] = "The difference was caused by a misdirected scheme settlement."
        self.assertTrue(any("cause" in e for e in self.check(d, packet, case)))

    def test_resolution_language_rejected(self):
        case, packet, d = self.base("SC2", "EXC-SC2-01")
        d["investigation_summary"] = "The timing difference has been resolved and the exception is closed."
        self.assertTrue(any("resolved" in e for e in self.check(d, packet, case)))

    def test_dropped_missing_evidence_rejected(self):
        case, packet, d = self.base()
        d["missing_evidence"] = [m for m in d["missing_evidence"] if "MISS-01" not in m["related_ids"]]
        self.assertTrue(any("missing evidence not preserved" in e for e in self.check(d, packet, case)))

    def test_sufficient_assessment_with_missing_evidence_rejected(self):
        case, packet, d = self.base()
        d["overall_evidence_assessment"] = "EVIDENCE_SUFFICIENT"
        self.assertTrue(any("EVIDENCE_SUFFICIENT" in e for e in self.check(d, packet, case)))

    def test_zero_substitution_rejected(self):
        case, packet, d = self.base()
        d["confirmed_findings"][0]["claim"] = "The 15 September bank balance was 0.00 on SGA-EUR-01."
        self.assertTrue(any("zero" in e for e in self.check(d, packet, case)))


class MalformedOutputAndProviders(TempRoot):
    def test_non_json_output_fails_without_findings(self):
        s = self.run_case("SC2", "EXC-SC2-01", ScriptedInvestigator("I think it was timing."))
        r = s["result"]
        self.assertEqual((r["investigation_status"], r["validation_status"], s["persist_outcome"]), ("FAILED", "NOT_VALIDATED", "NOT_PUBLISHED"))
        self.assertIn("no JSON", r["failure_reason"])

    def test_schema_violations_fail(self):
        def bad(field, value):
            def f(packet):
                d = OFFLINE.investigate(packet)[0].model_dump()
                d[field] = value
                return d
            return f
        for field, value in (("unexpected_field", 1), ("overall_evidence_assessment", "RESOLVED"),
                             ("hypotheses", [{"hypothesis_id": "H-01", "possible_explanation": "x", "limitations": "y",
                                              "status": "CONFIRMED"}])):
            s = self.run_case("S05", "EXC-S05-01", ScriptedInvestigator(bad(field, value)))
            self.assertEqual(s["result"]["investigation_status"], "FAILED", field)

    def test_rejected_output_is_not_published(self):
        def promoted(packet):
            d = OFFLINE.investigate(packet)[0].model_dump()
            d["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")
            return d
        s = self.run_case("SC5A", "EXC-SC5A-01", ScriptedInvestigator(promoted))
        self.assertEqual((s["result"]["validation_status"], s["persist_outcome"]), ("REJECTED", "NOT_PUBLISHED"))
        self.assertFalse((self.tmp / PACK["SC5A"]).exists())

    def test_missing_credentials_and_provider_config(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigurationError):
                AnthropicInvestigator()
            with self.assertRaises(LLMConfigurationError):
                investigator_from_env()
        with mock.patch.dict(os.environ, {config.ENV_PROVIDER: "offline"}):
            self.assertTrue(investigator_from_env().simulated)
        with mock.patch.dict(os.environ, {config.ENV_PROVIDER: "unknown"}):
            with self.assertRaises(LLMConfigurationError):
                investigator_from_env()

    def _live_stub(self, side_effects):
        import anthropic
        inv = AnthropicInvestigator.__new__(AnthropicInvestigator)
        inv.model, inv.timeout, inv.max_tokens, inv._anthropic = "test-model", 5, 100, anthropic
        inv._client = mock.Mock()
        inv._client.messages.create.side_effect = side_effects
        return inv

    def test_timeout_and_api_errors_are_reported(self):
        import anthropic
        import httpx
        inv = self._live_stub(anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")))
        s = self.run_case("SC2", "EXC-SC2-01", inv)
        self.assertEqual(s["result"]["investigation_status"], "FAILED")
        self.assertIn("timed out", s["result"]["failure_reason"])

    def test_unexpected_sdk_error_is_a_recorded_failure_not_a_crash(self):
        inv = self._live_stub(TypeError("create() got an unexpected keyword argument"))
        s = self.run_case("SC2", "EXC-SC2-01", inv)
        self.assertEqual((s["result"]["investigation_status"], s["persist_outcome"]), ("FAILED", "NOT_PUBLISHED"))
        self.assertIn("unexpected provider error", s["result"]["failure_reason"])

    def test_corrective_retry_then_success(self):
        pack, case, packet = packet_for("S02", "EXC-S02-01")
        good = json.dumps(OFFLINE.investigate(packet)[0].model_dump())
        resp = lambda text: mock.Mock(content=[mock.Mock(type="text", text=text)], usage=mock.Mock(input_tokens=10, output_tokens=5))
        inv = self._live_stub([resp("not json"), resp(good)])
        out, meta = inv.investigate(packet)
        self.assertEqual(meta["attempts"], 2)
        inv = self._live_stub([resp("still not json"), resp("{bad")])
        with self.assertRaises(LLMCallError):
            inv.investigate(packet)

    def test_parse_json_object(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(LLMCallError):
            parse_json_object("no braces")


class Persistence(TempRoot):
    def test_write_once_and_identical_rerun(self):
        a = self.run_case("SC2", "EXC-SC2-01")
        b = self.run_case("SC2", "EXC-SC2-01")
        self.assertEqual((a["persist_outcome"], b["persist_outcome"]), ("PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL"))
        d = Path(a["artefact_path"])
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["evidence_packet.json", "findings.json", "runs"])
        self.assertEqual(len(list((d / "runs").glob("*.json"))), 2)
        f = d / "findings.json"
        f.write_text(f.read_text().replace("COMPLETED", "COMPLETED ", 1))
        with self.assertRaises(ImmutabilityError):
            self.run_case("SC2", "EXC-SC2-01")

    def test_artefact_identity_and_metadata(self):
        s = self.run_case("SC3C", "EXC-SC3C-01")
        r = json.loads((Path(s["artefact_path"]) / "findings.json").read_text())
        pack = load_pack(PACK["SC3C"])
        self.assertEqual((r["pack_id"], r["pack_content_sha256"], r["exception_id"]),
                         (PACK["SC3C"], pack["audit_trail"]["pack_content_sha256"], "EXC-SC3C-01"))
        self.assertTrue(r["investigation_id"].startswith("INV-EXC-SC3C-01-"))
        m = r["model_metadata"]
        self.assertEqual((m["provider"], m["simulated"], m["prompt_version"], m["workflow_version"]),
                         ("offline-simulated", True, config.PROMPT_VERSION, config.WORKFLOW_VERSION))
        self.assertEqual((r["exception_resolution"], r["original_exception_status"]), ("NOT_RESOLVED_BY_INVESTIGATION", "OPEN"))
        self.assertTrue(r["investigated_at"] and r["evidence_packet_sha256"])


class EndToEndRealScenarios(TempRoot):
    def test_clean_baseline_creates_no_investigation(self):
        s = investigate_pack(PACK["S01"], OFFLINE, investigations_root=self.tmp)
        self.assertEqual((s["status"], s["investigations"]), ("NO_EXCEPTIONS", []))
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_every_exception_in_every_pack_investigates_validly(self):
        for sc, pid in sorted(PACK.items()):
            s = investigate_pack(pid, OFFLINE, investigations_root=self.tmp)
            for r in s["investigations"]:
                self.assertEqual((r["investigation_status"], r["validation_status"]), ("COMPLETED", "VALID"), (sc, r))

    def test_scenario_specific_behaviour(self):
        s = self.run_case("SC2", "EXC-SC2-01")
        r = s["result"]
        self.assertEqual((r["original_evidence_status"], r["original_exception_status"]), ("TIMING_EVIDENCED", "OPEN"))
        self.assertTrue(any("DL-0001" in c["description"] for c in r["contradictory_evidence"]))
        s = self.run_case("S02", "EXC-S02-01")
        r = s["result"]
        self.assertEqual(r["overall_evidence_assessment"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("MISS-01", {i for m in r["missing_evidence"] for i in m["related_ids"]})
        s = self.run_case("SC5A", "EXC-SC5A-01")
        r = s["result"]
        self.assertEqual([h["status"] for h in r["hypotheses"]], ["HYPOTHESIS"])
        self.assertFalse(any("CAND-SC5A-01" in f["evidence_ids"] for f in r["confirmed_findings"]))
        for sc, eid in (("SC3C", "EXC-SC3C-01"), ("S05", "EXC-S05-01")):
            r = self.run_case(sc, eid)["result"]
            self.assertNotEqual(r["overall_evidence_assessment"], "EVIDENCE_SUFFICIENT", sc)


class DataSafety(TempRoot):
    def test_running_investigations_changes_no_project_data(self):
        before = sha_tree("uc042_dataset/**/*", "packs/**/*", "tests/golden/*")
        for sc in ("SC2", "S05", "SC5C"):
            investigate_pack(PACK[sc], OFFLINE, investigations_root=self.tmp)
        self.assertEqual(sha_tree("uc042_dataset/**/*", "packs/**/*", "tests/golden/*"), before)


if __name__ == "__main__":
    unittest.main()
