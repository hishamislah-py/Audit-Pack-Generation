> Appendix 22E to report 22 (`22_COMPLETE_UC042_PRODUCT_AND_WORKFLOW_WALKTHROUGH.md`). Read-only code trace of the Phase 8 working tree, 5 November 2026. Nothing was executed against live data; file:line references are to `uc042/`.

# Part D: Analyst workflow, the backend checks at each stage, and what starts the next stage

Source: the code in `C:/Users/artlptp263user/Downloads/UC042_CLAUDE_CODE_HANDOFF/uc042`, read on 5 Nov 2026. Paths are relative to that folder. When this note and the docs disagree, the code wins.

How to read the refusals:
- Each refusal is written as **HTTP status `CODE`** followed by `file:line`. Error classes (`uc042app/errors.py`): InvalidInput is 422, NotFound 404, Conflict 409, IntegrityFailure 409, ServiceUnavailable 503. The default `code` for a 422 is `VALIDATION_ERROR`.
- Every ID in a request is checked against its pattern before anything is stored (`uc042app/ids.py:24-27` → 422 `INVALID_ID`).
- The UI only *disables* buttons. **The backend is what enforces each rule.**
- Every monthly and case endpoint first needs the database: **503 `DATABASE_REQUIRED`** (`services/monthly.py:94-97`, `services/cases.py:37-40`).

---

## D.0 The main objects: definitions, ID formats and states

| Object | What it is (from the code) | ID format | States / status values |
|---|---|---|---|
| **Reporting period** | One calendar month of the safeguarding reconciliation. It is the key everything else hangs off, and its ID is fixed once created. It is a database row only and creates no data inside it (`services/monthly.py:121-138`; model `db/models.py:32`). | `PER-YYYY-MM`, built from the year and month by `ingest/analysis.py:56-57` and checked by `parse_period` (line 60, year 2000-2100, month 01-12). The engine checks again with `period.PeriodConfig.from_id` (`uc042lib/period.py:158`). | Stored `status`: EMPTY → DOCUMENTS_UPLOADED → PROCESSING → PROCESSED or PROCESSING_FAILED (`models.py:39`). Calculated `reporting_status` (`routers/monthly.py:150-158`): NO_DATA, DOCUMENTS_UPLOADED, VALIDATION_REQUIRED, DETERMINISTIC_PACK_AVAILABLE, INVESTIGATION_AVAILABLE, FINAL_PACK_PUBLISHED, ADDITIONAL_EVIDENCE_RECEIVED. Calculated `archive_state` (line 119): AWAITING_UPLOAD, DOCUMENTS_NO_RESULTS, RESULTS_NO_FINAL_PACK, RESULTS_AND_FINAL_PACK. `title` can be changed (3-120 characters); if no title is stored, it is shown as "<Month> <Year> Reconciliation Audit" (line 74-80). |
| **Source document** | One file uploaded for a period, or one POC dataset file registered where it already sits. The bytes are kept in the document store, addressed by their content. The database row holds the metadata, the content-based classification, the checks and the analyst's decision (`models.py:98`). | `DOC-<24 hex>` (`ids.new_id("DOC")`, `monthly.py:369`; pattern line 50) | `validation_status`: VALID, WARNING or ERROR (`analysis.status_of`, line 330). `review_decision`: none, INCLUDE or EXCLUDE. `submission_kind`: INITIAL, ADDITIONAL_EVIDENCE or CORRECTION. `evidence_id`: IN-01..IN-19 or null. `file_format`: CSV, PDF or OTHER. |
| **Upload batch** | The set of files sent in one upload (up to 60), validated together and confirmed together (`models.py:81`). | `UPL-<24 hex>` (`monthly.py:47, 357`) | `status`: VALIDATED → CONFIRMED → PROCESSING → PROCESSED or PROCESSING_FAILED. ARCHIVED_SCENARIO is used for POC imports. `validation_status`: VALID, WARNINGS, INCOMPLETE or INVALID (`_summarise`, `monthly.py:568-576`). `origin`: UPLOAD or POC_DATASET_IMPORT. |
| **Deterministic reconciliation (processing run)** | One run started by the analyst. It applies the deterministic engine to the period's current confirmed document set and runs in a PROCESSING background job (`monthly.py:678-726`, `_process` line 756). A retry is always a new run. | `RUN-<24 hex>` (`monthly.py:51, 707`). This is different from the engine's own `processing_run_id` inside a pack, which is `RUN-<16 hex of sha>` (`uc042lib/pack/model.py:82-84`). | `status`: QUEUED → RUNNING → SUCCEEDED or FAILED, or INTERRUPTED after a restart (`monthly.py:1068-1083`). BLOCKED exists in the schema (`api/schemas.py:447`) but no current code sets it. `result.purpose`: INITIAL or REASSESSMENT. |
| **Reconciliation pack (deterministic pack)** | The engine's verified output for one case folder, written once and never changed: `pack.json` (canonical), `pack.html`, `processing/*.csv` and `generations/*.json`. Its content includes the executive summary, control register, exception register, evidence register and missing-evidence register. It is linked to its period in `audit.period_packs`. | `PACK-<scenario 1-12 [A-Z0-9]>-PER-YYYY-MM-<12 hex of the content hash>` (`investigation/config.py:116`; built by `pack/model.py:50-51`). The scenario is `CASE` for uploads (`validate.py:1474-1477`), `S01`, `SC2` and similar for September, and `H2026MM` for history. | It has no status of its own. `engine_case_status`: CLEAN, EXCEPTIONS_OPEN or EVIDENCE_INCOMPLETE (`validate.py:1492-1501`). `pack_kind`: HISTORICAL_MONTHLY, DEMONSTRATION_SCENARIO or UPLOADED_DOCUMENTS (`services/packs.py:97-106`). `period_packs.origin`: POC_SCENARIO or UPLOAD_PROCESSING. |
| **Exception** | A failed control, or a group of failed controls with the same root cause, raised by the engine inside a pack. It is read-only: no endpoint changes it (`routers/packs.py:1`). | `EXC-<scenario>-NN` (`validate.py:1302`; pattern `investigation/config.py:117`, 2-3 digits) | `status`: OPEN (`validate.py:1280`). `review_status`: AWAITING_HUMAN_REVIEW (line 1293). `evidence_status` comes from the C08 evidence (for example TIMING_EVIDENCED or TIMING_PARTIAL, lines 1288-1296). These values never change after the engine sets them. |
| **Investigation** | One AI (V2 tools-mode) analysis of one exception, saved write-once as files and registered in the publication registry. Failed or rejected attempts go to `_not_published/` (`uc042lib/investigation/persistence.py:169-200`). | `INV-EXC-<scenario>-NN-<12 hex>` (`final_pack/sources.py:17`), derived from the findings and the packet hash (`persistence.py:31-35`). The job that produces it is `JOB-<24 hex>`. The pre-run authorisation is `AIA-<24 hex>` (`ids.py:14, 16`). | Artefact: `investigation_status` COMPLETED with `validation_status` VALID (otherwise it is not published). Registry `record_type`: NEW_PUBLICATION or LEGACY_BASELINE_IMPORT. Authorisation decision: APPROVED or AUTHORIZATION_DISCREPANCY. Calculated `eligible` true/false with reasons (`services/investigations.py:64-111`). Job: QUEUED, RUNNING, then COMPLETED, FAILED or INTERRUPTED. |
| **Exception case** | The analyst's own, explicitly opened record of investigating one exception in one pack. It keeps an append-only history and has a human resolution. It never changes the pack (`services/cases.py:1-14`). There is at most one per (pack, exception) (`models.py:273`). | `CASE-<24 hex>` (`ids.py:15`). Entries are `CE-<24 hex>` (`cases.py:159`). | `status`: OPEN or CLOSED. `human_resolution`: UNRESOLVED (start), EXPLAINED_BY_ANALYST or ESCALATED (`cases.py:26-28`). `revision` is an integer used for optimistic locking. Entry kinds: NOTE, EVIDENCE, EVIDENCE_GAP, OBSERVATION, HYPOTHESIS, DECISION, plus AI_REQUEST, which only the system writes (`cases.py:22-24`). |
| **Closing summary** | The AI-written summary for the final review. It is built from the review snapshot (the deterministic pack plus the selected investigations) in the PREVIEW job, checked against its input, and stored with the preview. GENERATE reuses it unchanged (`final_pack/summary.py:199-230`; `services/reviews.py:260-295, 369`). | It has no ID of its own. It is identified by `summary_sha256` and `source_fingerprint`, and is stored inside the preview `PV-<24 hex>` (`ids.py:13`). | `status`: GENERATED or UNAVAILABLE. UNAVAILABLE means the provider failed or is not configured, there is no text, and GENERATE then needs an explicit acknowledgement (`final_pack/model.py:139-142`; `reviews.py:356-358`). |
| **Final audit pack** | The published, write-once report for one deterministic pack, made on a GENERATE decision: `final_pack.json`, `report.html`, `report.pdf` and `manifest.json`. Versions are numbered across the period's reassessment lineage, and each new version names the one it supersedes (`services/final_packs.py:1-8, 60-65`). | `FAP-<scenario>-PER-YYYY-MM-v<n>-<12 hex>` (`final_pack/model.py:23`; built by `final_pack/assemble.py:211-212`). Previews are `PREVIEW-<scenario>-<period>-<12 hex>` and are never published. | `metadata.status`: GENERATED (a preview is PREVIEW, `assemble.py:149`). Generation record (`audit.final_pack_records`): GENERATING, then GENERATED or GENERATION_FAILED. |

