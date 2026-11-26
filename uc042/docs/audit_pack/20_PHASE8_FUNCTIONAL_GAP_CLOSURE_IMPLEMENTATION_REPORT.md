# 20 — Phase 8: Functional Gap Closure, Safe Workflow Improvements and Calculation Documentation

ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

**Date:** 4 November 2026, about 16:40–17:50 IST.

**Basis:**
- `19_COMPLETE_UI_FUNCTIONAL_AND_ARCHITECTURE_AUDIT.md` (the audit);
- `19_DATABASE_UNIFICATION_AND_FUNCTIONAL_GAP_CLOSURE_IMPLEMENTATION_REPORT.md` (unification).

**Companion document:** `20B_RECONCILIATION_CALCULATIONS.md`, explaining how the deterministic calculations work.

**The brief was truncated.** It ended in Part I item 4, at "…where the source record is already available to an authorised". Parts A–I were implemented. Anything specified after that point was not seen; see §10.

---

## Summary of results

| Part | Result |
|---|---|
| A Baseline | Recorded. One correction to earlier reports: `uc042_history` **is retired** (`uc042_history_retired_20261104`, read-only). |
| B Review URLs read-only | **Done and tested** (backend + UI). No page load, refresh or navigation creates a session; the explicit action logs `REVIEW_OPENED`. |
| C AI authorisation gate | **Done and tested.** Investigation and closing summary each need an explicit, recorded, immutable authorisation *before* the job runs. Refusals are recorded. A PostgreSQL trigger refuses UPDATE and DELETE. |
| D Reassessment | **Done and tested, end to end in the browser.** Reassessment reuses hash-verified original sources, records lineage with a change summary, and continues the version sequence (v3 superseded v2 across a reassessment). |
| E Case UI | **Done and tested** on the existing case APIs. |
| F Investigation page and snapshot fix | **Done and tested.** |
| G KPIs and activity | **Done and tested.** |
| H Performance | **Done.** Every measured page now loads in under 3 s (it was 10–33 s); see §7. After the continuation, under 1.6 s from a cold start (§10.5). |
| I Other corrections | **Done:** header-only files, policy-aware `processing_supported`, labels and empty states, and source evidence without AI (completed with provenance and an engine / AI distinction in the continuation, §10). |
| Live database | **Not migrated, by choice.** The new code needs migration `0004` on `uc042`. That is a step for you; commands are in §9. |
| One guard test | **Left failing on purpose.** `uc042lib/final_pack` changed by one optional parameter, and that folder's pinned digest needs your decision (§8). |

---

## 1. Part A — baseline (16:41–16:51 IST, before any edit)

**Working tree.**
- The other session's last code change was at 16:12 and its last document edit at 16:24. No other session was running during Phase 8.
- Hash snapshots: 292 source files (`uc042_phase8/source_baseline.sha`) and **827 protected artefact files** (`packs/`, `investigations/`, `uc042_dataset/`, `demo_history/`, `UC042_JAN_AUG_HISTORICAL_DEMO/`).

**Database** (read-only checks):

| Item | State |
|---|---|
| Active database | `uc042` at `0003_unified_schemas` |
| Periods | 9; September holds 9 pack references |
| Registry | seq 1 February (APPROVED), seq 2 June (AUTHORIZATION_DISCREPANCY) |
| Review sessions | 2: `RS-898ce…` GENERATED; **`RS-fc0a6e7f8aa4512c18b9a891` OPEN** (the authorised audit probe, still recorded) |
| `uc042_history` | **No longer exists.** `uc042_history_retired_20261104` has `default_transaction_read_only=on` and 0 connections. Audit L-16 has been corrected accordingly. |
| Other databases | `uc042_test`, `uc042_audit19`, `uc042_audit19_test`, `uc042_e2e_rehearsal`: present; only disposable test use, as stated below |

**Artefacts:**
- The February final pack verifies.
- February investigation `6b1425b437f4` and June `c7b353b53fb3` verify, both as artefacts and against the registry.
- The 7 September POC artefacts are present and unregistered.

**Tests:**
- Python **605 run, OK, 1 skipped** (opt-in live AI), on `uc042_test`.
- Frontend **40 passed, 2 skipped**.

**Housekeeping.** I also fixed the `\u` path corruption in my own audit report: four `%USERPROFILE%\uc042_a19` paths had become the character `\uc042`.

## 2. Part B — reviews are opened explicitly

