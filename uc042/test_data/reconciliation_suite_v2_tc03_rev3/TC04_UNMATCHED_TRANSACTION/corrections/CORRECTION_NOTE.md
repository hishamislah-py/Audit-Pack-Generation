# TC04 - Correction record (applied to the initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart

**Customer label:** SYNTHETIC TEST Dunmore Payments Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | add_record | IN-04 `unallocated_register_2026-09.csv` | `UR-0003` | (record) | absent | added after UR-0002: bank_reference=E2E-EUR-0930-U01, receipt_date=2026-09-30, receipt_ts=2026-09-30T16:20:00+01:00, amount=650.00, currency=EUR, classification=UNIDENTIFIED, identified_date=, allocated_date=, allocated_ts=, client_id= | receipt registered as unidentified |
| 2 | add_record | IN-10 `sga_cashbook_entries_2026-09.csv` | `LE-EUR-0930-0006` | (record) | absent | added after LE-EUR-0930-0005: account_id=SGA-EUR-01, posted_ts=2026-09-30T16:20:00+01:00, entry_type=UNALLOCATED_RECEIPT, amount=650.00, dc_indicator=D, currency=EUR, payment_reference=E2E-EUR-0930-U01 | receipt posted to the cash book |
| 3 | set_field | IN-05 `internal_recon_records_2026-09.csv` | `IRR-EMONEY-EUR-20260930` | requirement_reported | 118555.00 | 119205.00 | requirement includes the open receipt |
| 4 | set_field | IN-05 `internal_recon_records_2026-09.csv` | `IRR-EMONEY-EUR-20260930` | resource_reported | 118555.00 | 119205.00 | resource includes the receipt |
| 5 | set_field | IN-05 `internal_recon_records_2026-09.csv` | `IRR-EMONEY-EUR-20260930` | item_a | 118555.00 | 119205.00 | item A includes the receipt |
| 6 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-EUR-01-20260930` | ledger_balance_reported | 118555.00 | 119205.00 | ledger includes the receipt |
| 7 | set_field | IN-06 `external_recon_records_2026-09.csv` | `ERL-SGA-EUR-01-20260930` | difference_reported | 650.00 | 0.00 | difference cleared |

**What was wrong:** The 650.00 receipt was not recorded: no cash-book posting, no register entry, and the reconciliations omitted it.

**What changed:** Receipt recorded as UNIDENTIFIED (IN-04 UR-0003) and posted (IN-10 LE-EUR-0930-0006); IN-05 and IN-06 for EUR 30 Sep updated.

**Replacement files:** IN-04 `unallocated_register_2026-09.csv`, IN-05 `internal_recon_records_2026-09.csv`, IN-06 `external_recon_records_2026-09.csv`, IN-10 `sga_cashbook_entries_2026-09.csv`

**Expected before correction:** see `../expected_results/engine_predicted_initial.json` and `financial_answer_key.json`.
**Expected after correction:** see `../expected_results/engine_predicted_after_correction.json` and `financial_answer_key_after_correction.json`.

Re-upload: use `../upload/TC04_corrected_evidence_upload.zip` (complete set) or the replacement files only, as the receiving application requires (see UPLOAD_INSTRUCTIONS.md).
