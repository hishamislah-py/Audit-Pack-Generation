"""PDF report from the canonical final pack (via report.build_report only), using ReportLab (already a pinned dependency).
A4, header and footer with page N of M, wrapped table cells (never clipped), repeated table headers, row-level page
splitting, and byte-reproducible output (invariant=1). The built-in Helvetica covers cp1252; other characters are mapped
to ASCII equivalents by pdf_text() (the same mapping the consistency tests apply), never dropped silently."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .report import build_report

OK, WARN, BAD, MUTED, LINE, PANEL = (colors.HexColor(c) for c in ("#1e7d3c", "#a15c00", "#b3261e", "#5f6368", "#d9dce1", "#f6f7f9"))
_MAP = {"−": "-", "→": "->", "←": "<-", "≤": "<=", "≥": ">=", "≠": "!=", " ": " ", "‑": "-",
        "‐": "-", " ": " ", " ": " ", "≈": "~", "×": "x"}
KIND_COLOUR = {"confirmed": OK, "assessment": MUTED, "hypothesis": WARN, "gap": MUTED, "conflict": BAD, "unresolved": BAD,
               "info": MUTED, "step": MUTED}


def pdf_text(s):
    """Text as it can be drawn with the standard fonts (cp1252)."""
    s = "".join(_MAP.get(ch, ch) for ch in str(s))
    return s.encode("cp1252", errors="replace").decode("cp1252")


def _styles():
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.6, leading=11, alignment=TA_LEFT)
    return {"base": base, "small": ParagraphStyle("small", parent=base, fontSize=7.2, leading=9),
            "code": ParagraphStyle("code", parent=base, fontName="Courier", fontSize=6.8, leading=8.4, wordWrap="CJK"),
            "cell": ParagraphStyle("cell", parent=base, fontSize=7.2, leading=9),
            "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=3),
            "subtitle": ParagraphStyle("subtitle", parent=base, textColor=MUTED, spaceAfter=8),
            "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=5),
            "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=9.6, leading=12, spaceBefore=7, spaceAfter=3),
            "label": ParagraphStyle("label", parent=base, fontSize=7.6, leading=9.6, textColor=MUTED),
            "head": ParagraphStyle("head", parent=base, fontName="Helvetica-Bold", fontSize=7.2, leading=9),
            "muted": ParagraphStyle("muted", parent=base, fontSize=7.4, leading=9.4, textColor=MUTED)}


def _p(text, style):
    return Paragraph(escape(pdf_text(text)).replace("\n", "<br/>"), style)


class _NumberedCanvas(rl_canvas.Canvas):
    """Two-pass page numbering: 'Page N of M'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7)
            self.setFillColor(MUTED)
            self.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


_PAD = 7  # left + right cell padding (3 + 3) plus a point of slack


def _col_widths(b, st, width):
    """Content-aware column widths. Each column gets at least the width of its longest unbreakable word (header
    included) where the page allows, so enumerations, headers and identifiers are not split mid-word; remaining width
    goes to the columns with the most text. Identifier/hash columns (code_cols) may break anywhere, so their minimum
    is capped. Falls back to proportional minimums only when even those cannot fit."""
    n = len(b["headers"])
    mins, wants = [], []
    for j in range(n):
        code = j in b["code_cols"]
        cell_style = st["code"] if code else st["cell"]
        head_w = max((stringWidth(w, "Helvetica-Bold", st["head"].fontSize) for w in pdf_text(b["headers"][j]).split()), default=0)
        cells = [pdf_text(r[j]) for r in b["rows"]]
        word_w = max((stringWidth(w, cell_style.fontName, cell_style.fontSize) for c in cells for w in c.split()), default=0)
        if code:
            word_w = min(word_w, 70)
        full_w = max((stringWidth(c, cell_style.fontName, cell_style.fontSize) for c in cells), default=0)
        mins.append(min(max(head_w, word_w) + _PAD, width * 0.45))
        wants.append(max(mins[-1], min(full_w + _PAD, width)))
    if sum(wants) <= width:
        return [w * width / sum(wants) for w in wants]
    if sum(mins) <= width:
        spare, extra = width - sum(mins), [w - m for w, m in zip(wants, mins)]
        return [m + spare * e / sum(extra) for m, e in zip(mins, extra)]
    return [m * width / sum(mins) for m in mins]


