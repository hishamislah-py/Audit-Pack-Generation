# UC-042 Phase 4 — Implementation report: FastAPI integration, PostgreSQL and monthly document management

Date: 3 November 2026. Local POC, synthetic data only, one analyst, backend bound to 127.0.0.1, no authentication.
Technical detail (setup, API, rules, commands): `11_PHASE4_MONTHLY_DOCUMENTS.md`.

## A. Real FastAPI integration

* The React app uses the FastAPI adapter by default (`VITE_DATA_SOURCE=api`, `VITE_API_BASE_URL`). Mock data is loaded
  only by the dev server with `VITE_DATA_SOURCE=mock` (dynamic import); the fixtures moved from `public/` to
  `frontend/dev-fixtures/` and are served only in that mode. The production bundle was checked: no mock code, no
  fixture paths. A failed request is shown as an error, never replaced by mock data.
* All five screens were verified against the real backend (screenshots), and `src/test/api.live.test.ts` reads every
  pack, exception and investigation and runs a review through preview, HOLD and (opt-in, into a temporary folder)
  GENERATE.
* `scripts/check_contract.py` compares the 35 TypeScript interfaces with the Pydantic models: OK.
* Performance: the dashboard issued ~27 parallel requests, each re-verifying packs; a stat-keyed verified-pack cache and
  an eligibility cache (invalidated by any change to the pack, artefacts or registry) brought `/packs` from 1.6 s to
  0.56 s. No API contract changed for this.

## B. PostgreSQL architecture and schema

* SQLAlchemy 2.1 (pure Python), pg8000 (pure-Python driver), Alembic. The SQL repositories implement the same
  interfaces as the file repositories, so services and API contracts are unchanged; `UC042_DATABASE_URL` selects them.
* 12 tables: `reconciliation_periods`, `period_packs`, `upload_batches`, `source_documents`, `processing_runs`,
  `activity_events`, `jobs`, `review_sessions`, `review_decisions` (append-only), `previews` (write-once),
  `final_pack_records`, `investigation_registry` (append-only). JSONB for structured details.
* Optimistic concurrency on review sessions (`UPDATE … WHERE revision = expected`), unique decision sequence, write-once
  previews, unique final-pack record per decision — the same guarantees as the file store, tested on SQLite and
  PostgreSQL.
* Large and controlled files stay files (section 4 of the guide lists the authoritative location of each data type).
* Local PostgreSQL: the machine's PostgreSQL 18 service credentials are not available, so a project-local cluster runs
  under the user account on 127.0.0.1:5433 (scram-sha-256, random password in `uc042/.env`, git-ignored). No admin
  rights, nothing installed system-wide. Windows Application Control blocks unsigned compiled DLLs (SQLAlchemy's Cython
  extensions, psycopg binary); the pure-Python builds avoid this.

## C. Migrations

Alembic revision `0001_initial`, verified upgrade → downgrade → upgrade on PostgreSQL 18 (automated test). The backend
refuses to start on an unmigrated database (no implicit table creation). Commands: `db-status`, `db-upgrade`;
rollback and backup/restore are documented. `.env.example` lists `UC042_DATABASE_URL`, `UC042_TEST_DATABASE_URL`,
`UC042_DOCUMENT_STORE`; no credentials are in code or in the repository.

## D. Period model

A period is a month `PER-YYYY-MM`. A record exists only if the analyst opened the month (current or past; future
refused) or a verified pack exists for it. September 2026 is registered from its nine packs as nine `POC_SCENARIO`
packs of one month. January–August 2026 have no records and are shown as "No data". No month was invented.

## E. Archive behaviour

The dashboard archive table shows, per month: status, document count, latest validation, latest processing run, packs,
exceptions, unresolved, AI coverage and final packs. States: results and final pack · results, no final pack ·
documents, no results · open for upload · no data. `/periods/:id` shows the current processing document set, packs,
batches, runs and every document; `/uploads/:id` shows one batch. History is read-only: a correction is a new batch
(a newer document supersedes the older one for later runs; the older one stays) and a new run.

## F. Upload

Month → multiple files → stored as originals (content-addressed, SHA-256) **before** analysis, so nothing is lost →
identified by content (exact CSV header, PDF key details; IN-01 … IN-19 only; letters matched to the account inventory)
→ formats, record counts, date ranges → duplicates → missing required/optional categories → warnings and errors →
analyst INCLUDE/EXCLUDE decisions (comment required) on flagged documents → confirm → process. Invalid, empty, XLSX and
unreadable files are recorded as ERROR documents and kept. PDFs are stored as originals with their key details; they
are not fed to the AI.

## G. Date and duplicate checks

* Dates: each column has its own role (transaction, booking, value, settlement, cycle, cash-book posting,
  reconciliation, snapshot, statement, receipt/allocation, issue, effective, submission); only the field(s) that decide
  the month under the engine's `PERIOD_RULES` are judged. Findings: WRONG_PERIOD (error), OUT_OF_PERIOD_RECORDS,
  INVALID_DATE, MISSING_DATE (warnings), BOUNDARY_RECORDS and TIMING_DIFFERENCE (information). Records are never moved
  between months. Live check: the September files uploaded for October were rejected as WRONG_PERIOD on 10 evidence
  types, with the detected September ranges reported.
* Duplicates: identical file in a batch, identical file already uploaded for the period, same name with different
  content (both kept), two files claiming one evidence type, identical content in another month (warning) versus
  legitimately recurring standing documents (information), repeated record IDs inside a file, and new versions with the
  number of overlapping record IDs. Nothing is deleted; flagged documents need a recorded decision.

## H. Deterministic integration

