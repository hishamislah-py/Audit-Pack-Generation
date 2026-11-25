# 06 — Dataset Enrichment Implementation Report

Implemented 30 Oct 2026 under the approved gap-closure decisions D1–D6.

**Scope was limited to:** synthetic data, the generator, scenario mutation definitions, dataset validation tooling, tests and documentation. No application, audit-pack generator, AI layer, approval workflow, configuration platform, fee schedule or adjustment type was built. No financial control was changed.

> **ILLUSTRATIVE SYNTHETIC DATA (D6).** Every record, timing, reference and fee treatment is an illustrative convention for the UC-042 POC, not confirmed Moorwand practice.

## Scenario summary

| # | Scenario | Dataset | Status |
| --- | --- | --- | --- |
| 1 | Clean audit-pack baseline | `set_01_clean_baseline` | **DATA READY** |
| 2 | Settlement timing difference | `scn_SC2_settlement_timing` | **DATA READY, ENGINE LIMITATION** (E1) |
| 3a | Correctly supported fee | baseline batch `AQ-GBP-20260908` | **DATA READY** |
| 3b | Fee not itemised | `scn_SC3B_fee_not_itemised` | **DATA READY** |
| 3c | Unexplained gross-to-net (short settlement) | `scn_SC3C_short_settlement` | **DATA READY, ENGINE LIMITATION** (E2) |
| 4 | Missing or incomplete evidence | `scn_S02_missing_eur_statement` | **DATA READY** |
| 5a | Transaction missing | `scn_SC5A_missing_transaction` | **DATA READY, ENGINE LIMITATION** (E2) |
| 5c | Refund counted twice | `scn_SC5C_refund_double_posted` | **DATA READY, ENGINE LIMITATION** (E2) |
| 5d | Closing snapshot mismatch | `scn_SC5D_closing_snapshot_mismatch` | **DATA READY, ENGINE LIMITATION** (E2) |
| 6 | £812.40 unexplained GBP difference | `scn_S05_unexplained_gbp_difference` | **DATA READY** |

**No scenario is NOT READY.** Deferred by decision and not built: 3d wrong fee rate (D2) and 5b adjustment not reflected (D3).

**For every scenario,** the audit-pack generator, AI investigation layer and human approval record do not exist yet (E3). That is outside this task.

## 1. Changes implemented

| Decision | Implementation |
| --- | --- |
| D4 | 12 opening client snapshot rows `CBS-20260831-<client>-<ccy>` at 31 Aug 17:00 added to the baseline. GBP total £250,000.00 and EUR total €80,000.00 equal the cash-book and bank opening positions; the generator asserts this. |
| D4 (rule) | `schema.PERIOD_RULES["IN-03"]` now permits that one boundary record (recon date 2026-08-31, 17:00), matching how the cash-book opening row is already permitted. This is a period rule, not a financial control. |
| D1 | One-business-day allowance applied in the independent verifier's timing analysis ("cross-day items within one business day"). The engine does not apply it yet (E1). |
| D5 | Six new scenario folders, one per sub-case, built from the baseline by `uc042lib/scenarios.py` |
| D6 | Illustrative-synthetic notice in `GENERATION_NOTES.md` (now written by the generator), every `scenario.json` and `SCENARIO_NOTES.md`, and `SCENARIO_INDEX.md` |
| D2, D3 | Deferred. No fee schedule and no adjustment type. |

## 2. Files created or modified

| Change | Files |
| --- | --- |
| Modified (code) | `uc042lib/generate.py` (opening snapshot; writes `GENERATION_NOTES.md`, so regeneration no longer deletes it); `uc042lib/schema.py` (IN-03 permitted boundary record); `uc042lib/scenarios.py` (six definitions, baseline provenance, scenario index); `uc042lib/validate.py` (one report-text line about the roll-forward; no logic) |
| Modified (tests) | `tests/test_baseline.py`: two counts, 264 → 276 and 1,940 → 1,952, with D4 comments |
| Re-captured | `tests/golden/` baseline, S02 and S05, with justification in `tests/golden/README.md`; snapshots added for the six new datasets |
| Created | `tools/verify_datasets.py` (standalone independent verifier); `tests/test_scenario_datasets.py` (12 tests); `uc042_dataset/scenario_index.json`; `uc042_dataset/SCENARIO_INDEX.md`; six dataset folders; this report |
| Regenerated | `set_01_clean_baseline` (only IN-03 changed); S02 and S05 rebuilt from it with unchanged mutations |

