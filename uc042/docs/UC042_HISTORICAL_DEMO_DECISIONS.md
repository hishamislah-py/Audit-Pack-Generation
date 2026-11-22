# UC-042 — Historical demonstration decisions (January–August 2026)

> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**

**Status:** approved for implementation, 4 November 2026.

**Background:**

- the options: `docs/audit_pack/14_HISTORICAL_JAN_AUG_DETERMINISTIC_EXECUTION_REPORT.md` §P;
- the implementation: `docs/audit_pack/15_HISTORICAL_AI_INTEGRATION_READINESS_REPORT.md`.

These decisions concern **synthetic demonstration data only**. None of them is a statement about Moorwand practice, policy or records.

| ID | Decision | Recorded and enforced in |
| --- | --- | --- |
| HD-1 | Policy v1.1 for January–April 2026 | `uc042lib/policy.py`, `POLICY_VERSIONS["1.1"]` |
| HD-2 | Policy v1.2 for May 2026 | `uc042lib/policy.py`, `APPROVED_SELECTIONS["PER-2026-05"]` |
| HD-3 | GBP discrepancy accepted as generated; the exception stays OPEN | engine behaviour (unchanged); tests |
| HD-4 | Inconsistent settlement reference: reference-only mutation | historical package (unchanged); tests |

## HD-1 — Policy v1.1 (January–April 2026)

**Decision:**

- `safeguarding_reconciliation_policy_v1.1.pdf` is accepted as an **illustrative synthetic demonstration document** for January–April 2026;
- it is **not** an actual or historical Moorwand policy, and must never be presented as one.

**Rules:**

- Registered as classification `ILLUSTRATIVE_SYNTHETIC`, effective 2025-10-01, superseded by v1.2 from 2026-05-07.
- At upload and intake it is recognised only if its text carries the required markings:
  - "ILLUSTRATIVE SYNTHETIC DOCUMENT";
  - "NOT AN OFFICIAL RECORD";
  - "Illustrative predecessor of policy v1.2".
- A copy without its watermarks is rejected.
- The file is never altered. It keeps its versioned name (`…_v1.1.pdf`) in every case folder.
- The version used is visible in three places:
  - the pack's `audit_trail.inputs`;
  - the intake reasons (`audit_trail.intake`: "policy v1.1 (ILLUSTRATIVE_SYNTHETIC) SELECTED …");
  - the C03-POLICY citation.
- The upload analysis shows the analyst `ILLUSTRATIVE_SYNTHETIC_POLICY`: "not an actual or historical Moorwand policy".

## HD-2 — Policy v1.2 for May 2026

**Decision:** May 2026 is reconciled under **v1.2**, the version in force at the period end.

**Rules:**

- Both v1.1 (1–6 May) and v1.2 (from 7 May) apply to May. The engine never chooses between them. The selection is the approved entry `APPROVED_SELECTIONS["PER-2026-05"]`.
- Both documents stay in the May source inventory and the pack's audit trail:
  - v1.1 is `SUPPLIED_NOT_SELECTED`;
  - v1.2 is `SELECTED`.
- v1.1 is never discarded.
- Finding preserved from report 14 §F: run in isolation, v1.1 and v1.2 give **identical results** (1,703 results, 4 exceptions, the same groups), apart from the cited policy file name.
- The May deterministic pack `PACK-H202605-PER-2026-05-051d209cccc4` stays **pending review and approval**. It is not regenerated.

## HD-3 — Unexplained GBP discrepancy

**Decision:** the historical GBP discrepancy scenario is accepted as generated:

- March −517.30 (17–19 Mar);
- May −1,093.65 (18–20 May);
- August −276.90 (17–19 Aug).

**Rules:**

- The later matching bank credit brings the balance back into agreement. It **does not establish the cause** of the original debit.
- The `BANK_LEDGER_DIFFERENCE` exception stays **OPEN**, `AWAITING_HUMAN_REVIEW`, with no cause recorded. So do its two `UNMATCHED_BANK_ENTRY` exceptions.
- Nothing marks it resolved automatically. A balance agreeing later is not a formal resolution.
- No code, pack or narrative states the cause, or describes the difference as resolved, reversed or corrected.

**Tests:** `tests/test_demo_history.py`:

- `test_unexplained_gbp_difference_march`;
- `test_unexplained_difference_is_not_described_as_resolved`.

`tests/test_historical_integration.py` covers HD-3 too.

## HD-4 — Inconsistent settlement reference

**Decision:** the reference-only mutation is retained (June, July, August).

**Rules:**

- Only the bank entry's `bank_reference` is changed. Its `narrative_text` keeps the correct batch reference.
- No narrative mutation is introduced.
- Records are never matched on amount alone. The engine's matching rules and calculations are unchanged.

**Tests:** `tests/test_demo_history.py`:

- `test_inconsistent_reference_june_is_never_matched_on_amount`;
- `test_inconsistent_reference_with_the_narrative_also_changed` (temporary copy only).

`tests/test_historical_integration.py` covers HD-4 too.
