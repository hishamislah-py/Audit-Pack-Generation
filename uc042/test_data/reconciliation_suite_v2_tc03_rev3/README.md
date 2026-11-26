# UC-042 Reconciliation Test Suite V2

This is an independent suite of synthetic reconciliation test cases for the UC-042 Moorwand Safeguarding Audit Pack POC. It covers six scenarios: duplicate transaction, amount mismatch, timing difference, unmatched transaction, several discrepancies with one possible cause, and independent causes. It describes the **desired future behaviour** of an enriched reconciliation engine. Each scenario also records what the **current** engine is predicted to do, by source reading only.

> ILLUSTRATIVE SYNTHETIC DATA. All names, accounts, references and amounts are fictional. Customer labels start `SYNTHETIC TEST`.

## Status (23 Nov 2026)

| Stage | State |
|---|---|
| A. Source discovery | Done |
| B. Specification | Done. TC03 was revised after Stage C; current revision 3 = 24/25 Sep (see `TC03_REVISION_3_CHANGE_RECORD.md`). |
| C. Review | Approved |
| D. Dataset generation | Done: `tools/generate_suite.py` |
| E. Offline validation | Done, **PASS** (10/10 cases, 6/6 negative tests). See `VALIDATION_REPORT.md`. |
| Engine / application execution | **Not done** (not permitted in this task) |

## Start here

| File | Purpose |
|---|---|
| `generation_report.md` | How the data was generated, what changed, issues |
| `VALIDATION_REPORT.md` | Offline validation results |
| `SCENARIO_CATALOGUE.md` | The six specifications (TC03 revision 3) |
| `TC03_REVISION_3_CHANGE_RECORD.md` | Before/after for the TC03 revision from 25/26 Sep to 24/25 Sep |
| `CAPABILITY_GAP_REGISTER.md` | Existing, missing and proposed capabilities (G-01 to G-22) |
| `SOURCE_DISCOVERY_REPORT.md` | Evidence from the current engine and data |
| `UPLOAD_INSTRUCTIONS.md` | How to run or upload the scenarios later |
| `scenario_manifest.json` | Machine-readable summary |
| `expected_results/INDEX.md`, `corrections/INDEX.md` | Indexes |

## Layout

| Path | Contents |
|---|---|
| `TC01_DUPLICATE_TRANSACTION/` … `TC06_INDEPENDENT_CAUSES/` | `initial_submission/`, `mutations.json`, `MUTATION_RECORD.md`, `expected_results/`, `upload/`, and `corrections/` (TC01, TC04, TC05 only) |
| `shared_baseline/` | Hash-verified copy of `set_01_clean_baseline` |
| `tools/` | `contract.py` (reads schema.py with `ast`, without executing it), `scenario_specs.py`, `generate_suite.py`, `validate_suite.py`, `negative_tests.py`, `package_suite.py`, `write_reports.py`, `tc03_change_record.py`, and the contract snapshot |
| `validation/` | `validation_results.json`, `negative_tests.json` |
| `packages/` | Per-scenario ZIPs, the master ZIP, `SHA256SUMS.txt` |
| `archive/stage_b_approved_20261123/` | Approved Stage B documents, unchanged |
| `archive/rev2_tc03_25_26_sep_20261123/` | TC03 revision 2 (dataset, ZIPs, reports, tools), unchanged |
| `export_to_downloads.ps1` | Copies the suite to a new Downloads folder and never overwrites |

**Expectation labels:**

| Label | Meaning |
|---|---|
| FIN | Deterministic, engine-independent |
| ENGINE-PREDICTED | Source reading only; not executed |
| FUTURE (PROPOSED) | Desired enriched behaviour; categories PENDING |
| AI | Investigation-layer expectations |

## Reproduce

From this folder (Python 3.11, standard library only):

```
py -3.11 -I tools/generate_suite.py
py -3.11 -I tools/validate_suite.py
py -3.11 -I tools/negative_tests.py
```

No existing engine file, source file, frozen scenario, baseline dataset or answer key was modified.