**Backend.**
- `ReviewService.open` is only reached through `POST /packs/{id}/reviews`. It still returns an existing active session, so there are never duplicate active sessions.
- It now logs `REVIEW_OPENED`.
- The rest of the review lifecycle is logged too: `REVIEW_SELECTIONS_CHANGED`, `PREVIEW_REQUESTED`, `REVIEW_HOLD`, `REVIEW_GENERATED`, `REVIEW_GENERATION_FAILED`. Each event records `period_id`, `pack_id` and `review_id`, and the final pack ID, version and supersedes where relevant.

**Frontend.** `/packs/:packId/review` (`OpenReviewPage`) is **read-only**:
- with an active session, it navigates to it;
- otherwise it lists the pack's earlier reviews (status, last decision, final pack) and the latest published version, with an explicit **"Open a new final review"** button.

The sidebar, report, pack and workspace links all point at this page, so none of them creates anything.

**The existing session `RS-fc0a6e7f8aa4512c18b9a891`** was left untouched, as instructed.

**Tests:**
- `ExplicitReviews`: GET, listing and refresh create nothing; the explicit open creates exactly one session and logs it; a GENERATED review is never replaced by reading.
- Frontend `phase8.test.tsx` B: no `openReview` call on load or refresh; exactly one call on the button; an active session is shown, not re-opened.

## 3. Part C — explicit AI authorisation before paid operations

### Data model

**New table `audit.ai_execution_authorizations`** (migration `0004_ai_authorization_lineage`):
- columns: `authorization_id` (`AIA-…`), `operation` (INVESTIGATION / CLOSING_SUMMARY), `result` (AUTHORIZED or REFUSED_\<code\>), `period_id`, `pack_id`, `exception_id`, `review_id`, `case_id`, `job_id`, `provider`, `model`, `authorized_by`, `authorized_at`, `details`;
- `details` records the statement shown, `provider_configured`, the reasoning effort, the selected investigations, `model_call_expected` and `retry_of`;
- a PostgreSQL trigger refuses UPDATE and DELETE (tested);
- the repository has no update or delete method;
- file-backed mode keeps an append-only JSON-lines equivalent.

**It is a separate table from `audit.investigation_authorizations`,** which records decisions about already-published investigations. Nothing mixes the two. The read endpoint is `/api/v1/ai/confirmations`, because the API's own guard test forbids "auth" in paths so that no authentication endpoint can exist.

### Order of operations

The order is the same in `InvestigationService.start` and `ReviewService.request_preview`:

1. Validate the confirmation (`confirmed: true`).
2. Check that any provider or model the dialog showed is still the configured one; otherwise 409 `AI_CONFIGURATION_CHANGED`, recorded.
3. Check for an active job or preview (`INVESTIGATION_ACTIVE` / `PREVIEW_IN_PROGRESS`, recorded) and for blockers.
4. Check the provider; `PROVIDER_NOT_CONFIGURED` is recorded for investigations.
5. **Create the job (QUEUED, not running).**
6. **Insert the AUTHORIZED record linked to the job.**
7. Only then submit the job.

If the record cannot be written, the job is marked FAILED and never runs. Every job view carries `authorization_id`. An interrupted job stays traceable.

### API and UI

**API:**
- start-investigation, case-AI and preview requests take `authorization: {confirmed, provider, model}`; without it the response is 422 `AUTHORIZATION_REQUIRED`;
- `GET /api/v1/ai/configuration` returns what the dialog shows (no secrets).

**UI (`AiAuthorizationDialog`):**
- **Contents:** period and title, pack, exception and description (or the selected investigations for a summary), provider, model, reasoning effort and configured state, the charges notice, the approved-evidence and cannot-resolve statements, and the limits.
- **Confirmation:** a required tick-box with the operation's statement. Cancel sends nothing, and the confirm button is disabled while sending.
- **No provider:** an investigation is blocked with a clear notice. A closing summary is allowed, and the dialog says the summary will be UNAVAILABLE, so the existing UNAVAILABLE path and its GENERATE acknowledgement are unchanged.

**Tests (`AiAuthorization`, 9 tests, plus `AiAuthorizationImmutableInPostgres`):**
- no job and no model call without confirmation (cancel and `confirmed:false`);
- **at the moment of the model call, the AUTHORIZED record already exists with that job ID**;
- repeated clicks give one job and a recorded `REFUSED_INVESTIGATION_ACTIVE`;
- missing provider and changed configuration are refused and recorded;
- an interrupted job keeps its authorisation link;
- records are append-only (file repository and PostgreSQL trigger);
- the closing summary has its own authorisation, with and without a provider.

**Frontend C:** Cancel sends nothing; confirmation sends one request with the shown provider and model; a cancelled summary dialog sends no preview request.

