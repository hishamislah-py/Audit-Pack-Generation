# 22. UC-042: Complete Product and Workflow Walkthrough

**Purpose.** This document explains the UC-042 application as it actually works today, before any UI redesign decision is made. It is written for the project owner and for ChatGPT as a shared reference. It describes; it does not recommend. Where the screen says one thing and the backend does another, both are stated.

**Audience.** The project owner (business language first), and anyone helping to make the redesign decisions. Technical detail is kept in clearly marked sections and in five appendices (22A–22E).

**Method.** I used the application in a real browser (Microsoft Edge, driven over the DevTools protocol) at 1440 × 900 and at 1024, 768 and 390 pixels wide. I clicked through every screen and recorded every API request each screen made. I then traced what I saw into the code. Four read-only code traces were made in parallel; they are published as appendices 22A–22E.

**Contents**

- 0. Which version was explored, and how
- 1. What UC-042 is and what business problem it solves
- 2. The financial operations process
- 3. The ten things the application works with (definitions)
- 4. The full user journey (with an end-to-end workflow diagram)
- 5. The monthly reporting lifecycle
- 6. Screen-by-screen explanation (22 screens)
- 7. Upload and document-management workflow
- 8. Reconciliation and exception lifecycle
- 9. Exception case-management workflow
- 10. AI investigation architecture
- 11. Closing summary and final-pack workflow
- 12. Technical architecture (with diagram and request traces)
- 13. Database and file-storage architecture
- 14. The historical data
- 15. Calculation summary: the 36 controls
- 16. What the analyst actually experiences (plain-language walkthrough)
- 17. Where the screen and the backend differ
- 18. Functional limitations and unverified behaviour
- 19. Screen-to-function mapping table
- 20. Glossary
- 21. Screenshot index
- Appendices 22A–22E

---

## 0. Which version was explored, and how

### 0.1 Code version

| Item | State on 5 November 2026 |
|---|---|
| Code explored | The **Phase 8 working tree** (report 20 and its continuation). The project is not a git repository. The code state is therefore recorded as SHA-256 hashes of 190 source files (`uc042app`, `uc042lib`, `frontend/src`, `frontend/scripts`, `tests`, `tools`). Snapshots are at `%USERPROFILE%/p9/source_start.sha` and `source_end.sha`. |
| Changes since Phase 8 ended | **None.** Every file is byte-identical to the Phase 8 end snapshot (`uc042_phase8/source_cont_end.sha`). |
| Changes during this exploration | **None.** The start and end snapshots are identical. No source, React component, style or business-logic file was modified. |
| Phase 8 changes not yet deployed | Explicit review opening; pre-execution AI authorisation (`audit.ai_execution_authorizations`); reassessment with pack lineage (`audit.pack_lineage`); lineage-aware final-pack versions; case and investigation pages; dashboard counts; performance work. |
| Pending migration | **`0004_ai_authorization_lineage`**. It has been applied only to the disposable database `uc042_p9`. The live database `uc042` is still at **`0003_unified_schemas`** (checked at the start and at the end). |

### 0.2 What was running on ports 8000 and 5173

**Nothing.** When this task started, no process was listening on 8000 (backend) or 5173 (frontend). The PostgreSQL cluster on 127.0.0.1:5433, which holds `uc042` and the test databases, was also **stopped**.

- **What happened.** The cluster's log ends at 18:14 on 4 November with no shutdown record, and `postmaster.pid` was still present. The postmaster was terminated when the shell that started it closed. Reports 18 and 19 document this known Windows behaviour. The live backend and frontend had stopped too.
- **What I did.** I restarted the cluster with the documented `pg_ctl … start` command in a long-lived background shell. Crash recovery completed normally ("redo done … database system is ready to accept connections"). No database was modified by starting it.
- **What I did not do.** I did not start the live backend or frontend, because the brief says not to restart them.

**Important for later (finding from the code trace, appendix 22D).** The Phase 8 backend refuses to start on a database that is not at the latest migration (`uc042app/db/__init__.py:47-56`). Live `uc042` is at 0003. If the live backend is started on the current code, it will refuse to start until `python -m uc042app.admin db-upgrade` has been run against `uc042`. That is an owner decision; I did not do it.

### 0.3 The isolated exploration environment

| Component | Isolated instance |
|---|---|
| Code | A full copy at `%USERPROFILE%/p9/uc042` (short path; 10,083 files), without `.env`, so it has **no OpenAI key**. The `historical-demo` storage roots are fixed relative to the code (`PROJECT/demo_history/...`), so running from a copy is the only way to isolate them. |
| Data | `packs/` (72 files), `investigations/` (34), `demo_history/` (250), `uc042_dataset/` (287) and `UC042_JAN_AUG_HISTORICAL_DEMO/` (184) were copied and **re-hashed: byte-identical** to the originals. |
| Database | `uc042_p9`. It was created from a `pg_dump` of live `uc042` (97,722 bytes, the same size as the Phase 8 pre-deployment backup, so live had not changed). It was then migrated to 0004. `verify-pack-references`: 26 references, 0 problems. `verify-registry`: 2 entries, both verify (February APPROVED; June AUTHORIZATION_DISCREPANCY). |
| Backend | `python -m uc042app --port 8029`, run from the copy. Environment label "PHASE 9 EXPLORATION (isolated copy, disposable)". |
| Frontend | Vite dev server on port 5189, using the project's own `frontend/` (read-only use) with `VITE_API_BASE_URL=http://127.0.0.1:8029`. |
| AI protection | `OPENAI_API_KEY` empty, no `.env`, and `HTTPS_PROXY` pointed at a dead local port. The backend reported `provider_configured: false`. |
| Mock-mode capture | To show the AI dialog as a configured user sees it, one screenshot was taken from the frontend's built-in mock data mode (`VITE_DATA_SOURCE=mock`, port 5190). That mode has no backend and makes no AI call. |

**What the exploration changed, and where.** All changes are in `uc042_p9` and `%USERPROFILE%/p9`; nothing else changed.

- **Created:** October 2026 (a test month with invalid files); a March 2026 upload, confirmation and processing run (new pack `PACK-CASE-PER-2026-03-f91f3d2d6e6c`); a March correction; a February "additional evidence" upload plus a reassessment (new pack `PACK-CASE-PER-2026-02-19fbd4d1c1ce`, lineage recorded); one new review session on that reassessed pack; one exception case on September S05 with six entries.
- **Never done:** no AI authorisation was recorded (`audit.ai_execution_authorizations`: 0 rows); no preview was generated; no HOLD or GENERATE was executed; no final pack was created.

**Live and original data.**

- Live `uc042`: still at 0003, still 2 review sessions, still 9 periods.
- No file under `packs/`, `investigations/`, `demo_history/`, `uc042_dataset/` or `UC042_JAN_AUG_HISTORICAL_DEMO/` was modified.
- June and September investigation states were not touched.

---

## 1. What UC-042 is and what business problem it solves

