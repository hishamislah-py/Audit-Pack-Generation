# UC-042 Smart Parser — Phase 3B-7 Implementation Report
## Header-Count Routing and Direct Human-in-the-Loop Resolution

| | |
|---|---|
| Date | 18 November 2026 |
| Working copy | `C:\Users\artlptp263user\p10\smartparser_phase1` (the only location modified) |
| Status | **Implemented and tested offline. 491 tests pass. Both evaluations pass (3B-5 68/68, 3B-6 34/34). No live LLM call made.** |
| Evidence | `Downloads\UC042_SMART_PARSER_PHASE3B7\evidence\` |

---

## 1. Summary and verdict

When a category is supplied and it is a controlled UC-042 CSV category, the orchestrator now compares the incoming column count with the category's field count **before** any mapping is attempted.

- **Equal counts:** the existing pipeline runs unchanged (deterministic, then LLM proposal, then validation, then POC policy).
- **Different counts (fewer, more, or extra duplicates):** the file goes **directly to a person**.
  - There is no deterministic mapping, no proposal or LLM call, no POC policy, no rule and no preview.
  - A **column-review case** is opened. It lists every incoming position, the expected and incoming counts and their difference, missing fields, extra headers, duplicate headers and potential duplicate claims, and the content category when the header exactly matches another category.

The reviewer then decides each column:
- **MAP** or **CHANGE** to a field;
- **CHOOSE_DUPLICATE_SOURCE**, which gives every other claimant an explicit IGNORE disposition;
- **IGNORE_COLUMN**, which needs a reason;
- **LEAVE_UNRESOLVED**;
- or **REJECT** the whole case.

Finalising the case gives one of two outcomes:
- **HELD**, when a column is left unresolved or a required field is unmapped. Nothing is written.
- **RESOLVED.** A category confirmation and a governed **file-specific** mapping are written. MAP and IGNORE dispositions are tied to this intake, its SHA-256 and each column position. The file is then **reprocessed deterministically** (no LLM), checked against the 14-point handoff checklist, and a PREVIEW is written only when every check passes.

Equal-count files where several columns claim the same field now also open a case, of kind DETERMINISTIC_CONFLICT, and go to HUMAN_REVIEW. This happens whatever the proposal outcome, and also when no proposal can be requested.

**Defects found and fixed during the work:**
- Duplicate-named columns overwrote one another in the record originals, which lost data.
- The content check would have misaligned cells once a column was ignored.

Details are in §12.

## 2. Scope and constraints honoured

| Constraint | Status |
|---|---|
| Work only in the authorised Smart Parser copy | ✔ only `p10\smartparser_phase1` modified |
| Authoritative UC-042 source untouched | ✔ 107 code files + 624 dataset files hash-identical; 0 files newer than Phase 1 start |
| Desktop Smart Parser untouched / nothing copied back | ✔ 63 files hash-identical |
| Clone E / original UC-042 app | ✔ not touched |
| Datasets / canonical definitions | ✔ unchanged; registry check "in sync: 19 definitions" |
| No live LLM / provider calls; provider not enabled | ✔ recorded stubs only; sockets blocked in tests; `AIConfig` default `enabled=False` |
| Shipped POC policy | ✔ still `DISABLED` |
| Credentials, provider config, model, region, budgets | ✔ not touched |
| No destructive tests against the active demo database | ✔ no database used; every store is a temporary directory |
| No deployment or submission | ✔ `submit_to_uc042` still always refuses |
| Out of scope (Jev, fuzzy matching, OCR, PDF, new categories or schemas, reusable aliases or layouts, UI, auth) | ✔ none added; a case only ever creates a **file-specific** rule |

## 3. The header-count gate

`MappingOrchestrator._header_count_gate` (in `orchestration/orchestrator.py`) runs first in `process()`. It applies only when **all** of the following hold:
- a category is supplied, which is the confirmed category for this purpose;
- `is_controlled(schema)` is true, meaning a UC-042 CSV category with exact-header matching;
- the bytes identify as CSV and the CSV reads without a structural error.

In every other situation the gate returns `None` and the existing pipeline reports the file exactly as before. This covers no category, a synthetic or stub schema, a PDF, an empty file and a malformed CSV. No count decision is ever made on a partial read.

If `len(raw_headers) != len(schema.fields)`:
1. The original is stored in the evidence store (content-addressed) and receives an intake ID.
2. A diagnostic is computed: if the exact header list is another category's canonical header, `content_classification = {category, method: csv_exact_header}`. The supplied category is never switched.
3. `open_case("HEADER_COUNT_MISMATCH", …)` is called and audited as `INTAKE_CASE_OPENED`.
4. The gate returns `Decision.HUMAN_REVIEW` with `route="HEADER_COUNT_GATE"`, `initial=None` and `proposal=None`. `SmartParser.process_bytes` and the proposal gateway are never called, so there is no proposal record and no POC decision event.

Automatically classified files (no category supplied) have equal counts by construction, because classification needs a one-to-one mapping. They are therefore not gated.

## 4. Routing table (as implemented)

| Situation | Route | Where |
|---|---|---|
| Equal count, exact or policy matches | DETERMINISTIC | pipeline (unchanged) |
| Equal count, unresolved headers | LLM proposal path | gateway (unchanged) |
| Equal count, CLEAR proposals, no conflicts | POC policy (AUTO_ACCEPT only when the policy is enabled; shipped policy is DISABLED) | policy (unchanged) |
| Equal count, duplicate canonical claims | **HUMAN_REVIEW + DETERMINISTIC_CONFLICT case**, checked **before** the required-field HOLD (3B-7 reorder). This applies even with no proposal, and when the provider is disabled or errors. | policy + orchestrator |
| Equal count, ambiguous proposals | HUMAN_REVIEW | policy (unchanged) |
| Equal count, no valid mapping | HOLD when a required field is left unresolved (all UC-042 columns are header-required). Otherwise HUMAN_REVIEW for NO_MATCH. | policy |
| **Different count** (fewer, more, duplicates) | **Direct HUMAN_REVIEW + HEADER_COUNT_MISMATCH case**; 0 LLM calls | gate |
| Reviewer ignores an extra column | Reprocessed only when every required field is mapped exactly once | `complete_case` |
| Required field unmapped at finalisation | HELD (`REJECT_OR_HOLD`, route `CASE_HELD`) | `finalise_case` |
| Reviewer selects a duplicate source | Validated, then reprocessed | `decide` + `complete_case` |
| Reviewer leaves a column unresolved | HELD | `finalise_case` |
| Reviewer rejects | Case REJECTED | `reject_case` |

## 5. The column-review case (`review/intake.py`, new)

`ColumnReviewCase` is a strict pydantic model; extra fields are forbidden. Every column is identified by its **position**, never by header text alone.

**Contents:**
- **Identity:** `case_id`, `kind`, `intake_id`, `source_sha256`, filename, `category`, `registry_definition_sha256`, `mapping_rules`.
- **Counts:** `incoming_header_count`, `expected_field_count`, `count_difference`.
- **Columns:** `headers`, plus `columns[]` with, for each position, `source_index`, `source_header`, `suggested_field`, `suggestion_basis` and `same_header_positions`.
- **Diagnostics:** `missing_fields_diagnostic`, `extra_headers_diagnostic`, `duplicate_incoming_headers` (identical text at several positions) and `potential_duplicate_claims` (field → positions).
- **Context:** `content_classification`, and `proposal_id` for conflict cases seeded from a proposal.
- **Review state:**
  - `state`, `decisions[]` (append-only) and `history[]` (state transitions);
  - `final_summary`, `rejection_reason`, `file_mapping_id`, `confirmation_id`.

**States:**
- OPEN → UNDER_REVIEW → RESOLVED, HELD or REJECTED.
- A HELD case can return to UNDER_REVIEW for a revised decision.
- RESOLVED and REJECTED are terminal.

**Suggestions:**
- **HEADER_COUNT_MISMATCH** cases carry diagnostic name matches only: the canonical name, or the same name under the active whitespace and case policy. There are no aliases, layouts, LLM output or fuzzy matches, and a suggestion is never applied by itself.
- **DETERMINISTIC_CONFLICT** cases carry the deterministic matches per position, plus non-conflicting validated proposal fields (CLEAR, PLAUSIBLE or AMBIGUOUS) for the remaining columns.

**Review context (`case_context`).** It is built from the stored original only, after checking that:
- the stored original is present and matches its SHA-256;
- the intake exists with the same SHA-256;
- the re-read header equals the case header.

It holds the schema, the first 5 non-empty sample values per column, and the deterministic field per position. It is never persisted.

## 6. Reviewer decisions

Every decision has the same preconditions:
- **FILE_MAPPING** authority under the authority policy (production authorises nobody; tests use the test-only policy);
- a non-empty reason;
- a valid position and a matching context.

Each decision is appended (the previous decision for that position is recorded in `supersedes`) and audited as `INTAKE_DECISION`.

| Action | Rules enforced |
|---|---|
| MAP | The column must have a suggestion. Field checks apply (below). |
| CHANGE | Any field of the confirmed category. Field checks apply. |
| CHOOSE_DUPLICATE_SOURCE | The position must be one of ≥ 2 claimants of the field, and `others_reason` is required. Every other claimant receives an IGNORE_COLUMN decision in the same `group_id`, with the reason "duplicate claimant of X; authoritative column is N: …". |
| IGNORE_COLUMN | A reason is required. It never satisfies a field. |
| LEAVE_UNRESOLVED | The case is HELD at finalisation. |
| REJECT (`reject_case`) | A reason is required. The case becomes REJECTED and no further decisions are allowed. |

**Field checks:**
- **unknown field** → refused;
- **DUPLICATE_TARGET:** the field is already mapped from another column → refused, with a pointer to CHOOSE_DUPLICATE_SOURCE;
- **VALUE_INCOMPATIBLE:** a sample value breaks the field's type, pattern or allowed values → refused;
- **RULE_CONTRADICTION** (new): a column whose header deterministically matches field X (canonical name, policy, or approved alias) can only be mapped to X or ignored. This is the 3B-2 invariant that reprocessing enforces; it is now enforced at decision time, so a reviewer cannot record a decision that reprocessing would later refuse.

**Finalisation (`finalise_case`, or `MappingOrchestrator.complete_case`):**
- Undecided columns cause an error.
- The case is refused if the registry definition changed since it was opened.
- Duplicate targets are re-checked, and every mapped column is re-validated against the stored file.
- If any column is LEAVE_UNRESOLVED, or any required field is unmapped, the case is **HELD**: audited as `INTAKE_CASE_HELD`, nothing is written, and the result is `(None, None)`.
- Otherwise the category is confirmed. CATEGORY_CONFIRMATION is used, or **CATEGORY_CONFLICT** when the content identifies as another category; that needs the separate authority (data_owner in the test policy).
- A `FileMappingRule` (`FM-CRC-…`) is written with one `ColumnRule` per position, marked MAP or IGNORE (the ignore reason is stored). It carries the approvals, the decision IDs and `proposal_id` (the conflict proposal, or `column-review:<case_id>`).
- `RULE_CREATED`, `RULE_ACTIVATED` and `INTAKE_CASE_RESOLVED` are audited, and the case becomes **RESOLVED**.

## 7. IGNORE_COLUMN governance

| Requirement | Implementation |
|---|---|
| Reason required | `ColumnRule` validator: IGNORE requires `canonical_field=None` and a non-empty `ignore_reason`; MAP may not carry an ignore reason; `LayoutRule` rejects IGNORE (reusable layouts are out of scope) |
| Tied to file identity and position | Lives only in a `FileMappingRule` that applies to one `intake_id` + `source_sha256` and the exact header list; keyed by `source_index` |
| Auditable | `INTAKE_DECISION` (reason, group), `RULE_CREATED` and `RULE_ACTIVATED` (`ignored_positions`); approvals carry reviewer, role and kind |
| Preserved through reprocessing | `controlled_map` records the position in `ignored_columns` (`source_position`, `source_header`, `rule_id`, `rule_version`, `reason`); `to_mapping_result` → `MappingResult.ignored_columns` (with `record_key`) |
| Never satisfies a required field | Not a mapping; handoff check 3 (every field mapped exactly once) and check 5 (no required field missing) are unchanged; finalisation HOLDs on a missing field |
| Never silently drops data | Cells stay in the stored original and in every record's `original` (unique key per position); the preview sidecar lists `ignored_columns`; handoff check 6 now requires `len(mapped) + len(ignored) == len(raw)`, a reason and a rule for each ignore, and no overlap with mapped positions |
| Only valid while its rule is active | Checks 8 and 9 validate the file-mapping rule behind each ignored column (a revoked rule makes the file ineligible: tested) |

## 8. Reprocessing and preview

`complete_case` runs `_finish` with the new confirmation. That calls `reprocess`, which:
- loads the original and verifies its SHA-256 and intake;
- confirms the category for exactly this upload;
- applies the governed rules, with the file mapping valid for this intake and SHA-256 only;
- runs the normal pipeline. No proposer exists on this path, so `provider_calls = 0`.

It is followed by `check_handoff` (14 checks) and `write_preview` only when eligible.

**Properties verified by tests:**
- **Original cells unchanged.** The preview of an IN-10 file with an extra `note` column (end or middle position) is **byte-identical** to the canonical IN-10 file.
- **Repeatable.** Reprocessing twice gives byte-identical output and identical mappings.
- **Traceable.** The sidecar lists each canonical field's `source_index` and original header, plus `ignored_columns` (with reason, rule and version), and `rules_used` includes the case rule.
- **The chosen duplicate is the one used.** Choosing the second `amount` column makes the preview carry its cells, with `source_index` 8 in the sidecar.
- **Tamper-proof.** Changing the stored original after review makes both `case_context` and reprocessing fail on the SHA-256 check, so no preview is written.
- **Invalid decisions produce no preview.** A missing required field, an unresolved column, a refused duplicate or incompatible values each lead to HOLD or a refusal.

## 9. Before / after examples

**A. IN-10 with an extra `note` column (9 columns, 8 fields)**

| | Before 3B-7 (3B-6.1) | After 3B-7 |
|---|---|---|
| Route | Pipeline → proposal request for `note` → NO_MATCH → HUMAN_REVIEW (proposal session) | Gate → **direct HUMAN_REVIEW**, 0 LLM calls |
| Reviewer output | Could only leave the column unmapped; the file stayed non-canonical and never became eligible | IGNORE `note` with a reason → RESOLVED → reprocess → **eligible PREVIEW**, byte-identical to canonical IN-10; sidecar lists the ignored column |

Evidence: `examples/case_extra_note_RESOLVED.json`, `examples/preview_extra_note.csv` and `examples/preview_extra_note.provenance.json` (output SHA-256 `b1a831a2c98789df…`).

Reason text: *"header-count gate: the file has 9 column(s), IN-10 has 8 field(s) (+1); routed directly to a person - no deterministic mapping, no LLM proposal, no automatic decision"*

**B. IN-10 with a second `amount` column (identical header text)**

| | Before | After |
|---|---|---|
| Records | `original["amount"]` held the **last** column's cell; the first was lost | `original["amount"]` and `original["amount [col 9]"]`: both kept |
| Route | Proposal path → HOLD ("no unresolved source column") | Direct HITL; case shows `duplicate_incoming_headers {"amount": [4, 8]}` and `potential_duplicate_claims {"amount": [4, 8]}` |
| Resolution | none | CHOOSE_DUPLICATE_SOURCE 4 (column 8 ignored in the same group) → eligible preview |

Evidence: `examples/case_duplicate_amount_OPEN.json`.

**C. The owner's short example (4 columns for 8 fields)**
- **Before:** a proposal call, then HOLD.
- **After:** direct HITL with 0 LLM calls. All 8 fields are listed as missing and all 4 headers as unmatched.
- **Outcome:** even after the reviewer maps the 4 columns, the case is **HELD** with `missing_required_fields ['currency', 'dc_indicator', 'entry_type', 'payment_reference']`.
- **Evidence:** `examples/case_short_example_HELD.json`.

**D. IN-09 file supplied as IN-10 (13 vs 8)**
- **Before:** REJECT_OR_HOLD.
- **After:** direct HITL. The case shows `content_classification {"category": "IN-09", "method": "csv_exact_header"}`; the category is never switched.
- If a reviewer resolves a case like this against the content, CATEGORY_CONFLICT authority is required. This is tested with IN-08 supplied as IN-07: the analyst is refused and the data_owner succeeds.

## 10. Edge cases

| # | Edge case | Result | Test |
|---|---|---|---|
| 1 | Equal count, completely different headers | Not gated; proposal path; HOLD with all 8 headers unresolved when no usable answer | `test_equal_count_completely_different_headers_…` |
| 2 | Duplicate header names at different positions | Both kept (unique record keys); case lists positions | `test_case_diagnostics_…`, `test_choose_duplicate_source_with_identical_header_names` |
| 3 | The "wrong" duplicate chosen | Allowed if the values validate; fully traceable (`source_index` in sidecar, audited decision) | `test_chosen_second_duplicate_is_used_and_traceable` |
| 4 | Duplicate chosen with incompatible values | Refused (VALUE_INCOMPATIBLE) | `test_duplicate_choice_with_incompatible_values_is_refused` |
| 5 | Two columns mapped to one field | Refused (DUPLICATE_TARGET) at decision time and again at finalisation | `test_two_columns_can_never_map_to_one_field` |
| 6 | Ignoring the only source of a required field | HELD; nothing written | `test_ignoring_the_only_source_…` |
| 7 | Changing a decision | Held case revisited; new decision supersedes (history kept) → RESOLVED | same test |
| 8 | Remapping a deterministically matched column | Refused (RULE_CONTRADICTION) | `test_change_cannot_contradict_a_deterministic_match` |
| 9 | File changed after review | SHA-256 failure in context and reprocessing; no preview | `test_file_changed_after_review_fails_reprocessing` |
| 10 | Same file under a new intake | New case; earlier rule and confirmation not applied ("different upload"); nothing reusable created | `test_same_file_under_a_new_intake_…` |
| 11 | Reprocessing twice | Byte-identical | `test_reprocessing_twice_is_byte_identical` |
| 12 | LLM disabled | Gate unaffected (HITL); equal-count conflict still HITL | `test_llm_disabled_does_not_change_the_gate` |
| 13 | Category not supplied or confirmed | Not gated; never guessed; HOLD | `test_category_not_supplied_…` |
| 14 | Unsupported, empty or malformed CSV | Left to the pipeline (unchanged reporting); no case | `test_unsupported_or_malformed_input_…` (3 cases) |
| 15 | Fewer columns than fields | HELD after review (cannot be completed) | `test_fewer_columns_cannot_be_completed_and_hold` |
| 16 | Decision without a reason, without authority, out of range, or with an unknown action | Refused | `test_every_decision_needs_a_reason_and_authority` |
| 17 | Undecided columns; decisions after RESOLVED or REJECTED | Refused | `test_undecided_columns_…`, `test_resolved_case_is_terminal`, `test_reject_case` |
| 18 | Ignore rule revoked after resolution | Handoff check 9 fails; not eligible | `test_revoked_rule_makes_the_ignore_invalid` |

Also covered:
- category mismatch with the content category shown, and CATEGORY_CONFLICT authority;
- equal-count conflict with no unresolved column (now HITL, no LLM);
- production rules and POC policy untouched.

## 11. Policy changes and the test updates they required (documented, not weakened)

There are two deliberate policy changes, both required by the brief:
- **(P1)** Different counts go directly to HITL.
- **(P2)** Deterministic conflicts go to HITL before the required-field HOLD, and an equal-count conflict always opens a case, even when no proposal is possible.

Each affected test keeps its protective intent:
- The original different-count input is still tested, now asserting direct HITL with no LLM, no proposal and no rule.
- An **equal-count variant** keeps the 3B-6.1 conflict and NO_MATCH protection exercised.

| Test (before) | Change | Reason |
|---|---|---|
| 3B-6 `test_blocking_cases_are_rejected_or_held[in10_short_example]` | Removed from the parameter list; new `test_short_example_goes_directly_to_human_review` | P1 (4 vs 8) |
| 3B-6 `test_category_mismatch_is_held_without_switching` ×3 | → `test_category_mismatch_goes_to_review_without_switching` (HUMAN_REVIEW, gate, content category shown, never switched) + **new** `test_equal_count_category_mismatch_is_still_held_without_switching` (IN-08 as IN-06, 11 = 11 → HOLD as before) | P1 (13/8, 7/11, 19/11) |
| 3B-6.1 `test_case_a_exact_audit_reproduction_…` | Now asserts direct HITL (6 vs 4) + **new** `test_case_a_equal_count_conflict_…` with every original assertion (DETERMINISTIC_CONFLICT, CONFLICT_INCOMPLETE, no rule) on a 4-column file | P1, P2 |
| 3B-6.1 `test_case_a_on_uc042_in10` | Direct HITL for 10 columns + equal-count variant (currency → LEDGER_ENTRY_ID, payment_reference → entry_ref) | P1 |
| 3B-6.1 `test_case_b_duplicate_headers_without_a_proposal_are_held` | → `…go_to_a_conflict_case`: HUMAN_REVIEW + DETERMINISTIC_CONFLICT case, still 0 LLM calls (was HOLD) | P2 |
| 3B-6.1 `test_case_b_duplicates_plus_unmappable_extra…` | Direct HITL + equal-count variant | P1 |
| 3B-6.1 `test_case_c_extra_header_without_mapping_goes_to_review…` | → `…goes_directly_to_review_and_is_not_dropped` (case item, original bytes kept) + **new** `test_case_c_equal_count_unmappable_column_holds_required_field` (NO_MATCH reported; HOLD because payment_reference is unresolved) | P1 |
| 3B-6.1 `test_case_c_extra_header_without_any_answer…` | Equal-count variant | P1 |
| 3B-6.1 `test_case_f_…` | Equal-count variant (payment_reference → CURRENCY); also asserts the case suggestions | P1 |
| 3B-6.1 `test_unresolved_required_field_holds_before_conflict_review` | **Inverted** → `test_conflict_review_comes_before_unresolved_required_hold` + new policy unit `test_policy_unit_conflict_precedes_required_hold` | P2 |
| 3B-6.1 `test_review_session_supports_map_alternative_ignore_and_reject` | Exercises the (unchanged) 3B-2 proposal-review model directly instead of through the orchestrator; all assertions kept | P1 (extra column no longer reaches that model via the orchestrator) |
| 3B-6.1 `test_review_change_onto_conflicted_field_is_refused` | Equal-count variant | P1 |
| eval_3b6 cases `missing_required`, `mismatch_IN-09_as_IN-10`, `mismatch_IN-07_as_IN-08`, `mismatch_IN-05_as_IN-06` | Expected decision REJECT_OR_HOLD → HUMAN_REVIEW (`missing_required`: expected unresolved `[]`). The harness now also fails a gated case that shows any LLM call, mapping or proposal class, and reports `header_count_gate_3b7` metrics. Corpus rebuilt: **only `manifest.json` changed**; every data file is byte-identical. | P1 |

Test counts: 3B-6.1 went from 15 to 18 tests, and 3B-6 from 42 to 43.

## 12. Defects found and fixed

1. **Data loss with duplicate header names (pre-existing, all phases).** `Record.original` was a dict keyed by header text, so a second `amount` column overwrote the first. For example `{'a':'1','amount':'2.00'}` plus a later `'amount':'3.00'` left only `3.00`.

   **Fix:** `csv_engine.reader.column_keys`. The first occurrence keeps its name; later identical names become `name [col N]`, with uniqueness enforced. It is used in `normalise_table`, `raw_records` and `to_mapping_result`. Result: `{'a':'1','amount':'2.00','amount [col 3]':'3.00'}`.

2. **Content-check misalignment with an ignored column (latent, would have been introduced by IGNORE).** `pipeline._confirm_forced_category` built the content-check header from the mapped fields only. One ignored column made every row width-mismatched; an ignored column in the middle would have checked cells against the wrong fields.

   **Fix:** a positional header over all source columns, with a non-field placeholder at ignored positions. Behaviour without ignored columns is identical. Tested with an ignored column in the middle.

3. **Decision accepted, reprocessing refused (design gap found while testing).** A reviewer CHANGE onto a different field for a header that deterministically matches another field would have been recorded, and then refused by `controlled_map` at reprocessing.

   **Fix:** the RULE_CONTRADICTION refusal at decision time (§6).

## 13. Test and evaluation results

| Suite | Result |
|---|---|
| 3B-7 `tests/test_header_gate_3b7.py` (new) | **35 passed** |
| 3B-6.1 | 18 passed |
| 3B-6 | 43 passed |
| 3B-5 / 3B-4 / 3B-3 / 3B-2 / 3B-1 / 3B-0 | 16 / 14 / 15 / 23 / 40 / 117 passed |
| Phase 1 + original | 136 passed |
| Phase 2 | 34 passed |
| **Full suite** | **491 passed** (was 452) |
| Full suite without the UC-042 tree | 488 passed, 3 skipped (skips need the UC-042 tree) |
| Registry check | in sync: 19 definitions |
| Phase 1 baseline classification | 445 / 445 correct, 0 incorrect / unknown / ambiguous |
| Phase 2 variation corpus | 161 / 161 |
| eval_3b5 | 68 / 68 |
| eval_3b6 | 34 / 34. Decisions: DETERMINISTIC 16, AUTO_ACCEPT 2, HUMAN_REVIEW 7 (was 3), REJECT_OR_HOLD 9 (was 13). Header-count gate: 4 files direct to HITL, **0 LLM calls** on them; 0 LLM calls during reprocessing |

Evidence:
- `evidence/regression_summary.txt` and `evidence/test_run_full.txt` (verbose);
- `evidence/eval_3b5/` and `evidence/eval_3b6/`;
- `evidence/phase1_baseline/` and `evidence/phase2_corpus/`;
- `evidence/examples/`.

## 14. Safety and integrity evidence

- **Network imports:** 0 network-library imports in `smartparser` outside the `ai/` adapter package, and 0 in `review/intake.py`, `orchestration/` and `handoff/`. Tests block `socket.connect` and `create_connection`.
- **POC policy:** `PocAutoAcceptPolicy.load()` gives `DISABLED`, `enabled=False`. `AIConfig.from_env({}).enabled` is `False`.
- **Production rule files:**
  - aliases and layouts empty;
  - 19 alias proposals still `proposed`, 0 approved;
  - production authority policy authorises nobody.
  - Unchanged by every 3B-7 test (asserted).
- **Protected trees:**
  - UC-042: 107 code and 624 dataset files hash-identical;
  - Desktop Smart Parser: 63 files hash-identical;
  - 0 UC-042 files newer than the Phase 1 start.
- **Audit chain:** the hash-chained log verifies in every test and example. A resolved and a held example produced 21 events: `INTAKE_CASE_OPENED` 3, `INTAKE_DECISION` 13, `CATEGORY_CONFIRMED` 1, `RULE_CREATED` 1, `RULE_ACTIVATED` 1, `INTAKE_CASE_RESOLVED` 1, `INTAKE_CASE_HELD` 1.

**Files changed in 3B-7:**
- `csv_engine/reader.py`
- `normalise/engine.py`
- `mapping/governed.py`
- `mapping/controlled.py`
- `models/results.py`
- `pipeline.py`
- `handoff/eligibility.py`
- `handoff/writer.py`
- `handoff/reprocess.py`
- `review/audit.py`
- `review/intake.py` (new)
- `orchestration/orchestrator.py`
- `orchestration/policy.py`
- `tools/eval_3b6.py`
- `corpus/phase3b6_eval/manifest.json`
- `tests/test_header_gate_3b7.py` (new)
- `tests/test_conflict_protection_3b61.py`
- `tests/test_orchestration_3b6.py`

## 15. Limitations, open owner decisions and next steps

**Limitations**
- A **RESOLVED case is terminal.** Changing a resolved mapping needs revocation of its file rule (existing 3B-2 REVOCATION scope) and a new upload or case. A HELD case can be revised.
- **Suggestions are name-based only** (canonical name or policy match; deterministic and proposal suggestions for conflict cases). On a count mismatch no LLM is asked for suggestions; that is by design.
- A **mislabelled column** whose header deterministically matches another field cannot be remapped (RULE_CONTRADICTION). It can only be ignored, or the file rejected for a corrected export.
- **Business intent is not checked.** The system validates values but cannot know which duplicate is "right". It makes the choice explicit, reasoned, audited and traceable.
- **Cases are in-memory objects** returned to the caller. Persistence of open cases (a case store) is not part of this phase; the decisions, rules and outcome are persisted in the audit log and the rule store.
- **Windows path length.** The PREVIEW file name (`PREVIEW_ONLY_NOT_AUTHORISED_FOR_UC042_SUBMISSION__<cat>__<sha12>.provenance.json`, from 3B-3) under a deep output directory can exceed the 260-character Windows path limit. This was observed when writing examples to the deep session scratchpad, and does not occur with the test or Downloads paths. Keep the preview directory short, or enable long paths.
- **Equal-count NO_MATCH** for UC-042 categories in practice ends in HOLD: every UC-042 column is header-required, so an equal-count file with an unmappable column always leaves a required field unresolved.

**Open owner decisions (unchanged plus new)**
1. Authority roles for FILE_MAPPING, CATEGORY_CONFIRMATION and CATEGORY_CONFLICT in production (production authorises nobody).
2. Whether IGNORE_COLUMN needs a second approver (currently 1 approver per the FILE_MAPPING scope).
3. Approval of the canonical-layout preview and sidecar (including `ignored_columns`) as a UC-042 submission format; submission stays disabled.
4. Enabling the POC policy and the live provider (both remain off).

**Suggested next steps**
- A persistent case store, with a reviewer UI or API over `ColumnReviewCase`.
- A revocation-and-reopen flow for resolved cases.
- Owner review of the decision table in §4.
