# UC-042 Smart Parser: browser application implementation report

**Date:** 19 Nov 2026

**Working copy:** `C:\Users\artlptp263user\p10\smartparser_phase1` (isolated Smart Parser working copy)

**Evidence folder:** `Downloads\UC042_BROWSER_APP_BUILD\`

| Item | Location |
|---|---|
| Plan | `01_ARCHITECTURE_AND_IMPLEMENTATION_PLAN.md` |
| Major-screen screenshots | `screenshots/` |
| Browser journeys (178 screenshots, a result JSON per journey, server logs) | `journeys/J1..J6/` |
| Regression run | `regression/` |
| Pre-change hashes and tarball | `baseline/` |

## 1. Summary

The POC is now one connected browser application, **Safeguarding Evidence Processing**. An analyst can carry out the whole lifecycle in the browser:
1. upload a package (a ZIP or individual files);
2. watch real processing progress;
3. review mappings with the source values on screen;
4. validate (PV-01 to PV-09) and activate with explicit confirmation;
5. correct and resubmit files;
6. run the real UC-042 reconciliation;
7. inspect results, exceptions and their evidence;
8. read the audit trail.

The design system is in the application's stylesheet and a living reference page (`/design.html`).

**Results:**
- Every screen calls the existing services: PackageService, review_api, `run_reconciliation` and AuditLog. No business logic was duplicated and no outcome is hard-coded.
- **Browser E2E:** 6 journeys, **123/123 checks pass**, no JavaScript errors. All reconciliations match the original UC-042 answer keys:
  - clean;
  - S05 (HITL);
  - rejection and resubmission;
  - mixed quality;
  - all 9 exception datasets;
  - both CSV defects.
- **Regression:** 630/630 tests pass (620 existing + 10 new). The CSV baseline (445/445), the variation corpus (161/161) and the registry are unchanged.
- **Defects:** DEF-E2E-01 and DIV-E2E-02 are fixed and tested. The five smaller UI items are addressed.
- **Integrity:** the protected trees are hash-identical, and no database, live LLM, audit pack or submission was used.

## 2. Screens implemented

Every screen below is live; the screenshots are in `screenshots/`.

| # | Screen | Route | What it shows / does | Screenshot |
|---|---|---|---|---|
| 1 | Overview | `#/overview` | Current package facts: files received, identified by content, validated, requiring review, missing / failed, validation, activation, latest reconciliation. A next-step callout, recent packages, a primary "Start new evidence intake" button, and an empty state when there is no package. | `01_overview`, `overview_empty_state` |
| 2 | Evidence intake | `#/intake` | Reporting period; drag and drop or file picker (CSV / PDF / ZIP, with the ZIP expanded); a list of staged files with name, size, type, SHA-256, upload status, optional declared category and remove; submit creates the package and starts processing. | `02_evidence_intake` |
| 3 | Processing centre | `#/processing/{job}` | Nine stages with Pending / Running / Completed / Requires review / Not required / Activation blocked, start and finish times, and the evidence (service result or audit event) behind each stage. The real "n of N files" count, a per-file result table, a live recorded-event feed, and next-step buttons. | `03_processing_centre` |
| 4 | Evidence files | `#/packages/{id}` | One row per slot: category, required or optional, file, identified by content or declared, route, status, reason and next action. Refused uploads are listed for traceability. | `04_evidence_classification_file_status` |
| 5 | Mapping review | `#/review`, `#/review/{pkg}/{v}` | **Queue:** the diagnosis is now visible (duplicate positions, extra headers, missing fields). **Review:** position, source column, **sample source values**, proposed field (type, required), LLM assessment, alternative candidates, validation, Financial / Sign-sensitive / Required flags, and the decision. The expandable row holds all samples, statistics (distinct / empty / negative), explanation, provenance (SHA-256, intake), the field definition and the actions: Map, Map to selected field (CHANGE), Use this column as the source (CHOOSE_DUPLICATE_SOURCE), Ignore, Leave unresolved, each with a reason. Also: Complete review, Reject file (confirmation dialog), "Why this review", "If left unresolved", the TEST-ONLY banner, and the outcome with the 14 handoff checks and a preview link. | `05a`–`05c`, `14_reject_dialog` |
| 6 | Package validation | `#/validation/{id}` | PV-01 to PV-09 (result, evidence, whether it blocks activation, required action); slot summary; a status legend for FAILED_VALIDATION / REVIEW_REQUIRED / RESUBMISSION_REQUIRED / VALIDATED / ACTIVE; the selection that activation would snapshot; a "Run validation now" button. | `06a` (blocked), `06b` (passed) |
| 7 | Activation | dialog on screen 6 | Enabled only when the latest **real** validation passed. The dialog shows the package, version count and snapshot effect, and states "no submission, no audit pack". The result shows the snapshot and next steps. | `07a`, `07b` |
| 8 | Package history | `#/history/{id}`, `#/history/{id}/{v}`, `#/snapshot/{id}/{s}` | Snapshots, validation runs and versions per category (intake time, SHA-256, status history, previous version, replacement reason). Version detail adds review decisions, handoff checks and recorded events. Snapshot detail adds SV-1 to SV-5, the manifest status and reconciliation eligibility. | `08a`–`08c` |
| 9 | Resubmission | `#/resubmit/{id}` | Every category awaiting correction (status, reason, missing fields, what to correct); upload of a corrected file with a reason; upload of missing evidence. The page states the rules: no voluntary replacement, identical bytes refused, fresh review. | `09a`, `09b` |
| 10 | Reconciliation | `#/reconciliation/{id}` | Package, active snapshot, active version count, eligibility and the reason when not eligible; run button; four real run stages; outcome totals; previous runs. | `10a`, `10b` |
| 11 | Results dashboard | `#/runs/{run}` | Status, total controls, PASS, FAIL, INSUFFICIENT_EVIDENCE, NOT_APPLICABLE, exceptions by severity; tabs for Exceptions (filters for severity / account / currency / status, plus search), Control results (outcome and check filters), the Validation report, and Inputs & integrity. | `11a`–`11d` |
| 12 | Exception detail | `#/runs/{run}/exceptions/{id}` | Description, financial impact, account, dates, flags, related records, evidence status, engine review status, **supporting evidence resolved to file version / line / canonical row**, associated control results and investigation group. All are engine output; no decision is invented. | `12_exception_detail` |
| 13 | Activity & audit | `#/activity/{id}` | The hash-chained audit log, verified on load, grouped by day; type and package filters; actor, IDs and the full recorded details. Only recorded events are shown. | `13_activity_audit` |
| – | Design system | `/design.html` | Tokens, typography, status vocabulary, actions, feedback, dialogs, tables, stepper, progress, empty / loading / error states, timeline, and the inventory of the 13 screens with their APIs. | `design_system_reference` |

