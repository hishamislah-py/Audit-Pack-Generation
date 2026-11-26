# UC-042 Smart Parser: Phase 3B-5 report

**Evaluation dataset, metrics and end-to-end evaluation. 18 November 2026.**

**Working copy:** `C:\Users\artlptp263user\p10\smartparser_phase1`.

**Status:**
- **Implemented and tested:** a reproducible synthetic evaluation (68 cases, 22 case types covering all 25 required items), end-to-end scenarios A to J, separate metrics, and the explicit UNMAPPABLE correction regression.
- **Not implemented:** live-provider evaluation. It is blocked by owner decisions and budget.

**This is a regression evaluation on synthetic data. It supports no claim about production or third-party accuracy.**

## 1. Files

| File | Purpose |
|---|---|
| `tools/eval_3b5.py` | `build` (dataset), `run` (end-to-end runner and metrics), `compare` |
| `corpus/phase3b_eval/` | 68 generated CSVs, 13 recorded responses (for the cases that reach a proposer), `manifest.json` (1.5 MB) |
| `tests/test_evaluation_3b5.py` | 16 tests |

## 2. Dataset

**How it is built:** every case is a generated copy derived from `tests/fixtures/uc042_canonical/PER-2026-09_set_01_clean_baseline`, which is itself a byte copy of UC-042's `set_01_clean_baseline`. The originals are never modified. A rebuild is byte-identical to the committed copy (tested).

**What each case records:**
- case ID and type;
- scenario (A to J where applicable);
- data file and its SHA-256;
- upload filename;
- the true category, and the true column mapping by construction;
- the supplied category;
- the recorded response;
- the AI mode (stub, disabled, or a live-like double with its budget used up);
- the review plan, setup steps (approve alias or layout, revoke, upload twice) and the expected outcome:
  - upload category and final category;
  - unresolved columns;
  - classes, statuses and diagnostics per column;
  - review outcome;
  - handoff eligibility;
  - proposer calls;
  - case-specific flags;
- the ground-truth source.

| Required item (brief §6.2) | Case(s) |
|---|---|
| 1–3 Canonical, reordered, case and whitespace | 14 × 3 = 42 cases |
| 4 Approved alias | `alias_approved` (test-only approval) |
| 5 Proposed-only alias | `alias_proposed_only` |
| 6 Unfamiliar but clear | `unfamiliar_clear` |
| 7 Ambiguous headers | `ambiguous_headers` |
| 8 Duplicate targets | `duplicate_target` |
| 9 Missing required fields | `missing_required` |
| 10 Extra columns | `extra_column` |
| 11–14 Wrong forced category, IN-09/10, IN-07/08, IN-05/06 | 6 cases, both directions |
| 15 Sign-perspective ambiguity | `sign_perspective` |
| 16 Prompt-injection-like header | `prompt_injection` |
| 17 Malformed provider response | `malformed_response` |
| 18 Explicit UNMAPPABLE, both forms (plus form C) | `unmappable_form_A/B/C` |
| 19 Provider disabled | `provider_disabled` |
| 20 Budget exceeded | `budget_exceeded` |
| 21 Duplicate pending proposal | `duplicate_pending` |
| 22 Approved-mapping reprocessing | `approved_layout_reprocess`, `unfamiliar_clear` |
| 23 Revoked alias or layout | `revoked_layout` |
| 24 Handoff rejection | `handoff_rejected_d1` (and all ineligible cases) |
| 25 Handoff preview | `handoff_preview` (and all eligible cases) |

**The runner:**
- Each case runs in a **fresh temporary environment**: a rule store initialised from the production files, the TEST-ONLY authority policy, an audit log and an evidence store.
- Approvals are test approvals.
- There is no network access and no live provider.

## 3. Results (executed)

**68/68 cases match their expected outcome.**

