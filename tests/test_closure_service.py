"""Ringfence closure (smartparser.webapp.closure + smartparser.reconciliation.closure_runner).

Unit tests run everywhere. The journey tests use the REAL UC-042 library (engine tree UC042_ROOT, closure interpreter
UC042_CLOSURE_PYTHON) and are skipped when either is absent, mirroring tests/test_ringfence_cases.py. No live AI is ever
called here: the investigations and the closing summary use the clearly marked TEST DOUBLE below, injected by
subclassing the runner (production code has no test path)."""
import base64
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from smartparser.reconciliation import closure_runner as cr
from smartparser.reconciliation.closure_runner import ClosureRunner, RUNNER_DEFS, RUNNER_MAIN
from smartparser.webapp import api
from smartparser.webapp.closure import FIXED, ClosureService
from smartparser.webapp.context import AppContext

from .test_ringfence_cases import ANALYST, TEST_POLICY, make_zip, settle
from .uc042_support import UC042_ROOT

CLOSURE_PY = Path(os.environ.get("UC042_CLOSURE_PYTHON",
                                 r"C:\Users\artlptp263user\Downloads\UC042_CLAUDE_CODE_HANDOFF\uc042\.venv\Scripts\python.exe"))
DEMO = Path(os.environ.get("RINGFENCE_DEMO_DATA", r"C:\Users\artlptp263user\p10\RINGFENCE_DEMO_TEST_DATA"))
needs_closure = pytest.mark.skipif(not ((UC042_ROOT / "uc042lib" / "final_pack").is_dir() and CLOSURE_PY.is_file()),
                                   reason="UC-042 library tree or closure interpreter not available "
                                          "(set UC042_ROOT / UC042_CLOSURE_PYTHON)")
USER = "alice.analyst"

# ===================================================================================================== TEST DOUBLE
# Tests only. A deterministic, NON-AI stand-in for the OpenAI investigator, executed inside the real library subprocess:
# investigations use the library's own offline investigator logic (fixed mode) relabelled as a non-simulated test
# double so the library's eligibility rules accept it; the closing summary is a minimal, schema-valid output that the
# library's own validation checks. Nothing here is reachable from production code.
TEST_DOUBLE = r'''
INVESTIGATION_MODE = "fixed"


def make_investigator(req):
    import json as _json
    from uc042lib.investigation.llm import OfflineSimulatedInvestigator

    class TestDoubleInvestigator(OfflineSimulatedInvestigator):
        provider, model, simulated = "test-double", "test-double-v1", False

        def structured_request(self, instructions, user_content, text_format):
            data = _json.loads(user_content.split("<audit_pack_input>\n", 1)[1].rsplit("\n</audit_pack_input>", 1)[0])
            extra = {}
            if "allowed_source_refs" in data:   # engine summary input 1.1 (schema 1.2): group assessments are required
                units = [(g["group_id"], g["exception_ids"], g["source_evidence_ids"]) for g in data["investigation_groups"]]
                units += [(c["candidate_id"], c["exception_ids"], c["source_evidence_ids"]) for c in data["candidate_relationships"]]
                extra["group_assessments"] = [{
                    "group_id": u, "exception_ids": [i.strip() for i in e.split(";") if i.strip()], "related_exception_ids": [],
                    "relationship_verdict": "UNVERIFIED", "confidence": "LOW", "supporting_evidence": list(s[:1]),
                    "contradicting_evidence": [],
                    "common_cause_hypothesis": "Test double: a common cause may exist but is not established.",
                    "missing_evidence": ["Test double: records that would link these exceptions."],
                    "analyst_action": "Test double: review the linked records.",
                    "rationale": "Test double output; it is not AI analysis."} for u, e, s in units]
            out = text_format(
                overall_position="The deterministic engine reported the case status recorded in the audit pack.",
                summary_text="Test double closing summary: every exception listed remains unresolved and needs review.",
                key_observations=[], unverified_hypotheses=[], evidence_gaps=[], suggested_next_steps=[],
                unresolved_items=[{"exception_id": x["exception_id"], "text": "Remains open; human review is needed."}
                                  for x in data["exceptions"]],
                limitations=["Test double output for automated tests; it is not AI analysis."], **extra)
            CALLS.append({"model": self.model, "request_id": "test-double", "usage": {"input_tokens": 10,
                          "cached_input_tokens": 2, "output_tokens": 5, "reasoning_tokens": 1, "total_tokens": 15}})
            return out, {"attempts": 1, "usage": {}}
    return TestDoubleInvestigator()
'''


