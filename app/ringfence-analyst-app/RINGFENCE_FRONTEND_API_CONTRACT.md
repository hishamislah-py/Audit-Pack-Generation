# Ringfence: frontend API contract

**For:** the developer connecting the Claude Design Ringfence frontend (design system `Y3euVmzeGm7SShPbkDkM67`, screens S01–S14) to the backend in `p10\smartparser_phase1`.
**Backend version:** the working copy as of 19 November 2026 (this document matches its executed tests, listed in `RINGFENCE_BACKEND_INTEGRATION_REPORT.md`).
**Rule:** the backend owns every lifecycle rule. The frontend renders the states, counts, steps, actions and messages it receives, and never derives them (design handoff §5). Build one adapter module that maps the payloads below into the design's view models. §8 gives the mapping for each view model.

---

## 1. Conventions

| Item | Contract |
|---|---|
| Base URL | `http://127.0.0.1:<port>/api`. The server is `py -3.11 -m smartparser.webapp.server --root <workspace> --authority <policy> --uc042-root <engine> --reviewer-id <id> --reviewer-role analyst --reviewer-kind TEST --port 8780`. |
| Same origin | Serve the frontend from the same origin, or proxy `/api`. The server's CSP is `default-src 'self'`, and the server does not send CORS headers. |
| Bodies | JSON (`Content-Type: application/json`). |
| Mutations | Every `POST` **must** send `X-Smartparser-Client: webapp`; without it the server returns `403 FORBIDDEN`. |
| Identity | One analyst per server process, read from `GET /api/app` → `reviewer.reviewer_id`. There is no login API; the S01 sign-in is a simulated session. |
| Errors | Always `{"error": CODE, "message": text}`. Show `message` verbatim. HTTP 400 means invalid input; 403 forbidden or not authorised; 404 not found; 409 the state does not allow it (the codes in §6); 413 body too large (limit 120 MB); 500 `INTERNAL` (unexpected error text is never echoed). |
| Stale actions | Each case has `revision` (an integer that increases on every case change). Send `expected_revision` in any case mutation body; if the case changed since you loaded it you get `409 CASE_CHANGED` ("This case changed. Reload to see the latest state."). The field is optional, but recommended for every mutation. |
| Idempotency | Repeating a mutation never creates a duplicate operation. A second Start, Resume, Retry or Activate is refused with 409 (`CASE_STATE`, `RUN_NOT_FAILED`, `ALREADY_ACTIVATED`). Identical file bytes for a category are refused by the service. An operation is refused while another runs (`OPERATION_RUNNING`). |
| Times | ISO-8601 UTC strings (`2026-11-19T10:19:47+00:00`). Render them in UK time. |
| Identifiers | `case_ref` `RF-YYYY-MM-NNN` · `run_id` `RUN-YYYY-MM-NNN-NN-xxxxxx` · `package_id` `PKG-YYYY-MM-xxxxxx` · `file_version_id` `FV-…` · `job_id` `JOB-…` · `snapshot_id` `SNAP-NNN-xxxxxxxx` · reconciliation run `RECON-…` · exception `EXC-CASE-NN` · categories `IN-01`…`IN-19` (from `GET /api/app`). |

## 2. Status model and allowed actions

**Case status: exactly four values.**
- `WAITING`
- `IN_PROGRESS`: when `deferring: true`, it is still IN_PROGRESS and the design shows *Deferral requested*.
- `PENDING`
- `COMPLETED`

**`actions` on the case detail is authoritative.** Each entry is `{enabled: bool, reason: string|null}`. Render the button disabled with `reason` beside it. This table is informative only:

| Status | start | defer | resume | retry_from_beginning | upload_evidence | review | validate | activate | reconcile |
|---|---|---|---|---|---|---|---|---|---|
| WAITING | ✓ if no other case is IN_PROGRESS (`blocked_by` names it) | – | – | – | – | – | – | – | – |
| IN_PROGRESS (idle, latest run COMPLETED) | – | ✓ | – | – | ✓ until activated | ✓ if a file awaits review | ✓ until activated (normally automatic) | ✓ when validation PASSED, current, not activated | ✓ when activated and the engine is configured |
| IN_PROGRESS, operation running | – | ✓ (becomes a deferral request) | – | – | – | – | – | – | – |
| IN_PROGRESS, `deferring` | – | – | – | – | – | – | – | – | – |
| IN_PROGRESS, latest run FAILED | – | ✓ | – | ✓ (needs confirmation) | – | – | – | – | – |
| PENDING (inspect only) | – | – | ✓ if no other case is IN_PROGRESS | – (resume first, O10) | – | – | – | – | – |
| COMPLETED | – | – | – | – | – | – | – | – | – |

**Other state values:**

| Object | Values |
|---|---|
| Run `status` | `PROCESSING`, `COMPLETED`, `FAILED` (technical failure only, O6). There is **no** `PAUSED`: a deferral waits for the running job to finish. |
| `steps[]` (5, order fixed) | `key`: `smart_parser`, `review`, `validation`, `activation`, `reconciliation`. `state`: `done`, `current`, `attention`, `failed`, `paused`, `todo`. |
| File version `version_status` | `RECEIVED`, `VALIDATED`, `REVIEW_REQUIRED`, `RESUBMISSION_REQUIRED`, `FAILED_VALIDATION`, `REJECTED`, `ACTIVE`, `SUPERSEDED` |
| Package `package_status` | `RECEIVED`, `INCOMPLETE`, `REVIEW_REQUIRED`, `RESUBMISSION_REQUIRED`, `READY_FOR_VALIDATION`, `RECONCILIATION_READY` |
| Validation `state` | `NOT_RUN`, `RUNNING`, `PASSED`, `FAILED` (+ `current` false = out of date) |
| Reconciliation `state` / `case_status` | `NOT_RUN`, `RUNNING`, `COMPLETED`, `FAILED` / `CLEAN`, `EXCEPTIONS_OPEN`, `EVIDENCE_INCOMPLETE` |
| Control outcome | `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE`, `NOT_APPLICABLE` |
| Exception severity | `Critical`, `High` (as the engine writes them) |
| Review row `available_actions` | subset of `MAP`, `CHANGE`, `IGNORE` (per column); file-level `CONFIRM`, `REJECT` in `file_actions` |

## 3. Case endpoints

### 3.1 Register a case: `POST /api/cases` (S02 / O8)

Request: `{"customer_name": "Harbourline Payments Ltd", "reporting_period": "2026-09", "zip_name": "submission.zip", "zip_b64": "<base64 of the ZIP>", "customer_id": "optional"}`.

Response: case detail (§3.3), with `status: "WAITING"`.

Errors:
- `400 INVALID`: a missing name, or a period not in `YYYY-MM`.
- `400 NOT_A_ZIP`: the name doesn't end in `.zip` or the content has no ZIP signature.
- `400 FILE_TOO_LARGE`: more than 50 MB.

The ZIP is stored content-addressed, with its SHA-256 in `zip.sha256`. Several cases may share a period, and even a customer.

### 3.2 Work queue: `GET /api/cases[?status=WAITING|IN_PROGRESS|PENDING|COMPLETED]` (S02, top-bar slot)

Response:

```json
{"items": [CaseSummary…], "counts": {"WAITING": 2, "IN_PROGRESS": 1, "PENDING": 0, "COMPLETED": 1},
 "active_case_ref": "RF-2026-09-003",
 "active_case": {"case_ref": "…", "customer_name": "…", "reporting_period": "…", "deferring": false},
 "ordering": "in progress first; then WAITING and PENDING oldest first; then COMPLETED newest first"}
```

- `counts` and `active_case` always cover **all** cases, whatever the filter.
- Render `items` in the order given; do not re-sort.

**CaseSummary:**

