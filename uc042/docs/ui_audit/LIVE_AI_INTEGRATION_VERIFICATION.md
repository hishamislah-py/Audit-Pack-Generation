# UC-042: live AI integration verification

## Verdict

| Capability | Integration code | Mocked-provider tests | Real provider call | Successful real result |
|---|---|---|---|---|
| AI exception investigation (tools mode) | Complete; no change needed | Pass | **Made, through the UI** (5 Nov 2026 09:33 UTC) | **Not obtained: provider refused with HTTP 429 `credit_balance_exhausted`** |
| AI closing summary | Complete; no change needed | Pass, plus a new request-content test | **Made, through the UI** (09:34 UTC) | **Not obtained: same 429** |
| Missing-configuration handling | Improved (the backend names the missing variable) | Pass (new test) | n/a | n/a |

**Blocker:** the OpenAI account behind the existing project's API key has no credits. The key itself is accepted: OpenAI authenticated the request and answered with an account-level billing error, `code credit_balance_exhausted`, which the application cannot fabricate.

**To complete live verification:**
1. Add credits to that OpenAI organisation.
2. Repeat the two calls in the test clone. Commands are in §5.

No other change is needed.

## 1. Credentials and isolation

- **P10 itself has no credential.** There is no `p10/uc042/.env`, and the P10 backend runs with `OPENAI_API_KEY=''` and a dead proxy, by design.
- **Source of the credential.** With your authorisation, the existing project's `uc042/.env` was inspected for variable names only; no value was printed.
- **What was loaded.** `env_e/launch_backend.py` loads **only** `OPENAI_API_KEY`, `UC042_LLM_PROVIDER`, `UC042_LLM_MODEL`, `UC042_LLM_TIMEOUT_SECONDS`, `UC042_LLM_MAX_TOKENS` and `UC042_OPENAI_REASONING_EFFORT`, into the memory of one backend process. Nothing was written to disk, and nothing was sent to the frontend.
- **What was not loaded.** The live `.env`'s `UC042_DATABASE_URL` and `UC042_TEST_DATABASE_URL` were ignored.
- **Where the calls ran.** Both used the disposable clone **E**: database `uc042_p10e`, plus its own state, document store, investigations folder and final-pack folder.
- **What the backend reported.** `/ai/configuration` returned `openai · gpt-6-luna · reasoning medium · provider_configured: true · investigation_mode: tools`.
- **Call count.** Exactly two paid-path calls were made: one investigation and one closing summary. Neither was retried; both would only fail again. Afterwards the clone's backend was restarted **without** AI for all remaining tests.

## 2. AI exception investigation: traced flow

| Step | Where | Verified how |
|---|---|---|
| Analyst action | Workspace → "Run investigation" → `AiAuthorizationDialog` (tick statement → "Authorise and run") | Browser (screens `RA01`, `RA02`) |
| Frontend call | `AiPanel.run` → `DataSource.startInvestigation` → `POST /api/v1/packs/{pack}/exceptions/{exc}/investigations` with `authorization {confirmed, provider, model}` | Source, plus observed job creation |
| Authorisation record | `AiAuthorizationService.require` records provider, model, analyst and time before the job starts; refuses without it | Source, `test_phase8` |
| Job | Backend job runner; the UI polls `/jobs/{id}` | Job `JOB-d631ad4637751f81963b27ae`: submitted 09:33:38, completed 09:33:47 |
| Orchestration | `uc042lib/investigation/graph.py` (LangGraph `StateGraph`) → retrieval → routing → tool loop | Source; `test_investigation*`, `test_tool_calling` |
| Provider call | `OpenAIInvestigator` → `client.responses.with_raw_response.parse` (Responses API, strict function tools generated from the 8 tool argument models, `store: False`) | **Real call made.** The error text `ToolLoop[rate_limit] … OpenAI API error 429 (RateLimitError, code credit_balance_exhausted)` comes from the first tool-loop round |
| Tool execution | `tool_loop.py` executes the 8 read-only tools locally, appends tool results by call ID, allows further rounds, enforces limits (8 calls, 4 rounds, 25 records per call, 160 total, 150k input tokens, 300 s) | Mocked provider: `test_tool_calling.ToolLoop` (one call and call-ID linkage, several calls per response, several rounds, unknown tool / invalid JSON / tool failure reported back to the model, limits, duplicate calls, one correction of an invalid final answer) |
| Validation | Findings schema 1.4 rules, the citation ledger (only returned evidence IDs can be cited) | `test_tool_calling.LedgerValidation`, `test_output_verification` |
| Persistence | Atomic publication plus the registry; failures kept unpublished | `ToolPersistence`; **real run:** the failed attempt was kept unpublished ("1 failed or rejected attempt(s) were kept") |
| Display | Findings tabs, citations, analyst review | Browser (existing published investigations) |
| Error handling | Timeouts, connection errors, 401/404/429, refusals, truncation, invalid output: mapped and never masked or fabricated | `test_openai_provider.ResponseFailures`; **real 429 shown verbatim in the UI** (`RA03`) |

