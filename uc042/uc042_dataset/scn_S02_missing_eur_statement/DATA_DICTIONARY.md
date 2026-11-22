# Data dictionary — UC-042 Set 1 (clean baseline)

Generated from `uc042lib/schema.py`. All data is synthetic. Field names are POC conventions, not Moorwand's.

## Conventions

- Money: decimal strings with exactly 2 dp. `amount` columns are unsigned; `signed` columns may carry a leading `-`. No thousands separators.
- Currency: ISO 4217 (GBP, EUR). One currency per row; amounts in different currencies are never combined.
- Time: ISO 8601 with offset, Europe/London (`2026-09-08T17:00:00+01:00`).
- Requiredness: M mandatory, C conditional (rule in description), O optional.

## Sign rules (`uc042lib/money.py`, unit-tested)

| Source | Raw indicator | Signed value |
| --- | --- | --- |
| Bank balances and entries (IN-07, IN-08, IN-09) | C / D, bank perspective | C → +amount, D → −amount |
| Cash book (IN-10) | D / C, firm asset-ledger perspective | D → +amount, C → −amount |
| Transactions (IN-11) | CR / DR, client perspective | CR → +amount, DR → −amount |
| Settlement lines (IN-13) | C / D, settlement-account perspective | C → +amount, D → −amount |
| Settlement batch net (IN-12) | direction | TO_FIRM → +net, FROM_FIRM → −net |

## IN-01 `recon_calendar_2026-09.csv`

Reconciliation-day calendar

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| calendar_date | date | M | Every calendar date in the period (primary key) |
| period_id | id | M | Reporting period |
| is_recon_day | bool | M | true if reconciliation is required |
| non_recon_reason | enum | C | WEEKEND / UK_BANK_HOLIDAY / FOREIGN_MARKET_CLOSED; required when false |
| calendar_basis | str | M | Synthetic basis statement |

## IN-02 `account_inventory.csv`

Institution and account inventory

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| account_id | id | M | Account key |
| account_class | enum | M | RELEVANT_FUNDS_BANK or OWN_FUNDS |
| currency | ccy | M | Account currency |
| asset_pool_id | id | C | Required for RELEVANT_FUNDS_BANK |
| account_number_masked | str | M | Masked synthetic number |
| designation_name | str | C | Account name as designated; required for safeguarding accounts |
| acknowledgement_letter_ref | str | C | Reference printed on the acknowledgement letter PDF |
| institution_id | id | M | Institution key |
| institution_full_name | str | M | Fictional institution name |
| institution_postal_address | str | M | Fictional address |
| institution_email | str | M | Fictional email |
| institution_phone | str | M | Fictional phone |
| institution_role | enum | M | RELEVANT_FUNDS_BANK |
| open_date | date | M | Account opening date |
| close_date | date | O | Blank if open |

## IN-03 `client_balance_snapshots_2026-09.csv`

Client balance snapshots at each 17:00 point

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| snapshot_id | id | M | Key |
| recon_date | date | M | Reconciliation day |
| as_at_ts | ts | M | Snapshot time; must equal the reconciliation point |
| client_id | id | M | Client |
| asset_pool_id | id | M | Pool |
| currency | ccy | M | Currency |
| balance | signed | M | Individual safeguarding balance as per client ledger |

## IN-04 `unallocated_register_2026-09.csv`

Unallocated receipts register

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| receipt_id | id | M | Key |
| bank_reference | str | M | end_to_end_ref of the bank credit |
| receipt_date | date | M | Day received |
| receipt_ts | ts | M | Time received |
| amount | amount | M | Amount received |
| currency | ccy | M | Currency |
| classification | enum | M | UNALLOCATED or UNIDENTIFIED |
| identified_date | date | C | If first unidentified |
| allocated_date | date | C | Blank while open |
| allocated_ts | ts | C | Blank while open |
| client_id | id | C | Client once allocated |

## IN-05 `internal_recon_records_2026-09.csv`

