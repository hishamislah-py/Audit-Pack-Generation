"""Analyst review and finalisation make ZERO model calls (23 Nov 2026).

Every model request of the application is made inside the closure-runner subprocess, and only two operations can make one:
`investigate` (the AI investigation stage) and `preview` with an AI closing summary (the closing-summary stage). Every other
operation runs with ai=False, whose subprocess environment carries no provider key at all. This test instruments the runner
(every subprocess operation and its ai flag, plus the environment it would get) and drives the real closure service with
the real UC-042 library (TEST DOUBLE investigator of tests/test_closure_service.py; no live AI):

  AI stage        reconciliation -> automatic investigations (ai=True: investigate)
  review          open / reopen / evidence / history / ACCEPT / REJECT (+/- explanation) / pending refusals -> 0
  AI stage        closing-summary preview (ai=True: preview, exactly one)
  finalisation    GENERATE / final JSON, PDF, HTML / reopen closure and final pack -> 0
"""
import json

from smartparser.reconciliation.closure_runner import AI_ENV_KEYS
from smartparser.webapp.closure import FIXED, ClosureService

from .test_closure_service import (DoubleRunner, R, USER, code_of, ctx_for, needs_closure, reconcile, scenario_zip,
                                   wait_closure, wait_job)


class CountingRunner(DoubleRunner):
    """Records every runner subprocess operation with its ai flag and checks that an ai=False operation's environment
    carries no AI provider value."""
    LOG = []

    def _call(self, op, payload, ai, scratch=None):
        env = self._env(ai)
        leaked = sorted(k for k in env if k in AI_ENV_KEYS) if not ai else []
        CountingRunner.LOG.append({"op": op, "ai": bool(ai), "leaked_ai_env": leaked})
        return super()._call(op, payload, ai, scratch)


def ai_ops(since):
    return [x["op"] for x in CountingRunner.LOG[since:] if x["ai"]]


