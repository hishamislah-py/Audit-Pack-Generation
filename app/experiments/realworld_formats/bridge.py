"""Experiment C - isolated bridge from an IR table to the EXISTING Smart Parser workflow, plus measurement.

Per table: IR -> CSV bytes (UTF-8, comma, LF) -> MappingOrchestrator.process (content classification, then the
analyst's slot category) in fresh temporary stores -> if HUMAN_REVIEW, a SIMULATED ANALYST resolves it through the
existing review functions (complete_case / complete_session, test-only authority) -> reprocess + 14 handoff checks ->
canonical preview compared with the known truth. Nothing here maps, validates or decides anything itself.

Proposer: TruthStub - a TEST implementation of the existing MappingProposer interface that answers from the scenario's
known mapping (SIMULATED LLM, no network). POC policy: the SHIPPED one (DISABLED) - no auto-accept.
Limitation (as Experiment B): the intake stores the BRIDGED CSV bytes; the original upload's SHA-256 and extractor
identity are carried in the IR and the results, not in the Smart Parser intake (see the report, §13).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

from smartparser.ai.config import AIConfig  # noqa: E402
from smartparser.ai.gateway import ProposalGateway  # noqa: E402
from smartparser.intake.store import EvidenceStore  # noqa: E402
from smartparser.mapping.rule_store import RuleStore  # noqa: E402
from smartparser.orchestration.orchestrator import MappingOrchestrator  # noqa: E402
from smartparser.orchestration.policy import PocAutoAcceptPolicy  # noqa: E402
from smartparser.review import intake as intake_review  # noqa: E402
from smartparser.review.approvals import approve_alias  # noqa: E402
from smartparser.review.audit import AuditLog  # noqa: E402
from smartparser.review.authority import AuthorityPolicy, Reviewer  # noqa: E402
from smartparser.review.session import ReviewContext, approve_proposal, decide_column, open_review  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

REG = SchemaRegistry.from_directory()
TEST_AUTHORITY = AuthorityPolicy.load(HERE / "tests" / "fixtures" / "review" / "test_authority_policy.json")
ANALYST = Reviewer(reviewer_id="sim-analyst", role="analyst", kind="TEST")
OWNER = Reviewer(reviewer_id="sim-data-owner", role="data_owner", kind="TEST")
MONEY = {"amount", "signed"}
TEXTLIKE = {"id", "str", "enum", "ccy"}
from extract import BLOCKING, XLSX_WARNING_POLICY, declared_decimals, warning_code  # noqa: E402
from smartparser.handoff.writer import write_preview  # noqa: E402  (existing writer, used unchanged)


class UnclassifiedWarning(RuntimeError):
    """C1 stop condition: a warning with no policy decision must never be generated and then ignored."""


def xlsx_assert_classified(table, notes=()) -> None:
    """Every cell warning, table warning and workbook note of an XLSX extraction must have a policy decision."""
    for w in list(table.warnings if table is not None else []) + list(notes):
        if warning_code(w) not in XLSX_WARNING_POLICY:
            raise UnclassifiedWarning(f"table warning / note {w!r} has no XLSX policy decision")
    for row in (table.rows if table is not None else []):
        for c in row:
            for w in c.warnings:
                if w not in XLSX_WARNING_POLICY:
                    raise UnclassifiedWarning(f"{w} at {c.locator} has no XLSX policy decision")


def xlsx_gate(table, mapping: dict[int, str], fid: str) -> list[dict]:
    """C1 HARD GATE for XLSX tables, evaluated on the FINAL mapping (source position -> canonical field) produced by the
    existing workflow (deterministic / reviewed / file-specific rule). Every cell of every mapped column is checked:
    HARD_WHEN_MAPPED extractor warnings, plus three rules that need the mapped field type. Returns the findings; an
    empty list means the gate is clear. Unmapped / ignored columns are reported by the extractor, never gated."""
    xlsx_assert_classified(table)
    types = {f.name: f.source_type for f in REG.get(fid).fields}
    hits = []
    for j, fld in sorted(mapping.items()):
        ft = types.get(fld)
        for c in (row[j] for row in table.rows):
            codes = [w for w in c.warnings if XLSX_WARNING_POLICY[w][0] == "HARD_WHEN_MAPPED"]
            if "NUMERIC_CELL" in c.warnings and ft in TEXTLIKE:
                codes.append("NUMERIC_CELL_IN_TEXT_LIKE_COLUMN")
            if "BOOLEAN_CELL" in c.warnings and ft != "bool":
                codes.append("BOOLEAN_CELL_IN_NON_BOOLEAN_COLUMN")
            if "NUMERIC_CELL" in c.warnings and ft in MONEY and declared_decimals(c.number_format) != 2:
                codes.append("MONEY_NUMERIC_WITHOUT_FIXED_DECIMAL_FORMAT")
            for code in codes:
                hits.append({"code": code, "field": fld, "field_type": ft, "locator": c.locator, "text": c.text,
                             "raw": c.raw, "cell_type": c.type, "number_format": c.number_format})
    return hits


def _final_mapping(res) -> dict[int, str]:
    m = getattr(res, "mapping", None) if res is not None else None
    return {x.source_index: x.canonical_field for x in (m.mappings if m else [])}


def _counterfactual_preview(table, mapping: dict[int, str], fid: str) -> bytes:
    """IN MEMORY ONLY: the bytes the existing writer would emit without the gate (canonical order, source cells)."""
    canon = [f.name for f in REG.get(fid).fields]
    by_field = {f: j for j, f in mapping.items()}
    return to_csv([canon] + [[row[by_field[f]].text for f in canon] for row in table.rows])


class TruthStub:
    provider_id = "recorded_stub/experiment-C-truth (SIMULATED - not an LLM)"

    def __init__(self, truth_map: dict[str, str]):
        self.truth, self.calls = truth_map, []

    def propose(self, request):
        self.calls.append([c.source_header for c in request.unresolved_columns])
        names = {f.name for f in request.canonical_fields}
        cols = []
        for c in request.unresolved_columns:
            f = self.truth.get(c.source_header)
            ok = f in names
            cols.append({"source_index": c.source_index, "source_header": c.source_header,
                         "canonical_field": f if ok else "UNMAPPABLE", "assessment": "CLEAR" if ok else "UNMAPPABLE",
                         "alternatives": [], "explanation": "simulated from the scenario's known mapping",
                         "evidence": []})
        return json.dumps({"response_schema": "smartparser-mapping-proposal/1.0", "category": request.category,
                           "notes": "SIMULATED", "columns": cols})


def to_csv(rows: list[list[str]]) -> bytes:
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue().encode("utf-8")


def _dec(s):
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _orch(root: Path, truth_map, aliases=(), previews: bool = True):
    log = AuditLog(root / "audit.jsonl")
    store = RuleStore.initialise(root / "rules", REG)
    for cat, header, fld in aliases:
        approve_alias(cat, header, fld, [OWNER], "experiment C approved alias (test authority)", TEST_AUTHORITY, store,
                      log, "experiment", "test", "low")
    stub = TruthStub(truth_map or {})
    gw = ProposalGateway(proposer=stub, config=AIConfig(enabled=True, provider="recorded_stub"), log=log)
    return MappingOrchestrator(REG, store, EvidenceStore(root / "evidence"), gw, PocAutoAcceptPolicy.load(), log,
                               preview_dir=(root / "pv") if previews else None), stub


def _simulate_review(orch, wr, fid, truth_map) -> dict:
    """The analyst decides from the known truth, through the EXISTING review functions; every refusal is recorded."""
    out = {"mechanism": None, "decisions": [], "refusals": []}
    fields = {f.name for f in REG.get(fid).fields}
    try:
        if wr.intake_case is not None:
            case = wr.intake_case
            out["mechanism"] = f"column_review_case:{case.kind}"
            ctx = orch.case_context(case)
            assigned = set()
            for c in case.columns:
                f = truth_map.get(c.source_header)
                try:
                    if f in fields and f not in assigned:
                        act = "MAP" if c.suggested_field == f else "CHANGE"
                        intake_review.decide(case, act, ANALYST, "simulated analyst (known truth)", TEST_AUTHORITY,
                                             orch.log, ctx, c.source_index, None if act == "MAP" else f)
                        assigned.add(f)
                        out["decisions"].append((c.source_header, act, f))
                    else:
                        intake_review.decide(case, "IGNORE_COLUMN", ANALYST, "not an evidence field / duplicate "
                                             "(simulated analyst)", TEST_AUTHORITY, orch.log, ctx, c.source_index)
                        out["decisions"].append((c.source_header, "IGNORE_COLUMN", None))
                except Exception as exc:
                    out["refusals"].append(f"{c.source_header}: {str(exc)[:160]}")
                    intake_review.decide(case, "LEAVE_UNRESOLVED", ANALYST, "refused by the rules", TEST_AUTHORITY,
                                         orch.log, ctx, c.source_index)
                    out["decisions"].append((c.source_header, "LEAVE_UNRESOLVED", None))
            return out | {"result": orch.complete_case(case, [ANALYST], "simulated analyst review", TEST_AUTHORITY),
                          "case_state": None}
        if wr.review_session is not None:
            s = wr.review_session
            out["mechanism"] = "proposal_session"
            res = wr.initial
            ctx = ReviewContext(wr.proposal.request, REG.get(fid), list(res.csv_extraction.raw_headers),
                                {c.index: list(c.sample_values) for c in res.csv_extraction.columns})
            open_review(s, ANALYST, TEST_AUTHORITY, orch.log)
            for c in s.columns:
                f = truth_map.get(c.source_header)
                try:
                    if f in fields:
                        decide_column(s, c.source_index, "CHANGE", ANALYST, "simulated analyst (known truth)",
                                      TEST_AUTHORITY, orch.log, ctx, final_field=f)
                        out["decisions"].append((c.source_header, "CHANGE", f))
                    else:
                        decide_column(s, c.source_index, "LEAVE_UNMAPPED", ANALYST, "no field (simulated analyst)",
                                      TEST_AUTHORITY, orch.log, ctx)
                        out["decisions"].append((c.source_header, "LEAVE_UNMAPPED", None))
                except Exception as exc:
                    out["refusals"].append(f"{c.source_header}: {str(exc)[:160]}")
            approve_proposal(s, ANALYST, "simulated analyst review", TEST_AUTHORITY, orch.log, ctx)
            return out | {"result": orch.complete_session(s, [ANALYST], "simulated analyst review", TEST_AUTHORITY)}
    except Exception as exc:
        out["refusals"].append(f"review could not be completed: {type(exc).__name__}: {str(exc)[:200]}")
    return out | {"result": None}


def _fidelity(table, truth_rows, truth_map, fid) -> dict:
    types = {f.name: f.source_type for f in REG.get(fid).fields}
    ci = {n: k for k, n in enumerate(truth_rows[0])}
    st = {"cells": 0, "exact": 0, "money_cells": 0, "money_exact": 0, "money_numeric_equal": 0,
          "date_ts_cells": 0, "date_ts_exact": 0, "examples": []}
    seen = set()
    for j, h in enumerate(table.header):
        f = truth_map.get(h)
        if f is None or f in seen or f not in ci:
            continue
        seen.add(f)
        for i, row in enumerate(table.rows[:len(truth_rows) - 1]):
            got, want = row[j].text, truth_rows[i + 1][ci[f]]
            ok = got == want
            st["cells"] += 1
            st["exact"] += ok
            if types[f] in MONEY:
                st["money_cells"] += 1
                st["money_exact"] += ok
                st["money_numeric_equal"] += (got == want) or (_dec(got) is not None and _dec(got) == _dec(want))
            if types[f] in ("date", "ts"):
                st["date_ts_cells"] += 1
                st["date_ts_exact"] += ok
            if not ok and len(st["examples"]) < 4:
                c = row[j]
                st["examples"].append({"field": f, "type": types[f], "got": got, "want": want, "source": c.source,
                                       "cell_type": c.type, "number_format": c.number_format, "at": c.locator,
                                       "warnings": c.warnings})
    return st


def evaluate_table(table, work: Path, name: str, truth: dict | None, source_format: str | None = None) -> dict:
    xlsx = source_format == "xlsx"        # C1: the hard gate applies to XLSX tables only (JSON path unchanged)
    if xlsx:
        xlsx_assert_classified(table)      # also for tables that are not evidence tables
    data = to_csv([table.header] + table.text_rows())
    root = work / name
    root.mkdir(parents=True)
    tm = (truth or {}).get("map", {})
    orch, stub = _orch(root / "content", tm, previews=not xlsx)     # C1: no XLSX preview is written before the gate
    content = orch.process(data, f"{name}.csv", "2026-09")
    r = {"table": table.table_id, "columns": len(table.header), "rows": len(table.rows),
         "bridged_csv_sha256": hashlib.sha256(data).hexdigest(), "ir_warnings": table.warning_counts(),
         "ir_blocking": table.blocking(), "table_warnings": table.warnings[:12],
         "content_classification": content.category if content.decision.value == "DETERMINISTIC" else None,
         "provenance": {"row_locators": len(table.row_locators) == len(table.rows),
                        "column_locators": len(table.column_locators) == len(table.header),
                        "cell_locators": all(c.locator for row in table.rows for c in row),
                        "sample": table.rows[0][0].locator if table.rows else None}}
    if truth is None:
        r["outcome"] = "NOT_EVIDENCE_TABLE"
        return r
    fid = truth["fid"]
    orch, stub = _orch(root / "slot", tm, truth.get("aliases", ()), previews=not xlsx)
    wr = orch.process(data, f"{name}.csv", "2026-09", category=fid)
    expected = to_csv(truth["rows"])
    r.update(category=fid, route=wr.route, decision=wr.decision.value,
             review_kind=wr.intake_case.kind if wr.intake_case else ("PROPOSAL_REVIEW" if wr.review_session else None),
             simulated_proposals=len(stub.calls), headers_to_proposer=stub.calls[0] if stub.calls else [],
             eligible=bool(wr.eligibility and wr.eligibility.eligible),
             failed_checks=[c.check_id for c in wr.eligibility.failed] if wr.eligibility else None,
             checks_run=len(wr.eligibility.checks) if wr.eligibility else 0,
             preview_sha256=wr.preview["output_sha256"] if wr.preview else None,
             preview_exact=(wr.preview["csv"].read_bytes() == expected) if wr.preview else None,
             fidelity=_fidelity(table, truth["rows"], tm, fid))
    # experiment-level safeguard (proposed for integration): a NUMERIC cell feeding a text-like field (id/str/enum/ccy)
    types = {f.name: f.source_type for f in REG.get(fid).fields}
    hits = sum(1 for j, h in enumerate(table.header) if types.get(tm.get(h)) in TEXTLIKE
               for row in table.rows if "NUMERIC_CELL" in row[j].warnings)
    if hits:
        r["ir_blocking"] = sorted(set(r["ir_blocking"]) | {"NUMERIC_CELL_IN_TEXT_LIKE_COLUMN"})
        r["numeric_cells_in_text_like_columns"] = hits
    final = wr
    if wr.decision.value == "HUMAN_REVIEW" and wr.route != "HEADER_COUNT_GATE" or (
            wr.route == "HEADER_COUNT_GATE" and wr.intake_case.count_difference > 0):
        rv = _simulate_review(orch, wr, fid, tm)
        final = rv.pop("result")
        r["review"] = {"mechanism": rv["mechanism"], "decisions": rv["decisions"], "refusals": rv["refusals"]}
        if final is not None:
            r["review"].update(route=final.route, eligible=bool(final.eligibility and final.eligibility.eligible),
                               failed_checks=[c.check_id for c in final.eligibility.failed] if final.eligibility else None,
                               checks_run=len(final.eligibility.checks) if final.eligibility else 0,
                               preview_sha256=final.preview["output_sha256"] if final.preview else None,
                               preview_exact=(final.preview["csv"].read_bytes() == expected) if final.preview else None,
                               reprocess_provider_calls=final.reprocessed.provider_calls if final.reprocessed else None)
    gate_blocked = False
    if xlsx:
        # C1: the existing workflow ran WITHOUT writing a preview. If it says eligible, the XLSX hard gate decides on
        # the FINAL mapping; only a clear gate lets the existing writer produce the canonical preview.
        pipeline_eligible = bool(final is not None and final.eligibility and final.eligibility.eligible
                                 and final.reprocessed is not None)
        mapping = _final_mapping(final.reprocessed.result) if pipeline_eligible else _final_mapping(
            wr.initial) if wr.initial is not None else {}
        findings = xlsx_gate(table, mapping, fid)      # also checks every code is classified, even with no mapping
        g = {"evaluated_on": "final mapping (pipeline eligible)" if pipeline_eligible else
             "deterministic mapping (report only: the existing workflow already refused)",
             "mapped_columns": len(mapping), "clear": not findings,
             "findings": dict(sorted({k: sum(1 for h in findings if h["code"] == k)
                                      for k in {h["code"] for h in findings}}.items())),
             "samples": findings[:5]}
        if pipeline_eligible:
            g["counterfactual_without_gate_equals_truth"] = _counterfactual_preview(table, mapping, fid) == expected
            if findings:
                gate_blocked = True
            else:
                final.preview = write_preview(final.reprocessed, final.eligibility, REG, root / "pv" / final.intake_id)
            if "review" in r:
                r["review"].update(preview_sha256=final.preview["output_sha256"] if final.preview else None,
                                   preview_exact=(final.preview["csv"].read_bytes() == expected) if final.preview else None)
            else:
                r.update(preview_sha256=final.preview["output_sha256"] if final.preview else None,
                         preview_exact=(final.preview["csv"].read_bytes() == expected) if final.preview else None)
        # C1 evidence: preview files that exist on disk for this table (must be 0 unless the gate was clear)
        g["preview_files_on_disk"] = sum(1 for f in root.rglob("*.csv") if f.name.startswith("PREVIEW"))
        r["xlsx_gate"] = g
    elig = bool(final is not None and final.eligibility and final.eligibility.eligible and final.preview)
    exact = bool(elig and final.preview["csv"].read_bytes() == expected)
    if wr.route == "HEADER_COUNT_GATE" and wr.intake_case.count_difference < 0:
        cls = "RESUBMISSION"
    elif "review" in r:
        cls = "REVIEW->" + ("GATE_BLOCKED" if gate_blocked else "EXACT" if exact else "SILENT_DIFFERENCE" if elig
                            else "HELD_OR_BLOCKED")
    else:
        cls = "GATE_BLOCKED" if gate_blocked else "EXACT" if exact else "SILENT_DIFFERENCE" if elig else "BLOCKED"
    r["outcome"] = cls
    if elig and not exact:
        got = list(csv.reader(io.StringIO(final.preview["csv"].read_text(encoding="utf-8"))))
        r["silent_differences"] = [{"row": i, "field": truth["rows"][0][j], "got": g, "want": w}
                                   for i, (gr, wrow) in enumerate(zip(got[1:], truth["rows"][1:]), start=2)
                                   for j, (g, w) in enumerate(zip(gr, wrow)) if g != w][:6]
        r["caught_by_proposed_safeguard"] = bool(r["ir_blocking"])
    r["reproducibility_digest"] = hashlib.sha256(json.dumps(
        {k: r.get(k) for k in ("table", "bridged_csv_sha256", "ir_warnings", "content_classification", "route",
                                "decision", "eligible", "failed_checks", "preview_sha256", "outcome")} |
        ({"xlsx_gate": r["xlsx_gate"]} if "xlsx_gate" in r else {}) |
        {"review": {k: r.get("review", {}).get(k) for k in ("decisions", "route", "eligible", "preview_sha256")}},
        sort_keys=True, default=str).encode()).hexdigest()
    return r