Related IDs:
- Review session `RS-<24 hex>`.
- Review decision `RD-<24 hex>`.

Review session states (`services/reviews.py:6, 30-31`):
- `OPEN` ⇄ `ON_HOLD`
- `OPEN` → `GENERATING` → `GENERATED`, or `GENERATION_FAILED`, which can be edited again.

There is one active session per pack. The active states are OPEN, ON_HOLD, GENERATING and GENERATION_FAILED.

---

## D.1 Create or select a period
- **Endpoint**: `POST /api/v1/periods {year, month, title?}` → `routers/monthly.py:177` → `MonthlyService.create_period` (`services/monthly.py:121-138`).
- **Checks**:
  - The request body is checked first: `year` 2000-2100 and `month` 1-12 (`api/schemas.py:329-332`), otherwise 422 `VALIDATION_ERROR`. The service checks the same range again (`monthly.py:127-128`, 422).
  - **No future month**: 422 `FUTURE_PERIOD` (`monthly.py:130-131`). The current month and any past month back to the year 2000 are allowed.
  - A title, if given, must be 3-120 characters after spaces are collapsed: 422 `INVALID_TITLE` (`monthly.py:115-119`).
  - If the month already exists, the existing period is returned unchanged with HTTP 200. A second period for the same month is never created, and the title is not changed (`routers/monthly.py:181-183`).
- **Which months can be processed** is a separate question from which months can be opened. `processing_supported(period_id)` / `processing_limitation` (`monthly.py:55-71`) need a valid period with at least one registered policy version that applies (`policy.applicable_versions`). The registered versions are v1.1, effective 2025-10-01, and v1.2, effective 2026-05-07 (`uc042lib/policy.py:39-48`). So **October 2025 and later** can be processed, and earlier months show a limitation message. The backend does not block opening or uploading for those earlier months. Processing them fails through the policy check (IN-17 is marked POLICY_NOT_APPLICABLE, an ERROR, so it is never usable, so the run stops with 409 `INCOMPLETE`). The UI also disables the Process button (`pages/ArchivePages.tsx:52, 59`).
- **Rename**: `PATCH /periods/{id} {title}` → `rename_period` (`monthly.py:140-153`). An empty title gives 422 `INVALID_TITLE`. An unknown period gives 404. The period ID never changes.
- **Selecting a period** reads `GET /periods` and `GET /periods/{id}` (`period_detail`, `monthly.py:159-168`). This returns the `current_set`, `missing_required`, `processing_supported` and `processing_limitation`.
- **Next stage**: the analyst uploads documents. The upload page opens the period first if it is not yet in the archive (`pages/UploadPage.tsx:50`).

