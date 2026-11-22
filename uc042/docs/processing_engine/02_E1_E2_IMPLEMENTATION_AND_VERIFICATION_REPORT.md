# 02 — E1 and E2 Implementation and Verification Report

Date: 30 Oct 2026.

**Scope:** the deterministic processing and evidence-management foundation of the UC-042 POC. It covers synthetic data only; there is no production-readiness claim.

**Status labels used in this report:**

| Label | Meaning |
| --- | --- |
| **VERIFIED – PASSED** | Checked; no problem |
| **VERIFIED – EXPECTED SCENARIO EXCEPTIONS** | Checked; only the scenario's intended anomalies appear |
| **FAILED** | — |
| **NOT TESTED** | — |
| **NOT APPLICABLE** | — |

## 1. Executive summary

- **E1 and E2 are implemented and verified.** They were implemented in the preceding step (`02_E1_E2_IMPLEMENTATION_REPORT.md`) and verified against the actual code in this one; nothing needed re-implementing. This step added 17 regression tests (9 E1 cases requested by this brief, 8 output-verification tests) and a new processing-output verifier.
- **All nine datasets** were verified independently at four levels: file and schema, financial, provenance, and scenario isolation. This covered 171 input files and 17,561 CSV rows: 84,732 independent dataset checks plus 36,763 output checks. **Results:** the clean baseline passes everything; every other dataset shows **only its intended anomalies**; the output checks found **no problems**.
- **Change control:**
    - 135 tests, all passing.
    - Two complete regenerations, including validation outputs: 278 byte-identical files, identical to the recorded before-state.
    - No source dataset, golden snapshot or engine file changed in this step.
- **No frontend exists that reads engine output.** Presentation in a UI is **NOT TESTED** (§10).

## 2. Files inspected

| Area | Files |
| --- | --- |
| Engine | `uc042lib/validate.py` (checks, `business_day_after`, `timing_items`, `timing_assessment`, `_group_exceptions`, `_correlate_exceptions`, outputs, answer-key comparison), `structure.py`, `schema.py`, `money.py`, `prepare.py`, `trace.py` |
| Data generation | `uc042lib/generate.py`, `uc042lib/scenarios.py` |
| Verification | `tools/verify_datasets.py` |
| Datasets | `uc042_dataset/` (9 dataset folders, `scenario_index.json`, `SCENARIO_INDEX.md`), including answer keys, manifests, mutations and validation outputs |
| Tests | `tests/` (9 test files) and `tests/golden/` (9 snapshots + README) |
| Documentation | `docs/processing_engine/01_…ASSESSMENT.md`, `02_E1_E2_IMPLEMENTATION_REPORT.md`, `docs/dataset_gap_closure/06_…REPORT.md`, README |
| UI | `/outputs/audit-pack-workspace.html`: an earlier prototype with invented demo data. It does not read engine output (0 references to datasets, results or `fetch`). |

**Before-state recorded** in `verification/before_state.json`: hashes of 17 code files, 278 dataset files and 10 golden files; test results (118 OK); exceptions, groups, candidates and evidence statuses per dataset; independent-verifier findings.

## 3. Files changed in this step

| File | Change |
| --- | --- |
| `tests/test_e1_e2.py` | **Added cases:** incorrect account, incorrect currency, missing bank entry (evidence present), multiple possible matches, same-date match, Friday→Monday within one business day, Friday→Tuesday outside, business-day helper boundaries, timing items only where the scenario put them |
| `tests/test_output_verification.py` | **New:** schema-contract test (all 9 datasets), output-verification test, and 6 tests proving the verifier detects tampering |
| `tools/verify_outputs.py` | **New:** processing-output verifier (§10) |
| `README.md` | Test count and the new command |
| `docs/processing_engine/02_E1_E2_IMPLEMENTATION_AND_VERIFICATION_REPORT.md`, `verification/*.json` | This report and its evidence |
| **Unchanged in this step** | All engine code (`uc042lib/*`), all 278 dataset files (evidence, manifests, answer keys, validation outputs), all golden snapshots, `tools/verify_datasets.py` |

The E1/E2 engine changes themselves (`validate.py`, `trace.py`, `scenarios.py`, `generate.py`) were made in the preceding step and are listed in `02_E1_E2_IMPLEMENTATION_REPORT.md` §1.

