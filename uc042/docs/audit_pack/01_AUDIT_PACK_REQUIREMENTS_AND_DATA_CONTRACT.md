# 01 — Audit Pack Requirements and Data Contract

Status: **design for review.** Nothing is implemented. Date: 30 Oct 2026.

The contract is a **POC design for synthetic data**, not an official Moorwand or regulatory format.

It reuses the verified deterministic engine (`uc042lib/validate.py`) and its outputs. The pack layer **never recalculates or reinterprets** a financial value or control outcome: it copies engine outputs and source fields, and cites them.

**Field-status tags used throughout:**

| Tag | Meaning |
| --- | --- |
| **[C] Confirmed** | Exists today; source named |
| **[P] Proposed** | New, derived **without financial calculation** (identifiers, counts of records, reverse indexes, copies of source fields) |
| **[G] Gap** | Needs a small additive engine change or a decision before it can be filled (see §5) |

## 1. Requirements

| # | Requirement |
| --- | --- |
| R1 | A clean scenario produces a **complete, useful** pack. Empty exception, group and missing-evidence registers are explicit "none" statements, not missing sections. |
| R2 | Every figure, outcome and status in the pack equals an engine output or source field, and cites it |
| R3 | Pack generation status, evidence completeness, control outcomes and exception review status are **separate fields** |
| R4 | Missing evidence is listed as missing, never as zero |
| R5 | Investigation groups and candidates are never presented as causes; unexplained differences are never presented as explained |
| R6 | Deterministic: identical inputs, engine and configuration give identical canonical pack content |
| R7 | Immutable: a generated pack is never rewritten. New inputs or rules give a new pack. |
| R8 | Traceable: every evidence reference resolves to a source record or document, or to a generated output, of the same run |
| R9 | No AI in assembly. Future AI narrative may only restate cited pack content. |

## 2. Inventory: what exists versus what must be generated

| Information | Exists? | Source |
| --- | --- | --- |
| Control results (check, control code, scope, outcome, computed, reported, evidence, note, root cause, evidence status) | **[C]** | `Validator.results` (`validate.py` `add()`); persisted `validation/control_results.csv`. 1,886 results in the baseline, 32 check types. (`check_id`, `scope`) is unique in all 9 datasets. |
| Exceptions (ID, severity, status, category, root cause, account, currency, dates, amount, affected results, flags, related records, cause category, evidence, evidence status and detail, review status, group ID) | **[C]** | `Validator.exceptions` (`_group_exceptions`, `_correlate_exceptions`); `exceptions.csv` |
| Investigation groups (ID, members, primary, size, link types, links with citations, status, review status, cause, correlation version) | **[C]** | `Validator.groups`; `investigation_groups.csv` |
| Candidate relationships (ID, members, basis, detail, label, evidence) | **[C]** | `Validator.candidates`; `candidate_relationships.csv` |
| Case status (`CLEAN` / `EVIDENCE_INCOMPLETE` / `EXCEPTIONS_OPEN`) | **[C]** | `case_status(v)` |
| Input file inventory with SHA-256, requirement, record count, reporting period | **[C]** | `manifest.csv` (`generate.write_manifest`; `prepare.prepare_case` for uploaded cases) |
| Scenario identity, baseline and baseline manifest hash | **[C]** | `scenario.json` (scenario datasets only; the baseline has none, so it is treated as "S01") |
| Intake decisions (accepted, rejected, duplicate, ambiguous, missing) | **[C]** | `intake.csv` (prepared cases only) |
| Source records with primary keys | **[C]** | `source_data/*.csv`; key = first column (`schema.columns(fid)[0]`), unique (tests) |
| Row citations `IN-xx:file#Lnn` and ranges `#La-Lb` | **[C]** | `Validator.ref()`; resolvable (`tools/verify_outputs.py` O1) |
| Reporting period | **[C]** | `schema.PERIOD_ID` (`PER-2026-09`), `PERIOD_START`/`PERIOD_END`; manifest `reporting_period` |
| Accounts, currencies, pool | **[C]** | `account_inventory.csv`; `schema.POOL_ID` |
| Reconciliation days | **[C]** | `recon_calendar_2026-09.csv` (`Validator.recon_days`) |
| Gated or missing evidence and its dependent checks | **[C]** | `Validator.state`; `schema.DEPENDS`; INSUFFICIENT_EVIDENCE results and their roots |
| Trace (record → citing results; exception or group → members) | **[C]** | `uc042lib/trace.py` |
| Human-readable report | **[C]** | `VALIDATION_REPORT.md` (`write_outputs`). A validation report, not an audit pack. |
| Output verification checks O1–O8 | **[C]** | `tools/verify_outputs.py` (reusable for pack validation) |
| **Control names** | **[G]** | Only codes (C01–C16, DQ…) exist. Names are in `docs/UC042_SOURCE_TO_CONTROL_MATRIX.md` text. |
| **Entity identifier** (`SYN-EMI-001`) | **[G]** | Only in `GENERATION_NOTES.md` text; no data field |
| **Processing run ID, engine version, generation timestamp** | **[G]** | None exist (validator output is deliberately timestamp-free) |
| **Structured C05 values** | **[G]** | `computed` is a formatted string (`"item A 260019.50; resource 260019.50"`) |
| **Settlement booking lag / timing status per batch** | **[G]** | In C11-BATCH-BANK note text only |
| **PDF key details** (letter references, policy point) | **[G]** | Parsed in `Validator.pdf` but not persisted |
| Aggregate totals (for example all settlements in a month, client totals) | Not produced | The engine computes no aggregates. **Not included** unless decided (§5). |