Processing is an adapter around the unchanged engine: documents re-verified by SHA-256 → `uc042lib.prepare.prepare_case`
→ `uc042lib.pack.generate.build` → write-once publication in the engine's pack layout → verified load → registration.
The case folder is named by the content of the document set, so a retry with the same documents finds the identical
pack (`ALREADY_EXISTS`) and writes nothing. Incomplete intake or a failed build → run FAILED, nothing published.
Live and automated checks: uploading the SC2 and S05 scenario files for September produced packs whose exceptions,
control outcomes and reconciliation tables equal the original scenario packs.
**Limitation:** the engine is fixed to September 2026 (`uc042lib/schema.py`), so processing any other month is
recorded as BLOCKED with the reason; the smallest safe engine extension is proposed in the guide, section 13. General
monthly ingestion is therefore **not** claimed: it works end to end for September only.

## I. React changes

Real adapter by default; archive dashboard (new columns and states, open-a-month action, uploaded packs labelled
separately from scenarios); period page; upload batch page (document checks with date-role table, duplicate flags,
INCLUDE/EXCLUDE with comment, confirm, processing with job polling, runs); real multipart upload; activity log from the
backend; Job operation `PROCESSING`. Design tokens, components, report preview, evidence explorer and HOLD/GENERATE are
unchanged. With mock data the upload page keeps the design-only pre-check and never simulates an upload.

## J. Tests and end-to-end

| Suite | Result |
|---|---|
| Backend, full (`python -m unittest`; file state + SQLite + PostgreSQL DB tests) | 449 run, OK (1 skipped, pre-existing) |
| Monthly + reviews + jobs + DB suites on PostgreSQL (`UC042_TEST_REPOSITORIES=postgres`) | 66 run, OK |
| Existing API suites on SQLite and on PostgreSQL | 61 / 64 each; the 3 others read the JSON registry file and apply to file storage only (a SQL counterpart was added) |
| Frontend (Vitest) | 23 passed, 2 live tests skipped (opt-in) |
| Frontend build, contract check | OK; bundle free of mock code and data |
| Live backend (uvicorn + PostgreSQL test DB + temporary folders) | upload, duplicate decision, confirm, process, retry without overwrite, October wrong-period, future month refused |

The 14-step analyst workflow test (`AnalystWorkflow`) runs archive → upload → validation → decision → confirm → process →
new pack → exceptions → AI investigation (OpenAI mocked; reads the run's case folder) → review → preview → HOLD →
preview → GENERATE → verified final pack, and checks that nothing is published before GENERATE and every exception
stays UNRESOLVED.

## K. Integrity

Against the baselines taken before this phase: 426 protected files (datasets, original packs, golden snapshots,
engine, pack layer, existing engine tests, tools, docs) — none changed or missing; `uc042lib` byte-identical; all
investigation artefacts (including `_not_published`) unchanged. No `app_state/`, `final_packs/` or `document_store/`
was created in the project: tests and live checks used temporary folders and the disposable test database. Existing
tests were not modified to make new ones pass (only the shared test helper gained the repository selection). No live
OpenAI call was made. No final pack was published outside temporary folders. Answer keys, mutation lists, scenario
notes and `scenario.json` are never registered, uploaded into a case or exposed.

Operational database: during a dry run of `import-poc-scenarios`, a defect registered the nine September pack
**references** (1 period record, 9 pack references, 1 activity event) — the same registration the backend performs at
every start-up. Nothing else was written; the defect was fixed and the dry run now writes nothing.

## L. Limitations

* Processing is September 2026 only (engine contract); other months: upload and validation only.
* One upload batch at a time per analyst; no authentication; local single process (as agreed for the POC).
* The operational database's investigation publication registry is empty: run `import-legacy-investigations` (or
  `import-file-state` from an earlier state folder) before relying on investigation eligibility with the database.
* PDF content is not validated beyond key details; XLSX is not accepted (export as CSV).
* The archive lists the current year's months plus archived periods; earlier years appear only once opened.
* The per-row AI-coverage column loads investigations per pack and is slower with many packs.

## M. How to run (PowerShell)

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D "$env:USERPROFILE\uc042_pg\data" -o "-p 5433 -h 127.0.0.1" -l "$env:USERPROFILE\uc042_pg\server.log" start
cd uc042
.venv\Scripts\python.exe -m uc042app.admin db-upgrade
.venv\Scripts\python.exe -m uc042app.admin import-legacy-investigations      # once, for the database registry
.venv\Scripts\python.exe -m uc042app.admin import-poc-scenarios               # optional, scenario documents in place
.venv\Scripts\python.exe -m uc042app                                          # http://127.0.0.1:8000
cd frontend; npm run dev                                                      # http://127.0.0.1:5173
```

## N. Data still needed

* Real (or approved synthetic) source documents for any month other than September 2026 — January–August 2026 and
  later months — in the IN-01 … IN-19 formats. None exist; none were invented.
* For each such month: the previous month's REP027 receipt (IN-19) and the opening positions at the previous month-end
  (IN-03 snapshot, IN-10 opening rows).
* A decision on whether the nine September scenario document sets should stay archive-only (current behaviour) or one
  of them should become the "real" September set.

## O. Recommendation for the next phase

1. Implement the engine period extension (guide section 13) behind the existing golden snapshots, then process a second
   month end to end.
2. Add authentication and per-user identity before any shared or networked use.
3. Move the remaining file-backed operational data (failed-intake records, job logs) into the database, and add
   scheduled PostgreSQL backups.
4. Add XLSX-to-CSV conversion at upload with the original kept, if the business supplies spreadsheets.
