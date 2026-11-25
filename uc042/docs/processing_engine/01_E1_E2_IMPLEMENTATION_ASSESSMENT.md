# 01 — E1 and E2 Implementation Assessment

Assessment date: 30 Oct 2026. **Read-only.** No source code, dataset, golden snapshot or test was changed. Line numbers refer to `uc042lib/validate.py` as delivered.

**Summary.**

- **E1** fails because no step in the engine ever looks for clearing evidence. The C08 check only computes bank − ledger and appends a note when a timing claim exists. The data needed to evidence the timing difference is already read by two other checks, but it is never combined.
- **E2** has three causes:
  - root-cause grouping recognises only two patterns: missing-evidence days and persisting bank-ledger differences;
  - every other failure gets its own root-cause string;
  - there is no structure above an exception to link related ones.

Both can be fixed with small, local additions. No existing control calculation, outcome, exception ID or answer-key result has to change.

## 1. Relevant source files and functions

| Location | Function | Role in E1 / E2 |
| --- | --- | --- |
| `validate.py` 52 | `business_day_after(d, n)` | Business-day arithmetic (UK weekdays minus a synthetic holiday list). Reusable for the one-business-day window (D1). |
| `validate.py` 285 | `Validator.point(d)` | 17:00 Europe/London reconciliation point |
| `validate.py` 289 | `Validator.run()` | Fixed order: load → setup → checks → `group_exceptions()` |
| `validate.py` 502 | `check_cashbook_bank_links()` | Links each cash-book entry to **one bank entry by reference** (`payment_reference` = `bank_reference` or `end_to_end_ref`); compares signed amount and currency. **Does not compare dates or times.** |
| `validate.py` 544 | `ledger_at(acct, when)` | Item A / ledger balance: cash-book entries posted at or before the point |
| `validate.py` 620 | `check_external()` | C07 (reported bank balance against confirmation); RC2 (ledger); **C08 (bank − ledger)**. Lines 663–670 produce the E1 result. |
| `validate.py` 672 | `check_settlement()` | C11 batch arithmetic; **C11-BATCH-BANK** (lines 708–722): batch → bank by `expected_bank_reference`, then signed amount. `sdate` is used only to find evidence gaps, **not to compare the booking date**. |
| `validate.py` 867 | `check_unmatched_bank_entries()` | `C11-BANK-ENTRY`: bank entry with no counterpart → root `UNMATCHED_BANK_ENTRY` |
| `validate.py` 910 | `check_client_rollforward()` | `CBAL-ROLLFWD` per client per day-pair; no root cause set |
| `validate.py` 1031 | `_group_exceptions()` | All root-cause assignment and exception building (E2) |
| `validate.py` 1143 | `EXC_COLS` | Exception record columns |
| `validate.py` 1159 | `compare_answer_key()` | Compares non-passing results and `(exception_id, severity, root_cause, affected_results)` only |
| `validate.py` 79 | `Validator.add()` | Result record: `check_id, control, scope, outcome, computed, reported, evidence, note, root_cause` |
| `tools/verify_datasets.py` | `verify()` | The independent verifier **already implements** the timing analysis E1 needs ("cross-day items within one business day", "difference fully evidenced as timing"). It is a reference implementation and oracle, not engine code. |

## 2. Current execution flow (relevant part)

```text
run()
 ├─ check_cashbook_bank_links()  cash entry ↔ bank entry by reference; amount + currency only
 ├─ check_external()             per ERL row: C07, RC2, C08 = bank(17:00 confirmation) − ledger(cash book to 17:00)
 ├─ check_settlement()           batch → bank by reference; amount only
 ├─ … other checks (each failure appended to self.results; most with root_cause = "")
 └─ group_exceptions()
      1. C08 FAILs: contiguous recon days, same account, same difference → root BANK_LEDGER_DIFFERENCE|acct|d0|diff
      2. DISC-LOG per difference group
      3. C06 FAILs → root INTERNAL_DIFFERENCE|<date>/<ccy>   (one per day)
      4. any other FAIL/INSUF without a root → root "<check_id>|<scope>"   (one per result)
      5. group results by root → one exception per root
      6. S05 only: "related_records" = unmatched bank entries on the difference's first day (informational text)
```

