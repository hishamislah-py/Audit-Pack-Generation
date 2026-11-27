"""Phase 3B-11: the UC-042 reconciliation adapter, executed against the REAL (unmodified, read-only) UC-042 engine in an
isolated temporary folder, and the real-browser check of the review screen. Both are skipped when their external
dependency (the UC-042 tree / Microsoft Edge) is absent."""
import json
import sys
from pathlib import Path

import pytest

from smartparser.mapping.rule_store import RuleStore
from smartparser.packages.service import Submission
from smartparser.reconciliation.uc042_adapter import ReconciliationError, run_reconciliation
from smartparser.schemas import SchemaRegistry

from .phase3b_support import SEP, read
from .uc042_support import UC042_ROOT, needs_uc042

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))


def _activated_package(tmp_path):
    from reconcile_3b11 import service
    ws = tmp_path / "ws"
    ws.mkdir()
    RuleStore.initialise(ws / "rules", SchemaRegistry.from_directory())
    svc = service(ws)
    pkg = svc.create_package("2026-09")
    svc.submit(pkg.package_id, [Submission(read(SEP, c), f"f{n}" + (".pdf" if c in ("IN-15", "IN-16", "IN-17") else
                                                                       ".csv"))
                                for n, c in enumerate(pkg.required_evidence_categories)])
    a = svc.activate(pkg.package_id)
    assert a.activated
    return svc, pkg.package_id, a.snapshot.snapshot_id


@needs_uc042
def test_adapter_runs_the_real_engine_isolated_and_traces_back(tmp_path):
    svc, pid, sid = _activated_package(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in UC042_ROOT.joinpath("uc042lib").rglob("*") if p.is_file()}
    rec = run_reconciliation(svc, pid, sid, UC042_ROOT, tmp_path / "runs")
    after = {p: p.stat().st_mtime_ns for p in UC042_ROOT.joinpath("uc042lib").rglob("*") if p.is_file()}
    assert before == after                                                     # nothing written into the UC-042 tree
    assert rec["checks"] == {"all_selected_categories_accepted_by_engine": True, "engine_received_exact_bytes": True,
                             "engine_category_agrees": True, "no_superseded_version_staged": True}
    assert rec["result"]["case_status"] == "CLEAN" and rec["result"]["exceptions"] == []
    assert rec["result"]["outcomes"] == {"PASS": 1882, "NOT_APPLICABLE": 4}
    assert len(rec["input"]["staged"]) == 17 and rec["input"]["snapshot_id"] == sid
    run = tmp_path / "runs" / rec["run_id"]
    assert (run / "case" / "validation" / "control_results.csv").is_file() and (run / "case" / "VALIDATION_REPORT.md").is_file()
    t = rec["traceability"]["by_engine_file"]["sga_cashbook_entries_2026-09.csv"]
    v = svc.load(pid).versions[t["file_version_id"]]
    assert (t["evidence_category"], t["intake_id"], t["source_sha256"]) == ("IN-10", v.intake_id, v.source_sha256)
    ev = [e for e in svc.log.events() if e.event_type.startswith("RECONCILIATION_")]
    assert [e.event_type for e in ev] == ["RECONCILIATION_INPUT_STAGED", "RECONCILIATION_EXECUTED"]
    assert ev[1].details["run_id"] == rec["run_id"] and ev[1].details["snapshot_id"] == sid
    assert json.loads((run / "reconciliation_run.json").read_text(encoding="utf-8"))["run_id"] == rec["run_id"]
    with pytest.raises(ReconciliationError, match="write-once"):
        run_reconciliation(svc, pid, sid, UC042_ROOT, tmp_path / "runs", run_id=rec["run_id"])


@needs_uc042
def test_adapter_refuses_unverifiable_or_unsafe_runs(tmp_path):
    svc, pid, sid = _activated_package(tmp_path)
    with pytest.raises(ReconciliationError, match="outside the UC-042 tree"):
        run_reconciliation(svc, pid, sid, UC042_ROOT, UC042_ROOT / "never_written")
    with pytest.raises(ReconciliationError, match="not the ACTIVE snapshot"):
        run_reconciliation(svc, pid, "SNAP-999-deadbeef", UC042_ROOT, tmp_path / "runs")
    snap = svc.store.load_snapshot(pid, sid)
    pv = svc.store.abs(next(e for e in snap.entries if e.evidence_category == "IN-03").handoff.preview_csv)
    pv.write_bytes(pv.read_bytes() + b"tampered\n")
    with pytest.raises(ReconciliationError, match="snapshot verification failed"):
        run_reconciliation(svc, pid, sid, UC042_ROOT, tmp_path / "runs")
    assert not (UC042_ROOT / "never_written").exists()


EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


@pytest.mark.skipif(not EDGE.exists(), reason="Microsoft Edge not installed")
def test_review_screen_in_a_real_browser(tmp_path):
    import ui_browser_3b11
    res = ui_browser_3b11.run(tmp_path / "ui")
    assert res["all_ok"], [s for s in res["steps"] if not s["ok"]]
    assert len(res["steps"]) == 13 and len(list((tmp_path / "ui").glob("*.png"))) == 10
