"""Independent code review remediation (16 Nov 2026): DR-01 (search de-duplication), DR-02 (strict parity harness),
DR-03 (record budget and pruning register) for deterministic retrieval.

DR-01  A NOT_FOUND search is suppressed only when an EARLIER NOT_FOUND search has the same COMPLETE normalised query
       (only genuine date / reference synonyms are folded). A FOUND search never suppresses anything. Rule 1.3.
DR-02  The parity harness matches the full normalised query and requires the deterministic search to be NOT_FOUND too;
       fixed-mode records are reported (not skipped silently); attempts are split by status.
DR-03  The deterministic record budget cannot be exceeded by an expansion; every record a tool call returned but that was
       not added (record budget, per-call cap or the investigation-wide MAX_RECORDS) is in the pruning register.
Offline and read-only. Run: python -m unittest tests.test_dr01_dr03_remediation -v"""
import unittest
from pathlib import Path
from unittest import mock

from tests import det_parity
from tests.view_fixtures import all_packets, build
from uc042lib.investigation import config, det_retrieval as det
from uc042lib.investigation.packet import build_packet, build_scope, retrieve

ROOT = Path(__file__).resolve().parent.parent
SCEN = (ROOT / "packs", ROOT / "uc042_dataset")


def pack_id(tag):
    return next(p.name for p in SCEN[0].glob(f"PACK-{tag}-*"))


def det_packet(tag, exc):
    _, case, route, store, base = build(pack_id(tag), SCEN[0], SCEN[1], exc)
    col = retrieve(route, case, store)
    reg = det.expand(col, case, route, store)
    return base, det.finalise_packet(build_packet(case, build_scope(case), route, col), reg), reg


def search(sid, query, result):
    return {"search_id": sid, "description": sid, "query": query, "found": [] if result == "NOT_FOUND" else ["IN-11:X"],
            "result": result}


def omitted(reg):
    return {e for x in reg for e in x.get("omitted_evidence_ids", [])}


# ---------------------------------------------------------------------------------------------------------- DR-01
class DR01RealScenarios(unittest.TestCase):
    def test_sc5a_02_missing_transaction_search_is_kept(self):
        """SEARCH-04 {IN-11, txn_id TX-0915-00009} NOT_FOUND was dropped as a 'repeat' of the FOUND client-window search."""
        base, p, reg = det_packet("SC5A", "EXC-SC5A-02")
        want = {"file": "IN-11", "txn_id": "TX-0915-00009"}
        hits = [s for s in p["searches"] if s["query"] == want]
        self.assertEqual([(s["search_id"], s["result"]) for s in hits], [("SEARCH-04", "NOT_FOUND")])
        self.assertIn("SEARCH-04", p["allowed_citation_ids"])
        self.assertNotIn("SEARCH-04", [x.get("search_id") for x in reg])

    def test_sc5d_01_refund_search_is_kept(self):
        """SEARCH-02 {IN-11, client C0003, REFUND} NOT_FOUND was dropped because of the FOUND C0003 window search."""
        for exc in ("EXC-SC5D-01", "EXC-SC5D-02", "EXC-SC5D-03"):
            with self.subTest(exc):
                _, p, reg = det_packet("SC5D", exc)
                want = {"file": "IN-11", "client_id": "C0003", "txn_type": "REFUND"}
                hits = [s for s in p["searches"] if s["query"] == want]
                self.assertEqual([s["result"] for s in hits], ["NOT_FOUND"])
                self.assertIn(hits[0]["search_id"], p["allowed_citation_ids"])

    def test_every_base_not_found_search_survives(self):
        """No NOT_FOUND search of the tools-mode base packet ever disappears from the deterministic packet."""
        n = 0
        for label, _, _, base, store, case, route in all_packets():
            if not det.supported(route):
                continue
            col = retrieve(route, case, store)
            reg = det.expand(col, case, route, store)
            det_nf = [s["query"] for s in col.searches if s["result"] == "NOT_FOUND"]
            for s in base["searches"]:
                if s["result"] == "NOT_FOUND":
                    n += 1
                    with self.subTest(label, search=s["search_id"]):
                        self.assertIn(s["query"], det_nf)
            for x in reg:  # a de-duplication entry always names an earlier identical NOT_FOUND search that was kept
                if x.get("step") == "de-duplication":
                    kept = next(s for s in col.searches if s["search_id"] == x["duplicate_of"])
                    self.assertEqual(kept["result"], "NOT_FOUND", label)
        self.assertGreater(n, 40)

    def test_rule_version_is_1_3(self):
        self.assertEqual(det.DET_RULE_VERSION, "uc042-det-retrieval/1.3")
        _, p, _ = det_packet("SC5A", "EXC-SC5A-02")
        self.assertEqual(p["retrieval_rule_version"], "uc042-det-retrieval/1.3")


