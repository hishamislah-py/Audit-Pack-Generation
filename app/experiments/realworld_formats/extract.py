"""Experiment C - XLSX and JSON extractors into an extended intermediate representation (IR). ISOLATED EXPERIMENT:
nothing in the smartparser package imports this module.

Rendering principles (both formats):
  * every cell becomes TEXT exactly once, by a declared, versioned rendering policy; the original value, its type and
    (XLSX) number format are kept next to the text;
  * NO locale parsing, NO rounding, NO trimming, NO date guessing, NO formula evaluation, NO offset invention;
  * anything unusual becomes an explicit warning code on the cell / table / upload; codes listed in BLOCKING mark values
    that a future integration must not let through (the experiment reports them; it cannot change the pipeline);
  * nothing is dropped silently: hidden sheets, titles, repeated headers, empty arrays, non-tabular keys are reported;
  * category is NEVER derived from a file name, sheet name or JSON key.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

XLSX_EXTRACTOR = "xlsx-extractor/0.2-experiment-C1"
XLSX_POLICY = ("xlsx-strict-faithful/2 (C1: raw stored literal recorded per numeric cell; precision rule = significant "
               "digits of the shortest round-trip value of the stored double > 15; hard gate per XLSX_WARNING_POLICY)")
JSON_EXTRACTOR = "json-extractor/0.1-experiment-C"
JSON_POLICY = "json-literal-preserving/1 (flatten: dotted paths, max depth 4; arrays kept as JSON text)"
MAX_SHEET_CELLS = 2_000_000
JSON_FLATTEN_DEPTH = 4

# A future integration must stop these (the value cannot be trusted as the source's value)
BLOCKING = {"FORMULA_NO_CACHED_VALUE", "CELL_ERROR", "PRECISION_EXCEEDS_15_DIGITS",
            "DATETIME_NO_OFFSET", "MERGED_IN_DATA", "NUMERIC_CELL_IN_TEXT_LIKE_COLUMN",
            "DUPLICATE_KEYS", "NESTED_ARRAY", "DEEP_NESTING", "DATA_WITHOUT_HEADER_COLUMN", "PERCENT_FORMAT",
            "TIME_ONLY_CELL"}
INFO = {"NUMERIC_CELL", "FORMULA_CACHED_VALUE", "CURRENCY_FORMAT", "NEGATIVE_DISPLAYED_IN_PARENTHESES",
        "NUMBER_NO_DECLARED_DECIMALS", "DATE_LIKE_TEXT_NOT_ISO", "NUMBER_LIKE_TEXT_NON_CANONICAL",
        "SURROUNDING_WHITESPACE", "WHITESPACE_ONLY", "HIDDEN_ROW", "HIDDEN_COLUMN", "SHEET_PROTECTED",
        "REPEATED_HEADER_ROW", "TITLE_ROW", "SCIENTIFIC_NOTATION", "NULL_VALUE", "KEY_ABSENT", "BOOLEAN_CELL",
        # the STORED value is emitted (never the rounded display); a float artefact then fails validation visibly
        "HIDDEN_PRECISION",
        # same literal text from different JSON types is harmless; different text is judged by validation
        "MIXED_TYPES"}

# ------------------------------------------------------------------------------------------------ Experiment C1
# XLSX warning policy: EVERY code the XLSX extractor or the XLSX gate can produce is classified here; an unclassified
# code stops the run (bridge.UnclassifiedWarning) so no warning can be generated and then ignored.
#   HARD_WHEN_MAPPED  the cell feeds a canonical field (final mapping) -> the table is refused at handoff
#   INFO              reported only (the value is faithful, or the existing validation / review already decides)
# Codes derived by the GATE (they need the mapped field type) are marked as such.
XLSX_WARNING_POLICY = {
    # value unknown / not a value
    "FORMULA_NO_CACHED_VALUE": ("HARD_WHEN_MAPPED", "value unknown (never evaluated); an empty optional field would "
                                "otherwise pass validation silently"),
    "CELL_ERROR": ("HARD_WHEN_MAPPED", "an error literal (#N/A) is not a value; in a free-text field it would pass"),
    "MERGED_IN_DATA": ("HARD_WHEN_MAPPED", "only the top-left cell holds the value; the others are empty - an optional "
                       "field would silently lose data"),
    # value changed / incomplete
    "PRECISION_EXCEEDS_15_DIGITS": ("HARD_WHEN_MAPPED", "the stored double needs > 15 significant digits: beyond Excel's "
                                    "reliable precision - the source value cannot be trusted (X13)"),
    "DATETIME_NO_OFFSET": ("HARD_WHEN_MAPPED", "Excel datetimes carry no UTC offset; text derived from them is "
                           "incomplete for any field (a free-text field would accept it)"),
    "TIME_ONLY_CELL": ("HARD_WHEN_MAPPED", "no UC-042 field is a bare time; it would pass into a free-text field"),
    "PERCENT_FORMAT": ("HARD_WHEN_MAPPED", "displayed as a percentage, stored as a fraction (12% = 0.12): the meaning "
                       "of the value is ambiguous; 0.12 would pass the money pattern"),
    "UNEXPECTED_CELL_TYPE": ("HARD_WHEN_MAPPED", "a cell type the policy does not know cannot be rendered safely"),
    # gate-derived (need the mapped canonical field type)
    "NUMERIC_CELL_IN_TEXT_LIKE_COLUMN": ("HARD_WHEN_MAPPED", "GATE: a numeric cell feeding an id/str/enum/ccy field - "
                                         "leading zeros and identifier characters are not stored by Excel (X20)"),
    "BOOLEAN_CELL_IN_NON_BOOLEAN_COLUMN": ("HARD_WHEN_MAPPED", "GATE: an Excel boolean feeding a non-boolean field"),
    "MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT": ("HARD_WHEN_MAPPED", "GATE: a numeric money cell must declare exactly "
                                                   "2 fixed decimals; otherwise the rendered text depends on the value"),
    # informational (faithful value, or decided elsewhere)
    "NUMERIC_CELL": ("INFO", "marker for the gate"),
    "FORMULA_CACHED_VALUE": ("INFO", "cached result used as Excel saved it"),
    "BOOLEAN_CELL": ("INFO", "marker for the gate; 'true'/'false' matches the UC-042 boolean form"),
    "CURRENCY_FORMAT": ("INFO", "display only; the stored number is used"),
    "NEGATIVE_DISPLAYED_IN_PARENTHESES": ("INFO", "display only; the stored signed number is used"),
    "HIDDEN_PRECISION": ("INFO", "the STORED value is emitted (never the rounded display); validation judges it"),
    "NUMBER_NO_DECLARED_DECIMALS": ("INFO", "for money fields the gate applies MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT"),
    "DATE_LIKE_TEXT_NOT_ISO": ("INFO", "text kept verbatim; date fields fail validation, free text is genuine text"),
    "NUMBER_LIKE_TEXT_NON_CANONICAL": ("INFO", "text kept verbatim; money fields fail validation"),
    "SURROUNDING_WHITESPACE": ("INFO", "kept verbatim (never trimmed); enum/id/money fields fail validation"),
    "WHITESPACE_ONLY": ("INFO", "kept verbatim"),
    "HIDDEN_ROW": ("INFO", "data kept; visibility is presentation"),
    "HIDDEN_COLUMN": ("INFO", "data kept; visibility is presentation"),
    "REPEATED_HEADER_ROW": ("INFO", "page-break header rows: not data, reported with locators"),
    "EMPTY_COLUMN_EXCLUDED": ("INFO", "no header and no data: nothing to lose"),
    "DATA_WITHOUT_HEADER_COLUMN": ("INFO", "kept with an empty header: the header-count gate routes the file to review, "
                                   "where only a governed analyst decision can map or ignore it"),
    "TITLE_ROW": ("INFO", "single-cell row above the header: not data, reported with its locator"),
    # workbook-level notes (no table is produced from that content, so nothing can reach a preview from it)
    "SHEET_HIDDEN": ("INFO", "WORKBOOK NOTE: hidden sheet not extracted; reported with its cell count"),
    "SHEET_TOO_LARGE": ("INFO", "WORKBOOK NOTE: sheet not extracted (size limit); reported"),
    "SHEET_PROTECTED": ("INFO", "WORKBOOK NOTE: read normally; protection is not encryption"),
    "SHEET_EMPTY": ("INFO", "WORKBOOK NOTE: nothing to extract"),
    "NO_HEADER_ROW": ("INFO", "WORKBOOK NOTE: rows not tabulated; reported with locators"),
}


def warning_code(w: str) -> str:
    """Code of a table warning / workbook note ('TITLE_ROW: Bank!row 1 ...' -> 'TITLE_ROW')."""
    return w.split(":", 1)[0].strip()


def declared_decimals(fmt: str | None) -> int | None:
    """Fixed decimals declared by the FIRST section of an Excel number format (None: not declared, e.g. General)."""
    first = (fmt or "General").split(";")[0]
    m = re.search(r"0\.(0+)", first)
    if m:
        return len(m.group(1))
    if first != "General" and re.search(r"(^|[^.])0(?!\.)", first):
        return 0
    return None


def significant_digits(v) -> int:
    """Significant digits of the SHORTEST round-trip representation of the stored number. Writer noise
    (98765432109.99001, 2926.3299999999999) collapses to the intended value; real overflow (1.234567890123457e+16)
    does not. Information Excel discarded BEFORE storing (16 typed digits truncated to 15) cannot be detected."""
    d = Decimal(repr(v)) if isinstance(v, float) else Decimal(v)
    return 0 if d == 0 else len(d.normalize().as_tuple().digits)


@dataclass
class Upload:
    filename: str
    size: int
    sha256: str
    detected_format: str
    extractor: str = ""
    rendering_policy: str = ""


@dataclass
class Cell:
    text: str
    source: str                 # original value repr / JSON literal
    type: str                   # XLSX data type / python type, or JSON type; "absent" for a missing JSON key
    number_format: str | None = None
    locator: str = ""
    warnings: list[str] = field(default_factory=list)
    raw: str | None = None      # C1: the stored literal exactly as in the sheet XML (numeric XLSX cells only)


@dataclass
class Table:
    table_id: str                       # "Sheet!A1:H225" / "$.cash_book"
    header: list[str]
    header_cells: list[Cell]
    rows: list[list[Cell]]
    row_locators: list[str]
    column_locators: list[str]
    warnings: list[str] = field(default_factory=list)

    def text_rows(self):
        return [[c.text for c in r] for r in self.rows]

    def warning_counts(self) -> dict:
        out = {}
        for r in self.rows:
            for c in r:
                for w in c.warnings:
                    out[w] = out.get(w, 0) + 1
        for w in self.warnings:
            k = w.split(":", 1)[0]
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))

    def blocking(self) -> list[str]:
        return sorted(k for k in self.warning_counts() if k in BLOCKING)


@dataclass
class Extraction:
    upload: Upload
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # file / sheet level, reported
    refused: str | None = None                            # visible failure of the whole file

    def digest(self) -> str:
        """Deterministic digest of everything extracted (for reproducibility)."""
        doc = {"upload": asdict(self.upload), "refused": self.refused, "notes": self.notes,
               "tables": [{"id": t.table_id, "header": t.header,
                           "rows": [[{k: v for k, v in asdict(c).items() if not (k == "raw" and v is None)} for c in r]
                                    for r in t.rows],
                           "row_loc": t.row_locators, "col_loc": t.column_locators, "warnings": t.warnings}
                          for t in self.tables]}
        return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


# ================================================================================================ detection
def detect(data: bytes) -> str:
    """Content-based format detection (the file name / extension is never used)."""
    if not data:
        return "empty"
    if data[:4] == b"PK\x03\x04":
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return "zip_corrupt"
        if "[Content_Types].xml" in names and "xl/workbook.xml" in names:
            return "xlsx"
        if "[Content_Types].xml" in names and "word/document.xml" in names:
            return "docx"
        return "zip_other"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return "ole2"                                    # legacy .xls / encrypted OOXML: not supported
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf16_text"
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head in (b"{", b"["):
        return "json"
    return "other"


# ================================================================================================ XLSX
def _col(i: int) -> str:
    s, i = "", i
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


DATE_LIKE = re.compile(r"^\s*\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}")
NUM_LIKE = re.compile(r"^\s*[(\-+£$€]?\s*[\d.,]+\s*\)?\s*[£$€]?\s*$")


def _text_flags(s: str) -> list[str]:
    w = []
    if s.strip() == "" and s != "":
        w.append("WHITESPACE_ONLY")
    elif s != s.strip():
        w.append("SURROUNDING_WHITESPACE")
    if DATE_LIKE.match(s) and not re.match(r"^\d{4}-\d{2}-\d{2}", s):
        w.append("DATE_LIKE_TEXT_NOT_ISO")
    if NUM_LIKE.match(s) and not re.match(r"^-?\d+(\.\d+)?$", s.strip()):
        w.append("NUMBER_LIKE_TEXT_NON_CANONICAL")
    return w


def raw_numeric_literals(data: bytes) -> dict[str, dict[str, str]]:
    """{sheet title: {cell ref: stored literal}} for numeric cells, read from the sheet XML itself (C1: the original
    representation, not openpyxl's float)."""
    from xml.etree import ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    z = zipfile.ZipFile(io.BytesIO(data))
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("p:Relationship", ns)}
    out = {}
    for s in wbx.findall("m:sheets/m:sheet", ns):
        target = rels.get(s.get(f"{{{ns['r']}}}id"), "")
        path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        if path not in z.namelist():
            continue
        cells = {}
        for c in ET.fromstring(z.read(path)).iter(f"{{{ns['m']}}}c"):
            if c.get("t") in (None, "n"):
                v = c.find("m:v", ns)
                if v is not None and v.text is not None:
                    cells[c.get("r")] = v.text
        out[s.get("name")] = cells
    return out