def _table(b, st, width):
    if b.get("layout") == "records":  # dense record tables: one labelled card per row (same cells, readable widths)
        out = []
        for r in b["rows"]:
            out += [_item({"kind": "info", "heading": r[0], "badge": b["headers"][0], "fields": list(zip(b["headers"][1:], r[1:]))},
                          st, width), Spacer(1, 4)]
        return out
    col = _col_widths(b, st, width)
    rows = [[_p(h, st["head"]) for h in b["headers"]]]
    rows += [[_p(c, st["code"] if i in b["code_cols"] else st["cell"]) for i, c in enumerate(r)] for r in b["rows"]]
    t = Table(rows, colWidths=col, repeatRows=1, splitByRow=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), PANEL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _item(b, st, width, kv=False):
    colour = KIND_COLOUR.get(b.get("kind", "info"), MUTED)
    rows = [] if kv else [[_p(f"{b['heading']}   [{b['badge']}]", ParagraphStyle("ih", parent=st["head"], fontSize=8.4, leading=10.6,
                                                                                        textColor=colour if b["kind"] != "info" else colors.black)), ""]]
    rows += [[_p(k, st["label"]), _p(v, st["base"])] for k, v in (b["pairs"] if kv else b["fields"])]
    # The heading row repeats on a continuation page, and a split never leaves the heading alone at a page foot.
    t = Table(rows, colWidths=[width * 0.27, width * 0.73], splitByRow=1, repeatRows=0 if kv else 1)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
             ("LINEBEFORE", (0, 0), (0, -1), 3 if not kv else 0.6, colour), ("BOX", (0, 0), (-1, -1), 0.4, LINE)]
    if not kv:
        style.append(("SPAN", (0, 0), (-1, 0)))
    if b.get("kind") in ("assessment", "gap") or kv:
        style.append(("BACKGROUND", (0, 0), (-1, -1), PANEL))
    if b.get("kind") == "hypothesis":
        style += [("BOX", (0, 0), (-1, -1), 1.2, WARN, None, (3, 2))]
    if b.get("kind") == "conflict":
        style += [("BOX", (0, 0), (-1, -1), 1.2, BAD)]
    t.setStyle(TableStyle(style))
    return t


def _flowables(blocks, st, width):
    out = []
    for b in blocks:
        t = b["type"]
        if t == "title":
            out += [_p(b["text"], st["title"]), _p(b["subtitle"], st["subtitle"])]
        elif t == "section":  # never strand a section heading at a page foot
            h = Paragraph(f'<a name="{b["anchor"]}"/>{b["number"]}. {escape(pdf_text(b["title"]))}', st["h2"])
            out += [CondPageBreak(70 * mm), h]
        elif t == "sub":
            out += [CondPageBreak(30 * mm), _p(b["text"], st["h3"])]
        elif t == "para":
            out += [_p(b["text"], st["muted"] if b.get("cls") == "muted" else st["base"]), Spacer(1, 3)]
        elif t == "notice":
            colour = {"bad": BAD, "warn": WARN}.get(b["cls"], MUTED)
            n = Table([[_p(b["text"], ParagraphStyle("n", parent=st["base"], fontName="Helvetica-Bold" if b["cls"] == "bad" else
                                                      ("Helvetica-Oblique" if b["cls"] == "ai" else "Helvetica")))]], colWidths=[width])
            n.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LINEBEFORE", (0, 0), (0, -1), 3, colour),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            out += [n, Spacer(1, 4)]
        elif t == "kv":
            out += [_item(b, st, width, kv=True), Spacer(1, 4)]
        elif t == "table":
            tbl = _table(b, st, width)
            out += (tbl if isinstance(tbl, list) else [tbl]) + [Spacer(1, 5)]
        elif t == "item":
            out += [_item(b, st, width), Spacer(1, 5)]
        elif t == "bullets":
            out += [_p(f"- {i}", ParagraphStyle("li", parent=st["base"], leftIndent=8, firstLineIndent=-6)) for i in b["items"]] + [Spacer(1, 3)]
        elif t == "toc":
            rows = [[_p(f"{n}. {title}", st["cell"])] for n, title, _ in b["entries"]]
            half = (len(rows) + 1) // 2
            pairs = [[rows[i][0], rows[i + half][0] if i + half < len(rows) else ""] for i in range(half)]
            toc = Table([[_p("Contents", st["head"]), ""]] + pairs, colWidths=[width / 2] * 2)
            toc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("SPAN", (0, 0), (-1, 0)), ("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
            out += [KeepTogether([toc]), Spacer(1, 6)]
        elif t == "footer":
            out += [Spacer(1, 10), _p(b["text"], st["muted"])]
        else:
            raise ValueError(f"unknown block type {t!r}")
    return out


def render_pdf(final):
    """Return the PDF report as bytes."""
    blocks, st, m = build_report(final), _styles(), final["metadata"]
    buf = io.BytesIO()
    margin = 15 * mm
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=18 * mm, bottomMargin=16 * mm,
                          title=pdf_text(f"UC-042 Final Audit Pack {m['final_pack_id']}"), author="UC-042 final-pack renderer",
                          subject="Synthetic audit pack - not a compliance opinion", creator="uc042lib.final_pack", invariant=1)
    width = A4[0] - 2 * margin
    header = pdf_text(f"UC-042 Final Audit Pack - {m['final_pack_id']} - {m['reporting_period']['period_id']}")
    footer = pdf_text(f"Synthetic data - not a compliance opinion - content {final['final_content_sha256'][:12]}"
                      + (" - PREVIEW, not a final audit pack" if m["status"] == "PREVIEW" else ""))

    def decorate(canv, _doc):
        canv.saveState()
        canv.setFont("Helvetica", 7)
        canv.setFillColor(MUTED)
        canv.drawString(margin, A4[1] - 10 * mm, header)
        canv.drawString(margin, 9 * mm, footer)
        canv.setStrokeColor(LINE)
        canv.line(margin, A4[1] - 11.5 * mm, A4[0] - margin, A4[1] - 11.5 * mm)
        canv.restoreState()
    frame = Frame(margin, 16 * mm, width, A4[1] - 34 * mm, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=decorate)])
    doc.build(_flowables(blocks, st, width), canvasmaker=_NumberedCanvas)
    return buf.getvalue()
