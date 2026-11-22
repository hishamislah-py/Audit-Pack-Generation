# UC-042 Phase 10 — Analyst Review of AI Investigations: Implementation Report

5 Nov 2026. This work was implemented and tested in an **isolated copy** (`%USERPROFILE%/p10/uc042`, no `.env`, no API key) against **disposable databases** (`uc042_p10`, `uc042_p10_test`). The live repository and the live `uc042` database were **not modified**. Section 9 explains why, and what applying the change involves.

Screenshots are in [`23_screenshots/`](23_screenshots/). They come from the real application, running from the copy on ports 8030 (backend) and 5190 (UI).

---

## 1. Architecture assessment (before implementation)

| Area | Finding | Decision |
| --- | --- | --- |
| Exception Workspace (`frontend/src/pages/WorkspacePage.tsx`, `components/workspace/*`) | Three columns: exception list, deterministic results with engine and AI-tool evidence and inspector, AI panel with tabs. | **Reused.** Added list badges, an Analyst Review section under the AI tabs, and a Review History panel in the right column. No new page, sidebar or dashboard. |
| Final review (`uc042app/services/reviews.py`) | Session state machine, selections (`INCLUDED`, `NOT_INVESTIGATED`, `EXCLUDED_BY_ANALYST`), readiness blockers, HOLD / GENERATE, stale-preview check by snapshot hash. | **Reused.** Analyst decisions became an input of the review snapshot. A changed decision therefore changes the snapshot hash, and GENERATE on an old preview fails with `PREVIEW_STALE`. No new selection value was added. |
| Final-pack library (`uc042lib/final_pack`) | One block model (`report.build_report`) feeds both HTML and PDF. `verify_final_pack` re-renders stored JSON and compares the bytes. | **Modified, additively.** Every new field, report text and CSS rule appears only when analyst reviews are present (schema **1.1**). Published 1.0 packs still render byte-identically. The February 2026 pack was re-verified. |
| Persistence | Append-only patterns exist: `ai_execution_authorizations` with a PostgreSQL trigger (migration 0004), review decisions, and case entries with an optimistic revision. | **New** table `audit.investigation_reviews` (migration **0005**), built in the same style: append-only, trigger refuses UPDATE and DELETE, unique `(investigation_id, revision)`. A file-backed twin covers file mode. |
| Audit infrastructure | `operations.activity_events`; jobs; published and unpublished artefacts. | **Reused.** Decisions emit `AI_REVIEW_ACCEPTED` / `AI_REVIEW_REJECTED` activity events. The Review History is assembled from existing records: jobs, artefacts and decisions. There is no second audit system. |
| Identity | No accounts. The reviewer is the configured analyst (`UC042_ANALYST_ID` / `UC042_ANALYST_NAME`). | **Reused** unchanged. |
| Cases (`services/cases.py`) | A separate, explicit case workflow. | **Not required** for ACCEPT / REJECT, as specified. Cases are unchanged. |

---

## 2. Behaviour delivered

