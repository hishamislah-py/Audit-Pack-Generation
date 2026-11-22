"""Ringfence case workflow (smartparser.webapp.cases), driven through the application API handler.

Pins the confirmed decisions: WAITING / IN_PROGRESS / PENDING / COMPLETED; several cases per period; one active case;
explicit start, defer and resume (opening never changes state); a running operation finishes and persists before a
deferral completes; partial decisions survive deferral and a restart and only the remaining ones are presented; missing
and to-be-corrected evidence after resumption; oldest-first ordering with analyst override; failed runs kept, a fresh
retry is a new run of the whole ZIP from stage one in a new package; COMPLETED only after reconciliation, with no change
afterwards. Analyst decisions carry no free-text reason (a fixed generated wording is recorded)."""
import base64
import io
import threading
import time
import zipfile

import pytest

from smartparser.review.authority import Reviewer
from smartparser.webapp import api
from smartparser.webapp.context import AppContext

from .phase3b_support import TEST_POLICY, dump, tbl
from .uc042_support import SEP, UC042_ROOT, needs_uc042, read

ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")
REQUIRED = [f"IN-{i:02d}" for i in range(1, 18)]
NAMES = {"IN-05": "internal_recon_records_2026-09.csv", "IN-11": "transactions_2026-09.csv"}


def name(fid):
    return NAMES.get(fid, f"f_{fid}" + (".pdf" if fid in ("IN-15", "IN-16", "IN-17") else ".csv"))


def make_zip(skip=(), replace=None) -> bytes:
    replace = replace or {}
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for f in REQUIRED:
            if f not in skip:
                z.writestr(f"submission/{name(f)}", replace.get(f, read(SEP, f)))
    return b.getvalue()


def in05_with_extra(n=2) -> bytes:
    r = tbl("IN-05")
    extra = [f"memo_{k}" for k in range(1, n + 1)]
    return dump([r[0] + extra] + [x + ["note"] * n for x in r[1:]])


def ctx_for(tmp_path, engine=False) -> AppContext:
    return AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST,
                      uc042_root=UC042_ROOT if engine else None)


def R(ctx, method, path, body=None, q=None):
    return api.route(ctx, method, [p for p in path.split("/") if p], q or {}, body or {})


def err(fn):
    with pytest.raises(api.HttpError) as e:
        try:
            fn()
        except api.HttpError:
            raise
        except Exception as exc:
            raise api.to_http(exc)
    return e.value.code


def new_case(ctx, customer="Harbourline Payments Ltd", period="2026-09", data=None):
    return R(ctx, "POST", "cases", {"customer_name": customer, "reporting_period": period, "zip_name": "submission.zip",
                                    "zip_b64": base64.b64encode(data if data is not None else make_zip()).decode()})


