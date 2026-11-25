# UC-042 Source-to-Control Matrix — v1 (for review)

Status: proposed. It uses control IDs C01–C16, rules R01–R12 and D01–D11, reconciliation logic RC1–RC7 and data-quality checks DQ01–DQ23 from the parent spec (revision 17). Input file IDs (IN-xx) are defined in `UC042_INPUT_EVIDENCE_SPEC_V1.md`.

Outcome vocabulary (spec §6, `control_result.outcome`): `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE`, `NOT_APPLICABLE`. Status values such as `PENDING_REVIEW` belong to the review workflow, not to control outcomes.

The system concludes at most level L4 ("control demonstrated", spec §6). It never states a compliance conclusion (L5).

---

## 1. Matrix: input → fields → entity → rule → output

| Input | Source fields used | Canonical entity | Rule / control | Expected output (clean) | Failure behaviour |
| --- | --- | --- | --- | --- | --- |
| IN-01 calendar | `calendar_date`, `is_recon_day`, `non_recon_reason` | `recon_day` | Expected-scope generator for C01, C07, C14 (RC7); DQ05 | 22 recon days → 44 expected internal runs (22 × 2 currencies), 44 external lines, 44 confirmations, 88 EOD statements | File missing: no expected scope can be built, so C01, C07 and C14 all return `INSUFFICIENT_EVIDENCE`. Never assume weekdays. |
| IN-02 account inventory | `account_id`, `account_class`, `currency`, `asset_pool_id`, `designation_name`, `acknowledgement_letter_ref`, institution fields | `institution`, `safeguarding_account` | C10 (with IN-15/16); C13 currency ownership; scope for C07 | 2 safeguarding accounts, 2 own-funds accounts; each safeguarding account has a designation name and letter reference | Missing: account currency unknown, so C07 and C13 return `INSUFFICIENT_EVIDENCE`. Currency conflict with statements → DQ07 / DQ13. |
| IN-03 client snapshots | `recon_date`, `as_at_ts`, `client_id`, `currency`, `balance` | `client_balance_snapshot` | RC1 requirement term Σ max(0, balance); C04 (R04); DQ21 | Recomputed requirement per day and currency | Day or currency absent: C04 `INSUFFICIENT_EVIDENCE` for that scope. `as_at_ts` ≠ point → DQ21 BLOCK (day) and C03 finding. |
| IN-04 unallocated register | `receipt_ts`, `allocated_ts`, `amount`, `currency`, `bank_reference`, `classification` | `unallocated_receipt` | RC1 requirement term "open unallocated"; C09 (R09, R10) | `UR-0001` open on 11 Sep (adds £750.00); `UR-0002` open on 23 Sep (adds €400.00); both allocated by next business day | File missing: C04 `INSUFFICIENT_EVIDENCE` for **all** days, because the requirement cannot be completed without it. A header-only file is valid and means "none open". `bank_reference` unmatched → DQ12. |
| IN-05 internal records | `requirement_reported`, `resource_reported`, `item_a`–`item_d`, `difference_reported`, `reconciliation_point_ts`, `performed_at_ts`, `actions_taken_text` | `internal_recon_run` | C01 (R01) existence; C02 (R02) completeness; C03 (R03) point; C04/C05 reported ↔ recomputed; C06 (R06) difference handling | 44 rows; all reported values equal recomputed; every difference 0.00 | Row missing: C01 `FAIL` (`MISSING_RECON`). Field null: C02 `FAIL`. Reported ≠ recomputed: C04/C05 `FAIL` (`RECALC_DIFF`), with both values retained. |
| IN-06 external records | `ledger_balance_reported`, `bank_statement_id`, `bank_balance_reported`, `difference_reported`, `timing_difference_claimed` | `external_recon_line` | C07 (R07) existence and statement agreement; C08 (R08) difference handling; C02 | 44 rows; each cited statement exists; reported bank balance = statement balance | Row missing: C07 `FAIL` (`MISSING`). Cited statement absent: C07 `INSUFFICIENT_EVIDENCE` and DQ12; the reported bank balance is shown as unverified. |
| IN-07 confirmations | `statement_id`, `account_id`, `as_at_ts`, `balance_amount`, `balance_dc_indicator` | `bank_statement` (`BALANCE_CONFIRMATION`) | RC2 bank side; C07 | Balance per account per day; equals the cash-book roll-forward at 17:00 | Row missing: C07 `INSUFFICIENT_EVIDENCE` for that account and day. Two rows for one account and time with different balances → DQ13. |
| IN-08 EOD headers | `opening_*`, `closing_*`, `entry_count` | `bank_statement` (`EOD_STATEMENT`) | DQ22 cross-day continuity; DQ23 within-statement continuity; entry completeness | All continuity checks pass; 1 Sep openings equal the synthetic opening positions | Missing day: next day's DQ22 `WARN` (opening ≠ last available closing); entries for that day are unavailable to C09 and C11. `entry_count` ≠ entries → DQ23 BLOCK (statement). |
| IN-09 entries | `amount`, `dc_indicator`, `booking_ts`, `value_date`, `bank_reference`, `end_to_end_ref` | `bank_entry` | DQ23; C11 (D04) settlement → bank; RC4 1:1; C09 receipts mapping; C06 funding evidence (top-ups); confirmation inclusion (`booking_ts` ≤ 17:00) | Every entry links to exactly one of: settlement batch, load, redemption, top-up, unallocated receipt | Entry with no counterpart: C11 `FAIL` (bank entry with no batch). Reference duplicated across two entries → DQ13. |
| IN-10 cash book | `posted_ts`, `amount`, `dc_indicator`, `payment_reference`, `entry_type` | `sga_ledger_entry` (**proposed**) | RC1 item A recompute (C05, CASS 15.8.15R); RC2 ledger side (recomputed ledger vs `ledger_balance_reported`); cash book ↔ bank by reference | Item A at each 17:00 = reported `item_a`; recomputed ledger = reported ledger balance | Missing: C05 `INSUFFICIENT_EVIDENCE`, so `item_a` cannot be verified. The reported value is shown, not accepted. Cash-book entry with no bank entry → timing or break finding. |
| IN-11 transactions | `txn_type`, `amount`, `direction`, `settlement_batch_id`, `payment_reference`, `original_txn_id`, `executed_ts` | `transaction` | C11 transaction → batch; C12 (D07) reversal validity; RC4 1:1; C09 load allocation | Every card load, spend and refund belongs to one batch; refunds ≤ originals | Batch ID unknown → DQ12. Refund total > original → C12 `FAIL` (`OVER_REVERSED`). |
| IN-12 batch headers | `gross_amount`, `total_fees`, `total_adjustments`, `net_amount_reported`, `direction`, `expected_bank_reference`, `account_id` | `settlement_batch` | C11 (D04 batch → bank; D05 gross-to-net) | 88 batches, each matched by reference to one bank entry with equal signed amount | No entry with the reference: C11 `FAIL` (`REF_MISMATCH` / batch unsettled). Equations fail: C11 `FAIL` (`BATCH_DIFF`). |
| IN-13 batch lines | `line_type`, `txn_id`, `fee_code`, `amount`, `dc_indicator` | `settlement_line` | C11 (D05): Σ TXN lines = gross, Σ FEE lines = fees, Σ REFUND lines = adjustments, Σ signed lines = signed net | All equations hold | Missing fee lines while the header shows fees: `BATCH_DIFF` (spec S06b). The cause cannot be set to "fee" without lines. |
| IN-14 discrepancy log | `recon_ref`, `cause_category`, `cause_evidence_ref`, `funding_reference`, `status` | evidence for `exception_event` context | C06, C08 (investigation and funding evidence) | Header only, consistent with zero differences | File missing: C06 and C08 cannot show investigation evidence for any difference. With no differences in the clean demo, this gives `INSUFFICIENT_EVIDENCE` for the "log provided" checklist item only. |
| IN-15, IN-16 letters | Key details: letter reference, account name, masked number, currency | `evidence_document` + `extracted_field` | C10 | Each safeguarding account has a confirmed letter whose reference and account number match IN-02 | Missing: C10 `FAIL` (`MISSING_DESIGNATION`) for that account. Extracted values unconfirmed: DQ17, unusable until a reviewer confirms. |
| IN-17 policy | Key details: point, method, frequency, basis | `extracted_field` → `reporting_period.reconciliation_point_local`, `asset_pool` attributes | C03 (R03); method check | Point 17:00 confirmed; method `STANDARD`; per-currency basis | Missing or unconfirmed: C03 `INSUFFICIENT_EVIDENCE`. Every point-dependent check (DQ21) is then blocked. |
| IN-18 governance | Key details: accountable person, allocation date | `extracted_field` | C16 (checklist) | `PASS` (present) | Conditional: absent → C16 governance item `INSUFFICIENT_EVIDENCE`. Not part of the three scenario expectations. |
| IN-19 receipt | Key details: period, due date, submission timestamp | `extracted_field` | C16 (checklist: submitted ≤ 15 business days after month end, SUP 16.14A.3R) | `PASS`: submitted 17 Sep; due 21 Sep 2026 | Conditional, as for IN-18. |

