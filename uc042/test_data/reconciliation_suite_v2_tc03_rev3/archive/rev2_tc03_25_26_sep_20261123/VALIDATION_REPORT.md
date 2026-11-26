# UC-042 Reconciliation Test Suite V2: Offline Validation Report (Stage E)

**Overall result: PASS.** Date: 23 Nov 2026. Validator: `tools/validate_suite.py`. Negative tests: `tools/negative_tests.py`.

> **Scope.** This validates the **generated datasets and answer keys** only. No UC-042 engine, application or AI was executed. Nothing here shows how the engine behaves: every ENGINE-PREDICTED outcome remains unverified.

## 1. Independence

- The validator imports no engine code.
- The schema contract comes from an `ast` read of the reference `schema.py`. Every reconciliation calculation, matching rule and period rule is a separate implementation written for this suite.
- The FIN answer keys were written by hand from the specification (`tools/scenario_specs.py`) and **not** derived from the generated files. The validator recomputes everything from the files and requires:
  - an **exact** set equality between its findings and the key's `expected_anomalies` (no missing and no extra finding);
  - exact equality of every key figure.
- **Control:** the clean baseline must produce zero structure errors and zero findings.

## 2. Checks performed

| Group | Checks |
|---|---|
| Structure | Exact canonical headers; UTF-8, no BOM, LF; row width; mandatory fields; type formats (amount, signed, date, ts with offset, bool, int, ccy, id); 20 enum sets; 11 conditional rules; unique primary keys; empty-file rule |
| Period | September membership per evidence type; permitted 31 Aug boundary rows; IN-04 open during period; IN-14 event reference and not logged before its reconciliation |
| References | Accounts, statements, bank_statement_id, batches, pools, IN-14 recon_ref |
| Recomputation | Bank (IN-07) vs ledger at 17:00 per account and day; requirement (Σ non-negative snapshots + open register) and resource; every IN-05/IN-06 reported value; client roll-forward for every consecutive snapshot pair; statement arithmetic, entry counts, parent consistency and continuity; 17:00 confirmation vs statement; batch arithmetic (TXN, FEE, REFUND, signed NET); line ↔ transaction; card transaction in exactly one line; batch ↔ bank (count, amount, booking lag); own-funds top-ups; cash book ↔ bank by reference (missing, multiple, amount, cross-day timing); **many-to-one claims** (duplicates); bank entries without counterpart; direct loads and redemptions ↔ bank; register matching and allocation deadline; refunds; currency; daily coverage; discrepancy-log coverage of every bank-ledger difference; records on non-reconciliation days |
| Mutations | Row-level diff against the baseline (corrections: against the initial submission) must equal `mutations.json` exactly; files not named in any operation are byte-identical; unchanged rows keep their exact text and order; PDFs identical to the baseline; corrected TC01 and TC05 files byte-identical to the baseline |
| Packaging | `manifest.csv` SHA-256 and record counts; `scenario.json` identity; no `answer_key.json` in case roots; upload ZIP = exactly the 19 canonical names with bytes identical to the case, CRC-clean; ENGINE-PREDICTED JSON consistency (sequential IDs, Σ affected_results = non-passing results, groups and candidates reference existing exceptions, CLEAN ⇔ no non-passing results, label NOT EXECUTED); FUTURE and AI files present and labelled |

## 3. Results by case

| Case | Status | Structure errors | Findings (= FIN key) | FIN figures checked | Changes verified | Manifest / ZIP / JSON |
|---|---|---|---|---|---|---|
| CONTROL: clean baseline must produce no structure errors and no findings | **PASS** | 0 | 0 (exact match) | 0 | - | - |
| TC01 initial submission | **PASS** | 0 | 25 (exact match) | 12 | 1 | OK |
| TC01 corrected case | **PASS** | 0 | 0 (exact match) | 3 | 1 | OK |
| TC02 initial submission | **PASS** | 0 | 2 (exact match) | 4 | 1 | OK |
| TC03 initial submission | **PASS** | 0 | 7 (exact match) | 8 | 11 | OK |
| TC04 initial submission | **PASS** | 0 | 3 (exact match) | 4 | 6 | OK |
| TC04 corrected case | **PASS** | 0 | 0 (exact match) | 4 | 7 | OK |
| TC05 initial submission | **PASS** | 0 | 5 (exact match) | 6 | 3 | OK |
| TC05 corrected case | **PASS** | 0 | 0 (exact match) | 2 | 3 | OK |
| TC06 initial submission | **PASS** | 0 | 8 (exact match) | 8 | 5 | OK |

