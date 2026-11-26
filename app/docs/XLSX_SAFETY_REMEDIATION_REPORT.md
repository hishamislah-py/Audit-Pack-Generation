# Experiment C1: XLSX Safety Remediation and Verification

**Date:** 19 Nov 2026
**Scope:** `C:\Users\artlptp263user\p10\smartparser_phase1\experiments\realworld_formats\` only
**Follows:** `docs/REALWORLD_XLSX_JSON_COMPATIBILITY_REPORT.md` (Experiment C)
**Evidence:** `Downloads\UC042_REALWORLD_XLSX_JSON_EXPERIMENT\`, which holds:
- `inputs_c1/`;
- `run3/` and `run4/`;
- `summary_c1.json`;
- `tests_c1/`;
- `regression_c1/`.

**Status:** remediation complete inside the experiment. This report is a controlled remediation exercise. It does **not** approve integrating XLSX into the Smart Parser and does **not** declare XLSX production-ready. It stops for owner review.

## Summary

The two silent data changes found in Experiment C no longer produce an eligible canonical preview:

| Finding | Experiment C (run1) | C1 (run3 = run4) |
|---|---|---|
| **X20**: numeric cells holding leading-zero identifiers | `SILENT_DIFFERENCE`: eligible preview with `ledger_entry_id` "1" (expected "0000001") and `payment_reference` "42000001" (expected "0042000001") | `GATE_BLOCKED`: 448 `NUMERIC_CELL_IN_TEXT_LIKE_COLUMN` findings with locators; no preview file |
| **X13**: money value needs more than 15 significant digits | `SILENT_DIFFERENCE`: eligible preview with `balance_amount` "12345678901234570.00" (expected "12345678901234567.89") | `GATE_BLOCKED`: `PRECISION_EXCEEDS_15_DIGITS` at `Bank!E3`, raw stored literal `1.234567890123457e+16`; no preview file |

Across the whole run, 0 silent differences remain in any set, including 17 new C1 scenarios and the 16 adversarial cases. Both runs are identical. Input hashes are unchanged. The JSON results are byte-for-byte identical to Experiment C. The main package, CSV and PDF behaviour, the registry and the protected trees are all unchanged; the regression passes 620/620.

## 1. Original findings (X13, X20)

**X20.**
- **Source:** a CashBook (IN-10) sheet whose `ledger_entry_id` and `payment_reference` were typed as Excel numbers (`0000001`, `0042000001`, …).
- **What happened:** the existing workflow mapped every column deterministically, ran all 14 handoff checks, found the file **eligible**, and wrote a canonical preview containing `1` and `42000001`. The UC-042 `id` pattern `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` accepts both, so validation could not notice.
- **What Experiment C already knew:** its extractor marked every such cell `NUMERIC_CELL`. The bridge even computed `NUMERIC_CELL_IN_TEXT_LIKE_COLUMN` ("caught by proposed safeguard = True"). Nothing used that result in the eligibility decision.

**X13.**
- **Source:** a Bank (IN-07) sheet with two large balances: 98765432109.99 (13 significant digits) and 12345678901234567.89 (19).
- **What happened:** the second value is held in the file as the double `1.234567890123457e+16` and rendered as `12345678901234570.00`. That text matches the money pattern `^\d+\.\d{2}$`, so the file was **eligible** and the preview carried a different amount.
- **What Experiment C already knew:** the extractor emitted `PRECISION_EXCEEDS_15_DIGITS`, but again nothing acted on it.

## 2. Root causes

The sheet XML was inspected directly (`xl/worksheets/sheetN.xml`).

**X20: the zeros are not in the file.**
- The cells are `<c r="A2" t="n"><v>1</v></c>` and `<v>42000001</v>`. Excel stored the integer, and leading zeros are not part of a number.
- No extractor, formatting rule or review can recover them without **guessing** the width. Even a `0000000` display format is only presentation: it says how to *show* the number, not what the identifier *was*. (Was it 7 characters? Was it ever zero-padded?)
- The only safe answer is to refuse.

**X13: the value was lost before the file was written.**
- The stored literal is `1.234567890123457e+16`. A double carries about 15–17 significant decimal digits, and Excel documents 15 digits of precision.
- The typed `…567.89` does not exist anywhere in the package. The extractor read the stored value faithfully; the change happened when the workbook was saved.
- The only safe answer is to refuse.

**The common cause: warnings were generated and then ignored.**
- The Experiment C extractor reported both problems.
- The existing workflow decides eligibility from the bridged CSV text alone: mapping, validation patterns and the 14 handoff checks. XLSX cell provenance (numeric type, stored precision) never reaches that decision.
- The bridge recorded the warnings as `ir_blocking` but let the existing writer produce the preview regardless.

**A second, smaller cause (X13 rule).**
- The Experiment C precision check counted digits of the **rendered text**. Declared trailing zeros (`999999999999999.00` gives 17 digits) inflated the count, and writer noise in a raw literal could too.
- It was correct for X13 by coincidence, not by construction.

## 3. Changes (all inside `experiments/realworld_formats/`)

| File | Change |
|---|---|
| `extract.py` | Extractor id `xlsx-extractor/0.2-experiment-C1`, policy `xlsx-strict-faithful/2`. New `XLSX_WARNING_POLICY`, which classifies every XLSX cell warning, table warning and workbook note (§4). New `significant_digits()`: digits of the **shortest round-trip repr of the stored double**, more than 15 means `PRECISION_EXCEEDS_15_DIGITS`. New `declared_decimals()` for Excel number formats. New `raw_numeric_literals()`: reads the stored `<v>` literal of every numeric cell from the sheet XML; if that cannot be read, the workbook is refused (`WORKBOOK_UNREADABLE: sheet XML`). `Cell.raw` holds that literal, so the source representation is preserved next to the rendered text. JSON code paths, `BLOCKING` and `INFO` are unchanged; JSON digests are unchanged because `raw` is omitted when `None`. |
| `bridge.py` | The **XLSX hard gate**, described below. |
| `run.py` | `generate_c1`; `--sets`; expectation overrides X13 and X20 → `GATE_BLOCKED`; new metrics: `gate_blocked`, `gate_findings`, `counterfactual_silent_differences_stopped`, plus per-set XLSX summaries. Workbook notes are checked for classification. |
| `scenarios_c1.py` (new) | 17 additional XLSX scenarios, X38–X54 (§6). |
| `test_c1_remediation.py` (new) | 30 unit tests (§8). |
| `scenarios.py`, `test_realworld.py` | Unchanged; the original Experiment C inputs were **not regenerated**. |

How the XLSX hard gate works (`bridge.py`):

1. For XLSX tables, both orchestrator passes run with **no preview directory**: the content-classification pass and the slot/category pass. The existing workflow still maps, validates, routes to review and runs all 14 handoff checks exactly as before. It simply cannot write a preview by itself.
2. If the existing workflow says **eligible**, `xlsx_gate()` takes the **final** mapping (`reprocessed.result.mapping`: deterministic, reviewed, or file-specific rule). It checks **every cell of every mapped column**:
   - any `HARD_WHEN_MAPPED` extractor code;
   - `NUMERIC_CELL` feeding an `id`/`str`/`enum`/`ccy` field → `NUMERIC_CELL_IN_TEXT_LIKE_COLUMN`;
   - `BOOLEAN_CELL` feeding a non-boolean field → `BOOLEAN_CELL_IN_NON_BOOLEAN_COLUMN`;
   - `NUMERIC_CELL` feeding a money field whose format does not declare exactly 2 decimals → `MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT`.
3. Each finding records the code, field, field type, **locator**, rendered text, **raw stored literal**, cell type and number format.
4. The existing, unchanged `write_preview` runs **only if the gate is clear**. Otherwise the outcome is `GATE_BLOCKED`, or `REVIEW->GATE_BLOCKED` after review.
5. If the existing workflow already refused the file, the gate runs on the deterministic mapping for reporting only.
6. A **counterfactual** preview (what the writer would have produced without the gate) is computed **in memory only**, to prove which blocks stopped a real silent difference.
7. Any warning code without a policy decision raises `UnclassifiedWarning` and stops the run. This applies to cells, tables and workbook notes, and even when no column is mapped.

The gate never modifies a value. It does not pad, trim, round, re-parse or apply the display format. It only allows or refuses. The original upload and its SHA-256 are untouched; inputs are re-hashed after both runs.

**Found and fixed during C1.** The new end-to-end unit test caught a preview leak. The bridge's *content-classification* pass (an orchestrator run without a category) still had a preview directory. For X20-like data it wrote an unsafe `PREVIEW_ONLY_…csv` to disk, even though that result was never used for the outcome. It now also runs without previews for XLSX. Every XLSX table now records `preview_files_on_disk`: across run3 every blocked table has **0** preview files, and every EXACT table has exactly **1**, the gated one.

## 4. Blocking-warning decisions

`HARD_WHEN_MAPPED` means the table is refused at handoff if any such cell feeds a canonical field. A warning on an unmapped or ignored column cannot reach the preview and is reported only.

The test for a hard block: could the value be unknown, changed or ambiguous **and still pass** UC-042 validation in at least one field? Optional and free-text fields, such as IN-02 `close_date` and IN-07 `bank_statement_ref`, accept almost anything, so validation is not a safety net there.

| Code | Decision | Justification (and C1 scenario that proves the gate is needed) |
|---|---|---|
| `NUMERIC_CELL_IN_TEXT_LIKE_COLUMN` (gate) | HARD | Leading zeros and identifier characters are not stored by Excel. Applies even when no zero is visibly lost: a numeric ID is not text (X20, X38, X39, X40). |
| `PRECISION_EXCEEDS_15_DIGITS` | HARD | The stored double cannot be trusted as the source value (X13, X42–X44, X40). |
| `MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT` (gate) | HARD | Without a declared 2-decimal format the text depends on the value: 2926.33 passes but 250000 does not. An all-cents column would pass silently (X46). |
| `PERCENT_FORMAT` | HARD | 12% is stored as 0.12, which matches the money pattern (X47). |
| `BOOLEAN_CELL_IN_NON_BOOLEAN_COLUMN` (gate) | HARD | "true" passes a free-text field (X48). |
| `CELL_ERROR` | HARD | `#N/A` is not a value but passes free text (X49). |
| `FORMULA_NO_CACHED_VALUE` | HARD | Value unknown (never evaluated); an empty optional field "matches" (X50). |
| `MERGED_IN_DATA` | HARD | Merged-away cells read empty; an optional field silently loses data (X51). |
| `DATETIME_NO_OFFSET` | HARD | Excel cannot store an offset. A free-text field accepts the incomplete text (X52); timestamp fields already fail validation (X25). |
| `TIME_ONLY_CELL` | HARD | No UC-042 field is a bare time; free text accepts it (X53). |
| `UNEXPECTED_CELL_TYPE` | HARD | Unknown type means unknown rendering. |
| `NUMERIC_CELL` | INFO | Marker consumed by the gate rules above. |
| `BOOLEAN_CELL` | INFO | Marker; "true"/"false" is the UC-042 boolean form. |
| `FORMULA_CACHED_VALUE` | INFO | The cached result Excel saved is used, never re-evaluated (X27 EXACT). |
| `CURRENCY_FORMAT` | INFO | Display only; the stored number is used and no symbol enters the value (X16 EXACT). |
| `NEGATIVE_DISPLAYED_IN_PARENTHESES` | INFO | Display only; the signed stored number is used (X14 EXACT). |
| `HIDDEN_PRECISION` | INFO | The stored value is emitted (never the rounded display), so validation sees the extra decimals (X12). |
| `NUMBER_NO_DECLARED_DECIMALS` | INFO | For money fields the gate rule applies; for other fields the value is faithful. |
| `DATE_LIKE_TEXT_NOT_ISO`, `NUMBER_LIKE_TEXT_NON_CANONICAL`, `SURROUNDING_WHITESPACE`, `WHITESPACE_ONLY` | INFO | Text is kept verbatim and never converted. Typed fields fail validation visibly (X15, X24, X31); in free text it is the genuine source text. |
| `HIDDEN_ROW`, `HIDDEN_COLUMN` | INFO | Data is kept; visibility is presentation (X30 EXACT). |
| `TITLE_ROW`, `REPEATED_HEADER_ROW`, `EMPTY_COLUMN_EXCLUDED` | INFO | Not data; reported with locators (X06 EXACT). |
| `DATA_WITHOUT_HEADER_COLUMN` | INFO | Kept with an empty header; the existing header-count gate routes it to governed review (X08). |
| `SHEET_HIDDEN`, `SHEET_TOO_LARGE`, `SHEET_PROTECTED`, `SHEET_EMPTY`, `NO_HEADER_ROW` | INFO (workbook note) | No table is produced from that content, so nothing can reach a preview from it. Reported with counts (X04, E09). |

