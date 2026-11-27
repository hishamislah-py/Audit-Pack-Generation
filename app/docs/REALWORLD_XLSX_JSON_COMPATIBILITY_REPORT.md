# Experiment C: Real-World XLSX and JSON Compatibility — Feasibility Report

| | |
|---|---|
| Date | 19 November 2026 |
| Status | **Experiment complete. Awaiting owner review. Nothing has been integrated.** |
| Experiment code | `experiments/realworld_formats/` (`extract.py`, `bridge.py`, `scenarios.py`, `run.py`, `test_realworld.py`); isolated; **no change** to the `smartparser` package, the tests, the CSV/PDF pipelines, the registry, the schemas, packages, review UI/API or the reconciliation adapter |
| Evidence | `Downloads\UC042_REALWORLD_XLSX_JSON_EXPERIMENT\`: `inputs\` (85 inputs + truth + SHA-256 manifest), `run1\`, `run2\` (full results), `summary.json`, `tests\` (Experiment C/A/B results), `regression\` (existing suite) |
| Proposer | `TruthStub`: a **SIMULATED LLM** (test implementation of the existing proposer interface, answering from the scenario's known mapping). **No live LLM call was made**; no result here describes live-model performance |
| Policy | shipped POC policy (**DISABLED**); no auto-accept; review resolved by a **simulated analyst** through the existing review functions with the test-only authority policy |

## 1. Executive summary

XLSX and JSON were tested independently on **85 scenarios**: 38 XLSX, 31 JSON and 16 adversarial. They were run twice from the same inputs and reproduced **identically**, with every input hash unchanged.

| | XLSX | JSON |
|---|---|---|
| Scenarios | 38 (45 evidence tables) | 31 (33 evidence tables) |
| Verdict vs expected safe outcome | **36 PASS + 2 FINDING** | **31 PASS** |
| Extraction success | 38/38 | 31/31 |
| Final outcomes | EXACT 24 · REVIEW→EXACT 4 · BLOCKED 12 · RESUBMISSION 1 · REVIEW→HELD 2 · **SILENT_DIFFERENCE 2** | EXACT 14 · REVIEW→EXACT 6 · BLOCKED 12 · REVIEW→HELD 1 · silent differences **0** |
| Previews equal to truth when eligible | 28/30 (2 findings) | 20/20 |
| Provenance complete (row, column, cell locators) | 45/45 | 33/33 |
| Adversarial (shared) | 16/16 failed visibly or were extracted by content, as expected | (same) |

**Main findings:**
1. **JSON is the safer format.** With literal-preserving parsing, every number keeps its exact source text. `250000.00` and `12345678901234567.89` survived exactly; the standard parser would turn the first into `250000.0` and lose precision on the second. Every unsafe producer variation was **blocked** by existing validation or **routed to review**:
   - floats `250000.0`, scientific notation, integers for money;
   - symbols and grouping, lower-case currency codes;
   - timestamps without an offset, epoch numbers, ambiguous dates;
   - nulls, absent keys;
   - nested keys, arrays, extra and conflicting keys.

   No changed value ever reached a valid preview.
2. **XLSX works structurally**: multiple sheets and multiple tables per sheet, titles, repeated headers, hidden rows and columns, protected sheets, merged cells, formulas with cached values, approved aliases. There are **two silent-difference findings** that the existing pipeline **accepts** today:
   - **X20 (leading zeros).** Numeric-looking identifiers typed as Excel numbers lose their leading zeros (`0000001` → `1`, `0042000001` → `42000001`). They still match the identifier pattern, so the file becomes **eligible with changed identifiers**.
   - **X13 (precision).** Money beyond Excel's 15 significant digits is changed (`12345678901234567.89` → `12345678901234570.00`) and still matches the money pattern.

   Both were flagged by the experiment's proposed **blocking warnings** (`NUMERIC_CELL_IN_TEXT_LIKE_COLUMN`, 448 cells; `PRECISION_EXCEEDS_15_DIGITS`). XLSX therefore needs those safeguards to be enforced before it is safe.
3. **Everything else unsafe was stopped:**
   - **XLSX:** native datetime cells lose the offset; General or zero-decimal formats; cells with an error; formulas without a cached value (never evaluated); parentheses, symbols and locale text; text dates; merged data cells; whitespace.
   - **Mechanism:** these were blocked by the existing validation and handoff checks 10/11, or (header problems) routed to review, refused at the gate, or held.
   - **Nothing was silently corrected.**
4. **Two defects in the experiment's own extractors were found and fixed during the work:**
   - JSON arrays kept as text re-serialised numbers as strings (`[1, 2]` → `["1", "2"]`), caught by the unit tests;
   - single-cell title rows were mis-labelled.

**Recommendation (§15):**
- **JSON:** suitable for a future controlled integration phase, restricted to flat or shallow record arrays.
- **XLSX:** suitable only with additional safeguards and restrictions; the two findings must become blocking.
- **Both** need more real-world producer evidence before any production use.

## 2. Experiment boundaries

- **Isolated code.** All code is in `experiments/realworld_formats/`, and all outputs are in the Downloads folder.
- **Untouched.** Experiments A (`smartparser/pdf_extraction/`) and B (`experiments/multiformat/`) are untouched; B was re-run and reproduced identically.
- **Synthetic data only.** All inputs were generated from the canonical UC-042 fixture tables (`PER-2026-09_set_01_clean_baseline`), so every value has a known truth.
- **No real producers.** No real bank or ERP exports were used: "real-world" means **realistic structures and producer behaviours reproduced synthetically** (§14).
- **Libraries.** `openpyxl` 3.1.5 (already installed) and the standard-library `json`. No new dependency.
- **Pipeline untouched.** Each extracted table is bridged to CSV and given to the **unchanged** `MappingOrchestrator` in fresh temporary stores, with a disposable store per table.
- **Nothing else was done:** no live LLM, no auto-accept, no package lifecycle, no submission, no audit pack, no OCR, no formula evaluation.
- **Other sessions.** Experiment A and another session's `docs/PDF_VALIDATION_RULE_GENERATION_FEASIBILITY_REPORT.md` exist in the working copy; they are not part of this work.

**How outcomes are measured (separately):**

| Measure | Meaning |
|---|---|
| Extraction | was the structure read (tables, rows, columns) without a refusal? |
| Value fidelity | extracted text vs the truth: exact text; money numeric equivalence (Decimal, no locale parsing); date/timestamp exact |
| Mapping | content classification by header; deterministic mapping; simulated proposals; review |
| Workflow | gate → mapping → validation → review (simulated analyst) → reprocess → **14 handoff checks** → canonical preview **byte-compared** with the truth |

**Outcome classes:**

| Class | Meaning |
|---|---|
| EXACT | eligible; preview byte-identical to the truth |
| BLOCKED | not eligible (the problem is caught, not corrected) |
| REVIEW→EXACT / REVIEW→HELD | human review succeeded / could not make it valid |
| RESUBMISSION | fewer columns than fields |
| **SILENT_DIFFERENCE** | eligible but the preview differs from the truth (the dangerous case) |

Each scenario declares its **expected safe outcome**; the verdict is PASS, FAIL or FINDING (an expected silent difference, documented as a risk).

## 3. XLSX test matrix and results

| ID | Scenario | Outcome | Key evidence |
|---|---|---|---|
| X01 | one sheet, one table, text cells | EXACT | |
| X02 | 4 sheets named after categories | EXACT ×4 | |
| X03 | **misleading** sheet names (sheet "IN-03" holds IN-10 data) | EXACT ×2 | content classification gave IN-10 and IN-07; **sheet names never used** |
| X04 | blank sheet, **hidden** sheet with IN-03 data, extra "Notes" sheet | EXACT | `SHEET_EMPTY`, `SHEET_HIDDEN: 'Old' … 1939 non-empty cells not extracted`; Notes tabulated and classified **unknown** (not evidence) |
| X05 | **two tables** in one sheet | EXACT ×2 | |
| X06 | title row, blank rows, header **repeated** every 50 rows | EXACT | `TITLE_ROW` note; 4 × `REPEATED_HEADER_ROW` (reported, not data) |
| X07 | **merged** data cells | BLOCKED | `MERGED_IN_DATA`; the hidden half is empty, so mandatory currency is missing |
| X08 | empty column + extra "comment" column (9 vs 8) | REVIEW→EXACT | `EMPTY_COLUMN_EXCLUDED`; header-count case; comment ignored with a reason |
| X09 | **missing** column (7 vs 8) | RESUBMISSION | gate, no LLM |
| X10 | money as numbers `#,##0.00` (IN-07, IN-03, IN-10) | EXACT ×3 | |
| X11 | money as numbers, **General** format | BLOCKED | `260019.5` vs `260019.50`; `NUMBER_NO_DECLARED_DECIMALS`; checks 10, 11 |
| X12 | **zero-decimal** format `#,##0` | BLOCKED | stored values emitted (never the rounded display); `334413` fails the pattern; `HIDDEN_PRECISION` |
| X12b | float artefact `0.30000000000000004` displayed `0.30` | BLOCKED | the exact stored value is emitted and fails; never rounded |
| X13 | large money: 13 digits (ok) and **12345678901234567.89** | **SILENT_DIFFERENCE (finding)** | `12345678901234570.00` accepted; `PRECISION_EXCEEDS_15_DIGITS` raised |
| X14 | **negative** signed amounts, format `#,##0.00;(#,##0.00)` | EXACT | stored value `-x.xx` emitted; `NEGATIVE_DISPLAYED_IN_PARENTHESES` (info) |
| X15 | **text** `(12.50)`, `£1,234.56`, `1.234,56`, `1,234.56`, `-0012.50` | BLOCKED | kept verbatim, **never converted**; `NUMBER_LIKE_TEXT_NON_CANONICAL` |
| X16 | currency number format `£#,##0.00` | EXACT | `CURRENCY_FORMAT` (info) |
| X17 | zero amounts | EXACT | |
| X18 | blank mandatory amount | BLOCKED | |
| X19 | **debit / credit** split columns (needs a derivation) | REVIEW→HELD | simulated proposer: UNMAPPABLE → `UNMAPPABLE_PROPOSAL` case → analyst cannot map → held; no derivation invented |
| X20 | **leading-zero IDs typed as numbers** | **SILENT_DIFFERENCE (finding)** | `0000001` → `1`, `0042000001` → `42000001` accepted; 448 × `NUMERIC_CELL_IN_TEXT_LIKE_COLUMN` |
| X21 | the same IDs as text cells | EXACT | |
| X22 | date cells `yyyy-mm-dd` | EXACT | |
| X23 | date cells displayed `dd/mm/yyyy` | EXACT | the stored date is used; the display format is irrelevant |
| X24 | text dates `31/08/2026`, **ambiguous** `03/04/2026` | BLOCKED | never interpreted; `DATE_LIKE_TEXT_NOT_ISO` |
| X25 | timestamps as **native datetime** cells | BLOCKED | `2026-08-31T17:00:00` (offset impossible), 276 × `DATETIME_NO_OFFSET`; check 11; **no offset invented** |
| X26 | missing date, invalid `2026-02-30` | BLOCKED | |
| X27 | formulas **with** cached results | EXACT | `FORMULA_CACHED_VALUE` |
| X28 | formulas **without** cached results | BLOCKED | `FORMULA_NO_CACHED_VALUE`; **never evaluated** |
| X29 | error cells `#DIV/0!`, `#N/A` | BLOCKED | `CELL_ERROR` |
| X30 | hidden rows and columns, **protected** sheet | EXACT | data kept; `HIDDEN_ROW`, `HIDDEN_COLUMN`, `SHEET_PROTECTED` |
| X31 | surrounding whitespace `' GBP'` | BLOCKED | never trimmed |
| X32 | header case/whitespace variations | EXACT | existing policy normalisation |
| X33 | **approved alias** (isolated store) | EXACT | deterministic via the alias |
| X34 | friendly non-financial headers | REVIEW→EXACT | 4 headers to the simulated proposer → proposal session → analyst → 14/14 |
| X35 | friendly **financial** headers `Value`, `Dr/Cr` | REVIEW→EXACT | sign-sensitive → review → 14/14 |
| X36 | **duplicate** header `amount` ×2 | REVIEW→EXACT | header-count case; second claimant ignored |
| X37 | unmapped `display_colour` | REVIEW→HELD | `UNMAPPABLE_PROPOSAL` case; required field uncovered |

