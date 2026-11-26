# Ringfence · Analyst application (React + Vite)

The functional analyst UI for UC-042 Moorwand Safeguarding. It covers screens S01–S14 of the Ringfence design system and the whole analyst workflow: register a case, start Smart Parsing, review mappings, upload corrections, validation and activation, reconciliation, exceptions and activity.

The same source runs in two places:

- **This Vite app**, through `src/main.jsx`.
- **The live "Analyst application" card** in the Ringfence design system. `npm run build:card` compiles `src/card-entry.jsx`, which imports the same `src/app`, into `dist-card/analyst-app.js`. That file is appended to the design system's `components/bundle.js` as `window.Ringfence.AnalystApp`.

## Status: what is real and what is mocked

| Part | Status |
| --- | --- |
| Screens, navigation, dialogs, polling, error handling | Implemented in React. They render backend payloads exactly as the contract defines them. |
| `src/services/httpService.js` | Backend adapter written to `RINGFENCE_FRONTEND_API_CONTRACT.md`: same endpoints, bodies, headers and error shape. **It has not yet been run against the backend.** |
| `src/services/mockService.js` + `mockData.js` | **Temporary mock.** It runs in the browser with synthetic data and calls no backend. It returns the contract's payload shapes. Processing (Smart Parser stages, validation, reconciliation) is simulated with timers. The mock imitates the backend's lifecycle rules so that every screen can be exercised; the backend remains the owner of those rules. |

The mock is labelled in the UI by the amber **MOCK DATA SERVICE** bar at the bottom of every screen and on the sign-in screen. With the backend selected, the bar instead reads *Backend · Ringfence server via /api*.

## Run it

Requires Node 18 or later.

```bash
npm install
npm run dev            # http://localhost:5173 using the mock data service
```

**Against the Ringfence backend:**

1. Start the server as the contract §1 describes: `py -3.11 -m smartparser.webapp.server … --port 8780`.
2. Run `npm run dev:backend`. This loads `.env.backend` (`VITE_DATA_SERVICE=http`).
   - Vite proxies `/api` to `http://127.0.0.1:8780`. Set `RINGFENCE_API=http://host:port` to use another address.
   - The server sends no CORS headers and its CSP is `default-src 'self'`, so the app must reach the API on the same origin, here through the proxy.
3. You can also switch the service with a URL parameter: `?service=http` or `?service=mock`.

**Production build:** `npm run build` writes `dist/`. Serve it from the same origin as `/api`, either from the backend or behind a reverse proxy that forwards `/api`.

**Design-system card bundle:** `npm run build:card` writes `dist-card/analyst-app.js`, a single classic script with React included. The card always uses the mock.

### Demo data (mock)

| Case | Customer | Start state | Journey |
| --- | --- | --- | --- |
| RF-2026-10-004 | Kestrel Card Services | Waiting | **Clean.** Start, review 2 columns, confirm, validation passes, activate, reconcile → `CLEAN` |
| RF-2026-10-006 | Fernhill Pay | Waiting | **Correction.** FX file fails its structure check (`RESUBMISSION_REQUIRED`); a required category is missing; upload corrections as new file versions |
| RF-2026-10-005 | Northgate E-Money | Waiting | **Exceptions.** Review 4 columns, activate, reconcile → `EXCEPTIONS_OPEN` with 6 exceptions, including `INSUFFICIENT_EVIDENCE` and `NOT_APPLICABLE` control results |
| RF-2026-10-007 | Harbourline Payments | Waiting | Reconciliation ends `EVIDENCE_INCOMPLETE`; a second case for the same customer and period |
| RF-2026-10-002 | Quayside FX | Pending | Failed run (`EVIDENCE_STORE_TIMEOUT`): Resume, then Retry from Beginning |
| RF-2026-10-003 | Ashgrove Card | Pending | Partial review with a kept decision |
| RF-2026-10-001 | Harbourline Payments | Completed | `EXCEPTIONS_OPEN`, with history: deferrals, rejected file, uploads, failed reconciliation run then a completed run |
| RF-2026-09-001 | Ashgrove Card | Completed | `CLEAN` |

The bar's **Simulate…** menu can fail the next Smart Parser run, fail the next reconciliation, run processing four times faster, or reset the demo data. These controls are mock-only and not part of the contract.

## Integration with the Smart Parser backend (p10/smartparser_phase1, 19 Nov 2026)

