"""Phase 3B-6.1: deterministic-conflict protection and HITL routing (offline; recorded stub responses built in memory;
sockets blocked). A proposal can never be CLEAR or AUTO_ACCEPTed onto a field that more than one incoming column claims."""
import json
import socket
from pathlib import Path

import pytest

from smartparser.ai.config import AIConfig
from smartparser.ai.gateway import ProposalGateway
from smartparser.ai.proposer import RecordedResponseStub
from smartparser.mapping.proposal_runner import run_proposal
from smartparser.orchestration.orchestrator import MappingOrchestrator
from smartparser.orchestration.policy import Decision, PocAutoAcceptPolicy, decide
from smartparser.review.session import ReviewError, decide_column, open_review, reject_proposal
from smartparser.schemas import SchemaDefinition, SchemaRegistry

from .phase3b_support import ANALYST, SEP, dump, make_env, read, tbl
from .test_proposals import FX

POLICY_ON = Path(__file__).parent / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
STUB_ON = AIConfig(enabled=True, provider="recorded_stub")


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    return make_env(tmp_path)


def stub_for(category, cols):
    """In-memory recorded response: cols = [(source_index, header, field, assessment)]."""
    resp = {"response_schema": "smartparser-mapping-proposal/1.0", "category": category, "notes": "", "columns": [
        {"source_index": i, "source_header": h, "canonical_field": f, "assessment": a, "alternatives": [],
         "explanation": "recorded test response", "evidence": [], "confidence": 0.99} for i, h, f, a in cols]}
    return RecordedResponseStub([{"match": {"category": category, "unresolved_headers": [h for _, h, _, _ in cols]},
                                  "response_text": json.dumps(resp)}])


def orch(env, stub, reg=None):
    gw = ProposalGateway(proposer=stub, config=STUB_ON, log=env.log)
    return MappingOrchestrator(reg or env.reg, env.store, env.evidence, gw, PocAutoAcceptPolicy.load(POLICY_ON),
                               env.log, preview_dir=env.root / "preview")


def poc_rule_events(env):
    return [e for e in env.log.events() if e.event_type in ("RULE_CREATED", "RULE_ACTIVATED")
            and e.approval_kind == "POC_AUTO"]


def with_columns(fid, extra_headers, extra_from):
    """Canonical file of `fid` plus extra columns whose cells copy the named source column."""
    rows = tbl(fid)
    idx = [rows[0].index(src) for src in extra_from]
    return dump([rows[0] + extra_headers] + [r + [r[i] for i in idx] for r in rows[1:]])


def replacing(fid, repl):
    """EQUAL-COUNT variant of `fid` (Phase 3B-7): repl = {canonical column: (new header, column whose cells it copies)}.
    The header-count gate only lets equal-count files reach the deterministic/proposal pipeline, so the 3B-6.1
    conflict cases are exercised with equal counts; the original extra-column inputs are asserted as direct HITL."""
    rows = tbl(fid)
    h = list(rows[0])
    idx = {c: h.index(c) for c in repl}
    src = {c: h.index(s) for c, (_, s) in repl.items()}
    for c, (new, _) in repl.items():
        h[idx[c]] = new
    body = [[r[src[h0]] if h0 in repl else v for h0, v in zip(rows[0], r)] for r in rows[1:]]
    return dump([h] + body)


def assert_direct_hitl(env, s, wr, expected_count, extra):
    """3B-7: a different header count goes straight to a person - no LLM, no proposal, no mapping, no rule."""
    assert wr.decision == Decision.HUMAN_REVIEW and wr.route == "HEADER_COUNT_GATE" and s.calls == []
    assert wr.proposal is None and wr.initial is None and wr.proposer_calls == 0
    c = wr.intake_case
    assert (c.kind, c.incoming_header_count, c.expected_field_count) == ("HEADER_COUNT_MISMATCH", expected_count + extra,
                                                                         expected_count)
    assert_no_auto(env, wr)
    return c


