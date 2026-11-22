"""Experiment B - format extractors into a COMMON INTERMEDIATE REPRESENTATION (IR). Isolated: nothing in the smartparser
package imports this module, and nothing here maps, validates or decides a category.

IR (two shapes, mirroring the two existing Smart Parser routes):
  ExtractedTable     header + rows of cell TEXT + a source locator per data row and per column -> the CSV route
  ExtractedDocument  plain text (+ section headings, key-value lines) + locators            -> the PDF/label route

Rules every extractor follows:
  * cell values become TEXT exactly once, by a declared rendering policy (no silent coercion);
  * nothing is dropped silently: skipped empty rows/columns, merged cells, nested arrays, unknown structures are all
    reported as `notes` / `warnings`;
  * no category is inferred here (classification stays in Smart Parser), no column is renamed.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal


@dataclass
class ExtractedTable:
    source_format: str
    locator: str                       # e.g. "sheet:CashBook", "json:$.records", "docx:table[0]", "md:table[0]"
    header: list[str]
    rows: list[list[str]]
    row_locators: list[str]            # one per data row (e.g. "CashBook!row 5", "$.records[3]", "line 12")
    column_locators: list[str]         # one per column (e.g. "CashBook!col C", "$.records[*].amount")
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    source_format: str
    locator: str
    text: str
    headings: list[str] = field(default_factory=list)
    key_values: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Extraction:
    source_format: str
    tables: list[ExtractedTable] = field(default_factory=list)
    documents: list[ExtractedDocument] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


KV = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ()/'-]{1,60}?)\s*:\s*(.+?)\s*$")


# ================================================================================================ XLSX
def _col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def render_cell(cell, policy: str) -> tuple[str, str | None]:
    """(text, warning). policy 'naive' = str(value) (what a quick implementation would do); 'format_aware' = honour the
    cell's number format for numbers and ISO 8601 for dates - the minimum needed to keep UC-042 money/date text."""
    v = cell.value
    if v is None:
        return "", None
    if isinstance(v, str):
        return v, None
    if isinstance(v, bool):
        return ("true" if v else "false"), None
    if policy == "naive":
        return str(v), None
    if isinstance(v, datetime):
        fmt = (cell.number_format or "").lower()
        if not any(t in fmt for t in ("h", "s")) and v.time() == time(0):
            return v.date().isoformat(), None        # Excel has no date type: a date-only number format -> date
        if v.tzinfo is None:
            return v.isoformat(timespec="seconds"), "datetime cell without UTC offset (Excel stores no time zone)"
        return v.isoformat(timespec="seconds"), None
    if isinstance(v, date):
        return v.isoformat(), None
    if isinstance(v, time):
        return v.isoformat(), None
    if isinstance(v, (int, float)):
        fmt = cell.number_format or "General"
        m = re.search(r"0\.(0+)", fmt)
        if m:                                        # fixed decimals declared by the cell format, e.g. 0.00 / #,##0.00
            q = Decimal(1).scaleb(-len(m.group(1)))
            return str(Decimal(repr(v)).quantize(q)), None
        if isinstance(v, float) and not v.is_integer():
            return repr(v), "number cell without a fixed-decimal format (rendered with repr)"
        return str(int(v)) if isinstance(v, float) else str(v), None
    return str(v), f"unexpected cell type {type(v).__name__}"


def extract_xlsx(data: bytes, policy: str = "format_aware") -> Extraction:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)    # cached values only: formulas are never evaluated
    out = Extraction("xlsx")
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            out.notes.append(f"sheet {ws.title!r} is {ws.sheet_state}: not extracted (reported)")
            continue
        grid, warn = [], []
        for r in ws.iter_rows():
            vals = []
            for c in r:
                text, w = render_cell(c, policy)
                if w:
                    warn.append(f"{ws.title}!{c.coordinate}: {w}")
                vals.append(text)
            grid.append(vals)
        merged = [str(m) for m in ws.merged_cells.ranges]
        nonempty = [i for i, row in enumerate(grid) if any(x.strip() for x in row)]
        if not nonempty:
            out.notes.append(f"sheet {ws.title!r} is empty")
            continue
        # header row = first row whose non-empty cells are all text and >= 2 cells (title rows above are reported)
        hdr_i = next((i for i in nonempty if sum(1 for x in grid[i] if x.strip()) >= 2), nonempty[0])
        skipped_above = [i + 1 for i in nonempty if i < hdr_i]
        if skipped_above:
            warn.append(f"rows {skipped_above} above the header (titles/notes) not treated as data")
        cols = [j for j, x in enumerate(grid[hdr_i]) if x.strip()]
        empty_cols = [j for j in range(len(grid[hdr_i])) if j not in cols and any(
            grid[i][j].strip() for i in range(hdr_i + 1, len(grid)) if j < len(grid[i]))]
        if empty_cols:
            warn.append(f"columns {[_col_letter(j) for j in empty_cols]} have data but no header: NOT dropped "
                        "silently - reported (the table cannot be mapped until resolved)")
        for m in merged:
            warn.append(f"merged cell range {ws.title}!{m}: value only in its top-left cell")
        rows, locs, blank = [], [], []
        for i in range(hdr_i + 1, len(grid)):
            vals = [grid[i][j] if j < len(grid[i]) else "" for j in cols]
            if not any(x.strip() for x in vals):
                blank.append(i + 1)
                continue
            rows.append(vals)
            locs.append(f"{ws.title}!row {i + 1}")
        if blank:
            warn.append(f"{len(blank)} empty row(s) skipped (reported): {blank[:10]}")
        out.tables.append(ExtractedTable("xlsx", f"sheet:{ws.title}", [grid[hdr_i][j] for j in cols], rows, locs,
                                         [f"{ws.title}!col {_col_letter(j)}" for j in cols], warn))
    return out


