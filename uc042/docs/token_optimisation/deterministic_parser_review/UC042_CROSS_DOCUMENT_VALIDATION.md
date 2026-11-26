# UC-042: Cross-Document Validation

**What this is.** The relationships between the 19 documents that the current code enforces, verified in `p10/uc042_token_optimisation/uc042lib/validate.py` (class `Validator`, functions `_group_exceptions` and `_correlate_exceptions`) and in `uc042app/services/monthly.py` on 18 Nov 2026.

**When the checks run.** Three relationships (P1–P3) are checked at the **ZIP gate**, before Submit. Every other relationship is checked in the **engine** after Submit for Audit, and a failure produces a FAIL or INSUFFICIENT_EVIDENCE result plus an exception in the pack. A failing relationship never stops the pack from being built.

**How to read the outcomes:**

| Outcome | Meaning |
|---|---|
| **FAIL** | The evidence contradicts itself. |
| **INSUF** | INSUFFICIENT_EVIDENCE: a needed record is missing or was excluded as invalid, so the check could not be assessed (`Validator.tainted`, `evidence_gap`, `gate` with `schema.DEPENDS`). |

"P" means the period point: the policy reconciliation point (17:00 Europe/London) on the reconciliation day (`Validator.point`).

---

## 1. Checked at the ZIP gate (parsing stage)

| # | Relationship | Documents | Rule | Code | On failure |
|---|---|---|---|---|---|
| P1 | Letter slot | IN-15/IN-16 ↔ IN-02 (same ZIP) | `Letter reference` must equal `acknowledgement_letter_ref` of the IN-02 row for `SGA-GBP-01` (→IN-15) or `SGA-EUR-01` (→IN-16) | `MonthlyService._resolve_letters(independent=True)`, `schema.LETTER_SLOTS` | `LETTER_NOT_MATCHED` ERROR → gate fails |
| P2 | Calendar period | IN-01 ↔ selected period | Every `period_id` equals `PER-YYYY-MM` | `analysis.analyse_csv` | `WRONG_PERIOD` ERROR |
| P3 | Policy applicability | IN-17 ↔ period | A registered version that applies to the period | `analysis.analyse_policy`, `policy.applicability` | `POLICY_NOT_APPLICABLE` ERROR |

The gate also flags the following as WARNING or INFO only, without blocking:
- dates of other records outside the month;
- calendar days missing or duplicated against the England and Wales calendar.

---

## 2. Checked by the engine (downstream reconciliation)

### 2.1 Scope and coverage (calendar × account inventory)

The scope is set by IN-01 rows with `is_recon_day=true` (`recon_days`). IN-01 and IN-02 are **scope files**: one invalid row makes the whole file unusable (`schema.SCOPE_FILES`).

| Check | Expected per reconciliation day | Matching fields | When absent | When duplicated |
|---|---|---|---|---|
| C01-COVER | One IN-05 record per safeguarding currency (the currencies of the `RELEVANT_FUNDS_BANK` accounts) | `(recon_date, currency)` | **FAIL** (`MISSING_RECON`) | FAIL "duplicate records" |
| C07-COVER | One IN-06 record per safeguarding account | `(recon_date, account_id)` | **FAIL** (`MISSING_EXT_RECON`) | FAIL |
| C14-COVER IN-03 | One snapshot per (currency, client). The client list is every `client_id` seen in IN-03 for that currency. | `(recon_date, currency, client_id)` | INSUF (`MISSING_SNAPSHOT`) | FAIL |
| C14-COVER IN-12 | **Exactly one `SCHEME` and one `ACQUIRER` batch** per safeguarding currency | `(settlement_date, currency, counterparty_type)` | INSUF (`MISSING_BATCH`) | FAIL |
| C14-COVER IN-07 | One 17:00 confirmation per safeguarding account | `(as_at_ts date, account_id)` | INSUF (`MISSING_BANK_EVIDENCE`) | FAIL |
| C14-COVER IN-08 | One EOD statement per **every** IN-02 account (own-funds accounts included) | `(statement_date, account_id)` | INSUF | FAIL |

`Validator.check_coverage` / `_cover`.

### 2.2 Bank statements

| Check | Documents | Rule |
|---|---|---|
| DQ23-STATEMENT | IN-08 ↔ IN-09 (`IN-09.statement_id` = `IN-08.statement_id`) | `entry_count` = number of entries.<br>Signed opening + Σ signed entries = signed closing (bank sign: C+, D−).<br>Each entry's `account_id`, `currency` and `booking_date` equal the statement's. |
| DQ22-CONTINUITY | IN-08 day to day; IN-08 ↔ IN-10 | For each safeguarding account, the first statement's signed opening equals the cash-book `OPENING_BALANCE` (cash-book sign D+). For every account, each statement's opening equals the previous statement's closing. A reconciliation day with no statement in between gives INSUF. |
| BC-VS-EOD | IN-07 ↔ IN-08 ↔ IN-09 | The confirmation's signed balance equals the same day's EOD opening plus the entries with `booking_ts` ≤ the confirmation's `as_at_ts` |
| C03-POINT | IN-05, IN-03, IN-07 ↔ IN-17 | `IN-05.reconciliation_point_ts` and `IN-03.as_at_ts` equal P for their `recon_date`; the local clock time of `IN-07.as_at_ts` is the policy time |

