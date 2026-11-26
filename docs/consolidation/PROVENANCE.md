# Provenance of `internal/uc042-consolidated-poc`

Assembled 26 Nov 2026 from three sources. GitHub `main` (b132305) and `openship-deploy` (e3490b2) were not modified.

| Part | Source | Commit | How it was imported |
|---|---|---|---|
| Repository base, `demo_datasets/september_2026/`, root docs, `uc042/frontend/` | GitHub `main` | `b132305` | Branch created from it |
| Engine → `uc042/` | Local repo `C:\u42v\fix8_20261122\engine_rel`, branch `tms/relationship-register` (23 commits, 22–24 Nov 2026; the build the 8953 demo server ran) | `194b173` → rewritten `89ef77e` | History rewritten with git-filter-repo (credential file removed, paths moved under `uc042/`), then merged with `--allow-unrelated-histories`. All 187 files present on both sides take the engine version. |
| Smart Parser + analyst web application → `app/` | Local repo `C:\u42v\fix8_20261122\app_rel`, branch `tms/relationship-register-app` (50 commits, 22–24 Nov 2026) | `a0a4978` (original hashes kept) | Subtree merge (`git read-tree --prefix=app/`), history unchanged |
| Light/Dark theme | Uncommitted working changes in `C:\u42v\fix8_20261122\app_merge` (on `a0a4978`) | `98d369f` | Applied as one commit on top of `a0a4978` before the subtree merge |
| Engine test data → `uc042/test_data/` | `Downloads\UC042_RECONCILIATION_TEST_SUITE_V2`, `…_V2_TC03_REV3`, `C:\u42v\enrich_20261123\outputs\tc_snapshot_0205` | — | Copied byte-for-byte, `__pycache__` excluded |
| Demo scenarios → `demo_datasets/ringfence_demo_scenarios/` | `C:\u42v\fix8_20261122\evidence\lead\e2e_v2\inputs\RINGFENCE_DEMO_TEST_DATA` | — | Copied, `logs/` excluded |

## Verification of the imports (blob level)

- `uc042/` at the engine import commit equals `engine_rel@194b173`, file for file, except:
  - `docs/token_optimisation/test_db.url`, removed;
  - GitHub's `uc042/frontend/` (205 files), kept.
- `app/` at the app import commit equals `app_rel@a0a4978` plus the theme commit, file for file.
- Later commits change only:
  - the 12 files listed in "Changes after import";
  - the new `deploy/`, `docs/consolidation/` and `uc042/test_data/` folders and `demo_datasets/ringfence_demo_scenarios/`;
  - the root `README.md`, `.gitignore`, `.gitattributes` and `.vscode/settings.json`.

## Excluded, and why

| Item | Reason |
|---|---|
| `docs/token_optimisation/test_db.url` (engine) | Contained a local PostgreSQL test-database password. Removed from **every** commit before import; never pushed. |
| `.env` files (OpenAI key), auth files (password hashes) | Credentials. Created locally under the ignored `.runtime/` by `deploy/` scripts. |
| Demo workspace (`C:\u42v\fix8_20261122\homes\…`, 151 MB), PostgreSQL dumps, `.venv`, `node_modules`, `__pycache__` | Runtime state or build output |
| `RINGFENCE_DEMO_TEST_DATA/logs/` | Run logs |
| Engine branch `fix/IN04-empty-register`; app branches `race-probe`, `shakedown` | Not part of the demo build (IN-04 awaits owner decisions; the others are harness probes). Kept in the local backup bundles. |

## Changes after import

