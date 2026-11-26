# UC-042 Reconciliation Test Suite V2: Capability Gap Register

**Basis:** the current engine `C:\u42v\e2e_20261122\engine_base\uc042\uc042lib` (see SOURCE_DISCOVERY_REPORT §1). The line numbers refer to that copy's `validate.py`.

**Status labels:**

| Label | Meaning |
|---|---|
| EXISTING | Verified by reading the current source in this task |
| MISSING | No code path exists |
| PREDICTED | My reading of the source; it has **not** been executed |
| PROPOSED | A desired future capability. Nothing here is implemented, and no new schema field or control ID is defined. |

| ID | Area | Status | Evidence | What the suite needs | Scenarios |
|---|---|---|---|---|---|
| G-01 | Same-key duplicate rows | EXISTING | `structure.check_rows`: a later duplicate primary key is excluded, reported as DQ-FIELD ("duplicate key", DQ09) and taints its scope | Nothing; not the focus of TC01 | (reference) |
| G-02 | Duplicate records per expected scope | EXISTING | `_cover` (L564–577): more than one IN-05/IN-06/IN-07/IN-08/IN-03/IN-12 record per scope gives a C01/C07/C14 FAIL "duplicate records" | Nothing | (reference) |
| G-03 | Bank-side duplicate reference | EXISTING | CASH-BANK-LINK (L686), RC4-DIRECT (L980) and C11-BATCH-BANK (L903) FAIL when one reference matches more than one bank entry | Nothing | (reference) |
| G-04 | Ledger-side or transaction-side duplicate (many-to-one) | **MISSING** | CASH-BANK-LINK and RC4-DIRECT link each record on its own and never consume the bank entry. Two cash-book rows with the same reference and amount **both PASS** against one bank entry (L671–677). | PROPOSED: one-to-one matching, so that a second claimant of the same bank entry is flagged as a duplicate candidate and classified (exact duplicate vs possibly legitimate repeat), with an explicit duplicate exception category. Category name **PENDING**. | TC01 |
| G-05 | Consolidating the consequences of one root cause | **MISSING** (PREDICTED effect) | C05-RESOURCE and RC2-LEDGER failures get their own `<check>\|<scope>` roots, and no L1/L2/L3 rule connects them to the BANK_LEDGER_DIFFERENCE or INTERNAL_DIFFERENCE they share an input with. | PROPOSED: lineage from a failing cash-book posting to every ledger-derived failure. TC01 is predicted to raise **10 exceptions for one duplicate**. | TC01 |
| G-06 | Amount comparison after a reference link | EXISTING | CASH-BANK-LINK, RC4-DIRECT, C11-BATCH-BANK and C11-BATCH-ARITH compare exact Decimal amounts once a reference link exists | Nothing | TC02, TC06 |
| G-07 | Difference and direction as structured output | **MISSING** | RC4-DIRECT records `computed` = transaction amount and `reported` = bank amount, but no difference or direction field. CBAL-ROLLFWD records expected vs snapshot. | PROPOSED: a structured difference (source A − source B) with direction. The suite's answer keys carry these values independently. | TC02, TC06 |
| G-08 | Lineage from a failing transaction to the roll-forward | **MISSING** | L3 links CBAL-ROLLFWD only to INTERNAL_DIFFERENCE and C04-REQUIREMENT. An RC4-DIRECT failure and the CBAL-ROLLFWD failure for the same transaction's client and day are not linked. | PROPOSED: link them by the shared `txn_id` (record lineage, not amount) | TC02, TC06 |
| G-09 | Outlier-source identification | **MISSING** | The engine reports pairwise disagreement only. It does not record that IN-09, IN-10 and IN-03 agree while IN-11 differs. | PROPOSED: corroboration count per value. Otherwise this is an AI-investigation expectation. | TC02, TC06 |
| G-10 | In-period timing difference (≤ 1 business day) | EXISTING (and EXECUTED BY OTHERS via the SC2 frozen key) | E1 `timing_items` / `timing_assessment` (L129–206) gives TIMING_EVIDENCED, the exception stays OPEN and AWAITING_HUMAN_REVIEW, and the category text changes | Nothing. TC03 (revised) exercises it: clearing on Sat 26 Sep requires the IN-08 statement and IN-07 confirmation for that day to exist (`evidence_gap`) | TC03 |
| G-11 | Timing difference crossing the period end | **MISSING** | The clearing entry falls after `period.end`, so the item is `UNVERIFIABLE` (L150–153 and L170–171) and the exception reads TIMING_UNVERIFIABLE. A file for another period in the case gives V00-FILE FAIL "not used" (L313–326). There is no evidence slot for post-period clearing. | PROPOSED: a supplementary post-period clearing evidence channel (**owner decision**; no schema field invented here). With it, the expectation is TIMING_EVIDENCED, still OPEN, awaiting human confirmation. | (not exercised after the TC03 revision; kept for the record) |
| G-12 | Timing linkage across the batch, cash-book and difference exceptions | **MISSING** (PREDICTED effect) | The C11-BATCH-BANK and CASH-BANK-LINK failures for the uncleared batch are linked by L1 (shared reference). The BANK_LEDGER_DIFFERENCE is **not** linked to them, because L3 needs a bank entry and there is none. | PROPOSED: link a difference to the cash-book entry that its UNVERIFIABLE or IN_WINDOW timing item names | (not exercised after the TC03 revision; kept for the record) |
| G-13 | Preparer's timing claim and log cause | EXISTING (limited) | `timing_difference_claimed` only changes note wording (L832). IN-14 `cause_category` and `cause_evidence_ref` are never read. A logged entry only turns DISC-LOG to PASS. | Nothing (documented limitation) | TC03 |
| G-14 | Bank entry with no counterpart | EXISTING | BANK-CASH-LINK and C11-BANK-ENTRY check `bank_reference` and `end_to_end_ref` against IN-12, IN-11, IN-04 and IN-10 top-ups (L1065–1087). The S05 precedent gives an L3 group. | Nothing | TC04 |
| G-15 | Requirement impact of an unrecorded safeguarding credit | **MISSING** | C04 sees only IN-03 and IN-04. A credit missing from the register cannot raise the recomputed requirement. | PROPOSED: flag an unmatched SGA credit as a potential unidentified receipt with possible requirement understatement (amount = credit). Related to the IN-04 empty-register design of 22 Nov 2026 (not implemented). | TC04 |
| G-16 | Candidate for a multi-record common cause | **PARTIAL** | Candidates exist only for C11-BATCH-ARITH × CBAL-ROLLFWD where **one** missing line equals the roll-forward difference (L1499–1523). A client with two missing spends (difference = their sum) gets no candidate. | PROPOSED: candidates from line sums per client and day; batch-scoped grouping of missing-transaction lines. Still UNVERIFIED; no cause set. | TC05 |
| G-17 | Common-cause conclusion across exceptions | **MISSING / NOT VERIFIED** | AI investigation is per exception. The packet includes the group and candidates, but no group-level synthesis was found (R4). | PROPOSED: a group-level investigation output: individual findings, possible common cause, connecting evidence, missing evidence, confidence | TC05 |
| G-18 | Over-grouping by L3 lineage (b) | **PREDICTED DEFECT** (needs execution) | L1447–1458 link an INTERNAL_DIFFERENCE or C04 to **any** CBAL-ROLLFWD failure of the same currency and date, without checking that the client's snapshot is the faulty input. A roll-forward failure caused by a wrong **transaction** amount for another client would be merged into the internal-difference group. The next-day roll-forward failure of the faulty snapshot is not linked. | PROPOSED: restrict lineage (b) to snapshots that are inconsistent on the snapshot side, e.g. failing both the day-d and day-d+1 roll-forwards, or carrying no transaction-side failure. Owner decision. | TC06 |
| G-19 | Exception and category vocabulary for the four behaviours | **MISSING** | No DUPLICATE, AMOUNT_MISMATCH, TIMING_ITEM or UNMATCHED_TRANSACTION category exists. Existing categories describe the check that failed. | PROPOSED labels are used in the answer keys only as `PENDING:<label>`. They are not control or exception IDs. | All |
| G-20 | Exception IDs in Ringfence | NOT VERIFIED | The engine assigns `EXC-<scenario_id>-NN` (L1352–1354). Whether Ringfence shows the same IDs for an uploaded case was not checked. | Answer keys use **root_cause** as the stable key. Predicted engine IDs are labelled PREDICTED. | All |
| G-21 | Correction and re-upload | EXISTING (executed by others) | Ringfence correction-file flows: M3 corrected files, RF-DEMO-04 corrected IN-09. Investigations are scoped to the execution of each audit run. | No before/after comparison feature was verified. The suite provides separate initial and corrected evidence plus expected results for each. | TC01, TC04, TC05 |
| G-22 | Live AI cost and authorisation | EXISTING constraint | Ringfence auto-starts one live investigation per exception. There is no recorded mode for investigations. | Executing TC01 (predicted 10 exceptions) in Ringfence would make about 10 live calls. Needs owner approval. | All |

## Revision of 23 Nov 2026 (after Stage C)

TC03 now uses a 25/26 Sep timing item resolved under the existing D1 rule:

- **G-10** (existing in-period timing) is exercised.
- **G-11** (crossing the period end) and **G-12** (linking across period-end exceptions) remain valid gaps, but no scenario exercises them.

## Items deliberately not assumed

- No new schema field, file type, control ID, exception ID format or enum value is introduced. IN-14 `cause_category = TIMING` (used in TC03) follows the existing SC2 precedent; the schema has no allowed-value list for that field.
- Items B–D (gap G-S04), D+1 (gap G-R05), `value_date` and `clearing_date` are not read by the engine. Where the suite sets them, they are informational.
- Every PREDICTED current-engine outcome in the answer keys comes from reading the source. It must be confirmed by an engine run, which is not permitted in this task.
