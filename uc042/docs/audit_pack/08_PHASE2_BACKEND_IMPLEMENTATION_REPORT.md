# 08 — Phase 2: Local FastAPI Backend and File-Backed Application State (implementation report)

**Date:** 3 Nov 2026.

**Scope.** This phase implements the backend half of `06_FINAL_AUDIT_PACK_APPLICATION_SPECIFICATION.md` §6, §8 and §12,
reduced to a **working local POC**.

**Deployment model:**

- one analyst;
- one backend process;
- bound to `127.0.0.1`;
- no authentication;
- application state in files behind small repository interfaces.

**Added:** an investigation publication registry. It closes the limitation in report 07 §9.

**Out of scope:** React, PostgreSQL, SQLAlchemy, Alembic, Celery, Redis, authentication and multi-user or multi-worker
deployment.

**Baseline before this phase:** 347 tests, OK (1 opt-in live test skipped).

**Scope simplification (3 Nov 2026).** A first version included local accounts, bearer tokens, an HMAC-signed registry,
idempotency keys, an activity log and admin endpoints. Following the scope decision, these were **removed**:

- authentication, accounts, password hashing and the auth/admin endpoints;
- HMAC signing and key management;
- idempotency keys;
- the activity log.

What remains is the analyst workflow, simple background jobs, a plain file-backed registry and per-pack locks.

## 1. Architecture

```
React frontend (Phase 3, http://localhost:5173)  --HTTP/JSON-->  FastAPI app (uc042app/api), 127.0.0.1 only
                                                                   routers -> Pydantic schemas -> problem details
                                                                   |
                                          application services (uc042app/services)
                    packs . investigations . publication registry . reviews (+closing summary, preview) . final packs
                                                     |                                        |
                         existing libraries (unchanged)                         repositories (uc042app/repositories)
   uc042lib.final_pack.sources.load_pack . uc042lib.investigation.graph.run_investigation    base.py  (interfaces)
   verify_published . list_investigations / check_eligibility . build_review_snapshot          files.py (this phase)
   generate_closing_summary . assemble_preview / assemble_final_pack . render_html / render_pdf
   next_version . publish_final_pack . verify_final_pack
                                                     |
                 background jobs (uc042app/jobs): ThreadPoolExecutor, persisted status, restart -> INTERRUPTED
```

| Path | Contents |
| --- | --- |
| `uc042app/__main__.py` | `python -m uc042app [--port 8000]`: uvicorn on **127.0.0.1**, one worker |
| `uc042app/config.py` | `Settings.from_env()`. Covers the state directory, artefact roots, CORS origins, job workers and the analyst reference (`UC042_ANALYST_ID` / `UC042_ANALYST_NAME`). It refuses a state directory inside `packs/`, `investigations/`, `final_packs/` or `uc042_dataset/`. |
| `uc042app/errors.py`, `ids.py`, `clock.py` | Typed errors with stable codes; ID formats checked before any storage access; UTC timestamps |
| `uc042app/storage/` | Atomic JSON write, exclusive create, fsynced append, and `InstanceLock` (one process per state directory) |
| `uc042app/repositories/` | `base.py` interfaces and `files.py` implementations: jobs, reviews (sessions, decisions, previews), final-pack records, registry |
| `uc042app/services/` | `packs`, `investigations`, `registry`, `reviews`, `final_packs`, `locks`; `Services` wires them together and runs start-up recovery |
| `uc042app/jobs/` | `JobRunner` and `safe_error`, which redacts secrets and strips paths |
| `uc042app/api/` | `main.create_app` (CORS, loopback guard, security headers), `problems` (RFC 7807), `schemas`, `routers/` |
| `uc042app/admin.py` | CLI: `import-legacy-investigations`, `verify-registry` (run with the backend stopped) |

**Service boundaries.** The rule is strict:

- Routers only validate and translate.
- Services never import FastAPI.
- Nothing reimplements reconciliation, investigation, retrieval, assembly or rendering. Each step calls the library
  function shown above.
