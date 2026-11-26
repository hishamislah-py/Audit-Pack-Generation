"""Phase 3B-2: review state machine, authority policy, three separate approval scopes, rule lifecycle and audit."""
import json

import pytest

from smartparser.mapping.controlled import RULES_DIR, MappingRulesError, load_rules
from smartparser.mapping.governed import ColumnRule
from smartparser.mapping.rule_store import RuleStore, RuleStoreError
from smartparser.review.audit import AuditError, AuditLog
from smartparser.review.authority import AuthorityError, AuthorityPolicy, Reviewer
from smartparser.review.approvals import (
    approve_alias, approve_file_mapping, approve_layout, confirm_category, revoke_rule,
)
from smartparser.review.session import (
    ReviewError, ReviewSession, ReviewState, approve_proposal, decide_column, link_revision, open_review,
    reject_proposal, request_revision,
)

from .phase3b_support import (
    ANALYST, ANALYST2, OWNER, SYSOWNER, dump, make_env, read, renamed_in10, short_example, SEP, tbl,
)


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def reviewed(env, fixture="in10_valid_mix", data=None):
    data = data or renamed_in10()
    r = env.parse(data)
    out = env.propose(r, fixture)
    s, ctx = env.session(r, out)
    open_review(s, ANALYST, env.policy, env.log)
    return r, out, s, ctx


def approve_all(env, s, ctx):
    for c in s.columns:
        decide_column(s, c.source_index, "APPROVE", ANALYST, "test basis", env.policy, env.log, ctx)
    return approve_proposal(s, ANALYST, "test approval", env.policy, env.log, ctx)


# ============================================================================================ authority
def test_production_policy_authorises_nobody():
    prod = AuthorityPolicy.load()
    assert prod.status == "PRODUCTION_UNCONFIGURED" and prod.scopes == {} and not prod.allow_test_identities
    for scope in ("FILE_MAPPING", "ALIAS", "LAYOUT", "CATEGORY_CONFIRMATION", "CATEGORY_CONFLICT", "REVOCATION"):
        for who in (ANALYST, Reviewer(reviewer_id="x", role="data_owner", kind="BUSINESS")):
            with pytest.raises(AuthorityError, match="open owner decision"):
                prod.authorise(scope, [who])


def test_test_policy_roles_kinds_and_two_approvers(env):
    p = env.policy
    assert p.authorise("FILE_MAPPING", [ANALYST]) == "TEST"
    with pytest.raises(AuthorityError, match="not authorised"):
        p.authorise("ALIAS", [ANALYST])
    with pytest.raises(AuthorityError, match="business approvals need an OWNER_APPROVED policy"):
        p.authorise("FILE_MAPPING", [Reviewer(reviewer_id="b", role="analyst", kind="BUSINESS")])
    with pytest.raises(AuthorityError, match="2 distinct approver"):
        p.authorise("LAYOUT", [OWNER])
    with pytest.raises(AuthorityError, match="system_owner"):
        p.authorise("LAYOUT", [OWNER, Reviewer(reviewer_id="o2", role="data_owner", kind="TEST")])
    assert p.authorise("LAYOUT", [OWNER, SYSOWNER]) == "TEST"
    strict = p.model_copy(update={"allow_test_identities": False})
    with pytest.raises(AuthorityError, match="test identity"):
        strict.authorise("FILE_MAPPING", [ANALYST])


