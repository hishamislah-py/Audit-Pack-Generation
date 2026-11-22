# UC-042: UI interaction test matrix

Legend:
- **RT**: runtime-tested. The action was executed in the browser and its result observed, and for business actions verified in the backend afterwards.
- **RO**: read-only inspected. The control was clicked or opened in the browser, and a data-changing dialog was opened and cancelled.
- **SC**: source-code traced. The implementation and API were read, and the action is covered by automated tests, but it was not executed in the browser in this round.
- **NT**: not tested.

Environments:
- **P10**: `:5190 → :8030 → uc042_p10b`. Read-only exploration only; no business record was created.
- **E**: the disposable clone `:5191 → :8031 → uc042_p10e`.
- **E-AI**: clone E with the existing project's OpenAI settings loaded (key, provider and model only).

Evidence: step IDs refer to screenshots and page text in `p10/ui_audit/shots` and `p10/ui_audit/text`. Results of the browser workflows are in `p10/ui_audit/evidence/e2e_results.json` (31 checks) and `e2e_upload_results.json` (6 checks).

## Navigation and read-only controls

| Page | UI label / control | Type | Executed? | Env | Observed result | Blocker |
|---|---|---|---|---|---|---|
| Global | Each sidebar entry, from the S05 workspace context (9 original, 6 simplified) | Nav | RO | P10 | Destinations as listed in the inventory, §3 (`E95_*`, `A95_*`) | — |
| Global | Period selector → March | Nav | RO | P10 | Opens `/reports/PER-2026-03` and clears the pack context (`E99`, `A99`) | — |
| Global | Breadcrumbs | Nav | RO | P10 | Root and period crumbs (now Monthly reports / month report) | — |
| Global | Unknown URL `/nothing-here` | Nav | RO | P10 | "Page not found" with a link back (`E90`, `A90`) | — |
| Dashboard (original) | Period row select (Feb), September view, KPIs, side panels | RO | RO | P10 | `E01`–`E04` | Page removed later |
| Monthly reports | Search, Year, Month, Status, Final pack, Sort; empty search | RO | RO | P10 | Filters applied through the URL; empty state shown (`E05`–`E08`) | — |
| Monthly reports | Row / month link | Nav | RT | E | Opens the month (`W1_02`) | — |
| New monthly report | Month, Year, Title, validation messages | RO | RO | P10 | Form only (`E09`) | Create not executed |
| Month report | Section index anchors, KPIs | RO | RO | P10 | `E10`, `A10` | — |
| Month report | Change title → Cancel | RO | RO | P10 | Editor opens and closes (`E11`) | Save not executed |
| Month report | Add Supporting Document: Type = Correction, Replaces | RO | RO | P10 | Form changes (`E12`) | Upload from this form not executed |
| Month report | Pack link in section 3 | Nav | RT | E | Opens S01 (`W1_03`) | — |
| Month report | Exceptions / Investigations tables, links | Nav | RO | P10 | Links to the workspace and to the investigation record | — |
| Month report | Months: Feb (published), Jun (discrepancy), Nov (no records), BAD id, legacy `/periods/` | RO | RO | P10 | `E13`–`E17`, `A13`–`A17` | — |
| Pack | External / Internal / Differences tabs (S01, S05) | RO | RO | P10 | `E20`–`E22` | — |
| Pack | Open exceptions (N) | Nav | RT | E (mock in unit tests) | Opens the workspace; absent for S01 (`W1_03`) | — |
| Pack | Open final review | Nav | RT | E | `/packs/S01/review` | — |
| Workspace | Exception list items (S05, S02, SC2, SC5C, S01) | Nav | RO | P10 | `E30`–`E42`, `A30`–`A42` | — |
| Workspace | AI tabs: Summary, Observations, Hypotheses, Gaps & conflicts, Next steps | RO | RO | P10 | `E32_*` | — |
| Workspace | Investigation record select: ineligible / pending | RO | RO | P10 | `E33`, `E34` | — |
| Workspace | Source record click → citation inspector | RO | RO | P10 | `E37` | — |
| Workspace | Collapsible panels (evidence, AI records, relationships, case) | RO | RT | E | Supporting records opened for S02 (`W2_02`) | — |
| Workspace | Exception summary "Next step" button (scroll / link) | Nav | RT | unit + E | Link "Continue to final review" verified; scroll verified in vitest | — |
| Workspace | Technical record link → `/investigations/:id`; tabs Evidence, Tool calls, Validation | Nav | RO | P10 | `E50`–`E51` | — |
| Workspace | Legacy `/exceptions/:id` URL | Nav | RO | P10 | Redirects to the workspace (`E43`) | — |
| Case | Case page (existing S02 case) | RO | RO | P10 | `E52` | Entries not added |
| Review | `/packs/:id/review` (S05, S01) | Nav | RO | P10 | Earlier reviews listed (`E60`, `E61`) | — |
| Review | All / Final reviews list | Nav | RO | P10 | `E62`, `A62` | — |
| Review | HTML / PDF / JSON modes, section select, table of contents | RO | RO | P10 | `E66`, `E67` | — |
| Review | Edit selections → Cancel | RO | RO | P10 | Modal opens and closes (`E64`) | Save not executed |
| Review | HOLD → Cancel | RO | RO | P10 | Modal opens and closes (`E65`) | SAVE HOLD not executed |
| Review | Unknown review | RO | RO | P10 | "Review not found" (`E68`) | — |
| Final packs | List; detail tabs PDF / HTML / JSON / Version history (S05 v2, Feb v1) | RO | RO / RT | P10, E | `E70`–`E73`, `W5_04`–`W5_07` | — |
| Upload | Upload page, month select | RO | RO | P10 | `E80`, `E81` | — |

