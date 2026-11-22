"""Phase 3B-8: end-to-end workflow verification (offline; recorded stubs only; sockets blocked; synthetic UC-042 data).

Each scenario runs the REAL integrated path - orchestrator -> gate / pipeline / gateway / policy -> review (column-review
case or proposal session) -> governed rule -> deterministic reprocessing -> 14-point handoff check -> preview - and
verifies: final decision, review state, provider calls, rule side effects, audit events (and chain), handoff eligibility,
preview creation or refusal, provenance and original-file integrity. Every store lives in a pytest tmp directory.
"""
import csv
import hashlib
import io
import json
import socket
from pathlib import Path

import pytest

from smartparser.ai.config import AIConfig
from smartparser.ai.gateway import ProposalGateway
from smartparser.ai.proposer import RecordedResponseStub
from smartparser.handoff.eligibility import check_handoff
from smartparser.handoff.reprocess import reprocess
from smartparser.handoff.writer import write_preview
from smartparser.intake.store import EvidenceStore
from smartparser.mapping.controlled import RULES_DIR
from smartparser.mapping.rule_store import RuleStore, RuleStoreError
from smartparser.orchestration.orchestrator import MappingOrchestrator
from smartparser.orchestration.policy import Decision, PocAutoAcceptPolicy
from smartparser.review.approvals import approve_file_mapping, confirm_category, revoke_rule
from smartparser.review.audit import AuditLog
from smartparser.review.intake import CaseState, ColumnReviewCase, decide, reject_case
from smartparser.review.session import ReviewError, approve_proposal, decide_column, open_review

from .phase3b_support import ANALYST, OWNER, SEP, Env, dump, make_env, read, short_example, tbl
from .test_header_gate_3b7 import dup_amount, insert, plus_note, resolve
from .test_proposals import RENAME, renamed_in10

FX = Path(__file__).parent / "fixtures" / "recorded_llm"
POLICY_ON = Path(__file__).parent / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
STUB_ON = AIConfig(enabled=True, provider="recorded_stub")
CANON10 = read(SEP, "IN-10")
IN10 = tbl("IN-10")[0]
AUTO10 = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    return make_env(tmp_path)


def fx(name):
    return RecordedResponseStub([json.loads((FX / f"{name}.json").read_text(encoding="utf-8"))])


def orch(env, stub=None, config=STUB_ON):
    stub = stub if stub is not None else RecordedResponseStub([])
    gw = ProposalGateway(proposer=stub, config=config, log=env.log)
    return MappingOrchestrator(env.reg, env.store, env.evidence, gw, PocAutoAcceptPolicy.load(POLICY_ON), env.log,
                               preview_dir=env.root / "pv"), stub


def rename(fid, m):
    rows = tbl(fid)
    return dump([[m.get(c, c) for c in rows[0]]] + rows[1:])


def types(env, intake_id=None):
    env.log.verify()                                                   # the hash chain holds in every scenario
    return [e.event_type for e in env.log.events() if intake_id is None or e.intake_id == intake_id]


def fms(env):
    return env.store.read("file_mappings")["file_mappings"]


def assert_original_intact(env, intake_id, data):
    rec = env.evidence.find(intake_id)
    assert rec is not None and rec.sha256 == hashlib.sha256(data).hexdigest()
    assert env.evidence.read_original(rec.sha256) == data


def assert_no_reusable_rules(env):
    assert env.store.read("aliases")["aliases"] == [] and env.store.read("layouts")["layouts"] == []


def assert_preview_provenance(wr, data, expected_csv=CANON10):
    """Preview = expected canonical bytes; every output column traced to a source position whose cells it carries."""
    assert wr.eligibility.eligible and wr.preview is not None
    out = wr.preview["csv"].read_bytes()
    assert out == expected_csv and hashlib.sha256(out).hexdigest() == wr.preview["output_sha256"]
    side = wr.preview["sidecar_doc"]
    assert side["source"]["sha256"] == hashlib.sha256(data).hexdigest() and side["submission_authorised"] is False
    src = list(csv.reader(io.StringIO(data.decode())))
    got = list(csv.reader(io.StringIO(out.decode())))
    for c in side["columns"]:
        assert src[0][c["source_index"]] == c["original_header"]
        assert [r[c["canonical_position"]] for r in got[1:]] == [r[c["source_index"]] for r in src[1:]]
    return side


