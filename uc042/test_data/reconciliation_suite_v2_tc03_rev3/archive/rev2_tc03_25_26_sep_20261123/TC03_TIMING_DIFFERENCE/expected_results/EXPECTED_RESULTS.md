# TC03 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Timing difference: acquirer settlement AQ-GBP-20260925 (4,647.75) recorded 25 Sep, credited by the bank 26 Sep**

Customer label: SYNTHETIC TEST Cresswell Money Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

The acquirer settlement for Friday 25 Sep 2026 (AQ-GBP-20260925, net 4,647.75; settlement date 25 Sep per the acquirer report) was posted by the firm to its cash book at 14:00 on 25 Sep. The acquirer's funds reached the safeguarding account on Saturday 26 Sep at 08:00. At the 25 Sep 17:00 reconciliation point the bank is therefore 4,647.75 below the ledger. The firm reported the difference, claimed timing and logged it; the bank statement and 17:00 confirmation for 26 Sep evidence the clearing. By the next reconciliation day (Mon 28 Sep) bank and ledger agree.

## Evidence files involved

- IN-06 `external_recon_records_2026-09.csv` (mutated)
- IN-07 `bank_balance_confirmations_2026-09.csv` (mutated)
- IN-08 `bank_statements_eod_2026-09.csv` (mutated)
- IN-09 `bank_statement_entries_2026-09.csv` (mutated)
- IN-14 `discrepancy_log_2026-09.csv` (mutated)
- unchanged on purpose: IN-10 cash book (LE-GBP-0925-0003 posted 25 Sep 14:00)
- unchanged on purpose: IN-11 card loads of AQ-GBP-20260925
- unchanged on purpose: IN-12 AQ-GBP-20260925 (cycle and settlement date 25 Sep)
- unchanged on purpose: IN-13 lines
- unchanged on purpose: IN-03 snapshots
- unchanged on purpose: IN-05 internal records
- unchanged on purpose: IN-01 calendar (26 Sep stays WEEKEND, non-reconciliation day)
- unchanged on purpose: 28 Sep statement opening (375,461.46)

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **transaction_dates:** card loads of AQ-GBP-20260925 authorised and executed 25 Sep (IN-11)
- **processing_date:** cash book LE-GBP-0925-0003 posted 2026-09-25T14:00 (ledger D, +4,647.75)
- **settlement_date:** 2026-09-25 (IN-12 cycle_date and settlement_date)
- **bank_clearing:** BE-GBP-0926-T01 booked 2026-09-26T08:00 (Saturday), value date 2026-09-26
- **reconciliation_cut_off:** 2026-09-25 17:00 Europe/London
- **difference_at_cut_off:** bank minus ledger = -4,647.75 (reported correctly by the firm)
- **clearing_window:** existing rule D1: cleared no later than the next business day after 25 Sep (Mon 28 Sep); 26 Sep is inside it
- **next_reconciliation_day:** 28 Sep: bank 378,706.65 = ledger 378,706.65
- **expected_treatment:** explainable timing item, evidenced by the 26 Sep clearing; under existing rules the difference is still reported as an exception (FAIL) that stays OPEN awaiting human confirmation; it is never auto-resolved
- **weekend_note:** 26 Sep 2026 is a Saturday (IN-01 WEEKEND). The clearing evidence therefore requires a Saturday IN-08 statement and IN-07 17:00 confirmation; the baseline otherwise has no weekend bank records.

**Key figures**

