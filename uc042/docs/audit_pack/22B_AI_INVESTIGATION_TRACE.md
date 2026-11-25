> Appendix 22B to report 22 (`22_COMPLETE_UC042_PRODUCT_AND_WORKFLOW_WALKTHROUGH.md`). Read-only code trace of the Phase 8 working tree, 5 November 2026. Nothing was executed against live data; file:line references are to `uc042/`.

# Part F: February's published AI investigation, traced through the code

**Investigation:** `INV-EXC-H202602-01-6b1425b437f4`
**Exception:** `EXC-H202602-01` (Critical, OPEN, root cause `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16`)
**Pack:** `PACK-H202602-PER-2026-02-195df2e1f216`

**Artefact folder** (called "INV dir" below):
`demo_history/investigations/PACK-H202602-PER-2026-02-195df2e1f216/EXC-H202602-01/INV-EXC-H202602-01-6b1425b437f4/`

It contains `findings.json`, `evidence_packet.json`, `evidence_ledger.json`, `tool_calls.json` and `runs/0001.json`. There is no separate "manifest" file. `runs/0001.json` is the run record and holds the hashes of the extra artefacts.

**How this was produced.** Everything here was read statically. Nothing was run: no app, no tests, no database, no OpenAI call. The only Python I ran was read-only JSON parsing, a regex check and file hashing of the artefacts. Registry and authorisation *database* states are quoted from reports 17, 19 and 20, not queried.

**Paths.** Code paths are relative to `uc042/`. Frontend paths are relative to `uc042/frontend/src/`.

---

## 0. Plain-language summary

1. The analyst opens the exception and clicks **Run investigation**. A dialog shows the provider, model, limits and a charges notice. The analyst must tick a statement.
2. The backend records that authorisation, then starts a background job.
3. The job does several things without any AI:
   - re-checks the pack hash;
   - re-hashes every source file against the pack's audit trail;
   - picks a retrieval plan from the exception's root cause;
   - collects the relevant CSV rows into an **evidence packet**. February's packet holds 16 records, 3 searches, 1 missing-evidence item and 36 citable IDs.
4. OpenAI (`gpt-6-luna`, reasoning effort `medium` per report 17) receives the packet and a strict output schema. It may call **8 read-only tools**. Python executes the tools, and every returned row is added to an **evidence ledger** with its provenance.
   - In February the model made all 8 calls in one round. The ledger then held 29 records, 12 searches and 58 citable IDs.
   - The model then returned its final JSON.
5. Python validates the answer with fixed rules: every cited ID must exist, causes are not stated as facts, nothing is called resolved, missing evidence is not turned into a zero, and so on.
6. If the answer is valid, the folder is published in one atomic step under an ID derived from its content. The backend then adds it to the **publication registry**.
7. A final review may use it only if all of these hold:
   - the artefact still verifies;
   - it is registered with the same hashes;
   - no AUTHORIZATION_DISCREPANCY decision is recorded against it;
   - it passes today's validation rules.

**The February run that was published was the second attempt.** The first attempt was rejected by the `ZERO_PATTERN` rule (a false positive) and kept in `_not_published/`.

---

## 1. Selecting an exception and starting the investigation (UI → API → service)

### 1.1 UI

**Exception workspace: `components/workspace/AiPanel.tsx`**
- Header text: "V2 tools mode · reads cited records only · never changes the exception status" (AiPanel.tsx:72).
- The button only opens the dialog: `onClick={() => setAuthorising(true)}` (AiPanel.tsx:78-80). The label is "Run investigation", or "Retry investigation" when the last job did not complete.
- On confirmation, `run()` calls `data.startInvestigation(packId, exceptionId, authorization, retryOf)` (AiPanel.tsx:53-63).
  - `retryOf` is set to the previous job ID when that job finished but did not complete (AiPanel.tsx:56-57).
  - A 409 `INVESTIGATION_ACTIVE` is turned into "follow the running job" (AiPanel.tsx:60).
- The dialog context rows are the reporting period, the deterministic pack and the exception with its category, account and amount (AiPanel.tsx:82-86).
- The job is polled with `useJobPoller` (AiPanel.tsx:48).
- Failed or rejected attempts are mentioned only as a count: "N failed or rejected attempt(s) were kept by the backend and are not shown as findings" (AiPanel.tsx:101-103).

**Authorisation dialog: `components/ai/AiAuthorizationDialog.tsx`**
- Loads `GET /api/v1/ai/configuration` (AiAuthorizationDialog.tsx:26). It shows provider · model · reasoning effort, "Provider configured", the charges notice and the limits ("8 tool calls, 4 rounds, 300 s"). See lines 52-62.
- A required tick-box carries the operation statement (lines 69-70). The confirm button stays disabled until it is ticked, and also while sending or when the provider is not configured (line 47).
- On confirm it sends `{confirmed: true, provider: c.provider, model: c.model}` (line 38). A refusal keeps the dialog open and shows the server's message (lines 39-41, 71).
- Cancel sends nothing (line 46).

**HTTP call: `api/endpoints.ts:64-67`**
- `POST /api/v1/packs/{pack}/exceptions/{exc}/investigations`
- Body: `{mode:"tools", authorization:{confirmed, provider, model}, retry_of?}`

### 1.2 API

- `uc042app/api/routers/investigations.py:27-33` (`start_investigation`) passes `body.authorization` and `retry_of` to `InvestigationService.start`. It returns **202** with a Job.
- The request schema `StartInvestigationRequest` is in `uc042app/api/schemas.py:136-139`:
  - `mode: Literal["tools"]` means the API cannot request fixed mode;
  - `authorization: Optional[AiConfirmation]`, where `AiConfirmation` (schemas.py:131-133) is `confirmed: bool = False`, plus `provider` and `model`.
- `GET /api/v1/ai/configuration` (router :43-46) returns what the dialog shows, with no secrets (`ai_authorization.py:43-55`).
- `GET /api/v1/ai/confirmations[/{id}]` (router :49-61) lists the append-only authorisation records.

### 1.3 Service: `uc042app/services/investigations.py:240-278` (`start`)

The whole method runs under a per-pack lock (`self.locks.hold(pack_id)`, :245). Steps in order:

1. Load and verify the pack; check that the exception exists in it (:246-247).
2. `auth.require(INVESTIGATION, confirmation)` (:248 → `ai_authorization.py:58-70`).
   - Without `confirmed: true`: 422 `AUTHORIZATION_REQUIRED`.
   - If the provider or model the dialog showed differs from the configured one, it returns a "changed" message.
3. If changed: `auth.changed(...)` records `REFUSED_AI_CONFIGURATION_CHANGED` and raises 409 (:250-251; `ai_authorization.py:98-100`).
4. If a job for this exception is QUEUED or RUNNING: records `REFUSED_INVESTIGATION_ACTIVE` and raises 409 with that job's ID (:252-256).
5. `retry_of` must name an earlier job of the same pack and exception (:257-260). Otherwise 422, which is **not** recorded.
6. `_investigator()` (:228-238) builds the provider from the environment. It is refused when:
   - the provider is missing or misconfigured: `REFUSED_PROVIDER_NOT_CONFIGURED`, 503;
   - the provider is simulated: the offline provider is refused;
   - the provider does not support tools mode: `REFUSED_MODE_UNSUPPORTED`.
   Each refusal is recorded (:261-264).
7. The job is created as QUEUED. Its inputs are `{"mode":"tools", "workflow_version":"uc042-investigation-graph/2.0-tools", "authorization_id": AIA-…}` (:265-268).
8. The **AUTHORIZED** record is written, linked to that job ID (:269-272). If this write fails, the job is set to FAILED ("the authorisation could not be recorded; nothing was run") and never runs (:273-276).
9. Only then: `self.runner.submit(job, lambda j: self._execute(j, investigator))` (:277). The runner is a ThreadPoolExecutor inside the single backend process (`uc042app/jobs/__init__.py:29-68`).

### 1.4 What `audit.ai_execution_authorizations` records (Phase 8)

**Table definition**
- ORM: `uc042app/db/models.py`, class `AiExecutionAuthorizationRow`.
- Migration: `uc042app/db/migrations/versions/0004_ai_authorization_and_lineage.py:36-55`.
- Columns: `authorization_id` (AIA-…), `operation` (INVESTIGATION | CLOSING_SUMMARY), `result` (AUTHORIZED | REFUSED_<code>), `period_id`, `pack_id`, `exception_id`, `review_id`, `case_id`, `job_id`, `provider`, `model`, `authorized_by`, `authorized_at`, `details` (JSON).

