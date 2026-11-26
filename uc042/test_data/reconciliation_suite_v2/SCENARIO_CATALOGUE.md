# UC-042 Reconciliation Test Suite V2: Scenario Catalogue (Stage B specifications)

**Status:** Stage C APPROVED 23 Nov 2026. TC03 was revised on the user's instruction after approval (25/26 Sep). Datasets were generated (Stage D) and validated offline (Stage E). **Nothing has been executed by the UC-042 engine or application.** The approved Stage B text is preserved in `archive/stage_b_approved_20261123/`.

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
| TC03 | Timing difference (25 Sep recorded, 26 Sep cleared) | SYNTHETIC TEST Cresswell Money Ltd | IN-06, IN-07, IN-08, IN-09, IN-14 | No | EXCEPTIONS_OPEN / 1 / 0 (TIMING_EVIDENCED) |
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

## TC03: Timing difference, 25 Sep recorded / 26 Sep cleared (REVISED 23 Nov 2026)

> **Revision.** The user instructed the revision after the Stage C approval. It replaces the 30 Sep / 1 Oct period-end design, which is preserved unchanged in `archive/stage_b_approved_20261123/`.
>
> - No supplementary evidence mechanism is used.
> - No new field, control or evidence channel is introduced.

**Business situation.** The acquirer settlement for Friday 25 Sep 2026 is `AQ-GBP-20260925`.

| Stage | Detail |
|---|---|
| Card loads | `TX-0925-*` card loads, authorised and executed on 25 Sep |
| Settlement | Net £4,647.75; the acquirer report shows cycle date and settlement date 25 Sep |
| Firm's cash book | Posted at 14:00 on 25 Sep as `LE-GBP-0925-0003` |
| Bank | The acquirer's funds reached the safeguarding account on **Saturday 26 Sep 08:00** (`BE-GBP-0926-T01`, same reference and amount, value date 26 Sep) |

At the 25 Sep 17:00 reconciliation point the bank is £4,647.75 below the ledger.

The firm:

- reported the difference in IN-06;
- claimed timing;
- logged it in IN-14 as `DL-0001`, cause TIMING, evidence `BE-GBP-0926-T01`, RESOLVED 28 Sep.

The 26 Sep statement and 17:00 confirmation evidence the clearing. On the next reconciliation day (Mon 28 Sep) bank and ledger agree.

**Weekend dependency (flagged).** 26 Sep 2026 is a **Saturday**, marked WEEKEND (not a reconciliation day) in IN-01. Showing the clearing therefore needs a Saturday IN-08 statement and a Saturday IN-07 17:00 confirmation for SGA-GBP-01. Both use existing files and fields, but the baseline otherwise has no weekend bank records. The engine's timing rule (`timing_items`/`evidence_gap`) needs **both** for the clearing day to count as usable evidence. Without the confirmation the predicted status would be TIMING_UNVERIFIABLE. The validator lists the three weekend records as intended findings (`NON_RECON_DAY_RECORD`).

**Mutations (11 ops):**

| # | Op | File | Record | Change |
|---|---|---|---|---|
| 1 | delete_record | IN-09 | `BE-GBP-0925-AQ1` | The 25 Sep 14:00 credit of 4,647.75 is not on the 25 Sep statement |
| 2 | add_record | IN-09 | `BE-GBP-0926-T01` | `ST-SGA-GBP-01-20260926-EOD, 2026-09-26T08:00:00+01:00`, value 2026-09-26, `4647.75 C`, reference `AQ-GBP-20260925`, "Synthetic Acquirer Ltd" |
| 3–4 | set_field | IN-08 | `ST-SGA-GBP-01-20260925-EOD` | closing 375461.46 → 370813.71; entry_count 5 → 4 |
| 5 | add_record | IN-08 | `ST-SGA-GBP-01-20260926-EOD` | Saturday statement: opening 370813.71 C, closing 375461.46 C, 1 entry |
| 6 | set_field | IN-07 | `ST-SGA-GBP-01-20260925-1700` | 375461.46 → 370813.71 |
| 7 | add_record | IN-07 | `ST-SGA-GBP-01-20260926-1700` | Saturday 17:00 confirmation, 375461.46 C |
| 8–10 | set_field | IN-06 | `ERL-SGA-GBP-01-20260925` | bank_balance_reported 375461.46 → 370813.71; difference_reported 0.00 → -4647.75; timing_difference_claimed false → true |
| 11 | add_record | IN-14 | `DL-0001` | Logged 2026-09-25T18:05, recon_ref ERL-SGA-GBP-01-20260925, -4647.75, cause_category TIMING (SC2 precedent), cause_evidence_ref BE-GBP-0926-T01, RESOLVED 2026-09-28T09:00, approver U-04 |

