# Claude Code handoff — processing the January–August 2026 historical demo

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

This package was prepared in Claude Web from the 2 Nov 2026 project snapshot (the UC-042 handoff). **Your local repository may have moved on** (Investigation V2, the final-pack library, FastAPI). Apply these steps to your current code, and re-check every file and line reference below against it.

**Not in this package, and never fabricated here:**

- deterministic packs;
- AI investigations;
- closing summaries;
- final packs.

## 0. Inputs and protections

- Put the package somewhere outside the September datasets, for example `uc042/demo_history/` as proposed. Each `2026-MM/source_documents/` is an engine-ready case folder: `source_data/`, `supporting_documents/` and `manifest.csv`.
- **Do not modify, regenerate or merge September 2026.** That covers `uc042_dataset/*` (nine datasets), `packs/*` (nine packs), September investigations and golden snapshots.
- `manifest.json` records the September baseline manifest SHA-256 at generation time (`september_reference`); verify it is unchanged before and after your work.
- **Never give the AI investigation context** `scenario_definition.json`, `mutations.json`, the README, these reports or the generator. They describe the planted answers. Treat them like `answer_key.json`.

## 1. Add period-aware configuration to the engine

These September-specific values exist in the snapshot. The September default must stay byte-identical, so every existing golden snapshot and pack hash must still match.

| Where (snapshot) | September value | Needs to come from a `PeriodConfig` |
| --- | --- | --- |
| `uc042lib/schema.py` `PERIOD_ID`, `PERIOD_START`, `PERIOD_END` | `PER-2026-09`, 1–30 Sep | Selected period |
| `schema.CSV_FILES` file names | `*_2026-09.csv` | `*_<YYYY-MM>.csv` (`account_inventory.csv` has no suffix) |
| `schema.PDF_FILES["IN-17"]` | `…policy_v1.2.pdf` | The policy in force: v1.1 for Jan–Apr, v1.2 for Jun–Aug; **May has both** (v1.1 for 1–6 May, v1.2 from 7 May). See below. |
| `schema.PDF_FILES["IN-18"]`, `["IN-19"]` | September register / August receipt | Period-specific or absent (absent in every month here) |
| `schema.PERIOD_RULES["IN-01"].equals.period_id` | `PER-2026-09` | Selected `period_id` |
| `schema.PERIOD_RULES["IN-03"/"IN-10"].permitted` | `2026-08-31T17:00:00+01:00` | Previous month end at 17:00 Europe/London (`2025-12-31T17:00:00+00:00` for January) |
| `uc042lib/validate.py` `UK_BANK_HOLIDAYS` | 31 Aug, 25/28 Dec | Add 1 Jan, 3 Apr, 6 Apr, 4 May, 25 May 2026 (England & Wales) |
| `validate.py` C16-RETURN `business_day_after(date(2026, 8, 31), 15)` | Due date of the August return | Due date of the return the receipt relates to |

**Policy selection in May.** The snapshot accepts one IN-17. Both versions carry identical rules (standard method, per currency, 17:00). Pre-validation used the policy in force at the period end (v1.2). Decide whether your engine should select by effective date per reconciliation day, and document the choice.

**Reference:** `verification/prevalidate_engine.py` shows exactly which attributes had to be patched for the existing engine to process these months. Implement them as configuration, not patching.

## 2–5. Load, run, generate packs, validate

1. **Load and run:** for each month, run the real engine on `2026-MM/source_documents` with that month's `PeriodConfig`, through the normal pipeline. Do not hand-write any `pack.json`.
2. **Generate packs:** one deterministic pack per month in the demo root, never in the production `packs/` directory. Keep write-once publication and hash verification.
3. **Scenario identity:** consider giving each month one, for example `H2026-03`. Pre-validation shows the `CASE` prefix because the packages carry no `scenario.json`.
4. **Validate against `scenario_definition.json`:** `expected_reconciliation_outcome` gives the case status, exception count, root causes and groups; `pre_validation_observed` is the reference run. Investigate any difference before accepting it.
5. **Expected results** (from pre-validation):

