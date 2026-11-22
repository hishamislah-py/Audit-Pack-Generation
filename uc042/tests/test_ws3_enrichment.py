"""Workstream 3 reconciliation enrichment (uc042lib.enrichment, EngineRules.enrichment_v1). Run from the engine folder:
    python -m unittest tests.test_ws3_enrichment -v

Every case is a temporary copy (clean baseline + explicit mutations, or a frozen scenario copied unchanged). Committed
datasets and the TC snapshot are never written. Validator runs are in memory except the write_outputs test (temp copy).
"""
import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from uc042lib import enrichment
from uc042lib import validate as V
from uc042lib.scenarios import apply, read, set_op
from uc042lib.validate import APPROVED_RULES, DEFAULT_SET, ENRICHED_RULES, EngineRules, Validator

DATASETS = DEFAULT_SET.parent
FROZEN = ["set_01_clean_baseline", "scn_S02_missing_eur_statement", "scn_S05_unexplained_gbp_difference",
          "scn_SC2_settlement_timing", "scn_SC3B_fee_not_itemised", "scn_SC3C_short_settlement",
          "scn_SC5A_missing_transaction", "scn_SC5C_refund_double_posted", "scn_SC5D_closing_snapshot_mismatch"]
TC_SNAPSHOT = Path(r"C:\u42v\enrich_20261123\outputs\tc_snapshot_0205")
SKIP_TREE = {"validation", "VALIDATION_REPORT.md"}


# --- fixtures ---------------------------------------------------------------------------------------------------------
class Tmp:
    root = None

    @classmethod
    def dir(cls):
        if cls.root is None:
            cls.root = Path(tempfile.mkdtemp(prefix="ws3_enrichment_"))
        return cls.root


def tearDownModule():
    if Tmp.root is not None:
        shutil.rmtree(Tmp.root, ignore_errors=True)


def copy_case(source, name, keep_manifest=True):
    """Copy a case directory (without generated outputs). The manifest is dropped for mutated copies."""
    dst = Tmp.dir() / name
    shutil.copytree(source, dst, ignore=lambda d, names: [n for n in names if n in SKIP_TREE])
    if not keep_manifest and (dst / "manifest.csv").exists():
        (dst / "manifest.csv").unlink()
    return dst


def mutated(name, ops):
    root = copy_case(DEFAULT_SET, name, keep_manifest=False)
    apply(root, ops)
    return root


def row(fid, key, source=DEFAULT_SET):
    from uc042lib import schema
    pk = schema.columns(fid)[0]
    return dict(next(r for r in read(source, fid) if r[pk] == key))


def add(fid, record, after=None):
    op = {"op": "add_record", "file_id": fid, "record": record}
    if after:
        op["insert_after"] = after
    return op


def delete(fid, key):
    return {"op": "delete_record", "file_id": fid, "key": key}


def run(root, rules=ENRICHED_RULES):
    v = Validator(root, rules=rules)
    v.run()
    return v


def result(v, check, scope):
    return next(r for r in v.results if r["check_id"] == check and r["scope"] == scope)


def exc_by_root(v, prefix):
    return [x for x in v.exceptions if x["root_cause"].startswith(prefix)]


def groups_by_root(v):
    """Investigation groups as sets of root causes (independent of exception numbering)."""
    out = {}
    for x in v.exceptions:
        if x["investigation_group_id"]:
            out.setdefault(x["investigation_group_id"], set()).add(x["root_cause"])
    return sorted((frozenset(g) for g in out.values()), key=sorted)


def rels(v, link_type=None, strength=None):
    return [r for r in v.enrichment["relationships"]
            if (link_type is None or r["link_type"] == link_type) and (strength is None or r["strength"] == strength)]


def eid(v, root):
    return next(x["exception_id"] for x in v.exceptions if x["root_cause"] == root)


# Scenario mutations (synthetic; from the approved TC specifications)
def tc01_ops():
    dup = row("IN-10", "LE-GBP-0928-0001")
    dup.update(ledger_entry_id="LE-GBP-0928-0007", posted_ts="2026-09-28T09:25:00+01:00")
    return [add("IN-10", dup, after="LE-GBP-0928-0001")]


def tc02_ops():
    return [set_op("IN-11", "TX-0908-00002", "amount", "3035.61", "3053.61", "transposition in the export")]


def tc05_ops(ids=("TX-0924-00018", "TX-0924-00019", "TX-0924-00020")):
    return [delete("IN-11", t) for t in ids]


def tc06_ops():
    return [set_op("IN-11", "TX-0917-00002", "amount", "1390.07", "1480.07"),
            set_op("IN-03", "CBS-20260917-C0004-GBP", "balance", "40592.24", "40682.24"),
            set_op("IN-05", "IRR-EMONEY-GBP-20260917", "requirement_reported", "341484.46", "341574.46"),
            set_op("IN-05", "IRR-EMONEY-GBP-20260917", "difference_reported", "0.00", "-90.00"),
            set_op("IN-13", "SL-AQ-EUR-20260922-0002", "amount", "1283.12", "1238.12")]


