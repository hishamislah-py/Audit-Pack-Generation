# UC-042: AI Investigation Reliability and Token Optimisation, Implementation Report

**Date:** 16 November 2026
**Project:** `C:\Users\artlptp263user\p10\uc042_token_optimisation`, an isolated copy of Clone E
**Live provider calls made:** none. Every AI behaviour below was exercised offline: the real `OpenAIInvestigator` was used with its HTTP client mocked.
**Inputs:**
- `UC042_CORRECTNESS_AND_FOUR_SCENARIO_SHOWCASE_ASSESSMENT.md`
- `UC042_API_CONSUMPTION_OPTIMISATION_PLAN.md`
- `UC042_DETERMINISTIC_INVESTIGATION_ARCHITECTURE_ASSESSMENT.md`

## Phase checklist

| Phase | Status | Tests | Approval required | Notes |
|---|---|---|---|---|
| 0. Isolation and baseline | **Done** | Baseline: 683 OK (24 skipped) file mode; 125 OK PostgreSQL; 74 + 2 skipped vitest | No | The copy was byte-identical to Clone E at creation (1,500 files, tree SHA `62b5b3fd…`). It has its own test DB, `uc042_token_opt_test` |
| 1. Investigation correctness | **Done** (in the copy) | `test_phase1_reliability` 11/11 | **Yes:** prompt versions 1.6 / 2.6-tools; the output budget of 12,000 | DEF-01: separate budget plus concise-output guidance. DEF-02: `citation_classes`. The validator is unchanged and still refuses a `CAND-*` in a confirmed finding |
| 2. Closing-summary correctness | **Prepared, NOT applied** | 7 new tests pass in a scratch copy; the only failure is the expected guard digest | **Yes:** guard re-pin `bf2dc23b…` → `bd6dfdbc…` | DEF-03 (clean pack) and DEF-04 (causal wording). `docs/token_optimisation/PHASE2_closing_summary_PROPOSED.patch` |
| 3. Telemetry | **Done** | `test_phase3_telemetry` 7/7; guard and historical-artefact tests pass | No (only new metadata keys) | DEF-14. Per-request entries in `provider_response.responses[]`; investigation identity unaffected |
| 4. Lossless model view | **Done** | `test_phase4_model_view` 8/8 (76 packets reconstruct exactly) | Covered by the prompt-version approval | `packet_view.py`, `uc042-model-view/1.1`; schema no longer duplicated |
| 5. Verified relationships | **Done** | `test_phase5_verified_links` 6/6 | Covered by the prompt-version approval | Links computed with the `tools.RELATIONSHIPS` rules; contextual edges and candidates kept separate |
| 6. Deterministic retrieval | **Done, opt-in only** | `test_phase6_deterministic` 8/8; `test_dr01_dr03_remediation` 18/18; record parity **100%** (162/162, 77/77); strict NOT_FOUND parity **95/96** (corrected from the reported 96/96) | **Yes**, before any route uses it (phase 7 A/B) | `det_retrieval.py`, rule `uc042-det-retrieval/1.3` (DR-01, DR-03 fixed); size guard; uncovered routes fall back to tools |
| 7. A/B preparation | **Plan written, NOT executed** | — | **Yes:** budget (≈ 1.25M minimum / ≈ 2.7M full, ESTIMATES) | `docs/token_optimisation/PHASE7_AB_TEST_PLAN.md` |
| 8. Migration readiness | **Assessed, NOT migrated** | — | **Yes** | `docs/token_optimisation/PHASE8_MIGRATION_READINESS.md`. The app still runs tools mode |
| UI secondary fixes | **Done:** DEF-05 to DEF-12. **Open:** DEF-13 | vitest `labels.test.ts`, `secondaryUi.test.tsx`; backend `test_ui_secondary_backend` 2/2 | DEF-07 and DEF-08 wording: BA review recommended. **DEF-13: BA decision** | The same-second timestamp issue is reported only (§13) |

