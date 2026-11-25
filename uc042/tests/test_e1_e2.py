"""E1 (timing evidence) and E2 (investigation groups). Run from the uc042/ folder:  python -m unittest -v

Edge cases use temporary copies; committed datasets are never modified.
"""
import csv
import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from uc042lib import schema
from uc042lib.validate import DEFAULT_SET, Validator

DATASETS = DEFAULT_SET.parent
SC2 = DATASETS / "scn_SC2_settlement_timing"
ALL = ["set_01_clean_baseline", "scn_SC2_settlement_timing", "scn_SC3B_fee_not_itemised", "scn_SC3C_short_settlement",
       "scn_S02_missing_eur_statement", "scn_SC5A_missing_transaction", "scn_SC5C_refund_double_posted",
       "scn_SC5D_closing_snapshot_mismatch", "scn_S05_unexplained_gbp_difference"]


def run(root):
    v = Validator(root)
    v.run()
    return v


def rows(root, fid):
    with open(Path(root) / "source_data" / schema.CSV_FILES[fid][0], encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(root, fid, data):
    with open(Path(root) / "source_data" / schema.CSV_FILES[fid][0], "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def edit(root, fid, key, **values):
    pk = schema.columns(fid)[0]
    data = rows(root, fid)
    hit = [r for r in data if r[pk] == key]
    assert len(hit) == 1, (fid, key)
    hit[0].update(values)
    write(root, fid, data)


def c08(v, scope):
    return next(r for r in v.results if r["check_id"] == "C08-DIFFERENCE" and r["scope"] == scope)


class Copy(unittest.TestCase):
    source = SC2

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "c"
        shutil.copytree(self.source, self.root)
        for n in ("manifest.csv", "answer_key.json"):
            (self.root / n).unlink()

    def tearDown(self):
        shutil.rmtree(self.tmp)


class E1TimingEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = {n: run(DATASETS / n) for n in ALL}

    def test_e1_1_sc2_evidenced_but_open(self):
        r = c08(self.v["scn_SC2_settlement_timing"], "2026-09-15/SGA-GBP-01")
        self.assertEqual((r["outcome"], r["computed"], r["evidence_status"]), ("FAIL", "2868.50", "TIMING_EVIDENCED"))
        self.assertIn("LE-GBP-0915-0005 / BE-GBP-0916-T01", r["note"])
        self.assertIn("sga_cashbook_entries_2026-09.csv#L", r["evidence"])
        self.assertIn("bank_statement_entries_2026-09.csv#L", r["evidence"])
        x = self.v["scn_SC2_settlement_timing"].exceptions[0]
        self.assertEqual((x["status"], x["evidence_status"], x["review_status"], x["cause_category"]),
                         ("OPEN", "TIMING_EVIDENCED", "AWAITING_HUMAN_REVIEW", ""))

    def test_e1_2_short_settlement_and_812_40_remain_unexplained(self):
        for name, amount in (("scn_SC3C_short_settlement", "-4.50"), ("scn_S05_unexplained_gbp_difference", "-812.40")):
            fails = [r for r in self.v[name].results if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] == "FAIL"]
            self.assertTrue(fails)
            self.assertTrue(all(r["evidence_status"] == "NOT_EVIDENCED" and r["computed"] == amount for r in fails), name)
            self.assertTrue(all(r["note"].startswith("unexplained bank-ledger difference") for r in fails), name)

    def test_e1_9_nothing_is_resolved_or_closed(self):
        for name, v in self.v.items():
            self.assertTrue(all(x["status"] == "OPEN" and x["cause_category"] == "" for x in v.exceptions), name)
            self.assertFalse([r for r in v.results if r["check_id"] == "C08-DIFFERENCE" and r["evidence_status"] and r["outcome"] != "FAIL"])

    def test_e1_10_batch_lag_is_informational(self):
        r = next(r for r in self.v["scn_SC2_settlement_timing"].results if r["check_id"] == "C11-BATCH-BANK" and r["scope"] == "SB-GBP-20260915")
        self.assertEqual(r["outcome"], "PASS")
        self.assertIn("1 business day(s) after the settlement date (within the one-business-day allowance; informational)", r["note"])

    def test_e1_12_timing_items_only_where_the_scenario_put_them(self):
        from datetime import date
        for name, v in self.v.items():
            items = [(r["scope"], i["bank_row"]["bank_entry_id"] if i["bank_row"] else None)
                     for r in v.results if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] == "FAIL"
                     for i in v.timing_items(r["scope"].split("/")[1], date.fromisoformat(r["scope"].split("/")[0]))]
            self.assertEqual(items, [("2026-09-15/SGA-GBP-01", "BE-GBP-0916-T01")] if name == "scn_SC2_settlement_timing" else [], name)

    def test_e1_11_baseline_has_no_timing_items(self):
        v = self.v["set_01_clean_baseline"]
        self.assertFalse([r for r in v.results if r["evidence_status"]])
        self.assertFalse([r for r in v.results if r["check_id"] == "C11-BATCH-BANK" and "booked" in r["note"]])


