we ne# UC-042 — Phase 6B: February 2026 end-to-end live execution

Date: 4 November 2026. **Scope:** February 2026 only, through the real backend, PostgreSQL, the configured OpenAI provider, the tools-mode investigation, the AI closing summary, Final Review, and one authorised GENERATE.

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

The published pack is a demonstration artefact. It is not an audit opinion, a compliance certification or a resolution of any exception.

**Result:** published final audit pack **`FAP-H202602-PER-2026-02-v1-b8dd53bd2449`**, verified. The exception `EXC-H202602-01` remains **OPEN / UNRESOLVED**.

## 1. Initial February application and database state

| Item | State before this phase |
| --- | --- |
| Deterministic pack `PACK-H202602-PER-2026-02-195df2e1f216` | Present in `demo_history/packs`, verified, 1 exception (`MISSING_BANK_EVIDENCE\|SGA-EUR-01\|2026-02-16`) |
| Pack registered in PostgreSQL | **No.** The operational database `uc042` holds only the 9 September packs (1 period, 9 `period_packs`). |
| Phase 6A investigation `INV-EXC-H202602-01-a3fd3fd2e9ed` registered | **No.** `investigation_registry` was empty. |
| Can the app load the Phase 6A artefact? | Yes. It is listed, VALID and library-eligible, but **not eligible for review**: "publication registry: not in the investigation publication registry (unregistered artefact)". |
| Fresh investigation needed? | **Yes**, to exercise the application path (API job → tools mode → validation → publication → registry) and to obtain a registry-eligible investigation without importing the CLI artefact as legacy. Investigation IDs are hashes of the stored findings, so a new run receives its own identity, and the Phase 6A artefact cannot be touched. |

## 2. Backend, PostgreSQL and frontend configuration

**Single packs root.** The backend serves one packs root. The operational database's registrations point to September's `packs/`. Pointing that database at `demo_history/packs` would make the September registrations unloadable and mix the historical packs into the September archive.

**Dedicated database.** As foreseen in report 15 §10 ("a separate backend instance or state"), February ran on a dedicated database on the same cluster:

- **`uc042_history`**, created by the project role and migrated with the documented `python -m uc042app.admin db-upgrade` (Alembic `0001_initial`);
- **the operational `uc042` database was not changed** (verified read-only afterwards).

**Backend.** The documented entry point `python -m uc042app` (127.0.0.1:8000, one worker), with these explicit settings:

| Setting | Value |
| --- | --- |
| `UC042_PACKS_ROOT` | `uc042/demo_history/packs` |
| `UC042_DATASETS_ROOT` | `uc042/demo_history/datasets` |
| `UC042_INVESTIGATIONS_ROOT` | `uc042/demo_history/investigations` |
| `UC042_FINAL_PACKS_ROOT` | `uc042/demo_history/final_packs` |
| `UC042_APP_STATE_DIR`, `UC042_DOCUMENT_STORE` | `uc042/demo_history_app/{app_state,document_store}` (git-ignored names) |
| `UC042_ANALYST_ID` / `NAME` | `demo-reviewer` / "Demonstration Reviewer (synthetic)" |
| `UC042_DATABASE_URL` | `…/uc042_history`, derived in-process from `.env`; the password was never printed or written |

**Excluded from the AI runtime.** `demo_history/` as a whole and `demo_history/verification/` were never configured. The roots are validated at start-up (report 15 boundary); the verification directory and answer files are refused.

**Health.** `/health`: status ok, database true, provider_configured true, single_process true.