def settle(ctx, ref, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        d = R(ctx, "GET", f"cases/{ref}")
        if not d["progress"]["current_operation"] and (d["current_run"] or {}).get("status") != "PROCESSING" \
                and not d["deferring"]:
            return d
        time.sleep(0.2)
    raise AssertionError("case did not settle")


def events(ctx, *types):
    return [e for e in ctx.events() if e["event_type"] in types]


# ----------------------------------------------------------------------------------------------------- 1, 3, 9
def test_several_cases_per_period_and_opening_never_changes_state(tmp_path):
    ctx = ctx_for(tmp_path)
    a, b = new_case(ctx, "Harbourline Payments Ltd"), new_case(ctx, "Northgate Money Ltd")
    c = new_case(ctx, "Harbourline Payments Ltd")                    # even a second case for the same customer/period
    assert [x["status"] for x in (a, b, c)] == ["WAITING"] * 3
    assert len({a["case_ref"], b["case_ref"], c["case_ref"]}) == 3
    assert a["zip"]["sha256"] == b["zip"]["sha256"] and a["zip"]["size"] > 0
    for _ in range(3):                                              # opening does not start Smart Parsing
        d = R(ctx, "GET", f"cases/{a['case_ref']}")
    assert d["status"] == "WAITING" and d["runs"] == [] and d["package"] is None
    assert d["actions"]["start"]["enabled"] and not d["actions"]["resume"]["enabled"]
    assert ctx.svc.store.list() == []                               # no package exists before the explicit start
    assert err(lambda: new_case(ctx, data=b"not a zip")) == "NOT_A_ZIP"


# ----------------------------------------------------------------------------------------------------- 2, 3, 4, 9
def test_explicit_start_one_active_case_defer_and_explicit_resume(tmp_path):
    ctx = ctx_for(tmp_path)
    a, b = new_case(ctx), new_case(ctx, "Northgate Money Ltd")
    s = R(ctx, "POST", f"cases/{a['case_ref']}/start")
    assert s["status"] == "IN_PROGRESS" and s["current_run"]["run_no"] == 1 and s["started"]["by"] == "test-analyst-1"
    assert err(lambda: R(ctx, "POST", f"cases/{b['case_ref']}/start")) == "ACTIVE_CASE_EXISTS"
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/start")) == "CASE_STATE"
    d = settle(ctx, a["case_ref"])
    assert d["current_run"]["status"] == "COMPLETED" and d["progress"]["categories_processed"] == 17
    d = R(ctx, "POST", f"cases/{a['case_ref']}/defer")             # idle: immediate
    assert d["status"] == "PENDING" and not d["deferring"]
    for _ in range(2):                                              # opening a PENDING case does not resume it
        assert R(ctx, "GET", f"cases/{a['case_ref']}")["status"] == "PENDING"
    assert R(ctx, "GET", "cases")["active_case_ref"] is None
    R(ctx, "POST", f"cases/{b['case_ref']}/start")                  # the slot was released
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/resume")) == "ACTIVE_CASE_EXISTS"
    settle(ctx, b["case_ref"])
    R(ctx, "POST", f"cases/{b['case_ref']}/defer")
    d = R(ctx, "POST", f"cases/{a['case_ref']}/resume")
    assert d["status"] == "IN_PROGRESS"
    assert [h["status"] for h in d["status_history"]] == ["WAITING", "IN_PROGRESS", "PENDING", "IN_PROGRESS"]
    assert [e["event_type"] for e in events(ctx, "CASE_STARTED", "CASE_DEFERRED", "CASE_RESUMED")
            if e["details"]["case_ref"] == a["case_ref"]] == ["CASE_STARTED", "CASE_DEFERRED", "CASE_RESUMED"]
    assert all(e["actor_id"] == "test-analyst-1" for e in events(ctx, "CASE_STARTED", "CASE_RESUMED"))


# ----------------------------------------------------------------------------------------------------- 5, 6
def test_deferral_waits_for_the_running_operation_and_keeps_its_results(tmp_path):
    ctx = ctx_for(tmp_path)
    gate, entered = threading.Event(), threading.Event()
    real = ctx.staged

    def slow_staged(sid):                       # the job thread reads each staged file outside the lock: hold it there
        if threading.current_thread() is not threading.main_thread():
            entered.set()
            gate.wait(30)
        return real(sid)
    ctx.staged = slow_staged
    a, b = new_case(ctx), new_case(ctx, "Northgate Money Ltd")
    R(ctx, "POST", f"cases/{a['case_ref']}/start")
    assert entered.wait(10)
    d = R(ctx, "POST", f"cases/{a['case_ref']}/defer")
    assert d["status"] == "IN_PROGRESS" and d["deferring"]                  # not interrupted halfway
    assert d["deferral"]["waiting_for"][0]["kind"] == "intake"
    assert not d["actions"]["validate"]["enabled"] and not d["actions"]["defer"]["enabled"]
    assert err(lambda: R(ctx, "POST", f"cases/{b['case_ref']}/start")) == "ACTIVE_CASE_EXISTS"
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/validate")) == "CASE_DEFERRING"
    gate.set()                                                              # the operation completes normally
    d = settle(ctx, a["case_ref"])
    assert d["status"] == "PENDING" and not d["deferring"]
    job = ctx.jobs[d["runs"][-1]["intake_job"]["job_id"]]
    assert job["state"] == "completed" and all(f["state"] == "done" for f in job["files"]) and job["validation"]
    assert d["progress"]["categories_processed"] == 17                     # its results were persisted
    order = [e["event_type"] for e in events(ctx, "CASE_DEFERRAL_REQUESTED", "PACKAGE_VALIDATED",
                                                  "PACKAGE_VALIDATION_FAILED", "CASE_DEFERRED")]
    assert order.index("CASE_DEFERRAL_REQUESTED") < order.index("CASE_DEFERRED")
    assert any(t.startswith("PACKAGE_VALID") for t in order[order.index("CASE_DEFERRAL_REQUESTED"):
                                                             order.index("CASE_DEFERRED")])
    R(ctx, "POST", f"cases/{b['case_ref']}/start")                          # slot released only now


# ----------------------------------------------------------------------------------------------------- 7, 8, 10
def upload(ctx, ref, filename, data, category):
    sid = R(ctx, "POST", "staging", {"name": filename, "data_b64": base64.b64encode(data).decode()}
            )["entries"][0]["staging_id"]
    return R(ctx, "POST", f"cases/{ref}/evidence", {"staging_id": sid, "category": category})


def test_partial_review_survives_deferral_and_restart_and_only_remaining_items_are_shown(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx, data=make_zip(skip=("IN-03",), replace={"IN-05": in05_with_extra(2)}))
    R(ctx, "POST", f"cases/{a['case_ref']}/start")
    p = settle(ctx, a["case_ref"])["progress"]
    # in a ZIP nothing is declared: the IN-05 export with two extra columns is not identified and is reported as a
    # refused upload (never as processed); IN-03 is genuinely missing
    assert [m["category"] for m in p["missing_required"]] == ["IN-03", "IN-05"]
    assert [(u["filename"], u["evidence_category"]) for u in p["refused_uploads"]] == [(NAMES["IN-05"], None)]
    upload(ctx, a["case_ref"], NAMES["IN-05"], in05_with_extra(2), "IN-05")      # re-upload with a declared category
    p = settle(ctx, a["case_ref"])["progress"]
    assert [m["category"] for m in p["missing_required"]] == ["IN-03"]
    assert p["files_awaiting_review"] == 1 and p["decisions_outstanding"] == 2
    vid = p["awaiting_review"][0]["file_version_id"]
    rv = R(ctx, "GET", f"cases/{a['case_ref']}/review/{vid}")
    att = [r for r in rv["rows"] if r["needs_attention"]]
    assert [r["source_header"] for r in att] == ["memo_1", "memo_2"]         # only columns needing the analyst
    assert rv["counts"] == {"attention": 2, "decided": 0, "remaining": 2, "recognised": 19}
    assert att[0]["available_actions"] == ["CHANGE", "IGNORE"] and att[0]["samples"]
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/review/{vid}/decision",
                         {"action": "LEAVE_UNRESOLVED", "source_index": att[0]["source_index"]})) == "UNSUPPORTED_ACTION"
    rv = R(ctx, "POST", f"cases/{a['case_ref']}/review/{vid}/decision",       # no reason field is sent
           {"action": "IGNORE", "source_index": att[0]["source_index"]})
    assert rv["counts"]["remaining"] == 1 and not rv["can_confirm"]
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/review/{vid}/confirm")) == "DECISIONS_OUTSTANDING"
    before = R(ctx, "GET", f"cases/{a['case_ref']}")["progress"]
    R(ctx, "POST", f"cases/{a['case_ref']}/defer")
    ctx2 = ctx_for(tmp_path)                                                # server restart
    d = R(ctx2, "GET", f"cases/{a['case_ref']}")
    assert d["status"] == "PENDING"
    d = R(ctx2, "POST", f"cases/{a['case_ref']}/resume")
    assert {k: d["progress"][k] for k in ("decisions_outstanding", "decisions_made", "categories_processed")} == \
        {k: before[k] for k in ("decisions_outstanding", "decisions_made", "categories_processed")} == \
        {"decisions_outstanding": 1, "decisions_made": 1, "categories_processed": 16}
    assert [m["category"] for m in d["progress"]["missing_required"]] == ["IN-03"]   # highlighted after resumption
    assert d["actions"]["upload_evidence"]["enabled"]
    rv = R(ctx2, "GET", f"cases/{a['case_ref']}/review/{vid}")
    remaining = [r for r in rv["rows"] if r["needs_attention"] and not r["decided"]]
    assert [r["source_header"] for r in remaining] == ["memo_2"]
    done = next(r for r in rv["rows"] if r["source_header"] == "memo_1")
    assert done["decision"]["action"] == "IGNORE" and done["decision"]["reviewer"] == "test-analyst-1"
    R(ctx2, "POST", f"cases/{a['case_ref']}/review/{vid}/decision", {"action": "IGNORE",
                                                                    "source_index": remaining[0]["source_index"]})
    d = R(ctx2, "POST", f"cases/{a['case_ref']}/review/{vid}/confirm")      # recognised columns confirmed with the file
    assert d["progress"]["files_awaiting_review"] == 0
    assert ctx2.svc.load(d["package"]["package_id"]).versions[vid].version_status == "VALIDATED"
    reasons = [e["details"].get("reason") or "" for e in ctx2.events() if e["event_type"] == "INTAKE_DECISION"]
    assert reasons and all("no free-text reason" in r for r in reasons)
    # upload the missing category: processed, earlier work untouched
    vids_before = {s["evidence_category"]: (s["latest"] or {}).get("file_version_id") for s in d["package"]["slots"]}
    sid = R(ctx2, "POST", "staging", {"name": "client_balances.csv",
                                     "data_b64": base64.b64encode(read(SEP, "IN-03")).decode()})["entries"][0]["staging_id"]
    R(ctx2, "POST", f"cases/{a['case_ref']}/evidence", {"staging_id": sid, "category": "IN-03"})
    d = settle(ctx2, a["case_ref"])
    assert d["progress"]["missing_required"] == [] and d["progress"]["validation"]["state"] == "PASSED"
    after = {s["evidence_category"]: (s["latest"] or {}).get("file_version_id") for s in d["package"]["slots"]}
    assert all(after[k] == v for k, v in vids_before.items() if v)


