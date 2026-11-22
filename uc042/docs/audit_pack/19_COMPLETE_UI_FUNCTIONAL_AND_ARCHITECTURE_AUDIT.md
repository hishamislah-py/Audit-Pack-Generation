# 19 — UC-042 UI, Functional and Architecture Audit

ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

**Audit date:** 4 November 2026. Code inspected 15:24–15:57 IST; isolated tests run until about 16:05 IST.

**Type:** read-only inspection plus functional verification. No application source file was edited. No live AI call was made. Nothing published or protected was modified.

**Numbering note:** this report shares the number 19 with `19_DATABASE_UNIFICATION_AND_FUNCTIONAL_GAP_CLOSURE_IMPLEMENTATION_REPORT.md`. The file name was set by the brief. The screenshots are in `19_audit_screenshots/`.

---

## 0. Audit conditions (read first)

### 0.1 The application changed while it was being audited

Another Claude Code session was implementing changes in the same working tree during this audit. Code state was recorded with SHA-256 hashes of every file under `uc042app`, `uc042lib`, `frontend/src`, `tests`, `tools` and `docs` (236 files):

| Time (IST) | Event |
|---|---|
| 14:57 | Live backend (port 8000, database `uc042`) running. Started before the audit. |
| 15:22–15:23 | `tests/test_monthly_reports.py` and `uc042app/services/monthly.py` modified (before the baseline). |
| **15:24:34** | **Baseline snapshot taken.** |
| 15:25 | `tests/test_demo_history.py` modified. |
| 15:28 | `frontend/src/components/layout/AppShell.tsx` modified. The topbar tooltip no longer says "environments are not combined", a finding of this audit fixed in parallel. |
| 15:38 | `uc042app/api/routers/monthly.py` modified (period-list performance: pack objects passed through). |
| 15:39 | `uc042app/services/investigations.py` and `tests/test_unification.py` modified. |
| **15:39:29** | **The other session restarted the live backend** (new process). Requests in flight failed: `/periods` hung for 142 s, then the connection was refused. This audit did not cause it. |
| **15:56:59** | **End snapshot.** The same 5 files differ from the baseline. Nothing changed after 15:39. |

**What this means for the findings:**

- Live screens and timings were taken after the 15:39 restart, so they reflect the code as of 15:39.
- The isolated test backend started at 15:30. It therefore ran the 15:24 versions of `monthly.py`, `routers/monthly.py` and `investigations.py`, not the later ones.

**Classification used throughout:**

| Code | Meaning |
|---|---|
| **IMPL** | Implemented and verified by this audit |
| **MOD** | Being modified during the audit |
| **NOT** | Not implemented |
| **UNTESTED** | Could not be or was not tested; the reason is stated |

### 0.2 The brief's database assumption is out of date

The brief refers to a "separate-database architecture" and says "do not merge `uc042` and `uc042_history`".

**That merge already happened in report 19**, migration `UNIFY-20261104T081343Z-a3fa26b5`. A second catch-up run, `UNIFY-20261104T092615Z-6c31a186`, followed at 14:56. The live backend serves all nine periods (January to September) from one database `uc042` (Alembic `0003_unified_schemas`), with storage profiles `primary` and `historical-demo`.

This audit did not merge, change or touch either database's data. Read-only observations on the server:

- `uc042_history` **still exists**. It has not been renamed and has no read-only setting, so report 19's retirement step (§4 step 6) is still pending.
- A database `uc042_e2e_rehearsal` exists and is not documented in reports 17–19. It probably belongs to the other session. It was left alone.
- The category "blocked by the separate-database architecture" therefore no longer applies to any action. What remains is the legacy-database retirement.

### 0.3 How each kind of test was done safely

| Kind of test | Where it ran | Safeguards |
|---|---|---|
| Read-only UI inspection | Live app: Vite `127.0.0.1:5173` → backend `:8000` → `uc042` | GET-only pages. Not opened: `/packs/:id/review` (it writes; see L-1), "Run investigation", "Generate preview", HOLD/GENERATE. The 16 `audit`/`operations` row counts were captured before and after each of three capture runs: **identical every time**. |
| Write workflows | **Isolated instance**: backend `127.0.0.1:8019`, frontend `127.0.0.1:5179`, new database **`uc042_audit19`** (created and migrated for this audit), all roots under `%USERPROFILE%\uc042_a19\` | Copies of the February pack, investigations and final pack, plus the January, February and March datasets as upload sources. `OPENAI_API_KEY=""`: `/health` reported `provider_configured: false`, so no code path could reach OpenAI. The scratchpad path was too long for Windows (260-character limit) for nested investigation folders, so the isolated root sits at the short path above. |
| AI pipeline | Code and February artefacts only | No investigation or closing summary was run. |

**Protected material at the end of the audit:**

- The 61 February files copied for testing (`demo_history` pack, investigations, final pack and the January/February datasets) were re-hashed against the originals: **byte-identical**.
- `packs/`, `investigations/`, `demo_history/`, `UC042_JAN_AUG_HISTORICAL_DEMO/` and `uc042_dataset/` have no file modified after 15:24.
- No `uc042/app_state`, `uc042/final_packs` or `uc042/document_store` was created.

**Test suites:** not run in the first pass, because `uc042_test` was shared with the concurrent session. In the follow-up (§P) they were run against a separate database, `uc042_audit19_test`.

---

## A. Application overview

UC-042 is a **local, single-analyst** proof of concept for monthly safeguarding-reconciliation audit packs for an e-money institution. It uses synthetic data only.

**What it does:**

1. A month's financial evidence is uploaded: 19 contract inputs IN-01..IN-19, of which 14 are CSV and 5 are PDF.
2. Each file is identified by content and validated.
3. A **deterministic engine** reconciles the month (internal, per currency and day; external, per account and day; plus about 20 controls) and publishes an **immutable deterministic pack** containing an exception register.
4. An analyst may ask an **AI (OpenAI `gpt-6-luna`, tools mode)** to investigate one exception. The AI reads only approved, hash-verified records and is validated against strict citation and wording rules.
5. In a **final review** the analyst chooses which investigations to include. The backend generates an **AI closing summary** and a preview, and the analyst records HOLD or GENERATE.
6. GENERATE assembles, renders (JSON, HTML, PDF) and publishes an **immutable, versioned final audit pack**.

**Exceptions are never resolved by the application.** Every exception stays UNRESOLVED in every artefact, and the AI is an aid to human review.

**Stack:**

- React 19 + TypeScript + Vite frontend.
- FastAPI backend `uc042app`, bound to 127.0.0.1, with no authentication.
- Python library `uc042lib` (engine, packs, AI investigation, final pack).
- PostgreSQL 18 on port 5433, database `uc042`.
- Write-once artefact folders on disk.
- OpenAI Responses API.

**Current data in the live database `uc042`** (read 15:3x):

| Period | Title (source) | Profile | Packs | Exceptions | Investigations: published / excluded | Final pack | Reporting status |
|---|---|---|---|---|---|---|---|
| PER-2026-01 | January 2026 Reconciliation Audit (derived) | historical-demo | 1 | 0 | 0 / 0 | — | Deterministic pack available |
| PER-2026-02 | February … (derived) | historical-demo | 1 | 1 | **1 / 1** | **FAP-H202602-PER-2026-02-v1-b8dd53bd2449** | **Final audit pack published** |
| PER-2026-03 | March … | historical-demo | 1 | 3 | 0 / 0 | — | Deterministic pack available |
| PER-2026-04 | April … | historical-demo | 1 | 0 | 0 / 0 | — | Deterministic pack available |
| PER-2026-05 | May … | historical-demo | 1 | 4 | 0 / 0 | — | Deterministic pack available |
| PER-2026-06 | June … | historical-demo | 1 | 4 | 0 / **1** (authorisation discrepancy) | — | Deterministic pack available |
| PER-2026-07 | July … | historical-demo | 1 | 5 | 0 / 0 | — | Deterministic pack available |
| PER-2026-08 | August … | historical-demo | 1 | 8 | 0 / 0 | — | Deterministic pack available |
| PER-2026-09 | September 2026 Reconciliation Audit (stored) | primary | **9 scenarios** | 30 | 0 / **7** (unregistered POC artefacts) | — | Deterministic pack available |

**Database row counts:**

- `audit`: 17 period-pack references, 2 registry entries, 2 authorisations, 1 review session, 1 decision, 1 preview, 1 final-pack record, 37 provenance rows.
- `operations`: 4 jobs, 14 activity events, **0 upload batches, 0 source documents, 0 processing runs, 0 cases.**

No month in the live database has ever been processed from uploaded documents. Every live pack was registered from dataset folders.

---

## B. Complete UI screen inventory

**Global shell** (`components/layout/AppShell.tsx`, `workContext.tsx`), present on every screen:

**Sidebar "Workflow":**

| Item | Target |
|---|---|
| 01 Dashboard | `/` |
| R Monthly reports | `/reports` |
| 02 Reconciliation pack | the open pack; otherwise `/reports/<month>#reconciliation` |
| 03 Exceptions & investigation | the pack's workspace; otherwise `#exceptions` |
| 04 Final review | the open review; otherwise `/packs/<pack>/review`, which **writes** (see L-1); otherwise `/reviews` |
| 05 Final audit pack | the open final pack, or `/final-packs` |

**Sidebar "Records":** All reviews, All final packs, Upload documents. A "Current pack" box appears when a pack is open.

**Topbar:**

- **Period selector**, which navigates to `/reports/<id>`. Options are built from `GET /periods` and `GET /packs`, plus every month of the current year.
- **Environment tag** from `GET /health`.
- **"Live backend" / "Backend unreachable" badge.**
- "SYNTHETIC DATA" badge and the analyst ID.

**Breadcrumbs** are set by each page.