Code: `check_statements`, `check_policy_and_points`.

### 2.3 Cash book and bank, linked by reference only

| Check | Rule |
|---|---|
| CASH-BANK-LINK | Each IN-10 row except `OPENING_BALANCE` needs **exactly one** IN-09 entry with the same `account_id` and with `bank_reference` or `end_to_end_ref` equal to `payment_reference`. The signed amounts must be equal (bank C ↔ cash D) and the currencies equal. None → FAIL `UNMATCHED_CASHBOOK_ENTRY`, or INSUF if the bank evidence is missing. More than one → FAIL. |
| BANK-CASH-LINK | Each IN-09 entry on a safeguarding account needs an IN-10 row whose `payment_reference` is its `bank_reference` or `end_to_end_ref`. None → FAIL `UNMATCHED_BANK_ENTRY`. |

Code: `check_cashbook_bank_links`. An equal amount is **never** treated as a link [TEST `test_baseline.ChecksCanFail.test_equal_amount_is_not_a_link`].

### 2.4 Internal reconciliation (per IN-05 row: day × currency)

| Check | Recomputation | Compared with |
|---|---|---|
| C04-REQUIREMENT | Σ max(0, `IN-03.balance`) for that `recon_date` and currency, **plus** Σ `IN-04.amount` for receipts of that currency open at P (`receipt_ts` ≤ P and (`allocated_ts` blank or > P)) | `requirement_reported` |
| C05-RESOURCE | Item A = Σ signed IN-10 rows of the safeguarding account in that currency with `posted_ts` ≤ P, including `OPENING_BALANCE` (D+, C−); resource = A + `item_b` + `item_c` + `item_d` (B–D taken as reported) | `item_a` and `resource_reported` |
| C06-DIFFERENCE | resource − requirement | `difference_reported`. Equal and 0.00 → **PASS** (rule approved 17 Nov 2026). Equal and non-zero → FAIL (`INTERNAL_DIFFERENCE`). Unequal → FAIL. |

Code: `check_internal`, `ledger_at`.

### 2.5 External reconciliation (per IN-06 row: day × safeguarding account)

| Check | Rule |
|---|---|
| C07-BANK-EVIDENCE | `IN-06.bank_statement_id` → the IN-07 row with that `statement_id`. Account, currency (also equal to the IN-02 currency) and date must match, and the signed IN-07 balance must equal `bank_balance_reported`. Not found → INSUF. |
| RC2-LEDGER | Cash book at P (as for item A) = `ledger_balance_reported` |
| C08-DIFFERENCE | bank − ledger vs `difference_reported`. Zero and equal → PASS. Otherwise FAIL, with a timing assessment (E1): linked IN-10/IN-09 pairs on either side of P that clear by the next business day give `TIMING_EVIDENCED` or `TIMING_PARTIAL`. These **never** change the outcome. |
| DISC-LOG | A C08 failure group (consecutive reconciliation days, same account, same amount) needs an IN-14 row whose `recon_ref` = `ERL-<account_id>-<YYYYMMDD>` for one of the days in the group. Logged → PASS. Not logged → FAIL. An entry logged after the period end is kept and labelled. No C08 failure and a usable IN-14 → PASS "header-only log is consistent". |

Code: `check_external`, `timing_items`, `timing_assessment`, `_group_exceptions`.

**Hidden contracts (enforced by code, not described in `schema.py`):**
- **H1.** `recon_ref` must have the form `ERL-<account_id>-<YYYYMMDD>`. Through the IN-14 period rule (`PERIOD_RULES["IN-14"]["event_ref"]`), it must also exist as an `IN-06.ext_recon_id` (or an `IN-05.recon_run_id`) with an in-period `recon_date`. Otherwise the log row is excluded as out of period.

  **Practical consequence:** `ext_recon_id` must be `ERL-<account_id>-<YYYYMMDD>`.
- **H2.** IN-14 `logged_ts` must not be before the referenced reconciliation's date.

### 2.6 Settlement