- The new logic is application logic only:
  - registry checks;
  - readiness, staleness and session state;
  - locking.

## 2. API (`/api/v1`; JSON; errors are `application/problem+json` `{type,title,status,detail,code}`)

**Common behaviour:**

- No authentication.
- Requests from a non-loopback client get `403 LOCAL_ONLY`.
- IDs are format-checked first: `422 INVALID_ID`, or `404 NOT_FOUND` when unknown.

| Method and route | Request | Success | Main error codes |
| --- | --- | --- | --- |
| `GET /health` | — | `{status, storage, registry, provider_configured, analyst_id, single_process, version}` | — |
| `GET /packs` | — | `[{pack_id, verified, summary \| problem}]` (each verified by `load_pack`) | — |
| `GET /packs/{pack_id}` | — | `{summary, metadata, executive_summary, statements, verification}` | 404, `409 PACK_VERIFICATION_FAILED` |
| `GET /packs/{pack_id}/reconciliation` | — | Internal and external reconciliation tables, opening positions, accounts (copied from the pack). Added in Phase 3. | 404, 409 |
| `GET /packs/{pack_id}/sources` | — | Source-file register (dataset-relative names, SHA-256) and missing evidence. Added in Phase 3. | 404, 409 |
| `GET /packs/{pack_id}/exceptions` | — | `[ExceptionView]` (always `resolution_status: UNRESOLVED`) | 404 |
| `GET /packs/{pack_id}/exceptions/{exc}` | — | `{exception, affected_results (copied from control_register), investigations}` | 404 |
| `GET /packs/{pack_id}/investigations` | — | Per exception: `{published[…], not_published, active_jobs}` | 404 |
| `GET /packs/{pack_id}/exceptions/{exc}/investigations` | — | `{published[eligible, library_eligible, ineligible_reasons, registry], not_published, active_jobs}` | 404 |
| `POST /packs/{pack_id}/exceptions/{exc}/investigations` | `{mode:"tools", retry_of?}` | `202 Job` | `409 INVESTIGATION_ACTIVE` (+`job_id`), `503 PROVIDER_NOT_CONFIGURED`, `422 MODE_UNSUPPORTED` |
| `GET /jobs/{job_id}` | — | `Job` | 404 |
| `GET /investigations/{id}` | — | Summary, model metadata, eligibility, registry entry | 404 |
| `GET /investigations/{id}/findings` | — | Findings exactly as stored | 404 |
| `GET /investigations/{id}/evidence` | `?offset&limit≤200&evidence_id` | The ledger (tools mode) or packet records, paged; no source-file search | 404 |
| `GET /investigations/{id}/verify` | — | `{artefact_verified, artefact_problems, registry_verified, registry_problems, eligible, ineligible_reasons}` | 404 |
| `GET /reviews` | `?pack_id&status` | Review sessions, newest first; read-only, never creates one. Added in Phase 3. | 422 |
| `POST /packs/{pack_id}/reviews` | — | `201 ReviewSession`, or `200` for the existing active session | 404, 409 |
| `GET /reviews/{rid}` | — | Session, selections, readiness, current preview, preview job, acknowledgement text | 404 |
| `PATCH /reviews/{rid}/selections` | `{selections:[{exception_id, inclusion, investigation_id?, reason?}], expected_revision?}` | `ReviewSession` | `422 SELECTION_INVALID / SELECTION_INCOMPLETE / INELIGIBLE_SELECTION / NOT_INVESTIGATED_WITH_ELIGIBLE`, `409 SESSION_NOT_EDITABLE / REVIEW_CONFLICT / PREVIEW_IN_PROGRESS` |
| `POST /reviews/{rid}/preview` | — | `202 Job` (closing summary, then preview) | `409 BLOCKED` (+`blockers`), `409 PREVIEW_IN_PROGRESS` |
| `GET /reviews/{rid}/preview` | — | `PreviewMeta` (snapshot hash, closing-summary status and failure) | `404 NO_PREVIEW` |
| `GET /reviews/{rid}/preview/{html\|pdf\|json}` | `?snapshot=` | The rendered preview; headers `X-Snapshot-SHA256`, `ETag` | `409 PREVIEW_STALE` |
| `POST /reviews/{rid}/decision` | `{decision, snapshot_sha256, comment, acknowledgement_accepted, acknowledged_summary_unavailable}` | `201 {decision, session_status, final_pack}` | `409 PREVIEW_REQUIRED / PREVIEW_STALE / BLOCKED / GENERATION_IN_PROGRESS / SESSION_CLOSED` (+`final_pack_id`), `422 COMMENT_REQUIRED / ACKNOWLEDGEMENT_REQUIRED / SUMMARY_UNAVAILABLE_ACK_REQUIRED`, `500 GENERATION_FAILED` |
| `GET /reviews/{rid}/history` | — | `{decisions (append-only), final_pack_records}` | 404 |
| `GET /final-packs` | `?pack_id=` | List (ID, pack, version, supersedes, generated_at, decision, content hash) | 422 |
| `GET /final-packs/{fid}` | — | Metadata, human review, manifest files, generation record | 404 |
| `GET /final-packs/{fid}/verify` | — | `{verified, problems}` (`verify_final_pack`) | 404 |
| `GET /final-packs/{fid}/{json\|html\|pdf}` | — | File bytes, `ETag` = SHA-256, checked against the manifest first | 404, `409 FINAL_PACK_INTEGRITY_FAILED` |

