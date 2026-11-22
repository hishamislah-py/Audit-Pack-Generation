"""Fix8 lead hardening of D7: case-scoped POST routes fail CLOSED.

Any POST under /api/cases/{ref}/... other than the explicitly listed mutations and claim is still treated as a
restricted case mutation, so a route added later (or an unknown path) can never be reached by a non-owner: the
non-owner gets 403 NOT_CASE_OWNER + ACCESS_DENIED before the router is consulted, and nothing changes."""
from smartparser.webapp import api

from .test_fix8_C_identity_authz import ALICE, BOB, R, code, ctx, register  # noqa: F401  (ctx is a fixture)


def test_unknown_case_post_route_is_refused_for_a_non_owner_before_routing(ctx):
    ref = register(ctx, ALICE)["case_ref"]
    before = ctx.cases.load(ref)
    seq_before = len(ctx.events())
    # a POST route that does not exist (or is added later without being listed): a non-owner is refused, not routed
    assert code(lambda: R(ctx, BOB, "POST", f"cases/{ref}/some-future-mutation", {})) == "NOT_CASE_OWNER"
    after_events = ctx.events()[seq_before:]
    assert [e["event_type"] for e in after_events] == ["ACCESS_DENIED"]
    assert after_events[0]["details"]["attempted_action"] == "case/some-future-mutation"
    assert after_events[0]["actor_id"] == BOB
    assert ctx.cases.load(ref) == before                      # nothing changed
    # the owner reaches the router, which answers 404 for the unknown path (no ownership refusal)
    assert code(lambda: R(ctx, ALICE, "POST", f"cases/{ref}/some-future-mutation", {})) == "NOT_FOUND"


def test_claim_is_not_caught_by_the_fail_closed_rule(ctx):
    ref = register(ctx, ALICE)["case_ref"]
    assert api.restricted_target(ctx, "POST", ["cases", ref, "claim"]) is None
    assert api.restricted_target(ctx, "GET", ["cases", ref, "anything"]) is None
    assert api.restricted_target(ctx, "POST", ["cases", ref, "start"])[1] == "case/start"
