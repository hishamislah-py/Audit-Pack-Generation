# UC-042 Smart Parser — Phase 3B-11: Unmappable HITL, Mapping Review Screen and UC-042 Reconciliation Execution

| | |
|---|---|
| Date | 19 November 2026 (engine run timestamps are UTC, 18 Nov evening) |
| Working copy | `C:\Users\artlptp263user\p10\smartparser_phase1` (the only code location modified) |
| Evidence | `Downloads\UC042_SMART_PARSER_PHASE3B11\`: `evidence_baseline\`, `evidence\` (regression), `ui_evidence\` (10 screenshots + browser results), `reconciliation\` (engine runs), `demo_workspace\` (review demo) |
| Result | **All acceptance criteria met.** UNMAPPABLE proposals now create a human-review task. A real analyst mapping-review screen is implemented, connected to PackageService, and verified in a real browser (13/13 steps). The **actual UC-042 engine** ran in isolation on the Smart Parser snapshot from 3B-10: run `RECON-20261118T192518Z-23f8b80b` on snapshot `SNAP-001-23f8b80b` gave CLEAN, 1,886 check results and 0 exceptions, **byte-identical** to the same engine on the original files. A scenario with known discrepancies (S05) produced 2 exceptions, **matching UC-042's own answer key** and traced to file versions. Full suite **585 passed**; nothing written into the UC-042 tree. |

**Evidence labels**

| Label | Meaning |
|---|---|
| **[I]** | Implemented |
| **[T]** | Test-verified |
| **[UI]** | UI-verified in a real browser (Microsoft Edge, headless, driven through the page's own controls) |
| **[INT]** | Integration-verified |
| **[RX]** | Reconciliation executed (the real UC-042 engine) |
| **[N]** | Not implemented |

---

## 1. Baseline and protected-path status

**Baseline before any change** (`evidence_baseline/regression_summary.txt`):
- **568 passed**; registry in sync (19); baseline 445/445; corpus 161/161;
- UC-042 107 code + 624 dataset files, and Desktop 63 files, hash-identical; 0 UC-042 files newer than the Phase 1 start;
- POC policy `DISABLED`; AI default off; production authority `{}`.

**After all changes** (`evidence/regression_summary.txt`): the same protected hashes and 0 newer UC-042 files. Each engine run also checked "UC-042 files newer than run start": **0** for every run (§14).

## 2. UNMAPPABLE routing changes [I/T]

**Before (3B-6.1…3B-10).** A NO_MATCH column (explicit UNMAPPABLE, an invented or invalid canonical field, or an unaddressed column) that left a required field uncovered led to `REJECT_OR_HOLD`. The package version became FAILED_VALIDATION, with no review task.

**Now:**

| Change | Where |
|---|---|
| Policy order: … deterministic conflict → HUMAN_REVIEW; invalid proposal assignment → HOLD; **NO_MATCH → HUMAN_REVIEW** (now **before** the required-field HOLD); required field unresolved → HOLD; ambiguous/plausible → HUMAN_REVIEW; else AUTO | `orchestration/policy.py` (docstring updated) |
| A NO_MATCH proposal opens **one** `ColumnReviewCase` of the new kind `UNMAPPABLE_PROPOSAL`, seeded with the deterministic matches and the validated (CLEAR/PLAUSIBLE/AMBIGUOUS) proposal fields. **No parallel proposal session** is created (one review channel) | `orchestration/orchestrator.py` `_open_unmappable_case` |
| Each case column now carries what the proposal concluded (`proposal_field`, `proposal_assessment`, `validation_class`, `proposal_note`, e.g. "the LLM found no defensible mapping (UNMAPPABLE)"), and the case carries a `review_reason` | `review/intake.py` (optional fields, backward-compatible) |
| A held case whose analyst **left a column unresolved** keeps the version REVIEW_REQUIRED (revisitable). Held with every column decided and a required field uncovered → RESUBMISSION_REQUIRED | `packages/service.py` |

**Unchanged:**
- CLEAR → auto-accept under the test-only policy (shipped policy DISABLED);
- PLAUSIBLE/AMBIGUOUS → proposal session;
- extra columns → header-count case;
- missing columns → resubmission;
- deterministic conflicts → conflict case.

UNMAPPABLE is never auto-accepted, no field is invented, nothing forces the analyst to map, deterministic validation is unchanged, and file-specific approvals still bind to one intake and SHA-256.

**Tests [T]** (`tests/test_unmappable_review_3b11.py`, all passing):

| # | Requirement | Test |
|---|---|---|
| 1 | UNMAPPABLE creates a review task | `test_1_…`: REVIEW_REQUIRED, case `UNMAPPABLE_PROPOSAL`, no session, `INTAKE_CASE_OPENED`, POC decision HUMAN_REVIEW (no POC_AUTO) |
| 2 | Case shows the unresolved column and reason | `test_2_…`: `ref_code` has no suggestion, LLM said UNMAPPABLE, class NO_MATCH, note and review reason, missing `payment_reference` |
| 3 | Manual map → full workflow completes | `test_3_…`: CHANGE `ref_code`→`payment_reference` → VALIDATED, preview = canonical IN-10, FM-CRC rule, package activated |
| 4 | Left unresolved → held | `test_4_…`: case HELD, version REVIEW_REQUIRED, no handoff, no preview folder, activation refused |
| 5 | Reject | `test_5_…`: REJECTED, `INTAKE_CASE_REJECTED`; resubmission still possible (v2 VALIDATED) |
| 6 | Invalid manual mappings refused | `test_6_…`: VALUE_INCOMPATIBLE (amount, entry_type), unknown field, DUPLICATE_TARGET, reason required, MAP refused for a column without a suggestion; IGNORE of the only source → RESUBMISSION_REQUIRED |
| 7 | No preview before resolution | `test_7_…`: no handoff, no rule, no reprocessing or preview events for B/C/D/E; only scenario A (auto) has a file mapping |
| 8 | Reprocessing + 14 checks after review | `test_8_…`: 14/14 PASS, events in order RESOLVED → REPROCESSED → HANDOFF_EVALUATED → HANDOFF_PREVIEW_WRITTEN, 0 provider calls |

**Existing tests updated (documented policy change, protective intent kept):**
- 3B-6 `test_explicit_unmappable_is_held_never_accepted` ×3 → `…goes_to_review_never_accepted`: HUMAN_REVIEW + case; no rule or preview.
- 3B-6 `in10_auto_invented`: removed from the blocking-cases list and replaced by `test_invented_canonical_field_goes_to_review_never_accepted`, because the validator classes an invented field as NO_MATCH.
- 3B-6.1 `test_case_c_equal_count_unmappable_column_holds_required_field` → `…goes_to_a_review_case`.
- eval_3b6 cases `invented_field` and `unmappable_A/B/C`: expected decision REJECT_OR_HOLD → HUMAN_REVIEW. The corpus was rebuilt and **only `manifest.json` changed**; the data files are byte-identical.

## 3. Mapping-screen inspection, and what was implemented

**Before [inspected]:**

| Application | Frontend | Mapping review? |
|---|---|---|
| Smart Parser | **none** (no UI, no API; FastAPI only an undeclared optional extra, not installed) | no |
| UC-042 (read-only) | React 19 + Vite + react-router, over the UC-042 FastAPI backend. Routes: packages, uploads, submissions, reconciliation, exceptions, review (exception/investigation ACCEPT/REJECT), packs, final packs, investigations, cases | **no column-mapping review anywhere** (no matches for mapping, canonical-field, IGNORE_COLUMN or column-review terms). Its "review" screens review reconciliation exceptions on a different backend and cannot drive PackageService |

Nothing could be reused safely, so a minimal POC screen was built in the Smart Parser.

**Implemented [I]:**

| Component | File | Notes |
|---|---|---|
| View / action layer | `smartparser/packages/review_api.py` | Reads stored state; forwards actions to PackageService (`decide`, `review_session`, `reject_review`, `complete_review`); no mapping, validation or lifecycle logic of its own; structured error codes (DUPLICATE_TARGET, VALUE_INCOMPATIBLE, RULE_CONTRADICTION, REASON_REQUIRED, NOT_AUTHORISED, PACKAGE_STATE, …) |
| HTTP server | `smartparser/review_ui/server.py` | **Standard library only** (`http.server`), bound to 127.0.0.1, single-threaded (single user). **No authentication:** the reviewer identity and authority policy are explicit start-up arguments. With the shipped production policy every action returns 403. The review never calls an LLM |
| Page | `smartparser/review_ui/static/{index.html, app.js, style.css}` | Vanilla JS; untrusted text (CSV headers, reasons) is only ever set via `textContent`; review queue → review screen → decision summary → outcome |
| Demo workspace | `tools/demo_3b11.py` | Scenarios A–F as single-category **TEST packages** (IN-10 only), with **recorded** proposal responses that mirror the 3B-10 live answers (no live calls) |

**Screen content (all from the backend):**
- **Header:** package, period, category and title, file and version, incoming/canonical counts, short SHA-256 (full on hover), review kind and state, version status, review reason.
- **Mapping table:** one row per position, showing incoming header, proposed field (or *Unmapped*), the basis and the LLM's own assessment, the validation class, the current decision and reason, and per-row actions.
  - **Case actions:** MAP, CHANGE (field selector), CHOOSE_DUPLICATE_SOURCE (only on duplicate claimants), IGNORE (mandatory row reason), LEAVE UNRESOLVED.
  - **Proposal-session actions:** MAP (confirm proposal), CHANGE, LEAVE UNRESOLVED. IGNORE and CHOOSE_DUPLICATE_SOURCE don't exist there and are not offered.
  - There is also a "Map all suggested (undecided)" button, which loops over the same per-row MAP endpoint.
- **Decision summary:** decisions made, outstanding columns, required fields not covered, ignored columns with reasons, left unresolved, duplicate headers, category conflict, and a finalisation forecast ("ready", "not possible yet", or "will HOLD").
- **Completion:** Complete review (with basis), Reject file (with reason).
- **Outcome:** version status, processing route, whether deterministic reprocessing ran, handoff eligibility, **all 14 handoff checks with PASS/FAIL and detail**, canonical preview link, provenance sidecar path, eligibility for package activation, package status, missing fields.

## 4. Screenshots and UI evidence [UI]

`tools/ui_browser_3b11.py` builds a fresh demo workspace, starts the server, and drives **headless Microsoft Edge over the DevTools protocol** using only the page's controls (select, type, click). It asserts the rendered DOM and cross-checks the final package-store state. Result: **13/13 steps passed** (`ui_evidence/ui_browser_results.json`). It also runs as a pytest test (`test_review_screen_in_a_real_browser`).

| File (`ui_evidence\`) | Shows |
|---|---|
| `01_review_queue.png` | queue of 4 tasks: UNMAPPABLE_PROPOSAL ×2, PROPOSAL_REVIEW, HEADER_COUNT_MISMATCH |
| `02_unmappable_review_before.png` | `ref_code` *Unmapped*, "LLM said UNMAPPABLE / no defensible mapping", NO_MATCH; reason and counts 8/8 |
| `03_invalid_mapping_refused.png` | CHANGE `ref_code`→`amount` refused by the backend: VALUE_INCOMPATIBLE |
| `04_unmappable_decisions_made.png` | 7 MAPs + manual CHANGE → `payment_reference`; "Required fields not covered: none" |
| `05_unmappable_resolved_outcome.png` | VALIDATED, reprocessing completed, **14/14 PASS**, preview generated, eligible for activation |
| `06_ambiguous_review_before.png` | proposal session: `value`→amount AMBIGUOUS, `reference`→payment_reference PLAUSIBLE; no Ignore offered |
| `07_ambiguous_resolved_outcome.png` | B confirmed → VALIDATED with 14 checks |
| `08_unmappable_left_unresolved_held.png` | D: `display_colour` LEFT UNRESOLVED → case HELD, REVIEW_REQUIRED, reprocessing not run, no preview, not activation-eligible |
| `09_extra_column_ignored_outcome.png` | E: IGNORE without reason blocked (REASON_REQUIRED); with reason → VALIDATED; provenance sidecar listed |
| `10_review_queue_after.png` | only D remains in the queue |

## 5. Analyst review scenarios and outcomes

| # | Scenario | Path | Outcome | Evidence |
|---|---|---|---|---|
| A | Clear LLM mapping | 3B-10 **live** run (real `gpt-6-luna` call) → AUTO_ACCEPT (test-only policy) → 14 checks → 17-category package activated → manifest | VALIDATED → snapshot `SNAP-001-23f8b80b` → reconciled in G | 3B-10 [live] + [RX] |
| B | Ambiguous LLM mapping | proposal session → screen → MAP both → complete | VALIDATED, 14/14, eligible | [UI][T] |
| C | Unmappable → manual map | `UNMAPPABLE_PROPOSAL` case → screen → CHANGE `ref_code`→`payment_reference` → complete → package activation | VALIDATED, 14/14, activated (`test_3`) | [UI][T] |
| D | Unmappable → left unresolved | case → LEAVE UNRESOLVED → complete | case HELD, REVIEW_REQUIRED, no preview, no handoff, activation refused | [UI][T] |
| E | Extra column | header-count case → IGNORE with reason → complete | VALIDATED; ignored column in provenance | [UI][T] |
| F | Missing column | header-count gate | RESUBMISSION_REQUIRED (`missing_fields: [currency]`), no LLM call | demo index [T]; 3B-10 live E |
| G | Complete package → reconciliation | adapter → real UC-042 engine | CLEAN, 0 exceptions; S05 gave 2 exceptions matching the answer key | [RX] §10–12 |

B–F used **recorded** responses (no live call). Their routing is deterministic given the proposal, and 3B-10 already captured the live model's answers for these shapes.

## 6. API / service integration details [I/T]

| Method | Path | Delegates to |
|---|---|---|
| GET | `/api/reviews` | `review_api.list_reviews` (package store: versions in REVIEW_REQUIRED) |
| GET | `/api/review/<pkg>/<ver>` | `review_api.review_detail` (case or session + registry fields + outcome) |
| POST | `/api/review/<pkg>/<ver>/decision` `{action, source_index, reason, canonical_field?, others_reason?}` | `PackageService.decide` (case) / `PackageService.review_session` (session) → `review.intake.decide` / `review.session.decide_column` |
| POST | `…/reject` `{reason}` | `PackageService.reject_review` |
| POST | `…/complete` `{basis}` | session: `review_session(approve=True)`; then `PackageService.complete_review` → `MappingOrchestrator.complete_case` / `complete_session` |
| GET | `…/outcome`, `…/preview` | stored version handoff summary; the canonical preview CSV |
| GET | `/api/identity` | the configured reviewer + authority policy (display) |

**API tests [T]** (no socket; `App.handle`):
- the queue and detail come from the store;
- an invalid CHANGE returns 400 `VALUE_INCOMPATIBLE`, and IGNORE without a reason returns 400 `REASON_REQUIRED`;
- completing with nothing decided returns 400;
- a full completion gives VALIDATED, 14 checks and the preview bytes equal to the canonical file;
- the session flow works, and IGNORE in a session returns 400 `UNSUPPORTED_ACTION`;
- with the production authority every action returns **403** `NOT_AUTHORISED`;
- unknown paths and versions return 404, and a VALIDATED version returns 409.

**Supporting change [I].** `HandoffSummary.checks` now stores all 14 check results (id, name, pass, detail) per version, so the outcome screen shows each check. It is a backward-compatible optional field.

## 7. UC-042 reconciliation input contract (read-only inspection)

| Aspect | UC-042 behaviour (`uc042lib.prepare`, `uc042lib.validate`) |
|---|---|
| Entry point | `prepare_case(input_dir, case_dir, period)` → `Validator(case_dir, period).run()` → `write_outputs(...)` (the `python -m uc042lib.prepare` / `validate` CLI does the same) |
| Evidence loading | **Files in a folder, identified by content only.** CSV: header must equal one schema's canonical column list (UTF-8, optional BOM). PDF: key-detail labels of one supporting document type. File names, extensions and **any manifest in the input are never trusted** |
| Required evidence | `schema.CSV_FILES` (14, all REQUIRED) + `PDF_FILES` REQUIRED (IN-15/16/17); a missing required type → intake `MISSING`; optional (IN-18/19) absent → `NOT_APPLICABLE` results |
| Reporting period | `PeriodConfig` (`PER-YYYY-MM`) given explicitly, else from the single IN-01 calendar; canonical file names per period (`FILE_PATTERNS`); the README states the engine supports **September 2026 only** |
| Account inventory / letters | IN-15/16 have identical labels; the slot is chosen by matching the letter reference to IN-02 `acknowledgement_letter_ref` (`schema.LETTER_SLOTS`) |
| Policy | IN-17 accepted only as a recognised version with its markings; selection in `policy_selection.json` |
| Cross-file relationships | resolved inside the validator (cash book ↔ bank entries by reference, IN-14 → IN-05/IN-06 recon refs, settlement batches ↔ lines, …) |
| Results | `case_dir/validation/control_results.csv`, `exceptions.csv`, groups and candidates, `document_details.csv`, `VALIDATION_REPORT.md`; `case_status` CLEAN / EXCEPTIONS_OPEN |
| Isolation | the core imports only the standard library + its own modules; no `.env`, no database, no network; writes only to `case_dir`. The README warns never to run `validate` on the delivered dataset folders: the adapter never does |
| Existing harness | the `prepare` → `validate` CLI pair (no other test harness needed) |

## 8. Manifest-to-engine compatibility findings [INT]

| Smart Parser output | UC-042 expected input | Compatible? | Required transformation |
|---|---|---|---|
| Snapshot manifest JSON | none: the engine builds its own `manifest.csv` / `intake.csv` and ignores input manifests | **Not consumed by the engine** | Used by the adapter only: select and verify the exact versions; kept for traceability |
| Canonical preview CSV (canonical header and column order, source cells unchanged, UTF-8, comma, LF, header on line 1) | CSV with exactly the canonical header, UTF-8 | **Yes**: all 14 CSVs ACCEPTED; engine case bytes = staged bytes | none (copied as-is; the filename is irrelevant) |
| Original upload CSV with unfamiliar headers (e.g. 3B-10 IN-10 `cash_book_entry_id`, …) | — | **No** (would be REJECTED: header mismatch) | the preview must be used, never the raw upload |
| Original PDFs IN-15/16/17 | readable PDF with key-detail labels; letters via IN-02; recognised policy | **Yes**: ACCEPTED (letters resolved through the staged IN-02) | none (original bytes) |
| Optional IN-18/19 | optional | not in the 3B-10 package | engine: 4 NOT_APPLICABLE results (`optional file not provided`) |
| `reporting_period` `2026-09` | `PER-2026-09` | **Yes** | prefix `PER-` |
| File version / intake / source SHA-256 | not used by the engine | n/a | traced in `reconciliation_run.json` (engine canonical file name → category, version, intake, source SHA, staged SHA) |
| Provenance sidecar | not consumed | n/a | referenced by the manifest |
| Ignored columns (excluded from previews) | n/a: canonical previews contain canonical columns only | **Yes** | none |
| Months other than September 2026 | engine limitation | not tested | owner/engine decision |

## 9. Adapter implementation [I/T/INT]

`smartparser/reconciliation/uc042_adapter.py` → `run_reconciliation(svc, package_id, snapshot_id, uc042_root, out_dir)`:
1. **Refuses unsafe runs:**
   - an output folder inside the UC-042 tree;
   - a snapshot that isn't the **active** one (a superseded selection is never reconciled);
   - a failed `verify_snapshot` (SV-1…SV-5);
   - an existing run folder (write-once).
2. **Verifies inputs:** each selected original's SHA-256 and intake record, that the version is ACTIVE and is the slot's active version, and each preview's hash.
3. **Stages** exactly those versions: canonical preview for CSVs, original bytes for PDFs.
4. **Runs the existing engine unchanged** in a separate Python process (`-B`, `PYTHONDONTWRITEBYTECODE=1`, UC-042 / provider environment variables removed). The UC-042 tree is only on `sys.path`; the working directory and all outputs are inside the run folder.
5. **Verifies the engine** accepted every staged file, with the same category and the exact same bytes.
6. **Writes `reconciliation_run.json`** (inputs, engine intake, results, exceptions, groups, candidates, output hashes, traceability) and audits `RECONCILIATION_INPUT_STAGED` / `RECONCILIATION_EXECUTED` (or `RECONCILIATION_FAILED`). These are 3 new event types.

It reproduces no reconciliation rule or calculation, changes no evidence, invents nothing, re-runs no mapping, and submits or publishes nothing (no audit pack is generated).

**Tests [T]** (`tests/test_reconciliation_3b11.py`; they need the UC-042 tree and are skipped without it):
- **real engine, isolated:** CLEAN with exactly 1,882 PASS and 4 NOT_APPLICABLE; adapter checks all true; traceability of IN-10 to its version, intake and SHA; audit events; write-once;
- **refusals:** output inside UC-042, non-active snapshot, tampered preview (SV-3); and `uc042lib` file mtimes unchanged.

## 10. Exact isolated reconciliation execution evidence [RX]

**Main run (complete package from 3B-10 Scenario A, whose IN-10 was mapped by the live LLM):**

| Item | Value |
|---|---|
| Tool | `tools/reconcile_3b11.py` (copies the 3B-10 workspace to `reconciliation\workspace`; the 3B-10 evidence is untouched) |
| Package / snapshot | `PKG-2026-09-2276e4` / **`SNAP-001-23f8b80b`** (selection SHA in `reconciliation_run.json`) |
| Run ID | **`RECON-20261118T192518Z-23f8b80b`** (`reconciliation\runs\…\reconciliation_run.json`) |
| Engine | `uc042lib.prepare.prepare_case` + `uc042lib.validate.Validator.run` + `write_outputs`, unmodified, imported read-only from `p10\uc042_token_optimisation`; Python 3.11; exit 0; period `PER-2026-09` |
| Engine intake | **17/17 ACCEPTED** (IN-01…IN-17); 0 rejected, ambiguous or missing; engine case bytes = staged bytes for all 17 |
| Snapshot verification | SV-1…SV-5 pass; all source and preview hashes re-verified before staging |
| UC-042 files written | **0** (files newer than the run start) |
| Audit | `RECONCILIATION_INPUT_STAGED`, `RECONCILIATION_EXECUTED`; chain verified (122 events) |

**Control.** The same engine ran on the **original canonical fixture files** for the same 17 categories (no Smart Parser involved): `control_results.csv`, `exceptions.csv`, `VALIDATION_REPORT.md`, `manifest.csv` and every case file are **byte-identical** to the Smart Parser run. Reconciling through Smart Parser changed no engine result.

**Scenario run with known discrepancies** (`tools/reconcile_scenario_3b11.py`):
- The 19 files of `uc042_dataset/scn_S05_unexplained_gbp_difference` were read, never written, and submitted with **no declared categories** to a new Smart Parser package. All 19 were VALIDATED by content; snapshot `SNAP-001-84900ff8` was activated.
- Run **`RECON-20261118T192523Z-84900ff8`**.
- **UC-042's own `compare_answer_key`: `matched: true`, no differences.** The answer key and the scenario's ID-prefix metadata (`scenario.json`) were copied into a *separate check copy* of the case only. Without `scenario.json` the engine names exceptions `EXC-CASE-nn` instead of `EXC-S05-nn`, which is the only difference a plain comparison shows.
- The control on the dataset's original files is byte-identical.

## 11. Reconciliation run IDs and snapshot IDs

| Run | Snapshot | Package | Input |
|---|---|---|---|
| `RECON-20261118T192518Z-23f8b80b` | `SNAP-001-23f8b80b` | `PKG-2026-09-2276e4` | 3B-10 Scenario A complete package (17 required; IN-10 via live LLM mapping) |
| `RECON-20261118T192523Z-84900ff8` | `SNAP-001-84900ff8` | (new, in `reconciliation\scn_S05…\workspace`) | UC-042 scenario S05, 19 files |
| `CONTROL-original-fixture-files` / `CONTROL-original-dataset-files` | — | — | same engine on the original files (comparison only) |

(Earlier identical runs were made while developing and then replaced; the IDs above are the final evidence.)

## 12. Actual reconciliation results and discrepancies [RX]

**Main run:**
- **case_status CLEAN**; **1,886** check results: 1,882 PASS, 4 NOT_APPLICABLE; **0 exceptions**, 0 investigation groups, 0 candidates.
- The 4 NOT_APPLICABLE results are UC-042's own handling of the optional IN-18/IN-19 documents not being in the package: `V00-FILE` ×2 ("optional file not provided") and `C16-GOVERNANCE` / `C16-RETURN` ("optional evidence not provided").
- Zero discrepancies is the genuine result for the synthetic clean baseline; it was not assumed.

**S05 run:**
- **case_status EXCEPTIONS_OPEN**; 1,887 results: 1,874 PASS, **13 FAIL**; **2 exceptions** in one investigation group:

| Exception | Severity | Category | Account / amount / period | Cited evidence traced to Smart Parser versions |
|---|---|---|---|---|
| EXC-CASE-01 | Critical | Unexplained bank-ledger difference | SGA-GBP-01, −812.40, 2026-09-17…30 (11 results; evidence status NOT_EVIDENCED) | IN-07, IN-14, IN-06 file versions (IDs, intakes and SHA-256 in `scenario_summary.json`) |
| EXC-CASE-02 | High | Bank entry with no counterpart | SGA-GBP-01, −812.40, 2026-09-17 (2 results) | IN-09 file version |

**Traceability:** each engine output cites `IN-xx:<canonical file>#L<line>`. `reconciliation_run.json` maps each canonical file to package, snapshot, file version, intake ID, source SHA-256 and staged SHA-256.

