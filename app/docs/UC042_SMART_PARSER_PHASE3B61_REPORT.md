# UC-042 Smart Parser: Phase 3B-6.1 report

**Deterministic conflict protection and HITL routing. 18 November 2026.**

**Working copy:** `C:\Users\artlptp263user\p10\smartparser_phase1`. The UC-042 tree was used read-only.

**Scope:** fix C1 from the missing-vs-unmapped audit and establish the HITL routing. Prompt change C2 and the optional C3/C4 were **not** in scope and were not made.

## Summary

- **The defect is fixed.** A proposal onto a field claimed by more than one incoming column is now **CONFLICT_INCOMPLETE** with diagnostic `DETERMINISTIC_CONFLICT`. It is never CLEAR, never AUTO_ACCEPT, and never produces a POC rule or preview.
- **Safe before any record is written.** The routing decision is reached before any approval record or rule is created; it does not rely on the later handoff check.
- **New routing:**
  - duplicate claims → HITL;
  - ambiguous → HITL;
  - extra headers without a valid mapping → HITL;
  - unresolved required fields → HOLD;
  - conflict-free CLEAR → AUTO_ACCEPT, unchanged.
- **Results:** 452 tests pass (437 before, plus 15 new). Baselines 445/445 and 161/161, evaluations 34/34 and 68/68, registry in sync.
- **Nothing else changed:** no live calls, the POC policy is still disabled, and protected paths are unchanged.

## 1. Root cause

When two incoming columns claim the same canonical field, the field is a deterministic duplicate.

1. `build_request` (`mapping/proposal_runner.py`) recorded it in `request.deterministic_conflicts` and **left it out of `resolved_columns`**, deliberately, because neither column is a valid resolution.
2. `validate_proposal` (`mapping/proposals.py`) checked "already taken" only against `resolved_columns`. **`deterministic_conflicts` was never read anywhere**, which `grep` confirmed.
3. A third, unfamiliar column proposed onto that field therefore passed every check and was classed CLEAR. `_summary` even counted the field as *missing*.
4. `policy.decide` (`orchestration/policy.py`) saw only CLEAR columns and returned AUTO_ACCEPT. The orchestrator then wrote a `POC_AUTO` file mapping and confirmation. Only the later handoff check stopped a preview.

## 2. Files modified and exact changes

### `smartparser/mapping/proposals.py`

| Item | Change |
|---|---|
| `ProposalSummary` | New field `deterministic_conflicts: dict[str, list[str]]` (additive, default `{}`) |
| `validate_proposal` | Reads `conflicted = dict(request.deterministic_conflicts)`. For a proposal whose field is valid and in `conflicted`, it adds diagnostic **`DETERMINISTIC_CONFLICT`** ("…claimed by more than one incoming column […]; it is blocked for proposals until a person resolves the conflict") and sets `conflict = True`, so the class is **CONFLICT_INCOMPLETE** and the status `rejected`. Explicit UNMAPPABLE still takes precedence, so the 3B-1 correction is preserved and tested. |
| `_summary` | New `conflicted` argument. Conflicted fields are **removed from `required_fields_unresolved`**: they are present in the file, conflicted, not missing. Adds a reason ("deterministic conflict(s), a person must resolve them"). `overall` is `CONFLICT` whenever a deterministic conflict exists. Records `deterministic_conflicts`. |

### `smartparser/orchestration/policy.py`

`decide()` collects **every** finding into `reasons`, then routes in this order:

1. **REJECT_OR_HOLD:** no usable proposal, or the proposal was rejected (unchanged).
2. **REJECT_OR_HOLD:** a required field is unresolved (HOLD).
3. **HUMAN_REVIEW:** a deterministic conflict exists, or any proposal carries `DETERMINISTIC_CONFLICT`. **New; never AUTO_ACCEPT.**
4. **REJECT_OR_HOLD:** any other CONFLICT_INCOMPLETE column (duplicate proposal target, field already resolved, header or index mismatch, value-rule conflict). Unchanged.
5. **HUMAN_REVIEW:** a NO_MATCH column (an incoming header with no valid mapping). **Changed from REJECT_OR_HOLD**, as the brief requires; the column is never dropped.
6. **HUMAN_REVIEW:** ambiguous, plausible, or the policy is disabled (unchanged).
7. **AUTO_ACCEPT:** only if none of the above applies.

The docstring documents this order.

**Unchanged:** `proposal_runner.py`, `orchestrator.py` (it reads the conflicts through `record.summary`), the review state machine, the gateway, `controlled_map`, all rule and policy files, and every existing test.

