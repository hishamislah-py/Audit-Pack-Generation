# UC-042 Schema and Field Reference

Generated on 18 Nov 2026 directly from `uc042lib/schema.py` (CSV_FILES, PDF_FILES, ENUMS, CONDITIONAL, EMPTY_ALLOWED, SCOPE_FILES, PERIOD_RULES), `uc042lib/period.py` (FILE_PATTERNS) and `uc042lib/structure.py` (field formats) of `p10/uc042_token_optimisation`. Nothing here is hand-copied from documentation; the per-file notes were verified against `uc042lib/validate.py` and are referenced in `UC042_CROSS_DOCUMENT_VALIDATION.md`.

## Rules common to every CSV

| Rule | Behaviour | Source |
|---|---|---|
| Header | Must equal the schema column list **exactly**: same names, case, order, count. No aliases, no trimming, no reordering. | `prepare.identify` (`header == schema.columns(fid)`), `validate.load_csv` |
| Encoding | UTF-8; a leading BOM is accepted (`utf-8-sig`). Anything else is rejected (UNRECOGNISED). | `structure.read_csv` |
| Dialect | Python `csv` default (excel): comma delimiter, `"` quoting, doubled quotes inside quoted fields; LF or CRLF. | `structure.read_csv` |
| Blank lines | Fully empty lines are skipped by `csv.DictReader`. | Python csv |
| Row width | A row with more or fewer fields than the header is invalid ("wrong number of fields") and excluded. | `structure.check_rows` |
| Whitespace | Values are **not** trimmed for validation: ` 10.00` fails the amount rule; ` GBP` fails ccy. | `structure.check_rows` |
| Empty value | Empty string = missing. Mandatory (M) empty -> row invalid. Conditional (C) empty when its condition holds -> row invalid. Optional/Conditional empty otherwise -> accepted. | `structure.check_rows` |
| Primary key | The **first column** is the key. A later duplicate key is excluded (first kept), DQ09. | `structure.check_rows` |
| Invalid row | Excluded from all calculations, reported as DQ-FIELD FAIL; its scope (account, currency, date, batch, client, refs) taints dependent checks to INSUFFICIENT_EVIDENCE. | `validate.load_csv`, `structure.taint_scope`, `Validator.tainted` |
| Row validation timing | Field types/enums/conditions are checked by the **engine after Submit for Audit**, not by the ZIP gate. The gate only reads headers, row counts and date fields. | `ingest/analysis.analyse_csv` vs `structure.check_rows` |
| Empty file | 0 data rows is an intake ERROR (blocks the gate) except IN-04 and IN-14. | `analysis.analyse_csv` NO_RECORDS, `schema.EMPTY_ALLOWED` |

### Field types

| Type | Accepted format |
|---|---|
| `id` | identifier: `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` (letter/digit first; letters, digits, `.` `_` `:` `-`; max 64) |
| `str` | free text (any UTF-8; not validated) |
| `date` | `YYYY-MM-DD` (regex `^\d{4}-\d{2}-\d{2}$` + real calendar date) |
| `ts` | ISO 8601 date-time **with explicit UTC offset**, parsed by Python 3.11 `datetime.fromisoformat`; e.g. `2026-09-15T17:00:00+01:00` |
| `bool` | `true` or `false` (lower case only) |
| `int` | digits only `^\d+$` |
| `amount` | unsigned, exactly 2 dp, `.` decimal: `^\d+\.\d{2}$` (no sign, separators, symbols, spaces) |
| `signed` | as amount with optional leading `-`: `^-?\d+\.\d{2}$` |
| `ccy` | `GBP` or `EUR` only |
| `enum` | one of the allowed values below (case-sensitive) |

Money sign conventions (`uc042lib/money.py`): bank C=+ / D=-; cash book D=+ / C=-; transactions CR=+ / DR=-; settlement lines C=+ / D=-; batch net TO_FIRM=+ / FROM_FIRM=-. Amounts are compared exactly as `Decimal`, no tolerance, no rounding (rounding exists only for generator fees, half-up).

