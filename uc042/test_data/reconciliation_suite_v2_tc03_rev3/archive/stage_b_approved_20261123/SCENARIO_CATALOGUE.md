# UC-042 Reconciliation Test Suite V2: Scenario Catalogue (Stage B specifications)

**Status:** SPECIFIED. These scenarios are awaiting the Stage C review. **No scenario dataset has been generated and nothing has been executed.**

## Common basis

| Item | Value |
|---|---|
| Baseline | `shared_baseline/`, a byte-verified copy of `set_01_clean_baseline` (19/19 SHA-256 match). Every scenario is that baseline plus the mutations listed below and nothing else. |
| Period | PER-2026-09 (1–30 Sep 2026); 22 reconciliation days; reconciliation point 17:00 Europe/London |
| Evidence entity | SYN-EMI-001 / "Synthetic EMI Ltd", accounts at the fictional "Example Bank plc" (inherited from the baseline) |
| Customer label | Each scenario has a distinct fictional case label starting `SYNTHETIC TEST`. Distinct labels avoid case collisions if the scenarios are loaded into Ringfence. |
| Mutation format | The R1 `scenarios.py` operation vocabulary: `delete_record`, `set_field` (with the expected old value), `add_record`. Each op carries a `why`. |
| Reference engine | `C:\u42v\e2e_20261122\engine_base\uc042\uc042lib` (17 Nov 2026 rules) |

### How expectations are labelled

| Label | Meaning |
|---|---|
| **FIN** | A deterministic financial expectation, calculated independently from the synthetic data. Engine-independent. |
| **ENGINE-PREDICTED** | What the current engine is expected to output, from reading its source only. Not executed. Exception IDs assume `scenario.json` `scenario_id` = TCnn. |
| **FUTURE (PROPOSED)** | The desired behaviour of the enriched engine. Category names are `PENDING:<label>`. They are not control or exception IDs. |
| **AI** | Expectations for the AI investigation, kept separate from FIN |

## Summary

| ID | Behaviour | Customer label | Mutated files | Correction | ENGINE-PREDICTED status / exceptions / groups |
|---|---|---|---|---|---|
| TC01 | Duplicate transaction (cash-book double posting) | SYNTHETIC TEST Ashcombe Pay Ltd | IN-10 | **Yes**: corrected IN-10 | EXCEPTIONS_OPEN / 10 / 1 |
| TC02 | Amount mismatch (transaction export vs bank) | SYNTHETIC TEST Brindle Wallet Ltd | IN-11 | No | EXCEPTIONS_OPEN / 2 / 0 |
| TC03 | Timing difference across the period end | SYNTHETIC TEST Cresswell Money Ltd | IN-06, IN-07, IN-08, IN-09, IN-14 | Supplementary only (not ingestible) | EXCEPTIONS_OPEN / 3 / 1 |
| TC04 | Unmatched transaction (unrecorded bank credit) | SYNTHETIC TEST Dunmore Payments Ltd | IN-06, IN-07, IN-08, IN-09 | **Yes**: IN-04, IN-05, IN-06, IN-10 | Initial EXCEPTIONS_OPEN / 2 / 1; corrected CLEAN |
| TC05 | Several discrepancies, one possible cause (batch omitted from export) | SYNTHETIC TEST Elmstead Card Services Ltd | IN-11 | **Yes**: corrected IN-11 | Initial EXCEPTIONS_OPEN / 3 / 0 (+1 candidate); corrected CLEAN |
| TC06 | Independent discrepancies (with a same-day, same-amount decoy) | SYNTHETIC TEST Farrowdale E-Money Ltd | IN-03, IN-05, IN-11, IN-13 | No | EXCEPTIONS_OPEN / 6 / 1 (predicted over-grouping) |

---

## TC01: Duplicate transaction

**Business situation.** The firm's cash-book interface was re-run at 09:25 on Mon 28 Sep 2026. It re-posted the 09:10 inbound bank transfer `E2E-GBP-0928-L01` (client C0008, £1,246.80) as a new ledger row. The cash-book extract supplied for the audit contains both rows. The firm's own reconciliation records (IN-05, IN-06) were prepared from the correct ledger and do not contain the duplicate. The defect is in the extract supplied as evidence.

**Evidence compared:**

