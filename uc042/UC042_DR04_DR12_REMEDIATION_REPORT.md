# UC-042: Sequential Remediation, 96/96 Parity, Exact Reconstruction and DR-04 to DR-12

**Date:** 16 November 2026
**Project:** `C:\Users\artlptp263user\p10\uc042_token_optimisation`, the isolated copy of Clone E
**Starting baseline (verified before any change):**
- the tree was byte-identical to `docs/token_optimisation/IMPLEMENTATION_vs_CLONE_E_after_DR01_DR03.patch`;
- rule `uc042-det-retrieval/1.3`; model view `1.1`; prompts `1.6` / `2.6-tools`; guard `final_pack` `bf2dc23b…`;
- `det_parity_v13.json`: 95/96, with only `SEARCH-08` missing.

A file snapshot of that baseline was the reference for the new diff.

**Mode:** offline only. There were no live OpenAI, Groq, embedding or token-counting calls, no A/B test, no deployment and no migration. The application mode stays `tools`.

Each stage was run test-first. The failing tests (or a probe, where the tests could not import) were saved in `docs/token_optimisation/dr04_12_logs/stageN_red*.txt`. Each stage was then fixed and gated before the next one started. No stage failed its gate.

## Summary

| Stage | Finding | Result | Gate tests (exit 0) |
|---|---|---|---|
| 1 | Strict NOT_FOUND parity | **96/96**: 95 exact + **1 approved semantic equivalence**, reported separately; 0 missed | 38 OK |
| 2 | DR-05 exact reconstruction | **76/76 packets exact, 76/76 hashes match** (plus 53/53 deterministic packets); view 1.2 | 93 OK |
| 3 | DR-04 amounts | Compared only on two-way one-to-one links, with **signed** values. The 24 non-one-to-one comparisons are removed; the 364 one-to-one comparisons are unchanged | 42 OK |
| 4 | DR-06 / DR-07 | Missing-value sentinel; per-record provenance; duplicate edges; `evidence_ids: None`; fail-closed render (nothing sent); the wording is fixed | 114 OK |
| 5 | DR-08 / DR-09 | SDK retries documented and recorded per request (`max_retries=2` unchanged); failed-summary telemetry kept in the success shape | 84 OK |
| 6 | DR-10 / DR-11 | History matches by record name (exact), with a one-to-one legacy time fallback; provider refusals described correctly | 53 OK (1 PostgreSQL-only skip); vitest 81 passed |
| 7 | DR-12 | The two `contradictory_evidence` meanings are named; prompts **1.7 / 2.7-tools**; validation unchanged | 80 OK (1 skip, as before) |
| 8 | Integrated | Full backend **814 OK** (24 skipped, as at baseline); PostgreSQL **191 OK**; vitest **81 passed / 2 skipped**; build OK; DR and guard **150 OK** | see §8 |

## 1. Stage 1: strict NOT_FOUND parity 96/96 (approved semantic equivalence)

**Evidence that the equivalence is real** (from the source data; `test_source_data_establishes_the_equivalence`):
- `tools.RELATIONSHIPS["settlement_line_to_transaction"] = ("IN-13", "txn_id", "IN-11", "pk", …)`: a primary-key join of the line's `txn_id` to `IN-11`. `IN-11`'s primary-key field is `txn_id`.
- The source record `IN-13:SL-SB-GBP-20260915-0003` is `source_data/settlement_lines_2026-09.csv` line 201, with `txn_id = TX-0915-00009`. This equals the relationship query's `value`.
- `tools.follow_relationship` performs `store.get("IN-11:TX-0915-00009")`, which is the same lookup behind the file-shaped search `{"file":"IN-11","txn_id":"TX-0915-00009"}` (`packet.py:187`, `tools.py:258`).
- In that pack's data the lookup returns `None`, and no `IN-11` row has that `txn_id`: both searches state the same NOT_FOUND fact.
- The deterministic `SEARCH-01` describes itself as "Transaction TX-0915-00009 referenced by settlement line SL-SB-GBP-20260915-0003", and that line is in the deterministic packet.
- The model's record is `env_e/investigations/_not_published/PACK-CASE-PER-2026-09-109a585702ae/EXC-CASE-01/2026-11-12T081756+0000-c709e3c4.json`, with `SEARCH-08` NOT_FOUND. A different attempt has an unrelated `SEARCH-08`, which is FOUND.