class DR01Dedup(unittest.TestCase):
    def dedupe(self, searches):
        return det.dedupe_not_found(searches)

    def test_different_queries_with_the_same_old_partial_key_are_both_kept(self):
        # the 1.2 key (file, account, date, reference) of all of these was {"file": "IN-11"} only
        queries = [{"file": "IN-11", "txn_id": "TX-1"}, {"file": "IN-11", "txn_id": "TX-2"}, {"file": "IN-11", "batch_id": "SB-1"},
                   {"file": "IN-11", "client_id": "C1", "txn_type": "REFUND"}, {"file": "IN-11", "client_id": "C1", "txn_type": "PAYMENT"},
                   {"file": "IN-11", "payment_reference": "R1"}, {"file": "IN-11", "window": ["a", "b"]}, {"file": "IN-11", "window": ["a", "c"]},
                   {"file": "IN-09", "account_id": "A", "bank_reference": "R", "date_from": "2026-09-01", "date_to": None},
                   {"file": "IN-09", "account_id": "A", "bank_reference": "R", "date_from": "2026-09-02", "date_to": None}]
        s = [search(f"SEARCH-{i:02d}", q, "NOT_FOUND") for i, q in enumerate(queries, 1)]
        kept, reg = self.dedupe(s)
        self.assertEqual([x["search_id"] for x in kept], [x["search_id"] for x in s])
        self.assertEqual(reg, [])

    def test_truly_identical_not_found_searches_are_deduplicated_and_recorded(self):
        q = {"file": "IN-07", "account_id": "SGA-EUR-01", "date": "2026-09-15"}
        kept, reg = self.dedupe([search("SEARCH-01", q, "NOT_FOUND"), search("SEARCH-02", dict(q), "NOT_FOUND")])
        self.assertEqual([x["search_id"] for x in kept], ["SEARCH-01"])
        self.assertEqual(len(reg), 1)
        self.assertEqual((reg[0]["search_id"], reg[0]["duplicate_of"]), ("SEARCH-02", "SEARCH-01"))
        self.assertIn("identical", reg[0]["reason"])
        self.assertEqual(reg[0]["query"], q)

    def test_genuine_date_and_reference_synonyms_are_normalised(self):
        pairs = [({"file": "IN-08", "account_id": "A", "statement_date": "2026-09-15"}, {"file": "IN-08", "account_id": "A", "date": "2026-09-15"}),
                 ({"file": "IN-09", "account_id": "A", "booking_date": "2026-09-15"}, {"file": "IN-09", "account_id": "A", "date": "2026-09-15"}),
                 ({"file": "IN-09", "account_id": "A", "bank_reference": "R"}, {"file": "IN-09", "account_id": "A", "reference": "R"}),
                 ({"file": "IN-09", "account_id": "A", "bank_reference": "R", "date_to": None}, {"file": "IN-09", "account_id": "A", "bank_reference": "R"})]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                kept, reg = self.dedupe([search("SEARCH-01", a, "NOT_FOUND"), search("SEARCH-02", b, "NOT_FOUND")])
                self.assertEqual([x["search_id"] for x in kept], ["SEARCH-01"])
        # a synonym with a DIFFERENT value is a different query
        kept, _ = self.dedupe([search("SEARCH-01", {"file": "IN-08", "statement_date": "2026-09-15"}, "NOT_FOUND"),
                               search("SEARCH-02", {"file": "IN-08", "date": "2026-09-16"}, "NOT_FOUND")])
        self.assertEqual(len(kept), 2)

    def test_found_then_not_found_with_the_same_query_keeps_both(self):
        q = {"file": "IN-11", "txn_id": "TX-0915-00009"}
        kept, reg = self.dedupe([search("SEARCH-01", q, "FOUND"), search("SEARCH-02", dict(q), "NOT_FOUND")])
        self.assertEqual([(x["search_id"], x["result"]) for x in kept], [("SEARCH-01", "FOUND"), ("SEARCH-02", "NOT_FOUND")])
        self.assertEqual(reg, [])

    def test_not_found_then_found_keeps_both(self):
        q = {"file": "IN-11", "txn_id": "TX-0915-00009"}
        kept, reg = self.dedupe([search("SEARCH-01", q, "NOT_FOUND"), search("SEARCH-02", dict(q), "FOUND")])
        self.assertEqual([x["search_id"] for x in kept], ["SEARCH-01", "SEARCH-02"])
        self.assertEqual(reg, [])

    def test_found_searches_are_never_dropped(self):
        q = {"file": "IN-09", "account_id": "A", "date": "2026-09-15"}
        kept, reg = self.dedupe([search("SEARCH-01", q, "FOUND"), search("SEARCH-02", dict(q), "FOUND")])
        self.assertEqual(len(kept), 2)
        self.assertEqual(reg, [])


