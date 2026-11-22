# UC-042 Smart Parser — Phase 3B-10: Live LLM Integration, Automatic Progression and HITL Verification

| | |
|---|---|
| Date | 18–19 November 2026 (provider ledger day `2026-11-18` UTC) |
| Working copy | `C:\Users\artlptp263user\p10\smartparser_phase1` (the only code location modified) |
| Evidence | `Downloads\UC042_SMART_PARSER_PHASE3B10\`: `evidence_baseline\`, `evidence\` (regression), `live_run\` (live provider run) |
| Result | **All acceptance criteria demonstrated** (§15 lists the honest caveats). **4 real OpenAI requests**, 6,000 tokens in total, no errors. Scenario A was auto-accepted with no human review, passed 14/14 handoff checks, and the complete 17-category package produced a reconciliation-ready manifest (not submitted, reconciliation NOT_RUN). Full suite **568 passed**. |

**Evidence labels**

| Label | Meaning |
|---|---|
| **[I]** | Implemented |
| **[T]** | Test-verified (offline pytest) |
| **[L]** | Live-provider-verified (real OpenAI requests) |
| **[C]** | Code-inspected |
| **[N]** | Not implemented |

---

## 1. Baseline state (before any 3B-10 change)

`evidence_baseline/regression_summary.txt` showed:
- **553 passed** (3B-9 41; all earlier phases as in 3B-9);
- registry in sync (19); baseline 445/445; corpus 161/161;
- protected trees hash-identical;
- POC policy `DISABLED`, AI off, production authority `{}`.

**Provider integration as found [C]:**
- **No live adapter existed.** `ai/gateway.py` held only `DisabledLiveProvider`, a placeholder that always raises.
- **The rest of the path was in place:** the versioned prompt (`ai/prompts/mapping_prompt_v1.md`), the strict category-specific response schema (`ai/prompting.py`, "for a later provider"), the gateway (feature flag, budget gate, timeout, 1 retry, dedup, audited `PROVIDER_CALL`), the proposal parser and deterministic validator (`mapping/proposals.py`), the POC policy, and the existing **test-only** policy fixture (`tests/fixtures/orchestration/poc_auto_accept_enabled.json`, status `POC_TEST_ONLY`).
- **Credentials.** No provider configuration or key was present in the session environment. Per your instruction, the key was taken from `Downloads\UC042_CLAUDE_CODE_HANDOFF\uc042\.env`.

## 2. Files changed and why

| File | Change | Why |
|---|---|---|
| `smartparser/packages/service.py` | `resubmit` refuses VALIDATED and ACTIVE files (audited `RESUBMISSION_RECEIVED` / REFUSED); new `reprocess_version` | §3 policy change; reprocessing without a new version |
| `smartparser/packages/models.py` | comment on `NEEDS_NEW_VERSION` updated | document the policy (no status meanings changed) |
| `smartparser/ai/openai_provider.py` | **new**: `OpenAIMappingProposer`, an implementation of the **existing** `MappingProposer` interface (no new abstraction) | the missing live adapter |
| `tools/live_eval_3b10.py` | **new**: the live evaluation runner, outside pytest | live scenarios A–E in isolated stores |
| `tests/test_live_llm_3b10.py` | **new**: 15 offline tests (no network) | policy regressions; the adapter through the real gateway with a fake transport |
| `tests/test_packages_3b9.py` | 3 tests rewritten: `test_23`, `test_24_25`, `test_30` | they relied on voluntary replacement of an ACTIVE file, which is now prohibited (§3) |
| `docs/…PHASE3B10…REPORT.md` | this report | — |

**Not changed:**
- the gateway, AI config, prompt and schema, validator, POC policies (shipped and test), orchestrator, authority policies, packaged rules and canonical definitions;
- every other existing test.

## 3. Voluntary replacement policy change [I/T]

| Latest version of the slot | `resubmit(...)` |
|---|---|
| VALIDATED / ACTIVE | **refused** (`PackageError`; audited REFUSED; nothing created) |
| RESUBMISSION_REQUIRED, FAILED_VALIDATION, REJECTED | corrected version accepted (unchanged rules) |
| REVIEW_REQUIRED / RECEIVED | refused until the review is completed or rejected (unchanged) |
| identical bytes to any version | idempotent refusal (unchanged; checked first) |

**Reprocessing is not replacement.** `PackageService.reprocess_version(package_id, file_version_id)` does the following for an existing CSV version:
- re-runs deterministic reprocessing with the same intake, SHA-256 and recorded confirmation and the current rules (no LLM);
- runs all 14 handoff checks;
- rebuilds the canonical output in a temporary folder and compares it with the recorded preview hash.

It creates **no version**, changes **no status**, creates **no snapshot**, does **not** rewrite the recorded preview or sidecar, and leaves the package record untouched (revision unchanged). The outcome is audited as `REPROCESSED` / `HANDOFF_EVALUATED` with `purpose: reprocess_existing_version`.

**Regression tests [T]** (`tests/test_live_llm_3b10.py`):

| Test | Proves |
|---|---|
| `test_p1` | replacing a VALIDATED file is refused |
| `test_p2` | replacing an ACTIVE file is refused, and the active snapshot, its manifest bytes, the ACTIVE versions and RECONCILIATION_READY status are unchanged |
| `test_p3` | a RESUBMISSION_REQUIRED file still takes a correction |
| `test_p4` | a FAILED_VALIDATION file still takes a correction |
| `test_p5` | reprocessing creates no version (14 checks, 0 provider calls, preview hash matches, package revision unchanged) |
| `test_p6` | the open-review and identical-bytes rules are kept |

**3B-9 tests updated** (documented reason: they exercised the now-prohibited voluntary replacement of ACTIVE files):
- `test_23`, `test_24_25` and `test_30` keep their properties (new snapshot with `previous_snapshot_id`; no partial activation; previous active snapshot preserved; superseded versions and historical snapshots retrievable).
- They now reach those properties through permitted paths: corrections of failed files, and a first file for an empty optional slot after activation.

## 4. Provider configuration used (no credentials) [L]

| Setting | Value |
|---|---|
| Provider / API | OpenAI, **Responses API** (`responses.create`), the same API family UC-042 uses with this account |
| Model | `gpt-6-luna` (your choice; also UC-042's `.env` model). Every response reported model `gpt-6-luna` |
| Reasoning effort | `low` (my choice, so reasoning fits within the small output cap you chose; UC-042 uses `medium`) |
| `max_output_tokens` | 2000 |
| Calls cap | `AI_MAX_CALLS_PER_DAY` = 6 (shared persistent ledger) |
| Cost cap | 1.0. **Not effective**, because OpenAI does not report cost (§12) |
| Timeout / retries | 120 s (UC-042 `.env` value; the Smart Parser default is 30 s) / gateway retry limit 1; SDK retries disabled (`max_retries=0`) so the gateway's limit is the only one |
| `store` | `False` |
| Value shapes / sample values | **not sent**: `send_value_shapes=False`; verified per request (`value_shapes_in_payload: false`) |
| Region | not pinned: recorded as "openai-default (not pinned; owner decision)" |
| Auto-accept | the **existing test-only** fixture `poc_auto_accept_enabled.json` (`POC_TEST_ONLY`), loaded only inside the run; shipped policy file untouched and still `DISABLED` |
| Review authority | existing test-only authority fixture (TEST identities); production authority untouched |
| Isolation | every scenario has its own rule store, evidence store, package store and audit log under `live_run\<scenario>\`; no global configuration or environment was changed |
| Key handling | read at runtime from the `.env` you named; passed only to the SDK client; never printed, logged or written. **Leak scan:** 680 files (the working copy + all 3B-10 outputs) contain neither the key nor its last 8 characters. Provider errors are re-raised as category + HTTP status only (sanitising verified offline with a key-like error text [T]) |

**Adapter behaviour [I/T/L].** It sends exactly three things:
- the existing prompt as `instructions`;
- the existing DATA block, containing only the unresolved headers with **no value shapes**, plus field context and the resolved columns;
- the existing response schema in the provider's strict subset (`$schema`/`title`/`maxLength` dropped, `const` → single `enum`).

The returned text then goes through the **unchanged** parser and deterministic validator.

**Offline tests [T] with a fake transport, through the real gateway, orchestrator and package service:**
- what is sent: unresolved headers only, no shapes, no row values, no key;
- malformed JSON and incomplete responses lead to REJECT_OR_HOLD, never accepted;
- a 401-style error with key text: sanitised, held, 2 attempts (1 retry);
- a missing budget configuration: DENIED with 0 requests;
- sign-sensitive mappings never auto-accept;
- extra or missing columns: 0 requests.

## 5. Exact number of real provider requests [L]

**4 HTTP requests**, all `completed`, none retried, no errors, run never stopped (`live_run/live_results.json`, `usage_ledger.json`).

| Request | Scenario | Headers sent (only these) |
|---|---|---|
| 1 | A | `cash_book_entry_id`, `safeguarding_account_id`, `posting_timestamp` |
| 2 | A2 | `ledger_line_id`, `account_ref_id`, `posting_datetime` |
| 3 | B | `value`, `reference` |
| 4 | C | `display_colour` |

Scenarios D and E made **0** requests. The review completions in B and D made 0 requests. A separate re-run of E (§6) also made 0.

## 6. Per-scenario inputs and outcomes

All inputs are synthetic, built from the canonical clean-baseline fixtures (`PER-2026-09_set_01_clean_baseline`). Only headers were changed, except C, whose replaced column holds colour codes.

| Scenario | Input | Provider proposal (assessment → validator class) | Route / decision | File outcome |
|---|---|---|---|---|
| **A** [L] | **Complete UC-042 package** (17 required categories). IN-10 with 8 = 8 columns: `ledger_entry_id`→`cash_book_entry_id`, `account_id`→`safeguarding_account_id`, `posted_ts`→`posting_timestamp`; 5 exact headers. The other 16 files canonical | 3 × CLEAR → **CLEAR** (validated, no diagnostics) | PROPOSAL → **AUTO_ACCEPT** (test policy) | **VALIDATED**; no case or session; 14/14 checks; preview = canonical |
| **A2** [L] | Test package (IN-10 only). `ledger_line_id`, `account_ref_id`, `posting_datetime` | 3 × CLEAR → CLEAR | AUTO_ACCEPT | VALIDATED; preview = canonical |
| **B** [L] | Test package. `payment_reference`→`reference`, `amount`→`value` | `value`→amount PLAUSIBLE → **AMBIGUOUS** (`SIGN_PERSPECTIVE`); `reference`→payment_reference PLAUSIBLE → **PLAUSIBLE** | **HUMAN_REVIEW** (proposal session) | REVIEW_REQUIRED, no preview. Reviewer CHANGE ×2 → APPROVED → `complete_session` → VALIDATED, preview = canonical, 0 provider calls |
| **C** [L] | Test package. `payment_reference` replaced by `display_colour` (values `#FF0000` / `#00AA00` / `#0000FF`) | `display_colour` → **UNMAPPABLE** → NO_MATCH (no field invented) | **REJECT_OR_HOLD** (`payment_reference` unresolved) | **FAILED_VALIDATION**, `missing_fields: [payment_reference]`, no preview, no rule |
| **D** [L-run, 0 calls] | Test package. IN-10 + `operator_memo` (9 vs 8) | — (not called) | HEADER_COUNT_GATE → HUMAN_REVIEW (`HEADER_COUNT_MISMATCH`, extra `operator_memo`) | REVIEW_REQUIRED, then the analyst IGNOREs `operator_memo` with a reason and MAPs the rest → VALIDATED. The sidecar lists the ignored column (reason, rule); preview = canonical; original preserved |
| **E** [L-run, 0 calls] | Test package. IN-10 without `currency` (7 vs 8) | — (not called) | HEADER_COUNT_GATE | **RESUBMISSION_REQUIRED**, `missing_fields: [currency]`, no handoff, no preview; events `INTAKE_CASE_OPENED`, `PACKAGE_FILE_RECEIVED`, `FILE_VERSION_CREATED`, `RESUBMISSION_REQUESTED` |

