"""Experiment B - multi-format ingestion feasibility (XLSX, JSON, DOCX, TXT, Markdown). ISOLATED experiment.

    py -3.11 experiments/multiformat/run_experiment.py --out <dir>

For every scenario: generate a synthetic input from the canonical UC-042 fixture tables (known truth) -> extract it with
experiments/multiformat/extractors.py into the common IR -> TABLES are bridged to CSV bytes and given UNCHANGED to the
existing MappingOrchestrator (gate, deterministic mapping, proposal when eligible, validation, policy / review,
reprocess, 14-point handoff, preview); DOCUMENTS are given to the EXISTING PDF label classifier (classify_pdf) as text.
Measured separately: extraction (structure found), value fidelity vs truth (all cells / money / dates), mapping
(deterministic coverage, route), validation + handoff eligibility, provenance completeness, review requirement.

The proposer, when a proposal is eligible, is TruthStub: a TEST implementation of the existing MappingProposer
interface that answers from the generator's known mapping (SIMULATED LLM, no network). The POC policy is the SHIPPED
one (DISABLED), so any proposal ends in human review - production auto-accept is never enabled. Nothing is submitted.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from extractors import ExtractedTable, extract  # noqa: E402
from smartparser.ai.config import AIConfig  # noqa: E402
from smartparser.ai.gateway import ProposalGateway  # noqa: E402
from smartparser.classify.pdf_classifier import classify_pdf, letter_refs_from_inventory  # noqa: E402
from smartparser.intake.store import EvidenceStore  # noqa: E402
from smartparser.mapping.rule_store import RuleStore  # noqa: E402
from smartparser.orchestration.orchestrator import MappingOrchestrator  # noqa: E402
from smartparser.orchestration.policy import PocAutoAcceptPolicy  # noqa: E402
from smartparser.pdf_engine import PdfExtraction, extract_pdf  # noqa: E402
from smartparser.review.audit import AuditLog  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

SEP = HERE / "tests" / "fixtures" / "uc042_canonical" / "PER-2026-09_set_01_clean_baseline"
REG = SchemaRegistry.from_directory()
MONEY = {"amount", "signed"}


def _files():
    with open(SEP / "manifest.csv", encoding="utf-8", newline="") as f:
        out = {}
        for r in csv.DictReader(f):
            out.setdefault(r["file_id"], SEP / r["relative_path"])
    return out


FILES = _files()


def table(fid):
    return list(csv.reader(io.StringIO(FILES[fid].read_bytes().decode("utf-8"))))


def types(fid):
    return {f.name: f.source_type for f in REG.get(fid).fields}


class TruthStub:
    """TEST implementation of MappingProposer (SIMULATED LLM): answers each unresolved header from the generator's
    known mapping, assessment CLEAR; headers it does not know -> UNMAPPABLE. No network."""
    provider_id = "recorded_stub/experiment-truth (SIMULATED - not an LLM)"

    def __init__(self, truth: dict[str, str]):
        self.truth, self.calls = truth, []

    def propose(self, request):
        self.calls.append([c.source_header for c in request.unresolved_columns])
        cols = [{"source_index": c.source_index, "source_header": c.source_header,
                 "canonical_field": self.truth.get(c.source_header, "UNMAPPABLE"),
                 "assessment": "CLEAR" if c.source_header in self.truth else "UNMAPPABLE", "alternatives": [],
                 "explanation": "simulated from the generator's known mapping", "evidence": []}
                for c in request.unresolved_columns]
        return json.dumps({"response_schema": "smartparser-mapping-proposal/1.0", "category": request.category,
                           "notes": "SIMULATED", "columns": cols})


# ================================================================================================ input generation
def xlsx_bytes(sheets: list[dict]) -> bytes:
    """sheets: [{name, fid, header (source headers), mode: text|typed|typed_ts_text, title?, blank_rows?}]"""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sh in sheets:
        ws = wb.create_sheet(sh["name"])
        r0 = 1
        if sh.get("title"):
            ws.cell(1, 1, sh["title"])
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
            r0 = 3                                   # title, blank row, header
        if sh.get("rows") is not None:               # free-form (non-evidence) sheet
            for i, row in enumerate(sh["rows"]):
                for j, v in enumerate(row):
                    ws.cell(r0 + i, j + 1, v)
            continue
        canon = table(sh["fid"])
        t = types(sh["fid"])
        for j, h in enumerate(sh["header"]):
            ws.cell(r0, j + 1, h)
        for i, row in enumerate(canon[1:]):
            for j, (name, v) in enumerate(zip(canon[0], row)):
                c = ws.cell(r0 + 1 + i, j + 1)
                mode, st = sh.get("mode", "text"), t[name]
                if mode == "text" or v == "":
                    c.value = v
                elif st in MONEY:
                    c.value, c.number_format = float(v), "#,##0.00"
                elif st == "date":
                    c.value, c.number_format = date.fromisoformat(v), "yyyy-mm-dd"
                elif st == "ts" and mode == "typed":
                    c.value = datetime.fromisoformat(v).replace(tzinfo=None)   # Excel cannot store an offset
                    c.number_format = "yyyy-mm-dd hh:mm:ss"
                elif st == "int":
                    c.value = int(v)
                else:
                    c.value = v
        for k in range(sh.get("blank_rows", 0)):
            ws.cell(r0 + len(canon) + k + 2, 1, None)
            ws.cell(r0 + len(canon) + k + 2, 2, " ")                # whitespace-only trailing rows
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def json_bytes(arrays: dict[str, tuple], numbers: str = "string", nest: dict | None = None,
               drop_key: tuple | None = None, extra_key: str | None = None) -> bytes:
    """arrays: {json key or '' for a top-level array: (fid, rename)}; numbers 'string' | 'producer' (JSON numbers as a
    typical producer writes them: 250000.0 / 2926.33); nest: {field: 'a.b'} nesting; drop_key (field, every_n)."""
    def lit(v, st):
        if numbers == "producer" and v != "" and st in MONEY:
            d = Decimal(v)
            return repr(float(d))                 # e.g. 250000.0, 2926.33
        if numbers == "producer" and v != "" and st == "int":
            return v
        return json.dumps(v)

    def obj(fid, rename, row, i):
        t = types(fid)
        parts = {}
        for name, v in zip(table(fid)[0], row):
            if drop_key and name == drop_key[0] and i % drop_key[1] == 0:
                continue
            key = (nest or {}).get(name, rename.get(name, name))
            cur = parts
            ks = key.split(".")
            for k in ks[:-1]:
                cur = cur.setdefault(k, {})
            cur[ks[-1]] = lit(v, t[name])
        if extra_key:
            parts[extra_key] = json.dumps("note")

        def ser(d):
            return "{" + ", ".join(f"{json.dumps(k)}: {ser(v) if isinstance(v, dict) else v}" for k, v in d.items()) + "}"
        return ser(parts)

    chunks = []
    for key, (fid, rename) in arrays.items():
        recs = ",\n  ".join(obj(fid, rename, r, i) for i, r in enumerate(table(fid)[1:]))
        chunks.append((key, f"[\n  {recs}\n]"))
    if len(chunks) == 1 and chunks[0][0] == "":
        return chunks[0][1].encode()
    return ("{\n" + ",\n".join(f"{json.dumps(k)}: {v}" for k, v in chunks) + "\n}").encode()


def docx_bytes(heading: str, tables: list[tuple] = (), paragraphs: list[str] = (), multiline_cell=False) -> bytes:
    import docx
    d = docx.Document()
    d.add_heading(heading, level=1)
    for p in paragraphs:
        d.add_paragraph(p)
    for fid, rename in tables:
        rows = table(fid)
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                t.cell(i, j).text = rename.get(v, v) if i == 0 else v
        if multiline_cell:
            t.cell(1, len(rows[0]) - 1).text = rows[1][-1] + "\n(continued)"
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def md_table(fid, rename=None) -> str:
    rows = table(fid)
    rename = rename or {}
    h = [rename.get(c, c) for c in rows[0]]
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    return "\n".join(["| " + " | ".join(h) + " |", "|" + "|".join("---" for _ in h) + "|"] +
                     ["| " + " | ".join(esc(v) for v in r) + " |" for r in rows[1:]])


def pdf_text(fid) -> str:
    return extract_pdf(FILES[fid].read_bytes()).text


# ================================================================================================ evaluation
def bridge(t: ExtractedTable) -> tuple[bytes, dict]:
    """IR table -> the CSV the existing pipeline accepts (UTF-8, comma, LF, header on line 1) + a provenance map
    (CSV line -> source row locator; CSV column -> source column locator)."""
    b = io.StringIO()
    w = csv.writer(b, lineterminator="\n")
    w.writerow(t.header)
    w.writerows(t.rows)
    prov = {"table": t.locator, "rows": {str(i + 2): loc for i, loc in enumerate(t.row_locators)},
            "columns": dict(zip(t.header, t.column_locators))}
    return b.getvalue().encode("utf-8"), prov


def _dec(s):
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def fidelity(t: ExtractedTable, fid: str, truth_map: dict[str, str]) -> dict:
    """Extracted cell text vs the canonical fixture text, per canonical field the source column is known to carry."""
    canon = table(fid)
    ci = {n: k for k, n in enumerate(canon[0])}
    ty = types(fid)
    stats = {"cells": 0, "exact": 0, "money_cells": 0, "money_exact": 0, "money_value_equal": 0,
             "date_ts_cells": 0, "date_ts_exact": 0, "examples": []}
    for j, h in enumerate(t.header):
        fld = truth_map.get(h)
        if fld is None:
            continue
        for i, row in enumerate(t.rows[:len(canon) - 1]):
            got, want = row[j], canon[i + 1][ci[fld]]
            ok = got == want
            stats["cells"] += 1
            stats["exact"] += ok
            if ty[fld] in MONEY:
                stats["money_cells"] += 1
                stats["money_exact"] += ok
                stats["money_value_equal"] += (_dec(got) is not None and _dec(got) == _dec(want)) or (got == want == "")
            if ty[fld] in ("date", "ts"):
                stats["date_ts_cells"] += 1
                stats["date_ts_exact"] += ok
            if not ok and len(stats["examples"]) < 4:
                stats["examples"].append({"field": fld, "type": ty[fld], "got": got, "want": want,
                                          "at": t.row_locators[i]})
    return stats


def run_table(work: Path, t: ExtractedTable, fid: str, truth_map: dict[str, str], name: str) -> dict:
    data, prov = bridge(t)
    root = work / name
    root.mkdir(parents=True)
    log = AuditLog(root / "audit.jsonl")
    stub = TruthStub(truth_map)
    gw = ProposalGateway(proposer=stub, config=AIConfig(enabled=True, provider="recorded_stub"), log=log)
    orch = MappingOrchestrator(REG, RuleStore.initialise(root / "rules", REG), EvidenceStore(root / "evidence"), gw,
                               PocAutoAcceptPolicy.load(), log, preview_dir=root / "pv")      # SHIPPED policy (DISABLED)
    content = orch.process(data, f"{name}.csv", "2026-09")                                   # content classification
    wr = orch.process(data, f"{name}.csv", "2026-09", category=fid)                          # analyst's slot
    det = {}
    if wr.initial is not None and wr.initial.mapping is not None and wr.initial.mapping.mappings:
        det = {m.original_header: m.canonical_field for m in wr.initial.mapping.mappings}
    elif wr.resolved_columns:
        det = dict(wr.resolved_columns)
    nfields = len(REG.get(fid).fields)
    preview_ok = None
    if wr.preview:
        preview_ok = wr.preview["csv"].read_bytes() == FILES[fid].read_bytes()
    fid_stats = fidelity(t, fid, truth_map)
    return {"table": t.locator, "category": fid, "columns": len(t.header), "rows": len(t.rows),
            "expected_rows": len(table(fid)) - 1, "warnings": t.warnings,
            "content_classification": content.category if content.decision.value == "DETERMINISTIC" else None,
            "route": wr.route, "decision": wr.decision.value,
            "review_kind": wr.intake_case.kind if wr.intake_case else ("PROPOSAL_REVIEW" if wr.review_session else None),
            "llm_proposals_requested": len(stub.calls), "headers_sent_to_proposer": stub.calls[:1],
            "deterministic_fields": len(det), "canonical_fields": nfields,
            "deterministic_coverage": round(len(det) / nfields, 3),
            "eligible": bool(wr.eligibility and wr.eligibility.eligible),
            "failed_checks": [c.check_id for c in wr.eligibility.failed] if wr.eligibility else None,
            "preview_equals_canonical": preview_ok,
            "fidelity": fid_stats,
            "provenance": {"rows_with_locator": len(prov["rows"]), "columns_with_locator": len(prov["columns"]),
                           "complete": len(prov["rows"]) == len(t.rows) and len(prov["columns"]) == len(t.header),
                           "sample": {"first_row": next(iter(prov["rows"].items()), None),
                                      "first_column": next(iter(prov["columns"].items()), None)}}}


def run_document(doc, expect: str, refs) -> dict:
    ext = PdfExtraction(page_count=1, page_texts=[doc.text], image_count=0)
    res = classify_pdf(ext, REG, refs)
    return {"document": doc.locator, "expected_category": expect, "category": res.category,
            "status": res.status.value, "correct": res.category == expect, "labels_found": len(
                res.details.get("labels_found", {})), "reason": res.reason[:200], "warnings": res.warnings,
            "key_values_extracted": len(doc.key_values), "headings": doc.headings[:3]}


# ================================================================================================ scenarios
def scenarios():
    c10, c03, c11, c07 = table("IN-10")[0], table("IN-03")[0], table("IN-11")[0], table("IN-07")[0]
    ident = lambda fid: {c: c for c in table(fid)[0]}  # noqa: E731
    friendly10 = {"ledger_entry_id": "Ledger entry ID", "account_id": "Account ID", "posted_ts": "Posted at",
                  "entry_type": "Entry type", "amount": "Amount", "dc_indicator": "Debit/Credit", "currency": "Currency",
                  "payment_reference": "Payment reference"}
    nest10 = {"ledger_entry_id": "entry.id", "account_id": "account.id", "posted_ts": "posted.ts",
              "entry_type": "entry.type", "amount": "money.amount", "dc_indicator": "money.dc",
              "currency": "money.currency", "payment_reference": "reference"}
    S = []
    # ---------------- XLSX
    S.append(("X1", "xlsx", "3 sheets (IN-10, IN-03, IN-11), canonical headers, values stored as TEXT",
              xlsx_bytes([{"name": "CashBook", "fid": "IN-10", "header": c10},
                          {"name": "Balances", "fid": "IN-03", "header": c03},
                          {"name": "Transactions", "fid": "IN-11", "header": c11}]), {},
              {"tables": {"sheet:CashBook": ("IN-10", ident("IN-10")), "sheet:Balances": ("IN-03", ident("IN-03")),
                          "sheet:Transactions": ("IN-11", ident("IN-11"))}}))
    typed = [{"name": "CashBook", "fid": "IN-10", "header": c10, "mode": "typed"},
             {"name": "Balances", "fid": "IN-03", "header": c03, "mode": "typed"}]
    exp_typed = {"tables": {"sheet:CashBook": ("IN-10", ident("IN-10")), "sheet:Balances": ("IN-03", ident("IN-03"))}}
    S.append(("X2", "xlsx", "TYPED cells (money = numbers formatted #,##0.00, dates = date cells, timestamps = datetime "
                            "cells) read NAIVELY (str(value))", xlsx_bytes(typed), {"policy": "naive"}, exp_typed))
    S.append(("X3", "xlsx", "TYPED cells read FORMAT-AWARE (number format + ISO dates); timestamps are Excel datetimes "
                            "(no UTC offset possible)", xlsx_bytes(typed), {"policy": "format_aware"}, exp_typed))
    S.append(("X4", "xlsx", "typed money/dates but timestamps exported as TEXT with offsets (format-aware)",
              xlsx_bytes([dict(s, mode="typed_ts_text") for s in typed]), {"policy": "format_aware"}, exp_typed))
    S.append(("X5", "xlsx", "messy layout: merged title row + blank row above the header, whitespace-only trailing "
                            "rows; plus a free-form 'Notes' sheet",
              xlsx_bytes([{"name": "CashBook", "fid": "IN-10", "header": c10, "title": "Cash book export Sep 2026",
                           "blank_rows": 3},
                          {"name": "Notes", "rows": [["Prepared by", "Ops"], ["Checked", "yes"]]}]), {},
              {"tables": {"sheet:CashBook": ("IN-10", ident("IN-10"))}}))
    S.append(("X6", "xlsx", "friendly column labels (e.g. 'Ledger entry ID', 'Debit/Credit') - same count",
              xlsx_bytes([{"name": "CashBook", "fid": "IN-10", "header": [friendly10[c] for c in c10]}]), {},
              {"tables": {"sheet:CashBook": ("IN-10", {v: k for k, v in friendly10.items()})}}))
    # ---------------- JSON
    S.append(("J1", "json", "top-level array of flat records, canonical keys, all values as JSON strings",
              json_bytes({"": ("IN-10", {})}), {}, {"tables": {"json:$": ("IN-10", ident("IN-10"))}}))
    S.append(("J2", "json", "producer-style JSON numbers for money (250000.0, 2926.33)",
              json_bytes({"": ("IN-10", {})}, numbers="producer"), {}, {"tables": {"json:$": ("IN-10", ident("IN-10"))}}))
    S.append(("J3", "json", "NESTED objects (entry.id, account.id, money.amount, money.dc, ...) - same field count",
              json_bytes({"": ("IN-10", {})}, nest=nest10), {},
              {"tables": {"json:$": ("IN-10", {v: k for k, v in nest10.items()})}}))
    S.append(("J4", "json", "key missing in every 5th record + an extra 'comment' key in every record",
              json_bytes({"": ("IN-10", {})}, drop_key=("payment_reference", 5), extra_key="comment"), {},
              {"tables": {"json:$": ("IN-10", ident("IN-10"))}}))
    S.append(("J5", "json", "one object with two record arrays (cash_book = IN-10, balances = IN-03)",
              json_bytes({"cash_book": ("IN-10", {}), "balances": ("IN-03", {})}), {},
              {"tables": {"json:$.cash_book": ("IN-10", ident("IN-10")), "json:$.balances": ("IN-03", ident("IN-03"))}}))
    # ---------------- DOCX
    S.append(("D1", "docx", "heading + one table (IN-07 bank balance confirmations), canonical headers",
              docx_bytes("Bank balance confirmations", [("IN-07", {})]), {},
              {"tables": {"docx:table[0]": ("IN-07", ident("IN-07"))}}))
    S.append(("D2", "docx", "table with a multi-line cell (IN-07)",
              docx_bytes("Bank balance confirmations", [("IN-07", {})], multiline_cell=True), {},
              {"tables": {"docx:table[0]": ("IN-07", ident("IN-07"))}}))
    S.append(("D3", "docx", "acknowledgement letter (IN-15) as paragraphs (text taken from the fixture PDF)",
              docx_bytes("Acknowledgement letter", paragraphs=pdf_text("IN-15").splitlines()), {},
              {"documents": {"docx:body": "IN-15"}}))
    S.append(("D4", "docx", "safeguarding reconciliation policy (IN-17) as paragraphs",
              docx_bytes("Policy", paragraphs=pdf_text("IN-17").splitlines()), {},
              {"documents": {"docx:body": "IN-17"}}))
    # ---------------- Markdown / TXT
    S.append(("M1", "md", "Markdown pipe table (IN-07) under a heading",
              ("# Bank balance confirmations\n\n" + md_table("IN-07") + "\n").encode(), {},
              {"tables": {"md:table[0]": ("IN-07", ident("IN-07"))}}))
    S.append(("M2", "md", "acknowledgement letter (IN-16) as Markdown with **Label:** value lines",
              ("# Acknowledgement letter\n\n" + "\n".join(
                  f"- **{l.split(':', 1)[0]}:** {l.split(':', 1)[1].strip()}" if ":" in l else l
                  for l in pdf_text("IN-16").splitlines()) + "\n").encode(), {},
              {"documents": {"md:body": "IN-16"}}))
    S.append(("T1", "txt", "monthly return receipt (IN-19) as plain-text key: value lines",
              pdf_text("IN-19").encode(), {}, {"documents": {"txt:body": "IN-19"}}))
    S.append(("T2", "txt", "prose with the same facts but no labels / table (unstructured)",
              b"The cash book for September 2026 shows an opening balance of 250000.00 GBP on account SGA-GBP-01, "
              b"followed by several bank loads during the month.\n", {}, {"documents": {"txt:body": None}}))
    return S


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "inputs").mkdir(parents=True)
    work = out / "work"
    inv = table("IN-02")
    refs = letter_refs_from_inventory([dict(zip(inv[0], r)) for r in inv[1:]], REG)
    results = []
    for sid, fmt, desc, data, kw, expect in scenarios():
        (out / "inputs" / f"{sid}.{fmt}").write_bytes(data)
        r = {"scenario": sid, "format": fmt, "description": desc, "input": f"inputs/{sid}.{fmt}",
             "input_bytes": len(data), "tables": [], "documents": []}
        try:
            ex = extract(data, fmt, **kw)
        except Exception as exc:
            r["extraction_error"] = f"{type(exc).__name__}: {exc}"
            results.append(r)
            continue
        r["extraction_notes"] = ex.notes
        r["tables_found"] = [t.locator for t in ex.tables]
        r["documents_found"] = [d.locator for d in ex.documents]
        for t in ex.tables:
            if t.locator in expect.get("tables", {}):
                fid, tmap = expect["tables"][t.locator]
                r["tables"].append(run_table(work, t, fid, tmap, f"{sid}_{t.locator.replace(':', '_').replace('$', 'r').replace('[', '').replace(']', '').replace('.', '_')}"))
            else:
                r["tables"].append({"table": t.locator, "category": None, "columns": len(t.header),
                                    "rows": len(t.rows), "note": "not an expected evidence table (reported, not mapped)"})
        for d in ex.documents:
            if d.locator in expect.get("documents", {}):
                r["documents"].append(run_document(d, expect["documents"][d.locator], refs))
        r["expected_tables"] = sorted(expect.get("tables", {}))
        r["expected_documents"] = sorted(expect.get("documents", {}))
        results.append(r)
        print(sid, fmt, "tables", [(x.get("table"), x.get("decision"), x.get("eligible")) for x in r["tables"]],
              "docs", [(x["document"], x["category"], x["correct"]) for x in r["documents"]], flush=True)
    shutil.rmtree(work, ignore_errors=True)        # stores are disposable; results keep everything measured
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
