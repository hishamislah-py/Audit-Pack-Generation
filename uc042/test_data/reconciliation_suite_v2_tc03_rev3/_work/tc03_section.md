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

