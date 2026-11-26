"""The ten APPROVED owner decisions (O1-O10, 19 Nov 2026) for the Ringfence case workflow, one test each, through the
application API. Offline; the reconciliation-dependent test uses the real UC-042 engine when available."""
import threading
import time

import pytest

import smartparser.webapp.context as context_module
from smartparser.webapp.cases import REASON, needs_attention

from .phase3b_support import dump, tbl
from .test_ringfence_cases import (NAMES, R, ctx_for, err, events, in05_with_extra, make_zip, new_case, settle,
                                   upload)
from .uc042_support import SEP, needs_uc042, read


def started(ctx, data=None, customer="Harbourline Payments Ltd"):
    ref = new_case(ctx, customer, data=data)["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    return ref, settle(ctx, ref)


def fail_first_validation(ctx):
    real, n = ctx.svc.validate, {"n": 0}

    def flaky(pid):
        n["n"] += 1
        if n["n"] == 1:
            raise RuntimeError("simulated technical failure")
        return real(pid)
    ctx.svc.validate = flaky


# --------------------------------------------------------------------------------------------- O1
def test_o1_retry_uses_the_original_zip_and_does_not_carry_corrections_forward(tmp_path):
    ctx = ctx_for(tmp_path)
    fail_first_validation(ctx)
    ref, d = started(ctx, make_zip(skip=("IN-03",)))
    run1 = d["runs"][0]
    assert run1["status"] == "FAILED"
    # evidence that reached the failed run (set up directly: the case API itself blocks uploads into a failed run)
    sid = R(ctx, "POST", "staging", {"name": "balances.csv", "data_b64": __import__("base64").b64encode(
        read(SEP, "IN-03")).decode()})["entries"][0]["staging_id"]
    j = ctx.start_intake(run1["package_id"], [{"staging_id": sid, "declared_category": "IN-03"}])
    while ctx.jobs[j["job_id"]]["state"] in ("queued", "running"):
        time.sleep(0.1)
    assert err(lambda: upload(ctx, ref, "balances.csv", read(SEP, "IN-03"), "IN-03")) == "RUN_FAILED"
    d = R(ctx, "POST", f"cases/{ref}/retry", {"confirm": True})
    d = settle(ctx, ref)
    run2 = d["runs"][1]
    assert run2["evidence_source"] == "ORIGINAL_ZIP" and run2["retry_of"] == run1["run_id"]
    assert [f["category"] for x in run2["not_carried_forward"] for f in x["files"]] == ["IN-03"]
    pkg2 = ctx.svc.load(run2["package_id"])
    assert len(pkg2.versions) == 16 and all(v.version_number == 1 for v in pkg2.versions.values())
    assert [m["category"] for m in d["progress"]["missing_required"]] == ["IN-03"]       # must be uploaded again
    assert ctx.svc.load(run1["package_id"]).latest("IN-03") is not None                  # kept in the failed run
    ev = events(ctx, "CASE_RETRY_REQUESTED")[-1]["details"]
    assert ev["evidence_source"] == "ORIGINAL_ZIP" and ev["not_carried_forward"]


# --------------------------------------------------------------------------------------------- O2
def test_o2_only_exact_canonical_headers_are_recognised():
    base = {"suggested_field": "amount", "duplicate_claim": None, "same_header_positions": []}
    case = "column_review_case"
    assert not needs_attention({**base, "source_header": "amount", "suggestion_basis": "deterministic"}, case)
    assert not needs_attention({**base, "source_header": "amount", "suggestion_basis": "diagnostic_name_match"}, case)
    for hdr, basis in (("Amount", "deterministic"), (" amount", "deterministic"), ("AMOUNT", "diagnostic_name_match"),
                       ("txn_amt", "proposal"), ("amount", "proposal"), ("memo", "none")):
        assert needs_attention({**base, "source_header": hdr, "suggestion_basis": basis}, case), (hdr, basis)
    assert needs_attention({**base, "source_header": "amount", "suggestion_basis": "deterministic",
                            "duplicate_claim": "amount"}, case)
    assert needs_attention({**base, "source_header": "amount", "suggestion_basis": "proposal"}, "proposal_session")


def test_o2_case_variant_header_is_sent_for_review(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, _ = started(ctx, make_zip(skip=("IN-05",)))
    r = tbl("IN-05")
    variant = r[0][0].upper() if r[0][0] != r[0][0].upper() else r[0][0].title()
    hdr = [variant] + r[0][1:] + ["memo_1"]
    upload(ctx, ref, NAMES["IN-05"], dump([hdr] + [x + ["note"] for x in r[1:]]), "IN-05")
    p = settle(ctx, ref)["progress"]
    rv = R(ctx, "GET", f"cases/{ref}/review/{p['awaiting_review'][0]['file_version_id']}")
    assert sorted(x["source_header"] for x in rv["rows"] if x["needs_attention"]) == sorted([variant, "memo_1"])
    assert rv["counts"]["recognised"] == len(r[0]) - 1


# --------------------------------------------------------------------------------------------- O3, O4
def test_o3_last_decision_does_not_confirm_and_o4_no_free_text(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, _ = started(ctx, make_zip(skip=("IN-05",)))
    upload(ctx, ref, NAMES["IN-05"], in05_with_extra(1), "IN-05")
    p = settle(ctx, ref)["progress"]
    vid = p["awaiting_review"][0]["file_version_id"]
    row = next(x for x in R(ctx, "GET", f"cases/{ref}/review/{vid}")["rows"] if x["needs_attention"])
    rv = R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "IGNORE", "source_index": row["source_index"]})
    assert rv["counts"]["remaining"] == 0 and rv["can_confirm"] and rv["version_status"] == "REVIEW_REQUIRED"
    assert ctx.svc.load(p["awaiting_review"][0] and settle(ctx, ref)["package"]["package_id"]).versions[vid] \
        .version_status == "REVIEW_REQUIRED"                                       # O3: still awaiting confirmation
    d = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    assert d["progress"]["files_awaiting_review"] == 0
    reasons = [e["details"].get("reason") for e in ctx.events() if e["event_type"] == "INTAKE_DECISION"]
    assert reasons and all(x.startswith("Ringfence analyst action ") and x.endswith(
        "(no free-text reason is captured by design)") for x in reasons)        # O4: fixed wording only
    assert REASON.format(action="X") == "Ringfence analyst action X (no free-text reason is captured by design)"
    confirmed = events(ctx, "ANALYST_REVIEW_CONFIRMED")
    assert len(confirmed) == 1 and confirmed[0]["actor_id"] == "test-analyst-1"


# --------------------------------------------------------------------------------------------- O5
def test_o5_activated_package_is_immutable(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, d = started(ctx)
    out = R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})
    assert out["activated"]
    pid = out["case"]["package"]["package_id"]
    sid = R(ctx, "POST", "staging", {"name": "x.csv", "data_b64": __import__("base64").b64encode(
        read(SEP, "IN-01")).decode()})["entries"][0]["staging_id"]
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/evidence", {"staging_id": sid, "category": "IN-18"})) == "PACKAGE_LOCKED"
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/validate")) == "PACKAGE_LOCKED"
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})) == "ALREADY_ACTIVATED"
    assert err(lambda: R(ctx, "POST", f"packages/{pid}/intake", {"items": [{"staging_id": sid}]})) == "PACKAGE_LOCKED"
    assert err(lambda: R(ctx, "POST", f"packages/{pid}/resubmit", {"category": "IN-01", "staging_id": sid,
                                                                 "reason": "x"})) == "PACKAGE_LOCKED"
    a = R(ctx, "GET", f"cases/{ref}")["actions"]
    assert not a["upload_evidence"]["enabled"] and not a["validate"]["enabled"] and not a["activate"]["enabled"]
    assert len(ctx.svc.load(pid).snapshot_ids) == 1