**No live OpenAI call was made in Phase 8.** Every test uses the mock or a disabled provider. The browser checks used instances with `OPENAI_API_KEY=""`, so `provider_configured: false`.

## 4. Part D — reassessment, evidence reuse and lineage

### D1 Reassess action

**`GET /periods/{id}/reassessment`** is a read-only plan. It shows:
- the latest final pack and the pack being reassessed;
- the documents received after publication (with times compared as instants; a timezone-offset defect found during browser testing was fixed and is covered by a regression assertion);
- the verified baseline;
- the effective document set, slot by slot, uploaded or baseline;
- what is missing;
- blockers.

**UI:** the monthly report has a **Reassessment** section showing this plan, with a **"Reassess \<Month\>"** button. It requires a reason and a confirmation dialog, then calls `POST /periods/{id}/reconciliation {purpose: REASSESSMENT}` and polls the run. It shows the outcome and offers "Go to its final review".

**Normal processing never substitutes for reassessment:**
- `POST /uploads/{id}/process` and an INITIAL reconcile of a period with a published final pack return 409 **`REASSESSMENT_REQUIRED`**;
- the batch page shows a pointer to Reassess instead of "Start processing".

### D2 Reuse of the original historical sources

`MonthlyService.baseline()` takes the **lineage's first pack** and uses only:
- files its own `evidence_register` lists as PRESENT, with a SHA-256;
- paths matching `source_data/*.csv` or `supporting_documents/*.pdf` (so never answer keys, scenario definitions or `verification/`);
- files inside that pack's **own dataset folder, in its own storage root set**;
- a pack of the **same month**.

Every file is hashed when the plan is made and **again when it is materialised**. Any missing or changed file stops the reassessment with 409 **`BASELINE_UNVERIFIABLE`**, listing the problems; nothing runs (tested on a tampered temporary copy).

**Uploaded, confirmed documents supersede baseline files slot by slot.** The run records:
- `document_set` (uploaded);
- `baseline {pack_id, dataset, storage_profile, files {slot: source_file, sha256}}`;
- `predecessor_pack_id`, `reassessed_final_pack_id` and `baseline_files`.

**No database document records were invented:** baseline files appear only as provenance in the run. A month created from uploads has no baseline (`baseline: null`); its latest confirmed documents are the set.

### D3 Letters matched against the verified inventory

`_resolve_letters` now falls back to the IN-02 account inventory of the period's verified pack: the reassessed lineage, or the period's single registered pack. The file is re-hashed before it is read. A re-sent February acknowledgement letter is now identified as IN-15/16, with `slot_resolved_by` naming the pack, instead of `LETTER_NOT_MATCHED`.

**A letter that cannot be matched is still an ERROR.** September holds nine independent scenario packs, so it has no single inventory, and a letter there is not assigned by guesswork (tested). The validation rule was not relaxed.

### D4 Lineage and versions

**New table `audit.pack_lineage`:** pack, period, predecessor, lineage root, purpose, run, reason, `change_summary`, recorded at and by. It is written once per reassessed pack.

**`change_summary`** is read from the two packs:
- inputs changed, added and removed (by evidence type and hash);
- engine status before and after;
- evidence completeness;
- control outcomes;
- exceptions added, removed and unchanged (matched by category, account, currency, dates and amount, because IDs carry the scenario prefix).

**Versioning.** `FinalPackService.next_version` numbers versions over the lineage. A reassessed pack's first final pack is v(n+1) and supersedes the period's previous final pack. A pack without a lineage row behaves exactly as before, so the **nine September scenarios keep independent sequences** (tested).

**Library change.** This needed one optional `expected=(version, supersedes)` argument on `uc042lib/final_pack/persistence.publish_final_pack`. Its default is the previous per-pack rule, and nothing else in the library changed (§8).

**Final-pack page.** "Version history" lists the whole lineage (`GET /final-packs?pack_id=…&lineage=true`).

**Tests:**
- `ReassessmentLineage`: INITIAL → v1; `NOTHING_TO_REASSESS`; a correction of IN-09 → `REASSESSMENT_REQUIRED` on process → plan → REASSESSMENT → new pack linked, IN-09 in `inputs_changed` → **v2 supersedes v1**; v1 is byte-identical and verifies; nothing is pending after v2. Plus independent September scenarios.
- `HistoricalReassessment` (February, temporary storage profile): letters; tampered baseline; **reassessment after additional evidence succeeds from verified originals and leaves the profile and final packs byte-identical** (updated `test_unification` test).

