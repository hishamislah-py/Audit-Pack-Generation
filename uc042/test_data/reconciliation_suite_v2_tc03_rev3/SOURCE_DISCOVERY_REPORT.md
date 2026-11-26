# UC-042 Reconciliation Test Suite V2: Source Discovery Report (Stage A)

- **Prepared:** 23 Nov 2026.
- **Status:** read-only discovery. No engine, Smart Parser, Ringfence or scenario file was modified, and no engine or application run was made.

Every statement below is labelled with one of three tags:

- **EXISTING (verified in source):** I read the code path myself in this task.
- **EXISTING (executed by others):** an earlier recorded run demonstrated it. I did not re-run it here.
- **NOT VERIFIED:** inferred or not inspected.

## 1. Resources inspected

| # | Resource | Path | How used |
|---|---|---|---|
| R1 | Current shared engine, read-only copy | `C:\u42v\e2e_20261122\engine_base\uc042\uc042lib\` | Read `schema.py`, `money.py`, `structure.py` (row checks) and `validate.py` (all 1,717 lines). Its README says it is a byte-identical copy of `C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\src\uc042\uc042lib`. |
| R2 | Handoff repository engine | `Downloads\UC042_CLAUDE_CODE_HANDOFF\uc042\uc042lib\` | Hashed it against R1: identical except `validate.py` and `runtime_paths.py`. The diff shows the handoff `validate.py` predates the 17 Nov 2026 rules (zero difference = NOT_APPLICABLE; older C09 allocation-transaction rule). **R1 is the reference for this suite.** |
| R3 | Scenario generator | R1 `scenarios.py` | Reviewed the mutation operations (`delete_record`, `set_field` with old-value guard, `add_record`) and the 9 frozen scenario definitions. |
| R4 | AI investigation layer | R2 `uc042lib\investigation\routing.py`, `packet.py`, `validation.py` | Searched for how investigation groups and candidates are handled. |
| R5 | Clean baseline dataset | `Downloads\UC042_CLAUDE_CODE_HANDOFF\uc042\uc042_dataset\set_01_clean_baseline\` | Read `manifest.csv`, `GENERATION_NOTES.md` and every CSV. The manifest SHA-256 matches the copy under `C:\u42x\...` (read-only hash). |
| R6 | Derived field reference | `Downloads\UC042_SCHEMA_AND_FIELD_REFERENCE.md` (18 Nov 2026) | Used as an index only. Every fact used below was re-checked against R1. |
| R7 | Ringfence scenario library | `Downloads\Ringfence_Scenario_Library\` | Read the M3 `scenario.json`, `expected_outcome.json` and ZIP listing, and the RF-DEMO-04 `correction_provenance.json`. Used for packaging and correction conventions. |
| R8 | Live E2E environment brief | `C:\u42v\e2e_20261122\E2E_ENVIRONMENT_BRIEF.md` | Identified the canonical engine copy and the protected paths. |

**Protected locations never written:** `C:\u42x`, `p10\*`, `C:\u42v\checkpoint_CP1`, `C:\u42v\e2e_20261122\*` (read only), port 8780 (not touched), the Downloads originals, and every existing scenario bundle.

## 2. Canonical input schemas (IN-01 to IN-14)

**Source:** R1 `schema.CSV_FILES`. It is the single file contract shared by the generator, the validator and the data dictionary.

**Header rule.** The header must equal the schema column list exactly: same names, order and case, with no aliases.

**Primary key.** The first column is the key. A later duplicate key is excluded and reported as **DQ09**.

| ID | September file name | Key | Columns used by this suite (type) |
|---|---|---|---|
| IN-01 | `recon_calendar_2026-09.csv` | calendar_date | is_recon_day (bool). 22 reconciliation days in Sep 2026. |
| IN-02 | `account_inventory.csv` | account_id | SGA-GBP-01 and SGA-EUR-01 (RELEVANT_FUNDS_BANK); OWN-GBP-01 and OWN-EUR-01 (OWN_FUNDS). |
| IN-03 | `client_balance_snapshots_2026-09.csv` | snapshot_id `CBS-<yyyymmdd>-<client>-<ccy>` | recon_date (date), client_id (id), balance (signed). |
| IN-04 | `unallocated_register_2026-09.csv` | receipt_id `UR-nnnn` | bank_reference (str), receipt_ts (ts), amount (amount), classification (enum UNALLOCATED/UNIDENTIFIED), allocated_ts and client_id (both conditional). May be empty. |
| IN-05 | `internal_recon_records_2026-09.csv` | recon_run_id `IRR-EMONEY-<ccy>-<yyyymmdd>` | requirement_reported, resource_reported, item_a, difference_reported (all signed). |
| IN-06 | `external_recon_records_2026-09.csv` | ext_recon_id `ERL-<acct>-<yyyymmdd>` (hidden contract used by DISC-LOG) | ledger_balance_reported, bank_balance_reported, difference_reported (signed); timing_difference_claimed (bool). |
| IN-07 | `bank_balance_confirmations_2026-09.csv` | statement_id `ST-<acct>-<yyyymmdd>-1700` | balance_amount (amount), balance_dc_indicator (C/D). |
| IN-08 | `bank_statements_eod_2026-09.csv` | statement_id `ST-<acct>-<yyyymmdd>-EOD` | opening/closing_balance_amount and their dc indicators; entry_count (int). |
| IN-09 | `bank_statement_entries_2026-09.csv` | bank_entry_id `BE-<ccy>-<mmdd>-<code>` | booking_ts (ts), amount, dc_indicator (C = in), bank_reference, end_to_end_ref. |
| IN-10 | `sga_cashbook_entries_2026-09.csv` | ledger_entry_id `LE-<ccy>-<mmdd>-<nnnn>` | posted_ts, entry_type (enum of 7), amount, dc_indicator (D = in), payment_reference. |
| IN-11 | `transactions_2026-09.csv` | txn_id `TX-<mmdd>-<nnnnn>` | txn_type (enum), executed_ts, amount, direction (CR/DR), settlement_batch_id, payment_reference, original_txn_id (all three conditional). |
| IN-12 | `settlement_batches_2026-09.csv` | batch_id `AQ-/SB-<ccy>-<yyyymmdd>` | cycle_date, settlement_date, direction, gross, fees, adjustments, net, expected_bank_reference. |
| IN-13 | `settlement_lines_2026-09.csv` | line_id `SL-<batch>-<nnnn>` | line_type (TXN/FEE/REFUND), txn_id, amount, dc_indicator (C = to firm). |
| IN-14 | `discrepancy_log_2026-09.csv` | discrepancy_id | logged_ts, recon_ref (IN-05/IN-06 key), amount, cause_category (enum with **no allowed-value list**), status (OPEN/RESOLVED). May be empty. |

**PDFs.** IN-15 to IN-19 are reused unchanged from the baseline. No scenario in this suite touches them.

**Field formats** (R1 `structure.field_error`):

| Type | Format |
|---|---|
| amount | `^\d+\.\d{2}$` |
| signed | `^-?\d+\.\d{2}$` |
| date | `YYYY-MM-DD` |
| ts | ISO 8601 with an explicit offset |
| bool | `true` or `false` |
| id | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` |
| ccy | GBP or EUR only |

