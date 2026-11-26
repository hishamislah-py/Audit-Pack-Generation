# Experiment A: Native PDF Extraction and Canonical Mapping Without OCR

**Feasibility report, 19 Nov 2026.**

| | |
|---|---|
| **Working copy** | `C:\Users\artlptp263user\p10\smartparser_phase1` |
| **Authoritative source** | `p10/uc042_token_optimisation`, used read-only |
| **Status** | Experiment complete; awaiting review. No broader PDF implementation has been started. |

## 1. Summary

**Feasible, within a narrow scope.**

For the five UC-042 PDF evidence categories as UC-042 itself produces them, native text extraction without OCR works:
- it maps every value to its canonical field;
- it preserves identifiers, dates and timestamps exactly;
- it records page-and-line provenance for every value.

**Accuracy:**
- On the real UC-042 synthetic evidence, **34 of 34 canonical fields across the 6 distinct documents** equal UC-042's own extraction. Counting three extra runs in different contexts, it is 47 of 47.
- On 11 constructed variants, every extracted value equals the source value except one. That one is a wrapped value, which was **flagged and routed to human review**, not accepted.
- Results are byte-reproducible.
- No original PDF changed.

**The limits are important:**
- **One layout only.** The real corpus contains just 6 distinct PDFs, all one-page, all written by the same ReportLab generator, all in one layout: `Label: value` lines under a "Key details" heading.
- **Tables are not supported.** In table layouts, `pypdf` gives no reliable cell structure. The experiment can only show such values as *candidates* for a human.
- **Scanned PDFs are out of scope.** They are detected and refused.
- **No financial amounts were tested,** because none of the five PDF categories carries one.

**Recommendation:** make native PDF extraction a formal Smart Parser capability **only** for the UC-042 key-details layout, with the human-review routing shown here. Do not generalise it to other layouts, tables or third-party PDFs without a corpus of real documents of those kinds (§10).

---

## 2. Scope and boundaries

**Nothing outside the experiment was modified:**
- the UC-042 source;
- the original Smart Parser (Desktop);
- the UC-042 application;
- Clone E;
- demo databases;
- audit packs;
- the 19-category registry.

The registry is still in sync with UC-042: `import-registry --check` reports "in sync: 19 definitions match".

**What was added in the working copy (new files only):**

| File | Purpose |
|---|---|
| `smartparser/pdf_extraction/__init__.py`, `extractor.py`, `rules.py` | The isolated extraction module |
| `tests/test_pdf_native_extraction.py` | 35 tests |
| `tools/pdfx_build_variants.py` | Builds the constructed variants into an isolated folder |
| `tools/pdfx_run_experiment.py` | The experiment runner |

**Isolation:**
- No pipeline, package, handoff, orchestration, review UI, reconciliation, classification or intake module imports the experiment (asserted by `test_experiment_is_isolated_from_workflows`).
- The output is a proposal record with `applied: false`.
- Nothing is accepted, submitted, or published to an audit pack.

**Tools not used:**
- OCR;
- external AI providers;
- network access;
- new dependencies. Only `pypdf`, already declared in `pyproject.toml`, is used. PyMuPDF happens to be installed on the machine but was deliberately not used.

**Test data:**
- *Real:* the copies of UC-042 evidence already in `tests/fixtures/uc042_canonical`.
- *Constructed:* PDFs built in isolated folders (`p10/pdfx_experiment/constructed`, pytest `tmp_path`).
- *Oracle:* UC-042's own extraction, captured read-only to `p10/pdfx_experiment/oracle/uc042_pdf_details.json` by running `uc042lib.prepare._pdf_details`, `identify` and `policy.recognise` in UC-042's own environment with bytecode writing disabled. No file under `uc042_token_optimisation` was written; confirmed by an mtime check.

---

## 3. Phase 1: existing capabilities (architecture findings)