def test_correction_is_distinguished_from_missing_and_file_reject_requests_it(tmp_path):
    ctx = ctx_for(tmp_path)
    r = tbl("IN-11")
    short = dump([r[0], r[1][:-2]] + r[2:])                                   # malformed row -> FAILED_VALIDATION
    a = new_case(ctx, data=make_zip(skip=("IN-03", "IN-05"), replace={"IN-11": short}))
    R(ctx, "POST", f"cases/{a['case_ref']}/start")
    settle(ctx, a["case_ref"])
    upload(ctx, a["case_ref"], NAMES["IN-05"], in05_with_extra(1), "IN-05")
    p = settle(ctx, a["case_ref"])["progress"]
    assert [m["category"] for m in p["missing_required"]] == ["IN-03"]
    assert [(x["category"], x["version_status"]) for x in p["correction_required"]] == [("IN-11", "FAILED_VALIDATION")]
    vid = p["awaiting_review"][0]["file_version_id"]
    d = R(ctx, "POST", f"cases/{a['case_ref']}/review/{vid}/reject")         # file-level: request a corrected file
    corr = {x["category"]: x["version_status"] for x in d["progress"]["correction_required"]}
    assert corr == {"IN-05": "REJECTED", "IN-11": "FAILED_VALIDATION"}
    assert d["progress"]["validation"]["state"] == "FAILED"                  # validation ran automatically
    sid = R(ctx, "POST", "staging", {"name": "tx.csv", "data_b64": base64.b64encode(read(SEP, "IN-11")).decode()}
            )["entries"][0]["staging_id"]
    R(ctx, "POST", f"cases/{a['case_ref']}/evidence", {"staging_id": sid, "category": "IN-11"})
    d = settle(ctx, a["case_ref"])
    slot = next(s for s in d["package"]["slots"] if s["evidence_category"] == "IN-11")
    assert slot["versions"] == 2 and slot["latest"]["version_status"] == "VALIDATED"
    sid = R(ctx, "POST", "staging", {"name": "again.csv", "data_b64": base64.b64encode(read(SEP, "IN-01")).decode()}
            )["entries"][0]["staging_id"]
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/evidence",
                         {"staging_id": sid, "category": "IN-01"})) == "EVIDENCE_NOT_ACCEPTED"