**Design system:**
- **Styling:**
  - light theme with neutral surfaces and one blue-teal accent;
  - semantic colours used only for status;
  - system UI fonts (offline) and tabular figures;
  - monospaced IDs and hashes;
  - sticky table headers.
- **Behaviour and accessibility:**
  - confirmation dialogs for activation and rejection;
  - toasts only after a successful server answer;
  - skeleton loading, empty states and verbatim error states;
  - keyboard-reachable rows;
  - a CSP that blocks inline scripts.
- **No external assets.**

## 3. Backend endpoints and services connected

The application lives in the new package `smartparser/webapp/`:
- `server.py`: stdlib ThreadingHTTPServer;
- `api.py`: routes and views;
- `context.py`: services, staging and jobs;
- `results.py`: read-only views of the engine's outputs;
- `static/`.

Safety rules:
- It binds to 127.0.0.1 only.
- POST requests need the `X-Smartparser-Client` header, which blocks cross-site requests.
- Static files come from an allow-list only.
- A single service lock serialises mutations.

| Endpoint | Service called |
|---|---|
| `GET /api/app` | configuration: reviewer, authority policy, LLM mode, engine configured, categories (registry) |
| `GET/POST /api/packages` | `PackageService.create_package`; package summaries from `PackageStore` |
| `POST /api/staging` | stores the upload bytes (ZIP expanded; hidden and system entries skipped). Nothing is classified here. |
| `POST /api/packages/{id}/intake` | background job: `PackageService.submit` one file at a time, in the service's own CSV-before-PDF order, then `validate()` |
| `GET /api/jobs/{id}` | job state; stages derived from service results and audit events |
| `GET /api/packages/{id}` | `PackageStore`, `pending_resubmissions` |
| `GET /api/reviews` | `review_api.list_reviews` |
| `GET /api/review/{p}/{v}` | `review_api.review_detail`, plus a column profile read from the stored original (SHA-256 verified) with the existing `identify` / `read_csv` |
| `POST /api/review/{p}/{v}/decision`, `/reject`, `/complete` | `review_api.decide`, `review_api.reject`, `review_api.complete`, which run `PackageService.decide` / `review_session` / `reject_review` / `complete_review` |
| `GET /api/packages/{id}/validation`, `POST /validate` | `PackageService.validate`, `candidate` |
| `POST /api/packages/{id}/activate` `{confirm:true}` | `PackageService.activate` |
| `GET /api/packages/{id}/snapshots/{s}` | `store.load_snapshot`, manifest, `verify_snapshot` |
| `GET /api/packages/{id}/history`, `/versions/{v}` (`/columns`, `/preview`) | `PackageStore`, `review_detail`, audit events |
| `POST /api/packages/{id}/resubmit` | background job: `PackageService.resubmit`, only for categories in `pending_resubmissions` |
| `POST /api/packages/{id}/reconcile` | background job: `reconciliation.uc042_adapter.run_reconciliation`, only for the active snapshot |
| `GET /api/runs/{run}` (`/controls`, `/report`, `/exceptions/{id}`) | the engine's own `reconciliation_run.json`, `exceptions.csv`, `control_results.csv`, `VALIDATION_REPORT.md` |
| `GET /api/activity` | `AuditLog.verify()` plus a read-only view of the events |

