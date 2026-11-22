# UC042_JAN_AUG_HISTORICAL_DEMO

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**
> Every record, balance, reference and document in this package is synthetic. Nothing here is a Moorwand record, an audit, or a regulatory approval.

## What this package is

Eight new monthly UC-042 source datasets (January–August 2026), forming one continuous synthetic timeline that ends exactly on the existing September 2026 opening positions. They are ready for Claude Code to process with the real, period-configured engine.

**Not included, by design:**

- deterministic audit packs;
- AI investigations;
- AI closing summaries;
- final audit packs.

None of these has been generated: the period-aware engine, Investigation V2 and the final-pack library are not available here. `claude_code_handoff.md` explains how Claude Code should produce them.

## Scenario distribution (as requested; no change was needed)

| Month | Scenario composition | Discrepancy types | Expected outcome (pre-validated) |
| --- | --- | ---: | --- |
| 2026-01 | Clean baseline | 0 | CLEAN, 0 exceptions |
| 2026-02 | Missing EUR bank statement (16 Feb) | 1 | EVIDENCE_INCOMPLETE, 1 exception |
| 2026-03 | Unexplained GBP discrepancy (−517.30 from 17 Mar) | 1 | EXCEPTIONS_OPEN, 3 exceptions, 1 group |
| 2026-04 | Clean baseline | 0 | CLEAN, 0 exceptions |
| 2026-05 | Missing EUR statement (15 May) + unexplained GBP (−1,093.65 from 18 May) | 2 | EVIDENCE_INCOMPLETE, 4 exceptions, 1 group |
| 2026-06 | Inconsistent settlement reference (10 Jun) | 1 | EXCEPTIONS_OPEN, 4 exceptions, 2 groups |
| 2026-07 | Missing EUR statement (15 Jul) + inconsistent reference (10 Jul) | 2 | EVIDENCE_INCOMPLETE, 5 exceptions, 2 groups |
| 2026-08 | Missing EUR (17 Aug) + unexplained GBP (−276.90 from 17 Aug) + inconsistent reference (10 Aug) | 3 | EVIDENCE_INCOMPLETE, 8 exceptions, 3 groups |

**The combinations are compatible.** Each multi-scenario month's exception count is the exact sum of its single-scenario parts (May 1 + 3; July 1 + 4; August 1 + 3 + 4). Missing EUR evidence is EUR-only; the GBP scenarios use different days and records.

**"Pre-validated"** means the **existing project engine** ran on each month with the reporting period patched in memory (`verification/prevalidate_engine.py`). It did not run on the project's own period configuration, which does not exist yet. Claude Code must reproduce these results with the real engine.

## Structure

```text
UC042_JAN_AUG_HISTORICAL_DEMO/
  manifest.json                package manifest (month manifests + hashes; September reference hash)
  README.md                    this file
  scenario_matrix.csv          one row per month
  continuity_report.md         opening/closing chain and the August→September boundary
  date_quality_report.md       per-month date, timezone and data-quality results
  historical_coverage_report.md  Jan–Aug generated; Sep existing; Oct NO DATA; Nov ready for upload
  claude_code_handoff.md       what Claude Code must do with this data
  2026-MM/
    manifest.json              period metadata, seed, file inventory + SHA-256, document statuses, processing status
    scenario_definition.json   scenarios, expected impact, missing records, expected outcome, pre-validation observed
    mutations.json             the exact planted changes (empty for clean months)
    source_documents/          engine-ready case folder
      manifest.csv             engine-format manifest (12 columns, SHA-256)
      source_data/             the 14 CSV files, e.g. transactions_2026-03.csv
      supporting_documents/    applicable PDFs
  generator/                   generate_history.py, build_docs.py, build_reports.py, _last_run.json
  verification/                verify_history.py, prevalidate_engine.py, and their JSON results
```

## How it was generated