**What goes into `details`** (`ai_authorization.py:72-90`)
- The exact statement shown: "I authorise one AI investigation of this exception by the configured model. Live API calls may incur charges. The AI uses only the approved evidence sources of this deterministic pack. It cannot resolve the exception, change the deterministic results or approve the audit." (ai_authorization.py:21-28)
- `provider_configured`, `reasoning_effort`, `retry_of`, and for a refusal the `reason`.

**Immutability and side effects**
- On PostgreSQL a trigger refuses UPDATE and DELETE (migration 0004:68-77). In file mode the store is the append-only `ai_execution_authorizations.jsonl` (`uc042app/repositories/files.py:154-160`).
- An activity-log entry `AI_AUTHORIZED` or `AI_AUTHORIZATION_REFUSED` is also appended (ai_authorization.py:83-89).

**Do not confuse it with `audit.investigation_authorizations`** (`models.py`, class `InvestigationAuthorizationRow`). That is a different table. It records APPROVED or AUTHORIZATION_DISCREPANCY decisions about **already-published** investigations (see §13).

**February's case.** February's investigation ran on 4 Nov 2026 at about 05:45 UTC through the Phase 6B application path (report 17). That was **before** migration 0004 existed (its header says "Create Date: 2026-11-04 17:00"; Phase 8 is report 20). So February has **no** AIA pre-execution record, and none was needed at the time. Its authorisation evidence is:
- report 17 (live AI calls were explicitly authorised);
- the later `investigation_authorizations` row #1, APPROVED, basis "Phase 6B (report 17)", from report 19 §7.

Per memory and report 20 §1, the live `uc042` database still needs `db-upgrade 0004` before this table exists there.

**Refusals: what is and is not recorded**
- Recorded: configuration changed, investigation already active, provider not configured or simulated, mode unsupported.
- **Not recorded:**
  - a missing or false `confirmed`: `require` raises before any record is written (ai_authorization.py:61-64);
  - an unknown pack or exception;
  - an invalid `retry_of`.

### 1.5 The job body

`_execute` (investigations.py:290-310):
1. Calls `run_investigation(pack, exception, investigator, packs_root, datasets_root, investigations_root, mode="tools", tool_limits=inv_config.tool_limits())`.
2. If the outcome is not PUBLISHED or ALREADY_PUBLISHED_IDENTICAL, the job is FAILED with the failure reason or the first 3 validation findings.
3. Otherwise it calls `registry.register_new(...)`. Success gives COMPLETED with `registry_seq`. A refused registration gives FAILED "published but not registered".

**February's two jobs (report 17 §4):**

| Job | Result |
|---|---|
| `JOB-9e1f215007cb78ea71c2b49f` | FAILED: REJECTED by the validator |
| `JOB-2f5489498d5ac1784c5b3523` | the retry (`retry_of`): COMPLETED, registry seq 1, NEW_PUBLICATION |

---

## 2. How the backend retrieves relevant evidence (routing and retrieval)

### 2.1 The graph

The workflow is a LangGraph graph in `uc042lib/investigation/graph.py:301-325`. The nodes run in this order:

`load_investigation_case` → `identify_investigation_scope` → `route_investigation` → `retrieve_<route>` → `build_evidence_packet` → `ai_investigation` → `validate_findings` → `persist_findings`

Any node error jumps straight to `validate_findings`, which writes a FAILED result (graph.py:291-299).

### 2.2 Inputs come only from approved roots (`uc042lib/investigation/roots.py`)

- The **historical-demo** profile (roots.py:49-55) uses `demo_history/packs`, `demo_history/datasets` and `demo_history/investigations`, for periods PER-2026-01 to PER-2026-08.
- The backend picks the profile from the pack's period (`packs.root_set(pack_id)`; investigations.py:291).
- `check_input_root` (roots.py:86-101) refuses any root that lies inside, or contains, `verification/`, `golden/`, `tests/` or `UC042_JAN_AUG_HISTORICAL_DEMO/`. That is why `demo_history/` itself can never be a root.
- `retrieval._inside` (retrieval.py:26-33) refuses any path outside the root, any forbidden directory part, and the planted-answer filenames `answer_key.json`, `mutations.json`, `SCENARIO_NOTES.md`, `scenario.json` and `scenario_definition.json` (config.py:120-123).

### 2.3 Case: what the pack itself says (`packet.py:20-42`, `build_case`)

The case is built only from `pack.json`:
- the exception row;
- its affected control results (`affected_result_ids`);
- its investigation group and candidate relationships;
- related exceptions;
- missing-evidence items for this exception and its related exceptions.

**February:** 15 affected results, no group, no candidates, no related exceptions, one missing item `MISS-01` (evidence_packet.json:329).

### 2.4 Scope (`packet.py:69-80`)

The scope parses the root-cause string into keys (`parse_root`, packet.py:45-66). For `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16` the keys are `{"account_id":"SGA-EUR-01","date":"2026-02-16"}`. The packet's `investigation_scope.keys` shows exactly this.

### 2.5 Routing (`routing.py:23-41`)

Deterministic, with no AI:
1. If there is an unverified candidate relationship, the route is `unverified_relationship`.
2. Otherwise the root-cause kind decides through `KIND_ROUTE` (routing.py:7-16).
3. Otherwise, if all results are INSUFFICIENT_EVIDENCE, the route is `insufficient_evidence`.
4. Otherwise the route is `generic`.

**February:** `MISSING_BANK_EVIDENCE` gives `missing_bank_evidence`. The run record shows `{"node":"route_investigation","route":"missing_bank_evidence"}`, and findings.json `investigation_route` agrees.

### 2.6 Retrieval plans (`packet.py:118-306`)

`retrieve(route, case, store)` (packet.py:295-306) works in two passes:
1. `apply_plan_for` (packet.py:278-292) on the primary exception: always `plan_cited` first, then the plan for the exception's kind.
2. The same again for each related exception whose root-cause kind has not been seen yet (or for all of them on the unverified route). February has no related exceptions.

**`plan_cited` (packet.py:118-122)** fetches every record the engine's control results cite in `evidence_ids`. In February these 14 records were all fetched this way:
- `IN-01:2026-02-16`, `IN-02:SGA-EUR-01`
- `IN-08:ST-SGA-EUR-01-20260213-EOD`, `IN-08:…20260217-EOD`
- five `IN-10:LE-EUR-0216-000n`
- `IN-06:ERL-SGA-EUR-01-20260216`
- `IN-12:AQ-EUR-20260216`, `IN-12:SB-EUR-20260216`
- `IN-11:TX-0216-00014`, `IN-11:TX-0216-00020`

Each has `retrieved_via` "cited by control result …" and a relationship `cited_by_control_result`. Example: `C07-BANK-EVIDENCE|2026-02-16/SGA-EUR-01 → IN-06:ERL-SGA-EUR-01-20260216`, join key `ext_recon_id=ERL-SGA-EUR-01-20260216`.

**`plan_missing` (packet.py:205-223)** is the missing_bank_evidence plan. For the account and date it:
- adds the firm's external reconciliation record (IN-06). It was already present.
- **probes** the 17:00 confirmation (IN-07), the end-of-day statement (IN-08) and bank entries booked that day (IN-09). These probes become `SEARCH-01`, `SEARCH-02` and `SEARCH-03`; all three were NOT_FOUND in February (evidence_packet.json:487 and following).
- adds the **adjacent-day** statement and confirmation (previous and next reconciliation day) as "context only; not a substitute". February gained `IN-07:ST-SGA-EUR-01-20260213-1700` and `IN-07:ST-SGA-EUR-01-20260217-1700`, with `retrieved_via` "adjacent-day confirmation (context only; not a substitute)". The 13th and 17th statements were already in.
- adds the cash-book entries posted that day (already in) and the settlement batches due that day (already in).

**Result:** 16 records. The run record shows `retrieve_relevant_evidence[missing_bank_evidence] … "records": 16`.

**Why these files.** Each plan names the files that can evidence its type of discrepancy:
- for missing bank evidence: the bank side (IN-07 confirmation, IN-08 statement, IN-09 entries), the firm's own claim (IN-06) and the firm-side movements that would need bank support (IN-10 cash book, IN-12 batches);
- the engine's own citations are always included.

The other plans cover the other routes:
- `plan_bank_ledger`: external record, confirmation, statement and entries for the date and the next reconciliation day, timing items, batches joined by reference, discrepancy log;
- `plan_settlement`: batch, lines, transactions, bank and cash-book entries by batch reference, acquirer top-ups;
- `plan_customer`: snapshots either side of the roll-forward, transactions between the 17:00 points, refunds, settlement lines;
- `plan_unmatched`: the bank entry, its statement, the confirmation, external record, cash book and batches on the booking day, and a reference search across files.

