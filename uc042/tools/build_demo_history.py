"""Build the January–August 2026 historical demonstration: engine-ready case folders and one deterministic pack per month.

ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

Reads the supplied package (UC042_JAN_AUG_HISTORICAL_DEMO) read-only and writes only under demo_history/:
    demo_history/datasets/2026-MM/              the month's source_documents (14 CSV, the PDFs, manifest.csv), copied
                                                after every SHA-256 is verified, plus a neutral scenario.json (identity
                                                H2026MM and the synthetic notice only)
    demo_history/packs/<pack_id>/               the deterministic pack (uc042lib.pack.generate: write-once)
    demo_history/verification/run_manifest.json one record per month (policy used, pack ID, content hash, outcome)

Never copied: scenario_definition.json, mutations.json, the package reports and the generator (they describe the
planted answers; tests use them as offline oracles only). Never written: uc042_dataset/, packs/, investigations/.
A copied file that already exists with different content stops the build (nothing is overwritten).

Usage (from the uc042/ folder):
    python tools/build_demo_history.py [--package DIR] [--out DIR]
"""
import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from uc042lib import policy  # noqa: E402
from uc042lib.investigation.retrieval import pack_policy_version  # noqa: E402
from uc042lib.pack.generate import generate  # noqa: E402
from uc042lib.period import PeriodConfig  # noqa: E402

PACKAGE = PROJECT / "UC042_JAN_AUG_HISTORICAL_DEMO" / "UC042_JAN_AUG_HISTORICAL_DEMO"
OUT = PROJECT / "demo_history"
MONTHS = [PeriodConfig(2026, m) for m in range(1, 9)]
SYNTHETIC = "ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS"

# Policy (IN-17) selection where a month supplies more than one version. The engine refuses to choose (uc042lib.period
# resolve); the version comes from the approved register (uc042lib.policy.APPROVED_SELECTIONS, decision HD-2, approved
# 4 Nov 2026) and is recorded in the run manifest. Every other month uses the single version it supplies. The basis text
# below is the one recorded when the packs were generated (3 Nov 2026); it is kept unchanged so that a rebuild leaves the
# run manifest byte-identical. The May pack itself remains pending review.
POLICY_SELECTION = {
    "2026-05": (policy.APPROVED_SELECTIONS["PER-2026-05"].version, "two versions supplied (illustrative v1.1 for 1-6 May, v1.2 effective 2026-05-07); v1.2 selected as "
                       "the version in force at the period end; identical results under v1.1 (isolated comparison); "
                       "PENDING APPROVAL"),
}


class BuildError(Exception):
    pass


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def scenario_id(period):
    return f"H{period.year:04d}{period.month:02d}"  # [A-Z0-9]{1,12}: the pack and exception ID contract