**Implementation** (`tests/det_parity.py` only; production retrieval was not touched and the rule stays 1.3):
- `APPROVED_EQUIVALENCES = {"settlement_line_to_transaction": ("IN-13", "txn_id", "IN-11", "txn_id")}`.
- `relationship_equivalent_query()` applies only if:
  - the query's keys are exactly `evidence_id` / `relationship` / `value`;
  - the relationship is approved;
  - the source record exists in the pack's data, belongs to `IN-13`, and its own `txn_id` equals `value` exactly (checked against the data, not the query).
- `not_found_equivalent()` additionally requires the same line, with the same `txn_id`, to be a record of the deterministic packet, and a deterministic search with exactly `{file: IN-11, txn_id: value}` and result NOT_FOUND.
- It is tried only after the exact match fails.
- The summary reports `not_found_covered_exact` (95) and `not_found_semantic_matches` (1, with `matched_by: "approved semantic equivalence"` and the `equivalent_query`) separately.

**Tests** (`tests/test_stage1_parity_equivalence.py`, 12):
- Positive: the approved case matches by equivalence, and the exact matcher still fails on it.
- Negative:
  - a different transaction ID;
  - a different settlement line (another line, an unknown line, an empty ID);
  - a different relationship (`transaction_to_batch`, `settlement_line_to_batch`, `refund_to_original_transaction`, unknown);
  - a different file (`IN-12`);
  - a deterministic search that is FOUND;
  - a partial identifier (prefix, longer value, suffix, case, leading space, extra deterministic key);
  - extra or missing query keys;
  - the line missing from the deterministic packet;
  - the transaction ID alone.
- Summary: 96/96, exact 95, semantic 1, missed 0; records 162/162 and 77/77; rule 1.3.

The existing DR-02 test, which pinned the former miss, now pins it as the single semantic match, with `not_found_missed == []`.

## 2. Stage 2: DR-05 exact reconstruction (model view 1.2)

**Diagnosis:** the canonical hash (`uc042lib.pack.model.canonical`, `sort_keys=True`) ignores dictionary key order but not list order. The 57 failures came from exactly three lists: `source_records` (57), `relationships` (56) and `control_results` (39). `allowed_citation_ids` is stored sorted, so it already round-tripped.

**Implementation** (`packet_view.py`):
- **Records and control results** keep their compact, sorted table layout and gain a `packet_order` column with their original index.
- **`relationship_order`** is a string with one character per stored edge: `K` kept as listed, `C` contextual, `D` derived from `evidence_ids`.
- **`derived_order`** is emitted only when derived edges are not already in derivation order (22 of 76 packets).
- **`reconstruct_packet()`** rebuilds every list in stored order. It raises an error (fails closed) unless the positions are an exact permutation and the order string accounts for every edge.
- The hash convention itself is unchanged.

**Results** (`dr04_12_logs/final_reconstruction_hashes.json`):
- **76/76 packets `==` the original, 76/76 recomputed hashes equal `packet_sha256`.**
- 53/53 deterministic packets: exact, with matching hashes.
- The 57 view-1.1 ordering failures are pinned and covered.
- Synthetic orderings (reversed lists, interleaved and out-of-order derived edges, an empty relationship list with a single record) reconstruct exactly.
- A tampered order string or position raises.

**Token reduction:**

| | Characters (76 packets) | Smaller than raw | SC3C-01 |
|---|---|---|---|
| Raw packets | 1,948,282 | — | 84,495 |
| View 1.1 | 1,473,213 | 24.4% | 49,807 |
| View 1.2 final | 1,510,682 | **22.5%** | 50,606 |

The ordering data and the hardening notes cost about 1.9 points.

## 3. Stage 3: DR-04 signed, one-to-one amount comparison