**XLSX metrics:**

| Metric | Value |
|---|---|
| Extraction | 38/38 |
| Content classified by header | 37/45 (the rest are friendly, duplicate or extra headers, as for CSV) |
| Simulated proposals | 4 |
| Human review required | 6 |
| Handoff eligible at the end | 30 (28 exact + 2 findings) |
| Every reprocessed table ran **14** checks | yes |
| Provenance | `Sheet!row n`, `Sheet!col X`, cell `Sheet!E12` on every cell: 45/45 |

## 4. JSON test matrix and results

| ID | Scenario | Outcome | Key evidence |
|---|---|---|---|
| J01 | flat array, canonical keys, strings | EXACT | |
| J02 | one object, three record arrays | EXACT ×3 | |
| J03 | wrapped `{meta, data: {cash_book}}` | EXACT | `NON_TABULAR_VALUE` notes for meta |
| J04 | **nested** objects (`entry.id`, `money.amount`, …) | REVIEW→EXACT | dotted flattening; 7 paths → simulated proposer → session → 14/14 |
| J05 | **array inside** every record | REVIEW→EXACT | kept as JSON text (`NESTED_ARRAY`, blocking); extra column ignored |
| J06 | key **absent** in every 7th record | BLOCKED | `KEY_ABSENT`; absent ≠ null |
| J07 | additional key | REVIEW→EXACT | |
| J08 | empty array + empty object | EXACT | `EMPTY_ARRAY`, `EMPTY_OBJECT` notes |
| J09 | **null** in a mandatory field | BLOCKED | `NULL_VALUE` |
| J10 | **mixed** types for one key (same literal text) | EXACT | `MIXED_TYPES` (info) |
| J11 | inconsistent key **order** | EXACT | |
| J12 | **deep** nesting (5 levels) | REVIEW→HELD | beyond the flatten depth → JSON text (`DEEP_NESTING`) → unmappable → held |
| J13 | money as **integer** literals | BLOCKED | `250000` |
| J14 | money literals **with trailing zeros** | **EXACT** | `250000.00` preserved (stdlib default would give `250000.0`) |
| J15 | **12345678901234567.89** | **EXACT** | preserved exactly (no float) |
| J16 | negative signed literals | EXACT | |
| J17 | negative in an unsigned field | BLOCKED | |
| J18 | zero literals | EXACT | |
| J19 | null amount | BLOCKED | |
| J20 | string money `£260,019.50`, `1,234.56` | BLOCKED | never parsed |
| J21 | producer floats `250000.0` | BLOCKED | literal kept, fails the pattern |
| J22 | scientific `2.5000000E+5` | BLOCKED | `SCIENTIFIC_NOTATION` |
| J23 | lower-case currency `gbp` | BLOCKED | never normalised |
| J24 | ISO dates and offset timestamps | EXACT | |
| J25 | timestamps **without offset** | BLOCKED | check 11 |
| J26 | ambiguous `03/04/2026`, invalid `2026-02-30`, null date | BLOCKED | |
| J27 | **epoch** numbers for timestamps | BLOCKED | never converted |
| J28 | key case/whitespace variations | EXACT | |
| J29 | friendly camelCase keys | REVIEW→EXACT | |
| J30 | friendly **financial** keys `value`, `direction` | REVIEW→EXACT | |
| J31 | conflicting `amount` / `Amount` | REVIEW→EXACT | header-count case; duplicate ignored |

