# 07 — Final Audit Pack, Phase 1: Library and AI Closing Summary (implementation report)

Date: 3 Nov 2026. Implements Phase 1 (and Phase 1b, findings schema 1.4) of `06_FINAL_AUDIT_PACK_APPLICATION_SPECIFICATION.md`.
This phase delivers a Python library only. There is no FastAPI, React, PostgreSQL, authentication or job runner.

## 1. Findings schema 1.4 (additive; schema 1.3 artefacts unaffected)

| Item | Change |
| --- | --- |
| `ConfirmedFinding` | New fields `title` (5–160 chars), `audit_relevance`, `establishes`, `does_not_establish` |
| `Hypothesis` | New field `rationale` |
| Contradictions | `compared_evidence` / `same_measure_and_scope` (schema 1.3) are unchanged and still apply only to contradictions |
| JSON schema for the model | Each new field is a **required non-empty string** (via `WithJsonSchema`), so new runs always produce it |
| Python type | `Optional[str] = None`. Artefacts written under schema ≤ 1.3 load with `None` (not supplied); nothing is back-filled; explicit `None` round-trips |
| Validation (`validation._check_explanations`) | Applied only to fields that are present. `title` and `establishes` follow the cause rule. Every new field follows the resolution and non-existence rules and must not be blank. No existing rule was weakened. |
| Prompts | `uc042-investigator-prompt/1.2` (fixed) and `2.2-tools` (tools). The earlier versions stay recorded in historical artefacts. |
| Versions | `FINDINGS_SCHEMA_VERSION = uc042-investigation-findings/1.4` |
| Offline simulator | Fills the new fields with text marked "SIMULATED" |

**Live verification.** `INV-EXC-S05-01-65bd05498b9e` (gpt-6-luna, tools mode, 3 tool calls) is VALID and published, with
all five fields populated. All seven published investigations (schemas 1.1, 1.2, 1.3 and 1.4) pass `verify_published`.

## 2. Library (`uc042lib/final_pack/`)

| Module | Responsibility |
| --- | --- |
| `model.py` | Constants and versions; caller inputs `Selection`, `ReviewRecord` (+ `Reviewer`, `PriorDecision`), `GenerationInfo`; the AI output `ClosingSummaryOutput` and the `ClosingSummary` record |
| `sources.py` | Loads the pack (existing `load_pack` + schema check); discovers published and unpublished investigations; **eligibility** = `verify_published` + same pack and hash + COMPLETED/VALID + not simulated + re-validation under the **current** rules; `default_selections` |
| `snapshot.py` | `ReviewSnapshot`: verified inputs, every exception explicitly selected, hashes of the selected artefacts; `snapshot.sha256` |
| `content.py` | Deterministic mapping of the validated investigation output into final-pack items (classes, refs `INV-…#F-01`, gap subtypes, copied amounts and dates, ledger relationships); cited-only evidence index |
| `summary.py` | AI-generated closing summary: controlled input, fingerprint, prompt, generation (the **only** model call in the library), deterministic validation, explicit UNAVAILABLE record |
| `assemble.py` | `assemble_preview` / `assemble_final_pack`: no AI, no recalculation, no status change; preview and final built by the same code |
| `validate.py` | Final-pack rules (§4) |
| `report.py` | Block model built from the **canonical** JSON; shared by both renderers |
| `render_html.py` / `render_pdf.py` | HTML (reuses the `pack.html` CSS tokens) / ReportLab PDF (A4, page N of M, wrapped tables, reproducible bytes) |
| `persistence.py` | `publish_final_pack` (atomic, write-once, version chain, one pack per decision), `verify_final_pack`, `list_final_packs`, `next_version` |

**Public interface:**

```python
from uc042lib.final_pack import *

pack = load_pack(pack_id)
sels = default_selections(pack)                    # or explicit Selection(...) per exception
snap = build_review_snapshot(pack_id, sels)
summary = generate_closing_summary(snap)           # before the preview; or unavailable_closing_summary(snap, reason)
preview = assemble_preview(snap, summary)          # render_html(preview), render_pdf(preview)
final = assemble_final_pack(snap, summary, review, GenerationInfo(version=v, supersedes_final_pack_id=prev))
path = publish_final_pack(final)                   # final_packs/<FAP-…>/; verify_final_pack(path)
```

**Storage.** `final_packs/<final_pack_id>/` holds `final_pack.json`, `report.html`, `report.pdf` and `manifest.json`
(file SHA-256s + generation record). The folder is created only on the first publication. None has been published in
the project: there is no real human decision yet.

**Identity.** `final_pack_id = FAP-<scenario>-<period>-v<N>-<content12>`, where `final_content_sha256` is the canonical
hash without its self-referential fields. Previews are `PREVIEW-…` and are never published.

