# Date and data-quality report — January–August 2026

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

Produced by `verification/verify_history.py` (independent of the engine). Full detail: `verification/data_quality_results.json`.

| Month | Calendar days | Recon days | Checks | Problems | Timestamp offsets | Expected (by design) findings |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 2026-01 | 31 | 21 | 43,979 | 0 | GMT +00:00: 1827 | — |
| 2026-02 | 28 | 20 | 41,549 | 0 | GMT +00:00: 1728 | cash-book entries whose bank entry is on the missing statement (expected) (5); batches whose bank entry is on the missing statement (expected) (2); statement continuity not assessable across the missing day (expected) (1); external records without a confirmation (missing evidence, expected) (1) |
| 2026-03 | 31 | 22 | 46,015 | 0 | GMT +00:00: 1740, BST +01:00: 172 | — |
| 2026-04 | 30 | 20 | 42,133 | 0 | BST +01:00: 1750 | — |
| 2026-05 | 31 | 19 | 39,583 | 0 | BST +01:00: 1644 | cash-book entries whose bank entry is on the missing statement (expected) (5); batches whose bank entry is on the missing statement (expected) (2); statement continuity not assessable across the missing day (expected) (1); external records without a confirmation (missing evidence, expected) (1) |
| 2026-06 | 30 | 22 | 45,945 | 0 | BST +01:00: 1910 | batches affected by the planted reference mismatch (expected) (2) |
| 2026-07 | 31 | 23 | 47,371 | 0 | BST +01:00: 1971 | cash-book entries whose bank entry is on the missing statement (expected) (5); batches affected by the planted reference mismatch (expected) (2); batches whose bank entry is on the missing statement (expected) (2); statement continuity not assessable across the missing day (expected) (1); external records without a confirmation (missing evidence, expected) (1) |
| 2026-08 | 31 | 20 | 42,855 | 0 | BST +01:00: 1781 | cash-book entries whose bank entry is on the missing statement (expected) (5); batches affected by the planted reference mismatch (expected) (2); batches whose bank entry is on the missing statement (expected) (2); statement continuity not assessable across the missing day (expected) (1); external records without a confirmation (missing evidence, expected) (1) |

## What was checked (every month)

- **Files and schema:** 14 CSV files with the contract headers; every value type- and enum-checked with the project's own `field_error`; mandatory fields populated.
- **Identifiers:** primary keys unique within each month; no exact duplicate rows; no natural-key duplicate bank entries.
- **Dates:** every date inside its month, except the documented opening rows (snapshot and cash-book opening at the previous month end, 17:00).
- **Timezone:** every timestamp's offset equals the Europe/London offset for that instant: **GMT (+00:00) until 29 Mar 2026 01:00, BST (+01:00) after**. March contains both.
- **Point and date consistency:** booking timestamp local date = booking date; snapshots and reconciliation points at 17:00 on their own date.
- **Calendar:** every day present; reconciliation days = weekdays minus England & Wales bank holidays (1 Jan, 3 Apr, 6 Apr, 4 May, 25 May, 31 Aug).
- **References:** cash book ↔ bank (one-to-one by reference, amounts equal, opposite D/C); batch → bank by reference and net; line → transaction; transaction → batch; refund → original; unallocated receipt → bank, allocated within the month.
- **Arithmetic:** statement opening + entries = closing; entry counts; day-to-day continuity; 17:00 confirmation = opening + entries to 17:00; batch lines = header totals; gross − fees (or refunds) = net.
- **Balances:** requirement (client snapshots + open unallocated) = reported = cash book at 17:00; bank − ledger = 0 except on planted days.
- **Currency:** every record's currency equals its account's currency; GBP and EUR never combined.
- **Missing evidence:** removed records are absent, not zero-filled; checks that depend on them are reported as not assessable.

## Timing differences versus errors

No legitimate transaction-to-bank timing difference is planted in January–August: every cash-book posting date equals its bank booking date, and every batch is booked on its settlement date (checked). Transaction date, authorisation timestamp, clearing date, settlement date, bank booking date, cash-book posting date, reconciliation date, snapshot date and document date remain separate fields. Card loads are authorised at 08:05+ and settle the same day at 14:00; spends are authorised from 07:15 and settle at 15:00 (convention D8). These intraday sequences are by design, not inconsistencies.

## Cross-month identifiers

- Account inventory (IN-02): the same 4 standing accounts in every month (expected master data).
- Client snapshots (IN-03): 48 records appear in two months: the opening snapshot of a month whose previous month ended on a reconciliation day is byte-identical to that month's closing snapshot (carried-forward position, same ID and values). No conflicting duplicate exists.
- All other identifiers embed the date and are unique across months.

