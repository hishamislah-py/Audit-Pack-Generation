# UC-042 historical demonstration: January–August 2026

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

**Status:** eight deterministic packs, generated and verified. **Pending review and approval.**

Not generated here (each needs separate authorisation):

- AI investigations;
- AI closing summaries;
- final audit packs.

## Contents

| Path | What |
| --- | --- |
| `datasets/2026-MM/` | Each month's engine-ready case: `source_data/` (14 CSV), `supporting_documents/` (PDFs) and `manifest.csv`. These are byte-identical, hash-verified copies of the supplied package's `2026-MM/source_documents/`. `scenario.json` holds only the identity (`H2026MM`) and the synthetic notice. |
| `packs/<pack_id>/` | One deterministic pack per month (`uc042lib.pack.generate`, write-once): `pack.json`, `pack.html`, `processing/`, `generations/`. |
| `verification/run_manifest.json` | Per month: pack ID, content hash, policy version used and why, case status, results by outcome, exceptions and groups. |
| `verification/verification_results.json`, `continuity.csv`, `package_inventory.csv` | Independent verification results: `tools/verify_demo_history.py --write`. |

The supplied package stays read-only, where it was delivered: `UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/`.

The package's `scenario_definition.json` and `mutations.json` describe the planted answers. They are **not** copied here. Only the offline tests and `tools/verify_demo_history.py` read them, as expected-result oracles.

`verification/` compares the packs with those oracles, so it also contains answer material.

## Keep answer material out of the AI context

For any later AI step:

- set `datasets_root` to `demo_history/datasets`;
- set `packs_root` to `demo_history/packs`.

Never point an AI root at `demo_history/` itself or at the package folder. `scenario_definition.json` is in the investigation layer's `FORBIDDEN_NAMES`.

## Packs

| Month | Pack | Policy | Engine status | Exceptions |
| --- | --- | --- | --- | ---: |
| 2026-01 | `PACK-H202601-PER-2026-01-bc596db0bfe6` | v1.1 (illustrative) | CLEAN | 0 |
| 2026-02 | `PACK-H202602-PER-2026-02-195df2e1f216` | v1.1 (illustrative) | EVIDENCE_INCOMPLETE | 1 |
| 2026-03 | `PACK-H202603-PER-2026-03-d1d37aea9c2b` | v1.1 (illustrative) | EXCEPTIONS_OPEN | 3 |
| 2026-04 | `PACK-H202604-PER-2026-04-a854c4a2bcfd` | v1.1 (illustrative) | CLEAN | 0 |
| 2026-05 | `PACK-H202605-PER-2026-05-051d209cccc4` | v1.2 (selected; pending approval) | EVIDENCE_INCOMPLETE | 4 |
| 2026-06 | `PACK-H202606-PER-2026-06-a07de266b389` | v1.2 | EXCEPTIONS_OPEN | 4 |
| 2026-07 | `PACK-H202607-PER-2026-07-5d8714f8c422` | v1.2 | EVIDENCE_INCOMPLETE | 5 |
| 2026-08 | `PACK-H202608-PER-2026-08-22a356a95098` | v1.2 | EVIDENCE_INCOMPLETE | 8 |

Every exception is `OPEN` and `AWAITING_HUMAN_REVIEW`, with no cause recorded. The full report is `docs/audit_pack/14_HISTORICAL_JAN_AUG_DETERMINISTIC_EXECUTION_REPORT.md`.

## Rebuild and verify (from `uc042/`)

```powershell
python tools/build_demo_history.py            # verifies the package, copies, generates (existing identical packs are kept)
python tools/verify_demo_history.py --write   # independent checks; writes verification/
python -m unittest tests.test_demo_history    # 61 tests
```

The build never overwrites a file with different content. If a pack's code-derived identity changes after an engine change, the build publishes a new pack ID beside the old one. Remove the outdated pack deliberately.
