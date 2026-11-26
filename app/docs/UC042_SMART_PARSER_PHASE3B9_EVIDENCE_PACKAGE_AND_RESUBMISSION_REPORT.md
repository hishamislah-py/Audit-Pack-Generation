# UC-042 Smart Parser — Phase 3B-9: Evidence Package Management, File Versioning and Controlled Resubmission

| | |
|---|---|
| Date | 18 November 2026 |
| Working copy | `C:\Users\artlptp263user\p10\smartparser_phase1` (the only location modified) |
| Evidence | `Downloads\UC042_SMART_PARSER_PHASE3B9\evidence\` (`evidence_baseline\` = before any 3B-9 change) |
| Result | **Implemented and tested offline.** Evidence packages, per-file versions, controlled resubmission, all-or-nothing snapshot activation and an immutable reconciliation-ready manifest. **553 tests pass** (512 + 41). Evaluations 68/68 and 34/34. Nothing submitted, no reconciliation run, no live provider call. |

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| **[I]** | Implemented in this phase |
| **[T]** | Verified by an executed test |
| **[C]** | Inferred from code inspection |
| **[N]** | Not implemented |
| **[P]** | Proposed for a future phase |

---

## 1. Executive summary

An analyst can now:
1. create a package for a reporting period;
2. upload its evidence files at once;
3. see which files need correction;
4. resubmit **only those files**;
5. have the Smart Parser assemble the latest valid version of every file into one immutable, traceable snapshot and manifest.

The brief's business example runs end to end [T] (`evidence/example_business_scenario/`):

```
initial : IN-02 v1 VALIDATED, IN-03 v1 RESUBMISSION_REQUIRED, IN-05 v1 VALIDATED, IN-08 v1 RESUBMISSION_REQUIRED, IN-11 v1 VALIDATED
pending : ['IN-03', 'IN-08']                       (only these two are requested again)
IN-03 v2 VALIDATED       -> activation refused: IN-08 still awaits a corrected file (no partial package)
IN-08 v2 FAILED_VALIDATION (handoff checks 10, 11) -> activation refused again
IN-08 v3 VALIDATED       -> snapshot SNAP-001-68c4675d activated
final   : RECONCILIATION_READY
  IN-02: v1 ACTIVE                IN-05: v1 ACTIVE                IN-11: v1 ACTIVE
  IN-03: v1 SUPERSEDED -> v2 ACTIVE
  IN-08: v1 SUPERSEDED -> v2 SUPERSEDED -> v3 ACTIVE