- **Business conventions:** the same flows and rules as the project's own generator, documented in `uc042lib/generate.py` and `GENERATION_NOTES.md`:
    - bank-transfer loads;
    - card loads settled by the acquirer net of fees (0.30% and 0.155%, half-up), with a same-day own-funds top-up;
    - card spends and refunds settled by the scheme at 15:00 (convention D8);
    - redemptions;
    - unallocated receipts allocated the next reconciliation day;
    - the 17:00 Europe/London reconciliation point;
    - references (`AQ-*`, `SB-*`, `TOPUP-*`, `E2E-*`).
- **No September record is copied.** All amounts, clients and records are freshly drawn from one seed per month (`YYYYMM*100+42`), and identifiers embed their dates.
- **Balanced monthly flows:** redemptions keep client totals on a gently varying path, because re-using September's activity would grow balances by about £146k a month.
- **Planted scenarios** are explicit, recorded mutations of the generated clean month, in the same operation vocabulary as `uc042lib/scenarios.py`.
- **Reproducible:** regeneration produces byte-identical files, PDFs included (verified).

## Assumptions and adaptations (please review)

| # | Item | Decision | Alternative |
| --- | --- | --- | --- |
| A1 | **No policy exists before v1.2** (effective 7 May 2026; "approved 2026-04-30"). IN-17 is **required** and gates the internal reconciliation controls. | A watermarked **illustrative policy v1.1** (effective 2025-10-01) with v1.2's rules, used for 1 Jan–6 May. May carries both versions. | Omit it: January–April become evidence-incomplete and cannot be clean. |
| A2 | **Unexplained GBP discrepancy.** In September (S05) the unexplained debit persists to period end. An unresolved bank-ledger difference at a month end would carry into the next month (no later month could be clean), and would contradict the fixed September opening, where bank = ledger. | Each historical occurrence is **returned by the bank three reconciliation days later** (credit, same reference, narrative `RETURN …`, no counterparty). The cause stays unexplained. The engine reports a 3-day difference plus two unmatched bank entries. | Persist to month end and accept that the following months are not clean and the August → September boundary cannot match. |
| A3 | **Inconsistent settlement reference (S04)** | Grounded in `tests/test_baseline.py::test_equal_amount_is_not_a_link` and the research catalogue rule ("must not match on amount alone"): only `bank_reference` of the batch's bank entry is changed, to the first batch of the month. The narrative still names the correct batch. | Also change the narrative (not specified anywhere) |
| A4 | Missing EUR statement day | First reconciliation day on or after the 15th (the September scenario's day) | — |
| A5 | Governance register (IN-18), REP027 receipt (IN-19) | **Unavailable** in every month: optional; not fabricated. The engine reports them NOT_APPLICABLE. | — |
| A6 | August closing | One ordinary load or redemption per client on 28 Aug (16:40) lands every client exactly on the September opening | — |
| A7 | Bank holidays | England & Wales 2026 (1 Jan, 3 Apr, 6 Apr, 4 May, 25 May, 31 Aug) | — |
| A8 | Discrepancy log (IN-14) | Empty in every month, as in September's S02/S05. The engine therefore reports DISC-LOG FAIL on difference months. | — |
| A9 | Acknowledgement letters (IN-15/16) | The existing synthetic letters (dated 2024-03-01, before every month) are reused unchanged | — |
| A10 | Opening snapshot IDs | When the previous month ends on a reconciliation day, the opening snapshot is byte-identical to that month's closing snapshot (same ID): a carried-forward position, not a conflicting duplicate | — |

## Regenerate and verify

From this folder (needs Python 3.12, `reportlab`, `pypdf` and a copy of the UC-042 project, read-only):

```bash
python generator/generate_history.py --project /path/to/uc042 --out .
python verification/verify_history.py --project /path/to/uc042        # independent data-quality + continuity checks
python verification/prevalidate_engine.py --project /path/to/uc042    # existing engine, period patched in memory
python generator/build_docs.py --project /path/to/uc042
python generator/build_reports.py
```

These commands write only inside this package. They never modify the project.