| metric | scope | value |
|---|---|
| bank_1700|2026-09-25/SGA-GBP-01 | 370813.71 |
| bank_1700|2026-09-26/SGA-GBP-01 | 375461.46 |
| bank_1700|2026-09-28/SGA-GBP-01 | 378706.65 |
| ledger_1700|2026-09-25/SGA-GBP-01 | 375461.46 |
| ledger_1700|2026-09-26/SGA-GBP-01 | 375461.46 |
| ledger_1700|2026-09-28/SGA-GBP-01 | 378706.65 |
| requirement_1700|2026-09-25/GBP | 375461.46 |
| resource_1700|2026-09-25/GBP | 375461.46 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `BATCH_LAG AQ-GBP-20260925 settlement=2026-09-25 booked=2026-09-26`
- `BL_DIFF 2026-09-25 SGA-GBP-01 -4647.75`
- `BL_DIFF_LOGGED 2026-09-25 SGA-GBP-01 DL-0001`
- `NON_RECON_DAY_RECORD IN-07 ST-SGA-GBP-01-20260926-1700 2026-09-26`
- `NON_RECON_DAY_RECORD IN-08 ST-SGA-GBP-01-20260926-EOD 2026-09-26`
- `NON_RECON_DAY_RECORD IN-09 BE-GBP-0926-T01 2026-09-26`
- `TIMING LE-GBP-0925-0003/BE-GBP-0926-T01 ref=AQ-GBP-20260925 recorded=2026-09-25 bank=2026-09-26 amount=4647.75`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC03`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| C08-DIFFERENCE | 2026-09-25/SGA-GBP-01 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC03-01 | Critical | `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-25|-4647.75` | 1 |

- Evidence statuses: {'EXC-TC03-01': 'TIMING_EVIDENCED'}
- Investigation groups: none
- Candidate relationships (UNVERIFIED): none
- Must hold: C08 FAIL note: 'difference explained by timing: LE-GBP-0925-0003 / BE-GBP-0926-T01 (ref AQ-GBP-20260925, -4647.75, cleared 2026-09-26); cleared within one business day (D1); awaiting human confirmation; not resolved'
- Must hold: EXC-TC03-01 category 'Bank-ledger difference (explained by timing evidence, awaiting human confirmation)'; status OPEN; review AWAITING_HUMAN_REVIEW; flag OWN_FUNDS_REQUIRED (negative difference)
- Must hold: DISC-LOG PASS (DL-0001 logged)
- Must hold: C11-BATCH-BANK AQ-GBP-20260925 PASS with informational note: booked 2026-09-26, 1 business day(s) after the settlement date (within the allowance)
- Must hold: CASH-BANK-LINK LE-GBP-0925-0003 PASS; FUND-TOPUP AQ-GBP-20260925 PASS
- Must hold: C08 2026-09-28 PASS (difference cleared)
- Must hold: DQ22-CONTINUITY PASS for ST-SGA-GBP-01-20260926-EOD and ST-SGA-GBP-01-20260928-EOD; DQ23 and BC-VS-EOD PASS for 25 and 26 Sep
- Must hold: C14-COVER unaffected (weekend records are outside recon-day coverage)
- **Note:** TIMING_EVIDENCED depends on the 26 Sep IN-08 statement AND IN-07 confirmation both being present (validate.evidence_gap). Without the Saturday confirmation the predicted status is TIMING_UNVERIFIABLE.

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `PENDING:TIMING_ITEM`; gaps G-10, G-13, G-19.

- Timing item AQ-GBP-20260925 traced end to end: transaction 25 Sep, posting 25 Sep 14:00, settlement date 25 Sep, bank credit 26 Sep 08:00
- Evidence status TIMING_EVIDENCED as today; the exception stays OPEN until a human confirms; never auto-resolved
- The informational C11-BATCH-BANK lag and the C08 timing item presented as one traceable item

## 4. AI investigation expectations (separate from FIN)

- Finding: The -4,647.75 difference equals the AQ-GBP-20260925 net exactly
- Finding: The cash book recorded the credit on 25 Sep 14:00; the bank credited it on 26 Sep 08:00 with the same reference and amount
- Finding: The clearing falls within one business day; on 28 Sep bank and ledger agree
- Finding: The firm claimed timing and logged DL-0001; the claim is corroborated by the 26 Sep statement, not by the claim itself
- Evidence reference: IN-10 LE-GBP-0925-0003
- Evidence reference: IN-09 BE-GBP-0926-T01
- Evidence reference: IN-08 ST-SGA-GBP-01-20260926-EOD
- Evidence reference: IN-07 ST-SGA-GBP-01-20260926-1700
- Evidence reference: IN-12 AQ-GBP-20260925
- Evidence reference: IN-06 ERL-SGA-GBP-01-20260925
- Evidence reference: IN-14 DL-0001
- Missing evidence: acquirer remittance advice explaining the weekend payout (optional)
- Confidence: high that this is a timing difference
- Must not: mark the exception resolved
- Must not: rely on the log's TIMING label or the timing claim as proof

## 5. Expected analyst action

Confirm the timing item (accept the timing explanation) and record the shortfall at the 25 Sep point; no further action beyond confirming whether an own-funds top-up was required at the 25 Sep point per the firm's policy.

## 6. Correction and re-upload

None for this scenario (by design).

