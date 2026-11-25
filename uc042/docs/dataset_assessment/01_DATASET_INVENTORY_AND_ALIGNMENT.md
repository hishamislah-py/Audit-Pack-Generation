# 01 — Dataset Inventory and Alignment

Assessment date: 30 Oct 2026. Inspection only: nothing in the project was modified, regenerated or deleted. All data is **synthetic**; none of it is a Moorwand export.

## 1. Use case being assessed against

The source is Hypothesis 2, "Audit Pack Generation Assessment", in the Moorwand AI Opportunity Profile. It has three steps:

1. **Continuous evidence mapping** of programme activity to settlement accounts (deterministic).
2. **Pack assembly** into a reviewer-ready format on demand (AI layer).
3. **Compliance review**, where a human approves before any external submission.

Status: discovery hypothesis, LEAD. Kill condition: the "audit-ready data investment already produces packs as a by-product."

**Audit-pack generation is the primary outcome.** Reconciliation checks and exceptions are supporting evidence for the pack.

## 2. What exists (verified from the files)

| Item | Count | Location |
| --- | --- | --- |
| Datasets | 3: clean baseline (S01), missing EUR evidence (S02), unexplained £812.40 GBP difference (S05) | `uc042_dataset/` |
| Inputs per dataset | 19: 14 CSV + 5 PDF | `source_data/`, `supporting_documents/` |
| CSV data rows (baseline) | **1,940** (header excluded); 1,954 physical lines | Counted directly from the files |
| Engine | `generate.py`, `scenarios.py`, `prepare.py`, `validate.py`, `structure.py`, `schema.py`, `money.py`, `trace.py` | `uc042lib/` |
| Tests | 83, all passing | `tests/` |
| Audit-pack generator | **None** | — |
| AI component (investigation or narrative) | **None** | — |
| Human approval record | **None** in the engine. A UI prototype (`audit-pack-workspace.html`) simulates one on invented data. | — |

**Row-count discrepancy (1,898 versus 1,940).** The actual total from the files is **1,940**, equal to the per-file sum. "1,898" was an arithmetic error in a chat summary; no file, manifest or report contains it.

## 3. Inventory and classification

Classifications: RETAIN / MODIFY / CONSOLIDATE / OPTIONAL / REMOVE / MISSING.

"Synthetic-derived" means the values were produced by the generator's simulation rather than drawn independently. **Every file is synthetic.** The column says whether the file plays the role of independent source evidence or of a *reported* figure in the evidence model.

Scenario numbers follow the assessment scope (02 §1). **Scenario 6 is unconfirmed:** the provisional candidate is S05, the £812.40 unexplained difference.

