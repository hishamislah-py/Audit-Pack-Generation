"""Phase 6 (token-optimisation copy): deterministic retrieval beside tools mode (NOT the application default).

Offline (mocked OpenAI client): deterministic mode makes one structured request on a Python-extended packet; uncovered
routes fall back to tools mode and say so; a pre-request size guard stops oversized single requests; pruning is explicit;
NOT_FOUND searches are not duplicated; offline record parity with every persisted tools-mode investigation is 100%
(strict NOT_FOUND parity, with its one known shape miss, is in tests.test_dr01_dr03_remediation).
Run: python -m unittest tests.test_phase6_deterministic -v"""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests import det_parity
from tests.test_phase1_reliability import make
from tests.test_tool_calling import OFFLINE, PACK, Temp, final, requests_of
from tests.view_fixtures import CLONE_E_CASE, all_packets, build
from uc042lib.investigation import config, det_retrieval as det
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.packet import build_packet, build_scope, retrieve
from uc042lib.investigation.packet_view import reconstruct_packet, render_model_view

ROOT = Path(__file__).resolve().parent.parent


def det_packet(pack_id, packs_root, datasets_root, exc):
    _, case, route, store, base = build(pack_id, packs_root, datasets_root, exc)
    col = retrieve(route, case, store)
    reg = det.expand(col, case, route, store)
    return base, det.finalise_packet(build_packet(case, build_scope(case), route, col), reg), reg


class DeterministicMode(Temp):
    def test_single_request_on_the_extended_packet(self):
        pid = PACK["SC3C"]
        base, p, _ = det_packet(pid, ROOT / "packs", ROOT / "uc042_dataset", "EXC-SC3C-02")
        out = OFFLINE.investigate(base)[0].model_dump()  # cites only IDs of the base packet (a subset of the deterministic one)
        inv = make([final(out)])
        s = run_investigation(pid, "EXC-SC3C-02", inv, investigations_root=self.tmp, mode="deterministic")
        self.assertEqual(len(requests_of(inv)), 1)
        self.assertEqual(s["persist_outcome"], "PUBLISHED", s["result"]["validation_findings"])
        r = s["result"]
        self.assertEqual((r["investigation_mode"], r["model_metadata"]["workflow_version"], r["model_metadata"]["retrieval_rule_version"]),
                         ("deterministic", config.DET_WORKFLOW_VERSION, det.DET_RULE_VERSION))
        self.assertEqual(s["packet"]["packet_version"], det.DET_PACKET_VERSION)
        self.assertEqual(s["packet"]["packet_sha256"], p["packet_sha256"])  # reproducible for the same pack and rule version
        self.assertNotIn("tools", requests_of(inv)[0])  # no model-directed tools
        self.assertGreater(len(s["packet"]["source_records"]), len(base["source_records"]))

    def test_size_guard_sends_nothing(self):
        inv = make([])
        with mock.patch.dict(os.environ, {config.ENV_SINGLE_REQUEST_MAX_INPUT_TOKENS: "1000"}):
            s = run_investigation(PACK["SC3C"], "EXC-SC3C-01", inv, investigations_root=self.tmp, mode="deterministic")
        self.assertEqual(requests_of(inv), [])
        self.assertIn("input_token_budget", s["result"]["failure_reason"])
        self.assertEqual(s["persist_outcome"], "NOT_PUBLISHED")

    @unittest.skipUnless((CLONE_E_CASE[1] / CLONE_E_CASE[3] / "pack.json").is_file(), "Clone E CASE pack not present")
    def test_uncovered_route_falls_back_to_tools_and_says_so(self):
        _, packs_root, data_root, pid = CLONE_E_CASE
        from uc042lib.investigation.retrieval import load_pack
        from uc042lib.investigation.packet import build_case
        from uc042lib.investigation.routing import route_for
        pack = load_pack(pid, packs_root)
        exc = next(x["exception_id"] for x in pack["exception_register"]["exceptions"]
                   if not det.supported(route_for(x, build_case(pack, x["exception_id"])["candidates"], build_case(pack, x["exception_id"])["results"])))
        _, _, route, _, packet = build(pid, packs_root, data_root, exc)
        inv = make([final(OFFLINE.investigate(packet)[0].model_dump())])
        s = run_investigation(pid, exc, inv, packs_root=packs_root, datasets_root=data_root, investigations_root=self.tmp, mode="deterministic")
        self.assertEqual(s["result"]["investigation_mode"], "tools")
        self.assertIn("tools", requests_of(inv)[0])  # the tool loop ran
        self.assertTrue(any("no deterministic retrieval plan" in (t.get("fallback") or "") for t in s["trace"]), route)