Timestamps are compared as instants; period membership uses the **Europe/London local date** of a timestamp (`structure._local_date`). Date-type fields recognised for tainting: statement_date, booking_date, recon_date, settlement_date, calendar_date, receipt_date, cycle_date, value_date; timestamp fields: posted_ts, executed_ts, as_at_ts, booking_ts, receipt_ts, logged_ts, reconciliation_point_ts; reference fields: bank_reference, end_to_end_ref, payment_reference, expected_bank_reference, recon_ref.

## IN-01: Reconciliation-day calendar

- **File name (September 2026):** `recon_calendar_2026-09.csv`; pattern `recon_calendar_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `calendar_date`
- **Exact header:** `calendar_date,period_id,is_recon_day,non_recon_reason,calendar_basis`
- **Reporting-period rule:** `{'in_period': ['calendar_date'], 'equals': {'period_id': 'PER-2026-09'}}`
- **Notes:** Scope file (SCOPE_FILES): any invalid row makes the whole file UNUSABLE. Every calendar day of the month exactly once. `period_id` must equal the package period (intake WRONG_PERIOD ERROR otherwise). Days with `is_recon_day=true` drive every coverage check.

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `calendar_date` | date | Mandatory | - | Every calendar date in the period (primary key) |
| 2 | `period_id` | id | Mandatory | - | Reporting period |
| 3 | `is_recon_day` | bool | Mandatory | - | true if reconciliation is required |
| 4 | `non_recon_reason` | enum | Conditional | `FOREIGN_MARKET_CLOSED`, `UK_BANK_HOLIDAY`, `WEEKEND`; required when: required when is_recon_day is false | WEEKEND / UK_BANK_HOLIDAY / FOREIGN_MARKET_CLOSED; required when false |
| 5 | `calendar_basis` | str | Mandatory | - | Synthetic basis statement |

## IN-02: Institution and account inventory

- **File name (September 2026):** `account_inventory.csv`; pattern `account_inventory.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `account_id`
- **Exact header:** `account_id,account_class,currency,asset_pool_id,account_number_masked,designation_name,acknowledgement_letter_ref,institution_id,institution_full_name,institution_postal_address,institution_email,institution_phone,institution_role,open_date,close_date`
- **Reporting-period rule:** none (standing data)
- **Notes:** Scope file: any invalid row makes the whole file UNUSABLE. Standing data (no month in the file name). Safeguarding accounts SGA-GBP-01 and SGA-EUR-01 are hard-wired to the letter slots IN-15/IN-16 (schema.LETTER_SLOTS). Every account listed gets an EOD statement coverage check (C14 IN-08) on every reconciliation day.

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `account_id` | id | Mandatory | - | Account key |
| 2 | `account_class` | enum | Mandatory | `OWN_FUNDS`, `RELEVANT_FUNDS_BANK` | RELEVANT_FUNDS_BANK or OWN_FUNDS |
| 3 | `currency` | ccy | Mandatory | - | Account currency |
| 4 | `asset_pool_id` | id | Conditional | required when: required for safeguarding accounts | Required for RELEVANT_FUNDS_BANK |
| 5 | `account_number_masked` | str | Mandatory | - | Masked synthetic number |
| 6 | `designation_name` | str | Conditional | required when: required for safeguarding accounts | Account name as designated; required for safeguarding accounts |
| 7 | `acknowledgement_letter_ref` | str | Conditional | required when: required for safeguarding accounts | Reference printed on the acknowledgement letter PDF |
| 8 | `institution_id` | id | Mandatory | - | Institution key |
| 9 | `institution_full_name` | str | Mandatory | - | Fictional institution name |
| 10 | `institution_postal_address` | str | Mandatory | - | Fictional address |
| 11 | `institution_email` | str | Mandatory | - | Fictional email |
| 12 | `institution_phone` | str | Mandatory | - | Fictional phone |
| 13 | `institution_role` | enum | Mandatory | `RELEVANT_FUNDS_BANK` | RELEVANT_FUNDS_BANK |
| 14 | `open_date` | date | Mandatory | - | Account opening date |
| 15 | `close_date` | date | Optional | - | Blank if open |

## IN-03: Client balance snapshots at each 17:00 point

