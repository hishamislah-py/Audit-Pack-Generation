"""Analyst review of AI findings with an OPTIONAL explanation (23 Nov 2026 owner requirement; supersedes O4 for this one
decision): ACCEPT / REJECT, the analyst's own words stored verbatim (REJECT reason, else the fixed wording; ACCEPT comment),
identity and timestamp, PENDING REVIEW before a decision, audit history, final pack and report. A decision never changes the
engine's reconciliation result. The journey uses the real closure service and the real UC-042 library with the TEST DOUBLE
investigator of tests/test_closure_service.py (no live AI)."""
import json

import pytest

from smartparser.webapp import api
from smartparser.webapp.closure import EXPLANATION_MAX, FIXED, ClosureError, _explanation

from .test_closure_service import R, USER, code_of, ctx_for, needs_closure, reconcile, scenario_zip, wait_closure, wait_job


# ===================================================================================================== unit
def test_explanation_is_optional_trimmed_and_printable():
    assert _explanation(None) == "" and _explanation("   ") == ""
    assert _explanation("  The C0004 snapshot explains the £90; cause unknown.\n") == "The C0004 snapshot explains the £90; cause unknown."
    assert _explanation("Zeile 1\nZeile 2 – Übersicht €") == "Zeile 1\nZeile 2 – Übersicht €"
    for bad in ("x" * (EXPLANATION_MAX + 1), "bell \x07", "漢字", "emoji \U0001F600", 42):
        with pytest.raises(ClosureError) as e:
            _explanation(bad)
        assert e.value.code == "INVALID"


