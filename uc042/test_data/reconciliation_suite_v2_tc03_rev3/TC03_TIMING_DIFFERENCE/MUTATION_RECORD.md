# TC03 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Timing difference: acquirer settlement AQ-GBP-20260924 (5,495.05) recorded Thu 24 Sep, credited by the bank Fri 25 Sep

**Customer label:** SYNTHETIC TEST Cresswell Money Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | delete_record | IN-09 `bank_statement_entries_2026-09.csv` | `BE-GBP-0924-AQ1` | (record) | present | deleted | the bank did not credit the acquirer settlement on 24 Sep |
| 2 | add_record | IN-09 `bank_statement_entries_2026-09.csv` | `BE-GBP-0925-T01` | (record) | absent | added after BE-OWN-EUR-0924-TU1: statement_id=ST-SGA-GBP-01-20260925-EOD, account_id=SGA-GBP-01, booking_date=2026-09-25, booking_ts=2026-09-25T08:00:00+01:00, value_date=2026-09-25, amount=5495.05, dc_indicator=C, currency=GBP, bank_reference=AQ-GBP-20260924, end_to_end_ref=, counterparty_name=Synthetic Acquirer Ltd, narrative_text=CARD LOAD SETTLEMENT AQ-GBP-20260924 | clearing entry: the bank credited AQ-GBP-20260924 on Fri 25 Sep 08:00, same reference and amount |
| 3 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260924-EOD` | closing_balance_amount | 370603.29 | 365108.24 | 24 Sep statement without the acquirer credit |
| 4 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260924-EOD` | entry_count | 6 | 5 | one entry fewer on 24 Sep |
| 5 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260925-EOD` | opening_balance_amount | 370603.29 | 365108.24 | 25 Sep opening follows the 24 Sep closing |
| 6 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260925-EOD` | entry_count | 5 | 6 | clearing entry added on 25 Sep (closing unchanged) |
| 7 | set_field | IN-07 `bank_balance_confirmations_2026-09.csv` | `ST-SGA-GBP-01-20260924-1700` | balance_amount | 370603.29 | 365108.24 | 17:00 balance without the acquirer credit |
| 8 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-GBP-01-20260924` | bank_balance_reported | 370603.29 | 365108.24 | firm reports the bank balance per the 17:00 confirmation |
| 9 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-GBP-01-20260924` | difference_reported | 0.00 | -5495.05 | firm reports bank minus ledger |
| 10 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-GBP-01-20260924` | timing_difference_claimed | false | true | preparer claims timing |
| 11 | add_record | IN-14 `discrepancy_log_2026-09.csv` | `DL-0001` | (record) | absent | added: logged_ts=2026-09-24T18:05:00+01:00, recon_ref=ERL-SGA-GBP-01-20260924, account_id=SGA-GBP-01, currency=GBP, amount=-5495.05, description=Acquirer settlement AQ-GBP-20260924 not credited by the bank by 17:00; expected next business day, cause_category=TIMING, cause_evidence_ref=BE-GBP-0925-T01, funding_reference=, status=RESOLVED, resolved_ts=2026-09-25T09:00:00+01:00, approver_id=U-04 | the firm's own investigation record (follows SC2 precedent: cause_category TIMING) |

**Unchanged on purpose:**

- IN-10 cash book (LE-GBP-0924-0003 posted 24 Sep 14:00)
- IN-11 card loads of AQ-GBP-20260924
- IN-12 AQ-GBP-20260924 (cycle and settlement date 24 Sep)
- IN-13 lines
- IN-03 snapshots
- IN-05 internal records
- IN-01 calendar
- IN-07 25 Sep confirmation (375,461.46: the clearing is booked before 17:00)
- IN-08 25 Sep closing (375,461.46)
- own-funds top-up TOPUP-GBP-20260924 (still credited 24 Sep)