| Question | Finding | Evidence |
|---|---|---|
| Existing PDF classification | Yes, deterministic.<br>• A PDF is identified when its text contains every key-details label of exactly one category as a `Label: value` line.<br>• The policy (IN-17) must also be a registered version with the right effective date and markings.<br>• Letters (IN-15/IN-16) share a label set and are resolved by the IN-02 `acknowledgement_letter_ref`. | `smartparser/classify/pdf_classifier.py` (`classify_pdf`, `find_labels`, `recognise_policy`, `letter_refs_from_inventory`), mirroring `uc042lib.prepare.identify` / `_pdf_details` and `uc042lib.policy.recognise` |
| How the 5 categories are recognised | Label sets from the registry (`schemas/definitions/IN-15…IN-19.json` → `pdf.labels`, `label_pattern "^{label}: (.+)$"`), generated from `uc042lib.schema.PDF_FILES` | registry definitions |
| UC-042 expected structure | A text-based PDF with one `Label: value` line per label | `uc042lib/generate.py::write_pdfs` (ReportLab: Title, intro, "Key details" heading, one paragraph per label, body text, footer marking) |
| Which categories are digital with extractable text | All five. All 6 distinct documents in the corpus are ReportLab-generated, one page each, with a text layer and no images. | §4 |
| Canonical fields per category | The canonical "fields" of PDF evidence **are its labels** (`SchemaDefinition.fields` is empty for PDFs). The registry records **no value types** (`PdfLabel.value_type = None`), because UC-042's schema defines none. | `IN-15.json` etc. |
| Value rules | They exist only in the UC-042 *consumers*:<br>• `validate.check_designation` (C10);<br>• `check_policy_and_points` (C03);<br>• `check_checklist` (C16);<br>• `Validator.setup` (reconciliation point, effective date);<br>• `policy.applicability`. | read in the UC-042 source |
| Field extraction before this experiment | **No.** `find_labels` returns `{label: value}` for classification only: no page, no line, no per-field validation, no conflict or missing handling, no mapping record. `pdf_engine` says "Document-field extraction with page references remains Phase 3." | `smartparser/pdf_engine/__init__.py:6` |
| Libraries | `pypdf` 6.4.1: per-page text, no layout or table model. Image-only detection is already implemented (`pdf_engine.extract_pdf` counts image XObjects). `pdfplumber` and `pypdfium2` are not installed. | environment check |

**Design consequence.** The experiment reuses, rather than duplicates:
- the PDF engine;
- the classifier (identification, policy recognition, letter slot);
- the registry's labels and cross-document relationships;
- the orchestration `Decision` vocabulary.

It adds only per-field extraction, provenance, uncertainty detection and consumer-rule validation. The CSV mapping engine does not apply here, because PDF evidence has labels, not columns.

---

## 4. Phase 2: controlled test dataset

**Real UC-042 synthetic evidence.** All 6 distinct PDFs in the corpus; 95 PDF files collapse to these 6 by SHA-256.

| File | Category | Pages | Text layer | Images | Structure |
|---|---|---|---|---|---|
| ack_letter_SGA-GBP-01.pdf | IN-15 | 1 | yes | 0 | title, intro, Key details (6 labels), body |
| ack_letter_SGA-EUR-01.pdf | IN-16 | 1 | yes | 0 | same |
| safeguarding_reconciliation_policy_v1.2.pdf | IN-17 | 1 | yes | 0 | title, intro, Key details (7), two body paragraphs |
| safeguarding_reconciliation_policy_v1.1.pdf | IN-17 | 1 | yes | 0 | as v1.2, plus watermark lines; the em dash extracts as U+FFFD |
| governance_register_2026-09.pdf | IN-18 | 1 | yes | 0 | title, intro, Key details (3), body containing another `Key: value` line |
| rep027_submission_receipt_2026-08.pdf | IN-19 | 1 | yes | 0 | title, intro, Key details (5): identifiers, dates, an ISO timestamp |

