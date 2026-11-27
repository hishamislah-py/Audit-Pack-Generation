"""Phase 3B-10 - LIVE provider evaluation (OpenAI Responses API). NOT part of the offline test suite.

    py -3.11 tools/live_eval_3b10.py --env-file <.env holding OPENAI_API_KEY> --out <evidence dir>

Isolation: every scenario uses its own new rule store / evidence store / package store / audit log under --out. The
POC auto-accept policy is the EXISTING test-only fixture (tests/fixtures/orchestration/poc_auto_accept_enabled.json,
status POC_TEST_ONLY), loaded only for this run; the shipped policy file, production authority, rules and global
configuration are never written. Reviews use the existing test-only authority policy. Nothing is submitted.

Live-call controls: one adapter + one persistent usage ledger shared by all scenarios; AI_MAX_CALLS_PER_DAY caps the
calls; the gateway's existing timeout and retry limit apply; the run stops issuing live scenarios after the first
provider error (authentication, quota, model, bad request, timeout, unexpected). The API key is read from --env-file at
runtime, passed to the adapter only, and never printed, logged or written. Results contain no data rows.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from smartparser.ai.config import AIConfig  # noqa: E402
from smartparser.ai.gateway import ProposalGateway, UsageLedger  # noqa: E402
from smartparser.ai.openai_provider import OpenAIMappingProposer  # noqa: E402
from smartparser.intake.store import EvidenceStore  # noqa: E402
from smartparser.mapping.rule_store import RuleStore  # noqa: E402
from smartparser.orchestration.orchestrator import MappingOrchestrator  # noqa: E402
from smartparser.orchestration.policy import PocAutoAcceptPolicy  # noqa: E402
from smartparser.packages.service import PackageService, Submission  # noqa: E402
from smartparser.packages.store import PackageStore  # noqa: E402
from smartparser.review.audit import AuditLog  # noqa: E402
from smartparser.review.authority import AuthorityPolicy, Reviewer  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

FIX = HERE / "tests" / "fixtures"
TEST_POC_POLICY = FIX / "orchestration" / "poc_auto_accept_enabled.json"
TEST_AUTHORITY = FIX / "review" / "test_authority_policy.json"
SEP = FIX / "uc042_canonical" / "PER-2026-09_set_01_clean_baseline"
ANALYST = Reviewer(reviewer_id="eval-analyst-1", role="analyst", kind="TEST")
STOP_KINDS = {"authentication", "authentication_missing", "permission_denied", "rate_limit_or_quota",
              "model_unavailable", "bad_request", "unexpected", "api_status", "connection", "timeout"}


def load_key(env_file: Path) -> str:
    """OPENAI_API_KEY from a dotenv file (value only; quotes and an inline comment removed). Never printed."""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("export "):
            s = s[7:].lstrip()
        if s.startswith("OPENAI_API_KEY="):
            v = s.split("=", 1)[1].strip()
            if v[:1] in "'\"" and v[:1] and v[1:].find(v[0]) >= 0:
                v = v[1:1 + v[1:].find(v[0])]
            else:
                v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()
            return v
    return ""


def manifest_files():
    with open(SEP / "manifest.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        out.setdefault(r["file_id"], SEP / r["relative_path"])
    return out


FILES = manifest_files()


def canon(fid) -> bytes:
    return FILES[fid].read_bytes()


def table(fid):
    return list(csv.reader(io.StringIO(canon(fid).decode("utf-8"))))


def dump(rows) -> bytes:
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue().encode()


def renamed(fid, mapping) -> bytes:
    r = table(fid)
    return dump([[mapping.get(c, c) for c in r[0]]] + r[1:])


class Run:
    def __init__(self, out: Path, adapter, ledger, cfg):
        self.out, self.adapter, self.ledger, self.cfg = out, adapter, ledger, cfg
        self.reg = SchemaRegistry.from_directory()
        self.stopped: str | None = None

    def env(self, name):
        root = self.out / name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        log = AuditLog(root / "audit.jsonl")
        store = RuleStore.initialise(root / "rules", self.reg)
        gw = ProposalGateway(proposer=self.adapter, config=self.cfg, log=log, ledger=self.ledger)
        orch = MappingOrchestrator(self.reg, store, EvidenceStore(root / "evidence"), gw,
                                   PocAutoAcceptPolicy.load(TEST_POC_POLICY), log)
        svc = PackageService(PackageStore(root / "pk"), orch, AuthorityPolicy.load(TEST_AUTHORITY),
                             actor_id="eval-analyst-1")
        return svc, log

    def calls_before(self):
        return self.adapter.requests, len(self.adapter.usage_log)

    def live_record(self, before):
        req0, log0 = before
        entries = self.adapter.usage_log[log0:]
        for e in entries:
            if e.get("status") == "ERROR" and e.get("kind") in STOP_KINDS:
                self.stopped = f"provider error {e['kind']} (HTTP {e.get('http_status')})"
        return {"provider_requests": self.adapter.requests - req0, "requests": entries}


def version_view(v, svc):
    d = {"file_version_id": v.file_version_id, "category": v.evidence_category, "version": v.version_number,
         "status": v.version_status, "processing_status": v.processing_status, "reasons": v.reasons[:6],
         "missing_fields": v.missing_fields, "review_case_id": v.review_case_id,
         "review_session_id": v.review_session_id, "source_sha256": v.source_sha256,
         "confirmation_kind": v.confirmation.approval_kind if v.confirmation else None,
         "mapping_rule_refs": v.mapping_rule_refs,
         "handoff": v.handoff.model_dump() if v.handoff else None}
    if v.handoff and v.handoff.preview_csv:
        d["preview_equals_canonical"] = (svc.store.root / v.handoff.preview_csv).read_bytes() == canon(v.evidence_category)
    return d


def proposal_view(wr):
    if not wr or not wr.proposal or not wr.proposal.record:
        return None
    rec = wr.proposal.record
    return {"sent_unresolved_headers": [u.source_header for u in wr.proposal.request.unresolved_columns],
            "response_error": rec.response_error, "overall": rec.summary.overall,
            "required_fields_unresolved": rec.summary.required_fields_unresolved,
            "columns": [{"source_header": c.source_header, "proposed_field": c.proposed_field,
                         "proposer_assessment": c.proposer_assessment,
                         "validation_class": str(c.validation_class), "status": str(c.status),
                         "diagnostics": [d.code for d in c.diagnostics]} for c in rec.columns]}


def events_for(log, intake_id):
    return [e.event_type for e in log.events() if e.intake_id == intake_id]


# ------------------------------------------------------------------------------------------------ scenarios
def scenario_a(run: Run):
    """Valid semantic mapping inside the COMPLETE UC-042 package (17 required categories): IN-10 with three unfamiliar
    but unambiguous non-monetary headers; the other 16 required files are the canonical synthetic fixtures."""
    svc, log = run.env("A_full_package")
    ren = {"ledger_entry_id": "cash_book_entry_id", "account_id": "safeguarding_account_id",
           "posted_ts": "posting_timestamp"}
    pkg = svc.create_package("2026-09")
    subs = []
    for c in pkg.required_evidence_categories:
        if c == "IN-10":
            subs.append(Submission(renamed("IN-10", ren), "cashbook_export.csv", "IN-10"))
        else:
            subs.append(Submission(canon(c), FILES[c].name))
    before = run.calls_before()
    outs = svc.submit(pkg.package_id, subs)
    live = run.live_record(before)
    o10 = next(o for o in outs if o.evidence_category == "IN-10")
    wr = o10.workflow
    v = o10.file_version
    res = {"scenario": "A", "package": "COMPLETE UC-042 contract (17 required categories)",
           "input": {"category": "IN-10", "incoming_columns": 8, "canonical_fields": 8,
                     "unfamiliar_headers": ren},
           "live": live, "proposal": proposal_view(wr), "version": version_view(v, svc),
           "route": wr.route if wr else None, "decision": wr.decision.value if wr else None,
           "hitl_created": bool(wr and (wr.intake_case or wr.review_session)),
           "intake_events": events_for(log, v.intake_id),
           "handoff_checks_run": len(wr.eligibility.checks) if wr and wr.eligibility else 0,
           "handoff_checks_passed": sum(c.passed for c in wr.eligibility.checks) if wr and wr.eligibility else 0,
           "reprocess_provider_calls": wr.reprocessed.provider_calls if wr and wr.reprocessed else None,
           "other_files": {o.evidence_category: o.file_version.version_status for o in outs if o.file_version and
                           o.evidence_category != "IN-10"}}
    act = svc.activate(pkg.package_id)
    p = svc.load(pkg.package_id)
    res["activation"] = {"activated": act.activated, "reason": act.reason, "package_status": p.package_status,
                         "failed_checks": [(c.check_id, c.detail[:200]) for c in act.validation.checks if not c.passed]}
    if act.activated:
        man = json.loads(act.manifest_path.read_text(encoding="utf-8"))
        res["manifest"] = {"path": str(act.manifest_path.relative_to(run.out)), "status": man["status"],
                           "submission_authorised": man["submission_authorised"],
                           "reconciliation_status": man["reconciliation_status"], "files": len(man["files"]),
                           "snapshot_id": man["snapshot_id"],
                           "verify_snapshot": [(c.check_id, c.passed) for c in
                                               svc.verify_snapshot(pkg.package_id, p.active_snapshot_id)]}
    res["audit_events"] = log.verify()
    return res


def _single(run: Run, name, data, label, review=None):
    svc, log = run.env(name)
    pkg = svc.create_package("2026-09", ["IN-10"])
    before = run.calls_before()
    o = svc.submit(pkg.package_id, [Submission(data, f"{name}.csv", "IN-10")])[0]
    live = run.live_record(before)
    wr, v = o.workflow, o.file_version
    res = {"package": "TEST PACKAGE (one category, IN-10) - not a complete UC-042 package", "label": label,
           "live": live, "proposal": proposal_view(wr), "route": wr.route if wr else None,
           "decision": wr.decision.value if wr else None, "version_after_intake": version_view(v, svc),
           "review_case": None, "review_session": None, "preview_before_review": bool(v.handoff and v.handoff.preview_csv)}
    if v.review_case_id:
        case = svc.store.load_case(pkg.package_id, v.review_case_id)     # readable in any version status
        res["review_case"] = {"kind": case.kind, "state": case.state, "counts": [case.incoming_header_count,
                              case.expected_field_count], "extra": case.extra_headers_diagnostic,
                              "missing": case.missing_fields_diagnostic,
                              "columns": [(c.source_index, c.source_header, c.suggested_field, c.suggestion_basis)
                                          for c in case.columns]}
    if v.review_session_id:
        s, _, _ = svc.session_context(pkg.package_id, v.file_version_id)
        res["review_session"] = {"state": s.state, "columns": [
            {"source_header": c.source_header, "proposed_field": c.proposed_field,
             "validation_class": str(c.validation_class)} for c in s.columns]}
    if review and v.version_status != "REVIEW_REQUIRED":
        res["review"] = {"skipped": f"version is {v.version_status}, not under review"}
    elif review:
        before2 = run.calls_before()
        res["review"] = review(svc, pkg.package_id, v)
        res["review"]["provider_requests_during_review"] = run.live_record(before2)["provider_requests"]
    res["intake_events"] = events_for(log, v.intake_id)
    res["audit_events"] = log.verify()
    return res


def scenario_a2(run):
    data = renamed("IN-10", {"ledger_entry_id": "ledger_line_id", "account_id": "account_ref_id",
                             "posted_ts": "posting_datetime"})
    return {"scenario": "A2", **_single(run, "A2_cashbook_variant", data,
                                        "second valid semantic mapping (non-monetary headers)")}


def scenario_b(run):
    """Ambiguous: 'reference' (payment_reference vs ledger_entry_id) and 'value' (the signed amount)."""
    data = renamed("IN-10", {"payment_reference": "reference", "amount": "value"})

    def review(svc, pid, v):
        s = svc.review_session(pid, v.file_version_id, ANALYST, "checked against the export specification",
                               [(c.source_index, "CHANGE", {"reference": "payment_reference", "value": "amount"}
                                 [c.source_header]) for c in svc.session_context(pid, v.file_version_id)[0].columns])
        done = svc.complete_review(pid, v.file_version_id, [ANALYST], "reviewer-confirmed mapping")
        return {"session_state": s.state, "status_after_review": done.version_status,
                "preview_equals_canonical": (svc.store.root / done.handoff.preview_csv).read_bytes() == canon("IN-10")
                if done.handoff and done.handoff.preview_csv else False}
    return {"scenario": "B", **_single(run, "B_ambiguous", data, "ambiguous semantic headers", review)}


def scenario_c(run):
    """Unmappable: payment_reference replaced by 'display_colour' holding colour codes."""
    r = table("IN-10")
    i = r[0].index("payment_reference")
    rows = [r[0][:i] + ["display_colour"] + r[0][i + 1:]] + \
        [x[:i] + [["#FF0000", "#00AA00", "#0000FF"][k % 3]] + x[i + 1:] for k, x in enumerate(r[1:])]
    return {"scenario": "C", **_single(run, "C_unmappable", dump(rows), "header with no defensible mapping")}


def scenario_d(run):
    r = table("IN-10")
    data = dump([r[0] + ["operator_memo"]] + [x + ["free text"] for x in r[1:]])

    def review(svc, pid, v):
        case, _ = svc.review_case(pid, v.file_version_id)
        for c in case.columns:
            if c.source_header == "operator_memo":
                svc.decide(pid, v.file_version_id, "IGNORE_COLUMN", ANALYST, "operator memo, not evidence", c.source_index)
            else:
                svc.decide(pid, v.file_version_id, "MAP", ANALYST, "canonical name", c.source_index)
        done = svc.complete_review(pid, v.file_version_id, [ANALYST], "column review")
        side = json.loads((svc.store.root / done.handoff.provenance).read_text(encoding="utf-8"))
        return {"status_after_review": done.version_status, "ignored_in_provenance": side["ignored_columns"],
                "preview_equals_canonical": (svc.store.root / done.handoff.preview_csv).read_bytes() == canon("IN-10"),
                "original_preserved": svc.o.evidence.read_original(v.source_sha256) == data}
    return {"scenario": "D", **_single(run, "D_extra_column", data, "9 columns for 8 fields", review)}


def scenario_e(run):
    r = table("IN-10")
    i = r[0].index("currency")
    data = dump([[c for j, c in enumerate(x) if j != i] for x in r])
    return {"scenario": "E", **_single(run, "E_missing_column", data, "7 columns for 8 fields")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--max-calls", type=int, default=6)
    ap.add_argument("--max-output-tokens", type=int, default=2000)
    ap.add_argument("--reasoning-effort", default="low")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--only", default="A,A2,B,C,D,E")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    key = load_key(Path(a.env_file))
    cfg = AIConfig(enabled=True, provider="openai", model=a.model, region="openai-default (not pinned; owner decision)",
                   store=False, max_output_tokens=a.max_output_tokens, max_calls_per_day=a.max_calls,
                   max_cost_per_day=1.0, timeout_seconds=a.timeout, max_retries=1, send_value_shapes=False)
    adapter = OpenAIMappingProposer(api_key=key, model=a.model, max_output_tokens=a.max_output_tokens,
                                    timeout_seconds=a.timeout, reasoning_effort=a.reasoning_effort or None)
    del key
    ledger = UsageLedger(out / "usage_ledger.json")
    run = Run(out, adapter, ledger, cfg)
    meta = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provider": "openai (Responses API)",
            "model": a.model, "reasoning_effort": a.reasoning_effort, "max_output_tokens": a.max_output_tokens,
            "max_calls": a.max_calls, "timeout_seconds": a.timeout, "retries": cfg.max_retries, "store": False,
            "value_shapes_sent": False, "poc_policy": PocAutoAcceptPolicy.load(TEST_POC_POLICY).model_dump(),
            "shipped_poc_policy_status": PocAutoAcceptPolicy.load().status,
            "key_source": "dotenv file supplied by the user (value never printed or stored)"}
    results = []
    plan = [("A", scenario_a, True), ("A2", scenario_a2, True), ("B", scenario_b, True), ("C", scenario_c, True),
            ("D", scenario_d, False), ("E", scenario_e, False)]
    for name, fn, live in plan:
        if name not in a.only.split(","):
            continue
        if live and run.stopped:
            results.append({"scenario": name, "skipped": f"live calls stopped: {run.stopped}"})
            continue
        try:
            results.append(fn(run))
        except Exception as exc:                            # record and continue to the non-live scenarios
            results.append({"scenario": name, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        print(f"{name}: done; provider requests so far {adapter.requests}; stopped={run.stopped}", flush=True)
    meta["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["total_provider_requests"] = adapter.requests
    meta["usage_per_request"] = adapter.usage_log
    meta["ledger"] = json.loads((out / "usage_ledger.json").read_text()) if (out / "usage_ledger.json").exists() else {}
    meta["cost"] = "not reported by the provider API; not estimated"
    meta["stopped"] = run.stopped
    name = "live_results.json" if a.only == "A,A2,B,C,D,E" else f"results_{a.only.replace(',', '_')}.json"
    (out / name).write_text(json.dumps({"run": meta, "scenarios": results}, indent=1, default=str),
                                           encoding="utf-8")
    print(json.dumps({"total_provider_requests": adapter.requests, "stopped": run.stopped}))


if __name__ == "__main__":
    main()
