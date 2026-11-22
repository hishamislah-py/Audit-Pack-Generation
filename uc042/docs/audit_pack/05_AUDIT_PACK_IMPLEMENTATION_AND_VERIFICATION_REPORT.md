# 05 — Audit Pack Implementation and Verification Report

Implemented 30 Oct 2026 under decisions D1–D6 (`01`–`04` in this folder).

The pack layer is **deterministic**:

- no financial calculation;
- no AI;
- no answer-key or golden-snapshot access.

It runs the existing engine once per pack and assembles, cites, validates, renders and publishes write-once.

> **Synthetic POC.** The pack format is a design for illustrative synthetic data, not an official Moorwand or regulatory format. The entity ID `SYN-EMI-001` is illustrative (D2).

## 1. Files changed

| File | Change |
| --- | --- |
| `uc042lib/validate.py` | **D3 structured fields only** (§2). `add()` takes an optional `structured` dict; new helper `timing_structured()`; `control_results.csv` gains a `structured` column; new output `document_details.csv`. No outcome, value, ID, status or note changed. |
| `uc042lib/pack/` (new) | `config.py` (D2, D5 constants, statements, limitations); `registry.py` (D1 control names); `model.py` (canonical JSON, IDs, fingerprints, required structure); `assemble.py` (assembly); `validate_pack.py` (V1–V6, V8); `render_html.py`; `generate.py` (build, write-once publish, generation records, CLI) |
| `tests/test_audit_pack.py` (new) | 40 tests (§10) |
| `uc042_dataset/*/validation/` | Regenerated generated outputs: `control_results.csv` (new column), `document_details.csv` (new). **No source evidence, manifest, mutation or answer key changed** (hash-verified). |
| `packs/` (new) | Nine published packs (§6) |
| `README.md` | Pack command and test count |
| **Unchanged** | All source datasets, mutations, answer keys and golden snapshots (hash-identical to the recorded before-state, `verification/before_state.json`); all existing tests; both verifiers |

## 2. Structured engine fields (D3)

Each field was checked against its source first. Each already existed inside the engine, but only as formatted text or in memory.

| Field | Source before | Now | Verified |
| --- | --- | --- | --- |
| C05 resource: `item_a`, `items_b_to_d`, `resource`, `item_a_reported`, `resource_reported` | Formatted string `"item A …; resource …"` built from engine numbers | `structured` on every assessable C05 result | `computed` text equals `f"item A {item_a}; resource {resource}"` (test) |
| Settlement booking delay: `bank_entry_id`, `settlement_date`, `booking_date`, `booking_lag_business_days`, `within_one_business_day_allowance`, `timing_status: INFORMATIONAL` | Computed for the note only | `structured` on every matched C11-BATCH-BANK result. Outcome unchanged (D-E1b). | SC2 `SB-GBP-20260915` lag 1, within allowance; every other batch 0 (test) |
| Timing evidence: `timing_items[]` (ledger and bank entry, reference, effect, cleared date, item status), `explained_by_timing`, `residual_unexplained` | Note text | `structured` on every non-zero C08 result | explained + residual = difference (test); SC2 item `LE-GBP-0915-0005` / `BE-GBP-0916-T01` |
| PDF key details | `Validator.pdf` (in memory) | Persisted to `validation/document_details.csv` and the pack's file register | Only labels the engine extracts; nothing added (test) |

**Backward compatibility (verified for all 9 datasets):**

- every existing `control_results.csv` column is byte-identical;
- `exceptions.csv`, `investigation_groups.csv` and `candidate_relationships.csv` are identical;
- golden snapshots are unchanged;
- all 135 pre-existing tests pass unchanged.

Insufficient-evidence results carry no structured figures (test).

## 3. Pack schema and structure (`pack.json`, schema `uc042-pack/0.1`)

**Eleven sections:**

- `metadata`;
- `executive_summary`;
- `reconciliation_summary`;
- `control_register`;
- `evidence_register`;
- `settlement_register`;
- `exception_register`;
- `investigation_group_register`;
- `missing_evidence_register`;
- `audit_trail`;
- `statements`.

**Format:** canonical JSON (sorted keys; money as engine 2 dp strings).

**Separate status fields:**

