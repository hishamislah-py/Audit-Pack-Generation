"""Approved scenario specifications TC01-TC06 (Stage C approval 23 Nov 2026; TC03 revision 3 the same day: 24/25 Sep, AQ-GBP-20260924).

Everything here is written by hand from SCENARIO_CATALOGUE.md. It is NOT computed from the generated files:
  - ops / correction_ops: the record operations (scenarios.py vocabulary, with expected old values)
  - fin: the deterministic financial answer key, as stated by the specification
      expected_anomalies: the complete set of findings the independent validator must report (and nothing else)
      figures: key values the validator must recompute exactly
  - engine_predicted*: current-engine output predicted from SOURCE READING ONLY (never executed)
  - future: desired enriched-engine behaviour (PROPOSED; category names PENDING)
  - ai: AI investigation expectations (kept separate from fin)
"""

F = "FAIL"


def setf(fid, key, field, old, new, why):
    return {"op": "set_field", "file_id": fid, "key": key, "field": field, "old": old, "new": new, "why": why}


def add(fid, record, why, after=None):
    op = {"op": "add_record", "file_id": fid, "record": record, "why": why}
    if after:
        op["insert_after"] = after
    return op


def delete(fid, key, why):
    return {"op": "delete_record", "file_id": fid, "key": key, "why": why}


def predicted(sid, non_passing, exceptions, evidence=None, groups=(), candidates=(), status="EXCEPTIONS_OPEN", must_hold=(), notes=()):
    """Answer-key-compatible structure (uc042lib.validate.compare_answer_key fields) plus labels."""
    return {"label": "ENGINE-PREDICTED (source reading of the reference engine; NOT EXECUTED; unverified)",
            "scenario_id": sid, "expected_case_status": status,
            "non_passing_results": sorted(non_passing),
            "exceptions": [{"exception_id": f"EXC-{sid}-{n:02d}", "severity": s, "root_cause": r, "affected_results": a}
                           for n, (s, r, a) in enumerate(exceptions, 1)],
            "evidence_statuses": evidence or {}, "investigation_groups": [list(g) for g in groups],
            "candidate_relationships": [list(c) for c in candidates],
            "must_hold": list(must_hold), "notes": list(notes)}


CLEAN = lambda sid: predicted(sid, [], [], status="CLEAN", notes=[
    "Corrected evidence equals the clean baseline (or is internally consistent); no FAIL or INSUFFICIENT_EVIDENCE result expected."])

GBP, EUR = "SGA-GBP-01", "SGA-EUR-01"
D28 = ["2026-09-28", "2026-09-29", "2026-09-30"]