**Harness failure (disclosed).** In the main run, E's **product outcome was correct**. My runner then called the review-only accessor on a RESUBMISSION_REQUIRED version and raised `PackageError` while collecting its report (recorded in `live_results.json`). I fixed the runner to read the stored case directly and re-ran **E alone**, with 0 provider calls, into `live_run/results_E.json`. The product code was not changed.

## 7. Did Scenario A complete without HITL? — **Yes [L]**

- `hitl_created: false`: no `ColumnReviewCase`, no `ReviewSession`.
- No `INTAKE_CASE_OPENED` or `PROPOSAL_REVIEW_OPENED` event for the intake.
- The POC decision reason: "every unresolved column is CLEAR (deterministically validated), no conflict, no ambiguity, every required field covered".
- The file mapping carries approval kind `POC_AUTO` (test-only policy), and the category confirmation is `POC_AUTO`.

## 8. Did Scenario A complete all 14 handoff checks? — **Yes [L]**

- `handoff_checks_run: 14`, `handoff_checks_passed: 14`.
- The original's SHA-256 was re-verified by reprocessing (`REPROCESSED` audited).
- Reprocessing made 0 provider calls.
- The canonical preview is byte-identical to the canonical IN-10 file, and the provenance sidecar was written.

## 9. Complete package snapshot and manifest? — **Yes [L]**

