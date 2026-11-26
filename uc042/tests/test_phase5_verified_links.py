"""Phase 5 (token-optimisation copy): verified links in the tools' own vocabulary.

The model view lists every identifier link between evidence records that follow_relationship would establish (same
rules, tools.RELATIONSHIPS), so the model need not re-fetch a link Python already holds. Candidates and contextual
(date / free-text) edges are never verified links. Amount mismatches stay visible and are never an explanation.
Run: python -m unittest tests.test_phase5_verified_links -v"""
import json
import unittest

from tests.view_fixtures import all_packets
from uc042lib.investigation import tools
from uc042lib.investigation.packet import collector_from_packet
from uc042lib.investigation.packet_view import CONTEXTUAL_LABELS, reconstruct_packet, render_model_view
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
from tests.test_tool_calling import setup_case

PACKETS = list(all_packets())


def follow(store, packet, evidence_id, relationship):
    args, err = tools.parse_request("follow_relationship", json.dumps({"evidence_id": evidence_id, "relationship": relationship}))
    assert not err, err
    res = tools.execute("follow_relationship", args, store, collector_from_packet(packet))
    return set(res["evidence_ids"]) if isinstance(res, dict) else set(res.result()["evidence_ids"])


class VerifiedLinks(unittest.TestCase):
    def test_every_listed_link_matches_the_tool_result(self):
        n = 0
        for label, _, _, p, store, *_ in PACKETS:
            for rel, frm, to, value, amounts, results in render_model_view(p)["verified_links"]["rows"]:
                with self.subTest(label=label, link=(rel, frm, to)):
                    got = follow(store, p, frm, rel)
                    self.assertIn(to, got)  # the tool returns the listed target
                    if tools.RELATIONSHIPS[rel][3] == "pk":
                        self.assertEqual(got, {to})  # a key lookup: exactly that target
                    n += 1
        self.assertGreater(n, 300)

    def test_no_candidate_or_coincidence_listed_as_verified(self):
        for label, _, _, p, *_ in PACKETS:
            v = render_model_view(p)
            cands = {c["candidate_id"] for c in p["candidate_relationships"]}
            ids = {x for r in v["verified_links"]["rows"] for x in (r[1], r[2])}
            self.assertFalse(ids & cands, label)
            self.assertEqual(set(v["verified_links"]["rules"]) - set(tools.RELATIONSHIPS), set(), label)  # tool vocabulary only
            for e in p["relationships"]:
                if e["relationship"] in CONTEXTUAL_LABELS:
                    self.assertIn(e, v["contextual_associations_NOT_VERIFIED_JOINS"], label)
                    self.assertNotIn(e, v["relationships"], label)
            self.assertFalse({e["relationship"] for e in v["relationships"]} & set(CONTEXTUAL_LABELS), label)

    def test_own_funds_topup_date_edge_is_contextual_only(self):
        found = 0
        for label, _, _, p, *_ in PACKETS:
            v = render_model_view(p)
            topup = [e for e in v["contextual_associations_NOT_VERIFIED_JOINS"] if "OWN_FUNDS_TOPUP" in e["relationship"]]
            for e in topup:
                self.assertNotIn([e["from"], e["to"]], [[r[1], r[2]] for r in v["verified_links"]["rows"]])
            found += len(topup)
        self.assertGreater(found, 0)

    def test_view_with_links_is_still_lossless(self):
        for label, _, _, p, *_ in PACKETS:
            r = reconstruct_packet(render_model_view(p))
            self.assertEqual(sorted(json.dumps(e, sort_keys=True) for e in r["relationships"]),
                             sorted(json.dumps(e, sort_keys=True) for e in p["relationships"]), label)


class AmountMismatchesStayVisible(unittest.TestCase):
    def test_sc3c_reference_matches_with_different_amounts(self):
        _, p, _ = setup_case("SC3C", "EXC-SC3C-01")
        rows = render_model_view(p)["verified_links"]["rows"]
        mism = [r for r in rows if r[4] and r[4][2] is False]
        self.assertEqual(sorted((r[0], r[1], r[2], r[4][0], r[4][1], tuple(r[5])) for r in mism), [
            ("cashbook_to_bank_entry", "IN-10:LE-GBP-0908-0003", "IN-09:BE-GBP-0908-AQ1", "9954.50", "9950.00", ("CASH-BANK-LINK|LE-GBP-0908-0003",)),
            ("settlement_batch_to_bank_entry", "IN-12:AQ-GBP-20260908", "IN-09:BE-GBP-0908-AQ1", "9954.50", "9950.00", ("C11-BATCH-BANK|AQ-GBP-20260908",))])
        self.assertFalse(any(r[0] in ("settlement_line_to_batch", "transaction_to_batch") and r[4] for r in rows))  # part-to-whole never compared
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            self.assertIn("is never an explanation of why", prompt)


class RedundantRequestsUnnecessary(unittest.TestCase):
    def test_the_15_nov_redundant_follow_relationship_calls_are_already_listed(self):
        """15 Nov SC3C EXC-01 round 2 re-followed two links that were already in the packet; both are now listed."""
        _, p, _ = setup_case("SC3C", "EXC-SC3C-01")
        listed = {(r[0], r[1], r[2]) for r in render_model_view(p)["verified_links"]["rows"]}
        self.assertIn(("settlement_batch_to_bank_entry", "IN-12:AQ-GBP-20260908", "IN-09:BE-GBP-0908-AQ1"), listed)
        self.assertIn(("cashbook_to_bank_entry", "IN-10:LE-GBP-0908-0003", "IN-09:BE-GBP-0908-AQ1"), listed)
        self.assertIn("Do not call follow_relationship to confirm a link listed in verified_links", TOOLS_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
