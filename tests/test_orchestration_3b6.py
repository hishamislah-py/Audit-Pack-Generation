"""Phase 3B-6: deterministic-first, LLM-assisted mapping orchestration with the POC decision policy (offline; recorded
stub only; sockets blocked)."""
import json
import socket
from pathlib import Path

import pytest

from smartparser.ai.config import AIConfig
from smartparser.ai.gateway import ProposalGateway, UsageLedger
from smartparser.ai.proposer import RecordedResponseStub
from smartparser.handoff.reprocess import reprocess
from smartparser.mapping.controlled import RULES_DIR, load_rules
from smartparser.orchestration.orchestrator import MappingOrchestrator
from smartparser.orchestration.policy import Decision, PocAutoAcceptPolicy, decide
from smartparser.review.approvals import approve_alias
from smartparser.review.authority import AuthorityPolicy

from .phase3b_support import OWNER, SEP, dump, make_env, read, renamed_in10, short_example, tbl
from .test_proposals import FX, _variant

POLICY_ON = Path(__file__).parent / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
STUB_ON = AIConfig(enabled=True, provider="recorded_stub")


def rename(fid, mapping):
    rows = tbl(fid)
    return dump([[mapping.get(c, c) for c in rows[0]]] + rows[1:])


AUTO10 = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt"}
AUTO02 = {"account_id": "acct_id", "institution_full_name": "bank_name"}


def stub(name):
    return RecordedResponseStub([json.loads((FX / f"{name}.json").read_text(encoding="utf-8"))])


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    return make_env(tmp_path)


def orch(env, proposer=None, config=STUB_ON, policy=POLICY_ON, ledger=None):
    gw = ProposalGateway(proposer=proposer or RecordedResponseStub([]), config=config, log=env.log,
                         ledger=ledger or UsageLedger())
    pol = PocAutoAcceptPolicy.load(policy) if policy else PocAutoAcceptPolicy.load()
    return MappingOrchestrator(env.reg, env.store, env.evidence, gw, pol, env.log, preview_dir=env.root / "preview")


# ============================================================================================ policy configuration
def test_shipped_policy_is_disabled_and_production_untouched():
    p = PocAutoAcceptPolicy.load()
    assert p.status == "DISABLED" and not p.enabled and not p.accept_supplied_category and not p.accept_plausible
    assert AuthorityPolicy.load().scopes == {}                                     # production authority unchanged
    prod = load_rules(__import__("smartparser.schemas", fromlist=["x"]).SchemaRegistry.from_directory())
    assert prod.aliases == [] and prod.layouts == [] and prod.file_mappings == []
    assert AIConfig.from_env({}).enabled is False