**Activation:**
- In the same run, the complete UC-042 package (17 required categories: 14 CSV + 3 PDF; the 2 optional categories not supplied) passed PV-01…PV-09.
- Snapshot `SNAP-001-23f8b80b` was activated, and the package status is **RECONCILIATION_READY**.

**Manifest** (`live_run/A_full_package/pk/packages/PKG-2026-09-2276e4/manifests/SNAP-001-23f8b80b.manifest.json`):
- `status: RECONCILIATION_READY_NOT_SUBMITTED`, `submission_authorised: false`, `reconciliation_status: NOT_RUN`;
- 17 files;
- `verify_snapshot` SV-1…SV-5 all pass.

**No reconciliation was run, and UC-042 was not invoked.**

PDFs (IN-15/16/17) are accepted on content classification only (3B-9 limitation; letters resolved through the package's IN-02).

## 10. Did Scenarios B, C and D correctly enter HITL? [L]

**B — Yes.**
- A proposal **session** was created (state PROPOSED), with no preview before review.
- The reviewer sees each column's proposed field and validation class (`value`→amount AMBIGUOUS, `reference`→payment_reference PLAUSIBLE).
- The reason recorded is "ambiguous (needs a person): value [sign/perspective-sensitive]; plausible but not verified: reference".
- **Which mechanism caused review:** the model itself rated both headers only PLAUSIBLE, **and** the deterministic validator forces any money or debit/credit mapping to AMBIGUOUS. So review was guaranteed for `value` regardless of the model's answer.
- Review completion used the existing session decisions, existing test authority, and the 3B-9 `complete_session`.

**C — Correctly held.** The existing failure path was used:
- the model answered UNMAPPABLE, so no field was invented;
- the required `payment_reference` stays uncovered, so the decision is HOLD (decision table: required field unmapped → HOLD) and the package version is FAILED_VALIDATION;
- no preview, no rule.

It did **not** create a review task, which is existing designed behaviour: a hold needs a corrected file. Had the model invented `payment_reference`, the colour codes would still have failed the field's ID pattern in the validator (`VALUE_INCOMPATIBLE`) [T, earlier phases].

**D — Yes.**
- Direct HITL through the header-count gate, with no LLM request.
- The `HEADER_COUNT_MISMATCH` case shows the counts [9, 8] and the extra `operator_memo`.
- The analyst ignored it with a reason (existing IGNORE_COLUMN) → VALIDATED. The source bytes are preserved, and the ignored column is in provenance.

No deterministic duplicate-claim override was introduced.

## 11. Did Scenario E request resubmission without an LLM call? — **Yes [L-run, 0 calls; T offline]**

RESUBMISSION_REQUIRED with `missing_fields: [currency]`. There was no review task (the gate case is kept as history only), no fabricated values, no handoff and no preview.

## 12. Token usage and cost [L]

| Request | Input tokens | Output tokens | of which reasoning | Total |
|---|---|---|---|---|
| A | 1,329 | 202 | 0 | 1,531 |
| A2 | 1,321 | 263 | 53 | 1,584 |
| B | 1,298 | 172 | 0 | 1,470 |
| C | 1,283 | 132 | 0 | 1,415 |
| **Total** | **5,231** | **769** | **53** | **6,000** |

**Cost:** not reported by the OpenAI API, and **not estimated** (ledger `cost_measured: false`). Consequently the configured cost cap cannot be enforced, and only the call cap is effective.

## 13. Full regression results (`evidence/regression_summary.txt`, final code)

| Check | Result |
|---|---|
| Full suite | **568 passed**; without the UC-042 tree 565 passed, 3 skipped |
| Per phase | **3B-10 15**, 3B-9 41, 3B-8 21, 3B-7 35, 3B-6.1 18, 3B-6 43, 3B-5 16, 3B-4 14, 3B-3 15, 3B-2 23, 3B-1 40, 3B-0 117, Phase 1+orig 136, Phase 2 34 |
| Evaluations | eval_3b5 **68/68**, eval_3b6 **34/34** |
| Registry / baseline / corpus | in sync (19) / 445/445 / 161/161 |

The live runner is not collected by pytest (`testpaths = tests`; the runner is in `tools/`), and every offline test blocks sockets.

## 14. Protected-path and configuration verification

| Check | Result |
|---|---|
| UC-042 authoritative source | 107 code + 624 dataset files hash-identical; 0 files newer than the Phase 1 start |
| Desktop Smart Parser | 63 files hash-identical |
| Datasets / demo database / Clone E / original app | not modified (no database used; fixtures only read) |
| `UC042_CLAUDE_CODE_HANDOFF\uc042\.env` | read only (the key value) |
| Reconciliation / submission | none; `submit_to_uc042` unchanged and patched to fail in the offline tests; the manifest is NOT_SUBMITTED / NOT_RUN |
| Shipped POC policy | `poc_auto_accept_policy.json` still `DISABLED`, `enabled: false` (file unchanged) |
| Production authority | `PRODUCTION_UNCONFIGURED`, scopes `{}` |
| AI default config | `AIConfig.from_env({})`: `enabled=False`, provider `None`, model `None` (no live configuration persisted as a default) |
| Credentials | none in logs, results, stores or this report (leak scan of 680 files: 0 hits) |
| Network imports | one **lazy** `import openai` inside `OpenAIMappingProposer.__init__`; nothing imports a network library at package import time |

## 15. Remaining limitations and failures

1. **Live evidence is small.** It is 4 requests, one model (`gpt-6-luna`), reasoning effort `low`, and synthetic data on one category (IN-10) for the semantic cases. It demonstrates the path; it is not a statistical accuracy evaluation.
2. **B's review is partly guaranteed by design.** The deterministic sign-sensitivity rule forces review for `value`→amount whatever the model says. The model's own PLAUSIBLE ratings would also have routed to review under the test policy (`accept_plausible: false`).
3. **C ends in HOLD, not a review task.** This is the existing design for a required field left uncovered, and it is correct but differs from a reviewer task.
4. **Cost is unmeasured**, so the cost cap is ineffective (§12); region is not pinned. Both are owner decisions.
5. **Auto-acceptance used the test-only policy** (`POC_TEST_ONLY`). In the shipped configuration (DISABLED), the same file would go to human review. Enabling auto-accept for real use remains an owner decision.
6. **Harness failure in the first E run** (§6), fixed in the runner and re-run without provider calls.
7. **Unchanged limitations:**
   - PDFs are classification-only;
   - single-user only, with no cross-process locking;
   - production authority authorises nobody, so reviews complete only under the test policy;
   - equal-count duplicate-claim files cannot be completed (3B-8 decision pending);
   - no API or UI.
8. **Using the UC-042 `.env` key** for the Smart Parser was your explicit instruction for this evaluation. A dedicated key or project, with a data-handling decision for Smart Parser, is an owner decision before any further live use.
