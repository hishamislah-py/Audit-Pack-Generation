# UC-042 Smart Parser: Phase 2 report

**Controlled CSV column mapping. 18 November 2026.**

**Working copy:** `C:\Users\artlptp263user\p10\smartparser_phase1`, the same isolated copy as Phase 1. The UC-042 tree was used read-only.

**Note on the brief:** the brief I received ended at section 4, "Create a manifest describing:". I implemented everything up to that point and gave the corpus manifest the obvious contents: case, source, transformation, rule set and expected outcome. Sections after that point, if any, were not received.

## Summary

- **Tier A, canonical header:** unchanged, and still the highest-confidence route (`csv_exact_header`, confidence 1.0). On re-running the Phase 1 baseline, all 445 files are still correct, and all 350 CSVs still go through the exact-header route.
- **Tier B, structural variations:** a new tier sits between the exact match and the diagnosis, in the same `classify_csv`, so there is no second classifier.
  - It accepts reordered columns, plus surrounding whitespace and case variations under an explicit, switchable policy.
  - It accepts a file only if **every** column maps to exactly one canonical field and **every** field is present once.
  - The method is `csv_controlled_mapping`, at confidence 0.9.
- **Tier C, aliases:**
  - **The proposal catalogue** (`mapping/rules/alias_proposals.json`) holds 19 proposals, **all `proposed`, none approved**.
  - **The active rules file** (`mapping/rules/approved_aliases.json`) is separate and holds no aliases.
  - **The loader** refuses any active alias without an `approved` proposal and decision metadata. It also refuses ambiguous or colliding aliases.
- **Variation corpus:** 161 reproducible cases across all 14 CSV categories, including the hard negatives. **161/161 behave as expected**, both from bytes and through the pipeline under the upload filename.
- **Tests:** 170 pass, made up of the 136 from Phase 1 plus 34 new ones. Without the UC-042 tree, 167 pass and 3 skip.
- **Protected files:** the UC-042 code (107 files) and datasets (624 files), the Desktop original (63 files) and Clone E are untouched, all verified by hash. Nothing was copied to the Desktop.

## 1. Inspection, and where the mapping goes

The existing flow is:

`identify` → `read_csv` → `classify_csv` (exact header, else diagnosis) → `map_columns` (tiers exact, alias, **normalised name**, template) → normalise → validate.

Two findings shaped the design:
1. **Placement.** Controlled mapping has to happen **inside classification**, because a non-canonical header otherwise never gets a category. It is therefore a new tier in `classify_csv` that calls Module F, `mapping/controlled.py`, much as the scored path already calls `map_columns`.
2. **Mapping after classification.** The existing `map_columns` "normalised name" tier is much looser than Phase 2 allows: it also matches camelCase variants and punctuation (`ClientId` and `client-id` both become `client_id`). When a file is accepted through controlled mapping, the pipeline therefore uses **exactly the mapping the rules accepted** (`to_mapping_result`) and does not re-map loosely. `map_columns` itself is unchanged.

## 2. The mapping rules

| Tier | What is accepted | Where it is defined |
|---|---|---|
| A canonical | Header equals the canonical header exactly | Phase 1, unchanged |
| B structural | Reordered columns. Surrounding whitespace, if `trim_whitespace`. Letter case, if `case_insensitive`. The original BOM is ignored as before. | `approved_aliases.json` → `policy` |
| C alias | A header listed in the **active** rules, whose proposal in the catalogue is `approved` with `decided_by` and `decided_at` | `approved_aliases.json` → `aliases` (empty) plus `alias_proposals.json` |

**What every accepted mapping records:**
- the original source header, exactly as in the file;
- the source column position;
- the canonical field and its canonical position;
- the match kind (`exact`, `whitespace`, `case`, `case+whitespace` or `alias`) and the alias ID used;
- the list of variations (for example `reordered`, `case`).

In the pipeline, each `ColumnMapping` also carries `original_header`, `variation` and `alias_id`. Whitespace and case matches have method `policy_normalised`.

**Rejected, with reasons, and nothing dropped:**
- unexpected columns (the policy is `reject`, and they are listed);
- missing fields;
- several columns mapping to one field;
- a column matching two fields;
- reordering when the policy forbids it.

Rejected files keep all their original cells in the pipeline records, and a test checks this. When a header equals an alias **proposal** that is not active, the diagnosis names that proposal and its status.

**Load-time safeguards:**
- No two canonical names of a category may become equal under the policy. None do across the 14 UC-042 schemas.
- No alias may equal another field's name or alias.
- An active alias must reference a matching `approved` proposal.
- `approved` and `rejected` proposals need decision metadata.

**Alias catalogue**

All 19 proposals are `proposed`, and I approved none.
- **14 mechanical proposals:** a spaced Title-Case rendering of each CSV key column (for example `Bank Entry ID`), assessed as low risk. They are labelled as generated, not business-sourced.
- **5 hand-written proposals** with explicit risks:
  - `Reference` is proposed for **both** `bank_reference` and `end_to_end_ref` in IN-09. That makes it ambiguous, and the loader refuses to activate both.
  - `Debit/Credit` for the IN-09 `dc_indicator` carries a sign-perspective risk, because IN-10 uses the opposite convention.
  - `Balance` for IN-07 `balance_amount` could be confused with IN-08's opening or closing balance.
  - `Difference` for IN-05 `difference_reported` could be confused with IN-06, which defines the difference the opposite way round.

**Test-only approvals:** the "approved alias" path is exercised with `tests/fixtures/mapping_rules/test_*.json`, where approval is marked "TEST FIXTURE - not a business approval". These files are never used in production.

**Exact-only rules (`EXACT_ONLY_RULES`):** these reproduce Phase 1 behaviour.