**The text layer was verified, not assumed.** Each file was read with `pypdf`: non-empty text, zero image XObjects, ReportLab producer.

**Not available in the real corpus:**
- multi-page documents;
- tables;
- money amounts;
- documents from any other generator.

**Constructed variants**, to cover what the corpus lacks. They are built with the same ReportLab layout as `uc042lib/generate.py`, each changing **one** property. They are byte-reproducible (two builds, identical SHA-256) and stored in `constructed_pdfs/` with `variants_manifest.json`.

| Variant | Property tested |
|---|---|
| V01 | Multi-page (key details on page 2) |
| V02 | Key details as a two-column **table** |
| V03 | One label missing (IN-19 without `Submission reference`) |
| V04 | The same label twice with different values (`Allocated from`) |
| V05 | Near-miss label (`Accountable Person` instead of `Accountable person`) |
| V06 | **Image-only** page: the key details exist only as pixels |
| V07 | A value long enough to **wrap** onto the next line |
| V08 | Unregistered policy version 1.3 |
| V09 | Malformed timestamp (`17/09/2026 11:02`) |
| V10 | Letter reference matching no IN-02 account |
| V11 | Well-formed date that breaks a business rule (allocated after the period end) |

The constructed variants are test material, not evidence. They do not show that real-world PDFs behave this way (§10).

---

## 5. Phase 3: the extraction module

### `smartparser.pdf_extraction.extract_document`

**Signature:** `extract_document(data, filename, registry, *, inventory=None, period_id=None) -> ExtractionResult`.

**Steps:**
1. **Native text.** `pdf_engine.extract_pdf` (pypdf).
   - No `%PDF-` signature, or unreadable → `UNREADABLE`.
   - No text but images → `IMAGE_ONLY`. Nothing is extracted, `ocr_used: false`.
2. **Category.** `classify_pdf` (unchanged).
   - If it is not identified, the closest label set is reported for review only, never mapped.
   - A report-only fallback detects a label set present *without* `Label: value` anchoring, such as a table.
3. **Per-field extraction.** For every registry label of the category, every page and line is scanned:

   | Field status | Meaning |
   |---|---|
   | `EXTRACTED` | An anchored `^Label: (.+)$` line (the UC-042 rule); value stripped exactly as UC-042 strips it, never reformatted |
   | `CONFLICT` | Two or more different values; none is chosen |
   | `NOT_LINE_ANCHORED` | The label appears, but not as `Label: value` (for example a table cell). The next line is shown as a **candidate** only. |
   | `MISSING` | Not present |

4. **Uncertainty flags:**
   - `POSSIBLY_WRAPPED`: the value line fills at least 85% of the page's longest line and is followed by continuation text;
   - `REPEATED_IDENTICAL`;
   - near-miss labels (case and spacing, difflib ≥ 0.8), reported and never mapped.
5. **Canonical mapping:**
   - `canonical_field = "<category>.<label>"`, the registry's canonical identity for PDF evidence;
   - `cross_document_target` from the registry relationships (for example `IN-15.Letter reference` → `IN-02.acknowledgement_letter_ref`);
   - while a letter's slot is unresolved, the canonical field is `IN-15|IN-16.<label>`.
6. **Validation** (`rules.py`). Each rule cites the UC-042 consumer it restates. Labels UC-042 never reads (for example `Institution`, `Frequency`, `Role`) are `NOT_EVALUATED`, with the reason; no rule is invented.

   | Level | Meaning | Examples |
   |---|---|---|
   | PARSE | UC-042 treats the document as unusable | registered version, registered effective date, version applies to the period, `HH:MM Europe/London` |
   | CROSS_DOC | Compared with another document | letter values vs IN-02: reference, masked number, currency, designation |
   | CONTROL | A UC-042 control evaluates it | C10 (`Safeguarding` wording, letter date ≤ period end), C03 (`STANDARD`, `Per currency`), C16 (accountable person, allocated-from date, return period, timestamp format, due-date format) |

