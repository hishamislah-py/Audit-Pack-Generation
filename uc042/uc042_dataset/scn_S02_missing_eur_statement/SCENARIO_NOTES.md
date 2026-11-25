> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.

# Scenario S02 — Missing EUR bank evidence, 15 Sep 2026 (synthetic)

**Changes vs the clean baseline** (exact list in `mutations.json`):

- Removed the 17:00 balance confirmation `ST-SGA-EUR-01-20260915-1700` (IN-07).
- Removed the end-of-day statement `ST-SGA-EUR-01-20260915-EOD` (IN-08).
- Removed its 4 entries (IN-09).

**Kept unchanged on purpose:**

- `ERL-SGA-EUR-01-20260915` (IN-06) still cites `ST-SGA-EUR-01-20260915-1700` and still reports a bank balance. The claim stays; its support is gone.
- The cash book (IN-10), transactions, settlement batches and lines.
- The own-funds account statement for 15 Sep.

**Expected result:** one Critical exception, `EXC-S02-01` (missing bank evidence). It groups 13 INSUFFICIENT_EVIDENCE results; full list in `answer_key.json`. No bank balance is substituted and nothing passes for SGA-EUR-01 external reconciliation on 15 Sep. The internal reconciliation for EUR on 15 Sep still passes because it uses ledger values. The reviewer decides on CASS 15.8.60R(4) notification; the system does not.