verify_snapshot: SV-1..SV-5 all pass; audit chain 62 events, verified
```

**How it is built:**
- **Reuse.** Every file, whether a first upload or a correction, goes through the **existing** orchestrator from the beginning: header-count gate, deterministic mapping, proposal only when eligible, validation, policy or human review, reprocessing, the 14-point handoff checks and the preview.
- **Missing columns:** the file needs resubmission (RESUBMISSION_REQUIRED).
- **Extra columns:** the file goes to the existing mapping review, and nothing is ignored automatically.
- **Same-count unfamiliar headers:** the existing deterministic, then LLM, then validation, then review workflow.
- **No reuse of earlier approvals.** File-specific mappings are bound to one intake and its SHA-256, so a correction never reuses an earlier file-specific approval.

**What the manifest is and is not.** The package output is a **validated selection plus manifest** (`RECONCILIATION_READY_NOT_SUBMITTED`, `reconciliation_status: NOT_RUN`). No financial reconciliation was run and nothing was submitted to UC-042.

**Small additions to existing code:**
- `MappingOrchestrator.complete_session`, which closes 3B-8 gap P1-7, so same-count files that land in proposal review (with the shipped, disabled POC policy) can be completed.
- 15 package audit event types.

## 2. Baseline test results (before any 3B-9 change)

| Check | Result (`evidence_baseline/regression_summary.txt`) |
|---|---|
| Full suite | **512 passed**; without the UC-042 tree 509 passed, 3 skipped |
| Per phase | 3B-8 21, 3B-7 35, 3B-6.1 18, 3B-6 43, 3B-5 16, 3B-4 14, 3B-3 15, 3B-2 23, 3B-1 40, 3B-0 117, Phase 1+orig 136, Phase 2 34 |
| Registry / baseline / corpus | in sync (19); 445/445; 161/161 |
| Protected trees | UC-042 107 code + 624 dataset files, Desktop 63 files: hash-identical; 0 UC-042 files newer than the Phase 1 start |
| POC policy / AI / authority | `DISABLED`; `enabled=False`; production scopes `{}` |

These match the 3B-8 report.

## 3. Existing architecture inspection (what the package layer builds on)

| Need | Existing component reused [C/T] |
|---|---|
| Upload identity, immutable bytes | `intake.store.EvidenceStore`: content-addressed originals (never overwritten), `IntakeRecord` (intake ID, SHA-256, period); index reload and atomic write since 3B-8 |
| Category from content, never from the filename | `SmartParser.process_bytes` / `classify_csv` (exact header, controlled mapping); PDF label classification; `letter_refs_from_inventory` (IN-15/16 resolve **only** through an account inventory) |
| File workflow | `MappingOrchestrator.process` (3B-7 gate, deterministic, proposal, policy, HITL), `complete_case`, `_finish` (reprocess, 14 checks, preview, 3B-8 outcome events) |
| Human review state | `review.intake.ColumnReviewCase`, `review.session.ReviewSession`, `review.approvals.CategoryConfirmation` / `FileMappingRule` |
| File-level checks | `handoff.eligibility.check_handoff` (14 checks), `handoff.reprocess` (SHA verify, no LLM) |
| Audit | `review.audit.AuditLog` (hash-chained JSONL) |
| Required categories | the registry's `requirement` field, generated from the UC-042 upload contract (`uc042lib/schema.py`): **17 REQUIRED** (IN-01…IN-14 CSV, IN-15/16/17 PDF), **2 OPTIONAL** (IN-18, IN-19) |
| UC-042 package-level rule found | "no required evidence missing" (`uc042lib/pack/assemble.py`, missing-evidence register; read-only inspection). Content period rules (`period_rule`) and cross-file references are applied by the **UC-042 engine** during reconciliation; they are not re-implemented here (§16) |

**Where the package layer integrates:** a new package `smartparser/packages/` sits **above** the orchestrator. It decides which slot a file belongs to and records the outcome, but it never maps, proposes or validates columns itself.

## 4. Evidence package data model [I] (`smartparser/packages/models.py`)

| Model | Key fields |
|---|---|
| **EvidencePackage** | `package_id` (`PKG-<period>-<6 hex>`), `reporting_period`, `created_at`, `updated_at`, `package_status`, `required_evidence_categories`, `evidence_files` (one slot per category), `versions`, `active_snapshot_id`, `snapshot_ids`, `validation_results` (all, in order), `unassigned_uploads` (refused uploads, traceable), `revision` |
| **EvidenceFile** (slot) | `evidence_category`, `required`, `version_ids` (in order), `active_version_id` |
| **FileVersion** | `file_version_id`, `package_id`, `evidence_category`, `version_number`, `intake_id`, `original_filename`, `source_sha256`, `uploaded_at`, `reporting_period`, `version_status`, `processing_status` (`<route>:<decision>`), `reasons`, `missing_fields`, `content_category`, `review_case_id` / `review_session_id`, `previous_version_id`, `replacement_reason`, `mapping_rule_refs`, `confirmation` (the reused `CategoryConfirmation`, persisted, which closes 3B-8 gap P1-4 for package files), `handoff` (eligible, failed checks, preview path + output SHA, provenance path, basis), `status_history` |
| **PackageSnapshot** (immutable) | `snapshot_id` (`SNAP-<seq>-<selection hash>`), `package_id`, `reporting_period`, `sequence`, `created_at`, `entries` (category, version ID and number, intake ID, filename, SHA-256, period, handoff, rule refs, confirmation ID), `selection_sha256`, `validation_id`, `previous_snapshot_id`, `submission_authorised: false`, `reconciliation_status: NOT_RUN` |
| **PackageValidationResult** | `validation_id`, `at`, `selection`, `checks` (PV-01…PV-09), `passed` |

**Identity rule [T]:**
- A correction is a **new intake**, with a new intake ID and its own SHA-256, and a **new version** linked by `previous_version_id`.
- The earlier bytes stay in the content-addressed store unchanged (tests 13 and 22).

**One active file per category [T]:**
- one slot per category;
- a second file for an occupied slot is refused (test 06);
- a snapshot holds exactly one version per category (test 27);
- validation fails if any slot has two ACTIVE versions (PV-02).

## 5. File-version lifecycle [I/T]

| Status | Set when |
|---|---|
| RECEIVED | first entry of every version's history (the version is recorded after processing in the same call) |
| VALIDATED | equal count, eligible (DETERMINISTIC or AUTO_ACCEPT); or review completed (case or session RESOLVED) and eligible |
| REVIEW_REQUIRED | more columns than fields (3B-7 gate case), a proposal session, a deterministic-conflict case, or a held review with only unresolved columns |
| RESUBMISSION_REQUIRED | fewer columns than fields, or a completed review that still leaves a required field uncovered |
| FAILED_VALIDATION | processed but not eligible (e.g. data errors, handoff checks 10/11) or held on the proposal path (e.g. provider disabled, unmappable) |
| REJECTED | the content identifies as another category (never switched), or the reviewer rejected the file |
| ACTIVE | selected by the activated snapshot |
| SUPERSEDED | an earlier version of a slot when a newer version of that slot is activated (REJECTED stays REJECTED) |

**Transitions**

```
RECEIVED ─► VALIDATED ─────────────────────────────► ACTIVE ─► SUPERSEDED   (when a newer version is activated)
        ├─► REVIEW_REQUIRED ─complete─► VALIDATED | RESUBMISSION_REQUIRED | REVIEW_REQUIRED (held) | FAILED_VALIDATION
        │                   └─reject──► REJECTED
        ├─► RESUBMISSION_REQUIRED ─┐
        ├─► FAILED_VALIDATION ─────┼─(correction = new version)─►  … ; the older one ─► SUPERSEDED on activation
        └─► REJECTED ──────────────┘
