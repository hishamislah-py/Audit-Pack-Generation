"""PDF report from the canonical final pack (via report.build_report only), using ReportLab (already a pinned dependency).
A4, header and footer with page N of M, wrapped table cells (never clipped), repeated table headers, row-level page
splitting, and byte-reproducible output (invariant=1).

Two renderers, chosen by the pack itself (renderer_of), so a published pack always re-renders exactly as published:

  uc042-final-report-renderer/1.0          the built-in Helvetica / Courier (cp1252). Other characters are mapped to
                                           ASCII equivalents by pdf_text(). Every pack that declares no renderer (all packs
                                           published before final-pack schema 1.1) uses it, byte for byte unchanged.
  uc042-final-report-renderer/3.0-unicode  as 2.1 (fonts, row splitting), with the outcome-first layout of report_v3.py
  uc042-final-report-renderer/2.1-unicode  as 2.0, and a table row may split inside the row across pages (long findings)
  uc042-final-report-renderer/2.0-unicode  the bundled DejaVu fonts (fonts/, licence in fonts/LICENSE-DejaVu.txt, files
                                           verified against fonts/fonts.json) plus optional fallback fonts configured in
                                           UC042_PDF_FALLBACK_FONTS. Text is drawn exactly as stored. A character that no
                                           configured font can draw is never substituted: rendering stops with
                                           PdfGlyphError naming the characters and where they occur.
"""
import contextvars
import hashlib
import io
import json
import os
import threading
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .model import OUTCOME_RENDERER_VERSION, RENDERER_VERSION, SPLITTING_RENDERER_VERSION, UNICODE_RENDERER_VERSION
from .report import block_texts, build_report

OK, WARN, BAD, MUTED, LINE, PANEL = (colors.HexColor(c) for c in ("#1e7d3c", "#a15c00", "#b3261e", "#5f6368", "#d9dce1", "#f6f7f9"))
_MAP = {"−": "-", "→": "->", "←": "<-", "≤": "<=", "≥": ">=", "≠": "!=", " ": " ", "‑": "-",
        "‐": "-", " ": " ", " ": " ", "≈": "~", "×": "x"}
KIND_COLOUR = {"confirmed": OK, "assessment": MUTED, "hypothesis": WARN, "gap": MUTED, "conflict": BAD, "unresolved": BAD,
               "info": MUTED, "step": MUTED, "rejected": BAD, "accepted": OK,  # rejected / accepted: analyst reviews (schema 1.1)
               # closing-summary group assessments (summary schema 1.2); never present in packs written before it
               "relationship_backed": MUTED, "relationship_unverified": WARN, "relationship_rejected": BAD,
               # evidence-bearing relationships (23 Nov 2026): the engine's relationship proof (deterministic)
               "engine_relationship": OK}
FONT_DIR = Path(__file__).resolve().parent / "fonts"
ENV_FALLBACK_FONTS = "UC042_PDF_FALLBACK_FONTS"  # optional: os.pathsep-separated .ttf/.ttc paths, tried in order


def pdf_text(s):
    """Text as it can be drawn with the standard fonts (cp1252) - renderer 1.0 only."""
    s = "".join(_MAP.get(ch, ch) for ch in str(s))
    return s.encode("cp1252", errors="replace").decode("cp1252")


class PdfGlyphError(ValueError):
    """Text that no configured PDF font can draw. Raised instead of drawing a substitute; nothing is rendered."""

    def __init__(self, problems):
        self.problems = list(problems)
        shown = "; ".join(f"{p['character']!r} {p['codepoint']} ({p['name']}) in \"{p['context']}\"" for p in self.problems[:8])
        super().__init__(f"the PDF cannot render {len(self.problems)} character(s) with the configured fonts: {shown}. Configure a "
                         f"fallback font that covers them ({ENV_FALLBACK_FONTS}) or change the text; no PDF was produced.")


class PdfFontError(RuntimeError):
    """A bundled or configured font is missing or does not match its recorded SHA-256."""


class _FontSet:
    def __init__(self, renderer, base, bold, oblique, mono, text, faces=None, chain=(), fonts=()):
        self.renderer, self.base, self.bold, self.oblique, self.mono, self.text = renderer, base, bold, oblique, mono, text
        self.faces, self.chain, self.fonts = faces or {}, tuple(chain), list(fonts)  # name -> set of codepoints; fallback order

    def font_for(self, ch, name):
        """The font that draws ch in a run styled `name`: the style's own font, else the bundled regular face, else a
        configured fallback (None: nothing can draw it)."""
        cp = ord(ch)
        for n in (name, *self.chain):
            if cp in self.faces.get(n, ()):
                return n
        return None

    def markup(self, text, name):
        if not self.faces:  # renderer 1.0: unchanged
            return escape(pdf_text(text)).replace("\n", "<br/>")
        out, run, run_font = [], [], name
        for ch in str(text):
            if ch == "\n" or ch.isspace():
                f = run_font
            else:
                f = self.font_for(ch, name)
                if f is None:
                    raise PdfGlyphError([_problem(ch, text)])
            if f != run_font and run:
                out.append(_wrap("".join(run), run_font, name))
                run = []
            run_font = f
            run.append(ch)
        if run:
            out.append(_wrap("".join(run), run_font, name))
        return "".join(out).replace("\n", "<br/>")