| # | Requirement | Implementation |
| --- | --- | --- |
| 2 | Keep the three-column workspace | Left: ID, category, amount, severity, deterministic status (OPEN + UNRESOLVED), AI status, analyst status ([05](23_screenshots/05_exception_list_statuses.png)). Centre: unchanged. Right: AI panel with the 5 tabs; Analyst Review directly below the findings; Review History. |
| 3 | ACCEPT / REJECT bound to the exact investigation and findings version | Each record stores `investigation_id`, `findings_sha256` (of the stored `findings.json`) and `findings_schema_version`. The library refuses a decision whose hash differs from the artefact ("review it again"). |
| 3 | REJECT needs a reason, kept verbatim | The textarea "Reason for rejection" cannot be saved when empty or whitespace-only ([02](23_screenshots/02_reject_reason_required.png)). The backend refuses it too (`422 REJECTION_REASON_REQUIRED`). A DB CHECK constraint backs this up. The text is stored and published exactly, including spaces and line breaks. |
| 3 | Decision distinct from the AI assessment | A separate "Analyst review" block, labelled "separate from the AI's assessment" ([06](23_screenshots/06_analyst_review_rejected.png)). In the report it appears as its own item type, "ANALYST DECISION: REJECTED / ACCEPT". |
| 4 | Final pack follows the decision | **ACCEPT:** the AI summary, findings and citations, plus the analyst decision and comment. **REJECT:** decision, verbatim reason, reviewer and time. There is no AI summary, assessment, finding, hypothesis, recommendation or evidence-index entry for the rejected investigation, and it is excluded from the AI closing-summary input ([11](23_screenshots/11_final_pdf_html_section7_rejection.png)). JSON, HTML and PDF all come from the same blocks. |
| 4 | No workflow trail in the PDF | The report shows only the active decision. Superseded decisions and history are application data, and a test checks the PDF for this. |
| 5 | Review History, append-only | `GET /packs/{p}/exceptions/{e}/review-history` lists, in time order: AI requested, started, completed or failed, published, not published; and analyst decisions with exact text, reviewer, revision, and *Active* / *Superseded* ([13](23_screenshots/13_review_history_reject_then_accept.png)). A changed decision is a new row (`revision + 1`, `supersedes_review_id`). `expected_revision` gives `409 REVIEW_DECISION_CONFLICT` on an out-of-date view. |
| 6 | Exception status independent | Decisions never touch the pack, the engine results or the artefact. The exception stays `OPEN` / `UNRESOLVED`. Tests compare the API values and the file hashes before and after. |
| 7 | Final review integration | INCLUDED + pending → blocker `AI_REVIEW_PENDING` (never treated as accepted). INCLUDED + REJECT → info: reported by the reason. A decision change after a preview → blocker `PREVIEW_STALE`, and GENERATE returns `409 PREVIEW_STALE` ([14](23_screenshots/14_final_review_preview_stale.png)). NOT_INVESTIGATED and EXCLUDED_BY_ANALYST are unchanged. Default selections prefer an investigation that has already been reviewed. |
| 8 | Persistence and API | See §3. Validation runs on the backend (service, Pydantic request model and DB constraints) as well as in the frontend. |

---

## 3. API and data model

**Endpoints** (FastAPI, `uc042app/api/routers/investigations.py`):

- `POST /api/v1/investigations/{id}/analyst-review` — body `{decision: ACCEPT|REJECT, comment?, rejection_reason?, expected_revision}`.
  - Returns 201 with the record.
  - 422 codes: `REJECTION_REASON_REQUIRED`, `COMMENT_NOT_ALLOWED`, `REASON_NOT_ALLOWED`, `REVISION_REQUIRED`.
  - 409 codes: `REVIEW_DECISION_CONFLICT`, `ARTEFACT_UNVERIFIED`, `PACK_BUSY`.
  - 404 when the investigation is not published.
- `GET /api/v1/investigations/{id}/analyst-reviews` — every decision, oldest first, with `active`.
- `GET /api/v1/packs/{pack}/exceptions/{exc}/review-history` — the read-only timeline.
- Existing responses gain `analyst_review` (the active decision, or `null` = pending): `PublishedInvestigation` and `InvestigationDetail`.

**Table `audit.investigation_reviews`** (migration `0005_investigation_reviews`):
- Columns: `analyst_review_id`, `period_id`, `pack_id`, `exception_id`, `investigation_id`, `findings_sha256`, `findings_schema_version`, `decision`, `comment`, `rejection_reason`, `reviewer_id`, `reviewer_name`, `decided_at`, `revision`, `supersedes_review_id`.
- Constraints: UNIQUE(`investigation_id`, `revision`); CHECK decision ∈ {ACCEPT, REJECT}; CHECK a REJECT has a non-blank reason.
- A PostgreSQL trigger refuses UPDATE and DELETE.
- Downgrade refuses while rows exist.

**Final pack schema `uc042-final-pack/1.1`** (only when assembled with analyst reviews):
- `exception_register[].investigation.analyst_review`;
- `metadata.completeness.investigation_coverage.{accepted_by_analyst, rejected_by_analyst}`;
- `analyst_reviews{notice, accepted, rejected}`;
- `audit_trail.analyst_reviews[]`.

`validate_final_pack` re-checks independently that:
- the decision is copied exactly (even a trimmed reason is an error);
- no rejected investigation appears in any AI section, the evidence index or the provenance;
- a pack without reviews carries none of these fields.

---

## 4. Modified files

