# UC-042: Deterministic Parser Test Coverage

**What this is.** A read-only inventory of the tests in `p10/uc042_token_optimisation/tests`, made on 18 Nov 2026.

**No tests were run for this review.** The implementer's latest recorded results (17 Nov 2026, consolidated remediation report) were:
- file mode: 891 OK;
- PostgreSQL: 886 OK, plus 3 pre-existing errors in `test_api_registry`;
- vitest: 86.

These numbers are reported, not re-verified.

---

## 1. Test evidence by area

| Area | Tests (`file::Class::test`) | What is proven |
|---|---|---|
| **ZIP reading and safety** | `test_zip_submissions::Reading`, 12 tests:<br>`test_a_complete_package_maps_every_file_through_the_central_schema`, `test_folders_inside_the_zip_are_flattened`, `test_operating_system_metadata_is_listed_and_ignored`, `test_unexpected_and_wrong_period_files_are_reported_with_the_reason`, `test_nested_zip_is_unexpected`, `test_unsafe_entries_reject_every_file`, `test_symlink_and_encrypted_entries_are_unsafe`, `test_duplicate_flattened_names_and_duplicate_types`, `test_limits_entries_size_total_and_ratio`, `test_not_a_zip_and_corrupt_archives_are_rejected`, `test_limits_are_configurable_and_validated`, `test_no_smart_parser_fallback` | Safe reading, flattening, metadata ignored, unexpected and wrong-period names, nested ZIPs, `..`, symlink and encryption, upper-case duplicate names, limits, the non-ZIP case, no AI fallback |
| **Filename recognition** | `Reading.test_a_complete_package_maps_every_file_through_the_central_schema`, `Reading.test_unexpected_and_wrong_period_files_are_reported_with_the_reason`, `Gate.test_wrong_period_package_is_rejected` | All 19 canonical names map; another month's file and a wrong IN-19 month are rejected with the reason |
| **Completeness gate** | `test_zip_submissions::Gate`, 12 tests | Complete pass; missing required; optional absent; IN-04/IN-14 header-only; unexpected → no analysis; duplicate type; duplicate name; wrong period; **name/content mismatch** (IN-01 and IN-11 swapped); unreadable PDF; unsafe or nested; not a ZIP |
| **Submission semantics** | `test_zip_submissions::Independence`, `WithHistoricalLegacyBatches`, `SubmissionReview`, `IdenticalFindings`; `test_zip_only_workflow` (19 tests) | A new submission and run every time; no inheritance; scoping; retired endpoints refuse ZIP batches |
| **Header (schema) validation** | `test_period_and_headers::HeaderDiagnosis`: `test_missing_column`, `test_extra_column`, `test_misordered_columns`, `test_case_difference_is_named_not_accepted`, `test_ambiguous_header_is_not_guessed`, `test_unrelated_header`, `test_intake_rejects_near_match_with_actionable_detail`; `test_hardening::MissingEvidence::test_wrong_header_is_unusable_not_missing` | Exact header only; renamed, missing, extra, misordered and case-changed columns are rejected and explained, never accepted |
| **Field formats (CSV parsing)** | `test_hardening::FormatRules` (`test_documented_amount_rule`, `test_dates_identifiers_enums`); `MalformedRows` (`test_bad_debit_credit_code`, `test_amount_with_thousands_separator_is_rejected_not_converted`, `test_unknown_batch_direction`, `test_bad_date_taints_every_scope_it_might_touch`, `test_bad_identifier`, `test_wrong_number_of_fields`, `test_invalid_row_in_scope_file_makes_it_unusable`) | Amount, date, id and enum rules; row exclusion and tainting; scope-file rule |
| **Missing and empty evidence** | `test_hardening::MissingEvidence` (calendar, inventory, cash book, policy, present-but-empty, empty-allowed); `test_period_config::DocumentApplicability::test_optional_documents_do_not_block_and_missing_stays_missing`; `Gate.test_optional_documents_may_be_absent` | Missing → INSUFFICIENT_EVIDENCE, never zero; optional documents do not block |
| **Reporting period** | `test_period_and_headers::ReportingPeriod` (8 tests); `test_period_decisions::A1UnallocatedReceipts`, `A2DiscrepancyLog`; `test_period_config` (calendar, DST, case resolution) | DQ-PERIOD, WRONG_PERIOD, permitted boundary rows, DST offsets not hard-coded, IN-04 open-during-period, IN-14 event reference |
| **Content identification (case preparation)** | `test_hardening::CasePreparation`: `test_identification_ignores_misleading_names`, `test_ambiguous_candidates_are_not_selected`, `test_missing_types_are_recorded`, `test_prepared_case_validates_identically_to_baseline`, `test_validator_runs_without_any_manifest` | Content, not names, decides in `prepare_case`; ambiguity is never resolved by guessing |
| **Letter slot (cross-document at intake)** | `test_phase8` (around lines 290–299: `LETTER_NOT_MATCHED` present or absent) | A letter is matched to IN-02, or reported as an ERROR |
| **Policy registry** | `test_historical_integration` (`POLICY_NOT_RECOGNISED`); `test_period_config::DocumentApplicability::test_policy_effective_after_the_period_is_not_applied`; `test_demo_history` | Unregistered or inapplicable policy refused |
| **Cross-document reconciliation** | `test_baseline::CleanBaseline` (`test_no_failures_or_missing_evidence`, `test_essential_checks_ran_on_every_scope`, `test_every_citation_resolves`); `ChecksCanFail` (requirement not trusted, cash-book change, missing confirmation is INSUF, equal amount is not a link, fee lines required, renamed text file is not a PDF); `Regressions` | The clean set passes every check; checks can fail; links are by reference only |
| **Deterministic reconciliation inputs and outputs** | `test_hardening::GoldenRegression::test_golden_results_and_exceptions_unchanged` (golden re-pinned 17 Nov); `test_baseline::Determinism`; `test_scenario_datasets` (answer keys of the 9 September sets); `test_rules_c06_c08_c09` | Reproducible results; the scenario answer keys hold; the 17 Nov rules |
| **Monthly upload path (shared analysis)** | `test_api_monthly::Upload` (identification, wrong period, partial out-of-period, invalid and empty files, duplicates, missing categories) | `analysis.analyse_file` messages |