def assert_no_preview(wr):
    assert wr.preview is None


def assert_outcome_audited(env, wr):
    t = types(env, wr.intake_id)
    assert "REPROCESSED" in t and "HANDOFF_EVALUATED" in t
    ev = [e for e in env.log.events() if e.event_type == "HANDOFF_EVALUATED" and e.intake_id == wr.intake_id][-1]
    assert ev.details["eligible"] == wr.eligibility.eligible
    if wr.preview:
        pw = [e for e in env.log.events() if e.event_type == "HANDOFF_PREVIEW_WRITTEN" and e.intake_id == wr.intake_id]
        assert pw and pw[-1].details["output_sha256"] == wr.preview["output_sha256"]


# ============================================================================================ 1-3 equal count
def test_01_equal_count_all_deterministic(env):
    o, s = orch(env, fx("in10_auto_clear"))
    wr = o.process(CANON10, "ledger.csv", "2026-09", category="IN-10")
    assert (wr.decision, wr.route, wr.intake_case, wr.review_session) == (Decision.DETERMINISTIC, "DETERMINISTIC",
                                                                          None, None)
    assert s.calls == [] and wr.reprocessed.provider_calls == 0 and fms(env) == []
    assert_preview_provenance(wr, CANON10)
    assert_outcome_audited(env, wr)
    assert_original_intact(env, wr.intake_id, CANON10)