## Business actions

| # | Page | Action | Type | Executed? | Env | Observed result | Verified by |
|---|---|---|---|---|---|---|---|
| B1 | Workspace | Run investigation → authorise (real provider) | AI | **RT** | E-AI | Real OpenAI call. The provider refused it with **HTTP 429 `credit_balance_exhausted`**. The job is FAILED with that exact message, the attempt is kept unpublished, and nothing is fabricated (`RA01`–`RA03`) | UI and job record |
| B2 | Review | Generate closing summary and preview → authorise (real provider) | AI | **RT** | E-AI | Real OpenAI call, also refused with 429 `credit_balance_exhausted`. The preview was built with the summary UNAVAILABLE; the provider detail was stored (`RS01`–`RS04`) | API `current_preview.closing_summary.failure` |
| B3 | Workspace | Run investigation with no provider configured | AI | RT | E | The dialog names "OPENAI_API_KEY is not set in the backend environment"; Authorise is disabled (`W2_03`) | UI |
| B4 | Workspace | ACCEPT an eligible investigation with a comment | Data | **RT** | E | Recorded (AR-465dde4f…); appears in Review history; exception still OPEN / UNRESOLVED (`W3_02`) | API |
| B5 | Workspace | REJECT with a blank reason | Data | **RT** | E | Save stays disabled | UI |
| B6 | Workspace | REJECT with a Unicode / punctuation reason (line break, Ł ó ź, £, →, “ ”, —) | Data | **RT** | E | Saved byte-exact; shown in history; the earlier decision is marked Superseded (`W4_01`, `W4_02`) | API |
| B7 | Review | Preview made before a changed decision | Data | **RT** | E | Checklist: "The preview is out of date"; GENERATE disabled (`W5_01`) | UI |
| B8 | Review | GENERATE on the stale snapshot (direct API) | Data | **RT** | E | 409 `PREVIEW_STALE` | API |
| B9 | Review | Regenerate preview | AI / Data | **RT** | E | Fresh preview: the rejected AI text is absent and the reason is present (`W5_02`) | API (preview HTML) |
| B10 | Review | GENERATE (acknowledgements, modal) | Data | **RT** | E | `FAP-S05-PER-2026-09-v3-9e4d04058efc`; verify `verified: true` | API |
| B11 | Final pack | JSON / HTML / PDF contents | DL | **RT** | E | All three hold the exact reason; none holds the rejected AI content; `ai_investigations` is empty | API files and pypdf text |
| B12 | Final pack | Version history | RO | RT | E | v1, v2, v3 listed (`W5_07`) | UI |
| B13 | Pack review | Open a new final review (S01) | Data | **RT** | E | Review opened; checklist "0 exception(s)" | UI |
| B14 | Review | Clean pack: preview → GENERATE | Data | **RT** | E | `FAP-S01-PER-2026-09-v1-7526c9d28470`, no exceptions (`W1_06`–`W1_08`) | API |
| B15 | Upload | Upload 3 synthetic September CSVs to November, one chosen twice | Data | **RT** | E | Batch created; identified by content (IN-02, IN-07, IN-09); `WRONG_PERIOD`, `TIMING_DIFFERENCE`, `DUPLICATE_IN_BATCH`; status VALIDATED; no run (`U01`–`U04`) | API |
| B16 | Upload batch | Confirm batch with a pending decision | Data | RT | E | Confirm disabled until the flagged file is decided | UI |
| B17 | Upload batch | Include / Exclude with comment, Confirm, Start processing | Data | SC | — | Covered by `archive.test.tsx` and the backend upload tests | Not executed: would process an incomplete synthetic batch |
| B18 | Month report | Reassess after publication | Data | SC | — | `test_phase8`, `test_monthly_reports` | Not executed in the browser |
| B19 | Month report | Change title (save), Add supporting document (upload) | Data | SC | — | `reports.test.tsx` | Not executed in the browser |
| B20 | New report / month without data | Create period, "Open <month> for upload" | Data | SC | — | `reports.test.tsx`, `archive.test.tsx` (the button calls `openPeriod`) | Not executed in the browser |
| B21 | Review | Edit selections → Save (include / not investigated / exclude with reason) | Data | SC | — | `test_api_reviews`, `screens.test.tsx` | Not executed in the browser |
| B22 | Review | HOLD with reason | Data | SC | — | `test_api_reviews`, `screens.test.tsx` | Not executed in the browser |
| B23 | Case | Open case, add entries, disposition, request AI | Data / AI | SC | — | `test_phase8` (cases) | Not executed in the browser |
| B24 | AI | Successful live investigation (tool loop, citations, persistence) | AI | **NT live** / SC mocked | — | Mocked provider: `test_tool_calling` (8 tools, multi-round loop, call-id linkage, limits), `test_openai_provider` (Responses request shape, errors, retries), `test_investigation*` (validation, persistence) | **Blocked: provider account has no credits** |
| B25 | AI | Successful live closing summary | AI | **NT live** / SC mocked | — | `test_closing_summary`, plus the new `test_closing_summary_model_never_receives_rejected_ai_content` (inspects the real `OpenAIInvestigator` request with a mocked HTTP client) | **Blocked: provider account has no credits** |
| B26 | Layout | Narrow / mobile widths | — | NT | — | Responsive CSS was not re-verified after the layout change | Not tested |
