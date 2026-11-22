"""Stage 1 (owner-approved, 16 Nov 2026): the narrow settlement_line_to_transaction semantic equivalence in the parity
harness (tests/det_parity.py only; production retrieval unchanged, rule stays 1.3).

The model's follow_relationship query {evidence_id IN-13:SL-SB-GBP-20260915-0003, relationship settlement_line_to_transaction,
value TX-0915-00009} and the deterministic search {file IN-11, txn_id TX-0915-00009} are the same primary-key lookup of
IN-11 for the same line's txn_id. Positive case on the real data; negative cases for every way the match must fail.
Offline and read-only. Run: python -m unittest tests.test_stage1_parity_equivalence -v"""
import copy
import unittest

from tests import det_parity
from uc042lib.investigation import det_retrieval as det
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for

PACK_ID, EXC = "PACK-CASE-PER-2026-09-109a585702ae", "EXC-CASE-01"
LINE, TX = "IN-13:SL-SB-GBP-20260915-0003", "TX-0915-00009"
MODEL = {"search_id": "SEARCH-08", "result": "NOT_FOUND",
         "query": {"evidence_id": LINE, "relationship": "settlement_line_to_transaction", "value": TX}}


def real():
    for _, _, pr, dr in det_parity.STORES:
        try:
            pack = load_pack(PACK_ID, pr)
            return pack, EvidenceStore(pack, dr)
        except Exception:  # noqa: BLE001 - try the next store
            continue
    return None, None