This app has now been run against the real backend (`smartparser.webapp.server`, a standard-library HTTP server; no FastAPI). The original delivery is kept unchanged in `Downloads/ringfence-analyst-app.zip`.

**Same-origin build, served by the backend at `/analyst/`:**

```
cd ringfence-analyst-app
npm install --offline          # dev deps aligned to the offline npm cache: vite 5.4.21, @vitejs/plugin-react 4.7.0, esbuild 0.21.5
npm run build:backend          # vite build --mode backend -> ../smartparser/webapp/analyst/ (base /analyst/, data service = http)
cd ..
py -3.11 -m smartparser.webapp.server --root C:\u42v\rf_ws --authority tests\fixtures\review\test_authority_policy.json ^
   --uc042-root C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\src\uc042 ^
   --reviewer-id analyst-1 --reviewer-role analyst --reviewer-kind TEST --port 8780
# open http://127.0.0.1:8780/analyst/   (restart the backend after a rebuild: the served file list is read at startup)
```

**Development (hot reload, `/api` proxied):** run `npm run dev:backend`, then open http://127.0.0.1:5173/analyst/ (the backend mode uses base `/analyst/`). Set `RINGFENCE_API` if the backend is not on port 8780.

**Changes made during integration.** These fix the app against the actual backend payloads; nothing was redesigned.
- `httpService.getReconRun`: `/api/runs/{id}` exists only for a completed run. The response is marked `state: COMPLETED`, and `executed_at` is exposed as `finished_at`.
- `Recon.jsx`:
  - A running or failed latest run is shown from `case.progress.reconciliation`, without a fetch.
  - `integrity_checks` is a `{name: passed}` object.
  - Exceptions use `category`, `account_id` and `first_date`/`last_date`.
  - Control rows use `scope`.
  - Affected results read `control_result`.
  - The investigation group is an object and crashed React. It is now rendered field by field.
- `Evidence.jsx`:
  - `/api/staging` returns `{entries: [{staging_id}]}`; reading a top-level `staging_id` made every upload fail.
  - The received time is `uploaded_at`.
  - Mapping decisions are under `decision`.
  - Validation history uses `failed[]`.
- `Package.jsx`: validation history uses `failed[]` and marks the latest row; snapshot runs show `case_status`.
- `Parser.jsx`:
  - A file's `outcome` is an object and crashed React. It is now rendered as a status pill.
  - `skipped_entries` is a list.
  - The running file state is `running`.
  - The stage `detail` is shown.
- `Activity.jsx`: adds labels for `PACKAGE_VALIDATED` and `RECONCILIATION_EXECUTED`.
- `Review.jsx`: a `LEAVE_UNRESOLVED` decision is not preselected.
- `mockService.stageFile` returns the backend's shape.
- `vite.config.js` adds the `backend` build mode.

**Browser end-to-end test:** `py -3.11 -B tools/analyst_app_journey.py --bundle <E2E bundle> --out <dir> --scenarios <json> [--mode dev]`.

## Structure

```
src/
  main.jsx                 Vite entry: picks the data service, creates the store, renders <App>
  card-entry.jsx           Design-system card entry (mock service, memory routing)
  app/
    App.jsx                Shell (top bar, active-case slot, routing, toasts, data-service bar)
    CaseWorkspace.jsx      Case header, lifecycle actions (Start, Defer, Resume, Retry dialogs), banner, tabs
    store.js               Route, simulated session, toasts, query cache, mutation handling
    hooks.js               useQuery (cache and polling), useMutation (busy, verbatim error), useAppState
    format.js              UK-time formatting and display mapping of backend enums
    screens/               Login (S01), Queue (S02), Register (S02/O8), Customers (S03), Customer (S04)
    case/                  Overview (S05), Parser (S06), Evidence (S07/S10), Review (S08),
                           Package (S09/S11), Recon (S12/S13), Activity (S14)
  services/
    dataService.js         Method inventory (METHODS) and assertDataService
    httpService.js         Backend adapter (contract)
    mockService.js         Temporary mock (same methods and payloads)
    mockData.js            Synthetic demo content used only by the mock
    index.js               createDataService('http' | 'mock')
  ui/                      React port of the design-system helpers (same markup and class names)
  styles/                  tokens.css and ringfence.css (design system), plus app-*.css additions
```

## How the screens use the backend

