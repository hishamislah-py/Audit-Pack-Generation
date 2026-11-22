> Appendix 22D to report 22 (`22_COMPLETE_UC042_PRODUCT_AND_WORKFLOW_WALKTHROUGH.md`). Read-only code trace of the Phase 8 working tree, 5 November 2026. Nothing was executed against live data; file:line references are to `uc042/`.

# Part H: Architecture of the UC-042 application

Source: the code in `C:/Users/artlptp263user/Downloads/UC042_CLAUDE_CODE_HANDOFF/uc042`, read on 5 Nov 2026. Where the code and the docs disagree, these notes follow the code. Paths are relative to that folder. `file:line` points at the line where the cited item is defined or where the cited check is made. **UNCONFIRMED** marks anything that could not be checked from the code alone.

---

## H.1 Component responsibilities

### React (UI library)
- Draws every screen in the browser and keeps per-screen state in hooks. Entry point `frontend/src/main.tsx` mounts `<DataProvider>` around `<BrowserRouter><AppRoutes/></BrowserRouter>`.
- Screens load data with `useApi` (`frontend/src/hooks/useApi.ts`: explicit loading and error state, no caching, no mock fallback). Background jobs are followed with `useJobPoller` (`frontend/src/hooks/useJobPoller.ts`), which polls `GET /jobs/{id}` every 1 s (`POLL_INTERVAL_MS`, line 6) until the status is COMPLETED, FAILED or INTERRUPTED.
- Pages are in `frontend/src/pages/*`. Reusable panels are in `frontend/src/components/*`, for example `workspace/AiPanel.tsx`, `review/decision.tsx`, `report/Reassessment.tsx` and `ai/AiAuthorizationDialog.tsx`.

### TypeScript
- Every frontend file is `.ts`/`.tsx`. `frontend/src/api/types.ts` (993 lines) holds the response and request types, written to mirror the backend's Pydantic schemas (`uc042app/api/schemas.py`). Mistakes in how the UI uses an API are caught when the project is compiled, before it runs.
- `DataSource` (an interface in `frontend/src/data/DataSource.ts`) is the typed contract between the screens and whichever data source is active.

### React Router: every route (`frontend/src/App.tsx:16-41`)
All routes sit inside the `<AppShell/>` layout (`components/layout/AppShell.tsx`: top bar, period selector, health indicator).

| URL | Page component (file) |
|---|---|
| `/` (index) | `DashboardPage` (`pages/DashboardPage.tsx`) |
| `/upload` | `UploadPage` (`pages/UploadPage.tsx`) |
| `/reports` | `ReportsPage` (`pages/ReportPages.tsx`) |
| `/reports/new` | `NewReportPage` (`pages/ReportPages.tsx`) |
| `/reports/:periodId` | `ReportPage` (`pages/ReportPages.tsx`) |
| `/periods/:periodId` | `PeriodRedirect`: redirects to `/reports/:periodId` (`App.tsx:50-53`) |
| `/uploads/:batchId` | `BatchPage` (`pages/ArchivePages.tsx`) |
| `/packs/:packId` | `PackDetailPage` (`pages/PackDetailPage.tsx`) |
| `/packs/:packId/workspace` | `WorkspacePage` (`pages/WorkspacePage.tsx`) |
| `/packs/:packId/workspace/:exceptionId` | `WorkspacePage` |
| `/packs/:packId/exceptions/:exceptionId` | `LegacyException`: redirects to `/packs/:packId/workspace/:exceptionId` (`App.tsx:44-47`) |
| `/packs/:packId/review` | `OpenReviewPage` (`pages/ReviewPages.tsx`) |
| `/reviews` | `ReviewsPage` (`pages/ReviewPages.tsx`) |
| `/reviews/:reviewId` | `ReviewPage` (`pages/ReviewPages.tsx`) |
| `/final-packs` | `FinalPacksPage` (`pages/FinalPackPages.tsx`) |
| `/final-packs/:finalPackId` | `FinalPackPage` (`pages/FinalPackPages.tsx`) |
| `/investigations/:investigationId` | `InvestigationPage` (`pages/InvestigationPage.tsx`) |
| `/cases/:caseId` | `CasePage` (`pages/CasePages.tsx`) |
| `*` | inline "Page not found" panel (`App.tsx:38`) |

### DataSource abstraction
- `frontend/src/data/DataSource.ts:25-105` is the only connection between screens and data. Its method names follow the backend endpoints, so screens never know which source is active.
- `frontend/src/data/DataProvider.tsx` chooses the source once. The default is `createApiSource()`. The mock source is used only when `import.meta.env.DEV && VITE_DATA_SOURCE === "mock"` (line 10). It is loaded only in that case, so production bundles do not contain it, and the app never falls back from one source to the other automatically.
- `frontend/src/data/apiSource.ts` is the FastAPI adapter (the default) and a thin wrapper over `api.*`. It has a **10-second cache** (`TTL_MS = 10_000`, line 50; `cached()`, lines 54-61) for `health`, `periods` and `packs`. When several callers ask for the same list at once, one request serves them all, and a failed request is never cached (line 59). Every changing call is wrapped in `change()` (lines 64-66), which clears the whole cache in a `finally` block, so the cache is cleared even on failure. `job()` (lines 68-72) also clears the cache when a polled job reaches a final status. `periods()` (lines 78-81) merges `GET /periods` with `GET /packs` through `buildArchivePeriods` (`data/periods.ts:42`), which also adds placeholder months from January to the current month of the current year.
- `frontend/src/data/mock/MockDataSource.ts` is a design-phase mock. Reads replay captured September 2026 backend responses. Actions (investigation, preview, HOLD/GENERATE) are simulated in memory using the backend's error codes. Nothing is published, verification is never claimed, and monthly-document actions are refused (`DataSource.ts:34` comment).

### API client (`frontend/src/api/client.ts`, `frontend/src/api/endpoints.ts`)
- `client.ts:46-75`: `request()` is the only HTTP function. It uses the base URL `VITE_API_BASE_URL`, default `http://127.0.0.1:8000` (line 6). The default timeout is 30 s, and `LONG_TIMEOUT_MS = 180 s` (line 8) is used for uploads, GENERATE and final-pack verification. It sends JSON or `FormData` and parses JSON, text or blob responses. RFC 7807 problem responses become an `ApiError(status, code, detail, problem)` (lines 77-87). Network failures and timeouts become status 0 with code `NETWORK_ERROR` or `TIMEOUT`.
- `endpoints.ts:15-150` lists every backend path the UI uses as one `api` object.

### HTTP/REST
- JSON over HTTP on `127.0.0.1:8000`. Paths are versioned `/api/v1/...`, except `/health`. Only GET, POST and PATCH are allowed by CORS (`uc042app/api/main.py:44`).
- Every error is RFC 7807 `application/problem+json` with a stable `code` (`uc042app/api/problems.py:22-25`). The status-to-class mapping is in `uc042app/errors.py`: InvalidInput is 422, NotFound 404, Conflict 409, IntegrityFailure 409, ServiceUnavailable 503, and AppError 400 by default.
- The API is local-only: the middleware refuses any non-loopback client with 403 `LOCAL_ONLY` (`main.py:48-57`). `__main__.py:13` binds the server to 127.0.0.1 with one worker. There is no authentication.

### FastAPI routers (`uc042app/api/routers/*`; app factory `uc042app/api/main.py:24-63`)
- `system.py`: `/health` reports liveness, storage, registry, database, whether a provider is configured, and the environment label (no secrets).
- `packs.py`: read-only deterministic packs and exceptions. No endpoint changes an exception status.
- `investigations.py`: lists investigations and their eligibility, starts the AI investigation job, returns source evidence without AI, shows the AI configuration and the AI authorisation records, polls jobs, and returns investigation detail, findings, evidence, tool calls and verification.
- `reviews.py`: review sessions, selections, preview job, preview files, HOLD/GENERATE decision and history.
- `final_packs.py`: read-only published final packs (list, detail, verify, html, pdf, json).
- `monthly.py`: periods, uploads, batches, documents, reconciliation and processing runs, reassessment plan, exception overview, lineage, dashboard and activity. It needs the database (503 `DATABASE_REQUIRED`, `services/monthly.py:94-97`).
- `cases.py`: exception investigation cases. It also needs the database (`services/cases.py:37-40`).
- `deps.py`: `services()` returns the single `Services` object from `app.state`.

