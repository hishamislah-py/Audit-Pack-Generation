"""Experiment A: build the CONSTRUCTED (controlled, synthetic) PDF variants in an isolated folder.

Usage:  py -3.11 tools/pdfx_build_variants.py <out_dir>

The real UC-042 evidence PDFs are all single-page key-value documents (one layout). These variants exercise the
structures and failure modes the real corpus does not contain. They copy the layout of uc042lib.generate.write_pdfs
(ReportLab, 'Key details' block, footer marking) and change exactly one property each. ReportLab invariant mode makes
the bytes reproducible. Nothing here is UC-042 evidence; nothing is written outside <out_dir>.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

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
BODY = ("Generic synthetic wording: the institution acknowledges that the account is held for the purpose of "
        "safeguarding relevant funds of the account holder's clients and is designated accordingly.")


def build(out: Path) -> dict:
    from reportlab import rl_config
    rl_config.invariant = 1
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

    st = getSampleStyleSheet()

    def footer(c, _d):
        c.setFont("Helvetica", 8)
        c.drawString(56, 28, FOOTER)

    def write(name, story):
        SimpleDocTemplate(str(out / name), pagesize=A4, title=name, author="Experiment A variant builder",
                          creator="Experiment A variant builder").build(story, onFirstPage=footer, onLaterPages=footer)

    def kv(title, details, body=(BODY,), lead=()):
        story = list(lead) + [Paragraph(title, st["Title"]), Paragraph("Synthetic EMI Ltd (fictional).", st["Normal"]),
                              Spacer(1, 12), Paragraph("Key details", st["Heading2"])]
        story += [Paragraph(f"{k}: {v}", st["Normal"]) for k, v in details]
        story += [Spacer(1, 12)] + [Paragraph(b, st["Normal"]) for b in body]
        return story

    out.mkdir(parents=True, exist_ok=True)
    manifest = {}

    def add(name, purpose, expected, details):
        manifest[name] = {"purpose": purpose, "expected": expected, "source_values": dict(details) if details else {}}

    # V01: multi-page, key details on page 2
    lead = [Paragraph("Cover page", st["Title"]), Paragraph(BODY * 3, st["Normal"]), PageBreak()]
    write("V01_multipage_letter_GBP.pdf", kv("Safeguarding account acknowledgement (synthetic)", GBP_LETTER, lead=lead))
    add("V01_multipage_letter_GBP.pdf", "multi-page document; key details on page 2", "DETERMINISTIC, page 2 provenance", GBP_LETTER)
    # V02: key details in a two-column table (no 'Label: value' text)
    story = [Paragraph("Safeguarding account acknowledgement (synthetic)", st["Title"]), Paragraph("Key details", st["Heading2"]),
             Table([[k, v] for k, v in GBP_LETTER]), Spacer(1, 12), Paragraph(BODY, st["Normal"])]
    write("V02_table_layout_letter_GBP.pdf", story)
    add("V02_table_layout_letter_GBP.pdf", "key details as a table (label and value in separate cells)",
        "not identified (labels not line-anchored) -> REJECT_OR_HOLD, candidates reported, nothing mapped", GBP_LETTER)
    # V03: one label missing
    det = [x for x in RECEIPT if x[0] != "Submission reference"]
    write("V03_receipt_missing_label.pdf", kv("Monthly safeguarding return - submission receipt (synthetic)", det, body=("Generated for the UC-042 POC.",)))
    add("V03_receipt_missing_label.pdf", "IN-19 without 'Submission reference'", "REJECT_OR_HOLD (closest IN-19, 4/5 labels)", det)
    # V04: conflicting duplicate label
    det = GOV + [("Allocated from", "2026-06-01")]
    write("V04_governance_conflict.pdf", kv("Governance register extract (synthetic)", det, body=("Optional supporting evidence.",)))
    add("V04_governance_conflict.pdf", "IN-18 with two different 'Allocated from' values", "HUMAN_REVIEW (CONFLICT, none chosen)", det)
    # V05: near-miss label (capitalisation)
    det = [("Accountable Person", GOV[0][1])] + GOV[1:]
    write("V05_governance_near_miss.pdf", kv("Governance register extract (synthetic)", det, body=("Optional supporting evidence.",)))
    add("V05_governance_near_miss.pdf", "'Accountable Person' instead of 'Accountable person'",
        "REJECT_OR_HOLD (not identified), near miss reported, never mapped", det)
    # V06: image-only (rendered text, no text layer)
    from PIL import Image as PILImage, ImageDraw
    img = PILImage.new("RGB", (900, 400), "white")
    d = ImageDraw.Draw(img)
    for i, (k, v) in enumerate(GBP_LETTER):
        d.text((20, 20 + 40 * i), f"{k}: {v}", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    SimpleDocTemplate(str(out / "V06_image_only_letter.pdf"), pagesize=A4).build([Image(buf, width=450, height=200)])
    add("V06_image_only_letter.pdf", "scanned-style page: the key details exist only as pixels", "IMAGE_ONLY, nothing extracted (no OCR)", GBP_LETTER)
    # V07: value long enough to wrap onto a second line
    det = [(k, v + " held at Example Bank plc for the benefit of relevant-funds clients under the CASS 15 regime (synthetic)")
           if k == "Account name" else (k, v) for k, v in GBP_LETTER]
    write("V07_wrapped_account_name.pdf", kv("Safeguarding account acknowledgement (synthetic)", det))
    add("V07_wrapped_account_name.pdf", "Account name wraps onto the next line", "HUMAN_REVIEW (POSSIBLY_WRAPPED + IN-02 mismatch)", det)
    # V08: unregistered policy version
    det = [("Document version", "1.3")] + POLICY[1:]
    write("V08_policy_unregistered_v1.3.pdf", kv("Safeguarding reconciliation policy (synthetic)", det, body=("Synthetic.",)))
    add("V08_policy_unregistered_v1.3.pdf", "policy version 1.3 (not registered)", "REJECT_OR_HOLD (POLICY_NOT_RECOGNISED)", det)
    # V09: malformed timestamp
    det = [(k, "17/09/2026 11:02") if k == "Submitted at" else (k, v) for k, v in RECEIPT]
    write("V09_receipt_bad_timestamp.pdf", kv("Monthly safeguarding return - submission receipt (synthetic)", det, body=("Generated for the UC-042 POC.",)))
    add("V09_receipt_bad_timestamp.pdf", "'Submitted at' not ISO 8601", "HUMAN_REVIEW (FORMAT failure), value preserved as written", det)
    # V10: letter whose reference matches no IN-02 account
    det = [("Letter reference", "ACK-INST01-9999")] + GBP_LETTER[1:]
    write("V10_letter_unknown_reference.pdf", kv("Safeguarding account acknowledgement (synthetic)", det))
    add("V10_letter_unknown_reference.pdf", "letter reference not in IN-02", "HUMAN_REVIEW (category ambiguous IN-15|IN-16)", det)
    # V11: business-rule failure with a well-formed value (CONTROL, not an extraction problem)
    det = [(k, "2026-10-01") if k == "Allocated from" else (k, v) for k, v in GOV]
    write("V11_governance_allocated_after_period.pdf", kv("Governance register extract (synthetic)", det, body=("Optional supporting evidence.",)))
    add("V11_governance_allocated_after_period.pdf", "well-formed date after the period end",
        "DETERMINISTIC extraction; CONTROL GOV-ALLOCATED-FROM FAIL reported for UC-042 (C16)", det)
    (out / "variants_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = build(Path(sys.argv[1]))
    print(f"{len(m)} variants written to {sys.argv[1]}")
