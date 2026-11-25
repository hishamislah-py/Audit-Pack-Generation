# UC-042 frontend: Enterprise Audit Platform (Variation A)

React + TypeScript + Vite analyst UI for the local UC-042 backend.

- **Default: the FastAPI backend** (`VITE_DATA_SOURCE=api`, `VITE_API_BASE_URL`). A failed request is shown as an
  error; there is never a fallback to mock data.
- **Mock data: development and tests only.** `VITE_DATA_SOURCE=mock` works only in the dev server (`npm run dev`). The
  mock source reads captured backend responses from `dev-fixtures/mock-data` and simulates investigation, preview, HOLD
  and GENERATE in the browser. It never simulates document upload or processing. Neither the mock code nor its data is
  in the production build.

## Run (PowerShell, from `uc042/frontend`)

```powershell
npm install        # first time only
copy .env.example .env.local      # VITE_API_BASE_URL=http://127.0.0.1:8000, VITE_DATA_SOURCE=api
npm run dev        # http://127.0.0.1:5173 (start the backend first: python -m uc042app from uc042/)
npm test           # offline tests (Vitest + Testing Library; fixtures read from dev-fixtures/mock-data)
npm run build      # type-check + production build (frontend/dist)
```

Checks against a running backend: `UC042_E2E=1 npx vitest run src/test/api.live.test.ts` (reads all packs and runs a
review to HOLD; GENERATE only with `UC042_E2E_GENERATE=1`, which publishes a final pack into the backend's
`UC042_FINAL_PACKS_ROOT`, so point that at a temporary folder). Contract check of `src/api/types.ts` against the
Pydantic schemas: `..\.venv\Scripts\python.exe scripts\check_contract.py`.

## Screens and routes

| # | Screen | Route |
| --- | --- | --- |
| 01 | Dashboard: monthly archive table (documents, validation, processing, packs, exceptions, AI coverage, final packs), the September scenarios, KPIs, reviews, activity | `/` (`?period=PER-2026-09`) |
| — | Period archive: current document set, packs, upload batches, processing runs, all documents | `/periods/:periodId` |
| — | Upload documents: month, files, send for identification and validation | `/upload?period=…` |
| — | Upload batch: document checks (dates, duplicates), INCLUDE / EXCLUDE decisions, confirm, processing runs | `/uploads/:batchId` |
| 02 | Reconciliation pack: accounts, source inventory, external, internal and differences, exception register | `/packs/:packId` |
| 03 | Exception and investigation workspace: exception list, evidence, and an AI panel | `/packs/:packId/workspace/:exceptionId` |
| 04 | Final review: 16-section report preview, readiness, selections, HOLD / GENERATE | `/packs/:packId/review`, which opens `/reviews/:reviewId` |
| 05 | Final audit pack: record, artefacts, PDF / HTML / JSON, version history | `/final-packs/:finalPackId` |
| — | All reviews, all final packs | `/reviews`, `/final-packs` |

## Structure

```
src/
  api/          client.ts (HTTP, ApiError, timeouts, multipart), endpoints.ts (FastAPI routes), types.ts (backend schemas)
  data/         DataSource.ts (the seam screens use), apiSource.ts (FastAPI adapter, default), mock/ (MockDataSource +
                fixture loader, dev/test only), periods.ts (archive months), models.ts (period, upload, activity view
                models), DataProvider.tsx (explicit choice: VITE_DATA_SOURCE)
  hooks/        useApi (loading / error / reload), useJobPoller (polls jobs through the DataSource)
  lib/          format.ts (money and dates, never recalculated), evidence.ts (grouping, D/C as recorded),
                report.ts (the 16 Phase 1 sections), upload.ts (upload contract; mock-mode pre-check)
  styles/       tokens.css (every visual value), base.css, components.css (classes from tokens only)
  components/   common/, layout/, pack/, workspace/, review/, finalpack/, upload/ (drop zone, document table, runs)
  pages/        Dashboard, ArchivePages (period, batch), PackDetail, Workspace, ReviewPages, FinalPackPages, Upload
  test/         support.tsx, units.test.ts, screens.test.tsx, archive.test.tsx, api.live.test.ts (opt-in)
dev-fixtures/mock-data/  captured fixtures (dev server with VITE_DATA_SOURCE=mock and tests only)
```

**Re-theming.** Edit `src/styles/tokens.css`, and `components.css` for layout. Screens, data and API code do not
change.
