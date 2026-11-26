# TC03 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Timing difference: acquirer settlement AQ-GBP-20260924 (5,495.05) recorded Thu 24 Sep, credited by the bank Fri 25 Sep**

Customer label: SYNTHETIC TEST Cresswell Money Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

The acquirer settlement for Thursday 24 Sep 2026 (AQ-GBP-20260924, net 5,495.05; settlement date 24 Sep per the acquirer report) was posted by the firm to its cash book at 14:00 on 24 Sep. The acquirer's funds reached the safeguarding account on Friday 25 Sep at 08:00, the next business day. At the 24 Sep 17:00 reconciliation point the bank is therefore 5,495.05 below the ledger. The firm reported the difference, claimed timing and logged it; the 25 Sep statement and 17:00 confirmation evidence the clearing, and at 25 Sep 17:00 bank and ledger agree.

## Evidence files involved

- IN-06 `external_recon_records_2026-09.csv` (mutated)
- IN-07 `bank_balance_confirmations_2026-09.csv` (mutated)
- IN-08 `bank_statements_eod_2026-09.csv` (mutated)
- IN-09 `bank_statement_entries_2026-09.csv` (mutated)
- IN-14 `discrepancy_log_2026-09.csv` (mutated)
- unchanged on purpose: IN-10 cash book (LE-GBP-0924-0003 posted 24 Sep 14:00)
- unchanged on purpose: IN-11 card loads of AQ-GBP-20260924
- unchanged on purpose: IN-12 AQ-GBP-20260924 (cycle and settlement date 24 Sep)
- unchanged on purpose: IN-13 lines
- unchanged on purpose: IN-03 snapshots
- unchanged on purpose: IN-05 internal records
- unchanged on purpose: IN-01 calendar
- unchanged on purpose: IN-07 25 Sep confirmation (375,461.46: the clearing is booked before 17:00)
- unchanged on purpose: IN-08 25 Sep closing (375,461.46)
- unchanged on purpose: own-funds top-up TOPUP-GBP-20260924 (still credited 24 Sep)

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **transaction_dates:** card loads of AQ-GBP-20260924 authorised and executed 24 Sep (IN-11)
- **processing_date:** cash book LE-GBP-0924-0003 posted 2026-09-24T14:00 (ledger D, +5,495.05)
- **settlement_date:** 2026-09-24 (IN-12 cycle_date and settlement_date)
- **bank_clearing:** BE-GBP-0925-T01 booked 2026-09-25T08:00 (Friday, next business day), value date 2026-09-25
- **reconciliation_cut_off:** 2026-09-24 17:00 Europe/London
- **difference_at_cut_off:** bank minus ledger = -5,495.05 (reported correctly by the firm)
- **clearing_window:** existing rule D1: cleared no later than the next business day after 24 Sep (Fri 25 Sep); the clearing is on that day
- **next_reconciliation_day:** 25 Sep 17:00: bank 375,461.46 = ledger 375,461.46
- **expected_treatment:** explainable timing item, evidenced by the 25 Sep clearing; under existing rules the 24 Sep difference is still reported as an exception (FAIL) that stays OPEN awaiting human confirmation; it is never auto-resolved
- **amount_note:** 5,495.05 is the net of AQ-GBP-20260924; the previously stated 4,647.75 is the net of the 25 Sep batch, so the user chose the 24 Sep batch (23 Nov 2026)

**Key figures**

