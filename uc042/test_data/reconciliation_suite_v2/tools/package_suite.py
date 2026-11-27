"""Write scenario_manifest.json, then build packages/: one ZIP per scenario plus a master ZIP of the whole suite, with SHA256SUMS.txt.

Scenario package = the scenario folder + README.md + UPLOAD_INSTRUCTIONS.md + SCENARIO_CATALOGUE.md, under UC042_RTS_V2_<dir>/.
Master ZIP = the whole suite folder (excluding packages/ itself and _work/negative_tests), under UC042_RECONCILIATION_TEST_SUITE_V2/.
"""
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenario_specs import SCENARIOS  # noqa: E402

SUITE = Path(__file__).resolve().parent.parent
PK = SUITE / "packages"
ZIP_TIME = (2026, 11, 23, 12, 0, 0)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_zip(out, entries):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in sorted(entries):
            zi = zipfile.ZipInfo(arc, ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, Path(src).read_bytes())
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None


def files_under(root):
    return [p for p in Path(root).rglob("*") if p.is_file()]


def manifest():
    vr = json.loads((SUITE / "validation" / "validation_results.json").read_text())
    status = {r["role"]: r["status"] for r in vr["cases"]}
    m = {"suite": "UC042_RECONCILIATION_TEST_SUITE_V2", "status": "GENERATED_AND_VALIDATED_OFFLINE", "prepared": "2026-11-23",
         "datasets_generated": True, "engine_executed": False, "offline_validation": vr["overall"], "period_id": "PER-2026-09",
         "baseline": {"path": "shared_baseline", "manifest_sha256": sha(SUITE / "shared_baseline" / "manifest.csv")},
         "reference_engine": "C:/u42v/e2e_20261122/engine_base/uc042/uc042lib (read only; schema.py parsed with ast, never executed)",
         "expectation_labels": ["FIN", "ENGINE-PREDICTED (not executed)", "FUTURE (PROPOSED)", "AI"], "scenarios": []}
    for s in SCENARIOS:
        sd = SUITE / s["dir"]
        p = s["engine_predicted"]
        e = {"scenario_id": s["scenario_id"], "dir": s["dir"], "title": s["title"], "customer_label": s["customer_label"],
             "operations": len(s["ops"]), "mutated_files": sorted({o["file_id"] for o in s["ops"]}),
             "upload_zips": {z.name: sha(z) for z in sorted((sd / "upload").iterdir())},
             "offline_validation": {"initial": status[f"{s['scenario_id']} initial submission"]},
             "engine_predicted": {"case_status": p["expected_case_status"], "non_passing_results": len(p["non_passing_results"]),
                                  "exceptions": len(p["exceptions"]), "groups": len(p["investigation_groups"]),
                                  "candidates": len(p["candidate_relationships"]), "evidence_statuses": p["evidence_statuses"]},
             "correction": bool(s.get("correction"))}
        if s.get("correction"):
            e["offline_validation"]["corrected"] = status[f"{s['scenario_id']} corrected case"]
            e["engine_predicted_after_correction"] = s["engine_predicted_after_correction"]["expected_case_status"]
            e["correction_files"] = sorted(p.name for p in (sd / "corrections" / "replacement_files" / "source_data").iterdir())
        if s["scenario_id"] == "TC03":
            e["revision"] = "25/26 Sep design (replaces the approved 30 Sep / 1 Oct design); adds Saturday IN-07/IN-08 records for SGA-GBP-01"
        if s["scenario_id"] == "TC06":
            e["engine_predicted"]["note"] = "predicted over-grouping (G-18) UNVERIFIED"
        m["scenarios"].append(e)
    (SUITE / "scenario_manifest.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")


def main():
    manifest()
    if PK.exists():
        shutil.rmtree(PK)
    PK.mkdir()
    shared = ["README.md", "UPLOAD_INSTRUCTIONS.md", "SCENARIO_CATALOGUE.md"]
    for s in SCENARIOS:
        top = f"UC042_RTS_V2_{s['dir']}"
        entries = [(f"{top}/{p.relative_to(SUITE).as_posix()}", p) for p in files_under(SUITE / s["dir"])]
        entries += [(f"{top}/{n}", SUITE / n) for n in shared]
        write_zip(PK / f"{s['dir']}.zip", entries)
    entries = [(f"UC042_RECONCILIATION_TEST_SUITE_V2/{p.relative_to(SUITE).as_posix()}", p) for p in files_under(SUITE)
               if not p.relative_to(SUITE).as_posix().startswith(("packages/", "_work/negative_tests/"))]
    write_zip(PK / "UC042_RECONCILIATION_TEST_SUITE_V2_MASTER.zip", entries)
    sums = [f"{sha(z)}  {z.name}" for z in sorted(PK.glob("*.zip"))]
    (PK / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("\n".join(sums))
    print(f"master entries: {len(entries)}")


if __name__ == "__main__":
    main()
