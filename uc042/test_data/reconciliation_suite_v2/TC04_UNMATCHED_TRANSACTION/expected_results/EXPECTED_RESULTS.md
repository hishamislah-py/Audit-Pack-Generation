# TC04 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart**

Customer label: SYNTHETIC TEST Dunmore Payments Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

At 16:20 on Wed 30 Sep 2026 the EUR safeguarding account received an inbound transfer of 650.00 (E2E-EUR-0930-U01) from an unidentified payer. The firm did not post it to the cash book, did not record it in the unallocated register and created no client transaction. Its external reconciliation reported the difference but no investigation was logged.

## Evidence files involved

- IN-04 `unallocated_register_2026-09.csv` (mutated)
- IN-05 `internal_recon_records_2026-09.csv` (mutated)
- IN-06 `external_recon_records_2026-09.csv` (mutated)
- IN-07 `bank_balance_confirmations_2026-09.csv` (mutated)
- IN-08 `bank_statements_eod_2026-09.csv` (mutated)
- IN-09 `bank_statement_entries_2026-09.csv` (mutated)
- IN-10 `sga_cashbook_entries_2026-09.csv` (mutated)
- unchanged on purpose: IN-10 (no cash-book posting)
- unchanged on purpose: IN-04 (not registered)
- unchanged on purpose: IN-11 (no transaction)
- unchanged on purpose: IN-05 (internal recon omitted the receipt)
- unchanged on purpose: IN-14 (no investigation logged)

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **source_with_record:** IN-09 BE-EUR-0930-U01 (credit 650.00, 2026-09-30T16:20)
- **absent_counterparts:** ["IN-10 cash-book entry", "IN-04 register receipt", "IN-11 LOAD_BANK transaction"]
- **references_checked:** ["IN-10.payment_reference", "IN-11.payment_reference", "IN-04.bank_reference", "IN-12.expected_bank_reference", "TOPUP-EUR-20260930"]
- **financial_impact:** bank exceeds ledger by 650.00 at 30 Sep 17:00; recomputed requirement potentially understated by up to 650.00 if the receipt is relevant funds

**Key figures**

| metric | scope | value |
|---|---|
| bank_1700|2026-09-30/SGA-EUR-01 | 119205.00 |
| ledger_1700|2026-09-30/SGA-EUR-01 | 118555.00 |
| requirement_1700|2026-09-30/EUR | 118555.00 |
| resource_1700|2026-09-30/EUR | 118555.00 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `BANK_NO_COUNTERPART BE-EUR-0930-U01 ref=E2E-EUR-0930-U01`
- `BL_DIFF 2026-09-30 SGA-EUR-01 650.00`
- `BL_DIFF_NOT_LOGGED 2026-09-30 SGA-EUR-01`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC04`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| BANK-CASH-LINK | BE-EUR-0930-U01 | FAIL |
| C08-DIFFERENCE | 2026-09-30/SGA-EUR-01 | FAIL |
| C11-BANK-ENTRY | BE-EUR-0930-U01 | FAIL |
| DISC-LOG | SGA-EUR-01 from 2026-09-30 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC04-01 | Critical | `BANK_LEDGER_DIFFERENCE|SGA-EUR-01|2026-09-30|650.00` | 2 |
| EXC-TC04-02 | High | `UNMATCHED_BANK_ENTRY|BE-EUR-0930-U01` | 2 |

- Evidence statuses: {'EXC-TC04-01': 'NOT_EVIDENCED'}
- Investigation groups: [['EXC-TC04-01', 'EXC-TC04-02']]
- Candidate relationships (UNVERIFIED): none
- Must hold: C04, C05, C06 EUR 30 Sep PASS (the engine cannot see the requirement understatement, gap G-15)
- Must hold: EXC-TC04-01 flag NO_INVESTIGATION_LOGGED; related record BE-EUR-0930-U01

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `PENDING:UNMATCHED_TRANSACTION`; gaps G-14, G-15, G-19.

- Bank-side unmatched credit classified as a potential unidentified receipt
- Possible requirement understatement of 650.00 reported (G-15)

## 4. AI investigation expectations (separate from FIN)

- Finding: The credit has no counterpart in IN-10, IN-11, IN-04, IN-12 or the top-up reference
- Finding: It is a credit of client-payment form (end-to-end reference, INBOUND TRANSFER)
- Finding: It probably belongs in the unallocated register as UNIDENTIFIED (HYPOTHESIS)
- Evidence reference: IN-09 BE-EUR-0930-U01
- Evidence reference: IN-07 ST-SGA-EUR-01-20260930-1700
- Evidence reference: IN-06 ERL-SGA-EUR-01-20260930
- Evidence reference: IN-04 (no entry)
- Evidence reference: IN-10 (no entry)
- Missing evidence: payer details / remittance information
- Confidence: high that it is unrecorded; low on its owner
- Must not: allocate the receipt to any client

## 5. Expected analyst action

Require the firm to record the receipt (register and cash book), correct its reconciliations, and resubmit.

## 6. Correction and re-upload

- What was wrong: The 650.00 receipt was not recorded: no cash-book posting, no register entry, and the reconciliations omitted it.
- What changed: Receipt recorded as UNIDENTIFIED (IN-04 UR-0003) and posted (IN-10 LE-EUR-0930-0006); IN-05 and IN-06 for EUR 30 Sep updated.
- FIN after correction: validator findings expected = none
- ENGINE-PREDICTED after correction: **CLEAN**, 0 exceptions (not executed)
  - must hold: C04 includes UR-0003 (open at 17:00)
  - must hold: CASH-BANK-LINK LE-EUR-0930-0006 PASS
  - must hold: C11-BANK-ENTRY passes (register reference)
  - must hold: C09-ALLOCATION UR-0003 PASS: open at the period end; allocation due 2026-10-01, after the period
- Files: `corrections/replacement_files/` (only the replaced files), `corrections/corrected_case/` (complete corrected case), `upload/TC04_corrected_evidence_upload.zip`

