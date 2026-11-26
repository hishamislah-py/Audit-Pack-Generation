# TC05 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export**

Customer label: SYNTHETIC TEST Elmstead Card Services Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

The client transaction export (IN-11) omits the three EUR card spends of scheme batch SB-EUR-20260924 (total 847.45), consistent with the export being taken before the batch's clearing was processed. The scheme report, bank debit and client snapshots are complete.

## Evidence files involved

- IN-11 `transactions_2026-09.csv` (mutated)
- unchanged on purpose: IN-12 SB-EUR-20260924
- unchanged on purpose: IN-13 SL-SB-EUR-20260924-0001..0003
- unchanged on purpose: IN-09 BE-EUR-0924-SB1
- unchanged on purpose: IN-10 LE-EUR-0924-0004
- unchanged on purpose: IN-03 snapshots

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **missing_transactions:** [{"txn_id": "TX-0924-00018", "client_per_baseline": "C0104", "amount": "222.18"}, {"txn_id": "TX-0924-00019", "client_per_baseline": "C0101", "amount": "431.57"}, {"txn_id": "TX-0924-00020", "client_per_baseline": "C0101", "amount": "193.70"}]
- **total:** 847.45 (= batch gross = net = bank debit BE-EUR-0924-SB1)
- **client_effects:** {"C0101": "+625.27 (431.57 + 193.70)", "C0104": "+222.18"}
- **financial_impact:** none on bank, ledger or requirement

**Key figures**

| metric | scope | value |
|---|---|
| rollforward|EUR/C0101 2026-09-24 | 30615.68 |
| rollforward|EUR/C0102 2026-09-24 | 31235.11 |
| rollforward|EUR/C0104 2026-09-24 | 28055.28 |
| snapshot|EUR/C0101 2026-09-24 | 29990.41 |
| snapshot|EUR/C0102 2026-09-24 | 31235.11 |
| snapshot|EUR/C0104 2026-09-24 | 27833.10 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `LINE_TXN SL-SB-EUR-20260924-0001 TX-0924-00018 missing`
- `LINE_TXN SL-SB-EUR-20260924-0002 TX-0924-00019 missing`
- `LINE_TXN SL-SB-EUR-20260924-0003 TX-0924-00020 missing`
- `ROLLFWD EUR/C0101 2026-09-24 625.27`
- `ROLLFWD EUR/C0104 2026-09-24 222.18`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC05`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| C11-BATCH-ARITH | SB-EUR-20260924 | FAIL |
| CBAL-ROLLFWD | EUR/C0101 2026-09-24 | FAIL |
| CBAL-ROLLFWD | EUR/C0104 2026-09-24 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC05-01 | High | `C11-BATCH-ARITH|SB-EUR-20260924` | 1 |
| EXC-TC05-02 | High | `CBAL-ROLLFWD|EUR/C0101 2026-09-24` | 1 |
| EXC-TC05-03 | High | `CBAL-ROLLFWD|EUR/C0104 2026-09-24` | 1 |

- Evidence statuses: none
- Investigation groups: none
- Candidate relationships (UNVERIFIED): [['EXC-TC05-01', 'EXC-TC05-03']]
- Must hold: No investigation group
- Must hold: One UNVERIFIED candidate (line TX-0924-00018 = 222.18 = C0104 roll-forward gap)
- Must hold: No candidate for C0101: its gap is the SUM of two lines (gap G-16)
- Must hold: C11-TXN-LINE PASS summary (missing transactions are not iterated)

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `PENDING:SUSPECTED_COMMON_CAUSE (UNVERIFIED)`; gaps G-16, G-17, G-19.

- The three exceptions presented together as one suspected common cause: missing transactions of batch SB-EUR-20260924
- Basis: batch scope plus per-client line-sum match; still UNVERIFIED; no cause set deterministically

## 4. AI investigation expectations (separate from FIN)

- Level: **group** (one conclusion across the exceptions); currently investigation runs per exception (gap G-17).
- Finding: Batch lines reference 3 transaction IDs absent from the export
- Finding: C0101 roll-forward exceeds its snapshot by 625.27; C0104 by 222.18
- Finding: Possible common cause: the export is incomplete for SB-EUR-20260924
- Connecting evidence: all 3 missing IDs belong to one batch
- Connecting evidence: 222.18 equals one line exactly
- Connecting evidence: 625.27 equals the sum of the other two lines
- Connecting evidence: no other batch or day affected
- Connecting evidence: header, lines and bank debit agree with each other
- Evidence reference: IN-12 SB-EUR-20260924
- Evidence reference: IN-13 SL-SB-EUR-20260924-0001..0003
- Evidence reference: IN-09 BE-EUR-0924-SB1
- Evidence reference: IN-03 CBS-20260923/24-C0101-EUR
- Evidence reference: IN-03 CBS-20260923/24-C0104-EUR
- Missing evidence: client of each missing transaction (settlement lines carry no client_id)
- Missing evidence: export job log or a complete export
- Confidence: medium-high that the export is incomplete; low-medium for client attribution (amount-based only)
- Must not: state the client attribution as confirmed
- Must not: cite the UNVERIFIED candidate as evidence

## 5. Expected analyst action

Request a complete transaction export.

## 6. Correction and re-upload

- What was wrong: The transaction export omitted the three spends of SB-EUR-20260924.
- What changed: TX-0924-00018, -00019, -00020 restored; the file is byte-identical to the clean baseline IN-11.
- FIN after correction: validator findings expected = none
- ENGINE-PREDICTED after correction: **CLEAN**, 0 exceptions (not executed)
- Files: `corrections/replacement_files/` (only the replaced files), `corrections/corrected_case/` (complete corrected case), `upload/TC05_corrected_evidence_upload.zip`