**New:** `tests/test_conflict_protection_3b61.py` (15 tests) and this report.

## 3. Tests added (`tests/test_conflict_protection_3b61.py`; 15 passed)

| Case | Test | Verified |
|---|---|---|
| **A, the exact audit reproduction** | `test_case_a_exact_audit_reproduction_is_never_auto_accepted` | The request lists the conflict and `txn_ref` as the only unresolved header. `txn_ref → transaction_id` is CONFLICT_INCOMPLETE with `DETERMINISTIC_CONFLICT`; summary `CONFLICT`; **HUMAN_REVIEW**; review session PROPOSED; no file mapping; no `POC_AUTO` rule events; no preview. |
| A on UC-042 IN-10 | `test_case_a_on_uc042_in10` | `ledger_entry_id` + `LEDGER_ENTRY_ID` + `entry_ref` proposed as `ledger_entry_id`: never CLEAR; HUMAN_REVIEW; nothing created |
| A, confidence | `test_conflicted_target_never_clear_even_with_high_confidence` | Proposer confidence 0.99 is ignored; the conflicted field is not listed as missing |
| A, correction preserved | `test_explicit_unmappable_onto_conflicted_field_keeps_the_correction` | UNMAPPABLE onto a conflicted field stays NO_MATCH with status `unmappable`, diagnostic `UNMAPPABLE` only |
| **B** | `test_case_b_duplicate_headers_without_a_proposal_are_held` | `amount` + `AMOUNT`, nothing else unresolved: no proposer call; REJECT_OR_HOLD (hold); nothing created |
| B + extra | `test_case_b_duplicates_plus_unmappable_extra_go_to_review` | HUMAN_REVIEW with the conflict in the reasons |
| **C** | `test_case_c_extra_header_without_mapping_goes_to_review_and_is_not_dropped` | `note` UNMAPPABLE gives HUMAN_REVIEW. The column is a review item, its source cell is kept, and it is listed as unresolved. |
| C, no answer | `test_case_c_extra_header_without_any_answer_is_held_not_dropped` | Provider gives no answer: HOLD, with `note` still listed |
| **D** | `test_case_d_conflict_free_deterministic_file_unchanged` | DETERMINISTIC; 0 calls; preview byte-identical to the canonical IN-10 |
| **E** | `test_case_e_clear_conflict_free_proposal_still_auto_accepts` | AUTO_ACCEPT; `POC_AUTO`; eligible; preview equals canonical (with the POC policy explicitly enabled by the test fixture) |
| **F** | `test_case_f_conflict_blocks_even_when_other_proposals_are_valid` | `entry_ref` and `acct_no` CLEAR, `currency` + `CURRENCY` duplicated: HUMAN_REVIEW, no AUTO |
| F + missing | `test_unresolved_required_field_holds_before_conflict_review` | `account_id` unresolved: HOLD, and the reasons list both the missing field and the conflict |
| Review model | `test_review_session_supports_map_alternative_ignore_and_reject` | A NO_MATCH column cannot be APPROVEd; CHANGE onto a resolved field is refused; LEAVE_UNMAPPED with a reason; the whole file can be rejected |
| Review model | `test_review_change_onto_conflicted_field_is_refused` | A reviewer cannot CHANGE an unresolved column onto the conflicted field (`DETERMINISTIC_CONFLICT`) |
| Policy unit | `test_policy_unit_det_conflict_with_all_clear_columns_is_review` | All columns CLEAR plus a deterministic conflict gives HUMAN_REVIEW |

## 4. Case A: before and after (same input, recorded proposer response)

The input is `transaction_id, TRANSACTION_ID, transaction_date, amount, merchant_id, txn_ref`, with the proposal `txn_ref → transaction_id` (CLEAR, confidence 0.99).

| | Before 3B-6.1 | After 3B-6.1 |
|---|---|---|
| `txn_ref` | `transaction_id`, **CLEAR**, no diagnostics | `transaction_id`, **CONFLICT_INCOMPLETE**, `DETERMINISTIC_CONFLICT` |
| Summary | `REVIEW_REQUIRED`; no conflict recorded | **`CONFLICT`**; `deterministic_conflicts = {transaction_id: [transaction_id, TRANSACTION_ID]}` |
| Decision | **AUTO_ACCEPT** ("every unresolved column is CLEAR…") | **HUMAN_REVIEW** ("deterministic conflict: more than one incoming column claims …"; "proposal(s) onto a deterministically conflicted field: txn_ref -> transaction_id") |
| Side effects | `POC_AUTO` file mapping, confirmation and rule events written; handoff then failed checks 1, 2, 3, 5, 6, 10 and 11 | **No** file mapping, confirmation, rule event or preview; a review session is opened (PROPOSED) |