class E1EdgeCases(Copy):
    def test_e1_3_clearing_two_business_days_later_is_not_evidence(self):
        edit(self.root, "IN-09", "BE-GBP-0916-T01", statement_id="ST-SGA-GBP-01-20260917-EOD", booking_date="2026-09-17",
             booking_ts="2026-09-17T08:00:00+01:00", value_date="2026-09-17")
        r = c08(run(self.root), "2026-09-15/SGA-GBP-01")
        self.assertEqual((r["outcome"], r["evidence_status"]), ("FAIL", "NOT_EVIDENCED"))
        self.assertIn("later than one business day", r["note"])

    def test_e1_4_different_amount_is_not_evidence(self):
        edit(self.root, "IN-09", "BE-GBP-0916-T01", amount="2868.00")
        self.assertEqual(c08(run(self.root), "2026-09-15/SGA-GBP-01")["evidence_status"], "NOT_EVIDENCED")

    def test_e1_5_same_amount_different_reference_is_not_evidence(self):
        edit(self.root, "IN-09", "BE-GBP-0916-T01", bank_reference="OTHER-REF-0916")
        self.assertEqual(c08(run(self.root), "2026-09-15/SGA-GBP-01")["evidence_status"], "NOT_EVIDENCED")

    def test_e1_6_partial_explanation_reports_residual(self):
        cash = rows(self.root, "IN-10")
        cash.append({"ledger_entry_id": "LE-GBP-0915-9001", "account_id": "SGA-GBP-01", "posted_ts": "2026-09-15T16:00:00+01:00",
                     "entry_type": "REDEMPTION", "amount": "100.00", "dc_indicator": "C", "currency": "GBP", "payment_reference": "TEST-PARTIAL"})
        write(self.root, "IN-10", cash)
        r = c08(run(self.root), "2026-09-15/SGA-GBP-01")
        self.assertEqual((r["outcome"], r["computed"], r["evidence_status"]), ("FAIL", "2968.50", "TIMING_PARTIAL"))
        self.assertIn("residual 100.00 unexplained", r["note"])

    def test_e1_7_missing_clearing_evidence_is_unverifiable(self):
        write(self.root, "IN-09", [e for e in rows(self.root, "IN-09") if e["statement_id"] != "ST-SGA-GBP-01-20260916-EOD"])
        write(self.root, "IN-08", [s for s in rows(self.root, "IN-08") if s["statement_id"] != "ST-SGA-GBP-01-20260916-EOD"])
        write(self.root, "IN-07", [b for b in rows(self.root, "IN-07") if b["statement_id"] != "ST-SGA-GBP-01-20260916-1700"])
        r = c08(run(self.root), "2026-09-15/SGA-GBP-01")
        self.assertEqual((r["outcome"], r["evidence_status"]), ("FAIL", "TIMING_UNVERIFIABLE"))


