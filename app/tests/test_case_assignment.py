"""Case assignment (single-analyst demo support).

`assigned_to` is a plain case attribute recorded at registration. `GET /api/cases?assigned=me` narrows the Work Queue
to the signed-in username. It does NOT change the queue's date-based order, it is NOT an authorisation rule and it is
NOT the reviewer identity recorded on actions (that stays fixed at server start-up). There is no priority field."""
import base64
import io
import json
import zipfile

from smartparser.webapp import api, auth
from smartparser.webapp.server import App

from .test_ringfence_cases import R, ctx_for, err, events

PW = "correct horse battery"


def tiny_zip(tag: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("note.csv", f"a,b\n{tag},1\n")
    return b.getvalue()


def reg(ctx, customer, period="2026-09", **extra):
    body = {"customer_name": customer, "reporting_period": period, "zip_name": "s.zip",
            "zip_b64": base64.b64encode(tiny_zip(customer)).decode(), **extra}
    return R(ctx, "POST", "cases", body)


def test_registration_records_assignment_in_case_and_audit_and_no_priority(tmp_path):
    ctx = ctx_for(tmp_path)
    c = reg(ctx, "Alpha Ltd", assigned_to="analyst@example.test", priority="HIGH")   # unknown keys are ignored
    assert (c["assigned_to"], c["status"]) == ("analyst@example.test", "WAITING")
    assert "priority" not in c
    ev = events(ctx, "CASE_CREATED")[-1]["details"]
    assert ev["assigned_to"] == "analyst@example.test" and "priority" not in ev
    assert reg(ctx, "Beta Ltd")["assigned_to"] is None                              # optional


def test_invalid_assignee_is_refused(tmp_path):
    ctx = ctx_for(tmp_path)
    assert err(lambda: reg(ctx, "Alpha Ltd", assigned_to="x" * 300)) == "INVALID"
    assert R(ctx, "GET", "cases")["items"] == []


def test_legacy_case_without_the_field_reads_as_unassigned(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = reg(ctx, "Alpha Ltd")["case_ref"]
    p = ctx.cases._path(ref)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.pop("assigned_to")                                     # as written before assignment existed
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert R(ctx, "GET", "cases")["items"][0]["assigned_to"] is None


def test_mine_filter_keeps_the_date_based_order_and_the_global_slot(tmp_path):
    ctx = ctx_for(tmp_path)
    # registered out of reporting-period order on purpose: the queue orders by when the ZIP was received
    a = reg(ctx, "Alpha Ltd", period="2026-10", assigned_to="me@example.test")["case_ref"]
    reg(ctx, "Beta Ltd", assigned_to="other@example.test")
    c = reg(ctx, "Gamma Ltd", period="2026-06", assigned_to="me@example.test")["case_ref"]
    reg(ctx, "Delta Ltd")
    every = api.route(ctx, "GET", ["cases"], {}, {}, user="me@example.test")
    mine = api.route(ctx, "GET", ["cases"], {"assigned": "me"}, {}, user="me@example.test")
    assert len(every["items"]) == 4 and every["assigned_to_filter"] is None
    unfiltered_order = [x["case_ref"] for x in every["items"] if x["assigned_to"] == "me@example.test"]
    # the filter only removes rows: the order is exactly the unfiltered queue's (existing rule, oldest received first;
    # same-second registrations fall back to the case reference)
    assert [x["case_ref"] for x in mine["items"]] == unfiltered_order and set(unfiltered_order) == {a, c}
    assert mine["counts"]["WAITING"] == 2 and mine["assigned_to_filter"] == "me@example.test"
    other = [x for x in every["items"] if x["customer_name"] == "Beta Ltd"][0]["case_ref"]
    doc = ctx.cases.load(other)
    doc["status"] = "IN_PROGRESS"
    ctx.cases._save(doc)
    mine = api.route(ctx, "GET", ["cases"], {"assigned": "me"}, {}, user="me@example.test")
    assert mine["active_case_ref"] == other and other not in [x["case_ref"] for x in mine["items"]]


def test_assigned_me_needs_a_signed_in_user_and_only_accepts_me(tmp_path):
    ctx = ctx_for(tmp_path)
    assert err(lambda: api.route(ctx, "GET", ["cases"], {"assigned": "me"}, {})) == "NO_SIGNED_IN_USER"
    assert err(lambda: api.route(ctx, "GET", ["cases"], {"assigned": "bob"}, {}, user="bob")) == "INVALID"


def test_server_passes_the_session_email_through_to_the_queue(tmp_path):
    ctx = ctx_for(tmp_path)
    reg(ctx, "Alpha Ltd", assigned_to="alice@example.test")
    reg(ctx, "Beta Ltd", assigned_to="bob@example.test")
    app = App(ctx, auth.Authenticator({"alice@example.test": auth.hash_password(PW, 1000)}))
    hdr = {"X-Smartparser-Client": "webapp"}
    s, _, _, extra = app.handle_ex("POST", "/api/auth/login", hdr,
                                   json.dumps({"username": "alice@example.test", "password": PW}).encode())
    assert s == 200
    cookie = dict(extra)["Set-Cookie"].split(";")[0]
    s, _, data = app.handle("GET", "/api/cases?assigned=me", {"Cookie": cookie}, b"")
    assert s == 200 and [x["customer_name"] for x in json.loads(data)["items"]] == ["Alpha Ltd"]
    s, _, data = App(ctx).handle("GET", "/api/cases?assigned=me", {}, b"")
    assert s == 400 and json.loads(data)["error"] == "NO_SIGNED_IN_USER"


def test_assignment_is_not_an_authorisation_rule(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = reg(ctx, "Alpha Ltd", assigned_to="someone@example.test")["case_ref"]
    assert api.route(ctx, "GET", ["cases", ref], {}, {}, user="me@example.test")["case_ref"] == ref
