"""Stage 2 (DR-05): the model view preserves the original packet ordering, so reconstruct_packet(render_model_view(p)) is
EXACTLY the stored packet and its SHA-256, computed with the existing convention (packet.py: sha256 of
uc042lib.pack.model.canonical(packet without packet_sha256)), equals packet_sha256. Model view 1.2.

The 57 packets whose hash could not be reproduced under view 1.1 (source_records 57, relationships 56, control_results 39
out of order) are covered by the all-packet tests below; their count is pinned. Offline and read-only.
Run: python -m unittest tests.test_stage2_exact_reconstruction -v"""
import copy
import hashlib
import json
import unittest

from tests.view_fixtures import all_packets
from uc042lib.investigation import det_retrieval as det
from uc042lib.investigation.packet import build_packet, build_scope, retrieve
from uc042lib.investigation.packet_view import MODEL_VIEW_VERSION, model_view_text, reconstruct_packet, render_model_view
from uc042lib.pack.model import canonical

PACKETS = list(all_packets())
ORDERED = ("source_records", "relationships", "control_results")


def packet_hash(p):
    """The existing convention (packet.build_packet / det_retrieval.finalise_packet), unchanged."""
    return hashlib.sha256(canonical({k: v for k, v in p.items() if k != "packet_sha256"}).encode("utf-8")).hexdigest()


def round_trip(p):
    return reconstruct_packet(json.loads(model_view_text(p)))  # through the exact text sent to the model


def det_packets():
    for label, _, _, _, store, case, route in PACKETS:
        if det.supported(route):
            col = retrieve(route, case, store)
            reg = det.expand(col, case, route, store)
            yield label, det.finalise_packet(build_packet(case, build_scope(case), route, col), reg)


class ExactReconstruction(unittest.TestCase):
    def test_version_is_1_2(self):  # name kept; 1.3 (20 Nov 2026) changes only the citation classes
        self.assertEqual(MODEL_VIEW_VERSION, "uc042-model-view/1.3")

    def test_all_76_packets_reconstruct_exactly_with_matching_hashes(self):
        self.assertEqual(len(PACKETS), 76)
        exact = hashes = 0
        for label, _, _, p, *_ in PACKETS:
            with self.subTest(label):
                self.assertEqual(packet_hash(p), p["packet_sha256"])  # the convention reproduces the stored hash
                r = round_trip(p)
                self.assertEqual(r, p)  # every value, every list in its original order
                for k in ORDERED:
                    self.assertEqual([json.dumps(x, sort_keys=True) for x in r[k]], [json.dumps(x, sort_keys=True) for x in p[k]], k)
                self.assertEqual(packet_hash(r), p["packet_sha256"])
                self.assertEqual(r["packet_sha256"], p["packet_sha256"])
                exact += r == p
                hashes += packet_hash(r) == p["packet_sha256"]
        self.assertEqual((exact, hashes), (76, 76))

    def test_the_57_view_1_1_ordering_failures_are_covered(self):
        """Packets whose stored order differs from the view's sorted layout (the 57 hash failures of view 1.1)."""
        reordered = []
        for label, _, _, p, *_ in PACKETS:
            recs_sorted = sorted(p["source_records"], key=lambda r: (r["file_id"], r["evidence_id"]))
            if recs_sorted != p["source_records"]:
                reordered.append(label)
                self.assertEqual(round_trip(p), p, label)
        self.assertEqual(len(reordered), 57)

    def test_deterministic_packets_reconstruct_exactly(self):
        n = 0
        for label, p in det_packets():
            n += 1
            with self.subTest(label):
                self.assertEqual(packet_hash(p), p["packet_sha256"])
                r = round_trip(p)
                self.assertEqual(r, p)
                self.assertEqual(packet_hash(r), p["packet_sha256"])
        self.assertEqual(n, 53)

    def test_view_is_deterministic(self):
        for label, _, _, p, *_ in PACKETS[:20]:
            self.assertEqual(model_view_text(p), model_view_text(copy.deepcopy(p)), label)

    def test_token_reduction_is_preserved(self):
        raw = sum(len(json.dumps(p, sort_keys=True, ensure_ascii=False)) for _, _, _, p, *_ in PACKETS)
        view = sum(len(model_view_text(p)) for _, _, _, p, *_ in PACKETS)
        self.assertLess(view, raw * 0.80, f"{raw} -> {view}")  # still at least 20% smaller than the raw packet JSON


class OrderingEdgeCases(unittest.TestCase):
    """Synthetic orderings built from a real packet (no historical file is touched)."""

    def base(self):
        return copy.deepcopy(next(p for label, _, _, p, *_ in PACKETS if "SC3C" in label))

    def check(self, p):
        r = round_trip(p)
        self.assertEqual(r, p)
        return r

    def test_reversed_lists(self):
        p = self.base()
        for k in ORDERED:
            p[k] = list(reversed(p[k]))
        self.check(p)

    def test_derived_edges_out_of_derivation_order_and_interleaved(self):
        p = self.base()
        rels = p["relationships"]
        p["relationships"] = rels[1::2] + rels[0::2]
        self.check(p)

    def test_empty_relationships_and_single_record(self):
        p = self.base()
        p["source_records"] = p["source_records"][:1]
        p["relationships"] = []
        self.check(p)

    def test_tampered_order_fails_closed(self):
        p = self.base()
        v = json.loads(model_view_text(p))
        v["relationship_order"] = v["relationship_order"][:-1]  # one edge unaccounted for
        with self.assertRaises(ValueError):
            reconstruct_packet(v)
        v = json.loads(model_view_text(p))
        t = next(iter(v["records_by_file"].values()))
        i = t["columns"].index("packet_order")
        t["rows"][0][i] = t["rows"][-1][i] if len(t["rows"]) > 1 else 999  # duplicate / impossible position
        with self.assertRaises(ValueError):
            reconstruct_packet(v)


if __name__ == "__main__":
    unittest.main()
