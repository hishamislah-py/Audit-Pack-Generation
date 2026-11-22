# UC-042 — January–August 2026 historical dataset: validation and deterministic execution

Date: 3 November 2026. **Scope:** validation of the supplied January–August package, period-aware engine changes, and
eight deterministic packs.

**Not done:**

- no live OpenAI call;
- no AI investigation;
- no closing summary;
- no final audit pack.

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

## A. Starting test baseline (before any change)

| Suite | Result |
| --- | --- |
| Python, `python -W error::ResourceWarning -m unittest` | **477 run: 476 passed, 1 skipped** (opt-in live test), 0 failed (239 s) |
| Golden snapshots | Asserted inside the suite (6 modules). Passed. |
| Frontend `npm test` | 23 passed, 2 skipped (live), 4 files (1 skipped) |
| Frontend `npm run build` | OK |

`CLAUDE_CODE_HANDOFF.md` §11 still says 409 tests, which is stale; report 13 records 477.

`docs/data_audit/01_HISTORICAL_FINANCIAL_DATA_AND_DATE_COVERAGE_AUDIT.md`, named in the brief, **does not exist** in this repository.

## B. Package inventory and integrity

**Delivery.** The package was supplied as a folder, not a ZIP: `uc042/UC042_JAN_AUG_HISTORICAL_DEMO/UC042_JAN_AUG_HISTORICAL_DEMO/`. ZIP integrity and path-traversal entries therefore do not apply. Instead, every path was checked to resolve inside the package, with no symbolic links. Validation ran on a scratch copy; the package itself stayed read-only (hash-checked before and after).

**Files.** 184 files, exactly the expected set, with no unexpected, missing or duplicate paths:

| Category | Count |
| --- | ---: |
| Source CSV (14 per month × 8) | 112 |
| Supporting PDF (3 per month; May 4) | 25 |
| Engine `manifest.csv` | 8 |
| Month `manifest.json` | 8 |
| Scenario oracle (`scenario_definition.json`, `mutations.json`) | 16 |
| Package documents | 7 |
| Generator | 4 |
| Verification | 4 |

The full inventory (month, file, category, size, records, SHA-256, period) is in `demo_history/verification/package_inventory.csv`.

**Manifests and hashes:**

- every hash in the package `manifest.json`, the eight month `manifest.json` files and the eight engine `manifest.csv` files matches;
- every record count matches;
- the September reference hash (`0360b405…`) matches the current baseline manifest.

**Regeneration.** `generator/generate_history.py` was run into an isolated copy (Python 3.11; the package states 3.12):

- **every CSV, PDF and `manifest.csv` is byte-identical**;
- the JSON and Markdown metadata differ only by Windows CRLF line endings, plus the embedded hashes of those CRLF files. After newline normalisation, all 183 regenerated files match. `README.md` is hand-written and not regenerated.

**Duplicate content:**

- CSV content is unique across the months and September, except the standing `account_inventory.csv` and the header-only `discrepancy_log` files;
- the recurring PDFs are the standing documents: acknowledgement letters identical to September's, v1.2 identical to September's, and the one illustrative v1.1.

## C. Source-data validation (all eight months)

`tools/verify_demo_history.py` is independent of the engine's calculation code: plain csv, `Decimal`, `zoneinfo`. All checks found **0 problems** in Jan and Apr. In the other months they found **only planted, explained findings**.

**File and schema:**

- 14 categories per month with exact contract headers and order;
- every value type-checked: date, timestamp, amount (unsigned 2 dp), signed, int, bool, currency, enums;
- mandatory and conditional fields populated; optional blanks permitted;
- money is exact 2-dp text, and no `float(` is used in the engine or the verifier;
- currencies are GBP/EUR only and equal their account's currency;
- debit/credit indicators are only C/D.

**Identifiers:**

- project conventions are followed, and the same patterns hold for the September baseline;
- the date embedded in each ID equals the record's own date.

