## TC03: Timing difference, 24 Sep recorded / 25 Sep cleared (REVISION 3, 23 Nov 2026)

> **Revision history.**
>
> | Revision | Design | Where it is kept |
> |---|---|---|
> | 1 | 30 Sep / 1 Oct, as approved at Stage C | `archive/stage_b_approved_20261123/` |
> | 2 | 25 Sep / Sat 26 Sep, needing weekend records | `archive/rev2_tc03_25_26_sep_20261123/` |
> | 3 (current) | Thu 24 Sep / Fri 25 Sep, using the existing batch AQ-GBP-20260924 | this section |
>
> - The user chose revision 3, including its amount of **5,495.05**. The previously stated 4,647.75 is the net of the 25 Sep batch, whose card loads were made on 25 Sep.
> - Before/after detail: `TC03_REVISION_3_CHANGE_RECORD.md`.

**Business situation.** The acquirer settlement for Thursday 24 Sep 2026 is `AQ-GBP-20260924`.

| Stage | Detail |
|---|---|
| Card loads | Authorised and executed on 24 Sep |
| Settlement | Net £5,495.05; cycle date and settlement date 24 Sep |
| Firm's cash book | Posted at 14:00 on 24 Sep as `LE-GBP-0924-0003` |
| Bank | Credited on **Friday 25 Sep 08:00**, the next business day (`BE-GBP-0925-T01`, same reference and amount) |

At the 24 Sep 17:00 cut-off the bank is £5,495.05 below the ledger. The firm reported the difference, claimed timing and logged it as `DL-0001` (cause TIMING, evidence BE-GBP-0925-T01, RESOLVED 25 Sep). At 25 Sep 17:00 bank and ledger agree.

There are no weekend or non-reconciliation-day records.

**Mutations (11 ops):**

| # | Op | File | Record | Change |
|---|---|---|---|---|
| 1 | delete_record | IN-09 | `BE-GBP-0924-AQ1` | The 24 Sep 14:00 credit of 5,495.05 is not on the 24 Sep statement |
| 2 | add_record | IN-09 | `BE-GBP-0925-T01` | `ST-SGA-GBP-01-20260925-EOD`, 2026-09-25T08:00, value 2026-09-25, 5495.05 C, reference AQ-GBP-20260924 |
| 3–4 | set_field | IN-08 | `ST-SGA-GBP-01-20260924-EOD` | closing 370603.29 → 365108.24; entry_count 6 → 5 |
| 5–6 | set_field | IN-08 | `ST-SGA-GBP-01-20260925-EOD` | opening 370603.29 → 365108.24; entry_count 5 → 6. The closing is unchanged at 375461.46. |
| 7 | set_field | IN-07 | `ST-SGA-GBP-01-20260924-1700` | 370603.29 → 365108.24 |
| 8–10 | set_field | IN-06 | `ERL-SGA-GBP-01-20260924` | bank_balance_reported → 365108.24; difference_reported 0.00 → -5495.05; timing_difference_claimed false → true |
| 11 | add_record | IN-14 | `DL-0001` | Logged 2026-09-24T18:05 against ERL-SGA-GBP-01-20260924, -5495.05, TIMING, evidence BE-GBP-0925-T01, RESOLVED 2026-09-25T09:00, approver U-04 |

**Unchanged on purpose:**

- IN-10 cash book, IN-11, IN-12 and IN-13 for the batch.
- IN-03, IN-05 and IN-01.
- The 25 Sep 17:00 confirmation and the 25 Sep closing balance, both 375,461.46: the clearing is booked before 17:00.
- The own-funds top-up TOPUP-GBP-20260924, still on 24 Sep.

### FIN

| Item | Value |
|---|---|
| Transaction date | 24 Sep |
| Processing | Cash book 24 Sep 14:00 |
| Settlement date | 24 Sep |
| Bank clearing | Fri 25 Sep 08:00 |
| Cut-off | 24 Sep 17:00 |

| Point | Bank | Ledger | Bank − ledger |
|---|---|---|---|
| 24 Sep 17:00 | 365,108.24 | 370,603.29 | **−5,495.05** (reported and logged) |
| 25 Sep 17:00 | 375,461.46 | 375,461.46 | 0.00 |

- Requirement = resource on both days (370,603.29 and 375,461.46).
- Under the existing D1 rule, the clearing window is the next business day after 24 Sep, i.e. Fri 25 Sep. The clearing is inside it.
- **Expected treatment:** an explainable timing item. Under existing rules the 24 Sep difference is still a C08 exception, OPEN and awaiting human confirmation. It is never auto-resolved.

**Validator findings (exact set):**

- `BL_DIFF 2026-09-24 SGA-GBP-01 -5495.05`
- `BL_DIFF_LOGGED 2026-09-24 SGA-GBP-01 DL-0001`
- `TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05`
- `BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25`

### ENGINE-PREDICTED (not executed)

| Item | Prediction |
|---|---|
| Non-passing results (1) | C08-DIFFERENCE `2026-09-24/SGA-GBP-01` FAIL, evidence status **TIMING_EVIDENCED** |
| Exception | EXC-TC03-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-24\|-5495.05`. Category "explained by timing evidence, awaiting human confirmation". Flag OWN_FUNDS_REQUIRED. Status OPEN. |
| Groups | 0 |
| Must hold | DISC-LOG PASS. C11-BATCH-BANK `AQ-GBP-20260924` PASS, with the informational note of a 1-business-day lag. CASH-BANK-LINK and FUND-TOPUP PASS. C08 25 Sep PASS. DQ22, DQ23 and BC-VS-EOD PASS. |

### FUTURE (PROPOSED)

`PENDING:TIMING_ITEM`: one traceable item covering transaction → posting → settlement date → bank credit. It stays OPEN until a human confirms it.

### AI

The investigation should find:

- The −5,495.05 equals the AQ-GBP-20260924 net.
- It was recorded at 14:00 on 24 Sep and credited at 08:00 on 25 Sep.
- It cleared on the next business day.
- The timing claim is corroborated by the 25 Sep statement, not by the claim or the log label.

**Must not:** mark the exception resolved.

**Analyst action:** confirm the timing item, and confirm whether the firm's policy required an own-funds top-up at the 24 Sep point.

**Correction:** none.

---