# ---------------------------------------------------------------------------------------------------------- TC01
_TC01_LEDGER = {"2026-09-28": ("378706.65", "379953.45"), "2026-09-29": ("388744.47", "389991.27"), "2026-09-30": ("395844.86", "397091.66")}
TC01 = {
    "scenario_id": "TC01", "dir": "TC01_DUPLICATE_TRANSACTION", "customer_label": "SYNTHETIC TEST Ashcombe Pay Ltd",
    "title": "Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80)",
    "business": ("The firm's cash-book interface re-ran at 09:25 on Mon 28 Sep 2026 and re-posted the 09:10 inbound transfer "
                 "E2E-GBP-0928-L01 (client C0008, GBP 1,246.80) as a new ledger row. The cash-book extract supplied for audit holds both "
                 "rows. The firm's reconciliation records (IN-05, IN-06) were prepared from the correct ledger."),
    "ops": [add("IN-10", {"ledger_entry_id": "LE-GBP-0928-0007", "account_id": GBP, "posted_ts": "2026-09-28T09:25:00+01:00",
                          "entry_type": "BANK_LOAD", "amount": "1246.80", "dc_indicator": "D", "currency": "GBP",
                          "payment_reference": "E2E-GBP-0928-L01"},
                "interface re-run re-posted the 09:10 receipt E2E-GBP-0928-L01", after="LE-GBP-0928-0001")],
    "unchanged_on_purpose": ["IN-09 (one bank credit BE-GBP-0928-L01)", "IN-11 (one LOAD_BANK TX-0928-00001)", "IN-03 snapshots",
                             "IN-05 and IN-06 reported values", "IN-14 (header only)"],
    "fin": {
        "expected_anomalies":
            [f"BL_DIFF {d} {GBP} -1246.80" for d in D28] + [f"RR_DIFF {d} GBP 1246.80" for d in D28]
            + [f"BL_DIFF_NOT_LOGGED {d} {GBP}" for d in D28]
            + [f"REPORTED IN-05 IRR-EMONEY-GBP-{d.replace('-', '')} {fld} reported={rp} recomputed={val}"
               for d, (rep, new) in _TC01_LEDGER.items()
               for fld, val, rp in (("item_a", new, rep), ("resource_reported", new, rep), ("difference_reported", "1246.80", "0.00"))]
            + [f"REPORTED IN-06 ERL-{GBP}-{d.replace('-', '')} {fld} reported={rep} recomputed={val}"
               for d, (rep, new) in _TC01_LEDGER.items()
               for fld, val, rep in (("ledger_balance_reported", new, rep), ("difference_reported", "-1246.80", "0.00"))]
            + [f"BANK_MULTI_CLAIM BE-GBP-0928-L01 IN-10=LE-GBP-0928-0001,LE-GBP-0928-0007"],
        "figures": {**{f"ledger_1700|{d}/{GBP}": new for d, (old, new) in _TC01_LEDGER.items()},
                    **{f"bank_1700|{d}/{GBP}": old for d, (old, new) in _TC01_LEDGER.items()},
                    **{f"requirement_1700|{d}/GBP": old for d, (old, new) in _TC01_LEDGER.items()},
                    **{f"resource_1700|{d}/GBP": new for d, (old, new) in _TC01_LEDGER.items()}},
        "summary": {"duplicate": {"original": "IN-10 LE-GBP-0928-0001", "duplicate": "IN-10 LE-GBP-0928-0007",
                                  "matching_attributes": ["account_id", "payment_reference", "amount", "entry_type", "dc_indicator", "currency"],
                                  "classification": "EXACT DUPLICATE OF ONE BUSINESS EVENT (distinct ledger key)",
                                  "not_legitimate_because": ["end-to-end reference is unique per payment",
                                                             "one bank credit BE-GBP-0928-L01", "one LOAD_BANK TX-0928-00001",
                                                             "C0008 snapshot rises by 1,246.80 once"]},
                    "financial_impact": "cash-book extract overstates item A by 1,246.80 from 28 Sep to period end; real safeguarding position unaffected",
                    "legitimate_repeat_controls_unchanged": ["TX-0908-00003..TX-0908-00006 (4 x 2,500.00 LOAD_CARD, 4 clients)",
                                                             "TX-0909-0R001 = TX-0902-00044 (60.00)", "TX-0916-0R001 = TX-0903-00016 (284.02)"]},
    },
    "engine_predicted": predicted("TC01",
        [["C08-DIFFERENCE", f"{d}/{GBP}", F] for d in D28] + [["DISC-LOG", f"{GBP} from 2026-09-28", F]]
        + [["C06-DIFFERENCE", f"{d}/GBP", F] for d in D28] + [["C05-RESOURCE", f"{d}/GBP", F] for d in D28]
        + [["RC2-LEDGER", f"{d}/{GBP}", F] for d in D28],
        [("Critical", f"BANK_LEDGER_DIFFERENCE|{GBP}|2026-09-28|-1246.80", 4)]
        + [("Critical", f"INTERNAL_DIFFERENCE|{d}/GBP", 1) for d in D28]
        + [x for d in D28 for x in (("High", f"C05-RESOURCE|{d}/GBP", 1), ("High", f"RC2-LEDGER|{d}/{GBP}", 1))],
        evidence={"EXC-TC01-01": "NOT_EVIDENCED"}, groups=[["EXC-TC01-02", "EXC-TC01-03", "EXC-TC01-04"]],
        must_hold=["CASH-BANK-LINK PASS for both LE-GBP-0928-0001 and LE-GBP-0928-0007 (no one-to-one matching, gap G-04)",
                   "RC4-DIRECT TX-0928-00001 PASS", "C04-REQUIREMENT PASS 28-30 Sep GBP", "CBAL-ROLLFWD PASS for C0008",
                   "EXC-TC01-01 flags OWN_FUNDS_REQUIRED and NO_INVESTIGATION_LOGGED"]),
    "correction": {
        "what_was_wrong": "The cash-book extract contained a duplicate posting (LE-GBP-0928-0007) created by an interface re-run.",
        "what_changed": "LE-GBP-0928-0007 removed from sga_cashbook_entries_2026-09.csv; the file is byte-identical to the clean baseline IN-10.",
        "ops": [delete("IN-10", "LE-GBP-0928-0007", "duplicate interface posting removed")],
        "must_equal_baseline": ["IN-10"],
        "fin": {"expected_anomalies": [], "figures": {f"ledger_1700|{d}/{GBP}": old for d, (old, new) in _TC01_LEDGER.items()}},
    },
    "engine_predicted_after_correction": CLEAN("TC01"),
    "future": {"root": "PENDING:DUPLICATE_TRANSACTION", "gaps": ["G-04", "G-05", "G-19"],
               "expected": ["One root cause: LE-GBP-0928-0007 duplicates LE-GBP-0928-0001 (account, payment_reference, amount, entry_type) against one bank counterpart BE-GBP-0928-L01",
                            "All ledger-derived failures 28-30 Sep (C08, C06, C05, RC2, DISC-LOG) linked to that root as consequences",
                            "Financial impact +1,246.80 ledger overstatement; classification EXACT DUPLICATE",
                            "Legitimate-repeat controls (4 x 2,500.00 card loads; refunds equal to originals) NOT flagged"]},
    "ai": {"findings": ["Two IN-10 rows share E2E-GBP-0928-L01 while IN-09 and IN-11 hold one each: a duplicate posting, not two receipts",
                        "The -1,246.80 bank-ledger and +1,246.80 internal differences from 28 Sep equal the duplicate exactly",
                        "The firm's reported figures exclude the duplicate: the defect is in the supplied extract, not the firm's reconciliation"],
           "evidence": ["IN-10 LE-GBP-0928-0001", "IN-10 LE-GBP-0928-0007", "IN-09 BE-GBP-0928-L01", "IN-11 TX-0928-00001",
                        "IN-05 IRR-EMONEY-GBP-20260928..30", "IN-06 ERL-SGA-GBP-01-20260928..30"],
           "missing_evidence": ["interface run log / posting audit trail"],
           "confidence": "high for the duplicate; medium for extract defect versus ledger defect",
           "must_not": ["treat the two rows as two genuine receipts", "recommend an own-funds top-up (real position unaffected)"],
           "analyst_action": "Reject the submitted cash-book extract and request a corrected extract; no own-funds top-up required."},
}

