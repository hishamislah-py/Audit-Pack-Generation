"""Phase 3B-6 (updated 3B-7) - evaluation of the orchestrated workflow (extends tools/eval_3b5.py; synthetic, offline, recorded stub).

    py -3.11 tools/eval_3b6.py build [--out corpus/phase3b6_eval]
    py -3.11 tools/eval_3b6.py run   [--corpus corpus/phase3b6_eval] [--out <dir>]

Each case defines: input (supplied) category, incoming headers, expected deterministic mappings, expected unresolved
headers, the recorded response (if any), expected validation classes, expected final decision and the expected canonical
output (SHA-256 of the canonical UC-042 source file, or none). Metrics are reported in three SEPARATE groups:
deterministic mapping, proposal quality (SIMULATED - recorded responses, not a model), end-to-end workflow.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import eval_3b5 as base  # noqa: E402  (extends the 3B-5 framework)

POLICY_ON = HERE / "tests" / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
AUTO10 = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt"}
AUTO02 = {"account_id": "acct_id", "institution_full_name": "bank_name"}



O2_NOTE = 'owner decision O2 (approved 19 Nov 2026): a case/whitespace variant or an alias is never recognised automatically at intake; the category is still established deterministically and the file goes to a HEADER_VARIANT column review (no LLM call, no preview until the analyst confirms)'

def build(out: Path) -> list[dict]:
    files = base._files()
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / "recorded").mkdir()
    cases = []

    def sha(fid):
        return hashlib.sha256(files[fid].read_bytes()).hexdigest()

    def case(cid, ctype, rows_or_bytes, truth_cat, supplied, decision, *, recorded=None, ai="stub", setup=None,
             det_map=None, unresolved=None, classes=None, output=None, truth=None, note=""):
        data = rows_or_bytes if isinstance(rows_or_bytes, bytes) else base._dump(rows_or_bytes)
        (out / "data" / f"{cid}.csv").write_bytes(data)
        rec = None
        if recorded is not None:
            rec = f"{cid}.json"
            (out / "recorded" / rec).write_text(json.dumps(recorded, indent=1), encoding="utf-8")
        headers = next(csv.reader([data.decode("utf-8").splitlines()[0]]))
        cases.append({"case_id": cid, "case_type": ctype, "data_file": f"data/{cid}.csv",
                      "data_sha256": hashlib.sha256(data).hexdigest(), "input_category": supplied,
                      "truth_category": truth_cat, "incoming_headers": headers, "recorded_response": rec, "ai": ai,
                      "setup": setup or {},
                      "expected": {"deterministic_mappings": det_map or {}, "unresolved": unresolved or [],
                                   "classes": classes or {}, "decision": decision, "canonical_output_sha256": output},
                      "truth_mapping": truth or {}, "ground_truth_source": base.GT, "note": note})

    for fid in ("IN-02", "IN-07", "IN-09", "IN-10", "IN-13"):
        rows = base._table(files[fid])
        ident = {c: c for c in rows[0]}
        case(f"{fid}_canonical", "canonical", files[fid].read_bytes(), fid, None, "DETERMINISTIC", det_map=ident,
             output=sha(fid))
        case(f"{fid}_reordered", "reordered", [list(reversed(r)) for r in rows], fid, None, "DETERMINISTIC",
             det_map=ident, output=sha(fid))
        case(f"{fid}_case_ws", "case_whitespace", [[f" {c.upper()} " for c in rows[0]]] + rows[1:], fid, None,
             "HUMAN_REVIEW", det_map={f" {c.upper()} ": c for c in rows[0]}, output=None, note=O2_NOTE)
    in11 = base._table(files["IN-11"])
    case("alias_approved", "approved_alias", [["Txn ID"] + in11[0][1:]] + in11[1:], "IN-11", None, "HUMAN_REVIEW",
         setup={"approve_alias": ["IN-11", "Txn ID", "txn_id"]}, det_map={"Txn ID": "txn_id"}, output=None,
         note=O2_NOTE)

    def renamed(fid, ren):
        rows = base._table(files[fid])
        return [[ren.get(c, c) for c in rows[0]]] + rows[1:], {ren.get(c, c): c for c in rows[0] if c not in ren}, \
            {v: k for k, v in ren.items()}
    for fid, ren, fx in (("IN-10", AUTO10, "in10_auto_clear"), ("IN-02", AUTO02, "in02_auto_clear")):
        rows, det, truth = renamed(fid, ren)
        case(f"{fid}_unfamiliar_clear", "unfamiliar_clear", rows, fid, fid, "AUTO_ACCEPT", recorded=base._recorded(fx),
             det_map=det, unresolved=list(ren.values()), classes={h: "CLEAR" for h in ren.values()}, output=sha(fid),
             truth=truth)
    r10, det10, truth10 = renamed("IN-10", base.RENAME10)
    case("ambiguous_headers", "ambiguous", r10, "IN-10", "IN-10", "HUMAN_REVIEW",
         recorded=base._recorded("in10_ambiguous"), det_map=det10, unresolved=["entry_ref", "acct_no", "posting_dt",
                                                                               "txn_amt"],
         classes={"entry_ref": "AMBIGUOUS", "txn_amt": "AMBIGUOUS"}, truth=truth10)
    ra, deta, trutha = renamed("IN-10", {"amount": "txn_amt"})
    case("sign_sensitive", "sign_sensitive", ra, "IN-10", "IN-10", "HUMAN_REVIEW",
         recorded=base._recorded("in10_amount_only"), det_map=deta, unresolved=["txn_amt"],
         classes={"txn_amt": "AMBIGUOUS"}, truth=trutha, note="proposer says CLEAR; money field stays AMBIGUOUS")
    rp, detp, truthp = renamed("IN-10", AUTO10)
    case("partial_plausible", "partial_success", rp, "IN-10", "IN-10", "HUMAN_REVIEW",
         recorded=base._recorded("in10_partial_plausible"), det_map=detp, unresolved=list(AUTO10.values()),
         classes={"entry_ref": "CLEAR", "acct_no": "CLEAR", "posting_dt": "PLAUSIBLE"}, truth=truthp)
    case("duplicate_target", "duplicate_target", r10, "IN-10", "IN-10", "REJECT_OR_HOLD",
         recorded=base._recorded("in10_duplicate_target"), det_map=det10,
         unresolved=["entry_ref", "acct_no", "posting_dt", "txn_amt"],
         classes={"entry_ref": "CONFLICT_INCOMPLETE", "acct_no": "CONFLICT_INCOMPLETE"}, truth=truth10)
    case("invented_field", "unknown_canonical_field", rp, "IN-10", "IN-10", "HUMAN_REVIEW",   # 3B-11: NO_MATCH -> HITL
         recorded=base._recorded("in10_auto_invented"), det_map=detp, unresolved=list(AUTO10.values()),
         classes={"entry_ref": "NO_MATCH"}, truth=truthp)
    in10 = base._table(files["IN-10"])
    idx = [in10[0].index(c) for c in ("ledger_entry_id", "posted_ts", "account_id", "amount")]
    case("missing_required", "missing_required", [["entry_ref", "posting_dt", "acct_no", "txn_amt"]]
         + [[r[i] for i in idx] for r in in10[1:]], "IN-10", "IN-10", "HUMAN_REVIEW",   # 3B-7: 4 vs 8 -> direct HITL
         recorded=base._recorded("in10_short_example"), unresolved=[],
         truth={"entry_ref": "ledger_entry_id", "posting_dt": "posted_ts", "acct_no": "account_id", "txn_amt": "amount"})
    case("malformed_response", "malformed_response", r10, "IN-10", "IN-10", "REJECT_OR_HOLD",
         recorded=base._recorded("in10_malformed"), det_map=det10,
         unresolved=["entry_ref", "acct_no", "posting_dt", "txn_amt"])
    for tag, fld in (("A", "UNMAPPABLE"), ("B", "amount"), ("C", "entry_type")):
        case(f"unmappable_{tag}", "explicit_unmappable", r10, "IN-10", "IN-10", "HUMAN_REVIEW",   # 3B-11: HITL
             recorded=base._variant("in10_valid_mix", "txn_amt", canonical_field=fld, assessment="UNMAPPABLE"),
             det_map=det10, unresolved=["entry_ref", "acct_no", "posting_dt", "txn_amt"], classes={"txn_amt": "NO_MATCH"},
             truth=truth10)
    case("provider_disabled", "provider_disabled", rp, "IN-10", "IN-10", "REJECT_OR_HOLD",
         recorded=base._recorded("in10_auto_clear"), ai="disabled", det_map=detp)
    case("budget_refused", "budget_refused", rp, "IN-10", "IN-10", "REJECT_OR_HOLD",
         recorded=base._recorded("in10_auto_clear"), ai="budget_used", det_map=detp)
    for content, claimed in (("IN-09", "IN-10"), ("IN-07", "IN-08"), ("IN-05", "IN-06")):
        case(f"mismatch_{content}_as_{claimed}", "category_mismatch", files[content].read_bytes(), content, claimed,
             "HUMAN_REVIEW")                        # 3B-7: the field counts differ -> header-count gate -> direct HITL
    case("no_category", "no_category", rp, "IN-10", None, "REJECT_OR_HOLD", recorded=base._recorded("in10_auto_clear"))
    (out / "manifest.json").write_text(json.dumps(
        {"dataset": "UC-042 Smart Parser Phase 3B-6 orchestration evaluation (synthetic; recorded responses)",
         "extends": "tools/eval_3b5.py", "cases": cases}, indent=1), encoding="utf-8")
    return cases


def run_case(c: dict, corpus: Path) -> dict:
    from smartparser.ai.config import AIConfig
    from smartparser.ai.gateway import ProposalGateway, UsageLedger
    from smartparser.ai.proposer import RecordedResponseStub
    from smartparser.orchestration.orchestrator import MappingOrchestrator
    from smartparser.orchestration.policy import PocAutoAcceptPolicy
    from smartparser.review.approvals import approve_alias
    from smartparser.review.authority import Reviewer
    tmp = Path(tempfile.mkdtemp(prefix="sp3b6_"))
    e = base._env(tmp)
    if "approve_alias" in c["setup"]:
        cat, hdr, fld = c["setup"]["approve_alias"]
        approve_alias(cat, hdr, fld, [Reviewer(reviewer_id="eval-owner", role="data_owner", kind="TEST")], "eval",
                      e["policy"], e["store"], e["log"], "eval", "test", "low")
    fx = json.loads((corpus / "recorded" / c["recorded_response"]).read_text(encoding="utf-8")) \
        if c["recorded_response"] else None
    stub = RecordedResponseStub([fx] if fx else [])
    cfg, ledger, proposer = AIConfig(enabled=True, provider="recorded_stub"), UsageLedger(), stub
    if c["ai"] == "disabled":
        cfg = AIConfig()
    elif c["ai"] == "budget_used":
        class LiveLike:
            is_live, provider_id = True, "live-like-eval-double"

            def propose(self, request):
                return stub.propose(request)
        proposer = LiveLike()
        cfg = AIConfig(enabled=True, provider="p", model="m", region="r", max_output_tokens=10, max_calls_per_day=1,
                       max_cost_per_day=1.0)
        from datetime import datetime, timezone
        ledger.record(datetime.now(timezone.utc).date().isoformat(), None)
    gw = ProposalGateway(proposer=proposer, config=cfg, log=e["log"], ledger=ledger)
    o = MappingOrchestrator(e["reg"], e["store"], e["evidence"], gw, PocAutoAcceptPolicy.load(POLICY_ON), e["log"],
                            preview_dir=tmp / "preview")
    wr = o.process((corpus / c["data_file"]).read_bytes(), "upload.csv", "2026-09", category=c["input_category"])
    init = wr.initial                               # None when the 3B-7 header-count gate stopped the file
    det_map = {}
    if init is not None and init.mapping is not None and init.mapping.mappings:
        det_map = {m.original_header: m.canonical_field for m in init.mapping.mappings}
    elif wr.resolved_columns:
        det_map = dict(wr.resolved_columns)
    rec = wr.proposal.record if wr.proposal and wr.proposal.record else None
    return {"case_id": c["case_id"], "case_type": c["case_type"], "decision": wr.decision.value, "route": wr.route,
            "intake_case_kind": wr.intake_case.kind if wr.intake_case else None,
            "reasons": wr.reasons, "category": wr.category, "deterministic_mappings": det_map,
            "unresolved": wr.unresolved_headers, "llm_calls": len(stub.calls),
            "sent_headers": [u.source_header for u in stub.calls[0].unresolved_columns] if stub.calls else [],
            "classes": {x.source_header: x.validation_class.value for x in rec.columns} if rec else {},
            "proposed": {x.source_header: x.proposed_field for x in rec.columns} if rec else {},
            "eligible": bool(wr.eligibility and wr.eligibility.eligible),
            "canonical_output_sha256": wr.preview["output_sha256"] if wr.preview else None,
            "reprocess_llm_calls": wr.reprocessed.provider_calls if wr.reprocessed else None,
            "approval_kind": wr.file_mapping.approvals[0].approval_kind if wr.file_mapping else None,
            "audit_verified": e["log"].verify() >= 0}


def compare(c: dict, a: dict) -> list[str]:
    x, d = c["expected"], []
    if a["decision"] != x["decision"]:
        d.append(f"decision: expected {x['decision']}, got {a['decision']}")
    for h, f in x["deterministic_mappings"].items():
        if a["deterministic_mappings"].get(h) != f:
            d.append(f"deterministic[{h}]: expected {f}, got {a['deterministic_mappings'].get(h)}")
    if x["unresolved"] and a["unresolved"] != x["unresolved"]:
        d.append(f"unresolved: expected {x['unresolved']}, got {a['unresolved']}")
    if a["route"] == "HEADER_COUNT_GATE" and (a["llm_calls"] or a["deterministic_mappings"] or a["classes"]):
        d.append("the header-count gate must stop the file before any mapping or proposal")
    if a["sent_headers"] and a["sent_headers"] != a["unresolved"]:
        d.append("headers other than the unresolved ones were sent to the proposer")
    for h, k in x["classes"].items():
        if a["classes"].get(h) != k:
            d.append(f"class[{h}]: expected {k}, got {a['classes'].get(h)}")
    if a["canonical_output_sha256"] != x["canonical_output_sha256"]:
        d.append(f"canonical output: expected {x['canonical_output_sha256']}, got {a['canonical_output_sha256']}")
    if a["intake_case_kind"] == "HEADER_VARIANT" and (a["llm_calls"] or a["canonical_output_sha256"]):
        d.append("O2: a header-variant file must reach a person without an LLM call and without a preview")
    if a["decision"] == "DETERMINISTIC" and a["llm_calls"]:
        d.append("LLM called for a deterministically mapped file")
    if a["reprocess_llm_calls"]:
        d.append("LLM called during reprocessing")
    return d


def metrics(cases: list[dict], results: list[dict]) -> dict:
    by = {c["case_id"]: c for c in cases}
    det = [r for r in results if r["deterministic_mappings"]]
    det_pairs = [(h, f, by[r["case_id"]]) for r in det for h, f in r["deterministic_mappings"].items()]
    det_correct = sum(1 for h, f, c in det_pairs if c["expected"]["deterministic_mappings"].get(h, f) == f)
    prop = [(by[r["case_id"]]["truth_mapping"].get(h), f) for r in results for h, f in r["proposed"].items()
            if by[r["case_id"]]["truth_mapping"].get(h)]
    classes = Counter(v for r in results for v in r["classes"].values())
    decisions = Counter(r["decision"] for r in results)
    return {
        "note": "synthetic; proposal metrics are SIMULATED from recorded responses and say nothing about a live model",
        "deterministic_mapping": {"files_fully_mapped": decisions["DETERMINISTIC"],
                                  "column_mappings_checked": len(det_pairs),
                                  "column_mappings_correct": det_correct,
                                  "llm_calls_on_fully_mapped_files": sum(r["llm_calls"] for r in results
                                                                         if r["decision"] == "DETERMINISTIC")},
        "proposal_quality_SIMULATED": {"proposed_columns_with_truth": len(prop),
                                       "proposed_field_matches_truth": sum(1 for t, f in prop if t == f),
                                       "by_validation_class": dict(classes),
                                       "proposer_calls": sum(r["llm_calls"] for r in results)},
        "end_to_end": {"cases": len(results), "decisions": dict(decisions),
                       "decision_matches_expected": sum(1 for r in results if r["decision"] ==
                                                        by[r["case_id"]]["expected"]["decision"]),
                       "eligible_previews": sum(1 for r in results if r["canonical_output_sha256"]),
                       "previews_equal_expected_canonical_output": sum(
                           1 for r in results if r["canonical_output_sha256"] and r["canonical_output_sha256"] ==
                           by[r["case_id"]]["expected"]["canonical_output_sha256"]),
                       "auto_accept_approval_kinds": dict(Counter(r["approval_kind"] for r in results
                                                                  if r["approval_kind"])),
                       "llm_calls_during_reprocessing": sum(r["reprocess_llm_calls"] or 0 for r in results)},
        "header_count_gate_3b7": {"files_routed_directly_to_hitl": sum(r["route"] == "HEADER_COUNT_GATE" for r in results),
                                  "llm_calls_on_gated_files": sum(r["llm_calls"] for r in results
                                                                  if r["route"] == "HEADER_COUNT_GATE")},
        "operations": {"tokens_cost_latency": "not measured: recorded stub only, no live provider"},
    }


def run(corpus: Path, out_dir: Path | None = None):
    cases = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))["cases"]
    results = []
    for c in cases:
        r = run_case(c, corpus)
        r["diffs"] = compare(c, r)
        r["result"] = "PASS" if not r["diffs"] else "FAIL"
        results.append(r)
    m = metrics(cases, results)
    m["pass"], m["fail"] = sum(r["result"] == "PASS" for r in results), [r["case_id"] for r in results
                                                                        if r["result"] == "FAIL"]
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "eval3b6_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
        (out_dir / "eval3b6_metrics.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    return results, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run"])
    ap.add_argument("--out")
    ap.add_argument("--corpus", default=str(HERE / "corpus" / "phase3b6_eval"))
    a = ap.parse_args()
    if a.cmd == "build":
        print(len(build(Path(a.out or HERE / "corpus" / "phase3b6_eval"))), "cases")
    else:
        _, m = run(Path(a.corpus), Path(a.out) if a.out else None)
        print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