**Browser, end to end** (isolated copy, screenshots P01–P21):
1. Add a supporting document on the February report; confirm it; the batch points to Reassess.
2. Reassess with a reason; the run SUCCEEDED and lineage was recorded (`PACK-CASE-PER-2026-02-54bf8326eb35` ← `PACK-H202602-…`).
3. Open a new final review explicitly; authorise the closing summary (no provider, so UNAVAILABLE and acknowledged); GENERATE.

**Result: `FAP-CASE-PER-2026-02-v3-0c61d850175b`, version 3, superseding `FAP-H202602-PER-2026-02-v2-…`. Integrity verified.**

The isolated database also holds `FAP-CASE-PER-2026-02-v1-f3f…`, produced during the audit under the old code before lineage existed. It is test-environment history and has no live counterpart.

## 5. Parts E and F — cases, investigations

### E Case workspace

The new route is `/cases/:caseId`, reached from the exception workspace's "Investigation case" panel (open, or link to the existing case). It shows:
- **A prominent statement** that a disposition resolves nothing: the exception stays UNRESOLVED and published packs are unchanged.
- **The exception as recorded.**
- **The append-only history.**
- **An entry form** for note, evidence, evidence gap, observation, hypothesis or decision (with disposition and close). It sends `expected_revision`; every validation is the backend's (`INVALID_EVIDENCE_REF`, `EVIDENCE_REQUIRED`, `CASE_CHANGED`, `CASE_CLOSED`) and is shown verbatim.
- **Supporting financial records** retrieved without AI, each selectable as a citation.
- **Investigation history** with links.
- **"Request an AI investigation"**, through the authorisation dialog.

Case activity events now carry period, pack and exception.

### F Investigations

`/investigations/:id` is now a real page, built only from the stored artefacts through the existing APIs. It shows:
- record: model, prompt and schema, registry, authorisation decision, findings hash;
- eligibility and its reasons;
- findings by class;
- evidence records;
- **tool calls** (new read-only `GET /investigations/{id}/tool-calls`, metadata only);
- validation and publication verification.

It links to the exception workspace using the IDs recorded in the findings. Report-page and AI-panel investigation IDs link to it.

**Snapshot fix.** The review snapshot's other-attempt eligibility is now the **application's**: registry plus authorisation plus library rules. The library's eligibility alone no longer decides it. An unregistered artefact is reported as `published_ineligible`, never "eligible, not selected" (tested on February). The snapshot hash is unchanged, because attempts are not part of its content.

**Unchanged by design:**
- the June AUTHORIZATION_DISCREPANCY;
- the seven unregistered September artefacts, three of which fail the current rules;
- the February Phase 6A artefact.

Nothing was registered, approved, re-run or included.

## 6. Parts G and I — counts, activity, other corrections

### G KPIs and activity

**`GET /api/v1/dashboard?period_id=`** counts from the records. For investigations it gives published (registered, not discrepant), eligible, running, rejected attempts, unregistered, authorisation discrepancy and ineligible-other. It also gives:
- exceptions with an eligible investigation;
- final packs for the period **and** a global total, labelled as global;
- pending reviews for the period and globally;
- per-pack counts.

**Period and pack-reference views** carry the same `investigation_counts`. The dashboard and archive use them instead of per-pack requests.

**Activity labels** cover every event code, including `DATABASE_UNIFIED`, `CASE_*`, `REASSESSMENT_STARTED`, review, AI and lineage events. An unknown code is shown as words, never as a constant. The feed links reviews, cases, packs and final packs.

### I Other corrections

1. **Header-only files across months:** identical content is now `HEADER_ONLY_SAME_AS_OTHER_PERIOD` (INFO, no decision). This applies only to an identified CSV with 0 records; files with records still need the decision (tested).
2. **`processing_supported()`** is now false where no registered policy version applies. For example PER-2025-06 gets `processing_limitation`: "no registered safeguarding policy version applies…". The archive and period views report it (tested).
3. **Labels and empty states** updated: activity, workspace evidence, review page, reassessment, lineage.
4. **Source evidence without AI:** `GET /packs/{p}/exceptions/{e}/source-evidence` runs the approved deterministic retrieval an investigation starts from (`build_case`, `route_for`, `retrieve`, `build_packet`, over hash-checked sources). It uses no model and writes nothing. The workspace shows these records when no investigation is selected, and the case page uses them for citations (tested: no job, no model call).

## 7. Part H — performance

**Causes found:**
- `PackService.load` deep-copied each multi-MB pack on every call, and the period and pack lists load every pack;
- the frontend requested the period and pack lists several times per page;
- the dashboard requested investigations per pack.