7. **Provenance per value:** file name, SHA-256 of the bytes, and for every occurrence the page (1-based), the line (1-based in the extracted page text) and the exact source line.
8. **Routing.** The existing `Decision` values are reused. **No auto-accept exists.** `DETERMINISTIC` means "every canonical field extracted once, unflagged, and no PARSE or CROSS_DOC failure"; it is still a proposal.

   | Condition | Decision |
   |---|---|
   | Unreadable, image-only, or category not identified | `REJECT_OR_HOLD` |
   | Any `MISSING`, `CONFLICT` or `NOT_LINE_ANCHORED` field; `POSSIBLY_WRAPPED`; a PARSE or CROSS_DOC failure; a `FORMAT:` failure (a value UC-042 cannot read); a near-miss label; an ambiguous letter slot | `HUMAN_REVIEW` |
   | Otherwise | `DETERMINISTIC` |

   A CONTROL failure on a well-formed value (V11) is a business result for UC-042 to report, so it does not route the extraction to review.

---

## 6. Phase 4: results per tested PDF

**What was run:**
- **Runner:** `tools/pdfx_run_experiment.py`.
- **Context:** IN-02 = the September account inventory; period `PER-2026-09` unless stated otherwise.
- **Truth:**
  - real files: UC-042's own extraction (the oracle);
  - constructed files: the values the builder wrote.
- **"Original unchanged":** SHA-256 identical before and after.

**Column key:**
- **Ext.** = extracted / canonical fields;
- **Mapped** = values mapped to a canonical field of an *identified* category;
- **Unmapped lines** = other `Key: value` lines in the text that are not canonical labels.

### 6.1 Real UC-042 PDFs

| # | Case | Native text | Pages | Category | Ext. | Mapped | Not extracted | Unmapped lines | Validation | = truth | Review? | Decision | Original unchanged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | ack_letter_SGA-EUR-01 | SUCCEEDED | 1 | IN-16 | 6/6 | 6 | – | 1 (`Generic synthetic wording`) | 6 PASS, 1 n/e | 6/6 | No | DETERMINISTIC | Yes |
| R2 | ack_letter_SGA-GBP-01 | SUCCEEDED | 1 | IN-15 | 6/6 | 6 | – | 1 | 6 PASS, 1 n/e | 6/6 | No | DETERMINISTIC | Yes |
| R3 | policy_v1.2 | SUCCEEDED | 1 | IN-17 | 7/7 | 7 | – | 0 | 7 PASS, 2 n/e | 7/7 | No | DETERMINISTIC | Yes |
| R4 | governance_register_2026-09 | SUCCEEDED | 1 | IN-18 | 3/3 | 3 | – | 1 (`Critical individuals…`) | 2 PASS, 1 n/e | 3/3 | No | DETERMINISTIC | Yes |
| R5 | rep027_submission_receipt_2026-08 | SUCCEEDED | 1 | IN-19 | 5/5 | 5 | – | 0 | 4 PASS, 2 n/e | 5/5 | No | DETERMINISTIC | Yes |
| R6 | policy_v1.1, period **PER-2026-01** | SUCCEEDED | 1 | IN-17 | 7/7 | 7 | – | 0 | 7 PASS, 2 n/e | 7/7 | No | DETERMINISTIC | Yes |
| R7 | policy_v1.1, period **PER-2026-09** | SUCCEEDED | 1 | IN-17 | 7/7 | 7 | – | 0 | **POLICY-APPLIES FAIL** (superseded by v1.2 from 2026-05-07) | 7/7 | **Yes** | HUMAN_REVIEW | Yes |
| R8 | ack_letter_SGA-GBP-01, **no IN-02** | SUCCEEDED | 1 | IN-15\|IN-16 | 6/6 | 0 (slot unresolved) | – | 1 | 2 PASS, 4 n/e (cross-document rules wait for the slot) | 6/6 | **Yes** | HUMAN_REVIEW | Yes |
| R9 | ack_letter_SGA-EUR-01, **no IN-02** | SUCCEEDED | 1 | IN-15\|IN-16 | 6/6 | 0 | – | 1 | 2 PASS, 4 n/e | 6/6 | **Yes** | HUMAN_REVIEW | Yes |