**The business.** UC-042 models an **electronic-money institution** (EMI): a firm that holds money for its customers on prepaid cards or e-wallets. UK rules (the FCA's safeguarding requirements, cited in the code as CASS 15) require the firm to keep customer money **separate from its own money**, in designated safeguarding bank accounts. It must prove, **every business day**, that it holds at least as much as it owes its customers.

**The monthly problem.** At month end, an analyst must assemble an **audit pack**. The pack shows, for every reconciliation day and every currency or account:

- that the firm's books agree with the bank;
- that the money held covers what is owed to customers;
- that settlements, transactions, refunds and unallocated receipts all tie up;
- which problems (**exceptions**) remain, what evidence exists and what is missing.

Doing this by hand across 19 kinds of documents and thousands of records is slow and error-prone. The result also has to be defensible: every number must trace back to a source record.

**What UC-042 does.**

1. **Collects the month's documents** (14 CSV files and 5 PDFs: bank statements, ledger, client balances, settlements, policy…). It identifies each file by its content, and checks dates and duplicates.
2. **Runs a deterministic reconciliation engine**: ordinary Python with fixed rules and no AI. It performs 36 checks and produces an immutable **reconciliation pack** listing every result and every **exception**.
3. **Lets the analyst investigate exceptions.** The analyst works with the source records behind each exception, can keep a **case** of notes and decisions, and can authorise an **AI investigation**. The AI reads the hash-verified source records through read-only tools. It writes observations, hypotheses and evidence gaps, every one cited to a record. It never resolves anything.
4. **Produces the final audit pack.** In a **final review**, the analyst picks which investigation represents each exception and authorises one AI **closing summary**. The analyst reads an exact preview, then records **HOLD** or **GENERATE**. GENERATE assembles a write-once **final audit pack** (JSON, HTML, PDF and a hash manifest) by deterministic code.

**What it deliberately does not do.**

- It never resolves an exception or changes an engine result.
- It never certifies compliance.
- It never lets the AI decide anything.
- It never overwrites a published artefact. Corrections and new evidence produce **new versions**, linked to the old ones.

All data in the application is **synthetic**: a fictional firm (`SYN-EMI-001`), GBP and EUR accounts, January–September 2026. The banner "Synthetic data only. Not a compliance opinion. AI content is an aid to human review." is on every screen.

---

## 2. The financial operations process

How a month is reconciled in the business that UC-042 models:

| Step | What the firm does | Evidence it produces (UC-042 evidence type) |
|---|---|---|
| Daily, at 17:00 London time | Takes a snapshot of every customer's balance | IN-03 client balance snapshots |
| | Calculates what it owes customers (the **requirement**) and what it holds for them per its own books (the **resource**), per currency, and records the difference | IN-05 internal reconciliation records |
| | Obtains the bank's 17:00 balance confirmation for each safeguarding account and compares it with its ledger | IN-07 bank balance confirmations; IN-06 external reconciliation records |
| | Logs any discrepancy and what was done about it | IN-14 discrepancy log |
| Continuously | Posts every movement on the safeguarding accounts in its cash book | IN-10 cash book |
| | Receives bank statements (daily headers and individual entries) | IN-08 EOD statements; IN-09 statement entries |
| | Records customer transactions (card loads, spends, refunds, bank loads, redemptions) | IN-11 client transactions |
| | Settles card-scheme and acquirer batches (gross, fees, net) | IN-12 batch headers; IN-13 batch lines |
| | Holds money it cannot yet attribute to a customer | IN-04 unallocated receipts register |
| Standing documents | Reconciliation-day calendar; account inventory; bank acknowledgement letters designating the accounts as safeguarding; the reconciliation policy (which fixes the 17:00 point and method) | IN-01, IN-02, IN-15, IN-16, IN-17 |
| Optional | Governance register (accountable person); receipt for last month's regulatory return | IN-18, IN-19 |

**Two kinds of reconciliation** (detail in §15 and appendix 22A):

- **Internal reconciliation**, per currency per day: *what we owe customers* vs *what our own books say we hold*. Both sides come from the firm's own records.
- **External reconciliation**, per bank account per day: *what the bank says we hold* vs *what our ledger says we hold*. This is the only comparison against an independent source.

---

## 3. The ten things the application works with

| Term | What it is, in plain words | Example | Can it change? |
|---|---|---|---|
| **Reporting period** | One calendar month: the folder everything else hangs off. | `PER-2026-02` (February 2026) | Only its title can change. |
| **Source document** | One uploaded file (CSV or PDF), stored as an original with its SHA-256. It is identified as one of the 19 evidence types by its content. | `DOC-…`, e.g. `feb_bank_note.pdf`, identified as IN-16 | Never. A correction is a new document linked to the old one. |
| **Upload batch** | The set of files sent in one upload. It is validated together; the analyst decides on flagged files and confirms it. | `UPL-0b7922c00d0dff62a1c21db5` | Status moves forward only: VALIDATED → CONFIRMED → PROCESSING → PROCESSED / FAILED. |
| **Deterministic reconciliation (processing run)** | One run of the engine over the month's confirmed document set, started by the analyst as a background job. | `RUN-8e7a5a6c52acc33469fb177e` | No. A rerun is a new run. |
| **Reconciliation pack** (deterministic pack) | The engine's write-once output: every check result, every exception, the evidence and missing-evidence registers, and the source file hashes. It is *not* the final audit report. | `PACK-H202602-PER-2026-02-195df2e1f216` | Never. Its ID ends with its own content hash. |
| **Exception** | A problem the engine found. Results with the same root cause are grouped into one exception, which has a severity (Critical / High) and is always **OPEN / UNRESOLVED** in the pack. | `EXC-H202602-01`: missing bank evidence, SGA-EUR-01, 16 Feb | Never. Nothing in the application resolves it. |
| **Investigation** | One AI analysis of one exception. It reads source records through read-only tools and writes cited observations, hypotheses, gaps and next steps. Published write-once and registered. | `INV-EXC-H202602-01-6b1425b437f4` | Never. A rerun is a new investigation. |
| **Exception case** | The analyst's own working file for one exception: notes, cited evidence, gaps, observations, hypotheses and a human decision. Append-only. | `CASE-496bf488ed7e5dd54f32f134` | Entries are only added. The disposition (Unresolved / Explained by analyst / Escalated) is the analyst's record and **does not resolve the exception**. |
| **Closing summary** | One short AI-written summary of the month, generated during the final review from the pack and the selected investigations. It becomes section 16 of the report. | February's summary, `fbb6aae7…` | It is fixed into the preview and then into the final pack. |
| **Final audit pack** | The published report (JSON + HTML + PDF + manifest), assembled by deterministic code after a recorded GENERATE. Versioned across reassessments. | `FAP-H202602-PER-2026-02-v1-b8dd53bd2449` | Never. A new version (v2) supersedes, and keeps, the earlier one. |

Also used: **review session** (`RS-…`, the final-review workspace for one pack), **preview** (`PV-…`, the exact report that would be published, built from a fingerprinted snapshot), **decision** (`RD-…`, a recorded HOLD or GENERATE), **job** (`JOB-…`, a background task), and **AI authorisation** (`AIA-…`, Phase 8: the analyst's recorded consent before any paid AI call).

---

## 4. The full user journey

### 4.1 End-to-end business workflow diagram

```
 ANALYST                                   APPLICATION (what actually runs)                         RECORD CREATED
 ───────                                   ────────────────────────────────                         ──────────────
 1  Select a month / Add New Monthly Report ─► period row created (no data yet) ──────────────────► PER-YYYY-MM
 2  Upload files ──────────────────────────► every file stored as an original (SHA-256) FIRST,  ─► UPL-… + DOC-… ×n
                                             then identified by content (CSV header / PDF labels)
 3  (automatic) classify ──────────────────► evidence type IN-01..IN-19 or "Not identified"
 4  (automatic) validate ──────────────────► month-deciding dates, record counts, structure
 5  Review flagged files ──────────────────► Include / Exclude, comment required ───────────────► decision on DOC-…
 6  Confirm batch ─────────────────────────► batch fixed; "current document set" of the month ───► batch CONFIRMED
 7  Start processing ──────────────────────► background job: deterministic engine (36 checks) ──► RUN-… (job)
 8  (automatic) ───────────────────────────► write-once reconciliation pack, registered to month ► PACK-CASE-PER-…
 9  Inspect results (pack page) ───────────► read-only views of the pack
10  Read exceptions (workspace) ───────────► engine results + source records (no AI) + provenance
11  Open investigation case (optional) ────► append-only case file ─────────────────────────────► CASE-… + entries
12  Run investigation ─► AUTHORISE dialog ─► authorisation recorded BEFORE the job ─────────────► AIA-… (Phase 8)
                                             background job: hash checks → packet → OpenAI + tools
                                             → rule-based validation → atomic publish → registry ► INV-… (or _not_published)
13  Read findings and citations ───────────► investigation page / workspace tabs
14  Add supporting evidence / correction ──► new batch (steps 2–6) marked "received after publication"
15  Reassess (only if a final pack exists) ► engine reruns on uploads + hash-verified originals ─► new PACK-CASE + lineage
16  Open a new final review (explicit) ────► review session, default selections ──────────────────► RS-…
    Edit selections ───────────────────────► one eligible investigation per exception (or not investigated / excluded)
17  Generate closing summary and preview ─► AUTHORISE dialog → AIA-… → job: snapshot + fingerprint
                                             + ONE OpenAI call (closing summary) + full report preview ► PV-…
18  Read the preview (HTML / PDF / JSON)
19  HOLD (note required) ──────────────────► decision recorded; nothing published ───────────────► RD-… (HOLD)
    or GENERATE (tick acknowledgement) ────► re-check snapshot & inputs → deterministic assembly
                                             → HTML + PDF → manifest → ONE atomic folder rename ──► FAP-…-v<n>
20  (automatic) verify ────────────────────► hashes and re-render checked on every view
21  Retrieve versions ─────────────────────► Final pack page "Version history"; month page "Published audit packs"
```

### 4.2 Stage by stage: what triggers the next stage, and what must be true first

The rules below are the backend's. Each has an error code and a file:line in appendix 22E.

| # | Stage | Started by | Must be true before it can happen | What it produces / triggers next |
|---|---|---|---|---|
| 1 | Select or create a month | Top-bar **Period** selector, or **Add New Monthly Report** | Creating: year 2000–2100, month 1–12; not a future month; title 3–120 characters; the month must not already exist (one report per month). | Period row. The page goes straight to Upload for that month. |
| 2 | Upload | **Upload and validate** | At least one file; up to 60 per batch. For additional evidence or a correction: a reason of at least 3 characters. For a correction: exactly one file and the document it replaces. | Each file is stored as an original, then checked. The page opens the **batch**. |
| 3 | Classify | Automatic | — | Evidence type from the CSV header or the PDF's labelled key details. File names are not trusted. Unknown → `UNRECOGNISED` (ERROR). |
| 4 | Validate | Automatic | — | Status per file: VALID / WARNING / ERROR, with flags such as `WRONG_PERIOD`, `SAME_CONTENT_AS_OTHER_PERIOD`, `DUPLICATE_OF_EARLIER_UPLOAD` or `HEADER_ONLY_SAME_AS_OTHER_PERIOD` (INFO). Batch status: VALID / WARNINGS / INCOMPLETE / INVALID. |
| 5 | Review flagged files | **Checks → Include / Exclude** | A comment of at least 3 characters. A file with ERROR cannot be included. | Decision recorded on the document. |
| 6 | Confirm batch | **Confirm batch** | No flagged file still awaiting a decision; batch not INVALID. | Batch CONFIRMED; documents join the month's *current document set*. |
| 7 | Process | **Start processing** | Batch confirmed; every required evidence type (IN-01..IN-17) present in the month's document set; the month's policy (IN-17) applies to it (`processing_supported`). If the month already has a **published final pack**, a normal run is refused with `REASSESSMENT_REQUIRED`; use Reassess. | Background PROCESSING job → run SUCCEEDED / FAILED. |
| 8 | Pack | Automatic, at the end of the run | The engine finished. | A write-once pack in `packs/`, linked to the month (`audit.period_packs`). Identical inputs give the identical pack. |
| 9–10 | Inspect results and exceptions | Navigation | A pack exists. | Read-only. |
| 11 | Open a case | **Open investigation case** | One case per (pack, exception). | `CASE-…`. Entries are append-only; an Observation must cite evidence; a closed case accepts only a Decision. |
| 12 | AI investigation | **Run investigation**, then tick and **Authorise and run** | Provider configured; no other investigation of the same exception running; the dialog's provider and model still match the server's. | `AIA-…` recorded, then a job; a published `INV-…` or a rejected attempt in `_not_published`. |
| 13 | Read findings | Navigation | A published investigation. | — |
| 14 | Add supporting evidence / correction | **Add Supporting Document** on the month page | As in stage 2. | A new batch. If a final pack exists, the month shows **"Additional evidence received after publication — pending reassessment"**. |
| 15 | Reassess | **Reassess <Month>**, then reason and **Start reassessment** | A published final pack exists; new evidence was received after it, in a confirmed batch; the original source files still match their recorded SHA-256. | A new pack (`PACK-CASE-…`) linked to the reassessed pack, with "what changed". The published final pack is untouched. |
| 16 | Final review | **Open a new final review** (explicit) | No other active review for this pack. | `RS-…` with default selections. Visiting a review URL never creates one. |
| 17 | Preview | **Generate closing summary and preview**, then tick and **Authorise and generate** | Session editable (OPEN / ON_HOLD / GENERATION_FAILED); no blockers other than "preview required"; valid selections; no investigation running. | `AIA-…` recorded; a job builds the snapshot, the AI closing summary (or UNAVAILABLE) and the full preview. |
| 18 | Read the preview | HTML / PDF / JSON tabs | A current preview. | — |
| 19 | HOLD / GENERATE | **HOLD** then **SAVE HOLD**; or tick the acknowledgement, then **GENERATE** then **GENERATE PACK** | HOLD: a note. GENERATE: current preview; acknowledgement ticked (plus a second one if the summary is UNAVAILABLE); readiness has no blockers; snapshot and inputs unchanged since the preview (else `PREVIEW_STALE`). | HOLD: decision only. GENERATE: final pack v<n>. |
| 20 | Verify | Automatic, on every view of a final pack | — | Integrity status shown on the final-pack page. |
| 21 | Retrieve versions | Final pack → **Version history**; month page → **7. Published audit packs** | — | — |

---

## 5. The monthly reporting lifecycle

A month's **reporting status** (shown as a badge on the archive and the month page) is calculated by the backend from its records (`routers/monthly.py:150-158`):

```
NO_DATA ──upload──► DOCUMENTS_UPLOADED ──flagged files──► VALIDATION_REQUIRED
   │                        │ confirm + process
   │                        ▼
   │            DETERMINISTIC_PACK_AVAILABLE ──investigation published──► INVESTIGATION_AVAILABLE
   │                        │ GENERATE                                         │ GENERATE
   │                        ▼                                                  ▼
   │                  FINAL_PACK_PUBLISHED ◄────────────────────────────────────
   │                        │ new evidence uploaded after publication
   │                        ▼
   │            ADDITIONAL_EVIDENCE_RECEIVED  ──Reassess──► new pack (lineage) ──new review + GENERATE──► v2
   ▼
 (a month with no record at all is shown as "No data" / "Open for upload" for the current month)
```

Observed in the isolated environment:

- **October 2026** went from "No data" to an archive record with an INCOMPLETE batch.
- **March 2026** gained an uploaded batch and a second pack.
- **February 2026** showed "Additional evidence received after publication — pending reassessment", then a lineage row after reassessment.

**The top-bar period selector** lists every month from January 2026 to the current month (November 2026). November is "(open for upload)" and October is "(no data)". **Neither exists in the database** until someone creates it: live `uc042` has 9 period rows, January to September. The archive still lists them, with "—" for every column.

---

## 6. Screen-by-screen explanation

**What is on every screen.**

- **Left sidebar.** Two groups:
  - **WORKFLOW:** 01 Dashboard, R Monthly reports, 02 Reconciliation pack, 03 Exceptions & investigation, 04 Final review, 05 Final audit pack.
  - **RECORDS:** All reviews, All final packs, ↑ Upload documents.
  - **Behaviour:** the numbered items are *context links*, not steps the app tracks. They point to the pack, exception, review or final pack you last opened. With no pack open, 02 and 03 point to the selected month's report, or are greyed out ("select a month or open a pack first"). When a pack is open, a **CURRENT PACK** box shows its ID and month.
- **Top bar.**
  - The **Period** selector, January 2026 to the current month. Changing it moves the dashboard and month links to that month.
  - The **data environment label** (here "Data: PHASE 9 EXPLORATION…"), **Live backend**, **SYNTHETIC DATA**, and the analyst ID.
  - The analyst identity comes from **configuration** (`UC042_ANALYST_ID`). There is no login.
- **Breadcrumbs** show where you are.

For each screen below:

- **Reads** lists the API requests measured in the browser when the screen loaded.
- **Writes** says whether anything is created (database row, file, background job) or whether OpenAI is called.
- Screenshot names refer to `docs/audit_pack/22_screenshots/` (index in §21).

### 6.1 Dashboard (`/`), "Reconciliation overview"

- **Business purpose:** a one-page status of the selected month and of all months.
- **Who uses it:** the analyst at the start of a session; a manager checking progress.
- **Displayed** (S01, S01b, S01c, S01d):
  - **Header buttons:** "Upload documents for <month>" and "Open <month> packs".
  - **Five KPI tiles** for the selected month:
    - Reconciliation packs;
    - Exceptions (with the unresolved count);
    - AI investigations (eligible / published), with notes: exceptions covered, rejected attempts, excluded (unregistered / authorisation discrepancy);
    - Pending reviews (month · all periods);
    - Final audit packs (month · all periods).
  - **"Reconciliation periods"** table, one row per month: status, documents, validation, processing, packs, exceptions, unresolved, AI coverage (e.g. "1 / 1"), final pack ("1 generated").
  - **Below it**, the selected month's packs: pack type, ID, engine status, evidence, exceptions, unresolved, eligible AI.
  - **Panels:** "Recently generated audit packs", "Pending reviews", "Recent activity" (activity log, newest first, with readable labels and links).
- **Where the data comes from:**
  - `GET /dashboard?period_id=` (Phase 8: all counts computed by the backend);
  - `/periods`, `/packs`, `/final-packs`, `/reviews`, `/activity`.
  - The month defaults to the latest month with data (September). Clicking a row in the period table selects that month, and only `/dashboard` is requested again.
- **Buttons:** all are navigation. Clicking a pack row opens the pack page.
- **Writes:** none. **OpenAI:** no.
- **Observed:**
  - September shows "0 / 0 eligible of published · 1 rejected attempt · 7 excluded (unregistered 7)".
  - February shows "1 / 1 … 1 rejected attempt · 1 excluded (unregistered 1)".
  - "Pending reviews: all periods 1" is the review session `RS-fc0a6e7f8aa4512c18b9a891`, opened on 4 November during audit 19 and kept on purpose.

### 6.2 Monthly reports archive (`/reports`)

- **Purpose:** the list of all reporting months and their state; the way into each month.
- **Displayed** (S02–S02e):
  - The table columns: Month, Report title, Period ID, Documents, Packs ("9 demonstration scenarios", "1 historical monthly pack"), Exceptions, Investigations ("1 +1 excluded"), Final audit pack ("Published"), Status.
  - The data environment note: database name, packs root, storage profiles.
- **Controls:**
  - search (title or period ID);
  - filters for Year, Month, Reporting status (7 statuses) and Final audit pack (Any / Published / Not published);
  - Sort (newest / oldest).
  - Filters are kept in the URL (`?q=&status=&final=&sort=`) and work in the browser without new requests (S02b made no request).
  - "No reporting period matches" is shown when nothing matches (S02e).
- **Buttons:** **Add New Monthly Report** → screen 6.3. Clicking a row → the month's report.
- **Reads:** `/periods`, `/packs`, `/final-packs`. **Writes:** none.

### 6.3 Create Monthly Report (`/reports/new`)

- **Purpose:** create a reporting period before any upload.
- **Displayed** (S03, S03b, S03c, S03d):
  - **"1. Reporting period":** Month, Year and Report title (default "<Month> <Year> Reconciliation Audit"), plus the derived Period ID ("the immutable identifier used throughout the backend").
  - **"2. Check and create":** a live check against existing periods:
    - "February 2026 already exists … A second report is never created for the same month" (S03b);
    - "December 2026 has not started yet…" (S03c);
    - "October 2026 does not exist yet and can be created" (S03d).
- **Button: Create and continue to upload.**
  - Sends `POST /periods`, which creates the period row (database). No file, no job, no AI.
  - Then goes to `/upload?period=PER-2026-10&new=1`.
  - Observed: October 2026 was created this way in the isolated database.

### 6.4 Monthly Report workspace (`/reports/:periodId`)

- **Purpose:** the month's single "home": everything about one month on one long page.
- **Who uses it:** the analyst, throughout the month.
- **Displayed** (S04 February, S04b September, S04c June, S04d January, S04e March, S04f October, S04g November; S04h shows an invalid ID such as PER-2026-13, which reports "no report"):

  **Header:**
  - title, period, month dates, and the reporting-status badge;
  - **Add Supporting Document** (jumps to section 2) and **Upload documents** (→ Upload page).

  **Section index:** 1–8 plus "Reassessment" (in-page anchors).

  **1. Overview:**
  - KPI tiles: Month, Source documents (with batch count), Deterministic packs, Exceptions ("All unresolved"), Published audit packs.
  - "Report title: … · **Change title**": an inline edit (Save title / Cancel), `PATCH /periods/{id}`, database only (S04i).
  - The data environment note.

  **2. Source documents:**
  - Documents uploaded through the application, with batch, evidence type, validation, flags and decision.
  - The historical and September months show **0**: their packs were registered from dataset folders, not uploads (the page says so).
  - Contains the **Add Supporting Document** form (screen 6.13).

  **3. Reconciliation results:**
  - The month's deterministic packs: pack, type, engine status, evidence, exceptions, unresolved, with links **Workspace** and **Final review**.
  - September shows a notice that the 9 packs are "separate synthetic test scenarios, not separate months".

  **4. Exceptions:**
  - Every exception of every pack: ID (link to the workspace), pack, severity, category, account, status **UNRESOLVED**.
  - Notice: "exceptions are never resolved by this application".

  **5. AI investigations:**
  - Every published investigation artefact: mode, assessment, model and **review eligibility**.
  - Example: "Eligible (registered)", or "Not eligible: publication registry: not in the investigation publication registry (unregistered artefact)".

  **6. Closing summary:** the AI closing summary of the latest published final pack, read from its JSON, with the notice "not an audit opinion…".

  **7. Published audit packs:** final packs, newest first, with **JSON · HTML · PDF** download links.

  **Reassessment:** only shown when the month has a published final pack (screen 6.15).

  **8. Document history:** uploads, corrections, pack registrations and publications, newest first, plus the table of processing runs.

- **Reads:**
  - `/periods`, `/packs`, `/final-packs`, `/periods/{id}`;
  - `/periods/{id}/exception-overview` (one request for all packs of the month);
  - for a published month: `/final-packs/{id}/json`, `/periods/{id}/reassessment`, `/periods/{id}/lineage`.
- **Writes:** only through the title edit and the forms it contains.

### 6.5 Document upload (`/upload`)

- **Purpose:** send a month's financial files for identification and validation.
- **Displayed** (S05, S05b, S05c, S05e, S05f):
  - **Steps strip:** "1. Select month · 2. Add files · 3. Classify and validate · 4. Review summary · 5. Start processing".
  - **"1. Reconciliation month":** a month selector, labelled "(current month)" or "(has results)".
  - **"These documents are":** Source documents for the month / Additional evidence / Correction of an earlier document.
  - **"2. Files":** a drop zone, "Up to 19 evidence files: 14 CSV and 5 PDF (IN-18 and IN-19 optional)", the selected-file list with **Remove** and **Clear**.
  - **"3. Send for validation":** files selected, total size, and the **Upload and validate** button.
  - **Right side, "Expected documents":** the contract checklist IN-01..IN-19, grouped as reconciliation scope, client money, firm reconciliation records, bank evidence, firm ledger, settlement, governance. Each shows Missing / Present / Not provided.
- **Upload and validate:**
  - Sends `POST /periods/{id}/uploads` (multipart).
  - **Writes:** every file stored as an original in the document store (content-addressed by SHA-256), then rows for the batch and its documents.
  - Synchronous: no background job and no AI.
  - Then opens the batch page.

### 6.6 Upload batch and validation (`/uploads/:batchId`)

- **Purpose:** show what each file was identified as and what is wrong with it; record decisions; confirm.
- **Displayed** (S06, S06b October; S06c, S06d, S06e, S06f March; S13b, S13c February; S14b March correction):
  - **Header:** batch ID, uploaded by and when, **validation** (VALID / WARNINGS / INCOMPLETE / INVALID), **status** (VALIDATED / CONFIRMED / PROCESSED…).
  - **"Batch summary":**
    - counts of Valid / Warnings / Errors;
    - "Missing required evidence (period document set)" with the full IN-list;
    - "Optional evidence not supplied".
  - **"How documents were checked":**
    - identified by content;
    - dates judged on the field that decides the month;
    - duplicates flagged, never removed;
    - PDFs stored as originals, not read by the AI.
  - **"Documents" table:** file, size, submission kind; evidence ID and category; format; records; deciding dates; validation; flags; decision.
  - **Checks:** expands one file to show:
    - each message (e.g. `WRONG_PERIOD` "the calendar is for PER-2026-03, not PER-2026-10");
    - the period basis table (field, date type, decides the month, range, outside month, invalid, missing);
    - the SHA-256, "identified by CSV header", and **Download the stored original**;
    - the **Decision comment** with **Include / Exclude**.
  - **"Processing runs"** table.
- **Observed:**
  - **October**, files from March: calendar ERROR `WRONG_PERIOD`; account inventory VALID; `notes.txt` and `unknown_file.csv` ERROR `UNRECOGNISED`.
  - **March:** 16 VALID and 1 WARNING `SAME_CONTENT_AS_OTHER_PERIOD`. The same calendar file had just been put in October. A decision was required.
  - **March correction:** `DUPLICATE_OF_EARLIER_UPLOAD`, with "Correction of DOC-…".
- **Buttons:**
  - **Include / Exclude** sends `POST /documents/{id}/review`: a database row (decision + comment). Include is disabled for ERROR files.
  - **Confirm batch** sends `POST /uploads/{id}/confirm`: database only. It is disabled while any flagged file awaits a decision.
  - **Start processing / Start a new processing run** sends `POST /uploads/{id}/process`.
    - It creates a **background job** (PROCESSING) that runs the deterministic engine.
    - It **writes files**: the case folder in the document store and the new pack in `packs/`.
    - It writes rows: run, period-pack link, activity.
    - **No AI.**
    - The page polls `GET /jobs/{id}`. March finished in about 5 seconds: run `RUN-8e7a5a6c…` SUCCEEDED → `PACK-CASE-PER-2026-03-f91f3d2d6e6c`, "PUBLISHED · 3 exception(s)".
  - When the month already has a published final pack, **Start processing** is replaced by the notice "This month has a published final audit pack … assessed explicitly". The month page's Reassess is used instead.

### 6.7 Reconciliation results: the pack page (`/packs/:packId`)

- **Purpose:** read the engine's result for one pack.
- **Displayed** (S07, S07b, S07c, S07d):
  - **Header:** "HISTORICAL MONTHLY DETERMINISTIC PACK · FEBRUARY 2026 · IMMUTABLE", plus **Investigate exceptions** and **Open final review**.
  - **KPI tiles:**
    - reconciliation period;
    - currencies (EUR, GBP) and accounts (4);
    - engine status "EVIDENCE INCOMPLETE", with "Controls: INSUFFICIENT_EVIDENCE 15 · NOT_APPLICABLE 83 · PASS 1690";
    - evidence INCOMPLETE ("1 missing item");
    - exceptions;
    - pack content hash "195df2e1f216149c — verified on load".
  - **"Currencies and accounts":** class, currency and bank balance on the last external reconciliation day ("not reconciled externally" for own-funds accounts).
  - **"Source document inventory":** the 17 files the engine read, with category, records, status (PRESENT required) and SHA-256.
  - **"Reconciliation results"** with three tabs:
    - **External reconciliation** (ledger vs bank, per account and day);
    - **Internal reconciliation** (requirement vs resource, per currency and day);
    - **Reconciliation differences**. For S05 this shows "External (ledger vs bank) · 18 Sept 2026 · SGA-GBP-01 · −£812.40 · FAIL · NOT EVIDENCED" for each day 17–30 Sep.
  - **"Exception register"**, with the AI investigation status per exception.
- **Reads:** `/packs/{id}` and its `/reconciliation`, `/sources`, `/exceptions` and `/investigations`.
- **Writes:** none. The tabs switch without new requests.

### 6.8 Exception workspace (`/packs/:packId/workspace/:exceptionId`)

- **Purpose:** the analyst's main working screen for one exception.
- **Layout:** three columns at desktop width.
  - **Left:** the exception list. Each item shows ID, amount, date, severity, UNRESOLVED, and an AI badge: Not run / AI eligible / AI ineligible / Running.
  - **Centre:**
    1. **KPI tiles:** Amount (— for February, since a missing statement has no amount), Exception date, Severity, Evidence status, Deterministic status (OPEN + UNRESOLVED, "awaiting human review").
    2. **"Deterministic reconciliation results":** the engine results behind this exception, copied from the pack's control register (15 for February).
    3. **"Supporting evidence · engine retrieval (no AI)":** the source records retrieved deterministically from the pack's hash-verified files, grouped by source (bank records, cash-book entries, settlement records, client transactions, reconciliation records, other). Each record shows date, description, file:line, D/C and amount, with the badge **Engine**.
    4. **"Records retrieved by the AI investigation's tool calls":** further records the selected investigation fetched (badge **AI tool**), "evidence the AI looked at, not AI findings".
    5. **"Evidence relationships":** verified join keys (e.g. `C14-COVER|IN-07 2026-02-16/SGA-EUR-01` → `IN-01:2026-02-16`, join key `calendar_date=2026-02-16`).
  - **Right:**
    - the **Investigation case** panel (screen 6.9);
    - the **AI investigation** panel ("V2 tools mode · reads cited records only · never changes the exception status"), with **Run investigation**, a link "Open the full investigation record", the **Investigation record** selector (published investigations marked eligible / ineligible), "1 failed or rejected attempt(s) were kept…";
    - tabs **Summary / Observations (7) / Hypotheses (1) / Gaps & conflicts (1) / Next steps (3)** for February.
- **Displayed** (S08, the four S08 tab shots, S08b unregistered investigation, S08c and S08d September S05).
- **Clicking a record** opens the **provenance inspector** (screen 6.12).
- **Reads:**
  - `/packs/{id}/exceptions`, `/exceptions/{exc}`;
  - `/exceptions/{exc}/source-evidence` (no AI; Phase 8);
  - `/packs/{id}/investigations`;
  - `/investigations/{inv}`, `/findings`, `/evidence`;
  - `/cases?pack_id=`.
- **Buttons:**
  - **← Reconciliation pack** and **Continue to final review**: navigation. The latter goes to `/packs/{id}/review`, which never creates a review (screen 6.16).
  - **Run investigation** opens the authorisation dialog (screen 6.10).
- **Writes:** none on this screen except through the dialog and the case panel.

### 6.9 Exception case management (case panel → `/cases/:caseId`)

- **Purpose:** the analyst's own, permanent record of working on one exception.
- **On the workspace:**
  - **Open investigation case** sends `POST /packs/{p}/exceptions/{e}/case`: a database row and an activity entry. It then opens the case page.
  - If a case exists, its ID, status and disposition are shown instead.
- **Case page** (S09, S09b, S09c, S09d):
  - **Header:** case ID, exception, pack, case status (OPEN / CLOSED), disposition.
  - **Blue notice:** "A case records your investigation; it resolves nothing by itself … the exception stays UNRESOLVED there".
  - **Left column:**
    - "The exception as recorded in the pack" (read-only);
    - **"Case history"**: append-only, oldest first;
    - **"Supporting financial records"**: the same no-AI retrieval as the workspace, with tick-boxes to cite records.
  - **Right column:**
    - **"Add an entry":** Entry kind (Note / Supporting evidence / Evidence gap / Confirmed observation / Hypothesis / Human decision), Text, cited records, "Other references (uploaded document IDs, investigation IDs)". For a decision: **Disposition** (Unresolved / Explained by analyst / Escalated), "Close the case with this decision", and the warning that the disposition is a record only.
    - **"AI assistance":** **Request an AI investigation** opens the same authorisation dialog.
    - **"Investigation history":** the published investigations of this exception, with eligibility.
- **Add entry:**
  - Sends `POST /cases/{id}/entries` with the case revision, so a concurrent edit is refused. It writes a database row only.
  - **Observed rules:**
    - an Observation without a citation was refused: "a observation entry must cite at least one evidence reference" (S09b);
    - Supporting evidence also needs a citation;
    - a closed case accepts only a Decision (which can reopen it).
  - Six entries were added in the isolated case `CASE-496bf488ed7e5dd54f32f134`; the disposition became **Escalated**.
- **OpenAI:** only via Request an AI investigation, after authorisation. This was cancelled here (S10b).

### 6.10 Investigation confirmation: the AI authorisation dialog

- **Purpose (Phase 8):** nothing that may cost money or call the AI runs without the analyst's explicit, recorded consent.
- **Where:**
  - **Run investigation** (workspace);
  - **Request an AI investigation** (case);
  - **Generate closing summary and preview** / **Regenerate preview** (final review; title "Authorise the AI closing summary", screen 6.17).
- **Displayed** (S10 isolated, provider not configured; S10b from a case; S10c mock mode, provider configured):
  - **Context:** reporting period and title; deterministic pack; exception · category · account · amount (e.g. "EXC-S05-01 · Unexplained bank-ledger difference · SGA-GBP-01 · -812.40 GBP").
  - **Provider and model:** "openai · gpt-6-luna"; "Provider configured: Yes / No".
  - **"Live API calls may incur charges".**
  - **The rules:** approved evidence sources only; never answer keys; limits "8 tool calls, 4 rounds, 300 s"; "It cannot resolve the exception, change the deterministic results or approve the audit".
  - **A required tick-box** with the exact statement that is recorded.
  - "The authorisation is recorded (provider, model, analyst, time) before anything is run, and stays linked to the job."
  - When the provider is not configured, a red notice appears and **Authorise and run** stays disabled.
- **Cancel:** sends nothing. Verified: only `GET /ai/configuration` was requested, and no authorisation row exists.
- **Authorise and run:** sends `POST /packs/{p}/exceptions/{e}/investigations` with `{confirmed, provider, model}`.
  - The backend **first records** an `AIA-…` row (append-only; a database trigger refuses changes), **then** starts the background job, which **calls OpenAI**.
  - Some refusals are recorded too: provider not configured, another run active, configuration changed. A missing tick, an unknown pack and an invalid retry are not recorded.
  - Not executed in this exploration.

### 6.11 Investigation details (`/investigations/:investigationId`)

- **Purpose:** the full, read-only record of one AI investigation.
- **Displayed** (S11 February; S11b–S11d tabs; S11e June; S11f September S05):
  - **Header:** "AI INVESTIGATION · AN AID TO HUMAN REVIEW; IT RESOLVES NOTHING"; mode; investigated at; validation VALID; eligibility.
  - **"Record":**
    - exception and deterministic pack; status COMPLETED;
    - exception resolution **NOT_RESOLVED_BY_INVESTIGATION**;
    - model "openai gpt-6-luna";
    - prompt / schema "uc042-investigator-prompt/2.2-tools · uc042-investigation-findings/1.4";
    - publication registry "new publication (seq 1)";
    - authorisation decision **APPROVED**;
    - findings SHA-256.
  - **"Eligibility"** ("From the publication registry, the authorisation decisions and the current validation rules"): "Eligible: it can be selected in a final review", or the reasons it cannot. June: "authorisation: AUTHORIZATION_DISCREPANCY - not in the approved published set (Business owner decision 2026-11-04…)".
  - **Tabs:**
    - **Findings:** the assessment "INSUFFICIENT EVIDENCE" ("AI INTERPRETATION, NOT FACT"); 7 confirmed findings, each with relevance, *establishes*, *does not establish*, and cited evidence; the hypothesis; gaps; next steps.
    - **Evidence:** 29 records.
    - **Tool calls:** 8, listing tool, arguments, status, records and evidence IDs, e.g. "4 · r1 search_bank_entries {account SGA-EUR-01, reference E2E-EUR-0216-L01} NOT FOUND SEARCH-08".
    - **Validation and publication.**
- **Reads:**
  - `/investigations/{id}`, `/findings`, `/evidence`, `/tool-calls`;
  - `/investigations/{id}/verify`, which re-checks the artefact's hashes on every view.
- **Writes:** none.

### 6.12 Source evidence and provenance (inspector in the workspace)

- **Purpose:** prove where any figure came from.
- **Displayed** (S12): clicking any record row opens an inspector with:
  - **origin:** "Engine retrieval (no AI)" or "Retrieved by an AI tool call";
  - **retrieved via:** e.g. "cited by control result …", or "tool get_settlement_batch: settlement lines of the batch";
  - the source file, the line number and the **file SHA-256**;
  - all the record's fields;
  - the control results and relationships that involve it.
  - **Close** hides it.
- **Where it comes from:** the deterministic retrieval re-hashes every source file of the pack against the hashes recorded when the pack was built, and refuses to read a changed file. **No AI** is involved in engine records.

### 6.13 Supporting document upload ("Add Supporting Document", month page section 2)

- **Purpose:** add evidence to an existing month without touching anything already produced.
- **Displayed** (S13):
  - **Type:** Additional evidence / Correction.
  - **Reason for adding** (required), a drop zone, the file list.
  - When the month has a final pack: "New documents are recorded as received after publication; the published pack is not changed and will show as pending reassessment".
- **Upload and validate:** the same `POST /periods/{id}/uploads`, with `submission_kind` and reason. It writes originals and rows and opens the batch page.
- **Observed:** `feb_bank_note.pdf` was identified as **IN-16** (acknowledgement letter, SGA-EUR-01), VALID. After **Confirm batch**, the February page showed the amber banner "Additional evidence received after publication — pending reassessment" (S15).

### 6.14 Document correction (same form, Type = Correction)

- **Displayed** (S04j, S14):
  - **Replaces** selector: the month's uploaded documents, as "file · evidence type · DOC-ID". Only one file is allowed.
  - "There is no earlier document in this month to correct" if none exist: true for every historical month, whose originals were never uploaded.
- **Result:** a new document with `replaces_document_id`; the earlier one is kept ("Correction of DOC-5189288c8af25ee87616cfdc"). In the test it was flagged `DUPLICATE_OF_EARLIER_UPLOAD`, because the same bytes were re-sent.

### 6.15 Reassessment (month page, "Reassessment" panel)

- **Purpose:** process new evidence for a month whose final pack is already published, without changing anything published.
- **Displayed** (S15, S15b, S15c, S15d):
  - Previous published result (FAP v1); pack being reassessed.
  - **Original source documents:** "17 file(s) … verified against their recorded SHA-256 (historical-demo storage)".
  - **Document set:** "1 type(s) from uploads, 16 from the verified originals · Uploaded documents supersede the originals for: IN-16".
  - **"Evidence received after publication"** list.
  - Blockers, e.g. "no evidence was received after the latest final audit pack", "confirm the batch holding the new evidence first".
  - **Reassess <Month>** button.
  - **"Pack lineage"** table: reassessed pack, reassesses, what changed, reason, recorded.
- **Reassess → dialog → Start reassessment** (reason required):
  - Sends `POST /periods/{id}/reconciliation` with purpose REASSESSMENT.
  - Starts a **background job**: the engine reruns on the uploads plus the hash-verified originals.
  - It **writes a new pack** to `packs/` and records `audit.pack_lineage`. **No AI.**
- **Observed:**
  - Completed within seconds: "New deterministic pack PACK-CASE-PER-2026-02-19fbd4d1c1ce (1 exception(s)). Go to its final review…".
  - Lineage row: "Inputs changed: none · Exceptions 1 → 1 · Engine status EVIDENCE_INCOMPLETE → EVIDENCE_INCOMPLETE".
  - The added PDF could not change the result, because the engine reads only the labelled key details of IN-16 (the account designation letter), not bank balances (see §17).

### 6.16 Final review (`/packs/:packId/review` → `/reviews/:reviewId`)

- **Purpose:** the gate between investigation and publication.
- **`/packs/{id}/review` is read-only** (Phase 8):
  - If the pack has an active review, it **navigates to it** (S16: February's OPEN session `RS-fc0a…`).
  - Otherwise it shows "This pack has no active review. Opening one is an explicit action; reading this page changes nothing", earlier reviews, and **Open a new final review** (S16f, S16g).
  - For a pack with a published lineage, it says the next review "can publish the next version, v2".
- **Open a new final review:** `POST /packs/{id}/reviews`, a database row (S16h, isolated).
- **Review page layout:**
  - **Left:** "Contents · 16 sections" (jump links).
  - **Centre:** the document viewer, with format tabs **HTML / PDF / JSON** and the preview, or "Preview required" with **Generate closing summary and preview**.
  - **Right:**
    - **"Pack summary":** source pack, review status, closing summary status;
    - **"Readiness":** blockers in red, warnings in amber, info in blue, or "Ready for a decision.", plus **Regenerate preview**;
    - **"Investigation selections"** with **Edit**;
    - **"Human review"**: reviewer note, the acknowledgement tick-box, **HOLD** and **GENERATE**;
    - **"Decision history"**.
- **Observed readiness on February's open review:**
  - "PREVIEW REQUIRED: generate a preview (with the closing summary) before deciding";
  - "a final pack already exists for this reporting-period lineage; a new one will be version 2, superseding FAP-…-v1";
  - "1 exception(s) are unresolved and will appear as UNRESOLVED".
- **Edit → "Investigation selections" dialog** (S16b): per exception, choose Include investigation (and which one; ineligible ones are greyed out) / Not investigated / Exclude (reason required). **Save selections** (`PATCH /reviews/{id}/selections`) "invalidates the current closing summary and preview". Cancelled here.
- **A generated review** (S16c–S16e: February `RS-898ce…`, GENERATED) shows the green notice "Final audit pack generated … Open FAP-…" and the stored preview in HTML, JSON or PDF. The PDF is blank in a headless browser only; Phase 8 confirmed it displays in a normal Edge window.

### 6.17 Closing-summary confirmation (S17)

- **Same dialog**, titled "Authorise the AI closing summary".
- **Context:** period, pack, **Selected investigations** (or "None (every exception reported as not investigated or excluded)"), review.
- **Statement:** "I authorise one AI closing-summary request for this final review…".
- **Without a provider:** "No model is called: the preview is built with the closing summary UNAVAILABLE, and GENERATE then needs a second acknowledgement". Unlike the investigation dialog, the button is **not** blocked in this case.
- **Authorise and generate:**
  - Sends `POST /reviews/{id}/preview` with the authorisation.
  - It records `AIA-…`, then starts a **background job**. The job:
    - builds the snapshot and fingerprint;
    - makes **one OpenAI call** for the closing summary;
    - assembles the full preview (JSON + HTML + PDF) and stores it (database, `audit.previews`).
  - Cancelled here; no preview was created.

### 6.18 HOLD and GENERATE confirmation dialogs (S18)

- **HOLD:**
  - Opens "Save decision: HOLD": "The review and your note are saved. **No final audit pack is generated.** You can return, regenerate the preview and decide later."
  - "Reason for hold (required)".
  - **SAVE HOLD** sends `POST /reviews/{id}/decision` with HOLD: a database row; the session becomes ON_HOLD and the preview no longer applies.
  - Cancelled here.
- **GENERATE:**
  - The button is **disabled** until there is a current preview, the acknowledgement is ticked (plus "The AI closing summary is unavailable…" if applicable) and readiness has no blockers. Verified: `GENERATE disabled=true` with no preview.
  - Its dialog, "Authorise final audit-pack assembly", names the snapshot hash and the pack, and states that GENERATE "does **not** resolve exceptions, confirm hypotheses, certify a clean reconciliation or establish compliance".
  - **GENERATE PACK** sends `POST /reviews/{id}/decision` with GENERATE. It runs **inside the request** (not a background job) and makes no AI call:
    - re-checks the snapshot and inputs;
    - assembles the final pack;
    - renders HTML and PDF;
    - publishes the folder;
    - records the decision and the final-pack row.
  - Not executed.

### 6.19 All Reviews (`/reviews`, S19)

- A table of every review session: review, pack, status, preview (Current / None), last decision, final pack, updated.
- Live and isolated each contain February's GENERATED session (`RS-898ce…` → FAP v1) and the OPEN session `RS-fc0a…`.
- Read-only; `GET /reviews`.

### 6.20 All Final Packs (`/final-packs`, S20)

- "Immutable packs, each created by a recorded GENERATE decision in a final review".
- Columns: final pack, source pack, version, supersedes, generated, content hash.
- One row: February v1.

### 6.21 Published Final Audit Pack (`/final-packs/:finalPackId`, S21, S21b–S21d)

- **Header:** "FINAL AUDIT PACK · IMMUTABLE", the ID, v1, **✓ Integrity verified** ("Manifest hashes, the content hash and both renderings (HTML, PDF) match the canonical JSON").
- **"Pack record":**
  - ID, version, original deterministic pack and its hash;
  - investigation references ("INV-EXC-H202602-01-6b1425b437f4 → EXC-H202602-01 (included)");
  - generation time;
  - **Authorised by (GENERATE)** "Demonstration Reviewer (synthetic) (demo-reviewer)", with the reviewer's note;
  - unresolved exceptions "1 carried in the pack as UNRESOLVED".
- **"Artefacts":** PDF 77 KB, HTML 109 KB, JSON 190 KB, each with its SHA-256 and **Open · Download**.
- **Tabs:**
  - **PDF preview**, with the fallback "Open the PDF in a new tab" / "Download PDF";
  - **HTML report**, the 16-section report;
  - **Canonical JSON**;
  - **Version history** (1).
- **Reads:** `/final-packs/{id}`, `/json`, `/pdf`, `/html`, and `/verify` (integrity re-checked on every view).
- **Writes:** none.

### 6.22 Document history and activity

- **Month page section 8 "Document history"** (read-only): a merged timeline per month of upload batches (with submission kind and status), corrections ("Correction DOC-… replaces DOC-…; the earlier version is kept"), pack registrations and final-pack publications, plus the processing-run table.
- **Dashboard "Recent activity":** the global activity log (`GET /activity`), with readable labels. Examples: "Monthly report created", "Upload batch confirmed", "Reassessment started", "Reassessed pack linked to the pack it reassesses", "AI operation authorised", "Final review opened", "Investigation case opened". Each shows actor, time and link.
- After this exploration the isolated dashboard showed the test actions (S22).

---

## 7. Upload and document-management workflow

1. **Store first, check second.** Every uploaded file is written to the document store under its SHA-256 *before* any check. A rejected file is therefore never lost. The bytes are never overwritten: identical content is stored once.
2. **Identify by content.**
   - A CSV is matched by its exact header row to one of IN-01..IN-14.
   - A PDF is matched by its labelled key details (e.g. "Account number:", "Effective date:") to IN-15..IN-19.
   - **File names are not trusted.** Unknown content is `UNRECOGNISED`, file format OTHER (e.g. `notes.txt`).
3. **Decide the month from the right date.** Each evidence type has one field that decides the month (e.g. calendar date, recon date, booking date).
   - Rows outside the month are counted.
   - A file with **no** rows in the month is `WRONG_PERIOD` (ERROR).
   - Other dates are reported as timing differences.
   - **Records are never moved between months.**
4. **Flag duplicates, never remove them:**
   - same content already uploaded to this or another month (`SAME_CONTENT_AS_OTHER_PERIOD`, `DUPLICATE_OF_EARLIER_UPLOAD`);
   - same name with different content;
   - repeated record IDs;
   - header-only files identical to another month's (`HEADER_ONLY_SAME_AS_OTHER_PERIOD`, INFO only; Phase 8).
5. **The analyst decides on every flagged file** (Include / Exclude, with a comment). Errors cannot be included.
6. **Confirm the batch.** The month's **current document set** is then, for each evidence type, the latest included document across confirmed batches. A correction replaces its predecessor in the set; the predecessor is kept.
7. **Submission kinds.**
   - INITIAL: the month's sources.
   - ADDITIONAL_EVIDENCE: added later, with a reason.
   - CORRECTION: replaces one earlier document, with a reason.
   - After a final pack is published, any new document is counted as **received after publication**, and the month is marked pending reassessment.
8. **What is not uploaded.** The January–August and September documents were **never uploaded**. They were registered from their dataset folders, which is why "Source documents" is 0 for every preloaded month. Their files and hashes appear in each pack's **source document inventory**. September's 9 scenarios also have read-only "POC scenario documents registered" batches. Those batches are never processed.

---

## 8. Reconciliation and exception lifecycle

1. **Start.** The analyst presses **Start processing**, which creates a PROCESSING job.
2. **Materialise the document set.** The job copies the confirmed document set into a case folder in the document store. For a reassessment, it also copies the original sources, re-verified against their recorded SHA-256.
3. **Run the engine** (`uc042lib/validate.py`), configured for that month (calendar, policy, bank holidays). It runs **36 checks** in a fixed order (§15). Each check produces results:
   - PASS;
   - FAIL;
   - INSUFFICIENT_EVIDENCE ("could not be assessed": *never* treated as zero);
   - NOT_APPLICABLE.
4. **Group failures into exceptions.** Every FAIL or INSUFFICIENT_EVIDENCE has a **root cause**. All results with the same root cause become **one exception**. Severity:
   - **Critical** for missing bank evidence, a bank-ledger difference, an internal difference, missing reconciliations and file problems;
   - otherwise **High**.
   - Every exception starts **OPEN / AWAITING_HUMAN_REVIEW** and stays that way in the pack.
5. **Correlate exceptions** into investigation groups by shared reference, recurrence or lineage. This never changes an exception.
6. **Write the pack.** It contains the control register, exception register, evidence register, missing-evidence register and the source-file hashes. The pack's ID ends with its content hash. It is written once to `packs/`; identical inputs give the identical pack.
7. **Link the pack to the month** (`audit.period_packs`). The run is SUCCEEDED.
8. **Afterwards.** The exception is read by the analyst, documented in a case, investigated by the AI if authorised, selected in a final review, and **carried into the final pack as UNRESOLVED**.
   - Nothing in the system ever closes an exception.
   - A case disposition ("Explained by analyst", "Escalated") is the analyst's own record, held outside the pack.
   - A reassessment produces a **new** pack, whose exceptions may differ.

**Engine case status** for a pack:

- **CLEAN**: no exceptions.
- **EXCEPTIONS_OPEN**: evidence complete, but exceptions exist.
- **EVIDENCE_INCOMPLETE**: at least one result could not be assessed.

---

## 9. Exception case-management workflow

The case is the analyst's structured notebook. All rules are enforced by the backend (`uc042app/services/cases.py`); the observed behaviour is in §6.9.

| Entry kind | Meaning | Rule |
|---|---|---|
| Note | Working note | text ≥ 3 characters |
| Supporting evidence | Evidence that supports the analysis | must cite ≥ 1 record, uploaded document (`DOC-…`) or published investigation (`INV-…`) |
| Evidence gap | Evidence that is missing | — |
| Confirmed observation | A fact the evidence shows | **must cite evidence** (refusal observed) |
| Hypothesis | A possible explanation, not established | — |
| Human decision | Sets the disposition: Unresolved / Explained by analyst / Escalated; may close or reopen the case | the only kind allowed on a closed case |
| AI investigation requested | Written by the system when the analyst requests AI from the case | via the authorisation dialog |

Every entry is append-only and is stamped with the analyst and time. Each save carries the case's revision number, so two people cannot silently overwrite each other. A case **never** changes the pack, the exception or a published final pack. In the current code, case entries are **not** included in the final audit pack (see §17).

---

## 10. AI investigation architecture

This is a summary. The full trace of February's real investigation, with file:line references and quotes from the artefacts, is in **appendix 22B**.

**Plain-language flow (February, `INV-EXC-H202602-01-6b1425b437f4`):**

1. **Selection and authorisation.** The analyst opens EXC-H202602-01 and authorises one investigation. Phase 8 records the authorisation first. February predates Phase 8: its authorisation is the recorded business-owner approval in `audit.investigation_authorizations`.
2. **Integrity first, no AI.** The background job:
   - re-checks the pack's own hash (`195df2e1f216…`);
   - **re-hashes all 17 source files** against the hashes recorded when the pack was built. If any file has changed, the investigation fails before any AI call.
3. **Deterministic routing.** The root cause `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16` selects the route `missing_bank_evidence`.
4. **Deterministic retrieval.** It fetches:
   - every record the engine's results cite;
   - the firm's external reconciliation record for that day;
   - **probes** for the missing items: the 17:00 confirmation, the statement and the bank entries for 16 Feb (SEARCH-01..03, all NOT_FOUND);
   - the adjacent-day statements as "context only; not a substitute".
   - It works only through verified join keys: **no amount matching, no fuzzy matching**.
5. **Evidence packet.** The result is 16 records, 3 searches, 1 missing item (MISS-01) and 36 citable IDs, with the packet's own hash `760adfe5…`. Answer keys, scenario notes and verification folders are refused by path rules.
6. **The model call.**
   - OpenAI's Responses API, model `gpt-6-luna` (reasoning effort `medium`).
   - It receives a system prompt with strict rules: engine outcomes are authoritative; missing ≠ zero; causes only as hypotheses; never resolve.
   - It also receives the whole packet as untrusted data, and a strict output schema.
   - `store=False`: OpenAI keeps no application state.
7. **Tools mode.** The model may call **8 read-only tools**:
   - `get_source_record`, `search_bank_entries`, `get_cashbook_entries`, `get_settlement_batch`;
   - `search_customer_transactions`, `get_customer_balance_snapshots`, `get_reconciliation_evidence`, `follow_relationship`.
   - **Limits:** 8 calls, 4 rounds, 25 records per call, 160 records in total, a 150k-token estimate and 300 s.
   - **February:** 8 parallel calls in one round. Both settlement batches; the internal and external reconciliation records; five bank-reference searches, all NOT_FOUND.
   - Python executes each call against the same hash-verified files. Every returned row joins the **evidence ledger** with its provenance: 29 records, 12 searches, 58 citable IDs.
8. **Final answer.** The second model call returned the structured answer: 7 confirmed findings, 1 hypothesis, 1 evidence gap (covering MISS-01 and the 10 NOT_FOUND searches), 3 next steps, and the assessment **INSUFFICIENT_EVIDENCE**.
9. **Validation by fixed rules** (no AI):
   - every cited ID must be in the ledger;
   - a finding must cite real evidence;
   - no cause words in findings;
   - no "resolved / compliant";
   - no "does not exist" (only "not found in the supplied data");
   - missing evidence must be preserved;
   - `EVIDENCE_SUFFICIENT` is forbidden while anything is missing;
   - `ZERO_PATTERN` blocks a balance stated as 0 while evidence is missing.
   - **February's first attempt was rejected** by `ZERO_PATTERN`: it quoted "a reported difference of 0.00". Report 17 judged this a false positive and deliberately left the rule unchanged. The attempt is kept in `_not_published/`. The retry passed.
10. **Publication.** The folder is written to a temporary directory and moved into place with **one atomic rename**. Its ID is a **content address** (a hash over findings and packet), so a rerun can never overwrite it. Files: `findings.json`, `evidence_packet.json`, `evidence_ledger.json`, `tool_calls.json`, `runs/0001.json`.
11. **Registry.** The backend adds it to the **publication registry** (seq 1), pinning the hashes of every file. A rewritten artefact would no longer match.
12. **Eligibility** for a final review is recalculated every time. All four must hold:
    - the artefact verifies;
    - it is registered with the same hashes;
    - no AUTHORIZATION_DISCREPANCY decision is recorded against it;
    - it passes today's validation rules.

**Confirmed finding vs hypothesis.**

- **A confirmed finding** (F-nn) states only what cited records show. Each has *establishes* and *does not establish*. Example, F-05 "Cash-book entries lack matching bank evidence": it establishes that the five cash-book entries exist and that the bank searches returned NOT_FOUND. It does not establish that money reached or left the bank.
- **A hypothesis** (H-nn, always status HYPOTHESIS) is a possible explanation with its limitations. February's H-01 says bank activity may have occurred but the statement is absent.
- The UI keeps them in separate tabs, with the notice "Hypotheses are possible explanations the evidence does not establish."

**Why "tools mode" and not one prompt.** A one-shot call would give the model a fixed packet and accept whatever it says about it. In tools mode:

- the model can *ask for more evidence*, but only through narrow, read-only, typed queries that Python runs against hash-verified files;
- every answer is recorded with its provenance and becomes citable;
- negative lookups become citable "not found" evidence;
- the budget is bounded.

The code also contains a fixed (non-tools) mode, used by the command-line tool. The application's API accepts only `mode: "tools"`.

**The other February folder and the attempts.**

- `INV-EXC-H202602-01-a3fd3fd2e9ed` is the earlier command-line run (report 16). It is valid but was never registered, so it is "Not eligible: … unregistered artefact".
- `_not_published/…c392e113.json` is the rejected first app attempt.

---

## 11. Closing summary and final-pack workflow

This is a summary; the full trace is in **appendix 22C**.

1. **Review session (explicit).** One active session per pack. Default selections are made per exception: an eligible investigation if one exists, otherwise "not investigated".
2. **Selections.** Each exception is set to **INCLUDED** (exactly one eligible investigation), **NOT_INVESTIGATED**, or **EXCLUDED_BY_ANALYST** (reason required). Saving invalidates any preview.
3. **Readiness** is recalculated on every view.
   - **Blockers:** investigation running, ineligible selection, "not investigated" although an eligible investigation exists, preview in progress, preview required.
   - **Warnings:** not investigated, closing summary unavailable, final pack exists (lineage-aware: "a new one will be version 2…").
   - **Info:** unresolved exceptions.
4. **Snapshot and fingerprint.** The preview job freezes the exact inputs: the pack hash, each selection, each investigation's pinned hashes, and the rules versions. It hashes them into a **snapshot SHA-256**; an inputs fingerprint is recorded with it.
5. **Closing summary**, the only AI step in this workflow.
   - **One** OpenAI call. Its input is a fingerprinted digest of the pack and the *selected* investigations only.
   - It must return a strict schema and pass rule checks: only known IDs; nothing "resolved", "compliant" or causal.
   - If the provider is unavailable or the output fails the checks, the summary is recorded as **UNAVAILABLE** and no text is used. GENERATE then needs a second acknowledgement.
   - The summary is separate from the investigation: it summarises the month, and does not re-investigate.
   - With the Anthropic provider the summary is always UNAVAILABLE (appendix 22C §18).
6. **Preview.** The job assembles the *complete* final pack exactly as it would be published (ID `PREVIEW-…`, never published) and renders HTML and PDF. The analyst reads it in the review page.
7. **Stale-preview protection.** At GENERATE, the backend checks five things: a preview exists; the snapshot hash sent by the browser matches; the inputs fingerprint is unchanged; readiness has no blockers; a freshly rebuilt snapshot matches. If anything changed (selections, a new investigation, the pack) the result is `PREVIEW_STALE` and nothing is generated.
8. **HOLD** records a decision with a required note. Nothing is published, and the preview no longer applies.
9. **GENERATE** (acknowledgement ticked; second tick if the summary is unavailable) runs in the request:
   - **deterministic assembly** of `final_pack.json`, built by copying from the pack (every exception UNRESOLVED), the selected investigations, the human-review record and the closing summary, then validated;
   - **HTML and PDF** rendered *from* the JSON (ReportLab PDF, byte-identical on re-render);
   - a **manifest** of SHA-256 hashes;
   - all four files written to a `.tmp-*` folder and published by **one atomic rename**. Nothing is ever overwritten.
   - Phase 8 adds `expected=(version, supersedes)` so the library refuses a version that is not the next one in the lineage.
10. **Verification** re-hashes the manifest and content and re-renders the HTML and PDF, on every view. This is the "✓ Integrity verified" badge.
11. **Versions.** v1, then v2 *supersedes* v1. Phase 8 numbers versions across the whole reassessment lineage (`audit.pack_lineage`), so a reassessed pack's final pack becomes v2 of the same month.

**Why the AI does not assemble or approve the report.** The code makes the AI's position structural, not a matter of trust:

- **It cannot approve anything:** approval is a human decision record (`RD-…`) bound to a snapshot hash the human previewed.
- **It cannot assemble the report:** assembly is deterministic code that *copies* engine results and validated, registered artefacts.
- **It cannot change the numbers:** the AI contributes only text (findings already validated and published, and one closing summary), and that text is itself rule-checked.

**February's published final pack** (`FAP-H202602-PER-2026-02-v1-b8dd53bd2449`) has these 16 sections:

1. Audit overview
2. Executive summary
3. Source data inventory (17 files with SHA-256)
4. Deterministic reconciliation results (34 control check types)
5. Exception register (EXC-H202602-01, Critical, OPEN, UNRESOLVED)
6. Supporting evidence (25 cited records)
7. AI investigation summary
8. AI investigative assessments (INSUFFICIENT_EVIDENCE, "interpretation, not observation")
9. Confirmed observations F-01..F-07
10. Hypotheses (not established) H-01
11. Evidence gaps and conflicts
12. Suggested next steps S-01..S-03
13. Human review record (GENERATE by the synthetic demonstration reviewer)
14. Limitations and exclusions
15. Audit trail and provenance
16. AI-Generated Closing Summary (gpt-6-luna, fingerprint `f7dc43fb…`)

---

## 15. Calculation summary: the 36 controls

> The authoritative reference remains **`20B_RECONCILIATION_CALCULATIONS.md`**. It was checked again today against `uc042lib/validate.py`: **every formula and line range in 20B matches the code.** Appendix **22A** gives the full one-row-per-control table (question, records, matching, formula, time rules, missing-evidence behaviour, exception route), with file:line.

**Rules that apply everywhere:**

- Every amount comparison is **exact to the cent**. There is **no money tolerance**.
- The only tolerances are **time limits**:
  - the 17:00 Europe/London reconciliation point, DST-aware;
  - "next business day" for timing differences and for allocating unallocated receipts;
  - "same day" for fee top-ups;
  - "15 business days" for the regulatory return.
- Missing evidence makes a result **INSUFFICIENT_EVIDENCE, never zero**.
- No currency conversion: every figure is in one currency (internal reconciliation) or for one account (external reconciliation).
- Matching between files is **by reference, never by amount**.

### 15.1 The 36 controls in business language

| # | Control | The financial question it answers |
|---|---|---|
| 1 | V00-FILE | Is every required file present, unchanged (SHA-256 vs manifest) and for this month? |
| 2 | V01-SCHEMA | Can each CSV be read as its evidence type (exact header, row counts)? |
| 3 | V01-PDF | Is each PDF real and does it carry its key details; does the policy apply to this month? |
| 4 | DQ-FIELD | Is every row well-formed (2-decimal amounts, ISO dates with offsets, valid codes, unique keys)? |
| 5 | DQ-PERIOD | Does each row belong to this month (apart from the permitted opening rows)? |
| 6 | C03-POLICY | Does the policy prescribe the method the engine implements ("STANDARD", "Per currency")? |
| 7 | C03-POINT | Were reconciliations, snapshots and bank confirmations taken at the 17:00 point? |
| 8 | C01-COVER | Was exactly one internal reconciliation done per currency per reconciliation day? |
| 9 | C07-COVER | Was exactly one external (bank) reconciliation done per safeguarding account per day? |
| 10 | C14-COVER | Do we hold every client snapshot, both settlement batches, the 17:00 confirmation and the end-of-day statement, every day? |
| 11 | DQ23-STATEMENT | Does each bank statement add up (opening + entries = closing)? |
| 12 | DQ22-CONTINUITY | Does each day's bank opening equal the previous closing, and does the first statement start where the cash book starts? |
| 13 | BC-VS-EOD | Does the 17:00 bank balance equal the opening plus entries booked by 17:00? |
| 14 | CASH-BANK-LINK | Does every ledger posting have exactly one bank entry with the same reference and amount? |
| 15 | BANK-CASH-LINK | Did anything hit the safeguarding account that the ledger did not record? |
| 16 | C04-REQUIREMENT | How much must be safeguarded at 17:00 (Σ positive client balances + open unallocated receipts), and did the firm report it correctly? |
| 17 | C05-RESOURCE | What do the firm's books say is held at 17:00 (cash book rebuilt to 17:00 + items B–D), and did it report it correctly? |
| 18 | C06-DIFFERENCE | Does the firm hold exactly what it owes (resource − requirement), as reported? |
| 19 | C07-BANK-EVIDENCE | Does the bank's own 17:00 confirmation say what the firm reported? |
| 20 | RC2-LEDGER | Does the cash book really show the reported ledger balance at 17:00? |
| 21 | C08-DIFFERENCE | Does the bank hold what the ledger says (bank − ledger)? If not, is there timing evidence? |
| 22 | C11-BATCH-ARITH | Does each settlement batch add up from its lines, with each line a real transaction? |
| 23 | C11-BATCH-BANK | Did the bank receive or pay exactly the batch net under the batch reference? |
| 24 | C11-TXN-LINE | Is every card load, spend or refund settled in exactly one batch line? |
| 25 | FUND-TOPUP | Were fees netted from settlement replaced from own funds the same day? |
| 26 | RC4-DIRECT | Did each client bank load or payout actually go through the safeguarding account? |
| 27 | C09-ALLOCATION | Was each unallocated receipt real, and allocated to a client by the next business day? |
| 28 | C11-BANK-ENTRY | Is every safeguarding bank movement explained by a batch, transaction, receipt or top-up? |
| 29 | C12-REFUND | Does each refund reverse a real original, without exceeding it? |
| 30 | CBAL-NONNEG | Does any client have a negative balance? |
| 31 | CBAL-ROLLFWD | Does yesterday's client balance plus the transactions in between equal today's? |
| 32 | C13-CURRENCY | Is any record in a currency other than its account's or batch's? |
| 33 | C10-DESIGNATION | Has the bank acknowledged each safeguarding account as such (letters IN-15/16)? |
| 34 | DISC-LOG | Was each bank-ledger difference logged for investigation (IN-14)? |
| 35 | C16-GOVERNANCE | Was an accountable person named for the month (optional IN-18)? |
| 36 | C16-RETURN | Was last month's regulatory return filed within 15 business days (optional IN-19)? |

### 15.2 Internal and external reconciliation

- **Internal reconciliation** (C04 → C05 → C06): *requirement* vs *resource*, per currency per day.
  - **Requirement** = Σ max(0, client balance) + open unallocated receipts at 17:00.
  - **Resource** = the cash book rebuilt entry by entry up to 17:00 (item A), plus items B–D as reported (0.00 in all data; not verified).
  - **Difference** = resource − requirement. It must equal the reported difference and should be zero.
  - Both sides come from the firm's own records, so **a shortfall that exists only at the bank cannot appear here.**
- **External reconciliation** (C07 → RC2 → C08): the *bank's* 17:00 confirmed balance vs the *ledger* at 17:00, per safeguarding account.
  - **Difference** = **bank − ledger**. A negative difference means the bank holds less than the books, so the firm must top up from own funds (flag `OWN_FUNDS_REQUIRED`).
  - The firm's reported figures are compared with the recomputed ones, **never used in their place**.

**Opening balances, movements, closing balances.**

- **Openings:** each month starts from three "permitted boundary" records dated the previous month-end: the cash-book OPENING_BALANCE row, each client's month-end snapshot, and the first bank statement's opening.
- **Movements:** no monthly totals are calculated. Movements exist only inside the checks: a statement's entries (DQ23), entries booked by 17:00 (BC-VS-EOD), cash-book postings to 17:00, and client transactions between two 17:00 points (CBAL-ROLLFWD).
- **Closings:**
  - bank closings are taken from the statements and checked arithmetically and for day-to-day continuity;
  - the ledger position is recomputed cumulatively each day, not rolled from the previous day.

**Daily reconciliation.** The days are exactly the calendar rows marked `is_recon_day = true` (IN-01). Bank holidays are computed only for business-day arithmetic.

**Bank vs cash book, settlement, transactions, refunds, unallocated, missing statements.** These are covered by controls 14–15, 22–29 and 10 respectively. The two worked examples below show the most important ones.

**Month-to-month continuity.** There are three separate mechanisms; only the first is in the pack:

1. **The engine** checks only within the month: the first bank opening against the cash-book opening (DQ22). It never reads last month's files.
2. **`uc042lib/continuity.py`** runs *after* processing an upload. It compares last month's closing with this month's opening for bank, cash book, clients and unallocated receipts. Its result goes only into the processing run's record, not into the pack.
3. **`tools/verify_demo_history.py`** is a separate checker that produced `demo_history/verification/continuity.csv`: 144 comparisons across the 8 month boundaries, all MATCH.

Appendix 22A §5 notes that mechanisms 2 and 3 use **different client logic**. By reading the code, mechanism 2 would report CLIENT "NOT_VERIFIABLE" at 4 of the 8 boundaries. This is inferred, not executed.

### 15.3 Worked example A: February, the missing EUR statement (EXC-H202602-01)

**What is expected.**

- The calendar says **16 Feb 2026 is a reconciliation day** (IN-01 line 17).
- The inventory says **SGA-EUR-01 is a safeguarding account** (IN-02 line 3).

**What is missing.**

- **There is no 17:00 confirmation** (IN-07) **and no end-of-day statement** (IN-08) for SGA-EUR-01 on 16 Feb.
- The statement chain jumps from **13 Feb** (closing €73,061.72) to **17 Feb** (opening €73,199.44).

**How the engine reacts.** Every check that needed that day's bank evidence returns **INSUFFICIENT_EVIDENCE** with the same root cause, `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16`:

- C14 coverage (×2);
- DQ22 continuity ("statement gap");
- CASH-BANK-LINK for the five cash-book entries of that day;
- C07 ("reported bank balance is unverified");
- C08 ("bank evidence not provided; difference not computed", even though the firm *reported* 0.00);
- C11-BATCH-BANK (×2);
- FUND-TOPUP;
- RC4-DIRECT (×2).

**Result:** 15 results, one root cause, **one Critical exception, OPEN**. Engine status EVIDENCE_INCOMPLETE. 1,788 results: 1,690 PASS, 83 NA, 15 INSUF, 0 FAIL.

**What still passes ("missing is not zero").** The ledger-only checks on the same day still run and pass:

- requirement = resource = **€73,199.44**;
- RC2-LEDGER €73,199.44;
- both batches add up.

**What the engine does not infer.** The ledger's movement on 16 Feb is +1,821.28 + 1,485.52 + 6.79 − 1,007.29 − 2,168.58 = **+137.72**. 73,061.72 + 137.72 = 73,199.44, exactly the 17 Feb opening. The surrounding evidence is consistent, but the engine by design does **not** fill the gap.

### 15.4 Worked example B: September S05, the £812.40 discrepancy

**What changed in the synthetic data.** One extra bank debit was added on 17 Sep: `BE-GBP-0917-X01`, "SETTLE 0417", **£812.40 D**, on SGA-GBP-01. It appears on the bank statement and in the bank's 17:00 confirmation, but has **no cash-book entry**.

**External reconciliation, 17 Sep:**

| | Engine computed | Firm reported | Outcome |
|---|---|---|---|
| Bank (IN-07 17:00 confirmation) | 340,672.06 | 340,672.06 | C07 PASS |
| Ledger (cash book to 17:00, 73 entries) | 341,484.46 | 341,484.46 | RC2 PASS |
| **Difference = bank − ledger** | **−812.40** | −812.40 | **C08 FAIL** |

- **Bank cross-check.** Statement opening 334,413.00 + six entries (including −812.40) = 340,672.06, so DQ23 and BC-VS-EOD PASS.
- **Ledger cross-check.** Five postings, +7,071.46, give 341,484.46. The £812.40 debit is the whole gap.

**Internal reconciliation, same day.** Requirement 341,484.46 = resource 341,484.46, so the difference is **0.00**. Both sides are the firm's own books, so the bank-only debit cannot show here.

**Why it is classified "unexplained".**

- Timing logic only starts from **cash-book** entries and looks for their bank counterpart within one business day.
- A bank entry with no ledger posting can never be timing evidence: "explained by timing 0.00, residual −812.40".
- The firm claimed no timing difference.
- The category is therefore "**Unexplained bank-ledger difference**".

**Exceptions.**

- **EXC-S05-01**, Critical:
  - C08 FAIL on all 10 reconciliation days 17–30 Sep, merged into one exception because the account and amount repeat on consecutive days;
  - DISC-LOG FAIL (no discrepancy-log entry);
  - flags `OWN_FUNDS_REQUIRED` (negative difference) and `NO_INVESTIGATION_LOGGED`.
- **EXC-S05-02**, High: the unmatched bank entry (BANK-CASH-LINK and C11-BANK-ENTRY FAIL).
- The two are linked by lineage in group GRP-S05-01 ("the bank entry is inside the balance where the difference begins"). No cause is asserted.

### 15.5 Points that are unclear or surprising in the calculations (from appendix 22A §5)

1. **Engine continuity.** The engine does not check continuity across months, and the two continuity tools disagree on client method (§15.2).
2. **Misreports labelled as differences.** A *reporting* error with a true difference of 0.00 still becomes a Critical "Unexplained bank-ledger difference" or "Internal reconciliation difference".
3. **Row-count mismatches mislabelled.** A manifest row-count mismatch is labelled "Invalid rows excluded … dependent checks were not run", although no row was excluded and every check ran.
4. **Changed files still used.** A file whose SHA-256 differs from the manifest is reported as FAIL, but is still used in every calculation.
5. **Check counts disagree.** The code has 36 check IDs; February's pack shows **34** (DQ-FIELD and DQ-PERIOD do not appear when clean); older documents say **32**.
6. **Hard-coded synthetic conventions.** Examples: one SCHEME and one ACQUIRER batch per currency per day; the top-up reference `TOPUP-{CCY}-{YYYYMMDD}`; the discrepancy-log ID pattern; one safeguarding account per currency. Real data would need these confirmed.
7. **Unchecked fields.** Some IN-05 and IN-06 fields are never checked: when the reconciliation was performed, the D+1 figures, the preparer and the reviewer.

---

## 12. Technical architecture

Detail: **appendix 22D** has every component, the 58-route endpoint table, five request traces with file:line at each hop, and the storage tables.

### 12.1 Architecture diagram

```
┌──────────────────────────── BROWSER ─────────────────────────────────────────────────────────────┐
│ React 19 + TypeScript (Vite)   frontend/src                                                        │
│  App.tsx (React Router: 19 routes) ─► pages/*.tsx ─► components/*                                  │
│        │ useData()                                                                                 │
│        ▼                                                                                           │
│  DataSource interface (data/DataSource.ts)                                                         │
│   ├─ apiSource.ts  (default; 10 s shared cache for lists, cleared on every change / finished job)  │
│   └─ MockDataSource (dev/tests only: captured fixtures, simulated actions, never in a build)       │
│        │                                                                                           │
│  api/endpoints.ts ─► api/client.ts  fetch(JSON, 30 s timeout, RFC 7807 problem → ApiError)          │
└────────┼───────────────────────────────────────────────────────────────────────────────────────────┘
         │ HTTP/REST  http://127.0.0.1:8000/api/v1/...   (CORS: the Vite origin)
┌────────▼──────────────────────────── BACKEND (one Python process) ───────────────────────────────┐
│ FastAPI  uc042app/api/main.py ─► routers/{health,monthly,packs,investigations,cases,reviews,       │
│                                    final_packs,jobs,activity}.py  (Pydantic request/response)      │
│        │                                                                                           │
│ Services uc042app/services/: MonthlyService (periods, uploads, processing, reassessment, lineage)  │
│   PackService (verified pack cache) · InvestigationService · AiAuthorizationService · CaseService  │
│   ReviewService (selections, readiness, preview, decisions) · FinalPackService · Registry · Locks  │
│        │                          │                                   │                            │
│        │ JobRunner (ThreadPool, uc042app/jobs) ─ PROCESSING / INVESTIGATION / PREVIEW jobs         │
│        ▼                          ▼                                   ▼                            │
│ uc042app/ingest (identify,   uc042lib/validate.py + pack/     uc042lib/investigation/ (LangGraph:  │
│  dates, duplicates;          (deterministic ENGINE, 36 checks,  route→retrieve→packet→LLM+tools→   │
│  document store)             writes the pack)                   validate→publish)                  │
│                                                                 uc042lib/final_pack/ (assemble,    │
│                                                                 render HTML/PDF, publish, verify,  │
│                                                                 closing summary)                   │
│        │                                                              │ HTTPS                       │
│        │                                                              ▼                             │
│        │                                              OpenAI Responses API (gpt-6-luna; store=False)│
│        │                                              ONLY: investigation job, preview job          │
│        ▼                                                                                            │
│ Repositories (SQLAlchemy 2, pg8000)                         File storage (write-once folders)       │
└────────┼────────────────────────────────────────────────────────────┼───────────────────────────────┘
         ▼                                                            ▼
 PostgreSQL 18 (127.0.0.1:5433) database uc042            packs/ · investigations/ · final_packs (created on first
  schema audit: periods, period_packs, runs, reviews,     GENERATE) · demo_history/{packs,investigations,
  decisions, previews, final_pack_records, registry,      final_packs,datasets} · uc042_dataset/ · document
  investigation_authorizations, ai_execution_auth.,       store (uploads, SHA-256 addressed, case folders)
  pack_lineage, record_provenance                         · app state dir (instance lock)
  schema operations: source_documents, upload_batches,
  jobs, activity_events, exception_cases, case_entries
  (Alembic migrations 0001 → 0004)
```

### 12.2 Responsibilities in one line each

| Layer | Responsibility in UC-042 |
|---|---|
| React | Draws the screens; each page asks the DataSource for data and re-renders when it arrives. |
| TypeScript | Types every API response (`api/types.ts`). A contract check (`frontend/scripts/check_contract.py`) compares them with the backend's Pydantic models. |
| React Router | Maps URLs to pages (19 routes, e.g. `/reports/:periodId`, `/packs/:packId/workspace/:exceptionId`, `/reviews/:reviewId`). The URL carries the state (filters, tabs, `?view=`), so links can be shared. |
| DataSource | One interface with two implementations: the real API, or mock fixtures (development and tests). Pages never call `fetch` directly. |
| API client | Builds URLs, sends JSON, applies the timeout, and turns error responses into `ApiError` with a code (e.g. `PREVIEW_STALE`). |
| HTTP / REST | Each resource has a URL; GET reads; POST, PUT and PATCH change things. Errors are RFC 7807 "problem" JSON with a code. |
| FastAPI routers | Validate the request and call one service method. No business logic. |
| Services | All business rules: gates, statuses, authorisation, locking, recording activity. |
| Reconciliation engine | `uc042lib/validate.py`: the 36 deterministic checks; then the pack writer. Pure Python, no network. |
| Investigation library | Routes, retrieves, builds the packet, runs the AI with tools, validates and publishes. |
| Tool orchestration | `tool_loop.py` and `tools.py`: executes the model's tool calls read-only against hash-verified files, enforces the budget, and builds the ledger. |
| OpenAI Responses API | The only external service. It is called in exactly two places: the investigation job and the closing summary in the preview job. |
| PostgreSQL | All mutable *records*: who did what, when, with what status. |
| SQLAlchemy | The database access layer (models and repositories). A file-based repository exists for tests. |
| Alembic | Database version control. 0001 initial; 0002 titles and submissions; 0003 unified `audit` and `operations` schemas; **0004 AI authorisations + pack lineage (pending on live)**. |
| Background jobs | A thread pool inside the backend process. Jobs are recorded in `operations.jobs`; a backend restart marks running jobs INTERRUPTED. |
| File storage | Immutable *artefacts*: packs, investigations, final packs, uploaded originals. |
| Publication registries | The investigation registry (`audit.investigation_registry`), which pins artefact hashes, and the final-pack records (`audit.final_pack_records`). |

### 12.3 Representative request traces (measured in the browser)

Each trace runs: screen → frontend call → HTTP endpoint → router → service → library → storage → response → screen.

**a) Open February's month page.**
1. `ReportPage` calls `data.periods()`, `archivePeriod()`, `finalPacks()` and `periodExceptions()`.
2. These send `GET /periods`, `/packs`, `/final-packs`, `/periods/PER-2026-02`, `/periods/PER-2026-02/exception-overview`, `/final-packs/FAP…/json`, `/periods/PER-2026-02/reassessment` and `/periods/PER-2026-02/lineage`.
3. The routers in `routers/monthly.py` and `final_packs.py` call `MonthlyService` and `PackService.peek()`. Pack summaries are read from a verified in-memory cache.
4. Data comes from PostgreSQL (`audit.reconciliation_periods`, `period_packs`, `final_pack_records`, `pack_lineage`; `operations.source_documents`) and from files (`demo_history/packs/…/pack.json`, verified by content hash; `final_pack.json`).
5. JSON goes back to the browser and the page renders.

**b) Upload March's 17 files.**
1. `UploadPage` calls `data.uploadDocuments()`, which sends `POST /periods/PER-2026-03/uploads` (multipart).
2. `MonthlyService.upload` runs `ingest/store.py` (originals saved by SHA-256), then `ingest/analysis.py` (identify, dates, duplicates).
3. Rows are written: `operations.upload_batches`, `source_documents`, `activity_events`.
4. The response is the batch, and the screen navigates to `/uploads/UPL-…`.

**c) Process the batch.**
1. `BatchActions` calls `data.processBatch()`, which sends `POST /uploads/{id}/process`.
2. `MonthlyService.process` creates a run and a job. In the job: `_process` builds the case folder, runs the engine (`uc042lib.validate`), writes `packs/PACK-CASE-PER-2026-03-…` and links it in `audit.period_packs`.
3. The run is SUCCEEDED. The UI polls `GET /jobs/{id}`, then `/periods/PER-2026-03`.

