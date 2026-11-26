# TC01 - Expected results

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80)**

Customer label: SYNTHETIC TEST Ashcombe Pay Ltd. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.

## Business situation

The firm's cash-book interface re-ran at 09:25 on Mon 28 Sep 2026 and re-posted the 09:10 inbound transfer E2E-GBP-0928-L01 (client C0008, GBP 1,246.80) as a new ledger row. The cash-book extract supplied for audit holds both rows. The firm's reconciliation records (IN-05, IN-06) were prepared from the correct ledger.

## Evidence files involved

- IN-10 `sga_cashbook_entries_2026-09.csv` (mutated)
- unchanged on purpose: IN-09 (one bank credit BE-GBP-0928-L01)
- unchanged on purpose: IN-11 (one LOAD_BANK TX-0928-00001)
- unchanged on purpose: IN-03 snapshots
- unchanged on purpose: IN-05 and IN-06 reported values
- unchanged on purpose: IN-14 (header only)

## 1. Deterministic financial expectations (FIN)

Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).

- **duplicate:** {"original": "IN-10 LE-GBP-0928-0001", "duplicate": "IN-10 LE-GBP-0928-0007", "matching_attributes": ["account_id", "payment_reference", "amount", "entry_type", "dc_indicator", "currency"], "classification": "EXACT DUPLICATE OF ONE BUSINESS EVENT (distinct ledger key)", "not_legitimate_because": ["end-to-end reference is unique per payment", "one bank credit BE-GBP-0928-L01", "one LOAD_BANK TX-0928-00001", "C0008 snapshot rises by 1,246.80 once"]}
- **financial_impact:** cash-book extract overstates item A by 1,246.80 from 28 Sep to period end; real safeguarding position unaffected
- **legitimate_repeat_controls_unchanged:** ["TX-0908-00003..TX-0908-00006 (4 x 2,500.00 LOAD_CARD, 4 clients)", "TX-0909-0R001 = TX-0902-00044 (60.00)", "TX-0916-0R001 = TX-0903-00016 (284.02)"]

**Key figures**

| metric | scope | value |
|---|---|
| bank_1700|2026-09-28/SGA-GBP-01 | 378706.65 |
| bank_1700|2026-09-29/SGA-GBP-01 | 388744.47 |
| bank_1700|2026-09-30/SGA-GBP-01 | 395844.86 |
| ledger_1700|2026-09-28/SGA-GBP-01 | 379953.45 |
| ledger_1700|2026-09-29/SGA-GBP-01 | 389991.27 |
| ledger_1700|2026-09-30/SGA-GBP-01 | 397091.66 |
| requirement_1700|2026-09-28/GBP | 378706.65 |
| requirement_1700|2026-09-29/GBP | 388744.47 |
| requirement_1700|2026-09-30/GBP | 395844.86 |
| resource_1700|2026-09-28/GBP | 379953.45 |
| resource_1700|2026-09-29/GBP | 389991.27 |
| resource_1700|2026-09-30/GBP | 397091.66 |

**Complete expected finding set of the independent validator** (anything else is a generation error)