def assert_no_auto(env, wr):
    assert wr.decision != Decision.AUTO_ACCEPT
    assert wr.file_mapping is None and wr.preview is None and wr.reprocessed is None
    assert env.store.read("file_mappings")["file_mappings"] == [] and poc_rule_events(env) == []


# ============================================================================================ Case A (the audit defect)
def _txn_registry():
    f = [("transaction_id", "id", r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"), ("transaction_date", "date", r"^\d{4}-\d{2}-\d{2}$"),
         ("amount", "amount", r"^\d+\.\d{2}$"), ("merchant_id", "id", r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")]
    s = SchemaDefinition.model_validate({
        "category": "TST-TXN", "title": "audit example", "evidence_format": "csv", "verification_status": "provisional",
        "fields": [{"name": n, "type": "string", "source_type": t, "requiredness": "M" if n != "merchant_id" else "O",
                    "required": True, "nullable": n == "merchant_id", "position": i, "constraints": {"pattern": p}}
                   for i, (n, t, p) in enumerate(f)],
        "unique_key": ["transaction_id"], "null_tokens": [""], "classification": {"match_policy": "exact_header"},
        "csv": {"header": [x[0] for x in f], "encoding": "utf-8", "delimiter": ",", "primary_key": ["transaction_id"]}})
    return SchemaRegistry([s], allow_non_official=True)


def _txn_env(env):
    from smartparser.mapping.rule_store import RuleStore
    reg = _txn_registry()
    env.store = RuleStore.initialise(env.root / "rules_txn", reg)
    return reg


def test_case_a_exact_audit_reproduction_is_never_auto_accepted(env):
    """The audit file (6 headers for a 4-field category): transaction_id, TRANSACTION_ID, transaction_date, amount,
    merchant_id, txn_ref. Before 3B-6.1: CLEAR -> AUTO_ACCEPT -> POC_AUTO rule. 3B-6.1: HUMAN_REVIEW. 3B-7: the
    header-count gate sends it directly to a person - no proposal is even requested."""
    reg = _txn_env(env)
    headers = ["transaction_id", "TRANSACTION_ID", "transaction_date", "amount", "merchant_id", "txn_ref"]
    data = dump([headers, ["T1", "T1", "2026-09-01", "12.50", "M7", "T1"]])
    s = stub_for("TST-TXN", [(5, "txn_ref", "transaction_id", "CLEAR")])
    wr = orch(env, s, reg).process(data, "upload.csv", "2026-09", category="TST-TXN")
    c = assert_direct_hitl(env, s, wr, 4, 2)
    assert c.duplicate_incoming_headers == {} and c.potential_duplicate_claims == {"transaction_id": [0, 1]}
    assert c.extra_headers_diagnostic == [{"source_index": 5, "source_header": "txn_ref"}]


def test_case_a_equal_count_conflict_is_never_auto_accepted(env):
    """Equal-count form of the audit defect (4 headers, 4 fields): transaction_id, TRANSACTION_ID, amount, txn_ref;
    txn_ref -> transaction_id proposed CLEAR. DETERMINISTIC_CONFLICT -> HUMAN_REVIEW (before the required-field HOLD for
    transaction_date / merchant_id, 3B-7) + a DETERMINISTIC_CONFLICT column-review case, no rule."""
    reg = _txn_env(env)
    data = dump([["transaction_id", "TRANSACTION_ID", "amount", "txn_ref"], ["T1", "T1", "12.50", "T1"]])
    s = stub_for("TST-TXN", [(3, "txn_ref", "transaction_id", "CLEAR")])
    wr = orch(env, s, reg).process(data, "upload.csv", "2026-09", category="TST-TXN")
    req = s.calls[0]
    assert req.deterministic_conflicts == {"transaction_id": ["transaction_id", "TRANSACTION_ID"]}
    assert [u.source_header for u in req.unresolved_columns] == ["txn_ref"]
    c = wr.proposal.record.columns[0]
    assert c.validation_class == "CONFLICT_INCOMPLETE" and c.status == "rejected"
    assert "DETERMINISTIC_CONFLICT" in [d.code for d in c.diagnostics]
    assert wr.proposal.record.summary.overall == "CONFLICT"
    assert wr.proposal.record.summary.deterministic_conflicts == {"transaction_id": ["transaction_id", "TRANSACTION_ID"]}
    assert wr.decision == Decision.HUMAN_REVIEW and wr.review_session.state == "PROPOSED"
    assert wr.intake_case.kind == "DETERMINISTIC_CONFLICT"
    assert wr.intake_case.potential_duplicate_claims == {"transaction_id": [0, 1]}
    assert_no_auto(env, wr)


def test_case_a_on_uc042_in10(env):
    # different count (10 vs 8): direct HITL
    s0 = stub_for("IN-10", [(9, "entry_ref", "ledger_entry_id", "CLEAR")])
    wr0 = orch(env, s0).process(with_columns("IN-10", ["LEDGER_ENTRY_ID", "entry_ref"],
                                             ["ledger_entry_id", "ledger_entry_id"]), "upload.csv", "2026-09",
                                category="IN-10")
    assert_direct_hitl(env, s0, wr0, 8, 2)
    # equal count: currency -> LEDGER_ENTRY_ID, payment_reference -> entry_ref
    data = replacing("IN-10", {"currency": ("LEDGER_ENTRY_ID", "ledger_entry_id"),
                               "payment_reference": ("entry_ref", "ledger_entry_id")})
    s = stub_for("IN-10", [(7, "entry_ref", "ledger_entry_id", "CLEAR")])
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    c = wr.proposal.record.columns[0]
    assert c.validation_class != "CLEAR" and "DETERMINISTIC_CONFLICT" in [d.code for d in c.diagnostics]
    assert wr.decision == Decision.HUMAN_REVIEW and wr.intake_case.kind == "DETERMINISTIC_CONFLICT"
    assert_no_auto(env, wr)


def test_conflicted_target_never_clear_even_with_high_confidence(env):
    data = with_columns("IN-10", ["LEDGER_ENTRY_ID", "entry_ref"], ["ledger_entry_id", "ledger_entry_id"])
    r = env.parse(data, forced="IN-10")
    n = len(tbl("IN-10")[0])
    out = run_proposal(r, env.reg, stub_for("IN-10", [(n + 1, "entry_ref", "ledger_entry_id", "CLEAR")]),
                       rules=env.rules())
    c = out.record.columns[0]
    assert (c.validation_class, c.proposer_confidence_ignored) == ("CONFLICT_INCOMPLETE", 0.99)
    assert out.record.summary.required_fields_unresolved == []          # the field is present, not missing


def test_explicit_unmappable_onto_conflicted_field_keeps_the_correction(env):
    data = with_columns("IN-10", ["LEDGER_ENTRY_ID", "entry_ref"], ["ledger_entry_id", "ledger_entry_id"])
    n = len(tbl("IN-10")[0])
    out = run_proposal(env.parse(data, forced="IN-10"), env.reg,
                       stub_for("IN-10", [(n + 1, "entry_ref", "ledger_entry_id", "UNMAPPABLE")]), rules=env.rules())
    c = out.record.columns[0]
    assert (c.validation_class, c.status, [d.code for d in c.diagnostics]) == ("NO_MATCH", "unmappable", ["UNMAPPABLE"])


# ============================================================================================ Case B
def test_case_b_duplicate_headers_without_a_proposal_go_to_a_conflict_case(env):
    """3B-6.1: HOLD ("no unresolved source column"). 3B-7: a deterministic conflict is a human decision -> HUMAN_REVIEW
    with a DETERMINISTIC_CONFLICT case; still no LLM call (nothing is unresolved)."""
    s0 = stub_for("IN-10", [(0, "x", "amount", "CLEAR")])
    assert_direct_hitl(env, s0, orch(env, s0).process(with_columns("IN-10", ["AMOUNT"], ["amount"]), "upload.csv",
                                                      "2026-09", category="IN-10"), 8, 1)
    data = replacing("IN-10", {"currency": ("AMOUNT", "amount")})
    s = stub_for("IN-10", [(0, "x", "amount", "CLEAR")])
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and s.calls == [] and wr.proposer_calls == 0
    assert "deterministic conflict" in wr.reasons[0] and "several columns map to the same field" in " ".join(wr.reasons)
    case = wr.intake_case
    assert case.kind == "DETERMINISTIC_CONFLICT" and case.potential_duplicate_claims == {"amount": [4, 6]}
    assert case.missing_fields_diagnostic == ["currency"]
    assert_no_auto(env, wr)


def test_case_b_duplicates_plus_unmappable_extra_go_to_review(env):
    s0 = stub_for("IN-10", [(9, "note", "UNMAPPABLE", "UNMAPPABLE")])
    assert_direct_hitl(env, s0, orch(env, s0).process(with_columns("IN-10", ["AMOUNT", "note"], ["amount", "currency"]),
                                                      "upload.csv", "2026-09", category="IN-10"), 8, 2)
    data = replacing("IN-10", {"currency": ("AMOUNT", "amount"), "payment_reference": ("note", "currency")})
    s = stub_for("IN-10", [(7, "note", "UNMAPPABLE", "UNMAPPABLE")])
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW and any("deterministic conflict" in r for r in wr.reasons)
    assert wr.intake_case.kind == "DETERMINISTIC_CONFLICT" and len(s.calls) == 1
    assert_no_auto(env, wr)


# ============================================================================================ Case C
def test_case_c_extra_header_goes_directly_to_review_and_is_not_dropped(env):
    """3B-6.1: proposal path -> HUMAN_REVIEW (NO_MATCH). 3B-7: 9 columns for 8 fields -> direct HITL; the extra
    column is a case item (no suggestion), its cells stay in the stored original."""
    data = with_columns("IN-10", ["note"], ["currency"])
    s = stub_for("IN-10", [(8, "note", "UNMAPPABLE", "UNMAPPABLE")])
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    case = assert_direct_hitl(env, s, wr, 8, 1)
    assert case.extra_headers_diagnostic == [{"source_index": 8, "source_header": "note"}]
    assert case.missing_fields_diagnostic == []
    assert env.evidence.read_original(wr.source_sha256) == data                     # source kept byte-for-byte


def test_case_c_equal_count_unmappable_column_goes_to_a_review_case(env):
    """Equal count: payment_reference replaced by 'note'. The proposer says UNMAPPABLE (NO_MATCH, reported).
    3B-6.1..3B-10: HOLD (required payment_reference unresolved). 3B-11: a person decides -> HUMAN_REVIEW with an
    UNMAPPABLE_PROPOSAL column-review case (no parallel proposal session); nothing applied, never auto-accepted."""
    data = replacing("IN-10", {"payment_reference": ("note", "currency")})
    s = stub_for("IN-10", [(7, "note", "UNMAPPABLE", "UNMAPPABLE")])
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    joined = " ".join(wr.reasons)
    assert wr.decision == Decision.HUMAN_REVIEW and "no defensible canonical field for: note" in joined
    assert "required field(s) not covered: ['payment_reference']" in joined
    case = wr.intake_case
    assert case.kind == "UNMAPPABLE_PROPOSAL" and wr.review_session is None
    assert (case.columns[7].proposal_assessment, case.columns[7].validation_class) == ("UNMAPPABLE", "NO_MATCH")
    assert case.columns[7].suggested_field is None and case.missing_fields_diagnostic == ["payment_reference"]
    rows = tbl("IN-10")
    assert wr.initial.records[0].original["note"] == rows[1][rows[0].index("currency")]   # source cell kept
    assert wr.unresolved_headers == ["note"]
    assert_no_auto(env, wr)


def test_case_c_extra_header_without_any_answer_is_held_not_dropped(env):
    data = replacing("IN-10", {"payment_reference": ("note", "currency")})
    wr = orch(env, RecordedResponseStub([])).process(data, "upload.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.REJECT_OR_HOLD and wr.unresolved_headers == ["note"]
    assert_no_auto(env, wr)


# ============================================================================================ Case D, E (unchanged paths)
def test_case_d_conflict_free_deterministic_file_unchanged(env):
    s = stub_for("IN-10", [(0, "x", "amount", "CLEAR")])
    wr = orch(env, s).process(read(SEP, "IN-10"), "upload.csv", "2026-09")
    assert wr.decision == Decision.DETERMINISTIC and s.calls == []
    assert wr.eligibility.eligible and wr.preview["csv"].read_bytes() == read(SEP, "IN-10")


def test_case_e_clear_conflict_free_proposal_still_auto_accepts(env):
    rows = tbl("IN-10")
    ren = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt"}
    data = dump([[ren.get(c, c) for c in rows[0]]] + rows[1:])
    s = RecordedResponseStub([json.loads((FX / "in10_auto_clear.json").read_text(encoding="utf-8"))])
    wr = orch(env, s).process(data, "upload.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.AUTO_ACCEPT and wr.file_mapping.approvals[0].approval_kind == "POC_AUTO"
    assert wr.eligibility.eligible and wr.preview["csv"].read_bytes() == read(SEP, "IN-10")


# ============================================================================================ Case F
def _in10_conflict_renamed():
    """Equal count: ledger_entry_id -> entry_ref, account_id -> acct_no, payment_reference -> CURRENCY (copy of currency)."""
    rows = tbl("IN-10")
    ren = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "payment_reference": "CURRENCY"}
    cur = rows[0].index("currency")
    return dump([[ren.get(c, c) for c in rows[0]]] + [r[:-1] + [r[cur]] for r in rows[1:]])


def test_case_f_conflict_blocks_even_when_other_proposals_are_valid(env):
    s = stub_for("IN-10", [(0, "entry_ref", "ledger_entry_id", "CLEAR"), (1, "acct_no", "account_id", "CLEAR")])
    wr = orch(env, s).process(_in10_conflict_renamed(), "upload.csv", "2026-09", category="IN-10")
    classes = {c.source_header: c.validation_class.value for c in wr.proposal.record.columns}
    assert classes == {"entry_ref": "CLEAR", "acct_no": "CLEAR"}                 # valid proposals stay valid ...
    assert wr.proposal.record.summary.deterministic_conflicts == {"currency": ["currency", "CURRENCY"]}
    assert wr.decision == Decision.HUMAN_REVIEW                                   # ... but the conflict blocks AUTO
    case = wr.intake_case
    assert case.kind == "DETERMINISTIC_CONFLICT" and case.proposal_id == wr.proposal.record.proposal_id
    sug = {c.source_header: (c.suggested_field, c.suggestion_basis) for c in case.columns}
    assert sug["entry_ref"] == ("ledger_entry_id", "proposal") and sug["CURRENCY"] == ("currency", "deterministic")
    assert_no_auto(env, wr)


def test_conflict_review_comes_before_unresolved_required_hold(env):
    """3B-6.1 order: required-field HOLD first. 3B-7 order: a deterministic conflict goes to a person FIRST (HUMAN_REVIEW),
    the unresolved required fields are still reported - the reviewer sees both."""
    s = stub_for("IN-10", [(0, "entry_ref", "ledger_entry_id", "CLEAR"), (1, "acct_no", "UNMAPPABLE", "UNMAPPABLE")])
    wr = orch(env, s).process(_in10_conflict_renamed(), "upload.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW
    joined = " ".join(wr.reasons)
    assert "required fields unresolved: ['account_id', 'payment_reference']" in joined
    assert "deterministic conflict" in joined and wr.intake_case.kind == "DETERMINISTIC_CONFLICT"
    assert_no_auto(env, wr)


def test_policy_unit_conflict_precedes_required_hold(env):
    r = env.parse(_in10_conflict_renamed(), forced="IN-10")
    rec = run_proposal(r, env.reg, stub_for("IN-10", [(0, "entry_ref", "ledger_entry_id", "CLEAR"),
                                                      (1, "acct_no", "UNMAPPABLE", "UNMAPPABLE")]),
                       rules=env.rules()).record
    assert rec.summary.required_fields_unresolved and rec.summary.deterministic_conflicts
    assert decide(rec, PocAutoAcceptPolicy.load(POLICY_ON)).decision == Decision.HUMAN_REVIEW


# ============================================================================================ review model support
def test_review_session_supports_map_alternative_ignore_and_reject(env):
    """The 3B-2 proposal review model (unchanged) - exercised directly on a proposal (an extra column is now routed by
    the header-count gate, so it no longer reaches this model through the orchestrator)."""
    data = with_columns("IN-10", ["note"], ["currency"])
    n = len(tbl("IN-10")[0])
    r = env.parse(data, forced="IN-10")
    out = run_proposal(r, env.reg, stub_for("IN-10", [(n, "note", "UNMAPPABLE", "UNMAPPABLE")]), rules=env.rules())
    s, ctx = env.session(r, out)
    open_review(s, ANALYST, env.policy, env.log)
    with pytest.raises(ReviewError, match="cannot be approved as proposed"):
        decide_column(s, n, "APPROVE", ANALYST, "b", env.policy, env.log, ctx)              # NO_MATCH: no silent map
    with pytest.raises(ReviewError, match="FIELD_ALREADY_RESOLVED"):
        decide_column(s, n, "CHANGE", ANALYST, "b", env.policy, env.log, ctx, final_field="currency")
    d = decide_column(s, n, "LEAVE_UNMAPPED", ANALYST, "free-text column, not evidence", env.policy, env.log, ctx)
    assert d.final_field is None and d.basis == "free-text column, not evidence"            # ignore with a reason
    reject_proposal(s, ANALYST, "file needs a corrected export", env.policy, env.log)          # reject the file
    assert s.state == "REJECTED"


def test_review_change_onto_conflicted_field_is_refused(env):
    data = replacing("IN-10", {"currency": ("LEDGER_ENTRY_ID", "ledger_entry_id"),
                               "payment_reference": ("entry_ref", "ledger_entry_id")})
    n = 6
    wr = orch(env, stub_for("IN-10", [(n + 1, "entry_ref", "UNMAPPABLE", "UNMAPPABLE")])).process(
        data, "upload.csv", "2026-09", category="IN-10")
    assert wr.decision == Decision.HUMAN_REVIEW
    from smartparser.review.session import ReviewContext
    ctx = ReviewContext(wr.proposal.request, env.reg.get("IN-10"), list(wr.initial.csv_extraction.raw_headers),
                        {c.index: list(c.sample_values) for c in wr.initial.csv_extraction.columns})
    s = wr.review_session
    open_review(s, ANALYST, env.policy, env.log)
    with pytest.raises(ReviewError, match="DETERMINISTIC_CONFLICT"):
        decide_column(s, n + 1, "CHANGE", ANALYST, "b", env.policy, env.log, ctx, final_field="ledger_entry_id")


def test_policy_unit_det_conflict_with_all_clear_columns_is_review(env):
    rows = tbl("IN-10")
    cur = rows[0].index("currency")
    data = dump([["entry_ref"] + rows[0][1:] + ["CURRENCY"]] + [r + [r[cur]] for r in rows[1:]])
    r = env.parse(data, forced="IN-10")
    rec = run_proposal(r, env.reg, stub_for("IN-10", [(0, "entry_ref", "ledger_entry_id", "CLEAR")]),
                       rules=env.rules()).record
    assert all(c.validation_class == "CLEAR" for c in rec.columns)
    assert decide(rec, PocAutoAcceptPolicy.load(POLICY_ON)).decision == Decision.HUMAN_REVIEW
