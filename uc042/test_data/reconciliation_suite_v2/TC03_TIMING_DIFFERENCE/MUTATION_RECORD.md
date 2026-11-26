# TC03 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Timing difference: acquirer settlement AQ-GBP-20260925 (4,647.75) recorded 25 Sep, credited by the bank 26 Sep

**Customer label:** SYNTHETIC TEST Cresswell Money Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | delete_record | IN-09 `bank_statement_entries_2026-09.csv` | `BE-GBP-0925-AQ1` | (record) | present | deleted | the bank did not credit the acquirer settlement on 25 Sep |
| 2 | add_record | IN-09 `bank_statement_entries_2026-09.csv` | `BE-GBP-0926-T01` | (record) | absent | added after BE-GBP-0925-SB1: statement_id=ST-SGA-GBP-01-20260926-EOD, account_id=SGA-GBP-01, booking_date=2026-09-26, booking_ts=2026-09-26T08:00:00+01:00, value_date=2026-09-26, amount=4647.75, dc_indicator=C, currency=GBP, bank_reference=AQ-GBP-20260925, end_to_end_ref=, counterparty_name=Synthetic Acquirer Ltd, narrative_text=CARD LOAD SETTLEMENT AQ-GBP-20260925 | clearing entry: the bank credited AQ-GBP-20260925 on Sat 26 Sep 08:00, same reference and amount |
| 3 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260925-EOD` | closing_balance_amount | 375461.46 | 370813.71 | 25 Sep statement without the acquirer credit |
| 4 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260925-EOD` | entry_count | 5 | 4 | one entry fewer on 25 Sep |
| 5 | add_record | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-GBP-01-20260926-EOD` | (record) | absent | added after ST-SGA-GBP-01-20260925-EOD: account_id=SGA-GBP-01, statement_date=2026-09-26, as_at_ts=2026-09-26T23:59:59+01:00, currency=GBP, opening_balance_amount=370813.71, opening_balance_dc=C, closing_balance_amount=375461.46, closing_balance_dc=C, entry_count=1, bank_statement_ref=EOD/SGA-GBP-01/20260926 | Saturday 26 Sep statement carrying the clearing entry (subsequent clearing evidence) |
| 6 | set_field | IN-07 `bank_balance_confirmations_2026-09.csv` | `ST-SGA-GBP-01-20260925-1700` | balance_amount | 375461.46 | 370813.71 | 17:00 balance without the acquirer credit |
| 7 | add_record | IN-07 `bank_balance_confirmations_2026-09.csv` | `ST-SGA-GBP-01-20260926-1700` | (record) | absent | added after ST-SGA-EUR-01-20260925-1700: account_id=SGA-GBP-01, as_at_ts=2026-09-26T17:00:00+01:00, currency=GBP, balance_amount=375461.46, balance_dc_indicator=C, bank_statement_ref=BC/SGA-GBP-01/20260926 | Saturday 26 Sep 17:00 confirmation (makes the clearing day's bank evidence complete) |
| 8 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-GBP-01-20260925` | bank_balance_reported | 375461.46 | 370813.71 | firm reports the bank balance per the 17:00 confirmation |
| 9 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-GBP-01-20260925` | difference_reported | 0.00 | -4647.75 | firm reports bank minus ledger |
| 10 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-GBP-01-20260925` | timing_difference_claimed | false | true | preparer claims timing |
| 11 | add_record | IN-14 `discrepancy_log_2026-09.csv` | `DL-0001` | (record) | absent | added: logged_ts=2026-09-25T18:05:00+01:00, recon_ref=ERL-SGA-GBP-01-20260925, account_id=SGA-GBP-01, currency=GBP, amount=-4647.75, description=Acquirer settlement AQ-GBP-20260925 not credited by the bank by 17:00; expected next banking day, cause_category=TIMING, cause_evidence_ref=BE-GBP-0926-T01, funding_reference=, status=RESOLVED, resolved_ts=2026-09-28T09:00:00+01:00, approver_id=U-04 | the firm's own investigation record (follows SC2 precedent: cause_category TIMING) |

**Unchanged on purpose:**

- IN-10 cash book (LE-GBP-0925-0003 posted 25 Sep 14:00)
- IN-11 card loads of AQ-GBP-20260925
- IN-12 AQ-GBP-20260925 (cycle and settlement date 25 Sep)
- IN-13 lines
- IN-03 snapshots
- IN-05 internal records
- IN-01 calendar (26 Sep stays WEEKEND, non-reconciliation day)
- 28 Sep statement opening (375,461.46)
