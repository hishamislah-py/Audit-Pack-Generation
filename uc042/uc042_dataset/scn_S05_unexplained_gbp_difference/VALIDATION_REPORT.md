# Validation report — scn_S05_unexplained_gbp_difference

Produced by `python -m uc042lib.validate`. Every value below was recomputed from the source files; reported reconciliation values were compared, never copied. Synthetic data only; this is not a compliance conclusion.

**Overall:** 1887 check results — FAIL 13, NOT_APPLICABLE 78, PASS 1796

**Case status:** EXCEPTIONS_OPEN

## Files and row counts

Counting convention: CSV counts are **data rows, header excluded**; PDF counts are pages.

| File | Requirement | Count | Unit |
| --- | --- | ---: | --- |
| IN-01 `recon_calendar_2026-09.csv` | REQUIRED | 30 | data_rows |
| IN-02 `account_inventory.csv` | REQUIRED | 4 | data_rows |
| IN-03 `client_balance_snapshots_2026-09.csv` | REQUIRED | 276 | data_rows |
| IN-04 `unallocated_register_2026-09.csv` | REQUIRED | 2 | data_rows |
| IN-05 `internal_recon_records_2026-09.csv` | REQUIRED | 44 | data_rows |
| IN-06 `external_recon_records_2026-09.csv` | REQUIRED | 44 | data_rows |
| IN-07 `bank_balance_confirmations_2026-09.csv` | REQUIRED | 44 | data_rows |
| IN-08 `bank_statements_eod_2026-09.csv` | REQUIRED | 88 | data_rows |
| IN-09 `bank_statement_entries_2026-09.csv` | REQUIRED | 267 | data_rows |
| IN-10 `sga_cashbook_entries_2026-09.csv` | REQUIRED | 224 | data_rows |
| IN-11 `transactions_2026-09.csv` | REQUIRED | 422 | data_rows |
| IN-12 `settlement_batches_2026-09.csv` | REQUIRED | 88 | data_rows |
| IN-13 `settlement_lines_2026-09.csv` | REQUIRED | 420 | data_rows |
| IN-14 `discrepancy_log_2026-09.csv` | REQUIRED | 0 | data_rows |
| IN-15 `ack_letter_SGA-GBP-01.pdf` | REQUIRED | 1 | pages |
| IN-16 `ack_letter_SGA-EUR-01.pdf` | REQUIRED | 1 | pages |
| IN-17 `safeguarding_reconciliation_policy_v1.2.pdf` | REQUIRED | 1 | pages |
| IN-18 `governance_register_2026-09.pdf` | OPTIONAL | 1 | pages |
| IN-19 `rep027_submission_receipt_2026-08.pdf` | OPTIONAL | 1 | pages |

Total: 14 CSV files, 1953 data rows; 5 PDF files.

## Results by check

| Check | PASS | FAIL | INSUFFICIENT_EVIDENCE | NOT_APPLICABLE |
| --- | ---: | ---: | ---: | ---: |
| BANK-CASH-LINK | 0 | 1 | 0 | 0 |
| BC-VS-EOD | 44 | 0 | 0 | 0 |
| C01-COVER | 44 | 0 | 0 | 0 |
| C03-POINT | 3 | 0 | 0 | 0 |
| C03-POLICY | 1 | 0 | 0 | 0 |
| C04-REQUIREMENT | 44 | 0 | 0 | 0 |
| C05-RESOURCE | 44 | 0 | 0 | 0 |
| C06-DIFFERENCE | 0 | 0 | 0 | 44 |
| C07-BANK-EVIDENCE | 44 | 0 | 0 | 0 |
| C07-COVER | 44 | 0 | 0 | 0 |
| C08-DIFFERENCE | 0 | 10 | 0 | 34 |
| C09-ALLOCATION | 2 | 0 | 0 | 0 |
| C10-DESIGNATION | 2 | 0 | 0 | 0 |
| C11-BANK-ENTRY | 0 | 1 | 0 | 0 |
| C11-BATCH-ARITH | 88 | 0 | 0 | 0 |
| C11-BATCH-BANK | 88 | 0 | 0 | 0 |
| C11-TXN-LINE | 1 | 0 | 0 | 0 |
| C12-REFUND | 2 | 0 | 0 | 0 |
| C13-CURRENCY | 1 | 0 | 0 | 0 |
| C14-COVER | 484 | 0 | 0 | 0 |
| C16-GOVERNANCE | 1 | 0 | 0 | 0 |
| C16-RETURN | 1 | 0 | 0 | 0 |
| CASH-BANK-LINK | 222 | 0 | 0 | 0 |
| CBAL-NONNEG | 1 | 0 | 0 | 0 |
| CBAL-ROLLFWD | 264 | 0 | 0 | 0 |
| DISC-LOG | 0 | 1 | 0 | 0 |
| DQ22-CONTINUITY | 86 | 0 | 0 | 0 |
| DQ23-STATEMENT | 88 | 0 | 0 | 0 |
| FUND-TOPUP | 44 | 0 | 0 | 0 |
| RC2-LEDGER | 44 | 0 | 0 | 0 |
| RC4-DIRECT | 90 | 0 | 0 | 0 |
| V01-PDF | 5 | 0 | 0 | 0 |
| V01-SCHEMA | 14 | 0 | 0 | 0 |

