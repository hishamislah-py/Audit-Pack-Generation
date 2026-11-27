"""Phase 3B-11 - a UC-042 SCENARIO WITH KNOWN DISCREPANCIES through Smart Parser -> snapshot -> the existing engine.

    py -3.11 tools/reconcile_scenario_3b11.py --scenario scn_S05_unexplained_gbp_difference --out <dir>

1. reads the scenario dataset's evidence files from the UC-042 tree (READ ONLY; bytes only) and submits them, without
   declared categories, to a NEW Smart Parser package (content classification; deterministic; no LLM);
2. activates the package snapshot and reconciles it through smartparser.reconciliation.uc042_adapter;
3. checks the engine output against the scenario's own answer key with UC-042's compare_answer_key (answer_key.json is
   copied into the run's case folder for that call - the dataset is never written);
4. CONTROL: the same engine on the dataset's original files, compared byte for byte;
5. traces every exception's evidence back to the selected file version / intake / source SHA-256.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

from reconcile_3b11 import UC042, service  # noqa: E402
from smartparser.mapping.rule_store import RuleStore  # noqa: E402
from smartparser.packages.service import Submission  # noqa: E402
from smartparser.reconciliation.uc042_adapter import ENGINE_RUNNER, run_reconciliation  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

ANSWER_RUNNER = r'''
import json, sys
sys.dont_write_bytecode = True
uc042_root, case_dir, period = sys.argv[1:4]
sys.path.insert(0, uc042_root)
from uc042lib.validate import Validator, compare_answer_key
v = Validator(case_dir, period)
results = v.run()
matched, lines = compare_answer_key(case_dir, results, v.exceptions, v.candidates)
print(json.dumps({"matched": matched, "differences": lines}))
'''


def engine_env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("UC042_", "OPENAI", "ANTHROPIC", "GROQ"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scn_S05_unexplained_gbp_difference")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ds = UC042 / "uc042_dataset" / a.scenario
    out = Path(a.out).resolve() / a.scenario
    if out.exists():
        shutil.rmtree(out)
    ws = out / "workspace"
    ws.mkdir(parents=True)
    RuleStore.initialise(ws / "rules", SchemaRegistry.from_directory())
    svc = service(ws)
    with open(ds / "manifest.csv", encoding="utf-8", newline="") as f:
        files = [ds / r["relative_path"] for r in csv.DictReader(f)]
    pkg = svc.create_package("2026-09")                                      # the UC-042 contract: 17 required
    outs = svc.submit(pkg.package_id, [Submission(p.read_bytes(), p.name) for p in files])
    intake = {o.evidence_category: (o.file_version.version_status if o.file_version else o.refused_reason)
              for o in outs}
    act = svc.activate(pkg.package_id)
    if not act.activated:
        raise SystemExit(f"package not activated: {act.reason}; intake {intake}")
    rec = run_reconciliation(svc, pkg.package_id, act.snapshot.snapshot_id, UC042, out / "runs")
    run = out / "runs" / rec["run_id"]
    # answer key (UC-042's own comparison; key copied into the run's case folder only)
    # (a COPY of the case: the run's own outputs stay exactly as the engine wrote them; scenario.json only sets the
    #  scenario's exception-ID prefix - EXC-S05-nn instead of EXC-CASE-nn - and is test metadata, not evidence)
    chk = run / "answer_key_check"
    shutil.copytree(run / "case", chk)
    for meta in ("answer_key.json", "scenario.json"):
        shutil.copyfile(ds / meta, chk / meta)
    p = subprocess.run([sys.executable, "-B", "-c", ANSWER_RUNNER, str(UC042), str(chk), "PER-2026-09"],
                       cwd=str(run), env=engine_env(), capture_output=True, text=True, encoding="utf-8")
    answer = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {"error": p.stderr[-600:]}
    # control on the dataset's original files
    ctl = out / "runs" / "CONTROL-original-dataset-files"
    (ctl / "input").mkdir(parents=True)
    for f in files:
        shutil.copyfile(f, ctl / "input" / f.name)
    c = subprocess.run([sys.executable, "-B", "-c", ENGINE_RUNNER, str(UC042), str(ctl / "input"), str(ctl / "case"),
                        "PER-2026-09"], cwd=str(ctl), env=engine_env(), capture_output=True, text=True, encoding="utf-8")
    if c.returncode:
        raise SystemExit(f"control failed: {c.stderr[-600:]}")
    same = {rel: (run / "case" / rel).read_bytes() == (ctl / "case" / rel).read_bytes()
            for rel in ("validation/control_results.csv", "validation/exceptions.csv", "VALIDATION_REPORT.md")}
    # trace each exception's cited evidence back to Smart Parser file versions
    trace = rec["traceability"]["by_engine_file"]
    rows = list(csv.DictReader(open(run / "case" / "validation" / "control_results.csv", encoding="utf-8")))
    traced = []
    for x in rec["result"]["exceptions"]:
        cited = set()
        for r in rows:
            if r.get("root_cause") == x.get("root_cause") and r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE"):
                for ref in (r.get("evidence") or "").split(";"):
                    ref = ref.strip()
                    if ":" in ref:
                        cited.add(ref.split(":", 1)[1].split("#", 1)[0])
        traced.append({"exception_id": x["exception_id"], "severity": x["severity"], "category": x["category"],
                       "account_id": x.get("account_id"), "amount": x.get("amount"),
                       "period": f"{x.get('first_date')}..{x.get('last_date')}",
                       "affected_results": x.get("affected_results"),
                       "evidence_files": [{"engine_file": n, **trace[n]} for n in sorted(cited) if n in trace]})
    summary = {"scenario": a.scenario, "package_id": pkg.package_id, "snapshot_id": act.snapshot.snapshot_id,
               "smart_parser_intake": intake, "run_id": rec["run_id"], "case_status": rec["result"]["case_status"],
               "check_results": rec["result"]["check_results"], "outcomes": rec["result"]["outcomes"],
               "exceptions": traced, "investigation_groups": rec["result"]["investigation_groups"],
               "adapter_checks": rec["checks"], "answer_key": answer, "control_byte_identical": same,
               "audit_events_verified": svc.log.verify()}
    (out / "scenario_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("scenario", "snapshot_id", "run_id", "case_status", "outcomes",
                                               "adapter_checks", "answer_key", "control_byte_identical")},
                     indent=1, default=str))
    for t in traced:
        print(" ", t["exception_id"], t["severity"], t["category"], t["account_id"], t["amount"], t["period"],
              "->", [(e["evidence_category"], e["file_version_id"], e["source_sha256"][:10]) for e in t["evidence_files"]])


if __name__ == "__main__":
    main()