**d) Start an AI investigation** (traced in code, not executed).
1. `AiPanel` opens the dialog. `GET /ai/configuration` was measured.
2. On confirm, `POST /packs/{p}/exceptions/{e}/investigations` → `InvestigationService.start`:
   - lock;
   - authorisation check;
   - job created;
   - **`AIA-…` row written**;
   - `runner.submit`.
3. The job runs `run_investigation` (hash checks, packet, OpenAI and tools, validation, atomic publish), then the registry entry.
4. The UI polls `GET /jobs/{id}`.

**e) GENERATE** (traced in code, not executed).
1. `DecisionPanel` sends `POST /reviews/{id}/decision` with `{decision: GENERATE, snapshot_sha256, acknowledgement_accepted…}`.
2. `ReviewService.decide` → `FinalPackService.generate`, in the request (not a job):
   - stale-preview checks;
   - `assemble`;
   - render HTML and PDF;
   - `publish_final_pack(expected=(version, supersedes))` writes `final_packs/FAP-…` (or `demo_history/final_packs` for a historical-demo pack);
   - rows in `audit.review_decisions` and `final_pack_records`.
3. The response includes `final_pack`, and the UI navigates to `/final-packs/FAP-…`.

---

## 13. Database and file-storage architecture

**The split.**

- **PostgreSQL** holds **records that change state**: workflow status, decisions, authorisations, links and logs.
- **Files** hold **evidence and outputs that must never change**, each identified by its own hash.