# ---------------------------------------------------------------------------------------------------------- TC02
TC02 = {
    "scenario_id": "TC02", "dir": "TC02_AMOUNT_MISMATCH", "customer_label": "SYNTHETIC TEST Brindle Wallet Ltd",
    "title": "Amount mismatch: transaction export 3,053.61 vs bank 3,035.61 for E2E-GBP-0908-L02",
    "business": ("Client C0006's bank-transfer load of Tue 8 Sep 2026 (E2E-GBP-0908-L02) was received by the bank, posted to the cash book "
                 "and reflected in the client snapshot at 3,035.61. The transaction export (IN-11) shows 3,053.61: a transposition."),
    "ops": [setf("IN-11", "TX-0908-00002", "amount", "3035.61", "3053.61", "transposition in the platform transaction export")],
    "unchanged_on_purpose": ["IN-09 BE-GBP-0908-L02 (3,035.61)", "IN-10 LE-GBP-0908-0002 (3,035.61)", "IN-03 C0006 snapshots"],
    "fin": {
        "expected_anomalies": ["TXN_BANK_AMOUNT TX-0908-00002 ref=E2E-GBP-0908-L02 txn=3053.61 bank=3035.61",
                               "ROLLFWD GBP/C0006 2026-09-08 18.00"],
        "figures": {"rollforward|GBP/C0006 2026-09-08": "39126.37", "snapshot|GBP/C0006 2026-09-08": "39108.37",
                    "rollforward|GBP/C0006 2026-09-09": "39850.59", "snapshot|GBP/C0006 2026-09-09": "39850.59"},
        "summary": {"matching_reference": "E2E-GBP-0908-L02", "source_amounts": {"IN-11 TX-0908-00002": "3053.61", "IN-09 BE-GBP-0908-L02": "3035.61",
                                                                                  "IN-10 LE-GBP-0908-0002": "3035.61"},
                    "difference": "+18.00 (transaction minus bank)", "direction": "transaction export overstates the receipt",
                    "outlier_source": "IN-11 (3,035.61 corroborated by IN-09, IN-10, IN-03)",
                    "financial_impact": "none on bank, ledger or requirement; client roll-forward for 8 Sep breaks by 18.00"},
    },
    "engine_predicted": predicted("TC02",
        [["RC4-DIRECT", "TX-0908-00002", F], ["CBAL-ROLLFWD", "GBP/C0006 2026-09-08", F]],
        [("High", "CBAL-ROLLFWD|GBP/C0006 2026-09-08", 1), ("High", "RC4-DIRECT|TX-0908-00002", 1)],
        must_hold=["CASH-BANK-LINK LE-GBP-0908-0002 PASS", "C08 and C06 for 8 Sep PASS", "CBAL-ROLLFWD GBP/C0006 2026-09-09 PASS",
                   "no investigation group (gap G-08)"]),
    "future": {"root": "PENDING:AMOUNT_MISMATCH", "gaps": ["G-07", "G-08", "G-09", "G-19"],
               "expected": ["One root: amount mismatch on reference E2E-GBP-0908-L02, IN-11 3,053.61 vs IN-09 3,035.61, difference +18.00 (transaction > bank)",
                            "CBAL-ROLLFWD failure linked by txn_id lineage", "Outlier source identified as IN-11"]},
    "ai": {"findings": ["Both exceptions are one mismatch on TX-0908-00002", "Direction: export overstates by 18.00",
                        "IN-11 is the outlier; 3,035.61 corroborated by IN-09, IN-10 and IN-03",
                        "Difference divisible by 9: possible transposition (HYPOTHESIS, not evidence)"],
           "evidence": ["IN-11 TX-0908-00002", "IN-09 BE-GBP-0908-L02", "IN-10 LE-GBP-0908-0002", "IN-03 CBS-20260907-C0006-GBP", "IN-03 CBS-20260908-C0006-GBP"],
           "missing_evidence": ["platform export audit trail"], "confidence": "high",
           "must_not": ["recommend changing the bank or cash-book records"],
           "analyst_action": "Accept the finding; request a corrected transaction export. No client-money shortfall."},
}

