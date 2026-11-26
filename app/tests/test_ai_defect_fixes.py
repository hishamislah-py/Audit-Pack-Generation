"""DEF-SV-01 (proposal dedup identity) and DEF-SV-02 (non-atomic review completion), fixed in ai/gateway.py and
packages/review_api.py. Offline: the recorded LLM test fixture only (no provider)."""
import base64
import time
from pathlib import Path

import pytest

from smartparser.review.authority import Reviewer
from smartparser.webapp import api
from smartparser.webapp.context import AppContext

from .phase3b_support import TEST_POLICY, dump, tbl

ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")
FX = Path(__file__).parent / "fixtures" / "recorded_llm" / "in10_ambiguous.json"
REN = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt", "amount": "txn_amt"}
TRUTH = {v: k for k, v in REN.items()}


def R(ctx, method, path, body=None):
    return api.route(ctx, method, [p for p in path.split("/") if p], {}, body or {})


def renamed(edit_payment_reference: str | None = None) -> bytes:
    r = [list(x) for x in tbl("IN-10")]
    if edit_payment_reference:
        i = r[0].index("payment_reference")
        r[1][i] = r[1][i] + edit_payment_reference
    return dump([[REN.get(c, c) for c in r[0]]] + r[1:])


def upload(ctx, data, name="cashbook.csv"):
    pid = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})["package_id"]
    sid = R(ctx, "POST", "staging", {"name": name, "data_b64": base64.b64encode(data).decode()})["entries"][0]["staging_id"]
    jid = R(ctx, "POST", f"packages/{pid}/intake", {"items": [{"staging_id": sid, "declared_category": "IN-10"}]})["job_id"]
    while R(ctx, "GET", f"jobs/{jid}")["state"] in ("queued", "running"):
        time.sleep(0.1)
    return pid, R(ctx, "GET", f"jobs/{jid}")["files"][0]["outcome"]["file_version_id"]


def decide_all(ctx, pid, vid):
    for row in R(ctx, "GET", f"review/{pid}/{vid}")["rows"]:
        if not row.get("read_only"):
            want = TRUTH[row["source_header"]]
            R(ctx, "POST", f"review/{pid}/{vid}/decision", {
                # Fix8 D4: the money column (AMBIGUOUS proposal) needs an explicit field choice, never a one-click MAP
                "action": "MAP" if row["suggested_field"] == want and want != "amount" else "CHANGE",
                "source_index": row["source_index"],
                "canonical_field": want, "reason": "TEST-ONLY synthetic ground truth"})


def ctx_for(tmp_path):
    return AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None, recorded=[FX])


@pytest.mark.parametrize("order", ["first_then_second", "second_then_first"])
def test_def_sv_01_deduplicated_upload_keeps_its_own_identity_and_data(tmp_path, order):
    ctx = ctx_for(tmp_path)
    a_bytes, b_bytes = renamed(), renamed(" second export")
    pa, va = upload(ctx, a_bytes)
    pb, vb = upload(ctx, b_bytes)
    assert len(ctx.stub.calls) == 1                                               # still one proposal call
    dedup = [e for e in ctx.events() if e["event_type"] == "PROPOSAL_DEDUPLICATED"]
    assert len(dedup) == 1 and dedup[0]["details"]["revalidated_for_this_upload"]
    sa, sb = ctx.svc.load(pa).versions[va], ctx.svc.load(pb).versions[vb]
    sess_b, req_b = ctx.svc.store.load_session(pb, sb.review_session_id)
    assert (req_b.intake_id, req_b.source_sha256, sess_b.intake_id) == (sb.intake_id, sb.source_sha256, sb.intake_id)
    sess_a, _ = ctx.svc.store.load_session(pa, sa.review_session_id)
    assert sess_a.proposal_id == sess_b.proposal_id                               # same provider response reused
    seq = [(pa, va), (pb, vb)] if order == "first_then_second" else [(pb, vb), (pa, va)]
    for pid, vid in seq:
        decide_all(ctx, pid, vid)
        out = R(ctx, "POST", f"review/{pid}/{vid}/complete", {"basis": "TEST-ONLY"})
        assert out["outcome"]["version_status"] == "VALIDATED"
    for pid, vid, data in ((pa, va, a_bytes), (pb, vb, b_bytes)):
        v = ctx.svc.load(pid).versions[vid]
        prev = ctx.svc.store.abs(v.handoff.preview_csv).read_bytes()
        canonical = dump([[TRUTH.get(c, c) for c in r] if i == 0 else r for i, r in
                          enumerate([x for x in __import__("csv").reader(data.decode().splitlines())])])
        assert prev == canonical, "the preview must be built from this upload's own bytes"
        assert f"__{v.source_sha256[:12]}.csv" in v.handoff.preview_csv
        assert ctx.svc.reprocess_version(pid, vid)["version_status"] == "VALIDATED"    # PV-05 path succeeds
    assert len(ctx.stub.calls) == 1


