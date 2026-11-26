# UC-042: implementation changelog (UI simplification, P10 only)

- **Scope.** All changes are in `%USERPROFILE%\p10쁂`. The live repository, the live database, ports 5173 / 8000, migrations, schemas, environment configuration, datasets, packs and investigation artefacts were not modified.
- **Patch.** `p10/ui_audit/changes_ui.patch` is a unified diff against the backup `p10/backups_ui/p10_uc042_src_before_ui.tgz` (22 files).
- **Database.** There is no migration and no schema change.

## Backend (1 file)

| File | Change | Reason |
|---|---|---|
| `uc042app/services/ai_authorization.py` | `configuration()` fills `configuration_problem` when the provider key is missing ("OPENAI_API_KEY is not set in the backend environment") or the provider cannot be used live. Only the variable's name is given | The AI dialog said "not configured" with no reason (D8) |

## Frontend

| File | Change |
|---|---|
| `src/App.tsx` | `/` → `HomeRedirect` (Monthly reports; `/?period=X` → `/reports/X`); the 404 links to Monthly reports; dashboard import removed |
| `src/pages/DashboardPage.tsx` | **Deleted.** Its unique parts moved (see `ReportPages.tsx`); the original is in the backup |
| `src/components/layout/AppShell.tsx` | Sidebar now has six workflow steps: 1 Monthly reports, 2 Upload documents (month-aware), 3 Reconciliation packs, 4 Exceptions, 5 Final review, 6 Final audit packs. Active state is by route; none disabled. "All reviews", "All final packs" and "Dashboard" removed. The breadcrumb root is "Monthly reports" |
| `src/pages/ReportPages.tsx` | Archive: "Uploads" (validation / run status) and "Unresolved" columns; `PublishedCell` counts packs, not versions; `WorkInProgress` (final reviews in progress, recent activity). Month report: published-packs KPI counts packs; the pack table has the scenario name ("clean reconciliation" fallback), "AI available" and the latest final-pack version; the exceptions table has amount and AI status; the investigations table has "Final-pack eligibility" and "Analyst decision". Months without records show "No reconciliation data" with **Open <month> for upload** (`OpenMonth`, moved from the dashboard) or "open for upload" |
| `src/components/workspace/ExceptionSummary.tsx` | **New.** Exception summary (what went wrong, amounts and accounts, checks that identified it, evidence, AI assistance) and `nextStep()` |
| `src/pages/WorkspacePage.tsx` | Two-column layout; main column order: summary → citation inspector → AI investigation and review → check results → collapsed evidence panels → review history → case (collapsed). The breadcrumb opens the month report; the eyebrow names the scenario |
| `src/components/workspace/AiPanel.tsx` | Title "AI investigation and your review"; a notice for unusable investigations; technical rows under "Technical details"; option labels lead with the date and status; "Run a new investigation" is secondary when a usable investigation exists; technical-record link relabelled |
| `src/components/workspace/AnalystReview.tsx` | `defaultInvestigation()` and `AiStatus` (one plain AI status); labels "AI awaiting your review / AI accepted by analyst / AI rejected by analyst"; no Accept / Reject on unusable investigations; `id="analyst-review"` for the next-step button |
| `src/pages/ReviewPages.tsx` | `ReviewChecklist` ("Before you generate"); raw readiness messages in a collapsed list; preview / regenerate disabled while the backend would refuse (reason shown); closing-summary failure detail; "← Exceptions" button; reviews list with in-progress reviews first |
| `src/pages/PackDetailPage.tsx` | "Open exceptions (N)" only when N > 0; "Add documents for a new period" removed |
| `src/pages/FinalPackPages.tsx` | List: month, downloads, latest / superseded markers, versions-of-packs count |
| `src/components/common/index.tsx` | `Collapsible` panel |
| `src/styles/components.css` | Two-column workspace grid; collapsible, summary, next-step and checklist styles |

## Tests

