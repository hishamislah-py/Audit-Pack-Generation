"""SUPERSEDED (19 Nov 2026) by tools/analyst_queue_journey.py, the canonical browser journey (passed 62/62 on an
isolated copy). Kept for reference.

Check the RUNNING Ringfence server (sign-in enabled) in headless Edge:
Login → Work Queue → Select case → Start → Smart Parser → Validation & activation → Reconciliation.

    set RF_USER=analyst-1 & set RF_PW=<password>
    py -3.11 -B tools/live_server_journey.py --url http://127.0.0.1:8780 --case RF-2026-06-001 --expect CLEAN --out <dir>

The script starts no server and never prints the password, which is read from the RF_PW environment variable.

Every step is a click in the delivered UI. Backend state is read through the page's own authenticated session, using
same-origin requests that carry the session cookie."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
import ringfence_app_journey  # noqa: E402,F401  (installs NetEdge: records page /api calls and JS errors)
import webapp_journeys  # noqa: E402

DLG = "(document.querySelector('.rf-dialog') || document)"


class Live:
    def __init__(self, url, out: Path):
        self.url, self.out = url.rstrip("/"), out
        out.mkdir(parents=True, exist_ok=True)
        self.br = webapp_journeys.Edge(Path(tempfile.mkdtemp(prefix="rf_live_")) / "edge")
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.br.cmd("Network.enable")
        self.br.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "document.addEventListener('securitypolicyviolation', e => {"
                    " try { const k='rf_csp'; const v=JSON.parse(sessionStorage.getItem(k)||'[]'); v.push(e.violatedDirective);"
                    " sessionStorage.setItem(k, JSON.stringify(v)); } catch (x) {} });"})
        self.checks, self.n = [], 0

    def js(self, e):
        return self.br.js(e)

    def wait(self, e, timeout=60, what=""):
        self.br.wait(f"!!({e})", timeout=timeout, what=what or e[:80])

    def check(self, cid, desc, actual, expected):
        ok = actual == expected
        self.checks.append({"id": cid, "check": desc, "passed": ok, "actual": actual, "expected": expected})
        print(f"[LIVE] CHECK {cid} {'PASS' if ok else 'FAIL'} {desc}: {json.dumps(actual, default=str)[:260]}", flush=True)

    def shot(self, label):
        self.n += 1
        h = self.js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)") or 1000
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": int(min(h, 5000)), "deviceScaleFactor": 1, "mobile": False})
        d = self.br.cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})["data"]
        (self.out / f"{self.n:02d}_{label}.png").write_bytes(base64.b64decode(d))
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})

    def api(self, path):
        """GET through the page (same origin, the session cookie is sent)."""
        txt = self.js(f"(() => {{ const x = new XMLHttpRequest(); x.open('GET', {json.dumps('/api/' + path)}, false); x.send(); "
                      f"return JSON.stringify({{s: x.status, b: x.responseText}}); }})()")
        r = json.loads(txt)
        return r["s"], (json.loads(r["b"]) if r["b"].startswith(("{", "[")) else r["b"])

    def case(self, ref):
        return self.api(f"cases/{ref}")[1]

    def wait_case(self, ref, cond, timeout=900, what=""):
        end = time.time() + timeout
        while time.time() < end:
            c = self.case(ref)
            if cond(c):
                return c
            time.sleep(1)
        raise AssertionError("timeout: " + what)

    def button(self, text, scope="document", timeout=60):
        sel = (f"[...({scope}).querySelectorAll('button')].find(b => b.textContent.trim().startsWith({json.dumps(text)}) && !b.disabled)")
        self.wait(sel, timeout, f"button '{text}'")
        self.js(f"({sel}).click()")
        time.sleep(0.3)

    def set_input(self, sel, value):
        self.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); "
                f"Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(value)}); "
                f"e.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")

    def text(self, sel="#root"):
        return self.js(f"(document.querySelector({json.dumps(sel)}) || {{}}).innerText || ''")


def idle(c):
    return not c["progress"]["current_operation"] and not c["deferring"] and (c["current_run"] or {}).get("status") != "PROCESSING"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8780")
    ap.add_argument("--case", required=True)
    ap.add_argument("--expect", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reregister-zip", default=None, help="after the journey, register this ZIP again as a new WAITING case "
                    "for the same customer/period (POST /api/cases, the Register screen's call), assigned to the user")
    a = ap.parse_args()
    user, pw = os.environ.get("RF_USER", "analyst-1"), os.environ.get("RF_PW")
    if not pw:
        sys.exit("set RF_PW")
    L = Live(a.url, Path(a.out))
    ref = a.case
    try:
        # 0. without a session the API refuses (checked outside the browser)
        try:
            urllib.request.urlopen(f"{L.url}/api/cases", timeout=10)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        L.check("AUTH.01", "API without a session is refused", code, 401)
        # 1. Login
        L.br.goto(f"{L.url}/analyst/")
        L.wait("document.querySelector('input[name=password]')", 60, "login form")
        L.shot("login")
        L.set_input("input[name=username]", user)
        L.set_input("input[name=password]", "wrong-" + pw)
        L.button("Sign in")
        L.wait("document.querySelector('[role=alert], .rf-notice--danger, .rf-login__error') || document.body.innerText.match(/incorrect|invalid|not recognised|failed/i)", 30, "wrong password refused")
        L.check("AUTH.02", "a wrong password is refused (still on the sign-in screen)",
                bool(L.js("!!document.querySelector('input[name=password]')")), True)
        L.set_input("input[name=password]", pw)
        L.button("Sign in")
        L.wait("location.hash.startsWith('#/queue') && document.querySelector('table')", 60, "work queue")
        time.sleep(1)
        # 2. Work Queue
        s, q = L.api("cases")
        refs = sorted(x["case_ref"] for x in q["items"])
        L.check("QUEUE.01", "signed in; the Work Queue lists the four preloaded demo cases from the backend",
                (s, refs, all(r in L.text() for r in refs)),
                (200, ["RF-2026-06-001", "RF-2026-07-001", "RF-2026-10-001", "RF-2026-11-001"], True))
        L.shot("work_queue")
        # 3. Select case
        L.js(f"[...document.querySelectorAll('table tbody tr')].find(r => r.innerText.includes({json.dumps(ref)})).click()")
        L.wait(f"location.hash.startsWith('#/cases/{ref}')", 30, "case opened")
        L.wait("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Start Smart Parsing'))", 30, "start button")
        c = L.case(ref)
        L.check("CASE.01", "case opened from the Work Queue: Waiting, Start offered by the backend",
                (c["status"], c["actions"]["start"]["enabled"]), ("WAITING", True))
        L.shot("case_waiting")
        # 4. Start → Smart Parser
        L.button("Start Smart Parsing")                 # simplified flow: no confirmation dialog
        L.wait("location.hash.includes('/parser')", 30, "parser tab")
        c = L.wait_case(ref, idle, 900, "smart parser run")
        L.wait("!document.body.innerText.includes('Not finished')", 30, "parser page refreshed")
        L.check("PARSER.01", "Smart Parser run completed; automatic validation passed",
                (c["current_run"]["status"], c["progress"]["validation"]["state"]), ("COMPLETED", "PASSED"))
        L.shot("smart_parser")
        # 5. Activation + reconciliation: automatic once everything passed (AUTO_AFTER_SMART_PARSER); with
        #    RINGFENCE_AUTO_RECONCILE=off, one "Start reconciliation" click on the Smart Parser screen (no dialogs).
        time.sleep(3)
        if not L.case(ref).get("activation"):
            L.wait("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Start reconciliation' && !b.disabled)"
                   " || /reconciliation (is running|started)/.test(document.body.innerText)", 60, "Start reconciliation")
            L.js("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Start reconciliation' && !b.disabled)?.click()")
        c = L.wait_case(ref, lambda x: bool(x.get("activation")), 120, "activation")
        L.check("ACT.01", "package activated without an Activate screen or dialog (snapshot sealed)", bool(c["activation"]["snapshot_id"]), True)
        # 6. Reconciliation
        L.js(f"location.hash = '#/cases/{ref}/recon'")
        c = L.wait_case(ref, lambda x: x["status"] == "COMPLETED" or x["progress"]["reconciliation"]["state"] == "FAILED", 900, "reconciliation")
        L.wait("document.querySelector('.rf-outcome')", 60, "outcome")
        time.sleep(1)
        rid = c["progress"]["reconciliation"]["run_id"]
        s, r = L.api(f"runs/{rid}")
        L.check("RECON.01", f"reconciliation completed with {a.expect}; the UI shows the backend outcome",
                (c["status"], r["case_status"], a.expect in L.text(".rf-outcome")), ("COMPLETED", a.expect, True))
        L.shot("reconciliation")
        calls = L.br.api_calls
        L.check("NET.01", "every page API call went to the same origin",
                sorted({x["url"].split("/api/")[0] for x in calls}), [L.url])
        L.check("UI.01", "no JavaScript error, no CSP violation",
                (L.br.page_errors, L.js("JSON.parse(sessionStorage.getItem('rf_csp')||'[]')")), ([], []))
        if a.reregister_zip:
            zb = base64.b64encode(Path(a.reregister_zip).read_bytes()).decode()
            body = json.dumps({"customer_name": c["customer_name"], "customer_id": c["customer_id"],
                               "reporting_period": c["reporting_period"], "zip_name": Path(a.reregister_zip).name,
                               "zip_b64": zb, "assigned_to": user})
            res = json.loads(L.js(f"(() => {{ const x = new XMLHttpRequest(); x.open('POST', '/api/cases', false); "
                                  f"x.setRequestHeader('Content-Type', 'application/json'); x.setRequestHeader('X-Smartparser-Client', 'webapp'); "
                                  f"x.send({json.dumps(body)}); return JSON.stringify({{s: x.status, b: JSON.parse(x.responseText)}}); }})()"))
            nb = res["b"]
            L.check("REREG.01", "a fresh case was registered from the same scenario ZIP (normal registration); the verified "
                    "case is unchanged", (res["s"], nb.get("status"), nb.get("assigned_to"), L.case(ref)["status"]),
                    (200, "WAITING", user, "COMPLETED"))
        summary = {"url": L.url, "case_ref": ref, "case_status": r["case_status"], "outcomes": r["outcomes"],
                   "exception_count": r["exception_count"], "run_id": rid,
                   "checks_passed": sum(x["passed"] for x in L.checks), "checks_total": len(L.checks), "checks": L.checks}
        (L.out / "live_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
        print(f"[LIVE] DONE {summary['checks_passed']}/{summary['checks_total']}")
    except Exception:
        try:
            L.shot("FAILURE")
            print("[LIVE] page at failure:", L.js("location.href"), L.text()[:1500], L.br.page_errors)
        except Exception:
            pass
        raise
    finally:
        L.br.close()


if __name__ == "__main__":
    main()
