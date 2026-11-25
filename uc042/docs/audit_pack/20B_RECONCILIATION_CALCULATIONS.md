ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

# 20B — How UC-042's deterministic reconciliation calculations work

**Audience:** business owner, financial operations analyst and auditor. **Basis:** the code as it stands in `uc042lib/` and `uc042app/` (read, not executed, for this document), the scenario definitions in `uc042_dataset/`, the tests in `tests/`, and four published packs. Every statement cites the file and function that implements it, as `file:function:line`. Anything not confirmed from code or pack data is marked **[NOT VERIFIED]**. Where the code does not establish a formula, this document says so.

**One-sentence summary.** For one reporting month, the engine (`uc042lib/validate.py`, class `Validator`) loads the evidence files, discards invalid rows, recomputes each reconciliation figure from the source records, compares it with the figure the firm reported, and records each comparison as PASS, FAIL, INSUFFICIENT_EVIDENCE or NOT_APPLICABLE. It then turns every FAIL or INSUFFICIENT_EVIDENCE into exactly one exception per root cause. It never estimates, never fills gaps and never treats missing as zero.

---

## Verification record (4 November 2026)

**What was checked.** Every line reference and formula in the earlier version of this document was checked against `uc042lib/validate.py`, `money.py`, `period.py`, `policy.py`, `structure.py`, `schema.py`, `continuity.py`, `prepare.py`, `pack/assemble.py`, `pack/model.py`, `pack/config.py`, `pack/registry.py`, `pack/generate.py`, `uc042app/services/monthly.py`, `uc042app/services/packs.py`, the API routers, the database models and the frontend files named in Part K. The figures were checked by read-only Python against `demo_history/packs/PACK-H202602-PER-2026-02-195df2e1f216/pack.json`, `packs/PACK-S05-PER-2026-09-ddd0fdc8b731/pack.json`, `packs/PACK-SC2-PER-2026-09-aaca8a8b7194/pack.json`, `packs/PACK-SC5C-PER-2026-09-eaac7e6b1444/pack.json`, the S05 source CSVs and `mutations.json` files, and `demo_history/verification/continuity.csv`. Test names were found by parsing `tests/test_*.py` for the check IDs. No application, test, network or AI call was run.

**Corrections made to the earlier text:**

