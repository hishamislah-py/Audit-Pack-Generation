# UC-042 — Historical data integration readiness and pre-investigation fixes

Dates: 3–4 November 2026. Scope: the four approved decisions, period-aware upload policy validation, the AI investigation input boundary, PostgreSQL reference verification.

**Not done:**

- no AI investigation;
- no live OpenAI call;
- no closing summary;
- no final audit pack;
- no change to reconciliation calculations, matching, thresholds or deterministic findings.

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

## 1. Initial state and files inspected

**Starting state:**

- **Python suite:** 538 run, 537 passed, 1 skipped (report 14).
- **Snapshot:** a SHA-256 snapshot of the whole project (1,179 files, excluding `.venv`, `node_modules`, `frontend/dist`, `__pycache__`) was taken before any change.

**Documents read:**

- reports 12 (Phase 4), 13 (engine period configuration) and 14 (historical execution);
- `demo_history/verification/run_manifest.json`;
- the package manifests and `scenario_definition.json` files.

**Code inspected:**

| Area | Files |
| --- | --- |
| Engine and intake | `uc042lib/period.py`, `uc042lib/prepare.py` |
| Upload | `uc042app/ingest/analysis.py`, `uc042app/services/monthly.py` (upload, duplicates, current set, confirmation, processing) |
| Application settings | `uc042app/config.py` |
| Investigation layer | `uc042lib/investigation/{config,retrieval,graph,run}.py`, `uc042app/services/investigations.py` |
| Database | `uc042app/db/*` |
| Frontend | its use of `processing_set` and of pack IDs |

**What was found:**

1. **Upload policy.** Intake recognised any PDF carrying the seven policy key-detail labels as IN-17. It then copied that file to `period.filename("IN-17")`, which is always `…_v1.2.pdf`. As a result:
   - a January upload of v1.1 would have been **renamed to v1.2**;
   - May's two policies were AMBIGUOUS (neither was used).

   The app also held one document per evidence type, so confirmation refused two policies.

2. **Investigation roots.** They fell back silently to September: `Path(packs_root or PACKS_ROOT)`. A blank value became September. The app's `datasets_root` could not be configured at all.

3. **PostgreSQL.** See §6: no stale reference. The premise that September references had changed does not hold. The September packs were **never rewritten**; only an in-memory rebuild was compared (report 14 §I).

## 2. The four approved decisions and where they are recorded

The human record is `docs/UC042_HISTORICAL_DEMO_DECISIONS.md`.

| ID | Decision | Configuration and enforcement |
| --- | --- | --- |
| HD-1 | v1.1 accepted as an illustrative synthetic document for January–April | `uc042lib/policy.py` `POLICY_VERSIONS["1.1"]`. The upload analysis states "not an actual or historical Moorwand policy". |
| HD-2 | v1.2 governs May; both documents kept | `uc042lib/policy.py` `APPROVED_SELECTIONS["PER-2026-05"]`. `tools/build_demo_history.py` takes the May version from it. |
| HD-3 | GBP discrepancy accepted; exceptions stay OPEN with no cause | engine unchanged; tests in `test_demo_history.py` and `test_historical_integration.py` (`Decisions`) |
| HD-4 | Reference-only mutation retained; no narrative mutation; never match on amount alone | package and engine unchanged; same tests |

**HD-1 detail:**

- classification `ILLUSTRATIVE_SYNTHETIC`, effective 2025-10-01, superseded by v1.2 from 2026-05-07;
- recognised only with its watermarks: "ILLUSTRATIVE SYNTHETIC DOCUMENT", "NOT AN OFFICIAL RECORD" and "Illustrative predecessor of policy v1.2";
- copied byte-for-byte under its own name.

**HD-2 detail:**

- the basis records that results under v1.1 and v1.2 were identical apart from the cited file name;
- the May pack stays **pending review**.

## 3. Upload policy validation

**New module `uc042lib/policy.py`.** It is not part of the engine or pack-layer fingerprint, so the stored packs stay reproducible. It provides:

- **Register:** the recognised versions, each with effective date, classification and required markings, plus the approved selections.
- **`recognise(details, text)`:** the stated version must be registered, the effective date must equal the registered one, and the markings must be present. Anything else is unsupported. An arbitrary PDF without the key details is still rejected by identification.
- **`applicability(version, period)`:** effective by the period end, and not superseded by its start.
- **`select(period, supplied, override)`:** picks the single applicable version, else the approved selection, else AMBIGUOUS. Two different files of one version are AMBIGUOUS. If the required version is missing, the policy is MISSING; nothing is substituted.

**Intake (`uc042lib/prepare.py`):**

- each usable policy is copied under its **versioned** name;
- the selected version is `SELECTED`; another applicable version is `SUPPLIED_NOT_SELECTED`. Both are ACCEPTED and listed in the manifest;
- a policy that does not apply is REJECTED with the reason (for example "takes effect on 2026-05-07, after April 2026", or "superseded by v1.2");
- the selection is written in the intake reasons, which the pack copies into `audit_trail.intake`, and in `case/policy_selection.json` (`selected_policy()`).

**Upload (`uc042app`):**

- **Messages to the analyst:** `POLICY_VERSION`, `ILLUSTRATIVE_SYNTHETIC_POLICY` (v1.1), `POLICY_SELECTED`, `POLICY_SUPPLIED_NOT_SELECTED`.
- **ERROR documents (kept, never processed):** `POLICY_NOT_RECOGNISED`, `POLICY_NOT_APPLICABLE`.
- **One slot per policy version:**
  - the current set maps `IN-17` to the governing version and `IN-17@vN.N` to another supplied version;
  - two versions are therefore neither "ambiguous" nor a confirmation clash;
  - the batch summary carries `policy_selection`.
- **Processing:**
  - passes the intake-selected version explicitly to the engine (`PeriodConfig(y, m, version)`);
  - records `policy_version` in the run result;
  - a re-run reuses the prepared case only if its accepted documents match.

**Traceability, upload → pack:**

1. Document `checks.policy` and the batch `summary.policy_selection`.
2. The intake reasons.
3. The run `result.policy_version`.
4. The pack's `audit_trail.inputs` (both May files, with hashes) and `audit_trail.intake`.
5. The C03-POLICY citation.

**Behaviour by month (tested):**

| Months | Policy behaviour |
| --- | --- |
| January–April | v1.1 selected |
| May | v1.1 kept, v1.2 selected |
| June–August | v1.2 |
| September | v1.2, with canonical names and manifest identical to before; processing equals the stored S05 pack |
| April with v1.2 only | REJECTED or ERROR, policy MISSING |
| June with v1.1 only | superseded, MISSING |
| May without v1.2 | MISSING; v1.1 kept, not substituted |

Unsupported version 1.3, unmarked v1.1 and v1.2 with a wrong date are each rejected. Two different v1.2 documents are AMBIGUOUS; an identical copy is a DUPLICATE.

Upload → intake → engine for January, May and August, and the full app upload → confirm → process for May, give **the same exceptions and outcome counts as the stored historical packs**.

## 4. Investigation path configuration

**New module `uc042lib/investigation/roots.py`.** It defines two profiles:

| Profile | Packs | Datasets | Investigations (output) | Periods |
| --- | --- | --- | --- | --- |
| `september` (default) | `packs/` | `uc042_dataset/` | `investigations/` | PER-2026-09 |
| `historical-demo` | `demo_history/packs/` | `demo_history/datasets/` | `demo_history/investigations/` (not created; written only on a future publication) | PER-2026-01 … 08 |

**Selection without code changes**, highest precedence first:

1. explicit roots, which must give both packs and datasets;
2. `profile`;
3. `period_id`;
4. the environment variables `UC042_INVESTIGATION_PROFILE` / `UC042_INVESTIGATION_PERIOD`;
5. the September default.

**Wiring:**

