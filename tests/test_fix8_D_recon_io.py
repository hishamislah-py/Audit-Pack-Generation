"""Fix8 Agent D - reconciliation/job I/O under load.

Root cause of the load-only failure (test_closure_service ... reconcile(): settle() returned status IN_PROGRESS): the
reconciliation job flipped its in-memory state to 'completed' outside the case lock, so CaseService.detail() could decide
the case status (_refresh: job still running -> IN_PROGRESS) and then compute progress (job completed -> no current
operation) from two different job states. These tests force that interleaving deterministically, and inject sharing
violations / partial writes into the job record and the reconciliation adapter.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import threading
import time
from pathlib import Path

import pytest

from smartparser.reconciliation import uc042_adapter
from smartparser.webapp import cases as cases_mod
from smartparser.webapp import context as context_mod
from smartparser.webapp.context import AppContext

from .test_ringfence_cases import ANALYST, R, TEST_POLICY, ctx_for, make_zip, settle
from .uc042_support import UC042_ROOT, needs_uc042


def activated_case(ctx) -> str:
    ref = R(ctx, "POST", "cases", {"customer_name": "Harbourline Payments Ltd", "reporting_period": "2026-09",
                                   "zip_name": "submission.zip", "zip_b64": base64.b64encode(make_zip()).decode()})["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref, 300)
    assert d["actions"]["activate"]["enabled"], d["outstanding"]
    assert R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})["activated"]
    return ref


def fake_record(run_id="RECON-TEST-0001"):
    return {"run_id": run_id, "result": {"case_status": "CLEAN", "outcomes": {"PASS": 1}, "exceptions": []},
            "checks": {"engine_received_exact_bytes": True}}


def settled_condition(d) -> bool:                    # exactly the condition the tests' settle() helper uses
    return not d["progress"]["current_operation"] and (d["current_run"] or {}).get("status") != "PROCESSING" \
        and not d["deferring"]


# ======================================================================================= 1. the observed race
def test_case_view_never_reports_settled_while_in_progress_when_the_job_finishes_mid_view(tmp_path, monkeypatch):
    """Deterministic interleaving: the reconciliation finishes exactly while a GET case is between deciding the
    status and computing the progress. Before the fix this view was {status IN_PROGRESS, no current operation,
    reconciliation COMPLETED} - settle() returned and `assert status == COMPLETED` failed."""
    ctx = ctx_for(tmp_path)
    ref = activated_case(ctx)
    ctx.uc042_root = tmp_path                                     # enables start_reconciliation; the engine is faked
    release, finished_in_view = threading.Event(), threading.Event()

    def fake_run(svc, pid, sid, root, out):
        release.wait(30)
        return fake_record()
    monkeypatch.setattr(context_mod, "run_reconciliation", fake_run)

    job_id = R(ctx, "POST", f"cases/{ref}/reconcile")["job_id"]
    orig_detail = cases_mod.CaseService._detail
    armed = {"on": True}

    def detail_with_job_finishing_inside(self, c):
        if armed["on"] and c["case_ref"] == ref:
            armed["on"] = False
            assert c["status"] == "IN_PROGRESS"                    # status already decided: job still running
            release.set()                                          # now the job finishes ...
            end = time.time() + 2.0                                # ... give it every chance to publish mid-view
            while time.time() < end and ctx.jobs[job_id]["state"] != "completed":
                time.sleep(0.01)
            if ctx.jobs[job_id]["state"] == "completed":
                finished_in_view.set()
        return orig_detail(self, c)
    monkeypatch.setattr(cases_mod.CaseService, "_detail", detail_with_job_finishing_inside)

    d = R(ctx, "GET", f"cases/{ref}")
    # the view is coherent: either the job is still shown running, or the case is COMPLETED
    assert d["status"] == "COMPLETED" or d["progress"]["current_operation"] is not None, d["progress"]
    assert not (settled_condition(d) and d["status"] != "COMPLETED")
    assert not finished_in_view.is_set(), "the job published its terminal state while a case view was being built"
    d = settle(ctx, ref, 60)
    assert d["status"] == "COMPLETED" and d["completed"]["reconciliation_run_id"] == "RECON-TEST-0001"
    rec = json.loads((ctx.jobdir / f"{job_id}.json").read_text(encoding="utf-8"))
    assert rec["state"] == "completed" and rec["run_id"] == "RECON-TEST-0001" and rec["finished_at"]


def test_every_view_during_a_reconciliation_is_coherent(tmp_path, monkeypatch):
    """Pollers hammer GET case while the (fake, fast) job finishes; no view may satisfy settle() before COMPLETED."""
    ctx = ctx_for(tmp_path)
    ref = activated_case(ctx)
    ctx.uc042_root = tmp_path
    go = threading.Event()
    monkeypatch.setattr(context_mod, "run_reconciliation", lambda *a: (go.wait(30), fake_record())[1])
    orig_detail = cases_mod.CaseService._detail

    def slow_detail(self, c):                                     # widen the window (CPU starvation under load)
        time.sleep(0.1)
        return orig_detail(self, c)
    monkeypatch.setattr(cases_mod.CaseService, "_detail", slow_detail)
    R(ctx, "POST", f"cases/{ref}/reconcile")
    bad, stop = [], threading.Event()

    def poll():
        while not stop.is_set():
            d = R(ctx, "GET", f"cases/{ref}")
            if d["status"] == "COMPLETED":
                stop.set()
            elif settled_condition(d):
                bad.append((d["status"], d["progress"]["reconciliation"]))
    ts = [threading.Thread(target=poll) for _ in range(3)]
    for t in ts:
        t.start()
    time.sleep(0.3)
    go.set()
    stop.wait(30)
    stop.set()
    for t in ts:
        t.join(10)
    assert bad == []
    assert R(ctx, "GET", f"cases/{ref}")["status"] == "COMPLETED"


# ======================================================================================= 2. job record writes / reads
def test_save_job_is_atomic_retries_sharing_violations_and_leaves_no_temp_files(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    j = ctx._new_job("reconciliation", "PKG-x", snapshot_id="S", run_id=None, result=None)
    p = ctx.jobdir / f"{j['job_id']}.json"
    real_replace, calls = os.replace, {"n": 0}

    def flaky_replace(a, b):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise PermissionError(5, "Access is denied")          # WinError 5: target held by a reader right now
        return real_replace(a, b)
    monkeypatch.setattr(context_mod.os, "replace", flaky_replace)
    j["state"] = "completed"
    ctx._save_job(j)
    assert calls["n"] == 4 and json.loads(p.read_text(encoding="utf-8"))["state"] == "completed"
    assert list(ctx.jobdir.glob("*.tmp")) == []

    # persistent violation: raises, the previous COMPLETE record is untouched, no temp file left behind
    monkeypatch.setattr(context_mod.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(5, "denied")))
    monkeypatch.setattr(context_mod, "_retry_sharing", lambda fn: _retry_fast(fn))
    j["state"] = "failed"
    with pytest.raises(PermissionError):
        ctx._save_job(j)
    assert json.loads(p.read_text(encoding="utf-8"))["state"] == "completed"
    assert list(ctx.jobdir.glob("*.tmp")) == []


def _retry_fast(fn, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise


def test_a_write_interrupted_half_way_never_leaves_a_partial_job_record(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    j = ctx._new_job("intake", "PKG-x", files=[], resubmission=None, validation=None)
    p = ctx.jobdir / f"{j['job_id']}.json"
    real_write = pathlib.Path.write_text

    def half_write(self, text, *a, **kw):                           # the process dies / disk fills half way
        real_write(self, text[: len(text) // 2], *a, **kw)
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(pathlib.Path, "write_text", half_write)
    j["state"] = "running"
    with pytest.raises(OSError):
        ctx._save_job(j)
    monkeypatch.undo()
    assert json.loads(p.read_text(encoding="utf-8"))["state"] == "queued"   # previous complete record, never torn
    assert list(ctx.jobdir.glob("*.tmp")) == []


def test_restart_retries_a_locked_job_record_and_reports_an_unreadable_one(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    j = ctx._new_job("reconciliation", "PKG-x", snapshot_id="S", run_id=None, result=None)
    (ctx.jobdir / "JOB-torn000001.json").write_text('{"job_id": "JOB-torn000001", "sta', encoding="utf-8")
    real_read, seen = pathlib.Path.read_text, {"n": 0}

    def locked_twice(self, *a, **kw):
        if self.name == f"{j['job_id']}.json" and seen["n"] < 2:
            seen["n"] += 1
            raise PermissionError(32, "The process cannot access the file because it is being used")
        return real_read(self, *a, **kw)
    monkeypatch.setattr(pathlib.Path, "read_text", locked_twice)
    ctx2 = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    assert seen["n"] == 2
    assert ctx2.jobs[j["job_id"]]["state"] == "interrupted"          # retried, never silently dropped
    assert [e["file"] for e in ctx2.job_load_errors] == ["JOB-torn000001.json"]


def test_a_job_that_cannot_be_recorded_is_never_registered_as_queued(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    monkeypatch.setattr(ctx, "_save_job", lambda j: (_ for _ in ()).throw(PermissionError(5, "denied")))
    with pytest.raises(PermissionError):
        ctx._new_job("reconciliation", "PKG-x")
    assert ctx.jobs == {}


# ======================================================================================= 3. jobs never stuck
def _recon_job(ctx, monkeypatch, result):
    ctx.uc042_root = Path(".")
    monkeypatch.setattr(context_mod, "run_reconciliation", result)
    seen = []
    ctx.job_listeners.append(lambda j: seen.append(dict(j)))
    j = ctx._new_job("reconciliation", "PKG-x", snapshot_id="S", run_id=None, result=None)
    return j, seen


def test_recon_job_that_cannot_record_running_ends_failed_not_stuck(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    j, seen = _recon_job(ctx, monkeypatch, lambda *a: fake_record())
    real_save, n = ctx._save_job, {"k": 0}

    def fail_first(job):
        n["k"] += 1
        if n["k"] == 1:
            raise PermissionError(5, "Access is denied")            # the 'running' write
        real_save(job)
    monkeypatch.setattr(ctx, "_save_job", fail_first)
    ctx._run_recon(j)
    assert j["state"] == "failed" and "PermissionError" in j["error"] and j["finished_at"] and "trace" in j
    assert seen and seen[0]["state"] == "failed"
    assert json.loads((ctx.jobdir / f"{j['job_id']}.json").read_text(encoding="utf-8"))["state"] == "failed"


def test_recon_adapter_error_ends_failed_with_its_error(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)

    def boom(*a):
        raise PermissionError(5, "Access is denied: run/input/IN-01.csv")
    j, seen = _recon_job(ctx, monkeypatch, boom)
    ctx._run_recon(j)
    assert j["state"] == "failed" and "Access is denied" in j["error"] and seen[0]["state"] == "failed"
    assert j["run_id"] is None


def test_terminal_persist_or_audit_failure_still_completes_and_notifies(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    j, seen = _recon_job(ctx, monkeypatch, lambda *a: fake_record("RECON-OK"))
    real_save, n = ctx._save_job, {"k": 0}

    def fail_after_running(job):
        n["k"] += 1
        if n["k"] >= 2:
            raise PermissionError(5, "Access is denied")
        real_save(job)
    monkeypatch.setattr(ctx, "_save_job", fail_after_running)
    monkeypatch.setattr(ctx, "last_seq", lambda: (_ for _ in ()).throw(PermissionError(32, "in use")))
    ctx._run_recon(j)
    assert j["state"] == "completed" and j["run_id"] == "RECON-OK" and j["finished_at"]
    assert "PermissionError" in j["persist_error"]
    assert seen and seen[0]["state"] == "completed"                  # listeners (case, closure) still ran


def test_intake_job_publishes_terminal_state_through_the_same_path(tmp_path, monkeypatch):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    j = ctx._new_job("intake", "PKG-missing", files=[], resubmission=None, validation=None)
    calls = []
    monkeypatch.setattr(ctx, "_job_finish", lambda job, **t: (calls.append(t), job.update(t)))
    ctx._run_intake(j)                                              # validate() of an unknown package raises
    assert calls and calls[0]["state"] == "failed" and calls[0]["error"] and calls[0]["trace"]


# ======================================================================================= 4. adapter I/O, real engine
@needs_uc042
def test_reconciliation_survives_transient_sharing_violations_on_every_run_file(tmp_path, monkeypatch):
    """Every adapter read/write of a file under <ws>/runs (and the snapshot manifest) fails ONCE with a sharing
    violation; the reconciliation still completes, the case COMPLETES, and every file is the engine's real output."""
    ctx = ctx_for(tmp_path, engine=True)
    ref = activated_case(ctx)
    runs = str(ctx.runs)
    hit: dict[str, int] = {}
    injected = []

    def once(name):
        real = getattr(pathlib.Path, name)

        def wrapper(self, *a, **kw):
            s = str(self)
            if (s.startswith(runs) or s.endswith(".manifest.json")) and threading.current_thread().name != "MainThread":
                key = f"{name}:{s}"
                if key not in hit:
                    hit[key] = 1
                    injected.append(key)
                    raise PermissionError(5, f"Access is denied: '{s}'")
            return real(self, *a, **kw)
        monkeypatch.setattr(pathlib.Path, name, wrapper)
    for name in ("read_text", "read_bytes", "write_text", "write_bytes"):
        once(name)
    job_id = R(ctx, "POST", f"cases/{ref}/reconcile")["job_id"]
    d = settle(ctx, ref, 600)
    j = ctx.jobs[job_id]
    assert j["state"] == "completed", (j.get("error"), j.get("trace"))
    assert d["status"] == "COMPLETED" and d["completed"]["case_status"] == "CLEAN"
    kinds = {k.split(":", 1)[0] for k in injected}
    assert {"read_text", "read_bytes", "write_text", "write_bytes"} <= kinds, injected
    assert any(k.endswith(".manifest.json") for k in injected)
    rec = json.loads((ctx.runs / j["run_id"] / "reconciliation_run.json").read_text(encoding="utf-8"))
    assert all(rec["checks"].values())


