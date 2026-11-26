"""Stage 3 (DR-04): verified-link amounts are compared only on genuine one-to-one links (the source has exactly one target
and the target exactly one source, for that relationship), using SIGNED values (each record's own direction field gives
the sign; a missing or unknown direction means no comparison). Part-to-whole relationships are never compared. The links
themselves (tools.RELATIONSHIPS) are unchanged. Offline. Run: python -m unittest tests.test_stage3_dr04_amounts -v"""
import unittest
from pathlib import Path

from tests.view_fixtures import all_packets
from uc042lib.investigation import tools
from uc042lib.investigation.packet_view import verified_links

ROOT = Path(__file__).resolve().parent.parent


def rec(fid, pk, **fields):
    return {"evidence_id": f"{fid}:{pk}", "file_id": fid, "fields": fields}


def packet(*records):
    return {"source_records": list(records), "control_results": []}


def rows_of(p, name):
    return [r for r in verified_links(p)["rows"] if r[0] == name]


def batch(bid, amount, direction, ref="REF-1", acct="SGA-GBP-01"):
    return rec("IN-12", bid, batch_id=bid, account_id=acct, expected_bank_reference=ref, net_amount_reported=amount, direction=direction)


def bank(beid, amount, dc, ref="REF-1", acct="SGA-GBP-01"):
    return rec("IN-09", beid, bank_entry_id=beid, account_id=acct, bank_reference=ref, end_to_end_ref="", amount=amount, dc_indicator=dc)


def cash(leid, amount, dc, ref="REF-1", acct="SGA-GBP-01"):
    return rec("IN-10", leid, ledger_entry_id=leid, account_id=acct, payment_reference=ref, amount=amount, dc_indicator=dc)


class SignedOneToOne(unittest.TestCase):
    def test_matching_one_to_one_amounts_agree(self):
        for p, name, want in (
                (packet(batch("SB-1", "100.00", "TO_FIRM"), bank("BE-1", "100.00", "C")), "settlement_batch_to_bank_entry", ["100.00", "100.00", True]),
                (packet(batch("SB-1", "100.00", "FROM_FIRM"), bank("BE-1", "100.00", "D")), "settlement_batch_to_bank_entry", ["-100.00", "-100.00", True]),
                (packet(cash("LE-1", "50.25", "D"), bank("BE-1", "50.25", "C")), "cashbook_to_bank_entry", ["50.25", "50.25", True]),
                (packet(rec("IN-13", "SL-1", line_id="SL-1", txn_id="TX-1", amount="9.99", dc_indicator="D"),
                        rec("IN-11", "TX-1", txn_id="TX-1", amount="9.99", direction="DR")), "settlement_line_to_transaction", ["-9.99", "-9.99", True])):
            with self.subTest(name, want=want):
                self.assertEqual([r[4] for r in rows_of(p, name)], [want])

    def test_opposite_signed_amounts_do_not_agree(self):
        """Equal magnitudes in opposite directions: under 1.1 (absolute values) these 'agreed'."""
        cases = ((packet(batch("SB-1", "100.00", "TO_FIRM"), bank("BE-1", "100.00", "D")), "settlement_batch_to_bank_entry"),
                 (packet(cash("LE-1", "50.25", "D"), bank("BE-1", "50.25", "D")), "cashbook_to_bank_entry"),
                 (packet(rec("IN-13", "SL-1", line_id="SL-1", txn_id="TX-1", amount="9.99", dc_indicator="D"),
                         rec("IN-11", "TX-1", txn_id="TX-1", amount="9.99", direction="CR")), "settlement_line_to_transaction"))
        for p, name in cases:
            with self.subTest(name):
                (row,) = rows_of(p, name)
                self.assertIs(row[4][2], False)
                self.assertNotEqual(row[4][0], row[4][1])

    def test_one_to_many_is_not_compared(self):
        """The review's H202606 shape: one batch, two bank entries with the same reference."""
        p = packet(batch("SB-1", "3449.50", "FROM_FIRM"), bank("BE-A", "3449.50", "D"), bank("BE-B", "2344.78", "D"))
        rows = rows_of(p, "settlement_batch_to_bank_entry")
        self.assertEqual(len(rows), 2)  # both links still listed (identifier joins are unchanged)
        self.assertEqual([r[4] for r in rows], [None, None])

    def test_many_to_one_is_not_compared(self):
        p = packet(cash("LE-1", "10.00", "D"), cash("LE-2", "10.00", "D"), bank("BE-1", "10.00", "C"))
        rows = rows_of(p, "cashbook_to_bank_entry")
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[4] for r in rows], [None, None])

    def test_part_to_whole_is_never_compared(self):
        p = packet(rec("IN-13", "SL-1", line_id="SL-1", batch_id="SB-1", txn_id="", amount="10.00", dc_indicator="D"),
                   rec("IN-12", "SB-1", batch_id="SB-1", account_id="A", expected_bank_reference="", net_amount_reported="10.00", direction="FROM_FIRM"),
                   rec("IN-11", "TX-1", txn_id="TX-1", settlement_batch_id="SB-1", amount="10.00", direction="DR"))
        for name in ("settlement_line_to_batch", "transaction_to_batch"):
            with self.subTest(name):
                (row,) = rows_of(p, name)  # a genuine 1:1 link here, yet part-to-whole by definition
                self.assertIsNone(row[4])

    def test_missing_amounts_or_directions_are_not_compared(self):
        for p in (packet(batch("SB-1", "", "TO_FIRM"), bank("BE-1", "100.00", "C")),
                  packet(batch("SB-1", "100.00", "TO_FIRM"), bank("BE-1", None, "C")),
                  packet(batch("SB-1", "100.00", ""), bank("BE-1", "100.00", "C")),
                  packet(batch("SB-1", "100.00", "SIDEWAYS"), bank("BE-1", "100.00", "C")),
                  packet(batch("SB-1", "abc", "TO_FIRM"), bank("BE-1", "100.00", "C"))):
            with self.subTest(p["source_records"][0]["fields"]):
                (row,) = rows_of(p, "settlement_batch_to_bank_entry")
                self.assertIsNone(row[4])

    def test_column_states_the_rule(self):
        cols = verified_links(packet())["columns"]
        self.assertIn("one-to-one", cols[4])
        self.assertIn("signed", cols[4])


