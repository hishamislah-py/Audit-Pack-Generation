# Continuity report — January–August 2026

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

Generated from `verification/data_quality_results.json`. All figures are read from the month files, not from the generator.

## January opening position (synthetic, as at 31 Dec 2025 17:00 GMT)

A **documented synthetic demonstration opening position**, chosen for this package (not derived from any real or earlier record):

| Position | GBP | EUR |
| --- | ---: | ---: |
| Client balances (Σ, IN-03 `CBS-20251231-*`) | 223,400.00 | 71,100.00 |
| Cash book (IN-10 `LE-*-1231-0000` OPENING_BALANCE) | 223,400.00 | 71,100.00 |
| Safeguarding bank (first statement opening) | 223,400.00 | 71,100.00 |
| Own-funds bank (first statement opening) | 504,136.00 | 151,082.84 |

Own-funds openings were derived so that, after eight months of fee top-ups, August closes on the existing September own-funds openings (£500,000.00 / €150,000.00). No unallocated receipt is open at any month end.

## Month-to-month carry-forward

Closing = last reconciliation day at 17:00 (client snapshots), the cash-book balance, and each account's last end-of-day statement. Opening = the next month's opening snapshot, cash-book OPENING_BALANCE and first statement opening.

| From → to | Client balances (12) | Cash book GBP / EUR | Bank SGA-GBP / SGA-EUR / OWN-GBP / OWN-EUR | Closing GBP clients | Closing EUR clients |
| --- | --- | --- | --- | ---: | ---: |
| 2026-01 → 2026-02 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 223,716.25 | 71,684.56 |
| 2026-02 → 2026-03 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 226,582.78 | 74,438.89 |
| 2026-03 → 2026-04 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 234,895.94 | 73,596.75 |
| 2026-04 → 2026-05 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 233,363.67 | 76,625.44 |
| 2026-05 → 2026-06 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 243,697.66 | 76,057.81 |
| 2026-06 → 2026-07 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 240,772.97 | 78,458.92 |
| 2026-07 → 2026-08 | ✓ | ✓ / ✓ | ✓ / ✓ / ✓ / ✓ | 246,625.89 | 78,726.28 |

## August → September boundary (existing September data, unchanged)

August's last reconciliation day is Friday 28 Aug 2026 (31 Aug is a bank holiday). The existing September dataset (`set_01_clean_baseline`) opens at 31 Aug 2026 17:00 BST. No activity occurs between, so the positions must be equal.

| Position | August closing (this package) | September opening (existing) | Match |
| --- | ---: | ---: | --- |
| Client C0001/GBP | 40,000.00 | 40,000.00 | ✓ |
| Client C0002/GBP | 35,000.00 | 35,000.00 | ✓ |
| Client C0003/GBP | 32,500.00 | 32,500.00 | ✓ |
| Client C0004/GBP | 30,000.00 | 30,000.00 | ✓ |
| Client C0005/GBP | 30,000.00 | 30,000.00 | ✓ |
| Client C0006/GBP | 28,500.00 | 28,500.00 | ✓ |
| Client C0007/GBP | 27,500.00 | 27,500.00 | ✓ |
| Client C0008/GBP | 26,500.00 | 26,500.00 | ✓ |
| Client C0101/EUR | 25,000.00 | 25,000.00 | ✓ |
| Client C0102/EUR | 20,000.00 | 20,000.00 | ✓ |
| Client C0103/EUR | 18,000.00 | 18,000.00 | ✓ |
| Client C0104/EUR | 17,000.00 | 17,000.00 | ✓ |
| Cash book GBP | 250,000.00 | 250,000.00 | ✓ |
| Cash book EUR | 80,000.00 | 80,000.00 | ✓ |
| Bank SGA-GBP-01 | 250,000.00 | 250,000.00 | ✓ |
| Bank SGA-EUR-01 | 80,000.00 | 80,000.00 | ✓ |
| Bank OWN-GBP-01 | 500,000.00 | 500,000.00 | ✓ |
| Bank OWN-EUR-01 | 150,000.00 | 150,000.00 | ✓ |

**Result: all 18 positions match exactly. September was read, never modified.**

**How the boundary is met:** on 28 Aug 2026 at 16:40 the generator adds one ordinary bank-transfer load or redemption per client (references `E2E-<ccy>-0828-Bnn`) for the difference between that client's balance and the September opening figure. These are normal 1:1 synthetic movements (bank, cash book and transaction together), not adjustments. Planted discrepancies are designed to leave no unresolved bank-ledger difference at a month end (see README, assumption A2).

