"""Stage 4: model-view hardening (DR-06) and wording (DR-07). Synthetic packets derived in memory from a real one; no
historical file is touched. Run: python -m unittest tests.test_stage4_dr06_dr07 -v

DR-06  a key missing from some rows stays missing (never an explicit None); distinct provenance (source_file, file_sha256,
       record_type) under one file_id is preserved per record; duplicate derived edges survive; a control result with
       evidence_ids None is handled; a real value equal to the missing-value sentinel is refused; render_model_view refuses
       to produce a view that does not reconstruct the packet exactly (fail closed), and an investigation then sends nothing.
DR-07  'cited_without_edge' is renamed and described as pairs whose edge is not derivable from evidence_ids; relationship
       data and reconstruction are unchanged."""
import copy
import json
import unittest
from unittest import mock

from tests.test_phase1_reliability import make
from tests.test_tool_calling import PACK, Temp, final, offline_output, requests_of
from tests.view_fixtures import all_packets
from uc042lib.investigation import packet_view
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.packet_view import (MISSING, ModelViewError, model_view_text, reconstruct_packet,
                                                render_model_view, verified_links)

BASE = next(p for label, _, _, p, *_ in all_packets(include_case=False) if label == "scenario:SC3C/EXC-SC3C-01")


def base():
    return copy.deepcopy(BASE)


def round_trip(p):
    return reconstruct_packet(json.loads(model_view_text(p)))


class DR06Hardening(unittest.TestCase):
    def test_missing_keys_stay_missing(self):
        p = base()
        rec = next(r for r in p["source_records"] if r["file_id"] == "IN-09")
        del rec["fields"]["narrative_text"]          # a field missing from one row of its file
        del rec["join_key"]                          # a record-level key missing from one row
        p["control_results"][0].pop("note")          # a control-result key missing from one row
        r = round_trip(p)
        self.assertEqual(r, p)
        out = next(x for x in r["source_records"] if x["evidence_id"] == rec["evidence_id"])
        self.assertNotIn("narrative_text", out["fields"])
        self.assertNotIn("join_key", out)
        self.assertNotIn("note", r["control_results"][0])

    def test_explicit_none_is_kept_distinct_from_missing(self):
        p = base()
        recs = [r for r in p["source_records"] if r["file_id"] == "IN-09"]
        recs[0]["fields"]["narrative_text"] = None
        del recs[1]["fields"]["narrative_text"]
        r = round_trip(p)
        self.assertEqual(r, p)
        got = {x["evidence_id"]: x["fields"] for x in r["source_records"]}
        self.assertIsNone(got[recs[0]["evidence_id"]]["narrative_text"])
        self.assertNotIn("narrative_text", got[recs[1]["evidence_id"]])

    def test_distinct_provenance_under_one_file_id(self):
        p = base()
        recs = [r for r in p["source_records"] if r["file_id"] == "IN-09"]
        recs[0]["source_file"] = "source_data/bank_entries_2026-09_corrected.csv"
        recs[1]["file_sha256"] = "0" * 64
        recs[2]["record_type"] = "bank_entry_v2"
        r = round_trip(p)
        self.assertEqual(r, p)
        got = {x["evidence_id"]: x for x in r["source_records"]}
        for x in recs[:3]:
            self.assertEqual({k: got[x["evidence_id"]][k] for k in ("source_file", "file_sha256", "record_type")},
                             {k: x[k] for k in ("source_file", "file_sha256", "record_type")})

    def test_duplicate_derived_and_kept_edges_survive(self):
        p = base()
        derived = next(e for e in p["relationships"] if e["relationship"] == packet_view.DERIVED_EDGE)
        kept = next(e for e in p["relationships"] if e["relationship"] != packet_view.DERIVED_EDGE)
        p["relationships"] = p["relationships"] + [copy.deepcopy(derived), copy.deepcopy(kept), copy.deepcopy(derived)]
        r = round_trip(p)
        self.assertEqual(r["relationships"], p["relationships"])
        self.assertEqual(r, p)

    def test_evidence_ids_none(self):
        p = base()
        p["control_results"][0]["evidence_ids"] = None
        verified_links(p)  # does not raise
        self.assertEqual(round_trip(p), p)

    def test_sentinel_collision_is_refused(self):
        p = base()
        p["source_records"][0]["fields"]["narrative_text"] = copy.deepcopy(MISSING)
        with self.assertRaises(ModelViewError):
            render_model_view(p)

    def test_render_fails_closed_when_the_view_would_not_reconstruct(self):
        p = base()
        real = packet_view.reconstruct_packet
        with mock.patch.object(packet_view, "reconstruct_packet", lambda v: dict(real(v), conflicts=[])):
            with self.assertRaises(ModelViewError):
                render_model_view(p)

    def test_all_real_packets_still_exact(self):
        for label, _, _, p, *_ in all_packets():
            self.assertEqual(round_trip(p), p, label)


class FailClosedInvestigation(Temp):
    def test_no_request_is_sent_when_the_view_is_invalid(self):
        for mode in ("fixed", "tools"):
            with self.subTest(mode), mock.patch.object(packet_view, "reconstruct_packet", lambda v: {}):
                inv = make([final(offline_output("SC2", "EXC-SC2-01"))])
                s = run_investigation(PACK["SC2"], "EXC-SC2-01", inv, investigations_root=self.tmp / mode, mode=mode)
                self.assertEqual(requests_of(inv), [])
                self.assertEqual(s["result"]["investigation_status"], "FAILED")
                self.assertIn("ModelViewError", s["result"]["failure_reason"])
                self.assertNotEqual(s.get("persist_outcome"), "PUBLISHED")


class DR07Wording(unittest.TestCase):
    def test_renamed_and_described(self):
        v = render_model_view(base())
        self.assertNotIn("cited_without_edge", v)
        self.assertIn("evidence_ids_without_derivable_edge", v)
        self.assertIn("not derivable from evidence_ids", v["reading_guide"])
        self.assertNotIn("cited_without_edge", v["reading_guide"])
        self.assertNotIn("no such edge", open(packet_view.__file__, encoding="utf-8").read())

    def test_relationship_data_unchanged(self):
        for label, _, _, p, *_ in all_packets():
            r = round_trip(p)
            self.assertEqual(r["relationships"], p["relationships"], label)


if __name__ == "__main__":
    unittest.main()