class DoubleRunner(ClosureRunner):
    """TEST DOUBLE runner: the real library subprocess with the test-double investigator; AI reported available."""
    SCRIPT = RUNNER_DEFS + TEST_DOUBLE + RUNNER_MAIN

    def ai_configuration(self):
        return dict(super().ai_configuration(), available=True, provider="test-double", model="test-double-v1",
                    problem=None)


# ===================================================================================================== helpers
@pytest.fixture
def tmp_path():
    """A SHORT temporary folder: the library's write-once artefact paths (investigations/<pack>/<exception>/<inv>/...)
    are deep, and Windows limits paths to 260 characters (pytest's own tmp_path is too long)."""
    d = Path(tempfile.mkdtemp(prefix="cl", dir=os.environ.get("UC042_SHORT_TMP") or tempfile.gettempdir())).resolve()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def ctx_for(tmp_path, runner_cls=DoubleRunner, **kw) -> AppContext:
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=UC042_ROOT)
    ctx.closure = ClosureService(ctx, runner_cls(UC042_ROOT, CLOSURE_PY, **kw))
    return ctx


def R(ctx, method, path, body=None, q=None, user=USER):
    return api.route(ctx, method, [p for p in path.split("/") if p], q or {}, body or {}, user=user)


def code_of(fn):
    with pytest.raises(Exception) as e:
        fn()
    return api.to_http(e.value).code


def reconcile(ctx, data: bytes, customer="Closure Test Ltd", period="2026-09") -> str:
    c = R(ctx, "POST", "cases", {"customer_name": customer, "reporting_period": period, "zip_name": "upload.zip",
                                 "zip_b64": base64.b64encode(data).decode()})
    ref = c["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref, 300)
    assert d["actions"]["activate"]["enabled"], d["outstanding"]
    R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})
    R(ctx, "POST", f"cases/{ref}/reconcile")
    d = settle(ctx, ref, 900)
    # diagnostics on failure (Fix8 B: a load-only failure was otherwise unexplained)
    assert d["status"] == "COMPLETED", (d["status"], d["progress"].get("reconciliation"), [(j.get("kind"), j.get("state"), j.get("error")) for j in ctx.jobs.values() if j.get("kind") == "reconciliation"])
    return ref


def wait_closure(ctx, ref, until, timeout=900):
    end = time.time() + timeout
    v = None
    while time.time() < end:
        try:
            v = R(ctx, "GET", f"cases/{ref}/closure")
            if until(v):
                return v
        except api.HttpError:
            pass
        except Exception as e:                                       # NO_CLOSURE until the listener ran
            if api.to_http(e).code != "NO_CLOSURE":
                raise
        time.sleep(0.5)
    raise AssertionError(f"closure did not settle: {v and (v['state'], v['pack'])}")


def settled(v):
    return v["state"] not in ("PACK_PENDING", "INVESTIGATING", "GENERATING") and \
        not any(j in (v["review"].get("readiness") or {}).get("blockers", []) for j in ("A preview is being generated.",))


def scenario_zip(name: str) -> tuple[bytes, str, str]:
    d = next(DEMO.glob(f"{name}*"), None)
    if d is None:
        pytest.skip(f"demo scenario {name} not available at {DEMO}")
    meta = json.loads((d / "scenario.json").read_text(encoding="utf-8"))
    return (d / meta["zip"]["file"]).read_bytes(), meta["customer_name"], meta["reporting_period"]


def tree_digest(p: Path) -> dict:
    import hashlib
    return {str(f.relative_to(p)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob("*")) if f.is_file()}


