"""Read-only views over the files a reconciliation run already wrote (reconciliation_run.json from the adapter;
case/validation/*.csv and VALIDATION_REPORT.md from the UC-042 engine). Nothing is recomputed: rows are returned as the
engine wrote them; the only derived values are counts and the resolution of evidence references to the staged input."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
AFFECTED = re.compile(r"^(?P<check>\S+)\s+(?P<scope>.*?)\s*\[(?P<outcome>[A-Z_]+)\]$")
EVIDENCE = re.compile(r"^(?P<cat>IN-\d{2}):(?P<file>[^#]+?)(?:#L(?P<line>\d+))?$")


class RunNotFound(LookupError):
    pass


def _csv(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def run_dir(runs_root: Path, run_id: str) -> Path:
    if not RUN_ID.match(run_id or ""):
        raise RunNotFound(run_id)
    d = (runs_root / run_id).resolve()
    if d.parent != runs_root.resolve() or not (d / "reconciliation_run.json").is_file():
        raise RunNotFound(run_id)
    return d


def load_record(d: Path) -> dict:
    return json.loads((d / "reconciliation_run.json").read_text(encoding="utf-8"))


def list_runs(runs_root: Path, package_id: str | None = None) -> list[dict]:
    out = []
    if not runs_root.is_dir():
        return out
    for p in runs_root.glob("*/reconciliation_run.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        inp, res = rec.get("input", {}), rec.get("result", {})
        if package_id and inp.get("package_id") != package_id:
            continue
        out.append({"run_id": rec.get("run_id"), "executed_at": rec.get("executed_at"),
                    "package_id": inp.get("package_id"), "snapshot_id": inp.get("snapshot_id"),
                    "case_status": res.get("case_status"), "outcomes": res.get("outcomes", {}),
                    "exception_count": len(res.get("exceptions") or []), "checks": rec.get("checks", {})})
    return sorted(out, key=lambda r: r["executed_at"] or "", reverse=True)


def summary(d: Path) -> dict:
    rec = load_record(d)
    res, inp = rec["result"], rec["input"]
    exc = exceptions(d)
    outcomes = res.get("outcomes", {})
    return {
        "run_id": rec["run_id"], "executed_at": rec["executed_at"], "engine": rec["engine"],
        "package_id": inp["package_id"], "snapshot_id": inp["snapshot_id"],
        "selection_sha256": inp["selection_sha256"], "manifest_status": inp["manifest_status"],
        "snapshot_checks": inp["snapshot_checks"],
        "staged": [{k: s.get(k) for k in ("evidence_category", "file_version_id", "version_number", "original_filename",
                                          "staged_kind", "engine_decision", "engine_canonical_name",
                                          "engine_received_exact_bytes", "category_agrees")} for s in inp["staged"]],
        "case_status": res["case_status"], "total_results": sum(outcomes.values()), "outcomes": outcomes,
        "exception_count": len(exc),
        "by_severity": dict(Counter(e["severity"] for e in exc)),
        "integrity_checks": rec["checks"], "submission": rec.get("submission"),
        "filters": {"severity": sorted({e["severity"] for e in exc}), "account_id": sorted({e["account_id"] for e in exc
                                                                                           if e["account_id"]}),
                    "currency": sorted({e["currency"] for e in exc if e["currency"]}),
                    "status": sorted({e["status"] for e in exc if e["status"]})},
        "outputs": sorted(rec.get("outputs", {})),
    }


def exceptions(d: Path) -> list[dict]:
    return _csv(d / "case" / "validation" / "exceptions.csv")


def controls(d: Path) -> list[dict]:
    return _csv(d / "case" / "validation" / "control_results.csv")


def report(d: Path) -> str:
    p = d / "case" / "VALIDATION_REPORT.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _staged_row(d: Path, rec: dict, cat: str, line: int | None) -> dict | None:
    """The row the reference points at, read from the canonical input staged for that category (the bytes the engine
    received). Line numbers are physical lines of the canonical file (header = line 1)."""
    st = next((s for s in rec["input"]["staged"] if s["evidence_category"] == cat), None)
    if st is None or line is None or st["staged_kind"] != "CANONICAL_PREVIEW_CSV":
        return None
    p = d / st["staged_file"]
    if not p.is_file():
        return None
    with open(p, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not (2 <= line <= len(rows)):
        return None
    return dict(zip(rows[0], rows[line - 1]))


def resolve_evidence(d: Path, rec: dict, refs: str) -> list[dict]:
    trace = rec.get("traceability", {}).get("by_engine_file", {})
    out = []
    for ref in [r.strip() for r in (refs or "").split(";") if r.strip()]:
        m = EVIDENCE.match(ref)
        item = {"reference": ref}
        if m:
            line = int(m["line"]) if m["line"] else None
            t = trace.get(m["file"], {})
            st = next((s for s in rec["input"]["staged"] if s["file_version_id"] == t.get("file_version_id")), {})
            item.update(evidence_category=m["cat"], engine_file=m["file"], line=line,
                        file_version_id=t.get("file_version_id"), intake_id=t.get("intake_id"),
                        source_sha256=t.get("source_sha256"), original_filename=st.get("original_filename"),
                        version_number=st.get("version_number"), row=_staged_row(d, rec, m["cat"], line))
        out.append(item)
    return out


def exception_detail(d: Path, exception_id: str) -> dict:
    rec = load_record(d)
    exc = next((e for e in exceptions(d) if e["exception_id"] == exception_id), None)
    if exc is None:
        raise RunNotFound(exception_id)
    ctl = controls(d)
    index = {(r["check_id"], r["scope"]): r for r in ctl}
    affected = []
    for part in [p.strip() for p in (exc.get("affected") or "").split(";") if p.strip()]:
        m = AFFECTED.match(part)
        row = index.get((m["check"], m["scope"])) if m else None
        affected.append({"text": part, "check_id": m["check"] if m else None, "scope": m["scope"] if m else None,
                         "outcome": m["outcome"] if m else None, "control_result": row})
    groups = _csv(d / "case" / "validation" / "investigation_groups.csv")
    group = next((g for g in groups if g["group_id"] == exc.get("investigation_group_id")), None)
    return {"exception": exc, "affected_control_results": affected,
            "evidence": resolve_evidence(d, rec, exc.get("evidence", "")),
            "investigation_group": group,
            "note": "values as written by the UC-042 engine; no investigation decision or resolution is made here"}