| metric | scope | value |
|---|---|
| bank_1700|2026-09-24/SGA-GBP-01 | 365108.24 |
| bank_1700|2026-09-25/SGA-GBP-01 | 375461.46 |
| ledger_1700|2026-09-24/SGA-GBP-01 | 370603.29 |
| ledger_1700|2026-09-25/SGA-GBP-01 | 375461.46 |
| requirement_1700|2026-09-24/GBP | 370603.29 |
| requirement_1700|2026-09-25/GBP | 375461.46 |
| resource_1700|2026-09-24/GBP | 370603.29 |
| resource_1700|2026-09-25/GBP | 375461.46 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25`
- `BL_DIFF 2026-09-24 SGA-GBP-01 -5495.05`
- `BL_DIFF_LOGGED 2026-09-24 SGA-GBP-01 DL-0001`
- `TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC03`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| C08-DIFFERENCE | 2026-09-24/SGA-GBP-01 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC03-01 | Critical | `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-24|-5495.05` | 1 |

- Evidence statuses: {'EXC-TC03-01': 'TIMING_EVIDENCED'}
- Investigation groups: none
- Candidate relationships (UNVERIFIED): none
- Must hold: C08 FAIL note: 'difference explained by timing: LE-GBP-0924-0003 / BE-GBP-0925-T01 (ref AQ-GBP-20260924, -5495.05, cleared 2026-09-25); cleared within one business day (D1); awaiting human confirmation; not resolved'
- Must hold: EXC-TC03-01 category 'Bank-ledger difference (explained by timing evidence, awaiting human confirmation)'; status OPEN; review AWAITING_HUMAN_REVIEW; flag OWN_FUNDS_REQUIRED (negative difference)
- Must hold: DISC-LOG PASS (DL-0001 logged)
- Must hold: C11-BATCH-BANK AQ-GBP-20260924 PASS with informational note: booked 2026-09-25, 1 business day(s) after the settlement date (within the allowance)
- Must hold: CASH-BANK-LINK LE-GBP-0924-0003 PASS; FUND-TOPUP AQ-GBP-20260924 PASS
- Must hold: C08 2026-09-25 PASS (difference cleared)
- Must hold: DQ22-CONTINUITY PASS for ST-SGA-GBP-01-20260925-EOD; DQ23 and BC-VS-EOD PASS for 24 and 25 Sep
- Must hold: No records on non-reconciliation days
- **Note:** TIMING_EVIDENCED depends on the 25 Sep IN-08 statement and IN-07 confirmation being present (validate.evidence_gap); both are ordinary baseline records.

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `PENDING:TIMING_ITEM`; gaps G-10, G-13, G-19.

- Timing item AQ-GBP-20260924 traced end to end: transaction 24 Sep, posting 24 Sep 14:00, settlement date 24 Sep, bank credit 25 Sep 08:00
- Evidence status TIMING_EVIDENCED as today; the exception stays OPEN until a human confirms; never auto-resolved
- The informational C11-BATCH-BANK lag and the C08 timing item presented as one traceable item

## 4. AI investigation expectations (separate from FIN)

- Finding: The -5,495.05 difference equals the AQ-GBP-20260924 net exactly
- Finding: The cash book recorded the credit on 24 Sep 14:00; the bank credited it on 25 Sep 08:00 with the same reference and amount
- Finding: The clearing falls on the next business day; at 25 Sep 17:00 bank and ledger agree
- Finding: The firm claimed timing and logged DL-0001; the claim is corroborated by the 25 Sep statement, not by the claim itself
- Evidence reference: IN-10 LE-GBP-0924-0003
- Evidence reference: IN-09 BE-GBP-0925-T01
- Evidence reference: IN-08 ST-SGA-GBP-01-20260924-EOD
- Evidence reference: IN-08 ST-SGA-GBP-01-20260925-EOD
- Evidence reference: IN-07 ST-SGA-GBP-01-20260924-1700
- Evidence reference: IN-07 ST-SGA-GBP-01-20260925-1700
- Evidence reference: IN-12 AQ-GBP-20260924
- Evidence reference: IN-06 ERL-SGA-GBP-01-20260924
- Evidence reference: IN-14 DL-0001
- Missing evidence: acquirer remittance advice confirming the payout date (optional)
- Confidence: high that this is a timing difference
- Must not: mark the exception resolved
- Must not: rely on the log's TIMING label or the timing claim as proof

## 5. Expected analyst action

Confirm the timing item and record the shortfall at the 24 Sep point; confirm whether the firm's policy required an own-funds top-up at that point.

## 6. Correction and re-upload

None for this scenario (by design).

