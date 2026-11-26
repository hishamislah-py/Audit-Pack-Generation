"""Experiment C - scenario generator (synthetic, from the canonical UC-042 fixture tables; known truth).

Each scenario: id, format, description, input bytes (+ file name, which is NEVER used to classify), and per expected
table: the truth (category, canonical rows in canonical order, source header -> canonical field map, optional approved
aliases) and the EXPECTED SAFE OUTCOME:
    EXACT                    eligible, preview byte-identical to the truth
    BLOCKED                  not eligible (validation / handoff) - the value problem is caught, not corrected
    REVIEW->EXACT            human review (simulated analyst) -> eligible and exact
    REVIEW->HELD_OR_BLOCKED  human review cannot make it valid
    RESUBMISSION             fewer columns than fields
    SILENT_DIFFERENCE        a FINDING: the existing pipeline accepts a changed value (expected = documented risk)
Adversarial scenarios expect a visible refusal code or note instead.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
SEP = HERE / "tests" / "fixtures" / "uc042_canonical" / "PER-2026-09_set_01_clean_baseline"
sys.path.insert(0, str(HERE))
from smartparser.schemas import SchemaRegistry  # noqa: E402

REG = SchemaRegistry.from_directory()


def _files():
    with open(SEP / "manifest.csv", encoding="utf-8", newline="") as f:
        out = {}
        for r in csv.DictReader(f):
            out.setdefault(r["file_id"], SEP / r["relative_path"])
    return out


FILES = _files()


def canon(fid):
    return [list(r) for r in csv.reader(io.StringIO(FILES[fid].read_bytes().decode("utf-8")))]


def types(fid):
    return {f.name: f.source_type for f in REG.get(fid).fields}


def ident(fid, rows=None):
    return {c: c for c in (rows or canon(fid))[0]}


def T(fid, rows=None, mp=None, outcome="EXACT", aliases=()):
    rows = rows or canon(fid)
    return {"fid": fid, "rows": rows, "map": mp or ident(fid, rows), "outcome": outcome, "aliases": list(aliases)}


# ================================================================================================ XLSX writing
def workbook(sheets) -> bytes:
    """sheets: [{name, blocks: [(r0, c0, header, rows, typer)], state, protect, hidden_rows, hidden_cols, merge,
    extra_cells, formulas: {coord: formula}}]"""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sh in sheets:
        ws = wb.create_sheet(sh["name"])
        for r0, c0, header, rows, typer in sh.get("blocks", []):
            for j, h in enumerate(header):
                ws.cell(r0, c0 + j, h)
            for i, row in enumerate(rows):
                for j, v in enumerate(row):
                    cell = ws.cell(r0 + 1 + i, c0 + j)
                    (typer or text_typer)(header[j], v, cell)
        for coord, v in sh.get("extra_cells", {}).items():
            ws[coord] = v
        for coord, (formula, fmt) in sh.get("formulas", {}).items():
            ws[coord] = formula
            ws[coord].number_format = fmt
        for rng in sh.get("merge", []):
            ws.merge_cells(rng)
        for r in sh.get("hidden_rows", []):
            ws.row_dimensions[r].hidden = True
        for c in sh.get("hidden_cols", []):
            ws.column_dimensions[c].hidden = True
        if sh.get("protect"):
            ws.protection.sheet = True
        if sh.get("state"):
            ws.sheet_state = sh["state"]
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def text_typer(h, v, cell):
    cell.value = v


def typed(fid, money_fmt="#,##0.00", date_mode="date", ts_mode="text", id_numeric=(), date_fmt="yyyy-mm-dd"):
    t = types(fid)

    def f(h, v, cell):
        st = t.get(h)
        if v == "":
            cell.value = None
        elif st in ("amount", "signed") and money_fmt is not None:
            cell.value, cell.number_format = float(v), money_fmt
        elif st == "date" and date_mode == "date":
            cell.value, cell.number_format = date.fromisoformat(v), date_fmt
        elif st == "ts" and ts_mode == "datetime":
            cell.value, cell.number_format = datetime.fromisoformat(v).replace(tzinfo=None), "yyyy-mm-dd hh:mm:ss"
        elif st == "int":
            cell.value = int(v)
        elif h in id_numeric and re.fullmatch(r"\d+", v):
            cell.value = int(v)                   # what Excel does when a numeric-looking ID is typed in
        else:
            cell.value = v
    return f


def put_cached_values(data: bytes, cached: dict[str, str]) -> bytes:
    """Write cached results for formula cells (as Excel would after calculating). openpyxl cannot store them."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            b = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                s = b.decode("utf-8")
                for coord, val in cached.items():
                    s = re.sub(rf'(<c r="{coord}"[^>]*>)(<f>[^<]*</f>)(<v\s*/>|<v></v>)?', rf"\1\2<v>{val}</v>", s)
                b = s.encode("utf-8")
            zout.writestr(item, b)
    return out.getvalue()