def wait_job(ctx, job_id, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        j = R(ctx, "GET", f"jobs/{job_id}")
        if j["state"] not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise AssertionError("job did not finish")


# ===================================================================================================== unit tests
def test_env_file_exact_allowlist_never_prefix(tmp_path, monkeypatch):
    env = tmp_path / "ai.env"
    env.write_text("OPENAI_API_KEY=sk-test-123456789\nUC042_LLM_MODEL=m1\nUC042_LLM_FALLBACK_PROVIDER=groq\n"
                   "GROQ_API_KEY=gsk_secret\nUC042_DATABASE_URL=postgres://x\nexport UC042_OPENAI_REASONING_EFFORT=low\n"
                   "# OPENAI_API_KEY=commented\n", encoding="utf-8")
    vals = cr.parse_env_file(env)
    assert set(vals) == {"OPENAI_API_KEY", "UC042_LLM_MODEL", "UC042_OPENAI_REASONING_EFFORT"}
    monkeypatch.setenv("OPENAI_API_KEY", "sk-parent-should-not-leak")
    monkeypatch.setenv("UC042_LLM_FALLBACK_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_parent")
    r = ClosureRunner(tmp_path, "python", env)
    plain, ai = r._env(ai=False), r._env(ai=True)
    assert not any(k.startswith(("OPENAI", "GROQ", "UC042_LLM_FALLBACK")) for k in plain)
    assert ai["OPENAI_API_KEY"] == "sk-test-123456789" and "GROQ_API_KEY" not in ai
    assert "UC042_LLM_FALLBACK_PROVIDER" not in ai and "UC042_DATABASE_URL" not in ai
    assert plain["PYTHONDONTWRITEBYTECODE"] == "1" and plain["PYTHONPATH"] == str(Path(tmp_path).resolve())
    assert "sk-test" not in r._redact("error sk-test-123456789 here")


def test_ai_configuration_unavailable_and_never_returns_the_key(tmp_path):
    r = ClosureRunner(None, None)
    cfg = r.ai_configuration()
    assert cfg["available"] is False and cfg["problem"] == cr.UNAVAILABLE_NO_PYTHON and cfg["store"] is False
    env = tmp_path / "ai.env"
    env.write_text("OPENAI_API_KEY=sk-abcdefghijk\n", encoding="utf-8")
    r2 = ClosureRunner(UC042_ROOT, CLOSURE_PY, env)
    assert "sk-abcdefghijk" not in json.dumps(r2.ai_configuration())
    r3 = ClosureRunner(UC042_ROOT, CLOSURE_PY, tmp_path / "missing.env")
    if r3.problem() is None:
        assert r3.ai_configuration()["available"] is False
    with pytest.raises(cr.ClosureRunnerError) as e:
        r._call("info", {}, ai=False)
    assert str(e.value) == cr.UNAVAILABLE_NO_PYTHON


def test_cost_only_with_pricing(tmp_path):
    p = tmp_path / "price.json"
    p.write_text(json.dumps({"m": {"input_per_m": 2.0, "cached_input_per_m": 0.5, "output_per_m": 8.0}}))
    r = ClosureRunner(None, None, pricing_file=p)
    assert r.cost("m", {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 0}) == 2.0
    assert r.cost("m", {"input_tokens": 1_000_000, "cached_input_tokens": 1_000_000, "output_tokens": 1_000_000}) == 8.5
    assert r.cost("other", {"input_tokens": 5}) is None and ClosureRunner(None, None).cost("m", {}) is None


def test_routes_report_closure_disabled_without_service(tmp_path):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    assert R(ctx, "GET", "ai/configuration")["available"] is False
    assert code_of(lambda: R(ctx, "GET", "cases/RF-2026-09-001/closure")) == "CLOSURE_DISABLED"


# ===================================================================================================== journeys (real library)
@needs_closure
def test_clean_case_not_required_summary_final_pack_verified_and_authorised_by_user(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = reconcile(ctx, make_zip())
    v = wait_closure(ctx, ref, lambda v: v["state"] != "PACK_PENDING")
    assert v["pack"]["status"] == "GENERATED" and v["exceptions"] == [] and v["state"] == "READY", v
    assert v["usage"]["calls"] == 0 and v["deterministic_summary"]["label"] == "System-generated, not AI"
    st = v["deterministic_summary"]["statement"]                 # deterministic reconciliation statement (24 Nov 2026)
    assert st["state"] == "ALL_PASSED" and st["headline"] == "Everything checks out", st
    assert st["lines"] and all(x["state"] == "PASS" for x in st["lines"]) and "not by AI" in st["note"]
    run = v["recon_run_id"]
    before = tree_digest(ctx.runs / run)                       # runs/ is read-only for closure
    # no AI authorisation for a clean case
    assert not [e for e in ctx.events() if e["event_type"].startswith("AI_")]
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
    jj = wait_job(ctx, pv["job_id"]); assert jj["state"] == "completed", jj["error"]
    v = R(ctx, "GET", f"cases/{ref}/closure")
    cur = v["review"]["current_preview"]
    assert v["state"] == "PREVIEW_READY" and cur["closing_summary_status"] == "NOT_REQUIRED"
    # unchanged inputs: the cached preview is reused (no job)
    again = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
    assert again["job_id"] is None and again["reused"] is True and again["preview_id"] == cur["preview_id"]
    ctype, pdf, hdr = R(ctx, "GET", f"cases/{ref}/closure/review/preview.pdf")
    assert ctype == "application/pdf" and pdf[:5] == b"%PDF-" and hdr["X-Snapshot-SHA256"] == cur["snapshot_sha256"]
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": False, "snapshot_sha256": cur["snapshot_sha256"],
        "expected_revision": v["revision"]})) == "ACKNOWLEDGEMENT_REQUIRED"
    out = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": True, "acknowledged_summary_unavailable": False,
        "snapshot_sha256": cur["snapshot_sha256"], "expected_revision": v["revision"]})
    assert "Ringfence provenance" in out["decision"]["comment"] and ref in out["decision"]["comment"]
    assert wait_job(ctx, out["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "GENERATED" and v["frozen"] and v["final_pack"]["verified"]
    assert v["final_pack"]["authorised_by"] == USER
    fp = R(ctx, "GET", f"cases/{ref}/closure/final-pack")
    assert fp["verified"] and not fp["problems"] and {f["key"] for f in fp["files"]} >= {"pdf", "html", "json",
                                                                                         "manifest", "provenance.pdf"}
    ctype, data, hdr = R(ctx, "GET", f"cases/{ref}/closure/final-pack/json")
    final = json.loads(data)
    assert final["human_review"]["reviewer"]["user_id"] == USER and final["human_review"]["decision"] == "GENERATE"
    assert "Ringfence provenance" in final["human_review"]["comment"]
    assert final["closing_summary"]["status"] == "NOT_REQUIRED"
    _, pdf, hdr = R(ctx, "GET", f"cases/{ref}/closure/final-pack/pdf", q={"download": "1"})
    assert pdf[:5] == b"%PDF-" and hdr["Content-Disposition"].startswith("attachment")
    _, ppdf, _ = R(ctx, "GET", f"cases/{ref}/closure/final-pack/provenance.pdf")
    assert ppdf[:5] == b"%PDF-"
    # 23 Nov 2026: the analyst edition (renderer 4.0-analyst) is generated beside the provenance record and verified
    assert "analyst.pdf" in {f["key"] for f in fp["files"]}
    _, apdf, _ = R(ctx, "GET", f"cases/{ref}/closure/final-pack/analyst.pdf")
    assert apdf[:5] == b"%PDF-" and b"4.0-analyst" in apdf
    prov = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/provenance.json")[1])
    assert prov["authorised_by"] == USER and prov["zip"]["sha256"] and all(
        f["original_filename"] and f["file_version_id"] and f["source_sha256"] for f in prov["source_files"])
    # frozen: closure mutations refused
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/review/preview",
                             {"expected_revision": v["revision"]})) == "CLOSURE_FROZEN"
    # integrity: runs/ untouched; audit chain verifies; events written after state (closure revision already reflects)
    assert tree_digest(ctx.runs / run) == before
    assert ctx.log.verify() > 0
    types = [e["event_type"] for e in ctx.events() if e["details"].get("recon_run_id") == run]
    assert types.index("AUDIT_PACK_GENERATED") < types.index("CLOSING_PREVIEW_REQUESTED") < \
        types.index("FINAL_PACK_GENERATED")
    gen = [e for e in ctx.events() if e["event_type"] == "FINAL_PACK_GENERATED"][-1]
    assert gen["actor_id"] == USER and gen["details"]["system_reviewer_id"] == ANALYST.reviewer_id
    # "verify" from a fresh library process agrees
    assert ctx.closure.runner.verify_final(Path(ctx.closure._load(ref, run)["final_pack"]["path"]),
                                           tmp_path / "scratch") == []