- `BANK_MULTI_CLAIM BE-GBP-0928-L01 IN-10=LE-GBP-0928-0001,LE-GBP-0928-0007`
- `BL_DIFF 2026-09-28 SGA-GBP-01 -1246.80`
- `BL_DIFF 2026-09-29 SGA-GBP-01 -1246.80`
- `BL_DIFF 2026-09-30 SGA-GBP-01 -1246.80`
- `BL_DIFF_NOT_LOGGED 2026-09-28 SGA-GBP-01`
- `BL_DIFF_NOT_LOGGED 2026-09-29 SGA-GBP-01`
- `BL_DIFF_NOT_LOGGED 2026-09-30 SGA-GBP-01`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 item_a reported=378706.65 recomputed=379953.45`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 resource_reported reported=378706.65 recomputed=379953.45`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 item_a reported=388744.47 recomputed=389991.27`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 resource_reported reported=388744.47 recomputed=389991.27`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 item_a reported=395844.86 recomputed=397091.66`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 resource_reported reported=395844.86 recomputed=397091.66`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260928 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260928 ledger_balance_reported reported=378706.65 recomputed=379953.45`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260929 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260929 ledger_balance_reported reported=388744.47 recomputed=389991.27`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260930 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260930 ledger_balance_reported reported=395844.86 recomputed=397091.66`
- `RR_DIFF 2026-09-28 GBP 1246.80`
- `RR_DIFF 2026-09-29 GBP 1246.80`
- `RR_DIFF 2026-09-30 GBP 1246.80`

## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)

Expected case status: **EXCEPTIONS_OPEN**. Exception IDs assume `scenario.json` scenario_id `TC01`; Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.

| check_id | scope | outcome |
|---|---|---|
| C05-RESOURCE | 2026-09-28/GBP | FAIL |
| C05-RESOURCE | 2026-09-29/GBP | FAIL |
| C05-RESOURCE | 2026-09-30/GBP | FAIL |
| C06-DIFFERENCE | 2026-09-28/GBP | FAIL |
| C06-DIFFERENCE | 2026-09-29/GBP | FAIL |
| C06-DIFFERENCE | 2026-09-30/GBP | FAIL |
| C08-DIFFERENCE | 2026-09-28/SGA-GBP-01 | FAIL |
| C08-DIFFERENCE | 2026-09-29/SGA-GBP-01 | FAIL |
| C08-DIFFERENCE | 2026-09-30/SGA-GBP-01 | FAIL |
| DISC-LOG | SGA-GBP-01 from 2026-09-28 | FAIL |
| RC2-LEDGER | 2026-09-28/SGA-GBP-01 | FAIL |
| RC2-LEDGER | 2026-09-29/SGA-GBP-01 | FAIL |
| RC2-LEDGER | 2026-09-30/SGA-GBP-01 | FAIL |

| exception_id (predicted) | severity | root_cause | affected_results |
|---|---|---|---|
| EXC-TC01-01 | Critical | `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-28|-1246.80` | 4 |
| EXC-TC01-02 | Critical | `INTERNAL_DIFFERENCE|2026-09-28/GBP` | 1 |
| EXC-TC01-03 | Critical | `INTERNAL_DIFFERENCE|2026-09-29/GBP` | 1 |
| EXC-TC01-04 | Critical | `INTERNAL_DIFFERENCE|2026-09-30/GBP` | 1 |
| EXC-TC01-05 | High | `C05-RESOURCE|2026-09-28/GBP` | 1 |
| EXC-TC01-06 | High | `RC2-LEDGER|2026-09-28/SGA-GBP-01` | 1 |
| EXC-TC01-07 | High | `C05-RESOURCE|2026-09-29/GBP` | 1 |
| EXC-TC01-08 | High | `RC2-LEDGER|2026-09-29/SGA-GBP-01` | 1 |
| EXC-TC01-09 | High | `C05-RESOURCE|2026-09-30/GBP` | 1 |
| EXC-TC01-10 | High | `RC2-LEDGER|2026-09-30/SGA-GBP-01` | 1 |

- Evidence statuses: {'EXC-TC01-01': 'NOT_EVIDENCED'}
- Investigation groups: [['EXC-TC01-02', 'EXC-TC01-03', 'EXC-TC01-04']]
- Candidate relationships (UNVERIFIED): none
- Must hold: CASH-BANK-LINK PASS for both LE-GBP-0928-0001 and LE-GBP-0928-0007 (no one-to-one matching, gap G-04)
- Must hold: RC4-DIRECT TX-0928-00001 PASS
- Must hold: C04-REQUIREMENT PASS 28-30 Sep GBP
- Must hold: CBAL-ROLLFWD PASS for C0008
- Must hold: EXC-TC01-01 flags OWN_FUNDS_REQUIRED and NO_INVESTIGATION_LOGGED

## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)

Root: `PENDING:DUPLICATE_TRANSACTION`; gaps G-04, G-05, G-19.

- One root cause: LE-GBP-0928-0007 duplicates LE-GBP-0928-0001 (account, payment_reference, amount, entry_type) against one bank counterpart BE-GBP-0928-L01
- All ledger-derived failures 28-30 Sep (C08, C06, C05, RC2, DISC-LOG) linked to that root as consequences
- Financial impact +1,246.80 ledger overstatement; classification EXACT DUPLICATE
- Legitimate-repeat controls (4 x 2,500.00 card loads; refunds equal to originals) NOT flagged

## 4. AI investigation expectations (separate from FIN)

- Finding: Two IN-10 rows share E2E-GBP-0928-L01 while IN-09 and IN-11 hold one each: a duplicate posting, not two receipts
- Finding: The -1,246.80 bank-ledger and +1,246.80 internal differences from 28 Sep equal the duplicate exactly
- Finding: The firm's reported figures exclude the duplicate: the defect is in the supplied extract, not the firm's reconciliation
- Evidence reference: IN-10 LE-GBP-0928-0001
- Evidence reference: IN-10 LE-GBP-0928-0007
- Evidence reference: IN-09 BE-GBP-0928-L01
- Evidence reference: IN-11 TX-0928-00001
- Evidence reference: IN-05 IRR-EMONEY-GBP-20260928..30
- Evidence reference: IN-06 ERL-SGA-GBP-01-20260928..30
- Missing evidence: interface run log / posting audit trail
- Confidence: high for the duplicate; medium for extract defect versus ledger defect
- Must not: treat the two rows as two genuine receipts
- Must not: recommend an own-funds top-up (real position unaffected)

## 5. Expected analyst action

Reject the submitted cash-book extract and request a corrected extract; no own-funds top-up required.

## 6. Correction and re-upload

- What was wrong: The cash-book extract contained a duplicate posting (LE-GBP-0928-0007) created by an interface re-run.
- What changed: LE-GBP-0928-0007 removed from sga_cashbook_entries_2026-09.csv; the file is byte-identical to the clean baseline IN-10.
- FIN after correction: validator findings expected = none
- ENGINE-PREDICTED after correction: **CLEAN**, 0 exceptions (not executed)
- Files: `corrections/replacement_files/` (only the replaced files), `corrections/corrected_case/` (complete corrected case), `upload/TC01_corrected_evidence_upload.zip`