class E1PeriodEnd(Copy):
    source = DEFAULT_SET

    def test_e1_8_posting_on_30_september_is_unverifiable(self):
        cash = rows(self.root, "IN-10")
        cash.append({"ledger_entry_id": "LE-GBP-0930-9001", "account_id": "SGA-GBP-01", "posted_ts": "2026-09-30T16:30:00+01:00",
                     "entry_type": "REDEMPTION", "amount": "50.00", "dc_indicator": "C", "currency": "GBP", "payment_reference": "LATE-0930"})
        write(self.root, "IN-10", cash)
        r = c08(run(self.root), "2026-09-30/SGA-GBP-01")
        self.assertEqual((r["outcome"], r["computed"], r["evidence_status"]), ("FAIL", "50.00", "TIMING_UNVERIFIABLE"))


class E1AdditionalCases(Copy):
    """Cases added by the verification brief: account, currency, missing entry, ambiguity, same date, weekend boundary."""

    def status(self, scope="2026-09-15/SGA-GBP-01"):
        return c08(run(self.root), scope)["evidence_status"]

    def test_incorrect_account_is_not_evidence(self):
        edit(self.root, "IN-09", "BE-GBP-0916-T01", account_id="SGA-EUR-01", statement_id="ST-SGA-EUR-01-20260916-EOD")
        self.assertEqual(self.status(), "NOT_EVIDENCED")

    def test_incorrect_currency_is_not_evidence(self):
        edit(self.root, "IN-09", "BE-GBP-0916-T01", currency="EUR")
        self.assertEqual(self.status(), "NOT_EVIDENCED")

    def test_missing_bank_entry_with_evidence_present_is_not_evidence(self):
        write(self.root, "IN-09", [e for e in rows(self.root, "IN-09") if e["bank_entry_id"] != "BE-GBP-0916-T01"])
        self.assertEqual(self.status(), "NOT_EVIDENCED")  # 16 Sep statement exists, so this is not 'unverifiable'

    def test_multiple_possible_matches_are_not_evidence(self):
        data = rows(self.root, "IN-09")
        t01 = next(e for e in data if e["bank_entry_id"] == "BE-GBP-0916-T01")
        data.append(dict(t01, bank_entry_id="BE-GBP-0916-T02", booking_ts="2026-09-16T09:00:00+01:00"))
        write(self.root, "IN-09", data)
        self.assertEqual(self.status(), "NOT_EVIDENCED")  # ambiguous reference: no single clearing entry


class E1SameDateAndWeekend(Copy):
    source = DEFAULT_SET

    def move_friday_settlement(self, booking_date):
        """Bank books Friday 11 Sep scheme settlement SB-GBP-20260911 on a later day; 11 Sep balances adjusted consistently."""
        e = next(x for x in rows(self.root, "IN-09") if x["bank_entry_id"] == "BE-GBP-0911-SB1")
        amt = Decimal(e["amount"])
        edit(self.root, "IN-09", "BE-GBP-0911-SB1", statement_id=f"ST-SGA-GBP-01-{booking_date.replace('-', '')}-EOD",
             booking_date=booking_date, booking_ts=f"{booking_date}T08:00:00+01:00", value_date=booking_date)
        bc = next(x for x in rows(self.root, "IN-07") if x["statement_id"] == "ST-SGA-GBP-01-20260911-1700")
        edit(self.root, "IN-07", bc["statement_id"], balance_amount=f"{Decimal(bc['balance_amount']) + amt:.2f}")
        er = next(x for x in rows(self.root, "IN-06") if x["ext_recon_id"] == "ERL-SGA-GBP-01-20260911")
        edit(self.root, "IN-06", er["ext_recon_id"], bank_balance_reported=f"{Decimal(er['bank_balance_reported']) + amt:.2f}",
             difference_reported=f"{amt:.2f}")
        return amt

    def test_same_date_match_is_not_a_timing_item(self):
        v = run(self.root)
        from datetime import date
        self.assertEqual(v.timing_items("SGA-GBP-01", date(2026, 9, 15)), [])
        self.assertFalse([r for r in v.results if r["evidence_status"]])

    def test_friday_settlement_cleared_monday_is_within_one_business_day(self):
        amt = self.move_friday_settlement("2026-09-14")
        r = c08(run(self.root), "2026-09-11/SGA-GBP-01")
        self.assertEqual((r["outcome"], r["computed"], r["evidence_status"]), ("FAIL", f"{amt:.2f}", "TIMING_EVIDENCED"))

    def test_friday_settlement_cleared_tuesday_is_outside_the_allowance(self):
        self.move_friday_settlement("2026-09-15")
        self.assertEqual(c08(run(self.root), "2026-09-11/SGA-GBP-01")["evidence_status"], "NOT_EVIDENCED")

    def test_business_day_helper_boundaries(self):
        from datetime import date
        from uc042lib.validate import business_day_after
        self.assertEqual(business_day_after(date(2026, 9, 11)), date(2026, 9, 14))   # Fri -> Mon
        self.assertEqual(business_day_after(date(2026, 8, 28)), date(2026, 9, 1))    # Fri -> Tue (31 Aug bank holiday)
        self.assertEqual(business_day_after(date(2026, 9, 30)), date(2026, 10, 1))   # outside the period: unverifiable path