## 3. AI closing summary: traced flow

| Question | Answer (evidence) |
|---|---|
| What triggers it | Final review → "Generate closing summary and preview" (or "Regenerate preview") → `AiAuthorizationDialog` (CLOSING_SUMMARY) → `POST /reviews/{id}/preview` → job → `ReviewService._build_preview` → `generate_closing_summary` |
| Does it call the provider | Yes: `OpenAIInvestigator.structured_request` (Responses API, structured output `ClosingSummaryOutput`). **Real call made** for review `RS-a48067e753f1444a22ecf69c`; the stored failure was `{"kind": "rate_limit", "detail": "… OpenAI API error 429 (RateLimitError, code credit_balance_exhausted) …"}` |
| Which content is sent | `closing_summary_input(snapshot)`: deterministic pack facts plus **accepted** investigations only. For a rejected one, only the marker `REJECTED_AI_CONTENT_EXCLUDED` is sent. The analyst's reason is not sent (the assembler reports it verbatim). **New test** `test_closing_summary_model_never_receives_rejected_ai_content` inspects the actual Responses request: accepted markers present; rejected markers and reason absent |
| Deterministic results authoritative | Validation rejects unsupported claims (`test_closing_summary.OutputValidation`); the summary never changes a result or status |
| Validated and persisted | `validate_closing_summary`, then the summary SHA in the preview and the final pack; stale summaries are refused (`test_stale_summary_is_rejected_by_the_assembler`) |
| Shown in the report | Section 16 of the HTML / PDF; month report section 6 |
| Failure communicated | The preview is built with the summary UNAVAILABLE and **no fabricated text**, and GENERATE requires a second acknowledgement. **New:** the checklist shows the provider's reason, not just the category (`W5_01`, `RS04`) |
| The earlier "closing summary generation failed (configuration)" | Cause: the P10 backend runs with `OPENAI_API_KEY` blanked, so `investigator_from_env()` raises `LLMConfigurationError` ("OPENAI_API_KEY is not set; live investigation cannot run"). The message was correct but hid its detail. Not hidden or faked; now shown in full |

## 4. Changes made for AI handling

1. `uc042app/services/ai_authorization.py`: `configuration_problem` now names the missing variable (e.g. "OPENAI_API_KEY is not set in the backend environment"; never a value). Test: `test_phase8.test_configuration_names_the_missing_key_without_any_value`.
2. Frontend final review: the closing-summary failure detail is shown, and the preview button is disabled while a decision is pending, so no paid authorisation can be given for a request the backend will refuse.
3. The LangGraph orchestration, the Responses API client, the prompts, the schemas, the tools, retrieval, validation and persistence were **not changed**.

## 5. Completing the real smoke test once the account has credits

```
cd %USERPROFILE%\p10
python env_e\launch_backend.py            # clone E with the AI settings only (stop any no-AI instance on 8031 first)
cd uc042\frontend && set VITE_API_BASE_URL=http://127.0.0.1:8031 && node_modules\.bin\vite --host 127.0.0.1 --port 5191 --strictPort
# Browser: http://127.0.0.1:5191 → September → Scenario S05 → EXC-S05-02 → Run investigation → authorise
#          then Final review RS-a48067e753f1444a22ecf69c → Regenerate preview → authorise
```

Expected:
- a published investigation with `model.simulated = false`, a provider `response_id` and token usage;
- a preview whose `closing_summary.status` is `GENERATED`, with model `gpt-6-luna`.

---

## Update (6 Nov 2026): OpenAI primary with automatic Groq GPT-OSS fallback

### Configuration

| Item | Value |
|---|---|
| Primary | `UC042_LLM_PROVIDER=openai`, `UC042_LLM_MODEL=gpt-6-luna` (unchanged) |
| Fallback | `UC042_LLM_FALLBACK_PROVIDER=groq`, `UC042_LLM_FALLBACK_MODEL=openai/gpt-oss-120b`, `GROQ_BASE_URL=https://api.groq.com/openai/v1`, `UC042_LLM_FALLBACK_MAX_TOKENS=3000` |
| Groq key | Not present anywhere locally at first; you then supplied it. Stored in `p10/env_e/ai.env` (outside every repository, readable only by your Windows account) and, as you asked, appended to the existing project's `uc042/.env`, which is git-ignored. Never printed, logged, sent to the browser or written to a report. `redact()` now also masks `gsk_` keys |
| Isolation | The clone-E backend loads **only** the AI variables. Its database, state, documents, investigations, final packs and packs folder are its own |

**Security note:** the Groq key was pasted into the chat. Rotate it in the Groq console and update the two files above.

### How the fallback works (code)