| Scenario | Case(s) | Outcome (verified) |
|---|---|---|
| A Deterministic success | 14 canonical | 0 proposal calls; eligible; preview **byte-identical** to the canonical source |
| B Controlled variation | 28 reordered, case or whitespace | 0 calls; eligible; preview byte-identical to canonical |
| C Unfamiliar, clear | `unfamiliar_clear` | Category supplied, deterministic mapping fails, 1 recorded proposal (CLEAR, CLEAR, PLAUSIBLE, AMBIGUOUS), review approved, file mapping, confirmation, reprocessing with 0 provider calls, eligible, preview byte-identical to canonical IN-10 |
| D Ambiguous financial field | `sign_perspective` | `txn_amt`→`amount` is AMBIGUOUS; no automatic approval; not eligible |
| E Explicit UNMAPPABLE | Forms A, B, C | NO_MATCH, `unmappable`, diagnostic `UNMAPPABLE` only; approved with the column left unmapped; **not eligible** |
| F Missing required fields | `missing_required` | Review approved, recording 4 missing fields; **not eligible** |
| G Revoked rule | `revoked_layout` | First file mapped by the layout; after revocation it is `unknown`; the earlier result and the rule record are intact |
| H Provider unavailable | `provider_disabled`, `budget_exceeded` | 0 calls; manual review; unresolved columns still reported; the deterministic path unaffected |
| I Approved layout, AI disabled | `approved_layout_reprocess` | Deterministic; 0 calls; reproducible (two reprocessings identical); eligible |
| J Wrong category | 6 confusable directions | 3B-0 rejection unchanged; no category switching; 0 calls |

## 4. Metrics (reported separately; synthetic only)

| Area | Metric | Value |
|---|---|---|
| Classification | Correct upload category | 68/68 (1.0) |
| | Unknown at upload | 22/68. Expected for unfamiliar, wrong-category and rule-revoked cases. |
| | Wrong forced-category rejection | 6/6 (1.0) |
| Proposal quality | Columns with ground truth | 32 |
| | Correct proposed field | 29/32 (0.906) |
| | By class | CLEAR 16, PLAUSIBLE 10, AMBIGUOUS 7, CONFLICT_INCOMPLETE 4, NO_MATCH 3 |
| | CLEAR overturned in review | 0 |
| Review | Reviews / approved / rejected | 8 / 6 / 2 |
| | Approved but incomplete | 4 (missing-required, and the 3 UNMAPPABLE forms) |
| Reprocessing | Reprocessed / successful | 52 / 47 |
| | **Provider calls during reprocessing** | **0** |
| | Reproducibility check / revocation enforced | Passed / passed |
| Handoff | Eligible / ineligible | 47 / 21, each with reasons (failed check numbers, or "not reprocessed (type)") |
| | Source cells preserved (check 12) | 52/52 reprocessed |
| | Previews byte-identical to the canonical source | 47/47 |
| Operations | Proposal calls / per file when called | 11 / 1.0 |
| | Deduplicated / manual-review fallbacks | 1 / 3 |
| | Tokens, cost, latency | **Not measured.** No live provider; recorded stub only. |

**Reading the metrics:**
- **Proposal quality reflects the hand-recorded stub responses**, some of which are deliberately wrong (duplicate target, UNMAPPABLE forms). It is **not** a model-quality measure.
- **Not exercised by the evaluation cases:** invented-field rejection and revision requests. Both are covered by unit tests (3B-1 and 3B-2).
- No single overall accuracy score is produced.

## 5. Explicit UNMAPPABLE correction regression

| Form | Response | Verified result |
|---|---|---|
| A | `canonical_field = UNMAPPABLE`, assessment UNMAPPABLE | NO_MATCH, `unmappable` |
| B | `canonical_field = amount`, assessment UNMAPPABLE | NO_MATCH, `unmappable`. `amount` is kept only as the proposed field and in the diagnostic text; no field checks. |
| C | `canonical_field = entry_type` (already mapped deterministically), assessment UNMAPPABLE | NO_MATCH, `unmappable`; **no** `FIELD_ALREADY_RESOLVED` or `DUPLICATE_TARGET` |

`test_regression_would_fail_against_pre_correction_rule` puts back the pre-correction rule, under which only the field form was explicit. With it, form B becomes **AMBIGUOUS / `ambiguous`**, and `compare()` flags the case. The regression is real and detected.

The same correction is also checked in the 3B-1 (40), 3B-2, 3B-3 and 3B-4 tests.

## 6. Tests (executed)

`tests/test_evaluation_3b5.py`: **16 passed**. It covers:
- reproducibility against the committed corpus;
- coverage of every case type, all 14 categories and all 6 confusable directions;
- all 68 cases;
- scenarios A to J (10 parametrised checks);
- metric invariants;
- the correction (forms A, B and C);
- failure under the pre-correction rule.

Full regression: see the consolidated report.

## 7. Live evaluation (not done)

A live-provider evaluation needs the owner to choose a provider, model and region, a data policy, a budget, and **real or BA-authored non-canonical test files**. Until then no third-party accuracy, token, cost or latency figure exists.