This lets anyone re-verify an artefact without trusting the database. It also means a database restore cannot silently alter a published report.

| PostgreSQL table | What it stores | Written by |
|---|---|---|
| `audit.reconciliation_periods` | One row per month: status, title, storage profile | MonthlyService |
| `audit.period_packs` | Which packs belong to which month, and their origin | MonthlyService, start-up sync |
| `audit.processing_runs` | Each processing or reassessment run and its result | MonthlyService |
| `audit.pack_lineage` *(0004)* | Reassessed pack → predecessor → lineage root, reason, what changed | MonthlyService |
| `audit.review_sessions`, `audit.review_decisions`, `audit.previews` | Final reviews, HOLD and GENERATE decisions, stored previews (with closing summary) | ReviewService |
| `audit.final_pack_records` | GENERATING / GENERATED / FAILED record per final pack | FinalPackService |
| `audit.investigation_registry` | Publication registry: pinned hashes per investigation | Registry |
| `audit.investigation_authorizations` | Owner decisions on *already published* investigations (APPROVED / AUTHORIZATION_DISCREPANCY) | admin command |
| `audit.ai_execution_authorizations` *(0004)* | Pre-execution AI consent (append-only, database trigger) | AiAuthorizationService |
| `audit.record_provenance` | Provenance of migrated and unified records | unification migration |
| `operations.upload_batches`, `operations.source_documents` | Batches; document metadata, checks, decisions (the bytes are files) | MonthlyService |
| `operations.jobs` | Background jobs and their results | JobRunner |
| `operations.activity_events` | Activity log | all services |
| `operations.exception_cases`, `operations.exception_case_entries` | Cases and their append-only entries | CaseService |

