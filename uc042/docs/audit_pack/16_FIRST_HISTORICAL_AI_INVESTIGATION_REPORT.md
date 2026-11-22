# UC-042 — Phase 6A: first controlled historical AI investigation (February 2026)

Date: 4 November 2026. **Scope:** exactly one live AI investigation, of the February 2026 historical pack's single exception.

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

AI investigation findings are an aid to human review. They change no deterministic result and resolve no exception.

## 1. Preflight checks (all before any model call)

Each check ran read-only. The evidence packet was built with the same functions the graph uses, with no model involved.

| Check | Result |
| --- | --- |
| February pack exists and verifies (identity and content hash; equals the run manifest) | PASS: `PACK-H202602-PER-2026-02-195df2e1f216`, content SHA-256 `195df2e1f216149c…` |
| Period | PASS: `PER-2026-02` |
| Exception count | PASS: exactly 1, `EXC-H202602-01` |
| Expected exception | PASS: `MISSING_BANK_EVIDENCE\|SGA-EUR-01\|2026-02-16`, Critical, OPEN / AWAITING_HUMAN_REVIEW |
| February selected explicitly | PASS: `--period PER-2026-02` gives profile `historical-demo`, restricted to `{PER-2026-02}` (`uc042lib/investigation/roots.py`) |
| Pack root | PASS: `uc042/demo_history/packs` |
| Dataset root | PASS: `uc042/demo_history/datasets` |
| No root is `demo_history/` itself | PASS. Output root: `uc042/demo_history/investigations` |
| No verification or answer material reachable | PASS: see below |
| Provider configuration | PASS: `UC042_LLM_PROVIDER=openai`, model `gpt-6-luna`, key configured (value never printed). `--check-provider`: authenticated, model available (no tokens generated). |
| PostgreSQL running and accessible | PASS: cluster running on 127.0.0.1:5433. `python -m uc042app.admin verify-pack-references`: 9 references, 0 problems. |
| No earlier investigation of this pack | PASS |

**How answer material was ruled out:**

- **Files opened during retrieval:** all 19 were inside the February pack folder or `demo_history/datasets/2026-02`.
- **Packet scan:** the evidence packet (16 records, 36 citable IDs) contains none of `verification`, `scenario_definition`, `mutations`, `MISSING_EUR_STATEMENT`, `expected_reconciliation_outcome`, `pre_validation`, `answer_key`, `planted` or `SCENARIO`.
- **Boundary:** the technical input boundary from report 15 was in force.

## 2. February pack

| Item | Value |
| --- | --- |
| Pack | `PACK-H202602-PER-2026-02-195df2e1f216` |
| Dataset | `demo_history/datasets/2026-02` |
| Policy | v1.1, illustrative (HD-1) |
| Engine status | EVIDENCE_INCOMPLETE |
| Results | 1,690 PASS / 83 N/A / 15 INSUFFICIENT_EVIDENCE / 0 FAIL |

The pack verified before and after the run, and it was not changed.

## 3. Exception investigated

`EXC-H202602-01` (Critical): missing bank evidence for SGA-EUR-01 (EUR) on Monday 16 February 2026, a reconciliation day.

- **What is missing:** the 17:00 confirmation, the end-of-day statement and that day's bank entries.
- **Effect:** 15 results could not be assessed. They are in C07, C08, C11, C14, cash-book links, DQ22, FUND-TOPUP and RC4.
- **Missing-evidence item:** MISS-01.
- **Group:** none.

## 4. Configuration and input roots

**Command (from `uc042/`):**

```text
python -m uc042lib.investigation.run PACK-H202602-PER-2026-02-195df2e1f216 EXC-H202602-01 --mode tools --period PER-2026-02
```

**Mode: tools (V2), workflow `uc042-investigation-graph/2.0-tools`.** This is the investigation path the application itself runs (`uc042app/services/investigations.py` uses `mode="tools"`), and whose output the final-pack workflow consumes. The CLI default is fixed mode (V1); `--mode tools` selects the approved application path explicitly.

**Tool limits:**

| Limit | Value |
| --- | ---: |
| Tool calls | 8 |
| Rounds | 4 |
| Records per call | 25 |
| Total records | 160 |
| Input tokens | 150,000 |
| Time budget | 300 s |

**Roots:**

- packs: `demo_history/packs`;
- datasets: `demo_history/datasets`;
- investigations: `demo_history/investigations` (created by this publication).

September's folders were not used.

## 5. Provider, model and prompt actually used

| Item | Value |
| --- | --- |
| Provider | OpenAI Responses API (`store=False`) |
| Model | `gpt-6-luna` (resolved model `gpt-6-luna`) |
| Reasoning effort | `medium` (from `.env`) |
| Prompt | `uc042-investigator-prompt/2.2-tools` |
| Findings schema | `uc042-investigation-findings/1.4` |
| Simulated | **false** |