**Sign conventions** (R1 `money.py`):

| Source | Positive indicator |
|---|---|
| Bank | C = + |
| Cash book | D = + |
| Client transactions | CR = + |
| Settlement lines | C = + |
| Batch net | TO_FIRM = + |

Amounts are compared exactly as Decimal, with no tolerance.

## 3. Identifiers and reference relationships (EXISTING, verified in source)

| Link | Keys used | Engine check |
|---|---|---|
| Cash book ↔ bank | IN-10.payment_reference = IN-09.bank_reference or end_to_end_ref, same account | CASH-BANK-LINK, BANK-CASH-LINK |
| Direct client transaction ↔ bank | IN-11.payment_reference (LOAD_BANK/REDEMPTION) = IN-09.end_to_end_ref | RC4-DIRECT (control C09) |
| Batch ↔ bank | IN-12.expected_bank_reference = IN-09.bank_reference, same account | C11-BATCH-BANK |
| Batch ↔ lines ↔ transactions | IN-13.batch_id → IN-12; IN-13.txn_id → IN-11 (amount and batch must agree) | C11-BATCH-ARITH, C11-TXN-LINE |
| Top-up | Reference `TOPUP-<ccy>-<yyyymmdd>` on the SGA credit, the own-funds debit and the cash book | FUND-TOPUP |
| Unallocated receipt ↔ bank / allocation | IN-04.bank_reference = IN-09.end_to_end_ref; allocation = LOAD_BANK with the same payment_reference | C09-ALLOCATION |
| Bank entry explained | Batch reference, transaction end-to-end reference, register reference or top-up reference | C11-BANK-ENTRY |
| Discrepancy log ↔ difference | IN-14.recon_ref = `ERL-<acct>-<yyyymmdd>` of a C08 difference day | DISC-LOG |
| Client roll-forward | IN-03 previous snapshot + IN-11 movements in (point d-1, point d] = IN-03 snapshot | CBAL-ROLLFWD |

## 4. Reconciliation calculations (EXISTING, verified in source, R1 `validate.py`)