**JSON metrics:**

| Metric | Value |
|---|---|
| Extraction | 31/31 |
| Content classified by key set | 26/33 |
| Simulated proposals | 4 |
| Human review required | 7 |
| Handoff eligible at the end | 20 (**all exact**) |
| Every reprocessed table ran 14 checks | yes |
| Provenance | `$.path[i]`, `$.path[*].key`, cell `$.path[i].key` on every cell: 33/33 |

## 5. Financial value fidelity analysis

**Exact text vs numeric equivalence.**
- UC-042 validation needs the **exact text** (`^\d+\.\d{2}$`, `^-?\d+\.\d{2}$`), so numeric equivalence is not enough.
- Across all money cells compared with the truth:
  - XLSX: exact 7,393 / 7,414, numerically equal 7,403 / 7,414;
  - JSON: exact 6,379 / 6,856, numerically equal 6,633 / 6,856.
- These totals **include the deliberately changed sources** (General formats, producer floats, integers, symbols). The safety question is answered per scenario: **every cell whose text differed went to BLOCKED or review, except in X13 and X20.**

| Behaviour | XLSX | JSON |
|---|---|---|
| Exact two-decimal money | ✔ when the cell's own format declares the decimals (`0.00`, `#,##0.00`, `£#,##0.00`) or the value is text | ✔ when the producer writes `250000.00` or a string |
| Missing decimals | General / `#,##0` formats give `250000` → BLOCKED | integer literals → BLOCKED |
| Float artefacts | stored 17-digit value emitted → BLOCKED | producer floats `250000.0` → BLOCKED |
| Large values | **> 15 significant digits → changed by Excel's storage → accepted today (X13)** | literal preserved exactly (J15) |
| Negative values | stored sign used; parentheses display flagged only | literal |
| Parentheses / symbols / grouping / locale (text) | kept, BLOCKED | kept, BLOCKED |
| Debit/credit split columns | review → held (no derivation) | (not tested separately; same mapping path) |
| Numeric-looking identifiers | **typed numbers lose leading zeros → accepted today (X20)**; text cells exact | strings exact (numbers would be literal) |
| Zero / blank / null | zero exact; blank/null → BLOCKED | same |

