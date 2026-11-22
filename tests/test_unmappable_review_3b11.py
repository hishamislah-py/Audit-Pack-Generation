"""Phase 3B-11: UNMAPPABLE -> human review (column-review case) and the mapping-review API / screen backend.

Offline: recorded proposal responses (tools/demo_3b11.py, a RecordedResponseStub - not an LLM), sockets blocked, every
store in a pytest tmp directory. The HTTP layer is exercised through App.handle (no socket)."""
import json
import socket
import sys
from pathlib import Path

import pytest

from smartparser.handoff import writer
from smartparser.packages import review_api as api
from smartparser.review.authority import AuthorityPolicy, Reviewer
from smartparser.review.session import ReviewError
from smartparser.review_ui.server import App, build_service

from .phase3b_support import SEP, read

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import demo_3b11  # noqa: E402

ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")
TEST_AUTHORITY = Path(__file__).parent / "fixtures" / "review" / "test_authority_policy.json"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(writer, "submit_to_uc042", lambda *a, **k: (_ for _ in ()).throw(AssertionError("submit")))
    root = tmp_path / "ws"
    idx = demo_3b11.build(root)
    svc = demo_3b11.build_service(root)
    return svc, idx, root


def events(svc, intake_id=None, *types):
    svc.log.verify()
    return [e for e in svc.log.events() if (intake_id is None or e.intake_id == intake_id)
            and (not types or e.event_type in types)]


def ver(svc, idx, k):
    return svc.load(idx[k]["package_id"]).versions[idx[k]["file_version_id"]]


def map_suggested(svc, pid, vid):
    case, _ = svc.review_case(pid, vid)
    for c in case.columns:
        if c.source_index not in case.effective() and c.suggested_field:
            svc.decide(pid, vid, "MAP", ANALYST, "canonical name", c.source_index)


def col(case, header):
    return next(c for c in case.columns if c.source_header == header)


# ============================================================================================ 1-8 UNMAPPABLE -> HITL
def test_1_unmappable_creates_a_review_task(ws):
    svc, idx, _ = ws
    for k in ("C", "D"):
        v = ver(svc, idx, k)
        assert v.version_status == "REVIEW_REQUIRED" and v.processing_status == "PROPOSAL:HUMAN_REVIEW"
        assert v.review_case_id and v.review_session_id is None                     # one review channel
        case = svc.store.load_case(idx[k]["package_id"], v.review_case_id)
        assert case.kind == "UNMAPPABLE_PROPOSAL" and case.state == "OPEN"
        t = [e.event_type for e in events(svc, v.intake_id)]
        assert "INTAKE_CASE_OPENED" in t and "PROPOSAL_REVIEW_OPENED" not in t
        dec = [e for e in events(svc, v.intake_id, "POC_AUTO_DECISION")][0]
        assert dec.details["decision"] == "HUMAN_REVIEW" and dec.approval_kind is None   # never auto-accepted


def test_2_case_shows_the_unresolved_column_and_the_reason(ws):
    svc, idx, _ = ws
    pid, vid = idx["C"]["package_id"], idx["C"]["file_version_id"]
    case, _ = svc.review_case(pid, vid)
    c = col(case, "ref_code")
    assert (c.suggested_field, c.suggestion_basis, c.proposal_assessment, c.validation_class) == \
        (None, "none", "UNMAPPABLE", "NO_MATCH")
    assert "no defensible mapping" in c.proposal_note
    assert "no defensible canonical field for: ref_code" in case.review_reason
    assert "payment_reference" in case.review_reason and case.missing_fields_diagnostic == ["payment_reference"]
    assert all(x.suggestion_basis == "deterministic" for x in case.columns if x.source_header != "ref_code")


def test_3_analyst_maps_manually_and_the_full_workflow_completes(ws):
    svc, idx, _ = ws
    pid, vid = idx["C"]["package_id"], idx["C"]["file_version_id"]
    map_suggested(svc, pid, vid)
    svc.decide(pid, vid, "CHANGE", ANALYST, "ref_code carries the payment reference (checked with the bank)", 7,
               "payment_reference")
    v = svc.complete_review(pid, vid, [ANALYST], "column review")
    assert v.version_status == "VALIDATED" and v.processing_status == "CASE_RESOLVED:HUMAN_REVIEW"
    assert (svc.store.root / v.handoff.preview_csv).read_bytes() == read(SEP, "IN-10")
    assert any(r["rule_id"].startswith("FM-CRC-") for r in v.mapping_rule_refs)
    assert svc.activate(pid).activated