def test_02_equal_count_unfamiliar_headers_valid_recorded_proposals(env):
    data = rename("IN-10", AUTO10)
    o, s = orch(env, fx("in10_auto_clear"))
    wr = o.process(data, "ledger.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.AUTO_ACCEPT and wr.route == "PROPOSAL" and len(s.calls) == 1
    assert [u.source_header for u in s.calls[0].unresolved_columns] == list(AUTO10.values())
    assert wr.reprocessed.provider_calls == 0 and len(fms(env)) == 1
    assert fms(env)[0]["approvals"][0]["approval_kind"] == "POC_AUTO"
    side = assert_preview_provenance(wr, data)
    assert side["workflow_decision"]["approval_kind"] == "POC_AUTO"
    t = types(env, wr.intake_id)
    assert t.index("POC_AUTO_DECISION") < t.index("RULE_CREATED") < t.index("REPROCESSED")
    assert_outcome_audited(env, wr)
    assert_no_reusable_rules(env)
    assert_original_intact(env, wr.intake_id, data)


def test_03_equal_count_ambiguous_proposals_completed_through_the_session(env):
    """HUMAN_REVIEW (proposal session) -> reviewer decisions -> APPROVED -> file mapping + category confirmation ->
    reprocess -> preview. NOTE: there is no orchestrator entry point for this path (unlike complete_case); the service
    functions are called directly (§9 of the report)."""
    data = renamed_in10()
    o, s = orch(env, fx("in10_ambiguous"))
    wr = o.process(data, "ledger.csv", "2026-09", category="IN-10")
    sess = wr.review_session
    assert wr.decision == Decision.HUMAN_REVIEW and sess.state == "PROPOSED" and wr.intake_case is None
    assert len(s.calls) == 1 and fms(env) == [] and wr.preview is None
    from smartparser.review.session import ReviewContext
    ctx = ReviewContext(wr.proposal.request, env.reg.get("IN-10"), list(wr.initial.csv_extraction.raw_headers),
                        {c.index: list(c.sample_values) for c in wr.initial.csv_extraction.columns})
    truth = {v: k for k, v in RENAME.items()}
    open_review(sess, ANALYST, env.policy, env.log)
    for c in sess.columns:
        decide_column(sess, c.source_index, "CHANGE", ANALYST, "verified against the export spec", env.policy, env.log,
                      ctx, final_field=truth[c.source_header])
    approve_proposal(sess, ANALYST, "all columns verified", env.policy, env.log, ctx)
    assert sess.state == "APPROVED" and sess.final_summary["complete"] is True
    fm = approve_file_mapping(sess, [ANALYST], "file-specific", env.policy, env.store, env.log)
    conf = confirm_category(wr.intake_id, wr.source_sha256, "IN-10", ANALYST, "ledger extract", env.policy, env.log,
                            env.reg)
    rr = reprocess(wr.intake_id, env.evidence, env.reg, env.store.load(), conf)
    el = check_handoff(rr, env.reg)
    assert el.eligible and rr.provider_calls == 0 and len(s.calls) == 1
    pv = write_preview(rr, el, env.reg, env.root / "pv_sess")
    assert pv["csv"].read_bytes() == CANON10 and {r["rule_id"] for r in pv["sidecar_doc"]["rules_used"]} == {
        fm.file_mapping_id}
    assert {"PROPOSAL_REVIEW_OPENED", "COLUMN_DECIDED", "PROPOSAL_APPROVED", "RULE_CREATED", "CATEGORY_CONFIRMED"} <= \
        set(types(env, wr.intake_id))
    assert_original_intact(env, wr.intake_id, data)


def test_04_equal_count_duplicate_canonical_claims_cannot_bypass_review(env):
    """payment_reference replaced by CURRENCY (a copy of currency): two columns claim `currency`. HUMAN_REVIEW + a
    DETERMINISTIC_CONFLICT case. Choosing the source leaves payment_reference without any column and the duplicate cannot
    be remapped (RULE_CONTRADICTION) -> HELD. Structural finding: such a case can never yield a preview."""
    rows = tbl("IN-10")
    cur = rows[0].index("currency")
    data = dump([rows[0][:-1] + ["CURRENCY"]] + [r[:-1] + [r[cur]] for r in rows[1:]])
    o, s = orch(env, fx("in10_auto_clear"))
    wr = o.process(data, "ledger.csv", "2026-09", category="IN-10")
    case = wr.intake_case
    assert wr.decision == Decision.HUMAN_REVIEW and case.kind == "DETERMINISTIC_CONFLICT" and s.calls == []
    assert case.potential_duplicate_claims == {"currency": [6, 7]} and fms(env) == []
    ctx = o.case_context(case)
    with pytest.raises(ReviewError, match="RULE_CONTRADICTION"):
        decide(case, "CHANGE", ANALYST, "b", env.policy, env.log, ctx, 7, "payment_reference")
    decide(case, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "first is the booked currency", env.policy, env.log, ctx, 6,
           others_reason="export duplicate")
    resolve(o, env, case)
    done = o.complete_case(case, [ANALYST], "review", env.policy)
    assert case.state == CaseState.HELD and done.decision == Decision.REJECT_OR_HOLD
    assert case.final_summary["missing_required_fields"] == ["payment_reference"]
    assert_no_preview(done)
    assert fms(env) == [] and "INTAKE_CASE_HELD" in types(env, wr.intake_id)
    assert_original_intact(env, wr.intake_id, data)


# ============================================================================================ 5-13 different count / decisions
def test_05_extra_column_direct_hitl_then_resolved(env):
    data = plus_note()
    o, s = orch(env, fx("in10_auto_clear"))
    wr = o.process(data, "ledger.csv", "2026-09", category="IN-10")
    assert (wr.decision, wr.route) == (Decision.HUMAN_REVIEW, "HEADER_COUNT_GATE") and s.calls == []
    assert wr.initial is None and wr.proposal is None and fms(env) == []
    assert types(env, wr.intake_id) == ["INTAKE_CASE_OPENED"]                      # nothing else ran
    resolve(o, env, wr.intake_case, ignore={8: "free-text memo"})
    done = o.complete_case(wr.intake_case, [ANALYST], "review", env.policy)
    assert wr.intake_case.state == CaseState.RESOLVED and len(fms(env)) == 1 and s.calls == []
    assert_preview_provenance(done, data)
    assert_outcome_audited(env, done)
    assert_no_reusable_rules(env)
    assert_original_intact(env, wr.intake_id, data)


def test_06_fewer_columns_hold(env):
    data = short_example()
    o, s = orch(env, fx("in10_short_example"))
    wr = o.process(data, "short.csv", "2026-09", category="IN-10")
    c = wr.intake_case
    assert wr.route == "HEADER_COUNT_GATE" and s.calls == [] and c.count_difference == -4
    resolve(o, env, c, change={0: "ledger_entry_id", 1: "posted_ts", 2: "account_id", 3: "amount"})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    assert c.state == CaseState.HELD and done.decision == Decision.REJECT_OR_HOLD and fms(env) == []
    assert_no_preview(done)
    assert "REPROCESSED" not in types(env, wr.intake_id)
    assert_original_intact(env, wr.intake_id, data)


def test_07_missing_and_extra_columns(env):
    rows = tbl("IN-10")
    keep = [i for i, h in enumerate(rows[0]) if h not in ("currency", "payment_reference")]
    data = dump([[rows[0][i] for i in keep] + ["note"]] + [[r[i] for i in keep] + ["memo"] for r in rows[1:]])
    o, s = orch(env)
    c = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    assert (c.incoming_header_count, c.count_difference) == (7, -1)
    assert c.missing_fields_diagnostic == ["currency", "payment_reference"]
    assert c.extra_headers_diagnostic == [{"source_index": 6, "source_header": "note"}]
    resolve(o, env, c, ignore={6: "memo"})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    assert c.state == CaseState.HELD and c.final_summary["missing_required_fields"] == ["currency", "payment_reference"]
    assert_no_preview(done)
    assert fms(env) == [] and s.calls == []


def test_08_09_duplicate_identical_names_resolved_by_choosing_a_position(env):
    data = dup_amount()
    o, s = orch(env)
    wr = o.process(data, "u.csv", "2026-09", category="IN-10")
    c = wr.intake_case
    assert c.duplicate_incoming_headers == {"amount": [4, 8]} and c.potential_duplicate_claims == {"amount": [4, 8]}
    ctx = o.case_context(c)
    out = decide(c, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "position 5 is the ledger amount", env.policy, env.log, ctx, 4,
                 others_reason="duplicated by the export")
    assert [d.action for d in out] == ["CHOOSE_DUPLICATE_SOURCE", "IGNORE_COLUMN"]
    resolve(o, env, c)
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    side = assert_preview_provenance(done, data)
    assert next(x for x in side["columns"] if x["canonical_field"] == "amount")["source_index"] == 4
    assert [x["source_index"] for x in side["ignored_columns"]] == [8]
    rec = done.reprocessed.result.records[0]
    assert {"amount", "amount [col 9]"} <= set(rec.original)                       # both source cells kept
    dec = [e for e in env.log.events() if e.event_type == "INTAKE_DECISION"]
    assert dec[0].details["group_id"] == dec[1].details["group_id"] and dec[1].details["action"] == "IGNORE_COLUMN"
    assert_original_intact(env, wr.intake_id, data)


def test_10_extra_column_ignored_stays_in_provenance_and_records(env):
    data = plus_note(pos=2)
    o, _ = orch(env)
    c = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, c, ignore={2: "operator memo"})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    side = assert_preview_provenance(done, data)
    assert side["ignored_columns"][0] | {"note": None} == {"source_index": 2, "original_header": "note",
                                                           "reason": "operator memo", "rule_id": done.file_mapping.file_mapping_id,
                                                           "rule_version": 1, "note": None}
    assert all(r.original["note"] in ("free text A", "free text B") for r in done.reprocessed.result.records)
    fm = fms(env)[0]
    assert fm["columns"][2]["disposition"] == "IGNORE" and fm["columns"][2]["ignore_reason"] == "operator memo"