**No plan exists for `unverified_relationship`, `insufficient_evidence` or `generic`.** Those routes get `plan_cited` plus the kind plan of each exception.

---

## 3. How source files are hash-verified

There are three layers, all fail-closed.

**1. Pack integrity** (`retrieval.py:49-63`, `load_pack`). Every investigation starts here (graph.py:88), and the backend's `packs.load` also runs it. It checks that:
- the pack ID matches the regex;
- `metadata.pack_id` equals the requested ID;
- the recomputed `content_hash(pack)` equals `audit_trail.pack_content_sha256`;
- the pack ID ends with the first 12 hex characters of that hash.

February: `pack_content_sha256` is `195df2e1f216149c…`, and the pack ID ends `…-195df2e1f216`. On failure: `RetrievalError("pack content hash does not verify; refusing to investigate a modified pack")`.

**2. Source-file integrity** (`retrieval.py:80-95`, `EvidenceStore.__init__`). For **every** entry in `pack.audit_trail.inputs`, all 17 in February (IN-01 to IN-17), it:
- resolves the file inside the dataset folder (`demo_history/datasets/2026-02/…`);
- requires that the file exists;
- computes its SHA-256 and compares it with `sha256_actual` recorded when the pack was generated.

On a mismatch: `RetrievalError("source file changed since pack generation: <path>")`. A missing file raises "source file missing". Only after all files pass are rows parsed (`load_sources`, retrieval.py:96-100). The verified hash is stamped on every record as `file_sha256` (retrieval.py:109-114).

February example: the pack's audit trail lists `IN-06 source_data/external_recon_records_2026-02.csv sha256_actual e36a4e0878e1dfcc…ddad8`. The packet record `IN-06:ERL-SGA-EUR-01-20260216` carries `"file_sha256": "e36a4e0878e1dfcce73392e4362ee455e76014db8a34c78a14319f80655ddad8"`, `"source_file": "source_data/external_recon_records_2026-02.csv"` and `"source_line": 23`. The same match holds for IN-05 (`65119291…`), used later by a tool.

**When verification runs.** An `EvidenceStore` is built, and **all files re-hashed**:
- in the retrieval node (graph.py:120);
- **again** in tools mode, just before the tool loop (graph.py:155);
- by the no-AI "source evidence" endpoint (investigations.py:186-206).

**On a mismatch:** the node returns `error`, `validate_findings` writes a FAILED / NOT_VALIDATED result, and `persist` stores it under `_not_published/` (§12). The job becomes FAILED. No model call is made if the failure happens before `ai_investigation`.

**3. Artefact integrity after publication.** `verify_published` (§12) and the registry pins (§13) check that the stored packet, ledger and findings have not changed.

---

## 4. How the evidence packet is built (structure and record IDs)

The packet is built by `build_packet` (`packet.py:347-381`). Top-level keys of February's `evidence_packet.json`:

| Key | February content |
|---|---|
| `packet_version` | `uc042-evidence-packet/1.0` (config.py:21) |
| `pack_id`, `pack_content_sha256` | the pack's identity |
| `investigation_route`, `investigation_scope` | §2 |
| `exception` | a whitelisted view of the exception (packet.py:353-356): status OPEN, review_status AWAITING_HUMAN_REVIEW, severity Critical, … |
| `related_exceptions`, `investigation_group`, `candidate_relationships` | `[]`, `null`, `[]`. Candidates would carry the note "UNVERIFIED — NOT EVIDENCE-BACKED…" (packet.py:364-365) |
| `control_results` | 15 engine results, quoted verbatim (packet.py:341-344). Example: `C08-DIFFERENCE|2026-02-16/SGA-EUR-01`, outcome INSUFFICIENT_EVIDENCE, `reported: "0.00"`, note "bank evidence not provided; difference not computed" |
| `source_records` | 16 records |
| `relationships` | 18 `from → to` edges with join keys |
| `searches` | SEARCH-01..03, all NOT_FOUND |
| `missing_evidence` | MISS-01: "15 check result(s) could not be assessed…", `value_shown: "not available"` |
| `conflicts` | `[]` (deterministic, from `detect_conflicts`, packet.py:319-338) |
| `retrieval_truncated` | `false` (the cap is 160 records, config.py:126) |
| `conventions` | sign conventions: bank C = in; cash book D = in; 17:00 Europe/London reconciliation point |
| `allowed_citation_ids` | 36 IDs (packet.py:384-392) |
| `packet_sha256` | `760adfe5480557d379c65d32069e9ed463549ead6fe5d1073ef6d7ae87e6ea34` (evidence_packet.json:363): SHA-256 of the canonical JSON of everything else (packet.py:380) |

### Record and ID formats

**One source record** (retrieval.py:109-114) carries:
- `evidence_id`: `IN-xx:<primary key>`, for example `IN-06:ERL-SGA-EUR-01-20260216`;
- `file_id`, `record_type` (for example "External reconciliation records (as reported by the firm)");
- `source_file`, `source_line`, `file_sha256`;
- `retrieved_via`, `join_key`;
- `fields`: all CSV columns. For example `bank_balance_reported "73199.44"`, `ledger_balance_reported "73199.44"`, `difference_reported "0.00"`, `bank_statement_id "ST-SGA-EUR-01-20260216-1700"`, `timing_difference_claimed "false"`.

**Other citable ID types:**

| Type | Format | Example |
|---|---|---|
| Control result | `CHECK|scope` | `C14-COVER|IN-07 2026-02-16/SGA-EUR-01` |
| Exception | `EXC-…` | `EXC-H202602-01` |
| Search | `SEARCH-nn` | `SEARCH-01` |
| Missing item | `MISS-nn` | `MISS-01` |
| Conflict | `CONF-nn` | none in February |
| Candidate and group | their own IDs | none in February |

**February's 36 citable IDs:** 16 record IDs, 15 result IDs, `EXC-H202602-01`, `MISS-01` and `SEARCH-01..03`.

---

## 5. How retrieval selects relevant records (rules and limits)

**Selection rules**
- Retrieval starts **only** from what the deterministic engine cited, then widens **only** through verified join keys: same account and date, reference equality, `batch_id`, `txn_id`, `original_txn_id`, `statement_id`, `recon_ref` (packet.py docstring :1-7).
- There is **no amount matching and no fuzzy matching**.
  - Example: `plan_bank_ledger` reaches a batch only where "batch.expected_bank_reference = cashbook.payment_reference" (packet.py:145-148).
- Negative lookups are recorded as citable `SEARCH-nn` items with `result: NOT_FOUND` instead of being silently dropped (`Collector.search`, packet.py:108-115).
- A repeated identical search reuses its ID.
- De-duplication: a record is stored once, under the **first** `retrieved_via`, and later relationships are still added (packet.py:93-106).
  - That is why `IN-10:LE-EUR-0216-0001` shows "cited by control result …", not "cash-book entries posted on the date".

**Limits**
- `MAX_RECORDS = 160` per packet or ledger (config.py:126). Past that, `retrieval_truncated` becomes true (packet.py:98-100).
- Packet records omit columns that start with `_` (retrieval.py:114).

**Content hygiene**
- The packet never contains dataset folder names, scenario names, answer keys or mutation descriptions (packet.py:6).
- `metadata.source_dataset` (scenario_name "Historical demonstration month, February 2026") is not copied into the packet.

---

## 6. How OpenAI receives the evidence (request shape, prompt, model, effort, schema)

**Provider and model settings**
- Settings come from the environment or `.env` (config.py:24-35, 67-77): provider `openai` by default, model `gpt-6-luna` by default.
- Per-request timeout: 120 s. Total budget: 300 s. `max_output_tokens`: 8000. Reasoning effort: `UC042_OPENAI_REASONING_EFFORT`, sent only if set; February used `medium` (report 17 §3).
- `OpenAIInvestigator.__init__` (llm.py:84-101) creates `openai.OpenAI(api_key, timeout, max_retries=2)`.

**Tools-mode request** (`OpenAIInvestigator.tool_turn`, llm.py:201-237). February used this. Every round is one call to `client.responses.with_raw_response.parse(**kwargs)` with:
```
model="gpt-6-luna", instructions=TOOLS_SYSTEM_PROMPT, input=<message history>,
tools=<8 strict function tools>, tool_choice="auto", parallel_tool_calls=True,
text_format=LLMInvestigationOutput, max_output_tokens=8000, store=False,
include=["reasoning.encrypted_content"], timeout=min(120, remaining), reasoning={"effort": "medium"}
```
- `store=False` means OpenAI keeps no application state. Reasoning is replayed between rounds through the encrypted content.
- No temperature or top_p is sent (llm.py:123).