# ======================================================================================= 5. case record I/O (cases.py)
def _case(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = R(ctx, "POST", "cases", {"customer_name": "Harbourline Payments Ltd", "reporting_period": "2026-09",
                                   "zip_name": "submission.zip", "zip_b64": base64.b64encode(make_zip()).decode()})["case_ref"]
    return ctx, ref


def test_case_load_retries_a_transient_sharing_violation_and_never_reports_missing(tmp_path, monkeypatch):
    ctx, ref = _case(tmp_path)
    target = f"{ref}.json"
    real_read, seen = pathlib.Path.read_text, {"n": 0}

    def locked_three_times(self, *a, **kw):
        if self.name == target and seen["n"] < 3:
            seen["n"] += 1
            raise PermissionError(13, "Permission denied")         # what the race investigator captured under load
        return real_read(self, *a, **kw)
    monkeypatch.setattr(pathlib.Path, "read_text", locked_three_times)
    assert ctx.cases.load(ref)["case_ref"] == ref and seen["n"] == 3

    # persistent: PermissionError propagates - never NOT_FOUND
    monkeypatch.setattr(cases_mod, "_retry_sharing", _retry_fast)
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **kw: (_ for _ in ()).throw(PermissionError(13, "Permission denied"))
                        if self.name == target else real_read(self, *a, **kw))
    with pytest.raises(PermissionError):
        ctx.cases.load(ref)