Internal reconciliation records (as reported by the firm)

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| recon_run_id | id | M | Key |
| recon_date | date | M | Reconciliation day |
| reconciliation_point_ts | ts | M | Point the records were taken at |
| performed_at_ts | ts | M | When the reconciliation was carried out |
| asset_pool_id | id | M | Pool |
| currency | ccy | M | Currency (per-currency convention) |
| method | enum | M | STANDARD |
| requirement_reported | signed | M | Reported safeguarding requirement |
| resource_reported | signed | M | Reported safeguarding resource |
| item_a | signed | M | Reported item A (relevant funds bank accounts, ledger values) |
| item_b | signed | M | Reported item B |
| item_c | signed | M | Reported item C |
| item_d | signed | M | Reported item D |
| difference_reported | signed | M | Reported resource minus requirement |
| d1_requirement | signed | C | Blank: D+1 comparison excluded (CASS 15.8.13R basis, see gaps G-R05) |
| d1_resource | signed | C | Blank, as above |
| actions_taken_text | str | M | Actions taken |
| preparer_id | id | M | Preparer |
| reviewer_id | id | O | Reviewer |

## IN-06 `external_recon_records_2026-09.csv`

External reconciliation records (as reported by the firm)

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| ext_recon_id | id | M | Key |
| recon_date | date | M | Reconciliation day |
| performed_at_ts | ts | M | When carried out |
| account_id | id | M | Safeguarding account |
| currency | ccy | M | Currency |
| ledger_balance_reported | signed | M | Firm's ledger balance as reported |
| bank_statement_id | id | M | Statement the firm says it used (IN-07) |
| bank_balance_reported | signed | M | Bank balance as reported |
| difference_reported | signed | M | Bank minus ledger as reported |
| timing_difference_claimed | bool | M | Preparer's claim |
| preparer_id | id | M | Preparer |

## IN-07 `bank_balance_confirmations_2026-09.csv`

Bank balance confirmations at 17:00

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| statement_id | id | M | Key |
| account_id | id | M | Safeguarding account |
| as_at_ts | ts | M | 17:00 point |
| currency | ccy | M | Currency |
| balance_amount | amount | M | Balance as stated by the bank (unsigned) |
| balance_dc_indicator | enum | M | C = in credit to account holder (bank perspective) |
| bank_statement_ref | str | O | Bank's reference |

## IN-08 `bank_statements_eod_2026-09.csv`

End-of-day bank statement headers

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| statement_id | id | M | Key |
| account_id | id | M | Account |
| statement_date | date | M | Statement date |
| as_at_ts | ts | M | End of day |
| currency | ccy | M | Currency |
| opening_balance_amount | amount | M | Opening balance (unsigned) |
| opening_balance_dc | enum | M | C / D, bank perspective |
| closing_balance_amount | amount | M | Closing balance (unsigned) |
| closing_balance_dc | enum | M | C / D, bank perspective |
| entry_count | int | M | Number of entries in IN-09 for this statement |
| bank_statement_ref | str | O | Bank's reference |

## IN-09 `bank_statement_entries_2026-09.csv`

Bank statement entries

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| bank_entry_id | id | M | Key |
| statement_id | id | M | Parent EOD statement |
| account_id | id | M | Account |
| booking_date | date | M | Booking date |
| booking_ts | ts | M | Booking time |
| value_date | date | M | Value date |
| amount | amount | M | Unsigned amount |
| dc_indicator | enum | M | C = money in, D = money out (bank perspective) |
| currency | ccy | M | Currency |
| bank_reference | str | M | Reference carried by the bank |
| end_to_end_ref | str | C | Required for bank loads and redemptions |
| counterparty_name | str | O | Fictional |
| narrative_text | str | O | Free text, never authoritative |

## IN-10 `sga_cashbook_entries_2026-09.csv`

Safeguarding-account cash book (firm ledger)

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| ledger_entry_id | id | M | Key |
| account_id | id | M | Safeguarding account |
| posted_ts | ts | M | Posting time; entries at or before 17:00 count for that day |
| entry_type | enum | M | OPENING_BALANCE / BANK_LOAD / UNALLOCATED_RECEIPT / ACQUIRER_SETTLEMENT / OWN_FUNDS_TOPUP / SCHEME_SETTLEMENT / REDEMPTION |
| amount | amount | M | Unsigned amount |
| dc_indicator | enum | M | D = money in, C = money out (firm asset-ledger perspective) |
| currency | ccy | M | Currency |
| payment_reference | str | M | Equals the bank entry's bank_reference or end_to_end_ref; OPENING for opening rows |

