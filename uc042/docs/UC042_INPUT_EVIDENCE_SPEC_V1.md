# UC-042 Input Evidence Specification — v1 (for review)

Status: **v1 — accepted as the reference scope for milestone 1 (clean baseline)**. Prepared 29 Oct 2026; milestone-1 decisions added 29 Oct 2026 (see section 0).

## 0. Milestone-1 decisions (clean baseline)

The decisions below were open in v1. They are now fixed as synthetic POC conventions for the first baseline. Everything else in this document is unchanged.

| # | Decision | Effect |
| --- | --- | --- |
| D1 | Monthly CSV per tabular source; every record keeps its own ID and date | As in section 3.3 |
| D2 | IN-10 cash book is included **only** as the independent ledger source for item A and the ledger side of the external comparison. Minimal schema: `ledger_entry_id`, `account_id`, `posted_ts`, `entry_type`, `amount`, `dc_indicator`, `currency`, `payment_reference` | `value_date`, `batch_id` and `txn_id` dropped from IN-10; the link to the bank is by `payment_reference` only |
| D3 | Raw `amount` plus indicator in, `amount_signed` derived by the rules in section 6, and unit-tested | — |
| D4 | One exception per root cause | Applies when scenarios are built |
| D5 | £812.40 difference persists 17–30 Sep | Applies when scenarios are built |
| D6 | Required: IN-01 to IN-17. Optional supporting evidence: IN-18, IN-19 | Section 3.1 "Conditional" now reads "Optional" |
| D7 | `balance_ref` dropped from IN-03 and IN-11 (one balance per client; unused by any check) | — |
| D8 | When a balance changes for safeguarding purposes. **This is the only question that affects calculation correctness.** Convention: a card load credits the client at `executed_ts`; a spend and a refund change the client balance at batch settlement (15:00, when funds are paid to or received from the scheme, CASS 15.8.33R(2)(a)); a redemption debits at bank execution | Fixes the client-balance roll-forward and the requirement at each 17:00 point |
| D9 | Business days = UK weekdays excluding UK bank holidays; in September 2026 these equal the reconciliation days | Used for the allocation deadline (CASS 15.2.5R) and the return due date |
Parent specification: *UC-042 Moorwand Audit Pack — Data Sources, Field Dictionary, Relationships and Synthetic Dataset Specification* (Claude Doc, revision 17, https://claude.ai/artifact/XUXetbP9hTZDfmsVQUPpSS). Referred to below as **the spec**.

Every format in this document is a **synthetic POC convention**. None is a verified Moorwand export format, field name or system. Moorwand's actual formats are unconfirmed (see `UC042_RESEARCH_GAPS.md`).

---

## 1. Summary

The clean demo uses **19 upload files**: 14 CSV exports and 5 PDFs. 17 are required and 2 are conditional. They cover September 2026 for one fictional EMI (`SYN-EMI-001`), one e-money asset pool (`POOL-EMONEY`) and four accounts (`SGA-GBP-01`, `SGA-EUR-01`, `OWN-GBP-01`, `OWN-EUR-01`).

The three demo scenarios (clean baseline; missing EUR bank evidence on 15 Sep; unexplained £812.40 GBP difference on 17 Sep) are expressed as record-level changes to these same 19 files. Scenario details are in `UC042_SCENARIO_MUTATION_PLAN.md`.

## 2. Principles applied

1. **Files are not entities.** One file may feed two canonical entities (IN-02 feeds `institution` and `safeguarding_account`). Several canonical entities are internal only and are never uploaded.
2. **Reported is not recomputed.** IN-05 and IN-06 carry the firm's *reported* reconciliation results as source evidence. The POC recomputes requirement, resource and differences from other inputs and stores them separately in `control_result`. Neither overwrites the other.
3. **Raw values are preserved.** Money arrives as an unsigned amount plus the source's own debit/credit indicator, exactly as the source states it. The POC derives `amount_signed` with a per-source normalisation function (section 6). The signed value is a canonical field and is never uploaded.
4. **Links come from keys, never amounts.** Cross-file links use identifiers or references carried by the source records. Equal amounts never create a link (spec §5, *Relationship rules*).
5. **Missing is missing.** An absent record produces `INSUFFICIENT_EVIDENCE`. It never produces zero and is never back-filled (spec §6, DQ01, RC7).
6. **One reporting month per file.** Daily evidence keeps its own identity through per-row IDs (for example one `statement_id` per account per day), so a missing day is still detected precisely. See section 3.3 for why this replaces the spec's daily files.

## 3. Upload-file inventory

### 3.1 Inventory

"Spec source" refers to the spec §3 source categories (S01–S20). "Evidence type" refers to the earlier research catalogue (E01–E18).

| File ID | Filename | Business purpose | Spec source / evidence type | Need | Format | Kind | Rows (baseline) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IN-01 | `recon_calendar_2026-09.csv` | Which days require reconciliation | S01 | Required | CSV | Raw source (configuration evidence) | 30 |
| IN-02 | `account_inventory.csv` | Institution and account register (CASS 10A.2.3R details) | S07 | Required | CSV | Raw source | 4 |
| IN-03 | `client_balance_snapshots_2026-09.csv` | Individual client balances at each 17:00 point | S02 / E04 | Required | CSV | Raw source | 264 (22 days × 12 clients) |
| IN-04 | `unallocated_register_2026-09.csv` | Receipts not yet allocated to a client | S03 / E05 | Required | CSV | Raw source | 2 |
| IN-05 | `internal_recon_records_2026-09.csv` | Firm's reported internal reconciliations | S04 / E01 | Required | CSV | Raw source (reported results) | 44 (22 × GBP, EUR) |
| IN-06 | `external_recon_records_2026-09.csv` | Firm's reported external reconciliations | S05 / E02 | Required | CSV | Raw source (reported results) | 44 (22 × 2 SGA accounts) |
| IN-07 | `bank_balance_confirmations_2026-09.csv` | Bank balance as at 17:00 per safeguarding account | S06 / E03 | Required | CSV | Raw source (third party) | 44 |
| IN-08 | `bank_statements_eod_2026-09.csv` | End-of-day statement headers (opening, closing, entry count) | S06 / E03 | Required | CSV | Raw source (third party) | 88 (22 × 4 accounts) |
| IN-09 | `bank_statement_entries_2026-09.csv` | Entries on each end-of-day statement | S06 / E03; S18 | Required | CSV | Raw source (third party) | ≈ 470 (fixed at generation) |
| IN-10 | `sga_cashbook_entries_2026-09.csv` | Firm's own ledger of safeguarding-account movements (item A) | **Gap: not in spec** (RC1 input "internal ledger balances of SGA accounts") | Required | CSV | Raw source | ≈ 370 + 2 opening rows |
| IN-11 | `transactions_2026-09.csv` | Client movements: loads, spends, redemptions, refunds | S09, S12 / E14, E16 | Required | CSV | Raw source | ≈ 420 (fixed at generation) |
| IN-12 | `settlement_batches_2026-09.csv` | Scheme and acquirer batch headers with reported totals | S10 / E13 | Required | CSV | Raw source (third party) | 88 (22 × 2 types × 2 currencies) |
| IN-13 | `settlement_lines_2026-09.csv` | Transaction, fee and refund lines inside each batch | S10, S11 / E13, E15 | Required | CSV | Raw source (third party) | ≈ 560 (fixed at generation) |
| IN-14 | `discrepancy_log_2026-09.csv` | Firm's discrepancy and corrective-action log | S13 / E06 | Required (may be header-only) | CSV | Raw source | 0 (header only) |
| IN-15 | `ack_letter_SGA-GBP-01.pdf` | Designation acknowledgement for SGA-GBP-01 | S08 / E08 | Required | PDF | Supporting document | 1 page |
| IN-16 | `ack_letter_SGA-EUR-01.pdf` | Designation acknowledgement for SGA-EUR-01 | S08 / E08 | Required | PDF | Supporting document | 1 page |
| IN-17 | `safeguarding_reconciliation_policy_v1.2.pdf` | Method, reconciliation point, frequency | S14 / E07 | Required | PDF | Supporting document | 2 pages |
| IN-18 | `governance_register_2026-09.pdf` | Accountable person (CASS 15.2.4R) and critical individuals | S15 / E09 | Conditional (checklist C16) | PDF | Supporting document | 1 page |
| IN-19 | `rep027_submission_receipt_2026-08.pdf` | August monthly return submission receipt | S16 / E10 | Conditional (checklist C16) | PDF | Supporting document | 1 page |

Row counts marked ≈ depend on the generator's seeded activity and will be fixed exactly in the generation plan. All other counts are structural.

### 3.2 Not uploaded (derived or internal)

| Item | Why it is not an input |
| --- | --- |
| `reporting_period`, `asset_pool` | POC configuration. Their attributes (method, segregation, point) are evidenced by IN-17 and confirmed by a reviewer. |
| Recomputed requirement, resource and differences | Computed by the POC into `control_result`. |
| `exception`, `exception_event` | Produced by the POC and reviewers. IN-14 is the firm's own log, which is a different thing. |
| `evidence_document` | Created at ingestion: one record per uploaded file, with `evidence_id` and SHA-256. |
| `extracted_field` | Created when the POC reads values from PDFs. Each value must be reviewer-confirmed before use (DQ17). |
| Coverage matrix, findings, audit pack, `pack_*`, `approval` | Outputs. |

### 3.3 Material changes from the spec's file list

| Spec (§8 baseline) | v1 | Reason |
| --- | --- | --- |
| 22 client snapshot files | 1 file, 264 rows | A manual local upload of hundreds of files is impractical. Per-day identity is kept by `snapshot_id` and `recon_date`. |
| 44 balance confirmations, 44 end-of-day statements | 1 confirmations file (44 rows); 1 statement-header file (88 rows, including own-funds accounts); 1 entries file | Each daily statement keeps its own `statement_id`, so a missing day is detected as a missing ID, not a missing file. |
| 88 settlement report files | 1 batch-header file and 1 lines file | Same reasoning. Reported totals stay in the header and are checked against lines (D05). |
| Own-funds statements (unspecified format) | Rows for `OWN-*` accounts inside IN-08 and IN-09 | No separate file is needed. They corroborate top-ups (C06 funding evidence). |
| No SGA ledger source | **IN-10 cash-book entries (proposed)** | RC1 and C05 require item A from the firm's own ledger (CASS 15.8.15R). Without it, item A could only be copied from IN-05, which would make C05 circular. |
| Canonical `amount_signed` listed as a source field | Inputs carry `amount` and `dc_indicator`; `amount_signed` is derived | Preserves raw values (decision 1). |
| `bank_entry.booking_date` only; `unallocated_receipt` dates only | Adds `booking_ts`, `receipt_ts`, `allocated_ts` | Whether an item counts at the 17:00 point cannot be decided from a date alone. |

**Trade-off.** Monthly files mean a real bank's daily delivery is represented as rows rather than files. If stakeholders confirm daily files, IN-07, IN-08 and IN-09 can be split by statement without changing any schema or rule.

## 4. File schemas

Conventions for every CSV:

- UTF-8, comma-separated, header row, RFC 4180 quoting. No thousands separators.
- **Money:** decimal string with exactly 2 decimal places (GBP, EUR). `amount` columns are unsigned (≥ 0.00). Balances and reported differences are signed strings where noted. Never binary floating point.
- **Currency:** ISO 4217. One currency per row. No row or total mixes currencies.
- **Time:** ISO 8601 with offset, Europe/London (`2026-09-08T17:00:00+01:00`). Date-only columns are business dates.
- **Req:** M = mandatory; C = conditional (rule stated); O = optional.
- **Status** (spec codes): VR = required by a verified rule; IC = industry convention; DP = design proposal; **NEW** = proposed in this document, not in the spec.

### IN-01 `recon_calendar_2026-09.csv` → `recon_day`

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| calendar_date | date | M | PK. Every date 1–30 Sep. | DP |
| period_id | string | M | `PER-2026-09` | DP |
| is_recon_day | boolean (`true`/`false`) | M | Reconciliation-day definition per FCA glossary | VR |
| non_recon_reason | enum | C | Required when false: `WEEKEND`, `UK_BANK_HOLIDAY`, `FOREIGN_MARKET_CLOSED` | VR |
| calendar_basis | string | M | Fixed text: `SYNTHETIC: UK weekends and bank holidays; no foreign-market closures assumed` | NEW |

Baseline: 22 recon days (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30 Sep). 8 weekend days.

### IN-02 `account_inventory.csv` → `institution`, `safeguarding_account`

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| account_id | string | M | PK. `SGA-GBP-01`, `SGA-EUR-01`, `OWN-GBP-01`, `OWN-EUR-01` | DP |
| account_class | enum | M | `RELEVANT_FUNDS_BANK` or `OWN_FUNDS` | VR (15.8.39R) |
| currency | ISO 4217 | M | One per account | VR (15.8.47R) |
| asset_pool_id | string | C | Required when `RELEVANT_FUNDS_BANK`; blank for own funds | VR |
| account_number_masked | string | M | e.g. `****4471`. Synthetic. | VR (10A.2.3R(3)) |
| designation_name | string | C | Required for safeguarding accounts; must contain "Safeguarding" | VR (EMRs reg 21(3)); 15.2.2G |
| acknowledgement_letter_ref | string | C | Required for safeguarding accounts. Must equal the reference printed on IN-15 / IN-16. | NEW (link key) |
| institution_id | string | M | `INST-01` | DP |
| institution_full_name | string | M | `Example Bank plc` (fictional) | VR (10A.2.3R(1)) |
| institution_postal_address, institution_email, institution_phone | string | M | Fictional values | VR (10A.2.3R(2)) |
| institution_role | enum | M | `RELEVANT_FUNDS_BANK` | VR |
| open_date / close_date | date | M / O | Open throughout the period | DP |

### IN-03 `client_balance_snapshots_2026-09.csv` → `client_balance_snapshot`

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| snapshot_id | string | M | PK. `CBS-20260908-C0003-GBP` | DP |
| recon_date | date | M | FK → IN-01 (`is_recon_day = true`) | VR |
| as_at_ts | timestamp | M | Must equal the policy reconciliation point on that date | VR (15.8.21R) |
| client_id | string | M | `C0001`–`C0008` (GBP), `C0101`–`C0104` (EUR) | VR (15.8.8R(1)) |
| balance_ref | string | C | Blank: one balance per client in the POC | VR (15.8.32G option) |
| asset_pool_id | string | M | `POOL-EMONEY` | VR |
| currency | ISO 4217 | M | | DP |
| balance | signed decimal | M | Individual safeguarding balance per the client ledger. May be negative in principle; none is negative in the baseline. **Never inferred.** | VR (15.8.30R–34G) |

### IN-04 `unallocated_register_2026-09.csv` → `unallocated_receipt`

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| receipt_id | string | M | PK. `UR-0001` | DP |
| bank_reference | string | M | Must equal `bank_reference` or `end_to_end_ref` of one IN-09 credit entry | NEW (replaces raw `bank_entry_id`, which a register would not hold) |
| receipt_date / receipt_ts | date / timestamp | M | | VR (date, 15.2.5R); NEW (ts) |
| amount | unsigned decimal | M | Must equal the matched bank entry amount | VR |
| currency | ISO 4217 | M | | VR |
| classification | enum | M | `UNALLOCATED` or `UNIDENTIFIED` | VR (15.2.5R(2), 15.2.9R) |
| identified_date | date | C | Required if first `UNIDENTIFIED` | VR |
| allocated_date / allocated_ts | date / timestamp | C | Blank while open | VR (date); NEW (ts) |
| client_id | string | C | Required once allocated | VR |

Baseline content (DP): `UR-0001` £750.00 received 11 Sep 16:30, allocated 14 Sep 09:30. `UR-0002` €400.00 received 23 Sep 16:10, allocated 24 Sep 09:15. Both exercise the "open unallocated at the point" term of RC1 and the CASS 15.2.5R next-business-day deadline.

### IN-05 `internal_recon_records_2026-09.csv` → `internal_recon_run` (reported values)

Column names follow spec §4 exactly: `recon_run_id` (PK, `IRR-EMONEY-GBP-20260908`), `recon_date`, `reconciliation_point_ts`, `performed_at_ts`, `asset_pool_id`, `currency`, `method`, `requirement_reported`, `resource_reported`, `item_a`, `item_b`, `item_c`, `item_d`, `difference_reported`, `d1_requirement`, `d1_resource`, `actions_taken_text`, `preparer_id`, `reviewer_id`.

- All monetary columns are **signed decimal strings, as reported**.
- `item_b`–`item_d` = `0.00` in the baseline.
- `d1_*` are blank, with the CASS 15.8.13R basis stated in `actions_taken_text`. See gap G-R05 on whether this basis holds.
- One row per recon day per currency (per-currency internal reconciliation: frozen synthetic decision).

### IN-06 `external_recon_records_2026-09.csv` → `external_recon_line` (reported values)

Spec §4 columns: `ext_recon_id` (PK, `ERL-SGA-GBP-01-20260908`), `recon_date`, `performed_at_ts`, `account_id`, `currency`, `ledger_balance_reported`, `bank_statement_id` (FK → IN-07 `statement_id`), `bank_balance_reported`, `difference_reported` (bank − ledger), `timing_difference_claimed`. Adds `preparer_id` (DP).

`bank_statement_id` in IN-06 is the *firm's claim* about which statement it used. If that ID does not exist in IN-07, the claim is unsupported (DQ12) and the reported bank balance is **not** accepted.

### IN-07 `bank_balance_confirmations_2026-09.csv` → `bank_statement` (type `BALANCE_CONFIRMATION`)

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| statement_id | string | M | PK. `ST-SGA-GBP-01-20260908-1700` | DP |
| account_id | string | M | FK → IN-02. Safeguarding accounts only. | VR |
| as_at_ts | timestamp | M | `…T17:00:00+01:00` | VR (15.8.40G) |
| currency | ISO 4217 | M | Must equal account currency | VR |
| balance_amount | unsigned decimal | M | As stated by the bank. **Never inferred.** | VR (15.8.47R) |
| balance_dc_indicator | `C` / `D` | M | Bank's perspective: `C` = in credit to the account holder | IC |
| bank_statement_ref | string | O | Bank's own reference | IC |

### IN-08 `bank_statements_eod_2026-09.csv` → `bank_statement` (type `EOD_STATEMENT`)

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| statement_id | string | M | PK. `ST-SGA-GBP-01-20260908-EOD` | DP |
| account_id | string | M | FK → IN-02. All four accounts. | VR |
| statement_date | date | M | Recon days only (no weekend statements in the baseline) | DP |
| as_at_ts | timestamp | M | `…T23:59:59+01:00` | DP |
| currency | ISO 4217 | M | | VR |
| opening_balance_amount, opening_balance_dc | decimal, `C`/`D` | M | Must equal previous statement's closing for the account (DQ22) | VR |
| closing_balance_amount, closing_balance_dc | decimal, `C`/`D` | M | **Never inferred** | VR |
| entry_count | integer | M | Number of IN-09 rows for this statement; detects truncated entry files | NEW |
| bank_statement_ref | string | O | | IC |

The 1 Sep opening balances equal the synthetic 31 Aug 17:00 opening positions: SGA-GBP-01 £250,000.00 and SGA-EUR-01 €80,000.00. Own-funds openings are synthetic.

### IN-09 `bank_statement_entries_2026-09.csv` → `bank_entry`

| Column | Type | Req | Notes | Status |
| --- | --- | --- | --- | --- |
| bank_entry_id | string | M | PK. `BE-GBP-0908-AQ1`, `BE-GBP-0908-TU1`, `BE-OWN-GBP-0908-TU1` | DP |
| statement_id | string | M | FK → IN-08 | DP |
| account_id | string | M | Must match the statement's account (conflict → DQ13) | DP |
| booking_date / booking_ts | date / timestamp | M | `booking_ts` decides inclusion in the 17:00 confirmation | IC; NEW (ts) |
| value_date | date | M | **Never inferred** | IC |
| amount | unsigned decimal | M | | DP |
| dc_indicator | `C` / `D` | M | Bank's perspective: `C` = money into the account | IC |
| currency | ISO 4217 | M | | IC |
| bank_reference | string | M | Settlement, top-up and redemption references (for example `SB-GBP-20260908`, `TOPUP-GBP-20260908`) | IC |
| end_to_end_ref | string | C | Required for bank-transfer loads and redemptions | IC |
| counterparty_name | string | O | Fictional | IC |
| narrative_text | string | O | Free text. Never authoritative. | IC |

### IN-10 `sga_cashbook_entries_2026-09.csv` → **proposed entity `sga_ledger_entry`** (NEW; requires review)

| Column | Type | Req | Notes |
| --- | --- | --- | --- |
| ledger_entry_id | string | M | PK. `LE-GBP-0908-0004` |
| account_id | string | M | FK → IN-02. Safeguarding accounts only. |
| posted_ts | timestamp | M | Entries with `posted_ts` ≤ 17:00 count toward that day's item A |
| value_date | date | M | |
| entry_type | enum | M | `OPENING_BALANCE`, `BANK_LOAD`, `UNALLOCATED_RECEIPT`, `ACQUIRER_SETTLEMENT`, `OWN_FUNDS_TOPUP`, `SCHEME_SETTLEMENT`, `REDEMPTION` |
| amount | unsigned decimal | M | |
| dc_indicator | `D` / `C` | M | **Firm's asset-ledger perspective: `D` = money into the account.** This is the opposite of the bank convention; see section 6. |
| currency | ISO 4217 | M | |
| payment_reference | string | M | Must equal the matching IN-09 `bank_reference` or `end_to_end_ref`. This is the only cash-book-to-bank link. |
| batch_id / txn_id | string | C | Set for settlement and 1:1 movements respectively |

One `OPENING_BALANCE` row per safeguarding account, dated 31 Aug 2026 17:00, carries the synthetic opening position. The roll-forward to each 17:00 point gives item A independently of IN-05.

### IN-11 `transactions_2026-09.csv` → `transaction`

Spec §4 columns, with two input-level adjustments:

- `amount` (unsigned) + `direction` (`CR` = increases the client balance, `DR` = decreases it) replace an uploaded `amount_signed`.
- `payment_reference` (C: required for bank-transfer loads and redemptions) is the raw link to IN-09. The canonical `bank_entry_id` is populated only by an exact reference match.

Other columns: `txn_id` (PK, `TX-0908-00117`), `client_id`, `balance_ref` (blank), `txn_type` (`LOAD_BANK`, `LOAD_CARD`, `SPEND`, `REDEMPTION`, `REFUND`), `status`, `auth_ts`, `clearing_date`, `executed_ts`, `currency`, `settlement_batch_id` (C: required for `LOAD_CARD`, `SPEND`, `REFUND`), `original_txn_id` (C: required for `REFUND`).

Key records required by the spec §8: `TX-0902-00044` (spend £60.00, C0002, in `SB-GBP-20260902`) and `TX-0909-0R001` (refund £60.00, original `TX-0902-00044`, in `SB-GBP-20260909`).

### IN-12 `settlement_batches_2026-09.csv` → `settlement_batch`

Spec §4 columns: `batch_id` (PK, `SB-GBP-20260908`, `AQ-GBP-20260908`), `counterparty_type` (`SCHEME` or `ACQUIRER`), `cycle_date`, `settlement_date`, `account_id`, `currency`, `direction` (`TO_FIRM` or `FROM_FIRM`), `gross_amount`, `total_fees`, `total_adjustments`, `net_amount_reported`, `expected_bank_reference`.

All totals are **unsigned, as reported by the counterparty**. `net_amount_reported` is never recomputed into this file.

Generic synthetic format. No scheme-specific fields are included.

### IN-13 `settlement_lines_2026-09.csv` → `settlement_line`

| Column | Type | Req | Notes |
| --- | --- | --- | --- |
| line_id | string | M | PK. `SL-SB-GBP-20260908-0004` |
| batch_id | string | M | FK → IN-12 |
| line_type | enum | M | `TXN`, `FEE`, `REFUND` (`ADJUSTMENT` reserved; unused in v1) |
| txn_id | string | C | Required for `TXN` and `REFUND`. FK → IN-11. |
| fee_code | string | C | Required for `FEE`: `ACQ_FEE`, `SCHEME_FEE` |
| amount | unsigned decimal | M | |
| dc_indicator | `C` / `D` | M | Settlement-account perspective: `C` = money to the firm |
| currency | ISO 4217 | M | Must equal batch currency |

Key record per spec §8: `AQ-GBP-20260908` has gross £10,000.00 (4 × £2,500.00 to C0001–C0004), fee lines `ACQ_FEE` £30.00 and `SCHEME_FEE` £15.50, net £9,954.50. It is settled by `BE-GBP-0908-AQ1`, with top-up `BE-GBP-0908-TU1` £45.50.

### IN-14 `discrepancy_log_2026-09.csv` → evidence for C06 / C08

Columns: `discrepancy_id` (PK), `logged_ts`, `recon_ref` (an IN-05 or IN-06 ID), `account_id`, `currency`, `amount`, `description`, `cause_category`, `cause_evidence_ref`, `funding_reference`, `status`, `resolved_ts`, `approver_id`.

The baseline is header only. **A header-only file means "no discrepancies logged". A missing file means "log not provided".** These are different findings.

### PDF supporting documents (IN-15 to IN-19)

The PDFs are generated as real PDFs (ReportLab), not renamed text. Each carries a visible footer: "SYNTHETIC DOCUMENT — UC-042 POC — not a real bank or firm document".

To make deterministic text extraction possible, each PDF includes a **"Key details" table** with fixed labels. Real documents would need AI- or human-assisted extraction, and every extracted value must be reviewer-confirmed (DQ17).

| File | Required key details |
| --- | --- |
| IN-15 / IN-16 acknowledgement letters | Letter reference (must equal IN-02 `acknowledgement_letter_ref`); institution name and address; account name (designation); masked account number; currency; letter date; synthetic signatory. Body: generic acknowledgement wording, labelled synthetic. **The CASS 15.7 template wording has not been reviewed** (gap G-R04). |
| IN-17 policy v1.2 | Document version; effective date (7 May 2026); approval date; safeguarding method `SEGREGATION`; reconciliation method `STANDARD`; reconciliation point `17:00 Europe/London`; frequency "each reconciliation day"; internal reconciliation basis "per currency"; discrepancy procedure summary. |
| IN-18 governance register | Accountable person (synthetic name), role, allocation date; critical individuals list (CASS 10A.2.1R(10)). |
| IN-19 return receipt | Return name as used in the research (REP027; template not reviewed); period August 2026; due date 21 Sep 2026; submission timestamp 17 Sep 2026; synthetic submission reference. |

## 5. Relationships and link keys

| From → to | Cardinality | Key (source fields) | Never linked by |
| --- | --- | --- | --- |
| IN-03 → IN-01 | many → 1 | `recon_date` = `calendar_date` | — |
| IN-05 → IN-01 | 1 per currency per recon day | `recon_date`, `currency` | — |
| IN-06 → IN-02 | many → 1 | `account_id` | — |
| IN-06 → IN-07 | many → 1 | `bank_statement_id` = `statement_id` | Date proximity |
| IN-07, IN-08 → IN-02 | many → 1 | `account_id` | — |
| IN-09 → IN-08 | many → 1 | `statement_id` | — |
| IN-10 ↔ IN-09 | 1 ↔ 1 | `payment_reference` = `bank_reference` or `end_to_end_ref`, same account and currency | Amount |
| IN-04 → IN-09 | 1 → 1 | `bank_reference` | Amount |
| IN-11 → IN-12 | many → 1 | `settlement_batch_id` | Amount, date |
| IN-13 → IN-12 | many → 1 | `batch_id` | — |
| IN-13 → IN-11 | 1 → 1 | `txn_id` | Amount |
| IN-12 → IN-09 | 1 → 1 (baseline) | `expected_bank_reference` = `bank_reference`, same account and currency | **Amount alone (spec S04)** |
| IN-11 (refund) → IN-11 | many → 1 | `original_txn_id` | Amount, client |
| IN-11 (direct) → IN-09 | 1 → 1 | `payment_reference` = `end_to_end_ref` | Amount |
| IN-02 → IN-15 / IN-16 | 1 → 1 | `acknowledgement_letter_ref` = letter reference in PDF key details | File name |

**Provenance.** At ingestion each file receives an `evidence_id` and SHA-256 (spec `evidence_document`). Each parsed row receives `source_row_ref`, given as the physical CSV line number (header = line 1) or the PDF page and key-detail label. Each row also receives `ingested_at`. Every finding cites `(evidence_id, source_row_ref)`.

## 6. Sign normalisation (derived, documented)

The canonical `amount_signed` is positive when the balance it belongs to increases.

| Source | Raw indicator | Rule |
| --- | --- | --- |
| IN-07, IN-08 balances; IN-09 entries | Bank perspective `C`/`D` | `C` → +amount; `D` → −amount |
| IN-10 cash book | Firm asset-ledger `D`/`C` | `D` → +amount; `C` → −amount |
| IN-11 transactions | Client `CR`/`DR` | `CR` → +amount; `DR` → −amount |
| IN-13 settlement lines | Settlement-account `C`/`D` | `C` → +amount; `D` → −amount |
| IN-12 batch totals | Unsigned plus `direction` | Net signed = +net if `TO_FIRM`, −net if `FROM_FIRM` |

Any value outside the code list is rejected (DQ14). Raw `amount` and indicator are stored unchanged beside the derived value.

## 7. Handling missing, malformed, duplicated or contradictory files

The rules below apply to every file and use the spec §7 DQ IDs. File-specific consequences are in `UC042_SOURCE_TO_CONTROL_MATRIX.md`.

| Condition | Response |
| --- | --- |
| Required file not uploaded | Every control that consumes it returns `INSUFFICIENT_EVIDENCE` for its whole scope. The coverage view shows the file as missing. No values are assumed. |
| Expected record absent from an uploaded file (for example one day's statement) | `INSUFFICIENT_EVIDENCE` for that scope only (RC7, DQ18). |
| Malformed file (unparseable, wrong header) | BLOCK (file). Rejected with reason; nothing from it is used. |
| Malformed row (DQ01, DQ02, DQ06, DQ07, DQ14) | BLOCK (record). Row excluded and listed; affected scopes become `INSUFFICIENT_EVIDENCE`, never zero. |
| Wrong period (DQ04) | BLOCK (file). |
| Same file twice (DQ08, same SHA-256) | Second upload refused, pointing to the existing `evidence_id`. |
| Same record ID in two files or uploads (DQ09) | First kept, later one flagged. |
| Corrected version of a file | New `evidence_id` with `supersedes_evidence_id`. Old version retained as superseded. |
| Contradiction (DQ13: two values for one fact) | BLOCK (scope). Exception raised; both retained; a reviewer chooses. |
| Orphan link (DQ12) | Record kept, link left null, finding raised. |

## 8. Assumptions (synthetic POC conventions)

Each assumption below is safe for the POC and none is a Moorwand fact. The full list, with questions, is in `UC042_RESEARCH_GAPS.md`.

- Monthly consolidated CSVs.
- Generic settlement format.
- 17:00 balance confirmation plus end-of-day statements.
- Per-currency internal reconciliation.
- Same-day settlement in the baseline.
- Scheme fees billed outside safeguarding accounts.
- Acquirer fees deducted from card-load settlements and topped up from own funds the same day.
- One balance per client.
- No foreign-market closures.
- Two unallocated receipts in the baseline.