# ----------------------------------------------------------------------------------------------------- 11
def test_queue_oldest_waiting_and_pending_first_with_analyst_override(tmp_path):
    ctx = ctx_for(tmp_path)
    refs = []
    for cust in ("Alpha Pay", "Bravo Pay", "Charlie Pay"):
        refs.append(new_case(ctx, cust)["case_ref"])
        time.sleep(1.05)                                                     # distinct attach times (1 s resolution)
    R(ctx, "POST", f"cases/{refs[2]}/start")                                 # the analyst picks the NEWEST case
    q = R(ctx, "GET", "cases")
    assert [x["case_ref"] for x in q["items"]] == [refs[2], refs[0], refs[1]]
    assert q["counts"] == {"WAITING": 2, "IN_PROGRESS": 1, "PENDING": 0, "COMPLETED": 0}
    settle(ctx, refs[2])
    R(ctx, "POST", f"cases/{refs[2]}/defer")
    q = R(ctx, "GET", "cases")
    assert [(x["case_ref"], x["status"]) for x in q["items"]] == [(refs[0], "WAITING"), (refs[1], "WAITING"),
                                                                 (refs[2], "PENDING")]
    assert [x["case_ref"] for x in R(ctx, "GET", "cases", q={"status": "PENDING"})["items"]] == [refs[2]]
    item = q["items"][2]["progress"]
    assert item["summary"][0] == "17 of 19 evidence categories processed" and item["last_activity_at"]


