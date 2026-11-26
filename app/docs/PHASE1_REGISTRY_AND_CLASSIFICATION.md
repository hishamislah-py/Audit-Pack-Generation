# UC-042 Smart Parser: Phase 1 implementation report

**Authoritative mapping registry and baseline content classification. 18 November 2026.**

## Summary

**What exists now:**
- The Smart Parser has a registry of all 19 UC-042 evidence categories, **generated from the UC-042 code itself** (`uc042lib/schema.py` and six modules it relies on).
- Every column, label, type, enumeration and rule records the UC-042 symbol it came from.
- Every definition carries the SHA-256 of each UC-042 module that was read.
- A `--check` command proves that the shipped registry still matches the code.

**How classification works:** it runs on content only. A CSV is recognised by its exact canonical header. A PDF is recognised by its complete key-detail label set. The GBP/EUR letters are told apart through the account inventory's letter reference, and the policy is identified with its version. Image-only (scanned) PDFs are reported as unsupported.

**Measured on every available evidence file:**

| | Files | Correct | Incorrect | Unknown | Ambiguous |
|---|---|---|---|---|---|
| All | 445 (137 distinct contents) | 445 | 0 | 0 | 0 |
| CSV (IN-01 to IN-14) | 350 | 350 | 0 | 0 | 0 |
| PDF (IN-15 to IN-19) | 95 | 95 | 0 | 0 | 0 |

The files cover 25 dataset folders: 9 September 2026 sets and the January–August 2026 history, of which there are two copies. All 19 categories and 9 reporting periods are covered.

The ground truth for each file is the dataset's own manifest. UC-042's own content identification agrees with it for all 445 files.

**Read this result narrowly.** It shows that the classifier recognises the canonical files UC-042 generates. It does **not** show tolerance of renamed columns or third-party formats:
- Every CSV in the corpus has one layout per category.
- The 95 PDFs are only 6 distinct documents.

Near-miss headers are diagnosed but deliberately not accepted. See section D.

**Tests:** 136 pass, made up of 62 existing, 9 new registry tests and 65 new classification tests. Without the UC-042 tree, 133 pass and 3 skip.

**What was left untouched:**
- UC-042 code: 107 files, verified by hash.
- Datasets: 624 files.
- Clone E.
- The original Smart Parser on the Desktop: 63 files.

All work is in the isolated copy `C:\Users\artlptp263user\p10\smartparser_phase1`.

## 1. Inspection findings

### 1.1 The standalone Smart Parser before Phase 1

The project is `C:\Users\artlptp263user\Desktop\hr-projects\smartparser`. It is **not a git repository**, so I worked on a copy, `p10\smartparser_phase1`. The copy was verified identical (63 files) before any change.

| Module | Package | State found |
|---|---|---|
| A Intake | `intake/` | SHA-256, content-addressed store, duplicate and period tracking |
| B Identification | `identify/` | Format from magic bytes (never the extension); encoding (BOM, strict UTF-8, then charset-normalizer); delimiter detection |
| C Classification | `classify/csv_classifier.py` | Header **scoring** over mapping tiers 1–3 (exact name, alias, normalised name), with `MIN_SCORE` 0.5, `MIN_MARGIN` 0.15 and validated templates. It never uses the filename. |
| D CSV engine | `csv_engine/` | Structural reader: original strings, line numbers, preamble, ragged and empty rows, duplicate headers |
| E Schema registry | `schemas/` | Loads one JSON per category. **All 19 `IN-xx.json` were empty stubs** (`verification_status: missing`, "awaiting authoritative UC-042 schema manifest"). |
| F Mapping | `mapping/` | Tiers exact, alias, normalised, template; AI advisory |
| G PDF engine | `pdf_engine/` | **Interface stub** that raised `NotImplementedError` |
| H Normalisation | `normalise/` | Decimal, date and currency normalisers |
| I Validation | `validation/` | Per-cell issues |
| J AI | `ai/` | Protocol and `NullAssistant` only |

- **Orchestration:** `pipeline.py` runs intake, identification, CSV read, classification, mapping, normalisation and validation. A PDF went straight to `not_implemented`.
- **Tests:** 62 tests, all against three synthetic `TST-*` schemas. No real UC-042 file was tested, and all 62 passed.

### 1.2 UC-042 authoritative definitions

Source: the isolated copy `p10\uc042_token_optimisation`, inspected 18 Nov 2026, read-only.

| Module | What it defines, and what the registry takes from it |
|---|---|
| `uc042lib/schema.py` | `CSV_FILES`: 14 categories, **153 columns**, each with name, type code, requiredness M/C/O and description. `PDF_FILES`: 5 categories with REQUIRED/OPTIONAL and label lists. Also `ENUMS`, `CONDITIONAL`, `EMPTY_ALLOWED`, `SCOPE_FILES`, `LETTER_SLOTS`, `DEPENDS` (checks per file), `PERIOD_RULES` and `PERIOD_UNCHECKED`. |
| `uc042lib/period.py` | `FILE_PATTERNS` (canonical file names per period; recorded as information only, never used to classify) and `PeriodConfig` |
| `uc042lib/structure.py` | `field_error` (the value rules), `ID_RE`, `INT_RE` and `CURRENCIES`. `read_csv` reads UTF-8 with an optional BOM. `check_rows` takes the first column as the primary key. `diagnose_header` explains a rejected header and never accepts one. |
| `uc042lib/money.py` | `UNSIGNED_RE` and `SIGNED_RE` (2 dp, `.` decimal, no separators) |
| `uc042lib/policy.py` | `POLICY_VERSIONS`: v1.1 (illustrative, effective 2025-10-01) and v1.2 (effective 2026-05-07), each with required markings. `recognise` checks version, effective date and markings. `select` chooses which version governs a period. |
| `uc042lib/prepare.py` | `identify`, the UC-042 identification rule:<br>- a CSV header must **equal** one `schema.columns(fid)`;<br>- a PDF must be readable and contain every label as a `^Label: (.+)$` line;<br>- IN-15 and IN-16 share labels, and the slot comes from IN-02 `acknowledgement_letter_ref`;<br>- IN-17 goes through `policy.recognise`. |
| `uc042app/ingest/analysis.py` | `REQUIRED_IDS` / `OPTIONAL_IDS`, `RECURRING_IDS` and `PDF_DATE_ROLES` (label meanings) |

The earlier reports (data discovery, 16 Nov; deterministic parser review, 18 Nov) were **re-verified against the code**, not assumed:
- UC-042 has no aliases.
- CSV identity is exact header equality.
- PDF identity is a complete label set.
- There are 153 columns.

All four still hold in the current code.

### 1.3 Datasets found in the isolated copy