def _wrap(s, font, base):
    s = escape(s)
    return s if font == base else f'<font name="{font}">{s}</font>'


def _problem(ch, context):
    i = str(context).find(ch)
    return {"character": ch, "codepoint": f"U+{ord(ch):04X}", "name": unicodedata.name(ch, "unnamed"),
            "context": str(context)[max(0, i - 30):i + 30].replace("\n", " ")}


LEGACY = _FontSet(RENDERER_VERSION, "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier", pdf_text)
_UNICODE = None
_UNICODE_LOCK = threading.Lock()
_CURRENT = contextvars.ContextVar("uc042_pdf_fonts", default=LEGACY)  # per thread / task: renders may run concurrently
# Renderer 2.1: rows may split inside the row (splitInRow). Off for 1.0 / 2.0 so published packs re-render byte for byte.
_SPLIT_IN_ROW = contextvars.ContextVar("uc042_pdf_split_in_row", default=False)


def _split_args():
    return {"splitInRow": 1} if _SPLIT_IN_ROW.get() else {}


def _sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _unicode_fonts():
    """Register the bundled DejaVu faces (each verified against fonts.json) and the configured fallbacks, once."""
    global _UNICODE
    with _UNICODE_LOCK:
        if _UNICODE is not None:
            return _UNICODE
        manifest = json.loads((FONT_DIR / "fonts.json").read_text(encoding="utf-8"))
        names = {"UC042-DejaVuSans": "DejaVuSans.ttf", "UC042-DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
                 "UC042-DejaVuSans-Oblique": "DejaVuSans-Oblique.ttf", "UC042-DejaVuSansMono": "DejaVuSansMono.ttf"}
        faces, fonts = {}, []
        for name, file in names.items():
            path = FONT_DIR / file
            if not path.is_file() or _sha256(path) != manifest["files"].get(file):
                raise PdfFontError(f"bundled PDF font {file} is missing or does not match fonts/fonts.json")
            font = TTFont(name, str(path))
            pdfmetrics.registerFont(font)
            faces[name] = set(font.face.charToGlyph)
            fonts.append({"name": name, "file": file, "sha256": manifest["files"][file], "source": "bundled"})
        chain = ["UC042-DejaVuSans"]
        for i, raw in enumerate(p for p in os.environ.get(ENV_FALLBACK_FONTS, "").split(os.pathsep) if p.strip()):
            path = Path(raw.strip())
            if not path.is_file():
                raise PdfFontError(f"{ENV_FALLBACK_FONTS}: font file not found: {path}")
            name = f"UC042-Fallback-{i + 1}"
            font = TTFont(name, str(path), subfontIndex=0) if path.suffix.lower() == ".ttc" else TTFont(name, str(path))
            pdfmetrics.registerFont(font)
            faces[name] = set(font.face.charToGlyph)
            chain.append(name)
            fonts.append({"name": name, "file": path.name, "sha256": _sha256(path), "source": ENV_FALLBACK_FONTS})
        _UNICODE = _FontSet(UNICODE_RENDERER_VERSION, "UC042-DejaVuSans", "UC042-DejaVuSans-Bold", "UC042-DejaVuSans-Oblique",
                            "UC042-DejaVuSansMono", lambda s: str(s), faces, chain, fonts)
        return _UNICODE


def renderer_of(final):
    """The renderer a pack declares (final-pack schema 1.1 packs); renderer 1.0 for every pack that declares none."""
    return final["metadata"].get("report_renderer") or RENDERER_VERSION


def _fonts_for(final):
    r = renderer_of(final)
    if r == RENDERER_VERSION:
        return LEGACY
    if r in (UNICODE_RENDERER_VERSION, SPLITTING_RENDERER_VERSION, OUTCOME_RENDERER_VERSION):
        return _unicode_fonts()  # 2.1 and 3.0 draw with the same fonts as 2.0
    raise ValueError(f"unknown report renderer {r!r}")


