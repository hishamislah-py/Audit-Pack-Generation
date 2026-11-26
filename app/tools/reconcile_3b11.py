"""Phase 3B-11 - execute the EXISTING UC-042 reconciliation engine on the activated Smart Parser snapshot (isolated).

    py -3.11 tools/reconcile_3b11.py --source <3B-10 live A_full_package workspace> --out <3B-11 reconciliation dir>

1. copies the 3B-10 workspace (the complete 17-category package activated in Scenario A, whose IN-10 was mapped by the
   live LLM and auto-accepted) into <out>/workspace - the 3B-10 evidence itself is never modified;
2. runs smartparser.reconciliation.uc042_adapter.run_reconciliation on the ACTIVE snapshot;
3. CONTROL: runs the same unmodified engine on the ORIGINAL canonical fixture files of the same 17 categories and
   compares outputs byte for byte (does reconciling through Smart Parser change any engine result?);
4. writes <out>/reconciliation_summary.json.
All engine inputs / outputs are under <out>; the UC-042 tree is only imported (bytecode writing disabled).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from smartparser.ai.config import AIConfig  # noqa: E402
from smartparser.ai.gateway import DisabledLiveProvider, ProposalGateway  # noqa: E402
from smartparser.intake.store import EvidenceStore  # noqa: E402
from smartparser.mapping.rule_store import RuleStore  # noqa: E402
from smartparser.orchestration.orchestrator import MappingOrchestrator  # noqa: E402
from smartparser.orchestration.policy import PocAutoAcceptPolicy  # noqa: E402
from smartparser.packages.service import PackageService  # noqa: E402
from smartparser.packages.store import PackageStore  # noqa: E402
from smartparser.reconciliation.uc042_adapter import ENGINE_RUNNER, run_reconciliation  # noqa: E402
from smartparser.review.audit import AuditLog  # noqa: E402
from smartparser.review.authority import AuthorityPolicy  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

UC042 = Path(r"C:\Users\artlptp263user\p10\uc042_token_optimisation")
SEP = HERE / "tests" / "fixtures" / "uc042_canonical" / "PER-2026-09_set_01_clean_baseline"


def service(ws: Path) -> PackageService:
    reg = SchemaRegistry.from_directory()
    log = AuditLog(ws / "audit.jsonl")
    gw = ProposalGateway(proposer=DisabledLiveProvider(), config=AIConfig(), log=log)
    orch = MappingOrchestrator(reg, RuleStore(ws / "rules", reg), EvidenceStore(ws / "evidence"), gw,
                               PocAutoAcceptPolicy.load(), log)
    return PackageService(PackageStore(ws / "pk"), orch, AuthorityPolicy.load())


def control_run(out: Path, categories: list[str]) -> dict:
    """The same engine on the ORIGINAL canonical fixture files of the given categories (no Smart Parser involved)."""
    run = out / "CONTROL-original-fixture-files"
    if run.exists():
        shutil.rmtree(run)
    (run / "input").mkdir(parents=True)
    with open(SEP / "manifest.csv", encoding="utf-8", newline="") as f:
        rows = {r["file_id"]: SEP / r["relative_path"] for r in csv.DictReader(f)}
    for c in categories:
        shutil.copyfile(rows[c], run / "input" / f"{c}{rows[c].suffix}")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("UC042_", "OPENAI", "ANTHROPIC", "GROQ"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-B", "-c", ENGINE_RUNNER, str(UC042), str(run / "input"), str(run / "case"),
                        "PER-2026-09"], cwd=str(run), env=env, capture_output=True, text=True, encoding="utf-8")
    (run / "engine_stdout.json").write_text(p.stdout, encoding="utf-8")
    (run / "engine_stderr.txt").write_text(p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError(f"control engine run failed: {p.stderr[-600:]}")
    return {"run": run, "engine": json.loads(p.stdout.strip().splitlines()[-1])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    ws = out / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(a.source, ws)
    svc = service(ws)
    (pid,) = svc.store.list()
    pkg = svc.load(pid)
    rec = run_reconciliation(svc, pid, pkg.active_snapshot_id, UC042, out / "runs")
    run_dir = out / "runs" / rec["run_id"]
    cats = sorted(s["evidence_category"] for s in rec["input"]["staged"])
    ctl = control_run(out / "runs", cats)
    cmp = {}
    for rel in ("validation/control_results.csv", "validation/exceptions.csv", "VALIDATION_REPORT.md",
                "manifest.csv"):
        a_p, b_p = run_dir / "case" / rel, ctl["run"] / "case" / rel
        if a_p.exists() or b_p.exists():
            cmp[rel] = (a_p.exists() and b_p.exists() and a_p.read_bytes() == b_p.read_bytes())
    for sub in ("source_data", "supporting_documents"):
        names = sorted(p.name for p in (run_dir / "case" / sub).iterdir())
        cmp[f"{sub}/* bytes"] = names == sorted(p.name for p in (ctl["run"] / "case" / sub).iterdir()) and all(
            (run_dir / "case" / sub / n).read_bytes() == (ctl["run"] / "case" / sub / n).read_bytes() for n in names)
    summary = {"run_id": rec["run_id"], "package_id": pid, "snapshot_id": pkg.active_snapshot_id,
               "selection_sha256": rec["input"]["selection_sha256"], "case_status": rec["result"]["case_status"],
               "check_results": rec["result"]["check_results"], "outcomes": rec["result"]["outcomes"],
               "exceptions": [{k: x.get(k) for k in ("exception_id", "severity", "category", "account_id", "amount",
                                                     "first_date", "last_date", "affected_results")}
                              for x in rec["result"]["exceptions"]],
               "investigation_groups": len(rec["result"]["investigation_groups"]),
               "candidates": len(rec["result"]["candidates"]), "adapter_checks": rec["checks"],
               "engine_decisions": {s["evidence_category"]: s.get("engine_decision") for s in rec["input"]["staged"]},
               "engine_intake_rows_not_from_staging": rec["input"]["engine_intake_rows_not_from_staging"],
               "control": {"case_status": ctl["engine"]["case_status"], "check_results": ctl["engine"]["results"],
                           "exceptions": len(ctl["engine"]["exceptions"]), "byte_comparison": cmp},
               "run_record": str((run_dir / "reconciliation_run.json").relative_to(out)),
               "run_record_sha256": hashlib.sha256((run_dir / "reconciliation_run.json").read_bytes()).hexdigest(),
               "audit_events_verified": svc.log.verify()}
    (out / "reconciliation_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("run_id", "snapshot_id", "case_status", "check_results", "outcomes",
                                               "adapter_checks")}, indent=1, default=str))
    print("exceptions:", len(summary["exceptions"]), "control:", json.dumps(summary["control"], default=str))


if __name__ == "__main__":
    main()