```

The full history of every version is kept in `status_history`, for example `RECEIVED → FAILED_VALIDATION → SUPERSEDED` [T test 20].

## 6. Initial package intake [I/T]

`PackageService.create_package(period, required_categories=None)` defaults to the 17 UC-042 REQUIRED categories. `submit(package_id, [Submission(data, filename, declared_category?)])` then processes the files one by one:
1. **CSVs before PDFs**, so the package's own IN-02 can resolve the acknowledgement letters.
2. **Content category.** It is computed in memory, deterministically (exact header, controlled mapping, PDF labels), with no intake and no file rule. The filename is never used.
3. **Slot.**
   - The slot is the declared category or, failing that, the content category.
   - If the content identifies **another** category than the declared slot, the file is stored for traceability and the version is **REJECTED**; it is never switched (test `declared_slot_contradicted…`).
   - If neither content nor declaration gives a category, the upload is refused and recorded in `unassigned_uploads` (audited).
4. **Duplicates.** A file for an occupied slot is refused ("use resubmission"), which covers duplicates within one submission [T test 06].
5. **CSV workflow.** `MappingOrchestrator.process(data, filename, period, category=slot)`. This is unchanged and creates the intake, routes the file, runs the review or proposal, reprocesses, runs the handoff checks and writes the preview. The outcome is mapped onto the version (§5). Review cases and sessions (with their proposal request) are persisted in the package store.
6. **PDF evidence.** The existing PDF classification runs, with letters resolved via the package's IN-02. The version is VALIDATED on content classification only (`basis: PDF_CONTENT_CLASSIFICATION_ONLY`); PDF field extraction is not implemented (Phase 1 scope) [T test 01b: all 17 categories, PDFs listed first and still resolved].
7. **Audit.** `PACKAGE_FILE_RECEIVED`, `FILE_VERSION_CREATED`, then `FILE_VERSION_VALIDATED`, `FILE_VERSION_REVIEW_REQUIRED`, `RESUBMISSION_REQUESTED` (with reason and missing fields) or `FILE_VERSION_REJECTED`.

**Routing preserved [T]:**

| Case | Result | Test |
|---|---|---|
| Equal count | existing deterministic, proposal and policy path | 01, 05, 05b |
| More columns | REVIEW_REQUIRED (mapping review); the extra column is a case item; no decision is made automatically | 04 |
| Fewer columns | RESUBMISSION_REQUIRED with the missing fields; no LLM call; never filled | 02, 03 |

## 7. Specific-file resubmission [I/T]

`resubmit(package_id, category, data, filename, reason)` runs these steps:
1. The package and the category slot exist (else `PackageError`), and the slot has a previous version.
2. **Identical bytes** to any version of the slot are refused idempotently, with a reference to the existing version. No intake and no version are created [T test 19: a double upload, and v1's bytes re-sent].
3. The latest version must not be under an open review: complete or reject it first [T].

   A correction is accepted after RESUBMISSION_REQUIRED, FAILED_VALIDATION or REJECTED, **and also to replace an accepted (VALIDATED or ACTIVE) file**, as §7.2 requires ("do not silently replace an accepted file").
4. A replacement reason is required.
5. **Content check.** If the content identifies another category, the new version is REJECTED and "not a replacement for IN-03" is recorded [T test 17].
6. **Full pipeline from the beginning.** A new intake ID and SHA-256, then the gate, deterministic mapping, LLM only when eligible, validation, review, reprocessing, the 14 handoff checks and the preview [T test 15: route DETERMINISTIC, 14 checks evaluated, 0 provider calls].
7. **No reuse of file-specific approvals.** Earlier file-specific approvals are never reused: file mappings bind to intake ID and SHA-256 [C; 3B-7 test]. Reusable governed aliases or layouts still apply under their own rules [C].

**Outcomes:**
- A failed correction is kept as its own version (FAILED_VALIDATION, RESUBMISSION_REQUIRED or REJECTED), and the active snapshot is untouched [T tests 16, 20, 24].
- `pending_resubmissions(package_id)` lists **only** the categories that need a corrected file [T test 21: unchanged files are uploaded once and never requested again].

## 8. Version replacement and supersession [I/T]

- Nothing is replaced when a correction is uploaded. Replacement happens **only on snapshot activation**:
  - the selected version becomes ACTIVE (`FILE_VERSION_ACTIVATED`);
  - every earlier version of that slot (except REJECTED) becomes SUPERSEDED (`FILE_VERSION_SUPERSEDED`, with `superseded_by`) [T tests 20, 23, 26].
- Superseded versions remain fully retrievable:
  - the version record, its stored bytes (SHA-verified) and its preview;
  - every snapshot that referenced it, which `verify_snapshot` checks [T test 30].
- Nothing is ever deleted.

## 9. Package snapshot design [I/T]

**Candidate selection.** For every slot, the candidate is the **latest** version if it is VALIDATED or ACTIVE. A slot whose latest version is pending is **not** back-filled with an older version; it blocks activation.

`activate(package_id)` is **all-or-nothing**:
1. Run package validation (§10) over the complete candidate: unchanged ACTIVE versions plus every validated replacement.
2. If any check fails: `PACKAGE_VALIDATION_FAILED`; no snapshot is created, nothing changes, and the previous active snapshot stays active [T tests 24/25: IN-03 v2 valid, IN-08 v2 failed → still SNAP-001 with all v1; IN-03 v2 waits as VALIDATED].
3. If they pass: create the immutable snapshot (exclusive create), set ACTIVE and SUPERSEDED, write the immutable manifest, set the active pointer and save atomically. Audited as `PACKAGE_SNAPSHOT_CREATED`, then `FILE_VERSION_ACTIVATED`/`SUPERSEDED`, then `PACKAGE_SNAPSHOT_ACTIVATED`.

**Safety properties:**

| Property | Behaviour |
|---|---|
| Repeated activation | Idempotent: the same selection returns the existing active snapshot and creates nothing [T test 35] |
| Interrupted activation | A snapshot file already written with the same selection hash is reused on retry [C] |
| Immutability | Snapshot and manifest cannot be written twice (`PackageStoreError … immutable`) [T test 35] |
| Restart | Package state, review cases and sessions reload from disk [T tests 35, 35b] |
| Historical snapshots | Remain loadable and verifiable [T test 30] |

## 10. Package-level validation [I/T]

The checks run over the candidate selection. They are recorded on the package and audited (`PACKAGE_VALIDATION_STARTED`, then `PACKAGE_VALIDATED` or `PACKAGE_VALIDATION_FAILED` with the outcome per check).

| ID | Check (brief item) | How |
|---|---|---|
| PV-01 | all required categories present (1) | every required slot has ≥1 version [T 07] |
| PV-02 | exactly one selected version per category (2) | every required category selected; no slot with >1 ACTIVE; no duplicate selection |
| PV-03 | no file awaiting resubmission (3) | latest of **every** slot (required and optional) not in RESUBMISSION_REQUIRED, FAILED_VALIDATION or REJECTED [T 29] |
| PV-04 | no selected or required file under review (4) | latest not REVIEW_REQUIRED or RECEIVED [T 10, 29] |
| PV-05 | every selected file passed its file-level checks (5) | **re-run now**, not trusted. CSV: deterministic reprocess (no LLM) with the recorded confirmation and the current rules, then the 14-point handoff, then the preview file's hash re-verified. PDF: reclassified with the selection's IN-02. Catches revoked rules, tampered originals and changed previews [T 18b] |
| PV-06 | reporting periods consistent (6) | version period and intake-record period = package period [T 28] |
| PV-07 | package membership valid (7, 9) | version belongs to this package, its own slot, the slot's version list |
| PV-08 | valid intake + SHA-256 (8) | intake record exists, its SHA = version SHA, stored bytes re-hashed [T 18b] |
| PV-09 | the selection references exactly the validated versions (10) | selected versions VALIDATED or ACTIVE with an eligible handoff; the snapshot is then built **from exactly this selection** and `verify_snapshot` re-proves it (SV-1…SV-5) |

**Package status** (derived on every save):

| Status | Meaning |
|---|---|
| RECEIVED | created, no file yet |
| RESUBMISSION_REQUIRED | a correction is pending |
| REVIEW_REQUIRED | a review is open |
| INCOMPLETE | a required category has no file |
| READY_FOR_VALIDATION | the selection is complete but not yet the active snapshot |
| RECONCILIATION_READY | the active snapshot is exactly the current selection and passed validation |

A package **cannot** be RECONCILIATION_READY while any correction or review is pending [T 29]. If a voluntary correction of an accepted file fails, the previously activated snapshot stays active and immutable, but the package status shows RESUBMISSION_REQUIRED until it is resolved [T 24/25].

Per the brief, no financial or reconciliation rule was invented.

## 11. Reconciliation-ready manifest structure [I/T]

The manifest is at `packages/<package_id>/manifests/<snapshot_id>.manifest.json` and is immutable. A real one is in `evidence/example_business_scenario/manifest.json`.

```json
{ "manifest_schema": "smartparser-reconciliation-ready-package/1.0",
  "status": "RECONCILIATION_READY_NOT_SUBMITTED", "submission_authorised": false, "reconciliation_status": "NOT_RUN",
  "package_id": "...", "snapshot_id": "SNAP-001-…", "sequence": 1, "previous_snapshot_id": null,
  "reporting_period": "2026-09", "selection_sha256": "…", "validation_id": "PVR-…", "validation_timestamp": "…",
  "package_validation": {"passed": true, "checks": [ {"check_id": "PV-01", …} … ]},
  "required_evidence_categories": [...], "selected_evidence_categories": [...],
  "files": [ { "evidence_category", "file_version_id", "version_number", "previous_version_id", "replacement_reason",
               "intake_id", "original_filename", "source_sha256",
               "canonical_preview": {"path", "sha256"}, "provenance": {"path"},
               "file_level": {"eligible", "basis", "failed_checks"},
               "mapping_rule_refs", "confirmation_id", "processing_status" } ],
  "superseded_versions": [ … ] }
