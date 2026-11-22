# UC-042: complete UI exploration inventory

| | |
|---|---|
| Date | 5 November 2026 |
| Environment explored | P10 isolated copy: frontend `http://127.0.0.1:5190`, backend `http://127.0.0.1:8030`, database `uc042_p10b` (verified through `/health`: label "PHASE 10 V2 E2E (isolated copy, disposable database uc042_p10b)") |
| Data-changing tests | Disposable clone **E**: frontend `:5191`, backend `:8031`, database `uc042_p10e`, restored from the pre-test backup of `uc042_p10b`, with its own state, document store, investigations and final-pack folders |
| Live application | Ports 5173 / 8000 (PIDs 15732 / 15284) were never contacted and are unchanged. The live `uc042` database was not connected to |
| Method | Headless Edge driven over the DevTools protocol with real mouse events (`p10/ui_audit/explore.py`). Each step recorded every visible control, the API calls made, any console exceptions, a full-page screenshot and the page text. Source code was read to confirm routing and API behaviour |
| Raw evidence | `p10/ui_audit/evidence/explore_log.json` (74 steps, original UI); `explore_after_log.json` (71 steps, simplified UI); de-duplicated catalogues `*_catalogue.json` (559 distinct controls before, 371 after); screenshots `p10/ui_audit/shots/` (E* = original UI, A* = simplified UI) |

This document describes the application **as it was found** (the original P10 UI). For each item, the last column gives the decision that was later implemented; see `IMPLEMENTATION_CHANGELOG.md`. No console exception occurred on any of the 145 explored steps.

## 1. Initial environment and data state (recorded before any change)

| Item | Value |
|---|---|
| Reporting periods | 9 with data (January to September 2026), plus October (no data) and November (open for upload, current month) in the selector |
| Packs | 17 verified deterministic packs: 9 September demonstration scenarios and 8 historical monthly packs (January to August) |
| Final reviews | 4: S05 × 2 GENERATED; February × 1 GENERATED and × 1 OPEN |
| Final audit packs | 3: S05 v1, S05 v2, February v1 |
| Investigation case | 1 (`CASE-6aba11c883a2150c4932f8e7`, S02, OPEN), created before this work began |
| AI configuration | provider `openai`, model `gpt-6-luna`, `provider_configured: false` (the P10 backend runs with the key blanked) |
| Backups taken first | `p10/backups_ui/uc042_p10b_before_ui.dump` (pg_dump), `p10_uc042_src_before_ui.tgz` (source), `p10_state_before_ui.tgz` (state, document store, final packs) |

## 2. Routes (all 17, from `frontend/src/App.tsx`)

| Route | Screen | Reached from |
|---|---|---|
| `/` | Dashboard ("Reconciliation overview") | Sidebar 01, breadcrumb root, 404 page |
| `/reports` | Monthly reports archive | Sidebar R, dashboard link |
| `/reports/new` | Add new monthly report | Archive button |
| `/reports/:periodId` | Monthly report (period workspace, 9 sections) | Archive row, period selector, many links |
| `/periods/:periodId` | Legacy URL, redirects to `/reports/:periodId` | Old links only |
| `/upload` | Upload financial documents | Sidebar ↑, dashboard, report, pack page |
| `/uploads/:batchId` | Upload batch: validation, decisions, confirm, process | After upload; report history |
| `/packs/:packId` | Deterministic reconciliation pack | Dashboard rows, report section 3, many links |
| `/packs/:packId/workspace[/:exceptionId]` | Exception and investigation workspace | Pack, report, sidebar 03, review |
| `/packs/:packId/exceptions/:exceptionId` | Legacy URL, redirects to the workspace | Old links only |
| `/packs/:packId/review` | Final-review entry: forwards to the active review, otherwise lists earlier reviews and offers "Open a new final review" | Pack, report, sidebar 04 |
| `/reviews` | All final reviews | Sidebar "All reviews", sidebar 04 with no context |
| `/reviews/:reviewId` | Final audit-pack review | Lists, sidebar 04 |
| `/final-packs` | All final audit packs | Sidebar "All final packs", sidebar 05 with no context |
| `/final-packs/:finalPackId` | One final audit pack | Lists, report section 7, after GENERATE |
| `/investigations/:investigationId` | AI investigation technical record | Report section 5, workspace link, case page |
| `/cases/:caseId` | Analyst's investigation case | Workspace "Open investigation case" |
| `*` | Page not found | Any unknown URL (tested: `/nothing-here`) |

## 3. Global navigation (original)

