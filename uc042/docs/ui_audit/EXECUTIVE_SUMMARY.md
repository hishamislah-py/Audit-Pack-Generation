# UC-042: executive summary of the UI audit and simplification

## 1. What the application does

UC-042 turns a month's safeguarding source documents into an audit pack:
1. It **validates** uploaded documents: identified by content, with date and duplicate checks.
2. A deterministic engine **reconciles** them. It produces an immutable pack per month, or per demonstration scenario.
3. It **raises exceptions** where checks fail.
4. On request and after paid-AI authorisation, it runs an **AI investigation** of an exception against the pack's verified records.
5. It lets the analyst **ACCEPT or REJECT** each AI investigation. A rejection needs a reason, kept verbatim.
6. A **final review** produces a preview with an AI closing summary, then HOLD or GENERATE.
7. GENERATE **publishes** an immutable, versioned final audit pack in JSON, HTML and PDF.

No exception is ever resolved by the application.

## 2. Distinct functional areas: six

1. Monthly reports
2. Upload documents
3. Reconciliation packs
4. Exceptions (with AI investigation and analyst review)
5. Final review
6. Final audit packs

Supporting records outside these six:
- the AI investigation technical record;
- the analyst's investigation case;
- upload batches;
- reassessment.

The original UI exposed these six areas through **17 routes and 9 sidebar entries**, three of which were duplicates.

## 3. Where it was unnecessarily complicated

- **Two start pages.** Dashboard and Monthly reports showed the same months and packs.
- **Duplicate menu entries.** "All reviews" duplicated "Final review", and "All final packs" duplicated "Final audit pack". Two entries were disabled until a context existed.
- **The workspace.** It said neither what went wrong nor what to do next. About 60 expanded evidence rows came before the AI findings, and the Accept/Reject decision the final review needs sat in a narrow side column. Accept/Reject was also offered on investigations that can never be used.
- **Statuses.** Up to seven status badges per exception mixed the engine's status, the AI's assessment, registry eligibility and the analyst's decision.
- **The final review.**
  - Readiness was shown as backend codes.
  - The preview button invited a paid-AI authorisation that the backend then refused.
  - A missing closing summary said only "(configuration)".
- **Counting.** The overview counted final-pack *versions* as if they were separate published results.

## 4. What was consolidated (implemented in P10)

- One start page (Monthly reports), which absorbed everything unique on the dashboard.
- Six numbered workflow steps in the sidebar.
- One exception workspace, read top to bottom:
  1. an exception summary with one recommended next step;
  2. the AI investigation and your review;
  3. the check results;
  4. the supporting evidence, collapsed;
  5. the review history.
- A plain "Before you generate" checklist, with links to any decision still outstanding.
- Packs counted per scenario, with versions as history.

## 5. What remains (deliberately)

- The AI investigation technical record: tool calls, registry, verification.
- The optional investigation case.
- Upload batch decisions.
- Reassessment.
- HOLD.
- The selections editor.
- The stale-preview guard, in both the UI and the backend.
- Paid-AI authorisation before every call.
- Immutable final-pack versions.
- Every existing route.

## 6. Navigation, before and after

| Before | After |
|---|---|
| 01 Dashboard · R Monthly reports · 02 Reconciliation pack · 03 Exceptions & investigation · 04 Final review · 05 Final audit pack · R All reviews · F All final packs · ↑ Upload documents | 1 Monthly reports · 2 Upload documents · 3 Reconciliation packs · 4 Exceptions · 5 Final review · 6 Final audit packs |

## 7. The end-to-end workflow, simplified

Monthly report → (upload documents → validate → confirm → process) → reconciliation pack → exception: read the summary, optionally run AI, **ACCEPT or REJECT** → final review: checklist, preview, GENERATE → final audit pack (JSON / HTML / PDF, versioned).

Each step is one click from the previous one. The application states the next step at the two places where the analyst must decide: the exception and the review.

## 8. Broken, inaccessible or not verified

| Item | State |
|---|---|
| **Live AI** (investigation and closing summary) | Integration complete. A real call was made for each through the UI, and **OpenAI refused both: 429 `credit_balance_exhausted`**. The API key is valid, but the account has no credits. **Not verified with a successful real result.** Mocked-provider tests pass |
| Previously published investigations for SC2 (2), SC5A (1) and S05 (1) | **Not usable**: they fail the current findings rule C-01. S02's only investigation is unregistered. Re-runs need live AI |
| Exceptions with no amount, account or category in the pack data (SC3B, SC3C, SC5A, SC5C, SC5D) | Shown via control names and computed vs reported. Engine output unchanged |
| Browser-tested business flows | Clean pack to final pack; S02 missing evidence; S05 ACCEPT; S05 REJECT with a Unicode reason; stale preview blocked; fresh preview; GENERATE v3; JSON / HTML / PDF verified; upload with wrong-month and duplicate detection. **37 of 37 checks pass** |
| Not executed in the browser (covered by automated tests) | Batch confirmation and processing, reassessment, HOLD, saving selections, case entries, title change, creating a period |
| Not tested | Narrow and mobile layouts after the workspace change |
| Deployment | **None.** The live application (5173 / 8000) and the live database are untouched. P10 changes need your approval, together with the earlier migration 0005 decision |

**Recommendation:** review the simplified P10 at `http://127.0.0.1:5190`. Then decide:
1. whether to integrate into live;
2. whether to fund the OpenAI account to complete live verification;
3. whether the nine demonstration scenarios should move to a separate area (R24).