**Deliberately absent:**

- authentication, users and admin endpoints;
- upload, deletion or arbitrary file reads;
- editing findings, statuses or decisions;
- resolving exceptions;
- source-file search;
- any file-system path in a response.

### Example

```http
POST /api/v1/packs/PACK-SC5A-PER-2026-09-ae391170b93a/exceptions/EXC-SC5A-01/investigations   {"mode": "tools"}
→ 202 {"job_id":"JOB-…","operation":"INVESTIGATION","status":"QUEUED",…}
GET /api/v1/jobs/JOB-… → {"status":"COMPLETED","result":{"investigation_id":"INV-EXC-SC5A-01-…","persist_outcome":"PUBLISHED",
                          "validation_status":"VALID","registered":true,"registry_record_type":"NEW_PUBLICATION",…}}
POST /api/v1/reviews/RS-…/decision
{"decision":"GENERATE","snapshot_sha256":"<current preview>","acknowledgement_accepted":true,"comment":"Reviewed."}
→ 201 {"decision":{"review_decision_id":"RD-…","reviewer":{"user_id":"local-analyst",…}},"session_status":"GENERATED",
       "final_pack":{"final_pack_id":"FAP-SC5A-PER-2026-09-v1-…","status":"GENERATED","version":1,…}}
```

## 3. Persistence and concurrency

**Location.** State lives in `UC042_APP_STATE_DIR` (default `uc042/app_state/`, which is git-ignored). Controlled
artefacts stay where the libraries write them.

```
jobs/<job_id>.json                         final_pack_records/<decision_id>.json
reviews/<RS-…>/session.json                reviews/<RS-…>/decisions.jsonl          (append-only)
reviews/<RS-…>/previews/<PV-…>/{meta.json, preview.json}                           (write-once; meta holds the fingerprints)
registry/investigation_registry.json       (publication registry)                   instance.lock
```

**Write guarantees:**

- Whole-file writes are staged, fsynced and moved into place with `os.replace`.
- New records are created exclusively, so they never overwrite anything.
- Decision appends are fsynced.
- Review sessions carry a revision number; a stale update gets `409 REVIEW_CONFLICT`.

**Repository interfaces (`repositories/base.py`).** These are what a later database phase would implement:
`JobRepository`, `ReviewRepository`, `FinalPackRecordRepository` and `RegistryRepository`. Services receive them through
`Services(settings, repositories=…)`.

