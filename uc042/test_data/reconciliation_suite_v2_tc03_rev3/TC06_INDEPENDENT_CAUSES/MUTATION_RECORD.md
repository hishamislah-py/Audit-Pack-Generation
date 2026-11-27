# TC06 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Independent causes: export amount error (A), client snapshot error (B), acquirer line error (C); A and B share date and 90.00

**Customer label:** SYNTHETIC TEST Farrowdale E-Money Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | set_field | IN-11 `transactions_2026-09.csv` | `TX-0917-00002` | amount | 1390.07 | 1480.07 | cause A: export amount error |
| 2 | set_field | IN-03 `client_balance_snapshots_2026-09.csv` | `CBS-20260917-C0004-GBP` | balance | 40592.24 | 40682.24 | cause B: client-ledger snapshot overstated |
| 3 | set_field | IN-05 `internal_recon_records_2026-09.csv` | `IRR-EMONEY-GBP-20260917` | requirement_reported | 341484.46 | 341574.46 | cause B: firm's reconciliation used the ledger |
| 4 | set_field | IN-05 `internal_recon_records_2026-09.csv` | `IRR-EMONEY-GBP-20260917` | difference_reported | 0.00 | -90.00 | cause B: reported shortfall |
| 5 | set_field | IN-13 `settlement_lines_2026-09.csv` | `SL-AQ-EUR-20260922-0002` | amount | 1283.12 | 1238.12 | cause C: acquirer report line mis-stated |

**Unchanged on purpose:**

- IN-09/IN-10 for E2E-GBP-0917-L02 (1,390.07)
- IN-03 C0004 snapshots other than 17 Sep
- IN-12 AQ-EUR-20260922 header
- IN-11 TX-0922-00016 (1,283.12)
- IN-09 BE-EUR-0922-AQ1
