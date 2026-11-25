# UC-042 — Claude Code Handoff

Prepared 2 Nov 2026 from the verified Claude Web project state. Everything below was checked against the files in this package.

> **Synthetic POC.** All data is illustrative synthetic data, not Moorwand data or practice. Nothing here is a compliance opinion.

> ## ⚠️ Developer warning: keep test answers away from the AI runtime
> This package contains **test and developer-only material that reveals the planted answer for each scenario**:
>
> - `uc042_dataset/*/answer_key.json`
> - `uc042_dataset/*/mutations.json`
> - `uc042_dataset/*/SCENARIO_NOTES.md`
> - `uc042_dataset/*/scenario.json` (its `name` describes the scenario)
> - `uc042_dataset/SCENARIO_INDEX.md`, `scenario_index.json`
> - `tests/` (including `tests/golden/`)
> - `docs/dataset_gap_closure/06_*`, and dataset folder names such as `scn_SC5C_refund_double_posted`
>
> They are needed for regression tests and engine/pack generation. **They must never enter the LLM's investigation context, tool results or prompts.** V1 enforces this in `uc042lib/investigation/config.py` (`FORBIDDEN_NAMES`, `FORBIDDEN_DIR_PARTS`) and `retrieval.py` (`_inside`), and tests assert it. **Every new V2 tool must go through the same guarded retrieval layer.**

## 1. Project objective

UC-042 is an **Audit Pack Generation Assistant** for an e-money institution's safeguarding reconciliations (Hypothesis 2 in `docs/context/Moorwand_Hypothesis_2_Audit_Pack_Generation.md`). The intended workflow:

1. deterministic reconciliation;
2. deterministic audit pack;
3. AI investigation of identified exceptions;
4. validated findings;
5. a new versioned final pack;
6. human compliance review.

Steps 1–4 exist. Step 5 and later are future work.

## 2. Existing architecture

```text
uc042_dataset/<case>/source_data (14 CSV) + supporting_documents (5 PDF) + manifest.csv
        │  read-only
        ▼
uc042lib/validate.py  ── deterministic engine: controls, E1 timing evidence, exceptions, E2 investigation groups
        │  in-process (never the CLI)
        ▼
uc042lib/pack/        ── deterministic audit pack: packs/<pack_id>/pack.json (+ pack.html, processing/, generations/) — write-once
        │  read-only (hash-verified)
        ▼
uc042lib/investigation/ ── AI investigation V1 (LangGraph) → investigations/<pack_id>/<exception_id>/<INV-…>/ — write-once, separate
```

The engine and pack layers use only the standard library plus `pypdf`. Each layer only reads the one before it.

## 3. Directory structure (this package)

| Path | Contents |
| --- | --- |
| `uc042lib/` | Engine and support. **Engine:** `schema.py` (file contract, enums, period rules, `DEPENDS`), `structure.py` (row, header and period checks), `money.py`, `validate.py`. **Data generation:** `generate.py` (baseline), `scenarios.py` (8 scenario datasets). **Utilities:** `prepare.py` (identify uploaded files), `trace.py` (trace any record, exception, group or candidate ID). |
| `uc042lib/pack/` | Audit-pack layer: `config`, `registry` (control names), `model`, `assemble`, `validate_pack`, `render_html`, `generate` |
| `uc042lib/investigation/` | AI investigation V1: `config`, `models`, `retrieval`, `routing`, `packet`, `prompts`, `llm`, `validation`, `persistence`, `graph`, `run` |
| `uc042_dataset/` | 9 dataset folders (baseline + 8 scenarios), `scenario_index.json`, `SCENARIO_INDEX.md` |
| `packs/` | 9 immutable deterministic packs |
| `tests/` | Test files (409 tests, incl. 6 backend `test_api_*` modules) + `final_pack_support.py` / `api_support.py` helpers, `tests/golden/` (9 engine snapshots + README) |
| `uc042lib/final_pack/` | Final audit-pack library (Phase 1): snapshot, AI closing summary, assembly, validation, HTML/PDF, write-once publication to `final_packs/`. See `docs/audit_pack/06` (spec) and `07` (implementation). |
| `uc042app/` | Local FastAPI backend (Phase 2): routers, services, file-backed repositories, job runner, investigation publication registry, registry CLI. No authentication; 127.0.0.1 only; one process (`python -m uc042app`). Application state lives in `UC042_APP_STATE_DIR` (never inside `packs/`, `investigations/` or `final_packs/`). See `docs/audit_pack/08`. |
| `frontend/` | React + TypeScript + Vite analyst UI (Phase 3 baseline) for the local backend: `npm run dev` (127.0.0.1:5173), `npm test`, `npm run build`. Design tokens in `src/styles/tokens.css`. See `frontend/README.md` and `docs/audit_pack/09`. |
| `tools/` | `verify_datasets.py` (independent dataset verifier), `verify_outputs.py` (generated-output verifier) |
| `docs/` | Specs and implementation reports (§16a) |
| `requirements-ai.txt`, `requirements-api.txt`, `requirements-dev.txt`, `.env.example`, `.gitignore` | Dependencies, configuration template (copy to the git-ignored `.env`) |
| `README.md` | Project overview and engine rules |