| File | Change |
|---|---|
| `app/tests/uc042_support.py` | Default engine path is the sibling `uc042/` (was a `p10` path). `UC042_ROOT` still overrides it. |
| `app/tests/test_closure_service.py` | Engine interpreter defaults to `sys.executable` and demo data to `demo_datasets/ringfence_demo_scenarios` (both were local paths) |
| `app/tests/test_demo_scenarios.py` | Demo data from the repository |
| `app/tests/test_handoff_3b3.py` | The protected-path assertion uses `writer.DEFAULT_PROTECTED` |
| `app/smartparser/handoff/writer.py` | `DEFAULT_PROTECTED` is the repository's `uc042/` (was a `p10` path) |
| `app/tools/seed_analyst_demo.py` | Defaults point into the repository and `.runtime/` |
| `uc042/tests/test_evidence_relationships.py`, `test_relationship_register.py`, `test_s1_group_assessments.py`, `test_resolution_negation.py`, `test_ws3_enrichment.py` | Test suites read from `uc042/test_data/`; environment overrides are unchanged where they existed |
| `uc042/frontend/README.md` | LEGACY note added |

No application behaviour was changed.

## Engine commit map (old `engine_rel` hash → new hash on this branch)

The history was rewritten to remove the credential file, so every engine commit has a new hash. Contents and messages are unchanged apart from the removed file and the `uc042/` prefix.

| Old (`engine_rel`) | New | Subject |
|---|---|---|
| `0898ed9` | `e9f72de` | baseline: UC-042 engine source (byte-exact copy of p10/uc042_token_optimisation minus fron |
| `09aee0f` | `384f069` | S1: port citefix C (CITEFIX-FINAL-20261120-R2: findings schema 1.5 evidence_basis, evidenc |
| `18b9987` | `05ce9b4` | TMS r3: relationship reasoning - summary input 1.2 (each exception's engine root_cause; sh |
| `194b173` | `89ef77e` | Group investigations: prompt 1.12/2.12-tools names every related exception in a group lead |
| `21100bc` | `8a90751` | Analyst PDF: deterministic reconciliation statement (Everything checks out / per-area tick |
| `213f417` | `a852332` | Evidence-bearing relationships and AI relationship challenges (isolated; not merged) |
| `21e0cc5` | `074b6ce` | B: D5 rejected-content leak check: sentence-level, normalised, attributed to accepted/dete |
| `241cb8e` | `29b718b` | Investigator prompt 1.9 / 2.9-tools: individual investigations use the engine's relationsh |
| `566036f` | `9baecb9` | integrate: rules consistency fixes I-1..I-3 (enrichment-only effects) |
| `5756ea7` | `42901f7` | tests: exclude superseded Saturday TC03 from the TC snapshot integration class (Session 2  |
| `69798a7` | `1f22a1c` | TMS relationship register: the engine's deterministic financial-relationship discovery (en |
| `6d55cc9` | `97b36b4` | S1: supporting_records normalisation - control results/searches of the packet already cite |
| `877a81e` | `4aa7702` | TMS r2: closing-summary prompt 1.4 spells out the citation contract (allowed_refs only for |
| `9300d6a` | `4e983a9` | S1: group assessments use dedicated report block kinds (relationship_backed/unverified/rej |
| `97863db` | `ef8ba8f` | Investigation validation: negation-aware resolution rule (live TC06-06 false positive) |
| `a559baa` | `c28006b` | integrate: Session 1 AI/closing summary (fix/S1-citation 4e983a9: B D5 074b6ce, citefix C, |
| `a62c886` | `4c6de58` | Simplify: remove the AI ACKNOWLEDGED / CHALLENGED mechanism; the AI investigates and expla |
| `b107be3` | `d90ec22` | WS3: reconciliation engine enrichment v1 (off by default) |
| `c3e6b0b` | `5bb5f01` | Restore the original LF line endings of the files edited in a852332 (they had been rewritt |
| `caad29e` | `6af58d5` | Readable investigations, no AI closing summary, analyst-edition audit pack (renderer 4.0-a |
| `cbb81ba` | `4256a9b` | integrate: WS3 reconciliation enrichment v1 (d90ec22, off by default) onto clean base e9f7 |
| `d71afd7` | `acfca03` | S1: group assessments in the AI closing summary (summary schema 1.2, prompt 1.3, input 1.1 |
| `e977444` | `7aeedd2` | Investigation validation: does_not_establish may state "that X never existed" when framed  |