| Check | Rule |
|---|---|
| C11-BATCH-ARITH | Per IN-12 batch, using IN-13 lines with the same `batch_id`:<br>• Σ TXN lines = `gross_amount`;<br>• Σ FEE lines = `total_fees`;<br>• Σ REFUND lines = `total_adjustments`;<br>• Σ signed lines (C+, D−) = signed net (`TO_FIRM` +, `FROM_FIRM` −);<br>• every line's currency = the batch currency;<br>• every TXN/REFUND line's `txn_id` exists in IN-11 with `settlement_batch_id` = this batch and an identical `amount` string. |
| C11-BATCH-BANK | Exactly one IN-09 entry with (`account_id`, `bank_reference`) = (batch `account_id`, `expected_bank_reference`); signed bank amount = signed net; same currency. A booking lag is informational only. |
| C11-TXN-LINE | Every IN-11 `LOAD_CARD` / `SPEND` / `REFUND` must be in exactly one IN-13 line of its `settlement_batch_id`, and that batch must exist |
| C11-BANK-ENTRY | Every safeguarding IN-09 entry is explained by one of:<br>• an IN-12 (`account_id`, `expected_bank_reference`);<br>• an IN-11 `payment_reference` = its `end_to_end_ref`;<br>• an IN-04 `bank_reference` = its `end_to_end_ref`;<br>• an IN-10 `OWN_FUNDS_TOPUP` `payment_reference` = its `bank_reference`.<br>Otherwise FAIL `UNMATCHED_BANK_ENTRY`. |
| FUND-TOPUP | For each batch with `total_fees` > 0, reference `TOPUP-<CCY>-<YYYYMMDD of settlement_date>` (hidden contract H3):<br>• exactly one IN-09 **C** entry on the batch account, booked on the settlement date;<br>• exactly one IN-09 **D** entry on an `OWN_FUNDS` account;<br>• one IN-10 `OWN_FUNDS_TOPUP` row;<br>• all three equal to `total_fees`. |

Code: `check_settlement`, `check_unmatched_bank_entries`, `check_topups`.

### 2.7 Client money

| Check | Rule |
|---|---|
| RC4-DIRECT | Each IN-11 `LOAD_BANK` (bank **C**) / `REDEMPTION` (bank **D**) needs exactly one safeguarding IN-09 entry with `end_to_end_ref` = `payment_reference`, the same amount and the same currency. A reference that belongs to a receipt received before the period start gives NOT_APPLICABLE. |
| C09-ALLOCATION | Each IN-04 receipt:<br>• exactly one safeguarding IN-09 entry with `end_to_end_ref` = `bank_reference`, the same amount and currency;<br>• if allocated: allocation date ≤ next England and Wales business day after `receipt_date`, and exactly one IN-11 `LOAD_BANK` with `payment_reference` = `bank_reference` and the **same `client_id`** (17 Nov rule; execution time may differ);<br>• if not allocated: FAIL when the due date ≤ period end. |
| C12-REFUND | Each `REFUND`: `original_txn_id` exists in IN-11 with the same currency and client; cumulative refunds ≤ the original amount |
| CBAL-NONNEG | Every IN-03 balance ≥ 0 |
| CBAL-ROLLFWD | For each (currency, client) and consecutive snapshot days: previous balance + Σ signed IN-11 (CR+, DR−) with previous P < `executed_ts` ≤ current P = current balance. The opening boundary snapshot (previous month-end 17:00) starts the chain. |

Code: `check_direct_and_allocation`, `check_refunds`, `check_client_rollforward`.

### 2.8 Currency, designation and checklist

| Check | Rule |
|---|---|
| C13-CURRENCY | IN-06/07/08/09/10/12 `currency` = the currency of their `account_id` in IN-02; IN-13 and IN-11 (with a batch) `currency` = the batch currency |
| C10-DESIGNATION | For each safeguarding account, its letter's `Letter reference`, `Account number`, `Currency` and `Account name` equal IN-02 `acknowledgement_letter_ref`, `account_number_masked`, `currency` and `designation_name`; `designation_name` contains `Safeguarding`; `Letter date` ≤ period end |
| C03-POLICY | IN-17 `Reconciliation method` = `STANDARD` and `Internal reconciliation basis` = `Per currency` |
| C16-GOVERNANCE | Optional IN-18: `Accountable person` non-empty; `Allocated from` ≤ period end |
| C16-RETURN | Optional IN-19: `Period` = previous month; `Submitted at` ≤ due date; `Due date` = 15th business day after the previous month end |

Code: `check_currency_isolation`, `check_designation`, `check_policy_and_points`, `check_checklist`.

---

## 3. Relationships asked about but NOT enforced

| Relationship | Status |
|---|---|
| IN-03 `client_id` must exist in some master list | **Not enforced.** No client master file exists; the client list is whatever IN-03 contains. |
| IN-11 `client_id` must appear in IN-03 | **Not enforced directly.** A transaction for an unknown client affects no roll-forward. It is caught only indirectly (C09 client match). |
| IN-03 / IN-05 `asset_pool_id` consistency with IN-02 | **Not enforced** (type check only) |
| IN-02 `currency` vs letter `Institution` / IN-02 `institution_full_name` | `Institution` **not compared** |
| IN-07 confirmation vs IN-06 `ledger_balance_reported` | Indirect only, through C08 |
| IN-12 `cycle_date`, IN-09 `value_date`, IN-11 `auth_ts`/`clearing_date` | **Not used** (`schema.PERIOD_UNCHECKED`) |
| IN-11 `status` (SETTLED/EXECUTED) | Enumeration only; no rule depends on it |
| IN-14 amount vs the C08 difference | **Not compared.** Only the reference is linked. |
| Internal vs external reconciliation (IN-05 vs IN-06) | **No direct comparison.** Both derive from IN-10 at the same point. |
