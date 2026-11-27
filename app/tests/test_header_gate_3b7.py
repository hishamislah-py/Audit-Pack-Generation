"""Phase 3B-7: header-count routing and direct Human-in-the-Loop resolution (offline; recorded stubs only; sockets
blocked). Every file, rule store, evidence store, audit log and preview lives in pytest tmp directories."""
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
from smartparser.handoff.reprocess import ReprocessError, reprocess
from smartparser.handoff.writer import write_preview
from smartparser.mapping.controlled import RULES_DIR
from smartparser.mapping.governed import ColumnRule
from smartparser.orchestration.orchestrator import MappingOrchestrator
from smartparser.orchestration.policy import Decision, PocAutoAcceptPolicy
from smartparser.review.authority import AuthorityError
from smartparser.review.intake import CaseState, decide, reject_case
from smartparser.review.session import ReviewError

from .phase3b_support import ANALYST, ANALYST2, OWNER, SEP, dump, make_env, read, short_example, tbl

POLICY_ON = Path(__file__).parent / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
FX = Path(__file__).parent / "fixtures" / "recorded_llm"
STUB_ON = AIConfig(enabled=True, provider="recorded_stub")
IN10 = tbl("IN-10")[0]
CANON10 = read(SEP, "IN-10")


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    return make_env(tmp_path)


def orch(env, stub=None, config=STUB_ON):
    stub = stub if stub is not None else RecordedResponseStub([])
    gw = ProposalGateway(proposer=stub, config=config, log=env.log)
    o = MappingOrchestrator(env.reg, env.store, env.evidence, gw, PocAutoAcceptPolicy.load(POLICY_ON), env.log,
                            preview_dir=env.root / "preview")
    return o, stub


def insert(fid, pos, header, cells_from=None, values=None):
    """`fid` canonical file with an extra column at `pos` (cells copied from `cells_from`, or `values` per row)."""
    rows = tbl(fid)
    src = rows[0].index(cells_from) if cells_from else None
    out = [rows[0][:pos] + [header] + rows[0][pos:]]
    for k, r in enumerate(rows[1:]):
        v = r[src] if src is not None else values[k % len(values)]
        out.append(r[:pos] + [v] + r[pos:])
    return dump(out)


def plus_note(pos=8):
    return insert("IN-10", pos, "note", values=["free text A", "free text B"])


def dup_amount():
    return insert("IN-10", 8, "amount", cells_from="amount")


def events(env, *types):
    return [e for e in env.log.events() if e.event_type in types]


def resolve(o, env, case, ignore=None, change=None, leave=None, reviewer=ANALYST):
    """Decide every column: IGNORE / CHANGE / LEAVE_UNRESOLVED where listed, MAP (the diagnostic suggestion) otherwise."""
    ctx = o.case_context(case)
    ignore, change, leave = ignore or {}, change or {}, leave or set()
    for c in case.columns:
        i = c.source_index
        if i in ignore:
            decide(case, "IGNORE_COLUMN", reviewer, ignore[i], env.policy, env.log, ctx, i)
        elif i in change:
            decide(case, "CHANGE", reviewer, "reviewer mapping", env.policy, env.log, ctx, i, change[i])
        elif i in leave:
            decide(case, "LEAVE_UNRESOLVED", reviewer, "needs the submitter", env.policy, env.log, ctx, i)
        elif c.suggested_field and i not in case.effective():
            decide(case, "MAP", reviewer, "canonical name", env.policy, env.log, ctx, i)
    return ctx


def canonical_from(data: bytes) -> bytes:
    """Expected preview: the canonical IN-10 header + the source cells of the canonical columns (by name, first match)."""
    rows = list(csv.reader(io.StringIO(data.decode())))
    idx = [rows[0].index(f) for f in IN10]
    return dump([IN10] + [[r[i] for i in idx] for r in rows[1:]])