One deliberate new convention: unallocated receipts are `UR-YYYYMM-Gnn` (September: `UR-nnnn`), so they stay unique across periods.

**Keys and duplicates:**

- primary keys are unique;
- there are no exact duplicate rows;
- there are no natural-key duplicates: account-day statements, client-day snapshots, day-currency and day-account reconciliation records, calendar dates, bank entries, transactions, batch lines.

**Across months:** only the standing account inventory and **48 carried-forward boundary snapshots** share IDs. These are 12 clients × the four months whose previous month ended on a reconciliation day (Apr, May, Jul, Aug). Each shared row is byte-identical and dated at the boundary, so it is a carry-forward, not an accidental duplicate.

**Relationships (positive and negative):**

- bank entry → statement, account and day;
- external record → confirmation;
- cash book ↔ bank, one-to-one by reference. A reference on several bank entries is reported as ambiguous; the amount never chooses;
- batch → bank by `expected_bank_reference` only;
- line → batch and transaction;
- transaction → batch;
- refund → original;
- bank-load or redemption transaction → `end_to_end_ref`;
- receipt → bank;
- clients;
- log → reconciliation record.

Tampered copies prove the checks fail: a dangling `txn_id`, a duplicate primary key and a re-pointed reference are each detected.

**Arithmetic (Decimal):**

- statement opening + entries = closing;
- entry counts;
- day-to-day statement chain;
- 17:00 confirmation = opening + entries to 17:00;
- batch gross = TXN lines, fees = FEE lines, refunds = REFUND lines, gross − fees − adjustments = net;
- reported internal and external differences.

**Duplicate bank references (per account):** only the planted ones.

| Month | Reference | Entries |
| --- | --- | --- |
| March | `SETTLE 0263` | X01 / X02 |
| May | `SETTLE 0391` | X01 / X02 |
| August | `SETTLE 0528` | X01 / X02 |
| June | `SB-GBP-20260601` | `BE-GBP-0601-SB1` and `BE-GBP-0610-SB1` |
| July | `SB-GBP-20260701` | the July equivalents |
| August | `SB-GBP-20260803` | the August equivalents |

**Planted mutations.** Every operation in each `mutations.json` is present exactly in the data:

- each deleted key is absent;
- each added record is present, identical;
- each changed field holds the new value.

**Findings explained by planted scenarios.** Every relationship or arithmetic finding is explained by a planted scenario. The rules, checked automatically:

- **missing EUR statement:** only EUR records of that day, namely:
  - the external record without confirmation;
  - the five cash-book entries;
  - the AQ and SB batches;
  - two bank-transfer transactions;
  - one statement-chain gap;
- **GBP difference:** only the two added bank entries;
- **reference:** only the two batches, the two bank entries carrying the reference, and their cash-book entries.

## D. Financial continuity

Independent calculation:

- **clients:** the last snapshot by the next opening point, rolled forward with transactions to that point;
- **cash book:** the entries posted by the point;
- **bank:** each account's last statement closing against the next first statement opening;
- **unallocated:** receipts open at the boundary.

Views are compared only with their own previous-period view.

| Transition | Clients | Cash book | Bank (SGA GBP/EUR, OWN GBP/EUR) | Result |
| --- | ---: | ---: | ---: | --- |
| Jan → Feb … Jul → Aug (7 transitions) | 12 | 2 | 4 | **18/18 MATCH each**, difference 0.00 |
| **Aug → Sep (existing September)** | 12 | 2 | 4 | **18/18 MATCH**, difference 0.00 |

**Unallocated receipts:** none is open at any boundary, in either register.

**Engine module.** `uc042lib.continuity.compare` finds no DIFFERENCE on any transition, and BANK and CASH_BOOK MATCH. Its CLIENT view is NOT_VERIFIABLE where the previous month ended on a non-reconciliation day: it needs a snapshot on that exact day and does not roll forward. That is by design, not a defect.

**August → September (record key: August closing = September opening, difference):**