def render_xlsx(cell, fcell, loc: str, raw: str | None = None) -> Cell:
    c = _render_xlsx(cell, fcell, loc)
    if raw is not None and "NUMERIC_CELL" in c.warnings:
        c.raw = raw
    return c


def _render_xlsx(cell, fcell, loc: str) -> Cell:
    v, t, fmt = cell.value, cell.data_type, cell.number_format or "General"
    formula = fcell.value if (fcell is not None and fcell.data_type == "f") else None
    if formula is not None and v is None:
        return Cell("", f"={str(formula).lstrip('=')}", "formula", fmt, loc, ["FORMULA_NO_CACHED_VALUE"])
    warn = ["FORMULA_CACHED_VALUE"] if formula is not None else []
    if v is None:
        return Cell("", "None", "empty", fmt, loc, warn)
    if t == "e":
        return Cell(str(v), str(v), "error", fmt, loc, warn + ["CELL_ERROR"])
    if isinstance(v, bool):
        return Cell("true" if v else "false", repr(v), "bool", fmt, loc, warn + ["BOOLEAN_CELL"])
    if isinstance(v, str):
        return Cell(v, v, "str", fmt, loc, warn + _text_flags(v))
    if isinstance(v, datetime):
        if not any(ch in fmt.lower() for ch in ("h", "s")) and v.time() == time(0) and v.tzinfo is None:
            return Cell(v.date().isoformat(), repr(v), "date", fmt, loc, warn)
        return Cell(v.isoformat(timespec="seconds"), repr(v), "datetime", fmt, loc,
                    warn + ([] if v.tzinfo else ["DATETIME_NO_OFFSET"]))
    if isinstance(v, date):
        return Cell(v.isoformat(), repr(v), "date", fmt, loc, warn)
    if isinstance(v, time):
        return Cell(v.isoformat(), repr(v), "time", fmt, loc, warn + ["TIME_ONLY_CELL"])
    if isinstance(v, (int, float)):
        d = Decimal(repr(v)) if isinstance(v, float) else Decimal(v)
        warn += ["NUMERIC_CELL"]
        first = fmt.split(";")[0]
        if "%" in first:
            warn.append("PERCENT_FORMAT")
        if any(sym in fmt for sym in ("£", "$", "€", "[$")):
            warn.append("CURRENCY_FORMAT")
        if ";" in fmt and v < 0 and "(" in fmt.split(";")[1]:
            warn.append("NEGATIVE_DISPLAYED_IN_PARENTHESES")
        decimals = declared_decimals(fmt)
        if decimals is not None:
            q = d.quantize(Decimal(1).scaleb(-decimals)) if decimals else d.quantize(Decimal(1))
            if q != d:
                warn.append("HIDDEN_PRECISION")   # stored value has more decimals than the declared format shows
                text = format(d, "f")
            else:
                text = format(q, "f")
        else:
            text = format(d, "f") if d != d.to_integral_value() else str(int(d))
            if d != d.to_integral_value():
                warn.append("NUMBER_NO_DECLARED_DECIMALS")
        if significant_digits(v) > 15:
            # C1: judged on the shortest round-trip value of the stored double (not on the rendered text, whose
            # declared trailing zeros are not significance, and not on the raw literal, whose writer noise is not)
            warn.append("PRECISION_EXCEEDS_15_DIGITS")
        return Cell(text, repr(v), type(v).__name__, fmt, loc, warn)
    return Cell(str(v), repr(v), type(v).__name__, fmt, loc, warn + ["UNEXPECTED_CELL_TYPE"])


