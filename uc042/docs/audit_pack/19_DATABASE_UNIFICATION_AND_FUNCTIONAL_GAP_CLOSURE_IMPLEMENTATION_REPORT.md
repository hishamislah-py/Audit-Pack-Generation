# 19 — Database Unification and Functional Gap Closure: Implementation Report

ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

Date: 4 November 2026.

**Scope:**

- consolidate `uc042` and `uc042_history` into one PostgreSQL database;
- make reconciliation, exception investigation and AI investigation explicit, separate operations;
- close the five outstanding issues from report 18.

**Decisions from the business owner (4 November 2026):**

- **June investigation.** It is an authorisation discrepancy. It is preserved but excluded from the approved published set.
- **September.** Option A: merge the two records into one `PER-2026-09`, keeping the history title and the operational PROCESSED status.
- **No live AI** during the migration. None was made in that phase.
- **No UI redesign.** Frontend changes are limited to what prevents broken or misleading behaviour.

**Follow-up instruction (same day): final operational handover and end-to-end functional validation.** Complete the transition (catch-up, single backend, retirement of `uc042_history`) and prove that the application works end to end. **Live AI calls were authorised for this validation.** Section 13 reports it; sections 4, 7, 10, 11 and the assessment are updated.

---

## 1. Baseline before any change

| Check | Result |
|---|---|
| Python suite (fresh run) | 576 run: 574 passed, 1 skipped (optional live AI), **1 failed** |
| Frontend | 35 passed, 2 skipped; build and type check OK |
| File baseline | 1,216 files hashed (`sha256sum`), excluding `.venv`, `node_modules`, `dist` and `db_backups` |

**The baseline failure was real and not caused by code.** The failing test is `test_demo_history.OutputPacks.test_demo_output_is_isolated_and_deterministic_only`. It found a June investigation that did not exist at the end of Phase 7:

- **Artefact:** `demo_history/investigations/PACK-H202606-PER-2026-06-a07de266b389/EXC-H202606-01/INV-EXC-H202606-01-c7b353b53fb3`.
- **Registry:** registered as `uc042_history` entry 2 (`NEW_PUBLICATION`, 2026-11-04T07:18:08Z).
- **Origin:** job `JOB-a1f539840d090ef197d34b85`, submitted through the application by `demo-reviewer` at 07:17:22Z, while the history backend was running.

Section 7 records how it is handled. Per the decision, the guard test was **not** changed to accept it, so it still fails (§10).

## 2. Architecture

```
                    ┌──────────────────────────── one backend (python -m uc042app) ────────────────────────────┐
  React UI ──API──► │ services: packs · investigations · cases · reviews · final packs · monthly (reconciliation) │
                    │                 │ StorageLayout (services/layout.py)                                       │
                    │     primary root set            storage profile "historical-demo"                        │
                    │     packs/ uc042_dataset/       demo_history/packs, datasets, investigations, final_packs│
                    │     investigations/ final_packs/ (served because the DB records it on Jan–Aug periods)   │
                    └───────────────┬──────────────────────────────────────────────────────────────────────────┘
                                    │ one PostgreSQL database: uc042  (Alembic head 0003_unified_schemas)
                                    ├── schema audit       periods, pack references, reconciliation runs, reviews,
                                    │                      final-pack records, publication registry, authorisations,
                                    │                      record provenance
                                    ├── schema operations  upload batches, source documents, jobs, exception cases
                                    │                      and case entries, activity log
                                    └── public             alembic_version only
```

### Why a storage layout as well as one database

Packs, investigations and final packs are write-once files, not database rows (the design since report 08). The two environments kept them in different folders:

- September: `packs/`, `investigations/`;
- January–August: `demo_history/...`.

These folders were **not** moved or merged. Moving them would mean rewriting paths that the published artefacts' provenance points to. Instead:

- **Library profiles.** `uc042lib/investigation/roots.py` now gives each profile its final-packs root, and adds:
  - `profile_for_period(period, default=None)`;
  - `period_of_pack`;
  - `profile_for_pack`;
  - `storage_profile(name)`, which returns validated roots.

  The existing behaviour is unchanged: there is still no silent fallback to September.
- **`StorageLayout`.** The new `uc042app/services/layout.py` serves the primary roots plus every profile that the database records on a period (`audit.reconciliation_periods.storage_profile`). `UC042_STORAGE_PROFILES` can add a profile before the database records it.
- **How a pack is resolved.** By where it physically is:
  - it must be in exactly one root set (two copies is a `DUPLICATE_PACK` integrity failure);
  - a pack in a profile's root must belong to one of that profile's periods (`PACK_OUTSIDE_PROFILE`);
  - its investigations, datasets and final packs are read and written in the same root set.
- **New packs.** Packs produced from uploads are always published in the primary root.

### Users schema

Not created. The application has no user accounts: the reviewer is the configured analyst reference. Creating an empty `users` schema would imply something that does not exist. It is the natural home when authentication is introduced.

## 3. Ownership and dependency map

### Before unification

Both databases were on one server (PostgreSQL 18.4, 127.0.0.1:5433), each with one `public` schema at revision `0002_title_submissions`. There was no cross-database code: each backend instance used exactly one database, chosen by `UC042_DATABASE_URL`, with its own folder settings.

| Entity (table) | `uc042` rows | `uc042_history` rows | Notes |
|---|---|---|---|
| reconciliation_periods | 1 (PER-2026-09, PROCESSED) | 9 (Jan–Aug PROCESSED; **PER-2026-09 EMPTY**, title set 12:38 today) | **collision: PER-2026-09** |
| period_packs | 9 (September scenarios) | 8 (one per historical month) | no overlap |
| jobs | 0 | 4 (Feb investigation ×2, Feb preview, **June investigation**) | |
| review_sessions / review_decisions / previews | 0 / 0 / 0 | 1 / 1 / 1 | February final review |
| final_pack_records | 0 | 1 (GENERATED, `FAP-H202602-…b8dd53bd2449`) | |
| investigation_registry | 0 | 2 (seq 1 February; **seq 2 June**) | no sequence collision |
| activity_events | 1 (id 1) | 9 (ids 1–9) | **id collision** (serial) |
| upload_batches, source_documents, processing_runs | 0 | 0 | |

**Immutable published material** (files, referenced by ID; never modified):

- the 8 historical packs;
- the 9 September packs;
- the February investigation artefacts `6b1425b437f4` (registered) and `a3fd3fd2e9ed` (Phase 6A, unregistered);
- the June artefact `c7b353b53fb3`;
- the February final pack;
- the datasets.

**Code that touched the database:**

- `uc042app/db` (engine, models, repositories, migrations);
- `services/*` through the repositories;
- `admin.py`;
- `/health`.