| Area | UI label | Destination (as clicked; step `E95_*`) | Observation | Decision |
|---|---|---|---|---|
| Sidebar · WORKFLOW | 01 Dashboard | `/` | A second overview of the same months as Monthly reports | **Merged** into Monthly reports; `/` redirects there |
| | R Monthly reports | `/reports`, or the current report URL | Archive of months | **Kept** (step 1) |
| | 02 Reconciliation pack | Current pack, else `month#reconciliation`; **disabled** with no context | Context-dependent and sometimes disabled | **Kept**, renamed "Reconciliation packs", never disabled (falls back to the month, then to the archive) |
| | 03 Exceptions & investigation | Current pack's workspace, else `month#exceptions`; disabled with no context | Leads to two different-looking screens (the workspace, or the month report's exception table) | **Kept**, renamed "Exceptions" |
| | 04 Final review | Current review / pack review / `/reviews` | With no context it is identical to "All reviews" | **Kept**, absorbs "All reviews" |
| | 05 Final audit pack | Current final pack, else `/final-packs` | From the workspace it equals "All final packs" (step `E95_nav_ws_Final_audit_`) | **Kept**, renamed "Final audit packs", absorbs "All final packs" |
| Sidebar · RECORDS | R All reviews | `/reviews` | Duplicate of 04 with no context | **Removed** (the list remains via Final review) |
| | F All final packs | `/final-packs` | Duplicate of 05 | **Removed** (the list remains via Final audit packs) |
| | ↑ Upload documents | `/upload` | Not tied to the selected month | **Kept** as step 2, now opens `/upload?period=<selected month>` |
| Sidebar | CURRENT PACK box | Read-only | Shows the pack ID and month | Kept |
| Top bar | Period (select) | `/reports/<period>`; clears pack context | Options list every month with a state suffix ("open for upload", "no data") | Kept |
| | Data: <environment label> | Tooltip only | Identifies the database; useful for P10, technical | Kept |
| | Live backend / Backend unreachable | Read-only | | Kept |
| | SYNTHETIC DATA, analyst avatar | Read-only | | Kept |
| Breadcrumbs | Root "Reconciliation" | `/` (dashboard) | The workspace's period crumb also pointed at the dashboard (`/?period=`) | Root is now "Monthly reports" (`/reports`); the period crumb opens the month report |

## 4. Page-by-page inventory (original UI)

Action types: **Nav** navigation · **RO** read-only / reversible · **Data** creates or changes records · **AI** paid AI call · **DL** download.

### 4.1 Dashboard `/` (steps E01–E04)
| UI label | Type | What happens | Duplication | Decision |
|---|---|---|---|---|
| KPI tiles: Reconciliation packs, Exceptions, AI investigations (eligible/published), Pending reviews, Final audit packs | RO | Counts for the selected month from `/dashboard` | Month KPIs repeat on the monthly report | Removed with the page |
| "Reconciliation periods" table (10 columns), row click | RO | Selects the month and shows its packs below | Same months as Monthly reports (which has 9 columns) | Merged: the archive gained "Uploads" and "Unresolved" columns |
| Period detail: "N demonstration scenarios" notice; scenario rows (pack type, pack, engine, evidence, exceptions, unresolved, eligible AI) | Nav | Row opens the pack | Identical to report section 3 | Merged: report section 3 gained scenario names, AI coverage and final pack |
| "Open the <month> monthly report" link | Nav | `/reports/<period>` | | Removed (redundant) |
| "Upload documents for <month>", "Open <month> packs" | Nav | `/upload?period=`, first pack | Same as report buttons | Removed (sidebar step 2 is month-aware) |
| Empty states: no data → "Open <month> for upload" | Data | `POST /periods` opens the month | **Not available anywhere else** | **Preserved**: moved to the month report of a month without data |
| "Recently generated audit packs" (5) | Nav | Final pack links | Same as Final audit packs list | Removed (the list has all) |
| "Pending reviews" | Nav | Review links | Subset of All reviews | **Preserved** as "Final reviews in progress" on Monthly reports |
| "Recent activity" (8) | RO | `/activity` log | Unique | **Preserved** on Monthly reports |

### 4.2 Monthly reports `/reports` (E05–E08)
| UI label | Type | What happens | Decision |
|---|---|---|---|
| Add New Monthly Report | Nav | `/reports/new` | Kept |
| Search title or period; Year; Month; Reporting status; Final audit pack (Any / Published / Not published); Sort (newest / oldest) | RO | Filter the table through URL parameters (tested: status, final=none, oldest, empty search) | Kept |
| Table row / month link | Nav | `/reports/<period>` | Kept |
| "Final audit pack" column | RO | **"Published (2 versions)"**: counted versions of one scenario's pack | **Fixed**: "2 of 9 packs published · 4 versions" counts per pack |
| Environment note | RO | Database and storage profiles | Kept |