| File | Record | Content |
|---|---|---|
| IN-10 cash book | `LE-GBP-0928-0001` (original), `LE-GBP-0928-0007` (duplicate) | |
| IN-09 bank | `BE-GBP-0928-L01` | The only bank entry carrying `E2E-GBP-0928-L01` |
| IN-11 transactions | `TX-0928-00001` | The only LOAD_BANK carrying that reference |
| IN-03 snapshots | C0008 | Rises by £1,246.80 once |
| IN-05, IN-06 | | Reported 28–30 Sep values |

**Mutation (1 op):**

| Op | File | Record | Change | Why |
|---|---|---|---|---|
| add_record, inserted after `LE-GBP-0928-0001` | IN-10 | `LE-GBP-0928-0007` | `SGA-GBP-01, 2026-09-28T09:25:00+01:00, BANK_LOAD, 1246.80, D, GBP, E2E-GBP-0928-L01` | Interface re-run re-posted the 09:10 receipt |

**Unchanged on purpose:** IN-09, IN-11, IN-03, IN-05, IN-06 and IN-14 (header only).

### Duplicate classification

**Exact duplicate of one business event, with a distinct ledger key.** Same account, amount, type and end-to-end reference.

Evidence that the two rows are **not** a legitimate repeated payment:

- The end-to-end reference is unique per payment.
- The bank shows one credit.
- The client ledger shows one LOAD_BANK.
- C0008's snapshot rises by £1,246.80 only once.

**Legitimate-repeat controls (baseline, unchanged).** These must **not** be flagged as duplicates:

- Four LOAD_CARD of £2,500.00 on 8 Sep (`TX-0908-00003`…`-00006`) for four different clients, each on its own line of AQ-GBP-20260908.
- Refunds equal to their originals: `TX-0909-0R001` (60.00) and `TX-0916-0R001` (284.02).

### FIN

| Day | Ledger at 17:00 (recomputed, with duplicate) | Bank 17:00 (IN-07) | Bank − ledger | Requirement (IN-03) | Resource − requirement |
|---|---|---|---|---|---|
| 28 Sep | 379,953.45 | 378,706.65 | **−1,246.80** | 378,706.65 | **+1,246.80** |
| 29 Sep | 389,991.27 | 388,744.47 | **−1,246.80** | 388,744.47 | **+1,246.80** |
| 30 Sep | 397,091.66 | 395,844.86 | **−1,246.80** | 395,844.86 | **+1,246.80** |

The reported figures (IN-05 item_a and resource, IN-06 ledger) are unchanged and equal the bank figures.

- Overstatement of the extract's ledger: £1,246.80 from 28 Sep to the period end.
- Real safeguarding position: unaffected (bank = client requirement).

### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (13) | C08-DIFFERENCE ×3 (28/29/30 Sep SGA-GBP-01), DISC-LOG ×1, C06-DIFFERENCE ×3, C05-RESOURCE ×3, RC2-LEDGER ×3 |
| Exceptions (10) | EXC-TC01-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-28\|-1246.80` (4 results; flags OWN_FUNDS_REQUIRED, NO_INVESTIGATION_LOGGED; evidence status NOT_EVIDENCED) |
| | EXC-TC01-02/03/04 Critical `INTERNAL_DIFFERENCE\|2026-09-2{8,9}/GBP` and `…\|2026-09-30/GBP` |
| | EXC-TC01-05/07/09 High `C05-RESOURCE\|<day>/GBP` |
| | EXC-TC01-06/08/10 High `RC2-LEDGER\|<day>/SGA-GBP-01` |
| Groups | 1: GRP-TC01-01 = the 3 INTERNAL_DIFFERENCE exceptions (L2 PERSISTENCE). No candidates. |
| Must hold | CASH-BANK-LINK **PASS** for both `LE-GBP-0928-0001` and `LE-GBP-0928-0007` (gap G-04). RC4-DIRECT `TX-0928-00001` PASS. C04 PASS. CBAL-ROLLFWD PASS. |

### FUTURE (PROPOSED)

- One root `PENDING:DUPLICATE_TRANSACTION`: `LE-GBP-0928-0007` duplicates `LE-GBP-0928-0001`, matched on account + payment_reference + amount + entry_type, with one bank counterpart.
- All ledger-derived failures for 28–30 Sep are linked to it as consequences (G-05).
- Financial impact: +1,246.80 ledger overstatement.
- The legitimate-repeat controls are not flagged.

### AI

The investigation should find all of the following:

- (a) Two IN-10 rows share `E2E-GBP-0928-L01`, while IN-09 and IN-11 each have one, so this is a duplicate posting, not two receipts.
- (b) The −1,246.80 bank-ledger difference and the +1,246.80 internal differences from 28 Sep onward equal the duplicate exactly.
- (c) The firm's reported figures do not include the duplicate, which points to the evidence extract rather than the firm's reconciliation.

**Missing evidence:** the interface run log.

**Confidence:** high for the duplicate; medium for "extract defect versus ledger defect".

**Cited evidence:** IN-10 L(original, duplicate), IN-09 `BE-GBP-0928-L01`, IN-11 `TX-0928-00001`, IN-05 and IN-06 for 28–30 Sep.

**Expected analyst action:** reject the submitted cash-book extract and request a corrected one. No own-funds top-up is needed: the real position is unaffected.

### Correction

| Item | Detail |
|---|---|
| Correction file | `corrections/source_data/sga_cashbook_entries_2026-09.csv` with `LE-GBP-0928-0007` removed. It is byte-identical to the baseline IN-10. |
| What was wrong | Duplicate interface posting |
| What changed | One row removed |
| Expected after correction | **CLEAN**, identical to the baseline frozen key (0 exceptions) |

---

## TC02: Amount mismatch

**Business situation.** Client C0006's bank-transfer load on Tue 8 Sep 2026 (end-to-end reference `E2E-GBP-0908-L02`) was received by the bank, posted to the cash book and reflected in the client ledger snapshot at £3,035.61. The client transaction export (IN-11) shows £3,053.61, a two-digit transposition in the export.

**Evidence compared:**

| File | Record | Amount |
|---|---|---|
| IN-11 | `TX-0908-00002` | 3,053.61 |
| IN-09 | `BE-GBP-0908-L02` | 3,035.61 (C) |
| IN-10 | `LE-GBP-0908-0002` | 3,035.61 (D) |
| IN-03 | C0006 snapshots 7 and 8 Sep | |

**Mutation (1 op):**

| Op | File | Record | Field | Old → new | Why |
|---|---|---|---|---|---|
| set_field | IN-11 | `TX-0908-00002` | amount | 3035.61 → 3053.61 | Transposition in the platform export |

### FIN

- Transaction − bank = **+18.00**: the export overstates the receipt. The difference is a multiple of 9, the usual transposition signature.
- C0006 roll-forward for 8 Sep: 36,356.73 + 2,769.64 = 39,126.37, against a snapshot of 39,108.37, so roll-forward − snapshot = **+18.00**.
- The 9 Sep pair reconciles (0.00).
- Majority evidence:

| Value | Sources |
|---|---|
| 3,035.61 | IN-09, IN-10, IN-03 |
| 3,053.61 | IN-11 only |

- No balance impact on the bank, the ledger or the requirement.

### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (2) | RC4-DIRECT `TX-0908-00002` FAIL (computed 3053.61, reported 3035.61); CBAL-ROLLFWD `GBP/C0006 2026-09-08` FAIL (computed 39126.37, reported 39108.37) |
| Exceptions (2, High) | EXC-TC02-01 `CBAL-ROLLFWD\|GBP/C0006 2026-09-08`; EXC-TC02-02 `RC4-DIRECT\|TX-0908-00002` |
| Groups | 0 (gap G-08) |
| Must hold | CASH-BANK-LINK `LE-GBP-0908-0002` PASS; C08 and C06 for 8 Sep PASS; CBAL 9 Sep PASS |

### FUTURE (PROPOSED)

- One root `PENDING:AMOUNT_MISMATCH` on reference `E2E-GBP-0908-L02`: IN-11 3,053.61 vs IN-09 3,035.61, difference +18.00 (transaction > bank).
- The CBAL failure is linked by `txn_id` lineage.
- The outlier source is IN-11 (G-07, G-08, G-09).

### AI

The investigation should:

- Identify both exceptions as one mismatch on `TX-0908-00002`.
- State the direction.
- Name IN-11 as the outlier, corroborated by three sources.
- Note that the difference is divisible by 9, as a possible transposition. That is a **hypothesis**, not evidence.

**Missing evidence:** the platform's audit trail for the export.

**Must not:** recommend changing the bank or the cash book.

**Expected analyst action:** accept the finding and request a corrected transaction export. The client balance is correct, so no client-money shortfall arises.

**Correction:** none. This scenario stays as an investigation demonstration.

---

## TC03: Timing difference across the period end

**Business situation.** The six GBP card spends cleared in scheme batch `SB-GBP-20260930`:

| Stage | Value |
|---|---|
| Transactions | `TX-0930-00007`…`-00012`, clients C0008 ×2, C0005, C0002, C0003, C0007 |
| Authorised | 07:15–12:15 on 30 Sep |
| Clearing date | 30 Sep |
| Batch cycle and settlement date | 30 Sep |
| Client ledger debit | 15:00 on 30 Sep (convention D8) |
| Batch total | £2,720.15 |

The firm posted the scheme settlement to the cash book at 15:00 (`LE-GBP-0930-0005`). The bank did not debit the safeguarding account until **Thu 1 Oct 2026 08:00** (value date 1 Oct). At the 30 Sep 17:00 point the bank balance is therefore £2,720.15 above the ledger.

The firm's external reconciliation reports the difference and claims timing. Its log records it as OPEN at the period end.

**Mutations (8 ops, in 6 rows below):**

| # | Op | File | Record | Change |
|---|---|---|---|---|
| 1 | delete_record | IN-09 | `BE-GBP-0930-SB1` | Debit 2,720.15, reference SB-GBP-20260930. Not booked by the bank on 30 Sep. |
| 2 | set_field | IN-08 | `ST-SGA-GBP-01-20260930-EOD` | closing_balance_amount 395844.86 → 398565.01 |
| 3 | set_field | IN-08 | same | entry_count 6 → 5 |
| 4 | set_field | IN-07 | `ST-SGA-GBP-01-20260930-1700` | balance_amount 395844.86 → 398565.01 |
| 5 | set_field ×3 | IN-06 | `ERL-SGA-GBP-01-20260930` | bank_balance_reported 395844.86 → 398565.01; difference_reported 0.00 → 2720.15; timing_difference_claimed false → true |
| 6 | add_record | IN-14 | `DL-0001` | `2026-09-30T18:05:00+01:00, ERL-SGA-GBP-01-20260930, SGA-GBP-01, GBP, 2720.15, "Scheme settlement SB-GBP-20260930 not debited by the bank by 17:00; expected next business day", cause_category TIMING, cause_evidence_ref "", funding_reference "", OPEN, resolved_ts "", approver_id ""` |

`cause_category = TIMING` follows the SC2 precedent. The schema has no allowed-value list for that field.

**Unchanged on purpose:** IN-10, IN-11, IN-12, IN-13, IN-03 and IN-05. The internal reconciliation is unaffected.

**Supplementary evidence (reference only, NOT ingestible).** A one-row October extract in the existing IN-09 column layout, `supplementary_evidence/bank_statement_entries_2026-10.csv`:

`BE-GBP-1001-T01, ST-SGA-GBP-01-20261001-EOD, SGA-GBP-01, 2026-10-01, 2026-10-01T08:00:00+01:00, 2026-10-01, 2720.15, D, GBP, SB-GBP-20260930, "", Synthetic Card Scheme, SCHEME SETTLEMENT SB-GBP-20260930`

The current engine cannot use it in a September case. If it were placed in `source_data/`, the engine would return V00-FILE FAIL ("file for another reporting period") (G-11).

### FIN

| Stage | Date |
|---|---|
| Transaction | 30 Sep (auth 07:15–12:15) |
| Processing (client ledger and cash book) | 30 Sep 15:00 |
| Batch settlement date | 30 Sep |
| Bank booking | 1 Oct 08:00 (next business day, D+1) |

- At 30 Sep 17:00: bank 398,565.01 vs ledger 395,844.86, so bank − ledger = **+2,720.15**, as reported.
- Requirement = resource = 395,844.86 (no internal difference).
- Expected treatment: an **explainable timing item**. It cleared within one business day, but the clearing falls outside the reporting period. It stays visible at the period end as a reconciling item.

### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (3) | C08-DIFFERENCE `2026-09-30/SGA-GBP-01` FAIL (computed = reported = 2720.15; evidence_status **TIMING_UNVERIFIABLE**); CASH-BANK-LINK `LE-GBP-0930-0005` FAIL ("no bank entry carries this reference"); C11-BATCH-BANK `SB-GBP-20260930` FAIL ("no bank entry carries the batch reference") |
| Exceptions (3) | EXC-TC03-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-30\|2720.15`. No OWN_FUNDS flag; DISC-LOG PASS, so no NO_INVESTIGATION flag. |
| | EXC-TC03-02 High `C11-BATCH-BANK\|SB-GBP-20260930` |
| | EXC-TC03-03 High `UNMATCHED_CASHBOOK_ENTRY\|LE-GBP-0930-0005` |
| Groups | GRP-TC03-01 = {02, 03} (L1 REFERENCE SB-GBP-20260930). EXC-01 is **not** grouped (G-12). |
| Must hold | DISC-LOG PASS; DQ23 and BC-VS-EOD PASS for 30 Sep; C04, C05, C06 PASS |

