"""HTML report from the canonical final pack (via report.build_report only). Reuses the deterministic pack's CSS tokens
(uc042lib/pack/render_html.py) so the app, the HTML and the PDF share one palette. Every value is escaped."""
from html import escape

from ..pack.render_html import CSS as PACK_CSS
from .model import OUTCOME_RENDERER_VERSION
from .report import build_report

EXTRA_CSS = """
.subtitle{color:var(--muted);margin:0 0 12px}.toc ol{columns:2;margin:6px 0 0 18px;padding:0}.toc a{color:inherit}
.notice.info{border-left:4px solid var(--muted)}.notice.warn{border-left:4px solid var(--warn)}.notice.bad{border-left:4px solid var(--bad);font-weight:600}
.notice.ai{border-left:4px solid var(--muted);font-style:italic}
.item{border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin:10px 0;break-inside:avoid}
.item h4{margin:0 0 6px;font-size:15px}.item dl{display:grid;grid-template-columns:minmax(140px,220px) 1fr;gap:4px 12px;margin:0}
.item dt{color:var(--muted);font-size:13px}.item dd{margin:0;font-size:14px;overflow-wrap:anywhere}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;padding:2px 6px;border-radius:4px;margin-left:8px;
 border:1px solid currentColor;vertical-align:middle}
.item.confirmed{border-left:5px solid var(--ok)}.item.confirmed .badge{color:var(--ok)}
.item.assessment{border-left:5px solid var(--muted);background:var(--panel)}.item.assessment .badge{color:var(--muted)}
.item.hypothesis{border:2px dashed var(--warn)}.item.hypothesis .badge{color:var(--warn)}
.item.gap{background:var(--panel)}.item.gap .badge{color:var(--muted)}
.item.conflict{border:2px solid var(--bad)}.item.conflict .badge{color:var(--bad)}
.item.unresolved{border-left:5px solid var(--bad)}.item.unresolved .badge{color:var(--bad)}
.item.info .badge,.item.step .badge{color:var(--muted)}
td code,dd code{font-size:12px}.muted{color:var(--muted)}footer{margin-top:32px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
section.closing{border-top:3px solid var(--line);margin-top:24px}
"""


def _t(x):
    return escape(str(x))


def _block(b):
    t = b["type"]
    if t == "outcome":  # renderer 3.0
        tiles = "".join(f"<div class='tile'><b>{_t(v)}</b><span>{_t(k)}</span></div>" for k, v in b["tiles"])
        cls = "ok" if b["badge"] == "CLEAN" else "bad"
        return (f"<div class='outcome'><div class='obadge {cls}'>{_t(b['badge'])}</div>"
                f"<p class='muted'>{_t(b['label'])}</p><div class='tiles'>{tiles}</div><p class='headline'>{_t(b['headline'])}</p></div>")
    if t == "toc" and b.get("columns") == 1:  # renderer 3.0
        return ("<nav class='toc notice'><b>Contents</b><ol class='one'>" +
                "".join(f"<li><a href='#{a}'>{_t(title)}</a></li>" for _, title, a in b["entries"]) + "</ol></nav>")
    if t == "title":
        return f"<h1>{_t(b['text'])}</h1><p class='subtitle'>{_t(b['subtitle'])}</p>"
    if t == "section":
        return f"<h2 id='{b['anchor']}'>{b['number']}. {_t(b['title'])}</h2>"
    if t == "sub":
        return f"<h3>{_t(b['text'])}</h3>"
    if t == "para":
        return f"<p class='{b.get('cls', '')}'>{_t(b['text'])}</p>"
    if t == "notice":
        return f"<div class='notice {b['cls']}'>{_t(b['text'])}</div>"
    if t == "kv":
        return "<div class='item info'><dl>" + "".join(f"<dt>{_t(k)}</dt><dd>{_t(v)}</dd>" for k, v in b["pairs"]) + "</dl></div>"
    if t == "table":
        head = "".join(f"<th>{_t(h)}</th>" for h in b["headers"])
        body = "".join("<tr>" + "".join(f"<td>{f'<code>{_t(c)}</code>' if i in b['code_cols'] else _t(c)}</td>" for i, c in enumerate(r))
                       + "</tr>" for r in b["rows"])
        return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    if t == "item":
        fields = "".join(f"<dt>{_t(k)}</dt><dd>{_t(v)}</dd>" for k, v in b["fields"])
        return (f"<div class='item {b['kind']}'><h4>{_t(b['heading'])}<span class='badge'>{_t(b['badge'])}</span></h4>"
                f"<dl>{fields}</dl></div>")
    if t == "bullets":
        return "<ul>" + "".join(f"<li>{_t(i)}</li>" for i in b["items"]) + "</ul>"
    if t == "toc":
        return ("<nav class='toc notice'><b>Contents</b><ol>" +
                "".join(f"<li><a href='#{a}'>{_t(title)}</a></li>" for _, title, a in b["entries"]) + "</ol></nav>")
    if t == "footer":
        return f"<footer>{_t(b['text'])}</footer>"
    raise ValueError(f"unknown block type {t!r}")


# Schema 1.1 (analyst reviews) only, so a published 1.0 pack still renders byte-identically (verify_final_pack). The
# analyst's reason keeps its line breaks.
REVIEW_CSS = """
.item.rejected{border:2px solid var(--bad);border-left-width:6px}.item.rejected .badge{color:var(--bad)}
.item.accepted{border-left:5px solid var(--ok)}.item.accepted .badge{color:var(--ok)}
.item.rejected dd,.item.accepted dd{white-space:pre-wrap}
"""


# Renderer 3.0 only (outcome panel, one-column contents, positive notice); 1.x / 2.x packs keep their exact CSS.
V3_CSS = """
.outcome{border:1px solid var(--line);border-radius:6px;padding:12px;margin:10px 0}
.obadge{display:inline-block;font-weight:700;font-size:20px;color:#fff;padding:4px 12px;border-radius:4px}
.obadge.ok{background:var(--ok)}.obadge.bad{background:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:8px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px}.tile b{display:block;font-size:20px}
.tile span{font-size:12px;color:var(--muted)}.headline{font-weight:700}.toc ol.one{columns:1}
.notice.ok{border-left:4px solid var(--ok)}
"""


def render_html(final):
    blocks = build_report(final)
    v3 = final["metadata"].get("report_renderer") == OUTCOME_RENDERER_VERSION
    css = PACK_CSS + EXTRA_CSS + (REVIEW_CSS if "analyst_reviews" in final else "") + (V3_CSS if v3 else "")
    parts, closing = [], False
    for b in blocks:
        if b["type"] == "section" and b["anchor"] == "closing-summary":
            parts.append("<section class='closing'>")
            closing = True
        if b["type"] == "footer" and closing:
            parts.append("</section>")
            closing = False
        parts.append(_block(b))
    m = final["metadata"]
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{_t(m['final_pack_id'])}</title><style>{css}</style></head><body><main>"
            + "".join(parts) + "</main></body></html>\n")
