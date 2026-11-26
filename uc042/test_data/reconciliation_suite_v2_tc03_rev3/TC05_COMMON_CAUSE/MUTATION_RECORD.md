# TC05 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export

**Customer label:** SYNTHETIC TEST Elmstead Card Services Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | delete_record | IN-11 `transactions_2026-09.csv` | `TX-0924-00018` | (record) | present | deleted | export omitted the batch's spends (C0104, 222.18) |
| 2 | delete_record | IN-11 `transactions_2026-09.csv` | `TX-0924-00019` | (record) | present | deleted | export omitted the batch's spends (C0101, 431.57) |
| 3 | delete_record | IN-11 `transactions_2026-09.csv` | `TX-0924-00020` | (record) | present | deleted | export omitted the batch's spends (C0101, 193.70) |

**Unchanged on purpose:**

- IN-12 SB-EUR-20260924
- IN-13 SL-SB-EUR-20260924-0001..0003
- IN-09 BE-EUR-0924-SB1
- IN-10 LE-EUR-0924-0004
- IN-03 snapshots
