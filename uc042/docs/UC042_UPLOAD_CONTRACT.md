# UC-042 Upload Contract — Decision Document

Status: **approved 29 Oct 2026** (U1–U6). U2 and U3 are implemented; see `UC042_PERIOD_AND_HEADER_RULES.md`. Section 5.1 rows marked "Not caught" are now handled as described there.

Basis: the hardened engine (`uc042lib/structure.py`, `prepare.py`, `validate.py`, `schema.py`), the input evidence specification v1 and the source-to-control matrix. Every behaviour stated here was checked by running the code on disposable copies. No engine code was changed.

**Recommendation.** One consolidated file per evidence type, for one fixed reporting period (September 2026), in the synthetic formats defined by `schema.py`. Nothing else is accepted. One small engine change, a reporting-period check, is needed before a credible demo (decision U2).

---

## 1. Answers to the six questions

| # | Question | Answer from the code |
| --- | --- | --- |
| 1 | One file per type, or many? | **One per type.** `prepare.py` maps each type to one slot. Two different files of the same type become `AMBIGUOUS`, and neither is used. Tested: an entries file split in two gave 1 `AMBIGUOUS_FILE` exception, and the checks that need it were blocked. |
| 2 | Can multiple files be combined safely? | **Not today, and not without new rules.** Merging would need several things: a file identity per row for citations; detection of duplicate keys across files; rules for overlapping dates (two statements for one day); and a period and coverage check per file. None exists, so the engine correctly refuses to choose. Recommendation: do not merge in the first POC (decision U1). |
| 3 | What identifies each type? | **CSV:** the header row must equal one schema column list exactly. **PDF:** a readable PDF whose text contains every key-details label of one document type. Details in section 4. |
| 4 | Unreadable, duplicated, malformed, ambiguous, out of period? | All handled except **out of period**. That is undetected and gives misleading results (section 5). |
| 5 | What runs before financial validation, and what runs independently? | Section 5.2. |
| 6 | Which limitations are acceptable? | Section 6. One (period) would undermine a demo; one (vague header-rejection message) would confuse users. |

## 2. Accepted assumptions

1. **Synthetic only.** Every format is a POC convention defined in `schema.py`. Nothing claims to match a Moorwand, bank or scheme export.
2. **One case = one reporting period = September 2026.** The period ID, holiday list, return due date and canonical file names are fixed in code.
3. **One entity, one e-money asset pool, segregation method, GBP and EUR only.**
4. **One upload set = up to 19 files:** 14 CSVs and 5 PDFs. IN-18 and IN-19 are optional; the other 17 are required.
5. **The case is rebuilt from the full current upload set on every validation run.** `prepare` is all-or-nothing per run; there is no incremental merge.
6. **The engine is the authority.** The application only stores uploads, calls `prepare` and `validate`, and displays outputs.

## 3. Supported upload formats

| Format | Accepted | Rejected |
| --- | --- | --- |
| CSV | UTF-8, optional BOM, LF or CRLF line endings, comma separator, RFC 4180 quoting, one header row | Other encodings; XLSX, ZIP or ODS (rejected with "export as CSV"); semicolon or tab separators (header will not match) |
| PDF | Text-based PDF (starts with `%PDF-`, readable by pypdf) containing `Label: value` lines | Scanned or image-only PDFs (no text, no OCR); damaged PDFs; PDFs without a full label set |
| Anything else | — | Rejected at intake with a reason |

**Field formats inside CSVs** (from `structure.py`):

| Type | Format |
| --- | --- |
| Amounts | `1000.00`: 2 dp and `.` only. `1,000.00`, `1000,00`, signs on unsigned amounts, symbols and spaces are rejected, never converted. |
| Dates | `YYYY-MM-DD` |
| Timestamps | ISO 8601 with offset |
| Identifiers | `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` |
| Currencies | GBP or EUR |
| Enums | As listed in `schema.ENUMS` (for example debit/credit `C`/`D`, `TO_FIRM`/`FROM_FIRM`) |

## 4. File identification rules

Identification uses **content only**. File names, extensions, folders and any user-supplied manifest are ignored; a supplied `manifest.csv` is rejected as unrecognised.

### 4.1 CSV: exact header match

Matching is case-sensitive, column order is fixed, and there are no extra or missing columns. A BOM is ignored.

