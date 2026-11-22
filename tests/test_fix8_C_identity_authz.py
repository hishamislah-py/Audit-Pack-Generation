"""Fix8 Agent C - D6 (per-user identity, I-1), D7 (case ownership / authorisation, I-2) and R-P0-1 (a manually
registered case is assigned to the registering user).

Pins:
* every request runs as the signed-in user of the server-side session: case events, package events, job threads
  started by the user, case facts (started.by, run started_by, activation activated_by) and review decisions carry that
  user; system-detected events carry actor_role "system"; the identity survives a refresh and a server restart;
* a client-supplied identity field is ignored;
* only the case owner (assigned_to) may mutate a case; anybody else gets 403 NOT_CASE_OWNER + ACCESS_DENIED and the
  case / package / closure state is unchanged; a supervisor may act and every such action is SUPERVISOR_OVERRIDE;
* registration assigns the signed-in user; an unassigned (legacy) case must be claimed (CASE_ASSIGNED);
* reads stay open; --insecure-no-auth keeps working without enforcement;
* the credentials file accepts optional roles (backward compatible) and set-password keeps them."""
import base64
import json
import time

import pytest

from smartparser.webapp import api, auth, identity
from smartparser.webapp.context import AppContext
from smartparser.webapp.server import App

from .test_ringfence_cases import ANALYST, R as R_noauth, ctx_for, events, in05_with_extra, make_zip
from .uc042_support import needs_uc042

PW = "fix8-test-password"
ALICE, BOB, CAROL, SUP = "fix8.alice@ringfence.test", "fix8.bob@ringfence.test", "fix8.carol@ringfence.test", \
    "fix8.supervisor@ringfence.test"
POST_H = {"X-Smartparser-Client": "webapp"}


def make_auth():
    h = auth.hash_password(PW, 1000)
    return auth.Authenticator({u: h for u in (ALICE, BOB, CAROL, SUP)}, profiles={SUP: {"roles": ["supervisor"]}})


@pytest.fixture
def ctx(tmp_path):
    c = ctx_for(tmp_path)
    c.authenticator = make_auth()
    return c


def R(ctx, user, method, path, body=None, q=None):
    return api.route(ctx, method, [p for p in path.split("/") if p], q or {}, body or {}, user=user)


def code(fn):
    with pytest.raises(Exception) as e:
        fn()
    return api.to_http(e.value).code


def register(ctx, user, customer="Harbourline Payments Ltd", data=None, **extra):
    return R(ctx, user, "POST", "cases", {"customer_name": customer, "reporting_period": "2026-09",
                                          "zip_name": "submission.zip",
                                          "zip_b64": base64.b64encode(data if data is not None else make_zip()).decode(),
                                          **extra})


