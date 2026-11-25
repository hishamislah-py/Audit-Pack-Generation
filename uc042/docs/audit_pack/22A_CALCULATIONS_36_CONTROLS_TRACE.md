> Appendix 22A to report 22 (`22_COMPLETE_UC042_PRODUCT_AND_WORKFLOW_WALKTHROUGH.md`). Read-only code trace of the Phase 8 working tree, 5 November 2026. Nothing was executed against live data; file:line references are to `uc042/`.

# Part E: UC-042 financial calculations, a business-language companion to 20B

All data is ILLUSTRATIVE SYNTHETIC. Basis: `uc042lib/validate.py` (1,661 lines, read 5 Nov 2026), `uc042lib/schema.py` (`DEPENDS` 282–312), `uc042lib/continuity.py`, `tools/verify_demo_history.py`, the February and S05 pack JSON files, and the source CSVs. Nothing was executed except read-only Python and awk over JSON/CSV files. Line numbers refer to `validate.py` unless another file is named.

**How these notes relate to 20B.** I checked every method line range in the 20B run-order table (A.8) and every formula line it cites for the 36 checks against the current `validate.py`. **All of them match** (for example C06 `diff != rep` at 739, C08 `bank - ledger` at 789, C11 bank match key at 815–816, `abs(` only at 1462). I found no formula mismatch. The new points are in section 5 below. Some of 20B's documentation statements are imprecise or incomplete; they are flagged there with a "20B" tag.

**Outcome vocabulary.** PASS; FAIL (the evidence shows a problem); INSUFFICIENT_EVIDENCE ("INSUF": could not be assessed, never treated as zero); NOT_APPLICABLE ("NA"). Every FAIL or INSUF carries a `root_cause`. Each distinct root cause becomes exactly **one exception** (`_group_exceptions` 1191–1303). Severity comes from `SEVERITY` (1174–1177): Critical for MISSING_BANK_EVIDENCE, BANK_LEDGER_DIFFERENCE, INTERNAL_DIFFERENCE, MISSING_RECON, MISSING_EXT_RECON, MISSING_FILE, EMPTY_FILE, INVALID_FILE, AMBIGUOUS_FILE and WRONG_PERIOD. Everything else is High. Every exception is created with status OPEN and review status AWAITING_HUMAN_REVIEW (1280, 1293).

**Notation.** P = the reconciliation point (17:00 Europe/London, DST-aware, from the policy PDF; `point()` 400–401). "signed" = the sign rules in `money.py`: bank C+/D−; cash book D+/C−; client CR+/DR−. "Gate" = whole-check INSUF when a file the check depends on is unavailable (`gate` 186–195, `schema.DEPENDS`). "BD" = England and Wales business day (`business_day_after`, 55–57). No monetary tolerance exists anywhere: every comparison is exact to the cent.

---

## 1. The 36 controls in run order