| Files | Location (live) | Content |
|---|---|---|
| September scenario packs, and packs from uploads / reassessment | `uc042/packs/` | `pack.json` (canonical), `pack.html`, processing CSVs, generation records |
| Historical packs, Jan–Aug | `uc042/demo_history/packs/` | same |
| Source datasets | `uc042/uc042_dataset/` (September), `uc042/demo_history/datasets/` (Jan–Aug) | the 19 evidence files per scenario or month |
| Investigations | `uc042/investigations/`, `uc042/demo_history/investigations/` (+ `_not_published/`) | packet, ledger, findings, tool calls, run records |
| Final packs | `uc042/demo_history/final_packs/` (February); `uc042/final_packs/` created on the first GENERATE of a primary pack | `final_pack.json`, `report.html`, `report.pdf`, `manifest.json` |
| Uploaded originals and processing case folders | `UC042_DOCUMENT_STORE` (live: `%USERPROFILE%/uc042_runtime/document_store`) | content-addressed files; `cases/SET-<hash>` |
| App state | `UC042_APP_STATE_DIR` (live: `%USERPROFILE%/uc042_runtime/app_state`) | instance lock (one backend per state dir) |

**Storage profiles.**

- A **storage profile** names which artefact folders hold a month's files:
  - **`primary`** is the configured roots (`packs/`, `uc042_dataset/`, `investigations/`, final packs); it holds September and anything uploaded.
  - **`historical-demo`** is `demo_history/…` for PER-2026-01..08.
