# Phase 8: Route-by-Route Migration Readiness (NOT migrated)

Nothing has been switched. The application (`uc042app/services/investigations.py`) still runs `mode="tools"` for every investigation. The library default stays `fixed`. `deterministic` is an opt-in mode of the library only.

## Preconditions met offline (in this copy)

| Precondition | Status |
|---|---|
| Deterministic retrieval implemented beside tools mode | **Done**: `uc042lib/investigation/det_retrieval.py`, rule `uc042-det-retrieval/1.3` (DR-01 and DR-03 fixed), packet `uc042-evidence-packet/2.0-det` |
| Offline parity: every record a model fetched and cited in a persisted tools-mode investigation is supplied | Record parity **100%**: 77/77 distinct and 162/162 instances, all from 29 completed investigations. 51 tools-mode attempts were compared: 22 published, 7 completed but not published and 22 failed (no targets). 2 fixed-mode records are excluded, with the reason. **Strict NOT_FOUND parity is 95/96**, corrected from the previously reported 96/96 (DR-02). The one miss is a `follow_relationship`-shaped query in Clone E EXC-CASE-01; its fact is present as a file-shaped NOT_FOUND search (`det_parity_v13.json`). MISS items and candidates are unchanged (informational checks) |
| Bounded packets, explicit pruning | No supported packet reaches the 140-record budget (largest 77); pruning register recorded in the packet; nothing removed silently |
| Pre-request size guard for single-request modes | **Done**: `UC042_SINGLE_REQUEST_MAX_INPUT_TOKENS` (default 150,000 estimated) |
| Mode and retrieval rule recorded on new investigations | **Done**: `investigation_mode`, `workflow_version` 3.0-det, `model_metadata.retrieval_rule_version`, `model_view_version` / `model_view_sha256` |
| Rollback | Tools mode untouched and still the application mode; `deterministic` falls back to tools for uncovered routes |

## Not yet met (gates before any route switches)

1. **Live A/B (phase 7)**, which needs budget approval. No route has live evidence in deterministic mode yet.
2. **Uncovered routes** (no deterministic plan; they fall back to tools):
   - C07-BANK-EVIDENCE (10 exceptions in the CASE pack);
   - BC-VS-EOD (9);
   - DQ23-STATEMENT (1);
   - UNMATCHED_CASHBOOK_ENTRY (3 historical);
   - any other `generic` / `insufficient_evidence` kind.
3. **Production observation**: all parity data is synthetic.
4. **Owner approvals**: prompt versions (1.6 / 2.6-tools), the output-token setting, the closing-summary change (guard re-pin).

## Proposed order, once the gates pass

| Step | Routes | Condition |
|---|---|---|
| 1 | `missing_bank_evidence`, `unverified_relationship` | every B run VALID and median input lower |
| 2 | `settlement_discrepancy`, `bank_ledger_mismatch` | same, plus no truncation in B runs |
| 3 | `customer_balance_discrepancy`, `unmatched_bank_entry` | same, plus large-group (SC5C) runs within budget |
| — | `generic`, `insufficient_evidence` | only after plans exist and parity is shown on the CASE pack |

Implementation of a switch, when approved: a per-route setting read by `InvestigationService._execute` (for example `UC042_DETERMINISTIC_ROUTES`), defaulting to empty, so tools mode stays the default and every switch is reversible. **Not implemented here**, because the A/B gate is not met.