# ---------------------------------------------------------------------------------------------------------- TC03 (revision 3)
# Revision 3 (23 Nov 2026, user decision): Thu 24 Sep recorded / Fri 25 Sep cleared, using acquirer batch AQ-GBP-20260924
# (net 5,495.05). The user chose this option because 4,647.75 belongs to the 25 Sep batch. Revision 2 (25/26 Sep, Saturday
# records) is preserved in archive/rev2_tc03_25_26_sep_20261123/.
TC03 = {
    "scenario_id": "TC03", "dir": "TC03_TIMING_DIFFERENCE", "customer_label": "SYNTHETIC TEST Cresswell Money Ltd",
    "title": "Timing difference: acquirer settlement AQ-GBP-20260924 (5,495.05) recorded Thu 24 Sep, credited by the bank Fri 25 Sep",
    "business": ("The acquirer settlement for Thursday 24 Sep 2026 (AQ-GBP-20260924, net 5,495.05; settlement date 24 Sep per the acquirer "
                 "report) was posted by the firm to its cash book at 14:00 on 24 Sep. The acquirer's funds reached the safeguarding account "
                 "on Friday 25 Sep at 08:00, the next business day. At the 24 Sep 17:00 reconciliation point the bank is therefore 5,495.05 "
                 "below the ledger. The firm reported the difference, claimed timing and logged it; the 25 Sep statement and 17:00 "
                 "confirmation evidence the clearing, and at 25 Sep 17:00 bank and ledger agree."),
    "ops": [
        delete("IN-09", "BE-GBP-0924-AQ1", "the bank did not credit the acquirer settlement on 24 Sep"),
        add("IN-09", {"bank_entry_id": "BE-GBP-0925-T01", "statement_id": "ST-SGA-GBP-01-20260925-EOD", "account_id": GBP,
                      "booking_date": "2026-09-25", "booking_ts": "2026-09-25T08:00:00+01:00", "value_date": "2026-09-25",
                      "amount": "5495.05", "dc_indicator": "C", "currency": "GBP", "bank_reference": "AQ-GBP-20260924",
                      "end_to_end_ref": "", "counterparty_name": "Synthetic Acquirer Ltd",
                      "narrative_text": "CARD LOAD SETTLEMENT AQ-GBP-20260924"},
            "clearing entry: the bank credited AQ-GBP-20260924 on Fri 25 Sep 08:00, same reference and amount", after="BE-OWN-EUR-0924-TU1"),
        setf("IN-08", "ST-SGA-GBP-01-20260924-EOD", "closing_balance_amount", "370603.29", "365108.24", "24 Sep statement without the acquirer credit"),
        setf("IN-08", "ST-SGA-GBP-01-20260924-EOD", "entry_count", "6", "5", "one entry fewer on 24 Sep"),
        setf("IN-08", "ST-SGA-GBP-01-20260925-EOD", "opening_balance_amount", "370603.29", "365108.24", "25 Sep opening follows the 24 Sep closing"),
        setf("IN-08", "ST-SGA-GBP-01-20260925-EOD", "entry_count", "5", "6", "clearing entry added on 25 Sep (closing unchanged)"),
        setf("IN-07", "ST-SGA-GBP-01-20260924-1700", "balance_amount", "370603.29", "365108.24", "17:00 balance without the acquirer credit"),
        setf("IN-06", f"ERL-{GBP}-20260924", "bank_balance_reported", "370603.29", "365108.24", "firm reports the bank balance per the 17:00 confirmation"),
        setf("IN-06", f"ERL-{GBP}-20260924", "difference_reported", "0.00", "-5495.05", "firm reports bank minus ledger"),
        setf("IN-06", f"ERL-{GBP}-20260924", "timing_difference_claimed", "false", "true", "preparer claims timing"),
        add("IN-14", {"discrepancy_id": "DL-0001", "logged_ts": "2026-09-24T18:05:00+01:00", "recon_ref": f"ERL-{GBP}-20260924",
                      "account_id": GBP, "currency": "GBP", "amount": "-5495.05",
                      "description": "Acquirer settlement AQ-GBP-20260924 not credited by the bank by 17:00; expected next business day",
                      "cause_category": "TIMING", "cause_evidence_ref": "BE-GBP-0925-T01", "funding_reference": "",
                      "status": "RESOLVED", "resolved_ts": "2026-09-25T09:00:00+01:00", "approver_id": "U-04"},
            "the firm's own investigation record (follows SC2 precedent: cause_category TIMING)"),
    ],
    "unchanged_on_purpose": ["IN-10 cash book (LE-GBP-0924-0003 posted 24 Sep 14:00)", "IN-11 card loads of AQ-GBP-20260924",
                             "IN-12 AQ-GBP-20260924 (cycle and settlement date 24 Sep)", "IN-13 lines", "IN-03 snapshots", "IN-05 internal records",
                             "IN-01 calendar", "IN-07 25 Sep confirmation (375,461.46: the clearing is booked before 17:00)",
                             "IN-08 25 Sep closing (375,461.46)", "own-funds top-up TOPUP-GBP-20260924 (still credited 24 Sep)"],
    "fin": {
        "expected_anomalies": [f"BL_DIFF 2026-09-24 {GBP} -5495.05", f"BL_DIFF_LOGGED 2026-09-24 {GBP} DL-0001",
                               "TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05",
                               "BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25"],
        "figures": {f"bank_1700|2026-09-24/{GBP}": "365108.24", f"ledger_1700|2026-09-24/{GBP}": "370603.29",
                    f"bank_1700|2026-09-25/{GBP}": "375461.46", f"ledger_1700|2026-09-25/{GBP}": "375461.46",
                    "requirement_1700|2026-09-24/GBP": "370603.29", "resource_1700|2026-09-24/GBP": "370603.29",
                    "requirement_1700|2026-09-25/GBP": "375461.46", "resource_1700|2026-09-25/GBP": "375461.46"},
        "summary": {"transaction_dates": "card loads of AQ-GBP-20260924 authorised and executed 24 Sep (IN-11)",
                    "processing_date": "cash book LE-GBP-0924-0003 posted 2026-09-24T14:00 (ledger D, +5,495.05)",
                    "settlement_date": "2026-09-24 (IN-12 cycle_date and settlement_date)",
                    "bank_clearing": "BE-GBP-0925-T01 booked 2026-09-25T08:00 (Friday, next business day), value date 2026-09-25",
                    "reconciliation_cut_off": "2026-09-24 17:00 Europe/London",
                    "difference_at_cut_off": "bank minus ledger = -5,495.05 (reported correctly by the firm)",
                    "clearing_window": "existing rule D1: cleared no later than the next business day after 24 Sep (Fri 25 Sep); the clearing is on that day",
                    "next_reconciliation_day": "25 Sep 17:00: bank 375,461.46 = ledger 375,461.46",
                    "expected_treatment": "explainable timing item, evidenced by the 25 Sep clearing; under existing rules the 24 Sep difference is still reported as an exception (FAIL) that stays OPEN awaiting human confirmation; it is never auto-resolved",
                    "amount_note": "5,495.05 is the net of AQ-GBP-20260924; the previously stated 4,647.75 is the net of the 25 Sep batch, so the user chose the 24 Sep batch (23 Nov 2026)"},
    },
    "engine_predicted": predicted("TC03",
        [["C08-DIFFERENCE", f"2026-09-24/{GBP}", F]],
        [("Critical", f"BANK_LEDGER_DIFFERENCE|{GBP}|2026-09-24|-5495.05", 1)],
        evidence={"EXC-TC03-01": "TIMING_EVIDENCED"},
        must_hold=["C08 FAIL note: 'difference explained by timing: LE-GBP-0924-0003 / BE-GBP-0925-T01 (ref AQ-GBP-20260924, -5495.05, cleared 2026-09-25); cleared within one business day (D1); awaiting human confirmation; not resolved'",
                   "EXC-TC03-01 category 'Bank-ledger difference (explained by timing evidence, awaiting human confirmation)'; status OPEN; review AWAITING_HUMAN_REVIEW; flag OWN_FUNDS_REQUIRED (negative difference)",
                   "DISC-LOG PASS (DL-0001 logged)", "C11-BATCH-BANK AQ-GBP-20260924 PASS with informational note: booked 2026-09-25, 1 business day(s) after the settlement date (within the allowance)",
                   "CASH-BANK-LINK LE-GBP-0924-0003 PASS; FUND-TOPUP AQ-GBP-20260924 PASS", "C08 2026-09-25 PASS (difference cleared)",
                   "DQ22-CONTINUITY PASS for ST-SGA-GBP-01-20260925-EOD; DQ23 and BC-VS-EOD PASS for 24 and 25 Sep",
                   "No records on non-reconciliation days"],
        notes=["TIMING_EVIDENCED depends on the 25 Sep IN-08 statement and IN-07 confirmation being present (validate.evidence_gap); both are ordinary baseline records."]),
    "future": {"root": "PENDING:TIMING_ITEM", "gaps": ["G-10", "G-13", "G-19"],
               "expected": ["Timing item AQ-GBP-20260924 traced end to end: transaction 24 Sep, posting 24 Sep 14:00, settlement date 24 Sep, bank credit 25 Sep 08:00",
                            "Evidence status TIMING_EVIDENCED as today; the exception stays OPEN until a human confirms; never auto-resolved",
                            "The informational C11-BATCH-BANK lag and the C08 timing item presented as one traceable item"]},
    "ai": {"findings": ["The -5,495.05 difference equals the AQ-GBP-20260924 net exactly",
                        "The cash book recorded the credit on 24 Sep 14:00; the bank credited it on 25 Sep 08:00 with the same reference and amount",
                        "The clearing falls on the next business day; at 25 Sep 17:00 bank and ledger agree",
                        "The firm claimed timing and logged DL-0001; the claim is corroborated by the 25 Sep statement, not by the claim itself"],
           "evidence": ["IN-10 LE-GBP-0924-0003", "IN-09 BE-GBP-0925-T01", "IN-08 ST-SGA-GBP-01-20260924-EOD", "IN-08 ST-SGA-GBP-01-20260925-EOD",
                        "IN-07 ST-SGA-GBP-01-20260924-1700", "IN-07 ST-SGA-GBP-01-20260925-1700", "IN-12 AQ-GBP-20260924", "IN-06 ERL-SGA-GBP-01-20260924", "IN-14 DL-0001"],
           "missing_evidence": ["acquirer remittance advice confirming the payout date (optional)"],
           "confidence": "high that this is a timing difference",
           "must_not": ["mark the exception resolved", "rely on the log's TIMING label or the timing claim as proof"],
           "analyst_action": "Confirm the timing item and record the shortfall at the 24 Sep point; confirm whether the firm's policy required an own-funds top-up at that point."},
}

