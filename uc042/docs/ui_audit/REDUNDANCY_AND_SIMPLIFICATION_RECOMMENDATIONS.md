# UC-042: redundancy and simplification recommendations

Each item was traced to its code and backend effect before any change was decided. **Status:** Implemented (in P10, tested), Recommended (not yet implemented), or Keep (deliberately unchanged). No backend endpoint, record type or audit artefact was removed by any implemented item.

## Priority 1: duplicate pages and navigation

| # | What exists, and where | Business purpose | Duplicates | Replacement | Backend / audit effect | Status |
|---|---|---|---|---|---|---|
| R1 | Dashboard `/` (period table, scenario list, KPIs, recent packs, pending reviews, activity) | Overview of the months | Monthly reports (same months and counts); month report section 3 (same scenario list) | `/` opens Monthly reports. Kept from the dashboard: upload/processing status and unresolved columns, "Final reviews in progress", "Recent activity", "Open <month> for upload" (moved to the month report). Old `/?period=` links open that month | None: `/dashboard` and `/activity` endpoints unchanged | Implemented |
| R2 | Sidebar "All reviews" | List of final reviews | Sidebar 04 "Final review" with no context opens the same list | Removed; the list remains at `/reviews`, sorted with in-progress reviews first | None | Implemented |
| R3 | Sidebar "All final packs" | List of final packs | Sidebar 05 opens the same list | Removed; "Final audit packs" (step 6) always opens the list | None | Implemented |
| R4 | Sidebar numbering (01, R, 02–05, R, F, ↑) and two disabled entries | Workflow order | — | Six steps 1–6 in business order (Monthly reports, Upload documents, Reconciliation packs, Exceptions, Final review, Final audit packs); none disabled (each falls back to the month, then to the archive) | None | Implemented |
| R5 | "Add documents for a new period" on the pack's source inventory | Upload | Sidebar upload; month report upload buttons | Removed from the pack page | None | Implemented |
| R6 | "Investigate exceptions" on a pack with no exceptions | Open the workspace | — | "Open exceptions (N)", shown only when N > 0 | None | Implemented |

## Priority 2: the exception workspace (the central business object)

| # | Problem | Change | Effect | Status |
|---|---|---|---|---|
| R7 | No statement of what went wrong or what to do next | Exception summary at the top: engine notes, amounts (or computed vs reported when the pack has no amount), checks with failed / total results, evidence status and missing items, AI status, and one **Next step** with its button | Read-only; derived from the existing exception, results and evidence endpoints | Implemented |
| R8 | 60+ expanded evidence rows before the AI and the decision; the decision in a narrow side column | One main column. AI investigation and review come right after the summary; source records, AI-tool records and relationships are collapsed (one click away, never removed) | No data removed | Implemented |
| R9 | Accept / Reject offered on unusable (ineligible) investigations | Replaced by "No decision needed for this investigation", with the reason | The backend still accepts a decision through the API (unchanged); the UI no longer invites a decision with no effect | Implemented |
| R10 | Technical rows (model, validation, registry) mixed with business rows | Moved into "Technical details"; the full technical record stays one link away | None | Implemented |
| R11 | Seven status badges per exception | One AI-assistance status: Not investigated / Investigation running / AI awaiting your review / AI accepted by analyst / AI rejected by analyst / Not usable (N). The AI assessment stays on its own card, labelled "AI interpretation, not fact" | None | Implemented |
| R12 | "Run investigation" as the primary button even when a usable investigation exists | Secondary "Run a new investigation" in that case | A paid call is no longer the most prominent action | Implemented |
| R13 | Investigation case shown first in the AI column | Moved to the bottom, collapsed ("Investigation case (optional)") | Case feature unchanged | Implemented |
| R14 | Investigation case and analyst review overlap (both record an analyst view of the exception) | **Recommended decision for the owner**: keep the case as the analyst's working notes; consider whether its "Human decision / disposition" is needed alongside ACCEPT / REJECT. It never reaches the final pack | Would affect the `cases` API and records; do not remove without a decision | Recommended |