def test_case_save_uses_a_unique_temp_file_retries_and_never_tears_the_record(tmp_path, monkeypatch):
    ctx, ref = _case(tmp_path)
    p = ctx.cases.root / f"{ref}.json"
    before = json.loads(p.read_text(encoding="utf-8"))
    real_replace, tmps, n = pathlib.Path.replace, [], {"k": 0}

    def flaky_replace(self, target):
        tmps.append(self.name)
        n["k"] += 1
        if n["k"] <= 2:
            raise PermissionError(13, "Permission denied")
        return real_replace(self, target)
    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace)
    c = ctx.cases.load(ref)
    c["last_activity_at"] = "x"
    ctx.cases._save(c)
    assert n["k"] == 3 and json.loads(p.read_text(encoding="utf-8"))["last_activity_at"] == "x"
    assert tmps[0].startswith(f"{ref}.json.") and tmps[0].endswith(".tmp") and tmps[0] != f"{ref}.tmp"

    # persistent violation: raises, previous complete record intact, no temp left; refs() unaffected
    monkeypatch.setattr(cases_mod, "_retry_sharing", _retry_fast)
    monkeypatch.setattr(pathlib.Path, "replace",
                        lambda self, t: (_ for _ in ()).throw(PermissionError(13, "Permission denied")))
    c["last_activity_at"] = "y"
    with pytest.raises(PermissionError):
        ctx.cases._save(c)
    assert json.loads(p.read_text(encoding="utf-8"))["last_activity_at"] == "x"
    assert list(ctx.cases.root.glob("*.tmp")) == [] and ctx.cases.refs() == [ref]
    assert before["case_ref"] == ref


