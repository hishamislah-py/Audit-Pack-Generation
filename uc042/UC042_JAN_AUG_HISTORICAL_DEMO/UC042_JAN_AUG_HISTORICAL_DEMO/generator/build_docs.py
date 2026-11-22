"""Write the package manifests, scenario definitions, scenario matrix and reports from verified data (no hand-typed figures).

    python generator/build_docs.py --project /path/to/uc042
Run after generate_history.py and both verification scripts.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
MONTHS = [f"2026-{m:02d}" for m in range(1, 9)]
NAMES = {"2026-01": "January", "2026-02": "February", "2026-03": "March", "2026-04": "April", "2026-05": "May", "2026-06": "June",
         "2026-07": "July", "2026-08": "August"}
SYN = "ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS"
LABEL = {"MISSING_EUR_STATEMENT": "Missing EUR bank statement", "UNEXPLAINED_GBP_DIFFERENCE": "Unexplained GBP discrepancy",
         "INCONSISTENT_SETTLEMENT_REFERENCE": "Inconsistent settlement reference"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def money(c):
    c = int(c)
    s = f"{abs(c) // 100:,}.{abs(c) % 100:02d}"
    return ("−" if c < 0 else "") + s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    run = json.loads((PKG / "generator" / "_last_run.json").read_text())
    dq = json.loads((PKG / "verification" / "data_quality_results.json").read_text())
    eng = json.loads((PKG / "verification" / "engine_prevalidation_results.json").read_text())
    import sys
    sys.path.insert(0, str(PKG / "generator"))
    from generate_history import PLAN
    base_manifest = Path(a.project) / "uc042_dataset" / "set_01_clean_baseline" / "manifest.csv"
    root_months = []
    matrix = []
    for p in MONTHS:
        r, q, e = run[p], dq["months"][p], eng[p]
        kinds = PLAN[p]
        man = list(csv.DictReader(open(PKG / p / "source_documents" / "manifest.csv", encoding="utf-8")))
        manifest = {
            "synthetic_notice": SYN, "period_id": f"PER-{p}", "period": p, "month": NAMES[p],
            "reporting_period": {"start": f"{p}-01", "end": f"{p}-{q['days']:02d}", "calendar_days": q["days"], "reconciliation_days": q["recon_days"],
                                 "opening_point": f"{q['prev_end']} 17:00 Europe/London", "closing_point": f"{q['last_recon_day']} 17:00 Europe/London",
                                 "timestamp_offsets_used": q["offsets"]},
            "generation": {"generator": "generator/generate_history.py", "seed": r["seed"], "deterministic": True},
            "scenario_composition": kinds or ["CLEAN"],
            "files": [{k: m[k] for k in ("file_id", "relative_path", "format", "requirement", "record_count", "record_unit", "sha256")} for m in man],
            "supporting_documents": r["documents"],
            "engine_manifest": {"path": "source_documents/manifest.csv", "sha256": sha(PKG / p / "source_documents" / "manifest.csv")},
            "mutations": {"path": "mutations.json", "operations": r["ops_count"], "sha256": sha(PKG / p / "mutations.json")},
            "processing_status": {"project_engine_run": "NOT_RUN (to be run by Claude Code with the period-configured engine)",
                                  "pre_validation": "existing engine with the period patched in memory (verification/prevalidate_engine.py)",
                                  "deterministic_pack": "NOT_GENERATED", "ai_investigation": "NOT_RUN", "ai_closing_summary": "NOT_RUN", "final_audit_pack": "NOT_GENERATED"}}
        (PKG / p / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        sd = {
            "synthetic_notice": SYN, "period_id": f"PER-{p}", "scenario_types": [LABEL[k] for k in kinds] or ["Clean baseline"],
            "expected_discrepancy_types": len(kinds), "planted": r["expect"],
            "expected_missing_records": [x["removed"] | {"date": x["date"], "account": x["account"]} for x in r["expect"] if x["scenario"] == "MISSING_EUR_STATEMENT"],
            "expected_reconciliation_outcome": {
                "case_status": "CLEAN" if not kinds else ("EVIDENCE_INCOMPLETE" if "MISSING_EUR_STATEMENT" in kinds else "EXCEPTIONS_OPEN"),
                "evidence_completeness": "INCOMPLETE" if "MISSING_EUR_STATEMENT" in kinds else "COMPLETE",
                "exceptions": len(e["exceptions"]), "exception_root_causes": [x["root_cause"] for x in e["exceptions"]],
                "investigation_groups": [g["exception_ids"] for g in e["groups"]], "all_exceptions_open": True},
            "evidence_relationships": "All planted records keep the project's reference keys: bank_reference / end_to_end_ref ↔ cash-book payment_reference; "
                                      "batch expected_bank_reference ↔ bank entry; settlement line txn_id ↔ transaction; refund original_txn_id.",
            "basis_of_expectations": "Scenario design (generator mutations) confirmed by PRE-VALIDATION: the existing project engine run with the period "
                                     "patched in memory. Claude Code must reproduce these with the real period-configured engine.",
            "pre_validation_observed": {"case_status": e["case_status"], "results_by_outcome": e["results_by_outcome"],
                                        "exceptions": e["exceptions"], "groups": e["groups"], "policy_file_used": e["policy_file_used"]}}
        (PKG / p / "scenario_definition.json").write_text(json.dumps(sd, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = sum(int(m["record_count"]) for m in man if m["format"] == "CSV")
        matrix.append({"month": p, "scenario_composition": " + ".join(LABEL[k] for k in kinds) or "Clean baseline", "discrepancy_types": len(kinds),
                       "reconciliation_days": q["recon_days"], "csv_files": 14, "csv_rows": rows,
                       "pdf_files": sum(1 for m in man if m["format"] == "PDF"),
                       "expected_case_status": sd["expected_reconciliation_outcome"]["case_status"],
                       "expected_exceptions": len(e["exceptions"]), "investigation_groups": len(e["groups"]),
                       "pre_validated": "YES" if e["case_status"] == sd["expected_reconciliation_outcome"]["case_status"] else "MISMATCH"})
        root_months.append({"period": p, "manifest": f"{p}/manifest.json", "manifest_sha256": sha(PKG / p / "manifest.json"),
                            "scenario_definition_sha256": sha(PKG / p / "scenario_definition.json")})
    with open(PKG / "scenario_matrix.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(matrix[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(matrix)
    (PKG / "manifest.json").write_text(json.dumps({
        "package": "UC042_JAN_AUG_HISTORICAL_DEMO", "synthetic_notice": SYN, "months": root_months,
        "september_reference": {"baseline_manifest": "uc042_dataset/set_01_clean_baseline/manifest.csv", "sha256_at_generation": sha(base_manifest),
                                "note": "September 2026 is not part of this package and was not modified."},
        "october_2026": "NO DATA", "november_2026": "AVAILABLE FOR FRESH UPLOAD (no data generated)"}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote manifests, scenario definitions, scenario_matrix.csv")
    for m in matrix:
        print(m)


if __name__ == "__main__":
    main()