```json
{"case_ref", "customer_id", "customer_name", "reporting_period", "created_at", "status", "last_activity_at",
 "zip": {"filename", "size", "sha256"},
 "deferring", "deferral": {"requested_at", "waiting_for": [{"job_id", "kind", "state"}]} | null, "deferred_at",
 "started": {"by", "at"} | null, "completed": {"at", "reconciliation_run_id", "snapshot_id", "case_status"} | null,
 "current_run": {"run_id", "run_no", "status", "package_id", "started_at", "finished_at", "failure"} | null,
 "runs_total", "failed_runs", "revision", "status_since", "other_cases_for_period",
 "steps": [{"key", "state"} ×5],
 "progress": Progress}
```

**Progress** (all counts computed by the backend):

```json
{"categories_total": 19, "required_total": 17, "categories_processed", "categories_validated",
 "files_awaiting_review", "decisions_outstanding", "decisions_made",
 "missing_required": [{"category", "title"}],
 "correction_required": [{"category", "title", "file_version_id", "version_status", "version_number", "reason", "required"}],
 "awaiting_review": [{"category", "title", "file_version_id", "remaining", "total", "remaining_columns", "version_number", "original_filename"}],
 "refused_uploads": [{"filename", "source_sha256", "evidence_category", "reason", "at"}],
 "validation": {"state", "at", "failed_checks", "current"},
 "activation": {"snapshot_id"} | null,
 "reconciliation": {"state", "job_id", "run_id", "case_status", "exceptions", "error"},
 "current_operation": {"kind", "job_id", "state", "files_total", "files_processed", "validation_running"} | null,
 "last_activity_at",
 "summary": ["17 of 19 evidence categories processed", "1 file(s) awaiting mapping review, 2 decision(s) outstanding", …]}
```

`summary[]` holds the progress facts, already worded, most important first.

### 3.3 Case detail: `GET /api/cases/{ref}` (every case screen)

Opening a case **never** changes it. The response is the CaseSummary plus:

```json
{"status_history": [{"status", "at", "note"}],
 "runs": [Run…],
 "actions": {"start", "defer", "resume", "retry_from_beginning", "upload_evidence", "review", "validate", "activate", "reconcile"},
 "outstanding": {
   "mapping_decisions": [{"file_version_id", "category", "file_name", "version", "outstanding", "total", "columns": ["memo_2"]}],
   "missing_categories": [{"category", "title", "format": "CSV|PDF"}],
   "files_requiring_replacement": [{"category", "file_version_id", "version", "version_status", "cause": "STRUCTURE_FAILED|COLUMN_REJECTED", "detail"}],
   "refused_uploads": […],
   "other": [{"kind": "RETRY_FROM_BEGINNING|ACTIVATE|RUN_RECONCILIATION", "detail"}]},
 "kept": ["16 of 19 evidence categories processed and kept", "1 mapping decision(s) saved", …],
 "blocked_by": {"case_ref", "customer_name", "reporting_period"} | null,
 "activation": {"snapshot_id", "activated_by", "activated_at", "manifest_sha256"} | null,
 "package": {"package_id", "package_status", "active_snapshot_id",
             "slots": [{"evidence_category", "required", "versions", "latest": {"file_version_id", "version_number", "version_status", "original_filename", "processing_status"} | null}],
             "latest_validation": {"at", "passed", "checks": [{"check_id", "name", "passed", "detail"}]} | null,
             "jobs": [{"job_id", "kind": "intake|resubmission|reconciliation", "state", "created_at", "finished_at", "error", "run_id"}]} | null}
```

**Run** (also returned by §3.5):

```json
{"run_id", "run_no", "package_id", "started_at", "started_by", "status", "finished_at",
 "failure": {"code", "message", "at", "job_id?", "stage?"} | null,
 "retry_of", "evidence_source": "ORIGINAL_ZIP", "staged_entries", "skipped_entries",
 "not_carried_forward": [{"job_id", "kind", "files": [{"name", "category"}]}],
 "intake_job": {"job_id", "state", "error", "trace", "files": [{"name", "state", "outcome"}], "created_at", "finished_at"} | null}
```

`not_carried_forward` is present on retry runs only.

### 3.4 Lifecycle mutations

