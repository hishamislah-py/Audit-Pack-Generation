"""Experiment C1 unit tests - XLSX safety remediation (isolated; NOT part of the main suite: run with
    py -3.11 -m pytest -p no:cacheprovider experiments/realworld_formats/test_c1_remediation.py
They pin: X20 (numeric identifiers) and X13 (precision > 15 significant digits) are HARD blockers at handoff; nothing is
reconstructed; writer noise is not a false block; every XLSX code has a policy decision; review cannot bypass the gate;
the JSON path is unchanged."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge import UnclassifiedWarning, evaluate_table, xlsx_assert_classified, xlsx_gate  # noqa: E402
from extract import (BLOCKING, INFO, XLSX_WARNING_POLICY, declared_decimals, extract_json, extract_xlsx,  # noqa: E402
                     significant_digits)
from scenarios import T, blk, canon, mutate, set_raw_values, typed, workbook  # noqa: E402


def wb(build):
    import openpyxl
    w = openpyxl.Workbook()
    build(w.active)
    b = io.BytesIO()
    w.save(b)
    return b.getvalue()


def ident_mapping(table):
    return {j: h for j, h in enumerate(table.header)}


# ------------------------------------------------------------------------------------------- precision rule (X13)
@pytest.mark.parametrize("v,n", [
    (1234567890123.45, 15), (999999999999999, 15), (999999999999999.0, 15), (0.1, 1), (250000.0, 2),
    (98765432109.99001, 13), (2926.3299999999999, 6),                    # writer noise collapses to the intended value
    (12345678901234.56, 16), (1000000000000001, 16), (1.234567890123457e+16, 16),
    (0.30000000000000004, 17), (12345678901234567, 17), (0, 0)])
def test_significant_digits_of_shortest_round_trip(v, n):
    assert significant_digits(v) == n


def _bank_with_raw(literals):
    def build(ws):
        ws.append(["amount", "note"])
        for _ in literals:
            ws.append([1.0, "x"])
        for r in range(2, len(literals) + 2):
            ws.cell(r, 1).number_format = "#,##0.00"
    return set_raw_values(wb(build), {f"A{i + 2}": lit for i, lit in enumerate(literals)})


def test_precision_boundary_blocks_only_beyond_15_and_records_raw_literal():
    lits = ["1234567890123.45", "999999999999999", "98765432109.99001", "2926.3299999999999",        # safe
            "12345678901234.56", "1000000000000001", "1.234567890123457E+16", "0.30000000000000004"]  # block
    ex = extract_xlsx(_bank_with_raw(lits), "x.xlsx")
    cells = [r[0] for r in ex.tables[0].rows]
    flagged = ["PRECISION_EXCEEDS_15_DIGITS" in c.warnings for c in cells]
    assert flagged == [False] * 4 + [True] * 4
    assert [c.raw for c in cells] == lits                                  # the stored literal is preserved verbatim
    # never reconstructed / rounded / repaired: the text is the stored double, not a guess at the typed value
    assert cells[6].text == "12345678901234570.00" and cells[6].raw == "1.234567890123457E+16"


def test_x13_value_lost_before_storage_is_not_claimed_recovered():
    # 12345678901234567.89 typed -> the file can only hold the double 1.2345678901234568e16: the gate blocks, it does not
    # (and cannot) recover the typed digits.
    ex = extract_xlsx(_bank_with_raw(["1.2345678901234568E+16"]), "x.xlsx")
    c = ex.tables[0].rows[0][0]
    assert "PRECISION_EXCEEDS_15_DIGITS" in c.warnings and c.text == "12345678901234568.00"
    assert not c.text.endswith(".89") and c.text != "12345678901234567.89"           # typed cents not recovered


# ------------------------------------------------------------------------------------- numeric identifiers (X20)
def _cashbook(ids, as_number, fmt=None):
    c10 = canon("IN-10")
    rows = mutate(c10, "ledger_entry_id", lambda i, v: ids[(i - 1) % len(ids)])
    data = workbook([{"name": "CashBook", "blocks": [blk(rows, typed(
        "IN-10", date_mode="text", id_numeric=("ledger_entry_id",) if as_number else ()))]}])
    if fmt:
        import openpyxl
        w = openpyxl.load_workbook(io.BytesIO(data))
        for r in range(2, len(rows) + 1):
            w["CashBook"].cell(r, 1).number_format = fmt
        b = io.BytesIO()
        w.save(b)
        data = b.getvalue()
    return extract_xlsx(data, "x.xlsx").tables[0], rows


@pytest.mark.parametrize("ids", [["0000001", "0000002"], ["0042000001"], ["1001", "1002"], ["7"]])
def test_numeric_id_cells_block_and_keep_value_and_locator(ids):
    t, _ = _cashbook(ids, as_number=True)
    hits = [h for h in xlsx_gate(t, ident_mapping(t), "IN-10") if h["code"] == "NUMERIC_CELL_IN_TEXT_LIKE_COLUMN"]
    assert len(hits) == len(t.rows)                                        # every numeric id cell, not just the first
    h = hits[0]
    assert h["field"] == "ledger_entry_id" and h["field_type"] == "id" and h["locator"] == "CashBook!A2"
    assert h["text"] == str(int(ids[0])) and h["raw"] == str(int(ids[0]))  # zeros never reconstructed
    assert h["cell_type"] == "int"


def test_display_format_never_invents_leading_zeros():
    t, _ = _cashbook(["0000001"], as_number=True, fmt="0000000")          # Excel SHOWS 0000001, STORES 1
    c = t.rows[0][0]
    assert c.text == "1" and c.raw == "1" and c.number_format == "0000000"
    assert any(h["code"] == "NUMERIC_CELL_IN_TEXT_LIKE_COLUMN" for h in xlsx_gate(t, ident_mapping(t), "IN-10"))


def test_text_ids_with_leading_zeros_pass_the_gate():
    t, rows = _cashbook(["0000001", "0042000001"], as_number=False)
    assert [r[0].text for r in t.rows][:2] == ["0000001", "0042000001"]
    assert xlsx_gate(t, ident_mapping(t), "IN-10") == []


def test_unmapped_numeric_column_is_not_gated():
    t, _ = _cashbook(["0000001"], as_number=True)
    m = ident_mapping(t)
    del m[0]                                                             # ledger_entry_id not mapped
    assert not any(h["field"] == "ledger_entry_id" for h in xlsx_gate(t, m, "IN-10"))


# ------------------------------------------------------------------------------------------- rendering policies
def test_declared_decimals():
    assert declared_decimals("#,##0.00") == 2 and declared_decimals("0.00;(0.00)") == 2
    assert declared_decimals("#,##0") == 0 and declared_decimals("0000000") == 0
    assert declared_decimals("General") is None and declared_decimals(None) is None
    assert declared_decimals("0.000") == 3 and declared_decimals('"£"#,##0.00') == 2


def test_money_requires_fixed_two_decimal_format():
    def build(ws):
        ws.append(["amount", "note"])
        for v, f in ((260019.37, "General"), (5.0, "#,##0"), (5.0, "0.000"), (5.0, "#,##0.00"), (5.0, '"£"#,##0.00')):
            ws.append([v, "x"])
            ws.cell(ws.max_row, 1).number_format = f
    t = extract_xlsx(wb(build), "x.xlsx").tables[0]
    hits = [h["locator"] for h in xlsx_gate(t, {0: "balance_amount"}, "IN-07")
            if h["code"] == "MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT"]
    assert hits == ["Sheet!A2", "Sheet!A3", "Sheet!A4"]                   # General, 0 and 3 decimals; 2-decimal formats ok
    assert [r[0].text for r in t.rows] == ["260019.37", "5", "5.000", "5.00", "5.00"]   # currency symbol never in value


def test_locale_text_is_never_converted_and_dates_are_iso():
    from datetime import datetime
    def build(ws):
        ws.append(["a", "d"])
        ws.append(["1.234,56", datetime(2026, 8, 31)])
        ws["B2"].number_format = "dd/mm/yyyy"
    r = extract_xlsx(wb(build), "x.xlsx").tables[0].rows[0]
    assert r[0].text == "1.234,56" and r[1].text == "2026-08-31"


# ------------------------------------------------------------------------------------------------ warning policy
def test_every_xlsx_code_is_classified_and_unclassified_codes_stop():
    assert all(v[0] in ("HARD_WHEN_MAPPED", "INFO") and v[1] for v in XLSX_WARNING_POLICY.values())
    hard = {k for k, v in XLSX_WARNING_POLICY.items() if v[0] == "HARD_WHEN_MAPPED"}
    assert {"NUMERIC_CELL_IN_TEXT_LIKE_COLUMN", "PRECISION_EXCEEDS_15_DIGITS", "FORMULA_NO_CACHED_VALUE",
            "CELL_ERROR", "MERGED_IN_DATA", "DATETIME_NO_OFFSET", "TIME_ONLY_CELL", "PERCENT_FORMAT"} <= hard
    # every code literal the XLSX extractor can emit is classified (static check of the source)
    import re
    src = (Path(__file__).parent / "extract.py").read_text(encoding="utf-8")
    xlsx_src = src[src.index("def _text_flags"):src.index("# ======", src.index("def extract_xlsx"))]
    emitted = set(re.findall(r'"([A-Z][A-Z0-9_]{4,})(?::|")', xlsx_src)) - {"General", "WORKBOOK_UNREADABLE",
                                                                           "EMPTY_FILE", "NOT_AN_XLSX_WORKBOOK",
                                                                           "UNSUPPORTED"}
    assert emitted and emitted <= set(XLSX_WARNING_POLICY), emitted - set(XLSX_WARNING_POLICY)
    t, _ = _cashbook(["0000001"], as_number=False)
    t.rows[0][1].warnings.append("SOMETHING_NEW")
    with pytest.raises(UnclassifiedWarning):
        xlsx_gate(t, ident_mapping(t), "IN-10")
    with pytest.raises(UnclassifiedWarning):
        xlsx_assert_classified(None, ["BRAND_NEW_NOTE: x"])


def test_json_policy_sets_unchanged():
    assert BLOCKING == {"FORMULA_NO_CACHED_VALUE", "CELL_ERROR", "PRECISION_EXCEEDS_15_DIGITS", "DATETIME_NO_OFFSET",
                        "MERGED_IN_DATA", "NUMERIC_CELL_IN_TEXT_LIKE_COLUMN", "DUPLICATE_KEYS", "NESTED_ARRAY",
                        "DEEP_NESTING", "DATA_WITHOUT_HEADER_COLUMN", "PERCENT_FORMAT", "TIME_ONLY_CELL"}
    assert "SCIENTIFIC_NOTATION" in INFO and "MIXED_TYPES" in INFO
    ex = extract_json(b'[{"a": "0000001", "b": 12345678901234567.89}]', "x.json")
    assert [c.raw for c in ex.tables[0].rows[0]] == [None, None]             # no XLSX raw field on JSON cells


# --------------------------------------------------------------------- end to end through the existing workflow
def _x20_like(header_name, tmp_path, name):
    c10 = canon("IN-10")
    lz = mutate(c10, "ledger_entry_id", lambda i, v: f"{i:07d}")
    hdr = [header_name] + c10[0][1:]
    data = workbook([{"name": "CashBook", "blocks": [blk(lz, typed("IN-10", date_mode="text", id_numeric=(header_name,)),
                                                          header=hdr)]}])
    t = extract_xlsx(data, "x.xlsx").tables[0]
    truth = T("IN-10", lz, mp=dict(zip(hdr, c10[0])))
    return evaluate_table(t, tmp_path, name, truth, source_format="xlsx")


def test_x20_pipeline_eligible_but_gate_refuses_and_no_preview(tmp_path):
    r = _x20_like("ledger_entry_id", tmp_path, "direct")
    assert r["eligible"] is True and r["outcome"] == "GATE_BLOCKED"           # existing workflow alone would say eligible
    assert r["preview_sha256"] is None and r["preview_exact"] is None
    assert r["xlsx_gate"]["counterfactual_without_gate_equals_truth"] is False
    assert not [p for p in (tmp_path / "direct").rglob("*.csv") if "PREVIEW" in p.name]    # no preview file anywhere


def test_review_cannot_bypass_the_gate(tmp_path):
    r = _x20_like("Entry no", tmp_path, "review")
    assert "review" in r and r["review"]["eligible"] is True
    assert r["outcome"] == "REVIEW->GATE_BLOCKED" and r["review"]["preview_sha256"] is None
    assert not [p for p in (tmp_path / "review").rglob("*.csv") if "PREVIEW" in p.name]


def test_clean_xlsx_still_produces_exact_preview(tmp_path):
    c10 = canon("IN-10")
    ok = mutate(c10, "ledger_entry_id", lambda i, v: f"{i:07d}")
    t = extract_xlsx(workbook([{"name": "CashBook", "blocks": [blk(ok, typed("IN-10", date_mode="text"))]}]),
                     "x.xlsx").tables[0]
    r = evaluate_table(t, tmp_path, "ok", T("IN-10", ok), source_format="xlsx")
    assert r["outcome"] == "EXACT" and r["xlsx_gate"]["clear"] and r["preview_exact"] is True
    assert len([p for p in (tmp_path / "ok").rglob("*.csv") if "PREVIEW" in p.name]) == 1    # only the gated one