| Record | Value | Difference |
| --- | ---: | ---: |
| C0001/GBP | 40,000.00 = 40,000.00 | 0.00 |
| C0002/GBP | 35,000.00 = 35,000.00 | 0.00 |
| C0003/GBP | 32,500.00 = 32,500.00 | 0.00 |
| C0004/GBP | 30,000.00 = 30,000.00 | 0.00 |
| C0005/GBP | 30,000.00 = 30,000.00 | 0.00 |
| C0006/GBP | 28,500.00 = 28,500.00 | 0.00 |
| C0007/GBP | 27,500.00 = 27,500.00 | 0.00 |
| C0008/GBP | 26,500.00 = 26,500.00 | 0.00 |
| C0101/EUR | 25,000.00 = 25,000.00 | 0.00 |
| C0102/EUR | 20,000.00 = 20,000.00 | 0.00 |
| C0103/EUR | 18,000.00 = 18,000.00 | 0.00 |
| C0104/EUR | 17,000.00 = 17,000.00 | 0.00 |
| Cash book SGA-GBP-01 (GBP) | 250,000.00 = 250,000.00 | 0.00 |
| Cash book SGA-EUR-01 (EUR) | 80,000.00 = 80,000.00 | 0.00 |
| Bank SGA-GBP-01 (GBP) | 250,000.00 = 250,000.00 | 0.00 |
| Bank SGA-EUR-01 (EUR) | 80,000.00 = 80,000.00 | 0.00 |
| Bank OWN-GBP-01 (GBP) | 500,000.00 = 500,000.00 | 0.00 |
| Bank OWN-EUR-01 (EUR) | 150,000.00 = 150,000.00 | 0.00 |

All 18 are MATCH. August's sources are the 28 Aug snapshot and statements (31 Aug is a bank holiday), with no movement between 28 Aug 17:00 and 31 Aug 17:00. The September side is September's 31 Aug opening rows. No September file was changed. The full table is in `demo_history/verification/continuity.csv`.

**January opening:** 31 Dec 2025 17:00 GMT (`+00:00`), with IDs `CBS-20251231-*` and `LE-*-1231-0000`.

| Position | GBP | EUR |
| --- | ---: | ---: |
| Clients | Σ 223,400.00 | Σ 71,100.00 |
| Cash book and safeguarding bank | 223,400.00 | 71,100.00 |
| Own funds | 504,136.00 | 151,082.84 |

These equal the package's documented position. The package documents it as a "documented synthetic demonstration opening position … not derived from any real or earlier record"; the calendar basis reads `SYNTHETIC: …`. Without a previous period, the engine's continuity report says NOT_VERIFIABLE; nothing is assumed.

## E. Date and timezone verification

**Timestamps.** Each timestamp field is judged separately, never collapsed into one date. A timestamp is valid only if its offset equals Europe/London's offset **at that instant** and its wall time exists.

| Months | Offsets |
| --- | --- |
| Jan, Feb | all `+00:00` |
| Apr–Aug | all `+01:00` |
| March | 1,740 `+00:00` and 172 `+01:00` |

In March, every `+00:00` timestamp is before 29 Mar 2026 01:00 UTC and every `+01:00` timestamp is at or after it. No activity falls on Sunday 29 March.

Negative tests:

- 01:30 on 29 March is rejected with either offset;
- a BST offset on 27 March is rejected;
- a GMT offset on 30 March is rejected.

**Date rules:**

- booking date = the London date of the booking timestamp;
- value date ≥ booking date;
- authorisation ≤ execution, and clearing ≥ authorisation;
- settlement on a reconciliation day, not before its cycle date;
- snapshots, internal reconciliation points and confirmations at 17:00 London on reconciliation days;
- performed-at after the point;
- receipt and allocation dates consistent with their timestamps.

**Calendars:**

- every day of the month is present;
- reconciliation days = England & Wales business days (21/20/22/20/19/22/23/20). An independent written-out holiday list and the engine's computed calendar agree;
- 1 Jan, 3 Apr, 6 Apr, 4 May, 25 May and 31 Aug are `UK_BANK_HOLIDAY`;
- no statement or bank booking falls on a weekend or bank holiday.