def test_unconfigured_policy_cannot_enable_roles(tmp_path):
    bad = json.loads((RULES_DIR.parent.parent / "review" / "authority_policy.json").read_text())
    bad["scopes"] = {"FILE_MAPPING": {"roles": ["analyst"]}}
    (tmp_path / "p.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="may not enable roles"):
        AuthorityPolicy.load(tmp_path / "p.json")


# ============================================================================================ state machine
def test_full_lifecycle_and_audit(env):
    r, out, s, ctx = reviewed(env)
    assert s.state == "UNDER_REVIEW"
    summary = approve_all(env, s, ctx)
    assert s.state == "APPROVED" and summary == {"complete": True, "missing_required_fields": [], "unmapped_columns": []}
    assert [t.to_state for t in s.history][:2] == ["UNDER_REVIEW", "PARTIALLY_DECIDED"]
    assert env.log.verify() == 6 and env.log.events()[-1].event_type == "PROPOSAL_APPROVED"
    d = next(iter(s.decisions.values()))
    assert d.reviewer_id == "test-analyst-1" and d.approval_kind == "TEST" and d.basis


def test_invalid_transitions(env):
    r = env.parse(renamed_in10())
    out = env.propose(r, "in10_valid_mix")
    s, ctx = env.session(r, out)
    with pytest.raises(ReviewError, match="only possible under review"):
        decide_column(s, 0, "APPROVE", ANALYST, "b", env.policy, env.log, ctx)
    with pytest.raises(ReviewError, match="invalid transition PROPOSED -> APPROVED"):
        approve_proposal(s, ANALYST, "b", env.policy, env.log, ctx)
    open_review(s, ANALYST, env.policy, env.log)
    with pytest.raises(ReviewError, match="invalid transition"):
        open_review(s, ANALYST, env.policy, env.log)
    with pytest.raises(ReviewError, match="needs a reason"):
        reject_proposal(s, ANALYST, " ", env.policy, env.log)
    reject_proposal(s, ANALYST, "wrong export", env.policy, env.log)
    assert s.state == "REJECTED" and s.rejection_reason == "wrong export"
    for fn in (lambda: open_review(s, ANALYST, env.policy, env.log),
               lambda: decide_column(s, 0, "APPROVE", ANALYST, "b", env.policy, env.log, ctx)):
        with pytest.raises(ReviewError):
            fn()


def test_unauthorised_reviewer_cannot_open_or_decide(env):
    r = env.parse(renamed_in10())
    out = env.propose(r, "in10_valid_mix")
    s, _ = env.session(r, out)
    with pytest.raises(AuthorityError):
        open_review(s, OWNER, env.policy, env.log)                       # data_owner has no FILE_MAPPING role
    with pytest.raises(AuthorityError):
        open_review(s, ANALYST, AuthorityPolicy.load(), env.log)          # production policy: nobody


def test_partial_decisions_are_saved_and_never_applied(env, tmp_path):
    r, out, s, ctx = reviewed(env)
    decide_column(s, s.columns[0].source_index, "APPROVE", ANALYST, "b", env.policy, env.log, ctx)
    s.save(tmp_path / "s.json")
    again = ReviewSession.load(tmp_path / "s.json")
    assert again.state == "PARTIALLY_DECIDED" and len(again.decisions) == 1
    with pytest.raises(ReviewError, match="columns without a decision"):
        approve_proposal(again, ANALYST, "b", env.policy, env.log, ctx)
    # the file is still unresolved: nothing was applied
    assert env.parse(renamed_in10()).metadata.classification_status == "unknown"
    assert env.rules().file_mappings == [] and env.rules().aliases == []


def test_change_must_stay_in_category_and_pass_validation(env):
    r, out, s, ctx = reviewed(env)
    idx = {c.source_header: c.source_index for c in s.columns}
    with pytest.raises(ReviewError, match="not a field of the confirmed category IN-10"):
        decide_column(s, idx["entry_ref"], "CHANGE", ANALYST, "b", env.policy, env.log, ctx, final_field="bank_entry_id")
    with pytest.raises(ReviewError, match="FIELD_ALREADY_RESOLVED"):
        decide_column(s, idx["entry_ref"], "CHANGE", ANALYST, "b", env.policy, env.log, ctx, final_field="entry_type")
    with pytest.raises(ReviewError, match="VALUE_INCOMPATIBLE"):
        decide_column(s, idx["acct_no"], "CHANGE", ANALYST, "b", env.policy, env.log, ctx, final_field="posted_ts")
    decide_column(s, idx["entry_ref"], "APPROVE", ANALYST, "b", env.policy, env.log, ctx)
    with pytest.raises(ReviewError, match="DUPLICATE_TARGET"):
        decide_column(s, idx["acct_no"], "CHANGE", ANALYST, "b", env.policy, env.log, ctx, final_field="ledger_entry_id")
    d = decide_column(s, idx["acct_no"], "APPROVE", ANALYST, "b", env.policy, env.log, ctx)
    assert d.final_field == "account_id"


@pytest.mark.parametrize("field,assessment", [("UNMAPPABLE", "UNMAPPABLE"), ("amount", "UNMAPPABLE")])
def test_unmappable_column_never_silently_approved(env, field, assessment):
    """Phase 3B-1 correction preserved: explicit UNMAPPABLE (either form) is NO_MATCH/unmappable and cannot be APPROVED
    as proposed; leaving it unmapped keeps the approval incomplete."""
    from .test_proposals import _variant
    from smartparser.mapping.proposal_runner import run_proposal
    r = env.parse(renamed_in10())
    out = run_proposal(r, env.reg, _variant("in10_valid_mix", "txn_amt", canonical_field=field, assessment=assessment),
                       rules=env.rules())
    s, ctx = env.session(r, out)
    open_review(s, ANALYST, env.policy, env.log)
    col = next(c for c in s.columns if c.source_header == "txn_amt")
    assert (col.validation_class, col.status) == ("NO_MATCH", "unmappable")
    with pytest.raises(ReviewError, match="cannot be approved as proposed"):
        decide_column(s, col.source_index, "APPROVE", ANALYST, "b", env.policy, env.log, ctx)
    for c in s.columns:
        action = "LEAVE_UNMAPPED" if c.source_header == "txn_amt" else "APPROVE"
        decide_column(s, c.source_index, action, ANALYST, "b", env.policy, env.log, ctx)
    summary = approve_proposal(s, ANALYST, "b", env.policy, env.log, ctx)
    assert summary["complete"] is False and summary["unmapped_columns"] == ["txn_amt"]
    assert summary["missing_required_fields"] == ["amount"]


def test_missing_required_fields_recorded_on_approval(env):
    r, out, s, ctx = reviewed(env, "in10_short_example", short_example())
    summary = approve_all(env, s, ctx)
    assert summary["complete"] is False
    assert summary["missing_required_fields"] == ["currency", "dc_indicator", "entry_type", "payment_reference"]


def test_revision_creates_new_linked_identity(env):
    r, out, s, ctx = reviewed(env, "in10_ambiguous")
    with pytest.raises(ReviewError, match="needs a note"):
        request_revision(s, ANALYST, "", env.policy, env.log)
    request_revision(s, ANALYST, "entry_ref alternatives unclear", env.policy, env.log)
    new = env.propose(r, "in10_valid_mix", revision_of=out.record.proposal_id)
    link_revision(s, new.record, env.log)
    assert new.record.proposal_id != out.record.proposal_id and new.record.revision_of == out.record.proposal_id
    assert s.revision_proposal_id == new.record.proposal_id
    assert env.log.events()[-1].event_type == "REVISION_CREATED"


# ============================================================================================ scopes
def test_file_mapping_scope_is_one_upload_only_and_creates_nothing_else(env):
    r, out, s, ctx = reviewed(env)
    approve_all(env, s, ctx)
    aliases_before, layouts_before = env.store.read("aliases"), env.store.read("layouts")
    rule = approve_file_mapping(s, [ANALYST], "one-off", env.policy, env.store, env.log)
    assert rule.intake_id == r.metadata.evidence_id and rule.source_sha256 == r.metadata.sha256
    assert rule.proposal_id == out.record.proposal_id and len(rule.decision_ids) == len(s.decisions)
    assert env.store.read("aliases") == aliases_before and env.store.read("layouts") == layouts_before
    same = env.parse(renamed_in10(), identity=(r.metadata.evidence_id, r.metadata.sha256))
    assert same.metadata.mapping_status == "complete"
    second_upload = env.parse(renamed_in10())                              # a new intake, same bytes
    other = env.parse(renamed_in10(), identity=(second_upload.metadata.evidence_id, second_upload.metadata.sha256))
    assert other.metadata.classification_status == "unknown"


def test_file_mapping_needs_approved_review_and_authority(env):
    r, out, s, ctx = reviewed(env)
    with pytest.raises(ReviewError, match="needs an APPROVED review"):
        approve_file_mapping(s, [ANALYST], "b", env.policy, env.store, env.log)
    approve_all(env, s, ctx)
    with pytest.raises(AuthorityError):
        approve_file_mapping(s, [OWNER], "b", env.policy, env.store, env.log)


def test_alias_scope_separate_authority_and_reuse(env):
    rows = tbl("IN-10")
    data = dump([["Ledger Ref"] + rows[0][1:]] + rows[1:])
    assert env.parse(data, forced=None).metadata.classification_status == "unknown"
    with pytest.raises(AuthorityError):
        approve_alias("IN-10", "Ledger Ref", "ledger_entry_id", [ANALYST], "b", env.policy, env.store, env.log,
                      "test", "r", "low")
    alias = approve_alias("IN-10", "Ledger Ref", "ledger_entry_id", [OWNER], "seen in export X", env.policy, env.store,
                          env.log, "test-fixture", "spaced name", "low")
    res = env.parse(data, forced=None)
    assert (res.metadata.evidence_category, res.classification.method) == ("IN-10", "csv_controlled_mapping")
    m = res.mapping.mappings[0]
    assert (m.method.value, m.rule_id, m.rule_version) == ("alias", alias["alias_id"], 1)


def test_alias_refuses_sign_sensitive_and_collisions(env):
    with pytest.raises(ReviewError, match="sign or debit/credit perspective"):
        approve_alias("IN-10", "Txn Amt", "amount", [OWNER], "b", env.policy, env.store, env.log, "t", "r", "x")
    before = env.store.read("aliases")
    with pytest.raises(RuleStoreError, match="ambiguous alias"):
        approve_alias("IN-10", "ACCOUNT_ID", "ledger_entry_id", [OWNER], "b", env.policy, env.store, env.log, "t", "r", "x")
    assert env.store.read("aliases") == before                            # rolled back


def _layout_columns(headers, fields):
    return [ColumnRule(source_index=i, source_header=h, canonical_field=f) for i, (h, f) in enumerate(zip(headers, fields))]


def test_layout_scope_exact_header_list_two_approvers_and_acknowledgement(env):
    rows = tbl("IN-10")
    fields = rows[0]
    headers = ["entry_ref", "acct_no", "posting_dt", "entry_type", "txn_amt", "dc_indicator", "currency",
               "payment_reference"]
    cols = _layout_columns(headers, fields)
    with pytest.raises(AuthorityError):
        approve_layout(cols, "IN-10", "BankX export", "3", [OWNER], "b", env.policy, env.store, env.log)
    with pytest.raises(ReviewError, match="explicit acknowledgement"):
        approve_layout(cols, "IN-10", "BankX export", "3", [OWNER, SYSOWNER], "b", env.policy, env.store, env.log)
    with pytest.raises(ReviewError, match="every required field"):
        approve_layout(cols[:-1], "IN-10", "BankX export", "3", [OWNER, SYSOWNER], "b", env.policy, env.store, env.log,
                       acknowledge_sign_sensitive=True)
    lay = approve_layout(cols, "IN-10", "BankX export", "3", [OWNER, SYSOWNER], "system docs v3", env.policy, env.store,
                         env.log, acknowledge_sign_sensitive=True)
    assert lay.sign_sensitive_acknowledged == ["amount", "dc_indicator"] and lay.approval_kind == "TEST"
    data = dump([headers] + rows[1:])
    res = env.parse(data, forced=None)                                     # automatic classification via the layout
    assert res.metadata.evidence_category == "IN-10" and res.metadata.mapping_status == "complete"
    assert {m.rule_id for m in res.mapping.mappings if m.method.value == "approved_layout"} == {lay.layout_id}
    upper = dump([[h.upper() for h in headers]] + rows[1:])                # not the exact list -> no match
    assert env.parse(upper, forced=None).metadata.classification_status == "unknown"


def test_layout_requires_declared_source_system(env):
    rows = tbl("IN-10")
    cols = _layout_columns(rows[0], rows[0])
    with pytest.raises(Exception, match="source_system"):
        approve_layout(cols, "IN-10", "", "1", [OWNER, SYSOWNER], "b", env.policy, env.store, env.log,
                       acknowledge_sign_sensitive=True)


def test_revocation_and_supersession_keep_history(env):
    rows = tbl("IN-10")
    headers = ["entry_ref", "acct_no", "posting_dt", "entry_type", "txn_amt", "dc_indicator", "currency",
               "payment_reference"]
    data = dump([headers] + rows[1:])
    lay = approve_layout(_layout_columns(headers, rows[0]), "IN-10", "BankX", "3", [OWNER, SYSOWNER], "b",
                         env.policy, env.store, env.log, acknowledge_sign_sensitive=True)
    first = env.parse(data, forced=None)
    v2 = approve_layout(_layout_columns(headers, rows[0]), "IN-10", "BankX", "3.1", [OWNER, SYSOWNER], "b2",
                        env.policy, env.store, env.log, acknowledge_sign_sensitive=True, supersedes=lay.layout_id)
    assert (v2.layout_id, v2.rule_version) == (lay.layout_id, 2)
    versions = {x["rule_version"]: x["lifecycle"]["status"] for x in env.store.find("layouts", lay.layout_id)}
    assert versions == {1: "superseded", 2: "active"}
    assert {m.rule_version for m in env.parse(data, forced=None).mapping.mappings if m.rule_id} == {2}
    with pytest.raises(AuthorityError):
        revoke_rule("layouts", lay.layout_id, 2, ANALYST, "x", env.policy, env.store, env.log)
    with pytest.raises(ReviewError, match="needs a reason"):
        revoke_rule("layouts", lay.layout_id, 2, OWNER, "", env.policy, env.store, env.log)
    revoke_rule("layouts", lay.layout_id, 2, OWNER, "system retired", env.policy, env.store, env.log)
    assert env.parse(data, forced=None).metadata.classification_status == "unknown"   # stops matching
    hist = env.store.find("layouts", lay.layout_id)
    assert len(hist) == 2 and hist[1]["lifecycle"]["revocation_reason"] == "system retired"   # nothing deleted
    assert {m.rule_id for m in first.mapping.mappings if m.rule_id} == {lay.layout_id}         # old result intact
    with pytest.raises(RuleStoreError, match="only an active rule"):
        revoke_rule("layouts", lay.layout_id, 2, OWNER, "again", env.policy, env.store, env.log)


def test_category_confirmation_and_conflict_need_separate_authority(env):
    c = confirm_category("i1", "a" * 64, "IN-10", ANALYST, "export is a cash book", env.policy, env.log, env.reg)
    assert c.approval_kind == "TEST" and c.conflicting_content_category is None
    with pytest.raises(AuthorityError):
        confirm_category("i1", "a" * 64, "IN-10", ANALYST, "b", env.policy, env.log, env.reg, content_category="IN-09")
    c2 = confirm_category("i1", "a" * 64, "IN-10", OWNER, "b", env.policy, env.log, env.reg, content_category="IN-09")
    assert c2.conflicting_content_category == "IN-09"


# ============================================================================================ governed files
def test_production_rules_are_never_written(env, tmp_path):
    with pytest.raises(RuleStoreError, match="never written at runtime"):
        RuleStore(RULES_DIR, env.reg)
    with pytest.raises(RuleStoreError, match="never written at runtime"):
        RuleStore.initialise(RULES_DIR, env.reg)
    prod = load_rules(env.reg)
    assert prod.aliases == [] and prod.layouts == [] and prod.file_mappings == []
    cat = json.loads((RULES_DIR / "alias_proposals.json").read_text())
    assert len(cat["proposals"]) == 19 and all(p["status"] == "proposed" for p in cat["proposals"])


def test_rule_files_are_strict_and_registry_bound(env):
    r, out, s, ctx = reviewed(env)
    approve_all(env, s, ctx)
    approve_file_mapping(s, [ANALYST], "b", env.policy, env.store, env.log)
    doc = env.store.read("file_mappings")
    doc["file_mappings"][0]["registry_definition_sha256"] = "0" * 64
    env.store.path("file_mappings").write_text(json.dumps(doc))
    with pytest.raises(MappingRulesError, match="different IN-10 registry definition"):
        env.store.load()
    doc["file_mappings"][0]["registry_definition_sha256"] = "x"
    doc["file_mappings"][0]["unexpected"] = 1
    env.store.path("file_mappings").write_text(json.dumps(doc))
    with pytest.raises(MappingRulesError, match="invalid file_mapping record"):
        env.store.load()


# ============================================================================================ audit
def test_audit_is_append_only_and_tamper_evident(env):
    r, out, s, ctx = reviewed(env)
    approve_all(env, s, ctx)
    n = env.log.verify()
    lines = env.log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n
    with pytest.raises(Exception):
        env.log.append("NOT_AN_EVENT")                                     # malformed record refused
    assert len(env.log.path.read_text(encoding="utf-8").splitlines()) == n
    tampered = lines[:]
    tampered[1] = tampered[1].replace('"APPROVE"', '"REJECT"')
    env.log.path.write_text("\n".join(tampered) + "\n", encoding="utf-8")
    with pytest.raises(AuditError):
        env.log.verify()
    env.log.path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")   # deleted first event
    with pytest.raises(AuditError):
        env.log.verify()