---

## 2. Gaps: behaviour with no dedicated test

| # | Behaviour | Code | Risk |
|---|---|---|---|
| G1 | **UTF-8 BOM** accepted (`utf-8-sig`) | `structure.read_csv` | No test with a BOM-prefixed file (none found for `BOM` / `utf-8-sig` / `\xef\xbb\xbf`) |
| G2 | **Non-UTF-8 encodings** (cp1252, UTF-16) rejected | `prepare.identify` | No test |
| G3 | **CRLF** line endings and **quoted fields** with commas or newlines | Python `csv` | Indirect only: baseline IN-02 and IN-05 contain quoted commas; no CRLF ZIP test in `test_zip_submissions` |
| G4 | **Upper-case or mis-cased single file name** (not a duplicate) → unexpected | `map_filename` exact match | Covered only as a duplicate (`Reading.test_duplicate_flattened_names_and_duplicate_types` uses `IN11.upper()` next to the original) |
| G5 | **Timestamp variants** (`Z`, space separator, minutes-only, basic format) | `structure.parse_ts` (`datetime.fromisoformat`, Python 3.11 accepts all) | No test pins the accepted set; `Z` passes type validation but fails C03-POINT on IN-07 |
| G6 | `NO_RECORDS` ERROR for a header-only required CSV in a ZIP | `analysis.analyse_csv` | Covered in the engine (`MissingEvidence.test_present_but_empty_required_file`), not at the gate |
| G7 | **`LETTER_NOT_MATCHED` inside a ZIP** (independent mode, no fallback) | `_resolve_letters(independent=True)` | Tested in the legacy upload path only (`test_phase8`) |
| G8 | Policy name/content version mismatch (`IN-17 v1.2` file holding v1.1) | `_package_gate` | No test found |
| G9 | Two IN-17 versions for PER-2026-05 | `read_package` duplicate types | Known defect M5 (`DEFERRED_SMART_PARSER_REQUIREMENTS.md`); no acceptance test |
| G10 | Entry-count limit enforced before reading | `read_package` | Known defect M6 |
| G11 | **FUND-TOPUP** reference `TOPUP-<CCY>-<YYYYMMDD>` | `check_topups` | Covered by the baseline and scenarios only (no direct `TOPUP-` assertion found); `test_baseline::Regressions::test_topup_with_missing_statement_is_insufficient` |
| G12 | **DISC-LOG** `ERL-` contract when `ext_recon_id` uses another format | `_group_exceptions`, `PERIOD_RULES["IN-14"]` | No negative test |
| G13 | PDFs produced by tools other than ReportLab | `prepare._pdf_details` | No test; only `generate.write_pdfs` output is exercised |
| G14 | `IN-14 cause_category` free values; description-only conditionals (IN-04 `allocated_date`/`identified_date`, IN-05 `d1_*`, IN-09 `end_to_end_ref`, IN-11 `auth_ts`/`clearing_date`) | `schema.ENUMS`, `schema.CONDITIONAL` | Unenforced by design or by omission; no test documents the intent |
| G15 | Very large files and row counts | — | Not measured |

---

## 3. Discrepancies and limitations (summary)

See `DETERMINISTIC_PARSER_ARCHITECTURE.md` §4 for detail.

1. **Upload contract outdated.** `docs/UC042_UPLOAD_CONTRACT.md:52` says names and folders are ignored. For ZIPs, exact names are mandatory and must agree with the content.
2. **Multiple policy versions.** These are rejected in ZIPs (M5), although the engine supports approved selections.
3. **Gate scope.** The gate is a completeness gate. Type and enum errors in rows reach the engine and become DQ-FIELD exceptions in the pack. A "VALIDATED" package can therefore still produce data-quality exceptions.
4. **Fixed safeguarding account IDs.** `SGA-GBP-01` and `SGA-EUR-01` are hard-coded (letter file names and `LETTER_SLOTS`). The parser does not support any other safeguarding account set.
5. **Fixed currencies.** Only `GBP` and `EUR` are supported (`structure.CURRENCIES`).

---

## 4. Recommended validation runs for the two Claude Web datasets

To do after the datasets are generated; nothing was run for this review.

1. **Unit-level, read-only:** call `uc042app.ingest.zip_package.read_package(zip_bytes, "PER-2026-09")` and assert empty `unsafe`, `unexpected`, `duplicate_names` and `duplicate_types`, and 17–19 mapped files.
2. **Engine-level, offline:**
   - unzip into a temporary folder;
   - run `python -m uc042lib.prepare <tmp_in> <tmp_case> --period PER-2026-09`;
   - run `python -m uc042lib.validate <tmp_case>`;
   - compare the results with each dataset's expected-outcome manifest.

   This touches no database.
3. **Application-level:** only in an isolated environment with a disposable database (as `docs/token_optimisation/zip_submission/launch_backend.py` does): upload the package, check the gate, then Submit for Audit. **This needs owner approval**, because it creates a run, and any AI investigation is a provider call.
