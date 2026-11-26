# Upload and execution instructions: UC-042 Reconciliation Test Suite V2

> **Not yet executed.**
> - None of these datasets has been run through the UC-042 engine, the uc042app ZIP intake, or Ringfence.
> - Follow these steps only when engine and application runs are authorised, and only in an isolated environment. Never use the live 8780 server or the protected paths listed in `SOURCE_DISCOVERY_REPORT.md`.
> - Every ENGINE-PREDICTED value is a source-reading prediction to be confirmed, not a result.

## 1. What to upload for each scenario

| Scenario | Initial upload | Correction / re-upload |
|---|---|---|
| TC01 | `TC01_DUPLICATE_TRANSACTION/upload/TC01_initial_evidence_upload.zip` | `TC01_corrected_evidence_upload.zip` (complete set), or only `corrections/replacement_files/source_data/sga_cashbook_entries_2026-09.csv` |
| TC02 | `TC02_AMOUNT_MISMATCH/upload/TC02_initial_evidence_upload.zip` | none |
| TC03 | `TC03_TIMING_DIFFERENCE/upload/TC03_initial_evidence_upload.zip` | none |
| TC04 | `TC04_UNMATCHED_TRANSACTION/upload/TC04_initial_evidence_upload.zip` | `TC04_corrected_evidence_upload.zip`, or the 4 replacement files (IN-04, IN-05, IN-06, IN-10) |
| TC05 | `TC05_COMMON_CAUSE/upload/TC05_initial_evidence_upload.zip` | `TC05_corrected_evidence_upload.zip`, or the replacement IN-11 |
| TC06 | `TC06_INDEPENDENT_CAUSES/upload/TC06_initial_evidence_upload.zip` | none |

**What each upload ZIP contains:**

- Exactly the 19 canonical evidence files (14 CSV, 5 PDF) at the root, under their canonical September 2026 names.
- No manifest, README or answer key. Per `UC042_ZIP_INPUT_SPECIFICATION.md` section 4, any extra file would reject the whole package.

**The period** is PER-2026-09.

**Customer labels** are fictional and start `SYNTHETIC TEST`:

| Scenario | Customer label |
|---|---|
| TC01 | Ashcombe Pay Ltd |
| TC02 | Brindle Wallet Ltd |
| TC03 | Cresswell Money Ltd |
| TC04 | Dunmore Payments Ltd |
| TC05 | Elmstead Card Services Ltd |
| TC06 | Farrowdale E-Money Ltd |

Use a different label per scenario so that cases do not collide.

## 2. Direct engine run (when permitted), on a COPY

Each `initial_submission/` and `corrections/corrected_case/` is a complete engine-layout case directory (`source_data/`, `supporting_documents/`, `manifest.csv`, `scenario.json`). The `scenario_id` in `scenario.json` makes the engine number exceptions `EXC-TCnn-NN`, as predicted.

1. Copy the case directory to a scratch location. The engine writes `validation/` and `VALIDATION_REPORT.md` into the case.
2. From the reference engine's parent folder, run `python -m uc042lib.validate <copied_case_dir> PER-2026-09`.
3. Compare the output with `<scenario>/expected_results/engine_predicted_initial.json`, or with `engine_predicted_after_correction.json` for corrected cases. The file uses the answer-key fields `non_passing_results`, `exceptions`, `evidence_statuses`, `investigation_groups` and `candidate_relationships`.
4. To have the engine compare automatically, copy that JSON into the copied case as `answer_key.json`. It is deliberately **not** placed in the generated case directories.

## 3. Ringfence upload (when permitted)

| Item | Status |
|---|---|
| Ringfence's acceptance of these ZIPs | **Not verified.** The scenario library used customer-style member names; this suite uses canonical names and canonical headers. |
| Live AI cost | With live AI enabled, Ringfence starts one investigation per exception. Predicted exception counts: TC01 10, TC02 2, TC03 1, TC04 2, TC05 3, TC06 6. Owner approval is needed. |
| Re-upload behaviour (initial → corrected) | Investigations are scoped to each audit run; see the existing correction flows (M3, RF-DEMO-04). Not verified for this suite. |

## 4. What to compare after a run

| Layer | File |
|---|---|
| Financial facts (engine-independent) | `expected_results/financial_answer_key*.json` |
| Current engine | `expected_results/engine_predicted_*.json`. **TC06's group is a predicted over-grouping (G-18), UNVERIFIED.** |
| Future enriched engine | `expected_results/future_behaviour_proposed.json` (PROPOSED; categories PENDING) |
| AI investigation | `expected_results/ai_investigation_expectations.json` |