**Honest progress:** there are no timers and no percentages beyond real counts. Each file is a real service call, and a stage is marked completed only from the service's result or a recorded event:
- PACKAGE_CREATED;
- PROVIDER_CALL;
- FILE_VERSION_REVIEW_REQUIRED;
- HANDOFF_PREVIEW_WRITTEN;
- PACKAGE_VALIDATION_*;
- RECONCILIATION_*.

The engine reports no progress while it runs in its own process, so the UI shows an indeterminate bar there.

**Run it:**
```
py -3.11 -m smartparser.webapp.server --root <empty workspace> \
   --authority tests/fixtures/review/test_authority_policy.json \
   --uc042-root <read-only UC-042 tree, e.g. the E2E bundle's src/uc042> \
   [--recorded-llm <fixture.json> ...] --reviewer-id <id> --port 8780
```
Then open `http://127.0.0.1:8780/`.

## 4. Defects fixed

The fixes are minimal and live in the existing code.

| ID | Fix | Test |
|---|---|---|
| **DEF-E2E-01** (short CSV row raised `IndexError`) | `handoff/eligibility.py::_source_cells_preserved`: a row whose cell count differs from the header now fails check 12 ("row N has k cell(s), the header has m: … not repaired"). The file becomes FAILED_VALIDATION, fail-closed with no preview, the source is kept byte for byte, and **the other files of the same submission are processed**. | `tests/test_csv_defect_fixes.py`; journey J6 |
| **DIV-E2E-02** (header-only CSV VALIDATED) | Check 11 now fails when there are zero data rows and the registry's existing `csv.empty_allowed` is false. That flag is imported from UC-042 `schema.EMPTY_ALLOWED`, so IN-04 and IN-14 may still be empty, exactly as UC-042. The detail reads "no data rows: … (UC-042 reports EMPTY_FILE)". | same; J6 |
| 1-based column numbering | `review/intake.py`: the duplicate-source reason now reads "authoritative column is #7 (balance)", and its error message also uses 1-based positions. The new UI shows 1-based positions everywhere. | defect test 3 |
| Stale completion text | After completion the finalisation line and the action bar are removed. The outcome shows the current state, and the reason history moves into a collapsible section. | J2.09 |
| Map / APPROVE terminology | One vocabulary: the "Map" button and a recorded APPROVE are both shown as **Mapped**. Other labels: Mapped (changed field), Chosen as source, Ignored, Left unresolved, Deterministic. | design reference §3 |
| Duplicate diagnosis in the queue | `review_api.list_reviews` gains the additive fields `duplicate_headers` (1-based), `extra_headers` and `missing_fields`, shown in the queue's Diagnosis column. | defect test 3, API test |