- **`uc042lib/investigation/fallback.py`** (`FallbackInvestigator`) wraps the primary and the fallback investigator and exposes the same interface. Nothing changed in the LangGraph orchestration, tool loop, prompts, schemas or validation.
  - **Switches only on** `rate_limit` (including `credit_balance_exhausted`), `provider_unavailable` (5xx), `connection` and `timeout`.
  - **Never switches on** authentication, bad request, unknown model, refusal, truncation, invalid output, or citation or findings validation failures.
  - **At most one switch** per operation. A fallback failure is reported with its context and never retried on the primary.
- **`GroqInvestigator`** subclasses `OpenAIInvestigator` and uses the same SDK, `responses.with_raw_response.parse`, strict function tools and error mapping, with Groq-specific hooks:
  - no `store` / `include`;
  - the tool-loop history is sent in **canonical form**: user/assistant messages, `function_call` and `function_call_output` correlated by `call_id`, with no OpenAI reasoning items, item IDs or response IDs;
  - **no JSON mode on tool rounds.** Groq answers HTTP 400 "json mode cannot be combined with tool/function calling", which was observed for real. The final answer is parsed from the output text and validated strictly against the same `LLMInvestigationOutput` model and then the unchanged findings and citation validation; it is never repaired;
  - the `x-ratelimit-*` headers are recorded with each response.
- **Provenance.** The provider that actually answered is recorded in the investigation's `model_metadata` and in the closing summary's `model_metadata`. A `fallback` record holds from, to, reason and time. The UI shows "Answered by …" and "AI closing summary generated by groq · openai/gpt-oss-120b (automatic fallback: openai was unavailable, rate limit)".
- **Authorisation.** The dialog shows the primary and the fallback provider and model, and the analyst's statement says the fallback may be used. The confirmation carries `fallback_provider` / `fallback_model`, refused if they changed since the dialog was shown. The authorisation record stores both.
- **OpenAI resumes automatically.** Every operation starts with OpenAI, so once credits exist the fallback is simply not used.

### Results: real calls, simulated failures, mocked tests

| Test | Kind | Result |
|---|---|---|
| A: Groq connection | **Real Groq call** (application adapter, structured output) | PASS. Response `resp_01m6nq4740ez8a313p56cy09pz`, model `openai/gpt-oss-120b`; usage 198 in / 121 out (103 reasoning) tokens; headers: 1,000 requests per day, 8,000 tokens per minute |
| B: automatic fallback | **Real**: OpenAI's actual 429 `credit_balance_exhausted` (not simulated) → automatic switch → real Groq call | PASS, for the closing summary (review `RS-63e04104c595ad36d5f910e5`, 11:24 UTC). Fallback record stored and shown in the UI |
| B: switch rules | **Simulated** provider failures (real `openai` exception classes, mocked HTTP), `tests/test_provider_fallback.py`, 16 tests | PASS: eligible kinds switch once; auth / bad request / invalid findings never switch; fallback failure reported, not retried; switch after a tool round rebuilds the canonical conversation with no OpenAI IDs and no re-executed tools |
| D: closing summary through the UI | **Real** (OpenAI 429 → Groq) | **PASS.** Usage 2,914 in / 2,242 out (1,140 reasoning) tokens, response `resp_01m6nq7jp1eywafgg9c2c2dqcf`. Schema and claim validation passed. The accepted investigation was included, and rejected content is excluded (unchanged input builder plus its test). The summary is in final pack **FAP-S05-PER-2026-09-v4-95a88f6d46f3** (JSON / HTML / PDF), which verifies |
| C: AI investigation through the UI | **Real** (OpenAI 429 → Groq) | **BLOCKED by the Groq free tier.** The automatic fallback happened. The first attempt found the json-mode/tools incompatibility, which is fixed above. The second was refused with **HTTP 413: "Request too large … tokens per minute (TPM): Limit 8000, Requested 26406"**. The S05 investigation's first request is about 26–27k tokens (evidence packet about 68k characters plus 8 tool schemas plus instructions), about 3.3× the free plan's per-minute limit. Evidence was **not** truncated. Both failed attempts are kept unpublished, and the UI shows the exact error |
| C: tool-calling protocol on Groq | **Real Groq calls**, small protocol task with the real 8 strict tool definitions | PASS. Round 1 returned `get_settlement_batch` with call ID `fc_7279…`. Arguments were validated by the application's own Pydantic model, and the tool was executed locally (3 records). Round 2 accepted the `function_call_output` with the same call ID and answered. Responses `resp_01m6nsyq7se0…` and `resp_01m6nt0qxgez…`; usage 2,692 / 3,236 input tokens |

### Free-tier limits (observed from Groq's headers)

| Limit | Value | Effect |
|---|---|---|
| Tokens per minute | **8,000** | A closing summary fits (about 5.2k tokens). **A full investigation does not**: its first request is about 26k tokens before any tool round. This is not temporary: it needs Groq's paid Developer tier (higher TPM), or OpenAI credits |
| Requests per day | 1,000 | Not a constraint at this volume |

The application reports the 413 as `request_too_large`. It is not retried, and it is not treated as a reason to switch again.