**Pack sync on start.** Start-up `sync_packs` registered the 8 verified historical packs under their periods as references (the application's normal behaviour for packs in its root). **Nothing was run for any other month.**

**Frontend.** Vite dev server at 127.0.0.1:5173 with `VITE_DATA_SOURCE=api` and `VITE_API_BASE_URL=http://127.0.0.1:8000` (real backend; the header shows "Live backend").

**Shutdown.** Both servers were stopped after verification. The background-task stop left the child processes running; they were then stopped by their listening ports.

## 3. Provider and model

| Item | Value |
| --- | --- |
| Provider | OpenAI Responses API (`store=False`) |
| Model | `gpt-6-luna` (resolved `gpt-6-luna`) |
| Reasoning effort | `medium` (`.env`) |
| Mock, fixture or simulation | None. All results have `simulated: false`. |

## 4. Prompt version and mode

| Item | Value |
| --- | --- |
| Investigation prompt | `uc042-investigator-prompt/2.2-tools` |
| Workflow | `uc042-investigation-graph/2.0-tools` |
| Findings schema | 1.4 |
| Mode | **tools**: the API job runs `mode="tools"` (the fixed-mode CLI default was not involved) |
| Closing summary | `uc042-closing-summary-prompt/1.0`, schema `uc042-closing-summary/1.0` |

## 5. Live model calls and tool execution

Six live model calls ran in total. All six really occurred, with provider request and response IDs recorded in the artefacts.

**Model calls and usage:**

| Step | Job | Model calls | Input tokens (cached) | Output (reasoning) | Latency | Outcome |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Investigation, attempt 1 | `JOB-9e1f215007cb78ea71c2b49f` | 3 | 53,049 (48,520) | 7,184 (2,029) | 63.1 s | Completed, **REJECTED** by deterministic validation; not published |
| Investigation, attempt 2 (retry) | `JOB-2f5489498d5ac1784c5b3523` | 2 | 34,443 (29,908) | 7,260 (1,529) | 63.8 s | **VALID**, published, registered |
| AI closing summary | preview job `JOB-bbff23e55cfba3e01ca9e53c` | 1 | 3,356 (0) | 1,504 (293) | 14.3 s | **GENERATED**, 0 validation findings |

**Tool calls.** The tool loop ran under the implementation's configured limits:

| Limit | Value |
| --- | ---: |
| Tool calls | 8 |
| Rounds | 4 |
| Records per call | 25 |
| Total records | 160 |
| Input tokens | 150,000 |
| Time budget | 300 s |

No other limit was imposed. Each attempt executed 8 read-only tool calls; none was refused, rejected or truncated, and both ended with `final_answer`.

Attempt 2's tool calls:

| Tool | Arguments | Result |
| --- | --- | --- |
| `get_settlement_batch` | AQ-EUR-20260216 | 7 records |
| `get_settlement_batch` | SB-EUR-20260216 | 7 records |
| `get_reconciliation_evidence` | SGA-EUR-01, 2026-02-16 | 2 records |
| `search_bank_entries` | each of the five cash-book references (`E2E-EUR-0216-L01`, `AQ-EUR-20260216`, `TOPUP-EUR-20260216`, `SB-EUR-20260216`, `E2E-EUR-0216-R01`) | all NOT_FOUND (correct: that day's bank entries are the missing evidence) |

Records went from 16 initially to 29 at the end.

## 6. Investigation and validation

**Attempt 1 was rejected by the existing validator.** Its confirmed finding F-03 read "…ledger balance and a reported difference of 0.00 EUR, but the engine marks the bank balance unverified and the difference not computed". The rule `ZERO_PATTERN` (`balance … of 0.00` within 40 characters) treated this as "substitute zero for a balance while evidence is missing".

- **Assessment:** a false positive. The sentence attributes 0.00 to the firm's *reported* figure and states that it is unverified. This is the documented limitation "validation is rule-based … can over-reject".
- **Action:** the validator was **not changed**. The attempt is stored, unpublished, as `demo_history/investigations/_not_published/…/2026-11-04T054432+0000-c392e113.json`.
- **Retry:** the application's normal retry (`retry_of`) produced a new live run.

**Attempt 2 is the published investigation: `INV-EXC-H202602-01-6b1425b437f4`.**

| Item | Value |
| --- | --- |
| Status | VALID, COMPLETED |
| Overall assessment | INSUFFICIENT_EVIDENCE |
| Exception resolution | `NOT_RESOLVED_BY_INVESTIGATION` |
| Registry | seq 1, `NEW_PUBLICATION`, `verify_published` OK |
| App eligibility | artefact and registry verified; eligible |

**Content of attempt 2:**

- **Seven evidence-backed findings.** These are bank controls INSUFFICIENT_EVIDENCE; external reconciliation reports 73,199.44 = 73,199.44 but the bank balance is *unverified*; internal reconciliation reports requirement = resource = 73,199.44; statements exist for 13 and 17 Feb only; five cash-book entries have no bank evidence; settlement records do not supply bank confirmation; the FUND-TOPUP computed 6.79 remains insufficiently evidenced.
- **One hypothesis**, labelled HYPOTHESIS: "bank activity … may have occurred", with the limitation "no supplied bank confirmation … verifies".
- **Missing evidence:** M-01 (MISS-01).
- **Contradictions:** none.
- **Three next steps:** obtain the statement and confirmation, the bank transaction records, and the reconciliation workpapers.

**Checked independently against the February CSVs.** Every factual claim matches:

- external and internal reconciliation 73199.44 / 73199.44 / 0.00;
- five cash-book entries (D, D, D, C, C);
- statements 13 and 17 Feb only;
- batch directions AQ TO_FIRM and SB FROM_FIRM;
- no bank entry with either batch reference;
- the 17 Feb opening balance 73199.44 C.

**Nothing invented:**

- every amount the AI states (0.00, 6.79) appears in the evidence, and every date it names is in the evidence;
- no cause is claimed;
- no resolved, closed or approved wording.

## 7. Closing summary

Generated live in the preview job and stored in preview `PV-42255610070f513f87665a8e` with summary SHA-256 `fbb6aae7…`. Status GENERATED, 1 attempt, **0 validation findings**.

**Content (checked):**

- **Overall position:** EVIDENCE_INCOMPLETE / NOT_FULLY_ASSESSED; one OPEN Critical exception; 15 results not assessed; the exception "remains UNRESOLVED".
- **Summary:** the reported matching balances are unverified; "the supplied records do not confirm the bank position"; "not an audit opinion or a compliance certification".
- **Six key observations**, each citing the investigation's findings.
- **One unresolved item.** The hypothesis is placed under *unverified hypotheses* ("This hypothesis is not established").
- **One evidence gap**, citing M-01 and MISS-01.
- **Three next steps.**
- **Limitations** include "not … a statement that the reconciliation is clean".

**It does not:**

- present the hypothesis as fact;
- claim the statement was recovered;
- claim resolution;
- assert a clean reconciliation;
- add information outside the investigation or pack.

**References.** All 14 source references resolve to investigation items (`INV-…#F-01` … `#S-03`, `#H-01`, `#M-01`) or to `EXC-H202602-01` / `MISS-01`.

## 8. Final Review and Generate

| Step | Result |
| --- | --- |
| Review session | `RS-898ce8500e706e4a50f3f91b` (API `POST /packs/{pack}/reviews`). Default selection: `EXC-H202602-01` INCLUDED with `INV-EXC-H202602-01-6b1425b437f4` (newest registry-eligible tools-mode investigation). |
| Readiness before preview | blocker `PREVIEW_REQUIRED` only; info `UNRESOLVED_EXCEPTIONS` (1) |
| Preview | `PV-42255610070f513f87665a8e`, snapshot `e432ca8f…`, preview final content `86dc5e2f…` |
| Readiness after preview | `ready: true`, no blockers, no warnings |
| Decision | `RD-29e39d965f3ac4d29819ab84`, **GENERATE** (`POST /reviews/{id}/decision`) |

**What the decision carried:**

- the current preview's `snapshot_sha256`;
- `acknowledgement_accepted: true` (text: "Generating this pack does not resolve any exception, confirm any hypothesis or establish compliance. Unresolved exceptions will appear as UNRESOLVED.");
- a reviewer comment recording the one-time product-owner authorisation for this synthetic demonstration.

**Before publishing, the application re-verified:** the snapshot, the inputs fingerprint, readiness, and the investigation (library and registry). There was no bypass.

**Session result:** status GENERATED, final pack `FAP-H202602-PER-2026-02-v1-b8dd53bd2449`.

**What GENERATE does not mean:** the reviewer is a synthetic demonstration identity. GENERATE authorised assembly only; it did not approve the investigation, resolve the exception, certify compliance or declare the reconciliation clean.

## 9. Final pack

| Item | Value |
| --- | --- |
| ID | `FAP-H202602-PER-2026-02-v1-b8dd53bd2449` (version 1, no predecessor) |
| Content SHA-256 | `b8dd53bd24494b3ad78d02de03b5c349ff1fa11d6372406981b17dc9145cfd85` |
| Location | `uc042/demo_history/final_packs/FAP-H202602-PER-2026-02-v1-b8dd53bd2449/` |
| Files | `final_pack.json` (canonical), `report.html`, `report.pdf` (24 pages), `manifest.json` |
| Publication | existing atomic, write-once mechanism (`FinalPackService.generate`) |
| References | period PER-2026-02; deterministic pack `PACK-H202602-PER-2026-02-195df2e1f216` (hash `195df2e1…`); investigation `INV-EXC-H202602-01-6b1425b437f4` |

## 10. JSON, HTML and PDF verification

**Integrity checks:**

- **Library publication check:** `verify_final_pack`: no problems.
- **API check:** `GET /final-packs/{id}/verify`: `verified: true`, no problems.
- **Generator validation rerun:** `validate_final_pack` (schema and content rules) was run on the published JSON with a **freshly rebuilt review snapshot**. It passed, and the rebuilt snapshot hash equals the recorded one.

**Same canonical content in all renderings:**

- **16 sections** in the same order in HTML and PDF: 1 Audit overview … 15 Audit trail and provenance, **16 AI-Generated Closing Summary** (last);
- both renderings contain the final-pack ID, pack ID, investigation ID, `UNRESOLVED`, the closing-summary text and the content hash;
- the synthetic label appears in both.

**Visual inspection of the PDF.** Pages 1–4 and 22–24 were rendered to images with PDFium, installed into an isolated scratch folder, not the project environment, and inspected:

| Page | What it shows |
| --- | --- |
| 1 | synthetic banner, the "not a compliance opinion" statement, the 16-item contents, overview (PER-2026-02, EVIDENCE_INCOMPLETE, closing summary GENERATED), executive summary "1 UNRESOLVED" |
| 2 | source inventory with SHA-256 per file, including the illustrative v1.1 policy (HD-1) |
| 4 | the 16 Feb EUR external reconciliation shows bank **"not available"** and INSUFFICIENT_EVIDENCE: no balance substituted |
| 23 | section 16 with the AI disclaimer, all subsections, citations and "UNRESOLVED" |
| 24 | provenance: model, prompt, input fingerprint, content hash |

The layout is clean, with no overflow or missing glyphs observed.

## 11. Citations and source integrity

All of these were checked with independent scripts, plus the application's own checks:

| Check | Result |
| --- | --- |
| Investigation citations | all 50 cited IDs are allowed. 29 source records resolve to their file, line and primary key in `demo_history/datasets/2026-02/source_data/` with matching file SHA-256. The rest are engine results, searches or MISS-01, plus the exception ID `EXC-H202602-01` (in the allowed set; resolves to the pack's exception register). |
| Final-pack evidence index | 25 records resolve to their file, line and key with matching file hash |
| Source inventory | 17 input hashes equal the February dataset files |
| Closing-summary references | 14, all resolve |
| Investigation reference in the final pack | the recorded `findings_sha256` equals the artefact's `findings.json`, and `verify_published` passes |
| Registry | `findings_sha256 ba6d64e0…` equals the file |
| Deterministic pack | verifies, and its hash equals the final pack's reference |

## 12. Database registration and API retrieval

**`uc042_history` after the run** (read-only):

| Table | Rows | Contents |
| --- | ---: | --- |
| `reconciliation_periods` | 8 | |
| `period_packs` | 8 | |
| `jobs` | 3 | 2 INVESTIGATION (1 FAILED, 1 COMPLETED), 1 PREVIEW |
| `investigation_registry` | 1 | |
| `review_sessions` | 1 | |
| `review_decisions` | 1 | |
| `previews` | 1 | |
| `final_pack_records` | 1 | GENERATED, `b8dd53bd…` |
| `activity_events` | 8 | period registrations |
| uploads, documents, runs | 0 | |

**Admin checks (backend stopped):**

- `python -m uc042app.admin verify-registry`: 1 entry, all verified;
- `verify-pack-references`: 14 references, **0 problems**.

**Operational database `uc042`:** unchanged (same 13-table row counts as before: 9 September packs, empty registry).

**API retrieval through the running backend:**

| Endpoint | Result |
| --- | --- |
| `GET /final-packs` | lists the pack |
| `GET /final-packs/{id}` | detail |
| `/verify` | verified |
| `/json`, `/html`, `/pdf` | 200; each download is **byte-identical** to the published file |
| `GET /periods/PER-2026-02` | `RESULTS_AND_FINAL_PACK`, final_pack_count 1 |
| `GET /packs/{pack}/exceptions` | `EXC-H202602-01` OPEN / AWAITING_HUMAN_REVIEW |
| `GET /reviews/{id}` | GENERATED with the final-pack ID |
| `GET /investigations/{id}/verify` | artefact and registry verified, eligible |

## 13. Frontend verification

Real API mode, rendered with headless Microsoft Edge (screenshots inspected):

- **Final audit pack page** (`/final-packs/FAP-…`):
  - "Live backend", "Integrity verified (manifest hashes, content hash, HTML and PDF match the canonical JSON)";
  - pack record (original pack and hash, investigation reference, GENERATE by the demonstration reviewer with the note);
  - "Unresolved exceptions: 1 carried in the pack as UNRESOLVED";
  - artefacts (PDF, HTML, JSON with hashes).
- **Period page** (`/periods/PER-2026-02`): "Results and final pack", 1 pack, 1 exception, 1 unresolved, 1 final audit pack.
- **Dashboard:** January–August listed with packs; "Recently generated audit packs" shows the February final pack.

**Display limitations observed.** Not changed: UI changes were out of scope.

1. The header period selector defaults to September 2026, so the sidebar's "Current pack" label reads "September 2026" for the February pack. The dashboard's static text says September is "the only month with data", and its tiles count only the selected period. These are pre-existing frontend assumptions.
2. Historical packs are labelled "POC test scenario H202602", because `sync_packs` labels any pack with a scenario ID as `POC_SCENARIO`.
3. The embedded PDF preview pane is blank in headless Edge (no PDF viewer in headless mode). The PDF itself was inspected separately (§10).

## 14. Test results

| Suite | Result |
| --- | --- |
| Python full suite (`-W error::ResourceWarning`) | 568 run: 567 passed, 0 failed, 1 skipped (opt-in live test) |
| Frontend `npm test` | 23 passed, 2 skipped (opt-in live) |
| Frontend production build | OK |

**Test changed:** `tests/test_demo_history.py::OutputPacks::test_demo_output_is_isolated_and_deterministic_only` now pins exactly the authorised February artefacts:

- the two published investigations, both verified, non-simulated and not resolved;
- the one rejected attempt;
- the one final pack, verified, referencing the February pack, with the exception UNRESOLVED.

No other investigation or final pack may exist.

## 15. Failures, warnings, limitations and unexpected behaviour

- **First investigation attempt rejected** by the `ZERO_PATTERN` rule (a false positive, see §6). This was handled by the application's normal retry; the validator was not altered. **Recommendation:** narrow the rule so a *reported* figure explicitly described as unverified is not treated as substitution. That is a validator change for separate approval.
- **Stopping the servers:** the background-task stop did not terminate the child processes. They were stopped by port, after which the admin commands could take the instance lock.
- **Frontend display limitations:** see §13.
- **Pack sync:** the 8 historical packs were registered as period references in `uc042_history` at start-up (normal application behaviour). No other month was processed, investigated, reviewed or generated.
- **Data handling:** `store=False`. OpenAI default abuse-monitoring retention (up to 30 days) is assumed; Zero Data Retention is not established. All data is synthetic.

## 16. Files and database records created or modified

**Files created:**

- `demo_history/investigations/PACK-H202602-PER-2026-02-195df2e1f216/EXC-H202602-01/INV-EXC-H202602-01-6b1425b437f4/`, containing `findings.json`, `evidence_packet.json`, `evidence_ledger.json`, `tool_calls.json` and `runs/0001.json`
- `demo_history/investigations/_not_published/PACK-H202602-PER-2026-02-195df2e1f216/EXC-H202602-01/2026-11-04T054432+0000-c392e113.json` (the rejected attempt)
- `demo_history/final_packs/FAP-H202602-PER-2026-02-v1-b8dd53bd2449/`, containing `final_pack.json`, `report.html`, `report.pdf` and `manifest.json`
- `demo_history_app/app_state/instance.lock`
- `docs/audit_pack/17_FEBRUARY_END_TO_END_LIVE_EXECUTION_REPORT.md`

**Files modified:** `tests/test_demo_history.py` (one test, §14).

**Database:**

- **New database `uc042_history`**, migrated, holding these records:
  - 8 `reconciliation_periods`
  - 8 `period_packs`
  - 8 `activity_events`
  - 3 `jobs`
  - 1 `investigation_registry` entry
  - 1 `review_sessions` row
  - 1 `review_decisions` row
  - 1 `previews` row
  - 1 `final_pack_records` row
- **Operational database `uc042`:** no change.

## 17. Preservation

The project was hashed before and after the run. The comparison shows **only the additions in §16**. All of these are **unchanged**:

- the 8 historical deterministic packs and their datasets;
- `demo_history/verification/`;
- the 9 September packs and datasets;
- `investigations/` (September);
- the golden snapshots;
- the final-pack library;
- the application code.

The **Phase 6A investigation `INV-EXC-H202602-01-a3fd3fd2e9ed` is unchanged**, still verifies, and was not registered or reused.

No reconciliation calculation, matching rule or UI design was changed. No other month and no September pack was investigated, summarised or generated.
