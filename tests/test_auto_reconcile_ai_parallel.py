"""23 Nov 2026 demo feedback: (1) once an analyst's Smart Parsing passes validation with nothing left to do, activation and
reconciliation start by themselves (same gates, same identity, trigger recorded), so the automatic AI investigations start
without an extra click; RINGFENCE_AUTO_RECONCILE=off restores the manual step. (2) AI investigations may run in parallel
(RINGFENCE_AI_PARALLEL, default 3)."""
import time

import pytest

import base64

from smartparser.webapp import api, auth, closure, identity

from .test_ringfence_cases import ctx_for, events, make_zip

ALICE = "auto.alice@ringfence.test"
AUTO = "AUTO_AFTER_SMART_PARSER"


def actx(tmp_path):
    """Signed-in mode, as on the demo server: every request runs as the session user."""
    c = ctx_for(tmp_path, engine=True)
    c.authenticator = auth.Authenticator({ALICE: auth.hash_password("pw-auto-test", 1000)})
    return c


def R(ctx, method, path, body=None):
    return api.route(ctx, method, [p for p in path.split("/") if p], {}, body or {}, user=ALICE)


def new_case(ctx, data=None):
    return R(ctx, "POST", "cases", {"customer_name": "Harbourline Payments Ltd", "reporting_period": "2026-09",
                                    "zip_name": "submission.zip",
                                    "zip_b64": base64.b64encode(data if data is not None else make_zip()).decode()})


def settle(ctx, ref, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        d = R(ctx, "GET", f"cases/{ref}")
        if not d["progress"]["current_operation"] and (d["current_run"] or {}).get("status") != "PROCESSING":
            return d
        time.sleep(0.2)
    raise AssertionError("case did not settle")


def _wait(ctx, ref, pred, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        d = R(ctx, "GET", f"cases/{ref}")
        if pred(d):
            return d
        time.sleep(0.3)
    raise AssertionError("condition not reached")


def test_analyst_smart_parsing_continues_to_reconciliation_automatically(tmp_path, monkeypatch):
    monkeypatch.delenv("RINGFENCE_AUTO_RECONCILE", raising=False)
    ctx = actx(tmp_path)
    ref = new_case(ctx)["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    d = _wait(ctx, ref, lambda d: d["status"] == "COMPLETED")
    assert d["completed"]["case_status"] == "CLEAN"
    act = events(ctx, "ANALYST_ACTIVATION_REQUESTED")
    rec = events(ctx, "ANALYST_RECONCILIATION_REQUESTED")
    assert len(act) == 1 and len(rec) == 1
    for e in act + rec:                                   # the analyst who started Smart Parsing; trigger recorded
        assert e["actor_id"] == ALICE and e["details"]["trigger"] == AUTO
    recon = [j for j in ctx.jobs.values() if j["kind"] == "reconciliation"]
    assert len(recon) == 1 and recon[0].get("requested_by") == ALICE     # AUTO_INVESTIGATION authorised_by
    assert ctx.log.verify() > 0


def test_switch_off_keeps_the_manual_step(tmp_path, monkeypatch):
    monkeypatch.setenv("RINGFENCE_AUTO_RECONCILE", "off")
    ctx = actx(tmp_path)
    ref = new_case(ctx)["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref)
    time.sleep(1.0)
    d = R(ctx, "GET", f"cases/{ref}")
    assert d["actions"]["activate"]["enabled"] and not events(ctx, "ANALYST_ACTIVATION_REQUESTED")


def test_no_automatic_step_for_a_system_started_job(tmp_path, monkeypatch):
    monkeypatch.delenv("RINGFENCE_AUTO_RECONCILE", raising=False)
    ctx = ctx_for(tmp_path)
    calls = []
    monkeypatch.setattr(ctx.cases, "_auto_reconcile", lambda pid: calls.append(pid))
    job = {"kind": "intake", "state": "completed", "validation": {"passed": True}, "package_id": "PKG-x"}
    with identity.acting_as_system():
        ctx.cases._maybe_auto_reconcile(job)
    ctx.cases._maybe_auto_reconcile(dict(job, validation={"passed": False}))
    ctx.cases._maybe_auto_reconcile(dict(job, kind="reconciliation"))
    time.sleep(0.3)
    assert calls == []


def test_no_automatic_step_while_something_needs_the_analyst(tmp_path, monkeypatch):
    monkeypatch.delenv("RINGFENCE_AUTO_RECONCILE", raising=False)
    ctx = actx(tmp_path)
    ref = new_case(ctx, data=make_zip(skip=("IN-13",)))["case_ref"]     # a required category is missing
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref)
    time.sleep(1.0)
    d = R(ctx, "GET", f"cases/{ref}")
    assert d["progress"]["missing_required"] and d["status"] == "IN_PROGRESS"
    assert not events(ctx, "ANALYST_ACTIVATION_REQUESTED", "ANALYST_RECONCILIATION_REQUESTED")


@pytest.mark.parametrize("value,expected", [(None, 3), ("1", 1), ("5", 5), ("0", 1), ("99", 8), ("x", 3)])
def test_ai_parallel_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("RINGFENCE_AI_PARALLEL", raising=False)
    else:
        monkeypatch.setenv("RINGFENCE_AI_PARALLEL", value)
    assert closure.ai_parallel() == expected