## 3. Exact root cause of E1

Scenario SC2, SGA-GBP-01, 15 Sep:

| Fact in the data | Read by | Used for timing? |
| --- | --- | --- |
| Cash-book entry `LE-GBP-0915-0005`, SCHEME_SETTLEMENT, 2,868.50 C, posted 15 Sep 15:00, reference `SB-GBP-20260915` | `ledger_at` (C08 ledger side); `check_cashbook_bank_links` | No |
| Bank entry `BE-GBP-0916-T01`, 2,868.50 D, same reference, booked **16 Sep 08:00** | `check_cashbook_bank_links` (PASS: reference + amount); `check_settlement` (PASS: reference + amount) | No |
| 15 Sep 17:00 confirmation 331,179.44 (excludes the debit) | C08 bank side | — |
| C08: bank 331,179.44 − ledger 328,310.94 = **+2,868.50** | `check_external` line 663 | — |

**Root cause.** At lines 663–670, `check_external` has only three branches:

1. difference ≠ reported → FAIL;
2. difference = 0 → NOT_APPLICABLE;
3. otherwise → FAIL "unexplained bank-ledger difference", plus the text "(timing claimed, not evidenced)" whenever `timing_difference_claimed` is `"true"`.

The word "evidenced" is only a label on the claim flag. **No code searches for clearing evidence.** Requirement R08 (accept a timing difference only with evidence) was specified in the research documents but never implemented.

**Contributing gaps:**

- **(a) Reference links ignore time.** `check_cashbook_bank_links` and `check_settlement` both find the 16 Sep entry by reference, but neither compares `booking_ts` with `posted_ts` or `settlement_date`. The one-day lag is invisible.
- **(b) Window not wired.** `business_day_after` exists but is not connected to D1.

**Existing matching logic:**

| Aspect | Present | Where |
| --- | --- | --- |
| Reference matching | Yes | Cash ↔ bank, batch ↔ bank, RC4 transaction ↔ bank, register ↔ bank |
| Amount matching | Yes, only **after** a reference link; never alone | Same functions |
| Currency matching | Yes | Same functions; C13 |
| Date matching | Only for coverage and evidence gaps (`evidence_gap`), and the point-in-time cut-off in `ledger_at` and BC-VS-EOD | — |
| Timing tolerance or window | **None.** All comparisons are exact; "tolerance" does not appear in the code. | — |

## 4. Exact root cause of E2

| Scenario | Results | Root strings assigned by `_group_exceptions` | Exceptions | Why separate |
| --- | --- | --- | --- | --- |
| SC3C | C08 × 17, DISC-LOG, C11-BATCH-BANK, CASH-BANK-LINK | `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-08\|-4.50` (step 1); `C11-BATCH-BANK\|AQ-GBP-20260908` and `CASH-BANK-LINK\|LE-GBP-0908-0003` (step 4 fallback) | 3 | The step-4 fallback makes one root per result. Nothing records that all three involve reference `AQ-GBP-20260908` and bank entry `BE-GBP-0908-AQ1`. |
| SC5A | C11-BATCH-ARITH, CBAL-ROLLFWD | Both by step-4 fallback | 2 | Fallback. **Also: no record links them** (see §5.3). |
| SC5C | C06 × 16, CBAL-ROLLFWD | `INTERNAL_DIFFERENCE\|<date>/GBP` **per day** (step 3) + fallback | 17 | Step 3 groups C06 per day. The persistence rule used for C08 in step 1 was never applied to C06. |
| SC5D | C04, C06, CBAL-ROLLFWD | C06 step 3; C04 and CBAL fallback | 3 | Fallback, plus no link between C04 and C06 for the same scope |

**Grouping mechanisms that already exist:**

- **`root_cause` string per result.** This is the only grouping key: one exception per distinct string.
- **Persistence grouping** for C08 only (step 1).
- **`diff_groups`** (internal list, used for DISC-LOG).
- **`related_records`** on bank-ledger exceptions: free text listing unmatched entries on the first day, "not linked by amount". Informational only.
- **No correlation ID, no group object, no link record** between exceptions. Exceptions carry no reference to each other.

## 5. Recommended implementation changes