# ----------------------------------------------------------------------------------------------------- 12-15
def test_failed_run_is_kept_and_retry_starts_a_new_run_from_the_beginning(tmp_path):
    ctx = ctx_for(tmp_path)
    real, calls = ctx.svc.validate, {"n": 0}

    def flaky(pid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated validation crash")
        return real(pid)
    ctx.svc.validate = flaky
    a = new_case(ctx)
    R(ctx, "POST", f"cases/{a['case_ref']}/start")
    d = settle(ctx, a["case_ref"])
    run1 = d["runs"][0]
    assert d["status"] == "IN_PROGRESS" and run1["status"] == "FAILED"
    assert run1["failure"]["code"] == "INTAKE_JOB_FAILED" and "simulated validation crash" in run1["failure"]["message"]
    assert run1["intake_job"]["trace"]                                        # the log is kept
    assert d["actions"]["retry_from_beginning"]["enabled"] and not d["actions"]["validate"]["enabled"]
    assert a["case_ref"] in [x["case_ref"] for x in R(ctx, "GET", "cases")["items"]]
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/validate")) == "RUN_FAILED"
    assert err(lambda: R(ctx, "POST", f"cases/{a['case_ref']}/retry", {})) == "CONFIRMATION_REQUIRED"
    pkg1 = ctx.svc.load(run1["package_id"])
    v1 = sorted(pkg1.versions)
    d = R(ctx, "POST", f"cases/{a['case_ref']}/retry", {"confirm": True})
    d = settle(ctx, a["case_ref"])
    run2 = d["runs"][1]
    assert run2["run_id"] != run1["run_id"] and run2["retry_of"] == run1["run_id"] and run2["run_no"] == 2
    assert run2["package_id"] != run1["package_id"] and run2["status"] == "COMPLETED"
    assert run2["staged_entries"] == 17 and len(run2["intake_job"]["files"]) == 17   # every entry, from stage one
    pkg2 = ctx.svc.load(run2["package_id"])
    assert len(pkg2.versions) == 17 and not set(pkg2.versions) & set(pkg1.versions)     # every file re-processed
    assert {v.intake_id for v in pkg2.versions.values()}.isdisjoint({v.intake_id for v in pkg1.versions.values()})
    assert d["progress"]["validation"]["state"] == "PASSED" and d["actions"]["activate"]["enabled"]
    # the failed run stays inspectable and read-only
    old = R(ctx, "GET", f"cases/{a['case_ref']}/runs/{run1['run_id']}")
    assert old["status"] == "FAILED" and old["failure"]["code"] == "INTAKE_JOB_FAILED"
    assert sorted(ctx.svc.load(run1["package_id"]).versions) == v1
    assert err(lambda: R(ctx, "POST", f"packages/{run1['package_id']}/validate")) == "PACKAGE_SUPERSEDED"
    assert [e["event_type"] for e in events(ctx, "CASE_RUN_FAILED", "CASE_RETRY_REQUESTED", "CASE_RUN_STARTED")] == \
        ["CASE_RUN_STARTED", "CASE_RUN_FAILED", "CASE_RETRY_REQUESTED", "CASE_RUN_STARTED"]


def test_unreadable_zip_fails_the_run_at_the_read_stage(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx, data=b"PK\x03\x04 truncated archive")
    d = R(ctx, "POST", f"cases/{a['case_ref']}/start")
    assert d["current_run"]["status"] == "FAILED" and d["current_run"]["failure"]["code"] == "INVALID_ZIP"
    assert d["actions"]["retry_from_beginning"]["enabled"]
    d = R(ctx, "POST", f"cases/{a['case_ref']}/retry", {"confirm": True})
    assert [r["status"] for r in d["runs"]] == ["FAILED", "FAILED"] and d["runs"][1]["run_id"] != d["runs"][0]["run_id"]


def test_generic_package_routes_are_guarded_for_case_packages_only(tmp_path):
    ctx = ctx_for(tmp_path)
    a = new_case(ctx)
    R(ctx, "POST", f"cases/{a['case_ref']}/start")
    pid = settle(ctx, a["case_ref"])["package"]["package_id"]
    R(ctx, "POST", f"cases/{a['case_ref']}/defer")
    assert err(lambda: R(ctx, "POST", f"packages/{pid}/validate")) == "CASE_NOT_ACTIVE"
    other = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})["package_id"]   # no case: unaffected
    assert R(ctx, "POST", f"packages/{other}/validate")["result"]["passed"] is False