| Check | Calculation |
|---|---|
| C04-REQUIREMENT | Σ max(0, client balance at d) + open unallocated receipts at the 17:00 point, compared with IN-05.requirement_reported |
| C05-RESOURCE | Item A = signed sum of cash-book rows posted at or before 17:00 (including OPENING_BALANCE). Items B–D are taken as reported and not verified (gap G-S04). |
| C06-DIFFERENCE | Recomputed resource − requirement vs reported. A non-zero difference FAILs even when it is correctly reported (CASS 15.8.50R wording). Zero = PASS (approved 17 Nov 2026). |
| C07-BANK-EVIDENCE / RC2-LEDGER / C08-DIFFERENCE | Bank 17:00 confirmation vs reported; ledger recomputed vs reported; bank − ledger vs reported. A non-zero difference FAILs. |
| E1 timing evidence (`timing_items`, `timing_assessment`) | Only for C08. A cash-book and bank pair linked by reference with equal signed amount, where one side falls before and the other after the point. It counts as evidence only if cleared within **one business day (D1)** and the clearing evidence is usable and in period. Outcomes: `TIMING_EVIDENCED`, `TIMING_PARTIAL`, `TIMING_UNVERIFIABLE`, `NOT_EVIDENCED`. **It never changes the outcome and never resolves the exception.** |
| C11-BATCH-BANK | Reports the booking lag in business days as information only (D-E1b). |
| C09-ALLOCATION | Allocation deadline is the next business day after receipt. A receipt still open at the period end passes if its deadline falls after the period. |

## 5. Exception structure and severity (EXISTING, verified in source)

- **One exception per root cause** (`_group_exceptions`).
- **C08 grouping.** C08 FAILs on contiguous reconciliation days, for the same account, with the same recomputed difference, form one `BANK_LEDGER_DIFFERENCE|<acct>|<first day>|<amount>`.
- **C06 FAILs** become `INTERNAL_DIFFERENCE|<day>/<ccy>`, one per day.
- **Anything else** becomes `<check_id>|<scope>`. Linked records use `UNMATCHED_BANK_ENTRY|<id>` and `UNMATCHED_CASHBOOK_ENTRY|<id>`.

**Severity** (`SEVERITY`):

- **Critical:** MISSING_BANK_EVIDENCE, BANK_LEDGER_DIFFERENCE, INTERNAL_DIFFERENCE, MISSING_RECON, MISSING_EXT_RECON, MISSING_FILE, EMPTY_FILE, INVALID_FILE, AMBIGUOUS_FILE, WRONG_PERIOD.
- **High:** INVALID_ROWS, OUT_OF_PERIOD_ROWS, and **every other kind by default**.

**Exception ID** is `EXC-<scenario_id>-NN`, numbered after sorting by (severity rank, first_date, root_cause). `scenario_id` comes from `scenario.json` in the case root, or `CASE` if absent. Ringfence-assigned identifiers were **not verified** for this suite.

**Flags:**

- `OWN_FUNDS_REQUIRED`: a negative bank-ledger difference.
- `NO_INVESTIGATION_LOGGED`: DISC-LOG FAIL.
- `INVESTIGATION_RECORDED_AFTER_PERIOD_END`.

**Case status:**

| Status | Condition |
|---|---|
| CLEAN | Nothing failed and nothing lacks evidence |
| EVIDENCE_INCOMPLETE | Any required file unavailable, or any INSUFFICIENT_EVIDENCE result |
| EXCEPTIONS_OPEN | Evidence complete, at least one FAIL |

**Correlation (`_correlate_exceptions`, deterministic-v1).** Groups never set a cause or close anything.

| Link | What it connects |
|---|---|
| L1 REFERENCE | Exceptions that share an (account, reference) taken from C11-BATCH-BANK, C11-BATCH-ARITH, CASH-BANK-LINK, C11-BANK-ENTRY or BANK-CASH-LINK results |
| L2 PERSISTENCE | Equal INTERNAL_DIFFERENCE values on consecutive reconciliation days |
| L3 LINEAGE (a) | A BANK_LEDGER_DIFFERENCE and an exception whose bank entry is booked inside that day's 17:00 balance |
| L3 LINEAGE (b) | An INTERNAL_DIFFERENCE or C04-REQUIREMENT and **any** CBAL-ROLLFWD failure for the same currency and date |
| L3 LINEAGE (c) | An INTERNAL_DIFFERENCE and the C04-REQUIREMENT for the same scope |

**Candidates.** `DATE_AND_AMOUNT_COINCIDENCE` is produced only between a C11-BATCH-ARITH exception whose line references a missing transaction and a CBAL-ROLLFWD exception whose difference equals **that single line amount**. It is labelled UNVERIFIED.