### 5.1 E1: deterministic timing-evidence evaluation (local to `check_external`)

Add one helper and call it in the C08 non-zero branch. **Control outcomes do not change:** C08 stays FAIL on the day the difference exists, and the exception stays OPEN. Nothing is auto-resolved.

**`timing_items(acct, d)`** returns the cross-day items for an account at reconciliation point *d*:

- **Ledger-before-bank:** a cash-book entry with `posted_ts` ≤ point(d), linked **by reference** to exactly one bank entry on the same account and currency with the same signed amount, and with `booking_ts` > point(d) and `booking_date` ≤ the next business day after *d* (D1). Its effect on bank − ledger is −(ledger signed amount).
- **Bank-before-ledger:** the mirror case: bank booked ≤ point(d), ledger posted after point(d) within the window. Effect: +(bank signed amount).
- **Outside the window:** a reference-linked item whose lag exceeds one business day is listed, but does not count.
- **Clearing evidence missing:** if the bank or ledger evidence for the clearing day is missing or tainted (`evidence_gap`), or the clearing day is after the period end, the item is **unverifiable** and does not count.

**Classification of each non-zero C08 day:**

| Condition | `timing_status` |
| --- | --- |
| Σ effects = difference, and every item verified | `TIMING_EVIDENCED` |
| Some verified items, but Σ ≠ difference | `TIMING_PARTIAL` (residual = difference − Σ) |
| Claim made or items exist, but none verified | `TIMING_NOT_EVIDENCED` / `TIMING_UNVERIFIABLE` |
| No items and no claim | none (current behaviour) |

**Output changes:**

- The C08 note states the status and cites the cash-book row and clearing bank-entry rows. Those rows are appended to `evidence`.
- New exception fields `explanation_status` and `explanation_evidence`.
- The status remains `OPEN` with "awaiting human confirmation".

**Batch-to-bank lag (informational).** In `check_settlement`, report the booking lag in the C11-BATCH-BANK note (for example "booked 1 business day after settlement date, within D1"). The outcome is unchanged. Whether a lag beyond the window should *fail* would be a new control and needs a separate decision.

**Expected effect:**

| Scenario | Result |
| --- | --- |
| SC2 | C08 15 Sep: FAIL +2,868.50, `TIMING_EVIDENCED` by `LE-GBP-0915-0005` → `BE-GBP-0916-T01`. `EXC-SC2-01` OPEN, explained, pending review. |
| S05 and SC3C | `TIMING_NOT_EVIDENCED` (no cross-day items) |
| All other datasets | No change |

### 5.2 E2: investigation groups above unchanged exceptions

**Keep `_group_exceptions` exactly as it is.** Exceptions keep their IDs, severities, root causes and affected results, so the answer keys still match.

Add a separate deterministic step, `correlate_exceptions()`, run after it. It links exceptions only through **evidence-based link rules**, then forms groups as connected components:

| Link rule | Basis (never amount alone) | Applies to |
| --- | --- | --- |
| **L1 Reference** | Two exceptions cite records sharing a batch ID or payment/bank reference (`expected_bank_reference` = `bank_reference` = `payment_reference`) | SC3C: batch-to-bank ↔ cash link (`AQ-GBP-20260908`) |
| **L2 Persistence** | Same check, same account or currency, consecutive reconciliation days, same recomputed difference: the rule already approved for C08, applied to C06 | SC5C: 16 daily internal differences |
| **L3 Lineage** | A source row that fails one check is a direct input to the computation of another failing check, for the same account or currency and date | (a) a bank entry booked ≤ point(d) is a component of the 17:00 balance used by C08 on *d* (SC3C `BE-GBP-0908-AQ1`; S05 `BE-GBP-0917-X01`); (b) a client snapshot row failing roll-forward on *d* is an input to the requirement (C04/C06) on *d* (SC5C, SC5D); (c) C06 consumes C04's recomputed requirement for the same scope (SC5D) |

**What a group may never do:**

- set a cause;
- change a status, severity or outcome;
- merge exceptions;
- use an AI or probabilistic component.

### 5.3 Finding: scenario 5a cannot be grouped on evidence