**Changed Phase 1 tests:** three Phase 1 tests asserted that reordered, re-cased or whitespace-padded headers are **not** accepted, which the Phase 2 policy deliberately changes. The Phase 1 classification tests now run under `EXACT_ONLY_RULES` with their assertions unchanged. The default policy is tested separately, including switching each policy option off.

## 3. Variation corpus

The corpus is built by `tools/build_variation_corpus.py` into `corpus/phase2_variations/` (161 CSVs, `manifest.csv` and `manifest.json`).
- It is built from the canonical September fixtures, which are byte copies of UC-042's `set_01_clean_baseline`. The originals are only read.
- The build is byte-identical on every run, and a test checks this against the committed copy.
- For each case, the manifest records: case ID, category, case type, upload filename, source file and its SHA-256, output SHA-256, the transformation, the rule set, the expected outcome, the expected category and a note.

| Case type | Per category | Expected | Result |
|---|---|---|---|
| Canonical | 14 | accept | 14/14 |
| Renamed file (misleading upload name) | 14 | same category | 14/14 |
| Reordered (reversed columns, data moved with them) | 14 | accept | 14/14 |
| Header whitespace | 14 | accept (policy) | 14/14 |
| Header upper-case | 14 | accept (policy) | 14/14 |
| Approved alias (test approval) | 14 | accept | 14/14 |
| Same alias, proposed only (production rules) | 14 | reject | 14/14 |
| Missing column | 14 | reject | 14/14 |
| Extra column | 14 | reject, column reported | 14/14 |
| Duplicate mapping (`X` and `x`) | 14 | reject | 14/14 |
| Unknown header (`col_1..n`) | 14 | reject with diagnostic | 14/14 |
| Ambiguous alias (`Reference` in IN-09) | 1 | reject | 1/1 |
| Hard negatives | 6 | see below | 6/6 |
| **Total** | **161** | | **161/161** |

**Hard negatives:**

| Case | Expected and actual result |
|---|---|
| IN-10 with its key and time columns renamed to IN-09 names | Neither IN-09 nor IN-10 |
| IN-09 uploaded as `sga_cashbook_entries_2026-09.csv` | Still IN-09 |
| IN-07 plus the IN-08-only columns | Neither IN-07 nor IN-08 |
| IN-08 reordered | IN-08, not IN-07 |
| IN-06 uploaded as `internal_recon_records_2026-09.csv` | Still IN-06 |
| IN-05 reduced to the columns it shares with IN-06 | Neither IN-05 nor IN-06 |

Every accepted variation also maps `complete` and validates in the pipeline. The reordered files produce **identical normalised records** to their canonical originals for all 14 categories.

## 4. Changed files

All in `p10\smartparser_phase1`.

**New**
- `smartparser/mapping/controlled.py`
- `smartparser/mapping/rules/approved_aliases.json`
- `smartparser/mapping/rules/alias_proposals.json`
- `tools/build_variation_corpus.py`
- `tools/evaluate_variation_corpus.py`
- `corpus/phase2_variations/`: 161 CSVs and the manifests, 3.2 MB
- `tests/test_controlled_mapping.py`: 34 tests
- `tests/fixtures/mapping_rules/`: 5 test-only rule files

**Changed**
- `smartparser/classify/csv_classifier.py`: controlled tier, `EXACT_ONLY_RULES`, `default_rules`, a diagnosis that names unapproved proposals, and a more useful unknown-header message
- `smartparser/pipeline.py`: `mapping_rules` parameter, and the accepted controlled mapping is used as is
- `smartparser/classify/evidence.py`: `rules` parameter
- `smartparser/models/enums.py`: `CSV_CONTROLLED_MAPPING`, `POLICY_NORMALISED`
- `smartparser/models/results.py`: `ColumnMapping.variation`, `original_header`, `alias_id`
- `pyproject.toml`: rules files added as package data
- `README.md`: status line
- `tests/test_classification_baseline.py`: the helper uses `EXACT_ONLY_RULES`; assertions unchanged

## 5. Test results

```
py -3.11 -m pytest                         170 passed
UC042_ROOT=/nonexistent py -3.11 -m pytest 167 passed, 3 skipped
Phase 1 baseline re-run                    445/445 correct (350 CSV via csv_exact_header, 95 PDF)
Variation corpus                           161/161 as expected (bytes and pipeline)
```

## 6. Limitations and open points

- **The approved-alias path is proven only with test approvals.** In production no alias is active until someone with business authority approves a proposal and records it. The 14 key-column proposals are mechanical suggestions, not evidence that any real system uses those labels.
- **Supported variations:** reordering, whitespace and case only. Not supported:
  - punctuation variants and camelCase (`Bank-Entry-ID`, `bankEntryId`);
  - renamed columns without an approved alias;
  - extra columns of any kind;
  - other delimiters or encodings (still D-1 from Phase 1: an exact or mapped header is identified but flagged);
  - real third-party layouts.
- **Extra columns are always rejected.** Phase 2 has no "allowed extra columns" policy; that would need a decision on how retained but unused data should flow.
- **The corpus is synthetic**, derived from one canonical dataset. It tests the rules, not real-world export diversity.
- **Value-level variation is out of scope:** for example, `1,000.00` or `D`/`C` written as `Debit`/`Credit`. Row content checks still flag it as nonconforming.
- **Decision needed:** who in the business approves aliases. The catalogue fields `decided_by`, `decided_at` and `basis` are ready.

Evidence in this folder:
- `evidence/variation_results.csv` and `evidence/variation_summary.json`
- `evidence/manifest.csv` and `evidence/manifest.json` (the corpus manifest)
- `evidence/rules/` (the shipped rules and catalogue)
- `evidence/phase1_baseline_rerun/`
- `evidence/test_run_full.txt`