(n/e = NOT_EVALUATED: UC-042 has no rule for that label, for example `Institution`, `Frequency`, `Role` and `Submission reference`.)

**Notes:**
- **R6 and R7** show that applicability depends on the period. This matches UC-042's `POLICY_NOT_APPLICABLE` behaviour.
- **v1.1's em dash** extracts as U+FFFD. The policy markings still match because UC-042's normalisation is reused, and none of the field values is affected.

### 6.2 Constructed variants

| # | Variant | Native text | Pages | Category | Ext. | Mapped | Not extracted | Validation | = truth | Review? | Decision | Behaviour |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | multi-page | SUCCEEDED | **2** | IN-15 | 6/6 | 6 | – | 6 PASS | 6/6 | No | DETERMINISTIC | Every occurrence is on **page 2** |
| V02 | table layout | SUCCEEDED | 1 | (IN-15\|IN-16 candidates) | **0/6** | 0 | all 6 `NOT_LINE_ANCHORED` | – | – | Yes | REJECT_OR_HOLD | pypdf emits cells as alternating lines with no geometry. Values are shown as candidates (all 6 correct) but **never mapped**. |
| V03 | missing label | SUCCEEDED | 1 | (closest IN-19) | 4/5 | 0 | `Submission reference` MISSING | 3 PASS | 4/4 | – | REJECT_OR_HOLD | Not identified (4 of 5 labels), as UC-042 |
| V04 | conflicting values | SUCCEEDED | 1 | IN-18 | 2/3 | 2 | `Allocated from` **CONFLICT** [`2026-05-07`, `2026-06-01`] | 1 PASS | 2/2 | Yes | HUMAN_REVIEW | Neither value is chosen |
| V05 | near-miss label | SUCCEEDED | 1 | (closest IN-18) | 2/3 | 0 | `Accountable person` MISSING | 1 PASS | 2/2 | – | REJECT_OR_HOLD | `Accountable Person` reported as near-miss, never mapped |
| V06 | image-only | **IMAGE_ONLY** | 1 | – | 0 | 0 | – | – | – | – | REJECT_OR_HOLD | Nothing extracted; no OCR |
| V07 | wrapped value | SUCCEEDED | 1 | IN-15 | 6/6 | 6 | – | `LETTER-ACCOUNT-NAME` FAIL vs IN-02 | **5/6** | Yes | HUMAN_REVIEW | `Account name` truncated at the line end, but flagged **POSSIBLY_WRAPPED** and mismatched with IN-02, so not accepted |
| V08 | unregistered policy | SUCCEEDED | 1 | (IN-17 not recognised) | 7/7 | 0 | – | 3 PARSE FAIL | 7/7 | – | REJECT_OR_HOLD | Not identified (`POLICY_NOT_RECOGNISED`), as UC-042 |
| V09 | malformed timestamp | SUCCEEDED | 1 | IN-19 | 5/5 | 5 | – | `RETURN-SUBMITTED-AT` FAIL (FORMAT) | 5/5 | Yes | HUMAN_REVIEW | The value is kept exactly as written (`17/09/2026 11:02`) and not reformatted |
| V10 | unknown letter reference | SUCCEEDED | 1 | IN-15\|IN-16 | 6/6 | 0 | – | 2 PASS | 6/6 | Yes | HUMAN_REVIEW | Slot unresolved, as UC-042 (`LETTER_NOT_MATCHED`) |
| V11 | business-rule failure | SUCCEEDED | 1 | IN-18 | 3/3 | 3 | – | `GOV-ALLOCATED-FROM` **CONTROL FAIL** | 3/3 | No | DETERMINISTIC | Extraction is certain; the C16 failure is reported for UC-042 |

