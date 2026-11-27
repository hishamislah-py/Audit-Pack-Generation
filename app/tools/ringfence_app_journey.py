"""Ringfence React application (ringfence/, React 18 + Vite) driven in a REAL browser (headless Edge) against the REAL
Python backend process (smartparser.webapp.server). Every assertion reads backend state through the API; the browser's
own network traffic is recorded (DevTools) to prove the UI talks to the backend and sends `expected_revision`.

    py -3.11 -B tools/ringfence_app_journey.py --bundle <E2E bundle> --out <dir>              # built app at /rf/
    py -3.11 -B tools/ringfence_app_journey.py --bundle <E2E bundle> --out <dir> --mode dev   # Vite dev server (proxy)

Full journey (built app): A = S05 submission with a missing category, an unidentified IN-05 export (extra columns), a
malformed IN-11 (correction) and a case-variant IN-01 header (O2 review). Register (UI) -> start -> evidence uploads and
correction -> review (defer/resume mid-review) -> explicit confirmations -> automatic validation -> activation ->
reconciliation (EXCEPTIONS_OPEN, UC-042 S05 answer key) -> exception detail -> activity. C = unreadable ZIP -> failed run
-> Retry from Beginning. Analyst actions are TEST-ONLY (test authority). No LLM provider is involved."""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
import webapp_journeys  # noqa: E402
from webapp_journeys import Bundle, Journey, add_col, dump, rows_of  # noqa: E402

IN01, IN03, IN05, IN11 = ("recon_calendar_2026-09.csv", "client_balance_snapshots_2026-09.csv",
                          "internal_recon_records_2026-09.csv", "transactions_2026-09.csv")


class NetEdge(webapp_journeys.Edge):
    """Edge + a record of every /api request the PAGE sends (method, path, JSON keys of small bodies)."""
    def __init__(self, profile):
        self.api_calls = []
        super().__init__(profile)

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            m = msg.get("method")
            if m == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.page_errors.append((d.get("exception") or {}).get("description") or d.get("text"))
            elif m == "Runtime.consoleAPICalled" and msg["params"].get("type") == "error":
                self.page_errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"]))
            elif m == "Network.requestWillBeSent":
                req = msg["params"]["request"]
                if urllib.parse.urlsplit(req["url"]).path.startswith("/api/"):   # not /rf/src/api/*.js modules
                    keys = None
                    body = req.get("postData")
                    if body and len(body) < 4000:
                        try:
                            keys = sorted(json.loads(body))
                        except ValueError:
                            keys = None
                    self.api_calls.append({"method": req["method"], "url": req["url"],
                                           "path": req["url"].split("/api/", 1)[1], "keys": keys})
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


webapp_journeys.Edge = NetEdge                    # Journey constructs the browser through this name


class RF(Journey):
    base = "/rf/"

    def wait(self, expr, timeout=60, what=""):
        self.br.wait(f"!!({expr})", timeout=timeout, what=what or expr[:80])

    def settle(self, timeout=30):
        self.br.wait("!!(document.readyState === 'complete' && document.querySelector('#root .rf-page') && "
                     "!document.querySelector('[aria-busy=\"true\"]'))", timeout=timeout, what="render")
        time.sleep(0.35)

    def go(self, hash_):
        self.br.goto("about:blank")
        self.br.wait("location.href === 'about:blank'")
        self.br.goto(f"{self.origin}{self.base}{hash_}")
        self.settle()

    def set_value(self, selector, value, event="input"):
        self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); "
                f"Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(value)}); "
                f"e.dispatchEvent(new Event({json.dumps(event)}, {{bubbles: true}})); }})()")

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Smartparser-Client": "webapp"})
        return json.loads(urllib.request.urlopen(req, timeout=60).read())

    def case(self, ref):
        return self.api(f"cases/{ref}")

    def wait_case(self, ref, cond, timeout=600, what=""):
        end = time.time() + timeout
        while time.time() < end:
            c = self.case(ref)
            if cond(c):
                return c
            time.sleep(0.4)
        raise AssertionError(f"timeout waiting for {what}")

    @staticmethod
    def idle(c):
        return not c["progress"]["current_operation"] and not c["deferring"] and \
            (c["current_run"] or {}).get("status") != "PROCESSING"

    def click_when_enabled(self, selector, timeout=30):
        sel = json.dumps(selector)
        self.wait(f"document.querySelector({sel}) && !document.querySelector({sel}).disabled", timeout=timeout,
                  what="enabled " + selector)
        self.click(selector)

    def dialog(self, open_selector, confirm_id):
        self.click_when_enabled(open_selector)
        self.wait(f"document.querySelector('#{confirm_id}')", what=confirm_id)
        self.click("#" + confirm_id)


