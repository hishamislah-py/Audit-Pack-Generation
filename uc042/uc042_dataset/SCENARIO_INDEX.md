# UC-042 scenario datasets

> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.

Every scenario dataset is built from `set_01_clean_baseline` by `python -m uc042lib.scenarios`. The baseline is never modified. Each scenario folder holds `mutations.json` (exact record changes), `answer_key.json` (expected results from the current engine, the intended business outcome, and known engine limitations) and `SCENARIO_NOTES.md`.

| Assessment scenario | Dataset | Kind |
| --- | --- | --- |
| 1 Clean audit pack | `set_01_clean_baseline` | baseline |
| 2 Settlement timing difference | `scn_SC2_settlement_timing` | mutation of set_01_clean_baseline |
| 3a Correctly supported fee | `set_01_clean_baseline` | baseline |
| 3b Fee not itemised | `scn_SC3B_fee_not_itemised` | mutation of set_01_clean_baseline |
| 3c Unexplained gross-to-net (short settlement) | `scn_SC3C_short_settlement` | mutation of set_01_clean_baseline |
| 4 Missing or incomplete evidence | `scn_S02_missing_eur_statement` | mutation of set_01_clean_baseline |
| 5a Transaction missing | `scn_SC5A_missing_transaction` | mutation of set_01_clean_baseline |
| 5c Refund counted twice | `scn_SC5C_refund_double_posted` | mutation of set_01_clean_baseline |
| 5d Closing snapshot mismatch | `scn_SC5D_closing_snapshot_mismatch` | mutation of set_01_clean_baseline |
| 6 Unexplained GBP difference 812.40 | `scn_S05_unexplained_gbp_difference` | mutation of set_01_clean_baseline |

Scenario 3a uses acquirer batch `AQ-GBP-20260908` in the clean baseline unchanged. Deferred (not built): 3d wrong fee rate (D2), 5b adjustment not reflected (D3).