@needs_closure
def test_exceptions_case_investigations_decisions_preview_hold_generate_freeze_and_restart(tmp_path, monkeypatch):
    # The AI closing summary is off by the 23 Nov 2026 owner decision; this test keeps its (re-enableable) path covered.
    monkeypatch.setenv("RINGFENCE_AI_CLOSING_SUMMARY", "on")
    data, customer, period = scenario_zip("scenario_2")
    ctx = ctx_for(tmp_path)
    ref = reconcile(ctx, data, customer, period)
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING", "INVESTIGATING"))
    assert v["pack"]["status"] == "GENERATED" and len(v["exceptions"]) >= 2
    excs = v["exceptions"]
    auth = [e for e in ctx.events() if e["event_type"] == "AI_AUTHORIZED"]
    assert len(auth) == 1 and auth[0]["details"]["kind"] == "AUTO_INVESTIGATION"
    # automatic work is the system; the user who started reconciliation stays recorded (Fix8 B identity follow-up)
    assert (auth[0]["actor_id"], auth[0]["actor_role"], auth[0]["details"]["authorized_by"]) == ("ringfence-closure-service", "system", USER)
    assert len([e for e in ctx.events() if e["event_type"] == "AI_INVESTIGATION_QUEUED"]) == len(excs)
    pub = [x for x in excs if x["ai_state"] == "PUBLISHED"]
    assert len(pub) >= 2, [(x["exception_id"], x["ai_state"]) for x in excs]
    assert all(x["analyst_decision"] is None for x in excs)
    assert any(b.startswith("AI review pending") for b in v["review"]["readiness"]["blockers"])
    # exception workspace: facts trace back to the customer's files; AI block labelled
    ws = R(ctx, "GET", f"cases/{ref}/closure/exceptions/{pub[0]['exception_id']}")
    assert ws["facts"]["supporting_evidence"] and all(s["original_filename"] and s["file_version_id"]
                                                      for s in ws["facts"]["supporting_evidence"] if s.get("line"))
    assert ws["investigation"]["label"] == "AI-generated" and ws["decision"]["actions"]["accept"]["enabled"]
    assert ws["decision"]["actions"]["accept"]["label"] == "Accept AI finding"
    det = R(ctx, "GET", f"cases/{ref}/closure/investigations/{pub[0]['investigation_id']}")
    assert det["verify"]["ok"] and det["evidence_ledger"]["records"]
    # revision guard
    inv0, inv1 = pub[0]["investigation_id"], pub[1]["investigation_id"]
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv0}/decision",
                             {"decision": "ACCEPT"})) == "REVISION_REQUIRED"
    with pytest.raises(Exception) as e:
        R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv0}/decision",
          {"decision": "ACCEPT", "expected_revision": v["revision"] - 1})
    h = api.to_http(e.value)
    assert h.code == "CLOSURE_CHANGED" and h.extra["current_revision"] == v["revision"]
    # ACCEPT one / REJECT one (fixed wording, never free text)
    a = R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv0}/decision",
          {"decision": "ACCEPT", "expected_revision": v["revision"], "reason": "free text is ignored"})
    assert a["analyst_review"]["rejection_reason"] == "" and a["analyst_review"]["decided_by"] == USER
    r = R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv1}/decision",
          {"decision": "REJECT", "expected_revision": a["closure"]["revision"], "reason": "ignored"})
    assert r["analyst_review"]["rejection_reason"] == FIXED["REJECT"]
    v = r["closure"]
    # remaining published investigations: decide; failed ones (if any): exclude (fixed wording)
    for x in v["exceptions"]:
        if x["exception_id"] in (pub[0]["exception_id"], pub[1]["exception_id"]):
            continue
        if x["ai_state"] == "PUBLISHED":
            v = R(ctx, "POST", f"cases/{ref}/closure/investigations/{x['investigation_id']}/decision",
                  {"decision": "ACCEPT", "expected_revision": v["revision"]})["closure"]
        else:
            rv = R(ctx, "POST", f"cases/{ref}/closure/review/selections", {"expected_revision": v["revision"],
                   "selections": [{"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST"}]})
            assert next(s for s in rv["selections"] if s["exception_id"] == x["exception_id"])["reason"] == \
                FIXED["EXCLUDED_BY_ANALYST"]
            v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "READY", v["review"]["readiness"]
    hist = R(ctx, "GET", f"cases/{ref}/closure/exceptions/{pub[1]['exception_id']}/history")["events"]
    assert [e["event_type"] for e in hist][-1] == "ANALYST_INVESTIGATION_REJECTED"
    # preview (test-double summary), reuse, HOLD, reuse after HOLD, GENERATE
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/review/preview",
                             {"expected_revision": v["revision"]})) == "AI_CONFIRMATION_REQUIRED"
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"confirm_ai": True, "expected_revision": v["revision"]})
    assert wait_job(ctx, pv["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    cur = v["review"]["current_preview"]
    assert v["state"] == "PREVIEW_READY" and cur["closing_summary_status"] == "GENERATED"
    assert v["usage"]["calls"] >= 1 and v["usage"]["cost"] is None and "no price" in v["usage"]["cost_note"]
    held = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {"decision": "HOLD", "expected_revision": v["revision"],
                                                                   "comment": "ignored free text"})
    assert held["decision"]["comment"] == FIXED["HOLD"] and held["closure"]["state"] == "ON_HOLD"
    again = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"confirm_ai": True,
                                                                   "expected_revision": held["closure"]["revision"]})
    assert again["reused"] is True and again["preview_id"] == cur["preview_id"]
    v = R(ctx, "GET", f"cases/{ref}/closure")
    out = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": True, "snapshot_sha256": cur["snapshot_sha256"],
        "expected_revision": v["revision"]})
    assert wait_job(ctx, out["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "GENERATED" and v["frozen"] and v["final_pack"]["authorised_by"] == USER
    final = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/json")[1])
    reviews = {r["investigation_id"]: r for r in final["analyst_reviews"]["reviews"]} \
        if isinstance(final.get("analyst_reviews"), dict) and "reviews" in final["analyst_reviews"] else None
    blob = json.dumps(final)
    assert FIXED["REJECT"] in blob and FIXED["HOLD"] in blob
    if reviews is not None:
        assert reviews[inv1]["decision"] == "REJECT"
    # decisions refused after the freeze
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/investigations/{inv0}/decision",
                             {"decision": "REJECT", "expected_revision": v["revision"]})) == "CLOSURE_FROZEN"
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/exceptions/{pub[0]['exception_id']}/investigations",
                             {"expected_revision": v["revision"]})) == "CLOSURE_FROZEN"
    assert ctx.log.verify() > 0
    # events after state: every ANALYST_* event's review is already in the store when the event exists
    stored = {x["analyst_review_id"] for x in ctx.closure._reviews(ctx.closure._load(ref, v["recon_run_id"]))}
    for e in ctx.events():
        if e["event_type"].startswith("ANALYST_INVESTIGATION_"):
            assert e["details"]["analyst_review_id"] in stored and e["actor_id"] == USER
    # restart: a new context recomputes closure state from files; nothing re-runs
    n_jobs = len(ctx.jobs)
    ctx2 = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=UC042_ROOT)
    ctx2.closure = ClosureService(ctx2, DoubleRunner(UC042_ROOT, CLOSURE_PY))
    v2 = R(ctx2, "GET", f"cases/{ref}/closure")
    assert v2["state"] == "GENERATED" and v2["frozen"] and v2["final_pack"]["final_pack_id"] == v["final_pack"]["final_pack_id"]
    assert len(ctx2.jobs) == n_jobs