def test_def_sv_02_failed_completion_is_rolled_back_and_can_be_retried(tmp_path):
    ctx = ctx_for(tmp_path)
    pid, vid = upload(ctx, renamed())
    decide_all(ctx, pid, vid)
    real, calls = ctx.svc.o._finish, {"n": 0}

    def failing_finish(*a, **k):                                                  # fails AFTER the rule was written
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated failure after the file mapping was written")
        return real(*a, **k)
    ctx.svc.o._finish = failing_finish
    with pytest.raises(Exception) as e:
        R(ctx, "POST", f"review/{pid}/{vid}/complete", {"basis": "TEST-ONLY"})
    assert getattr(e.value, "code", None) == "INTERNAL"                         # unexpected errors are not echoed
    rb_err = [x for x in ctx.events() if x["event_type"] == "REVIEW_COMPLETION_ROLLED_BACK"][0]["details"]["error"]
    assert "simulated failure" in rb_err
    v = ctx.svc.load(pid).versions[vid]
    s, _ = ctx.svc.store.load_session(pid, v.review_session_id)
    assert v.version_status == "REVIEW_REQUIRED" and str(s.state) != "APPROVED"      # not stranded
    fms = ctx.svc.o.store.read("file_mappings")["file_mappings"]
    assert [x["lifecycle"]["status"] for x in fms if x["intake_id"] == v.intake_id] == ["revoked"]
    rb = [x for x in ctx.events() if x["event_type"] == "REVIEW_COMPLETION_ROLLED_BACK"]
    assert len(rb) == 1 and rb[0]["details"]["revoked_file_mappings"]
    out = R(ctx, "POST", f"review/{pid}/{vid}/complete", {"basis": "TEST-ONLY retry"})      # retry works
    assert out["outcome"]["version_status"] == "VALIDATED"
    fms = ctx.svc.o.store.read("file_mappings")["file_mappings"]
    assert sorted(x["lifecycle"]["status"] for x in fms if x["intake_id"] == v.intake_id) == ["active", "revoked"]
    assert ctx.log.verify() > 0


def test_incomplete_proposal_review_is_not_stranded(tmp_path):
    """G11 check (Stage 1 concern): completing a proposal review with a column left unresolved routes the file to the
    correction path (RESUBMISSION_REQUIRED) - it is not stranded in REVIEW_REQUIRED."""
    ctx = ctx_for(tmp_path)
    pid, vid = upload(ctx, renamed())
    rows = [r for r in R(ctx, "GET", f"review/{pid}/{vid}")["rows"] if not r.get("read_only")]
    R(ctx, "POST", f"review/{pid}/{vid}/decision", {"action": "LEAVE_UNRESOLVED", "source_index": rows[0]["source_index"],
                                                   "reason": "TEST-ONLY unsure"})
    for r in rows[1:]:
        R(ctx, "POST", f"review/{pid}/{vid}/decision", {"action": "CHANGE", "source_index": r["source_index"],
                                                       "canonical_field": TRUTH[r["source_header"]], "reason": "TEST-ONLY"})
    out = R(ctx, "POST", f"review/{pid}/{vid}/complete", {"basis": "TEST-ONLY"})
    assert out["outcome"]["version_status"] == "RESUBMISSION_REQUIRED"
    assert "IN-10" in out["outcome"]["pending_resubmissions"]