**No value was ever corrected:**
- no rounding, locale parsing or symbol stripping;
- no derivation of `amount` / `dc` from debit and credit columns;
- the stored value is always preferred to the display.

## 6. Date and timestamp analysis

- **XLSX date cells:** exact (ISO from the stored date; the display format, e.g. `dd/mm/yyyy`, is irrelevant).
- **XLSX datetime cells:** **cannot carry a UTC offset**. Every UC-042 timestamp (14 fields, all requiring an offset) typed as a datetime fails, and is blocked by validation check 11 (276/276 cells flagged `DATETIME_NO_OFFSET`). Timestamps are only safe as **text** cells.
- **Text dates** (`31/08/2026`, ambiguous `03/04/2026`, invalid `2026-02-30`) and **JSON** non-ISO dates, epoch numbers and offset-less timestamps: kept verbatim and BLOCKED. **No interpretation, no invented offset.**
- **JSON ISO dates and offset timestamps:** exact.

## 7. Mapping and validation results

- **Classification by content.** Content classification by header or key set worked whenever the headers were canonical or policy variants: XLSX 37/45, JSON 26/33. **Sheet names and JSON keys were never used** to choose a category (X03).
- **Mapping.** The existing deterministic mapping, policy normalisation, approved aliases (X33), header-count gate, duplicate detection, UNMAPPABLE routing and proposal validation behaved exactly as for CSV.
  - Friendly or nested headers went to the simulated proposer, which sends headers only.
  - Under the shipped DISABLED policy they then went to review; financially sensitive mappings are always review.
