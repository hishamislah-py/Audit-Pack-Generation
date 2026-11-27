# Experiment B: Multi-format Evidence Ingestion and Canonical Mapping — Feasibility Report

| | |
|---|---|
| Date | 19 November 2026 |
| Working copy | `C:\Users\artlptp263user\p10\smartparser_phase1` (experiment code only, in `experiments/multiformat/`; **the `smartparser` package was not changed**) |
| Authoritative UC-042 source | read-only; not used except through the already-generated registry and fixtures |
| Evidence | `Downloads\UC042_MULTI_FORMAT_EXPERIMENT\`: `inputs\` (19 synthetic input files), `results.json` (every measurement), `regression\` (full regression after the experiment) |
| Status | **Experiment complete; awaiting review.** No production implementation has been started. |

## 1. Summary

**Feasible, and cheaper than it looks, because the existing pipeline can be reused almost unchanged.**

**Tabular formats (XLSX, JSON record arrays, DOCX tables, Markdown tables).**
- Each format needs only a **format-specific extractor** that produces a small common intermediate representation (IR): a header, rows of cell *text*, and a source locator per row and per column.
- Bridged to CSV, that IR went through the **unchanged** orchestrator. Classification, controlled mapping, LLM-proposal eligibility, validation, human-review routing, reprocessing, the 14 handoff checks and the canonical preview all worked as they do for CSV.
- **20 of 20 expected tables were extracted**, with every data row (100%) and a complete source locator for every row and column.

**Document formats (DOCX, Markdown, TXT versions of IN-15 to IN-19).**
- The extracted text was given to the **existing PDF label classifier, unchanged**.
- **5 of 5** documents were classified correctly: the letters resolved through the IN-02 inventory, the IN-17 policy version was recognised, and unstructured prose was correctly *not* classified.

**The real risk is cell rendering, not structure.**

| Format feature | Finding |
|---|---|
| Typed Excel cells read naively, or JSON numbers as producers write them (`250000.0`) | They changed money and date **text** (`250000.0`, `2026-08-31 00:00:00`). **Numeric values were never wrong** (Decimal-equal 100% everywhere). Every such file was **blocked by the existing validation** (checks 10/11), never silently accepted or "fixed" |
| Excel cannot store a UTC offset | So UC-042 timestamps (`…+01:00`) survive only as text cells |

**Recommendation:**
1. Support **XLSX first** (highest business value; clear rendering rules needed).
2. Then **JSON flat record arrays** (easy).
3. **Markdown/DOCX tables** are trivial extensions but low value.
4. **DOCX/TXT/MD document classification** is easy but needs a policy decision on evidential value.
5. **Defer** unstructured documents and deep or nested JSON beyond simple flattening.

The architecture changes actually needed are few, but structural (§8): file identity per **extracted table** (one upload → several evidence tables), re-extraction during deterministic reprocessing, and generalised source locators in provenance.

## 2. Phase 1 — Architecture discovery (from the code)

| # | Item | Finding |
|---|---|---|
| 1 | Intake and classification flow | `SmartParser.process_bytes` → `EvidenceStore.save` (content-addressed original, intake ID, SHA-256) → `identify.detect.identify` (magic bytes / extension, **content wins**) → CSV: `csv_engine.read_csv` → `classify_csv` (exact header / controlled mapping) or a supplied category (3B-0 check); PDF: `pdf_engine.extract_pdf` → `classify_pdf` (labels); ZIP: *not implemented*. Orchestration (`MappingOrchestrator`) adds the 3B-7 header-count gate, proposals, policy and review |
| 2 | Registry | 19 categories (generated from UC-042 `schema.py`): **14 CSV + 5 PDF**; requirement REQUIRED for 17, OPTIONAL for IN-18/IN-19 |
| 3 | CSV schemas | **14 schemas, 153 canonical columns**. Types: id 39, str 23, enum 20, date 15, ts 14, **signed 14, amount 12** (26 money columns), ccy 13, bool 2, int 1. Every column is header-required |
| 4 | Format boundaries | `FileFormat` = CSV / PDF / ZIP / UNKNOWN. **XLSX and DOCX start with the ZIP signature, so `identify` routes them to the unimplemented ZIP path.** `.txt` is mapped to CSV by extension (content still decides). JSON / Markdown have no route |
| 5 | Canonical representation from CSV | `CsvTable` (raw headers, rows of cell **strings**, source line numbers) → `controlled_map` → `MappingResult` → `Record`s (`original` cells keyed by `column_keys`, normalised values, `source_line`) → canonical preview (cells unchanged, canonical order) + provenance sidecar |
| 6 | Mapping / validation / review | `controlled_map` (canonical, case/whitespace policy, approved aliases, governed file/layout rules); `ProposalGateway` + validator (eligible unresolved headers only, no values sent); `policy.decide`; `review.intake` column-review cases, `review.session` proposal sessions; `handoff.reprocess` + 14-point `check_handoff` |
| 7 | Packages / versions | `PackageService`: one upload = one intake = one version of **one** category slot; snapshots, manifests (3B-9/3B-10) |
| 8 | Provenance / audit | intake SHA-256; per record `source_line` / `row_number`; preview sidecar (source index, header, rule, line); hash-chained `AuditLog` |

**Where a new format can enter without duplicating downstream logic:** between intake/identification and the CSV reader. A format extractor turns the original bytes into one or more IR tables; each table then follows the **existing** CSV path from `CsvTable` onwards. Document-type evidence follows the existing label path from "text" onwards (`classify_pdf` takes a `PdfExtraction`, which is just page texts).

## 3. Phase 2 — Candidate formats

| Format | Library (already installed, no new dependency) | Extraction complexity | Main limitations | Reuses the canonical mapping workflow? |
|---|---|---|---|---|
| **XLSX** | `openpyxl 3.1.5` (pure Python; `data_only=True` reads cached formula values, never evaluates) | **Medium**: cell typing, number formats, dates as numbers, header-row detection, merged cells, hidden sheets, several sheets | Excel has **no date type and no time zone** (timestamps with offsets only as text); a number's text depends on its format; formulas need a cached value; `.xls` (OLE2) not covered | **Yes**: one IR table per sheet → CSV path |
| **JSON** | stdlib `json` with `parse_float=str, parse_int=str` (number **literals kept verbatim**) | **Low** (flat arrays) to **medium** (nesting) | producers write money as binary floats (`250000.0`); nested objects need a flattening rule; arrays inside records; keys missing in some records | **Yes**: one IR table per record array |
| **DOCX** | `python-docx 1.2.0` | **Low** for tables; **medium/high** for free prose | merged cells repeat in python-docx; multi-line cells; no page numbers (Word paginates at render time); prose has no structure | Tables **yes**; documents → the existing label classifier |
| **TXT / Markdown** | stdlib (pipe-table and `Label: value` parsing) | **Low** | only pipe tables and `Label: value` lines; fixed-width text and prose not handled | Tables **yes**; documents → label classifier |

## 4. Phase 3 — Controlled experiment

**Method** (`experiments/multiformat/run_experiment.py`; extractors in `experiments/multiformat/extractors.py`):
1. **Generate** 19 synthetic inputs from the canonical UC-042 fixture tables (`PER-2026-09_set_01_clean_baseline`), so every value has a known truth.
2. **Extract** each one into the IR: `ExtractedTable` (header, cell text, row locators such as `CashBook!row 5`, `$[3]`, `table[0] row 2`, `line 12`, and column locators), or `ExtractedDocument` (text, headings, key-values). Nothing is dropped silently: skipped rows/columns, merged cells and absent keys are reported as warnings.
3. **Bridge** each table to CSV bytes (UTF-8, comma, LF) plus a provenance map (CSV line → source row; CSV column → source column).
4. **Process** each table through the unchanged `MappingOrchestrator` twice: without a category (content classification) and with the analyst's slot category. Fresh isolated stores are used per table.
   - The proposer is `TruthStub`, a **test implementation** of the existing proposer interface that answers from the generator's known mapping. It is a **SIMULATED LLM**: no network, no live calls.
   - The POC policy is the **shipped DISABLED** policy, so any proposal ends in human review.
5. **Documents** go to the unchanged `classify_pdf` as text, with the IN-02 inventory for the letters.
6. **Measure** separately:
   - extraction (tables found, rows, columns);
   - value fidelity against truth (all cells; money text exact; money value Decimal-equal; dates and timestamps);
   - mapping (deterministic coverage, route);
   - validation and handoff eligibility, and whether the preview equals the canonical file;
   - provenance completeness;
   - review requirement.

**Results (`results.json`):**

| ID | Format | Input characteristics | Extraction | Mapping / route | Value fidelity (cells; money text) | Eligible / outcome |
|---|---|---|---|---|---|---|
| X1 | XLSX | 3 sheets (IN-10, IN-03, IN-11), canonical headers, **text** cells | 3/3 tables, all rows | content-identified; **deterministic 8/8, 7/7, 13/13** | 100%; 100% | **eligible ×3**, preview = canonical |
| X2 | XLSX | **typed** cells (money numbers `#,##0.00`, date cells, datetime cells), **naive** `str(value)` | 2/2 | deterministic 8/8, 7/7 | 86% / 69%; money text 199/224 and 227/276 (`250000.0`); dates `2026-08-31 00:00:00`; **Decimal-equal 100%** | **blocked** (checks 10, 11) |
| X3 | XLSX | typed cells, **format-aware** rendering (number format; date-only format → ISO date) | 2/2 | deterministic | money 100%, dates 100%; **timestamps 0%** (`…T17:00:00`, offset lost: Excel stores none) | **blocked** (check 11); 224 + 276 offset warnings reported |
| X4 | XLSX | typed money/dates, timestamps exported as **text** | 2/2 | deterministic | **100%; 100%** | **eligible ×2**, preview = canonical |
| X5 | XLSX | merged title row + blank row above the header, whitespace-only trailing rows, extra "Notes" sheet | 1/1 evidence table (+ Notes reported, not mapped) | deterministic | 100% | **eligible**; warnings: title row, merged range, 5 skipped rows |
| X6 | XLSX | friendly labels (`Ledger entry ID`, `Debit/Credit`, …), same count | 1/1 | not content-identified; deterministic 2/8 (`Amount`, `Currency` by case policy); **6 headers sent to the proposer** (headers only) | 100% | **HUMAN_REVIEW** (proposal session; shipped policy; `Debit/Credit` is sign-sensitive anyway) |
| J1 | JSON | flat records, canonical keys, string values | 1/1 | deterministic 8/8 | 100% | **eligible**, preview = canonical |
| J2 | JSON | producer-style numbers (`250000.0`, `2926.33`) | 1/1 | deterministic | money text 199/224 (`250000.0`); Decimal-equal 100% | **blocked** (checks 10, 11) |
| J3 | JSON | **nested** objects (`entry.id`, `money.amount`, `money.dc`, …), same count | 1/1 (dotted keys) | deterministic 0/8 → **8 headers to the proposer** | 100% | **HUMAN_REVIEW** (proposal session) |
| J4 | JSON | key missing in every 5th record + an extra key | 1/1, 9 columns; 45 absent values reported | **header-count gate** (9 vs 8) | missing values empty (reported) | **HUMAN_REVIEW** (header-count case; no LLM) |
| J5 | JSON | one object, two record arrays (IN-10, IN-03) | 2/2 | deterministic | 100% | **eligible ×2** |
| D1 | DOCX | heading + one table (IN-07) | 1/1 | deterministic 7/7 | 100% | **eligible**, preview = canonical |
| D2 | DOCX | IN-07 table with a deliberate multi-line cell | 1/1, warning | deterministic | the cell kept **exactly as in the source** (line break included) | **eligible**: the preview equals the *source* (which differs from the fixture by design). `bank_statement_ref` is free text, so no validation rule objects |
| D3 | DOCX | IN-15 acknowledgement letter as paragraphs | 1 document | `classify_pdf` unchanged | 6/6 labels | **IN-15 correct** (letter resolved via IN-02) |
| D4 | DOCX | IN-17 policy as paragraphs | 1 document | `classify_pdf` | 7/7 labels | **IN-17 correct**, policy v1.2 recognised (markings present) |
| M1 | Markdown | pipe table (IN-07) | 1/1 | deterministic 7/7 | 100% | **eligible**, preview = canonical |
| M2 | Markdown | IN-16 letter, `**Label:** value` bullets | 1 document | `classify_pdf` | 6/6 labels | **IN-16 correct** |
| T1 | TXT | IN-19 receipt, `Label: value` lines | 1 document | `classify_pdf` | 5/5 labels | **IN-19 correct** |
| T2 | TXT | the same facts as prose, no labels or table | 1 document, 0 key-values | `classify_pdf` | — | correctly **not classified** (no inference) |

