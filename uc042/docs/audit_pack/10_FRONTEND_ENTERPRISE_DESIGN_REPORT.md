# 10 — Frontend: Enterprise Audit Platform design (Variation A), mock-data phase

**Date:** 3 Nov 2026.

**Scope.** This phase implements the selected Variation A design in `uc042/frontend` with an explicit, isolated mock data
source. It reuses the Phase 3 API client, types and patterns.

**Unchanged:** FastAPI, PostgreSQL, the datasets, packs, investigation artefacts and the final-pack library.

## 1. Data: real captured responses, simulated actions

**Fixture capture.** `frontend/scripts/capture_mock_data.py` runs the real FastAPI app in-process, read-only:

- a temporary state directory and a temporary final-packs folder;
- the offline provider, so there are no OpenAI calls;
- a legacy registry import into the temporary state only.

It writes every response the UI reads to `frontend/public/mock-data/`: 142 files, 3.6 MB, including one real Phase 1
report preview (HTML, JSON, PDF) per pack. The S05 preview is the live gpt-6-luna one, re-rendered with the current
library.

**What the mock does:**

- `MockDataSource` serves those responses unchanged.
- It simulates investigation runs, previews, HOLD and GENERATE in browser memory, applying the backend's own rules and
  error codes: `PREVIEW_STALE`, `ACKNOWLEDGEMENT_REQUIRED`, `COMMENT_REQUIRED`, `SUMMARY_UNAVAILABLE_ACK_REQUIRED`,
  `INVESTIGATION_ACTIVE`, `SESSION_CLOSED`, `INELIGIBLE_SELECTION`.
- A simulated investigation run completes to an investigation already captured for that exception, or fails with a
  `SIMULATED:` reason when none exists.
- A simulated GENERATE creates a session-only `SIM-FAP-…` record. Its document is the real preview (which still reads
  PREVIEW), and integrity is shown as **not verified**, never as verified.

**Switching sources.** `DataSource` is the single seam between the screens and the data. `apiSource.ts` maps every
method to the existing endpoints. The source is chosen explicitly by `VITE_DATA_SOURCE` (`mock` by default in this phase,
or `api`) and shown in the top bar. A failed real request is never replaced by mock data.

**Real data shown:**

- **September 2026 scenarios.** The nine packs are presented as nine test scenarios of the same month, never as months.
- **EXC-SC2-01.**
  - £2,868.50 on 15 Sept 2026.
  - The bank entry `IN-09:BE-GBP-0916-T01` is a **debit** on 16 Sept.
  - The cashbook entry `IN-10:LE-GBP-0915-0005` is a **credit** on 15 Sept.
  - The status is UNRESOLVED.
  - Both SC2 investigations are shown as ineligible (rule C-01), as they really are.
- **Reconciliation views.** Internal (safeguarding requirement vs resource, per currency and day) and external (firm
  ledger vs bank, per account and day) are separate tabs, each with its own definition. The differences view labels the
  view on every row, and no amount is netted or recalculated.

## 2. Screens

