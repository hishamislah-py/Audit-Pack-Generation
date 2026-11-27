# UC-042 Audit Pack POC — clean synthetic baseline and two demo scenarios

All data here is **synthetic**. It describes no real firm, bank, client or account, and is not a Moorwand format.

## Run it (Python 3.11, dependencies in `requirements-dev.txt`)

Windows (PowerShell), from the `uc042` folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt        # pypdf, reportlab, tzdata, pypdfium2, httpx + requirements-api.txt (fastapi, uvicorn) + requirements-ai.txt
python -m unittest                         # 409 tests, offline (1 opt-in live test skipped; no API key needed)
```

> **Do not run** `uc042lib.generate`, `uc042lib.scenarios` or `uc042lib.validate` against the delivered data: they regenerate or write into the dataset folders (see `CLAUDE_CODE_HANDOFF.md` §15).

```bash
python -m uc042lib.generate      # regenerate the clean baseline (deterministic; same bytes every time)
python -m uc042lib.scenarios     # build the scenarios from the baseline (baseline never modified)
python -m uc042lib.validate                                                  # validate the baseline
python -m uc042lib.validate uc042_dataset/scn_S02_missing_eur_statement      # validate a scenario
python tools/verify_datasets.py  # independent verification of every scenario dataset (no shared code with the engine)
python tools/verify_outputs.py   # checks generated outputs, report and trace against the source data (run validate first)
python -m uc042lib.pack.generate uc042_dataset/set_01_clean_baseline   # audit pack -> packs/<pack_id>/pack.json + pack.html (write-once)
python -m uc042lib.trace EXC-S05-01 --set uc042_dataset/scn_S05_unexplained_gbp_difference
```

## Backend API (local FastAPI POC) and monthly document archive

The `uc042app/` package is a local, single-analyst FastAPI backend that calls the existing libraries directly. It has no
authentication, is bound to 127.0.0.1, and runs as one process. With `UC042_DATABASE_URL` set (Phase 4), application
state and the monthly archive (periods, upload batches, source documents, processing runs, activity) are in PostgreSQL;
without it, state stays in files under `UC042_APP_STATE_DIR` and the monthly features are unavailable. Packs,
investigations and final packs always stay write-once files. PostgreSQL setup (no administrator rights), migrations,
upload API, date and duplicate checks and the engine's September-only limitation:
`docs/audit_pack/11_PHASE4_MONTHLY_DOCUMENTS.md`. Phase 2 details: `docs/audit_pack/08_PHASE2_BACKEND_IMPLEMENTATION_REPORT.md`.

```powershell
python -m pip install -r requirements-api.txt
python -m uc042app.admin db-upgrade                     # create / migrate the PostgreSQL schema
python -m uc042app.admin import-legacy-investigations   # one-time: register existing published investigations (baseline)
python -m uc042app.admin import-poc-scenarios           # optional: register the September scenario documents (read-only)
python -m uc042app                                      # http://127.0.0.1:8000/docs
```

**Published final packs are stored outside the repository.** Set `UC042_FINAL_PACKS_ROOT` to an absolute, backed-up
directory (default: `%LOCALAPPDATA%\UC042\final_packs`); the backend refuses a location inside the source tree.
Historical-demo packs stay in `demo_history/final_packs`. Final packs with analyst reviews (schema 1.1) render their PDF
with the Unicode renderer and the bundled DejaVu fonts (`uc042lib/final_pack/fonts`, licence included); optional fallback
fonts for other scripts go in `UC042_PDF_FALLBACK_FONTS`. Text no configured font can draw blocks the preview and GENERATE
instead of being substituted. Earlier packs keep re-rendering, and verifying, with the renderer they were published with.

## Frontend (React + TypeScript + Vite)

`uc042/frontend/` is the analyst UI. It uses the backend API by default (`VITE_API_BASE_URL`); mock data is available
only in the dev server with `VITE_DATA_SOURCE=mock` and never in a production build. Start the backend, then:

```powershell
cd frontend; npm install; npm run dev        # http://127.0.0.1:5173  (tests: npm test; build: npm run build)
```

See `frontend/README.md`, `docs/audit_pack/09_PHASE3_REACT_FRONTEND_IMPLEMENTATION_REPORT.md` and
`docs/audit_pack/10_FRONTEND_ENTERPRISE_DESIGN_REPORT.md`.

## AI investigation (OpenAI by default)

Configuration lives in `uc042/.env` (git-ignored; copy `.env.example`). It is loaded automatically, and variables already
set in the process environment take precedence.

| Variable | Default | Meaning |
| --- | --- | --- |
| `UC042_LLM_PROVIDER` | `openai` | `openai` (live), `anthropic` (live, legacy adapter) or `offline` (SIMULATED, tests only) |
| `UC042_LLM_MODEL` | `gpt-6-luna` (openai) | Any model your account can use |
| `UC042_LLM_TIMEOUT_SECONDS` | `120` | Per provider request |
| `UC042_LLM_TOTAL_TIMEOUT_SECONDS` | `300` | Wall-clock budget for one investigation's model calls |
| `UC042_LLM_MAX_TOKENS` | `8000` | `max_output_tokens` (reasoning tokens count towards it) |
| `UC042_OPENAI_REASONING_EFFORT` | unset | Optional `none`…`max`; sent only when set |
| `UC042_INVESTIGATION_MODE` | `fixed` | `fixed` (V1) or `tools` (V2 bounded tool calling) |
| `OPENAI_API_KEY` | — | Required for live OpenAI runs. Never commit it; it is never printed or logged |

```powershell
python -m uc042lib.investigation.run --check-provider                                   # authenticate + model lookup, no tokens
python -m uc042lib.investigation.run PACK-SC2-PER-2026-09-aaca8a8b7194 EXC-SC2-01         # one live investigation -> investigations/
$env:UC042_LLM_PROVIDER="offline"; python -m uc042lib.investigation.run <pack_id>       # SIMULATED output, testing only
```

**V2 tool calling** (`UC042_INVESTIGATION_MODE=tools` or `--mode tools`, OpenAI only): inside the same LangGraph
workflow, the model may request 8 read-only evidence tools that Python validates and executes, within budgets (8 calls,
4 rounds, 25 records per call, 160 records, 300 s). Results add `evidence_ledger.json` and `tool_calls.json`. Details:
`docs/ai_investigation/02_AI_INVESTIGATION_V2_TOOL_CALLING_REPORT.md`.

```powershell
python -m uc042lib.investigation.run PACK-SC2-PER-2026-09-aaca8a8b7194 EXC-SC2-01 --mode tools
```

Each result records `model_metadata.provider`, `model`, `simulated` (true only for offline/test doubles), token usage and
the provider response ID. A live result has `simulated: false`; a simulated summary starts with "SIMULATED OFFLINE OUTPUT".
Investigation never changes an exception's status (`exception_resolution: NOT_RESOLVED_BY_INVESTIGATION`).

`validate` exits 0 when the results match the dataset's `answer_key.json`. Each dataset has an answer key; the baseline's expects no failures.
It also prints a **case status**:

- `CLEAN`: all evidence is available and every check passed or was not applicable.
- `EVIDENCE_INCOMPLETE`: a required file is missing, empty, unusable or ambiguous, or some check lacks evidence.
- `EXCEPTIONS_OPEN`: evidence is complete but at least one check failed.

## Validate your own evidence (no generator needed)

```bash
python -m uc042lib.prepare path/to/inbox cases/my_case    # identify files by content, hash them, write the manifest
python -m uc042lib.validate cases/my_case
```

`prepare` copies every recognised file, byte for byte, to its canonical path. It records every decision in `intake.csv`:

| Decision | Meaning |
| --- | --- |
| `ACCEPTED` | Identified and copied |
| `DUPLICATE` | Same SHA-256 as an earlier file; not copied |
| `REJECTED` | Not a supported evidence type: unknown CSV header, not UTF-8, XLSX, non-evidence PDF |
| `AMBIGUOUS` | Two different files claim the same slot; neither is used |
| `MISSING` | A required type was not supplied |

Identification is by **content only**:

- **CSV:** the exact header row matches one schema file.
- **PDF:** the text contains every key-details label of one supporting document type. Acknowledgement letters are matched to an account through the letter reference in the account inventory.

File names and any manifest in the inbox are never trusted. The manifest `prepare` writes is case metadata (identity, hash, counts), not proof of validity: `validate` checks every file's content itself and also runs without a manifest.

## The scenario datasets

> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions, not confirmed Moorwand practice.

All are built from `set_01_clean_baseline` by `python -m uc042lib.scenarios`; the baseline is never modified. Index: `uc042_dataset/SCENARIO_INDEX.md`. Full report: `docs/dataset_gap_closure/06_DATASET_ENRICHMENT_IMPLEMENTATION_REPORT.md`.

| Scenario | Dataset | Expected result |
| --- | --- | --- |
| 1 Clean audit pack | `set_01_clean_baseline` (includes the 31 Aug opening client snapshot, D4) | No exceptions |
| 2 Settlement timing difference | `scn_SC2_settlement_timing` | 15 Sep difference +2,868.50 stays FAIL and OPEN, evidence status `TIMING_EVIDENCED` (clearing entry on 16 Sep) |
| 3a Supported fee | baseline batch `AQ-GBP-20260908` | All fee checks pass |
| 3b Fee not itemised | `scn_SC3B_fee_not_itemised` | Batch arithmetic fails; fee partially supported |
| 3c Short settlement | `scn_SC3C_short_settlement` | −4.50 unexplained (`NOT_EVIDENCED`) for 17 days; 3 exceptions in investigation group `GRP-SC3C-01` |
| 4 Missing evidence | `scn_S02_missing_eur_statement` | 13 INSUFFICIENT_EVIDENCE; `EXC-S02-01` |
| 5a / 5c / 5d Customer mismatch | `scn_SC5A_…`, `scn_SC5C_…`, `scn_SC5D_…` | 5a: 2 exceptions, no confirmed group, one UNVERIFIED candidate; 5c and 5d: one investigation group each |
| 6 £812.40 unexplained | `scn_S05_unexplained_gbp_difference` | `EXC-S05-01`, `EXC-S05-02`; unresolved |

Each scenario folder has `mutations.json`, `answer_key.json` (current-engine expectations, intended `target_outcome`, `engine_limitations`), `scenario.json` (baseline provenance) and `SCENARIO_NOTES.md`.

## What is where

| Path | Contents |
| --- | --- |
| `docs/` | Phase 1 specification. Milestone-1 decisions are in section 0 of `UC042_INPUT_EVIDENCE_SPEC_V1.md`. |
| `uc042_dataset/set_01_clean_baseline/source_data/` | 14 monthly CSV inputs (IN-01 to IN-14) |
| `uc042_dataset/set_01_clean_baseline/supporting_documents/` | 5 genuine PDFs (IN-15 to IN-19; IN-18 and IN-19 are optional) |
| `.../manifest.csv` | Every input file with its requirement, row or page count and SHA-256 |
| `.../DATA_DICTIONARY.md` | Columns, types and sign rules |
| `.../GENERATION_NOTES.md` | How the data is generated and the conventions used |
| `.../VALIDATION_REPORT.md`, `.../validation/control_results.csv`, `exceptions.csv`, `investigation_groups.csv`, `candidate_relationships.csv` | Validator output: one row per check and scope with `file#Lline` citations; one exception per root cause (with evidence status, review status and group ID); evidence-linked investigation groups; unverified candidate relationships |
| `uc042lib/` | `money.py` (sign rules), `schema.py` (file contract, enums, dependencies), `structure.py` (row rules), `prepare.py` (case intake), `generate.py`, `scenarios.py`, `validate.py`, `trace.py` |
| `tests/test_baseline.py` | Sign rules, determinism, clean pass, and six tests that break a temporary copy to prove each check can fail |
| `tests/test_hardening.py`, `tests/test_period_and_headers.py`, `tests/test_period_decisions.py`, `tests/golden/` | Golden regression for the three datasets; malformed rows; missing, empty, unusable and ambiguous evidence; case preparation |

