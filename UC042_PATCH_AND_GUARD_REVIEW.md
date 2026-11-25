# UC-042 — Problem 4: Patch and Guard Re-pin Review

**Date:** 15 November 2026
**Type:** Read-only review. Nothing was modified, approved, re-pinned or migrated.
**Subject:** `p10/ui_audit/live_verification.patch` (P10 `p10/uc042` → Clone E `p10/uc042_e`, 57 files, 258,601 bytes, SHA-256 `ecdddf9a…873f84`)
**For:** the business owner (technical and governance approvals) and the business analyst (UI and workflow approvals)

### How findings are labelled

| Label | Meaning |
|---|---|
| **VERIFIED (this review)** | Checked independently during this review, by reading the code, recomputing a value or running a check |
| **RECORDED** | Taken from the 6 Nov or 12 Nov reports (`END_TO_END_ANALYST_WORKFLOW.md`, `LIVE_VERIFICATION_REPORT.md`) and not repeated here |
| **CONCERN** | A possible issue found by reading the code. It is not shown to cause a failure. |

---

## 1. Executive summary

**What the patch is.** It is the full difference between the original P10 copy and Clone E. It merges two pieces of work:

- **6 Nov 2026** (39 files): the end-to-end analyst workflow. It adds:
  - mandatory automatic AI investigation;
  - an optional comment on REJECT;
  - the final-pack disposition REJECTED BY ANALYST;
  - a validation that stops rejected AI text from appearing in a pack;
  - a new readiness blocker for failed investigations;
  - a per-exception checklist.
- **12 Nov 2026** (18 more files; 11 of the 39 changed again): Groq removal and live verification. It contains:
  - OpenAI as the only provider;
  - investigator prompt 1.3 / 2.3-tools;
  - closing-summary prompt 1.1;
  - the workspace retry link;
  - corrected "Next step" wording;
  - a wrapping checklist table.

**Integrity of the patch. VERIFIED (this review).**

- **The stored patch is exactly P10 → Clone E today.** I regenerated the diff with the same options. It is identical to the stored patch apart from timestamps, so neither tree has changed since 12 Nov.
- **Nothing is hidden by the exclusions.** The diff leaves out `docs`, `packs`, `investigations`, `final_packs` and `app_state`. Outside the patch, the two trees differ only in a runtime `app_state` folder. Data trees and docs are identical.
- **No real secrets.** Only fake test keys appear (`sk-test-NOT-REAL-0000`, and a fake `gsk_…` in the retired Groq test).

**Both guard digests reproduce exactly. VERIFIED (this review).**

| Digest | Files | What it covers | Reproduced by |
|---|---|---|---|
| `b6509a20…89f38c` | 18 | P10 as it is today | Hashing `p10/uc042/uc042lib/final_pack` |
| `8b0d6aa885b972a16cc2f864743308a97b7251735e83ff74de1af029dc9f7942` | 18 | P10 + the 6 Nov changes to `assemble.py`, `report.py` and `validate.py` | Clone E's tree with `model.py` and `summary.py` put back to P10 |
| `bf2dc23bbc516b50bd19393fbbd9e5bfa00907b2115a04455d210b3e8c709cae` | 18 | `8b0d6aa8` + the 12 Nov changes to `model.py` and `summary.py` | Hashing `p10/uc042_e/uc042lib/final_pack` |

- No protected file was added or removed, and the fonts are unchanged.
- Exactly 5 of the 18 protected files differ, and each difference matches its stated reason.
- No other change touches a protected file.

**Historical packs. VERIFIED (this review).** I ran `verify_final_pack` offline on all 21 published final packs on this machine:

- the February historical pack in live `demo_history`;
- 12 packs in Clone E;
- 2 P10 end-to-end packs;
- 5 Report 19 packs;
- 1 `uc042_e2e` pack.

Every pack verifies with the **Clone E code**, including the 4 older packs that contain rejections.

With the **P10 code**, 2 packs fail: the two Clone E packs that carry the new `REJECTED_BY_ANALYST` field. That means **once a REJECTED BY ANALYST pack is published, going back to the old code makes that pack fail verification.** This is a rollback constraint.

**The most important migration fact. VERIFIED (this review).** The patch is written against **P10, not live**.

- Live (`Downloads/UC042_CLAUDE_CODE_HANDOFF/uc042`) is still at Phase 8. Its `final_pack` digest is `1a638662…` (12 files) and its guard pin is `af18244c…`.
- Live → P10 is another **71 file differences**. These include migration **0005**, the bundled fonts, the UI simplification and the Groq fallback code.
- The live `.env` still sets `UC042_LLM_FALLBACK_PROVIDER=groq` and holds a Groq key. **If the P10 code reaches live without this patch, the automatic Groq fallback switches on.**

**Decisions that need business or UI review before migration:**

- Mandatory investigation of every processed or reassessed pack. This includes the cost, and the fact that an API call sending no disclosure still records an authorisation.
- The new blocker that a failed investigation must be retried or excluded.
- The new final-pack wording for rejections.
- The checklist and disposition table.
- The bulk "Include the N completed investigation(s)" shortcut. It has no automated or browser test.

**My technical view (not an approval).** The code is coherent and its claims match the code. The guard re-pins are accurate and the historical packs are safe going forward. No change needs a database migration beyond 0005. The remaining questions are about policy, sequencing and environment, not code defects. There is one code-level concern worth deciding: the processing button is disabled while the AI configuration cannot be read (CONCERN 6.3-c).

---

## 2. Complete 57-file inventory

Each file is listed once, under its main category. "Tests" names the automated tests that cover it. **LIVE** marks evidence from browser or live checks recorded on 12 Nov. File numbers follow the order in the patch.

**Totals:**
- 57 files: 46 modified, 9 new, 2 deleted.
- New files (9):
  - frontend components: `AutoInvestigationDisclosure.tsx`, `AutoInvestigations.tsx`;
  - frontend tests: `autoInvestigation.test.tsx`, `nextStep.test.ts`, `workspaceRetry.test.tsx`;
  - backend service: `auto_investigations.py`;
  - backend tests: `test_auto_investigations.py`, `test_end_to_end_workflow.py`, `test_openai_only_provider.py`.
- Deleted files (2): `uc042lib/investigation/fallback.py` and `tests/test_provider_fallback.py`.
- By category: backend/API 5, frontend 13, AI architecture 9, validation 1, review workflow 4, final pack 4, reassessment 2, database 0, tests 17, configuration 2.

### 2.1 Backend and APIs (5 files)