- the CLI takes `--profile` and `--period`, and validates roots before any provider is configured;
- `run_investigation` and `investigate_pack` accept `profile` and `period_id`, and validate before anything is read;
- a pack must belong to the profile's periods.

**Backend:** `UC042_DATASETS_ROOT` is new. The packs and datasets roots are validated at start-up, and a bad root stops the backend.

**Failures are explicit (`InvestigationRootsError` / `RetrievalError` / `ConfigurationError`):**

- missing, blank or non-directory roots;
- only one input root given;
- an unknown profile;
- a period without a profile;
- a mismatch between profile and period;
- a blank environment variable.

**There is no fallback to September** except when nothing at all is configured.

## 5. Evidence that the verification directory is excluded

The boundary is technical, at three levels:

1. **Roots.** An input root must not lie inside, or contain, a directory named `verification`, `golden`, `tests` or `UC042_JAN_AUG_HISTORICAL_DEMO` (recursive check). So `demo_history/`, `demo_history/verification/` and the package folder are refused as roots.
2. **Every file read.** `retrieval._inside` refuses any path outside its root, or with one of those names as a path part (`FORBIDDEN_DIR_PARTS` extended). `scenario_definition.json` and the earlier answer files are in `FORBIDDEN_NAMES`.
3. **What is read at all.** `EvidenceStore` reads only the files listed in the verified pack's audit trail, plus the canonical source names inside the pack's own dataset folder. There is no recursive discovery.

**Tests (`test_historical_integration.InvestigationRoots`):**

- In a mirror of the demo layout, a `verification/expected.csv` holds a planted reference. `search_reference` does not find it, while real evidence (`SETTLE 0263`) is found. No loaded record comes from a verification path.
- A tampered pack whose inputs point to `../../verification/expected.csv`, or to `<dataset>/verification/expected.csv`, is refused.
- A datasets root containing a `verification/` folder is refused.
- `demo_history/`, `demo_history/verification/` and the package folder are refused as roots.
- For all eight historical months, every loaded source file is the month's own source data.

## 6. PostgreSQL reference inspection

**Method.** The local cluster was inspected read-only (127.0.0.1:5433, database `uc042`, Alembic `0001_initial`), inside a `READ ONLY` transaction.

**Tables and pack references:**

| Table | Rows | Pack references |
| --- | ---: | --- |
| `period_packs` | 9 | 9 |
| `reconciliation_periods` | 1 | PER-2026-09 |
| `activity_events` | 1 | 0 |
| jobs, reviews, decisions, previews, final-pack records, investigation registry, upload batches, source documents, processing runs | 0 each | — |

**Results:**

- All 9 references are the **original** September IDs (`PACK-S01-PER-2026-09-577b06a1d894` … `PACK-SC5D-…-2c5a7ae2e160`). All exist in `packs/`, verify, belong to PER-2026-09, and match the registered content hash.
- Foreign keys (period ↔ packs, batches, runs; review ↔ decisions and previews) are consistent.
- The 9 IDs in the frontend fixtures and the 34 investigation artefacts also resolve to packs on disk.

**No stale reference exists, so no migration was performed and no backup was needed.** No record was changed.

**Reusable check.** `python -m uc042app.admin verify-pack-references` (read-only) checks:

- period registrations (period and content hash);
- processing runs;
- jobs;
- reviews;
- final-pack records;
- registry entries.

On the operational database it reported **9 references, 0 problems** (run with application state in a scratch folder: no `app_state/` was created). The service method is tested on SQLite and PostgreSQL, including stale-ID, wrong-period and wrong-hash rows, which are reported, never repaired.

## 7. Files changed and added

**Added:**

- `uc042lib/policy.py`
- `uc042lib/investigation/roots.py`
- `tests/test_historical_integration.py`
- `docs/UC042_HISTORICAL_DEMO_DECISIONS.md`
- this report

**Modified:**