## D.2 Upload documents
- **Endpoint**: `POST /api/v1/periods/{id}/uploads`, multipart with `files[]`, `submission_kind`, `reason` and `replaces_document_id` → `routers/monthly.py:200-211` → `MonthlyService.upload` (`monthly.py:341-390`).
- **Checks before anything is stored**:
  - Period ID format: 422 `INVALID_ID`. Unknown period: 404 (`_period`, `monthly.py:99-107`).
  - No files: 422 `NO_FILES` (line 348-349).
  - Submission rules (`_submission`, lines 322-339):
    - the kind must be INITIAL, ADDITIONAL_EVIDENCE or CORRECTION, otherwise 422 `INVALID_SUBMISSION`;
    - a non-INITIAL submission needs a reason of at least 3 characters, otherwise 422 `REASON_REQUIRED`;
    - `replaces_document_id` is allowed only on a CORRECTION, otherwise 422 `INVALID_SUBMISSION`;
    - a CORRECTION must be exactly one file and must replace an earlier `DOC-` of the **same period**, otherwise 422 `INVALID_SUBMISSION`.
  - **Size limits**: at most **60 files** per batch (422 `TOO_MANY_FILES`) and **50 MB per file** (422 `FILE_TOO_LARGE`) (`MAX_FILES` and `MAX_FILE_BYTES`, lines 45-46 and 351-355). The router reads at most 50 MB + 1 byte of each file (`routers/monthly.py:208`). The total batch size has no limit beyond 60 × 50 MB. No limit is set at the web-server level (UNCONFIRMED).
- **Accepted file types**: the file's **content** decides, not its name (`uc042lib/prepare.py:63-85` `identify`):
  - **PDF** (starts with `%PDF-`): it must contain the key-detail labels of one of the PDF types IN-15..IN-19. Otherwise it is rejected with "PDF without the key details of any supported document type".
  - **UTF-8 CSV**: the header must match one of IN-01..IN-14 exactly. Otherwise `diagnose_header` explains what is missing, extra, out of order or wrongly cased or spaced.
  - **XLSX/ZIP** is rejected ("export as CSV"). Anything else is rejected.
  - A rejected or unreadable file is still **stored** and recorded as an ERROR document (`UNRECOGNISED` or `UNREADABLE`, `monthly.py:361-368`; `analysis.py:286-293`). An empty file gives `EMPTY_FILE` ERROR (`analysis.py:283-284`).
- **Classification into the 19 evidence types** (`uc042lib/schema.py:15-209`). IN-01..IN-17 are required and IN-18..IN-19 are optional (`ingest/analysis.py:50-51`):
  - **CSV**: IN-01 reconciliation calendar, IN-02 account inventory, IN-03 client balance snapshots, IN-04 unallocated receipts, IN-05 internal reconciliation records, IN-06 external reconciliation records, IN-07 bank balance confirmations, IN-08 end-of-day statement headers, IN-09 statement entries, IN-10 safeguarding cash book, IN-11 client transactions, IN-12 settlement batches, IN-13 settlement lines, IN-14 discrepancy log.
  - **PDF**: IN-15 and IN-16 acknowledgement letters (SGA-GBP-01 and SGA-EUR-01), IN-17 reconciliation policy, IN-18 governance register (optional), IN-19 previous month's return receipt (optional).
  - **Letters**: IN-15 and IN-16 have the same key details. `_resolve_letters` (`monthly.py:440-478`) matches the letter reference against IN-02's `acknowledgement_letter_ref`, looking first in this batch, then in the period's current set, then in the verified baseline IN-02 of the period's pack (`reference_baseline`, line 418). If none matches: `LETTER_NOT_MATCHED` ERROR. A letter is never assigned by guessing.
  - **Policy (IN-17)**: `analyse_policy` (`analysis.py:249-274`). The version must be recognised and its effective date must equal the registered one, otherwise `POLICY_NOT_RECOGNISED` ERROR. It must apply to the month, otherwise `POLICY_NOT_APPLICABLE` ERROR. Info messages: POLICY_VERSION, ILLUSTRATIVE_SYNTHETIC_POLICY, POLICY_SELECTED or POLICY_SUPPLIED_NOT_SELECTED (an approved selection, e.g. PER-2026-05 → v1.2, HD-2, `policy.py:50-55`). Each policy version takes its own slot, `IN-17@vN.N` (`analysis.slot`, line 323).
  - **ADDITIONAL_EVIDENCE**: a readable but unrecognised file becomes "Supporting evidence (not a reconciliation input)" with a `SUPPORTING_EVIDENCE` WARNING instead of an ERROR (`monthly.py:397-406`).
- **Content and date checks** (`analysis.analyse_csv`, lines 114-230):
  - Each date column is labelled with its meaning (`DATE_ROLES`). Only the column(s) that decide which month a record belongs to (`schema.PERIOD_RULES`) are judged against the selected month.
  - **WRONG_PERIOD** ERROR when no record falls in the month (line 194-196), or when the IN-01 `period_id` is not this period (line 186-188).
  - **OUT_OF_PERIOD_RECORDS** WARNING (line 197-200). The records stay where they are, and the engine excludes and reports them.
  - **BOUNDARY_RECORDS** INFO for the previous month-end opening points of IN-03 and IN-10 (line 96-104 and 201-203).
  - **TIMING_DIFFERENCE** INFO for dates outside the month in columns that do not decide the period (line 204-208).
  - INVALID_DATE and MISSING_DATE warnings. **REPEATED_RECORD_ID** WARNING for repeated first-column keys.
  - **NO_RECORDS**: INFO for IN-04 and IN-14, which may be empty (`schema.EMPTY_ALLOWED`, line 270), otherwise ERROR.
  - `CALENDAR_*` warnings come from comparing against the England and Wales calendar (line 190-192).
  - PDFs: IN-19 must be the previous month's return, otherwise WRONG_PERIOD WARNING (line 238-243). `PDF_STORED_AS_ORIGINAL` INFO.