## 13. Full regression results (`evidence/regression_summary.txt`)

| Check | Result |
|---|---|
| Full suite | **585 passed** (568 + 17 new); without the UC-042 tree 580 passed, 5 skipped (the 3 earlier + the 2 real-engine adapter tests) |
| Per phase | **3B-11 17** (14 UNMAPPABLE/API + 2 real-engine adapter + 1 real-browser), 3B-10 15, 3B-9 41, 3B-8 21, 3B-7 35, 3B-6.1 18, 3B-6 43, 3B-5 16, 3B-4 14, 3B-3 15, 3B-2 23, 3B-1 40, 3B-0 117, Phase 1+orig 136, Phase 2 34 |
| Evaluations | eval_3b5 **68/68**, eval_3b6 **34/34** |
| Registry / baseline / corpus | in sync (19) / 445/445 / 161/161 |

No live LLM call was made in 3B-11.

## 14. Security and isolation verification

| Check | Result |
|---|---|
| UC-042 source | 107 code + 624 dataset files hash-identical; **0 files newer** after every engine run; only imported (bytecode off) and datasets only read |
| Original UC-042 app / active demo database / audit packs / Clone E | not used: the engine core is file-based; no app, no database, no pack generation or publication |
| Desktop Smart Parser | 63 files hash-identical |
| 3B-10 evidence | not modified (the reconciliation used a copy) |
| Submission | none; `submit_to_uc042` unchanged; no audit pack generated |
| POC policy / provider / production authority | `DISABLED` / AI default off / scopes `{}`, all unchanged |
| Review server | 127.0.0.1 only, single-user, no authentication (POC); identity fixed at start-up; production authority → 403; untrusted text never rendered as HTML |
| Credentials | none used in 3B-11; engine subprocesses run with UC-042 and provider environment variables removed |