No other behaviour changed. The old POC review screen (`review_ui/`) is untouched, and its Edge regression test still passes.

## 5. Workflow coverage: browser E2E

The journeys are run by `tools/webapp_journeys.py`. Each one starts the real application server on a fresh temporary workspace and drives headless Microsoft Edge only through the page's controls:
- real uploads through the file inputs;
- selects, reason fields and buttons;
- the confirmation dialogs.

Its environment:
- **Engine:** the E2E bundle's read-only UC-042 copy.
- **LLM:** the recorded fixture `in10_ambiguous` (offline).
- **Authority:** the TEST-ONLY policy, with `kind=TEST` identities.

**Answer keys:** results are compared with the bundle's original answer keys using UC-042's own `compare_answer_key`, and with the reference exception rows.

| Journey | What it demonstrates | Checks |
|---|---|---|
| **J1 Clean** | ZIP upload (19 files), all identified by content and VALIDATED; stages derived from events; PV-01..09 PASS; confirmed activation; reconciliation **CLEAN, 1,886 PASS, 0 exceptions** = E2E-01; all four result tabs, snapshot, history, verified audit chain | 8/8 |
| **J2 HITL + exceptions** | S05 with renamed IN-10 headers and an extra IN-05 column. The recorded proposal is shown, and activation is disabled while reviews are open. The review grid shows **sample values** and flags `txn_amt` as sign-sensitive; a missing reason is refused by the backend. Four TEST-ONLY decisions are made (reasons based on the values shown) and IN-05 is ignored and mapped. Both files VALIDATED; reconciliation **EXCEPTIONS_OPEN**: Critical −812.40 SGA-GBP-01 (11 results), High BE-GBP-0917-X01 (2). **S05 answer key matched**; the exception detail resolves 21 evidence references to file versions and rows. | 23/23 |
| **J3 Rejection + resubmission** | IN-03 without `balance`: the UI warns that completing will HOLD, and the file ends RESUBMISSION_REQUIRED ("balance"). IN-10 is mapped and then rejected through the dialog. Activation is blocked (PV-02, PV-03) with the button disabled. The corrected IN-03 v2 goes through the resubmission screen, and its **fresh review starts with zero decisions**. IN-10 v2 is canonical. Final states: IN-03 [SUPERSEDED, ACTIVE] and IN-10 [REJECTED, ACTIVE]. **CLEAN, baseline answer key matched.** | 12/12 |
| **J4 Mixed quality + scanned PDF** | IN-08 missing, V02 table-layout PDF, **V06 image-only PDF**, IN-05 extra column, unknown CSV. The PDFs are FAILED_VALIDATION, with V06 reported as "Image-only (scanned) PDF … OCR is not supported, so the category cannot be determined" on the processing screen. The unknown CSV is listed as refused. Activation is blocked (PV-01..04, "IN-08" named). Recovery covers the review, the missing IN-08 upload and the two PDF resubmissions; then PV all pass and the result is **CLEAN**. | 13/13 |
| **J5 Exception analysis** | All 9 datasets, each uploaded as a ZIP: clean, SC2, S05, SC3C, SC5A, SC5D, SC5C (17 exceptions), SC3B, S02 (EVIDENCE_INCOMPLETE). Status, exception count, **every UI exception row** (ID, severity, account, amount, affected results), **every engine row** (all compared columns) and **UC-042 compare_answer_key** all match for every dataset. | 63/63 |
| **J6 CSV defects** | One upload holding a short-row IN-01, a header-only IN-11 and valid IN-02 / IN-03. The two bad files are FAILED_VALIDATION with check 12 / check 11 explanations visible in the version detail, and **the valid files in the same upload are VALIDATED**. | 4/4 |

