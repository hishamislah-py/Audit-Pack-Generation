# 03 — Scenario 1 Acceptance Criteria: Clean Audit Pack

Status: **design for review.** Every expected value below is taken from the **existing verified engine outputs** of `uc042_dataset/set_01_clean_baseline`, read on 30 Oct 2026. The pack must reproduce these values, never recompute them.

**A clean pack is a successful, complete, non-empty output.** It differs from an incomplete pack only in its status fields and registers (section 4), never by missing sections.

## 1. Acceptance criteria

| # | Criterion | Expected value (from existing outputs) | How verified |
| --- | --- | --- | --- |
| AC1 | Reporting period | `PER-2026-09`, 2026-09-01 to 2026-09-30; **22** reconciliation days | Equals `schema` and IN-01 |
| AC2 | Currency and account context | Currency scope GBP, EUR. Safeguarding accounts `SGA-GBP-01` (GBP), `SGA-EUR-01` (EUR); own-funds `OWN-GBP-01`, `OWN-EUR-01`. Pool `POOL-EMONEY`. Entity `SYN-EMI-001` (synthetic configuration, D2). | Equals IN-02 rows (cited) |
| AC3 | All applicable control results | **32** check types, **1,886** results, every one present exactly once (`result_id` = `check_id\|scope`) | Count and set equality with the engine run |
| AC4 | Outcomes shown | **1,886 PASS** (including C06 × 44 and C08 × 44: "no difference to resolve" / "bank equals ledger"), **0 NOT_APPLICABLE**, **0 FAIL**, **0 INSUFFICIENT_EVIDENCE**. Per check (see list below). Approved 17 Nov 2026: a reconciled zero difference is **PASS**; packs published before that date record it as NOT_APPLICABLE and are kept unchanged. (Before then: 1,798 PASS and 88 NOT_APPLICABLE.) | Per-check counts equal the engine |
| AC5 | Reconciliation summaries | 44 currency-days (requirement, item A, resource, difference) and 44 account-days (bank, ledger, difference). **30 Sep:** GBP requirement **395844.86**, item A **395844.86**, bank **395844.86**, ledger **395844.86**, difference **0.00**; EUR requirement **118555.00**, bank and ledger **118555.00**, difference **0.00**. Opening positions (cited source rows): `LE-GBP-0831-0000` 250000.00; `LE-EUR-0831-0000` 80000.00; 12 `CBS-20260831-*` client rows. | Value fidelity: each figure equals its engine field or source field exactly |
| AC6 | Evidence references | All 19 input files in the file register (SHA-256 from the manifest, availability PRESENT). **1,920** cited source rows in the record register, each resolving to `file#line` and its primary key. | Reference resolution (04, V2) |
| AC7 | Provenance | Manifest hashes; dataset `set_01_clean_baseline` (scenario ID `S01`); engine and configuration fingerprints; processing-output hashes of the same run | Audit-trail completeness (04, V8) |
| AC8 | Zero open exceptions | Exception register: "No exceptions were raised for this period", with supporting counts (1,886 results, 0 FAIL, 0 INSUFFICIENT_EVIDENCE) | Equals `v.exceptions == []` |
| AC9 | Zero investigation groups | Group register "none"; candidate register "none" | Equals `v.groups == []`, `v.candidates == []` |
| AC10 | Valid evidence register | Every file and record entry resolves; no orphan; no fabricated ID | V2 |
| AC11 | Cross-references | Every `result_id`, `evidence_id`, exception ID and group ID referenced anywhere in the pack exists in the pack | V2 |
| AC12 | Matches the engine | Every outcome, amount, status and note equals the same run's engine output | V3 (value fidelity) |
| AC13 | Reproducible | Two generations from identical inputs, engine and configuration give identical `pack.json` and `pack_id`; only `generated_at` in `generation_record.json` differs | V7 |
| AC14 | Non-empty and useful | Contains metadata, executive summary, reconciliation tables, control register with results, evidence register, settlement register (88 batches: C11-BATCH-ARITH PASS × 88, C11-BATCH-BANK PASS × 88, FUND-TOPUP PASS × 44 for acquirer batches), and explicit "none" statements for the empty registers | Section presence and minimum-content checks |