def test_4_left_unresolved_stays_held(ws):
    svc, idx, _ = ws
    pid, vid = idx["D"]["package_id"], idx["D"]["file_version_id"]
    map_suggested(svc, pid, vid)
    svc.decide(pid, vid, "LEAVE_UNRESOLVED", ANALYST, "cannot tell what the colour code means", 7)
    v = svc.complete_review(pid, vid, [ANALYST], "column review")
    case = svc.store.load_case(pid, v.review_case_id)
    assert case.state == "HELD" and v.version_status == "REVIEW_REQUIRED" and v.missing_fields == ["payment_reference"]
    assert v.handoff is None and svc.load(pid).package_status == "REVIEW_REQUIRED"
    a = svc.activate(pid)
    assert not a.activated and svc.load(pid).active_snapshot_id is None
    assert svc.store.root.joinpath("previews", v.intake_id).exists() is False


def test_5_analyst_rejects_and_resubmission_stays_available(ws):
    svc, idx, _ = ws
    pid, vid = idx["D"]["package_id"], idx["D"]["file_version_id"]
    v = svc.reject_review(pid, vid, ANALYST, "colour codes are not evidence; ask for the reference export")
    assert v.version_status == "REJECTED" and svc.pending_resubmissions(pid) == {"IN-10": vid}
    assert events(svc, v.intake_id, "INTAKE_CASE_REJECTED")
    nv = svc.resubmit(pid, "IN-10", read(SEP, "IN-10"), "cashbook_fixed.csv", "reference column restored").file_version
    assert (nv.version_number, nv.version_status) == (2, "VALIDATED")


def test_6_invalid_manual_mappings_are_refused(ws):
    svc, idx, _ = ws
    pd_, vd = idx["D"]["package_id"], idx["D"]["file_version_id"]
    with pytest.raises(ReviewError, match="VALUE_INCOMPATIBLE"):
        svc.decide(pd_, vd, "CHANGE", ANALYST, "guess", 7, "amount")                    # colour codes are not amounts
    with pytest.raises(ReviewError, match="VALUE_INCOMPATIBLE"):
        svc.decide(pd_, vd, "CHANGE", ANALYST, "guess", 7, "entry_type")                # not an allowed value
    # NOTE: payment_reference is a free-text field (no pattern in the UC-042 contract): mapping colour codes to it is
    # NOT refused deterministically - that choice is the analyst's judgement (the scenario leaves it unresolved).
    pc, vc = idx["C"]["package_id"], idx["C"]["file_version_id"]
    with pytest.raises(ReviewError, match="VALUE_INCOMPATIBLE"):
        svc.decide(pc, vc, "CHANGE", ANALYST, "guess", 7, "amount")
    with pytest.raises(ReviewError, match="not a field"):
        svc.decide(pc, vc, "CHANGE", ANALYST, "guess", 7, "colour")                        # no invented fields
    svc.decide(pc, vc, "MAP", ANALYST, "canonical", 0)
    with pytest.raises(ReviewError, match="DUPLICATE_TARGET"):
        svc.decide(pc, vc, "CHANGE", ANALYST, "guess", 7, "ledger_entry_id")
    with pytest.raises(ReviewError, match="reason"):
        svc.decide(pc, vc, "IGNORE_COLUMN", ANALYST, " ", 7)
    with pytest.raises(ReviewError, match="no suggested field"):
        svc.decide(pc, vc, "MAP", ANALYST, "accept the proposal", 7)                       # UNMAPPABLE: nothing to map
    # ignoring the only source of a required field is allowed as a decision, but the file can never validate
    map_suggested(svc, pc, vc)
    svc.decide(pc, vc, "IGNORE_COLUMN", ANALYST, "not needed", 7)
    v = svc.complete_review(pc, vc, [ANALYST], "review")
    assert v.version_status == "RESUBMISSION_REQUIRED" and v.missing_fields == ["payment_reference"]