All six journeys report **123/123 checks, 0 JavaScript errors, 178 screenshots.**

## 6. Regression

The regression run is in `regression/`.

| Suite | Result |
|---|---|
| Full suite | **630 passed**: 620 existing (including Experiment A and the Edge test of the old review screen) + 3 defect tests + 7 webapp API tests |
| Without the UC-042 tree | 624 passed, 6 skipped |
| Per-phase suites 3B-0 … 3B-11, Phase 1, Phase 2 | all pass |
| Registry | in sync (19 definitions) |
| CSV baseline classification | 445/445 |
| Variation corpus | 161/161 |
| Production rules | aliases / layouts empty, 0 approved proposals, no policy roles (unchanged) |

## 7. Remaining limitations

1. **Single-user POC.**
   - There is no authentication; the reviewer identity is fixed when the server starts. The UI says so, and every action still goes through the authority policy.
   - The **TEST-ONLY** policy is required, because the production policy authorises nobody.
   - The store is file-based, with one in-process lock.
2. **Simulated LLM:** proposals come from **recorded fixtures** or are disabled. No live provider is wired into this app.
3. **PDFs:** classification only. There is no value extraction and no OCR, and the UI says so.
4. **No percentage while the engine runs:** reconciliation runs in its own process and reports no progress, so the UI shows an indeterminate bar and the real stage events instead of a percentage.
5. **Out of scope:** investigation decisions, exception resolution, audit-pack generation and submission. Only the engine's own fields are shown, such as `status` and `review_status = AWAITING_HUMAN_REVIEW`.
6. **Jobs and restarts:** job records persist in the workspace. A job interrupted by a server restart is shown as "interrupted" and is never resumed automatically.
7. **Bundle expectations are now outdated:** the E2E bundle in Downloads still asserts DEF-E2E-01 and DIV-E2E-02 *as observed*, so after these fixes its E2E-05 expectations need updating. The bundle was deliberately left unchanged.
8. **Desktop layout:** the layout targets desktop widths. A narrow-screen fallback exists but was not part of the tests.

## 8. Protected-source integrity

| Item | Result |
|---|---|
| `p10\uc042_token_optimisation` (authoritative UC-042) | 107 code + 624 dataset files hash-identical; 0 newer files |
| Desktop Smart Parser | 63 files hash-identical |
| Clone E (`p10\uc042_e`) | 0 files changed |
| E2E bundle (Downloads copy and the `C:\u42x` working copy) | integrity check passes; not modified |
| Active demo DB, production data, audit packs | not accessed |
| Live LLM / submission / audit-pack generation | none |
| Working copy changes | **3 files modified**: `handoff/eligibility.py`, `review/intake.py`, `packages/review_api.py` (additive field). **13 files added**: `smartparser/webapp/*` (10), `tests/test_csv_defect_fixes.py`, `tests/test_webapp_api.py`, `tools/webapp_journeys.py`. Everything else is hash-identical to the Stage 1 baseline (`baseline/`). |
