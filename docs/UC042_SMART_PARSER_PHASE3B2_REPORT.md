# UC-042 Smart Parser: Phase 3B-2 report

**Review state machine and governed mapping approvals. 18 November 2026.**

**Working copy:** `C:\Users\artlptp263user\p10\smartparser_phase1`. The UC-042 tree was used read-only.

**Status of the consolidated 3B-2 to 3B-5 assignment:** **3B-2 is complete and verified.** 3B-3, 3B-4, 3B-5 and the consolidated report have **not been started**. Work was paused here at the owner's request, at a clean, fully regressed state.

## Summary

| Area | Status |
|---|---|
| Review state machine (PROPOSED, UNDER_REVIEW, PARTIALLY_DECIDED, REVISION_REQUESTED, APPROVED, REJECTED) | Implemented and tested |
| Column decisions (APPROVE, CHANGE, REJECT, LEAVE_UNMAPPED), each re-validated by the deterministic 3B-1 validator | Implemented and tested |
| Three separate approval scopes: file-specific mapping, header alias, source-system layout | Implemented and tested |
| Category confirmation and category-conflict confirmation (separate authority scopes) | Implemented and tested |
| Configurable authority policy | Implemented. **The production policy authorises nobody** (blocked by owner decision). A test-only policy is used in tests. |
| Governed rule files, versions, revocation, supersession, registry-hash binding | Implemented and tested |
| Append-only, hash-chained JSONL audit | Implemented and tested |
| Business approvals | **Blocked by owner decision.** Only possible under an `OWNER_APPROVED` policy, which does not exist. |

**Tests:** 350 pass, the 327 baseline plus 23 new. Without the UC-042 tree, 347 pass and 3 skip.

**Baselines:** Phase 1 is 445/445 and Phase 2 is 161/161. The registry is in sync.

**Unchanged:** the 19 alias proposals are all still `proposed`, and the production rule files and policy were not written.

## 1. New and modified files

**New**

| File | Purpose |
|---|---|
| `smartparser/mapping/governed.py` | Strict rule records: `LayoutRule`, `FileMappingRule`, `Approval`, `Lifecycle`, `ColumnRule`; `header_fingerprint` (exact ordered list); `definition_sha256` (registry binding) |
| `smartparser/mapping/rule_store.py` | `RuleStore`: a writable governed rule directory (aliases, catalogue, layouts, file mappings). It refuses the packaged production directory, validates each write by reloading (rolled back on failure), never deletes, and changes only lifecycle. |
| `smartparser/mapping/rules/approved_layouts.json` | Production layouts: empty |
| `smartparser/review/audit.py` | `AuditLog`: strict event schema, append-only, SHA-256 hash chain, `verify()`, injectable clock |
| `smartparser/review/authority.py` and `review/authority_policy.json` | `AuthorityPolicy` and `Reviewer`. The production policy is `PRODUCTION_UNCONFIGURED` with no roles. |
| `smartparser/review/session.py` | `ReviewSession` state machine; `open_review`, `decide_column`, `approve_proposal`, `reject_proposal`, `request_revision`, `link_revision` |
| `smartparser/review/approvals.py` | `confirm_category`, `approve_file_mapping`, `approve_alias`, `approve_layout` (with `supersedes`), `revoke_rule` |
| `tests/phase3b_support.py`, `tests/test_review_3b2.py` (23 tests), `tests/fixtures/review/test_authority_policy.json` | Tests; a test-only policy marked "NOT an owner decision" |

**Modified (additive)**

| File | Change |
|---|---|
| `mapping/controlled.py` | `MappingRules` gains `layouts`, `file_mappings`, `file_identity`, `with_file_identity()` and `header_rules_for()`. `aliases_for()` returns **active** aliases only. `load_rules` loads layouts and file mappings strictly and checks registry hashes and collisions. `controlled_map` applies an exact-header-list rule inside the same all-or-nothing checks; a rule that disagrees with a deterministic name is rejected. Mappings carry `rule_id` and `rule_version`. |
| `mapping/proposals.py` | `ProposalRecord.revision_of` (optional) |
| `mapping/proposal_runner.py` | `run_proposal(..., revision_of=None)` |
| `models/enums.py` | `MatchMethod.APPROVED_LAYOUT`, `APPROVED_FILE_MAPPING` |
| `models/results.py` | `ColumnMapping.rule_id`, `rule_version` |
| `pyproject.toml` | Package data for `review/authority_policy.json` |

No existing test was changed.

## 2. State machine

Allowed transitions:
- PROPOSED → UNDER_REVIEW
- UNDER_REVIEW → PARTIALLY_DECIDED, APPROVED, REJECTED or REVISION_REQUESTED
- PARTIALLY_DECIDED → PARTIALLY_DECIDED, APPROVED, REJECTED or REVISION_REQUESTED
- APPROVED, REJECTED and REVISION_REQUESTED are terminal.

Any other transition raises `ReviewError`.

**Rules:**
- **CHANGE:** the new field must belong to the confirmed category, and all chosen fields are re-validated together. That catches duplicate targets, fields already resolved and value-rule conflicts.
- **APPROVE as proposed:** only allowed for CLEAR, PLAUSIBLE or AMBIGUOUS columns. **NO_MATCH (including explicit UNMAPPABLE in either form) and CONFLICT columns can never be approved as proposed**; this is tested for both UNMAPPABLE forms.
- **Partial decisions** are saved (`save`/`load`) and never applied: the file stays `unknown` and no rule exists.
- **APPROVED** requires every column decided and no blocking conflict. It records `final_summary` (`complete`, `missing_required_fields`, `unmapped_columns`).
  - **Approval does not mean the file is complete.** For example, the owner's short example is approved with 4 required fields still missing.