class E2InvestigationGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = {n: run(DATASETS / n) for n in ALL}

    def groups(self, name):
        return {g["group_id"]: g for g in self.v[name].groups}

    def test_e2_1_short_settlement_group(self):
        g = self.groups("scn_SC3C_short_settlement")
        self.assertEqual(list(g), ["GRP-SC3C-01"])
        self.assertEqual(g["GRP-SC3C-01"]["exception_ids"], "EXC-SC3C-01; EXC-SC3C-02; EXC-SC3C-03")
        self.assertEqual(g["GRP-SC3C-01"]["link_types"], "L1 REFERENCE; L3 LINEAGE")
        self.assertIn("reference AQ-GBP-20260908", g["GRP-SC3C-01"]["links"])
        self.assertIn("BE-GBP-0908-AQ1 is inside the 2026-09-08 17:00 balance", g["GRP-SC3C-01"]["links"])

    def test_e2_2_refund_twice_group(self):
        g = self.groups("scn_SC5C_refund_double_posted")["GRP-SC5C-01"]
        self.assertEqual((g["size"], g["link_types"]), (17, "L2 PERSISTENCE; L3 LINEAGE"))
        self.assertIn("snapshot of C0002 on 2026-09-09", g["links"])

    def test_e2_3_closing_snapshot_group(self):
        g = self.groups("scn_SC5D_closing_snapshot_mismatch")["GRP-SC5D-01"]
        self.assertEqual((g["size"], g["link_types"]), (3, "L3 LINEAGE"))

    def test_e2_4_missing_transaction_has_no_confirmed_group(self):
        v = self.v["scn_SC5A_missing_transaction"]
        self.assertEqual(v.groups, [])
        self.assertTrue(all(x["investigation_group_id"] == "" for x in v.exceptions))
        self.assertEqual(len(v.candidates), 1)
        c = v.candidates[0]
        self.assertEqual((c["exception_ids"], c["basis"]), ("EXC-SC5A-01; EXC-SC5A-02", "DATE_AND_AMOUNT_COINCIDENCE"))
        self.assertIn("UNVERIFIED", c["label"])
        self.assertIn("NOT EVIDENCE-BACKED", c["label"])

    def test_e2_5_812_40_group_remains_unresolved(self):
        g = self.groups("scn_S05_unexplained_gbp_difference")["GRP-S05-01"]
        self.assertEqual((g["size"], g["link_types"], g["status"], g["cause"]), (2, "L3 LINEAGE", "OPEN", ""))

    def test_e2_6_no_groups_where_nothing_to_link(self):
        for name in ("set_01_clean_baseline", "scn_S02_missing_eur_statement", "scn_SC2_settlement_timing", "scn_SC3B_fee_not_itemised"):
            self.assertEqual(self.v[name].groups, [], name)
            self.assertEqual(self.v[name].candidates, [], name)

    def test_e2_7_individual_exceptions_preserved(self):
        golden = Path(__file__).parent / "golden"
        for name, v in self.v.items():
            g = json.loads((golden / f"{name}.json").read_text())
            self.assertEqual([[x["exception_id"], x["severity"], x["root_cause"], str(x["affected_results"]), x["flags"]]
                              for x in v.exceptions], g["exceptions"], name)

    def test_e2_8_groups_never_set_cause_or_close(self):
        for name, v in self.v.items():
            for g in v.groups:
                self.assertEqual((g["status"], g["review_status"], g["cause"]), ("OPEN", "AWAITING_HUMAN_REVIEW", ""), name)
                self.assertRegex(g["links"], r"IN-\d\d:[^#\]]+#L\d+")

    def test_e2_11_deterministic(self):
        for name in ("scn_SC3C_short_settlement", "scn_SC5C_refund_double_posted"):
            again = run(DATASETS / name)
            self.assertEqual(again.groups, self.v[name].groups)
            self.assertEqual([x["investigation_group_id"] for x in again.exceptions],
                             [x["investigation_group_id"] for x in self.v[name].exceptions])

    def test_e2_12_cited_link_rows_carry_the_claimed_reference(self):
        g = self.groups("scn_SC3C_short_settlement")["GRP-SC3C-01"]
        l1 = next(part for part in g["links"].split(" | ") if "L1 REFERENCE" in part)
        for cite in l1.split("[")[1].rstrip("]").split(", "):
            fname, line = cite.split(":", 1)[1].split("#L")
            with open(DATASETS / "scn_SC3C_short_settlement" / "source_data" / fname, encoding="utf-8") as f:
                self.assertIn("AQ-GBP-20260908", f.read().splitlines()[int(line) - 1])