**Changes:**
- **Backend:** `PackService.peek()` and `summary_of()` read the verified, cached pack without copying, on read-only list paths only. `load()` still returns a private copy for every other caller.
- **Frontend:** `apiSource` shares concurrent list requests and reuses results for at most 10 s. The cache is dropped after **every** change made through the app and whenever a polled job finishes, so new documents, investigations and publications are never hidden (tested).
- **Dashboard:** uses `/dashboard` and the period counts, with no per-pack fan-out.
- **Report page:** a reload no longer unmounts the page. That also fixed the reassessment outcome disappearing.

**Measurements** were taken on a restored copy of `uc042` (`uc042_phase8_perf`, migrated to 0004) with the real artefact folders and the new code. Times run until no "Loading" text remained, in headless Edge, local machine.

| Screen | Audit (old code, live) | Phase 8, after restart ("cold") | Phase 8, repeated ("warm") |
|---|---|---|---|
| Monthly reports archive | 10.0 s | **0.68 s** | 0.42 s |
| Dashboard, February | 33.5 s (dashboard) | **0.65 s** | 0.54 s |
| Dashboard, September | 20.9 s | **0.67 s** | 0.63 s |
| February report | 27.2 s | **0.65 s** | 0.75 s |
| June report | 10.3 s | **0.75 s** | 0.75 s |
| September report (nine scenario packs) | 20.1 s | **2.92 s** | 2.78 s |

**API timings:**
- first `/periods` after the backend restart: 0.75 s, then 0.46 s;
- `/packs`: 0.007 s (was 0.95 s);
- `/periods/PER-2026-09`: 0.21 s;
- `/dashboard`: 0.19 s.

**Caveat on "cold":** page timings were taken after those first API requests, so the backend's pack cache was already warm. A true first page after a restart adds about 0.3–0.8 s.

The September report is the slowest page (still under 3 s). It loads exception tables for nine packs; that could be moved server-side later.

## 8. Tests, guard test and file changes

### Test results

| Suite | Result |
|---|---|
| Python, full (`uc042_test`) | **626 run: 624 passed, 1 skipped** (opt-in live AI), **1 failed**: the `uc042lib/final_pack` guard digest (below, deliberate). Baseline was 605 run, all OK; the 21 new tests are all included. |
| New `tests/test_phase8.py` | 21 tests, all pass on file/SQLite **and** PostgreSQL (`UC042_TEST_REPOSITORIES=postgres`), including the trigger test |
| Frontend vitest | **49 passed, 2 skipped** (40 existing + 9 new in `phase8.test.tsx`) |
| Build (`tsc --noEmit` + Vite) | OK |
| `check_contract.py` | OK, **48 interfaces** (was 37) |

### Changes to existing tests (intent unchanged)

- AI-starting requests carry `authorization: AI_OK`.
- The navigation and review UI tests press "Open a new final review" and confirm the AI dialogs.
- Two `test_unification` reassessment tests asserted the old behaviour that Part D replaces. They now assert:
  - that February is reassessed from verified originals, the history is unchanged and lineage is recorded;
  - that September (no final pack) is refused, and processing a published period gives `REASSESSMENT_REQUIRED`.

No assertion was weakened.

### The guard test left failing (decision needed)

`test_demo_history.Immutability.test_protected_trees_unchanged` pins a digest of `uc042lib/final_pack`.

**Why it changed:** Part D4 required one change in that folder, `publish_final_pack(..., expected=None)`. Its default is the previous per-pack rule, and assembly, rendering, validation and verification are untouched. Existing final packs still verify byte for byte: February `FAP-H202602-…-v1` verifies, and the golden tests pass.

**The pin was not updated,** because it guards that library against unreviewed change. Choose one:

1. **Accept the change:** re-pin the digest to the new value (`1a63…f107`, 12 files). This is a one-line test change, which I will make on your word.
2. **Reject it:** revert the parameter. Reassessed packs would then start again at v1, unlinked, or the application would need its own copy of the publication step (not recommended).

### Files

**New:**
- `uc042app/db/migrations/versions/0004_ai_authorization_and_lineage.py`
- `uc042app/services/ai_authorization.py`
- `tests/test_phase8.py`
- `frontend/src/components/ai/AiAuthorizationDialog.tsx`
- `frontend/src/components/report/Reassessment.tsx`
- `frontend/src/pages/CasePages.tsx`
- `frontend/src/pages/InvestigationPage.tsx`
- `frontend/src/test/phase8.test.tsx`
- this report
- `20B_RECONCILIATION_CALCULATIONS.md`
- `20_phase8_screenshots/` (15 PNG)