## 3. Canonical pack structure (JSON)

`pack.json` is the source of truth. Keys are sorted, money is a 2 dp **string**, and dates are ISO.

### A. Metadata

| Field | Tag | Source or rule |
| --- | --- | --- |
| `pack_id` | P | `PACK-{scenario_id}-{period_id}-{content_hash[:12]}` |
| `pack_schema_version` | P | `"uc042-pack/0.1"` |
| `reporting_period` | C | `{period_id, start, end}` from `schema` |
| `reconciliation_days` | C | Dates from IN-01 where `is_recon_day` |
| `entity_id` | G | `SYN-EMI-001`, as case configuration (decision D2) |
| `asset_pool_id` | C | `schema.POOL_ID` |
| `currency_scope` | C | Currencies of `RELEVANT_FUNDS_BANK` accounts in IN-02 |
| `accounts` | C | IN-02 rows (ID, class, currency, masked number, designation) with citations |
| `source_dataset` | C | `{dataset, scenario_id, baseline, baseline_manifest_sha256}` from `scenario.json` / folder name |
| `processing_run_id` | P/G | Deterministic hash of (input manifest SHA-256s + engine fingerprint + configuration fingerprint) |
| `generation_status` | P | `GENERATED` / `FAILED` (failure details in the generation record; no pack published) |
| `synthetic_notice` | C | `scenario.json` `synthetic_notice` / D6 text |
| `generated_at` | P | **Outside** the canonical content, in the generation record (§6, decision D5) |

### B. Executive summary (status dimensions kept separate)

| Field | Tag | Rule (counting and copying only) |
| --- | --- | --- |
| `evidence_completeness` | P from C | `COMPLETE` if no INSUFFICIENT_EVIDENCE result and no unavailable required file (`Validator.state`); else `INCOMPLETE` |
| `control_outcomes` | P from C | Counts of results by outcome, per check and in total; `ALL_PASSED_OR_NOT_APPLICABLE` or `FAILURES_PRESENT` |
| `exceptions` | P from C | `{total, by_severity, open}`. Every exception has `status` OPEN today. |
| `exception_review` | P from C | `NONE` if no exceptions; else `AWAITING_HUMAN_REVIEW` (count) |
| `investigation_groups` / `candidate_relationships` | P from C | Counts |
| `missing_evidence_items` | P from C | Count from register I |
| `engine_case_status` | C | `case_status(v)` |
| `pack_review_status` | P | `NOT_REVIEWED` (future approval capability) |

