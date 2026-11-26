"""Experiment C unit tests (isolated; NOT part of the main suite: run with
    py -3.11 -m pytest -p no:cacheprovider experiments/realworld_formats/test_realworld.py
They pin the extractor safety rules: content-based detection, faithful rendering, visible refusal, no correction."""
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import BLOCKING, detect, extract, extract_json, extract_xlsx  # noqa: E402


def wb(build):
    import openpyxl
    w = openpyxl.Workbook()
    build(w.active)
    b = io.BytesIO()
    w.save(b)
    return b.getvalue()


def cell(ex, r=0, c=0, t=0):
    return ex.tables[t].rows[r][c]


def test_detection_is_by_content_not_extension():
    x = wb(lambda ws: ws.append(["a", "b"]))
    assert detect(x) == "xlsx" and detect(b'[{"a": "1"}]') == "json" and detect(b"") == "empty"
    assert extract(x, "named.json").upload.detected_format == "xlsx"
    assert extract(b'[{"a": "1"}]', "named.xlsx").tables[0].header == ["a"]


def test_json_number_literals_are_preserved_exactly():
    ex = extract_json(b'[{"a": 250000.00, "b": 12345678901234567.89, "c": 250000.0, "d": 2.5E5, "e": 7}]', "x.json")
    assert [c.text for c in ex.tables[0].rows[0]] == ["250000.00", "12345678901234567.89", "250000.0", "2.5E5", "7"]
    assert "SCIENTIFIC_NOTATION" in cell(ex, c=3).warnings


def test_json_duplicate_keys_nan_and_encoding_are_refused_visibly():
    assert json.loads('{"a":1,"a":2}') == {"a": 2}                       # what the standard parser does silently
    assert extract_json(b'[{"a": "1", "a": "2"}]', "x").refused.startswith("DUPLICATE_KEYS")
    assert extract_json(b'[{"a": NaN}]', "x").refused.startswith("NON_STANDARD_NUMBER")
    assert extract_json('[{"a": "Café"}]'.encode("latin-1"), "x").refused.startswith("INVALID_ENCODING")
    assert extract_json(b"[" * 100000 + b"]" * 100000, "x").refused.startswith("NESTING_TOO_DEEP")


def test_json_null_absent_nested_and_arrays_are_distinguished_and_reported():
    ex = extract_json(b'[{"a": null, "b": {"c": "1"}, "t": [1, 2]}, {"b": {"c": "2"}}]', "x.json")
    t = ex.tables[0]
    assert t.header == ["a", "b.c", "t"]
    assert t.rows[0][0].type == "null" and t.rows[1][0].type == "absent"
    assert "NESTED_ARRAY" in t.rows[0][2].warnings and t.rows[0][2].text == "[1, 2]"
    assert "NESTED_ARRAY" in t.blocking()


def test_xlsx_money_rendering_is_faithful_never_corrected():
    def build(ws):
        ws.append(["amount", "other"])
        ws.append([1234.5, "(12.50)"])
        ws.append([-12.5, "1.234,56"])
        ws["A2"].number_format = "#,##0.00"
        ws["A3"].number_format = "#,##0.00;(#,##0.00)"
    ex = extract_xlsx(wb(build), "x.xlsx")
    assert [cell(ex, 0, 0).text, cell(ex, 1, 0).text] == ["1234.50", "-12.50"]
    assert "NEGATIVE_DISPLAYED_IN_PARENTHESES" in cell(ex, 1, 0).warnings
    assert [cell(ex, 0, 1).text, cell(ex, 1, 1).text] == ["(12.50)", "1.234,56"]        # text never converted
    assert "NUMBER_LIKE_TEXT_NON_CANONICAL" in cell(ex, 0, 1).warnings


def test_xlsx_dates_timestamps_formulas_errors():
    def build(ws):
        ws.append(["d", "ts", "f", "e"])
        ws.append([datetime(2026, 8, 31), datetime(2026, 8, 31, 17, 0), "=1+1", "#DIV/0!"])
        ws["A2"].number_format = "yyyy-mm-dd"
        ws["B2"].number_format = "yyyy-mm-dd hh:mm:ss"
    ex = extract_xlsx(wb(build), "x.xlsx")
    d, ts, f, e = ex.tables[0].rows[0]
    assert d.text == "2026-08-31" and ts.text == "2026-08-31T17:00:00" and "DATETIME_NO_OFFSET" in ts.warnings
    assert f.text == "" and "FORMULA_NO_CACHED_VALUE" in f.warnings                      # never evaluated
    assert e.text == "#DIV/0!" and "CELL_ERROR" in e.warnings
    assert {"DATETIME_NO_OFFSET", "FORMULA_NO_CACHED_VALUE", "CELL_ERROR"} <= set(ex.tables[0].blocking())


def test_xlsx_precision_and_hidden_sheets_and_titles_are_reported():
    import openpyxl
    w = openpyxl.Workbook()
    ws = w.active
    ws.title = "Data"
    ws.append(["Report title"])
    ws.append([])
    ws.append(["amount", "id"])
    ws.append([12345678901234567.89, 123])
    ws["A4"].number_format = "0.00"
    h = w.create_sheet("Hidden")
    h.append(["x", "y"])
    h.sheet_state = "hidden"
    b = io.BytesIO()
    w.save(b)
    ex = extract_xlsx(b.getvalue(), "x.xlsx")
    assert any(n.startswith("TITLE_ROW") for n in ex.notes) and any(n.startswith("SHEET_HIDDEN") for n in ex.notes)
    assert "PRECISION_EXCEEDS_15_DIGITS" in cell(ex, 0, 0).warnings
    assert cell(ex, 0, 1).text == "123" and "NUMERIC_CELL" in cell(ex, 0, 1).warnings


def test_xlsx_refusals_are_visible():
    assert extract_xlsx(b"", "x").refused == "EMPTY_FILE"
    good = wb(lambda ws: ws.append(["a", "b"]))
    assert extract_xlsx(good[: len(good) // 2], "x").refused.startswith("WORKBOOK_UNREADABLE")


def test_blocking_set_is_the_documented_one():
    assert {"FORMULA_NO_CACHED_VALUE", "CELL_ERROR", "PRECISION_EXCEEDS_15_DIGITS", "DATETIME_NO_OFFSET",
            "NUMERIC_CELL_IN_TEXT_LIKE_COLUMN", "DUPLICATE_KEYS"} <= BLOCKING