| Month | Case status | Results (pass / N/A / insufficient / fail) | Exceptions | Groups |
| --- | --- | --- | ---: | ---: |
| 2026-01 | CLEAN | 1,795 / 88 / 0 / 0 | 0 | 0 |
| 2026-02 | EVIDENCE_INCOMPLETE | 1,690 / 83 / 15 / 0 | 1 | 0 |
| 2026-03 | EXCEPTIONS_OPEN | 1,875 / 89 / 0 / 8 | 3 | 1 |
| 2026-04 | CLEAN | 1,717 / 84 / 0 / 0 | 0 | 0 |
| 2026-05 | EVIDENCE_INCOMPLETE | 1,604 / 76 / 15 / 8 | 4 | 1 |
| 2026-06 | EXCEPTIONS_OPEN | 1,873 / 92 / 0 / 4 | 4 | 2 |
| 2026-07 | EVIDENCE_INCOMPLETE | 1,928 / 95 / 15 / 4 | 5 | 2 |
| 2026-08 | EVIDENCE_INCOMPLETE | 1,718 / 80 / 15 / 12 | 8 | 3 |

**Exception families:**

| Family | Engine output |
| --- | --- |
| Missing EUR statement | `MISSING_BANK_EVIDENCE\|SGA-EUR-01\|<date>` (15 insufficient-evidence results; no balance substituted) |
| Unexplained GBP | `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|<date>\|-<amount>` (NOT_EVIDENCED, 3 days) + 2 × `UNMATCHED_BANK_ENTRY`, one group (L1 + L3) |
| Inconsistent reference | 2 × `C11-BATCH-BANK` + `CASH-BANK-LINK` + `UNMATCHED_CASHBOOK_ENTRY`, two reference groups |

**Tests to add:**

- period configuration and day counts;
- GMT and BST offsets (March contains the 29 Mar switch);
- continuity (reuse `verification/verify_history.py` logic);
- one test per scenario family;
- the combined months;
- unique IDs across months;
- pack hashes;
- September regression (golden snapshots unchanged).

## 6. AI investigations (existing V2 implementation only)

- Run at most four live V2 investigations on representative exceptions. Suggested:
    - March unexplained-difference group;
    - June inconsistent-reference group;
    - February missing-evidence exception;
    - one August exception.
- Record every other exception as NOT_INVESTIGATED.
- **Never reuse September findings for another month, and never label offline or simulated output as genuine AI.**
- PDFs are reference documents only: the AI pipeline does not parse PDF content.

## 7. Monthly AI closing summaries

Use the existing summary generator with the configured live provider (one call per month, eight in total).

- **Clean months:** describe zero exceptions without implying an audit opinion or compliance certification.
- **If the live provider is unavailable:** stop this stage and report it.

## 8. Final audit packs (existing Phase 1 library)

- **Content:** one per month (JSON, HTML and PDF), with the AI closing summary as the last substantive narrative section and every exception included, investigated or not.
- **Label every pack:** *"ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT A REAL MOORWAND AUDIT OR REGULATORY APPROVAL."*
- **Review records:** use a clearly synthetic demonstration reviewer record. Never resolve exceptions or imply certification.
- **Storage:** inside the demo root, write-once.

## 9. Preserve September

After all steps:

- re-hash every September dataset file, pack and golden snapshot and compare with the values before you started;
- run the full existing test suite;
- October stays NO DATA; November stays available for upload.

## Open questions for the product owner

1. **A1:** accept the illustrative policy v1.1, or treat January–April as evidence-incomplete?
2. **A2:** accept the bank-returned unexplained difference, or let it persist and give up clean following months and the August → September match?
3. **A3:** should the S04 bank entry's narrative also carry the wrong reference?
4. **May policy:** which version should the engine apply?