Tampered values are detected: an impossible date (2026-02-30), a malformed timestamp, a wrong offset, an out-of-period execution and a Saturday settlement.

**Out-of-period rows.** The only rows outside each month are its opening boundary rows, at the previous month-end 17:00 London (opening points `2025-12-31T17:00+00:00`, `2026-02-28T17:00+00:00`, `2026-03-31T17:00+01:00`, …).

**31 August.** August holds no record dated 31 Aug. September's 14 rows dated 31 Aug (12 snapshots, 2 OPENING_BALANCE) are only boundary records; the engine's DQ-PERIOD has no failure for September.

**Document dates:**

| Document | Date |
| --- | --- |
| Acknowledgement letters | 2024-03-01 |
| Policy v1.1 effective | 2025-10-01 |
| Policy v1.2 effective | 2026-05-07 |

## F. Policy v1.1 and the May policy comparison

**What the engine consumes from IN-17:**

- Reconciliation point;
- Reconciliation method;
- Internal reconciliation basis;
- Effective date: a policy effective after the period end is never applied.

The document version is not read.

**v1.1:**

- watermarked "ILLUSTRATIVE SYNTHETIC DOCUMENT — NOT AN OFFICIAL RECORD" (twice);
- states "Illustrative predecessor of policy v1.2 … Its contents are an assumption (same rules as v1.2), not a recovered document";
- effective 2025-10-01; superseded by v1.2 from 2026-05-07;
- its engine-relevant key details are identical to v1.2 (17:00 Europe/London, STANDARD, Per currency, SEGREGATION, each reconciliation day).

It cannot be mistaken for a Moorwand policy, and it is technically valid for the engine.

**Blocker found and fixed.** The engine's IN-17 file name was fixed at `…policy_v1.2.pdf`, so January–April read as "required file not provided". With that bug, January and April were EVIDENCE_INCOMPLETE, and March's C08 difference was hidden behind the missing policy. See I.

**Isolated comparison: January without v1.1** (decision A1 alternative). EVIDENCE_INCOMPLETE, with one exception `MISSING_FILE|IN-17`; it cannot be clean.

**May (v1.1 vs v1.2), run in isolation:**

| | v1.1 | v1.2 |
| --- | --- | --- |
| Inputs | same 14 CSV; letters + v1.1 | same 14 CSV; letters + v1.2 |
| Results | 1,703: 1,604 PASS / 76 NA / 15 INSUF / 8 FAIL | identical |
| Exceptions | 4 (identical root causes, IDs, amounts, dates, groups) | identical |
| Evidence completeness | INCOMPLETE (missing EUR 15 May) | identical |
| C03-POLICY | PASS, cites v1.1 | PASS, cites v1.2 |

All 1,703 results are identical once the cited policy file name is normalised. **There is no material difference.**

**Recommendation for May: v1.2.**

- It is the version in force at the period end;
- it covers 16 of May's 19 reconciliation days (v1.1 covers 1, 5 and 6 May);
- it is the existing project document;
- it matches the package pre-validation.

The May pack was generated with v1.2. The selection is explicit (`tools/build_demo_history.py` `POLICY_SELECTION`) and **pending approval**. The pack's audit trail and evidence register list **both** supplied policy files with their hashes. Both originals are preserved unchanged.

If per-day policy selection is ever wanted, the engine would need to be changed so that it can take more than one policy in a period. With identical rules it would change nothing here.

## G. Unexplained GBP discrepancy (March −517.30; also May −1,093.65 and August −276.90)

**March records:**

| Record | Detail |
| --- | --- |
| Original entry `BE-GBP-0317-X01` | 17 Mar 15:20, **517.30 D**, reference `SETTLE 0263`, no counterparty |
| Subsequent entry `BE-GBP-0320-X02` | 20 Mar 10:05, **517.30 C**, same reference, narrative `RETURN SETTLE 0263` |
| Cash book | No entry carries `SETTLE 0263`: no cash-book movement |