- **File name (September 2026):** `client_balance_snapshots_2026-09.csv`; pattern `client_balance_snapshots_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `snapshot_id`
- **Exact header:** `snapshot_id,recon_date,as_at_ts,client_id,asset_pool_id,currency,balance`
- **Reporting-period rule:** `{'in_period': ['recon_date'], 'permitted': [{'recon_date': '2026-08-31', 'as_at_ts': '2026-08-31T17:00:00+01:00'}]}`
- **Notes:** One snapshot per client per currency per reconciliation day (C14). Opening boundary rows at the previous month-end 17:00 point are permitted. `as_at_ts` must equal the policy point for `recon_date` (C03-POINT).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `snapshot_id` | id | Mandatory | - | Key |
| 2 | `recon_date` | date | Mandatory | - | Reconciliation day |
| 3 | `as_at_ts` | ts | Mandatory | - | Snapshot time; must equal the reconciliation point |
| 4 | `client_id` | id | Mandatory | - | Client |
| 5 | `asset_pool_id` | id | Mandatory | - | Pool |
| 6 | `currency` | ccy | Mandatory | - | Currency |
| 7 | `balance` | signed | Mandatory | - | Individual safeguarding balance as per client ledger |

## IN-04: Unallocated receipts register

- **File name (September 2026):** `unallocated_register_2026-09.csv`; pattern `unallocated_register_{period}.csv`
- **Required:** yes (every CSV is REQUIRED); may contain zero data rows
- **Primary key:** `receipt_id`
- **Exact header:** `receipt_id,bank_reference,receipt_date,receipt_ts,amount,currency,classification,identified_date,allocated_date,allocated_ts,client_id`
- **Reporting-period rule:** `{'open_during_period': {'start': ['receipt_date', 'receipt_ts'], 'end': ['allocated_date', 'allocated_ts']}}`
- **Notes:** May be header-only (EMPTY_ALLOWED). Belongs to the period if open at some point in it.

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `receipt_id` | id | Mandatory | - | Key |
| 2 | `bank_reference` | str | Mandatory | - | end_to_end_ref of the bank credit |
| 3 | `receipt_date` | date | Mandatory | - | Day received |
| 4 | `receipt_ts` | ts | Mandatory | - | Time received |
| 5 | `amount` | amount | Mandatory | - | Amount received |
| 6 | `currency` | ccy | Mandatory | - | Currency |
| 7 | `classification` | enum | Mandatory | `UNALLOCATED`, `UNIDENTIFIED` | UNALLOCATED or UNIDENTIFIED |
| 8 | `identified_date` | date | Conditional | conditional in the description only: **not enforced** by code | If first unidentified |
| 9 | `allocated_date` | date | Conditional | conditional in the description only: **not enforced** by code | Blank while open |
| 10 | `allocated_ts` | ts | Conditional | required when: required when allocated_date is set | Blank while open |
| 11 | `client_id` | id | Conditional | required when: required when allocated_date is set | Client once allocated |

## IN-05: Internal reconciliation records (as reported by the firm)

- **File name (September 2026):** `internal_recon_records_2026-09.csv`; pattern `internal_recon_records_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `recon_run_id`
- **Exact header:** `recon_run_id,recon_date,reconciliation_point_ts,performed_at_ts,asset_pool_id,currency,method,requirement_reported,resource_reported,item_a,item_b,item_c,item_d,difference_reported,d1_requirement,d1_resource,actions_taken_text,preparer_id,reviewer_id`
- **Reporting-period rule:** `{'in_period': ['recon_date']}`
- **Notes:** One record per reconciliation day per safeguarding currency (C01). `reconciliation_point_ts` must equal the policy point (C03-POINT).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `recon_run_id` | id | Mandatory | - | Key |
| 2 | `recon_date` | date | Mandatory | - | Reconciliation day |
| 3 | `reconciliation_point_ts` | ts | Mandatory | - | Point the records were taken at |
| 4 | `performed_at_ts` | ts | Mandatory | - | When the reconciliation was carried out |
| 5 | `asset_pool_id` | id | Mandatory | - | Pool |
| 6 | `currency` | ccy | Mandatory | - | Currency (per-currency convention) |
| 7 | `method` | enum | Mandatory | `NON_STANDARD`, `STANDARD` | STANDARD |
| 8 | `requirement_reported` | signed | Mandatory | - | Reported safeguarding requirement |
| 9 | `resource_reported` | signed | Mandatory | - | Reported safeguarding resource |
| 10 | `item_a` | signed | Mandatory | - | Reported item A (relevant funds bank accounts, ledger values) |
| 11 | `item_b` | signed | Mandatory | - | Reported item B |
| 12 | `item_c` | signed | Mandatory | - | Reported item C |
| 13 | `item_d` | signed | Mandatory | - | Reported item D |
| 14 | `difference_reported` | signed | Mandatory | - | Reported resource minus requirement |
| 15 | `d1_requirement` | signed | Conditional | conditional in the description only: **not enforced** by code | Blank: D+1 comparison excluded (CASS 15.8.13R basis, see gaps G-R05) |
| 16 | `d1_resource` | signed | Conditional | conditional in the description only: **not enforced** by code | Blank, as above |
| 17 | `actions_taken_text` | str | Mandatory | - | Actions taken |
| 18 | `preparer_id` | id | Mandatory | - | Preparer |
| 19 | `reviewer_id` | id | Optional | - | Reviewer |