**JSON is unchanged.** `BLOCKING`/`INFO` are the same sets (pinned by a test). JSON tables do not pass through the gate, and all 31 JSON scenarios are identical to Experiment C run1 in extraction digest, outcome, preview SHA, fidelity, review and reproducibility digest.

**No warning generated and ignored.**
- Every code the XLSX extractor or gate can emit is in `XLSX_WARNING_POLICY`. A static test scans `extract.py` and a runtime check runs on every cell, table warning and workbook note.
- An unknown code stops the run (tested).
- Every `HARD_WHEN_MAPPED` code on a mapped cell prevents the preview (tested end to end).

### 4.1 Rendering policies rechecked (Fix 4)

| Policy | Status | Evidence |
|---|---|---|
| Text preserved | Unchanged; verbatim, never trimmed or converted | X15, X31, unit test `test_locale_text…` |
| Money needs a declared fixed-decimal format | **Now enforced** at the gate (exactly 2 declared decimals) | X11, X12 (report-only, already blocked); X46 and X47 (newly blocked); unit test |
| Date-only cells become ISO dates | Unchanged | X22, X23 (dd/mm/yyyy display → `2026-08-31`), unit test |
| Datetimes have no offset, so timestamps must be text | Unchanged; now a hard block in any mapped field | X25, X52 |
| Formulas use cached values only; no cache means block | Unchanged; now a hard block in any mapped field | X27 EXACT, X28, X50 |
| Currency formatting does not change the value | Unchanged | X16 EXACT, unit test (`"£"#,##0.00` → `5.00`) |
| Locale text never converted | Unchanged | X15, E16, unit test (`1.234,56` stays) |
| Numeric IDs are not treated as text | **Now enforced** (gate) | X20, X38–X40 blocked; X21 and X54 text IDs EXACT |
| No automatic correction | Holds: the gate only refuses; display formats are never used to create characters | unit tests `test_display_format_never_invents_leading_zeros`, `test_x13_value_lost…` |