## 3. Baseline preservation

- **18 of 19 evidence files** are byte-identical to the previous baseline.
- `client_balance_snapshots_2026-09.csv` differs only by the 12 added opening rows. All 264 September rows are identical.
- **Result effect:** compared with the previous golden snapshot, the only differences are:
  - 12 new `CBAL-ROLLFWD` PASS results (the 1 Sep pair per client);
  - the IN-03 row-count text (264 → 276).

  Exceptions are unchanged. S02 and S05 show exactly the same effect.
- **Scenario builds never modify the baseline.** Its manifest hash is checked before and after every build. Every `scenario.json` records `baseline_manifest_sha256`.

## 4. File and row counts (data rows, header excluded)

| File | baseline | SC2 | SC3B | SC3C | S02 | SC5A | SC5C | SC5D | S05 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `recon_calendar` | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 |
| `account_inventory` | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 |
| `client_balance_snapshots` | 276 | 276 | 276 | 276 | 276 | 276 | 276 | 276 | 276 |
| `unallocated_register` | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| `internal_recon_records` | 44 | 44 | 44 | 44 | 44 | 44 | 44 | 44 | 44 |
| `external_recon_records` | 44 | 44 | 44 | 44 | 44 | 44 | 44 | 44 | 44 |
| `bank_balance_confirmations` | 44 | 44 | 44 | 44 | 43 | 44 | 44 | 44 | 44 |
| `bank_statements_eod` | 88 | 88 | 88 | 88 | 87 | 88 | 88 | 88 | 88 |
| `bank_statement_entries` | 266 | 266 | 266 | 266 | 262 | 266 | 266 | 266 | 267 |
| `sga_cashbook_entries` | 224 | 224 | 224 | 224 | 224 | 224 | 224 | 224 | 224 |
| `transactions` | 422 | 422 | 422 | 422 | 422 | 421 | 422 | 422 | 422 |
| `settlement_batches` | 88 | 88 | 88 | 88 | 88 | 88 | 88 | 88 | 88 |
| `settlement_lines` | 420 | 420 | 418 | 420 | 420 | 420 | 420 | 420 | 420 |
| `discrepancy_log` | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **CSV rows** | **1,952** | **1,953** | **1,950** | **1,952** | **1,946** | **1,951** | **1,952** | **1,952** | **1,953** |

Every dataset has 14 CSV + 5 PDF files.

## 5. Scenario-by-scenario data changes

Changes by primary key, verified against `mutations.json` by test:

| Dataset | Operations | Added | Removed | Modified |
| --- | --- | --- | --- | --- |
| SC2 | 11 | `BE-GBP-0916-T01` (2,868.50 D, ref `SB-GBP-20260915`, booked 16 Sep 08:00); `DL-0001` (log, TIMING, cites `BE-GBP-0916-T01`) | `BE-GBP-0915-SB1` | 15 Sep GBP statement (closing 331,179.44, 4 entries); 16 Sep statement (opening 331,179.44, 7 entries); 15 Sep confirmation 331,179.44; `ERL-SGA-GBP-01-20260915` (bank 331,179.44, difference 2,868.50, timing claimed) |
| SC3B | 2 | — | `SL-AQ-GBP-20260908-0005` (ACQ_FEE 30.00), `-0006` (SCHEME_FEE 15.50) | — |
| SC3C | 85 | — | — | `BE-GBP-0908-AQ1` 9,954.50 → 9,950.00; GBP statements, confirmations and external records 8–30 Sep (17 days each) −4.50 |
| S02 | 6 | — | EUR 15 Sep confirmation, end-of-day header, 4 entries | — |
| SC5A | 1 | — | `TX-0915-00009` (C0002 spend 443.55) | — |
| SC5C | 48 | — | — | `CBS-<d>-C0002-GBP` +60.00 and `IRR-EMONEY-GBP-<d>` requirement +60.00 / difference −60.00, for 16 days from 9 Sep |
| SC5D | 1 | — | — | `CBS-20260930-C0003-GBP` 49,374.75 → 49,124.75 |
| S05 | 51 | `BE-GBP-0917-X01` (812.40 D, `SETTLE 0417`) | — | GBP statements, confirmations and external records 17–30 Sep |

