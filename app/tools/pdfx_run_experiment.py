"""Experiment A runner: extract every test PDF, compare with ground truth, check originals unchanged and reproducibility.

Usage:  py -3.11 tools/pdfx_run_experiment.py <fixtures_root> <oracle.json> <constructed_dir> <out_dir>

Ground truth:
  * real UC-042 PDFs   -> UC-042's own extraction (uc042lib.prepare._pdf_details / identify / policy.recognise),
                          captured read-only in <oracle.json>;
  * constructed PDFs   -> the values the variant builder wrote (variants_manifest.json).
Writes only into <out_dir>. Reads the PDFs; asserts each file's SHA-256 is identical before and after.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smartparser.pdf_extraction import extract_document  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_case(reg, path: Path, inventory, period, label):
    before = sha(path)
    r = extract_document(path.read_bytes(), path.name, reg, inventory=inventory, period_id=period)
    after = sha(path)
    d = r.model_dump(mode="json")
    d["case"], d["original_unchanged"] = label, before == after
    return d


def main(fixtures: Path, oracle_path: Path, constructed: Path, out: Path):
    reg = SchemaRegistry.from_directory()
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    variants = json.loads((constructed / "variants_manifest.json").read_text(encoding="utf-8"))
    sep = fixtures / "PER-2026-09_set_01_clean_baseline"
    inv = list(csv.DictReader(open(sep / "source_data" / "account_inventory.csv", encoding="utf-8", newline="")))
    real = {}
    for p in sorted(fixtures.glob("*/supporting_documents/*.pdf")):
        real.setdefault(sha(p), p)
    cases = []
    for h, p in real.items():
        cases.append((f"REAL {p.name} (PER-2026-09, with IN-02)", p, inv, "PER-2026-09", "real", h))
    letters = [p for p in real.values() if p.name.startswith("ack_letter")]
    for p in letters:
        cases.append((f"REAL {p.name} (no IN-02 supplied)", p, None, "PER-2026-09", "real", sha(p)))
    v11 = next(p for p in real.values() if p.name.endswith("v1.1.pdf"))
    cases.append(("REAL safeguarding_reconciliation_policy_v1.1.pdf (PER-2026-01, its own period)", v11, inv, "PER-2026-01", "real", sha(v11)))
    for name in variants:
        cases.append((f"CONSTRUCTED {name}", constructed / name, inv, "PER-2026-09", "constructed", None))

    results, rows = [], []
    for label, p, inventory, period, kind, h in cases:
        d = run_case(reg, p, inventory, period, label)
        truth = (oracle[h]["details"] if kind == "real" else variants[p.name]["source_values"])
        cmp = []
        for f in d["fields"]:
            if f["status"] != "EXTRACTED":
                continue
            expected = truth.get(f["label"])
            cmp.append({"label": f["label"], "extracted": f["value"], "truth": expected, "equal": f["value"] == expected})
        d["truth_comparison"] = cmp
        results.append(d)
        rows.append({"case": label, "kind": kind, "native_text": d["native_text"], "pages": d["page_count"],
                     "category": d["category"] or "|".join(d["candidate_categories"]) or "-",
                     "fields": len(d["fields"]),
                     "extracted": sum(f["status"] == "EXTRACTED" for f in d["fields"]),
                     "not_extracted": sum(f["status"] != "EXTRACTED" for f in d["fields"]),
                     "mapped": sum(f["status"] == "EXTRACTED" for f in d["fields"]) if d["category"] else 0,
                     "unmapped_lines": len(d["unmapped"]),
                     "compared": len(cmp), "equal_to_truth": sum(c["equal"] for c in cmp),
                     "validation_fail": sum(v["result"] == "FAIL" for f in d["fields"] for v in f["validations"]),
                     "review_required": d["decision"] == "HUMAN_REVIEW", "decision": d["decision"],
                     "original_unchanged": d["original_unchanged"], "ocr_used": d["ocr_used"], "applied": d["applied"]})
    # reproducibility: a second full pass must give identical results
    second = [run_case(reg, p, inventory, period, label) for label, p, inventory, period, _, _ in cases]
    repro = all({k: v for k, v in a.items() if k != "truth_comparison"} == b for a, b in zip(results, second))
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    summary = {"cases": len(rows), "reproducible_second_pass": repro, "rows": rows,
               "fields_compared": sum(r["compared"] for r in rows), "fields_equal": sum(r["equal_to_truth"] for r in rows),
               "all_originals_unchanged": all(r["original_unchanged"] for r in rows),
               "ocr_used_anywhere": any(r["ocr_used"] for r in rows), "applied_anywhere": any(r["applied"] for r in rows)}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return summary


if __name__ == "__main__":
    s = main(*(Path(a) for a in sys.argv[1:5]))
    print(json.dumps({k: v for k, v in s.items() if k != "rows"}, indent=1))
    for r in s["rows"]:
        print(f"{r['decision']:<15} {r['native_text']:<10} p{r['pages']} {r['category']:<12} ext {r['extracted']}/{r['fields']} "
              f"truth {r['equal_to_truth']}/{r['compared']} vfail {r['validation_fail']} unchanged {r['original_unchanged']}  {r['case']}")
