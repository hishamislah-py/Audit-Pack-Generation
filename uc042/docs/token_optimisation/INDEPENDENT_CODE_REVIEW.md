# UC-042: Independent Code Review, AI Reliability and Token Optimisation

**Date:** 16 November 2026
**Scope:** `p10/uc042_token_optimisation` against Clone E (`p10/uc042_e`)
**Mode:** read-only. No source, prompt, schema, guard, database or configuration was changed. No live AI call, token-counting call, deployment or migration was made.
**Reviewers:**
- the implementing session, reviewing reviews A–D and H;
- a separate agent with no access to the implementation reasoning, reviewing E–G.

Every finding the separate agent reported was re-reproduced by the main reviewer before inclusion (commands in §9).

**Inputs read:**
- `IMPLEMENTATION_vs_CLONE_E.patch` (37 files), `files_changed.txt`
- the implementation report
- `PHASE2_closing_summary_PROPOSED.patch`, `PHASE7_AB_TEST_PLAN.md`, `PHASE8_MIGRATION_READINESS.md`
- `det_parity_v12.json`, `packet_sizes.json`
- the final test outputs
- the three original assessment reports
- the source of `config.py`, `llm.py`, `tool_loop.py`, `graph.py`, `prompts.py`, `packet_view.py`, `det_retrieval.py`, `validation.py`, `final_pack/summary.py`, `investigation_reviews.py`, `routers/packs.py` and the changed frontend files

## Summary

The reliability changes (phases 1–3), the closing-summary patch (phase 2) and the UI fixes are sound.

The token-optimisation work has **two confirmed High defects** in deterministic retrieval and its parity evidence:

- **DR-01:** the search de-duplication drops distinct NOT_FOUND searches. In SC5A EXC-02 (and EXC-CASE-02) this removes the NOT_FOUND evidence for the missing transaction TX-0915-00009.
- **DR-02:** the parity harness's loose matching hid DR-01. The reported **96/96 NOT_FOUND parity is really 92/96**.

There are also **Medium** defects:

- amounts are compared on links that are not one-to-one (DR-04);
- records cut by tool caps are not registered as pruned (DR-03);
- the report overstates reconstruction as exact (DR-05).

**Phase 6 is not ready for the A/B test until DR-01 to DR-03 are fixed and parity is re-run.** The record parity claim itself, 162/162 instances and 77/77 distinct, was independently reproduced and holds.

---

## 1. Confirmed defects