## How to read a finding

Each row in `control_results.csv` has:

- `outcome`: PASS, FAIL, INSUFFICIENT_EVIDENCE or NOT_APPLICABLE;
- `computed`: the validator's own value;
- `reported`: the firm's stated value, where one exists;
- `evidence`: the source rows, as `IN-xx:file.csv#L<line>`. Line numbers count the header as line 1.

Open the file at that line to see the record.

## How validation handles bad or missing evidence

1. **Structure first.** Every row is checked before any calculation, by `uc042lib/structure.py` (the one place for these rules). Checks cover:
    - required fields and conditional requiredness;
    - types: amounts, dates, timestamps, identifiers, integers, booleans and currencies;
    - enum values: debit/credit codes, batch directions, entry and transaction types;
    - the number of fields per row;
    - duplicate keys.

   An invalid row is **excluded from all calculations**. It is reported as a `DQ-FIELD` result with file, line, field, raw value and error. Nothing is converted, defaulted or set to zero.
2. **Format rule for amounts.** Exactly 2 decimal places, `.` as the decimal separator, and nothing else: `1000.00`.
    - Rejected: thousands separators (`1,000.00`), decimal commas (`1000,00`), signs on unsigned amounts, currency symbols, spaces and scientific notation.
    - A thousands comma is ambiguous with a European decimal comma, so exports must be normalised before upload.
    - Dates are `YYYY-MM-DD`. Timestamps are ISO 8601 with an explicit offset.