### 4.3 Add new monthly report `/reports/new` (E09)
Month, Year, Report title, derived Period ID, checks (future month, existing month, title length), "Create and continue to upload" (Data: `POST /periods`). Inspected only; nothing was created in `uc042_p10b`. Kept unchanged.

### 4.4 Monthly report `/reports/:periodId` (E10–E17)
| Section / control | Type | Observation | Decision |
|---|---|---|---|
| Section index (9 anchors: Overview … Document history, Reassessment) | Nav | In-page anchors | Kept |
| KPIs: Month, Source documents, Deterministic packs, Exceptions, Published audit packs | RO | "Published audit packs" counted versions | Fixed (packs, with versions in the note) |
| Change title → Save title / Cancel | Data | Rename (opened and cancelled) | Kept |
| "Add Supporting Document" (anchor) and "Upload documents" | Nav | The first scrolls to the form in section 2; the second opens the upload page | Kept (different purposes: evidence for an existing month vs a new batch) |
| 2. Source documents; Add Supporting Document form: Type (Additional evidence / Correction), Replaces, Reason, drop zone, Remove, Upload and validate | Data | Form exercised without uploading (type → correction) | Kept |
| 3. Reconciliation results table, links "Workspace · Final review" | Nav | No scenario name, no AI coverage, no final-pack column | Improved: scenario name, AI available, latest final pack version; "Exceptions · Final review" links (Exceptions hidden for a clean pack) |
| 4. Exceptions table (exception, pack, severity, category, account, status) | Nav | No amount and no AI / analyst status | Improved: amount and AI-investigation status columns |
| 5. AI investigations table (investigation, exception, mode, assessment, model, review eligibility) | Nav | "Review eligibility" was easily confused with the analyst's review | Improved: "Final-pack eligibility" and a separate "Analyst decision" column |
| 6. Closing summary of the latest published pack; link to section 16 | RO | | Kept |
| 7. Published audit packs, JSON · HTML · PDF downloads | DL | | Kept |
| Reassessment panel (only when published) | Data | Not exercised (would create a new pack) | Kept; see the test matrix |
| 8. Document history; processing runs | RO | | Kept |
| Month without data (November in the archive list) | RO | Showed an empty report workspace | Now "No reconciliation data" with "Open <month> for upload" (from the dashboard) |
| `/reports/BAD` | RO | "Not a reporting period" | Kept |

### 4.5 Reconciliation pack `/packs/:packId` (E20–E22, S01 and S05)
| Control | Type | Observation | Decision |
|---|---|---|---|
| Investigate exceptions | Nav | Shown even for the clean S01 pack (0 exceptions) | Now "Open exceptions (N)", hidden when there are none |
| Open final review | Nav | `/packs/:id/review` | Kept |
| KPIs (period, currencies, accounts, engine status with control outcome counts, evidence, exceptions, pack hash) | RO | | Kept |
| Currencies and accounts; Source document inventory (19 files with SHA-256) | RO | | Kept |
| "Add documents for a new period" (inside the source inventory) | Nav | Unrelated to the pack being read; a third upload entry point | **Removed** |
| Tabs: External reconciliation / Internal reconciliation / Reconciliation differences | RO | All three opened | Kept |
| Exception register, row links to the workspace | Nav | | Kept |

### 4.6 Exception and investigation workspace `/packs/:packId/workspace/:exceptionId` (E30–E43)
Explored on S05-01 (3 investigations: accepted, pending and ineligible), S05-02 (none), S02 (unregistered), SC2 (ineligible), SC5C (17 exceptions), S01 (none).