In SC5A the missing transaction `TX-0915-00009` is absent from the export. The only record carrying its ID is the settlement line, and lines and batches hold no client ID. Nothing links the batch-arithmetic failure to C0002's roll-forward failure, except that:

- they are on the same date; and
- the roll-forward gap (443.55) equals the line amount.

That is an amount coincidence, which the design forbids as a link.

**Recommendation:** SC5A stays as **2 exceptions with no group**. Optionally, record a **candidate relationship** with basis `DATE_AND_AMOUNT_COINCIDENCE`, clearly labelled *not evidence* and never grouped, for the human reviewer (decision D-E2a).

The SC5A answer key's `target_outcome` ("one exception … linked by reference") **overstates what the evidence supports** and should be corrected. This is metadata only.

## 6. Proposed data structures

**Result record:** unchanged columns, plus one optional field on C08 results:

```text
timing_status: "" | TIMING_EVIDENCED | TIMING_PARTIAL | TIMING_NOT_EVIDENCED | TIMING_UNVERIFIABLE
```

**Exception record** (`EXC_COLS`): existing columns unchanged, plus three appended:

| Field | Example | Notes |
| --- | --- | --- |
| `investigation_group_id` | `GRP-SC3C-01` | Blank if not grouped |
| `explanation_status` | `TIMING_EVIDENCED` | Blank unless E1 applies. Never closes the exception. |
| `explanation_evidence` | `IN-10:…#L95; IN-09:…#L131` | Row citations |

**Investigation group** (new output `validation/investigation_groups.csv`):

| Field | Example |
| --- | --- |
| `group_id` | `GRP-SC3C-01` (ordered by first exception ID) |
| `exception_ids` | `EXC-SC3C-01; EXC-SC3C-02; EXC-SC3C-03` |
| `primary_exception_id` | Highest severity, earliest date |
| `links` | `EXC-SC3C-02—EXC-SC3C-03 L1 reference AQ-GBP-20260908 [IN-12:…#L…; IN-10:…#L…]`; `EXC-SC3C-01—EXC-SC3C-02 L3 BE-GBP-0908-AQ1 in 17:00 balance 8 Sep [IN-09:…#L…; IN-07:…#L…]` |
| `status` | `OPEN` (always; humans close) |
| `cause` | Blank (never set by the engine) |
| `correlation_version` | `deterministic-v1` |

**Optional candidate relationship** (only if D-E2a is approved): `candidate_links` with `basis`, `exception_ids` and the label `NOT EVIDENCE`. Kept separate from groups.

## 7. Regression test plan

### Existing tests affected

| Test | Effect |
| --- | --- |
| `test_scenario_datasets.test_timing_difference_evidenced_within_one_business_day` | Asserts the C08 note contains "not evidenced". It encodes limitation E1 and must change to assert "evidenced", with justification. The outcome assertion (FAIL, +2,868.50) is unchanged. |
| All answer-key, golden, hardening, period and scenario tests | Unaffected: exception IDs, severities, roots, affected counts and outcomes are unchanged. Golden snapshots store none of the new fields or the notes. |

### New E1 tests

| # | Case | Expected |
| --- | --- | --- |
| E1-1 | SC2 | 15 Sep C08 FAIL +2,868.50, `TIMING_EVIDENCED`, cites `LE-GBP-0915-0005` and `BE-GBP-0916-T01`; exception OPEN |
| E1-2 | S05, SC3C | `TIMING_NOT_EVIDENCED`; no items |
| E1-3 | SC2 copy with the clearing entry moved 2 business days later | Item outside the window → not evidenced |
| E1-4 | SC2 copy, clearing entry amount 2,868.00 | No link (amount differs after the reference match) → not evidenced |
| E1-5 | SC2 copy, clearing entry with a different reference, same amount | Not evidenced (no amount-only matching) |
| E1-6 | Two in-transit items, one cleared | `TIMING_PARTIAL`, residual reported |
| E1-7 | SC2 copy with the 16 Sep statement removed | `TIMING_UNVERIFIABLE` |
| E1-8 | Posting on 30 Sep, clearing would be 1 Oct | `TIMING_UNVERIFIABLE` (outside the period) |
| E1-9 | Any dataset | No C08 outcome changes from FAIL; no exception status other than OPEN |
| E1-10 | SC2 C11-BATCH-BANK | Outcome PASS unchanged; note reports a 1-business-day lag |
| E1-11 | Baseline | No timing items; results identical to golden |