**Locking:**

- `PackLocks` (in-process) serialises every write for a pack: session creation, selections, preview requests,
  investigation submission and decisions.
- GENERATE takes the pack lock without waiting, so a concurrent GENERATE gets `409 GENERATION_IN_PROGRESS`.
- Version allocation (`next_version`) and publication happen under that lock. The library's write-once publication and
  its one-pack-per-decision rule remain as a second guard.
- A repeated GENERATE on a generated session gets `409 SESSION_CLOSED`, naming the published `final_pack_id`.
- A repeated investigation submission while one is active gets `409 INVESTIGATION_ACTIVE`, naming the active job.

**Single-process limitation.** The locks are in-process, so the POC must run as **one backend process**:

- `python -m uc042app` always starts one worker.
- `InstanceLock` takes an OS-level exclusive lock on `instance.lock`, so a second backend or the maintenance CLI is
  refused while the backend runs.
- There is no distributed or multi-machine locking.

## 4. Investigation publication registry

**Purpose.** It closes the limitation in report 07 §9.

**Storage.** One JSON file, `registry/investigation_registry.json`, rewritten atomically on every append. Entries are
never edited or removed by the backend. Each entry records:

- `seq` and `record_type` (`NEW_PUBLICATION` | `LEGACY_BASELINE_IMPORT`);
- `investigation_id`, `exception_id`, `investigation_mode`;
- `pack_id`, `pack_content_sha256`;
- `findings_sha256` (the bytes of `findings.json`);
- `evidence_packet_sha256` (as declared) and `evidence_packet_file_sha256` (the bytes), plus
  `evidence_ledger_file_sha256`;
- `findings_schema_version`, `prompt_version`;
- `recorded_at`, `recorded_by` (the analyst reference), `verify_published: "OK"`, `note`.

**Record types:**

- **`NEW_PUBLICATION`.** Written by the backend's investigation job right after the library publishes the artefact, and
  only when all of these hold:
  - the investigation is COMPLETED and VALID;
  - it is not simulated;
  - `verify_published` is OK;
  - the pack and hash match.

  Failed, rejected and simulated results are never registered.
- **`LEGACY_BASELINE_IMPORT`.** Written by `python -m uc042app.admin import-legacy-investigations` for pre-registry
  artefacts that pass `verify_published` now.
  - The entry's note states that it is an integrity baseline **from the time of import** and does **not** prove the
    contents at original publication.
  - It never modifies an artefact and never regenerates an ID.
  - Artefacts that fail the current rules (C-01) are imported but stay ineligible.

**Eligibility = library check AND registry check:**

- **Library check:** `verify_published`, the same pack and hash, COMPLETED/VALID, not simulated, and the current
  validation rules.
- **Registry check:** an entry exists, the folder name equals the ID, and every pinned hash and version equals the
  current files.

Until the legacy import is run, existing artefacts are listed with `library_eligible: true, eligible: false` and the
reason "not in the investigation publication registry".

**Detection (tested):**

| Change | Result |
| --- | --- |
| Edited findings | `findings_sha256 differs` |
| Edited packet | `evidence_packet_file_sha256 differs` |
| Folder renamed | `verify_published` fails |
| Findings rewritten, **ID recomputed and folder renamed** | Unregistered, so ineligible |
| Wrong pack or pack hash | Registration refused, or "different pack" |
| A registry entry edited so it no longer matches the files | Flagged as a mismatch |
| Unreadable or malformed registry | The service **fails closed** (nothing registry-verified) and `/health` reports `degraded` |

**Trust limit (stated plainly).** The registry is a plain local file, with no signing and no key management. A local
administrator with write access to both the artefacts and the registry can change both consistently. The registry
detects inconsistent changes; it is **not** tamper-proof.

## 5. Background jobs

- **Runner.** A `ThreadPoolExecutor` (`UC042_JOB_WORKERS`, default 2) in the backend process. It has no Celery, Redis,
  broker, WebSockets or scheduler.