def pdf_fonts(final):
    """The fonts (name, file, SHA-256, source) the pack's PDF is drawn with; [] for renderer 1.0 (standard fonts)."""
    return [dict(f) for f in _fonts_for(final).fonts]


def unsupported_in_text(text):
    """Characters of one text (for example an analyst's reason) that the Unicode renderer's fonts cannot draw."""
    fonts = _unicode_fonts()
    out, seen = [], set()
    for ch in str(text or ""):
        if ch in seen or ch.isspace():
            continue
        seen.add(ch)
        if fonts.font_for(ch, fonts.base) is None:
            out.append({k: v for k, v in _problem(ch, text).items() if k != "context"})
    return out


def unsupported_characters(final):
    """Every character of the report's text that no configured font can draw ([] for renderer 1.0, which maps text to
    cp1252 by design). Checked before anything is rendered."""
    fonts = _fonts_for(final)
    if not fonts.faces:
        return []
    m = final["metadata"]
    texts = block_texts(build_report(final)) + [f"UC-042 Final Audit Pack - {m['final_pack_id']} - {m['reporting_period']['period_id']}"]
    seen, problems = set(), []
    for t in texts:
        for ch in str(t):
            if ch in seen or ch.isspace():
                continue
            seen.add(ch)
            if fonts.font_for(ch, fonts.base) is None and fonts.font_for(ch, fonts.mono) is None:
                problems.append(_problem(ch, t))
    return problems


def _styles():
    f = _CURRENT.get()
    base = ParagraphStyle("base", fontName=f.base, fontSize=8.6, leading=11, alignment=TA_LEFT)
    return {"base": base, "small": ParagraphStyle("small", parent=base, fontSize=7.2, leading=9),
            "code": ParagraphStyle("code", parent=base, fontName=f.mono, fontSize=6.8, leading=8.4, wordWrap="CJK"),
            "cell": ParagraphStyle("cell", parent=base, fontSize=7.2, leading=9),
            "title": ParagraphStyle("title", parent=base, fontName=f.bold, fontSize=15, leading=19, spaceAfter=3),
            "subtitle": ParagraphStyle("subtitle", parent=base, textColor=MUTED, spaceAfter=8),
            "h2": ParagraphStyle("h2", parent=base, fontName=f.bold, fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=5),
            "h3": ParagraphStyle("h3", parent=base, fontName=f.bold, fontSize=9.6, leading=12, spaceBefore=7, spaceAfter=3),
            "label": ParagraphStyle("label", parent=base, fontSize=7.6, leading=9.6, textColor=MUTED),
            "head": ParagraphStyle("head", parent=base, fontName=f.bold, fontSize=7.2, leading=9),
            "muted": ParagraphStyle("muted", parent=base, fontSize=7.4, leading=9.4, textColor=MUTED)}


def _p(text, style):
    return Paragraph(_CURRENT.get().markup(text, style.fontName), style)


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
            self.setFont(_CURRENT.get().base, 7)
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
    f = _CURRENT.get()
    n = len(b["headers"])
    mins, wants = [], []
    for j in range(n):
        code = j in b["code_cols"]
        cell_style = st["code"] if code else st["cell"]
        head_w = max((stringWidth(w, f.bold, st["head"].fontSize) for w in f.text(b["headers"][j]).split()), default=0)
        cells = [f.text(r[j]) for r in b["rows"]]
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
    t = Table(rows, colWidths=col, repeatRows=1, splitByRow=1, **_split_args())
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
    t = Table(rows, colWidths=[width * 0.27, width * 0.73], splitByRow=1, repeatRows=0 if kv else 1, **_split_args())
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
             ("LINEBEFORE", (0, 0), (0, -1), 3 if not kv else 0.6, colour), ("BOX", (0, 0), (-1, -1), 0.4, LINE)]
    if not kv:
        style.append(("SPAN", (0, 0), (-1, 0)))
    if b.get("kind") in ("assessment", "gap", "relationship_backed") or kv:
        style.append(("BACKGROUND", (0, 0), (-1, -1), PANEL))
    if b.get("kind") in ("hypothesis", "relationship_unverified"):
        style += [("BOX", (0, 0), (-1, -1), 1.2, WARN, None, (3, 2))]
    if b.get("kind") in ("conflict", "rejected", "relationship_rejected"):
        style += [("BOX", (0, 0), (-1, -1), 1.2, BAD)]
    t.setStyle(TableStyle(style))
    return t


