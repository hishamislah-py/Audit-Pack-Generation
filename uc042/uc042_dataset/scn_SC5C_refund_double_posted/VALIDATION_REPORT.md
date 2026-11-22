# Validation report — scn_SC5C_refund_double_posted

Produced by `python -m uc042lib.validate`. Every value below was recomputed from the source files; reported reconciliation values were compared, never copied. Synthetic data only; this is not a compliance conclusion.

**Overall:** 1886 check results — FAIL 17, NOT_APPLICABLE 72, PASS 1797

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
| IN-09 `bank_statement_entries_2026-09.csv` | REQUIRED | 266 | data_rows |
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

Total: 14 CSV files, 1952 data rows; 5 PDF files.

## Results by check

| Check | PASS | FAIL | INSUFFICIENT_EVIDENCE | NOT_APPLICABLE |
| --- | ---: | ---: | ---: | ---: |
| BC-VS-EOD | 44 | 0 | 0 | 0 |
| C01-COVER | 44 | 0 | 0 | 0 |
| C03-POINT | 3 | 0 | 0 | 0 |
| C03-POLICY | 1 | 0 | 0 | 0 |
| C04-REQUIREMENT | 44 | 0 | 0 | 0 |
| C05-RESOURCE | 44 | 0 | 0 | 0 |
| C06-DIFFERENCE | 0 | 16 | 0 | 28 |
| C07-BANK-EVIDENCE | 44 | 0 | 0 | 0 |
| C07-COVER | 44 | 0 | 0 | 0 |
| C08-DIFFERENCE | 0 | 0 | 0 | 44 |
| C09-ALLOCATION | 2 | 0 | 0 | 0 |
| C10-DESIGNATION | 2 | 0 | 0 | 0 |
| C11-BANK-ENTRY | 1 | 0 | 0 | 0 |
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
| CBAL-ROLLFWD | 263 | 1 | 0 | 0 |
| DISC-LOG | 1 | 0 | 0 | 0 |
| DQ22-CONTINUITY | 86 | 0 | 0 | 0 |
| DQ23-STATEMENT | 88 | 0 | 0 | 0 |
| FUND-TOPUP | 44 | 0 | 0 | 0 |
| RC2-LEDGER | 44 | 0 | 0 | 0 |
| RC4-DIRECT | 90 | 0 | 0 | 0 |
| V01-PDF | 5 | 0 | 0 | 0 |
| V01-SCHEMA | 14 | 0 | 0 | 0 |

## Exceptions (one per root cause)

### EXC-SC5C-01 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-09/GBP`
- Scope:   2026-09-09 to 2026-09-09
- Affected results (1): C06-DIFFERENCE 2026-09-09/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L14
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-02 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-10/GBP`
- Scope:   2026-09-10 to 2026-09-10
- Affected results (1): C06-DIFFERENCE 2026-09-10/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L16
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-03 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-11/GBP`
- Scope:   2026-09-11 to 2026-09-11
- Affected results (1): C06-DIFFERENCE 2026-09-11/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L18
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-04 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-14/GBP`
- Scope:   2026-09-14 to 2026-09-14
- Affected results (1): C06-DIFFERENCE 2026-09-14/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L20
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-05 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-15/GBP`
- Scope:   2026-09-15 to 2026-09-15
- Affected results (1): C06-DIFFERENCE 2026-09-15/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L22
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-06 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-16/GBP`
- Scope:   2026-09-16 to 2026-09-16
- Affected results (1): C06-DIFFERENCE 2026-09-16/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L24
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-07 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-17/GBP`
- Scope:   2026-09-17 to 2026-09-17
- Affected results (1): C06-DIFFERENCE 2026-09-17/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L26
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-08 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-18/GBP`
- Scope:   2026-09-18 to 2026-09-18
- Affected results (1): C06-DIFFERENCE 2026-09-18/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L28
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-09 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-21/GBP`
- Scope:   2026-09-21 to 2026-09-21
- Affected results (1): C06-DIFFERENCE 2026-09-21/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L30
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-10 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-22/GBP`
- Scope:   2026-09-22 to 2026-09-22
- Affected results (1): C06-DIFFERENCE 2026-09-22/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L32
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-11 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-23/GBP`
- Scope:   2026-09-23 to 2026-09-23
- Affected results (1): C06-DIFFERENCE 2026-09-23/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L34
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-12 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-24/GBP`
- Scope:   2026-09-24 to 2026-09-24
- Affected results (1): C06-DIFFERENCE 2026-09-24/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L36
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-13 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-25/GBP`
- Scope:   2026-09-25 to 2026-09-25
- Affected results (1): C06-DIFFERENCE 2026-09-25/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L38
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-14 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-28/GBP`
- Scope:   2026-09-28 to 2026-09-28
- Affected results (1): C06-DIFFERENCE 2026-09-28/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L40
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-15 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-29/GBP`
- Scope:   2026-09-29 to 2026-09-29
- Affected results (1): C06-DIFFERENCE 2026-09-29/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L42
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-16 — Critical — Internal reconciliation difference (OPEN)