## IN-06: External reconciliation records (as reported by the firm)

- **File name (September 2026):** `external_recon_records_2026-09.csv`; pattern `external_recon_records_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `ext_recon_id`
- **Exact header:** `ext_recon_id,recon_date,performed_at_ts,account_id,currency,ledger_balance_reported,bank_statement_id,bank_balance_reported,difference_reported,timing_difference_claimed,preparer_id`
- **Reporting-period rule:** `{'in_period': ['recon_date']}`
- **Notes:** One record per reconciliation day per safeguarding account (C07). `ext_recon_id` must follow `ERL-<account_id>-<YYYYMMDD>` for the discrepancy log to be linked (hidden contract, validate.py _group_exceptions).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `ext_recon_id` | id | Mandatory | - | Key |
| 2 | `recon_date` | date | Mandatory | - | Reconciliation day |
| 3 | `performed_at_ts` | ts | Mandatory | - | When carried out |
| 4 | `account_id` | id | Mandatory | - | Safeguarding account |
| 5 | `currency` | ccy | Mandatory | - | Currency |
| 6 | `ledger_balance_reported` | signed | Mandatory | - | Firm's ledger balance as reported |
| 7 | `bank_statement_id` | id | Mandatory | - | Statement the firm says it used (IN-07) |
| 8 | `bank_balance_reported` | signed | Mandatory | - | Bank balance as reported |
| 9 | `difference_reported` | signed | Mandatory | - | Bank minus ledger as reported |
| 10 | `timing_difference_claimed` | bool | Mandatory | - | Preparer's claim |
| 11 | `preparer_id` | id | Mandatory | - | Preparer |

## IN-07: Bank balance confirmations at 17:00

- **File name (September 2026):** `bank_balance_confirmations_2026-09.csv`; pattern `bank_balance_confirmations_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `statement_id`
- **Exact header:** `statement_id,account_id,as_at_ts,currency,balance_amount,balance_dc_indicator,bank_statement_ref`
- **Reporting-period rule:** `{'in_period': ['as_at_ts']}`
- **Notes:** One confirmation per reconciliation day per safeguarding account (C14). Local time of `as_at_ts` must be the policy point (17:00). Referenced by IN-06.bank_statement_id.

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `statement_id` | id | Mandatory | - | Key |
| 2 | `account_id` | id | Mandatory | - | Safeguarding account |
| 3 | `as_at_ts` | ts | Mandatory | - | 17:00 point |
| 4 | `currency` | ccy | Mandatory | - | Currency |
| 5 | `balance_amount` | amount | Mandatory | - | Balance as stated by the bank (unsigned) |
| 6 | `balance_dc_indicator` | enum | Mandatory | `C`, `D` | C = in credit to account holder (bank perspective) |
| 7 | `bank_statement_ref` | str | Optional | - | Bank's reference |

## IN-08: End-of-day bank statement headers