## 6. Live model calls

**Yes.** Three model calls (two tool rounds and the final answer). All three responses had status `completed`, with request IDs recorded in `findings.json`.

| Item | Value |
| --- | ---: |
| Input tokens | 52,479 (33,384 cached) |
| Output tokens | 7,296 (2,006 reasoning) |
| Latency | 70.8 s |

**Tool calls.** Five tool calls ran; none was rejected or refused for budget:

| Tool | Arguments | Result |
| --- | --- | --- |
| `get_settlement_batch` | AQ-EUR-20260216 | 7 records |
| `get_settlement_batch` | SB-EUR-20260216 | 7 records |
| `search_bank_entries` | SGA-EUR-01, AQ-EUR-20260216 | NOT_FOUND |
| `search_bank_entries` | SGA-EUR-01, SB-EUR-20260216 | NOT_FOUND |
| `get_reconciliation_evidence` | SGA-EUR-01, EUR, 2026-02-16 | 2 records |

The records went from 16 initially to 29 at the end.

The only other provider contact was the preflight `--check-provider`: authentication and model lookup, with no generation.

## 7. Output and evidence-based assessment

| Item | Value |
| --- | --- |
| Investigation | `INV-EXC-H202602-01-a3fd3fd2e9ed` |
| Status | COMPLETED |
| Validation | **VALID** (no validation findings) |
| Overall assessment | **INSUFFICIENT_EVIDENCE** |
| Exception resolution | `NOT_RESOLVED_BY_INVESTIGATION` |

**Confirmed findings.** Every one was checked against the source CSVs independently of the model:

| ID | Claim (abridged) | Independent check |
| --- | --- | --- |
| F-01 | The 16 Feb confirmation and end-of-day statement for SGA-EUR-01 are not in the supplied evidence (the calendar shows a reconciliation day; searches not found) | Matches; the engine's C14 results |
| F-02 | The external record reports bank 73,199.44 = ledger 73,199.44; the bank balance is **unverified** | `ERL-SGA-EUR-01-20260216`: 73199.44 / 73199.44 / 0.00 ✓ |
| F-03 | The internal record reports requirement = resource 73,199.44, difference 0.00 | `IRR-EMONEY-EUR-20260216` ✓ |
| F-04 | Five cash-book entries on 16 Feb, 3 D and 2 C; bank links not assessable | Five `LE-EUR-0216-000x`, indicators D, D, D, C, C ✓ |
| F-05 | Statements exist for 13 and 17 Feb, none for 16 Feb | ✓ |
| F-06 | Batch AQ is to the firm and batch SB from the firm; no bank entry carries either reference | Directions ✓; zero bank entries with either reference ✓ |

Each finding states what it does **not** establish: the actual bank balance, the cause of the gap, and whether funds moved at the bank.

**Hypothesis.** H-01 has status `HYPOTHESIS`. The external reconciliation's bank figure may have been carried forward or reused rather than verified against a 16 Feb confirmation. Its rationale is factually correct: the 17 Feb statement opens at 73,199.44 C. It is labelled "not established", with its limitations stated.

> **Reviewer note:** the same equality is equally consistent with the reported figure being correct. The hypothesis is legitimately unconfirmed but weakly discriminating, and should not be read as a finding.

**Missing evidence:**

