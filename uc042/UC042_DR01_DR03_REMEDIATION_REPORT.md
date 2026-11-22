# UC-042: Remediation of DR-01, DR-02 and DR-03

**Date:** 16 November 2026
**Project:** `C:\Users\artlptp263user\p10\uc042_token_optimisation` (isolated copy of Clone E)
**Baseline:**
- `UC042_POST_REVIEW_STATUS.md`: none of the review findings had been addressed.
- `docs/token_optimisation/INDEPENDENT_CODE_REVIEW.md`.

**Scope:** DR-01, DR-02 and DR-03 only. DR-04, DR-05 and every secondary finding were left untouched.

**Result:** all three are fixed. Every one of the 18 new regression tests failed on the old code (reproducing a defect) and passes on the new code. The full backend suite passes, and record parity is intact. Strict NOT_FOUND parity is **95/96**; the one remaining miss is listed in §7.

---

## 1. Files changed

| File | Change | Lines changed (pre → post) |
|---|---|---|
| `uc042lib/investigation/det_retrieval.py` | DR-01 and DR-03 fixes; rule 1.2 → **1.3**; module docstring updated | 123 (`docs/token_optimisation/DR01_DR03_det_retrieval.diff`) |
| `tests/det_parity.py` | DR-02: strict harness | 148 (`docs/token_optimisation/DR02_det_parity.diff`) |
| `tests/test_phase6_deterministic.py` | Docstring, and the parity assertion now uses strict accounting (`covered + missed == cited`) instead of the loose equality | 6 (same diff file) |
| `tests/test_dr01_dr03_remediation.py` | **New:** 18 regression tests | new |
| `UC042_AI_RELIABILITY_AND_TOKEN_OPTIMISATION_IMPLEMENTATION_REPORT.md` (project and Downloads copy) | Phase checklist row 6, §3 Phase 6 and §11 corrected: 96/96 → strict 95/96; rule 1.3; attempts split by status | doc only |
| `docs/token_optimisation/PHASE8_MIGRATION_READINESS.md` | Preconditions table corrected the same way | doc only |
| `docs/token_optimisation/det_parity_v13.json` | **New:** strict parity output, rule 1.3. `det_parity_v12.json` is kept unchanged as the superseded record | new |

**New evidence files** in `docs/token_optimisation/`:
- `dr0103_full_backend.txt` and `dr0103_postgres.txt`;
- `IMPLEMENTATION_vs_CLONE_E_after_DR01_DR03.patch` (38 files) and `files_changed_after_DR01_DR03.txt`.

The pre-review `IMPLEMENTATION_vs_CLONE_E.patch` is kept unchanged, because earlier status documents reference it.

**Not changed:**
- `tools.py`, `packet.py` and `validation.py` (all byte-identical to Clone E);
- `packet_view.py`: the model view stays 1.1, because DR-04 and DR-05 are out of scope;
- prompts (`1.6` / `2.6-tools`) and the investigation output budget (12000);
- the application mode (`uc042app/services/investigations.py:321`, `mode="tools"`) and the library default (`fixed`);
- the Phase 2 patch: not applied;
- the protected digest `uc042lib/final_pack` (`bf2dc23b…`);
- every pack, dataset, golden file and investigation.

## 2. Exact implementation changes

### 2.1 DR-01: search de-duplication (`det_retrieval.py`)

**`_norm(query)` (l.188) now returns the complete normalised query.**
- **Every key is kept:** `txn_id`, `batch_id`, `client_id`, `txn_type`, `payment_reference`, `window`, `date_from`, `date_to`, `currency` and any others.
- **None values are dropped,** because a `None` filter is no filter.
- **Only genuine synonyms are folded** (`_SYNONYMS`, l.185):
  - `statement_date`, `booking_date` and `recon_date` become `date`;
  - `bank_reference` becomes `reference`.
  - A synonym is folded only when it does not conflict with a value already present. Two different values are both kept and never merged.

**New `dedupe_not_found(searches)` (l.203) returns `(kept, register entries)`.**
- Only NOT_FOUND searches are ever dropped.
- A search is dropped only if an **earlier NOT_FOUND** search has the identical complete normalised query. FOUND searches are never dropped and never cause a drop.
- Order is preserved.
- Each drop records `search_id`, `duplicate_of`, `query` and the reason `"identical NOT_FOUND query already recorded as SEARCH-xx"`. The old reason, "repeats an earlier NOT_FOUND search", was false in the defect cases.

**`expand()` step 4 (l.273)** is now `col.searches, dropped = dedupe_not_found(col.searches)`.