## 2. How the inputs support each required area

**Reporting period and recon-day completeness.**
- IN-01 defines the expected scope.
- RC7 then checks that each recon day has exactly one IN-05 row per currency, one IN-06 row per safeguarding account, one IN-07 row per safeguarding account, and one IN-08 header per account.
- Controls: C01, C07, C14. A missing record yields a finding, never zero.

**Requirement calculation** (RC1, C04; CASS 15.8.30R, 15.8.33R, 15.8.34G).
- requirement(d, c) = Σ max(0, IN-03.balance for d, c) + Σ IN-04.amount where currency = c, `receipt_ts` ≤ point(d), and `allocated_ts` is blank or later than point(d).
- This is compared with IN-05 `requirement_reported`.

**Resource calculation** (RC1, C05; CASS 15.8.15R, 15.8.26R).
- item A(d, c) = Σ signed IN-10 entries for the safeguarding account in currency c with `posted_ts` ≤ point(d), including the opening row.
- resource = A + B + C + D, where B, C and D come from IN-05 as reported. They are 0.00 in the baseline. **No independent source exists for B–D** (gap G-S04).
- This is compared with IN-05 `resource_reported` and `item_a`.

**Bank statement and confirmation comparison** (RC2, C07, C08; CASS 15.8.47R).
- recomputed difference(d, account) = IN-07 normalised balance − IN-10 ledger roll-forward at the point.
- Both must also agree with the IN-06 reported values.
- The comparison is made in one currency only.
- DQ22 and DQ23 continuity tie IN-07 and IN-08 to IN-09.