**Each dataset folder** contains:

- `source_data/` (14 CSV) and `supporting_documents/` (5 PDF);
- `manifest.csv` (SHA-256 per file);
- `DATA_DICTIONARY.md`, `GENERATION_NOTES.md`;
- `answer_key.json` (test-only);
- `validation/`: `control_results.csv`, `exceptions.csv`, `investigation_groups.csv`, `candidate_relationships.csv`, `document_details.csv`;
- `VALIDATION_REPORT.md`.

Scenario folders also hold `scenario.json`, `mutations.json` and `SCENARIO_NOTES.md`.

| Dataset | Scenario | Exceptions |
| --- | --- | --- |
| `set_01_clean_baseline` | 1 clean (and 3a supported fee) | 0 |
| `scn_SC2_settlement_timing` | 2 timing £2,868.50 | 1 |
| `scn_SC3B_fee_not_itemised` | 3b | 1 |
| `scn_SC3C_short_settlement` | 3c £4.50 | 3 (1 group) |
| `scn_S02_missing_eur_statement` | 4 missing EUR evidence | 1 |
| `scn_SC5A_missing_transaction` | 5a £443.55 | 2 + 1 unverified candidate |
| `scn_SC5C_refund_double_posted` | 5c refund in client ledger | 17 (1 group) |
| `scn_SC5D_closing_snapshot_mismatch` | 5d £250 | 3 (1 group) |
| `scn_S05_unexplained_gbp_difference` | 6 £812.40 | 2 (1 group) |

## 4. Deterministic engine

`uc042lib/validate.py`, `Validator(case_dir).run()`. The run is in memory and writes nothing.

- **Pipeline:** load and SHA-256 check → structure → period (September 2026, with documented 31 Aug opening rows) → evidence gate (`schema.DEPENDS`) → 32 check types → exceptions (one per root cause) → E2 correlation.
- **Results:** `check_id, control, scope, outcome (PASS/FAIL/INSUFFICIENT_EVIDENCE/NOT_APPLICABLE), computed, reported, evidence (file#Lnn citations), note, root_cause, evidence_status, structured`.
- **E1:** timing evidence on C08 (one business day). Evidence statuses: `TIMING_EVIDENCED`, `TIMING_PARTIAL`, `NOT_EVIDENCED`, `TIMING_UNVERIFIABLE`. C08 stays FAIL and the exception stays OPEN.
- **E2:** investigation groups through L1 reference, L2 persistence and L3 lineage links. Date/amount coincidences are recorded only as UNVERIFIED candidate relationships.

Exceptions are always `status OPEN`, `review_status AWAITING_HUMAN_REVIEW`, with no cause. Money is `Decimal`; there are no floats. Details: `docs/processing_engine/02_E1_E2_IMPLEMENTATION_AND_VERIFICATION_REPORT.md`, `README.md`.

## 5. Audit-pack implementation

`python -m uc042lib.pack.generate <dataset_dir>` runs the engine once and assembles `pack.json`, which is canonical, deterministic and the source of truth.