def tc04_ops(claimed=False):
    be = row("IN-09", "BE-EUR-0930-R01")
    be.update(bank_entry_id="BE-EUR-0930-U01", booking_ts="2026-09-30T16:20:00+01:00", amount="650.00", dc_indicator="C",
              bank_reference="E2E-EUR-0930-U01", end_to_end_ref="E2E-EUR-0930-U01",
              counterparty_name="Synthetic payer (unidentified)", narrative_text="INBOUND TRANSFER")
    ops = [add("IN-09", be, after="BE-EUR-0930-R01"),
           set_op("IN-08", "ST-SGA-EUR-01-20260930-EOD", "closing_balance_amount", "118555.00", "119205.00"),
           set_op("IN-08", "ST-SGA-EUR-01-20260930-EOD", "entry_count", "5", "6"),
           set_op("IN-07", "ST-SGA-EUR-01-20260930-1700", "balance_amount", "118555.00", "119205.00"),
           set_op("IN-06", "ERL-SGA-EUR-01-20260930", "bank_balance_reported", "118555.00", "119205.00"),
           set_op("IN-06", "ERL-SGA-EUR-01-20260930", "difference_reported", "0.00", "650.00")]
    if claimed:
        ops.append(set_op("IN-06", "ERL-SGA-EUR-01-20260930", "timing_difference_claimed", "false", "true"))
    return ops


def cross_period_timing_ops():
    """Scheme batch SB-GBP-20260930 posted on 30 Sep, not booked by the bank in September (clearing unverifiable)."""
    return [delete("IN-09", "BE-GBP-0930-SB1"),
            set_op("IN-08", "ST-SGA-GBP-01-20260930-EOD", "closing_balance_amount", "395844.86", "398565.01"),
            set_op("IN-08", "ST-SGA-GBP-01-20260930-EOD", "entry_count", "6", "5"),
            set_op("IN-07", "ST-SGA-GBP-01-20260930-1700", "balance_amount", "395844.86", "398565.01"),
            set_op("IN-06", "ERL-SGA-GBP-01-20260930", "bank_balance_reported", "395844.86", "398565.01"),
            set_op("IN-06", "ERL-SGA-GBP-01-20260930", "difference_reported", "0.00", "2720.15")]