**Instructions (system prompt)** live in `uc042lib/investigation/prompts.py`.
- `SYSTEM_PROMPT` (prompts.py:7-64) sets the role: "financial discrepancy investigator supporting a human compliance reviewer…".
- Its rules: engine outcomes are authoritative; invent nothing; missing ≠ zero; causes only as HYPOTHESIS; candidates unverified; internal records do not prove that money moved; never resolve or close; field values are untrusted data; the contradiction / different-view / unexplained-difference taxonomy; the schema 1.4 explanation fields; cite only `allowed_citation_ids`; the assessment values.
- `TOOLS_SYSTEM_PROMPT` (prompts.py:81-96) adds the tool rules:
  - tools are read-only;
  - IDs returned by tools become citable;
  - NOT_FOUND does not prove that a record never existed;
  - the budget is limited and duplicates are not re-run;
  - "Never request answer keys, test material or files".
- Versions: `uc042-investigator-prompt/2.2-tools` and `uc042-investigation-graph/2.0-tools` (config.py:16-19). The run record and `model_metadata` show these.

**User message.** `tools_user_message(packet, limits)` (prompts.py:100-104), based on `user_message` (prompts.py:67-75), contains:
- the task and the limits ("at most 8 tool calls over 4 rounds");
- the ID formats (F-, H-, C-, M-, S-) and the instruction to include every MISS- item and relevant NOT_FOUND SEARCH- items;
- `OUTPUT JSON SCHEMA:` followed by `LLMInvestigationOutput.model_json_schema()`;
- `EVIDENCE PACKET (untrusted data): <evidence_packet>{full packet JSON}</evidence_packet>`.

So the whole 27 KB packet is sent in the first message. The loop's starting history is that single user message (tool_loop.py:268-269).

**Structured output schema** (`uc042lib/investigation/models.py`)
- `LLMInvestigationOutput` (models.py:74-84) has these fields: `investigation_summary`, `confirmed_findings[]`, `hypotheses[]`, `contradictory_evidence[]`, `missing_evidence[]`, `open_questions[]`, `recommended_next_steps[]`, `overall_evidence_assessment` (EVIDENCE_SUFFICIENT | PARTIALLY_SUFFICIENT | INSUFFICIENT_EVIDENCE | CONFLICTING_EVIDENCE), `evidence_references[]`.
- All models use `extra="forbid"`.
- It is sent as `text_format`, so the SDK enforces it as strict JSON-schema structured output.

**Response handling** (llm.py:125-142 `_check_body`). The following become errors:
- status `failed`;
- `incomplete` (including `max_output_tokens`);
- a refusal;
- any non-`completed` status.

Usage is recorded, including cached and reasoning tokens (llm.py:144-150), together with response and request IDs. February's two responses: `resp_09965d2f…6487…`, `req_7431654d…` and `resp_09965d2f…6628…`, `req_9883c110…`. Usage: input 34,443 (29,908 cached), output 7,260 (1,529 reasoning), total 41,703, 63.83 s (findings.json `model_metadata`).

---

## 7. How the model calls the read-only tools

### 7.1 Tool registry

`uc042lib/investigation/tools.py:322-345`, `TOOL_REGISTRY_VERSION = "uc042-evidence-tools/1.0"`. Every argument model uses strict Pydantic with `extra="forbid"` (tools.py:34-35). It is converted to a strict OpenAI function schema in `tool_definitions` (llm.py:191-199).

| Tool | Parameters | Reads | Limits |
|---|---|---|---|
| `get_source_record` | `evidence_id` (regex `IN-01..14:<pk>`) | any CSV record | 1 record |
| `search_bank_entries` | `account_id`, optional `bank_reference`, `date_from`/`date_to` | IN-09 | a reference **or** a date range is required; range ≤ 7 days (config.py:91) |
| `get_cashbook_entries` | `account_id`, optional `payment_reference`, date range | IN-10 | reference or range ≤ 7 days |
| `get_settlement_batch` | `batch_id` | IN-12 header + IN-13 lines + IN-11 transactions referenced | records per call |
| `search_customer_transactions` | `txn_id` alone, **or** `client_id` + date range (≤ 31 days) + optional `transaction_type` | IN-11 | — |
| `get_customer_balance_snapshots` | `client_id`, `currency`, date range ≤ 31 days | IN-03 | — |
| `get_reconciliation_evidence` | `account_id`, `currency` (must match the account, checked against IN-02), `date` | IN-06, IN-07, IN-08, IN-05 + IN-14 log entries for the IN-06 record | one search per file |
| `follow_relationship` | `evidence_id` (must already be in the evidence), `relationship` (one of 8 fixed joins, tools.py:130-142) | the target file | no free joins |

There are no write tools, no paths, no free-text predicates and no arbitrary joins (tools.py:1-9). Unknown accounts are refused with a `ToolInputError` (tools.py:198-205).

### 7.2 Budget and limits

Defaults are in `config.py:85-107`; the environment can override them.

| Limit | Default | Enforced at |
|---|---|---|
| Tool calls per investigation | **8** (`UC042_TOOLS_MAX_CALLS`), counting rejected and duplicate calls | tool_loop.py:142-146 |
| Rounds (model → tools → model) | **4** (`UC042_TOOLS_MAX_ROUNDS`) | tool_loop.py:142 |
| Records per call | **25** (`UC042_TOOLS_MAX_RECORDS_PER_CALL`) | `ToolCall.add`, tools.py:165-182; truncated results set `truncated` and a note |
| Total records | **160** | Collector |
| Estimated input tokens | **150,000** (`UC042_TOOLS_MAX_INPUT_TOKENS`), estimated as characters / 3 before every request | tool_loop.py:81-84, 99-101 |
| Per request | 120 s | — |
| Whole investigation, wall clock | **300 s** (`UC042_LLM_TOTAL_TIMEOUT_SECONDS`) | tool_loop.py:96-98 |
| LangGraph recursion limit | 8 × (rounds + 4) = 64 | tool_loop.py:273 |

**When the budget runs out**
- Further requests come back as `BUDGET_EXHAUSTED` and are not run.
- The outputs of the last allowed round carry the message "The tool budget is now exhausted. Do not call more tools; return your final JSON…" (tool_loop.py:206-219).
- If the model asks for a tool again after that: `budget_exhausted_without_findings` FAILED (tool_loop.py:129-131).
- An invalid final answer gets **one** correction message, then fails (tool_loop.py:123-128).

**Loop shape** (tool_loop.py:241-257):

`llm_step` → `inspect_response` → (`validate_tool_request` → `execute_tools` → `append_tool_results` → `llm_step`) or `extract_structured_findings`, or `controlled_failure`.

### 7.3 February's loop (`tool_calls.json` and `runs/0001.json`)

**First model call:** 8 parallel function calls in a single response. All have `round: 1` and `requested_at` 05:45:06.216-223Z.

| # | Tool | Arguments | Status | Result |
|---|---|---|---|---|
| 1 | `get_settlement_batch` | `AQ-EUR-20260216` | OK | 7 IDs returned, 6 new: 4 IN-13 lines and `IN-11:TX-0216-00015`/`16`. The IN-12 header was already in the packet |
| 2 | `get_settlement_batch` | `SB-EUR-20260216` | OK | 7 returned, 6 new |
| 3 | `get_reconciliation_evidence` | `SGA-EUR-01, EUR, 2026-02-16` | OK | IN-06 (already in) and **new `IN-05:IRR-EMONEY-EUR-20260216`**; SEARCH-04 FOUND, 05 NOT_FOUND (IN-07), 06 NOT_FOUND (IN-08), 07 FOUND (IN-05) |
| 4-8 | `search_bank_entries` | `SGA-EUR-01` with references `E2E-EUR-0216-L01`, `AQ-EUR-20260216`, `TOPUP-EUR-20260216`, `SB-EUR-20260216`, `E2E-EUR-0216-R01` | all NOT_FOUND | SEARCH-08..12 |

After this round, 8 calls had been used out of 8, so `append_tool_results` marked the budget as exhausted. The **second** model call returned the final JSON.

