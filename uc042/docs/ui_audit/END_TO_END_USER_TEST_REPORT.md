# UC-042: end-to-end user test report

**Setup:**
- **Browser:** headless Microsoft Edge, real mouse and keyboard input over the DevTools protocol.
- **App under test:** the P10 frontend on the disposable clone **E** (`http://127.0.0.1:5191` → backend `:8031` → `uc042_p10e`), restored from the backup of `uc042_p10b`.
- **AI:** disabled in E for these workflows. The two real provider calls are reported separately in `LIVE_AI_INTEGRATION_VERIFICATION.md`.
- **Verification:** after each business action, the backend API was read to check what was recorded.

**Scripts:** `p10/ui_audit/e2e_ui.py` and `e2e_upload.py`. **Results:** `p10/ui_audit/evidence/e2e_results.json` (31 checks) and `e2e_upload_results.json` (6 checks). **Screenshots:** `docs/ui_audit/screenshots/` and `p10/ui_audit/shots/`.

**Result: 37 of 37 checks pass.** Two checks failed on the first run because the *test* was wrong. Each was corrected, re-run and is labelled as such below; neither hid a product defect.

## Workflow 1: clean reconciliation (S01)

| Step | Check | Result |
|---|---|---|
| Open the application | The start page is Monthly reports (`W1_01`) | PASS |
| Select September 2026 | "9 demonstration scenarios of this one month" (`W1_02`) | PASS |
| Open scenario S01 | Pack opens; no "Open exceptions" button (`W1_03`) | PASS |
| No false exception | API: 0 exceptions | PASS |
| Final review | "Open a new final review" → checklist "0 exception(s)" (`W1_04`) | PASS |
| Preview | The summary dialog says the provider is not configured; the preview is current, and the missing summary is explained with "OPENAI_API_KEY is not set" (`W1_05`, `W1_06`) | PASS |
| GENERATE | `FAP-S01-PER-2026-09-v1-7526c9d28470`, exception register empty (`W1_08`) | PASS |

## Workflow 2: missing evidence (S02)

| Step | Check | Result |
|---|---|---|
| Open EXC-S02-01 | The summary names "Missing bank evidence", the statement gap and the missing statement (`W2_01`) | PASS |
| No invented bank balance | API: C07 / C08 `computed` empty, outcome INSUFFICIENT_EVIDENCE. The workspace shows "reported bank balance is unverified" and "difference not computed" | PASS, *re-checked*: the first assertion wrongly counted the firm-**reported** balance 98,500.35 as invented |
| Source records | The collapsed panel opens and lists the bank and ledger records (`W2_02`) | PASS |
| Next action | "The existing AI investigation cannot be used in the final audit pack (… unregistered artefact). Run a new investigation if useful, or continue …" | PASS |
| Trigger AI investigation | The dialog names "OPENAI_API_KEY is not set in the backend environment"; Authorise disabled (`W2_03`). The real-provider attempt for S05-02 is in the live-AI report | PASS (live result blocked by provider credits) |

## Workflow 3: unexplained bank-ledger difference (S05): ACCEPT

| Step | Check | Result |
|---|---|---|
| Open EXC-S05-01, pending investigation 2b3d | The summary shows −£812.40, SGA-GBP-01 and the C08 checks (10 of 10 failed) (`W3_01`) | PASS |
| ACCEPT with comment | Recorded (API `AR-465dde4f58d0ce97c89b763a`) (`W3_02`) | PASS |
| History | "Analyst accepted the AI investigation" | PASS |
| Exception not resolved | API: `OPEN` / `UNRESOLVED` | PASS |

## Workflow 4: REJECT an AI investigation (S05, the investigation included in the open review)

Reason entered, character by character:

```
The investigation did not consider Łódź's additional evidence.
Difference: £812.40 → unresolved; “bank trace” pending (ref. BE-GBP-0917-X01) — re-run after the advice is loaded.
```

| Step | Check | Result |
|---|---|---|
| Blank reason | "Save decision: REJECT" stays disabled | PASS |
| Save | API `rejection_reason` is byte-identical to the text above (`W4_01`, `W4_02`) | PASS |
| History | The reason is shown; the earlier ACCEPT is marked "Superseded" | PASS |

## Workflow 5: final pack generation and the stale preview

| Step | Check | Result |
|---|---|---|
| Open the review made before the REJECT | Checklist: "The preview is out of date"; GENERATE disabled (`W5_01`) | PASS |
| GENERATE on the old snapshot (API) | 409 `PREVIEW_STALE` | PASS |
| Regenerate preview | The fresh preview contains the reason and none of the rejected AI text (`W5_02`) | PASS |
| GENERATE | `FAP-S05-PER-2026-09-v3-9e4d04058efc`; verification `verified: true, problems: []` | PASS |
| JSON | Exact reason in `exception_register[].investigation.analyst_review.rejection_reason`; `ai_investigations: []`; the AI assessment text is absent | PASS |
| HTML | Escaped exact reason present; AI text absent | PASS |
| PDF (pypdf text) | "Łódź", "£812.40 →" and the first line verbatim; AI text absent | PASS |
| Version history | v1, v2 and v3 listed (`W5_07`) | PASS |
| Exceptions | Still UNRESOLVED after GENERATE | PASS |
| Monthly overview | "2 of 9 packs published · 4 versions" (`W6_01`) | PASS |

## Workflow 6: live closing summary