3. **Scope of an excluded row.** Any scope the row could have affected returns `INSUFFICIENT_EVIDENCE`, for example its statement's arithmetic, its account's ledger from its date onward, or its batch. The scope is worked out from the row's own valid fields: account, currency, date, batch, client and references. Where one of those fields is itself unreadable, every scope it might touch is treated as affected. This is deliberately conservative.
4. **Scope-defining files.** An invalid row in the calendar (IN-01) or account inventory (IN-02) makes that whole file unusable. A partial calendar or account list would silently shrink what is checked.
5. **Evidence gate.** `schema.DEPENDS` lists the files each check needs, taken from `docs/UC042_SOURCE_TO_CONTROL_MATRIX.md`. If any is missing, empty, unusable or ambiguous, the check is not run and returns **one** `INSUFFICIENT_EVIDENCE` result. Checks with their own evidence keep running.
6. **One exception per root cause.** The root causes are `MISSING_FILE`, `EMPTY_FILE`, `INVALID_FILE`, `AMBIGUOUS_FILE` and `INVALID_ROWS` (one per file), plus the existing reconciliation causes. A missing file is one exception that lists the checks it blocked, not hundreds.

7. **Reporting period (one month per case, `uc042lib.period.PeriodConfig`; September 2026 is the baseline dataset).** Rows outside the period are excluded (`DQ-PERIOD`, root cause `OUT_OF_PERIOD_ROWS`). A file with no row in the month is one `WRONG_PERIOD` exception. The opening positions at the previous month-end 17:00 point (Europe/London) are the permitted boundary records. Rules: `docs/UC042_PERIOD_AND_HEADER_RULES.md`.
8. **Headers stay exact.** A rejected CSV is explained in `intake.csv`: likely type, missing, extra and misordered columns, and the expected and received headers. Near matches are never accepted.