### Backend services (`uc042app/services/*`; wiring in `services/__init__.py:44-72`)
- `Services` builds the repositories: SQL when `UC042_DATABASE_URL` is set, otherwise files (lines 49-51). It also builds `StorageLayout`, the job runner and the services listed below. `start()` (lines 86-102) takes the instance lock, marks interrupted jobs and runs, reconciles GENERATING records, runs `monthly.sync_packs()` (registers every verified pack on disk under its period), then starts the thread pool.
- `monthly.py` (`MonthlyService`): periods, upload and validation, duplicate flags, include/exclude decisions, confirmation, processing and reassessment, the baseline, pack publication (write-once), lineage and continuity.
- `packs.py` (`PackService`): verified, cached, read-only loading of `pack.json` (`load`/`peek`/`_verified`, lines 35-61) and views of it (summary, reconciliation, sources, exceptions).
- `investigations.py` (`InvestigationService`): eligibility (library check, then the registry, then the authorisation decision), starting jobs, running `run_investigation` and registering the result.
- `ai_authorization.py` (`AiAuthorizationService`): pre-execution AI authorisations that cannot be changed (`require`, `record`, `refuse`).
- `registry.py` (`PublicationRegistry`): the investigation publication registry, which pins file hashes.
- `reviews.py` (`ReviewService`): the review state machine, selections, readiness, the preview job (AI closing summary) and HOLD/GENERATE.
- `final_packs.py` (`FinalPackService`): final-pack generation records, version numbering over the lineage, publish and verify through the library, and reads.
- `cases.py` (`CaseService`): exception cases with append-only entries, and AI requests made from a case.
- `layout.py` (`StorageLayout`): the storage profiles (see H.5). `locks.py` (`PackLocks`): in-process locks, one per pack.

### Python reconciliation engine
- `uc042lib/validate.py` (1661 lines): `class Validator` (line 72). `Validator.run()` (line 404) runs every control check (C01-C16, DQ*) over one prepared case and produces results, exceptions (IDs `EXC-<scenario>-NN`, line 1302; `status: "OPEN"`, `review_status: "AWAITING_HUMAN_REVIEW"`, lines 1280 and 1293), investigation groups and candidate relationships. `case_status()` (line 1492) gives CLEAN, EVIDENCE_INCOMPLETE or EXCEPTIONS_OPEN. The period comes from `uc042lib/period.py` `PeriodConfig` (line 142), and the policy rules from `uc042lib/policy.py`.
- Case preparation: `uc042lib/prepare.py` `identify()` (line 63) recognises a file by its content. `prepare_case()` (line 104) builds a case folder with `intake.csv`. `selected_policy()` (line 248) picks the governing IN-17 version.
- Pack builder: `uc042lib/pack/generate.py` `build(case_dir, period)` (line 37) is pure (writes nothing). It calls `assemble()` (`pack/assemble.py:67`, which runs `run_engine` (line 61, `Validator.run`)), then `processing_outputs`, then `finalise()` (`assemble.py:388`, which sets the content hash and `pack_id`), then `validate_pack`, then `render_html`. The pack ID is `PACK-<scenario>-<PER-YYYY-MM>-<sha[:12]>` (`pack/model.py:50-51`). The command-line `generate()` (line 61) also publishes, but the backend calls `build()` and publishes the pack itself (`services/monthly.py:897-925`).

### Investigation library (`uc042lib/investigation/*`)
- `graph.py`: a LangGraph `StateGraph` (`build_graph`, line 301). Nodes run in this order: `load_investigation_case`, `identify_investigation_scope`, `route_investigation`, `retrieve_<route>`, `build_evidence_packet`, `ai_investigation`, `validate_findings`, `persist_findings`. `run_investigation()` (line 331) checks the input roots first (`roots.resolve`, `check_pack_id`).
- `packet.py` / `retrieval.py` / `routing.py`: deterministic, hash-checked retrieval of the exception's cited records (`EvidenceStore`), plus the evidence packet.
- `validation.py`: checks the AI output against the evidence (citations and classification).
- `persistence.py`: write-once artefacts. A valid, completed result is written to `investigations/<pack_id>/<exception_id>/<INV-...>/{findings.json, evidence_packet.json, evidence_ledger.json, tool_calls.json, runs/0001.json}`. Anything else goes to `investigations/_not_published/<pack>/<exc>/<ts>-<hash>.json` (`persist`, lines 169-200). `verify_published()` is at line 45.

### Tool-calling orchestration (`uc042lib/investigation/tool_loop.py`, `tools.py`)
- A nested LangGraph subgraph (`build_tool_loop`, line 241; `run_tool_loop`, line 263). The flow is `llm_step`, then `inspect_response`, then either (tool calls) `validate_tool_request`, `execute_tools`, `append_tool_results` and back to `llm_step`, or (final answer) `extract_structured_findings`. Errors and limits go to `controlled_failure`.
- The model only *requests* tools. Python checks each request (registry name, strict Pydantic arguments, budgets, duplicates) and runs it through the guarded `EvidenceStore`. The tools are in `tools.py:323+`: `get_source_record`, `search_bank_entries`, `get_cashbook_entries`, `get_settlement_batch`, `search_customer_transactions`, `get_customer_balance_snapshots`, `get_reconciliation_evidence` and `follow_relationship`.
- Limits (`investigation/config.py:86-89`): 8 tool calls, 4 rounds, 25 records per call, an estimated 150,000 input tokens, and an overall time budget.

### OpenAI Responses API usage (`uc042lib/investigation/llm.py`)
- `OpenAIInvestigator` (line 78) uses `openai.OpenAI(api_key, timeout, max_retries=2)` (line 101), and every call goes through `client.responses.with_raw_response.parse(...)`. Each call sends `store=False` and `text_format=<Pydantic model>` (structured output). It sends `reasoning={"effort": ...}` only when that is set, and never sends temperature or top_p.
  - V2 tool mode: `tool_turn()` (line 201) sends `tools` (strict function tools generated from the Pydantic argument models, lines 191-199), `tool_choice="auto"`, `parallel_tool_calls=True` and `include=["reasoning.encrypted_content"]`, which replays reasoning between rounds without storing it at OpenAI.
  - Fixed mode (V1): `investigate()` (line 152). The backend refuses providers that cannot use tools (`services/investigations.py:236-237`), so it only ever uses tools mode.
  - Closing summary: `structured_request()` (line 239), called by `uc042lib/final_pack/summary.py:211` `generate_closing_summary`.
- Provider and model come from `UC042_LLM_PROVIDER` / `UC042_LLM_MODEL`. The default model is `gpt-6-luna` (`investigation/config.py:35`), and the key comes from `.env`, `OPENAI_API_KEY`. `investigator_from_env()` (line 445) chooses openai, anthropic or offline.
- OpenAI is called **only** inside background jobs: INVESTIGATION jobs and PREVIEW jobs (the closing summary). No request handler calls it directly, and GENERATE reuses the closing summary stored with the preview (`services/reviews.py:369`).

### PostgreSQL
- One database, `uc042` (report 19 §13.2), at `UC042_DATABASE_URL` (driver `postgresql+pg8000`, `uc042app/config.py:22`). It has two schemas: `audit` and `operations` (`uc042app/db/models.py:3-6`). It holds every application record. The deterministic packs, AI artefacts, final packs and uploaded file contents are stored as files, not in the database (see H.4).
- Without a database URL the backend runs with file-based state (`FileRepositories`, `uc042app/repositories/files.py:176-189`). Periods, uploads, runs, cases, activity and lineage are then `None`, and those endpoints return 503 `DATABASE_REQUIRED`.

