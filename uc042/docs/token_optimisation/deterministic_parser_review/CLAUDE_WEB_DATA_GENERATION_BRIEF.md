# Brief for Claude: generate two UC-042 ZIP test submissions

> **How to use:** paste everything below the line into Claude (web) in one message. Nothing else is needed.
>
> **Sources (for the reviewer, not for Claude):** the brief was derived on 18 Nov 2026 from the deterministic parser in `p10/uc042_token_optimisation`:
> - `uc042lib/schema.py`, `period.py`, `structure.py`, `money.py`, `policy.py`, `validate.py`, `generate.py`;
> - `uc042app/ingest/zip_package.py`;
> - the scenario answer keys in `uc042_dataset/scn_*`.
>
> **What is grounded:**
> - Scenario A's target is what the engine produces for the committed clean baseline: `CLEAN`, all PASS, 0 exceptions (checked in memory on 18 Nov).
> - Scenario B combines four existing scenarios whose expected results are pinned by answer keys (S05, SC2, SC5A, SC5D), plus one optional-document failure.
>
> **What is not verified:** the combined Scenario B outcome is the union of those answer keys. It has not been run and must be confirmed with the validation steps in `DETERMINISTIC_PARSER_TEST_COVERAGE.md` §4.

---

## Your task

**What to produce:** two ZIP files of synthetic safeguarding-reconciliation evidence for a fictional e-money institution, for **September 2026** (reporting period `PER-2026-09`).

**How they will be checked:** a strict, deterministic parser and reconciliation engine:
- it rejects any deviation in file names, CSV headers or value formats;
- it recomputes every balance from the underlying records, to the cent.

**The two ZIPs:**
- **Scenario A, `uc042_PER-2026-09_scenario_A_clean.zip`:** a complete, internally consistent month with no exceptions.
- **Scenario B, `uc042_PER-2026-09_scenario_B_exceptions.zip`:** the same schema and the same kind of month, with exactly the business-level exceptions specified in §9. Every file must still parse.

**Also provide, as separate files outside the ZIPs:**
- `scenario_A_expected_results.md` and `scenario_B_expected_results.md` (format in §10);
- the Python script you used to generate the data.

**Use code.** Write one Python generator: build the month day by day with integer cents, write the files, then run the self-checks in §11 **before** you zip.

**Use only what this brief specifies.** Do not invent columns, file names, values for enumerations, or ID formats.

**All data is synthetic and fictional.** Do not use real company, bank or person names. Use the fictional names given.

---

## 1. ZIP structure (both scenarios)

**Layout:** a flat ZIP with these files at the root and nothing else. No folders, no README, no manifest, no answer key, no hidden files. Any other file makes the whole package be rejected.

```
recon_calendar_2026-09.csv
account_inventory.csv
client_balance_snapshots_2026-09.csv
unallocated_register_2026-09.csv
internal_recon_records_2026-09.csv
external_recon_records_2026-09.csv
bank_balance_confirmations_2026-09.csv
bank_statements_eod_2026-09.csv
bank_statement_entries_2026-09.csv
sga_cashbook_entries_2026-09.csv
transactions_2026-09.csv
settlement_batches_2026-09.csv
settlement_lines_2026-09.csv
discrepancy_log_2026-09.csv
ack_letter_SGA-GBP-01.pdf
ack_letter_SGA-EUR-01.pdf
safeguarding_reconciliation_policy_v1.2.pdf
governance_register_2026-09.pdf
rep027_submission_receipt_2026-08.pdf
```

**File names are exact and case-sensitive.** The last file is named for **August** (`2026-08`) on purpose: it is the receipt for the previous month's regulatory return.

**Manifest of files and purposes:**

| ID | File | Purpose |
|---|---|---|
| IN-01 | recon_calendar_2026-09.csv | Every day of September, and whether it is a reconciliation day |
| IN-02 | account_inventory.csv | The four bank accounts and the bank holding them |
| IN-03 | client_balance_snapshots_2026-09.csv | Each client's balance at 17:00 on each reconciliation day, plus the opening position at 31 Aug 17:00 |
| IN-04 | unallocated_register_2026-09.csv | Receipts not yet attributed to a client |
| IN-05 | internal_recon_records_2026-09.csv | The firm's daily internal reconciliation (requirement vs resource) per currency |
| IN-06 | external_recon_records_2026-09.csv | The firm's daily external reconciliation (ledger vs bank) per safeguarding account |
| IN-07 | bank_balance_confirmations_2026-09.csv | The bank-confirmed balance at 17:00 per safeguarding account per day |
| IN-08 | bank_statements_eod_2026-09.csv | End-of-day statement header per account per day |
| IN-09 | bank_statement_entries_2026-09.csv | Every bank statement line |
| IN-10 | sga_cashbook_entries_2026-09.csv | The firm's ledger of the safeguarding bank accounts |
| IN-11 | transactions_2026-09.csv | Client transactions (loads, spends, refunds, redemptions) |
| IN-12 | settlement_batches_2026-09.csv | Card scheme and acquirer settlement batch headers |
| IN-13 | settlement_lines_2026-09.csv | Lines of each settlement batch |
| IN-14 | discrepancy_log_2026-09.csv | The firm's log of investigated differences (may be header-only) |
| IN-15 | ack_letter_SGA-GBP-01.pdf | Bank's acknowledgement letter for the GBP safeguarding account |
| IN-16 | ack_letter_SGA-EUR-01.pdf | The same for the EUR safeguarding account |
| IN-17 | safeguarding_reconciliation_policy_v1.2.pdf | The firm's reconciliation policy (registered version 1.2) |
| IN-18 | governance_register_2026-09.pdf | Accountable person (optional document; include it) |
| IN-19 | rep027_submission_receipt_2026-08.pdf | Receipt for the August return (optional document; include it) |