| ID | What is missing |
| --- | --- |
| M-01 | The 16 Feb bank evidence (carries the engine's MISS-01) |
| M-02 | The bank entry for AQ-EUR-20260216 |
| M-03 | The bank entry for SB-EUR-20260216 |

**Other content:**

- **Contradictions:** none claimed (correct: there is no conflicting evidence, only missing evidence).
- **Open questions:** four. They concern the actual balance, the bank entries, the source of the reported 73,199.44, and why the evidence is unavailable.
- **Next steps:**
  - **S-01:** obtain the 16 Feb confirmation and statement;
  - **S-02:** obtain the bank entries for the five cash-book references (`E2E-EUR-0216-L01`, `AQ-…`, `TOPUP-…`, `SB-…`, `E2E-EUR-0216-R01`; verified to be exactly the five), without treating firm records as proof;
  - **S-03:** obtain the external reconciliation workpaper.

**Assessment.** The output meets the brief:

- it separates what the records establish (F-01 … F-06) from what cannot be established;
- it names the missing evidence;
- it proposes proportionate follow-up;
- it invents no balance or transaction: every amount it states (0.00, 6.79, 1,007.29, 1,485.52, 1,821.28, 2,168.58, 73,199.44) appears in the evidence, and every date it names is in the evidence;
- it infers no cause;
- it does not claim resolution.

## 8. Citations and source integrity

- **Citations:**
  - all **44 cited IDs** are in the packet's allowed citation set;
  - the 29 cited source records resolve to their stated file, line and primary key in `demo_history/datasets/2026-02/source_data/`, and each recorded file SHA-256 matches the file;
  - the rest are engine results in the pack, recorded searches (`SEARCH-nn`) or `MISS-01`.
- **Source files:** all 29 records come from February's own source files (and the standing account inventory).
- **Publication:** `persistence.verify_published` reports no problems, and the recorded pack content hash equals the pack's.
- **Immutability** (tested on temporary copies; the real artefact was only read):
  - a tampered copy fails verification;
  - publishing a different result under the same investigation ID raises `ImmutabilityError`;
  - the real artefact is unchanged (5 files) and still verifies.

## 9. Exception status

`EXC-H202602-01` remains **OPEN / AWAITING_HUMAN_REVIEW** in the pack, which is unchanged.

The artefact records:

- the original statuses;
- `exception_resolution: NOT_RESOLVED_BY_INVESTIGATION`;
- the standard statement: findings "do not resolve or close any exception".

No resolved, closed or approved wording appears in the AI text (checked).

## 10. Tests and integrity checks

**Test results:**

| Suite | Result |
| --- | --- |
| Python full suite (`-W error::ResourceWarning`) | 568 run: 567 passed, 0 failed, 1 skipped (opt-in live test) |
| `tests/test_demo_history.py` + `tests/test_historical_integration.py` | 91 run; after the test update below, all pass |

**Test changed:** `test_demo_history.OutputPacks.test_demo_output_is_isolated_and_deterministic_only` asserted that `demo_history/` held no investigation, which was the rule before this phase. It now asserts:

- **exactly** the authorised artefact exists: one pack, one exception, one investigation;
- that artefact verifies, is not simulated and is not resolved;
- no other `findings.json` or `evidence_packet.json` exists in `demo_history/`;
- there is still no closing summary or final pack.

The test is no weaker: the old blanket ban is replaced by an exact match on the authorised artefact.

**Project integrity.** A SHA-256 snapshot of the whole project was taken before the run. The only difference after the run is the **5 added artefact files**. These are all unchanged:

- the eight deterministic packs and datasets;
- `demo_history/verification/`;
- the September datasets and packs;
- `investigations/` (September);
- the golden snapshots;
- the final-pack library;
- the application code;
- the React frontend.

**Database.** Read-only after the run: the same rows as before (`period_packs` 9, `reconciliation_periods` 1, `activity_events` 1; investigation registry, jobs, reviews, final-pack records, uploads and runs all 0).

## 11. Problems, limitations and unexpected behaviour

- **No failure, retry, refusal or truncation occurred.**
- **Not registered in the application database.** The CLI publishes the write-once artefact, which is the authoritative record and needs no database row. The backend's packs root is September's, so registering this investigation would also mean registering February in the dashboard, which this phase excludes. To make the investigation visible in the app later, run the backend with `UC042_PACKS_ROOT=demo_history/packs` and `UC042_DATASETS_ROOT=demo_history/datasets`, then `import-legacy-investigations` (a deliberate, separate step).
- **H-01 is weakly discriminating** (see §7).
- **Data handling:** `store=False`. OpenAI's default abuse-monitoring retention (up to 30 days) is assumed to apply; Zero Data Retention is not established (report 02 §12.4). The packet contains synthetic data only.

## 12. Files and records created or modified

**Created: the investigation artefact.** Directory `demo_history/investigations/PACK-H202602-PER-2026-02-195df2e1f216/EXC-H202602-01/INV-EXC-H202602-01-a3fd3fd2e9ed/`, containing:

- `findings.json`
- `evidence_packet.json`
- `evidence_ledger.json`
- `tool_calls.json`
- `runs/0001.json`

**Created: this report**, `docs/audit_pack/16_FIRST_HISTORICAL_AI_INVESTIGATION_REPORT.md`.

**Modified:** `tests/test_demo_history.py` (one test, see §10).

**Database:** no records created or modified.

## 13. Confirmation

- Exactly **one** AI investigation was run: February 2026, `EXC-H202602-01`.
- **No other month** (January, March–August, September) was investigated.
- **No AI closing summary** was generated.
- **No final audit pack** was generated.
- **Hold and Generate were not executed.**
- No deterministic pack, source dataset, verification material, September pack or investigation artefact was altered.
- No reconciliation rule changed.
- The React dashboard was not changed and no month was registered in it.

**Stopped here pending review.** March and later months will not be investigated until these results are reviewed.