- The profile is recorded on the period row. The backend serves every profile the database mentions (`services/layout.py`, `StorageLayout`).
- The historical-demo paths are **fixed relative to the code**, not configurable. That is why the isolated copy had to be a copy of the code.
- **Reprocessing a historical month writes its new pack to `packs/`**, not `demo_history/packs/` (observed: `PACK-CASE-PER-2026-03-…`, `PACK-CASE-PER-2026-02-…`). Lineage and versioning still find it.

**How reporting periods are kept apart** (ten mechanisms; appendix 22D §H.5). The main ones:

- the period ID is part of every pack ID and final-pack ID;
- profiles declare which periods they hold;
- uploads are tied to one period, and rows outside it are flagged, never moved;
- the engine is configured per month;
- reassessment reads only the lineage root's own verified sources;
- lineage and versions are per month;
- the dashboard and archive count per period.

---

## 14. The historical data

| Month | What is preloaded | Exceptions | AI investigations | Final pack | Notes |
|---|---|---|---|---|---|
| January 2026 | 1 historical pack (CLEAN) | 0 | — | — | A clean month is a valid report. |
| **February 2026** | 1 historical pack (EVIDENCE INCOMPLETE) | 1 (EXC-H202602-01, missing EUR bank evidence on 16 Feb) | `…6b1425b437f4` **eligible** (registered, APPROVED); `…a3fd3fd2e9ed` unregistered; 1 rejected attempt | **v1 published** `FAP-H202602-PER-2026-02-v1-b8dd53bd2449` | Reviews: `RS-898ce…` GENERATED; `RS-fc0a…` OPEN (opened 4 Nov during audit 19, kept). |
| March 2026 | 1 historical pack | 3 | — | — | |
| April 2026 | 1 historical pack (CLEAN) | 0 | — | — | |
| May 2026 | 1 historical pack | 4 | — | — | |
| **June 2026** | 1 historical pack | 4 | `INV-EXC-H202606-01-c7b353b53fb3` verifies and is registered (seq 2), but recorded as **AUTHORIZATION_DISCREPANCY**, so **not eligible** | — | Kept exactly as is; owner decision pending. |
| July 2026 | 1 historical pack | 5 | — | — | |
| August 2026 | 1 historical pack | 8 | — | — | |
| **September 2026** | **9 demonstration scenario packs** of the *same* month: S01 clean; S02 missing EUR evidence; S05 unexplained GBP difference −812.40; SC2 settlement timing; SC3B fee not itemised; SC3C short settlement; SC5A missing transaction; SC5C refund counted twice; SC5D closing snapshot mismatch | 30 in total | **7 artefacts, all unregistered, so not eligible** (S02 ×1, S05 ×3, SC2 ×2, SC5A ×1); several also fail today's validation rules; 1 rejected attempt | — | Owner decision pending on registration. |
| October 2026 | Nothing (no database row on live) | — | — | — | Shown as "No data". |
| November 2026 | Nothing (current month) | — | — | — | Shown as "Open for upload". |