**Evidence:** `evidence/caseA_before.json` and `evidence/caseA_after.json` come from the same probe script, run before and after the change.

## 5. Full regression (executed 18 Nov 2026)

| Suite | Result |
|---|---|
| **3B-6.1** | **15 passed** |
| 3B-6 | 42 passed |
| 3B-5 | 16 passed |
| 3B-4 | 14 passed |
| 3B-3 | 15 passed |
| 3B-2 | 23 passed |
| 3B-1 (including the UNMAPPABLE correction) | 40 passed |
| 3B-0 | 117 passed |
| Phase 1 and original | 136 passed |
| Phase 2 | 34 passed |
| **Full suite** | **452 passed** |
| Without the UC-042 tree | 449 passed, 3 skipped |
| Registry `--check` | in sync, 19 definitions |
| Phase 1 baseline | **445/445** |
| Phase 2 corpus | **161/161** |
| 3B-6 evaluation | **34/34** |
| 3B-5 evaluation | **68/68** |

No existing test or evaluation expectation needed changing. The NO_MATCH routing change affects only files where a header has no valid mapping **and** no required field is unresolved, and no earlier test exercised that combination.

## 6. No live provider calls

- Every test uses recorded responses built in memory or from fixtures, with sockets blocked in the new tests.
- `grep` finds 0 network imports in `smartparser/`.
- `AIConfig` defaults are unchanged (disabled).
- No credential, provider, model, region, budget or flag was touched.
- The shipped POC policy is still `DISABLED` (`enabled: false`).

## 7. Protected paths and data

| Item | Result |
|---|---|
| UC-042 code (107 `.py` files) | Unchanged (SHA-256) |
| UC-042 datasets (624 files) | Unchanged |
| Desktop Smart Parser (63 files) | Unchanged |
| Files in the UC-042 tree newer than the start of Phase 1 | 0 |
| Production rules | 0 aliases, 0 layouts, 19 proposals all `proposed` |
| Production authority policy | No roles |
| Clone E, demo database | Not touched |

Nothing was deployed or submitted.

## 8. Review-model limitations (map, alternative, ignore, reject)

| Reviewer action | Supported today? |
|---|---|
| Map an incoming header to a canonical field | **Yes:** APPROVE (CLEAR, PLAUSIBLE or AMBIGUOUS proposals) or CHANGE (any field, re-validated) |
| Select an alternative valid field | **Yes:** CHANGE. It is refused for invalid, already-resolved, value-incompatible and now **deterministically conflicted** fields. |
| Ignore an incoming header with a recorded reason | **Partly.** LEAVE_UNMAPPED records the reviewer, time and reason. But under the current **reject-extra-column policy** an ignored column keeps the file **ineligible** (handoff check 6), because the model has no "exclude this column from the canonical output" decision. Allowing it needs an owner decision on extra columns and a small extension (a governed "ignored column" entry in the file mapping, honoured by `controlled_map`). |
| Leave unresolved, or reject the file | **Yes:** REJECT or LEAVE_UNMAPPED per column; `reject_proposal` (reason required) or `request_revision` for the whole proposal |
| **Resolve a deterministic duplicate** (choose which of `amount` / `AMOUNT` is authoritative) | **No.** The review session contains only the *unresolved* columns from the proposal. Duplicate columns are "mapped" deterministically, so they are **not review items**. A reviewer can see the conflict (summary and reasons) and reject the file, but cannot pick one of the duplicates. Supporting that needs a new decision type, such as "column X is the source of field F; column Y is ignored", which runs into the same extra-column policy question. |
| Duplicates with **no other unresolved column** (Case B) | **Held** (REJECT_OR_HOLD) without a review session, because there is no proposal to attach one to. The reasons explain the conflict, and the file must be corrected upstream or handled once the decision type above exists. |

**Recommended follow-up, not implemented:**
1. An owner decision on whether "ignored" incoming columns may be excluded from a canonical output.
2. If yes, two small review decision types, `IGNORE_COLUMN` and `CHOOSE_DUPLICATE_SOURCE`, recorded in the file-specific mapping and honoured by `controlled_map`.
3. Audit item C2 (prompt v1.1 wording on missing fields), still open.

### Evidence

`Downloads\UC042_SMART_PARSER_PHASE3B61\evidence\`:
- `regression_summary.txt` and `test_run_full.txt`;
- the baseline, corpus and both evaluations;
- `caseA_before.json` and `caseA_after.json`.