| # | Screen | Highlights |
| --- | --- | --- |
| 01 | Dashboard | KPI strip; January–November 2026 period table (AVAILABLE / OPEN FOR UPLOAD / NO DATA); a September scenario table with a "test scenarios, not months" notice; empty states for other months; upload entry for the current month; recent final packs, pending reviews; activity (captured investigation publications plus simulated session actions, labelled) |
| 02 | Reconciliation pack | KPI strip; accounts with last-day bank balance; 19-document source inventory (file, category, source type, records, status, period, SHA-256); external / internal / differences tabs; exception register with UNRESOLVED and AI status |
| 03 | Exception and investigation workspace | **Left:** exception list. **Centre:** KPIs, deterministic results, citation inspector, evidence grouped as bank, cashbook, settlement, transactions and reconciliation records (D/C as recorded), relationships. **Right:** AI panel with a simulated run and job status, an investigation-record selector, eligibility, and tabs for Summary (assessment), Observations (with "Relevance to the discrepancy"), Hypotheses (NOT ESTABLISHED), Gaps and conflicts (with unverified links) and Next steps. A citation click highlights the record and opens the inspector. |
| 04 | Final review (document-centric) | **Left:** the 16 Phase 1 sections, with AI sections marked and the closing summary 16th; the list scrolls the sandboxed report. **Centre:** the real report, in HTML, PDF or JSON. **Right:** pack summary and report facts, readiness, selections editor, human review (note, the backend's acknowledgement text, a summary-unavailable acknowledgement), HOLD and GENERATE confirmation modals ("Authorise final audit-pack assembly … does not resolve exceptions … or establish compliance"), and decision history. |
| 05 | Final audit pack | Integrity status (verified / failed / not verified-simulated); pack record (ID, version, original pack and hash, investigation references, time, authoriser, unresolved count); artefacts with Open and Download; PDF preview, HTML report, canonical JSON and version history tabs |
| — | Upload (design only) | Steps: month, files, classify and validate, summary, process. The drop zone reads names and sizes only. Pre-checks follow the upload contract (19 documents, IN-18 and IN-19 optional, IN-19 being the previous month's receipt). It detects duplicates, wrong period, unknown, unsupported and empty files, and checks the expected-document list. Processing is disabled: there is no ingestion endpoint. |

## 3. Design decisions (Variation A, adapted to the brief)

- **Navigation.** A dark navy sidebar, as the brief asks, carries Variation A's numbered workflow (01–05), records links
  and the current pack. The prototype's navy header becomes a white top bar with the period selector, a
  MOCK DATA / live-backend badge, a SYNTHETIC DATA badge and the analyst.
- **Typography and shape.**
  - Source Serif 4 for headings and figures, Source Sans 3 for UI, Source Code Pro for IDs. All are bundled locally with
    `@fontsource`, so there are no font CDN calls.
  - Square corners, 1 px borders, no decorative shadows except on the document page and modals.
- **Colour roles.** Navy for primary actions, blue for links and assessments, green for evidence-supported observations,
  amber for hypotheses and warnings (dashed), purple for evidence gaps and mock notices, red for UNRESOLVED and failures.
- **Tables.** Uppercase 11 px headers, tabular figures, right-aligned amounts, FAIL rows tinted, highlighted rows for the
  selected evidence.
- **Responsive.**
  - **Desktop (1440 px and wider):** full three-column layouts.
  - **Up to 1600 px:** narrower side panels.
  - **Up to 1200 px (tablet):** compact numbered sidebar; the workspace AI panel moves below; the report navigation
    becomes a dropdown.
  - **Up to 900 px:** single column.
  - Desktop (1440) and tablet (1024) layouts were checked in a real browser (headless Edge).
- **Tokens.** All values live in `styles/tokens.css` (colour, typography, spacing, shape, depth, table metrics, layout),
  and `components.css` uses tokens only. Components contain no inline styles.

## 4. Tests and build

| Check | Result |
| --- | --- |
| `npm test` | **17 passed**, plus 1 opt-in live-backend test skipped. **Units:** periods; amounts; D/C preserved; 16 sections; upload checks; API adapter errors with no fallback. **Screens:** months and September scenarios; empty and upload states; workflow navigation; pack inventory and reconciliation views; workspace SC2 evidence directions, citations and record switching; simulated runs (complete and fail); review preview with 16 sections; HOLD (reason required, nothing published); GENERATE (acknowledgement, modal, simulated pack, version history); summary-unavailable acknowledgement; selection change invalidates the preview; upload set and missing documents. |
| `npm run build` | OK. JS 379 kB (113 kB gzip); CSS 56 kB including the fonts' `@font-face` rules; `public/mock-data` is copied as static files. |
| Browser check | The dashboard, pack, workspace (with citation), review (preview, closing-summary section, GENERATE modal), final pack (PDF viewer) and upload screens were clicked through at 1440 px; the dashboard, workspace and review at 1024 px. Two layout defects were found and fixed: a cramped centre column and long-ID overflow. |

## 5. Known limitations (mock-only behaviour)

- **Simulated actions.** All actions are simulated and lost on reload. No AI call is made, nothing is published, no file
  is uploaded or read, and integrity is never verified in mock mode.
- **Previews are fixed.** Each pack has one captured preview, built from the default selections. If the analyst changes
  selections, the preview is invalidated (as in the backend), but regenerating shows the same captured content. This is
  stated in the UI.
- **Closing summaries.** Only S05 has a generated (live) closing summary. The other packs show UNAVAILABLE, because the
  capture used the offline provider; this also demonstrates the acknowledgement path.
- **Data the backend does not expose yet:**
  - months, an activity log and upload/ingestion have no endpoints;
  - periods are derived from the pack list;
  - activity in mock mode is captured investigation timestamps plus session actions;
  - pack-level evidence records come only through an investigation's evidence (there is no per-exception evidence
    endpoint), so uninvestigated exceptions show an explanatory empty state.
- **Production build.** It includes `public/mock-data`; exclude it when the API source becomes the default.

## 6. Integrity

- No FastAPI, backend, test, dataset, pack, investigation or final-pack-library file changed in this phase (checked by
  hash and modification time).
- The 423 protected files are unchanged, and the 34 investigation artefacts are unchanged.
- The project has no `final_packs/` or `app_state/` directory.
- There is no PostgreSQL, SQLAlchemy or Alembic.
