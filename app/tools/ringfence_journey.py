"""Ringfence case-workflow journey in a REAL browser (headless Edge) against the real server process.

    py -3.11 -B tools/ringfence_journey.py --bundle <E2E bundle> --out <dir>

Three synthetic cases (same reporting period, different customers), driven through the /rf/ React UI:
  A  submission missing IN-03 and with an IN-05 export carrying two extra columns: start, upload IN-05 under its
     category, decide one column, DEFER; work on B; open A (stays PENDING), RESUME, only the remaining decision is shown;
     confirm, upload the missing IN-03, validate, activate, reconcile -> COMPLETED (UC-042 answer key compared)
  B  clean submission: start while A is pending (analyst override of the oldest-first order), defer when processed
  C  an unreadable ZIP: start -> failed run, Retry from beginning (confirmation) -> a second run, both kept in history
Every assertion is made against the backend API, not only the DOM. Analyst actions are TEST-ONLY (test authority)."""
from __future__ import annotations

import argparse
import base64
import io
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
from webapp_journeys import Bundle, Journey, add_col, rows_of, dump  # noqa: E402

IN05 = "internal_recon_records_2026-09.csv"
IN03 = "client_balance_snapshots_2026-09.csv"


class RF(Journey):
    def settle(self, timeout=30):
        self.br.wait("document.readyState === 'complete' && document.querySelector('#root .rf-page') && "
                     "!/Loading…/.test((document.querySelector('.rf-page')||{}).textContent||'')", timeout=timeout,
                     what="ringfence render")
        time.sleep(0.4)

    def wait(self, expr, timeout=60, what=""):
        self.br.wait(f"!!({expr})", timeout=timeout, what=what or expr[:80])     # DOM elements do not serialise

    def set_value(self, selector, value, event="input"):
        # React-controlled inputs: use the native value setter so React sees the change
        self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); "
                f"Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(value)}); "
                f"e.dispatchEvent(new Event({json.dumps(event)}, {{bubbles: true}})); }})()")

    def go(self, hash_):
        self.br.goto("about:blank")
        self.br.wait("location.href === 'about:blank'")
        self.br.goto(f"http://127.0.0.1:{self.port}/rf/{hash_}")
        self.settle()

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
            time.sleep(0.5)
        raise AssertionError(f"timeout waiting for {what}")

    def idle(self, c):
        return not c["progress"]["current_operation"] and not c["deferring"] and \
            (c["current_run"] or {}).get("status") != "PROCESSING"