| File | Change |
|---|---|
| `tests/test_phase8.py` | New: `test_configuration_names_the_missing_key_without_any_value` (no key → message; key set → configured, the key's value never in the response) |
| `tests/test_analyst_review.py` | New: `test_closing_summary_model_never_receives_rejected_ai_content` (inspects the actual Responses-API request of a real `OpenAIInvestigator` with a mocked HTTP client) |
| `frontend/src/test/simplified.test.tsx` | **New** (5 tests): exception summary sections, next step for a pending / accepted / uninvestigated exception, and the checklist (pending decision with link, stale preview, provider failure detail, ready) |
| `frontend/src/test/screens.test.tsx` | Dashboard tests rewritten for the new start page and month report (same assertions about the nine scenarios, empty states and navigation); SC2 test asserts the "cannot be used" notice instead of the `INELIGIBLE` badge |
| `frontend/src/test/archive.test.tsx` | Dashboard tests rewritten for Monthly reports (upload status column, open-month-on-request moved to the month report). The test fake now returns 404 for unknown months, **as the real backend does** (it had returned September's data for any month) |
| `frontend/src/test/reports.test.tsx` | Navigation names; the upload entry targets the selected month in the sidebar and the month report |
| `frontend/src/test/phase8.test.tsx`, `analystReview.test.tsx` | Panel titles and status label updated |

The changed tests assert the new intended behaviour. No integrity, financial or safety assertion was removed or weakened. One test caught a real regression while I was working: the historical February pack was labelled "Scenario H202602". That was fixed in the code, not in the test.

## Test-environment artefacts (outside the repository)

- `p10/env_e/`: clone E's database URL, state, document store, investigations, final packs and `launch_backend.py`.
- `p10/ui_audit/`: the browser driver, exploration and E2E scripts, evidence JSON, screenshots, and `changes_ui.patch`.
- `p10/backups_ui/`: the backups taken before any change.

---

## Update (6 Nov 2026): OpenAI primary with automatic Groq fallback

| File | Change |
|---|---|
| `uc042lib/investigation/config.py` | Fallback settings (`UC042_LLM_FALLBACK_PROVIDER/MODEL/MAX_TOKENS/REASONING_EFFORT`, `GROQ_API_KEY`, `GROQ_BASE_URL`) and `fallback_settings()` |
| `uc042lib/investigation/llm.py` | `GroqInvestigator` (OpenAI SDK on the Groq base URL; request, history, metadata and final-output hooks); `_request` / `_meta` / `_history` / `_final_output` hooks in `OpenAIInvestigator` (OpenAI behaviour unchanged); 5xx → `provider_unavailable`, 413 → `request_too_large`; `gsk_` redaction; factory wraps the primary with the fallback |
| `uc042lib/investigation/fallback.py` | **New**: `FallbackInvestigator` (eligible kinds, one switch, provenance record) |
| `uc042lib/investigation/graph.py` | Tools-mode model metadata carries the fallback record |
| `uc042app/services/ai_authorization.py`, `api/schemas.py` | Configuration shows the fallback; statements mention it; confirmation checks and records it |
| `uc042app/services/investigations.py`, `reviews.py` | Investigation view and preview metadata expose the fallback record |
| `frontend`: `types.ts`, `AiAuthorizationDialog.tsx`, `AiPanel.tsx`, `ReviewPages.tsx`, `decision.tsx` | Dialog shows and confirms the fallback; "Answered by" plus a fallback notice; checklist names the summary's provider; stale exclusion reason fixed |
| `tests/test_provider_fallback.py` | **New**, 16 tests (simulated failures, mocked HTTP) |
| `frontend/src/test/phase8.test.tsx` | The confirmation now includes the fallback the dialog showed |
| `.env.example` | Fallback variables (empty) |
| `p10/env_e/launch_backend.py`, `p10/env_e/ai.env` | Clone E loads the fallback variables only; uses its own packs root (`env_e/packs`) so reassessment writes nowhere else |