- **File name (September 2026):** `bank_statements_eod_2026-09.csv`; pattern `bank_statements_eod_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `statement_id`
- **Exact header:** `statement_id,account_id,statement_date,as_at_ts,currency,opening_balance_amount,opening_balance_dc,closing_balance_amount,closing_balance_dc,entry_count,bank_statement_ref`
- **Reporting-period rule:** `{'in_period': ['statement_date']}`
- **Notes:** One EOD statement per reconciliation day per account in IN-02 (all four, including own-funds accounts).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `statement_id` | id | Mandatory | - | Key |
| 2 | `account_id` | id | Mandatory | - | Account |
| 3 | `statement_date` | date | Mandatory | - | Statement date |
| 4 | `as_at_ts` | ts | Mandatory | - | End of day |
| 5 | `currency` | ccy | Mandatory | - | Currency |
| 6 | `opening_balance_amount` | amount | Mandatory | - | Opening balance (unsigned) |
| 7 | `opening_balance_dc` | enum | Mandatory | `C`, `D` | C / D, bank perspective |
| 8 | `closing_balance_amount` | amount | Mandatory | - | Closing balance (unsigned) |
| 9 | `closing_balance_dc` | enum | Mandatory | `C`, `D` | C / D, bank perspective |
| 10 | `entry_count` | int | Mandatory | - | Number of entries in IN-09 for this statement |
| 11 | `bank_statement_ref` | str | Optional | - | Bank's reference |

## IN-09: Bank statement entries

- **File name (September 2026):** `bank_statement_entries_2026-09.csv`; pattern `bank_statement_entries_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `bank_entry_id`
- **Exact header:** `bank_entry_id,statement_id,account_id,booking_date,booking_ts,value_date,amount,dc_indicator,currency,bank_reference,end_to_end_ref,counterparty_name,narrative_text`
- **Reporting-period rule:** `{'in_period': ['booking_date', 'booking_ts']}`
- **Notes:** Child of IN-08 via `statement_id`; `booking_date`, `account_id`, `currency` must equal the parent statement's.

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `bank_entry_id` | id | Mandatory | - | Key |
| 2 | `statement_id` | id | Mandatory | - | Parent EOD statement |
| 3 | `account_id` | id | Mandatory | - | Account |
| 4 | `booking_date` | date | Mandatory | - | Booking date |
| 5 | `booking_ts` | ts | Mandatory | - | Booking time |
| 6 | `value_date` | date | Mandatory | - | Value date |
| 7 | `amount` | amount | Mandatory | - | Unsigned amount |
| 8 | `dc_indicator` | enum | Mandatory | `C`, `D` | C = money in, D = money out (bank perspective) |
| 9 | `currency` | ccy | Mandatory | - | Currency |
| 10 | `bank_reference` | str | Mandatory | - | Reference carried by the bank |
| 11 | `end_to_end_ref` | str | Conditional | conditional in the description only: **not enforced** by code | Required for bank loads and redemptions |
| 12 | `counterparty_name` | str | Optional | - | Fictional |
| 13 | `narrative_text` | str | Optional | - | Free text, never authoritative |

## IN-10: Safeguarding-account cash book (firm ledger)