def test_disabled_policy_never_auto_accepts(env):
    s = stub("in10_auto_clear")
    wr = orch(env, s, policy=None).process(rename("IN-10", AUTO10), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and any("not enabled" in r for r in wr.reasons)
    assert wr.file_mapping is None and wr.review_session.state == "PROPOSED"


# ============================================================================================ A-D deterministic
@pytest.mark.parametrize("variant", ["canonical", "reordered", "case_ws"])
@pytest.mark.parametrize("fid", ["IN-02", "IN-09", "IN-10", "IN-13"])
def test_deterministic_files_never_call_the_llm(env, fid, variant):
    rows = tbl(fid)
    data = {"canonical": read(SEP, fid), "reordered": dump([list(reversed(r)) for r in rows]),
            "case_ws": dump([[f" {c.upper()} " for c in rows[0]]] + rows[1:])}[variant]
    s = stub("in10_auto_clear")
    wr = orch(env, s).process(data, "x.csv", "2026-09")
    assert s.calls == [] and wr.proposer_calls == 0                              # never an LLM call
    if variant == "case_ws":
        # owner decision O2 (19 Nov 2026): case/whitespace variants are never recognised automatically; the category is
        # still established deterministically and the file goes to a HEADER_VARIANT column review (no preview yet)
        assert (wr.decision, wr.route, wr.intake_case.kind) == (Decision.HUMAN_REVIEW, "HEADER_VARIANT", "HEADER_VARIANT")
        assert wr.preview is None and wr.eligibility is None
        assert [c.suggested_field for c in wr.intake_case.columns] == rows[0]
        return
    assert wr.decision == Decision.DETERMINISTIC
    assert wr.eligibility.eligible and wr.preview["csv"].read_bytes() == read(SEP, fid)


def test_existing_approved_alias_requires_review(env):
    """O2: an approved alternative name is still an alternative name - it is suggested from the governed alias, never
    applied automatically at intake; no new alias or rule is created."""
    approve_alias("IN-11", "Txn ID", "txn_id", [OWNER], "test", env.policy, env.store, env.log, "t", "r", "low")
    rows = tbl("IN-11")
    s = stub("in10_auto_clear")
    aliases_before = env.store.read("aliases")
    wr = orch(env, s).process(dump([["Txn ID"] + rows[0][1:]] + rows[1:]), "x.csv", "2026-09")
    assert (wr.decision, wr.route) == (Decision.HUMAN_REVIEW, "HEADER_VARIANT") and s.calls == []
    assert wr.intake_case.columns[0].suggested_field == "txn_id" and wr.preview is None
    assert env.store.read("aliases") == aliases_before


# ============================================================================================ E auto-accept + P reprocess
@pytest.mark.parametrize("fid,ren,fx", [("IN-10", AUTO10, "in10_auto_clear"), ("IN-02", AUTO02, "in02_auto_clear")])
def test_unfamiliar_clear_headers_are_auto_accepted_and_reprocessed(env, fid, ren, fx):
    s = stub(fx)
    wr = orch(env, s).process(rename(fid, ren), "upload.csv", "2026-09", category=fid)
    assert wr.decision == Decision.AUTO_ACCEPT and wr.proposer_calls == 1 and len(s.calls) == 1
    req = s.calls[0]
    assert [u.source_header for u in req.unresolved_columns] == list(ren.values())      # only unresolved headers
    assert [f.name for f in req.canonical_fields] == [f.name for f in env.reg.get(fid).fields]   # correct schema
    assert all(u.value_shapes == [] for u in req.unresolved_columns)                      # shapes not sent (default)
    fm = wr.file_mapping
    assert fm.intake_id == wr.intake_id and fm.approvals[0].approval_kind == "POC_AUTO"
    assert fm.approvals[0].approver_id.startswith("POC_AUTO_ACCEPT_POLICY")
    assert wr.confirmation.approval_kind == "POC_AUTO" and wr.category == fid
    assert wr.reprocessed.provider_calls == 0 and wr.eligibility.eligible
    assert wr.preview["csv"].read_bytes() == read(SEP, fid)                                  # cells preserved
    side = wr.preview["sidecar_doc"]
    assert side["workflow_decision"]["approval_kind"] == "POC_AUTO" and side["status"].startswith("PREVIEW_ONLY")
    assert {c["original_header"] for c in side["columns"]} >= set(ren.values())
    assert env.store.read("aliases")["aliases"] == [] and env.store.read("layouts")["layouts"] == []   # no reusable rule
    assert env.log.verify() > 0


def test_request_carries_no_values(env):
    s = stub("in10_auto_clear")
    data = rename("IN-10", AUTO10)
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    text = s.calls[0].model_dump_json()
    for col in wr.initial.csv_extraction.columns:
        if col.name in AUTO10.values():
            for v in col.sample_values:
                assert v not in text


def test_reprocessing_after_auto_accept_never_calls_again_and_is_repeatable(env, monkeypatch):
    s = stub("in10_auto_clear")
    o = orch(env, s)
    wr = o.process(rename("IN-10", AUTO10), "upload.csv", "2026-09", category="IN-10")
    import smartparser.mapping.proposal_runner as pr
    monkeypatch.setattr(pr, "run_proposal", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM path")))
    again = [reprocess(wr.intake_id, env.evidence, env.reg, env.store.load(), wr.confirmation) for _ in range(2)]
    assert len(s.calls) == 1
    assert again[0].result.mapping.model_dump() == again[1].result.mapping.model_dump() == \
        wr.reprocessed.result.mapping.model_dump()
    assert [x.values for x in again[0].result.records] == [x.values for x in wr.reprocessed.result.records]


def test_repeated_processing_of_the_same_file_gives_the_same_decision_and_output(env):
    data = rename("IN-10", AUTO10)
    outs = []
    for _ in range(2):
        s = stub("in10_auto_clear")
        wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
        outs.append((wr.decision, wr.preview["csv"].read_bytes(), wr.preview["output_sha256"]))
        assert len(s.calls) == 1        # a new upload is a new intake; its accepted proposal was not pending
    assert outs[0] == outs[1]


# ============================================================================================ F, G, I, J, O, Q review / hold
def test_ambiguous_headers_go_to_human_review(env):
    wr = orch(env, stub("in10_ambiguous")).process(renamed_in10(), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and wr.file_mapping is None and wr.preview is None
    assert wr.review_session.state == "PROPOSED" and any("ambiguous" in r for r in wr.reasons)


def test_sign_sensitive_field_is_never_auto_accepted_even_if_proposer_says_clear(env):
    wr = orch(env, stub("in10_amount_only")).process(rename("IN-10", {"amount": "txn_amt"}), "u.csv", "2026-09",
                                                     category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and "sign/perspective-sensitive" in wr.reasons[0]
    assert wr.proposal.record.columns[0].validation_class == "AMBIGUOUS"


def test_partial_success_plausible_column_goes_to_review(env):
    wr = orch(env, stub("in10_partial_plausible")).process(rename("IN-10", AUTO10), "u.csv", "2026-09",
                                                           category="IN-10")
    classes = {c.source_header: c.validation_class.value for c in wr.proposal.record.columns}
    assert classes == {"entry_ref": "CLEAR", "acct_no": "CLEAR", "posting_dt": "PLAUSIBLE"}
    assert wr.decision == Decision.HUMAN_REVIEW and "plausible but not verified" in wr.reasons[0]
    assert len(wr.proposal.request.resolved_columns) == 5                     # 5 of 8 columns resolved deterministically


@pytest.mark.parametrize("fixture,data_fn,expected_reason", [
    ("in10_duplicate_target", renamed_in10, "conflicting or invalid assignments"),
    ("in10_malformed", renamed_in10, "MALFORMED_RESPONSE"),
])
def test_blocking_cases_are_rejected_or_held(env, fixture, data_fn, expected_reason):
    wr = orch(env, stub(fixture)).process(data_fn(), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.REJECT_OR_HOLD and expected_reason in " ".join(wr.reasons)
    assert wr.file_mapping is None and wr.preview is None and wr.reprocessed is None


def test_short_example_goes_directly_to_human_review(env):
    """3B-6: REJECT_OR_HOLD after a proposal (required fields unresolved). 3B-7: 4 columns for the 8 IN-10 fields ->
    header-count gate -> direct HUMAN_REVIEW; no proposal, no LLM call, nothing applied."""
    s = stub("in10_short_example")
    wr = orch(env, s).process(short_example(), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and wr.route == "HEADER_COUNT_GATE" and s.calls == []
    c = wr.intake_case
    assert (c.incoming_header_count, c.expected_field_count, c.count_difference) == (4, 8, -4)
    assert c.missing_fields_diagnostic == tbl("IN-10")[0] and len(c.extra_headers_diagnostic) == 4
    assert wr.file_mapping is None and wr.preview is None and wr.reprocessed is None


@pytest.mark.parametrize("field,assessment", [("UNMAPPABLE", "UNMAPPABLE"), ("amount", "UNMAPPABLE"),
                                              ("entry_type", "UNMAPPABLE")])
def test_explicit_unmappable_goes_to_review_never_accepted(env, field, assessment):
    """3B-6..3B-10: REJECT_OR_HOLD. 3B-11: an UNMAPPABLE column is a human decision -> HUMAN_REVIEW with an
    UNMAPPABLE_PROPOSAL column-review case; still never accepted, no rule, no preview."""
    s = _variant("in10_valid_mix", "txn_amt", canonical_field=field, assessment=assessment)
    wr = orch(env, s).process(renamed_in10(), "u.csv", "2026-09", category="IN-10")
    c = next(x for x in wr.proposal.record.columns if x.source_header == "txn_amt")
    assert (c.validation_class, c.status) == ("NO_MATCH", "unmappable")
    assert wr.decision == Decision.HUMAN_REVIEW and "DUPLICATE_TARGET" not in " ".join(wr.reasons)
    assert wr.intake_case.kind == "UNMAPPABLE_PROPOSAL" and wr.file_mapping is None and wr.preview is None
    col = next(x for x in wr.intake_case.columns if x.source_header == "txn_amt")
    assert col.suggested_field is None and col.validation_class == "NO_MATCH"


def test_invented_canonical_field_goes_to_review_never_accepted(env):
    """3B-6..3B-10: REJECT_OR_HOLD. 3B-11: the validator classes an invented field as NO_MATCH (no valid canonical
    field), so a person decides; the invented name is never suggested, applied or accepted."""
    wr = orch(env, stub("in10_auto_invented")).process(rename("IN-10", AUTO10), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and "INVALID_CANONICAL_FIELD" in " ".join(
        d.code for c in wr.proposal.record.columns for d in c.diagnostics)
    names = {f.name for f in env.reg.get("IN-10").fields}
    assert all(c.suggested_field in names | {None} for c in wr.intake_case.columns)
    assert wr.file_mapping is None and wr.preview is None and wr.reprocessed is None


# ============================================================================================ L, M, N provider / category
def test_provider_disabled_holds_for_manual_review(env):
    s = stub("in10_auto_clear")
    wr = orch(env, s, config=AIConfig()).process(rename("IN-10", AUTO10), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.REJECT_OR_HOLD and s.calls == [] and "AI mapping is disabled" in wr.reasons[0]
    assert wr.proposal.manual_review_required


def test_budget_gate_refusal_holds(env):
    class LiveLike:
        is_live, provider_id = True, "live-like-test-double"

        def propose(self, request):
            raise AssertionError("must not be called")
    led = UsageLedger()
    from datetime import datetime, timezone
    led.record(datetime.now(timezone.utc).date().isoformat(), None)
    cfg = AIConfig(enabled=True, provider="p", model="m", region="r", max_output_tokens=10, max_calls_per_day=1,
                   max_cost_per_day=1.0)
    wr = orch(env, LiveLike(), config=cfg, ledger=led).process(rename("IN-10", AUTO10), "u.csv", "2026-09",
                                                              category="IN-10")
    assert wr.decision == Decision.REJECT_OR_HOLD and "daily call limit reached" in wr.reasons[0]


@pytest.mark.parametrize("content,claimed", [("IN-09", "IN-10"), ("IN-07", "IN-08"), ("IN-05", "IN-06")])
def test_category_mismatch_goes_to_review_without_switching(env, content, claimed):
    """3B-6: REJECT_OR_HOLD. 3B-7: the counts differ (13/8, 7/11, 19/11) -> direct HUMAN_REVIEW case; the category is
    never switched, the exact-header match is shown as a diagnostic, and no LLM call is made."""
    s = stub("in10_auto_clear")
    wr = orch(env, s).process(read(SEP, content), "u.csv", "2026-09", category=claimed)
    assert wr.decision == Decision.HUMAN_REVIEW and s.calls == [] and wr.category is None
    assert wr.route == "HEADER_COUNT_GATE" and f"identifies as {content}" in " ".join(wr.reasons)
    assert wr.intake_case.content_classification == {"category": content, "method": "csv_exact_header"}
    assert wr.intake_case.category == claimed and wr.file_mapping is None and wr.preview is None


def test_equal_count_category_mismatch_is_still_held_without_switching(env):
    """IN-08 and IN-06 both have 11 fields: equal counts pass the gate; the 3B-6 behaviour is unchanged (HOLD)."""
    s = stub("in10_auto_clear")
    wr = orch(env, s).process(read(SEP, "IN-08"), "u.csv", "2026-09", category="IN-06")
    assert wr.decision == Decision.REJECT_OR_HOLD and s.calls == [] and wr.category is None
    assert wr.route == "PROPOSAL" and wr.intake_case is None
    assert "identifies as IN-08" in wr.reasons[0]


def test_unknown_file_without_category_is_held(env):
    s = stub("in10_auto_clear")
    wr = orch(env, s).process(rename("IN-10", AUTO10), "u.csv", "2026-09")
    assert wr.decision == Decision.REJECT_OR_HOLD and s.calls == [] and "never decides the evidence category" in wr.reasons[0]


def test_supplied_category_requires_policy_permission(env, tmp_path):
    doc = json.loads(POLICY_ON.read_text())
    doc["accept_supplied_category"] = False
    (tmp_path / "p.json").write_text(json.dumps(doc))
    wr = orch(env, stub("in10_auto_clear"), policy=tmp_path / "p.json").process(
        rename("IN-10", AUTO10), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and "a person must confirm it" in wr.reasons[0]


# ============================================================================================ policy unit rules
def test_policy_never_uses_proposer_confidence(env):
    # valid_mix: the proposer says CLEAR with confidence 0.99 for txn_amt -> still AMBIGUOUS -> HUMAN_REVIEW
    from smartparser.mapping.proposal_runner import run_proposal
    r = env.parse(renamed_in10())
    rec = run_proposal(r, env.reg, stub("in10_valid_mix"), rules=env.rules()).record
    assert decide(rec, PocAutoAcceptPolicy.load(POLICY_ON)).decision == Decision.HUMAN_REVIEW
    assert decide(None, PocAutoAcceptPolicy.load(POLICY_ON)).decision == Decision.REJECT_OR_HOLD


def test_production_rule_files_unchanged_by_orchestration(env):
    before = {p.name: p.read_bytes() for p in RULES_DIR.glob("*.json")}
    orch(env, stub("in10_auto_clear")).process(rename("IN-10", AUTO10), "u.csv", "2026-09", category="IN-10")
    assert {p.name: p.read_bytes() for p in RULES_DIR.glob("*.json")} == before


# ============================================================================================ held-file context + evaluation
def test_held_file_still_reports_unresolved_and_resolved_context(env):
    wr = orch(env, stub("in10_auto_clear"), config=AIConfig()).process(rename("IN-10", AUTO10), "u.csv", "2026-09",
                                                                       category="IN-10")
    assert wr.decision == Decision.REJECT_OR_HOLD and wr.proposer_calls == 0
    assert wr.unresolved_headers == list(AUTO10.values())
    assert wr.resolved_columns == {c: c for c in tbl("IN-10")[0] if c not in AUTO10}


def _eval_module():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import eval_3b6
    return eval_3b6


def test_eval_3b6_dataset_is_reproducible(tmp_path):
    ev = _eval_module()
    corpus = Path(__file__).resolve().parent.parent / "corpus" / "phase3b6_eval"
    a = ev.build(tmp_path / "a")
    assert a == json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))["cases"]
    for c in a:
        assert (tmp_path / "a" / c["data_file"]).read_bytes() == (corpus / c["data_file"]).read_bytes()
        assert set(c["expected"]) == {"deterministic_mappings", "unresolved", "classes", "decision",
                                      "canonical_output_sha256"}


def test_eval_3b6_all_cases_and_metric_invariants():
    ev = _eval_module()
    results, m = ev.run(Path(__file__).resolve().parent.parent / "corpus" / "phase3b6_eval")
    assert m["fail"] == [] and m["pass"] == len(results) == 34
    d = m["deterministic_mapping"]
    assert d["column_mappings_correct"] == d["column_mappings_checked"] and d["llm_calls_on_fully_mapped_files"] == 0
    e = m["end_to_end"]
    assert e["decision_matches_expected"] == 34 and e["llm_calls_during_reprocessing"] == 0
    assert e["previews_equal_expected_canonical_output"] == e["eligible_previews"]
    assert e["auto_accept_approval_kinds"] == {"POC_AUTO": e["decisions"]["AUTO_ACCEPT"]}
    assert "SIMULATED" in "".join(m) and m["operations"]["tokens_cost_latency"].startswith("not measured")