| Panel / control | Type | Observation | Decision |
|---|---|---|---|
| Layout | — | Three columns. The S05 page was **7,014 px** tall: 60+ expanded evidence rows came before any AI content, and the AI findings and Accept/Reject sat in a 440 px right-hand column | Two columns: an exception list, then one main column (summary → AI and review → checks → collapsed evidence → history). The page is now 3,203 px |
| Exception list (role listbox) | Nav | Badges "AI eligible", "AI ineligible", "Not run", "Analyst: accepted" side by side | One plain status: "Not investigated", "AI awaiting your review", "AI accepted by analyst", "AI rejected by analyst", "Not usable (N)" |
| KPI strip (amount, dates, severity, evidence status, deterministic status) | RO | For SC3B, SC5A, SC5C and SC5D the amount, currency and account are blank in the pack and the category is a check code (e.g. `C11-BATCH-ARITH`) | Replaced by the **Exception summary**: what went wrong (engine notes), amounts (or computed vs reported), checks that identified it (control code, name, failed results), evidence (status, record count, missing items), AI assistance, and a **Next step** |
| Deterministic reconciliation results | RO | | Kept (collapsible, open) |
| Supporting evidence · engine retrieval (no AI); record click → Citation inspector | RO | 47 records for S05, all expanded | Kept, **collapsed by default**; the inspector opens at the top of the main column |
| Records retrieved by the AI investigation's tool calls | RO | | Kept, collapsed ("Further records the AI looked at") |
| Evidence relationships | RO | | Kept, collapsed |
| Investigation case panel: "Open investigation case" | Data | A separate notes-and-disposition feature | Kept, collapsed at the bottom ("Investigation case (optional)") |
| AI investigation: "Run investigation" → authorisation dialog (Cancel / Authorise and run) | AI | Opened and cancelled in `uc042_p10b`. With no provider, the dialog said "not configured" with an **empty reason** | Kept. The backend now names the missing variable. The button is secondary ("Run a new investigation") when a usable investigation exists |
| "Open the full investigation record" | Nav | Leads to the technical page | Kept, relabelled "Technical record of this investigation (tool calls, validation, publication)" |
| Investigation record (select) | RO | Options like `INV-… · tools · eligible · review pending` | Options lead with the date and status ("03 Nov 2026 · awaiting your review · INV-…") |
| Tabs Summary / Observations / Hypotheses / Gaps & conflicts / Next steps; citation buttons | RO | All five opened | Kept |
| Summary key/values: exception status, final-pack eligibility, model, investigated, validation, registry | RO | Technical rows mixed with business rows | Business rows kept; model, validation and registry moved to "Technical details" |
| Analyst review: Accept / Reject (radio), comment, mandatory reason, Save / Cancel | Data | Offered even for an **ineligible** investigation, where a decision changes nothing | Hidden for unusable investigations, with an explanation |
| Review history (timeline) | RO | | Kept |
| "← Reconciliation pack", "Continue to final review" | Nav | Breadcrumb period linked to the dashboard | Kept; the breadcrumb now opens the month report |

### 4.7 Other exception-related screens
| Screen | Steps | Content | Verdict |
|---|---|---|---|
| AI investigation record `/investigations/:id` | E50–E51 | Record (registry, authorisation, hashes), Eligibility, tabs Findings / Evidence / Tool calls / Validation and publication, "Open the exception workspace" | **Technical audit record.** The tool-call transcript and verification exist only here. Kept, reached as a secondary link |
| Investigation case `/cases/:id` | E52 | Exception as recorded, case history (append-only), supporting records with cite boxes, Add an entry (Note, Supporting evidence, Evidence gap, Confirmed observation, Hypothesis, Human decision with disposition and close), AI assistance (request an investigation), investigation history | A **separate analyst feature** (own notes and disposition). It does not feed the final pack. Kept, de-emphasised |