# --- A. duplicates -----------------------------------------------------------------------------------------------------
class A_Duplicates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tc01 = mutated("a_tc01", tc01_ops())
        cls.v, cls.v0 = run(cls.tc01), run(cls.tc01, APPROVED_RULES)
        clean = copy_case(DEFAULT_SET, "a_clean")
        cls.clean = run(clean)

    def test_exact_duplicate_is_flagged_and_original_passes(self):
        r = result(self.v, "CASH-BANK-LINK", "LE-GBP-0928-0007")
        self.assertEqual((r["outcome"], r["root_cause"]), ("FAIL", "DUPLICATE_CASHBOOK_ENTRY|LE-GBP-0928-0007"))
        self.assertEqual(r["structured"]["duplicate"]["classification"], "EXACT_DUPLICATE")
        self.assertEqual(r["structured"]["duplicate"]["duplicate_of"], "LE-GBP-0928-0001")
        self.assertEqual(r["structured"]["duplicate"]["bank_entry_id"], "BE-GBP-0928-L01")
        o = result(self.v, "CASH-BANK-LINK", "LE-GBP-0928-0001")
        self.assertEqual(o["outcome"], "PASS")
        self.assertEqual(o["structured"]["duplicate_claimants"], ["LE-GBP-0928-0007"])

    def test_duplicate_exception_carries_account_date_amount_and_category(self):
        (x,) = exc_by_root(self.v, "DUPLICATE_CASHBOOK_ENTRY|")
        self.assertEqual((x["account_id"], x["currency"], x["first_date"], x["amount"], x["severity"]),
                         ("SGA-GBP-01", "GBP", "2026-09-28", "1246.80", "High"))
        self.assertEqual(x["category"], enrichment.CATEGORY[enrichment.DUP_CASH])
        self.assertEqual(x["status"], "OPEN")
        (d,) = [d for d in self.v.enrichment["duplicates"] if d.get("outcome_changed")]
        self.assertEqual(d["exception_id"], x["exception_id"])

    def test_default_rules_unchanged_both_rows_pass_gap_g04(self):
        for le in ("LE-GBP-0928-0001", "LE-GBP-0928-0007"):
            self.assertEqual(result(self.v0, "CASH-BANK-LINK", le)["outcome"], "PASS")
        self.assertIsNone(self.v0.enrichment)
        self.assertFalse(exc_by_root(self.v0, "DUPLICATE_"))

    def test_legitimate_repeats_in_the_clean_baseline_are_not_duplicates(self):
        # 4 x 2,500.00 LOAD_CARD on 8 Sep (different clients, own lines) and refunds equal to their originals
        self.assertEqual(self.clean.enrichment["duplicates"], [])
        self.assertEqual(self.clean.enrichment["suspected_duplicates"], [])
        self.assertEqual(self.clean.exceptions, [])
        loads = [t for t in self.clean.rows("IN-11") if t["amount"] == "2500.00" and t["executed_ts"].startswith("2026-09-08")]
        self.assertGreaterEqual(len(loads), 4)

    def test_conflicting_claim_same_reference_different_amount(self):
        dup = row("IN-10", "LE-GBP-0928-0001")
        dup.update(ledger_entry_id="LE-GBP-0928-0007", posted_ts="2026-09-28T09:25:00+01:00", amount="1000.00")
        v = run(mutated("a_conflict", [add("IN-10", dup, after="LE-GBP-0928-0001")]))
        r = result(v, "CASH-BANK-LINK", "LE-GBP-0928-0007")
        self.assertEqual((r["outcome"], r["root_cause"]), ("FAIL", "DUPLICATE_CASHBOOK_ENTRY|LE-GBP-0928-0007"))
        self.assertEqual(r["structured"]["duplicate"]["classification"], "CONFLICTING_CLAIM")
        self.assertEqual(result(v, "CASH-BANK-LINK", "LE-GBP-0928-0001")["outcome"], "PASS")

    def test_split_posting_is_not_a_duplicate(self):
        a = row("IN-10", "LE-GBP-0928-0001")
        b = dict(a, ledger_entry_id="LE-GBP-0928-0007", amount="246.80")
        ops = [set_op("IN-10", "LE-GBP-0928-0001", "amount", "1246.80", "1000.00"), add("IN-10", b, after="LE-GBP-0928-0001")]
        v = run(mutated("a_split", ops))
        (d,) = v.enrichment["duplicates"]
        self.assertEqual((d["classification"], d["outcome_changed"]), ("SPLIT_POSTING", False))
        self.assertFalse(exc_by_root(v, "DUPLICATE_"))
        # existing amount checks still apply to each row
        self.assertEqual(result(v, "CASH-BANK-LINK", "LE-GBP-0928-0001")["outcome"], "FAIL")

    def test_transaction_side_duplicate(self):
        t = row("IN-11", "TX-0928-00001")
        v = run(mutated("a_txn_dup", [add("IN-11", dict(t, txn_id="TX-0928-90001"), after="TX-0928-00001")]))
        r = result(v, "RC4-DIRECT", "TX-0928-90001")
        self.assertEqual((r["outcome"], r["root_cause"]), ("FAIL", "DUPLICATE_TRANSACTION|TX-0928-90001"))
        self.assertEqual(r["structured"]["duplicate"]["classification"], "EXACT_DUPLICATE")
        self.assertEqual(result(v, "RC4-DIRECT", "TX-0928-00001")["outcome"], "PASS")
        (x,) = exc_by_root(v, "DUPLICATE_TRANSACTION|")
        self.assertEqual((x["account_id"], x["first_date"], x["amount"]), ("SGA-GBP-01", "2026-09-28", "1246.80"))
        # the client roll-forward failure is explained by the duplicate (L4, CONFIRMED) and grouped with it
        l4 = rels(v, "L4 TRANSACTION LINEAGE", "CONFIRMED")
        self.assertTrue(any(x["exception_id"] in r_["exception_ids"] for r_ in l4))
        self.assertIn(frozenset({x["root_cause"], "CBAL-ROLLFWD|GBP/C0008 2026-09-28"}), groups_by_root(v))

    def test_suspected_card_duplicate_is_annotation_only(self):
        t = row("IN-11", "TX-0901-00007")
        v = run(mutated("a_card_dup", [add("IN-11", dict(t, txn_id="TX-0901-90007"), after="TX-0901-00007")]))
        r = result(v, "C11-TXN-LINE", "TX-0901-90007")
        self.assertEqual(r["outcome"], "FAIL")
        self.assertEqual(r["root_cause"], "C11-TXN-LINE|TX-0901-90007")
        self.assertEqual(r["structured"]["suspected_duplicate"]["suspected_duplicate_of"], "TX-0901-00007")
        self.assertEqual(r["structured"]["suspected_duplicate"]["classification"], "SUSPECTED_DUPLICATE")
        self.assertFalse(exc_by_root(v, "DUPLICATE_"))
        (s,) = v.enrichment["suspected_duplicates"]
        self.assertEqual(s["exception_id"], eid(v, "C11-TXN-LINE|TX-0901-90007"))


