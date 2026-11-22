"""Experiment C - runner.

    py -3.11 experiments/realworld_formats/run.py generate --out <dir>      # inputs + truth, ONCE
    py -3.11 experiments/realworld_formats/run.py run --out <dir> --name run1
    py -3.11 experiments/realworld_formats/run.py run --out <dir> --name run2
    py -3.11 experiments/realworld_formats/run.py compare --out <dir>       # reproducibility + metrics per format
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scenarios as sc  # noqa: E402
from bridge import evaluate_table, xlsx_assert_classified  # noqa: E402
from extract import detect, extract  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def generate(out: Path):
    if (out / "inputs").exists():
        shutil.rmtree(out / "inputs")
    (out / "inputs" / "truth").mkdir(parents=True)
    xs, js = sc.xlsx_scenarios(), sc.json_scenarios()
    adv = sc.adversarial_scenarios(next(s["data"] for s in xs if s["id"] == "X01"),
                                   next(s["data"] for s in js if s["id"] == "J01"))
    manifest = []
    for s in xs + js + adv:
        d = out / "inputs" / s["id"]
        d.mkdir()
        (d / s["file"]).write_bytes(s["data"])
        tables = s.get("tables") or s.get("table") or {}
        (out / "inputs" / "truth" / f"{s['id']}.json").write_text(json.dumps(tables), encoding="utf-8")
        manifest.append({"id": s["id"], "fmt": s["fmt"], "desc": s["desc"], "file": f"{s['id']}/{s['file']}",
                         "sha256": sha(s["data"]), "bytes": len(s["data"]), "expect": s.get("expect"),
                         "expected_tables": {k: (v["outcome"] if v else None) for k, v in tables.items()},
                         "warn": s.get("warn", []), "notes": s.get("notes", []), "existing": s.get("existing", False)})
    (out / "inputs" / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"generated {len(manifest)} scenarios: " + ", ".join(f"{k} {v}" for k, v in
                                                            Counter(m["fmt"] for m in manifest).items()))


def _table_key(t, ex, i):
    if "!" in t.table_id:
        sheet = t.table_id.split("!", 1)[0]
        k = sum(1 for x in ex.tables[:i] if x.table_id.split("!", 1)[0] == sheet)
        return f"{sheet}#{k}"
    return t.table_id


def _existing_identify(data: bytes, name: str) -> dict:
    """Read-only: what the EXISTING Smart Parser identification / pipeline does with this file today."""
    from smartparser import SmartParser
    from smartparser.intake import EvidenceStore
    from smartparser.schemas import SchemaRegistry
    r = SmartParser(schemas=SchemaRegistry.from_directory(), store=EvidenceStore(None)).process_bytes(data, name, "2026-09")
    return {"detected_format": r.metadata.file_format.value if r.metadata.file_format else None,
            "processing_status": r.metadata.processing_status.value,
            "classification": r.metadata.classification_status.value if r.metadata.classification_status else None,
            "category": r.metadata.evidence_category,
            "issues": [f"{i.code.value}: {i.message[:120]}" for i in r.issues][:4]}


# Experiment C1: documented expectation changes (the two findings must now be refused by the XLSX hard gate)
C1_EXPECTATION_OVERRIDES = {"X13": {"Bank#0": "GATE_BLOCKED"}, "X20": {"CashBook#0": "GATE_BLOCKED"}}


def generate_c1(out: Path):
    import scenarios_c1
    d0 = out / "inputs_c1"
    if d0.exists():
        shutil.rmtree(d0)
    (d0 / "truth").mkdir(parents=True)
    manifest = []
    for s in scenarios_c1.xlsx_c1_scenarios():
        (d0 / s["id"]).mkdir()
        (d0 / s["id"] / s["file"]).write_bytes(s["data"])
        (d0 / "truth" / f"{s['id']}.json").write_text(json.dumps(s["tables"]), encoding="utf-8")
        manifest.append({"id": s["id"], "fmt": s["fmt"], "desc": s["desc"], "file": f"{s['id']}/{s['file']}",
                         "sha256": sha(s["data"]), "bytes": len(s["data"]), "expect": None,
                         "expected_tables": {k: v["outcome"] for k, v in s["tables"].items()},
                         "warn": s.get("warn", []), "notes": s.get("notes", []), "existing": False})
    (d0 / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"generated {len(manifest)} C1 scenarios into {d0}")


def run(out: Path, name: str, sets=("inputs",)):
    work = out / name / "work"
    if (out / name).exists():
        shutil.rmtree(out / name)
    work.mkdir(parents=True)
    results = []
    todo = [(st, m) for st in sets for m in json.loads((out / st / "manifest.json").read_text(encoding="utf-8"))]
    for st, m in todo:
        data = (out / st / m["file"]).read_bytes()
        truth = json.loads((out / st / "truth" / f"{m['id']}.json").read_text(encoding="utf-8"))
        for k, v in C1_EXPECTATION_OVERRIDES.get(m["id"], {}).items():
            if truth.get(k):
                truth[k]["outcome"] = v
                m["expected_tables"][k] = v
        r = {"id": m["id"], "set": st, "fmt": m["fmt"], "desc": m["desc"], "input_sha256": sha(data),
             "input_unchanged": sha(data) == m["sha256"], "detected": detect(data)}
        ex = extract(data, m["file"].split("/", 1)[1])
        if ex.upload.detected_format == "xlsx":
            xlsx_assert_classified(None, ex.notes)      # C1: workbook notes need a policy decision too
        r.update(refused=ex.refused, notes=ex.notes, extraction_digest=ex.digest(), upload=ex.upload.__dict__,
                 tables_found=[t.table_id for t in ex.tables], tables=[])
        if m.get("existing"):
            r["existing_smart_parser"] = _existing_identify(data, m["file"].split("/", 1)[1])
        for i, t in enumerate(ex.tables):
            key = _table_key(t, ex, i)
            tr = truth.get(key)
            res = evaluate_table(t, work, f"{m['id']}_{i}", tr, source_format=ex.upload.detected_format)
            res["key"] = key
            res["expected"] = tr["outcome"] if tr else ("NOT_EVIDENCE_TABLE" if key in truth else "NOT_EXPECTED")
            res["verdict"] = ("PASS" if res["outcome"] == res["expected"] else "FAIL")
            if res["verdict"] == "PASS" and res["outcome"].endswith("SILENT_DIFFERENCE"):
                res["verdict"] = "FINDING"            # an expected, documented risk of the existing pipeline
            r["tables"].append(res)
        # scenario-level verdict
        problems = []
        if m["expect"]:
            kind, code = m["expect"].split(":", 1)
            if kind == "REFUSED" and not (ex.refused or "").startswith(code):
                problems.append(f"expected refusal {code}, got {ex.refused!r}")
            if kind == "EXTRACTED" and (ex.refused or r["detected"] != code):
                problems.append(f"expected extraction as {code}, got detected={r['detected']} refused={ex.refused!r}")
            if kind == "NOTE" and not any(n.startswith(code) for n in ex.notes):
                problems.append(f"expected note {code}")
        found = {t["key"] for t in r["tables"]}
        for k, v in m["expected_tables"].items():
            if k not in found:
                problems.append(f"expected table {k} not extracted")
        codes = set()
        for t in r["tables"]:
            codes |= set(t["ir_warnings"])
        for w in m["warn"]:
            if w not in codes:
                problems.append(f"expected warning {w} not raised")
        for n in m["notes"]:
            if not any(x.startswith(n) for x in ex.notes):
                problems.append(f"expected note {n} not reported")
        bad = [t for t in r["tables"] if t["verdict"] == "FAIL" and t["expected"] != "NOT_EXPECTED"]
        r["problems"] = problems + [f"{t['key']}: expected {t['expected']}, got {t['outcome']}" for t in bad]
        r["verdict"] = "FAIL" if r["problems"] else ("FINDING" if any(t["verdict"] == "FINDING" for t in r["tables"])
                                                   else "PASS")
        results.append(r)
        print(m["id"], r["verdict"], [(t["key"], t["outcome"]) for t in r["tables"]], r["refused"] or "",
              r["problems"][:2], flush=True)
    shutil.rmtree(work, ignore_errors=True)
    (out / name / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")


def metrics(results, fmt):
    R = [r for r in results if r["fmt"] == fmt]
    T = [t for r in R for t in r["tables"] if t.get("category")]
    f = lambda k: sum(t["fidelity"][k] for t in T)  # noqa: E731
    finals = Counter(t["outcome"] for t in T)
    return {"scenarios": len(R), "verdicts": dict(Counter(r["verdict"] for r in R)),
            "extraction_success": f"{sum(1 for r in R if not r['refused'] and not any('not extracted' in p for p in r['problems']))}/{len(R)}",
            "evidence_tables": len(T),
            "exact_value_fidelity": f"{f('exact')}/{f('cells')}",
            "money_exact_text": f"{f('money_exact')}/{f('money_cells')}",
            "money_numeric_equal": f"{f('money_numeric_equal')}/{f('money_cells')}",
            "date_ts_exact": f"{f('date_ts_exact')}/{f('date_ts_cells')}",
            "content_classified_by_header": f"{sum(1 for t in T if t['content_classification'] == t['category'])}/{len(T)}",
            "outcomes": dict(finals),
            "human_review_required": sum(1 for t in T if t["outcome"].startswith("REVIEW")),
            "handoff_eligible_final": sum(1 for t in T if t["outcome"] in ("EXACT", "REVIEW->EXACT") or
                                          t["outcome"].endswith("SILENT_DIFFERENCE")),
            "gate_blocked": sum(1 for t in T if t["outcome"].endswith("GATE_BLOCKED")),
            "gate_findings": dict(sorted(__import__("collections").Counter(
                k for t in T for k, n in t.get("xlsx_gate", {}).get("findings", {}).items() for _ in range(n)).items())),
            "counterfactual_silent_differences_stopped": [
                (r["id"], t["key"]) for r in R for t in r["tables"]
                if t["outcome"].endswith("GATE_BLOCKED") and t.get("xlsx_gate", {}).get(
                    "counterfactual_without_gate_equals_truth") is False],
            "silent_differences": [(r["id"], t["key"], t.get("caught_by_proposed_safeguard")) for r in R
                                   for t in r["tables"] if t["outcome"].endswith("SILENT_DIFFERENCE")],
            "provenance_complete": f"{sum(1 for t in T if all(t['provenance'][k] for k in ('row_locators', 'column_locators', 'cell_locators')))}/{len(T)}",
            "checks_run_when_reprocessed": sorted({t.get('checks_run') for t in T if t.get('checks_run')} |
                                                  {t['review'].get('checks_run') for t in T if t.get('review', {}).get('checks_run')}),
            "simulated_proposals": sum(t.get("simulated_proposals", 0) for t in T)}


def compare(out: Path, ra="run1", rb="run2", sets=("inputs",), summary_name="summary.json"):
    a = json.loads((out / ra / "results.json").read_text(encoding="utf-8"))
    b = json.loads((out / rb / "results.json").read_text(encoding="utf-8"))
    manifest = [dict(m, file=f"{st}/{m['file']}") for st in sets
                for m in json.loads((out / st / "manifest.json").read_text(encoding="utf-8"))]
    diffs = []
    for x, y in zip(a, b):
        if x["extraction_digest"] != y["extraction_digest"]:
            diffs.append(f"{x['id']}: extraction differs")
        for tx, ty in zip(x["tables"], y["tables"]):
            for k in ("reproducibility_digest", "bridged_csv_sha256", "preview_sha256", "outcome"):
                if tx.get(k) != ty.get(k):
                    diffs.append(f"{x['id']}/{tx['key']}: {k} differs")
    unchanged = all(hashlib.sha256((out / m["file"]).read_bytes()).hexdigest() == m["sha256"] for m in manifest)
    summary = {"reproducibility": {"scenarios": len(a), "differences": diffs, "identical": not diffs,
                                   "inputs_unchanged_after_two_runs": unchanged},
               "xlsx": metrics(a, "xlsx"), "json": metrics(a, "json"), "adversarial": metrics(a, "adversarial"),
               "xlsx_original_set": metrics([r for r in a if r.get("set", "inputs") == "inputs"], "xlsx"),
               "xlsx_c1_set": metrics([r for r in a if r.get("set") == "inputs_c1"], "xlsx")}
    (out / summary_name).write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "generate_c1", "run", "compare"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="run1")
    ap.add_argument("--sets", default="inputs")
    ap.add_argument("--runs", default="run1,run2")
    ap.add_argument("--summary", default="summary.json")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sets = tuple(a.sets.split(","))
    ra, rb = a.runs.split(",")
    {"generate": lambda: generate(out), "generate_c1": lambda: generate_c1(out),
     "run": lambda: run(out, a.name, sets),
     "compare": lambda: compare(out, ra, rb, sets, a.summary)}[a.cmd]()
