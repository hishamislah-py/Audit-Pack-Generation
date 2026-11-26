# TC03 revision 3: change record (25/26 Sep → 24/25 Sep)

**Date:** 23 Nov 2026. This revision was decided by the user.

**Old version.** Revision 2 is preserved unchanged in `archive/rev2_tc03_25_26_sep_20261123/`: the dataset, ZIPs, reports and tools.

**Scope.** Only TC03 was regenerated (`generate_suite.py --only TC03`). A hash comparison against a snapshot taken beforehand shows `shared_baseline/` and TC01, TC02, TC04, TC05 and TC06 byte-identical.

## Decision

| Item | Revision 2 | Revision 3 |
|---|---|---|
| Item | AQ-GBP-20260925 | AQ-GBP-20260924 |
| Recorded | Fri 25 Sep 14:00 | Thu 24 Sep 14:00 |
| Bank credit | Sat 26 Sep 08:00 | Fri 25 Sep 08:00 (next business day) |
| Amount | 4,647.75 | **5,495.05** |
| Weekend records | 3 (IN-07, IN-08, IN-09 on 26 Sep) | none |

The amount changed because 4,647.75 is the net of the 25 Sep batch, whose card loads were made on 25 Sep. The user chose the 24 Sep batch, which keeps every record consistent, over re-dating or rewriting a batch.

## File-level comparison (initial submission)

| File | Revision 2 SHA-256 | Revision 3 SHA-256 | Baseline? |
|---|---|---|---|
| IN-06 `external_recon_records_2026-09.csv` | `f9816157b6856281` | `224885675830cf1b` | mutated |
| IN-07 `bank_balance_confirmations_2026-09.csv` | `6ed5b87da2a81e62` | `9bdef964d6ee6d36` | mutated |
| IN-08 `bank_statements_eod_2026-09.csv` | `c76d26add88a7dd3` | `87ca9cf00bf13f60` | mutated |
| IN-09 `bank_statement_entries_2026-09.csv` | `c9ec654b681625f8` | `86b4bd9af248b753` | mutated |
| IN-14 `discrepancy_log_2026-09.csv` | `13bfa63e575e58c9` | `51087db5e783a4ac` | mutated |

Files not listed are byte-identical to the baseline in both revisions.

## Record-level before/after (revision 2 → revision 3)

| File | Record | Field | Revision 2 | Revision 3 |
|---|---|---|---|---|
| IN-06 | `ERL-SGA-GBP-01-20260924` | bank_balance_reported | 370603.29 | 365108.24 |
| IN-06 | `ERL-SGA-GBP-01-20260924` | difference_reported | 0.00 | -5495.05 |
| IN-06 | `ERL-SGA-GBP-01-20260924` | timing_difference_claimed | false | true |
| IN-06 | `ERL-SGA-GBP-01-20260925` | bank_balance_reported | 370813.71 | 375461.46 |
| IN-06 | `ERL-SGA-GBP-01-20260925` | difference_reported | -4647.75 | 0.00 |
| IN-06 | `ERL-SGA-GBP-01-20260925` | timing_difference_claimed | true | false |
| IN-07 | `ST-SGA-GBP-01-20260924-1700` | balance_amount | 370603.29 | 365108.24 |
| IN-07 | `ST-SGA-GBP-01-20260925-1700` | balance_amount | 370813.71 | 375461.46 |
| IN-07 | `ST-SGA-GBP-01-20260926-1700` | (record) | present | **removed** |
| IN-08 | `ST-SGA-GBP-01-20260924-EOD` | closing_balance_amount | 370603.29 | 365108.24 |
| IN-08 | `ST-SGA-GBP-01-20260924-EOD` | entry_count | 6 | 5 |
| IN-08 | `ST-SGA-GBP-01-20260925-EOD` | closing_balance_amount | 370813.71 | 375461.46 |
| IN-08 | `ST-SGA-GBP-01-20260925-EOD` | entry_count | 4 | 6 |
| IN-08 | `ST-SGA-GBP-01-20260925-EOD` | opening_balance_amount | 370603.29 | 365108.24 |
| IN-08 | `ST-SGA-GBP-01-20260926-EOD` | (record) | present | **removed** |
| IN-09 | `BE-GBP-0924-AQ1` | (record) | present | **removed** |
| IN-09 | `BE-GBP-0925-AQ1` | (record) | absent | **added** after `BE-GBP-0925-L02`: ST-SGA-GBP-01-20260925-EOD, SGA-GBP-01, 2026-09-25, 2026-09-25T14:00:00+01:00, 2026-09-25, 4647.75, C, GBP, AQ-GBP-20260925, , Synthetic Acquirer Ltd, CARD LOAD SETTLEMENT AQ-GBP-20260925 |
| IN-09 | `BE-GBP-0925-T01` | (record) | absent | **added** after `BE-OWN-EUR-0924-TU1`: ST-SGA-GBP-01-20260925-EOD, SGA-GBP-01, 2026-09-25, 2026-09-25T08:00:00+01:00, 2026-09-25, 5495.05, C, GBP, AQ-GBP-20260924, , Synthetic Acquirer Ltd, CARD LOAD SETTLEMENT AQ-GBP-20260924 |
| IN-09 | `BE-GBP-0926-T01` | (record) | present | **removed** |
| IN-14 | `DL-0001` | amount | -4647.75 | -5495.05 |
| IN-14 | `DL-0001` | cause_evidence_ref | BE-GBP-0926-T01 | BE-GBP-0925-T01 |
| IN-14 | `DL-0001` | description | Acquirer settlement AQ-GBP-20260925 not credited by the bank by 17:00; expected next banking day | Acquirer settlement AQ-GBP-20260924 not credited by the bank by 17:00; expected next business day |
| IN-14 | `DL-0001` | logged_ts | 2026-09-25T18:05:00+01:00 | 2026-09-24T18:05:00+01:00 |
| IN-14 | `DL-0001` | recon_ref | ERL-SGA-GBP-01-20260925 | ERL-SGA-GBP-01-20260924 |
| IN-14 | `DL-0001` | resolved_ts | 2026-09-28T09:00:00+01:00 | 2026-09-25T09:00:00+01:00 |