---

## 1. Environment and isolation details

| Item | Value |
|---|---|
| Source | Clone E, `p10/uc042_e`. Read only; its manifest was verified unchanged at the end |
| Copy | `p10/uc042_token_optimisation`. It has a physical `frontend/node_modules`, not Clone E's junction |
| Database | `uc042_token_opt_test` on the local 5433 cluster, used by tests only. The URL is in `docs/token_optimisation/test_db.url`, which is gitignored. No DB of another environment was opened for writing |
| Storage / config | The copy's own `packs/`, `uc042_dataset/`, `demo_history/` and `investigations/` trees. No `.env` holding a key was copied or created |
| Services | None started from the copy. The showcase services on 8031 and 5191 were not touched |
| Python | 3.11 venv (`Downloads/UC042_CLAUDE_CODE_HANDOFF/uc042/.venv`) with the `uuid_utils` shim from `p10/env_e/shims` on `PYTHONPATH` |
| Provider | OpenAI only (no Groq or other provider). `store: false` is unchanged. **No live call** and no token-counting endpoint call |
| Read-only fixtures | The 20-exception CASE pack in `p10/env_e/packs` and `p10/env_e/docstore/cases`. It is opened read-only by `tests/view_fixtures.py`, and its tests skip if it is absent |

## 2. Baseline findings (Phase 0)

- **Tests on the unmodified copy:** 683 OK (24 skipped) in file mode; 125 OK in PostgreSQL mode (`uc042_token_opt_test`); vitest 74 passed and 2 skipped. Outputs are in `docs/token_optimisation/baseline_*.txt`.
- **Clone E against P10:** 58 differing files (`clone_e_vs_p10_diff.json`), which is the 57-file patch plus Clone E's test-DB wiring. The patch was neither applied nor re-approved.
- **Implementation map:** `docs/token_optimisation/PHASE0_IMPLEMENTATION_MAP.md`. Main points:
  - one output budget was shared by investigations and closing summaries;
  - `CAND-*` was offered to the model as an ordinary citable ID;
  - every request carried the full packet JSON plus a duplicate output schema;
  - packet edge labels differed from the tool vocabulary, so the model re-followed links that were already present;
  - per-request usage was lost, and a fixed-mode failure lost its usage entirely;
  - fixed mode had no pre-request size guard;
  - `uc042lib/final_pack` is guard-protected.

## 3. Phases completed

**Phase 1A: DEF-01 output truncation.**
- `UC042_INVESTIGATION_MAX_OUTPUT_TOKENS` (default 12,000) is used by `investigate()` (fixed mode) and `tool_turn()` (tools mode).
- `structured_request()` (closing summary) keeps `UC042_LLM_MAX_TOKENS` (8,000).
- The prompt gains concise-output guidance: state each fact once, keep prose short, do not restate packet content. No required field was removed.
- A response cut at the budget is still FAILED, `NOT_VALIDATED` and unpublished, and it is not retried automatically.

**Phase 1B: DEF-02 candidate citations.**
- The model sees `citation_classes`: `confirmed_finding_ids` (never `CAND-*`) and `hypotheses_only_ids` (`CAND-*`), plus a rule saying so.
- The stored `allowed_citation_ids` and the validator are unchanged, so a candidate in a confirmed finding is still refused.

**Phase 2: DEF-03 and DEF-04 (prepared only).**
- DEF-03, clean pack: the pack ID is citable only when the pack has no exceptions and is not insufficient-evidence.
- DEF-04: the summary prompt names every refused causal phrase. The validator is unchanged.
- The change sits in guard-protected `uc042lib/final_pack`, so it is delivered as a patch with a proposed re-pin and was not applied.

**Phase 3: DEF-14 telemetry.** Every request is recorded in `model_metadata.provider_response.responses[i]`:
- the turn;
- response and request IDs, model, status and incomplete reason;
- usage: input, cached, output, reasoning and total tokens;
- latency;
- the output budget;
- input item count and characters, and instruction characters.