@needs_closure
def test_restart_recovery_marks_interrupted_generation_and_pack(tmp_path):
    """Recovery: a closure whose final-pack job (or pack job) was running when the server stopped is recomputed."""
    ctx = ctx_for(tmp_path)
    ref = reconcile(ctx, make_zip())
    v = wait_closure(ctx, ref, lambda v: v["state"] == "READY")
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
    wait_job(ctx, pv["job_id"])
    v = R(ctx, "GET", f"cases/{ref}/closure")
    cl = ctx.closure
    c = cl._load(ref, v["recon_run_id"])
    s = cl._session(c)
    # simulate a crash in the middle of GENERATE: session GENERATING with a running final_pack job record
    j = cl._job("final_pack", c, review_id=s["review_id"])
    j["state"] = "running"
    ctx._save_job(j)
    s["status"] = "GENERATING"
    cl._save_session(c, s)
    ctx2 = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=UC042_ROOT)
    ctx2.closure = ClosureService(ctx2, DoubleRunner(UC042_ROOT, CLOSURE_PY))
    assert ctx2.jobs[j["job_id"]]["state"] == "interrupted"
    v2 = R(ctx2, "GET", f"cases/{ref}/closure")
    assert v2["state"] == "GENERATION_FAILED" and "interrupted" in v2["last_generation_failure"]["error"]
    assert not v2["frozen"]


