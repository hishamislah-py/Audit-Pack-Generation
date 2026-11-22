# 02 — Scenario Coverage Matrix

Assessment date: 30 Oct 2026. Probes for the unbuilt scenarios were run on temporary copies of the baseline and then discarded.

## 1. The six scenarios, and the unconfirmed sixth

| # | Scenario (as briefed) | Closest item in the project | Dataset exists? |
| --- | --- | --- | --- |
| 1 | Clean audit-pack generation | S01 clean baseline | Yes: `set_01_clean_baseline` |
| 2 | Settlement timing difference | Research catalogue S07 (with evidence) and S08 (claim without evidence) | **No** |
| 3 | Fee or gross-to-net discrepancy | Research catalogue S06 (documented fee) and S06b (fee lines missing) | **No** |
| 4 | Missing or incomplete evidence | S02 missing EUR bank evidence, 15 Sep | Yes: `scn_S02_missing_eur_statement` |
| 5 | Customer balance or transaction mismatch | Nearest is research S09 (duplicate or over-reversal causing an internal shortfall) | **No** |
| 6 | **Not established** | See below | — |

### Scenario 6: confirmation required

The latest agreed project documents (`UC042_SCENARIO_MUTATION_PLAN.md`, input specification §1, README, milestone review) agree on **three** scenarios: S01, S02 and S05. No project document lists six.

- **Strongest candidate:** **S05, unexplained GBP bank-ledger difference of £812.40 from 17 Sep.** It is approved, built (`scn_S05_unexplained_gbp_difference`) and verified, and it is the only agreed scenario absent from scenarios 1–5.
- **Alternative candidate:** S04, inconsistent settlement reference (an amount matches but the reference points to the wrong batch). It appeared in the UI prototype's demo set and in the research catalogue, and the engine detects it (regression test). It was never approved as a dataset.

**Please confirm which is scenario 6.** Below, scenario 6 is assessed **provisionally as S05**. It has not been silently substituted.

## 2. Coverage matrix

| | 1 Clean | 2 Timing difference | 3 Fee / gross-to-net | 4 Missing evidence | 5 Customer mismatch | 6 (provisional: S05) |
| --- | --- | --- | --- | --- | --- | --- |
| **Required datasets** | All 11 core CSVs + configuration | IN-06, IN-07/08/09 (bank), IN-10, IN-14, IN-12 | IN-12, IN-13, IN-09, IN-10, IN-11 | IN-07/08/09 (+ the dependants of what is missing) | IN-03, IN-04, IN-11, IN-05 | IN-06, IN-07/08/09, IN-10, IN-14 |
| **Key fields** | All `schema.py` columns | `booking_ts`, `value_date`, `timing_difference_claimed`, `posted_ts` | `gross_amount`, `total_fees`, `net_amount_reported`, `line_type`, `fee_code` | `statement_id`, `bank_statement_id` | `balance`, `executed_ts`, `direction`, `allocated_ts` | `bank_balance_reported`, `difference_reported`, `bank_reference` |
| **Relationships** | All reference links (02 §3) | Cash book ↔ bank by reference across days; ERL → confirmation | Batch → lines → transactions; batch → bank by `expected_bank_reference` | ERL → cited confirmation; entries → statement | Snapshot (d−1, d) ↔ transactions between points | ERL → confirmation; bank entry ↔ batch, cash book (none) |
| **Deterministic controls** | C01–C16 | RC2, C08; **evidenced timing acceptance (R08): not implemented** | C11 batch arithmetic and batch-to-bank; FUND-TOPUP | Evidence gate, C14, C07, C08, DQ22 | C04, C06, CBAL roll-forward, C11 | C08, C11-BANK-ENTRY, BANK-CASH-LINK, DISC-LOG |
| **Investigation evidence** | — (none needed) | Next-day bank entry with the same reference; discrepancy-log entry | Fee lines, fee schedule or invoice | Bank request or re-issued statement | Transaction export, client ledger detail | Bank correspondence; settlement record carrying `SETTLE 0417` |
| **Expected pack outputs** | Scope, inventory, evidence index, control results with assurance grade, empty exception register, limitations, approval | Exception with timing evidence and its status | Exception with the fee breakdown | Exception citing missing items; reported balance shown as unverified | Exception with the roll-forward and snapshot rows | Exception with persistence (10 days), own-funds flag, no cause set |
| **Human review** | Pack sign-off | Accept or reject timing; sign-off | Confirm the fee cause | Notification decision (CASS 15.8.60R(4)); sign-off | Confirm the cause; any funding | Investigation; funding decision; sign-off |
| **Current support** | **Partial.** Data and checks complete; pack generator and approval record missing. | **Partial / unsupported.** Detected, but cannot be resolved. | **Partial.** Detected, but fragmented, with fixed fee categories. | **Supported** (data and checks). Pack missing. | **Partial.** Detected, but fragmented, with 1 Sep not assessable. | **Supported** (data and checks). Pack missing. |

## 3. Evidence for each "current support" judgement

| # | Probe or dataset result | Gap |
| --- | --- | --- |
| 1 | Baseline: 1,786 PASS, 88 NOT_APPLICABLE, 0 exceptions; answer key MATCH; independent audit 36 checks, 0 problems | No pack generator (C15), AI narrative or approval record. Assurance is synthetic internal consistency (03 §4). |
| 2 | SB-GBP debit moved to 08:00 the next day, timing claimed, statements adjusted: **1 Critical `BANK_LEDGER_DIFFERENCE`**. C08 FAILs with "timing claimed, not evidenced", **even though the clearing entry exists on 16 Sep**. | Timing acceptance (R08) not implemented. No baseline data for timing (no post-17:00 or next-day entries). No dataset. |
| 3 | Acquirer reported net changed to 9,950.00: C11-BATCH-ARITH FAIL + C11-BATCH-BANK FAIL → **2 High exceptions for one root cause** | Root-cause grouping only recognises S02/S05 patterns. Fee codes fixed (`ACQ_FEE`, `SCHEME_FEE`). Bank-account fees not representable. No dataset. |
| 4 | S02 dataset: 13 INSUFFICIENT_EVIDENCE results, 1 Critical `EXC-S02-01`; no balance substituted; answer key MATCH | Pack missing |
| 5 | Snapshot +100.00: C04, C06 and 2 × CBAL fail → **4 exceptions for one root cause**. Spend removed from transactions: C11 + CBAL → 2 exceptions. | Grouping fragmentation. No 31 Aug client snapshot. No dataset. |
| 6 (S05) | 13 FAIL results; `EXC-S05-01` Critical (11) and `EXC-S05-02` High (2); answer key MATCH; corroborated by the independent audit | Pack missing |

## 4. Unsupported or partially supported: summary

- **Fully supported** (data and checks): scenarios 4 and 6 (S05, if confirmed).
- **Partially supported:** 1 (pack layer missing), 3 and 5 (detection works; exception grouping and datasets missing).
- **Not supported:** 2. Detection works, but the scenario's point, evidencing a timing difference, has no logic and no data.
- **For every scenario:** the audit pack itself, the AI narrative layer and the human approval record do not exist yet.