## Design rules this milestone enforces

- **Reported values are never trusted.** Requirement, resource, item A, ledger and bank balances are recomputed from other source files.
- **Links come from identifiers and references, never matching amounts.**
- **Missing evidence gives INSUFFICIENT_EVIDENCE**, never zero and never PASS.
- **Every comparison stays in one currency.** There is no FX conversion.
- **One exception per root cause.** Each failing or insufficient-evidence result belongs to exactly one exception.
- **Evidence status, grouping and review are separate.** A timing-evidenced difference stays FAIL and OPEN (`TIMING_EVIDENCED`, awaiting human confirmation). Investigation groups link exceptions only through references, persistence or lineage; they never set a cause or close anything. Date-and-amount coincidences are only recorded as UNVERIFIED candidates.
- **No cause is ever set without evidence.**

## Counting convention

CSV counts are **data rows, header excluded**. The baseline has 14 CSV files with 1,952 data rows (1,940 September rows plus 12 opening client snapshot rows) and 5 PDFs.

## Known limitations (synthetic POC)

These are documented in the reports and docs. They are not hidden.

- **Same simulation.** The reported reconciliation values and the source records come from one simulation. Validation proves the files are consistent with each other, not that the figures are operationally true or that any firm complies.
- **Transaction timing.** A synthetic convention (spec section 0, D8): card loads credit the client at load; spends and refunds change the balance at 15:00 scheme settlement; redemptions debit at bank execution.
- **Resource items B–D** are taken as reported (all 0.00). No independent source exists.
- **D+1 comparison** is excluded by convention: all relevant funds are modelled in relevant-funds bank accounts. Whether this holds for acquirer-routed card loads is open (gap G-R05).
- **PDFs** use fixed synthetic layouts. Key details are parsed from `Label: value` lines, and no human confirmation of extracted fields is modelled.
- **Not assessed:** own-funds opening balances.
- **Engine limits for real-world input (hardening phase):**
    - only UTF-8 CSV and the fixed synthetic PDF layouts are supported (no XLSX, OCR or bank or scheme formats);
    - a row with an unreadable account or date taints every scope it might touch, which can mark many results insufficient;
    - no general date-order check (DQ03); period decisions A1/A2 (conventions P1, P2) and unchecked fields A3–A5 are in `docs/UC042_PERIOD_AND_HEADER_RULES.md`;
    - cross-file conflicts other than duplicate references are not detected (DQ13);
    - the synthetic conventions remain hard-coded: the `TOPUP-<ccy>-<date>` reference pattern, the holiday list, and account letter slots;
    - `prepare` identifies files but does not merge several files of one type (for example daily statements); more than one becomes `AMBIGUOUS`.