**Version:** `DET_RULE_VERSION = "uc042-det-retrieval/1.3"` (l.35). It is recorded in every deterministic packet (`retrieval_rule_version`) and in `ModelMetadata.retrieval_rule_version`.

### 2.2 DR-03: record budget and pruning register (`det_retrieval.py`)

**New `_BudgetedCall(tools.ToolCall)` (l.102).** `tools.py` itself is unchanged.
- **`add()` (l.114):**
  1. Applies the per-call cap exactly as `ToolCall.add` does, and also records which IDs it cut (`cut_per_call`). `ToolCall.add` keeps no record of them.
  2. Adds a record that is new to the packet only while the packet is below `budget` (`DET_MAX_RECORDS`). The rest go to `cut_budget`, in the original order.
  3. Passes the allowed records to `ToolCall.add`, so the investigation-wide `MAX_RECORDS` still applies and still fills `not_added`.
  4. Keeps each cut record (`cut_items`) for the register.
- **The return value equals the tools-mode value** (all records after the per-call cut). That list becomes a search's `found` list, so a budget cut can never turn a FOUND search into a fabricated NOT_FOUND. A test proves this.
- **`unfollowed()` (l.142):** `get_settlement_batch` follows a settlement line to its transaction only if the line was added (`tools.py`, `ln["evidence_id"] not in call.ids`). This is the only traversal in the tool registry that depends on an earlier add. For every cut line, the transaction the tool would have fetched is reported (it exists in the data and is not in the packet), together with the line that references it.

**`_run()` (l.156):**
- Keeps the existing pre-call refusal ("record budget N reached; not fetched").
- Runs the tool with a `_BudgetedCall`, which is what `tools.execute` does with a plain `ToolCall`.
- Writes one register entry per reason, each with `omitted_evidence_ids`:
  - `record budget N reached during the call; not added`;
  - `per-call cap of N records reached; not added`;
  - `investigation-wide MAX_RECORDS N reached; not added`;
  - `not retrieved: the settlement line referencing each transaction was not added`, with `not_retrieved_via` naming the line for each transaction.

**The invariant now enforced and tested:** an expansion never takes the packet past `max(DET_MAX_RECORDS, records already in the base packet)`. Nothing already collected is removed, record order is preserved, and every record a call returned but did not add is registered by evidence ID.

### 2.3 DR-02: strict parity harness (`tests/det_parity.py`)

- **`full_query()` (l.41):** the harness's own normaliser, deliberately independent of `det_retrieval._norm`. It keeps every key, drops `None` values, and maps date and reference synonyms to one name each when they agree.
- **`not_found_covered()` (l.55):** covered only when a deterministic search has the **same complete normalised query and is itself NOT_FOUND**.
- **`_records()` (l.81)** yields every record with an exclusion reason. Fixed-mode records and tools records without a transcript are **reported under `excluded`**, no longer skipped silently.
- **`_status()` (l.74)** classifies each record as published, completed but not published, failed, or other.
- **`summary()` (l.183) reports:**
  - `attempts` (each status, plus `completed_investigations`);
  - `excluded`, with reasons;
  - `not_found_missed` (each miss with store, status, pack, exception, search ID and query);
  - `not_found_matching`;
  - `retrieval_rule_versions`;
  - `by_status` coverage.
- The existing keys are kept, so the Phase 6 test still runs.
- `miss_items_preserved` and `candidates_unchanged` are kept, but now labelled informational, because both come from the case and cannot differ by construction.

## 3. Regression tests added (`tests/test_dr01_dr03_remediation.py`, 18 tests)