The aggregate `usage` equals the sum. A failed request keeps its telemetry on the error (`LLMCallError.telemetry`), so a fixed-mode failure no longer loses its usage. `persistence.investigation_id_from_findings` already excludes `usage` and `provider_response`, so identity is unchanged.

**Phase 4: lossless model view.**
- `packet_view.py` renders the stored packet as a compact, deterministic view (`uc042-model-view/1.1`):
  - per-file record tables with shared constants factored out;
  - derived `cited_by_control_result` edges dropped, with the exceptions listed in `cited_without_edge`;
  - `packet_extras` for any additional key.
- `reconstruct_packet(view)` rebuilds the stored packet exactly.
- `model_view_version` and `model_view_sha256` are recorded in `ModelMetadata`.
- The output schema is no longer embedded in the user message. It is still enforced through `text_format`.
- The stored packet and `packet_sha256` are unchanged.

**Phase 5: verified links.**
- `verified_links(packet, store)` lists one-to-one links between packet records, computed with exactly the `tools.RELATIONSHIPS` rules. An amount is compared only for one-to-one links, never part-to-whole.
- Contextual (date-based) associations and candidates are listed separately, never as verified.
- Tools-mode rule: "Do not call `follow_relationship` to confirm a link listed in `verified_links`."

**Phase 6: deterministic retrieval.**
- `det_retrieval.py` with rule `uc042-det-retrieval/1.3` (1.2 at first delivery; 1.3 after DR-01 and DR-03):
  - extends the packet with the records a tools-mode model has fetched;
  - de-duplicates only NOT_FOUND searches whose complete normalised query is identical;
  - enforces a record budget (`DET_MAX_RECORDS` = 140), including inside a call, and lists every record not added in an explicit `pruning_register`.
- The new `mode="deterministic"` makes one fixed-mode request on the extended packet's model view:
  - packet `uc042-evidence-packet/2.0-det`;
  - workflow `uc042-investigation-graph/3.0-det`.
- A pre-request size guard applies (`UC042_SINGLE_REQUEST_MAX_INPUT_TOKENS`, default 150,000 estimated). Over the limit, nothing is sent and the investigation fails with a recorded reason.
- The routes `generic` and `insufficient_evidence` fall back to tools mode, and the fallback is recorded in the trace.
- **The application is unchanged:** `uc042app/services/investigations.py` still runs `mode="tools"`.

**Phase 7.** The A/B plan and budget are written. Nothing was run.

**Phase 8.** Readiness was assessed and the gates are listed. Nothing was switched.

**UI DEF-05 to DEF-12.**
- DEF-05: "Mandatory" wording in the exception summary and the AI panel.
- DEF-06: the engine's candidate relationships are shown as "UNVERIFIED — NOT EVIDENCE-BACKED" on the exception summary and the pack page. The pack API now returns `candidate_relationships`.
- DEF-07: business labels for check codes; an unknown code falls back to the control name, never a guessed label.
- DEF-08: "Evidence missing (see items)".
- DEF-09: one history event per failed attempt. A not-published record within 10 s of a FAILED or INTERRUPTED job event is merged into it.
- DEF-10: a plain-language failure reason, with the technical text kept under "Technical details".
- DEF-11: a wider document-name column that wraps cleanly.
- DEF-12: a neutral tone for a zero count, and an environment tag that wraps.

## 4. Exact files changed (37, relative to Clone E)

The full diff is in `docs/token_optimisation/IMPLEMENTATION_vs_CLONE_E.patch` and the list in `docs/token_optimisation/files_changed.txt`.