## 6. Validation results

### Engine (`python -m uc042lib.validate`), against design-derived answer keys

All 9 datasets: **answer key MATCH**.

| Dataset | Results | Exceptions (actual = expected) | Case status |
| --- | --- | --- | --- |
| baseline | 1,798 PASS, 88 NA | none | CLEAN |
| SC2 | 1 FAIL (C08 15 Sep +2,868.50) | `EXC-SC2-01` Critical | EXCEPTIONS_OPEN |
| SC3B | 1 FAIL (C11 batch arithmetic) | `EXC-SC3B-01` High | EXCEPTIONS_OPEN |
| SC3C | 20 FAIL (C08 × 17, batch-to-bank, cash link, DISC-LOG) | `EXC-SC3C-01` Critical (18), `-02` High, `-03` High | EXCEPTIONS_OPEN |
| S02 | 13 INSUFFICIENT_EVIDENCE | `EXC-S02-01` Critical | EVIDENCE_INCOMPLETE |
| SC5A | 2 FAIL (C11 arithmetic, C0002 roll-forward 15 Sep) | `EXC-SC5A-01`, `-02` High | EXCEPTIONS_OPEN |
| SC5C | 17 FAIL (C06 × 16, C0002 roll-forward 9 Sep) | 16 Critical + 1 High | EXCEPTIONS_OPEN |
| SC5D | 3 FAIL (C04, C06, C0003 roll-forward 30 Sep) | `EXC-SC5D-01` Critical, `-02`, `-03` High | EXCEPTIONS_OPEN |
| S05 | 13 FAIL | `EXC-S05-01` Critical (11), `-02` High (2) | EXCEPTIONS_OPEN |

### Independent verifier (`tools/verify_datasets.py`, no shared code)

The verifier covers currency consistency, D/C and signed amounts, money format, period dates, duplicate IDs, eight reference links, statement arithmetic and continuity, confirmations, gross-to-net, batch-to-bank, top-ups, refunds, client roll-forward from 31 Aug, the three-way opening, requirement, ledger, bank-versus-ledger, and cross-day timing.

| Dataset | Checks | OK | PROBLEM | INSUFFICIENT | Where (exactly the intended places) |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline | 9,416 | 9,416 | 0 | 0 | — (includes opening: clients = cash = bank, GBP and EUR) |
| SC2 | 9,422 | 9,420 | 2 | 0 | Bank − ledger on 15 Sep only; batch booked 1 day after settlement date. **The timing item is within one business day and fully explains the 15 Sep difference.** |
| SC3B | 9,412 | 9,411 | 1 | 0 | `AQ-GBP-20260908`: FEE lines 0.00 against fees 45.50 |
| SC3C | 9,433 | 9,397 | 36 | 0 | Bank − ledger −4.50 × 17; batch reported 9,954.50 against 9,950.00 banked; cash link; **not timing-evidenced × 17** |
| S02 | 9,373 | 9,363 | 0 | 10 | Only INSUFFICIENT (missing EUR 15 Sep evidence); no balance substituted |
| SC5A | 9,411 | 9,408 | 3 | 0 | Line → missing `TX-0915-00009`; batch arithmetic; C0002 15 Sep roll-forward −443.55 |
| SC5C | 9,416 | 9,399 | 17 | 0 | C0002 9 Sep roll-forward +60.00; internal shortfall −60.00 × 16 |
| SC5D | 9,416 | 9,413 | 3 | 0 | C0003 30 Sep roll-forward −250.00; requirement 395,594.86 against reported 395,844.86; internal +250.00 |
| S05 | 9,433 | 9,412 | 21 | 0 | Bank − ledger −812.40 × 10; `SETTLE 0417` with no cash-book counterpart; **not timing-evidenced × 10** |