def test_concurrent_case_reads_and_saves_never_fail(tmp_path):
    """One writer saving, four readers loading the same case record (the closure/_locate + view pattern)."""
    ctx, ref = _case(tmp_path)
    errors, stop = [], threading.Event()

    def writer():
        while not stop.is_set():
            try:
                with ctx.cases.lock:
                    c = ctx.cases.load(ref)
                    ctx.cases._save(c)
            except Exception as e:
                errors.append(f"write {type(e).__name__}: {e}")

    def reader():
        while not stop.is_set():
            try:
                assert ctx.cases.load(ref)["case_ref"] == ref
            except Exception as e:
                errors.append(f"read {type(e).__name__}: {e}")
    ts = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(4)]
    for t in ts:
        t.start()
    time.sleep(4)
    stop.set()
    for t in ts:
        t.join(30)
    assert errors == []
    assert list(ctx.cases.root.glob("*.tmp")) == []


# ======================================================================================= 6. settled => persisted
def test_when_a_view_shows_the_intake_finished_its_records_are_already_final_on_disk(tmp_path, monkeypatch):
    """Root cause of test_ringfence_api_contract::test_state_survives_restart... ('COMPLETED' == 'FAILED'): settle()
    returned as soon as the in-memory job was terminal, but the job thread had not yet written its terminal record nor
    run the case listener; those late writes then overwrote the test's simulated 'running' job / PROCESSING run. A
    slow terminal job write (disk under load) is injected; once a view shows the run finished, the job and case
    records on disk must already be final and the job thread must have nothing left to write."""
    ctx, ref = _case(tmp_path)
    real_save = ctx._save_job

    def slow_terminal_save(j):
        if j.get("kind") == "intake" and j.get("state") in ("completed", "failed"):
            time.sleep(1.5)
        real_save(j)
    monkeypatch.setattr(ctx, "_save_job", slow_terminal_save)
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref, 300)
    job_id = d["runs"][0]["intake_job_id"]
    disk_job = json.loads((ctx.jobdir / f"{job_id}.json").read_text(encoding="utf-8"))
    disk_case = json.loads((ctx.cases.root / f"{ref}.json").read_text(encoding="utf-8"))
    assert disk_job["state"] == "completed" and disk_job["finished_at"]
    assert disk_case["runs"][0]["status"] == "COMPLETED"
    mtimes = {p.name: p.stat().st_mtime_ns for p in (ctx.jobdir / f"{job_id}.json", ctx.cases.root / f"{ref}.json")}
    time.sleep(2.0)                                                   # nothing is written after the view said done
    assert {p.name: p.stat().st_mtime_ns for p in (ctx.jobdir / f"{job_id}.json",
                                                    ctx.cases.root / f"{ref}.json")} == mtimes
