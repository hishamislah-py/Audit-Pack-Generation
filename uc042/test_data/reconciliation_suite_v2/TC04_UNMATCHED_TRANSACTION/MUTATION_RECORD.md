# TC04 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart

**Customer label:** SYNTHETIC TEST Dunmore Payments Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | add_record | IN-09 `bank_statement_entries_2026-09.csv` | `BE-EUR-0930-U01` | (record) | absent | added after BE-EUR-0930-R01: statement_id=ST-SGA-EUR-01-20260930-EOD, account_id=SGA-EUR-01, booking_date=2026-09-30, booking_ts=2026-09-30T16:20:00+01:00, value_date=2026-09-30, amount=650.00, dc_indicator=C, currency=EUR, bank_reference=E2E-EUR-0930-U01, end_to_end_ref=E2E-EUR-0930-U01, counterparty_name=Synthetic payer (unidentified), narrative_text=INBOUND TRANSFER | unidentified inbound credit, not recorded by the firm |
| 2 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-EUR-01-20260930-EOD` | closing_balance_amount | 118555.00 | 119205.00 | statement includes the credit |
| 3 | set_field | IN-08 `bank_statements_eod_2026-09.csv` | `ST-SGA-EUR-01-20260930-EOD` | entry_count | 5 | 6 | one more entry |
| 4 | set_field | IN-07 `bank_balance_confirmations_2026-09.csv` | `ST-SGA-EUR-01-20260930-1700` | balance_amount | 118555.00 | 119205.00 | credit booked before 17:00 |
| 5 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-EUR-01-20260930` | bank_balance_reported | 118555.00 | 119205.00 | firm reports the bank balance |
| 6 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-EUR-01-20260930` | difference_reported | 0.00 | 650.00 | firm reports the difference, no timing claim |

**Unchanged on purpose:**

- IN-10 (no cash-book posting)
- IN-04 (not registered)
- IN-11 (no transaction)
- IN-05 (internal recon omitted the receipt)
- IN-14 (no investigation logged)
