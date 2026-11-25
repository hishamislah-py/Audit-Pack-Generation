# Generation notes — Set 1 clean baseline

> **ILLUSTRATIVE SYNTHETIC CONVENTIONS (decision D6).** Every value, timing rule, reference pattern, fee treatment and
> account arrangement below is an illustrative convention for the UC-042 POC. None is a confirmed Moorwand practice.

**Command:** `python -m uc042lib.generate` (from `uc042/`). Seed `20260930`. The PDFs are written with ReportLab invariant mode, so repeated runs produce byte-identical files. `tests/test_baseline.py::Determinism` checks this against `manifest.csv`.

**Money.** Integer cents internally; written as 2 dp decimal strings. Acquirer fees are 0.30% and 0.155% of gross, rounded half-up to the cent. The exception is `AQ-GBP-20260908`, fixed by the spec at £30.00 and £15.50. No binary floating point is used for money.

## Scope (synthetic conventions)

- **Entity:** `SYN-EMI-001`, pool `POOL-EMONEY`, segregation, standard method.
- **Period:** 1–30 Sep 2026, with 22 reconciliation days (UK weekdays; no UK bank holidays in September; no foreign-market closures assumed).
- **Reconciliation point:** 17:00 Europe/London.
- **Accounts:** at Example Bank plc (fictional): `SGA-GBP-01`, `SGA-EUR-01`, `OWN-GBP-01`, `OWN-EUR-01`.
- **Opening position, 31 Aug 2026 17:00:** SGA-GBP-01 £250,000.00 and SGA-EUR-01 €80,000.00 (equal to client totals, ledger and bank). Own funds: £500,000.00 and €150,000.00, synthetic.
- **Opening client snapshot (D4):** 12 rows `CBS-20260831-<client>-<ccy>` at 31 Aug 17:00 in `client_balance_snapshots_2026-09.csv`. GBP C0001–C0008 total £250,000.00; EUR C0101–C0104 total €80,000.00. This is a permitted boundary record for the September period, so the 1 Sep client roll-forward can be checked.

## Daily activity (each reconciliation day)

| Flow | GBP | EUR | Records produced |
| --- | --- | --- | --- |
| Bank-transfer loads (1:1) | 2 (09:10, 11:40) | 1 (10:00) | Bank credit, cash-book debit and LOAD_BANK transaction, all sharing an end-to-end reference |
| Card loads | 4 | 2 | LOAD_CARD transactions (client credited at load); acquirer batch `AQ-*` credited at 14:00 net of two fee lines |
| Own-funds top-up of acquirer fees | 14:30 | 14:30 | Own-account debit, safeguarding credit and cash-book debit, all with reference `TOPUP-<ccy>-<date>` |
| Card spends | 6 | 3 | SPEND transactions; scheme batch `SB-*` debited at 15:00; client debited at 15:00 (convention D8) |
| Refunds | `TX-0909-0R001` (refunds `TX-0902-00044`) | `TX-0916-0R001` | REFUND line in the scheme batch; client credited at 15:00 |
| Redemptions | alternate days, 16:00 | alternate days, 16:00 | Bank debit, cash-book credit and REDEMPTION transaction |
| Unallocated receipts | `UR-0001` £750.00, 11 Sep 16:30 → C0007 on 14 Sep 09:30 | `UR-0002` €400.00, 23 Sep 16:10 → C0102 on 24 Sep 09:15 | Bank credit and cash-book entry on receipt; register row; LOAD_BANK transaction on allocation |

Scheme fees on spends are assumed to be billed to own-funds accounts outside this dataset. No record for them is generated.

## Roll-forward

For each currency, all three views move together:

- the cash book balance at 17:00 (item A);
- the bank balance;
- Σ client balances + open unallocated receipts (the requirement).

So requirement = resource and bank = ledger at every point. The generator asserts this while building. The validator independently re-derives it from the files.

All baseline bank entries book before 17:00, so each 17:00 confirmation equals the end-of-day closing balance.

## Known limitations (synthetic, by design)

- Reported values in IN-05 and IN-06 come from the same simulation that produced the source records. Validation proves the files are mutually consistent; it cannot prove operational truth.
- Items B–D are 0.00 and D+1 columns are blank (gaps G-S04, G-R05).
- PDFs use generic, labelled wording. The CASS 15.7 letter template and the REP027 template were not reviewed.
