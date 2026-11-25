"""Final-pack rendering: JSON round trip, HTML sections and classes, PDF generation (multi-page, reproducible, no clipping)
and HTML/PDF/JSON consistency through the shared block model. Offline. Run from uc042/: python -m unittest -v"""
import html
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from tests.final_pack_support import PACK, make_investigation, review_for, summary_investigator
from uc042lib.final_pack import (GenerationInfo, assemble_final_pack, assemble_preview, build_review_snapshot, default_selections,
                                 generate_closing_summary, load_pack, render_html, render_pdf)
from uc042lib.final_pack.render_pdf import pdf_text
from uc042lib.final_pack.report import SECTIONS, block_texts, build_report
from uc042lib.pack.model import canonical

LONG = ("Supporting observation " + " ".join(f"word{i:03d}" for i in range(260)) +
        " with an unbroken token IN-13:SL-SB-GBP-20260915-0003-AND-A-VERY-LONG-UNBROKEN-IDENTIFIER-THAT-MUST-WRAP-0123456789ABCDEF")


def _norm(s):
    return re.sub(r"\s+", "", pdf_text(s))


class RenderCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        inv_root = cls.tmp / "investigations"

        def long_finding(o):
            o["confirmed_findings"][0]["explanation"] = LONG
            o["confirmed_findings"][0]["does_not_establish"] = "Why the line references a transaction that is not in the supplied export. " * 6
        make_investigation("SC5A", "EXC-SC5A-01", inv_root, edit=long_finding)
        cls.snap = build_review_snapshot(PACK["SC5A"], default_selections(load_pack(PACK["SC5A"]), inv_root), investigations_root=inv_root)
        inv, _ = summary_investigator(cls.snap)
        cls.summary = generate_closing_summary(cls.snap, inv)
        cls.final = assemble_final_pack(cls.snap, cls.summary, review_for(cls.snap, cls.summary), GenerationInfo())
        cls.html = render_html(cls.final)
        cls.pdf = render_pdf(cls.final)
        reader = PdfReader(io.BytesIO(cls.pdf))
        cls.pages = len(reader.pages)
        cls.pdf_text = "".join(p.extract_text() for p in reader.pages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)


class Rendering(RenderCase):
    def test_json_round_trip(self):
        self.assertEqual(json.loads(canonical(self.final)), self.final)
        self.assertEqual(self.final["final_pack_schema_version"], "uc042-final-pack/1.0")

    def test_html_sections_order_and_closing_summary_last(self):
        positions = [self.html.find(f"{i + 1}. {html.escape(title)}</h2>") for i, (_, title) in enumerate(SECTIONS)]
        self.assertTrue(all(p > 0 for p in positions), positions)
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(SECTIONS[-1][1], "AI-Generated Closing Summary")
        tail = self.html[positions[-1]:]
        self.assertNotIn("<h2", tail[5:])  # nothing substantive after the closing summary
        self.assertIn(html.escape(self.final["statements"]["closing_summary_notice"]), tail)
        for cls in ("item confirmed", "item assessment", "item hypothesis", "item unresolved", "item gap", "notice bad"):
            self.assertIn(f"class='{cls}", self.html)
        self.assertIn(">UNRESOLVED<", self.html)
        self.assertIn("HYPOTHESIS - NOT ESTABLISHED", self.html)

    def test_pdf_multi_page_reproducible_and_not_clipped(self):
        self.assertTrue(self.pdf.startswith(b"%PDF"))
        self.assertGreater(self.pages, 3)
        self.assertEqual(render_pdf(self.final), self.pdf)  # byte-reproducible
        self.assertIn(f"Page 1 of {self.pages}", self.pdf_text)
        flat = _norm(self.pdf_text)
        for token in LONG.split():  # every word of a very long finding survives wrapping and page breaks
            self.assertIn(_norm(token), flat, token)
        self.assertIn("AI-Generated Closing Summary", self.pdf_text)

    def test_both_renderers_show_the_same_substantive_content(self):
        blocks = build_report(self.final)
        texts = block_texts(blocks)
        page_html = html.unescape(re.sub(r"<[^>]+>", " ", self.html))
        flat_html, flat_pdf = re.sub(r"\s+", "", page_html), _norm(self.pdf_text)
        missing_html = [t for t in texts if re.sub(r"\s+", "", t) not in flat_html]
        self.assertEqual(missing_html, [])
        pdf_words = set(re.findall(r"\S+", pdf_text(self.pdf_text)))
        missing_pdf = [t for t in texts if _norm(t) not in flat_pdf and not set(re.findall(r"\S+", pdf_text(t))) <= pdf_words]
        self.assertEqual(missing_pdf, [])
        for f in self.final["ai_investigations"][0]["confirmed_findings"]:  # spot-check JSON values in both outputs
            for value in (f["title"], f["establishes"]):
                self.assertIn(re.sub(r"\s+", "", value), flat_html)

    def test_historical_fields_are_shown_as_not_supplied(self):
        legacy = json.loads(json.dumps(self.final))
        legacy["ai_investigations"][0]["confirmed_findings"][0]["audit_relevance"] = None
        text = " ".join(block_texts(build_report(legacy)))
        self.assertIn("Not supplied by this investigation", text)

    def test_clean_pack_and_preview_render(self):
        snap = build_review_snapshot(PACK["S01"], [], investigations_root=self.tmp / "investigations")
        inv, _ = summary_investigator(snap)
        preview = assemble_preview(snap, generate_closing_summary(snap, inv))
        page = render_html(preview)
        self.assertIn("PREVIEW - not a final audit pack", page)
        self.assertIn("No exceptions were raised by the deterministic engine.", page)
        self.assertTrue(render_pdf(preview).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
