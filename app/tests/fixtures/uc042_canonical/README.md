# UC-042 canonical evidence fixtures (byte-for-byte copies)

Copied on 18 Nov 2026 from the isolated UC-042 working copy `C:\Users\artlptp263user\p10\uc042_token_optimisation`
so that the Phase 1 tests run without the UC-042 tree. The files are not modified; their SHA-256 values equal the
`sha256` column of each folder's `manifest.csv`, which the tests check.

| Folder | Source | Period | Contents |
|---|---|---|---|
| `PER-2026-09_set_01_clean_baseline/` | `uc042_dataset/set_01_clean_baseline/` | September 2026 | all 19 categories (IN-01..IN-19), policy v1.2 |
| `PER-2026-05_demo_history/` | `demo_history/datasets/2026-05/` | May 2026 | IN-01..IN-17 (no IN-18/IN-19), policy v1.1 **and** v1.2 |

The tests use the manifests only as ground truth; classification receives file bytes only.