### FUTURE (PROPOSED)

- With post-period clearing evidence accepted through an owner-approved channel, the item is `PENDING:TIMING_ITEM` / evidence status TIMING_EVIDENCED.
- All three exceptions are linked to one timing item.
- The status stays OPEN, awaiting human confirmation. **It is never auto-resolved.**

### AI

The investigation should find:

- (a) The difference equals the SB-GBP-20260930 batch net exactly.
- (b) The cash book and the client ledger recorded it on 30 Sep, but no September bank debit exists.
- (c) The firm claimed timing and logged it.
- (d) The cause is **probably timing**, but confirmation requires the October statement, which is **missing evidence** in the September pack.

**Confidence:** medium. The AI must not treat the log's TIMING label or the timing claim as proof.

**Expected analyst action:** treat as a period-end reconciling item. Request the 1 Oct statement and keep it open until the clearing is evidenced. No own-funds top-up is needed (the bank holds more than the ledger).

---

## TC04: Unmatched transaction

**Business situation.** At 16:20 on Wed 30 Sep 2026 the EUR safeguarding account received an inbound transfer of €650.00:

| Field | Value |
|---|---|
| Bank reference / end-to-end reference | `E2E-EUR-0930-U01` |
| Payer | Unidentified |
| Cash book | Not posted |
| Unallocated register | Not recorded |
| Client transaction | None |