**Expected per-check counts (AC4):**

| Group of checks | Counts |
| --- | --- |
| Schema and documents | V01-SCHEMA 14 PASS · V01-PDF 5 PASS |
| Policy and point | C03-POLICY 1 · C03-POINT 3 |
| Coverage | C01-COVER 44 · C14-COVER 484 · C07-COVER 44 |
| Bank statements | DQ23-STATEMENT 88 · DQ22-CONTINUITY 86 · BC-VS-EOD 44 · CASH-BANK-LINK 222 |
| Internal and external reconciliation | C04-REQUIREMENT 44 · C05-RESOURCE 44 · **C06-DIFFERENCE 44 PASS** · C07-BANK-EVIDENCE 44 · RC2-LEDGER 44 · **C08-DIFFERENCE 44 PASS** (zero differences; NOT_APPLICABLE in packs published before 17 Nov 2026) |
| Settlement | C11-BATCH-ARITH 88 · C11-BATCH-BANK 88 · C11-TXN-LINE 1 · C11-BANK-ENTRY 1 · FUND-TOPUP 44 |
| Allocation and refunds | RC4-DIRECT 90 · C09-ALLOCATION 2 · C12-REFUND 2 |
| Client balances and currency | CBAL-NONNEG 1 · CBAL-ROLLFWD 264 · C13-CURRENCY 1 |
| Designation, checklist and log | C10-DESIGNATION 2 · C16-GOVERNANCE 1 · C16-RETURN 1 · DISC-LOG 1 |

All are PASS unless marked otherwise.

## 2. Required status fields for the clean pack

| Field | Expected |
| --- | --- |
| `generation_status` | `GENERATED` |
| `evidence_completeness` | `COMPLETE` |
| `control_outcomes.summary` | `ALL_PASSED_OR_NOT_APPLICABLE` |
| `exceptions.total` / `exception_review` | `0` / `NONE` |
| `investigation_groups` / `candidate_relationships` | `0` / `0` |
| `missing_evidence_items` | `0` |
| `engine_case_status` | `CLEAN` |
| `pack_review_status` | `NOT_REVIEWED` (future approval capability) |

## 3. Required statements

- **Synthetic notice (D6):** "Illustrative synthetic data; not confirmed Moorwand practice."
- **Limitations,** copied from existing documented limitations:
    - items B–D taken as reported;
    - D+1 not performed;
    - PDF key details parsed from a fixed layout without human confirmation;
    - results show the internal consistency of synthetic data, not compliance.
- **Not-a-compliance-opinion statement.**

## 4. Complete clean pack versus incomplete pack

| Aspect | Complete clean pack (S01) | Incomplete pack (for example S02) |
| --- | --- | --- |
| `generation_status` | GENERATED | GENERATED (the pack is valid; its content records the gap) |
| `evidence_completeness` | COMPLETE | INCOMPLETE |
| Missing evidence register | "None" | Lists items, for example `MISSING_BANK_EVIDENCE\|SGA-EUR-01\|2026-09-15` with 13 affected results, value "not available" |
| Control outcomes | No FAIL, no INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE present |
| What makes a pack FAILED (not published) | — | Unresolvable reference, missing control result, exception without evidence, value mismatch with the engine, schema invalid |

## 5. Rejection conditions for Scenario 1

The clean pack **fails acceptance** if any of the following holds:

- any section is missing;
- any count differs from section 1;
- any figure differs from its engine or source field;
- any reference does not resolve;
- the pack contains any exception, group, candidate or missing-evidence item;
- any status field differs from section 2;
- `pack.json` differs between two identical generations;
- the pack layer read an answer key or golden file.
