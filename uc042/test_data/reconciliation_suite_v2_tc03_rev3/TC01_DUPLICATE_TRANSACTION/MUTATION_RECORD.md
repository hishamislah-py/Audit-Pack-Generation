# TC01 - Mutation record (initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80)

**Customer label:** SYNTHETIC TEST Ashcombe Pay Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | add_record | IN-10 `sga_cashbook_entries_2026-09.csv` | `LE-GBP-0928-0007` | (record) | absent | added after LE-GBP-0928-0001: account_id=SGA-GBP-01, posted_ts=2026-09-28T09:25:00+01:00, entry_type=BANK_LOAD, amount=1246.80, dc_indicator=D, currency=GBP, payment_reference=E2E-GBP-0928-L01 | interface re-run re-posted the 09:10 receipt E2E-GBP-0928-L01 |

**Unchanged on purpose:**

- IN-09 (one bank credit BE-GBP-0928-L01)
- IN-11 (one LOAD_BANK TX-0928-00001)
- IN-03 snapshots
- IN-05 and IN-06 reported values
- IN-14 (header only)