**Every original was unchanged:** 20 of 20 cases had identical SHA-256 before and after.

**Field-level provenance example** (R5, `IN-19.Submitted at`):

```
value "2026-09-17T11:02:00+01:00"
file rep027_submission_receipt_2026-08.pdf
sha256 91743fd3f1c8…
page 1, line 10
source "Submitted at: 2026-09-17T11:02:00+01:00"
```

Every value in `results/results.json` carries the same record.

---

## 7. Accuracy

| Measure | Result |
|---|---|
| Real documents: canonical fields equal to UC-042's own extraction | **34/34** (6 distinct documents); 47/47 counting the three extra context runs |
| Constructed variants: extracted values equal to the written source values | 45/46. The one difference is V07's truncated wrapped value, which was **flagged and routed to review**. |
| Uncertain values silently accepted | **0**: every MISSING, CONFLICT, unanchored, wrapped, near-miss, ambiguous or FORMAT case went to HUMAN_REVIEW or REJECT_OR_HOLD |
| Identifiers preserved exactly | Yes: `ACK-INST01-4471`, `****4471` (asterisks intact), `SYN-RD-2026-08-0001`, ISO timestamp with offset |
| Dates and times preserved exactly | Yes; never reformatted (V09 keeps `17/09/2026 11:02` as written) |
| Financial amounts | **Not tested: no PDF category carries an amount.** This criterion cannot be demonstrated on UC-042 PDF evidence. |
| Reproducibility | A second full pass gave identical output (`summary.json: reproducible_second_pass: true`); a pytest test asserts it too; the variant PDFs rebuild byte-identically |
| OCR used | Never (`ocr_used: false` in all 20 cases) |
| Anything applied, accepted or submitted | Nothing (`applied: false` in all 20 cases) |

**Tests.**
- `tests/test_pdf_native_extraction.py`: **35 passed**.
- Full Smart Parser suite: **620 passed** (585 before, plus 35 new), so nothing regressed.
- Registry drift check: in sync.

**Acceptance criteria:**

| Criterion | Met? |
|---|---|
| Text extracted without OCR | Yes |
| Values correctly mapped to existing canonical fields | Yes |
| Financial values and identifiers preserved | Identifiers yes; **financial values not applicable** (no amounts in PDF evidence) |
| Field-level provenance | Yes |
| Uncertain values not silently accepted | Yes |
| Results reproducible | Yes |

---

## 8. Limitations

1. **Corpus homogeneity.**
   - The real evidence is **6 distinct one-page documents from one generator, in one layout**.
   - 34/34 proves the method on UC-042's own documents only. **It is not evidence about real bank letters, policies or regulator receipts.**
2. **Tables are not supported.**
   - `pypdf` extracts table cells as separate lines in reading order, with no row or column geometry (V02).
   - The experiment can only offer candidates to a human.
   - A real table capability needs a layout-aware extractor (for example pdfplumber or PyMuPDF word coordinates). That would be new infrastructure, so it was not used.
3. **Wrapped values.**
   - UC-042's own rule (`^Label: (.+)$`) also takes only the first line, so it would truncate exactly as V07 shows.
   - The 85% width heuristic is a safety net, not a guarantee: a wrap in a narrow layout could be missed. In the UC-042 letter case, the IN-02 cross-check catches it anyway.
4. **Layout assumption.**
   - Values must sit on the same extracted line as the label.
   - Two-column layouts, labels in a sidebar, or text drawn out of reading order can break that, and nothing in the corpus tests it.