## Priority 3: final review

| # | Problem | Change | Status |
|---|---|---|---|
| R15 | Readiness shown as backend codes | "Before you generate" checklist in plain words, with links to the investigations awaiting a decision; raw messages kept in a collapsed list | Implemented |
| R16 | Preview button enabled while the backend will refuse the preview; the refusal came only after the paid-AI authorisation | Button disabled, with the reason, until the decision is recorded | Implemented |
| R17 | Missing closing summary explained only as "(configuration)" or "(rate_limit)" | The provider's stored reason is shown (e.g. "OPENAI_API_KEY is not set …" or "429 … credit_balance_exhausted") | Implemented |
| R18 | AI dialog "The AI provider is not configured" with no reason | Backend `GET /ai/configuration` now returns `configuration_problem` naming the missing variable (never a value) | Implemented |
| R19 | No way back to the exceptions from the review page except the sidebar | "← Exceptions" button | Implemented |

## Priority 4: counting and listing

| # | Problem | Change | Status |
|---|---|---|---|
| R20 | Monthly overview counted final-pack versions ("Published (2 versions)") | "N of M packs published · K versions"; month KPI counts packs, with versions in the note | Implemented |
| R21 | Month report pack table without scenario names, AI coverage or final pack | Added; a clean scenario is labelled "clean reconciliation" when the dataset has no name (S01's name is empty in the data) | Implemented |
| R22 | Exceptions table without amount or AI status; investigations table "Review eligibility" without the analyst's decision | Amount and AI-investigation status columns; "Final-pack eligibility" and "Analyst decision" columns | Implemented |
| R23 | Final packs list without month, downloads or latest marker | Added month, JSON / HTML / PDF, "latest" / "superseded by a later version" | Implemented |

## Recommended, not implemented

| # | Recommendation | Reason it was not done here |
|---|---|---|
| R24 | Separate the nine September demonstration scenarios into a clearly labelled "Demonstration scenarios" view, apart from operational months | Changes the period model (all nine are packs of PER-2026-09 in the database). The current labels ("9 demonstration scenarios of this one month") are accurate. Owner decision |
| R25 | Re-run the investigations that fail current validation rule C-01 (SC2 × 2, SC5A × 1, S05 × 1) and register or replace the unregistered S02 investigation | Needs live AI calls (the provider account has no credits). The historical artefacts must not be edited |
| R26 | Exceptions whose pack records no amount, currency or account (SC3B, SC3C-02/03, SC5A, SC5C, SC5D), and categories stored as check codes | A dataset / engine output matter. The UI now shows computed vs reported and the control name instead. Changing the engine output would alter financial results, which is out of scope |
| R27 | Normalise case timestamps to UTC like the analyst reviews (the API returns +05:30 for `cases`) | Display is already correct (the UI converts to Europe/London). Backend consistency fix for later |
| R28 | Re-verify narrow / mobile layouts after the workspace layout change | Not tested in this round |
| R29 | Show a scenario description (from `SCENARIO_NOTES.md`) on each demonstration pack | Needs a backend field |

## Functionality that must be preserved (verified still present)

- Every route, including legacy redirects. The only route that changed is `/`, which now redirects to Monthly reports.
- Monthly report sections 1–8, reassessment, add supporting document, change title.
- The upload and validation flow, with decisions on flagged documents, confirmation and processing.
- The pack's three reconciliation views, source inventory and exception register.
- In the workspace, every evidence panel, the citation inspector, all AI tabs, the analyst review with its mandatory verbatim reason, the review history and the investigation case.
- The investigation technical record: tool calls, registry, verification.
- In the final review, the selections editor, HOLD, GENERATE, both acknowledgements, the stale-preview guard (UI and backend) and the decision history.
- On final audit packs, all three formats, integrity verification and version history.
- Paid-AI authorisation before every AI call.