- **Validation.** Every value problem except X13/X20 failed handoff check 10 (normalisation/validation) and/or 11 (content check).
- **No new canonical fields** were created; unmappable columns stayed unmapped (X19, X37, J12).

## 8. Human-review and handoff results

**Review volume:** 13 tables needed review (6 XLSX, 7 JSON). The simulated analyst resolved them through the existing functions:
- **10 became EXACT** after review. The route was either a proposal session (`complete_session`) or a column-review case (`complete_case`). In both cases the file mapping was governed, reprocessing was deterministic with **0 provider calls**, **14/14 checks** passed, and the preview equalled the truth.
- **3 were correctly HELD** (X19 debit/credit, X37 unmapped, J12 deep nesting): a required field stayed uncovered.

**Rule refusals:** no review decision was refused.

**Eligibility:** 50 tables eligible in total (30 XLSX, 20 JSON), 48 of them byte-identical to the truth. The other 2 are the XLSX findings.

## 9. Intermediate representation assessment

The Experiment B IR was extended (`extract.py`):

| Element | Captured |
|---|---|
| Upload identity, size, **SHA-256** of the original | yes (`Upload`) |
| Extractor name + version, rendering policy | yes (`xlsx-extractor/0.1-experiment-C`, `xlsx-strict-faithful/1`; `json-extractor/0.1-experiment-C`, `json-literal-preserving/1`) |
| Table identity | yes (`Sheet!A1:H225`, `$.data.cash_book`) |
| Headers, rows, **original cell text** | yes |
| Original value / literal, **cell type**, **number format** | yes, on every cell |
| Row, column and **cell** locators | yes (100%) |
| Warnings (cell / table / file), blocking vs info | yes |
| Missing vs null vs empty | yes (`absent` / `null` / `empty` types) |
| Unmapped values | kept in the table (never dropped); unmapped columns flow into review |