- **Flow.** Submit, then get `202` with a `job_id` immediately. The job runs in the background, its status is persisted,
  and the client polls `GET /jobs/{id}`.
- **Statuses:** `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `INTERRUPTED`.
- **Job record:** `job_id`, `operation` (`INVESTIGATION` | `PREVIEW`), `pack_id`, `exception_id`, `inputs`, `status`,
  `submitted_at`, `started_at`, `completed_at`, `error_summary` (redacted, with no paths), `result` (a result reference),
  `retry_of`, `submitted_by`.
- **No blocking work on the event loop.** Endpoints are synchronous functions, which FastAPI runs in its thread pool. AI
  calls run only inside jobs.
- **Investigation job.** It runs `run_investigation(..., mode="tools", tool_limits=config.tool_limits())`, then:
  - registers a `PUBLISHED` result, and reports `COMPLETED`;
  - reports anything else (provider failure, REJECTED, or a write-once refusal) as `FAILED` with the reason.

  The library keeps failed attempts in `_not_published/`, and they are listed in the API.
- **Restart:**
  - unfinished jobs are marked `INTERRUPTED` and never re-run automatically; there are no repeated OpenAI calls;
  - the analyst can start a new job (`retry_of` links it to the earlier one);
  - write-once persistence means a retry cannot overwrite an artefact.

  Final-pack records left `GENERATING` are reconciled with storage:
  - if a published pack for the decision verifies, the record becomes `GENERATED`;
  - otherwise it becomes `GENERATION_FAILED`.

  Abandoned staging folders are removed.

## 6. Review workflow (spec 06 §6, using the library throughout)

1. **Open a session.** `POST /packs/{id}/reviews` verifies the pack and opens one active session per pack. Defaults apply
   the library rule (newest eligible tools-mode, then newest eligible) to registry-eligible investigations; otherwise the
   exception is `NOT_INVESTIGATED`.
2. **Select.** `PATCH …/selections` validates with `Selection`:
   - EXCLUDED_BY_ANALYST needs a reason;
   - every exception needs exactly one selection;
   - INCLUDED needs a combined-eligible investigation;
   - NOT_INVESTIGATED is refused while a verified investigation exists.

   Any change invalidates the closing summary and preview.
3. **Preview** (a job):
   - `build_review_snapshot`, plus the registry check;
   - `generate_closing_summary`. On failure, the failure is stored and `unavailable_closing_summary` is used. No text is
     ever invented, and the analyst sees a warning;
   - `assemble_preview` from the same snapshot.

   Stored: the preview document, the snapshot hash, an **inputs fingerprint** (the snapshot plus every published
   investigation of the pack with its eligibility), and the full summary record and its SHA-256.
4. **Readiness** (shown on the session):
   - **Blockers:** a running investigation, an ineligible selection, NOT_INVESTIGATED with an eligible investigation, a
     preview running, or a preview required.
   - **Warnings:** not investigated, closing summary unavailable, a final pack already exists.
   - **Info:** unresolved exceptions, which never block.
5. **HOLD.**
   - Requires a comment, and the decision is appended.
   - The session moves to ON_HOLD and the preview is cleared, so resuming needs a fresh preview.
   - Nothing is published.
6. **GENERATE.** In order:
   1. The `snapshot_sha256` must equal the current preview's; otherwise `409 PREVIEW_STALE`.
   2. `acknowledgement_accepted` must be true; otherwise `422`.
   3. If the closing summary is unavailable, the request must also acknowledge that.
   4. The inputs fingerprint must be unchanged; otherwise `PREVIEW_STALE`.
   5. No blockers remain.
   6. The snapshot is rebuilt and re-verified, and must have the same hash.

   Then:

   - the decision is appended, with `reviewer = {UC042_ANALYST_ID, UC042_ANALYST_NAME}`;
   - `next_version`;
   - `assemble_final_pack(..., ReviewRecord(prior HOLD decisions), GenerationInfo(version, supersedes))`;
   - `publish_final_pack`;
   - `verify_final_pack`.

   On failure, the record and session become `GENERATION_FAILED` and the response is `500 GENERATION_FAILED`. Nothing is
   published, and a new GENERATE retries.
7. **Afterwards.** A GENERATED session is closed. A new session produces version N+1, superseding N.

**Generation is synchronous** in the request thread: about 2–5 s, mostly PDF rendering, with the pack lock held. The AI
never decides; decisions come only from the analyst's explicit request.

## 7. Error handling

- **Problem details everywhere:**
  - typed `AppError` codes;
  - Pydantic request errors become `422 VALIDATION_ERROR`, listing field locations;
  - unknown routes become 404 and wrong methods 405.
- **Unexpected exceptions** are logged server-side and answered with a generic `500 INTERNAL_ERROR`. There is no
  trace, path or secret in the response.
- **Library errors are mapped:**

| Library error | Response |
| --- | --- |
| `RetrievalError` / `FinalPackInputError` on load | `409 PACK_VERIFICATION_FAILED` |
| `FinalPackInputError` in a snapshot | `409 BLOCKED` |
| `LLMConfigurationError` or a simulated provider | `503 PROVIDER_NOT_CONFIGURED` |
| `ClosingSummaryError` | Stored failure plus UNAVAILABLE summary |
| `FinalPackValidationError` or a publication error | `500 GENERATION_FAILED` |

## 8. Tests (offline)

**New modules (58 tests).** Every backend test runs on temporary state, investigations and final-pack folders; the real
`packs/` folder is only read. The provider is the real `OpenAIInvestigator` with its HTTP layer mocked
(`tests/api_support.py`). `investigator_from_env` is patched to fail, so no live call is possible.

| Module | Tests | Covers |
| --- | --- | --- |
| `test_api_basics.py` | 14 | Health; `403 LOCAL_ONLY` for a non-loopback client; no auth, user or admin routes; invalid IDs; 404s; body validation; generic 500 without internals; pack and exception serialisation without paths; no status-changing routes; CORS allow and deny; wildcard refused; state-dir guard; analyst reference; single-process lock |
| `test_api_registry.py` | 14 | New registration; unregistered not eligible; legacy import (labelled, idempotent, unchanged artefacts; schema 1.2 and 1.4 eligible; C-01 still ineligible); edited findings or packet; folder rename; recomputed ID; wrong pack or hash; edited registry entry; damaged registry fails closed; atomic writes; simulated and failed never registered; restart persistence; real artefacts unchanged |
| `test_api_jobs.py` | 10 | V2 job success and polling; findings and evidence endpoints; failed job (redacted); duplicate while active → 409; 4 concurrent submissions → 1 job; restart → INTERRUPTED with no re-run, then an explicit retry; a retry never overwrites; invalid `retry_of`; provider unconfigured or simulated → 503; 404s; pack listing |
| `test_api_reviews.py` | 18 | Session defaults and single active session; restart persistence; selection validation; preview with generated summary and HTML/PDF/JSON; stale `?snapshot`; selection change invalidates; summary failure (UNAVAILABLE, warning, acknowledgement required, recorded in the final pack); HOLD → resume → GENERATE (history, prior decisions, configured reviewer); acknowledgement and stale snapshot; a new investigation makes the preview stale; a running investigation blocks; duplicate and concurrent GENERATE → one pack; generation failure and retry; final-pack retrieval, verification and tamper detection; version 2 supersedes 1; crash recovery; clean pack S01 end to end; no project `final_packs/` or `app_state/` |
| `test_api_admin.py` | 2 | Legacy import (dry run, real, idempotent) and `verify-registry` (detects a changed findings file); the CLI is refused while the backend runs |

## 9. Run locally (PowerShell; no administrator rights; the project `.venv` only)

```powershell
cd C:\Users\<you>\Downloads\UC042_CLAUDE_CODE_HANDOFF\uc042
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-api.txt        # fastapi 0.162.0, uvicorn 0.54.0 (prebuilt wheels, into .venv)

