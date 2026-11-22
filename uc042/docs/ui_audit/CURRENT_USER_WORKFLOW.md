# UC-042: the analyst's user journey (as found, and as simplified)

## 1. Business objects and how they relate

```
Reporting period (PER-YYYY-MM, one per month)
 └─ Deterministic reconciliation pack(s), immutable
      · historical months: one pack per month
      · September 2026: NINE packs, one per demonstration scenario (S01, S02, S05, SC2, SC3B, SC3C, SC5A, SC5C, SC5D),
        all for the same month: different synthetic test situations, not different months
      · uploaded months: one pack per processing run (a reassessment adds a new pack linked to the earlier one)
      └─ Exceptions (raised by the engine; always UNRESOLVED in this application)
           └─ AI investigations (optional, paid, recorded; each usable in the final pack or not)
                └─ Analyst decisions (ACCEPT / REJECT with reason; append-only history)
      └─ Final reviews (one active at a time per pack): selections → preview (with AI closing summary) → HOLD or GENERATE
           └─ Final audit pack versions v1, v2, v3 … (immutable; a later version supersedes, never replaces)
```

## 2. The journey as found (original P10 UI)

```
Dashboard (/) ──────┐  both list the same months and packs
Monthly reports ────┤
                    ▼
        Month report (/reports/PER-…)  ── 9 sections, incl. packs, exceptions, AI investigations, final packs
          │  └ "Workspace · Final review" links per pack
          ▼
        Reconciliation pack (/packs/…) ── "Investigate exceptions" (also on clean packs), "Open final review",
          │                               "Add documents for a new period" (unrelated upload entry)
          ▼
        Exception workspace (/packs/…/workspace/EXC-…)
          ├ middle column: KPIs → check results → 60+ expanded source records → relationships
          ├ right column (narrow): investigation case → AI investigation → findings tabs → ACCEPT / REJECT → review history
          ├ "Open the full investigation record" → /investigations/INV-… (technical page, different layout)
          └ "Open investigation case" → /cases/CASE-… (third layout)
          ▼  "Continue to final review"
        Pack review entry (/packs/…/review) → "Open a new final review"
          ▼
        Final review (/reviews/RS-…)
          ├ "Generate closing summary and preview" → paid-AI authorisation → may then be REFUSED (decision pending)
          ├ Readiness: raw codes (AI REVIEW PENDING, PREVIEW STALE …); summary failure shown as "(configuration)"
          └ GENERATE → Final audit pack (/final-packs/FAP-…)
Side routes: All reviews (= Final review with no context), All final packs (= Final audit pack with no context),
             Upload documents (3 entry points), sidebar 02/03 disabled until a month or pack is chosen.
```

### Pain points observed

| # | Where | Problem |
|---|---|---|
| 1 | Start | Two start pages (Dashboard, Monthly reports) showing the same months; the analyst has to choose without knowing why |
| 2 | Sidebar | Nine entries, three of them duplicates ("All reviews", "All final packs", Dashboard); two disabled until context exists |
| 3 | "Exceptions & investigation" | Opens either the month report's exception table or the workspace, depending on context |
| 4 | Workspace | No statement of what went wrong or what to do next. Evidence dominates the page, and the decision the final review needs (ACCEPT / REJECT) sits in a narrow side column after the case panel and the run button |
| 5 | Workspace | Accept / Reject is offered on investigations that can never be used in the pack |
| 6 | Workspace | Seven different status badges for one exception; "eligible" (registry) next to "accepted" (analyst) next to "INSUFFICIENT EVIDENCE" (AI) |
| 7 | Final review | The preview button invites a paid-AI authorisation that the backend then refuses because a decision is pending |
| 8 | Final review | Readiness shows backend codes; a missing closing summary says only "(configuration)" or "(rate_limit)" |
| 9 | Overview | "Published (2 versions)" reads as two published results for September when one scenario was published twice |
| 10 | Breadcrumbs | The workspace's month crumb returned to the dashboard, not to the month |

## 3. The journey as simplified (implemented in P10)

```
1 Monthly reports (start page) ── months, upload status, exceptions, unresolved, "N of M packs published · K versions",
  │                                final reviews in progress, recent activity
  ▼
  Month report ── packs with scenario name, AI available, latest final pack; exceptions with amount + AI status
  │
2 Upload documents (month-aware) → batch validation → confirm → processing → new pack in the month
  │
3 Reconciliation packs ── pack detail: results, sources, exception register; "Open exceptions (N)" only when there are any
  ▼
4 Exceptions (workspace, one column per exception)
    Exception summary: what went wrong · amounts and accounts · checks that identified it · evidence · AI assistance
    Next step (one sentence + one button), e.g. "Read the AI investigation below, then ACCEPT or REJECT it"
    AI investigation and your review ── run (optional) → findings → ACCEPT / REJECT (reason mandatory)
    Check results (open) · source records, AI records, relationships (collapsed) · review history · case (optional)
  ▼  "Continue to final review"
5 Final review ── "Before you generate" checklist: exceptions included · your decisions (with links to the ones
  │               awaiting you) · preview current / out of date · closing summary (with the provider's reason)
  │               Preview button disabled until a decision is recorded; GENERATE only with a current preview
  ▼
6 Final audit packs ── list with month, downloads, latest / superseded; detail with PDF / HTML / JSON / versions
```

Navigation steps for the core task (Workflow 3 / 4 in the test report): month → pack → exception → decide → final review → generate → pack. That is six screens, each reached with one click from the previous one, with no side trips. In the original UI the same task needed the analyst to find the decision in the side column and to work out readiness codes.

## 4. What stays separate on purpose (traceability)

| Screen | Why it stays separate |
|---|---|
| AI investigation technical record (`/investigations/:id`) | Tool-call transcript, registry entry, artefact verification: audit evidence, not daily work |
| Investigation case (`/cases/:id`) | The analyst's own working notes and disposition, kept append-only; never part of the final pack |
| Final review session | The decision (HOLD / GENERATE) is recorded against an exact previewed snapshot; it must not be merged into the exception workspace |
| Final audit pack versions | Immutable; a new version supersedes and never replaces |
| Upload batch page | Per-batch validation decisions with comments, confirmation and processing runs |
