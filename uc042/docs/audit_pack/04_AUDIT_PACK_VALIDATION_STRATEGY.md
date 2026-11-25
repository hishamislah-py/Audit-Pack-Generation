# 04 — Audit Pack Validation Strategy

Status: **design for review.** Nothing is implemented.

Validation runs inside generation (step 10 of 02: any error means FAILED and nothing is published) and again in the test suite.

**Expectations come from:**

- the **same run's engine outputs** (fidelity);
- the existing **answer keys** (tests only, never read by the pack layer);
- the independent verifiers `tools/verify_datasets.py` and `tools/verify_outputs.py`, which are **[C]** existing and reused.

## 1. Validation levels

| ID | Level | Checks | Failure means |
| --- | --- | --- | --- |
| V1 | Schema | `pack.json` validates against the contract's JSON schema: required sections present (empty registers as explicit empty lists plus a statement); types; money as 2 dp strings; ISO dates | FAILED |
| V2 | Reference resolution | Every `evidence_id` resolves (file ID → manifest; `file_id:key` → a source row with that primary key at the stated line); every citation resolves (reuses O1 logic); every `result_id`, exception ID, group ID and candidate ID referenced anywhere exists in the pack | FAILED |
| V3 | Value fidelity | Every amount, outcome, status, evidence status, note and category in the pack is **byte-identical** to the same run's engine field, or to the cited source field (for copied source values such as opening positions and batch headers). No value may originate in the pack layer. | FAILED |
| V4 | Count reconciliation | Summary counts equal register contents; register contents equal engine collections (results 1:1; exceptions 1:1; groups 1:1; candidates 1:1); `affected_result_ids` equal the results with that root cause | FAILED |
| V5 | Status semantics | Separate status fields present (no blended status). No exception, group or candidate shows resolved or closed; no `cause` set. `NOT_EVIDENCED` items never described as explained; `TIMING_EVIDENCED` items say "awaiting human confirmation" and "not resolved". Candidates keep the UNVERIFIED label and appear only in the candidate list. Groups carry the "does not establish a cause" statement. (Reuses O3/O4 logic.) | FAILED |
| V6 | Completeness | Every check type in `DEPENDS` plus the always-run checks is present; every engine result appears exactly once; every INSUFFICIENT_EVIDENCE result is referenced by a missing-evidence item; no missing value is rendered as a number | FAILED |
| V7 | Determinism | Two generations → identical `pack.json` and `pack_id` (tests) | Test failure |
| V8 | Provenance and immutability | Manifest hashes match the files; processing-output hashes match the run's CSVs; fingerprints present; writing to an existing `pack_id` with a different hash is refused | FAILED / test failure |
| V9 | HTML fidelity | Every figure, ID and status in `pack.html` appears in `pack.json`; the HTML has no data source other than `pack.json` (tests parse the HTML) | Test failure |
| V10 | Independent cross-check | Run `verify_outputs.py` (O1–O8) on the run's outputs, and `verify_datasets.py` on the inputs; pack summaries agree with their findings | Test failure |

**Negative tests (V1–V9 must be able to fail).** Generate the pack from tampered copies and assert FAILED:

- a changed amount in an engine field after assembly;
- a broken citation;
- a removed result;
- an exception marked RESOLVED;
- an unexplained difference described as explained;
- a candidate inserted into the group list;
- a missing value shown as `0.00`;
- an overwrite attempt.

## 2. Scenario coverage: future compatibility, with the same contract and no outcome changes

Expected pack content is taken from the verified engine results and answer keys. **No scenario outcome or mutation changes.**

