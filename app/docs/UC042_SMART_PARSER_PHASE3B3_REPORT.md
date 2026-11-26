# UC-042 Smart Parser: Phase 3B-3 report

**Deterministic reprocessing and handoff. 18 November 2026.**

**Working copy:** `C:\Users\artlptp263user\p10\smartparser_phase1`. The UC-042 tree was used read-only.

**Status:**
- **Implemented and tested:** reprocessing, the 14-point eligibility checklist, and the preview writer with its sidecar.
- **Implemented but disabled:** UC-042 submission. `submit_to_uc042` always refuses.
- **Blocked by owner decision:** approving the canonical re-serialisation and the sidecar as a UC-042 submission format.

## 1. Files

**New**

| File | Purpose |
|---|---|
| `smartparser/handoff/reprocess.py` | `reprocess(intake_id, evidence, registry, rules, confirmation=None)` gives a `ReprocessResult` |
| `smartparser/handoff/eligibility.py` | `check_handoff(rr, registry, policy)` gives a `HandoffEligibility` (14 checks). `HandoffPolicy` (D-1 off, submission off). |
| `smartparser/handoff/writer.py` | `write_preview` gives the canonical CSV plus `.provenance.json`. `submit_to_uc042` always raises `HandoffNotAuthorised`. |
| `tests/test_handoff_3b3.py` | 15 tests |

**Modified**

| File | Change |
|---|---|
| `intake/store.py` | `EvidenceStore.find(evidence_id)`, an intake lookup (additive) |
| `mapping/controlled.py` | `MappingRules.without_file_identity()` |
| `classify/csv_classifier.py` | The automatic controlled tier ignores file mappings (see section 5) |

## 2. Reprocessing

The steps, in order:
1. Find the intake record.
2. Load the stored original bytes, then verify their SHA-256 (a tampered original is refused).
3. Establish the category.
   - With a category confirmation, the confirmation must belong to this intake and SHA-256, and the category is supplied to the 3B-0 controlled path.
   - Without one, automatic classification must identify the file.
4. Load the governed rules with this upload's file identity.
5. Run the normal pipeline: `controlled_map`, existing normalisation, validation and content check.

**Isolation:**
- An **in-memory** evidence store is used, so reprocessing never creates a new intake record.
- The proposal mechanism is never reached. A test replaces `run_proposal` with a function that raises, and reprocessing still succeeds. `provider_calls` is always 0.

**Repeatability (tested):** two runs give identical mapping models and normalised records.

**Mapping sources:**
- the exact header;
- a policy-normalised header (reordering, case, whitespace);
- an approved alias;
- an approved layout;
- an approved file mapping (this intake only).

UC-042 categories never use `map_columns`.

## 3. Handoff checklist (`check_handoff`)

| # | Check |
|---|---|
| 1 | Category deterministic (`csv_exact_header` or `csv_controlled_mapping`), or `manual` **with** a recorded confirmation ID |
| 2 | Mapping status `complete` |
| 3 | Every canonical field mapped exactly once |
| 4 | No duplicate targets |
| 5 | No required field missing |
| 6 | No unmapped source column (current reject policy) |
| 7 | Every mapping is exact, policy-normalised, alias, approved layout or approved file mapping; rule-backed ones carry a rule ID |
| 8 | Rule IDs and versions exist for this file |
| 9 | No revoked or superseded rule used |
| 10 | Validation has zero errors |
| 11 | Content check has zero nonconforming rows |
| 12 | Every record cell equals the cell re-read from the stored source bytes, so **no value, including money, is modified or reinterpreted** |
| 13 | Provenance complete: SHA-256, intake ID, original header and index per column, row and line per record |
| 14 | Serialisation (D-1): UTF-8, comma, header on line 1. Otherwise ineligible unless `HandoffPolicy(allow_noncanonical_serialisation=True)`, which is **off by default**. |

**Notes:**
- `submission_authorised` is always `False`.
- **An approved proposal does not make a file eligible.** Tests prove this for missing required fields, a column left unmapped, a revoked rule, D-1, and nonconforming values.

## 4. Preview writer

- **Output:** the writer only **reorders columns** into the UC-042 canonical order. Cells are the original strings, with no date, amount, sign or currency conversion. It verifies its own output by re-reading it.
- **Refusals:** it refuses ineligible files, and it refuses to write inside the UC-042 tree (the default UC-042 path, or `UC042_ROOT`).
- **File names** start with `PREVIEW_ONLY_NOT_AUTHORISED_FOR_UC042_SUBMISSION`.
- **The sidecar** carries:
  - the status marker and `submission_authorised: false`;
  - source SHA-256, intake ID and original filename;
  - category, its basis and the confirmation ID;
  - the canonical header;
  - per column: canonical field and position, source index, original header, method, rule ID and version;
  - the rules used and approval references;
  - per-row output row, source row and source line;
  - the validation status and all 14 check results;
  - the handoff timestamp, and the output SHA-256 and size.
- **Byte-for-byte evidence:** for IN-02, IN-09, IN-10 and IN-13, the preview of a canonical file, of its reordered variant, and of the renamed IN-10 approved through a file mapping **equals the canonical UC-042 source file byte for byte**. Only the column order and header names change; no cell does.

## 5. Design gap found and fixed

**The gap:** the automatic classifier's controlled tier also applied file-specific mappings. A file could therefore be identified as its category **without any category confirmation**, which would have bypassed check 1. A test caught it.

**The fix:** automatic classification uses `rules.without_file_identity()`. A file mapping applies only on the confirmed-category (forced) path. Layouts, which are reusable and approved for a source system, still apply automatically.

## 6. TemplateRegistry decision

Inspected callers: `classify/csv_classifier._classify_scored` (synthetic schemas) and `mapping/engine.map_columns` tier 4 (generic path).

Since 3B-0, **UC-042 categories reach neither.**

**Decision:** UC-042 layouts are governed only by `approved_layouts.json` (3B-2). `TemplateRegistry` is **kept unchanged** for synthetic and provisional schemas, because deleting it would break the generic path and its tests. A test shows a VALIDATED TemplateRegistry entry has no effect on an IN-10 file.

## 7. D-1

**Unchanged.** Non-canonical files remain classified and flagged as before. They are now additionally **ineligible for handoff** (check 14) unless a separately configured policy allows them, which is off by default.

## 8. Results (executed)

| Suite | Result |
|---|---|
| **3B-3** | **15 passed** |
| 3B-2 | 23 passed |
| 3B-1 (including the UNMAPPABLE correction) | 40 passed |
| 3B-0 | 117 passed |
| Phase 1 and original | 136 passed |
| Phase 2 | 34 passed |
| **Full suite** | **365 passed** |
| Without the UC-042 tree | 362 passed, 3 skipped |
| Registry `--check` | in sync |
| Phase 1 baseline | 445/445 |
| Phase 2 corpus | 161/161 |

**Integrity:**
- UC-042 code (107 files) and datasets (624 files): unchanged.
- Desktop Smart Parser (63 files): unchanged.
- 0 files in the UC-042 tree newer than the start of Phase 1.
- Production aliases and layouts: empty. Proposals: 19 `proposed`. Production policy: no roles.

**Evidence:** `Downloads\UC042_SMART_PARSER_PHASE3B\3B3_evidence\`.

## 9. Open owner decisions

1. **Submission format:** is the canonical-layout re-serialisation plus sidecar an acceptable UC-042 submission, and does the sidecar enter UC-042's audit trail?
2. **D-1:** should non-canonical delimiters or encodings ever be eligible?
3. **Location:** where approved previews may be written in a real deployment.
