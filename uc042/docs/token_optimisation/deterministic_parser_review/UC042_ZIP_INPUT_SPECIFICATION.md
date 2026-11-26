# UC-042: ZIP Input Specification (deterministic parser)

**Sources.** Everything here is verified against `p10/uc042_token_optimisation` on 18 Nov 2026. The main files are:
- `uc042app/ingest/zip_package.py`;
- `uc042lib/period.py`;
- `uc042lib/schema.py`;
- `uc042lib/structure.py`;
- `uc042lib/prepare.py`;
- `uc042lib/policy.py`;
- `uc042app/ingest/analysis.py`;
- `uc042app/services/monthly.py` (`upload_package`, `_package_gate`, `submit_for_audit`).

**Related documents:**
- Field-level detail: `UC042_SCHEMA_AND_FIELD_REFERENCE.md`.
- Relationships: `UC042_CROSS_DOCUMENT_VALIDATION.md`.

**Periods.** File names are given for **September 2026 (`PER-2026-09`)**, the baseline period with registered policy v1.2. For another month, substitute `{period}` = `YYYY-MM` and `{previous}` = the previous month. The period must be processable: a registered IN-17 version must apply (`monthly.processing_limitation`). That is true from October 2025 onwards (v1.1 from 2025-10-01, v1.2 from 2026-05-07).

---

## 1. The 19 evidence categories (definitive)

| ID | Official name (`schema.py`) | Exact file name (Sep 2026) | Pattern (`period.FILE_PATTERNS`) | Type | Requirement | May be header-only | Primary key / identity |
|---|---|---|---|---|---|---|---|
| IN-01 | Reconciliation-day calendar | `recon_calendar_2026-09.csv` | `recon_calendar_{period}.csv` | CSV | REQUIRED | No | `calendar_date` |
| IN-02 | Institution and account inventory | `account_inventory.csv` | `account_inventory.csv` | CSV | REQUIRED | No | `account_id` |
| IN-03 | Client balance snapshots at each 17:00 point | `client_balance_snapshots_2026-09.csv` | `client_balance_snapshots_{period}.csv` | CSV | REQUIRED | No | `snapshot_id` |
| IN-04 | Unallocated receipts register | `unallocated_register_2026-09.csv` | `unallocated_register_{period}.csv` | CSV | REQUIRED | **Yes** | `receipt_id` |
| IN-05 | Internal reconciliation records (as reported by the firm) | `internal_recon_records_2026-09.csv` | `internal_recon_records_{period}.csv` | CSV | REQUIRED | No | `recon_run_id` |
| IN-06 | External reconciliation records (as reported by the firm) | `external_recon_records_2026-09.csv` | `external_recon_records_{period}.csv` | CSV | REQUIRED | No | `ext_recon_id` |
| IN-07 | Bank balance confirmations at 17:00 | `bank_balance_confirmations_2026-09.csv` | `bank_balance_confirmations_{period}.csv` | CSV | REQUIRED | No | `statement_id` |
| IN-08 | End-of-day bank statement headers | `bank_statements_eod_2026-09.csv` | `bank_statements_eod_{period}.csv` | CSV | REQUIRED | No | `statement_id` |
| IN-09 | Bank statement entries | `bank_statement_entries_2026-09.csv` | `bank_statement_entries_{period}.csv` | CSV | REQUIRED | No | `bank_entry_id` |
| IN-10 | Safeguarding-account cash book (firm ledger) | `sga_cashbook_entries_2026-09.csv` | `sga_cashbook_entries_{period}.csv` | CSV | REQUIRED | No | `ledger_entry_id` |
| IN-11 | Client transactions | `transactions_2026-09.csv` | `transactions_{period}.csv` | CSV | REQUIRED | No | `txn_id` |
| IN-12 | Settlement batch headers (generic synthetic format) | `settlement_batches_2026-09.csv` | `settlement_batches_{period}.csv` | CSV | REQUIRED | No | `batch_id` |
| IN-13 | Settlement batch lines | `settlement_lines_2026-09.csv` | `settlement_lines_{period}.csv` | CSV | REQUIRED | No | `line_id` |
| IN-14 | Discrepancy and corrective-action log | `discrepancy_log_2026-09.csv` | `discrepancy_log_{period}.csv` | CSV | REQUIRED | **Yes** | `discrepancy_id` |
| IN-15 | Acknowledgement letter, SGA-GBP-01 | `ack_letter_SGA-GBP-01.pdf` | `ack_letter_SGA-GBP-01.pdf` | PDF | REQUIRED | n/a | Letter reference ↔ IN-02 |
| IN-16 | Acknowledgement letter, SGA-EUR-01 | `ack_letter_SGA-EUR-01.pdf` | `ack_letter_SGA-EUR-01.pdf` | PDF | REQUIRED | n/a | Letter reference ↔ IN-02 |
| IN-17 | Safeguarding reconciliation policy v1.2 | `safeguarding_reconciliation_policy_v1.2.pdf` | `safeguarding_reconciliation_policy_v{policy}.pdf` (regex `^safeguarding_reconciliation_policy_v(\d+\.\d+)\.pdf$`) | PDF | REQUIRED | n/a | Document version |
| IN-18 | Governance register | `governance_register_2026-09.pdf` | `governance_register_{period}.pdf` | PDF | **OPTIONAL** | n/a | — |
| IN-19 | Monthly safeguarding return receipt (August) | `rep027_submission_receipt_2026-08.pdf` | `rep027_submission_receipt_{previous}.pdf` | PDF | **OPTIONAL** | n/a | Submission reference |

