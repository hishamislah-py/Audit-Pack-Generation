# 03 — Data Integrity and Provenance Review

Assessment date: 30 Oct 2026. The checks were run directly on `uc042_dataset/set_01_clean_baseline` with code that does not use the project engine:

- `docs/review/independent_audit.py`, which shares no code with the generator or validator;
- additional throwaway queries for keys, references and dates.

Nothing was modified.

## 1. Integrity results

| Check | Result |
| --- | --- |
| File count | 14 CSV + 5 PDF per dataset (3 datasets) |
| Row count | **1,940** CSV data rows (header excluded), equal to the per-file sum; 1,954 physical lines. The "1,898" total was a chat arithmetic error; no file contains it. |
| Duplicate primary keys | **0** in all 14 files |
| Orphan references | **0** across seven foreign-key links: entries → statements; account IDs in 6 files → inventory; external records → confirmations; lines → batches; lines → transactions; transactions → batches; refunds → originals |
| Currency consistency | Every record's currency equals its account's or batch's currency; nothing combines GBP and EUR |
| D/C and signed amounts | Bank C = in; cash book D = in (opposite perspective, correct for every entry type); client CR = up; settlement C = to the firm. Re-implemented independently and agreed on every record. |
| Money format | All values 2 dp; no signs in unsigned columns (0 violations) |
| Dates and period | 3,286 dated values in September 2026. The only exceptions are the 2 permitted 31 Aug 17:00 cash-book opening rows. All timestamps carry `+01:00` (BST). |
| Bank arithmetic and continuity | 88/88 statements (opening + entries = closing); 84/84 day-to-day continuity; 44/44 confirmations = opening + entries booked by 17:00 |
| Settlement and fee arithmetic | 88/88 batches: lines reconcile to reported totals and to the bank entry by reference. 44/44 fee top-ups. 332/332 card transactions in exactly one line of their batch. |
| Client balances and transactions | Requirement 44/44 equal to reported; client roll-forward 252/252 day-pairs; **1 Sep not assessable** (no 31 Aug client snapshot); no negative balances |
| Missing evidence treated as zero or success? | **No.** Missing files and records produce INSUFFICIENT_EVIDENCE (verified by the S02 dataset and 83 tests). An absent record is never summed as zero. |

## 2. Evidence classes

| Class | What falls in it |
| --- | --- |
| **Verified source evidence** | **None.** No genuine Moorwand data has been supplied. |
| **Synthetic source evidence** | All 14 CSVs and 5 PDFs: client snapshots, register, bank statements and entries, cash book, transactions, settlement reports, letters and policy |
| **Synthetic *reported* values** (the firm's or counterparty's claims inside the evidence) | IN-05 and IN-06 reconciliation figures; IN-12 batch totals; IN-06 `timing_difference_claimed` |
| **Deterministically calculated results** | `validation/control_results.csv` (computed values), `validation/exceptions.csv`, case status. Kept separate from reported values in every result row. |
| **AI-generated interpretations** | **None exist** |
| **Missing or unverified** | Resource items B–D (taken as reported 0.00); D+1 comparison (not performed); opening client balances; PDF key details (parsed, no human confirmation) |

## 3. Derived values presented as source evidence

These are not errors, since the model labels them "reported". They do matter for how much assurance a pack can claim:

| Field | How it was produced | Effect |
| --- | --- | --- |
| IN-05 `requirement_reported`, `resource_reported`, `item_a` | Written by the generator from the same simulated balances that produced IN-03 and IN-10 | Reported versus recomputed agreement is guaranteed by construction |
| IN-06 `ledger_balance_reported`, `bank_balance_reported` | Written from the generator's running bank and cash totals | Same |
| IN-12 `gross_amount`, `total_fees`, `net_amount_reported` | Summed by the generator from the lines it wrote | Header versus lines cannot disagree unless mutated |
| IN-07 `balance_amount` | Taken from the same running bank balance as the IN-08 closing | Equal in 44/44 cases |
| IN-10 cash book versus IN-09 bank | Both written from one generated event: same reference, amount and timestamp (222/222) | The ledger can never differ from the bank in the baseline |

## 4. Inconsistencies, missing references, unsupported assumptions

**Data inconsistencies: none found.**

**Documentation inconsistencies** (no data impact):

- The body of `UC042_INPUT_EVIDENCE_SPEC_V1.md` still lists dropped columns (`balance_ref`; IN-10 `value_date`, `batch_id`, `txn_id`).
- It still marks IN-18/IN-19 "Conditional".
- It describes the policy PDF as 2 pages; it is 1.

**Unsupported or untested assumptions** (synthetic conventions, not Moorwand facts):

- Transaction timing D8.
- The 17:00 point.
- Per-currency internal reconciliation.
- No foreign-market closures.
- Fees deducted inside safeguarding accounts and topped up the same day.
- Scheme fees billed outside the safeguarding accounts.
- References carrying batch IDs or end-to-end IDs.
- Items B–D are zero.
- D+1 not required.
- Period conventions P1 and P2.

**Not exercised by the clean baseline:**

- bank entries after 17:00;
- next-day bookings and value-date differences;
- negative client balances;
- multiple balances per client;
- receipts crossing the period boundary;
- bank-account fees.

## 5. Provenance and traceability

- Every file has a SHA-256 in `manifest.csv`, and every evidence file still matches its recorded hash.
- Every check result cites `IN-xx:file#Lline`.
- `python -m uc042lib.trace` resolves a record or an exception to its rows.
- Cases built by `prepare` also keep `intake.csv` (original file name, hash, decision). The three committed datasets were generated directly, so they have no `intake.csv`.