- **Duplicate detection** (`_duplicates`, `monthly.py:494-549`). A flag never removes a file. Flags marked "decision" set `checks.decision_required`:
  - `DUPLICATE_IN_BATCH`, WARNING, decision: the same SHA-256 appears twice in this batch.
  - `DUPLICATE_OF_EARLIER_UPLOAD`, WARNING, decision: the same SHA-256 was already uploaded for this period.
  - `SAME_NAME_DIFFERENT_CONTENT`, WARNING, decision: the same file name was uploaded earlier with different content. Both are kept.
  - Identical SHA-256 already uploaded for **another** period:
    - **`HEADER_ONLY_SAME_AS_OTHER_PERIOD`**, INFO, **no decision** (lines 518-523): for a CSV that is identified, has `record_count == 0` and matches another month's file. Empty files of one type are identical in every month, so equal hashes prove nothing.
    - `RECURRING_DOCUMENT`, INFO, no decision: for IN-02, IN-15, IN-16, IN-17 and IN-18 (standing data, `analysis.RECURRING_IDS`, line 53).
    - otherwise `SAME_CONTENT_AS_OTHER_PERIOD`, WARNING, **decision**.
  - `NEW_VERSION`, INFO, no decision: a different version of the same CSV type exists earlier in this period. The message reports how many record IDs overlap, and the new one replaces the old one for future runs once included and confirmed.
  - `AMBIGUOUS_EVIDENCE_TYPE`, WARNING, decision: two or more different files in this batch identify as the same slot.
- **How the upload was submitted** (`_submission_checks`, lines 393-416): `REPLACES_DOCUMENT` INFO, `REPLACEMENT_TYPE_DIFFERS` WARNING, and `RECEIVED_AFTER_PUBLICATION` INFO (the period already has published final packs, so a reassessment is pending).
- **Result**: each document gets VALID, WARNING or ERROR (`status_of`). The batch is created with `status=VALIDATED`. `_summarise` (lines 551-576) computes `validation_status`:
  - INVALID if every document has an error;
  - otherwise INCOMPLETE if required IDs are missing from the combined set (confirmed batches plus this one);
  - otherwise WARNINGS if there are warnings, errors or decisions pending;
  - otherwise VALID.
  - The period status changes from EMPTY to DOCUMENTS_UPLOADED.
- **Include / exclude**: `POST /documents/{id}/review {decision, comment}` → `review_document` (`monthly.py:602-621`).
  - The decision must be INCLUDE or EXCLUDE (422). The comment must be at least 3 characters: 422 `COMMENT_REQUIRED` (also checked by the schema, `schemas.py:479-481`).
  - Only while the batch is VALIDATED: otherwise 409 `BATCH_CONFIRMED`.
  - INCLUDE of an ERROR document: 409 `DOCUMENT_HAS_ERRORS`.
  - Nothing is deleted. The decision is recorded with who made it and when, and the batch summary is recomputed.
  - A document can be used (`_usable`, line 172-174) when it is not an ERROR, is not EXCLUDED, has an evidence type, and either needs no decision or was INCLUDED.
- **Next stage**: confirm the batch.

## D.3 Confirm the batch
- **Endpoint**: `POST /uploads/{batch_id}/confirm` → `routers/monthly.py:219` → `MonthlyService.confirm` (`monthly.py:623-646`).
- **Checks**:
  - The batch ID must match `UPL-<24hex>` (422 `INVALID_ID`) and exist (404) (`batch_detail`, line 578-585).
  - Already confirmed (status is not VALIDATED): 409 `BATCH_CONFIRMED`.
  - `validation_status == INVALID`: 409 `BATCH_INVALID`.
  - Decisions still pending: 409 `DECISIONS_PENDING`, with `extra.documents`.
  - More than one usable document for the same slot: 409 `AMBIGUOUS_EVIDENCE_TYPE`, with `extra.evidence_types`.
  - An INCOMPLETE batch **can** be confirmed. Completeness is checked when processing starts.
- **Effect**: status becomes CONFIRMED with `confirmed_at` and `confirmed_by`. The period's `current_set` is then the latest usable document of each type across confirmed batches, in confirmation order (`current_set`, lines 176-200). Earlier versions are kept but replaced.
- **Next stage**: processing (D.4).

## D.4 Process (deterministic reconciliation run)
- **Endpoints**:
  - `POST /uploads/{batch_id}/process` → `process()` (`monthly.py:678-726`), used by the batch page.
  - `POST /periods/{id}/reconciliation {purpose, reason}` → `reconcile()` (`monthly.py:653-676`), which picks the latest confirmed UPLOAD batch and calls `process()`.
  - Processing never starts automatically: not at startup, not on upload, and not on any other change (`monthly.py:654-656`).
- **Checks**:
  - `reconcile()` only: `purpose` must be INITIAL or REASSESSMENT (422 `INVALID_PURPOSE`). For REASSESSMENT, evidence must have arrived after publication (`pending_reassessment`), otherwise 409 `NOTHING_TO_REASSESS`, and a reason of at least 3 characters is needed (422 `REASON_REQUIRED`). A confirmed UPLOAD batch must exist, otherwise 409 `NO_CONFIRMED_DOCUMENTS` (lines 662-675).
  - Batch still VALIDATED: 409 `BATCH_NOT_CONFIRMED` (line 684-685).
  - A run for the period is already QUEUED or RUNNING: 409 `RUN_IN_PROGRESS` (lines 686-687).
  - **`REASSESSMENT_REQUIRED`**: INITIAL processing of a period that already has a published final audit pack gives 409 `REASSESSMENT_REQUIRED`, with `extra.final_pack_id` (lines 691-694). New evidence for a published month can only be assessed through an explicit REASSESSMENT.
  - REASSESSMENT with no published final pack: 409 `NOTHING_TO_REASSESS` (lines 698-699). The baseline must verify, otherwise 409 `BASELINE_UNVERIFIABLE` (see D.9).
  - A required type IN-01..IN-17 missing from the effective set: 409 **`INCOMPLETE`**, with `extra.missing` (lines 703-706).