**Backups and recovery before this phase:** manual `pg_dump -Fc` into `uc042/db_backups/` (Phase 7).

### After unification

The same entities, in schemas by ownership:

| Schema | Tables |
|---|---|
| `audit` | `reconciliation_periods` (+ `storage_profile`), `period_packs`, `processing_runs`, `review_sessions`, `review_decisions`, `previews`, `final_pack_records`, `investigation_registry`, new `investigation_authorizations`, new `record_provenance` |
| `operations` | `upload_batches`, `source_documents`, `jobs`, `activity_events`, new `exception_cases`, new `exception_case_entries` |

**Foreign keys:**

- **Existing (moved with their tables):**
  - `period_packs` → `reconciliation_periods`;
  - `upload_batches` → `reconciliation_periods`;
  - `source_documents` → `upload_batches`;
  - `processing_runs` → `reconciliation_periods` / `upload_batches`;
  - `review_decisions` → `review_sessions`;
  - `previews` → `review_sessions`.
- **Added:**
  - `period_packs.processing_run_id` → `processing_runs`;
  - `source_documents.replaces_document_id` → `source_documents` (correction version history);
  - `exception_cases.period_id` → `reconciliation_periods`;
  - `exception_case_entries.case_id` → `exception_cases`.
- **New indexes:**
  - `period_packs(pack_id)`;
  - `source_documents(replaces_document_id)`.

## 4. Migration and rollback procedure

### Schema migration

`uc042app/db/migrations/versions/0003_unified_schemas.py`:

- creates the `audit` and `operations` schemas;
- moves the 12 tables out of `public` with `ALTER TABLE … SET SCHEMA`, so rows, keys, indexes and the activity sequence move without being copied;
- adds `storage_profile`, the foreign keys and indexes above, and the four new tables.

The downgrade reverses all of this. It **refuses** while the new tables or `storage_profile` hold data: after a data migration, rollback means restoring the backup.

### Data migration

Run with `python -m uc042app.admin unify-databases` (`uc042app/db/unify.py`).

- **Inputs:**
  - the target is `UC042_DATABASE_URL` at head;
  - the source must be at `0002_title_submissions` and is read through one `REPEATABLE READ READ ONLY` snapshot. Nothing in the source is changed.
- **Files are verified before any write:**
  - every source pack reference is a verified pack with the registered content hash, in the source profile's root;
  - every registry entry's artefact matches its pinned hashes;
  - every GENERATED final-pack record points to a final pack that passes `verify_final_pack`.
- **One transaction.** Any stop or failure rolls back everything, so no partially migrated record can exist.
- **Identifiers are preserved.** Activity events are the only renumbered records, and they keep their original ID in provenance.
- **Provenance.** Every source row gets one `audit.record_provenance` row, recording:
  - the source database, table and key;
  - the target key;
  - the action: `COPIED`, `IDENTICAL`, `MERGED` or `RENUMBERED`;
  - the complete original row.
- **Resumable.**
  - A row that already has provenance is skipped; new source rows are copied by a re-run.
  - A migrated row that has since **changed** in the source stops the run.
  - A re-run never copies anything twice.
- **Approved period merge** (`--approve-period-merge PER-2026-09`):
  - the target status is kept unless it is EMPTY;
  - the target title is kept unless empty;
  - `last_processed_at` is the later of the two;
  - the target row as it was before the merge is stored in provenance as `MERGE_TARGET`.
- **Stop conditions** (each tested; nothing is written when one triggers):
  - an unapproved key collision with different values;
  - a source at another revision;
  - a changed artefact (pack, registry-pinned investigation file or final pack);
  - a source period outside the profile that holds packs (ambiguous storage);
  - a source row changed after migration.

### Procedure as executed, 4 November 2026

1. **Backups.** `pg_dump -Fc` into `uc042/db_backups/`:
   - before any change: `uc042_before_0003_unification_20261104.dump` (sha256 `8e4ed8f3…`) and `uc042_history_before_0003_unification_20261104.dump` (`caf1fa0e…`);
   - immediately before the live run: `uc042_immediately_before_unification_20261104.dump` (`5719f94e…`) and `uc042_history_immediately_before_unification_20261104.dump` (`6b8ceb81…`).
2. **Rehearsal.** Both backups were restored into `uc042_rehearsal` and `uc042_history_rehearsal`. Then:
   - `db-upgrade`;
   - unify without approval: **stopped** on PER-2026-09, as designed;
   - dry run;
   - real run, then a re-run (all `ALREADY_MIGRATED`);
   - authorisations, `verify-registry`, `verify-pack-references` and an API smoke check: all as expected;
   - the rehearsal databases were dropped.
3. **Live:**
   - `db-upgrade` of `uc042` gave `0003_unified_schemas`;
   - a dry run gave the same counts as the rehearsal;
   - the real run was migration `UNIFY-20261104T081343Z-a3fa26b5`.
