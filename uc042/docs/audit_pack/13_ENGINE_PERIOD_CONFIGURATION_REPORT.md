# UC-042 — Removing the September 2026 hardcoding from the deterministic engine

Date: 3 November 2026. Scope: engine architecture and period handling only. No dataset, pack, investigation, closing
summary or final pack was generated or changed.

## A. September hardcoding found

| Location | Assumption |
|---|---|
| `uc042lib/schema.py` | `PERIOD_ID = "PER-2026-09"`; `PERIOD_START/END = 1–30 Sep 2026`; 12 file names with `_2026-09` (IN-01, IN-03…IN-14, IN-18); IN-19 named `_2026-08` and described as "(August)"; `PERIOD_RULES`: calendar must equal `PER-2026-09`, boundary rows literal `2026-08-31` / `2026-08-31T17:00:00+01:00` (fixed BST offset) for IN-03 and IN-10 |
| `uc042lib/structure.py` `check_period` | period range from `schema.PERIOD_START/END`; rules from `schema.PERIOD_RULES` |
| `uc042lib/validate.py` | bank holidays as a three-date list (31 Aug, 25 and 28 Dec 2026); `fname()` from September names; `PERIOD_START/END` in the timing window (E1), taint scoping, DQ-PERIOD wording, allocation timeliness and P1 conventions; result notes saying "September evidence"; C16 return due date from `date(2026, 8, 31)`; report text "31 Aug opening snapshot … every September day-pair" |
| `uc042lib/prepare.py` | canonical names and manifest `reporting_period` from September constants |
| `uc042lib/pack/assemble.py` | `load_sources` September file names; opening client snapshots matched on `"2026-08-31"`; `reporting_period` from September constants; descriptions of unavailable files |
| `uc042lib/pack/validate_pack.py` | September file names when resolving settlement and opening-position sources |
| `uc042lib/investigation/retrieval.py` (via `load_sources`), `uc042lib/trace.py` | September file names |
| `uc042app/services/monthly.py`, API router, React texts | Phase 4 guard: processing only `PER-2026-09`, other months `BLOCKED` |

Already period-neutral (unchanged): the reconciliation point (from the policy IN-17, applied with `zoneinfo`
Europe/London per instant), the reconciliation days (read from the supplied calendar IN-01), all calculations, matching,
exception grouping and correlation, pack identifiers (`PACK-<scenario>-<period>-<hash>` already carried the period).
Not changed on purpose: the dataset generator (`generate.py`, `scenarios.py`), which keeps producing the September
baseline and was not run.

## B. Files changed

Engine: `uc042lib/period.py` (new), `uc042lib/continuity.py` (new), `schema.py` (comments only), `structure.py`,
`validate.py`, `prepare.py`, `trace.py`, `pack/assemble.py`, `pack/generate.py`, `pack/validate_pack.py`,
`pack/config.py` (`period.py` added to the engine fingerprint), `investigation/retrieval.py`.
Backend: `uc042app/services/monthly.py`, `uc042app/ingest/analysis.py`, `uc042app/api/routers/monthly.py` (no API
contract change). Frontend: two texts in `DashboardPage.tsx` and `UploadPage.tsx` (no design change).
Tests: `tests/test_period_config.py` (new, 27 tests); `tests/test_api_monthly.py` (the Phase 4 test that asserted the
old BLOCKED behaviour was replaced by tests of the new behaviour); `frontend/src/test/archive.test.tsx` (same reason).
No existing engine test, golden snapshot or dataset was changed.

## C. PeriodConfig