- **File name (September 2026):** `sga_cashbook_entries_2026-09.csv`; pattern `sga_cashbook_entries_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `ledger_entry_id`
- **Exact header:** `ledger_entry_id,account_id,posted_ts,entry_type,amount,dc_indicator,currency,payment_reference`
- **Reporting-period rule:** `{'in_period': ['posted_ts'], 'permitted': [{'entry_type': 'OPENING_BALANCE', 'posted_ts': '2026-08-31T17:00:00+01:00'}]}`
- **Notes:** Firm asset ledger. One OPENING_BALANCE row per safeguarding account at the previous month-end 17:00 point (permitted boundary row; required for item A).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `ledger_entry_id` | id | Mandatory | - | Key |
| 2 | `account_id` | id | Mandatory | - | Safeguarding account |
| 3 | `posted_ts` | ts | Mandatory | - | Posting time; entries at or before 17:00 count for that day |
| 4 | `entry_type` | enum | Mandatory | `ACQUIRER_SETTLEMENT`, `BANK_LOAD`, `OPENING_BALANCE`, `OWN_FUNDS_TOPUP`, `REDEMPTION`, `SCHEME_SETTLEMENT`, `UNALLOCATED_RECEIPT` | OPENING_BALANCE / BANK_LOAD / UNALLOCATED_RECEIPT / ACQUIRER_SETTLEMENT / OWN_FUNDS_TOPUP / SCHEME_SETTLEMENT / REDEMPTION |
| 5 | `amount` | amount | Mandatory | - | Unsigned amount |
| 6 | `dc_indicator` | enum | Mandatory | `C`, `D` | D = money in, C = money out (firm asset-ledger perspective) |
| 7 | `currency` | ccy | Mandatory | - | Currency |
| 8 | `payment_reference` | str | Mandatory | - | Equals the bank entry's bank_reference or end_to_end_ref; OPENING for opening rows |

## IN-11: Client transactions

- **File name (September 2026):** `transactions_2026-09.csv`; pattern `transactions_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `txn_id`
- **Exact header:** `txn_id,client_id,txn_type,status,auth_ts,clearing_date,executed_ts,amount,direction,currency,settlement_batch_id,payment_reference,original_txn_id`
- **Reporting-period rule:** `{'in_period': ['executed_ts']}`
- **Notes:** Client ledger movements; `executed_ts` decides the period and the roll-forward window.

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `txn_id` | id | Mandatory | - | Key |
| 2 | `client_id` | id | Mandatory | - | Client |
| 3 | `txn_type` | enum | Mandatory | `LOAD_BANK`, `LOAD_CARD`, `REDEMPTION`, `REFUND`, `SPEND` | LOAD_BANK / LOAD_CARD / SPEND / REDEMPTION / REFUND |
| 4 | `status` | enum | Mandatory | `EXECUTED`, `SETTLED` | SETTLED / EXECUTED |
| 5 | `auth_ts` | ts | Conditional | conditional in the description only: **not enforced** by code | Card authorisation time |
| 6 | `clearing_date` | date | Conditional | conditional in the description only: **not enforced** by code | Card clearing date |
| 7 | `executed_ts` | ts | Mandatory | - | When the client balance changed (convention D8) |
| 8 | `amount` | amount | Mandatory | - | Unsigned amount |
| 9 | `direction` | enum | Mandatory | `CR`, `DR` | CR increases client balance, DR decreases |
| 10 | `currency` | ccy | Mandatory | - | Currency |
| 11 | `settlement_batch_id` | id | Conditional | required when: required for card transactions | Required for LOAD_CARD, SPEND, REFUND |
| 12 | `payment_reference` | str | Conditional | required when: required for bank loads and redemptions | Required for LOAD_BANK and REDEMPTION; equals bank end_to_end_ref |
| 13 | `original_txn_id` | id | Conditional | required when: required for refunds | Required for REFUND |

## IN-12: Settlement batch headers (generic synthetic format)