```

Paths are relative to the package store root. Previews and provenance sidecars live under `previews/<intake_id>/` (still PREVIEW_ONLY).

**Verified by tests:**
- [T 31–34] every SHA-256 re-hashes from the stored original and matches the intake record;
- every preview hash matches and its bytes equal the canonical file;
- every sidecar names the same source SHA, intake and output hash.

## 12. Audit and provenance behaviour [I/T]

The 15 new event types are in the existing hash-chained log. `package_id`, `file_version_id`, `previous_file_version_id`, `snapshot_id`, `evidence_category` and `reporting_period` are in `details`, and `intake_id` / `source_sha256` are top-level.

| Question | Answered by |
|---|---|
| 1 Which original file was uploaded? | `PACKAGE_FILE_RECEIVED` / `FILE_VERSION_CREATED` (intake, SHA, filename) |
| 2 Why was resubmission requested? | `RESUBMISSION_REQUESTED` (reason, `missing_fields`) [T] |
| 3 Which corrected version was uploaded? | `RESUBMISSION_RECEIVED` (`previous_file_version_id`, replacement reason; also refusals with `outcome: REFUSED`) [T 13, 19] |
| 4 Which checks did it pass? | `FILE_VERSION_VALIDATED` (handoff summary) + the 3B-8 `REPROCESSED` / `HANDOFF_EVALUATED` for the intake [T 15]; `PACKAGE_VALIDATED` (per-check outcome) |
| 5 Which version became active? | `FILE_VERSION_ACTIVATED` |
| 6 Which files were in the final snapshot? | `PACKAGE_SNAPSHOT_CREATED` (selection, selection hash, validation ID) |
| 7 Which versions were superseded? | `FILE_VERSION_SUPERSEDED` (`superseded_by`); `PACKAGE_SNAPSHOT_ACTIVATED.superseded_versions` |
| 8 Which exact snapshot was prepared? | `PACKAGE_SNAPSHOT_ACTIVATED` (snapshot ID, previous, manifest path) |

`test_package_audit_answers_the_traceability_questions` asserts these events and their key details. Nothing historical is overwritten: the audit is append-only, snapshots and manifests are create-once, and originals are content-addressed.

## 13. New end-to-end scenarios and results

`tests/test_packages_3b9.py`: **41 passed** (`evidence/packages_3b9_run.txt`). Every test runs with sockets blocked and `submit_to_uc042` patched to fail if it is ever called.

| # | Scenario | Test | Result |
|---|---|---|---|
| — | Store: create-once, stale-revision refusal, period/category validation, default 17 required | `test_store_…` | ✔ |
| 1 | All valid files | `test_01_…`, `test_01b_complete_uc042_contract_with_pdfs` | ✔ |
| 2 | One file with missing columns | `test_02_…` | ✔ |
| 3 | Two files with missing columns | `test_03_…` | ✔ |
| 4 | Extra-column file needs mapping | `test_04_…` | ✔ |
| 5 | Same-count unfamiliar headers | `test_05_…` (auto-accept, test policy), `test_05b_…` (proposal review, shipped policy) | ✔ |
| 6 | Duplicate category in one package | `test_06_…` | ✔ |
| 7 | Missing required category | `test_07_…` | ✔ |
| 8 | Extra column mapped | `test_08_…` (txn_ref CHANGE → txn_id; memo ignored) | ✔ |
| 9 | Extra column ignored with reason | `test_09_…` | ✔ |
| 10 | Extra column left unresolved | `test_10_…` (held → revisited → VALIDATED) | ✔ |
| 11 | Duplicate sources resolved | `test_11_…` | ✔ |
| 12 | Required field uncovered after mapping | `test_12_…` (→ RESUBMISSION_REQUIRED) | ✔ |
| 13 | Resubmit one file | `test_13_…` | ✔ |
| 14 | Resubmit two files | `test_14_…` | ✔ |
| 15 | Valid corrected structure, full pipeline | `test_15_…` | ✔ |
| 16 | Correction still missing columns | `test_16_…` | ✔ |
| 17 | Incorrect category | `test_17_…` | ✔ |
| 18 | Modified file after review | `test_18_…` (refused before writes) + `test_18b_…` (validated file tampered → PV-05/PV-08) | ✔ |
| 19 | Identical corrected bytes repeated | `test_19_…` | ✔ |
| 20 | v1 missing → v2 failed → v3 valid | `test_20_…` | ✔ |
| 21 | Unchanged files not requested again | `test_21_…` | ✔ |
| 22 | Original files unchanged | `test_22_…` | ✔ |
| 23 | All replacements valid → new snapshot | `test_23_…` | ✔ |
| 24–25 | One of two replacements fails; previous snapshot preserved | `test_24_25_…` | ✔ |
| 26–27 | Final snapshot = unchanged v1 + corrected v2; each category once | `test_26_27_…` | ✔ |
| 28 | Reporting-period consistency | `test_28_…` | ✔ |
| 29 | Not RECONCILIATION_READY with unresolved files | `test_29_…` | ✔ |
| 30 | Superseded versions retrievable | `test_30_…` | ✔ |
| 31 | Manifest generated | `test_31_…` | ✔ |
| 32 | Selected SHA-256 values | `test_32_…` | ✔ |
| 33–34 | Preview and provenance references | `test_33_34_…` | ✔ |
| 35 | Snapshot reproducible and inspectable (after restart; idempotent; immutable) | `test_35_…`, `test_35b_review_resumes_after_restart` | ✔ |
| 36 | No UC-042 submission or protected integration | `test_36_…` | ✔ |
| — | Rejected review needs a new version; no correction during an open review | `test_rejected_review_requires_a_new_version` | ✔ |
| — | Declared slot contradicted by content → REJECTED | `test_declared_slot_contradicted_by_content_is_rejected` | ✔ |
| — | Audit answers the 8 traceability questions | `test_package_audit_answers_…` | ✔ |

Across these tests the brief's verification list is covered:
- file contents (stored bytes);
- versions, active membership and package status;
- audit events and SHA-256;
- provenance (sidecars), mapping rules and preview eligibility;
- historical retention.

## 14. Full regression results (`evidence/regression_summary.txt`, final files)

| Check | Result |
|---|---|
| Full suite | **553 passed** (512 + 41); without the UC-042 tree 550 passed, 3 skipped |
| Per phase | 3B-9 41, 3B-8 21, 3B-7 35, 3B-6.1 18, 3B-6 43, 3B-5 16, 3B-4 14, 3B-3 15, 3B-2 23, 3B-1 40, 3B-0 117, Phase 1+orig 136, Phase 2 34 |
| Registry / baseline / corpus | in sync (19); 445/445; 161/161 |
| eval_3b5 / eval_3b6 | **68/68** / **34/34** (`evidence/eval_3b5`, `evidence/eval_3b6`) |

No existing test was changed in this phase, and no expected behaviour was altered.

## 15. Exact files created and modified

| File | Change |
|---|---|
| `smartparser/packages/__init__.py` | **new** |
| `smartparser/packages/models.py` | **new**: EvidencePackage, EvidenceFile, FileVersion, PackageSnapshot, PackageValidationResult (+ HandoffSummary, SnapshotEntry, PackageCheck, StatusChange) |
| `smartparser/packages/store.py` | **new**: file-based PackageStore (atomic package writes with a revision check; create-once snapshots and manifests; persisted cases and sessions) |
| `smartparser/packages/service.py` | **new**: PackageService (create, submit, resubmit, review wrappers, complete_review, pending, validate, activate, manifest, verify_snapshot) |
| `smartparser/orchestration/orchestrator.py` | **added** `complete_session` (APPROVED and complete session → confirmation + file mapping → reprocess → handoff → preview; re-verifies the original; incomplete → nothing written); `import hashlib` |
| `smartparser/review/audit.py` | **added** 15 event types: PACKAGE_CREATED, PACKAGE_FILE_RECEIVED, FILE_VERSION_CREATED, FILE_VERSION_VALIDATED, FILE_VERSION_REJECTED, RESUBMISSION_REQUESTED, RESUBMISSION_RECEIVED, FILE_VERSION_REVIEW_REQUIRED, FILE_VERSION_SUPERSEDED, FILE_VERSION_ACTIVATED, PACKAGE_VALIDATION_STARTED, PACKAGE_VALIDATION_FAILED, PACKAGE_VALIDATED, PACKAGE_SNAPSHOT_CREATED, PACKAGE_SNAPSHOT_ACTIVATED |
| `tests/test_packages_3b9.py` | **new**: 41 tests |
| `docs/UC042_SMART_PARSER_PHASE3B9_EVIDENCE_PACKAGE_AND_RESUBMISSION_REPORT.md` | this report |

**Not changed:**
- the canonical definitions, packaged rules, authority policy, POC policy, AI configuration and prompts;
- the classification, mapping, proposal, review, reprocessing and handoff logic;
- existing tests and evaluation corpora.

Outside the working copy, the session's regression helper script gained a 3B-9 entry. Temporary folders were created and removed.

## 16. Known limitations

| # | Limitation | Status |
|---|---|---|
| 1 | **Single-user.** No locking: the package revision check refuses a stale copy, but two simultaneous processes are not supported. The audit log and rule store remain unlocked across processes (3B-8 P1-2) | by design (brief); [P] lock file |
| 2 | **PDF evidence** is validated on content classification only (letters via the package's IN-02); no field extraction, no handoff, no preview | Phase 1 scope; [N] |
| 3 | **Content-level period rules and cross-file references** (`period_rule`, IN-14 recon_ref, etc.) are not applied at package level. They belong to the UC-042 engine during reconciliation. PV-06 checks period **identity** only | [N]; no rules invented |
| 4 | A file whose category cannot be identified from content needs the slot to be **declared**. If the content contradicts the declaration, the file is REJECTED (never switched) | by design |
| 5 | **Equal-count duplicate-claim files** (3B-8 structural finding) can only be held or rejected. In a package such a file ends REVIEW_REQUIRED until the reviewer rejects it and a corrected file is uploaded | owner decision pending (3B-8 §18) |
| 6 | **Interruption between intake creation and version recording** leaves an orphan intake (no version). Between snapshot write and package save, the retry reuses the snapshot. Finalisation of a review is still multi-step (3B-8 P1-3) | [P] |
| 7 | **Production authority authorises nobody**, so in production no review can be completed. Tests use the test-only policy | owner decision |
| 8 | **Reviewer identity** is supplied by the caller (no authentication) | [P] with the API |
| 9 | **No package-level REJECTED** (abandon a package) and no deletion; out of scope | [N] |
| 10 | **No API or UI**. The service functions are the integration surface | [P] |
| 11 | **Downstream use of a superseded snapshot.** After a voluntary correction fails, the older active snapshot stays active while the status shows RESUBMISSION_REQUIRED. Downstream consumers should select by `snapshot_id` from the manifest | documented |
| 12 | **Windows path length** for deep store roots: preview file names are long (3B-7 note) | keep store roots short |

## 17. Protected-path verification

| Check | Result |
|---|---|
| UC-042 authoritative source | 107 code files + 624 dataset files hash-identical; 0 files newer than the Phase 1 start; inspected read-only (`uc042lib/period.py`, `schema.py`, `pack/assemble.py`) |
| Desktop Smart Parser | 63 files hash-identical; nothing copied back |
| Clone E / original app / demo database | not accessed; all stores are pytest temporary folders |
| Live provider | none: recorded stubs; sockets blocked; 0 network-library imports in `smartparser` |
| POC policy / provider configuration | `DISABLED`; `AIConfig` default disabled; credentials, model, region and budgets untouched |
| Production authority | unchanged (scopes `{}`) |
| Submission | `submit_to_uc042` unchanged (always refuses) and never called (patched to fail in tests); manifests and snapshots carry `submission_authorised: false`, `reconciliation_status: NOT_RUN` |
| New infrastructure | none: plain JSON files, atomic replace, exclusive create |

## 18. Remaining decisions for the next phase

1. **Reconciliation integration.** How the manifest is consumed by the UC-042 engine (format approval, submission gate). Submission stays disabled until then.
2. **Voluntary correction of an accepted file.** Is it allowed (implemented, per §7.2), or should corrections be restricted to files that failed?
3. **Equal-count duplicate-claim files.** May a reviewer override a deterministic header match for one file (3B-8 decision 3)?
4. **Production authority roles** for FILE_MAPPING, CATEGORY_CONFIRMATION and CATEGORY_CONFLICT, so that package reviews can be completed outside tests.
5. **Required categories per package.** Is the UC-042 contract default (17 REQUIRED) always mandatory, or may an analyst define a subset, as the tests do with the five-file example?
6. **PDF evidence acceptance.** Is classification-only acceptance enough for the acknowledgement letters and policy until PDF extraction exists?
7. **API/UI** over `PackageService` (upload, pending list, review, activation, manifest), and the durable-review items still open from 3B-8 (locking, recoverable finalisation, authentication).