- **Rejection** needs a reason, and a **revision request** needs a note. A revision is a **new proposal identity** with `revision_of` linked and audited.

## 3. Approval scopes and authority

| Scope | Function | Authority scope | Applies to | Notes |
|---|---|---|---|---|
| File-specific mapping | `approve_file_mapping` | FILE_MAPPING | Only the matching **intake ID and SHA-256**, and the exact header list | Requires an APPROVED session. References the proposal, session and decision IDs. Creates **no** alias or layout (tested). |
| Header alias | `approve_alias` | ALIAS | Any future file of the category with that header (case and whitespace under policy) | Separate catalogue entry and active alias. Collisions are refused and rolled back. **Sign-sensitive fields are refused** unless the policy allows them (an open owner decision). |
| Source-system layout | `approve_layout` | LAYOUT (test policy: 2 approvers, data_owner **and** system_owner) | Files whose **exact ordered header list** matches (no normalisation) | Declared `source_system` and version are required. Every column must be mapped and every required field covered. Sign-sensitive fields need explicit acknowledgement. |
| Category confirmation | `confirm_category` | CATEGORY_CONFIRMATION | One upload | |
| Conflict confirmation | `confirm_category(..., content_category=...)` | CATEGORY_CONFLICT | One upload | Separate scope |
| Revocation | `revoke_rule` | REVOCATION | One rule version | |

**Authority policy:**
- The shipped `review/authority_policy.json` is `PRODUCTION_UNCONFIGURED`, has **no roles** and does not allow test identities. Every approval is refused, and a test checks this for every scope.
- **TEST approvals** require `allow_test_identities`.
- **BUSINESS approvals** require `status: OWNER_APPROVED`.
- Every decision and rule records `approval_kind` (TEST or BUSINESS).
- The test policy uses the provisional Phase 3A roles (analyst; data_owner; data_owner plus system_owner) and is labelled as not an owner decision.

## 4. Rule lifecycle

- **Status** is `active`, `revoked` or `superseded`. Only `active` rules match.
- **Revocation** records who, when (with role) and why. It refuses a rule that is not active.
- **Supersession** of a layout keeps the same `layout_id`, with version n+1 and `superseded_by` set on the old version. It is atomic.
- **Nothing is deleted.** Earlier results keep their `rule_id`/`rule_version`. A test confirms a result processed under v1 still shows v1 after supersession and revocation.
- **Registry binding:** every layout and file mapping (and governed alias) carries the category definition hash. A changed registry makes the rule load fail rather than match.

## 5. Audit

Events:
- review and decisions: `PROPOSAL_REVIEW_OPENED`, `COLUMN_DECIDED`, `PROPOSAL_APPROVED`, `PROPOSAL_REJECTED`;
- revisions: `REVISION_REQUESTED`, `REVISION_CREATED`;
- rules and categories: `RULE_CREATED`, `RULE_ACTIVATED`, `RULE_REVOKED`, `RULE_SUPERSEDED`, `CATEGORY_CONFIRMED`;
- reserved for later phases: provider-call, reprocessing and handoff events.

Each event carries the proposal, session, rule, intake and SHA-256 references where applicable.

Properties (all tested):
- Malformed events are refused before writing.
- The file is only appended.
- `verify()` detects edited, reordered or deleted history through the hash chain.

## 6. Test results (executed on 18 Nov 2026)

| Suite | Result |
|---|---|
| **3B-2** (`tests/test_review_3b2.py`) | **23 passed** |
| 3B-1, including the UNMAPPABLE correction | 40 passed |
| 3B-0 | 117 passed |
| Phase 1 and original | 136 passed |
| Phase 2 | 34 passed |
| **Full suite** | **350 passed** |
| Full suite with `UC042_ROOT=/nonexistent` | 347 passed, 3 skipped |
| Registry `--check` | in sync, 19 definitions |
| Phase 1 baseline | 445/445 |
| Phase 2 corpus | 161/161 |

**Fixed during the phase:** `approve_proposal` checked for undecided columns before checking the state. It now refuses invalid transitions first, which a test caught.

## 7. Integrity

- **UC-042 code** (107 `.py` files) and **datasets** (624 files): unchanged (SHA-256).
- **Desktop Smart Parser** (63 files): unchanged.
- **Production rules:** aliases empty, layouts empty, 19 proposals all `proposed`. The production authority policy has no roles.

## 8. Open owner decisions (blocking business use)

1. **Roles:** which real roles may approve file mappings, aliases and layouts, and whether layouts need two approvers.
2. **Category decisions:** who may confirm an unfamiliar category, and who may resolve a category conflict.
3. **Sign-sensitive aliases:** may a reusable alias ever target a sign-sensitive field (`allow_sign_sensitive_reusable`, default false)?
4. **Location:** where the governed rule store and audit log live in a real deployment. In tests, they are temporary directories.

## 9. Not yet done (remaining work of the consolidated assignment)

- **3B-3:** deterministic reprocessing from stored originals, the handoff checklist, the preview-only canonical writer and sidecar, and the D-1 gate.
- **3B-4:** provider configuration and feature flags, the budget gate, deduplication, versioned prompt and schema, the disabled provider adapter, and call audit.
- **3B-5:** the evaluation dataset and metrics, and end-to-end scenarios A to J.
- **The consolidated report.**

The smoke run already showed the 3B-3 core path working: an approved file mapping re-applied through the normal pipeline maps `complete`, validates, and matches only the original intake. It is not yet packaged as a reprocessing module or tested as such.