def test_11_required_field_still_missing_after_review(env):
    o, _ = orch(env)
    c = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, c, ignore={8: "memo", 4: "believed to be a copy"})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    assert c.state == CaseState.HELD and c.final_summary["missing_required_fields"] == ["amount"]
    assert_no_preview(done)
    assert fms(env) == [] and "CATEGORY_CONFIRMED" not in types(env)


def test_12_reviewer_leaves_unresolved(env):
    o, _ = orch(env)
    c = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, c, leave={8})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    assert c.state == CaseState.HELD and c.final_summary["unresolved_positions"] == [8]
    assert_no_preview(done)
    assert fms(env) == []


def test_13_reviewer_rejects(env):
    data = plus_note()
    o, _ = orch(env)
    wr = o.process(data, "u.csv", "2026-09", category="IN-10")
    reject_case(wr.intake_case, ANALYST, "wrong export, resubmit", env.policy, env.log)
    assert wr.intake_case.state == CaseState.REJECTED and fms(env) == []
    assert types(env, wr.intake_id) == ["INTAKE_CASE_OPENED", "INTAKE_CASE_REJECTED"]
    assert_original_intact(env, wr.intake_id, data)


# ============================================================================================ 14-20 integrity / operations
def test_14_category_mismatch(env):
    o, s = orch(env, fx("in10_auto_clear"))
    wr = o.process(read(SEP, "IN-09"), "u.csv", "2026-09", category="IN-10")                 # 13 vs 8
    assert wr.route == "HEADER_COUNT_GATE" and wr.category is None and s.calls == []
    assert wr.intake_case.content_classification["category"] == "IN-09" and wr.intake_case.category == "IN-10"
    wr2 = o.process(read(SEP, "IN-08"), "u.csv", "2026-09", category="IN-06")                # 11 = 11
    assert wr2.decision == Decision.REJECT_OR_HOLD and wr2.route == "PROPOSAL" and s.calls == []
    assert fms(env) == []