- Root cause: `INTERNAL_DIFFERENCE|2026-09-30/GBP`
- Scope:   2026-09-30 to 2026-09-30
- Affected results (1): C06-DIFFERENCE 2026-09-30/GBP [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-05:internal_recon_records_2026-09.csv#L44
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)

### EXC-SC5C-17 — High — CBAL-ROLLFWD (OPEN)

- Root cause: `CBAL-ROLLFWD|GBP/C0002 2026-09-09`
- Scope:    to 
- Affected results (1): CBAL-ROLLFWD GBP/C0002 2026-09-09 [FAIL]
- Investigation group: `GRP-SC5C-01`
- Evidence: IN-03:client_balance_snapshots_2026-09.csv#L75; IN-03:client_balance_snapshots_2026-09.csv#L87; IN-11:transactions_2026-09.csv#L122; IN-11:transactions_2026-09.csv#L130; IN-11:transactions_2026-09.csv#L134
- Status: OPEN; review: AWAITING_HUMAN_REVIEW
- Cause: not established (no cause is set without evidence)


## Investigation groups (evidence-linked; never set a cause or close an exception)

### GRP-SC5C-01 — 17 exceptions (OPEN; review: AWAITING_HUMAN_REVIEW)

- Exceptions: EXC-SC5C-01; EXC-SC5C-02; EXC-SC5C-03; EXC-SC5C-04; EXC-SC5C-05; EXC-SC5C-06; EXC-SC5C-07; EXC-SC5C-08; EXC-SC5C-09; EXC-SC5C-10; EXC-SC5C-11; EXC-SC5C-12; EXC-SC5C-13; EXC-SC5C-14; EXC-SC5C-15; EXC-SC5C-16; EXC-SC5C-17
- Link types: L2 PERSISTENCE; L3 LINEAGE
- Links: EXC-SC5C-01—EXC-SC5C-02 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L14, IN-05:internal_recon_records_2026-09.csv#L16] | EXC-SC5C-01—EXC-SC5C-17 L3 LINEAGE: snapshot of C0002 on 2026-09-09 fails the roll-forward and is an input to the GBP requirement on 2026-09-09 [IN-03:client_balance_snapshots_2026-09.csv#L87] | EXC-SC5C-02—EXC-SC5C-03 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L16, IN-05:internal_recon_records_2026-09.csv#L18] | EXC-SC5C-03—EXC-SC5C-04 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L18, IN-05:internal_recon_records_2026-09.csv#L20] | EXC-SC5C-04—EXC-SC5C-05 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L20, IN-05:internal_recon_records_2026-09.csv#L22] | EXC-SC5C-05—EXC-SC5C-06 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L22, IN-05:internal_recon_records_2026-09.csv#L24] | EXC-SC5C-06—EXC-SC5C-07 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L24, IN-05:internal_recon_records_2026-09.csv#L26] | EXC-SC5C-07—EXC-SC5C-08 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L26, IN-05:internal_recon_records_2026-09.csv#L28] | EXC-SC5C-08—EXC-SC5C-09 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L28, IN-05:internal_recon_records_2026-09.csv#L30] | EXC-SC5C-09—EXC-SC5C-10 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L30, IN-05:internal_recon_records_2026-09.csv#L32] | EXC-SC5C-10—EXC-SC5C-11 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L32, IN-05:internal_recon_records_2026-09.csv#L34] | EXC-SC5C-11—EXC-SC5C-12 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L34, IN-05:internal_recon_records_2026-09.csv#L36] | EXC-SC5C-12—EXC-SC5C-13 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L36, IN-05:internal_recon_records_2026-09.csv#L38] | EXC-SC5C-13—EXC-SC5C-14 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L38, IN-05:internal_recon_records_2026-09.csv#L40] | EXC-SC5C-14—EXC-SC5C-15 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L40, IN-05:internal_recon_records_2026-09.csv#L42] | EXC-SC5C-15—EXC-SC5C-16 L2 PERSISTENCE: same internal difference -60.00 on consecutive reconciliation days (GBP) [IN-05:internal_recon_records_2026-09.csv#L42, IN-05:internal_recon_records_2026-09.csv#L44]


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
