# 09 — Phase 3: React Frontend Baseline (implementation report)

**Date:** 3 Nov 2026.

**What was built.** One working React application in `uc042/frontend/` against the actual Phase 2 FastAPI backend. It is
a functional baseline with a clean, token-based initial theme. The final visual design will be applied later (Claude
Design).

**Out of scope:** PostgreSQL, SQLAlchemy, Alembic, authentication, and design variations.

## 1. Stack (installed locally in `frontend/node_modules`; no global installs, no administrator rights)

| Package | Version | Notes |
| --- | --- | --- |
| react / react-dom | 19.3.1 | |
| react-router-dom | 7.18.5 | URL routes for every screen |
| vite / @vitejs/plugin-react | 8.3.5 / 6.2.1 | |
| typescript | 5.9.3 | |
| vitest / @testing-library/* / jsdom | 5.1.0 / 16.3.3, 14.6.8, 7.0.1 / 29.1.1 | jsdom 29: version 30 requires Node ≥ 24.15, and the machine has 24.12 |

There is no state-management, UI-kit or charting library. Node 24.12 and npm 11.6 were already installed.

## 2. Screens and routes

| Route | Screen | Backend endpoints |
| --- | --- | --- |
| `/` | Dashboard: packs (scenario, period, engine status, evidence, exceptions, eligible-investigation coverage), pending reviews, recent final packs | `GET /packs`, `GET /packs/{id}/investigations` (per row), `GET /reviews`, `GET /final-packs`, `GET /health` |
| `/packs/:packId?tab=` | Pack details: summary, exception register, internal and external reconciliation, source data and missing evidence, accounts; **Open final audit-pack review** | `GET /packs/{id}`, `/exceptions`, `/reconciliation`, `/sources`, `POST /packs/{id}/reviews` |
| `/packs/:packId/exceptions/:exc` | Exception investigation: deterministic details, affected engine results, AI investigation runs with eligibility and reasons, failed attempts; **Run AI investigation** (job + polling, retry as a new job) | `GET /packs/{id}/exceptions/{exc}`, `POST …/investigations`, `GET /jobs/{id}` |
| `/investigations/:id` | AI investigation results: summary, AI assessment, confirmed observations (with why relevant / establishes / does not establish), hypotheses NOT ESTABLISHED, gaps, conflicts, unverified relationships, next steps, open questions, citations → evidence viewer | `GET /investigations/{id}`, `/findings`, `/evidence?limit=200` |
| `/reviews` | Review sessions | `GET /reviews` |
| `/reviews/:reviewId?view=` | **Final audit-pack review**: report preview (backend HTML), AI closing summary, exception register, investigation selections; readiness; preview generation (job + polling); HOLD (comment) and GENERATE (acknowledgement, plus summary-unavailable acknowledgement); history | `GET/PATCH /reviews/{id}…`, `POST /reviews/{id}/preview`, `GET /reviews/{id}/preview/{html,json,pdf}`, `POST /reviews/{id}/decision`, `GET /reviews/{id}/history` |
| `/final-packs`, `/final-packs/:id?view=` | Final packs; details with integrity verification, human review, investigation references, HTML report, PDF, closing summary, exception register, and links to the JSON/HTML/PDF files | `GET /final-packs`, `/final-packs/{id}`, `/verify`, `/json`, `/html`, `/pdf` |

All IDs are in the URL, so a refresh or a shared link reopens the same view.

### How the workflow rules appear in the UI

- **Immutability.** The deterministic pack and the AI investigations are labelled immutable, separate records.
- **Unresolved exceptions** always show `UNRESOLVED`. Investigations show "NOT RESOLVED BY INVESTIGATION".
- **Hypotheses** sit in a dashed amber "HYPOTHESIS · NOT ESTABLISHED" card under an explicit notice. Gaps and conflicts
  each have their own style.
- **Preview before GENERATE.** GENERATE is disabled until a current preview exists, the acknowledgement (the backend's
  own text) is ticked, and readiness has no blockers.
- **Stale previews.** A stale preview (`409 PREVIEW_STALE`) is shown as "regenerate the preview".
- **HOLD** requires a comment and publishes nothing. The page then shows "Review on hold — generate a new preview to
  continue".
- **GENERATE** is a single backend call. On success the UI navigates to the published final pack. Nothing is assembled
  or published in the browser.
- **Errors.** Every backend error is shown with its detail and code. An unreachable backend is reported as such, never
  replaced by data.

## 3. Structure and design system

- **API layer** (`src/api/`). `client.ts` is the only code that performs HTTP: base URL, JSON, problem details become
  `ApiError` (status, code, detail, extra fields), and network and timeout errors are handled. `endpoints.ts` lists
  every route, and `types.ts` mirrors the backend schemas.
- **Hooks.** `useApi` handles loading, error and reload. `useJobPoller` polls every 2 s until COMPLETED, FAILED or
  INTERRUPTED, and keeps polling through a transient error.
- **Styling.**
  - `tokens.css` holds every visual value: colours, navy navigation, status and AI-class colours, typography, spacing,
    radii and shadows.
  - `components.css` defines classes built from tokens only; there are no inline styles.
  - The status hues and AI-content classes match `pack.html` and the final-pack report.
- **Report isolation.** The backend's HTML is shown in a sandboxed `iframe srcdoc` (no scripts, opaque origin), and the
  PDF as a blob `iframe`. The API sends `X-Frame-Options: DENY` and a sandbox CSP, so the API URLs are opened only as
  top-level links.

## 4. Backend changes (reported before changing the contract; approved)

**Three additive, read-only endpoints.** No existing endpoint or schema changed.

| Endpoint | Reason |
| --- | --- |
| `GET /api/v1/packs/{id}/reconciliation` | Internal and external reconciliation tables, opening positions and accounts, copied from the pack (spec 06 §8.3 row 5) |
| `GET /api/v1/packs/{id}/sources` | Source-file register (dataset-relative names, SHA-256) and missing evidence (spec 06 §8.3 row 6) |
| `GET /api/v1/reviews?pack_id=&status=` | A read-only list of review sessions for the dashboard. Previously the only way to find a session was `POST /packs/{id}/reviews`, which creates one. |

**Defect found by the frontend and fixed (internal, no contract change).**

- *Symptom.* On Windows, `GET /jobs/{id}` intermittently returned 500 while the job runner was rewriting the job file:
  a read during `os.replace` raises a sharing violation (`PermissionError`). Frontend polling hit this.
- *Fix.* Repository reads now take the same in-process lock as writes, and the atomic replace and read retry briefly on
  a Windows sharing violation.
- *Evidence.* With the old read, 21 of 150 polls during rewrites failed; with the fix, none. The regression test is
  `tests/test_api_reads.py::ConcurrentPolling`.

New backend tests are in `tests/test_api_reads.py`: 4 tests (reconciliation, sources, the review list, concurrent
polling).

## 5. Verification

| Check | Result |
| --- | --- |
| `npm run build` (type-check + Vite production build) | OK: 44 modules, JS 328 kB (98 kB gzip), CSS 11.7 kB |
| `npm test` (offline, scripted fetch) | **20 passed**. Covers: API client errors and formatting, navigation, pack list (populated, empty, error), pack detail and reconciliation tables, exception navigation, investigation start and job completion, failed job and ineligibility, poller to a terminal status, findings classes and evidence viewer, preview frame and closing summary, selections PATCH with revision, HOLD comment, GENERATE acknowledgement and navigation, stale preview, on-hold state, summary-unavailable acknowledgement, final-pack integrity failure and file links |
| Live backend (`e2e.backend.test.tsx`, opt-in) | **3 passed** against the real FastAPI on the September 2026 packs. All 9 packs verified; S05 reconciliation shows −812.40 FAIL; EXC-S05-01 is UNRESOLVED and `INV-EXC-S05-01-65bd05498b9e` is eligible after legacy import; findings and ledger load; investigation start correctly reports `PROVIDER_NOT_CONFIGURED`; then open review, preview (closing summary UNAVAILABLE), HOLD (nothing published), a stale snapshot gets 409, preview again, GENERATE, final pack verified, JSON/HTML/PDF retrieved, history HOLD then GENERATE |
| Browser render | Headless Edge, driven over the DevTools protocol, against Vite and the backend: dashboard, pack, exception, investigation, review (with the backend report in the sandboxed frame) and final pack (integrity verified) render correctly |
| Backend suite (`python -W error::ResourceWarning -m unittest`) | **409 tests, OK (1 opt-in live test skipped)**: 405 before this phase + 4 in `test_api_reads.py`. No existing test changed. |

**No live OpenAI calls.** The live check ran with `UC042_LLM_PROVIDER=offline`, a scratch state directory and a scratch
final-packs folder outside the project; those folders were deleted afterwards. The one GENERATE was an explicit request
issued by the check, into that scratch folder. The project has no `final_packs/` or `app_state/` directory.

## 6. Known limitations

- **Real AI runs.** A successful investigation or closing summary needs `OPENAI_API_KEY` and
  `UC042_LLM_PROVIDER=openai` on the backend. That path is covered by the backend's mocked-provider tests and the
  frontend's scripted tests, not by a live call in this phase.
- **Dashboard coverage cost.** The coverage column calls `GET /packs/{id}/investigations` per pack, and the backend
  re-validates eligibility on each call (about 1 s per pack with investigations).
- **Synchronous GENERATE.** The UI shows "Generating…" until the single request returns (typically 2–5 s), because the
  backend reports no intermediate progress.
- **Not shown:** recent activity (the backend has no activity log) and tool-call transcripts (no endpoint).
- **Visual design.** Desktop-first, with only basic responsiveness. Long result IDs wrap in narrow columns. This is
  baseline styling, pending the Claude Design output.
- **Windows path length.** Keep `UC042_APP_STATE_DIR` short (for example `C:\uc042_state`). Very deep paths can exceed
  the 260-character limit for preview files.