# ---------------------------------------------------------------------------------------------------------- DR-02
class DR02StrictParity(unittest.TestCase):
    def test_full_query_and_not_found_result_are_both_required(self):
        model = {"search_id": "SEARCH-04", "query": {"file": "IN-11", "txn_id": "TX-0915-00009"}, "result": "NOT_FOUND"}
        cases = [([{"query": {"file": "IN-11", "client_id": "C0002", "window": ["a", "b"]}, "result": "NOT_FOUND"}], False),  # old partial key
                 ([{"query": {"file": "IN-11", "txn_id": "TX-0915-00008"}, "result": "NOT_FOUND"}], False),  # other transaction
                 ([{"query": {"file": "IN-11", "txn_id": "TX-0915-00009"}, "result": "FOUND"}], False),  # found is not parity
                 ([{"query": {"file": "IN-11", "txn_id": "TX-0915-00009"}, "result": "NOT_FOUND"}], True),
                 ([{"query": {"txn_id": "TX-0915-00009", "file": "IN-11"}, "result": "NOT_FOUND"}], True)]
        for det_searches, want in cases:
            with self.subTest(det_searches):
                self.assertIs(det_parity.not_found_covered(model, det_searches), want)
        # the harness's normaliser is its own (not det_retrieval's): synonyms only
        self.assertEqual(det_parity.full_query({"file": "IN-08", "statement_date": "d", "date_to": None}), det_parity.full_query({"file": "IN-08", "date": "d"}))
        self.assertNotEqual(det_parity.full_query({"file": "IN-11", "txn_id": "A"}), det_parity.full_query({"file": "IN-11", "txn_id": "B"}))

    def test_strict_parity_reports_status_categories_and_fixed_mode_records(self):
        rows = det_parity.run()
        s = det_parity.summary(rows)
        a = s["attempts"]
        self.assertEqual(a["published"] + a["completed_not_published"] + a["failed"] + a["other"], s["investigations_examined"])
        self.assertEqual(a["completed_investigations"], a["published"] + a["completed_not_published"])
        self.assertTrue(s["excluded"], "fixed-mode records must be reported, not skipped silently")
        self.assertTrue(all(x["reason"] for x in s["excluded"]))
        self.assertEqual(s["errors"], [])
        # record parity (162/162 instances, 77/77 distinct at the time of the review) must hold
        self.assertEqual((s["covered"], s["missed"]), (s["cited_model_fetched_records"], []))
        self.assertEqual(s["distinct_per_exception"]["covered"], s["distinct_per_exception"]["targets"])
        # strict NOT_FOUND parity: the denominator is every cited NOT_FOUND search; misses are listed, never hidden
        self.assertEqual(s["not_found_searches_cited"], s["not_found_covered"] + len(s["not_found_missed"]))
        # The former strict miss (rule 1.3): Clone E EXC-CASE-01 SEARCH-08, a follow_relationship search with a different query
        # SHAPE. Since the owner-approved settlement_line_to_transaction equivalence (stage 1) it is covered, and reported
        # SEPARATELY as a semantic match; the exact matcher is unchanged. No miss remains.
        self.assertEqual(s["not_found_missed"], [])
        self.assertEqual(s["not_found_covered_exact"] + len(s["not_found_semantic_matches"]), s["not_found_covered"])
        self.assertEqual([(m["store"], m["exception_id"], m["search_id"], m["query"]) for m in s["not_found_semantic_matches"]],
                         [("clone-e", "EXC-CASE-01", "SEARCH-08", {"evidence_id": "IN-13:SL-SB-GBP-20260915-0003",
                                                                     "relationship": "settlement_line_to_transaction",
                                                                     "value": "TX-0915-00009"})])
        row = next(r for r in rows if r["store"] == "clone-e" and r["exception_id"] == "EXC-CASE-01" and r.get("not_found_semantic_matches"))
        self.assertEqual(row["status"], "completed_not_published")