# ---------------------------------------------------------------------------------------------------------- TC04
TC04 = {
    "scenario_id": "TC04", "dir": "TC04_UNMATCHED_TRANSACTION", "customer_label": "SYNTHETIC TEST Dunmore Payments Ltd",
    "title": "Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart",
    "business": ("At 16:20 on Wed 30 Sep 2026 the EUR safeguarding account received an inbound transfer of 650.00 (E2E-EUR-0930-U01) from an "
                 "unidentified payer. The firm did not post it to the cash book, did not record it in the unallocated register and created no "
                 "client transaction. Its external reconciliation reported the difference but no investigation was logged."),
    "ops": [
        add("IN-09", {"bank_entry_id": "BE-EUR-0930-U01", "statement_id": "ST-SGA-EUR-01-20260930-EOD", "account_id": EUR,
                      "booking_date": "2026-09-30", "booking_ts": "2026-09-30T16:20:00+01:00", "value_date": "2026-09-30", "amount": "650.00",
                      "dc_indicator": "C", "currency": "EUR", "bank_reference": "E2E-EUR-0930-U01", "end_to_end_ref": "E2E-EUR-0930-U01",
                      "counterparty_name": "Synthetic payer (unidentified)", "narrative_text": "INBOUND TRANSFER"},
            "unidentified inbound credit, not recorded by the firm", after="BE-EUR-0930-R01"),
        setf("IN-08", "ST-SGA-EUR-01-20260930-EOD", "closing_balance_amount", "118555.00", "119205.00", "statement includes the credit"),
        setf("IN-08", "ST-SGA-EUR-01-20260930-EOD", "entry_count", "5", "6", "one more entry"),
        setf("IN-07", "ST-SGA-EUR-01-20260930-1700", "balance_amount", "118555.00", "119205.00", "credit booked before 17:00"),
        setf("IN-06", f"ERL-{EUR}-20260930", "bank_balance_reported", "118555.00", "119205.00", "firm reports the bank balance"),
        setf("IN-06", f"ERL-{EUR}-20260930", "difference_reported", "0.00", "650.00", "firm reports the difference, no timing claim"),
    ],
    "unchanged_on_purpose": ["IN-10 (no cash-book posting)", "IN-04 (not registered)", "IN-11 (no transaction)", "IN-05 (internal recon omitted the receipt)",
                             "IN-14 (no investigation logged)"],
    "fin": {
        "expected_anomalies": [f"BL_DIFF 2026-09-30 {EUR} 650.00", f"BL_DIFF_NOT_LOGGED 2026-09-30 {EUR}",
                               "BANK_NO_COUNTERPART BE-EUR-0930-U01 ref=E2E-EUR-0930-U01"],
        "figures": {f"bank_1700|2026-09-30/{EUR}": "119205.00", f"ledger_1700|2026-09-30/{EUR}": "118555.00",
                    "requirement_1700|2026-09-30/EUR": "118555.00", "resource_1700|2026-09-30/EUR": "118555.00"},
        "summary": {"source_with_record": "IN-09 BE-EUR-0930-U01 (credit 650.00, 2026-09-30T16:20)",
                    "absent_counterparts": ["IN-10 cash-book entry", "IN-04 register receipt", "IN-11 LOAD_BANK transaction"],
                    "references_checked": ["IN-10.payment_reference", "IN-11.payment_reference", "IN-04.bank_reference",
                                           "IN-12.expected_bank_reference", "TOPUP-EUR-20260930"],
                    "financial_impact": "bank exceeds ledger by 650.00 at 30 Sep 17:00; recomputed requirement potentially understated by up to 650.00 if the receipt is relevant funds"},
    },
    "engine_predicted": predicted("TC04",
        [["C08-DIFFERENCE", f"2026-09-30/{EUR}", F], ["DISC-LOG", f"{EUR} from 2026-09-30", F],
         ["BANK-CASH-LINK", "BE-EUR-0930-U01", F], ["C11-BANK-ENTRY", "BE-EUR-0930-U01", F]],
        [("Critical", f"BANK_LEDGER_DIFFERENCE|{EUR}|2026-09-30|650.00", 2), ("High", "UNMATCHED_BANK_ENTRY|BE-EUR-0930-U01", 2)],
        evidence={"EXC-TC04-01": "NOT_EVIDENCED"}, groups=[["EXC-TC04-01", "EXC-TC04-02"]],
        must_hold=["C04, C05, C06 EUR 30 Sep PASS (the engine cannot see the requirement understatement, gap G-15)",
                   "EXC-TC04-01 flag NO_INVESTIGATION_LOGGED; related record BE-EUR-0930-U01"]),
    "correction": {
        "what_was_wrong": "The 650.00 receipt was not recorded: no cash-book posting, no register entry, and the reconciliations omitted it.",
        "what_changed": "Receipt recorded as UNIDENTIFIED (IN-04 UR-0003) and posted (IN-10 LE-EUR-0930-0006); IN-05 and IN-06 for EUR 30 Sep updated.",
        "ops": [
            add("IN-04", {"receipt_id": "UR-0003", "bank_reference": "E2E-EUR-0930-U01", "receipt_date": "2026-09-30",
                          "receipt_ts": "2026-09-30T16:20:00+01:00", "amount": "650.00", "currency": "EUR", "classification": "UNIDENTIFIED",
                          "identified_date": "", "allocated_date": "", "allocated_ts": "", "client_id": ""},
                "receipt registered as unidentified", after="UR-0002"),
            add("IN-10", {"ledger_entry_id": "LE-EUR-0930-0006", "account_id": EUR, "posted_ts": "2026-09-30T16:20:00+01:00",
                          "entry_type": "UNALLOCATED_RECEIPT", "amount": "650.00", "dc_indicator": "D", "currency": "EUR",
                          "payment_reference": "E2E-EUR-0930-U01"}, "receipt posted to the cash book", after="LE-EUR-0930-0005"),
            setf("IN-05", "IRR-EMONEY-EUR-20260930", "requirement_reported", "118555.00", "119205.00", "requirement includes the open receipt"),
            setf("IN-05", "IRR-EMONEY-EUR-20260930", "resource_reported", "118555.00", "119205.00", "resource includes the receipt"),
            setf("IN-05", "IRR-EMONEY-EUR-20260930", "item_a", "118555.00", "119205.00", "item A includes the receipt"),
            setf("IN-06", f"ERL-{EUR}-20260930", "ledger_balance_reported", "118555.00", "119205.00", "ledger includes the receipt"),
            setf("IN-06", f"ERL-{EUR}-20260930", "difference_reported", "650.00", "0.00", "difference cleared"),
        ],
        "must_equal_baseline": [],
        "fin": {"expected_anomalies": [],
                "figures": {f"bank_1700|2026-09-30/{EUR}": "119205.00", f"ledger_1700|2026-09-30/{EUR}": "119205.00",
                            "requirement_1700|2026-09-30/EUR": "119205.00", "resource_1700|2026-09-30/EUR": "119205.00"}},
    },
    "engine_predicted_after_correction": predicted("TC04", [], [], status="CLEAN", must_hold=[
        "C04 includes UR-0003 (open at 17:00)", "CASH-BANK-LINK LE-EUR-0930-0006 PASS", "C11-BANK-ENTRY passes (register reference)",
        "C09-ALLOCATION UR-0003 PASS: open at the period end; allocation due 2026-10-01, after the period"]),
    "future": {"root": "PENDING:UNMATCHED_TRANSACTION", "gaps": ["G-14", "G-15", "G-19"],
               "expected": ["Bank-side unmatched credit classified as a potential unidentified receipt",
                            "Possible requirement understatement of 650.00 reported (G-15)"]},
    "ai": {"findings": ["The credit has no counterpart in IN-10, IN-11, IN-04, IN-12 or the top-up reference",
                        "It is a credit of client-payment form (end-to-end reference, INBOUND TRANSFER)",
                        "It probably belongs in the unallocated register as UNIDENTIFIED (HYPOTHESIS)"],
           "evidence": ["IN-09 BE-EUR-0930-U01", "IN-07 ST-SGA-EUR-01-20260930-1700", "IN-06 ERL-SGA-EUR-01-20260930", "IN-04 (no entry)", "IN-10 (no entry)"],
           "missing_evidence": ["payer details / remittance information"], "confidence": "high that it is unrecorded; low on its owner",
           "must_not": ["allocate the receipt to any client"],
           "analyst_action": "Require the firm to record the receipt (register and cash book), correct its reconciliations, and resubmit."},
}