| Scenario | Evidence completeness | Control summary | Exceptions (register G) | Groups / candidates (H) | Missing evidence (I) | Specific pack content |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Clean | COMPLETE | ALL_PASSED_OR_NOT_APPLICABLE | none | none / none | none | See 03 |
| 2 Timing | COMPLETE | FAILURES_PRESENT | `EXC-SC2-01` Critical, +2868.50, **TIMING_EVIDENCED**, OPEN, awaiting human confirmation | none / none | none | Settlement register `SB-GBP-20260915`: bank entry `BE-GBP-0916-T01`, booked 1 business day late, informational (needs D3 structured lag). External table: 15 Sep difference 2868.50 with evidence status. |
| 3a Supported fee | (baseline) | — | — | — | — | Settlement register `AQ-GBP-20260908`: gross 10000.00, fees 45.50, net 9954.50, lines PASS, bank PASS, top-up PASS |
| 3b Fee not itemised | COMPLETE | FAILURES_PRESENT | `EXC-SC3B-01` High | none / none | none | Batch shows fees 45.50 (header) with C11-BATCH-ARITH FAIL. **No fee breakdown shown or invented.** |
| 3c £4.50 short | COMPLETE | FAILURES_PRESENT | `EXC-SC3C-01` Critical −4.50 **NOT_EVIDENCED**; `-02`, `-03` High | `GRP-SC3C-01` (L1 + L3) / none | none | External table −4.50 × 17 days; group with its stated link basis and the no-cause statement |
| 4 Missing EUR | **INCOMPLETE** | FAILURES_PRESENT (INSUFFICIENT_EVIDENCE) | `EXC-S02-01` Critical | none / none | **1 item:** `MISSING_BANK_EVIDENCE\|SGA-EUR-01\|2026-09-15`, 13 affected results, "not available" | External 15 Sep EUR: bank balance "not available"; reported balance shown as unverified |
| 5a Missing £443.55 | COMPLETE | FAILURES_PRESENT | `EXC-SC5A-01`, `-02` High (kept separate) | **none** / `CAND-SC5A-01` with UNVERIFIED label, **in the candidate list only** | none | No statement that the two share a cause |
| 5c Refund twice | COMPLETE | FAILURES_PRESENT | 17 (16 Critical, 1 High), all kept | `GRP-SC5C-01` (L2 + L3) / none | none | Internal table −60.00 from 9 Sep |
| 5d Closing −£250 | COMPLETE | FAILURES_PRESENT | `EXC-SC5D-01/02/03` | `GRP-SC5D-01` (L3) / none | none | 30 Sep GBP requirement 395594.86 (recomputed) against 395844.86 (reported), both shown as the engine reports them |
| 6 £812.40 | COMPLETE | FAILURES_PRESENT | `EXC-S05-01` Critical −812.40 **NOT_EVIDENCED**; `EXC-S05-02` High | `GRP-S05-01` (L3) / none | none | No cause; bank entry `BE-GBP-0917-X01` (`SETTLE 0417`) cited; "unexplained" wording retained |

**Test plan per dataset:**

- generate the pack;
- V1–V10 pass;
- the summary fields equal the row above;
- registers equal the engine collections;
- `pack.json` is reproducible.

## 3. Test assets (proposed)

| Test file | Content |
| --- | --- |
| `tests/test_pack_contract.py` | V1, V4, V6 on all 9 datasets |
| `tests/test_pack_fidelity.py` | V2, V3, V5 (all datasets) and the negative tampering tests |
| `tests/test_pack_scenario1.py` | Acceptance criteria AC1–AC14 (03) |
| `tests/test_pack_scenarios.py` | The section 2 table for scenarios 2–6 |
| `tests/test_pack_determinism.py` | V7, V8 (two generations; write-once refusal) |
| `tests/test_pack_html.py` | V9 |

The existing 135 tests, golden snapshots, answer keys and both verifiers stay unchanged and must keep passing.

## 4. What validation cannot establish

Pack validation proves that the pack faithfully represents the synthetic evidence and the engine results. It does **not** establish:

- operational correctness of real Moorwand processes;
- regulatory compliance;
- the cause of any exception.

The pack states this explicitly (03 §3).