@needs_closure
def test_corvane_type_pack_failure_is_unavailable_and_blocks_closure(tmp_path):
    data, customer, period = scenario_zip("scenario_3")
    ctx = ctx_for(tmp_path)
    ref = reconcile(ctx, data, customer, period)
    v = wait_closure(ctx, ref, lambda v: v["state"] != "PACK_PENDING")
    assert v["state"] == "PACK_UNAVAILABLE" and v["pack"]["status"] == "UNAVAILABLE"
    assert v["pack"]["reason"] and v["pack"]["reason"].startswith("V")       # the library's exact validation finding
    assert v["review"]["readiness"]["blockers"][0].startswith("Audit pack unavailable: " + v["pack"]["reason"])
    assert not any(a["enabled"] for a in v["actions"].values())
    assert all(x["ai_state"] == "UNAVAILABLE" for x in v["exceptions"])
    for path, body in (("review", {}), ("review/preview", {"confirm_ai": True}),
                       ("review/decision", {"decision": "GENERATE", "acknowledgement_accepted": True})):
        assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/{path}",
                                 dict(body, expected_revision=v["revision"]))) == "PACK_UNAVAILABLE"
    assert code_of(lambda: R(ctx, "GET", f"cases/{ref}/closure/final-pack")) == "NO_FINAL_PACK"
    assert not list((ctx.root / "closure" / ref / v["recon_run_id"] / "final_packs").glob("FAP-*"))
    ev = [e for e in ctx.events() if e["event_type"] == "AUDIT_PACK_UNAVAILABLE"]
    assert len(ev) == 1 and ev[0]["details"]["reason"] == v["pack"]["reason"]
    assert not [e for e in ctx.events() if e["event_type"].startswith("AI_")]
    pk = R(ctx, "GET", f"cases/{ref}/closure/pack")
    assert pk["status"] == "UNAVAILABLE" and pk["findings"]