- **processing_supported / processing_limitation / policy applicability**: these are shown on the period, the batch and the dashboard (`routers/monthly.py:140-141`; `period_detail`). The backend does **not** call them as a separate check in `process()`. The rule is still enforced, because without an applicable policy no IN-17 document can be used, so the run stops with `INCOMPLETE`.
- **The run (job)**: `_execute` (line 736) calls `_process` (lines 756-814):
  - The case folder is `cases/SET-<sha256(period + slot:sha …)[:16]>`. If that folder already exists, its `intake.csv` must match the document set, otherwise FAILED "the prepared case folder does not match".
  - `prepare_case` stops on MISSING (for a required type), AMBIGUOUS or REJECTED intake decisions: FAILED "prepared case is incomplete".
  - The governing policy is passed explicitly (`selected_policy`).
  - `build()` must return GENERATED, otherwise FAILED with the first validation findings.
  - `_publish` is write-once. An existing pack with the same ID but different bytes raises "packs are never overwritten". An identical pack gives `ALREADY_EXISTS`.
  - The published pack must load and verify, and is then registered in `period_packs`.
  - Continuity with the previous month is reported but never changes the result: status NOT_VERIFIABLE when no earlier run exists (lines 874-889).
  - Outcome: run SUCCEEDED or FAILED; batch PROCESSED or PROCESSING_FAILED; period PROCESSED (if it has any pack) or PROCESSING_FAILED (lines 745-750).
- **Next stage**: the pack appears under the period. The analyst works on the exceptions (D.6).

## D.5 Pack generation and registration
- Generation is the `build()` call described in D.4 (`uc042lib/pack/generate.py:37-50`). It writes nothing; the backend writes with `_publish` (`monthly.py:897-925`) into the **primary** packs root, with an atomic rename from a `.tmp-` folder and `generations/0001.json` recording `uc042app_processing_run`.
- Registration is the `audit.period_packs` row (`add_pack`, `monthly.py:806-808`), with origin UPLOAD_PROCESSING and the `pack_content_sha256`.
- At **startup**, `sync_packs()` (`monthly.py:983-1014`) registers any verified pack in any root set that is not yet registered. September scenario packs get origin POC_SCENARIO. A period row is created only for a month that has a pack.
- On every read, `PackService._verified` (`services/packs.py:47-61`) calls `layout.for_pack`. Not found gives 404. Found in two roots gives 409 `DUPLICATE_PACK`, and a pack in the wrong profile gives 409 `PACK_OUTSIDE_PROFILE` (`layout.py:78-92`). It then calls `load_pack`, which checks identity, content hash and schema; failure gives 409 `PACK_VERIFICATION_FAILED`.

## D.6 Exceptions
- Read-only: `GET /packs/{id}/exceptions` and `GET /packs/{id}/exceptions/{eid}` (`routers/packs.py:41-53`). An unknown exception gives 404 "exception not found in this pack" (`services/packs.py:67-72`).
- **No endpoint changes an exception's status or review status.** OPEN and AWAITING_HUMAN_REVIEW stay as the engine wrote them. Human conclusions are recorded in cases (D.7). How each exception is represented in the final pack is set through the review selections (D.11).
- `GET .../source-evidence` (`services/investigations.py:186-206`) gives the exception's supporting records through deterministic retrieval with no AI. It returns 409 `SOURCE_UNAVAILABLE` if those records cannot be retrieved.

## D.7 Opening a case and adding case entries
- **Open**: `POST /packs/{p}/exceptions/{e}/case` → `CaseService.open` (`services/cases.py:57-78`).
  - The pack must verify and the exception must exist (404 or 409, as in D.5).
  - If a case already exists for (pack, exception), it is returned with **HTTP 200** (one case per exception, plus a unique constraint, `models.py:273`).
  - The pack's period must be registered: 409 `PERIOD_NOT_REGISTERED` (line 67-68).
  - A new case starts with status OPEN, resolution UNRESOLVED, revision 0, and HTTP 201.
  - Nothing ever opens a case automatically.
- **Entry**: `POST /cases/{id}/entries {kind, text, evidence_refs, expected_revision, resolution?, close?}` → `add_entry` (`cases.py:135-167`).
  - `kind` must be NOTE, EVIDENCE, EVIDENCE_GAP, OBSERVATION, HYPOTHESIS or DECISION: 422 `INVALID_KIND`.
  - `text` must be 3-4000 characters: 422 `TEXT_REQUIRED`.
  - `expected_revision` is required: 422 `REVISION_REQUIRED`. The schema also requires it (`schemas.py:502`).
  - `evidence_refs`: at most 50, and each must be a pack record or file evidence ID, a `DOC-` of the case's period, or a published `INV-` of this exception. Otherwise 422 `INVALID_EVIDENCE_REF` (`_valid_refs`, lines 108-133).
  - EVIDENCE and OBSERVATION must cite at least one reference: 422 `EVIDENCE_REQUIRED`.
  - DECISION must set `resolution` to UNRESOLVED, EXPLAINED_BY_ANALYST or ESCALATED: 422 `RESOLUTION_REQUIRED`. `close=true` closes the case; `close=false` keeps it open or reopens it.
  - A non-DECISION entry with a resolution or close value: 422 `DECISION_ONLY`.
  - A non-DECISION entry on a CLOSED case: 409 `CASE_CLOSED`.
  - A revision mismatch: 409 `CASE_CHANGED` (`ConcurrentUpdate`, line 163-164).
  - Entries can only be added, never edited or deleted. The resolution changes **only** through a DECISION entry, never automatically (`cases.py:7-10`).