| Operation | Endpoint | Body | Success | Typical errors |
|---|---|---|---|---|
| Start Smart Parsing (S05) | `POST /api/cases/{ref}/start` | `{expected_revision?}` | detail; `current_run.status: PROCESSING` | 409 `CASE_STATE`, `ACTIVE_CASE_EXISTS` |
| Defer Case | `POST /api/cases/{ref}/defer` | `{expected_revision?}` | detail: `PENDING`, or `IN_PROGRESS` + `deferring: true` while a job runs | 409 `CASE_STATE` |
| Resume Processing | `POST /api/cases/{ref}/resume` | `{expected_revision?}` | detail: `IN_PROGRESS`; `outstanding` lists what is left | 409 `CASE_STATE`, `ACTIVE_CASE_EXISTS` |
| Retry from Beginning (S06) | `POST /api/cases/{ref}/retry` | `{"confirm": true, expected_revision?}` | detail; new run (`retry_of` = failed run). The **original ZIP** is used; uploads to the failed run are listed in `not_carried_forward` (O1). | 400 `CONFIRMATION_REQUIRED`; 409 `RUN_NOT_FAILED`, `CASE_NOT_ACTIVE` (PENDING: resume first) |
| Upload missing / corrected file (S10) | first `POST /api/staging` `{"name", "data_b64"}`, then `POST /api/cases/{ref}/evidence` `{"staging_id", "category"}` | – | `{job_id, case}`. Processing starts immediately; validation runs automatically at the end. | 409 `EVIDENCE_NOT_ACCEPTED`, `PACKAGE_LOCKED`, `OPERATION_RUNNING`, `RUN_FAILED`, `CASE_NOT_ACTIVE` |
| Activate package (S11) | `POST /api/cases/{ref}/activate` | `{"confirm": true}` (send only after the acknowledgement is ticked) | `{activated, reason, snapshot_id, case}` | 400 `CONFIRMATION_REQUIRED`; 409 `ALREADY_ACTIVATED`; `activated:false` + reason if validation fails |
| Run reconciliation (S12) | `POST /api/cases/{ref}/reconcile` | `{expected_revision?}` | `{job_id, case}` | 409 `NOT_ACTIVATED`, `OPERATION_RUNNING` |
| (Optional) Run validation | `POST /api/cases/{ref}/validate` | – | detail | 409 `PACKAGE_LOCKED` after activation. The design has no button: validation runs automatically after every run, upload, confirmation and rejection. |

`category` for an upload:
- **missing category:** the category code (a routing hint; the content is checked, O7);
- **correction:** the category of a `files_requiring_replacement` entry.

The backend decides intake or resubmission. Identical bytes are refused.

### 3.5 Run detail: `GET /api/cases/{ref}/runs/{run_id}` (S06)

Returns a Run plus:
- `stages`: the 9 real stages `[{key, title, explanation, status, started_at, finished_at, evidence, …}]`, keyed `init`, `read`, `identify`, `structure`, `mapping`, `proposals`, `review`, `previews`, `validation`. Each status is `pending`, `running`, `completed`, `requires_review`, `requires_attention`, `not_required`, `blocked` or `failed`.
- `events`: the recorded audit events of the job (`[{seq, event_type, at, actor_id}]`).
- `llm_mode`: `{mode: DISABLED|RECORDED, label}`.

A stage is `completed` only when its service result or audit event exists.

### 3.6 Mapping review (S08)

**`GET /api/cases/{ref}/review/{file_version_id}`** returns:

```json
{"case_ref", "package_id", "file_version_id", "evidence_category", "category_title", "original_filename", "version_number",
 "version_status", "review_kind": "HEADER_VARIANT|HEADER_COUNT_MISMATCH|DETERMINISTIC_CONFLICT|UNMAPPABLE_PROPOSAL|PROPOSAL_REVIEW",
 "review_reason", "editable", "canonical_fields": [{"name", "requiredness", "required", "type"}],
 "rows": [{"source_index", "source_position", "source_header", "suggested_field",
           "suggestion_basis": "deterministic|diagnostic_name_match|proposal|none", "proposal_assessment", "validation", "note",
           "needs_attention", "duplicate", "decided",
           "decision": {"action": "MAP|CHANGE|IGNORE", "backend_action", "canonical_field", "at", "reviewer"} | null,
           "field_type", "field_required", "financial", "samples": ["…" ×≤6], "available_actions": ["MAP", "CHANGE", "IGNORE"]}],
 "counts": {"attention", "decided", "remaining", "recognised"},
 "required_not_covered", "can_confirm", "file_actions": ["CONFIRM", "REJECT"]}
```