**Unchanged on purpose:**

- IN-10 cash book, IN-11, IN-12 and IN-13 for the batch.
- IN-03 and IN-05.
- IN-01: 26 Sep stays WEEKEND.
- The 28 Sep statement opening of 375,461.46 equals the Saturday closing, so it needs no change.

### FIN

| Item | Value |
|---|---|
| Transaction date | 25 Sep (card loads) |
| Processing | Cash book 25 Sep 14:00 |
| Settlement date | 25 Sep |
| Bank clearing | Sat 26 Sep 08:00 |
| Cut-off | 25 Sep 17:00 |

| Point | Bank (IN-07) | Ledger | Bank − ledger |
|---|---|---|---|
| 25 Sep 17:00 | 370,813.71 | 375,461.46 | **−4,647.75** (reported correctly) |
| 26 Sep 17:00 (Saturday) | 375,461.46 | 375,461.46 | 0.00 |
| 28 Sep 17:00 | 378,706.65 | 378,706.65 | 0.00 |

- The internal reconciliation is unaffected: requirement = resource = 375,461.46 on 25 Sep.
- Under the existing D1 rule, the clearing window is the next business day after 25 Sep, i.e. Mon 28 Sep. The 26 Sep clearing is inside it.
- **Expected treatment:** an explainable timing item, evidenced by the 26 Sep clearing. Under the existing rules the 25 Sep difference is still an exception (C08 FAIL) that stays OPEN, awaiting human confirmation. It is never auto-resolved.

### ENGINE-PREDICTED (not executed)

| Item | Prediction |
|---|---|
| Non-passing results (1) | C08-DIFFERENCE `2026-09-25/SGA-GBP-01` FAIL. Evidence status **TIMING_EVIDENCED**; note "difference explained by timing: LE-GBP-0925-0003 / BE-GBP-0926-T01 (ref AQ-GBP-20260925, -4647.75, cleared 2026-09-26) … awaiting human confirmation; not resolved". |
| Exceptions (1) | EXC-TC03-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-25\|-4647.75`. Category "Bank-ledger difference (explained by timing evidence, awaiting human confirmation)". Flag OWN_FUNDS_REQUIRED (the difference is negative). Status OPEN. |
| Groups | 0 |
| Must hold | DISC-LOG PASS. C11-BATCH-BANK `AQ-GBP-20260925` PASS, with the informational note "booked 2026-09-26, 1 business day(s) after the settlement date (within the allowance)". CASH-BANK-LINK and FUND-TOPUP PASS. C08 28 Sep PASS. DQ22, DQ23 and BC-VS-EOD PASS for the 25, 26 and 28 Sep statements. C14 coverage unaffected. |

### FUTURE (PROPOSED)

`PENDING:TIMING_ITEM`. The C08 timing item and the C11 informational lag are presented as one traceable item covering transaction → posting → settlement date → bank credit. It stays OPEN until a human confirms it.

### AI

The investigation should find:

- The −4,647.75 equals the AQ-GBP-20260925 net exactly.
- The cash book recorded it at 14:00 on 25 Sep, and the bank credited it at 08:00 on 26 Sep with the same reference and amount.
- It cleared within one business day, and bank and ledger agree on 28 Sep.
- The timing claim is corroborated by the 26 Sep statement, not by the claim or the log label.

**Must not:** mark the exception resolved.

**Expected analyst action:** confirm the timing item, and confirm whether the firm's policy required an own-funds top-up at the 25 Sep point.

**Correction:** none.

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

## Stage C decisions (23 Nov 2026)

1. TC03: replaced by the 25/26 Sep design. No supplementary or post-period evidence mechanism is used.
2. TC06: retained. The predicted over-grouping (G-18) is documented as UNVERIFIED.
3. Packaging: engine-layout case directories, plus flat upload ZIPs of the 19 canonical files (per UC042_ZIP_INPUT_SPECIFICATION section 4), per-scenario packages and a master ZIP.
4. All ENGINE-PREDICTED values remain unexecuted.
