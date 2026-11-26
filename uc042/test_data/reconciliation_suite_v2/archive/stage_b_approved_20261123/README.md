# UC-042 Reconciliation Test Suite V2

This is an independent suite of synthetic reconciliation test cases for the UC-042 Moorwand Safeguarding Audit Pack POC. It defines the **desired future behaviour** of an enriched reconciliation engine for four behaviours (duplicate transactions, amount mismatch, timing difference, unmatched transaction) and two combined cases (common cause, independent causes).

## Current status: Stage C review checkpoint

| Stage | State |
|---|---|
| A. Source discovery | Done: `SOURCE_DISCOVERY_REPORT.md`, `CAPABILITY_GAP_REGISTER.md` |
| B. Scenario specification | Done: `SCENARIO_CATALOGUE.md`, `scenario_manifest.json` (draft) |
| C. Review checkpoint | **Waiting for the owner's review** |
| D. Dataset generation | Not started. Only `shared_baseline/` exists: a hash-verified copy of the clean baseline. |
| E. Offline validation | Not started |

Nothing in this suite has been run through the UC-042 engine or application. Every "ENGINE-PREDICTED" value comes from reading the source.

## Layout

| Path | Contents |
|---|---|
| `README.md` | This file |
| `SOURCE_DISCOVERY_REPORT.md` | What exists in the current engine, schemas and data (Stage A) |
| `CAPABILITY_GAP_REGISTER.md` | Existing, missing and proposed capabilities (G-01 to G-22) |
| `SCENARIO_CATALOGUE.md` | TC01 to TC06 specifications, with exact mutations and expectations (Stage B) |
| `scenario_manifest.json` | Machine-readable summary (draft) |
| `shared_baseline/` | A copy of `set_01_clean_baseline` (`source_data/`, `supporting_documents/`, `manifest.csv`) |
| `_work/` | Read-only analysis scripts used to pick records and compute figures. They never import the engine. |

Stage D will add these directories, all inside this folder:

- `TC01_…/` to `TC06_…/`, each a case directory with `initial_submission/`, `mutations.json`, `MUTATION_RECORD.md`, `expected_results/` and, where applicable, `corrections/`;
- top-level `expected_results/` and `corrections/` indexes;
- `generation_report.md`;
- a PowerShell export script.

## Safety

- The workspace is `C:\u42v\recon_suite_v2_20261123\UC042_RECONCILIATION_TEST_SUITE_V2`.
- No existing engine, Smart Parser, Ringfence, dataset, scenario bundle or frozen key was modified.
- No verification process was touched.
- All data is synthetic. Customer labels start `SYNTHETIC TEST`.