## 4. Findings recomputed from the generated data (each equals the FIN key exactly)

**TC01 initial submission**

- `BANK_MULTI_CLAIM BE-GBP-0928-L01 IN-10=LE-GBP-0928-0001,LE-GBP-0928-0007`
- `BL_DIFF 2026-09-28 SGA-GBP-01 -1246.80`
- `BL_DIFF 2026-09-29 SGA-GBP-01 -1246.80`
- `BL_DIFF 2026-09-30 SGA-GBP-01 -1246.80`
- `BL_DIFF_NOT_LOGGED 2026-09-28 SGA-GBP-01`
- `BL_DIFF_NOT_LOGGED 2026-09-29 SGA-GBP-01`
- `BL_DIFF_NOT_LOGGED 2026-09-30 SGA-GBP-01`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 item_a reported=378706.65 recomputed=379953.45`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 resource_reported reported=378706.65 recomputed=379953.45`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 item_a reported=388744.47 recomputed=389991.27`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 resource_reported reported=388744.47 recomputed=389991.27`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 item_a reported=395844.86 recomputed=397091.66`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 resource_reported reported=395844.86 recomputed=397091.66`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260928 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260928 ledger_balance_reported reported=378706.65 recomputed=379953.45`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260929 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260929 ledger_balance_reported reported=388744.47 recomputed=389991.27`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260930 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260930 ledger_balance_reported reported=395844.86 recomputed=397091.66`
- `RR_DIFF 2026-09-28 GBP 1246.80`
- `RR_DIFF 2026-09-29 GBP 1246.80`
- `RR_DIFF 2026-09-30 GBP 1246.80`

**TC01 corrected case**

- none (consistent dataset)

**TC02 initial submission**

- `ROLLFWD GBP/C0006 2026-09-08 18.00`
- `TXN_BANK_AMOUNT TX-0908-00002 ref=E2E-GBP-0908-L02 txn=3053.61 bank=3035.61`

**TC03 initial submission**

- `BATCH_LAG AQ-GBP-20260925 settlement=2026-09-25 booked=2026-09-26`
- `BL_DIFF 2026-09-25 SGA-GBP-01 -4647.75`
- `BL_DIFF_LOGGED 2026-09-25 SGA-GBP-01 DL-0001`
- `NON_RECON_DAY_RECORD IN-07 ST-SGA-GBP-01-20260926-1700 2026-09-26`
- `NON_RECON_DAY_RECORD IN-08 ST-SGA-GBP-01-20260926-EOD 2026-09-26`
- `NON_RECON_DAY_RECORD IN-09 BE-GBP-0926-T01 2026-09-26`
- `TIMING LE-GBP-0925-0003/BE-GBP-0926-T01 ref=AQ-GBP-20260925 recorded=2026-09-25 bank=2026-09-26 amount=4647.75`

**TC04 initial submission**

- `BANK_NO_COUNTERPART BE-EUR-0930-U01 ref=E2E-EUR-0930-U01`
- `BL_DIFF 2026-09-30 SGA-EUR-01 650.00`
- `BL_DIFF_NOT_LOGGED 2026-09-30 SGA-EUR-01`

**TC04 corrected case**

- none (consistent dataset)

**TC05 initial submission**

- `LINE_TXN SL-SB-EUR-20260924-0001 TX-0924-00018 missing`
- `LINE_TXN SL-SB-EUR-20260924-0002 TX-0924-00019 missing`
- `LINE_TXN SL-SB-EUR-20260924-0003 TX-0924-00020 missing`
- `ROLLFWD EUR/C0101 2026-09-24 625.27`
- `ROLLFWD EUR/C0104 2026-09-24 222.18`

**TC05 corrected case**

- none (consistent dataset)

**TC06 initial submission**

- `BATCH_ARITH AQ-EUR-20260922 NET lines=2059.53 header=2104.53`
- `BATCH_ARITH AQ-EUR-20260922 TXN lines=2069.15 header=2114.15`
- `LINE_TXN SL-AQ-EUR-20260922-0002 TX-0922-00016 amount line=1238.12 txn=1283.12`
- `ROLLFWD GBP/C0004 2026-09-17 -90.00`
- `ROLLFWD GBP/C0004 2026-09-18 90.00`
- `ROLLFWD GBP/C0007 2026-09-17 90.00`
- `RR_DIFF 2026-09-17 GBP -90.00`
- `TXN_BANK_AMOUNT TX-0917-00002 ref=E2E-GBP-0917-L02 txn=1480.07 bank=1390.07`

## 5. Negative tests (the validator must reject deliberately broken copies)

| Test | Rejected | Detected by | Sample |
|---|---|---|---|
| unrelated amount change (TC02: bank entry BE-GBP-0901-L01) | yes | fin_unexpected_findings | `CASH_BANK_AMOUNT LE-GBP-0901-0001/BE-GBP-0901-L01 ledger=2926.33 bank=2926.34` |
| header renamed (TC02: IN-11 amount -> amt) | yes | structure_errors | `IN-11 header differs from the canonical schema` |
| invalid enum (TC04: dc_indicator X) | yes | structure_errors | `IN-09 L266 dc_indicator='X': not one of ['C', 'D']` |
| Saturday 17:00 confirmation removed (TC03) | yes | fin_missing_findings, fin_figure_mismatches | `NON_RECON_DAY_RECORD IN-07 ST-SGA-GBP-01-20260926-1700 2026-09-26` |
| duplicate posting removed (TC01 initial no longer shows the duplicate) | yes | fin_missing_findings | `BANK_MULTI_CLAIM BE-GBP-0928-L01 IN-10=LE-GBP-0928-0001,LE-GBP-0928-0007` |
| amount format 1,390.07 (TC06) | yes | structure_errors | `IN-11 L241 amount='1,480.07': invalid amount` |

## 6. Financial differences confirmed

| Scenario | Confirmed from the data |
|---|---|
| TC01 | bank − ledger −1,246.80 and resource − requirement +1,246.80 on 28, 29 and 30 Sep; bank entry BE-GBP-0928-L01 claimed by two cash-book rows; reported IN-05/IN-06 values match the bank, not the extract |
| TC02 | TX-0908-00002 3,053.61 vs bank 3,035.61 (+18.00); C0006 8 Sep roll-forward +18.00; 9 Sep reconciles |
| TC03 | 25 Sep 17:00 bank 370,813.71 vs ledger 375,461.46 (−4,647.75, reported and logged); timing pair LE-GBP-0925-0003 / BE-GBP-0926-T01 (25 → 26 Sep); 26 and 28 Sep bank = ledger; batch lag 1 day |
| TC04 | bank − ledger +650.00 on 30 Sep EUR; BE-EUR-0930-U01 has no counterpart; no log entry. Corrected: consistent, requirement and resource 119,205.00 |
| TC05 | C0101 +625.27 and C0104 +222.18 roll-forward gaps; 3 lines reference missing transactions. Corrected: byte-identical to the baseline IN-11 |
| TC06 | A: +90.00 (TX-0917-00002, C0007); B: C0004 −90.00 on 17 Sep and +90.00 on 18 Sep, internal −90.00; C: AQ-EUR-20260922 TXN −45.00 and NET −45.00, line vs transaction |

## 7. Unresolved issues and assumptions

1. **ENGINE-PREDICTED outcomes are unverified** for all six scenarios. Above all, TC06's predicted over-grouping (G-18) and the predicted exception counts must be confirmed by an engine run.
2. **TC03 weekend records.** 26 Sep is a Saturday, so the scenario adds a Saturday statement and 17:00 confirmation. The validator lists them as intended `NON_RECON_DAY_RECORD` findings. The owner should confirm this is acceptable; the alternative is a weekday pair.
3. **The validator's own rules are an independent re-implementation**, not the engine. Agreement with the engine is not claimed.
4. **Ringfence acceptance** of canonical-name upload ZIPs, and its exception identifiers, are not verified (G-20).
5. **Business-day calculation** uses England and Wales 2026 holidays; none fall in the affected dates.