**Extraction defect found and fixed during the experiment** (it informs the rules a real XLSX extractor needs):
- The first format-aware renderer printed date cells as `2026-08-31T00:00:00`, because openpyxl returns every date cell as a `datetime`.
- Fix: a cell whose number format has no time component is a **date**.
- After the fix, X3/X4 dates are 100% exact. The numbers above are from the final run.

## 5. Phase 4 — Comparative evaluation

| Criterion | XLSX | JSON | DOCX | TXT / Markdown |
|---|---|---|---|---|
| **Extraction success** (structure found) | 11/11 evidence tables, 100% rows; extra sheet reported | 6/6 tables, 100% rows; absent keys reported | 2/2 tables; 2/2 documents | 1/1 table; 3/3 documents (incl. the prose) |
| **Mapping success** (canonical fields resolved) | canonical headers: 100% deterministic, content-identified; friendly labels: 2/8 deterministic → proposal → review | canonical keys: 100%; nested: 0/8 → proposal → review; extra key → header-count review | 100% deterministic (canonical headers) | 100% deterministic |
| **Canonical field coverage** (eligible files) | 8/8, 7/7, 13/13 (text or typed-with-text-timestamps) | 8/8, 7/7 | 7/7 | 7/7 |
| **Data type preservation** | text cells exact. Typed: depends on the renderer — format-aware keeps money and dates; **timestamps with offsets impossible as typed cells** | literal number text kept exactly; **producer floats change money text** | exact (text) | exact (text) |
| **Financial value accuracy** | numeric value 100% in every run; money **text** 100% with format-aware rendering, 82–89% naive (caught) | value 100%; text 89% with producer floats (caught) | 100% | 100% |
| **Provenance completeness** | 100%: `Sheet!row n` + `Sheet!col X` | 100%: JSON path per record and key | tables 100% (`table[t] row r col c`); documents: document-level only (no pages in DOCX) | 100%: `line n`; documents document-level |
| **Human review requirement** | only for unfamiliar labels (as CSV) | for nested keys, inconsistent records (as CSV) | none for canonical tables | none for canonical tables |
| **Implementation complexity** | **medium** (rendering policy, multi-sheet identity, merged and hidden sheets) | **low** (flat) / **medium** (nested) | **low** (tables) | **low** |
| **Reuse of existing components** | everything after extraction | everything after extraction | tables: everything after extraction; documents: the label classifier unchanged | same as DOCX |

