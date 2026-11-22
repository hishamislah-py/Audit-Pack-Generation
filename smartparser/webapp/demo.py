"""Ringfence demo scenarios (enabled only with `server --demo-scenarios <folder>`).

The folder is p10/RINGFENCE_DEMO_TEST_DATA: one sub-folder per scenario with the original evidence ZIP,
`scenario.json` (customer, period, ZIP sha256) and `expected_outcome.json` (the frozen answer key).

What this module does:
- `catalogue()` lists the scenarios for the UI (read-only).
- `load(sid)` registers a NEW case from the scenario's ZIP through the normal registration operation
  (`CaseService.create`, the same call as POST /api/cases). The ZIP is read from disk and its sha256 must equal the
  value recorded in scenario.json. Nothing else happens: the analyst then runs the normal workflow (Start, review,
  activation, reconciliation, retry) and every result comes from the real Smart Parser and UC-042 engine.
- `verification(sid, case_ref)` compares what the backend actually produced for that case with the frozen answer key.
  This is read-only and runs after the fact; the answer key is never passed to, or read by, any processing step.

Nothing here writes outside the server workspace, and the scenario folder is only read."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import results

# Display text for the known scenarios (UI copy only; it does not influence processing). Any other scenario folder
# with a scenario.json is still listed, with generic text taken from scenario.json (see _text).
TEXT = {
    "RF-DEMO-01": {"order": 1, "title": "Clean reconciliation",
                   "description": "A complete, correctly mapped month of safeguarding evidence for Halden Pay Ltd: all 19 "
                                  "evidence categories, every CSV in the canonical UC-042 layout, no planted discrepancy.",
                   "demonstrates": "Start Smart Parsing → automatic validation passes → activate the package → run "
                                   "reconciliation → the engine reports CLEAN with no exceptions."},
    "RF-DEMO-02": {"order": 2, "title": "Reconciliation exceptions",
                   "description": "Complete evidence for Marlow Street Payments Ltd with two planted problems: an unexplained "
                                  "GBP 1,284.60 bank-ledger difference (17–21 Jul) and a bank entry carrying the wrong "
                                  "settlement-batch reference.",
                   "demonstrates": "The package validates and activates normally; reconciliation reports EXCEPTIONS_OPEN "
                                   "with failed controls, exceptions and investigation groups. Open an exception to see its "
                                   "supporting evidence rows."},
    "RF-DEMO-03": {"order": 3, "title": "Insufficient evidence",
                   "description": "Every evidence category for Corvane Money Ltd is supplied, but the bank evidence for one "
                                  "account-day (SGA-EUR-01, 15 Oct) is missing from the 17:00 confirmations, end-of-day "
                                  "statements and statement lines.",
                   "demonstrates": "Validation and activation succeed (no category is missing); reconciliation reports "
                                   "EVIDENCE_INCOMPLETE: controls that cannot be evaluated are INSUFFICIENT_EVIDENCE, not a "
                                   "financial failure."},
    "RF-DEMO-04": {"order": 4, "title": "Unreadable file in the ZIP and correction",
                   "description": "A ZIP for Thornbury Wallet Ltd that opens and registers normally, but one member (IN-09 "
                                  "bank statement lines) has a corrupted CRC-32, so its bytes cannot be read or trusted.",
                   "demonstrates": "Start Smart Parsing → the 18 readable files are processed; the corrupted member is "
                                   "isolated and never accepted (its exact read error is shown) → IN-09 is listed as a "
                                   "correction requirement and validation blocks activation → upload a corrected IN-09 as a "
                                   "new file version → validation passes → activate → reconcile. The original ZIP and its "
                                   "SHA-256 stay unchanged."},
    "RF-DEMO-05": {"order": 5, "title": "Duplicate refund (refund counted twice)",
                   "description": "Complete September evidence for Pellworth Card Services Ltd, copied byte for byte from the "
                                  "canonical UC-042 dataset SC5C: refund TX-0909-0R001 (60.00) appears once in the "
                                  "transactions, but the client ledger counted it twice, so client C0002's balance is 60.00 "
                                  "too high from 9 Sep and the firm's internal reconciliation reports a -60.00 shortfall.",
                   "demonstrates": "The package validates and activates normally; reconciliation reports EXCEPTIONS_OPEN: "
                                   "C06-DIFFERENCE fails on each of the 16 GBP reconciliation days from 9 Sep and "
                                   "CBAL-ROLLFWD fails for C0002 on 9 Sep. The 17 exceptions are linked in one "
                                   "investigation group; no cause is set by the engine.",
                   "expected": "EXCEPTIONS_OPEN: 17 FAIL (16 C06-DIFFERENCE GBP days + 1 CBAL-ROLLFWD GBP/C0002 "
                               "2026-09-09), 0 INSUFFICIENT_EVIDENCE, 17 exceptions (16 Critical, 1 High), 1 investigation "
                               "group (frozen answer key scn_SC5C_refund_double_posted/answer_key.json)."},
}


def _text(sid: str, meta: dict) -> dict:
    """Display text: the TEXT entry, or (for any other scenario folder) a generic entry built from scenario.json."""
    if sid in TEXT:
        return TEXT[sid]
    exp = meta.get("expected_outcome") or {}
    return {"order": int(meta.get("order") or 1000), "title": meta.get("title") or sid,
            "description": meta.get("description") or f"{meta.get('customer_name')} {meta.get('reporting_period')}",
            "demonstrates": meta.get("demonstrates") or "",
            "expected": meta.get("expected_text") or (exp.get("case_status") or "")}


class DemoError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DemoScenarios:
    def __init__(self, folder: Path):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise SystemExit(f"--demo-scenarios: {self.folder} is not a folder")
        self.items: dict[str, dict] = {}
        for d in sorted(p for p in self.folder.iterdir() if p.is_dir() and (p / "scenario.json").is_file()):
            meta = json.loads((d / "scenario.json").read_text(encoding="utf-8"))
            sid = meta.get("scenario_id")
            if not sid or not (meta.get("zip") or {}).get("file") or sid in self.items:
                continue                                       # not a usable scenario folder (or a duplicate id)
            zp = d / meta["zip"]["file"]
            # expected_outcome_current.json, when present, supersedes expected_outcome.json for runs made with the
            # current code (both kept; neither is an engine answer key unless its own "source" says so)
            cur = d / "expected_outcome_current.json"
            self.items[sid] = {"dir": d, "meta": meta, "zip_path": zp, "text": _text(sid, meta),
                               "expected_path": cur if cur.is_file() else d / "expected_outcome.json"}

    # ------------------------------------------------------------------------------------------------ helpers
    def _get(self, sid: str) -> dict:
        it = self.items.get(sid)
        if it is None:
            raise DemoError(404, "NOT_FOUND", f"unknown demo scenario {sid}")
        return it

    def _expected(self, it) -> dict:
        p = it["expected_path"]
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def _cases(self, ctx, it) -> list[dict]:
        """Cases in this workspace whose original ZIP is this scenario's ZIP (identified by sha256), newest first."""
        sha = it["meta"]["zip"]["sha256"]
        out = []
        for ref in ctx.cases.refs():
            try:
                c = ctx.cases.detail(ref)
            except Exception:
                continue
            if (c.get("zip") or {}).get("sha256") == sha:
                out.append(c)
        return sorted(out, key=lambda c: c.get("created_at") or "", reverse=True)

    # ------------------------------------------------------------------------------------------------ views
    def catalogue(self, ctx) -> dict:
        rows = []
        for sid, it in sorted(self.items.items(), key=lambda kv: (kv[1]["text"]["order"], kv[0])):
            m, t, e = it["meta"], it["text"], self._expected(it)
            zp = it["zip_path"]
            present = zp.is_file()
            rows.append({
                "scenario_id": sid, "order": t["order"], "title": t["title"],
                "customer_name": m["customer_name"], "reporting_period": m["reporting_period"],
                "description": t["description"], "demonstrates": t["demonstrates"],
                "expected": m.get("expected_outcome") or {}, "expected_text": t.get("expected") or "",
                "answer_key": {"source": e.get("source"), "source_sha256": e.get("source_sha256")},
                "synthetic_notice": m.get("synthetic_notice"),
                "zip": {"file": m["zip"]["file"], "bytes": m["zip"].get("bytes"), "sha256": m["zip"]["sha256"],
                        "present": present},
                "cases": [{k: c.get(k) for k in ("case_ref", "status", "created_at", "revision")}
                          | {"case_status": (c.get("completed") or {}).get("case_status"),
                             "runs": [{"run_no": r.get("run_no"), "status": r.get("status")} for r in c.get("runs") or []]}
                          for c in self._cases(ctx, it)],
            })
        return {"enabled": True, "folder": str(self.folder),
                "note": "Each load registers a new case from the scenario's original ZIP through the normal registration "
                        "operation. Results come from the real Smart Parser and UC-042 engine; the answer key is used only "
                        "to compare afterwards.",
                "scenarios": rows}

    def load(self, ctx, sid: str, assigned_to: str | None = None) -> dict:
        it = self._get(sid)
        m = it["meta"]
        zp = it["zip_path"]
        if not zp.is_file():
            raise DemoError(409, "DEMO_ZIP_MISSING", f"{zp.name} is not in {it['dir']}")
        data = zp.read_bytes()
        if _sha(data) != m["zip"]["sha256"]:
            raise DemoError(409, "DEMO_ZIP_CHANGED", f"{zp.name} does not match the sha256 recorded in scenario.json")
        c = ctx.cases.create(m["customer_name"], m["reporting_period"], zp.name, data,   # same call as POST /api/cases
                             assigned_to=assigned_to)
        return ctx.cases.detail(c["case_ref"])

    # ------------------------------------------------------------------------------------------------ verification
    def verification(self, ctx, sid: str, case_ref: str) -> dict:
        it = self._get(sid)
        c = ctx.cases.detail(case_ref)
        if (c.get("zip") or {}).get("sha256") != it["meta"]["zip"]["sha256"]:
            raise DemoError(409, "NOT_THIS_SCENARIO", f"{case_ref} was not registered from {sid}")
        e = self._expected(it)
        checks = []

        def chk(name, expected, actual):
            checks.append({"check": name, "expected": expected, "actual": actual, "passed": expected == actual})

        if "expected_member_isolation" in e:           # unreadable-member scenario (isolated, then corrected)
            x, after = e["expected_member_isolation"], e.get("expected_after_corrected_in09") or {}
            runs = c.get("runs") or []
            if not runs or runs[0].get("status") == "PROCESSING":
                return {"scenario_id": sid, "case_ref": case_ref, "status": "PENDING",
                        "detail": "Start Smart Parsing to compare.", "checks": []}
            r1 = runs[0]
            unread = r1.get("unreadable_entries") or []
            chk("run 1 status (one unreadable member does not fail the run)", x["run_1_status"], r1.get("status"))
            chk("isolated member", x["unreadable_member"], unread[0].get("name") if unread else None)
            chk("isolation reason", x["unreadable_error_kind"], unread[0].get("error_kind") if unread else None)
            chk("readable members staged", x["staged_entries"], r1.get("staged_entries"))
            done = c.get("completed") or {}
            status = "PARTIAL"
            if c["status"] == "COMPLETED" and done.get("reconciliation_run_id"):
                s = results.summary(results.run_dir(ctx.runs, done["reconciliation_run_id"]))
                chk("case status after the corrected IN-09", after.get("case_status"), s["case_status"])
                chk("exceptions after the corrected IN-09", after.get("exceptions"), s["exception_count"])
                status = None
        elif "expected_run_1" in e:                     # earlier technical-failure expectation (kept for history)
            runs = c.get("runs") or []
            if not runs or any(r.get("status") == "PROCESSING" for r in runs):
                return {"scenario_id": sid, "case_ref": case_ref, "status": "PENDING",
                        "detail": "Start Smart Parsing (and then Retry from Beginning) to compare.", "checks": []}
            chk("run 1 status", "FAILED", runs[0].get("status"))
            chk("run 1 failure is technical (case stays In Progress or later deferred, never Completed)",
                True, c["status"] in ("IN_PROGRESS", "PENDING"))
            if len(runs) >= 2:
                chk("retry run status", "FAILED", runs[1].get("status"))
                chk("retry run source", "ORIGINAL_ZIP", runs[1].get("evidence_source"))
                chk("retry run is a retry of run 1", runs[0].get("run_id"), runs[1].get("retry_of"))
                chk("failed runs kept in history", True, len(runs) >= 2 and all(r.get("status") == "FAILED" for r in runs))
            status = "PARTIAL" if len(runs) < 2 else None
        else:
            done = c.get("completed") or {}
            run_id = done.get("reconciliation_run_id")
            if c["status"] != "COMPLETED" or not run_id:
                return {"scenario_id": sid, "case_ref": case_ref, "status": "PENDING",
                        "detail": "Run the case to reconciliation to compare with the answer key.", "checks": []}
            d = results.run_dir(ctx.runs, run_id)
            s = results.summary(d)
            ctl = results.controls(d)
            exc = results.exceptions(d)
            groups = results._csv(d / "case" / "validation" / "investigation_groups.csv")
            outs = s["outcomes"]
            chk("case status", e.get("expected_case_status"), s["case_status"])
            for k, v in (e.get("expected_counts") or {}).items():
                chk(f"{k} control results", v, outs.get(k, 0))
            if "expected_non_passing_set" in e:
                exp_set = sorted(tuple(x) for x in e["expected_non_passing_set"])
                act_set = sorted((r["check_id"], r["scope"], r["outcome"]) for r in ctl
                                 if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE"))
                chk("non-passing control results (check, scope, outcome)", [list(x) for x in exp_set],
                    [list(x) for x in act_set])
            if "expected_exception_count" in e:
                chk("exceptions", e["expected_exception_count"], len(exc))
            if "expected_exception_root_causes" in e:
                chk("exception root causes", sorted(e["expected_exception_root_causes"]), sorted(x["root_cause"] for x in exc))
            if "expected_investigation_group_count" in e:
                chk("investigation groups", e["expected_investigation_group_count"], len(groups))
            status = None
        ok = all(x["passed"] for x in checks)
        return {"scenario_id": sid, "case_ref": case_ref, "status": status or ("MATCH" if ok else "MISMATCH"),
                "answer_key": {"source": e.get("source"), "source_sha256": e.get("source_sha256")},
                "checks": checks}


def route(ctx, method: str, P: list[str], q: dict, body: dict, *, user: str | None = None):
    demo = getattr(ctx, "demo", None)
    if demo is None:
        raise DemoError(404, "DEMO_DISABLED", "demo scenarios are not enabled on this server (--demo-scenarios)")
    if P == ["scenarios"] and method == "GET":
        return demo.catalogue(ctx)
    if len(P) == 3 and P[0] == "scenarios" and P[2] == "load" and method == "POST":
        return demo.load(ctx, P[1], assigned_to=user)  # same registration as a manual upload
    if len(P) == 3 and P[0] == "scenarios" and P[2] == "verification" and method == "GET":
        if not q.get("case_ref"):
            raise DemoError(400, "INVALID", "case_ref is required")
        return demo.verification(ctx, P[1], q["case_ref"])
    raise DemoError(404, "NOT_FOUND", "/api/demo/" + "/".join(P))