def test_7_no_preview_or_handoff_before_resolution(ws):
    svc, idx, _ = ws
    for k in ("B", "C", "D", "E"):
        v = ver(svc, idx, k)
        assert v.handoff is None and v.mapping_rule_refs == []
        assert not events(svc, v.intake_id, "REPROCESSED", "HANDOFF_EVALUATED", "HANDOFF_PREVIEW_WRITTEN")
    fm = svc.o.store.read("file_mappings")["file_mappings"]
    assert len(fm) == 1 and fm[0]["intake_id"] == ver(svc, idx, "A").intake_id           # only A (auto-accepted)


def test_8_full_reprocessing_and_14_checks_after_review(ws):
    svc, idx, _ = ws
    pid, vid = idx["C"]["package_id"], idx["C"]["file_version_id"]
    map_suggested(svc, pid, vid)
    svc.decide(pid, vid, "CHANGE", ANALYST, "verified", 7, "payment_reference")
    v = svc.complete_review(pid, vid, [ANALYST], "column review")
    assert len(v.handoff.checks) == 14 and all(c["passed"] for c in v.handoff.checks)
    assert [c["id"] for c in v.handoff.checks] == list(range(1, 15))
    t = [e.event_type for e in events(svc, v.intake_id)]
    assert t.index("INTAKE_CASE_RESOLVED") < t.index("REPROCESSED") < t.index("HANDOFF_EVALUATED") < \
        t.index("HANDOFF_PREVIEW_WRITTEN")
    rep = [e for e in events(svc, v.intake_id, "REPROCESSED")][0]
    assert rep.details["provider_calls"] == 0


def test_other_routes_unchanged(ws):
    svc, idx, _ = ws
    assert (idx["A"]["status"], idx["A"]["processing_status"]) == ("VALIDATED", "PROPOSAL:AUTO_ACCEPT")
    assert idx["B"]["review_session_id"] and idx["B"]["review_case_id"] is None            # AMBIGUOUS: session
    assert idx["E"]["processing_status"] == "HEADER_COUNT_GATE:HUMAN_REVIEW"
    assert idx["F"]["status"] == "RESUBMISSION_REQUIRED"


# ============================================================================================ API (screen backend)
def app(root, authority=TEST_AUTHORITY):
    return App(build_service(root, authority), ANALYST)


def call(a, method, path, body=None):
    status, ctype, data = a.handle(method, path, body or {})
    return status, (json.loads(data) if ctype.startswith("application/json") else data)


def test_api_queue_and_detail_come_from_the_backend(ws):
    _, idx, root = ws
    a = app(root)
    st, q = call(a, "GET", "/api/reviews")
    assert st == 200 and {r["file_version_id"] for r in q} == {idx[k]["file_version_id"] for k in "BCDE"}
    st, d = call(a, "GET", f"/api/review/{idx['C']['package_id']}/{idx['C']['file_version_id']}")
    assert st == 200 and d["mechanism"] == "column_review_case" and d["review_kind"] == "UNMAPPABLE_PROPOSAL"
    row = next(r for r in d["rows"] if r["source_header"] == "ref_code")
    assert (row["suggested_field"], row["validation"], row["proposal_assessment"]) == (None, "NO_MATCH", "UNMAPPABLE")
    assert d["incoming_header_count"] == 8 and d["expected_field_count"] == 8 and len(d["source_sha256_short"]) == 12
    assert d["missing_fields_diagnostic"] == ["payment_reference"] and d["outcome"]["preview_generated"] is False
    assert len(d["summary"]["outstanding"]) == 8 and len(d["summary"]["required_not_covered"]) == 8   # nothing decided
    st, s = call(a, "GET", f"/api/review/{idx['B']['package_id']}/{idx['B']['file_version_id']}")
    assert s["mechanism"] == "proposal_session" and {r["validation"] for r in s["rows"] if not r["read_only"]} == \
        {"AMBIGUOUS", "PLAUSIBLE"} and "IGNORE_COLUMN" not in s["actions"]
    status, ctype, html = a.handle("GET", "/", {})
    assert status == 200 and b"Mapping Review" in html and b"/app.js" in html