def verify_package(package):
    """The package's own manifests: month manifest hashes, then every listed file. Returns {token: [manifest.csv rows]}."""
    top = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for m in top["months"]:
        mdir = package / m["period"]
        if sha256(package / m["manifest"]) != m["manifest_sha256"]:
            raise BuildError(f"{m['manifest']}: SHA-256 differs from the package manifest")
        if sha256(mdir / "scenario_definition.json") != m["scenario_definition_sha256"]:
            raise BuildError(f"{m['period']}/scenario_definition.json: SHA-256 differs from the package manifest")
        with open(mdir / "source_documents" / "manifest.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        listed = {r["relative_path"] for r in rows}
        present = {p.relative_to(mdir / "source_documents").as_posix() for p in (mdir / "source_documents").rglob("*") if p.is_file()}
        if present - listed - {"manifest.csv"} or listed - present:
            raise BuildError(f"{m['period']}: files differ from manifest.csv (unlisted {sorted(present - listed - {'manifest.csv'})}, "
                             f"missing {sorted(listed - present)})")
        for r in rows:
            if sha256(mdir / "source_documents" / r["relative_path"]) != r["sha256"]:
                raise BuildError(f"{m['period']}/{r['relative_path']}: SHA-256 differs from manifest.csv")
            if r["reporting_period"] != f"PER-{m['period']}":
                raise BuildError(f"{m['period']}/{r['relative_path']}: manifest period {r['reporting_period']}")
        out[m["period"]] = rows
    if sorted(out) != [p.token for p in MONTHS]:
        raise BuildError(f"package months {sorted(out)} are not 2026-01..2026-08")
    return out


def copy_once(src, dst):
    """Copy src to dst; an existing dst must be byte-identical (never overwritten)."""
    if dst.exists():
        if dst.read_bytes() != src.read_bytes():
            raise BuildError(f"{dst} exists with different content; not overwritten")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def write_once(dst, text):
    if dst.exists():
        if dst.read_text(encoding="utf-8") != text:
            raise BuildError(f"{dst} exists with different content; not overwritten")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8", newline="\n")


def build_case(package, period, rows, out):
    src = package / period.token / "source_documents"
    case = out / "datasets" / period.token
    for r in rows:
        copy_once(src / r["relative_path"], case / r["relative_path"])
    copy_once(src / "manifest.csv", case / "manifest.csv")
    for r in rows:  # the copy, not the source, is what the engine reads
        if sha256(case / r["relative_path"]) != r["sha256"]:
            raise BuildError(f"{case / r['relative_path']}: copy differs from manifest.csv")
    write_once(case / "scenario.json", json.dumps({
        "scenario_id": scenario_id(period), "name": f"Historical demonstration month, {period.label}",
        "synthetic_notice": SYNTHETIC}, indent=1, ensure_ascii=False) + "\n")
    return case


def run(package=PACKAGE, out=OUT):
    package, out = Path(package), Path(out)
    listed = verify_package(package)
    records = []
    for period in MONTHS:
        version, basis = POLICY_SELECTION.get(period.token, (None, "the single policy version the month supplies"))
        case = build_case(package, period, listed[period.token], out)
        cfg = PeriodConfig(period.year, period.month, version)
        rec = generate(case, out / "packs", cfg)
        if rec["status"] != "GENERATED":
            raise BuildError(f"{period.token}: pack not generated: {rec['validation_findings'][:5]}")
        pack = json.loads((out / "packs" / rec["pack_id"] / "pack.json").read_text(encoding="utf-8"))
        inputs = pack["audit_trail"]["inputs"]
        s = pack["executive_summary"]
        records.append({
            "period_id": period.period_id, "dataset": f"datasets/{period.token}", "scenario_id": scenario_id(period),
            "dataset_manifest_sha256": sha256(case / "manifest.csv"),
            "policy_version": pack_policy_version(pack),
            "policy_files_supplied": sorted(i["relative_path"] for i in inputs if i["file_id"] == "IN-17"),
            "policy_basis": basis, "pack_id": rec["pack_id"], "pack_content_sha256": rec["pack_content_sha256"],
            "processing_run_id": rec["processing_run_id"], "engine_case_status": s["engine_case_status"],
            "evidence_completeness": s["evidence_completeness"],
            "engine_results_by_outcome": dict(sorted(Counter(r["outcome"] for c in pack["control_register"] for r in c["results"]).items())),
            "exceptions": [{"exception_id": x["exception_id"], "root_cause": x["root_cause"], "status": x["status"],
                            "investigation_group_id": x["investigation_group_id"]} for x in pack["exception_register"]["exceptions"]],
            "investigation_groups": [{"group_id": g["group_id"], "exception_ids": g["exception_ids"], "link_types": g["link_types"]}
                                     for g in pack["investigation_group_register"]["groups"]],
            "missing_evidence_items": len(pack["missing_evidence_register"]["items"]),
        })
        print(f"{period.token}: {rec['outcome']:<28} {rec['pack_id']}  policy v{records[-1]['policy_version']}  "
              f"exceptions {len(records[-1]['exceptions'])}")
    manifest = {"synthetic_notice": SYNTHETIC, "status": "DETERMINISTIC PACKS ONLY — PENDING REVIEW AND APPROVAL",
                "not_generated": ["AI investigations", "AI closing summaries", "final audit packs"],
                "package": package.name, "months": records}
    (out / "verification").mkdir(parents=True, exist_ok=True)
    (out / "verification" / "run_manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
                                                            encoding="utf-8", newline="\n")
    return manifest


def main():
    ap = argparse.ArgumentParser(description="Build the Jan-Aug 2026 historical demonstration (datasets + deterministic packs)")
    ap.add_argument("--package", default=str(PACKAGE))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    try:
        run(a.package, a.out)
    except BuildError as e:
        sys.exit(f"BUILD STOPPED: {e}")


if __name__ == "__main__":
    main()