## 5. Before/after results

### X13, X20 and the scenarios named in the brief

| Scenario | Experiment C (run1) | C1 (run3 = run4) | Gate findings |
|---|---|---|---|
| X10 money numbers `#,##0.00` | EXACT ×3 | EXACT ×3 | none |
| **X13** precision | **SILENT_DIFFERENCE** | **GATE_BLOCKED** | PRECISION_EXCEEDS_15_DIGITS 1 (`Bank!E3`, raw `1.234567890123457e+16`); safe row `98765432109.99001` (13 digits) not flagged |
| **X20** numeric IDs | **SILENT_DIFFERENCE** | **GATE_BLOCKED** | NUMERIC_CELL_IN_TEXT_LIKE_COLUMN 448 (`CashBook!A2` text "1", raw "1", …) |
| X21 text IDs with zeros | EXACT | EXACT | none |
| X22 / X23 date cells | EXACT / EXACT | EXACT / EXACT | none |
| X25 datetime cells | BLOCKED | BLOCKED | DATETIME_NO_OFFSET 276 (report-only) |
| X27 / X28 formulas | EXACT / BLOCKED | EXACT / BLOCKED | X28: FORMULA_NO_CACHED_VALUE 2 (report-only) |
| X34 / X35 friendly headers (review) | REVIEW->EXACT | REVIEW->EXACT | none |
| X36 / X37 duplicate / unmapped | REVIEW->EXACT / REVIEW->HELD_OR_BLOCKED | unchanged | none |