## 4. E1: timing evidence (verified against the code)

| Aspect | Implementation | Verified |
| --- | --- | --- |
| Link | Cash-book entry ↔ exactly **one** bank entry by reference on the **same account**, same currency and same signed amount; the existing reference architecture | Tests: wrong account, wrong currency, wrong amount, wrong reference, two candidate entries → `NOT_EVIDENCED` |
| Window | Later side booked no later than `business_day_after(d)`: UK weekdays minus a synthetic holiday list. Inspected: Fri 11 Sep → Mon 14 Sep; Sat → Mon; Fri 28 Aug → Tue 1 Sep (31 Aug holiday); 30 Sep → 1 Oct. No separate tolerance. | Tests: Fri→Mon evidenced; Fri→Tue and two business days later not evidenced |
| Statuses | `TIMING_EVIDENCED`, `TIMING_PARTIAL`, `NOT_EVIDENCED`, `TIMING_UNVERIFIABLE` (the project's names for evidenced / partly_evidenced / not_evidenced / unverifiable) | Tests: partial (residual 100.00), unverifiable (missing clearing statement; 30 Sep posting) |
| Business rule | C08 stays FAIL while the difference exists. The exception stays `OPEN` with `review_status` `AWAITING_HUMAN_REVIEW`. The note says "awaiting human confirmation; not resolved". | Tests E1-1, E1-9; output check O4 |
| Batch delay | C11-BATCH-BANK note only; outcome unchanged; no new control | Test E1-10 |
| No false positives | Timing items appear only for SC2's `BE-GBP-0916-T01`, in all 9 datasets. Same-date settlements produce no items. | Tests E1-11, E1-12, same-date |

## 5. E2: investigation groups (verified against the code)

**A separate layer.** `_correlate_exceptions()` runs after `_group_exceptions()`. It never edits an exception's ID, control, outcome, evidence, description or review status; it only sets `investigation_group_id`.

**Link rules** (the relationship basis is stored on every link, with source-row citations):

| Rule | Meaning |
| --- | --- |
| L1 REFERENCE | A shared batch or payment/bank reference on the same account |
| L2 PERSISTENCE | The same internal difference on consecutive reconciliation days |
| L3 LINEAGE | A failing record is a direct input to another failing calculation |

**Group fields:** `group_id`, `exception_ids`, `primary_exception_id`, `size`, `link_types`, `links`, `status` (`OPEN`), `review_status` (`AWAITING_HUMAN_REVIEW`), `cause` (always empty), `correlation_version`. Timestamps are not part of the project's conventions, so none were added.

**Scenario 5a:** no group. One candidate `CAND-SC5A-01` (basis `DATE_AND_AMOUNT_COINCIDENCE`), labelled "UNVERIFIED — NOT EVIDENCE-BACKED; not an investigation group", is kept in a separate file.

## 6. Data-integrity verification: all 9 datasets — VERIFIED – PASSED

| Check | Result |
| --- | --- |
| Expected files | 14 CSV + 5 PDF in every dataset (171 files). Manifest: 19 entries; IN-18 and IN-19 OPTIONAL, all others REQUIRED. |
| Headers, mandatory fields, types | Exact schema headers; no blank mandatory field; every value valid for its type and enum (schema-contract test, all 17,561 rows) |
| Dates and timestamps | 23,337 dated values; all in September 2026 except the two documented 31 Aug opening record types; all timestamps carry an offset |
| Money | Every amount is a 2 dp decimal string; no `float()` anywhere in the engine or tools |
| Currencies | 6,781 account-linked records match their account currency; nothing mixes GBP and EUR |
| IDs | 17,561 primary keys, no duplicates |
| References | All 8 reference types resolve, except the intended break in SC5A (line → removed `TX-0915-00009`) |
| PDFs | All 45 are genuine PDFs |

## 7. Financial validation (independent verifier) — VERIFIED

| Dataset | Result | Non-OK findings (all intended) |
| --- | --- | --- |
| Clean baseline | **PASSED** (9,416 / 9,416) | — |
| SC2 | EXPECTED EXCEPTIONS | Bank − ledger 15 Sep only (+2,868.50, fully explained by a timing item within one business day); batch booked 1 day after settlement |
| SC3B | EXPECTED EXCEPTIONS | `AQ-GBP-20260908`: FEE lines 0.00 against fees 45.50 |
| SC3C | EXPECTED EXCEPTIONS | Bank − ledger −4.50 × 17 days, not timing-evidenced; batch net 9,954.50 against 9,950.00 banked; cash link |
| S02 | EXPECTED EXCEPTIONS | Only INSUFFICIENT (EUR 15 Sep confirmation, statement and 4 entries missing); no balance substituted |
| SC5A | EXPECTED EXCEPTIONS | Line → missing `TX-0915-00009`; C0002 15 Sep roll-forward −443.55 |
| SC5C | EXPECTED EXCEPTIONS | C0002 9 Sep roll-forward +60.00; internal shortfall −60.00 × 16 days |
| SC5D | EXPECTED EXCEPTIONS | C0003 30 Sep roll-forward −250.00; requirement 395,594.86 against reported 395,844.86 |
| S05 | EXPECTED EXCEPTIONS | Bank − ledger −812.40 × 10 days, not timing-evidenced; `SETTLE 0417` has no cash-book counterpart |

**Covered in every dataset:**

- cash-book opening and roll-forward;
- statement arithmetic and continuity;
- 17:00 confirmations;
- client opening (31 Aug: clients = cash book = bank opening, both currencies) and roll-forward (264 pairs, including 1 Sep);
- requirement, item A, internal and external reconciliation;
- batch arithmetic and gross-to-net;
- fee lines and top-ups;
- refunds;
- unallocated receipts;
- currency separation;
- period boundaries.

## 8. Evidence and provenance — VERIFIED – PASSED

- **Citations:** every citation in results, exceptions, groups and candidates resolves to an existing file and line (output check O1, all datasets).
- **Exceptions:** every exception has cited source rows, and its records exist in that dataset (O6).
- **Missing evidence:** shown as missing. S02 shows INSUFFICIENT, never a substituted balance.
- **Mutations:** documented in `mutations.json` and reproducible. Tests prove the diff equals the mutation list.
- **Baseline:** uncontaminated; its manifest hash is recorded in every `scenario.json`.
- **Opening snapshot:** the 31 Aug snapshot is present (12 rows), and all 12 "1 Sep" roll-forwards PASS.

### Scenario isolation (independent record-level diff against the baseline)

| Dataset | Changed records | Intended? |
| --- | --- | --- |
| SC2 | entries +1 −1; EOD headers ~2; confirmations ~1; external records ~1; log +1 | Yes (T1) |
| SC3B | settlement lines −2 | Yes (F1) |
| SC3C | entries ~1; EOD ~17; confirmations ~17; external ~17 | Yes (F2) |
| S02 | confirmations −1; EOD −1; entries −4 | Yes |
| SC5A | transactions −1 | Yes (C1) |
| SC5C | snapshots ~16; internal records ~16 | Yes (C2) |
| SC5D | snapshots ~1 | Yes (C3) |
| S05 | entries +1; EOD ~10; confirmations ~10; external ~10 | Yes |

**No unintended change in any dataset;** all other records are identical to the baseline. The financial verifier shows no anomaly beyond the intended ones (§7).

## 9. Scenario-by-scenario results

| # | Scenario | Exceptions (unchanged IDs) | Evidence status | Group / candidate | Answer key | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Clean baseline | none | — | — | MATCH | VERIFIED – PASSED |
| 2 | Timing £2,868.50 | `EXC-SC2-01` FAIL, OPEN | `TIMING_EVIDENCED`, awaiting human confirmation | — | MATCH | VERIFIED – EXPECTED |
| 3a | Supported fee (baseline `AQ-GBP-20260908`) | none | — | — | MATCH | VERIFIED – PASSED |
| 3b | Fee not itemised | `EXC-SC3B-01` | — | — | MATCH | VERIFIED – EXPECTED (no fee breakdown invented) |
| 3c | £4.50 short | `EXC-SC3C-01/02/03` | `NOT_EVIDENCED` | `GRP-SC3C-01` (L1 + L3) | MATCH | VERIFIED – EXPECTED |
| 4 | Missing EUR | `EXC-S02-01` | — | — | MATCH | VERIFIED – EXPECTED (nothing invented) |
| 5a | Missing £443.55 | `EXC-SC5A-01`, `-02` | — | **No group**; `CAND-SC5A-01` UNVERIFIED | MATCH | VERIFIED – EXPECTED |
| 5c | Refund twice | 17 kept | — | `GRP-SC5C-01` (L2 + L3) | MATCH | VERIFIED – EXPECTED |
| 5d | Closing £250 low | `EXC-SC5D-01/02/03` | — | `GRP-SC5D-01` (L3) | MATCH | VERIFIED – EXPECTED |
| 6 | £812.40 | `EXC-S05-01`, `-02` | `NOT_EVIDENCED` | `GRP-S05-01` (L3) | MATCH | VERIFIED – EXPECTED (no cause) |

## 10. Processing output and presentation verification

`tools/verify_outputs.py` reads each dataset's generated outputs and the `trace` output. It checks them against the source CSVs using only the standalone helpers in `verify_datasets.py`, not the engine's calculations.

**36,763 checks; 0 problems.**

| # | Requirement from the brief | Output check | Result |
| --- | --- | --- | --- |
| 1 | Incorrect amounts or currencies | O2: every C04 requirement, C05 item A, C08 bank − ledger and C11 net / bank amount is recomputed from source and compared with the displayed value. O3: exception amount and currency against results and account. | PASSED |
| 2 | Incorrect dates | O3: exception first/last dates equal the scopes of their results | PASSED |
| 3–4 | Missing or broken evidence references | O1: every citation resolves (file and line range) | PASSED |
| 5–6 | Duplicate exceptions; incorrect counts | O3: unique IDs, one per root cause, affected counts, ID prefix per scenario; counts equal the answer keys | PASSED |
| 7, 9 | Incorrect status labels; resolved without approval | O3: every exception OPEN, AWAITING_HUMAN_REVIEW, no cause | PASSED |
| 8 | Misleading group descriptions | O4: groups OPEN, no cause; candidates labelled UNVERIFIED / NOT EVIDENCE-BACKED | PASSED |
| 10–11 | Unexplained shown as explained; timing shown as resolved | O4: NOT_EVIDENCED stays "Unexplained"; TIMING_EVIDENCED says "awaiting human confirmation" and "not resolved" | PASSED |
| 12 | Missing records shown as valid | §6–7 (S02 INSUFFICIENT; no substituted balances) | PASSED |
| 13 | Data from another scenario | O6: every record ID shown exists in that dataset | PASSED |
| 14 | Trace against summary consistency | O7: report totals, exception IDs, group IDs and answer-key line equal the CSVs. O8: trace's affected-result counts, evidence status and group members equal the CSVs. | PASSED |

**The verifier is proven able to fail.** Six tampering tests on copies are each detected:

- a wrong amount;
- an exception marked RESOLVED;
- "unexplained" rewritten as "explained by timing";
- a record from another scenario;
- a broken citation;
- a report total mismatch.

**Frontend presentation: NOT TESTED.** No UI renders engine output. The HTML prototype uses invented demo data and is not connected to the engine. Only generated files (CSV, Markdown report) and command-line trace output were verified.

## 11. Golden snapshots and answer keys

**Golden snapshots:** **unchanged** in this step and in the preceding E1/E2 step. All 10 hashes are identical to the before-state. Every control result and exception in all 9 datasets equals its golden snapshot.

**Answer keys:** changed in the preceding step (D-E2b); unchanged in this step. In all 9 keys, `non_passing_results` and `exceptions` are **unchanged** (proven: they still match unchanged golden results). Added or changed metadata:

| Key | Previous value | New value | Reason / evidence | Expected? |
| --- | --- | --- | --- | --- |
| All 9 | No `evidence_statuses`, `investigation_groups` or `candidate_relationships` fields | Fields present (empty where nothing applies) | E1/E2 outputs must be checked; the validator now compares them | Yes |
| SC2 | `target_outcome`: timing "evidences" the difference (described as an aim); `engine_limitations`: two E1 items | `evidence_statuses` `{"EXC-SC2-01": "TIMING_EVIDENCED"}`; target restated as achieved; limitations `[]` | E1 implemented; test E1-1 | Yes |
| SC3C | Target "One exception …"; limitation "E2: split into 3 exceptions" | Group `[EXC-SC3C-01, -02, -03]`; `{"EXC-SC3C-01": "NOT_EVIDENCED"}`; target "three individual exceptions kept, linked in one investigation group"; limitations `[]` | E2 keeps exceptions and adds groups (D-E2a/b); test E2-1 | Yes |
| SC5A | Target "One exception … (linked by reference, not by amount)"; limitation "E2: split into 2" | Groups `[]`; candidate `[EXC-SC5A-01, -02]`; target "two separate exceptions and NO confirmed investigation group …"; limitation "evidence limitation, not an engine defect" | **Correction:** no record links the missing transaction to C0002 (assessment §5.3; D-E2a); test E2-4 | Yes |
| SC5C | Target "One Critical exception …"; limitation "E2: split into 17" | One group of all 17; target updated; limitations `[]` | Test E2-2 | Yes |
| SC5D | Target "One exception …"; limitation "E2: split into 3" | Group of 3; target updated; limitations `[]` | Test E2-3 | Yes |
| S05 | No target text | Group `[EXC-S05-01, -02]`; `{"EXC-S05-01": "NOT_EVIDENCED"}`; target "unresolved; no cause set; no resolving evidence added" | Test E2-5 | Yes |
| S02, SC3B, baseline | — | Empty group, candidate and status fields | — | Yes |

## 12. Test results — VERIFIED – PASSED

**135 tests, all passing,** with ResourceWarnings treated as errors.

| File | Tests | Covers |
| --- | ---: | --- |
| `test_baseline.py` | 30 | Sign rules, determinism, clean pass, checks can fail, regressions, S02/S05 |
| `test_hardening.py` | 23 | Malformed rows, missing evidence, case preparation |
| `test_period_and_headers.py` | 18 | Period rules, header diagnosis |
| `test_period_decisions.py` | 12 | A1/A2 conventions |
| `test_scenario_datasets.py` | 12 | Scenario builds, isolation, independent verifier |
| `test_e1_e2.py` | 32 | 9 new: account, currency, missing, ambiguous, same date, weekend, helper, false positives |
| `test_output_verification.py` | 8 | New: contract, output verifier, 6 tampering cases |

Of the 135, 118 were existing before this step and passed unchanged; 17 are new.

## 13. Independent verification

| Tool | Result |
| --- | --- |
| `tools/verify_datasets.py` (no shared code with the engine) | 84,732 checks; baseline all OK; each scenario only its intended findings (§7). Identical to the before-state. |
| `tools/verify_outputs.py` | 36,763 checks; 0 problems (§10) |
| `trace` | Run for every exception and group (37 invocations); consistent with the CSV outputs |

## 14. Deterministic regeneration — VERIFIED – PASSED

Two complete regenerations (generator, scenario builder and validator for all 9 datasets) produced **278 files, byte-identical between runs and identical to the before-state**. That covers evidence, manifests, mutations, answer keys, scenario metadata, control results, exceptions, groups, candidates and reports.

## 15. Remaining limitations

- **Scenario 5a:** the relationship between its two exceptions cannot be evidenced; it is recorded as an UNVERIFIED candidate only.
- **Timing window:** uses `business_day_after` with a synthetic UK holiday list, not case configuration. It agrees with the September calendar.
- **Lineage rules:** limited to the three defined patterns; new failure types remain ungrouped until a rule is added.
- **UI:** no presentation layer reads engine output, so on-screen presentation is **NOT TESTED**.
- **Synthetic data:** all checks prove internal consistency of illustrative synthetic data (D6), not operational correctness or regulatory compliance.

## 16. Not built

- Audit-pack generator.
- AI investigation agent.
- Human approval workflow.
- Configuration platform.
- Deferred scenarios 3d and 5b.
- Any application UI connected to the engine.

## Milestone assessment

For the agreed POC scope, the **deterministic evidence-detection and exception-management foundation is complete**. Controls, timing evidence, exceptions, investigation groups, unverified candidates, provenance and traceability are implemented and verified across all nine datasets, with deterministic outputs. The next stage, audit-pack generation and AI investigation, has not been started.