**Changed:**
- `uc042app`: `ids`; `db/models`, `db/repositories`; `repositories/base`, `repositories/files`; `services/__init__`, `cases`, `final_packs`, `investigations`, `monthly`, `packs`, `reviews`; `api/schemas`; `api/routers/cases`, `final_packs`, `investigations`, `monthly`, `packs`, `reviews`.
- `uc042lib/final_pack/persistence.py` (one optional parameter).
- `frontend/src`: `App`, `api/endpoints`, `api/types`, `components/workspace/AiPanel`, `data/DataSource`, `data/apiSource`, `data/mock/MockDataSource`; pages `Archive`, `Dashboard`, `FinalPack`, `Report`, `Review`, `Workspace`; tests `api.live`, `screens`, `support`.
- `tests/`: `api_support`, `test_api_jobs`, `test_api_monthly`, `test_api_reviews`, `test_unification`.
- `docs/audit_pack/19_COMPLETE_UI_…AUDIT.md`: path corruption fixed; L-16 corrected.

**Protected material.** All **827** protected artefact files were re-verified byte-identical at the end (§9). Nothing under `packs/`, `investigations/`, `uc042_dataset/`, `demo_history/` or `UC042_JAN_AUG_HISTORICAL_DEMO/` changed. No `uc042/app_state`, `final_packs` or `document_store` was created.

## 9. Environment, data and what you need to do

### Live `uc042` (untouched in Phase 8)

- **Schema:** still at `0003`. Nothing was written to it.
- **Backup taken:** a `pg_dump` at 17:36 IST, `%USERPROFILE%\uc042_phase8\uc042_before_phase8_perf_copy.dump` (sha256 `df649c39…`).
- **Your live backend (port 8000) still runs the pre-Phase 8 code.** A restart with the new code will refuse to start until the database is migrated (`check_schema`). To deploy, from `uc042/`:

  ```powershell
  # 1. stop the running backend (Ctrl+C in its window)
  # 2. migrate (adds two tables and a trigger; nothing existing is changed)
  $env:UC042_APP_STATE_DIR  = "$env:USERPROFILE/uc042_runtime/app_state"
  $env:UC042_DOCUMENT_STORE = "$env:USERPROFILE/uc042_runtime/document_store"
  .\.venv\Scripts\python.exe -m uc042app.admin db-upgrade
  # 3. start it again
  .\.venv\Scripts\python.exe -m uc042app --port 8000
  ```

  The downgrade refuses while the new tables hold data. Rollback is the dump above.

### Disposable resources used

| Resource | Used for |
|---|---|
| `uc042_test` | the project's test database |
| `uc042_audit19` | migrated to 0004; browser verification, with OpenAI disabled |
| `uc042_phase8_perf` | new restored copy for timings |

`uc042_audit19_test` and `uc042_e2e_rehearsal` were not used. The isolated servers (8019/5179 and 8020/5180) can be stopped, and the two disposable databases dropped, at any time.

### Unchanged by instruction

- review session `RS-fc0a6e7f8aa4512c18b9a891` (OPEN);
- the June discrepancy;
- the September artefacts;
- the zero-balance rule;
- the reconciliation rules.

## 10. Continuation: Parts I.4–M (4 November 2026, 17:50–19:00 IST)

This section covers the continuation brief, "Complete the Remaining Scope (Part I.4 onwards)". That brief was itself truncated, inside Part M at the report's file name. Its instruction to update this report is what this section does.

**Code state.** Snapshot taken at 17:51. No other session was active. The continuation changed 13 files:

- **Frontend:** `api/endpoints`, `api/types`, `components/workspace/evidence`, `data/DataSource`, `data/apiSource`, `data/mock/MockDataSource`, pages `Report` and `Workspace`, tests `phase8` and `screens`.
- **Tests:** `tests/test_phase8`, `tests/test_unification`.
- **Backend:** `uc042app/api/routers/monthly`.

### 10.1 I.4 Source evidence without AI (completed)

**The workspace always shows "Supporting evidence · engine retrieval (no AI)".** These are the exception's bank, cashbook, settlement and reconciliation records, retrieved by the approved deterministic retrieval over the pack's hash-verified source files. This now applies whether or not an investigation is selected.

**AI-retrieved records are kept apart.** Records that a selected AI investigation added with its tool calls appear in their own panel, "Records retrieved by the AI investigation's tool calls". That panel says they are source records the AI looked at, **not AI findings**.

**Every record carries an origin badge** (Engine / AI tool), taken from its recorded `retrieved_via` value. Clicking a record opens the provenance inspector, which shows:
- origin;
- source file and line;
- file SHA-256, evidence type and record type;
- how it was retrieved, and the join key;
- every field.

**Only verified joins are drawn as relationships.** Unverified candidate relationships are never shown as links.

