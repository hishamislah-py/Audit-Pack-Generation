# Halden Brook Payments Ltd, September 2026: the full demo in one run

> **Illustrative synthetic data.** Fictional customer and bank; not real financial records.

One upload shows every feature:
- Smart Parser asks for a **column mapping**;
- a **missing file** is uploaded separately;
- the reconciliation finds **two different problems**;
- the AI investigates them;
- you accept or reject the findings and generate the **audit pack PDF**.

Upload the files exactly as supplied. Do not open and re-save them in Excel.

## 1. Upload

1. Dashboard → **Upload a submission** → customer `Halden Brook Payments Ltd`.
2. Choose `15_Halden_Brook_Payments_Ltd_September_2026.zip`. The period shows **September 2026** automatically.
3. Click **Upload and start**.

Smart Parser processes 18 files and stops for you with two items:

| What you see | Why |
|---|---|
| **IN-11 Client transactions needs a mapping review (4 columns)** | The firm's export wrote `TXN_ID`, `Client_ID`, `␣amount␣` and `CURRENCY` instead of the standard names. Smart Parser never accepts a renamed column on its own: a person confirms it. |
| **IN-13 Settlement lines is missing** | The file was not in the ZIP. |

## 2. Map the 4 columns

1. Smart Parser tab → **Review mapping**.
2. For each column: click the row → **Map** (the suggested field) → **Record decision**.

   | Column in the file | Map to |
   |---|---|
   | `TXN_ID` | `txn_id` |
   | `Client_ID` | `client_id` |
   | `␣amount␣` | `amount` |
   | `CURRENCY` | `currency` |

3. Click **Confirm file** → confirm.

## 3. Upload the missing file

1. Evidence tab → **Upload missing or corrected file** → **IN-13 Settlement lines**.
2. Choose `15_Halden_Brook_Payments_Ltd_September_2026_upload_later\settlement_lines_2026-09.csv`.
3. Click **Upload and process**.

Its columns are already correct, so **no mapping is needed**; it is accepted straight away. If reconciliation does not start by itself, click **Activate package** → **Run reconciliation**.

## 4. Reconciliation: two different problems

Result: **EXCEPTIONS OPEN, 7 exceptions in 2 groups.** AI investigations start at once, for all exceptions in parallel.

The Reconciliation tab shows **"Not everything checks out"**: a system-generated statement with a ✓ or ✗ for each area.

**Problem 1: a duplicate entry (GBP)**
- The firm recorded the same £1,684.33 bank load of 30 Sept **twice** in its cash book.
- The bank received the money only once.
- The cash book is therefore £1,684.33 too high, and every check on that balance fails.

| Exception | What it is |
|---|---|
| Duplicate cash-book entry `LE-GBP-0930-0007` | **The cause**: the second copy of `LE-GBP-0930-0001` |
| Bank and ledger difference, SGA-GBP-01, 30 Sept (−£1,684.33) | Effect: the bank shows £1,684.33 less than the cash book |
| Internal difference, 30 Sept GBP | Effect |
| Safeguarding resource, 30 Sept GBP | Effect |
| Firm ledger balance, 30 Sept SGA-GBP-01 | Effect |

**How it is handled:** the firm deletes the duplicate row from its cash book. The real money is fine; only the records are wrong.

**Problem 2: a missing entry (EUR)**
- €1,275.40 arrived in the EUR safeguarding account on 30 Sept (`BE-EUR-0930-U01`).
- The firm never recorded it in its cash book.

| Exception | What it is |
|---|---|
| Bank entry with no cash-book entry `BE-EUR-0930-U01` | **The cause** |
| Bank and ledger difference, SGA-EUR-01, 30 Sept (+€1,275.40) | Effect: the bank shows €1,275.40 more than the cash book |

**How it is handled:** the firm finds out what the credit is and records it. Until then, the client-money requirement may be understated by €1,275.40.

The two problems are on different accounts and in different currencies, and the engine keeps them in separate groups.

## 5. Decisions and the audit pack

1. Open each exception and choose **Accept** or **Reject**. A note is optional; a rejection keeps the AI text out of the PDF.
2. Go to **Closing & Audit Pack** → **Generate audit pack** (one click).
3. Download the PDF. Section 1 shows the reconciliation statement and both problems; the sign-off section shows your decisions.

## Verified

24 Nov 2026, on the current app (test server, same code as the demo server), through the API:
- **Smart Parser:** the IN-11 mapping review (4 columns) and the missing IN-13 file, uploaded with no mapping.
- **Reconciliation:** 7 exceptions in 2 engine groups.
- **AI:** all 7 investigations published.
- **Decisions:** 6 accepted and 1 rejected.
- **Audit pack:** generated and verified; the analyst PDF has 9 pages.