# ===================================================================================================== journey
@needs_closure
def test_accept_reject_with_explanation_pending_audit_and_final_pack(tmp_path):
    data, customer, period = scenario_zip("scenario_2")
    ctx = ctx_for(tmp_path)
    ref = reconcile(ctx, data, customer, period)
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING", "INVESTIGATING"))
    pub = [x for x in v["exceptions"] if x["ai_state"] == "PUBLISHED"]
    assert len(pub) >= 2
    pack_before = json.dumps(R(ctx, "GET", f"cases/{ref}/closure/pack")["exception_register"], sort_keys=True)
    # PENDING REVIEW: a published AI finding without a decision is never treated as accepted
    assert all(x["review_state"] == "PENDING_REVIEW" and x["analyst_decision"] is None for x in pub)
    ws = R(ctx, "GET", f"cases/{ref}/closure/exceptions/{pub[0]['exception_id']}")
    assert ws["decision"]["review_state"] == "PENDING_REVIEW" and ws["decision"]["current"] is None
    assert any(b.startswith("AI review pending") for b in v["review"]["readiness"]["blockers"])
    inv0, inv1 = pub[0]["investigation_id"], pub[1]["investigation_id"]
    accept_text = "Agreed: the cited bank entry and ledger rows support the AI finding; cause still to be confirmed."
    reject_text = "Rejected: the finding relies on a settlement file the client has not yet confirmed."
    # invalid explanations are refused and record nothing
    for bad in ("x" * (EXPLANATION_MAX + 1), "漢字"):
        assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv0}/decision",
                                 {"decision": "ACCEPT", "expected_revision": v["revision"], "explanation": bad})) == "INVALID"
    assert R(ctx, "GET", f"cases/{ref}/closure/exceptions/{pub[0]['exception_id']}")["decision"]["current"] is None
    # ACCEPT with an explanation; REJECT with an explanation
    a = R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv0}/decision",
          {"decision": "ACCEPT", "expected_revision": v["revision"], "explanation": "  " + accept_text + "  "})
    rec = a["analyst_review"]
    assert (rec["decision"], rec["comment"], rec["rejection_reason"], rec["decided_by"]) == ("ACCEPT", accept_text, "", USER)
    assert rec["reviewer"]["user_id"] == USER and rec["decided_at"] and rec["explanation_supplied"] is True
    r = R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv1}/decision",
          {"decision": "REJECT", "expected_revision": a["closure"]["revision"], "explanation": reject_text})
    assert (r["analyst_review"]["rejection_reason"], r["analyst_review"]["comment"]) == (reject_text, "")
    v = r["closure"]
    rows = {x["exception_id"]: x for x in v["exceptions"]}
    assert rows[pub[0]["exception_id"]]["review_state"] == "REVIEWED" and rows[pub[0]["exception_id"]]["decided_by"] == USER
    # workspace: current decision with its explanation, history
    ws = R(ctx, "GET", f"cases/{ref}/closure/exceptions/{pub[1]['exception_id']}")
    assert ws["decision"]["current"]["explanation"] == reject_text and ws["decision"]["review_state"] == "REVIEWED"
    assert ws["decision"]["history"][-1]["explanation"] == reject_text
    # audit events carry the decision, the explanation and the analyst
    ev = [e for e in ctx.events() if e["event_type"] in ("ANALYST_INVESTIGATION_ACCEPTED", "ANALYST_INVESTIGATION_REJECTED")]
    assert {(e["event_type"], e["actor_id"], e["details"].get("comment") or e["details"].get("rejection_reason")) for e in ev} == {
        ("ANALYST_INVESTIGATION_ACCEPTED", USER, accept_text), ("ANALYST_INVESTIGATION_REJECTED", USER, reject_text)}
    # remaining findings: REJECT without an explanation -> the fixed wording; others ACCEPT; failed ones excluded
    fixed_done = False
    for x in v["exceptions"]:
        if x["exception_id"] in (pub[0]["exception_id"], pub[1]["exception_id"]):
            continue
        if x["ai_state"] == "PUBLISHED":
            d = "ACCEPT" if fixed_done else "REJECT"
            out = R(ctx, "POST", f"cases/{ref}/closure/investigations/{x['investigation_id']}/decision",
                    {"decision": d, "expected_revision": v["revision"]})
            if d == "REJECT":
                assert out["analyst_review"]["rejection_reason"] == FIXED["REJECT"] and out["analyst_review"]["explanation_supplied"] is False
                assert R(ctx, "GET", f"cases/{ref}/closure/exceptions/{x['exception_id']}")["decision"]["current"]["explanation"] is None
                fixed_done = True
            v = out["closure"]
        else:
            R(ctx, "POST", f"cases/{ref}/closure/review/selections", {"expected_revision": v["revision"],
              "selections": [{"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST"}]})
            v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "READY", v["review"]["readiness"]
    # the decisions never changed the engine's exceptions
    assert json.dumps(R(ctx, "GET", f"cases/{ref}/closure/pack")["exception_register"], sort_keys=True) == pack_before
    # preview -> GENERATE -> the final pack and report carry the decisions, explanations, analyst and time
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"confirm_ai": True, "expected_revision": v["revision"]})
    assert wait_job(ctx, pv["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    cur = v["review"]["current_preview"]
    out = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": True, "snapshot_sha256": cur["snapshot_sha256"],
        "expected_revision": v["revision"]})
    assert wait_job(ctx, out["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "GENERATED" and v["final_pack"]["verified"] is True
    final = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/json")[1])
    reviews = {e["investigation"]["investigation_id"]: e["investigation"].get("analyst_review") for e in final["exception_register"]}
    assert (reviews[inv0]["decision"], reviews[inv0]["comment"], reviews[inv0]["reviewer"]["user_id"]) == ("ACCEPT", accept_text, USER)
    assert (reviews[inv1]["decision"], reviews[inv1]["rejection_reason"]) == ("REJECT", reject_text)
    assert reviews[inv0]["decided_at"] and reviews[inv1]["decided_at"]
    assert inv1 not in {i["investigation_id"] for i in final["ai_investigations"]}           # rejected AI content excluded
    assert [e["exception"] for e in final["exception_register"]] == json.loads(pack_before)    # engine result unchanged
    html = R(ctx, "GET", f"cases/{ref}/closure/final-pack/html")[1].decode("utf-8")
    for s in (accept_text, reject_text, "REJECTED BY ANALYST", FIXED["REJECT"]):
        assert s in html, s
    for s in ("ACKNOWLEDGED", "CHALLENGED"):
        assert s not in html
    # the original AI investigation of the rejected finding stays in the audit history, unchanged and verifiable
    det = R(ctx, "GET", f"cases/{ref}/closure/investigations/{inv1}")
    assert det["verify"]["ok"]
    assert ctx.log.verify() > 0