**Daily view.** The 17:00 bank confirmation minus the cash book to 17:00 (independent calculation) is −517.30 on 17, 18 and 19 March and 0.00 on every other day. The engine agrees: C08 FAIL −517.30 on exactly those three days.

The internal view is unaffected: C04/C05 PASS every day, and C06 has no difference on any day.

**Month end.** Bank = ledger on 31 March, so the monthly balance is brought back into agreement. The continuity to April matches.

**Exceptions.** EXC-H202603-01 `BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-03-17|-517.30`:

- Critical, 17–19 Mar;
- NOT_EVIDENCED;
- **OPEN, AWAITING_HUMAN_REVIEW, no cause**;
- grouped with the two UNMATCHED_BANK_ENTRY exceptions (L1 reference + L3 lineage);
- DISC-LOG FAIL (no log entry).

No exception text says "resolved", "reversed", "corrected" or "returned by the bank" (tested). The cause stays unexplained; the later credit restores the balance but does not establish what the debit was. The engine has no resolution mechanism, so the exception stays open.

**May and August.** The same structure: 18–20 May (return 21 May) and 17–19 Aug (return 20 Aug).

## H. Inconsistent settlement reference (S04)

**Research.** In `docs/dataset_assessment/02` S04 is "an amount matches but the reference points to the wrong batch". Input spec §IN-12→IN-09: the link is `expected_bank_reference = bank_reference`, and "Amount alone (spec S04)" is not a basis. Spec IN-09: `narrative_text` is "Free text. Never authoritative." The engine's existing regression test `test_equal_amount_is_not_a_link` mutates **only `bank_reference`**. The package does the same.

**June evidence.** `BE-GBP-0610-SB1` has exactly the net of `SB-GBP-20260610` on its settlement date and account, but carries `SB-GBP-20260601`. The engine does **not** link them. Its four exceptions:

| Exception | Group |
| --- | --- |
| C11-BATCH-BANK for 0610 (no bank entry) | 0610 group |
| C11-BATCH-BANK for 0601 (two bank entries) | 0601 group |
| CASH-BANK-LINK for LE-GBP-0601-0005 (ambiguous reference) | 0601 group |
| UNMATCHED_CASHBOOK_ENTRY for LE-GBP-0610-0005 | 0610 group |

The groups are two L1 reference groups. No C08 difference arises, because the balances are unaffected.

**Variant 2: narrative changed as well.** Tested on a temporary copy only; the package was not changed. The results are **identical**: same root causes, same non-passing results, same outcome counts. The engine never reads `narrative_text` (asserted).

**Recommendation.** Keep the reference-only representation. It is what S04 and the existing regression test define, and changing the narrative adds nothing the engine uses.

## I. Period-aware engine changes

The engine was already period-aware (report 13: `PeriodConfig`, period rules, calendars, continuity). The package's patch list described an older snapshot. **Remaining gaps found and fixed** (minimal, period-specific interfaces only; no calculation changed):

| File | Change |
| --- | --- |
| `uc042lib/period.py` | `PeriodConfig.policy_version` (optional; excluded from equality, so a period is still identified by its month). IN-17 file name `safeguarding_reconciliation_policy_v{policy}.pdf`, default v1.2. `resolve()` takes the version the case supplies (manifest, else documents). **More than one supplied version and none selected → `PeriodError`**: the engine never chooses. Helper `policy_version_of()`. |
| `uc042lib/validate.py` | With a file ID listed twice in `manifest.csv` (two policies), the row of the file actually read is used. Before, the last row won: v1.1 was checked against v1.2's hash and gave a spurious V00-FILE FAIL. |
| `uc042lib/pack/assemble.py` | `load_sources` always resolves the period against the case, so it picks up the supplied policy. |
| `uc042lib/pack/generate.py` | CLI `--policy-version N.N` (requires `--period`). |
| `uc042lib/investigation/retrieval.py` | `EvidenceStore` reads the policy version the pack's results cite (`pack_policy_version`), so a later investigation reads the same documents. |
| `uc042lib/investigation/config.py` | `scenario_definition.json` added to `FORBIDDEN_NAMES`. |