## 3. Canonical JSON (`uc042-final-pack/1.0`)

| Group | Sections |
| --- | --- |
| Metadata | `metadata` (ID, version, supersedes, status, generated_at, source pack reference + hash, period, scope, completeness) |
| Deterministic (copied, verified) | `executive_summary.deterministic`; `source_inventory`; `reconciliation_results`; `relationships`; `exception_register[]` (verbatim exception + `resolution_status: UNRESOLVED` + investigation inclusion) |
| AI-generated (validated) | `ai_investigations[]` (assessment, confirmed findings, hypotheses, conflicts, evidence gaps, not-found searches, unverified relationships, next steps, open questions); `closing_summary` |
| Evidence | `evidence_index` (cited records only, with provenance) |
| Human | `human_review` (supplied record, or PENDING_DECISION in a preview) |
| Context and provenance | `limitations`, `statements`, `audit_trail`, `final_content_sha256` |

## 4. Validation (`validate_final_pack`; any problem blocks assembly and publication)

1. Original pack still loads and verifies (identity and content hash) at its snapshot location.
2. Snapshot hash and pack hash match.
3. Pack schema is supported.
4. Selected investigations are published and eligible.
5. Selected investigations re-validate under the current rules.
6. Every cited ID resolves to that investigation's ledger or packet, and every cited record is in the evidence index.
7. Confirmed observations cite a record, result or search, and are genuine validated findings (title and explanations
   verbatim, never rewritten or back-filled).
8. Hypotheses stay hypotheses (`NOT_ESTABLISHED`).
9. The AI assessment is verbatim and distinct from observations.
10. The exception register equals the pack's exceptions (order, fields), all UNRESOLVED.
11. Reconciliation and summary values equal the pack's values.
12. The closing-summary fingerprint and snapshot match.
13. The closing summary passes its own validation.
14. A GENERATE review with acknowledgement on this exact snapshot and summary is present (final only).
15. The content hash is correct.

Duplicate generation and overwriting are refused by `publish_final_pack`.

## 5. AI-generated closing summary

- **Input.** `closing_summary_input(snapshot)`: the deterministic summary, the exception register (all UNRESOLVED),
  missing-evidence items, groups, candidates (UNVERIFIED), and the selected investigations' assessments, findings,
  hypotheses, gaps, conflicts and next steps, each with its reference. It excludes dataset and scenario names, file paths
  and raw rows. It also excludes the human decision, because the summary is generated *before* the review preview.
  `allowed_refs` lists the citable IDs.
- **Fingerprint.** SHA-256 of the canonical input. A change of selection or input gives a new fingerprint, and the
  assembler rejects a summary whose fingerprint or snapshot does not match.
- **Generation.** `generate_closing_summary(snapshot, investigator=None)` uses the existing `OpenAIInvestigator`
  configuration and client through a new `structured_request` method: Responses API, `text_format=ClosingSummaryOutput`,
  `store=False`, the same error mapping. Prompt `uc042-closing-summary-prompt/1.0`.
- **Validation.** References must be in `allowed_refs`. Observations must cite evidence, not only hypotheses.
  Hypotheses must cite hypotheses or candidates. Unresolved items must be the pack's exceptions, and must be present
  whenever exceptions exist. Text must not assert resolution, compliance, certification, an audit opinion or a "clean
  audit" (negated statements such as "this is not an audit opinion" are accepted), nor causes in observations, nor
  non-existence.
- **Failure decision.** Generation **raises `ClosingSummaryError`** (typed kind) and never returns substitute text. The
  workflow may record an explicit `unavailable_closing_summary(snapshot, reason)`. A preview then shows "unavailable — no
  substitute text". A **final pack with an unavailable summary is allowed only if the review record sets
  `acknowledged_summary_unavailable=True`**: a warning that needs explicit human consent, not a silent pass.

**Live verification (S05).** The summary was generated from the snapshot including `INV-EXC-S05-01-65bd05498b9e`:

| Item | Result |
| --- | --- |
| Usage | 3,293 input / 1,512 output tokens; 16.3 s |
| Validation | VALID |
| Figures | All match the pack and evidence: 13 FAIL; 1 Critical, 1 High; −812.40 on 17–30 Sep; ledger 341,484.46 vs bank 340,672.06; internal 0.00 |
| Content | Both exceptions UNRESOLVED; the SETTLE 0417 relationship stated only as an unverified hypothesis; "not an audit opinion, compliance certification, or approval" |

The preview was rendered to a temporary folder only.

## 6. Rendering