| Field | Values |
| --- | --- |
| `generation_status` | GENERATED / FAILED |
| `evidence_completeness` | COMPLETE / INCOMPLETE |
| `control_outcomes.summary` | ALL_PASSED_OR_NOT_APPLICABLE / FAILURES_PRESENT / NOT_FULLY_ASSESSED |
| `exception_review` | NONE / AWAITING_HUMAN_REVIEW |
| `engine_case_status` | Engine value |
| `pack_review_status` | NOT_REVIEWED |

No blended status exists.

**Identifiers:**

| Identifier | Format |
| --- | --- |
| `pack_id` | `PACK-{scenario}-{period}-{content hash[:12]}` |
| `processing_run_id` | `RUN-` + hash of input hashes, engine, configuration and pack-layer fingerprints |
| `result_id` | `check_id\|scope` |
| `evidence_id` | `IN-xx` (files) or `IN-xx:{primary key}` (records) |
| Missing-evidence items | `MISS-nn` |

### Deviations from the design, and why

| Design | Implemented | Reason |
| --- | --- | --- |
| Every check in `DEPENDS` has ≥ 1 result | `BANK-CASH-LINK` listed as **`NO_FINDINGS`**, proven by the engine's evidence gate, never as PASS | Found during build: the engine emits that check only on failure, so a clean run has no row for it. Showing PASS would be invented; failing generation would be wrong. |
| `control_outcomes` for S02 = FAILURES_PRESENT | **`NOT_FULLY_ASSESSED`** | S02 has insufficient-evidence results but no FAIL; a distinct value is more accurate |
| Run ID from inputs, engine and configuration | Also includes a **pack-layer fingerprint** | So a change to the assembly code can never silently change a pack under the same run ID |
| Control names from the matrix | Engine code `INTEGRITY` (file presence) is labelled "(not named in the source-to-control matrix)" | The matrix has no descriptor for it; none is invented (D1) |
| Zero-substitution guard on balance checks | Excludes DQ22/DQ23 | Their `computed` is the bank-statement side, which is present evidence (e.g. bank opening when the cash-book opening is missing) |

## 4. Assembly workflow (as implemented)

1. `build(case_dir)` runs the engine once in process (`Validator.run()`, D6).
2. It assembles from that run's objects and the source rows. Citations are expanded to source records; any citation that does not resolve fails generation.
3. It computes processing-output hashes, then the content hash and pack ID.
4. It validates (V1–V6, V8). Any finding → FAILED.
5. It renders HTML from the pack only.

`generate()` then publishes **write-once**:

- **New content:** assembled in a temporary directory, then renamed into `packs/<pack_id>/`, with a new generation record in `generations/NNNN.json` (`generated_at` lives only there, D5).
- **Identical content:** the existing pack is left untouched and an `ALREADY_GENERATED_IDENTICAL` record is added.
- **Different content under an existing ID:** refused (`ImmutabilityError`).
- **FAILED:** nothing is published; a record is written to `packs/_failed/<run>/`.

**A control failure is not a generation failure.** Packs with FAIL or INSUFFICIENT_EVIDENCE results are GENERATED, and their status fields say so.

## 5. Scenario 1 acceptance results: all 14 PASSED

| AC | Result |
| --- | --- |
| AC1 Period | `PER-2026-09`, 2026-09-01 to 2026-09-30, 22 reconciliation days |
| AC2 Accounts and currency | EUR, GBP; `OWN-EUR-01`, `OWN-GBP-01`, `SGA-EUR-01`, `SGA-GBP-01`; `POOL-EMONEY`; `SYN-EMI-001` with its illustrative notice |
| AC3/AC4 Controls | 1,886 results (set-equal to the engine run) across 32 check types with results, plus BANK-CASH-LINK `NO_FINDINGS`. 1,798 PASS and 88 NOT_APPLICABLE (C06 × 44, C08 × 44). Per-check PASS counts exactly as 03 §1. |
| AC5 Reconciliation | 44 internal + 44 external rows. 30 Sep GBP 395844.86 / 395844.86 / 395844.86 / 0.00; EUR 118555.00 both sides, 0.00. Opening `LE-EUR-0831-0000` 80000.00, `LE-GBP-0831-0000` 250000.00; 12 client opening rows. |
| AC6/AC10 Evidence | 19 files, all PRESENT; 1,920 cited records, each resolving to its source line and primary key |
| AC7 Provenance | 19 input hashes match the manifest; engine, configuration and pack-layer fingerprints; processing-output hashes; scenario `S01` |
| AC8/AC9 Empty registers | "No exceptions were raised for this period."; "No investigation groups were formed."; no candidates; no missing evidence |
| AC11/AC12 References and fidelity | `validate_pack` returns no findings against the same engine run |
| AC13 Reproducible | Identical `pack.json` and `pack.html` across builds |
| AC14 Non-empty | GENERATED / COMPLETE / ALL_PASSED_OR_NOT_APPLICABLE / NONE / CLEAN / NOT_REVIEWED; 88 batches (lines and bank PASS, 44 top-ups PASS); limitations included |