| # | File | What changed | Why | Behaviour affected | New / fix | Historical data / compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 36 | `uc042app/api/routers/investigations.py` (+18/−1) | New `GET` and `POST /api/v1/packs/{pack_id}/auto-investigations` | Pack-level status, "Investigate all exceptions" and "Retry failed" | New endpoints. POST returns 202, or 422 / 409 / 503 | New | Additive. Existing routes unchanged | `test_auto_investigations` (Orchestration 1–9, authorisation), `test_end_to_end_workflow`; LIVE C-2…C-11 |
| 37 | `uc042app/api/routers/monthly.py` (+7/−4) | `POST /uploads/{id}/process` accepts an optional body `{ai_authorization}`. `POST /periods/{id}/reconciliation` passes `ai_authorization` | Carries what the processing confirmation showed (provider, model) | Every processing or reassessment run now starts the automatic investigation path | New | Backwards compatible: a request with no body is still accepted, and still triggers investigations (see 6.3-a) | `test_auto_investigations.AfterReconciliationRun`, `test_api_monthly`, `test_phase8` |
| 38 | `uc042app/api/schemas.py` (+20/−3) | New `AutoInvestigationRequest` and `ProcessRequest`. `ReconcileRequest.ai_authorization` added. `Readiness.checklist` added. `AiConfiguration.fallback` **removed**. `AiAuthorization.operation` gains `AUTO_INVESTIGATION`. `fallback_provider` accepts only `"none"` | Auto investigation, checklist, Groq removal | API contracts | New + removal | Response field `fallback` removed (breaking for any client that reads it; only our frontend does). A request with `fallback_provider` other than `"none"` gets 409 | `test_openai_only_provider.ApiConfigurationAndAuthorisation`, `test_phase8`, `test_auto_investigations` |
| 40 | `uc042app/jobs/__init__.py` (+19/−9) | `JobRunner` gets a second, bounded thread pool, the "AI lane" (`ai_workers`, default 1). `submit(..., lane="ai")`. Shutdown closes both pools | A queue of investigations must not block processing, previews or generation, and must stay within provider rate and token limits | Investigations run one at a time by default. On shutdown, jobs still QUEUED become INTERRUPTED (unchanged rule) | New | None | Indirect only: `test_phase8` (mock signature). **No unit test of the lane or of concurrency.** LIVE C-13 (no overlap) |
| 41 | `uc042app/services/__init__.py` (+6/−1) | Builds `AutoInvestigationService`. Passes `ai_job_workers` to the runner. Connects `monthly.auto_investigations` and `reviews.auto_investigations` | Wiring | Enqueue after every run; per-exception status in readiness | New | None | All API test suites |

### 2.2 Frontend and UI (13 files)

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 02 | `frontend/src/api/endpoints.ts` (+6/−3) | `processBatch(batchId, aiAuthorization?)`, `autoInvestigations`, `startAutoInvestigations` | New API calls | Processing sends the disclosure | New | Additive | vitest (indirect), LIVE |
| 03 | `frontend/src/api/types.ts` (+72/−8) | Types for the checklist, auto-investigation status and results. Fallback fields removed from `AiConfirmation` and `AiConfiguration`. `FallbackRecord` kept and marked historical | Type contracts | None at runtime | New + removal | `FallbackRecord` kept so old records still display | `tsc --noEmit` (RECORDED pass) |
| 04 | `frontend/src/components/ai/AiAuthorizationDialog.tsx` (+14/−10) | New operation `AUTO_INVESTIGATION` (title "Authorise automatic AI investigations", button "Authorise", three explanatory bullets). The "Automatic fallback" row is replaced by "Other providers: None — a failed request is reported as it failed…". The confirmation no longer sends fallback fields | Pack-level authorisation; Groq removal | The text of the authorisation dialog | New + change | A browser tab opened before the update still sends fallback fields: 409 asks for a fresh confirmation | `phase8.test.tsx` (payload, no "groq"); LIVE STG1-UI |
| 05 | `frontend/src/components/ai/AutoInvestigationDisclosure.tsx` (new, 53) | A notice inside the processing and reassessment confirmations: "AI investigations will run automatically… every exception… may incur charges… never sent to another provider". If AI is not configured: "AI investigations cannot run…". `AutoInvestigationRunStatus` shows the outcome on a run | Mandatory policy: disclosure instead of a checkbox | Processing and reassessment confirmations; run rows | New | n/a | `phase8.test.tsx` (reassessment disclosure, no checkbox); LIVE C-1 |
| 07 | `frontend/src/components/upload/documents.tsx` (+2) | Run rows show `AutoInvestigationRunStatus` | Visibility | Upload batch page, list of runs | New | Old runs have no `auto_investigation`, so nothing is shown | LIVE (run rows) |
| 10 | `frontend/src/components/workspace/AutoInvestigations.tsx` (new, 74) | Monthly report section 5: one row per pack with status counts and the buttons "Investigate all exceptions" and "Retry failed" (with the `AUTO_INVESTIGATION` dialog). Refreshes every 4 s while jobs are active | Pack-level control and visibility | Monthly report | New | Works for historical packs (explicit action) | **No vitest.** Backend `test_8`, `test_9`; LIVE "Retry failed" (run B), "Investigate all" repeat with no duplicate; 6 Nov historical-pack run (PERSISTED) |
| 11 | `frontend/src/components/workspace/ExceptionSummary.tsx` (+12/−3) | "Next step" text. Failed or unusable: "Retry the investigation, or exclude the exception at the final review with a documented reason; it cannot be reported as not investigated." Never run: no longer says "optional" | Defect 4.4: the wording contradicted the mandatory policy and the new blocker | Exception Workspace guidance | Fix | None | `nextStep.test.ts` (3), `simplified.test.tsx`; LIVE C-15 |
| 12 | `frontend/src/data/DataSource.ts` (+7/−3) | Interface: `processBatch(…, aiAuthorization?)`, `autoInvestigations`, `startAutoInvestigations` | Data layer | None | New | Additive | `tsc` |
| 13 | `frontend/src/data/apiSource.ts` (+2) | Implements the two new methods | Data layer | None | New | Additive | `tsc`, LIVE |
| 14 | `frontend/src/data/mock/MockDataSource.ts` (+5/−3) | Mock: new methods "not available". Statement for `AUTO_INVESTIGATION` | Mock parity | Mock mode only | New | n/a | vitest suites |
| 15 | `frontend/src/pages/ArchivePages.tsx` (+8/−2) | Batch page: disclosure above "Start processing". The button is disabled until the disclosure has loaded; the disclosure is sent with the request | Mandatory policy | **Processing is blocked in the UI while the AI configuration cannot be read** (6.3-c) | New | n/a | **No vitest of the disclosure** (`archive.test` covers only the disabled state when evidence is missing); LIVE C-1 |
| 16 | `frontend/src/pages/ReportPages.tsx` (+4/−1) | Section 5 shows `AutoInvestigationsPanel` above the investigations table (real backend only) | Visibility | Monthly report | New | n/a | LIVE |
| 18 | `frontend/src/styles/components.css` (+9) | `.dtable--wrap` (fixed layout, wrapping) and `.linklike` (a button that looks like a link) | Defect 4.5: clipped labels; inline "exclude it with a reason" | Layout of the final-review side panel | Fix + new | None | LIVE LV32 (292 px table inside a 328 px panel) |

