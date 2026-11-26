"""Final-pack PDF with long findings (owner-approved renderer correction, 17 Nov 2026).

The live walkthrough failed GENERATE with a ReportLab LayoutError: one confirmed finding's "Exact amounts and dates (copied)"
field held 7,918 characters in a single table cell, taller than a page, and table rows only split between rows. Renderer
2.1-unicode lets a row split inside the row, so long findings flow across pages; nothing is shortened. Packs that declare
renderer 1.0 or 2.0 keep rendering exactly as published (verify_final_pack re-renders them byte for byte).

Fixture: tests/fixtures/live_long_finding_preview.json is the exact preview document of the failed live review (isolated test
database; synthetic data). Offline. Run from uc042/: python -m unittest tests.test_pdf_long_findings -v"""
import io
import json
import re
import unittest
from pathlib import Path

from pypdf import PdfReader
from reportlab.platypus.doctemplate import LayoutError

from uc042lib.final_pack.model import CURRENT_RENDERER_VERSION, SPLITTING_RENDERER_VERSION, UNICODE_RENDERER_VERSION
from uc042lib.final_pack.render_pdf import render_pdf
from uc042lib.final_pack.report import build_report

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_long_finding_preview.json"
LONG_ITEM = "INV-EXC-CASE-01-9f42b5eecb46#F-01"


def norm(s):
    return re.sub(r"\s+", "", s)


def with_renderer(doc, version):
    return dict(doc, metadata=dict(doc["metadata"], report_renderer=version))


def body_text(pdf, headings):
    """The PDF's text without page furniture: the two running header lines, the page footer and an item heading repeated at
    the top of a continuation page (with its badge)."""
    out = []
    for page in PdfReader(io.BytesIO(pdf)).pages:
        lines = page.extract_text().splitlines()[2:]
        if lines and re.match(r"^Page \d+ of \d+$", lines[-1].strip()):
            lines = lines[:-1]
        while lines and (lines[0].strip() in headings or re.match(r"^\[[A-Z -]+\]$", lines[0].strip())):
            lines = lines[1:]
        out.append("\n".join(lines))
    return "\n".join(out)


class LongFindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.blocks = build_report(cls.doc)
        cls.item = next(b for b in cls.blocks if b.get("type") == "item" and b["heading"].startswith(LONG_ITEM))
        cls.headings = {b["heading"] for b in cls.blocks if b.get("type") == "item"}

    def test_new_packs_declare_the_splitting_renderer(self):
        """Since 18 Nov 2026 new packs declare renderer 3.0, which keeps 2.1's in-row splitting (render_pdf)."""
        self.assertEqual(CURRENT_RENDERER_VERSION, "uc042-final-report-renderer/3.0-unicode")
        self.assertEqual(SPLITTING_RENDERER_VERSION, "uc042-final-report-renderer/2.1-unicode")

    def test_the_live_failure_is_reproduced_under_renderer_2_0(self):
        """Renderer 2.0 is unchanged (published 2.0 packs must re-render byte for byte): the live content still fails there."""
        self.assertEqual(self.doc["metadata"]["report_renderer"], UNICODE_RENDERER_VERSION)
        self.assertGreater(max(len(str(v)) for _, v in self.item["fields"]), 7000)
        with self.assertRaises(LayoutError):
            render_pdf(self.doc)

    def test_long_findings_flow_across_pages_complete_under_renderer_2_1(self):
        pdf = render_pdf(with_renderer(self.doc, SPLITTING_RENDERER_VERSION))
        reader = PdfReader(io.BytesIO(pdf))
        self.assertGreater(len(reader.pages), 20)
        body = norm(body_text(pdf, self.headings))
        long_fields = [(k, str(v)) for k, v in self.item["fields"] if len(str(v)) > 1000]
        self.assertEqual(len(long_fields), 3)
        for k, v in long_fields:  # nothing truncated, shortened or lost at a page break
            self.assertIn(norm(v), body, k)
        for k, v in self.item["fields"]:
            self.assertIn(norm(str(v)), body, k)
        for ref in re.findall(r"source_data/[a-z_0-9-]+\.csv:\d+", " ".join(str(v) for _, v in self.item["fields"])):
            self.assertIn(norm(ref), body)  # every citation (file:line) is present

    def test_every_item_of_the_report_is_present_under_renderer_2_1(self):
        pdf = render_pdf(with_renderer(self.doc, SPLITTING_RENDERER_VERSION))
        body = norm(body_text(pdf, self.headings))
        missing = [(b["heading"], k) for b in self.blocks if b.get("type") == "item"
                   for k, v in b["fields"] if norm(str(v)) and norm(str(v)) not in body]
        self.assertEqual(missing, [])

    def test_rendering_is_deterministic(self):
        doc = with_renderer(self.doc, SPLITTING_RENDERER_VERSION)
        self.assertEqual(render_pdf(doc), render_pdf(doc))


if __name__ == "__main__":
    unittest.main()
