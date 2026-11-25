# 02 — E1 and E2 Implementation Report

Implemented 30 Oct 2026 under decisions D-E1a, D-E1b, D-E2a and D-E2b, following `01_E1_E2_IMPLEMENTATION_ASSESSMENT.md`.

- **Deterministic only:** no AI in matching or correlation.
- **Nothing resolved, closed or attributed to a cause.**
- **No source evidence changed.**

## 1. Changed files

| File | Change |
| --- | --- |
| `uc042lib/validate.py` | **E1:** `timing_items()` and `timing_assessment()`; the C08 check records an evidence status; C11-BATCH-BANK adds an informational lag note. **E2:** `_correlate_exceptions()` after `_group_exceptions()`. **Exceptions:** evidence status, review status and group ID (category wording follows the evidence status). **Outputs:** `investigation_groups.csv` and `candidate_relationships.csv`. **Answer-key comparison:** also checks evidence statuses, groups and candidates. **Report:** new sections. |
| `uc042lib/trace.py` | Accepts `GRP-…` and `CAND-…` IDs; shows the new exception fields |
| `uc042lib/scenarios.py` | Answer-key metadata (D-E2b): `evidence_statuses`, `investigation_groups`, `candidate_relationships`; corrected `target_outcome` for SC2, SC3C, SC5A (corrected), SC5C and SC5D; S05 target added |
| `uc042lib/generate.py` | Baseline answer key gains the same three empty fields |
| `tests/test_e1_e2.py` | **New:** 23 regression tests |
| `tests/test_scenario_datasets.py` | One assertion changed. It encoded limitation E1 ("not evidenced"); it now asserts `TIMING_EVIDENCED` and "not resolved". |
| `uc042_dataset/*/answer_key.json` | Regenerated metadata (9 files) |
| `uc042_dataset/*/validation/*`, `VALIDATION_REPORT.md` | Regenerated outputs |
| **Unchanged** | All 180 source evidence files and manifests (verified by hash); golden snapshots; every control calculation and outcome |

## 2. Implementation decisions

### E1: timing evidence (D-E1a, D-E1b)

**Mechanism.** It reuses the existing reference link: a cash-book entry ↔ exactly one bank entry by reference, with the same account, currency and signed amount. An item counts as timing evidence only when **all** of these hold:

- one side is recorded by the 17:00 point and the other after it;
- the later side falls no later than the next business day (D1, via the existing `business_day_after`);
- the clearing evidence is usable and inside the period.

**Evidence status** on each non-zero C08 result, and rolled up to the exception:

| Status | Meaning |
| --- | --- |
| `TIMING_EVIDENCED` | Evidenced items fully explain the difference |
| `TIMING_PARTIAL` | They explain part of it; the residual is reported |
| `TIMING_UNVERIFIABLE` | A possible item exists, but the clearing evidence is missing or falls after 30 Sep |
| `NOT_EVIDENCED` | No qualifying item (including a clearing entry more than one business day later, a different amount, or a different reference) |

**What does not change:**

- **The outcome:** C08 stays FAIL whenever the difference exists (D-E1a).
- **The exception status:** stays `OPEN`.
- **The review status:** `AWAITING_HUMAN_REVIEW`.

Three separate fields keep evidence status, exception status and review status distinct.

**Batch delay (D-E1b).** C11-BATCH-BANK notes the delay in business days, as information only. Its outcome is unchanged and no new control was added.

### E2: investigation groups (D-E2a, D-E2b)

**A separate layer.** Exceptions keep their IDs, severities, root causes, affected counts and flags. Groups are connected components of evidence links:

- **L1 Reference:** shared batch or payment/bank reference on the same account.
- **L2 Persistence:** the same internal difference on consecutive reconciliation days.
- **L3 Lineage:** a failing record that is a direct input to another failing check:
    - a bank entry inside the 17:00 balance where a difference begins;
    - a client snapshot inside that day's requirement;
    - the requirement consumed by the internal difference.

**What a group cannot do:** groups carry `status` OPEN, `review_status` AWAITING_HUMAN_REVIEW and an empty `cause`, and they cite source rows for every link. They never close, resolve or attribute anything.

**Scenario 5a.** A **candidate relationship** (`CAND-SC5A-01`) is recorded with basis `DATE_AND_AMOUNT_COINCIDENCE`. It is labelled "UNVERIFIED — NOT EVIDENCE-BACKED; not an investigation group", is kept in a separate file, and is never a group.

## 3. Results (actual)