| ID | Severity | File and location | Finding | Evidence | Consequence | Recommendation | Approval required |
|---|---|---|---|---|---|---|---|
| **DR-01** | **High** | `uc042lib/investigation/det_retrieval.py` `_norm()` (≈ l.110–114) and `expand()` step 4 (≈ l.170–178) | De-duplication keys a search only on file, account, date and reference. It ignores `txn_id`, `batch_id`, `client_id`, `txn_type`, `payment_reference` and date ranges. `seen` also holds FOUND searches, so a NOT_FOUND search can be dropped as a "repeat" of a FOUND search with a different query. The register reason "repeats an earlier NOT_FOUND search" is then false | Reproduced (`verify_f.py`): **SC5A EXC-SC5A-02**: base `SEARCH-04 {'file':'IN-11','txn_id':'TX-0915-00009'}` NOT_FOUND is absent from the deterministic packet and from its `allowed_citation_ids`; the register records it as a de-duplication. **SC5D EXC-SC5D-01**: `SEARCH-02 {'file':'IN-11','client_id':'C0003','txn_type':'REFUND'}` NOT_FOUND is dropped the same way (also EXC-02/03 per the second reviewer). The S02 / H2026xx IN-07/IN-08 drops (10) are genuine equivalents | In deterministic mode the model cannot cite the key negative evidence (the transaction a settlement line references is not in the data). That weakens missing-evidence handling, the core SC5A finding, and could change `missing_evidence` and the quality gates | De-duplicate only when the earlier search is **also NOT_FOUND** and the **full** normalised query is equal: map date and reference synonyms, keep every other key. Bump `uc042-det-retrieval` to 1.3 | No (code fix in the copy). The rule version bump is recorded |
| **DR-02** | **High** (evidence integrity) | `tests/det_parity.py` `run()` NOT_FOUND coverage (≈ l.104–110) | Coverage passes if any deterministic search shares `_q` fields 0–3, ignoring `txn_id` and `batch_id`. It never requires the deterministic search to be NOT_FOUND. This masked DR-01 | Strict re-count (second reviewer's `r7.py`, rerun by the main reviewer): **cited 96, covered 92**. The misses are EXC-CASE-02 `SEARCH-04` and `SEARCH-06` `{'file':'IN-11','txn_id':'TX-0915-00009'}` in the Clone E and showcase stores. Also: **22 of the 51 "investigations" are FAILED attempts with no cited targets**, so all 162 targets come from 29 COMPLETED runs. `miss_items_preserved` and `candidates_unchanged` are true by construction (taken from `case`). 2 fixed-mode records are skipped silently | The report and Phase 8 state 96/96 NOT_FOUND parity and "51 investigations"; both overstate the evidence | Match on the full query key and require `result == NOT_FOUND`. Report COMPLETED runs separately. Drop or rework the two trivially-true checks. Re-run and correct the report, §11 and Phase 8 | No |
| **DR-03** | Medium | `det_retrieval._run()` (≈ l.95–107) | The record budget is checked only **before** each tool call. Records a call does not add (per-call cap 25, packet cap `MAX_RECORDS` 160) are not written to the pruning register; only `retrieval_truncated` is set | Second reviewer (`r4.py`, budget reduced to `DET_MAX_RECORDS=52`, `MAX_RECORDS=55`): S05 EXC-01's `get_settlement_batch` took the packet from 51 to 55 records; 6 lines were not added (e.g. `IN-13:SL-AQ-GBP-20260917-0005`) with no register entry. At production values a call starting at 139 can overshoot 140. No real fixture reaches the budget (largest 77), so the path is untested on real data | The "no silent pruning" claim does not hold at the boundary. Evidence could be dropped without an audit trail | Record the tool result's `not_added` / `truncated` IDs in the register, or refuse a call when `len(records) + per_call_cap > budget`. Add a boundary test |
| **DR-04** | Medium | `uc042lib/investigation/packet_view.py` `verified_links()` and `COMPARED` (≈ l.28–32, 96–100) | The column header says "(1:1 links only)", yet amounts are compared whenever the relationship type is in `COMPARED`, including a batch or cash-book entry that links to **two** bank entries. `_num` also compares magnitudes only, so opposite directions would show as "agree" | Reproduced (`verify_f7.py`) on H202606 EXC-01: `IN-12:SB-GBP-20260601 → IN-09:BE-GBP-0601-SB1` gives `['3449.50','3449.50',True]` and `→ IN-09:BE-GBP-0610-SB1` gives `['3449.50','2344.78',False]`; the same for `IN-10:LE-GBP-0601-0005`. The second reviewer counted 24 such rows | The model is shown a part-to-whole or split link as an amount disagreement. That invites a discrepancy statement the engine did not make, and contradicts the stated contract | Compare only when the source has exactly one target **and** the target has exactly one source for that relationship. Otherwise emit `null`. Optionally compare signed values using the direction fields. View version 1.2 |
| **DR-05** | Medium (claim accuracy) | `packet_view.reconstruct_packet()` (≈ l.197–232); report §3 and §4 Phase 4 | Reconstruction is **content-equal as sets**, not exact. The order of `source_records`, `relationships` and `control_results` (and key order) is not preserved, so `packet_sha256` cannot be recomputed from the view | Reproduced: of 76 packets, the hash recomputed from the reconstruction differs in **57**, and exact list-order equality holds in 19. `test_model_view_lossless` compares sorted or keyed collections by design | Nothing sent to the model is lost (no correctness defect). The report's "rebuilds the stored packet exactly", and the docstring's suggestion that auditors can use the view, are wrong | Either carry the original order (an index per row) so the hash reproduces, or correct the claim to "content-lossless (order-insensitive)". The stored packet and its hash are unaffected either way |

## 2. Lower-severity defects and gaps

| ID | Severity | File and location | Finding | Evidence | Consequence | Recommendation | Approval required |
|---|---|---|---|---|---|---|---|
| DR-06 | Low | `packet_view._table` / `render_model_view` | Latent loss on unusual inputs: a key missing from some rows of a file comes back as `None`; two different `source_file` / `file_sha256` values under one `file_id` collapse to one; duplicate derived edges collapse; `evidence_ids: None` crashes reconstruction | Second reviewer's synthetic packets (`r5.py`). None of these shapes occurs in the 129 real packets | A future pack shape could lose provenance silently | Use a missing-value sentinel; key provenance by (file_id, source_file, sha); assert in `render_model_view` that `reconstruct(render(p))` is set-equal, and fail closed | No |
| DR-07 | Low | `packet_view.render_model_view` `cited_without_edge` | In 39 cases an edge for the same pair exists but with a different `join_key`, so the "no such edge" wording is inaccurate. Reconstruction is still lossless | Second reviewer, SC3C-01 `C11-BATCH-BANK|AQ-GBP-20260908 → IN-09:BE-GBP-0908-AQ1` | Cosmetic and misleading to a reader of the view | Relabel (for example "edges not derivable from evidence_ids") | No |
| DR-08 | Low | `llm.py` `OpenAIInvestigator.__init__` (`max_retries=2`) | The SDK's internal retries (429 / 5xx) are separate HTTP requests with no telemetry entry. Telemetry is per application-level request, not per HTTP request | Code: `openai.OpenAI(..., max_retries=2)`; `_failed_request` only after the SDK gives up | Request counts can be understated under rate limiting (billed usage is not affected for failed calls) | Document it, or set `max_retries=0` and retry explicitly with telemetry | Owner (behaviour change) |
| DR-09 | Low | `uc042app/services/reviews.py` (≈ l.372–378) | A failed closing summary becomes `unavailable_closing_summary(...)` and discards `LLMCallError.telemetry`, so billed usage of a failed summary is not stored. Successful summaries do keep `provider_response.responses[]` | Code path: `ClosingSummaryError` wraps the error, and only `kind` and `detail` are kept | DEF-14 is incomplete for summary failures | Keep `getattr(e.__cause__, 'telemetry', None)` in the job result or the review metadata | No |
| DR-10 | Low | `uc042app/services/investigation_reviews.py` `exception_history` (DEF-09) | (a) `same["details"].setdefault("validation_status", …)` is a no-op, because the job event always has that key (possibly `None`). (b) Matching is by time only (±10 s) and a job event can absorb several not-published records | Code reading; `test_ui_secondary_backend` covers only the one-to-one case | A second quick attempt's record could be hidden; the record's own validation status is never shown | Assign when the value is `None`; remove a matched job event from `failed_at` once used; prefer matching on the job's `investigation_id` / record when available | No |
| DR-11 | Low | `frontend/src/lib/labels.ts` `readableFailure` | "model refused: …" (a provider refusal) matches `refused` and is explained as "did not pass the application's validation" | Code reading | A misleading plain-language reason (the technical text is still shown under "Technical details") | Add a `model refused` branch before the validation branch | No |
| DR-12 | Low | `prompts.py` SYSTEM_PROMPT citation-classes rule | `contradictory_evidence` names both the hypothesis field (allowed for CAND-) and the top-level contradictions list (not allowed) in one sentence: "…ONLY in a hypothesis (supporting_evidence or contradictory_evidence) … and never in contradictory_evidence" | Code reading; `models.Hypothesis.contradictory_evidence` and `LLMInvestigationOutput.contradictory_evidence` | Ambiguous instruction. The validator still refuses a misuse (`_check_contradictions`), but the result could be a refused investigation | Say "the top-level contradictory_evidence list" explicitly | Yes (prompt version) |

## 3. Risks that require live verification

| ID | Risk | Why it cannot be settled offline |
|---|---|---|
| LV-01 | Whether the 12,000 budget plus concise guidance stops SC3C truncation, and what it costs | Output length is model behaviour; only telemetry from runs shows it |
| LV-02 | Whether `gpt-6-luna` respects `citation_classes` (SC5A 3/3 refusals before) | The validator still refuses a violation; compliance can only be observed live |
| LV-03 | Whether the model view (no embedded schema, compact tables) changes answer quality | Structured output is still enforced by `text_format`, but readability for the model is empirical |
| LV-04 | The token estimates (≈ 0.35–0.37 tokens per character; deterministic SC3C ≈ 22–23k input) | Estimates only. The single-request guard uses `chars // 3`, slightly more permissive than that calibration (≈ 2.8 characters per token), but far below any context limit |
| LV-05 | Whether verified links really remove the redundant `follow_relationship` calls | Tool choice is model behaviour |

## 4. Design concerns (no defect today)

- **D-01.** The size guard applies only to adapters with `uses_model_view` (OpenAI). Other adapters have no single-request guard. This is acceptable while OpenAI is the only provider.
- **D-02.** The uncovered kinds C07-BANK-EVIDENCE (10), BC-VS-EOD (9), DQ23-STATEMENT (1) and UNMATCHED_CASHBOOK_ENTRY (3) have no deterministic plan. They route to `generic` and fall back to tools mode, and the fallback is written to the trace. Real-case parity for them is therefore **untested**, and so is the CASE pack's generic route.
- **D-03.** Next-day batch over-fetch: none observed. Step 2 could still expand a batch already in evidence that settles on a next-day anchor (unverified risk).
- **D-04.** The prompt names `amounts_agree`, but the view's column is "amounts [from, to, agree]". This is a naming mismatch.
- **D-05.** The CHECK_LABELS are authored text, not engine names. All 11 codes exist in the engine (control names checked), but the wording (for example DQ23-STATEMENT, "Bank statement data-quality issue", against the engine's "Within-statement continuity") needs BA confirmation.
- **D-06.** "Mandatory: every exception of a processed pack is investigated automatically" is accurate for Clone E's auto-investigation design, which runs after a recorded authorisation. BA should confirm the wording.
- **D-07.** DEF-11 widened the document column in `DocumentTable`. The Reassessment table (`components/report/Reassessment.tsx`) has the same file-name cell and was not changed.
- **D-08.** `uncached_input_tokens` is not stored explicitly; it is derivable as input minus cached. The plan's measures should compute it rather than expect a field.

## 5. Items verified correct (should not be changed)

| Area | Verified |
|---|---|
| **A. Output budget** | `investigate()` and `tool_turn()` use `investigation_max_tokens` (`UC042_INVESTIGATION_MAX_OUTPUT_TOKENS`, default 12000, configurable). `structured_request()` (closing summary) uses `max_tokens` (`UC042_LLM_MAX_TOKENS`, 8000). No code path lets the investigation setting raise the summary budget. The Anthropic legacy adapter is unchanged. Truncation (`status: incomplete`, `max_output_tokens`) raises a non-retryable `LLMCallError` before parsing, so no partial output reaches validation; the result is FAILED / NOT_VALIDATED / unpublished (tests for fixed and tools mode). The concise-output rule ends with "Every finding still gives title, audit_relevance, establishes and does_not_establish"; the schema (required fields) is unchanged |
| **B. Candidates** | `citation_classes` only partitions `allowed_citation_ids`, never widens them (test asserts the union). `validation.py` is byte-identical to Clone E. A candidate in `evidence_ids` is refused, and a candidate in `supporting_records` is refused (not a record ID). SC5A offline: a hypothesis citing `CAND-SC5A-01` beside valid confirmed findings is VALID and published; the same output with CAND in a confirmed finding is REJECTED and not published. Verified links never contain CAND- or contextual edges |
| **C. Phase 2 patch** | Applies cleanly (`patch --dry-run`) in a scratch copy. The recomputed `tree_digest` of the patched `uc042lib/final_pack` is **`bd6dfdbcd7e9d74e1af7ed05503e415f428ac644ff77d088e6c9d5aa8a774102`** (18 files), exactly the proposed value; the current value is `bf2dc23b…` (18). `_is_clean` requires engine `CLEAN`, no exceptions, an empty missing-evidence register, `missing_evidence_items` = 0 and no investigations. In the shipped packs it is true only for S01, H202601 and H202604 (all CLEAN / COMPLETE / 0 exceptions); `EVIDENCE_INCOMPLETE` and `EXCEPTIONS_OPEN` packs never get the pack ID. Blank and unknown refs are still refused (validator unchanged; `SummaryItem.source_refs` min 1). Causal phrases: the prompt names all five `CAUSE_PATTERNS`, and the validator still refuses "because of". Final-pack assembly, the renderer and the schemas are untouched; only prompt 1.1→1.2 and input 1.0→1.1 change |
| **D. Telemetry** | Each application-level request gets one entry: fixed and summary attempts are appended per attempt, and each tool turn appends one entry with `turn=calls`. Errors without a body are recorded with `status: error` and `error_kind`. The aggregate equals the sum (test). Corrective retries are recorded as two entries. A failed fixed-mode run keeps usage via `e.telemetry`. Only sizes are stored, never prompt or evidence text. Investigation identity (`investigation_id_from_findings` excludes `usage` and `provider_response`) is unchanged (test) |
| **E. Model view** | Deterministic (0 differences on re-render). Every record keeps its `evidence_id`, `source_line`, `retrieved_via` and `join_key`, and per-file `source_file` and `file_sha256`. Content is lossless as sets on all 129 real packets (76 base + 53 deterministic). `allowed_citation_ids` and `packet_sha256` (passed through) are unaffected. `model_view_version` and `model_view_sha256` are recorded. The schema is removed only from the user message; `text_format=LLMInvestigationOutput` still enforces it |
| **F. Verified links** | For all 129 packets, `follow_relationship` was run from every eligible record (targets inside the packet). The listed set equals the tool set with **0 mismatches** in source, target and join value. Part-to-whole types (line→batch, transaction→batch) are never compared. The OWN_FUNDS_TOPUP date edge and same-reference edges are only under contextual associations. The tools prompt says not to re-confirm listed links but still allows "records or links that are not in the evidence" |
| **G. Deterministic retrieval (parts that hold)** | Pack hash verification is unchanged (`load_pack` / `EvidenceStore`; `persistence.py` unchanged). Expansion uses `tools.execute`, so provenance is identical to tools mode. MISS items are unchanged. Candidates stay separate. Record parity of **162/162 instances and 77/77 distinct was independently reproduced**. SC3C-01 fetches `IN-05:IRR-EMONEY-GBP-20260909`. SC5C stays bounded (9–10 → 12–16 records). The size guard runs before `investigator.investigate()` and returns with **no request sent** (test). Unsupported routes switch to tools mode and write `fallback` to the trace. The app still passes `mode="tools"` (`uc042app/services/investigations.py:321`); the library default is still `fixed` |
| **H. UI and API** | DEF-05 wording; DEF-06 (pack API adds `candidate_relationships` with a default-empty schema field, so it is backward-compatible; `api/types.ts` is optional; the frontend filters by the engine's `"; "`-separated `exception_ids`, which matches every real pack); DEF-07 (unknown codes fall back to the control name, never a guessed label; all mapped codes exist in the engine); DEF-08; DEF-10 (technical text kept under "Technical details"); DEF-12 (neutral zero; the env tag wraps). DEF-13 was not changed |

## 6. Approval-gated items

| Item | Exact approval required |
|---|---|
| Phase 2 closing-summary patch | Owner approval to apply `PHASE2_closing_summary_PROPOSED.patch` **and** to re-pin `tests/test_demo_history.py` PROTECTED `"uc042lib/final_pack"` from `("bf2dc23bbc516b50bd19393fbbd9e5bfa00907b2115a04455d210b3e8c709cae", 18)` to `("bd6dfdbcd7e9d74e1af7ed05503e415f428ac644ff77d088e6c9d5aa8a774102", 18)`, plus acceptance of summary prompt 1.2 and input 1.1. Existing final packs are unaffected; existing review previews would show as stale and need regenerating, because the summary fingerprint includes the input version |
| Prompt versions | 1.6 / 2.6-tools (after the DR-04 / DR-12 fixes, expect 1.7 / 2.7-tools and view 1.2) |
| Output budget | `UC042_INVESTIGATION_MAX_OUTPUT_TOKENS` = 12000 |
| Live A/B | Budget ≈ 1.25M tokens (minimum) or ≈ 2.7M (full), both estimates |
| Per-route migration (phase 8) | Only after the A/B gates |
| DEF-13; DEF-07 and DEF-08 wording | BA decision or review |
| DR-08 retry policy change | Owner (if chosen) |

## 7. Tests run by this review (offline, exact commands)

All commands ran from `p10/uc042_token_optimisation` with `PYTHONPATH=/c/Users/artlptp263user/p10/env_e/shims PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8`.

| Command | Exit | Result |
|---|---|---|
| `env -u UC042_TEST_DATABASE_URL -u UC042_TEST_REPOSITORIES python -m unittest tests.test_phase1_reliability tests.test_phase3_telemetry tests.test_phase4_model_view tests.test_phase5_verified_links tests.test_phase6_deterministic tests.test_ui_secondary_backend tests.test_demo_history tests.test_closing_summary tests.test_openai_provider` | 0 | **Ran 142 tests, OK** (50.6 s) |
| `patch -p1 --dry-run < docs/token_optimisation/PHASE2_closing_summary_PROPOSED.patch` (in a scratch copy of `uc042lib/final_pack` and `tests/test_closing_summary.py`), then `tree_digest` | 0 | Applies; digest `bd6dfdbc…` (18 files) |
| `python <scratchpad>/verify_f.py` (reconstruction hash, SC5A-02 / SC5D-01 de-duplication) | 0 | 57/76 hash differences; SEARCH-04 and SEARCH-02 dropped |
| `python <scratchpad>/verify_f7.py` (H202606 amount comparison) | 0 | Non-one-to-one comparisons present |
| `python <scratchpad>/review/r7.py` (strict NOT_FOUND parity; reads the investigation stores, writes nothing) | 0 | 96 cited, **92 covered** |
| Second reviewer: `r1`–`r10.py` (losslessness, synthetic edge cases, links against the tool, budget boundary, parity re-run) | 0 | See the findings above |

The implementation's own recorded results, not rerun in full here: file mode 725 OK (24 skipped); PostgreSQL (`uc042_token_opt_test`) 142 OK; vitest 78 passed and 2 skipped; build OK. No formatter, auto-fix, migration or DB reset was run.

## 8. Decisions

1. **Is Phase 1 safe to approve?** **Yes, conditionally.** The budget isolation, the truncation handling and the candidate contract are correct and strictly validated. Clarify the DR-12 wording in the same prompt bump. Approval covers the 12,000 budget and the prompt version.
2. **Is the Phase 2 patch safe to approve for protected re-pinning?** **Yes.** The change is narrow, the validator is unchanged, clean-pack detection is strict, and the proposed digest was independently reproduced. Approve the exact re-pin in §6.
3. **Is Phase 3 telemetry ready?** **Yes, for the A/B.** Fix DR-09 (failed-summary usage) and document DR-08 (SDK retries) before relying on request counts.
4. **Is the Phase 4 model view safe?** **Yes, as content-lossless input for the model.** Correct the "exact" claim or carry the order (DR-05). DR-06 hardening is recommended but not blocking.
5. **Is the Phase 5 relationship optimisation safe?** **Not yet.** Links equal the tool's results exactly, but DR-04 (amounts compared on non-one-to-one links) must be fixed first. This is a small change.
6. **Is Phase 6 deterministic retrieval safe to A/B test?** **No, not until DR-01, DR-02 and DR-03 are fixed and parity is re-run** with the strict matcher, and the 96/96 claim is corrected.
7. **Is the implementation ready for the live A/B test?** **No.** It will be ready once the items in decision 8 are done and the owner approves the prompt versions, the output budget and the A/B budget.
8. **What must be fixed before the next gate?**
   - DR-01 (search de-duplication; rule 1.3);
   - DR-02 (strict parity matcher, re-run, report corrections);
   - DR-03 (register cap-truncated records, boundary test);
   - DR-04 (one-to-one-only amount comparison; view 1.2);
   - DR-05 (claim correction or order-preserving view);
   - DR-12 (prompt wording);
   - recommended in the same pass: DR-09, DR-10, DR-11.

## 9. Approval recommendation

- Approve **Phase 2** (re-pin as specified) and **Phase 3** now.
- Approve **Phase 1** together with the next prompt bump, after DR-12.
- Hold **Phases 4–6**, and therefore the **live A/B test**, until DR-01 to DR-05 are fixed in the copy and the strict parity is re-run and reported.

None of these fixes needs a validator change, a guard change or a live call.

## 10. Confirmation of non-modification

- This review changed **no** source, test, prompt, schema, guard pin, fixture, pack, investigation, database or configuration, in this copy or anywhere else.
- The only file written in the project is this document.
- Scratch scripts and the patched scratch copy are in the session scratchpad only.
- No live OpenAI call, token-counting call, deployment or migration was made.
- Clone E, P10, `env_e`, `env_s`, the live application and the services on 8031 and 5191 were not touched.

Verified at the end of the review:
- a fresh `diff -ruN uc042_e uc042_token_optimisation` is byte-identical to `IMPLEMENTATION_vs_CLONE_E.patch` (generated 12:53), so the implementation is unchanged by the review;
- Clone E matches `source_manifest_clone_e.json`;
- no file in `p10/uc042`, `p10/uc042_e`, `p10/env_s`, `p10/env_e` or the live `uc042` is newer than that patch;
- 8031 and 5191 are still listening.

The implementation report's claims of "96/96 NOT_FOUND" and "rebuilds the stored packet exactly" were left as they are (this review does not edit it). DR-02 and DR-05 record the corrections.