# ----------------------------------------------------------------------------------------------------- 16, 17
@needs_uc042
def test_completed_only_after_reconciliation_and_nothing_changes_afterwards(tmp_path):
    ctx = ctx_for(tmp_path, engine=True)
    a = new_case(ctx)
    ref = a["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref)
    assert d["actions"]["activate"]["enabled"] and not d["actions"]["reconcile"]["enabled"]
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/activate", {})) == "CONFIRMATION_REQUIRED"
    out = R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})
    assert out["activated"] and out["case"]["status"] == "IN_PROGRESS"           # activation does not complete
    sid = R(ctx, "POST", "staging", {"name": "x.csv", "data_b64": base64.b64encode(b"a,b\n1,2\n").decode()}
            )["entries"][0]["staging_id"]
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/evidence", {"staging_id": sid})) == "PACKAGE_LOCKED"
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})) == "ALREADY_ACTIVATED"
    R(ctx, "POST", f"cases/{ref}/reconcile")
    d = settle(ctx, ref, 600)
    assert d["status"] == "COMPLETED" and d["completed"]["case_status"] == "CLEAN"
    assert d["status_history"][-1]["status"] == "COMPLETED"
    pid = d["package"]["package_id"]
    for path, body in ((f"cases/{ref}/validate", {}), (f"cases/{ref}/activate", {"confirm": True}),
                       (f"cases/{ref}/reconcile", {}), (f"cases/{ref}/evidence", {"staging_id": sid}),
                       (f"packages/{pid}/validate", {}), (f"packages/{pid}/reconcile", {"snapshot_id": "x"})):
        assert err(lambda: R(ctx, "POST", path, body)) == "CASE_COMPLETED", path
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/defer")) == "CASE_STATE"
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/resume")) == "CASE_STATE"
    assert not any(a["enabled"] for a in d["actions"].values())
    actors = {e["event_type"]: e["actor_id"] for e in ctx.events()}
    assert actors["ANALYST_ACTIVATION_REQUESTED"] == actors["ANALYST_RECONCILIATION_REQUESTED"] == "test-analyst-1"
    assert ctx.log.verify() > 0