**Implementation** (`packet_view.verified_links`, `_signed`, `SIGNS`, `AMOUNTS_COLUMN`):
- Every link is computed first, unchanged.
- Amounts are compared only if the relationship type measures the same movement (`COMPARED`; part-to-whole types are never included) **and** the source has exactly one target **and** the target has exactly one source for that relationship.
- Values are signed by each record's own direction field. A missing or unknown direction, or an unparsable amount, means no comparison (`null`). Absolute values are never used.
- The column is labelled "signed amounts [from, to, agree] (one-to-one links only; null = not compared)".

**Sign table, with the evidence for each entry:**
- `IN-09` bank: C = +, D = −. Packet `conventions.bank_dc`.
- `IN-10` cash book: D = +, C = −. `conventions.cashbook_dc`.
- `IN-11` transaction: CR = +, DR = −. `conventions.transaction_direction`.
- `IN-12` batch: TO_FIRM = +, FROM_FIRM = −. Consistent with the bank `dc_indicator` on all 11 one-to-one batch-to-bank links in the data.
- `IN-13` line: C = +, D = −. C matches CR and D matches DR on all 50 line-to-transaction links.

**Effect on the 76 real packets:**
- The link rows themselves are identical in 76/76.
- **24** comparisons on links that are not one-to-one were removed (including the review's H202606 rows: `SB-GBP-20260601 → BE-GBP-0601-SB1` and `→ BE-GBP-0610-SB1`, and the same for `LE-GBP-0601-0005`).
- The **364** one-to-one comparisons are kept, and no agree flag changed.

**Tests** (`tests/test_stage3_dr04_amounts.py`, 10): matching one-to-one amounts (both signs); opposite signs (equal magnitudes no longer "agree"); one-to-many; many-to-one; part-to-whole; missing amount, direction, unknown direction or unparsable value; H202606; every compared real link is one-to-one; `tools.py` byte-identical to Clone E.

## 4. Stage 4: DR-06 hardening and DR-07 wording

Before the fix, a probe (`stage4_red_probe.txt`) showed:
- a missing key returned as `None`;
- distinct provenance collapsed;
- a duplicate derived edge raised an error;
- `evidence_ids: None` gave a `TypeError` in both `verified_links` and reconstruction.

**DR-06 changes:**
- **`MISSING = {"__missing_key__": true}`:** used for a key absent from a row and dropped on reconstruction, so an explicit `None` stays `None`. A real value equal to the sentinel is refused (`ModelViewError`).
- **Provenance:** each distinct `(source_file, file_sha256, record_type)` under one `file_id` gets its own `source_files` entry, and rows carry `source_file_index` only when a file has more than one. Real packets have none, so they cost no extra tokens.
- **Duplicate edges:** duplicate derived and kept edges survive (`derived_order` may repeat an index).
- **`evidence_ids: None`** is handled everywhere.
- **Fail-closed invariant:** `render_model_view()` reads the view back exactly as it is sent (JSON) and raises `ModelViewError` unless it reconstructs the packet exactly. Every graph node is wrapped by `_guarded`, so the investigation is FAILED and **no provider request is sent** (tested in fixed and tools mode).

**DR-07:** `cited_without_edge` is renamed `evidence_ids_without_derivable_edge`, and both the reading guide and the code comment say "edges not derivable from evidence_ids". Relationship data and reconstruction are unchanged; the relationships of all 76 packets are identical.

**Tests:** `tests/test_stage4_dr06_dr07.py`, 11. All synthetic data is derived in memory, and no historical file is touched.

## 5. Stage 5: DR-08 and DR-09 telemetry

**DR-08** (`llm.py`):
- `SDK_MAX_RETRIES = 2`, used for `openai.OpenAI(max_retries=…)`. The behaviour is unchanged.
- The module docstring documents that SDK-internal HTTP retries (connection errors, timeouts, 408, 409, 429, 5xx) are not separate telemetry entries. As a result:
  - request counts are a lower bound on HTTP requests;
  - usage comes from the final response only;
  - `latency_seconds` includes the SDK's backoff;
  - application-level retries are separate entries.
- Every telemetry entry, including error entries, records `sdk_max_retries`.

**DR-09:**
- `OpenAIInvestigator.structured_request` now keeps `last_structured_request`: the metadata on success, the error's telemetry on failure. It is reset at the start of every call, and the class default is `None`.
- New `uc042app/services/reviews.summary_failure_record(error, investigator)` keeps `kind` and the redacted `detail`, and adds `telemetry_available` and `model_metadata` in the **same shape as a successful summary** (attempts, `provider_response.responses`, usage, provider, model, simulated, prompt and schema versions). Its sources are:
  - the wrapped `LLMCallError.telemetry`, for a provider or transport failure;
  - the investigator's last request, only for `invalid_summary` (a billed call whose output was refused).
- A failure before any request records no telemetry; earlier telemetry is never reused.
- `_build_preview` stores it under `closing_summary.failure`.
- Protected `uc042lib/final_pack` is **unchanged**.

**Tests** (`tests/test_stage5_telemetry.py`, 10):
- retry allowance unchanged and recorded;
- success;
- provider failure (incomplete);
- validation failure (billed usage kept);
- transport failure with no response body;
- no telemetry (configuration, unsupported provider);
- stale telemetry not reused;
- through the real preview job: failure and success.

## 6. Stage 6: DR-10 history and DR-11 labels

**DR-10:**
- `uc042app/services/investigations.py`: a NOT_PUBLISHED job result now records `not_published_record` (the record's file name).
- `investigation_reviews.exception_history`:
  - **exact match first** (a job that names its record matches only that record);
  - the time fallback (±10 s, `LEGACY_MATCH_SECONDS`) applies only to legacy job events that name no record, nearest first, with **one record per job event**;
  - the validation status is assigned when the job's value is `None` (an existing value is kept);
  - records with no job stay separate events.

DR-10 tests (`tests/test_stage6_dr10_history.py`, 9): closely spaced attempts (3 s apart); an identified job never absorbs another record; status assigned when `None` and kept otherwise; a legacy job absorbs at most one record; two legacy jobs and two records; records outside the window or with no job; and a real failed job end-to-end.

**DR-11:** `frontend/src/lib/labels.ts` has a new branch before the validation branch. `model refused` and `[refusal]` now read "The AI model declined to answer (a provider refusal). This is not a validation failure…". Validation refusals and the fallback are unchanged, and the technical text stays under "Technical details". Tests: `frontend/src/test/stage6Labels.test.ts` (3); before the fix, 1 failed and 2 passed.

## 7. Stage 7: DR-12 prompt wording (prompts 1.7 / 2.7-tools)

- The citation-class rule now says a candidate may be cited "inside a hypothesis (in that hypothesis's own supporting_evidence or contradictory_evidence field)", and "never anywhere in the TOP-LEVEL contradictory_evidence list (its C-01.. items: neither evidence_ids nor compared_evidence): a candidate is never confirmed evidence and never one side of a contradiction".
- **Also corrected in the same bump, because DR-04 changed the column:** the sentence "amounts_agree reports whether both amounts are equal" became "Their signed amounts column compares the two amounts (each signed by its own record's direction field) only for one-to-one links; null means not compared."
- **Validation is unchanged** (`validation.py` is byte-identical to Clone E). A candidate in a hypothesis's `contradictory_evidence` is VALID, and a candidate as one side of a top-level contradiction is still REJECTED.
- **Version pins** were updated in `tests/test_findings_schema_14.py` and `tests/test_review_hardening.py`.
- **Tests:** `tests/test_stage7_dr12_prompt.py`, 6.

## 8. Final integrated verification (Stage 8)

All commands ran from `p10/uc042_token_optimisation` with `PYTHONPATH=…/p10/env_e/shims PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8`. Logs are in `docs/token_optimisation/dr04_12_logs/`.

| # | Command | Exit | Result |
|---|---|---|---|
| 1–2, 9 | `python -m unittest tests.test_demo_history tests.test_dr01_dr03_remediation tests.test_stage1_parity_equivalence tests.test_stage2_exact_reconstruction tests.test_stage3_dr04_amounts tests.test_stage4_dr06_dr07 tests.test_stage5_telemetry tests.test_stage6_dr10_history tests.test_stage7_dr12_prompt` → `final_dr_and_guard.txt` | 0 | **150 OK**, including the protected-digest guard tests |
| 3 | `python -m unittest discover -s tests -t .` (file mode) → `final_full_backend.txt` | 0 | **814 OK, 24 skipped** (baseline 743 / 24; +71) |
| 4 | PostgreSQL on `uc042_token_opt_test` only (the guard refuses any other URL); 16 modules, listed in the command in the log → `final_postgres.txt` | 0 | **191 OK** (baseline 160) |
| 5 | `npx vitest run` → `final_frontend.txt` | 0 | **81 passed, 2 skipped** (14 files) (baseline 78) |
| 6 | `npm run build` | 0 | built |
| 7 | 76-packet reconstruction → `final_reconstruction_hashes.json` | 0 | **76/76 exact and hash-equal**; 53/53 deterministic |
| 8 | `python -m tests.det_parity docs/token_optimisation/det_parity_v15.json` | 0 | 53 records (51 compared, 2 fixed-mode excluded with a reason); records **162/162**, **77/77**; NOT_FOUND **96/96 = 95 exact + 1 approved semantic** (Clone E EXC-CASE-01 `SEARCH-08`); 0 missed; rule 1.3; 0 errors |
| 10 | Isolation checks | — | §11 |

The new backend tests total 68 test methods across seven new files; the suite counts 71, because two test classes reuse an existing harness. The DR-02 test, the Phase 6 parity test and two version pins were also updated.

## 9. Files changed (against the post-DR-01/03 baseline)

Manifest: `docs/token_optimisation/DR04_DR12_files_changed.txt` (20 files). Diff: `docs/token_optimisation/DR04_DR12_vs_post_DR01_DR03_baseline.patch` (1,812 lines).

| Area | Files |
|---|---|
| Library | `uc042lib/investigation/packet_view.py` (stages 2–4), `uc042lib/investigation/llm.py` (5), `uc042lib/investigation/prompts.py` (7), `uc042lib/investigation/config.py` (7) |
| Application | `uc042app/services/reviews.py` (5), `uc042app/services/investigations.py` (6), `uc042app/services/investigation_reviews.py` (6) |
| Frontend | `frontend/src/lib/labels.ts` (6); new test `frontend/src/test/stage6Labels.test.ts` |
| Test harness | `tests/det_parity.py` (1) |
| Tests, new | `tests/test_stage1_parity_equivalence.py`, `test_stage2_exact_reconstruction.py`, `test_stage3_dr04_amounts.py`, `test_stage4_dr06_dr07.py`, `test_stage5_telemetry.py`, `test_stage6_dr10_history.py`, `test_stage7_dr12_prompt.py` |
| Tests, updated | `tests/test_dr01_dr03_remediation.py` (stage 1 pin), `tests/test_findings_schema_14.py`, `tests/test_review_hardening.py` (prompt pins) |

**Unchanged:**
- `det_retrieval.py` (this round), `tools.py`, `packet.py` and `validation.py` (the last three byte-identical to Clone E);
- `uc042lib/final_pack/*` and every guard pin;
- packs, datasets, golden files and investigations;
- the application mode;
- the Phase 2 patch (not applied).

**Also written:**
- `docs/token_optimisation/IMPLEMENTATION_vs_CLONE_E_after_DR04_DR12.patch` (48 files against Clone E; no secret patterns);
- `det_parity_v14.json` (stage 1) and `det_parity_v15.json` (final).

All earlier reports, patches and parity files (`v1`, `v11`, `v12`, `v13`) are unchanged.

## 10. Versions now

| Item | Before | Now |
|---|---|---|
| Deterministic retrieval rule | 1.3 | **1.3** (unchanged) |
| Model view | 1.1 | **`uc042-model-view/1.2`**: one version for the whole unreleased revision (DR-05, DR-04, DR-06, DR-07), documented in the constant's comment |
| Fixed prompt | 1.6 | **`uc042-investigator-prompt/1.7`** |
| Tools prompt | 2.6-tools | **`uc042-investigator-prompt/2.7-tools`** |
| Closing-summary prompt / input / schema | 1.1 / 1.0 / 1.0 | unchanged (Phase 2 not applied) |
| Investigation output budget | 12000 | 12000 |
| Protected `uc042lib/final_pack` digest | `bf2dc23b…` | `bf2dc23b…` |

## 11. Isolation and no live calls

- **Clone E** matches `source_manifest_clone_e.json`: unchanged.
- **No file newer than the start of this work** in `p10/uc042`, `p10/uc042_e`, `p10/env_e`, `p10/env_s` or the live `Downloads/UC042_CLAUDE_CODE_HANDOFF/uc042`.
- **Databases:** row counts of `uc042`, `uc042_p10b`, `uc042_p10e` and `uc042_p10e_showcase` are unchanged. Only `uc042_token_opt_test` was used, by tests.
- **Copy data trees:** packs, `demo_history`, `uc042_dataset`, `investigations`, `tests/golden` and `uc042lib/final_pack` are identical to Clone E.
- **Services:** 8031 and 5191 were untouched and are still listening.
- **No live provider call** of any kind was made. Every provider interaction in the tests is a mocked OpenAI client.

## 12. Unresolved findings and limitations

1. **DR-13:** the BA decision on the "NOT APPLICABLE" label is still open (not in this scope).
2. **The same-second timestamp issue** is still reported only (not in this scope).
3. **The batch and settlement-line sign mappings** (`IN-12`, `IN-13`) are inferred from the data, consistently on every link (11 and 50). They are not stated in the packet `conventions`. A BA or owner should confirm them; until then, a direction value outside the mapping yields `null`, never a guess.
4. **Token reduction is now 22.5%** (24.4% under the content-lossless view 1.1). The difference is the price of exact reconstruction and the hardening notes.
5. **DR-09 coverage:** a validation-refused summary keeps its billed usage only when the review service holds the investigator, which the application always does. A direct library call without an investigator has no handle to read from; `final_pack` is protected and was not changed.
6. **DR-10:** legacy job events (before `not_published_record` existed) still use the time fallback, now one-to-one and nearest-first.
7. **Live behaviour** is unproven: whether the model follows the new wording, whether outputs stay within budget, and actual token usage.

## 13. Rollback

- **Whole round:** apply `docs/token_optimisation/DR04_DR12_vs_post_DR01_DR03_baseline.patch` in reverse (`patch -R -p0` from the project root), or discard the copy. No database, migration or data file was changed, so nothing else needs reverting.
- **Stage 1:** remove `APPROVED_EQUIVALENCES` and `not_found_equivalent` from `tests/det_parity.py`. Strict parity returns to 95/96 with the miss listed. Production is unaffected.
- **Stages 2–4 (model view):** revert `packet_view.py` to view 1.1. New investigations would then record `model_view_version` 1.1. Stored packets and hashes are independent of the view.
- **Stage 5:** revert `llm.py` and `reviews.py`. `max_retries` is the same either way. `closing_summary.failure` returns to `{kind, detail}` only.
- **Stage 6:** revert `investigation_reviews.py`, `investigations.py` and `labels.ts`. Job results that already contain `not_published_record` remain readable; the key is simply ignored.
- **Stage 7:** revert `prompts.py` and `config.py` (prompts 1.6 / 2.6-tools) and the two pins.

## 14. Readiness assessment

**Offline implementation readiness: READY.**
- Every review finding in scope (DR-01 to DR-12, except DR-13, which needs a BA decision) is implemented in the copy, each with failing-first regression tests.
- NOT_FOUND parity is 96/96, with the single equivalence reported separately.
- Reconstruction is exact (76/76 hashes).
- The full backend, PostgreSQL, frontend and guard suites pass.
- The validator, retrieval, protected library and data are unchanged.

**Live A/B approval readiness: NOT AUTHORISED by this work.** Passing offline tests does not authorise live testing. Before any live run, the owner must explicitly approve:
1. prompt versions **1.7 / 2.7-tools** and model view **1.2** (these change what the model receives);
2. the investigation output budget of **12,000**;
3. the **A/B budget** (≈ 1.25M tokens minimum or ≈ 2.7M full; both estimates; plan in `PHASE7_AB_TEST_PLAN.md`);
4. the **inferred sign mappings** for batches and settlement lines (§12.3).

The Phase 2 closing-summary re-pin remains a separate owner decision and was not applied here.
