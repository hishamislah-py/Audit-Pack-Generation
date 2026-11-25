# 05 — Recommended Minimum Dataset and Next Steps

Assessment date: 30 Oct 2026. Recommendations only: nothing has been implemented.

## Executive summary

| Question | Answer |
| --- | --- |
| **How much of the existing dataset aligns with the use case?** | Most of it. **11 of 19 files** are directly required uploads, holding about **96% of the 1,940 rows**. Every file feeds at least one check or pack section, so none should be removed. The data supports the *evidence-mapping* step of Hypothesis 2 well. *Pack assembly* (AI layer) and *compliance review* (human approval) have no implementation yet. |
| **Which scenarios are supported?** | **Fully** (data and checks): 4 (missing evidence, S02) and 6 if confirmed as S05 (£812.40 difference). **Partially:** 1 (clean: data and checks complete, pack layer missing); 3 (fee) and 5 (customer mismatch): detected, but no dataset and one cause splits into 2–4 exceptions. **Unsupported:** 2 (timing difference): detected, but evidenced timing cannot be accepted and no timing data exists. |
| **Scenario 6** | **Not established** from the project documents, which agree only on S01, S02 and S05. Provisionally S05 (the only agreed scenario not in 1–5); alternative S04 (inconsistent settlement reference). **Needs your confirmation.** |
| **How much is unnecessary or duplicated?** | No file is unnecessary. As **uploads**, 8 of 19 are not required: 1 becomes configuration (calendar); 2 can merge into 1 (bank confirmations + end-of-day headers, whose balances are equal in 44/44 cases in this data); 6 are optional supporting documents. Duplicated by construction: confirmation balances; cash book versus bank timing; reported versus recomputed reconciliation values. |
| **What is the minimum dataset?** | **11 CSVs + case configuration**, with 6 optional documents (below) |
| **Can the current data generate a clean audit pack?** | **The data can; the system cannot yet.** The clean baseline has every input a pack needs: scope, inventory with hashes, evidence index, account and transaction mapping, control results, an (empty) exception register, supporting PDFs, citations and limitations. **There is no pack generator, no AI narrative and no approval record.** A pack must also present the results as **synthetic internal consistency**, not independent assurance. |
| **How configuration-driven is it?** | **Not configuration-driven.** There is no configuration file. Period, currencies, holidays, fee categories, top-up pattern, letter slots, one-account-per-currency logic, exact-match rules, controls and scenarios are all code. Adding *data* within the existing types works; any new type, rule, mapping, tolerance, scenario or control needs code. |
| **Most important blockers** | 1. Scenario 6 unconfirmed. 2. No audit-pack generator, AI narrative layer or approval record. 3. No timing-difference logic or data (scenario 2). 4. Root-cause grouping fragments scenarios 3 and 5. 5. No configuration layer for the briefed change examples. |

## 1. Minimum dataset for a credible initial POC

**Configuration** (not uploaded): period, reconciliation days, 17:00 point, method and basis, accounts' letter slots, fee categories (`ACQ_FEE`, `SCHEME_FEE`), exact-match rules.

**Required uploads (11 CSVs):**

| # | File | Status versus today |
| --- | --- | --- |
| 1 | `account_inventory.csv` | RETAIN |
| 2 | `client_balance_snapshots_2026-09.csv` | MODIFY: add the 31 Aug 17:00 opening snapshot |
| 3 | `unallocated_register_2026-09.csv` | RETAIN |
| 4 | `internal_recon_records_2026-09.csv` | RETAIN |
| 5 | `external_recon_records_2026-09.csv` | RETAIN |
| 6 | `bank_statements_2026-09.csv` | CONSOLIDATE IN-07 + IN-08 with `statement_type`; MODIFY data to include post-17:00 movements |
| 7 | `bank_statement_entries_2026-09.csv` | MODIFY data (timing cases) |
| 8 | `sga_cashbook_entries_2026-09.csv` | RETAIN |
| 9 | `transactions_2026-09.csv` | RETAIN |
| 10 | `settlement_batches_2026-09.csv` | RETAIN |
| 11 | `settlement_lines_2026-09.csv` | RETAIN |

**Optional (6):** `discrepancy_log_2026-09.csv`, both acknowledgement letters, the policy PDF, the governance register, the return receipt.

**Remove:** none.

**Additional evidence required (MISSING):**

- case configuration;
- the opening client snapshot;
- timing-difference bank evidence (scenario 2);
- a fee schedule or fee-category mapping (scenario 3, and the configuration examples);
- datasets for scenarios 2, 3, 5 and the confirmed scenario 6;
- the audit-pack output and its human approval record.

## 2. Files to retain, modify, consolidate, make optional or remove

| Action | Files |
| --- | --- |
| RETAIN | IN-02, IN-04, IN-05, IN-06, IN-10, IN-11, IN-12, IN-13 |
| MODIFY | IN-01 (to configuration), IN-03 (opening snapshot), IN-09 (timing data) |
| CONSOLIDATE | IN-07 + IN-08 → `bank_statements_2026-09.csv` |
| OPTIONAL | IN-14, IN-15, IN-16, IN-17, IN-18, IN-19 |
| REMOVE | None |
| MISSING | See §1 |

## 3. Recommended order of work, after approval

1. **Confirm scope.** Confirm scenario 6, and approve these classifications. The earlier review decisions R1–R9 (`docs/review/UC042_DECISIONS_REQUIRED.md`) cover the same changes.
2. **Minimal configuration layer.** One case-configuration file for period, calendar, point, accounts, fee categories and matching rules, loaded and recorded with every run. Start with what the six scenarios need; no general rules engine.
3. **Data adjustments.** Merge the bank statements; add the opening client snapshot; add post-17:00 and next-day bank movements. Regenerate the baseline deterministically and verify it with the independent audit.
4. **Engine gaps the scenarios need:**
    - evidenced timing-difference acceptance (scenario 2);
    - general root-cause grouping (scenarios 3 and 5);
    - bank-charge handling via fee configuration (scenario 3 and the examples).
5. **Scenario datasets.** Build 2, 3 and 5 (and 6 once confirmed) as mutation lists on the baseline, with answer keys derived from the scenario definitions and checked by the independent audit.
6. **Audit-pack layer** (the primary outcome):
    - a deterministic pack structure (scope, inventory, evidence index, mapping, results with assurance grade, exception register, limitations);
    - an AI narrative step that may only restate cited results and evidence;
    - a human review and approval record.

    The clean scenario must produce a complete pack with an empty exception register.
7. **Thin application.** Upload → prepare → validate → review → trace → pack, around the existing engine.

**Stop here** until the assessment, and scenario 6, are approved.