**How they were made.**

- The January–August packs were generated **offline** by the same engine from synthetic datasets (reports 14–17) and registered.
- February's investigation and final pack were produced through the application on 4 November (report 17).
- The September scenarios are the original proof-of-concept data sets.
- None of these months has uploaded documents. Their source files and hashes are inside each pack.

**What happens with a genuinely new month** (observed with October, traced in code):

1. **Add New Monthly Report** creates the period. Upload the 19 files. They are identified and checked for October's dates.
   - The October checklist asks for "IN-17 Safeguarding reconciliation policy **v1.2**" and "IN-19 … (September)": the expected policy version and the previous-month return are derived for the month.
2. Processing is allowed only when every required type is present and **a policy version applies to the month**. Months whose policy does not apply fail as INCOMPLETE (appendix 22E D.4).
3. The run writes a new `PACK-CASE-PER-2026-10-…` to `packs/` (primary profile). Everything after that works as for any month.
4. **Continuity with September** is computed only into the run record (§15.2). September's 9 scenarios are separate test packs, not one "September closing", so the question of which scenario a real October should follow is not answered by the application.

---

## 16. What the analyst actually experiences

*Plain-language walkthrough, in the order a real analyst would work.*

**Opening the application.** The analyst sees the **Dashboard** for the most recent month with data: September 2026.

- **Tiles:** 9 reconciliation packs, 30 exceptions all unresolved, "0 / 0" eligible AI investigations (with a note that 7 are excluded), no pending reviews for September, no final packs.
- **Below:** a table of every month, with a status, a count of exceptions and "AI coverage". Further down are the latest final packs, pending reviews and recent activity.
- **Changing month:** clicking February or choosing it in the **Period** selector at the top changes the tiles.

**Opening February.** On **Monthly reports → February 2026** the analyst sees one long page titled "February 2026 Reconciliation Audit", with the badge "Final audit pack published". In order:

- **Source documents:** none uploaded; the pack was built from the historical dataset.
- **Reconciliation results:** one deterministic pack, "EVIDENCE INCOMPLETE".
- **Exceptions:** one exception, EXC-H202602-01, Critical, Missing bank evidence on SGA-EUR-01, UNRESOLVED.
- **AI investigations:** two artefacts, one "Eligible (registered)" and one "Not eligible … unregistered".
- **Closing summary:** the AI's paragraph from the published report.
- **Published audit packs:** v1 with JSON / HTML / PDF links.
- **Reassessment:** "cannot start yet: no evidence was received after the latest final audit pack".
- **Document history.**

**Looking at the numbers.** Clicking the pack opens the **pack page**:

- engine status and control counts (1,690 PASS, 83 not applicable, 15 could not be assessed);
- the 17 source files with their fingerprints;
- three tabs: bank vs ledger per account and day, requirement vs resource per currency and day, and the differences.

**Working an exception.** **Investigate exceptions** opens the **workspace**:

- **Left:** the exception list.
- **Middle:** what the engine found (15 checks "INSUFFICIENT EVIDENCE"), then the actual records behind it, retrieved without any AI: the bank confirmations for 13 and 17 Feb, the five cash-book entries of 16 Feb, the two settlement batches, the client transactions and the firm's own reconciliation record showing €0.00 difference. Clicking any record shows exactly which file and line it came from, and that file's fingerprint.
- **Right:** a button to open a personal **case** for notes, and the **AI investigation** panel showing the published AI analysis.

**Running the AI.** **Run investigation** opens a confirmation window. It names the month, pack, exception, provider and model, warns about charges and lists the limits. The analyst must tick a statement before **Authorise and run** becomes available. Cancel sends nothing. After authorising, the panel shows Queued → Running → Finished, typically about a minute (February: 64 s).

**Reading the AI result.** The **Summary** tab shows the AI's assessment, labelled "AI INTERPRETATION, NOT FACT": *insufficient evidence*. The other tabs:

- **Observations (7):** each says what the evidence establishes and what it does not.
- **Hypotheses (1):** marked "not established".
- **Gaps & conflicts.**
- **Next steps:** e.g. obtain the bank's confirmation for 16 Feb.

"Open the full investigation record" shows the AI's eight tool calls (for example five searches of the bank file, all "not found") and the 29 records it looked at.

**When the missing bank statement arrives.** On February's page the analyst uses **Add Supporting Document**: Additional evidence, a reason ("Bank confirmation for 16 Feb received…"), and the file. Then:

1. The batch page shows how the file was identified. The analyst confirms the batch.
2. February now shows an amber banner: "Additional evidence received after publication — pending reassessment".
3. In the **Reassessment** panel the analyst presses **Reassess February 2026** and gives a reason.
4. Seconds later: "Reassessment complete — new deterministic pack … (1 exception)", with a lineage row saying what changed. The published v1 is untouched.
5. "Go to its final review" leads to a new review that would publish **v2**.

*Important:* to change the result, the new evidence must be the **bank data files** (IN-07 confirmations / IN-08 statements). A PDF letter is stored and listed, but its content is not used in calculations (§17).

**When a discrepancy is found (September S05).** The workspace shows:

- **Amount** −£812.40 from 17 Sep, Critical, "Unexplained bank-ledger difference".
- **Records:** the bank's confirmation £340,672.06 vs the ledger's £341,484.46, and the extra bank debit "SETTLE 0417".

The analyst opens a **case**, records a note, cites the bank record as supporting evidence, records the gap ("no bank trace supplied"), records an observation (which *must* cite a record), adds a hypothesis, and finally records a decision such as **Escalated**. The page reminds them that the exception stays UNRESOLVED in the pack.

**Producing the audit pack.**

1. From the pack or workspace, **Continue to final review** shows the pack's review. If none exists, **Open a new final review** creates it.
2. The analyst checks which investigation is included per exception (**Edit**), then presses **Generate closing summary and preview**. A second confirmation window authorises the one AI summary.
3. The full 16-section report appears in the centre, as HTML, PDF or JSON.
4. They either:
   - **HOLD** with a reason (nothing is published), or
   - tick "Generating this pack does not resolve any exception…" and press **GENERATE**, confirming once more.
5. The application opens the new **final audit pack** page: "✓ Integrity verified", the three files with their fingerprints, and a **Version history** tab listing v1, v2, …

---

## 17. Where the screen and the backend differ

| # | What the screen suggests | What actually happens |
|---|---|---|
| 1 | Sidebar numbers 01–05 look like a guided, stateful workflow. | They are context links to the last pack, exception, review or final pack opened. No step is tracked or enforced by the sidebar; the gates are in the backend. |
| 2 | "Source documents: 0" for every preloaded month suggests nothing is on file. | The 17–19 source files exist and are hash-listed in the pack's "Source document inventory"; they were registered, not uploaded. |
| 3 | Adding a PDF "bank note" as additional evidence and reassessing looks like it could clear a missing-statement exception. | The engine reads only labelled key details from PDFs (designation letters, policy, governance, return). Bank balances come only from IN-07 / IN-08 / IN-09 CSV rows. The test reassessment showed "Inputs changed: none · Exceptions 1 → 1", although the uploaded IN-16 superseded the original. |
| 4 | A case disposition "Explained by analyst" sounds like the exception is dealt with. | The exception stays OPEN / UNRESOLVED in the pack and in every final pack; the disposition lives only in the case. Case entries are not part of the final audit pack. |
| 5 | "AI investigations 0 / 0" on September's dashboard suggests none exist. | Seven artefacts exist; they are excluded because they are unregistered (and several fail today's rules). The note under the tile says so. |
| 6 | The amount "—" on February's exception. | Correct: a missing statement has no amount. The engine never substitutes zero. |
| 7 | "Final review" links on every pack row look harmless. | Since Phase 8 they are harmless: the page is read-only. Only **Open a new final review** creates a session. (Audit 19 recorded the opposite on the old code.) |
| 8 | GENERATE looks like a background operation ("Generating…"). | It runs inside the HTTP request: assembly, rendering and publication. Preview and investigations are background jobs. |
| 9 | "Authorised by" on the final pack names a reviewer. | The reviewer identity is the backend's configured analyst (`UC042_ANALYST_ID` / `UC042_ANALYST_NAME`). There is no login or user account. |
| 10 | The PDF preview tab shows nothing in some environments. | The PDF exists and verifies. Headless browsers cannot display inline PDFs; a normal browser does (verified in Phase 8). |
| 11 | "Inputs changed: none" in the lineage after replacing IN-16. | The change summary compares engine check outcomes. The superseded document type is listed separately in the reassessment panel ("Uploaded documents supersede the originals for: IN-16"). Whether "inputs changed" should mention it is unclear. |
| 12 | The engine status of a reassessed pack is shown next to the original. | A reassessed pack is a **new** pack in `packs/`. The original pack and its published final pack are unchanged; the month page lists both packs. |

---

## 18. Functional limitations and unverified behaviour

**Not executed in this exploration** (prohibited, or would call OpenAI):

- a live AI investigation;
- preview / closing-summary generation;
- HOLD;
- GENERATE;
- final-pack publication.

Their behaviour is documented from the code (appendices 22B and 22C) and from earlier reports (17, 19, 20), where they were run under authorisation.

**Environment and operations.**

- **The live application was not running.** PostgreSQL 5433 had stopped (restarted by me, no data change); backend and frontend were down.
- **The Phase 8 backend will not start on live `uc042` until migration 0004 is applied** (`uc042app/db/__init__.py:47-56`).
- The final-pack library guard test (`test_protected_trees_unchanged`) still fails on purpose, awaiting the owner's re-pin decision (report 20).
- Single backend process; jobs are threads. A restart marks running jobs INTERRUPTED.
- No user accounts or roles; the analyst identity is configuration.

**Responsive behaviour** (measured):

- **1440 px:** no horizontal scroll.
- **1024 px:** the dashboard, month page and workspace are **wider than the window** (horizontal scroll).
- **768 px and 390 px:** no horizontal scroll; columns stack. At 390 px the sidebar shrinks to its codes (01, R, 02 … F, ↑) without labels.
- **Long IDs** wrap inside narrow table cells: the workspace's "Deterministic reconciliation results" table breaks IDs over many lines at 1440 px.

**Unverified or unclear, from the code traces:**

1. Some AI refusals are not recorded in `ai_execution_authorizations`: a missing tick, an unknown pack or exception, an invalid retry (22B §1.4).
2. Final-review defaults may block themselves when only unregistered valid artefacts exist ("not investigated although an eligible investigation exists"). Inferred, not tested (22B §16).
3. Report 19 counted 3 September artefacts failing the contradiction rule; the static check counts 4 (22B). `GET /investigations/{id}/verify` would settle it.
4. Opening a review does not check whether the pack has a newer reassessed version or pending reassessment (22D/22E, marked UNCONFIRMED).
5. The `expected=(version, supersedes)` check compares the application's own numbers; the lock covers one pack, not the whole lineage (22C §18).
6. February's closing-summary call has no pre-execution authorisation record, because it predates Phase 8. Its approval is documented in report 17.
7. February's published final pack lists the unregistered `a3fd…` as "eligible, not selected". The code is fixed for future packs; the published pack cannot change.
8. Run status `BLOCKED` exists in the API schema but is never set.
9. The document-store description says case folders are `cases/<run_id>`; the code uses `cases/SET-<hash>`.
10. Calculation points: §15.5 and 22A §5.