| ID | Canonical file | Exact header |
| --- | --- | --- |
| IN-01 | `recon_calendar_2026-09.csv` | `calendar_date,period_id,is_recon_day,non_recon_reason,calendar_basis` |
| IN-02 | `account_inventory.csv` | `account_id,account_class,currency,asset_pool_id,account_number_masked,designation_name,acknowledgement_letter_ref,institution_id,institution_full_name,institution_postal_address,institution_email,institution_phone,institution_role,open_date,close_date` |
| IN-03 | `client_balance_snapshots_2026-09.csv` | `snapshot_id,recon_date,as_at_ts,client_id,asset_pool_id,currency,balance` |
| IN-04 | `unallocated_register_2026-09.csv` | `receipt_id,bank_reference,receipt_date,receipt_ts,amount,currency,classification,identified_date,allocated_date,allocated_ts,client_id` |
| IN-05 | `internal_recon_records_2026-09.csv` | `recon_run_id,recon_date,reconciliation_point_ts,performed_at_ts,asset_pool_id,currency,method,requirement_reported,resource_reported,item_a,item_b,item_c,item_d,difference_reported,d1_requirement,d1_resource,actions_taken_text,preparer_id,reviewer_id` |
| IN-06 | `external_recon_records_2026-09.csv` | `ext_recon_id,recon_date,performed_at_ts,account_id,currency,ledger_balance_reported,bank_statement_id,bank_balance_reported,difference_reported,timing_difference_claimed,preparer_id` |
| IN-07 | `bank_balance_confirmations_2026-09.csv` | `statement_id,account_id,as_at_ts,currency,balance_amount,balance_dc_indicator,bank_statement_ref` |
| IN-08 | `bank_statements_eod_2026-09.csv` | `statement_id,account_id,statement_date,as_at_ts,currency,opening_balance_amount,opening_balance_dc,closing_balance_amount,closing_balance_dc,entry_count,bank_statement_ref` |
| IN-09 | `bank_statement_entries_2026-09.csv` | `bank_entry_id,statement_id,account_id,booking_date,booking_ts,value_date,amount,dc_indicator,currency,bank_reference,end_to_end_ref,counterparty_name,narrative_text` |
| IN-10 | `sga_cashbook_entries_2026-09.csv` | `ledger_entry_id,account_id,posted_ts,entry_type,amount,dc_indicator,currency,payment_reference` |
| IN-11 | `transactions_2026-09.csv` | `txn_id,client_id,txn_type,status,auth_ts,clearing_date,executed_ts,amount,direction,currency,settlement_batch_id,payment_reference,original_txn_id` |
| IN-12 | `settlement_batches_2026-09.csv` | `batch_id,counterparty_type,cycle_date,settlement_date,account_id,currency,direction,gross_amount,total_fees,total_adjustments,net_amount_reported,expected_bank_reference` |
| IN-13 | `settlement_lines_2026-09.csv` | `line_id,batch_id,line_type,txn_id,fee_code,amount,dc_indicator,currency` |
| IN-14 | `discrepancy_log_2026-09.csv` | `discrepancy_id,logged_ts,recon_ref,account_id,currency,amount,description,cause_category,cause_evidence_ref,funding_reference,status,resolved_ts,approver_id` |

IN-04 and IN-14 may contain only the header. Every other CSV must have at least one data row.

### 4.2 PDF: full key-details label set

| ID | Requirement | Every one of these `Label: value` lines must be present |
| --- | --- | --- |
| IN-15 / IN-16 | Required | Letter reference, Institution, Account name, Account number, Currency, Letter date |
| IN-17 | Required | Document version, Effective date, Safeguarding method, Reconciliation method, Reconciliation point (`HH:MM Europe/London`), Frequency, Internal reconciliation basis |
| IN-18 | Optional | Accountable person, Role, Allocated from |
| IN-19 | Optional | Return, Period, Due date, Submitted at, Submission reference |

Acknowledgement letters share a label set. The slot (IN-15 for SGA-GBP-01, IN-16 for SGA-EUR-01) is chosen only by matching the letter's `Letter reference` to `acknowledgement_letter_ref` in the account inventory. If there is no inventory or no match, the letter is `AMBIGUOUS`.

## 5. Missing and invalid evidence behaviour

### 5.1 Behaviour by condition (verified)

| Condition | Where caught | Result | Exceptions |
| --- | --- | --- | --- |
| Unreadable file (bad encoding, damaged PDF, XLSX) | `prepare`: `REJECTED` with reason. If placed directly in a case: `INVALID_FILE` | Type treated as unavailable | 1 Critical |
| Header does not match any type | `prepare`: `REJECTED` ("CSV header does not match any evidence type"), then `MISSING` for the type | Dependent checks blocked | 1 Critical |
| Same content uploaded twice | `prepare`: second copy `DUPLICATE`, not used | No effect | None |
| Two different files of one type | `prepare`: all `AMBIGUOUS`, none used | Dependent checks blocked | 1 Critical (`AMBIGUOUS_FILE`) |
| Required type not supplied | `prepare`: `MISSING`; validator gate | One INSUFFICIENT_EVIDENCE result per dependent check | 1 Critical (`MISSING_FILE`) |
| File present but empty | Validator | As missing, labelled empty | 1 Critical (`EMPTY_FILE`) |
| Malformed row (type, enum, missing field, wrong field count, duplicate key) | Validator, `structure.py` | Row excluded; `DQ-FIELD` finding with file, line, field and raw value; affected scopes INSUFFICIENT_EVIDENCE | 1 High per file (`INVALID_ROWS`) |
| Malformed row in calendar or account inventory | Validator | Whole file unusable | 1 per file |
| **File for another period** (for example August confirmations) | **Not caught** | Treated as missing days: **88 `MISSING_BANK_EVIDENCE` exceptions** | **88** (should be 1) |
| **Stray row dated outside the period** | **Not caught** | Processed as normal; produced 2 misleading FAILs in a test (a duplicate reference) | 2 (should be 1 data-quality finding) |
| Extra record on a non-reconciliation day | Processed | Allowed (spec DQ05: extra reconciliations are permitted) | Only if its values are wrong |