Across all 54 original XLSX and adversarial scenarios, the only outcome changes from Experiment C are X13 and X20. The only preview SHA changes are the same two, which now have no preview. Every other EXACT preview is byte-identical to Experiment C. XLSX extraction digests changed for all 38 original XLSX scenarios, as expected: each numeric cell now carries its raw stored literal and the extractor id changed. The rendered text of every cell is the same.

**Counterfactual proof.**

The gate stopped a *real* silent difference in 6 tables: X13, X20, X39, X40, X44 and X51. In each, the in-memory preview without the gate would have been eligible and different from the truth.

In the other blocked tables the counterfactual happened to equal the truth (for example X42, X46, X50). There the gate refused a value whose correctness **cannot be established from the file**, which is the intended behaviour, not a false positive. For example, X50's formula result is unknown; it only "matches" because the truth is empty.

## 6. Full XLSX results

The table covers 38 original XLSX scenarios + 16 adversarial cases + 17 C1 scenarios.

How to read the last column:
- **E:** the gate evaluated the final mapping of an eligible pipeline result.
- **R:** report only; the existing workflow had already refused the file.

**Set totals:**

| Set | Scenarios | Verdicts | Outcomes | Silent differences | Provenance |
|---|---|---|---|---|---|
| Original XLSX | 38 | 38/38 PASS (45 evidence tables) | EXACT 24, REVIEW->EXACT 4, BLOCKED 12, REVIEW->HELD_OR_BLOCKED 2, RESUBMISSION 1, GATE_BLOCKED 2 | **0** (Experiment C: 2) | 45/45 |
| C1 | 17 | 17/17 PASS | GATE_BLOCKED 13, REVIEW->GATE_BLOCKED 1, EXACT 3 | 0 | 17/17 |
| Adversarial | 16 | 16/16 PASS | — | 0; 0 eligible | — |