| Class | Test | Proves |
|---|---|---|
| DR01RealScenarios | `test_sc5a_02_missing_transaction_search_is_kept` | SC5A-02 `SEARCH-04 {IN-11, txn_id TX-0915-00009}` is NOT_FOUND in the packet and in `allowed_citation_ids`, with no de-duplication entry |
| | `test_sc5d_01_refund_search_is_kept` | SC5D-01/02/03 `{IN-11, client C0003, REFUND}` is NOT_FOUND and citable |
| | `test_every_base_not_found_search_survives` | Across all 53 deterministic-supported packets, every base NOT_FOUND search (more than 40, asserted) is still in the deterministic packet, and every de-duplication names a kept NOT_FOUND search |
| | `test_rule_version_is_1_3` | The constant and the packet field are both 1.3 |
| DR01Dedup | `test_different_queries_with_the_same_old_partial_key_are_both_kept` | 10 queries whose 1.2 key was identical (`txn_id`, `batch_id`, `client_id`/`txn_type`, `payment_reference`, `window`, `date_from`) are all kept |
| | `test_truly_identical_not_found_searches_are_deduplicated_and_recorded` | The second identical NOT_FOUND search is dropped; the entry names `duplicate_of` and gives the query and an "identical" reason |
| | `test_genuine_date_and_reference_synonyms_are_normalised` | `statement_date`/`booking_date` against `date`, `bank_reference` against `reference`, and a `None` filter are folded; a synonym with a different value is not |
| | `test_found_then_not_found_with_the_same_query_keeps_both` | A FOUND search never suppresses a NOT_FOUND one |
| | `test_not_found_then_found_keeps_both` | The later FOUND search is kept |
| | `test_found_searches_are_never_dropped` | Two identical FOUND searches are both kept |
| DR02StrictParity | `test_full_query_and_not_found_result_are_both_required` | The old partial key, another transaction, or a FOUND result do not count; key order does not matter; the harness normaliser is independent |
| | `test_strict_parity_reports_status_categories_and_fixed_mode_records` | The status categories add up; the 2 fixed-mode records are excluded with a reason; no errors; record parity is complete; `covered + missed == cited`; the known miss is pinned exactly |
| DR03Budget | `test_boundary_51_to_55_with_a_budget_of_52` | S05 EXC-01 with budget 52 and `MAX_RECORDS` 55: **52 records**; all **six** review records are in the register; nothing registered is in the packet |
| | `test_records_cut_by_the_investigation_wide_max_records_are_registered` | `MAX_RECORDS` 55: the six records are registered with the MAX_RECORDS reason |
| | `test_records_cut_by_the_per_call_cap_are_registered` | Per-call cap 3 on SC3C-01: the truncated IDs are registered, are absent from the packet, and are real records |
| | `test_budget_is_never_exceeded_by_an_expansion` | Budgets 20, 40 and 60 on all scenario and history packets: never above `max(budget, base)`; base records stay in order; omitted records are never in the packet |
| | `test_found_status_is_not_changed_by_budget_cuts` | Under budget 52, every search keeps its FOUND or NOT_FOUND result |
| | `test_production_values_omit_nothing` | At 140 / 160 / 25, nothing is omitted on any of the 53 packets |

## 4. Original failure reproduction (tests written first, run on the unfixed code)

`python -m unittest tests.test_dr01_dr03_remediation -v` gave exit 1: **18 tests, 25 failures and 18 errors (subtests included)**. Representative results:

- **DR-01:**
  - SC5A-02: `Lists differ: [] != [('SEARCH-04', 'NOT_FOUND')]`.
  - SC5D-01/02/03: `Lists differ: [] != ['NOT_FOUND']` (3 subtests).
  - `'uc042-det-retrieval/1.2' != 'uc042-det-retrieval/1.3'`.
  - `KeyError: 'duplicate_of'`: the old register entry named no surviving search.
  - `dedupe_not_found` did not exist (10 errors).
- **DR-02:** `not_found_covered` and `full_query` did not exist. There was no strict matching, status split or exclusion report.
- **DR-03:**
  - `55 not less than or equal to 52`, plus the six IDs not registered: `['IN-11:TX-0917-00003', …, 'IN-13:SL-AQ-GBP-20260917-0006']`.
  - Expansions overshot tight budgets on real packets: `23 > 20` (×4), `44 > 40`, `61`–`66 > 60` (×11).
  - The per-call cap of 3 produced no register entry.

The diagnosis of DR-01 on the unfixed code:
- SC5A-02 `SEARCH-04` and SC5D-01 `SEARCH-02` were each dropped because they collided with a **FOUND** `SEARCH-01`, under the 1.2 key `{"account":null,"date":null,"file":"IN-11","reference":null}`.
- 4 of the 14 rule-1.2 drops were wrong in this way. The other 10 were IN-07/IN-08 near-duplicates differing by an explicit `currency` (§8).

## 5. Before-and-after results

**All 53 deterministic packets** (scenario, history and CASE), rebuilt at production limits before and after:

| Measure | Rule 1.2 (before) | Rule 1.3 (after) |
|---|---|---|
| Record lists (IDs **and order**) | — | **identical in 53/53** |
| Relationships, control results, MISS items | — | identical in 53/53 |
| Total records; largest packet | 1,790; 77 | 1,790; 77 |
| `retrieval_truncated` flags | — | unchanged in 53/53 |
| NOT_FOUND searches dropped by de-duplication | 14 | **0** |
| NOT_FOUND searches restored | — | **14:** SC5A-02 `SEARCH-04`; SC5D-01/02/03 `SEARCH-02`; and 10 IN-07/IN-08 searches that repeat an earlier query with an explicit `currency` (S02, H202602, H202605, H202607, H202608) |
| Searches removed | — | 0 |
| Omitted-record register entries (production limits) | 0 | 0 |

**The boundary scenario** (S05 EXC-01, budget 52, `MAX_RECORDS` 55):

| | Before | After |
|---|---|---|
| Packet records | **55** (over the budget of 52) | **52** |
| Register entries for omitted records | none (only two pre-call refusals) | `record budget 52 reached during the call`: `SL-AQ-GBP-20260917-0002…0006`, `TX-0917-00003`. `not retrieved: the settlement line … was not added`: `TX-0917-00004`, `-00005`, `-00006`, each linked to its line. Plus the two pre-call refusals |
| All six review records registered | no | **yes** |