## Exceptions (one per root cause)

### EXC-S05-01 — Critical — Unexplained bank-ledger difference (OPEN)

- Root cause: `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-17|-812.40`
- Scope: SGA-GBP-01 GBP 2026-09-17 to 2026-09-30; amount -812.40
- Affected results (11): C08-DIFFERENCE 2026-09-17/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-18/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-21/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-22/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-23/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-24/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-25/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-28/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-29/SGA-GBP-01 [FAIL]; C08-DIFFERENCE 2026-09-30/SGA-GBP-01 [FAIL]; DISC-LOG SGA-GBP-01 from 2026-09-17 [FAIL]
- Flags: OWN_FUNDS_REQUIRED (CASS 15.8.57R: ledger shows a greater need than the bank holds); NO_INVESTIGATION_LOGGED
- Related records: BE-GBP-0917-X01 (unreconciled entry on the statement where the difference first appears; not linked by amount)
- Evidence status: **NOT_EVIDENCED**
- Investigation group: `GRP-S05-01`
- Evidence: IN-06:external_recon_records_2026-09.csv#L26; IN-07:bank_balance_confirmations_2026-09.csv#L26; IN-06:external_recon_records_2026-09.csv#L28; IN-07:bank_balance_confirmations_2026-09.csv#L28; IN-06:external_recon_records_2026-09.csv#L30; IN-07:bank_balance_confirmations_2026-09.csv#L30; IN-06:external_recon_records_2026-09.csv#L32; IN-07:bank_balance_confirmations_2026-09.csv#L32; IN-06:external_recon_records_2026-09.csv#L34; IN-07:bank_balance_confirmations_2026-09.csv#L34; IN-06:external_recon_records_2026-09.csv#L36; IN-07:bank_balance_confirmations_2026-09.csv#L36; IN-06:external_recon_records_2026-09.csv#L38; IN-07:bank_balance_confirmations_2026-09.csv#L38; IN-06:external_recon_records_2026-09.csv#L40; IN-07:bank_balance_confirmations_2026-09.csv#L40; IN-06:external_recon_records_2026-09.csv#L42; IN-07:bank_balance_confirmations_2026-09.csv#L42; IN-06:external_recon_records_2026-09.csv#L44; IN-07:bank_balance_confirmations_2026-09.csv#L44; IN-14:discrepancy_log_2026-09.csv
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-S05-02 — High — Bank entry with no counterpart (OPEN)

- Root cause: `UNMATCHED_BANK_ENTRY|BE-GBP-0917-X01`
- Scope: SGA-GBP-01 GBP 2026-09-17 to 2026-09-17; amount -812.40
- Affected results (2): BANK-CASH-LINK BE-GBP-0917-X01 [FAIL]; C11-BANK-ENTRY BE-GBP-0917-X01 [FAIL]
- Investigation group: `GRP-S05-01`
- Evidence: IN-09:bank_statement_entries_2026-09.csv#L152
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)


## Investigation groups (evidence-linked; never set a cause or close an exception)

### GRP-S05-01 — 2 exceptions (OPEN; review: AWAITING_HUMAN_REVIEW)

- Exceptions: EXC-S05-01; EXC-S05-02
- Link types: L3 LINEAGE
- Links: EXC-S05-01—EXC-S05-02 L3 LINEAGE: bank entry BE-GBP-0917-X01 is inside the 2026-09-17 17:00 balance of SGA-GBP-01, where the difference begins [IN-09:bank_statement_entries_2026-09.csv#L152, IN-07:bank_balance_confirmations_2026-09.csv#L26]


## Candidate relationships (UNVERIFIED — not evidence-backed; not groups)

None.

## Answer key

MATCH: results and exceptions are exactly as expected.

## Not independently verified in milestone 1

- Resource items B–D: taken as reported (all 0.00). No independent source exists (gap G-S04).
- D+1 comparison: not performed; blank by synthetic convention (gap G-R05).
- Own-funds account opening balances: synthetic, no independent source. Not assessed; no result is emitted.
- Client balance roll-forward is assessed from the earliest snapshot provided; with the 31 Aug opening snapshot (D4), every September day-pair is assessed.
- Reported values (IN-05, IN-06) and source records come from the same synthetic simulation: validation proves mutual consistency, not operational truth.
- NOT_APPLICABLE is used only for: no difference to resolve (C06, C08); optional evidence not provided (V00-FILE, C16); allocation of a receipt received before the period start, whose bank credit is outside the period (RC4, convention P1).
- PDF key details are parsed deterministically from a fixed synthetic layout. Reviewer confirmation (DQ17) is not modelled.
- Not in scope for milestone 1: pack statements (C15), exception workflow, timing-difference evidence (no differences exist).
- Invalid rows are excluded and reported (DQ-FIELD). A scope an excluded row could have affected returns INSUFFICIENT_EVIDENCE; where an excluded row's own account, date or reference is unreadable, every scope it might touch is treated as affected.