| ID | Scenario | Exp. C | C1 | Gate |
|---|---|---|---|---|
| X01 | one sheet, one table (IN-10), canonical headers, text cells | EXACT | EXACT | E: - |
| X02 | 4 sheets named after categories (4 tables) | EXACT ×4 | EXACT ×4 | E: - |
| X03 | misleading sheet names | EXACT ×2 | EXACT ×2 | E: - |
| X04 | blank sheet + HIDDEN sheet + 'Notes' sheet + IN-x data | NOT_EVIDENCE_TABLE / EXACT | same | R: - / E: - |
| X05 | two tables in one sheet | EXACT ×2 | EXACT ×2 | E: - |
| X06 | title row + blank rows + header repeated every 50 rows | EXACT | EXACT | E: - |
| X07 | merged cells in data | BLOCKED | BLOCKED | R: MERGED_IN_DATA 2 |
| X08 | empty column + extra 'comment' column | REVIEW->EXACT | REVIEW->EXACT | E: - |
| X09 | missing column | RESUBMISSION | RESUBMISSION | R: - |
| X10 | money as numbers `#,##0.00` | EXACT ×3 | EXACT ×3 | E: - |
| X11 | money in GENERAL format | BLOCKED | BLOCKED | R: MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT 44 |
| X12 | money with `#,##0` | BLOCKED | BLOCKED | R: MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT 44 |
| X12b | float artefact 0.30000000000000004 | BLOCKED | BLOCKED | R: PRECISION_EXCEEDS_15_DIGITS 1 |
| **X13** | large values | **SILENT_DIFFERENCE** | **GATE_BLOCKED** | E: PRECISION_EXCEEDS_15_DIGITS 1 |
| X14 | negative amounts, parentheses format | EXACT | EXACT | E: - |
| X15 | text money '(12.50)', '£1,234.56', '1.234,56' … | BLOCKED | BLOCKED | R: - |
| X16 | currency number format | EXACT | EXACT | E: - |
| X17 | zero amounts | EXACT | EXACT | E: - |
| X18 | blank mandatory amount | BLOCKED | BLOCKED | R: - |
| X19 | debit/credit split columns | REVIEW->HELD_OR_BLOCKED | same | R: - |
| **X20** | leading-zero IDs as numbers | **SILENT_DIFFERENCE** | **GATE_BLOCKED** | E: NUMERIC_CELL_IN_TEXT_LIKE_COLUMN 448 |
| X21 | same IDs as text | EXACT | EXACT | E: - |
| X22 | date cells yyyy-mm-dd | EXACT | EXACT | E: - |
| X23 | date cells shown dd/mm/yyyy | EXACT | EXACT | E: - |
| X24 | text dates / ambiguous dates | BLOCKED | BLOCKED | R: - |
| X25 | timestamps as datetime cells | BLOCKED | BLOCKED | R: DATETIME_NO_OFFSET 276 |
| X26 | missing / invalid date | BLOCKED | BLOCKED | R: - |
| X27 | formulas with cached values | EXACT | EXACT | E: - |
| X28 | formulas without cached values | BLOCKED | BLOCKED | R: FORMULA_NO_CACHED_VALUE 2 |
| X29 | error cells in amount | BLOCKED | BLOCKED | R: CELL_ERROR 2 |
| X30 | hidden rows/columns + protected sheet | EXACT | EXACT | E: - |
| X31 | surrounding whitespace | BLOCKED | BLOCKED | R: - |
| X32 | header case/whitespace variations | EXACT | EXACT | E: - |
| X33 | approved alias | EXACT | EXACT | E: - |
| X34 | friendly non-financial headers | REVIEW->EXACT | REVIEW->EXACT | E: - |
| X35 | friendly financial headers | REVIEW->EXACT | REVIEW->EXACT | E: - |
| X36 | duplicate header | REVIEW->EXACT | REVIEW->EXACT | E: - |
| X37 | unmapped column | REVIEW->HELD_OR_BLOCKED | same | R: - |
| X38 | numeric IDs *without* leading zeros (1001) | — | GATE_BLOCKED | E: NUMERIC_CELL_IN_TEXT_LIKE_COLUMN 224 |
| X39 | X20 pattern via **human review** ('Entry no') | — | REVIEW->GATE_BLOCKED | E: NUMERIC_CELL_IN_TEXT_LIKE_COLUMN 224 |
| X40 | 18-digit numeric reference | — | GATE_BLOCKED | E: NUMERIC_CELL_IN_TEXT_LIKE_COLUMN 224, PRECISION_EXCEEDS_15_DIGITS 224 |
| X41 | 15 digits: 1234567890123.45, 999999999999999.00 | — | **EXACT** | E: - |
| X42 | 16 digits, decimal 12345678901234.56 | — | GATE_BLOCKED | E: PRECISION_EXCEEDS_15_DIGITS 1 |
| X43 | 16 digits, integer 1000000000000001.00 | — | GATE_BLOCKED | E: PRECISION_EXCEEDS_15_DIGITS 1 |
| X44 | 17 digits, 12345678901234567.00 (stored …568) | — | GATE_BLOCKED | E: PRECISION_EXCEEDS_15_DIGITS 1 |
| X45 | writer noise 2926.3299999999999, 98765432109.99001 | — | **EXACT** | E: - |
| X46 | GENERAL money, all values with 2 non-zero decimals | — | GATE_BLOCKED | E: MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT 44 |
| X47 | percent format on money | — | GATE_BLOCKED | E: MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT 1, PERCENT_FORMAT 1 |
| X48 | boolean in free-text field | — | GATE_BLOCKED | E: BOOLEAN_CELL_IN_NON_BOOLEAN_COLUMN 1 |
| X49 | `#N/A` in free-text field | — | GATE_BLOCKED | E: CELL_ERROR 1 |
| X50 | uncached formula in optional `close_date` | — | GATE_BLOCKED | E: FORMULA_NO_CACHED_VALUE 1 |
| X51 | merged cells in optional free-text field | — | GATE_BLOCKED | E: MERGED_IN_DATA 2 |
| X52 | datetime cell in free-text field | — | GATE_BLOCKED | E: DATETIME_NO_OFFSET 1 |
| X53 | time-only cell in free-text field | — | GATE_BLOCKED | E: TIME_ONLY_CELL 1 |
| X54 | control: text leading-zero IDs + `#,##0.00` money | — | **EXACT** | E: - |