# ----------------------------------------------------------------------------------------------------- 7 (proposal path)
def test_proposal_review_partial_decisions_survive_and_ai_proposals_can_be_changed(tmp_path):
    """Recorded LLM fixture (offline): an AI-proposed mapping is reviewed column by column; only Map and Change exist in
    a proposal review; partial decisions survive deferral; the analyst can change a proposal."""
    from pathlib import Path
    fx = Path(__file__).parent / "fixtures" / "recorded_llm" / "in10_ambiguous.json"
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None, recorded=[fx])
    a = new_case(ctx, data=make_zip(skip=("IN-10",)))
    ref = a["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    settle(ctx, ref)
    r = tbl("IN-10")
    ren = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt", "amount": "txn_amt"}
    upload(ctx, ref, "cashbook.csv", dump([[ren.get(c, c) for c in r[0]]] + r[1:]), "IN-10")
    p = settle(ctx, ref)["progress"]
    vid = p["awaiting_review"][0]["file_version_id"]
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "PROPOSAL_REVIEW" and rv["counts"]["remaining"] == 4
    rows = {x["source_header"]: x for x in rv["rows"] if x["needs_attention"]}
    assert rows["entry_ref"]["available_actions"] == ["MAP", "CHANGE"]                 # no IGNORE in a proposal review
    assert rows["txn_amt"]["financial"] and rows["txn_amt"]["suggestion_basis"] == "proposal"
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "MAP", "source_index": rows["acct_no"]["source_index"]})
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "CHANGE", "canonical_field": "ledger_entry_id",
                                                         "source_index": rows["entry_ref"]["source_index"]})
    R(ctx, "POST", f"cases/{ref}/defer")
    ctx2 = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None, recorded=[fx])
    R(ctx2, "POST", f"cases/{ref}/resume")
    rv = R(ctx2, "GET", f"cases/{ref}/review/{vid}")
    dec = {x["source_header"]: x["decision"] for x in rv["rows"] if x["decided"]}
    assert dec["acct_no"]["action"] == "MAP" and dec["entry_ref"]["canonical_field"] == "ledger_entry_id"
    assert sorted(x["source_header"] for x in rv["rows"] if x["needs_attention"] and not x["decided"]) == \
        ["posting_dt", "txn_amt"]
    for h in ("posting_dt", "txn_amt"):
        x = next(y for y in rv["rows"] if y["source_header"] == h)
        R(ctx2, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "CHANGE", "source_index": x["source_index"],
                                                              "canonical_field": {"posting_dt": "posted_ts",
                                                                                  "txn_amt": "amount"}[h]})
    d = R(ctx2, "POST", f"cases/{ref}/review/{vid}/confirm")
    assert d["progress"]["files_awaiting_review"] == 0 and d["progress"]["validation"]["state"] == "PASSED"
    assert len(ctx2.stub.calls) == 0 and len(ctx.stub.calls) == 1                       # no new proposal after restart