# ============================================================================================ routing
def test_equal_count_exact_headers_stay_deterministic(env):
    o, s = orch(env)
    wr = o.process(CANON10, "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.DETERMINISTIC and wr.route == "DETERMINISTIC" and wr.intake_case is None
    assert s.calls == [] and wr.preview["csv"].read_bytes() == CANON10


def test_equal_count_unresolved_headers_take_the_proposal_path(env):
    rows = tbl("IN-10")
    ren = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt"}
    stub = RecordedResponseStub([json.loads((FX / "in10_auto_clear.json").read_text(encoding="utf-8"))])
    o, s = orch(env, stub)
    wr = o.process(dump([[ren.get(c, c) for c in rows[0]]] + rows[1:]), "u.csv", "2026-09", category="IN-10")
    assert wr.route == "PROPOSAL" and wr.intake_case is None and len(s.calls) == 1
    assert wr.decision == Decision.AUTO_ACCEPT and wr.preview["csv"].read_bytes() == CANON10


def test_equal_count_completely_different_headers_use_the_proposal_path_not_the_gate(env):
    """Edge 1: same count, no header matches -> NOT the gate (counts are equal); the proposal path runs and, with no
    usable answer, the file is held with every header reported unresolved."""
    rows = tbl("IN-10")
    data = dump([[f"col_{i}" for i in range(8)]] + rows[1:])
    o, s = orch(env)
    wr = o.process(data, "u.csv", "2026-09", category="IN-10")
    assert wr.route == "PROPOSAL" and wr.intake_case is None and wr.decision == Decision.REJECT_OR_HOLD
    assert wr.unresolved_headers == [f"col_{i}" for i in range(8)]


@pytest.mark.parametrize("data_fn,incoming,diff", [(short_example, 4, -4), (plus_note, 9, 1), (dup_amount, 9, 1)])
def test_different_count_goes_directly_to_hitl_and_nothing_else_runs(env, data_fn, incoming, diff):
    stub = RecordedResponseStub([json.loads((FX / "in10_auto_clear.json").read_text(encoding="utf-8"))])
    o, s = orch(env, stub)
    data = data_fn()
    wr = o.process(data, "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and wr.route == "HEADER_COUNT_GATE"
    assert s.calls == [] and wr.proposer_calls == 0 and wr.proposal is None          # no LLM, no proposal
    assert wr.initial is None and wr.resolved_columns == {}                            # no deterministic mapping
    assert wr.file_mapping is None and wr.confirmation is None and wr.reprocessed is None and wr.preview is None
    assert env.store.read("file_mappings")["file_mappings"] == []                      # no rule
    assert events(env, "POC_AUTO_DECISION", "PROPOSAL_REQUESTED", "RULE_CREATED") == []
    c = wr.intake_case
    assert (c.kind, c.state, c.incoming_header_count, c.expected_field_count, c.count_difference) == (
        "HEADER_COUNT_MISMATCH", CaseState.OPEN, incoming, 8, diff)
    assert [x.source_index for x in c.columns] == list(range(incoming))               # every position listed
    assert c.headers == next(csv.reader(io.StringIO(data.decode())))
    assert c.source_sha256 == hashlib.sha256(data).hexdigest() and env.evidence.read_original(c.source_sha256) == data
    assert [e.details["case_id"] for e in events(env, "INTAKE_CASE_OPENED")] == [c.case_id]
    assert not (env.root / "preview").exists()


def test_case_diagnostics_missing_extra_and_duplicates(env):
    o, _ = orch(env)
    c = o.process(dup_amount(), "u.csv", "2026-09", category="IN-10").intake_case
    assert c.duplicate_incoming_headers == {"amount": [4, 8]}
    assert c.potential_duplicate_claims == {"amount": [4, 8]}
    assert c.columns[8].same_header_positions == [4] and c.columns[4].same_header_positions == [8]
    assert c.missing_fields_diagnostic == [] and c.extra_headers_diagnostic == []
    c2 = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    assert c2.extra_headers_diagnostic == [{"source_index": 8, "source_header": "note"}]
    c3 = o.process(short_example(), "u.csv", "2026-09", category="IN-10").intake_case
    assert c3.missing_fields_diagnostic == IN10
    assert all(x.suggestion_basis == "none" for x in c3.columns)                      # no alias/LLM guesses


def test_llm_disabled_does_not_change_the_gate(env):
    o, s = orch(env, config=AIConfig())
    wr = o.process(plus_note(), "u.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and wr.route == "HEADER_COUNT_GATE" and s.calls == []


def test_category_not_supplied_is_not_gated_and_never_guessed(env):
    """Edge: no confirmed category -> no gate (there is no expected count); the classifier cannot identify the file,
    the LLM never decides a category -> HOLD."""
    o, s = orch(env)
    wr = o.process(plus_note(), "u.csv", "2026-09")
    assert wr.decision == Decision.REJECT_OR_HOLD and wr.route == "NO_CATEGORY" and wr.intake_case is None
    assert s.calls == []


@pytest.mark.parametrize("data,name", [(b"%PDF-1.4\n%binary\n", "x.pdf"), (b"", "x.csv"),
                                       (b'a,b\n"unterminated,1\n', "x.csv")])
def test_unsupported_or_malformed_input_is_left_to_the_pipeline(env, data, name):
    """Unsupported / empty / malformed input: the gate makes no count decision on it; the existing pipeline reports it
    (unchanged behaviour) and nothing is mapped, applied or previewed."""
    o, s = orch(env)
    wr = o.process(data, name, "2026-09", category="IN-10")
    assert wr.route != "HEADER_COUNT_GATE" and wr.intake_case is None
    assert wr.decision == Decision.REJECT_OR_HOLD and wr.preview is None and wr.file_mapping is None


# ============================================================================================ decisions + reprocessing
def test_ignore_extra_column_then_reprocess_to_a_canonical_preview(env):
    o, s = orch(env)
    data = plus_note()
    wr = o.process(data, "u.csv", "2026-09", category="IN-10")
    case = wr.intake_case
    resolve(o, env, case, ignore={8: "free-text memo, not evidence"})
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert case.state == CaseState.RESOLVED and done.route == "CASE_RESOLVED"
    fm = done.file_mapping
    assert (fm.intake_id, fm.source_sha256) == (case.intake_id, case.source_sha256)
    assert [c.disposition for c in fm.columns] == ["MAP"] * 8 + ["IGNORE"]
    assert fm.columns[8].ignore_reason == "free-text memo, not evidence" and fm.columns[8].canonical_field is None
    assert done.reprocessed.provider_calls == 0 and s.calls == []
    assert done.eligibility.eligible, [(c.check_id, c.detail) for c in done.eligibility.failed]
    assert done.preview["csv"].read_bytes() == CANON10                               # source cells, canonical order
    side = done.preview["sidecar_doc"]
    assert side["ignored_columns"][0]["source_index"] == 8 and side["ignored_columns"][0]["original_header"] == "note"
    assert side["ignored_columns"][0]["reason"] == "free-text memo, not evidence"
    rec = done.reprocessed.result.records[0]
    assert rec.original["note"] == "free text A"                                       # not silently dropped
    assert done.reprocessed.result.mapping.ignored_columns[0]["rule_id"] == fm.file_mapping_id
    assert {r["rule_id"] for r in side["rules_used"]} == {fm.file_mapping_id}
    assert done.confirmation.category == "IN-10" and done.confirmation.intake_id == case.intake_id
    for ev in ("INTAKE_DECISION", "RULE_CREATED", "RULE_ACTIVATED", "INTAKE_CASE_RESOLVED", "CATEGORY_CONFIRMED"):
        assert events(env, ev), ev
    assert env.log.verify() > 0


def test_ignored_column_in_the_middle_keeps_the_other_cells_aligned(env):
    o, _ = orch(env)
    data = plus_note(pos=3)
    case = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case, ignore={3: "memo"})
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert done.eligibility.eligible, [(c.check_id, c.detail) for c in done.eligibility.failed]
    cc = done.reprocessed.result.classification.content_check
    assert cc["nonconforming_rows"] == 0                                               # positional content check
    assert done.preview["csv"].read_bytes() == CANON10


def test_reprocessing_twice_is_byte_identical(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case, ignore={8: "memo"})
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    rr = reprocess(case.intake_id, env.evidence, env.reg, env.store.load(), done.confirmation)
    el = check_handoff(rr, env.reg)
    again = write_preview(rr, el, env.reg, env.root / "again", now=done.preview["sidecar_doc"]["handoff_timestamp"])
    assert again["csv"].read_bytes() == done.preview["csv"].read_bytes()
    assert again["output_sha256"] == done.preview["output_sha256"] and rr.provider_calls == 0
    assert [m.model_dump() for m in rr.result.mapping.mappings] == \
        [m.model_dump() for m in done.reprocessed.result.mapping.mappings]


def test_choose_duplicate_source_with_identical_header_names(env):
    o, _ = orch(env)
    case = o.process(dup_amount(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = o.case_context(case)
    with pytest.raises(ReviewError, match="explicit disposition"):
        decide(case, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "first is the ledger amount", env.policy, env.log, ctx, 4)
    out = decide(case, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "first is the ledger amount", env.policy, env.log, ctx, 4,
                 others_reason="copy appended by the export tool")
    assert [(d.source_index, d.action, d.canonical_field) for d in out] == [(4, "CHOOSE_DUPLICATE_SOURCE", "amount"),
                                                                             (8, "IGNORE_COLUMN", None)]
    assert out[0].group_id == out[1].group_id and "copy appended" in out[1].reason
    resolve(o, env, case)
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert done.eligibility.eligible and done.preview["csv"].read_bytes() == CANON10
    side = done.preview["sidecar_doc"]
    amount = next(c for c in side["columns"] if c["canonical_field"] == "amount")
    assert amount["source_index"] == 4 and side["ignored_columns"][0]["source_index"] == 8
    rec = done.reprocessed.result.records[0]
    assert rec.original["amount"] == rec.original["amount [col 9]"]                  # both cells kept, distinct keys


def test_chosen_second_duplicate_is_used_and_traceable(env):
    """Edge: the 'wrong' (second) duplicate chosen. The system cannot know business intent; it validates the values
    and records exactly which position supplied the field, so the choice is visible and auditable."""
    o, _ = orch(env)
    rows = tbl("IN-10")
    data = insert("IN-10", 8, "amount", values=["1.00", "2.00"])
    case = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    ctx = o.case_context(case)
    decide(case, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "second column is authoritative", env.policy, env.log, ctx, 8,
           others_reason="superseded")
    resolve(o, env, case)
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    amount = next(c for c in done.preview["sidecar_doc"]["columns"] if c["canonical_field"] == "amount")
    assert amount["source_index"] == 8
    out = list(csv.reader(io.StringIO(done.preview["csv"].read_text())))
    assert [r[IN10.index("amount")] for r in out[1:3]] == ["1.00", "2.00"] and rows[1][4] != "1.00"


def test_duplicate_choice_with_incompatible_values_is_refused(env):
    o, _ = orch(env)
    case = o.process(insert("IN-10", 8, "amount", values=["n/a"]), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = o.case_context(case)
    with pytest.raises(ReviewError, match="VALUE_INCOMPATIBLE"):
        decide(case, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "b", env.policy, env.log, ctx, 8, others_reason="x")


def test_two_columns_can_never_map_to_one_field(env):
    o, _ = orch(env)
    case = o.process(dup_amount(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = o.case_context(case)
    decide(case, "MAP", ANALYST, "b", env.policy, env.log, ctx, 4)
    with pytest.raises(ReviewError, match="DUPLICATE_TARGET"):
        decide(case, "MAP", ANALYST, "b", env.policy, env.log, ctx, 8)
    case2 = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx2 = o.case_context(case2)
    decide(case2, "MAP", ANALYST, "b", env.policy, env.log, ctx2, 6)
    with pytest.raises(ReviewError, match="DUPLICATE_TARGET|VALUE_INCOMPATIBLE"):
        decide(case2, "CHANGE", ANALYST, "b", env.policy, env.log, ctx2, 8, "currency")


def test_change_cannot_contradict_a_deterministic_match(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = o.case_context(case)
    with pytest.raises(ReviewError, match="RULE_CONTRADICTION"):
        decide(case, "CHANGE", ANALYST, "b", env.policy, env.log, ctx, 7, "entry_type")
    with pytest.raises(ReviewError, match="not a field"):
        decide(case, "CHANGE", ANALYST, "b", env.policy, env.log, ctx, 8, "no_such_field")


def test_change_maps_an_unrecognised_column(env):
    """Short header 'pay_ref' instead of payment_reference + an extra memo column: CHANGE + IGNORE resolve it."""
    rows = tbl("IN-10")
    data = dump([rows[0][:7] + ["pay_ref", "memo"]] + [r + ["m"] for r in rows[1:]])
    o, _ = orch(env)
    case = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    assert case.missing_fields_diagnostic == ["payment_reference"]
    resolve(o, env, case, ignore={8: "memo"}, change={7: "payment_reference"})
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert done.eligibility.eligible and done.preview["csv"].read_bytes() == CANON10
    m = next(x for x in done.reprocessed.result.mapping.mappings if x.canonical_field == "payment_reference")
    assert m.original_header == "pay_ref" and m.method.value == "approved_file_mapping"


def test_ignoring_the_only_source_of_a_required_field_holds(env):
    """Edge: IGNORE can never satisfy a field -> HELD, nothing written; then the decision is changed and it resolves."""
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = resolve(o, env, case, ignore={8: "memo", 4: "reviewer thinks it is a copy"})
    held = o.complete_case(case, [ANALYST], "column review", env.policy, ctx)
    assert case.state == CaseState.HELD and held.decision == Decision.REJECT_OR_HOLD and held.route == "CASE_HELD"
    assert case.final_summary["missing_required_fields"] == ["amount"] and held.preview is None
    assert env.store.read("file_mappings")["file_mappings"] == [] and events(env, "INTAKE_CASE_HELD")
    # changing the decision: the held case is revisited; the earlier decision is superseded, never overwritten
    d = decide(case, "MAP", ANALYST, "it is the amount", env.policy, env.log, ctx, 4)[0]
    assert d.supersedes and len([x for x in case.decisions if x.source_index == 4]) == 2
    done = o.complete_case(case, [ANALYST], "column review", env.policy, ctx)
    assert case.state == CaseState.RESOLVED and done.preview["csv"].read_bytes() == CANON10


def test_leave_unresolved_holds(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case, leave={8})
    wr = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert case.state == CaseState.HELD and wr.decision == Decision.REJECT_OR_HOLD
    assert case.final_summary["unresolved_positions"] == [8] and wr.preview is None and wr.file_mapping is None


def test_fewer_columns_cannot_be_completed_and_hold(env):
    o, _ = orch(env)
    case = o.process(short_example(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case, change={0: "ledger_entry_id", 1: "posted_ts", 2: "account_id", 3: "amount"})
    wr = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert case.state == CaseState.HELD and wr.decision == Decision.REJECT_OR_HOLD
    assert case.final_summary["missing_required_fields"] == ["currency", "dc_indicator", "entry_type",
                                                             "payment_reference"]


def test_reject_case(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    with pytest.raises(ReviewError, match="reason"):
        reject_case(case, ANALYST, " ", env.policy, env.log)
    reject_case(case, ANALYST, "wrong export, ask for a corrected file", env.policy, env.log)
    assert case.state == CaseState.REJECTED and case.rejection_reason.startswith("wrong export")
    with pytest.raises(ReviewError):
        decide(case, "MAP", ANALYST, "b", env.policy, env.log, o.case_context(case), 0)
    assert events(env, "INTAKE_CASE_REJECTED") and env.store.read("file_mappings")["file_mappings"] == []


def test_every_decision_needs_a_reason_and_authority(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = o.case_context(case)
    with pytest.raises(ReviewError, match="reason"):
        decide(case, "IGNORE_COLUMN", ANALYST, "", env.policy, env.log, ctx, 8)
    with pytest.raises(AuthorityError):
        decide(case, "IGNORE_COLUMN", OWNER, "memo", env.policy, env.log, ctx, 8)     # data_owner: no FILE_MAPPING
    with pytest.raises(ReviewError, match="not a column"):
        decide(case, "IGNORE_COLUMN", ANALYST, "memo", env.policy, env.log, ctx, 9)
    with pytest.raises(ReviewError, match="unknown action"):
        decide(case, "DROP", ANALYST, "memo", env.policy, env.log, ctx, 8)
    with pytest.raises(ReviewError, match="no suggested field"):
        decide(case, "MAP", ANALYST, "memo", env.policy, env.log, ctx, 8)


def test_undecided_columns_block_finalisation(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    decide(case, "IGNORE_COLUMN", ANALYST2, "memo", env.policy, env.log, o.case_context(case), 8)
    with pytest.raises(ReviewError, match="without a decision"):
        o.complete_case(case, [ANALYST2], "column review", env.policy)


def test_resolved_case_is_terminal(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = resolve(o, env, case, ignore={8: "memo"})
    o.complete_case(case, [ANALYST], "column review", env.policy, ctx)
    with pytest.raises(ReviewError):
        decide(case, "LEAVE_UNRESOLVED", ANALYST, "b", env.policy, env.log, ctx, 8)
    with pytest.raises(ReviewError):
        reject_case(case, ANALYST, "late", env.policy, env.log)


def test_category_mismatch_case_shows_content_category_and_holds(env):
    """IN-07 (7 columns) claimed as IN-08 (11 fields): the case shows the exact-header content category; the supplied
    category is never switched; 7 columns cannot fill 11 fields -> HELD. (If it could be resolved, confirming a category
    that conflicts with the content needs the separate CATEGORY_CONFLICT authority - review.approvals.)"""
    o, _ = orch(env)
    case = o.process(read(SEP, "IN-07"), "u.csv", "2026-09", category="IN-08").intake_case
    assert case.content_classification == {"category": "IN-07", "method": "csv_exact_header"}
    resolve(o, env, case, leave={4, 5})                     # balance_amount / balance_dc_indicator: no IN-08 field
    wr = o.complete_case(case, [ANALYST], "column review", env.policy)
    assert case.state == CaseState.HELD and wr.decision == Decision.REJECT_OR_HOLD   # 7 columns cannot fill 11 fields


# ============================================================================================ integrity
def test_file_changed_after_review_fails_reprocessing(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    ctx = resolve(o, env, case, ignore={8: "memo"})
    stored = env.evidence.root / "originals" / case.source_sha256[:2] / case.source_sha256
    stored.write_bytes(stored.read_bytes().replace(b"free text A", b"free text Z"))     # tamper after review
    with pytest.raises(ReviewError, match="SHA-256"):
        o.case_context(case)
    # 3B-8: refused BEFORE anything is written (was: ReprocessError after the rule + confirmation were written)
    with pytest.raises(ReviewError, match="SHA-256"):
        o.complete_case(case, [ANALYST], "column review", env.policy, ctx)
    assert case.state == CaseState.UNDER_REVIEW and env.store.read("file_mappings")["file_mappings"] == []
    assert events(env, "CATEGORY_CONFIRMED", "RULE_CREATED", "INTAKE_CASE_RESOLVED") == []


def test_same_file_under_a_new_intake_gets_a_new_case_and_no_reuse(env):
    o, s = orch(env)
    data = plus_note()
    case1 = o.process(data, "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case1, ignore={8: "memo"})
    done = o.complete_case(case1, [ANALYST], "column review", env.policy)
    wr2 = o.process(data, "u.csv", "2026-09", category="IN-10")
    assert wr2.decision == Decision.HUMAN_REVIEW and wr2.route == "HEADER_COUNT_GATE"
    assert wr2.intake_id != case1.intake_id and wr2.intake_case.case_id != case1.case_id
    assert wr2.preview is None and s.calls == []
    with pytest.raises(ReprocessError, match="different upload"):
        reprocess(wr2.intake_id, env.evidence, env.reg, env.store.load(), done.confirmation)
    assert len(env.store.read("file_mappings")["file_mappings"]) == 1                 # nothing reusable created
    assert env.store.read("aliases")["aliases"] == [] and env.store.read("layouts")["layouts"] == []


def test_revoked_rule_makes_the_ignore_invalid(env):
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case, ignore={8: "memo"})
    done = o.complete_case(case, [ANALYST], "column review", env.policy)
    rules = env.store.load().with_file_identity(case.intake_id, case.source_sha256)
    fm = rules.file_mappings[0]
    fm.lifecycle.status = "revoked"
    rr = done.reprocessed
    rr.rules = rules
    el = check_handoff(rr, env.reg)
    assert not el.eligible and {c.check_id for c in el.failed} >= {9}


def test_ignore_rule_model_validation():
    with pytest.raises(ValueError):
        ColumnRule(source_index=0, source_header="x", canonical_field="amount", disposition="IGNORE", ignore_reason="r")
    with pytest.raises(ValueError):
        ColumnRule(source_index=0, source_header="x", canonical_field=None, disposition="IGNORE")
    with pytest.raises(ValueError):
        ColumnRule(source_index=0, source_header="x", canonical_field="amount", ignore_reason="r")


def test_production_rules_and_policy_untouched(env):
    before = {p.name: p.read_bytes() for p in RULES_DIR.glob("*.json")}
    o, _ = orch(env)
    case = o.process(plus_note(), "u.csv", "2026-09", category="IN-10").intake_case
    resolve(o, env, case, ignore={8: "memo"})
    o.complete_case(case, [ANALYST], "column review", env.policy)
    assert {p.name: p.read_bytes() for p in RULES_DIR.glob("*.json")} == before
    assert PocAutoAcceptPolicy.load().status == "DISABLED"


def test_resolving_against_the_content_category_needs_conflict_authority(env):
    """IN-08 (11 columns) claimed as IN-07 (7 fields). The reviewer maps the closing balance and ignores 4 columns;
    finalising confirms IN-07 although the content identifies as IN-08 -> CATEGORY_CONFLICT authority (data_owner)."""
    o, _ = orch(env)
    h = tbl("IN-08")[0]
    case = o.process(read(SEP, "IN-08"), "u.csv", "2026-09", category="IN-07").intake_case
    assert case.content_classification["category"] == "IN-08"
    ign = {h.index(c): "not an IN-07 field" for c in ("statement_date", "opening_balance_amount",
                                                     "opening_balance_dc", "entry_count")}
    ctx = resolve(o, env, case, ignore=ign, change={h.index("closing_balance_amount"): "balance_amount",
                                                    h.index("closing_balance_dc"): "balance_dc_indicator"})
    with pytest.raises(AuthorityError, match="CATEGORY_CONFLICT"):
        o.complete_case(case, [ANALYST], "column review", env.policy, ctx)
    assert case.state == CaseState.UNDER_REVIEW and env.store.read("file_mappings")["file_mappings"] == []
    done = o.complete_case(case, [ANALYST], "column review", env.policy, ctx, category_reviewer=OWNER)
    assert case.state == CaseState.RESOLVED and done.confirmation.conflicting_content_category == "IN-08"
    assert done.category == "IN-07" and done.reprocessed.provider_calls == 0
    assert done.eligibility.eligible, [(c.check_id, c.detail) for c in done.eligibility.failed]
    side = done.preview["sidecar_doc"]
    assert sorted(x["source_index"] for x in side["ignored_columns"]) == sorted(ign)