def set_raw_values(data: bytes, values: dict[str, str]) -> bytes:
    """Replace the stored <v> of numeric cells with an exact raw literal (as Excel can store 17 digits)."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            b = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                s = b.decode("utf-8")
                for coord, raw in values.items():
                    s, n = re.subn(rf'(<c r="{coord}"[^>]*>)<v>[^<]*</v>', lambda m: m.group(1) + f"<v>{raw}</v>", s)
                    assert n == 1, coord
                b = s.encode("utf-8")
            zout.writestr(item, b)
    return out.getvalue()


def mutate(rows, field, fn):
    rows = [list(r) for r in rows]
    j = rows[0].index(field)
    for i in range(1, len(rows)):
        rows[i][j] = fn(i, rows[i][j])
    return rows


def blk(rows, typer=None, r0=1, c0=1, header=None):
    return (r0, c0, header or rows[0], rows[1:], typer)


# ================================================================================================ XLSX scenarios
def xlsx_scenarios():
    S = []
    c10, c03, c07, c08, c11 = canon("IN-10"), canon("IN-03"), canon("IN-07"), canon("IN-08"), canon("IN-11")
    add = lambda sid, desc, data, tables, **kw: S.append(  # noqa: E731
        dict(id=sid, fmt="xlsx", desc=desc, data=data, file=f"{sid}.xlsx", tables=tables, **kw))
    # ---- A1 structures
    add("X01", "one sheet, one table (IN-10), canonical headers, text cells",
        workbook([{"name": "Sheet1", "blocks": [blk(c10)]}]), {"Sheet1#0": T("IN-10")})
    add("X02", "4 sheets named after categories (IN-10, IN-03, IN-07, IN-11)",
        workbook([{"name": n, "blocks": [blk(canon(n))]} for n in ("IN-10", "IN-03", "IN-07", "IN-11")]),
        {f"{n}#0": T(n) for n in ("IN-10", "IN-03", "IN-07", "IN-11")})
    add("X03", "MISLEADING sheet names: sheet 'IN-03' holds IN-10 data, sheet 'Bank' holds IN-07",
        workbook([{"name": "IN-03", "blocks": [blk(c10)]}, {"name": "Bank", "blocks": [blk(c07)]}]),
        {"IN-03#0": T("IN-10"), "Bank#0": T("IN-07")})
    add("X04", "blank sheet + HIDDEN sheet with IN-03 data + extra 'Notes' sheet + IN-10 sheet",
        workbook([{"name": "Blank"}, {"name": "Old", "blocks": [blk(c03)], "state": "hidden"},
                  {"name": "Notes", "extra_cells": {"A1": "Prepared by", "B1": "Ops", "A2": "Checked", "B2": "yes"}},
                  {"name": "Data", "blocks": [blk(c10)]}]),
        {"Data#0": T("IN-10"), "Notes#0": None}, notes=["SHEET_HIDDEN", "SHEET_EMPTY"])
    add("X05", "TWO tables in one sheet (IN-07 at A1, IN-08 below after 3 blank rows)",
        workbook([{"name": "Bank", "blocks": [blk(c07), blk(c08, r0=len(c07) + 4)]}]),
        {"Bank#0": T("IN-07"), "Bank#1": T("IN-08")})
    rep = [c10[0]] + [r for i, r in enumerate(c10[1:]) for r in ([r, c10[0]] if (i + 1) % 50 == 0 else [r])]
    add("X06", "title row + blank rows before/after + header REPEATED every 50 rows (page-break style)",
        workbook([{"name": "CashBook", "extra_cells": {"A1": "Safeguarding cash book - September 2026"},
                   "blocks": [blk(rep, r0=3)]}]),
        {"CashBook#0": T("IN-10")}, warn=["REPEATED_HEADER_ROW"], notes=["TITLE_ROW"])
    add("X07", "MERGED cells in data (IN-07 currency rows 2-3 merged)",
        workbook([{"name": "Bank", "blocks": [blk(c07)], "merge": ["D2:D3"]}]),
        {"Bank#0": T("IN-07", outcome="BLOCKED")}, warn=["MERGED_IN_DATA"])
    extra = [c10[0][:4] + [""] + c10[0][4:] + ["comment"]] + [r[:4] + [""] + r[4:] + ["n/a"] for r in c10[1:]]
    add("X08", "EMPTY column inside the table + an EXTRA 'comment' column (9 vs 8)",
        workbook([{"name": "CashBook", "blocks": [blk(extra)]}]),
        {"CashBook#0": T("IN-10", outcome="REVIEW->EXACT")}, warn=["EMPTY_COLUMN_EXCLUDED"])
    miss = [[v for j, v in enumerate(r) if j != c10[0].index("currency")] for r in c10]
    add("X09", "MISSING column (IN-10 without currency, 7 vs 8)",
        workbook([{"name": "CashBook", "blocks": [blk(miss)]}]), {"CashBook#0": T("IN-10", outcome="RESUBMISSION")})
    # ---- A2 financial values
    add("X10", "money as NUMBERS with #,##0.00; dates/timestamps as text (IN-07, IN-03, IN-10)",
        workbook([{"name": n, "blocks": [blk(canon(n), typed(n, date_mode="text"))]} for n in ("IN-07", "IN-03", "IN-10")]),
        {f"{n}#0": T(n) for n in ("IN-07", "IN-03", "IN-10")})
    add("X11", "money as numbers with GENERAL format (250000 / 2926.33)",
        workbook([{"name": "Bank", "blocks": [blk(c07, typed("IN-07", money_fmt="General", date_mode="text"))]}]),
        {"Bank#0": T("IN-07", outcome="BLOCKED")}, warn=["NUMBER_NO_DECLARED_DECIMALS"])
    cents = mutate(c07, "balance_amount", lambda i, v: str(Decimal(v) + Decimal("0.37")) if i <= 3 else v)
    add("X12", "money with ZERO-decimal format '#,##0': cents hidden by the display; whole amounts render without "
               "decimals (stored values emitted, never the display; '250000' fails the money pattern)",
        workbook([{"name": "Bank", "blocks": [blk(cents, typed("IN-07", money_fmt="#,##0", date_mode="text"))]}]),
        {"Bank#0": T("IN-07", cents, outcome="BLOCKED")}, warn=["HIDDEN_PRECISION"])
    art = mutate(c07, "balance_amount", lambda i, v: "0.30" if i == 1 else v)
    wb_art = workbook([{"name": "Bank", "blocks": [blk(art, typed("IN-07", date_mode="text"))]}])
    acol = chr(65 + art[0].index("balance_amount"))
    # openpyxl rounds floats when writing, so the 17-digit artefact Excel itself can store is written into the XML
    add("X12b", "FLOAT ARTEFACT stored in the sheet XML (0.30000000000000004), displayed 0.30 by #,##0.00",
        set_raw_values(wb_art, {f"{acol}2": "0.30000000000000004"}),
        {"Bank#0": T("IN-07", art, outcome="BLOCKED")}, warn=["HIDDEN_PRECISION"])
    big = mutate(c07, "balance_amount", lambda i, v: {1: "98765432109.99", 2: "12345678901234567.89"}.get(i, v))
    add("X13", "LARGE values: 98765432109.99 (13 digits, safe) and 12345678901234567.89 (beyond Excel's 15 digits)",
        workbook([{"name": "Bank", "blocks": [blk(big, typed("IN-07", date_mode="text"))]}]),
        {"Bank#0": T("IN-07", big, outcome="SILENT_DIFFERENCE")}, warn=["PRECISION_EXCEEDS_15_DIGITS"])
    neg = mutate(c03, "balance", lambda i, v: f"-{v}" if i % 9 == 0 and not v.startswith("-") and v != "0.00" else v)
    add("X14", "NEGATIVE signed amounts as numbers with parentheses display format #,##0.00;(#,##0.00)",
        workbook([{"name": "Balances", "blocks": [blk(neg, typed("IN-03", money_fmt="#,##0.00;(#,##0.00)", date_mode="text"))]}]),
        {"Balances#0": T("IN-03", neg)}, warn=["NEGATIVE_DISPLAYED_IN_PARENTHESES"])
    txt = {1: "(12.50)", 2: "£1,234.56", 3: "1.234,56", 4: "1,234.56", 5: "-0012.50"}
    tv = mutate(c03, "balance", lambda i, v: {1: "-12.50", 2: "1234.56", 3: "1234.56", 4: "1234.56", 5: "-12.50"}.get(i, v))
    src = mutate(c03, "balance", lambda i, v: txt.get(i, v))
    add("X15", "TEXT money: '(12.50)', '£1,234.56', '1.234,56', '1,234.56', '-0012.50' (never converted)",
        workbook([{"name": "Balances", "blocks": [blk(src)]}]), {"Balances#0": T("IN-03", tv, outcome="BLOCKED")},
        warn=["NUMBER_LIKE_TEXT_NON_CANONICAL"])
    add("X16", "money as numbers with a CURRENCY number format £#,##0.00",
        workbook([{"name": "Bank", "blocks": [blk(c07, typed("IN-07", money_fmt="£#,##0.00", date_mode="text"))]}]),
        {"Bank#0": T("IN-07")}, warn=["CURRENCY_FORMAT"])
    zero = mutate(c07, "balance_amount", lambda i, v: "0.00" if i <= 2 else v)
    add("X17", "ZERO amounts (0 with 0.00 format)",
        workbook([{"name": "Bank", "blocks": [blk(zero, typed("IN-07", date_mode="text"))]}]), {"Bank#0": T("IN-07", zero)})
    blank = mutate(c07, "balance_amount", lambda i, v: "" if i == 2 else v)
    add("X18", "BLANK mandatory amount in one row",
        workbook([{"name": "Bank", "blocks": [blk(blank, typed("IN-07", date_mode="text"))]}]),
        {"Bank#0": T("IN-07", outcome="BLOCKED")})
    ai, di = c10[0].index("amount"), c10[0].index("dc_indicator")
    dc = [c10[0][:ai] + ["debit", "credit"] + c10[0][di + 1:]] + \
        [r[:ai] + ([r[ai], ""] if r[di] == "D" else ["", r[ai]]) + r[di + 1:] for r in c10[1:]]
    add("X19", "DEBIT / CREDIT split columns instead of amount + dc_indicator (needs a derivation)",
        workbook([{"name": "CashBook", "blocks": [blk(dc)]}]),
        {"CashBook#0": T("IN-10", mp={h: h for h in c10[0] if h not in ("amount", "dc_indicator")},
                         outcome="REVIEW->HELD_OR_BLOCKED")})
    lz = mutate(mutate(c10, "ledger_entry_id", lambda i, v: f"{i:07d}"), "payment_reference", lambda i, v: f"00420{i:05d}")
    add("X20", "numeric-looking IDs with LEADING ZEROS typed as Excel NUMBERS (0000001 -> 1)",
        workbook([{"name": "CashBook", "blocks": [blk(lz, typed("IN-10", date_mode="text", id_numeric=(
            "ledger_entry_id", "payment_reference")))]}]),
        {"CashBook#0": T("IN-10", lz, outcome="SILENT_DIFFERENCE")}, warn=["NUMERIC_CELL"])
    add("X21", "the same leading-zero IDs stored as TEXT cells",
        workbook([{"name": "CashBook", "blocks": [blk(lz)]}]), {"CashBook#0": T("IN-10", lz)})
    # ---- A3 dates / timestamps
    add("X22", "DATE cells (yyyy-mm-dd), timestamps as text (IN-03)",
        workbook([{"name": "Balances", "blocks": [blk(c03, typed("IN-03"))]}]), {"Balances#0": T("IN-03")})
    add("X23", "DATE cells displayed dd/mm/yyyy (display format differs, stored date identical)",
        workbook([{"name": "Balances", "blocks": [blk(c03, typed("IN-03", date_fmt="dd/mm/yyyy"))]}]),
        {"Balances#0": T("IN-03")})
    td = mutate(c03, "recon_date", lambda i, v: {1: "31/08/2026", 2: "03/04/2026"}.get(i, v))
    add("X24", "TEXT dates '31/08/2026' and AMBIGUOUS '03/04/2026' (never interpreted)",
        workbook([{"name": "Balances", "blocks": [blk(td)]}]), {"Balances#0": T("IN-03", outcome="BLOCKED")},
        warn=["DATE_LIKE_TEXT_NOT_ISO"])
    add("X25", "TIMESTAMPS as native Excel datetime cells (offset cannot be stored)",
        workbook([{"name": "Balances", "blocks": [blk(c03, typed("IN-03", ts_mode="datetime"))]}]),
        {"Balances#0": T("IN-03", outcome="BLOCKED")}, warn=["DATETIME_NO_OFFSET"])
    bad = mutate(c03, "recon_date", lambda i, v: {1: "", 2: "2026-02-30"}.get(i, v))
    add("X26", "MISSING date and INVALID date '2026-02-30' (text)",
        workbook([{"name": "Balances", "blocks": [blk(bad)]}]), {"Balances#0": T("IN-03", outcome="BLOCKED")})
    # ---- A4 formulas / special cells
    j = c07[0].index("balance_amount") + 1
    col = chr(64 + j)
    f_rows = [r[:] for r in c07]
    wb_f = workbook([{"name": "Bank", "blocks": [blk(f_rows, typed("IN-07", date_mode="text"))],
                      "formulas": {f"{col}2": (f"=ROUND({c07[1][j - 1]},2)", "#,##0.00"),
                                   f"{col}3": (f"=ROUND({c07[2][j - 1]},2)", "#,##0.00")}}])
    add("X27", "FORMULA cells with CACHED results (as saved by Excel)",
        put_cached_values(wb_f, {f"{col}2": c07[1][j - 1], f"{col}3": c07[2][j - 1]}), {"Bank#0": T("IN-07")},
        warn=["FORMULA_CACHED_VALUE"])
    add("X28", "FORMULA cells WITHOUT cached results (never evaluated by the extractor)",
        wb_f, {"Bank#0": T("IN-07", outcome="BLOCKED")}, warn=["FORMULA_NO_CACHED_VALUE"])
    add("X29", "ERROR cells (#DIV/0!, #N/A) in the amount column",
        workbook([{"name": "Bank", "blocks": [blk(c07, typed("IN-07", date_mode="text"))],
                   "extra_cells": {f"{col}2": "#DIV/0!", f"{col}3": "#N/A"}}]),
        {"Bank#0": T("IN-07", outcome="BLOCKED")}, warn=["CELL_ERROR"])
    add("X30", "HIDDEN rows and columns + PROTECTED sheet (data must not be dropped)",
        workbook([{"name": "Bank", "blocks": [blk(c07)], "hidden_rows": [3, 4], "hidden_cols": ["B"], "protect": True}]),
        {"Bank#0": T("IN-07")}, warn=["HIDDEN_ROW", "HIDDEN_COLUMN"], notes=["SHEET_PROTECTED"])
    ws_ = mutate(c07, "currency", lambda i, v: f" {v}" if i == 1 else v)
    add("X31", "surrounding WHITESPACE in a value (' GBP') - never trimmed",
        workbook([{"name": "Bank", "blocks": [blk(ws_)]}]), {"Bank#0": T("IN-07", outcome="BLOCKED")},
        warn=["SURROUNDING_WHITESPACE"])
    # ---- A5 mapping
    var = {h: (f" {h.upper()} " if k % 2 == 0 else h.title()) for k, h in enumerate(c10[0])}
    add("X32", "header CASE / WHITESPACE variations (policy-normalised)",
        workbook([{"name": "CashBook", "blocks": [blk(c10, header=[var[h] for h in c10[0]])]}]),
        {"CashBook#0": T("IN-10", mp={var[h]: h for h in c10[0]})})
    alias_hdr = ["Ledger Ref"] + c10[0][1:]
    add("X33", "an APPROVED ALIAS ('Ledger Ref' -> ledger_entry_id, approved in the isolated store)",
        workbook([{"name": "CashBook", "blocks": [blk(c10, header=alias_hdr)]}]),
        {"CashBook#0": T("IN-10", mp=dict(zip(alias_hdr, c10[0])), aliases=[("IN-10", "Ledger Ref", "ledger_entry_id")])})
    fr = {"ledger_entry_id": "Ledger entry ID", "account_id": "Safeguarding account", "posted_ts": "Posted at",
          "payment_reference": "Payment ref"}
    add("X34", "FRIENDLY non-financial headers (4 of 8)",
        workbook([{"name": "CashBook", "blocks": [blk(c10, header=[fr.get(h, h) for h in c10[0]])]}]),
        {"CashBook#0": T("IN-10", mp={fr.get(h, h): h for h in c10[0]}, outcome="REVIEW->EXACT")})
    ff = {"amount": "Value", "dc_indicator": "Dr/Cr"}
    add("X35", "FRIENDLY FINANCIAL headers ('Value', 'Dr/Cr')",
        workbook([{"name": "CashBook", "blocks": [blk(c10, header=[ff.get(h, h) for h in c10[0]])]}]),
        {"CashBook#0": T("IN-10", mp={ff.get(h, h): h for h in c10[0]}, outcome="REVIEW->EXACT")})
    dup = [c10[0] + ["amount"]] + [r + [r[ai]] for r in c10[1:]]
    add("X36", "DUPLICATE header ('amount' twice, 9 vs 8)",
        workbook([{"name": "CashBook", "blocks": [blk(dup)]}]), {"CashBook#0": T("IN-10", outcome="REVIEW->EXACT")})
    unm = [c10[0][:-1] + ["display_colour"]] + [r[:-1] + ["#FF0000"] for r in c10[1:]]
    add("X37", "UNMAPPED column ('display_colour' replaces payment_reference; same count)",
        workbook([{"name": "CashBook", "blocks": [blk(unm)]}]),
        {"CashBook#0": T("IN-10", mp={h: h for h in c10[0][:-1]}, outcome="REVIEW->HELD_OR_BLOCKED")})
    return S


# ================================================================================================ JSON writing
class Raw(str):
    """A literal written into the JSON text as-is (to produce exact number / float / scientific forms)."""


def jdump(v, indent=0) -> str:
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(k)}: {jdump(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[\n  " + ",\n  ".join(jdump(x) for x in v) + "\n]" if v else "[]"
    return json.dumps(v, ensure_ascii=False)


def records(rows, transform=None, keymap=None, drop=None, extra=None, nest=None):
    out = []
    for i, r in enumerate(rows[1:], start=1):
        o = {}
        for h, v in zip(rows[0], r):
            if drop and drop(i, h):
                continue
            val = transform(i, h, v) if transform else v
            key = (keymap or {}).get(h, h)
            if nest and h in nest:
                cur = o
                parts = nest[h].split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                cur[parts[-1]] = val
            else:
                o[key] = val
        if extra:
            o.update(extra(i))
        out.append(o)
    return out


def jfile(doc) -> bytes:
    return jdump(doc).encode("utf-8")


def json_scenarios():
    S = []
    c10, c03, c07, c08 = canon("IN-10"), canon("IN-03"), canon("IN-07"), canon("IN-08")
    t10 = types("IN-10")
    add = lambda sid, desc, data, tables, **kw: S.append(  # noqa: E731
        dict(id=sid, fmt="json", desc=desc, data=data, file=f"{sid}.json", tables=tables, **kw))
    # ---- B1 structures
    add("J01", "flat ARRAY of records, canonical keys, string values (IN-10)", jfile(records(c10)), {"$": T("IN-10")})
    add("J02", "ONE OBJECT with three record arrays (IN-10, IN-03, IN-07)",
        jfile({"cash_book": records(c10), "balances": records(c03), "confirmations": records(c07)}),
        {"$.cash_book": T("IN-10"), "$.balances": T("IN-03"), "$.confirmations": T("IN-07")})
    add("J03", "WRAPPED: {meta: {...}, data: {cash_book: [...]}}",
        jfile({"meta": {"producer": "synthetic", "generated": "2026-10-01"}, "data": {"cash_book": records(c10)}}),
        {"$.data.cash_book": T("IN-10")}, notes=["NON_TABULAR_VALUE"])
    nest = {"ledger_entry_id": "entry.id", "account_id": "account.id", "posted_ts": "entry.posted_ts",
            "entry_type": "entry.type", "amount": "money.amount", "dc_indicator": "money.dc",
            "currency": "money.currency"}
    add("J04", "NESTED objects (entry.id, money.amount, money.dc, ...) flattened to dotted paths",
        jfile(records(c10, nest=nest)),
        {"$": T("IN-10", mp={**{v: k for k, v in nest.items()}, "payment_reference": "payment_reference"},
                outcome="REVIEW->EXACT")})
    add("J05", "ARRAY nested inside every record ('tags': [...]) -> extra column kept as JSON text",
        jfile(records(c10, extra=lambda i: {"tags": ["a", "b"]})), {"$": T("IN-10", outcome="REVIEW->EXACT")},
        warn=["NESTED_ARRAY"])
    add("J06", "key MISSING in every 7th record (payment_reference)",
        jfile(records(c10, drop=lambda i, h: h == "payment_reference" and i % 7 == 0)),
        {"$": T("IN-10", outcome="BLOCKED")}, warn=["KEY_ABSENT"])
    add("J07", "an ADDITIONAL key in every record ('comment')",
        jfile(records(c10, extra=lambda i: {"comment": "ok"})), {"$": T("IN-10", outcome="REVIEW->EXACT")})
    add("J08", "EMPTY array + EMPTY object + a record array",
        jfile({"cash_book": [], "meta": {}, "balances": records(c03)}), {"$.balances": T("IN-03")},
        notes=["EMPTY_ARRAY", "EMPTY_OBJECT"])
    add("J09", "NULL values in a mandatory field (payment_reference null in 3 records)",
        jfile(records(c10, transform=lambda i, h, v: None if h == "payment_reference" and i <= 3 else v)),
        {"$": T("IN-10", outcome="BLOCKED")}, warn=["NULL_VALUE"])
    add("J10", "MIXED types for one key (amount as string in some records, number in others)",
        jfile(records(c10, transform=lambda i, h, v: Raw(v) if h == "amount" and i % 2 else v)),
        {"$": T("IN-10")}, warn=["MIXED_TYPES"])
    shuffled = [dict(reversed(list(o.items()))) if i % 2 else o for i, o in enumerate(records(c10))]
    add("J11", "INCONSISTENT key ORDER across records (same key set)", jfile(shuffled), {"$": T("IN-10")})
    deep = {"ledger_entry_id": "l1.l2.l3.l4.l5.id"}
    add("J12", "DEEPLY nested key (5 levels) beyond the flattening depth",
        jfile(records(c10, nest=deep)),
        {"$": T("IN-10", mp={h: h for h in c10[0] if h != "ledger_entry_id"}, outcome="REVIEW->HELD_OR_BLOCKED")},
        warn=["DEEP_NESTING"])
    # ---- B2 numbers
    money = lambda f: (lambda i, h, v: Raw(f(v)) if t10.get(h) in ("amount", "signed") and v else v)  # noqa: E731
    add("J13", "money as INTEGER literals (250000)", jfile(records(c10, transform=money(lambda v: str(int(Decimal(v)))))),
        {"$": T("IN-10", outcome="BLOCKED")})
    add("J14", "money as DECIMAL literals WITH trailing zeros (250000.00) - literal preserved",
        jfile(records(c10, transform=money(lambda v: v))), {"$": T("IN-10")})
    big = mutate(c07, "balance_amount", lambda i, v: "12345678901234567.89" if i == 1 else v)
    add("J15", "LARGE number literal 12345678901234567.89 (beyond float precision) - literal preserved",
        jfile(records(big, transform=lambda i, h, v: Raw(v) if h == "balance_amount" else v)), {"$": T("IN-07", big)})
    neg = mutate(c03, "balance", lambda i, v: f"-{v}" if i % 9 == 0 and not v.startswith("-") and v != "0.00" else v)
    add("J16", "NEGATIVE signed amounts as literals (-12.50) for IN-03 balance",
        jfile(records(neg, transform=lambda i, h, v: Raw(v) if h == "balance" else v)), {"$": T("IN-03", neg)})
    negu = mutate(c10, "amount", lambda i, v: f"-{v}" if i == 3 else v)
    add("J17", "a NEGATIVE value in an UNSIGNED amount field (IN-10 amount -x)",
        jfile(records(negu, transform=money(lambda v: v))), {"$": T("IN-10", outcome="BLOCKED")})
    z = mutate(c07, "balance_amount", lambda i, v: "0.00" if i <= 2 else v)
    add("J18", "ZERO literals 0.00", jfile(records(z, transform=lambda i, h, v: Raw(v) if h == "balance_amount" else v)),
        {"$": T("IN-07", z)})
    add("J19", "NULL amount", jfile(records(c07, transform=lambda i, h, v: None if h == "balance_amount" and i == 2 else v)),
        {"$": T("IN-07", outcome="BLOCKED")})
    add("J20", "STRING amounts with currency symbol / grouping ('£12.50', '1,234.56')",
        jfile(records(c07, transform=lambda i, h, v: {1: "£260,019.50", 2: "1,234.56"}.get(i, v)
                      if h == "balance_amount" else v)),
        {"$": T("IN-07", outcome="BLOCKED")}, warn=["NUMBER_LIKE_TEXT_NON_CANONICAL"])
    add("J21", "FLOAT representations (250000.0) as a typical producer writes them",
        jfile(records(c10, transform=money(lambda v: repr(float(Decimal(v)))))), {"$": T("IN-10", outcome="BLOCKED")})
    add("J22", "SCIENTIFIC notation (2.5E5)",
        jfile(records(c10, transform=money(lambda v: f"{Decimal(v):E}"))), {"$": T("IN-10", outcome="BLOCKED")},
        warn=["SCIENTIFIC_NOTATION"])
    add("J23", "lower-case CURRENCY codes ('gbp') - never normalised",
        jfile(records(c10, transform=lambda i, h, v: v.lower() if h == "currency" else v)),
        {"$": T("IN-10", outcome="BLOCKED")})
    # ---- B3 dates
    add("J24", "ISO dates and ISO timestamps WITH offsets (IN-03)", jfile(records(c03)), {"$": T("IN-03")})
    add("J25", "timestamps WITHOUT offset ('2026-08-31T17:00:00')",
        jfile(records(c03, transform=lambda i, h, v: v[:19] if h == "as_at_ts" else v)),
        {"$": T("IN-03", outcome="BLOCKED")})
    add("J26", "AMBIGUOUS '03/04/2026', INVALID '2026-02-30', NULL dates",
        jfile(records(c03, transform=lambda i, h, v: {1: "03/04/2026", 2: "2026-02-30", 3: None}.get(i, v)
                      if h == "recon_date" else v)),
        {"$": T("IN-03", outcome="BLOCKED")}, warn=["DATE_LIKE_TEXT_NOT_ISO"])
    add("J27", "EPOCH numbers for timestamps (1756656000)",
        jfile(records(c03, transform=lambda i, h, v: Raw(str(int(datetime.fromisoformat(v).timestamp())))
                      if h == "as_at_ts" else v)),
        {"$": T("IN-03", outcome="BLOCKED")})
    # ---- B4 mapping
    var = {h: (h.upper() if k % 2 else f" {h} ") for k, h in enumerate(c10[0])}
    add("J28", "key CASE / WHITESPACE variations", jfile(records(c10, keymap=var)),
        {"$": T("IN-10", mp={v: k for k, v in var.items()})})
    fr = {"ledger_entry_id": "entryRef", "account_id": "accountRef", "posted_ts": "postedAt", "entry_type": "type"}
    add("J29", "FRIENDLY camelCase keys (non-financial)", jfile(records(c10, keymap=fr)),
        {"$": T("IN-10", mp={fr.get(h, h): h for h in c10[0]}, outcome="REVIEW->EXACT")})
    ff = {"amount": "value", "dc_indicator": "direction"}
    add("J30", "FRIENDLY FINANCIAL keys ('value', 'direction')", jfile(records(c10, keymap=ff)),
        {"$": T("IN-10", mp={ff.get(h, h): h for h in c10[0]}, outcome="REVIEW->EXACT")})
    add("J31", "CONFLICTING structures: 'amount' and 'Amount' in every record (9 vs 8)",
        jfile(records(c10, extra=lambda i: {"Amount": "0.00"})), {"$": T("IN-10", outcome="REVIEW->EXACT")})
    return S


# ================================================================================================ adversarial
def adversarial_scenarios(xlsx_ok: bytes, json_ok: bytes):
    import openpyxl
    S = []
    add = lambda sid, desc, data, file, expect, **kw: S.append(  # noqa: E731
        dict(id=sid, fmt="adversarial", desc=desc, data=data, file=file, expect=expect, **kw))
    add("E01", "CORRUPTED workbook (truncated ZIP)", xlsx_ok[: len(xlsx_ok) // 2], "broken.xlsx", "REFUSED:WORKBOOK_UNREADABLE")
    add("E02", "INVALID JSON (trailing comma)", b'[{"a": "1",}]', "broken.json", "REFUSED:JSON_SYNTAX")
    add("E03", "EMPTY file named .xlsx", b"", "empty.xlsx", "REFUSED:EMPTY_FILE")
    add("E04", "EMPTY file named .json", b"", "empty.json", "REFUSED:EMPTY_FILE")
    add("E05", "XLSX content with a .json extension (detected by content)", xlsx_ok, "really_a_workbook.json", "EXTRACTED:xlsx")
    add("E06", "XLSX renamed to .csv (existing Smart Parser identify also checked)", xlsx_ok, "cashbook.csv",
        "EXTRACTED:xlsx", existing=True)
    add("E07", "JSON renamed to .csv (existing Smart Parser identify also checked)", json_ok, "cashbook.csv",
        "EXTRACTED:json", existing=True)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("readme.txt", "not a workbook")
    add("E08", "unexpected ZIP contents named .xlsx", b.getvalue(), "fake.xlsx", "REFUSED:NOT_AN_XLSX_WORKBOOK")
    wb = openpyxl.Workbook()
    wb.active.title = "Huge"
    wb.active["A1"] = "x"
    wb.active["XFD1048576"] = "stray"
    wb.create_sheet("Data")
    for r in canon("IN-07"):
        wb["Data"].append(r)
    bb = io.BytesIO()
    wb.save(bb)
    add("E09", "EXTREME sheet dimension (stray cell at XFD1048576) next to a normal sheet", bb.getvalue(), "huge.xlsx",
        "NOTE:SHEET_TOO_LARGE")
    add("E10", "EXCESSIVELY nested JSON (100 000 levels)", b"[" * 100000 + b"]" * 100000, "deep.json",
        "REFUSED:NESTING_TOO_DEEP")
    add("E11", "DUPLICATE keys in a JSON record", b'[{"amount": "1.00", "amount": "2.00"}]', "dup.json",
        "REFUSED:DUPLICATE_KEYS")
    add("E12", "INVALID encoding (Latin-1 bytes in JSON)", '[{"name": "Café"}]'.encode("latin-1"), "latin1.json",
        "REFUSED:INVALID_ENCODING")
    add("E13", "UTF-16 encoded JSON", '[{"a": "1"}]'.encode("utf-16"), "utf16.json", "REFUSED:INVALID_ENCODING")
    add("E14", "NaN / Infinity literals in JSON", b'[{"amount": NaN}]', "nan.json", "REFUSED:NON_STANDARD_NUMBER")
    wb2 = openpyxl.Workbook()
    ws = wb2.active
    ws.title = "Odd"
    c07 = canon("IN-07")
    for r in c07:
        ws.append(r)
    jj = c07[0].index("balance_amount") + 1
    ws.cell(2, jj).value = __import__("datetime").time(12, 30)
    ws.cell(3, jj).value, ws.cell(3, jj).number_format = 0.125, "0%"
    ws.cell(4, jj).value = True
    bb2 = io.BytesIO()
    wb2.save(bb2)
    add("E15", "UNEXPECTED cell types in an amount column (time-only, percent, boolean)", bb2.getvalue(), "odd.xlsx",
        "EXTRACTED:xlsx", table={"Odd#0": T("IN-07", outcome="BLOCKED")}, warn=["TIME_ONLY_CELL", "PERCENT_FORMAT"])
    add("E16", "AMBIGUOUS financial text '1,234' (1234 or 1.234?)",
        jfile(records(canon("IN-07"), transform=lambda i, h, v: "1,234" if h == "balance_amount" and i == 1 else v)),
        "ambiguous.json", "EXTRACTED:json", table={"$": T("IN-07", outcome="BLOCKED")})
    return S