### SQLAlchemy
- SQLAlchemy 2.x declarative models (`uc042app/db/models.py`). JSON columns use `JSONB` on PostgreSQL (line 22). The engine and session factory are in `uc042app/db/__init__.py:20-30`, with `pool_pre_ping`. The repositories are in `uc042app/db/repositories.py`, and `SqlRepositories` (line 488) gathers 12 of them. Optimistic concurrency uses a `revision` value on review sessions and cases.
- SQLite is allowed only in tests, where `schema_translate_map` folds both schemas into one (`db/__init__.py:22-25`).

### Alembic (`uc042app/db/migrations/versions/`)
- `check_schema()` (`db/__init__.py:47-56`) **refuses to start** the backend if the database is not at head. The fix is `python -m uc042app.admin db-upgrade` (`admin.py:242`).
- **0001_initial**: creates 12 tables in `public`: `activity_events`, `final_pack_records`, `investigation_registry`, `jobs`, `reconciliation_periods`, `review_sessions`, `period_packs`, `previews`, `review_decisions`, `upload_batches`, `processing_runs`, `source_documents` (lines 19-151).
- **0002_title_submissions**: additive. Adds `reconciliation_periods.title` and `source_documents.submission_kind`, `submission_reason` and `replaces_document_id` (lines 23-26).
- **0003_unified_schemas**: creates the `audit` and `operations` schemas and moves the 12 tables into them with `SET SCHEMA` (`OWNERSHIP`, lines 24-28). It adds `reconciliation_periods.storage_profile` (line 43), two foreign keys (lines 45 and 47), two indexes (lines 49-50) and four new tables: `operations.exception_cases`, `operations.exception_case_entries`, `audit.record_provenance` and `audit.investigation_authorizations` (lines 29-30 and 52-90). Downgrade refuses while the new data exists.
- **0004_ai_authorization_lineage** (file `0004_ai_authorization_and_lineage.py`): adds `audit.ai_execution_authorizations` (lines 36-49) and `audit.pack_lineage` (lines 54-67). On PostgreSQL it also adds a PL/pgSQL trigger, `ai_execution_authorizations_immutable`, that refuses UPDATE and DELETE (lines 68-76). Downgrade refuses while either table holds rows (lines 79-84). **It has not been applied to the live `uc042` database.** Because of `check_schema`, the current code will not start against that database until `db-upgrade` is run. Report 20 says the upgrade was tested on restored copies (`uc042_phase8_perf`, `uc042_audit19`, report 20 lines 274 and 377), and line 30 says the live database was "Not migrated, by choice". I did not run it.

### Background jobs (`uc042app/jobs/__init__.py`)
- `JobRunner` (line 29) is a `ThreadPoolExecutor` inside the one backend process (`UC042_JOB_WORKERS`, 1-8, default 2). Every state change is saved: QUEUED, then RUNNING, then COMPLETED or FAILED, or INTERRUPTED. The three operations are `INVESTIGATION`, `PREVIEW` and `PROCESSING`.
- `create()` (line 57) and `submit()` (line 63) record the job; `_run()` (lines 71-78) runs it with each job's failure kept separate. At startup `recover()` (lines 36-44) marks any QUEUED or RUNNING jobs as INTERRUPTED. They are never re-run automatically, so OpenAI calls are not repeated. `active()` (line 87) enforces "one active job per exception".

### File storage (`uc042app/storage/__init__.py`, `uc042app/ingest/store.py`)
- `storage/__init__.py`: atomic JSON writes (`atomic_write_json`, line 28; `create_json`, line 44, which refuses to overwrite) and `InstanceLock` (line 109), an OS lock on `<state_dir>/instance.lock` that stops a second backend process from starting.
- `ingest/store.py` `DocumentStore`: write-once, content-addressed originals at `objects/<sha[:2]>/<sha256>` (`put`, line 48). Storage references are `object:<sha>` or `dataset:<dataset>/<source_data|supporting_documents>/...` (`path`, line 72). `read()` (line 84) re-checks the SHA-256 every time. `cases_root` (line 40) is `<store>/cases`. Processing case folders are named `SET-<hash16>`, where the hash covers the period and the document-set hashes (`services/monthly.py:767-768`). The `cases/<run_id>` in the module's docstring is out of date.