# ---------------------------------------------------------------------------------------------------------- DR-03
SIX = {"IN-13:SL-AQ-GBP-20260917-0005", "IN-13:SL-AQ-GBP-20260917-0006", "IN-11:TX-0917-00003", "IN-11:TX-0917-00004",
       "IN-11:TX-0917-00005", "IN-11:TX-0917-00006"}


class DR03Budget(unittest.TestCase):
    def test_boundary_51_to_55_with_a_budget_of_52(self):
        """Review reproduction: S05 EXC-01 at 51 records; get_settlement_batch went to 55 against a budget of 52 and its six
        cap-excluded records were not registered."""
        with mock.patch.object(det, "DET_MAX_RECORDS", 52), mock.patch.object(config, "MAX_RECORDS", 55):
            _, p, reg = det_packet("S05", "EXC-S05-01")
        ids = {r["evidence_id"] for r in p["source_records"]}
        self.assertLessEqual(len(p["source_records"]), 52)
        self.assertTrue(SIX <= omitted(reg), sorted(SIX - omitted(reg)))
        self.assertFalse(omitted(reg) & ids)  # what is registered as omitted is really absent
        self.assertEqual(p["pruning_register"], reg)
        for x in reg:
            if x.get("omitted_evidence_ids"):
                self.assertTrue(x["tool"] and x["reason"] and x["step"])

    def test_records_cut_by_the_investigation_wide_max_records_are_registered(self):
        with mock.patch.object(config, "MAX_RECORDS", 55):
            _, p, reg = det_packet("S05", "EXC-S05-01")
        ids = {r["evidence_id"] for r in p["source_records"]}
        self.assertLessEqual(len(ids), 55)
        self.assertTrue(SIX <= omitted(reg), sorted(SIX - omitted(reg)))
        self.assertTrue(any("MAX_RECORDS" in x["reason"] for x in reg if x.get("omitted_evidence_ids")))
        self.assertFalse(omitted(reg) & ids)

    def test_records_cut_by_the_per_call_cap_are_registered(self):
        _, full, _ = det_packet("SC3C", "EXC-SC3C-01")
        with mock.patch.object(config, "TOOL_MAX_RECORDS_PER_CALL", 3):
            _, p, reg = det_packet("SC3C", "EXC-SC3C-01")
        cut = [x for x in reg if "per-call" in x.get("reason", "")]
        self.assertTrue(cut, "a per-call cap of 3 must truncate at least one expansion call")
        ids = {r["evidence_id"] for r in p["source_records"]}
        real = {r["evidence_id"] for r in full["source_records"]}
        for x in cut:
            self.assertTrue(x["omitted_evidence_ids"])
            self.assertFalse(set(x["omitted_evidence_ids"]) & ids)
            self.assertTrue(set(x["omitted_evidence_ids"]) <= real)  # real records of the data, not invented IDs

    def test_budget_is_never_exceeded_by_an_expansion(self):
        for budget in (20, 40, 60):
            for label, _, _, base, store, case, route in all_packets(include_case=False):
                if not det.supported(route):
                    continue
                with self.subTest(label, budget=budget), mock.patch.object(det, "DET_MAX_RECORDS", budget):
                    col = retrieve(route, case, store)
                    before = list(col.records)
                    reg = det.expand(col, case, route, store)
                    self.assertLessEqual(len(col.records), max(budget, len(before)))
                    self.assertEqual(list(col.records)[:len(before)], before)  # nothing removed, order kept
                    self.assertFalse(omitted(reg) & set(col.records))

    def test_found_status_is_not_changed_by_budget_cuts(self):
        """A search whose records were cut for budget reasons is still FOUND (the data exists); never a fabricated NOT_FOUND."""
        with mock.patch.object(det, "DET_MAX_RECORDS", 52), mock.patch.object(config, "MAX_RECORDS", 55):
            _, tight, _ = det_packet("S05", "EXC-S05-01")
        _, full, _ = det_packet("S05", "EXC-S05-01")
        full_res = {(repr(s["query"])): s["result"] for s in full["searches"]}
        for s in tight["searches"]:
            if repr(s["query"]) in full_res:
                self.assertEqual(s["result"], full_res[repr(s["query"])], s["query"])

    def test_production_values_omit_nothing(self):
        for label, _, _, base, store, case, route in all_packets():
            if not det.supported(route):
                continue
            col = retrieve(route, case, store)
            reg = det.expand(col, case, route, store)
            with self.subTest(label):
                self.assertEqual(omitted(reg), set())
                self.assertLess(len(col.records), det.DET_MAX_RECORDS)


if __name__ == "__main__":
    unittest.main()