**Sections:**

- `metadata`, `executive_summary`;
- `reconciliation_summary`, `control_register`, `settlement_register`;
- `evidence_register` (files plus cited-record pointers `IN-xx:<primary key>` → file and line);
- `exception_register`, `investigation_group_register` (groups, plus candidates kept separate);
- `missing_evidence_register`;
- `audit_trail` (input hashes; engine, configuration and pack-layer fingerprints; output hashes; `review_events: []`; `narrative: []`);
- `statements`.

**Separate statuses:** generation, evidence completeness, control outcomes, exception review, pack review.

**Identity and immutability:** `pack_id = PACK-<scenario>-PER-2026-09-<content hash[:12]>`. Publishing is write-once and timestamps live only in `generations/`. **Never edit a pack**; a changed pack fails hash verification in the investigation layer.

Details: `docs/audit_pack/01`–`05`.

## 6. AI Investigation Layer V1

A fixed LangGraph `StateGraph` controls the sequence. Python retrieves the evidence and builds a scoped packet. In **fixed mode (V1, default)** the LLM is called **once, with no tools**, in `ai_investigation`. In **tools mode (V2, `UC042_INVESTIGATION_MODE=tools`)** `ai_investigation` runs a nested LangGraph subgraph (`tool_loop.py`) in which the model may request 8 read-only evidence tools (`tools.py`). Python validates and executes each request through `EvidenceStore`, within budgets. Python then validates and persists the findings in both modes. Reports: `docs/ai_investigation/01_AI_INVESTIGATION_V1_IMPLEMENTATION_REPORT.md` and **`02_AI_INVESTIGATION_V2_TOOL_CALLING_REPORT.md`** (architecture, tool schemas, budgets, ledger, live results).

## 7. LangGraph nodes and execution flow (`uc042lib/investigation/graph.py`)

```text
START → load_investigation_case ─(error)→ validate_findings
          │ok
          ▼
        identify_investigation_scope → route_investigation ─(deterministic)→ retrieve_<route> ─(error)→ validate_findings
                                                                                 │ok
          routes: bank_ledger_mismatch | settlement_discrepancy | missing_bank_evidence |          ▼
                  customer_balance_discrepancy | unmatched_bank_entry |        build_evidence_packet → ai_investigation
                  unverified_relationship | insufficient_evidence | generic          → validate_findings → persist_findings → END
```

- **State:** `InvestigationState` (`TypedDict`).
- **Injected through `config["configurable"]`:** the investigator object and the roots (`packs_root`, `datasets_root`, `investigations_root`).
- **Entry points:** `run_investigation(pack_id, exception_id, investigator, ...)` in `graph.py`; `investigate_pack(pack_id, investigator)` in `run.py`. A pack with no exceptions returns `NO_EXCEPTIONS` and creates nothing.

## 8. Evidence retrieval and relationship resolution

**Integrity and access:**

- `retrieval.load_pack` validates the pack ID format, then verifies pack identity and content hash.
- `retrieval.EvidenceStore(pack)` verifies every source file's SHA-256 against the pack's audit trail, then loads rows with the existing `uc042lib.pack.assemble.load_sources`.
- **The only approved data access** is through `EvidenceStore`:
    - `get(evidence_id)`, `find(fid, **equals)`, `find_where`;
    - `bank_entries_by_reference`, `cashbook_by_reference`, `cashbook_on_date`;
    - `statement`, `confirmation`, `entries_on_statement`;
    - `external_record`, `internal_record`;
    - `batches_on_date`, `lines_of_batch`;
    - `snapshots`, `client_transactions`;
    - `discrepancy_log_for`, `search_reference`;
    - `previous_snapshot_date`, `next_recon_day`, `point`.

**Retrieval plans** (`packet.py`, route-specific) start from the evidence the engine cited, then widen through verified join keys only:

| Join | Keys |
| --- | --- |
| Cash book ↔ bank | (account, `payment_reference` = `bank_reference` or `end_to_end_ref`) |
| Batch → bank and cash book | `expected_bank_reference` |
| Line → transaction | `txn_id` |
| Transaction → batch | `settlement_batch_id` |
| Refund → original | `original_txn_id` |
| External record → confirmation | `bank_statement_id` |
| Discrepancy log | `recon_ref` |
| Date-scoped lookups | account + date |

**Joins that do not exist:** settlement lines carry **no client ID**, and there is **no posting-level client ledger**.

**Packet contents:** every record carries `evidence_id`, `file_id`, `source_file`, `source_line`, `file_sha256`, `retrieved_via` and `join_key`. Negative lookups become citable `SEARCH-nn` items, deterministic contradictions become `CONF-nn`. Missing items are the pack's `MISS-nn`. The packet also holds `allowed_citation_ids`. It never contains dataset folder names, scenario names or answer material (tested).

## 9. Pydantic models and findings contract (`models.py`)

**`LLMInvestigationOutput`** (what the model returns; `extra="forbid"`):

| Field | Contents |
| --- | --- |
| `investigation_summary` | Text |
| `confirmed_findings[]` | `F-nn`: `claim`, `explanation`, `evidence_ids` (≥ 1), `supporting_records` |
| `hypotheses[]` | `H-nn`: `possible_explanation`, `supporting_evidence`, `contradictory_evidence`, `limitations`, `status: "HYPOTHESIS"` |
| `contradictory_evidence[]` | `C-nn` |
| `missing_evidence[]` | `M-nn`, with `related_ids` |
| `open_questions[]` | Text |
| `recommended_next_steps[]` | `S-nn` |
| `overall_evidence_assessment` | EVIDENCE_SUFFICIENT / PARTIALLY_SUFFICIENT / INSUFFICIENT_EVIDENCE / CONFLICTING_EVIDENCE |
| `evidence_references[]` | All IDs cited |

**`InvestigationResult`** (persisted) adds fields set only by Python:

- identity: `investigation_id`, `pack_id`, `pack_content_sha256`, `exception_id`;
- original statuses;
- context: scope, route;
- `investigation_status` (COMPLETED / FAILED);
- fixed `exception_resolution: "NOT_RESOLVED_BY_INVESTIGATION"`;
- `evidence_packet_sha256`, `model_metadata` (with a `simulated` flag);
- `validation_status` (VALID / REJECTED / NOT_VALIDATED) and `validation_findings`;
- `failure_reason`, `investigated_at`.

**Deterministic validation (`validation.py`) rejects:**

- unknown citations;
- confirmed findings without a source record, control result or search;
- a candidate cited as confirmed;
- cause wording in confirmed findings;
- "exception resolved, closed or approved" wording;
- dropped `MISS` items;
- EVIDENCE_SUFFICIENT while evidence is missing;
- zero substituted for a missing balance.

**Persistence (`persistence.py`):** VALID results go to `investigations/<pack>/<exc>/INV-<exc>-<hash12>/` as `findings.json`, `evidence_packet.json` and `runs/NNNN.json`, write-once. An identical re-run appends a run record; a differing result for the same ID is refused. REJECTED and FAILED results go to `investigations/_not_published/`.

## 10. LLM provider configuration (`config.py`, `llm.py`)

**OpenAI is the default provider** (migrated 2 Nov 2026). Settings are read from the process environment and from a
local, git-ignored `uc042/.env`, loaded once by `config.load_local_env()` with python-dotenv; already-set variables win.