# ---------------------------------------------------------------------------------------------------------- TC05
_TC05_MISSING = [("TX-0924-00018", "C0104", "222.18"), ("TX-0924-00019", "C0101", "431.57"), ("TX-0924-00020", "C0101", "193.70")]
TC05 = {
    "scenario_id": "TC05", "dir": "TC05_COMMON_CAUSE", "customer_label": "SYNTHETIC TEST Elmstead Card Services Ltd",
    "title": "Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export",
    "business": ("The client transaction export (IN-11) omits the three EUR card spends of scheme batch SB-EUR-20260924 (total 847.45), "
                 "consistent with the export being taken before the batch's clearing was processed. The scheme report, bank debit and "
                 "client snapshots are complete."),
    "ops": [delete("IN-11", t, f"export omitted the batch's spends ({c}, {a})") for t, c, a in _TC05_MISSING],
    "unchanged_on_purpose": ["IN-12 SB-EUR-20260924", "IN-13 SL-SB-EUR-20260924-0001..0003", "IN-09 BE-EUR-0924-SB1", "IN-10 LE-EUR-0924-0004", "IN-03 snapshots"],
    "fin": {
        "expected_anomalies": ["ROLLFWD EUR/C0101 2026-09-24 625.27", "ROLLFWD EUR/C0104 2026-09-24 222.18",
                               "LINE_TXN SL-SB-EUR-20260924-0001 TX-0924-00018 missing",
                               "LINE_TXN SL-SB-EUR-20260924-0002 TX-0924-00019 missing",
                               "LINE_TXN SL-SB-EUR-20260924-0003 TX-0924-00020 missing"],
        "figures": {"rollforward|EUR/C0101 2026-09-24": "30615.68", "snapshot|EUR/C0101 2026-09-24": "29990.41",
                    "rollforward|EUR/C0104 2026-09-24": "28055.28", "snapshot|EUR/C0104 2026-09-24": "27833.10",
                    "rollforward|EUR/C0102 2026-09-24": "31235.11", "snapshot|EUR/C0102 2026-09-24": "31235.11"},
        "summary": {"missing_transactions": [{"txn_id": t, "client_per_baseline": c, "amount": a} for t, c, a in _TC05_MISSING],
                    "total": "847.45 (= batch gross = net = bank debit BE-EUR-0924-SB1)",
                    "client_effects": {"C0101": "+625.27 (431.57 + 193.70)", "C0104": "+222.18"},
                    "financial_impact": "none on bank, ledger or requirement"},
    },
    "engine_predicted": predicted("TC05",
        [["C11-BATCH-ARITH", "SB-EUR-20260924", F], ["CBAL-ROLLFWD", "EUR/C0101 2026-09-24", F], ["CBAL-ROLLFWD", "EUR/C0104 2026-09-24", F]],
        [("High", "C11-BATCH-ARITH|SB-EUR-20260924", 1), ("High", "CBAL-ROLLFWD|EUR/C0101 2026-09-24", 1),
         ("High", "CBAL-ROLLFWD|EUR/C0104 2026-09-24", 1)],
        candidates=[["EXC-TC05-01", "EXC-TC05-03"]],
        must_hold=["No investigation group", "One UNVERIFIED candidate (line TX-0924-00018 = 222.18 = C0104 roll-forward gap)",
                   "No candidate for C0101: its gap is the SUM of two lines (gap G-16)", "C11-TXN-LINE PASS summary (missing transactions are not iterated)"]),
    "correction": {
        "what_was_wrong": "The transaction export omitted the three spends of SB-EUR-20260924.",
        "what_changed": "TX-0924-00018, -00019, -00020 restored; the file is byte-identical to the clean baseline IN-11.",
        "ops": [],  # built by the generator: one add_record per deleted row, record and position taken from the baseline
        "restore_from_baseline": ["IN-11"],
        "must_equal_baseline": ["IN-11"],
        "fin": {"expected_anomalies": [], "figures": {"rollforward|EUR/C0101 2026-09-24": "29990.41", "rollforward|EUR/C0104 2026-09-24": "27833.10"}},
    },
    "engine_predicted_after_correction": CLEAN("TC05"),
    "future": {"root": "PENDING:SUSPECTED_COMMON_CAUSE (UNVERIFIED)", "gaps": ["G-16", "G-17", "G-19"],
               "expected": ["The three exceptions presented together as one suspected common cause: missing transactions of batch SB-EUR-20260924",
                            "Basis: batch scope plus per-client line-sum match; still UNVERIFIED; no cause set deterministically"]},
    "ai": {"group_level": True,
           "findings": ["Batch lines reference 3 transaction IDs absent from the export",
                        "C0101 roll-forward exceeds its snapshot by 625.27; C0104 by 222.18",
                        "Possible common cause: the export is incomplete for SB-EUR-20260924"],
           "connecting_evidence": ["all 3 missing IDs belong to one batch", "222.18 equals one line exactly", "625.27 equals the sum of the other two lines",
                                   "no other batch or day affected", "header, lines and bank debit agree with each other"],
           "evidence": ["IN-12 SB-EUR-20260924", "IN-13 SL-SB-EUR-20260924-0001..0003", "IN-09 BE-EUR-0924-SB1",
                        "IN-03 CBS-20260923/24-C0101-EUR", "IN-03 CBS-20260923/24-C0104-EUR"],
           "missing_evidence": ["client of each missing transaction (settlement lines carry no client_id)", "export job log or a complete export"],
           "confidence": "medium-high that the export is incomplete; low-medium for client attribution (amount-based only)",
           "must_not": ["state the client attribution as confirmed", "cite the UNVERIFIED candidate as evidence"],
           "analyst_action": "Request a complete transaction export."},
}