There is **no single "overall status"** that blends these dimensions (R3).

### C. Reconciliation summary (engine values only)

| Block | Rows | Fields (tag) |
| --- | --- | --- |
| `internal_by_currency_day` | Per (day, currency) | `requirement` = C04 `computed` (C); `requirement_reported` = C04 `reported` (C); `requirement_composition` = C04 `note` (C); `item_a`, `resource` (**G**: C05 composite string); `difference` = C06 `computed` (C); outcomes and citations (C) |
| `external_by_account_day` | Per (day, account) | `bank_balance` = C07 `computed` (C); `ledger_balance` = RC2 `computed` (C); `difference` = C08 `computed` (C); `difference_reported` (C); `evidence_status` (C); outcomes and citations (C) |
| `opening_positions` | Per account and currency | Source fields with citations: cash-book `OPENING_BALANCE` rows; first EOD opening balance; 31 Aug client snapshot rows (C). **No totals computed.** |
| `client_balances` | — | Represented by C04 (requirement and its composition note) and the CBAL results. Citations point to the snapshot rows. No client total is computed by the pack. |

### D. Control register

| Field | Tag | Source |
| --- | --- | --- |
| `check_id`, `control_code` | C | `results.check_id`, `results.control` |
| `control_name` | G | Registry built from the source-to-control matrix (decision D1) |
| `result_counts` | P | Counts by outcome |
| `results[]` | C | Every result: `result_id` (P) = `check_id\|scope`; `scope`, `outcome`, `computed`, `reported`, `evidence_status`, `note`, `evidence_refs`, `root_cause` (C) |
| `amount` | C | `computed` / `reported` exactly as output (no reformatting) |
| `related_exception_ids` | P | Via `root_cause` → exception (C) |
| `related_group_ids` | P | Via the exception's `investigation_group_id` (C) |
| `reporting_period` | C | Pack period; scope dates where the scope is dated |

### E. Evidence register

**Level 1: files** (all inputs).

| Field | Tag | Source |
| --- | --- | --- |
| `evidence_id` | C | Manifest `file_id` (IN-01 to IN-19) |
| `source_file`, `sha256`, `record_count`, `record_unit`, `requirement`, `evidence_kind`, `description` | C | Manifest |
| `availability` | P from C | `PRESENT` / `MISSING` / `EMPTY` / `UNUSABLE` / `AMBIGUOUS` / `WRONG_PERIOD` (`Validator.state`, intake) |
| `key_details` (PDFs) | G | `Validator.pdf` (not persisted today) |

**Level 2: cited records** (every row cited by any result, exception, group or candidate; 1,920 in the baseline). Ranges `#La-Lb` are expanded.

| Field | Tag | Source |
| --- | --- | --- |
| `evidence_id` | P | `{file_id}:{primary_key}` (key unique per file, tested) |
| `source_file`, `source_line`, `file_sha256` | C | Citation + manifest |
| `record_type` | C | File description (manifest) |
| `business_date` | P | The row's business-date field per `schema.PERIOD_RULES` (copied, not calculated) |
| `account_id`, `currency` | C | Row fields, where present |
| `associated_result_ids`, `associated_exception_ids` | P | Reverse index of citations |
| `availability` | P | `PRESENT` (cited rows exist by definition; missing items live in register I) |

### F. Settlement register (per batch in IN-12)

| Field | Tag | Source |
| --- | --- | --- |
| `batch_id`, `counterparty_type`, `settlement_date`, `account_id`, `currency`, `direction`, `gross_amount`, `total_fees`, `total_adjustments`, `net_amount_reported`, `expected_bank_reference` | C | IN-12 source row (copied) + citation |
| `lines_result`, `bank_result` | C | C11-BATCH-ARITH and C11-BATCH-BANK results (outcome, computed, reported, citations) |
| `bank_entry` | C | The IN-09 row cited by C11-BATCH-BANK |
| `booking_lag_business_days`, `timing_status` | G | Note text today; needs a structured field (decision D3) |
| `fee_top_up` | C | FUND-TOPUP result for the batch, where applicable |