With only `MAX_RECORDS` 55 and the budget at 140, all six are registered under `investigation-wide MAX_RECORDS 55 reached` (as are the next batch's six lines and six transactions), and the packet has 55 records.

## 6. Full test results

All commands ran from `p10/uc042_token_optimisation` with `PYTHONPATH=…/p10/env_e/shims PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8`.

| Command | Exit | Result | Original baseline |
|---|---|---|---|
| `python -m unittest tests.test_dr01_dr03_remediation -v` (before the fix) | 1 | 18 tests; 25 failures and 18 errors (subtests) | — |
| `python -m unittest tests.test_dr01_dr03_remediation -v` (after the fix) | 0 | **18 OK** | — |
| `python -m unittest discover -s tests -t .` (file mode, full suite) → `docs/token_optimisation/dr0103_full_backend.txt` | 0 | **743 OK, 24 skipped** (817.9 s) | 725 OK, 24 skipped (+18 new) |
| PostgreSQL mode on `uc042_token_opt_test` (the guard refuses any other DB): `tests.test_auto_investigations tests.test_end_to_end_workflow tests.test_analyst_review tests.test_db tests.test_phase8 tests.test_api_reviews tests.test_openai_only_provider tests.test_api_monthly tests.test_closing_summary tests.test_ui_secondary_backend tests.test_phase3_telemetry tests.test_phase6_deterministic tests.test_dr01_dr03_remediation` → `dr0103_postgres.txt` | 0 | **160 OK** | 142 OK (+18 new) |

The frontend was not changed, so it was not re-run. The last result was 78 passed and 2 skipped, and the build succeeded.

## 7. Strict parity results (`python -m tests.det_parity docs/token_optimisation/det_parity_v13.json`, exit 0)

| Measure | Review baseline | Now (rule 1.3, strict harness) |
|---|---|---|
| Records examined | 51 (2 fixed-mode records skipped silently) | 53: **51 compared**; **2 excluded with a reason** (EXC-SC2-01 in this copy and in Clone E: "fixed mode: no model-directed tool fetches to compare") |
| Attempts by status | not reported | published 22; completed but not published 7 (**29 completed investigations**); failed 22; other 0 |
| Cited model-fetched records (instances) | 162/162 | **162/162**, all from the completed investigations (published 107/107; completed but not published 55/55; failed 0) |
| Distinct per exception | 77/77 | **77/77** |
| NOT_FOUND parity | reported 96/96 (loose); 92/96 under the review's re-count | **95/96** (strict: complete query, and the deterministic search must be NOT_FOUND). Published 68/68; completed but not published 27/28 |
| Packets at the record budget | none | none |
| Pruning entries across the compared rows | 34 (rule-1.2 de-duplication drops) | 0 |

**The 4 misses from the review's re-count are now covered.** They were EXC-CASE-02 `SEARCH-04` and `SEARCH-06` `{IN-11, txn_id TX-0915-00009}`, in the Clone E and showcase stores. This is a direct result of the DR-01 fix.

**The one remaining miss** (exact, not hidden, and not covered by changing the matcher):

| Store | Status | Pack / exception | Model search | Query |
|---|---|---|---|---|
| clone-e | completed, not published | `PACK-CASE-PER-2026-09-109a585702ae` / EXC-CASE-01 (route `unverified_relationship`) | `SEARCH-08` | `{"evidence_id": "IN-13:SL-SB-GBP-20260915-0003", "relationship": "settlement_line_to_transaction", "value": "TX-0915-00009"}` |

- The model searched with `follow_relationship`, so its query has a relationship shape.
- The deterministic packet holds the **same fact** in file shape: `SEARCH-01 {"file": "IN-11", "txn_id": "TX-0915-00009"}` NOT_FOUND. The referencing line `IN-13:SL-SB-GBP-20260915-0003` is in the packet, and the transaction is not in that pack's data.
- The strict matcher deliberately does not translate relationship-shaped queries into file-shaped ones, so this is reported as a miss.
- Counting it as covered would need an explicit, approved equivalence rule (§8).
- This miss was also invisible to the review's own re-count, whose key ignored the `evidence_id`, `relationship` and `value` fields.

## 8. Remaining limitations

1. **Strict NOT_FOUND parity is 95/96, not 96/96.** The miss is a query-shape difference with the fact present (§7). Closing it needs a decision:
   - accept it as an equivalent, with a documented and tested relationship-to-file equivalence in the harness only; or
   - leave it as a known miss.
2. **10 restored NOT_FOUND searches are near-duplicates.** In S02 and H202602/05/07/08, rule 1.3 keeps an IN-07/IN-08 search that repeats an earlier one with an explicit `currency` the account already determines. Under your rule (same complete query; only date and reference synonyms folded), these are not identical, so they are kept.
   - The cost is about 10 small search entries; nothing is lost.
   - Folding `currency` when it is implied by `account_id` would need approval.
3. **Budget scope.** The budget governs **expansions**. The base packet from the existing route plan (`packet.retrieve`) is unchanged and capped by `MAX_RECORDS` (160), as in tools mode. If a base packet were above 140, no expansion would run (each one is refused and registered), but the base would not be cut. No fixture comes close: the largest base is 70 and the largest final packet is 77.
4. **Dependent records** are traced for the one tool traversal that depends on an earlier add (settlement line to transaction). Records that a skipped call (refused before running) would have fetched are not enumerated. The register records the refused call with its arguments, which is the auditable unit.
5. **Uncovered routes** (`generic`, `insufficient_evidence`): C07-BANK-EVIDENCE, BC-VS-EOD, DQ23-STATEMENT and UNMATCHED_CASHBOOK_ENTRY still fall back to tools mode. This is unchanged and outside the scope of this work.
6. **Still open from the review** (out of scope here, not started): DR-04 (amount comparison on links that are not one-to-one), DR-05 (the reconstruction "exact" claim), DR-08 to DR-12.

## 9. Environments untouched (verified at the end)

- **Clone E** (`p10/uc042_e`) matches `source_manifest_clone_e.json`: unchanged.
- **No file newer than the review** in `p10/uc042`, `p10/uc042_e`, `p10/env_e`, `p10/env_s` or the live `Downloads/UC042_CLAUDE_CODE_HANDOFF/uc042`.
- **In the copy,** the packs, `demo_history`, `uc042_dataset`, `investigations`, `tests/golden` and `uc042lib/final_pack` trees are identical to Clone E. Guard pins are unchanged (`final_pack` is still `bf2dc23b…`), and `test_demo_history` passes in the full run.
- **Code that must not change:** `validation.py`, `tools.py` and `packet.py` are byte-identical to Clone E. Prompts (1.6 / 2.6-tools), the model view (1.1), the output budget (12000), the application mode (tools) and the library default (fixed) are unchanged. The Phase 2 patch is not applied.
- **Databases:** only `uc042_token_opt_test`, through the tests. No other database was opened, and no migration was run.
- **No live AI call** and no token-counting call was made.
- **Services** on 8031 and 5191 are untouched and still listening.
- The only files changed since the review are the four code and test files in §1 and the two corrected documents. Everything else written is in `docs/token_optimisation/` and in this report.

## 10. Exact next action

1. **Owner decision on §8.1** (the relationship-shaped NOT_FOUND equivalence) and **§8.2** (folding a `currency` implied by the account). Neither is needed for correctness; both affect only reported parity and packet size.
2. **Then remediate DR-04 and DR-05** in the same copy, with the same approach (failing tests first):
   - DR-04: compare amounts only on links that are one-to-one in both directions, using signed values; view 1.2.
   - DR-05: preserve order so the packet hash reproduces, or correct the claim.
   - Fix DR-12 (prompt wording) in the same prompt bump; DR-09 to DR-11 can follow.
3. **Only then** ask the owner to approve the Phase 7 A/B budget. Phase 6 is no longer blocked by DR-01 to DR-03, but the A/B test still depends on DR-04 and DR-05.
