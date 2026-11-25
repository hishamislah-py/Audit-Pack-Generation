# TC04 Dunmore Payments: Smart Parser mapping, re-upload, then the corrected submission

> **Illustrative synthetic data.** Fictional customer and bank; not real financial records.

This one scenario shows the whole journey:

1. **First upload:** Smart Parser asks for a mapping review.
2. **Re-upload:** one refused file is uploaded again and its columns are mapped.
3. **Reconciliation:** finds the €650 unmatched bank credit (2 exceptions, investigated by AI).
4. **Corrected submission:** comes back CLEAN.

**Customer:** Dunmore Payments Ltd · **Period:** detected automatically (September 2026)

Upload the files exactly as supplied. Do not open and re-save them in Excel.

## 1. First upload

1. Dashboard → **Upload a submission** → customer `Dunmore Payments Ltd`.
2. Choose `06_Dunmore_Payments_Ltd_September_2026_TC04_initial_mapping.zip`. The period shows **September 2026**.
3. Click **Upload and start**.

Smart Parser processes 18 of 19 categories and stops for you with two items:

| What you see | Why |
|---|---|
| **IN-11 Client transactions: mapping review, 4 decisions** | The firm's export wrote `TXN_ID`, `Client_ID`, `␣amount␣`, `CURRENCY` instead of the standard names. Smart Parser never accepts a renamed column by itself. |
| **`settlement_batches_2026-09.csv` not accepted** (IN-12 missing) | The file uses the ops team's own layout (`Settlement Run`, `Gross Value`, … plus an extra `Ops Comment` column), so its category cannot be identified from the content. |

## 2. Mapping review (IN-11)

1. Smart Parser tab → **Review mapping**.
2. For each of the 4 columns: click the row → **Map** (suggested field) → **Record decision**.

   | Source header | Decision |
   |---|---|
   | `TXN_ID` | Map → `txn_id` |
   | `Client_ID` | Map → `client_id` |
   | `␣amount␣` | Map → `amount` |
   | `CURRENCY` | Map → `currency` |

3. Click **Confirm file** → confirm.

## 3. Re-upload the refused file and map it (IN-12)

1. Evidence tab → **Upload missing or corrected file** → category **IN-12 Settlement batches**.
2. Choose `06_Dunmore_Payments_Ltd_September_2026_TC04_upload_later\settlement_batches_2026-09.csv`. It is the same file that was refused.
3. Click **Upload and process**.
4. A column review opens: 13 columns against 12 fields, with no suggestions. For each column: click the row → **Change** → pick the field (or **Ignore**) → **Record decision**.

   | Source header | Decision |
   |---|---|
   | `Settlement Run` | Change → `batch_id` |
   | `Counterparty` | Change → `counterparty_type` |
   | `Run Date` | Change → `cycle_date` |
   | `Value Date` | Change → `settlement_date` |
   | `Receiving Account` | Change → `account_id` |
   | `Ccy` | Change → `currency` |
   | `Flow` | Change → `direction` |
   | `Gross Value` | Change → `gross_amount` |
   | `Fees Deducted` | Change → `total_fees` |
   | `Adjustments` | Change → `total_adjustments` |
   | `Net Value` | Change → `net_amount_reported` |
   | `Bank Ref` | Change → `expected_bank_reference` |
   | `Ops Comment` | Ignore |

5. Click **Confirm file** → confirm.

## 4. Reconcile

1. Validation now passes. Click **Activate package** → **Run reconciliation**.
2. Result: **EXCEPTIONS OPEN, 2 exceptions.** AI investigations start by themselves.

   | Exception | What it says |
   |---|---|
   | EXC-CASE-02 (the cause) | A €650.00 bank credit (BE-EUR-0930-U01, 30 Sept) has no matching cash-book entry. |
   | EXC-CASE-01 (the effect) | The EUR bank and cash book differ by €650.00 on 30 Sept, caused by EXC-CASE-02. |

3. Accept or Reject each finding → Closing & Audit Pack → **Generate audit pack**.

The reconciliation result is identical to the original TC04: the mapping changes only the column names, never the values.

## 5. Corrected submission

Upload `07_Dunmore_Payments_Ltd_September_2026_TC04_corrected.zip` as a **new case** for `Dunmore Payments Ltd`. The firm has now booked the €650 credit in its cash book. Expected result: **CLEAN**, 0 exceptions. This ZIP needs no mapping.

## Verified

23 Nov 2026, on the current analyst app (test server, same code as the demo server):
- **Through the API:** Smart Parser asked for the 4-column IN-11 review and refused `settlement_batches_2026-09.csv`. The IN-12 re-upload gave a 13-column review. Reconciliation produced **2 exceptions**, `UNMATCHED_BANK_ENTRY|BE-EUR-0930-U01` (High) and `BANK_LEDGER_DIFFERENCE|SGA-EUR-01|2026-09-30|650.00` (Critical), and both AI findings were published.
- **In the browser:** the Overview, Smart Parser, Evidence and mapping review pages were checked up to the mapping step.

The original TC04 ZIP (no mapping) is still in `Downloads\UC042_TEST_DATASETS\05_TC04_UNMATCHED_BANK_CREDIT\TC04_initial_submission.zip`.