# --------------------------------------------------------------------------------------------- O6
def test_o6_business_outcomes_do_not_fail_the_run(tmp_path):
    ctx = ctx_for(tmp_path)
    r = tbl("IN-11")
    ref, d = started(ctx, make_zip(skip=("IN-03",), replace={"IN-11": dump([r[0], r[1][:-2]] + r[2:]),
                                                             "IN-05": in05_with_extra(1)}))
    p = d["progress"]
    assert p["missing_required"] and p["refused_uploads"] and p["correction_required"]
    assert p["validation"]["state"] == "FAILED"
    assert d["current_run"]["status"] == "COMPLETED" and d["failed_runs"] == 0
    assert not d["actions"]["retry_from_beginning"]["enabled"]
    ctx2 = ctx_for(tmp_path / "b")
    fail_first_validation(ctx2)
    _, d2 = started(ctx2)
    assert d2["current_run"]["status"] == "FAILED" and d2["current_run"]["failure"]["code"] == "INTAKE_JOB_FAILED"


# --------------------------------------------------------------------------------------------- O7
def test_o7_declared_category_is_only_a_routing_hint(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, _ = started(ctx, make_zip(skip=("IN-03", "IN-08")))
    upload(ctx, ref, "balances.csv", read(SEP, "IN-01"), "IN-03")          # IN-01 content declared as IN-03
    settle(ctx, ref)
    upload(ctx, ref, "eod.csv", read(SEP, "IN-07"), "IN-08")               # IN-07 content declared as IN-08
    d = settle(ctx, ref)
    corr = {x["category"]: x for x in d["progress"]["correction_required"]}
    assert corr["IN-03"]["version_status"] == corr["IN-08"]["version_status"] == "REJECTED"
    assert "content identifies as IN-01, not IN-03" in corr["IN-03"]["reason"]
    assert d["progress"]["categories_validated"] == 15                      # nothing accepted under a wrong category
    assert ctx.authority.scopes["CATEGORY_CONFLICT"].roles == ["data_owner"]  # an analyst cannot confirm a conflict
    assert not any("categor" in r for r in __import__("smartparser.webapp.api", fromlist=["x"]).case_route.__code__.co_consts
                   if isinstance(r, str) and r.startswith("/"))                 # no category-change route exists
    upload(ctx, ref, "balances.csv", read(SEP, "IN-03"), "IN-03")          # the genuine file is then accepted
    d = settle(ctx, ref)
    assert "IN-03" not in {x["category"] for x in d["progress"]["correction_required"]}


# --------------------------------------------------------------------------------------------- O8
def test_o8_registration_captures_customer_period_and_zip(tmp_path):
    ctx = ctx_for(tmp_path)
    c = new_case(ctx, "Northgate Money Ltd", "2026-10")
    assert (c["customer_name"], c["reporting_period"], c["zip"]["filename"], c["status"]) == \
        ("Northgate Money Ltd", "2026-10", "submission.zip", "WAITING")
    assert len(c["zip"]["sha256"]) == 64 and (ctx.root / "cases" / "zips" / f"{c['zip']['sha256']}.zip").is_file()
    assert err(lambda: new_case(ctx, "", "2026-10")) == "INVALID"
    assert err(lambda: new_case(ctx, "X Ltd", "Oct 2026")) == "INVALID"
    assert events(ctx, "CASE_CREATED")[-1]["details"]["zip_sha256"] == c["zip"]["sha256"]


# --------------------------------------------------------------------------------------------- O9
@needs_uc042
def test_o9_deferral_during_reconciliation_is_superseded_by_completion(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path, engine=True)
    gate, entered = threading.Event(), threading.Event()
    real = context_module.run_reconciliation

    def slow(*a, **k):
        entered.set()
        gate.wait(60)
        return real(*a, **k)
    monkeypatch.setattr(context_module, "run_reconciliation", slow)
    ref, _ = started(ctx)
    R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})
    R(ctx, "POST", f"cases/{ref}/reconcile")
    assert entered.wait(30)
    d = R(ctx, "POST", f"cases/{ref}/defer")
    assert d["status"] == "IN_PROGRESS" and d["deferring"]                     # reconciliation is not interrupted
    gate.set()
    d = settle(ctx, ref, 600)
    assert d["status"] == "COMPLETED" and d["completed"]["case_status"] == "CLEAN"
    assert "deferral was superseded" in d["status_history"][-1]["note"]
    assert not events(ctx, "CASE_DEFERRED")
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/resume")) == "CASE_STATE"


# --------------------------------------------------------------------------------------------- O10
def test_o10_pending_case_must_be_resumed_before_retry(tmp_path):
    ctx = ctx_for(tmp_path)
    fail_first_validation(ctx)
    ref, d = started(ctx)
    assert d["current_run"]["status"] == "FAILED"
    R(ctx, "POST", f"cases/{ref}/defer")
    d = R(ctx, "GET", f"cases/{ref}")
    assert d["status"] == "PENDING" and not d["actions"]["retry_from_beginning"]["enabled"]
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/retry", {"confirm": True})) == "CASE_NOT_ACTIVE"
    assert R(ctx, "GET", f"cases/{ref}")["status"] == "PENDING" and len(R(ctx, "GET", f"cases/{ref}")["runs"]) == 1
    R(ctx, "POST", f"cases/{ref}/resume")
    d = R(ctx, "POST", f"cases/{ref}/retry", {"confirm": True})
    assert len(d["runs"]) == 2