---

## 2. Value formats (apply to every CSV)

**File format:**
- Encoding: UTF-8, no BOM preferred.
- Line endings: LF.
- Delimiter: comma.
- Quote a field with double quotes **only** if it contains a comma, a double quote or a newline; escape a quote by doubling it.

**Header row:** exactly the header in §3, as the first line. Same column names, order and case. No extra columns.

**Data rows:**
- every row has exactly as many fields as the header;
- no blank lines in the middle of the file;
- no trailing spaces in values;
- never pad values.

**Value rules:**

| Type | Rule | Example |
|---|---|---|
| empty | Nothing between the commas. Never `NULL`, `N/A`, `-`, `0` or a space. | `a,,c` |
| amount | Unsigned, exactly 2 decimals, `.` separator, no thousands separator, no currency symbol, no `+`. | `2868.50` |
| signed | As amount, with an optional leading `-`. | `-812.40` |
| date | `YYYY-MM-DD` | `2026-09-15` |
| ts | `YYYY-MM-DDTHH:MM:SS+01:00`. Every timestamp in this dataset is British Summer Time, so always `+01:00`. Never `Z`; never omit the offset. | `2026-09-15T17:00:00+01:00` |
| bool | `true` / `false` (lower case) | `true` |
| int | Digits only | `5` |
| ccy | `GBP` or `EUR` | `GBP` |
| id | Starts with a letter or digit; then only letters, digits, `.` `_` `:` `-`; max 64 characters; no spaces or `/` | `TX-0915-00009` |
| enum | Exactly one of the listed values, upper case as shown | `SETTLED` |
| str | Free text (quote it if it contains a comma) | `Example Bank plc` |

**Money:** keep all money in integer cents in your generator and format with 2 decimals only when writing. All comparisons are exact to the cent; there is no tolerance.

---

## 3. Exact CSV headers, columns and rules

**Requiredness codes:** M = mandatory; C = conditional (rule given); O = optional, may be empty.

### IN-01 `recon_calendar_2026-09.csv`

```
calendar_date,period_id,is_recon_day,non_recon_reason,calendar_basis
```

**One row per day, 2026-09-01 to 2026-09-30 (30 rows):**
- `period_id` = `PER-2026-09` in every row.
- **Reconciliation days:** the 22 weekdays, `is_recon_day=true` with `non_recon_reason` empty:
  - 1, 2, 3, 4;
  - 7, 8, 9, 10, 11;
  - 14, 15, 16, 17, 18;
  - 21, 22, 23, 24, 25;
  - 28, 29, 30.
- **Weekends:** 5, 6, 12, 13, 19, 20, 26, 27, with `is_recon_day=false` and `non_recon_reason=WEEKEND`.
- There are no England and Wales bank holidays in September 2026.
- `calendar_basis` = `SYNTHETIC: UK weekends and bank holidays; no foreign-market closures assumed` (no comma, so no quotes needed).

### IN-02 `account_inventory.csv`

```
account_id,account_class,currency,asset_pool_id,account_number_masked,designation_name,acknowledgement_letter_ref,institution_id,institution_full_name,institution_postal_address,institution_email,institution_phone,institution_role,open_date,close_date
```

Exactly four rows. **The account IDs are fixed and must not be renamed.**

| account_id | account_class | currency | asset_pool_id | account_number_masked | designation_name | acknowledgement_letter_ref |
|---|---|---|---|---|---|---|
| SGA-GBP-01 | RELEVANT_FUNDS_BANK | GBP | POOL-EMONEY | ****4471 | Synthetic EMI Ltd Safeguarding Account (GBP) | ACK-INST01-4471 |
| SGA-EUR-01 | RELEVANT_FUNDS_BANK | EUR | POOL-EMONEY | ****8823 | Synthetic EMI Ltd Safeguarding Account (EUR) | ACK-INST01-8823 |
| OWN-GBP-01 | OWN_FUNDS | GBP | *(empty)* | ****1190 | *(empty)* | *(empty)* |
| OWN-EUR-01 | OWN_FUNDS | EUR | *(empty)* | ****1206 | *(empty)* | *(empty)* |

**The same values on all four rows:**
- `institution_id` = `INST-01`;
- `institution_full_name` = `Example Bank plc`;
- `institution_postal_address` = `"1 Example Street, London EC0A 0AA (fictional)"` (quoted, because it contains a comma);
- `institution_email` = `safeguarding@example-bank.invalid`;
- `institution_phone` = `+44 20 0000 0000`;
- `institution_role` = `RELEVANT_FUNDS_BANK` (the only allowed value, also on own-funds rows);
- `open_date` = `2024-03-01`;
- `close_date` empty.

### IN-03 `client_balance_snapshots_2026-09.csv`

```
snapshot_id,recon_date,as_at_ts,client_id,asset_pool_id,currency,balance
```

**Clients:**
- GBP: `C0001`–`C0008`;
- EUR: `C0101`–`C0104`;
- a client has one currency only.