- Show only `needs_attention` rows by default; `recognised` rows are exact canonical headers (O2).
- `source_header` is the header exactly as received.
- The provenance tag comes from `suggestion_basis`: `deterministic` is EXACT or ALIAS, `diagnostic_name_match` is a variant needing a decision, `proposal` is an LLM proposal, `none` is NONE.

**`POST …/review/{vid}/decision`** with `{"action": "MAP"|"CHANGE"|"IGNORE"|"IGNORE_COLUMN"|"REJECT", "source_index": n, "canonical_field": "…" (CHANGE only), expected_revision?}`.
- There is no reason field (O4).
- `IGNORE_COLUMN` is accepted as `IGNORE`.
- `REJECT` is **file-level**: it rejects the file version and requests a correction, exactly like `/reject`.
- Returns the review (or the case detail for REJECT).
- Errors: `UNSUPPORTED_ACTION`, `RULE_CONTRADICTION`, `DUPLICATE_TARGET`, `VALUE_INCOMPATIBLE`, `OPERATION_RUNNING`, `CASE_NOT_ACTIVE`.

**`POST …/review/{vid}/confirm`** confirms the file mapping explicitly (O3).
- It is refused with `409 DECISIONS_OUTSTANDING` while `remaining > 0`.
- Recognised columns are confirmed with the file, then validation runs.
- Returns the case detail.

**`POST …/review/{vid}/reject`**: Reject / Request correction. Returns the case detail; the file appears in `outstanding.files_requiring_replacement`.

### 3.7 Activity: `GET /api/cases/{ref}/activity` (S14)

Returns `{case_ref, chain: {verified, events}, status_history, events: [{seq, event_id, event_type, at, actor_id, actor_role, intake_id, source_sha256, details}]}`, newest first.
- It covers case events and every run's package.
- `actor_role` `system` is a system actor; an analyst has the analyst role and ID.
- **Case events:** `CASE_CREATED`, `CASE_STARTED`, `CASE_RUN_STARTED`, `CASE_RUN_FAILED`, `CASE_RETRY_REQUESTED`, `CASE_DEFERRAL_REQUESTED`, `CASE_DEFERRED`, `CASE_RESUMED`, `CASE_COMPLETED`.
- **Analyst events:** `ANALYST_EVIDENCE_UPLOADED`, `ANALYST_REVIEW_CONFIRMED`, `ANALYST_CORRECTION_REQUESTED`, `ANALYST_VALIDATION_REQUESTED`, `ANALYST_ACTIVATION_REQUESTED`, `ANALYST_RECONCILIATION_REQUESTED`.
- **Other events:** service events (`PACKAGE_*`, `FILE_VERSION_*`, `INTAKE_*`, `RECONCILIATION_*`) and `REVIEW_COMPLETION_ROLLED_BACK`.

### 3.8 Customers (S03, S04)

- `GET /api/customers` returns `[{customer_id, customer_name, cases, by_status: {WAITING, IN_PROGRESS, PENDING, COMPLETED}}]`.
- `GET /api/customers/{customer_id}` returns `{customer_id, customer_name, cases: [CaseSummary…], reconciliation_history: [{case_ref, reporting_period, at, reconciliation_run_id, snapshot_id, case_status}]}`.

## 4. Evidence, snapshot and result endpoints (existing, unchanged)

`{pid}` is `case.package.package_id`, or a run's `package_id` for history. An earlier run's package is read-only.