| Element | Detail |
| --- | --- |
| Section order | 1 Audit overview · 2 Executive summary · 3 Source data inventory · 4 Deterministic reconciliation results · 5 Exception register · 6 Supporting evidence · 7 AI investigation summary · 8 AI investigative assessments · 9 Confirmed observations · 10 Hypotheses · 11 Evidence gaps and conflicts · 12 Suggested next steps · 13 Human review record · 14 Limitations · 15 Audit trail and provenance · **16 AI-Generated Closing Summary** (last), then a one-line provenance footer |
| Visual distinctions | Confirmed (green rule) · AI assessment (grey panel, "interpretation, not fact") · Hypothesis (amber dashed, "NOT ESTABLISHED") · Evidence gap (grey, with subtype) · Conflict (red outline) · UNRESOLVED (red badge) · Preview (red notice) |
| PDF | Long cells wrap (identifier and hash columns break anywhere); table headers repeat; rows split across pages; non-cp1252 characters are mapped (− → -, → → ->) |
| Visual verification | Done on 3 Nov 2026. Every page of the S05 preview was rendered at 150 DPI with pypdfium2 5.14.0, a dev-only dependency, and inspected. Five layout defects were fixed in `render_pdf.py`: mid-word splits in table headers and enumerations, a cramped seven-column evidence table (now one card per record in the PDF only), card headings separated from their content across pages, and section headings stranded at a page foot. Regression tests are in `tests/test_final_pack_pdf_layout.py`. Text-level checks still recover every word of every block. |

## 7. Tests

**340 tests: 339 passed, 0 failed, 1 skipped** (the opt-in live test). That is the 302 baseline plus 38 new:

| File | Tests |
| --- | ---: |
| `test_findings_schema_14` | 5 |
| `test_final_pack` | 17 |
| `test_closing_summary` | 10 |
| `test_final_pack_render` | 6 |

Shared helpers are in `tests/final_pack_support.py`. They produce genuinely published, non-simulated investigations
through the real adapter with a mocked HTTP layer.

**One existing assertion changed:** `test_review_hardening` pinned prompt versions 1.1 / 2.1-tools. It now pins
1.2 / 2.2-tools, as required by the approved schema 1.4.

## 8. Integrity

- **Protected files:** 422, unchanged (datasets, packs, golden snapshots, engine, pack layer, existing tests, tools).
- **Investigation artefacts:** unchanged. The only addition is the live `INV-EXC-S05-01-65bd05498b9e`.
- **`final_packs/`:** not created in the project.
- **No AI during assembly:** the library makes no model call during assembly or publication (tested with the provider
  patched to fail).
- **Investigation ID verification (clarified 3 Nov 2026).** The ID is recomputed in two different ways, and they have
  different purposes:
  - **`verify_published` → `investigation_id_from_findings(stored findings, packet hash)`.** This hashes the findings
    exactly as stored. It is the integrity check, and it is the one final-pack eligibility uses. All seven published
    investigations pass it.
  - **`investigation_id(result, packet)`.** This first round-trips the findings through the current
    `InvestigationResult` model, so fields added in later schemas appear as `null` or `{}`. For example, schema 1.4 adds
    `title`, `establishes`, `does_not_establish`, `audit_relevance` and `rationale`, and schema 1.3 adds
    `compared_evidence`. The helper is only correct at publication time, when the result already has the current
    schema.
  - **Expected behaviour.** Applied to the six artefacts written under schemas 1.1–1.3, the helper returns a different
    ID. This is a schema-compatibility difference, not corruption. A one-off diagnostic script reported it as an "ID
    mismatch" during PDF visual QA because it used the helper, not `verify_published`.
  - **Rule.** Never re-derive or rewrite a historical ID with the current-model helper.

## 9. Limitations and next phase

- **Historical eligibility.** The historical SC2 (V1 and V2) and SC5A investigations, and the first S05 run, fail the
  current contradiction rules and are therefore **ineligible**. SC2 and SC5A currently have no eligible investigation,
  so a fresh run is needed to include them. The failure is rule C-01: those contradictions predate `compared_evidence`.
  The investigation ID plays no part in it.
- **Tamper evidence, not authenticity.** The investigation ID is a content address. It detects any inconsistent edit to
  findings, packet or ledger. It cannot detect a deliberate rewrite that also recomputes the ID and renames the folder,
  because run records hash only the ledger and tool-call files, not `findings.json`. A final pack pins the
  `findings_sha256` it used. Phase 2 should keep an independent, append-only record of published investigation IDs and
  findings hashes.
- **Pattern-based validation.** Summary and finding text checks are rule-based. They can over- or under-reject
  paraphrases; negated statements are handled.
- **Visual PDF review:** done on 3 Nov 2026 (see Visual verification above).
- **Next:** Phase 2 (spec 06 §14). PostgreSQL schema and repositories, a review-session service that stores decisions,
  and wiring of `build_review_snapshot` → `generate_closing_summary` → `assemble_preview` → decision →
  `assemble_final_pack` → `publish_final_pack`.
