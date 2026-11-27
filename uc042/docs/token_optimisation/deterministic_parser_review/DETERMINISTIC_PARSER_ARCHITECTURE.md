# UC-042: Deterministic ZIP Parser Architecture

**What this is.** A read-only reverse engineering of `p10/uc042_token_optimisation` on 18 Nov 2026. No code, test, schema, dataset, database or configuration was changed.

**Evidence labels:**

| Label | Meaning |
|---|---|
| **[CODE]** | Read in the source at the cited `file:line`. |
| **[TEST]** | Asserted by an existing test. |
| **[DOC]** | Stated in project documentation only. |
| **[UNKNOWN]** | Could not be established. |

**There is no AI at any stage of ingestion or parsing.** AI is used only after a pack exists, for exception investigations. The future Smart Parser hook `zip_package.resolve_unexpected` returns `None` [CODE `uc042app/ingest/zip_package.py:90-93`] [TEST `test_zip_submissions.Reading.test_no_smart_parser_fallback`].

**Line-number caveat.** A separate implementation process was active in this working copy on 17 Nov, so line numbers may drift. Function names are the stable reference.

---

## 1. End-to-end flow

```
POST /api/v1/periods/{period_id}/packages  (multipart field "file")          api/routers/monthly.py upload_package
  │  archive read capped at max_archive_bytes+1 → 413 PACKAGE_TOO_LARGE
  ▼
MonthlyService.upload_package                                                  services/monthly.py
  ├─ store.put(zip bytes)            ZIP kept content-addressed (never processed)
  ├─ zip_package.read_package        SAFETY + INVENTORY + FILENAME MAPPING      ingest/zip_package.py
  │     PackageRejected ─────────────► batch PACKAGE_REJECTED (no documents)
  │     unsafe/unexpected/duplicates ► batch PACKAGE_REJECTED (no documents)
  ├─ MonthlyService.upload(origin=ZIP_SUBMISSION, independent=True)
  │     per file: store.put → analysis.analyse_file                           ingest/analysis.py
  │                └─ prepare.identify  CONTENT IDENTIFICATION                  uc042lib/prepare.py
  │                     CSV: exact header == schema.columns(fid)
  │                     PDF: all key-detail labels of one type present
  │                └─ analyse_csv / analyse_pdf / analyse_policy  (dates, period, keys, policy registry)
  │     _resolve_letters (IN-15/IN-16 by IN-02 letter ref, this ZIP only)
  │     _duplicates (within this ZIP only)
  ├─ _package_gate   COMPLETENESS GATE (name == content, no ERROR docs, 17 required present)
  │     fail ► batch PACKAGE_INCOMPLETE      pass ► batch VALIDATED
  ▼
POST /api/v1/uploads/{batch_id}/submit   → MonthlyService.submit_for_audit   NEW submission ID + NEW run every time
  ▼  job (background)
MonthlyService._execute → _process                                             services/monthly.py
  ├─ materialise this package's document set into a temp folder (names {fid}_{doc}.csv/pdf; SHA re-verified)
  ├─ prepare.prepare_case(work, case, period)   RE-IDENTIFY BY CONTENT, canonical names, manifest.csv, intake.csv,
  │                                               policy_selection.json                 uc042lib/prepare.py
  │     MISSING / AMBIGUOUS / REJECTED required ► run FAILED (no pack)
  ├─ pack.generate.build(case, period)          uc042lib/pack/generate.py
  │     └─ validate.Validator.run()             THE DETERMINISTIC ENGINE             uc042lib/validate.py
  │           load (header, rows, types, period) → setup → 18 check stages → exceptions → candidates
  │     └─ assemble / finalise / validate_pack / render_html
  └─ _publish (write-once pack), register pack, auto-investigations (AI, separate jobs)
```

---

## 2. Stage by stage