| Purpose (screen) | Endpoint | Response (main fields) |
|---|---|---|
| Category registry, LLM mode, engine availability | `GET /api/app` | `reviewer`, `llm{mode,label}`, `engine_configured`, `categories[{category,title,required,format}]` |
| File version detail and history (S07, drawers) | `GET /api/packages/{pid}/versions/{vid}` | `version` (full model incl. `source_sha256`, `intake_id`, `status_history`, `handoff`), `history[]`, `decisions[]`, `events[]` |
| Source columns with samples (S07) | `GET /api/packages/{pid}/versions/{vid}/columns` | `columns[{source_header, samples, rows, empty, distinct}]` |
| Canonical preview (S07) | `GET /api/packages/{pid}/versions/{vid}/preview` | `text/csv` (whole file, not paged) |
| Package history: versions, snapshots, validations (S07, S10) | `GET /api/packages/{pid}/history` | `categories[{versions[…]}]`, `snapshots[]`, `validations[]` |
| Snapshot and manifest (S11) | `GET /api/packages/{pid}/snapshots/{sid}` | `snapshot{entries[]}`, `manifest`, `is_active`, `verification[SV-1..5]`, `reconciliation_eligible`, `runs[]` |
| Job progress (any job) | `GET /api/jobs/{job_id}` | `state` (`queued`, `running`, `completed`, `failed`, `interrupted`), `stages[]`, `files[]`, `progress`, `run_id` |
| Reconciliation results (S12) | `GET /api/runs/{run_id}` | `case_status`, `exception_count`, `total_results`, `outcomes{PASS,FAIL,…}`, `integrity_checks`, `exceptions[]` |
| Control results (S12) | `GET /api/runs/{run_id}/controls?outcome=&check=` | `{total, rows[≤2000], truncated}` |
| Engine report (S12) | `GET /api/runs/{run_id}/report` | `text/markdown` |
| Exception detail and supporting evidence (S13) | `GET /api/runs/{run_id}/exceptions/{exception_id}` | `exception`, `affected_control_results[]`, `evidence[{reference, evidence_category, file_version_id, intake_id, source_sha256, original_filename, version_number, line, row{…}}]`, `investigation_group`, `note` |

The reconciliation `run_id` for a case is `case.completed.reconciliation_run_id`, `case.progress.reconciliation.run_id`, or `package.jobs[kind=reconciliation].run_id`.

## 5. Refresh and polling

| While | Poll | Every |
|---|---|---|
| `current_run.status == "PROCESSING"`, or `progress.current_operation` not null, or `deferring` | `GET /api/cases/{ref}`, plus `GET /api/cases/{ref}/runs/{run_id}` on S06 | 3 s |
| `progress.reconciliation.state == "RUNNING"` | `GET /api/cases/{ref}` | 5 s |
| Always (queue, active-case slot) | `GET /api/cases` | 30 s and on window focus |
| After every mutation | refetch the case detail (and the review, on S08) | once |

- Never move a case to PENDING in the UI before the backend reports it.
- Never advance a stage on a timer.
- Stop polling once nothing runs.

## 6. Error codes the frontend should handle

- **400:** `INVALID`, `NOT_A_ZIP`, `FILE_TOO_LARGE`, `CONFIRMATION_REQUIRED`, `UNSUPPORTED_ACTION`, `RULE_CONTRADICTION`, `DUPLICATE_TARGET`, `VALUE_INCOMPATIBLE`, `INVALID_ZIP`.
- **404:** `NOT_FOUND`.
- **409:**
  - case lifecycle: `CASE_STATE`, `ACTIVE_CASE_EXISTS`, `CASE_NOT_ACTIVE`, `CASE_DEFERRING`, `CASE_COMPLETED`, `CASE_CHANGED`;
  - runs and operations: `RUN_FAILED`, `RUN_NOT_FAILED`, `OPERATION_RUNNING`;
  - evidence and packages: `PACKAGE_LOCKED`, `PACKAGE_SUPERSEDED`, `ALREADY_ACTIVATED`, `NOT_ACTIVATED`, `EVIDENCE_NOT_ACCEPTED`;
  - review: `DECISIONS_OUTSTANDING`, `REVIEW_STATE`, `SESSION_INCOMPLETE`;
  - package service: `PACKAGE_STATE`.