**Opening rows:** one per client with:
- `recon_date=2026-08-31`;
- `as_at_ts=2026-08-31T17:00:00+01:00`;
- `snapshot_id=CBS-20260831-<client>-<CCY>`.

**Daily rows:** for **every reconciliation day** and **every** client of that currency (even if the balance did not change), one row with:
- `as_at_ts=<day>T17:00:00+01:00`;
- `snapshot_id=CBS-<YYYYMMDD>-<client>-<CCY>`;
- `asset_pool_id=POOL-EMONEY`;
- `balance` = the client's balance after all of that client's transactions with `executed_ts` ≤ 17:00 that day (signed type; balances never go negative).

**Opening balances (cents):**

| Client | Opening balance |
|---|---|
| C0001 | 40000.00 |
| C0002 | 35000.00 |
| C0003 | 32500.00 |
| C0004 | 30000.00 |
| C0005 | 30000.00 |
| C0006 | 28500.00 |
| C0007 | 27500.00 |
| C0008 | 26500.00 |
| C0101 | 25000.00 |
| C0102 | 20000.00 |
| C0103 | 18000.00 |
| C0104 | 17000.00 |

The GBP total is 250000.00 and the EUR total is 80000.00.

### IN-04 `unallocated_register_2026-09.csv`

```
receipt_id,bank_reference,receipt_date,receipt_ts,amount,currency,classification,identified_date,allocated_date,allocated_ts,client_id
```

Two receipts:

| receipt_id | Received | Amount | Allocated | To client |
|---|---|---|---|---|
| UR-0001 | 2026-09-11 16:30 | 750.00 GBP | 2026-09-14 09:30 (the next business day) | C0007 |
| UR-0002 | 2026-09-23 16:10 | 400.00 EUR | 2026-09-24 09:15 | C0102 |

**Field values:**
- `bank_reference` = `E2E-<CCY>-<MMDD of receipt>-U01`;
- `classification=UNALLOCATED`;
- `identified_date` empty;
- `allocated_date`, `allocated_ts` and `client_id` filled.

### IN-05 `internal_recon_records_2026-09.csv`

```
recon_run_id,recon_date,reconciliation_point_ts,performed_at_ts,asset_pool_id,currency,method,requirement_reported,resource_reported,item_a,item_b,item_c,item_d,difference_reported,d1_requirement,d1_resource,actions_taken_text,preparer_id,reviewer_id
```

One row per reconciliation day per currency (GBP and EUR), so 44 rows.

| Column | Value |
|---|---|
| `recon_run_id` | `IRR-EMONEY-<CCY>-<YYYYMMDD>` |
| `reconciliation_point_ts` | `<day>T17:00:00+01:00` (must be exactly 17:00) |
| `performed_at_ts` | `<day>T17:35:00+01:00` |
| `asset_pool_id` | `POOL-EMONEY` |
| `method` | `STANDARD` |
| `requirement_reported` | Σ of that currency's client balances at 17:00 (each floored at 0) + Σ amounts of that currency's IN-04 receipts received at or before 17:00 and not allocated by 17:00 |
| `item_a` | The safeguarding cash-book balance (IN-10) of that currency's SGA account at 17:00 |
| `item_b`, `item_c`, `item_d` | `0.00` |
| `resource_reported` | item_a |
| `difference_reported` | resource − requirement (`0.00` in Scenario A) |
| `d1_requirement`, `d1_resource` | empty |
| `actions_taken_text` | `"Client ledger extract and safeguarding cash book taken at 17:00; requirement and resource compared; no difference."` (quoted) |
| `preparer_id` | `U-12` |
| `reviewer_id` | `U-04` |

### IN-06 `external_recon_records_2026-09.csv`

```
ext_recon_id,recon_date,performed_at_ts,account_id,currency,ledger_balance_reported,bank_statement_id,bank_balance_reported,difference_reported,timing_difference_claimed,preparer_id
```

One row per reconciliation day per **safeguarding** account (SGA-GBP-01, SGA-EUR-01), so 44 rows.