| Area | Files |
|---|---|
| Investigation library | `uc042lib/investigation/config.py`, `llm.py`, `tool_loop.py`, `graph.py`, `models.py`, `prompts.py`. **New:** `packet_view.py`, `det_retrieval.py` |
| Application API / services | `uc042app/api/routers/packs.py`, `uc042app/api/schemas.py`, `uc042app/services/investigation_reviews.py` |
| Frontend | `src/api/types.ts`, `components/finalpack/index.tsx`, `components/pack/index.tsx`, `components/upload/documents.tsx`, `components/workspace/AiPanel.tsx`, `components/workspace/ExceptionSummary.tsx`, `pages/PackDetailPage.tsx`, `pages/WorkspacePage.tsx`, `styles/components.css`. **New:** `lib/labels.ts` |
| Tests, new | `tests/test_phase1_reliability.py`, `test_phase3_telemetry.py`, `test_phase4_model_view.py`, `test_phase5_verified_links.py`, `test_phase6_deterministic.py`, `test_ui_secondary_backend.py`, `view_fixtures.py`, `det_parity.py`; `frontend/src/test/labels.test.ts`, `secondaryUi.test.tsx` |
| Tests, updated | `test_findings_schema_14.py` and `test_review_hardening.py` (prompt-version pins); `test_openai_provider.py` (investigation budget; `provider_response` checked as a superset); `test_auto_investigations.py` and `test_end_to_end_workflow.py` (mock responders read the packet from the model view through `view_fixtures.packet_from_message`) |
| Other | `.gitignore` (`test_db.url`) |

**Not changed:**
- `uc042lib/final_pack/*` (guard-protected);
- `uc042lib/investigation/validation.py` (no validator weakened);
- `packet.py`, `persistence.py`, `tools.py`;
- the engine, the database migrations and the guard pins;
- every pack, dataset, golden file and published investigation.

## 5. Tests added and results

| Suite | Baseline | Final |
|---|---|---|
| Backend, file mode (`unittest discover`) | 683 OK, 24 skipped | **725 OK, 24 skipped** (643.9 s) |
| Backend, PostgreSQL (`uc042_token_opt_test`) | 125 OK | **142 OK** (the same 9 modules plus `test_ui_secondary_backend`, `test_phase3_telemetry`, `test_phase6_deterministic`) |
| Frontend vitest | 74 passed, 2 skipped | **78 passed, 2 skipped** (12 files passed, 1 skipped) |
| Frontend production build | OK | **OK** |

New tests:
- backend: 42 (phase 1: 11; phase 3: 7; phase 4: 8; phase 5: 6; phase 6: 8; UI backend: 2);
- frontend: 4.

Key assertions:
- the closing summary keeps the 8,000 budget;
- truncation is still FAILED and unpublished;
- SC5A is VALID when the candidate is only a hypothesis, and still refused when it is cited as confirmed;
- every one of the 76 packets reconstructs exactly from its view;
- every listed link equals the result of the `follow_relationship` tool;
- the size guard sends no request;
- the uncovered route falls back to tools mode and records it;
- no silent pruning;
- the app still runs tools mode.

Phase 2's seven tests (clean pack only offers its pack ID; blank or unknown refs still refused; insufficient-evidence pack not treated as clean; every causal phrase named; "because of" still refused) pass in a scratch copy with the patch applied. In that run, the only failure was the PROTECTED digest of `uc042lib/final_pack`, as expected.

## 6. Before/after packet character counts

These were measured offline over all 76 exception packets: the scenario packs, the historical demonstration packs and the CASE pack. Data: `docs/token_optimisation/packet_sizes.json`.

| Packet | Raw packet JSON (before) | Model view 1.1 (after) | Deterministic extended view (rule 1.2) |
|---|---|---|---|
| **All 76 packets** | 1,948,282 | 1,473,213 (**−24.4%**, including the new verified-links table; −33.3% without it) | n/a |
| SC3C EXC-01 (70 records) | 84,495 | 49,807 (−41%) | 55,129 (74 records) |
| SC3C EXC-02 | 84,396 | 49,672 | 54,994 |
| SC3C EXC-03 | 84,435 | 49,699 | 55,021 |
| S02 EXC-01 (14 records) | 21,974 | 15,583 | 25,844 (27 records) |
| SC5C EXC-17 | 30,883 | 26,475 | 30,489 (12 records) |