Extraction success and mapping success are different things. Every format extracted completely, while mapping success depended only on the *header vocabulary* (canonical, friendly, nested), exactly as for CSV today. And every fidelity problem was a **rendering** problem that the existing validation caught.

## 6. Safety properties observed

- **No new canonical fields.** Unfamiliar keys and labels went to the existing proposal or review path; the registry was untouched.
- **No silent data loss:**
  - title rows, merged ranges and skipped empty rows were reported;
  - the non-evidence "Notes" sheet was reported, not mapped;
  - absent JSON keys were reported and left as empty cells, which the existing rules then judge;
  - JSON arrays inside records would be kept as JSON text and reported (none occurred in the test data).
- **No bypass.** Every table went through the same gate, deterministic mapping, proposal eligibility, validation, review and 14 handoff checks. Nothing format-specific decided a category or accepted a mapping.
- **No auto-accept, no live LLM, no submission.** The shipped DISABLED policy and a simulated, labelled proposer were used.
- **Value changes are blocked, not repaired.** The extractor never rewrote `250000.0` to `250000.00`: the validator rejected it. Format-aware Excel rendering uses the cell's **own declared** number format, which is a legitimate reading of the source, not a correction.

## 7. Phase 5 — Implementation recommendation

| Priority | Format | Why |
|---|---|---|
| **1 — support first** | **XLSX** (single and multi-sheet, `.xlsx` only) | Most likely real-world evidence format; structure extraction proven; needs explicit rendering rules (text cells as-is; numbers by their own fixed-decimal format; date-only format → ISO date; **datetime cells refused or flagged when the field needs an offset**; formulas → cached value only, flagged when missing) |
| **2 — easy extension** | **JSON record arrays** (flat; one level of object flattening) | Literal-number parsing keeps exact text; nested keys work through the existing proposal/review path |
| **3 — easy but low value** | Markdown pipe tables, DOCX tables | Trivial extractors; financial evidence rarely arrives this way |
| **4 — easy technically, needs a policy decision** | DOCX / TXT / MD versions of **document** evidence (IN-15 … IN-19) | The existing label classifier works on their text unchanged. Whether an editable letter is acceptable evidence where UC-042 expects a PDF is a **business/control decision**, not a technical one. Field extraction for these would align with Experiment A |
| **5 — needs document understanding** | DOCX/TXT prose, irregular tables, fixed-width text, deep JSON with arrays of sub-records | Requires inference (layout or LLM extraction of values), which Smart Parser deliberately does not do for values |
| **Defer** | legacy `.xls` (OLE2), `.ods`, password-protected or macro workbooks, images in documents (no OCR) | — |