### New E2 tests

| # | Case | Expected |
| --- | --- | --- |
| E2-1 | SC3C | 1 group of 3 exceptions; links L1 (reference `AQ-GBP-20260908`) and L3 (`BE-GBP-0908-AQ1` in the 8 Sep balance) |
| E2-2 | SC5C | 1 group of 17 (L2 across 16 days, L3 from `CBS-20260909-C0002-GBP`) |
| E2-3 | SC5D | 1 group of 3 (L3) |
| E2-4 | SC5A | **No group**; 2 independent exceptions (candidate link only if D-E2a) |
| E2-5 | S05 | 1 group of 2 (L3 `BE-GBP-0917-X01` in the 17 Sep balance) |
| E2-6 | S02, SC2, SC3B, baseline | No groups (single or no exceptions) |
| E2-7 | All datasets | Exception list identical to the answer keys and golden (individual exceptions preserved) |
| E2-8 | All groups | `status` OPEN, `cause` blank; every link cites rows |
| E2-9 | Negative: differences on two accounts on the same day | Not grouped |
| E2-10 | Negative: two exceptions with equal amounts and no shared reference or lineage | Not grouped |
| E2-11 | Determinism | Group IDs and membership identical across runs |
| E2-12 | Independent check | `tools/verify_datasets.py` agrees on the shared references and lineage rows |

## 8. Side effects and backward compatibility

| Area | Effect |
| --- | --- |
| Control outcomes, exception IDs, root causes, affected counts | **Unchanged.** Answer keys and golden snapshots still match. |
| `exceptions.csv` | Three columns appended. Readers using column names are unaffected; strict column-count readers need updating. |
| New file `investigation_groups.csv` | Additive |
| `control_results.csv` | C08 and C11-BATCH-BANK notes and evidence lists change in SC2 (notes are not in golden); optional `timing_status` column appended |
| `VALIDATION_REPORT.md` | New "Investigation groups" and "Timing evidence" sections |
| `trace.py` | Should accept `GRP-…` IDs (small addition) |
| Answer keys (dataset metadata, not evidence) | Add expected groups and timing status, and correct the SC2, SC3C, SC5A, SC5C and SC5D `target_outcome` text, by regenerating via `scenarios.py`. Evidence files and manifests untouched. Needs approval, since datasets were frozen for this task. |
| Business-day calendar | `business_day_after` uses a synthetic UK holiday list; the reconciliation calendar is the case configuration. For September these agree. Recommend using the next reconciliation day from the calendar, for consistency. |
| Risk of over-grouping | Limited to the three explicit rules; negative tests E2-9 and E2-10 guard it |

## 9. Decisions needed before implementation

| # | Decision | Recommended default |
| --- | --- | --- |
| D-E1a | C08 outcome stays FAIL when timing is evidenced (explained, not resolved) | Approve |
| D-E1b | A batch-to-bank lag beyond the window: informational only now; a failing control later if wanted | Informational only |
| D-E2a | Record non-evidential candidate relationships (SC5A) | Yes, labelled `NOT EVIDENCE`, never grouped |
| D-E2b | Update answer-key metadata (expected groups, timing status, corrected `target_outcome`) by regenerating via `scenarios.py`; no evidence changes | Approve |

## 10. Recommended implementation order

1. **E1 timing evaluation.** It is local to `check_external` (plus a note in `check_settlement`), independent of E2, and reuses `business_day_after`. Tests E1-1 to E1-11. The one existing test that encodes the limitation is updated with justification.
2. **E2 correlation layer.** Add `correlate_exceptions()` after `_group_exceptions()`, then the new exception columns and `investigation_groups.csv`. Tests E2-1 to E2-12. It runs after E1 so groups can show timing status.
3. **Answer-key metadata (D-E2b).** Expected groups and timing statuses, plus corrected target text, via `scenarios.py`. Evidence untouched; confirm with the independent verifier.
4. **Report and trace.** Validation report sections, and `trace` support for group IDs.

Stop after step 4 for review, before any audit-pack work (E3).
