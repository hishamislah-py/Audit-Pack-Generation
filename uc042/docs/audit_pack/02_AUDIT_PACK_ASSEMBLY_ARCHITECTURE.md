# 02 — Audit Pack Assembly Architecture

Status: **design for review.** Nothing is implemented. Tags [C] / [P] / [G] as in 01.

## 1. Layers and boundaries

```text
1. Source evidence           uc042_dataset/<case>/source_data, supporting_documents, manifest.csv, scenario.json, intake.csv
                             (read-only; never modified by any later layer)
2. Deterministic processing  uc042lib.validate.Validator  →  results, exceptions, groups, candidates, case status   [C]
3. Audit-pack assembly       uc042lib.pack (new, deterministic): selects, copies, cites, cross-checks; no financial maths
4. AI narrative (future)     may only restate pack content, citing pack IDs; cannot alter values, outcomes or statuses
5. Human review (future)     records review and approval events against an immutable pack_id
```

| Layer | May | May not |
| --- | --- | --- |
| 3 Assembly | Copy engine values and source fields; count records; build identifiers and reverse indexes; validate references | Compute amounts, totals or differences; change outcomes, statuses or wording; infer causes; drop or merge exceptions |
| 4 AI (future) | Draft text that cites pack IDs | Calculate figures; change outcomes; invent evidence; assign unverified causes; approve |
| 5 Human (future) | Review, comment, approve, reject; each an append-only event | Edit pack content (a correction creates a new pack) |

## 2. Interfaces

**Engine → pack.** The pack layer uses the existing in-memory objects of **one** validator run. It never reads stale CSVs (decision D6).

```python
v = Validator(case_dir); v.run()     # existing API [C]
v.results        # list of result dicts                  [C]
v.exceptions     # list of exception dicts              [C]
v.groups         # list of group dicts                  [C]
v.candidates     # list of candidate dicts              [C]
v.state          # unavailable files and their root cause [C]
v.recon_days, v.accounts, v.sga, v.ccy_of   # scope     [C]
case_status(v)   # existing summary status              [C]
v.pdf            # parsed PDF key details               [C] in memory; not persisted (gap D3)
```

**Pack layer API (proposed):**

```python
assemble_pack(case_dir, config) -> PackResult        # pure function of inputs + engine + config
PackResult = {status: "GENERATED" | "FAILED", pack: dict | None, validation: list, generation_record: dict}
write_pack(pack_result, packs_root) -> path           # write-once; refuses to overwrite
render_html(pack: dict) -> str                        # presentation only; reads pack.json, no other inputs
validate_pack(pack: dict, case_dir) -> list[finding]  # see 04
```

**Proposed modules** (no change to existing files except the additive engine fields of D3, if approved):

| Module | Purpose |
| --- | --- |
| `uc042lib/pack/model.py` | Contract constants, JSON schema, ID builders |
| `uc042lib/pack/assemble.py` | Workflow steps 1–9 |
| `uc042lib/pack/validate_pack.py` | Step 10 |
| `uc042lib/pack/render_html.py` | Step 11 |
| `uc042lib/pack/registry.py` | Control names (D1) |

## 3. Assembly workflow (deterministic)