4. **Authorisation decisions** (`record-investigation-authorization`, §7).
5. **Verification** (§5).
6. **Retire the legacy database: done in the follow-up phase (§13.1).** The history backend was stopped gracefully (Ctrl+C to its console), the catch-up below found nothing new (36 `ALREADY_MIGRATED`), and `uc042_history` is now `uc042_history_retired_20261104`, read-only by default.

   Commands, from `uc042/`, as originally specified:

   ```powershell
   # a. stop the old history backend (Ctrl+C in its window), then catch anything it wrote after the snapshot:
   $env:UC042_APP_STATE_DIR = "$env:USERPROFILE\uc042_runtime\app_state"; $env:UC042_DOCUMENT_STORE = "$env:USERPROFILE\uc042_runtime\document_store"
   .\.venv\Scripts\python.exe -m uc042app.admin unify-databases --source-database uc042_history --source-profile historical-demo `
       --approve-period-merge PER-2026-09 --source-state-dir demo_history_app\app_state
   # expected: every row ALREADY_MIGRATED (plus any new rows COPIED); a STOP means the old backend changed a migrated row
   # b. retire it: rename, and make it read-only by default (reversible; the dump files remain the recovery copy)
   #    ALTER DATABASE uc042_history RENAME TO uc042_history_retired_20261104;
   #    ALTER DATABASE uc042_history_retired_20261104 SET default_transaction_read_only = on;
   ```

   It can be dropped after acceptance. The backups are the recovery copy.

### Rollback

1. Stop the backend.
2. Restore `uc042_immediately_before_unification_20261104.dump` into `uc042`: `pg_restore --clean --if-exists -d uc042 <dump>`, or drop, recreate and restore.
3. Rename the retired database back and make it writable again:
   `ALTER DATABASE uc042_history_retired_20261104 RENAME TO uc042_history;`
   `ALTER DATABASE uc042_history RESET default_transaction_read_only;`
4. Start the two backends as in report 18.

To return to the state **after** the unification and catch-up instead (for example after a failed later change), restore `uc042_after_catchup_20261104.dump` into `uc042`.

**Backups in `uc042/db_backups/`** (none deleted):

| File | Taken | SHA-256 (prefix) |
|---|---|---|
| `uc042_before_0002_20261104.dump`, `uc042_history_before_0002_20261104.dump` | before report 18's migration 0002 | — |
| `uc042_before_0003_unification_20261104.dump` | before any change of this report | `8e4ed8f3…` |
| `uc042_history_before_0003_unification_20261104.dump` | same | `caf1fa0e…` |
| `uc042_immediately_before_unification_20261104.dump` | immediately before the live unification | `5719f94e…` |
| `uc042_history_immediately_before_unification_20261104.dump` | same | `6b8ceb81…` |
| `uc042_after_catchup_20261104.dump` | after the catch-up, before retirement | `ec284999…` |
| `uc042_history_after_catchup_20261104.dump` | the legacy database as retired | `2e84e434…` |

Because `0003` refuses to downgrade while migrated data exists, rollback is never a downgrade. No files need restoring, because the migration changes none.

## 5. Data-integrity verification (live)

| Check | Result |
|---|---|
| Row counts | periods 1 + 9 − 1 merged = **9**; pack references 9 + 8 = **17**; activity 1 + 9 + 1 `DATABASE_UNIFIED` + 2 authorisation = **13**; registry **2**; jobs **4**; review session, decision, preview, final-pack record **1** each |
| Provenance | **37** rows: 36 source rows, each exactly once (checked inside the transaction), plus 1 `MERGE_TARGET` |
| September | one `PER-2026-09`: status **PROCESSED** (operational), title **"September 2026 Reconciliation Audit"** (history), 9 scenario pack references, both activity trails (`PERIOD_REGISTERED_FROM_PACKS` from `uc042`, `PERIOD_OPENED` from history) |
| Historical periods | Jan–Aug, `storage_profile = historical-demo`, one verified pack each |
| `verify-registry` | 2 entries, all verified (seq 1 `[authorisation: APPROVED]`, seq 2 `[authorisation: AUTHORIZATION_DISCREPANCY]`) |
| `verify-pack-references` | **25 references, 0 problems**: 17 period packs, 4 jobs, 1 review, 1 final-pack record, 2 registry entries |
| Final pack | `FAP-H202602-PER-2026-02-v1-b8dd53bd2449` verifies through the API, served from `demo_history/final_packs` |
| Referential integrity | enforced by the foreign keys; invalid inserts are rejected with SQLSTATE 23503 (tested) |
| Source database | `uc042_history` row counts identical before and after; only read |
| Files | 1,216-file baseline re-checked. **No file changed** in `packs/`, `investigations/`, `uc042_dataset/`, `demo_history/` or `UC042_JAN_AUG_HISTORICAL_DEMO/`. Changed and added files are only the source, test and documentation files of this phase. No `uc042/app_state` or `uc042/final_packs` was created. |

**API check against the live unified database** (in-process, read-only, provider refused):

- **Health:** `ok`, database `uc042`, storage profiles `primary`, `historical-demo`.
- **Periods:** all 9 months are listed from one database.
  - February: FINAL_PACK_PUBLISHED, 1 published investigation, 1 excluded.
  - June: 1 excluded.
- **Packs:** 17.
- **Cases:** none, since nothing opens one automatically.

## 6. Workflow changes

### A. Reconciliation (explicit, per period)

New endpoint: `POST /api/v1/periods/{period_id}/reconciliation` with `{purpose: INITIAL | REASSESSMENT, reason}`.

- It runs the **existing deterministic engine**, unchanged, over the period's current confirmed document set, through the existing processing run.
- It is refused with `NO_CONFIRMED_DOCUMENTS` until a batch is uploaded, validated and confirmed.
- **Execution history.** Runs record `purpose` and `reason`, and new packs are written once to the primary root.

Nothing reconciles on its own. The test `test_nothing_reconciles_or_investigates_on_its_own` checks that none of these create a run, job or case:

- start-up;
- upload;
- reading the period list, a period or a pack;
- confirmation;
- a restart.

Start-up only registers existing packs under their period, as before.

### B. Exception investigation cases (explicit, per exception)

`services/cases.py` and `routers/cases.py`:

- `POST /packs/{pack}/exceptions/{exc}/case` opens a case. There is one case per exception; a second request returns the same case.
- `GET /cases`, `GET /cases/{id}`.
- `POST /cases/{id}/entries`.

The case stores:

- exception reference, period, status (OPEN/CLOSED) and human resolution;
- an **append-only** history with these entry kinds:
  - **NOTE**;
  - **EVIDENCE** (supporting evidence);
  - **EVIDENCE_GAP**;
  - **OBSERVATION** (confirmed; must cite evidence);
  - **HYPOTHESIS**;
  - **DECISION** (human);
- timestamps and revision;
- activity events (`CASE_*`).

Rules:

- **Evidence references must exist.** A reference must be a pack evidence ID (record or file), a document uploaded for the same period, or a published investigation of the exception. Anything else is refused as `INVALID_EVIDENCE_REF`, so evidence cannot be fabricated.
- **Resolution.** `human_resolution` starts **UNRESOLVED**. It changes only through a DECISION entry with a resolution (`UNRESOLVED`, `EXPLAINED_BY_ANALYST` or `ESCALATED`) and a comment, which also opens or closes the case.
- **Concurrency.** Optimistic, with `CASE_CHANGED` on conflict.
- **Pack untouched.** The pack's deterministic exception (status, review status, results) is shown as recorded and never changed. Tests compare the pack files and the API exception view before and after.

### C. AI investigation (explicit, per case)

`POST /cases/{id}/ai-investigation` (optionally with `retry_of`) reuses the existing V2 tools-mode `InvestigationService.start`. That means the same:

- evidence retrieval and validation;
- provider check: `PROVIDER_NOT_CONFIGURED`, and simulated output is refused;
- duplicate-submission protection: `INVESTIGATION_ACTIVE`;
- job history and failure handling;
- explicit retries.

The request is recorded in the case (`AI_REQUEST`, with job and retry). Results stay in the investigation artefact and are listed in the case with their eligibility. The AI's own findings keep the V2 distinction between confirmed observations, hypotheses, missing evidence and next steps.

Nothing changes the exception or the case resolution. Tested: after a completed AI job the case is still OPEN/UNRESOLVED, the findings say `NOT_RESOLVED_BY_INVESTIGATION`, and only the requested case was investigated.

The AI closing summary remains a separate final-review operation and is unchanged.

**No live AI call was made.** All AI tests use the existing offline mock provider. The live-provider factory is patched to fail the test if it is ever reached.

## 7. June investigation: authorisation discrepancy

- **Preserved unchanged:** the artefact files, the registry entry (`audit.investigation_registry` seq 2, copied verbatim), and job `JOB-a1f5…` with its activity.
- **Decision recorded.** New append-only table `audit.investigation_authorizations`:

  | # | Investigation | Status | Basis |
  |---|---|---|---|
  | 1 | `INV-EXC-H202602-01-6b1425b437f4` | APPROVED | Phase 6B (report 17) |
  | 2 | `INV-EXC-H202606-01-c7b353b53fb3` | **AUTHORIZATION_DISCREPANCY** | "Business owner decision 2026-11-04: not explicitly authorised … Artefact and registry entry seq 2 preserved unchanged; excluded from the approved published set (report 19)." |

- **Effect:**
  - the June investigation is **not eligible** for a final audit pack, with reason `authorisation: AUTHORIZATION_DISCREPANCY …`;
  - it is not counted as published;
  - it is counted as excluded.

  `verify` still reports artefact and registry verified, because they are intact. A later APPROVED row would supersede the decision (latest in force), and that is recorded too.
- **Guard test, resolved in the follow-up phase** (you asked me to update it if it asserted an outdated assumption, without weakening it). Its outdated assumption was "the demo folder contains no investigation except the authorised February ones". It now asserts the authorisation rules instead:
  - The closed-world check is kept: any other investigation or final pack in `demo_history` still fails the test.
  - The June artefact is the one named exception. It is pinned byte for byte: five SHA-256 values, the same files as the registry entry.
  - No file in `demo_history/final_packs` may reference it.

  To show the test is not weakened, it was run against three tampered copies of `demo_history`, and each must fail:
  - a June file changed;
  - an extra unauthorised investigation added;
  - the June ID planted in a final pack.

  All three fail.

  In addition, `test_an_authorisation_discrepancy_is_kept_but_excluded_from_the_approved_set` now proves that a discrepant investigation is never selected by default in a review, and that selecting it explicitly is refused with `INELIGIBLE_SELECTION`.

## 8. Phase 7 outstanding issues

| # (report 18 §14) | Resolution |
|---|---|
| 1 Reassessment had no dedicated action | `purpose: REASSESSMENT` on the reconciliation endpoint. It requires evidence received after the latest final pack (`NOTHING_TO_REASSESS` otherwise) and a reason, records `REASSESSMENT_STARTED`, and the period shows `reassessment_runs` and `latest_reassessment_status`. Published packs are never changed; a new final-pack version still goes through the normal review. |
| 2 Historical periods had empty titles | The API returns the stored title, or the month's default with `title_source: DERIVED`. Records are not rewritten; "Change title" stores one (`STORED`). |
| 3 February counted the unregistered Phase 6A artefact | Only **registered, not-discrepant** investigations count as published. The rest are reported as `excluded_investigations`, and the archive shows "+N excluded". February now shows 1 published, 1 excluded. |
| 4 Corrections only on the report page | The upload page offers "Correction of an earlier document", with a **Replaces** selector and a one-file limit. |
| 5 The dashboard upload button targeted the current month | It now targets the **selected** month, and the current month only when none is selected. |

Also fixed: with a month selected but no pack open, the sidebar workflow items "Reconciliation pack" and "Exceptions & investigation" were greyed out. They now open that month's report sections. They stay disabled, with an explanation, only when no month is selected.

## 9. Frontend changes (minimum)

- **`types.ts`:** optional fields for storage profiles, authorisation, title source, excluded and reassessment counts.
- **`UploadPage`:** corrections.
- **`DashboardPage`:** upload target.
- **`AppShell`:** sidebar links.
- **`ReportPages`:** the environment note now says that every period of the database is listed, and names the storage profiles (the old "not combined" text would now be wrong), plus the "+N excluded" marker.

There is no UI for cases yet; they are API-complete for the next UI phase.

## 10. Test results (exact)

| Suite | Result |
|---|---|
| Python `python -m unittest` (full, after implementation) | **603 run: 601 passed, 1 skipped** (optional live AI test), **1 failed**: the June guard test (§7), the same failure as the baseline |
| New `tests/test_unification.py` | 27 tests (part of the total above): storage resolution 3, unified backend 5, explicit reconciliation 4, cases and AI 6, migration (PostgreSQL) 9 |
| Frontend `vitest run` | **39 passed, 2 skipped** (the opt-in live-backend tests) |
| Frontend build (`tsc --noEmit` + Vite) | OK |
| `check_contract.py` | OK (37 interfaces) |

**Follow-up phase (final, after all fixes):**

| Suite | Result |
|---|---|
| Python `python -m unittest` (full) | **605 run: 604 passed, 1 skipped** (optional live AI test), **0 failed**. The June guard test now passes (§7); +2 new regression tests |
| Frontend `vitest run` | **40 passed, 2 skipped** (opt-in live-backend tests); +1 new regression test |
| Frontend production build (`tsc --noEmit` + Vite) | OK |
| `check_contract.py` | OK (37 interfaces) |
| `verify-registry` (live `uc042`) | 2 entries, all verified (seq 1 APPROVED, seq 2 AUTHORIZATION_DISCREPANCY) |
| `verify-pack-references` (live) | 25 references, 0 problems |
| Database integrity checks (live, read-only) | 20/20 (§13.4) |
| Manual end-to-end checks | **356 passing checks** in the final runs across live API, live database, live UI, clone workflows and clone UI (§13.4), separate from the automated counts; every failure on the way is explained in §13.6 |
| Protected files | 827 files identical before and after (including after the full suite) |

**Test changes and why:**

- **`tests/test_db.py`**:
  - `tables()` now lists tables in `public`, `audit` and `operations`; the assertions themselves are unchanged (upgrade creates all, downgrade removes all);
  - the migration test empties the disposable database first, because the 0003 downgrade refuses to drop data.
- **`tests/api_support.py`:** truncates schema-qualified table names.
- **`reports.test.tsx`:** the Phase 7 archive test expected "the separate environments are not combined", which is now false by decision. It now expects the single-database note.

No test was weakened. In the migration phase the guard test was not changed; in the follow-up phase it was updated as instructed, without weakening (§7).

**Every failure investigated:**

- The only failure is `test_demo_output_is_isolated_and_deterministic_only`, which is the June discrepancy (§1, §7). It fails identically in the baseline.
- During development:
  - three errors in my own new tests (expected 400 instead of 422; a wrong PDF path; a wrong row count);
  - a PostgreSQL `CREATE`/`DROP DATABASE` that needed an autocommit engine.

  All four were fixed in the tests themselves.

## 11. Remaining limitations and recommendations

1. **Legacy database: retired** (follow-up phase, §13.1). It remains available read-only as `uc042_history_retired_20261104`; it can be dropped after acceptance (the dump files are the recovery copy). **Decision for you:** when to drop it.
2. **Seven September POC investigation artefacts are unregistered** (unchanged; **decision for you**). They are the original artefacts under `investigations/`; the operational registry was always empty. They were never eligible, and they now show as "excluded" rather than "published". As a result, September reads "Deterministic pack available" instead of "Investigation available". Registering them (`import-legacy-investigations`, as `LEGACY_BASELINE_IMPORT`) is a separate decision.
3. **February Phase 6A artefact `a3fd3fd2e9ed`.** Authorised in report 16 but never registered, so it is listed, not counted and not eligible. No authorisation row was recorded for it, because the registry decides first.
4. **June guard test: resolved** (follow-up phase, §7). The June artefact itself stays an `AUTHORIZATION_DISCREPANCY` until you decide otherwise (**decision for you:** keep, archive, or approve).
5. **Reassessment of a historical month needs its complete document set uploaded.** February's source files exist only as a dataset, not as uploaded documents, so a February reassessment is refused with `INCOMPLETE` and the missing evidence is listed. That is correct behaviour, but the documents would have to be uploaded first.
6. **Runtime folders for the unified backend** (in use): `UC042_APP_STATE_DIR=%USERPROFILE%\uc042_runtime\app_state` and `UC042_DOCUMENT_STORE=%USERPROFILE%\uc042_runtime\document_store`; start-up commands in §13.2. The defaults inside `uc042/` trip the project guard test. Neither database had uploaded documents, so no document store needed migrating.
7. **Zero-balance safety rule (`ZERO_PATTERN`).** Unchanged, and its false positive is still open (report 17).
8. **No user accounts or users schema.** To be designed with authentication.
9. **Operations.** Run PostgreSQL as a service. Stopping the shell that started `pg_ctl` once crashed the postmaster (report 18).
10. **Clean-up for you:** delete `C:\app_state` (an empty lock file from a corrupted path, §13.7). Optionally remove the validation clone: database `uc042_e2e_rehearsal` and folder `%USERPROFILE%\uc042_e2e` (kept as evidence of §13).
11. **Windows long paths are disabled**: keep the project at a short path (§13.7), or enable `LongPathsEnabled`.
12. **UI request duplication and the post-reassessment status** (§13.8): observations, not changed.

## 12. Files

**New:**

- `uc042app/db/migrations/versions/0003_unified_schemas.py`
- `uc042app/db/unify.py`
- `uc042app/services/layout.py`
- `uc042app/services/cases.py`
- `uc042app/api/routers/cases.py`
- `tests/test_unification.py`
- this report

**Changed:**

- `uc042lib/investigation/roots.py`
- `uc042app`:
  - `config.py`, `ids.py`, `admin.py`;
  - `db/__init__.py`, `db/models.py`, `db/repositories.py`;
  - `repositories/base.py`, `repositories/files.py`;
  - `services/__init__.py`, `packs.py`, `investigations.py`, `final_packs.py`, `reviews.py`, `monthly.py`;
  - `api/main.py`, `api/schemas.py`, `api/routers/monthly.py`, `api/routers/system.py`.
- `tests/test_db.py`, `tests/api_support.py`.
- `frontend/src`:
  - `api/types.ts`;
  - `components/layout/AppShell.tsx`;
  - `pages/DashboardPage.tsx`, `pages/ReportPages.tsx`, `pages/UploadPage.tsx`;
  - `test/reports.test.tsx`.

**Database:** `uc042` at `0003_unified_schemas` with the migrated data, and 4 new dump files in `db_backups/`.

**Follow-up phase (§13):**

- `uc042app/services/monthly.py` (correction of a supporting document), `uc042app/services/investigations.py` and `uc042app/api/routers/monthly.py` (one pack load per aggregate);
- `frontend/src/components/workspace/AiPanel.tsx`, `frontend/src/pages/WorkspacePage.tsx` (load errors shown), `frontend/src/components/layout/AppShell.tsx` (tooltip text);
- tests: `tests/test_demo_history.py` (guard test), `tests/test_unification.py` (2 tests extended/added), `tests/test_monthly_reports.py` (1 added), `frontend/src/test/screens.test.tsx` (1 added);
- database: `uc042_history` renamed to `uc042_history_retired_20261104` (read-only); 2 more dumps in `db_backups/`.

## 13. Final transition and end-to-end functional validation (follow-up phase)

### 13.1 Transition to one database

1. **Old backend identified:** pid 9784, started from VS Code terminal pid 524 via the venv launcher pid 22900.
   - All five connections to `uc042_history` belonged to it (client ports matched to pid 9784).
   - No job was queued or running, and its row counts equalled the post-migration snapshot.
2. **Stopped gracefully** by sending Ctrl+C to that console, the same as pressing it in the window.
   - Pids 9784 and 22900 exited; the terminal itself and the frontend's separate terminal were untouched.
   - Afterwards: no listener on 8000, and **0 connections** to `uc042_history`.
3. **Catch-up**, exactly as in §4 step 6a, with `--source-state-dir demo_history_app\app_state` (the old instance lock was free):
   - dry run, then the real run `UNIFY-20261104T092615Z-6c31a186`;
   - result: **all 36 source rows `ALREADY_MIGRATED`, nothing copied**, because the old backend wrote nothing after the snapshot;
   - the only change is its own `DATABASE_UNIFIED` audit event (activity 13 → 14).
4. **Catch-up rehearsal on copies of the post-catch-up dumps.** Provenance in the copy was relabelled to the copy's source name:

   | Run | Situation | Result |
   |---|---|---|
   | 1 | A migrated row changed in the source (a period title) | **STOPPED (nothing written)**: "changed in the source after it was migrated … (historical data conflict)" |
   | 2 | The change reverted; a late activity event added | The late event was **copied** (`RENUMBERED`, original ID kept in provenance) |
   | 3 | Re-run | Nothing copied twice |

   The rehearsal databases were then dropped.
5. **Backups after the catch-up:** `uc042_after_catchup_20261104.dump` and `uc042_history_after_catchup_20261104.dump` (§4 Rollback).
6. **Retirement** (§4 step 6b), only after every check below had passed:
   - re-checked 0 connections;
   - `uc042_history` renamed to **`uc042_history_retired_20261104`**, with `default_transaction_read_only = on`.

   Verified afterwards:
   - the old name no longer exists;
   - the rows are still readable (9 periods, 2 registry entries) and row counts are identical to before the stop;
   - a write is refused (read-only transaction);
   - `uc042_test` is untouched and separate.

### 13.2 Unified runtime

**Configuration:**
- one database, `uc042`, from `UC042_DATABASE_URL` in `.env` (no override);
- one backend on 127.0.0.1:8000;
- `UC042_APP_STATE_DIR=%USERPROFILE%\uc042_runtime\app_state`;
- `UC042_DOCUMENT_STORE=%USERPROFILE%\uc042_runtime\document_store`;
- frontend: Vite on 127.0.0.1:5173.

**Health:**
- `ok`, database `uc042`, environment label "Database uc042";
- storage profiles `primary` (September) and `historical-demo` (January–August, from `audit.reconciliation_periods.storage_profile`).

**No file was moved, renamed, copied into the project or rewritten.** All **827** files under the following folders hash identically before and after this phase:
- `packs/`, `investigations/` and `uc042_dataset/`;
- `demo_history/`;
- `UC042_JAN_AUG_HISTORICAL_DEMO/`.

No `uc042/app_state`, `uc042/final_packs` or `uc042/document_store` was created.

**Start the backend** (PowerShell, from `uc042/`, PostgreSQL running on 5433):

```powershell
$env:UC042_APP_STATE_DIR  = "$env:USERPROFILE/uc042_runtime/app_state"
$env:UC042_DOCUMENT_STORE = "$env:USERPROFILE/uc042_runtime/document_store"
.\.venv\Scripts\python.exe -m uc042app --port 8000
# frontend, in a second window from uc042/frontend:  npm run dev
```

Forward slashes are deliberate. In some tools a `\u` followed by hex digits is turned into a Unicode character. This report's own commands were corrupted that way, which is now fixed, and so was one command in this session (§13.7).

### 13.3 How the workflows were tested

| Environment | Used for | Why |
|---|---|---|
| **Live**: backend 8000 + Vite 5173 on `uc042` | Read-only checks: HTTP API, database integrity, browser UI | Historical records and published artefacts must not be touched |
| **Isolated clone**: backend 8001 + Vite 5174, unchanged application code (`python -m uc042app`) | Every write workflow: upload, reconciliation, cases, live AI, review and publication | Database `uc042_e2e_rehearsal`, restored from `uc042_after_catchup_20261104.dump`. Primary roots on copies of `packs/`, `investigations/` and `uc042_dataset/` under `%USERPROFILE%\uc042_e2e`. The historical-demo profile still reads the real `demo_history/` (read-only use; nothing was generated into it). |

The test period is the clone's `PER-2026-09`. The documents are the 19 files of the S05 scenario dataset, uploaded through the API and the UI exactly as an analyst would.

**Driver:** staged Python scripts over real HTTP, plus headless Microsoft Edge driven through the DevTools protocol for the UI.

### 13.4 Results: manual end-to-end scenarios (separate from the automated suite)

| Scenario | Checks | Result |
|---|---|---|
| Live API, read-only: health, 9 months, titles, statuses, storage profiles, every pack (opens, verifies, exceptions, sources, reconciliation), June/February authorisation and verification, February final pack (verify, HTML, PDF, JSON), CORS | 121 | all pass |
| Live database integrity: head, schemas, constraints validated, no orphans, provenance (36 history rows once each), September merge provenance and both trails, authorisations, registry seq 1/2, both unify runs | 20 | all pass |
| Live UI, browser on 5173: dashboard; archive (9 months, "+N excluded"); each of the 9 report pages; month picker; month kept on dashboard, sidebar and upload; dashboard upload button targets the selected month; historical and September packs; February final pack; June shown "Not eligible: authorisation: AUTHORIZATION_DISCREPANCY"; no JS errors or failed requests; nothing triggered by browsing | 29 | all pass |
| A/B upload and reconciliation (clone) | 16 + 12, plus a concurrent 3-request test | pass; one sequential "concurrency" check was my test-design error, replaced by the concurrent test |
| C exception case lifecycle | 27 | all pass |
| D live AI investigation: failure, duplicates, retry, output | 18 + 13 | pass; one check read a wrong field name, and the failure reason was verified directly (13.5) |
| E/F review, closing summary, final pack | 36 | all pass |
| G evidence after publication, correction, reassessment, case continuation, close/reopen | 35 + 6 | 1 real defect found and fixed (13.6) |
| June in the application (clone) | 6 | all pass |
| UI on the clone (5174): additional-evidence upload and correction through the browser, report / final pack / workspace showing the E2E outputs | 17 of 18 | the workspace check timed out once, after passing in an earlier run; a separate trace showed the findings render in 5.3 s with every request returning 200, and that led to fix 3 in 13.6 |

**A. Months and uploads:**
- An upload to an unknown period is refused (404), and an invalid submission kind is refused (422).
- An unsupported or empty file is stored but marked `ERROR`, so its batch can never be processed.
- The 19 S05 documents uploaded to the selected month are persisted. Every stored original returns byte-identical content (SHA-256 re-verified).
- Neither the upload nor any page read starts a reconciliation, case or AI job.

**B. Reconciliation:**
- Reconciliation is refused until the batch is confirmed (`NO_CONFIRMED_DOCUMENTS`).
- It started explicitly and `SUCCEEDED`, publishing `PACK-CASE-PER-2026-09-6134d5781879` once into the primary root, referenced once by the period (`UPLOAD_PROCESSING`).
- **Deterministic:**
  - its exceptions (EXC-CASE-01 Critical, EXC-CASE-02 High, both −812.40 GBP, OPEN / AWAITING_HUMAN_REVIEW) equal the POC pack built from the same inputs;
  - the full reconciliation output is identical apart from the pack ID.
- Repeated requests: a sequential repeat after completion is a new run with `ALREADY_EXISTS` and the **same** pack (no duplicate).
- Three **simultaneous** requests: one accepted, two refused `RUN_IN_PROGRESS`.
- Runs, pack reference, documents and case all persisted across two backend restarts.

**C. Case lifecycle on EXC-CASE-01:**
- **Opening:** opened explicitly; a second open returns the same case.
- **Evidence:** the evidence was retrieved: exception detail (21 evidence IDs, 11 affected results), and the cited source line read from the stored original.
- **Entries recorded:** EVIDENCE citing pack records and uploaded documents, EVIDENCE_GAP, OBSERVATION with evidence, HYPOTHESIS.
- **Refused:**
  - an observation without evidence (`EVIDENCE_REQUIRED`);
  - fabricated or unpublished references (`INVALID_EVIDENCE_REF`);
  - a stale revision (`CASE_CHANGED`);
  - a resolution outside a DECISION (`DECISION_ONLY`);
  - an AI_REQUEST written by an analyst.
- **State and history:** the case stayed OPEN/UNRESOLVED throughout, and the history is append-only and ordered.
- **Pack untouched:** the pack files and the exception view are unchanged.

**E/F. Review and publication** (clone, processed September pack):
- **Selections:** the live registered investigation is selected by default for EXC-CASE-01; EXC-CASE-02 stays visible as NOT_INVESTIGATED; "unresolved" is reported.
- **Refused selections and decisions:**
  - including the June investigation (`INELIGIBLE_SELECTION`);
  - NOT_INVESTIGATED while an eligible investigation exists;
  - incomplete selections;
  - GENERATE before a preview;
  - HOLD without a comment.
- **Preview 1** (live closing summary): a duplicate preview request is refused (`PREVIEW_IN_PROGRESS`).
- **Stale preview:**
  - GENERATE against a different snapshot is refused (`PREVIEW_STALE`);
  - GENERATE without the acknowledgement is refused;
  - after the selections changed, the old preview could not be used (`PREVIEW_REQUIRED`);
  - nothing was published.
- **HOLD** with a comment set the session `ON_HOLD`.
- **Preview 2:** same snapshot hash.
- **Two simultaneous GENERATEs:** exactly one final pack, **`FAP-CASE-PER-2026-09-v1-5cc11d5abd23`**; the other was refused with `GENERATION_IN_PROGRESS`; a later GENERATE is refused with `SESSION_CLOSED`.
- **Verification:**
  - the pack verifies through the API, and **independently with the library verifier, with no backend**;
  - a tampered copy fails ("report.html does not match its manifest SHA-256");
  - HTML (88 KB), PDF (66 KB) and JSON are served;
  - history: HOLD then GENERATE, one generation record;
  - both exceptions are `UNRESOLVED` in the pack;
  - the HOLD is kept as a prior decision.
- **Immutability:** the published files were byte-for-byte unchanged by later uploads, the reassessment and a restart.
- **Historical final packs:** none was regenerated, overwritten or modified.

**G. After publication:**
- **Reassessment:**
  - refused while nothing new had arrived (`NOTHING_TO_REASSESS`);
  - after additional evidence, the period shows `ADDITIONAL_EVIDENCE_RECEIVED` / pending;
  - REASSESSMENT needs a reason;
  - it ran explicitly and `SUCCEEDED` as `REASSESSMENT`, with `REASSESSMENT_STARTED` logged.
  - Its outcome is `ALREADY_EXISTS`: the new evidence is a supporting document, not a reconciliation input, so the deterministic result is the same pack. This is correct.
- **The case continued:**
  - the new document and the AI investigation were cited;
  - a reassessment note was added;
  - a human DECISION set `ESCALATED` while keeping the case open, with the previous resolution recorded;
  - all earlier entries were unchanged.
- **Close and reopen on EXC-CASE-02:**
  - a human decision closed it;
  - entries and AI requests on the closed case are refused (`CASE_CLOSED`);
  - a decision reopened it as UNRESOLVED.

  The deterministic exceptions stayed OPEN throughout.

### 13.5 Live AI results

Model `gpt-6-luna` (OpenAI); `simulated: false`.

**Provider calls:**
- 1 that timed out by design;
- 2 for the investigation;
- 1 per closing summary, 2 in total.

That is **5 provider requests** in all.

1. **Failure handling (real failure).** The backend was restarted with `UC042_LLM_TIMEOUT_SECONDS=1` and AI was requested for the case.
   - **Job routing:** the job carried exactly the case's pack and exception.
   - **Duplicate protection:** duplicates through the case endpoint and the investigation endpoint were both refused with `INVESTIGATION_ACTIVE`.
   - **Outcome:** the job became **FAILED** in 5 s:
     - `error_summary`: "ai_investigation: ToolLoop[timeout]: [timeout] provider call timed out";
     - 1 LLM call; `stop_reason` timeout; no artefact published; the failed attempt kept as not published; no secret in the record.
   - **Case and exception:** the case stayed OPEN/UNRESOLVED with the AI_REQUEST recorded, and the exception stayed OPEN.
   - A retry naming an unknown job is refused.
2. **Explicit retry.** After a restart with normal settings, `retry_of` named the failed job. The job **COMPLETED in 50 s**:
   - 2 model calls (55,863 input tokens, 27,401 cached; 5,707 output tokens);
   - 3 retrieval tools: `get_cashbook_entries`, `search_bank_entries`, `get_reconciliation_evidence`;
   - `validation_status: VALID`;
   - published and **registered** as `INV-EXC-CASE-01-1dd2c7d4f5c1` (registry seq 3).
3. **Quality of the output** (reviewed by hand and checked mechanically):
   - **Overall:** the assessment is `INSUFFICIENT_EVIDENCE`, and the resolution is `NOT_RESOLVED_BY_INVESTIGATION`.
   - **4 confirmed findings**, each with what it *establishes* and what it *does not establish*: the −812.40 GBP difference on 10 days from 17 Sep; the internal reconciliation showing 0.00; a 17 Sep bank debit "SETTLE 0417" of 812.40 with no cash-book counterpart; no discrepancy-log entries.
   - **1 hypothesis**, kept separate and labelled unverified: the debit may explain the difference.
   - **4 missing-evidence items**, each with the expected source.
   - **4 open questions.**
   - **4 next steps:** a bank payment trace, a cash-book search including alternate references, the discrepancy log and investigation file, and a balance roll-forward.
   - **Traceability:** all **22** cited IDs trace to the evidence packet or ledger, and all 5 cited source records exist in the pack's evidence register.
   - **No leakage:** none of the following reached the AI input: answer keys, `mutations.json`, scenario definitions or notes, `verification/`.
4. **Result persisted and reopened:**
   - the artefact and registry entry verify;
   - the investigation is eligible and listed in the case;
   - the exception workspace in the browser shows the findings.
5. **Nothing changed by AI:**
   - the exception stayed OPEN, and the case stayed OPEN/UNRESOLVED after completion;
   - only the requested exception was investigated.
6. **No automatic AI:** none of the following started an AI job (checked by counts before and after):
   - upload;
   - confirmation;
   - reconciliation and reassessment;
   - page views, dashboard and archive;
   - backend restart.
7. **Closing summary** (generated within each preview; 9 s; 3.3k input / 1.4k output tokens). It is a different artefact from an investigation: schema `uc042-closing-summary/1.0`, prompt `uc042-closing-summary-prompt/1.0`, and the pack's own "closing summary notice".
   - **What it says:**
     - it reflects the review context: 2 open exceptions, 1 investigated, EXC-CASE-02 NOT_INVESTIGATED, `INSUFFICIENT_EVIDENCE`;
     - it states that all exceptions remain unresolved and that it is not an audit opinion, certification or approval.
   - **Traceability:** all **13** source references point to real items (F/M/S) of the included investigation.
   - **No overreach:**
     - it makes no claim that anything is resolved;
     - the hypothesis is never presented as an observation;
     - it did not approve or publish anything (the session status changed only through the human HOLD and GENERATE).

### 13.6 Defects found and fixed

| # | Found by | Root cause (layer) | Fix | Regression test | Re-run |
|---|---|---|---|---|---|
| 1 | Stage G: a correction of a supporting document (`ADDITIONAL_EVIDENCE` PDF) was `UNRECOGNISED`/ERROR, so its batch could never be confirmed (`BATCH_INVALID`). The same file as additional evidence was accepted. | Backend business rule (`services/monthly.py::_submission_checks`). The supporting-evidence rule applied to `ADDITIONAL_EVIDENCE` only. | A correction of a document that is itself supporting evidence is supporting evidence too. A correction of a reconciliation input with an unrecognised file is still an ERROR. | `test_monthly_reports.SupportingDocuments.test_a_supporting_document_can_be_corrected` (fails on the old code) | Stage G2 6/6; UI correction in the browser stored as WARNING and confirmable |
| 2 | Live UI: archive and month pages slow. `GET /periods/PER-2026-09` took **19–20 s**; the period list did not return within 120 s while the browser made several requests. | Backend performance, a regression made visible by unification (one backend now serves all 17 packs). `PackService.load` deep-copies a pack of several MB on every call, and `InvestigationService.for_pack` reloaded the pack **once per exception** (48 loads, 97 % of the time in `copy.deepcopy`). | Load each pack once per aggregate: `for_pack` reuses one loaded pack, and the period view passes the pack it already loaded. Same results; no cache semantics changed. | `test_unification.UnifiedBackend.test_the_period_views_load_each_pack_once` (fails on the old code: 5 loads for 2 packs) | September detail **0.6 s**, period list **1.1 s** over HTTP. The archive renders in about 15 s from a cold start, with 4 parallel duplicate `/periods` requests from the UI (see 13.8). Live UI 29/29. |
| 3 | UI on the clone: the workspace AI panel showed "Loading findings…" indefinitely when its request did not succeed | Frontend error handling (`AiPanel` / `WorkspacePage`): load errors of the investigation and findings requests were ignored | The existing `ErrorPanel` is shown ("The investigation could not be loaded"); no layout change | `screens.test.tsx` "shows an error, not an endless 'Loading findings…'…" (fails on the old code) | Workspace renders the live findings in 5 s |
| 4 | UI: the top-bar environment tooltip still said "environments are not combined" | Frontend text outdated by unification | It now lists the storage profiles and says every period of this database is listed | covered by the build and type check | live UI pass |
| 5 | June guard test asserted an outdated assumption | Test | Updated to the authorisation rules without weakening (§7) | the test itself, plus a 3-way tamper check | passes |

**Test-design errors of my own** (not product defects), each corrected and re-run:
- a "concurrency" test that actually sent requests one after another;
- a wrong job field name (`error_summary`);
- incomplete June selections;
- UI waits that were too short;
- the investigation route, which is a pointer page; the June check now uses the report's investigations section.

### 13.7 Environment findings

- **Windows long paths are disabled** (`LongPathsEnabled = 0`). Investigation artefact paths are up to about 110 characters below the project root, so a project folder deeper than about 150 characters fails, for example in a temporary folder. The current location is fine.
  - The first E2E attempt from a scratch folder failed this way (HTTP 500 from `rglob`). It ran from `%USERPROFILE%\uc042_e2e` instead.
- **Corrupted `\u` paths.**
  - The first run of this session's catch-up command and live backend had their state folder corrupted: `$env:USERPROFILE\uc042_runtime` arrived with `\uc042` turned into a character. That created **`C:\app_state\instance.lock`** (an empty lock file).
  - The database URL comes from `.env`, so the migration and catch-up are unaffected: the lock is the only thing that went to the wrong place.
  - The backend now runs with the correct folder. **Please delete `C:\app_state`.** This session was not permitted to remove anything at the drive root.
  - The same corruption is present in the other session's document `19_COMPLETE_UI_FUNCTIONAL_AND_ARCHITECTURE_AUDIT.md`. That document is not part of this work and was not edited.
- **Another session was active:** its database `uc042_audit19`, backend 8019 and frontend 5179 were seen. They were not touched.

### 13.8 Observations (not changed; for a later decision)

- **Duplicate requests.** The UI requests `/periods` up to 4 times per page (top bar, page, data provider), and the backend's work is CPU-bound. A cold archive load therefore takes about 15 s, within the 30 s frontend timeout. A client-side request de-duplication would remove most of this.
- **Status after reassessment.** After a reassessment the period stays `ADDITIONAL_EVIDENCE_RECEIVED` / pending until a new final-pack version is reviewed and published (by design, report 18). The status does not say that a reassessment already ran; `latest_reassessment_status` does.
- **No UI for cases** (API only), as planned.

## Assessment

| Capability | Status |
|---|---|
| One database with ownership schemas, keys and indexes; data migrated with identifiers, provenance, verification, backups and rollback | **Implemented and verified (live).** Catch-up done (nothing new), legacy database **retired** as `uc042_history_retired_20261104` (read-only); §13.1 |
| One backend, one database, period-aware file layout | **Running and verified end to end** (§13.2–13.4) |
| September merge (Option A) | **Implemented and verified** (database, API and UI) |
| June discrepancy preserved and excluded from the approved set | **Implemented and verified** in the database, API, review (cannot be included) and UI; guard test now asserts the rules (§7) |
| Period-aware file resolution (`profile_for_period` and related) | **Implemented and verified** |
| Explicit reconciliation, reassessment | **Verified end to end** (clone): deterministic, duplicate-safe, persistent across restarts |
| Exception investigation cases | **Verified end to end** (API); UI deferred to the UI phase |
| Case-by-case AI investigation (existing V2) | **Verified live**: real failure, duplicate refusal, explicit retry, traceable evidence-based output, no status changes |
| Audit review, closing summary (live) and final-pack generation | **Verified end to end** on the clone: stale-preview protection, HOLD, acknowledgement, single generation under concurrency, independent verification, immutability |
| Phase 7 issues 1–5 | **Resolved** |
| Zero-balance rule review, users and authentication | **Not in scope / deferred** |