The XLSX controls that must stay EXACT (X41, X45, X54, X21, X10) all remain EXACT, so the safeguards do not produce false blocks on safe data.

## 7. Adversarial results

16/16 PASS, identical outcomes to Experiment C.

| ID | Case | Result |
|---|---|---|
| E01, E03, E08 | corrupt ZIP, empty `.xlsx`, ZIP without `workbook.xml` | REFUSED (`WORKBOOK_UNREADABLE`, `EMPTY_FILE`, `NOT_AN_XLSX_WORKBOOK`) |
| E02, E04, E10–E14 | JSON cases | REFUSED as in Experiment C (JSON unchanged) |
| E05, E06, E07 | wrong extensions | detected by content; NOT_EVIDENCE_TABLE as before |
| E09 | extreme sheet dimension | `SHEET_TOO_LARGE` note (now classified INFO); NOT_EVIDENCE_TABLE |
| E15 | time / percent / boolean / General number in an amount column | BLOCKED by validation; the gate (report-only) independently finds BOOLEAN_CELL_IN_NON_BOOLEAN_COLUMN, MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT, PERCENT_FORMAT, TIME_ONLY_CELL |
| E16 | ambiguous '1,234' text | BLOCKED |

0 adversarial tables were eligible, and 0 had silent differences.