- The duplicated output schema (about 6–7k characters per request) is also removed from every request. It is not included in the figures above.
- The largest deterministic packet has 77 records, against a budget of 140.

## 7. Token-saving estimates (ESTIMATES, not measurements)

These estimates use the 15 Nov calibration of about 0.35–0.37 tokens per character. Only live telemetry can confirm them.

- **Tools mode, per request:** the view plus the removed schema cut about 41k characters (≈ 15k tokens) from SC3C's first message. The Responses API is stateless (`store: false`), so the cut repeats on every turn. For SC3C's usual 3–4 requests, that is ≈ 45–60k fewer input tokens per investigation, out of the 128–131k measured.
- **Phase 5:** this removes the redundant `follow_relationship` calls seen on 15 Nov, which are already listed as verified. Each avoided call saves one full round trip.
- **Deterministic mode (phase 6):** one request of about 22–23k input tokens for SC3C, against 128–131k total in tools mode. The per-exception estimates are in the phase 7 plan.
- **Cached input** is billed at a discount, not at zero. No figure here counts it as free.

## 8. Per-request telemetry: capability and offline sample

Each request records an entry like this offline sample (from `test_phase3_telemetry`; a mocked provider, so the values are fixture values):

```json
{"turn": 2, "response_id": "resp_…", "request_id": "req_…", "model": "gpt-6-luna", "resolved_model": "…",
 "status": "completed", "incomplete_reason": null,
 "usage": {"input_tokens": …, "cached_input_tokens": …, "output_tokens": …, "reasoning_tokens": …, "total_tokens": …},
 "latency_seconds": …, "max_output_tokens": 12000, "input_items": 5, "input_chars": …, "instructions_chars": …}
```
A request that fails without a response body is recorded with `status: "error"` and `error_kind`. The request content itself is never stored, only its size.

Verified offline:
- multi-turn tools mode: one entry per turn, and the aggregate equals the sum;
- a truncated turn is recorded with `incomplete_reason: max_output_tokens` and its usage;
- a corrective retry records both attempts;
- a fixed-mode failure keeps its usage;
- the investigation ID is identical with and without telemetry.

No live telemetry has been captured; that needs the phase 7 budget.

## 9. Candidate citation handling results

- **Before:** SC5A EXC-01 was refused 3 times out of 3. The model put `CAND-*` in a confirmed finding because it was offered as an ordinary citable ID.
- **After:**
  - the model sees `CAND-*` only under `hypotheses_only_ids`, with an explicit rule;
  - an offline SC5A response citing the candidate only as a hypothesis is VALID and publishable;
  - the same response with the candidate in a confirmed finding is **still refused** by the unchanged validator;
  - in deterministic mode, candidates stay hypotheses-only.
- **UI:** the engine's candidates now appear on the exception summary and the pack page as "UNVERIFIED — NOT EVIDENCE-BACKED", even without a published investigation.
- Whether a live model now complies is unproven until the A/B runs.

## 10. Closing-summary correctness results

Prepared in `PHASE2_closing_summary_PROPOSED.patch` (4 files, 167 lines). It applies cleanly to this copy and to Clone E.

- **DEF-03 (clean pack):** a pack with no exceptions, and not insufficient-evidence, may cite its own pack ID. Previously `allowed_refs` was empty while every item needed at least one reference, so a clean pack was refused structurally. Blank or unknown references are still refused. A pack with exceptions cannot cite the pack ID.
- **DEF-04 (causal wording):** the prompt now names every phrase the validator refuses. The validator is unchanged, and "because of" is still refused.
- **Status:** NOT applied. Applying it changes the PROTECTED digest of `uc042lib/final_pack` from `bf2dc23b…` to `bd6dfdbc…` in `tests/test_demo_history.py`. **Owner approval is required.** Historical final packs are unaffected, because summaries are regenerated only for new final packs.