| Variable | Values / default |
| --- | --- |
| `UC042_LLM_PROVIDER` | `openai` (default, live), `anthropic` (live, legacy) or `offline` (deterministic stub, SIMULATED, tests only) |
| `UC042_LLM_MODEL` | Default `gpt-6-luna` for openai (`claude-sonnet-5-5` for anthropic); `config.DEFAULT_MODELS` |
| `UC042_LLM_TIMEOUT_SECONDS` | 120 (per request) |
| `UC042_LLM_TOTAL_TIMEOUT_SECONDS` | 300 (wall-clock budget for one investigation's model calls) |
| `UC042_LLM_MAX_TOKENS` | 8000 (`max_output_tokens`; reasoning tokens count towards it) |
| `UC042_OPENAI_REASONING_EFFORT` | Optional (`none`…`max`); `reasoning.effort` is sent only when set |
| `OPENAI_API_KEY` | Required for live OpenAI mode (`ANTHROPIC_API_KEY` for the legacy adapter) |

**Live adapter** (`OpenAIInvestigator`):

- `openai` 3.42.1 directly (no LangChain model wrapper), through the Responses API: `client.responses.with_raw_response.parse(model, instructions=SYSTEM_PROMPT, input=[user message with the packet], text_format=LLMInvestigationOutput, max_output_tokens, store=False, [reasoning])`;
- the raw body is checked first for `status` failed/incomplete (`max_output_tokens` is reported as such, not as invalid JSON) and for refusal items, then the SDK's Pydantic parse runs;
- no `temperature`/`top_p`;
- one retry only for invalid or absent structured output, within the overall time budget;
- typed failures: `LLMCallError.kind` is one of authentication, permission_denied, model_unavailable, bad_request, rate_limit, timeout, connection, refusal, max_output_tokens, incomplete, response_failed, invalid_output, timeout_budget or unexpected. Messages are credential-redacted;
- `check_availability()` (CLI `--check-provider`) authenticates and looks the model up without generating tokens;
- metadata: usage (input, output, reasoning, cached, total tokens; latency) and `provider_response` (response ID, resolved model, request ID, status).

**Data handling (corrected 2 Nov 2026):**

- `store=False` prevents Responses API application-state storage only.
- OpenAI's default abuse-monitoring logs (up to 30 days; they may contain prompts and responses) still apply, unless the
  organisation has approved Zero Data Retention or Modified Abuse Monitoring. Whether it has is **not established** for
  this project.
- `reasoning.encrypted_content` keeps reasoning available between rounds of a stateless conversation; it is not a
  retention control.

Details and official sources: report 02 §12.4.

**Contradiction rules (prompt 1.1 / 2.1-tools, findings schema 1.3):**

- A contradiction must compare exactly two items of the same measure and scope (`compared_evidence`,
  `same_measure_and_scope`).
- Different reconciliation views (internal requirement vs resource; external ledger vs bank; client balance) are never
  contradictions.
- Missing or not-found evidence is never one side of a contradiction.
- Unexplained differences stay unexplained.

`persistence.verify_published(path)` re-verifies any published artefact, read-only. Report 02 §12.1–12.3.

**Legacy adapter** (`AnthropicInvestigator`): unchanged behaviour, minus the dead `temperature` check; it now reports `refusal` and `max_tokens` stop reasons explicitly. There is no fallback between providers or to simulated output.

**Test doubles:** `ScriptedInvestigator`, `OfflineSimulatedInvestigator`.

**Hardening (V1.1, workflow `uc042-investigation-graph/1.1`, findings schema 1.1):**

- every graph node is guarded: unexpected exceptions are logged with their traceback (logger `uc042.investigation`) and become FAILED results, with error routes after scope, route and packet;
- publication is atomic, with `runs/0001.json` staged with the findings;
- run records are numbered through exclusive hard links (no overwrite under concurrency);
- storage failures give `PERSIST_FAILED` and leave no partial artefact;
- `investigate_pack` isolates each exception;
- an `ImmutabilityError` is still raised by the graph (tampering signal) and recorded per exception by `investigate_pack`.

## 11. Testing status (verified 2 Nov 2026, Python 3.11, Windows)

**409 tests: 408 passing and 1 opt-in live test skipped** (3 Nov 2026, after Phase 3; 340 at the time this section was first written) (`python -m unittest`, ResourceWarnings as errors) in the project `.venv`. Only the opt-in live test (`UC042_RUN_LIVE_TESTS=1`) calls a provider. `test_review_hardening` (12) covers contradiction classification and write-once integrity. Phase 1 final pack: `test_findings_schema_14` (5), `test_final_pack` (17), `test_closing_summary` (10), `test_final_pack_render` (6). Findings schema is **1.4** (prompts 1.2 / 2.2-tools): additive `title`, `audit_relevance`, `establishes`, `does_not_establish`, hypothesis `rationale`; older artefacts load with these as "not supplied".

| File | Tests |
| --- | ---: |
| test_audit_pack | 40 |
| test_investigation | 39 |
| test_tool_calling (V2: registry, execution, ledger, tool loop, validation, persistence; 1 opt-in live) | 34 |
| test_e1_e2 | 32 |
| test_baseline | 30 |
| test_openai_provider (OpenAI adapter, mocked SDK) | 28 |
| test_hardening | 23 |
| test_period_and_headers | 18 |
| test_investigation_hardening (persistence, graph errors, isolation) | 14 |
| test_period_decisions | 12 |
| test_scenario_datasets | 12 |
| test_output_verification | 8 |

Tests write only to temporary folders. Golden snapshots are regression references only.

## 12. Known limitations

1. **Live verification (2 Nov 2026, gpt-6-luna):** one V1 investigation (SC2) and four V2 tool-calling investigations (SC2, S02, SC5A, S05), all VALID and published under `investigations/`. Results are in report 02 §9. Quality has been reviewed by hand on these five runs only.
2. **Fixed mode has no tool calling** (by design). In tools mode the model decides which tools to call, and may call few or none when the packet already holds the evidence.
3. **Validation is rule-based** (regex phrase checks). It can over-reject (for example "due to") or miss paraphrased cause claims.
4. **Per-exception runs only.** SC5C's 17 grouped exceptions are 17 separate runs.
5. **Dataset gaps:** no client-ledger postings, no counterparty or remittance data, no fee schedule. PDFs are governance documents only. September only.
6. **Out of scope so far:** PDF evidence in investigations, the versioned final pack, review UI and upload workflow, deployment.
7. **SDK retries:** each request may be retried twice by the SDK on 429/5xx, so wall-clock time can exceed the per-request timeout. The overall budget is checked before each attempt.
8. **Windows path length:** very deep `investigations_root` paths can exceed MAX_PATH (260 characters); the default root is well within it.

## 13. Install and test (Windows, Python 3.11)

```powershell
cd uc042
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt                # pypdf, reportlab, tzdata + requirements-ai.txt
python -W error::ResourceWarning -m unittest       # expect: Ran 409 tests ... OK (skipped=1: opt-in live test)
python tools/verify_datasets.py                    # independent dataset verification (read-only)
```

`tzdata` is required on Windows: `zoneinfo` has no system time-zone database there, and the engine uses `Europe/London`.
VS Code: `.vscode/settings.json` at the workspace root points at `uc042/.venv`; confirm with "Python: Select Interpreter".

## 14. Run an investigation

```powershell
# One-time: copy .env.example to .env (already done locally) and put your key after OPENAI_API_KEY=
python -m uc042lib.investigation.run --check-provider                                    # auth + model availability, no tokens
python -m uc042lib.investigation.run PACK-SC2-PER-2026-09-aaca8a8b7194 EXC-SC2-01          # one live exception
python -m uc042lib.investigation.run PACK-S05-PER-2026-09-ddd0fdc8b731                     # every exception in the pack
python -m uc042lib.investigation.run PACK-SC2-PER-2026-09-aaca8a8b7194 EXC-SC2-01 --mode tools   # V2 bounded tool calling
$env:UC042_INVESTIGATION_MODE="tools"                                                    # or select V2 for this shell
$env:UC042_RUN_LIVE_TESTS="1"; python -m unittest tests.test_tool_calling.LiveSmoke          # opt-in live smoke test (spends tokens)
$env:UC042_LLM_MODEL="<other-model>"                                                     # switch model for this shell
$env:UC042_LLM_PROVIDER="offline"; python -m uc042lib.investigation.run <pack_id>        # SIMULATED, for testing only
python -m uc042lib.trace EXC-SC2-01 --set uc042_dataset/scn_SC2_settlement_timing          # trace (read-only)
```

A live result has `model_metadata.simulated: false` and `provider: openai`; simulated output has `simulated: true` and a
summary starting "SIMULATED OFFLINE OUTPUT". Exit code 0 means every investigation is VALID and persisted.

**Pack IDs:**

| Scenario | Pack ID |
| --- | --- |
| S01 | `PACK-S01-PER-2026-09-577b06a1d894` |
| SC2 | `PACK-SC2-PER-2026-09-aaca8a8b7194` |
| SC3B | `PACK-SC3B-PER-2026-09-137351796028` |
| SC3C | `PACK-SC3C-PER-2026-09-28bb49134f15` |
| S02 | `PACK-S02-PER-2026-09-f3dfa52766bb` |
| SC5A | `PACK-SC5A-PER-2026-09-ae391170b93a` |
| SC5C | `PACK-SC5C-PER-2026-09-eaac7e6b1444` |
| SC5D | `PACK-SC5D-PER-2026-09-2c5a7ae2e160` |
| S05 | `PACK-S05-PER-2026-09-ddd0fdc8b731` |

## 15. Protected files: never modify

- `uc042_dataset/**`: source CSVs, PDFs, manifests, scenario metadata, answer keys, validation outputs.
- `packs/**`: write-once; content-hash verified.
- `tests/golden/**` and existing tests: extend with new test files; do not alter existing assertions without an explicit, documented decision.
- `uc042lib/*.py` (engine) and `uc042lib/pack/*.py`: reuse them, don't rewrite them. Any change needs explicit approval and golden or pack impact analysis.

**Never run** these against the delivered data; they regenerate or write into dataset folders:

- `python -m uc042lib.generate`
- `python -m uc042lib.scenarios`
- `python -m uc042lib.validate`

Use `Validator(...).run()` in memory, or the read-only tools.

## 16. Never in the AI investigation context

Never in prompts, tool results or retrieval:

- `answer_key.json`, `mutations.json`, `SCENARIO_NOTES.md`, `scenario.json`;
- `SCENARIO_INDEX.md`, `scenario_index.json`;
- anything under `tests/` (including `golden/`);
- `docs/` (scenario-design and implementation reports describe planted answers);
- dataset folder names and pack `metadata.source_dataset` names;
- the generation and validation reports of scenario datasets (`GENERATION_NOTES.md`, `VALIDATION_REPORT.md`).

The AI may see only what `EvidenceStore` and the packet builder expose.

### 16a. Documentation in this package

| Path | Contents |
| --- | --- |
| `README.md` | Engine rules and overview |
| `docs/context/` | Hypothesis 2 business context |
| `docs/UC042_INPUT_EVIDENCE_SPEC_V1.md` | Input evidence spec |
| `docs/UC042_SOURCE_TO_CONTROL_MATRIX.md` | **Required by a test** (control-name registry) |
| `docs/UC042_PERIOD_AND_HEADER_RULES.md`, `UC042_UPLOAD_CONTRACT.md`, `UC042_RESEARCH_GAPS.md` | Rules, upload contract, open questions |
| `docs/dataset_assessment/01–05` | Dataset inventory |
| `docs/dataset_gap_closure/06` | Dataset enrichment report |
| `docs/processing_engine/01–02` | E1/E2 |
| `docs/audit_pack/01–05` | Audit pack |
| `docs/ai_investigation/01` + `examples/` | AI V1 report; SIMULATED example artefact |
| `docs/ai_investigation/02` | AI V2 tool-calling report: architecture, tool schemas, budgets, ledger, transcript, live results |

---

## V2: bounded LLM tool calling inside the investigation node — IMPLEMENTED (2 Nov 2026)

> **Status:** implemented as a nested LangGraph subgraph (`tool_loop.py`) with 8 strict read-only tools (`tools.py`), an
> evidence ledger, budgets, ledger-based validation and atomic persistence of `evidence_ledger.json` and `tool_calls.json`.
> 289 offline tests pass; four live gpt-6-luna tool-calling investigations are VALID. The design guidance below is kept
> for history; the implemented design is in `docs/ai_investigation/02_AI_INVESTIGATION_V2_TOOL_CALLING_REPORT.md`.

**Goal:** let the AI investigator request additional evidence dynamically through **approved Python tools**, within strict limits. LangGraph keeps control of the outer lifecycle, and Python keeps control of validation and persistence. Reuse V1. Do not rebuild the engine or pack layer.

```text
LangGraph outer workflow
  → load_investigation_case            (V1, unchanged)
  → identify_investigation_scope       (V1, unchanged)
  → retrieve initial evidence          (V1 route plans → initial packet)
  → AI investigation node (bounded loop)
        LLM decides which approved evidence tool to call
        Python executes the tool (EvidenceStore only), returns records with provenance
        LLM examines the evidence; may request more within limits
        LLM returns LLMInvestigationOutput
  → validate_findings                  (V1 deterministic validation; citation set = initial packet + tool results)
  → persist_findings                   (V1 write-once, separate from packs)
```

### Original design guidance (superseded by the implementation; see report 02)

1. **Tools as thin wrappers over `EvidenceStore`.** For example:
    - `get_record(evidence_id)`;
    - `find_bank_entries_by_reference(account, reference)`, `find_cashbook_by_reference(account, reference)`;
    - `get_statement(account, date)`, `get_confirmation(account, date)`, `get_entries_on_statement(statement_id)`;
    - `get_settlement_batch(batch_id)` (with lines), `get_transaction(txn_id)`;
    - `get_client_snapshots(client, currency, dates)`, `get_client_transactions(client, currency, from_date, to_date)`;
    - `get_external_reconciliation(account, date)`, `get_internal_reconciliation(currency, date)`;
    - `search_reference(account, reference)`.

    Input schemas use Pydantic, with strict ID and date formats, scoped to the case's own dataset. **No filesystem, shell or free-path tools.**
2. **Provenance on every tool result,** identical to packet records (`evidence_id`, file, line, `file_sha256`, `retrieved_via` = tool name and arguments, `join_key`). Not-found results become `SEARCH-nn`. Every returned ID is added to `allowed_citation_ids`; validation must use the final, accumulated set.
3. **Bounds, configurable and enforced in Python:** maximum tool calls (for example 8), maximum rounds, maximum records per call and in total (reuse `MAX_RECORDS`), a token budget, and a wall-clock timeout. When a limit is hit, stop and require the final structured answer. Record each call (tool, arguments, result size, latency) in the run record and artefact.
4. **Placement:** either a bounded loop inside `ai_investigation`, or a small LangGraph subgraph (`llm_step → tool_executor → llm_step`, with a conditional edge and an iteration counter in state). Prefer the subgraph for traceability. Keep a single agent.
5. **Untrusted data.** Tool results are data, never instructions. Keep the V1 system-prompt rules, and add tool-use rules (cite only returned IDs; do not request answer material; stop when evidence is sufficient or limits are reached).
6. **Provider.** Use OpenAI Responses API function calling through the existing `OpenAIInvestigator` pattern (raw-body status/refusal checks, typed `LLMCallError.kind`). Check the installed SDK's actual signatures first (`openai` 3.42.1). Keep `OfflineSimulatedInvestigator` and add a **scripted tool-calling test double**, so tests stay deterministic and offline.
7. **Keep V1 working:** the fixed path stays available (for example a `UC042_INVESTIGATION_MODE=fixed|tools` setting), and all 256 existing tests must keep passing.
8. **Tests to add:**
    - tool argument validation and path-safety;
    - forbidden files unreachable through any tool;
    - the call limit enforced;
    - tool-result provenance;
    - citations to tool-returned IDs accepted, invented ones rejected;
    - a scripted multi-step investigation on real packs (SC2, S02, SC5A, S05);
    - no data, pack or golden changes;
    - a live smoke test, skipped automatically when no API key is set.
9. **Definition of done for V2:** at least one **real live** investigation run end to end with credentials and reviewed by hand. If credentials are unavailable, report that honestly.

### After V2

- Group-level investigation (one run per investigation group).
- Final versioned audit-pack assembly that references the original pack and validated `INV-…` findings, never editing the original.
- Human compliance review (append-only review events).
- Frontend and upload workflow (`uc042lib/prepare.py` identifies uploaded files by content).
- Deployment and production hardening.
