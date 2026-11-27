"""Ringfence frontend contract (RINGFENCE_FRONTEND_API_CONTRACT.md): every field and endpoint the Claude Design
frontend's adapter relies on, through the real handler (and the HTTP layer for status codes)."""
import json
import time

from smartparser.webapp.server import App

from .phase3b_support import dump, tbl
from .test_ringfence_cases import (NAMES, R, ctx_for, err, in05_with_extra, make_zip, new_case, settle, upload)


def H(app, method, path, body=None):
    s, ctype, data = app.handle(method, path, {"X-Smartparser-Client": "webapp"} if method == "POST" else {},
                                json.dumps(body or {}).encode() if method == "POST" else b"")
    return s, json.loads(data) if ctype.startswith("application/json") else data


def test_queue_detail_steps_outstanding_and_blocked_by(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx, "Alpha Pay", data=make_zip(skip=("IN-03", "IN-05")))["case_ref"]
    b = new_case(ctx, "Bravo Pay")["case_ref"]
    q = R(ctx, "GET", "cases")
    assert all(x["other_cases_for_period"] == 1 for x in q["items"])
    assert [s["state"] for s in q["items"][0]["steps"]] == ["todo"] * 5
    R(ctx, "POST", f"cases/{a}/start")
    settle(ctx, a)
    upload(ctx, a, NAMES["IN-05"], in05_with_extra(2), "IN-05")
    d = settle(ctx, a)
    assert [s["key"] for s in d["steps"]] == ["smart_parser", "review", "validation", "activation", "reconciliation"]
    assert [s["state"] for s in d["steps"]] == ["done", "attention", "attention", "todo", "todo"]
    o = d["outstanding"]
    assert [m["category"] for m in o["missing_categories"]] == ["IN-03"] and o["missing_categories"][0]["format"] == "CSV"
    md = o["mapping_decisions"][0]
    assert (md["category"], md["outstanding"], md["total"], md["columns"]) == ("IN-05", 2, 2, ["memo_1", "memo_2"])
    assert o["files_requiring_replacement"] == [] and o["refused_uploads"] == []      # IN-05 was not in the ZIP
    assert d["kept"][0].startswith("16 of 19") and d["status_since"] and d["revision"] > 0
    q = R(ctx, "GET", "cases", q={"status": "WAITING"})
    assert [x["case_ref"] for x in q["items"]] == [b] and q["active_case_ref"] == a     # slot known in a filtered list
    assert q["active_case"]["customer_name"] == "Alpha Pay"
    db = R(ctx, "GET", f"cases/{b}")
    assert db["blocked_by"]["case_ref"] == a and not db["actions"]["start"]["enabled"]
    R(ctx, "POST", f"cases/{a}/defer")
    assert [s["state"] for s in R(ctx, "GET", f"cases/{a}")["steps"]][1] == "paused"


def test_stale_revision_is_refused_and_repeated_requests_do_not_duplicate(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx)["case_ref"]
    rev = R(ctx, "GET", f"cases/{a}")["revision"]
    R(ctx, "POST", f"cases/{a}/start", {"expected_revision": rev})
    assert err(lambda: R(ctx, "POST", f"cases/{a}/defer", {"expected_revision": rev})) == "CASE_CHANGED"
    assert err(lambda: R(ctx, "POST", f"cases/{a}/start")) == "CASE_STATE"              # no second run
    settle(ctx, a)
    R(ctx, "POST", f"cases/{a}/defer")
    assert err(lambda: R(ctx, "POST", f"cases/{a}/defer")) == "CASE_STATE"
    d = R(ctx, "GET", f"cases/{a}")
    assert len(d["runs"]) == 1 and len([e for e in ctx.events() if e["event_type"] == "CASE_DEFERRED"]) == 1


def test_frontend_action_names_and_file_level_reject(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx, data=make_zip(skip=("IN-05",)))["case_ref"]
    R(ctx, "POST", f"cases/{a}/start")
    settle(ctx, a)
    upload(ctx, a, NAMES["IN-05"], in05_with_extra(2), "IN-05")
    vid = settle(ctx, a)["outstanding"]["mapping_decisions"][0]["file_version_id"]
    rows = [x for x in R(ctx, "GET", f"cases/{a}/review/{vid}")["rows"] if x["needs_attention"]]
    rv = R(ctx, "POST", f"cases/{a}/review/{vid}/decision", {"action": "IGNORE_COLUMN", "source_index": rows[0]["source_index"]})
    assert rv["counts"]["decided"] == 1
    d = R(ctx, "POST", f"cases/{a}/review/{vid}/decision", {"action": "REJECT", "source_index": rows[1]["source_index"]})
    assert d["outstanding"]["files_requiring_replacement"][0]["cause"] == "COLUMN_REJECTED"