**Other requirements:**

- the engine is not duplicated;
- there is no global mutable setting;
- September stays the default.

**Identity.** Scenario ID `H2026MM`, giving `PACK-H2026MM-PER-2026-MM-…` and `EXC-H2026MM-nn`. The handoff's `H2026-03` would break the investigation layer's `PACK_ID_RE` (no hyphen allowed).

**September regression.** All nine September packs were rebuilt in memory and compared with the stored packs:

- **canonical content and all processing outputs are identical**;
- only the five code-derived fields differ (engine and pack-layer fingerprints, run ID, content hash, pack ID), as accepted in report 13;
- no stored pack was rewritten.

## J. Deterministic results (real engine, `demo_history/`)

| Month | Pack | Policy | Status | PASS / NA / INSUF / FAIL | Exc. | Groups | Missing evidence |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| 2026-01 | `PACK-H202601-PER-2026-01-bc596db0bfe6` | 1.1 | CLEAN | 1,795 / 88 / 0 / 0 | 0 | 0 | 0 |
| 2026-02 | `PACK-H202602-PER-2026-02-195df2e1f216` | 1.1 | EVIDENCE_INCOMPLETE | 1,690 / 83 / 15 / 0 | 1 | 0 | 1 |
| 2026-03 | `PACK-H202603-PER-2026-03-d1d37aea9c2b` | 1.1 | EXCEPTIONS_OPEN | 1,875 / 89 / 0 / 8 | 3 | 1 | 0 |
| 2026-04 | `PACK-H202604-PER-2026-04-a854c4a2bcfd` | 1.1 | CLEAN | 1,717 / 84 / 0 / 0 | 0 | 0 | 0 |
| 2026-05 | `PACK-H202605-PER-2026-05-051d209cccc4` | 1.2 | EVIDENCE_INCOMPLETE | 1,604 / 76 / 15 / 8 | 4 | 1 | 1 |
| 2026-06 | `PACK-H202606-PER-2026-06-a07de266b389` | 1.2 | EXCEPTIONS_OPEN | 1,873 / 92 / 0 / 4 | 4 | 2 | 0 |
| 2026-07 | `PACK-H202607-PER-2026-07-5d8714f8c422` | 1.2 | EVIDENCE_INCOMPLETE | 1,928 / 95 / 15 / 4 | 5 | 2 | 1 |
| 2026-08 | `PACK-H202608-PER-2026-08-22a356a95098` | 1.2 | EVIDENCE_INCOMPLETE | 1,718 / 80 / 15 / 12 | 8 | 3 | 1 |

The engine counts equal the package's pre-validation counts **exactly, month by month**. Each pack includes:

- pack ID and reporting period;
- the dataset manifest reference and source-file hashes (`audit_trail.inputs`);
- internal and external reconciliation views;
- exceptions, groups and candidates;
- the evidence register;
- the missing-evidence register;
- the content hash.

## K. Expected versus actual

| Month | Expected | Actual | Difference | Root causes | Groups | Result |
| --- | ---: | ---: | ---: | --- | --- | --- |
| January | 0 | 0 | 0 | — | — | MATCH |
| February | 1 | 1 | 0 | equal | equal | MATCH |
| March | 3 | 3 | 0 | equal | equal | MATCH |
| April | 0 | 0 | 0 | — | — | MATCH |
| May | 4 | 4 | 0 | equal | equal | MATCH |
| June | 4 | 4 | 0 | equal | equal | MATCH |
| July | 5 | 5 | 0 | equal | equal | MATCH |
| August | 8 | 8 | 0 | equal | equal | MATCH |

No exception was inserted or removed by hand.

**Interaction tests.** The planted operations were reverted on temporary copies. Missing-statement deletions cannot be restored from the oracle and were never reverted.