**Deliberately not decided here** (owner decisions, unchanged):

- the June investigation;
- registration of the seven September artefacts;
- dropping `uc042_history_retired_20261104`;
- deleting `uc042_e2e_rehearsal` and its folder;
- the guard re-pin;
- the live migration.

---

## 19. Screen-to-function mapping table

The calls listed were **measured** from the browser.

| Screen (route) | Main actions | Endpoint(s) | DB write | Files written | Background job | OpenAI |
|---|---|---|---|---|---|---|
| Dashboard `/` | select month; navigate | GET `/dashboard`, `/periods`, `/packs`, `/final-packs`, `/reviews`, `/activity` | – | – | – | – |
| Monthly reports `/reports` | search, filter, sort; open month | GET `/periods`, `/packs`, `/final-packs` | – | – | – | – |
| Create report `/reports/new` | Create and continue to upload | POST `/periods` | period, activity | – | – | – |
| Month page `/reports/:id` | Change title | PATCH `/periods/{id}` | period title, activity | – | – | – |
| | (view) | GET `/periods/{id}`, `/exception-overview`, `/reassessment`, `/lineage`, `/final-packs/{id}/json` | – | – | – | – |
| Upload `/upload`; Add Supporting Document | Upload and validate (initial / additional / correction) | POST `/periods/{id}/uploads` | batch, documents, activity | originals in document store | – | – |
| Batch `/uploads/:id` | Include / Exclude | POST `/documents/{id}/review` | decision | – | – | – |
| | Confirm batch | POST `/uploads/{id}/confirm` | batch, activity | – | – | – |
| | Start processing | POST `/uploads/{id}/process`; GET `/jobs/{id}` | run, job, period-pack, activity | case folder, **new pack** | **PROCESSING** | – |
| Reassessment (month page) | Start reassessment | POST `/periods/{id}/reconciliation` (purpose REASSESSMENT) | run, job, **pack_lineage**, activity | case folder, **new pack** | **PROCESSING** | – |
| Pack `/packs/:id` | tabs | GET `/packs/{id}`, `/reconciliation`, `/sources`, `/exceptions`, `/investigations` | – | – | – | – |
| Workspace `/packs/:id/workspace/:exc` | view; inspector | GET `/exceptions/{e}`, `/source-evidence`, `/investigations/{inv}`, `/findings`, `/evidence`, `/cases` | – | – | – | – |
| | Run investigation → Authorise | GET `/ai/configuration`; POST `/packs/{p}/exceptions/{e}/investigations` | **AIA- authorisation**, job, registry, activity | investigation folder (or `_not_published`) | **INVESTIGATION** | **yes** |
| Case `/cases/:id` | Open case | POST `/packs/{p}/exceptions/{e}/case` | case, activity | – | – | – |
| | Add entry | POST `/cases/{id}/entries` | entry, activity | – | – | – |
| | Request an AI investigation | POST `/cases/{id}/ai-investigation` | AIA-, job, case entry | investigation folder | INVESTIGATION | yes |
| Investigation `/investigations/:id` | tabs | GET `/investigations/{id}`, `/findings`, `/evidence`, `/tool-calls`, `/verify` | – | – | – | – |
| Open review `/packs/:id/review` | Open a new final review | GET `/reviews?pack_id=`; POST `/packs/{id}/reviews` | review session, activity | – | – | – |
| Review `/reviews/:id` | Edit selections | PATCH `/reviews/{id}/selections` | selections (preview invalidated) | – | – | – |
| | Generate closing summary and preview → Authorise | POST `/reviews/{id}/preview` | AIA-, job, **preview**, activity | – (preview stored in DB) | **PREVIEW** | **yes (1 call)** |
| | view preview | GET `/reviews/{id}/preview/html`, `/pdf`, `/json`, `/history` | – | – | – | – |
| | HOLD → SAVE HOLD | POST `/reviews/{id}/decision` (HOLD) | decision, session, activity | – | – | – |
| | GENERATE → GENERATE PACK | POST `/reviews/{id}/decision` (GENERATE) | decision, final-pack record, session | **final pack folder** (4 files) | – (in request) | – |
| All reviews `/reviews` | – | GET `/reviews` | – | – | – | – |
| All final packs `/final-packs` | – | GET `/final-packs` | – | – | – | – |
| Final pack `/final-packs/:id` | tabs, open, download | GET `/final-packs/{id}`, `/json`, `/html`, `/pdf`, `/verify` | – | – | – | – |

---

## 20. Glossary

| Term | Meaning |
|---|---|
| Safeguarding | Keeping customer money separate from the firm's own, in designated accounts (FCA CASS 15). |
| EMI | Electronic-money institution: the kind of firm UC-042 models (synthetic `SYN-EMI-001`). |
| Reconciliation day | A day the calendar (IN-01) marks for reconciliation; the engine expects every record for it. |
| Reconciliation point | 17:00 Europe/London (from the policy, IN-17); all balances are compared at this instant. |
| Requirement | What the firm owes customers: Σ positive client balances + open unallocated receipts. |
| Resource | What the firm's books say it holds: the cash book at 17:00 (item A) + items B–D. |
| Internal reconciliation | Requirement vs resource, per currency per day (both from the firm's own records). |
| External reconciliation | Bank-confirmed balance vs ledger, per safeguarding account per day. |
| Cash book / ledger | IN-10: the firm's record of every movement on its safeguarding accounts. |
| Settlement batch | A card-scheme or acquirer payment: gross, fees, adjustments, net (IN-12 / IN-13). |
| Top-up | Own funds paid in to replace fees deducted from a settlement (FUND-TOPUP). |
| Unallocated receipt | Money received but not yet attributed to a customer (IN-04). |
| Evidence type IN-01..IN-19 | The 19 document kinds of the upload contract (14 CSV, 5 PDF; IN-18 and IN-19 optional). |
| Deterministic | Same inputs, same outputs, by fixed rules; no AI and no randomness. |
| Check / control | One of the 36 engine tests; its results are PASS / FAIL / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE. |
| INSUFFICIENT_EVIDENCE | The check could not be assessed because evidence is missing; never treated as zero. |
| Root cause | The key that groups results into one exception, e.g. `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16`. |
| Exception | A grouped problem in a pack; Critical or High; always OPEN / UNRESOLVED in the pack. |
| Engine case status | CLEAN / EXCEPTIONS_OPEN / EVIDENCE_INCOMPLETE for a whole pack. |
| Reconciliation (deterministic) pack | The engine's immutable output for one month or scenario. |
| Pack content hash | SHA-256 of the canonical pack; its first 12 characters end the pack ID. |
| SHA-256 | A fingerprint of a file's exact bytes; any change gives a different fingerprint. |
| Upload batch | Files sent together; validated, decided and confirmed together. |
| Current document set | Per evidence type, the latest included document of the month's confirmed batches. |
| Submission kind | INITIAL, ADDITIONAL_EVIDENCE or CORRECTION. |
| Received after publication | A document added after the month's final pack was published; it triggers "pending reassessment". |
| Reassessment | Rerunning the engine on new evidence plus the verified originals, producing a new linked pack. |
| Lineage | The chain from a reassessed pack back to its original (root) pack; final-pack versions follow it. |
| Exception case | The analyst's append-only notebook for one exception; its disposition does not resolve anything. |
| AI investigation | One tools-mode AI analysis of one exception, validated, published and registered. |
| Tools mode | The AI may request more records through 8 read-only, typed tools, within a fixed budget. |
| Evidence packet / ledger | The records given to the AI (packet), and the packet plus everything its tools returned (ledger). |
| Citation | An ID (record, check result, search, missing item) that a finding points to; it must exist in the ledger. |
| Confirmed finding / observation | A statement the cited evidence shows (F-nn), with "establishes / does not establish". |
| Hypothesis | A possible explanation the evidence does not establish (H-nn). |
| SEARCH-nn NOT_FOUND | A recorded lookup that found nothing "in the supplied data"; it is citable. |
| ZERO_PATTERN | Validation rule rejecting a balance stated as 0 while evidence is missing. |
| `_not_published` | Folder keeping rejected or failed AI attempts for diagnosis; never eligible. |
| Publication registry | Database list pinning the hashes of every published investigation; required for eligibility. |
| Authorisation decision | Owner decision on a published investigation: APPROVED or AUTHORIZATION_DISCREPANCY. |
| AI execution authorisation (AIA) | Phase 8: the analyst's recorded consent before any AI call; append-only. |
| Eligibility | Whether an investigation can be selected in a final review (verifies, registered, not discrepant, passes current rules). |
| Review session | The final-review workspace for one pack (OPEN, ON_HOLD, GENERATING, GENERATED, GENERATION_FAILED). |
| Selection | Per exception in a review: INCLUDED (with one investigation), NOT_INVESTIGATED or EXCLUDED_BY_ANALYST. |
| Readiness | The review's blockers, warnings and info; GENERATE needs no blockers. |
| Snapshot / fingerprint | Hashes of the exact inputs of a preview; GENERATE refuses if they changed (PREVIEW_STALE). |
| Closing summary | One AI-written month summary (report section 16), or UNAVAILABLE. |
| Preview | The complete report exactly as it would be published; never published itself. |
| HOLD / GENERATE | The human decision: save and stop, or authorise deterministic assembly and publication. |
| Final audit pack | The published, immutable JSON / HTML / PDF / manifest, versioned (v1, v2 supersedes v1). |
| Storage profile | `primary` or `historical-demo`: which folders hold a month's artefacts. |
| Isolated environment | The disposable copy used for this exploration (`uc042_p9`, `%USERPROFILE%/p9`). |

---

## 21. Screenshot index

All screenshots are in `docs/audit_pack/22_screenshots/` (99 PNG files). The page text of each is in `%USERPROFILE%/p9/text/`. They were taken at 1440 px wide unless named `R_<width>_…`. Full-page shots are full height.

| Screen | Screenshots |
|---|---|
| 6.1 Dashboard | S01_dashboard_default, S01b_dashboard_february_selected, S01c_dashboard_june, S01d_dashboard_october_empty, S01e_dashboard_mock_mode, S22_dashboard_activity_after_tests |
| 6.2 Archive | S02_archive, S02b_archive_search_feb, S02c_archive_filter_published, S02d_archive_filter_nodata, S02e_archive_no_match |
| 6.3 Create report | S03_new_report_default, S03b_new_report_existing_month, S03c_new_report_future_month, S03d_new_report_october_ready |
| 6.4 Month page | S04_report_february, S04b_report_september, S04c_report_june, S04d_report_january_clean, S04e_report_march, S04f_report_october_empty, S04g_report_november, S04h_report_invalid_id, S04i_report_change_title_editing, S04k_report_march_after_upload_processing |
| 6.5 Upload | S05_upload_empty, S05b_upload_february_selected, S05c_upload_after_create_october, S05d_upload_files_selected, S05e_upload_march_existing_month, S05f_upload_march_17_files_selected |
| 6.6 Batch | S06_batch_october_mixed_files, S06b_batch_checks_expanded, S06c_batch_march_validated, S06d_batch_flag_decision, S06e_batch_march_confirmed, S06f_batch_march_processed |
| 6.7 Pack | S07_pack_february_external, S07b_pack_february_internal, S07c_pack_february_differences, S07d_pack_s05_differences |
| 6.8 Workspace | S08_workspace_february_summary, S08_workspace_february_tab_observations, …_tab_hypotheses, …_tab_gaps, …_tab_next, S08b_workspace_february_unregistered_investigation, S08c_workspace_s05_first_exception, S08d_workspace_s05_with_case |
| 6.9 Case | S09_case_new, S09b_case_observation_without_citation_refused, S09c_case_decision_form, S09d_case_with_entries |
| 6.10 AI authorisation | S10_ai_dialog_investigation_isolated_no_provider, S10b_ai_dialog_from_case, S10c_ai_dialog_investigation_configured_mockmode |
| 6.11 Investigation | S11_investigation_february, S11b_evidence_investigation_february, S11c_toolcalls_investigation_february, S11d_validation_investigation_february, S11e_investigation_june_discrepancy, S11f_investigation_september_unregistered |
| 6.12 Provenance | S12_provenance_inspector_engine_record |
| 6.13 Supporting document | S13_add_supporting_document_february, S13b_supporting_batch_february, S13c_supporting_batch_february_confirmed |
| 6.14 Correction | S04j_report_add_supporting_correction_mode, S14_correction_form_march, S14b_correction_batch_march |
| 6.15 Reassessment | S15_report_february_pending_reassessment, S15b_reassess_dialog, S15c_reassessment_complete, S15d_report_february_after_reassessment |
| 6.16 Final review | S16_review_february_open_session, S16b_review_selection_editor, S16c_review_february_generated_html, S16d_review_february_generated_json, S16e_review_february_generated_pdf_headless, S16f_open_review_page_no_active_review, S16g_reassessed_pack_open_review_page, S16h_new_review_on_reassessed_pack |
| 6.17 Closing-summary confirmation | S17_closing_summary_ai_dialog_isolated |
| 6.18 HOLD / GENERATE | S18_hold_dialog |
| 6.19 All reviews | S19_all_reviews |
| 6.20 All final packs | S20_all_final_packs |
| 6.21 Final pack | S21_final_pack_february_pdf_tab, S21b_html_final_pack_february, S21c_json_final_pack_february, S21d_versions_final_pack_february |
| Other | S99_not_found; responsive R_1024_*, R_768_*, R_390_* (dashboard, report, workspace) |

---

## Appendices

| Appendix | Content |
|---|---|
| **22A_CALCULATIONS_36_CONTROLS_TRACE.md** | All 36 controls (formula, records, matching, time rules, missing evidence, exception route) with file:line; business explanations; the February and S05 worked examples from the real CSVs; 18 unclear points. |
| **22B_AI_INVESTIGATION_TRACE.md** | February's investigation traced through 13 steps with quotes from the artefacts; tools vs one-shot; sequence diagram; eligibility of June and September artefacts. |
| **22C_CLOSING_SUMMARY_AND_FINAL_PACK_TRACE.md** | Review, readiness, snapshot, preview, stale protection, HOLD, GENERATE, assembly, rendering, publication, verification, versions; February's 16 sections. |
| **22D_TECHNICAL_ARCHITECTURE_TRACE.md** | Components, 19 routes, 58-route endpoint table, five request traces, every database table, file locations, storage profiles, period isolation. |
| **22E_WORKFLOW_STAGES_AND_GATES.md** | Definitions, ID formats and states of the ten objects; every stage's backend gate with HTTP status, error code and file:line. |

Related: `20B_RECONCILIATION_CALCULATIONS.md` (calculation reference), `19_COMPLETE_UI_FUNCTIONAL_AND_ARCHITECTURE_AUDIT.md` (audit of the Phase 7 state), `20_PHASE8_FUNCTIONAL_GAP_CLOSURE_IMPLEMENTATION_REPORT.md` (Phase 8).

*The appendices were produced by read-only code traces made in parallel during this exploration. Their key claims were spot-checked against the browser observations and the artefacts. Database states they quote from earlier reports are labelled as such.*