# ================================================================================================ JSON
def _flatten(obj, prefix="", out=None, warn=None):
    out = {} if out is None else out
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            _flatten(v, key, out, warn)
        elif isinstance(v, list):
            out[key] = json.dumps(v, ensure_ascii=False)
            if warn is not None:
                warn.append(f"array at {key}: kept as JSON text (not exploded into rows)")
        else:
            out[key] = v
    return out


def _json_text(v) -> str:
    if v is None:
        return ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)                 # numbers arrive as their LITERAL text (parse_float / parse_int = str)


def extract_json(data: bytes) -> Extraction:
    doc = json.loads(data.decode("utf-8"), parse_float=str, parse_int=str)   # number literals kept verbatim
    out = Extraction("json")
    arrays = []
    if isinstance(doc, list):
        arrays = [("$", doc)]
    elif isinstance(doc, dict):
        arrays = [(f"$.{k}", v) for k, v in doc.items() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
        other = [k for k, v in doc.items() if f"$.{k}" not in {a for a, _ in arrays}]
        if other:
            out.notes.append(f"top-level keys that are not record arrays (reported, not tabulated): {other}")
    for path, recs in arrays:
        if not all(isinstance(r, dict) for r in recs):
            out.notes.append(f"{path} is not an array of objects: not tabulated")
            continue
        warn = []
        flat = [_flatten(r, warn=warn) for r in recs]
        header = []
        for r in flat:                                   # union of keys, first-seen order
            for k in r:
                if k not in header:
                    header.append(k)
        missing = {k: sum(1 for r in flat if k not in r) for k in header}
        for k, n in missing.items():
            if n:
                warn.append(f"key {k!r} absent in {n} of {len(flat)} record(s): empty cell (reported)")
        rows = [[_json_text(r.get(k)) for k in header] for r in flat]
        out.tables.append(ExtractedTable("json", f"json:{path}", header, rows,
                                         [f"{path}[{i}]" for i in range(len(rows))],
                                         [f"{path}[*].{k}" for k in header], warn))
    return out


# ================================================================================================ DOCX
def extract_docx(data: bytes) -> Extraction:
    import docx
    d = docx.Document(io.BytesIO(data))
    out = Extraction("docx")
    lines, headings, kv = [], [], {}
    for i, p in enumerate(d.paragraphs):
        t = p.text.strip()
        if not t:
            continue
        lines.append(t)
        if p.style is not None and p.style.name.lower().startswith("heading"):
            headings.append(t)
        m = KV.match(t)
        if m:
            kv.setdefault(m.group(1).strip(), m.group(2).strip())
    if lines:
        out.documents.append(ExtractedDocument("docx", "docx:body", "\n".join(lines), headings, kv))
    for ti, t in enumerate(d.tables):
        warn = []
        grid = []
        for r in t.rows:
            cells, seen = [], []
            for c in r.cells:
                if any(c._tc is s for s in seen):        # python-docx repeats a horizontally merged cell
                    warn.append(f"table[{ti}]: merged cell repeated across columns (value duplicated by the layout)")
                seen.append(c._tc)
                cells.append(c.text.strip())
                if "\n" in c.text:
                    warn.append(f"table[{ti}]: multi-line cell (line breaks kept)")
            grid.append(cells)
        if len(grid) < 2:
            out.notes.append(f"table[{ti}] has no data rows")
            continue
        out.tables.append(ExtractedTable("docx", f"docx:table[{ti}]", grid[0], grid[1:],
                                         [f"table[{ti}] row {i + 1}" for i in range(1, len(grid))],
                                         [f"table[{ti}] col {j + 1}" for j in range(len(grid[0]))], sorted(set(warn))))
    return out


# ================================================================================================ TXT / Markdown
PIPE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _split_pipe(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def extract_text(data: bytes, fmt: str = "md") -> Extraction:
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    out = Extraction(fmt)
    i, used = 0, set()
    ti = 0
    while i < len(lines) - 1:
        if "|" in lines[i] and PIPE_SEP.match(lines[i + 1] or ""):
            header = _split_pipe(lines[i])
            rows, locs, warn = [], [], []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                cells = _split_pipe(lines[j])
                if len(cells) != len(header):
                    warn.append(f"line {j + 1}: {len(cells)} cells, header has {len(header)} (row kept as-is, reported)")
                    cells = (cells + [""] * len(header))[:len(header)]
                rows.append(cells)
                locs.append(f"line {j + 1}")
                j += 1
            used.update(range(i, j))
            out.tables.append(ExtractedTable(fmt, f"{fmt}:table[{ti}]", header, rows, locs,
                                             [f"table[{ti}] col {k + 1}" for k in range(len(header))], warn))
            ti += 1
            i = j
            continue
        i += 1
    rest = [lines[k] for k in range(len(lines)) if k not in used]
    headings = [l.lstrip("#").strip() for l in rest if l.startswith("#")]
    kv = {}
    body = []
    for l in rest:
        s = l.lstrip("#").strip().lstrip("-*").strip()
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)                     # **Label:** value -> Label: value
        if s:
            body.append(s)
        m = KV.match(s)
        if m:
            kv.setdefault(m.group(1).strip(), m.group(2).strip())
    if any(x.strip() for x in body):
        out.documents.append(ExtractedDocument(fmt, f"{fmt}:body", "\n".join(body), headings, kv))
    return out


def extract(data: bytes, fmt: str, **kw) -> Extraction:
    return {"xlsx": extract_xlsx, "json": extract_json, "docx": extract_docx}.get(
        fmt, lambda d, **_: extract_text(d, fmt))(data, **kw)
