# TC05 - Correction record (applied to the initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export

**Customer label:** SYNTHETIC TEST Elmstead Card Services Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | add_record | IN-11 `transactions_2026-09.csv` | `TX-0924-00018` | (record) | absent | added after TX-0924-00012: client_id=C0104, txn_type=SPEND, status=SETTLED, auth_ts=2026-09-24T07:15:00+01:00, clearing_date=2026-09-24, executed_ts=2026-09-24T15:00:00+01:00, amount=222.18, direction=DR, currency=EUR, settlement_batch_id=SB-EUR-20260924, payment_reference=, original_txn_id= | restored from the complete source export |
| 2 | add_record | IN-11 `transactions_2026-09.csv` | `TX-0924-00019` | (record) | absent | added after TX-0924-00018: client_id=C0101, txn_type=SPEND, status=SETTLED, auth_ts=2026-09-24T08:15:00+01:00, clearing_date=2026-09-24, executed_ts=2026-09-24T15:00:00+01:00, amount=431.57, direction=DR, currency=EUR, settlement_batch_id=SB-EUR-20260924, payment_reference=, original_txn_id= | restored from the complete source export |
| 3 | add_record | IN-11 `transactions_2026-09.csv` | `TX-0924-00020` | (record) | absent | added after TX-0924-00019: client_id=C0101, txn_type=SPEND, status=SETTLED, auth_ts=2026-09-24T09:15:00+01:00, clearing_date=2026-09-24, executed_ts=2026-09-24T15:00:00+01:00, amount=193.70, direction=DR, currency=EUR, settlement_batch_id=SB-EUR-20260924, payment_reference=, original_txn_id= | restored from the complete source export |

**What was wrong:** The transaction export omitted the three spends of SB-EUR-20260924.

**What changed:** TX-0924-00018, -00019, -00020 restored; the file is byte-identical to the clean baseline IN-11.

**Replacement files:** IN-11 `transactions_2026-09.csv`

**Expected before correction:** see `../expected_results/engine_predicted_initial.json` and `financial_answer_key.json`.
**Expected after correction:** see `../expected_results/engine_predicted_after_correction.json` and `financial_answer_key_after_correction.json`.

Re-upload: use `../upload/TC05_corrected_evidence_upload.zip` (complete set) or the replacement files only, as the receiving application requires (see UPLOAD_INSTRUCTIONS.md).
