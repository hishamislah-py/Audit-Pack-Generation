# UC-042 Smart Parser — Phase 3B-8: End-to-End Workflow Verification and Review Interface Readiness

| | |
|---|---|
| Date | 18 November 2026 |
| Working copy | `C:\Users\artlptp263user\p10\smartparser_phase1` (the only location modified) |
| Evidence | `Downloads\UC042_SMART_PARSER_PHASE3B8\evidence\` (`evidence_baseline\` = before any 3B-8 change) |
| Result | **The backend works end to end for a single caller in a single process.** 20 end-to-end scenarios pass. 1 P0 defect fixed and 3 small P1 corrections made inside the existing architecture. **It is not yet an operational reviewer workflow:** there is no case store, no locking across processes, finalisation is not atomic, and there is no API. The design for these is in §6–§10 and awaits approval. |

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| **[T]** | Verified by an executed test or probe in this phase |
| **[C]** | Inferred from code inspection |
| **[I]** | Existing implemented functionality |
| **[P]** | Proposed, not implemented |
| **[N]** | Not implemented |

---

## 1. Executive summary

### What works [T]
Every route has been verified end to end through the real orchestrator and stores (§12):
- **deterministic** files;
- **proposal** files: recorded CLEAR proposals reaching POC auto-accept, and ambiguous proposals completed through the review session;
- **direct human review** for a different column count, with MAP, CHANGE, CHOOSE_DUPLICATE_SOURCE, IGNORE_COLUMN, LEAVE_UNRESOLVED and REJECT, ending RESOLVED or HELD;
- **deterministic-conflict** cases.

Each resolved path then runs **deterministic reprocessing, the 14-point handoff check and a preview**.

Across those runs:
- No LLM call ever happens before review on a file with a different count, or during reprocessing.
- Original bytes stay intact, and provenance traces every output cell to its source position.
- The audit chain verifies in every scenario.
- Duplicate finalisation cannot create two active rules.

### What was wrong and is now fixed
- **P0 (data loss).** Two `EvidenceStore` instances on the same folder silently dropped each other's intake records; the index was also written non-atomically. **Fixed** [T].
- **P1, small.** All three are fully inside the existing architecture:
  - **(a) Changed original.** A file changed after review used to leave an active rule, a category confirmation and a RESOLVED case behind. It is now refused before anything is written.
  - **(b) Unaudited outcomes.** Reprocessing, handoff and preview events were declared but never written to the audit log; they now are.
  - **(c) Ambiguous resolution record.** The resolution event now names the confirmation and rule it used.

### What is not operational yet [T]/[C]
These are design proposals awaiting approval:
- **Open review cases exist only in memory** (neither cases nor proposal sessions have a store). Cases cannot be listed or retrieved by ID, and they survive a restart only if the caller saves the JSON.
- **There is no locking across processes** for the audit log, rule store or evidence index.
- **Finalisation is a multi-step write without atomicity** (orphan confirmation events, tested).
- **The category confirmation exists only as an audit event.**
- **Conflict files get two parallel review channels.**
- **A case's state is not linked to its rule's lifecycle.**
- **There is no API** (FastAPI is declared only as an optional "Phase 5" extra), **and reviewer identity is passed in by the caller, not authenticated.**

### Structural finding for the owner [T]
On a UC-042 category, an **equal-count** file with a deterministic duplicate claim **can never produce a preview**. With equal counts, a duplicate claim always leaves one required field without a column, and the duplicate column cannot be remapped because its header matches another field (RULE_CONTRADICTION). Such cases can only end HELD or REJECTED (scenario 4). Whether a reviewer may override a deterministic header match for one file is an owner decision (§18).

## 2. Actual implementation baseline (established independently before any change)

| Check | Result | Evidence |
|---|---|---|
| Full suite | **491 passed** | `evidence_baseline/test_run_full.txt` |
| Suite without the UC-042 tree | 488 passed, 3 skipped | `evidence_baseline/regression_summary.txt` |
| Per phase | 3B-7 35, 3B-6.1 18, 3B-6 43, 3B-5 16, 3B-4 14, 3B-3 15, 3B-2 23, 3B-1 40, 3B-0 117, Phase 1+orig 136, Phase 2 34 | same |
| Registry | in sync: 19 definitions | same |
| Phase 1 baseline / Phase 2 corpus | 445/445; 161/161 | same |
| POC policy | `DISABLED`, `enabled=False`, `accept_supplied_category=False` | command output |
| AI config default | `enabled=False`, provider `None` | command output |
| Production authority policy | `uc042-authority/production-unconfigured`, `PRODUCTION_UNCONFIGURED`, scopes `{}` | command output |
| Protected trees | UC-042 code 107, datasets 624, Desktop 63: hash-identical; 0 UC-042 files newer than the Phase 1 start | regression summary |
| API layer | none; `pyproject` `[api]` extra (fastapi, uvicorn) declared as "Phase 5 … deliberately not required"; fastapi not installed | `pyproject.toml` |
| CLI | `schemas`, `process`, `classify`, `import-registry` only; no orchestration or review commands | `smartparser/cli.py` |

The baseline matches the 3B-7 report.

## 3. Three complete workflow traces (actual call chains)

### Scenario A — equal count, unfamiliar headers [T scenarios 2, 3, 20; C for the call chain]

| Step | Call | Data passed / produced |
|---|---|---|
| Intake | `MappingOrchestrator.process(data, filename, period, category)` → `RuleStore.load()` | `MappingRules` (policy, aliases, layouts, file mappings, no file identity) |
| Category | supplied by the caller (`category`); the LLM never chooses it | — |
| Header-count gate | `_header_count_gate` → `identify` → `read_csv` → `len(raw)==len(schema.fields)` → `None` | nothing stored by the gate |
| Deterministic matching | `SmartParser.process_bytes(forced_category)` → `EvidenceStore.save` (intake ID and SHA) → `_confirm_forced_category` → `controlled_map` rejects (unexpected columns) → `FORCED_CATEGORY_REJECTED`, mapping NOT_ATTEMPTED; records keep originals (`raw_records`) | `EvidenceResult` |
| Proposal request | `ProposalGateway.propose` → `eligibility` (confirmed category, not mapped, no content conflict) → `DedupIndex` → budget gate → `run_proposal` → `build_request` | `ProposalRequest`: resolved columns, **only the unresolved headers**, missing required fields, deterministic conflicts; value shapes stripped by default |
| LLM response | `RecordedResponseStub.propose` (tests); a live provider is `DisabledLiveProvider` | JSON text |
| Validation | `validate_proposal` → per-column class CLEAR / PLAUSIBLE / AMBIGUOUS / NO_MATCH / CONFLICT_INCOMPLETE; the proposer's confidence is ignored | `ProposalRecord` (summary, `required_fields_unresolved`, `deterministic_conflicts`) |
| Duplicate check | `_deterministic_duplicates` → `controlled_map(...).duplicate_fields` | `{}` here |
| Decision policy | `policy.decide` (order: no proposal → HOLD; deterministic conflict → HITL; required unresolved → HOLD; invalid → HOLD; NO_MATCH → HITL; ambiguous/plausible/policy off → HITL; else AUTO) + supplied-category guard; `POC_AUTO_DECISION` audited | `PolicyDecision` |
| AUTO_ACCEPT | `_auto_accept` → `FileMappingRule` (approval kind `POC_AUTO`) → `RuleStore.add_file_mapping` → `RULE_CREATED`/`RULE_ACTIVATED` → `CategoryConfirmation` (POC) → `CATEGORY_CONFIRMED` | rule + confirmation |
| HUMAN_REVIEW | `start_session` → `ReviewSession` (PROPOSED). **Completion has no orchestrator entry point:** `open_review` → `decide_column` → `approve_proposal` → `approve_file_mapping` → `confirm_category` → `reprocess` → `check_handoff` → `write_preview` called by the caller (scenario 3) | session in memory (`ReviewSession.save` exists) |
| Reprocessing | `_finish` → `reprocess` (SHA verify, intake verify, confirmation for this upload, `rules.with_file_identity(intake, sha)`, in-memory evidence store, no proposer) | `ReprocessResult` (`provider_calls=0`) |
| Handoff | `check_handoff` (14 checks) | `HandoffEligibility` |
| Preview | `write_preview` (refuses ineligible input and protected roots; self-check) + sidecar `workflow_decision`; **3B-8:** `REPROCESSED`, `HANDOFF_EVALUATED`, `HANDOFF_PREVIEW_WRITTEN` audited | CSV + `.provenance.json` |

**Inconsistencies found:**
- The proposal-session path has no completion entry point equivalent to `complete_case` (P1-7).
- Proposal records are never persisted (P1-10).

### Scenario B — different column count [T scenarios 5, 6, 7, 10–13, 15–19]

| Step | Call | Observed |
|---|---|---|
| Intake + gate | `_header_count_gate`: counts differ → `validate_reporting_period` → `EvidenceStore.save` → `exact_header_index` diagnostic → `open_case("HEADER_COUNT_MISMATCH")` → `INTAKE_CASE_OPENED` | audit for the intake is **exactly** `["INTAKE_CASE_OPENED"]`; `initial=None`, `proposal=None`, 0 provider calls, no rule [T s5] |
| Reviewer decisions | `case_context` (verifies the stored original's SHA, the intake and the header; 5 samples per column; deterministic field per position) → `intake.decide` (FILE_MAPPING authority, reason, DUPLICATE_TARGET / VALUE_INCOMPATIBLE / RULE_CONTRADICTION) → `INTAKE_DECISION` | decisions appended, never overwritten |
| Finalisation | `complete_case` → **3B-8: fresh `case_context` (re-verify)** → `finalise_case`: undecided columns → error; registry hash; duplicates; re-validation; unresolved or missing required → **HELD** (`INTAKE_CASE_HELD`, nothing written); else `confirm_category` (CONFIRMATION or CONFLICT scope) → `FileMappingRule` (MAP/IGNORE per position) → `add_file_mapping` → `RULE_CREATED`/`RULE_ACTIVATED` → RESOLVED → `INTAKE_CASE_RESOLVED` (3B-8: names the confirmation and rule) | rule + confirmation |
| Reprocessing → handoff → preview | as in Scenario A (`_finish`) | eligible: preview byte-identical to canonical; HELD: no reprocessing at all [T s6] |

**Confirmed:** no deterministic mapping and no LLM proposal is invoked before review. Only `identify`/`read_csv` run, plus the diagnostic name match (which is never applied).

### Scenario C — equal count with duplicate canonical claims [T scenario 4, probes E2 / E2b]

| Step | Observed |
|---|---|
| Matching | `controlled_map`: both claimants are in `mappings`, and `duplicate_fields = {"currency": ["currency", "CURRENCY"]}`; forced category rejected |
| Proposal | requested only if other columns are unresolved (validator flags `DETERMINISTIC_CONFLICT`); with no unresolved column, no call is made [T s4] |
| Routing | `dup` non-empty → HUMAN_REVIEW in every branch (no proposal, error, HOLD or AUTO all overridden) → `open_case("DETERMINISTIC_CONFLICT")` seeded by `deterministic_suggestions` |
| Review | `CHOOSE_DUPLICATE_SOURCE` gives the other claimants IGNORE in one group; remapping the duplicate to the missing field → **RULE_CONTRADICTION** |
| Outcome | HELD: `payment_reference` has no column (§1 structural finding). No rule, no preview |
| **Gap** | the orchestrator **also** opens a proposal `ReviewSession` for the same file when a proposal exists. Approving that session creates an active file mapping with both duplicate positions unmapped (`None`) [T E2]. That rule is never eligible (the forced category is rejected at reprocess) [T E2b], so it fails safe. But it occupies the intake's single active-rule slot, so a later case resolution for the same file would be refused ("two active file mappings") until it is revoked (P1-5) |

**Duplicate conflicts cannot bypass review [T]:**
- no AUTO_ACCEPT;
- no eligible preview through either channel;
- the policy unit test confirms that a conflict is routed before the required-field HOLD.

## 4. Architecture and module dependency map

```
                 cli.py (schemas/process/classify/import-registry; no review commands)
                        │
 orchestration/orchestrator.py ── policy.py (POC policy JSON, DISABLED)
   │  gate: identify/detect.py → csv_engine/reader.py → schemas/registry.py → review/intake.open_case
   │  pipeline.py ─ intake/store.py (EvidenceStore: originals/, index.json)
   │      ├ identify/detect.py, csv_engine/reader.py, classify/{csv_classifier,content_check}.py
   │      ├ mapping/controlled.py (controlled_map, MappingRules) ← mapping/rule_store.py (RuleStore: 4 JSON files)
   │      ├ normalise/engine.py, validation/validator.py → models/results.py
   │  ai/gateway.py (eligibility, DedupIndex[mem], UsageLedger[file|mem], budget gate) → mapping/proposal_runner.py
   │      → ai/proposer.py (RecordedResponseStub | DisabledLiveProvider) → mapping/proposals.py (validate_proposal)
   │  review/session.py (ReviewSession [mem; save/load to a path]) ── review/approvals.py (confirm_category,
   │      approve_file_mapping, approve_alias/layout, revoke_rule) ── review/authority.py (AuthorityPolicy, Reviewer)
   │  review/intake.py (ColumnReviewCase [mem], decide, reject_case, finalise_case)
   │  review/audit.py (AuditLog: hash-chained append-only JSONL)  ← every review/rule/outcome event
   └ handoff/reprocess.py → pipeline (no proposer) ; handoff/eligibility.py (14 checks) ; handoff/writer.py (preview)