| Column | Value |
|---|---|
| `ext_recon_id` | **`ERL-<account_id>-<YYYYMMDD>`** (this exact format is relied on to link the discrepancy log) |
| `performed_at_ts` | `<day>T17:50:00+01:00` |
| `ledger_balance_reported` | The cash-book balance at 17:00 |
| `bank_statement_id` | The IN-07 `statement_id` of that account and day |
| `bank_balance_reported` | The IN-07 balance (signed: positive when the bank's indicator is C) |
| `difference_reported` | bank − ledger |
| `timing_difference_claimed` | `false` (except as stated in Scenario B) |
| `preparer_id` | `U-12` |

### IN-07 `bank_balance_confirmations_2026-09.csv`

```
statement_id,account_id,as_at_ts,currency,balance_amount,balance_dc_indicator,bank_statement_ref
```

One row per reconciliation day per **safeguarding** account, so 44 rows.

| Column | Value |
|---|---|
| `statement_id` | `ST-<account_id>-<YYYYMMDD>-1700` |
| `as_at_ts` | `<day>T17:00:00+01:00` |
| `balance_amount` | The bank balance at 17:00: that day's IN-08 opening + Σ IN-09 entries booked at or before 17:00. Unsigned. |
| `balance_dc_indicator` | `C` |
| `bank_statement_ref` | `BC/<account_id>/<YYYYMMDD>` |

### IN-08 `bank_statements_eod_2026-09.csv`

```
statement_id,account_id,statement_date,as_at_ts,currency,opening_balance_amount,opening_balance_dc,closing_balance_amount,closing_balance_dc,entry_count,bank_statement_ref
```

One row per reconciliation day for **each of the four accounts** (88 rows), including days with no entries (`entry_count=0`, opening = closing).

| Column | Value |
|---|---|
| `statement_id` | `ST-<account_id>-<YYYYMMDD>-EOD` |
| `as_at_ts` | `<day>T23:59:59+01:00` |
| opening / closing | Unsigned; dc `C` (all balances are in credit) |
| `entry_count` | The number of IN-09 rows with this `statement_id` |
| `bank_statement_ref` | `EOD/<account_id>/<YYYYMMDD>` |

**Balance continuity:**
- Each day's opening equals the previous reconciliation day's closing for the same account.
- 1 Sep openings:
  - SGA-GBP-01: 250000.00;
  - SGA-EUR-01: 80000.00;
  - OWN-GBP-01: 500000.00;
  - OWN-EUR-01: 150000.00.
- Opening + Σ signed entries = closing (C = +, D = −).

### IN-09 `bank_statement_entries_2026-09.csv`

```
bank_entry_id,statement_id,account_id,booking_date,booking_ts,value_date,amount,dc_indicator,currency,bank_reference,end_to_end_ref,counterparty_name,narrative_text
```

**Rules:**
- `statement_id` = the EOD statement of the same account and day.
- `booking_date` = that day; `value_date` = `booking_date`.
- `amount` unsigned; `dc_indicator` C = money into the account, D = money out (bank perspective).
- All entries in Scenario A are booked **before 17:00**.
- `bank_entry_id` format:
  - `BE-<CCY>-<MMDD>-<suffix>` on safeguarding accounts;
  - `BE-OWN-<CCY>-<MMDD>-<suffix>` on own-funds accounts.
- Suffixes are unique per account per day (see §4).

### IN-10 `sga_cashbook_entries_2026-09.csv`

```
ledger_entry_id,account_id,posted_ts,entry_type,amount,dc_indicator,currency,payment_reference
```

The firm's ledger of the **two safeguarding accounts only**. `dc_indicator` is the **firm's** perspective, the opposite of the bank's: D = money in, C = money out.

**Rows:**
- **Opening rows:** `LE-GBP-0831-0000` (SGA-GBP-01, 250000.00) and `LE-EUR-0831-0000` (SGA-EUR-01, 80000.00), with `posted_ts=2026-08-31T17:00:00+01:00`, `entry_type=OPENING_BALANCE`, `dc_indicator=D`, `payment_reference=OPENING`.
- **Other rows:** `ledger_entry_id=LE-<CCY>-<MMDD>-<nnnn>` (sequence per currency per day, from 0001).
- **Allowed `entry_type` values:**
  - OPENING_BALANCE;
  - BANK_LOAD;
  - UNALLOCATED_RECEIPT;
  - ACQUIRER_SETTLEMENT;
  - OWN_FUNDS_TOPUP;
  - SCHEME_SETTLEMENT;
  - REDEMPTION.
- **Matching:** every non-opening row has exactly one safeguarding IN-09 entry on the same account whose `bank_reference` or `end_to_end_ref` equals its `payment_reference`, with the same amount and opposite letter (bank C ↔ cash D). Every safeguarding IN-09 entry has such a cash-book row.

### IN-11 `transactions_2026-09.csv`

```
txn_id,client_id,txn_type,status,auth_ts,clearing_date,executed_ts,amount,direction,currency,settlement_batch_id,payment_reference,original_txn_id
```

**Field rules:**
- `txn_id=TX-<MMDD>-<nnnnn>` (sequence per day across both currencies, from 00001); refunds may use `TX-<MMDD>-0R001`.
- `direction`: CR raises the client balance, DR lowers it.
- `txn_type`, `status` and conditional fields:

| `txn_type` | `status` | `auth_ts` | `clearing_date` | `settlement_batch_id` | `payment_reference` | `original_txn_id` | `direction` |
|---|---|---|---|---|---|---|---|
| LOAD_BANK | EXECUTED | empty | empty | empty | the bank entry's `end_to_end_ref` | empty | CR |
| REDEMPTION | EXECUTED | empty | empty | empty | the bank entry's `end_to_end_ref` | empty | DR |
| LOAD_CARD | SETTLED | = `executed_ts` | the day | the day's AQ batch | empty | empty | CR |
| SPEND | SETTLED | an earlier time that day | the day | the day's SB batch | empty | empty | DR |
| REFUND | SETTLED | empty | the day | the day's SB batch | empty | an earlier SPEND of the same client and currency, refund ≤ its amount | CR |

**Constraint:** no client balance may go below zero at any time.

### IN-12 `settlement_batches_2026-09.csv`

```
batch_id,counterparty_type,cycle_date,settlement_date,account_id,currency,direction,gross_amount,total_fees,total_adjustments,net_amount_reported,expected_bank_reference
```

**Exactly one ACQUIRER batch and exactly one SCHEME batch per currency per reconciliation day** (88 batches; not more, not fewer).

| | ACQUIRER | SCHEME |
|---|---|---|
| `batch_id` | `AQ-<CCY>-<YYYYMMDD>` | `SB-<CCY>-<YYYYMMDD>` |
| `direction` | `TO_FIRM` | `FROM_FIRM` |
| `gross_amount` | Σ card loads | Σ spends |
| `total_fees` | Σ fee lines (> 0) | `0.00` |
| `total_adjustments` | `0.00` | Σ refunds |
| `net_amount_reported` | gross − fees | gross − adjustments (keep it > 0) |

For both types:
- `cycle_date` = `settlement_date` = the day;
- `account_id` = `SGA-<CCY>-01`;
- `expected_bank_reference` = `batch_id`.

### IN-13 `settlement_lines_2026-09.csv`

```
line_id,batch_id,line_type,txn_id,fee_code,amount,dc_indicator,currency
```

**Field rules:**
- `line_id=SL-<batch_id>-<nnnn>`.
- `dc_indicator`: C = money to the firm, D = money from the firm.

**Lines per batch:**
- **ACQUIRER batch:**
  - one `TXN` line per card load (`txn_id`, amount equal to the transaction amount, `C`);
  - two `FEE` lines with an empty `txn_id`: `fee_code=ACQ_FEE` and `fee_code=SCHEME_FEE`, both `D`.
- **SCHEME batch:**
  - one `TXN` line per spend (`D`);
  - one `REFUND` line per refund (`C`, `txn_id` = the refund's `txn_id`).

**Line amounts:** every line amount string equals its transaction's amount string exactly.

### IN-14 `discrepancy_log_2026-09.csv`

```
discrepancy_id,logged_ts,recon_ref,account_id,currency,amount,description,cause_category,cause_evidence_ref,funding_reference,status,resolved_ts,approver_id
```

**Scenario A:** header only (no data rows).

**Scenario B:** see §9. The field rules are:
- `recon_ref` must be an existing `ext_recon_id` (`ERL-<account>-<YYYYMMDD>`);
- `logged_ts` must be on or after that reconciliation day;
- `status` is `OPEN` or `RESOLVED`.

---

## 4. Daily activity model (generate this for every reconciliation day)

All times are local (`+01:00`). Per currency (`CCY`, account `SGA-<CCY>-01`, own account `OWN-<CCY>-01`), in time order:

1. **Bank-transfer loads.**
   - **How many:** GBP 2 (09:10 and 11:40); EUR 1 (10:00).
   - **Amounts:** GBP 500.00–4000.00; EUR 400.00–2500.00. Random client of that currency.
   - **References:** `e2e = E2E-<CCY>-<MMDD>-L<nn>`.
   - **Bank entry:** suffix `L<nn>`, `C`, `bank_reference` = `end_to_end_ref` = e2e, counterparty `Synthetic payer`, narrative `INBOUND TRANSFER`.
   - **Cash book:** `BANK_LOAD`, `D`, `payment_reference` = e2e.
   - **Transaction:** `LOAD_BANK` CR, executed at the same time.
2. **Card loads (acquirer).**
   - **How many:** GBP 4, EUR 2, at 08:05, 08:15, 08:25, 08:35.
   - **Amounts:** GBP 100.00–2600.00; EUR 100.00–1300.00.
   - **Transactions:** `LOAD_CARD` CR in batch `AQ-<CCY>-<YYYYMMDD>`.
   - **Fees:** ACQ_FEE = 0.30% of gross and SCHEME_FEE = 0.155% of gross, each rounded half-up to the cent.
   - **Bank entry:** at 14:00, suffix `AQ1`, `C`, amount = net, `bank_reference` = batch_id, `end_to_end_ref` empty, counterparty `Synthetic Acquirer Ltd`.
   - **Cash book:** `ACQUIRER_SETTLEMENT`, `D`, net, `payment_reference` = batch_id, at 14:00.
3. **Own-funds top-up of the acquirer fees** at 14:30. With `ref = TOPUP-<CCY>-<YYYYMMDD>`, all three with amount = total fees:
   - IN-09 on `OWN-<CCY>-01`: suffix `TU1`, `D`, `bank_reference` = ref, `end_to_end_ref` empty;
   - IN-09 on `SGA-<CCY>-01`: suffix `TU1`, `C`, `bank_reference` = ref;
   - IN-10 `OWN_FUNDS_TOPUP`, `D`, `payment_reference` = ref.
4. **Card spends (scheme).**
   - **How many:** GBP 6, EUR 3.
   - **Amounts:** GBP 20.00–900.00; EUR 15.00–600.00. Random clients.
   - **Transactions:** `SPEND` DR, `executed_ts` = 15:00, `auth_ts` earlier that day, batch `SB-<CCY>-<YYYYMMDD>`.
   - **Refunds:** add one `REFUND` in GBP on 2026-09-09 and one in EUR on 2026-09-16. Each refunds an earlier spend of the same client in full, in that day's SB batch, CR at 15:00.
   - **Bank entry:** at 15:00, suffix `SB1`, `D`, amount = net (spends − refunds), `bank_reference` = batch_id, counterparty `Synthetic Card Scheme`.
   - **Cash book:** `SCHEME_SETTLEMENT`, `C`, net, at 15:00.
5. **Redemptions** on every second reconciliation day (the 2nd, 4th, … of the month's reconciliation days).
   - **What:** one per currency at 16:00 to the client with the highest balance; amount GBP 300.00–2500.00, EUR 200.00–1200.00, never more than the client's balance.
   - **References:** `e2e = E2E-<CCY>-<MMDD>-R01`.
   - **Bank entry:** suffix `R01`, `D`, `bank_reference` = `end_to_end_ref` = e2e.
   - **Cash book:** `REDEMPTION`, `C`.
   - **Transaction:** `REDEMPTION` DR at 16:00.
6. **Unallocated receipts** (IN-04) on their receipt day.
   - **Bank entry:** suffix `U01`, `C`, `bank_reference` = `end_to_end_ref` = `E2E-<CCY>-<MMDD>-U01`, counterparty `Unknown remitter`.
   - **Cash book:** `UNALLOCATED_RECEIPT`, `D`.
   - **No transaction on the receipt day.** On the allocation day add a `LOAD_BANK` CR transaction for the allocated client, at the allocation time, with `payment_reference` = the receipt's e2e. It has **no** new bank or cash-book entry.

**The invariant to hold at 17:00 on every reconciliation day, per currency (Scenario A):**

Σ max(0, client balances) + open unallocated receipts = cash-book balance (item A) = SGA bank balance.

Own-funds accounts change only by top-up debits.

---

## 5. PDFs (all five)

**Format:**
- Text-based PDFs (not scanned images), A4, one page.
- Use a library that writes real text (Python `reportlab` is known to work).

**Layout:** each PDF has a title, one intro sentence, a heading `Key details`, and then **one line per key detail** in the form `Label: value`:
- the label starts the line;
- it is followed by a colon and a single space;
- the value is on the same line with no wrapping (keep values short).

**Footer:** put this text on every page, exactly:

`SYNTHETIC DOCUMENT - UC-042 POC - not a real bank or firm document`

(The policy is only recognised if this text is present.)

**Key details:**

| File | Key details (exact labels and values) |
|---|---|
| `ack_letter_SGA-GBP-01.pdf` | `Letter reference: ACK-INST01-4471`<br>`Institution: Example Bank plc`<br>`Account name: Synthetic EMI Ltd Safeguarding Account (GBP)`<br>`Account number: ****4471`<br>`Currency: GBP`<br>`Letter date: 2024-03-01` |
| `ack_letter_SGA-EUR-01.pdf` | The same labels: `ACK-INST01-8823`, `Example Bank plc`, `Synthetic EMI Ltd Safeguarding Account (EUR)`, `****8823`, `EUR`, `2024-03-01` |
| `safeguarding_reconciliation_policy_v1.2.pdf` | `Document version: 1.2`<br>`Effective date: 2026-05-07`<br>`Safeguarding method: SEGREGATION`<br>`Reconciliation method: STANDARD`<br>`Reconciliation point: 17:00 Europe/London`<br>`Frequency: Each reconciliation day`<br>`Internal reconciliation basis: Per currency` |
| `governance_register_2026-09.pdf` | `Accountable person: A. Example (synthetic)`<br>`Role: Chief Financial Officer (synthetic)`<br>`Allocated from: 2026-05-07` |
| `rep027_submission_receipt_2026-08.pdf` | `Return: REP027 monthly safeguarding return`<br>`Period: 2026-08`<br>`Due date: 2026-09-21`<br>`Submitted at: 2026-09-17T11:02:00+01:00`<br>`Submission reference: SYN-RD-2026-08-0001` |

**Constraints on these values:**
- Do not change the policy version, its effective date or the footer.
- The letter values must equal the IN-02 values exactly.
- The return due date is fixed at 2026-09-21 (the 15th England and Wales business day after 31 Aug 2026).

---

## 6. Cross-document rules the engine checks (both scenarios)

1. **Coverage.** Every reconciliation day has:
   - one IN-05 row per currency;
   - one IN-06 and one IN-07 row per safeguarding account;
   - one IN-08 row per account (all four);
   - one IN-03 row per client;
   - exactly one ACQUIRER and one SCHEME batch per currency.
2. **Statements.** For each statement:
   - entries sum from opening to closing;
   - `entry_count` = the number of entries;
   - entries carry the statement's account, currency and date;
   - each day's opening = the previous day's closing;
   - the first SGA opening = the cash-book opening row.
3. **The 17:00 confirmation** (IN-07) = the EOD opening + entries booked by 17:00.
4. **References, not amounts, link records:**
   - cash book ↔ bank entry: `payment_reference` ↔ `bank_reference` or `end_to_end_ref`, same account;
   - batch ↔ bank: `expected_bank_reference` ↔ `bank_reference`;
   - LOAD_BANK / REDEMPTION ↔ bank: `payment_reference` ↔ `end_to_end_ref`;
   - receipt ↔ bank: IN-04 `bank_reference` ↔ IN-09 `end_to_end_ref`;
   - top-up: `TOPUP-<CCY>-<YYYYMMDD>`.
5. **Every safeguarding bank entry is explained** by one of: a batch, a client transaction reference, an unallocated receipt or a top-up.
6. **Batch arithmetic.**
   - TXN lines = gross; FEE lines = fees; REFUND lines = adjustments.
   - Signed lines (C+, D−) = signed net (TO_FIRM +, FROM_FIRM −).
   - Every line's transaction exists with the same batch and amount.
   - Every card transaction is in exactly one line of its batch.
7. **Client roll-forward.** Each client's snapshot = the previous reconciliation day's snapshot + their transactions executed after the previous 17:00 and at or before this 17:00.
8. **Internal reconciliation.** `requirement_reported`, `item_a`, `resource_reported` and `difference_reported` are recomputed exactly (§3 IN-05).
9. **External reconciliation.**
   - `bank_statement_id` → IN-07; the IN-07 balance = `bank_balance_reported`;
   - the cash-book balance at 17:00 = `ledger_balance_reported`;
   - bank − ledger = `difference_reported`.
10. **Allocation.** IN-04 receipts are allocated by the next business day to the same client as the LOAD_BANK carrying their reference.
11. **Refunds** reference an earlier spend of the same client and currency and never exceed it.
12. **Currency consistency.** Every record's currency equals its account's or batch's currency.
13. **Discrepancy log.** Every non-zero external difference must be logged in IN-14 with `recon_ref = ERL-<account>-<YYYYMMDD>`; otherwise the log check fails.

---

## 7. Scenario A: clean month

**Generation:** apply §1–§6 with no deviations.

**Expected engine result:**
- case status `CLEAN`;
- every check result `PASS`, including all 44 C06 and 44 C08 zero differences (a reconciled zero difference is PASS);
- **0 FAIL, 0 INSUFFICIENT_EVIDENCE, 0 NOT_APPLICABLE**;
- **0 exceptions**.

**Expected ZIP gate:** `VALIDATED`, 17 required + 2 optional present, no warnings about names or content.

---

## 8. Scenario B: overview

**Starting point:** generate a month exactly as in Scenario A (fresh random amounts allowed). Then apply **only** the changes in §9.

**What does not change:**
- every file, header and format stays valid;
- every file name stays the same;
- all 19 files are present;
- the ZIP gate must still be `VALIDATED`.

The exceptions are business-level only.

---

## 9. Scenario B: changes and expected outcomes

Apply each change on the account and day given. They are designed not to interact.

### B1. Unexplained bank debit on SGA-GBP-01 from 2026-09-17, never logged

**Change:**
- Add an IN-09 entry `BE-GBP-0917-X01` on `ST-SGA-GBP-01-20260917-EOD`: 2026-09-17 15:20, `812.40`, `D`, `bank_reference=SETTLE 0917 UNKNOWN`, `end_to_end_ref` empty, counterparty `Unknown`, narrative `DEBIT`. Add **no** cash-book row, transaction or batch for it.
- For SGA-GBP-01 on **every reconciliation day from 17 Sep to 30 Sep:**
  - lower the IN-08 balances (17 Sep closing and later openings and closings) by 812.40;
  - raise 17 Sep `entry_count` by 1;
  - lower the IN-07 confirmations by 812.40;
  - set IN-06 `bank_balance_reported` = the new bank balance and `difference_reported=-812.40` (ledger unchanged).
- IN-05 is unchanged (it is ledger-based).
- **Do not** add an IN-14 entry for it.

**Expected results:**
- `C08-DIFFERENCE` FAIL on all 10 days 2026-09-17…30 for SGA-GBP-01, with evidence status `NOT_EVIDENCED`;
- `BANK-CASH-LINK` FAIL for `BE-GBP-0917-X01`;
- `C11-BANK-ENTRY` FAIL for `BE-GBP-0917-X01`;
- `DISC-LOG` FAIL "SGA-GBP-01 from 2026-09-17".

**Expected exceptions:**
- root cause `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-17|-812.40` (Critical, 11 results);
- `UNMATCHED_BANK_ENTRY|BE-GBP-0917-X01` (High, 2 results).

*(Basis: scenario S05.)*

### B2. Scheme settlement booked by the bank one business day late on SGA-EUR-01 (timing), logged

**Change:**
- On 2026-09-15 the EUR scheme batch `SB-EUR-20260915` stays as normal in IN-10 (posted 15:00), IN-11, IN-12 and IN-13.
- The bank books it on **2026-09-16 at 08:00**: move its IN-09 entry from the 15 Sep statement to `ST-SGA-EUR-01-20260916-EOD` (same `bank_reference`, amount and `D`; new `bank_entry_id` `BE-EUR-0916-T01`; booking date and value date 2026-09-16).
- Adjust SGA-EUR-01:
  - 15 Sep EOD closing and `entry_count`;
  - 16 Sep EOD opening and `entry_count`;
  - 15 Sep IN-07 balance (higher by the net).
- 16 Sep's 17:00 balance is back in line.
- IN-06 for 2026-09-15: `bank_balance_reported` = the new bank balance, `difference_reported` = +net, `timing_difference_claimed=true`.
- Add one IN-14 row:
  - `discrepancy_id=DL-0001`;
  - `logged_ts=2026-09-15T18:05:00+01:00`;
  - `recon_ref=ERL-SGA-EUR-01-20260915`;
  - `account_id=SGA-EUR-01`, `currency=EUR`;
  - `amount` = net;
  - `description=Scheme settlement SB-EUR-20260915 not debited by the bank by 17:00`;
  - `cause_category=TIMING`;
  - `cause_evidence_ref=BE-EUR-0916-T01`;
  - `funding_reference` empty;
  - `status=RESOLVED`;
  - `resolved_ts=2026-09-16T09:00:00+01:00`;
  - `approver_id=U-04`.

**Expected results:**
- `C08-DIFFERENCE` FAIL for 2026-09-15/SGA-EUR-01 only, evidence status `TIMING_EVIDENCED`;
- `DISC-LOG` PASS for this difference;
- `C11-BATCH-BANK` PASS for SB-EUR-20260915, with an informational one-business-day lag note.

**Expected exception:** `BANK_LEDGER_DIFFERENCE|SGA-EUR-01|2026-09-15|<+net>` (Critical, 1 result, `TIMING_EVIDENCED`; it stays open for human confirmation).

*(Basis: scenario SC2.)*

### B3. Card spend missing from the transaction export (GBP, 2026-09-15)

**Change:**
- Pick one SPEND in `SB-GBP-20260915` of client `C0002` (create it with that client if needed).
- **Delete** its IN-11 row only.
- Keep its IN-13 line, the batch totals, the bank and cash entries, and the client's snapshots, which still reflect the spend. The client ledger knew about it; the export lost it.

**Expected results:**
- `C11-BATCH-ARITH` FAIL for SB-GBP-20260915 (the line does not match a transaction);
- `CBAL-ROLLFWD` FAIL for `GBP/C0002 2026-09-15`.

**Expected exceptions:**
- `C11-BATCH-ARITH|SB-GBP-20260915` (High);
- `CBAL-ROLLFWD|GBP/C0002 2026-09-15` (High).

*(Basis: scenario SC5A.)*

### B4. Closing client snapshot 250.00 too low (EUR, 2026-09-30)

**Change:**
- Lower the 2026-09-30 IN-03 balance of client `C0103` (EUR) by `250.00`. Choose a client whose balance stays ≥ 250.00.
- Leave IN-05 for 2026-09-30 EUR **unchanged** (the firm reported the pre-error requirement).

**Expected results:**
- `CBAL-ROLLFWD` FAIL `EUR/C0103 2026-09-30`;
- `C04-REQUIREMENT` FAIL `2026-09-30/EUR`;
- `C06-DIFFERENCE` FAIL `2026-09-30/EUR`.

**Expected exceptions:**
- `INTERNAL_DIFFERENCE|2026-09-30/EUR` (Critical);
- `CBAL-ROLLFWD|EUR/C0103 2026-09-30` (High);
- `C04-REQUIREMENT|2026-09-30/EUR` (High).

*(Basis: scenario SC5D, which uses GBP C0003.)*

### B5. Governance responsibility allocated after the period (optional document)

**Change:** in `governance_register_2026-09.pdf`, set `Allocated from: 2026-10-01`.

**Expected:**
- `C16-GOVERNANCE` FAIL;
- exception root cause `C16-GOVERNANCE|period`.

### Scenario B totals

**Expected case status:** `EXCEPTIONS_OPEN`.

**Expected exceptions:** 9 exceptions with the root causes listed in B1–B5. Every other check passes.

**Exception IDs:** the engine numbers exceptions itself (`EXC-CASE-nn`, ordered by severity, then first date). Do not predict IDs; list the root causes.

---

## 10. Expected-results files (outside the ZIPs)

`scenario_X_expected_results.md` must contain:

1. **The ZIP itself:** file name, SHA-256, and the 19 file names with SHA-256 and row or page counts.
2. **Generation parameters:** seed, record counts per file.
3. **Expected ZIP gate:** `VALIDATED`.
4. **Expected case status**, and the list of expected non-PASS results as `(check, scope, outcome)`.
5. **Expected exception root causes**, with severity.
6. **For Scenario B:** each change, the exact records you changed or added (IDs and old/new values), and why the expected results follow.
7. **The self-check output** from §11.

---

## 11. Validation checklist (run in your generator before zipping; report the results)

**Files and formats:**
- [ ] Exactly 19 files at the ZIP root, names exactly as in §1; nothing else in the ZIP.
- [ ] Every CSV header is exactly the line in §3.
- [ ] Every row has the header's field count; no value has leading or trailing spaces.
- [ ] All amounts match `^\d+\.\d{2}$` (signed: `^-?\d+\.\d{2}$`).
- [ ] All dates match `YYYY-MM-DD`.
- [ ] All timestamps end in `+01:00`.
- [ ] All enumerations are from the listed values.
- [ ] All IDs match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`.
- [ ] Primary keys (first column) are unique in each file.
- [ ] IN-14 is header-only in A; every other CSV has rows.

**Coverage and arithmetic:**
- [ ] 22 reconciliation days with full coverage (§6.1); 88 batches (one AQ and one SB per currency per day).
- [ ] Statement arithmetic and continuity (§6.2–6.3) hold for all 88 statements.
- [ ] Every cash-book row links to exactly one bank entry by reference, and the reverse (§6.4–6.5).
- [ ] Batch arithmetic holds for every batch, and every card transaction is in exactly one line (§6.6).
- [ ] Client roll-forward holds for every client and every day (§6.7) [except B3 and B4 in Scenario B].
- [ ] IN-05 and IN-06 reported values equal your recomputation [except the B1, B2 and B4 days].
- [ ] In Scenario A, requirement = item A = bank at 17:00 for every day and currency.

**PDFs:**
- [ ] Re-open each PDF with a text extractor (for example `pypdf`) and confirm each key-detail line appears as `Label: value` on its own line.
- [ ] The policy text contains `SYNTHETIC DOCUMENT - UC-042 POC`.

**Packaging:**
- [ ] The ZIP opens, has no folders, and contains no `.DS_Store` or `__MACOSX`.

**If you cannot satisfy a rule, stop and say which one. Do not work around it.**