### 4.8 Final review
| Screen / control | Steps | Observation | Decision |
|---|---|---|---|
| `/packs/:id/review`: earlier reviews table, "Open a new final review" (Data) | E60–E61 | Read-only until the explicit button | Kept |
| `/reviews` (All reviews): review, pack, status, preview, last decision, final pack, updated | E62 | Same list as sidebar 04 with no context | Kept as "Final reviews", in-progress reviews first |
| Review page `/reviews/:id`: 16-section table of contents, section select, HTML / PDF / JSON modes | E63–E67 | All modes opened on a GENERATED review | Kept |
| "Generate closing summary and preview" → AI authorisation dialog | E63 | Enabled even while an included investigation awaits the analyst's decision; the backend then refuses **after** the paid-AI dialog | **Fixed**: disabled, with the reason, until the decision is recorded |
| Pack summary, Readiness (raw blocker codes such as `AI REVIEW PENDING`) | E63 | Technical wording; the closing-summary failure showed only "(configuration)" | Replaced by **"Before you generate"**: a plain checklist (exceptions included, decisions accepted / rejected / awaiting with links, preview current / out of date, closing summary with the provider's actual reason, readiness). Raw messages are kept in a collapsed list |
| Investigation selections + Edit (modal: inclusion, investigation, exclusion reason; Cancel / Save) | E64 | Opened and cancelled | Kept |
| Human review: note, acknowledgement, summary-unavailable acknowledgement, HOLD (modal: reason; SAVE HOLD) and GENERATE (modal: GENERATE PACK) | E65 | HOLD modal opened and cancelled | Kept |
| Decision history | E66 | | Kept |
| Unknown review | E68 | "Review not found" | Kept |

### 4.9 Final audit packs
| Screen / control | Steps | Observation | Decision |
|---|---|---|---|
| `/final-packs` list: final pack, source pack, version, supersedes, generated, hash | E70 | No month, no downloads, no "latest" marker | Improved: month link, JSON / HTML / PDF downloads, latest / superseded markers, count of versions per pack |
| `/final-packs/:id`: integrity status, pack record, artefacts (Open / Download for PDF, HTML, JSON), tabs PDF preview / HTML report / Canonical JSON / Version history | E71–E73 | All tabs opened (S05 v2 and February v1) | Kept |

### 4.10 Upload
| Screen / control | Steps | Observation | Decision |
|---|---|---|---|
| `/upload`: steps 1–5, Month (select with state suffixes), "These documents are" (source / additional evidence / correction), drop zone / file chooser, "Upload and validate", back link | E80–E81 | Three entry points existed (sidebar, dashboard, pack page) | One entry in the sidebar (month-aware), plus the month report's buttons |
| `/uploads/:batchId`: batch summary (valid / warnings / errors), missing required or optional evidence, "Show checks", Include / Exclude with comment, Confirm batch, Start processing, processing runs | U01–U04 (clone E) | See the test matrix | Kept |

## 5. Answers to the specific questions

**Are Dashboard and Monthly Reports duplicates?** Mostly, yes. Both listed every month with document, pack, exception and final-pack counts, and both led to the same packs. The dashboard had five features of its own: the upload / validation / processing status columns, the scenario list per month, the "Open month for upload" empty state, pending reviews and recent activity. All five were moved into Monthly reports or the month report before the dashboard was removed.

**Why does "Open in Workspace" sometimes open a different-looking screen?** Four separate causes:
1. Sidebar 03 with no open pack opened the **month report's exception table** (`/reports/<month>#exceptions`), not the workspace.
2. The workspace URL without an exception ID selects the first exception automatically. For a clean pack (S01) it shows a bare "Exceptions / No exceptions" page.
3. Investigation links in the month report (section 5) and on the case page open the **technical investigation record** `/investigations/:id`, which looks completely different.
4. "Open investigation case" opens the **case page** `/cases/:id`, a third layout for the same exception.

**Are the exception screens separate experiences or views of one exception?** They are views of one business object, the deterministic exception:

| Screen | What it is | Business need |
|---|---|---|
| Exceptions & investigation (workspace) | The exception, its checks and evidence, its AI investigations, and the analyst's decision | **Required**: the central screen |
| Exception details (month report section 4, pack exception register) | Rows in lists | Required as lists; they link to the workspace |
| AI Investigation detail | Technical record: tool calls, registry, verification | Needed for audit traceability, not for the analyst's daily task. Kept as a secondary link |
| Publication / eligibility information | Registry and validation state | Technical. The analyst only needs "usable in the final pack: yes / no (reason)", which is what now shows |
| Review history | Append-only timeline | Required (traceability); kept in the workspace |
| Investigation case | The analyst's own notes and disposition | Optional feature; kept, de-emphasised |

**Can users tell the statuses apart?** Not reliably in the original UI. For S05-01 one screen showed `OPEN`, `UNRESOLVED`, `AI eligible`, `ELIGIBLE`, `INSUFFICIENT EVIDENCE`, `VALID` and `Analyst: accepted` together. The table below is now applied consistently:

| Concept | Meaning | Where it now shows |
|---|---|---|
| Deterministic exception | Raised by the engine; status `OPEN`; resolution always `UNRESOLVED` in this application | Summary header, exception list |
| AI investigation | An optional, recorded AI analysis of one exception | "AI investigation and your review" section |
| AI assessment (e.g. `INSUFFICIENT_EVIDENCE`) | The AI's view of the evidence, labelled "AI interpretation, not fact" | The assessment card only |
| Review eligibility | Whether the investigation can be used in the final pack (registered, valid under current rules) | "Usable in the final pack: Yes / No" plus the reason |
| Analyst acceptance / rejection | The analyst's decision on a usable investigation | "AI accepted by analyst" / "AI rejected by analyst" |
| Final exception resolution | Never set by this application; exceptions stay UNRESOLVED | Stated in the summary and in the review notes |

## 6. Appendix: the generated control catalogue

The complete de-duplicated list of every visible control on every explored page (label, kind, area, href, steps where seen) is in `p10/ui_audit/evidence/explore_log_catalogue.json` (559 controls, original UI) and `explore_after_log_catalogue.json` (371 controls, simplified UI). Most of the reduction comes from the merged dashboard, the two removed sidebar entries and the collapsed evidence lists.