## 11. Deterministic retrieval parity results

> **Corrected 16 Nov 2026 after the independent code review (DR-01, DR-02).** The original table claimed NOT_FOUND parity of 96 / 96. That figure came from a loose matcher (file, account, date and reference only, with no check that the deterministic search was itself NOT_FOUND), and rule 1.2 also dropped distinct NOT_FOUND searches. With rule 1.3 and the strict harness, the result is **95 / 96**. See `UC042_DR01_DR03_REMEDIATION_REPORT.md`.

The offline parity harness (`tests/det_parity.py`, strict since DR-02) runs over every persisted investigation record available: the scenario stores of this copy and Clone E, plus the CASE store, all read-only. Current results: `det_parity_v13.json` (rule 1.3). The superseded results are in `_v12` (rule 1.2, loose matching), `_v11` and `_v1`.

| Measure | Result (rule 1.3, strict harness) |
|---|---|
| Records examined | 53. **51 tools-mode attempts compared** (all on deterministic-supported routes). 2 fixed-mode records (EXC-SC2-01 in this copy and in Clone E) are listed as excluded, with the reason |
| Attempts by status | 22 published; 7 completed but not published (**29 completed investigations**); 22 failed attempts, none of which cites any target |
| Model-fetched records later cited (instances) | **162 / 162 supplied**, all from the 29 completed investigations |
| Distinct per exception | **77 / 77** |
| NOT_FOUND searches cited | **95 / 96** under strict matching: complete normalised query, and the deterministic search must also be NOT_FOUND |
| The one strict miss | Clone E, EXC-CASE-01, `SEARCH-08`: a `follow_relationship` query `{evidence_id IN-13:SL-SB-GBP-20260915-0003, relationship settlement_line_to_transaction, value TX-0915-00009}`. The same fact is in the deterministic packet as `SEARCH-01 {file IN-11, txn_id TX-0915-00009}` NOT_FOUND, but under a different query shape, which the strict matcher deliberately does not translate |
| MISS items preserved, candidates unchanged | all. These checks are informational only: both values come from the case, so they cannot differ by construction |
| Packets at the record budget | none (largest 77 of 140) |
| Pruning register entries | 0 at production limits under rule 1.3. Rule 1.2's 34 entries were all de-duplication drops, which are no longer made. Nothing is removed silently |

The rule history:
- **1.0** missed the last-persistence-day, booking-date and cash-book anchors;
- **1.1** fixed those;
- **1.2** stopped SC5C over-fetch by taking related anchors only for a different exception kind;
- **1.3** (DR-01, DR-03) de-duplicates only NOT_FOUND searches with an identical complete query, enforces the record budget inside a call, and registers every record a call did not add.

## 12. Remaining uncovered exception categories

These have no deterministic plan; in deterministic mode they fall back to tools, and the fallback is recorded.

| Kind | Route | Count seen |
|---|---|---|
| C07-BANK-EVIDENCE | `generic` / `insufficient_evidence` | 10 (CASE pack) |
| BC-VS-EOD | `generic` | 9 (CASE pack) |
| DQ23-STATEMENT | `generic` | 1 (CASE pack) |
| UNMATCHED_CASHBOOK_ENTRY | `generic` | 3 (historical packs) |

Any other kind routed to `generic` or `insufficient_evidence` also stays on tools.

## 13. Approval gates still pending