**Revision-2 records restored to the baseline:**

- the 25 Sep acquirer entry BE-GBP-0925-AQ1;
- the 25 Sep statement and confirmation balances;
- ERL-SGA-GBP-01-20260925.

**Removed outright:** the Saturday statement, the Saturday confirmation and the Saturday clearing entry.

## Independent validator findings

| Revision 2 (7) | Revision 3 |
|---|---|
| `BATCH_LAG AQ-GBP-20260925 settlement=2026-09-25 booked=2026-09-26` | `BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25` |
| `BL_DIFF 2026-09-25 SGA-GBP-01 -4647.75` | `BL_DIFF 2026-09-24 SGA-GBP-01 -5495.05` |
| `BL_DIFF_LOGGED 2026-09-25 SGA-GBP-01 DL-0001` | `BL_DIFF_LOGGED 2026-09-24 SGA-GBP-01 DL-0001` |
| `NON_RECON_DAY_RECORD IN-07 ST-SGA-GBP-01-20260926-1700 2026-09-26` | `TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05` |
| `NON_RECON_DAY_RECORD IN-08 ST-SGA-GBP-01-20260926-EOD 2026-09-26` |  |
| `NON_RECON_DAY_RECORD IN-09 BE-GBP-0926-T01 2026-09-26` |  |
| `TIMING LE-GBP-0925-0003/BE-GBP-0926-T01 ref=AQ-GBP-20260925 recorded=2026-09-25 bank=2026-09-26 amount=4647.75` |  |

**Saturday-related findings in revision 3:** 0 (none).
**Structure errors in revision 3:** 0.

## ENGINE-PREDICTED (source reading only; not executed)

| | Revision 2 | Revision 3 |
|---|---|---|
| Non-passing | [['C08-DIFFERENCE', '2026-09-25/SGA-GBP-01', 'FAIL']] | [['C08-DIFFERENCE', '2026-09-24/SGA-GBP-01', 'FAIL']] |
| Exceptions | ['BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-25|-4647.75'] | ['BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-24|-5495.05'] |
| Evidence status | {'EXC-TC03-01': 'TIMING_EVIDENCED'} | {'EXC-TC03-01': 'TIMING_EVIDENCED'} |
| Case status | EXCEPTIONS_OPEN | EXCEPTIONS_OPEN |

## Upload ZIP

- Revision 2 `TC03_initial_evidence_upload.zip`: `fbb372cc0c527fa33aa39901ed5837974ea08cc6550a281481e29979f0f1b029`
- Revision 3 `TC03_initial_evidence_upload.zip`: `93c4a11f7c3bbf5aafcf4ac1586142673c0a5e2c07ac92955aa751877d661146`

**Correction:** TC03 has no correction dataset in either revision, so there is nothing further to keep consistent.