| # | Stage | Module / function | Input → Output | Validation rules | Failure behaviour | Deterministic? |
|---|---|---|---|---|---|---|
| 1 | ZIP reception | `api/routers/monthly.py::upload_package`; `ZipLimits.from_env` | multipart `file` → bytes | Size ≤ `max_archive_bytes` (100 MB default, env `UC042_ZIP_MAX_ARCHIVE_BYTES`). The period must already exist (`MonthlyService._period`). | 413 `PACKAGE_TOO_LARGE`; 404 unknown period | Yes |
| 2 | Archive inspection | `zip_package.read_package` | bytes → `(inventory, files)` | Magic bytes `PK\x03\x04` / `PK\x05\x06` / `PK\x07\x08`; `zipfile.ZipFile` must open | `PackageRejected` `NOT_A_ZIP` / `PACKAGE_UNREADABLE` → batch `PACKAGE_REJECTED`, error recorded | Yes |
| 3 | Extraction and safety | `read_package`, `_unsafe_path`, `_is_metadata` | each entry → `unsafe[]`, `ignored_metadata[]` or content bytes (in memory only; nothing is written to disk) | **Unsafe:** absolute path, drive letter, `..`, NUL in the name, symlink, encrypted entry, `> max_file_bytes` (50 MB), compression ratio `> 200`, `> max_entries` (40) file entries, total `> 200 MB`, unreadable entry.<br>**Ignored:** `__MACOSX/`, `._*`, `.DS_Store`, `Thumbs.db`, `desktop.ini`, `ehthumbs.db`.<br>**Nested ZIP** (`.zip` name or `PK` magic) → `unexpected`.<br>**Folders are flattened** to the base name. A case-insensitive repeated base name goes to `duplicate_names`. | Any unsafe entry → `archive_safe=False` and **no file is analysed**; batch `PACKAGE_REJECTED` | Yes |
| 4 | Filename recognition | `zip_package.map_filename` → `PeriodConfig.file_id_of` (`uc042lib/period.py`), `period.POLICY_FILE_RE` | base name → `(evidence_id, policy_version, problem)` | **Exact, case-sensitive equality** with `FILE_PATTERNS[fid]` rendered for the selected period. IN-17 matches the regex `^safeguarding_reconciliation_policy_v(\d+\.\d+)\.pdf$`. A schema name for another month → "named for another reporting period". IN-19 not for the previous month → its own message. | `unexpected[]` → whole package `PACKAGE_REJECTED`. More than one file per evidence ID → `duplicate_types` → rejected. | Yes |
| 5 | Required / optional | `PeriodConfig.requirement`, `required_ids`, `optional_ids`; `_package_gate` | evidence IDs present in the package's usable set | Required: IN-01…IN-17 (14 CSV + IN-15, IN-16, IN-17). Optional: IN-18, IN-19 (`schema.PDF_FILES[...][2]`). | Missing required → `PACKAGE_INCOMPLETE` (`missing_required`) | Yes |
| 6 | CSV/PDF identification by content | `prepare.identify` (via `analysis.analyse_file`) | stored file → `CSV fid` / `PDF [candidates]` / `REJECT` | `%PDF-` magic → PDF. `PK\x03\x04` → reject ("export as CSV"). Otherwise UTF-8 CSV whose header equals one schema column list. PDF: candidates = types whose **every** label is found. | `UNRECOGNISED` ERROR (with `header_diagnosis`) → doc unusable → gate fails (`mismatches`/`unusable`) | Yes |
| 7 | Schema selection | `prepare.identify` (CSV), `_resolve_letters` (IN-15/IN-16), `policy.recognise` (IN-17) | content → evidence ID | CSV: by header only. Letters share labels: slot = IN-02 row whose `acknowledgement_letter_ref` equals `Letter reference` and whose `account_id` is in `LETTER_SLOTS` (`SGA-GBP-01`→IN-15, `SGA-EUR-01`→IN-16), **from the same ZIP only** (`independent=True`). | `LETTER_NOT_MATCHED` ERROR; name/content disagreement → `mismatches` | Yes |
| 8 | Header validation | `prepare.identify`; engine `validate.load_csv`; diagnosis `structure.diagnose_header` | header list | Exact equality: names, case, order, count. **No aliases.** `diagnose_header` only explains a failure (LIKELY / AMBIGUOUS / UNKNOWN, with missing/extra/misordered/case lists); it never accepts a file. | Intake `UNRECOGNISED`; engine `V01-SCHEMA` FAIL, file `UNUSABLE` | Yes |
| 9a | Data type and format at intake | `analysis.analyse_csv` | rows → messages | **Date/ts columns only:** invalid → `INVALID_DATE` WARNING; mandatory empty → `MISSING_DATE` WARNING; governing date outside the month → `OUT_OF_PERIOD_RECORDS` WARNING, or `WRONG_PERIOD` **ERROR** if no row is in the month; IN-01 `period_id` ≠ period → ERROR; 0 rows → `NO_RECORDS` ERROR (INFO for IN-04/IN-14); repeated first-column key → `REPEATED_RECORD_ID` WARNING. | Only ERROR blocks the gate; warnings are reported | Yes |
| 9b | Data type and format in the engine | `structure.check_rows`, `field_error`, `money.parse_*` | rows → valid rows + `DQ-FIELD` findings | All types (`amount` `^\d+\.\d{2}$`, `signed`, `date`, `ts` with offset, `bool`, `int`, `ccy` GBP/EUR, `id` regex), `schema.ENUMS`, mandatory, `schema.CONDITIONAL`, duplicate primary key, row width | Row excluded and tainting dependent checks (INSUFFICIENT_EVIDENCE). Any invalid row in IN-01/IN-02 → whole file UNUSABLE. | Yes |
| 10 | Deterministic parsing | `structure.read_csv` (`csv.DictReader`, `utf-8-sig`); `prepare._pdf_details` / `validate.load_pdf` (pypdf, regex `^Label: (.+)$`) | bytes → `{column: str}` rows with `_line`; PDF `{label: value}` | Values stay **strings**; `Decimal` only inside calculations; no implicit conversion or normalisation | see 9 | Yes |
| 11 | Canonical data construction | `prepare.prepare_case` | identified files → case folder (`source_data/<canonical>.csv`, `supporting_documents/<canonical>.pdf`, `manifest.csv`, `intake.csv`, `policy_selection.json`) | Re-identifies by content (`{fid}_{doc}` temp names are ignored); duplicate SHA → `DUPLICATE`; two candidates for one slot → `AMBIGUOUS`; IN-17 re-recognised and selected (`policy.select`). Copies are byte-for-byte; **no field is renamed or transformed**. | MISSING/AMBIGUOUS/REJECTED required → run `FAILED` | Yes |
| 12 | Reconciliation input prep | `validate.Validator.load` → `load_csv` / `apply_period` / `load_pdf`; `setup` | case → `self.data[fid]` (period-kept valid rows), `self.pdf`, `self.state`, `self.taint`; indices (recon days, accounts, statements…) | Manifest hash and record count; `check_period` (`schema.PERIOD_RULES` with `period.period_rules`); `check_other_periods`; policy `Reconciliation point` must match `HH:MM Europe/London`; a policy effective after the period end is dropped | `V00-FILE`, `V01-*`, `DQ-PERIOD` results; files unavailable → `schema.DEPENDS` gates INSUFFICIENT_EVIDENCE | Yes |
| 13 | Reconciliation and controls | `Validator.run` → `check_policy_and_points` … `check_checklist`, `_group_exceptions`, `_correlate_exceptions`; `pack.generate.build` | data → results, exceptions, candidate relationships, pack | See `UC042_CROSS_DOCUMENT_VALIDATION.md` | FAIL / INSUFFICIENT_EVIDENCE results become exceptions; the pack is still generated | Yes. AI runs only afterwards, on the pack's exceptions. |