**IN-18 and IN-19 are optional** [CODE `schema.PDF_FILES`; `PeriodConfig.optional_ids`] [TEST `Gate.test_optional_documents_may_be_absent`]:
- **When absent:** `C16-GOVERNANCE` / `C16-RETURN` give NOT_APPLICABLE and no exception.
- **When present but unusable** (an ERROR in analysis): reported in `optional_not_usable`. This **does not block** the gate.
- **When present with a mismatched name or content:** this **does block** the gate. `mismatches` apply to every mapped file.

**IN-19 is the receipt for the *previous* month's return.** Its file name carries the previous month: `rep027_submission_receipt_2026-08.pdf` in a September package.

**The account-specific letter names are fixed.** `ack_letter_SGA-GBP-01.pdf` and `ack_letter_SGA-EUR-01.pdf` are fixed strings (`FILE_PATTERNS`, `schema.LETTER_SLOTS`). A safeguarding account with any other ID cannot have a letter slot. **The two safeguarding accounts must be `SGA-GBP-01` (GBP) and `SGA-EUR-01` (EUR).**

---

## 2. Exact CSV headers

Copy these exactly; the header row must be byte-for-byte this text. Generated from `schema.columns(fid)`.

```
IN-01 calendar_date,period_id,is_recon_day,non_recon_reason,calendar_basis
IN-02 account_id,account_class,currency,asset_pool_id,account_number_masked,designation_name,acknowledgement_letter_ref,institution_id,institution_full_name,institution_postal_address,institution_email,institution_phone,institution_role,open_date,close_date
IN-03 snapshot_id,recon_date,as_at_ts,client_id,asset_pool_id,currency,balance
IN-04 receipt_id,bank_reference,receipt_date,receipt_ts,amount,currency,classification,identified_date,allocated_date,allocated_ts,client_id
IN-05 recon_run_id,recon_date,reconciliation_point_ts,performed_at_ts,asset_pool_id,currency,method,requirement_reported,resource_reported,item_a,item_b,item_c,item_d,difference_reported,d1_requirement,d1_resource,actions_taken_text,preparer_id,reviewer_id
IN-06 ext_recon_id,recon_date,performed_at_ts,account_id,currency,ledger_balance_reported,bank_statement_id,bank_balance_reported,difference_reported,timing_difference_claimed,preparer_id
IN-07 statement_id,account_id,as_at_ts,currency,balance_amount,balance_dc_indicator,bank_statement_ref
IN-08 statement_id,account_id,statement_date,as_at_ts,currency,opening_balance_amount,opening_balance_dc,closing_balance_amount,closing_balance_dc,entry_count,bank_statement_ref
IN-09 bank_entry_id,statement_id,account_id,booking_date,booking_ts,value_date,amount,dc_indicator,currency,bank_reference,end_to_end_ref,counterparty_name,narrative_text
IN-10 ledger_entry_id,account_id,posted_ts,entry_type,amount,dc_indicator,currency,payment_reference
IN-11 txn_id,client_id,txn_type,status,auth_ts,clearing_date,executed_ts,amount,direction,currency,settlement_batch_id,payment_reference,original_txn_id
IN-12 batch_id,counterparty_type,cycle_date,settlement_date,account_id,currency,direction,gross_amount,total_fees,total_adjustments,net_amount_reported,expected_bank_reference
IN-13 line_id,batch_id,line_type,txn_id,fee_code,amount,dc_indicator,currency
IN-14 discrepancy_id,logged_ts,recon_ref,account_id,currency,amount,description,cause_category,cause_evidence_ref,funding_reference,status,resolved_ts,approver_id
```

