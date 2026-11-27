"""Phase 1 baseline: classify every evidence file of every UC-042 dataset by content and compare with ground truth.

Ground truth for each file (filenames are never used for it):
  1. declared   - the file_id the dataset's own manifest.csv assigns to the file's relative path (the generator's
                  declaration of what it wrote);
  2. oracle     - UC-042's own content identification, run on the file: uc042lib.prepare.identify, the account-inventory
                  letter-slot resolution of uc042lib.prepare.prepare_case (using the IN-02 the oracle identified in the
                  same dataset), and uc042lib.policy.recognise for policies.
  The expected category is the declared one; the file is flagged when the oracle disagrees.

Smart Parser result: smartparser.classify.evidence.classify_batch over the dataset's files, keyed by opaque IDs (bytes
only). A second pass runs the full pipeline (SmartParser.process_bytes) under a neutral filename ("upload.dat") to show
the pipeline reaches the same category without the original name.

Read-only on the UC-042 tree. Usage:
    py -3.11 tools/baseline_classification.py --uc042-root <UC-042 dir> --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from smartparser import SmartParser  # noqa: E402
from smartparser.classify.evidence import classify_batch  # noqa: E402
from smartparser.classify.pdf_classifier import letter_refs_from_inventory  # noqa: E402
from smartparser.intake import EvidenceStore  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

DATASET_PARENTS = ["uc042_dataset", "demo_history/datasets", "UC042_JAN_AUG_HISTORICAL_DEMO"]
EVIDENCE_DIRS = ("source_data", "supporting_documents")


def discover(root: Path) -> list[Path]:
    """Dataset roots: directories holding a manifest.csv next to source_data/ or supporting_documents/."""
    out = []
    for parent in DATASET_PARENTS:
        for m in sorted((root / parent).rglob("manifest.csv")):
            if any((m.parent / d).is_dir() for d in EVIDENCE_DIRS):
                out.append(m.parent)
    return out


def oracle_for_dataset(files: list[Path], uc):
    """UC-042's own identification of each file (same steps as prepare_case, per file)."""
    prepare, policy, schema = uc["prepare"], uc["policy"], uc["schema"]
    first, inventories = {}, []
    for p in files:
        kind, value, info = prepare.identify(p)
        first[p] = (kind, value, info)
        if kind == "CSV" and value == "IN-02":
            inventories.append(info)
    letter_ref_to_slot = {}
    if len(inventories) == 1:
        for r in inventories[0]:
            if r.get("account_id") in schema.LETTER_SLOTS and r.get("acknowledgement_letter_ref"):
                letter_ref_to_slot[r["acknowledgement_letter_ref"]] = schema.LETTER_SLOTS[r["account_id"]]
    out = {}
    for p, (kind, value, info) in first.items():
        if kind == "REJECT":
            out[p] = ("REJECTED", value["message"] if isinstance(value, dict) else value)
        elif kind == "CSV":
            out[p] = (value, "exact header")
        else:
            details = info[0]
            if len(value) == 1:
                slot = value[0]
            else:
                slot = letter_ref_to_slot.get(details.get("Letter reference", ""))
                if slot not in value:
                    out[p] = ("AMBIGUOUS", "/".join(value))
                    continue
            if slot == "IN-17":
                version, problems = policy.recognise(details, policy.document_text(p))
                out[p] = ("REJECTED", "; ".join(problems)) if problems else ("IN-17", f"policy v{version}")
            else:
                out[p] = (slot, "PDF key details")
    return out