@needs_closure
def test_review_and_finalisation_make_zero_model_calls(tmp_path):
    CountingRunner.LOG = []
    data, customer, period = scenario_zip("scenario_2")
    ctx = ctx_for(tmp_path, runner_cls=CountingRunner)
    ref = reconcile(ctx, data, customer, period)
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING", "INVESTIGATING"))
    table = {"AI stage: investigations": len(ai_ops(0))}
    assert table["AI stage: investigations"] >= 2 and set(ai_ops(0)) == {"investigate"}
    pub = [x for x in v["exceptions"] if x["ai_state"] == "PUBLISHED"]
    e0, e1 = pub[0]["exception_id"], pub[1]["exception_id"]
    i0, i1 = pub[0]["investigation_id"], pub[1]["investigation_id"]
    findings_before = {i: R(ctx, "GET", f"cases/{ref}/closure/investigations/{i}")["findings"] for i in (i0, i1)}

    def zero(name, fn):
        mark = len(CountingRunner.LOG)
        out = fn()
        assert ai_ops(mark) == [], (name, ai_ops(mark))
        table[name] = len(ai_ops(mark))
        return out
    ws = zero("Open investigation (PENDING REVIEW)", lambda: R(ctx, "GET", f"cases/{ref}/closure/exceptions/{e0}"))
    assert ws["decision"]["review_state"] == "PENDING_REVIEW" and ws["investigation"]["investigation_id"] == i0
    zero("Reopen investigation", lambda: R(ctx, "GET", f"cases/{ref}/closure/exceptions/{e0}"))
    det = zero("View supporting evidence and citations", lambda: R(ctx, "GET", f"cases/{ref}/closure/investigations/{i0}"))
    assert det["verify"]["ok"] and det["evidence_ledger"]["records"]
    zero("View decision history", lambda: R(ctx, "GET", f"cases/{ref}/closure/exceptions/{e0}/history"))
    zero("Closing preview while findings are pending (refused)", lambda: code_of(lambda: R(
        ctx, "POST", f"cases/{ref}/closure/review/preview", {"confirm_ai": True, "expected_revision": v["revision"]})))
    zero("GENERATE while findings are pending (refused)", lambda: code_of(lambda: R(
        ctx, "POST", f"cases/{ref}/closure/review/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                             "snapshot_sha256": "0" * 64, "expected_revision": v["revision"]})))
    a = zero("Accept finding with explanation", lambda: R(ctx, "POST", f"cases/{ref}/closure/investigations/{i0}/decision",
             {"decision": "ACCEPT", "expected_revision": v["revision"], "explanation": "Agreed with the cited records."}))
    r = zero("Reject finding with explanation", lambda: R(ctx, "POST", f"cases/{ref}/closure/investigations/{i1}/decision",
             {"decision": "REJECT", "expected_revision": a["closure"]["revision"], "explanation": "Needs the client's file."}))
    v = r["closure"]
    rejected_without = None
    for x in v["exceptions"]:
        if x["exception_id"] in (e0, e1):
            continue
        if x["ai_state"] == "PUBLISHED":
            kind = "REJECT" if rejected_without is None else "ACCEPT"
            name = "Reject finding without explanation" if kind == "REJECT" else "Accept finding"
            out = zero(name, lambda x=x, kind=kind: R(ctx, "POST", f"cases/{ref}/closure/investigations/{x['investigation_id']}/decision",
                                                      {"decision": kind, "expected_revision": v["revision"]}))
            if kind == "REJECT":
                rejected_without = x["investigation_id"]
                assert out["analyst_review"]["rejection_reason"] == FIXED["REJECT"]
            v = out["closure"]
        else:
            zero("Exclude failed investigation", lambda x=x: R(ctx, "POST", f"cases/{ref}/closure/review/selections", {
                "expected_revision": v["revision"], "selections": [{"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST"}]}))
            v = R(ctx, "GET", f"cases/{ref}/closure")
    zero("Reopen a reviewed investigation", lambda: R(ctx, "GET", f"cases/{ref}/closure/exceptions/{e1}"))
    hist = zero("View decision history (after decisions)", lambda: R(ctx, "GET", f"cases/{ref}/closure/exceptions/{e1}/history"))
    assert hist["events"][-1]["event_type"] == "ANALYST_INVESTIGATION_REJECTED"
    assert v["state"] == "READY", v["review"]["readiness"]
    # missing dependency: GENERATE without a closing summary (no preview) is refused, never filled by a model call
    code = zero("GENERATE without a closing summary (refused: missing dependency)", lambda: code_of(lambda: R(
        ctx, "POST", f"cases/{ref}/closure/review/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                             "snapshot_sha256": "0" * 64, "expected_revision": v["revision"]})))
    assert code in ("PREVIEW_REQUIRED", "NO_REVIEW", "BLOCKED", "PREVIEW_STALE"), code
    # AI stage: the closing summary (exactly one ai=True operation)
    mark = len(CountingRunner.LOG)
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"confirm_ai": True, "expected_revision": v["revision"]})
    assert wait_job(ctx, pv["job_id"])["state"] == "completed"
    table["AI stage: closing summary (preview)"] = len(ai_ops(mark))
    assert ai_ops(mark) == ["preview"]
    v = R(ctx, "GET", f"cases/{ref}/closure")
    cur = v["review"]["current_preview"]

    def generate():
        out = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
            "decision": "GENERATE", "acknowledgement_accepted": True, "snapshot_sha256": cur["snapshot_sha256"],
            "expected_revision": v["revision"]})
        assert wait_job(ctx, out["job_id"])["state"] == "completed"
        return out
    zero("Generate final audit pack", generate)
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "GENERATED" and v["final_pack"]["verified"] is True
    final = json.loads(zero("Final pack JSON", lambda: R(ctx, "GET", f"cases/{ref}/closure/final-pack/json"))[1])
    pdf = zero("Generate / download PDF", lambda: R(ctx, "GET", f"cases/{ref}/closure/final-pack/pdf"))[1]
    html = zero("Generate / download HTML", lambda: R(ctx, "GET", f"cases/{ref}/closure/final-pack/html"))[1].decode("utf-8")
    zero("Reopen final pack", lambda: (R(ctx, "GET", f"cases/{ref}/closure"), R(ctx, "GET", f"cases/{ref}/closure/final-pack")))
    assert pdf[:5] == b"%PDF-"
    # persisted content reused: the final pack carries the persisted AI findings and summary and the analyst's decisions
    reviews = {e["investigation"]["investigation_id"]: e["investigation"].get("analyst_review") for e in final["exception_register"]}
    assert (reviews[i0]["decision"], reviews[i0]["comment"], reviews[i0]["reviewer"]["user_id"]) == ("ACCEPT", "Agreed with the cited records.", USER)
    assert (reviews[i1]["decision"], reviews[i1]["rejection_reason"]) == ("REJECT", "Needs the client's file.")
    assert reviews[rejected_without]["rejection_reason"] == FIXED["REJECT"] if rejected_without else True
    for s in ("Agreed with the cited records.", "Needs the client&#x27;s file." if "&#x27;" in html else "Needs the client's file.",
              final["closing_summary"]["output"]["overall_position"][:60]):
        assert s in html, s
    for i, f in findings_before.items():                       # the original AI findings are unchanged after the decisions
        assert R(ctx, "GET", f"cases/{ref}/closure/investigations/{i}")["findings"] == f
    # no ai=False operation ever received a provider value in its environment
    assert all(not x["leaked_ai_env"] for x in CountingRunner.LOG)
    table["operations instrumented"] = len(CountingRunner.LOG)
    print("ZERO-LLM TABLE " + json.dumps(table))
