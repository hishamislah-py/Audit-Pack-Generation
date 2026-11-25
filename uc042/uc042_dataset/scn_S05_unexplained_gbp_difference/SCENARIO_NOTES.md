> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.

# Scenario S05 — Unexplained GBP difference of £812.40 from 17 Sep 2026 (synthetic)

**Changes vs the clean baseline** (exact list, with old and new values, in `mutations.json`):

- Added bank entry `BE-GBP-0917-X01`: £812.40 debit at 15:20 on 17 Sep, reference `SETTLE 0417` (IN-09).
- SGA-GBP-01 end-of-day statements from 17 Sep: closing balances reduced by 812.40; later openings reduced to match; 17 Sep `entry_count` + 1 (IN-08).
- 17:00 confirmations reduced by 812.40 on the 10 reconciliation days 17–30 Sep (IN-07).
- External reconciliation records for those days now report the lower bank balance and a difference of −812.40, with no timing claim (IN-06).

**Kept unchanged on purpose:**

- The cash book (the ledger), client balances and internal reconciliation records.
- Transactions, settlement batches and lines (nothing carries `SETTLE 0417`).
- The discrepancy log (no investigation entry).

**Expected result:**

- `EXC-S05-01` (Critical): unexplained bank-ledger difference on 10 days. Flags: own-funds top-up indicated (CASS 15.8.57R) and no investigation logged.
- `EXC-S05-02` (High): the bank entry has no counterpart.

The entry is listed as related to EXC-S05-01 because it sits on the statement where the difference first appears. It is not linked by amount. No cause is set; closing requires evidence and a reviewer.
