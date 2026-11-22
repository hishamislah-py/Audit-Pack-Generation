"""Period-configurable engine (uc042lib.period): period values, calendars, Europe/London offsets, bank holidays, file
names, period rules, case-period resolution, wrong-period and mixed-period files, document applicability, period-specific
pack identifiers, sequence independence and financial continuity.

The fixtures here are synthetic CONFIGURATION fixtures built inside the tests (calendars generated from the period
itself, a few hand-written rows for the continuity comparison). They are not monthly datasets and produce no
reconciliation results for any real month. September 2026 is checked against the existing baseline. Offline."""
import copy
import csv
import shutil
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from uc042lib import schema
from uc042lib.continuity import compare
from uc042lib.pack.generate import build
from uc042lib.period import (BASELINE, LONDON, PeriodConfig, PeriodError, bank_holidays, business_day_after, london_offset,
                             resolve)
from uc042lib.structure import check_period
from uc042lib.validate import DEFAULT_SET, Validator

DATASETS = DEFAULT_SET.parent
DAYS_2026 = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30}


def write_csv(path, fid, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = schema.columns(fid)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def calendar_rows(period, basis="SYNTHETIC TEST FIXTURE"):
    return [{"calendar_date": d.isoformat(), "period_id": period.period_id, "is_recon_day": "true" if bd else "false",
             "non_recon_reason": reason, "calendar_basis": basis} for d, bd, reason in period.expected_calendar()]


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def case(self, period, name="case"):
        d = self.tmp / name
        write_csv(d / "source_data" / period.filename("IN-01"), "IN-01", calendar_rows(period))
        return d


class PeriodValues(unittest.TestCase):
    def test_january_to_november_2026(self):
        for month, days in DAYS_2026.items():
            p = PeriodConfig(2026, month)
            self.assertEqual(p.period_id, f"PER-2026-{month:02d}")
            self.assertEqual((p.start, p.end.day, p.days, len(p.dates())), (date(2026, month, 1), days, days, days))
            self.assertEqual(PeriodConfig.from_id(p.period_id), p)
            self.assertEqual(p.filename("IN-01"), f"recon_calendar_2026-{month:02d}.csv")
            self.assertEqual(p.filename("IN-19"), f"rep027_submission_receipt_{p.previous.token}.pdf")
            self.assertEqual(p.previous_end, p.start.fromordinal(p.start.toordinal() - 1))
        self.assertEqual(PeriodConfig(2026, 1).previous.period_id, "PER-2025-12")
        self.assertEqual(PeriodConfig(2026, 1).filename("IN-19"), "rep027_submission_receipt_2025-12.pdf")
        self.assertEqual(PeriodConfig(2026, 12).next.period_id, "PER-2027-01")

    def test_invalid_periods(self):
        for bad in ("PER-2026-13", "PER-2026-00", "PER-26-01", "2026-09", "", None, "PER-1999-12"):
            with self.assertRaises(PeriodError, msg=bad):
                PeriodConfig.from_id(bad)
        for y, m in ((2026, 0), (2026, 13), (1999, 5), ("2026", 9)):
            with self.assertRaises(PeriodError):
                PeriodConfig(y, m)

    def test_leap_years(self):
        self.assertEqual(PeriodConfig(2028, 2).days, 29)
        self.assertEqual(PeriodConfig(2026, 2).days, 28)
        self.assertEqual(PeriodConfig(2100, 2).days, 28)  # century rule
        self.assertEqual(PeriodConfig(2028, 3).previous_end, date(2028, 2, 29))

    def test_immutable_and_hashable(self):
        p = PeriodConfig(2026, 9)
        with self.assertRaises(Exception):
            p.month = 10
        self.assertEqual(len({PeriodConfig(2026, 9), BASELINE, PeriodConfig.from_id("PER-2026-09")}), 1)

    def test_baseline_matches_the_existing_contract_exactly(self):
        sep = PeriodConfig(2026, 9)
        self.assertEqual(sep.period_id, schema.PERIOD_ID)
        self.assertEqual((sep.start, sep.end), (schema.PERIOD_START, schema.PERIOD_END))
        self.assertEqual(sep.csv_files, schema.CSV_FILES)
        self.assertEqual(sep.pdf_files, schema.PDF_FILES)
        self.assertEqual(sep.period_rules, schema.PERIOD_RULES)


class CalendarAndTimezone(unittest.TestCase):
    def test_bank_holidays_england_and_wales(self):
        self.assertEqual(sorted(bank_holidays(2026)), [date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4),
                                                       date(2026, 5, 25), date(2026, 8, 31), date(2026, 12, 25), date(2026, 12, 28)])
        self.assertEqual(sorted(bank_holidays(2027)), [date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29), date(2027, 5, 3),
                                                       date(2027, 5, 31), date(2027, 8, 30), date(2027, 12, 27), date(2027, 12, 28)])
        self.assertIn(date(2022, 12, 27), bank_holidays(2022))  # Christmas on a Sunday: substitute Tuesday
        self.assertIn(date(2023, 1, 2), bank_holidays(2023))    # New Year's Day on a Sunday

    def test_business_days_across_holidays(self):
        self.assertEqual(business_day_after(date(2026, 4, 2)), date(2026, 4, 7))     # Good Friday and Easter Monday
        self.assertEqual(business_day_after(date(2026, 8, 28)), date(2026, 9, 1))    # summer bank holiday
        self.assertEqual(business_day_after(date(2026, 12, 24)), date(2026, 12, 29))
        self.assertEqual(business_day_after(date(2026, 8, 31), 15), date(2026, 9, 21))

    def test_reconciliation_days_per_month(self):
        expected = {1: 21, 2: 20, 3: 22, 4: 20, 5: 19, 6: 22, 7: 23, 8: 20, 9: 22, 10: 22, 11: 21}
        for month, n in expected.items():
            cal = PeriodConfig(2026, month).expected_calendar()
            self.assertEqual(sum(1 for _, bd, _ in cal if bd), n, month)
        reasons = {d: r for d, _, r in PeriodConfig(2026, 4).expected_calendar()}
        self.assertEqual((reasons[date(2026, 4, 3)], reasons[date(2026, 4, 4)]), ("UK_BANK_HOLIDAY", "WEEKEND"))

    def test_daylight_saving_offsets_are_not_hardcoded(self):
        self.assertEqual(london_offset(date(2026, 3, 29), time(0, 30)), "+00:00")   # before the 01:00 UTC change
        self.assertEqual(london_offset(date(2026, 3, 29), time(2, 30)), "+01:00")
        self.assertEqual(london_offset(date(2026, 10, 25), time(0, 30)), "+01:00")
        self.assertEqual(london_offset(date(2026, 10, 25), time(17, 0)), "+00:00")
        boundary = {m: PeriodConfig(2026, m).opening_point_iso() for m in (1, 3, 4, 10, 11)}
        self.assertEqual(boundary, {1: "2025-12-31T17:00:00+00:00", 3: "2026-02-28T17:00:00+00:00", 4: "2026-03-31T17:00:00+01:00",
                                    10: "2026-09-30T17:00:00+01:00", 11: "2026-10-31T17:00:00+00:00"})
        self.assertEqual(PeriodConfig(2026, 9).opening_point_iso(), "2026-08-31T17:00:00+01:00")  # unchanged baseline
        self.assertEqual(PeriodConfig(2026, 11).opening_point(), datetime(2026, 10, 31, 17, 0, tzinfo=LONDON))

    def test_september_calendar_matches_the_supplied_calendar(self):
        with open(DEFAULT_SET / "source_data" / "recon_calendar_2026-09.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([x for x in PeriodConfig(2026, 9).calendar_findings(rows) if x[0] != "INFO"], [])

    def test_calendar_findings(self):
        p = PeriodConfig(2026, 4)
        rows = calendar_rows(p)
        rows = [r for r in rows if r["calendar_date"] != "2026-04-15"] + [dict(rows[0])]
        rows[2]["is_recon_day"], rows[2]["non_recon_reason"] = "false", "FOREIGN_MARKET_CLOSED"  # 3 Apr is Good Friday
        sat = next(r for r in rows if r["calendar_date"] == "2026-04-04")
        sat["is_recon_day"], sat["non_recon_reason"] = "true", ""
        codes = {c for _, c, _ in p.calendar_findings(rows + [{"calendar_date": "2026-05-01", "is_recon_day": "true"}])}
        self.assertEqual(codes, {"MISSING_DATE", "DUPLICATE_DATE", "RECON_ON_NON_BUSINESS_DAY", "OUTSIDE_PERIOD"})


class UploadCalendarCheck(Tmp):
    def test_supplied_calendar_is_compared_with_the_month(self):
        from uc042app.ingest.analysis import analyse_file
        p = PeriodConfig(2026, 8)
        rows = calendar_rows(p)
        hol = next(r for r in rows if r["calendar_date"] == "2026-08-31")       # summer bank holiday marked as a recon day
        hol["is_recon_day"], hol["non_recon_reason"] = "true", ""
        f = self.tmp / "cal.csv"
        write_csv(f, "IN-01", [r for r in rows if r["calendar_date"] != "2026-08-14"])
        a = analyse_file(f, "cal.csv", 2026, 8)
        codes = {m["code"]: m["level"] for m in a["checks"]["messages"]}
        self.assertEqual(codes.get("CALENDAR_RECON_ON_NON_BUSINESS_DAY"), "WARNING")
        self.assertEqual(codes.get("CALENDAR_MISSING_DATE"), "WARNING")
        self.assertNotIn("WRONG_PERIOD", codes)
        september = {m["code"] for m in analyse_file(f, "cal.csv", 2026, 9)["checks"]["messages"]}
        self.assertIn("WRONG_PERIOD", september)  # an August calendar is never accepted for September


class PeriodRules(unittest.TestCase):
    def test_boundary_records_follow_the_period_and_its_offset(self):
        feb28 = PeriodConfig(2028, 2)
        opening = {"ledger_entry_id": "L1", "account_id": "A", "posted_ts": "2028-01-31T17:00:00+00:00", "entry_type": "OPENING_BALANCE",
                   "amount": "1.00", "dc_indicator": "D", "currency": "GBP", "payment_reference": "OPENING", "_line": 2}
        wrong_offset = dict(opening, posted_ts="2028-01-31T17:00:00+01:00", _line=3)   # a different instant: not the point
        leap_day = dict(opening, entry_type="BANK_LOAD", posted_ts="2028-02-29T10:00:00+00:00", _line=4)
        march = dict(leap_day, posted_ts="2028-03-01T00:30:00+00:00", _line=5)
        kept, findings, counts = check_period("IN-10", [opening, wrong_offset, leap_day, march], period=feb28)
        self.assertEqual([r["_line"] for r in kept], [2, 4])
        self.assertEqual(counts, {"applicable": 1, "permitted": 1, "outside": 2, "subsequent": 0})
        self.assertEqual(sorted(f["line"] for f in findings), [3, 5])
        # a September file judged as October: every row is outside
        with open(DEFAULT_SET / "source_data" / "bank_statement_entries_2026-09.csv", encoding="utf-8") as f:
            rows = [dict(r, _line=i) for i, r in enumerate(csv.DictReader(f), 2)]
        self.assertEqual(check_period("IN-09", rows, period=PeriodConfig(2026, 10))[2]["applicable"], 0)
        self.assertEqual(check_period("IN-09", rows, period=PeriodConfig(2026, 9))[2]["outside"], 0)

    def test_no_shared_mutable_period_state(self):
        before = copy.deepcopy(schema.PERIOD_RULES)
        a, b = PeriodConfig(2026, 2).period_rules, PeriodConfig(2026, 3).period_rules
        a["IN-01"]["equals"]["period_id"] = "TAMPERED"
        self.assertEqual(b["IN-01"]["equals"]["period_id"], "PER-2026-03")
        self.assertEqual(PeriodConfig(2026, 2).period_rules["IN-01"]["equals"]["period_id"], "PER-2026-02")
        self.assertEqual(schema.PERIOD_RULES, before)


class CaseResolution(Tmp):
    def test_period_is_resolved_from_the_case_never_defaulted(self):
        self.assertEqual(resolve(DEFAULT_SET), PeriodConfig(2026, 9))                      # manifest
        self.assertEqual(resolve(self.case(PeriodConfig(2026, 2))), PeriodConfig(2026, 2))  # file names
        empty = self.tmp / "empty"
        (empty / "source_data").mkdir(parents=True)
        with self.assertRaises(PeriodError):
            resolve(empty)
        self.assertEqual(resolve(empty, "PER-2026-05"), PeriodConfig(2026, 5))

    def test_conflicting_or_mixed_periods_are_refused(self):
        with self.assertRaises(PeriodError):
            resolve(DEFAULT_SET, PeriodConfig(2026, 10))
        with self.assertRaises(PeriodError):
            Validator(DEFAULT_SET, "PER-2026-10")
        mixed = self.case(PeriodConfig(2026, 2), "mixed")
        write_csv(mixed / "source_data" / PeriodConfig(2026, 3).filename("IN-05"), "IN-05", [])
        with self.assertRaises(PeriodError):
            resolve(mixed)

    def test_other_period_file_in_a_case_is_reported_and_not_used(self):
        p = PeriodConfig(2026, 2)
        d = self.case(p)
        shutil.copyfile(DEFAULT_SET / "source_data" / "transactions_2026-09.csv", d / "source_data" / "transactions_2026-09.csv")
        v = Validator(d, p)
        v.run()
        other = [r for r in v.results if r["check_id"] == "V00-FILE" and "another reporting period" in r["note"]]
        self.assertEqual([(r["scope"], r["outcome"]) for r in other], [("IN-11", "FAIL")])
        missing = next(r for r in v.results if r["check_id"] == "V00-FILE" and r["scope"] == "IN-11" and r["outcome"] != "FAIL")
        self.assertIn("transactions_2026-02.csv", missing["note"])  # September's file was not substituted
        self.assertNotIn("IN-11", v.data)


class ProcessingPeriods(Tmp):
    def test_validator_and_pack_for_a_non_september_period(self):
        p = PeriodConfig(2028, 2)
        d = self.case(p)
        v = Validator(d)
        v.run()
        self.assertEqual(v.period, p)
        self.assertEqual(len(v.recon_days), sum(1 for _, bd, _ in p.expected_calendar() if bd))
        self.assertIn(date(2028, 2, 29), v.recon_days)
        self.assertFalse([r for r in v.results if r["check_id"] == "DQ-PERIOD"])
        notes = " ".join(r["note"] for r in v.results if r["check_id"] == "V00-FILE")
        self.assertIn("transactions_2028-02.csv", notes)
        self.assertIn("rep027_submission_receipt_2028-01.pdf", notes)
        self.assertNotIn("2026-09", notes)
        # Pack assembly carries the period; with only a calendar, generation fails pack validation exactly as it does
        # for September in the same situation (missing evidence is never filled in).
        from uc042lib.pack.assemble import assemble, finalise, processing_outputs
        from uc042lib.prepare import prepare_case
        case = self.tmp / "prepared"
        prepare_case(d / "source_data", case, p)
        pack, v2 = assemble(case, period=p)
        pack = finalise(pack, processing_outputs(v2))
        self.assertEqual(pack["metadata"]["reporting_period"], {"period_id": "PER-2028-02", "start": "2028-02-01", "end": "2028-02-29"})
        self.assertTrue(pack["metadata"]["pack_id"].startswith("PACK-CASE-PER-2028-02-"))
        self.assertEqual(pack["executive_summary"]["evidence_completeness"], "INCOMPLETE")  # missing stays missing
        self.assertTrue(all(x["status"] == "OPEN" for x in pack["exception_register"]["exceptions"]))
        sep = self.case(BASELINE, "sep")
        sep_case = self.tmp / "sep_prepared"
        prepare_case(sep / "source_data", sep_case, BASELINE)
        feb_status, _, _, _, feb_findings = build(case, p)
        sep_status, _, _, _, sep_findings = build(sep_case, BASELINE)
        self.assertEqual((feb_status, len(feb_findings)), (sep_status, len(sep_findings)))

    def test_wrong_period_calendar(self):
        p = PeriodConfig(2026, 10)
        d = self.tmp / "oct"
        shutil.copyfile(DEFAULT_SET / "source_data" / "recon_calendar_2026-09.csv", (d / "source_data").mkdir(parents=True) or
                        d / "source_data" / p.filename("IN-01"))
        v = Validator(d, p)
        v.run()
        self.assertEqual(v.state["IN-01"][0], "WRONG_PERIOD")
        self.assertIn("2026-10-01 to 2026-10-31", next(r for r in v.results if r["check_id"] == "DQ-PERIOD")["computed"])

    def test_periods_in_sequence_do_not_interfere(self):
        results = {}
        for month in (1, 2, 3, 9, 10, 11):
            p = PeriodConfig(2026, month)
            v = Validator(self.case(p, f"c{month}"))
            v.run()
            results[month] = (v.period.period_id, len(v.recon_days))
        again = Validator(self.tmp / "c2")
        again.run()
        self.assertEqual((again.period.period_id, len(again.recon_days)), results[2])
        self.assertEqual(results[9], ("PER-2026-09", 22))


class DocumentApplicability(Tmp):
    def test_policy_effective_after_the_period_is_not_applied(self):
        p = PeriodConfig(2026, 4)                     # the illustrative policy v1.2 is effective from 2026-05-07
        d = self.case(p)
        (d / "supporting_documents").mkdir()
        shutil.copyfile(DEFAULT_SET / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf",
                        d / "supporting_documents" / p.filename("IN-17"))
        v = Validator(d, p)
        v.run()
        r = next(r for r in v.results if r["check_id"] == "V01-PDF" and "effective" in r["note"])
        self.assertEqual((r["outcome"], r["root_cause"]), ("FAIL", "INVALID_FILE|IN-17"))
        self.assertNotIn("IN-17", v.pdf)
        self.assertFalse([x for x in v.results if x["check_id"] == "C03-POLICY" and x["outcome"] == "PASS"])
        june = PeriodConfig(2026, 6)                   # in force: used
        d2 = self.case(june, "june")
        (d2 / "supporting_documents").mkdir()
        shutil.copyfile(DEFAULT_SET / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf",
                        d2 / "supporting_documents" / june.filename("IN-17"))
        v2 = Validator(d2, june)
        v2.run()
        self.assertIn("IN-17", v2.pdf)

    def test_return_receipt_must_be_for_the_previous_period(self):
        p = PeriodConfig(2026, 10)                     # expects the September return; the file is August's
        d = self.case(p)
        (d / "supporting_documents").mkdir()
        shutil.copyfile(DEFAULT_SET / "supporting_documents" / "rep027_submission_receipt_2026-08.pdf",
                        d / "supporting_documents" / p.filename("IN-19"))
        v = Validator(d, p)
        v.run()
        r = next(r for r in v.results if r["check_id"] == "C16-RETURN")
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("for 2026-09", r["note"])
        self.assertIn("due 2026-10-21", r["computed"])     # 15 business days after 30 September

    def test_optional_documents_do_not_block_and_missing_stays_missing(self):
        p = PeriodConfig(2026, 2)
        v = Validator(self.case(p), p)
        v.run()
        by_scope = {r["scope"]: r for r in v.results if r["check_id"] == "V00-FILE"}
        self.assertEqual((by_scope["IN-18"]["outcome"], by_scope["IN-19"]["outcome"]), ("NOT_APPLICABLE", "NOT_APPLICABLE"))
        self.assertEqual(by_scope["IN-05"]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(p.optional_ids, ["IN-18", "IN-19"])
        self.assertEqual(len(p.required_ids), 17)


class Continuity(Tmp):
    """Two consecutive synthetic test periods with one account, one client and one open receipt."""

    def period_case(self, p, name, opening_bank, closing_bank, opening_ledger, ledger_movement, opening_client, closing_client,
                    open_receipt_amount):
        d = self.case(p, name)
        shutil.copyfile(DEFAULT_SET / "source_data" / "account_inventory.csv", d / "source_data" / "account_inventory.csv")
        sd = d / "source_data"
        first, last = p.start, p.end
        write_csv(sd / p.filename("IN-08"), "IN-08", [
            {"statement_id": f"ST-{p.token}-1", "account_id": "SGA-GBP-01", "statement_date": first.isoformat(),
             "as_at_ts": f"{first}T23:59:59{london_offset(first)}", "currency": "GBP", "opening_balance_amount": opening_bank,
             "opening_balance_dc": "C", "closing_balance_amount": opening_bank, "closing_balance_dc": "C", "entry_count": "0"},
            {"statement_id": f"ST-{p.token}-2", "account_id": "SGA-GBP-01", "statement_date": last.isoformat(),
             "as_at_ts": f"{last}T23:59:59{london_offset(last)}", "currency": "GBP", "opening_balance_amount": opening_bank,
             "opening_balance_dc": "C", "closing_balance_amount": closing_bank, "closing_balance_dc": "C", "entry_count": "0"}])
        write_csv(sd / p.filename("IN-10"), "IN-10", [
            {"ledger_entry_id": f"LE-{p.token}-0", "account_id": "SGA-GBP-01", "posted_ts": p.opening_point_iso(),
             "entry_type": "OPENING_BALANCE", "amount": opening_ledger, "dc_indicator": "D", "currency": "GBP", "payment_reference": "OPENING"},
            {"ledger_entry_id": f"LE-{p.token}-1", "account_id": "SGA-GBP-01", "posted_ts": f"{first.replace(day=10)}T10:00:00{london_offset(first.replace(day=10))}",
             "entry_type": "BANK_LOAD", "amount": ledger_movement, "dc_indicator": "D", "currency": "GBP", "payment_reference": f"REF-{p.token}"}])
        write_csv(sd / p.filename("IN-03"), "IN-03", [
            {"snapshot_id": f"CBS-{p.token}-O", "recon_date": p.previous_end.isoformat(), "as_at_ts": p.opening_point_iso(),
             "client_id": "C0001", "asset_pool_id": "POOL-EMONEY", "currency": "GBP", "balance": opening_client},
            {"snapshot_id": f"CBS-{p.token}-C", "recon_date": last.isoformat(), "as_at_ts": PeriodConfig(p.next.year, p.next.month).opening_point_iso(),
             "client_id": "C0001", "asset_pool_id": "POOL-EMONEY", "currency": "GBP", "balance": closing_client}])
        write_csv(sd / p.filename("IN-04"), "IN-04", [
            {"receipt_id": "UR-1", "bank_reference": "BR-1", "receipt_date": "2030-01-20", "receipt_ts": "2030-01-20T10:00:00+00:00",
             "amount": open_receipt_amount, "currency": "GBP", "classification": "UNALLOCATED"}])
        return d

    def test_previous_closing_against_next_opening(self):
        jan, feb = PeriodConfig(2030, 1), PeriodConfig(2030, 2)
        prev = self.period_case(jan, "jan", "1000.00", "1500.00", "1000.00", "500.00", "40.00", "55.00", "7.00")
        cur = self.period_case(feb, "feb", "1500.00", "1500.00", "1450.00", "0.00", "55.00", "55.00", "7.00")
        report = compare(prev, cur)
        status = {(i["view"], i["status"]) for i in report["items"]}
        self.assertEqual((report["previous_period"], report["current_period"]), ("PER-2030-01", "PER-2030-02"))
        self.assertIn(("BANK", "MATCH"), status)
        cash = next(i for i in report["items"] if i["view"] == "CASH_BOOK" and i["key"].startswith("SGA-GBP-01"))
        eur = next(i for i in report["items"] if i["view"] == "CASH_BOOK" and i["key"].startswith("SGA-EUR-01"))
        self.assertEqual(eur["status"], "NOT_VERIFIABLE")  # no EUR records in either fixture: not assumed to be zero
        self.assertEqual((cash["status"], cash["previous_closing"], cash["current_opening"], cash["difference"]),
                         ("DIFFERENCE", "1500.00", "1450.00", "-50.00"))     # reported, never adjusted
        self.assertIn(("CLIENT", "MATCH"), status)
        self.assertIn(("UNALLOCATED", "MATCH"), status)
        self.assertEqual(report["status"], "DIFFERENCE")

    def test_without_a_previous_period_nothing_is_assumed(self):
        report = compare(None, DEFAULT_SET)
        self.assertEqual((report["status"], report["previous_period"], len(report["items"])), ("NOT_VERIFIABLE", "PER-2026-08", 1))

    def test_periods_must_be_consecutive(self):
        jan, mar = PeriodConfig(2030, 1), PeriodConfig(2030, 3)
        prev = self.period_case(jan, "jan", "1.00", "1.00", "1.00", "0.00", "1.00", "1.00", "1.00")
        cur = self.period_case(mar, "mar", "1.00", "1.00", "1.00", "0.00", "1.00", "1.00", "1.00")
        with self.assertRaises(PeriodError):
            compare(prev, cur)


class SeptemberScenarios(unittest.TestCase):
    """All nine September scenarios resolve to the baseline period and run through the same engine path."""

    def test_nine_scenarios_through_period_config(self):
        names = [p.name for p in sorted(DATASETS.iterdir()) if p.is_dir()]
        self.assertEqual(len(names), 9)
        for n in names:
            v = Validator(DATASETS / n, "PER-2026-09")
            v.run()
            self.assertEqual(v.period, BASELINE, n)
            self.assertEqual(len(v.recon_days), 22, n)


if __name__ == "__main__":
    unittest.main()