def extract_xlsx(data: bytes, filename: str) -> Extraction:
    import openpyxl
    up = Upload(filename, len(data), hashlib.sha256(data).hexdigest(), detect(data), XLSX_EXTRACTOR, XLSX_POLICY)
    ex = Extraction(up)
    if up.detected_format != "xlsx":
        ex.refused = {"empty": "EMPTY_FILE", "zip_corrupt": "WORKBOOK_UNREADABLE: corrupt ZIP container",
                      "zip_other": "NOT_AN_XLSX_WORKBOOK: ZIP without xl/workbook.xml",
                      "ole2": "UNSUPPORTED: legacy .xls or encrypted workbook"}.get(
            up.detected_format, f"NOT_AN_XLSX_WORKBOOK: content is {up.detected_format}")
        return ex
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)        # cached values only, never evaluated
        wbf = openpyxl.load_workbook(io.BytesIO(data), data_only=False)      # to see which cells are formulas
    except Exception as exc:
        ex.refused = f"WORKBOOK_UNREADABLE: {type(exc).__name__}"
        return ex
    try:
        raws = raw_numeric_literals(data)
    except Exception as exc:                       # the stored representation must be readable (C1)
        ex.refused = f"WORKBOOK_UNREADABLE: sheet XML ({type(exc).__name__})"
        return ex
    for ws in wb.worksheets:
        wsf = wbf[ws.title]
        sheet_raw = raws.get(ws.title, {})
        if ws.sheet_state != "visible":
            n = sum(1 for r in ws.iter_rows(values_only=True) for v in r if v not in (None, ""))
            ex.notes.append(f"SHEET_HIDDEN: {ws.title!r} ({ws.sheet_state}, {n} non-empty cells) not extracted")
            continue
        if ws.max_row * ws.max_column > MAX_SHEET_CELLS:
            ex.notes.append(f"SHEET_TOO_LARGE: {ws.title!r} dimension {ws.dimensions} "
                            f"({ws.max_row}x{ws.max_column}) exceeds {MAX_SHEET_CELLS} cells - not extracted")
            continue
        if ws.protection.sheet:
            ex.notes.append(f"SHEET_PROTECTED: {ws.title!r} (read normally; protection is not encryption)")
        hidden_rows = {r for r, d in ws.row_dimensions.items() if d.hidden}
        hidden_cols = {c for c, d in ws.column_dimensions.items() if d.hidden}
        merged = list(ws.merged_cells.ranges)
        grid = {}
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
            for c in row:
                if c.value is None and not (wsf[c.coordinate].data_type == "f"):
                    continue
                grid[(c.row, c.column)] = render_xlsx(c, wsf[c.coordinate], f"{ws.title}!{c.coordinate}",
                                                      sheet_raw.get(c.coordinate))
        if not grid:
            ex.notes.append(f"SHEET_EMPTY: {ws.title!r}")
            continue
        nonblank = lambda r: any(grid.get((r, j)) is not None and grid[(r, j)].text.strip() != ""  # noqa: E731
                                 or (grid.get((r, j)) is not None and grid[(r, j)].warnings
                                     and "FORMULA_NO_CACHED_VALUE" in grid[(r, j)].warnings)
                                 for j in range(1, ws.max_column + 1))
        rows_nb = [r for r in range(1, ws.max_row + 1) if nonblank(r)]
        blocks, cur = [], []
        for r in rows_nb:                                  # blocks of consecutive non-blank rows
            if cur and r != cur[-1] + 1:
                blocks.append(cur)
                cur = []
            cur.append(r)
        if cur:
            blocks.append(cur)
        for bi, block in enumerate(blocks):
            twarn = []
            single = [j for j in range(1, ws.max_column + 1) if grid.get((block[0], j)) and grid[(block[0], j)].text.strip()]
            if len(block) == 1 and len(single) == 1:
                ex.notes.append(f"TITLE_ROW: {ws.title}!row {block[0]} "
                                f"({grid[(block[0], single[0])].text[:40]!r}; not data, reported)")
                continue
            cols_with = lambda r: [j for j in range(1, ws.max_column + 1) if grid.get((r, j)) and grid[(r, j)].text.strip()]  # noqa: E731
            while len(block) > 1 and len(cols_with(block[0])) == 1:
                twarn.append(f"TITLE_ROW: {ws.title}!row {block[0]} ({grid[(block[0], cols_with(block[0])[0])].text[:40]!r})")
                block = block[1:]
            hdr_r = block[0]
            hdr_cols = cols_with(hdr_r)
            if len(hdr_cols) < 2 or any(grid[(hdr_r, j)].type != "str" for j in hdr_cols):
                ex.notes.append(f"NO_HEADER_ROW: {ws.title}!rows {block[0]}-{block[-1]} not tabulated "
                                f"({len(block)} non-blank row(s) reported)")
                continue
            data_rows = block[1:]
            span = range(min(hdr_cols), max(max(hdr_cols), max((max(cols_with(r) or [0]) for r in data_rows), default=0)) + 1)
            cols = []
            for j in span:
                has_hdr = j in hdr_cols
                has_data = any(grid.get((r, j)) and grid[(r, j)].text.strip() for r in data_rows)
                if has_hdr:
                    cols.append(j)
                elif has_data:
                    cols.append(j)
                    twarn.append(f"DATA_WITHOUT_HEADER_COLUMN: {ws.title}!{_col(j)} has data but no header (kept, "
                                 "header empty)")
                else:
                    twarn.append(f"EMPTY_COLUMN_EXCLUDED: {ws.title}!{_col(j)} (no header, no data)")
            header_cells = [grid.get((hdr_r, j)) or Cell("", "None", "empty", None, f"{ws.title}!{_col(j)}{hdr_r}")
                            for j in cols]
            header = [c.text for c in header_cells]
            rows, locs = [], []
            for r in data_rows:
                cells = [grid.get((r, j)) or Cell("", "None", "empty", None, f"{ws.title}!{_col(j)}{r}") for j in cols]
                if [c.text for c in cells] == header:
                    twarn.append(f"REPEATED_HEADER_ROW: {ws.title}!row {r} (not data; reported)")
                    continue
                for c, j in zip(cells, cols):
                    if r in hidden_rows:
                        c.warnings.append("HIDDEN_ROW")
                    if _col(j) in hidden_cols:
                        c.warnings.append("HIDDEN_COLUMN")
                    for m in merged:
                        if m.min_row <= r <= m.max_row and m.min_col <= j <= m.max_col:
                            c.warnings.append("MERGED_IN_DATA")
                rows.append(cells)
                locs.append(f"{ws.title}!row {r}")
            first, last = f"{_col(cols[0])}{hdr_r}", f"{_col(cols[-1])}{data_rows[-1] if data_rows else hdr_r}"
            ex.tables.append(Table(f"{ws.title}!{first}:{last}", header, header_cells, rows, locs,
                                   [f"{ws.title}!{_col(j)}" for j in cols], twarn))
    return ex