Summary (findings.json `tool_summary`): `llm_calls 2, tool_calls_requested 8, tool_rounds 1, tools_executed 8, deduplicated 0, rejected_or_failed 0, refused_budget 0, records_initial 16, records_final 29, stop_reason "final_answer"`. The run trace shows `ai_investigation[tools] … "seconds": 63.828, "llm_calls": 2, "tool_calls": 8, "rounds": 1`.

---

## 8. How tool responses are added to the evidence ledger

1. **Validation.** `validate_tool_request` (tool_loop.py:135-153) parses each request with `tools.parse_request` (tools.py:348-363): it checks the registry name, that the arguments are a JSON object, and the strict Pydantic model. Rejected requests are answered with `{"status":"REJECTED","error":…}` and still count toward the budget.
2. **Execution.** `execute_tools` (tool_loop.py:156-203):
   - rebuilds a `Collector` from the current ledger (`collector_from_packet`, packet.py:402-411);
   - de-duplicates on the canonical `(tool, sorted-args)` key (tool_loop.py:87-88, 171-176). A duplicate gets `DEDUPLICATED` and its earlier IDs;
   - runs the tool through the hash-verified `EvidenceStore`.
3. **Adding records.** `ToolCall.add` (tools.py:165-182) adds records through the **same Collector**, so they get the same provenance fields as packet records. `retrieved_via` is prefixed `tool <name>:`; February example: "tool get_settlement_batch: settlement lines of the batch". Relationships are added too, for example `IN-12:AQ-EUR-20260216 → IN-13:SL-AQ-EUR-20260216-0001`, relationship `line.batch_id`. Every search becomes a new `SEARCH-nn`, continuing from SEARCH-03.
4. **Rebuilding the ledger.** After each round `build_ledger` (packet.py:414-424) builds a new ledger:
   - a copy of the packet without `packet_sha256` and `packet_version`;
   - plus `ledger_version`, `initial_packet_sha256` and the accumulated records, relationships and searches;
   - conflict detection is re-run;
   - `allowed_citation_ids` is recomputed and `ledger_sha256` set.
   New deterministic conflicts are attached to the last tool output (tool_loop.py:197-199). February had none.
5. **Reply to the model.** Each call is answered with `{"type":"function_call_output","call_id":…,"output": json(payload)}` (tool_loop.py:216). The payload (tools.py:189-195) contains `status`, `evidence_ids`, `new_evidence_ids`, `already_in_evidence`, `search_ids`, `truncated`, the **full new records** (fields and provenance) and a note.
6. **Transcript.** One row per call (tool_loop.py:164-195, written to `tool_calls.json` at graph.py:273-277), holding the call ID, tool, round, arguments, status, evidence and search IDs, records returned, truncation, error and latency.

**February's ledger** (`evidence_ledger.json`):
- `ledger_version uc042-evidence-ledger/1.0`
- `initial_packet_sha256 760adfe5…` (line 301), which equals the packet's hash
- `ledger_sha256 42ff6356e7f3774cb7e4d2b40bc3d3fd50b933c614e31790fb5c05993573eaa5` (line 348)
- 29 records, 12 searches, 58 citable IDs: the 36 packet IDs plus 13 new records and SEARCH-04..12

**In the UI**, `components/workspace/evidence.tsx:46-51` (`recordOrigin`) marks any record whose `retrieved_via` starts with "tool " as **"Retrieved by an AI tool call"** and every other record as **"Engine retrieval (no AI)"**. A tool-retrieved record is still a source record, never an AI finding (evidence.tsx:1-5).

---

## 9. How citations are validated

`validate_output(out, evidence, case)` lives in `uc042lib/investigation/validation.py:102-155` and is called from graph.py:241-250. **In tools mode the evidence checked against is the ledger, not the packet** (graph.py:242). Any error means `validation_status: REJECTED`, and the result is not published. No LLM is used to validate.

**Citation rules**
- Every ID cited anywhere must be in `allowed_citation_ids`, otherwise "cites IDs not present in the evidence packet". The places checked are: findings' `evidence_ids` and `supporting_records`; hypotheses' supporting and contradictory evidence; contradictions' `evidence_ids` and `compared_evidence`; missing items' `related_ids`; and `evidence_references`. See validation.py:89-99 and 111-113.
- Each confirmed finding must cite at least one source record, control result or search (:115-116).
- `supporting_records` must be source record IDs (:117-118).
- A confirmed finding must not cite an unverified candidate relationship (:119-120).

**Wording rules**
- No cause words ("root cause", "caused by", "the cause is", "due to", "because of") in a finding's claim or explanation (:121-126), nor in the 1.4 `title` or `establishes` fields (:76-81).
- No resolution wording ("…is resolved/closed/cleared/approved/reconciled", "compliance opinion:", "is compliant") in the summary or findings (:129-134), nor in any explanation field (:82-83).
- No claim that evidence "does not exist" or "never existed", unless qualified as "…in the supplied data", or negated as in "not that such records never existed" (:10-19, 135-140).

**`ZERO_PATTERN`** (validation.py:9; applied at :127-128):
```
\b(bank )?balance\b[^.;]{0,40}\b(was|is|of|=)\s*(£|€)?0(\.00)?\b
```
- It applies only when the evidence has any `missing_evidence` item.
- It checks confirmed-finding claim and explanation text.
- A match gives "appears to substitute zero for a balance while evidence is missing".

**February is exactly this case.** `MISS-01` exists, and the firm's own records report `difference_reported "0.00"`.
- **Rejected attempt 1.** F-03 claim: "…a 73199.44 EUR ledger **balance and a reported difference of 0.00** EUR, but the engine marks…". My regex check shows the matched text `'balance and a reported difference of 0.00'`. The result is in `_not_published/…/2026-11-04T054432+0000-c392e113.json:452-454`: `"validation_status": "REJECTED"`, `"F-03: appears to substitute zero for a balance while evidence is missing"`.
- **Published attempt 2.** F-02 says "…a bank balance and ledger balance of 73199.44 EUR and a reported difference of 0.00 EUR". It passes because `[^.;]` cannot cross the decimal point in "73199.44". I checked all 7 published findings; none match.
- Report 17 §6 calls this a **false positive**: the model was quoting a *reported* figure and calling it unverified. The validator was deliberately not changed.

**Contradiction rules** (validation.py:39-59). A contradiction must compare exactly 2 distinct IDs and explain "same measure and scope" in at least 20 characters. Neither side may be MISS-, a NOT_FOUND SEARCH- or a candidate. The two sides must not come from different reconciliation views (internal IN-05/C04-C06, external IN-06/07/08/C07/C08, client IN-03/CBAL). It must not state a cause.

**Missing-evidence rules**
- Every packet MISS- item must be preserved in some `missing_evidence[].related_ids` (:144-147).
- `EVIDENCE_SUFFICIENT` is forbidden while anything is missing (:148-149).

**Other checks**
- The pack identity must be unchanged between case and packet (:150-151).
- `evidence_references` is normalised to the set actually cited. Normalising adds a note, not an error (:152-154).

**What happens on failure**
- REJECTED → `persist` writes to `_not_published/` → the job is FAILED with the first findings as `error_summary` (investigations.py:300-302).
- The analyst can retry with `retry_of`. February's retry is attempt 2.
- Validation runs **again** whenever eligibility is checked, under the *current* rules (§13).

---

## 10. Confirmed findings versus hypotheses (statuses and fields)

**Confirmed finding** (`ConfirmedFinding`, models.py:24-33)
- `finding_id` `F-nn`, `claim` (at least 10 characters), `explanation`, `evidence_ids` (at least 1), `supporting_records` (source records only).
- Schema 1.4 fields: `title` (5-160 characters), `audit_relevance`, `establishes`, `does_not_establish`.
- There is no status field. It is "EVIDENCE_BACKED" in the Python-derived `classification_summary` (validation.py:158-179).
- It must cite real evidence and may not state a cause.

**Hypothesis** (`Hypothesis`, models.py:36-43)
- `hypothesis_id` `H-nn`, `possible_explanation`, `supporting_evidence[]`, `contradictory_evidence[]`, `limitations`, `status: Literal["HYPOTHESIS"]` (the only allowed value), and `rationale` (1.4).
- Its citations must be allowed IDs, but it may cite MISS- and SEARCH- items. It is not subject to the cause-word ban: causes belong here.

**February** (findings.json):
- 7 confirmed findings. Example F-05, "Cash-book entries lack matching bank evidence":
  - `establishes`: "The firm's cash book contains the five cited entries… The specified bank-entry searches returned NOT_FOUND in the supplied data."
  - `does_not_establish`: "…that any entry reached or left the bank…"
  - cites `IN-10:…0001-0005`, `CASH-BANK-LINK|…` and `SEARCH-03`, `SEARCH-08..12`.