def zip_of(files, skip=(), replace=None) -> bytes:
    replace = replace or {}
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files:
            if n not in skip:
                z.writestr(f"submission/{n}", replace.get(n, d))
    return b.getvalue()


def slot(c, cat):
    return next((s for s in (c["package"] or {}).get("slots", []) if s["evidence_category"] == cat), None)


def full_journey(j: RF, b: Bundle):
    s05 = b.zip_files("uc042_PER-2026-09_S05_unexplained_difference.zip")
    files = dict(s05)
    in05x = add_col(add_col(files[IN05], "memo_1", "note"), "memo_2", "note")
    r11 = rows_of(files[IN11])
    in11_short = dump([r11[0], r11[1][:-2]] + r11[2:])
    r01 = rows_of(files[IN01])
    in01_variant = dump([[r01[0][0].upper()] + r01[0][1:]] + r01[1:])
    inputs = j.inputs
    for name, data in ((IN05, in05x), (IN03, files[IN03]), (IN11, files[IN11])):
        (inputs / name).write_bytes(data)
    za = zip_of(s05, skip=(IN03,), replace={IN05: in05x, IN11: in11_short, IN01: in01_variant})
    (inputs / "harbourline_2026-09.zip").write_bytes(za)

    # 1. register the case through the UI (a second case through the API for the retry scenario)
    j.go("#/queue")
    j.wait("document.querySelector('.rf-filter__n')", what="queue data")
    j.click("#new-case")
    j.wait("document.querySelector('#nc-customer')", what="dialog")
    j.set_value("#nc-customer", "Harbourline Payments Ltd")
    j.set_value("#nc-period", "2026-09")
    j.upload("#nc-file", [inputs / "harbourline_2026-09.zip"])
    j.click_when_enabled("#create-case")
    j.wait("location.hash.startsWith('#/case/RF-2026-09-')", what="case opened")
    j.settle()
    ref = j.js("location.hash.split('/')[2]")
    c = j.case(ref)
    j.check("RF.01", "case registered through the UI: WAITING, ZIP stored with its SHA-256, nothing processed",
            (c["status"], c["zip"]["filename"], len(c["zip"]["sha256"]), c["runs"]), ("WAITING", "harbourline_2026-09.zip", 64, []))
    j.shot("A_registered_waiting")
    ref_c = j.post("cases", {"customer_name": "Corrupt Archive Co", "reporting_period": "2026-09", "zip_name": "corrupt.zip",
                             "zip_b64": base64.b64encode(b"PK\x03\x04 broken").decode()})["case_ref"]
    # 3. start Smart Parsing (explicit, confirmed)
    j.go(f"#/case/{ref}")
    j.dialog("#act-start button", "confirm-start")
    j.wait(f"location.hash === '#/case/{ref}/parser'", what="parser tab")
    c = j.wait_case(ref, j.idle, what="run 1")
    j.go(f"#/case/{ref}/parser")
    j.wait("document.querySelectorAll('#stages [data-stage]').length === 9", what="9 real stages")
    j.check("RF.02", "run 1 completed; the 9 real stages are shown from the backend",
            (c["current_run"]["status"], j.js("document.querySelectorAll('#stages [data-stage]').length")), ("COMPLETED", 9))
    j.shot("A_run1_stages")
    o = c["outstanding"]
    j.check("RF.03", "outstanding from the backend: IN-03 and IN-05 missing, IN-05 export refused, IN-11 needs replacement, "
            "IN-01 header variant under review (O2)",
            ([m["category"] for m in o["missing_categories"]], [u["filename"] for u in o["refused_uploads"]],
             [(f["category"], f["cause"]) for f in o["files_requiring_replacement"]],
             [m["category"] for m in o["mapping_decisions"]]),
            (["IN-03", "IN-05"], [IN05], [("IN-11", "STRUCTURE_FAILED")], ["IN-01"]))
    # 2 / 6. evidence: upload the missing files and the correction through the UI
    j.go(f"#/case/{ref}/evidence")
    j.shot("A_evidence_outstanding")
    for cat, name, done in (("IN-03", IN03, lambda x: (slot(x, "IN-03") or {}).get("latest")),
                            ("IN-05", IN05, lambda x: (slot(x, "IN-05") or {}).get("latest")),
                            ("IN-11", IN11, lambda x: (slot(x, "IN-11") or {}).get("versions") == 2)):
        j.wait(f"document.querySelector('#file-{cat}')", what=f"upload {cat}")
        j.upload(f"#file-{cat}", [inputs / name])
        j.wait_case(ref, lambda x, done=done: done(x) and j.idle(x), what=f"{cat} processed")
        j.go(f"#/case/{ref}/evidence")
    c = j.case(ref)
    j.check("RF.04", "after uploads: nothing missing, IN-11 corrected (v2 VALIDATED), IN-05 and IN-01 await review",
            ([m["category"] for m in c["outstanding"]["missing_categories"]], c["outstanding"]["files_requiring_replacement"],
             slot(c, "IN-11")["latest"]["version_status"], sorted(m["category"] for m in c["outstanding"]["mapping_decisions"])),
            ([], [], "VALIDATED", ["IN-01", "IN-05"]))
    # 4. review IN-05: one decision, defer, resume, the remaining one
    v05 = next(m["file_version_id"] for m in c["outstanding"]["mapping_decisions"] if m["category"] == "IN-05")
    j.go(f"#/case/{ref}/review/{v05}")
    shown = j.js("[...document.querySelectorAll('#review-table tbody tr')].map(r => r.children[1].textContent)")
    j.check("RF.05", "review lists only the columns needing the analyst; no free-text field",
            (shown, j.js("document.querySelectorAll('#review-table textarea, #review-table input[type=text]').length")),
            (["memo_1", "memo_2"], 0))
    j.shot("A_review_IN05")
    col = j.js("document.querySelector('#review-table tbody tr').dataset.col")
    j.click(f"#ignore-{col}")
    j.wait("document.querySelectorAll('#review-table tbody tr').length === 1", what="one remaining")
    j.dialog("#act-defer button", "confirm-defer")
    c = j.wait_case(ref, lambda x: x["status"] == "PENDING", what="pending")
    j.go(f"#/case/{ref}/review/{v05}")
    j.check("RF.06", "deferred mid-review: PENDING, the decision kept, review read-only",
            (c["status"], c["progress"]["decisions_made"] >= 1, j.js("!document.querySelector('#confirm-file')")), ("PENDING", True, True))
    j.shot("A_pending_readonly")
    j.dialog("#act-resume button", "confirm-resume")
    j.wait_case(ref, lambda x: x["status"] == "IN_PROGRESS", what="resumed")
    j.go(f"#/case/{ref}/review/{v05}")
    shown = j.js("[...document.querySelectorAll('#review-table tbody tr')].map(r => r.children[1].textContent)")
    j.check("RF.07", "after resume only the remaining decision is shown", shown, ["memo_2"])
    col = j.js("document.querySelector('#review-table tbody tr').dataset.col")
    j.click(f"#ignore-{col}")
    j.wait("!document.querySelector('#confirm-file').disabled", what="confirm enabled")
    pid = j.case(ref)["package"]["package_id"]
    j.check("RF.08", "the last decision does not confirm the file (O3)",
            j.api(f"packages/{pid}/versions/{v05}")["version"]["version_status"], "REVIEW_REQUIRED")
    j.click("#confirm-file")
    j.wait_case(ref, lambda x: all(m["category"] != "IN-05" for m in x["outstanding"]["mapping_decisions"]), what="IN-05 confirmed")
    # 4/5. review the IN-01 header variant: Map, then confirm
    c = j.case(ref)
    v01 = next(m["file_version_id"] for m in c["outstanding"]["mapping_decisions"] if m["category"] == "IN-01")
    j.go(f"#/case/{ref}/review/{v01}")
    j.check("RF.09", "IN-01 case-variant header: only that column is shown, with Map / Ignore (no Change)",
            (j.js("[...document.querySelectorAll('#review-table tbody tr')].map(r => r.children[1].textContent)"),
             j.js("[...document.querySelectorAll('#review-table tbody tr button')].map(b => b.textContent)")),
            ([r01[0][0].upper()], ["Map", "Ignore"]))
    j.shot("A_review_IN01_variant")
    col = j.js("document.querySelector('#review-table tbody tr').dataset.col")
    j.click(f"#map-{col}")
    j.wait("!document.querySelector('#confirm-file').disabled", what="confirm enabled")
    j.click("#confirm-file")
    c = j.wait_case(ref, lambda x: not x["outstanding"]["mapping_decisions"] and j.idle(x), what="reviews done")
    # 7. validation (automatic)
    j.go(f"#/case/{ref}/package")
    j.check("RF.10", "validation passed automatically (all 9 PV checks shown, none failing)",
            (c["progress"]["validation"]["state"], j.js("document.querySelectorAll('#pv-table tbody tr').length"),
             j.js("document.querySelectorAll('#pv-table .rf-pill--danger').length")), ("PASSED", 9, 0))
    # 8. activation (acknowledged)
    j.check("RF.11", "activation needs the acknowledgement", j.js("document.querySelector('#act-activate button').disabled"), True)
    j.js("document.querySelector('#ack').click()")
    j.click_when_enabled("#act-activate button")
    c = j.wait_case(ref, lambda x: bool(x["activation"]), what="activated")
    j.go(f"#/case/{ref}/package")
    j.wait("document.querySelector('#activation-result')", what="activation shown")
    j.check("RF.12", "activated: snapshot, activated_by = analyst, manifest SHA-256; case still IN_PROGRESS",
            (c["status"], c["activation"]["activated_by"], len(c["activation"]["manifest_sha256"] or "")),
            ("IN_PROGRESS", "e2e-test-analyst-1", 64))
    j.shot("A_activated")
    # 9. reconciliation
    j.go(f"#/case/{ref}/recon")
    j.dialog("#act-reconcile button", "confirm-reconcile")
    c = j.wait_case(ref, lambda x: x["status"] == "COMPLETED", timeout=900, what="completed")
    run_id = c["completed"]["reconciliation_run_id"]
    ak = j.b.answer_key(j.ws / "runs" / run_id, "scn_S05_unexplained_gbp_difference")
    j.check("RF.13", "COMPLETED after reconciliation; EXCEPTIONS_OPEN; UC-042 S05 answer key matched",
            (c["completed"]["case_status"], ak), ("EXCEPTIONS_OPEN", {"matched": True, "differences": []}))
    # 10. exceptions and activity
    j.go(f"#/case/{ref}/recon")
    j.wait("document.querySelectorAll('#exceptions-table tbody tr').length > 0", what="exceptions listed")
    ui_exc = j.js("[...document.querySelectorAll('#exceptions-table tbody tr')].map(r => r.dataset.exception)")
    api_exc = [e["exception_id"] for e in j.api(f"runs/{run_id}")["exceptions"]]
    j.check("RF.14", "exception list = backend run exceptions", ui_exc, api_exc)
    j.shot("A_reconciliation_results")
    j.click(f"tr[data-exception='{ui_exc[0]}']")
    j.wait("document.querySelectorAll('#exception-evidence li').length > 0", what="exception evidence")
    det = j.api(f"runs/{run_id}/exceptions/{ui_exc[0]}")
    j.check("RF.15", "exception drawer shows its supporting evidence (one row per backend reference)",
            j.js("document.querySelectorAll('#exception-evidence li').length"), len(det["evidence"]))
    j.shot("A_exception_detail")
    j.go(f"#/case/{ref}/activity")
    j.wait("document.querySelectorAll('#activity-table tbody tr').length > 0", what="activity")
    act = j.api(f"cases/{ref}/activity")
    types = {e["event_type"] for e in act["events"]}
    j.check("RF.16", "activity: the case's lifecycle and analyst events are recorded and listed",
            ({"CASE_CREATED", "CASE_STARTED", "CASE_DEFERRED", "CASE_RESUMED", "ANALYST_EVIDENCE_UPLOADED",
              "ANALYST_REVIEW_CONFIRMED", "ANALYST_ACTIVATION_REQUESTED", "ANALYST_RECONCILIATION_REQUESTED",
              "CASE_COMPLETED"} <= types, act["chain"]["verified"],
             j.js("document.querySelectorAll('#activity-table tbody tr').length") == min(400, len(act["events"]))), (True, True, True))
    j.shot("A_activity")
    j.go(f"#/case/{ref}")
    j.check("RF.17", "completed case offers no lifecycle or correction action",
            j.js("document.querySelectorAll('.rf-casehead__actions button:not([disabled])').length"), 0)
    # 11. failed run -> retry from beginning
    j.go(f"#/case/{ref_c}")
    j.dialog("#act-start button", "confirm-start")
    c = j.wait_case(ref_c, lambda x: (x["current_run"] or {}).get("status") == "FAILED", what="C failed")
    j.go(f"#/case/{ref_c}")
    j.wait("document.querySelector('#act-retry button')", what="retry offered")
    j.shot("C_failed")
    j.dialog("#act-retry button", "confirm-retry")
    c = j.wait_case(ref_c, lambda x: len(x["runs"]) == 2 and x["runs"][1]["status"] != "PROCESSING", what="retry")
    j.go(f"#/case/{ref_c}/parser")
    j.wait("document.querySelectorAll('#runs-table tbody tr').length === 2", what="2 runs listed")
    j.check("RF.18", "retry created a new run from the original ZIP; the failed run is kept and listed",
            (len({r["run_id"] for r in c["runs"]}), c["runs"][0]["status"], c["runs"][1]["retry_of"], c["runs"][1]["evidence_source"]),
            (2, "FAILED", c["runs"][0]["run_id"], "ORIGINAL_ZIP"))
    j.shot("C_retry_history")
    # real API traffic from the page
    calls = j.br.api_calls
    case_posts = [x for x in calls if x["method"] == "POST" and x["path"].startswith("cases/RF-") and x["keys"] is not None]
    j.check("RF.19", "the UI talked to the backend: GET and POST /api calls observed; every case mutation sent expected_revision",
            (len([x for x in calls if x["method"] == "GET"]) > 20, len(case_posts) >= 10,
             [x["path"] for x in case_posts if "expected_revision" not in x["keys"]]), (True, True, []))
    j.go("#/queue")
    j.shot("queue_final")