| Location | Datasets | Evidence files |
|---|---|---|
| `uc042_dataset/` | 9 September 2026 sets: `set_01_clean_baseline` and 8 scenarios, S02 to SC5D | 171 |
| `demo_history/datasets/2026-01` … `2026-08` | 8 historical months | 137 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/…/2026-0n/source_documents` | The same 8 months (zip copy) | 137 |
| **Total** | **25 dataset folders, each with its own `manifest.csv`** | **445 (137 distinct)** |

`validation/` folders hold engine outputs, not evidence, and were excluded. IN-18 and IN-19 occur only in the September sets. May 2026 supplies policy v1.1 **and** v1.2.

## 2. What was built

### 2.1 Registry: controlled generation from UC-042

The importer is `smartparser/registry_import/uc042.py`:

```
python -m smartparser import-registry --uc042-root <UC-042 dir>           # writes the 19 IN-xx.json
python -m smartparser import-registry --uc042-root <UC-042 dir> --check   # "in sync: 19 definitions match"
```

**Reading the source:**
- It imports the UC-042 modules from the given root, with bytecode writing off, and checks they were loaded from that root.
- Every value is read from them. Nothing is hand-typed: columns, order, types, requiredness, enumerations, conditional rules, primary key, empty-allowed, scope files, period rules, consumed-by checks, PDF labels and roles, shared label groups, letter-slot accounts and policy versions with their markings.
- Two value rules are written **inline** in `structure.field_error` rather than as named constants: the date regex and `true`/`false`. The importer checks that they are still present in the source text and fails if not.
- The importer also fails if `prepare._pdf_details` stops using the documented label regex.

**Provenance:**
- Each field lists its provenance, for example `uc042lib.schema.CSV_FILES['IN-10'][2][3]`, `uc042lib.money.UNSIGNED_RE` and `uc042lib.schema.ENUMS[('IN-10', 'entry_type')]`.
- Each definition records `provenance.definition` (the exact source symbol), the generator version and the SHA-256 of all 7 source modules.

**What is translated, and what is left undefined:**
- **The one translation:** UC-042 type codes map to Smart Parser `FieldType` (`id`/`str`/`enum` to `string`, `ts` to `datetime`, `amount`/`signed` to `decimal`, and so on). The UC-042 code is always kept in `source_type`, and the value rules attached are UC-042's own.
- **Nothing is invented:**
  - PDF label value types are undefined in UC-042, so they stay `null`. Each PDF definition lists this under `unresolved`.
  - IN-14 `cause_category` is declared an enum with no values, so no values were added; it is recorded as unresolved.
  - Policy *selection* (which version governs a month) is a period decision, not file classification. It is recorded as not applied.
- **Requiredness:** every UC-042 column must be present, because the header must be exact, so `required = true`. `nullable` is true unless the column is M. The UC-042 M/C/O value is kept in `requiredness`, and conditional rules are kept verbatim.

**Load-time safeguards:**
- Two exact headers that are equal are rejected.
- Two PDF label sets that are equal without being declared a shared group are rejected.
- `exact_header` matching without a CSV contract is rejected.

### 2.2 Content-based classification

**CSV:** `classify/csv_classifier.py`, with the `exact_header` policy for the generated schemas.
- **Match rule:** the header row exactly as read, with case, spacing and order intact, must equal one canonical header. The 14 headers are distinct, so an exact match is never ambiguous.
- **Content check:** the data rows are then checked against the field rules (mandatory values, patterns, allowed values, ISO date, timestamp with offset). This is informational. UC-042 identifies by header, and row errors are its data-quality findings, so a nonconforming row adds a warning but never changes the category.
- **Near misses:** missing, extra, reordered, re-cased or spaced, or duplicate columns are **not accepted**. The result is `unknown`, or `ambiguous` when two categories are about equally close. The diagnosis names the closest category and the differences, using the same thresholds as UC-042's `diagnose_header`.
- **Serialisation:** an exact header in a non-canonical serialisation (other delimiter, non-UTF-8, lines before the header) is identified **and flagged** (`canonical_serialisation: false`). A UTF-8 BOM counts as canonical. This is a deliberate difference from UC-042 and is raised in D-1.
- **Synthetic schemas:** they keep the original scoring path unchanged.

**PDF:** `pdf_engine/` and `classify/pdf_classifier.py`.
- **Engine:** pypdf, the library UC-042 uses, extracts selectable text per page and counts image XObjects.
- **Text checks:**
  - No text but images: `unknown`, `unsupported = image_only_pdf` ("OCR is not supported").
  - No text and no images: `pdf_no_text`.
  - Unreadable: `pdf_unreadable`.
- **Labels:** each label must be a line `Label: value`.
  - One complete label set identifies the category.
  - Partial sets give `unknown`, with the closest category and the missing labels.
  - Two complete sets give `ambiguous`.
- **IN-17:** the version must also be recognised, exactly as `policy.recognise` does: registered version, its effective date, and required markings in whitespace-normalised text. Otherwise the result is `unknown` with `POLICY_NOT_RECOGNISED` and the reasons. The identified version (1.1 or 1.2) and its classification are returned.
- **IN-15 / IN-16:** the label sets are identical. The slot is the one whose account (`SGA-GBP-01` or `SGA-EUR-01`, from `LETTER_SLOTS`) has `acknowledgement_letter_ref` equal to the letter's `Letter reference` in an account inventory. Without an inventory, or with an unmatched reference, the result is `ambiguous`. The letter's own `Currency` and `Account name` values are recorded but **not used**, because UC-042 does not use them. A test proves it: swapping the inventory references swaps the slot even though the PDF says GBP.

**Entry points:** `classify/evidence.py`.
- `classify_bytes(data, registry)` takes **bytes only**, so no filename or extension can reach the decision.
- `classify_batch(items, registry)` classifies a set. If exactly one file in the set is identified (by header) as IN-02, its letter references resolve the letters. With two inventories, nothing is resolved and a warning says so. This is the only cross-file step, and it is UC-042's own rule. No other relationship mapping is done.

**Pipeline:**
- The CSV path now passes the raw header and rows to the classifier.
- PDFs are classified, and `document_fields` holds the extracted label values.
- PDF field extraction and validation are still Phase 3, so the PDF `processing_status` stays `not_implemented`.
- New issue codes: `pdf_image_only`, `pdf_no_text`, `pdf_unreadable` and `pdf_policy_not_recognised`.

### 2.3 Ground truth for the baseline

The baseline tool is `tools/baseline_classification.py`. It is read-only on UC-042. For each file:

1. **Declared:** the `file_id` the dataset's own `manifest.csv` gives the file's relative path. This is the generator's record of what it wrote, not a guess from the filename.
2. **UC-042 oracle:** UC-042's own content identification run on the file, using `prepare.identify`, the IN-02 letter resolution of `prepare_case`, and `policy.recognise`.
3. The expected category is (1). A file is flagged `CONFLICT` when (2) disagrees. **No conflicts were found.**
4. **Actual:** `classify_batch` over the dataset, keyed by opaque IDs.
5. **Pipeline cross-check:** `SmartParser.process_bytes` with the neutral filename `upload.dat`. It reached the same category for 445 of 445 files.

## A. Registry completeness

All 19 categories, generated from UC-042 (source symbol per category in the last column; per-field provenance is in each IN-xx.json).

### A.1 Category overview

| ID | Smart Parser title | UC-042 official name | Format | Requirement | Columns / labels | Mandatory / conditional / optional | Primary key | Empty allowed | Source definition |
|---|---|---|---|---|---|---|---|---|---|
| IN-01 | Reconciliation calendar | Reconciliation-day calendar | CSV | REQUIRED | 5 | 4 / 1 / 0 | calendar_date | no | `uc042lib.schema.CSV_FILES['IN-01']` |
| IN-02 | Account inventory | Institution and account inventory | CSV | REQUIRED | 15 | 11 / 3 / 1 | account_id | no | `uc042lib.schema.CSV_FILES['IN-02']` |
| IN-03 | Client balance snapshots | Client balance snapshots at each 17:00 point | CSV | REQUIRED | 7 | 7 / 0 / 0 | snapshot_id | no | `uc042lib.schema.CSV_FILES['IN-03']` |
| IN-04 | Unallocated receipts | Unallocated receipts register | CSV | REQUIRED | 11 | 7 / 4 / 0 | receipt_id | yes | `uc042lib.schema.CSV_FILES['IN-04']` |
| IN-05 | Internal reconciliation records | Internal reconciliation records (as reported by the firm) | CSV | REQUIRED | 19 | 16 / 2 / 1 | recon_run_id | no | `uc042lib.schema.CSV_FILES['IN-05']` |
| IN-06 | External reconciliation records | External reconciliation records (as reported by the firm) | CSV | REQUIRED | 11 | 11 / 0 / 0 | ext_recon_id | no | `uc042lib.schema.CSV_FILES['IN-06']` |
| IN-07 | Bank balance confirmations | Bank balance confirmations at 17:00 | CSV | REQUIRED | 7 | 6 / 0 / 1 | statement_id | no | `uc042lib.schema.CSV_FILES['IN-07']` |
| IN-08 | End-of-day statement headers | End-of-day bank statement headers | CSV | REQUIRED | 11 | 10 / 0 / 1 | statement_id | no | `uc042lib.schema.CSV_FILES['IN-08']` |
| IN-09 | Statement entries | Bank statement entries | CSV | REQUIRED | 13 | 10 / 1 / 2 | bank_entry_id | no | `uc042lib.schema.CSV_FILES['IN-09']` |
| IN-10 | Safeguarding cash book | Safeguarding-account cash book (firm ledger) | CSV | REQUIRED | 8 | 8 / 0 / 0 | ledger_entry_id | no | `uc042lib.schema.CSV_FILES['IN-10']` |
| IN-11 | Client transactions | Client transactions | CSV | REQUIRED | 13 | 8 / 5 / 0 | txn_id | no | `uc042lib.schema.CSV_FILES['IN-11']` |
| IN-12 | Settlement batches | Settlement batch headers (generic synthetic format) | CSV | REQUIRED | 12 | 12 / 0 / 0 | batch_id | no | `uc042lib.schema.CSV_FILES['IN-12']` |
| IN-13 | Settlement lines | Settlement batch lines | CSV | REQUIRED | 8 | 6 / 2 / 0 | line_id | no | `uc042lib.schema.CSV_FILES['IN-13']` |
| IN-14 | Discrepancy log | Discrepancy and corrective-action log | CSV | REQUIRED | 13 | 8 / 0 / 5 | discrepancy_id | yes | `uc042lib.schema.CSV_FILES['IN-14']` |
| IN-15 | GBP safeguarding account acknowledgement letter | Acknowledgement letter, SGA-GBP-01 | PDF | REQUIRED | 6 | n/a (labels) | n/a | n/a | `uc042lib.schema.PDF_FILES['IN-15']` |
| IN-16 | EUR safeguarding account acknowledgement letter | Acknowledgement letter, SGA-EUR-01 | PDF | REQUIRED | 6 | n/a (labels) | n/a | n/a | `uc042lib.schema.PDF_FILES['IN-16']` |
| IN-17 | Reconciliation policy | Safeguarding reconciliation policy v1.2 | PDF | REQUIRED | 7 | n/a (labels) | n/a | n/a | `uc042lib.schema.PDF_FILES['IN-17']` |
| IN-18 | Governance register | Governance register | PDF | OPTIONAL | 3 | n/a (labels) | n/a | n/a | `uc042lib.schema.PDF_FILES['IN-18']` |
| IN-19 | Previous month's return receipt | Monthly safeguarding return receipt (August) | PDF | OPTIONAL | 5 | n/a (labels) | n/a | n/a | `uc042lib.schema.PDF_FILES['IN-19']` |

### A.2 CSV contracts (IN-01 to IN-14): canonical header in order, with type and requiredness

Type codes are UC-042's own (`id, str, date, ts, bool, int, amount, signed, ccy, enum`). Requiredness: M mandatory, C conditional, O optional. Every column must be present (exact header); requiredness is about the value.

**IN-01 - Reconciliation-day calendar** (canonical file name pattern, informational only: `recon_calendar_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `calendar_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 1 | `period_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `is_recon_day` | bool | M | `^(true|false)$` |  |
| 3 | `non_recon_reason` | enum | C | one of FOREIGN_MARKET_CLOSED, UK_BANK_HOLIDAY, WEEKEND | required when is_recon_day is false |
| 4 | `calendar_basis` | str | M | - |  |

- period rule `{"in_period": ["calendar_date"], "equals": {"period_id": "PER-2026-09"}}`
- used by checks: C01-COVER, C04-REQUIREMENT, C05-RESOURCE, C06-DIFFERENCE, C07-BANK-EVIDENCE, C07-COVER, C08-DIFFERENCE, C14-COVER, DQ22-CONTINUITY