**Integrity, all datasets:** 0 duplicate IDs; 0 unintended broken references (the only broken one is SC5A's intended line → `TX-0915-00009`); currencies consistent; all money 2 dp; all dates in September except the two documented 31 Aug opening record types.

**The D1 allowance is not a blanket resolution.** Only SC2 has a cross-day item. The SC3C and S05 differences have none, so they stay unexplained.

### Tests

**95 tests, all passing:** 83 existing (two D4 count updates) + 12 new in `tests/test_scenario_datasets.py`. The new tests cover:

- answer keys for all datasets;
- byte-identical rebuilds;
- diff = `mutations.json`;
- baseline untouched;
- provenance and D6 labels;
- opening snapshot and the 12 new 1 Sep PASS results;
- the independent verifier's exact expected findings per dataset;
- timing within one business day;
- the allowance not resolving other differences;
- £812.40 unresolved with an empty log;
- 3a supported in the baseline.

## 7. Determinism

Two complete regenerations from scratch (baseline + all scenarios) produced **233 byte-identical files**. They are identical to each other and to the delivered datasets: evidence files, manifests, mutations, answer keys, scenario metadata, notes and index.

## 8. Remaining engine limitations

These are not data problems. They are recorded in each `answer_key.json` under `engine_limitations` and `target_outcome`, and are left for separate approval.

| # | Limitation | Scenarios | Current behaviour (in the answer key) | Intended outcome |
| --- | --- | --- | --- | --- |
| E1 | Timing evidence not evaluated; batch-to-bank does not compare dates | 2 | C08 FAIL "timing claimed, not evidenced", although `BE-GBP-0916-T01` matches account, currency, reference and amount one business day later | Difference explained as timing (evidence cited), awaiting human confirmation; lag reported |
| E2 | Root-cause grouping limited to the S02/S05 patterns | 3c, 5a, 5c, 5d | 3, 2, 17 and 3 exceptions respectively | One exception per root cause |
| E3 | No audit-pack generator, AI investigation or approval record | All | — | Packs per 03 design |

## 9. Deferred scenarios and assumptions

- **Deferred:** 3d wrong fee rate (no fee schedule, D2); 5b adjustment not reflected (no adjustment type, D3).
- **Illustrative synthetic conventions (D6, not Moorwand practice):**
  - timing convention D8;
  - 17:00 point;
  - per-currency internal reconciliation;
  - acquirer fees deducted and topped up from own funds the same day;
  - scheme fees outside safeguarding accounts;
  - references (batch ID, end-to-end ID, `TOPUP-…`);
  - items B–D zero;
  - D+1 not performed;
  - period conventions P1/P2;
  - one-business-day timing window (D1);
  - opening client balances.

## 10. Final readiness assessment

**The data layer is ready.** All six scenarios have reproducible, isolated, independently verified datasets. The clean baseline includes the opening snapshot, and the missing-EUR and £812.40 scenarios are preserved unchanged in intent.

**Scenarios 2, 3c and 5** are limited only by the engine (E1, E2). Their datasets represent the intended business situation, and the independent verifier proves it.

**Next step, subject to approval:** engine changes E1 and E2. The answer keys' `target_outcome` fields define the intended results. After that, the audit-pack layer (E3).

---

## Update, 30 Oct 2026: E1 and E2 implemented

Engine limitations E1 and E2 (section 8) are implemented; see `docs/processing_engine/02_E1_E2_IMPLEMENTATION_REPORT.md`.

| Scenario | Updated status |
| --- | --- |
| 2 | **DATA READY.** Timing difference evidenced (`TIMING_EVIDENCED`), still FAIL and OPEN, awaiting human confirmation. |
| 3c | **DATA READY.** Three exceptions in one investigation group (`GRP-SC3C-01`); −4.50 `NOT_EVIDENCED`. |
| 5a | **DATA READY.** Two exceptions with no confirmed group (evidence limitation), plus one UNVERIFIED candidate relationship. |
| 5c, 5d | **DATA READY.** One investigation group each. |
| 6 | **DATA READY.** Two exceptions in `GRP-S05-01`; −812.40 `NOT_EVIDENCED`; unresolved. |

Answer-key metadata was updated (D-E2b). Source evidence, manifests and golden snapshots are unchanged. Tests: 118, all passing.