def _outcome(b, st, width):
    """Renderer 3.0 outcome panel: the engine status badge with its label, a row of figure tiles, the headline sentence."""
    f = _CURRENT.get()
    size = 15 if len(b["badge"]) <= 12 else 12  # the engine's status exactly as stored, never split mid-word
    badge = Table([[_p(b["badge"], ParagraphStyle("ob", parent=st["base"], fontName=f.bold, fontSize=size, leading=size + 3,
                                                  textColor=colors.white)),
                    _p(b["label"], ParagraphStyle("ol", parent=st["base"], fontSize=8, leading=10, textColor=MUTED))]],
                  colWidths=[width * 0.4, width * 0.6])
    colour = OK if b["badge"] == "CLEAN" else WARN if b["badge"] == "EVIDENCE_INCOMPLETE" else BAD
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), colour), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
    n = len(b["tiles"])
    value = ParagraphStyle("tv", parent=st["base"], fontName=f.bold, fontSize=13, leading=16)
    tiles = Table([[_p(v, value) for _, v in b["tiles"]], [_p(k, st["label"]) for k, _ in b["tiles"]]], colWidths=[width / n] * n)
    tiles.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                               ("LINEBEFORE", (1, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, 0), 6),
                               ("BOTTOMPADDING", (0, 1), (-1, 1), 6)]))
    headline = _p(b["headline"], ParagraphStyle("hl", parent=st["base"], fontName=f.bold, fontSize=10, leading=13, spaceBefore=6))
    return [KeepTogether([badge, Spacer(1, 4), tiles, headline]), Spacer(1, 6)]


def _flowables(blocks, st, width):
    f = _CURRENT.get()
    out = []
    for b in blocks:
        t = b["type"]
        if t == "title":
            out += [_p(b["text"], st["title"]), _p(b["subtitle"], st["subtitle"])]
        elif t == "section":  # never strand a section heading at a page foot
            h = Paragraph(f'<a name="{b["anchor"]}"/>{b["number"]}. {f.markup(b["title"], st["h2"].fontName)}', st["h2"])
            out += [CondPageBreak(b.get("keep_mm", 70) * mm), h]  # keep_mm: renderer 3.0 blocks only
        elif t == "sub":
            out += [CondPageBreak(30 * mm), _p(b["text"], st["h3"])]
        elif t == "para":
            out += [_p(b["text"], st["muted"] if b.get("cls") == "muted" else st["base"]), Spacer(1, 3)]
        elif t == "notice":
            colour = {"bad": BAD, "warn": WARN, "ok": OK}.get(b["cls"], MUTED)  # "ok": renderer 3.0 blocks only
            n = Table([[_p(b["text"], ParagraphStyle("n", parent=st["base"], fontName=f.bold if b["cls"] == "bad" else
                                                      (f.oblique if b["cls"] == "ai" else f.base)))]], colWidths=[width])
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
        elif t == "outcome":  # renderer 3.0: the executive outcome panel
            out += _outcome(b, st, width)
        elif t == "toc" and b.get("columns") == 1:  # renderer 3.0: one column, in reading order
            toc = Table([[_p("Contents", st["head"])]] + [[_p(f"{n}. {title}", st["cell"])] for n, title, _ in b["entries"]], colWidths=[width])
            toc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
            out += [KeepTogether([toc]), Spacer(1, 6)]
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
    """Return the PDF report as bytes, drawn with the renderer the pack declares (renderer_of). Raises PdfGlyphError
    (renderer 2.0) instead of drawing a character no configured font has."""
    fonts = _fonts_for(final)
    problems = unsupported_characters(final)
    if problems:
        raise PdfGlyphError(problems)
    token = _CURRENT.set(fonts)
    split_token = _SPLIT_IN_ROW.set(renderer_of(final) in (SPLITTING_RENDERER_VERSION, OUTCOME_RENDERER_VERSION))
    try:
        blocks, st, m = build_report(final), _styles(), final["metadata"]
        buf = io.BytesIO()
        margin = 15 * mm
        doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=18 * mm, bottomMargin=16 * mm,
                              title=fonts.text(f"UC-042 Final Audit Pack {m['final_pack_id']}"), author="UC-042 final-pack renderer",
                              subject="Synthetic audit pack - not a compliance opinion", creator="uc042lib.final_pack", invariant=1)
        width = A4[0] - 2 * margin
        header = fonts.text(f"UC-042 Final Audit Pack - {m['final_pack_id']} - {m['reporting_period']['period_id']}")
        footer = fonts.text(f"Synthetic data - not a compliance opinion - content {final['final_content_sha256'][:12]}"
                            + (" - PREVIEW, not a final audit pack" if m["status"] == "PREVIEW" else ""))

        def decorate(canv, _doc):
            canv.saveState()
            canv.setFont(fonts.base, 7)
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
    finally:
        _SPLIT_IN_ROW.reset(split_token)
        _CURRENT.reset(token)