# --- B. amount comparison -----------------------------------------------------------------------------------------------
class B_AmountComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = run(mutated("b_tc02", tc02_ops()))

    def comp(self, v, check, scope):
        return result(v, check, scope)["structured"]["comparison"]

    def test_tc02_difference_direction_and_outlier(self):
        c = self.comp(self.v, "RC4-DIRECT", "TX-0908-00002")
        self.assertEqual((c["difference"], c["direction"]), ("18.00", "TRANSACTION_GREATER_THAN_BANK"))
        self.assertEqual(c["difference_basis"], "IN-11 - IN-09")
        o = c["outlier"]
        self.assertEqual((o["status"], o["source"], o["record"]), ("IDENTIFIED", "IN-11", "TX-0908-00002"))
        self.assertEqual(o["corroborating_sources"], ["IN-03", "IN-09", "IN-10"])
        self.assertEqual((o["outlier_value"], o["agreed_value"]), ("3053.61", "3035.61"))
        self.assertEqual(c["exception_id"], eid(self.v, "RC4-DIRECT|TX-0908-00002"))

    def test_decimal_exactness_of_every_comparison(self):
        for c in self.v.enrichment["amount_comparisons"]:
            self.assertEqual(Decimal(c["difference"]), Decimal(c["difference"]).quantize(Decimal("0.01")), c)
            for x in c["values"]:
                self.assertRegex(x["amount"], r"^-?\d+\.\d{2}$")
        cb = self.comp(self.v, "CBAL-ROLLFWD", "GBP/C0006 2026-09-08")
        self.assertEqual((cb["difference"], cb["direction"]), ("18.00", "ROLL_FORWARD_GREATER_THAN_SNAPSHOT"))

    def test_two_two_split_is_undetermined(self):
        # the cash book carries the same wrong amount as the export: 2 sources against 2, no single outlier
        ops = tc02_ops() + [set_op("IN-10", "LE-GBP-0908-0002", "amount", "3035.61", "3053.61")]
        v = run(mutated("b_split", ops))
        c = self.comp(v, "RC4-DIRECT", "TX-0908-00002")
        self.assertEqual(c["outlier"]["status"], "UNDETERMINED")
        self.assertEqual(c["difference"], "18.00")

    def test_two_sources_only_is_undetermined(self):
        o = enrichment._outlier([{"source": "IN-11", "record": "a", "amount": "1.00"}, {"source": "IN-09", "record": "b", "amount": "2.00"}])
        self.assertEqual(o["status"], "UNDETERMINED")
        o = enrichment._outlier([{"source": "A", "record": "a", "amount": "1.00"}, {"source": "B", "record": "b", "amount": "2.00"},
                                 {"source": "C", "record": "c", "amount": "3.00"}])
        self.assertEqual(o["status"], "UNDETERMINED")

    def test_batch_line_mismatch_outlier_is_the_line(self):
        v = run(mutated("b_line", [set_op("IN-13", "SL-AQ-EUR-20260922-0002", "amount", "1283.12", "1238.12")]))
        lc = result(v, "C11-BATCH-ARITH", "AQ-EUR-20260922")["structured"]["line_comparison"]
        (m,) = lc["line_mismatches"]
        self.assertEqual((m["difference"], m["direction"]), ("-45.00", "LINE_LESS_THAN_TRANSACTION"))
        self.assertEqual((m["outlier"]["status"], m["outlier"]["source"]), ("IDENTIFIED", "IN-13"))
        self.assertEqual(lc["missing_transactions"], [])

    def test_clean_baseline_has_no_comparisons(self):
        v = run(copy_case(DEFAULT_SET, "b_clean"))
        self.assertEqual(v.enrichment["amount_comparisons"], [])