## 6. Results across all nine datasets (published packs)

| Dataset | Pack ID | Evidence | Controls | Results | Exc. | Groups | Cand. | Missing | Cited records |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Clean baseline | `PACK-S01-PER-2026-09-577b06a1d894` | COMPLETE | ALL_PASSED_OR_NOT_APPLICABLE | 1886 | 0 | 0 | 0 | 0 | 1920 |
| SC2 timing | `PACK-SC2-PER-2026-09-aaca8a8b7194` | COMPLETE | FAILURES_PRESENT | 1886 | 1 | 0 | 0 | 0 | 1921 |
| SC3B fee not itemised | `PACK-SC3B-PER-2026-09-137351796028` | COMPLETE | FAILURES_PRESENT | 1886 | 1 | 0 | 0 | 0 | 1918 |
| SC3C £4.50 | `PACK-SC3C-PER-2026-09-28bb49134f15` | COMPLETE | FAILURES_PRESENT | 1886 | 3 | 1 | 0 | 0 | 1920 |
| S02 missing EUR | `PACK-S02-PER-2026-09-f3dfa52766bb` | **INCOMPLETE** | NOT_FULLY_ASSESSED | 1883 | 1 | 0 | 0 | **1** | 1915 |
| SC5A missing £443.55 | `PACK-SC5A-PER-2026-09-ae391170b93a` | COMPLETE | FAILURES_PRESENT | 1886 | 2 | **0** | **1** | 0 | 1919 |
| SC5C refund twice | `PACK-SC5C-PER-2026-09-eaac7e6b1444` | COMPLETE | FAILURES_PRESENT | 1886 | 17 | 1 | 0 | 0 | 1920 |
| SC5D closing −£250 | `PACK-SC5D-PER-2026-09-2c5a7ae2e160` | COMPLETE | FAILURES_PRESENT | 1886 | 3 | 1 | 0 | 0 | 1920 |
| S05 £812.40 | `PACK-S05-PER-2026-09-ddd0fdc8b731` | COMPLETE | FAILURES_PRESENT | 1887 | 2 | 1 | 0 | 0 | 1921 |

### Scenario-specific checks (all PASSED)

| Scenario | Verified content |
| --- | --- |
| SC2 | `EXC-SC2-01` is TIMING_EVIDENCED, OPEN and AWAITING_HUMAN_REVIEW, with "not resolved". Settlement `SB-GBP-20260915` lag 1, bank entry `IN-09:BE-GBP-0916-T01`. |
| 3a (baseline) | `AQ-GBP-20260908`: gross 10000.00, fees 45.50, net 9954.50; lines, bank and top-up PASS |
| 3b | Fees 45.50 shown from the header; lines FAIL; no breakdown invented |
| SC3C | `GRP-SC3C-01` (3); −4.50 NOT_EVIDENCED |
| S02 | `MISS-01` = `MISSING_BANK_EVIDENCE\|SGA-EUR-01\|2026-09-15`, 13 results, "not available"; the 15 Sep EUR external row shows "not available" |
| 5a | No group; `CAND-SC5A-01` UNVERIFIED, in the candidate list only |
| 5c, 5d | One group each, with the no-cause statement |
| S05 | −812.40, NOT_EVIDENCED, "Unexplained", no cause, `GRP-S05-01` |

## 7. Financial value fidelity

**V3 compares every figure in every pack with its origin; zero differences across all 9 packs:**

- result outcome, computed, reported, evidence status, note, root cause and structured fields → the same engine run;
- exceptions, groups and candidates → field by field;
- internal and external reconciliation rows → engine fields;
- settlement gross, fees, adjustments, net, dates, currency and direction → source rows;
- opening positions → source rows.