def test_15_original_modified_after_review_is_refused_before_anything_is_written(env):
    o, _ = orch(env)
    c = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = resolve(o, env, c, ignore={8: "memo"})
    p = env.evidence.root / "originals" / c.source_sha256[:2] / c.source_sha256
    p.write_bytes(p.read_bytes() + b"LE-X,SGA,2026-09-01T00:00:00+01:00,BANK_LOAD,1.00,D,GBP,X,y\n")
    with pytest.raises(ReviewError, match="SHA-256"):
        o.complete_case(c, [ANALYST], "review", env.policy, ctx)
    assert c.state == CaseState.UNDER_REVIEW and fms(env) == []
    assert not {"CATEGORY_CONFIRMED", "RULE_CREATED", "INTAKE_CASE_RESOLVED", "REPROCESSED"} & set(types(env))


def test_16_revoked_mapping_rule(env):
    data = plus_note()
    o, _ = orch(env)
    c = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, c, ignore={8: "memo"})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    revoke_rule("file_mappings", done.file_mapping.file_mapping_id, 1, OWNER, "decision withdrawn", env.policy,
                env.store, env.log)
    rr = reprocess(c.intake_id, env.evidence, env.reg, env.store.load(), done.confirmation)
    el = check_handoff(rr, env.reg)
    assert not el.eligible                                                                   # no preview possible
    assert fms(env)[0]["lifecycle"]["status"] == "revoked" and "RULE_REVOKED" in types(env)
    # documented gap (P1): the case object still says RESOLVED - its state is not linked to the rule lifecycle
    assert c.state == CaseState.RESOLVED


def test_17_reprocessing_repeated_twice_is_identical(env):
    data = plus_note()
    o, _ = orch(env)
    c = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, c, ignore={8: "memo"})
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    outs = []
    for k in range(2):
        rr = reprocess(c.intake_id, env.evidence, env.reg, env.store.load(), done.confirmation)
        pv = write_preview(rr, check_handoff(rr, env.reg), env.reg, env.root / f"r{k}", now="2026-11-18T00:00:00+00:00")
        outs.append((pv["csv"].read_bytes(), pv["sidecar"].read_bytes(), rr.provider_calls))
    assert outs[0] == outs[1] and outs[0][0] == done.preview["csv"].read_bytes() and outs[0][2] == 0
    assert_original_intact(env, c.intake_id, data)


def test_18_attempted_duplicate_finalisation(env):
    o, _ = orch(env)
    c = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, c, ignore={8: "memo"})
    stale_copy = ColumnReviewCase.model_validate_json(c.model_dump_json())      # e.g. a second browser tab / request
    done = o.complete_case(c, [ANALYST], "review", env.policy)
    with pytest.raises(ReviewError, match="only a case under review"):
        o.complete_case(c, [ANALYST], "review", env.policy)                      # same object: state guard
    with pytest.raises(RuleStoreError, match="two active file mappings"):
        o.complete_case(stale_copy, [ANALYST], "review", env.policy)             # copy: rule-store uniqueness guard
    assert len(fms(env)) == 1 and stale_copy.state == CaseState.UNDER_REVIEW
    rr = reprocess(c.intake_id, env.evidence, env.reg, env.store.load(), done.confirmation)
    assert check_handoff(rr, env.reg).eligible                                   # the first resolution is intact
    # documented gap (P1): the refused attempt leaves an orphan CATEGORY_CONFIRMED event; RESOLVED names the real one
    confs = [e for e in env.log.events() if e.event_type == "CATEGORY_CONFIRMED"]
    resolved = [e for e in env.log.events() if e.event_type == "INTAKE_CASE_RESOLVED"]
    assert len(confs) == 2 and len(resolved) == 1
    assert resolved[0].details["confirmation_id"] == done.confirmation.confirmation_id