# Optional settings
$env:UC042_ANALYST_ID   = "jdoe"                     # reviewer reference recorded in decisions (default local-analyst)
$env:UC042_ANALYST_NAME = "J Doe"
$env:UC042_APP_STATE_DIR = "C:\Users\<you>\uc042_app_state"    # default uc042\app_state

# One-time (backend stopped): register the existing published investigations as a legacy baseline
python -m uc042app.admin import-legacy-investigations --dry-run
python -m uc042app.admin import-legacy-investigations
python -m uc042app.admin verify-registry

# Start: 127.0.0.1 only, one process
python -m uc042app                                   # http://127.0.0.1:8000/docs (Swagger), /openapi.json

# Offline tests
$env:PYTHONDONTWRITEBYTECODE = "1"; python -W error::ResourceWarning -m unittest
```

Live investigations and closing summaries use the existing `uc042/.env` (`OPENAI_API_KEY`, model `gpt-6-luna`). They run
only when the analyst starts an investigation job or requests a preview.

## 10. Frontend connection (Phase 3)

- **Development setup.** The React dev server (`http://localhost:5173`, an allowed CORS origin) calls
  `http://127.0.0.1:8000/api/v1`.
- **Workflow.**
  - Jobs are polled with `GET /jobs/{id}`.
  - The review screen reads `readiness`, embeds the preview HTML in a sandboxed iframe or opens the PDF, and sends the
    preview's `snapshot_sha256` with the decision.