### 2.3 AI provider and investigation architecture (9 files)

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 08 | `frontend/src/components/workspace/AiPanel.tsx` (+16/−6) | Reads the exception's latest job from the auto-investigation status. After a page load, a FAILED or INTERRUPTED automatic job shows "The latest investigation failed" with its reason. The button reads "Retry investigation" and sends `retry_of`. Historical fallback banner relabelled "Historical record: answered by the former fallback provider…" | Defect 4.3: a retry was not linked and the failure was not shown | Exception Workspace AI panel | Fix | Old fallback records still shown (read-only) | `workspaceRetry.test.tsx` (2); LIVE C-10R |
| 42 | `uc042app/services/ai_authorization.py` (+19/−32) | New operation `AUTO_INVESTIGATION` with its own statement. Fallback sentence, fallback configuration and fallback fields in records removed. A confirmation that names a fallback other than `none` is refused (409 `AI_CONFIGURATION_CHANGED`). `record()` accepts `period_id` (run-level records have an empty `pack_id`) | Auto authorisation; Groq removal | Authorisation records and statements | New + removal | Old records with fallback fields are unchanged (append-only). The statement text the analyst confirms has changed for every operation (the fallback sentence is gone) | `test_openai_only_provider`, `test_auto_investigations`, `test_phase8` |
| 43 | `uc042app/services/auto_investigations.py` (new, 182) | `AutoInvestigationService`: `authorize` (pack or retry), `authorize_run` (policy `MANDATORY_AUTO_INVESTIGATION`, basis `PROCESSING_CONFIRMATION`, recorded **before** the run), `exception_status` (8 states), `pack_status`, `enqueue` (a recorded outcome for every exception: QUEUED, ALREADY_ACTIVE, ALREADY_INVESTIGATED, PREVIOUS_ATTEMPT_FAILED, NOT_RETRIED, NOT_QUEUED; one activity event), `start_for_pack`, `after_run` | Mandatory investigation without duplicating the engine (it reuses `InvestigationService`) | Every run enqueues one investigation per exception. A failed attempt is retried only by an explicit action. Without a provider: NOT_STARTED with the reason | New | Exceptions are never resolved. Historical packs are investigated only on explicit request | `test_auto_investigations` (11), `test_end_to_end_workflow`, `test_api_monthly`; LIVE C-0…C-15 |
| 45 | `uc042app/services/investigations.py` (+21/−3) | `enqueue_authorized()` (one active job per exception, idempotent). Jobs record a `trigger` (MANUAL / CASE / AUTO_*). Investigation jobs use the AI lane | Reuse of the existing engine | Investigation jobs | New | Old jobs have no `trigger` (read as null) | as above |
| 53 | `uc042lib/investigation/config.py` (+7/−31) | `PROMPT_VERSION` 1.2 → **1.3**, `TOOLS_PROMPT_VERSION` 2.2-tools → **2.3-tools**. All `UC042_LLM_FALLBACK_*` and `GROQ_*` constants, `fallback_settings()` and the Groq default model removed | Prompt fix 4.1; Groq removal | New investigations record prompt 1.3 / 2.3 | Fix + removal | Historical investigations keep the version they recorded. No code compares stored and current prompt versions | `test_review_hardening` (version pin), `test_findings_schema_14`, `test_openai_only_provider` |
| 54 | `uc042lib/investigation/fallback.py` (**deleted**, −100) | `FallbackInvestigator` removed | Groq removal (owner direction, 12 Nov) | No automatic switch of provider | Removal | Historical fallback records stay readable (shown from stored metadata) | `test_openai_only_provider.test_no_fallback_api_remains` |
| 55 | `uc042lib/investigation/graph.py` (+1/−3) | Fallback record hook removed from the metadata of the tool loop | Groq removal | Investigation metadata | Removal | None | `test_openai_only_provider` |
| 56 | `uc042lib/investigation/llm.py` (+8/−122) | `GroqInvestigator`, `_primary_from_env` and `fallback_from_env` removed. `investigator_from_env()` builds OpenAI (or the Anthropic / offline adapters). `"groq"` is now an unsupported provider. The Groq key is no longer redacted | Groq removal | Provider factory; error messages | Removal | If the live `.env` still has `GROQ_API_KEY`, it is no longer redacted from logs (low risk: it is never sent; delete it anyway) | `test_openai_only_provider` (7) |
| 57 | `uc042lib/investigation/prompts.py` (+5) | One new rule naming every refused causal phrase ("due to", "because of", "caused by", "root cause", "the cause is/was"), with how to report an engine outcome instead. It applies to both prompts (`TOOLS_SYSTEM_PROMPT` is built from `SYSTEM_PROMPT`; VERIFIED) | Defect 4.1: the validator refused phrases the prompt never named | Model behaviour; validation unchanged | Fix | None | `test_findings_schema_14.test_prompts_name_every_causal_phrase_the_validation_refuses`; LIVE D-0R |

### 2.4 Evidence retrieval and validation (1 file)

The retrieval tools, the evidence ledger, findings validation (`validation.CAUSE_PATTERNS`) and citation checks are **not changed** (VERIFIED: no file under `uc042lib/investigation/` other than config, fallback, graph, llm and prompts is in the patch).

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 52 | `uc042lib/final_pack/validate.py` (+40) — **protected** | New `_rejected_text_in()`. Any AI-written passage of 40 characters or more from a REJECTED investigation (summary, findings, hypotheses, gaps, conflicts, next steps, questions) found anywhere in a final pack is a validation error. The analyst's reason and comment are not scanned. Passages that are also deterministic text or text of an accepted investigation are allowed | Defence in depth: rejected AI content must not reach a pack by any route | Preview and GENERATE are refused if any such text leaks | New | Applies only to new validation runs. Stored packs are verified by hash and re-render, not by this check | `test_end_to_end_workflow.RejectedTextGuard`, `test_analyst_review`; LIVE G-C3/G-C4 (9 texts, zero leaks) |

### 2.5 ACCEPT / REJECT / EXCLUDE workflow (4 files)

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 09 | `frontend/src/components/workspace/AnalystReview.tsx` (+22/−12) | REJECT form gains an optional "Analyst comment (kept separately from the reason)". A recorded rejection shows the comment, plus a note: "In the final audit pack this exception shows REJECTED BY ANALYST…". Status labels renamed ("AI accepted by analyst" → "Accepted by analyst", "AI awaiting your review" → "Findings ready for review"). `AiStatus` adds Queued and "Investigation failed — reason available". Guidance for unusable investigations mentions retry or exclusion | Comment on rejection; status visibility | Workspace decision panel, status badges | New + label change | Old rejections have no comment (nothing shown) | `analystReview.test.tsx` (new case), `autoInvestigation.test.tsx` (labels); LIVE E-R2/E-R3 |
| 17 | `frontend/src/pages/ReviewPages.tsx` (+62/−5) | Final review "Before you generate": new **DispositionTable**. It shows counts (total, investigated, awaiting, accepted, rejected, failed, excluded…) and one row per exception with a disposition badge, the job error, and links "ACCEPT or REJECT it", "Retry it" or "exclude it with a reason". New button **"Include the N completed investigation(s)"** (selects `usable_investigations[0]` for each SELECTION_NEEDED exception). Blockers shown in the table are not listed twice | Every exception's status in one place; defect 4.5 | Final review page | New | Mock data has no checklist, so the table is hidden | **No vitest of the table or the shortcut.** LIVE F-2, F-5, LV25, LV27, LV32. **No evidence that the shortcut was exercised** |
| 44 | `uc042app/services/investigation_reviews.py` (+3/−4) | REJECT with a comment is now **accepted** (it was 422 `COMMENT_NOT_ALLOWED`). The comment is stored separately, exactly as written. A blank reason is still refused (422, and a PG CHECK constraint) | BA requirement (6 Nov): a comment on rejection | REJECT API | Contract change | Existing rows unchanged. The `comment` column already exists (migration 0005, NOT NULL, default empty) | `test_analyst_review` (test updated + `RejectedWithComment`); LIVE E-R1…E-R3, S3-2 |
| 47 | `uc042app/services/reviews.py` (+64/−1) | Readiness: new **blocker `INVESTIGATION_FAILED_NO_DISPOSITION`**. An exception marked NOT_INVESTIGATED whose investigation FAILED or is NOT_USABLE blocks GENERATE until it is retried or excluded with a reason. New `checklist` (8 dispositions, counts, preview CURRENT/STALE/NONE, closing-summary status) | A failed attempt must not be reported as "not investigated" | Final-review readiness; GENERATE gating | New rule | **Affects review sessions that are already open** with failed investigations: they become blocked after the upgrade | `test_api_monthly`, `test_end_to_end_workflow.MixedPackWorkflow`, `test_phase8` helper; LIVE F-1…F-7R |

