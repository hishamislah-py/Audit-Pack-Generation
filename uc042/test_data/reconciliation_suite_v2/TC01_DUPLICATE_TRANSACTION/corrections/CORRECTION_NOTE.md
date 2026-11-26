# TC01 - Correction record (applied to the initial submission)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

**Scenario:** Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80)

**Customer label:** SYNTHETIC TEST Ashcombe Pay Ltd  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline

| # | Op | File | Record | Field | Old | New / detail | Why |
|---|---|---|---|---|---|---|---|
| 1 | delete_record | IN-10 `sga_cashbook_entries_2026-09.csv` | `LE-GBP-0928-0007` | (record) | present | deleted | duplicate interface posting removed |

**What was wrong:** The cash-book extract contained a duplicate posting (LE-GBP-0928-0007) created by an interface re-run.

**What changed:** LE-GBP-0928-0007 removed from sga_cashbook_entries_2026-09.csv; the file is byte-identical to the clean baseline IN-10.

**Replacement files:** IN-10 `sga_cashbook_entries_2026-09.csv`

**Expected before correction:** see `../expected_results/engine_predicted_initial.json` and `financial_answer_key.json`.
**Expected after correction:** see `../expected_results/engine_predicted_after_correction.json` and `financial_answer_key_after_correction.json`.

Re-upload: use `../upload/TC01_corrected_evidence_upload.zip` (complete set) or the replacement files only, as the receiving application requires (see UPLOAD_INSTRUCTIONS.md).