**Routes** (`App.tsx`). All data comes through `DataSource` → `apiSource.ts` → `api/endpoints.ts` → `fetch`, with base URL `VITE_API_BASE_URL` (default `http://127.0.0.1:8000`).

| # | Route | Screen | Business purpose | Data shown (source) | Controls → effect (endpoint) | Writes? | Screenshot |
|---|---|---|---|---|---|---|---|
| 1 | `/` | **Dashboard** (`DashboardPage`) | Monthly overview and entry point | KPI tiles (packs, exceptions, AI investigations, pending reviews, final packs); period table (status, documents, validation, processing, packs, exceptions, unresolved, AI coverage, final pack); recent final packs; pending reviews; recent activity. Sources: `GET /periods`, `/packs`, `/final-packs`, `/reviews`, `/activity`, and `GET /packs/{id}/investigations` per pack | Row click selects the month (`?period=`). "Upload documents for <month>" → `/upload?period=`. "Open <month> packs" → first pack. Pack row → `/packs/{id}`. "Open <month> for upload" (empty month) → `POST /periods` then `/upload`. Activity links. | Only "Open … for upload" | L01, L02 |
| 2 | `/reports` | **Monthly reports archive** (`ReportsPage`) | One row per month: lifecycle status | Month, title, period ID, documents, pack types, exceptions, investigations ("+N excluded"), final pack, reporting status. Source: `GET /periods` + `/packs` + `/final-packs`; environment note from `/health` | Search (title/ID), Year, Month, Reporting status, Final audit pack, Sort. All are kept in the URL; client-side filtering. Row/link → `/reports/{id}`. "Add New Monthly Report" → `/reports/new` | No | L03, L04, L05 |
| 3 | `/reports/new` | **Add new monthly report** (`NewReportPage`) | Create a reporting period | Month, Year, Title (default "<Month YYYY> Reconciliation Audit"), derived period ID; duplicate, future-month and title checks (client-side, from `GET /periods`) | "Create and continue to upload" → `POST /periods {year, month, title}` → `/upload?period=…&new=1`. Disabled for an existing, future or invalid month | Yes: `audit.reconciliation_periods`, activity `PERIOD_OPENED` | L20 (duplicate), I17 (future), I18 |
| 4 | `/reports/:periodId` | **Monthly report workspace** (`ReportPage`) | Everything about one month | 1 Overview (title, status, KPIs, Change title, pending-reassessment notice, environment); 2 Source documents + "Add Supporting Document" form; 3 Reconciliation results (packs); 4 Exceptions; 5 AI investigations (with eligibility); 6 Closing summary (from the latest final pack's JSON); 7 Published audit packs with JSON/HTML/PDF links; 8 Document history and processing runs. Sources: `GET /periods/{id}`, `/periods`, `/packs`, `/final-packs`, `/packs/{id}/exceptions`, `/packs/{id}/investigations`, `/final-packs/{id}/json` | "Upload documents" → `/upload?period=`. "Add Supporting Document" scrolls to the form. "Change title" → `PATCH /periods/{id}`. Supporting-document form → `POST /periods/{id}/uploads` (kind ADDITIONAL_EVIDENCE or CORRECTION, reason, replaces) → `/uploads/{batch}`. Pack row: "Workspace" (read-only), **"Final review" → `/packs/{id}/review` (writes, L-1)**. Exception and investigation links → workspace. Downloads open `GET /final-packs/{id}/{json\|html\|pdf}` in a new tab | Title change, uploads | L06 (Feb), L07 (Sep), I10 (Feb, isolated) |
| 5 | `/periods/:id` | Redirect | Old URL | — | → `/reports/:id` (verified) | No | — |
| 6 | `/upload` | **Upload financial documents** (`UploadPage → RealUpload`) | Send a batch for validation | Month selector (current year plus archive); existing-documents, scenario-pack and published-pack notices; submission type (Source / Additional evidence / Correction); Replaces selector; reason; drop zone; expected IN-01..IN-19 checklist (static) | "Upload and validate" → `POST /periods` if the month has no record, then `POST /periods/{id}/uploads` (multipart) → `/uploads/{batch}`. "Clear", "Remove". Disabled until files, reason and replaces are complete | Yes: batch and documents, original files in the document store | L21, I01, I16 |
| 7 | `/uploads/:batchId` | **Upload batch** (`BatchPage`) | Review validation, decide flagged files, confirm, process | Batch status and validation; Valid/Warnings/Errors; missing required/optional evidence; documents (evidence ID, records, governing dates, flags, decision, "Checks" detail with messages, dates table, SHA-256, download link); processing runs. Sources: `GET /uploads/{id}`, `/periods/{id}`, `/jobs/{id}` (poll) | "Checks" toggles detail. **Include / Exclude** (comment ≥ 3) → `POST /documents/{id}/review`. **Confirm batch** → `POST /uploads/{id}/confirm` (disabled while decisions are pending or the batch is INVALID). **Start processing / Start a new processing run** → `POST /uploads/{id}/process`, then poll; disabled while required evidence is missing. "Download the stored original" → `GET /documents/{id}/content` | Yes | I02, I20, I22, I08, I09, I11, I12 |
| 8 | `/packs/:packId` | **Deterministic pack** (`PackDetailPage`) | Read the engine's results | KPIs (period, currencies, accounts, engine status, evidence, exceptions, content hash); accounts; source-file inventory (SHA-256); reconciliation tabs (External / Internal / Differences); exception register with AI status. Sources: `GET /packs/{id}`, `/reconciliation`, `/sources`, `/exceptions`, `/investigations` | Tabs (URL `?recon=`). "Investigate exceptions" → workspace. **"Open final review" → `/packs/{id}/review` (writes)**. "Add documents for a new period" → `/upload` | No (the link does) | L09 |
| 9 | `/packs/:packId/workspace[/:exc]` | **Exception & investigation workspace** (`WorkspacePage`, `AiPanel`) | Investigate one exception | Exception list; KPIs (amount, date, severity, evidence status, deterministic status); engine results behind the exception; **supporting evidence records** and relationships (shown only from an investigation's ledger); AI panel: investigation selector, tabs Summary / Observations / Hypotheses / Gaps & conflicts / Next steps, eligibility, model, validation, registry; citation inspector. Sources: `GET /packs/{id}/exceptions`, `/packs/{id}/investigations`, `/packs/{id}/exceptions/{exc}`, `/investigations/{id}`, `/findings`, `/evidence?limit=200`, `/packs/{id}` | Exception buttons switch the exception. Citation chips highlight records. Tabs (`?tab=`), investigation selector (`?inv=`). **"Run investigation" / "Retry investigation" → `POST /packs/{id}/exceptions/{exc}/investigations {mode: tools}`, then poll `GET /jobs/{id}`. It is a live, paid OpenAI call with no confirmation dialog.** "Continue to final review" → writes (L-1) | "Run investigation" | L10, L11, L12, I15 |
| 10 | `/packs/:p/exceptions/:e` | Redirect | Old URL | — | → workspace | No | — |
| 11 | `/packs/:packId/review` | **Open review** (`OpenReviewPage`) | Get or create the review session | Spinner | **On load: `POST /packs/{id}/reviews`.** Returns the active session, or **creates a new one if the last is GENERATED** → `/reviews/{id}` | **Yes, on navigation** | — (not opened live) |
| 12 | `/reviews` | **All reviews** | List sessions | Review, pack, status, preview, last decision, final pack, updated. Source: `GET /reviews` | Links | No | — |
| 13 | `/reviews/:reviewId` | **Final review** (`ReviewPage`) | Read the preview, choose investigations, decide | Status notices; section navigation; document viewer (HTML / PDF / JSON preview); pack summary and report facts; readiness (blockers, warnings, info); selections; decision panel (note, acknowledgement checkbox(es), HOLD, GENERATE with confirmation modals); decision history. Sources: `GET /reviews/{id}`, `/reviews/{id}/preview/{html\|pdf\|json}?snapshot=`, `/history`, `/packs/{id}/exceptions`, `/packs/{id}/investigations` | **"Generate closing summary and preview" / "Regenerate preview" → `POST /reviews/{id}/preview` (background job; live OpenAI closing-summary call).** "Edit" selections → modal → `PATCH /reviews/{id}/selections`. HOLD (comment required) → `POST /reviews/{id}/decision`. GENERATE (acknowledgement; plus the summary-unavailable acknowledgement where it applies) → `POST /reviews/{id}/decision` → `/final-packs/{id}`. All editable controls are hidden for GENERATED sessions | Yes | L13 (Feb GENERATED, live), I13, I19 |
| 14 | `/final-packs` | **All final packs** | List published packs | ID, source pack, version, supersedes, generated, hash. Source: `GET /final-packs` | Links | No | — |
| 15 | `/final-packs/:id` | **Published final audit pack** (`FinalPackPage`) | Read and download the immutable pack | Integrity status (`GET /final-packs/{id}/verify`); pack record (versions, references, reviewer, note); artefact table (PDF/HTML/JSON with SHA-256); tabs PDF preview (blob iframe plus "Open in a new tab" / "Download PDF" fallback), HTML report (sandboxed), Canonical JSON, Version history | Open / Download per format → `GET /final-packs/{id}/{kind}`. Tabs (`?view=`) | No | L15 (PDF), L16 (HTML), I14 |
| 16 | `/investigations/:id` | Placeholder | Old investigation links | Text naming the exception | Link to the dashboard only. It does not open the investigation (UI-only stub) | No | — |
| 17 | `*` | Page not found | — | — | Back to the dashboard | No | — |

**Not in the UI at all:** exception investigation **cases** (`/cases*`) and **explicit reconciliation / reassessment** (`POST /periods/{id}/reconciliation`). See L-2 and L-3.

---

## C. Complete user workflow

```
 ┌──────────── PRELOADED (registered from dataset folders at start-up; no documents in the DB) ─────────────┐
 │ Jan–Aug: 8 historical packs (demo_history/packs)   Sep: 9 scenario packs (packs/)   Feb: 1 investigation  │
 │ + 1 final pack (demo_history)                                                                              │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 NEW MONTH ─► (1) Create period ─► (2) Upload ─► (3) Validate (automatic on upload) ─► Decide flagged ─► Confirm
   POST /periods     POST /periods/{id}/uploads     identification, dates,          POST /documents/  POST /uploads/
   [UI]              [UI] originals → document store duplicates, missing           {id}/review       {id}/confirm
                                                                                    [UI]              [UI]
 ─► (4) Reconcile = deterministic engine ─► (5) Deterministic pack (immutable, packs/) ─────────────┐
   POST /uploads/{id}/process [UI]            exception register, all OPEN / UNRESOLVED              │
   POST /periods/{id}/reconciliation [API only; also REASSESSMENT]                                   │
                                                          zero exceptions ──────────────────────────►│
 ─► (6) Investigate exception  ═══ AI BOUNDARY ═══  POST …/exceptions/{e}/investigations [UI]         │
        (optional, per exception, explicit)          POST /cases/{id}/ai-investigation [API only]     │
        evidence packet → OpenAI tools loop → deterministic validation → write-once artefact          │
        → publication registry (DB) → eligibility (registry + authorisation + current rules)          │
 ─► (7) Final review  POST /packs/{p}/reviews  [UI: on navigation]  ◄──────────────────────────────────┘
        selections per exception: INCLUDED (eligible investigation) | NOT_INVESTIGATED | EXCLUDED_BY_ANALYST
 ─► (8) Closing summary + preview  POST /reviews/{id}/preview  ═══ AI (one call) ═══ or UNAVAILABLE
 ─► (9) Human review: HOLD (note) | GENERATE (acknowledgement [+ summary-unavailable acknowledgement])
 ─► (10) Assemble → render JSON/HTML/PDF → publish write-once → verify   (deterministic, no AI)
 ─► (11) Published final audit pack  final_packs/FAP-…-v<n>-<hash>   GET /final-packs/{id}/{json|html|pdf}
```

**What happens at each stage:**

1. **Create or select the period.** Done from `/reports/new`, the topbar selector, or implicitly when uploading to a month that has no record. The period ID is `PER-YYYY-MM` and never changes. A duplicate request returns the existing period (HTTP 200, title unchanged). Future months are refused.
2. **Upload.** Each file is first stored write-once, addressed by its content hash, in `UC042_DOCUMENT_STORE/objects/<sha[:2]>/<sha>`. Its metadata then goes into `operations.source_documents`. Nothing is lost even if the file is rejected.
3. **Validate.** This runs during the upload request (`ingest/analysis.py`):
   - CSVs are identified by exact header; PDFs by their key details.
   - The dates that govern the month are checked: `WRONG_PERIOD`, `OUT_OF_PERIOD_RECORDS`, `TIMING_DIFFERENCE`.
   - Duplicates are flagged and never removed: `DUPLICATE_IN_BATCH`, `DUPLICATE_OF_EARLIER_UPLOAD`, `SAME_NAME_DIFFERENT_CONTENT`, `SAME_CONTENT_AS_OTHER_PERIOD`.
   - Missing required inputs are listed.

   Flagged files need an Include or Exclude decision with a comment. Confirming fixes the batch. Confirmation is allowed when the batch is INCOMPLETE, but processing is not.
4. **Reconcile.** `prepare_case` materialises the period's *current confirmed set* (the latest usable document per input slot) into `document_store/cases/SET-<hash>`. The engine (`uc042lib/validate.py`, run in a background thread) runs structure checks, the evidence gate, about 20 controls, exception grouping and correlation. Nothing reconciles automatically.
5. **Deterministic pack.** `pack.json`, `pack.html`, processing CSVs and a generation record are written write-once into the primary `packs/`, then registered in `audit.period_packs`. **Identical inputs produce an identical pack.** This audit demonstrated it twice (§K, T4 and I22).
6. **Investigate exceptions** (AI). Optional. One exception at a time, always started by an analyst. See §H.
7. **Final review.** One session per pack at a time. The default selection includes the eligible investigation, if any. Readiness blockers:
   - an investigation running;
   - an ineligible selection;
   - "not investigated" while an eligible investigation exists;
   - preview in progress;
   - preview required.
8. **Closing summary and preview.** A background job builds the snapshot, makes one AI call for the closing summary (or marks it UNAVAILABLE), and assembles a preview with HTML/PDF/JSON views.
9. **Human review.** HOLD records a note and clears the preview. GENERATE requires the same snapshot hash, the acknowledgement, and, if the summary is unavailable, a second acknowledgement.
10. **Assemble and publish** (deterministic). See §I.
11. **Published pack.** Immutable. Integrity re-verified on every view.

**Data in three origins:**

| Origin | Examples | How it enters | In the DB |
|---|---|---|---|
| **Preloaded historical** | Jan–Aug `demo_history/packs`, February investigation and final pack | Built offline (reports 14–17), then registered at start-up by `sync_packs`, or migrated by unification | Period and pack references only. **No source documents**, so "Source documents: 0" for every live month. |
| **September demonstration** | 9 scenario packs SC1…SC5D, 7 POC investigation artefacts | Same | 9 pack references. The investigations are unregistered, so they show as "excluded". |
| **Newly uploaded** | None in the live database; Jan, Mar and Feb were uploaded in the isolated database | Upload → validate → confirm → process | Batches, documents, runs, packs |

**With zero exceptions:**

- The workspace says "No exceptions… nothing to investigate".
- The review has no selections and the information note `NO_EXCEPTIONS`.
- The preview and GENERATE still run; the closing summary is either generated or UNAVAILABLE and must be acknowledged.
- The final pack says the reconciliation is clean.
- Tested end to end with January (isolated, T9): `FAP-CASE-PER-2026-01-v1-ee0b03fcf6cc`, verified.

**With unresolved exceptions** (always the case — the app never resolves one):

- Every exception is carried into the final pack as UNRESOLVED, with severity and the deterministic results.
- An exception with no included investigation is marked NOT_INVESTIGATED and raises a readiness warning.
- The GENERATE dialog states how many exceptions will be reported as UNRESOLVED and that GENERATE resolves nothing.
- A case DECISION (API only) records a human resolution (`EXPLAINED_BY_ANALYST` / `ESCALATED`) on the case. **It does not change the pack, the exception, or any final pack** (tested, T8b).

---

## D. Function-by-function interaction map: what each major user action actually does

| User action (screen) | Endpoint | Backend function | DB effect | File effect | AI? | User sees | Verified |
|---|---|---|---|---|---|---|---|
| Select month (topbar or dashboard) | none (client state) | — | — | — | — | Month's report or dashboard detail | IMPL (live) |
| Filter or search the archive | none (client-side) | — | — | — | — | Filtered rows; URL keeps the filters | IMPL (live, L04/L05) |
| Create monthly report | `POST /periods` | `MonthlyService.create_period` | insert `audit.reconciliation_periods`, activity | — | — | Upload page with "Monthly report created" | IMPL (isolated T1) |
| Duplicate month | `POST /periods` → 200 | same, returns existing | none (title unchanged) | — | — | UI blocks first: "January 2026 already exists" | IMPL (T1, I18) |
| Future month | 422 `FUTURE_PERIOD` | same | none | — | — | UI: "December 2026 has not started yet" | IMPL (T1, I17) |
| Change title | `PATCH /periods/{id}` | `rename_period` | update title, activity `PERIOD_RETITLED` | — | — | New title. Fewer than 3 characters → 422 | IMPL (T1) |
| Upload and validate | `POST /periods/{id}/uploads` | `MonthlyService.upload`, `ingest.analysis`, `DocumentStore.put` | `upload_batches`, `source_documents`, activity | original stored by SHA-256 | — | Batch page with checks | IMPL (T2, I01–I02) |
| Include / Exclude a flagged file | `POST /documents/{id}/review` | `review_document` | decision columns, batch summary, activity | — | — | Decision badge | IMPL (T5, I20) |
| Confirm batch | `POST /uploads/{id}/confirm` | `confirm` | batch CONFIRMED | — | — | Process button appears | IMPL (T4, T5, I21) |
| Start processing | `POST /uploads/{id}/process` | `process` → job → `_process` → `prepare_case`, `pack.generate.build`, `_publish` | `processing_runs`, `jobs`, `period_packs`, statuses, activity | `document_store/cases/SET-…`, `packs/PACK-CASE-…` | — | Run SUCCEEDED and pack link | IMPL (T4, I22) |
| Reconcile / reassess explicitly | `POST /periods/{id}/reconciliation` | `reconcile` → `process` | same plus `purpose`/`reason`, activity `REASSESSMENT_STARTED` | new pack | — | **No UI** | Backend IMPL (T4, T7b, §K-R); UI NOT |
| Add supporting document | `POST /periods/{id}/uploads` (ADDITIONAL_EVIDENCE) | `upload` with `_submission_checks` | documents with `submission_kind`/`reason` | original stored | — | `SUPPORTING_EVIDENCE` warning; period "Additional evidence received" | IMPL (T7b, I10) |
| Correction | same (CORRECTION + replaces) | same | `replaces_document_id` link | new object | — | "Correction of DOC-…", earlier version kept | IMPL (T6, I16) |
| Download a stored original | `GET /documents/{id}/content` | `document_content` (hash re-verified) | — | read | — | File download; `X-Content-SHA256` | IMPL (T11) |
| Open pack / tabs | `GET /packs/{id}/…` | `PackService.load` (verified, cached) | — | read | — | Pack screens | IMPL (live L09) |
| Run investigation | `POST /packs/{p}/exceptions/{e}/investigations` | `InvestigationService.start` → `_execute` → `run_investigation(mode=tools)` → registry | `jobs`, `investigation_registry` | `investigations/<pack>/<exc>/INV-…/` or `_not_published/` | **YES** | Job progress, then findings | Refusal path IMPL (I15: `PROVIDER_NOT_CONFIGURED`). **Live path UNTESTED by instruction.** Report 17 ran it once. |
| View investigation | `GET /investigations/{id}`, `/findings`, `/evidence` | `detail`, `findings`, `evidence` | — | read | — | Workspace AI panel | IMPL (live L10–L12) |
| Open final review | `POST /packs/{id}/reviews` | `ReviewService.open` | **new session if none active** | — | — | Review page | IMPL (T9, T10). Live not opened (L-1). |
| Edit selections | `PATCH /reviews/{id}/selections` | `set_selections` | session revision; preview cleared | — | — | Updated selections | UNTESTED in UI. Backend tested by report 19's suite. |
| Generate preview | `POST /reviews/{id}/preview` | `request_preview` → `_build_preview` → `generate_closing_summary` → `assemble_preview` | `jobs`, `previews` | — | **YES** (summary) | Preview and readiness | UNAVAILABLE path IMPL (T9). Live summary UNTESTED by instruction. |
| HOLD | `POST /reviews/{id}/decision` | `decide` | decision; ON_HOLD; preview cleared | — | — | "Decision saved: HOLD" | IMPL (T9) |
| GENERATE | same | `decide` → `FinalPackService.generate` → `assemble_final_pack`, `publish_final_pack`, `verify_final_pack` | decision, final-pack record, GENERATED | `final_packs/FAP-…/{final_pack.json, report.html, report.pdf, manifest.json}` | — | Final-pack page | IMPL (T9, §K-R) |
| View or download final pack | `GET /final-packs/{id}`, `/verify`, `/{json\|html\|pdf}` | `FinalPackService` (manifest-verified) | — | read | — | Verified pack; byte-identical downloads | IMPL (live L15–L16; T11 byte-equality) |
| Open case / add entry / AI for case | `/cases*` | `CaseService` | `exception_cases`, `exception_case_entries` | — | AI request = **YES** | **No UI** | Backend IMPL (T8, T8b); UI NOT |

---

## E. Frontend-to-backend API mapping

All endpoints are under `/api/v1`, except `/health`. Every router is in `uc042app/api/routers/`; services are in `uc042app/services/`.

| Endpoint | Router → service | Frontend caller (`api/endpoints.ts` → page) |
|---|---|---|
| `GET /health` | `system.get_health` | `api.health` → TopBar, ReportPages |
| `GET/POST /periods`, `PATCH/GET /periods/{id}` | `monthly` → `MonthlyService` + `period_view` | `api.periods / createPeriod / updatePeriod / period` → Dashboard, Reports, NewReport, Report, Upload, Batch |
| `POST /periods/{id}/uploads` | `monthly.upload` → `MonthlyService.upload` | `api.upload` → UploadPage, AddSupportingDocument |
| `GET /uploads/{id}`, `POST …/confirm`, `POST …/process` | `MonthlyService.batch_detail / confirm / process` | `api.batch / confirmBatch / processBatch` → BatchPage |
| **`POST /periods/{id}/reconciliation`** | `MonthlyService.reconcile` | **none** |
| `GET /documents/{id}` | `MonthlyService.document` | `api.document` defined, **never called** |
| `GET /documents/{id}/content`, `POST …/review` | `document_content`, `review_document` | `documentContentUrl`, `reviewDocument` → DocumentTable |
| `GET /processing-runs/{id}`, `GET /activity` | `MonthlyService.run`, activity repository | `processingRun` (DataSource), `activity` → Dashboard |
| `GET /packs`, `/packs/{id}`, `/reconciliation`, `/sources`, `/exceptions`, `/exceptions/{e}` | `packs` → `PackService` (+ `InvestigationService.for_exception`) | Dashboard, PackDetail, Workspace, ReportPages, Review |
| `GET /packs/{id}/investigations` | `InvestigationService.for_pack` | Dashboard (per pack), Report, PackDetail, Workspace, Review |
| `GET /packs/{p}/exceptions/{e}/investigations` | `for_exception` | defined, **never called** |
| `POST /packs/{p}/exceptions/{e}/investigations` | `InvestigationService.start` | AiPanel "Run investigation" |
| `GET /jobs/{id}` | `JobRunner.repo` | `useJobPoller` (AiPanel, BatchPage, Review) |
| `GET /investigations/{id}`, `/findings`, `/evidence`, `/verify` | `InvestigationService` | Workspace (`verify` only through DataSource; not displayed) |
| `GET /reviews`, `POST /packs/{id}/reviews`, `GET /reviews/{id}`, `PATCH …/selections`, `POST …/preview`, `GET …/preview/{kind}`, `POST …/decision`, `GET …/history` | `reviews` → `ReviewService` | Reviews, OpenReview, Review, DecisionPanel, SelectionEditor (`GET …/preview` metadata is defined but never called) |
| `GET /final-packs`, `/{id}`, `/verify`, `/{json\|html\|pdf}` | `final_packs` → `FinalPackService` | Dashboard, Reports, Report, FinalPack(s) |
| **`POST /packs/{p}/exceptions/{e}/case`, `GET /cases`, `GET /cases/{id}`, `POST /cases/{id}/entries`, `POST /cases/{id}/ai-investigation`** | `cases` → `CaseService` | **none** |

**Errors** use problem+json (`api/problems.py`). Validation failures are **HTTP 422**. The UI shows `detail` and code through `ErrorPanel` / `Notice` (for example I15: "Code: PROVIDER_NOT_CONFIGURED · HTTP 503").

**Middleware:**

- requests from any non-loopback client get 403;
- `nosniff`, `X-Frame-Options: DENY`, `no-store` on `/api`;
- CORS limited to `UC042_CORS_ORIGINS`;
- served HTML uses CSP `sandbox`.

---

## F. Database and file-storage architecture

**PostgreSQL `uc042`** (pg8000, SQLAlchemy, Alembic head `0003_unified_schemas`):

| Schema.table | Holds |
|---|---|
| `audit.reconciliation_periods` | period, status, title, `storage_profile` ("" = primary, `historical-demo`) |
| `audit.period_packs` | period → pack reference (origin POC_SCENARIO / UPLOAD_PROCESSING, content hash, run) |
| `audit.processing_runs` | runs (status, document set, purpose, reason, outcome, continuity) |
| `audit.review_sessions` / `review_decisions` / `previews` | review state, append-only decisions, write-once previews (meta and document JSON) |
| `audit.final_pack_records` | GENERATE outcome per decision |
| `audit.investigation_registry` | append-only publication registry (pinned file hashes) |
| `audit.investigation_authorizations` | append-only APPROVED / AUTHORIZATION_DISCREPANCY (latest row wins) |
| `audit.record_provenance` | unification provenance |
| `operations.upload_batches` / `source_documents` | batches; document metadata and checks JSON, submission kind and reason, `replaces_document_id` |
| `operations.jobs` | background jobs. For PROCESSING jobs the `pack_id` column holds a period ID. |
| `operations.exception_cases` / `exception_case_entries` | cases and their append-only history |
| `operations.activity_events` | activity log |

**Files** (write-once; the database holds only references and hashes):

| Content | Location | Notes |
|---|---|---|
| Deterministic packs | `packs/` (primary; new uploads go here), `demo_history/packs/` (historical-demo profile) | Immutable; ID `PACK-<scenario>-PER-YYYY-MM-<sha12>`. Uploaded packs get `PACK-CASE-…`. |
| AI investigations | `investigations/` and `demo_history/investigations/<pack>/<exc>/INV-…/`; rejected attempts in `_not_published/` | `evidence_packet.json`, `evidence_ledger.json`, `findings.json`, `tool_calls.json`, `runs/NNNN.json` |
| Final packs | `final_packs/` (primary, created on first GENERATE), `demo_history/final_packs/` | `final_pack.json` (canonical), `report.html`, `report.pdf`, `manifest.json` |
| Uploaded originals | `UC042_DOCUMENT_STORE/objects/<sha[:2]>/<sha>` | Content-addressed; hash re-checked on every read |
| Prepared cases | `UC042_DOCUMENT_STORE/cases/SET-<hash>` | `intake.csv`, `manifest.csv`, `policy_selection.json` |
| POC datasets | `uc042_dataset/`, `demo_history/datasets/` | Read-only engine and AI input |
| Instance lock | `UC042_APP_STATE_DIR/instance.lock` | One backend per state directory |

**Storage layout** (`services/layout.py`):

- A pack is resolved by where it physically is: exactly one root set must contain it, otherwise `DUPLICATE_PACK`.
- A pack in a profile root must belong to that profile's periods (`PACK_OUTSIDE_PROFILE`).
- Its investigations and final packs are read and written in the same root set.
- **Consequence:** a final review GENERATE on a historical pack writes to `demo_history/final_packs/`, as February did.

---

## G. Deterministic reconciliation pipeline

```
upload ─► ingest.analysis (identify by content; dates; duplicates; policy PDF) ─► current_set (latest usable per slot)
      ─► prepare.prepare_case (intake: ACCEPTED/DUPLICATE/REJECTED/AMBIGUOUS/MISSING; policy selection)
      ─► validate.Validator.run: load ─► structure (DQ) ─► evidence gate ─► controls (policy, coverage, statements,
         cashbook↔bank, internal C04–C06, external C07–C08, settlement, top-ups, allocation, unmatched bank,
         refunds, client roll-forward, currency isolation, designation, discrepancy log, checklist)
         ─► group_exceptions / correlate
      ─► pack.assemble + finalise (pack_content_sha256, pack_id) ─► validate_pack (V1–V6, V8) ─► render_html
      ─► MonthlyService._publish (write-once, os.replace) ─► period_packs ─► continuity vs previous month
```

**Outcomes:**

- per check: PASS, FAIL, INSUFFICIENT_EVIDENCE or NOT_APPLICABLE;
- case status: CLEAN, EVIDENCE_INCOMPLETE or EXCEPTIONS_OPEN.

**Guarantees verified by this audit:**

- **Reproducibility.**
  - January uploaded into the isolated database produced `PACK-CASE-PER-2026-01-be868a82a6e4`. Its reconciliation summary, control register, exception register, missing-evidence register and settlement register are **identical** to the historical `PACK-H202601-…`.
  - March, uploaded **through the UI**, produced `PACK-CASE-PER-2026-03-3d04203c985b` with 3 exceptions. All registers are **identical** to `PACK-H202603-…` once the ID prefix is normalised (`EXC-CASE-` vs `EXC-H202603-`).
  - A re-run on the same set gives `ALREADY_EXISTS` (idempotent).
- **No automatic processing.** Processing needs a confirmed batch (`BATCH_NOT_CONFIRMED`, `NO_CONFIRMED_DOCUMENTS`) and all required inputs (`INCOMPLETE`).

**Not verified:** `processing_supported()` returns true for every month. Months before 1 October 2025 cannot actually be processed, because IN-17 (policy) is required and no policy version applies before then. This is inferred from code and was not tested.

---

## H. AI investigation pipeline

Traced with February's published `INV-EXC-H202602-01-6b1425b437f4`. No call was made.

1. **Selection.** The analyst clicks "Run investigation" for one exception: `POST /packs/{p}/exceptions/{e}/investigations`, or `POST /cases/{id}/ai-investigation` (API only).

   `InvestigationService.start` (`services/investigations.py`) then:
   - loads and verifies the pack;
   - refuses a second active job (`INVESTIGATION_ACTIVE`);
   - checks `retry_of`;
   - gets the investigator. A missing key or an offline/simulated provider gives **503 `PROVIDER_NOT_CONFIGURED`**, verified in isolation.

   It then creates an INVESTIGATION job in a thread pool. Jobs interrupted by a restart become INTERRUPTED and never re-run. **The backend always uses tools mode.**

2. **Approved evidence** (`uc042lib/investigation/roots.py`, `retrieval.py`):
   - roots per profile;
   - no root may contain or sit inside `verification`, `golden`, `tests` or `UC042_JAN_AUG_HISTORICAL_DEMO`;
   - forbidden file names include `answer_key.json`, `scenario.json` and others;
   - the pack must hash-match;
   - **every input file is SHA-256-checked against the pack's audit trail before any row is indexed**;
   - **only CSV inputs IN-01..IN-14 are evidence. PDFs (IN-15..19) are never read by the AI.**

3. **Evidence packet** (`packet.py`):
   - route chosen by exception category, here `missing_bank_evidence`;
   - scoped retrieval through verified join keys only, with empty searches recorded as `SEARCH-nn`;
   - contents: whitelisted exception fields; related exceptions; candidate relationships labelled "UNVERIFIED"; control results; source records with file, line and hash provenance; missing evidence; conflicts; `allowed_citation_ids`; `packet_sha256`;
   - at most 160 records.
   - **February:** 16 records, 36 citable IDs, 3 searches, 1 MISS.

4. **LLM call** (`llm.py`, `prompts.py`):
   - OpenAI **Responses API** `responses.parse`, structured output `LLMInvestigationOutput`, `store=False`;
   - model `gpt-6-luna`, at most 8,000 output tokens, 120 s per request, 300 s total;
   - the system prompt forbids invented records, zero for missing values, stated causes, resolution and opinions, and treats packet text as untrusted;
   - the packet goes inside `<evidence_packet>` tags.

5. **Tools** (`tools.py`, `tool_loop.py` as a LangGraph subgraph): 8 read-only strict tools:
   - `get_source_record`
   - `search_bank_entries`
   - `get_cashbook_entries`
   - `get_settlement_batch`
   - `search_customer_transactions`
   - `get_customer_balance_snapshots`
   - `get_reconciliation_evidence`
   - `follow_relationship`

   **Limits:** 8 calls, 4 rounds, 25 records per call, 160 records in total, about 150k input tokens. Duplicate calls are deduplicated, a budget-exhausted notice is issued, and one schema-correction retry is allowed. The ledger grows from the packet. **February:** 8 calls in 1 round (5 bank searches, all NOT_FOUND), 16 → 29 records.

6. **Citations and validation** (`validation.py`, deterministic):
   - every cited ID must be in the ledger's `allowed_citation_ids`;
   - confirmed findings must cite evidence and never a candidate relationship;
   - cause, resolution and non-existence wording is rejected;
   - contradiction rules apply;
   - every MISS item must be preserved;
   - EVIDENCE_SUFFICIENT is not allowed while evidence is missing;
   - **ZERO_PATTERN** rejects "balance … 0.00" claims while evidence is missing.

   Any error makes the attempt **REJECTED**: it is written to `_not_published/` and the job FAILED. **There is no automatic retry.**

   Verified: February's first attempt `_not_published/…/2026-11-04T054432+0000-c392e113.json` was REJECTED with the single finding "F-03: appears to substitute zero for a balance while evidence is missing". This is the false positive noted in report 17. The analyst's rerun produced `6b1425b437f4`.

7. **Persistence:**
   - write-once folder with ID `INV-<exc>-sha256(content)[:12]`;
   - an identical rerun appends `runs/NNNN.json`;
   - `verify_published` re-hashes everything;
   - the registry (`audit.investigation_registry`) pins file hashes.

   **Eligibility for a final pack** requires all of: verified; same pack hash; COMPLETED/VALID; not simulated; **passes the current validation rules**; **registered**; not AUTHORIZATION_DISCREPANCY.

   **February results:** 7 confirmed findings, 1 hypothesis, 1 missing-evidence item, 3 next steps; **INSUFFICIENT_EVIDENCE**; `NOT_RESOLVED_BY_INVESTIGATION`; 2 LLM calls, 41,703 tokens, 63.8 s.

   **Live eligibility state:**
   - February `6b1425b437f4`: eligible.
   - February `a3fd3fd2e9ed` (Phase 6A): not registered.
   - June `c7b353b53fb3`: authorisation discrepancy.
   - September: 7 POC artefacts unregistered, of which 3 also **fail the current findings-1.4 rules** (`C-01: a contradiction must name exactly two different compared evidence IDs`, seen on screen L07).

---

## I. Closing summary and final-pack generation

- **Closing summary** (`final_pack/summary.py`): a separate AI call, made only by `POST /reviews/{id}/preview`.
  - **Input:** a fingerprinted, row-free digest: executive summary, missing evidence, exceptions (all UNRESOLVED), and the selected investigations' findings, hypotheses, gaps and next steps, with `allowed_refs`.
  - **Output:** `ClosingSummaryOutput`, validated for allowed references only, no resolution, opinion or cause wording, and `unresolved_items` equal to the unresolved exceptions.
  - **Failure:** any configuration or validation failure gives **UNAVAILABLE**. The preview still builds and GENERATE then needs a second acknowledgement. Verified in isolation: GENERATE without it returns 422 `SUMMARY_UNAVAILABLE_ACK_REQUIRED`.
  - **February:** GENERATED by gpt-6-luna, 4,860 tokens. "The deterministic engine reports EVIDENCE_INCOMPLETE … one OPEN exception, classified Critical … remains UNRESOLVED and awaits human review."
- **Snapshot** (`snapshot.py`): pack ID and hash, plus each selection with its findings, packet and ledger hashes. GENERATE requires the preview's snapshot hash (`PREVIEW_STALE` otherwise) and re-derives the same snapshot.
- **Assembler** (`assemble.py`, **no AI**):
  - copies the deterministic sections verbatim;
  - exception register verbatim and UNRESOLVED;
  - investigation content verbatim;
  - evidence index, human review, limitations, audit trail;
  - the supplied closing summary.

  `validate_final_pack` re-checks all of this. `publish_final_pack` renders HTML and PDF (ReportLab, byte-reproducible) from the canonical JSON, writes the manifest, and publishes with one atomic rename. `verify_final_pack` re-renders and compares bytes.
- **February final pack:** `FAP-H202602-PER-2026-02-v1-b8dd53bd2449`.
  - Files: `final_pack.json` 195,013 bytes; `report.html` 111,395; `report.pdf` 78,866 (24 pages); `manifest.json` 962.
  - Integrity is verified on the live screen. Downloads are byte-identical to disk (T11).
  - Cosmetic issue: it lists the unregistered `a3fd3fd2e9ed` under `other_attempts.published_not_selected`, because the snapshot uses library-only eligibility.
- **Versioning (finding):** `next_version()` counts **per deterministic pack**. Re-reviewing the same pack gives v2 superseding v1. **A reassessment creates a new deterministic pack, so its final pack is a new v1 with no supersedes link.** Proven in isolation: February ended with `FAP-H202602-…-v1` and `FAP-CASE-PER-2026-02-v1-f3f085951d4b` (`supersedes: None`) side by side. This contradicts the reassessment notice ("published as a new version"). See L-4.

---

## J. Existing historical and September data behaviour (live, read-only)

| Check | Result | Evidence |
|---|---|---|
| January–August listed with correct titles and statuses | **Yes.** 9 real periods plus October and November 2026 shown as "No data" (the archive lists every month of the current year). Titles are derived ("<Month> 2026 Reconciliation Audit") for Jan–Aug and stored for September. | L03 |
| February published final pack | **Yes.** Status "Final audit pack published"; 1 published + 1 excluded investigation; closing summary shown; JSON/HTML/PDF links; integrity verified; inline PDF renders 24 pages (headless Edge, new mode). | L06, L13, L15 |
| September's 9 scenarios grouped under one month | **Yes.** "9 demonstration scenarios … not separate months" on the archive, dashboard and report. "0 +7 excluded" investigations. | L02, L07 |
| June discrepancy | **Yes.** "0 +1 excluded". | L03, L08 |
| Period switching and URL navigation | **Yes.** Topbar select → `/reports/<id>`. `/periods/PER-2026-03` → `/reports/PER-2026-03`. Unknown route → "Page not found". Refreshing a deep link reopens the same pack, exception, tab (`?tab=`) and view (`?view=`). | L23, L24 |
| Search and filters | **Yes.** Status = "Final audit pack published" → February only. Search "june" → June only. | L04, L05 |
| Document inventory and downloads | Live months have **0 uploaded documents** (registered from datasets). The pack screen's source inventory lists files and SHA-256 (download not offered). Uploaded-document download was tested in isolation with hash header equality. | L09, T11 |
| Investigation and exception details | **Yes.** Exception KPIs, 6+ engine results, 29 supporting records grouped by source, relationships, and the AI panel with tabs and eligibility. | L10–L12 |
| JSON / HTML / PDF downloads | **Yes.** Byte-identical, with correct content types. | T11 |

**Performance** (live, after the 15:39 restart; time until no "Loading" text remained):

| Screen | Time to load |
|---|---|
| Archive | 10.0 s |
| June | 10.3 s |
| New-report form | 10.0 s |
| Upload | 17.3 s |
| September | 20.1 s |
| Dashboard (September) | 20.9 s |
| February report | 27.2 s |
| **Dashboard** | **33.5 s** |

`GET /periods` takes 1.1–1.3 s alone and **about 8.9 s when four list requests run concurrently**, which is what every page does: topbar plus page, each calling `/periods` and `/packs`. The dashboard also calls `/packs/{id}/investigations` for each of the 17 packs, more than once. Before the restart, pages had not loaded within 12 s at all. Performance code was being changed during the audit (MOD).

---

## K. Functional verification results

**Isolated instance.** Full log: `19_audit_screenshots/evidence.json` and `evidence_2.json`.

| # | Test | Result | Status |
|---|---|---|---|
| T1 | Create PER-2026-01 / duplicate / future / rename / short title | 201 created · **200, title unchanged** · **422 `FUTURE_PERIOD`** · 200 `STORED` · 422 | IMPL |
| T2 | Upload January's 17 files (14 CSV + 3 PDF) | 201, all 17 VALID, identified IN-01..17 by content. Process before confirming → 409 `BATCH_NOT_CONFIRMED`; reconcile → 409 `NO_CONFIRMED_DOCUMENTS` | IMPL |
| T3 | Wrong period: January transactions uploaded to October | Batch INVALID; **`WRONG_PERIOD` ERROR** "no record falls in the selected month on transaction execution timestamp"; also `SAME_CONTENT_AS_OTHER_PERIOD` | IMPL (I08) |
| T4 | Confirm → process (UI endpoint) → explicit INITIAL reconcile → REASSESSMENT without new evidence | SUCCEEDED `PACK-CASE-PER-2026-01-be868a82a6e4`, 0 exceptions, CLEAN, continuity NOT_VERIFIABLE · re-run `ALREADY_EXISTS` · **409 `NOTHING_TO_REASSESS`** | IMPL |
| T5 | Duplicate document | **`DUPLICATE_OF_EARLIER_UPLOAD`**, decision required → confirm 409 `DECISIONS_PENDING` → EXCLUDE with comment → CONFIRMED | IMPL (I09) |
| T6 | Correction / two-file correction / evidence without reason | CORRECTION linked to the replaced document (`REPLACES_DOCUMENT`) · 422 `INVALID_SUBMISSION` · 422 `REASON_REQUIRED` | IMPL (I16) |
| T7 | February (published): additional evidence = a re-sent **acknowledgement letter** | Recognised as IN-16, then **`LETTER_NOT_MATCHED` ERROR** (February has no uploaded IN-02) → batch INVALID → **cannot be confirmed** (409 `BATCH_INVALID`). The period still turned "Additional evidence received / pending reassessment". | Partial (L-5) |
| T7b | February: a genuine non-input PDF as additional evidence | `SUPPORTING_EVIDENCE` warning + `RECEIVED_AFTER_PUBLICATION` → confirmed → process and REASSESSMENT both **409 `INCOMPLETE`** (IN-01..IN-17 missing) | IMPL as designed, but reassessment is impossible without a full re-upload (L-3) |
| K-R | February: full 17-file re-upload → REASSESSMENT → GENERATE | Upload flagged 2 (`SAME_CONTENT_AS_OTHER_PERIOD`, `DUPLICATE_OF_EARLIER_UPLOAD`) → INCLUDE → confirm → **REASSESSMENT SUCCEEDED** `PACK-CASE-PER-2026-02-54bf8326eb35` (1 exception, purpose REASSESSMENT) → review (NOT_INVESTIGATED) → GENERATE **`FAP-CASE-PER-2026-02-v1-f3f085951d4b`, version 1, supersedes None** | IMPL; versioning gap (L-4) |
| — | Published February final pack after all uploads and reassessment | Directory hash identical before and after (`1b22b1ea…`); originals re-verified (61 files) | IMPL |
| T8 / T8b | Cases (API) | Open 201 / again 200 same case · fabricated reference 422 `INVALID_EVIDENCE_REF` · NOTE 201 · stale revision 409 `CASE_CHANGED` · OBSERVATION without evidence 422 `EVIDENCE_REQUIRED` · DECISION ESCALATED → case `ESCALATED`, still OPEN · **pack exception unchanged (OPEN / AWAITING_HUMAN_REVIEW)** · case AI and direct investigation → **503 `PROVIDER_NOT_CONFIGURED`** | Backend IMPL; UI NOT |
| T9 | January (0 exceptions) final review | Open: blocker `PREVIEW_REQUIRED`, info `NO_EXCEPTIONS` · GENERATE without preview 409 · preview COMPLETED, **summary UNAVAILABLE** (no provider), HTML/PDF/JSON previews 200 · HOLD → ON_HOLD, preview cleared · GENERATE without the summary acknowledgement 422 · GENERATE → **`FAP-CASE-PER-2026-01-v1-ee0b03fcf6cc`**, verify OK, downloads 200 · decide again → 409 `SESSION_CLOSED` · **opening the review again → 201, a NEW OPEN session** | IMPL (I13, I14) |
| T10 | February review opened in isolation | 201 OPEN. Blockers `NOT_INVESTIGATED_WITH_ELIGIBLE` + `PREVIEW_REQUIRED` (the copied investigation is unregistered in the isolated database) | IMPL (I19) |
| T11 | February final pack retrieval (copy) and document download | verify OK; JSON/HTML/PDF byte-identical to disk; document download hash header matches | IMPL |
| UI | **End-to-end in the browser:** Upload page → attach 17 March files → "Upload and validate" → batch page → Checks → comment → Include → "Confirm batch" → "Start processing" | Run SUCCEEDED, `PACK-CASE-PER-2026-03-3d04203c985b`, "PUBLISHED · 3 exception(s)"; March report shows the pack | IMPL (I01, I02, I20, I22, I05) |
| UI | "Run investigation" with no provider | Error panel "The investigation could not be started … OPENAI_API_KEY is not set … Code: PROVIDER_NOT_CONFIGURED · HTTP 503" | IMPL (I15) |
| UI | New-report form: duplicate / future | "January 2026 already exists … Open January 2026"; "December 2026 has not started yet"; Create disabled | IMPL (I17, I18, L20) |

**Not tested in the first pass:**

- Live AI investigation and closing summary.
- INVESTIGATION_ACTIVE, retries and job recovery.
- Selection editing and stale preview in the UI.
- The February live review page.
- The automated test suites.

The business owner then authorised these. **All of them were run in the follow-up; see §P.**

---

## L. Incomplete, mock or blocked functionality

| # | Item | Classification | Detail and evidence |
|---|---|---|---|
| L-1 | **Navigation creates review sessions** | Working, with a side effect | `/packs/:id/review` sends `POST /packs/{id}/reviews` on page load. If the pack's last session is GENERATED, as February's is, a **new OPEN session is created** (T9: 201, new ID). The links are: Report section 3 "Final review", Pack "Open final review", Workspace "Continue to final review", and sidebar "04 Final review" whenever a pack is open. **Proven live (§P, authorised):** opening the February route created `RS-fc0a6e7f8aa4512c18b9a891` (OPEN) in `uc042`. Review sessions went from 1 to 2, and the dashboard now shows "Pending reviews 1". **No activity event was written.** |
| L-2 | **Exception investigation cases** | **Backend implemented, not connected** | Every `/cases*` endpoint works (T8/T8b), but there is no UI, API client or type for them. |
| L-3 | **Explicit reconciliation / reassessment** | **Backend implemented, not connected**; working partially | `POST /periods/{id}/reconciliation` (INITIAL / REASSESSMENT) has no UI. The UI's "Start processing" always runs INITIAL and ignores reassessment gating. The pending-reassessment notice sends the user to "open a final review", which only re-reviews the **old** pack and does not reprocess. Reassessing a historical month **needs all 17 inputs re-uploaded** (T7b `INCOMPLETE`; K-R succeeded only after a full re-upload). |
| L-4 | **Reassessment versioning** | Working partially | A reassessed month gets a new deterministic pack, so its final pack is a **separate v1** (`supersedes: None`). Two unrelated "v1" final packs for one month (K-R). Report 18 §7 and the UI notice promise "a new version that supersedes the old one". |
| L-5 | **Supporting evidence that is a recognised input type** | Working partially | A re-sent acknowledgement letter is classified as IN-15/16 and fails `LETTER_NOT_MATCHED` when the period has no uploaded IN-02, as with every preloaded month. **The whole batch becomes INVALID and cannot be confirmed**, yet the period is already marked "pending reassessment" (T7). |
| L-6 | **"Run investigation" safety** | Working end to end, with a risk | One click starts a live, paid OpenAI run. There is no confirmation dialog, no authorisation check (the authorisation table is used only *after* publication), and the live backend has a configured provider. A click on any Jan–Aug or September exception would create an unauthorised investigation, the same way the June discrepancy arose. |
| L-7 | **Performance** | Working, slow (**MOD**) | Pages take 10–33 s to load (§J). Changes to period and investigation listing were in progress during the audit. |
| L-8 | **Dashboard KPI counts** | Working partially | With September selected: "AI investigations **7**" counts unregistered artefacts (the archive says 0 +7 excluded). "Final audit packs **1**" is global (February's), not the selected month's. |
| L-9 | **Activity labels** | Working partially | The new action codes are shown raw: `DATABASE_UNIFIED`, `INVESTIGATION_AUTHORIZATION_RECORDED`, `CASE_*`, `REASSESSMENT_STARTED`. The label map in `apiSource.ts` predates them. Review and GENERATE decisions do not appear in the activity feed. |
| L-10 | **Empty files as cross-month duplicates** | Working, with friction | A header-only discrepancy log is byte-identical every month, so `SAME_CONTENT_AS_OTHER_PERIOD` requires a manual decision in every upload (I02, K-R). |
| L-11 | `/investigations/:id` | **UI-only placeholder** | Shows the exception ID; does not open the investigation. |
| L-12 | Mock data source and design upload | **UI-only / mock** (development only) | `VITE_DATA_SOURCE=mock`: simulated jobs, HOLD and GENERATE, and a name-only upload check. Not in production builds. The live app reported "Live backend". |
| L-13 | September investigations | Not eligible by data, not by code | 7 POC artefacts are unregistered, and 3 also fail the current rules. September cannot include any investigation in a final pack without new runs or a registration decision. |
| L-14 | Exception evidence without AI | Design limitation | The workspace's "Supporting evidence" comes only from an investigation's ledger. Without an investigation an analyst sees engine results only, not the underlying bank or cashbook records. |
| L-15 | Defined but unused client calls | Dead code | `api.document`, `api.exceptionInvestigations`, `api.previewMeta`, `api.previewPdfUrl`. |
| L-16 | Legacy `uc042_history` database | **Resolved after the audit (correction)** | At the audit's read-only check (15:3x) it was still present and writable. The other session retired it afterwards, during the audit window (report 19 §13.1). A direct check at 16:4x confirmed that only **`uc042_history_retired_20261104`** exists, with `default_transaction_read_only=on` and 0 connections. `uc042_e2e_rehearsal` is the other session's isolated clone (report 19 §13.3). |
| L-17 | Topbar "environments are not combined" tooltip | **MOD: fixed during the audit** (15:28) | It now says "Every reporting period of this database is listed". |
| L-18 | Cosmetic: final pack lists the unregistered Phase 6A artefact as "published_not_selected" | Working, cosmetic | §I |
| L-19 | June guard test | **MOD**: changed by the other session at 15:25 | `tests/test_demo_history.py` now pins the June artefact as a preserved AUTHORIZATION_DISCREPANCY. It **passes** (§P), whereas report 19 recorded it as failing on purpose. |
| — | Blocked by the separate-database architecture | **None** | Unification is complete (§0.2). |

---

## M. Operational requirements and limitations

- **Processes:** PostgreSQL 18 cluster on `127.0.0.1:5433`, started manually after a restart. Do not close the shell that started `pg_ctl` (report 18). One backend per state directory (`python -m uc042app --port 8000`). Vite dev server on 5173 (`npm run dev`), or a built `dist/`.
- **Configuration** (`uc042/.env`, never printed): `UC042_DATABASE_URL`; the OpenAI key; `UC042_LLM_MODEL=gpt-6-luna`; and `UC042_APP_STATE_DIR` / `UC042_DOCUMENT_STORE` **outside the project**, otherwise the guard test trips (report 19 §11.6).
- **Security model:** loopback only, no authentication, one analyst identity from configuration, CORS allow-list. **Unsuitable for multi-user or networked use.**
- **Concurrency:** in-process locks only. Admin CLI commands need the backend stopped (instance lock). Interrupted jobs are not resumed.
- **Limits:**
  - upload: 60 files of at most 50 MB each, read into memory before the size check;
  - AI: 8 tool calls, 4 rounds, 300 s, about 60k tokens per investigation (February: 41.7k);
  - processable months: in practice October 2025 onwards (policy coverage; inferred).
- **Windows:** artefact paths are deep. A root path longer than about 60 characters breaks investigation listing with `FileNotFoundError` (260-character `MAX_PATH`), observed during this audit's setup. Keep roots short or enable long paths.
- **Backups:** manual `pg_dump` in `uc042/db_backups/`. Artefact folders are not backed up by the application.

---

## N. Recommended improvements

Listed for review only. None were made.

1. **Make opening a review explicit (L-1).** Keep `/packs/:id/review` read-only and add an "Open new review" button, or show the existing GENERATED session.
2. **Put a confirmation and authorisation gate on "Run investigation" and "Generate preview" (L-6).** Show the model and estimated cost, and require a recorded authorisation for historical months. Consider leaving the provider unconfigured on demonstration instances.
3. **Expose reassessment and cases in the UI (L-2, L-3).** The backend is ready.
4. **Decide reassessment versioning (L-4).** Either version final packs per period with `supersedes` across packs, or relabel reassessed packs explicitly as new, independent packs.
5. **Treat a recognised input uploaded as additional evidence leniently (L-5).** Allow `LETTER_NOT_MATCHED` to downgrade to a warning, or limit its effect to that one document.
6. **Performance (L-7).**
   - One call for the period list, so `/periods` is not requested twice per page.
   - Server-side investigation coverage.
   - Remove the per-pack `packInvestigations` fan-out from the dashboard.

   Already partly in progress (MOD).
7. **Fix the dashboard KPIs (L-8)** to count only registered, non-discrepant investigations and the selected month's final packs. **Fix the activity labels (L-9).** Record review and GENERATE in the activity log.
8. **Exempt header-only files from cross-month duplicate decisions (L-10).**
9. **Retire `uc042_history`** as in report 19 §4 step 6. **Document or drop `uc042_e2e_rehearsal`.**
10. **Make `processing_supported`** reflect the policy coverage.
11. **Decide the September POC investigations** (register or rerun) and the June artefact (guard test).

---

## O. Glossary

| Term | Meaning |
|---|---|
| Period (`PER-YYYY-MM`) | One reporting month; immutable ID |
| IN-01..IN-19 | The 19 contract inputs: 14 CSV (calendar, accounts, balances, recon records, bank statements, cashbook, transactions, settlements, discrepancy log) and 5 PDF (acknowledgement letters IN-15/16, policy IN-17, governance IN-18, return receipt IN-19) |
| Batch (`UPL-…`) | One upload. VALIDATED → CONFIRMED → PROCESSING → PROCESSED / PROCESSING_FAILED |
| Submission kind | INITIAL, ADDITIONAL_EVIDENCE (reason required) or CORRECTION (one file, `replaces_document_id`) |
| Current set | The latest usable document per input slot across confirmed batches |
| Deterministic pack (`PACK-…`) | Immutable engine output. Kinds: historical monthly, demonstration scenario, uploaded documents (`PACK-CASE-…`) |
| Exception (`EXC-…`) | An engine finding. Always OPEN / UNRESOLVED in the application |
| Storage profile | `primary` or `historical-demo`: which artefact folders hold a period's files |
| Evidence packet / ledger | The scoped, hash-verified records given to the AI, and the same set extended by tool calls |
| Citation ID | `IN-xx:<key>`, a control-result ID or `SEARCH-nn`; must be in `allowed_citation_ids` |
| Confirmed finding / hypothesis / gap / conflict / next step | AI output classes (`F-`, `H-`, `M-`, `C-`, `S-`); only confirmed findings are evidence-backed |
| ZERO_PATTERN | Validation rule rejecting "balance … 0" claims when evidence is missing |
| Publication registry | Append-only database list of registered investigations, with pinned hashes |
| Authorisation | Append-only APPROVED / AUTHORIZATION_DISCREPANCY decision per investigation |
| Eligible | Usable in a final pack: verified, valid under current rules, registered, not discrepant |
| Review session (`RS-…`) | OPEN / ON_HOLD / GENERATING / GENERATED / GENERATION_FAILED |
| Snapshot | Hash of the pack and selected investigations; GENERATE must match the previewed snapshot |
| Closing summary | AI digest of the whole pack, generated at preview; may be UNAVAILABLE |
| HOLD / GENERATE | Human decisions; GENERATE publishes a final pack and resolves nothing |
| Final audit pack (`FAP-…-v<n>-<hash>`) | Immutable JSON + HTML + PDF + manifest, versioned per deterministic pack |
| Pending reassessment | A document arrived after the latest final pack; the published pack does not include it |
| Case (`CASE-…`) | Analyst's investigation file for one exception (API only) |

---

## P. Follow-up testing authorised by the business owner (4 November 2026, 16:05–16:30 IST)

**Authorisation** (given after the first version of this report):

- live AI **on the isolated copy only**;
- test suites on a separate database;
- job-safety checks;
- review UI interactions;
- opening the live February review page, knowingly creating one review session in `uc042`.

No other live-database write and no live-app AI call was made.

### P.1 Live AI on the isolated copy

- **Instance:** backend `:8019`, database `uc042_audit19`, roots under `%USERPROFILE%\uc042_a19\`.
- **Provider:** configured from `.env`: `openai`, `gpt-6-luna`, reasoning effort medium.
- **Code:** the instance was restarted at 16:08, so it ran the working-tree code as of then.

| # | Test | Result | Status |
|---|---|---|---|
| J1 | `retry_of` naming a job that does not exist | 422 `VALIDATION_ERROR`, "retry_of must name an earlier job for the same exception"; no job created | IMPL |
| J2/J3 | Start job A (live), then immediately start again | A 202 QUEUED → RUNNING. The second request gets **409 `INVESTIGATION_ACTIVE`** with A's job ID. | IMPL |
| J4 | Case AI request while A runs | **409 `INVESTIGATION_ACTIVE`**: both entry points share the guard | IMPL |
| J5 | **Crash during the run**: backend force-killed 17 s in, then restarted | Startup log: "start-up recovery: 1 job(s) interrupted". Job A is **INTERRUPTED** ("the backend restarted while this job was RUNNING; it was not re-run automatically"). No partial artefact was written; no automatic re-run. | IMPL |
| J6/J7 | Job B with `retry_of` = A (live) | COMPLETED in 65 s. 3 LLM calls; 8 tools over 2 rounds (2× `get_settlement_batch`, `get_reconciliation_evidence`, 5× `search_bank_entries`); records 16 → 29. **VALID on the first attempt** (no ZERO_PATTERN rejection this time). Published, then **registered** (seq 1, NEW_PUBLICATION). `INV-EXC-H202602-01-15412698307d` | IMPL |
| J8 | Eligibility and content | New investigation **eligible**. The copied originals are ineligible (not in this database's registry), which is correct. Same evidence packet as the original (`760adfe54805`) and same assessment (**INSUFFICIENT_EVIDENCE**). Findings 4 confirmed / 1 hypothesis / 2 missing / 3 next steps, against 7 / 1 / 1 / 3 originally. Tokens 60,564 (original 41,703). | IMPL; non-deterministic content, as expected |

### P.2 Review UI interactions in the browser (isolated February review `RS-b008307e3819aa021ce09f06`)

| # | Interaction | Result | Screenshot |
|---|---|---|---|
| R1 | Open the review | Blockers shown: `NOT_INVESTIGATED_WITH_ELIGIBLE` and `PREVIEW_REQUIRED` | R1 |
| R2/R3 | "Edit" → selection editor → Inclusion = "Include investigation" (the eligible investigation is selected automatically) → "Save selections" | Saved; preview invalidated | R2 |
| R4 | "Generate closing summary and preview" (**live closing summary**) | Preview ready in about 10 s; HTML report shown | R4 |
| R5 | **Stale preview**: selections changed and a new preview generated behind the page's back, then "GENERATE" → "GENERATE PACK" with the page's old snapshot | Refused. Notice "**The preview is stale** — the decision does not match the current preview; reload the preview". Nothing generated. | R5 |
| R6 | Reload | Shows the newer preview (snapshot `7412ee91b785`), selection "EXCLUDED BY ANALYST · Audit19 stale-preview test" | R6 |
| R7 | Re-include → save → generate preview (**live**) | Preview in about 12 s | — |
| R8 | "HOLD" → modal → reason → "SAVE HOLD" | "Decision saved: HOLD … No final pack was generated", with the note; preview cleared | R8 |
| R9/R10 | Generate preview again (**live**) → acknowledgement → "GENERATE" | The modal states: does not resolve exceptions, confirm hypotheses, certify or establish compliance; "1 exception(s) will be reported as UNRESOLVED" | R10 |
| R11 | "GENERATE PACK" | **`FAP-H202602-PER-2026-02-v2-45257b96de2e`**: version **2**, **supersedes `FAP-H202602-…-v1-b8dd53bd2449`**. Integrity verified. Closing summary GENERATED (gpt-6-luna). Includes `INV-…-15412698307d`. Decision history HOLD then GENERATE. | R11, R12, R13 |

**Live AI usage in P.1 and P.2:**

- 1 interrupted investigation (partial; tokens not recorded);
- 1 complete investigation (60,564 tokens);
- 4 closing summaries.

Every artefact was written only under `%USERPROFILE%\uc042_a19\`.

Note: re-reviewing the **same** deterministic pack versions correctly (v2 supersedes v1). The versioning gap L-4 applies only to reassessment, which creates a new deterministic pack.

### P.3 Live February review page (authorised write to `uc042`)

`http://127.0.0.1:5173/packs/PACK-H202602-PER-2026-02-195df2e1f216/review` was opened once.

| Before | After |
|---|---|
| `audit.review_sessions` 1 (`RS-898ce…` GENERATED) | **2**: new **`RS-fc0a6e7f8aa4512c18b9a891` OPEN** (created 10:45:51Z) |
| every other `audit`/`operations` table | unchanged, **including `activity_events` (14)**: the new session is not logged |
| dashboard "Pending reviews 0" | **"Pending reviews 1"**, listing the new session (L26) |

This confirms L-1 on the live system. **The OPEN session remains in `uc042`.** There is no API to delete a review session, and it was not removed by direct database edit. It holds no preview and no decision, and changes no published artefact. Removing it needs a decision by the business owner.

### P.4 Automated test suites (separate database `uc042_audit19_test`; provider key blanked; live-AI test not enabled)

| Suite | Result |
|---|---|
| Python, every module except `test_unification` (16:07–16:16, the code then current) | **577 run, OK, 1 skipped** (opt-in live AI test). The June guard test **passes**, because of the other session's 15:25 change (L-19). |
| Python `tests.test_unification` | Run separately, after the other session's own full test run (started 16:12) had finished, because both use the fixed database name `uc042_test_unify_source`. Run at 16:34. **28 run: 27 passed, 1 failed.** The failure (`test_unification_preserves_identifiers_merges_september_and_keeps_provenance`) is caused by the test setup, not by the application: the test hard-codes the target database name `uc042_test` in its provenance assertion. Running against the separate `uc042_audit19_test` gives `("uc042_audit19_test", "MERGE_TARGET", "PROCESSED", "")` where it expects `("uc042_test", …)`. Every other value is identical. Minor test-portability finding: the test should read the name from `UC042_TEST_DATABASE_URL`. |
| Frontend vitest, 16:07 | 39 passed, 2 skipped |
| Frontend vitest, 16:17 (after the other session's 16:10–16:12 frontend changes) | **40 passed, 2 skipped** |

### P.5 Code state during the follow-up

The other session changed four more files:

| Time | File |
|---|---|
| 16:10 | `frontend/src/pages/WorkspacePage.tsx` |
| 16:11 | `frontend/src/test/screens.test.tsx` |
| 16:12 | `frontend/src/components/workspace/AiPanel.tsx` |
| 16:16 | `docs/audit_pack/19_DATABASE_UNIFICATION_AND_FUNCTIONAL_GAP_CLOSURE_IMPLEMENTATION_REPORT.md` |

As of 16:17, "Run investigation" is still a single click with no confirmation, so L-6 stands.

The protected February artefacts (61 files) were re-verified byte-identical at 16:17. No file under `packs/`, `investigations/`, `demo_history/`, `UC042_JAN_AUG_HISTORICAL_DEMO/` or `uc042_dataset/` changed.

---

## Honest readiness assessment

**What is real and works end to end** (verified in this audit, mostly on an isolated copy):

- A month can be created, its 17 documents uploaded and validated in the browser, flagged files decided, the batch confirmed and processed. The result is a deterministic pack **identical** to the historical reference for January and March.
- A final review on that pack can produce a verified, byte-reproducible JSON/HTML/PDF final audit pack.
- Duplicate and wrong-period detection, corrections with version links, immutability of published packs, and the "pending reassessment" signal all work.
- The preloaded archive (January–September, nine September scenarios, February's published pack with its AI investigation and closing summary) is shown correctly, consistently labelled, and downloadable byte for byte.
- The AI layer is carefully bounded, and its February output is traceable to hash-verified evidence.

**What is not ready:**

- **Two backend capabilities have no UI:** cases, and explicit reconciliation/reassessment. Reassessment of any preloaded month is impractical: it needs a full re-upload, and it yields an unlinked "v1" rather than a new version.
- **Two controls can cause irreversible or costly side effects on the live database:**
  - visiting the review route creates review sessions;
  - "Run investigation" calls OpenAI with one unconfirmed click.

  Given the project's authorisation rules, this is the most important issue.
- **Pages take 10–33 seconds to load.** That work was being changed during this audit.
- **Every live month's data was preloaded, not uploaded.** The upload → reconcile → review → publish path has never been exercised in the live database. It was proven only in isolation.
- **Live AI was tested only on the isolated copy.** It works there (§P): first-attempt VALID investigation, 4 live closing summaries, and a GENERATE of v2. It has still never been run through the live app, apart from the single authorised February run in report 17. Its output varies between runs (4 vs 7 confirmed findings on identical evidence), as expected of a model.

**Overall:** a sound, well-guarded **single-analyst demonstration**, with a correct deterministic core and an auditable AI layer. It is **not yet ready for an analyst to operate unsupervised against the live database**, until L-1, L-6 and L-7 are addressed and the reassessment workflow (L-3/L-4) is completed in the UI.

---

### Artefacts of this audit

- **Report:** this file.
- **Screenshots and request logs:** `docs/audit_pack/19_audit_screenshots/` (49 PNG, 1600 px wide, full page; `evidence.json`, `evidence_2.json`).
- **Live screenshots:** prefix `L` (live app, read-only).
- **Isolated screenshots:** `I*` (environment tag "AUDIT 19 ISOLATED TEST (disposable)").
- **Follow-up (§P):** review-flow screenshots `R*` (isolated); `L25`/`L26` (the live review route and the dashboard after it); job-test logs `evidence_jobs_1.json` and `evidence_jobs_2.json`.
- **Disposable test material** (outside the project):
  - database `uc042_audit19`;
  - folder `%USERPROFILE%\uc042_a19\`: roots, test scripts `functional_tests.py`, `functional_tests_2.py`, the screenshot driver `shoot.py`, raw page text;
  - isolated backend on port 8019 and frontend on port 5179.

  All of these can be dropped or stopped at any time; nothing else depends on them.