## 15. Limitations and blocked acceptance criteria

**No acceptance criterion is blocked.** Limitations:
1. **Correction to the 3B-10 report.** It stated that colour codes mapped to `payment_reference` "would still have failed the field's ID pattern (VALUE_INCOMPATIBLE)". **That was wrong.** `payment_reference` is free text (`str`, no pattern) in the UC-042 contract, so no deterministic value rule backs it up.
   - Consequence: for free-text target fields, a confident but semantically wrong CLEAR proposal would pass validation and could be auto-accepted under the **test-only** policy. The shipped policy is DISABLED, so a person always decides.
   - In review, mapping colour codes to `payment_reference` is not refused; it is the analyst's judgement (scenario D leaves it unresolved).
   - An owner decision is needed: should free-text fields ever be auto-acceptable?
2. **Equal-count UNMAPPABLE always leaves a required field uncovered** (every UC-042 column is header-required). So an UNMAPPABLE case resolves only if the analyst maps the column to that field; otherwise it ends held, rejected or ignored, leading to resubmission.
3. **Review screen POC.** No authentication; single user; a TEST reviewer identity under the test-only authority policy, because production authority authorises nobody (owner decision). It is not integrated with the UC-042 frontend. Tested in Edge only.
4. **The reconciliation is the engine's controls and exceptions only.** No audit pack, investigation, final pack or UC-042 app/database workflow was run. The engine supports September 2026 only (UC-042 README), and only synthetic data was used.
5. **Cases opened before 3B-11 lack the new proposal fields** (they render as no proposal information); no migration is needed.
6. **Unchanged from earlier phases:** PDFs classification-only; single-user stores without cross-process locking; equal-count duplicate-claim files cannot be completed (3B-8 decision pending).

**Files created:**
- `smartparser/packages/review_api.py`
- `smartparser/review_ui/{__init__.py, server.py, static/index.html, static/app.js, static/style.css}`
- `smartparser/reconciliation/{__init__.py, uc042_adapter.py}`
- `tools/{demo_3b11.py, ui_browser_3b11.py, reconcile_3b11.py, reconcile_scenario_3b11.py}`
- `tests/{test_unmappable_review_3b11.py, test_reconciliation_3b11.py}`
- this report

**Files modified:**
- `smartparser/orchestration/{policy.py, orchestrator.py}`
- `smartparser/review/{intake.py, audit.py}`
- `smartparser/packages/{models.py, service.py}`
- `pyproject.toml` (package-data for the static files)
- `tests/{test_orchestration_3b6.py, test_conflict_protection_3b61.py}`
- `tools/eval_3b6.py`, `corpus/phase3b6_eval/manifest.json`