| Dataset | Exceptions (unchanged) | Evidence status | Investigation groups | Candidates | Answer key |
| --- | --- | --- | --- | --- | --- |
| Clean baseline | 0 | — | 0 | 0 | MATCH |
| SC2 timing | `EXC-SC2-01` (C08 FAIL +2,868.50, OPEN) | **`TIMING_EVIDENCED`**: `LE-GBP-0915-0005` / `BE-GBP-0916-T01`, cleared 16 Sep | 0 | 0 | MATCH |
| SC3B fee not itemised | `EXC-SC3B-01` | — | 0 | 0 | MATCH |
| SC3C £4.50 short | `EXC-SC3C-01/02/03` | **`NOT_EVIDENCED`** (unexplained) | **`GRP-SC3C-01`** (3; L1 reference `AQ-GBP-20260908` + L3 `BE-GBP-0908-AQ1`) | 0 | MATCH |
| S02 missing EUR | `EXC-S02-01` | — (C08 is insufficient, not a difference) | 0 | 0 | MATCH |
| SC5A missing transaction | `EXC-SC5A-01`, `-02` | — | **0** (no confirmed group) | **1, UNVERIFIED** | MATCH |
| SC5C refund twice | 17 | — | **`GRP-SC5C-01`** (17; L2 + L3 via `CBS-20260909-C0002-GBP`) | 0 | MATCH |
| SC5D closing mismatch | `EXC-SC5D-01/02/03` | — | **`GRP-SC5D-01`** (3; L3) | 0 | MATCH |
| S05 £812.40 | `EXC-S05-01`, `-02` | **`NOT_EVIDENCED`** (unexplained) | `GRP-S05-01` (2; L3 `BE-GBP-0917-X01`) | 0 | MATCH |

**Individual exceptions preserved.** For all 9 datasets, every control result (check, scope, outcome, computed, reported, root cause) and every exception (ID, severity, root cause, affected count, flags) is **identical to the golden snapshots**, so no golden file changed.

## 4. Validation

| Requirement | Result |
| --- | --- |
| All existing and new tests | **118 tests, all OK** (95 existing, one assertion updated as above; 23 new), with ResourceWarnings as errors |
| Independent dataset verification (`tools/verify_datasets.py`) | Unchanged findings: baseline 9,416/9,416 OK; each scenario flags only its intended records |
| Clean baseline remains clean | CLEAN; 0 exceptions, groups, candidates or evidence statuses |
| One-business-day timing scenario evidenced but open | SC2: C08 FAIL, `TIMING_EVIDENCED`, exception OPEN, `AWAITING_HUMAN_REVIEW`, no cause |
| £4.50 and £812.40 remain unexplained | `NOT_EVIDENCED` on all 17 and 10 days; notes still "unexplained bank-ledger difference" |
| 3c, 5c and 5d have evidence-supported groups | `GRP-SC3C-01`, `GRP-SC5C-01`, `GRP-SC5D-01`. Every link cites source rows; test E2-12 confirms the cited rows carry the claimed reference. |
| 5a has no confirmed group | No group; one candidate labelled UNVERIFIED |
| Exception records and IDs intact | Identical to golden in all 9 datasets |
| Deterministic regeneration | Two full regenerations plus validations: **278 files byte-identical**, and identical to the delivered datasets |
| Source evidence unchanged | All 180 evidence files and manifests byte-identical to before this task |

### New regression tests (`tests/test_e1_e2.py`)

| E1 | E2 |
| --- | --- |
| E1-1 SC2 evidenced, still FAIL and OPEN | E2-1 SC3C group (L1 + L3) |
| E1-2 £4.50 and £812.40 not evidenced | E2-2 SC5C group of 17 (L2 + L3) |
| E1-3 clearing 2 business days later → not evidenced | E2-3 SC5D group of 3 (L3) |
| E1-4 different amount → not evidenced | E2-4 SC5A: no group; one UNVERIFIED candidate |
| E1-5 different reference, same amount → not evidenced | E2-5 S05 group open, no cause |
| E1-6 partial → residual 100.00 reported | E2-6 no groups where nothing links |
| E1-7 clearing statement missing → unverifiable | E2-7 exceptions identical to golden |
| E1-8 posting on 30 Sep → unverifiable | E2-8 groups never set a cause or close; links cite rows |
| E1-9 nothing resolved or closed anywhere | E2-9 same day on two accounts → not grouped |
| E1-10 batch delay informational, PASS kept | E2-10 equal amounts without reference or lineage → not grouped |
| E1-11 baseline has no timing items | E2-11 deterministic group IDs |
| | E2-12 cited link rows carry the claimed reference |

## 5. Remaining limitations

- **Scenario 5a** stays two exceptions plus an unverified candidate. This is an evidence limit, not an engine defect: no record links the missing transaction to C0002.
- **The timing window** uses `business_day_after` (UK weekdays minus a synthetic holiday list). It agrees with the September reconciliation calendar; it is not yet driven by case configuration.
- **L3 lineage rules are specific** (balance components, snapshot to requirement, requirement to internal difference). New failure types need explicit rules before they can be grouped; until then they stay ungrouped, which is the safe default.
- **Output formats grew.** `exceptions.csv` gained four columns and `control_results.csv` one. Two new output files were added. Readers that rely on column names are unaffected.
- **Not built (out of scope):** the audit-pack generator, AI investigation, the human review workflow, the configuration platform, and the deferred scenarios 3d and 5b.

## 6. Status

E1 and E2 are implemented and validated. Stopped here for review. Audit-pack generation and AI investigation have not been started.