`PeriodConfig(year, month)` — a frozen dataclass, hashable, no mutable state; `PeriodConfig.from_id("PER-YYYY-MM")`.
It derives: `period_id`, `token` (YYYY-MM), `start`, `end`, `days`, `month_name`, `label`, `timezone`
(Europe/London), `previous`/`next`, `previous_end`, `opening_point()` (previous month-end 17:00 London, DST-aware),
`filename(fid)` and `csv_files`/`pdf_files` (same shape as `schema.CSV_FILES`/`PDF_FILES`), `requirement(fid)`,
`required_ids`/`optional_ids`, `period_rules` (schema rules with the month's values), `expected_calendar()` and
`calendar_findings(rows)`. `BASELINE = PeriodConfig(2026, 9)` equals the schema constants exactly (tested).

The period is passed explicitly: `Validator(case, period)`, `prepare_case(input, case, period)`,
`assemble/build/generate(case, period)`, `load_sources(case, period)`. When a caller does not pass it (existing tests,
CLI), the period is **resolved from the case itself** (`uc042lib.period.resolve`): the intake manifest, else the month in
the canonical file names, else the calendar's `period_id`. If none or more than one period is declared, the engine
refuses (`PeriodError`); there is no default month. An explicit period that conflicts with the case's manifest is
refused. `prepare_case` without a period takes the one period declared by the identified calendar, else refuses.

## D. Period-aware source files

File names come from `period.FILE_PATTERNS` (`recon_calendar_{period}.csv`, …, `rep027_submission_receipt_{previous}.pdf`;
standing documents carry no month). The IN-01…IN-19 contract is unchanged; requirements (REQUIRED / OPTIONAL) are the
same for every month. Manifest hashes are verified as before. A canonical file of **another** month inside a case is
reported (`V00-FILE` FAIL "file for another reporting period present; not used") and never read; the month's own file is
then missing and stays missing (`INSUFFICIENT_EVIDENCE`). A file whose rows all fall outside the month is `WRONG_PERIOD`
(as before). No September file or record is ever used for another month.

## E. Calendar and timezone

England and Wales bank holidays are computed for any year (Easter algorithm, early May, spring and summer Mondays,
Christmas/Boxing Day/New Year substitutes); 2026 and 2027 lists are tested. `business_day_after` works across years and
holidays (e.g. 2 Apr 2026 → 7 Apr). 28/29/30/31-day months and leap years (Feb 2028, 2100) are tested. All instants
use `zoneinfo` Europe/London: boundary points are `+00:00` in winter and `+01:00` in summer (tested around the
29 March and 25 October 2026 changes); a wrong offset is a different instant and is not accepted as the boundary. The
supplied calendar (IN-01) stays the record of reconciliation days; at upload it is compared with the month (missing or
duplicate dates, reconciliation on a weekend or bank holiday → warnings; a business day marked not reconciled →
information). Date types stay distinct as before (only the deciding field per evidence type is period-judged).

## F. Document applicability

* Policy (IN-17): a policy whose effective date is after the period end is not applied (`V01-PDF` FAIL, file unusable;
  the policy-dependent checks report insufficient evidence). It is never substituted to force a result. Example
  (tested): the illustrative policy v1.2 (effective 2026-05-07) is not applied to April 2026 and is applied to June.
* Return receipt (IN-19): must be for the previous month; the due date is 15 business days after the previous
  month-end. A receipt for another month fails C16-RETURN with the reason.
* Governance register (IN-18): responsibility allocated only after the period end fails C16-GOVERNANCE.
* Acknowledgement letters (IN-15/16): a letter dated after the period end does not evidence it (C10 FAIL).
* Standing documents (inventory, letters, policy) may recur unchanged across months; at upload they are flagged
  `RECURRING_DOCUMENT` (information).
* Optional documents (IN-18, IN-19) never block; missing required evidence stays missing.
  These checks emit nothing new when the document applies, so September results are unchanged.

## G. Financial continuity

`uc042lib.continuity.compare(previous_case, current_case)` compares, by key: bank (each account, safeguarding and own
funds: last statement closing vs first statement opening), cash book (each safeguarding account: the previous period's
position at the opening point, with the engine's own ledger function, vs the OPENING_BALANCE row), client balances
(client and currency, snapshot at the previous month-end point) and unallocated receipts (receipts open at the boundary
in both registers). Each item is MATCH, DIFFERENCE (with the difference, never adjusted) or NOT_VERIFIABLE (with the
reason). Views are never compared with each other. Without a previous period, the report is NOT_VERIFIABLE; periods
must be consecutive. The backend stores the report in each successful run's result (`result.continuity`), using the
previous period's latest successful run; it never changes the engine result.

## H. PostgreSQL and FastAPI integration

The processing job passes `PeriodConfig(period)` to `prepare_case` and `build` (tested by observing the calls). The
`BLOCKED` path was removed; `processing_supported` is true for every valid period and `processing_limitation` is null
(the API contract is unchanged). Case folders are keyed by period and document set. Upload validation labels evidence
for the month (October's IN-19 is "(September)") and checks the calendar. No business logic was added to FastAPI.

## I. September regression

* Golden snapshots, scenario answer keys, engine, hardening, period and pack tests: all pass unchanged (175 tests).
* All nine September packs were rebuilt in memory and compared with the stored packs: the canonical content and all
  processing outputs are **identical**. Only the five fields derived from the engine's source code differ —
  `engine_fingerprint`, `pack_layer_fingerprint`, `processing_run_id`, `pack_content_sha256`, `pack_id` — because the
  fingerprints hash the engine and pack-layer source files by design (no silent engine change). This is the one
  unavoidable serialization difference: a September pack regenerated now would get a new pack ID. **No stored pack was
  rewritten**; the nine published packs keep their IDs and hashes and still verify.

## J. New test results

| Suite | Result |
|---|---|
| Backend, full | 477 run, OK (1 skipped, pre-existing) |
| `tests/test_period_config.py` | 27 OK: Jan–Nov 2026 configurations, invalid periods, leap years, day counts, DST offsets, bank holidays, reconciliation days, calendar findings, period-specific file names, missing / wrong-period / other-period files, case resolution and mixing, policy effective dates, return-receipt period, optional vs missing, period-specific pack IDs, periods in sequence, no shared mutable state, continuity (match, difference, not verifiable, non-consecutive), the nine September scenarios through PeriodConfig |
| Monthly API + DB on PostgreSQL | 39 OK |
| Frontend | 23 passed (2 live tests skipped); production build OK; contract check OK |

## K. Protected-file integrity (SHA-256)

Compared with the snapshot taken before this task: changed only the engine files listed in B
(`uc042lib/*.py`, `uc042lib/pack/*.py`); added `uc042lib/period.py` and `uc042lib/continuity.py`; nothing missing.
Unchanged: all datasets (`uc042_dataset/`), all nine packs (`packs/`), golden snapshots, existing engine tests, tools.
All investigation artefacts (including `_not_published`): unchanged. No `app_state/`, `final_packs/` or
`document_store/` in the project.

## L. Remaining limitations

* No real month other than September has been processed: there is no data for it yet. Full monthly execution is the next
  task, with the separately generated dataset package.
* One-off proclaimed bank holidays are not modelled (the supplied calendar remains authoritative for reconciliation days).
* The opening boundary point is 17:00 London (the policy's point in the baseline). A policy with a different point
  would need the boundary point taken from that period's policy.
* Continuity compares the views available in the source files; own-funds cash-book positions are not modelled by the
  engine and are compared through bank statements only.
* Regenerating a September pack yields new code-derived identifiers (section I); published packs are unaffected.

## M. Confirmation

No January–August dataset, substitute dataset, reconciliation pack, AI investigation, closing summary or final audit pack
was generated. September datasets, packs, golden snapshots and investigation artefacts were not modified. The test
fixtures are small synthetic configuration fixtures created inside the tests (calendars generated from the period, a
few hand-written rows for the continuity comparison).

## N. Non-September processing

Non-September processing is now supported by the configurable engine, subject to valid period-specific input data: the
same engine, rules and calculations run for any `PER-YYYY-MM`, with that month's files, calendar, boundary records,
document applicability and identifiers. It has not yet been exercised end to end on a real non-September dataset.