def settle(ctx, user, ref, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        d = R(ctx, user, "GET", f"cases/{ref}")
        if not d["progress"]["current_operation"] and (d["current_run"] or {}).get("status") != "PROCESSING" \
                and not d["deferring"]:
            return d
        time.sleep(0.2)
    raise AssertionError("case did not settle")


def state_of(ctx, ref) -> str:
    p = ctx.cases._path(ref)
    return p.read_text(encoding="utf-8")


# ============================================================================================ identity (D6)
def test_app_reports_the_signed_in_user_not_the_server_reviewer(ctx):
    for u in (ALICE, BOB):
        app = R(ctx, u, "GET", "app")
        assert app["reviewer"]["reviewer_id"] == u and app["user"]["username"] == u
        assert app["system_reviewer"]["reviewer_id"] == ANALYST.reviewer_id and app["authorization"]["enforced"]
    assert R(ctx, SUP, "GET", "app")["user"]["supervisor"] is True
    assert ctx.reviewer.reviewer_id == ANALYST.reviewer_id          # outside a request: the server reviewer


def test_identity_contextvar_and_reviewer_property(ctx):
    assert identity.current_actor() == (None, None)
    with identity.acting_as(ALICE):
        assert identity.current_actor() == (ALICE, "analyst")
        r = ctx.reviewer
        assert (r.reviewer_id, r.role, r.kind) == (ALICE, ANALYST.role, ANALYST.kind)
        with identity.acting_as_system():
            assert identity.current_actor() == (identity.SYSTEM_ACTOR_ID, "system")
            assert ctx.reviewer.reviewer_id == ANALYST.reviewer_id
    assert identity.current_actor() == (None, None)


def test_registration_assigns_the_signed_in_user_and_my_cases(ctx):
    c = register(ctx, ALICE)                                         # no assigned_to supplied (R-P0-1)
    assert c["assigned_to"] == ALICE and c["access"]["is_owner"]
    ev = events(ctx, "CASE_CREATED")[-1]
    assert (ev["actor_id"], ev["actor_role"], ev["details"]["assigned_to"]) == (ALICE, "analyst", ALICE)
    mine = R(ctx, ALICE, "GET", "cases", q={"assigned": "me"})
    assert [x["case_ref"] for x in mine["items"]] == [c["case_ref"]]
    assert R(ctx, BOB, "GET", "cases", q={"assigned": "me"})["items"] == []
    # an analyst cannot register a case for somebody else; a supervisor can (known users only)
    n = len(events(ctx, "ACCESS_DENIED"))
    assert code(lambda: register(ctx, BOB, "Other Ltd", assigned_to=ALICE)) == "ASSIGNMENT_NOT_PERMITTED"
    assert len(events(ctx, "ACCESS_DENIED")) == n + 1 and len(R(ctx, BOB, "GET", "cases")["items"]) == 1
    assert register(ctx, SUP, "Other Ltd", assigned_to=BOB)["assigned_to"] == BOB
    assert code(lambda: register(ctx, SUP, "Third Ltd", assigned_to="nobody@x")) == "UNKNOWN_USER"


def test_client_supplied_identity_is_ignored_over_http(tmp_path):
    ctx = ctx_for(tmp_path)
    a = make_auth()
    app = App(ctx, a)

    def H(method, path, body=None, cookie=None):
        h = dict(POST_H) if method == "POST" else {}
        if cookie:
            h["Cookie"] = cookie
        s, ct, data, extra = app.handle_ex(method, path, h, json.dumps(body or {}).encode() if method == "POST" else b"")
        return s, json.loads(data), dict(extra)

    s, _, extra = H("POST", "/api/auth/login", {"username": BOB, "password": PW})
    cookie = extra["Set-Cookie"].split(";")[0]
    s, c, _ = H("POST", "/api/cases", {"customer_name": "Spoof Ltd", "reporting_period": "2026-09",
                                      "zip_name": "s.zip", "zip_b64": base64.b64encode(make_zip()).decode(),
                                      "user": ALICE, "actor_id": ALICE, "reviewer_id": ALICE}, cookie)
    assert s == 200 and c["assigned_to"] == BOB
    assert events(ctx, "CASE_CREATED")[-1]["actor_id"] == BOB
    s, app_doc, _ = H("GET", "/api/app", cookie=cookie)               # a refresh: same identity
    assert app_doc["user"]["username"] == BOB and app_doc["reviewer"]["reviewer_id"] == BOB


# ============================================================================================ authorisation (D7)
def test_non_owner_is_refused_every_case_and_closure_mutation_without_state_change(ctx):
    c = register(ctx, ALICE)
    ref = c["case_ref"]
    before, n0 = state_of(ctx, ref), ctx.last_seq()
    sid = R(ctx, BOB, "POST", "staging", {"name": "x.csv", "data_b64": base64.b64encode(b"a,b\n1,2\n").decode()}
            )["entries"][0]["staging_id"]                            # staging is not a case mutation
    attempts = [("start", {}), ("defer", {}), ("resume", {}), ("retry", {"confirm": True}),
                ("evidence", {"staging_id": sid, "category": "IN-03"}), ("validate", {}),
                ("activate", {"confirm": True}), ("reconcile", {}),
                ("review/FV-x/decision", {"action": "IGNORE", "source_index": 0}), ("review/FV-x/confirm", {}),
                ("review/FV-x/reject", {}), ("closure/review", {"expected_revision": 0}),
                ("closure/review/selections", {"selections": [], "expected_revision": 0}),
                ("closure/review/preview", {"expected_revision": 0}),
                ("closure/review/decision", {"decision": "GENERATE", "expected_revision": 0}),
                ("closure/review/decision", {"decision": "HOLD", "expected_revision": 0}),
                ("closure/investigations/INV-x/decision", {"decision": "ACCEPT", "expected_revision": 0}),
                ("closure/exceptions/EXC-x/investigations", {"expected_revision": 0})]
    for path, body in attempts:
        assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/{path}", body)) == "NOT_CASE_OWNER", path
    denied = [e for e in ctx.events() if e["seq"] > n0]
    assert [e["event_type"] for e in denied] == ["ACCESS_DENIED"] * len(attempts)   # nothing else was recorded
    assert all(e["actor_id"] == BOB and e["details"]["case_ref"] == ref and e["details"]["assigned_to"] == ALICE
               for e in denied)
    assert [e["details"]["attempted_action"] for e in denied][:3] == ["case/start", "case/defer", "case/resume"]
    assert state_of(ctx, ref) == before                              # revision and status unchanged
    d = R(ctx, BOB, "GET", f"cases/{ref}")                           # reads stay open
    assert d["access"] == d["access"] | {"enforced": True, "owner": ALICE, "is_owner": False, "can_act": False}
    assert not any(a["enabled"] for a in d["actions"].values())
    assert all("NOT_CASE_OWNER" in a["reason"] and ALICE in a["reason"] for a in d["actions"].values())
    assert R(ctx, ALICE, "GET", f"cases/{ref}")["actions"]["start"]["enabled"]
    assert R(ctx, BOB, "GET", f"cases/{ref}/activity")["case_ref"] == ref


@needs_uc042
def test_owner_flow_actors_refusals_supervisor_override_refresh_and_restart(tmp_path):
    """Alice registers, starts, decides and confirms a review, uploads, validates, activates and reconciles; Bob is
    refused at each step (generic package/review endpoints too); the supervisor defers/resumes (override)."""
    ctx = ctx_for(tmp_path, engine=True)
    ctx.authenticator = make_auth()
    c = register(ctx, ALICE, data=make_zip(skip=("IN-03",), replace={"IN-05": in05_with_extra()}))
    ref = c["case_ref"]
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/start")) == "NOT_CASE_OWNER"
    d = R(ctx, ALICE, "POST", f"cases/{ref}/start")
    assert d["started"]["by"] == ALICE
    d = settle(ctx, ALICE, ref)
    run = d["runs"][-1]
    assert run["started_by"] == ALICE
    job = ctx.jobs[run["intake_job_id"]]
    assert job["actor"] == {"user": ALICE, "role": "analyst", "system": False, "authenticated": True}
    pid = d["package"]["package_id"]
    pk = [e for e in ctx.events() if e["details"].get("package_id") == pid]
    by = {(e["event_type"], e["actor_id"], e["actor_role"]) for e in pk}
    assert ("PACKAGE_CREATED", ALICE, "analyst") in by and ("PACKAGE_FILE_RECEIVED", ALICE, "analyst") in by
    assert not any(a == "analyst" for _, a, _ in by)                 # the old fixed "analyst" actor is gone
    assert all(r == "system" for t, a, r in by if a == "smartparser-package-service")
    # the IN-05 export with extra columns was refused in the ZIP: re-upload it with its declared category (Alice only)
    sid5 = R(ctx, ALICE, "POST", "staging", {"name": "internal_recon_records_2026-09.csv",
                                            "data_b64": base64.b64encode(in05_with_extra()).decode()}
             )["entries"][0]["staging_id"]
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/evidence", {"staging_id": sid5, "category": "IN-05"})) \
        == "NOT_CASE_OWNER"
    R(ctx, ALICE, "POST", f"cases/{ref}/evidence", {"staging_id": sid5, "category": "IN-05"})
    d = settle(ctx, ALICE, ref)
    up = [j for j in ctx.jobs.values() if j["package_id"] == pid and j["kind"] == "intake"][-1]
    assert up["actor"]["user"] == ALICE
    # review: Bob refused (case endpoint and generic review endpoint), Alice decides and confirms
    vid = d["progress"]["awaiting_review"][0]["file_version_id"]
    rv = R(ctx, BOB, "GET", f"cases/{ref}/review/{vid}")             # read open
    att = [r for r in rv["rows"] if r["needs_attention"]]
    for path, body in ((f"cases/{ref}/review/{vid}/decision", {"action": "IGNORE", "source_index": att[0]["source_index"]}),
                       (f"review/{pid}/{vid}/decision", {"action": "IGNORE", "source_index": att[0]["source_index"],
                                                         "reason": "x"}),
                       (f"cases/{ref}/review/{vid}/confirm", {}), (f"packages/{pid}/validate", {})):
        assert code(lambda: R(ctx, BOB, "POST", path, body)) == "NOT_CASE_OWNER", path
    for r in att:
        R(ctx, ALICE, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "IGNORE", "source_index": r["source_index"]})
    R(ctx, ALICE, "POST", f"cases/{ref}/review/{vid}/confirm")
    rv = R(ctx, ALICE, "GET", f"cases/{ref}/review/{vid}")
    assert all(r["decision"]["reviewer"] == ALICE for r in rv["rows"] if r.get("decision") and r["needs_attention"])
    assert events(ctx, "ANALYST_REVIEW_CONFIRMED")[-1]["actor_id"] == ALICE
    # supervisor override: defer + resume Alice's case (audited)
    n = len(events(ctx, "SUPERVISOR_OVERRIDE"))
    R(ctx, SUP, "POST", f"cases/{ref}/defer")
    R(ctx, SUP, "POST", f"cases/{ref}/resume")
    ov = events(ctx, "SUPERVISOR_OVERRIDE")[n:]
    assert [(e["actor_id"], e["actor_role"], e["details"]["attempted_action"], e["details"]["outcome"]) for e in ov] == \
        [(SUP, "supervisor", "case/defer", "COMPLETED"), (SUP, "supervisor", "case/resume", "COMPLETED")]
    assert events(ctx, "CASE_RESUMED")[-1]["actor_id"] == SUP
    # missing evidence: Bob refused, Alice uploads
    from .uc042_support import SEP, read
    sid = R(ctx, ALICE, "POST", "staging", {"name": "client_balances.csv",
                                           "data_b64": base64.b64encode(read(SEP, "IN-03")).decode()})["entries"][0]["staging_id"]
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/evidence", {"staging_id": sid, "category": "IN-03"})) \
        == "NOT_CASE_OWNER"
    assert code(lambda: R(ctx, BOB, "POST", f"packages/{pid}/intake", {"items": [{"staging_id": sid}]})) \
        == "NOT_CASE_OWNER"
    R(ctx, ALICE, "POST", f"cases/{ref}/evidence", {"staging_id": sid, "category": "IN-03"})
    d = settle(ctx, ALICE, ref)
    assert events(ctx, "ANALYST_EVIDENCE_UPLOADED")[-1]["actor_id"] == ALICE
    assert d["progress"]["validation"]["state"] == "PASSED"
    rev = R(ctx, ALICE, "GET", f"cases/{ref}")["revision"]
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/validate")) == "NOT_CASE_OWNER"
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/activate", {"confirm": True})) == "NOT_CASE_OWNER"
    assert R(ctx, ALICE, "GET", f"cases/{ref}")["revision"] == rev and not ctx.svc.load(pid).active_snapshot_id
    R(ctx, ALICE, "POST", f"cases/{ref}/validate")
    R(ctx, ALICE, "POST", f"cases/{ref}/activate", {"confirm": True})
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/reconcile")) == "NOT_CASE_OWNER"
    R(ctx, ALICE, "POST", f"cases/{ref}/reconcile")
    d = settle(ctx, ALICE, ref, 900)
    assert d["status"] == "COMPLETED" and d["activation"]["activated_by"] == ALICE
    recon = [j for j in ctx.jobs.values() if j["kind"] == "reconciliation"][-1]
    assert recon["actor"]["user"] == ALICE and recon["requested_by"] == ALICE
    done = events(ctx, "CASE_COMPLETED")[-1]
    assert (done["actor_id"], done["actor_role"]) == (identity.SYSTEM_ACTOR_ID, "system")
    expected = {"CASE_CREATED": ALICE, "CASE_STARTED": ALICE, "CASE_RUN_STARTED": ALICE, "CASE_DEFERRED": SUP,
                "CASE_RESUMED": SUP, "ANALYST_REVIEW_CONFIRMED": ALICE, "ANALYST_EVIDENCE_UPLOADED": ALICE,
                "ANALYST_VALIDATION_REQUESTED": ALICE, "ANALYST_ACTIVATION_REQUESTED": ALICE,
                "ANALYST_RECONCILIATION_REQUESTED": ALICE}

    def check(c2, user):
        act = R(c2, user, "GET", f"cases/{ref}/activity")
        assert act["chain"]["verified"]
        last = {}
        for e in reversed(act["events"]):                            # oldest first
            last[e["event_type"]] = e["actor_id"]
        assert {k: last.get(k) for k in expected} == expected
        assert all(e["actor_id"] == BOB for e in act["events"] if e["event_type"] == "ACCESS_DENIED")
        return act
    check(ctx, BOB)                                                  # anyone may read
    lines = [json.loads(x) for x in (ctx.root / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["event_type"] == "ANALYST_ACTIVATION_REQUESTED" and e["actor_id"] == ALICE for e in lines)
    c2 = AppContext(root=tmp_path / "ws", authority_path=ctx.authority_path, reviewer=ANALYST,
                    uc042_root=ctx.uc042_root)                      # server restart
    c2.authenticator = make_auth()
    check(c2, ALICE)
    assert R(c2, ALICE, "GET", f"cases/{ref}")["activation"]["activated_by"] == ALICE
    assert c2.log.verify() > 0


# ============================================================================================ claim
def _unassign(ctx, ref):
    p = ctx.cases._path(ref)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.pop("assigned_to")                                           # as registered before assignment existed
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_claim_unassigned_legacy_case_and_supervisor_reassignment(ctx):
    ref = register(ctx, ALICE)["case_ref"]
    _unassign(ctx, ref)
    d = R(ctx, BOB, "GET", f"cases/{ref}")
    assert d["access"]["can_claim"] and "unassigned" in d["actions"]["start"]["reason"]
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/start")) == "NOT_CASE_OWNER"   # claim first
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/claim", {"assigned_to": CAROL})) == "ASSIGNMENT_NOT_PERMITTED"
    d = R(ctx, BOB, "POST", f"cases/{ref}/claim")
    assert d["assigned_to"] == BOB and d["access"]["is_owner"] and d["actions"]["start"]["enabled"]
    ev = events(ctx, "CASE_ASSIGNED")[-1]
    assert (ev["actor_id"], ev["details"]["assigned_to"], ev["details"]["previous_assigned_to"], ev["details"]["how"]) \
        == (BOB, BOB, None, "CLAIM")
    n = len(events(ctx, "CASE_ASSIGNED"))
    assert R(ctx, BOB, "POST", f"cases/{ref}/claim")["assigned_to"] == BOB   # idempotent, nothing recorded
    assert len(events(ctx, "CASE_ASSIGNED")) == n
    assert code(lambda: R(ctx, ALICE, "POST", f"cases/{ref}/claim")) == "NOT_CASE_OWNER"   # owned by Bob
    assert events(ctx, "ACCESS_DENIED")[-1]["details"]["attempted_action"] == "case/claim"
    d = R(ctx, SUP, "POST", f"cases/{ref}/claim", {"assigned_to": ALICE})
    assert d["assigned_to"] == ALICE and [h["how"] for h in d["assignment_history"]] == ["CLAIM", "REASSIGN"]
    ov = events(ctx, "SUPERVISOR_OVERRIDE")[-1]
    assert (ov["actor_id"], ov["details"]["attempted_action"], ov["details"]["outcome"]) == (SUP, "case/reassign",
                                                                                            "COMPLETED")
    assert code(lambda: R(ctx, SUP, "POST", f"cases/{ref}/claim", {"assigned_to": "ghost"})) == "UNKNOWN_USER"


# ============================================================================================ no-auth harness mode
def test_insecure_no_auth_mode_keeps_working_without_enforcement(tmp_path):
    ctx = ctx_for(tmp_path)
    c = R_noauth(ctx, "POST", "cases", {"customer_name": "Harness Ltd", "reporting_period": "2026-09",
                                        "zip_name": "s.zip", "zip_b64": base64.b64encode(make_zip()).decode(),
                                        "assigned_to": "someone"})
    assert c["access"]["enforced"] is False and c["actions"]["start"]["enabled"]     # owner is someone else
    app = R_noauth(ctx, "GET", "app")
    assert app["user"] is None and app["reviewer"]["reviewer_id"] == ANALYST.reviewer_id
    assert not app["authorization"]["enforced"]
    assert code(lambda: R_noauth(ctx, "POST", f"cases/{c['case_ref']}/claim")) == "NO_SIGNED_IN_USER"
    assert events(ctx, "CASE_CREATED")[-1]["actor_id"] == ANALYST.reviewer_id
    assert not events(ctx, "ACCESS_DENIED")


# ============================================================================================ credentials file
def test_roles_in_credentials_file_backward_compatible_and_cli(tmp_path, monkeypatch, capsys):
    f = tmp_path / "auth.json"
    monkeypatch.setenv("FIX8_PW", PW)
    assert auth.main(["set-password", "--file", str(f), "--username", BOB, "--password-env", "FIX8_PW"]) == 0
    assert auth.load_profiles(f)[BOB] == {"roles": (), "reviewer_role": None}         # old format: analyst
    assert auth.main(["set-roles", "--file", str(f), "--username", BOB, "--roles", "supervisor"]) == 0
    assert auth.load_profiles(f)[BOB]["roles"] == ("supervisor",)
    assert auth.main(["set-password", "--file", str(f), "--username", BOB, "--password-env", "FIX8_PW"]) == 0
    assert auth.load_profiles(f)[BOB]["roles"] == ("supervisor",)                      # set-password keeps roles
    a = auth.Authenticator.from_file(f)
    assert a.profile(BOB)["roles"] == ("supervisor",) and a.login(BOB, PW)
    assert auth.main(["set-roles", "--file", str(f), "--username", BOB, "--roles", "root"]) == 2
    assert auth.main(["set-roles", "--file", str(f), "--username", "ghost", "--roles", "supervisor"]) == 2
    assert auth.main(["set-roles", "--file", str(f), "--username", BOB, "--roles", ""]) == 0
    assert "roles" not in json.loads(f.read_text(encoding="utf-8"))["users"][0]
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["users"][0]["roles"] = ["admin"]
    f.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(auth.AuthConfigError):
        auth.Authenticator.from_file(f)
    out = capsys.readouterr()
    assert PW not in out.out + out.err