**Tests:**
- **Backend:** every engine record is under `source_data/` or `supporting_documents/` of the same pack. Its `file_sha256` equals the pack's registered hash, it has a line reference, and it was never fetched by an AI tool.
- **Frontend:** engine and AI-tool records appear in separate panels with the right labels. The inspector shows the file, SHA-256 and origin.

### 10.2 I.5 PDF preview (investigated; no defect, nothing changed)

**Headers** (live backend, read-only): `Content-Type: application/pdf` and `Content-Disposition: inline; filename="FAP-….pdf"`, with ETag and CORS for the app origin. The bytes are **identical** to the published `report.pdf` (`f5be438d…`).

**Normal (headful) Microsoft Edge, driven over DevTools, on the live February final-pack page:**
- `navigator.pdfViewerEnabled` is true, and the frame uses a typed `blob:` URL;
- **the inline viewer renders all 24 pages**;
- a real click on "Open the PDF in a new tab" opens the PDF (`document.contentType` is `application/pdf`);
- **"Download PDF" saves a file byte-identical to the published PDF.**

**Conclusion:** the original blank preview was a **headless-browser limitation**, not a user-facing defect. The existing fallback links stay in place, and no code or PDF was changed. One observation: a script-triggered click on "Open in a new tab" is blocked as a popup, while a user's click is not.

Screenshots: `20_phase8_screenshots/I5_headful_edge_inline_pdf.png` and `…_new_tab_pdf.png`.

### 10.3 I.6 Earlier UI corrections (reviewed; correct, not redone)

These were all checked and are correct:
- period-aware titles and labels;
- historical and demonstration pack labels;
- the environment tooltip (fixed at 15:28 by the other session);
- readable activity descriptions;
- dashboard counts;
- PDF behaviour (§10.2).

The only change is the workspace inspector label, which now names the record's origin. One existing screen-test assertion was updated to match.

### 10.4 Part J — calculation reference (verified and extended in place)

**`20B_RECONCILIATION_CALCULATIONS.md`** was verified against the code first, then extended in the same file; no duplicate was created. It now runs to about 19,000 words and opens with a verification record. It contains:
- **Controls:** all **36 engine check IDs**, each with the 16 requested items: purpose, question answered, inputs, columns, joins, grouping, formula, tolerances, dates and timezone, missing-evidence behaviour, output, outcome conditions, exceptions, tests and limitations. Each also has a plain-language explanation.
- **Structure:** internal and external reconciliation in separate parts.
- **Topic explanations:** opening and closing balances, daily movements, cashbook-to-bank, settlements, transactions and refunds, unallocated balances, missing statements, currency isolation, continuity and policy effective dates.
- **Worked examples:** February EXC-H202602-01, September S05, SC2 and SC5C, with a map from each scenario to its exceptions (all labelled synthetic).
- **"From the screen to the calculation":** the path from frontend action to API route, backend service, Python function, database record or file, and the result the user sees.

**Corrections made to the earlier text:**
- continuity covers 144 items across 8 month boundaries, not 36;
- several line references;
- the C11 bank-matching key and C09's in-period condition;
- V00 never passes;
- the internal-difference grouping;
- **the "no thresholds" claim is refined.** There is no monetary tolerance anywhere, but there are **hardcoded time limits** in `validate.py`: a one-business-day timing window (lines 105–107), next-business-day allocation, a one-day settlement allowance (informational), same-day top-ups, and a 15th-business-day return deadline (line 1157). These are now in one table, §A.6.

**Spot-checked independently:** lines 105–107, 739 and 1157 match the code.

**Gaps it reports:**
- registry code C02 is named but no check produces it;
- several controls' failure paths are covered only by whole-dataset golden or answer-key tests;
- the engine assumes one safeguarding account per currency.

### 10.5 Part K — testing and verification

**`test_unification` portability.** The migration test now takes the target database name from `UC042_TEST_DATABASE_URL` (`TARGET_DB`). The assertion remains exact, and it passes on `uc042_test` **and** `uc042_audit19_test`.

**Performance (one more change).** A month report used to fetch exceptions and investigations per pack. A new read-only `GET /periods/{id}/exception-overview` returns them for all packs in one response, using `PackService.peek`. It has a test, and the mock source supports it.

Measured from a **cold backend start**, with no prior requests, on the restored `uc042` copy:

| Page | First load | Repeat |
|---|---|---|
| Archive | 1.18 s | 0.42 s |
| Dashboard, Feb / Sep | 0.75 / 0.87 s | 0.44 / 0.75 s |
| Report, Feb / Sep / Jun | 0.67 / **1.51** / 0.64 s | 0.73 / 1.07 / 0.54 s |
| Exception workspace, Feb / SC2 | 1.29 / 1.07 s | 1.08 / 1.18 s |