class Policy(unittest.TestCase):
    PACKETS = [(lbl, pid, exc) for lbl, pid, exc, p, store, case, route in all_packets(include_case=False) if det.supported(route)]

    def test_no_silent_pruning_under_a_tight_budget(self):
        with mock.patch.object(det, "DET_MAX_RECORDS", 20):
            base, p, reg = det_packet(PACK["SC3C"], ROOT / "packs", ROOT / "uc042_dataset", "EXC-SC3C-01")
        skipped = [x for x in reg if "record budget" in x.get("reason", "")]
        self.assertTrue(skipped)
        self.assertTrue({r["evidence_id"] for r in base["source_records"]} <= {r["evidence_id"] for r in p["source_records"]})  # nothing removed
        self.assertEqual(p["pruning_register"], reg)

    def test_no_duplicate_not_found_searches_and_view_lossless(self):
        for lbl, pid, exc in self.PACKETS:
            root = ROOT / "packs" if lbl.startswith("scenario") else ROOT / "demo_history" / "packs"
            data = ROOT / "uc042_dataset" if lbl.startswith("scenario") else ROOT / "demo_history" / "datasets"
            _, p, _ = det_packet(pid, root, data, exc)
            keys = [det._norm(s["query"]) for s in p["searches"] if s["result"] == "NOT_FOUND"]
            self.assertEqual(len(keys), len(set(keys)), lbl)
            r = reconstruct_packet(render_model_view(p))
            self.assertEqual({x["evidence_id"]: x for x in r["source_records"]}, {x["evidence_id"]: x for x in p["source_records"]}, lbl)
            self.assertEqual((r["retrieval_rule_version"], r["pruning_register"]), (det.DET_RULE_VERSION, p["pruning_register"]), lbl)
            self.assertLess(len(p["source_records"]), det.DET_MAX_RECORDS, lbl)

    def test_candidates_stay_hypotheses_only(self):
        _, p, _ = det_packet(PACK["SC5A"], ROOT / "packs", ROOT / "uc042_dataset", "EXC-SC5A-01")
        self.assertEqual([c["candidate_id"] for c in p["candidate_relationships"]], ["CAND-SC5A-01"])
        self.assertEqual(render_model_view(p)["citation_classes"]["hypotheses_only_ids"], ["CAND-SC5A-01"])


class Parity(unittest.TestCase):
    def test_every_previously_cited_model_fetched_record_is_supplied(self):
        rows = det_parity.run()
        s = det_parity.summary(rows)
        self.assertGreaterEqual(s["investigations_examined"], 20)
        self.assertEqual(s["errors"], [])
        self.assertEqual((s["covered"], s["missed"]), (s["cited_model_fetched_records"], []))
        # DR-02: strict NOT_FOUND matching; every cited search is either covered or listed as missed (none hidden)
        self.assertEqual(s["not_found_covered"] + len(s["not_found_missed"]), s["not_found_searches_cited"])
        self.assertTrue(s["miss_items_preserved_all"] and s["candidates_unchanged_all"])
        self.assertEqual(s["any_at_record_budget"], [])


class ApplicationDefaultUnchanged(unittest.TestCase):
    def test_the_app_still_runs_tools_mode(self):
        src = (ROOT / "uc042app" / "services" / "investigations.py").read_text(encoding="utf-8")
        self.assertIn('mode="tools"', src)
        self.assertEqual(config.DEFAULT_MODE, "fixed")  # library default unchanged; the app passes tools explicitly


if __name__ == "__main__":
    unittest.main()