- `uc042lib/prepare.py`
- `uc042lib/investigation/config.py`
- `uc042lib/investigation/retrieval.py`
- `uc042lib/investigation/graph.py`
- `uc042lib/investigation/run.py`
- `uc042app/config.py`
- `uc042app/ingest/analysis.py`
- `uc042app/services/monthly.py`
- `uc042app/admin.py`
- `tools/build_demo_history.py`: the May version now comes from the register. The recorded basis text is unchanged, so a rebuild leaves `run_manifest.json` byte-identical.
- `.env.example`

**Not changed:**

- engine and pack-layer modules (`schema`, `period`, `structure`, `money`, `validate`, `uc042lib/pack/*`), so the engine and pack-layer fingerprints are unchanged;
- the React source;
- the API contract.

## 8. Tests executed

| Suite | Run | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Python full suite (`-W error::ResourceWarning`) | 568 | 567 | 0 | 1 (opt-in live test) |
| of which new `tests/test_historical_integration.py` | 30 | 30 | 0 | 0 |
| Upload, monthly and DB suites on **PostgreSQL** (`UC042_TEST_REPOSITORIES=postgres`: historical uploads, monthly API, `test_db`) | 45 | 45 | 0 | 0 |
| Frontend `npm test` | 25 | 23 | 0 | 2 (opt-in live) |
| Frontend production build; API contract check (35 interfaces) | — | OK | — | — |

**New tests, by group:**

| Group | Tests |
| --- | ---: |
| Policy register | 5 |
| Intake | 9 |
| Application upload, processing and DB references | 6 |
| Investigation roots and verification exclusion | 7 |
| Recorded decisions | 3 |

**PostgreSQL restart.** During this task the local PostgreSQL cluster stopped (machine/session restart). Twelve PostgreSQL tests failed with "connection refused" until the cluster was restarted with the documented `pg_ctl … start` command; they then passed.

**Offline only.** The only investigation executed was the existing September offline **simulated** run (SC2, `simulated: true`, into a temporary folder), to prove the September configuration still works. It is not AI output.

## 9. Preservation of deterministic packs

Compared with the snapshot taken before this task, all of these are **unchanged**:

| Asset | Files |
| --- | ---: |
| `demo_history/` (8 packs, datasets, verification, README) | 230 |
| `uc042_dataset/` | 287 |
| `packs/` (9 September packs) | 72 |
| `tests/golden/` | 10 |
| `investigations/` | 34 |
| `uc042lib/final_pack/` | 12 |
| The supplied package | 184 |

There is no `final_packs/`, `app_state/` or `document_store/` in the project.

**Verification:**

- **all 8 historical packs** and **all 9 September packs** verify (content hash and identity);
- the historical packs are still reproduced byte-for-byte by the current code (`test_demo_history`);
- the independent verifier still gives 8/8 MATCH and 18/18 continuity at every boundary.

## 10. Outstanding issues

1. **`demo_history/README.md` wording.** It still says the decisions are pending. It was left unchanged so that the protected `demo_history` tree stays byte-identical. The decisions are recorded in `docs/UC042_HISTORICAL_DEMO_DECISIONS.md`.
2. **Historical packs are not in the application archive.** The backend's `packs_root` is September's. Showing January–August in the dashboard would need `UC042_PACKS_ROOT=demo_history/packs` and `UC042_DATASETS_ROOT=demo_history/datasets` (a separate backend instance or state), or a deliberate registration step. Neither was done here.
3. **Investigations root for the historical profile.** `demo_history/investigations/` does not exist yet. It would be created only by a future, authorised investigation.
4. **The local PostgreSQL cluster does not start automatically** after a restart (Phase 4 §M command).

## 11. Readiness conclusion

The application and configuration are **ready for the next phase, subject to review**:

- the four decisions are recorded and enforced;
- policy validation is period-aware from upload through processing into the pack;
- the investigation layer reads the historical packs and datasets only from explicitly approved roots, with the verification material technically excluded;
- September works unchanged;
- the database references are consistent;
- no protected asset was modified.

**Stopped here.** No AI investigation, live OpenAI call, closing summary or final audit pack was run or generated.