def test_19_restart_during_an_unfinished_review(env):
    """Supported only through caller-side serialisation: there is no case store. The case JSON + the persistent rule
    store, evidence store and audit log are enough to resume in a new 'process' (fresh objects on the same folders)."""
    data = plus_note()
    o, _ = orch(env)
    wr = o.process(data, "u.csv", "2026-09", category="IN-10")
    decide(wr.intake_case, "IGNORE_COLUMN", ANALYST, "memo", env.policy, env.log, o.case_context(wr.intake_case), 8)
    saved = env.root / "case.json"
    saved.write_text(wr.intake_case.model_dump_json(), encoding="utf-8")
    del o, wr
    env2 = Env(env.root, env.reg, env.policy, AuditLog(env.root / "audit.jsonl"), RuleStore(env.root / "rules", env.reg),
               EvidenceStore(env.root / "evidence"))
    o2, _ = orch(env2)
    case = ColumnReviewCase.model_validate_json(saved.read_text(encoding="utf-8"))
    assert case.state == CaseState.UNDER_REVIEW and len(case.decisions) == 1
    resolve(o2, env2, case)
    done = o2.complete_case(case, [ANALYST], "review", env2.policy)
    assert_preview_provenance(done, data)
    assert env2.log.verify() == len(env2.log.events())
    assert [e.details["action"] for e in env2.log.events() if e.event_type == "INTAKE_DECISION"][0] == "IGNORE_COLUMN"


def test_19b_two_store_instances_never_lose_intake_records(env):
    """P0 regression (3B-8): two EvidenceStore objects on one folder used to drop each other's intake records."""
    a, b = EvidenceStore(env.root / "ev2"), EvidenceStore(env.root / "ev2")
    ra = a.save(b"x,y\n1,2\n", "a.csv", "2026-09")
    rb = b.save(b"x,y\n3,4\n", "b.csv", "2026-09")
    fresh = EvidenceStore(env.root / "ev2")
    assert fresh.find(ra.evidence_id) and fresh.find(rb.evidence_id) and b.find(ra.evidence_id) and a.find(rb.evidence_id)
    assert len(json.loads((env.root / "ev2" / "index.json").read_text())) == 2
    # and through two orchestrators sharing the stores: a case opened by one is completed by the other
    o1, _ = orch(env)
    c = o1.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    env2 = Env(env.root, env.reg, env.policy, env.log, env.store, EvidenceStore(env.root / "evidence"))
    o2, _ = orch(env2)
    o1.process(CANON10, "other.csv", "2026-09", category="IN-10")                    # o1 writes another intake
    resolve(o2, env2, c, ignore={8: "memo"})
    assert o2.complete_case(c, [ANALYST], "review", env2.policy).eligibility.eligible
    assert EvidenceStore(env.root / "evidence").find(c.intake_id) is not None


def test_20_provider_disabled(env):
    o, s = orch(env, fx("in10_auto_clear"), config=AIConfig())
    wr = o.process(rename("IN-10", AUTO10), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.REJECT_OR_HOLD and s.calls == [] and "AI mapping is disabled" in wr.reasons[0]
    assert wr.unresolved_headers == list(AUTO10.values()) and fms(env) == []
    wr2 = o.process(plus_note(), "u.csv", "2026-09", category="IN-10")
    assert wr2.decision == Decision.HUMAN_REVIEW and wr2.route == "HEADER_COUNT_GATE" and s.calls == []
    resolve(o, env, wr2.intake_case, ignore={8: "memo"})
    assert o.complete_case(wr2.intake_case, [ANALYST], "review", env.policy).eligibility.eligible
    assert s.calls == []


def test_protection_boundaries_after_all_scenarios():
    assert PocAutoAcceptPolicy.load().status == "DISABLED" and AIConfig.from_env({}).enabled is False
    from smartparser.review.authority import AuthorityPolicy
    assert AuthorityPolicy.load().scopes == {}
    rules = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in RULES_DIR.glob("*.json")}
    assert rules["approved_aliases.json"]["aliases"] == [] and rules["approved_layouts.json"]["layouts"] == []