### 2.6 Final audit-pack generation (4 files, all protected)

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 48 | `uc042lib/final_pack/assemble.py` (+5) | A rejected review's view gets `disposition: "REJECTED_BY_ANALYST"` and, if one was written, `comment` | Explicit analyst disposition | Content of new final packs | New | New packs only. **Old code cannot re-render packs that carry this field** (6.2) | `test_analyst_review` (both classes), `test_end_to_end_workflow` |
| 49 | `uc042lib/final_pack/model.py` (+1/−1) | `SUMMARY_PROMPT_VERSION` 1.0 → **1.1** | Prompt change 4.2 | New summaries record 1.1 | Fix | Stored summaries carry `prompt_version` explicitly (all 22 stored records on disk say 1.0; VERIFIED). The default applies only to newly built records | `test_closing_summary` |
| 50 | `uc042lib/final_pack/report.py` (+18/−2) | When `disposition == "REJECTED_BY_ANALYST"`: the heading "EXC-… - REJECTED BY ANALYST", "Reason for rejection (exactly as recorded by the analyst)", "Analyst comment (optional, separate from the reason)", the rejected investigation's reference, and an "AI content: Excluded…" statement. **Packs without the field keep the old rendering byte for byte** | Explicit disposition in the report | HTML and PDF of new packs | New | Old packs re-render unchanged (VERIFIED, 21/21) | `test_analyst_review`; LIVE G-C*, PDF text run C |
| 51 | `uc042lib/final_pack/summary.py` (+3) | Prompt rule: "negate each term in its own short clause". Summary validation unchanged | Defect 4.2: a correct long disclaimer was refused | Closing-summary model behaviour | Fix | None | `test_closing_summary.test_prompt_states_the_negation_scope_the_validation_applies` (also proves the long form is still refused); LIVE G-E0 |

### 2.7 Reassessment and pack lineage (2 files)

The lineage code (`audit.pack_lineage`, final-pack versions) is **not changed**.

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 06 | `frontend/src/components/report/Reassessment.tsx` (+9/−4) | The reassessment confirmation shows the disclosure. "Start reassessment" is disabled until it has loaded. The completion notice points to the Exception Workspace first, then the final review, and shows the run's AI status | Mandatory policy applies to reassessment too | Reassessment dialog | New | n/a | `phase8.test.tsx` (disclosure, no checkbox, `ai_authorization` sent); LIVE C-1 |
| 46 | `uc042app/services/monthly.py` (+26/−5) | `process()` and `reconcile()` take `ai_authorization`. The run-level authorisation is recorded before the run row is created. After a successful run, `after_run` enqueues and the run result gets `auto_investigation` (ENQUEUED / ENQUEUE_FAILED / NOT_STARTED). A configuration change since the dialog refuses processing (409) | Mandatory investigation | Every processing and reassessment run | New | Old runs have no `auto_investigation`. The deterministic result never depends on AI (an enqueue failure is recorded; the run stands) | `test_auto_investigations.AfterReconciliationRun` (4), `test_api_monthly`, `test_phase8` |

### 2.8 Database and persistence (0 files)

No migration, model or repository file is in the patch. VERIFIED that none is needed beyond 0005 (which P10 already needs):

- `audit.ai_execution_authorizations.operation` is `String(32)` with no CHECK constraint, so `AUTO_INVESTIGATION` fits.
- Run-level records store `pack_id = ""`. The column is NOT NULL, but an empty string is allowed. The run, job and authorisation are linked through `job.inputs.authorization_id` and `run.result.auto_investigation`.
- `operations.jobs.inputs` (JSON) gains `trigger`. `runs.result` (JSON) gains `auto_investigation`.
- `audit.investigation_reviews.comment` already exists. The CHECK constraints (`decision IN (…)`, a non-blank reason on REJECT) do not forbid a comment on REJECT.
- Minor: the comment in `uc042app/db/models.py` still says `INVESTIGATION | CLOSING_SUMMARY`. It is out of date but harmless.

### 2.9 Tests and test infrastructure (17 files)

| # | File | Change | What it verifies |
|---|---|---|---|
| 19 | `frontend/src/test/analystReview.test.tsx` (+21/−2) | New case | REJECT sends `comment` separately; a comment never replaces the reason |
| 20 | `frontend/src/test/autoInvestigation.test.tsx` (new, 29) | New | Labels of `AiStatus` (Queued, In progress, Failed…) |
| 21 | `frontend/src/test/nextStep.test.ts` (new, 33) | New (3) | "Next step": failed → retry or exclude; unusable → same; only "never run" may be reported as not investigated |
| 22 | `frontend/src/test/phase8.test.tsx` (+8/−3) | **Expectation changed** | The investigation dialog payload no longer contains fallback fields, and no "groq" text. The reassessment dialog shows the disclosure, has no checkbox and sends `ai_authorization`. The change matches the intended behaviour |
| 23 | `frontend/src/test/simplified.test.tsx` (+4/−2) | **Expectation changed** | The old assertion that the text says "optional" is replaced by the new wording and "not optional". Intended |
| 24 | `frontend/src/test/workspaceRetry.test.tsx` (new, 49) | New (2) | A failed automatic job is shown and `retry_of` is sent; with no failed job, it is a plain first run |
| 25 | `tests/test_analyst_review.py` (+57/−4) | **Expectation changed** + new class | `COMMENT_NOT_ALLOWED` replaced by "a blank reason with a comment is refused". Report assertions updated to the REJECTED BY ANALYST wording. `RejectedWithComment`: reason and comment kept byte for byte in API, PG, JSON, HTML and PDF; neither reaches the summary model; the pack verifies |
| 26 | `tests/test_api_monthly.py` (+28/−4) | **Flow changed** | The end-to-end monthly flow now expects automatic jobs (failed when the provider is unreachable), a retry with `retry_of`, the new blocker, and exclusion with a reason |
| 27 | `tests/test_auto_investigations.py` (new, 241) | New (11) | Zero or one or many exceptions; one failure does not stop the others; a token-limit refusal is not retried; explicit retry; no duplicates; authorisation required, recorded and linked; run enqueues only its own pack; mandatory with no opt-in; NOT_STARTED without a provider; configuration change refuses processing |
| 28 | `tests/test_closing_summary.py` (+11/−1) | New test | The prompt states the negation scope; the long negated list is still refused by validation |
| 29 | `tests/test_demo_history.py` (+10/−1) | **Guard re-pin** | `uc042lib/final_pack` → `bf2dc23b…` (18 files), with both justifications (section 4) |
| 30 | `tests/test_end_to_end_workflow.py` (new, 179) | New (2) | ACCEPT, REJECT, FAILED and EXCLUDED in one pack through to the final pack; the rejected-text guard |
| 31 | `tests/test_findings_schema_14.py` (+15/−1) | New test | Both prompts name every `CAUSE_PATTERNS` phrase |
| 32 | `tests/test_openai_only_provider.py` (new, 150) | New (7) | No fallback API remains; only OpenAI is built even with legacy variables; `groq` refused; each availability failure is reported after one request; investigation and summary fail visibly; the configuration API has no fallback; a stale fallback confirmation is refused |
| 33 | `tests/test_phase8.py` (+16/−3) | Helper changed | `generate_final_pack` waits for automatic jobs and excludes failed ones with a reason; the mock accepts `lane`; the configuration lists 3 statements |
| 34 | `tests/test_provider_fallback.py` (**deleted**, −282, 16 tests) | Retired | It tested the removed Groq fallback |
| 35 | `tests/test_review_hardening.py` (+2/−2) | **Expectation changed** | The prompt version pin moves to 1.3 / 2.3-tools |