## 8. Regression

Evidence is in `regression_c1/` and `tests_c1/`.

| Check | Result |
|---|---|
| Per-phase suites 3B-0 … 3B-11, Phase 1, Phase 2 | all pass (17, 15, 41, 21, 35, 18, 43, 16, 14, 15, 23, 40, 117, 136, 34) |
| Full suite (`tests/`, includes Experiment A) | **620 passed** |
| Full suite without the UC-042 tree | 615 passed, 5 skipped (as before) |
| Experiment A (`tests/test_pdf_native_extraction.py`) | 35 passed |
| Experiment C + C1 unit tests (`experiments/realworld_formats/`) | **39 passed** (9 original + 30 new) |
| Registry | in sync: 19 definitions |
| Phase 1 baseline classification (CSV) | 445/445, 0 incorrect, unknown or ambiguous |
| Phase 2 variation corpus (CSV) | 161/161 |
| Production rules | aliases empty, layouts empty, 0 approved proposals, no policy roles (unchanged) |

The 30 C1 tests cover:
- the significant-digit boundary (13 values: 15/16/17 digits, decimal and integer, writer noise, zero);
- raw-literal preservation;
- no recovery of lost precision;
- numeric IDs blocked with field, locator, text and raw (4 ID sets, including IDs without zeros);
- the `0000000` display format inventing no zeros;
- text leading-zero IDs passing;
- unmapped numeric columns not gated;
- `declared_decimals`;
- the money format rule;
- locale text and dates;
- policy completeness (a static scan of emitted codes, and an unknown code raising);
- JSON sets unchanged;
- end-to-end: the pipeline is eligible but the gate refuses with no preview file anywhere; **review cannot bypass the gate**; a clean XLSX still produces exactly one EXACT preview.

## 9. Reproducibility

- run3 and run4 on the same inputs (102 scenarios: Experiment C's 85 + C1's 17) are **identical**. `differences: []` across the per-table reproducibility digest, which covers extraction warnings, route, decision, eligibility, failed checks, preview SHA, outcome, the full `xlsx_gate` record and review decisions. Extraction digests are identical too.
- Input files were re-hashed after both runs: **unchanged** for both `inputs/` and `inputs_c1/`.
- The original `inputs/` are byte-identical to the pre-C1 hashes taken before any change.
- JSON: every result field compared is identical to Experiment C run1. Compared fields: extraction digest, refusal, notes, outcome, preview SHA, bridged-CSV SHA, fidelity, review and reproducibility digest.
- Source hashes of the C1 experiment files: `tests_c1/c1_source.sha256`.