**Backend**
- `uc042app/db/models.py` — `InvestigationReviewRow`
- `uc042app/db/migrations/versions/0005_investigation_reviews.py` — **new**
- `uc042app/repositories/base.py`, `repositories/files.py`, `db/repositories.py` — repository interface plus file and SQL implementations
- `uc042app/services/investigation_reviews.py` — **new** (decisions and review history)
- `uc042app/services/__init__.py`, `services/investigations.py`, `services/reviews.py` — wiring, `analyst_review` on rows, final-review gating and staleness
- `uc042app/api/schemas.py`, `api/routers/investigations.py` — models and endpoints

**Final-pack library**
- `uc042lib/final_pack/model.py` (`AnalystReview`, schema 1.1, notice), `snapshot.py`, `assemble.py`, `validate.py`, `summary.py`, `report.py`, `render_html.py`, `render_pdf.py`, `__init__.py`

**Frontend**
- `src/components/workspace/AnalystReview.tsx` — **new** (Analyst Review section, status badge, Review History panel)
- `src/components/workspace/AiPanel.tsx`, `src/pages/WorkspacePage.tsx`, `src/pages/ReviewPages.tsx`
- `src/api/types.ts`, `src/api/endpoints.ts`, `src/data/DataSource.ts`, `src/data/apiSource.ts`, `src/data/mock/MockDataSource.ts`
- `src/components/common/index.tsx` (badge tones), `src/styles/components.css`

**Tests**
- `tests/test_analyst_review.py` — **new**: scenarios A–F plus library gating
- `frontend/src/test/analystReview.test.tsx` — **new**
- `tests/api_support.py` — new `accept_investigation` helper
- `tests/test_api_reviews.py`, `tests/test_api_monthly.py`, `tests/test_phase8.py` — these now record an ACCEPT before their final reviews (the new mandatory rule)

The complete diff against the live repository is in `%USERPROFILE%/p10/changes.patch` (2,426 lines).

---

## 5. Migration status

| Database | Status |
| --- | --- |
| **Live `uc042`** | **Not migrated** (still at `0004_ai_authorization_lineage`). Only read, by `pg_dump`, to create the disposable clone. |
| `uc042_p10` (clone of live, 5 Nov 2026) | Upgraded 0004 → **0005**. All 18 existing tables kept identical row counts; the new table is empty; trigger and constraints are present. Used for the browser E2E. |
| `uc042_p10_test` | 0004 → 0005 → downgrade to 0004 (empty table, allowed) → 0005. Used for the PostgreSQL test run. |

---

## 6. Tests and results