**Is a common IR sufficient?**
- **For tables: yes.** Header + cell text + row/column locators carried every experiment through the unchanged pipeline.
- **For documents: yes for classification** (text + key-values). Field extraction is a separate capability (see Experiment A for PDFs).
- One addition is needed: **the IR must carry the extractor name and version and the rendering policy**, so that reprocessing is reproducible.

## 8. Architectural changes actually necessary (proposed, not implemented)

1. **Identification.** Recognise XLSX/DOCX inside the ZIP signature (`[Content_Types].xml` / part names) and JSON/Markdown by content; add `FileFormat` values. Today they fall into the unimplemented ZIP path or the CSV reader.
2. **Extraction stage.** A registry of format extractors (`bytes → IR tables + documents`) between identification and the existing CSV/label paths. The CSV reader stays the reference implementation; a CSV upload is just a single-table IR.
3. **Identity per extracted table.** Today one upload is one intake, one category and one version. A workbook (X1, J5) carries several evidence tables.
   - Proposed identity: `(intake_id, source_sha256, table locator, extractor version)`.
   - File-specific mapping rules, review cases, package versions and the snapshot entry must key on it.
   - The package slot keeps one *active* table per category, possibly several slots fed by one upload.
4. **Reprocessing re-extracts.** Deterministic reprocessing and handoff check 12 ("source values unmodified") must re-run the same extractor version on the stored original. **The experiment stored the bridged CSV as the intake for simplicity; production must store the original file** (the immutable-original principle) and treat the bridged table as a derived, reproducible artefact.
5. **Provenance locators.** Generalise `source_line` to a locator (`Sheet!row 5`, `$[3]`, `table[0] row 2`, `line 12`) in records, sidecars and audit events; add `extractor` and `rendering_policy` to the sidecar.
6. **Handoff check 14 (serialisation policy D-1)** is currently CSV-specific (encoding, delimiter, preamble). For extracted tables it should check the extraction warnings instead (unhandled merged cells, missing cached formula values, offset-less datetimes, skipped rows).
7. **Not needed:** new canonical fields or categories; changes to mapping, proposals, validation, review, packages' lifecycle, reconciliation adapter or the UC-042 engine. UC-042 itself rejects XLSX ("export as CSV"), but it receives Smart Parser's **canonical CSV previews**, so no engine change is needed (as 3B-11 showed).