### 5.2 Order of checks

These run **before any financial calculation**, in this order:

1. **Intake (`prepare`):** identify by content; reject, flag duplicates or ambiguity; hash; write the manifest.
2. **Integrity:** recompute SHA-256 against the manifest (`V00-FILE`).
3. **Readability and header** (`V01-SCHEMA`, `V01-PDF`); key-details completeness for PDFs.
4. **Row structure** (`DQ-FIELD`); exclude invalid rows.
5. **Scope files:** the calendar (IN-01) and account inventory (IN-02) must be fully valid, otherwise unusable.
6. **Policy point:** IN-17 must provide `HH:MM Europe/London`, otherwise unusable.
7. **Evidence gate:** each check runs only if every file in `schema.DEPENDS` is available.

**Checks independent of the calendar, inventory and policy.** These still run when IN-01, IN-02 or IN-17 is unavailable:

- `DQ23-STATEMENT` (IN-08, IN-09) and `BC-VS-EOD` (IN-07, IN-08, IN-09);
- `C11-BATCH-ARITH` and `C11-TXN-LINE` (IN-11, IN-12, IN-13);
- `C12-REFUND` (IN-11);
- `CBAL-NONNEG` (IN-03);
- `DISC-LOG` (IN-14).

The other 22 checks need at least one of IN-01, IN-02 or IN-17.

## 6. Known limitations

### Acceptable for the synthetic demo

- Only the synthetic CSV schemas and fixed PDF layouts are supported. There is no XLSX, OCR, MT940, camt.053 or scheme format. This is stated, not hidden.
- One file per type; multi-file merging is unsupported (decision U1).
- Header matching is strict. Correct, but needs a clearer message (decision U3).
- An excluded row with an unreadable account or date blocks every scope it could touch. This is conservative by design.
- No date-order check (DQ03) and no general cross-file conflict detection beyond duplicate references (DQ13).
- PDF fields are parsed without human confirmation.
- Hard-coded conventions: the top-up reference pattern, the holiday list and the letter slots.
- Reported and source values come from one simulation. Results show consistency, not operational truth or compliance.

### Would prevent a credible demonstration

- **No reporting-period check.** Uploading the wrong month, a likely demo mistake, produces dozens of misleading "missing evidence" exceptions instead of one clear finding. A single out-of-period row can create false failures.
- **Generic header rejection.** "CSV header does not match any evidence type" doesn't tell a user which type was intended or which columns are wrong, so they can't fix the file. This doesn't affect correctness, but it will make a live demo stall.

## 7. Decisions requiring your approval

| # | Decision | Recommendation | Engine change? |
| --- | --- | --- | --- |
| **U1** | One file per evidence type; more than one is `AMBIGUOUS`; no merging in the first POC | **Approve.** Merging needs per-row file identity, cross-file duplicate and overlap rules: a separate piece of work. | No |
| **U2** | Add a reporting-period check | **Approve; needed before the demo.** See the rules below this table. | Yes, small: about 1 rule and 4 tests |
| **U3** | Keep strict header matching, but improve the rejection reason | **Approve.** Name the closest type and list missing, extra or misordered columns. Matching stays exact. | Yes, message only, in `prepare.py` |
| **U4** | Replacement semantics: each run rebuilds the case from the current upload set; to replace a file, remove the old one and upload the new one; earlier runs stay available as history | **Approve.** Matches how `prepare` works today. | No |
| **U5** | The POC accepts only September 2026; the app does not offer other periods | **Approve** as a synthetic constraint, documented in the UI | No |
| **U6** | IN-18 and IN-19 stay optional: absent means NOT_APPLICABLE and no exception | **Approve** | No |

**U2, proposed rules:**

- **Row level:** a row whose own business date falls outside the case period is excluded as an invalid row (`DQ-FIELD`, reason "outside reporting period"). There are documented exceptions:
  - the cash-book `OPENING_BALANCE` row dated 31 Aug 17:00;
  - dates that are not period activity: account open and close dates, the policy effective date, and the return period, which is August by design.
- **File level:** a CSV with data rows but none inside the period is reported as one `WRONG_PERIOD` exception and treated as unusable.

If you approve U2 and U3, I'll implement them as one small engine change with regression tests. All three answer keys must still match. Only then should application work start.