```

**Persistent stores:**
- `EvidenceStore`: original bytes and the intake index;
- `RuleStore`: rules;
- `AuditLog`: events;
- the preview directory: CSV and sidecar;
- optionally the `UsageLedger` file.

**Everything else is an in-memory object:** cases, sessions, proposal records, confirmations, `WorkflowResult`, `ReprocessResult` and the dedup index.

## 5. Review-case lifecycle (column-review case) [I/T]

```
 OPEN ──decide──► UNDER_REVIEW ──decide──► UNDER_REVIEW
   │                 │  finalise: unresolved / missing required ──► HELD ──decide──► UNDER_REVIEW (revisable)
   │                 │  finalise: complete ──► RESOLVED (terminal)
   └──reject──────►  └──reject──► REJECTED (terminal)          HELD ──reject──► REJECTED
```

**Persisted side effects:**
- **On a decision:** `INTAKE_DECISION` only.
- **On HELD:** `INTAKE_CASE_HELD`.
- **On RESOLVED:**
  - `CATEGORY_CONFIRMED`;
  - a file-mapping rule (`file_mappings.json`) with `RULE_CREATED`/`RULE_ACTIVATED`;
  - `INTAKE_CASE_RESOLVED`;
  - then `REPROCESSED` and `HANDOFF_EVALUATED`, plus `HANDOFF_PREVIEW_WRITTEN` when eligible.
- **On REJECTED:** `INTAKE_CASE_REJECTED`.

**The case snapshot itself is never persisted** by the backend. Its `state`, the `decisions` list and `history` live only in the object.

The proposal `ReviewSession` has its own lifecycle (PROPOSED → UNDER_REVIEW → PARTIALLY_DECIDED → APPROVED, REJECTED or REVISION_REQUESTED). It has `save(path)` and `load(path)`, but no store and no index.

## 6. Persistence assessment

### 6.1 The twelve questions

| # | Question | Answer |
|---|---|---|
| 1 | Where is an open review case stored? | **Nowhere persistent.** `ColumnReviewCase` is a pydantic object on the returned `WorkflowResult.intake_case` [C, T s19]. A caller can serialise it (`model_dump_json`) |
| 2 | Does it survive a process restart? | **No**, unless the caller saved the JSON. The decisions survive as `INTAKE_DECISION` audit events [T s19] |
| 3 | Can a reviewer retrieve a case after closing the application? | **No backend mechanism** (no store, no list, no lookup by ID) [N] |
| 4 | Can another process retrieve the same case? | **No** [N]. Two orchestrators can share the persistent stores (3B-8 fix; T s19b), but not cases |
| 5 | Are decision histories recoverable? | **Yes, from the audit log.** `INTAKE_DECISION` carries `case_id`, `decision_id`, position, header, action, field, reason, `group_id`, `supersedes`, reviewer, role and kind [T s8–9, s19] |
| 6 | Can a reviewer resume an unfinished case? | **Only with the caller's saved JSON** (verified: reload → continue → finalise → eligible preview, audit chain intact) [T s19]. Rebuilding from the audit alone is possible in principle: headers from the stored original, diagnostic suggestions are deterministic, decisions and state from events. There is no helper [N], and proposal-based suggestions cannot be rebuilt because proposal records are not stored |
| 7 | What happens if finalisation is interrupted? | It depends where. Rule write fails after the confirmation: **orphan `CATEGORY_CONFIRMED` event, no rule, case still UNDER_REVIEW; a retry succeeds and leaves 2 confirmation events** [T E4]. Crash after the rule write but before `RULE_CREATED`: **active rule without its audit events** [C]. Crash after the rule but before `INTAKE_CASE_RESOLVED`: rule active, case object lost [C]. Crash before or after preview: the preview can be regenerated deterministically [C/T s17] |
| 8 | Can duplicate finalisation create inconsistent rules? | **No duplicate active rule** [T s18]: the same object is refused by the state guard; a stale copy is refused by the rule store ("two active file mappings for the same key", which rolls back the write). Residue: one orphan `CATEGORY_CONFIRMED` [T s18]. Under two **processes** writing at the same moment, the rule store's read-modify-write is unlocked, so a lost update is possible [C] (P1-2) |
| 9 | Transaction-like protection around rule creation, activation and resolution? | **Partial.** Each rule-store write is atomic per file (tmp+replace) with validate-and-rollback [C]. Across steps (confirmation event → rule file → rule events → resolution event) there is **no transaction, intent record or recovery** [C/T E4] |
| 10 | Can an audit event be written while the rule operation fails? | **Yes**, `CATEGORY_CONFIRMED` [T E4, T s18]. `RULE_CREATED`/`ACTIVATED` are written only after a successful rule write [C] |
| 11 | Can a revoked rule leave a case appearing resolved? | **Yes.** The case object stays RESOLVED after `revoke_rule`; reprocessing is then ineligible [T s16] (P1-6) |
| 12 | Are file-specific decisions reliably linked to the upload? | **Yes.** The rule carries `intake_id` and `source_sha256` and applies only under `with_file_identity(intake, sha)`. Reprocessing verifies the stored bytes' SHA and that the confirmation belongs to this upload. A re-upload gets a new intake, a new case and no reuse [T s15, s17; 3B-7 test]. Positions are tied via `header_fingerprint` and the exact header list [C] |

### 6.2 What is persistent, in memory or reconstructable

| Artefact | Where it lives | Persistent | Reconstructable after restart |
|---|---|---|---|
| Original upload bytes | `evidence/originals/<sha[:2]>/<sha>` (content-addressed) | ✔ | — |
| Intake record (intake ID ↔ SHA, filename, period) | `evidence/index.json` (**3B-8: atomic, re-read before each read and append**) | ✔ | — |
| **Review-case state** (state, history, final summary) | in-memory object | ✘ | partly, from `INTAKE_CASE_*` events + the stored original; no helper |
| **Review decisions** | case object + `INTAKE_DECISION` events | ✔ (audit) | ✔ |
| Proposal session | in memory; optional `ReviewSession.save(path)` | caller only | decisions from `COLUMN_DECIDED` events |
| Proposal record (LLM output, classes) | in memory (gateway `DedupIndex`) | ✘ | ✘ (`PROVIDER_CALL` keeps hashes and metadata only) |
| **Mapping rules** | `rules/file_mappings.json` (+ aliases, layouts, proposals) | ✔ atomic per write, validated, rollback | — |
| **Category confirmations** | returned object + `CATEGORY_CONFIRMED` event (ID, category, scope, basis, actor) | audit only | ✔ in principle from the event; **no helper**; ambiguous after an orphan (3B-8: `INTAKE_CASE_RESOLVED` names the one used) |
| **Audit events** | `audit.jsonl` hash chain | ✔ | — |
| **Reprocessing results** | transient `ReprocessResult` (**3B-8: `REPROCESSED` and `HANDOFF_EVALUATED` audited**) | outcome audited | ✔ deterministic: same bytes + rules + confirmation → identical output [T s17] |
| Preview + sidecar | `preview_dir/<intake_id>/` (**3B-8: `HANDOFF_PREVIEW_WRITTEN` audited with output SHA**) | ✔ | ✔ regenerable |
| `WorkflowResult` | transient dataclass (not JSON-serialisable: contains bytes and dataclasses) | ✘ | partly, from audit |

**An append-only audit log is not a case store.** It records what happened, but it is not indexed or queryable, and it does not hold the case's current snapshot. Its intent is also incomplete: the `INTAKE_CASE_OPENED` event does not carry the columns or suggestions. Using it as the system of record would mean replaying the whole file for every read.

### 6.3 Persistence recommendation [P] — smallest compatible design (not implemented)

A **file-based `CaseStore`**, in the same style as `RuleStore` and `EvidenceStore`. It needs no database, Redis or broker: the existing stores already prove that atomic JSON files meet the POC's volume and audit needs.

| Aspect | Design |
|---|---|
| Storage model | `cases/<case_id>.json` holds the full `ColumnReviewCase` snapshot (plus, for a conflict case, the embedded `ProposalRecord` so suggestions survive). `cases/index.json` holds a summary list: `case_id`, kind, state, `intake_id`, sha, category, filename, received_at, counts, `updated_at`, revision. Proposal sessions are stored the same way under `sessions/` |
| Case identity | the existing `case_id` (`CRC-…`); at most one OPEN, UNDER_REVIEW or HELD case per `intake_id` (enforced in the store) |
| Decision history | already in the snapshot (append-only `decisions`, `supersedes`); the audit stays the independent record |
| State transitions | unchanged (`intake.TRANSITIONS`); the store only persists after a service function succeeds |
| Idempotency | every mutation carries `expected_revision`; the store writes `revision+1` only if it matches, else 409. Finalisation carries an `idempotency_key` recorded in the snapshot; a repeat with the same key returns the stored outcome |
| Concurrency | one lock file per store root (`os.open(..., O_CREAT\|O_EXCL)` with stale-lock timeout; the standard library is enough), used by CaseStore, RuleStore, EvidenceStore index and AuditLog appends. Keeps the hash chain linear across processes |
| Finalisation recovery | persist `state=FINALISING` (new transient state) with the planned `file_mapping_id`/`confirmation_id` **before** any write; then confirmation → rule → events → RESOLVED. On start-up, for every FINALISING case: if the rule exists and is active, complete the missing events and RESOLVED; otherwise return to UNDER_REVIEW and audit `INTAKE_CASE_FINALISE_ABORTED` (new event type). Removes orphan confirmations as an ambiguity source |
| Confirmations | stored in the snapshot (`confirmation` object) and reconstructable from audit by `confirmation_id`; `reprocess` gets it from the store, not the caller |
| Restart | everything needed to resume or finish is on disk: original, intake, case snapshot, rules, audit |
| Audit integration | unchanged events + `INTAKE_CASE_SAVED` not needed (the snapshot is derived state); add `INTAKE_CASE_FINALISE_ABORTED` |
| File identity | on every load, the store re-verifies the stored original's SHA and intake (as `case_context` already does) |
| Rule-lifecycle link | `effective_outcome(case)` derives RESOLVED_ACTIVE, RESOLVED_REVOKED or RESOLVED_SUPERSEDED at read time from the rule store; it is never written into the case |
| Migration | none: new folders; existing callers (tests, evaluations) keep working, since the store wraps the existing functions. Cases opened before the store exists are not migrated (in-memory only today) |

## 7. Restart and recovery assessment [T/C]

| Situation | Today |
|---|---|
| Restart with an unfinished case | resumable **only** if the caller saved the case JSON [T s19]; otherwise re-derivable by hand from the original + audit [C] |
| Restart after RESOLVED, preview not yet written | rule active; the confirmation must be rebuilt from `CATEGORY_CONFIRMED` (no helper) → `reprocess` → preview [C] |
| Restart mid-finalisation | see §6.1 Q7; no automatic recovery [C] |
| Two orchestrators or store instances | **fixed in 3B-8** for the evidence index within a process (sequential) [T s19b]; across processes unlocked (P1-2) [C] |
| Pending proposal deduplication | lost (in memory); a re-submission re-requests a proposal (budget-gated) [C] |

## 8. Idempotency and concurrency assessment

| Operation | Idempotent? | Concurrency-safe? |
|---|---|---|
| `process()` same bytes twice | No: two intakes, two cases (by design, one case per upload event) [T 3B-7] | evidence index safe within a process (3B-8) |
| `decide()` repeated | Appends a new decision (supersedes); no duplicate-request detection [C] | object-local; no cross-request guard |
| `complete_case()` repeated | Same object: refused (state) [T s18]. Stale copy: refused by rule-store uniqueness + rollback [T s18]. Residue: orphan confirmation event | rule store unlocked across processes [C] |
| `reject_case()` repeated | refused (terminal state) [T 3B-7] | object-local |
| `revoke_rule()` repeated | refused (only an active rule changes) [C] | unlocked |
| `reprocess()` / preview | yes, byte-identical [T s17] | read-only plus its own preview folder |
| `AuditLog.append` | n/a | **two processes can fork the chain** (both read the same last hash) [C] |

## 9. Reviewer API readiness matrix

There is **no API layer** [N]. "Authority" is the `AuthorityPolicy` scope; production authorises nobody. "Persistence" means whether the operation's result is retrievable later without the caller holding the object.

| # | Operation | Existing service function | Request model | Response model | Authority | Validation | Persistence | API wrapper |
|---|---|---|---|---|---|---|---|---|
| 1 | List open cases | **none** | — | — | read | — | **✘** | missing (needs CaseStore) |
| 2 | Get case by ID | **none** (object only) | — | `ColumnReviewCase` | read | — | **✘** | missing (needs CaseStore) |
| 3 | Incoming headers + canonical fields | `case.headers`, `case.columns`; `registry.get(case.category).fields` (name, M/C/O, type, pattern) | — | `ColumnReviewCase`, `FieldDefinition` | read | — | case ✘, registry ✔ | missing |
| 4 | Missing / extra columns | `case.missing_fields_diagnostic`, `case.extra_headers_diagnostic` | — | in case | read | — | ✘ | missing |
| 5 | Duplicate-header claims | `case.duplicate_incoming_headers`, `potential_duplicate_claims`, `columns[].same_header_positions` | — | in case | read | — | ✘ | missing |
| 6 | Deterministic / LLM suggestions | `case.columns[].suggested_field` + `suggestion_basis`; `case_context()` (deterministic per position, samples); proposal record only on the original `WorkflowResult` | — | `CaseContext` (dataclass) | read | SHA verify | proposal ✘ | missing |
| 7 | MAP | `intake.decide(case, "MAP", reviewer, reason, policy, log, ctx, i)` | positional args (no request model) | `list[CaseDecision]` | FILE_MAPPING | reason; suggestion exists; DUPLICATE_TARGET; VALUE_INCOMPATIBLE; RULE_CONTRADICTION | audit ✔, case ✘ | missing |
| 8 | CHANGE | `decide(..., "CHANGE", ..., canonical_field)` | as above | as above | FILE_MAPPING | + field of the category | as above | missing |
| 9 | Choose duplicate source | `decide(..., "CHOOSE_DUPLICATE_SOURCE", ..., others_reason)` | as above | chosen + IGNOREs | FILE_MAPPING | ≥2 claimants; `others_reason` | as above | missing |
| 10 | Ignore column | `decide(..., "IGNORE_COLUMN", reason)` | as above | `CaseDecision` | FILE_MAPPING | reason | as above | missing |
| 11 | Leave unresolved | `decide(..., "LEAVE_UNRESOLVED")` | as above | `CaseDecision` | FILE_MAPPING | reason | as above | missing |
| 12 | Reject | `intake.reject_case` | args | `None` (mutates) | FILE_MAPPING | reason; state | audit ✔ | missing |
| 13 | Finalise | `MappingOrchestrator.complete_case` | args | `WorkflowResult` (not serialisable) | FILE_MAPPING + CATEGORY_CONFIRMATION or CONFLICT | all decided; registry hash; dup; re-validation; **3B-8 SHA re-verify** | rule ✔, confirmation audit-only, case ✘ | missing; non-atomic (P1-3) |
| 14 | Final outcome | `WorkflowResult` (transient); `REPROCESSED` / `HANDOFF_*` events (3B-8) | — | — | read | — | audit ✔ | missing (needs CaseStore + outcome model) |
| 15 | Audit history | `AuditLog.events()` + filter by `intake_id` / `details.case_id`; `verify()` | — | `list[AuditEvent]` | read | chain verify | ✔ | missing (full-file scan) |
| 16 | Preview + provenance | `wr.preview` (paths, output SHA, sidecar doc); files under `preview_dir/<intake_id>/` | — | dict | read | eligibility | ✔ files | missing |
| — | Proposal session (ambiguous path) | `open_review`, `decide_column`, `approve_proposal`, `reject_proposal`, `request_revision`, `approve_file_mapping`, `confirm_category` | args | `ReviewSession` | FILE_MAPPING, CATEGORY_* | per 3B-2 | `save(path)` only | missing; **no completion entry point** (P1-7) |

**Cross-cutting gaps:**
- **No error codes.** Rule violations are `ReviewError` messages ("DUPLICATE_TARGET: …"); an API needs a structured `code`.
- **No identity binding.** `Reviewer` is constructed by the caller (`reviewer_id`, role, kind). An API must derive it from an authenticated principal and never accept it from the request body.
- **Values in the context.** `CaseContext.samples` contains real cell values. Showing them to reviewers is a data-exposure decision (§18).

## 10. Proposed API contracts [P] (not implemented; the architecture has no API layer)

These are thin wrappers over the existing service functions and the proposed CaseStore. FastAPI matches the existing optional `[api]` extra. All mutations require `expected_revision`. Identity and roles come from the authenticated session; the production policy currently authorises nobody, so mutations return 403 until the owner configures roles.

| Method | Path | Purpose | Request | Response | Errors |
|---|---|---|---|---|---|
| POST | `/intakes` | upload + route | multipart `file`, `category?`, `reporting_period?` | `{intake_id, sha256, route, decision, reasons, case_id?, session_id?}` | 400 (unreadable), 413, 422 |
| GET | `/cases?state=&kind=&category=` | review queue | — | `[{case_id, kind, category, filename, received_at, incoming_header_count, expected_field_count, reason, state, revision}]` | — |
| GET | `/cases/{case_id}` | case detail | — | `ColumnReviewCase` + `revision` + `effective_outcome` | 404 |
| GET | `/cases/{case_id}/context` | review table | — | `{canonical_fields:[{name, requiredness, type, pattern}], columns:[{source_index, header, suggested_field, basis, deterministic_field, samples?}]}` | 404, 409 (original SHA mismatch) |
| POST | `/cases/{case_id}/decisions` | MAP / CHANGE / CHOOSE_DUPLICATE_SOURCE / IGNORE_COLUMN / LEAVE_UNRESOLVED | `{action, source_index, canonical_field?, reason, others_reason?, expected_revision}` | `{decisions:[CaseDecision], case}` | 400 `{code: DUPLICATE_TARGET \| VALUE_INCOMPATIBLE \| RULE_CONTRADICTION \| REASON_REQUIRED \| NOT_A_CLAIMANT \| UNKNOWN_FIELD}`, 403, 404, 409 (revision, terminal state) |
| POST | `/cases/{case_id}/reject` | reject | `{reason, expected_revision}` | `case` | 400, 403, 409 |
| POST | `/cases/{case_id}/finalise` | finalise → reprocess → handoff → preview | `{basis, expected_revision, idempotency_key, category_reviewer?}` | `{state: RESOLVED\|HELD, file_mapping_id?, confirmation_id?, final_summary, eligibility:{eligible, checks}, preview?:{output_sha256, csv_url, provenance_url}}` | 400 (undecided), 403 (FILE_MAPPING / CATEGORY_CONFLICT), 409 (revision, original changed, duplicate active rule, already finalised with another key) |
| GET | `/cases/{case_id}/outcome` | outcome incl. rule lifecycle | — | `{state, effective_outcome, rule:{id, version, status}, reprocess:{provider_calls, category_basis}, eligibility, preview?}` | 404 |
| GET | `/cases/{case_id}/audit` | history | — | `[AuditEvent]` (filtered by `case_id` / `intake_id`; chain verified) | 404, 500 (chain broken) |
| GET | `/intakes/{intake_id}/preview` / `/provenance` | preview files | — | CSV / sidecar JSON (always marked PREVIEW_ONLY) | 404 (not eligible) |
| — | `/sessions/...` | same pattern for proposal sessions + a new `finalise` (P1-7) | | | |

**Authentication and authorisation (decisions):**
- the identity provider;
- the mapping from roles to policy scopes;
- whether BUSINESS approvals require `OWNER_APPROVED`, which the policy already enforces;
- separation of duties for CATEGORY_CONFLICT.

## 11. Reviewer workflow design (no UI built)

| Screen | Content | Backend support today |
|---|---|---|
| **1 Review queue** | case ID, category, filename, upload time, counts, reason, status | Data exists per case (`ColumnReviewCase`) and per intake (`IntakeRecord.received_at`). **The list itself does not exist** (no store) → needs CaseStore + `GET /cases` |
| **2 Column mapping review** | position-aware table | **Fully supported by the case model** [T]: position, header, suggestion, basis, same-header positions, claims, deterministic field, samples via `case_context`. Actual example from the backend (IN-10 + duplicate `amount`, `evidence/…3B7/examples/case_duplicate_amount_OPEN.json`) is shown below the table |
| **3 Decision confirmation** | decisions made / outstanding, missing required, ignored + reasons, duplicate selections, category conflict, eligibility to finalise | Partly. `case.effective()`, `case.mapped()`, `content_classification` exist. **No "pre-finalise" dry run:** `finalise_case` computes the summary only while finalising → add a read-only `preview_finalisation(case)` (same checks, no writes) [P] |
| **4 Outcome** | RESOLVED or HELD, rule reference, reprocess status, eligibility, preview, sidecar, audit | Supported in the transient `WorkflowResult` + audit (3B-8 events). **Not retrievable later** without CaseStore and an outcome model; rule lifecycle not reflected (P1-6) |

**Screen 2, actual backend data** (HEADER_COUNT_MISMATCH, incoming 9 / expected 8; `duplicate_incoming_headers {"amount": [4, 8]}`):

| Source position (0-based) | Incoming header | Suggested field | Basis | Status (derived) | Reviewer action |
|---|---|---|---|---|---|
| 0 | ledger_entry_id | ledger_entry_id | diagnostic_name_match | Suggested | MAP / CHANGE* / IGNORE |
| 1–3, 5–7 | account_id, posted_ts, entry_type, dc_indicator, currency, payment_reference | same names | diagnostic_name_match | Suggested | MAP |
| 4 | amount | amount | diagnostic_name_match | Duplicate (same header at 8) | CHOOSE_DUPLICATE_SOURCE |
| 8 | amount | amount | diagnostic_name_match | Duplicate (same header at 4) | CHOOSE_DUPLICATE_SOURCE / IGNORE |

\*CHANGE of a deterministically matched header is refused (RULE_CONTRADICTION). The UI should disable it, using the `deterministic` value from the context.

## 12. End-to-end test results

New module `tests/test_e2e_3b8.py`: **21 passed** (`evidence/e2e_3b8_run.txt`). Each scenario checks:
- the final decision and review state;
- provider calls;
- rule side effects;
- audit events and a chain verify;
- eligibility, and preview creation or refusal;
- provenance (sidecar SHA = source SHA; every output column equals its source column cells);
- original integrity (stored bytes = submitted bytes).

| # | Scenario | Result | Key observations |
|---|---|---|---|
| 1 | Equal count, all deterministic | ✔ | 0 calls, no rule, preview = canonical, outcome audited |
| 2 | Equal count, unfamiliar, valid recorded proposals | ✔ | 1 call (unresolved headers only) → AUTO_ACCEPT (test POC policy) → POC_AUTO rule → reprocess 0 calls → preview; audit order POC_AUTO_DECISION < RULE_CREATED < REPROCESSED |
| 3 | Equal count, ambiguous | ✔ | session → CHANGE ×4 → APPROVED → file mapping + confirmation → reprocess → preview = canonical. **Manual service calls** (no orchestrator completion) |
| 4 | Equal count, duplicate claims | ✔ | HUMAN_REVIEW + conflict case, 0 calls, RULE_CONTRADICTION on remap, HELD, no rule or preview (structural finding) |
| 5 | Different count, extra column | ✔ | audit = only INTAKE_CASE_OPENED before review; resolved → preview = canonical; 0 calls |
| 6 | Fewer columns | ✔ | HELD; not reprocessed |
| 7 | Missing and extra | ✔ | diagnostics exact; HELD (`currency`, `payment_reference`) |
| 8–9 | Identical duplicate names, chosen source | ✔ | both cells kept (`amount`, `amount [col 9]`); grouped decisions; sidecar source 4, ignored 8 |
| 10 | Extra column ignored | ✔ | sidecar ignored entry with rule ID and version; records keep the cells; rule IGNORE + reason |
| 11 | Required missing after review | ✔ | HELD; no confirmation event |
| 12 | Leave unresolved | ✔ | HELD |
| 13 | Reject | ✔ | REJECTED; audit = OPENED, REJECTED |
| 14 | Category mismatch | ✔ | 13 vs 8 → gate, never switched; IN-08 as IN-06 (11 = 11) → HOLD |
| 15 | Original modified after review | ✔ | **refused before any write** (3B-8) |
| 16 | Revoked rule | ✔ | ineligible; RULE_REVOKED audited; case still RESOLVED (documented gap) |
| 17 | Reprocessing twice | ✔ | CSV and sidecar byte-identical; 0 calls |
| 18 | Duplicate finalisation | ✔ | state guard + rule-store uniqueness; first resolution intact; orphan confirmation documented |
| 19 | Restart during review | ✔ (caller-side JSON only) | new store, log and evidence objects on the same folders; resumed; preview; chain intact |
| 19b | Two store instances (P0 regression) | ✔ | no lost intake records; a case opened by one orchestrator is completed by another |
| 20 | Provider disabled | ✔ | equal count → HOLD 0 calls; different count → HITL → resolved, 0 calls |
| — | Protection boundaries | ✔ | POC DISABLED, AI off, authority empty, packaged rules empty |

**Full regression after the 3B-8 changes** (`evidence/regression_summary.txt`):

| Check | Result |
|---|---|
| Full suite | **512 passed** (491 + 21) |
| Without the UC-042 tree | 509 passed, 3 skipped |
| Registry | in sync (19) |
| Phase 1 baseline | 445/445 |
| Phase 2 corpus | 161/161 |
| eval_3b5 | **68/68** |
| eval_3b6 | **34/34** |

## 13. Defects discovered and fixes made

| ID | Priority | Defect (root cause) | Fix | Regression test |
|---|---|---|---|---|
| D1 | **P0** | `EvidenceStore` loaded `index.json` once into a private list. Two instances on one root (two orchestrators, a CLI next to a service, a reprocess helper) each appended to their stale copy, so **the last writer silently erased the other's intake records** [T probe E8: a fresh instance could not find A's intake]. Affected intakes become "unknown" to reprocessing and case review. The index was also written in place (a crash could truncate it) | `_reload()` before every read (`find`, `check_duplicate`) and inside the lock before every append; atomic tmp+replace write. Cross-process locking remains P1-2 | `test_19b_two_store_instances_never_lose_intake_records` |
| D2 | P1 (fixed: no new architecture) | `complete_case` trusted a review context computed earlier; a stored original changed after review produced an **active rule, a category confirmation and a RESOLVED case** before reprocessing noticed [T probe E5] | `complete_case` always re-verifies (SHA, intake, header) via a fresh `case_context` and refuses a supplied context that no longer matches | `test_15_…`; 3B-7 `test_file_changed_after_review_fails_reprocessing` **updated** (now `ReviewError` before writes, instead of `ReprocessError` after; asserts no rule or events) |
| D3 | P1 (fixed) | Event types `REPROCESSED`, `HANDOFF_EVALUATED` and `HANDOFF_PREVIEW_WRITTEN` were declared but never emitted, so **outcomes and preview generation were unaudited** | `_finish` emits them (actor `smartparser-orchestrator`/`system`; rules used, provider calls, category basis, failed checks, output SHA) | `assert_outcome_audited` in scenarios 1, 2 and 5 |
| D4 | P1 (fixed) | `INTAKE_CASE_RESOLVED` did not name the confirmation or rule, so after an orphan confirmation the effective one was ambiguous | adds `confirmation_id`, `file_mapping_id` | `test_18_…` |

No expected behaviour was changed to make a test pass. The single updated 3B-7 assertion reflects the stricter D2 behaviour.

## 14. Priority list

### P0 — correctness or data integrity
| ID | Item | Status |
|---|---|---|
| D1 | Lost intake records with two evidence-store instances | **Fixed** |
| — | No other P0 found: no path produced an incorrect mapping, lost cell data, bypassed review or produced an invalid preview in the 20 scenarios and 8 probes | [T] |

### P1 — required for an operational reviewer workflow
| ID | Item | Status |
|---|---|---|
| D2–D4 | Re-verify before finalising; outcome audit events; resolution names its confirmation | **Fixed** |
| P1-1 | Persistent `CaseStore` (+ session store): list, get, resume, revisions | design §6.3, awaiting approval |
| P1-2 | Locking across processes for AuditLog, RuleStore and the EvidenceStore index (chain fork, lost update) | design §6.3 |
| P1-3 | Atomic or recoverable finalisation (FINALISING intent + recovery), idempotency key | design §6.3 |
| P1-4 | Persist the category confirmation (snapshot + rebuild from audit) | design §6.3 |
| P1-5 | One review channel per intake: a conflict file currently gets a proposal session **and** a case; a session-approved rule is never eligible but blocks a later case resolution | needs decision (§18); recommended: the case supersedes, the session becomes advisory only |
| P1-6 | Case outcome linked to rule lifecycle (`effective_outcome`) | design §6.3 |
| P1-7 | Orchestrator completion path for proposal sessions (`complete_session`), mirroring `complete_case` | design; small but changes the 3B-2/3B-6 service contract |
| P1-8 | Serialisable outcome model (`WorkflowResult` → JSON DTO) and outcome retrieval | design §10 |
| P1-9 | Authenticated reviewer identity (API binds `Reviewer` from the principal) + production authority roles | owner decision |
| P1-10 | Persist proposal records (conflict-case suggestions, dedup across restarts) | design |
| P1-11 | Structured error codes on `ReviewError` | design §10 |
| P1-12 | Read-only finalisation dry run (Screen 3) | design §11 |
| P1-13 | Reviewer API (thin FastAPI over the services and stores) | design §10, after P1-1…P1-4 |
| P1-14 | Duplicate-upload signal on gated intakes (the gate stores via `save` without `check_duplicate`, so the reviewer is not told the same bytes were already submitted) | small; design |

### P2 — user experience
- Queue filters and sorting.
- Alias-aware diagnostic suggestions on count-mismatch cases.
- Side-by-side sample comparison for duplicate claimants.
- Activity summaries and review analytics.
- Shorter preview file names (the Windows 260-character path limit, seen in 3B-7).
- A UI that disables RULE_CONTRADICTION actions up front.

## 15. Recommended next implementation phase

**Phase 3B-9 — "Durable review backend"** (backend only, no UI). This needs owner approval of §6.3 and §18 first.
1. A file-based `CaseStore` and `SessionStore`: snapshot plus index, revisions, embedded proposal record and confirmation (P1-1, P1-4, P1-10).
2. A lock file per store root for CaseStore, RuleStore, the EvidenceStore index and AuditLog (P1-2).
3. Recoverable finalisation (FINALISING plus a start-up reconciler) and idempotency keys (P1-3).
4. `effective_outcome` linked to the rule lifecycle; a serialisable outcome DTO; a finalisation dry run (P1-6, P1-8, P1-12).
5. A single review channel for conflict files and `complete_session` (P1-5, P1-7), after the owner decision.
6. Structured error codes (P1-11).
7. Then **Phase 3B-10:** a thin API over these, with authentication to be decided (P1-9, P1-13), and only after that the reviewer UI.

## 16. Exact files modified in 3B-8

| File | Change |
|---|---|
| `smartparser/intake/store.py` | D1: `_reload()`; reload in `check_duplicate`, `find` and inside `save`'s lock; atomic index write |
| `smartparser/orchestration/orchestrator.py` | D2: `complete_case` re-verifies; D3: `REPROCESSED`, `HANDOFF_EVALUATED`, `HANDOFF_PREVIEW_WRITTEN` in `_finish`; import `ReviewError` |
| `smartparser/review/intake.py` | D4: `INTAKE_CASE_RESOLVED` details + `confirmation_id`, `file_mapping_id` |
| `tests/test_e2e_3b8.py` | **new**: 21 end-to-end tests |
| `tests/test_header_gate_3b7.py` | one test updated for D2 (stricter: refused before writes; asserts no rule or events) |
| `docs/UC042_SMART_PARSER_PHASE3B8_END_TO_END_AND_REVIEW_READINESS_REPORT.md` | this report |

Not changed: the canonical definitions, packaged rules, authority policy, POC policy, AI configuration, prompts, evaluation corpora and tools.

Outside the working copy, the session's regression helper script gained a 3B-8 entry. Temporary probe folders were created and removed.

## 17. Protected-path verification

| Check | Result |
|---|---|
| UC-042 authoritative source | 107 code files hash-identical; 624 dataset files hash-identical; 0 files newer than the Phase 1 start |
| Desktop Smart Parser | 63 files hash-identical; nothing copied back |
| Clone E / original UC-042 app / demo database / audit packs | not accessed; no database used (all stores are pytest temporary folders) |
| Live provider | no call: recorded stubs only; sockets blocked in the tests; 0 network-library imports in `smartparser` |
| Provider configuration | `AIConfig` default disabled; credentials, model, region and budgets untouched |
| POC policy | `DISABLED`, `enabled=False` |
| Production authority policy | unchanged, scopes `{}` |
| Packaged rules | aliases and layouts empty; 19 proposals `proposed`, 0 approved |
| Deployment / submission | none; `submit_to_uc042` always refuses |

## 18. Outstanding owner decisions

1. **Approve the durable review backend design** (§6.3): file-based CaseStore, lock files, FINALISING recovery, idempotency keys. No new infrastructure.
2. **One review channel for conflict files** (P1-5): should the column-review case supersede the proposal session (recommended), or should both remain?
3. **Override of deterministic header matches.** May a reviewer remap a column whose header deterministically matches another field, for one file only? (Today: RULE_CONTRADICTION. Consequence: equal-count conflicts can never be completed, §1.)
4. **Production authority roles** for FILE_MAPPING, CATEGORY_CONFIRMATION, CATEGORY_CONFLICT and REVOCATION, plus separation of duties and whether IGNORE_COLUMN needs a second approver.
5. **Reviewer identity and authentication** for any API (identity provider, role mapping).
6. **Sample-value exposure.** May real cell values (the first 5 per column) be shown to reviewers in the UI?
7. **API technology.** Is the already-declared FastAPI `[api]` extra acceptable for Phase 3B-10?
8. **Unchanged from earlier phases:** the preview and sidecar as a UC-042 submission format (submission stays disabled), and enabling the POC policy or the live provider (both stay off).