1. **Continuity CSV count.** It was described as "36 items, all MATCH, for January→February and February→March". The file holds **144 items, 18 per month boundary, for all eight boundaries January→February to August→September, all MATCH**.
2. **"No thresholds exist" was incomplete.** There is no *monetary* tolerance anywhere (confirmed). There are, however, **hardcoded time windows** in `validate.py`: one business day for timing evidence (line 107), the next-business-day allocation deadline (lines 986, 1005), the one-business-day settlement booking allowance (informational only, lines 858–866), the same-day top-up rule (line 926) and the 15-business-day return deadline (line 1157). None is read from the policy. See section A.6.
3. **Line reference.** The C06 comparison `diff != rep` is at validate.py:739, not 738.
4. **`evidence_gap` was under-described.** It also returns a root cause when an excluded row of IN-08, IN-07 or IN-09 could belong to that account-day (validate.py:225–228), not only when a statement or confirmation is absent.
5. **February BC-VS-EOD.** "BC-VS-EOD produced no 16 Feb result" is true only for SGA-EUR-01. A 16 Feb BC-VS-EOD result exists for SGA-GBP-01 (`ST-SGA-GBP-01-20260216-1700`).
6. **Internal differences are not merged across days.** The earlier text implied the same treatment as bank-ledger differences. In fact each failing C06 day is its **own** exception (`INTERNAL_DIFFERENCE|date/ccy`). Consecutive days are only *linked* by correlation (L2). Example: SC5C has 16 separate internal-difference exceptions in one group (section J.4).
7. **C11-BATCH-BANK matching key.** It matches on the bank entry's `bank_reference` only, not `end_to_end_ref` (validate.py:815–816). The earlier text did not say which.
8. **C09-ALLOCATION.** The matching LOAD_BANK transaction is required only when the allocation falls inside the period. An allocation after the period end is reported as a convention-P1 note, and no transaction is required (validate.py:989–991).
9. **V00-FILE emits no PASS row.** It reports only problems (missing, ambiguous, hash mismatch, not in manifest, another period's file) or NOT_APPLICABLE. A clean case has no V00-FILE entry in the control register.
10. **Pack read verification.** The API read path verifies packs with `uc042lib/final_pack/sources.load_pack` (services/packs.py:8, 56), not `investigation/retrieval.load_pack`. The retrieval function is used by the AI layer. Both statements are now given.

**Additions.** These are new in this version: a per-control specification for all 36 check IDs the engine emits (Parts B–F); separate parts for internal (C) and external (D) reconciliation; the explanation topics requested (section A.7 and Parts C–H); two more worked examples (SC2 and SC5C) and a scenario-to-exception map (Part J); "From the screen to the calculation" (Part K); and a consolidated list of limitations (Part M).

**Not verifiable from code or data in this pass:**

- That reruns are byte-identical. This is established from code, not by rerunning.
- The behaviour of several limitations in Part M, for example bank-ledger grouping when two accounts differ on the same days. These are observed from the code and were not executed.
- The internal content of the final-pack builder (`uc042lib/final_pack/assemble.py`) beyond the report section list. It was not traced line by line.
- The CASS and SUP rule references quoted in engine notes. These are reproduced as the code states them and were not checked against regulatory text.

---

## How to read this document

- **Part A** covers the foundations: inputs, identification, calendar, policy, money, dates, tolerances, the run order, and the cross-cutting explanations.
- **Part B** covers data-quality, file and coverage controls. **Part C** covers internal reconciliation, **Part D** external reconciliation and bank evidence, **Part E** settlement, transactions, funding and receipts, and **Part F** currency, designation and the checklist.
- **Part G** covers the evidence gate, exceptions, correlation and case status. **Part H** covers month-boundary continuity, **Part I** pack integrity, **Part J** worked examples, **Part K** the path from screen to calculation, **Part L** the AI boundary, and **Part M** limitations.

Each control in Parts B–F uses the same table: (1) ID and name, (2) business purpose, (3) the financial question, (4) inputs, (5) CSV columns, (6) join and matching, (7) grouping, (8) calculation, (9) tolerance, (10) dates and timezone, (11) missing evidence, (12) output, (13) outcome conditions, (14) exceptions, (15) tests, (16) limitations, and **Why** (a plain-language note for a financial operations analyst).

Control **names** are the engine's control code passed through `uc042lib/pack/registry.py` `control_name` (lines 31–35), using `CONTROL_OF` (validate.py:46–52). Codes that the source-to-control matrix does not name are shown as "not named", as the registry does. **Tests** were found by searching test bodies for the check ID. Three tests exercise **every** check on their datasets and are not repeated in each table:

- `test_hardening.py::GoldenRegression::test_golden_results_and_exceptions_unchanged` (every result of the baseline, S02 and S05 compared with `tests/golden/`);
- `test_scenario_datasets.py::ScenarioDatasets::test_every_answer_key_matches` and `test_baseline.py::Scenarios::test_answer_keys_match` (all non-passing results per scenario, against `answer_key.json`);
- `test_audit_pack.py::Scenario1Acceptance::test_ac3_ac4_all_results_and_outcomes` (the PASS count of every check on the clean September baseline).

---

# Part A — Foundations

## A.1 The nineteen evidence types

The file contract is in `uc042lib/schema.py` (`CSV_FILES` lines 15–197, `PDF_FILES` lines 199–211). File names come from `uc042lib/period.py` `FILE_PATTERNS` (lines 44–64), where `{period}` is the month (YYYY-MM).

| ID | What it is | Canonical name pattern | Required? |
|---|---|---|---|
| IN-01 | Reconciliation-day calendar (one row per calendar day, `is_recon_day`) | `recon_calendar_{period}.csv` | Required |
| IN-02 | Account and institution inventory (`account_class` = RELEVANT_FUNDS_BANK or OWN_FUNDS) | `account_inventory.csv` | Required |
| IN-03 | Client balance snapshots at each reconciliation point | `client_balance_snapshots_{period}.csv` | Required |
| IN-04 | Unallocated receipts register | `unallocated_register_{period}.csv` | Required (may be empty) |
| IN-05 | Internal reconciliation records **as reported by the firm** | `internal_recon_records_{period}.csv` | Required |
| IN-06 | External reconciliation records **as reported by the firm** | `external_recon_records_{period}.csv` | Required |
| IN-07 | Bank balance confirmations at the 17:00 point | `bank_balance_confirmations_{period}.csv` | Required |
| IN-08 | End-of-day bank statement headers (opening/closing balance, entry count) | `bank_statements_eod_{period}.csv` | Required |
| IN-09 | Bank statement entries | `bank_statement_entries_{period}.csv` | Required |
| IN-10 | Safeguarding-account cash book (the firm's ledger), including one OPENING_BALANCE row per account | `sga_cashbook_entries_{period}.csv` | Required |
| IN-11 | Client transactions | `transactions_{period}.csv` | Required |
| IN-12 | Settlement batch headers | `settlement_batches_{period}.csv` | Required |
| IN-13 | Settlement batch lines | `settlement_lines_{period}.csv` | Required |
| IN-14 | Discrepancy and corrective-action log | `discrepancy_log_{period}.csv` | Required (may be empty) |
| IN-15 | Acknowledgement letter, SGA-GBP-01 (PDF) | `ack_letter_SGA-GBP-01.pdf` | Required |
| IN-16 | Acknowledgement letter, SGA-EUR-01 (PDF) | `ack_letter_SGA-EUR-01.pdf` | Required |
| IN-17 | Safeguarding reconciliation policy (PDF, versioned) | `safeguarding_reconciliation_policy_v{policy}.pdf` | Required |
| IN-18 | Governance register (PDF) | `governance_register_{period}.pdf` | Optional |
| IN-19 | Monthly return receipt for the **previous** month (PDF) | `rep027_submission_receipt_{previous}.pdf` | Optional |

Every CSV is required, and so are the PDFs marked REQUIRED (`PeriodConfig.requirement`, period.py:251–253). Only IN-04 and IN-14 may contain no data rows (`schema.EMPTY_ALLOWED`, schema.py:270). The exact column names of every CSV are in schema.py lines 15–197. The tables below quote them verbatim.

## A.2 How files are identified

- **At intake** (`uc042lib/prepare.py`, module docstring lines 7–27; `prepare_case` line 104), files are identified **by content only**. A CSV is matched when its header row exactly equals one schema column list. A PDF is matched when its text contains every key-details label of one document type. Acknowledgement letters are assigned to IN-15 or IN-16 by matching the letter reference to IN-02. File names and any supplied manifest are never trusted. Two different files competing for one slot make the slot AMBIGUOUS, and neither is used.
- **In the engine** (`Validator.load`, validate.py:234–281), each file ID is read from its canonical path. A file is then classed as MISSING, EMPTY, UNUSABLE or AMBIGUOUS. UNUSABLE means a wrong header (`load_csv`, 305–312), or a file that is not a PDF or lacks key details (`load_pdf`, 365–394). The manifest is used only to detect a changed file. A SHA-256 or row-count mismatch is a FAIL (`V00-FILE` / `V01-SCHEMA`), and a manifest is never treated as proof that a file is valid (docstring lines 19–20).
- **Row structure** (`uc042lib/structure.py` `check_rows`, lines 83–119): every row is type-checked. Amounts must have exactly 2 dp, dates must be ISO, timestamps must carry an offset, currencies must be GBP or EUR, and enums must be valid (`schema.ENUMS`, schema.py:230–252). Conditional fields must be present when their condition holds (`schema.CONDITIONAL`, schema.py:255–267). Duplicate primary keys after the first are rejected. An invalid row is **excluded from all calculations** and reported as `DQ-FIELD` FAIL (validate.py:320–323). Any invalid row in IN-01 or IN-02 makes the whole file unusable, because a partial calendar or account list would silently shrink scope (`schema.SCOPE_FILES`, schema.py:274; validate.py:333–335).
- **Reporting period** (`structure.check_period`, structure.py:170–238; `Validator.apply_period`, validate.py:338–363): rows dated outside the month are excluded (`DQ-PERIOD`). Two kinds of row are permitted boundary records: the cash-book OPENING_BALANCE row and the client snapshot at the previous month-end 17:00 point (`PeriodConfig.period_rules`, period.py:268–277). If no row of a file falls in the period, the file is WRONG_PERIOD and is not used. A canonical file for a different month in the case folder is reported and never used (`check_other_periods`, validate.py:283–296).

## A.3 Reconciliation calendar and reconciliation days

- The reconciliation days are **exactly the IN-01 rows with `is_recon_day == "true"`** (`Validator.setup`, validate.py:428). The engine does not derive them itself.
- England and Wales bank holidays are computed in `period.bank_holidays` (period.py:98–116). They are used for "next business day" arithmetic (`business_day_after`, period.py:123–129, wrapped at validate.py:55–57). They are also used for an upload-time calendar plausibility check (`PeriodConfig.calendar_findings`, period.py:288–316, called from `uc042app/ingest/analysis.py:190`), which gives warnings and information only. The validator itself does not override IN-01.
- In February 2026 the pack lists 20 reconciliation days, 2–27 February on weekdays (pack `metadata.reconciliation_days`; synthetic).

## A.4 The policy (IN-17): selection, effective dates, and what it controls

**Recognised versions** (`uc042lib/policy.py` `POLICY_VERSIONS`, lines 39–48):

| Version | Registered effective date | Classification | Decision |
|---|---|---|---|
| 1.1 | 2025-10-01 | ILLUSTRATIVE_SYNTHETIC ("illustrative predecessor of v1.2, same rules") | HD-1 |
| 1.2 | 2026-05-07 | SYNTHETIC_PROJECT_DOCUMENT | (none) |

A policy PDF is recognised only if its stated version is registered, its stated effective date equals the registered one, and its text carries the required markings (`recognise`, policy.py:69–81).

**Applicability rule** (`applicability`, policy.py:89–97). A version applies to a period if **both** of these hold:

1. its effective date is on or before the period end; **and**
2. it is not superseded, meaning the next registered version's effective date is not on or before the period start (`_successor`, policy.py:84–86).

What follows from this rule:

- **No version applies to any period ending before 2025-10-01.** `applicable_versions(PeriodConfig(2025, 9))` is `[]`, asserted in `test_historical_integration.py::PolicyRegister::test_applicable_version_by_month`. At intake, a policy that does not apply is REJECTED, and "no policy document selected" is recorded as MISSING IN-17 (`prepare._policy_documents`, prepare.py:218–245). The monthly service treats a MISSING required file as blocking, so the run fails before the engine (services/monthly.py, `_process`, the `blocking` list). Run directly, the engine would report V00-FILE INSUFFICIENT_EVIDENCE for IN-17 and gate every check that depends on it.
- January–April 2026: v1.1 only. **May 2026: both v1.1 (not yet superseded on 1 May) and v1.2 (effective 7 May, before the period end) apply.** June 2026 onwards: v1.2 only (v1.1 is superseded from 2026-05-07, before 1 June).

**Selection** (`select`, policy.py:104–151), at intake, not in the engine:

- If one version applies, it is selected.
- If several apply, the period needs an approved selection. `APPROVED_SELECTIONS` (policy.py:50–55) has one entry: **PER-2026-05 → v1.2, decision HD-2** ("v1.2, the version in force at the period end, is selected for reconciliation; both documents stay in the source inventory and audit trail; results under v1.1 were identical apart from the cited file name").
- Without an approved selection, every applicable version is AMBIGUOUS and none is used.
- A caller-selected version (`PeriodConfig.policy_version`) overrides, but must itself apply.
- The choice is written to `<case>/policy_selection.json` and read back with `prepare.selected_policy` (prepare.py:248–251). The monthly service passes it explicitly to the engine (services/monthly.py:796–799).
- If a case holds more than one version and none was selected, `period._with_policy` raises an error (period.py:377–386), because **the engine never chooses between policy documents**.

Observed (synthetic): Jan–Apr packs cite v1.1, Jun–Sep packs cite v1.2. The May pack lists both files in its evidence register, and its C03-POLICY result cites `safeguarding_reconciliation_policy_v1.2.pdf`.

**Engine-side effective-date guard** (`Validator.setup`, validate.py:449–456): if the loaded policy's stated effective date is after the period end, the engine deletes it from use, marks IN-17 UNUSABLE and adds a V01-PDF FAIL (`INVALID_FILE|IN-17`). This guard is independent of intake. Tests: `test_period_config.py::DocumentApplicability::test_policy_effective_after_the_period_is_not_applied`, `test_demo_history.py::PeriodAwareEngine::test_policy_effective_after_the_period_is_never_applied`.

**What the policy parameterises in the engine:**

1. **The reconciliation point.** The text "Reconciliation point: HH:MM Europe/London" is parsed into `point_time` (validate.py:441–448). Every "as at the point" cut-off uses `Validator.point(d)` = date *d* at that time in Europe/London, adjusted for daylight saving (validate.py:400–401). Both versions state 17:00.
2. **C03-POLICY** passes only if "Reconciliation method" = STANDARD and "Internal reconciliation basis" = Per currency (validate.py:464).
3. **Effective date**, as above.

"Frequency" and "Safeguarding method" are required labels, so a PDF without them is unusable, but no calculation reads them.

## A.5 Money handling

- **Exact decimals.** Amounts are parsed only from strings matching `^\d+\.\d{2}$` (unsigned) or `^-?\d+\.\d{2}$` (signed) into Python `Decimal` (`money.parse_unsigned` / `parse_signed`, money.py:27–37). Floats, thousands separators, decimal commas, symbols and scientific notation are rejected (structure.py docstring lines 6–9).
- **Rounding.** The validator does no rounding. It only adds and subtracts 2-dp decimals, so every result is exact to the cent. The one rounding rule, `round_half_up` (money.py:47–49), is used only by the synthetic data generator for fees (generate.py:206–207).
- **Sign conventions** (`money._RULES` and `signed`, money.py:52–65): the signed amount is positive when the balance it belongs to increases.

  | Source | Indicator | Rule |
  |---|---|---|
  | Bank balances and entries (IN-07/08/09) | C / D | C = +, D = − |
  | Cash book (IN-10, firm asset ledger) | D / C | D = +, C = − |
  | Client transactions (IN-11) | CR / DR | CR = +, DR = − |
  | Settlement lines (IN-13) | C / D | C = +, D = − |
  | Batch net (IN-12) | TO_FIRM / FROM_FIRM | +net / −net (`batch_net_signed`, money.py:68–73) |

- **Currencies.** Only GBP and EUR are accepted (structure.py:28). Every calculation is keyed by one currency or one account, and **no FX conversion exists** (C13 note, validate.py:1105, 1112).
- **Missing is never zero.** When an input is absent or tainted by an excluded row, the computed value is `None` and the result is INSUFFICIENT_EVIDENCE, never 0.00. Examples: `ledger_at` returns `None` without an opening row (validate.py:675–677); C04 returns INSUF when snapshots are absent (699–703); C06 and C08 return INSUF when either side is `None` (735–736, 784–788). In the pack, a value from an INSUF result is shown as the literal text "not available" (`pack/assemble.py` `val`, lines 178–181; `pack/config.py` `NOT_AVAILABLE`, line 8). Items B–D of the resource are the one place reported figures are taken as given, and that is stated as a limitation (validate.py:729; `pack/config.py` `LIMITATIONS`, line 15).

## A.6 Tolerances and thresholds (one place)

**Monetary tolerance: none.** Every amount comparison is exact `Decimal` (or, in RC4 and C09, exact 2-dp text) equality. A one-penny difference is a FAIL. A search of `uc042lib` outside the AI layer for "toleran", "threshold", "materiality" and `abs(` finds no monetary tolerance. The only `abs(` in the engine is in the unverified-candidate rule (validate.py:1462), which compares a difference *exactly* with a line amount.

**Hardcoded time windows.** These are not read from the policy. "Business day" means England and Wales (`period.business_day_after`).

| Rule | Value | Location | Effect on outcome |
|---|---|---|---|
| Timing evidence window (D1) | later side booked no later than the next business day after *d* | validate.py:107, 138 | Changes only `evidence_status` / wording of a C08 FAIL, never the outcome |
| Unallocated receipt allocation deadline (CASS 15.2.5R) | next business day after `receipt_date` | validate.py:986, 1005 | FAIL if allocated (or still open) after it |
| Settlement booking allowance (D-E1b) | 1 business day | validate.py:856–861, 866 | Informational only, outcome unaffected |
| Fee top-up timing | safeguarding credit booked on the settlement date | validate.py:926 | FAIL otherwise |
| Monthly return due date (SUP 16.14A.3R, as cited in the code) | 15th business day after the previous month end | validate.py:1157 | FAIL if submitted later or stated due date differs |
| Coverage expectation for batches | one SCHEME and one ACQUIRER batch per currency per reconciliation day | validate.py:519 | INSUF if absent |
| Top-up reference format | `TOPUP-{CCY}-{YYYYMMDD}` | validate.py:906–907 | Defines what is sought |

## A.7 Dates and timezone (engine-wide)

- `schema.TZ` = "Europe/London" (schema.py:13). `point(d)` builds a timezone-aware instant with `ZoneInfo`, so British Summer Time is applied per date and never as a fixed +01:00 (period.py docstring lines 10–14; test `test_period_config.py::CalendarAndTimezone::test_daylight_saving_offsets_are_not_hardcoded`).
- **Instant comparisons** (`posted_ts <= P`, `receipt_ts <= P`, `booking_ts <= as_at_ts`, transactions in `(P_prev, P_cur]`) compare aware datetimes. They are correct whatever offset each row states.
- **Period membership** converts timestamps to Europe/London dates (`structure._local_date`, structure.py:150–154).
- **Dates taken from a timestamp without conversion.** `parse_ts(x).date()` uses the date *in the row's own stated offset*: IN-07 as-at date (validate.py:435, 494, 610, 767–768); cash-book posting date in CASH-BANK-LINK (649); transaction execution date in RC4 (959); allocation date versus deadline in C09 (987); IN-19 submission date (1159); and the date of an excluded row's taint scope (structure.py:140). For the synthetic data, which states local offsets, this is identical. **[Not tested with non-local offsets.]**
- **Converted to London:** timing-item dates (validate.py:120, 133, 135) and the C09 "allocated after the period end" test (989).
- **C03-POINT for IN-07** compares the wall-clock time as written (`timetz().replace(tzinfo=None)`, validate.py:478) and ignores the offset.
- Plain ISO date columns (`recon_date`, `statement_date`, `booking_date`, `settlement_date`, `receipt_date`, `calendar_date`) are used as dates.

## A.8 The run order

`Validator.run()` (validate.py:404–425): `load` → `setup` → 16 control methods → `group_exceptions` → `correlate_exceptions`.

| Order | Method (validate.py lines) | Check IDs emitted | Part |
|---|---|---|---|
| 1 | `load` 234–281, `load_csv` 298–336, `apply_period` 338–363, `load_pdf` 365–394, `check_other_periods` 283–296 | V00-FILE, V01-SCHEMA, V01-PDF, DQ-FIELD, DQ-PERIOD | B |
| 2 | `setup` 427–456 | V01-PDF (policy point / effective date) | B |
| 3 | `check_policy_and_points` 458–480 | C03-POLICY, C03-POINT | B |
| 4 | `check_coverage` 482–532, `_cover` 534–547 | C01-COVER, C07-COVER, C14-COVER | B |
| 5 | `check_statements` 549–624 | DQ23-STATEMENT, DQ22-CONTINUITY, BC-VS-EOD | D |
| 6 | `check_cashbook_bank_links` 626–666 | CASH-BANK-LINK, BANK-CASH-LINK | D |
| 7 | `check_internal` 680–744 (uses `ledger_at` 668–678) | C04-REQUIREMENT, C05-RESOURCE, C06-DIFFERENCE | C |
| 8 | `check_external` 746–806 (uses `timing_*` 99–176) | C07-BANK-EVIDENCE, RC2-LEDGER, C08-DIFFERENCE | D |
| 9 | `check_settlement` 808–892 | C11-BATCH-ARITH, C11-BATCH-BANK, C11-TXN-LINE | E |
| 10 | `check_topups` 894–929 | FUND-TOPUP | E |
| 11 | `check_direct_and_allocation` 931–1011 | RC4-DIRECT, C09-ALLOCATION | E |
| 12 | `check_unmatched_bank_entries` 1013–1035 | C11-BANK-ENTRY | E |
| 13 | `check_refunds` 1037–1054 | C12-REFUND | E |
| 14 | `check_client_rollforward` 1056–1086 | CBAL-NONNEG, CBAL-ROLLFWD | C |
| 15 | `check_currency_isolation` 1088–1112 | C13-CURRENCY | F |
| 16 | `check_designation` 1114–1136 | C10-DESIGNATION | F |
| 17 | `check_discrepancy_log` 1138–1140 (gate only) | DISC-LOG (evaluated in step 19) | D |
| 18 | `check_checklist` 1142–1171 | C16-GOVERNANCE, C16-RETURN | F |
| 19 | `_group_exceptions` 1191–1303 | DISC-LOG; exceptions | G |
| 20 | `_correlate_exceptions` 1306–1471 | investigation groups, candidates | G |

Registry codes with **no** engine check: **C02** "Record completeness" (registry.py:11) is named but not emitted by any check (`CONTROL_OF` has no C02). C15 is out of scope ("pack statements (C15)", validate.py:1629).

Every result is a dict with `check_id, control, scope, outcome, computed, reported, evidence, note, root_cause, evidence_status, structured` (`Validator.add`, validate.py:92–96). The pack copies these into `control_register[].results[]` with `result_id = check_id|scope` (`pack/model.py` `result_id`, line 54–55; assemble.py:143–167).

## A.9 Cross-cutting explanations

### Opening and closing balances

The engine never stores or derives a "closing balance" of its own. Each balance type is handled as follows.

| Balance | Where it comes from | How the engine checks it |
|---|---|---|
| **Bank opening/closing per day** (IN-08 `opening_balance_amount/_dc`, `closing_balance_amount/_dc`) | The bank's statement header | **DQ23**: opening + Σ signed entries = closing. **DQ22**: previous closing = next opening. **DQ22 first statement**: opening = cash-book OPENING_BALANCE. |
| **Bank balance at 17:00** (IN-07 `balance_amount/balance_dc_indicator`) | The bank's confirmation | **BC-VS-EOD**: = IN-08 opening + Σ IN-09 entries booked by the as-at time. **C07**: = the firm's `bank_balance_reported`. |
| **Ledger (cash-book) balance at 17:00** | **Computed** by `ledger_at` (validate.py:668–678) | Σ signed IN-10 entries for the account with `posted_ts` ≤ P, **including** the OPENING_BALANCE row. It is cumulative from the month opening, not rolled from the previous day. |
| **Month opening, cash book** | IN-10 OPENING_BALANCE row at the previous month-end 17:00 (permitted boundary record) | DQ22 first-statement check. Continuity CASH_BOOK view (Part H). |
| **Month opening, clients** | IN-03 snapshot at the previous month-end 17:00 (permitted boundary record) | Starting point for CBAL-ROLLFWD. Continuity CLIENT view. |
| **Client balances per day** (IN-03 `balance`) | The firm's client ledger | CBAL-ROLLFWD, CBAL-NONNEG, and the input to C04. |

### Daily movements

**The engine computes no separate "daily movement" figure and publishes no daily or monthly totals.** `pack/config.py` LIMITATIONS line 19 says "Monthly totals are not included: the engine does not calculate them". Movements appear only inside these checks:

- **DQ23**: Σ entries on one EOD statement.
- **BC-VS-EOD**: Σ entries booked by the as-at time.
- **ledger_at**: cumulative cash-book total to P.
- **CBAL-ROLLFWD**: Σ client transactions between two snapshot points.

The pack's opening-position block (`reconciliation_summary.opening_positions`, assemble.py:211–229) lists source rows and computes nothing.

### Unallocated balances

Unallocated (and unidentified) receipts in IN-04 enter the calculation in five places:

1. **C04 requirement**: each receipt open at the point is **added** to the requirement (validate.py:705–708).
2. **C09-ALLOCATION**: each receipt must match one bank credit and be allocated by the next business day.
3. **C11-BANK-ENTRY**: a register `bank_reference` is an acceptable explanation for a bank entry.
4. **Period rule A1**: a register row belongs to the period if it was open at any point in it (schema.py:331–336).
5. **Continuity UNALLOCATED view** (Part H).

### Missing bank statements

If the statement or confirmation for an account-day is missing, `evidence_gap` (validate.py:223–231) returns `MISSING_BANK_EVIDENCE|acct|d`. It also returns a root when an excluded IN-08, IN-07 or IN-09 row could belong to that account-day. The following checks then return INSUFFICIENT_EVIDENCE with that root instead of FAIL:

- C14-COVER (IN-07, IN-08)
- DQ22 (statement gap)
- CASH-BANK-LINK
- C07-BANK-EVIDENCE and C08-DIFFERENCE (no confirmation)
- C11-BATCH-BANK
- FUND-TOPUP
- RC4-DIRECT
- C09-ALLOCATION

All of these share one root, so they form **one** Critical exception. **C08 is never computed from the firm's reported bank figure.** The ledger side and the internal reconciliation still run. Worked examples: February EXC-H202602-01 (J.1) and S02.

### Currency isolation

Every computation is keyed by one currency or one account. C13-CURRENCY (Part F) asserts that each record's currency equals its account's or batch's currency. `check_internal` maps currency to the safeguarding account (`acct_of_ccy`, validate.py:688). No FX conversion exists anywhere.

---

# Part B — Data-quality, file and coverage controls

### V00-FILE — INTEGRITY (not named in the source-to-control matrix)

| | |
|---|---|
| 2 Purpose | Confirm each expected evidence file is present for this period and unchanged since intake. |
| 3 Question | Do we have every required file for this month, and is it the file that was registered? |
| 4 Inputs | All of IN-01 to IN-19 (file level); case metadata `manifest.csv`, `intake.csv`. |
| 5 Columns | manifest: `file_id`, `filename`, `sha256`, `record_count`; intake: `decision`, `file_id`, `original_path`, `probable_file_id`, `reason`. |
| 6 Join / match | File ID → canonical path `period.filename(fid)` (period.py:231–232). Manifest row by `file_id`, preferring the row whose filename is the one read (validate.py:241–243). |
| 7 Grouping | Per file ID. |
| 8 Calculation | `load` validate.py:254–281: (a) intake AMBIGUOUS and no file → AMBIGUOUS; (b) no file → MISSING (required) or optional missing; (c) SHA-256 of bytes ≠ manifest `sha256` → mismatch; (d) manifest present but file not listed. `check_other_periods` 283–296: a canonical file of another month (not IN-19) → reported. |
| 9 Tolerance | None. Exact hash equality. |
| 10 Dates | Month token in file name (`MONTH_TOKEN`, period.py:65). |
| 11 Missing evidence | Required missing → INSUF, root `MISSING_FILE|fid`. Optional missing → NOT_APPLICABLE, no root. Ambiguous → INSUF (required) or NA (optional), root `AMBIGUOUS_FILE|fid`. The file is then unavailable and gates dependent checks (Part G). |
| 12 Output | One row per file event; scope = file ID; `computed` = actual hash or name, `reported` = manifest hash or expected name. |
| 13 Outcomes | **PASS: never emitted.** FAIL: hash mismatch, not in manifest, other period's file. INSUF: required missing/ambiguous. NA: optional missing/ambiguous. |
| 14 Exceptions | `MISSING_FILE`, `AMBIGUOUS_FILE` → Critical, flag "dependent checks were not run on incomplete evidence" (validate.py:1268–1269). FAIL rows without root → `V00-FILE|fid`, High. |
| 15 Tests | `test_period_config.py::CaseResolution::test_other_period_file_in_a_case_is_reported_and_not_used`; `test_period_config.py::DocumentApplicability::test_optional_documents_do_not_block_and_missing_stays_missing`; `test_baseline.py::Regressions::test_not_applicable_only_where_documented`; `test_hardening.py::MissingEvidence::test_missing_calendar`, `::test_missing_account_inventory`, `::test_missing_cash_book`, `::test_missing_policy_pdf`; `test_hardening.py::CasePreparation::test_ambiguous_candidates_are_not_selected`. |
| 16 Limitations | Without a manifest, hash checking is skipped (validate.py:1581). No PASS row, so a clean case has no V00-FILE line in the control register. |
| **Why** | Before any number is trusted, you need to know you are looking at the right, complete and unaltered set of files for the month. |

### V01-SCHEMA — Data-quality checks (DQ)

| | |
|---|---|
| 2 Purpose | Confirm each CSV is readable, has the exact contracted header, and has rows where rows are required. |
| 3 Question | Can this file be read as the evidence type it claims to be? |
| 4 Inputs | IN-01 to IN-14. |
| 5 Columns | The full column list per file, `schema.columns(fid)` (schema.py:216–217). |
| 6 Join / match | Header list equality with the schema list, including order and case. |
| 7 Grouping | Per file. |
| 8 Calculation | `load_csv` validate.py:298–336: UTF-8 read (`structure.read_csv`); `header != expected_cols` → unusable (with `diagnose_header` explanation); no rows and not in `EMPTY_ALLOWED` → empty; else `check_rows`; problems = invalid rows and/or row count ≠ manifest `record_count`. |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | Empty required file → INSUF, root `EMPTY_FILE|fid`. Unreadable or wrong header → FAIL, root `INVALID_FILE|fid`. The file is unavailable. |
| 12 Output | Scope = file ID; `computed` "N rows", `reported` manifest count. |
| 13 Outcomes | PASS: readable, exact header, rows valid, count matches. FAIL: wrong header, unreadable, invalid rows (root `INVALID_ROWS|fid`), count mismatch. INSUF: empty. |
| 14 Exceptions | `INVALID_FILE`, `EMPTY_FILE` Critical; `INVALID_ROWS` High; all with the file flag. |
| 15 Tests | `test_hardening.py::MissingEvidence::test_present_but_empty_required_file`, `::test_wrong_header_is_unusable_not_missing`, `::test_empty_allowed_file_is_not_an_issue`; `test_hardening.py::MalformedRows::test_bad_identifier`. |
| 16 Limitations | Header matching is strict by design; a reordered but otherwise correct export is rejected (the diagnosis only explains it). |
| **Why** | A file with the wrong columns can silently put amounts in the wrong field. Exactness prevents that. |

### V01-PDF — Data-quality checks (DQ)

| | |
|---|---|
| 2 Purpose | Confirm each PDF is a genuine PDF with every key-details label, and that the policy states a usable point and effective date. |
| 3 Question | Can the letter, policy, register or receipt be read reliably? |
| 4 Inputs | IN-15 to IN-19. |
| 5 Columns | Key-details labels, `schema.PDF_FILES[fid][3]` (schema.py:199–211), for example "Reconciliation point", "Effective date", "Letter reference". |
| 6 Join / match | Regex `^{label}: (.+)$` per line of extracted text (validate.py:381–384). |
| 7 Grouping | Per file. |
| 8 Calculation | `load_pdf` 365–394: `%PDF-` header; pypdf text extraction; all labels present; page count vs manifest. `setup` 441–456: "Reconciliation point" must match `^HH:MM Europe/London$`; "Effective date" must not be after the period end. |
| 9 Tolerance | None. |
| 10 Dates | Effective date compared with `period.end` (validate.py:450). |
| 11 Missing evidence | Missing file is V00-FILE. Unusable → state UNUSABLE, root `INVALID_FILE|fid`. |
| 12 Output | Scope = file ID; `computed` "N page(s)" or the policy value; note explains. |
| 13 Outcomes | PASS: genuine PDF, labels parsed, pages match. FAIL: not a PDF, unreadable, labels missing, page-count mismatch (no root, so `V01-PDF|fid`), malformed point, effective after period end. |
| 14 Exceptions | `INVALID_FILE` Critical; `V01-PDF|fid` High. |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_renamed_text_file_is_not_a_pdf`; `test_period_config.py::DocumentApplicability::test_policy_effective_after_the_period_is_not_applied`; `test_demo_history.py::PeriodAwareEngine::test_policy_effective_after_the_period_is_never_applied`. |
| 16 Limitations | Key details are parsed from a fixed synthetic layout; no human confirmation (`pack/config.py` LIMITATIONS line 17). |
| **Why** | The policy sets the 17:00 cut-off and the letters prove the accounts are designated. If they cannot be read, the checks that depend on them must not run. |

### DQ-FIELD — Data-quality checks (DQ)

| | |
|---|---|
| 2 Purpose | Exclude any row whose fields do not meet the documented format, and say exactly why. |
| 3 Question | Is every row well-formed enough to be used in a calculation? |
| 4 Inputs | IN-01 to IN-14. |
| 5 Columns | Every column, typed per schema (id, str, date, ts, bool, int, amount, signed, ccy, enum). |
| 6 Join / match | Primary key = first column of each file (`check_rows`, structure.py:91); duplicates after the first are invalid. |
| 7 Grouping | One result per (file, line, field) finding. |
| 8 Calculation | `structure.check_rows` 83–119: field-count check; mandatory present; `field_error` per type (42–68); `schema.CONDITIONAL`; duplicate key. Invalid rows are recorded in `self.taint` via `taint_scope` (structure.py:122–146). |
| 9 Tolerance | None. Amounts must be exactly 2 dp. |
| 10 Dates | ISO date `YYYY-MM-DD`; timestamps must carry an offset (`parse_ts`, structure.py:35–39). |
| 11 Missing evidence | The row is excluded, and any scope it could touch becomes INSUF (Part G). |
| 12 Output | Scope `"{fid} L{line} {field}"`; `computed` = error; `reported` = raw value. |
| 13 Outcomes | FAIL only (emitted only for findings). |
| 14 Exceptions | All findings of a file share root `INVALID_ROWS|fid`: one High exception per file. In IN-01 or IN-02 the file also becomes unusable. |
| 15 Tests | `test_hardening.py::MalformedRows::test_bad_debit_credit_code`, `::test_amount_with_thousands_separator_is_rejected_not_converted`, `::test_unknown_batch_direction`, `::test_bad_date_taints_every_scope_it_might_touch`, `::test_bad_identifier`, `::test_wrong_number_of_fields`, `::test_invalid_row_in_scope_file_makes_it_unusable`; `test_period_and_headers.py::ReportingPeriod::test_6_malformed_date_is_a_structure_finding_not_a_period_finding`. |
| 16 Limitations | An unreadable key field on an excluded row is treated as matching *every* scope, which is conservative and can widen INSUF. |
| **Why** | A badly formatted amount (for example "1,000.00") could be misread. It is never converted or guessed, only excluded and reported. |

### DQ-PERIOD — Data-quality checks (DQ)

| | |
|---|---|
| 2 Purpose | Keep only rows that belong to the reporting month, plus the documented boundary records. |
| 3 Question | Does each row relate to this month? |
| 4 Inputs | IN-01, IN-03 to IN-14 (rules in `schema.PERIOD_RULES`, schema.py:326–355; IN-02, IN-13 and PDFs are not period-checked, `PERIOD_UNCHECKED` 358–371). |
| 5 Columns | IN-01 `calendar_date`, `period_id`; IN-03 `recon_date`; IN-04 `receipt_date`, `receipt_ts`, `allocated_date`, `allocated_ts`; IN-05/06 `recon_date`; IN-07 `as_at_ts`; IN-08 `statement_date`; IN-09 `booking_date`, `booking_ts`; IN-10 `posted_ts`; IN-11 `executed_ts`; IN-12 `settlement_date`; IN-14 `recon_ref`, `logged_ts`. |
| 6 Join / match | IN-14 `recon_ref` → IN-05 `recon_run_id` or IN-06 `ext_recon_id` to find its reconciliation date (`event_ref`, schema.py:352–354; validate.py:342–344). |
| 7 Grouping | Per file; one result per out-of-period finding. |
| 8 Calculation | `structure.check_period` 170–238: permitted boundary rows kept; `equals` (IN-01 `period_id`); `in_period` dates within start..end; IN-04 open-during-period; IN-14 must refer to an in-period reconciliation and not be logged before it; IN-14 logged after period end kept and flagged `_subsequent`. |
| 9 Tolerance | None. |
| 10 Dates | Timestamps converted to Europe/London dates (`_local_date`, structure.py:150–154). Boundary timestamps compared as instants (157–167). |
| 11 Missing evidence | 0 applicable rows → file WRONG_PERIOD (unusable). Otherwise rows excluded and tainted. |
| 12 Output | WRONG_PERIOD: scope = file ID. Rows: scope `"{fid} L{line} {field}"`. |
| 13 Outcomes | FAIL only. |
| 14 Exceptions | `WRONG_PERIOD|fid` Critical; `OUT_OF_PERIOD_ROWS|fid` High. |
| 15 Tests | `test_period_and_headers.py::ReportingPeriod::test_2_august_bank_confirmation_file_is_one_wrong_period_exception`, `::test_3_single_stray_august_row_is_excluded_and_reported`, `::test_4c_file_with_only_the_opening_row_is_wrong_period`, `::test_7_mixed_file_keeps_september_rows`; `test_period_decisions.py::A1UnallocatedReceipts::test_open_during_period_rule`; `test_period_decisions.py::A2DiscrepancyLog::test_entry_logged_after_period_end_counts_and_is_labelled`, `::test_entry_logged_before_the_reconciliation_is_excluded`, `::test_log_with_no_september_entries_is_wrong_period`; `test_demo_history.py::DatesAndTime::test_september_opening_rows_are_not_august_activity`. |
| 16 Limitations | `value_date`, `auth_ts`, `clearing_date`, `cycle_date` and `resolved_ts` are deliberately unchecked (schema.py:358–371). |
| **Why** | Mixing months would make balances meaningless. Only this month's activity and the opening position may be used. |

### C03-POLICY — Reconciliation point

| | |
|---|---|
| 2 Purpose | Confirm the governing policy prescribes the method the engine implements. |
| 3 Question | Does the policy say "standard method, per currency"? |
| 4 Inputs | IN-17. |
| 5 Columns | PDF labels "Reconciliation method", "Internal reconciliation basis", "Reconciliation point". |
| 6 Join / match | n/a. |
| 7 Grouping | Period (scope "period"). |
| 8 Calculation | validate.py:464: PASS iff method == "STANDARD" and basis == "Per currency". |
| 9 Tolerance | Exact text. |
| 10 Dates | Effective-date guard in `setup` (A.4). |
| 11 Missing evidence | Gate on IN-17 (`schema.DEPENDS` line 283): one INSUF "all scopes", root of IN-17's state. |
| 12 Output | One row; `computed` "point HH:MM; method …; basis …". |
| 13 Outcomes | PASS / FAIL / INSUF (gate). |
| 14 Exceptions | FAIL → `C03-POLICY|period` High. |
| 15 Tests | `test_historical_integration.py::Intake::test_selection_reaches_the_pack_audit_trail_and_results_equal_the_stored_pack`; `test_historical_integration.py::HistoricalUpload::test_may_upload_keeps_both_policies_and_processes_with_v12`; `test_demo_history.py::PeriodAwareEngine::test_may_policy_comparison_is_identical_apart_from_the_file_cited`. |
| 16 Limitations | Note in code: "reviewer confirmation not modelled in milestone 1" (validate.py:466). |
| **Why** | The calculations below assume one method. If the policy said otherwise, the results would not answer the policy's question. |

### C03-POINT — Reconciliation point

| | |
|---|---|
| 2 Purpose | Confirm every point-dependent record was taken at the policy's 17:00 point. |
| 3 Question | Were the firm's reconciliations, client snapshots and bank confirmations all taken at the right time? |
| 4 Inputs | IN-17, IN-05, IN-03, IN-07. |
| 5 Columns | IN-05 `reconciliation_point_ts`, `recon_date`; IN-03 `as_at_ts`, `recon_date`; IN-07 `as_at_ts`. |
| 6 Join / match | Row-wise; date from `recon_date`. |
| 7 Grouping | One result per file (scope IN-05, IN-03, IN-07). |
| 8 Calculation | validate.py:468–480: IN-05/IN-03 off-point if `parse_ts(ts) != point(recon_date)` (instant equality); IN-07 off-point if wall-clock time ≠ `point_time`. |
| 9 Tolerance | None: exact second. |
| 10 Dates | IN-05/03: DST-aware instant. IN-07: offset ignored (A.7). |
| 11 Missing evidence | Gate on IN-17; per-file INSUF if that file is unavailable. |
| 12 Output | `computed` "N off-point of M"; evidence cites up to 5 off-point rows. |
| 13 Outcomes | PASS (0 off-point), FAIL (any), INSUF. |
| 14 Exceptions | `C03-POINT|IN-xx` High. |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_renamed_text_file_is_not_a_pdf` (gated path). No test naming the ID asserts the FAIL path. |
| 16 Limitations | It does not check IN-08 `as_at_ts` (unused, schema.py:364). |
| **Why** | A balance taken at 16:00 cannot be compared with one taken at 17:00. Every figure must be "as at" the same moment. |

### C01-COVER — Internal reconciliation existence

| | |
|---|---|
| 2 Purpose | Confirm the firm performed one internal reconciliation per currency on every reconciliation day. |
| 3 Question | Is there exactly one internal reconciliation record for each day and currency? |
| 4 Inputs | IN-01, IN-02, IN-05 (DEPENDS line 285). |
| 5 Columns | IN-01 `calendar_date`, `is_recon_day`; IN-02 `account_class`, `currency`; IN-05 `recon_date`, `currency`. |
| 6 Join / match | Index IN-05 by (`recon_date`, `currency`) (validate.py:492). |
| 7 Grouping | Reconciliation day × currency of the safeguarding accounts. |
| 8 Calculation | validate.py:509–513 and `_cover` 534–547: count of records = 1 → PASS; 0 → missing; >1 → duplicates. |
| 9 Tolerance | None. |
| 10 Dates | Plain dates. |
| 11 Missing evidence | Record absent → **FAIL** (the firm failed to reconcile), root `MISSING_RECON|ccy|d`. Absent but an excluded IN-05 row could be it → INSUF with that row's root. |
| 12 Output | Scope `"IN-05 {d}/{ccy}"`; evidence cites the IN-01 and IN-02 rows that create the expectation. |
| 13 Outcomes | PASS / FAIL (absent, duplicate) / INSUF (taint or gate). |
| 14 Exceptions | `MISSING_RECON` Critical; duplicates → `C01-COVER|IN-05 …` High. |
| 15 Tests | Covered by the three all-check tests only (see "How to read"). |
| 16 Limitations | With no IN-05 record for a day, C04–C06 produce **no** result for that day (they iterate IN-05 rows, validate.py:689); the gap shows only here. |
| **Why** | A missing daily reconciliation is itself a failure, not a gap in evidence. |

### C07-COVER — External existence and statement agreement

| | |
|---|---|
| 2 Purpose | Confirm one external reconciliation per safeguarding account per reconciliation day. |
| 3 Question | Did the firm reconcile each safeguarding account to the bank every day? |
| 4 Inputs | IN-01, IN-02, IN-06. |
| 5 Columns | IN-06 `recon_date`, `account_id`. |
| 6 Join / match | Index IN-06 by (`recon_date`, `account_id`) (validate.py:493). |
| 7 Grouping | Reconciliation day × safeguarding account. |
| 8 Calculation | validate.py:522–525 + `_cover`. |
| 9 Tolerance | None. |
| 10 Dates | Plain dates. |
| 11 Missing evidence | Absent → **FAIL**, root `MISSING_EXT_RECON|acct|d`; taint → INSUF. |
| 12 Output | Scope `"IN-06 {d}/{acct}"`. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `MISSING_EXT_RECON` Critical. |
| 15 Tests | All-check tests only. |
| 16 Limitations | As C01: no C07/RC2/C08 rows exist for a day with no IN-06 record. |
| **Why** | Each safeguarding bank account must be agreed to the bank daily. A skipped day is a failure. |

### C14-COVER — Reporting period and recon-day completeness

| | |
|---|---|
| 2 Purpose | Confirm the underlying evidence exists for every scope the month requires. |
| 3 Question | For each day, do we hold every client snapshot, both settlement batches per currency, the 17:00 confirmation for each safeguarding account, and an EOD statement for every account? |
| 4 Inputs | IN-01, IN-02 (gate); IN-03, IN-12, IN-07, IN-08. |
| 5 Columns | IN-03 `recon_date`, `currency`, `client_id`; IN-12 `settlement_date`, `currency`, `counterparty_type`; IN-07 `as_at_ts`, `account_id`; IN-08 `statement_date`, `account_id`. |
| 6 Join / match | Indexes at validate.py:494–500. Expected clients per currency = every `client_id` seen in IN-03 for that currency (497–499). |
| 7 Grouping | IN-03: day × currency × client. IN-12: day × currency × {SCHEME, ACQUIRER}. IN-07: day × safeguarding account. IN-08: day × **every** account (including own funds). |
| 8 Calculation | validate.py:503–532 + `_cover`. |
| 9 Tolerance | None. Expecting both batch types daily is hardcoded (line 519). |
| 10 Dates | IN-07 date from the timestamp as written. |
| 11 Missing evidence | Absent → **INSUF** (evidence missing): roots `MISSING_SNAPSHOT|ccy|d`, `MISSING_BATCH|ccy|d`, `MISSING_BANK_EVIDENCE|acct|d`. A file unavailable → one INSUF "IN-xx all scopes". |
| 12 Output | Scope `"IN-xx {d}/…"`. |
| 13 Outcomes | PASS / INSUF (absent, taint) / FAIL (duplicates). |
| 14 Exceptions | `MISSING_BANK_EVIDENCE` Critical (shared with all other checks for that account-day). `MISSING_SNAPSHOT`, `MISSING_BATCH` High (not in `SEVERITY`, so default High). |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_missing_bank_confirmation_is_insufficient_not_zero`. |
| 16 Limitations | A client absent from the whole file is not expected, because expectations come from IN-03 itself. A real day without card activity would be INSUF. |
| **Why** | Every figure needs its source. This check lists what is missing so nothing is silently treated as nil. |

---

# Part C — Internal reconciliation

The internal reconciliation compares what the firm **owes** clients (requirement) with what it **holds** for them according to its own ledger (resource), per currency, at 17:00 on each reconciliation day. It is **ledger-based**. The bank balance is not used, so a debit that appears only at the bank is caught by the external reconciliation (Part D), not here (see S05, J.2).

**Unit:** one result per **IN-05 row**, meaning one currency on one reconciliation day (scope `YYYY-MM-DD/CCY`), from the loop at validate.py:689. Let *P* = `point(d)`.

**Gating:** C04 needs IN-01, 03, 04, 05 and 17. C05 needs IN-01, 02, 05, 10 and 17. C06 needs the union of both (`schema.DEPENDS`, schema.py:293–295). If neither C04 nor C05 can run, nothing is emitted beyond the gate result (validate.py:683–684).

**Computed vs reported.** "Computed" is always the engine's own figure from source rows. "Reported" is copied unchanged from the firm's IN-05 record. A reported figure is never used in place of a computed one, apart from items B–D. Agreement between the two does not make a non-zero difference acceptable. The pack's `reconciliation_summary.internal_by_currency_day` shows both side by side (assemble.py:182–196).

### C04-REQUIREMENT — Requirement

| | |
|---|---|
| 2 Purpose | Recompute the safeguarding requirement and compare it with the firm's figure. |
| 3 Question | How much must be safeguarded in this currency at 17:00 today, and did the firm report that amount? |
| 4 Inputs | IN-01, IN-03, IN-04, IN-05, IN-17. |
| 5 Columns | IN-03 `recon_date`, `currency`, `balance`; IN-04 `currency`, `receipt_ts`, `allocated_ts`, `amount`; IN-05 `recon_date`, `currency`, `requirement_reported`. |
| 6 Join / match | Snapshots keyed (`recon_date`, `currency`) (validate.py:685–687); receipts filtered by currency and time. |
| 7 Grouping | Day × currency. |
| 8 Calculation | validate.py:696–712: `Requirement(d, ccy) = Σ max(0, balance) over IN-03 rows for (d, ccy) + Σ amount of IN-04 rows in ccy with receipt_ts ≤ P and (allocated_ts blank or allocated_ts > P)`. Compare with `parse_signed(requirement_reported)`. |
| 9 Tolerance | None (`req == rep`, line 710). |
| 10 Dates | Snapshot by `recon_date`; receipts by instant against P (DST-aware). |
| 11 Missing evidence | No snapshots for (d, ccy) → INSUF root `MISSING_SNAPSHOT|ccy|d`. An excluded IN-03 row for (ccy, d), or an excluded IN-04 row in ccy dated on or before d → INSUF with its root (line 698). |
| 12 Output | `computed` requirement, `reported` firm figure; note "sum of N non-negative client balances + M open unallocated receipt(s)"; evidence cites the IN-03 line range and each open IN-04 row. |
| 13 Outcomes | PASS if equal; FAIL if not; INSUF as above. |
| 14 Exceptions | FAIL → `C04-REQUIREMENT|d/ccy` High. Linked to a same-scope internal difference by L3 (validate.py:1407–1412). |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_reported_requirement_is_not_trusted`; `test_baseline.py::CleanBaseline::test_essential_checks_ran_on_every_scope`; `test_baseline.py::Scenarios::test_s02_must_hold`, `::test_s05_must_hold`; `test_period_decisions.py::A1UnallocatedReceipts::test_september_receipt_allocated_1_october_counts_as_open_on_30_september`; `test_hardening.py::MissingEvidence::test_missing_cash_book`; `test_demo_history.py::ScenarioBehaviour::test_unexplained_gbp_difference_march`. |
| 16 Limitations | Negative balances count as zero here and are reported separately (CBAL-NONNEG). The client ledger is taken as the source of client balances; the engine has no independent client ledger. |
| **Why** | This is the amount owed to customers. The firm's own figure is never trusted without recomputing it. |

### C05-RESOURCE — Resource

| | |
|---|---|
| 2 Purpose | Recompute item A of the safeguarding resource from the cash book. |
| 3 Question | What does the firm's ledger say it holds in the safeguarding account at 17:00, and does the reported resource add up? |
| 4 Inputs | IN-01, IN-02, IN-05, IN-10, IN-17. |
| 5 Columns | IN-10 `account_id`, `posted_ts`, `entry_type`, `amount`, `dc_indicator`; IN-05 `item_a`, `item_b`, `item_c`, `item_d`, `resource_reported`; IN-02 `account_id`, `account_class`, `currency`. |
| 6 Join / match | Currency → safeguarding account via `acct_of_ccy = {currency: account}` (validate.py:688). |
| 7 Grouping | Day × currency. |
| 8 Calculation | `ledger_at` 668–678: `Item A = Σ signed(amount, dc, "cashbook")` over IN-10 rows of the account with `posted_ts ≤ P`, **including** the OPENING_BALANCE row. Then `Resource = Item A + item_b + item_c + item_d` (lines 717, 724), with B–D taken as reported. PASS iff `Item A == item_a` **and** `Resource == resource_reported` (725). |
| 9 Tolerance | None. |
| 10 Dates | `posted_ts` against P as an instant. |
| 11 Missing evidence | No OPENING_BALANCE row, or an excluded IN-10 row for the account dated in [period start, d] → Item A `None` → INSUF (root: the taint root, or `MISSING_FILE|IN-10`). |
| 12 Output | `computed` "item A x; resource y"; `structured` = {`item_a`, `items_b_to_d`, `resource`, `item_a_reported`, `resource_reported`}. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | FAIL → `C05-RESOURCE|d/ccy` High. |
| 15 Tests | `test_audit_pack.py::D3StructuredFields::test_resource_fields_match_the_existing_computed_text`; `test_baseline.py::ChecksCanFail::test_cashbook_change_breaks_resource_and_ledger`; `test_hardening.py::MalformedRows::test_bad_date_taints_every_scope_it_might_touch`; `test_baseline.py::Scenarios::test_s02_must_hold`, `::test_s05_must_hold`. |
| 16 Limitations | Items B–D are not verified (`pack/config.py` LIMITATIONS line 15). One safeguarding account per currency is assumed (a dict, line 688). If no safeguarding account exists for a currency, the INSUF root reads `MISSING_FILE|IN-10`, which is misleading. |
| **Why** | Item A is what the firm's own books say is in the safeguarding account. It must be rebuilt from postings, not copied. |

### C06-DIFFERENCE — Internal difference handling

| | |
|---|---|
| 2 Purpose | Compute resource − requirement and flag any shortfall or excess. |
| 3 Question | Does the firm hold exactly what it owes clients in this currency today? |
| 4 Inputs | Union of C04 and C05 inputs. |
| 5 Columns | IN-05 `difference_reported`, plus the C04 and C05 columns. |
| 6 Join / match | Same IN-05 row. |
| 7 Grouping | Day × currency. |
| 8 Calculation | validate.py:733–744: `Difference = Resource − Requirement`, compared with `difference_reported`. |
| 9 Tolerance | None (`diff != rep`, line 739). |
| 10 Dates | As C04/C05. |
| 11 Missing evidence | Either side `None` → INSUF with the first root (line 736). |
| 12 Output | `computed` difference; `reported` firm difference. |
| 13 Outcomes | INSUF if not computable. FAIL "reported difference differs from recomputed" if computed ≠ reported. NOT_APPLICABLE "no difference to resolve" if both 0.00. FAIL "difference requires same-day resolution (CASS 15.8.50R)" if computed = reported ≠ 0.00. |
| 14 Exceptions | Each FAIL day → its own `INTERNAL_DIFFERENCE|d/ccy`, Critical (validate.py:1237–1239). **Consecutive days are not merged.** They are linked by L2 PERSISTENCE when the value and currency are the same on consecutive reconciliation days (1374–1382), and by L3 to roll-forward or requirement failures (1395–1412). |
| 15 Tests | `test_baseline.py::Regressions::test_not_applicable_only_where_documented`; `test_e1_e2.py::E2InvestigationGroups::test_e2_2_refund_twice_group`; `test_e1_e2.py::E2InvestigationGroups::test_e2_3_closing_snapshot_group`; `test_demo_history.py::ScenarioBehaviour::test_unexplained_gbp_difference_march`; `test_review_hardening.py::ContradictionClassification::test_s05_internal_vs_external_views_are_not_a_contradiction`. |
| 16 Limitations | Exceptions for internal differences carry blank `account_id`, `currency` and `amount` (only bank-ledger and unmatched-entry kinds populate them, validate.py:1254–1273). |
| **Why** | A non-zero difference means client money is under- or over-protected. Even if the firm reported it correctly, it still needs same-day action. |

### CBAL-NONNEG — Requirement

| | |
|---|---|
| 2 Purpose | Flag any negative client balance. |
| 3 Question | Does any client show a negative e-money balance? |
| 4 Inputs | IN-03. |
| 5 Columns | `balance`. |
| 6 Join / match | n/a. |
| 7 Grouping | All snapshots (one result, scope "all snapshots"). |
| 8 Calculation | validate.py:1058–1061: count rows with `balance < 0`. |
| 9 Tolerance | None. |
| 10 Dates | All in-period and boundary snapshots. |
| 11 Missing evidence | Gate on IN-03. |
| 12 Output | `computed` "N negative"; evidence cites up to 5 rows. |
| 13 Outcomes | PASS (0) / FAIL (≥1) / INSUF (gate). |
| 14 Exceptions | `CBAL-NONNEG|all snapshots` High. |
| 15 Tests | `test_demo_history.py::ScenarioInteraction::test_scenarios_do_not_break_customer_balance_continuity`. |
| 16 Limitations | One result for the whole month; it does not say which day first went negative beyond the cited rows. |
| **Why** | A negative balance is an anomaly that C04 hides by treating it as zero, so it is reported separately. |

### CBAL-ROLLFWD — Requirement

| | |
|---|---|
| 2 Purpose | Prove each client's balance moves only by recorded transactions between reconciliation points. |
| 3 Question | Does yesterday's balance plus today's transactions equal today's balance, for every client? |
| 4 Inputs | IN-03, IN-11, IN-17. |
| 5 Columns | IN-03 `currency`, `client_id`, `recon_date`, `balance`; IN-11 `currency`, `client_id`, `executed_ts`, `amount`, `direction`. |
| 6 Join / match | Snapshots and transactions keyed (`currency`, `client_id`) (validate.py:1064–1069). |
| 7 Grouping | Currency × client × consecutive pair of snapshot dates (the first snapshot, normally the previous month-end, is the starting point and is not itself assessed). |
| 8 Calculation | validate.py:1070–1086: `expected = balance(prev) + Σ signed(amount, direction, "client")` for transactions with `point(prev) < executed_ts ≤ point(cur)`; compare with `balance(cur)`. |
| 9 Tolerance | None. |
| 10 Dates | Instants against DST-aware points. |
| 11 Missing evidence | An excluded IN-03 row for either day, or an excluded IN-11 row for the client and currency on any date in the window → INSUF. |
| 12 Output | Scope `"{ccy}/{client} {cur}"`; `computed` expected, `reported` actual snapshot. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `CBAL-ROLLFWD|{ccy}/{client} {date}` High; linked by L3 to an internal difference or requirement failure on the same currency and day (1395–1406). Unverified CAND links to C11-BATCH-ARITH (1442–1471). |
| 15 Tests | `test_scenario_datasets.py::ScenarioDatasets::test_opening_client_snapshot`; `test_e1_e2.py::E2Negative::test_e2_10_equal_amounts_without_reference_or_lineage_not_grouped`; `test_demo_history.py::ScenarioInteraction::test_scenarios_do_not_break_customer_balance_continuity`; `test_review_hardening.py` (`test_missing_scope_or_missing_evidence_is_not_proof_of_contradiction`). |
| 16 Limitations | A persistent error introduced on one day fails only that day (later days roll forward consistently). See SC5C (J.4). |
| **Why** | A balance that changes without a transaction means the client ledger cannot be relied on, and the requirement is built from it. |

---

# Part D — External reconciliation and bank evidence

The external reconciliation compares the **bank's** balance at 17:00 with the firm's **ledger** for the same safeguarding account. Supporting checks prove the bank evidence is internally consistent and that cash-book and bank entries correspond.

**Unit for C07/RC2/C08:** one result per **IN-06 row** (scope `YYYY-MM-DD/ACCOUNT`).

**Role of each bank file:**

- **IN-07 (17:00 confirmation)** is the bank side of C08.
- **IN-08 (EOD statements)** is *not* a side of C08. It is used for DQ23, DQ22, BC-VS-EOD and `evidence_gap`.
- **IN-09 (entries)** links to the cash book by reference.
- **IN-10 (cash book)** is the ledger side.
- **IN-06 (firm records)** supplies only the reported figures and the cited statement ID.

### C07-BANK-EVIDENCE — External existence and statement agreement

| | |
|---|---|
| 2 Purpose | Verify the bank balance the firm reported against the bank confirmation it cites. |
| 3 Question | Does the bank's own 17:00 confirmation say what the firm says the bank balance was? |
| 4 Inputs | IN-01, IN-02, IN-06, IN-07. |
| 5 Columns | IN-06 `recon_date`, `account_id`, `currency`, `bank_statement_id`, `bank_balance_reported`; IN-07 `statement_id`, `account_id`, `as_at_ts`, `currency`, `balance_amount`, `balance_dc_indicator`. |
| 6 Join / match | IN-06 `bank_statement_id` = IN-07 `statement_id` (validate.py:756). |
| 7 Grouping | Day × safeguarding account. |
| 8 Calculation | Lines 755–771: `Bank = signed(balance_amount, balance_dc_indicator, "bank")`. PASS iff confirmation account = record account, and confirmation currency = record currency = account currency, and as-at date = d, and Bank = `bank_balance_reported`. |
| 9 Tolerance | None. |
| 10 Dates | As-at date from the timestamp as written. |
| 11 Missing evidence | Cited confirmation not found → INSUF "cited statement … not provided; reported bank balance is unverified", root `MISSING_BANK_EVIDENCE|acct|d`, or the taint root if an excluded IN-07 row could be it. |
| 12 Output | `computed` bank balance; `reported` firm figure. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | Missing → shared `MISSING_BANK_EVIDENCE` Critical; FAIL → `C07-BANK-EVIDENCE|d/acct` High. |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_missing_bank_confirmation_is_insufficient_not_zero`; `test_demo_history.py::ScenarioBehaviour::test_missing_eur_statement_february`; `test_hardening.py::MissingEvidence::test_missing_policy_pdf`; `test_period_and_headers.py::ReportingPeriod::test_7_mixed_file_keeps_september_rows`; `test_baseline.py::Scenarios::test_s02_must_hold`. |
| 16 Limitations | If the cited confirmation exists but belongs to the wrong account or date, C07 FAILs, yet C08 still uses that bank figure (`bank` is set before the `ok` test, lines 766–768). |
| **Why** | The bank balance must come from the bank, not from the firm's spreadsheet. |

### RC2-LEDGER — External existence and statement agreement

| | |
|---|---|
| 2 Purpose | Recompute the ledger balance the firm reported. |
| 3 Question | Does the firm's cash book really show the ledger balance it reported at 17:00? |
| 4 Inputs | IN-02, IN-06, IN-10, IN-17. |
| 5 Columns | IN-06 `ledger_balance_reported`; IN-10 as for C05. |
| 6 Join / match | IN-06 `account_id` = IN-10 `account_id`. |
| 7 Grouping | Day × safeguarding account. |
| 8 Calculation | Lines 772–781: `Ledger = ledger_at(acct, point(d))`, the same function as Item A. |
| 9 Tolerance | None. |
| 10 Dates | `posted_ts ≤ P`. |
| 11 Missing evidence | Not computable → INSUF, root the taint root or `MISSING_FILE|IN-10`. |
| 12 Output | `computed` ledger; `reported` firm figure; evidence "(N entries)". |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `RC2-LEDGER|d/acct` High. |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_cashbook_change_breaks_resource_and_ledger`; `test_baseline.py::CleanBaseline::test_essential_checks_ran_on_every_scope`; `test_baseline.py::Scenarios::test_s05_must_hold`. |
| 16 Limitations | As `ledger_at`. |
| **Why** | The ledger side must also be rebuilt from postings. Otherwise a wrong ledger figure could hide a real difference. |

### C08-DIFFERENCE — External difference handling

| | |
|---|---|
| 2 Purpose | Compute bank − ledger and classify any difference. |
| 3 Question | Does the bank hold what the firm's ledger says it should, and if not, is there evidence of a timing item? |
| 4 Inputs | IN-01, IN-02, IN-06, IN-07, IN-10, IN-17; IN-09 for timing evidence. |
| 5 Columns | IN-06 `difference_reported`, `timing_difference_claimed`; plus C07 and RC2 columns. Timing: IN-10 `payment_reference`, `posted_ts`, `amount`, `dc_indicator`, `currency`; IN-09 `bank_reference`, `end_to_end_ref`, `booking_ts`, `amount`, `dc_indicator`, `currency`. |
| 6 Join / match | Same IN-06 row. Timing items: cash-book entry linked to exactly one bank entry on the same account by reference, with equal signed amount and currency (`timing_items`, 99–145). |
| 7 Grouping | Day × account. Exceptions group consecutive days (below). |
| 8 Calculation | Line 789: `Difference = Bank − Ledger`. Timing: an item is a pair where one side is ≤ P and the other > P; effect on (bank − ledger) is −ledger amount (ledger first) or +bank amount (bank first). Status is IN_WINDOW if the later side is ≤ next business day and that day's evidence is usable; OUTSIDE_WINDOW if later; UNVERIFIABLE if after the period end or evidence missing. A ledger entry with no bank match posted on *d* by P, whose next business day is outside the period or lacks evidence, is UNVERIFIABLE. `explained = Σ IN_WINDOW effects`; `residual = diff − explained` (`timing_structured`, 147–156). |
| 9 Tolerance | None. Timing window: one business day (A.6). |
| 10 Dates | Timing dates converted to London (120, 133, 135). |
| 11 Missing evidence | Bank or ledger `None` → INSUF "bank evidence not provided; difference not computed" (or "cash book not available"). The firm's reported difference is **never** used as the result. |
| 12 Output | `computed` difference; `reported`; `evidence_status`; `structured` {`timing_items`[…], `explained_by_timing`, `residual_unexplained`}. |
| 13 Outcomes | See table below. |
| 14 Exceptions | See "Grouping of bank-ledger differences" below. |
| 15 Tests | `test_audit_pack.py::D3StructuredFields::test_timing_structured_consistent_with_the_difference`; `test_e1_e2.py::E1TimingEvidence::test_e1_1_sc2_evidenced_but_open`, `::test_e1_2_short_settlement_and_812_40_remain_unexplained`, `::test_e1_9_nothing_is_resolved_or_closed`, `::test_e1_12_timing_items_only_where_the_scenario_put_them`, `::test_e1_11_baseline_has_no_timing_items`; `test_e1_e2.py::E1EdgeCases::test_e1_3_clearing_two_business_days_later_is_not_evidence`, `::test_e1_4_different_amount_is_not_evidence`, `::test_e1_5_same_amount_different_reference_is_not_evidence`, `::test_e1_6_partial_explanation_reports_residual`, `::test_e1_7_missing_clearing_evidence_is_unverifiable`; `test_e1_e2.py::E1PeriodEnd::test_e1_8_posting_on_30_september_is_unverifiable`; `test_e1_e2.py::E1AdditionalCases` (4 tests); `test_e1_e2.py::E1SameDateAndWeekend` (4 tests); `test_scenario_datasets.py::ScenarioDatasets::test_timing_difference_evidenced_within_one_business_day`, `::test_one_business_day_allowance_does_not_resolve_other_differences`, `::test_812_40_remains_unresolved`; `test_demo_history.py::ScenarioBehaviour::test_missing_eur_statement_february`, `::test_unexplained_gbp_difference_march`. |
| 16 Limitations | See Part M (grouping across two accounts). |
| **Why** | This is the core bank reconciliation. A shortfall at the bank means client money may not be protected, whatever the ledger says. |

C08 outcome conditions:

| Condition | Outcome | Note |
|---|---|---|
| Bank or Ledger is None | INSUFFICIENT_EVIDENCE | "bank evidence not provided; difference not computed" |
| Computed ≠ `difference_reported` | FAIL | "reported difference differs from recomputed" (+ timing detail if the computed difference ≠ 0) |
| Computed = reported = 0.00 | NOT_APPLICABLE | "bank equals ledger" |
| Computed = reported ≠ 0.00 | FAIL | TIMING_EVIDENCED / TIMING_PARTIAL: "bank-ledger difference; …". Otherwise "unexplained bank-ledger difference" (+ "(timing claimed, not evidenced)" if `timing_difference_claimed` = true) |

**Timing evidence never changes the outcome.** The evidence status (TIMING_EVIDENCED, TIMING_PARTIAL, TIMING_UNVERIFIABLE, NOT_EVIDENCED; `timing_assessment`, 158–176) changes only the wording. It says "awaiting human confirmation; not resolved".

**Grouping of bank-ledger differences** (`_group_exceptions`, 1193–1214). C08 FAIL results are sorted by scope. A result joins the previous group if it has the same account, the same computed difference, and is on the **next reconciliation day**. Each group gives one root cause, `BANK_LEDGER_DIFFERENCE|acct|first_date|amount`, which is Critical. The flags are:

- `OWN_FUNDS_REQUIRED` if the amount is negative (CASS 15.8.57R as cited, 1261–1262);
- `NO_INVESTIGATION_LOGGED` if the group's DISC-LOG result FAILs (1263–1264);
- `INVESTIGATION_RECORDED_AFTER_PERIOD_END` (1265–1266).

`related_records` lists unmatched bank entries on the same account booked on the first date, "not linked by amount" (1267, 1285). The exception's `evidence_status` is the single status of its C08 rows. If statuses are mixed, it is TIMING_PARTIAL when any is TIMING_EVIDENCED, otherwise NOT_EVIDENCED (1287–1297).

### DISC-LOG — Internal difference handling / External difference handling

| | |
|---|---|
| 2 Purpose | Confirm every bank-ledger difference was recorded for investigation in the discrepancy log. |
| 3 Question | Did the firm log each difference it should have investigated? |
| 4 Inputs | IN-14 (DEPENDS line 311); the C08 groups. |
| 5 Columns | IN-14 `recon_ref`, `logged_ts` (via period rule). |
| 6 Join / match | Group's `ERL-{acct}-{yyyymmdd}` IDs (one per day in the group, line 1212) ∩ set of IN-14 `recon_ref`. |
| 7 Grouping | One result per bank-ledger difference group (scope `"{acct} from {first_date}"`); or one "period" result if there are no differences. |
| 8 Calculation | Lines 1206–1236: hit = any matching log entry. Late = matching entries flagged `_subsequent` (logged after the period end). |
| 9 Tolerance | None. |
| 10 Dates | Log period follows the reconciliation it refers to (A2, schema.py:348–354). |
| 11 Missing evidence | IN-14 unavailable → gate INSUF; no per-group result. An excluded log entry could be the one → INSUF with its root. |
| 12 Output | `computed` "N day(s) with difference"; `reported` "M log entries". |
| 13 Outcomes | PASS "investigation logged" (plus subsequent-recorded note if late); FAIL "difference not recorded in the discrepancy log (CASS 15.8.56R …)"; PASS "header-only log is consistent with zero differences" when there are no groups; INSUF. |
| 14 Exceptions | Joins the bank-ledger difference's exception (root set to the group root, line 1232). |
| 15 Tests | `test_period_decisions.py::A2DiscrepancyLog::test_entry_logged_after_period_end_counts_and_is_labelled`, `::test_entry_logged_in_september_is_not_labelled`, `::test_log_with_no_september_entries_is_wrong_period`; `test_demo_history.py::ScenarioBehaviour::test_unexplained_gbp_difference_march`. |
| 16 Limitations | Internal (C06) differences are **not** checked against the log. Only the existence of an entry is checked; its amount, status and content are not. |
| **Why** | A difference that nobody logged was probably not investigated. That is a separate failing from the difference itself. |

### DQ23-STATEMENT — Within-statement continuity

| | |
|---|---|
| 2 Purpose | Prove each bank statement adds up internally. |
| 3 Question | Does opening + entries = closing, with the stated number of entries? |
| 4 Inputs | IN-08, IN-09. |
| 5 Columns | IN-08 `statement_id`, `account_id`, `statement_date`, `currency`, `opening_balance_amount`, `opening_balance_dc`, `closing_balance_amount`, `closing_balance_dc`, `entry_count`; IN-09 `statement_id`, `account_id`, `currency`, `booking_date`, `amount`, `dc_indicator`, `bank_entry_id`. |
| 6 Join / match | IN-09 `statement_id` = IN-08 `statement_id` (validate.py:436–438). |
| 7 Grouping | Per statement (every account, including own funds). |
| 8 Calculation | Lines 551–572: `opening + Σ signed entries == closing`; `len(entries) == entry_count`; each entry's account, currency and `booking_date` equal the statement's. |
| 9 Tolerance | None. |
| 10 Dates | Plain dates. |
| 11 Missing evidence | An excluded IN-09 row for the account-day → INSUF. |
| 12 Output | `computed` "opening+total=sum"; `reported` closing. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `DQ23-STATEMENT|sid` High. |
| 15 Tests | `test_baseline.py::CleanBaseline::test_essential_checks_ran_on_every_scope`; `test_hardening.py::MalformedRows::test_bad_debit_credit_code`. |
| 16 Limitations | Statement balances are taken from the bank. Only their internal arithmetic is tested. |
| **Why** | If a bank statement does not add up, none of its figures can be relied on. |

### DQ22-CONTINUITY — Cross-day continuity

| | |
|---|---|
| 2 Purpose | Prove bank statements chain day to day, and that the first one starts where the cash book starts. |
| 3 Question | Does each day's opening equal the previous day's closing, with no missing days? |
| 4 Inputs | IN-01, IN-08; IN-10 (opening row). |
| 5 Columns | IN-08 balances, `statement_date`; IN-10 `entry_type`, `amount`, `dc_indicator`, `account_id`. |
| 6 Join / match | Statements per account sorted by date (validate.py:576–580). First statement versus IN-10 OPENING_BALANCE of the same account. |
| 7 Grouping | Per account: one "opening" result plus one per subsequent statement. |
| 8 Calculation | Lines 573–607: (a) first opening = cash-book opening (signed). (b) For each consecutive pair, if any reconciliation day lies strictly between them → gap; else `prev closing == cur opening`. |
| 9 Tolerance | None. |
| 10 Dates | Plain dates. |
| 11 Missing evidence | Gap → INSUF "statement gap: no statement for …", root `evidence_gap(acct, first gap day)` or `MISSING_BANK_EVIDENCE|acct|day`. IN-10 unavailable → opening INSUF. A safeguarding account with no usable opening row → FAIL (or INSUF if a tainted row may be it). |
| 12 Output | Scope `"{acct} opening"` or the current `statement_id`. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | Gaps join `MISSING_BANK_EVIDENCE`; breaks → `DQ22-CONTINUITY|…` High. |
| 15 Tests | `test_baseline.py::Regressions::test_topup_with_missing_statement_is_insufficient`. |
| 16 Limitations | Own-funds accounts have no independent opening source, so no opening result is emitted for them (line 595). The cross-month bank chain is checked by continuity (Part H), not here. |
| **Why** | A gap or break in the chain of statements means a day's movements are unaccounted for. |

### BC-VS-EOD — External existence and statement agreement

| | |
|---|---|
| 2 Purpose | Prove the 17:00 confirmation is consistent with the day's statement. |
| 3 Question | Does the 17:00 balance equal the morning opening plus entries booked by 17:00? |
| 4 Inputs | IN-07, IN-08, IN-09. |
| 5 Columns | IN-07 `statement_id`, `account_id`, `as_at_ts`, `balance_amount`, `balance_dc_indicator`; IN-08 opening; IN-09 `booking_ts`, `amount`, `dc_indicator`. |
| 6 Join / match | IN-07 (`account_id`, as-at date) → IN-08 (`account_id`, `statement_date`) (`eod_by`, line 433); entries by that statement's ID. |
| 7 Grouping | Per IN-07 row. |
| 8 Calculation | Lines 608–624: `expected = signed(opening) + Σ signed(entries with booking_ts ≤ as_at_ts)`; `got = signed(balance)`. |
| 9 Tolerance | None. |
| 10 Dates | As-at date from the timestamp as written; booking instants compared. |
| 11 Missing evidence | No EOD statement for that day, or an invalid row → INSUF. |
| 12 Output | `computed` expected; `reported` got; note "opening + N entries booked by 17:00". |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `BC-VS-EOD|sid` High, or the shared missing-evidence root. |
| 15 Tests | All-check tests only. |
| 16 Limitations | It iterates over existing IN-07 rows only, so a missing confirmation produces no BC-VS-EOD row (that gap is C14/C07). |
| **Why** | It proves the confirmation and the statement tell the same story. |

### CASH-BANK-LINK — Resource / External existence and statement agreement

| | |
|---|---|
| 2 Purpose | Prove each cash-book posting corresponds to one real bank entry. |
| 3 Question | For every ledger entry, is there exactly one bank entry with the same reference, amount and currency? |
| 4 Inputs | IN-02, IN-07, IN-08, IN-09, IN-10. |
| 5 Columns | IN-10 `ledger_entry_id`, `account_id`, `payment_reference`, `amount`, `dc_indicator`, `currency`, `posted_ts`, `entry_type`; IN-09 `account_id`, `bank_reference`, `end_to_end_ref`, `amount`, `dc_indicator`, `currency`. |
| 6 Join / match | **By reference only**: key (`account_id`, ref) where ref ∈ {`bank_reference`, `end_to_end_ref`} of safeguarding-account bank entries (lines 628–632). Amounts are compared only after the link is made. |
| 7 Grouping | Per cash-book entry (OPENING_BALANCE excluded). |
| 8 Calculation | Lines 637–658: 1 match → PASS iff `signed(bank) == signed(cashbook)` and the currencies are equal; 0 → unmatched; >1 → FAIL. |
| 9 Tolerance | None. |
| 10 Dates | Posting date from `posted_ts` as written (line 649), used only to find an evidence gap. |
| 11 Missing evidence | No match and that day's bank evidence missing or tainted → INSUF (root `MISSING_BANK_EVIDENCE…` or the taint root). |
| 12 Output | Scope = `ledger_entry_id`; `computed` cash-book signed; `reported` bank signed. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | No match → `UNMATCHED_CASHBOOK_ENTRY|id` High; amount mismatch or multiple → `CASH-BANK-LINK|id` High. L1 REFERENCE links via the entry's reference. |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_cashbook_change_breaks_resource_and_ledger`; `test_demo_history.py::ScenarioBehaviour::test_inconsistent_reference_june_is_never_matched_on_amount`; `test_hardening.py::MalformedRows::test_amount_with_thousands_separator_is_rejected_not_converted`. |
| 16 Limitations | It never matches on amount alone, by design. A posting with a mistyped reference is unmatched even if the amount is identical. |
| **Why** | Every pound in the ledger should be traceable to the bank. A reference is the evidence; an equal amount is coincidence. |

### BANK-CASH-LINK — Resource / External existence and statement agreement

| | |
|---|---|
| 2 Purpose | The reverse of CASH-BANK-LINK: every safeguarding bank entry has a ledger counterpart. |
| 3 Question | Did anything hit the safeguarding account that the firm did not record? |
| 4 Inputs | IN-02, IN-09, IN-10. |
| 5 Columns | As CASH-BANK-LINK. |
| 6 Join / match | Any of the entry's references present in the cash book on the same account (lines 659–662). |
| 7 Grouping | Per safeguarding bank entry. |
| 8 Calculation | Existence of a counterpart only (no amount comparison here). |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | An excluded cash-book row may be its counterpart → INSUF. |
| 12 Output | Emitted **only for problems**. The pack lists it as NO_FINDINGS when it ran clean (`pack/config.py` `FAILURE_ONLY_CHECKS`, lines 26–28; assemble.py:169–175). |
| 13 Outcomes | FAIL / INSUF only. |
| 14 Exceptions | `UNMATCHED_BANK_ENTRY|bank_entry_id` High (shared with C11-BANK-ENTRY, so one exception). |
| 15 Tests | `test_audit_pack.py::Scenario1Acceptance::test_ac3_ac4_all_results_and_outcomes` (NO_FINDINGS). The failure path is covered by the S05 golden. |
| 16 Limitations | Own-funds entries are out of scope. |
| **Why** | Money leaving or entering the safeguarding account without a ledger record is exactly what a reconciliation must surface. |

---

# Part E — Settlement, transactions, funding and receipts

### C11-BATCH-ARITH — Settlement

| | |
|---|---|
| 2 Purpose | Prove each settlement batch adds up from its lines, and the lines tie to transactions. |
| 3 Question | Do gross, fees, refunds and net in the batch header equal the sum of its lines, and is every line a real transaction of that batch? |
| 4 Inputs | IN-11, IN-12, IN-13. |
| 5 Columns | IN-12 `batch_id`, `currency`, `direction`, `gross_amount`, `total_fees`, `total_adjustments`, `net_amount_reported`; IN-13 `batch_id`, `line_id`, `line_type`, `txn_id`, `amount`, `dc_indicator`, `currency`; IN-11 `txn_id`, `settlement_batch_id`, `amount`. |
| 6 Join / match | IN-13 `batch_id` = IN-12 `batch_id`; IN-13 `txn_id` = IN-11 `txn_id`. |
| 7 Grouping | Per batch. |
| 8 Calculation | Lines 818–846: Σ TXN lines = `gross_amount`; Σ FEE = `total_fees`; Σ REFUND = `total_adjustments`; Σ signed lines (C +, D −) = `batch_net_signed`; each line's currency = batch currency; each TXN/REFUND line's transaction exists, has `settlement_batch_id` = this batch and amount text equal. |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | An excluded IN-13 or IN-11 row for the batch → INSUF. |
| 12 Output | `computed` signed line sum; `reported` signed net; note lists issues. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `C11-BATCH-ARITH|batch` High. CAND (unverified) to a CBAL-ROLLFWD with an equal amount on the same date (1442–1471). |
| 15 Tests | `test_baseline.py::ChecksCanFail::test_fee_lines_required_for_gross_to_net`; `test_scenario_datasets.py::ScenarioDatasets::test_supported_fee_3a_in_baseline`; `test_hardening.py::MissingEvidence::test_missing_calendar`; `test_e1_e2.py::E2InvestigationGroups::test_e2_4_missing_transaction_has_no_confirmed_group`. |
| 16 Limitations | It does not check that every transaction in the batch appears as a line (that is C11-TXN-LINE). |
| **Why** | Scheme and acquirer reports must reconcile to their own detail before they are matched to the bank. |

### C11-BATCH-BANK — Settlement

| | |
|---|---|
| 2 Purpose | Match each batch to the bank entry that settled it. |
| 3 Question | Did the bank receive or pay exactly the batch net, under the batch reference? |
| 4 Inputs | IN-02, IN-07, IN-08, IN-09, IN-12. |
| 5 Columns | IN-12 `account_id`, `expected_bank_reference`, `settlement_date`, `currency`; IN-09 `account_id`, `bank_reference`, `amount`, `dc_indicator`, `currency`, `booking_date`, `bank_entry_id`. |
| 6 Join / match | (`account_id`, `expected_bank_reference`) = (`account_id`, **`bank_reference`**) (lines 814–816, 849). `end_to_end_ref` is not used. Reference first, then amount. |
| 7 Grouping | Per batch. |
| 8 Calculation | Lines 847–875: 1 hit → PASS iff signed bank amount = signed net and currency equal; booking lag counted in business days (856–858). |
| 9 Tolerance | None on amount. Lag is informational only (`within_one_business_day_allowance`, `timing_status: INFORMATIONAL`). |
| 10 Dates | `settlement_date` versus `booking_date` (plain dates). |
| 11 Missing evidence | No hit and the settlement day's evidence is missing or tainted → INSUF. |
| 12 Output | `computed` signed net; `reported` signed bank; `structured` {`bank_entry_id`, `settlement_date`, `booking_date`, `booking_lag_business_days`, `within_one_business_day_allowance`, `timing_status`}. |
| 13 Outcomes | PASS / FAIL (no hit with evidence present, amount or currency mismatch, multiple hits) / INSUF. |
| 14 Exceptions | `C11-BATCH-BANK|batch` High (no root is set on a no-hit FAIL, so the default applies). L1 REFERENCE via the batch reference. |
| 15 Tests | `test_audit_pack.py::D3StructuredFields::test_booking_lag_structured`; `test_e1_e2.py::E1TimingEvidence::test_e1_10_batch_lag_is_informational`; `test_baseline.py::ChecksCanFail::test_equal_amount_is_not_a_link`; `test_demo_history.py::ScenarioBehaviour::test_inconsistent_reference_june_is_never_matched_on_amount`. |
| 16 Limitations | A lag beyond one business day is still PASS here (reported in the note). The C08 timing logic is what judges the day-end effect. |
| **Why** | Card settlements are the largest daily flows. Each must be traceable to one bank movement of the right amount. |

### C11-TXN-LINE — Settlement

| | |
|---|---|
| 2 Purpose | Prove every card transaction is settled in exactly one line of its batch. |
| 3 Question | Is any card load, spend or refund missing from, or duplicated in, settlement? |
| 4 Inputs | IN-11, IN-12, IN-13. |
| 5 Columns | IN-11 `txn_id`, `txn_type`, `settlement_batch_id`; IN-13 `batch_id`, `txn_id`. |
| 6 Join / match | Transaction → lines of `settlement_batch_id` with the same `txn_id`. |
| 7 Grouping | Per LOAD_CARD / SPEND / REFUND transaction. |
| 8 Calculation | Lines 876–892: FAIL if the batch is unknown or the count of matching lines ≠ 1. |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | Batch or line possibly in an excluded row → INSUF. |
| 12 Output | Per-transaction rows only on problems; otherwise one summary PASS "all card transactions" with the count. |
| 13 Outcomes | PASS (summary) / FAIL / INSUF. |
| 14 Exceptions | `C11-TXN-LINE|txn` High. |
| 15 Tests | All-check tests only. |
| 16 Limitations | Amounts are not compared here (that is C11-BATCH-ARITH). |
| **Why** | A transaction that never settles means the client balance and the bank will drift apart. |

### C11-BANK-ENTRY — Settlement (unmatched bank entries)

| | |
|---|---|
| 2 Purpose | Every safeguarding bank entry must be explained by a known source. |
| 3 Question | Is there any bank movement on a safeguarding account that no batch, transaction, receipt or top-up explains? |
| 4 Inputs | IN-02, IN-04, IN-09, IN-10, IN-11, IN-12. |
| 5 Columns | IN-09 `account_id`, `bank_reference`, `end_to_end_ref`, `bank_entry_id`; IN-12 `account_id`, `expected_bank_reference`; IN-11 `payment_reference`; IN-04 `bank_reference`; IN-10 `entry_type`, `payment_reference`. |
| 6 Join / match | Explained if (account, `bank_reference`) is a batch reference, or `end_to_end_ref` ∈ transaction payment references, or `end_to_end_ref` ∈ register references, or `bank_reference` ∈ cash-book OWN_FUNDS_TOPUP references (lines 1017–1026). |
| 7 Grouping | Per safeguarding bank entry. |
| 8 Calculation | Reference existence only. No amount comparison. |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | An excluded IN-12, IN-11, IN-04 or IN-10 row carrying one of its references → INSUF. |
| 12 Output | Per unexplained entry; or one summary PASS "N of N explained". |
| 13 Outcomes | PASS (summary) / FAIL / INSUF. |
| 14 Exceptions | `UNMATCHED_BANK_ENTRY|id` High, shared with BANK-CASH-LINK; amount = signed bank amount, date = booking date (1270–1273). |
| 15 Tests | `test_baseline.py::Regressions::test_unmatched_bank_entry_reported_once_per_check`; `test_period_and_headers.py::ReportingPeriod::test_3_single_stray_august_row_is_excluded_and_reported`. |
| 16 Limitations | It does not test that the explaining record has the same amount (other checks do). |
| **Why** | An unexplained debit is the first thing an analyst should look at when the bank is short (S05). |

### FUND-TOPUP — Internal difference handling

| | |
|---|---|
| 2 Purpose | Confirm fees deducted from settlements are replaced from own funds on the same day. |
| 3 Question | For each batch with fees, did own funds top up the safeguarding account by exactly the fee, recorded in the cash book? |
| 4 Inputs | IN-02, IN-07, IN-08, IN-09, IN-10, IN-12. |
| 5 Columns | IN-12 `batch_id`, `total_fees`, `currency`, `settlement_date`, `account_id`; IN-09 `bank_reference`, `account_id`, `dc_indicator`, `amount`, `booking_date`; IN-10 `entry_type`, `payment_reference`, `amount`; IN-02 `account_class`, `currency`. |
| 6 Join / match | Reference `TOPUP-{CCY}-{YYYYMMDD}` built from the batch (lines 906–907); safeguarding credit on the batch account (C); own-funds debit on any OWN_FUNDS account (D); cash-book OWN_FUNDS_TOPUP with that reference. |
| 7 Grouping | Per batch with `total_fees` > 0. |
| 8 Calculation | Lines 924–926: exactly one safeguarding credit, exactly one own-funds debit, a cash-book entry; all three amounts = fees; safeguarding `booking_date` = `settlement_date`. |
| 9 Tolerance | None; same-day rule hardcoded. |
| 10 Dates | Plain dates. |
| 11 Missing evidence | No safeguarding (or own-funds) entry and that account's evidence for the settlement date is missing → INSUF; cash-book entry absent but possibly excluded → INSUF. |
| 12 Output | `computed` fees; note. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `FUND-TOPUP|batch` High, or the shared missing-evidence root. |
| 15 Tests | `test_baseline.py::Regressions::test_topup_with_missing_statement_is_insufficient`; `test_scenario_datasets.py::ScenarioDatasets::test_supported_fee_3a_in_baseline`. |
| 16 Limitations | The own-funds debit's currency and date are not checked. The cash-book lookup is a dict keyed by reference, so duplicates are not detected. The reference format is a synthetic convention. |
| **Why** | Fees netted from a settlement leave the safeguarding account short unless the firm replaces them from its own money. |

### RC4-DIRECT — Receipts mapping

| | |
|---|---|
| 2 Purpose | Match each bank load and redemption to its bank movement 1:1. |
| 3 Question | Did each client bank transfer in, or payout, actually move through the safeguarding account? |
| 4 Inputs | IN-02, IN-04, IN-07, IN-08, IN-09, IN-11. |
| 5 Columns | IN-11 `txn_id`, `txn_type`, `payment_reference`, `amount`, `currency`, `executed_ts`; IN-09 `end_to_end_ref`, `account_id`, `amount`, `currency`, `dc_indicator`; IN-04 `bank_reference`, `receipt_date`. |
| 6 Join / match | IN-11 `payment_reference` = IN-09 `end_to_end_ref` on safeguarding accounts (lines 933–936, 943). |
| 7 Grouping | Per LOAD_BANK or REDEMPTION transaction. |
| 8 Calculation | Lines 939–969: 1 hit → PASS iff amount text equal, currency equal and `dc_indicator` = C (LOAD_BANK) or D (REDEMPTION); >1 → FAIL; 0 and the reference is a pre-period register receipt → NA (convention P1); 0 otherwise → FAIL, or INSUF if evidence is missing for the execution date or the receipt date. |
| 9 Tolerance | None. |
| 10 Dates | Execution date from `executed_ts` as written. |
| 11 Missing evidence | As above. |
| 12 Output | `computed` transaction amount; `reported` bank amount. |
| 13 Outcomes | PASS / FAIL / INSUF / NA. |
| 14 Exceptions | `RC4-DIRECT|txn` High, or the shared missing-evidence root. |
| 15 Tests | `test_baseline.py::Regressions::test_missing_bank_entry_with_statement_present_is_fail`; `test_baseline.py::Regressions::test_not_applicable_only_where_documented`. |
| 16 Limitations | It does not check the booking date against the execution date. |
| **Why** | A load credited to a client without the money arriving would inflate the requirement with no matching resource. |

### C09-ALLOCATION — Receipts mapping

| | |
|---|---|
| 2 Purpose | Confirm every unallocated receipt is real and allocated on time. |
| 3 Question | Did each unidentified or unallocated receipt arrive at the bank, and was it allocated to a client by the next business day? |
| 4 Inputs | IN-02, IN-04, IN-09, IN-11. |
| 5 Columns | IN-04 `receipt_id`, `bank_reference`, `receipt_date`, `amount`, `currency`, `allocated_ts`, `allocated_date`, `client_id`; IN-09 `end_to_end_ref`, `amount`, `currency`; IN-11 `txn_type`, `payment_reference`, `executed_ts`, `client_id`. |
| 6 Join / match | IN-04 `bank_reference` = IN-09 `end_to_end_ref` (safeguarding); allocation transaction = LOAD_BANK with the same `payment_reference`. |
| 7 Grouping | Per receipt. |
| 8 Calculation | Lines 970–1011. (a) The receipt must match exactly one bank credit with equal amount text and currency, unless received before the period start (P1 note). (b) If allocated: the allocation date must be ≤ next business day after `receipt_date`; if allocated inside the period, exactly one LOAD_BANK with `executed_ts` = `allocated_ts` and the same client is required. (c) If open: FAIL if the due date ≤ period end, else PASS "open at the period end; allocation due by …". |
| 9 Tolerance | Next business day (A.6). |
| 10 Dates | Deadline uses the allocation date in its stated offset; "after period end" uses London. |
| 11 Missing evidence | Issues plus missing or tainted bank or transaction evidence → INSUF. |
| 12 Output | Note-only rows (no computed figures). |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `C09-ALLOCATION|receipt` High. |
| 15 Tests | `test_period_decisions.py::A1UnallocatedReceipts::test_september_receipt_allocated_1_october_counts_as_open_on_30_september`, `::test_allocation_transaction_in_october_is_reported_but_not_required`, `::test_late_allocation_after_period_end_fails_timeliness`, `::test_receipt_still_open_at_period_end_within_deadline`, `::test_receipt_received_in_october_is_out_of_period_and_does_not_affect_september`, `::test_overdue_receipt_never_allocated_fails`. |
| 16 Limitations | The `classification` (UNALLOCATED / UNIDENTIFIED) and `identified_date` are not used. |
| **Why** | Money received but not yet credited to a client must still be safeguarded and allocated promptly. |

### C12-REFUND — Reversal validity

| | |
|---|---|
| 2 Purpose | Confirm refunds reverse a real original and never exceed it. |
| 3 Question | Does each refund point to a genuine original for the same client and currency, and do total refunds stay within the original amount? |
| 4 Inputs | IN-11. |
| 5 Columns | `txn_id`, `txn_type`, `original_txn_id`, `currency`, `client_id`, `amount`. |
| 6 Join / match | REFUND `original_txn_id` = original `txn_id`. |
| 7 Grouping | Per refund; running total per original. |
| 8 Calculation | Lines 1041–1054: original exists with the same currency and client; cumulative refunds so far (file order) ≤ original amount. |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | Original in an excluded row → INSUF. |
| 12 Output | `computed` running total; `reported` original amount. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `C12-REFUND|txn` High. |
| 15 Tests | `test_hardening.py::MissingEvidence::test_missing_account_inventory`. No dedicated failure-path test was found by grep. |
| 16 Limitations | It does not see a refund double-posted only in the **client ledger** (SC5C, J.4: C12 PASS, caught by CBAL-ROLLFWD and C06). |
| **Why** | An invalid refund credits a client with money that was never owed. |

---

# Part F — Currency, designation and checklist

### C13-CURRENCY — Currency ownership

| | |
|---|---|
| 2 Purpose | Prove no record crosses currencies. |
| 3 Question | Is every record in the currency of its account or batch? |
| 4 Inputs | IN-02 (gate); IN-06, 07, 08, 09, 10, 12 (account), IN-13, IN-11 (batch). |
| 5 Columns | `currency`, `account_id` (IN-06/07/08/09/10/12); `batch_id` (IN-13); `settlement_batch_id` (IN-11); IN-02 `currency`. |
| 6 Join / match | Row `account_id` → IN-02 currency; row batch → IN-12 currency. |
| 7 Grouping | One result for all records. |
| 8 Calculation | Lines 1088–1112: count mismatches. |
| 9 Tolerance | None. |
| 10 Dates | n/a. |
| 11 Missing evidence | Records whose batch is in an excluded IN-12 row → INSUF "not comparable" (only if there are no mismatches). |
| 12 Output | `computed` "N mismatches"; evidence cites up to 10. |
| 13 Outcomes | PASS / FAIL / INSUF. |
| 14 Exceptions | `C13-CURRENCY|all records` High. |
| 15 Tests | All-check tests only. |
| 16 Limitations | IN-03, IN-04 and IN-05 are not in its list (they carry currency but no account). |
| **Why** | GBP and EUR must never be netted against each other. |

### C10-DESIGNATION — Designation

| | |
|---|---|
| 2 Purpose | Confirm each safeguarding account is acknowledged by the bank as a safeguarding account. |
| 3 Question | Does the bank's letter match the account we hold and name it as safeguarding? |
| 4 Inputs | IN-02 (gate); IN-15 / IN-16 (`schema.LETTER_SLOTS`, schema.py:277). |
| 5 Columns | IN-02 `acknowledgement_letter_ref`, `account_number_masked`, `currency`, `designation_name`; letter labels "Letter reference", "Account number", "Currency", "Account name", "Letter date". |
| 6 Join / match | Safeguarding account → letter slot → parsed key details. |
| 7 Grouping | Per safeguarding account. |
| 8 Calculation | Lines 1126–1136: all four fields equal and `designation_name` contains "Safeguarding"; letter date ≤ period end. |
| 9 Tolerance | Exact text. |
| 10 Dates | Letter date versus period end. |
| 11 Missing evidence | Letter missing or unusable → **FAIL** (not INSUF), root = the file's root (for example `MISSING_FILE|IN-16`), so it joins the file exception. |
| 12 Output | `computed` letter reference; `reported` inventory reference. |
| 13 Outcomes | PASS / FAIL / INSUF (gate on IN-02). |
| 14 Exceptions | Joins the file root, or `C10-DESIGNATION|acct` High. |
| 15 Tests | All-check tests only. |
| 16 Limitations | Fixed synthetic layout; no reviewer confirmation (note at line 1130). |
| **Why** | Funds in an account not acknowledged as safeguarding may not be protected on insolvency. |

### C16-GOVERNANCE — Checklist

| | |
|---|---|
| 2 Purpose | Confirm an accountable person is named for the period. |
| 3 Question | Was someone responsible for safeguarding during this month? |
| 4 Inputs | IN-18 (optional; no gate). |
| 5 Columns | Labels "Accountable person", "Allocated from". |
| 6–7 | n/a; scope "period". |
| 8 Calculation | Lines 1144–1151: FAIL if allocated after the period end; else PASS iff a person is named. |
| 9 Tolerance | None. |
| 10 Dates | "Allocated from" versus period end. |
| 11 Missing evidence | Absent or unusable → NOT_APPLICABLE. |
| 12–13 | One row; PASS / FAIL / NA. |
| 14 Exceptions | `C16-GOVERNANCE|period` High. |
| 15 Tests | `test_baseline.py::Regressions::test_not_applicable_only_where_documented`. |
| 16 Limitations | Optional, so its absence never makes evidence incomplete. |
| **Why** | Governance evidence supports, but does not change, the reconciliation. |

### C16-RETURN — Checklist

| | |
|---|---|
| 2 Purpose | Confirm the previous month's safeguarding return was filed on time. |
| 3 Question | Was last month's return submitted by its due date? |
| 4 Inputs | IN-19 (optional; no gate). |
| 5 Columns | Labels "Period", "Due date", "Submitted at". |
| 6–7 | Receipt "Period" must equal the previous month token. |
| 8 Calculation | Lines 1155–1168: `due = business_day_after(previous_end, 15)`; PASS iff right period and submitted ≤ due and stated "Due date" = due. |
| 9 Tolerance | 15 business days (hardcoded). |
| 10 Dates | Submission date from the timestamp as written. |
| 11 Missing evidence | Absent → NA; unreadable timestamp → FAIL. |
| 12–13 | One row; PASS / FAIL / NA. |
| 14 Exceptions | `C16-RETURN|…` High. |
| 15 Tests | `test_period_config.py::DocumentApplicability::test_return_receipt_must_be_for_the_previous_period`; `test_baseline.py::Regressions::test_not_applicable_only_where_documented`. |
| 16 Limitations | Optional evidence. |
| **Why** | Late returns are a regulatory breach in themselves, separate from the reconciliation figures. |

---

# Part G — Evidence gate, exceptions, correlation and case status

## G.1 The evidence gate and INSUFFICIENT_EVIDENCE

INSUFFICIENT_EVIDENCE means "could not be assessed", not "passed" or "failed". It arises at three levels:

1. **Whole check (the gate).** `Validator.gate` (validate.py:186–195) looks up the check's dependency list in `schema.DEPENDS` (schema.py:282–312). If any listed file is MISSING, EMPTY, UNUSABLE, AMBIGUOUS or WRONG_PERIOD, the check does not run. It emits one INSUF result with scope "all scopes", rooted at the first unavailable file. Checks that do not depend on that file keep running. C16 has no DEPENDS entry and is never gated.
2. **One scope, because of an excluded row.** `tainted` (197–221) returns a root cause when an excluded (invalid or out-of-period) row *could* belong to the scope: the same account, currency, date, batch, client, reference or key. Any field that was unreadable on the excluded row matches everything (`structure.taint_scope`, structure.py:122–146).
3. **One scope, because a record is absent.** Examples: no bank confirmation for a day (C07, C08), no statement for a day (`evidence_gap`), no snapshots (C04), no cash-book opening (C05, RC2).

In every case the result carries a `root_cause` string, and that string determines the exception it belongs to.

## G.2 Exceptions — `_group_exceptions` (validate.py:1191–1303)

**One exception per root cause (decision D4).** Every FAIL and INSUF result belongs to exactly one exception:

1. Bank-ledger differences are grouped into `BANK_LEDGER_DIFFERENCE|acct|first_date|amount` (Part D), and DISC-LOG is evaluated (1206–1236).
2. Each C06 FAIL without a root becomes `INTERNAL_DIFFERENCE|date/ccy` (1237–1239). There is one per day; days are not merged.
3. Anything else without a root becomes `check_id|scope`, so nothing is silently absorbed (1240–1242).
4. Results are grouped by `root_cause` (1243–1246).

**Severity** (`SEVERITY`, 1174–1177): **Critical** for MISSING_BANK_EVIDENCE, BANK_LEDGER_DIFFERENCE, INTERNAL_DIFFERENCE, MISSING_RECON, MISSING_EXT_RECON, MISSING_FILE, EMPTY_FILE, INVALID_FILE, AMBIGUOUS_FILE and WRONG_PERIOD. **High** for INVALID_ROWS, OUT_OF_PERIOD_ROWS and every other kind (for example UNMATCHED_BANK_ENTRY, MISSING_SNAPSHOT and every `check_id|scope` root).

**Fields** (1279–1286): `severity, status, category` (`CATEGORY`, 1178–1185, else the check ID), `root_cause, account_id, currency, first_date, last_date, amount, affected_results, affected, flags, related_records, evidence, cause_category` (always blank), plus `evidence_status, evidence_status_detail, review_status, investigation_group_id`.

**IDs and status** (1287–1302): exceptions are sorted by severity (Critical first), then first date, then root cause, and numbered `EXC-{scenario}-{NN}`. The scenario comes from `scenario.json`, or is `CASE` (`_scenario_id`, 1474–1477). Every exception is created with `status = "OPEN"` and `review_status = "AWAITING_HUMAN_REVIEW"`. No engine code sets any other status. Timing evidence changes only the category wording (1294–1297).

## G.3 Correlation — `_correlate_exceptions` (validate.py:1306–1471)

This adds `investigation_group_id` (`GRP-{scenario}-{NN}`) above the exceptions, which are left unchanged. It runs only when there are at least 2 exceptions (1320–1321). Links are evidence-based only:

- **L1 REFERENCE** (1367–1373): two exceptions involve records carrying the same (account, reference). The keys come from batch, cash-book and bank-entry results.
- **L2 PERSISTENCE** (1374–1382): internal-difference exceptions on consecutive reconciliation days, with the same currency and the same C06 value.
- **L3 LINEAGE** (1383–1412): a bank entry of another exception booked on the account by 17:00 on the day a bank-ledger difference begins; a failing roll-forward snapshot that is an input to the same-day requirement or internal difference; a requirement failure consumed by the same-scope internal difference.

Linked exceptions form groups through connected components (1413–1441). Groups carry `status OPEN`, `review_status AWAITING_HUMAN_REVIEW`, `cause ""` and `correlation_version "deterministic-v1"`. Coincidences of date and amount alone are recorded separately as `CAND-…` "UNVERIFIED — NOT EVIDENCE-BACKED" candidates (1442–1471). Groups never set a cause, change a status, merge exceptions or close anything (docstring, 1317–1318). Tests: `test_e1_e2.py::E2InvestigationGroups` (e2_1 to e2_12) and `test_e1_e2.py::E2Negative`.

## G.4 Case status and evidence completeness

`case_status` (validate.py:1492–1501):

| Status | Condition |
|---|---|
| **EVIDENCE_INCOMPLETE** | any **required** file is unavailable, **or** any result is INSUFFICIENT_EVIDENCE |
| **EXCEPTIONS_OPEN** | evidence complete and at least one FAIL |
| **CLEAN** | evidence complete and every result is PASS or NOT_APPLICABLE |

EVIDENCE_INCOMPLETE takes precedence, so a case can contain FAILs and still be EVIDENCE_INCOMPLETE. The pack records the same rule as `executive_summary.evidence_completeness` = INCOMPLETE / COMPLETE (`pack/assemble.py`:288–291), next to `control_outcomes.summary` (292–293):

- FAILURES_PRESENT if any FAIL;
- otherwise NOT_FULLY_ASSESSED if any INSUF;
- otherwise ALL_PASSED_OR_NOT_APPLICABLE.

Each INSUF root cause becomes a `MISS-NN` item in `missing_evidence_register`, with the value shown as "not available" (assemble.py:271–284). A missing optional file (IN-18, IN-19) is listed under `optional_not_provided` and does not make evidence incomplete. Tests: `test_hardening.py::GoldenRegression::test_case_status`, `test_scenario_datasets.py::ScenarioDatasets::test_case_status`, `test_hardening.py::CasePreparation::test_validator_runs_without_any_manifest`.

---

# Part H — Month-boundary continuity (`uc042lib/continuity.py`)

**What it is.** A read-only comparison of the previous period's closing positions with the current period's opening positions. Each view is compared only with itself (docstring lines 1–23):

| View | Previous closing | Current opening | Function |
|---|---|---|---|
| BANK | last IN-08 `closing_balance` per account | first IN-08 `opening_balance` | `bank`, lines 64–88 |
| CASH_BOOK | `prev.ledger_at(acct, opening_point)`, i.e. all previous entries to the previous month-end 17:00 | the single IN-10 OPENING_BALANCE row, which must be posted exactly at the opening point | `cash_book`, 91–112 |
| CLIENT | previous IN-03 snapshot at the month-end date | current IN-03 boundary snapshot | `clients`, 115–134 |
| UNALLOCATED | IN-04 receipts open at the month end in the previous register | the same test on the current register | `unallocated`, 137–158 |

Each item is MATCH, DIFFERENCE (with `difference = current − previous`, "not adjusted") or NOT_VERIFIABLE. Without a previous case, the whole report is one NOT_VERIFIABLE item and nothing is assumed (`compare`, 161–175). Each case is read through the engine's own `load()` and `setup()` (`_engine_view`, 36–41). No controls are run.

**It does not change results.** Four facts establish this:

1. Continuity is **not part of the pack** (no reference in `uc042lib/pack/` or `uc042lib/final_pack/`).
2. It is **not in the engine fingerprint** (`pack/config.py` `ENGINE_MODULES`, line 22).
3. The monthly service calls it only after the pack has been built, published and registered. It is evaluated when the run's result dict is built (`services/monthly.py` `_process`, line 814), after `_publish` (804) and `add_pack` (806).
4. The call is wrapped so that any error returns NOT_VERIFIABLE: "continuity is reported, never allowed to change or fail the run's engine result" (`_continuity`, 874–889).

The report is stored only in the run's `result` JSON (`audit.processing_runs.result`).

**Observed (synthetic).** `demo_history/verification/continuity.csv` holds 144 items, 18 per boundary, for January→February to August→September. All are MATCH. That file is produced by the separate, independent check in `tools/verify_demo_history.py` (`continuity`, lines 604–614), not by `uc042lib/continuity.py`.

**Tests:** `test_period_config.py::Continuity::test_previous_closing_against_next_opening`, `::test_without_a_previous_period_nothing_is_assumed`, `::test_periods_must_be_consecutive`; `test_demo_history.py::Continuity::test_engine_continuity_module_finds_no_difference`, `::test_a_carry_forward_break_is_reported_not_adjusted`; `test_api_monthly.py::Processing::test_the_selected_period_is_passed_to_preparation_and_generation`.

**Why this exists.** A month can reconcile perfectly in isolation and still start from the wrong place. Continuity shows whether this month's opening equals last month's closing, without ever "correcting" either.

---

# Part I — Pack integrity and determinism

- **Single engine run.** `pack/assemble.py` runs the validator once (`run_engine`, 61–64) and copies its outputs. Its docstring (lines 3–5) states that it "performs no financial calculation, never changes an outcome, status or wording".
- **`processing_run_id`** = `RUN-` + the first 16 hex characters of the SHA-256 of the canonical JSON of four things (`model.run_id`, model.py:82–84):
  - the sorted (file ID, actual input SHA-256) pairs;
  - the **engine fingerprint**, a hash of `schema.py`, `period.py`, `structure.py`, `money.py` and `validate.py` (`config.ENGINE_MODULES`);
  - the configuration fingerprint (model.py:75–79);
  - the pack-layer fingerprint, a hash of every `pack/*.py` (66–72).
- **`pack_content_sha256`** = SHA-256 of the canonical JSON (sorted keys, `indent=1`, UTF-8) of the whole pack, with `pack_id` and `pack_content_sha256` blanked (`model.content_hash`, model.py:42–47). It is computed after the hashes of the processing outputs are recorded (`finalise`, assemble.py:388–395).
- **Pack ID** = `PACK-{scenario}-{period}-{first 12 hex of the content hash}` (`model.pack_id`, model.py:50–51). For example, the February content hash `195df2e1f216149c…` gives `PACK-H202602-PER-2026-02-195df2e1f216`.
- **Determinism.** Nothing in `assemble` reads a clock or random source, and the engine's ordering is deterministic. So identical inputs, engine code and pack code produce the same pack content, the same hash and the same pack ID. A change to any input byte or engine module produces a new ID, so there is no silent change. *(Established from the code; reruns were not executed for this document **[NOT VERIFIED BY RERUN]**. Test: `test_e1_e2.py::E2InvestigationGroups::test_e2_11_deterministic`, `test_baseline.py::Determinism::test_two_runs_identical_and_match_committed_baseline`.)*
- **Verification on read.** The API loads packs through `uc042lib/final_pack/sources.load_pack` (services/packs.py:8, 56) and returns 409 PACK_VERIFICATION_FAILED if a pack does not verify. The AI layer uses `investigation/retrieval.load_pack`, which recomputes the content hash and refuses any pack whose hash or ID suffix does not verify (retrieval.py:58–62).

---

# Part J — Worked examples (all figures synthetic)

## J.1 February 2026 — EXC-H202602-01, missing bank evidence for SGA-EUR-01 on 16 Feb

Source: `demo_history/packs/PACK-H202602-PER-2026-02-195df2e1f216/pack.json` (read only).

**What is missing.** IN-01 line 17 marks 2026-02-16 as a reconciliation day, and IN-02 line 3 lists SGA-EUR-01 as a safeguarding account. For that account-day there is **no IN-07 confirmation and no IN-08 statement**. IN-07 has 39 rows and IN-08 has 79, against an expected 40 (20 days × 2 safeguarding accounts) and 80 (20 days × 4 accounts) (synthetic). Every file is present and structurally valid, so **no check is gated**. Only the scopes that need that day's bank evidence cannot be assessed.

**The 15 INSUFFICIENT_EVIDENCE results, all with root `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16`:**

| Result | Why it could not be assessed |
|---|---|
| C14-COVER IN-07 and IN-08 `2026-02-16/SGA-EUR-01` | Expected record absent. Absent evidence defaults to INSUF (`_cover`, 534–545). |
| DQ22-CONTINUITY `ST-SGA-EUR-01-20260217-EOD` | "statement gap: no statement for 2026-02-16", between IN-08 L39 (13 Feb) and L46 (17 Feb). |
| CASH-BANK-LINK `LE-EUR-0216-0001` … `0005` | Five cash-book entries (IN-10 L128–132) with no bank entry. Because `evidence_gap` reports the day as missing, the result is INSUF, not FAIL. |
| C07-BANK-EVIDENCE `2026-02-16/SGA-EUR-01` | IN-06 L23 cites `ST-SGA-EUR-01-20260216-1700`, which is not in IN-07. Reported bank balance **73199.44** (synthetic) is "unverified". Computed: blank. |
| C08-DIFFERENCE `2026-02-16/SGA-EUR-01` | The bank side is None, so no difference is computed. The firm's reported **0.00** is not accepted as the result. |
| C11-BATCH-BANK `AQ-EUR-20260216`, `SB-EUR-20260216` | The batch reference cannot be sought on a statement that was not provided (IN-12 L44 for AQ). |
| FUND-TOPUP `AQ-EUR-20260216` | Fees **6.79** (synthetic) need a safeguarding credit on SGA-EUR-01 that day. Statement not provided. |
| RC4-DIRECT `TX-0216-00014`, `TX-0216-00020` | No end-to-end match, and the day's bank evidence is missing (TX-0216-00014 is IN-11 L219). |

**What still passed for that scope.** This shows that missing is not zero, and that only the affected results are withheld:

- **RC2-LEDGER** 2026-02-16/SGA-EUR-01: computed 73199.44 from 57 cash-book entries to 17:00 = reported 73199.44, so PASS (synthetic). The ledger side exists but the bank side does not, so C08 shows "not available", not 0.00.
- **Internal reconciliation EUR, 16 Feb:** requirement 73199.44 (4 client balances, IN-03 L142–145, + 0 open receipts) = reported, so C04 PASS. Item A 73199.44, items B–D 0.00, resource 73199.44 = reported, so C05 PASS. Difference 0.00 = reported, so C06 NOT_APPLICABLE (all synthetic). The internal reconciliation uses the ledger, not the bank, so it can be assessed.
- **BC-VS-EOD** produced no 16 Feb result for SGA-EUR-01, because it iterates only over IN-07 rows that exist. The 16 Feb result for SGA-GBP-01 exists and passed.

**Grouping and status.** All 15 results share one root, so there is one exception: EXC-H202602-01, **Critical** ("Missing bank evidence"), status **OPEN**, review AWAITING_HUMAN_REVIEW, 15 affected results, no flags, no group, and one missing-evidence item MISS-01. The pack totals are 1,788 results: 1,690 PASS, 83 NOT_APPLICABLE, 15 INSUFFICIENT_EVIDENCE, 0 FAIL (synthetic). Case status is **EVIDENCE_INCOMPLETE**, with evidence completeness INCOMPLETE and control outcomes NOT_FULLY_ASSESSED. IN-18 and IN-19 were not provided and are optional, so both C16 results and both V00-FILE results are NOT_APPLICABLE. Policy: IN-17 v1.1, effective 2025-10-01 (HD-1).

## J.2 September 2026 scenario S05 — unexplained GBP difference −812.40

Source: `packs/PACK-S05-PER-2026-09-ddd0fdc8b731/pack.json` (dataset `scn_S05_unexplained_gbp_difference`). Mutation (`mutations.json`): a debit `BE-GBP-0917-X01` of 812.40 added to IN-09, with the 17 Sep statement closing and entry count adjusted. The cash book is unchanged.

**External reconciliation, SGA-GBP-01, 17 Sep 2026** (IN-06 L26, `ERL-SGA-GBP-01-20260917`). All figures synthetic:

| | Computed (engine) | Reported (firm, IN-06) | Result |
|---|---|---|---|
| Bank (IN-07 L26, 17:00) | 340672.06 | 340672.06 | C07 PASS |
| Ledger (IN-10, 73 entries to 17:00) | 341484.46 | 341484.46 | RC2 PASS |
| Difference = Bank − Ledger | 340672.06 − 341484.46 = **−812.40** | −812.40 | **C08 FAIL** |

The firm's reported figures agree with the recomputed ones, so the failure is **not** a reporting mismatch. It is the last row of the C08 outcome table: computed = reported ≠ 0. `timing_difference_claimed` = false. The timing assessment found no cross-day items (`explained_by_timing` 0.00, `residual_unexplained` −812.40), so the evidence status is NOT_EVIDENCED. On 16 Sep the difference was 0.00 (NOT_APPLICABLE).

**Grouping.** The same −812.40 appears on all 10 consecutive reconciliation days from 17 Sep to 30 Sep. On 30 Sep, for example, bank 395032.46 and ledger 395844.86 (123 entries) give −812.40 (synthetic). These form one root cause, `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-17|-812.40`. IN-14 has a header only, with no entry for any `ERL-SGA-GBP-01-202609xx`, so DISC-LOG is FAIL. **EXC-S05-01** is therefore Critical, with 11 affected results (10 C08 + 1 DISC-LOG). It carries the flags `OWN_FUNDS_REQUIRED` (the amount is negative) and `NO_INVESTIGATION_LOGGED`, and the related record `BE-GBP-0917-X01`.

**The related bank entry.** IN-09 L152, `BE-GBP-0917-X01`, is a debit of 812.40 booked 17 Sep 15:20 (+01:00), reference "SETTLE 0417". It has no cash-book counterpart (BANK-CASH-LINK FAIL) and no batch, transaction, top-up or register counterpart (C11-BANK-ENTRY FAIL). This is **EXC-S05-02**, severity High (UNMATCHED_BANK_ENTRY), amount −812.40. Correlation links the two exceptions in **GRP-S05-01** by **L3 LINEAGE**, because the entry falls inside the 17 Sep 17:00 balance where the difference begins. The group does not state that the entry *is* the cause.

**Internal side the same day:** GBP requirement 341484.46 (8 client balances) = Item A 341484.46, so C06 0.00 is NOT_APPLICABLE (synthetic). The internal reconciliation is ledger-based, so a debit that appears only at the bank is caught by the external reconciliation, not the internal one. The pack totals are 1,887 results: 1,796 PASS, 13 FAIL, 78 NOT_APPLICABLE (synthetic). Evidence is COMPLETE, so case status is **EXCEPTIONS_OPEN**.

## J.3 September 2026 scenario SC2 — settlement timing, evidenced but still open

Source: `packs/PACK-SC2-PER-2026-09-aaca8a8b7194/pack.json`. Mutation: the bank booked the 15 Sep scheme settlement `SB-GBP-20260915` (debit 2868.50) on 16 Sep 08:00 instead of 15 Sep. The ledger posted it on 15 Sep.

| 15 Sep, SGA-GBP-01 (synthetic) | Computed | Reported | Result |
|---|---|---|---|
| Bank (IN-07) | 331179.44 | 331179.44 | C07 PASS |
| Ledger (IN-10) | 328310.94 | 328310.94 | RC2 PASS |
| Difference | 331179.44 − 328310.94 = **2868.50** | 2868.50 | **C08 FAIL** |

Timing assessment: cash-book `LE-GBP-0915-0005` (posted by 17:00 on 15 Sep, −2868.50 in the ledger) links by reference `SB-GBP-20260915` to bank `BE-GBP-0916-T01` (booked 16 Sep, −2868.50). The effect on (bank − ledger) is −(−2868.50) = +2868.50. The bank booked it on 16 Sep, the next business day, and that day's evidence is usable, so the item is IN_WINDOW. `explained_by_timing` 2868.50, `residual_unexplained` 0.00, giving evidence status **TIMING_EVIDENCED**. On 16 Sep the difference is 0.00 (NA). C11-BATCH-BANK for `SB-GBP-20260915` is PASS, with the note "booked 2026-09-16, 1 business day(s) after the settlement date (within the one-business-day allowance; informational)". CASH-BANK-LINK `LE-GBP-0915-0005` is PASS (linked by reference; the amount is equal). DISC-LOG is PASS ("investigation logged").

Result: **EXC-SC2-01**, Critical, category "Bank-ledger difference (explained by timing evidence, awaiting human confirmation)", 1 affected result, no flags (the amount is positive), **status OPEN**. Totals: 1,798 PASS, 1 FAIL, 87 NA; EXCEPTIONS_OPEN (synthetic). This shows that timing evidence changes the *wording*, never the outcome or status.

## J.4 September 2026 scenario SC5C — refund double-posted in the client ledger

Source: `packs/PACK-SC5C-PER-2026-09-eaac7e6b1444/pack.json`. Mutation: client C0002's GBP snapshot is raised by 60.00 from 9 Sep onwards ("refund TX-0909-0R001 posted twice in the client ledger"). The firm's IN-05 `requirement_reported` is raised by the same amount, and `difference_reported` is set to −60.00.

| 9 Sep, GBP (synthetic) | Computed | Reported | Result |
|---|---|---|---|
| C04 requirement (8 client balances, includes inflated C0002) | 303756.81 | 303756.81 | PASS |
| C05 Item A / resource (cash book) | 303696.81 | 303696.81 | PASS |
| C06 difference = 303696.81 − 303756.81 | **−60.00** | −60.00 | **FAIL** "requires same-day resolution" |
| CBAL-ROLLFWD GBP/C0002 9 Sep: 8 Sep balance + 3 transactions | 43719.60 | snapshot 43779.60 | **FAIL** |
| C12-REFUND TX-0909-0R001: cumulative 60.00 ≤ original | 60.00 | 60.00 | PASS |

The same −60.00 internal difference recurs on every reconciliation day from 9 to 30 Sep (16 days). The roll-forward fails only on 9 Sep, because later snapshots carry the same inflation and therefore roll forward consistently. C12 passes because the transaction file itself holds one valid refund. The double-posting exists only in the client ledger.

Result: **17 exceptions**. EXC-SC5C-01 to EXC-SC5C-16 are each Critical `INTERNAL_DIFFERENCE|date/GBP` (one per day, not merged). EXC-SC5C-17 is High `CBAL-ROLLFWD|GBP/C0002 2026-09-09`. All 17 are joined in **GRP-SC5C-01** by **L2 PERSISTENCE** (same −60.00 on consecutive days) and **L3 LINEAGE** (the 9 Sep snapshot of C0002 fails the roll-forward and is an input to the 9 Sep requirement). Totals: 1,797 PASS, 17 FAIL, 72 NA; EXCEPTIONS_OPEN (synthetic).

## J.5 Scenario-to-exception map (September 2026 packs in `packs/`; synthetic)

| Scenario | Mutation (from `mutations.json` / scenario name) | Exceptions produced | Groups / candidates | Case status |
|---|---|---|---|---|
| S01 baseline | none | none | none | CLEAN |
| S02 | missing EUR statement (15 Sep) | EXC-S02-01 Critical `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-09-15` (13 results) | none | EVIDENCE_INCOMPLETE |
| S05 | unexplained debit 812.40 | J.2 | GRP (L3) | EXCEPTIONS_OPEN |
| SC2 | settlement booked next business day | J.3 | none | EXCEPTIONS_OPEN |
| SC3B | fee not itemised | EXC-SC3B-01 High `C11-BATCH-ARITH|AQ-GBP-20260908` | none | EXCEPTIONS_OPEN |
| SC3C | short settlement | EXC-SC3C-01 Critical `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-08|-4.50` (18 results); -02 High `C11-BATCH-BANK|AQ-GBP-20260908`; -03 High `CASH-BANK-LINK|LE-GBP-0908-0003` | 1 group (L1 + L3) | EXCEPTIONS_OPEN |
| SC5A | missing transaction | EXC-SC5A-01 High `C11-BATCH-ARITH|SB-GBP-20260915`; -02 High `CBAL-ROLLFWD|GBP/C0002 2026-09-15` | no group; 1 unverified candidate | EXCEPTIONS_OPEN |
| SC5C | refund double-posted | J.4 | GRP (L2 + L3) | EXCEPTIONS_OPEN |
| SC5D | closing snapshot mismatch | EXC-SC5D-01 Critical `INTERNAL_DIFFERENCE|2026-09-30/GBP`; -02 High `CBAL-ROLLFWD|GBP/C0003 2026-09-30`; -03 High `C04-REQUIREMENT|2026-09-30/GBP` | 1 group (L3) | EXCEPTIONS_OPEN |

---

# Part K — From the screen to the calculation

Each name below was checked in the code.

**1. Frontend action.** Two buttons start a calculation:

- **Start processing** (normal run). Upload batch detail, `frontend/src/pages/ArchivePages.tsx:60`: `data.processBatch(b.batch_id)`. The button is disabled while required evidence is missing. If the month already has a published final pack, it is replaced by a notice pointing to Reassess (lines 52–56). The upload wizard's "5. Start processing" (`UploadPage.tsx:196`) is a step in the wizard.
- **Reassess** (after publication). `frontend/src/components/report/Reassessment.tsx:63` opens a modal. "Start reassessment" (line 68) calls `data.reconcile(periodId, { purpose: "REASSESSMENT", reason })` (line 32) and needs a reason of at least 3 characters.

**2. API** (`frontend/src/api/endpoints.ts`, `V1 = "/api/v1"`, line 13):

- `processBatch` → **POST `/api/v1/uploads/{batch_id}/process`** (endpoints.ts:36) → `uc042app/api/routers/monthly.py:225–228` `process` → `MonthlyService.process`.
- `reconcile` → **POST `/api/v1/periods/{period_id}/reconciliation`** (endpoints.ts:42–43) → routers/monthly.py:231–239 `reconcile` → `MonthlyService.reconcile` (services/monthly.py:653–676). This checks the purpose, requires pending evidence and a reason for REASSESSMENT, picks the latest confirmed upload batch, then calls `process(…, purpose, reason)`.

**3. Backend: `MonthlyService.process`** (services/monthly.py:678–727):

- It refuses an unconfirmed batch (BATCH_NOT_CONFIRMED) or a run already in progress (RUN_IN_PROGRESS).
- It refuses INITIAL processing of a period with a published final pack (REASSESSMENT_REQUIRED). It refuses if required evidence is missing (INCOMPLETE).
- It creates a run record (`status QUEUED`) in **`audit.processing_runs`** (`repos.runs.create`; model `ProcessingRun`, `uc042app/db/models.py:63–76`), and submits a job.
- `_execute` (736–754) sets the status to RUNNING, calls `_process`, then records SUCCEEDED or FAILED with the result JSON.

**4. Backend: `_process`** (services/monthly.py:756–814):

1. Case folder: `key = sha256(period_id + "fid:sha" lines)[:16]` → `document_store/cases/SET-{key}`. Here `DocumentStore.cases_root` = store root / "cases" (`uc042app/ingest/store.py:39–41`), and the store root defaults to `PROJECT/document_store` (`uc042app/config.py:30`, env `UC042_DOCUMENT_STORE`). An existing folder is reused only if its accepted intake matches the document set.
2. `prepare_case(work, staging/"case", period)` (`uc042lib/prepare.py:104`) identifies files by content and selects the policy. Blocking intake decisions (MISSING required, AMBIGUOUS, REJECTED) fail the run before the engine.
3. `selected_policy(case_dir)` → `PeriodConfig(year, month, version)` (lines 796–799).
4. `build(case_dir, period)` (`uc042lib/pack/generate.py:37–50`) runs `assemble` (`pack/assemble.py:67`). `assemble` runs `run_engine` → `Validator(case_dir, period).run()` (assemble.py:61–64; the whole of Parts B–G). Then come `processing_outputs`, `finalise` (content hash and pack ID) and `validate_pack` (`pack/validate_pack.py:17`). A pack with validation findings is FAILED. Otherwise `render_html`.
5. `_publish` (services/monthly.py:897–925) writes, write-once, into `packs_root/<pack_id>/`:
   - `pack.json` (canonical);
   - `pack.html`;
   - `processing/control_results.csv`, `exceptions.csv`, `investigation_groups.csv`, `candidate_relationships.csv`, `document_details.csv`;
   - `generations/0001.json`.
   An identical existing pack gives ALREADY_EXISTS. A different pack with the same ID raises an error.
6. `self.packs.load(pack_id)` re-verifies the published pack.
7. `repos.periods.add_pack(...)` writes **`audit.period_packs`** (model `PeriodPack`, models.py:49–60).
8. `_record_lineage` (816–839) writes **`audit.pack_lineage`** (`__tablename__` at models.py:238) only for a REASSESSMENT whose pack differs from its predecessor. It records `change_summary` (what inputs, statuses and exceptions changed, read from both packs, nothing recomputed).
9. `_continuity` (Part H). Its report is stored in the run result only.

**5. Read path: GET `/api/v1/packs/{pack_id}/reconciliation`.** The route is `uc042app/api/routers/packs.py:30–33`, which calls `svc.packs.reconciliation(svc.packs.load(pack_id))`.

- `PackService.load` verifies the pack (services/packs.py:35–62).
- `PackService.reconciliation` (services/packs.py:82–88) returns `pack_id`, `accounts`, `currency_scope`, `reconciliation_days`, `internal_by_currency_day`, `external_by_account_day`, `opening_positions` and `client_balances_note`, "copied as reported (the pack computes no totals and nothing is recalculated)".

The exception register comes from **GET `/api/v1/packs/{pack_id}/exceptions`** (routers/packs.py:41).

**6. What the user sees.** The pack page is route `packs/:packId` (`frontend/src/App.tsx:27`), component `PackDetailPage.tsx`. It contains:

- **Reconciliation results** tabs (lines 73–81): "External reconciliation" (`external_by_account_day`, Part D: bank, ledger, difference, outcomes, evidence status, timing), "Internal reconciliation" (`internal_by_currency_day`, Part C: requirement, item A, items B–D, resource, difference) and a differences view.
- An **Exception register** panel (85–86): the exceptions of Part G, "all unresolved".

The monthly report (final audit pack, `uc042lib/final_pack/report.py`, `SECTIONS` lines 13–19) includes "Deterministic reconciliation results" (`_s_reconciliation`, line 146: control outcome summary, internal and external tables) and "Exception register" (`_s_exceptions`, 175). These are built from the final pack, which is assembled from the deterministic pack. The final-pack builder was not traced line by line for this document.

| Layer | Name | Writes or reads |
|---|---|---|
| Screen | ArchivePages "Start processing" / Reassessment "Reassess" | |
| API | POST `/api/v1/uploads/{id}/process`; POST `/api/v1/periods/{id}/reconciliation` | |
| Service | `MonthlyService.reconcile` → `process` → `_execute` → `_process` | `audit.processing_runs` |
| Intake | `prepare_case`, `selected_policy` | `document_store/cases/SET-…/` (source_data, supporting_documents, manifest.csv, intake.csv, policy_selection.json) |
| Engine | `build` → `assemble` → `Validator.run` → `validate_pack` | in memory |
| Publish | `_publish`, `add_pack`, `_record_lineage` | `packs/<pack_id>/…`; `audit.period_packs`; `audit.pack_lineage` |
| Read | GET `/api/v1/packs/{id}/reconciliation`, `/exceptions` | `pack.json` (verified) |
| Screen | `/packs/:packId` tabs and exception register; monthly report sections | |

---

# Part L — What the AI never does to these calculations

The AI investigation layer (`uc042lib/investigation`) runs only **after** a pack exists, and reads it. Its package docstring states that it "investigates exceptions already identified by the deterministic engine. It never re-reconciles, never resolves exceptions and never edits deterministic packs" (`investigation/__init__.py`, lines 1–2).

- It loads a pack only if the content hash verifies (`retrieval.load_pack`, retrieval.py:58–62).
- Its source-record access is read-only and scoped (`retrieval.py`, `tools.py`).
- Its instructions forbid recalculating or restating engine values, and require missing values to be called "not available" (`prompts.py`:24, 28).
- Its outputs are written as separate, write-once artefacts, and "deterministic packs … are never touched" (`persistence.py`:1).
- Every result carries the statement that AI findings "do not change any deterministic control outcome, do not resolve or close any exception" (`models.py`:133–134).

Every PASS, FAIL, figure, exception and status in this document comes from the deterministic engine alone.

---

# Part M — Known limitations (consolidated)

These are observed from the code. Items marked † were not executed or tested for this document.

1. **One safeguarding account per currency is assumed** (`acct_of_ccy`, validate.py:688). With two in one currency, only one would feed Item A. †
2. **Bank-ledger grouping when two accounts differ on the same days.** C08 FAILs are sorted by scope (`date/account`), so results for two accounts interleave. A group continues only if the *immediately preceding* result is the same account, on the previous reconciliation day, with the same amount (validate.py:1194–1205). Persistent differences on both accounts at once would therefore be split into one exception per account-day. †
3. **Exception fields left blank.** `first_date`, `account_id`, `currency` and `amount` are blank for exceptions whose result scopes do not start with a date or whose kind is not bank-ledger or unmatched-entry. Examples: MISSING_RECON, C11-*, CBAL-ROLLFWD; INTERNAL_DIFFERENCE has no account, currency or amount (validate.py:1254–1273). Observed in the SC3B, SC3C, SC5C and SC5D packs. A blank first date also sorts first among exceptions of equal severity.
4. **Internal differences are not merged across days** (one exception per day). They are linked only by L2 correlation (SC5C: 16 exceptions).
5. **Items B–D are taken as reported**, and the D+1 comparison is not performed (`pack/config.py` LIMITATIONS).
6. **The engine fingerprint does not cover `policy.py`, `prepare.py` or `continuity.py`** (`pack/config.py` ENGINE_MODULES). A change to policy selection reaches the pack through the input hashes and the IN-17 file name, not through the engine fingerprint.
7. **Dates from timestamps** are taken in the row's own offset in several checks (A.7). †
8. **C08 uses the cited bank confirmation even when C07 fails** for an account, currency or date mismatch (validate.py:766–768).
9. **The DISC-LOG check covers bank-ledger differences only.** It checks only that a log entry exists.
10. **C14 expectations come from the files themselves** (clients from IN-03), and both batch types are expected every reconciliation day.
11. **The evidence register shows the selected policy's key details** on every IN-17 row. In the May 2026 pack, the v1.1 row shows "Document version 1.2" because `assemble.py:106` looks up `v.pdf` by file ID.
12. **Hardcoded windows** (A.6) are not policy-driven.
13. **The client ledger is the only source of client balances.** Errors present in both IN-03 and IN-05 surface only through roll-forward and the C06 difference (SC5C).

---

## Glossary

- **Reconciliation day:** a date whose IN-01 row has `is_recon_day = true`.
- **Reconciliation point (P):** the time stated in the policy (17:00 Europe/London) on a reconciliation day. Records "as at the point" include items at or before it.
- **Requirement (C04):** the sum of non-negative client balances plus open unallocated receipts, per currency, at the point.
- **Resource (C05):** Item A (the cash-book balance of the safeguarding account at the point) plus reported items B–D.
- **Internal difference (C06):** resource − requirement.
- **External difference (C08):** bank confirmation balance − cash-book balance, per account, at the point.
- **Computed:** a figure the engine derived from source rows.
- **Reported:** a figure copied from the firm's own records (IN-05, IN-06).
- **PASS / FAIL:** the check was assessed and agreed / did not agree or found a breach.
- **INSUFFICIENT_EVIDENCE (INSUF):** the check could not be assessed because evidence is missing, unusable or possibly affected by an excluded row.
- **NOT_APPLICABLE:** used only for these cases:
  - no difference to resolve (C06/C08 = 0.00);
  - optional evidence absent (V00-FILE, C16);
  - a pre-period receipt (RC4, convention P1).
- **Evidence gate:** the rule that a check whose required files are unavailable does not run (`schema.DEPENDS`).
- **Taint / excluded row:** a row rejected for structure or period. Any scope it could touch becomes INSUF.
- **Root cause:** a string such as `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16` that identifies one underlying problem. Each root cause gives one exception.
- **Exception:** a register entry grouping all FAIL/INSUF results of one root cause. Always OPEN and AWAITING_HUMAN_REVIEW when created.
- **Investigation group (GRP):** evidence-linked exceptions for joint review. It establishes no cause.
- **Candidate (CAND):** an unverified date-and-amount coincidence. It is not a group.
- **Timing evidence:** a cross-day item cleared within one business day (D1). It explains a difference but never changes the outcome.
- **Case status:** CLEAN, EXCEPTIONS_OPEN or EVIDENCE_INCOMPLETE (G.4).
- **pack_content_sha256 / pack ID:** the hash of the canonical pack, and the identifier derived from it.
- **Continuity:** the comparison of the previous month's closing positions with this month's opening positions. It is read-only, outside the pack, and never changes a result.
- **SGA:** safeguarding (relevant-funds) bank account. **Own funds:** the firm's own account.