**Transaction to settlement to bank entry** (C11, D04).
- IN-11 `settlement_batch_id` → IN-12 → IN-12 `expected_bank_reference` = IN-09 `bank_reference`.
- IN-13 `txn_id` provides the reverse link.
- Bank-transfer loads and redemptions use IN-11 `payment_reference` = IN-09 `end_to_end_ref` (RC4).

**Gross-to-net and fees** (C11, D05).
- IN-13 lines are checked against IN-12 totals.
- AQ batch: Σ load lines − Σ fee lines = net = IN-09 credit.
- Same-day top-up: IN-09 `TOPUP-*` credit = Σ fee lines, corroborated by an `OWN-*` debit with the same reference in IN-09 and an `OWN_FUNDS_TOPUP` row in IN-10.

**Currency-specific external reconciliation** (C13, DQ15).
- Every computation is keyed by currency.
- Any rule input set spanning two currencies aborts with DQ15. There are no FX tables.

**Missing-evidence detection** (RC7, DQ18).
- The expected scope comes from IN-01 × IN-02.
- Presence is checked by ID: `statement_id`, `recon_run_id`, `ext_recon_id`.

**Provenance and row citations.**
- Every canonical record carries `evidence_id`, `source_row_ref` and `ingested_at`.
- Every `control_result` lists `input_evidence_ids`.
- Every finding and pack sentence cites `(evidence_id, source_row_ref)`.

## 3. Checks that need more than one file to pass

| Check | Files that must all be present |
| --- | --- |
| C04 requirement | IN-01, IN-03, IN-04, IN-05, IN-17 (point) |
| C05 resource | IN-01, IN-10, IN-05, IN-17 |
| C07 external | IN-01, IN-02, IN-06, IN-07, IN-10 |
| C11 settlement | IN-09, IN-11, IN-12, IN-13 |
| C10 designation | IN-02, IN-15, IN-16 |

## 4. Unresolved items that affect this matrix

| ID | Item | Effect |
| --- | --- | --- |
| G-S01 | IN-10 cash book is a proposed entity, not in the spec | Without approval, C05 can only compare reported values with themselves. **Approval required before generation.** |
| G-S04 | No independent source for resource items B–D | Accepted as reported 0.00 in v1; marked "not independently verified" in output |
| G-S05 | Exception grouping rule (one exception per root cause across days vs one per day) | Affects expected exception counts in scenario 3. v1 proposes one per root cause (mutation plan §4). |
| G-S06 | Whether a difference with no IN-14 log entry is a separate finding | v1: not a separate exception; recorded as missing investigation evidence inside the main exception |
| G-S07 | DQ outputs vs exceptions | v1: DQ results are data-quality findings attached to the related exception, not separate exceptions, unless the spec scenario lists them |