- **Real call.** One real closing-summary call was made through the UI on clone E with the project's OpenAI settings. The provider refused it with 429 `credit_balance_exhausted`.
- **Failure handling.** The preview was built with the summary UNAVAILABLE. Nothing was fabricated, and the checklist shows the provider's exact message (`RS04`, and visible in `W5_01`).
- **What remains unverified.** A *successful* live summary could not be obtained: **blocked by provider credits.**

## Upload workflow (supplementary)

Three of the project's own synthetic September CSVs were uploaded to November, one chosen twice:

| Check | Result |
|---|---|
| Batch created, validation page opened (`U03`) | PASS |
| Identified by content (IN-02, IN-07, IN-09) | PASS |
| `WRONG_PERIOD` and `TIMING_DIFFERENCE` flagged | PASS |
| `DUPLICATE_IN_BATCH` flagged, nothing removed (4 documents kept) | PASS |
| Nothing processed before confirmation (status VALIDATED, no runs) | PASS |
| Confirm disabled while a flagged file needs a decision | PASS, *re-evaluated*: the first run's extra "element exists" check was a test fault |

## Analyst-perspective review

| Question | Original UI | Simplified UI |
|---|---|---|
| Does the user know where to click? | Two start pages, nine sidebar entries | One start page, six numbered steps |
| Is the next action obvious? | No statement of what to do in the workspace | A "Next step" with one button on every exception |
| Does each button do what it says? | "Generate closing summary and preview" could be refused after authorisation | Disabled with the reason until it will succeed |
| Is a clear result shown? | "closing summary generation failed (configuration)" | The provider's reason, in full |
| Are errors understandable? | Readiness as codes | Plain checklist; codes one click away |
| Is the user sent away from the task? | The decision was hidden in a side column; the breadcrumb went to the dashboard | The decision follows the findings in the main column; the breadcrumb goes to the month |
| Is technical information exposed? | Model, registry and validation status beside business facts | Under "Technical details" and the technical-record link |
| Does it work without knowing the AI architecture? | "eligible", "registered" and "INELIGIBLE" next to analyst decisions | "Usable in the final pack: Yes / No (reason)" |

## Automated regression (run after the changes)

| Suite | Result |
|---|---|
| Backend full suite (`python -m unittest`) | **660 tests OK**, 24 skipped (658 before plus 2 new) |
| Backend in PostgreSQL mode (analyst review, db, timestamps, phase 8, review API, unification) on the disposable `uc042_p10_test` | **110 tests OK** |
| Frontend (`vitest`) | **60 passed**, 2 skipped (55 before plus 5 new) |
| Type check (`tsc --noEmit`) | Pass |
| Production build (`npm run build`) | Pass |
| API contract (OpenAPI paths vs the frontend, in `test_api_basics`) | Pass (part of the backend suite) |
| Deterministic financial outputs (17 packs: summary, reconciliation, exceptions, sources) and the packs / dataset / demo-history / investigations trees | **Identical** before and after (`financial_before.json` = `financial_after.json`) |
| Unicode PDF, versioning, analyst review, citation validation | Pass (`test_pdf_unicode`, `test_final_pack*`, `test_analyst_review`, `test_tool_calling`; all within the full suite) |

---

## Update (6 Nov 2026): remaining workflows, real AI and regression (run one at a time)

**Previously not browser-tested, now runtime-tested on clone E:**

| Workflow | Result |
|---|---|
| R1: change the report title | PASS (title saved; period ID unchanged) |
| R2: create a reporting period (October 2026) | PASS (created, upload page opened; a second report for the same month is refused) |
| R3: upload decisions with comment, confirm batch | PASS (the duplicate was excluded with a comment; batch CONFIRMED; all files kept; processing refused while 16 required evidence types are missing) |
| R4: additional evidence, then reassessment | PASS. First attempt: the button was correctly disabled, because the v4 final pack was newer than the uploaded evidence, so no request was sent. After one new synthetic upload, **one** reassessment ran: request `POST /periods/PER-2026-09/reconciliation`, run `RUN-cd92116394fb…` SUCCEEDED in **4 seconds**, **no AI call** (the deterministic engine only). New pack `PACK-CASE-PER-2026-09-9c7e777c3353` verifies, with lineage to S05. Its 21 exceptions come from mixing clean-baseline bank files into S05's mutated data in the test, as expected for that input. The original pack is unchanged |
| R5: edit selections (exclude with reason); HOLD with reason | PASS (preview invalidated; ON_HOLD; the exact reason including “ ” and — stored; no final pack) |
| R6: case entries (note, gap, observation citing a record, hypothesis, decision) | PASS (an uncited observation is refused; a disposition never resolves the exception) |
| Real AI closing summary through the UI (fallback) | PASS (see the live-AI document) |
| Real AI investigation through the UI (fallback) | BLOCKED: Groq free-tier limit of 8,000 tokens per minute (413) |

**Defects found and fixed:**
- The selection editor kept a stale exclusion reason after switching back to "Include".
- Groq errors were labelled "OpenAI API error".
- Groq refused JSON mode with tools (adapter added).

**Regression, run sequentially:**
- Backend: **676 OK** (24 skipped).
- PostgreSQL: **126 OK**.
- Frontend: **60 passed**; type check and build pass.
- Financial outputs for all 17 packs: **identical** to the original baseline.
- Browser smoke test of six key screens: PASS.