- **File name (September 2026):** `settlement_batches_2026-09.csv`; pattern `settlement_batches_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `batch_id`
- **Exact header:** `batch_id,counterparty_type,cycle_date,settlement_date,account_id,currency,direction,gross_amount,total_fees,total_adjustments,net_amount_reported,expected_bank_reference`
- **Reporting-period rule:** `{'in_period': ['settlement_date']}`
- **Notes:** Exactly one SCHEME and one ACQUIRER batch per reconciliation day per safeguarding currency (C14; two of a type = FAIL).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `batch_id` | id | Mandatory | - | Key |
| 2 | `counterparty_type` | enum | Mandatory | `ACQUIRER`, `SCHEME` | SCHEME or ACQUIRER |
| 3 | `cycle_date` | date | Mandatory | - | Cycle date per report |
| 4 | `settlement_date` | date | Mandatory | - | Settlement date per report |
| 5 | `account_id` | id | Mandatory | - | Settlement account |
| 6 | `currency` | ccy | Mandatory | - | Currency |
| 7 | `direction` | enum | Mandatory | `FROM_FIRM`, `TO_FIRM` | TO_FIRM or FROM_FIRM |
| 8 | `gross_amount` | amount | Mandatory | - | Reported gross (unsigned) |
| 9 | `total_fees` | amount | Mandatory | - | Reported fees (unsigned) |
| 10 | `total_adjustments` | amount | Mandatory | - | Reported refunds/adjustments (unsigned) |
| 11 | `net_amount_reported` | amount | Mandatory | - | Reported net (unsigned) |
| 12 | `expected_bank_reference` | str | Mandatory | - | Reference the bank entry should carry |

## IN-13: Settlement batch lines

- **File name (September 2026):** `settlement_lines_2026-09.csv`; pattern `settlement_lines_{period}.csv`
- **Required:** yes (every CSV is REQUIRED)
- **Primary key:** `line_id`
- **Exact header:** `line_id,batch_id,line_type,txn_id,fee_code,amount,dc_indicator,currency`
- **Reporting-period rule:** none (standing data)
- **Notes:** Child of IN-12 via `batch_id`; no date fields (follows its batch).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `line_id` | id | Mandatory | - | Key |
| 2 | `batch_id` | id | Mandatory | - | Parent batch |
| 3 | `line_type` | enum | Mandatory | `FEE`, `REFUND`, `TXN` | TXN / FEE / REFUND |
| 4 | `txn_id` | id | Conditional | required when: required for TXN and REFUND lines | Required for TXN and REFUND |
| 5 | `fee_code` | str | Conditional | `ACQ_FEE`, `SCHEME_FEE`; required when: required for FEE lines | Required for FEE: ACQ_FEE or SCHEME_FEE |
| 6 | `amount` | amount | Mandatory | - | Unsigned amount |
| 7 | `dc_indicator` | enum | Mandatory | `C`, `D` | C = money to the firm, D = money from the firm |
| 8 | `currency` | ccy | Mandatory | - | Currency |

## IN-14: Discrepancy and corrective-action log

- **File name (September 2026):** `discrepancy_log_2026-09.csv`; pattern `discrepancy_log_{period}.csv`
- **Required:** yes (every CSV is REQUIRED); may contain zero data rows
- **Primary key:** `discrepancy_id`
- **Exact header:** `discrepancy_id,logged_ts,recon_ref,account_id,currency,amount,description,cause_category,cause_evidence_ref,funding_reference,status,resolved_ts,approver_id`
- **Reporting-period rule:** `{'event_ref': {'field': 'recon_ref', 'sources': {'IN-05': 'recon_run_id', 'IN-06': 'ext_recon_id'}, 'date_field': 'recon_date'}, 'not_before_event': ['logged_ts'], 'subsequent_after_end': ['logged_ts']}`
- **Notes:** May be header-only (EMPTY_ALLOWED). Period follows the referenced reconciliation (`recon_ref` -> IN-05.recon_run_id or IN-06.ext_recon_id).

| # | Column | Type | Req. | Allowed values / condition | Description |
|---|---|---|---|---|---|
| 1 | `discrepancy_id` | id | Mandatory | - | Key |
| 2 | `logged_ts` | ts | Mandatory | - | When logged |
| 3 | `recon_ref` | id | Mandatory | - | IN-05 or IN-06 record |
| 4 | `account_id` | id | Mandatory | - | Account |
| 5 | `currency` | ccy | Mandatory | - | Currency |
| 6 | `amount` | signed | Mandatory | - | Difference amount |
| 7 | `description` | str | Mandatory | - | Description |
| 8 | `cause_category` | enum | Optional | **no allowed-value list in schema.ENUMS: any non-empty value passes** (UNKNOWN business list) | Cause, if evidenced |
| 9 | `cause_evidence_ref` | str | Optional | - | Evidence for the cause |
| 10 | `funding_reference` | str | Optional | - | Own-funds transfer reference |
| 11 | `status` | enum | Mandatory | `OPEN`, `RESOLVED` | OPEN / RESOLVED |
| 12 | `resolved_ts` | ts | Optional | - | When resolved |
| 13 | `approver_id` | id | Optional | - | Approver |

## PDF evidence (IN-15 to IN-19)

Identification and parsing (`prepare._pdf_details`, `validate.load_pdf`): the file must start with `%PDF-` and be readable by `pypdf`; text is extracted from every page and each key detail is found with the regex `^<Label>: (.+)$` (multi-line mode). The label must start a line, be followed by exactly `: ` and the value must sit on the same extracted line. A PDF is a candidate for a type only if **all** of that type's labels are found. Missing labels: intake REJECT (UNRECOGNISED) / engine V01-PDF FAIL (file unusable).

| ID | File name (Sep 2026) | Requirement | Key-detail labels (all required) | Value rules enforced by code |
|---|---|---|---|---|
| IN-15 | `ack_letter_SGA-GBP-01.pdf` | REQUIRED | `Letter reference`, `Institution`, `Account name`, `Account number`, `Currency`, `Letter date` | Slot chosen by `Letter reference` = IN-02.acknowledgement_letter_ref of SGA-GBP-01. C10: Letter reference, Account number (= account_number_masked), Currency, Account name (= designation_name, which must contain `Safeguarding`) must equal IN-02; Letter date (YYYY-MM-DD) must not be after the period end. |
| IN-16 | `ack_letter_SGA-EUR-01.pdf` | REQUIRED | `Letter reference`, `Institution`, `Account name`, `Account number`, `Currency`, `Letter date` | As IN-15 for SGA-EUR-01. |
| IN-17 | `safeguarding_reconciliation_policy_v1.2.pdf` | REQUIRED | `Document version`, `Effective date`, `Safeguarding method`, `Reconciliation method`, `Reconciliation point`, `Frequency`, `Internal reconciliation basis` | `Document version` must be a registered version (`1.1` or `1.2`); `Effective date` must equal the registered date (1.2: `2026-05-07`; 1.1: `2025-10-01`); text must contain the version's markings (1.2: `SYNTHETIC DOCUMENT - UC-042 POC`); version must apply to the period. Engine: `Reconciliation point` must match `HH:MM Europe/London`; C03-POLICY PASS needs `Reconciliation method: STANDARD` and `Internal reconciliation basis: Per currency`. File-name version must equal the document version. |
| IN-18 | `governance_register_2026-09.pdf` | OPTIONAL | `Accountable person`, `Role`, `Allocated from` | C16-GOVERNANCE: PASS if `Accountable person` non-empty and `Allocated from` (YYYY-MM-DD) not after the period end. |
| IN-19 | `rep027_submission_receipt_2026-08.pdf` | OPTIONAL | `Return`, `Period`, `Due date`, `Submitted at`, `Submission reference` | Named for the PREVIOUS month. C16-RETURN PASS needs `Period` = previous month `YYYY-MM`, `Submitted at` an ISO timestamp with offset on/before the due date, and `Due date` = 15th England-and-Wales business day after the previous month end (Sep 2026: `2026-09-21`). |

## Fields with no runtime reader

Present in the header (and so required to exist as columns) but not read by any engine calculation (grep of `validate.py`, `pack/*.py`, `trace.py`, 18 Nov 2026); values are only type-checked. `snapshot_id` and `cycle_date` are displayed in the pack's opening-position and settlement tables but never calculated with: IN-01 `calendar_basis`; IN-02 `institution_*`, `open_date`, `close_date`, `asset_pool_id`; IN-03 `snapshot_id` (key only), `asset_pool_id`; IN-04 `classification`, `identified_date`; IN-05 `performed_at_ts`, `method`, `d1_requirement`, `d1_resource`, `actions_taken_text`, `preparer_id`, `reviewer_id`; IN-06 `performed_at_ts`, `timing_difference_claimed` (wording of a note only), `preparer_id`; IN-07 `bank_statement_ref`; IN-08 `as_at_ts`, `bank_statement_ref`; IN-09 `value_date`, `counterparty_name`, `narrative_text`; IN-11 `status`, `auth_ts`, `clearing_date`; IN-12 `cycle_date`; IN-13 `fee_code` (enum only); IN-14 everything except `recon_ref` and `logged_ts`. (Derived from the code paths in `validate.py`; see the discovery report of 16 Nov 2026 for the full trace.)
