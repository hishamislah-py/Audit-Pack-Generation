"""Evaluate the Phase 2 variation corpus: bytes-only classification AND the full pipeline under each case's upload
filename, under the rule set the case names. Writes results.csv and summary.json.

    py -3.11 tools/evaluate_variation_corpus.py [--corpus corpus/phase2_variations] --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from smartparser import SmartParser  # noqa: E402
from smartparser.classify.evidence import classify_bytes  # noqa: E402
from smartparser.intake import EvidenceStore  # noqa: E402
from smartparser.mapping.controlled import load_rules  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

RULES = HERE / "tests" / "fixtures" / "mapping_rules"


def evaluate(corpus: Path) -> list[dict]:
    reg = SchemaRegistry.from_directory()
    rule_sets = {"production": load_rules(reg),
                 "test_approved_aliases": load_rules(reg, RULES / "test_approved_aliases.json",
                                                     RULES / "test_alias_proposals.json")}
    cases = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))["cases"]
    store = Path(tempfile.mkdtemp(prefix="sp2_store_"))
    out = []
    for c in cases:
        data = (corpus / c["file"]).read_bytes()
        rules = rule_sets[c["rules"]]
        r = classify_bytes(data, reg, rules=rules).result
        p = SmartParser(schemas=reg, store=EvidenceStore(store), mapping_rules=rules).process_bytes(
            data, c["upload_filename"], "2026-09")
        got = "accept" if r.status == "identified" else "reject"
        ok = got == c["expected"] and (r.category or "") == c["expected_category"] \
            and (p.metadata.evidence_category or "") == c["expected_category"]
        cm = (r.details.get("controlled_mapping") or (r.diagnosis or {}).get("controlled_mapping") or {})
        out.append({**{k: c[k] for k in ("case_id", "category", "case_type", "upload_filename", "rules", "expected",
                                         "expected_category")},
                    "status": r.status.value, "actual_category": r.category or "", "method": r.method.value,
                    "pipeline_category": p.metadata.evidence_category or "",
                    "pipeline_mapping_status": p.metadata.mapping_status.value,
                    "pipeline_validation_status": p.metadata.validation_status.value,
                    "variations": ",".join(cm.get("variations", [])) if isinstance(cm, dict) else "",
                    "rejections": " | ".join(cm.get("rejections", [])) if isinstance(cm, dict) else "",
                    "unapproved_alias_proposals": ",".join(h["proposal_id"] for h in
                                                           (r.diagnosis or {}).get("unapproved_alias_proposals", [])),
                    "reason": r.reason, "result": "PASS" if ok else "FAIL"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(HERE / "corpus" / "phase2_variations"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = evaluate(Path(a.corpus))
    with open(out_dir / "variation_results.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    by_type = {}
    for r in rows:
        d = by_type.setdefault(r["case_type"], Counter())
        d["cases"] += 1
        d[r["result"]] += 1
        d[r["expected"]] += 1
    summary = {"cases": len(rows), "pass": sum(r["result"] == "PASS" for r in rows),
               "fail": [r["case_id"] for r in rows if r["result"] == "FAIL"],
               "categories": len({r["category"] for r in rows}),
               "by_case_type": {k: dict(v) for k, v in by_type.items()}}
    (out_dir / "variation_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