**Effort (rough).**

| Item | Estimate |
|---|---|
| XLSX extractor with rendering rules + identity/reprocess/provenance changes (items 1–6) | the bulk of the work, ~1 phase |
| JSON on top | small |
| MD/DOCX tables | very small |
| Document-format classification | small, after the policy decision |

## 9. Limitations of this experiment

- **Synthetic, well-formed inputs**, generated from the canonical fixtures. Real exports have more variety (subtotals, multiple header rows, locale formats such as `1.234,56`, `£` symbols, `(123.45)` negatives), which this experiment did not test. Each would surface as a validation failure or a review case, not a silent change, but it is unquantified.
- **The LLM proposer was simulated** (`TruthStub`, answering from the known truth). Live-model quality on friendly/nested keys was not measured; 3B-10 measured live behaviour for CSV headers.
- **One rendering policy** per run; no locale handling; `.xls` / `.ods` not tested; no formula evaluation (cached values only).
- **DOCX provenance is document/table/row level**; Word has no fixed pages.
- **Documents were classification-only**, as PDFs are today (field extraction is Experiment A's scope).
- **The bridge stored derived CSV bytes as the intake** (acceptable for an experiment; not for production; see §8.4).

## 10. Test evidence and verification

| Item | Detail |
|---|---|
| Experiment run | `py -3.11 experiments/multiformat/run_experiment.py --out <dir>`: deterministic; 19 scenarios; outputs `inputs\*` and `results.json` |
| Full regression after the experiment (`regression\regression_summary.txt`) | **620 passed**; without the UC-042 tree 615 passed, 5 skipped. The count includes the 35 tests of the **separate, parallel Experiment A** (`smartparser/pdf_extraction/`, `tests/test_pdf_native_extraction.py`, `docs/PDF_NATIVE_EXTRACTION_FEASIBILITY_REPORT.md`, created by another session this morning; **not part of this work**). Experiment B added no tests to the suite and no code to the `smartparser` package |
| Registry / baseline / corpus | in sync (19) / 445/445 / 161/161 |
| Protected trees | UC-042 107 code + 624 dataset files, Desktop 63 files: hash-identical; 0 UC-042 files newer than the Phase 1 start |
| Production rules / policy / authority | packaged rules empty; shipped POC policy `DISABLED`; production authority unconfigured |
| Not done | no OCR, no live LLM call, no database, no submission or audit-pack publication, no change to the 19 categories or the CSV/PDF pipelines |

**Files created (all in the working copy, isolated):**
- `experiments/multiformat/extractors.py`
- `experiments/multiformat/run_experiment.py`
- this report (`docs/MULTI_FORMAT_INGESTION_FEASIBILITY_REPORT.md`)

**Decisions requested before any implementation:**
1. Approve XLSX as the first supported format, and the rendering rules in §7.
2. Approve the per-table identity model (§8.3).
3. For document evidence: is a DOCX/TXT/MD letter, policy or receipt acceptable where UC-042 expects a PDF?
4. Are locale-formatted numbers (e.g. `1.234,56`, `(123.45)`) to be supported, or rejected for correction at source?