- **March and June:** reverting their only scenario gives CLEAN, with 0 non-passing results.
- **May and July:** reverting GBP or REF leaves only the missing-EUR exception. What the scenario adds has the same shape as March and June (3 or 4 exceptions).
- **August:**
  - only-missing = 1;
  - + reference = 4;
  - + GBP = 3;
  - total 1 + 3 + 4 = 8;
  - non-passing(Aug) = non-passing(Aug − GBP) ∪ non-passing(Aug − REF).
- Missing EUR evidence produces no GBP finding.
- CBAL-ROLLFWD and CBAL-NONNEG have no failure in any month or variant.

**Exception level** (evidence IDs abbreviated; full lists in each pack):

| Exception | Root cause | Key evidence |
| --- | --- | --- |
| EXC-H202602-01 Critical | MISSING_BANK_EVIDENCE SGA-EUR-01 2026-02-16 | IN-06:ERL-SGA-EUR-01-20260216, IN-12:AQ/SB-EUR-20260216, IN-10:LE-EUR-0216-0001…5 (14 IDs); MISS-01 lists 15 results |
| EXC-H202603-01 Critical, GRP-01 | BANK_LEDGER_DIFFERENCE −517.30 17–19 Mar | IN-06:ERL-SGA-GBP-01-20260317/18/19, IN-07:ST-SGA-GBP-01-2026031x-1700 |
| EXC-H202603-02 / -03 High, GRP-01 | UNMATCHED_BANK_ENTRY | IN-09:BE-GBP-0317-X01 / IN-09:BE-GBP-0320-X02 |
| EXC-H202605-01 | MISSING_BANK_EVIDENCE 2026-05-15 | IN-06:ERL-SGA-EUR-01-20260515 … |
| EXC-H202605-02, -03, -04 (GRP-01) | −1,093.65 18–20 May; X01 / X02 | IN-06/07 18–20 May; IN-09:BE-GBP-0518-X01, BE-GBP-0521-X02 |
| EXC-H202606-01 / -03 (GRP-01) | C11-BATCH-BANK SB-GBP-20260601; CASH-BANK-LINK LE-GBP-0601-0005 | IN-12:SB-GBP-20260601, IN-09:BE-GBP-0601-SB1, IN-09:BE-GBP-0610-SB1, IN-10:LE-GBP-0601-0005 |
| EXC-H202606-02 / -04 (GRP-02) | C11-BATCH-BANK SB-GBP-20260610; UNMATCHED_CASHBOOK_ENTRY LE-GBP-0610-0005 | IN-12:SB-GBP-20260610, IN-10:LE-GBP-0610-0005 |
| EXC-H202607-01 … -05 | missing EUR 15 Jul + the July reference pair (0701 / 0710) | as June, July IDs |
| EXC-H202608-01 … -08 | GBP −276.90 17–19 Aug (+X01 / X02, GRP-01); missing EUR 17 Aug; reference pair 0803 / 0810 (GRP-02, GRP-03) | as above, August IDs |

## L. Evidence relationships

For all eight packs:

- the content hash and pack ID verify;
- the synthetic notice is present in metadata and statements;
- every input hash equals the dataset file;
- **every evidence-register record resolves** to its file, line and primary key;
- **every evidence ID cited** by results, exceptions and groups resolves;
- every exception is OPEN / AWAITING_HUMAN_REVIEW with no cause.

**Planted records are cited:**

| Scenario | Cited records |
| --- | --- |
| GBP months | both X01 and X02 |
| Reference months | the batch without its reference, and the re-pointed bank entry |
| Missing months | that day's external record |

**Reproducibility.** Each stored pack is reproduced **byte for byte** by an in-memory rebuild with the current code (same pack ID, `pack.html` and processing outputs).

**AI-context isolation.** The engine, run on the package's own case folder (next to the oracles), opens only files inside that folder (tested).

## M. Tests