def zip_of(files, skip=(), replace=None) -> bytes:
    replace = replace or {}
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files:
            if n not in skip:
                z.writestr(f"submission/{n}", replace.get(n, d))
    return b.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    b = Bundle(Path(a.bundle))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    j = RF("RF1", "Ringfence case workflow: queue, defer/resume, partial review, missing evidence, retry, completion",
           b, out, recorded=[])
    clean = b.zip_files("uc042_PER-2026-09_scenario_A_clean.zip")
    files = dict(clean)
    in05x = add_col(add_col(files[IN05], "memo_1", "note"), "memo_2", "note")
    inputs = j.inputs
    (inputs / IN05).write_bytes(in05x)
    (inputs / IN03).write_bytes(files[IN03])
    za = zip_of(clean, skip=(IN03,), replace={IN05: in05x})
    zb = zip_of(clean)
    (inputs / "harbourline_2026-09.zip").write_bytes(za)
    # CSP violations are not console errors: record every securitypolicyviolation event, on every page load
    j.br.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "document.addEventListener('securitypolicyviolation', e => {"
             " try { const k='rf_csp'; const v=JSON.parse(sessionStorage.getItem(k)||'[]'); v.push(e.violatedDirective+' '+e.blockedURI);"
             " sessionStorage.setItem(k, JSON.stringify(v)); } catch (x) {} });"})
    try:
        # ---------------------------------------------------------------- queue with three cases, one via the UI dialog
        j.go("#/queue")
        j.wait("document.querySelector('.rf-filter__n')", what="queue data")
        for _ in range(3):
            j.click("#new-case")
            try:
                j.wait("document.querySelector('#nc-customer')", timeout=8)
                break
            except AssertionError:
                pass
        j.set_value("#nc-customer", "Harbourline Payments Ltd")
        j.set_value("#nc-period", "2026-09")
        j.upload("#nc-file", [inputs / "harbourline_2026-09.zip"])
        j.wait("!document.querySelector('#create-case').disabled", what="create enabled")
        j.shot("new_case_dialog")
        j.click("#create-case")
        j.wait("location.hash.startsWith('#/case/RF-2026-09-')", what="case opened")
        ref_a = j.js("location.hash.split('/')[2]")
        time.sleep(1.1)
        ref_b = j.post("cases", {"customer_name": "Northgate Money Ltd", "reporting_period": "2026-09",
                                 "zip_name": "northgate.zip", "zip_b64": base64.b64encode(zb).decode()})["case_ref"]
        time.sleep(1.1)
        ref_c = j.post("cases", {"customer_name": "Corrupt Archive Co", "reporting_period": "2026-09",
                                 "zip_name": "corrupt.zip", "zip_b64": base64.b64encode(b"PK\x03\x04 broken").decode()})["case_ref"]
        j.step("cases registered", a=ref_a, b=ref_b, c=ref_c)
        j.go("#/queue")
        rows = j.js("[...document.querySelectorAll('#queue-table tbody tr')].map(r => r.dataset.case)")
        q = j.api("cases")
        j.check("RF.01", "three cases for the same period; queue order = backend order (oldest WAITING first)",
                (rows, [x["case_ref"] for x in q["items"]], q["counts"]["WAITING"]), ([ref_a, ref_b, ref_c], [ref_a, ref_b, ref_c], 3))
        j.shot("queue_three_waiting")
        # ---------------------------------------------------------------- A: opening does not start; explicit start
        j.go(f"#/case/{ref_a}")
        j.check("RF.02", "opening a WAITING case does not start Smart Parsing", (j.case(ref_a)["status"], j.case(ref_a)["runs"]),
                ("WAITING", []))
        j.shot("A_waiting")
        j.click("#act-start button")
        j.wait("document.querySelector('#confirm-start')")
        j.shot("A_confirm_start")
        j.click("#confirm-start")
        j.wait(f"location.hash === '#/case/{ref_a}/parser'", what="parser tab")
        c = j.wait_case(ref_a, j.idle, what="A run 1")
        j.go(f"#/case/{ref_a}/parser")
        j.shot("A_run1_completed")
        j.check("RF.03", "A in progress; run 1 completed; IN-03 and IN-05 missing; the IN-05 export refused (not identified)",
                (c["status"], c["current_run"]["status"], [m["category"] for m in c["progress"]["missing_required"]],
                 [u["filename"] for u in c["progress"]["refused_uploads"]]), ("IN_PROGRESS", "COMPLETED", ["IN-03", "IN-05"], [IN05]))
        j.go(f"#/case/{ref_a}/evidence")
        j.shot("A_evidence_missing")
        j.upload("#file-IN-05", [inputs / IN05])
        c = j.wait_case(ref_a, lambda x: x["progress"]["files_awaiting_review"] == 1 and j.idle(x), what="IN-05 review")
        j.check("RF.04", "IN-05 uploaded under its category -> mapping review with 2 decisions outstanding",
                c["progress"]["decisions_outstanding"], 2)
        vid = c["progress"]["awaiting_review"][0]["file_version_id"]
        j.go(f"#/case/{ref_a}/review/{vid}")
        shown = j.js("[...document.querySelectorAll('#review-table tbody tr')].map(r => r.children[1].textContent)")
        j.check("RF.05", "review shows only the columns needing the analyst (the 19 recognised are not listed)", shown, ["memo_1", "memo_2"])
        j.check("RF.06", "no free-text reason field; actions are Change/Ignore for an extra column",
                (j.js("document.querySelectorAll('#review-table textarea, #review-table input[type=text]').length"),
                 j.js("[...document.querySelectorAll('#review-table tbody tr:first-child button')].map(b => b.textContent)")),
                (0, ["Change", "Ignore"]))
        j.shot("A_review_before")
        col = j.js("document.querySelector('#review-table tbody tr').dataset.col")
        j.click(f"#ignore-{col}")
        j.wait("document.querySelectorAll('#review-table tbody tr').length === 1", what="one remaining")
        j.shot("A_review_one_decided")
        # ---------------------------------------------------------------- defer A with a partial review
        j.click("#act-defer button")
        c = j.wait_case(ref_a, lambda x: x["status"] == "PENDING", what="A pending")
        j.check("RF.07", "Defer: A PENDING, partial decision kept (1 made, 1 outstanding), slot released",
                (c["status"], c["progress"]["decisions_made"], c["progress"]["decisions_outstanding"], j.api("cases")["active_case_ref"]),
                ("PENDING", 1, 1, None))
        # ---------------------------------------------------------------- B: analyst override, start, defer
        j.go("#/queue")
        j.shot("queue_A_pending")
        j.go(f"#/case/{ref_b}")
        j.click("#act-start button")
        j.wait("document.querySelector('#confirm-start')")
        j.click("#confirm-start")
        c = j.wait_case(ref_b, j.idle, what="B run")
        j.check("RF.08", "B started while A pending; B processed all 19 categories of its ZIP", (c["status"], c["progress"]["categories_processed"]),
                ("IN_PROGRESS", 19))
        j.go(f"#/case/{ref_a}")
        j.check("RF.09", "while B is active, A's Resume is disabled with the backend reason",
                (j.case(ref_a)["status"], j.js("document.querySelector('#act-resume button').disabled"),
                 "in progress" in j.text("#act-resume")), ("PENDING", True, True))
        j.shot("A_pending_resume_blocked")
        j.go(f"#/case/{ref_b}")
        j.click("#act-defer button")
        j.wait_case(ref_b, lambda x: x["status"] == "PENDING", what="B pending")
        # ---------------------------------------------------------------- resume A: remaining decision only, missing IN-03
        j.go(f"#/case/{ref_a}")
        j.check("RF.10", "opening the PENDING case does not resume it", j.case(ref_a)["status"], "PENDING")
        j.click("#act-resume button")
        c = j.wait_case(ref_a, lambda x: x["status"] == "IN_PROGRESS", what="A resumed")
        j.go(f"#/case/{ref_a}/evidence")
        j.check("RF.11", "after resumption the missing required category is highlighted with an upload action",
                (j.js("[...document.querySelectorAll('#missing-panel [data-missing]')].map(r => r.dataset.missing)"),
                 j.js("!!document.querySelector('#upload-IN-03') && !document.querySelector('#upload-IN-03').disabled")), (["IN-03"], True))
        j.shot("A_resumed_missing_evidence")
        j.go(f"#/case/{ref_a}/review/{vid}")
        shown = j.js("[...document.querySelectorAll('#review-table tbody tr')].map(r => r.children[1].textContent)")
        j.check("RF.12", "resumed review shows only the remaining decision", shown, ["memo_2"])
        j.shot("A_review_resumed_remaining")
        col = j.js("document.querySelector('#review-table tbody tr').dataset.col")
        j.click(f"#ignore-{col}")
        j.wait("!document.querySelector('#confirm-file').disabled", what="confirm enabled")
        j.click("#confirm-file")
        j.wait_case(ref_a, lambda x: x["progress"]["files_awaiting_review"] == 0, what="review confirmed")
        j.go(f"#/case/{ref_a}/evidence")
        j.upload("#file-IN-03", [inputs / IN03])
        c = j.wait_case(ref_a, lambda x: j.idle(x) and not x["progress"]["missing_required"], what="IN-03 processed")
        j.check("RF.13", "after the missing upload validation passed automatically", c["progress"]["validation"]["state"], "PASSED")
        # ---------------------------------------------------------------- activate (acknowledged) and reconcile
        j.go(f"#/case/{ref_a}/validation")
        j.check("RF.14", "activation needs the acknowledgement", j.js("document.querySelector('#act-activate button').disabled"), True)
        j.js("document.querySelector('#ack').click()")
        j.wait("!document.querySelector('#act-activate button').disabled", what="activate enabled")
        j.shot("A_validation_ready")
        j.click("#act-activate button")
        c = j.wait_case(ref_a, lambda x: bool(x["progress"]["activation"]), what="activated")
        j.check("RF.15", "activation does not complete the case", c["status"], "IN_PROGRESS")
        j.go(f"#/case/{ref_a}/recon")
        j.click("#act-reconcile button")
        c = j.wait_case(ref_a, lambda x: x["status"] == "COMPLETED", timeout=900, what="completed")
        run_id = c["completed"]["reconciliation_run_id"]
        ak = b.answer_key(j.ws / "runs" / run_id, "set_01_clean_baseline")
        j.check("RF.16", "COMPLETED only after reconciliation; CLEAN; UC-042 answer key matched",
                (c["status"], c["completed"]["case_status"], ak), ("COMPLETED", "CLEAN", {"matched": True, "differences": []}))
        j.go(f"#/case/{ref_a}/recon")
        j.wait("document.querySelector('#recon-outcome')", what="outcome shown")
        j.shot("A_completed_reconciliation")
        j.go(f"#/case/{ref_a}")
        j.check("RF.17", "completed case offers no lifecycle or correction action",
                (j.js("[...document.querySelectorAll('.rf-casehead__actions button:not([disabled])')].length"),
                 any(a["enabled"] for a in c["actions"].values())), (0, False))
        j.shot("A_completed_overview")
        # ---------------------------------------------------------------- C: failed run, retry from beginning
        j.go(f"#/case/{ref_c}")
        j.click("#act-start button")
        j.wait("document.querySelector('#confirm-start')")
        j.click("#confirm-start")
        c = j.wait_case(ref_c, lambda x: (x["current_run"] or {}).get("status") == "FAILED", what="C failed")
        j.go(f"#/case/{ref_c}")
        j.check("RF.18", "failed run shown with its code; Retry from beginning offered",
                (c["current_run"]["failure"]["code"], j.js("!!document.querySelector('#act-retry button')")), ("INVALID_ZIP", True))
        j.shot("C_failed_run")
        j.click("#act-retry button")
        j.wait("document.querySelector('#confirm-retry')")
        j.shot("C_retry_confirm")
        j.click("#confirm-retry")
        c = j.wait_case(ref_c, lambda x: len(x["runs"]) == 2 and x["runs"][1]["status"] != "PROCESSING", what="C retry")
        j.check("RF.19", "retry created a new run (new ID, new package); the failed run is kept in history",
                (len({r["run_id"] for r in c["runs"]}), len({r["package_id"] for r in c["runs"]}), c["runs"][0]["status"], c["runs"][1]["retry_of"]),
                (2, 2, "FAILED", c["runs"][0]["run_id"]))
        j.go(f"#/case/{ref_c}/parser")
        j.shot("C_run_history")
        j.go("#/queue")
        j.shot("queue_final")
        j.check("UI.errors", "no JavaScript error in the browser", j.br.page_errors, [])
        j.check("UI.csp", "no CSP violation on any page", j.js("JSON.parse(sessionStorage.getItem('rf_csp')||'[]')"), [])
        act = j.api("activity")
        j.check("RF.20", "audit chain verified after the journey", act["chain"]["verified"], True)
    except Exception:
        try:
            j.shot("FAILURE")
            print("[RF1] page at failure:", j.js("location.href"), j.js("document.body.innerText.slice(0,800)"), j.br.page_errors)
        except Exception:
            pass
        raise
    finally:
        try:
            j.br.close()
        finally:
            j.server.terminate()
    summary = {"journey": j.jid, "title": j.title, "checks_total": len(j.checks),
               "checks_passed": sum(c["passed"] for c in j.checks), "screenshots": j.shots, "checks": j.checks}
    (out / "ringfence_journey_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"[RF1] DONE {summary['checks_passed']}/{summary['checks_total']}")
    shutil.rmtree(j.ws, ignore_errors=True)
    sys.exit(0 if summary["checks_passed"] == summary["checks_total"] else 1)


if __name__ == "__main__":
    main()