**Sufficient for deterministic reprocessing?** The runs show it: re-extracting the same original gives the identical IR digest, bridged CSV, preview and validation outcome (§10).

What is **not** proven: the bridge stores the **bridged CSV** as the Smart Parser intake, so the existing reprocessing re-reads that CSV, not the original workbook or JSON. An integration must store the original and re-extract with the recorded extractor version (§13).

## 10. Reproducibility results

| Check | Result |
|---|---|
| Two complete runs (`run1`, `run2`) from the same 85 stored inputs | **identical**: extraction digests, bridged CSV SHA-256, outcomes, preview SHA-256, review decisions |
| Input files before and after both runs | **unchanged** (SHA-256 manifest) |
| Inputs | generated once (openpyxl writes timestamps into workbooks, so regeneration produces different bytes; therefore runs never regenerate) |

## 11. Full regression results

| Suite | Result | Evidence |
|---|---|---|
| **Experiment C unit tests** (`experiments/realworld_formats/test_realworld.py`, run separately) | **9 passed** (1 failed first and found the nested-array defect, now fixed) | `tests/experiment_C_tests.txt` |
| **Existing Smart Parser suite** | **620 passed**; without the UC-042 tree 615 passed, 5 skipped; per phase 3B-0 … 3B-11 all pass | `regression/regression_summary.txt`, `regression/test_run_full.txt` |
| **Experiment A tests** (`tests/test_pdf_native_extraction.py`, another session's work, run separately) | **35 passed** | `tests/experiment_A_tests.txt` |
| **Experiment B artefacts** (re-run into a temporary folder, compared with the stored results) | **identical outcomes**, 19/19 scenarios | `tests/experiment_B_reproduction.txt` |
| Registry / baseline / corpus | in sync (19) / 445/445 / 161/161 | regression summary |
| Protected trees | UC-042 107 code + 624 dataset files and Desktop 63 files hash-identical; 0 UC-042 files newer | regression summary |

## 12. Unsupported cases (by design or untested)

| Case | Status |
|---|---|
| Legacy `.xls` / OLE2, password-encrypted workbooks | refused (`UNSUPPORTED`); encrypted files not generated |
| `.xlsm` macros, `.ods`, external links, pivot tables, charts | not tested |
| Formula evaluation | deliberately not done; formulas without a cached value are blocking |
| Timestamps with offsets as Excel datetime cells | impossible in Excel; text only |
| Derivations (debit/credit → amount + dc; split date/time) | not supported; review → held |
| Locale or currency-formatted **text** money | not parsed; blocked |
| JSON nesting deeper than 4 levels, arrays of sub-records (exploding rows) | kept as JSON text, blocking; not tabulated |
| JSON Lines (NDJSON), streaming / very large JSON | not tested |
| JSON keys containing `.` | warned (`KEY_CONTAINS_DOT`); ambiguous with the dotted convention |
| Multiple header rows, subtotal rows, side-by-side tables in one sheet row band | not tested |
| Encodings other than UTF-8 (UTF-16, Latin-1) | refused |

## 13. Architectural changes required for eventual integration (proposed only)

1. **Identify XLSX and JSON by content.** Today the existing Smart Parser routes XLSX to the unimplemented ZIP path, so XLSX renamed to `.csv` is refused visibly. JSON is read as CSV and left unclassified (`unknown_category`), so JSON renamed to `.csv` is never accepted wrongly, but it isn't processed either.
2. **An extraction stage** with versioned extractors and **declared rendering policies**, producing the IR (§9).
3. **Store the original upload** as the immutable intake. The bridged table becomes a derived, reproducible artefact; reprocessing and handoff check 12 re-extract with the recorded extractor version.
4. **Identity per extracted table:** `(intake, SHA-256, table locator, extractor version)` for workbooks and JSON documents carrying several evidence tables (X02, X05, J02).
5. **Blocking extraction warnings must stop handoff.** For example, a replacement for CSV-specific check 14:
   - `FORMULA_NO_CACHED_VALUE`, `CELL_ERROR`, `DATETIME_NO_OFFSET`, `MERGED_IN_DATA`;
   - **`PRECISION_EXCEEDS_15_DIGITS`** and **`NUMERIC_CELL_IN_TEXT_LIKE_COLUMN`** (the two findings);
   - `NESTED_ARRAY`, `DEEP_NESTING`, `DATA_WITHOUT_HEADER_COLUMN`, `PERCENT_FORMAT`, `TIME_ONLY_CELL`, `DUPLICATE_KEYS`.

   The numeric-cell rule needs the **mapped** field type, so it runs after mapping (as the experiment's bridge does).
6. **Provenance locators** at cell level in records, sidecars and audit (`Sheet!E12`, `$.cash_book[3].amount`), plus the extractor and policy in the sidecar.
7. **No change needed** to the 19 categories, schemas, mapping, proposals, review, packages or the UC-042 engine; previews stay canonical CSV.

## 14. Risks and limitations

- **Synthetic, not real exports.** Producer behaviours were *reproduced*, not observed. Real ERP or bank exports may add multi-row headers, subtotals, footnotes, report layouts, locale-specific defaults and very large files. **No claim is made for producers that were not tested.**
- **Simulated proposer and analyst.** Mapping-quality numbers for friendly or nested headers reflect the known truth, not a live model; live behaviour was measured only for CSV headers in 3B-10.
- **XLSX findings X13/X20 are accepted by the existing pipeline today.** Only the experiment's *proposed* blocking warnings catch them. Until those are enforced, XLSX can produce eligible previews with **changed identifiers or large amounts**.
- **Free-text fields** (`payment_reference` etc.) have no deterministic value rule (3B-11 correction). Format conversions that change such text would not be caught by validation.
- **Generation by openpyxl.** openpyxl itself rounds floats on write; the 17-digit artefact (X12b) had to be written into the sheet XML directly. Other generators may behave differently.
- **Cost:** none incurred (no live calls). Performance with very large workbooks was tested only for the dimension guard.

## 15. Recommendation for each format (independently)

### JSON — **suitable for a future controlled integration phase**, with restrictions

**Evidence:**
- 31/31 safe outcomes, 0 silent differences, 20/20 eligible previews exact;
- exact literal preservation, including values beyond float precision;
- duplicate keys, NaN, bad encodings and excessive nesting refused visibly;
- every producer variant that changes money or date text blocked by the existing validation.

**Restrictions for the first phase:**
- UTF-8 only;
- record arrays (top level, or at most 2 levels deep) with flat or shallowly nested objects;
- nested arrays and deep objects remain blocking or reviewed;
- literal-preserving parsing and duplicate-key detection are mandatory.

**Also needed:** more real-world producer evidence before production use.

### XLSX — **suitable only with additional safeguards or restrictions**

**Evidence:**
- structurally robust (38/38 extracted; all layout features handled or reported);
- 28/30 eligible previews exact;
- every formula, error, date, format and text problem blocked or reviewed.

**But 2 silent differences** (X13 large values, X20 leading-zero identifiers) pass the existing pipeline.

**Required before integration:**
- enforce `PRECISION_EXCEEDS_15_DIGITS` and `NUMERIC_CELL_IN_TEXT_LIKE_COLUMN` (and the other blocking warnings) as hard stops;
- timestamps accepted only as text cells;
- money only from numeric cells with a declared fixed-decimal format, or from text;
- original-file storage with re-extraction;
- **more real-world export evidence** (actual bank/ERP workbooks) before any production use.

### Both

**Not to be integrated now.** This report stops here, and integration waits for explicit owner approval.

**Decisions needed:**
1. Approve JSON (restricted) for a controlled integration phase.
2. Approve XLSX only with the safeguards above.
3. Provide or authorise real (anonymised) producer exports for a further evidence round.
4. Should the blocking-warning list (§13.5) become the integration contract?
