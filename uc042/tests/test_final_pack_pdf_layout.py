"""Final-pack PDF layout regressions found by visual inspection of the S05 preview (pypdfium2 page renders):
mid-word splits in table headers and enumerations, cramped seven-column evidence table, card headings separated from
their content across pages, and section headings stranded at a page foot. Offline. Run from uc042/: python -m unittest -v"""
import importlib.util
import io
import re
import unittest

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import CondPageBreak, Table

from tests.test_final_pack_render import RenderCase
from uc042lib.final_pack.render_pdf import _PAD, _col_widths, _flowables, _item, _styles, _table, pdf_text
from uc042lib.final_pack.report import SECTIONS, build_report

WIDTH = A4[0] - 30 * mm


def _words(text, font, size):
    return max((stringWidth(w, font, size) for w in pdf_text(text).split()), default=0)


class ColumnWidths(unittest.TestCase):
    def setUp(self):
        self.st = _styles()

    def test_headers_and_enumerations_are_not_split_mid_word(self):
        # Shape of the deterministic results tables that rendered "Requireme/nt" and "NOT_APPLICAB/LE".
        b = {"headers": ["Date", "Ccy", "Requirement", "Resource", "Difference", "Reported", "Outcome", "Evidence status"],
             "rows": [["2026-09-01", "GBP", "341484.46", "341484.46", "0.00", "0.00", "NOT_APPLICABLE", "NOT_EVIDENCED"],
                      ["2026-09-02", "EUR", "80000.00", "80000.00", "0.00", "0.00", "ALL_PASSED_OR_NOT_APPLICABLE", ""]],
             "code_cols": []}
        col = _col_widths(b, self.st, WIDTH)
        self.assertAlmostEqual(sum(col), WIDTH, places=3)
        for j, w in enumerate(col):
            need = max(_words(b["headers"][j], "Helvetica-Bold", self.st["head"].fontSize),
                       max(_words(r[j], self.st["cell"].fontName, self.st["cell"].fontSize) for r in b["rows"]))
            self.assertGreaterEqual(w, need + _PAD - 0.01, b["headers"][j])


class PageFlow(RenderCase):
    def test_report_grid_tables_keep_words_whole_where_the_page_allows(self):
        st = _styles()
        tables = [b for b in build_report(self.final) if b["type"] == "table" and b.get("layout", "grid") == "grid"]
        self.assertTrue(tables)
        for b in tables:
            col = _col_widths(b, st, WIDTH)
            self.assertAlmostEqual(sum(col), WIDTH, places=3)
            for j, w in enumerate(col):
                if j in b["code_cols"]:
                    continue
                need = max(_words(b["headers"][j], "Helvetica-Bold", st["head"].fontSize),
                           max((_words(r[j], st["cell"].fontName, st["cell"].fontSize) for r in b["rows"]), default=0))
                if need + _PAD <= WIDTH * 0.45:
                    self.assertGreaterEqual(w, need + _PAD - 0.01, (b["headers"], b["headers"][j]))

    def test_evidence_table_is_rendered_as_labelled_cards_in_pdf_only(self):
        st = _styles()
        evidence = [b for b in build_report(self.final) if b["type"] == "table" and b.get("layout") == "records"]
        self.assertEqual(len(evidence), 1)
        b = evidence[0]
        cards = [f for f in _table(b, st, WIDTH) if isinstance(f, Table)]
        self.assertEqual(len(cards), len(b["rows"]))
        for card, row in zip(cards, cards and b["rows"]):
            self.assertEqual(card.repeatRows, 1)
            self.assertIn(pdf_text(row[0]), card._cellvalues[0][0].getPlainText())
            self.assertEqual(len(card._cellvalues), len(b["headers"]))  # heading row + one row per remaining column
        for h in b["headers"]:  # the HTML ignores the hint and keeps the grid table
            self.assertIn(f"<th>{h}</th>", self.html)

    def test_card_heading_repeats_and_kv_panels_do_not(self):
        st = _styles()
        card = _item({"kind": "gap", "heading": "INV-X#M-03", "badge": "EVIDENCE GAP", "fields": [("Description", "d")]}, st, WIDTH)
        kv = _item({"type": "kv", "pairs": [("Final pack", "P")]}, st, WIDTH, kv=True)
        self.assertEqual((card.repeatRows, kv.repeatRows), (1, 0))

    def test_section_and_sub_headings_are_guarded_against_page_foot(self):
        flow = _flowables(build_report(self.final), _styles(), WIDTH)
        heads = [i for i, f in enumerate(flow) if getattr(f, "style", None) is not None and f.style.name in ("h2", "h3")]
        self.assertTrue(heads)
        for i in heads:
            self.assertIsInstance(flow[i - 1], CondPageBreak, flow[i].getPlainText())

    def test_closing_summary_heading_shares_its_page_with_content_and_is_last(self):
        reader = PdfReader(io.BytesIO(self.pdf))
        title = f"{len(SECTIONS)}. {SECTIONS[-1][1]}"
        pages = [i for i, p in enumerate(reader.pages) if title in p.extract_text()]
        self.assertGreater(pages[-1], 0)  # page 1 also lists it in the contents
        text = reader.pages[pages[-1]].extract_text()
        after = re.sub(r"\s+", "", text[text.index(title) + len(title):])
        notice = re.sub(r"\s+", "", pdf_text(self.final["statements"]["closing_summary_notice"]))[:40]
        self.assertIn(notice, after)  # the heading is followed by its content on the same page
        later = "".join(p.extract_text() for p in reader.pages[pages[-1] + 1:])
        self.assertFalse([t for n, (_, t) in enumerate(SECTIONS, 1) if f"{n}. {t}" in later], "a section follows the closing summary")

    @unittest.skipUnless(importlib.util.find_spec("pypdfium2"), "pypdfium2 (dev-only) not installed")
    def test_every_page_rasterises_with_visible_content(self):
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(self.pdf)
        try:
            self.assertEqual(len(doc), self.pages)
            for i in range(len(doc)):
                img = doc[i].render(scale=0.5).to_pil().convert("L")
                lo, hi = img.getextrema()
                self.assertLess(lo, 128, f"page {i + 1} looks blank")
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