**About the changed expectations.** I read all 7 tests whose expectations changed (#22, 23, 25, 26, 29, 33, 35). Each change matches a behaviour change described in the reports. None of them loosens a check without a matching behaviour change. #33 changes a shared helper, so every Phase 8 test that generates a pack now excludes failed automatic investigations. That is correct for the new rule, but it means those tests no longer cover a "failed and reported as not investigated" path, because that path no longer exists.

### 2.10 Configuration and environment (2 files)

| # | File | What changed | Why | Behaviour affected | New / fix | Compatibility | Tests |
|---|---|---|---|---|---|---|---|
| 01 | `.env.example` (+2/−8) | Groq and fallback block replaced by "OpenAI is the only live provider… `UC042_LLM_FALLBACK_*` and `GROQ_*` are no longer read" | Groq removal | Documentation only | Removal | The live `.env` still contains them (ignored after the patch) | n/a |
| 39 | `uc042app/config.py` (+10/−1) | New `UC042_AI_JOB_WORKERS` (integer 1–4, default 1; anything else stops start-up with `ConfigurationError`) | Size of the AI lane | Start-up | New | Not set means 1 | **No unit test of the validation** |

---

## 3. UI and workflow change register

"BA approval advisable" is my recommendation, not a decision. Passing technical tests does not settle whether the change is acceptable to the business.

| # | Change | Existing behaviour (P10) | New behaviour (Clone E) | Reason | Screens / workflows | Change in user decisions or responsibilities | BA approval advisable? |
|---|---|---|---|---|---|---|---|
| U1 | **Mandatory automatic AI investigation on processing** | "Start processing" runs the deterministic engine only. Each investigation needs its own "Authorise an AI investigation" dialog | Under the button: "AI investigations will run automatically… every exception… may incur charges". Starting the run *is* the AI authorisation. No checkbox, no opt-out | Policy MANDATORY_AUTO_INVESTIGATION (6 Nov direction) | Upload batch page → Start processing | **Yes.** The analyst no longer decides per exception whether to spend on AI. Starting processing commits to paid calls for every exception (live runs used about 37k–130k tokens per investigation) | **Yes — and owner approval (cost and consent)** |
| U2 | Same, on **reassessment** | Reassess: reason + confirmation | Same dialog plus the disclosure. "Start reassessment" is disabled until the disclosure has loaded. Completion points to the Workspace first | Same | Monthly report → Reassessment | Same as U1 | **Yes** |
| U3 | Run outcome line | Run row: pack, outcome, number of exceptions | Plus "AI investigations: N queued automatically (…)" or "…not started: <reason>" | Visibility | Upload batch → runs; reassessment result | None | Optional |
| U4 | **Monthly report section 5: investigation processing panel** | Investigations table only | One row per pack with status counts, **"Investigate all exceptions"** and **"Retry failed"** (each with an "Authorise automatic AI investigations" dialog) | Pack-level control; historical packs | Monthly report | New bulk paid action available to the analyst | **Yes** |
| U5 | Authorisation dialog: provider rows | "Automatic fallback: groq · … used only if the primary provider is unavailable" | "Other providers: None — a failed request is reported as it failed and is never sent to another provider" | Groq removal | Every AI authorisation dialog | None (less to understand) | Informational |
| U6 | **REJECT: optional comment** | REJECT takes only a reason; a comment was refused | Optional "Analyst comment (kept separately from the reason)". After saving, the comment is shown separately, with a note on how the pack will show it | BA requirement | Exception Workspace → Analyst decision | The analyst may now add a second free-text field to a rejection | **Yes** (wording, and whether a comment should appear in the audit pack) |
| U7 | **Final pack wording for a rejection** | "EXC-… - AI investigation rejected by the analyst", badge "ANALYST DECISION: REJECTED", "Reason for rejection (as recorded by the analyst)" | "EXC-… - REJECTED BY ANALYST", "Reason for rejection (exactly as recorded by the analyst)", "Analyst comment (optional, separate from the reason)", rejected investigation reference, "AI content: Excluded…" | Explicit disposition | Final audit pack (JSON / HTML / PDF) | None; this is the auditor-facing wording | **Yes** (auditor-facing text) |
| U8 | **New blocker: a failed investigation must be retried or excluded** | A failed or unusable investigation could be left as NOT_INVESTIGATED; the pack said "not investigated" (a warning only) | GENERATE is blocked: "its AI investigation failed; retry it, or exclude it from the final pack with a documented reason" | A failed attempt is not the same as "not investigated" | Final review | **Yes.** The analyst must now take an extra action (retry or written exclusion) for each failed investigation | **Yes — and owner approval** |
| U9 | **Per-exception disposition table** | A checklist of review-level items | A table of every exception (disposition badge, job error, action links) plus counts, above the checklist | Visibility | Final review → Before you generate | None (presentation of existing rules) | **Yes** (layout and wording) |
| U10 | **"Include the N completed investigation(s)" shortcut** | Selections edited one by one | One click includes the first usable investigation of each exception that has one but is not selected | Convenience | Final review | **Yes.** A bulk selection made for the analyst; if an exception has several usable investigations, the first is chosen without asking. It still needs ACCEPT/REJECT afterwards | **Yes**, plus a test (none exists) |
| U11 | Workspace "Next step" text | Never run / failed: "An AI investigation is optional… otherwise reported as not investigated". Unusable: "Run a new investigation if useful, or continue" | Failed or unusable: "Retry the investigation, or exclude… with a documented reason; it cannot be reported as not investigated". Never run: "No AI investigation has run for this exception yet…" | Defect 4.4 (contradicted the new rule) | Exception Workspace | Follows U8 | Yes (wording) |
| U12 | Workspace AI panel after a failed automatic job | After a reload, a failed automatic job was not shown; "Run investigation" started an unlinked job | "The latest investigation failed" with the reason; button "Retry investigation" (linked) | Defect 4.3 | Exception Workspace | None | Informational |
| U13 | Status labels | "AI accepted by analyst", "AI rejected by analyst", "AI awaiting your review", "Investigation running" | "Accepted by analyst", "Rejected by analyst", "Findings ready for review", "Queued" / "Investigation in progress", "Investigation failed — reason available" | Consistency with the 8 states | Workspace, monthly report, final review | None | Optional |
| U14 | Historical fallback banner | "Answered by the fallback provider…" | "Historical record: answered by the former fallback provider… (removed since; OpenAI is now the only provider)" | Groq removal | Workspace (old investigations only) | None | Informational |
| U15 | Checklist table wrapping | Long labels clipped at the panel edge | Wrapped | Defect 4.5 | Final review side panel | None | No |
| U16 | Processing blocked while the AI configuration cannot be read | Processing never depended on AI | "Start processing" and "Start reassessment" stay disabled until the AI configuration has loaded (if `/ai/configuration` fails, they stay disabled) | Side effect of U1/U2 | Upload batch; reassessment | The deterministic step now depends on an AI endpoint answering | **Owner / technical decision** (see 6.3-c) |

---

## 4. Guard re-pin reviews (`uc042lib/final_pack`)

**The guard.** `tests/test_demo_history.py` pins a digest of the final-pack **library** (code, fonts and font metadata). The digest is SHA-256 over sorted "relative path NUL file SHA-256" lines, ignoring `__pycache__`. It stops unreviewed changes to the code that produces audit packs. It does not protect pack data; the `packs`, `investigations`, `uc042_dataset` and `tests/golden` digests do that, and the patch does not change them.

**Chain of pins (VERIFIED).**

| Pin | Files | Where it is pinned | Approval status |
|---|---|---|---|
| `af18244c…77d80f37` | 12 | **Live** `tests/test_demo_history.py` (live code is `1a638662…`, so the live guard fails today, on purpose) | Approved original |
| `1a638662…c1bf107` | 12 | Live code (Phase 8 `expected=`) | **Awaiting owner** (since 5 Nov) |
| `b6509a20…89f38c` | 18 | P10 test file and P10 code | **Awaiting owner** (with P10) |
| `8b0d6aa8…9f7942` | 18 | Only in the history comment (never pinned on its own) | **Awaiting owner** |
| `bf2dc23b…c709cae` | 18 | Clone E test file and Clone E code | **Awaiting owner** |

The 18 protected files are `__init__.py`, `assemble.py`, `content.py`, `model.py`, `persistence.py`, `render_html.py`, `render_pdf.py`, `report.py`, `snapshot.py`, `sources.py`, `summary.py`, `validate.py`, and `fonts/` (`DejaVuSans.ttf`, `-Bold`, `-Oblique`, `DejaVuSansMono.ttf`, `LICENSE-DejaVu.txt`, `fonts.json`).

### 4.1 Re-pin 1 — `8b0d6aa8…` (6 Nov: REJECTED BY ANALYST, rejection comment, rejected-content protection)

| Check | Result |
|---|---|
| Digest value | `8b0d6aa885b972a16cc2f864743308a97b7251735e83ff74de1af029dc9f7942`. **VERIFIED**: recomputed from Clone E's tree with `model.py` and `summary.py` taken from P10. It matches the value in the comment (`8b0d6aa8…9f7942`) |
| File set | 18 files, the same set as `b6509a20` (no file added or removed) |
| Files changed from `b6509a20` | `assemble.py`, `report.py`, `validate.py`. Their hunks in `end_to_end_workflow.patch` (6 Nov) and `live_verification.patch` (12 Nov) are **identical** (VERIFIED), so nothing was added to them later |
| Justification recorded | In the comment: "the explicit REJECTED BY ANALYST disposition and the optional comment on a rejection (rendered only for packs that carry the new 'disposition' field, so every earlier pack, including 4 with rejections, re-renders and verifies byte for byte), and the check that no rejected AI text appears anywhere in a final pack". Report: `END_TO_END_ANALYST_WORKFLOW.md` |
| Does the justification match the code? | **Yes.** `assemble.py` adds `disposition` and `comment`. `report.py` adds a rendering branch gated on `disposition == "REJECTED_BY_ANALYST"`, with the old branch unchanged. `validate.py` adds `_rejected_text_in`. Nothing else changed |
| Historical packs | **VERIFIED**: all 21 packs verify with this code (the later `bf2dc23b` only adds prompt text and a version string, which do not affect rendering). The 4 older packs with rejections (Clone E S05 v1/v3/v5, P10 e2e S05 v1) verify with both the P10 and the Clone E code |
| Unexpected changes | None found |
| Side effects to note | (a) Gated on the field, not on a renderer version. Packs with the new disposition do not declare a new `report_renderer`, unlike the Unicode renderer change, which declared `2.0-unicode`. Consequence: the old code renders such a pack the old way and verification fails. That is safe (nothing is misreported), but packs created after the upgrade **cannot be verified by the old code** (VERIFIED: 2 packs). (b) The rejected-text check runs only at preview and GENERATE, not inside `verify_final_pack` |

### 4.2 Re-pin 2 — `bf2dc23b…` (12 Nov: closing-summary prompt 1.1)

| Check | Result |
|---|---|
| Digest value | `bf2dc23bbc516b50bd19393fbbd9e5bfa00907b2115a04455d210b3e8c709cae`. **VERIFIED**: recomputed from `p10/uc042_e/uc042lib/final_pack`. It matches the pinned value |
| File set | 18 files, the same set |
| Files changed from `8b0d6aa8` | `model.py` (`SUMMARY_PROMPT_VERSION` 1.0 → 1.1) and `summary.py` (3 added prompt lines). Nothing else |
| Justification recorded | In the comment: "summary.py / model.py: the closing-summary prompt 1.1 tells the model to negate each disclaimer term separately (a live summary was refused for a long negated list); the validation is unchanged. Every published final pack re-verified before re-pinning". Report: `LIVE_VERIFICATION_REPORT.md` §4.2 |
| Does the justification match the code? | **Yes.** `summary.py` changes only the prompt text; `COMPLIANCE_PATTERNS` and the negation window are unchanged. The new test proves the long form is still refused |
| Wording of the disclaimer | The disclaimer *requirements* in the prompt ("not an audit opinion, not a compliance certification…") are unchanged. Only a new instruction on *how* to phrase them was added. The final-pack report's own disclaimer text (`report.py`) is not changed by this re-pin |
| Historical packs | **VERIFIED**: 21/21 verify. Stored summaries carry their own `prompt_version` (all 1.0 on disk), so the new default does not change them |
| Unexpected changes | None |
| Note | The comment block lists `8b0d6aa8` with its own line, but the 12 Nov entry has no digest prefix written next to it (only the final pinned value shows it). This is cosmetic, but the owner may want the history line to read "`bf2dc23b…c709cae` (18 files)" for consistency |

### 4.3 Is the new digest an accurate picture of what should be protected?

- **Yes for the intended scope.** It covers all code and fonts that build, render, validate and persist final packs, and nothing outside that package.
- **Not protected by this guard, though they affect pack content:**
  - `uc042app/services/reviews.py`, which decides readiness and what is included;
  - `uc042app/services/investigation_reviews.py`, which decides what a REJECT may store.

  Both changed in this patch. That is by design (the guard protects the library, not the services), but the owner should know that a review of the guard alone does not cover them.

---

## 5. Historical integrity assessment

| Item | Result | Basis |
|---|---|---|
| All published final packs re-render and verify with the patched code | **21 / 21 OK** | VERIFIED (this review). Offline `verify_final_pack`, Clone E code |
| Same packs with the P10 code | 19 OK, **2 FAIL** (the 2 new-disposition packs: Clone E `FAP-CASE-…-v10-964869b18b72` and `FAP-S05-…-v8-a4f23fa94f33`). Errors: "report.html / report.pdf is not the rendering of final_pack.json" | VERIFIED (this review). Shows forward-only compatibility |
| Live historical pack (`FAP-H202602-PER-2026-02-v1`) | OK with both | VERIFIED (this review) |
| Packs with old-format rejections (4) | OK with both | VERIFIED (this review) |
| Data trees (`packs`, `investigations`, `uc042_dataset`, `demo_history`, `tests/golden`) | Identical in P10 and Clone E; not in the patch | VERIFIED (this review). Tree diff |
| Guard test (`test_demo_history`) on Clone E | See section 5.1 | Re-run in this review |
| Deterministic outputs of 21 packs; 17 baseline packs | Identical | RECORDED (H-2) |
| Golden-pack equality of 4 live uploads | Identical | RECORDED (A-GOLD…) |
| Databases `uc042`, `uc042_p10b` | Row counts unchanged | RECORDED (S5) |
| Stored investigations | Unchanged. New prompt versions apply only to new investigations | VERIFIED (code) |
| Historical fallback records | Still readable and shown, labelled as historical | VERIFIED (code) |

### 5.1 Tests re-run during this review (Clone E, offline, temporary folders only)

Run on 15 Nov 2026 with the shared Python 3.11 venv and the Clone E `uuid_utils` shim on `PYTHONPATH`. No provider keys and no database URL were set (SQLite and temporary folders, mocked providers). No bytecode was written.

| Module | Result |
|---|---|
| `tests.test_demo_history` (includes the `uc042lib/final_pack` guard at `bf2dc23b…` and the protected data-tree digests) | **61 OK** |
| `tests.test_openai_only_provider` | 7 OK |
| `tests.test_auto_investigations` | 11 OK |
| `tests.test_end_to_end_workflow` | 2 OK |
| `tests.test_analyst_review` | 12 OK, 1 skipped (PostgreSQL-only) |
| `tests.test_closing_summary` | 11 OK |
| `tests.test_findings_schema_14` | 6 OK |
| `tests.test_review_hardening` | 12 OK |

**Not re-run here:**
- the full backend suite (RECORDED: 683 OK, 24 skipped);
- the PostgreSQL suite (RECORDED: 125 OK);
- vitest (RECORDED: 74 passed, 2 skipped), `tsc` and `vite build` (RECORDED: pass).

---

## 6. Technical risks and migration dependencies

### 6.1 Verified risks (shown by evidence in this review)

| # | Risk | Evidence | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **The patch does not apply to live.** It needs the P10 state first | Live `final_pack` = `1a63…` (12 files); 71 file differences live → P10, including migration 0005, fonts, `runtime_paths.py`, UI simplification | Applying it to live directly fails or gives an inconsistent tree | Migrate live → P10 → Clone E as one reviewed set (see section 8) |
| R2 | **Groq would switch on if P10 code reaches live before this patch** | Live `.env`: `UC042_LLM_FALLBACK_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_BASE_URL`, `UC042_LLM_FALLBACK_MODEL`, `UC042_LLM_FALLBACK_MAX_TOKENS` present; P10 contains `fallback.py` | Data sent to Groq against the owner's 12 Nov direction | Remove the variables (and revoke the key) **before** any P10 code runs on live; or deploy P10 and this patch together |
| R3 | **Rollback limit, packs.** After the first REJECTED BY ANALYST pack is published, the old code cannot verify it | 2 Clone E packs fail with the P10 code | A code rollback leaves packs that "fail verification" | Treat the renderer as forward-only once such a pack exists; any rollback keeps the `final_pack` library |
| R4 | **Rollback limit, database.** Inherited from P10: once a 0005 decision exists, the old code refuses to start | RECORDED (P10 readiness report, rehearsed) | Rollback means restoring the database | Backup before 0005; rehearsed restore |
| R5 | **Every processing or reassessment run makes paid calls**, even when the client sends no disclosure | `test_investigation_is_mandatory_no_opt_in_needed`: no `ai_authorization` → AUTHORIZED with `disclosure_shown: False`, all exceptions queued | Scripts, an old browser tab or an API client trigger charges without seeing the disclosure. Recorded honestly, but this weakens the Phase 8 principle that a paid call needs an explicit confirmation | Owner decision: accept it, or require `ai_authorization` (refuse or record NOT_STARTED when it is missing) |
| R6 | **Open review sessions become blocked** after the upgrade if they hold failed investigations | `reviews.py` new blocker | Analysts see new blockers on work in progress | Tell analysts; list affected sessions before migrating |
| R7 | **A restart turns queued investigations into failures** | `JobRunner.shutdown` marks QUEUED → INTERRUPTED; `exception_status` treats INTERRUPTED as FAILED. With a 1-worker lane, a long queue is likely at restart | After a restart, many exceptions need "Retry failed" (and a new authorisation) | Operational note; restart when the AI lane is idle |
| R8 | **Smart App Control blocks `uuid_utils`**, so `langchain_core` / LangGraph cannot load | RECORDED (12 Nov); Clone E uses a shim outside the repository | P10 and live backends cannot run investigations, or may not start | Owner choice: shim, signed build, or a different `langchain_core`. **Not in the patch** |
| R9 | Two UI paths have no automated test: the "Include the N completed investigation(s)" shortcut (no browser evidence either) and the monthly-report panel | grep of test suites and `results.json` | Regressions would go unnoticed | Add a vitest before migration, or accept with the BA |
| R10 | AI lane and `UC042_AI_JOB_WORKERS` validation have no unit test | grep | Low | Accept, or add a small test |
| R11 | First-attempt refusals of live investigations (2 of 7 for citing an unverified candidate relationship) | RECORDED (§14.1) | With mandatory investigation, more failures need retry or exclusion (U8): analyst workload and cost | Owner decision on options (a), (b) or (c) of §14.1 |
| R12 | Pre-existing flaky test `test_phase8 … v2_superseding_v1` (timestamps stored to the second) | RECORDED (§14.2) | Intermittent CI failure; a real ordering issue in the same second | Not caused by the patch; track separately |

### 6.2 Compatibility summary

- **Database schema.** No new migration. It depends on 0005 (part of P10). New values go into existing columns: the `operation` value, and the JSON fields `trigger` and `auto_investigation`. Records are append-only and old records are unchanged.
- **Historical packs.** Compatible going forward (21/21). Not compatible going back for new-disposition packs (R3).
- **API contracts:**
  - Additive: the auto-investigation endpoints, an optional body on `process`, `ai_authorization` on reconcile, `readiness.checklist`.
  - **Breaking:**
    - `AiConfiguration.fallback` is removed.
    - `fallback_provider` other than `"none"` gets 409.
    - REJECT with a comment changes from 422 to 201.
    - The new readiness blocker code `INVESTIGATION_FAILED_NO_DISPOSITION`.
    - `operation` may now be `AUTO_INVESTIGATION`.
- **Frontend.** The frontend and backend must be deployed together. An old frontend with the new backend does not send a disclosure, so runs are still investigated (R5), and it does not know the new operation or checklist. A new frontend with the old backend fails on the new endpoints.
- **OpenAI-only.** `UC042_LLM_PROVIDER=groq` now fails start-up of AI ("unsupported provider"). The fallback variables are ignored. The Groq key is no longer redacted from error text.
- **Environment:**
  - Smart App Control (R8).
  - Groq variables still present (R2).
  - An inline comment after `OPENAI_API_KEY` in live `.env` (RECORDED: harmless for `python-dotenv`, but best moved).
  - `UC042_FINAL_PACKS_ROOT` is not set on live: a P10 dependency, since the P10 backend refuses a root inside the repository; the default is `%LOCALAPPDATA%\UC042\final_packs`.
  - The new optional `UC042_AI_JOB_WORKERS`.

### 6.3 Possible concerns (found by reading the code; not shown to fail)

- **(a)** R5 above is intended by the tests, so it is a policy question, not a bug. I list it because it changes a governance property approved in Phase 8.
- **(b)** The run-level authorisation is stored with an empty `pack_id`, because the pack does not exist yet. A query of authorisations **by pack** therefore does not find it directly; `pack_status` finds it through the jobs. If auditors look up authorisations by pack ID, they may miss run-level ones.
- **(c)** `ArchivePages` and `Reassessment` disable the run buttons until `/ai/configuration` has answered. The endpoint catches configuration errors, so a failure is unlikely, but if it happens the deterministic step cannot be started from the UI. The backend would accept it. Consider allowing processing with a visible "AI status unknown" note.
- **(d)** The "Include the N completed investigation(s)" shortcut picks `usable_investigations[0]` when there are several. Which investigation that is depends on list order.
- **(e)** The new disposition is gated on a data field instead of a declared renderer version (4.1-a). That is safe, but it differs from the convention used for the Unicode renderer.
- **(f)** Each readiness call computes `exception_status` per exception, with job-list queries for each. That is fine at current sizes (at most 8 exceptions per pack) and worth watching if packs grow.

### 6.4 Rollback considerations

1. **Before migrating:** `pg_dump` of `uc042`, a copy of the live tree, the live `.env` and all final-pack roots, as was done for 0004.
2. **Before any new decision, pack or authorisation exists:** a code rollback plus a database restore is clean.
3. **After the first 0005 decision:** database restore only (R4).
4. **After the first REJECTED BY ANALYST pack:** keep the patched `final_pack` library in any rollback, or accept that the pack shows as unverifiable under the old code (R3).
5. Authorisation records (`AUTO_INVESTIGATION`) are immutable through a PG trigger. A rollback by restore removes them along with everything else; there is no partial clean-up.

---

## 7. Approval register

**Classification used:**
- **A** — Technically ready for approval.
- **B** — Requires further investigation.
- **C** — Requires business/UI review.
- **D** — Not recommended for migration.

This is not an approval decision.

| # | Change | Technical review | Owner approval | BA approval | Migration dependency | Classification |
|---|---|---|---|---|---|---|
| 1 | Mandatory automatic investigation after every processing or reassessment run (files 37, 43, 45, 46, 05, 06, 15) | Coherent, well tested (11 backend tests in `test_auto_investigations`, plus `test_end_to_end_workflow` and `test_api_monthly`; LIVE C-*). Paid calls happen even with no disclosure (R5) | **Required** (cost, consent model, R5) | **Required** (U1, U2) | P10 (0005), AI lane, provider funded, R8 resolved | **C** (with R5 needing investigation, **B**) |
| 2 | Pack-level "Investigate all exceptions" / "Retry failed" (36, 10, 16, 04) | Backend tested; no vitest | Required (paid bulk action) | Advisable (U4) | as 1 | **C** |
| 3 | Bounded AI job lane + `UC042_AI_JOB_WORKERS` (40, 39, 41) | Simple, LIVE timing check; no unit test | Informational | — | none | **A** |
| 4 | Groq removal / OpenAI only (53, 54, 55, 56, 42, 38, 01, 03, 04) | Clean removal, 7 new tests, LIVE: no Groq contact | **Required** (listed in §14.7) | — | Delete Groq variables from live `.env`, revoke the key, delete `env_e/ai.env` (R2) | **A** |
| 5 | Stale fallback confirmation refused with 409 (42, 38) | Tested | With 4 | — | Frontend and backend deployed together | **A** |
| 6 | Investigator prompt 1.3 / 2.3-tools (57, 53) | Fix verified live; test that the prompt names every pattern | **Required** (prompt versions) | — | none | **A** |
| 7 | Closing-summary prompt 1.1 + **guard re-pin `bf2dc23b`** (51, 49, 29) | Digest reproduced; validation unchanged; packs 21/21 | **Required** (re-pin + prompt) | — | Re-pins `af18→1a63→b650` approved first, or one combined decision | **A** |
| 8 | REJECTED BY ANALYST disposition in packs + **guard re-pin `8b0d6aa8`** (48, 50, 29) | Digest reproduced; old packs byte-identical; forward-only (R3) | **Required** (re-pin, rollback rule) | **Required** (U7, auditor wording) | as 7 | **C** |
| 9 | Optional comment on REJECT (44, 09) | Tested in API, PG, JSON, HTML and PDF; covered by the glyph check | Informational (API contract change) | **Required** (U6: should the comment appear in the audit pack?) | 0005 | **C** |
| 10 | Rejected-AI-text leak validation (52) | Tested; LIVE zero leaks | With 8 (protected file) | — | as 7 | **A** |
| 11 | New blocker `INVESTIGATION_FAILED_NO_DISPOSITION` (47, 11) | Tested | **Required** (listed in §14.7) | **Required** (U8: new analyst duty) | Analysts told about open sessions (R6) | **C** |
| 12 | Readiness checklist + disposition table (47, 17, 03, 18) | Backend tested; table LIVE only | — | **Required** (U9) | none | **C** |
| 13 | "Include the N completed investigation(s)" shortcut (17) | **No test, no browser evidence**; picks the first usable investigation (6.3-d) | — | **Required** (U10) | A test is needed | **B** |
| 14 | Workspace retry linkage and failed-job display (08) | Fix; vitest + LIVE C-10R | — | Informational | none | **A** |
| 15 | "Next step" wording (11) | Fix; vitest + LIVE | — | Advisable (U11) | Depends on 11 | **C** (wording only) |
| 16 | Status label renames (09, 10) | Tested | — | Optional (U13) | none | **A** |
| 17 | Historical fallback banner relabelled (08, 03, 45) | Read-only | — | — | none | **A** |
| 18 | Checklist table wrap / `.linklike` (18) | LIVE LV32 | — | — | none | **A** |
| 19 | Run buttons disabled until the AI configuration loads (15, 06) | Side effect; untested failure path | Decision advisable | Advisable (U16) | none | **B** |
| 20 | Retired `test_provider_fallback` (16 tests) + new tests | Matches 4 | With 4 | — | none | **A** |

**Environment items (not in the patch, but needed for it):**

| # | Item | Status | Owner approval | Classification |
|---|---|---|---|---|
| E1 | `p10/env_e/shims/uuid_utils` (pure-Python stand-in for the blocked native module) | Clone E-only workaround, outside the repository and the patch | Required (choose a solution, R8) | **D** as built (a temporary workaround). A supported solution needs a decision |
| E2 | `p10/env_e/launch_backend.py --test-model` | Test-only launcher option | — | **D** (not for live) |
| E3 | Remove Groq variables from live `.env`, revoke the Groq key, delete `env_e/ai.env`, move the `OPENAI_API_KEY` inline comment | Not done (by design) | Required | Prerequisite |
| E4 | Set `UC042_FINAL_PACKS_ROOT` for live (P10 dependency) | Not done | Required | Prerequisite |
| E5 | OpenAI account funded (credits) | Funded on 12 Nov (live runs succeeded) | — | Prerequisite |

---

## 8. Recommended migration sequence

The order only. Each step needs the owner's go-ahead; nothing here is authorised.

1. **Decisions first (owner, and BA where marked):**
   - mandatory investigation and its cost, and R5 (U1/U2);
   - the failed-investigation rule (U8);
   - the auditor-facing rejection wording and the comment (U6/U7, BA);
   - the checklist and the shortcut (U9/U10, BA);
   - the prompt versions (6, 7);
   - option (a), (b) or (c) for first-attempt refusals (R11);
   - the Smart App Control solution (R8);
   - the full guard chain `af18 → 1a63 → b6509a20 → 8b0d6aa8 → bf2dc23b`: approve each step, or one combined re-pin that records every reason.
2. **Prepare the environment:** remove the Groq variables from live `.env` and revoke the key (R2); set `UC042_FINAL_PACKS_ROOT`; put the chosen Smart App Control fix in place; keep the OpenAI account funded.
3. **Build one combined live → Clone E change set**, rather than applying P10 and then this patch on live. That way the Groq fallback code is never live, even briefly. Check it on a scratch copy of live: the patched copy must equal Clone E (plus the binary fonts, which a text patch does not carry).
4. **Back up:** `pg_dump uc042` (check with `pg_restore --list`), the live tree, `.env` and every final-pack root. Take before/after row counts, as for 0004.
5. **Stop** the live backend and frontend, when no job is QUEUED or RUNNING.
6. **Apply** the combined set. Copy the fonts. Run `db-upgrade` to 0005. Apply the owner-approved guard pin.
7. **Verify before reopening:**
   - full backend suite (file mode), the PostgreSQL suite, vitest, `tsc` and `vite build`;
   - `verify_final_pack` on every published pack, expecting the live February pack to pass;
   - deterministic output hashes of every pack equal to before;
   - row counts unchanged apart from the new tables.
8. **Start** the backend and frontend. Smoke test: the AI configuration shows `openai · gpt-6-luna` and "Other providers: None". Process one small period and confirm the automatic jobs, one ACCEPT and one REJECT with a comment, then GENERATE and check the PDF.
9. **Tell analysts** about open review sessions that are now blocked (R6), and about restart behaviour (R7).
10. **Rollback plan ready** (section 6.4). After the first new decision or pack, rollback means a database restore and keeping the new `final_pack` library.

---

*Stop condition observed. This review changed no source file, patch, digest, database or historical pack, and approved nothing. Findings are submitted for owner review.*