def test_api_actions_errors_and_completion(ws):
    _, idx, root = ws
    a = app(root)
    base = f"/api/review/{idx['C']['package_id']}/{idx['C']['file_version_id']}"
    st, err = call(a, "POST", base + "/decision", {"action": "CHANGE", "source_index": 7, "reason": "x",
                                                   "canonical_field": "amount"})
    assert st == 400 and err["error"] == "VALUE_INCOMPATIBLE"
    st, err = call(a, "POST", base + "/decision", {"action": "IGNORE_COLUMN", "source_index": 7, "reason": ""})
    assert st == 400 and err["error"] == "REASON_REQUIRED"
    st, err = call(a, "POST", base + "/complete", {"basis": "done"})
    assert st == 400 and "only a case under review can be finalised" in err["message"]     # nothing decided yet
    for i in range(7):
        assert call(a, "POST", base + "/decision", {"action": "MAP", "source_index": i, "reason": "canonical"})[0] == 200
    st, d = call(a, "POST", base + "/decision", {"action": "CHANGE", "source_index": 7, "reason": "verified",
                                                 "canonical_field": "payment_reference"})
    assert st == 200 and d["summary"]["required_not_covered"] == []
    st, d = call(a, "POST", base + "/complete", {"basis": "column review"})
    o = d["outcome"]
    assert st == 200 and o["version_status"] == "VALIDATED" and o["reprocessed"] and o["preview_generated"]
    assert len(o["handoff"]["checks"]) == 14 and o["eligible_for_package_activation"]
    status, ctype, csvb = a.handle("GET", base + "/preview", {})
    assert status == 200 and csvb == read(SEP, "IN-10")


def test_api_session_flow_for_ambiguous_proposals(ws):
    _, idx, root = ws
    a = app(root)
    base = f"/api/review/{idx['B']['package_id']}/{idx['B']['file_version_id']}"
    st, err = call(a, "POST", base + "/decision", {"action": "IGNORE_COLUMN", "source_index": 4, "reason": "x"})
    assert st == 400 and err["error"] == "UNSUPPORTED_ACTION"
    # Fix8 D4: an AMBIGUOUS money proposal is never a one-click MAP; the analyst names the field explicitly (CHANGE)
    st, err = call(a, "POST", base + "/decision", {"action": "MAP", "source_index": 4, "reason": "signed amount checked"})
    assert st == 400 and err["error"] == "CLARIFICATION_REQUIRED"
    assert call(a, "POST", base + "/decision", {"action": "CHANGE", "source_index": 4, "reason": "signed amount checked",
                                                "canonical_field": "amount"})[0] == 200
    assert call(a, "POST", base + "/decision", {"action": "MAP", "source_index": 7, "reason": "reference checked"})[0] == 200
    st, d = call(a, "POST", base + "/complete", {"basis": "proposal confirmed"})
    assert st == 200 and d["outcome"]["version_status"] == "VALIDATED" and len(d["outcome"]["handoff"]["checks"]) == 14


def test_api_production_authority_refuses_every_action(ws):
    _, idx, root = ws
    a = App(build_service(root, None), ANALYST)                       # shipped production policy: nobody authorised
    base = f"/api/review/{idx['C']['package_id']}/{idx['C']['file_version_id']}"
    st, err = call(a, "POST", base + "/decision", {"action": "MAP", "source_index": 0, "reason": "x"})
    assert st == 403 and err["error"] == "NOT_AUTHORISED"
    assert AuthorityPolicy.load().scopes == {}


def test_api_unknown_paths_and_versions(ws):
    _, idx, root = ws
    a = app(root)
    assert call(a, "GET", "/api/nothing")[0] == 404
    assert call(a, "GET", f"/api/review/{idx['C']['package_id']}/FV-unknown")[0] == 404
    st, err = call(a, "POST", f"/api/review/{idx['A']['package_id']}/{idx['A']['file_version_id']}/decision",
                   {"action": "MAP", "source_index": 0, "reason": "x"})
    assert st == 409 and err["error"] == "PACKAGE_STATE"                     # VALIDATED: nothing to review
