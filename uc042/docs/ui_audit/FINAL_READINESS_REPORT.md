# UC-042: final readiness report (UI simplification, P10)

**Date:** 5 November 2026.

**Scope:** the isolated P10 application and its disposable clone E.

**Verdict:**
- **The simplified application is complete and works in P10 for every workflow that does not need a successful live AI response.**
- **Live AI is blocked externally.** The provider account has no credits, so real calls reach OpenAI and are refused.
- **Nothing has been deployed to live.**

## 1. Status per item

| Item | Status |
|---|---|
| Navigation consolidated (6 steps; dashboard merged; duplicate entries removed) | **Implemented and runtime-tested** (P10 exploration `A95_*`, E2E W1) |
| Exception summary with next step; single-column workspace; evidence collapsed | **Implemented and runtime-tested** (W2, W3, W4, A30–A42) |
| Accept / Reject exposed and working in the workspace; mandatory exact reason; history | **Implemented and runtime-tested** (W3, W4: API-verified byte-exact Unicode reason) |
| No decision offered on unusable investigations | **Implemented and runtime-tested** (A39, A40; vitest) |
| Review decisions never resolve exceptions | **Runtime-tested** (W3, W5: OPEN / UNRESOLVED after ACCEPT, REJECT and GENERATE) |
| "Before you generate" checklist; stale preview shown; GENERATE blocked | **Implemented and runtime-tested** (W5: UI and backend 409 `PREVIEW_STALE`) |
| Preview button gated while a decision is pending | **Implemented**; tested in vitest and visible in screenshots. Not exercised through a click in E2E, because no review in E was left with a pending decision |
| Closing-summary failure reason shown | **Implemented and runtime-tested** (W1_06 "OPENAI_API_KEY is not set", W5_01 real 429 detail) |
| `configuration_problem` names the missing key | **Implemented and runtime-tested** (W2_03) plus a backend unit test |
| Rejected AI content excluded from JSON / HTML / PDF; reason included | **Runtime-tested** (W5, FAP-S05-…-v3) |
| Closing-summary model never receives rejected AI content | **Verified through mocked-provider tests** (inspects the real Responses request) |
| Final pack generation, downloads, verification, version history | **Runtime-tested** (W1: S01 v1; W5: S05 v3) |
| Overview counts packs, not versions | **Implemented and runtime-tested** (W6_01) |
| Upload: identification, wrong period, duplicates, no processing before confirmation | **Runtime-tested** (U01–U04) |
| Batch confirm / process, reassessment, HOLD, saving selections, case entries, rename, create period | **Implemented earlier; not runtime-tested in this round**: covered by automated tests (matrix B17–B23) |
| AI investigation through the UI, against the real provider | **Real provider call made; blocked by missing credits** (429 `credit_balance_exhausted`). No successful real investigation |
| AI closing summary through the UI, against the real provider | **Real provider call made; blocked by missing credits.** No successful real summary |
| Tool execution, multi-round loop, citation validation, persistence | **Verified through mocked-provider tests** (`test_tool_calling`, `test_openai_provider`, `test_investigation*`) |
| All nine September scenarios | **Verified** against the answer keys (all match) |
| Deterministic financial outputs unchanged | **Verified** (17 packs and 4 data trees: identical hashes) |
| Narrow / mobile layout | **Not tested** |
| Separate demonstration-scenario area (R24); re-run of C-01-failing investigations (R25) | **Not implemented**, outstanding (owner decision / needs live AI) |

## 2. Remaining blockers (exact)

1. **OpenAI credits.** The organisation behind the existing project's `OPENAI_API_KEY` returns `429 credit_balance_exhausted`. Until it is funded, there can be no successful live investigation or live closing summary in any environment, live included. The steps to finish the smoke test are in `LIVE_AI_INTEGRATION_VERIFICATION.md` §5.
2. **Usable investigations are scarce.** Only S05's EXC-S05-01 has usable investigations. SC2, SC5A and one S05 investigation fail current rule C-01, and S02's is unregistered. Producing reviewable investigations for the other scenarios depends on blocker 1.
3. **Owner approval for live integration.** This needs:
   - `changes_ui.patch`, plus the earlier P10 analyst-review change set (`changes_v2.patch`, the fonts, migration 0005);
   - a backup of live `uc042`;
   - a redeploy.
   None of it has been applied to live.

## 3. Regression results

| Suite | Result |
|---|---|
| Backend full suite | 660 OK, 24 skipped |
| Backend in PostgreSQL mode (disposable `uc042_p10_test`; analyst review, db, UTC timestamps, phase 8, review API, unification) | 110 OK |
| Frontend vitest | 60 passed, 2 skipped |
| `tsc --noEmit` / `npm run build` | Pass / pass |
| Browser E2E | 37 / 37 checks pass (2 test-side corrections documented) |
| Financial outputs before / after | Identical |
| Live application | Ports 5173 / 8000 still served by the original processes 15732 / 15284. No live file modified (checked against the backup's timestamp). The live database was never connected to |

## 4. Running environments left up

| Environment | URL | Backend | Database | Notes |
|---|---|---|---|---|
| **P10** (for your review) | http://127.0.0.1:5190 | http://127.0.0.1:8030 (new code) | `uc042_p10b` | No AI key, as before. Data unchanged by this work except read-only exploration |
| Clone E (test results) | http://127.0.0.1:5191 | http://127.0.0.1:8031 (AI disabled) | `uc042_p10e` | Contains the test-generated S01 v1 and S05 v3 final packs, the ACCEPT and REJECT decisions and the November upload batch. Disposable |

## 5. Recovery

- **Database.** `uc042_p10b` can be restored from `p10/backups_ui/uc042_p10b_before_ui.dump`. It was not modified by any business action in this work.
- **Source.** The source can be restored from `p10/backups_ui/p10_uc042_src_before_ui.tgz`.
- **Clone E.** It can be dropped (`DROP DATABASE uc042_p10e`, delete `p10/env_e`) without affecting P10.

---

## Update (6 Nov 2026): status after adding the Groq fallback

| Item | Status |
|---|---|
| OpenAI primary / Groq fallback configured | **Implemented** |
| Automatic fallback on the real OpenAI 429 | **Verified through a real provider call** (closing summary) |
| Fallback switch rules | **Verified through simulated-failure tests** (16) |
| Real Groq connection | **Verified through a real provider call** |
| Real AI closing summary | **Verified through a real provider call** (Groq; FAP-S05-…-v4 verifies) |
| Real AI investigation | **Blocked: Groq free tier allows 8,000 tokens per minute; the investigation needs about 26k.** Tool-calling protocol verified with real Groq calls |
| Remaining UI workflows (title, create period, upload decisions, confirm, reassessment, selections, HOLD, case entries) | **Implemented and runtime-tested** |
| Regression | Backend 676 OK · PostgreSQL 126 OK · frontend 60 passed · build OK · financial outputs identical |

**Remaining blockers:**
1. A successful real AI investigation needs either OpenAI credits or a Groq plan with a higher tokens-per-minute limit. Reducing the evidence to fit is not acceptable.
2. Rotate the Groq key that was shared in the chat.
3. Live integration still needs your approval. The live app (5173 / 8000) was found down after the machine restart and was **not** restarted by me.

**Running for review:** P10 http://127.0.0.1:5190 (`uc042_p10b`, no AI key) and clone E http://127.0.0.1:5191 (`uc042_p10e`, OpenAI primary plus Groq fallback). The PostgreSQL cluster on 5433 was restarted from this session and may stop when the session ends.