The firm's external reconciliation reported the €650.00 bank-over-ledger difference but logged no investigation. Its internal reconciliation omitted the receipt.

**Mutations, initial submission (6 ops):**

| # | Op | File | Record | Change |
|---|---|---|---|---|
| 1 | add_record, after `BE-EUR-0930-R01` | IN-09 | `BE-EUR-0930-U01` | `ST-SGA-EUR-01-20260930-EOD, SGA-EUR-01, 2026-09-30, 2026-09-30T16:20:00+01:00, 2026-09-30, 650.00, C, EUR, E2E-EUR-0930-U01, E2E-EUR-0930-U01, Synthetic payer (unidentified), INBOUND TRANSFER` |
| 2–3 | set_field | IN-08 | `ST-SGA-EUR-01-20260930-EOD` | closing 118555.00 → 119205.00; entry_count 5 → 6 |
| 4 | set_field | IN-07 | `ST-SGA-EUR-01-20260930-1700` | balance 118555.00 → 119205.00 |
| 5–6 | set_field | IN-06 | `ERL-SGA-EUR-01-20260930` | bank_balance_reported 118555.00 → 119205.00; difference_reported 0.00 → 650.00 (timing claim stays false) |

**Matching references checked** (the engine's C11-BANK-ENTRY / BANK-CASH-LINK set) for `E2E-EUR-0930-U01`, all absent:

- IN-10.payment_reference
- IN-11.payment_reference
- IN-04.bank_reference
- IN-12.expected_bank_reference
- the `TOPUP-EUR-20260930` reference

### FIN

- 30 Sep 17:00: bank 119,205.00 vs ledger 118,555.00, so bank − ledger = **+650.00**.
- The recomputed requirement (118,555.00) is **potentially understated by up to €650.00**: if the receipt is relevant funds, it belongs in the register at receipt.
- The net safeguarding position is unaffected if it is recorded on both sides.

### ENGINE-PREDICTED (initial)

This mirrors the executed S05 pattern.

| Item | Prediction |
|---|---|
| Non-passing results (4) | C08-DIFFERENCE `2026-09-30/SGA-EUR-01` FAIL (NOT_EVIDENCED); DISC-LOG `SGA-EUR-01 from 2026-09-30` FAIL; BANK-CASH-LINK `BE-EUR-0930-U01` FAIL; C11-BANK-ENTRY `BE-EUR-0930-U01` FAIL |
| Exceptions (2) | EXC-TC04-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-EUR-01\|2026-09-30\|650.00` (flag NO_INVESTIGATION_LOGGED; related record BE-EUR-0930-U01) |
| | EXC-TC04-02 High `UNMATCHED_BANK_ENTRY\|BE-EUR-0930-U01` (2 results) |
| Groups | GRP-TC04-01 = {01, 02} (L3 LINEAGE: entry booked 16:20, inside the 17:00 balance) |
| Must hold | C04, C05, C06 EUR 30 Sep PASS. The engine cannot see the requirement understatement (G-15). |

### FUTURE (PROPOSED)

- `PENDING:UNMATCHED_TRANSACTION` (bank-side, credit).
- Classified as a potential unidentified receipt, with a possible requirement understatement of €650.00 (G-15).

### AI

The investigation should find:

- The credit has no counterpart in any of the five reference sources.
- It is a **credit** of client-type form (end-to-end reference pattern, "INBOUND TRANSFER").
- It probably belongs in the unallocated register as UNIDENTIFIED. That is a hypothesis.

**Missing evidence:** payer details and remittance information.

**Must not:** allocate the receipt to any client.

**Expected analyst action:** require the firm to record the receipt (register and cash book) and correct its reconciliations, then resubmit.

### Correction

The firm completes its records. There are 4 corrected files in `corrections/source_data/`:

| File | Change |
|---|---|
| IN-04 | Add `UR-0003`: `E2E-EUR-0930-U01, 2026-09-30, 2026-09-30T16:20:00+01:00, 650.00, EUR, UNIDENTIFIED`, identified/allocated fields blank |
| IN-10 | Add `LE-EUR-0930-0006`: `SGA-EUR-01, 2026-09-30T16:20:00+01:00, UNALLOCATED_RECEIPT, 650.00, D, EUR, E2E-EUR-0930-U01` |
| IN-05 | `IRR-EMONEY-EUR-20260930`: requirement_reported, resource_reported and item_a 118555.00 → 119205.00; difference stays 0.00 |
| IN-06 | `ERL-SGA-EUR-01-20260930`: ledger_balance_reported 118555.00 → 119205.00; difference_reported 650.00 → 0.00 |

**What was wrong:** the receipt was not recorded. **What changed:** it is now recorded as unidentified, with the reconciliations updated.

**Expected after correction (ENGINE-PREDICTED): CLEAN.**

- C04 includes UR-0003 (open at 17:00).
- CASH-BANK-LINK `LE-EUR-0930-0006` PASS.
- C11-BANK-ENTRY passes (register reference).
- C09-ALLOCATION `UR-0003` PASS: still open at the period end, with the allocation due 1 Oct, after the period.

---

## TC05: Several discrepancies with one possible cause

**Business situation.** The client transaction export (IN-11) omits all three EUR card spends of scheme batch `SB-EUR-20260924`. That is consistent with the export having been taken before that batch's clearing was processed. The scheme's own settlement report (IN-12, IN-13), the bank debit and the client ledger snapshots are complete.

| Missing transaction | Client | Amount |
|---|---|---|
| `TX-0924-00018` | C0104 | 222.18 |
| `TX-0924-00019` | C0101 | 431.57 |
| `TX-0924-00020` | C0101 | 193.70 |

Total €847.45 = batch gross = batch net.

**Mutations (3 ops):** `delete_record` IN-11 `TX-0924-00018`, `TX-0924-00019`, `TX-0924-00020`. Reason: the export omitted the batch's spends.

**Unchanged on purpose:** IN-12 `SB-EUR-20260924`, its lines `SL-SB-EUR-20260924-*`, IN-09 bank debit, IN-10, and IN-03.

### FIN

| Client | Roll-forward (24 Sep) | Snapshot | Roll-forward − snapshot |
|---|---|---|---|
| C0101 | 29,803.31 + 812.37 = 30,615.68 | 29,990.41 | **+625.27** (= 431.57 + 193.70) |
| C0104 | 26,002.58 + 2,052.70 = 28,055.28 | 27,833.10 | **+222.18** |
| C0102 (control) | | | 0.00 |

- Batch lines reference 3 transaction IDs absent from IN-11: TXN lines total 847.45 against 0.00 of matching transactions.
- No bank, ledger or requirement impact.

### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (3) | C11-BATCH-ARITH `SB-EUR-20260924` FAIL (3 lines do not match a transaction); CBAL-ROLLFWD `EUR/C0101 2026-09-24` FAIL; CBAL-ROLLFWD `EUR/C0104 2026-09-24` FAIL |
| Exceptions (3, High) | EXC-TC05-01 `C11-BATCH-ARITH\|SB-EUR-20260924`; EXC-TC05-02 `CBAL-ROLLFWD\|EUR/C0101 2026-09-24`; EXC-TC05-03 `CBAL-ROLLFWD\|EUR/C0104 2026-09-24` |
| Groups | 0 |
| Candidates | **1**: CAND-TC05-01 = {01, 03} (line TX-0924-00018 = 222.18). **No candidate for C0101**: its difference is the sum of two lines (G-16). |

### FUTURE (PROPOSED)

- The three exceptions are presented together as one suspected common cause, still UNVERIFIED: missing transactions of batch SB-EUR-20260924.
- The basis is the batch scope plus a line-sum match per client.
- No cause is set deterministically (G-16, G-17).

### AI (group-level)

| Element | Expectation |
|---|---|
| Individual discrepancies | (1) batch lines reference 3 IDs absent from the export; (2) C0101 is short 625.27 against its roll-forward; (3) C0104 is short 222.18 against its roll-forward |
| Possible common cause | The transaction export is incomplete for SB-EUR-20260924 |
| Connecting evidence | All 3 missing IDs belong to one batch. 222.18 equals one line exactly. 625.27 equals the sum of the other two lines. No other batch or day is affected. The header, lines and bank debit agree with each other. |
| Evidence still missing | The client of each missing transaction (settlement lines carry no client_id), and the export job log or a complete export |
| Confidence | Medium-high that the export is incomplete. Low-medium for the client attribution, which rests on amounts only. |

**Must not:** state the client attribution as confirmed.

**Expected analyst action:** request a complete transaction export.

### Correction

| Item | Detail |
|---|---|
| Correction file | `corrections/source_data/transactions_2026-09.csv` with the 3 rows restored. It is byte-identical to the baseline IN-11. |
| Expected after correction | **CLEAN** (the baseline frozen key) |

---

## TC06: Independent discrepancies

**Business situation.** Three unrelated defects. A and B deliberately share **date (17 Sep), currency (GBP) and magnitude (£90.00)**. That coincidence is a decoy: a date-and-amount grouping would wrongly merge them.

| Cause | Situation | Mutation |
|---|---|---|
| A: export amount error | C0007 bank load `TX-0917-00002` (E2E-GBP-0917-L02): bank, cash book and snapshot show 1,390.07; the export shows 1,480.07 | set_field IN-11 `TX-0917-00002` amount 1390.07 → 1480.07 |
| B: client-ledger snapshot error | C0004's 17 Sep 17:00 snapshot is overstated by 90.00. The firm's internal reconciliation used that ledger, so it reports a 90.00 shortfall. | set_field IN-03 `CBS-20260917-C0004-GBP` balance 40592.24 → 40682.24; set_field IN-05 `IRR-EMONEY-GBP-20260917` requirement_reported 341484.46 → 341574.46 and difference_reported 0.00 → -90.00 |
| C: acquirer report line error (EUR, 22 Sep) | Line 2 of `AQ-EUR-20260922` states 1,238.12; its header, the transaction and the bank credit imply 1,283.12 | set_field IN-13 `SL-AQ-EUR-20260922-0002` amount 1283.12 → 1238.12 |

### FIN

**Cause A:**

- Transaction − bank = **+90.00**.
- C0007 roll-forward for 17 Sep: 35,913.63 + 817.48 = 36,731.11 vs snapshot 36,641.11, so **+90.00**.
- The 18 Sep pair reconciles.

**Cause B:**

- C0004 17 Sep: roll-forward 40,592.24 vs snapshot 40,682.24, so **−90.00**.
- C0004 18 Sep: 40,682.24 + 1,492.89 = 42,175.13 vs snapshot 42,085.13, so **+90.00**.
- Recomputed requirement 17 Sep = 341,574.46 (as reported). Resource = 341,484.46. Difference = **−90.00** (apparent shortfall, as reported).

**Cause C:**

- TXN lines 2,069.15 vs gross 2,114.15, so **−45.00**.
- Signed lines 2,059.53 vs net 2,104.53, so **−45.00**.
- The line differs from `TX-0922-00016` by −45.00.
- The bank credit equals the header net, so there is no balance impact.

### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (6) | RC4-DIRECT `TX-0917-00002`; CBAL-ROLLFWD `GBP/C0007 2026-09-17`; C06-DIFFERENCE `2026-09-17/GBP` (C04 PASS); CBAL-ROLLFWD `GBP/C0004 2026-09-17`; CBAL-ROLLFWD `GBP/C0004 2026-09-18`; C11-BATCH-ARITH `AQ-EUR-20260922` |
| Exceptions (6) | EXC-TC06-01 Critical `INTERNAL_DIFFERENCE\|2026-09-17/GBP` |
| | EXC-TC06-02 `C11-BATCH-ARITH\|AQ-EUR-20260922` |
| | EXC-TC06-03 `CBAL-ROLLFWD\|GBP/C0004 2026-09-17` |
| | EXC-TC06-04 `CBAL-ROLLFWD\|GBP/C0004 2026-09-18` |
| | EXC-TC06-05 `CBAL-ROLLFWD\|GBP/C0007 2026-09-17` |
| | EXC-TC06-06 `RC4-DIRECT\|TX-0917-00002` (02–06 all High) |
| Groups | **Predicted over-grouping (G-18):** GRP-TC06-01 = {01, 03, **05**}. L3 lineage (b) links the internal difference to every same-day GBP roll-forward failure, including C0007's, whose snapshot is correct. EXC-04 (C0004's next day) and EXC-06 (C0007's RC4) stay ungrouped. No candidates. |

**Correct clustering (FUTURE, PROPOSED):**

| Cluster | Exceptions | Root |
|---|---|---|
| A | {06, 05} | `PENDING:AMOUNT_MISMATCH` on TX-0917-00002 |
| B | {01, 03, 04} | Snapshot error, C0004 17 Sep |
| C | {02} | Acquirer report line inconsistency |

The A/B coincidence must be recorded as **rejected** (no shared record or reference).

### AI

The investigation should:

- Keep three separate causes.
- Explain that A is transaction-side (IN-11 is the outlier against IN-09, IN-10 and IN-03).
- Explain that B is snapshot-side (C0004's 17 Sep snapshot fails the roll-forward in both directions and drives the reported shortfall).
- Explain that C is internal to the acquirer report.
- Explicitly reject a link between A and B based on equal date and amount.

**Missing evidence:**

- A: the export audit trail.
- B: the client-ledger postings behind C0004's 17 Sep balance.
- C: the corrected acquirer report.

**Expected analyst actions:**

| Cause | Action |
|---|---|
| A | Request a corrected export |
| B | Investigate the client-ledger posting. The reported 17 Sep shortfall is not supported by the transactions. |
| C | Request a corrected acquirer report |

**Correction:** none (investigation demonstration).

---

## Open points for the Stage C review

1. **TC03 supplementary evidence.** May the October extract be shipped as a clearly marked, non-ingestible reference artefact? The alternative is to omit it.
2. **TC06 relies on a predicted engine defect (G-18).** If the owner considers L3 (b) correct by design, TC06 still stands, and only its "predicted over-grouping" label changes.
3. **Packaging.** Stage D will produce engine-layout case directories (`source_data/`, `supporting_documents/`, `scenario.json`, `manifest.csv`). Ringfence-style customer ZIPs are **not** planned unless requested: the Ringfence member naming was seen only in the existing library and not verified as a contract.
4. **All ENGINE-PREDICTED values are unexecuted.** They become verifiable only when engine runs are permitted.
