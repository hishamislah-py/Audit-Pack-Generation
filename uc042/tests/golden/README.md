# Golden snapshots

Validator outputs captured for regression only. They prove results are **unchanged**, not that they are **correct**.
Correctness comes from the scenario answer keys (derived from the scenario design) and from the independent verifier
`tools/verify_datasets.py` (no shared code with the engine).

## Change log

**30 Oct 2026: re-captured for decision D4 (opening client snapshot).**

`set_01_clean_baseline`, `scn_S02_missing_eur_statement` and `scn_S05_unexplained_gbp_difference` were compared with the
previous snapshots before re-capture. In each, the only differences were:

- **added:** 12 `CBAL-ROLLFWD` PASS results for the 1 Sep day-pair (one per client), now assessable from the 31 Aug snapshot;
- **changed:** `V01-SCHEMA` IN-03 count 264 → 276, and `C03-POINT` IN-03 "0 off-point of 264" → "of 276".

Exceptions were identical, and every other result was identical.

Added the same day: snapshots for the six new scenario datasets (SC2, SC3B, SC3C, SC5A, SC5C, SC5D).