# --- C. timing traceability ---------------------------------------------------------------------------------------------
class C_Timing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc2 = copy_case(DATASETS / "scn_SC2_settlement_timing", "c_sc2")
        cls.v, cls.v0 = run(cls.sc2), run(cls.sc2, APPROVED_RULES)

    def test_sc2_evidence_status_unchanged_and_trace_evidenced(self):
        self.assertEqual([x["evidence_status"] for x in self.v.exceptions], [x["evidence_status"] for x in self.v0.exceptions])
        (x,) = self.v.exceptions
        self.assertEqual((x["evidence_status"], x["status"], x["review_status"]), ("TIMING_EVIDENCED", "OPEN", "AWAITING_HUMAN_REVIEW"))
        (t,) = self.v.enrichment["timing_traces"]
        self.assertEqual((t["evidence_class"], t["resolves_exception"], t["exception_status"]), ("EVIDENCED", False, "OPEN"))
        self.assertEqual(t["residual"], "0.00")
        (item,) = t["items"]
        self.assertEqual(item["reference"], "SB-GBP-20260915")
        self.assertEqual(item["batch"]["batch_id"], "SB-GBP-20260915")
        self.assertTrue(t["claim_is_not_evidence"])

    def test_unverifiable_clearing_links_difference_batch_and_cashbook_suspected(self):
        v = run(mutated("c_cross", cross_period_timing_ops()))
        bld = eid(v, "BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-30|2720.15")
        (t,) = v.enrichment["timing_traces"]
        self.assertEqual((t["exception_id"], t["evidence_class"], t["resolves_exception"]), (bld, "SUSPECTED", False))
        l5 = rels(v, "L5 TIMING TRACE", "CONFIRMED")
        linked = {i for r in l5 for i in r["exception_ids"]} - {bld}
        self.assertEqual(linked, {eid(v, "C11-BATCH-BANK|SB-GBP-20260930"), eid(v, "UNMATCHED_CASHBOOK_ENTRY|LE-GBP-0930-0005")})
        self.assertIn(frozenset({"BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-30|2720.15", "C11-BATCH-BANK|SB-GBP-20260930",
                                 "UNMATCHED_CASHBOOK_ENTRY|LE-GBP-0930-0005"}), groups_by_root(v))
        x = next(x for x in v.exceptions if x["exception_id"] == bld)
        self.assertEqual((x["status"], x["evidence_status"]), ("OPEN", "TIMING_UNVERIFIABLE"))
        # default rules: the difference is not grouped (gap G-12)
        v0 = run(mutated("c_cross0", cross_period_timing_ops()), APPROVED_RULES)
        self.assertEqual(next(x for x in v0.exceptions if x["root_cause"].startswith("BANK_LEDGER"))["investigation_group_id"], "")

    def test_timing_claim_alone_is_claimed_only_never_evidenced(self):
        v = run(mutated("c_claim", tc04_ops(claimed=True)))
        (t,) = v.enrichment["timing_traces"]
        self.assertEqual((t["evidence_class"], t["timing_claimed_by_preparer"], t["items"]), ("CLAIMED_ONLY", True, []))
        self.assertEqual(next(x for x in v.exceptions if x["root_cause"].startswith("BANK_LEDGER"))["evidence_status"], "NOT_EVIDENCED")

    def test_no_trace_without_items_or_claim(self):
        v = run(mutated("c_noclaim", tc04_ops()))
        self.assertEqual(v.enrichment["timing_traces"], [])


# --- D. lineage ------------------------------------------------------------------------------------------------------------
class D_Lineage(unittest.TestCase):
    def test_tc02_confirmed_transaction_lineage_groups(self):
        v = run(mutated("d_tc02", tc02_ops()))
        (r,) = rels(v, "L4 TRANSACTION LINEAGE")
        self.assertEqual(r["strength"], "CONFIRMED")
        self.assertEqual(groups_by_root(v), [frozenset({"RC4-DIRECT|TX-0908-00002", "CBAL-ROLLFWD|GBP/C0006 2026-09-08"})])
        self.assertEqual(v.groups[0]["correlation_version"], enrichment.CORRELATION_VERSION)
        s = next(e for e in v.enrichment["exceptions"] if e["root_cause"] == "RC4-DIRECT|TX-0908-00002")
        lin = next(l for l in s["lineage"] if l["txn_id"] == "TX-0908-00002")
        self.assertEqual((lin["bank_entries"], lin["cashbook_entries"]), (["BE-GBP-0908-L02"], ["LE-GBP-0908-0002"]))
        # default rules: not grouped (gap G-08)
        self.assertEqual(run(mutated("d_tc02_0", tc02_ops()), APPROVED_RULES).groups, [])

    def test_unreconciled_amounts_give_a_candidate_not_a_group(self):
        ops = tc02_ops() + [set_op("IN-03", "CBS-20260908-C0006-GBP", "balance", "39108.37", "39113.37")]
        v = run(mutated("d_unrec", ops))
        (r,) = rels(v, "L4 TRANSACTION LINEAGE")
        self.assertEqual(r["strength"], "CANDIDATE")
        rc4, cbal = eid(v, "RC4-DIRECT|TX-0908-00002"), eid(v, "CBAL-ROLLFWD|GBP/C0006 2026-09-08")
        g = {x["exception_id"]: x["investigation_group_id"] for x in v.exceptions}
        self.assertFalse(g[rc4] and g[rc4] == g[cbal])
        self.assertIn(sorted([rc4, cbal]), [sorted(c["exception_ids"].split("; ")) for c in v.candidates])
        self.assertFalse(rels(v, strength="CONFIRMED") and any(rc4 in r_["exception_ids"] for r_ in rels(v, strength="CONFIRMED")))