- **403:** `FORBIDDEN` (missing header), `NOT_AUTHORISED`.
- **500:** `INTERNAL`.

On any error, keep the button enabled and show the message. "Nothing was changed" holds for every 4xx: refused operations do not change state.

## 7. Differences from the design's assumptions (adapt in the adapter; no redesign)

| Design assumption | Backend reality | Adapter handling |
|---|---|---|
| `RunState` `QUEUED`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED` | Run `status` `PROCESSING`, `COMPLETED`, `FAILED`; no pause | PROCESSING becomes RUNNING. Never show PAUSED for a run: a deferred case shows its step as `paused`. |
| 11 Smart Parser stages | 9 real stages | Bind to the real keys and relabel (design permitted) |
| Package versions v1, v2… on upload | Per-file versions; package snapshots on activation | Show file version chains (`history`); "package version" means the snapshot |
| *Process uploaded files* (explicit batch) | Each upload is processed immediately, then validated | Hide that button (design open question 2: backend behaviour is automatic) |
| *Remove upload* | Not supported (staging is inert until used) | Do not offer |
| Mapping action `IGNORE_COLUMN`, `REJECT` | Accepted as given (`REJECT` is file-level) | none |
| `ReviewColumn.llmAssessment`, `alternatives`, sample row numbers, per-rule validation list | Not returned: `proposal_assessment`, `note`, `samples` (no row numbers) only | Show what is returned; omit the rest |
| `CaseDetail.accounts` (bank, masked) | Not returned | Omit |
| `Validation.trigger` | Not recorded | Omit |
| `Snapshot.activatedBy`, manifest SHA-256 | `case.activation.activated_by`, `activated_at`, `manifest_sha256` | none |
| `ReconRun.adapterRequestId` | None | Omit |
| `earlierDecision` (reference) | Not provided | Omit |
| Control description column | No catalogue (`check_id`, `control`, `note`) | Show `check_id` and `note` |
| Severities `HIGH`/`MEDIUM`/`LOW` | `Critical`/`High` | Map to the registry |
| Exception investigation (assign, comment, resolve) | Out of scope; nothing investigates exceptions | Read-only |
| Live LLM proposals | Not configured (`llm.mode` DISABLED or RECORDED) | Show `llm.label` verbatim; never claim live AI |

## 8. View model → endpoint mapping

| Design view model / field | Source |
|---|---|
| `ActiveCase` | `GET /api/cases` → `active_case` |
| `CaseSummary.ref/customer/period/zip/receivedAt/status/lastActivityAt` | `case_ref`, `customer_id`/`customer_name`, `reporting_period`, `zip`, `created_at`, `status`, `last_activity_at` |
| `CaseSummary.progress.steps/facts/live` | `steps[].state`, `progress.summary`, `progress.current_operation != null` |
| `deferralRequested`, `reconOutcome`, `otherCasesForPeriod` | `deferring`, `completed.case_status` or `progress.reconciliation.case_status`, `other_cases_for_period` |
| `CaseDetail.zip.sha256`, `statusSince`, `outstanding`, `kept`, `blockedBy`, `snapshotId` | `zip.sha256`, `status_since`, `outstanding`, `kept`, `blocked_by`, `package.active_snapshot_id` |
| `CaseDetail.package.state` | `package.package_status` (and the per-file `version_status`) |
| `Run` | `runs[]` and `GET …/runs/{run_id}` (`stages`, `events`, `failure`, `retry_of`, `evidence_source`) |
| `EvidenceFile` | `package.slots[].latest` plus `GET /packages/{pid}/versions/{vid}` |
| `ReviewColumn` | `GET …/review/{vid}` → `rows[]` where `needs_attention` |
| `Validation` | `package.latest_validation` plus `progress.validation` |
| `Snapshot` | `GET /packages/{pid}/snapshots/{sid}` plus `case.activation` |
| `ReconRun`, `ReconException` | `GET /runs/{run_id}`, `/controls`, `/exceptions/{id}` |
| `ActivityEvent` | `GET /api/cases/{ref}/activity` → `events[]`, with `statusChange` from `status_history` |