- **Client contract.** `/openapi.json` can generate a typed client.

## 11. Results and integrity

**Tests:** the full suite runs **405 tests** (347 existing + 58 new): OK, with 1 skipped (the existing opt-in live test).
No existing test was changed.

**Integrity:**

- Before and after hashes match for these, with no changes:
  - datasets, packs, golden snapshots;
  - the engine and all 43 `uc042lib` modules;
  - existing tests;
  - all 34 `investigations/` files, including `_not_published/`.
- There is no project `final_packs/` or `app_state/`.
- No live OpenAI call was made in this phase.

## 11a. Phase 3 additions (3 Nov 2026)

- **Three read-only endpoints** were added for the React frontend: pack reconciliation, pack sources, and the review list.
  No existing contract changed.
- **Windows fix.** A `GET /jobs/{id}` issued while the runner rewrote the job file could fail with a sharing violation
  (500). Repository reads now share the writers' lock, and atomic replaces and reads retry briefly on
  `PermissionError`.
- **Tests and details.** The regression test is `tests/test_api_reads.py`; details are in report 09.

## 12. Known POC limitations

- **Single analyst, no authentication.** It is safe only on `127.0.0.1` on a single-user machine; anyone with local access
  can use the API. The reviewer identity is a configured reference, not an authenticated user.
- **Single process.** One backend process per state directory (enforced), with in-process locks. There is no multi-worker,
  multi-machine or distributed locking.
- **File-backed state.** It is durable (atomic writes, fsync), but it has no transactions spanning several files. For
  example, a decision append and the session update are separate writes. Start-up recovery reconciles generation records
  only.
- **Registry trust.**
  - It is a plain file: a local administrator can change both artefacts and registry consistently.
  - Legacy imports attest only from the time of import.
  - An investigation interrupted between publication and registration stays unregistered, and so ineligible, until
    `import-legacy-investigations` is run.
- **No request idempotency keys.** Duplicates are controlled by session state and locks (`409 SESSION_CLOSED` /
  `INVESTIGATION_ACTIVE`) rather than by replaying the original response.
- **Performance.**
  - Eligibility re-validates published investigations on each listing and readiness check; this is fine for the
    synthetic packs.
  - PDF previews are rendered on each request.
  - Generation is synchronous.
- **Scope.** Synthetic data only; OpenAI data handling is as documented in report 07 (ZDR/MAM not established).