---

## 3. Key design facts

1. **Two identities must agree.**
   - The ZIP path checks the **filename** (stage 4) **and** the **content** (stage 6); both must give the same evidence ID [CODE `_package_gate`] [TEST `Gate.test_filename_content_mismatch_fails`].
   - The engine then ignores names and re-identifies by content (`prepare_case`).
2. **One central schema.**
   - Names come from `uc042lib/period.py::FILE_PATTERNS`.
   - Columns, types, enums, conditions and period rules come from `uc042lib/schema.py`.
   - Formats come from `uc042lib/structure.py`.
   - The ZIP module holds no second schema [CODE docstring `zip_package.py:9-13`].
3. **Independence.** A ZIP batch never borrows documents from earlier uploads:
   - no letter-slot fallback;
   - no duplicate comparison with other batches;
   - no reassessment baseline;
   - the run's `document_set` is `submission_set(batch_id)` only [CODE `submission_set`, `upload(independent=True)`] [TEST `WithHistoricalLegacyBatches.test_no_inheritance_from_earlier_packages_or_uploads`].
4. **The gate is about completeness, not data quality.** Row-level type and enum errors are found by the engine **after** Submit for Audit. They do not stop a package from being submitted; they become DQ-FIELD exceptions. *(This is the main point the Smart Parser design must be aware of.)*
5. **Strings throughout.**
   - No trimming, case-folding, alias mapping or locale handling.
   - A value is valid exactly as written or not at all [CODE `structure.py` docstring] [TEST `test_hardening.MalformedRows.test_amount_with_thousands_separator_is_rejected_not_converted`].