**IN-02 - Institution and account inventory** (canonical file name pattern, informational only: `account_inventory.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `account_class` | enum | M | one of OWN_FUNDS, RELEVANT_FUNDS_BANK |  |
| 2 | `currency` | ccy | M | one of EUR, GBP |  |
| 3 | `asset_pool_id` | id | C | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` | required for safeguarding accounts |
| 4 | `account_number_masked` | str | M | - |  |
| 5 | `designation_name` | str | C | - | required for safeguarding accounts |
| 6 | `acknowledgement_letter_ref` | str | C | - | required for safeguarding accounts |
| 7 | `institution_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 8 | `institution_full_name` | str | M | - |  |
| 9 | `institution_postal_address` | str | M | - |  |
| 10 | `institution_email` | str | M | - |  |
| 11 | `institution_phone` | str | M | - |  |
| 12 | `institution_role` | enum | M | one of RELEVANT_FUNDS_BANK |  |
| 13 | `open_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 14 | `close_date` | date | O | `^\d{4}-\d{2}-\d{2}$` |  |

- not period-checked: open_date/close_date describe the account, not period activity
- used by checks: BANK-CASH-LINK, C01-COVER, C05-RESOURCE, C06-DIFFERENCE, C07-BANK-EVIDENCE, C07-COVER, C08-DIFFERENCE, C09-ALLOCATION, C10-DESIGNATION, C11-BANK-ENTRY, C11-BATCH-BANK, C13-CURRENCY, C14-COVER, CASH-BANK-LINK, FUND-TOPUP, RC2-LEDGER, RC4-DIRECT
- relationships (recorded, not enforced in Phase 1): `acknowledgement_letter_ref` -> IN-16.Letter reference (letter_slot_resolution); `acknowledgement_letter_ref` -> IN-15.Letter reference (letter_slot_resolution)

**IN-03 - Client balance snapshots at each 17:00 point** (canonical file name pattern, informational only: `client_balance_snapshots_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `snapshot_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `recon_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 2 | `as_at_ts` | ts | M | ISO 8601 with UTC offset |  |
| 3 | `client_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 4 | `asset_pool_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 5 | `currency` | ccy | M | one of EUR, GBP |  |
| 6 | `balance` | signed | M | `^-?\d+\.\d{2}$` |  |

- period rule `{"in_period": ["recon_date"], "permitted": [{"recon_date": "2026-08-31", "as_at_ts": "2026-08-31T17:00:00+01:00"}]}`
- not period-checked: as_at_ts is checked against the reconciliation point by C03 instead
- used by checks: C04-REQUIREMENT, C06-DIFFERENCE, CBAL-NONNEG, CBAL-ROLLFWD

**IN-04 - Unallocated receipts register** (canonical file name pattern, informational only: `unallocated_register_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `receipt_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `bank_reference` | str | M | - |  |
| 2 | `receipt_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 3 | `receipt_ts` | ts | M | ISO 8601 with UTC offset |  |
| 4 | `amount` | amount | M | `^\d+\.\d{2}$` |  |
| 5 | `currency` | ccy | M | one of EUR, GBP |  |
| 6 | `classification` | enum | M | one of UNALLOCATED, UNIDENTIFIED |  |
| 7 | `identified_date` | date | C | `^\d{4}-\d{2}-\d{2}$` |  |
| 8 | `allocated_date` | date | C | `^\d{4}-\d{2}-\d{2}$` |  |
| 9 | `allocated_ts` | ts | C | ISO 8601 with UTC offset | required when allocated_date is set |
| 10 | `client_id` | id | C | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` | required when allocated_date is set |

- period rule `{"open_during_period": {"start": ["receipt_date", "receipt_ts"], "end": ["allocated_date", "allocated_ts"]}}`
- not period-checked: identified_date is not used by any calculation; receipt and allocation dates follow the open-during-period rule
- used by checks: C04-REQUIREMENT, C06-DIFFERENCE, C09-ALLOCATION, C11-BANK-ENTRY, RC4-DIRECT

**IN-05 - Internal reconciliation records (as reported by the firm)** (canonical file name pattern, informational only: `internal_recon_records_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `recon_run_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `recon_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 2 | `reconciliation_point_ts` | ts | M | ISO 8601 with UTC offset |  |
| 3 | `performed_at_ts` | ts | M | ISO 8601 with UTC offset |  |
| 4 | `asset_pool_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 5 | `currency` | ccy | M | one of EUR, GBP |  |
| 6 | `method` | enum | M | one of NON_STANDARD, STANDARD |  |
| 7 | `requirement_reported` | signed | M | `^-?\d+\.\d{2}$` |  |
| 8 | `resource_reported` | signed | M | `^-?\d+\.\d{2}$` |  |
| 9 | `item_a` | signed | M | `^-?\d+\.\d{2}$` |  |
| 10 | `item_b` | signed | M | `^-?\d+\.\d{2}$` |  |
| 11 | `item_c` | signed | M | `^-?\d+\.\d{2}$` |  |
| 12 | `item_d` | signed | M | `^-?\d+\.\d{2}$` |  |
| 13 | `difference_reported` | signed | M | `^-?\d+\.\d{2}$` |  |
| 14 | `d1_requirement` | signed | C | `^-?\d+\.\d{2}$` |  |
| 15 | `d1_resource` | signed | C | `^-?\d+\.\d{2}$` |  |
| 16 | `actions_taken_text` | str | M | - |  |
| 17 | `preparer_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 18 | `reviewer_id` | id | O | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |

- period rule `{"in_period": ["recon_date"]}`
- not period-checked: reconciliation_point_ts is checked by C03; performed_at_ts is not used
- used by checks: C01-COVER, C04-REQUIREMENT, C05-RESOURCE, C06-DIFFERENCE

**IN-06 - External reconciliation records (as reported by the firm)** (canonical file name pattern, informational only: `external_recon_records_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `ext_recon_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `recon_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 2 | `performed_at_ts` | ts | M | ISO 8601 with UTC offset |  |
| 3 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 4 | `currency` | ccy | M | one of EUR, GBP |  |
| 5 | `ledger_balance_reported` | signed | M | `^-?\d+\.\d{2}$` |  |
| 6 | `bank_statement_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 7 | `bank_balance_reported` | signed | M | `^-?\d+\.\d{2}$` |  |
| 8 | `difference_reported` | signed | M | `^-?\d+\.\d{2}$` |  |
| 9 | `timing_difference_claimed` | bool | M | `^(true|false)$` |  |
| 10 | `preparer_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |

- period rule `{"in_period": ["recon_date"]}`
- not period-checked: performed_at_ts is not used
- used by checks: C07-BANK-EVIDENCE, C07-COVER, C08-DIFFERENCE, RC2-LEDGER
- relationships (recorded, not enforced in Phase 1): `bank_statement_id` -> IN-07 (documented_reference)

**IN-07 - Bank balance confirmations at 17:00** (canonical file name pattern, informational only: `bank_balance_confirmations_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `statement_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `as_at_ts` | ts | M | ISO 8601 with UTC offset |  |
| 3 | `currency` | ccy | M | one of EUR, GBP |  |
| 4 | `balance_amount` | amount | M | `^\d+\.\d{2}$` |  |
| 5 | `balance_dc_indicator` | enum | M | one of C, D |  |
| 6 | `bank_statement_ref` | str | O | - |  |

- period rule `{"in_period": ["as_at_ts"]}`
- used by checks: BC-VS-EOD, C07-BANK-EVIDENCE, C08-DIFFERENCE, C11-BATCH-BANK, CASH-BANK-LINK, FUND-TOPUP, RC4-DIRECT

**IN-08 - End-of-day bank statement headers** (canonical file name pattern, informational only: `bank_statements_eod_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `statement_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `statement_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 3 | `as_at_ts` | ts | M | ISO 8601 with UTC offset |  |
| 4 | `currency` | ccy | M | one of EUR, GBP |  |
| 5 | `opening_balance_amount` | amount | M | `^\d+\.\d{2}$` |  |
| 6 | `opening_balance_dc` | enum | M | one of C, D |  |
| 7 | `closing_balance_amount` | amount | M | `^\d+\.\d{2}$` |  |
| 8 | `closing_balance_dc` | enum | M | one of C, D |  |
| 9 | `entry_count` | int | M | `^\d+$` |  |
| 10 | `bank_statement_ref` | str | O | - |  |

- period rule `{"in_period": ["statement_date"]}`
- not period-checked: as_at_ts is not used
- used by checks: BC-VS-EOD, C11-BATCH-BANK, CASH-BANK-LINK, DQ22-CONTINUITY, DQ23-STATEMENT, FUND-TOPUP, RC4-DIRECT
- relationships (recorded, not enforced in Phase 1): `entry_count` -> IN-09 (documented_reference)

**IN-09 - Bank statement entries** (canonical file name pattern, informational only: `bank_statement_entries_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `bank_entry_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `statement_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 3 | `booking_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 4 | `booking_ts` | ts | M | ISO 8601 with UTC offset |  |
| 5 | `value_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 6 | `amount` | amount | M | `^\d+\.\d{2}$` |  |
| 7 | `dc_indicator` | enum | M | one of C, D |  |
| 8 | `currency` | ccy | M | one of EUR, GBP |  |
| 9 | `bank_reference` | str | M | - |  |
| 10 | `end_to_end_ref` | str | C | - |  |
| 11 | `counterparty_name` | str | O | - |  |
| 12 | `narrative_text` | str | O | - |  |

- period rule `{"in_period": ["booking_date", "booking_ts"]}`
- not period-checked: value_date is not used (A3: a 30 Sep booking with an October value date is plausible; the spec is silent)
- used by checks: BANK-CASH-LINK, BC-VS-EOD, C09-ALLOCATION, C11-BANK-ENTRY, C11-BATCH-BANK, CASH-BANK-LINK, DQ23-STATEMENT, FUND-TOPUP, RC4-DIRECT

**IN-10 - Safeguarding-account cash book (firm ledger)** (canonical file name pattern, informational only: `sga_cashbook_entries_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `ledger_entry_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `posted_ts` | ts | M | ISO 8601 with UTC offset |  |
| 3 | `entry_type` | enum | M | one of ACQUIRER_SETTLEMENT, BANK_LOAD, OPENING_BALANCE, OWN_FUNDS_TOPUP, REDEMPTION, SCHEME_SETTLEMENT, UNALLOCATED_RECEIPT |  |
| 4 | `amount` | amount | M | `^\d+\.\d{2}$` |  |
| 5 | `dc_indicator` | enum | M | one of C, D |  |
| 6 | `currency` | ccy | M | one of EUR, GBP |  |
| 7 | `payment_reference` | str | M | - |  |

- period rule `{"in_period": ["posted_ts"], "permitted": [{"entry_type": "OPENING_BALANCE", "posted_ts": "2026-08-31T17:00:00+01:00"}]}`
- used by checks: BANK-CASH-LINK, C05-RESOURCE, C06-DIFFERENCE, C08-DIFFERENCE, C11-BANK-ENTRY, CASH-BANK-LINK, FUND-TOPUP, RC2-LEDGER

**IN-11 - Client transactions** (canonical file name pattern, informational only: `transactions_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `txn_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `client_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `txn_type` | enum | M | one of LOAD_BANK, LOAD_CARD, REDEMPTION, REFUND, SPEND |  |
| 3 | `status` | enum | M | one of EXECUTED, SETTLED |  |
| 4 | `auth_ts` | ts | C | ISO 8601 with UTC offset |  |
| 5 | `clearing_date` | date | C | `^\d{4}-\d{2}-\d{2}$` |  |
| 6 | `executed_ts` | ts | M | ISO 8601 with UTC offset |  |
| 7 | `amount` | amount | M | `^\d+\.\d{2}$` |  |
| 8 | `direction` | enum | M | one of CR, DR |  |
| 9 | `currency` | ccy | M | one of EUR, GBP |  |
| 10 | `settlement_batch_id` | id | C | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` | required for card transactions |
| 11 | `payment_reference` | str | C | - | required for bank loads and redemptions |
| 12 | `original_txn_id` | id | C | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` | required for refunds |

- period rule `{"in_period": ["executed_ts"]}`
- not period-checked: auth_ts and clearing_date are not used (A4: an August authorisation settled in September is plausible)
- used by checks: C09-ALLOCATION, C11-BANK-ENTRY, C11-BATCH-ARITH, C11-TXN-LINE, C12-REFUND, CBAL-ROLLFWD, RC4-DIRECT

**IN-12 - Settlement batch headers (generic synthetic format)** (canonical file name pattern, informational only: `settlement_batches_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `batch_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `counterparty_type` | enum | M | one of ACQUIRER, SCHEME |  |
| 2 | `cycle_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 3 | `settlement_date` | date | M | `^\d{4}-\d{2}-\d{2}$` |  |
| 4 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 5 | `currency` | ccy | M | one of EUR, GBP |  |
| 6 | `direction` | enum | M | one of FROM_FIRM, TO_FIRM |  |
| 7 | `gross_amount` | amount | M | `^\d+\.\d{2}$` |  |
| 8 | `total_fees` | amount | M | `^\d+\.\d{2}$` |  |
| 9 | `total_adjustments` | amount | M | `^\d+\.\d{2}$` |  |
| 10 | `net_amount_reported` | amount | M | `^\d+\.\d{2}$` |  |
| 11 | `expected_bank_reference` | str | M | - |  |

- period rule `{"in_period": ["settlement_date"]}`
- not period-checked: cycle_date is not used (A5: a cycle may precede its settlement date)
- used by checks: C11-BANK-ENTRY, C11-BATCH-ARITH, C11-BATCH-BANK, C11-TXN-LINE, FUND-TOPUP

**IN-13 - Settlement batch lines** (canonical file name pattern, informational only: `settlement_lines_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `line_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `batch_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 2 | `line_type` | enum | M | one of FEE, REFUND, TXN |  |
| 3 | `txn_id` | id | C | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` | required for TXN and REFUND lines |
| 4 | `fee_code` | str | C | one of ACQ_FEE, SCHEME_FEE | required for FEE lines |
| 5 | `amount` | amount | M | `^\d+\.\d{2}$` |  |
| 6 | `dc_indicator` | enum | M | one of C, D |  |
| 7 | `currency` | ccy | M | one of EUR, GBP |  |

- not period-checked: no date fields; a line follows its batch, and lines of an excluded batch are not used
- used by checks: C11-BATCH-ARITH, C11-TXN-LINE

**IN-14 - Discrepancy and corrective-action log** (canonical file name pattern, informational only: `discrepancy_log_{period}.csv`)

| # | Column | Type | Req. | Value rule (from UC-042) | Condition |
|---|---|---|---|---|---|
| 0 | `discrepancy_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 1 | `logged_ts` | ts | M | ISO 8601 with UTC offset |  |
| 2 | `recon_ref` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 3 | `account_id` | id | M | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |
| 4 | `currency` | ccy | M | one of EUR, GBP |  |
| 5 | `amount` | signed | M | `^-?\d+\.\d{2}$` |  |
| 6 | `description` | str | M | - |  |
| 7 | `cause_category` | enum | O | - |  |
| 8 | `cause_evidence_ref` | str | O | - |  |
| 9 | `funding_reference` | str | O | - |  |
| 10 | `status` | enum | M | one of OPEN, RESOLVED |  |
| 11 | `resolved_ts` | ts | O | ISO 8601 with UTC offset |  |
| 12 | `approver_id` | id | O | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |  |

- period rule `{"event_ref": {"field": "recon_ref", "sources": {"IN-05": "recon_run_id", "IN-06": "ext_recon_id"}, "date_field": "recon_date"}, "not_before_event": ["logged_ts"], "subsequent_after_end": ["logged_ts"]}`
- not period-checked: resolved_ts is not used; the log's period follows the reconciliation it refers to
- used by checks: DISC-LOG
- relationships (recorded, not enforced in Phase 1): `recon_ref` -> IN-05/IN-06 (period_event_reference); `recon_ref` -> IN-05 (documented_reference); `recon_ref` -> IN-06 (documented_reference)
- **unresolved:** cause_category: declared enum with no allowed values in uc042lib.schema.ENUMS

### A.3 PDF contracts (IN-15 to IN-19)

| ID | Labels (each must appear as a `Label: value` line) | Identification | Notes |
|---|---|---|---|
| IN-15 | Letter reference, Institution, Account name, Account number, Currency, Letter date (Letter issue date) | labels shared with IN-16; slot = account SGA-GBP-01 via IN-02 letter reference | unresolved: PDF label value types are not defined by UC-042 (labels only); value_type left undefined |
| IN-16 | Letter reference, Institution, Account name, Account number, Currency, Letter date (Letter issue date) | labels shared with IN-15; slot = account SGA-EUR-01 via IN-02 letter reference | unresolved: PDF label value types are not defined by UC-042 (labels only); value_type left undefined |
| IN-17 | Document version, Effective date (Policy effective date), Safeguarding method, Reconciliation method, Reconciliation point, Frequency, Internal reconciliation basis | all labels + recognised policy version | versions: v1.1 effective 2025-10-01, ILLUSTRATIVE_SYNTHETIC, markings ['ILLUSTRATIVE SYNTHETIC DOCUMENT', 'NOT AN OFFICIAL RECORD', 'Illustrative predecessor of policy v1.2']; v1.2 effective 2026-05-07, SYNTHETIC_PROJECT_DOCUMENT, markings ['SYNTHETIC DOCUMENT - UC-042 POC'] / unresolved: PDF label value types are not defined by UC-042 (labels only); value_type left undefined; Which recognised version governs a period is a period-level selection (uc042lib.policy.select / APPROVED_SELECTIONS), not a file classification; not applied here |
| IN-18 | Accountable person, Role, Allocated from (Responsibility allocated from) | all labels present | unresolved: PDF label value types are not defined by UC-042 (labels only); value_type left undefined |
| IN-19 | Return, Period (Return period), Due date (Return due date), Submitted at (Return submission timestamp), Submission reference | all labels present | the receipt is for the PREVIOUS month's return (uc042app.ingest.analysis.analyse_pdf) / unresolved: PDF label value types are not defined by UC-042 (labels only); value_type left undefined |


## B. Baseline classification results

The complete machine-readable list (445 rows, with SHA-256, UC-042 oracle basis, full reasons and pipeline statuses) is evidence/baseline_results.csv. B.1 lists each distinct file once; B.2 lists every tested file.

### B.1 Distinct files (one row per distinct content; the same bytes recur across datasets)

| # | Original filename(s) | Type | Expected | Actual | Match | Occurrences | Reason (abridged) | Warnings |
|---|---|---|---|---|---|---|---|---|
| 1 | recon_calendar_2026-01.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 2 | recon_calendar_2026-02.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 3 | recon_calendar_2026-03.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 4 | recon_calendar_2026-04.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 5 | recon_calendar_2026-05.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 6 | recon_calendar_2026-06.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 7 | recon_calendar_2026-07.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 8 | recon_calendar_2026-08.csv | CSV | IN-01 | IN-01 | MATCH | 2 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 9 | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | MATCH | 9 | Header row equals the canonical IN-01 header exactly (5 columns, same order and case) |  |
| 10 | account_inventory.csv | CSV | IN-02 | IN-02 | MATCH | 25 | Header row equals the canonical IN-02 header exactly (15 columns, same order and case) |  |
| 11 | client_balance_snapshots_2026-01.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 12 | client_balance_snapshots_2026-02.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 13 | client_balance_snapshots_2026-03.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 14 | client_balance_snapshots_2026-04.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 15 | client_balance_snapshots_2026-05.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 16 | client_balance_snapshots_2026-06.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 17 | client_balance_snapshots_2026-07.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 18 | client_balance_snapshots_2026-08.csv | CSV | IN-03 | IN-03 | MATCH | 2 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 19 | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | MATCH | 7 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 20 | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | MATCH | 1 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 21 | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | MATCH | 1 | Header row equals the canonical IN-03 header exactly (7 columns, same order and case) |  |
| 22 | unallocated_register_2026-01.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 23 | unallocated_register_2026-02.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 24 | unallocated_register_2026-03.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 25 | unallocated_register_2026-04.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 26 | unallocated_register_2026-05.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 27 | unallocated_register_2026-06.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 28 | unallocated_register_2026-07.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 29 | unallocated_register_2026-08.csv | CSV | IN-04 | IN-04 | MATCH | 2 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 30 | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | MATCH | 9 | Header row equals the canonical IN-04 header exactly (11 columns, same order and case) |  |
| 31 | internal_recon_records_2026-01.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 32 | internal_recon_records_2026-02.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 33 | internal_recon_records_2026-03.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 34 | internal_recon_records_2026-04.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 35 | internal_recon_records_2026-05.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 36 | internal_recon_records_2026-06.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 37 | internal_recon_records_2026-07.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 38 | internal_recon_records_2026-08.csv | CSV | IN-05 | IN-05 | MATCH | 2 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 39 | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | MATCH | 8 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 40 | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | MATCH | 1 | Header row equals the canonical IN-05 header exactly (19 columns, same order and case) |  |
| 41 | external_recon_records_2026-01.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 42 | external_recon_records_2026-02.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 43 | external_recon_records_2026-03.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 44 | external_recon_records_2026-04.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 45 | external_recon_records_2026-05.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 46 | external_recon_records_2026-06.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 47 | external_recon_records_2026-07.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 48 | external_recon_records_2026-08.csv | CSV | IN-06 | IN-06 | MATCH | 2 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 49 | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | MATCH | 6 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 50 | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | MATCH | 1 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 51 | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | MATCH | 1 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 52 | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | MATCH | 1 | Header row equals the canonical IN-06 header exactly (11 columns, same order and case) |  |
| 53 | bank_balance_confirmations_2026-01.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 54 | bank_balance_confirmations_2026-02.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 55 | bank_balance_confirmations_2026-03.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 56 | bank_balance_confirmations_2026-04.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 57 | bank_balance_confirmations_2026-05.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 58 | bank_balance_confirmations_2026-06.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 59 | bank_balance_confirmations_2026-07.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 60 | bank_balance_confirmations_2026-08.csv | CSV | IN-07 | IN-07 | MATCH | 2 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 61 | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | MATCH | 1 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 62 | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | MATCH | 1 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 63 | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | MATCH | 1 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 64 | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | MATCH | 5 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 65 | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | MATCH | 1 | Header row equals the canonical IN-07 header exactly (7 columns, same order and case) |  |
| 66 | bank_statements_eod_2026-01.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 67 | bank_statements_eod_2026-02.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 68 | bank_statements_eod_2026-03.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 69 | bank_statements_eod_2026-04.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 70 | bank_statements_eod_2026-05.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 71 | bank_statements_eod_2026-06.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 72 | bank_statements_eod_2026-07.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 73 | bank_statements_eod_2026-08.csv | CSV | IN-08 | IN-08 | MATCH | 2 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 74 | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | MATCH | 1 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 75 | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | MATCH | 1 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 76 | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | MATCH | 1 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 77 | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | MATCH | 5 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 78 | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | MATCH | 1 | Header row equals the canonical IN-08 header exactly (11 columns, same order and case) |  |
| 79 | bank_statement_entries_2026-01.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 80 | bank_statement_entries_2026-02.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 81 | bank_statement_entries_2026-03.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 82 | bank_statement_entries_2026-04.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 83 | bank_statement_entries_2026-05.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 84 | bank_statement_entries_2026-06.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 85 | bank_statement_entries_2026-07.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 86 | bank_statement_entries_2026-08.csv | CSV | IN-09 | IN-09 | MATCH | 2 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 87 | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | MATCH | 1 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 88 | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | MATCH | 1 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 89 | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | MATCH | 1 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 90 | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | MATCH | 5 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 91 | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | MATCH | 1 | Header row equals the canonical IN-09 header exactly (13 columns, same order and case) |  |
| 92 | sga_cashbook_entries_2026-01.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 93 | sga_cashbook_entries_2026-02.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 94 | sga_cashbook_entries_2026-03.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 95 | sga_cashbook_entries_2026-04.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 96 | sga_cashbook_entries_2026-05.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 97 | sga_cashbook_entries_2026-06.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 98 | sga_cashbook_entries_2026-07.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 99 | sga_cashbook_entries_2026-08.csv | CSV | IN-10 | IN-10 | MATCH | 2 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 100 | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | MATCH | 9 | Header row equals the canonical IN-10 header exactly (8 columns, same order and case) |  |
| 101 | transactions_2026-01.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 102 | transactions_2026-02.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 103 | transactions_2026-03.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 104 | transactions_2026-04.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 105 | transactions_2026-05.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 106 | transactions_2026-06.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 107 | transactions_2026-07.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 108 | transactions_2026-08.csv | CSV | IN-11 | IN-11 | MATCH | 2 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 109 | transactions_2026-09.csv | CSV | IN-11 | IN-11 | MATCH | 8 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 110 | transactions_2026-09.csv | CSV | IN-11 | IN-11 | MATCH | 1 | Header row equals the canonical IN-11 header exactly (13 columns, same order and case) |  |
| 111 | settlement_batches_2026-01.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 112 | settlement_batches_2026-02.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 113 | settlement_batches_2026-03.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 114 | settlement_batches_2026-04.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 115 | settlement_batches_2026-05.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 116 | settlement_batches_2026-06.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 117 | settlement_batches_2026-07.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 118 | settlement_batches_2026-08.csv | CSV | IN-12 | IN-12 | MATCH | 2 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 119 | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | MATCH | 9 | Header row equals the canonical IN-12 header exactly (12 columns, same order and case) |  |
| 120 | settlement_lines_2026-01.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 121 | settlement_lines_2026-02.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 122 | settlement_lines_2026-03.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 123 | settlement_lines_2026-04.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 124 | settlement_lines_2026-05.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 125 | settlement_lines_2026-06.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 126 | settlement_lines_2026-07.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 127 | settlement_lines_2026-08.csv | CSV | IN-13 | IN-13 | MATCH | 2 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 128 | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | MATCH | 8 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 129 | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | MATCH | 1 | Header row equals the canonical IN-13 header exactly (8 columns, same order and case) |  |
| 130 | discrepancy_log_2026-01.csv, discrepancy_log_2026-02.csv, discrepancy_log_2026-03.csv, discrepancy_log_2026-04.csv, discrepancy_log_2026-05.csv, discrepancy_log_2026-06.csv, discrepancy_log_2026-07.csv, discrepancy_log_2026-08.csv, discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | MATCH | 24 | Header row equals the canonical IN-14 header exactly (13 columns, same order and case) | no data rows (allowed for this category) |
| 131 | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | MATCH | 1 | Header row equals the canonical IN-14 header exactly (13 columns, same order and case) |  |
| 132 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | MATCH | 25 | Acknowledgement-letter labels found; letter reference 'ACK-INST01-4471' equals the IN-02 acknowledgement_letter_ref of SGA-GBP-01, so the sl |  |
| 133 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | MATCH | 25 | Acknowledgement-letter labels found; letter reference 'ACK-INST01-8823' equals the IN-02 acknowledgement_letter_ref of SGA-EUR-01, so the sl |  |
| 134 | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | MATCH | 10 | policy v1.1: All 7 IN-17 key-detail labels found |  |
| 135 | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | MATCH | 17 | policy v1.2: All 7 IN-17 key-detail labels found |  |
| 136 | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | MATCH | 9 | All 3 IN-18 key-detail labels found, as 'Label: value' lines |  |
| 137 | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | MATCH | 9 | All 5 IN-19 key-detail labels found, as 'Label: value' lines |  |

### B.2 Every tested file

| # | Dataset | Original filename | Type | Expected (manifest) | UC-042 oracle | Actual | Match | Method | Warnings |
|---|---|---|---|---|---|---|---|---|---|
| 1 | uc042_dataset/scn_S02_missing_eur_statement | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 2 | uc042_dataset/scn_S02_missing_eur_statement | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 3 | uc042_dataset/scn_S02_missing_eur_statement | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 4 | uc042_dataset/scn_S02_missing_eur_statement | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 5 | uc042_dataset/scn_S02_missing_eur_statement | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 6 | uc042_dataset/scn_S02_missing_eur_statement | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 7 | uc042_dataset/scn_S02_missing_eur_statement | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 8 | uc042_dataset/scn_S02_missing_eur_statement | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 9 | uc042_dataset/scn_S02_missing_eur_statement | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 10 | uc042_dataset/scn_S02_missing_eur_statement | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 11 | uc042_dataset/scn_S02_missing_eur_statement | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 12 | uc042_dataset/scn_S02_missing_eur_statement | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 13 | uc042_dataset/scn_S02_missing_eur_statement | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 14 | uc042_dataset/scn_S02_missing_eur_statement | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 15 | uc042_dataset/scn_S02_missing_eur_statement | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 16 | uc042_dataset/scn_S02_missing_eur_statement | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 17 | uc042_dataset/scn_S02_missing_eur_statement | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 18 | uc042_dataset/scn_S02_missing_eur_statement | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 19 | uc042_dataset/scn_S02_missing_eur_statement | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 20 | uc042_dataset/scn_S05_unexplained_gbp_difference | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 21 | uc042_dataset/scn_S05_unexplained_gbp_difference | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 22 | uc042_dataset/scn_S05_unexplained_gbp_difference | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 23 | uc042_dataset/scn_S05_unexplained_gbp_difference | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 24 | uc042_dataset/scn_S05_unexplained_gbp_difference | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 25 | uc042_dataset/scn_S05_unexplained_gbp_difference | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 26 | uc042_dataset/scn_S05_unexplained_gbp_difference | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 27 | uc042_dataset/scn_S05_unexplained_gbp_difference | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 28 | uc042_dataset/scn_S05_unexplained_gbp_difference | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 29 | uc042_dataset/scn_S05_unexplained_gbp_difference | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 30 | uc042_dataset/scn_S05_unexplained_gbp_difference | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 31 | uc042_dataset/scn_S05_unexplained_gbp_difference | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 32 | uc042_dataset/scn_S05_unexplained_gbp_difference | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 33 | uc042_dataset/scn_S05_unexplained_gbp_difference | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 34 | uc042_dataset/scn_S05_unexplained_gbp_difference | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 35 | uc042_dataset/scn_S05_unexplained_gbp_difference | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 36 | uc042_dataset/scn_S05_unexplained_gbp_difference | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 37 | uc042_dataset/scn_S05_unexplained_gbp_difference | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 38 | uc042_dataset/scn_S05_unexplained_gbp_difference | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 39 | uc042_dataset/scn_SC2_settlement_timing | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 40 | uc042_dataset/scn_SC2_settlement_timing | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 41 | uc042_dataset/scn_SC2_settlement_timing | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 42 | uc042_dataset/scn_SC2_settlement_timing | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 43 | uc042_dataset/scn_SC2_settlement_timing | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 44 | uc042_dataset/scn_SC2_settlement_timing | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header |  |
| 45 | uc042_dataset/scn_SC2_settlement_timing | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 46 | uc042_dataset/scn_SC2_settlement_timing | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 47 | uc042_dataset/scn_SC2_settlement_timing | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 48 | uc042_dataset/scn_SC2_settlement_timing | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 49 | uc042_dataset/scn_SC2_settlement_timing | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 50 | uc042_dataset/scn_SC2_settlement_timing | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 51 | uc042_dataset/scn_SC2_settlement_timing | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 52 | uc042_dataset/scn_SC2_settlement_timing | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 53 | uc042_dataset/scn_SC2_settlement_timing | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 54 | uc042_dataset/scn_SC2_settlement_timing | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 55 | uc042_dataset/scn_SC2_settlement_timing | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 56 | uc042_dataset/scn_SC2_settlement_timing | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 57 | uc042_dataset/scn_SC2_settlement_timing | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 58 | uc042_dataset/scn_SC3B_fee_not_itemised | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 59 | uc042_dataset/scn_SC3B_fee_not_itemised | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 60 | uc042_dataset/scn_SC3B_fee_not_itemised | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 61 | uc042_dataset/scn_SC3B_fee_not_itemised | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 62 | uc042_dataset/scn_SC3B_fee_not_itemised | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 63 | uc042_dataset/scn_SC3B_fee_not_itemised | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 64 | uc042_dataset/scn_SC3B_fee_not_itemised | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 65 | uc042_dataset/scn_SC3B_fee_not_itemised | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 66 | uc042_dataset/scn_SC3B_fee_not_itemised | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 67 | uc042_dataset/scn_SC3B_fee_not_itemised | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 68 | uc042_dataset/scn_SC3B_fee_not_itemised | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 69 | uc042_dataset/scn_SC3B_fee_not_itemised | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 70 | uc042_dataset/scn_SC3B_fee_not_itemised | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 71 | uc042_dataset/scn_SC3B_fee_not_itemised | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 72 | uc042_dataset/scn_SC3B_fee_not_itemised | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 73 | uc042_dataset/scn_SC3B_fee_not_itemised | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 74 | uc042_dataset/scn_SC3B_fee_not_itemised | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 75 | uc042_dataset/scn_SC3B_fee_not_itemised | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 76 | uc042_dataset/scn_SC3B_fee_not_itemised | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 77 | uc042_dataset/scn_SC3C_short_settlement | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 78 | uc042_dataset/scn_SC3C_short_settlement | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 79 | uc042_dataset/scn_SC3C_short_settlement | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 80 | uc042_dataset/scn_SC3C_short_settlement | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 81 | uc042_dataset/scn_SC3C_short_settlement | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 82 | uc042_dataset/scn_SC3C_short_settlement | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 83 | uc042_dataset/scn_SC3C_short_settlement | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 84 | uc042_dataset/scn_SC3C_short_settlement | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 85 | uc042_dataset/scn_SC3C_short_settlement | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 86 | uc042_dataset/scn_SC3C_short_settlement | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 87 | uc042_dataset/scn_SC3C_short_settlement | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 88 | uc042_dataset/scn_SC3C_short_settlement | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 89 | uc042_dataset/scn_SC3C_short_settlement | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 90 | uc042_dataset/scn_SC3C_short_settlement | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 91 | uc042_dataset/scn_SC3C_short_settlement | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 92 | uc042_dataset/scn_SC3C_short_settlement | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 93 | uc042_dataset/scn_SC3C_short_settlement | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 94 | uc042_dataset/scn_SC3C_short_settlement | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 95 | uc042_dataset/scn_SC3C_short_settlement | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 96 | uc042_dataset/scn_SC5A_missing_transaction | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 97 | uc042_dataset/scn_SC5A_missing_transaction | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 98 | uc042_dataset/scn_SC5A_missing_transaction | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 99 | uc042_dataset/scn_SC5A_missing_transaction | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 100 | uc042_dataset/scn_SC5A_missing_transaction | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 101 | uc042_dataset/scn_SC5A_missing_transaction | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 102 | uc042_dataset/scn_SC5A_missing_transaction | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 103 | uc042_dataset/scn_SC5A_missing_transaction | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 104 | uc042_dataset/scn_SC5A_missing_transaction | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 105 | uc042_dataset/scn_SC5A_missing_transaction | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 106 | uc042_dataset/scn_SC5A_missing_transaction | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 107 | uc042_dataset/scn_SC5A_missing_transaction | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 108 | uc042_dataset/scn_SC5A_missing_transaction | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 109 | uc042_dataset/scn_SC5A_missing_transaction | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 110 | uc042_dataset/scn_SC5A_missing_transaction | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 111 | uc042_dataset/scn_SC5A_missing_transaction | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 112 | uc042_dataset/scn_SC5A_missing_transaction | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 113 | uc042_dataset/scn_SC5A_missing_transaction | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 114 | uc042_dataset/scn_SC5A_missing_transaction | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 115 | uc042_dataset/scn_SC5C_refund_double_posted | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 116 | uc042_dataset/scn_SC5C_refund_double_posted | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 117 | uc042_dataset/scn_SC5C_refund_double_posted | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 118 | uc042_dataset/scn_SC5C_refund_double_posted | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 119 | uc042_dataset/scn_SC5C_refund_double_posted | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 120 | uc042_dataset/scn_SC5C_refund_double_posted | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 121 | uc042_dataset/scn_SC5C_refund_double_posted | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 122 | uc042_dataset/scn_SC5C_refund_double_posted | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 123 | uc042_dataset/scn_SC5C_refund_double_posted | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 124 | uc042_dataset/scn_SC5C_refund_double_posted | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 125 | uc042_dataset/scn_SC5C_refund_double_posted | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 126 | uc042_dataset/scn_SC5C_refund_double_posted | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 127 | uc042_dataset/scn_SC5C_refund_double_posted | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 128 | uc042_dataset/scn_SC5C_refund_double_posted | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 129 | uc042_dataset/scn_SC5C_refund_double_posted | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 130 | uc042_dataset/scn_SC5C_refund_double_posted | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 131 | uc042_dataset/scn_SC5C_refund_double_posted | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 132 | uc042_dataset/scn_SC5C_refund_double_posted | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 133 | uc042_dataset/scn_SC5C_refund_double_posted | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 134 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 135 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 136 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 137 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 138 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 139 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 140 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 141 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 142 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 143 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 144 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 145 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 146 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 147 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 148 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 149 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 150 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 151 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 152 | uc042_dataset/scn_SC5D_closing_snapshot_mismatch | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 153 | uc042_dataset/set_01_clean_baseline | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 154 | uc042_dataset/set_01_clean_baseline | bank_balance_confirmations_2026-09.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 155 | uc042_dataset/set_01_clean_baseline | bank_statement_entries_2026-09.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 156 | uc042_dataset/set_01_clean_baseline | bank_statements_eod_2026-09.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 157 | uc042_dataset/set_01_clean_baseline | client_balance_snapshots_2026-09.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 158 | uc042_dataset/set_01_clean_baseline | discrepancy_log_2026-09.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 159 | uc042_dataset/set_01_clean_baseline | external_recon_records_2026-09.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 160 | uc042_dataset/set_01_clean_baseline | internal_recon_records_2026-09.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 161 | uc042_dataset/set_01_clean_baseline | recon_calendar_2026-09.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 162 | uc042_dataset/set_01_clean_baseline | settlement_batches_2026-09.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 163 | uc042_dataset/set_01_clean_baseline | settlement_lines_2026-09.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 164 | uc042_dataset/set_01_clean_baseline | sga_cashbook_entries_2026-09.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 165 | uc042_dataset/set_01_clean_baseline | transactions_2026-09.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 166 | uc042_dataset/set_01_clean_baseline | unallocated_register_2026-09.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 167 | uc042_dataset/set_01_clean_baseline | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 168 | uc042_dataset/set_01_clean_baseline | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 169 | uc042_dataset/set_01_clean_baseline | governance_register_2026-09.pdf | PDF | IN-18 | IN-18 | IN-18 | MATCH | pdf_text_pattern |  |
| 170 | uc042_dataset/set_01_clean_baseline | rep027_submission_receipt_2026-08.pdf | PDF | IN-19 | IN-19 | IN-19 | MATCH | pdf_text_pattern |  |
| 171 | uc042_dataset/set_01_clean_baseline | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 172 | demo_history/datasets/2026-01 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 173 | demo_history/datasets/2026-01 | bank_balance_confirmations_2026-01.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 174 | demo_history/datasets/2026-01 | bank_statement_entries_2026-01.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 175 | demo_history/datasets/2026-01 | bank_statements_eod_2026-01.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 176 | demo_history/datasets/2026-01 | client_balance_snapshots_2026-01.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 177 | demo_history/datasets/2026-01 | discrepancy_log_2026-01.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 178 | demo_history/datasets/2026-01 | external_recon_records_2026-01.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 179 | demo_history/datasets/2026-01 | internal_recon_records_2026-01.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 180 | demo_history/datasets/2026-01 | recon_calendar_2026-01.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 181 | demo_history/datasets/2026-01 | settlement_batches_2026-01.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 182 | demo_history/datasets/2026-01 | settlement_lines_2026-01.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 183 | demo_history/datasets/2026-01 | sga_cashbook_entries_2026-01.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 184 | demo_history/datasets/2026-01 | transactions_2026-01.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 185 | demo_history/datasets/2026-01 | unallocated_register_2026-01.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 186 | demo_history/datasets/2026-01 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 187 | demo_history/datasets/2026-01 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 188 | demo_history/datasets/2026-01 | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 189 | demo_history/datasets/2026-02 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 190 | demo_history/datasets/2026-02 | bank_balance_confirmations_2026-02.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 191 | demo_history/datasets/2026-02 | bank_statement_entries_2026-02.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 192 | demo_history/datasets/2026-02 | bank_statements_eod_2026-02.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 193 | demo_history/datasets/2026-02 | client_balance_snapshots_2026-02.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 194 | demo_history/datasets/2026-02 | discrepancy_log_2026-02.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 195 | demo_history/datasets/2026-02 | external_recon_records_2026-02.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 196 | demo_history/datasets/2026-02 | internal_recon_records_2026-02.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 197 | demo_history/datasets/2026-02 | recon_calendar_2026-02.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 198 | demo_history/datasets/2026-02 | settlement_batches_2026-02.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 199 | demo_history/datasets/2026-02 | settlement_lines_2026-02.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 200 | demo_history/datasets/2026-02 | sga_cashbook_entries_2026-02.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 201 | demo_history/datasets/2026-02 | transactions_2026-02.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 202 | demo_history/datasets/2026-02 | unallocated_register_2026-02.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 203 | demo_history/datasets/2026-02 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 204 | demo_history/datasets/2026-02 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 205 | demo_history/datasets/2026-02 | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 206 | demo_history/datasets/2026-03 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 207 | demo_history/datasets/2026-03 | bank_balance_confirmations_2026-03.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 208 | demo_history/datasets/2026-03 | bank_statement_entries_2026-03.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 209 | demo_history/datasets/2026-03 | bank_statements_eod_2026-03.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 210 | demo_history/datasets/2026-03 | client_balance_snapshots_2026-03.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 211 | demo_history/datasets/2026-03 | discrepancy_log_2026-03.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 212 | demo_history/datasets/2026-03 | external_recon_records_2026-03.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 213 | demo_history/datasets/2026-03 | internal_recon_records_2026-03.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 214 | demo_history/datasets/2026-03 | recon_calendar_2026-03.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 215 | demo_history/datasets/2026-03 | settlement_batches_2026-03.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 216 | demo_history/datasets/2026-03 | settlement_lines_2026-03.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 217 | demo_history/datasets/2026-03 | sga_cashbook_entries_2026-03.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 218 | demo_history/datasets/2026-03 | transactions_2026-03.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 219 | demo_history/datasets/2026-03 | unallocated_register_2026-03.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 220 | demo_history/datasets/2026-03 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 221 | demo_history/datasets/2026-03 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 222 | demo_history/datasets/2026-03 | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 223 | demo_history/datasets/2026-04 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 224 | demo_history/datasets/2026-04 | bank_balance_confirmations_2026-04.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 225 | demo_history/datasets/2026-04 | bank_statement_entries_2026-04.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 226 | demo_history/datasets/2026-04 | bank_statements_eod_2026-04.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 227 | demo_history/datasets/2026-04 | client_balance_snapshots_2026-04.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 228 | demo_history/datasets/2026-04 | discrepancy_log_2026-04.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 229 | demo_history/datasets/2026-04 | external_recon_records_2026-04.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 230 | demo_history/datasets/2026-04 | internal_recon_records_2026-04.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 231 | demo_history/datasets/2026-04 | recon_calendar_2026-04.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 232 | demo_history/datasets/2026-04 | settlement_batches_2026-04.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 233 | demo_history/datasets/2026-04 | settlement_lines_2026-04.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 234 | demo_history/datasets/2026-04 | sga_cashbook_entries_2026-04.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 235 | demo_history/datasets/2026-04 | transactions_2026-04.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 236 | demo_history/datasets/2026-04 | unallocated_register_2026-04.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 237 | demo_history/datasets/2026-04 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 238 | demo_history/datasets/2026-04 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 239 | demo_history/datasets/2026-04 | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 240 | demo_history/datasets/2026-05 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 241 | demo_history/datasets/2026-05 | bank_balance_confirmations_2026-05.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 242 | demo_history/datasets/2026-05 | bank_statement_entries_2026-05.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 243 | demo_history/datasets/2026-05 | bank_statements_eod_2026-05.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 244 | demo_history/datasets/2026-05 | client_balance_snapshots_2026-05.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 245 | demo_history/datasets/2026-05 | discrepancy_log_2026-05.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 246 | demo_history/datasets/2026-05 | external_recon_records_2026-05.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 247 | demo_history/datasets/2026-05 | internal_recon_records_2026-05.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 248 | demo_history/datasets/2026-05 | recon_calendar_2026-05.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 249 | demo_history/datasets/2026-05 | settlement_batches_2026-05.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 250 | demo_history/datasets/2026-05 | settlement_lines_2026-05.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 251 | demo_history/datasets/2026-05 | sga_cashbook_entries_2026-05.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 252 | demo_history/datasets/2026-05 | transactions_2026-05.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 253 | demo_history/datasets/2026-05 | unallocated_register_2026-05.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 254 | demo_history/datasets/2026-05 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 255 | demo_history/datasets/2026-05 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 256 | demo_history/datasets/2026-05 | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 257 | demo_history/datasets/2026-05 | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 258 | demo_history/datasets/2026-06 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 259 | demo_history/datasets/2026-06 | bank_balance_confirmations_2026-06.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 260 | demo_history/datasets/2026-06 | bank_statement_entries_2026-06.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 261 | demo_history/datasets/2026-06 | bank_statements_eod_2026-06.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 262 | demo_history/datasets/2026-06 | client_balance_snapshots_2026-06.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 263 | demo_history/datasets/2026-06 | discrepancy_log_2026-06.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 264 | demo_history/datasets/2026-06 | external_recon_records_2026-06.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 265 | demo_history/datasets/2026-06 | internal_recon_records_2026-06.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 266 | demo_history/datasets/2026-06 | recon_calendar_2026-06.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 267 | demo_history/datasets/2026-06 | settlement_batches_2026-06.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 268 | demo_history/datasets/2026-06 | settlement_lines_2026-06.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 269 | demo_history/datasets/2026-06 | sga_cashbook_entries_2026-06.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 270 | demo_history/datasets/2026-06 | transactions_2026-06.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 271 | demo_history/datasets/2026-06 | unallocated_register_2026-06.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 272 | demo_history/datasets/2026-06 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 273 | demo_history/datasets/2026-06 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 274 | demo_history/datasets/2026-06 | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 275 | demo_history/datasets/2026-07 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 276 | demo_history/datasets/2026-07 | bank_balance_confirmations_2026-07.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 277 | demo_history/datasets/2026-07 | bank_statement_entries_2026-07.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 278 | demo_history/datasets/2026-07 | bank_statements_eod_2026-07.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 279 | demo_history/datasets/2026-07 | client_balance_snapshots_2026-07.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 280 | demo_history/datasets/2026-07 | discrepancy_log_2026-07.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 281 | demo_history/datasets/2026-07 | external_recon_records_2026-07.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 282 | demo_history/datasets/2026-07 | internal_recon_records_2026-07.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 283 | demo_history/datasets/2026-07 | recon_calendar_2026-07.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 284 | demo_history/datasets/2026-07 | settlement_batches_2026-07.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 285 | demo_history/datasets/2026-07 | settlement_lines_2026-07.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 286 | demo_history/datasets/2026-07 | sga_cashbook_entries_2026-07.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 287 | demo_history/datasets/2026-07 | transactions_2026-07.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 288 | demo_history/datasets/2026-07 | unallocated_register_2026-07.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 289 | demo_history/datasets/2026-07 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 290 | demo_history/datasets/2026-07 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 291 | demo_history/datasets/2026-07 | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 292 | demo_history/datasets/2026-08 | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 293 | demo_history/datasets/2026-08 | bank_balance_confirmations_2026-08.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 294 | demo_history/datasets/2026-08 | bank_statement_entries_2026-08.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 295 | demo_history/datasets/2026-08 | bank_statements_eod_2026-08.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 296 | demo_history/datasets/2026-08 | client_balance_snapshots_2026-08.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 297 | demo_history/datasets/2026-08 | discrepancy_log_2026-08.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 298 | demo_history/datasets/2026-08 | external_recon_records_2026-08.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 299 | demo_history/datasets/2026-08 | internal_recon_records_2026-08.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 300 | demo_history/datasets/2026-08 | recon_calendar_2026-08.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 301 | demo_history/datasets/2026-08 | settlement_batches_2026-08.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 302 | demo_history/datasets/2026-08 | settlement_lines_2026-08.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 303 | demo_history/datasets/2026-08 | sga_cashbook_entries_2026-08.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 304 | demo_history/datasets/2026-08 | transactions_2026-08.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 305 | demo_history/datasets/2026-08 | unallocated_register_2026-08.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 306 | demo_history/datasets/2026-08 | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 307 | demo_history/datasets/2026-08 | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 308 | demo_history/datasets/2026-08 | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 309 | JAN_AUG_zip/2026-01/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 310 | JAN_AUG_zip/2026-01/source_documents | bank_balance_confirmations_2026-01.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 311 | JAN_AUG_zip/2026-01/source_documents | bank_statement_entries_2026-01.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 312 | JAN_AUG_zip/2026-01/source_documents | bank_statements_eod_2026-01.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 313 | JAN_AUG_zip/2026-01/source_documents | client_balance_snapshots_2026-01.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 314 | JAN_AUG_zip/2026-01/source_documents | discrepancy_log_2026-01.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 315 | JAN_AUG_zip/2026-01/source_documents | external_recon_records_2026-01.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 316 | JAN_AUG_zip/2026-01/source_documents | internal_recon_records_2026-01.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 317 | JAN_AUG_zip/2026-01/source_documents | recon_calendar_2026-01.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 318 | JAN_AUG_zip/2026-01/source_documents | settlement_batches_2026-01.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 319 | JAN_AUG_zip/2026-01/source_documents | settlement_lines_2026-01.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 320 | JAN_AUG_zip/2026-01/source_documents | sga_cashbook_entries_2026-01.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 321 | JAN_AUG_zip/2026-01/source_documents | transactions_2026-01.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 322 | JAN_AUG_zip/2026-01/source_documents | unallocated_register_2026-01.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 323 | JAN_AUG_zip/2026-01/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 324 | JAN_AUG_zip/2026-01/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 325 | JAN_AUG_zip/2026-01/source_documents | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 326 | JAN_AUG_zip/2026-02/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 327 | JAN_AUG_zip/2026-02/source_documents | bank_balance_confirmations_2026-02.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 328 | JAN_AUG_zip/2026-02/source_documents | bank_statement_entries_2026-02.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 329 | JAN_AUG_zip/2026-02/source_documents | bank_statements_eod_2026-02.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 330 | JAN_AUG_zip/2026-02/source_documents | client_balance_snapshots_2026-02.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 331 | JAN_AUG_zip/2026-02/source_documents | discrepancy_log_2026-02.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 332 | JAN_AUG_zip/2026-02/source_documents | external_recon_records_2026-02.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 333 | JAN_AUG_zip/2026-02/source_documents | internal_recon_records_2026-02.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 334 | JAN_AUG_zip/2026-02/source_documents | recon_calendar_2026-02.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 335 | JAN_AUG_zip/2026-02/source_documents | settlement_batches_2026-02.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 336 | JAN_AUG_zip/2026-02/source_documents | settlement_lines_2026-02.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 337 | JAN_AUG_zip/2026-02/source_documents | sga_cashbook_entries_2026-02.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 338 | JAN_AUG_zip/2026-02/source_documents | transactions_2026-02.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 339 | JAN_AUG_zip/2026-02/source_documents | unallocated_register_2026-02.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 340 | JAN_AUG_zip/2026-02/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 341 | JAN_AUG_zip/2026-02/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 342 | JAN_AUG_zip/2026-02/source_documents | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 343 | JAN_AUG_zip/2026-03/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 344 | JAN_AUG_zip/2026-03/source_documents | bank_balance_confirmations_2026-03.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 345 | JAN_AUG_zip/2026-03/source_documents | bank_statement_entries_2026-03.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 346 | JAN_AUG_zip/2026-03/source_documents | bank_statements_eod_2026-03.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 347 | JAN_AUG_zip/2026-03/source_documents | client_balance_snapshots_2026-03.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 348 | JAN_AUG_zip/2026-03/source_documents | discrepancy_log_2026-03.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 349 | JAN_AUG_zip/2026-03/source_documents | external_recon_records_2026-03.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 350 | JAN_AUG_zip/2026-03/source_documents | internal_recon_records_2026-03.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 351 | JAN_AUG_zip/2026-03/source_documents | recon_calendar_2026-03.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 352 | JAN_AUG_zip/2026-03/source_documents | settlement_batches_2026-03.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 353 | JAN_AUG_zip/2026-03/source_documents | settlement_lines_2026-03.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 354 | JAN_AUG_zip/2026-03/source_documents | sga_cashbook_entries_2026-03.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 355 | JAN_AUG_zip/2026-03/source_documents | transactions_2026-03.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 356 | JAN_AUG_zip/2026-03/source_documents | unallocated_register_2026-03.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 357 | JAN_AUG_zip/2026-03/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 358 | JAN_AUG_zip/2026-03/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 359 | JAN_AUG_zip/2026-03/source_documents | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 360 | JAN_AUG_zip/2026-04/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 361 | JAN_AUG_zip/2026-04/source_documents | bank_balance_confirmations_2026-04.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 362 | JAN_AUG_zip/2026-04/source_documents | bank_statement_entries_2026-04.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 363 | JAN_AUG_zip/2026-04/source_documents | bank_statements_eod_2026-04.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 364 | JAN_AUG_zip/2026-04/source_documents | client_balance_snapshots_2026-04.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 365 | JAN_AUG_zip/2026-04/source_documents | discrepancy_log_2026-04.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 366 | JAN_AUG_zip/2026-04/source_documents | external_recon_records_2026-04.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 367 | JAN_AUG_zip/2026-04/source_documents | internal_recon_records_2026-04.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 368 | JAN_AUG_zip/2026-04/source_documents | recon_calendar_2026-04.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 369 | JAN_AUG_zip/2026-04/source_documents | settlement_batches_2026-04.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 370 | JAN_AUG_zip/2026-04/source_documents | settlement_lines_2026-04.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 371 | JAN_AUG_zip/2026-04/source_documents | sga_cashbook_entries_2026-04.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 372 | JAN_AUG_zip/2026-04/source_documents | transactions_2026-04.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 373 | JAN_AUG_zip/2026-04/source_documents | unallocated_register_2026-04.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 374 | JAN_AUG_zip/2026-04/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 375 | JAN_AUG_zip/2026-04/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 376 | JAN_AUG_zip/2026-04/source_documents | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 377 | JAN_AUG_zip/2026-05/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 378 | JAN_AUG_zip/2026-05/source_documents | bank_balance_confirmations_2026-05.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 379 | JAN_AUG_zip/2026-05/source_documents | bank_statement_entries_2026-05.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 380 | JAN_AUG_zip/2026-05/source_documents | bank_statements_eod_2026-05.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 381 | JAN_AUG_zip/2026-05/source_documents | client_balance_snapshots_2026-05.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 382 | JAN_AUG_zip/2026-05/source_documents | discrepancy_log_2026-05.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 383 | JAN_AUG_zip/2026-05/source_documents | external_recon_records_2026-05.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 384 | JAN_AUG_zip/2026-05/source_documents | internal_recon_records_2026-05.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 385 | JAN_AUG_zip/2026-05/source_documents | recon_calendar_2026-05.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 386 | JAN_AUG_zip/2026-05/source_documents | settlement_batches_2026-05.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 387 | JAN_AUG_zip/2026-05/source_documents | settlement_lines_2026-05.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 388 | JAN_AUG_zip/2026-05/source_documents | sga_cashbook_entries_2026-05.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 389 | JAN_AUG_zip/2026-05/source_documents | transactions_2026-05.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 390 | JAN_AUG_zip/2026-05/source_documents | unallocated_register_2026-05.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 391 | JAN_AUG_zip/2026-05/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 392 | JAN_AUG_zip/2026-05/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 393 | JAN_AUG_zip/2026-05/source_documents | safeguarding_reconciliation_policy_v1.1.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 394 | JAN_AUG_zip/2026-05/source_documents | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 395 | JAN_AUG_zip/2026-06/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 396 | JAN_AUG_zip/2026-06/source_documents | bank_balance_confirmations_2026-06.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 397 | JAN_AUG_zip/2026-06/source_documents | bank_statement_entries_2026-06.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 398 | JAN_AUG_zip/2026-06/source_documents | bank_statements_eod_2026-06.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 399 | JAN_AUG_zip/2026-06/source_documents | client_balance_snapshots_2026-06.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 400 | JAN_AUG_zip/2026-06/source_documents | discrepancy_log_2026-06.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 401 | JAN_AUG_zip/2026-06/source_documents | external_recon_records_2026-06.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 402 | JAN_AUG_zip/2026-06/source_documents | internal_recon_records_2026-06.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 403 | JAN_AUG_zip/2026-06/source_documents | recon_calendar_2026-06.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 404 | JAN_AUG_zip/2026-06/source_documents | settlement_batches_2026-06.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 405 | JAN_AUG_zip/2026-06/source_documents | settlement_lines_2026-06.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 406 | JAN_AUG_zip/2026-06/source_documents | sga_cashbook_entries_2026-06.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 407 | JAN_AUG_zip/2026-06/source_documents | transactions_2026-06.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 408 | JAN_AUG_zip/2026-06/source_documents | unallocated_register_2026-06.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 409 | JAN_AUG_zip/2026-06/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 410 | JAN_AUG_zip/2026-06/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 411 | JAN_AUG_zip/2026-06/source_documents | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 412 | JAN_AUG_zip/2026-07/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 413 | JAN_AUG_zip/2026-07/source_documents | bank_balance_confirmations_2026-07.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 414 | JAN_AUG_zip/2026-07/source_documents | bank_statement_entries_2026-07.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 415 | JAN_AUG_zip/2026-07/source_documents | bank_statements_eod_2026-07.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 416 | JAN_AUG_zip/2026-07/source_documents | client_balance_snapshots_2026-07.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 417 | JAN_AUG_zip/2026-07/source_documents | discrepancy_log_2026-07.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 418 | JAN_AUG_zip/2026-07/source_documents | external_recon_records_2026-07.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 419 | JAN_AUG_zip/2026-07/source_documents | internal_recon_records_2026-07.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 420 | JAN_AUG_zip/2026-07/source_documents | recon_calendar_2026-07.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 421 | JAN_AUG_zip/2026-07/source_documents | settlement_batches_2026-07.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 422 | JAN_AUG_zip/2026-07/source_documents | settlement_lines_2026-07.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 423 | JAN_AUG_zip/2026-07/source_documents | sga_cashbook_entries_2026-07.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 424 | JAN_AUG_zip/2026-07/source_documents | transactions_2026-07.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 425 | JAN_AUG_zip/2026-07/source_documents | unallocated_register_2026-07.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 426 | JAN_AUG_zip/2026-07/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 427 | JAN_AUG_zip/2026-07/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 428 | JAN_AUG_zip/2026-07/source_documents | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |
| 429 | JAN_AUG_zip/2026-08/source_documents | account_inventory.csv | CSV | IN-02 | IN-02 | IN-02 | MATCH | csv_exact_header |  |
| 430 | JAN_AUG_zip/2026-08/source_documents | bank_balance_confirmations_2026-08.csv | CSV | IN-07 | IN-07 | IN-07 | MATCH | csv_exact_header |  |
| 431 | JAN_AUG_zip/2026-08/source_documents | bank_statement_entries_2026-08.csv | CSV | IN-09 | IN-09 | IN-09 | MATCH | csv_exact_header |  |
| 432 | JAN_AUG_zip/2026-08/source_documents | bank_statements_eod_2026-08.csv | CSV | IN-08 | IN-08 | IN-08 | MATCH | csv_exact_header |  |
| 433 | JAN_AUG_zip/2026-08/source_documents | client_balance_snapshots_2026-08.csv | CSV | IN-03 | IN-03 | IN-03 | MATCH | csv_exact_header |  |
| 434 | JAN_AUG_zip/2026-08/source_documents | discrepancy_log_2026-08.csv | CSV | IN-14 | IN-14 | IN-14 | MATCH | csv_exact_header | no data rows (allowed for this category) |
| 435 | JAN_AUG_zip/2026-08/source_documents | external_recon_records_2026-08.csv | CSV | IN-06 | IN-06 | IN-06 | MATCH | csv_exact_header |  |
| 436 | JAN_AUG_zip/2026-08/source_documents | internal_recon_records_2026-08.csv | CSV | IN-05 | IN-05 | IN-05 | MATCH | csv_exact_header |  |
| 437 | JAN_AUG_zip/2026-08/source_documents | recon_calendar_2026-08.csv | CSV | IN-01 | IN-01 | IN-01 | MATCH | csv_exact_header |  |
| 438 | JAN_AUG_zip/2026-08/source_documents | settlement_batches_2026-08.csv | CSV | IN-12 | IN-12 | IN-12 | MATCH | csv_exact_header |  |
| 439 | JAN_AUG_zip/2026-08/source_documents | settlement_lines_2026-08.csv | CSV | IN-13 | IN-13 | IN-13 | MATCH | csv_exact_header |  |
| 440 | JAN_AUG_zip/2026-08/source_documents | sga_cashbook_entries_2026-08.csv | CSV | IN-10 | IN-10 | IN-10 | MATCH | csv_exact_header |  |
| 441 | JAN_AUG_zip/2026-08/source_documents | transactions_2026-08.csv | CSV | IN-11 | IN-11 | IN-11 | MATCH | csv_exact_header |  |
| 442 | JAN_AUG_zip/2026-08/source_documents | unallocated_register_2026-08.csv | CSV | IN-04 | IN-04 | IN-04 | MATCH | csv_exact_header |  |
| 443 | JAN_AUG_zip/2026-08/source_documents | ack_letter_SGA-EUR-01.pdf | PDF | IN-16 | IN-16 | IN-16 | MATCH | pdf_text_pattern |  |
| 444 | JAN_AUG_zip/2026-08/source_documents | ack_letter_SGA-GBP-01.pdf | PDF | IN-15 | IN-15 | IN-15 | MATCH | pdf_text_pattern |  |
| 445 | JAN_AUG_zip/2026-08/source_documents | safeguarding_reconciliation_policy_v1.2.pdf | PDF | IN-17 | IN-17 | IN-17 | MATCH | pdf_text_pattern |  |

## C. Accuracy summary

### C.1 Totals

| Scope | Files | Distinct contents | Correct | Incorrect | Unknown | Ambiguous | Ground-truth conflicts | With warnings |
|---|---|---|---|---|---|---|---|---|
| All | 445 | 137 | 445 | 0 | 0 | 0 | 0 | 24 |
| CSV | 350 | 131 | 350 | 0 | 0 | 0 | 0 | 24 |
| PDF | 95 | 6 | 95 | 0 | 0 | 0 | 0 | 0 |

### C.2 Category coverage

| Category | Files tested | Distinct contents | Datasets | Periods | Correct |
|---|---|---|---|---|---|
| IN-01 | 25 | 9 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-02 | 25 | 1 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-03 | 25 | 11 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-04 | 25 | 9 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-05 | 25 | 10 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-06 | 25 | 12 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-07 | 25 | 13 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-08 | 25 | 13 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-09 | 25 | 13 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-10 | 25 | 9 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-11 | 25 | 10 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-12 | 25 | 9 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-13 | 25 | 10 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-14 | 25 | 2 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-15 | 25 | 1 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-16 | 25 | 1 | 25 | 9 (PER-2026-01..PER-2026-09) | 25/25 |
| IN-17 | 27 | 2 | 25 | 9 (PER-2026-01..PER-2026-09) | 27/27 |
| IN-18 | 9 | 1 | 9 | 1 (PER-2026-09..PER-2026-09) | 9/9 |
| IN-19 | 9 | 1 | 9 | 1 (PER-2026-09..PER-2026-09) | 9/9 |

### C.3 Datasets

| Dataset | Files | Correct |
|---|---|---|
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-01/source_documents` | 17 | 17 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-02/source_documents` | 17 | 17 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-03/source_documents` | 17 | 17 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-04/source_documents` | 17 | 17 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-05/source_documents` | 18 | 18 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-06/source_documents` | 17 | 17 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-07/source_documents` | 17 | 17 |
| `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/2026-08/source_documents` | 17 | 17 |
| `demo_history/datasets/2026-01` | 17 | 17 |
| `demo_history/datasets/2026-02` | 17 | 17 |
| `demo_history/datasets/2026-03` | 17 | 17 |
| `demo_history/datasets/2026-04` | 17 | 17 |
| `demo_history/datasets/2026-05` | 18 | 18 |
| `demo_history/datasets/2026-06` | 17 | 17 |
| `demo_history/datasets/2026-07` | 17 | 17 |
| `demo_history/datasets/2026-08` | 17 | 17 |
| `uc042_dataset/scn_S02_missing_eur_statement` | 19 | 19 |
| `uc042_dataset/scn_S05_unexplained_gbp_difference` | 19 | 19 |
| `uc042_dataset/scn_SC2_settlement_timing` | 19 | 19 |
| `uc042_dataset/scn_SC3B_fee_not_itemised` | 19 | 19 |
| `uc042_dataset/scn_SC3C_short_settlement` | 19 | 19 |
| `uc042_dataset/scn_SC5A_missing_transaction` | 19 | 19 |
| `uc042_dataset/scn_SC5C_refund_double_posted` | 19 | 19 |
| `uc042_dataset/scn_SC5D_closing_snapshot_mismatch` | 19 | 19 |
| `uc042_dataset/set_01_clean_baseline` | 19 | 19 |

- Policy versions identified (IN-17 files): {'1.2': 17, '1.1': 10}
- Letter slots resolved through the IN-02 letter reference: {'IN-16<-SGA-EUR-01': 25, 'IN-15<-SGA-GBP-01': 25}
- Full pipeline under the neutral name `upload.dat` reached the same category for 445 of 445 files. Pipeline status counts: {'csv:completed_with_warnings': 350, 'pdf:not_implemented': 95}; validation: {'csv:valid': 326, 'csv:valid_with_warnings': 24, 'pdf:not_validated': 95}.


## D. Known limitations

These cases are not supported yet. None of them is claimed.

**Header and format tolerance**
1. **Renamed, aliased, reordered, re-cased, spaced, extra, missing or duplicate columns are not accepted.** They are diagnosed: the closest category and what differs. Phase 1 recognises exact canonical headers only. Passing the canonical files says nothing about tolerance of such variants.
2. **Unfamiliar third-party formats are not supported.** Bank exports, ERP extracts and spreadsheets in other layouts will come out `unknown`, which is honest but not useful yet. That is the next phase's mapping work.
3. **XLSX/ODS and other spreadsheets are not handled.** XLSX is a ZIP container. ZIP packages themselves are not classified in Phase 1 (`unsupported = zip`).

**What the corpus can and cannot show**

4. **The corpus is homogeneous.** All 350 CSVs come from one generator, with exactly one layout per category. The 100% CSV result measures exact matching on canonical files.
5. **PDF coverage is thin:** 95 PDF files but **only 6 distinct documents**.
   - One GBP letter, one EUR letter, policy v1.1, policy v1.2, one governance register and one return receipt.
   - IN-18 and IN-19 exist only in September.
   - All use the generator's `Label: value` line layout. Real letters and policies will not.
   - Synthetic test PDFs cover the negative cases (scanned, blank, unreadable, partial labels, two label sets, unrecognised policy). They do not widen positive coverage.

**PDF limits**

6. **Letters need the account inventory in the same set.** A letter classified on its own is `ambiguous` (IN-15 or IN-16), exactly as UC-042 behaves.
7. **Policies:** only registered versions (1.1 and 1.2) with their effective dates and markings are recognised. A real or new policy is `unknown` by design. Choosing which recognised version governs a period is out of scope.
8. **No OCR.** Image-only PDFs are reported as unsupported. Password-protected PDFs, other than empty-password encryption, are unreadable.

**Validation and relationships**

9. **Row content checks are informational.** Data rows of exactly identified CSVs are checked against UC-042's value rules, and all 350 corpus files conform. Full validation parity with UC-042 (the engine's DQ rules, period rules, duplicate-key handling) is **not** established. The Smart Parser's normalisers accept formats UC-042 rejects (for example `1,000.00`), although the generated pattern constraints flag them.
10. **Relationships are recorded, not enforced.** The registry holds the ones UC-042's definitions state:
    - IN-14 `recon_ref` to IN-05/IN-06;
    - IN-02 `acknowledgement_letter_ref` to IN-15/IN-16;
    - column descriptions that name another IN.

    Hidden contracts that live only in the engine code (`ERL-<acct>-<YYYYMMDD>`, `TOPUP-<CCY>-<YYYYMMDD>`, one ACQUIRER and one SCHEME batch per currency per day) are **not** in `schema.py`, so they are not in the registry. Importing them would need a decision on reading `validate.py`.

**Recorded unresolved definitions**

11. Unresolved definitions are recorded, not filled:
    - PDF label value types (all five PDFs);
    - IN-14 `cause_category` enumeration values;
    - IN-17 period-level policy selection.

    The IN-17 `official_name` comes from `schema.py` and says "v1.2", the baseline wording. The version actually identified is returned per file.

**Deliberate differences and environment**

12. **D-1, a deliberate difference from UC-042: decision needed.** An exact canonical header in a non-canonical serialisation is identified and flagged rather than rejected. UC-042 would reject it.
    - Covered: a `;` or tab delimiter, a non-UTF-8 encoding, or lines before the header.
    - Not covered: the BOM, which UC-042 itself accepts.
    - **Recommendation:** keep "identified + flagged" so that the mapping layer can use it, and have the UC-042 hand-off reject anything not flagged canonical. The owner should confirm.
13. **Near-miss thresholds** (overlap 0.5, tie 0.1) are UC-042's `diagnose_header` values. They only shape the explanation, never acceptance.
14. **Environment:** the tests run on the system Python 3.11, which has pytest, pydantic and pypdf 6.4.1. The UC-042 venv has no pytest. The importer must run in a fresh interpreter per UC-042 root, and it checks this.

## Changed files

All changes are in `C:\Users\artlptp263user\p10\smartparser_phase1`. The original on the Desktop is unchanged (63 files verified by hash).

**Changed: production code**

| File | Change |
|---|---|
| `smartparser/schemas/model.py` | Optional provenance fields on `FieldDefinition`; `MatchPolicy`; `CsvContract`, `PdfContract`, `PdfLabel`, `PolicyVersionInfo`, `Relationship`; new optional `SchemaDefinition` fields; `is_defined` for PDF contracts; consistency checks. Backwards compatible. |
| `smartparser/schemas/registry.py` | `_check_identities` (unique headers, declared shared label sets), `exact_header_index()`, label count in the coverage report |
| `smartparser/schemas/__init__.py` | Exports |
| `smartparser/schemas/definitions/IN-01..IN-19.json` | **Replaced:** stubs replaced by generated definitions. They are written only by `import-registry`. |
| `smartparser/classify/csv_classifier.py` | Exact-header path, near-miss `diagnose_header`, content check. The scored path is unchanged (moved into `_classify_scored`). |
| `smartparser/pdf_engine/__init__.py` | `extract_pdf` and `PdfExtraction` (the stub is replaced; `PdfEngineNotImplemented` is kept) |
| `smartparser/pipeline.py` | Raw header and rows passed to CSV classification; PDF classification; `letter_refs` parameter |
| `smartparser/models/enums.py`, `models/results.py` | `CSV_EXACT_HEADER`; new issue codes; `ClassificationResult.diagnosis/content_check/details/warnings/unsupported` |
| `smartparser/cli.py` | `classify` and `import-registry` commands; labels count |
| `pyproject.toml` | `pypdf>=4.0` dependency |
| `README.md`, `docs/ARCHITECTURE.md` | Status and Phase 1 description |

**New**

| File | Purpose |
|---|---|
| `smartparser/registry_import/uc042.py`, `__init__.py` | Controlled import, provenance, sync check |
| `smartparser/classify/content_check.py` | Row conformity against field rules |
| `smartparser/classify/pdf_classifier.py` | PDF labels, letter slot and policy recognition |
| `smartparser/classify/evidence.py` | Bytes-only `classify_bytes` and `classify_batch` |
| `tools/baseline_classification.py` | Baseline measurement with ground truth and the UC-042 oracle |
| `tests/test_registry.py` | 9 tests |
| `tests/test_classification_baseline.py` | 65 tests |
| `tests/uc042_support.py`, `tests/pdfgen.py` | Helpers; minimal PDF builder (text, image-only, blank) |
| `tests/fixtures/uc042_canonical/` | Byte-for-byte copies of `set_01_clean_baseline` (Sep, 19 categories) and `demo_history/2026-05` (May, policy v1.1 and v1.2), with a README; 40 files, 560 KB |
| `docs/PHASE1_REGISTRY_AND_CLASSIFICATION.md` | This report |

**Changed: existing tests.** Two tests are retargeted, with all their assertions unchanged. Both were written for "the shipped registry is all stubs", a premise Phase 1 had to remove:
- `test_units.py::test_official_registry_has_19_missing_stubs`
- `test_csv_scenarios.py::test_official_registry_recognised_but_schema_unavailable`

They now build the all-stub registry explicitly with `SchemaRegistry([])`, which still fills all 19 categories with stubs. They keep testing the unchanged stub behaviour, and the populated registry is tested by the new files. No assertion was removed or loosened.

## Test results

```
py -3.11 -m pytest                      136 passed in 3.4 s
UC042_ROOT=/nonexistent py -3.11 -m pytest   133 passed, 3 skipped (the UC-042-tree tests)
python -m smartparser import-registry --check   in sync: 19 definitions match <UC-042 copy>
```

Before Phase 1 there were 62 tests, all passing. After Phase 1 there are 136, all passing.

**Requirement coverage:**

| Requirement (brief §5) | Test(s) |
|---|---|
| Every CSV category | `test_each_csv_category_by_exact_header_in_two_periods` (14 categories × Sep and May) |
| Every PDF category | `test_single_slot_pdfs_identified_by_labels` (IN-17/18/19), `test_letters_resolved_…` (IN-15/16), `test_every_file_of_a_dataset_…` |
| Different reporting periods | Sep 2026 and May 2026 fixtures; the corpus test covers 9 periods |
| Different filenames, identical content | `test_identical_content_under_different_filenames`, `test_misleading_filename_does_not_change_category` |
| No reliance on filenames | `classify_bytes` takes no name; batches use opaque keys; pipeline runs use `upload.dat` and misleading names |
| Unknown / missing / extra / reordered / casing / duplicate headers | `test_unknown_header`, `test_missing_header_column_not_accepted`, `test_extra_…`, `test_reordered_…`, `test_incorrect_casing_…`, `test_header_whitespace_…`, `test_duplicate_headers_…` |
| Ambiguous CSV | `test_header_equally_close_to_two_categories_is_ambiguous` |
| Empty files | `test_empty_file`, `test_header_only_files` |
| Malformed CSV | `test_malformed_csv_data_row_is_reported`, `test_malformed_csv_header_is_not_classified` |
| Unsupported file types | `test_unsupported_file_types` (PNG, OLE2, binary, prose), `test_zip_is_not_classified_in_phase1` |
| Scanned / image-only PDF | `test_scanned_image_only_pdf_is_unsupported`, `test_pdf_without_text_or_images`, `test_unreadable_pdf` |
| Ambiguous PDF | `test_pdf_with_two_complete_label_sets_is_ambiguous`, `test_letters_are_ambiguous_without_an_account_inventory`, `test_letter_reference_not_in_inventory_is_ambiguous`, `test_batch_with_two_inventories_…` |
| GBP/EUR distinction | `test_letters_resolved_through_the_inventory_letter_reference`, `test_letter_slot_follows_the_inventory_not_the_currency_label` |
| Policy-version identification | `test_policy_versions_identified` (v1.1 and v1.2), `test_synthetic_policy_…`, `test_unrecognised_policy_is_not_accepted` (unknown version, wrong date, missing markings ×2) |
| Registry authority and sync | `test_registry.py` (9 tests, including regeneration from the live UC-042 code) |
| Whole corpus | `test_all_uc042_datasets_classify_as_declared` (445 files) |

## Boundary compliance

| Boundary | Evidence |
|---|---|
| Only the isolated copy | All edits are in `p10\smartparser_phase1`. The Desktop original was verified unchanged (63/63 hashes). |
| Original UC-042 and Clone E untouched | Neither was opened |
| No deployment | None |
| Reconciliation engine and canonical schemas unchanged | 107 UC-042 `.py` files in the working copy verified unchanged. No file in that tree is newer than the start of Phase 1. The importer runs with bytecode writing off. |
| Datasets not deleted or overwritten | 624 dataset files verified unchanged; fixtures are copies |
| No OCR, no LLM calls, no relationship mapping, no frontend | None added. The one cross-file step is UC-042's own IN-02 letter rule. |
| No weakened tests or validation rules | Two tests retargeted with identical assertions (see Changed files); no rule relaxed |

## Remaining gaps and decisions

- **D-1:** non-canonical serialisation, identified + flagged versus rejected. An owner decision is needed (see D.12).
- **Adoption:** copying `p10\smartparser_phase1` back to `Desktop\hr-projects\smartparser` was not done and needs your approval. The project has no git, so a backup should be taken first.
- **Next phase (not started, as instructed):**
  - a BA-approved alias and value-map layer;
  - LLM-assisted mapping proposals that never auto-apply;
  - cross-file relationship mapping;
  - ZIP/XLSX intake;
  - PDF field extraction (Phase 3).

  The registry and classifier are modular, so each of these can consume `SchemaRegistry` unchanged.
- **Test-data need:** meaningful accuracy figures for real-world formats need non-canonical samples. These would be real or BA-authored variants: renamed and reordered columns, other delimiters, real bank letters and policies. The current corpus cannot provide them.
- **Hidden contracts:** importing the engine-only ID contracts into the registry (see D.10) needs a decision on using `uc042lib/validate.py` as a source.