class RealPackets(unittest.TestCase):
    def test_h202606_split_links_are_not_compared(self):
        p = next(p for label, _, _, p, *_ in all_packets(include_case=False) if label == "history:H202606/EXC-H202606-01")
        rows = {(r[0], r[1], r[2]): r[4] for r in verified_links(p)["rows"]}
        for key in (("settlement_batch_to_bank_entry", "IN-12:SB-GBP-20260601", "IN-09:BE-GBP-0601-SB1"),
                    ("settlement_batch_to_bank_entry", "IN-12:SB-GBP-20260601", "IN-09:BE-GBP-0610-SB1"),
                    ("cashbook_to_bank_entry", "IN-10:LE-GBP-0601-0005", "IN-09:BE-GBP-0601-SB1"),
                    ("cashbook_to_bank_entry", "IN-10:LE-GBP-0601-0005", "IN-09:BE-GBP-0610-SB1")):
            self.assertIn(key, rows)
            self.assertIsNone(rows[key], key)

    def test_every_compared_link_is_one_to_one_and_signed(self):
        n = 0
        for label, _, _, p, *_ in all_packets():
            rows = verified_links(p)["rows"]
            out_n, in_n = {}, {}
            for r in rows:
                out_n[(r[0], r[1])] = out_n.get((r[0], r[1]), 0) + 1
                in_n[(r[0], r[2])] = in_n.get((r[0], r[2]), 0) + 1
            for r in rows:
                if r[4] is not None:
                    n += 1
                    self.assertEqual((out_n[(r[0], r[1])], in_n[(r[0], r[2])]), (1, 1), (label, r))
                    self.assertIn(r[0], ("settlement_batch_to_bank_entry", "cashbook_to_bank_entry", "settlement_line_to_transaction"))
        self.assertGreater(n, 50)

    def test_relationship_definitions_unchanged(self):
        clone_e = (Path("C:/Users/artlptp263user/p10/uc042_e/uc042lib/investigation/tools.py"))
        if clone_e.is_file():
            self.assertEqual(clone_e.read_bytes(), (ROOT / "uc042lib" / "investigation" / "tools.py").read_bytes())
        self.assertEqual(tools.RELATIONSHIPS["settlement_batch_to_bank_entry"][:4], ("IN-12", "expected_bank_reference", "IN-09", "bank_ref"))


if __name__ == "__main__":
    unittest.main()
