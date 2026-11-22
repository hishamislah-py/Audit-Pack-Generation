"""Experiment C1 - additional XLSX safety scenarios (generated into inputs_c1/; the original Experiment C inputs are never
regenerated). Same conventions as scenarios.py; new expected outcome:
    GATE_BLOCKED            the existing workflow says eligible, the C1 XLSX hard gate refuses: no preview written
    REVIEW->GATE_BLOCKED    the same after a (simulated) human review - review cannot bypass the gate
"""
from __future__ import annotations

import io
from datetime import datetime, time

from scenarios import T, blk, canon, mutate, set_raw_values, typed, workbook


def xlsx_c1_scenarios():
    S = []
    add = lambda sid, desc, data, tables, **kw: S.append(  # noqa: E731
        dict(id=sid, fmt="xlsx", desc=desc, data=data, file=f"{sid}.xlsx", tables=tables, **kw))
    c10, c07, c02 = canon("IN-10"), canon("IN-07"), canon("IN-02")
    j07 = c07[0].index("balance_amount")
    acol = chr(65 + j07)

    # ---------------- numeric identifiers (X20 family)
    ids = mutate(c10, "ledger_entry_id", lambda i, v: str(1000 + i))
    add("X38", "numeric-looking IDs WITHOUT leading zeros typed as numbers (1001 -> 1001: unchanged, still refused)",
        workbook([{"name": "CashBook", "blocks": [blk(ids, typed("IN-10", date_mode="text", id_numeric=("ledger_entry_id",)))]}]),
        {"CashBook#0": T("IN-10", ids, outcome="GATE_BLOCKED")}, warn=["NUMERIC_CELL"])
    lz = mutate(c10, "ledger_entry_id", lambda i, v: f"{i:07d}")
    hdr = ["Entry no"] + c10[0][1:]
    add("X39", "X20 pattern through HUMAN REVIEW: friendly header 'Entry no' + leading-zero IDs typed as numbers",
        workbook([{"name": "CashBook", "blocks": [blk(lz, typed("IN-10", date_mode="text", id_numeric=("Entry no",)),
                                                      header=hdr)]}]),     # the typer keys on the WRITTEN header
        {"CashBook#0": T("IN-10", lz, mp=dict(zip(hdr, c10[0])), outcome="REVIEW->GATE_BLOCKED")})
    big = mutate(c10, "payment_reference", lambda i, v: str(123456789012345600 + i))
    add("X40", "18-digit numeric reference typed as a number (identifier AND precision)",
        workbook([{"name": "CashBook", "blocks": [blk(big, typed("IN-10", date_mode="text", id_numeric=("payment_reference",)))]}]),
        {"CashBook#0": T("IN-10", big, outcome="GATE_BLOCKED")}, warn=["PRECISION_EXCEEDS_15_DIGITS"])

    # ---------------- precision boundary (X13 family), money as numbers with #,##0.00
    def prec(sid, desc, values, outcome, warn=()):
        rows = mutate(c07, "balance_amount", lambda i, v: values.get(i, v))
        add(sid, desc, workbook([{"name": "Bank", "blocks": [blk(rows, typed("IN-07", date_mode="text"))]}]),
            {"Bank#0": T("IN-07", rows, outcome=outcome)}, warn=list(warn))
    prec("X41", "15 significant digits: 1234567890123.45 and 999999999999999.00 (Excel-safe)",
         {1: "1234567890123.45", 2: "999999999999999.00"}, "EXACT")
    prec("X42", "16 significant digits, decimal: 12345678901234.56", {1: "12345678901234.56"}, "GATE_BLOCKED",
         ["PRECISION_EXCEEDS_15_DIGITS"])
    prec("X43", "16 significant digits, integer: 1000000000000001.00", {1: "1000000000000001.00"}, "GATE_BLOCKED",
         ["PRECISION_EXCEEDS_15_DIGITS"])
    prec("X44", "17 significant digits, integer: 12345678901234567.00 (stored as ...568)", {1: "12345678901234567.00"},
         "GATE_BLOCKED", ["PRECISION_EXCEEDS_15_DIGITS"])
    noise = mutate(c07, "balance_amount", lambda i, v: {1: "2926.33", 2: "98765432109.99"}.get(i, v))
    add("X45", "WRITER NOISE in the stored literal (2926.3299999999999, 98765432109.99001) - safe values, not flagged",
        set_raw_values(workbook([{"name": "Bank", "blocks": [blk(noise, typed("IN-07", date_mode="text"))]}]),
                       {f"{acol}2": "2926.3299999999999", f"{acol}3": "98765432109.99001"}),
        {"Bank#0": T("IN-07", noise)})

    # ---------------- cases that would pass validation silently without the gate
    cents = mutate(c07, "balance_amount", lambda i, v: v[:-2] + "37")
    add("X46", "money as numbers in GENERAL format, every value with 2 non-zero decimals (passes the money pattern)",
        workbook([{"name": "Bank", "blocks": [blk(cents, typed("IN-07", money_fmt="General", date_mode="text"))]}]),
        {"Bank#0": T("IN-07", cents, outcome="GATE_BLOCKED")}, warn=["NUMBER_NO_DECLARED_DECIMALS"])
    pct = mutate(c07, "balance_amount", lambda i, v: "0.12" if i == 1 else v)
    wb = workbook([{"name": "Bank", "blocks": [blk(pct, typed("IN-07", date_mode="text"))]}])
    import openpyxl
    w = openpyxl.load_workbook(io.BytesIO(wb))
    w["Bank"].cell(2, j07 + 1).number_format = "0%"          # 0.12 displayed as 12%
    w["Bank"].cell(2, j07 + 1).value = 0.12
    b = io.BytesIO()
    w.save(b)
    add("X47", "PERCENT format on a money cell (0.12 shown as 12%; '0.12' would pass the money pattern)",
        b.getvalue(), {"Bank#0": T("IN-07", pct, outcome="GATE_BLOCKED")}, warn=["PERCENT_FORMAT"])
    jr = c07[0].index("bank_statement_ref")
    rcol = chr(65 + jr)
    boolv = mutate(c07, "bank_statement_ref", lambda i, v: "true" if i == 1 else v)
    add("X48", "Excel BOOLEAN in the optional free-text bank_statement_ref",
        workbook([{"name": "Bank", "blocks": [blk(c07, typed("IN-07", date_mode="text"))], "extra_cells": {f"{rcol}2": True}}]),
        {"Bank#0": T("IN-07", boolv, outcome="GATE_BLOCKED")}, warn=["BOOLEAN_CELL"])
    errv = mutate(c07, "bank_statement_ref", lambda i, v: "#N/A" if i == 1 else v)
    add("X49", "ERROR cell #N/A in the optional free-text bank_statement_ref (a string field accepts it)",
        workbook([{"name": "Bank", "blocks": [blk(c07, typed("IN-07", date_mode="text"))], "extra_cells": {f"{rcol}2": "#N/A"}}]),
        {"Bank#0": T("IN-07", errv, outcome="GATE_BLOCKED")}, warn=["CELL_ERROR"])
    jc = c02[0].index("close_date")
    ccol = chr(65 + jc)
    row_empty = next(i for i, r in enumerate(c02[1:], start=1) if r[jc] == "")
    add("X50", "FORMULA without a cached value in the optional close_date (truth empty: the result would 'match')",
        workbook([{"name": "Accounts", "blocks": [blk(c02)],
                   "formulas": {f"{ccol}{row_empty + 1}": ("=TODAY()", "yyyy-mm-dd")}}]),
        {"Accounts#0": T("IN-02", outcome="GATE_BLOCKED")}, warn=["FORMULA_NO_CACHED_VALUE"])
    add("X51", "MERGED cells in the optional bank_statement_ref (rows 2-3: row 3's value silently empty)",
        workbook([{"name": "Bank", "blocks": [blk(c07)], "merge": [f"{rcol}2:{rcol}3"]}]),
        {"Bank#0": T("IN-07", outcome="GATE_BLOCKED")}, warn=["MERGED_IN_DATA"])
    dtv = mutate(c07, "bank_statement_ref", lambda i, v: "2026-09-01T09:00:00" if i == 1 else v)
    add("X52", "native DATETIME cell in the free-text bank_statement_ref (no offset; a string field accepts it)",
        workbook([{"name": "Bank", "blocks": [blk(c07)], "extra_cells": {f"{rcol}2": datetime(2026, 9, 1, 9, 0)}}]),
        {"Bank#0": T("IN-07", dtv, outcome="GATE_BLOCKED")}, warn=["DATETIME_NO_OFFSET"])
    tv = mutate(c07, "bank_statement_ref", lambda i, v: "09:30:00" if i == 1 else v)
    add("X53", "TIME-ONLY cell in the free-text bank_statement_ref",
        workbook([{"name": "Bank", "blocks": [blk(c07)], "extra_cells": {f"{rcol}2": time(9, 30)}}]),
        {"Bank#0": T("IN-07", tv, outcome="GATE_BLOCKED")}, warn=["TIME_ONLY_CELL"])
    # ---------------- control: everything right
    ok = mutate(mutate(c10, "ledger_entry_id", lambda i, v: f"{i:07d}"), "payment_reference", lambda i, v: f"00420{i:05d}")
    add("X54", "CONTROL: leading-zero IDs as TEXT + money as numbers with #,##0.00 (must stay EXACT)",
        workbook([{"name": "CashBook", "blocks": [blk(ok, typed("IN-10", date_mode="text"))]}]),
        {"CashBook#0": T("IN-10", ok)})
    return S