def test_run_detail_has_stages_and_events_and_case_activity_covers_every_run(tmp_path):
    ctx = ctx_for(tmp_path)
    real, n = ctx.svc.validate, {"n": 0}

    def flaky(pid):
        n["n"] += 1
        if n["n"] == 1:
            raise RuntimeError("technical failure")
        return real(pid)
    ctx.svc.validate = flaky
    a = new_case(ctx)["case_ref"]
    R(ctx, "POST", f"cases/{a}/start")
    d = settle(ctx, a)
    run1 = R(ctx, "GET", f"cases/{a}/runs/{d['runs'][0]['run_id']}")
    assert [s["key"] for s in run1["stages"]][:3] == ["init", "read", "identify"] and run1["events"]
    assert run1["status"] == "FAILED" and run1["llm_mode"]["mode"] == "DISABLED"
    R(ctx, "POST", f"cases/{a}/retry", {"confirm": True})
    d = settle(ctx, a)
    act = R(ctx, "GET", f"cases/{a}/activity")
    types = {e["event_type"] for e in act["events"]}
    assert {"CASE_CREATED", "CASE_STARTED", "CASE_RUN_FAILED", "CASE_RETRY_REQUESTED", "PACKAGE_CREATED"} <= types
    pkgs = {e["details"].get("package_id") for e in act["events"] if e["event_type"] == "PACKAGE_CREATED"}
    assert pkgs == {r["package_id"] for r in d["runs"]} and act["chain"]["verified"]


def test_customers_endpoints(tmp_path):
    ctx = ctx_for(tmp_path)
    new_case(ctx, "Alpha Pay")
    new_case(ctx, "Alpha Pay", "2026-10")
    new_case(ctx, "Bravo Pay")
    cs = R(ctx, "GET", "customers")
    assert [(c["customer_name"], c["cases"]) for c in cs] == [("Alpha Pay", 2), ("Bravo Pay", 1)]
    one = R(ctx, "GET", f"customers/{cs[0]['customer_id']}")
    assert [x["reporting_period"] for x in one["cases"]] == ["2026-10", "2026-09"] and one["reconciliation_history"] == []
    assert err(lambda: R(ctx, "GET", "customers/CUST-nobody")) == "NOT_FOUND"


def test_state_survives_restart_and_an_interrupted_run_is_a_technical_failure(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx)["case_ref"]
    R(ctx, "POST", f"cases/{a}/start")
    d = settle(ctx, a)
    # simulate a server stop while the intake job was running: the job record is left "running"
    j = ctx.jobs[d["runs"][0]["intake_job_id"]]
    rec = dict(j, state="running", finished_at=None)
    (ctx.root / "jobs" / f"{j['job_id']}.json").write_text(json.dumps(rec), encoding="utf-8")
    c = json.loads((ctx.root / "cases" / f"{a}.json").read_text(encoding="utf-8"))
    c["runs"][0]["status"] = "PROCESSING"
    (ctx.root / "cases" / f"{a}.json").write_text(json.dumps(c), encoding="utf-8")
    ctx2 = ctx_for(tmp_path)                                                   # restart
    d2 = R(ctx2, "GET", f"cases/{a}")
    assert d2["status"] == "IN_PROGRESS" and d2["current_run"]["status"] == "FAILED"
    assert d2["current_run"]["failure"]["code"] == "INTAKE_JOB_INTERRUPTED"
    assert d2["actions"]["retry_from_beginning"]["enabled"]


def test_http_errors_are_structured(tmp_path):
    ctx = ctx_for(tmp_path)
    app = App(ctx)
    s, body = H(app, "GET", "/api/cases/RF-2026-09-999")
    assert s == 404 and body["error"] == "NOT_FOUND" and body["message"]
    a = new_case(ctx)["case_ref"]
    s, body = H(app, "POST", f"/api/cases/{a}/resume")
    assert s == 409 and body["error"] == "CASE_STATE"
    s, body = H(app, "POST", f"/api/cases/{a}/retry", {"confirm": True})
    assert s == 409 and body["error"] == "CASE_NOT_ACTIVE"
    s, body = H(app, "POST", "/api/cases", {"customer_name": "", "reporting_period": "2026-09"})
    assert s == 400 and body["error"] in ("INVALID", "NOT_A_ZIP")
    s, body = app.handle("POST", f"/api/cases/{a}/start", {}, b"{}")[0], None
    assert s == 403                                                             # client header required