# ================================================================================================ JSON
class JNum(str):
    """A JSON number kept as its exact source literal."""
    kind = "number"


class _Dup(Exception):
    pass


def _pairs(pairs):
    keys = [k for k, _ in pairs]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        raise _Dup(dups)
    return dict(pairs)


def _jtype(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, JNum):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _dump_raw(v) -> str:
    """JSON text of a nested value with number LITERALS written exactly as in the source (JNum is a str subclass,
    so json.dumps would turn 1 into "1" - a silent type change)."""
    if isinstance(v, JNum):
        return str(v)
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(k, ensure_ascii=False)}: {_dump_raw(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_dump_raw(x) for x in v) + "]"
    return json.dumps(v, ensure_ascii=False)


def _reject_constant(name):
    raise ValueError(f"NON_STANDARD_NUMBER: {name}")


def _flatten(obj, prefix, depth, out, warn):
    for k, v in obj.items():
        if "." in k:
            warn.append(f"KEY_CONTAINS_DOT: {prefix + k!r} (ambiguous with the dotted flattening convention)")
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v and depth < JSON_FLATTEN_DEPTH:
            _flatten(v, key + ".", depth + 1, out, warn)
        elif isinstance(v, dict) and v:
            out[key] = ("object", _dump_raw(v), ["DEEP_NESTING"])
        elif isinstance(v, dict):
            out[key] = ("object", "{}", ["EMPTY_OBJECT"])
        elif isinstance(v, list):
            out[key] = ("array", _dump_raw(v), ["NESTED_ARRAY"])
        else:
            out[key] = (_jtype(v), v, [])
    return out


def extract_json(data: bytes, filename: str) -> Extraction:
    up = Upload(filename, len(data), hashlib.sha256(data).hexdigest(), detect(data), JSON_EXTRACTOR, JSON_POLICY)
    ex = Extraction(up)
    if up.detected_format != "json":
        ex.refused = {"empty": "EMPTY_FILE", "utf16_text": "INVALID_ENCODING: UTF-16 (UTF-8 required)"}.get(
            up.detected_format, f"NOT_JSON: content is {up.detected_format}")
        return ex
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        ex.refused = f"INVALID_ENCODING: not UTF-8 at byte {exc.start}"
        return ex
    if data.startswith(b"\xef\xbb\xbf"):
        ex.notes.append("UTF8_BOM: present (accepted)")
    try:
        doc = json.loads(text, parse_float=JNum, parse_int=JNum, parse_constant=_reject_constant,
                         object_pairs_hook=_pairs)
    except _Dup as d:
        ex.refused = f"DUPLICATE_KEYS: {d.args[0]} (the standard parser would silently keep the last value)"
        return ex
    except RecursionError:
        ex.refused = "NESTING_TOO_DEEP: exceeds the parser's recursion limit"
        return ex
    except ValueError as exc:
        msg = str(exc)
        ex.refused = msg if msg.startswith("NON_STANDARD_NUMBER") else f"JSON_SYNTAX: {msg}"
        return ex
    arrays = []

    def find(node, path, depth):
        if isinstance(node, list):
            if not node:
                ex.notes.append(f"EMPTY_ARRAY: {path}")
            elif all(isinstance(x, dict) for x in node):
                arrays.append((path, node))
            else:
                bad = [i for i, x in enumerate(node) if not isinstance(x, dict)]
                if any(isinstance(x, dict) for x in node):
                    arrays.append((path, node))
                    ex.notes.append(f"NON_OBJECT_RECORDS: {path} entries {bad[:10]} are not objects (not tabulated, "
                                    "reported)")
                else:
                    ex.notes.append(f"NOT_A_RECORD_ARRAY: {path} (array of {_jtype(node[0])}; reported)")
        elif isinstance(node, dict):
            if not node:
                ex.notes.append(f"EMPTY_OBJECT: {path}")
            for k, v in node.items():
                if isinstance(v, (list, dict)) and depth < 2:
                    find(v, f"{path}.{k}", depth + 1)
                else:
                    ex.notes.append(f"NON_TABULAR_VALUE: {path}.{k} ({_jtype(v)}; reported, not tabulated)")
    find(doc, "$", 0)
    if not arrays:
        ex.refused = "NO_RECORD_ARRAYS: no array of objects found" + (f" ({'; '.join(ex.notes)})" if ex.notes else "")
        return ex
    for path, recs in arrays:
        twarn = []
        flat = []
        idx = []
        for i, r in enumerate(recs):
            if isinstance(r, dict):
                flat.append(_flatten(r, "", 1, {}, twarn))
                idx.append(i)
        header = []
        for r in flat:
            for k in r:
                if k not in header:
                    header.append(k)
        types = {k: sorted({r[k][0] for r in flat if k in r and r[k][0] != "null"}) for k in header}
        mixed = {k: t for k, t in types.items() if len(t) > 1}
        for k, t in mixed.items():
            twarn.append(f"MIXED_TYPES: {k!r} has {t}")
        rows = []
        for i, r in zip(idx, flat):
            cells = []
            for k in header:
                loc = f"{path}[{i}].{k}"
                if k not in r:
                    cells.append(Cell("", "<absent>", "absent", None, loc, ["KEY_ABSENT"]))
                    continue
                jt, v, w = r[k]
                w = list(w)
                if k in mixed:
                    w.append("MIXED_TYPES")
                if jt == "null":
                    cells.append(Cell("", "null", "null", None, loc, w + ["NULL_VALUE"]))
                elif jt == "bool":
                    cells.append(Cell("true" if v else "false", json.dumps(v), "bool", None, loc, w))
                elif jt == "number":
                    if re.search(r"[eE]", v):
                        w.append("SCIENTIFIC_NOTATION")
                    cells.append(Cell(str(v), str(v), "number", None, loc, w))
                elif jt == "string":
                    cells.append(Cell(v, json.dumps(v, ensure_ascii=False), "string", None, loc, w + _text_flags(v)))
                else:
                    cells.append(Cell(v, v, jt, None, loc, w))
            rows.append(cells)
        hdr_cells = [Cell(k, k, "key", None, f"{path}[*].{k}") for k in header]
        ex.tables.append(Table(path, header, hdr_cells, rows, [f"{path}[{i}]" for i in idx],
                               [f"{path}[*].{k}" for k in header], twarn))
    return ex


def extract(data: bytes, filename: str) -> Extraction:
    """Dispatch by CONTENT (never by extension)."""
    fmt = detect(data)
    if fmt in ("xlsx", "zip_corrupt", "zip_other", "ole2", "docx"):
        return extract_xlsx(data, filename)
    return extract_json(data, filename)