- **AI from a case**: `POST /cases/{id}/ai-investigation`. A CLOSED case gives 409 `CASE_CLOSED` (`cases.py:176-177`). Otherwise the request goes through D.8, and an `AI_REQUEST` entry is added at the current revision (lines 180-188). The AI result does not change the case's resolution.

## D.8 Starting an AI investigation
- **Endpoints**: `POST /packs/{p}/exceptions/{e}/investigations {mode:"tools", authorization, retry_of?}` (`routers/investigations.py:27`), or the case route above. Both use `InvestigationService.start` (`services/investigations.py:240-278`) under the per-pack lock (`locks.hold`; if busy for more than 30 s: 409 `PACK_BUSY`, `locks.py:20-24`).
- **Checks, in order**:
  1. The pack verifies and the exception exists (404 or 409).
  2. **Authorisation**: `authorization.confirmed` must be `true`, otherwise 422 **`AUTHORIZATION_REQUIRED`**, with the current configuration in `extra` (`ai_authorization.py:58-70`). A provider or model that differs from the current configuration gives 409 **`AI_CONFIGURATION_CHANGED`**, and the refusal is recorded (line 98-100).
  3. An INVESTIGATION job already active for this exception: 409 **`INVESTIGATION_ACTIVE`**, with `extra.job_id`, recorded as `REFUSED_INVESTIGATION_ACTIVE` (lines 252-256).
  4. `retry_of` must name an earlier job of the same pack and exception: 422 (lines 257-260).
  5. Provider: if not configured, or if it is the offline simulator, 503 **`PROVIDER_NOT_CONFIGURED`**. A provider without tool support gives 422 `MODE_UNSUPPORTED` (lines 228-238). Both are recorded as refusals.
  6. The job is created, then the AUTHORIZED record (`AIA-…`) is written **before** the job is submitted. If that write fails, the job is marked FAILED and never runs (lines 265-277).
- **Response**: 202 with the `Job`. The job (`_execute`, lines 290-310) runs the LangGraph tools-mode investigation (`graph.run_investigation`) within the limits: 8 tool calls, 4 rounds, 25 records per call, an estimated 150k input tokens, and a time budget.
  - Not published: the job is FAILED and the attempt is kept in `_not_published/`.
  - Published but registration refused: the job is FAILED with "published but not registered".
  - Otherwise COMPLETED with `registered=true`.
- **Eligibility for a final pack** (`investigations.py:64-111`), shown as `eligible` with its reasons. It requires all of:
  - the library check: verify_published, same pack and hash, COMPLETED/VALID, not simulated, current rules;
  - the registry check: the files must match the pinned hashes;
  - no AUTHORIZATION_DISCREPANCY decision.
- **Next stage**: the final review (D.10), or more case work.

## D.9 Reassessment (new evidence after a final pack was published)
- **Trigger**:
  - The analyst uploads a batch, usually ADDITIONAL_EVIDENCE or CORRECTION, after a final pack has been published. The documents get `RECEIVED_AFTER_PUBLICATION`.
  - `period_view` then marks `pending_reassessment=true` and `reporting_status=ADDITIONAL_EVIDENCE_RECEIVED`. This happens when any document's `created_at` is later than the latest final pack's `generated_at` (`routers/monthly.py:122-124, 152-153`).
  - The analyst confirms that batch (D.3).
- **Read-only plan**: `GET /periods/{id}/reassessment` → `reassessment_plan` (`monthly.py:279-319`). It returns the target pack (the source pack of the latest final pack), the new documents, the baseline, `effective_set` (uploaded documents first, then baseline files), `missing_required` and `blockers`:
  - "no final audit pack has been published";
  - "no evidence was received after the latest final audit pack";
  - "confirm the batch holding the new evidence first";
  - "the original source documents cannot be verified";
  - "required evidence is missing: …".
  - `can_reassess` is true when there are no blockers.
- **Baseline from the lineage root's hash-checked sources** (`baseline()`, `monthly.py:223-264`):
  - `root_id = final_packs.lineage_root(pack_id)`: the `audit.pack_lineage.lineage_root_pack_id`, or the pack itself (`final_packs.py:44-46`).
  - The root pack must be from the **same period**, otherwise 409 `BASELINE_UNVERIFIABLE`.
  - The files are read where they sit, in the root pack's own storage root set's dataset folder. Only evidence-register files with `availability == PRESENT`, a SHA-256 and an evidence ID are used, and only paths under `source_data/*.csv` or `supporting_documents/*.pdf` (`BASELINE_FILE_RE`, line 48). Answer keys and verification material are never read.
  - Every file is hashed. A missing file, an unreadable file, a hash mismatch or a path outside the folder gives 409 `BASELINE_UNVERIFIABLE` with `extra.problems`.
  - If the lineage started from uploaded documents (there is no dataset folder), the baseline is `None`. The latest confirmed uploads already form the full set.
  - Every baseline file is hashed **again when the job uses it** (`_baseline_bytes`, lines 266-277).
- **Letters during reassessment**: if the new batch contains IN-15 or IN-16 PDFs but no IN-02, and the period has no uploaded IN-02, the letter reference is matched against the **verified baseline IN-02** of the lineage being reassessed. The baseline CSV is hashed again and read from a temporary copy (`_resolve_letters` and `_baseline_rows`, `monthly.py:433-465`). If nothing matches: `LETTER_NOT_MATCHED` ERROR.
- **Start**: `POST /periods/{id}/reconciliation {purpose:"REASSESSMENT", reason}` (UI `components/report/Reassessment.tsx:32`). This applies the D.4 checks, then:
  - the run result records `predecessor_pack_id`, `reassessed_final_pack_id` and the baseline subset actually used (`monthly.py:709-714`);
  - the case is built from uploaded files plus `<fid>_BASELINE` files.