| Suite | Run | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Python full suite (after), `-W error::ResourceWarning` | 538 | 537 | 0 | 1 (opt-in live test) |
| of which new `tests/test_demo_history.py` | 61 | 61 | 0 | 0 |
| Frontend `npm test` (after; no frontend change) | 25 | 23 | 0 | 2 |
| Frontend production build | — | OK | — | — |

The new tests are grouped as follows:

| Group | Tests |
| --- | ---: |
| Package integrity, including regeneration | 8 |
| Source data | 10 |
| Dates and time | 7 |
| Continuity | 5 |
| Period-aware engine | 10 |
| Scenario behaviour | 7 |
| Scenario interaction | 6 |
| Output packs | 6 |
| Immutability | 2 |

No existing test was changed or weakened.

## N. September integrity

These were hashed before the work began and compared afterwards:

- the nine September datasets (`uc042_dataset/`, 287 files);
- the nine packs (`packs/`, 72 files);
- the golden snapshots (`tests/golden/`, 10);
- the investigations, including `_not_published` (34);
- the Phase 1 final-pack library (`uc042lib/final_pack/`, 12).

**Result: all unchanged.** The project-wide before/after comparison (761 files, excluding `.venv`, `node_modules`, `frontend/dist`, `__pycache__`) shows only:

- the six modified engine and layer files;
- four added files: two tools, one test module and this report.

`tests/test_demo_history.py::Immutability` asserts the five tree digests permanently.

There are no `final_packs/` or `app_state/` folders in the project. The supplied package is unchanged (184 files hashed before and after). No `H2026*` artefact exists under `packs/`, `investigations/` or `uc042_dataset/`.

## O. Files created and modified

**Modified (engine and layers):**

- `uc042lib/period.py`
- `uc042lib/validate.py`
- `uc042lib/pack/assemble.py`
- `uc042lib/pack/generate.py`
- `uc042lib/investigation/retrieval.py`
- `uc042lib/investigation/config.py`

**Created:**

- `tools/build_demo_history.py`
- `tools/verify_demo_history.py`
- `tests/test_demo_history.py`
- this report
- `demo_history/README.md`
- `demo_history/datasets/2026-01 … 2026-08/`: copies plus `scenario.json`
- `demo_history/packs/` (8 packs)
- `demo_history/verification/`:
  - `run_manifest.json`
  - `verification_results.json`
  - `continuity.csv`
  - `package_inventory.csv`

**Rebuilt but unchanged in source:** `frontend/dist/` (by `npm run build`).

## P. Decisions requiring approval

1. **A1, policy v1.1 for January–April.** Recommendation: accept it as an *illustrative synthetic* document for the demonstration; it is clearly watermarked and has v1.2's rules. The alternative leaves January–April EVIDENCE_INCOMPLETE (tested).
2. **May policy.** Recommendation: v1.2 (identical results; see F). Currently selected and pending approval.
3. **A2, bank-returned GBP difference.** The data restores agreement by month end, which keeps months clean and the August → September boundary exact. The exception stays OPEN and unexplained. The alternative (persisting differences) would break the September boundary. Recommendation: accept.
4. **A3, S04.** Recommendation: keep reference-only. A narrative change makes no difference to the engine.

**Before AI investigations:**

- the investigation layer's default roots point at `packs/` and `uc042_dataset/`. A run on these packs must pass `packs_root=demo_history/packs` and `datasets_root=demo_history/datasets`;
- `EvidenceStore` loading was tested offline for the January, May and August packs.

**Known limitations:**

- upload intake (`uc042lib/prepare.py`, app) still identifies only the canonical v1.2 policy name, so a policy of another version uploaded through the app is not yet recognised;
- the engine does not model policy supersession (it would accept v1.1 for June if selected explicitly; v1.1's supersession is only free text).

## Q. Confirmation

- **No live OpenAI call was made.** No provider was invoked; the opt-in live test stayed skipped.
- **No AI investigation, closing summary or final audit pack was generated.**
- No historical investigation or final-pack directory was created.
- No simulated output is labelled as AI.
- No September dataset, pack, golden snapshot or investigation was modified.