The September report was 3.06 s before the overview call.

**Regression checks:**

| Check | Result |
|---|---|
| `tools/verify_demo_history.py` | all **8 historical packs OK**; expected = actual exceptions for every month; continuity MATCH for all 8 boundaries |
| September packs (library `load_pack`) | **9/9 verify** |
| February final pack (`verify_final_pack`) | no problems; the served PDF is byte-identical |
| Registered investigations | February and June artefacts verify (`verify_published`); `verify-registry`: 2 entries, all verified, with their authorisation states |
| Pack references | 26 references, 0 problems (25 earlier, plus the audit's review session) |
| Protected artefacts | **827/827 byte-identical** |

**Suites:**

| Suite | Result |
|---|---|
| Python, full | **627 run: 625 passed, 1 skipped** (opt-in live AI), **1 failed**: the reserved final-pack library guard |
| Frontend vitest | **50 passed, 2 skipped** |
| Build | OK |
| Contract check | OK |

**Areas covered** (Phase 8 tests plus the browser runs in §4): review safety, AI authorisation, reassessment, cases and investigations, the June and September protections, dashboard counts and labels.

**Guard test.** The final-pack library fingerprint guard was **not** re-pinned or bypassed. It remains the one deliberate failure, pending your decision.

### 10.6 Part L — decisions reserved for the business owner (state verified read-only; nothing changed)

| # | Item | Current state (verified 4 Nov 2026, 18:5x) | Options and consequences |
|---|---|---|---|
| 1 | **June investigation** `INV-EXC-H202606-01-c7b353b53fb3` | Artefact verifies. Registry seq 2. Authorisation **AUTHORIZATION_DISCREPANCY**. Excluded from eligibility; shown "+1 excluded". | (a) **Keep as is**: no effect. (b) **Approve**: append an APPROVED decision (`record-investigation-authorization`), after which it becomes eligible for a June final pack. The discrepancy stays in the append-only history. (c) **Archive**: move it to an explicitly unapproved location. Its registry entry would then fail verification unless a supersession procedure is defined first; not recommended without one. |
| 2 | **Seven September POC artefacts** | Unregistered and ineligible. Three also fail the current findings-1.4 rule (C-01). | (a) **Keep**: September stays at "Deterministic pack available". (b) **Register those that pass the current rules** (four of seven by the audit's eligibility view; to be confirmed with `import-legacy-investigations --dry-run`) (`import-legacy-investigations`, LEGACY_BASELINE_IMPORT): they become eligible for September reviews. (c) **Re-run** under current rules: this needs AI authorisation and costs tokens. The three failing artefacts cannot become eligible without a re-run. |
| 3 | **Retired legacy database** `uc042_history_retired_20261104` | Exists; `default_transaction_read_only=on`; 0 connections; Alembic `0002`; 9 periods, 8 pack references, 2 registry entries, 1 final-pack record; 8.9 MB. | (a) **Keep**: no cost beyond the space. (b) **Drop**: irreversible except from the dumps in `uc042/db_backups/`. Every row is in `uc042` with provenance. Recommended only after acceptance. |
| 4 | **E2E rehearsal** database `uc042_e2e_rehearsal` and folder `%USERPROFILE%/uc042_e2e` | Database at `0003`: 18 pack references, 3 registry entries, 2 final-pack records, 28 documents; 9.8 MB. Folder: 42 MB (roots, document store, final packs, logs). | (a) **Keep** as evidence for report 19 §13. (b) **Delete both** once report 19's evidence is no longer needed: no effect on `uc042`. |

Also present, all disposable (mine): `uc042_audit19`, `uc042_audit19_test`, `uc042_phase8_perf`, and the folders `%USERPROFILE%/uc042_a19` and `%USERPROFILE%/uc042_phase8`. They are safe to drop.

## 11. Open points

1. **Guard digest:** decide whether to re-pin (§8).
2. **Live migration and restart** (§9).
3. **Part L decisions** (§10.6).
4. **The continuation brief was truncated** inside Part M. Anything specified after "Update the existing implementation report" was not seen.
5. **Possible follow-ups (not done):**
   - targeted failure-path tests for C01-COVER, C07-COVER, BC-VS-EOD, C11-TXN-LINE, C13-CURRENCY and C10-DESIGNATION (20B, limitations);
   - a close action for unwanted OPEN review sessions;
   - support for more than one safeguarding account per currency, if that will ever arise.
