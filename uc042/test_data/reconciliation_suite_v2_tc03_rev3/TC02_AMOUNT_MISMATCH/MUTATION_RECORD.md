# TC02 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Amount mismatch: transaction export 3,053.61 vs bank 3,035.61 for E2E-GBP-0908-L02

**Customer label:** SYNTHETIC TEST Brindle Wallet Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | set_field | IN-11 `transactions_2026-09.csv` | `TX-0908-00002` | amount | 3035.61 | 3053.61 | transposition in the platform transaction export |

**Unchanged on purpose:**

- IN-09 BE-GBP-0908-L02 (3,035.61)
- IN-10 LE-GBP-0908-0002 (3,035.61)
- IN-03 C0006 snapshots
