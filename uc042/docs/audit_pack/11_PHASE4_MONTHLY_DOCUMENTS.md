# UC-042 Phase 4 — PostgreSQL, monthly archive and document upload (technical guide)

Local POC: one analyst, one backend process bound to 127.0.0.1, no authentication. Synthetic data only. Everything here
runs without administrator rights. Commands are PowerShell, run from `uc042\` unless stated.

Contents: 1 What changed · 2 PostgreSQL setup · 3 Migrations · 4 Storage strategy (what is authoritative where) ·
5 Period and archive model · 6 Upload API · 7 Content identification and date validation · 8 Duplicates ·
9 Processing workflow · 10 Importing existing state and the POC scenarios · 11 Configuration · 12 Running backend and
frontend · 13 Engine limitation and extension proposal · 14 Tests

---------------------------------------------------------------------------------------------------------------------------

## 1. What changed

| Layer | Change |
|---|---|
| Backend persistence | `UC042_DATABASE_URL` set → every application-state repository (jobs, review sessions, decisions, preview fingerprints, final-pack records, investigation publication registry) uses PostgreSQL through SQLAlchemy 2.x (`uc042app/db/`). Unset → the Phase 2 file repositories, unchanged. |
| New records | Reconciliation periods, period ↔ pack references, upload batches, source documents, processing runs, activity events. |
| New services | `uc042app/ingest/` (document store, content analysis), `uc042app/services/monthly.py` (periods, uploads, decisions, confirmation, processing). |
| New API | `/api/v1/periods`, `/uploads`, `/documents`, `/processing-runs`, `/activity` (section 6). `Job.operation` gains `PROCESSING`; `/health` gains `database`. Additive only: no existing endpoint changed. |
| Frontend | Real FastAPI adapter by default; mock data only with `VITE_DATA_SOURCE=mock` in the dev server. Dashboard archive table, period page (`/periods/:id`), upload batch page (`/uploads/:id`), real upload workflow. |
| Engine, datasets, packs, investigations, golden snapshots | Not modified. |

## 2. PostgreSQL setup (no administrator rights)

The machine's PostgreSQL 18 service (port 5432) is managed by IT and its credentials are not available, so the POC
uses a **project-local cluster** started from the installed binaries under the user's own account:

```powershell
$pg = "C:\Program Files\PostgreSQL\18\bin"
$data = "$env:USERPROFILE\uc042_pg\data"
# one time: create the cluster with a random password for role uc042 (scram-sha-256, listening on 127.0.0.1 only)
$pw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
Set-Content -NoNewline -Encoding ascii "$env:TEMP\uc042_pw.txt" $pw
& "$pg\initdb.exe" -D $data -U uc042 --pwfile="$env:TEMP\uc042_pw.txt" -A scram-sha-256 -E UTF8 --locale=C
Remove-Item "$env:TEMP\uc042_pw.txt"
# start (each session / after a reboot) and stop
& "$pg\pg_ctl.exe" -D $data -o "-p 5433 -h 127.0.0.1" -l "$env:USERPROFILE\uc042_pg\server.log" start
& "$pg\pg_ctl.exe" -D $data stop
# one time: the operational database and a separate, disposable test database
$env:PGPASSWORD = "<the password>"
& "$pg\createdb.exe" -h 127.0.0.1 -p 5433 -U uc042 uc042
& "$pg\createdb.exe" -h 127.0.0.1 -p 5433 -U uc042 uc042_test
```

Put the URLs in `uc042\.env` (git-ignored; never commit a password):

```
UC042_DATABASE_URL=postgresql+pg8000://uc042:<password>@127.0.0.1:5433/uc042
UC042_TEST_DATABASE_URL=postgresql+pg8000://uc042:<password>@127.0.0.1:5433/uc042_test
```

Python packages (`requirements-api.txt`): SQLAlchemy 2.1.6, Alembic 1.20.1, pg8000 1.31.6 (pure-Python driver),
python-multipart. On this machine Windows Application Control blocks unsigned compiled DLLs, which rules out SQLAlchemy's
Cython extensions and psycopg's binary build. Install SQLAlchemy from its pure-Python wheel (the commands are in
`requirements-api.txt`); pg8000 is pure Python. Nothing is installed system-wide.

## 3. Migrations

The schema is created and changed **only** by Alembic (`uc042app/db/migrations/`, initial revision `0001_initial`, 12
tables). The backend refuses to start against a database that is not at the latest revision (it never creates tables
implicitly).

```powershell
.venv\Scripts\python.exe -m uc042app.admin db-status             # current and latest revision (exit 1 if behind)
.venv\Scripts\python.exe -m uc042app.admin db-upgrade            # apply all migrations
# rollback (destroys the tables of the reverted revisions; take a backup first):
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h 127.0.0.1 -p 5433 -U uc042 -Fc -f uc042_backup.dump uc042
.venv\Scripts\python.exe -c "from uc042app.db import alembic_config; from alembic import command; import os; command.downgrade(alembic_config(os.environ['UC042_DATABASE_URL']), 'base')"
```

(The last line needs `UC042_DATABASE_URL` in the process environment; `.env` is loaded by the backend, not by a bare
`python -c`.) Restore a backup with `pg_restore -h 127.0.0.1 -p 5433 -U uc042 -d uc042 --clean uc042_backup.dump`.
The migration was verified up → down → up against PostgreSQL 18 (test `PostgresMigrations`).

Tables: `reconciliation_periods`, `period_packs`, `upload_batches`, `source_documents`, `processing_runs`,
`activity_events`, `jobs`, `review_sessions`, `review_decisions` (append-only, unique per review and sequence),
`previews` (write-once), `final_pack_records`, `investigation_registry` (append-only, ordered by `seq`).
JSON columns are `JSONB` on PostgreSQL.

## 4. Storage strategy — what is authoritative where

PostgreSQL holds metadata, state and references; large and controlled artefacts stay files.

| Data | Authoritative location | In PostgreSQL |
|---|---|---|
| Deterministic packs | `packs/<pack_id>/` (immutable files, content hash) | `period_packs`: reference + content SHA-256 |
| AI investigations, evidence packets, ledgers | `investigations/<pack>/<exc>/<inv>/` (write-once files) | `investigation_registry`: publication registry (pinned hashes) |
| Final audit packs (JSON, HTML, PDF) | `final_packs/<FAP-…>/` (write-once files) | `final_pack_records`: generation status per GENERATE decision |
| Uploaded originals | document store `objects/<sha[:2]>/<sha256>` (content-addressed, write-once) | `source_documents`: metadata, checks, SHA-256, storage reference |
| Prepared processing cases | document store `cases/SET-<hash>/` (written once per document set) | `processing_runs.result.case` |
| POC scenario documents | `uc042_dataset/<dataset>/source_data`, `supporting_documents` (read-only, referenced in place) | `source_documents` with `dataset:` reference |
| Periods, batches, runs, decisions on documents, activity | PostgreSQL | — |
| Jobs, review sessions, decisions, preview fingerprints | PostgreSQL (file state when no database) | — |

Every read of a stored document re-checks its SHA-256. API responses never contain paths or storage references (a
document only reports `storage_kind`: `UPLOADED_ORIGINAL` or `POC_DATASET`). The document store must be outside
`packs/`, `investigations/`, `final_packs/` and `uc042_dataset/` (checked at start-up).

## 5. Period and archive model

* A **period** is a month, `PER-YYYY-MM` (the engine's period identifier). A record is created only when (a) the analyst
  opens a month for upload (current or past month; future months are refused), or (b) a verified pack exists for it.
  **No month is invented**: January–August 2026 have no records and show "No data".
* **September 2026** is registered from its nine packs. They are nine separate synthetic **test scenarios** of the same
  month (`origin = POC_SCENARIO`), never nine months and never merged.
* Archive states shown in the UI (`archive_state`): `RESULTS_AND_FINAL_PACK`, `RESULTS_NO_FINAL_PACK`,
  `DOCUMENTS_NO_RESULTS`, `AWAITING_UPLOAD`; months without a record are `NO_DATA` (frontend).
* **History is read-only.** A correction is a new upload batch: a newer document of an evidence type **supersedes** the
  earlier one for later processing runs (the earlier one stays archived), and a new run produces a new pack (or finds
  the identical existing one). Nothing is deleted, edited or overwritten.
* The **current processing document set** of a period is, for each evidence type, the latest usable document over the
  CONFIRMED upload batches, in confirmation order. "Usable": no validation error, not excluded, and any flagged duplicate
  explicitly included. POC scenario document batches are archive records only and never part of a processing set.

## 6. Upload API (`/api/v1`, database required; otherwise 503 `DATABASE_REQUIRED`)

| Method and path | Purpose |
|---|---|
| `GET /periods` | Archive table: every period with document, batch, run, pack, exception and final-pack counts |
| `POST /periods` `{year, month}` | Open a month for upload (201 created, 200 if it exists; 422 `FUTURE_PERIOD`) |
| `GET /periods/{id}` | Period detail: batches, documents, runs, packs, current document set, missing evidence, engine limitation |
| `POST /periods/{id}/uploads` | Multipart field `files` (≤ 60 files, ≤ 50 MB each). Stores every original, analyses it, records a batch. Does not process. |
| `GET /uploads/{batch_id}` | Batch, documents (with checks), runs |
| `POST /documents/{id}/review` `{decision: INCLUDE\|EXCLUDE, comment}` | Decision on one document of an unconfirmed batch (comment required; an ERROR document cannot be included) |
| `POST /uploads/{batch_id}/confirm` | Confirm (409 `DECISIONS_PENDING`, `AMBIGUOUS_EVIDENCE_TYPE`, `BATCH_INVALID`, `BATCH_CONFIRMED`) |
| `POST /uploads/{batch_id}/process` | Start a processing run (202). 409 `BATCH_NOT_CONFIRMED`, `INCOMPLETE`, `RUN_IN_PROGRESS`. Any valid month is processed with its own period configuration (section 13). |
| `GET /processing-runs/{id}` | Run status and result (`pack_id`, `outcome` PUBLISHED / ALREADY_EXISTS, intake, exceptions) |
| `GET /documents/{id}`, `GET /documents/{id}/content` | Metadata; the stored original (SHA-256 re-verified, `X-Content-SHA256`) |
| `GET /activity?limit=` | Activity log, newest first |
| `GET /jobs/{job_id}` | Existing endpoint; processing jobs have `operation = PROCESSING` |

Statuses — document: `VALID`, `WARNING`, `ERROR`. Batch validation: `VALID`, `WARNINGS`, `INCOMPLETE` (required evidence
missing from the period set), `INVALID` (no usable document). Batch: `VALIDATED` → `CONFIRMED` → `PROCESSING` →
`PROCESSED` | `PROCESSING_FAILED` (`ARCHIVED_SCENARIO` for POC scenario documents). Run: `QUEUED`, `RUNNING`, `SUCCEEDED`,
`FAILED`, `BLOCKED`, `INTERRUPTED` (backend restarted; never re-run automatically).

## 7. Content identification and date validation

**Identification** reuses the engine's own intake rules (`uc042lib.prepare.identify`): a CSV is identified only by its
exact header row, a PDF only by the key-detail labels printed in it. File names are never trusted. Acknowledgement
letters (IN-15 / IN-16) share labels and are assigned by matching the letter reference to the account inventory (IN-02)
in the batch or the period's current set. Categories are the IN-01 … IN-19 upload contract; no category was added.
XLSX/ZIP, unreadable PDFs and unknown CSV headers are `ERROR` documents with a header diagnosis — stored, never dropped.

**Dates.** Each date column has its own meaning and is reported separately (`checks.dates`): transaction execution
timestamp, booking date/timestamp, value date, settlement and cycle dates, cash-book posting timestamp, reconciliation
date and point, snapshot timestamp, bank confirmation timestamp, statement date, receipt/allocation dates, letter issue
date, policy effective date, return period / due date / submission timestamp. Only the field(s) that **decide the month**
for an evidence type — the engine's `PERIOD_RULES` (`uc042lib/schema.py`) — are judged against the selected month:

| Finding | Level | Meaning |
|---|---|---|
| `WRONG_PERIOD` | ERROR | No record falls in the selected month on the deciding field (or the calendar's `period_id` is another month). The detected range is reported. |
| `OUT_OF_PERIOD_RECORDS` | WARNING | Some records fall outside the month; they stay in the document, and the engine excludes and reports them (DQ-PERIOD). |
| `BOUNDARY_RECORDS` | INFO | Opening positions at the previous month-end 17:00 point (IN-03 snapshot, IN-10 opening rows): permitted. |
| `TIMING_DIFFERENCE` | INFO | A non-deciding date (e.g. an October value date on a 30 September booking, an August card authorisation) is outside the month: legitimate. |
| `INVALID_DATE`, `MISSING_DATE` | WARNING | Unparseable or missing mandatory dates (rows the engine will exclude). |
| `WRONG_PERIOD` on IN-19 | WARNING | The return receipt must be for the previous month. |

**No record is ever moved between months.** IN-04 follows the engine's "open during the period" rule; IN-14 follows the
reconciliation record it refers to (judged at processing).

## 8. Duplicates

Flagged, never removed; flags marked *decision* need an INCLUDE / EXCLUDE decision with a comment before confirmation.

| Flag | Detection | Decision |
|---|---|---|
| `DUPLICATE_IN_BATCH` | Same SHA-256 twice in one batch | yes |
| `DUPLICATE_OF_EARLIER_UPLOAD` | Same SHA-256 already uploaded for the period | yes |
| `SAME_NAME_DIFFERENT_CONTENT` | Same original file name, different content, in the period. Both are kept (content-addressed storage: a name never overwrites anything). | yes |
| `AMBIGUOUS_EVIDENCE_TYPE` | Two different files in one batch identify as the same IN type | yes (include exactly one) |
| `SAME_CONTENT_AS_OTHER_PERIOD` | Identical content uploaded for another month (likely the wrong month's file) | warning |
| `RECURRING_DOCUMENT` | Identical standing data/document in another month (IN-02, IN-15…IN-18): legitimate | info |
| `REPEATED_RECORD_ID` | A record key (the file's first column, e.g. `txn_id`) repeated inside one document | warning |
| `NEW_VERSION` | A different version of the same IN type exists in the period; reports how many record IDs overlap | info |

## 9. Processing workflow

`upload → validation → decisions → confirm → processing job → new pack → exceptions → AI investigation (where requested)
→ human review → final pack (GENERATE only)`

The processing job (`operation = PROCESSING`, background, one run per period at a time):

1. Reads the current document set from the store, re-verifying every SHA-256.
2. Prepares the case with the engine's `uc042lib.prepare.prepare_case` into `cases/SET-<hash of the set>/` (staged, then
   moved into place; an existing case for the same set is reused after checking its intake hashes).
3. Any MISSING / AMBIGUOUS / REJECTED intake for required evidence → run `FAILED` with the intake summary.
4. Builds the pack with `uc042lib.pack.generate.build` (the unchanged engine, assembly and validation). Any failure →
   `FAILED`, nothing published.
5. Publishes write-once into `packs_root` (engine layout, staged then `os.replace`). An identical existing pack →
   `ALREADY_EXISTS`, nothing written. A different pack with the same ID → error, never overwritten.
6. Loads the published pack through the verified loader and registers it under the period (`UPLOAD_PROCESSING`).

Exceptions are never resolved by processing; AI investigations of the new pack read source rows from its prepared case
(`InvestigationService.datasets_root_for`), which contains only the prepared source files. Hypotheses remain hypotheses;
no final pack is created by processing.

## 10. Importing existing state and the POC scenarios

```powershell
.venv\Scripts\python.exe -m uc042app.admin import-file-state --from C:\path\to\old\app_state --dry-run
.venv\Scripts\python.exe -m uc042app.admin import-file-state --from C:\path\to\old\app_state
.venv\Scripts\python.exe -m uc042app.admin import-poc-scenarios --dry-run
.venv\Scripts\python.exe -m uc042app.admin import-poc-scenarios
```

* `import-file-state` copies jobs, review sessions, decisions, previews, final-pack records and registry entries from a
  Phase 2 state folder. The source is only read. Identical records → unchanged; a database record with different content
  → reported as `CONFLICT` and left as it is (exit code 1). Idempotent.
* `import-poc-scenarios` registers each POC scenario pack's source documents in place (read-only `dataset:` references,
  SHA-256 checked against the pack's evidence register). Only `source_data/*.csv` and `supporting_documents/*.pdf` are
  referenced; answer keys, mutation lists, scenario notes and `scenario.json` are never registered. Missing evidence
  stays missing. Idempotent.
* Packs are registered under their period automatically at start-up (references only).
* Real historical months: when real documents for January–August are supplied, open each month and upload them; they go
  through the same validation. Processing them needs the engine extension (section 13).

## 11. Configuration

Backend (`uc042\.env` or the process environment):

| Variable | Default | |
|---|---|---|
| `UC042_DATABASE_URL` | unset (file state, no monthly features) | `postgresql+pg8000://…` |
| `UC042_TEST_DATABASE_URL` | unset | separate disposable database for tests (must differ from the above) |
| `UC042_DOCUMENT_STORE` | `uc042\document_store` | uploaded originals and case folders (git-ignored) |
| `UC042_APP_STATE_DIR` | `uc042\app_state` | instance lock (and file state without a database) |
| `UC042_PACKS_ROOT`, `UC042_INVESTIGATIONS_ROOT`, `UC042_FINAL_PACKS_ROOT` | project folders | |
| `UC042_ANALYST_ID`, `UC042_ANALYST_NAME` | `local-analyst`, `Local Analyst` | recorded as reviewer and uploader |

Frontend (`frontend\.env.local`): `VITE_API_BASE_URL=http://127.0.0.1:8000`, `VITE_DATA_SOURCE=api` (default;
`mock` only for the dev server and tests — mock data is excluded from the production build and never simulates an
upload), `VITE_API_TIMEOUT_MS=30000`.

## 12. Running backend and frontend

```powershell
# 1. database (once per session)
& "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D "$env:USERPROFILE\uc042_pg\data" -o "-p 5433 -h 127.0.0.1" -l "$env:USERPROFILE\uc042_pg\server.log" start
# 2. backend (terminal 1, from uc042\)
.venv\Scripts\python.exe -m uc042app.admin db-status
.venv\Scripts\python.exe -m uc042app                       # http://127.0.0.1:8000/docs
# 3. frontend (terminal 2)
cd frontend; npm run dev                                   # http://127.0.0.1:5173
# production build served by any static server: npm run build  ->  frontend\dist
```

## 13. Period-configurable engine (update, 3 November 2026)

The September-only limitation described in the first version of this guide has been removed. The engine takes the
reporting period explicitly (`uc042lib.period.PeriodConfig`); every processing run passes the period of its month to
case preparation and pack generation, and a run is no longer `BLOCKED` because of its month. A month is processed when
its mandatory inputs are present and valid for that month; otherwise the run is refused (`INCOMPLETE`) or `FAILED`
with the reason. Each successful run also records a continuity comparison with the previous period's latest successful
run (`result.continuity`; `NOT_VERIFIABLE` when there is none). Design, September regression evidence and limitations:
`13_ENGINE_PERIOD_CONFIGURATION_REPORT.md`.

## 14. Tests

| Suite | Runs on | What it covers |
|---|---|---|
| `tests/test_db.py` | SQLite and PostgreSQL | SQL repositories (concurrency, append-only, write-once, uniqueness), migrations up/down/up, refusal of an unmigrated DB, file-state import (complete, idempotent, read-only, conflicts), registry tampering on SQL |
| `tests/test_api_monthly.py` | SQLite (PostgreSQL with `UC042_TEST_REPOSITORIES=postgres`) | archive, open month, POC document registration, upload (complete set, wrong month, partial out-of-period, timing differences, invalid/empty/fake files, duplicate in batch, same name different content, repeat upload, missing categories), processing (new pack equal to the engine's, retry without overwrite, failure, other months processed subject to their inputs, the period passed to the engine, restart → INTERRUPTED), and the full analyst workflow to GENERATE with OpenAI mocked |
| Existing API suites | file, SQLite or PostgreSQL (`UC042_TEST_REPOSITORIES=file\|sqlite\|postgres`) | unchanged tests; 3 tests read the JSON registry file directly and apply to file storage only |
| `frontend/src/test/archive.test.tsx` | jsdom | archive period builder, dashboard archive states, opening a month, duplicate decision → confirm → blocked processing, real upload flow, mock never simulates uploads |

```powershell
.venv\Scripts\python.exe -m unittest                                             # file state + SQLite + PostgreSQL DB tests
$env:UC042_TEST_REPOSITORIES="postgres"; .venv\Scripts\python.exe -m unittest tests.test_api_monthly tests.test_api_reviews; Remove-Item Env:UC042_TEST_REPOSITORIES
cd frontend; npm test; npm run build; ..\.venv\Scripts\python.exe scripts\check_contract.py
```
