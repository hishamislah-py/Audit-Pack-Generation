"""Generate an audit pack: run the engine once, assemble, validate, render, publish write-once.

Usage (from the uc042/ folder):
    python -m uc042lib.pack.generate uc042_dataset/set_01_clean_baseline [--packs-root packs]

Layout (write-once):
    packs/<pack_id>/pack.json              canonical, deterministic content (source of truth)
    packs/<pack_id>/pack.html              rendered from pack.json only
    packs/<pack_id>/processing/*.csv       the engine run's outputs used by the pack (hashes in the audit trail)
    packs/<pack_id>/generations/*.json     one generation record per attempt (volatile: timestamps) (D5)
    packs/_failed/<run_id>/<ts>.json       failed attempts: no pack is published
"""
import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import model
from ..period import PeriodConfig, PeriodError
from .assemble import PackError, assemble, finalise, load_sources, processing_outputs
from .render_html import render_html
from .validate_pack import validate_pack

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT / "packs"


class ImmutabilityError(Exception):
    pass


def build(case_dir, period=None):
    """Pure generation for one reporting period (PeriodConfig or PER-YYYY-MM; without it, the period the case declares):
    returns (status, pack, html, outputs, findings). Nothing is written."""
    try:
        pack, v = assemble(case_dir, period=period)
        outputs = processing_outputs(v)
        pack = finalise(pack, outputs)
        rows, _, _ = load_sources(case_dir, v.period)
        findings = validate_pack(pack, v, rows)
    except (PackError, PeriodError) as e:
        return "FAILED", None, None, None, [f"ASSEMBLY: {e}"]
    if findings:
        return "FAILED", pack, None, outputs, findings
    return "GENERATED", pack, render_html(pack), outputs, []


def _record(status, case_dir, pack, findings, outcome):
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": status, "outcome": outcome,
            "case_dir": str(case_dir), "pack_id": pack["metadata"]["pack_id"] if pack else "",
            "processing_run_id": pack["metadata"]["processing_run_id"] if pack else "",
            "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"] if pack else "",
            "validation_findings": findings, "python": platform.python_version()}


def generate(case_dir, packs_root=DEFAULT_ROOT, period=None):
    """Generate and publish. Returns the generation record. Existing packs are never modified."""
    packs_root = Path(packs_root)
    packs_root.mkdir(parents=True, exist_ok=True)
    status, pack, html, outputs, findings = build(case_dir, period)
    if status == "FAILED":
        rec = _record("FAILED", case_dir, pack, findings, "NOT_PUBLISHED")
        d = packs_root / "_failed" / (pack["metadata"]["processing_run_id"] if pack else "no-run")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{rec['generated_at'].replace(':', '')}.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        return rec
    text = model.canonical(pack)
    target = packs_root / pack["metadata"]["pack_id"]
    if target.exists():
        if (target / "pack.json").read_text(encoding="utf-8") != text:
            raise ImmutabilityError(f"{target} exists with different content; packs are never overwritten")
        rec = _record("GENERATED", case_dir, pack, [], "ALREADY_GENERATED_IDENTICAL")
    else:
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=packs_root))
        try:
            (tmp / "pack.json").write_text(text, encoding="utf-8")
            (tmp / "pack.html").write_text(html, encoding="utf-8")
            (tmp / "processing").mkdir()
            for name, content in outputs.items():
                (tmp / "processing" / name).write_text(content, encoding="utf-8")
            (tmp / "generations").mkdir()
            os.chmod(tmp, 0o755)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)
        rec = _record("GENERATED", case_dir, pack, [], "PUBLISHED")
    gen = target / "generations"
    n = len(list(gen.glob("*.json"))) + 1
    (gen / f"{n:04d}.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    return rec


def main():
    ap = argparse.ArgumentParser(description="Generate a UC-042 audit pack")
    ap.add_argument("case_dir")
    ap.add_argument("--packs-root", default=str(DEFAULT_ROOT))
    ap.add_argument("--period", help="reporting period PER-YYYY-MM (default: the period the case declares)")
    ap.add_argument("--policy-version", help="policy (IN-17) version N.N, with --period (default: the version the case supplies)")
    a = ap.parse_args()
    if a.policy_version and not a.period:
        ap.error("--policy-version needs --period")
    try:
        period = PeriodConfig.from_id(a.period, a.policy_version) if a.period else None
    except PeriodError as e:
        ap.error(str(e))
    rec = generate(a.case_dir, a.packs_root, period)
    print(f"{rec['status']} ({rec['outcome']}): {rec['pack_id'] or '-'}")
    for f in rec["validation_findings"][:20]:
        print("  " + f)
    if rec["status"] == "GENERATED":
        p = json.loads((Path(a.packs_root) / rec["pack_id"] / "pack.json").read_text())
        s = p["executive_summary"]
        print(f"  evidence {s['evidence_completeness']}; controls {s['control_outcomes']['summary']} "
              f"({s['control_outcomes']['by_outcome']}); exceptions {s['exceptions']['total']}; groups {s['investigation_groups']}; "
              f"candidates {s['candidate_relationships']}; missing evidence {s['missing_evidence_items']}")
        print(f"  {Path(a.packs_root) / rec['pack_id'] / 'pack.html'}")
    sys.exit(0 if rec["status"] == "GENERATED" else 1)


if __name__ == "__main__":
    main()