| File (ID) | Category | Rows | Purpose | Fields used by checks | Scenarios | Depends on / referenced by | Evidence role | Duplicated elsewhere? | Needed for a meaningful pack? | Classification |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| `recon_calendar_2026-09.csv` (IN-01) | Calendar | 30 | Which days need reconciliation | `calendar_date`, `is_recon_day` | All | Scope for C01, C07, C14, DQ22; gates C04–C08 | Synthetic list (UK weekdays) | No | Yes, as scope. Not necessarily as an upload. | **MODIFY** (move to configuration) |
| `account_inventory.csv` (IN-02) | Accounts / institution | 4 | Accounts, currencies, designation, CASS 10A details | `account_id`, `account_class`, `currency`, `designation_name`, `acknowledgement_letter_ref` | All | Referenced by IN-06/07/08/09/10/12 (0 orphans) | Source | No | Yes | **RETAIN** |
| `client_balance_snapshots_2026-09.csv` (IN-03) | Client ledger | 264 | Client balances at 17:00 | `recon_date`, `as_at_ts`, `client_id`, `currency`, `balance` | 1, 4, 5, 6 | `client_id` ↔ IN-11 | Source | No | Yes | **MODIFY** (add a 31 Aug opening snapshot so the 1 Sep roll-forward can be checked) |
| `unallocated_register_2026-09.csv` (IN-04) | Ops register | 2 | Receipts not yet attributed | `bank_reference`, `receipt_ts`, `allocated_ts`, `amount`, `currency` | 1, 5 | → IN-09 by end-to-end ref; → IN-11 allocation | Source | No | Yes | **RETAIN** |
| `internal_recon_records_2026-09.csv` (IN-05) | Firm's reported reconciliation | 44 | Reported requirement, resource, items A–D | `requirement_reported`, `resource_reported`, `item_a`–`item_d`, `difference_reported` | All | (date, currency) ↔ IN-03, IN-10 | **Reported** (generator-written) | No | Yes: central CASS 15.8.9R record | **RETAIN** |
| `external_recon_records_2026-09.csv` (IN-06) | Firm's reported reconciliation | 44 | Reported ledger and bank balance | `ledger_balance_reported`, `bank_statement_id`, `bank_balance_reported`, `difference_reported`, `timing_difference_claimed` | All | → IN-07 (0 orphans), IN-02 | **Reported** | No | Yes | **RETAIN** |
| `bank_balance_confirmations_2026-09.csv` (IN-07) | Bank | 44 | Bank balance at 17:00 | `balance_amount`, `balance_dc_indicator`, `as_at_ts` | All; key for 2 | ← IN-06 | Source | Value equals the IN-08 closing balance in **44/44** cases (no post-17:00 entries) | Yes | **CONSOLIDATE** with IN-08; **MODIFY** data to include post-17:00 movements |
| `bank_statements_eod_2026-09.csv` (IN-08) | Bank | 88 | Opening, closing, entry count (4 accounts) | `opening_*`, `closing_*`, `entry_count` | All | ← IN-09 (0 orphans) | Source | See IN-07 | Yes | **CONSOLIDATE** with IN-07 |
| `bank_statement_entries_2026-09.csv` (IN-09) | Bank | 266 | Bank movements | `amount`, `dc_indicator`, `booking_ts`, `bank_reference`, `end_to_end_ref` | All | → IN-08; ↔ IN-10, IN-12, IN-11, IN-04 by reference | Source | No | Yes | **MODIFY** (data: next-day bookings for timing; bank-fee entries need a category) |
| `sga_cashbook_entries_2026-09.csv` (IN-10) | Firm ledger | 224 | Independent ledger for item A and external comparison | `posted_ts`, `entry_type`, `amount`, `dc_indicator`, `payment_reference` | All | ↔ IN-09 by reference (222/222 pairs) | Source (internal) | Every pair shares time and amount with the bank by construction | Yes | **RETAIN** |
| `transactions_2026-09.csv` (IN-11) | E-money platform | 422 | Client movements | `txn_type`, `executed_ts`, `amount`, `direction`, `settlement_batch_id`, `payment_reference`, `original_txn_id` | 1, 3, 5 | → IN-12 (0 orphans); → IN-11 (refunds) | Source | No | Yes | **RETAIN** |
| `settlement_batches_2026-09.csv` (IN-12) | Scheme / acquirer report | 88 | Reported gross, fees, adjustments, net | `gross_amount`, `total_fees`, `total_adjustments`, `net_amount_reported`, `direction`, `expected_bank_reference` | 1, 2, 3 | ← IN-13, IN-11; → IN-09 | **Reported by counterparty** (generator-summed from lines) | No | Yes | **RETAIN** |
| `settlement_lines_2026-09.csv` (IN-13) | Scheme / acquirer report | 420 | Transactions, fees, refunds per batch | `line_type`, `txn_id`, `fee_code`, `amount`, `dc_indicator` | 1, 3, 5 | → IN-12, IN-11 (0 orphans) | Source | No | Yes | **RETAIN** (fee categories need configuration, see 04) |
| `discrepancy_log_2026-09.csv` (IN-14) | Firm's investigation log | 0 | Evidence of investigating differences | `recon_ref`, `logged_ts` | 2, 3, 6 | → IN-05/IN-06 by `recon_ref` | Source | No | Only when a difference exists | **OPTIONAL** |
| `ack_letter_SGA-GBP-01.pdf`, `ack_letter_SGA-EUR-01.pdf` (IN-15/16) | Supporting documents | 1 page each | Account designation acknowledgement | Key details | Pack completeness | ↔ IN-02 by letter reference | Source (synthetic layout) | No | Supporting only | **OPTIONAL** |
| `safeguarding_reconciliation_policy_v1.2.pdf` (IN-17) | Supporting document | 1 page | Point, method, basis | Key details | All (supplies 17:00) | Drives every point-dependent check today | Source (synthetic layout) | No | The *point* is needed, not the PDF | **OPTIONAL** (point moves to configuration) |
| `governance_register_2026-09.pdf` (IN-18) | Supporting document | 1 page | Accountable person | Key details | Pack completeness | — | Source (synthetic) | No | No | **OPTIONAL** (already) |
| `rep027_submission_receipt_2026-08.pdf` (IN-19) | Supporting document | 1 page | Return filed on time | Key details | Pack completeness | — | Source (synthetic) | No | No | **OPTIONAL** (already) |

**REMOVE: none.** Every file has at least one dependent check or pack section.

### MISSING evidence or artefacts

| Missing item | Needed for | Why |
| --- | --- | --- |
| Case configuration (period, calendar, point, accounts, fee categories, matching rules, enabled scenarios) | All; configuration examples | Everything is a Python constant today (see 04) |
| 31 Aug opening client snapshot | 1, 5 | The client roll-forward into 1 Sep is insufficient evidence today |
| Bank evidence of timing differences (bookings after 17:00 or next day; value-date differences) | 2 | The baseline has none: confirmation = closing in 44/44 cases, and cash book and bank share all 222 timestamps |
| Fee schedule or fee-category mapping (fee type → account, rate) | 3 | Fee codes are fixed to `ACQ_FEE` and `SCHEME_FEE`; bank-account fees have no representation |
| Scenario datasets for 2, 3 and 5 | 2, 3, 5 | Not built; only S01, S02 and S05 exist |
| Audit-pack output and human approval record | All | Neither the pack generator nor an approval record exists |

## 4. Alignment summary

- **By file:** 11 of 19 files are directly required uploads (58%). Of the other eight:
  - one becomes configuration (calendar);
  - two merge into one (IN-07 + IN-08);
  - six are optional supporting evidence (IN-14 to IN-19).
- **By data volume:** about **96%** of the 1,940 rows are in required files. Not required as uploads: 30 calendar rows; the log is empty; the PDFs have no rows. Values duplicated by construction: the 44 confirmation balances equal the end-of-day closings.
- **Against the use case:** the data supports the *evidence-mapping* step well. It cannot yet support *pack assembly* (no generator, no AI layer) or *compliance review* (no approval record). These are capability gaps, not data gaps.