# --- E. common cause -----------------------------------------------------------------------------------------------------
class E_CommonCause(unittest.TestCase):
    def test_tc05_line_sum_candidate_and_suspected_common_cause(self):
        v = run(mutated("e_tc05", tc05_ops()))
        batch = eid(v, "C11-BATCH-ARITH|SB-EUR-20260924")
        c0101, c0104 = eid(v, "CBAL-ROLLFWD|EUR/C0101 2026-09-24"), eid(v, "CBAL-ROLLFWD|EUR/C0104 2026-09-24")
        cands = {tuple(sorted(c["exception_ids"].split("; "))): c["basis"] for c in v.candidates}
        self.assertEqual(cands[tuple(sorted([batch, c0104]))], "DATE_AND_AMOUNT_COINCIDENCE")  # existing D-E2a kept
        self.assertEqual(cands[tuple(sorted([batch, c0101]))], "LINE_SUM_MATCH")
        ls = next(r for r in rels(v, "LINE-SUM MATCH") if c0101 in r["exception_ids"])
        self.assertIn("SL-SB-EUR-20260924-0002", ls["basis"])
        self.assertIn("SL-SB-EUR-20260924-0003", ls["basis"])
        self.assertEqual(ls["strength"], "CANDIDATE")
        (cc,) = v.enrichment["common_causes"]
        self.assertEqual((cc["status"], cc["all_missing_lines_accounted_for"]), ("SUSPECTED", True))
        self.assertEqual(set(cc["exception_ids"]), {batch, c0101, c0104})
        self.assertTrue(cc["missing_evidence"])
        self.assertEqual(v.groups, [])  # amounts alone never group

    def test_unreconcilable_difference_is_not_attributed(self):
        ops = tc05_ops() + [set_op("IN-03", "CBS-20260924-C0101-EUR", "balance", "29990.41", "29991.41")]
        v = run(mutated("e_insuf", ops))
        batch, c0101 = eid(v, "C11-BATCH-ARITH|SB-EUR-20260924"), eid(v, "CBAL-ROLLFWD|EUR/C0101 2026-09-24")
        self.assertFalse([r for r in rels(v, "LINE-SUM MATCH") if c0101 in r["exception_ids"]])
        (cc,) = v.enrichment["common_causes"]
        self.assertFalse(cc["all_missing_lines_accounted_for"])
        self.assertEqual(cc["unaccounted_lines"], ["SL-SB-EUR-20260924-0002", "SL-SB-EUR-20260924-0003"])
        self.assertEqual(next(x for x in v.exceptions if x["exception_id"] == batch)["investigation_group_id"], "")
        self.assertFalse([r for r in v.enrichment["relationships"] if r["strength"] == "CONFIRMED" and batch in r["exception_ids"]])

    def test_single_missing_line_matches_its_client_only(self):
        v = run(mutated("e_one", tc05_ops(("TX-0924-00019",))))
        batch = eid(v, "C11-BATCH-ARITH|SB-EUR-20260924")
        self.assertEqual([x["root_cause"] for x in exc_by_root(v, "CBAL-ROLLFWD")], ["CBAL-ROLLFWD|EUR/C0101 2026-09-24"])
        self.assertEqual(len(v.candidates), 1)  # the existing single-line candidate; no duplicate row added
        self.assertEqual(v.groups, [])
        (cc,) = v.enrichment["common_causes"]
        self.assertTrue(cc["all_missing_lines_accounted_for"])
        self.assertEqual(set(cc["exception_ids"]), {batch, eid(v, "CBAL-ROLLFWD|EUR/C0101 2026-09-24")})


# --- F. independent causes -------------------------------------------------------------------------------------------------
class F_IndependentCauses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = mutated("f_tc06", tc06_ops())
        cls.v, cls.v0 = run(cls.root), run(cls.root, APPROVED_RULES)

    def test_three_independent_clusters(self):
        A = frozenset({"RC4-DIRECT|TX-0917-00002", "CBAL-ROLLFWD|GBP/C0007 2026-09-17"})
        B = frozenset({"INTERNAL_DIFFERENCE|2026-09-17/GBP", "CBAL-ROLLFWD|GBP/C0004 2026-09-17", "CBAL-ROLLFWD|GBP/C0004 2026-09-18"})
        self.assertEqual(groups_by_root(self.v), sorted([A, B], key=sorted))
        self.assertEqual(next(x for x in self.v.exceptions if x["root_cause"] == "C11-BATCH-ARITH|AQ-EUR-20260922")["investigation_group_id"], "")

    def test_default_rules_over_group_g18(self):
        g = groups_by_root(self.v0)
        self.assertEqual(g, [frozenset({"INTERNAL_DIFFERENCE|2026-09-17/GBP", "CBAL-ROLLFWD|GBP/C0004 2026-09-17",
                                        "CBAL-ROLLFWD|GBP/C0007 2026-09-17"})])

    def test_l3b_rejected_for_the_transaction_explained_roll_forward(self):
        internal, c0007 = eid(self.v, "INTERNAL_DIFFERENCE|2026-09-17/GBP"), eid(self.v, "CBAL-ROLLFWD|GBP/C0007 2026-09-17")
        (r,) = rels(self.v, "L3 LINEAGE (b)", "REJECTED")
        self.assertEqual(r["exception_ids"], sorted([internal, c0007]))
        (s,) = rels(self.v, "L7 SNAPSHOT LINEAGE")
        self.assertEqual(s["strength"], "CONFIRMED")

    def test_same_date_same_amount_coincidences_are_rejected(self):
        ids = {x["root_cause"]: x["exception_id"] for x in self.v.exceptions}
        pairs = {tuple(r["exception_ids"]) for r in self.v.enrichment["rejected_coincidences"]}
        expect = {tuple(sorted([ids[a], ids[b]])) for a in ("INTERNAL_DIFFERENCE|2026-09-17/GBP", "CBAL-ROLLFWD|GBP/C0004 2026-09-17")
                  for b in ("RC4-DIRECT|TX-0917-00002", "CBAL-ROLLFWD|GBP/C0007 2026-09-17")}
        self.assertEqual(pairs, expect)
        for r in self.v.enrichment["rejected_coincidences"]:
            self.assertEqual((r["date"], r["currency"], r["amount"], r["strength"]), ("2026-09-17", "GBP", "90.00", "REJECTED"))

    def test_outlier_sources_per_cause(self):
        rc4 = result(self.v, "RC4-DIRECT", "TX-0917-00002")["structured"]["comparison"]
        self.assertEqual((rc4["difference"], rc4["outlier"]["source"]), ("90.00", "IN-11"))
        (m,) = result(self.v, "C11-BATCH-ARITH", "AQ-EUR-20260922")["structured"]["line_comparison"]["line_mismatches"]
        self.assertEqual((m["difference"], m["outlier"]["source"]), ("-45.00", "IN-13"))

    def test_sc5c_and_sc5d_keep_their_groups_and_answer_keys(self):
        for name in ("scn_SC5C_refund_double_posted", "scn_SC5D_closing_snapshot_mismatch"):
            root = copy_case(DATASETS / name, f"f_{name}")
            v = run(root)
            matched, diffs = V.compare_answer_key(root, v.results, v.exceptions, v.candidates)
            self.assertTrue(matched, (name, diffs))
            self.assertEqual(len(v.groups), 1, name)
            self.assertFalse(rels(v, "L3 LINEAGE (b)"), name)  # no rejection or candidate: the snapshot error reconciles