## 6. Control definitions

`validate.CONTROL_OF` maps 29 check IDs to controls:

| Control | Check IDs |
|---|---|
| C01 | C01-COVER |
| C03 | C03-POLICY, C03-POINT |
| C04 | C04-REQUIREMENT, CBAL-NONNEG, CBAL-ROLLFWD |
| C05 | C05-RESOURCE |
| C06 | C06-DIFFERENCE, FUND-TOPUP |
| C07 | C07-COVER, BC-VS-EOD, C07-BANK-EVIDENCE, RC2-LEDGER |
| C05/C07 | CASH-BANK-LINK, BANK-CASH-LINK |
| C08 | C08-DIFFERENCE |
| C06/C08 | DISC-LOG |
| C09 | RC4-DIRECT, C09-ALLOCATION |
| C10 | C10-DESIGNATION |
| C11 | C11-BATCH-ARITH, C11-BATCH-BANK, C11-TXN-LINE, C11-BANK-ENTRY |
| C12 | C12-REFUND |
| C13 | C13-CURRENCY |
| C14 | C14-COVER |
| DQ22 | DQ22-CONTINUITY |
| DQ23 | DQ23-STATEMENT |

Data-quality checks: V00-FILE, V01-SCHEMA, V01-PDF, DQ-FIELD, DQ-PERIOD. Optional evidence: C16-GOVERNANCE, C16-RETURN.

**This suite uses only these existing check IDs.** It defines no new control ID. Where a desired behaviour has no check, the scenario says so and marks the expectation `PENDING`.

## 7. AI investigation layer (R4)

| Status | Finding |
|---|---|
| EXISTING, verified in source | Routing is per exception, from the root-cause kind: `bank_ledger_mismatch`, `settlement_discrepancy`, `customer_balance_discrepancy`, `unmatched_bank_entry`, `unverified_relationship`, `missing_bank_evidence`, `insufficient_evidence` and `generic`. |
| EXISTING, verified in source | The investigation packet carries the exception's deterministic group and any UNVERIFIED candidates. The output validator rejects any finding that cites a candidate as confirmed evidence. |
| NOT VERIFIED / not found | A group-level or cross-exception "common cause" or "independent causes" conclusion. Investigation runs per exception. |
| EXISTING, executed by others (memory of 20–22 Nov runs) | Live AI investigations (OpenAI) for financial exceptions produced findings, analyst decisions and a verified PDF in an isolated environment. Ringfence auto-queues one live investigation per exception after pack generation, so running these scenarios there would make one live call per exception. |

## 8. Reference datasets (existing frozen scenarios)

These are reference examples only. Their keys were matched by earlier engine runs (EXISTING, executed by others: 11/11 on 20 Nov and 12/12 on 22 Nov per the earlier session record). Each one demonstrates one path. None proves a control independently.

| Dataset | Demonstrates | Relevance |
|---|---|---|
| SC2 | In-period settlement timing, TIMING_EVIDENCED | Contrast for TC03 |
| SC3C | Short settlement, L1 + L3 group | Contrast for TC02 and TC05 |
| SC5A | One missing transaction, one UNVERIFIED candidate | Single-record precursor of TC05 |
| SC5C / SC5D | L2 persistence / L3 lineage | Mechanism behind the TC06 over-grouping prediction |
| S05 | Unmatched bank debit, L3 group | Mechanism mirrored by TC04 |

## 9. Baseline facts used by the scenarios (from R5, verified by reading the files)

- **Entity:** SYN-EMI-001.
- **Accounts:** at "Example Bank plc" (fictional).
- **Period:** PER-2026-09, with 22 reconciliation days. 1 Sep 2026 is a Tuesday. 28 Sep is a Monday, and 29 and 30 Sep are Tue/Wed.
- **Daily pattern:**
  - GBP and EUR bank loads (1:1, end-to-end reference).
  - Acquirer batches credited at 14:00.
  - Own-funds top-up at 14:30.
  - Scheme batches debited at 15:00.
  - Redemptions at 16:00.
- **Agreement:** bank = ledger and requirement = resource at every 17:00 point.
- **Natural legitimate repeats** (unchanged controls for TC01):
  - Four LOAD_CARD of £2,500.00 on 8 Sep for four different clients: `TX-0908-00003` to `TX-0908-00006`, each on its own line of AQ-GBP-20260908.
  - Two refunds equal to their originals: `TX-0909-0R001`/`TX-0902-00044` (60.00) and `TX-0916-0R001`/`TX-0903-00016` (284.02).
- **Baseline copy** in this workspace: `shared_baseline/`, 19 files. All SHA-256 match `manifest.csv` (checked 23 Nov 2026).