# ---------------------------------------------------------------------------------------------------------- TC06
TC06 = {
    "scenario_id": "TC06", "dir": "TC06_INDEPENDENT_CAUSES", "customer_label": "SYNTHETIC TEST Farrowdale E-Money Ltd",
    "title": "Independent causes: export amount error (A), client snapshot error (B), acquirer line error (C); A and B share date and 90.00",
    "business": ("Three unrelated defects. A: C0007's bank load TX-0917-00002 shows 1,480.07 in the export against 1,390.07 at the bank. "
                 "B: C0004's 17 Sep 17:00 client-ledger snapshot is overstated by 90.00 and the firm's internal reconciliation used it. "
                 "C: line 2 of acquirer batch AQ-EUR-20260922 states 1,238.12 against 1,283.12. A and B deliberately share date (17 Sep), "
                 "currency (GBP) and magnitude (90.00): a decoy coincidence that must not be treated as a link."),
    "ops": [
        setf("IN-11", "TX-0917-00002", "amount", "1390.07", "1480.07", "cause A: export amount error"),
        setf("IN-03", "CBS-20260917-C0004-GBP", "balance", "40592.24", "40682.24", "cause B: client-ledger snapshot overstated"),
        setf("IN-05", "IRR-EMONEY-GBP-20260917", "requirement_reported", "341484.46", "341574.46", "cause B: firm's reconciliation used the ledger"),
        setf("IN-05", "IRR-EMONEY-GBP-20260917", "difference_reported", "0.00", "-90.00", "cause B: reported shortfall"),
        setf("IN-13", "SL-AQ-EUR-20260922-0002", "amount", "1283.12", "1238.12", "cause C: acquirer report line mis-stated"),
    ],
    "unchanged_on_purpose": ["IN-09/IN-10 for E2E-GBP-0917-L02 (1,390.07)", "IN-03 C0004 snapshots other than 17 Sep", "IN-12 AQ-EUR-20260922 header",
                             "IN-11 TX-0922-00016 (1,283.12)", "IN-09 BE-EUR-0922-AQ1"],
    "fin": {
        "expected_anomalies": ["TXN_BANK_AMOUNT TX-0917-00002 ref=E2E-GBP-0917-L02 txn=1480.07 bank=1390.07",
                               "ROLLFWD GBP/C0007 2026-09-17 90.00", "ROLLFWD GBP/C0004 2026-09-17 -90.00", "ROLLFWD GBP/C0004 2026-09-18 90.00",
                               "RR_DIFF 2026-09-17 GBP -90.00",
                               "BATCH_ARITH AQ-EUR-20260922 TXN lines=2069.15 header=2114.15",
                               "BATCH_ARITH AQ-EUR-20260922 NET lines=2059.53 header=2104.53",
                               "LINE_TXN SL-AQ-EUR-20260922-0002 TX-0922-00016 amount line=1238.12 txn=1283.12"],
        "figures": {"rollforward|GBP/C0007 2026-09-17": "36731.11", "snapshot|GBP/C0007 2026-09-17": "36641.11",
                    "rollforward|GBP/C0004 2026-09-17": "40592.24", "snapshot|GBP/C0004 2026-09-17": "40682.24",
                    "rollforward|GBP/C0004 2026-09-18": "42175.13", "snapshot|GBP/C0004 2026-09-18": "42085.13",
                    "requirement_1700|2026-09-17/GBP": "341574.46", "resource_1700|2026-09-17/GBP": "341484.46"},
        "summary": {"A": {"records": ["IN-11 TX-0917-00002", "IN-09 BE-GBP-0917-L02", "IN-10 LE-GBP-0917-0002"], "difference": "+90.00 transaction minus bank",
                          "outlier": "IN-11"},
                    "B": {"records": ["IN-03 CBS-20260917-C0004-GBP", "IN-05 IRR-EMONEY-GBP-20260917"],
                          "difference": "snapshot +90.00 (roll-forward 17 Sep -90.00, 18 Sep +90.00); reported shortfall -90.00 not supported by transactions"},
                    "C": {"records": ["IN-13 SL-AQ-EUR-20260922-0002", "IN-12 AQ-EUR-20260922", "IN-11 TX-0922-00016"], "difference": "-45.00 line vs header and transaction"},
                    "decoy": "A and B: same date 2026-09-17, same currency GBP, same magnitude 90.00; NO shared record, client or reference"},
    },
    "engine_predicted": predicted("TC06",
        [["RC4-DIRECT", "TX-0917-00002", F], ["CBAL-ROLLFWD", "GBP/C0007 2026-09-17", F], ["C06-DIFFERENCE", "2026-09-17/GBP", F],
         ["CBAL-ROLLFWD", "GBP/C0004 2026-09-17", F], ["CBAL-ROLLFWD", "GBP/C0004 2026-09-18", F], ["C11-BATCH-ARITH", "AQ-EUR-20260922", F]],
        [("Critical", "INTERNAL_DIFFERENCE|2026-09-17/GBP", 1), ("High", "C11-BATCH-ARITH|AQ-EUR-20260922", 1),
         ("High", "CBAL-ROLLFWD|GBP/C0004 2026-09-17", 1), ("High", "CBAL-ROLLFWD|GBP/C0004 2026-09-18", 1),
         ("High", "CBAL-ROLLFWD|GBP/C0007 2026-09-17", 1), ("High", "RC4-DIRECT|TX-0917-00002", 1)],
        groups=[["EXC-TC06-01", "EXC-TC06-03", "EXC-TC06-05"]],
        must_hold=["C04-REQUIREMENT 2026-09-17/GBP PASS (firm reported the overstated requirement)", "No candidates"],
        notes=["PREDICTED OVER-GROUPING, UNVERIFIED (gap G-18): L3 lineage (b) is predicted to link the 17 Sep internal difference to EVERY same-day GBP roll-forward failure, "
               "including EXC-TC06-05 (C0007, cause A, whose snapshot is correct). EXC-TC06-04 (C0004 next day) and EXC-TC06-06 (C0007 RC4) are predicted ungrouped. "
               "This must be confirmed by an engine run before it is reported as engine behaviour."]),
    "future": {"root": "three independent roots", "gaps": ["G-08", "G-18", "G-19"],
               "expected": ["Cluster A {EXC-TC06-06, EXC-TC06-05}: PENDING:AMOUNT_MISMATCH on TX-0917-00002",
                            "Cluster B {EXC-TC06-01, EXC-TC06-03, EXC-TC06-04}: client snapshot error C0004 17 Sep",
                            "Cluster C {EXC-TC06-02}: acquirer report line inconsistency",
                            "A/B coincidence recorded as REJECTED (no shared record or reference)"]},
    "ai": {"findings": ["Three separate causes",
                        "A is transaction-side: IN-11 is the outlier against IN-09, IN-10, IN-03",
                        "B is snapshot-side: C0004's 17 Sep snapshot fails the roll-forward in both directions and drives the reported shortfall",
                        "C is internal to the acquirer report: header, transaction and bank agree on 1,283.12",
                        "Equal date and amount of A and B is coincidence, explicitly rejected as a link"],
           "evidence": ["IN-11 TX-0917-00002", "IN-09 BE-GBP-0917-L02", "IN-03 CBS-20260916/17/18-C0004-GBP", "IN-05 IRR-EMONEY-GBP-20260917",
                        "IN-13 SL-AQ-EUR-20260922-0002", "IN-12 AQ-EUR-20260922", "IN-11 TX-0922-00016"],
           "missing_evidence": ["A: export audit trail", "B: client-ledger postings behind C0004's 17 Sep balance", "C: corrected acquirer report"],
           "confidence": "high for the separation", "must_not": ["group A with B on date and amount"],
           "analyst_action": "A: request corrected export. B: investigate the client-ledger posting; the reported 17 Sep shortfall is not supported by transactions. C: request corrected acquirer report."},
}

SCENARIOS = [TC01, TC02, TC03, TC04, TC05, TC06]