# --- G-15 unmatched credit -------------------------------------------------------------------------------------------------
class G15_UnmatchedCredit(unittest.TestCase):
    def test_unmatched_credit_flags_potential_requirement_understatement(self):
        v = run(mutated("g_tc04", tc04_ops()))
        (x,) = exc_by_root(v, "UNMATCHED_BANK_ENTRY|BE-EUR-0930-U01")
        self.assertIn("POTENTIAL_UNRECORDED_RECEIPT", x["flags"])
        self.assertIn("650.00 EUR", x["flags"])
        (u,) = v.enrichment["unmatched_credits"]
        self.assertEqual((u["exception_id"], u["potential_requirement_understatement"], u["classification"]),
                         (x["exception_id"], "650.00", "POTENTIAL_UNIDENTIFIED_RECEIPT"))
        self.assertEqual(len(v.groups), 1)  # the existing L3 group is kept
        v0 = run(mutated("g_tc04_0", tc04_ops()), APPROVED_RULES)
        self.assertNotIn("POTENTIAL_UNRECORDED_RECEIPT", exc_by_root(v0, "UNMATCHED_BANK_ENTRY|")[0]["flags"])

    def test_unmatched_debit_is_not_a_receipt(self):
        v = run(copy_case(DATASETS / "scn_S05_unexplained_gbp_difference", "g_s05"))
        self.assertEqual(v.enrichment["unmatched_credits"], [])
        self.assertTrue(all("POTENTIAL_UNRECORDED_RECEIPT" not in x["flags"] for x in v.exceptions))