- **After success**: `_record_lineage` (lines 816-839) writes `audit.pack_lineage` once, with the predecessor, the root, the reason and `change_summary`: inputs changed, added or removed; engine status; completeness; control outcomes; exceptions added, removed or unchanged. These are compared by category, account, currency, dates and amount (lines 841-872).
  - If the reassessment gives the **same** pack ID, no row is written, and the result is `same_pack: true`.
  - The published final packs are never changed. A new final-pack version needs the normal review (D.10-D.13), and its version number continues the lineage.

## D.10 Opening the final review
- **Endpoint**: `POST /packs/{pack_id}/reviews` → `ReviewService.open` (`services/reviews.py:70-85`), under the per-pack lock.
- **Checks**: the pack must verify (404 or 409). If an active session (OPEN, ON_HOLD, GENERATING or GENERATION_FAILED) exists for the pack, it is returned with HTTP 200, so there is never a second active session. Otherwise a new `RS-…` session is created: status OPEN, revision 1, `selections_version` 1, HTTP 201.
- The default selections (`_default_selections`, lines 87-96) are the newest eligible tools-mode investigation of each exception, otherwise the newest eligible one, otherwise NOT_INVESTIGATED.
- Only this explicit POST creates a session. Reading or browsing never does (line 71-72).
- The review does **not** check that the pack is the latest in its lineage, or that its period has no pending reassessment (UNCONFIRMED whether this is intended; no such check was found in `reviews.py`).

## D.11 Selections
- **Endpoint**: `PATCH /reviews/{id}/selections {selections[], expected_revision?}` → `set_selections` (`reviews.py:98-138`).
- **Checks**:
  - The session must be OPEN, ON_HOLD or GENERATION_FAILED: 409 `SESSION_NOT_EDITABLE`.
  - The revision must match: 409 `REVIEW_CONFLICT`.
  - A preview job must not be running: 409 `PREVIEW_IN_PROGRESS`.
  - Each `Selection` (`uc042lib/final_pack/model.py:47-64`):
    - `inclusion` is INCLUDED, NOT_INVESTIGATED or EXCLUDED_BY_ANALYST;
    - INCLUDED needs an `investigation_id`; the others must not have one;
    - EXCLUDED_BY_ANALYST needs a `reason`;
    - otherwise 422 `SELECTION_INVALID`.
  - There must be exactly one selection per exception in the pack: 422 `SELECTION_INCOMPLETE`.
  - INCLUDED must name a published **and eligible** investigation of that exception: 422 `INELIGIBLE_SELECTION`.
  - NOT_INVESTIGATED while a library-eligible investigation exists: 422 `NOT_INVESTIGATED_WITH_ELIGIBLE`.
- **Effect**: `selections_version` increases by 1, `current_preview_id` is cleared (so a new preview is needed), and the status returns to OPEN.

## D.12 Preview (with the AI closing summary)
- **Endpoint**: `POST /reviews/{id}/preview {authorization}` → `request_preview` (`reviews.py:213-258`). This is a PREVIEW background job.
- **Checks**:
  - The same authorisation checks as D.8: 422 `AUTHORIZATION_REQUIRED` or 409 `AI_CONFIGURATION_CHANGED`. Operation CLOSING_SUMMARY.
  - Session not editable: 409 `SESSION_NOT_EDITABLE`.
  - A preview is already running: 409 `PREVIEW_IN_PROGRESS`.
  - Readiness blockers other than PREVIEW_REQUIRED: 409 `BLOCKED`, with `extra.blockers`. The blockers are INVESTIGATION_RUNNING (any investigation job of the pack), INELIGIBLE_SELECTION and NOT_INVESTIGATED_WITH_ELIGIBLE (`readiness`, lines 145-178).
  - Every refusal is recorded in `ai_execution_authorizations`.
  - **A missing provider does not refuse the request.** The authorisation is recorded with `model_call_expected=false`, and the summary comes out as UNAVAILABLE.
- **Job** (`_build_preview`, lines 260-295):
  - `build_review_snapshot` runs in the pack's own root set. Problems give job FAILED, `BLOCKED`.
  - `generate_closing_summary` calls OpenAI `structured_request` and checks the output (`final_pack/summary.py:199-222`). Any failure produces `unavailable_closing_summary` instead.
  - `assemble_preview` must pass final-pack validation, otherwise the job is FAILED.
  - The meta (snapshot hash, inputs fingerprint, closing summary) and the preview document are saved write-once in `audit.previews`.
  - The preview becomes `current_preview_id` only if `selections_version` did not change while the job ran and the session is still editable (lines 289-293).
- **Reading**: `GET /reviews/{id}/preview` and `/preview/{html|pdf|json}?snapshot=<sha>`. If there is no current preview: 404 `NO_PREVIEW`. A `snapshot` that no longer matches: 409 `PREVIEW_STALE` (`routers/reviews.py:62-81`).

## D.13 HOLD
- **Endpoint**: `POST /reviews/{id}/decision {decision:"HOLD", comment, snapshot_sha256?}` → `decide` (`reviews.py:311-324`), then `_hold` (lines 336-346). The lock waits up to 30 s.
- **Checks**:
  - The session is GENERATING: 409 `GENERATION_IN_PROGRESS`. The session is GENERATED: 409 `SESSION_CLOSED`, with `extra.final_pack_id`.
  - A comment is required: 422 `COMMENT_REQUIRED`.
  - If a `snapshot_sha256` is sent, it must match the current preview: 409 `PREVIEW_STALE`.
- **Effect**: a `RD-…` decision is appended (append-only). The status becomes ON_HOLD and `current_preview_id` is cleared, so a new preview is needed before GENERATE. All HOLD decisions are later listed in the final pack as `prior_decisions` (line 371-372).