1. **Guard re-pin for phase 2:** `uc042lib/final_pack` digest `bf2dc23b…` → `bd6dfdbc…`. Apply the patch only after approval.
2. **Prompt versions 1.6 / 2.6-tools** and model view `uc042-model-view/1.1`. These change what the model is given, so new investigations will show new versions.
3. **The investigation output budget** `UC042_INVESTIGATION_MAX_OUTPUT_TOKENS` = 12,000. It is a cost ceiling, not a guaranteed cost.
4. **The live A/B budget for phase 7** (§14). No live call has been made.
5. **Per-route migration for phase 8:** only after the A/B gates pass.
6. **DEF-13 (BA decision):** whether balanced external-reconciliation days should read "NOT APPLICABLE". It is golden-consistent, so it was not changed.
7. **DEF-07 and DEF-08 wording:** BA review of the business labels in `frontend/src/lib/labels.ts` is recommended.
8. **Same-second timestamps (reported only):**
   - `clock.now_iso` has seconds precision, and `routers/monthly._after` compares with a strict `>`.
   - An event written in the same second as the reference timestamp is therefore treated as "not after", which can hide a reassessment made within the same second.
   - Possible fixes are sub-second timestamps or `>=` with a tie-breaker. Either touches persisted formats, so owner approval is needed.
9. **The existing 57-file patch:** its approval status is unchanged. This work is based on Clone E, so it would ship after or with that patch.

## 14. Proposed live A/B test budget

The full plan is `docs/token_optimisation/PHASE7_AB_TEST_PLAN.md`.

- **Arm A:** tools mode (current).
- **Arm B:** deterministic retrieval plus one request on the model view.
- **Held equal:** the same packs, `gpt-6-luna` at medium effort, a temporary investigations root (nothing is published), and alternating runs.

| Option | Runs | Total tokens (ESTIMATE) |
|---|---|---|
| Minimum: S02, SC3C-01, SC5A-01, SC2 × 3 runs × 2 arms | 24 | **≈ 1.25M** |
| Full: 9 exceptions × 3 × 2 | 54 | **≈ 2.7M** |

No currency figure is given, because no verified `gpt-6-luna` price table is available. Adopt arm B for a route only if every B run passes every quality gate and the median input tokens are lower.

## 15. Rollback instructions

- **Whole change:** discard `p10/uc042_token_optimisation`. No other environment depends on it. To revert in place, apply `docs/token_optimisation/IMPLEMENTATION_vs_CLONE_E.patch` in reverse (`git apply -R` or `patch -R -p1`).
- **Output budget:** set `UC042_INVESTIGATION_MAX_OUTPUT_TOKENS=8000` to restore the previous ceiling. The summary budget is independent.
- **Model view:** revert the phase 4 hunks in `llm.py` (`_request_kwargs`) and `tool_loop.py` (first message), so they call the retained legacy `user_message` / `tools_user_message` again. Then set `OpenAIInvestigator.uses_model_view = False`, so no view version or hash is recorded.
- **Deterministic mode:** it is opt-in, and the app never selects it. Nothing to roll back unless a route is switched later. The phase 8 proposal makes that switch a per-route setting defaulting to empty.
- **Phase 2:** not applied, so nothing to roll back.
- **Database:** no migration was added, so there is no DB rollback. The test DB `uc042_token_opt_test` can be dropped.
- **Investigation records:** new metadata fields are additive and excluded from identity. Existing records remain valid.

## 16. Confirmation that original environments and historical packs were not changed

Verified at the end of the work:

- **Clone E (`p10/uc042_e`):** matches `source_manifest_clone_e.json` (1,500 files, tree SHA `62b5b3fd…`). Unchanged.
- **P10 (`p10/uc042`), `p10/env_e`, `p10/env_s` and the live application:** no file newer than the start of this work. Unchanged.
- **Databases:** row counts of `uc042`, `uc042_p10b`, `uc042_p10e` and `uc042_p10e_showcase` are unchanged. Only `uc042_token_opt_test` was written, by tests.
- **Services:** 8031 (showcase backend) and 5191 (Clone E frontend) are untouched and still running.
- **Data trees in the copy:** packs, final packs, datasets, golden files and published investigations are unchanged. `tests/test_demo_history.py` (PROTECTED digests) passes, so guard pins and approval-chain digests are unmodified.
- **Not done:** the 57-file patch was not applied and its approval was not modified; no Groq or other provider was added; `store: false` is unchanged; no validator was weakened; no live OpenAI or token-counting call was made.