(The IN-xx prefix and the following space are labels in this listing only; they are not part of the header.)

**Alternative column names are not accepted.**
- **Matching is exact** (`prepare.identify`: `header == schema.columns(fid)`) [TEST `test_period_and_headers.HeaderDiagnosis.*`].
- **Missing, renamed, extra, duplicated, misordered or re-cased columns** all have the same result: the file is not identified, gets an `UNRECOGNISED` ERROR with a `header_diagnosis` (expected/missing/extra/misordered/case_or_spacing), and the gate fails with a name/content mismatch.
- **There is no partial acceptance.**

---

## 3. PDF structure

**Format** [CODE `prepare.identify`, `prepare._pdf_details`, `validate.load_pdf`]:
- The file starts with `%PDF-` and is readable by `pypdf`.
- The text is extractable: **not a scanned image**. There is no OCR.
- **Key details:** one line per label, in the form `<Label>: <value>`:
  - the label starts the extracted line;
  - it is followed by a colon and one space;
  - the value is on the same line.

**Labels per type.** Every label of the type must be present.

| ID | Labels |
|---|---|
| IN-15 / IN-16 | `Letter reference`, `Institution`, `Account name`, `Account number`, `Currency`, `Letter date` |
| IN-17 | `Document version`, `Effective date`, `Safeguarding method`, `Reconciliation method`, `Reconciliation point`, `Frequency`, `Internal reconciliation basis` |
| IN-18 | `Accountable person`, `Role`, `Allocated from` |
| IN-19 | `Return`, `Period`, `Due date`, `Submitted at`, `Submission reference` |

**IN-17 is a registered document** [CODE `uc042lib/policy.py`]. For v1.2:
- `Document version: 1.2`;
- `Effective date: 2026-05-07`;
- the document text contains `SYNTHETIC DOCUMENT - UC-042 POC` (whitespace-normalised; an em dash is treated as `-`).

For use in the engine:
- `Reconciliation point: 17:00 Europe/London` (regex `^(\d{2}):(\d{2}) Europe/London$`);
- `Reconciliation method: STANDARD` and `Internal reconciliation basis: Per currency` (C03-POLICY PASS).

**Any other version, date or missing marking** gives `POLICY_NOT_RECOGNISED` (ERROR), and the gate fails. The version in the file name must equal `Document version` (`_package_gate`).

**Reference PDFs** (known to parse): `uc042_dataset/set_01_clean_baseline/supporting_documents/*.pdf`, generated by `uc042lib/generate.py::write_pdfs` with ReportLab.

---

## 4. ZIP construction rules