### Publication registries
1. **Investigation publication registry**: `audit.investigation_registry`, or `app_state/registry/investigation_registry.json` without a database. Written by `PublicationRegistry.register_new` (`services/registry.py:120`) after a job publishes a result. It pins `findings_sha256`, the packet and ledger file hashes, the pack hash and the schema and prompt versions (`PINNED`). An investigation is eligible only if the files still match (`check`, line 128). A damaged registry blocks everything (`REGISTRY_UNREADABLE`, line 91).
2. **Investigation authorisation decisions**: `audit.investigation_authorizations`, append-only, APPROVED or AUTHORIZATION_DISCREPANCY. The newest row for an investigation applies (`services/investigations.py:42-74`). Written by the admin command `record-investigation-authorization` (`admin.py:262`).
3. **Pre-execution AI authorisations**: `audit.ai_execution_authorizations` (0004), which cannot be changed. Written by `AiAuthorizationService.record` (`services/ai_authorization.py:72`).
4. **Period/pack registration**: `audit.period_packs`, written by `sync_packs` (`services/monthly.py:983`) and `_process` (line 806).
5. **Final-pack publication**: the files themselves (`final_packs/<FAP-...>/manifest.json` with each file's SHA-256 and the generation record), plus `audit.final_pack_records` (one per GENERATE decision).

---

## H.2 Complete endpoint table

Notes on the columns:
- "Router fn" gives the router file and line. "Service" gives the method and its line.
- "DB?" means writes to PostgreSQL. With no database configured, jobs, reviews, registry, final_pack_records and AI authorisations are written to app_state files instead.
- Every `/api/v1/periods*`, `/uploads*`, `/documents*`, `/processing-runs*`, `/dashboard`, `/activity` and `/cases*` endpoint returns 503 `DATABASE_REQUIRED` when there is no database.

| METHOD path | Router fn | Service method | Writes DB? | Writes files? | Starts job? | Calls OpenAI? |
|---|---|---|---|---|---|---|
| GET /health | system.py:28 `get_health` | `Services.storage_ok/database_ok`, `registry.problems` | no | temp probe file in state_dir (created and deleted) | no | no |
| GET /api/v1/packs | packs.py:11 `list_packs` | `PackService.pack_ids/summary_of` (packs.py:28,44) | no | no | no | no |
| GET /api/v1/packs/{pack_id} | packs.py:22 `get_pack` | `PackService.load/summary` (35,109) | no | no | no | no |
| GET /api/v1/packs/{pack_id}/reconciliation | packs.py:30 | `PackService.reconciliation` (82) | no | no | no | no |
| GET /api/v1/packs/{pack_id}/sources | packs.py:36 | `PackService.sources` (91) | no | no | no | no |
| GET /api/v1/packs/{pack_id}/exceptions | packs.py:41 | `PackService.exception_view` (120) | no | no | no | no |
| GET /api/v1/packs/{pack_id}/exceptions/{exception_id} | packs.py:47 | `PackService.exception/affected_results`, `InvestigationService.for_exception` (123) | no | no | no | no |
| GET /api/v1/packs/{pack_id}/investigations | investigations.py:15 | `InvestigationService.for_pack` (130) | no | no | no | no |
| GET /api/v1/packs/{p}/exceptions/{e}/investigations | investigations.py:21 | `for_exception` (123) | no | no | no | no |
| POST /api/v1/packs/{p}/exceptions/{e}/investigations | investigations.py:27 `start_investigation` | `InvestigationService.start` (240) | yes: operations.jobs, audit.ai_execution_authorizations (also on refusal), operations.activity_events; on completion the job adds audit.investigation_registry | job writes investigations/<pack>/<exc>/<INV>/... or _not_published/... | yes, INVESTIGATION | yes, inside the job (tool loop, Responses API) |
| GET /api/v1/packs/{p}/exceptions/{e}/source-evidence | investigations.py:36 | `InvestigationService.source_evidence` (186) | no | no | no | no |
| GET /api/v1/ai/configuration | investigations.py:43 | `AiAuthorizationService.configuration` (43) | no | no | no | no |
| GET /api/v1/ai/confirmations | investigations.py:49 | `AiAuthorizationService.list` (103) | no | no | no | no |
| GET /api/v1/ai/confirmations/{id} | investigations.py:59 | `AiAuthorizationService.get` (106) | no | no | no | no |
| GET /api/v1/jobs/{job_id} | investigations.py:64 `get_job` | `runner.repo.get` + `job_view` (223) | no | no | no | no |
| GET /api/v1/investigations/{id} | investigations.py:72 | `InvestigationService.detail` (137) | no | no | no | no |
| GET /api/v1/investigations/{id}/findings | investigations.py:78 | `findings` (158) | no | no | no | no |
| GET /api/v1/investigations/{id}/evidence | investigations.py:83 | `evidence` (162) | no | no | no | no |
| GET /api/v1/investigations/{id}/tool-calls | investigations.py:90 | `tool_calls` (178) | no | no | no | no |
| GET /api/v1/investigations/{id}/verify | investigations.py:96 | `verify` (208) | no | no | no | no |
| GET /api/v1/reviews | reviews.py:29 | `ReviewService.list` (391) | no | no | no | no |
| POST /api/v1/packs/{pack_id}/reviews | reviews.py:35 `open_review` | `ReviewService.open` (70) | yes: audit.review_sessions, activity | no | no | no |
| GET /api/v1/reviews/{review_id} | reviews.py:43 | `get` (57), `readiness` (145), `preview_meta` (297) | no | no | no | no |
| PATCH /api/v1/reviews/{id}/selections | reviews.py:48 | `set_selections` (98) | yes: review_sessions, activity | no | no | no |
| POST /api/v1/reviews/{id}/preview | reviews.py:55 `request_preview` | `ReviewService.request_preview` (213); job `_build_preview` (260) | yes: jobs, ai_execution_authorizations (also on refusal), review_sessions, activity; the job adds audit.previews (meta and document) | no (the preview is stored in the database, never published) | yes, PREVIEW | yes, inside the job (closing summary via `structured_request`), only if a live provider is configured; otherwise the summary is UNAVAILABLE |
| GET /api/v1/reviews/{id}/preview | reviews.py:62 | `ReviewService.preview` (303) | no | no | no | no |
| GET /api/v1/reviews/{id}/preview/{html,pdf,json} | reviews.py:68 | `preview` (303) + `render_html/render_pdf` | no | no | no | no |
| POST /api/v1/reviews/{id}/decision | reviews.py:84 `decide` | `ReviewService.decide` (311) → `_hold` (336) / `_generate` (348) → `FinalPackService.generate` (final_packs.py:68) | yes: audit.review_decisions, review_sessions, activity; GENERATE also writes audit.final_pack_records | GENERATE: final_packs/<FAP>/{final_pack.json, report.html, report.pdf, manifest.json} | no (GENERATE runs inside the request) | no (reuses the stored summary) |
| GET /api/v1/reviews/{id}/history | reviews.py:93 | `history` (406) | no | no | no | no |
| GET /api/v1/final-packs | final_packs.py:13 | `FinalPackService.list` (118) | no | no | no | no |
| GET /api/v1/final-packs/{id} | final_packs.py:19 | `detail` (139) | no | no | no | no |
| GET /api/v1/final-packs/{id}/verify | final_packs.py:24 | `verify` (152) | no | no | no | no |
| GET /api/v1/final-packs/{id}/{html,pdf,json} | final_packs.py:39/44/49 | `file` (156) | no | no | no | no |
| GET /api/v1/periods | monthly.py:170 | `MonthlyService.periods` (155) + `period_view` (router line 110) | no | no | no | no |
| POST /api/v1/periods | monthly.py:177 `create_period` | `create_period` (121) | yes: audit.reconciliation_periods, activity | no | no | no |
| PATCH /api/v1/periods/{id} | monthly.py:186 | `rename_period` (140) | yes: reconciliation_periods, activity | no | no | no |
| GET /api/v1/periods/{id} | monthly.py:192 | `period_detail` (159) | no | no | no | no |
| POST /api/v1/periods/{id}/uploads | monthly.py:200 `upload` | `MonthlyService.upload` (341) | yes: operations.upload_batches, operations.source_documents, reconciliation_periods.status, activity | document_store/objects/<sha> | no | no |
| GET /api/v1/uploads/{batch_id} | monthly.py:214 | `batch_detail` (578) | no | no | no | no |
| POST /api/v1/uploads/{batch_id}/confirm | monthly.py:219 | `confirm` (623) | yes: upload_batches, activity | no | no | no |
| POST /api/v1/uploads/{batch_id}/process | monthly.py:225 | `process` (678); job `_execute` (736) / `_process` (756) | yes: audit.processing_runs, jobs, upload_batches, reconciliation_periods, activity; the job adds audit.period_packs and audit.pack_lineage (reassessment only) | job: document_store/cases/SET-*/ and packs/<PACK-...>/ (primary packs root) | yes, PROCESSING | no |
| POST /api/v1/periods/{id}/reconciliation | monthly.py:231 `reconcile` | `reconcile` (653) → `process` (678) | as for /process | as for /process | yes, PROCESSING | no |
| GET /api/v1/periods/{id}/reassessment | monthly.py:242 | `reassessment_plan` (279) | no | no (reads and hashes baseline files) | no | no |
| GET /api/v1/periods/{id}/exception-overview | monthly.py:250 | `PackService.peek` + `for_pack` | no | no | no | no |
| GET /api/v1/periods/{id}/lineage | monthly.py:268 | `repos.lineage.list` | no | no | no | no |
| GET /api/v1/dashboard | monthly.py:276 `dashboard` | `period_view`, `final_packs.list`, `reviews.list` | no | no | no | no |
| GET /api/v1/documents/{id} | monthly.py:304 | `document` (587) | no | no | no | no |
| GET /api/v1/documents/{id}/content | monthly.py:309 | `document_content` (595) | no | no | no | no |
| POST /api/v1/documents/{id}/review | monthly.py:318 | `review_document` (602) | yes: source_documents, upload_batches.summary, activity | no | no | no |
| GET /api/v1/processing-runs/{run_id} | monthly.py:324 | `run` (728) | no | no | no | no |
| GET /api/v1/activity | monthly.py:329 | `repos.activity.recent` | no | no | no | no |
| POST /api/v1/packs/{p}/exceptions/{e}/case | cases.py:13 `open_case` | `CaseService.open` (57) | yes: operations.exception_cases, activity | no | no | no |
| GET /api/v1/cases | cases.py:22 | `CaseService.list` (80) | no | no | no | no |
| GET /api/v1/cases/{case_id} | cases.py:28 | `CaseService.view` (86) | no | no | no | no |
| POST /api/v1/cases/{case_id}/entries | cases.py:33 | `CaseService.add_entry` (135) | yes: operations.exception_case_entries, exception_cases (revision, resolution, status), activity | no | no | no |
| POST /api/v1/cases/{case_id}/ai-investigation | cases.py:40 `request_ai` | `CaseService.request_ai` (170) → `InvestigationService.start` (240) | as for POST investigations, plus an AI_REQUEST case entry | as for POST investigations | yes, INVESTIGATION | yes, inside the job |

Total: 58 route functions. The final-pack html/pdf/json routes are three functions shown in one row; preview/{kind} is a single function. FastAPI also serves its own `/docs` and `/openapi.json` pages; they are not app endpoints. The only startup-time database write that is not triggered by a request is `Services.start()` → `monthly.sync_packs()` (`services/__init__.py:94`), which registers verified packs found on disk in `audit.period_packs` (plus a period row if needed).

---

## H.3 Five end-to-end request traces

### (a) Opening the dashboard (`/`)
1. **Screen**: `DashboardPage` (`frontend/src/pages/DashboardPage.tsx:125`) calls `useApi(() => data.periods())`, `data.finalPacks()`, `data.reviews()` and `data.activity()` (lines 131-134). When a period is selected it also calls `data.dashboard(selected)` (line 137). `AppShell` also calls `data.periods()` and `data.health()` (`components/layout/AppShell.tsx:61-62`), and these share the 10 s cache.
2. **DataSource**: `apiSource.ts:78-81`. `periods()` goes through `cached("periods")`, which runs `api.periods()` and `packs()` (cached "packs") in parallel and then `buildArchivePeriods` (`data/periods.ts:42`). `dashboard` is `api.dashboard` (line 97) and is not cached.
3. **API client**: `endpoints.ts:19` `GET /api/v1/periods`, `endpoints.ts:52` `GET /api/v1/packs`, `endpoints.ts:48` `GET /api/v1/dashboard?period_id=PER-YYYY-MM`. All go through `client.ts:46` `request()`, which calls `fetch` (line 54).
4. **HTTP to FastAPI**: the loopback check in `main.py:48-57`, then the router `monthly.py:276` `dashboard()`.
5. **Router to services**: `_monthly(svc)` (monthly.py:161) checks the database. `_finals_by_pack` (line 30) calls `FinalPackService.list()` (final_packs.py:118), which walks every final-packs root (`_published`, line 40, the library's `list_final_packs`). `svc.reviews.list()` (reviews.py:391). `period_view()` (monthly.py:110) calls `repos.uploads.batches/documents`, `repos.runs.list` and `_pack_refs` (line 86). `_pack_refs` uses `repos.lineage.list` (audit.pack_lineage), `repos.periods.packs` (audit.period_packs), `PackService.peek()` (packs.py:39) and `_investigation_counts` (line 48), which calls `InvestigationService.for_pack` (investigations.py:130).
6. **Python functions**: `PackService._verified` (packs.py:47) calls `layout.for_pack` (layout.py:78), then `load_pack` (full verification of `pack.json`: identity, content hash and schema), and caches the result by mtime and size. `InvestigationService.published` (line 91) calls the library's `list_investigations`, `registry.check` and `authorization` (cached by a signature).
7. **Storage**: PostgreSQL `audit.reconciliation_periods`, `period_packs`, `processing_runs`, `pack_lineage`, `review_sessions`, `review_decisions`, `final_pack_records`, `investigation_registry`, `investigation_authorizations`, and `operations.upload_batches`, `source_documents`, `jobs`. Files: `packs/*/pack.json`, `demo_history/packs/*/pack.json`, `investigations/**`, `final_packs/*/manifest.json` and `demo_history/final_packs/*`.
8. **Response**: `DashboardSummary` JSON (monthly.py:293-301) with counts for the selected period and global totals labelled as global.
9. **Screen**: KPI tiles, the period list, pending reviews and activity, rendered from the `useApi` states.

### (b) Uploading documents to a period
1. **Screen**: `UploadPage` `submit()` (`pages/UploadPage.tsx:45-55`). If the month has no archive record yet, it first calls `data.openPeriod(year, month)` (line 50, `POST /api/v1/periods`). It then calls `data.uploadDocuments(period_id, files, submission?)` (line 51). The monthly report's "add evidence" form uses the same call (`ReportPages.tsx:537`).
2. **DataSource**: `apiSource.ts:86` `uploadDocuments: change(api.upload)`, so the cache is cleared afterwards.
3. **API client**: `endpoints.ts:24-33` builds `FormData` (fields `files`, plus `submission_kind`, `reason` and `replaces_document_id` when given) and sends `POST /api/v1/periods/{id}/uploads` with the 180 s timeout.
4. **Router**: `monthly.py:200-211` `upload()` reads each file up to `MAX_FILE_BYTES + 1` (line 208), works out which final packs have already been published for the period (line 210), and calls `MonthlyService.upload`.
5. **Service**: `services/monthly.py:341-390`:
   - checks `_require` and `_period` (lines 94-107), then `_submission` (line 322) and the file count and size limits (lines 351-355);
   - for each file: `self.store.put(data)` (line 361, `ingest/store.py:48`) writes the file to `objects/<sha[:2]>/<sha>`;
   - `A.analyse_file()` (line 363, `ingest/analysis.py:277`) identifies the file by its content with `prepare.identify` (prepare.py:63) and analyses its dates and keys;
   - `_submission_checks` (line 393), `_resolve_letters` (line 440), `_duplicates` (line 494), and `status_of` for each document (line 377).
6. **PostgreSQL**: `repos.uploads.create_batch` (line 384, `db/repositories.py:278`) inserts into `operations.upload_batches` and `operations.source_documents`. `_summarise` (line 551) then updates the batch's `summary` and `validation_status`. The period status changes from EMPTY to DOCUMENTS_UPLOADED (line 387). The activity row `DOCUMENTS_UPLOADED` is written to `operations.activity_events` (line 388).
7. **Response**: `BatchDetail` (batch, its documents and their runs). `document_view` (router line 24) removes `storage_ref` and adds `storage_kind`.
8. **Screen**: navigates to `/uploads/{batch_id}` (`UploadPage.tsx:53`), where `BatchPage` (`pages/ArchivePages.tsx`) shows the checks and the include/exclude controls (`components/upload/documents.tsx:58`).

### (c) Processing a confirmed batch into a deterministic pack
1. **Screen**: `BatchPage` (`pages/ArchivePages.tsx:60`) has the "Start processing" button, which calls `data.processBatch(batch_id)`. The button is disabled when processing is not supported for the month, when required evidence is missing, when a run is active, or when the period has a published final pack (lines 52-62).
2. **DataSource**: `apiSource.ts:90` `change(api.processBatch)`. **API client**: `endpoints.ts:36` `POST /api/v1/uploads/{batch_id}/process`.
3. **Router**: `monthly.py:225-228` `process()` calls `MonthlyService.process(batch_id)`.
4. **Service, during the request**: `services/monthly.py:678-726` takes `self._lock`, checks the batch is not still VALIDATED and that no run is active, raises `REASSESSMENT_REQUIRED` if a final pack exists, builds `current_set` (line 176), checks the required IDs (`INCOMPLETE`), and builds the run record `RUN-<24hex>`. It then calls `runner.create("PROCESSING")` (jobs:57) and `repos.runs.create` (audit.processing_runs), sets the batch status to PROCESSING and the period status to PROCESSING (lines 719-720), and calls `runner.submit(job, self._execute)` (line 721).
5. **Response 202**: the `ProcessingRun` (status QUEUED, `job_id`). The screen polls the job with `useJobPoller(active?.job_id)` (`ArchivePages.tsx:32`), which calls `GET /api/v1/jobs/{id}`.
6. **Background job**: `jobs._run` (jobs:71) calls `_execute` (monthly.py:736), which calls `_process` (line 756):
   - computes the `SET-<hash>` case folder name (lines 763-768);
   - reads each document back from the store with a SHA re-check (`store.read`, line 780) into a temporary folder;
   - calls `prepare_case(work, staging/"case", period)` (line 785, `prepare.py:104`) and moves the result into `document_store/cases/SET-*` with `os.replace` (line 786);
   - stops if any intake decision is blocking (lines 791-795);
   - calls `selected_policy`, then `build(case_dir, period)` (line 800, `pack/generate.py:37`), which runs `Validator.run` (validate.py:404) and then assembles, validates and renders the pack;
   - `_publish` (line 897) writes `pack.json`, `pack.html`, `processing/*.csv` and `generations/0001.json` into `<UC042_PACKS_ROOT>/<PACK-...>/` in a single atomic step that never overwrites;
   - `packs.load(pack_id)` (line 805) re-verifies the published pack;
   - `repos.periods.add_pack` (line 806) writes audit.period_packs, `_record_lineage` (line 816) writes audit.pack_lineage for REASSESSMENT runs only, and `_continuity` (line 874) runs.
7. **Final updates**: `_execute` sets `processing_runs.status` to SUCCEEDED or FAILED with the result, the batch to PROCESSED or PROCESSING_FAILED, and the period to PROCESSED or PROCESSING_FAILED (lines 746-750). The activity row is `PROCESSING_SUCCEEDED/FAILED`. The job ends COMPLETED or FAILED.
8. **Screen**: when the job ends, `reload()` runs, and the cache is cleared by `apiSource.job` (line 70). The new pack then appears under the period.

### (d) Starting an AI investigation
1. **Screen**: the `AiPanel` "Run AI investigation" button (`components/workspace/AiPanel.tsx`) opens `AiAuthorizationDialog` (`components/ai/AiAuthorizationDialog.tsx`), which loads `GET /ai/configuration` and, when the analyst confirms, calls `onConfirm({confirmed: true, provider, model})` (line 38). `run()` (AiPanel.tsx:53-63) then calls `data.startInvestigation(packId, exceptionId, authorization, retryOf)` (line 56). The same thing happens from a case through `data.caseAi` (`pages/CasePages.tsx:170`).
2. **DataSource**: `apiSource.ts:106` `change(api.startInvestigation)`. **API client**: `endpoints.ts:64-67` sends `POST /api/v1/packs/{p}/exceptions/{e}/investigations` with body `{mode: "tools", authorization, retry_of?}`.
3. **Router**: `investigations.py:27-33` calls `InvestigationService.start(pack_id, exception_id, retry_of, confirmation)`.
4. **Service** (`services/investigations.py:240-278`), under `locks.hold(pack_id)`:
   - `packs.load` and `packs.exception`;
   - `auth.require(INVESTIGATION, confirmation)` (ai_authorization.py:58) raises 422 `AUTHORIZATION_REQUIRED` if the confirmation is missing, or refuses with 409 `AI_CONFIGURATION_CHANGED` if the provider or model changed;
   - if a job for this exception is already active: refusal 409 `INVESTIGATION_ACTIVE`, which is recorded;
   - `_investigator()` (line 228) raises 503 `PROVIDER_NOT_CONFIGURED` or 422 `MODE_UNSUPPORTED`, also recorded;
   - `runner.create("INVESTIGATION")`, then `auth.record(..., AUTHORIZED, job_id, authorization_id=AIA-...)` (ai_authorization.py:72), which inserts into `audit.ai_execution_authorizations` and the activity log. If that write fails, the job is marked FAILED and never runs (lines 273-276).
   - `runner.submit(job, _execute)`.
5. **Response 202**: the `Job` (status QUEUED) with its `authorization_id`. The screen calls `useJobPoller(jobId)` (AiPanel.tsx:48).
6. **Background job**: `_execute` (investigations.py:290) calls `run_investigation(pack_id, exception_id, investigator, packs_root=<the pack's root set>, datasets_root=datasets_root_for(...), investigations_root=<the same set>, mode="tools")` (`uc042lib/investigation/graph.py:331`). The graph runs retrieval (hash-checked), builds the packet, then runs `_tools_investigation` (graph.py:150) and `run_tool_loop` (tool_loop.py:263). That loop makes repeated `OpenAIInvestigator.tool_turn` calls (llm.py:201), each one `client.responses.parse` with `store=False`, until it returns a final result. `validate_findings` then runs, and `persist_findings` (graph.py:262) calls `persist` (persistence.py:169), which writes to `investigations/<pack>/<exc>/<INV-...>/` or `_not_published/`.
7. **Registration**: if the result was PUBLISHED or ALREADY_PUBLISHED_IDENTICAL, `registry.register_new` (registry.py:120) writes `audit.investigation_registry`. The job ends COMPLETED; otherwise FAILED with an error summary that has paths removed and secrets redacted.
8. **Screen**: when the job ends, `onFinished` reloads the exception's investigations through `GET .../investigations`, which shows them with their eligibility.

### (e) GENERATE of a final pack
1. **Screen**: `ReviewPage` (`pages/ReviewPages.tsx`). Before GENERATE is possible, the preview job must have been run (`data.requestPreview`, line 128, through the AI dialog). The decision panel (`components/review/decision.tsx:23-41`) calls `data.decide(review_id, {decision: "GENERATE", comment, snapshot_sha256: preview.snapshot_sha256, acknowledgement_accepted: ack, acknowledged_summary_unavailable})` (line 28). The button is enabled only when there is a preview, the acknowledgement is ticked, and `readiness.ready` is true (line 22).
2. **DataSource**: `apiSource.ts:130` `change(api.decide)`. **API client**: `endpoints.ts:135-138` sends `POST /api/v1/reviews/{id}/decision` with the 180 s timeout.
3. **Router**: `reviews.py:84-90` calls `ReviewService.decide(review_id, body)`.
4. **Service** (`services/reviews.py:311-324`): takes `locks.hold(pack_id, timeout=0, busy_code="GENERATION_IN_PROGRESS")`, refuses if the session is GENERATING or GENERATED, then calls `_generate` (line 348):
   - checks there is a preview (`PREVIEW_REQUIRED`), that the snapshot hash matches (`PREVIEW_STALE`), the acknowledgement (`ACKNOWLEDGEMENT_REQUIRED`) and the unavailable-summary acknowledgement (`SUMMARY_UNAVAILABLE_ACK_REQUIRED`);
   - compares the inputs fingerprint (`PREVIEW_STALE`), checks the readiness blockers (`BLOCKED`), rebuilds the snapshot with `_snapshot` (line 188, `build_review_snapshot` in the pack's own root set) and requires the same hash;
   - `repo.append_decision` writes audit.review_decisions, and `_save(status="GENERATING")` writes audit.review_sessions;
   - calls `final_packs.generate(snapshot, summary, review)` (line 380).
5. **FinalPackService.generate** (`services/final_packs.py:68-92`):
   - `next_version` (line 60) numbers the version over the lineage;
   - `records.create` writes audit.final_pack_records with status GENERATING;
   - `assemble_final_pack` (`uc042lib/final_pack/assemble.py:224`), then `publish_final_pack(final, root_for(pack_id), expected=(version, supersedes))` (`final_pack/persistence.py:67`). This stages `final_pack.json`, `report.html`, `report.pdf` and `manifest.json` and renames them into `<final_packs_root>/FAP-...` in one step;
   - `verify_final_pack(path)`;
   - the record is updated to GENERATED with `final_pack_id` and its hash. On any failure it becomes GENERATION_FAILED, nothing is published, and the request returns HTTP 500 `GENERATION_FAILED`.
6. **Back in reviews**: `_save(status="GENERATED", final_pack_id)` and the activity row `REVIEW_GENERATED`.
7. **Response 201**: `DecisionResponse {decision, session_status, final_pack}`.
8. **Screen**: `onDecided(r)` shows the result and links to `/final-packs/{FAP-...}`. That page (`FinalPackPages.tsx:48-51`) calls `GET /final-packs/{id}/verify` and `GET /final-packs?pack_id=..&lineage=true`.

---

## H.4 What PostgreSQL stores and what is kept as files

### PostgreSQL, schema `audit` (`uc042app/db/models.py`)

| Table (model line) | Main columns | Written by |
|---|---|---|
| reconciliation_periods (32) | period_id PK (PER-YYYY-MM), use_case, year, month, status (EMPTY / DOCUMENTS_UPLOADED / PROCESSING / PROCESSED / PROCESSING_FAILED), created_at, last_processed_at, note, title, storage_profile ("" or `historical-demo`) | MonthlyService.create_period / rename_period / upload / process / _execute / recover / sync_packs; unify.py (migration of data) |
| period_packs (49) | (period_id, pack_id) PK, origin (POC_SCENARIO / UPLOAD_PROCESSING), scenario_id, dataset, processing_run_id FK, pack_content_sha256, registered_at | MonthlyService._process (monthly.py:806), sync_packs (983) |
| processing_runs (63) | run_id PK (RUN-24hex), period_id FK, batch_id FK, job_id, status, started_at, completed_at, error, result JSON (document_set, purpose, reason, predecessor_pack_id, baseline, pack_id, outcome, intake, continuity, lineage), created_at, created_by | MonthlyService.process / _execute / recover |
| review_sessions (142) | review_id PK, pack_id, status, revision, created_at, data JSON (the whole session: selections, selections_version, current_preview_id, preview_job_id, final_pack_id, last_decision_id) | ReviewService.open / set_selections / request_preview / _build_preview / _hold / _generate / recover |
| review_decisions (153) | review_decision_id PK (RD-), review_id FK, seq, decided_at, data JSON (decision, reviewer, comment, acknowledgement, snapshot_sha256, preview_id, closing_summary_sha256). Append-only | ReviewService._hold / _generate |
| previews (164) | preview_id PK (PV-), review_id FK, meta JSON (snapshot hash, fingerprint, closing-summary record), document JSON (the whole preview document). Write-once | ReviewService._build_preview (job) |
| final_pack_records (174) | review_decision_id PK, review_id, pack_id, status (GENERATING / GENERATED / GENERATION_FAILED), created_at, data JSON (version, supersedes, final_pack_id, final_content_sha256, error_summary) | FinalPackService.generate / recover |
| investigation_registry (185) | seq PK, investigation_id, record_type (NEW_PUBLICATION / LEGACY_BASELINE_IMPORT), recorded_at, data JSON (pinned hashes) | PublicationRegistry.register_new / import_legacy (admin `import-legacy-investigations`) |
| investigation_authorizations (196) | id, investigation_id, status (APPROVED / AUTHORIZATION_DISCREPANCY), basis, recorded_at, recorded_by | admin `record-investigation-authorization`; unify.py |
| ai_execution_authorizations (211; migration 0004) | authorization_id (AIA-) unique, operation (INVESTIGATION / CLOSING_SUMMARY), result (AUTHORIZED / REFUSED_<code>), period_id, pack_id, exception_id, review_id, case_id, job_id, provider, model, authorized_by, authorized_at, details JSON. UPDATE and DELETE are blocked by a trigger | AiAuthorizationService.record / refuse |
| pack_lineage (235; migration 0004) | pack_id PK, period_id FK, predecessor_pack_id, lineage_root_pack_id, purpose (REASSESSMENT), processing_run_id FK, reason, change_summary JSON, recorded_at, recorded_by | MonthlyService._record_lineage (monthly.py:816) |
| record_provenance (252) | migration_id, source_database / table / key, target table / key, action (COPIED / MERGED / RENUMBERED), source_row JSON | `uc042app/db/unify.py` (admin `unify-databases`) |

### PostgreSQL, schema `operations`

| Table | Main columns | Written by |
|---|---|---|
| upload_batches (81) | batch_id PK (UPL-), period_id FK, origin (UPLOAD / POC_DATASET_IMPORT), created_at/by, file_count, validation_status (VALID / WARNINGS / INCOMPLETE / INVALID), status (VALIDATED / CONFIRMED / PROCESSING / PROCESSED / PROCESSING_FAILED / ARCHIVED_SCENARIO), summary JSON, error, confirmed_at/by | MonthlyService.upload / _summarise / confirm / process / _execute / recover / import_poc_documents |
| source_documents (98) | document_id PK (DOC-), batch_id FK, original_filename, evidence_id (IN-01..IN-19), category, file_format (CSV / PDF / OTHER), size_bytes, sha256, reporting_period, date_from/to, record_count, validation_status (VALID / WARNING / ERROR), checks JSON (messages, dates, period, key details, policy, decision_required), storage_ref, created_at, review_decision (INCLUDE / EXCLUDE), review_comment, reviewed_at/by, submission_kind, submission_reason, replaces_document_id FK | MonthlyService.upload / review_document / import_poc_documents |
| jobs (130) | job_id PK (JOB-), operation, pack_id (for PROCESSING this holds the period ID; see `monthly.py:715`), exception_id, status, submitted_at, data JSON (the whole job record: inputs incl. authorization_id, result, error_summary, retry_of) | JobRunner.create / _run / recover / shutdown; services that mark a job FAILED |
| exception_cases (269) | case_id PK (CASE-), period_id FK, pack_id, exception_id (unique together with pack_id), status (OPEN / CLOSED), human_resolution (UNRESOLVED / EXPLAINED_BY_ANALYST / ESCALATED), revision, created_at/by, updated_at | CaseService.open / add_entry (via append_entry) |
| exception_case_entries (286) | entry_id PK (CE-), case_id FK, seq, kind, text, evidence_refs JSON, details JSON, created_at/by. Append-only | CaseService.add_entry / request_ai |
| activity_events (302) | id, at, actor, action, entity_type, entity_id, details JSON | every service's `_activity`; AiAuthorizationService.record |

Without a database, `FileRepositories` (`repositories/files.py:1-6, 176-189`) store jobs, reviews (session.json, decisions.jsonl, previews), final_pack_records, the registry and AI authorisations under `app_state/`. Periods, uploads, runs, cases, lineage and activity are then unavailable.

### Actual files and where they live

| What | Location | Writer |
|---|---|---|
| Deterministic packs (pack.json, pack.html, processing/*.csv, generations/*.json) | primary `UC042_PACKS_ROOT` (default `uc042/packs/`, 9 September scenario packs); historical-demo `demo_history/packs/` (8 Jan-Aug packs) | `MonthlyService._publish` (always the primary root, `monthly.py:899`); the CLI `pack/generate.py`; `tools/build_demo_history.py` (historical months) |
| Source datasets (source_data/*.csv, supporting_documents/*.pdf) | `uc042_dataset/` (primary) and `demo_history/datasets/` | build tools only; read-only for the app |
| AI investigation artefacts | `investigations/<pack>/<exc>/<INV>/...` and `investigations/_not_published/...` (primary); `demo_history/investigations/` (historical-demo) | `uc042lib/investigation/persistence.persist`, run from the INVESTIGATION job |
| Final audit packs (final_pack.json, report.html, report.pdf, manifest.json) | `UC042_FINAL_PACKS_ROOT` (default `uc042/final_packs/`, not present in the current tree); `demo_history/final_packs/` (currently FAP-H202602-PER-2026-02-v1-...) | `final_pack/persistence.publish_final_pack`, run during GENERATE |
| Uploaded originals | `<UC042_DOCUMENT_STORE>/objects/<sha[:2]>/<sha256>`; live setting `%USERPROFILE%\uc042_runtime\document_store` (report 19 §13.2) | `DocumentStore.put` |
| Processing case folders | `<document store>/cases/SET-<hash16>/` (prepared case with intake.csv) | `MonthlyService._process` |
| Application state dir | `UC042_APP_STATE_DIR` (live: `%USERPROFILE%\uc042_runtime\app_state`): `instance.lock`, the health probe file, and all file-backed repositories when there is no database | `InstanceLock`, `FileRepositories` |

**Why the split.** PostgreSQL holds the workflow records, which change and must be queried, kept consistent with each other and audited: statuses, decisions, append-only histories and authorisations. The evidence-grade artefacts are files: the packs, investigation outputs, final packs and uploaded originals. Each is write-once, addressed by its content and given its own SHA-256 or manifest, and is checked again on every read (for example `PackService._verified` and `final_packs.file`, final_packs.py:156-166). This keeps them independent of the database and portable as audit evidence, and `models.py:10-14` says so explicitly. The database stores only IDs and hashes that point to these files (`period_packs.pack_content_sha256`, `source_documents.storage_ref` and `sha256`, the registry's pinned hashes), so a mismatch between the database and the files is detected and reported, never silently repaired (`monthly.pack_references`, line 928).

---

## H.5 Storage profiles and keeping reporting periods separate

### Profiles
- `uc042lib/investigation/roots.py:49-55` `PROFILES`:
  - `september`: packs/, uc042_dataset/, investigations/, final_packs/. Periods {PER-2026-09}.
  - `historical-demo`: demo_history/packs, demo_history/datasets, demo_history/investigations, demo_history/final_packs. Periods PER-2026-01 to PER-2026-08.
  - `storage_profile(name)` (line 148) checks a profile's roots: input roots must exist and must not be inside or contain `verification`, `golden`, `tests` or `UC042_JAN_AUG_HISTORICAL_DEMO` (`FORBIDDEN_DIRS`, line 30; `check_input_root`, line 86).
- `uc042app/services/layout.py`:
  - `RootSet` (line 25) holds packs, datasets, investigations and final-packs roots, plus `periods` (`None` means unrestricted).
  - `StorageLayout.from_settings` (line 52): the **`primary`** set is built from the backend's own environment settings (`UC042_PACKS_ROOT`, and so on; unrestricted, and it holds every pack produced from uploads). One extra set is added for each named profile, de-duplicated by packs root (lines 41-49), so the `september` profile adds nothing when the primary root is already `packs/`.
  - Profiles are served when they are recorded on a period in the database (`reconciliation_periods.storage_profile`, read through `repos.periods.storage_profiles()`, `services/__init__.py:55-58`) or listed in `UC042_STORAGE_PROFILES`. The live database records `historical-demo` for January-August (report 19 §13.2), so `/health` lists `primary` and `historical-demo`.
  - `for_pack(pack_id)` (line 78) finds the **one** set that holds `<root>/<pack_id>/pack.json`. If none holds it: 404. If two do: 409 `DUPLICATE_PACK`. The pack's investigations, datasets and final packs are then read and written in that same set (`InvestigationService.root_for`, investigations.py:38; `datasets_root_for`, line 280; `FinalPackService.root_for`, final_packs.py:37; `ReviewService._snapshot`, reviews.py:191).

### How reporting periods are kept separate (with the code that enforces each rule)
1. **The period is part of every artefact ID.** Pack `PACK-<scope>-PER-YYYY-MM-<12hex>` (`investigation/config.py:116`, `pack/model.py:50`). Final pack `FAP-<scope>-PER-YYYY-MM-v<n>-<12hex>` (`final_pack/model.py:23`). Every ID in a request is checked against these patterns before any storage is touched (`uc042app/ids.py:24-27`). `roots.period_of_pack` (line 132) and `ai_authorization.period_of` (line 31) read the period from the ID.
2. **Profile period sets.** `layout.for_pack` refuses a pack whose period is outside the period set of the profile root it was found in: 409 `PACK_OUTSIDE_PROFILE` (layout.py:88-91). The library does the same with `InvestigationRoots.check_pack_id` (roots.py:72-79), and `run_investigation` calls it before reading anything (graph.py:341). The backend passes explicit roots, so for the backend the period check comes from the layout.
3. **The period ID format and the allowed months.** `PER-YYYY-MM` with year 2000-2100 (`ingest/analysis.py:60-64`; `period.PeriodConfig`, lines 149-161). No future month (`monthly.py:130-131`, `FUTURE_PERIOD`). One record per month (`create_period` returns the existing one).
4. **Upload content is checked against the selected month.** The governing date columns are judged against the month (`analysis.analyse_csv`, lines 148-200). If no record falls in the month: `WRONG_PERIOD` ERROR (line 194). An IN-01 calendar for another period: `WRONG_PERIOD` ERROR (lines 186-188). Records are never moved between months.
5. **Cross-period duplicates are flagged.** `SAME_CONTENT_AS_OTHER_PERIOD` needs a decision. `RECURRING_DOCUMENT` and `HEADER_ONLY_SAME_AS_OTHER_PERIOD` are INFO (`monthly.py:516-530`).
6. **The engine never mixes periods.** `period.resolve` raises "the case mixes reporting periods" or "prepared for X, not Y; periods are never mixed" (`uc042lib/period.py:403-410`). Processing always passes the period explicitly (`monthly.py:762, 785, 800`).
7. **Reassessment baselines must come from the same month.** `baseline()` raises `BASELINE_UNVERIFIABLE` if the lineage root pack is from another month (`monthly.py:232-233`).
8. **Corrections stay within one period.** The replaced document must belong to the same period (`monthly.py:336-338`).
9. **Case evidence stays within one period.** Document references must belong to the case's period (`services/cases.py:120-124`). A case can be opened only if the pack's period is registered (`PERIOD_NOT_REGISTERED`, line 68).
10. **Reference integrity check.** `monthly.pack_references` (line 928) reports any period_pack registered under a period that differs from the pack's own `reporting_period` (line 951-952). This check is read-only (admin `verify-pack-references`).

Points to note:
- Packs produced by processing are always published in the **primary** packs root (`monthly.py:899`), even for a historical month. A reassessed historical month therefore has its new pack in `packs/` while its lineage root stays in `demo_history/packs/`. Version numbering searches every final-packs root (`lineage_final_packs`, final_packs.py:54), and the baseline is read from the root pack's own set (`monthly.py:235`).
- The `Services._check_layout` check (`services/__init__.py:74-84`) and `Settings.check` (`config.py:89-107`) keep the app state and the document store outside every storage root.

---

## H.6 ASCII architecture diagram

```
 Browser (analyst, same machine)
 +---------------------------------------------------------------------------------------------+
 | React 18 + TypeScript + React Router (frontend/src, Vite dev server 127.0.0.1:5173)          |
 |  pages/* (Dashboard, Upload, Reports, Batch, Workspace, Case, Review, FinalPack, ...)        |
 |     | useApi / useJobPoller (1 s polling)                                                    |
 |  DataProvider -> DataSource interface                                                        |
 |     |-- apiSource.ts (default; 10 s cache for health/periods/packs; change() clears it)      |
 |     '-- MockDataSource.ts (DEV + VITE_DATA_SOURCE=mock only)                                 |
 |  api/endpoints.ts -> api/client.ts request() (fetch, 30 s / 180 s, ApiError from 7807)       |
 +-----------------------------|---------------------------------------------------------------+
                               | HTTP/JSON (REST) http://127.0.0.1:8000  /api/v1/...  /health
 +-----------------------------v---------------------------------------------------------------+
 | FastAPI (uvicorn, 1 worker, loopback only -> 403 LOCAL_ONLY; CORS GET/POST/PATCH)            |
 |  routers: system | packs | investigations | reviews | final_packs | monthly | cases          |
 |  problems.py: RFC 7807 {status, code, detail}                                                |
 |-----------------------------|---------------------------------------------------------------|
 | Services (uc042app/services)                                                                 |
 |  MonthlyService  PackService  InvestigationService  AiAuthorizationService  ReviewService    |
 |  FinalPackService  CaseService  PublicationRegistry  StorageLayout(primary + profiles)       |
 |  PackLocks (in-process)   InstanceLock (state_dir/instance.lock)                             |
 |  JobRunner: ThreadPoolExecutor  [PROCESSING | INVESTIGATION | PREVIEW]                       |
 +------|------------------------|----------------------------|--------------------|-----------+
        | SQLAlchemy 2 / Alembic | uc042lib (Python)          |                    |
        v                        v                            v                    v
 +-------------------+  +----------------------------+  +------------------+  +-------------------+
 | PostgreSQL "uc042"|  | prepare.py -> validate.py  |  | investigation/   |  | final_pack/       |
 |  audit.*          |  |  (Validator: C01..C16, DQ) |  |  LangGraph graph |  |  snapshot,summary |
 |  operations.*     |  | pack/generate.build ->     |  |  + tool_loop     |  |  assemble,render  |
 |  (0001..0004;     |  |  assemble/finalise/        |  |  llm.py ---------+--+--> OpenAI         |
 |   0004 not yet    |  |  validate_pack/render_html |  |  persistence     |  |  Responses API    |
 |   applied live)   |  +-------------|--------------+  +--------|---------+  |  (store=False)    |
 +-------------------+                |                          |            +--------|----------+
                                      v                          v                     v
 +-------------------------------------------------------------------------------------------------+
 | FILES (write-once, SHA-256 verified on read)                                                    |
 |  primary:  packs/PACK-*/  uc042_dataset/  investigations/  final_packs/FAP-*/                    |
 |  historical-demo: demo_history/{packs, datasets, investigations, final_packs}  (PER-2026-01..08) |
 |  document store: objects/<sha[:2]>/<sha256>   cases/SET-<hash>/        (%USERPROFILE%\uc042_runtime)|
 |  app state: instance.lock (+ file repositories when no database)                                |
 +-------------------------------------------------------------------------------------------------+
```