- **The backend owns the rules.**
  - Buttons follow `case.actions.<name>.enabled`; when a button is disabled, its `reason` is shown beside it.
  - Step states come from `steps[]` and progress text from `progress.summary`.
  - Outstanding work comes from `outstanding` and `kept`.
  - Review editing follows `editable`, `available_actions`, `can_confirm` and `file_actions`.
  - The UI never derives a lifecycle state and never advances a stage on a timer.
- **Mutations:**
  - Every POST sends `X-Smartparser-Client: webapp`.
  - Case mutations send `expected_revision`.
  - Activation sends `{confirm: true}`, only after the acknowledgement is ticked; Retry sends `{confirm: true}` after confirmation.
  - Uploads are two calls: `POST /api/staging`, then `POST /api/cases/{ref}/evidence`.
  - After every mutation, all mounted queries refetch (§5) before the button is released.
  - Errors show the backend `message` verbatim and the button stays enabled. `409 CASE_CHANGED` reloads the data.
- **Polling (§5):**
  - Case detail every 3 s while a run is `PROCESSING`, `current_operation` is set, or `deferring` is true; every 5 s while reconciliation is `RUNNING`.
  - The run detail on the Smart Parser tab polls during processing.
  - The queue polls every 30 s and on window focus.
  - Polling stops when nothing runs. The mock polls faster because it puts no load on a server.
- **Times** are ISO UTC from the backend and are shown in UK time (Europe/London).

## Data-service method inventory and API mapping

Both services implement every method; `assertDataService` refuses one that is incomplete. Payloads are the contract's, unchanged (snake_case).

| Method | HTTP | Endpoint | Request body | Response |
| --- | --- | --- | --- | --- |
| `getApp` | GET | `/api/app` | — | { reviewer, llm, engine_configured, categories } |
| `listCases` | GET | `/api/cases[?status=]` | — | { items: CaseSummary[], counts, active_case_ref, active_case, ordering } |
| `registerCase` | POST | `/api/cases` | `{ customer_name, reporting_period, zip_name, zip_b64, customer_id? }` | CaseDetail |
| `getCase` | GET | `/api/cases/{ref}` | — | CaseDetail |
| `startCase` | POST | `/api/cases/{ref}/start` | `{ expected_revision? }` | CaseDetail |
| `deferCase` | POST | `/api/cases/{ref}/defer` | `{ expected_revision? }` | CaseDetail |
| `resumeCase` | POST | `/api/cases/{ref}/resume` | `{ expected_revision? }` | CaseDetail |
| `retryCase` | POST | `/api/cases/{ref}/retry` | `{ confirm: true, expected_revision? }` | CaseDetail |
| `validateCase` | POST | `/api/cases/{ref}/validate` | — | CaseDetail |
| `stageFile` | POST | `/api/staging` | `{ name, data_b64 }` | { staging_id } |
| `submitEvidence` | POST | `/api/cases/{ref}/evidence` | `{ staging_id, category }` | { job_id, case } |
| `activateCase` | POST | `/api/cases/{ref}/activate` | `{ confirm: true }` | { activated, reason, snapshot_id, case } |
| `reconcileCase` | POST | `/api/cases/{ref}/reconcile` | `{ expected_revision? }` | { job_id, case } |
| `getRun` | GET | `/api/cases/{ref}/runs/{run_id}` | — | Run + { stages, events, llm_mode } |
| `getReview` | GET | `/api/cases/{ref}/review/{vid}` | — | Review |
| `postDecision` | POST | `/api/cases/{ref}/review/{vid}/decision` | `{ action, source_index, canonical_field?, expected_revision? }` | Review (CaseDetail for REJECT) |
| `confirmReview` | POST | `/api/cases/{ref}/review/{vid}/confirm` | `{ expected_revision? }` | CaseDetail |
| `rejectReview` | POST | `/api/cases/{ref}/review/{vid}/reject` | `{ expected_revision? }` | CaseDetail |
| `getActivity` | GET | `/api/cases/{ref}/activity` | — | { case_ref, chain, status_history, events } |
| `listCustomers` | GET | `/api/customers` | — | CustomerSummary[] |
| `getCustomer` | GET | `/api/customers/{customer_id}` | — | { customer_id, customer_name, cases, reconciliation_history } |
| `getFileVersion` | GET | `/api/packages/{pid}/versions/{vid}` | — | { version, history, decisions, events } |
| `getVersionColumns` | GET | `/api/packages/{pid}/versions/{vid}/columns` | — | { columns } |
| `getVersionPreview` | GET | `/api/packages/{pid}/versions/{vid}/preview` | — | text/csv (whole canonical preview) |
| `getPackageHistory` | GET | `/api/packages/{pid}/history` | — | { categories, snapshots, validations } |
| `getSnapshot` | GET | `/api/packages/{pid}/snapshots/{sid}` | — | { snapshot, manifest, is_active, verification, reconciliation_eligible, runs } |
| `getJob` | GET | `/api/jobs/{job_id}` | — | { state, stages, files, progress, run_id } |
| `getReconRun` | GET | `/api/runs/{run_id}` | — | { case_status, exception_count, total_results, outcomes, integrity_checks, exceptions } |
| `getControls` | GET | `/api/runs/{run_id}/controls?outcome=&check=` | — | { total, rows, truncated } |
| `getReport` | GET | `/api/runs/{run_id}/report` | — | text/markdown (engine report) |
| `getException` | GET | `/api/runs/{run_id}/exceptions/{exception_id}` | — | { exception, affected_control_results, evidence, investigation_group, note } |

