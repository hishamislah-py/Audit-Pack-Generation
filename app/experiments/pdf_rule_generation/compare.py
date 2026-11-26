"""Experiment A2 - compare the hand-maintained PDF value rules with the generated ones (value level and document level).

Usage:  py -3.11 experiments/pdf_rule_generation/compare.py <fixtures_root> <experiment_a_constructed_dir> <a2_work_dir> <out_dir>

* value level: every syntax label is checked with a set of edge values under (1) the hand rules, (2) the generated
  rules, (3) UC-042 itself (<a2_work_dir>/uc042_helper_oracle.json, captured read-only in the UC-042 environment);
* document level: the 20 Experiment A cases plus A2 edge-case PDFs (built into <a2_work_dir>/edge_pdfs) are extracted
  under both rule sets by swapping the rule tables in-process; the Experiment A module and evidence are not modified.
Writes only into <out_dir> and <a2_work_dir>.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import generated_rules_adapter as G  # noqa: E402
from smartparser.pdf_extraction import extractor as X  # noqa: E402
from smartparser.pdf_extraction import rules as H  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

FOOTER = "SYNTHETIC DOCUMENT - UC-042 POC - not a real bank or firm document"
GBP_LETTER = [("Letter reference", "ACK-INST01-4471"), ("Institution", "Example Bank plc"),
              ("Account name", "Synthetic EMI Ltd Safeguarding Account (GBP)"), ("Account number", "****4471"),
              ("Currency", "GBP"), ("Letter date", "2024-03-01")]
RECEIPT = [("Return", "REP027 monthly safeguarding return"), ("Period", "2026-08"), ("Due date", "2026-09-21"),
           ("Submitted at", "2026-09-17T11:02:00+01:00"), ("Submission reference", "SYN-RD-2026-08-0001")]
GOV = [("Accountable person", "A. Example (synthetic)"), ("Role", "Chief Financial Officer (synthetic)"),
       ("Allocated from", "2026-05-07")]
POLICY = [("Document version", "1.2"), ("Effective date", "2026-05-07"), ("Safeguarding method", "SEGREGATION"),
          ("Reconciliation method", "STANDARD"), ("Reconciliation point", "17:00 Europe/London"),
          ("Frequency", "Each reconciliation day"), ("Internal reconciliation basis", "Per currency")]


def _set(details, label, value):
    return [(k, value if k == label else v) for k, v in details]


EDGE = {   # name: (title, details, purpose)
    "E01_letter_date_basic_format.pdf": ("Safeguarding account acknowledgement (synthetic)", _set(GBP_LETTER, "Letter date", "20240301"),
                                         "Letter date in ISO basic format (UC-042 reads it)"),
    "E02_letter_date_with_text.pdf": ("Safeguarding account acknowledgement (synthetic)", _set(GBP_LETTER, "Letter date", "2024-03-01 (original issue)"),
                                      "Letter date followed by text (UC-042 reads the first 10 characters)"),
    "E03_letter_date_week_format.pdf": ("Safeguarding account acknowledgement (synthetic)", _set(GBP_LETTER, "Letter date", "2024-W09-5"),
                                        "Letter date as an ISO week date (UC-042 reads it)"),
    "E04_letter_date_uk_format.pdf": ("Safeguarding account acknowledgement (synthetic)", _set(GBP_LETTER, "Letter date", "01/03/2024"),
                                      "Letter date dd/mm/yyyy (UC-042 cannot read it)"),
    "E05_receipt_ts_zulu.pdf": ("Monthly safeguarding return - submission receipt (synthetic)", _set(RECEIPT, "Submitted at", "2026-09-17T10:02:00Z"),
                                "Submitted at with Z offset (UC-042 reads it)"),
    "E06_receipt_ts_no_offset.pdf": ("Monthly safeguarding return - submission receipt (synthetic)", _set(RECEIPT, "Submitted at", "2026-09-17T11:02:00"),
                                     "Submitted at without an offset (UC-042 rejects it)"),
    "E07_receipt_due_date_uk.pdf": ("Monthly safeguarding return - submission receipt (synthetic)", _set(RECEIPT, "Due date", "21/09/2026"),
                                    "Due date dd/mm/yyyy (UC-042 compares it with its computed date: C16 fails)"),
    "E08_policy_point_12h.pdf": ("Safeguarding reconciliation policy (synthetic)", _set(POLICY, "Reconciliation point", "5pm Europe/London"),
                                 "Reconciliation point '5pm Europe/London' (UC-042 marks IN-17 unusable)"),
    "E09_governance_from_with_text.pdf": ("Governance register extract (synthetic)", _set(GOV, "Allocated from", "2026-05-07 (board minute 12)"),
                                          "Allocated from followed by text (UC-042 reads it)"),
    "E10_letter_currency_lower.pdf": ("Safeguarding account acknowledgement (synthetic)", _set(GBP_LETTER, "Currency", "gbp"),
                                      "Currency in lower case (C10 compares with IN-02: business level)"),
}


def build_edge_pdfs(out: Path) -> dict:
    from reportlab import rl_config
    rl_config.invariant = 1
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    st = getSampleStyleSheet()
    out.mkdir(parents=True, exist_ok=True)

    def footer(c, _d):
        c.setFont("Helvetica", 8)
        c.drawString(56, 28, FOOTER)
    manifest = {}
    for name, (title, details, purpose) in EDGE.items():
        story = [Paragraph(title, st["Title"]), Paragraph("Synthetic EMI Ltd (fictional).", st["Normal"]), Spacer(1, 12),
                 Paragraph("Key details", st["Heading2"])] + [Paragraph(f"{k}: {v}", st["Normal"]) for k, v in details] + \
                [Spacer(1, 12), Paragraph("Synthetic edge case for Experiment A2.", st["Normal"])]
        SimpleDocTemplate(str(out / name), pagesize=A4, title=name, author="Experiment A2", creator="Experiment A2").build(
            story, onFirstPage=footer, onLaterPages=footer)
        manifest[name] = {"purpose": purpose, "source_values": dict(details)}
    (out / "edge_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


@contextlib.contextmanager
def ruleset(name, gen):
    """Swap the rule tables the extractor uses ('hand' leaves them untouched)."""
    saved = (X.RULES, X.NO_RULE_REASON, X.document_rules)
    try:
        if name == "generated":
            X.RULES, X.NO_RULE_REASON, X.document_rules = gen
        yield
    finally:
        X.RULES, X.NO_RULE_REASON, X.document_rules = saved


def readable(rules_for_label, value, ctx):
    """'readable' (no FORMAT failure), 'FORMAT_FAIL', or 'no rule'."""
    if not rules_for_label:
        return "no syntax rule"
    fails = [d for r in rules_for_label for res, d in [r.check(value, ctx)] if res == "FAIL" and d.startswith("FORMAT:")]
    return "FORMAT_FAIL" if fails else "readable"


def value_level(gen_rules, oracle):
    ctx = H.Context(period_id="PER-2026-09")
    plan = [("IN-15", "Letter date", "date"), ("IN-18", "Allocated from", "date"), ("IN-17", "Effective date", "date"),
            ("IN-19", "Submitted at", "timestamp"), ("IN-17", "Reconciliation point", "point"), ("IN-19", "Due date", "date")]
    rows = []
    for cat, label, kind in plan:
        hand = [r for r in H.RULES.get(cat, {}).get(label, [])]
        gen = [r for r in gen_rules.get(cat, {}).get(label, []) if r.rule_id.endswith(("DATE_PARSE", "TIMESTAMP_PARSE", "REGEX_MATCH"))]
        for value, uc in oracle[kind].items():
            if value == "":
                continue
            h, g = readable(hand, value, ctx), readable(gen, value, ctx)
            u = "readable" if uc else "FORMAT_FAIL"
            if label == "Due date":
                u = "no UC-042 syntax rule (string compared with the computed due date)"
            rows.append({"category": cat, "label": label, "value": value, "uc042": u, "hand": h, "generated": g,
                         "hand_equals_uc042": h == u, "generated_equals_uc042": g == u, "hand_equals_generated": h == g})
    return rows


def doc_cases(fixtures: Path, constructed: Path, edge: Path, inv):
    real = {}
    for p in sorted(fixtures.glob("*/supporting_documents/*.pdf")):
        real.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), p)
    cases = [(f"A-REAL {p.name}", p, inv, "PER-2026-09") for p in real.values()]
    cases += [(f"A-REAL {p.name} (no IN-02)", p, None, "PER-2026-09") for p in real.values() if p.name.startswith("ack_letter")]
    v11 = next(p for p in real.values() if p.name.endswith("v1.1.pdf"))
    cases.append(("A-REAL policy_v1.1 (PER-2026-01)", v11, inv, "PER-2026-01"))
    cases += [(f"A-CONSTRUCTED {p.name}", p, inv, "PER-2026-09") for p in sorted(constructed.glob("V*.pdf"))]
    cases += [(f"A2-EDGE {p.name}", p, inv, "PER-2026-09") for p in sorted(edge.glob("E*.pdf"))]
    return cases


def run_doc(reg, path, inv, period):
    r = X.extract_document(path.read_bytes(), path.name, reg, inventory=inv, period_id=period)
    return {"decision": str(r.decision), "fields": {f.label: (f.status, f.value, tuple(sorted(f.flags))) for f in r.fields},
            "review_reasons": sorted(x for f in r.fields for x in f.review_reasons),
            "validations": sorted((f.label, v.result, v.level) for f in r.fields for v in f.validations if v.result != "NOT_EVALUATED"),
            "format_fails": sorted(f.label for f in r.fields for v in f.validations if v.result == "FAIL" and v.detail.startswith("FORMAT:"))}


def main(fixtures, constructed, work, out):
    reg = SchemaRegistry.from_directory()
    doc = G.load()
    gen = G.build(doc)
    oracle = json.loads((work / "uc042_helper_oracle.json").read_text(encoding="utf-8"))
    edge_manifest = build_edge_pdfs(work / "edge_pdfs")
    sep = fixtures / "PER-2026-09_set_01_clean_baseline"
    inv = list(csv.DictReader(open(sep / "source_data" / "account_inventory.csv", encoding="utf-8", newline="")))
    vrows = value_level(gen[0], oracle)
    drows = []
    for label, path, i, period in doc_cases(fixtures, constructed, work / "edge_pdfs", inv):
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with ruleset("hand", gen):
            h = run_doc(reg, path, i, period)
        with ruleset("generated", gen):
            g = run_doc(reg, path, i, period)
        h2 = run_doc(reg, path, i, period)   # tables restored: identical to the first hand run
        unchanged = hashlib.sha256(path.read_bytes()).hexdigest() == before
        drows.append({"case": label, "hand_decision": h["decision"], "generated_decision": g["decision"],
                      "same_decision": h["decision"] == g["decision"], "same_extraction": h["fields"] == g["fields"],
                      "hand_format_fails": h["format_fails"], "generated_format_fails": g["format_fails"],
                      "hand_review_reasons": len(h["review_reasons"]), "generated_review_reasons": len(g["review_reasons"]),
                      "hand_validations_evaluated": len(h["validations"]), "generated_validations_evaluated": len(g["validations"]),
                      "restored": h == h2, "original_unchanged": unchanged,
                      "edge_purpose": edge_manifest.get(path.name, {}).get("purpose", "")})
    # reproducibility: regenerate the artefact in memory and compare bytes
    sys.path.insert(0, str(HERE))
    import generate_rules as GR
    regen = GR.render(GR.generate(Path(HERE.parents[2]) / "uc042_token_optimisation"))
    repro = regen == (HERE / "generated_pdf_rules.json").read_text(encoding="utf-8")
    out.mkdir(parents=True, exist_ok=True)
    (out / "value_level_comparison.json").write_text(json.dumps(vrows, indent=1), encoding="utf-8")
    (out / "document_level_comparison.json").write_text(json.dumps(drows, indent=1), encoding="utf-8")
    summary = {"value_cases": len(vrows), "hand_equals_uc042": sum(r["hand_equals_uc042"] for r in vrows),
               "generated_equals_uc042": sum(r["generated_equals_uc042"] for r in vrows),
               "hand_equals_generated": sum(r["hand_equals_generated"] for r in vrows),
               "document_cases": len(drows), "same_decision": sum(r["same_decision"] for r in drows),
               "same_extraction": sum(r["same_extraction"] for r in drows),
               "tables_restored": all(r["restored"] for r in drows), "originals_unchanged": all(r["original_unchanged"] for r in drows),
               "artefact_reproducible": repro}
    (out / "comparison_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary, vrows, drows


if __name__ == "__main__":
    s, v, d = main(*(Path(a) for a in sys.argv[1:5]))
    print(json.dumps(s, indent=1))
    print("\nVALUE LEVEL (differences only)")
    for r in v:
        if not (r["hand_equals_uc042"] and r["generated_equals_uc042"]):
            print(f"  {r['label']:<20} {r['value']!r:<32} uc042={r['uc042'][:20]:<20} hand={r['hand']:<14} gen={r['generated']}")
    print("\nDOCUMENT LEVEL")
    for r in d:
        flag = "" if r["same_decision"] else "  <-- DIFFERENT"
        print(f"  {r['hand_decision']:<15} {r['generated_decision']:<15} fmt h{r['hand_format_fails']} g{r['generated_format_fails']} "
              f"rev {r['hand_review_reasons']}/{r['generated_review_reasons']}  {r['case']}{flag}")
