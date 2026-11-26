# TC06 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Independent causes: export amount error (A), client snapshot error (B), acquirer line error (C); A and B share date and 90.00**

Customer label: SYNTHETIC TEST Farrowdale E-Money Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

Three unrelated defects. A: C0007's bank load TX-0917-00002 shows 1,480.07 in the export against 1,390.07 at the bank. B: C0004's 17 Sep 17:00 client-ledger snapshot is overstated by 90.00 and the firm's internal reconciliation used it. C: line 2 of acquirer batch AQ-EUR-20260922 states 1,238.12 against 1,283.12. A and B deliberately share date (17 Sep), currency (GBP) and magnitude (90.00): a decoy coincidence that must not be treated as a link.

## Evidence files involved

- IN-03 `client_balance_snapshots_2026-09.csv` (mutated)
- IN-05 `internal_recon_records_2026-09.csv` (mutated)
- IN-11 `transactions_2026-09.csv` (mutated)
- IN-13 `settlement_lines_2026-09.csv` (mutated)
- unchanged on purpose: IN-09/IN-10 for E2E-GBP-0917-L02 (1,390.07)
- unchanged on purpose: IN-03 C0004 snapshots other than 17 Sep
- unchanged on purpose: IN-12 AQ-EUR-20260922 header
- unchanged on purpose: IN-11 TX-0922-00016 (1,283.12)
- unchanged on purpose: IN-09 BE-EUR-0922-AQ1

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **A:** {"records": ["IN-11 TX-0917-00002", "IN-09 BE-GBP-0917-L02", "IN-10 LE-GBP-0917-0002"], "difference": "+90.00 transaction minus bank", "outlier": "IN-11"}
- **B:** {"records": ["IN-03 CBS-20260917-C0004-GBP", "IN-05 IRR-EMONEY-GBP-20260917"], "difference": "snapshot +90.00 (roll-forward 17 Sep -90.00, 18 Sep +90.00); reported shortfall -90.00 not supported by transactions"}
- **C:** {"records": ["IN-13 SL-AQ-EUR-20260922-0002", "IN-12 AQ-EUR-20260922", "IN-11 TX-0922-00016"], "difference": "-45.00 line vs header and transaction"}
- **decoy:** A and B: same date 2026-09-17, same currency GBP, same magnitude 90.00; NO shared record, client or reference

**Key figures**

| metric | scope | value |
|---|---|
| requirement_1700|2026-09-17/GBP | 341574.46 |
| resource_1700|2026-09-17/GBP | 341484.46 |
| rollforward|GBP/C0004 2026-09-17 | 40592.24 |
| rollforward|GBP/C0004 2026-09-18 | 42175.13 |
| rollforward|GBP/C0007 2026-09-17 | 36731.11 |
| snapshot|GBP/C0004 2026-09-17 | 40682.24 |
| snapshot|GBP/C0004 2026-09-18 | 42085.13 |
| snapshot|GBP/C0007 2026-09-17 | 36641.11 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `BATCH_ARITH AQ-EUR-20260922 NET lines=2059.53 header=2104.53`
- `BATCH_ARITH AQ-EUR-20260922 TXN lines=2069.15 header=2114.15`
- `LINE_TXN SL-AQ-EUR-20260922-0002 TX-0922-00016 amount line=1238.12 txn=1283.12`
- `ROLLFWD GBP/C0004 2026-09-17 -90.00`
- `ROLLFWD GBP/C0004 2026-09-18 90.00`
- `ROLLFWD GBP/C0007 2026-09-17 90.00`
- `RR_DIFF 2026-09-17 GBP -90.00`
- `TXN_BANK_AMOUNT TX-0917-00002 ref=E2E-GBP-0917-L02 txn=1480.07 bank=1390.07`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC06`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| C06-DIFFERENCE | 2026-09-17/GBP | FAIL |
| C11-BATCH-ARITH | AQ-EUR-20260922 | FAIL |
| CBAL-ROLLFWD | GBP/C0004 2026-09-17 | FAIL |
| CBAL-ROLLFWD | GBP/C0004 2026-09-18 | FAIL |
| CBAL-ROLLFWD | GBP/C0007 2026-09-17 | FAIL |
| RC4-DIRECT | TX-0917-00002 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC06-01 | Critical | `INTERNAL_DIFFERENCE|2026-09-17/GBP` | 1 |
| EXC-TC06-02 | High | `C11-BATCH-ARITH|AQ-EUR-20260922` | 1 |
| EXC-TC06-03 | High | `CBAL-ROLLFWD|GBP/C0004 2026-09-17` | 1 |
| EXC-TC06-04 | High | `CBAL-ROLLFWD|GBP/C0004 2026-09-18` | 1 |
| EXC-TC06-05 | High | `CBAL-ROLLFWD|GBP/C0007 2026-09-17` | 1 |
| EXC-TC06-06 | High | `RC4-DIRECT|TX-0917-00002` | 1 |

- Evidence statuses: none
- Investigation groups: [['EXC-TC06-01', 'EXC-TC06-03', 'EXC-TC06-05']]
- Candidate relationships (UNVERIFIED): none
- Must hold: C04-REQUIREMENT 2026-09-17/GBP PASS (firm reported the overstated requirement)
- Must hold: No candidates
- **Note:** PREDICTED OVER-GROUPING, UNVERIFIED (gap G-18): L3 lineage (b) is predicted to link the 17 Sep internal difference to EVERY same-day GBP roll-forward failure, including EXC-TC06-05 (C0007, cause A, whose snapshot is correct). EXC-TC06-04 (C0004 next day) and EXC-TC06-06 (C0007 RC4) are predicted ungrouped. This must be confirmed by an engine run before it is reported as engine behaviour.

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `three independent roots`; gaps G-08, G-18, G-19.

- Cluster A {EXC-TC06-06, EXC-TC06-05}: PENDING:AMOUNT_MISMATCH on TX-0917-00002
- Cluster B {EXC-TC06-01, EXC-TC06-03, EXC-TC06-04}: client snapshot error C0004 17 Sep
- Cluster C {EXC-TC06-02}: acquirer report line inconsistency
- A/B coincidence recorded as REJECTED (no shared record or reference)

## 4. AI investigation expectations (separate from FIN)

- Finding: Three separate causes
- Finding: A is transaction-side: IN-11 is the outlier against IN-09, IN-10, IN-03
- Finding: B is snapshot-side: C0004's 17 Sep snapshot fails the roll-forward in both directions and drives the reported shortfall
- Finding: C is internal to the acquirer report: header, transaction and bank agree on 1,283.12
- Finding: Equal date and amount of A and B is coincidence, explicitly rejected as a link
- Evidence reference: IN-11 TX-0917-00002
- Evidence reference: IN-09 BE-GBP-0917-L02
- Evidence reference: IN-03 CBS-20260916/17/18-C0004-GBP
- Evidence reference: IN-05 IRR-EMONEY-GBP-20260917
- Evidence reference: IN-13 SL-AQ-EUR-20260922-0002
- Evidence reference: IN-12 AQ-EUR-20260922
- Evidence reference: IN-11 TX-0922-00016
- Missing evidence: A: export audit trail
- Missing evidence: B: client-ledger postings behind C0004's 17 Sep balance
- Missing evidence: C: corrected acquirer report
- Confidence: high for the separation
- Must not: group A with B on date and amount

## 5. Expected analyst action

A: request corrected export. B: investigate the client-ledger posting; the reported 17 Sep shortfall is not supported by transactions. C: request corrected acquirer report.

## 6. Correction and re-upload

None for this scenario (by design).