## Screens → methods

| Screen | Route | Methods |
| --- | --- | --- |
| S01 Sign in (simulated; there is no login API) | `#/login` | `getApp` |
| S02 Work queue | `#/queue[?status=]` | `listCases` |
| S02 / O8 Register case | `#/register` | `listCustomers`, `registerCase` |
| S03 Customers | `#/customers` | `listCustomers` |
| S04 Customer profile | `#/customers/{id}` | `getCustomer` |
| S05 Case overview | `#/cases/{ref}/overview` | `getCase`, `startCase`, `deferCase`, `resumeCase` |
| S06 Smart Parser | `#/cases/{ref}/parser[/{run_id}]` | `getRun`, `retryCase` |
| S07 / S10 Evidence and corrections | `#/cases/{ref}/evidence[/{vid}][?upload=IN-xx]` | `getFileVersion`, `getVersionColumns`, `getVersionPreview`, `getPackageHistory`, `stageFile`, `submitEvidence` |
| S08 Mapping review | `#/cases/{ref}/review[/{vid}]` | `getReview`, `postDecision`, `confirmReview`, `rejectReview` |
| S09 / S11 Validation and activation | `#/cases/{ref}/package` | `getCase` (`latest_validation`), `activateCase`, `getSnapshot` |
| S12 Reconciliation | `#/cases/{ref}/recon[/{run_id}]` | `reconcileCase`, `getReconRun`, `getControls`, `getReport` |
| S13 Exception detail (drawer) | `#/cases/{ref}/recon/{run_id}/{exception_id}` | `getException` |
| S14 Activity | `#/cases/{ref}/activity` | `getActivity` |

`validateCase` and `getJob` are implemented but no screen calls them:

- Validation runs automatically, and the design has no button for it (contract §3.4).
- The case detail already reports job progress.

## Integration gaps to check against the backend

1. **First live run.** `httpService` follows the contract but has not been exercised against the server. Run each journey with `npm run dev:backend` and compare the responses with the mock's.
2. **Field names the contract does not list.** The screens read these defensively:
   - Reconciliation `exceptions[]` and `exception{}`: the UI uses `exception_id`, `severity`, `title`, `root_cause`, `account`, `currency`, `period`, `amount`, `affected_results`.
   - Control rows: `check_id`, `control`, `account`, `outcome`, `note`.
   - Package history `snapshots[]` and `validations[]`.
   - Snapshot `entries[]`.
   - File version `handoff`.
   - `reviewer.name`: the UI falls back to `reviewer_id`.
3. **Validation checks carry no blocking flag.** Every failed PV check is shown as blocking. The precedence between `FAILED_VALIDATION`, `REVIEW_REQUIRED` and `RESUBMISSION_REQUIRED` is taken from `version_status` as sent.
4. **Severity.** The engine's `Critical` / `High` are shown as written, with the design's three-step bars (Critical = 3, High = 2).
5. **Sign-in is simulated (S01).** Identity is `GET /api/app` → `reviewer.reviewer_id`, and Sign out only clears the client session.
6. **Upload limits.** The client checks only for presence and a `.zip` extension. The backend enforces its limits (ZIP 50 MB, body 120 MB) and its error messages are shown as sent.
7. **Rapid decisions.** Each decision changes the case `revision`. The UI waits for the refetch before it releases the button, so the next call sends the new revision. If another client changes the case, `CASE_CHANGED` reloads it.
8. **Reports and previews** (`text/markdown`, `text/csv`) are shown as plain text.