### G. Exception register

All `exceptions.csv` fields **[C]**, unchanged, plus:

- `control_codes`: **[P]**, from the affected results' `control`;
- `affected_result_ids`: **[P]**, `check_id|scope` of results with the same `root_cause`.

Wording, amounts and currencies are copied exactly.

### H. Investigation-group register and candidate relationships

- **Groups:** all `investigation_groups.csv` fields **[C]**. Each carries the fixed statement "An investigation group links exceptions for review; it does not establish a cause."
- **Candidates:** all `candidate_relationships.csv` fields **[C]**, in a **separate** list, with the label kept verbatim ("UNVERIFIED — NOT EVIDENCE-BACKED").

### I. Missing evidence register

| Field | Tag | Source |
| --- | --- | --- |
| `item_id` | P | `MISS-{n}` in deterministic order |
| `expected_evidence` | C | Root cause (for example `MISSING_BANK_EVIDENCE\|SGA-EUR-01\|2026-09-15`, `MISSING_FILE\|IN-10`) or `V00-FILE` / intake row |
| `related_results` | C | INSUFFICIENT_EVIDENCE results with that root (check, scope, note, citations) |
| `related_controls` | P | Their control codes |
| `related_exception_id` | C | The exception with that root |
| `completeness_impact` | P | "Checks not assessable: …" (from those results); `evidence_completeness` = INCOMPLETE |
| `value_shown` | — | Always "not available". **Never zero.** |

### J. Audit trail and provenance

| Field | Tag | Source |
| --- | --- | --- |
| `inputs[]` | C | Manifest rows (file ID, path, SHA-256) + intake decisions where present |
| `baseline_manifest_sha256` | C | `scenario.json` |
| `engine_fingerprint` | G | SHA-256 of `uc042lib/*.py` (+ `correlation_version` (C)) |
| `configuration_fingerprint` | G | Hash of the period rules, `DEPENDS`, enums, conventions in `schema.py`, and case configuration |
| `processing_outputs` | P | SHA-256 of `control_results.csv`, `exceptions.csv`, `investigation_groups.csv` and `candidate_relationships.csv` from the same run |
| `pack_content_sha256` | P | Hash of canonical `pack.json` without `generated_at` |
| `review_events[]` | Future | Empty list; reserved for the approval capability |
| `narrative[]` | Future | Empty list; reserved for AI narrative (each entry must cite pack IDs) |

## 4. Immutability

- **Write-once location.** Each pack is written to `packs/<pack_id>/`, containing `pack.json`, `pack.html` and `generation_record.json`. An existing pack directory is never overwritten.
- **New inputs give a new pack.** Changed inputs, engine or configuration produce a different `processing_run_id` and `pack_id`, so a new pack is created. Earlier packs stay as they were.
- **Supersession.** `supersedes_pack_id` may be recorded for the same dataset and period (proposed; set only by an explicit user action later).

## 5. Gaps and decisions affecting the contract

| # | Gap or decision | Recommendation |
| --- | --- | --- |
| D1 | Control names | A static registry (`check_id` → name, description) built from the source-to-control matrix wording; marked as documentation-derived |
| D2 | Entity ID | Case configuration constant `SYN-EMI-001` (synthetic) |
| D3 | Structured fields missing (C05 item A/resource; batch booking lag and timing status; PDF key details) | Small **additive** engine change: structured fields alongside the existing ones, with no change to outcomes. The alternative is parsing note strings, which is not recommended. |
| D4 | Aggregates (settlement totals, client totals) | Exclude from v1. If wanted later, compute them in the engine as an explicit, tested output, not in the pack. |
| D5 | Generation timestamp versus reproducibility | Keep `generated_at` in `generation_record.json`, excluded from `pack_content_sha256` |
| D6 | Engine invocation | The assembler runs the existing `Validator` in process once per pack and writes that run's outputs beside the pack (see 02), so the pack never uses stale CSVs |