## IN-11 `transactions_2026-09.csv`

Client transactions

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| txn_id | id | M | Key |
| client_id | id | M | Client |
| txn_type | enum | M | LOAD_BANK / LOAD_CARD / SPEND / REDEMPTION / REFUND |
| status | enum | M | SETTLED / EXECUTED |
| auth_ts | ts | C | Card authorisation time |
| clearing_date | date | C | Card clearing date |
| executed_ts | ts | M | When the client balance changed (convention D8) |
| amount | amount | M | Unsigned amount |
| direction | enum | M | CR increases client balance, DR decreases |
| currency | ccy | M | Currency |
| settlement_batch_id | id | C | Required for LOAD_CARD, SPEND, REFUND |
| payment_reference | str | C | Required for LOAD_BANK and REDEMPTION; equals bank end_to_end_ref |
| original_txn_id | id | C | Required for REFUND |

## IN-12 `settlement_batches_2026-09.csv`

Settlement batch headers (generic synthetic format)

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| batch_id | id | M | Key |
| counterparty_type | enum | M | SCHEME or ACQUIRER |
| cycle_date | date | M | Cycle date per report |
| settlement_date | date | M | Settlement date per report |
| account_id | id | M | Settlement account |
| currency | ccy | M | Currency |
| direction | enum | M | TO_FIRM or FROM_FIRM |
| gross_amount | amount | M | Reported gross (unsigned) |
| total_fees | amount | M | Reported fees (unsigned) |
| total_adjustments | amount | M | Reported refunds/adjustments (unsigned) |
| net_amount_reported | amount | M | Reported net (unsigned) |
| expected_bank_reference | str | M | Reference the bank entry should carry |

## IN-13 `settlement_lines_2026-09.csv`

Settlement batch lines

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| line_id | id | M | Key |
| batch_id | id | M | Parent batch |
| line_type | enum | M | TXN / FEE / REFUND |
| txn_id | id | C | Required for TXN and REFUND |
| fee_code | str | C | Required for FEE: ACQ_FEE or SCHEME_FEE |
| amount | amount | M | Unsigned amount |
| dc_indicator | enum | M | C = money to the firm, D = money from the firm |
| currency | ccy | M | Currency |

## IN-14 `discrepancy_log_2026-09.csv`

Discrepancy and corrective-action log

| Column | Type | Req | Meaning |
| --- | --- | --- | --- |
| discrepancy_id | id | M | Key |
| logged_ts | ts | M | When logged |
| recon_ref | id | M | IN-05 or IN-06 record |
| account_id | id | M | Account |
| currency | ccy | M | Currency |
| amount | signed | M | Difference amount |
| description | str | M | Description |
| cause_category | enum | O | Cause, if evidenced |
| cause_evidence_ref | str | O | Evidence for the cause |
| funding_reference | str | O | Own-funds transfer reference |
| status | enum | M | OPEN / RESOLVED |
| resolved_ts | ts | O | When resolved |
| approver_id | id | O | Approver |

## Supporting documents (PDF)

Each PDF has a **Key details** block of `Label: value` lines, parsed deterministically by the validator.

| File ID | File | Requirement | Key details |
| --- | --- | --- | --- |
| IN-15 | `ack_letter_SGA-GBP-01.pdf` | REQUIRED | Letter reference, Institution, Account name, Account number, Currency, Letter date |
| IN-16 | `ack_letter_SGA-EUR-01.pdf` | REQUIRED | Letter reference, Institution, Account name, Account number, Currency, Letter date |
| IN-17 | `safeguarding_reconciliation_policy_v1.2.pdf` | REQUIRED | Document version, Effective date, Safeguarding method, Reconciliation method, Reconciliation point, Frequency, Internal reconciliation basis |
| IN-18 | `governance_register_2026-09.pdf` | OPTIONAL | Accountable person, Role, Allocated from |
| IN-19 | `rep027_submission_receipt_2026-08.pdf` | OPTIONAL | Return, Period, Due date, Submitted at, Submission reference |