5. **Scanned PDFs are out of scope.** They are detected (`IMAGE_ONLY`) and refused. A PDF with *both* images and a partial text layer is treated as text; only its text is used.
6. **Value rules are a restatement, not the registry.**
   - `rules.py` restates UC-042 consumer rules with citations. If UC-042 changes a rule, it must be updated by hand.
   - The UC-042 due-date business-day calculation and C10's other conditions are left to UC-042, not duplicated.
7. **"DETERMINISTIC" is not acceptance.** No workflow consumes the result. Any use would need the existing review and approval principles (owner decision).
8. **The near-miss detector** covers case and spacing variants only (difflib ≥ 0.8). Translated or synonymous labels ("Ref no.", "Effective from") are reported as unmapped lines, not near misses.

---

## 9. Reuse and non-duplication

| Reused | Not duplicated |
|---|---|
| `pdf_engine.extract_pdf` (text and image detection) | No second PDF reader |
| `classify_pdf`, `letter_refs_from_inventory`, policy recognition | No second classifier or policy registry |
| Registry labels, `relationships`, `policy_versions` | No new schema or types; the registry is unchanged (`value_type` stays None; asserted by a test) |
| `orchestration.policy.Decision` | No new routing vocabulary |
| UC-042 rules, cited in `rules.py` | The business-day calendar and C16 due-date computation stay in UC-042 |

**Related work.** A separate, parallel experiment (`experiments/multiformat`, "Experiment B", created 19 Nov 08:44) feeds document text to `classify_pdf`. It was not modified. If both proceed, Experiment B's document route could call this extractor instead of re-implementing it.

---

## 10. Recommendation

**Adopt native PDF extraction as a formal Smart Parser capability for the UC-042 key-details layout only, after review.**

**Conditions:**
1. **Scope it explicitly** to "text-based PDFs whose key details are `Label: value` lines", the layout UC-042 defines. Everything else stays REJECT_OR_HOLD or HUMAN_REVIEW, as now.
2. **Keep the routing:**
   - no auto-accept;
   - any uncertainty goes to HUMAN_REVIEW;
   - unreadable, scanned or unidentified documents go to REJECT_OR_HOLD.
3. **Connect it to the existing review workflow** (review cases, approvals, audit events) before any output is used. That is an owner decision and was not done here.
4. **Owner decision on the rule restatements.** Either keep `rules.py`, with a drift test against the UC-042 consumers, or extend the registry import to emit PDF value rules from UC-042, so they are generated, not hand-kept.

**Do not proceed with any of these before a real corpus exists:**
- tables;
- other layouts;
- third-party PDFs;
- money amounts;
- scanned documents.

They need real documents of those kinds, and a decision on a layout-aware extractor (new dependency) or OCR (out of scope). Recommended next step if wanted: collect 10 to 20 real, anonymised examples per category and re-run this harness unchanged.

---

## 11. How to reproduce

From `p10/smartparser_phase1`, with `py -3.11`:

```
py -3.11 tools/pdfx_build_variants.py ../pdfx_experiment/constructed
py -3.11 tools/pdfx_run_experiment.py tests/fixtures/uc042_canonical ../pdfx_experiment/oracle/uc042_pdf_details.json ../pdfx_experiment/constructed <out_dir>
py -3.11 -m pytest tests/test_pdf_native_extraction.py -q
```

## 12. Deliverables in this folder

| Path | Content |
|---|---|
| `PDF_NATIVE_EXTRACTION_FEASIBILITY_REPORT.md` | This report (also in `p10/smartparser_phase1/docs/`) |
| `results/results.json` | Full per-case output: every field, occurrence, validation and decision, plus comparison with the truth |
| `results/summary.json`, `results/summary.csv` | One row per case, plus the overall checks |
| `constructed_pdfs/` | The 11 variant PDFs and `variants_manifest.json` (purpose, expected behaviour, source values) |
| `oracle/uc042_pdf_details.json` | UC-042's own extraction of the 6 real PDFs (the ground truth) |