| Run | Result |
| --- | --- |
| Baseline (unmodified pristine copy), full backend suite | 627 tests, **1 failure**: `test_demo_history … test_protected_trees_unchanged` (the known guard digest of `uc042lib/final_pack`, awaiting the owner's re-pin). |
| Modified copy, full backend suite, file repositories | **638 tests, 2 failures, 22 skipped.** (1) the known guard digest above; (2) `ProtectedArtefacts`, caused by the E2E's final packs in the copy (§8). After moving them out, `ProtectedArtefacts` passes. Before the test updates, the first run showed 16 failures and 1 error, all `AI_REVIEW_PENDING` (the new mandatory rule); those tests now record an ACCEPT first. |
| `tests.test_analyst_review` (11 tests), file / SQLite / PostgreSQL | All pass. The PostgreSQL trigger test (UPDATE and DELETE refused) runs only in PostgreSQL mode, and passes. |
| `test_analyst_review` + `test_api_reviews` + `test_db`, PostgreSQL (`uc042_p10_test`) | 51 tests. Only failure: `ProtectedArtefacts` — caused by the browser E2E, which published final packs into the copy's default `final_packs/` folder (environment, not code; see §8). |
| Frontend `vitest` | 54 passed, 2 skipped (live-API tests), including 4 new analyst-review tests. |
| `tsc --noEmit`, `npm run build`, `check_contract.py` | Pass. The contract check covers 52 interfaces, including the new ones. |
| Published 1.0 pack `FAP-H202602-PER-2026-02-v1-b8dd53bd2449` | `verify_final_pack` → verified with the new renderer (byte-identical). |

**Scenario coverage** (`tests/test_analyst_review.py`):
- **A:** ACCEPT saved with timestamp and reviewer; history shows ACCEPT; the preview includes the AI findings and citations; GENERATE; pack verifies.
- **B:** empty and whitespace reasons refused (422); verbatim storage; history shows the exact reason; final PDF contains it; summary, hypothesis and next-step markers absent from JSON, HTML and PDF; original findings still served; artefact unchanged.
- **C:** REJECT then ACCEPT; old revision refused (409); both kept, latest active; preview stale and GENERATE 409; new preview and final pack follow ACCEPT.
- **D:** exception OPEN / UNRESOLVED and engine results identical after both decisions.
- **E:** pending investigation blocks; EXCLUDED_BY_ANALYST and NOT_INVESTIGATED still generate.
- **F:** three revisions, append-only; repository refuses a stale revision; artefact and pack hashes unchanged; pack verifies; PostgreSQL trigger.

**Browser E2E, synthetic data, isolated copy** — September S05, `INV-EXC-S05-01-65bd05498b9e`:
1. REJECT with a three-line reason ([01](23_screenshots/01_workspace_pending_review.png)–[07](23_screenshots/07_review_history_reject.png)).
2. Final review, preview, GENERATE → `FAP-S05-PER-2026-09-v1-753e9354e49a`. It verifies; schema 1.1; `ai_investigations: []`; the reason is in the PDF exactly; the AI summary, hypothesis and next step are not ([11](23_screenshots/11_final_pdf_html_section7_rejection.png), [`final_v1_rejected.pdf`](23_screenshots/final_v1_rejected.pdf)).
3. New review previewed, then ACCEPT in the workspace → readiness PREVIEW STALE, and GENERATE returns 409 ([14](23_screenshots/14_final_review_preview_stale.png)).
4. New preview, then GENERATE → `FAP-S05-PER-2026-09-v2-9aff43513bcb`. It verifies, includes the accepted investigation (26 citations), and supersedes v1.

No paid AI call was made: the copy has no key, and outbound HTTP was routed to a dead proxy. The closing summary was therefore UNAVAILABLE and acknowledged through the existing flow.

---

## 7. Differences from the agreed behaviour, and remaining gaps

1. **"Analyst opened a review" is not recorded.** Opening a page is not an accurate review event in this application. The history records requests, starts, completions, failures, publications and decisions.
2. **The AI closing summary sees that an investigation was rejected, but not the reason.** This prevents the model from paraphrasing the analyst's words. The reason appears only verbatim, in section 7 and in the exception register.
3. **No new report section.** The analyst review content goes at the top of section 7 ("AI investigation summary") and in the exception register, plus counts in sections 1 and 2. A 17th section would desynchronise the UI's fixed 16-section report navigation and the existing section tests.
4. **PDF character set.** The PDF uses the standard Helvetica (cp1252) fonts. Characters outside cp1252 in a reason are mapped by the existing `pdf_text()` (for example `→` becomes `->`). JSON and HTML keep the exact text. This limitation already applies to all PDF text.
5. **Time zone of `decided_at`.** In PostgreSQL mode, timestamps come back in the server's local offset (for example `+05:30`), as for other tables read through `_row_dict`. They are correct ISO instants, but are not normalised to UTC.
6. **Library callers that pass no analyst reviews** get the unchanged Phase 1 (schema 1.0) behaviour. The application always passes them.
7. **The mock data source cannot record decisions.** It shows them as backend-only, consistent with other write operations.
8. **Guard test `test_demo_history … test_protected_trees_unchanged`.** It already failed before this work (pending re-pin). It now also reflects the changed `uc042lib/final_pack` digest. Re-pinning needs the owner's decision.

---

## 8. Environment notes

- The browser E2E published two final packs into the **copy's** `final_packs/`. That trips `ProtectedArtefacts` in the copy's test run only. Moving them to `%USERPROFILE%/p10/e2e_final_packs/` clears it.
- Disposable resources:
  - databases `uc042_p10` and `uc042_p10_test`;
  - folder `%USERPROFILE%/p10` (copy, state, dumps, scripts, shots).
  - Drop them when no longer needed.

## 9. Not applied to the live repository (decision needed)

The running live UI (Vite on 5173) hot-reloads from the live `frontend/src`. The live backend (8000) refuses to start at database revision 0004 once migration 0005 is in the code. Copying this change into the live repository would therefore:
1. immediately change the running live UI, which would then call endpoints the running backend does not have;
2. stop the next live backend restart until migration 0005 is applied to live `uc042`.

Both need the owner's authorisation. The recommended steps, once authorised:
1. Back up `uc042`.
2. Apply `changes.patch` (or copy the files listed in §4).
3. Run `python -m uc042app.admin db-upgrade`.
4. Restart the backend and Vite.
5. Re-run the suite.
6. Decide the guard re-pin.