| Topic | Rule | Source / test |
|---|---|---|
| Archive | A standard ZIP (deflate or stored); one ZIP = one complete document set for one period | `read_package` |
| Root structure | **Flat root recommended.** Folders are allowed and flattened to the base name (`source_data/x.csv` is read as `x.csv`). | `read_package`; `Reading.test_folders_inside_the_zip_are_flattened` |
| Nested ZIP | Not accepted (unexpected → package rejected) | `Reading.test_nested_zip_is_unexpected` |
| File names | Exactly the names in §1: case-sensitive, no spaces, no prefixes or suffixes such as `(1)` or `copy_` | `map_filename`, `PeriodConfig.file_id_of` |
| Extensions | `.csv` / `.pdf` as part of the exact name (lower case) | same |
| Required documents | All 17 (IN-01…IN-17), each exactly once | `_package_gate` |
| Optional documents | IN-18, IN-19: zero or one each | `_package_gate` |
| Duplicate file name | The same base name twice (in different folders, or differing only in case) → `duplicate_names` → package rejected | `Gate.test_duplicate_flattened_names_reject` |
| Duplicate category | Two files mapping to one ID (for example two IN-17 versions) → `duplicate_types` → package rejected | `Gate.test_duplicate_document_type_rejects` |
| Unknown file | Any other file (README, manifest.csv, .txt, a file for another month) → `unexpected` → **whole package rejected, nothing analysed** | `Gate.test_unexpected_file_rejects_the_whole_package_without_analysis` |
| OS metadata | `__MACOSX/`, `._*`, `.DS_Store`, `Thumbs.db`, `desktop.ini`, `ehthumbs.db` are listed as ignored and do not reject | `Reading.test_operating_system_metadata_is_listed_and_ignored` |
| Unsafe entries | Absolute paths, `..`, drive letters, NUL, symlinks, encryption → rejected | `Reading.test_unsafe_entries_reject_every_file`, `test_symlink_and_encrypted_entries_are_unsafe` |
| Limits (defaults) | ≤ 40 file entries; ≤ 50 MB per file uncompressed; ≤ 200 MB total; compression ratio ≤ 200:1; ZIP ≤ 100 MB. Overridable by `UC042_ZIP_MAX_*`. | `ZipLimits`; `Reading.test_limits_*` |
| Empty file (0 bytes) | `EMPTY_FILE` ERROR → gate fails | `analysis.analyse_file` |
| CSV encoding | UTF-8, BOM optional. Other encodings → UNRECOGNISED. | `structure.read_csv` |
| CSV delimiter and quoting | Comma; double-quote fields that contain a comma, quote or newline; escape a quote by doubling it; LF or CRLF | Python `csv` default dialect |
| Header row | Exactly one, first line, exact text (§2) | `prepare.identify` |
| Data rows | At least 1 (IN-04 and IN-14 may have 0) | `analysis.analyse_csv` |
| Dates | `YYYY-MM-DD` | `structure.field_error` |
| Timestamps | `YYYY-MM-DDTHH:MM:SS±HH:MM`, using the **Europe/London offset of that instant** (`+01:00` in BST, `+00:00` in GMT). Do not use `Z` or omit the offset; `Z` parses but fails the 17:00 point check on IN-07. | `structure.parse_ts`; `Validator.check_policy_and_points` |
| Amounts | `amount` `^\d+\.\d{2}$`; `signed` `^-?\d+\.\d{2}$`. No `,` `£` `€`, spaces or `+`. | `money.py` |
| Booleans | `true` / `false` | `structure.field_error` |
| Currencies | `GBP`, `EUR` | `structure.CURRENCIES` |
| Identifiers | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` (no spaces, no `/`) | `structure.ID_RE` |
| Empty values | Empty field = missing. Write nothing between the commas; never write `NULL`, `N/A`, `-` or `0` for missing. | `structure.check_rows` |
| Whitespace | Never pad values; nothing is trimmed | `structure.check_rows` |
| PDF | Text-based, with the key-detail lines of §3 | §3 |

---

## 5. Example ZIP tree (September 2026)

```
uc042_PER-2026-09_submission.zip        (the ZIP's own name is free text; it is recorded, not interpreted)
├── recon_calendar_2026-09.csv
├── account_inventory.csv
├── client_balance_snapshots_2026-09.csv
├── unallocated_register_2026-09.csv
├── internal_recon_records_2026-09.csv
├── external_recon_records_2026-09.csv
├── bank_balance_confirmations_2026-09.csv
├── bank_statements_eod_2026-09.csv
├── bank_statement_entries_2026-09.csv
├── sga_cashbook_entries_2026-09.csv
├── transactions_2026-09.csv
├── settlement_batches_2026-09.csv
├── settlement_lines_2026-09.csv
├── discrepancy_log_2026-09.csv
├── ack_letter_SGA-GBP-01.pdf
├── ack_letter_SGA-EUR-01.pdf
├── safeguarding_reconciliation_policy_v1.2.pdf
├── governance_register_2026-09.pdf              (optional)
└── rep027_submission_receipt_2026-08.pdf        (optional)
```

The tree contains no `manifest.csv`, README or answer key: any of these would be `unexpected` and reject the package. A tree with `source_data/` and `supporting_documents/` folders (the dataset layout) is equivalent, because folders are flattened.

---

## 6. Gate outcomes (what the user sees)

| Batch status | Meaning | Can Submit for Audit? |
|---|---|---|
| `PACKAGE_REJECTED` | The archive is unreadable, or it has unsafe entries, unexpected files or duplicates. **No document was analysed.** | No (409 `PACKAGE_NOT_COMPLETE`) |
| `PACKAGE_INCOMPLETE` | Documents were analysed, but a required type is missing, name and content disagree, or a required document has an ERROR | No |
| `VALIDATED` | The gate passed (warnings allowed) | Yes. Each submit creates a new `SUB-…` and `RUN-…`. |

**After a submit** the run can still be `FAILED`:
- if case preparation finds a required file MISSING, AMBIGUOUS or REJECTED; or
- if the pack fails validation (`_process`).

**Row-level data errors do not fail the run.** They are excluded and reported as DQ-FIELD / DQ-PERIOD exceptions in the pack.