**The pack performs no arithmetic.** Insufficient-evidence balance and difference results stay blank or "not available", never a number (V6).

**Negative tests detect each of:**

- a changed result amount;
- a changed reconciliation figure;
- a missing section;
- an unknown evidence ID;
- a removed result;
- an exception shown as RESOLVED;
- an unexplained difference described as explained;
- a group with a cause;
- a missing value shown as `0.00`;
- a candidate promoted to a group.

## 8. Provenance and reference validation

- **References:** every result, exception, group and candidate evidence ID resolves to a file entry or to a record entry whose source line carries that primary key (V2; AC6 test re-reads the source).
- **Inputs:** input SHA-256 values are recomputed and match the manifest (V8).
- **Processing outputs:** hashes recorded in the pack equal the files written beside it (test).
- **Answer keys and golden files:** never read by the pack layer (source scan test).

## 9. HTML fidelity — PASSED

- **Single source:** `pack.html` is rendered only from `pack.json`. Rendering the canonical JSON reproduces the same HTML (test).
- **Values:** every 2 dp figure in the visible text of all 9 HTML files exists in its `pack.json`.
- **Identifiers:** every `EXC-`, `GRP-`, `CAND-`, `MISS-`, `PACK-` and `RUN-` identifier shown exists in the pack.
- **Statuses and statements:** all status fields, the compliance statement and register statements are shown; no "RESOLVED" anywhere; every exception and group ID is shown.

**Not tested:** visual inspection in a browser. Only the HTML text and structure were verified.

## 10. Regression tests — 175, all passing (ResourceWarnings as errors)

| File | Tests |
| --- | ---: |
| test_audit_pack (new) | 40 |
| test_baseline | 30 |
| test_e1_e2 | 32 |
| test_hardening | 23 |
| test_output_verification | 8 |
| test_period_and_headers | 18 |
| test_period_decisions | 12 |
| test_scenario_datasets | 12 |

**`test_audit_pack` covers:**

- D1 registry (verbatim matrix phrases; unnamed codes labelled);
- D3 fields (5);
- Scenario 1 AC1–AC14 (11);
- all scenarios (3);
- validation-can-fail (10);
- publishing, immutability and failure handling (5);
- HTML fidelity (3).

## 11. Independent verification

| Tool | Result |
| --- | --- |
| `tools/verify_datasets.py` | Unchanged: baseline 9,416/9,416 OK; each scenario only its intended findings |
| `tools/verify_outputs.py` | 9 datasets, 36,763 output checks, 0 problems (the new `structured` column does not affect it) |
| Answer keys | All 9 MATCH |

## 12. Deterministic regeneration and immutability — PASSED

- **Regeneration:** two independent generations of all 9 packs gave **63 byte-identical files** (`pack.json`, `pack.html`, `processing/*.csv`), identical to the published `packs/`. Only generation records (timestamps) differ, by design (D5).
- **Repeat generation:** an existing pack is not modified; a second generation record is appended (test).
- **Altered content:** a tampered `pack.json` makes regeneration refuse with `ImmutabilityError` (test).
- **Failed generation:** publishes nothing (test).
- **Missing required file:** gives an INCOMPLETE pack, not a failed generation (test, IN-10 removed in a copy).

## 13. Remaining limitations

- **Pack size:** each pack is about 2.2 MB of JSON and 0.75 MB of HTML, because all 1,886 results and about 1,920 cited records are included. The HTML collapses large registers; pagination or filtering may be wanted later.
- **Failure-only checks:** BANK-CASH-LINK is shown as NO_FINDINGS (engine design). A future engine change could emit an explicit summary result; not done, to keep golden snapshots unchanged.
- **Control names:** the matrix descriptors are short (D1). No richer names were invented.
- **Monthly totals:** not included (D4).
- **Excluded by scope:** browser visual QA, PDF export, AI narrative, human review and approval workflow, configuration platform, deferred scenarios 3d and 5b.
- **Synthetic data:** all results describe illustrative synthetic data. They are not a compliance opinion and not production-ready.

## 14. Status

Audit-pack generation is implemented and validated for all nine datasets. Stopped here: AI narrative generation and human approval have not been started.