6. **The period is chosen by the user, not inferred.** The URL `period_id` selects the period. File names must carry that period's month token, and IN-19 the previous month's.

---

## 4. Documentation versus implementation

| # | Documentation says | Implementation does | Classification |
|---|---|---|---|
| D1 | `docs/UC042_UPLOAD_CONTRACT.md:52`: "Identification uses content only. File names, extensions, folders and any user-supplied manifest are ignored." | True of the **retired** individual-document upload and of `prepare_case`. **False for the ZIP path:** an exact canonical file name is mandatory and must agree with the content. | Documentation outdated for the ZIP workflow |
| D2 | `zip_package.py:199-200` comment: "the engine itself refuses more than one policy version per case" | The engine accepts several versions through `policy.APPROVED_SELECTIONS` (PER-2026-05). A ZIP with two IN-17 versions is rejected as a `duplicate_type`. | Known and deferred: `DEFERRED_SMART_PARSER_REQUIREMENTS.md` M5 |
| D3 | `schema.py` column descriptions mark `identified_date`, `allocated_date` (IN-04), `d1_requirement`, `d1_resource` (IN-05), `end_to_end_ref` (IN-09), `auth_ts`, `clearing_date` (IN-11) as **C** (conditional) | No rule in `schema.CONDITIONAL`, so blanks are always accepted. `end_to_end_ref` is effectively needed by RC4/C09 matching, but no row-level rule exists. | Description-only conditions |
| D4 | `IN-14 cause_category` has type `enum` | No allowed-value list in `schema.ENUMS`, so any value passes | Unspecified enumeration |
| D5 | `ZipLimits.max_entries` (40) described as a limit | Excess is recorded as unsafe, but every entry is still read | Known and deferred: M6 |

---

## 5. What is UNKNOWN

- **Accepted `ts` variants.** `datetime.fromisoformat` (Python 3.11) also accepts forms such as `2026-09-15 17:00:00+01:00` (space separator) and a `Z` suffix. There is no test pinning the accepted set. **Use the `T` and `±HH:MM` form only.**
- **PDF text extraction across generators.** The engine depends on pypdf putting each `Label: value` on its own extracted line. This is proven only for ReportLab output (`uc042lib/generate.py::write_pdfs`). PDFs from other tools (browser print, Word, LaTeX) are untested.
- **Behaviour under very large row counts.** Not measured.
