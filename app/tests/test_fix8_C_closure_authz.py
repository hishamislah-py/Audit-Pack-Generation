"""Fix8 Agent C - D7 on the closure workflow, with the real engine and closure library (test-double AI investigator,
as in test_closure_service). Alice owns a reconciled case with exceptions; Bob (analyst) is refused every closure
mutation - investigation retry, AI-finding decision, open review, selections, preview, HOLD, GENERATE - with 403
NOT_CASE_OWNER + ACCESS_DENIED, the closure revision unchanged and no final pack; the system jobs (audit pack,
automatic investigations) still run; a supervisor's preview is an audited override; Alice generates the final pack and
it is authorised by her."""
import json

from smartparser.webapp import api, auth

from .test_closure_service import (R, code_of, ctx_for, needs_closure, reconcile, scenario_zip, wait_closure,
                                   wait_job, tmp_path)  # noqa: F401  (tmp_path: the short-path fixture)
from .test_ringfence_cases import events

PW = "fix8-test-password"
ALICE, BOB, SUP = "fix8.alice@ringfence.test", "fix8.bob@ringfence.test", "fix8.supervisor@ringfence.test"


def make_auth():
    h = auth.hash_password(PW, 1000)
    return auth.Authenticator({u: h for u in (ALICE, BOB, SUP)}, profiles={SUP: {"roles": ["supervisor"]}})


@needs_closure
def test_closure_mutations_owner_only_supervisor_override_and_system_jobs(tmp_path):
    data, customer, period = scenario_zip("scenario_2")
    ctx = ctx_for(tmp_path)
    ctx.authenticator = make_auth()
    from . import test_closure_service as T
    orig = T.USER
    T.R.__defaults__ = (None, None, ALICE)                          # reconcile() as Alice (the registering owner)
    try:
        ref = reconcile(ctx, data, customer, period)
    finally:
        T.R.__defaults__ = (None, None, orig)
    assert ctx.cases.load(ref)["assigned_to"] == ALICE
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING", "INVESTIGATING"))
    # system jobs ran: audit pack + automatic investigations (authorised by the user who started reconciliation)
    assert v["pack"]["status"] == "GENERATED"
    auto = [e for e in ctx.events() if e["event_type"] == "AI_AUTHORIZED"]
    assert auto and auto[0]["details"]["authorized_by"] == ALICE and auto[0]["details"]["kind"] == "AUTO_INVESTIGATION"
    assert (auto[0]["actor_id"], auto[0]["actor_role"]) == ("ringfence-closure-service", "system")   # Fix8 B (lead item 1)
    pub = [x for x in v["exceptions"] if x["ai_state"] == "PUBLISHED"]
    assert pub, [(x["exception_id"], x["ai_state"]) for x in v["exceptions"]]
    # Bob reads the closure; every action is disabled with the owner reason
    vb = R(ctx, "GET", f"cases/{ref}/closure", user=BOB)
    assert vb["access"]["owner"] == ALICE and not vb["access"]["can_act"]
    assert not any(a["enabled"] for a in vb["actions"].values())
    assert all("NOT_CASE_OWNER" in a["reason"] for a in vb["actions"].values())
    ws = R(ctx, "GET", f"cases/{ref}/closure/exceptions/{pub[0]['exception_id']}", user=BOB)
    assert not ws["decision"]["actions"]["accept"]["enabled"]
    assert R(ctx, "GET", f"cases/{ref}/closure", user=ALICE)["actions"]["preview"]["enabled"] is not None
    rev, n0 = v["revision"], len(ctx.events())
    case_before = ctx.cases._path(ref).read_text(encoding="utf-8")
    attempts = [(f"exceptions/{pub[0]['exception_id']}/investigations", {"expected_revision": rev}),
                (f"investigations/{pub[0]['investigation_id']}/decision", {"decision": "ACCEPT", "expected_revision": rev}),
                ("review", {"expected_revision": rev}),
                ("review/selections", {"expected_revision": rev, "selections": [
                    {"exception_id": pub[0]["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST"}]}),
                ("review/preview", {"confirm_ai": True, "expected_revision": rev}),
                ("review/decision", {"decision": "HOLD", "expected_revision": rev}),
                ("review/decision", {"decision": "GENERATE", "acknowledgement_accepted": True, "expected_revision": rev})]
    for path, body in attempts:
        assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/{path}", body, user=BOB)) == "NOT_CASE_OWNER", path
    new = ctx.events()[n0:]
    assert [e["event_type"] for e in new] == ["ACCESS_DENIED"] * len(attempts)
    assert all(e["actor_id"] == BOB and e["details"]["case_ref"] == ref for e in new)
    assert [e["details"]["attempted_action"] for e in new][-1] == "case/closure/review/decision"
    after = R(ctx, "GET", f"cases/{ref}/closure", user=ALICE)
    assert after["revision"] == rev and after["final_pack"] is None and after["review"].get("review_id") is None
    assert ctx.cases._path(ref).read_text(encoding="utf-8") == case_before
    # Alice decides every published finding; the supervisor requests the preview (audited override)
    for x in after["exceptions"]:
        if x["ai_state"] == "PUBLISHED":
            after = R(ctx, "POST", f"cases/{ref}/closure/investigations/{x['investigation_id']}/decision",
                      {"decision": "ACCEPT", "expected_revision": after["revision"]}, user=ALICE)["closure"]
        else:
            R(ctx, "POST", f"cases/{ref}/closure/review/selections", {"expected_revision": after["revision"],
              "selections": [{"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST"}]}, user=ALICE)
            after = R(ctx, "GET", f"cases/{ref}/closure", user=ALICE)
    assert all(e["actor_id"] == ALICE for e in ctx.events() if e["event_type"] == "ANALYST_INVESTIGATION_ACCEPTED")
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"confirm_ai": True,
                                                                "expected_revision": after["revision"]}, user=SUP)
    ov = events(ctx, "SUPERVISOR_OVERRIDE")[-1]
    assert (ov["actor_id"], ov["actor_role"], ov["details"]["attempted_action"], ov["details"]["outcome"]) == \
        (SUP, "supervisor", "case/closure/review/preview", "COMPLETED")
    assert events(ctx, "CLOSING_PREVIEW_REQUESTED")[-1]["actor_id"] == SUP
    if pv.get("job_id"):
        assert wait_job(ctx, pv["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure", user=ALICE)
    cur = v["review"]["current_preview"]
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": True, "snapshot_sha256": cur["snapshot_sha256"],
        "expected_revision": v["revision"]}, user=BOB)) == "NOT_CASE_OWNER"
    out = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": True, "snapshot_sha256": cur["snapshot_sha256"],
        "expected_revision": v["revision"]}, user=ALICE)
    assert wait_job(ctx, out["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure", user=BOB)
    assert v["frozen"] and v["final_pack"]["authorised_by"] == ALICE
    final = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/json", user=BOB)[1])   # reads open
    assert final["human_review"]["reviewer"]["user_id"] == ALICE
    assert ctx.log.verify() > 0