- 1 hypothesis, H-01 (findings.json:284, `"status": "HYPOTHESIS"`):
  - `possible_explanation`: "Bank activity corresponding to some firm-recorded entries may have occurred, but the supporting statement and bank-entry records are absent…"
  - `limitations`: "No supplied bank confirmation, statement or bank entry verifies that activity occurred."
  - supporting evidence includes `MISS-01` and `SEARCH-01..03`.

**Envelope (`InvestigationResult`)**
- Fixed values: `exception_resolution: "NOT_RESOLVED_BY_INVESTIGATION"` (models.py:113; findings.json:275) and the statement "AI investigation findings are an aid to human review. They do not change any deterministic control outcome, do not resolve or close any exception, and are not a compliance opinion." (models.py:133-134).
- The model cannot set these, nor `validation_status`, `classification_summary` or the IDs. Python wraps them (graph.py:243-252).

**UI**
- Separate tabs, "Observations" and "Hypotheses", with the notice "Hypotheses are possible explanations the evidence does not establish. None is a finding or a cause." (AiPanel.tsx:134-141).
- The InvestigationPage heading reads "Hypotheses (n) · not established" (InvestigationPage.tsx:72).

---

## 11. How missing evidence and conflicts are represented

**Missing evidence exists at three levels**
1. **Engine:** `missing_evidence_register` items, for example `MISS-01` with `"value_shown": "not available"`. They go into the packet unchanged.
2. **Searches:** `SEARCH-nn` with `result: NOT_FOUND`. These come from the retrieval plan (SEARCH-01..03) and from tools (SEARCH-05, 06, 08-12). The wording is "not found in the supplied data", never "does not exist".
3. **AI output:** `MissingEvidenceItem` (models.py:59-64) has `M-nn`, `description`, `expected_source`, `impact` and `related_ids`.

February's `M-01` covers `MISS-01`, SEARCH-01/02/03/08-12 and all 15 result IDs. Its `expected_source` reads "…obtain the underlying bank records or authenticated bank-provided copies."

`classification_summary.evidence_gaps` (validation.py:161-171) splits gaps into `engine_missing_evidence`, `searched_not_found` and `additional_gaps_identified_by_ai`. February: `{"engine_missing_evidence":["M-01"], "searched_not_found":["M-01"], "additional_gaps_identified_by_ai":[]}` plus the 10 NOT_FOUND searches.

Missing values are never treated as zero: the prompt says so, and the validator's `ZERO_PATTERN` and `EVIDENCE_SUFFICIENT` rules enforce it (§9).

**Conflicts exist at two levels**
1. **Deterministic** `CONF-nn` from `detect_conflicts` (packet.py:319-338):
   - an engine FAIL whose computed value differs from the reported value;
   - IN-06 claiming a timing difference while the engine found none;
   - an IN-14 log entry marked RESOLVED while the exception is still OPEN.
   They are recomputed over the ledger after each tool round. February had none.
2. **AI** `ContradictoryItem` `C-nn` (models.py:46-56), with exactly 2 `compared_evidence` IDs and a "same measure and scope" explanation. February had none.
   - The AI explicitly treated the internal-versus-external figures as **different views**, not a contradiction. F-03 explanation: "It is a different reconciliation view from the external reconciliation… the figures are not contradictory merely because they are comparable numerically."
   - Summary: "No actual contradiction is established."

**Overall assessment:** `INSUFFICIENT_EVIDENCE` (findings.json:427).

**UI:** the "Gaps & conflicts" tab shows GapCard, ConflictCard and UnverifiedCard (AiPanel.tsx:142-148).

---

## 12. Publication: atomic write, registry entry, verification, hashes, and `_not_published`

### 12.1 Write-once persistence (`uc042lib/investigation/persistence.py:169-202`)

**Investigation ID** (persistence.py:31-42, set at graph.py:251-252):
- `INV-<exception>-<first 12 hex of SHA-256 over canonical {findings without investigation_id, investigated_at, model_metadata; model_metadata without usage and provider_response; packet_sha256}>`.
- It is a **content address**. In tools mode the findings include `evidence_ledger_sha256`, so the evidence is part of the identity. A rerun therefore always gets a new ID; nothing is overwritten.

**VALID and COMPLETED → `_publish`** (persistence.py:150-162):
- `findings.json`, `evidence_packet.json`, `evidence_ledger.json`, `tool_calls.json` and `runs/0001.json` are written into a temporary sibling directory `.tmp-…`.
- That directory is then moved into place with **one `os.replace`**. On any error the staging directory is deleted, so no partial artefact is left.
- The target is `<investigations_root>/<pack>/<exception>/<investigation_id>/`. `_safe_dir` refuses path escapes.

**Same ID already exists**
- If the findings are identical apart from `investigated_at`, a new `runs/NNNN.json` is appended with outcome `ALREADY_PUBLISHED_IDENTICAL`, through an exclusive hard link (persistence.py:88-115).
- If they differ: `ImmutabilityError`, which is never caught or ignored.

**Run record** (graph.py:268-279; persistence.py:177-178). February's `runs/0001.json` holds `investigation_mode tools`, the workflow and prompt versions, the full node `trace`, `route`, `artefact_sha256` for the extra files, `recorded_at 2026-11-04T05:46:02+00:00` and `outcome PUBLISHED`. The extra-file hashes are:
- `evidence_ledger.json: b89ccf4bf145…f7843`
- `tool_calls.json: 5c60e9daccc8…464dc`

I re-hashed both files with `sha256sum`; they match exactly.

### 12.2 `verify_published` (persistence.py:45-81)

A read-only check, re-run at every eligibility evaluation. It checks that:
- the packet's self-hash equals `packet_sha256`;
- the findings' `evidence_packet_sha256` equals the packet's hash;
- the investigation ID, **recomputed** from the stored findings, equals both the stored ID and the folder name;
- the ledger self-hash is correct, and the ledger is the one the findings and packet point to (`ledger_sha256 == findings.evidence_ledger_sha256` and `initial_packet_sha256 == packet_sha256`);
- every `runs/*.json` `artefact_sha256` matches its file;
- the findings still load with the current Pydantic models.

### 12.3 Publication registry (`uc042app/services/registry.py`)

**Why it exists.** It closes a gap: because an investigation ID is only a content address, someone could rewrite the artefact, recompute the ID and rename the folder, and the rewrite would still pass `verify_published` (registry.py:1-17).

**Registration.** `register_new` is called by the job right after publishing (investigations.py:303-309 → registry.py:97-122). It refuses:
- if `verify_published` fails;
- if the investigation is not COMPLETED and VALID;
- if the output is simulated;
- if it belongs to a different pack or pack hash;
- if the same ID is already registered with different hashes.

**What an entry pins** (`PINNED`, registry.py:33-34): `pack_id`, `pack_content_sha256`, `findings_sha256` (hash of the file bytes), `evidence_packet_sha256`, `evidence_packet_file_sha256`, `evidence_ledger_file_sha256`, `findings_schema_version` and `prompt_version`. It also stores `seq`, `record_type` (NEW_PUBLICATION or LEGACY_BASELINE_IMPORT), `recorded_at`, `recorded_by` and `verify_published: "OK"`.

**Storage.**
- Database mode: `audit.investigation_registry` (models.py, `RegistryEntryRow`).
- File mode: `<app_state>/registry/investigation_registry.json` (repositories/files.py:6, 131-135).
- A damaged registry fails closed (registry.py:87-92).

**February.** Registry **seq 1, NEW_PUBLICATION** (report 17 §6). Report 17 §11 also records registry `findings_sha256 ba6d64e0…`. My `sha256sum findings.json` gives `ba6d64e0a10189bf2192b59a3fd4e749b9d0d2a9fd3e85878fc8ac251f2aeeb9`, which matches.

### 12.4 What `_not_published/` is

Any result that is not VALID and COMPLETED (REJECTED, or FAILED at any stage) is written to `<root>/_not_published/<pack>/<exception>/<UTC timestamp>-<8 hex>.json` (persistence.py:179-187).
- `_write_new` (persistence.py:118-141) never replaces an existing record.
- The record holds `result` (the full InvestigationResult with `validation_findings` or `failure_reason`), `run`, `evidence_packet_sha256`, and in tools mode the whole `evidence_ledger` and `tool_calls`, kept for diagnosis.
- It is never eligible.
- The UI only counts these ("N failed or rejected attempt(s)…"). The API lists them as `not_published` (`list_investigations`, final_pack/sources.py:102-109).