## D.14 GENERATE
- **Endpoint**: as D.13 with `decision:"GENERATE"`, then `_generate` (`reviews.py:348-389`). It does **not** wait for the lock: if busy, 409 `GENERATION_IN_PROGRESS` (lines 314-315). It runs inside the request, which the frontend allows 180 s for.
- **Checks, in order**:
  - GENERATING or GENERATED: 409 `GENERATION_IN_PROGRESS` or `SESSION_CLOSED`.
  - No current preview: 409 `PREVIEW_REQUIRED`.
  - `snapshot_sha256` differs from the preview's: 409 `PREVIEW_STALE`.
  - `acknowledgement_accepted` is not true: 422 `ACKNOWLEDGEMENT_REQUIRED`. The text (`final_pack/model.py:26-27`): "Generating this pack does not resolve any exception, confirm any hypothesis or establish compliance. Unresolved exceptions will appear as UNRESOLVED."
  - The closing summary is UNAVAILABLE and `acknowledged_summary_unavailable` is not true: 422 `SUMMARY_UNAVAILABLE_ACK_REQUIRED`.
  - The inputs fingerprint changed (a new or changed investigation, or a change in eligibility): 409 `PREVIEW_STALE`.
  - Any readiness blocker: 409 `BLOCKED`, with `extra.blockers`.
  - The snapshot is rebuilt now (library plus registry) and must hash to the preview's snapshot hash: 409 `PREVIEW_STALE` or `BLOCKED`.
- **Effect**:
  - The decision is appended and the session goes to GENERATING.
  - `FinalPackService.generate` (`final_packs.py:68-92`): `next_version` across the lineage gives (v, supersedes); a GENERATING record is written; then `assemble_final_pack`, `publish_final_pack(root_for(pack), expected=(v, supersedes))` and `verify_final_pack`.
  - On success: the record and the session become GENERATED, and the response is 201 with `final_pack`.
  - On any failure: the record and the session become GENERATION_FAILED, nothing is published, and the response is **HTTP 500 `GENERATION_FAILED`** (`reviews.py:381-385`). The session can be edited again and retried.
  - Readiness also warns `FINAL_PACK_EXISTS`: "a new one will be version N, superseding …" (lines 171-174).
  - If the backend restarts during GENERATING, `recover()` reconciles the record with what is on disk (`final_packs.py:94-115`; `reviews.py:411-419`).

## D.15 Publish and verify
- Publication is part of GENERATE (D.14). Nothing is published separately.
- `publish_final_pack` (`uc042lib/final_pack/persistence.py:67+`) refuses anything that is not a GENERATED pack with a GENERATE decision, so previews are never published. It also refuses an invalid FAP ID or content hash, a version or supersedes value that differs from `expected`, and a second final pack for the same decision. All four files are staged and renamed together.
- **Verify**: `GET /final-packs/{id}/verify` → `verify_final_pack` (`final_packs.py:152-154`). It checks the manifest hashes, the content hash and the rendering. Each file download (`/html`, `/pdf`, `/json`) is checked against the manifest before it is served: 409 `FINAL_PACK_INTEGRITY_FAILED` (`final_packs.py:156-166`). An unknown ID gives 404. Two copies in different roots give 409 `DUPLICATE_FINAL_PACK`.

## D.16 Retrieving previous versions
- `GET /final-packs` lists every published final pack in all final-packs roots (primary and demo_history), oldest first. `GET /final-packs?pack_id=<PACK>` lists that deterministic pack's own versions. `GET /final-packs?pack_id=<PACK>&lineage=true` lists **every version of the period's reassessment lineage**, even when they come from different deterministic packs or are published in different roots (`final_packs.py:54-58, 118-128`).
- Each item gives `version`, `supersedes_final_pack_id`, `generated_at`, `review_decision_id` and `final_content_sha256`. Every older version stays published, can still be verified, and is never changed (UI: `pages/FinalPackPages.tsx:51`; `pages/ReviewPages.tsx:26`).
- Review history: `GET /reviews/{id}/history` returns the append-only decisions and the final-pack records (`reviews.py:406-409`).
- Source documents: earlier versions stay in the archive (`GET /periods/{id}` returns every document; `GET /documents/{id}/content` re-checks the SHA-256 and returns 409 `DOCUMENT_INTEGRITY` on mismatch, `monthly.py:595-600`).
- Lineage: `GET /periods/{id}/lineage` lists which pack reassesses which (`routers/monthly.py:268-273`).

---

## D.17 Flow summary (what starts each next stage)
```
create/select period (PER-YYYY-MM; current or past month only)
  -> upload batch (UPL-, VALIDATED; documents DOC- with checks and flags)
  -> include/exclude flagged documents (only while VALIDATED)
  -> confirm (CONFIRMED)                      [409 DECISIONS_PENDING / BATCH_INVALID / AMBIGUOUS_EVIDENCE_TYPE]
  -> process (RUN-, PROCESSING job)           [409 BATCH_NOT_CONFIRMED / RUN_IN_PROGRESS / REASSESSMENT_REQUIRED / INCOMPLETE]
  -> pack PACK-... published + period_packs row (job SUCCEEDED)
  -> exceptions EXC-... (read-only) -> optional case CASE- (entries; DECISION sets the resolution)
  -> AI investigation (AIA- recorded first; JOB-; INV- published + registered)
                                              [422 AUTHORIZATION_REQUIRED / 409 INVESTIGATION_ACTIVE / 503 PROVIDER_NOT_CONFIGURED]
  -> open review (RS-) -> selections -> preview job (closing summary; PV-)
  -> HOLD (ON_HOLD, the preview is cleared) | GENERATE (FAP-...-v<n>, published + verified; or 500 GENERATION_FAILED)
  -> new evidence after publication -> confirm -> REASSESSMENT run -> new PACK linked in pack_lineage
  -> new review -> FAP v<n+1> supersedes v<n>
```
