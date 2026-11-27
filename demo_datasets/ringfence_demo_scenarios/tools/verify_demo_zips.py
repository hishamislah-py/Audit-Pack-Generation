"""Verify the four Ringfence demo ZIPs through the REAL Smart Parser backend (smartparser.webapp.server) over HTTP.

    py -3.11 -B tools/verify_demo_zips.py --data <RINGFENCE_DEMO_TEST_DATA> [--only 1 2 3 4]

One fresh server process per scenario (fresh --root C:\\u42v\\rfdata_ws_<n>, port 8790+n), AI disabled (no recorded
fixtures, provider env vars stripped), TEST authority. Helper logic (wait_case / idle / post with the webapp header /
answer-key comparison) is copied from p10/smartparser_phase1/tools/ringfence_app_journey.py and the demo bundle's
tools/run_workflow.py. Results are written to each scenario folder as verification_result.json.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SP = Path(r"C:\Users\artlptp263user\p10\smartparser_phase1")
UC = Path(r"C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\src\uc042")
FOLDERS = {1: "scenario_1_clean", 2: "scenario_2_exceptions", 3: "scenario_3_evidence_incomplete",
           4: "scenario_4_technical_failure"}


class Server:
    def __init__(self, ws: Path, port: int, log: Path):
        self.port, self.transcript = port, []
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True)
        cmd = [sys.executable, "-B", "-m", "smartparser.webapp.server", "--root", str(ws),
               "--authority", "tests/fixtures/review/test_authority_policy.json", "--uc042-root", str(UC),
               "--reviewer-id", "analyst-1", "--reviewer-role", "analyst", "--reviewer-kind", "TEST", "--insecure-no-auth", "--port", str(port)]
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("OPENAI", "ANTHROPIC", "GROQ", "UC042_", "AI_"))}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        self.logf = open(log, "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=str(SP), stdout=self.logf, stderr=subprocess.STDOUT, env=env)
        end = time.time() + 90
        while time.time() < end:
            try:
                self.app = self.get("app")
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("server did not start")

    def req(self, method, path, body=None, ok_errors=False):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/{path}", data=data, method=method,
                                   headers={"Content-Type": "application/json", "X-Smartparser-Client": "webapp"})
        try:
            with urllib.request.urlopen(r, timeout=180) as resp:
                raw, status = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        out = json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode("utf-8", "replace")
        if method == "POST":
            self.transcript.append({"method": method, "path": f"/api/{path}", "status": status,
                                    "request": {k: v for k, v in (body or {}).items() if k != "zip_b64"},
                                    "error": out.get("error") if isinstance(out, dict) else None})
        if status >= 400 and not ok_errors:
            raise RuntimeError(f"{method} /api/{path} -> {status}: {out}")
        return (status, out) if ok_errors else out

    def get(self, path):
        return self.req("GET", path)

    def post(self, path, body):
        return self.req("POST", path, body)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.logf.close()


class Checks:
    def __init__(self, sid):
        self.sid, self.items = sid, []

    def check(self, cid, what, got, want):
        ok = got == want
        self.items.append({"id": f"{self.sid}.{cid}", "check": what, "passed": ok, "observed": got, "expected": want})
        print(f"  [{'PASS' if ok else 'FAIL'}] {self.sid}.{cid} {what}" +
              ("" if ok else f"\n      observed={json.dumps(got, default=str)[:1500]}\n      expected={json.dumps(want, default=str)[:1500]}"),
              flush=True)
        return ok


def wait_case(srv, ref, cond, what, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        c = srv.get(f"cases/{ref}")
        if cond(c):
            return c
        time.sleep(0.5)
    raise TimeoutError(f"{ref}: timeout waiting for {what}")


def idle(c):
    return not c["progress"]["current_operation"] and not c["deferring"] and \
        (c["current_run"] or {}).get("status") != "PROCESSING"


def register(srv, sdir, scen, ck):
    zb = (sdir / scen["zip"]["file"]).read_bytes()
    c = srv.post("cases", {"customer_name": scen["customer_name"], "reporting_period": scen["reporting_period"],
                           "zip_name": scen["zip"]["file"], "zip_b64": base64.b64encode(zb).decode()})
    ck.check("CASE.registered", "case registered WAITING with the ZIP's SHA-256, no run yet",
             (c["status"], c["zip"]["sha256"], c["runs"]), ("WAITING", scen["zip"]["sha256"], []))
    return c


# ============================================================================================ S1-S3
def full_flow(srv, sdir, scen, exp, ck, ev):
    c = register(srv, sdir, scen, ck)
    ref = c["case_ref"]
    ev["case_ref"] = ref
    c = srv.post(f"cases/{ref}/start", {"expected_revision": c["revision"]})
    c = wait_case(srv, ref, idle, "Smart Parser run")
    run = c["current_run"]
    ev["smart_parser_run"] = {"run_id": run["run_id"], "status": run["status"], "failure": run["failure"]}
    rd = srv.get(f"cases/{ref}/runs/{run['run_id']}")
    ev["run_stages"] = [{"key": s["key"], "status": s["status"]} for s in rd.get("stages", [])]
    ev["llm_mode"] = rd.get("llm_mode")
    ck.check("RUN.completed", "Smart Parser run COMPLETED", run["status"], "COMPLETED")
    o = c["outstanding"]
    ev["outstanding_after_run"] = o
    ev["slots_after_run"] = [{"category": s["evidence_category"], "status": (s["latest"] or {}).get("version_status"),
                              "file": (s["latest"] or {}).get("original_filename")} for s in c["package"]["slots"]]
    ck.check("RUN.nothing_missing", "no missing category, no file requiring replacement, no refused upload",
             ([m["category"] for m in o["missing_categories"]], o["files_requiring_replacement"], o["refused_uploads"]),
             ([], [], []))
    # ---- review (expected: none, every CSV header is canonical)
    reviews = []
    for md in list(o["mapping_decisions"]):
        vid = md["file_version_id"]
        rv = srv.get(f"cases/{ref}/review/{vid}")
        steps = []
        for r in rv["rows"]:
            if r["needs_attention"] and not r["decided"]:
                act = "MAP" if r.get("suggested_field") and "MAP" in r["available_actions"] else "IGNORE"
                c = srv.get(f"cases/{ref}")
                srv.post(f"cases/{ref}/review/{vid}/decision", {"action": act, "source_index": r["source_index"],
                                                                "expected_revision": c["revision"]})
                steps.append({"source_header": r["source_header"], "action": act, "field": r.get("suggested_field")})
        c = srv.get(f"cases/{ref}")
        srv.post(f"cases/{ref}/review/{vid}/confirm", {"expected_revision": c["revision"]})
        reviews.append({"category": md["category"], "file": md["file_name"], "review_kind": rv["review_kind"],
                        "decisions": steps})
        c = wait_case(srv, ref, idle, "after review")
    ev["review_steps"] = reviews
    ck.check("REVIEW.none", "no mapping review needed (all CSVs canonical, AI disabled)", reviews, [])
    c = wait_case(srv, ref, lambda x: idle(x) and x["progress"]["validation"]["state"] in ("PASSED", "FAILED"),
                  "automatic validation", timeout=300)
    ev["validation"] = c["package"]["latest_validation"]
    ck.check("VAL.passed", "automatic package validation PASSED", c["progress"]["validation"]["state"], "PASSED")
    ck.check("ACT.enabled", "Activate action enabled", c["actions"]["activate"]["enabled"], True)
    a = srv.post(f"cases/{ref}/activate", {"confirm": True, "expected_revision": c["revision"]})
    ck.check("ACT.snapshot", "activation created a snapshot", (a["activated"], bool(a["snapshot_id"])), (True, True))
    ev["snapshot_id"] = a["snapshot_id"]
    c = srv.get(f"cases/{ref}")
    srv.post(f"cases/{ref}/reconcile", {"expected_revision": c["revision"]})
    c = wait_case(srv, ref, lambda x: x["status"] == "COMPLETED" or x["progress"]["reconciliation"]["state"] == "FAILED",
                  "reconciliation", timeout=1500)
    ck.check("REC.completed", "reconciliation finished and the case is COMPLETED", c["status"], "COMPLETED")
    rid = c["completed"]["reconciliation_run_id"]
    run = srv.get(f"runs/{rid}")
    nonpass = []
    for o_ in ("FAIL", "INSUFFICIENT_EVIDENCE"):
        cr = srv.get(f"runs/{rid}/controls?outcome={o_}")
        assert not cr.get("truncated")
        nonpass += cr["rows"]
    allc = srv.get(f"runs/{rid}/controls")
    exc = run["exceptions"]
    details = {e["exception_id"]: srv.get(f"runs/{rid}/exceptions/{e['exception_id']}") for e in exc}
    key = exp["frozen_key"]
    # ---- comparison with the frozen answer key
    ck.check("KEY.case_status", "case_status equals the frozen key", (c["completed"]["case_status"], run["case_status"]),
             (key["expected_case_status"],) * 2)
    ck.check("KEY.counts", "FAIL / INSUFFICIENT_EVIDENCE counts", {o_: sum(r["outcome"] == o_ for r in nonpass)
                                                                   for o_ in ("FAIL", "INSUFFICIENT_EVIDENCE")},
             key["expected_non_passing_counts"])
    ck.check("KEY.non_passing", "non-passing (check_id, scope, outcome) set equals the key",
             sorted([r["check_id"], r["scope"], r["outcome"]] for r in nonpass),
             sorted([r["check_id"], r["scope"], r["outcome"]] for r in key["expected_non_passing_results"]))
    by = {(r["check_id"], r["scope"]): r for r in nonpass}
    ck.check("KEY.result_root_causes", "root cause of every non-passing result equals the key",
             [[k["check_id"], k["scope"], (by.get((k["check_id"], k["scope"])) or {}).get("root_cause")]
              for k in key["expected_non_passing_results"]],
             [[k["check_id"], k["scope"], k["root_cause"]] for k in key["expected_non_passing_results"]])
    ev_diff = []
    for k in key["expected_non_passing_results"]:
        r = by.get((k["check_id"], k["scope"]))
        got = sorted(x.strip() for x in (r or {}).get("evidence", "").split(";") if x.strip())
        if got != sorted(k["expected_evidence"]):
            ev_diff.append({"result": [k["check_id"], k["scope"]], "observed": got, "expected": k["expected_evidence"]})
    ck.check("KEY.evidence_refs", "evidence references (category:file#line) equal the key", ev_diff, [])
    ck.check("KEY.exception_count", "exception count", (len(exc), run["exception_count"]),
             (len(key["expected_exceptions"]),) * 2)
    ck.check("KEY.exception_root_causes", "exception root causes", sorted(e["root_cause"] for e in exc),
             sorted(e["root_cause"] for e in key["expected_exceptions"]))
    fields = ("severity", "root_cause", "affected_results", "amount", "first_date", "last_date", "evidence_status")
    ck.check("KEY.exception_fields", "exception severity / affected results / amount / dates / evidence status",
             sorted(({f: str(x.get(f) or "") for f in fields} for x in exc), key=lambda x: x["root_cause"]),
             sorted(({f: str(x[f]) for f in fields} for x in key["expected_exceptions"]), key=lambda x: x["root_cause"]))
    gid = {}
    for x in exc:
        if x.get("investigation_group_id"):
            gid.setdefault(x["investigation_group_id"], []).append(x["root_cause"])
    multi = sorted(sorted(v) for v in gid.values() if len(v) > 1)
    ck.check("KEY.groups", "investigation groups (root-cause sets of multi-exception groups) and their count",
             (len(multi), multi), (len(key["expected_investigation_groups"]), sorted(key["expected_investigation_groups"])))
    ck.check("API.exception_detail", "every exception detail resolves with evidence rows",
             all(d["exception"]["exception_id"] == i and isinstance(d["evidence"], list) for i, d in details.items()), True)
    ck.check("API.actions_after", "completed case offers no enabled action",
             sorted(k for k, v in c["actions"].items() if v["enabled"]), [])
    ev["reconciliation"] = {"run_id": rid, "case_status": run["case_status"], "outcomes": run["outcomes"],
                            "total_results": run["total_results"], "controls_endpoint_total": allc["total"],
                            "exception_count": run["exception_count"], "by_severity": run["by_severity"],
                            "integrity_checks": run["integrity_checks"],
                            "investigation_groups": {g: sorted(v) for g, v in gid.items()},
                            "investigation_group_ids_total": len(gid),
                            "exceptions": [{k: e.get(k) for k in ("exception_id", "severity", "root_cause", "affected_results",
                                                                  "amount", "first_date", "last_date", "evidence_status",
                                                                  "investigation_group_id")} for e in exc],
                            "exception_evidence_rows": {i: len(d["evidence"]) for i, d in details.items()},
                            "non_passing": [{k: r[k] for k in ("check_id", "scope", "outcome", "root_cause")} for r in nonpass]}


# ============================================================================================ S4
def failure_flow(srv, sdir, scen, exp, ck, ev):
    c = register(srv, sdir, scen, ck)
    ref = c["case_ref"]
    ev["case_ref"] = ref
    c = srv.post(f"cases/{ref}/start", {"expected_revision": c["revision"]})
    c = wait_case(srv, ref, lambda x: (x["current_run"] or {}).get("status") in ("FAILED", "COMPLETED"), "run 1")
    r1 = c["runs"][0]
    e1 = exp["expected_run_1"]
    ck.check("RUN1.failed", "run 1 FAILED with a technical failure (code, stage, Bad CRC-32 message)",
             (r1["status"], r1["failure"]["code"], r1["failure"].get("stage"), e1["failure_message_contains"] in r1["failure"]["message"]),
             ("FAILED", e1["failure_code"], e1["failure_stage"], True))
    ev["run_1"] = r1
    ev["case_after_run_1"] = {"status": c["status"], "steps": c["steps"], "outstanding_other": c["outstanding"]["other"],
                              "actions": {k: v for k, v in c["actions"].items()}}
    ck.check("RUN1.actions", "after failure: Retry and Defer enabled; Activate / Reconcile / Upload disabled",
             {k: c["actions"][k]["enabled"] for k in ("retry_from_beginning", "defer", "activate", "reconcile", "upload_evidence")},
             {"retry_from_beginning": True, "defer": True, "activate": False, "reconcile": False, "upload_evidence": False})
    st, out = srv.req("POST", f"cases/{ref}/retry", {"expected_revision": c["revision"]}, ok_errors=True)
    ck.check("RETRY.needs_confirm", "retry without confirmation refused (400 CONFIRMATION_REQUIRED), nothing changed",
             (st, out.get("error"), len(srv.get(f"cases/{ref}")["runs"])), (400, "CONFIRMATION_REQUIRED", 1))
    c = srv.get(f"cases/{ref}")
    srv.post(f"cases/{ref}/retry", {"confirm": True, "expected_revision": c["revision"]})
    c = wait_case(srv, ref, lambda x: len(x["runs"]) == 2 and x["runs"][1]["status"] != "PROCESSING", "retry run")
    r2 = c["runs"][1]
    ev["run_2"] = r2
    ck.check("RETRY.failed_again", "retry run 2 used the ORIGINAL ZIP and FAILED again; run 1 kept (O1)",
             (len({r["run_id"] for r in c["runs"]}), [r["status"] for r in c["runs"]], r2["retry_of"], r2["evidence_source"],
              r2["failure"]["code"], e1["failure_message_contains"] in r2["failure"]["message"], c["failed_runs"]),
             (2, ["FAILED", "FAILED"], r1["run_id"], "ORIGINAL_ZIP", "RUN_FAILED", True, 2))
    ck.check("CASE.status", "case stays IN_PROGRESS with retry offered again", (c["status"], c["actions"]["retry_from_beginning"]["enabled"]),
             (exp["expected_case_status_after_retry"], True))
    runs_detail = [srv.get(f"cases/{ref}/runs/{r['run_id']}") for r in c["runs"]]
    ev["runs_detail"] = [{"run_id": d["run_id"], "status": d["status"], "failure": d["failure"],
                          "stages": [{"key": s["key"], "status": s["status"]} for s in d.get("stages", [])]} for d in runs_detail]
    act = srv.get(f"cases/{ref}/activity")
    types = [e["event_type"] for e in act["events"]]
    ck.check("ACTIVITY", "activity records CASE_RUN_FAILED x2 and CASE_RETRY_REQUESTED; audit chain verified",
             (types.count("CASE_RUN_FAILED"), "CASE_RETRY_REQUESTED" in types, act["chain"]["verified"]), (2, True, True))
    q = srv.get("cases")
    ck.check("APP.healthy", "queue still served; app info still served; this case is the active case",
             (q["active_case_ref"], bool(srv.get("app"))), (ref, True))
    ev["activity_event_types"] = sorted(set(types))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--only", nargs="*", type=int, default=[1, 2, 3, 4])
    a = ap.parse_args()
    data = Path(a.data)
    overall = {}
    for n in a.only:
        sdir = data / FOLDERS[n]
        scen = json.loads((sdir / "scenario.json").read_text(encoding="utf-8"))
        exp = json.loads((sdir / "expected_outcome.json").read_text(encoding="utf-8"))
        ws, port = Path(rf"C:\u42v\rfdata_ws_{n}"), 8790 + n
        print(f"=== scenario {n}: {scen['customer_name']} {scen['reporting_period']} (port {port}, ws {ws})", flush=True)
        srv = Server(ws, port, data / "logs" / f"server_scenario_{n}.log")
        ck, ev = Checks(f"S{n}"), {"server": {"port": port, "root": str(ws), "llm": srv.app.get("llm"),
                                              "engine_configured": srv.app.get("engine_configured"),
                                              "reviewer": srv.app.get("reviewer")}}
        t0 = time.time()
        err = None
        try:
            (failure_flow if n == 4 else full_flow)(srv, sdir, scen, exp, ck, ev)
        except Exception as exc:                                       # recorded, not hidden
            err = f"{type(exc).__name__}: {exc}"
            print("  ERROR", err, flush=True)
        finally:
            srv.stop()
        res = {"scenario": FOLDERS[n], "customer_name": scen["customer_name"], "reporting_period": scen["reporting_period"],
               "zip_sha256": scen["zip"]["sha256"], "verdict": "PASS" if not err and all(c["passed"] for c in ck.items) else "FAIL",
               "checks_passed": sum(c["passed"] for c in ck.items), "checks_total": len(ck.items), "error": err,
               "seconds": round(time.time() - t0, 1), "checks": ck.items, "observed": ev, "post_transcript": srv.transcript}
        (sdir / "verification_result.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
        overall[FOLDERS[n]] = {k: res[k] for k in ("verdict", "checks_passed", "checks_total", "error")}
        print(f"=== scenario {n}: {res['verdict']} {res['checks_passed']}/{res['checks_total']} in {res['seconds']}s", flush=True)
    print(json.dumps(overall, indent=1))
    sys.exit(0 if all(v["verdict"] == "PASS" for v in overall.values()) else 1)


if __name__ == "__main__":
    main()