def load_uc042(root: Path):
    sys.path.insert(0, str(root))
    from uc042lib import policy, prepare, schema  # noqa: WPS433
    return {"prepare": prepare, "policy": policy, "schema": schema}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uc042-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root, out = Path(a.uc042_root).resolve(), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    uc = load_uc042(root)
    reg = SchemaRegistry.from_directory()
    rows = []
    store_dir = Path(tempfile.mkdtemp(prefix="sp1_store_"))
    for ds in discover(root):
        with open(ds / "manifest.csv", encoding="utf-8", newline="") as f:
            manifest = list(csv.DictReader(f))
        declared = {r["relative_path"].replace("\\", "/"): r for r in manifest}
        files = sorted(p for d in EVIDENCE_DIRS if (ds / d).is_dir() for p in (ds / d).rglob("*") if p.is_file())
        oracle = oracle_for_dataset(files, uc)
        keyed = {f"F{i:03d}": p for i, p in enumerate(files)}
        results = classify_batch([(k, p.read_bytes()) for k, p in keyed.items()], reg)
        inv = [fc.inventory_rows for fc in results.values() if fc.inventory_rows is not None]
        refs = letter_refs_from_inventory(inv[0], reg) if len(inv) == 1 else None
        parser = SmartParser(schemas=reg, store=EvidenceStore(store_dir / ds.name))
        for k, p in keyed.items():
            rel = p.relative_to(ds).as_posix()
            m = declared.get(rel)
            fc = results[k]
            r = fc.result
            pipe = parser.process_bytes(p.read_bytes(), "upload.dat", None, letter_refs=refs)
            o_cat, o_why = oracle[p]
            expected = m["file_id"] if m else None
            cc = r.content_check or {}
            rows.append({
                "dataset": ds.relative_to(root).as_posix(),
                "period": (m or {}).get("reporting_period", ""),
                "relative_path": rel, "original_filename": p.name,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "file_type": fc.file_format,
                "expected_category": expected or "(not in manifest)",
                "uc042_oracle": o_cat, "oracle_basis": o_why,
                "ground_truth": "AGREED" if expected and o_cat == expected else "CONFLICT",
                "actual_category": r.category or "",
                "classification_status": r.status.value,
                "match": "MATCH" if expected and r.category == expected and r.status.value == "identified" else
                         ("AMBIGUOUS" if r.status.value == "ambiguous" else
                          "UNKNOWN" if r.status.value == "unknown" else "MISMATCH"),
                "method": r.method.value, "reason": r.reason, "warnings": " | ".join(r.warnings),
                "policy_version": r.details.get("policy_version") or "",
                "letter_slot_via": (r.details.get("slot_resolution") or {}).get("account_id", ""),
                "rows_checked": cc.get("rows_checked", ""), "nonconforming_rows": cc.get("nonconforming_rows", ""),
                "pipeline_category": pipe.metadata.evidence_category or "",
                "pipeline_processing_status": pipe.metadata.processing_status.value,
                "pipeline_mapping_status": pipe.metadata.mapping_status.value,
                "pipeline_validation_status": pipe.metadata.validation_status.value,
                "pipeline_validation_errors": pipe.validation.error_count if pipe.validation else "",
            })
    write(rows, out, root)


def write(rows, out: Path, root: Path):
    with open(out / "baseline_results.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    def summary(sel):
        c = Counter(r["match"] for r in sel)
        return {"files": len(sel), "unique_contents": len({r["sha256"] for r in sel}), "correct": c["MATCH"],
                "incorrect": c["MISMATCH"], "unknown": c["UNKNOWN"], "ambiguous": c["AMBIGUOUS"],
                "ground_truth_conflicts": sum(r["ground_truth"] == "CONFLICT" for r in sel),
                "with_warnings": sum(bool(r["warnings"]) for r in sel)}
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["expected_category"]].append(r)
    by_ds = defaultdict(list)
    for r in rows:
        by_ds[r["dataset"]].append(r)
    doc = {
        "uc042_root": str(root),
        "total": summary(rows),
        "csv": summary([r for r in rows if r["file_type"] == "csv"]),
        "pdf": summary([r for r in rows if r["file_type"] == "pdf"]),
        "by_category": {k: dict(summary(v), periods=sorted({r["period"] for r in v}),
                                datasets=len({r["dataset"] for r in v}))
                        for k, v in sorted(by_cat.items())},
        "by_dataset": {k: summary(v) for k, v in sorted(by_ds.items())},
        "pipeline_same_category": sum(r["pipeline_category"] == r["actual_category"] for r in rows),
        "pipeline_status_counts": dict(Counter(f"{r['file_type']}:{r['pipeline_processing_status']}" for r in rows)),
        "pipeline_validation_counts": dict(Counter(f"{r['file_type']}:{r['pipeline_validation_status']}" for r in rows)),
        "policy_versions": dict(Counter(r["policy_version"] for r in rows if r["expected_category"] == "IN-17")),
        "letters_resolved_via": dict(Counter(f"{r['actual_category']}<-{r['letter_slot_via']}" for r in rows
                                             if r["expected_category"] in ("IN-15", "IN-16"))),
        "nonconforming_files": [(r["dataset"], r["relative_path"], r["nonconforming_rows"]) for r in rows
                                if r["nonconforming_rows"] not in ("", 0)],
    }
    (out / "baseline_summary.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("total", "csv", "pdf", "pipeline_same_category", "policy_versions",
                                          "letters_resolved_via")}, indent=1))


if __name__ == "__main__":
    main()