class E2Negative(Copy):
    source = DEFAULT_SET

    def test_e2_9_same_day_on_two_accounts_not_grouped(self):
        edit(self.root, "IN-09", "BE-GBP-0908-AQ1", amount="9950.00")
        eur = next(e for e in rows(self.root, "IN-09") if e["bank_reference"] == "AQ-EUR-20260908")
        edit(self.root, "IN-09", eur["bank_entry_id"], amount=f"{Decimal(eur['amount']) - 1:.2f}")
        v = run(self.root)
        acct = {x["exception_id"]: x["account_id"] or x["root_cause"] for x in v.exceptions}
        for g in v.groups:
            members = g["exception_ids"].split("; ")
            text = " ".join(next(x["evidence"] for x in v.exceptions if x["exception_id"] == m) for m in members)
            self.assertFalse("GBP" in text and "EUR" in text, (g, acct))

    def test_e2_10_equal_amounts_without_reference_or_lineage_not_grouped(self):
        edit(self.root, "IN-03", "CBS-20260910-C0001-GBP",
             balance=f"{Decimal(next(r for r in rows(self.root, 'IN-03') if r['snapshot_id'] == 'CBS-20260910-C0001-GBP')['balance']) + 100:.2f}")
        edit(self.root, "IN-05", "IRR-EMONEY-GBP-20260910",
             requirement_reported=f"{Decimal(next(r for r in rows(self.root, 'IN-05') if r['recon_run_id'] == 'IRR-EMONEY-GBP-20260910')['requirement_reported']) + 100:.2f}",
             difference_reported="-100.00")
        v = run(self.root)
        cbal = [x for x in v.exceptions if x["root_cause"].startswith("CBAL-ROLLFWD")]
        self.assertEqual(len(cbal), 2)  # 9->10 and 10->11 Sep, both 100.00
        self.assertNotEqual(cbal[0]["investigation_group_id"] or "a", cbal[1]["investigation_group_id"] or "b",
                            "two roll-forward breaks of equal amount must not be grouped with each other on amount alone")


if __name__ == "__main__":
    unittest.main()
