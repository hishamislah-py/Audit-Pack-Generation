# Validation report — scn_S02_missing_eur_statement

Produced by `python -m uc042lib.validate`. Every value below was recomputed from the source files; reported reconciliation values were compared, never copied. Synthetic data only; this is not a compliance conclusion.

**Overall:** 1883 check results — INSUFFICIENT_EVIDENCE 13, NOT_APPLICABLE 87, PASS 1783

**Case status:** EVIDENCE_INCOMPLETE

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
| IN-07 `bank_balance_confirmations_2026-09.csv` | REQUIRED | 43 | data_rows |
| IN-08 `bank_statements_eod_2026-09.csv` | REQUIRED | 87 | data_rows |
| IN-09 `bank_statement_entries_2026-09.csv` | REQUIRED | 262 | data_rows |
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

Total: 14 CSV files, 1946 data rows; 5 PDF files.

## Results by check

| Check | PASS | FAIL | INSUFFICIENT_EVIDENCE | NOT_APPLICABLE |
| --- | ---: | ---: | ---: | ---: |
| BC-VS-EOD | 43 | 0 | 0 | 0 |
| C01-COVER | 44 | 0 | 0 | 0 |
| C03-POINT | 3 | 0 | 0 | 0 |
| C03-POLICY | 1 | 0 | 0 | 0 |
| C04-REQUIREMENT | 44 | 0 | 0 | 0 |
| C05-RESOURCE | 44 | 0 | 0 | 0 |
| C06-DIFFERENCE | 0 | 0 | 0 | 44 |
| C07-BANK-EVIDENCE | 43 | 0 | 1 | 0 |
| C07-COVER | 44 | 0 | 0 | 0 |
| C08-DIFFERENCE | 0 | 0 | 1 | 43 |
| C09-ALLOCATION | 2 | 0 | 0 | 0 |
| C10-DESIGNATION | 2 | 0 | 0 | 0 |
| C11-BANK-ENTRY | 1 | 0 | 0 | 0 |
| C11-BATCH-ARITH | 88 | 0 | 0 | 0 |
| C11-BATCH-BANK | 86 | 0 | 2 | 0 |
| C11-TXN-LINE | 1 | 0 | 0 | 0 |
| C12-REFUND | 2 | 0 | 0 | 0 |
| C13-CURRENCY | 1 | 0 | 0 | 0 |
| C14-COVER | 482 | 0 | 2 | 0 |
| C16-GOVERNANCE | 1 | 0 | 0 | 0 |
| C16-RETURN | 1 | 0 | 0 | 0 |
| CASH-BANK-LINK | 218 | 0 | 4 | 0 |
| CBAL-NONNEG | 1 | 0 | 0 | 0 |
| CBAL-ROLLFWD | 264 | 0 | 0 | 0 |
| DISC-LOG | 1 | 0 | 0 | 0 |
| DQ22-CONTINUITY | 84 | 0 | 1 | 0 |
| DQ23-STATEMENT | 87 | 0 | 0 | 0 |
| FUND-TOPUP | 43 | 0 | 1 | 0 |
| RC2-LEDGER | 44 | 0 | 0 | 0 |
| RC4-DIRECT | 89 | 0 | 1 | 0 |
| V01-PDF | 5 | 0 | 0 | 0 |
| V01-SCHEMA | 14 | 0 | 0 | 0 |

## Exceptions (one per root cause)

### EXC-S02-01 — Critical — Missing bank evidence (OPEN)

- Root cause: `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-09-15`
- Scope: SGA-EUR-01 EUR 2026-09-15 to 2026-09-15
- Affected results (13): C14-COVER IN-07 2026-09-15/SGA-EUR-01 [INSUFFICIENT_EVIDENCE]; C14-COVER IN-08 2026-09-15/SGA-EUR-01 [INSUFFICIENT_EVIDENCE]; DQ22-CONTINUITY ST-SGA-EUR-01-20260916-EOD [INSUFFICIENT_EVIDENCE]; CASH-BANK-LINK LE-EUR-0915-0001 [INSUFFICIENT_EVIDENCE]; CASH-BANK-LINK LE-EUR-0915-0002 [INSUFFICIENT_EVIDENCE]; CASH-BANK-LINK LE-EUR-0915-0003 [INSUFFICIENT_EVIDENCE]; CASH-BANK-LINK LE-EUR-0915-0004 [INSUFFICIENT_EVIDENCE]; C07-BANK-EVIDENCE 2026-09-15/SGA-EUR-01 [INSUFFICIENT_EVIDENCE]; C08-DIFFERENCE 2026-09-15/SGA-EUR-01 [INSUFFICIENT_EVIDENCE]; C11-BATCH-BANK AQ-EUR-20260915 [INSUFFICIENT_EVIDENCE]; C11-BATCH-BANK SB-EUR-20260915 [INSUFFICIENT_EVIDENCE]; FUND-TOPUP AQ-EUR-20260915 [INSUFFICIENT_EVIDENCE]; RC4-DIRECT TX-0915-00013 [INSUFFICIENT_EVIDENCE]
- Evidence: IN-01:recon_calendar_2026-09.csv#L16; IN-02:account_inventory.csv#L3; IN-08:bank_statements_eod_2026-09.csv#L39; IN-08:bank_statements_eod_2026-09.csv#L46; IN-10:sga_cashbook_entries_2026-09.csv#L110; IN-10:sga_cashbook_entries_2026-09.csv#L111; IN-10:sga_cashbook_entries_2026-09.csv#L112; IN-10:sga_cashbook_entries_2026-09.csv#L113; IN-06:external_recon_records_2026-09.csv#L23; IN-12:settlement_batches_2026-09.csv#L44; IN-12:settlement_batches_2026-09.csv#L45; IN-11:transactions_2026-09.csv#L201
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)


## Investigation groups (evidence-linked; never set a cause or close an exception)

None.

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