def dev_smoke(j: RF):
    """Vite dev server (npm run dev) proxying /api to the backend process."""
    env = dict(os.environ, RINGFENCE_BACKEND=f"http://127.0.0.1:{j.port}")
    vite = subprocess.Popen("npm run dev", cwd=str(HERE / "ringfence"), env=env, shell=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen("http://127.0.0.1:5173/rf/", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)
        j.origin = "http://127.0.0.1:5173"
        j.go("#/queue")
        j.wait("document.querySelector('.rf-filter__n')", what="queue via proxy")
        (j.inputs / "dev.zip").write_bytes(zip_of(j.b.zip_files("uc042_PER-2026-09_scenario_A_clean.zip")))
        j.click("#new-case")
        j.wait("document.querySelector('#nc-customer')")
        j.set_value("#nc-customer", "Dev Proxy Ltd")
        j.set_value("#nc-period", "2026-09")
        j.upload("#nc-file", [j.inputs / "dev.zip"])
        j.click_when_enabled("#create-case")
        j.wait("location.hash.startsWith('#/case/RF-')", what="case via proxy")
        ref = j.js("location.hash.split('/')[2]")
        j.settle()
        j.dialog("#act-start button", "confirm-start")
        c = j.wait_case(ref, j.idle, what="dev run")
        j.check("DEV.01", "Vite dev server: register and start through the /api proxy; run completed on the backend",
                (c["status"], c["current_run"]["status"], c["progress"]["categories_processed"]), ("IN_PROGRESS", "COMPLETED", 19))
        calls = j.br.api_calls
        j.check("DEV.02", "page API calls went to the Vite origin (proxied), including the POSTs",
                (len(calls) > 5, sorted({x["url"].split("/api/")[0] for x in calls}),
                 sorted({x["path"].split("/")[-1] for x in calls if x["method"] == "POST"})),
                (True, ["http://127.0.0.1:5173"], sorted({"cases", "start"})))
        j.go(f"#/case/{ref}/parser")
        j.wait("document.querySelectorAll('#stages [data-stage]').length === 9", what="stages via proxy")
        j.shot("dev_case_parser")
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(vite.pid)], capture_output=True)
        else:
            vite.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["built", "dev"], default="built")
    a = ap.parse_args()
    b = Bundle(Path(a.bundle))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jid = "RF2" if a.mode == "built" else "RF2-DEV"
    j = RF(jid, "Ringfence React app against the real backend", b, out, recorded=[])
    j.origin = f"http://127.0.0.1:{j.port}"
    j.br.cmd("Network.enable")
    j.br.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "document.addEventListener('securitypolicyviolation', e => {"
             " try { const k='rf_csp'; const v=JSON.parse(sessionStorage.getItem(k)||'[]'); v.push(e.violatedDirective+' '+e.blockedURI);"
             " sessionStorage.setItem(k, JSON.stringify(v)); } catch (x) {} });"})
    try:
        if a.mode == "built":
            full_journey(j, b)
            j.check("UI.csp", "no CSP violation (built app served by the backend under its CSP)",
                    j.js("JSON.parse(sessionStorage.getItem('rf_csp')||'[]')"), [])
        else:
            dev_smoke(j)
        j.check("UI.errors", "no JavaScript error in the browser", j.br.page_errors, [])
    except Exception:
        try:
            j.shot("FAILURE")
            print(f"[{jid}] page at failure:", j.js("location.href"), j.js("document.body.innerText.slice(0,1500)"), j.br.page_errors)
        except Exception:
            pass
        raise
    finally:
        try:
            j.br.close()
        finally:
            j.server.terminate()
    summary = {"journey": jid, "checks_total": len(j.checks), "checks_passed": sum(c["passed"] for c in j.checks),
               "screenshots": j.shots, "api_calls_observed": len(j.br.api_calls), "checks": j.checks}
    (out / f"{jid}_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"[{jid}] DONE {summary['checks_passed']}/{summary['checks_total']} (api calls observed: {len(j.br.api_calls)})")
    shutil.rmtree(j.ws, ignore_errors=True)
    sys.exit(0 if summary["checks_passed"] == summary["checks_total"] else 1)


if __name__ == "__main__":
    main()