# --- regression and compatibility -------------------------------------------------------------------------------------------
class R_Compatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for name in FROZEN:
            root = copy_case(DATASETS / name, f"r_{name}")
            cls.runs[name] = (root, run(root, None), run(root, APPROVED_RULES), run(root, ENRICHED_RULES))

    @staticmethod
    def snapshot(v):
        return (json.dumps(v.results, sort_keys=True, default=str), json.dumps(v.exceptions, sort_keys=True),
                json.dumps(v.groups, sort_keys=True), json.dumps(v.candidates, sort_keys=True))

    def test_default_rules_identical_and_no_enrichment_state(self):
        for name, (_, none, approved, _) in self.runs.items():
            self.assertEqual(self.snapshot(none), self.snapshot(approved), name)
            self.assertIsNone(none.enrichment, name)

    def test_answer_keys_match_in_both_modes(self):
        for name, (root, _, approved, enriched) in self.runs.items():
            for mode, v in (("default", approved), ("enriched", enriched)):
                matched, diffs = V.compare_answer_key(root, v.results, v.exceptions, v.candidates)
                if (root / "answer_key.json").exists():
                    self.assertTrue(matched, (name, mode, diffs))

    def test_enriched_mode_changes_no_outcome_in_frozen_datasets(self):
        key = lambda v: [(r["check_id"], r["scope"], r["outcome"], r["root_cause"]) for r in v.results]
        for name, (_, _, approved, enriched) in self.runs.items():
            self.assertEqual(key(approved), key(enriched), name)
            self.assertEqual([x["root_cause"] for x in approved.exceptions], [x["root_cause"] for x in enriched.exceptions], name)

    def test_rules_fingerprint_and_validation(self):
        self.assertEqual(EngineRules().recorded(), {"c06_c08_zero_difference": "PASS"})
        self.assertEqual(V.PUBLISHED_RULES_BEFORE_17_NOV_2026.recorded(), {})
        self.assertEqual(ENRICHED_RULES.recorded(), {"c06_c08_zero_difference": "PASS", "reconciliation_enrichment": "v1"})
        self.assertFalse(APPROVED_RULES.enrichment_v1)
        with self.assertRaises(TypeError):
            EngineRules(enrichment_v1="yes")

    def test_write_outputs_enrichment_file_only_when_given(self):
        root = copy_case(DATASETS / "scn_SC5A_missing_transaction", "r_write")
        v = run(root, APPROVED_RULES)
        V.write_outputs(root, v.results, v.exceptions, V.case_status(v), v.groups, v.candidates, v.pdf, v.period, v.rules)
        self.assertFalse((root / "validation" / "enrichment.json").exists())
        self.assertNotIn("Reconciliation enrichment", (root / "VALIDATION_REPORT.md").read_text(encoding="utf-8"))
        ve = run(root)
        V.write_outputs(root, ve.results, ve.exceptions, V.case_status(ve), ve.groups, ve.candidates, ve.pdf, ve.period, ve.rules,
                        enrichment_state=ve.enrichment)
        data = json.loads((root / "validation" / "enrichment.json").read_text(encoding="utf-8"))
        self.assertEqual((data["schema"], data["version"]), (enrichment.SCHEMA, enrichment.VERSION))
        self.assertIn("Reconciliation enrichment", (root / "VALIDATION_REPORT.md").read_text(encoding="utf-8"))

    def test_nothing_is_resolved_or_closed(self):
        for name, (_, _, _, v) in self.runs.items():
            self.assertTrue(all(x["status"] == "OPEN" and x["review_status"] == "AWAITING_HUMAN_REVIEW" for x in v.exceptions), name)
            self.assertTrue(all(g["cause"] == "" and g["status"] == "OPEN" for g in v.groups), name)


# --- integration: the TC01-TC06 dataset snapshot (read-only source, copied) ----------------------------------------------------
@unittest.skipUnless(TC_SNAPSHOT.is_dir(), "TC dataset snapshot not present")
class T_TestSuiteV2Snapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {}
        for d in sorted(TC_SNAPSHOT.glob("TC0*")):
            root = copy_case(d / "initial_submission", f"t_{d.name}")
            pred = json.loads((d / "expected_results" / "engine_predicted_initial.json").read_text(encoding="utf-8"))
            cls.cases[d.name[:4]] = (root, pred, run(root, APPROVED_RULES), run(root))

    def test_default_mode_matches_engine_predictions(self):
        for tc, (_, pred, v, _) in self.cases.items():
            got = [{k: x[k] for k in ("exception_id", "severity", "root_cause", "affected_results")} for x in v.exceptions]
            self.assertEqual(got, pred["exceptions"], tc)
            self.assertEqual(sorted([r["check_id"], r["scope"], r["outcome"]] for r in v.results if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE")),
                             sorted(pred["non_passing_results"]), tc)

    def test_enriched_key_outcomes(self):
        c = self.cases
        v = c["TC01"][3]
        self.assertEqual(len(v.exceptions), 11)
        self.assertEqual(len(v.groups), 1)
        self.assertEqual(v.groups[0]["size"], 11)
        v = c["TC02"][3]
        self.assertEqual(len(v.groups), 1)
        self.assertEqual(result(v, "RC4-DIRECT", "TX-0908-00002")["structured"]["comparison"]["outlier"]["source"], "IN-11")
        v = c["TC03"][3]
        (t,) = v.enrichment["timing_traces"]
        self.assertEqual((t["evidence_class"], t["resolves_exception"]), ("EVIDENCED", False))
        self.assertEqual(t["items"][0]["batch"]["batch_id"], "AQ-GBP-20260925")
        v = c["TC04"][3]
        self.assertEqual(len(v.enrichment["unmatched_credits"]), 1)
        v = c["TC05"][3]
        self.assertEqual(v.enrichment["common_causes"][0]["status"], "SUSPECTED")
        self.assertEqual(len(v.candidates), 2)
        v = c["TC06"][3]
        self.assertEqual(sorted(g["exception_ids"] for g in v.groups), ["EXC-TC06-01; EXC-TC06-03; EXC-TC06-04", "EXC-TC06-05; EXC-TC06-06"])
        self.assertEqual(len(v.enrichment["rejected_coincidences"]), 4)


if __name__ == "__main__":
    unittest.main()