**February's** `_not_published/PACK-H202602-…/EXC-H202602-01/2026-11-04T054432+0000-c392e113.json` is attempt 1, job `JOB-9e1f2150…`:
- 3 LLM calls, 8 tools over 2 rounds, same packet `760adfe5…`;
- a different ledger `af224cef…`;
- `validation_status: REJECTED` because of `ZERO_PATTERN` on F-03.

September has a similar record at `investigations/_not_published/PACK-S02-…/EXC-S02-01/2026-11-02T115736+0000-10c4a727.json`.

### 12.5 The second published folder `INV-EXC-H202602-01-a3fd3fd2e9ed`

This is the **Phase 6A** investigation (report 16):
- produced at 05:21:31Z by the **CLI**: `python -m uc042lib.investigation.run PACK-H202602-… EXC-H202602-01 --mode tools --period PER-2026-02` (report 16, line 60);
- not through the API, so there was no job, no AIA record and no registry entry;
- VALID, `INSUFFICIENT_EVIDENCE`, 3 LLM calls, 5 tools over 2 rounds, 6 findings;
- the same packet `760adfe5…` but a different ledger `54079f47…`, and therefore a different ID.

It still verifies and is "library-eligible", but it is **unregistered**, so it is **not eligible** ("publication registry: not in the investigation publication registry (unregistered artefact)"; report 17 §1, report 19 §H).

Report 17 chose to rerun through the app rather than import it as LEGACY_BASELINE_IMPORT. It is left untouched. Note that `demo_history/final_packs/FAP-H202602-…/final_pack.json:2228` mentions `a3fd…` under the other published attempts that were not selected (report 19 §H calls this cosmetic).

---

## 13. Eligibility for the final review

### 13.1 Rules

An investigation is eligible only if **all** of the following hold.

**A. Library check** (`uc042lib/final_pack/sources.py:59-78`, `check_eligibility`)
1. `verify_published` passes (otherwise "artefact verification failed: …").
2. It belongs to the same `pack_id` and `pack_content_sha256` as the pack under review.
3. It is `COMPLETED` / `VALID`.
4. `simulated` is false.
5. It **passes the current validation rules**: the stored findings are re-validated against the stored ledger or packet with today's `validate_output`. Failures read "fails current validation rules (uc042-investigation-findings/1.4): …".

**B. Publication registry** (registry.py:128-146, `check`). It must:
- be registered;
- have a folder name equal to the registered ID;
- match every PINNED value;
- be registered for this pack and hash.

**C. Authorisation decision** (investigations.py:70-74). The latest `audit.investigation_authorizations` row for the ID must be absent (the registry then decides alone) or `APPROVED`. `AUTHORIZATION_DISCREPANCY` adds the reason "authorisation: AUTHORIZATION_DISCREPANCY - not in the approved published set (…)".

**Where the rules are combined**
- `InvestigationService.reasons` (investigations.py:64-68), `published()` (:91-111, cached under a signature of artefact file stats, the registry, authorisations, pack hash and schema version) and `detail()` / `verify()` (:137-156, 208-219).
- The final review uses only `eligible` rows:
  - the default selection is the newest eligible tools-mode investigation (reviews.py:87-96);
  - an INCLUDED selection of an ineligible ID is refused with `INELIGIBLE_SELECTION` (reviews.py:126-134);
  - readiness blocks a selection that is no longer eligible (reviews.py:151-156).
- The monthly views count an investigation as "published" only if it is registered and not a discrepancy (`uc042app/api/routers/monthly.py:38-41, 65-68`).

### 13.2 Investigation by investigation

| Investigation | Outcome |
|---|---|
| **February `6b1425b437f4`** | Verifies; registry seq 1 (NEW_PUBLICATION); authorisation row #1 APPROVED, basis "Phase 6B (report 17)". **Eligible.** It was selected by default in review `RS-898ce850…` and is in the final pack `FAP-H202602-PER-2026-02-v1-b8dd53bd2449` (report 17 §8-10) |
| **February `a3fd3fd2e9ed`** | Verifies, library-eligible, **unregistered**, so ineligible (§12.5) |
| **June `INV-EXC-H202606-01-c7b353b53fb3`** | **AUTHORIZATION_DISCREPANCY** (see below) |
| **The seven September artefacts** | Unregistered and ineligible (see below) |

**June `c7b353b53fb3`.** Report 19 (DB unification), §1 and §7, gives the history:
- It was created at 07:17-07:18Z on 4 Nov by job `JOB-a1f539840d090ef197d34b85`, submitted through the application by `demo-reviewer` while the history backend was running.
- Before Phase 8 there was no confirmation dialog, so one click started a paid run (report 19 audit, L-6).
- It was **not explicitly authorised** by the owner, but it was published **and** registered (seq 2, NEW_PUBLICATION).
- The owner decided (2026-11-04) to keep the artefact and its registry entry unchanged and to append `audit.investigation_authorizations` row #2: status `AUTHORIZATION_DISCREPANCY`, basis "Business owner decision 2026-11-04: not explicitly authorised … Artefact and registry entry seq 2 preserved unchanged; excluded from the approved published set (report 19)".

Effect:
- `verify` still reports artefact verified and registry verified, but `eligible: false` with the authorisation reason.
- The month counts it as "+1 excluded".
- A later APPROVED row would supersede the decision, because the latest row is in force (report 20, decisions table item 1, around line 514).

**The seven September artefacts** (under `investigations/`, the "september" profile):

| ID | Mode | Schema |
|---|---|---|
| `INV-EXC-S02-01-764aed67bb83` | tools | 1.2 |
| `INV-EXC-S05-01-2b3defdae13f` | tools | 1.3 |
| `INV-EXC-S05-01-51ba0f94bf82` | tools | 1.2 |
| `INV-EXC-S05-01-65bd05498b9e` | tools | 1.4 |
| `INV-EXC-SC2-01-389ba1328c3c` | tools | 1.2 |
| `INV-EXC-SC2-01-eb2021ac50e9` | **fixed** mode, schema 1.1, prompt 1.0; no ledger or tool_calls | 1.1 |
| `INV-EXC-SC5A-01-fae6067d9d23` | tools | 1.2 |

They are all POC CLI runs from 2–3 Nov, all VALID when written, and **none registered**. Each therefore gets "publication registry: not in the investigation publication registry (unregistered artefact)".
- Several also fail today's rules: older schemas had no `compared_evidence`, so it defaults to `[]` and fails "C-01: a contradiction must name exactly two different compared evidence IDs".
- Report 19 counts 3 such failures. My static check finds 4 artefacts with a C-01 lacking two compared IDs: 51ba0f94bf82, 389ba1328c3c, eb2021ac50e9 and fae6067d9d23 (see "Unclear" below).
- Options listed in report 20 decision 2: keep as is, `import-legacy-investigations` (LEGACY_BASELINE_IMPORT) for those that pass the current rules, or re-run, which needs AI authorisation and costs tokens.

---

## 14. "Tools mode" versus a one-shot LLM call, and whether non-tools mode exists

**Fixed mode (V1) exists in code.**
- `config.DEFAULT_MODE = "fixed"` (config.py:80-83). `graph.ai_investigation` makes one call, `investigator.investigate(packet)` (graph.py:189-191 → llm.py:152-186).
- The request has the same `SYSTEM_PROMPT`, the packet in the user message and `text_format` structured output, with **no tools**, and one retry only for invalid or missing structured output.
- The model sees only what deterministic retrieval put in the packet.
- It is the **CLI default** (run.py:95 `mode = a.mode or config.investigation_mode()`). The Anthropic legacy adapter supports only fixed mode (llm.py:289-345).
- Of the existing artefacts, only September `eb2021ac50e9` is fixed mode.

**The application uses only tools mode.**
- `StartInvestigationRequest.mode: Literal["tools"]` (schemas.py:137).
- `_execute(... mode="tools")` (investigations.py:292-295).
- `_investigator()` refuses providers without `supports_tools` (investigations.py:236-237).

**Purpose of tools mode.** The deterministic plan is deliberately narrow: engine citations plus fixed joins per route. Tools mode lets the model *ask for more* of the same hash-verified data while it reasons, but only through 8 typed, read-only, bounded functions that Python validates and executes. Every row it obtains is logged with provenance and becomes citable. The final answer is validated against everything that was actually retrieved, which is the ledger.

