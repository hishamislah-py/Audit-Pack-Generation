"""Phase 3B-11 - adapter from an activated Smart Parser package snapshot to the EXISTING UC-042 reconciliation engine.

Contract of the UC-042 engine (read-only inspection of uc042lib.prepare / uc042lib.validate):
  * `prepare_case(input_dir, case_dir, period)` takes a folder of evidence FILES and identifies every file by CONTENT
    only: a CSV must carry exactly one schema's canonical header (UTF-8); a PDF must carry the key-detail labels of one
    supporting-document type (acknowledgement letters resolved through the account inventory IN-02; the policy must be a
    recognised version). File names and any manifest in the input are never trusted. It writes case_dir/source_data,
    case_dir/supporting_documents (canonical file names of the period), manifest.csv and intake.csv.
  * `Validator(case_dir, period).run()` runs the reconciliation controls; `write_outputs(...)` writes
    case_dir/validation/*.csv and case_dir/VALIDATION_REPORT.md.
So the only transformation needed is: put the snapshot's canonical previews (CSV - canonical header, source cells
unchanged) and the PDF originals into an input folder. No mapping, calculation or reconciliation rule is reproduced here.

What this adapter does:
  1. loads the immutable snapshot + manifest and re-verifies them (verify_snapshot SV-1..SV-5);
  2. re-hashes every selected original (evidence store) and every canonical preview against the manifest;
  3. stages exactly the selected versions (never a superseded one) into <run>/input;
  4. runs the UC-042 engine in a SEPARATE Python process with the read-only UC-042 tree on sys.path, bytecode writing
     disabled, working directory and every output inside <run> (nothing is written into the UC-042 tree);
  5. verifies the engine accepted exactly the staged bytes (engine intake SHA-256 = staged SHA-256) for every category;
  6. writes <run>/reconciliation_run.json tracing engine outputs back to package, snapshot, file version, intake ID and
     source SHA-256, and audits RECONCILIATION_INPUT_STAGED / RECONCILIATION_EXECUTED (or _FAILED).
Nothing is submitted and no audit pack is generated or published.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ENGINE_RUNNER = r'''
import json, sys
sys.dont_write_bytecode = True
uc042_root, input_dir, case_dir, period = sys.argv[1:5]
sys.path.insert(0, uc042_root)
from uc042lib.prepare import prepare_case
from uc042lib.validate import Validator, case_status, write_outputs
intake = prepare_case(input_dir, case_dir, period)
v = Validator(case_dir, period)
results = v.run()
status = case_status(v)
totals = write_outputs(case_dir, results, v.exceptions, status, v.groups, v.candidates, v.pdf, v.period, v.rules)
print(json.dumps({"intake": intake, "results": len(results), "totals": totals, "case_status": status,
                  "exceptions": v.exceptions, "groups": v.groups, "candidates": v.candidates,
                  "period": v.period.period_id}, default=str))
'''


class ReconciliationError(RuntimeError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_reconciliation(svc, package_id: str, snapshot_id: str, uc042_root: str | Path, out_dir: str | Path,
                       python: str | None = None, run_id: str | None = None) -> dict:
    uc042_root, out_dir = Path(uc042_root).resolve(), Path(out_dir).resolve()
    if uc042_root == out_dir or uc042_root in out_dir.parents:
        raise ReconciliationError("the reconciliation output must be outside the UC-042 tree")
    pkg = svc.load(package_id)
    if snapshot_id != pkg.active_snapshot_id:
        raise ReconciliationError(f"{snapshot_id} is not the ACTIVE snapshot ({pkg.active_snapshot_id}); a superseded "
                                  "selection is never reconciled")
    snap = svc.store.load_snapshot(package_id, snapshot_id)
    checks = svc.verify_snapshot(package_id, snapshot_id)
    if not all(c.passed for c in checks):
        raise ReconciliationError("snapshot verification failed: " + "; ".join(f"{c.check_id} {c.detail}"
                                                                               for c in checks if not c.passed))
    manifest = json.loads(svc.store.manifest_path(package_id, snapshot_id).read_text(encoding="utf-8"))
    run_id = run_id or f"RECON-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{snapshot_id[-8:]}"
    run = out_dir / run_id
    if run.exists():
        raise ReconciliationError(f"{run} already exists (runs are write-once)")
    (run / "input").mkdir(parents=True)

    # ---- stage exactly the selected versions (verified)
    staged = []
    for f in manifest["files"]:
        v = pkg.versions[f["file_version_id"]]
        original = svc.evidence.read_original(f["source_sha256"])
        rec = svc.evidence.find(f["intake_id"])
        if original is None or _sha(original) != f["source_sha256"] or rec is None or rec.sha256 != f["source_sha256"]:
            raise ReconciliationError(f"{f['evidence_category']}: stored original / intake does not match the manifest")
        if v.version_status != "ACTIVE" or v.file_version_id != pkg.evidence_files[f["evidence_category"]].active_version_id:
            raise ReconciliationError(f"{f['evidence_category']}: {v.file_version_id} is not the active version")
        if f["canonical_preview"]:
            data = svc.store.abs(f["canonical_preview"]["path"]).read_bytes()
            if _sha(data) != f["canonical_preview"]["sha256"]:
                raise ReconciliationError(f"{f['evidence_category']}: canonical preview hash mismatch")
            kind, ext = "CANONICAL_PREVIEW_CSV", "csv"
        else:
            data, kind, ext = original, "ORIGINAL_PDF", "pdf"
        name = f"{f['evidence_category']}__{f['file_version_id']}.{ext}"
        (run / "input" / name).write_bytes(data)
        staged.append({"evidence_category": f["evidence_category"], "file_version_id": f["file_version_id"],
                       "version_number": f["version_number"], "intake_id": f["intake_id"],
                       "original_filename": f["original_filename"], "source_sha256": f["source_sha256"],
                       "staged_file": f"input/{name}", "staged_kind": kind, "staged_sha256": _sha(data)})
    period = "PER-" + pkg.reporting_period
    svc.log.append("RECONCILIATION_INPUT_STAGED", actor_id="smartparser-reconciliation-adapter", actor_role="system",
                   details={"package_id": package_id, "snapshot_id": snapshot_id, "run_id": run_id,
                            "reporting_period": pkg.reporting_period, "files": [
                                {k: s[k] for k in ("evidence_category", "file_version_id", "staged_sha256")}
                                for s in staged]})

    # ---- run the existing UC-042 engine, isolated
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("UC042_", "OPENAI", "ANTHROPIC", "GROQ"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run([python or sys.executable, "-B", "-c", ENGINE_RUNNER, str(uc042_root), str(run / "input"),
                           str(run / "case"), period], cwd=str(run), env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=600)
    (run / "engine_stdout.json").write_text(proc.stdout, encoding="utf-8")
    (run / "engine_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        svc.log.append("RECONCILIATION_FAILED", actor_id="smartparser-reconciliation-adapter", actor_role="system",
                       details={"package_id": package_id, "snapshot_id": snapshot_id, "run_id": run_id,
                                "returncode": proc.returncode, "stderr_tail": proc.stderr[-800:]})
        raise ReconciliationError(f"UC-042 engine failed (exit {proc.returncode}): {proc.stderr[-800:]}")
    eng = json.loads(proc.stdout.strip().splitlines()[-1])

    # ---- the engine accepted exactly the staged bytes?
    by_path = {s["staged_file"].split("/", 1)[1]: s for s in staged}
    accepted = {}
    for row in eng["intake"]:
        s = by_path.get(row["original_path"])
        if s is not None:
            s["engine_decision"], s["engine_file_id"] = row["decision"], row["file_id"]
            s["engine_canonical_name"], s["engine_reason"] = row["canonical_name"], row["reason"]
            if row["decision"] == "ACCEPTED":
                accepted[row["file_id"]] = s
    for s in staged:
        sub = "source_data" if s["staged_kind"] == "CANONICAL_PREVIEW_CSV" else "supporting_documents"
        p = run / "case" / sub / (s.get("engine_canonical_name") or "")
        s["engine_case_sha256"] = _sha(p.read_bytes()) if s.get("engine_canonical_name") and p.is_file() else None
        s["engine_received_exact_bytes"] = s["engine_case_sha256"] == s["staged_sha256"]
        s["category_agrees"] = s.get("engine_file_id") == s["evidence_category"]
    not_staged = [r for r in eng["intake"] if r["original_path"] not in by_path]   # MISSING rows etc.

    # ---- outputs + traceability
    out_files = {str(p.relative_to(run)).replace("\\", "/"): _sha(p.read_bytes())
                 for p in sorted((run / "case").rglob("*")) if p.is_file()}
    trace = {s["engine_canonical_name"]: {k: s[k] for k in ("evidence_category", "file_version_id", "intake_id",
                                                            "source_sha256", "staged_sha256")}
             for s in staged if s.get("engine_canonical_name")}
    rows = list(csv.DictReader(open(run / "case" / "validation" / "control_results.csv", encoding="utf-8")))
    outcomes = Counter(r["outcome"] for r in rows)
    traced_examples = []
    for r in rows:
        refs = [e.strip() for e in (r.get("evidence") or "").split(";") if e.strip()]
        hits = []
        for ref in refs:
            name = ref.split(":", 1)[1].split("#", 1)[0] if ":" in ref else None
            if name in trace:
                hits.append({"reference": ref, **trace[name]})
        if hits and r["outcome"] != "PASS" or (hits and len(traced_examples) < 3):
            traced_examples.append({"check_id": r["check_id"], "outcome": r["outcome"], "scope": r["scope"],
                                    "evidence": hits[:4]})
        if len(traced_examples) >= 8:
            break
    record = {
        "run_id": run_id, "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": {"implementation": "uc042lib.prepare.prepare_case + uc042lib.validate.Validator.run + write_outputs "
                                     "(unmodified, imported read-only from the UC-042 tree)",
                   "uc042_root": str(uc042_root), "python": python or sys.executable, "returncode": proc.returncode,
                   "period": eng["period"]},
        "input": {"package_id": package_id, "snapshot_id": snapshot_id, "selection_sha256": snap.selection_sha256,
                  "manifest_status": manifest["status"], "snapshot_checks": [(c.check_id, c.passed) for c in checks],
                  "staged": staged, "engine_intake_rows_not_from_staging": not_staged},
        "result": {"case_status": eng["case_status"], "check_results": eng["results"], "outcomes": dict(outcomes),
                   "totals": eng["totals"], "exceptions": eng["exceptions"], "investigation_groups": eng["groups"],
                   "candidates": eng["candidates"]},
        "traceability": {"by_engine_file": trace, "examples": traced_examples},
        "outputs": out_files,
        "submission": "none (no audit pack generated or published; nothing submitted)",
    }
    record["checks"] = {
        "all_selected_categories_accepted_by_engine": all(s.get("engine_decision") == "ACCEPTED" for s in staged),
        "engine_received_exact_bytes": all(s["engine_received_exact_bytes"] for s in staged),
        "engine_category_agrees": all(s["category_agrees"] for s in staged),
        "no_superseded_version_staged": all(pkg.versions[s["file_version_id"]].version_status == "ACTIVE" for s in staged),
    }
    (run / "reconciliation_run.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    svc.log.append("RECONCILIATION_EXECUTED", actor_id="smartparser-reconciliation-adapter", actor_role="system",
                   details={"package_id": package_id, "snapshot_id": snapshot_id, "run_id": run_id,
                            "case_status": eng["case_status"], "outcomes": dict(outcomes),
                            "exceptions": len(eng["exceptions"]), "checks": record["checks"],
                            "run_record_sha256": _sha((run / "reconciliation_run.json").read_bytes())})
    return record