## 10. Limitations

1. **Precision lost before saving can go unnoticed.** If a user typed 16+ digits and Excel truncated them to a *plausible* 15-digit value (e.g. typed `1234567890123456.7`, stored `1234567890123450`), the file holds a valid 15-digit double. No rule can tell it from a genuine value. The gate detects only values whose stored double still needs more than 15 digits. It never claims to recover lost information, and it cannot prove that none was lost.
2. **The safe boundary is set by the rule, not proven.** The rule uses Excel's documented 15-digit precision applied to the shortest round-trip representation. Writer noise (`98765432109.99001`) collapses to the intended value and is correctly not flagged. A writer that stores a *different* 15-digit value than the user intended is outside what the file can reveal.
3. **Numeric IDs are refused, not repaired.** X38-style files, where the numeric ID has no zeros to lose, are refused too, because Excel cannot tell us what the text was. That is safe but strict. The remedy is a resubmission with text-formatted ID columns, not a conversion.
4. **The gate depends on the final mapping.** A column mapped to the wrong field type by a reviewer would be judged by that field's type. The existing review controls govern the mapping itself.
5. **The test fixtures are synthetic.** They were written by openpyxl plus direct XML edits. Workbooks from Excel, LibreOffice and Google Sheets, shared-formula variants, rich text, 1904 date systems, `.xlsm` and very large files were not exercised.
6. **The gate is an experiment-only wrapper around the existing workflow.** It lives in the bridge, not in the Smart Parser's handoff checks. The intake still stores the bridged CSV bytes, not the original XLSX (Experiment C §13 limitation unchanged).
7. **Proposals are simulated (TruthStub).** No live LLM was used (none permitted).

## 11. Protected integrity

| Protected item | Result |
|---|---|
| `smartparser/` package, `tests/`, `tools/` | 0 files newer than the Experiment C report; full suite unchanged at 620 |
| Existing CSV / PDF pipelines, 19-category registry, 14 canonical schemas, mapping/validation, evidence packages, review UI/API, reconciliation adapter | untouched: no code file outside `experiments/realworld_formats/` changed (the only other new file is this report in `docs/`, as for Experiment C); registry in sync; baseline 445/445; corpus 161/161 |
| Experiment A (`tests/test_pdf_native_extraction.py`, `smartparser/pdf_extraction`), Experiment A2 (`experiments/pdf_rule_generation/`), Experiment B (`experiments/multiformat/`) | 0 files changed; Experiment A 35/35 |
| Experiment C JSON results | identical to run1 |
| Experiment C original inputs | hash-identical |
| UC-042 authoritative source `p10/uc042_token_optimisation` | 107 code files + 624 datasets hash-identical; 0 newer files |
| Desktop Smart Parser | 63 files hash-identical |
| Clone E, original app, demo database, audit packs | not accessed |
| Integration, auto-accept, live LLM, reconciliation, submission, audit packs | none performed |

No stop condition was triggered:
- the source value was established from the raw XML in both cases;
- no safeguard guesses or reconstructs anything;
- CSV and PDF are unaffected;
- no change outside the experiment directory was needed;
- the gate reliably prevents the preview: 0 preview files for any blocked table, verified on disk.

## 12. Next-step recommendation

1. **Owner review of this report.** In particular, review the §4 hard/info decisions and the strictness of refusing *all* numeric cells in identifier and text fields (limitation 3).
2. If XLSX ingestion is pursued, the next step is a **design note**, not code. It would describe how the gate would move from the experiment bridge into the Smart Parser as an additional handoff check fed by extractor provenance, and how the original XLSX (not the bridged CSV) becomes the stored evidence. That touches the protected package and needs explicit approval.
3. Before any integration, test with **real workbooks** saved by Excel, LibreOffice and Google Sheets. Cover typed IDs, large balances, shared formulas, the 1904 date system and big files, and confirm the 15-digit rule against them.
4. Provide analyst guidance for the refusals: "format ID columns as Text and re-export"; "amounts above 15 significant digits cannot be submitted via XLSX, so use CSV or JSON".

Nothing beyond this report is planned until the owner decides.