class Stage1Equivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack, cls.store = real()
        if cls.store is None:
            raise unittest.SkipTest("Clone E CASE pack not present")
        case = build_case(cls.pack, EXC)
        route = route_for(case["exception"], case["candidates"], case["results"])
        col = retrieve(route, case, cls.store)
        reg = det.expand(col, case, route, cls.store)
        cls.packet = det.finalise_packet(build_packet(case, build_scope(case), route, col), reg)

    def mutated(self, **query):
        m = copy.deepcopy(MODEL)
        m["query"].update(query)
        return m

    # ---------------------------------------------------------------- evidence that the equivalence is real
    def test_source_data_establishes_the_equivalence(self):
        line = self.store.get(LINE, "probe")
        self.assertEqual((line["file_id"], line["fields"]["txn_id"]), ("IN-13", TX))
        self.assertIsNone(self.store.get(f"IN-11:{TX}", "probe"))  # the transaction is not in IN-11
        self.assertEqual(self.store.pk_of["IN-11"], "txn_id")
        from uc042lib.investigation.tools import RELATIONSHIPS
        self.assertEqual(RELATIONSHIPS["settlement_line_to_transaction"][:4], ("IN-13", "txn_id", "IN-11", "pk"))
        hit = [s for s in self.packet["searches"] if s["query"] == {"file": "IN-11", "txn_id": TX}]
        self.assertEqual([s["result"] for s in hit], ["NOT_FOUND"])
        self.assertIn(LINE, {r["evidence_id"] for r in self.packet["source_records"]})
        self.assertEqual(self.packet["retrieval_rule_version"], "uc042-det-retrieval/1.3")  # production rule unchanged

    # ---------------------------------------------------------------- positive
    def test_approved_case_matches_by_equivalence_not_exactly(self):
        self.assertFalse(det_parity.not_found_covered(MODEL, self.packet["searches"]))  # exact match still fails
        self.assertTrue(det_parity.not_found_equivalent(MODEL, self.packet, self.store))
        self.assertEqual(det_parity.relationship_equivalent_query(MODEL["query"], self.store),
                         det_parity.full_query({"file": "IN-11", "txn_id": TX}))

    # ---------------------------------------------------------------- negatives
    def test_transaction_id_differs(self):
        self.assertFalse(det_parity.not_found_equivalent(self.mutated(value="TX-0915-00008"), self.packet, self.store))

    def test_settlement_line_differs(self):
        for other in ("IN-13:SL-SB-GBP-20260915-0002", "IN-13:SL-SB-GBP-20260915-9999", ""):
            with self.subTest(other):
                self.assertFalse(det_parity.not_found_equivalent(self.mutated(evidence_id=other), self.packet, self.store))

    def test_relationship_type_differs(self):
        for rel in ("transaction_to_batch", "settlement_line_to_batch", "refund_to_original_transaction", "unknown"):
            with self.subTest(rel):
                self.assertFalse(det_parity.not_found_equivalent(self.mutated(relationship=rel), self.packet, self.store))

    def test_file_differs(self):
        p = copy.deepcopy(self.packet)
        for s in p["searches"]:
            if s["query"] == {"file": "IN-11", "txn_id": TX}:
                s["query"] = {"file": "IN-12", "txn_id": TX}
        self.assertFalse(det_parity.not_found_equivalent(MODEL, p, self.store))

    def test_deterministic_result_found_does_not_match(self):
        p = copy.deepcopy(self.packet)
        for s in p["searches"]:
            if s["query"] == {"file": "IN-11", "txn_id": TX}:
                s["result"] = "FOUND"
        self.assertFalse(det_parity.not_found_equivalent(MODEL, p, self.store))

    def test_partial_identifier_does_not_match(self):
        for v in ("TX-0915-0000", "TX-0915-000090", "0915-00009", TX.lower(), f" {TX}"):
            with self.subTest(v):
                self.assertFalse(det_parity.not_found_equivalent(self.mutated(value=v), self.packet, self.store))
        p = copy.deepcopy(self.packet)  # deterministic query with an extra key is not the same query
        for s in p["searches"]:
            if s["query"] == {"file": "IN-11", "txn_id": TX}:
                s["query"] = {"file": "IN-11", "txn_id": TX, "client_id": "C0002"}
        self.assertFalse(det_parity.not_found_equivalent(MODEL, p, self.store))

    def test_extra_or_missing_query_keys_do_not_match(self):
        m = copy.deepcopy(MODEL)
        m["query"]["currency"] = "GBP"
        self.assertFalse(det_parity.not_found_equivalent(m, self.packet, self.store))
        m = copy.deepcopy(MODEL)
        del m["query"]["value"]
        self.assertFalse(det_parity.not_found_equivalent(m, self.packet, self.store))

    def test_line_missing_from_the_deterministic_packet_does_not_match(self):
        p = copy.deepcopy(self.packet)
        p["source_records"] = [r for r in p["source_records"] if r["evidence_id"] != LINE]
        self.assertFalse(det_parity.not_found_equivalent(MODEL, p, self.store))

    def test_transaction_id_alone_never_matches(self):
        """A search for the same txn_id is not enough: the line, relationship and file must all agree."""
        bare = {"search_id": "X", "result": "NOT_FOUND", "query": {"txn_id": TX}}
        self.assertFalse(det_parity.not_found_equivalent(bare, self.packet, self.store))
        self.assertFalse(det_parity.not_found_covered(bare, self.packet["searches"]))


class Stage1ParitySummary(unittest.TestCase):
    def test_96_of_96_with_one_separately_reported_semantic_match(self):
        excluded = []
        rows = det_parity.run(excluded)
        s = det_parity.summary(rows, excluded)
        self.assertEqual((s["not_found_covered"], s["not_found_searches_cited"]), (96, 96))
        self.assertEqual(s["not_found_covered_exact"], 95)
        self.assertEqual(len(s["not_found_semantic_matches"]), 1)
        m = s["not_found_semantic_matches"][0]
        self.assertEqual((m["store"], m["exception_id"], m["search_id"], m["matched_by"]),
                         ("clone-e", "EXC-CASE-01", "SEARCH-08", "approved semantic equivalence"))
        self.assertEqual(m["equivalent_query"], {"file": "IN-11", "txn_id": TX})
        self.assertEqual(s["not_found_missed"], [])
        self.assertEqual((s["covered"], s["cited_model_fetched_records"]), (162, 162))
        self.assertEqual(s["distinct_per_exception"], {"targets": 77, "covered": 77})
        self.assertEqual(s["retrieval_rule_versions"], ["uc042-det-retrieval/1.3"])


if __name__ == "__main__":
    unittest.main()