| # | Step | Detail | On failure |
| --- | --- | --- | --- |
| 1 | Select inputs | Case directory (scenario dataset or prepared case); period from `schema` | Unknown directory → FAILED |
| 2 | Load source and run the engine | Read the manifest and `scenario.json` / `intake.csv`; `Validator(case).run()`; write that run's outputs to `packs/<run>/processing/` | Engine exception → FAILED (record traceback; no pack) |
| 3 | Verify required processing results | Every check in `schema.DEPENDS` plus the always-run checks has ≥ 1 result (gated checks produce an INSUFFICIENT_EVIDENCE result, so absence means an engine defect) | Missing check → FAILED: "control result missing" |
| 4 | Control register | Group results by `check_id`; add names (D1), counts, related exceptions and groups | — |
| 5 | Evidence register | Files from the manifest and `state`; cited rows from all citations (ranges expanded); reverse index | Unresolvable citation → FAILED (step 10 also checks) |
| 6 | Settlement register | IN-12 rows + C11 results + cited bank entry + FUND-TOPUP | — |
| 7 | Exceptions, groups, candidates | Copied unchanged; derived member and control lists | — |
| 8 | Missing evidence register | INSUFFICIENT_EVIDENCE results by root cause + unavailable files + intake | — (empty is valid) |
| 9 | Assemble | Metadata, summary, reconciliation blocks, registers, audit trail; canonical JSON (sorted keys, 2 dp strings) | — |
| 10 | Validate | All checks in 04 (references, value fidelity, counts, status semantics, completeness) | Any error → FAILED; nothing published |
| 11 | Render | `pack.html` from `pack.json` only | Render error → FAILED |
| 12 | Record and publish | `generation_record.json` (`generated_at`, `run_id`, fingerprints, validation summary). Atomic write: build in a temporary directory, then rename to `packs/<pack_id>/`. | If the target exists with a different hash → FAILED (immutability). Same hash → no-op ("already generated"). |

### Conditions defined in the brief

| Condition | Behaviour |
| --- | --- |
| Required input file missing | The engine already gates dependent checks and raises `MISSING_FILE`. The pack is **generated** with `evidence_completeness` = INCOMPLETE and a missing-evidence item. It is not blocked, because the gap *is* the audit finding. |
| Source reference does not resolve | **FAILED**: pack integrity error, nothing published (references are the pack's core promise) |
| Control result missing | **FAILED** (step 3): indicates an engine or run defect |
| Evidence incomplete | **GENERATED**, INCOMPLETE, listed in register I. Never zero-filled. |
| Exception without supporting evidence | **FAILED**. Every exception must cite rows; the engine guarantees this today (tests), so it would mean a defect. |
| No exceptions | **GENERATED**. Exception register states "No exceptions were raised for this period" with the result counts that support it. |
| No investigation groups | **GENERATED**; explicit "none" statement |
| Generation attempt fails | No pack directory is created. `generation_record.json` with FAILED and the findings is written to `packs/_failed/<run_id>/`. |

## 4. Output formats

| Format | Role | Reason |
| --- | --- | --- |
| **JSON (`pack.json`)** | **Source of truth** | Machine-checkable against the engine; hashable; diffable between runs; feeds rendering, future AI narrative (which cites IDs) and future review events |
| **HTML (`pack.html`)** | First human-readable view | Rendered only from `pack.json`. Collapsible registers (1,886 results, 1,920 evidence rows). Static file, no server needed; not the record. |
| PDF | Later export | Generated from the HTML. Not in scope now. |

## 5. Determinism and immutability

- **Canonical JSON:** sorted keys, fixed list orderings (results in engine order; exceptions by ID; evidence by file then line), money as engine strings, no timestamps inside `pack.json`.
- **Pack identity:** `pack_content_sha256` over canonical `pack.json`; the `pack_id` includes its first 12 hex characters.
- **Repeat generation** with identical inputs, engine and configuration gives an identical `pack.json` and `pack_id`. Only `generation_record.json` differs, by `generated_at`.
- **Changes create new packs:** any input, engine or configuration change produces a new run ID and a new pack. Existing packs are never edited (write-once check in step 12).

## 6. Risks

| Risk | Mitigation |
| --- | --- |
| Pack drifts from engine values | Value-fidelity validation (04, V3): every number equals its engine field byte for byte |
| Note-text parsing (lag, C05 values) | Additive structured engine fields (D3) instead of parsing |
| Large registers make the HTML unusable | Summary first; registers collapsed; cited-row evidence linked from results |
| A clean pack read as "nothing checked" | Summary shows result counts per check, evidence inventory and reconciliation tables, not just "0 exceptions" |
| Misleading single status | Four separate status fields; no blended status (R3) |
| Test-only artefacts leaking into the pack | Answer keys and golden files are **never** read by the pack layer; used only by tests |