In February this added things the one-shot packet did not contain:
- the batch **lines and transactions** behind both settlement batches;
- the firm's **internal** reconciliation record IN-05, which let the AI separate the internal and external views (F-03);
- **exact-reference bank searches** proving NOT_FOUND for five specific references (SEARCH-08..12), which strengthened M-01.

The trade-off is cost and non-determinism: more tokens and more model calls. Report 19 J8 records that a rerun produced 4 findings instead of 7 for the same packet.

---

## 15. Sequence diagram (February, attempt 2)

```
Analyst          UI (React)                 API / Service                        Library (LangGraph)                 OpenAI         Storage
  |  click "Run investigation"  |                       |                                     |                          |               |
  |---------------------------->| AiPanel.tsx:78 open dialog                                   |                          |               |
  |                             |--GET /ai/configuration-->| ai_authorization.configuration()  |                          |               |
  |                             |<-- provider openai, gpt-6-luna, effort medium, limits 8/4/300s |                       |               |
  |  tick statement + confirm   |                       |                                     |                          |               |
  |---------------------------->|--POST /packs/PACK-H202602…/exceptions/EXC-H202602-01/investigations
  |                             |   {mode:"tools", authorization:{confirmed:true,provider,model}, retry_of: JOB-9e1f…}
  |                             |                       | start(): lock pack; load+verify pack |                          |               |
  |                             |                       | require() -> config unchanged        |                          |               |
  |                             |                       | no active job; retry_of valid        |                          |               |
  |                             |                       | _investigator() (openai, tools OK)   |                          |               |
  |                             |                       | runner.create(job QUEUED)  -------------------------------------------------------> jobs
  |                             |                       | auth.record(AUTHORIZED, job_id) ----------------------------------------------------> audit.ai_execution_authorizations (Phase 8 only;
  |                             |<-- 202 Job ------------| runner.submit(_execute)             |                          |               |   Feb predates it)
  |   poll GET /jobs/{id}       |                       |                                     |                          |               |
  |                             |                       | _execute -> run_investigation(mode=tools)                       |               |
  |                             |                       |------------------------------------>| load_pack: hash 195df2e1… OK               |
  |                             |                       |                                     | build_case / scope / route=missing_bank_evidence
  |                             |                       |                                     | EvidenceStore: SHA-256 of 17 inputs OK      |
  |                             |                       |                                     | plan_cited + plan_missing -> 16 records,    |
  |                             |                       |                                     |   SEARCH-01..03 NOT_FOUND, MISS-01          |
  |                             |                       |                                     | build_packet -> 36 IDs, packet 760adfe5…    |
  |                             |                       |                                     | EvidenceStore re-hash (tools)              |
  |                             |                       |                                     | ledger0 = packet                            |
  |                             |                       |                                     |--responses.parse(instructions, packet msg,->|
  |                             |                       |                                     |   8 tools, text_format, store=False)       |
  |                             |                       |                                     |<-- 8 parallel function_calls --------------|
  |                             |                       |                                     | validate args (Pydantic), budget 8/8        |
  |                             |                       |                                     | execute via EvidenceStore + Collector:      |
  |                             |                       |                                     |   +13 records, SEARCH-04..12; ledger rebuilt|
  |                             |                       |                                     |   (29 records, 58 IDs) + "budget exhausted"|
  |                             |                       |                                     |--responses.parse(history + 8 outputs) ---->|
  |                             |                       |                                     |<-- final JSON (LLMInvestigationOutput) ----|
  |                             |                       |                                     | validate_output vs ledger -> VALID          |
  |                             |                       |                                     | investigation_id = INV-…-6b1425b437f4       |
  |                             |                       |                                     | persist: stage .tmp dir, os.replace ------------------------> INV dir (5 files)
  |                             |                       |<------------------------------------| PUBLISHED                                   |
  |                             |                       | registry.register_new: verify_published, pin hashes ----------------------------> audit.investigation_registry seq 1
  |                             |                       | job COMPLETED ------------------------------------------------------------------> jobs
  |                             |<-- job COMPLETED ------|                                     |                          |               |
  |  read findings              |--GET /investigations/{id}, /findings, /evidence, /tool-calls, /verify            |               |
  |                             |   detail(): check_eligibility + registry.check + authorisation -> eligible        |               |
  |                             |                       |                                     |                          |               |
  (later: owner records audit.investigation_authorizations #1 APPROVED; Final Review selects it by default)
```

---

## 16. Unclear or surprising

1. **The published February run is a retry after a false-positive rejection.**
   - What happened: `ZERO_PATTERN` rejected a finding that correctly quoted the firm's *reported* difference of 0.00 and called it unverified.
   - Status: the validator was left unchanged, and narrowing the rule is still an open recommendation (report 17 §14).
   - Risk: any future month with a reported 0.00 and missing bank evidence can trip it again. Whether a run passes then depends on the wording the model chooses; the decimal point in "73199.44" is what let attempt 2 through.

2. **There are two VALID published February artefacts; only one is eligible.** `a3fd3fd2e9ed` (CLI, Phase 6A) is unregistered.
   - Quirk: the review rules treat "library-eligible" artefacts specially (reviews.py:135-137, 158-160). Choosing NOT_INVESTIGATED for an exception that has an unregistered but valid artefact is refused or blocked with `NOT_INVESTIGATED_WITH_ELIGIBLE`.
   - Yet `_default_selections` proposes NOT_INVESTIGATED when nothing is registry-eligible (reviews.py:87-96).
   - Consequence: June and the September scenarios with library-valid artefacts would start with a default selection that is blocked. The analyst must pick EXCLUDED_BY_ANALYST with a reason. I inferred this from the code and did not test it.

3. **`model_metadata.attempts` means something different in tools mode.** There it equals the number of LLM calls (2 for February; graph.py:168), not retries. In fixed mode it means the retry attempt number.

4. **`runs/0001.json` hashes only the ledger and tool transcript** (`artefact_sha256`), not `findings.json` or `evidence_packet.json`. Those two are protected by the packet self-hash, the content-addressed ID and the registry pins. That is enough, but not obvious.

5. **Not every refusal is recorded.**
   - The `ai_authorization` docstring says a refused request "is recorded with its reason".
   - But a request without `confirmed: true` (422 `AUTHORIZATION_REQUIRED`), an invalid `retry_of`, or an unknown pack or exception is **not** written to `ai_execution_authorizations`, because `require()` raises before `refuse()`.
   - Only configuration-changed, already-active, provider-not-configured and mode-unsupported refusals are recorded.

6. **February has no pre-execution AIA record.** It predates migration 0004; its authorisation basis is report 17 plus the later APPROVED decision row. Per memory and report 20, the live `uc042` database has not yet been migrated to 0004.

7. **The budget was exhausted in a single round.** With `parallel_tool_calls=True` the model spent all 8 calls in round 1, so "4 rounds" was never reachable. The model got the "budget exhausted" note on every output and had one chance to answer.

8. **First-come provenance hides some retrieval reasons.** A packet record keeps only its first `retrieved_via`. Example: the IN-10 and IN-12 records show "cited by control result", even though `plan_missing` also selected them, because `plan_missing` adds them without a relationship edge.

9. **`latency_ms: 0.0` on several tool calls** is probably the Windows monotonic clock's resolution, not a real zero.

10. **The September C-01 count disagrees with the report.** Report 19 says 3 of the 7 artefacts fail the current rule. My static inspection finds 4 with a contradiction lacking two `compared_evidence` IDs. I did not run `check_eligibility`.
    - Possible explanation: one of them (perhaps the schema 1.1 fixed-mode `eb2021ac50e9`) may fail earlier (`verify_published` or the model load), which would report a different reason.
    - The count should be confirmed with `import-legacy-investigations --dry-run` or `GET /investigations/{id}/verify`.

11. **Two "authorisation" tables with similar names.**
    - `audit.ai_execution_authorizations`: before the run.
    - `audit.investigation_authorizations`: after publication, the approved set.
    - The UI labels them "AI authorisation" and "Authorisation decision" respectively (InvestigationPage.tsx:52). This is easy to confuse in owner-facing material.

12. **Non-determinism.** No temperature is sent and reasoning models vary. Report 19 J8 shows a rerun of February in an isolated copy produced `INV-…-15412698307d`, with 4 findings instead of 7 from the same packet. This is expected, but reviewers should know that "re-run" is not "reproduce".

13. **The full packet, including free-text fields, goes to OpenAI.** Example: IN-05 `actions_taken_text`. The prompt says to treat these as untrusted data. `store=False` limits OpenAI-side retention of application state, but report 02 §12 notes that abuse-monitoring retention is separate.