def test_hypothesis_evidence_resolves_in_citations(tmp_path):
    """Final E2E round (20 Nov 2026): hypothesis supporting / contradictory evidence IDs are in the citation map, so the
    exception workspace renders them as citation chips that resolve to the customer's file like the findings'."""
    d = Path(tmp_path) / "inv"
    d.mkdir()
    (d / "evidence_ledger.json").write_text(json.dumps({"source_records": [
        {"evidence_id": "IN-09:BE-1", "source_file": "source_data/bank_statement_entries.csv", "source_line": 4},
        {"evidence_id": "IN-09:BE-2", "source_file": "source_data/bank_statement_entries.csv", "source_line": 9}]}),
        encoding="utf-8")
    svc = ClosureService.__new__(ClosureService)
    svc._trace = lambda c: {"bank_statement_entries.csv": {"original_filename": "stmt.csv", "file_version_id": "FV-1",
                                                           "source_sha256": "ab" * 32}}
    f = {"confirmed_findings": [], "hypotheses": [{"hypothesis_id": "H-01", "supporting_evidence": ["IN-09:BE-1"],
                                                    "contradictory_evidence": ["IN-09:BE-2"]}]}
    out = svc._citations({}, d, f)
    assert sorted(out) == ["IN-09:BE-1", "IN-09:BE-2"]
    assert (out["IN-09:BE-1"]["original_filename"], out["IN-09:BE-1"]["file_version_id"], out["IN-09:BE-1"]["line"]) == \
        ("stmt.csv", "FV-1", 4)


def test_ai_closing_summary_is_off_by_default(monkeypatch):
    """23 Nov 2026 owner decision: no AI closing summary; the preview needs no AI confirmation for a case with exceptions."""
    from smartparser.webapp import closure
    monkeypatch.delenv("RINGFENCE_AI_CLOSING_SUMMARY", raising=False)
    assert closure.ai_closing_summary() is False
    monkeypatch.setenv("RINGFENCE_AI_CLOSING_SUMMARY", "on")
    assert closure.ai_closing_summary() is True
