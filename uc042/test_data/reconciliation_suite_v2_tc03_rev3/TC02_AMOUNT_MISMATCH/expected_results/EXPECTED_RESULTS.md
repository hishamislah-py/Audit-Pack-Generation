# TC02 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Amount mismatch: transaction export 3,053.61 vs bank 3,035.61 for E2E-GBP-0908-L02**

Customer label: SYNTHETIC TEST Brindle Wallet Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

Client C0006's bank-transfer load of Tue 8 Sep 2026 (E2E-GBP-0908-L02) was received by the bank, posted to the cash book and reflected in the client snapshot at 3,035.61. The transaction export (IN-11) shows 3,053.61: a transposition.

## Evidence files involved

- IN-11 `transactions_2026-09.csv` (mutated)
- unchanged on purpose: IN-09 BE-GBP-0908-L02 (3,035.61)
- unchanged on purpose: IN-10 LE-GBP-0908-0002 (3,035.61)
- unchanged on purpose: IN-03 C0006 snapshots

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **matching_reference:** E2E-GBP-0908-L02
- **source_amounts:** {"IN-11 TX-0908-00002": "3053.61", "IN-09 BE-GBP-0908-L02": "3035.61", "IN-10 LE-GBP-0908-0002": "3035.61"}
- **difference:** +18.00 (transaction minus bank)
- **direction:** transaction export overstates the receipt
- **outlier_source:** IN-11 (3,035.61 corroborated by IN-09, IN-10, IN-03)
- **financial_impact:** none on bank, ledger or requirement; client roll-forward for 8 Sep breaks by 18.00

**Key figures**

| metric | scope | value |
|---|---|
| rollforward|GBP/C0006 2026-09-08 | 39126.37 |
| rollforward|GBP/C0006 2026-09-09 | 39850.59 |
| snapshot|GBP/C0006 2026-09-08 | 39108.37 |
| snapshot|GBP/C0006 2026-09-09 | 39850.59 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `ROLLFWD GBP/C0006 2026-09-08 18.00`
- `TXN_BANK_AMOUNT TX-0908-00002 ref=E2E-GBP-0908-L02 txn=3053.61 bank=3035.61`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC02`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| CBAL-ROLLFWD | GBP/C0006 2026-09-08 | FAIL |
| RC4-DIRECT | TX-0908-00002 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC02-01 | High | `CBAL-ROLLFWD|GBP/C0006 2026-09-08` | 1 |
| EXC-TC02-02 | High | `RC4-DIRECT|TX-0908-00002` | 1 |

- Evidence statuses: none
- Investigation groups: none
- Candidate relationships (UNVERIFIED): none
- Must hold: CASH-BANK-LINK LE-GBP-0908-0002 PASS
- Must hold: C08 and C06 for 8 Sep PASS
- Must hold: CBAL-ROLLFWD GBP/C0006 2026-09-09 PASS
- Must hold: no investigation group (gap G-08)

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `PENDING:AMOUNT_MISMATCH`; gaps G-07, G-08, G-09, G-19.

- One root: amount mismatch on reference E2E-GBP-0908-L02, IN-11 3,053.61 vs IN-09 3,035.61, difference +18.00 (transaction > bank)
- CBAL-ROLLFWD failure linked by txn_id lineage
- Outlier source identified as IN-11

## 4. AI investigation expectations (separate from FIN)

- Finding: Both exceptions are one mismatch on TX-0908-00002
- Finding: Direction: export overstates by 18.00
- Finding: IN-11 is the outlier; 3,035.61 corroborated by IN-09, IN-10 and IN-03
- Finding: Difference divisible by 9: possible transposition (HYPOTHESIS, not evidence)
- Evidence reference: IN-11 TX-0908-00002
- Evidence reference: IN-09 BE-GBP-0908-L02
- Evidence reference: IN-10 LE-GBP-0908-0002
- Evidence reference: IN-03 CBS-20260907-C0006-GBP
- Evidence reference: IN-03 CBS-20260908-C0006-GBP
- Missing evidence: platform export audit trail
- Confidence: high
- Must not: recommend changing the bank or cash-book records

## 5. Expected analyst action

Accept the finding; request a corrected transaction export. No client-money shortfall.

## 6. Correction and re-upload

None for this scenario (by design).