| # | Check ID (code lines) | Financial question | Records compared (file: columns) | Match / group | Formula (exact, from code) | Time / BD rules | Missing evidence | Becomes exception as |
|---|---|---|---|---|---|---|---|---|
| 1 | V00-FILE (254–296) | Is every required file present, unaltered and for this month? | All IN-01..19 vs `manifest.csv` sha256, `intake.csv` | per file ID | SHA-256(bytes) ≠ manifest sha256 → FAIL; not in manifest → FAIL; other-month canonical file → FAIL | month token in file name | required missing → INSUF `MISSING_FILE`; optional → NA; ambiguous → INSUF/NA `AMBIGUOUS_FILE` | MISSING/AMBIGUOUS_FILE Critical; FAIL → `V00-FILE|fid` High. Never emits PASS |
| 2 | V01-SCHEMA (298–336) | Can each CSV be read as its evidence type? | IN-01..14 header vs `schema.columns` | per file | header == expected list (order/case); rows>0 unless IN-04/IN-14; row count == manifest | – | empty → INSUF `EMPTY_FILE`; bad header → FAIL `INVALID_FILE` | EMPTY/INVALID_FILE Critical; invalid rows/count mismatch → `INVALID_ROWS` High |
| 3 | V01-PDF (365–394, 441–456) | Is each PDF genuine and does it carry its key details? Is the policy usable for this period? | IN-15..19 text labels; policy "Reconciliation point", "Effective date" | per file | `%PDF-` header; every label matches `^label: (.+)$`; pages == manifest; point matches `^HH:MM Europe/London$`; effective ≤ period end | effective date vs period end | unusable → FAIL `INVALID_FILE` (file then gates dependants) | INVALID_FILE Critical; page mismatch → `V01-PDF|fid` High |
| 4 | DQ-FIELD (319–327; structure.py `check_rows`) | Is every row well-formed (2-dp amounts, ISO dates, offsets, enums, unique key)? | every column of IN-01..14 | per (file, line, field) | type rules; duplicate primary key after the first | ts must carry an offset | row excluded and "taints" every scope it could touch → those scopes go INSUF | `INVALID_ROWS|fid` High (one per file); a bad row in IN-01/IN-02 makes the whole file unusable (333–335) |
| 5 | DQ-PERIOD (338–363) | Does each row belong to this month (plus the permitted opening rows)? | dated columns per `PERIOD_RULES` | per row / file | row date in [start, end], except permitted boundary rows (IN-03 month-end snapshot, IN-10 OPENING_BALANCE) | London dates | 0 in-period rows → file WRONG_PERIOD (unusable) | WRONG_PERIOD Critical; `OUT_OF_PERIOD_ROWS` High |
| 6 | C03-POLICY (458–466) | Does the policy prescribe the method the engine implements? | IN-17 "Reconciliation method", "Internal reconciliation basis" | period | PASS iff method == "STANDARD" and basis == "Per currency" (464) | – | gate IN-17 → INSUF | `C03-POLICY|period` High |
| 7 | C03-POINT (467–480) | Were reconciliations, snapshots and bank confirmations taken at 17:00? | IN-05 `reconciliation_point_ts`, IN-03 `as_at_ts` (vs `recon_date`); IN-07 `as_at_ts` | one result per file | IN-05/03: `parse_ts(ts) != point(recon_date)` (instant); IN-07: wall-clock time ≠ point_time (offset ignored, 478) | exact second | file unavailable → INSUF with its root | `C03-POINT|IN-xx` High |
| 8 | C01-COVER (509–513, `_cover` 534–547) | Did the firm do exactly one internal reconciliation per currency per recon day? | IN-01 recon days × safeguarding currencies vs IN-05 (`recon_date`, `currency`) | day × currency | count == 1 PASS; 0 → **FAIL**; >1 → FAIL duplicates | IN-01 `is_recon_day` only | absent → FAIL `MISSING_RECON` (INSUF if a tainted IN-05 row could be it) | MISSING_RECON Critical |
| 9 | C07-COVER (522–525) | Did the firm do one external (bank) reconciliation per safeguarding account per day? | IN-06 (`recon_date`, `account_id`) | day × account | as C01 | as C01 | absent → **FAIL** `MISSING_EXT_RECON` | MISSING_EXT_RECON Critical |
| 10 | C14-COVER (503–532) | Do we hold every client snapshot, both batches (SCHEME and ACQUIRER) per currency, the 17:00 confirmation per safeguarding account, and the EOD statement for every account, every day? | IN-03, IN-12, IN-07, IN-08 | day × ccy × client / ccy × type / account | count == 1 | the "two batches every day" rule is hardcoded (519) | absent → **INSUF** (`MISSING_SNAPSHOT`, `MISSING_BATCH`, `MISSING_BANK_EVIDENCE`) | MISSING_BANK_EVIDENCE Critical (shared); MISSING_SNAPSHOT/BATCH High |
| 11 | DQ23-STATEMENT (551–572) | Does each bank statement add up? | IN-08 header vs IN-09 entries (by `statement_id`) | per statement, all 4 accounts | `opening + Σ signed(entries) == closing`; `len(entries) == entry_count`; each entry has the statement's account, currency and date | plain dates | tainted entry → INSUF | `DQ23-STATEMENT|sid` High |
| 12 | DQ22-CONTINUITY (573–607) | Does each day's bank opening equal the previous closing, and does the first statement start where the cash book starts? | IN-08 consecutive statements per account; first opening vs IN-10 OPENING_BALANCE | per account | (a) `first_open == opening_cash[acct]`; (b) `prev_closing == cur_opening` if no recon day lies between them | gap = any recon day strictly between two statements | gap → INSUF root `MISSING_BANK_EVIDENCE|acct|first gap day`; no usable opening row → FAIL (or INSUF if tainted) | gap joins the missing-bank exception; break → `DQ22-CONTINUITY|…` High |
| 13 | BC-VS-EOD (608–624) | Does the 17:00 bank balance equal the opening plus entries booked by 17:00? | IN-07 vs IN-08 opening + IN-09 | per existing IN-07 row | `expected = signed(opening) + Σ signed(entries with booking_ts ≤ as_at_ts)`; PASS iff `balance == expected` | instants | no EOD for that day / invalid row → INSUF | `BC-VS-EOD|sid` High or the shared missing root |
| 14 | CASH-BANK-LINK (637–658) | Does every ledger posting have exactly one bank entry with the same reference, and is the amount equal? | IN-10 `payment_reference` vs IN-09 `bank_reference` / `end_to_end_ref` (safeguarding accounts only) | key (account, reference); **never by amount** | 1 match: PASS iff `signed(bank) == signed(cashbook)` and same currency; >1 → FAIL | posting date from `posted_ts` as written | no match and that day's bank evidence missing/tainted → INSUF (`evidence_gap`) | no match → `UNMATCHED_CASHBOOK_ENTRY|id` High; mismatch → `CASH-BANK-LINK|id` High |
| 15 | BANK-CASH-LINK (659–666) | Did anything hit the safeguarding account that the ledger did not record? | IN-09 (safeguarding accounts) vs IN-10 references | per bank entry | existence of any reference in the cash book (no amount test) | – | tainted IN-10 row → INSUF | `UNMATCHED_BANK_ENTRY|id` High (shared with #28). Emits only problems; the pack shows NO_FINDINGS when clean |
| 16 | C04-REQUIREMENT (694–712) | How much must be safeguarded in this currency at 17:00, and did the firm report it? | IN-03 balances (`recon_date`, `currency`); IN-04 open receipts; IN-05 `requirement_reported` | one per IN-05 row (day × ccy) | `req = Σ max(0, balance) + Σ amount(IN-04 in ccy with receipt_ts ≤ P and (allocated_ts blank or > P))` (707–708); PASS iff `req == requirement_reported` | instants vs P | no snapshots → INSUF `MISSING_SNAPSHOT`; tainted IN-03/04 → INSUF | `C04-REQUIREMENT|d/ccy` High |
| 17 | C05-RESOURCE (713–731, `ledger_at` 668–678) | What does the ledger say is held at 17:00, and does the reported resource add up? | IN-10 for the currency's safeguarding account; IN-05 `item_a..d`, `resource_reported` | one per IN-05 row | `item_A = Σ signed(IN-10 rows of acct with posted_ts ≤ P, incl. OPENING_BALANCE)`; `resource = item_A + item_b + item_c + item_d` (B–D as reported); PASS iff item_A == `item_a` **and** resource == `resource_reported` (725) | instants | no OPENING_BALANCE row / tainted → INSUF | `C05-RESOURCE|d/ccy` High |
| 18 | C06-DIFFERENCE (732–744) | Does the firm hold exactly what it owes clients today? | outputs of #16 and #17; IN-05 `difference_reported` | per IN-05 row | `diff = resource − req` (738); diff ≠ reported → FAIL; diff == 0 == reported → NA; diff == reported ≠ 0 → FAIL "requires same-day resolution (CASS 15.8.50R)" | – | either side None → INSUF | **every** C06 FAIL → `INTERNAL_DIFFERENCE|d/ccy` Critical (1237–1239), one per day |
| 19 | C07-BANK-EVIDENCE (755–771) | Does the bank's own 17:00 confirmation say what the firm reported? | IN-06 `bank_statement_id`, `bank_balance_reported` vs IN-07 | per IN-06 row (day × account) | `bank = signed(balance_amount, dc)`; PASS iff same account, currency == record == account currency, as-at date == d, bank == reported | as-at date as written | cited confirmation absent → INSUF `MISSING_BANK_EVIDENCE` | shared missing root, or `C07-BANK-EVIDENCE|d/acct` High |
| 20 | RC2-LEDGER (772–781) | Does the cash book really show the reported ledger balance at 17:00? | IN-10 via `ledger_at`; IN-06 `ledger_balance_reported` | per IN-06 row | `ledger = ledger_at(acct, P)` (same as item A); PASS iff == reported | instants | not computable → INSUF | `RC2-LEDGER|d/acct` High |
| 21 | C08-DIFFERENCE (782–806, timing 99–176) | Does the bank hold what the ledger says? If not, is there timing evidence? | #19 bank vs #20 ledger; IN-06 `difference_reported`, `timing_difference_claimed`; timing pairs IN-10↔IN-09 | per IN-06 row | `diff = bank − ledger` (789); ≠ reported → FAIL; 0 == reported → NA; == reported ≠ 0 → FAIL. Timing: `explained = Σ effects of IN_WINDOW items`, `residual = diff − explained` | timing item counts only if its later side is ≤ next BD after d (107, 138) and that day's evidence is usable; **wording only, never the outcome** | bank or ledger None → INSUF; the reported figure is never used | C08 FAILs on consecutive recon days, same account, same amount → one `BANK_LEDGER_DIFFERENCE|acct|first|amt` Critical (1193–1214); flags OWN_FUNDS_REQUIRED if negative |
| 22 | C11-BATCH-ARITH (818–846) | Does each settlement batch add up from its lines, and is each line a real transaction? | IN-12 header vs IN-13 lines vs IN-11 | per batch | Σ TXN lines == `gross_amount`; Σ FEE == `total_fees`; Σ REFUND == `total_adjustments`; Σ signed lines (C+/D−) == `batch_net_signed`; line currency == batch; each TXN/REFUND line's txn exists in this batch with an equal amount string | – | tainted line/txn → INSUF | `C11-BATCH-ARITH|batch` High |
| 23 | C11-BATCH-BANK (847–875) | Did the bank receive or pay exactly the batch net under the batch reference? | IN-12 (`account_id`, `expected_bank_reference`) vs IN-09 (`account_id`, `bank_reference` only) | reference first, then amount | 1 hit: PASS iff `signed(bank) == net_signed` and same currency; 0/>1 → FAIL | lag in BDs is **informational only** (856–866) | no hit and that day's evidence missing → INSUF | shared missing root or `C11-BATCH-BANK|batch` High |
| 24 | C11-TXN-LINE (876–892) | Is every card load, spend or refund settled in exactly one line of its batch? | IN-11 (LOAD_CARD/SPEND/REFUND) vs IN-13 | per transaction | batch known and count(lines with txn_id) == 1; otherwise one summary PASS | – | tainted batch/line → INSUF | `C11-TXN-LINE|txn` High |
| 25 | FUND-TOPUP (894–929) | Were fees netted from settlement replaced from own funds the same day? | IN-12 `total_fees` > 0; IN-09 safeguarding credit and own-funds debit with ref `TOPUP-{CCY}-{YYYYMMDD}`; IN-10 OWN_FUNDS_TOPUP | per batch with fees | exactly 1 safeguarding C, 1 own-funds D, a cash-book row; all three amounts == fees; safeguarding `booking_date == settlement_date` (924–926) | **same day** (926) | leg absent and that account-day's evidence missing → INSUF | shared root or `FUND-TOPUP|batch` High |
| 26 | RC4-DIRECT (939–969) | Did each client bank load or payout actually move through the safeguarding account? | IN-11 LOAD_BANK/REDEMPTION `payment_reference` vs IN-09 `end_to_end_ref` | 1:1 by end-to-end reference | 1 hit: PASS iff amount string equal, currency equal, dc == C (load) / D (redemption) | – | 0 hits: pre-period receipt → NA (P1); evidence missing → INSUF; else FAIL | shared root or `RC4-DIRECT|txn` High |
| 27 | C09-ALLOCATION (970–1011) | Was each unallocated receipt real, and allocated to a client by the next business day? | IN-04 vs IN-09 (`end_to_end_ref`) vs IN-11 LOAD_BANK | per receipt | exactly one bank credit with equal amount/currency; allocated date ≤ `business_day_after(receipt_date)`; if allocated in period, one LOAD_BANK with `executed_ts == allocated_ts` and same client | **next BD** (986, 1005); after-period allocation = P1 note | issue + missing/tainted evidence → INSUF | `C09-ALLOCATION|receipt` High |
| 28 | C11-BANK-ENTRY (1013–1035) | Is every safeguarding bank movement explained by a batch, transaction, receipt or top-up? | IN-09 vs IN-12 / IN-11 / IN-04 / IN-10 references | per bank entry | reference existence only (1025–1026) | – | tainted counterpart → INSUF | `UNMATCHED_BANK_ENTRY|id` High (shared with #15); otherwise one summary PASS |
| 29 | C12-REFUND (1037–1054) | Does each refund reverse a real original, and stay within it? | IN-11 REFUND `original_txn_id` → original | per refund; running total per original | original exists, same currency and client; `cumulative refunds ≤ original amount` (1051–1052) | file order | original in a bad row → INSUF | `C12-REFUND|txn` High |
| 30 | CBAL-NONNEG (1058–1061) | Does any client have a negative balance? | IN-03 `balance` | whole month, one result | count(balance < 0) == 0 | – | gate IN-03 | `CBAL-NONNEG|all snapshots` High |
| 31 | CBAL-ROLLFWD (1062–1086) | Does yesterday's client balance plus the transactions between equal today's? | IN-03 consecutive snapshots per (ccy, client); IN-11 | per client × consecutive snapshot pair | `expected = balance(prev) + Σ signed(txns with point(prev) < executed_ts ≤ point(cur))`; PASS iff == balance(cur) | instants | tainted snapshot or txn → INSUF | `CBAL-ROLLFWD|ccy/client date` High |
| 32 | C13-CURRENCY (1088–1112) | Is any record in a currency other than its account's or batch's? | IN-06/07/08/09/10/12 vs IN-02 currency; IN-13/IN-11 vs IN-12 currency | one result | count of mismatches == 0 | – | batch in a bad row → INSUF | `C13-CURRENCY|all records` High |
| 33 | C10-DESIGNATION (1114–1136) | Has the bank acknowledged each safeguarding account as such? | IN-02 vs IN-15/16 letter labels | per safeguarding account | letter ref, account number, currency and name all equal; name contains "Safeguarding"; letter date ≤ period end | letter date vs period end | missing letter → **FAIL** (not INSUF), root = the file's root | joins the file exception, or `C10-DESIGNATION|acct` High |
| 34 | DISC-LOG (1206–1236; gate 1138–1140) | Was each bank-ledger difference logged for investigation? | each C08 difference group's `ERL-{acct}-{yyyymmdd}` ids vs IN-14 `recon_ref` | per difference group (or one "period" row) | PASS iff any matching log entry exists; FAIL otherwise | entries logged after period end are labelled P2 | excluded log entry → INSUF | FAIL shares the BANK_LEDGER_DIFFERENCE root and adds the NO_INVESTIGATION_LOGGED flag |
| 35 | C16-GOVERNANCE (1144–1154) | Was an accountable person named for the month? | IN-18 "Accountable person", "Allocated from" (optional) | period | PASS iff a person is named and allocated ≤ period end | allocated date | absent → NA (never gated) | `C16-GOVERNANCE|period` High |
| 36 | C16-RETURN (1155–1171) | Was last month's return filed on time? | IN-19 "Period", "Due date", "Submitted at" (optional) | period | `due = business_day_after(previous_end, 15)`; PASS iff the receipt is for the previous month, submitted ≤ due and stated due == due | **15 BDs** (1157) | absent → NA | `C16-RETURN|…` High |

Correlation (`_correlate_exceptions` 1306–1471) runs after the 36 checks. It never changes an exception. It only links exceptions into investigation groups:

- **L1:** the exceptions share a reference.
- **L2:** the same internal difference recurs on consecutive days.
- **L3:** lineage (one exception's record feeds the other's calculation).

Equal amounts with no shared reference are recorded only as "CAND, UNVERIFIED" candidates.

---

## 2. Business explanations

**Internal reconciliation (C04, C05, C06; one result per currency per reconciliation day).** This compares what the firm *owes* clients (the requirement) with what its *own books* say it holds for them (the resource), at 17:00:

- **Requirement:** the sum of each client's balance, with negatives counted as zero, plus every unallocated receipt still open at 17:00 (707–708).
- **Resource:** "item A" plus items B–D. Item A is the safeguarding cash book, rebuilt entry by entry from the month's opening row up to 17:00 (668–678). Items B–D are taken as the firm reported them, 0.00 in all data, and are not verified (729).

It is **ledger-to-ledger**: the bank balance is never used. A shortfall that exists only at the bank is therefore invisible here (see S05).

**External reconciliation (C07, RC2, C08; one result per safeguarding account per day).** This compares the **bank's** 17:00 confirmed balance (IN-07) with the firm's **ledger** for the same account (the same `ledger_at`). The difference is defined as bank − ledger (789). A negative difference means the bank holds less than the books say, so the firm must top up from own funds (flag at 1261–1262). The firm's own reported bank, ledger and difference figures are always compared with recomputed ones. They are never used in place of them.

**Opening balances.** The month starts from three "permitted boundary records" dated the previous calendar month-end at 17:00 (`period.py:268–277`):

- the cash-book OPENING_BALANCE row, one per safeguarding account;
- each client's month-end snapshot;
- the bank, whose first EOD statement opening is in IN-08.

Within the engine, the only opening test is DQ22 "opening": the first bank opening must equal the cash-book opening (586–590). Own-funds accounts have no opening test (595).

**Movements.** No separate "daily movement" or monthly total is computed or published (pack/config.py:19). Movements exist only inside these checks:

- DQ23: one statement's entries.
- BC-VS-EOD: entries booked by 17:00.
- `ledger_at`: all cash-book postings up to the point.
- CBAL-ROLLFWD: client transactions between two 17:00 points.

**Closing balances.** The engine never derives a closing balance of its own:

- **Bank closings** are taken from IN-08 and tested only arithmetically (DQ23) and for continuity (DQ22).
- **Ledger position** at 17:00 is recomputed cumulatively each day. It is not rolled from the previous day.

**Daily reconciliation (recon days / calendar).** The set of days is exactly the IN-01 rows with `is_recon_day == "true"` (428). The engine does not derive or override them. On each of those days it expects:

- one internal reconciliation per currency (C01);
- one external reconciliation per safeguarding account (C07-COVER);
- every client snapshot, one SCHEME batch and one ACQUIRER batch per currency, one 17:00 confirmation per safeguarding account, and one EOD statement per account (C14).

Bank holidays are computed (`period.bank_holidays`) and are used only for "next business day" arithmetic.

**Currency-specific calculations.** Every figure is keyed by one currency (internal) or one account (external), and there is no FX conversion anywhere (1105). The currency maps to the safeguarding account through a one-to-one dict (688). C13 proves that no record carries a currency other than its account's or batch's.

**Bank vs cashbook comparison.** This happens at two levels:

- **Balance level:** C08 (bank 17:00 balance − ledger at 17:00).
- **Item level:**
  - CASH-BANK-LINK: every ledger posting must have exactly one bank entry with the same reference, and the amounts are compared only after the reference link is made.
  - BANK-CASH-LINK: every safeguarding bank entry must have a ledger counterpart.

Matching is **by reference only**, never by amount (627, 641). When the two sides straddle 17:00, the timing logic (99–176) can *explain* a C08 difference if the later side is booked within one business day. It never resolves or passes the difference.

**Settlement matching (C11).** Each card-scheme or acquirer batch must satisfy three things:

1. **It adds up** (C11-BATCH-ARITH): lines = gross, fees and refunds, and the signed lines equal the signed net.
2. **It ties 1:1 to transactions** (C11-TXN-LINE).
3. **It appears once at the bank** under its reference with exactly the net amount (C11-BATCH-BANK). A booking lag is reported but does not change the outcome.

Fees deducted from a batch must be topped up from own funds the same day (FUND-TOPUP).

**Transactions and refunds.**

- Bank loads and redemptions must match one bank entry by end-to-end reference, with the same amount, currency and direction (RC4).
- Card transactions must each sit in one settlement line (C11-TXN-LINE).
- A refund must point to a genuine original for the same client and currency, and cumulative refunds must not exceed the original (C12).
- Client balances must roll forward only by recorded transactions (CBAL-ROLLFWD). This is what catches a double-posted refund that exists only in the client ledger (20B J.4).

**Unallocated balances (IN-04).** A receipt the firm cannot yet attribute to a client still counts:

- **In the requirement:** it is added while it is open at 17:00 (705–708).
- **In C09-ALLOCATION:** it must match one bank credit and be allocated by the next business day (986).
- **As an explanation:** its reference can explain a bank entry (C11-BANK-ENTRY).

A receipt from before the period is handled by "convention P1": its bank credit is in the previous month, so it is not matched (976–978, 953–956).

**Missing statements.** `evidence_gap` (223–231) declares an account-day "missing" when the EOD statement is absent, or, for a safeguarding account, when the 17:00 confirmation is absent. It also does so when an excluded row could belong to that account-day. Every check that needed that day's bank evidence then returns INSUF instead of FAIL, all with the same root `MISSING_BANK_EVIDENCE|acct|date`. They collapse into **one Critical exception**:

- C14, DQ22 gap, CASH-BANK-LINK, C07, C08;
- C11-BATCH-BANK, FUND-TOPUP, RC4, C09.

Ledger-only checks continue (RC2, C04–C06). Missing is never zero: C08 is not computed from the firm's reported bank figure.

**Month-to-month continuity.** There are three separate mechanisms, and only the first is inside the audit pack.

1. **Inside the engine (single month only):**
   - DQ22 "opening" checks the first bank opening against the cash-book OPENING_BALANCE row (586–590).
   - CBAL-ROLLFWD uses the month-end boundary snapshot as its *starting point*, which is not itself assessed (1071).
   - RC4/C09 apply convention P1 to pre-period receipts.

   The engine never reads the previous month's files. So it does **not** check that this month's OPENING_BALANCE equals last month's closing ledger, or that this month's opening client snapshot equals last month's last snapshot rolled forward.
2. **`uc042lib/continuity.py` (`compare`, continuity.py:161–175):** this compares previous closing with current opening in four views, each compared only with itself: BANK, CASH_BOOK (via `prev.ledger_at(acct, opening_point)`), CLIENT and UNALLOCATED. The result is MATCH, DIFFERENCE or NOT_VERIFIABLE, and a difference is never adjusted. The monthly service runs it *after* the pack is built. Its result is stored only in the processing run's result JSON, not in the pack, and an error in it becomes NOT_VERIFIABLE (`uc042app/services/monthly.py:814, 874–885`).
3. **`tools/verify_demo_history.py` (`closing_positions` 555–580, `opening_positions` 583–601, `continuity` 604–614):** an independent re-implementation that produced `demo_history/verification/continuity.csv`. That file has 144 rows: 8 boundaries × 18 (4 BANK + 2 CASH_BOOK + 12 CLIENT), all MATCH, and no UNALLOCATED rows because no receipt was open at any boundary. Its CLIENT view rolls the previous month's last snapshot forward with transactions up to the month-end 17:00. This **differs** from the engine module (see section 5, item 1).

---

## 3. Worked example A: February 2026, missing EUR bank statement (EXC-H202602-01)

**Sources:**

- `demo_history/packs/PACK-H202602-PER-2026-02-195df2e1f216/pack.json`
- `demo_history/datasets/2026-02/source_data/*.csv`

**The expectation:**

- `recon_calendar_2026-02.csv` L17 `2026-02-16,PER-2026-02,true`: 16 Feb is a reconciliation day.
- `account_inventory.csv` L3 `SGA-EUR-01,RELEVANT_FUNDS_BANK,EUR`: a safeguarding account.

**What is absent.** There is no row for SGA-EUR-01 on 16 Feb in either bank file:

- `bank_balance_confirmations_2026-02.csv` has 39 data rows; only `ST-SGA-GBP-01-20260216-1700` exists for 16 Feb.
- `bank_statements_eod_2026-02.csv` has 79 rows; on 16 Feb only SGA-GBP-01 (L42), OWN-GBP-01 (L43) and OWN-EUR-01 (L44) exist.
- The EUR chain jumps from L39 `ST-SGA-EUR-01-20260213-EOD` (closing 73061.72 C) to L46 `ST-SGA-EUR-01-20260217-EOD` (opening 73199.44 C).

Every file is present and valid, so no check is gated. `evidence_gap(SGA-EUR-01, 2026-02-16)` returns `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16` (229–230).

**The 15 INSUF results (pack `affected_result_ids`), all with that root:**

| Check | Scope | Source rows | Engine output (from pack) |
|---|---|---|---|
| C14-COVER | IN-07 and IN-08 `2026-02-16/SGA-EUR-01` | IN-01 L17, IN-02 L3 | "expected record absent (expected because of the cited calendar and account rows)" |
| DQ22-CONTINUITY | `ST-SGA-EUR-01-20260217-EOD` | IN-08 L39, L46 | "statement gap: no statement for 2026-02-16" (600–603) |
| CASH-BANK-LINK ×5 | `LE-EUR-0216-0001..0005` | IN-10 L128–132: BANK_LOAD 1821.28 D; ACQUIRER 1485.52 D; TOPUP 6.79 D; SCHEME 1007.29 C; REDEMPTION 2168.58 C | "bank statement for that day not provided" (INSUF, not FAIL, because of `evidence_gap`, 650–655) |
| C07-BANK-EVIDENCE | `2026-02-16/SGA-EUR-01` | IN-06 L23 cites `ST-SGA-EUR-01-20260216-1700`, bank_balance_reported 73199.44 | computed blank, reported 73199.44, "cited statement … not provided; reported bank balance is unverified" |
| C08-DIFFERENCE | same | IN-06 L23 difference_reported 0.00 | computed blank, reported 0.00, "bank evidence not provided; difference not computed" (784–788) |
| C11-BATCH-BANK ×2 | `AQ-EUR-20260216` (TO_FIRM net 1485.52), `SB-EUR-20260216` (FROM_FIRM 1007.29) | IN-12 L44, L45 | "bank statement for settlement date not provided" |
| FUND-TOPUP | `AQ-EUR-20260216` | IN-12 L44 fees 6.79 | computed 6.79, "bank statement for SGA-EUR-01 on 2026-02-16 not provided". The own-funds leg *is* present (IN-09 L140 `BE-OWN-EUR-0216-TU1`, 6.79 D, ref TOPUP-EUR-20260216); only the safeguarding credit is unavailable (913–914). |
| RC4-DIRECT ×2 | `TX-0216-00014` (LOAD_BANK 1821.28, E2E-EUR-0216-L01), `TX-0216-00020` (REDEMPTION 2168.58, E2E-EUR-0216-R01) | IN-11 L219, L231 | "bank statement for that day not provided" |

**What still ran on the same day and account (missing is not zero):**

- **C04 EUR 16 Feb: PASS 73199.44 = 73199.44.** The four balances (IN-03 L142–145) are 15982.42 + 20945.68 + 17196.41 + 19074.93, with 0 open receipts.
- **C05: PASS** "item A 73199.44; resource 73199.44" (57 cash-book entries to 17:00).
- **C06: NA** 0.00 = 0.00.
- **RC2-LEDGER: PASS** 73199.44 (57 entries).
- **C11-BATCH-ARITH: PASS** for both EUR batches (1485.52; −1007.29).
- **CBAL-ROLLFWD: PASS** for C0101..C0104.
- **DQ22 "SGA-EUR-01 opening": PASS** 71684.56 = cash-book opening.
- **DQ23 for 17 Feb: PASS** "73199.44+137.71=73337.15".

**An observation the engine does not make.** The 16 Feb ledger movement is +1821.28 + 1485.52 + 6.79 − 1007.29 − 2168.58 = **+137.72**. 13 Feb closing 73061.72 + 137.72 = 73199.44, which is exactly the 17 Feb opening. The surrounding bank evidence is therefore consistent with the ledger, but the engine does not (and by design should not) infer the missing day. DQ22 simply returns INSUF.

**Becoming an exception.** All 15 results share one root (one root = one exception), so there is one exception, EXC-H202602-01:

- severity **Critical** (`SEVERITY["MISSING_BANK_EVIDENCE"]`); category "Missing bank evidence"; status **OPEN**; review AWAITING_HUMAN_REVIEW;
- account SGA-EUR-01, EUR, first and last date 2026-02-16, amount blank; no flags, no group;
- one missing-evidence item MISS-01, "15 check result(s) could not be assessed", value shown as "not available".

Pack totals: 1,788 results, of which 1,690 PASS, 83 NA, 15 INSUF and 0 FAIL. Engine case status is **EVIDENCE_INCOMPLETE** (any INSUF; `case_status` 1492–1501); evidence completeness INCOMPLETE; control outcomes NOT_FULLY_ASSESSED. 20B J.1 matches all of these values.

---

## 4. Worked example B: September S05, unexplained GBP difference −812.40

**Sources:**

- `packs/PACK-S05-PER-2026-09-ddd0fdc8b731/pack.json`
- `uc042_dataset/scn_S05_unexplained_gbp_difference/` (`mutations.json` has 51 operations; `source_data/*.csv`)

**What was changed (mutations.json):**

- Added IN-09 L152 `BE-GBP-0917-X01,ST-SGA-GBP-01-20260917-EOD,SGA-GBP-01,2026-09-17,2026-09-17T15:20:00+01:00,…,812.40,D,GBP,SETTLE 0417,,,SETTLE 0417`.
- The 17 Sep EOD closing went from 341484.46 to 340672.06, and entry_count from 5 to 6.
- On each of the 10 reconciliation days 17–30 Sep, the IN-07 confirmation and the IN-06 `bank_balance_reported` were lowered by 812.40, and the IN-06 `difference_reported` was set to −812.40.
- The cash book, client snapshots, internal reconciliation records, batches and discrepancy log are unchanged.

**External reconciliation, SGA-GBP-01, 17 Sep (IN-06 L26 `ERL-SGA-GBP-01-20260917`):**

| Item | Engine computed | Firm reported (IN-06 L26) | Result |
|---|---|---|---|
| Bank: IN-07 L26 `340672.06 C` at 17:00+01:00 | 340672.06 | 340672.06 | C07 PASS |
| Ledger: `ledger_at(SGA-GBP-01, 17 Sep 17:00)` (73 IN-10 entries, opening 250000.00 D) | 341484.46 | 341484.46 | RC2 PASS |
| **Difference = bank − ledger (789)** | 340672.06 − 341484.46 = **−812.40** | −812.40 | **C08 FAIL** |

**Bank side cross-check.** The 17 Sep statement (IN-08 L50) opens at 334413.00. Its entries are:

- credits: +2785.45, +1390.07, +6431.06, +29.39;
- debits: −3564.51 and **−812.40**.

334413.00 + 6259.06 = 340672.06, so DQ23 PASS and BC-VS-EOD PASS ("opening + 6 entries booked by 17:00"). The ledger has only five postings that day (IN-10 L125–129), totalling +7071.46: 334413.00 + 7071.46 = 341484.46. The 812.40 debit is the whole gap.

**Internal reconciliation, GBP, 17 Sep (IN-05 L26 `IRR-EMONEY-GBP-20260917`):**

| Item | Computed | Reported | Result |
|---|---|---|---|
| Requirement: 8 client balances (IN-03 L158–165, 49069.04 … 39993.41) + 0 open receipts | 341484.46 | 341484.46 | C04 PASS |
| Resource: item A 341484.46 + B–D 0.00 | 341484.46 | 341484.46 | C05 PASS |
| Difference: resource − requirement | 0.00 | 0.00 | C06 NA |

"Requirement vs resource" balances because both sides are ledger-based. Only "bank vs ledger" shows the −812.40. The pack's 30 Sep figures follow the same pattern: bank 395032.46, ledger 395844.86, and requirement = resource = 395844.86.

**Why it is classified "unexplained":**

- C08's computed difference equals the reported one and is not zero, so the outcome is FAIL (797–806).
- `timing_assessment` found no timing items. The structured output is `{"timing_items": [], "explained_by_timing": "0.00", "residual_unexplained": "-812.40"}`. `timing_items` iterates *cash-book* entries and seeks their bank counterpart (114–117). `SETTLE 0417` has no cash-book entry, so a bank-only debit can never become timing evidence.
- `timing_difference_claimed` = false, so the note reads "unexplained bank-ledger difference" with evidence_status NOT_EVIDENCED.
- The exception category comes from `CATEGORY["BANK_LEDGER_DIFFERENCE"]` = "Unexplained bank-ledger difference" (1178). Only TIMING_EVIDENCED or TIMING_PARTIAL rename it (1294–1297).

**Exceptions:**

- **EXC-S05-01**: Critical, OPEN; root `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-17|-812.40`; amount −812.40; 2026-09-17 to 2026-09-30.
  - **Affected results (11):** C08 FAIL on 17, 18, 21, 22, 23, 24, 25, 28, 29 and 30 Sep, all −812.40. Consecutive reconciliation days with the same account and amount are merged into one group (1200–1201). DISC-LOG `SGA-GBP-01 from 2026-09-17` FAIL ("10 day(s) with difference" vs "0 log entries"; IN-14 is header-only).
  - **Flags:** `OWN_FUNDS_REQUIRED (CASS 15.8.57R …)` because the amount is negative, and `NO_INVESTIGATION_LOGGED`.
  - **Related record:** `BE-GBP-0917-X01` ("unreconciled entry on the statement where the difference first appears; not linked by amount", 1267).
- **EXC-S05-02**: High, OPEN; root `UNMATCHED_BANK_ENTRY|BE-GBP-0917-X01`; amount −812.40.
  - **Affected results:** BANK-CASH-LINK FAIL ("bank entry has no cash-book counterpart") and C11-BANK-ENTRY FAIL ("no batch, transaction, top-up or register counterpart").
- **GRP-S05-01** links the two by **L3 LINEAGE**: "bank entry BE-GBP-0917-X01 is inside the 2026-09-17 17:00 balance of SGA-GBP-01, where the difference begins". The group sets no cause.

Totals: 1,887 results, of which 1,796 PASS, 13 FAIL and 78 NA. Evidence is COMPLETE, so engine status is **EXCEPTIONS_OPEN**. 20B J.2 matches all of these values.

---

## 5. Unclear, inconsistent or surprising points

1. **There are two continuity implementations, and they disagree on method.**
   - `uc042lib/continuity.py:115–134` (`clients`) requires the previous period to hold a snapshot dated the previous calendar month-end. In the demo data, the previous month's last snapshot is the last *reconciliation* day whenever the month ends on a weekend or holiday:
     - January's last snapshot is 2026-01-30, while February opens with 2026-01-31.
     - The same applies to Feb→Mar (27 Feb vs 28 Feb), May→Jun (29 May vs 31 May) and Aug→Sep (28 Aug vs 31 Aug).
   - Reading the code, the engine module would therefore return CLIENT **NOT_VERIFIABLE** for those 4 of 8 boundaries. This is inferred and was not executed.
   - `tools/verify_demo_history.py:562–569` instead rolls the last snapshot forward with transactions, and reports MATCH (continuity.csv).
   - The test `tests/test_demo_history.py:516–523` asserts only "no DIFFERENCE" and "BANK and CASH_BOOK all MATCH". It would not catch CLIENT NOT_VERIFIABLE.
   - **20B:** Part H presents "144 items, all MATCH" next to the engine module, without saying that the two use different CLIENT logic.
2. **The engine never checks continuity across months**, apart from DQ22 opening against the cash-book OPENING_BALANCE (586–590). Engine continuity is reported only in the run's result JSON and is not in the pack (`uc042app/services/monthly.py:814`). An auditor reading only the pack sees no cross-month check.
3. **DQ22 opening compares a bank EOD-based opening with a ledger 17:00 position** (582–589). The first statement's opening is the previous day's end-of-day balance; the OPENING_BALANCE row is the ledger at month-end 17:00. A genuine post-17:00 movement on the last day of the previous month would FAIL here, with no timing logic applied. It is harmless in the demo data (the month-ends have no such entries), but it is a latent false-positive.
4. **A reporting error is labelled as a real difference.**
   - C08 FAILs when computed ≠ reported, even if computed = 0.00 (790–794). That result still becomes `BANK_LEDGER_DIFFERENCE|…|0.00`, a Critical exception with the category "Unexplained bank-ledger difference" (1211, 1178).
   - Likewise, *any* C06 FAIL, including a mere misreport with a true difference of 0.00, becomes a Critical `INTERNAL_DIFFERENCE` "Internal reconciliation difference" (1237–1239).
   - **20B** describes the outcomes but not this labelling consequence.
5. **A row-count mismatch is labelled as invalid rows.** In V01-SCHEMA, a manifest row-count mismatch with no invalid rows still gets root `INVALID_ROWS|fid` (320, 328–332). The exception then reads "Invalid rows excluded", with the flag "has invalid rows: dependent checks were not run on incomplete evidence" (1268–1269). In fact no row was excluded and every check ran.
6. **A changed file is reported but still used.** A V00-FILE SHA-256 mismatch is a FAIL, but the file is still loaded and used in every calculation (275–280). The same applies to a file "not listed in manifest". This is not stated in 20B's V00-FILE table.
7. **The category says "Unexplained" even when timing is merely unverifiable.** The category stays "Unexplained bank-ledger difference" for TIMING_UNVERIFIABLE and NOT_EVIDENCED alike (1294–1297). "Unexplained" can therefore mean "possible timing item, but the evidence is outside the period".
8. **Bank-ledger difference grouping breaks when both accounts fail together.** C08 grouping sorts by the scope string `date/account` (1194–1195). When GBP and EUR both fail on the same days, the rows interleave, so each day becomes its own exception. 20B Part M mentions this; it is untested.
9. **Bank-only items can never be timing evidence.** The timing logic only starts from cash-book entries (114–117). A bank entry that the ledger books later *with the same reference* can be evidenced (the `booked <= pt < posted` branch, 134–135). A bank entry with no ledger posting at all never can (S05).
10. **Internal differences are never checked against the discrepancy log.** DISC-LOG covers only C08 groups (1206–1236). The match also depends on the hard-coded ID pattern `ERL-{acct}-{yyyymmdd}` (1212) rather than the actual IN-06 `ext_recon_id`. It works only because the synthetic IDs follow that pattern.
11. **Some IN-05 and IN-06 fields are never checked:**
    - `performed_at_ts`: when the reconciliation was actually done. There is no "reconciled by when" control; C03-POINT checks only `reconciliation_point_ts`.
    - `d1_requirement` and `d1_resource`: the D+1 comparison is not performed, as listed in `pack/config.py:16`.
    - `preparer_id` and `reviewer_id`.
12. **Missing evidence is treated inconsistently.** C10 treats a missing acknowledgement letter as FAIL, not INSUF (1120–1124). C01 and C07-COVER treat a missing reconciliation record as FAIL. C14 treats a missing bank, snapshot or batch record as INSUF. This is intentional (the firm's failure versus missing evidence), but a non-specialist will find it inconsistent.
13. **Some control-code labels are odd for business readers.** FUND-TOPUP is labelled control "C06 / Internal difference handling", RC4-DIRECT is labelled "C09 / Receipts mapping", and CBAL-* are labelled "C04 / Requirement" (`CONTROL_OF` 46–52).
14. **The documents disagree on how many checks there are.**
    - Code: 36 distinct check IDs (29 in `CONTROL_OF`, plus V00-FILE, V01-SCHEMA, V01-PDF, DQ-FIELD, DQ-PERIOD, C16-GOVERNANCE and C16-RETURN).
    - The February pack shows `check_types: 34`. DQ-FIELD and DQ-PERIOD are absent because they emit only findings, and unlike BANK-CASH-LINK they are not in `FAILURE_ONLY_CHECKS` (`pack/config.py:26–28`). A clean pack therefore does not show that they ran.
    - `CLAUDE_CODE_HANDOFF.md:95`, `docs/audit_pack/01_…:35`, `05_…:121` and `06_…:31` say "32 check types".
    - `docs/UC042_UPLOAD_CONTRACT.md:126` says "the other 22 checks".
15. **Hard-coded synthetic conventions drive outcomes:**
    - one SCHEME and one ACQUIRER batch per currency per day (519);
    - the top-up reference `TOPUP-{CCY}-{YYYYMMDD}` (907);
    - one safeguarding account per currency (688, a dict);
    - items B–D taken as reported (729).
16. **Dates are sometimes taken in the row's own offset rather than London time.** This affects the IN-07 as-at date, the CASH-BANK-LINK posting date, the RC4 execution date, the C09 deadline test (987, compared with 989, which uses London) and the IN-19 submission date. 20B A.7 notes it; it has not been tested with non-local offsets.
17. **20B DQ-PERIOD row:** "Inputs IN-01, IN-03 to IN-14" includes IN-13, but the same row says IN-13 is not period-checked (`schema.PERIOD_UNCHECKED`, schema.py:43). This is a minor wording inconsistency.
18. **C12 depends on file order.** Its running refund total is evaluated in file order (1051–1052), so the *first* refund that pushes the total over the original is the one that FAILs.
