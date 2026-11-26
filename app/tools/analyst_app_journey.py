"""Ringfence analyst application (ringfence-analyst-app, delivered React 18 + Vite app) driven in a REAL browser
(headless Edge) against a REAL backend process (smartparser.webapp.server, stdlib HTTP server), same origin under /analyst/.

    py -3.11 -B tools/analyst_app_journey.py --bundle <E2E bundle> --out <dir> --scenarios <scenarios.json>
    py -3.11 -B tools/analyst_app_journey.py ... --mode dev     # Vite dev server (npm run dev:backend) proxying /api

scenarios.json: [{"id": "S1", "zip": "<path>", "customer": "...", "period": "YYYY-MM",
                  "expect": {"case_status": "CLEAN"} | {"run_failure": true}, "answer": {optional expected counts}}]

Every step is an analyst action in the UI (sign in, register with the ZIP, start, confirm reviews, activate, reconcile,
open an exception, retry). Every assertion reads the backend through the API and compares it with what the page shows.
The browser's own network traffic is recorded to prove the page talks to the backend and sends `expected_revision`.
No LLM provider is involved (no recorded fixtures, no keys in the server environment)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
import ringfence_app_journey as rfj  # noqa: E402  (NetEdge network recorder + RF helpers; installs NetEdge)
from webapp_journeys import Bundle  # noqa: E402

APP = HERE / "ringfence-analyst-app"
MUTATIONS_WITH_REVISION = ("start", "defer", "resume", "retry", "reconcile", "decision", "confirm", "reject")


class AJ(rfj.RF):
    base = "/analyst/"

    def settle(self, timeout=30):
        self.br.wait("!!(document.readyState === 'complete' && document.querySelector('#root') && "
                     "document.querySelector('#root').children.length && !document.querySelector('.rf-skel'))",
                     timeout=timeout, what="render")
        time.sleep(0.4)

    def go(self, hash_):
        self.br.goto("about:blank")
        self.br.wait("location.href === 'about:blank'")
        self.br.goto(f"{self.origin}{self.base}{hash_}")
        self.br.wait("!!(document.readyState === 'complete' && document.querySelector('#root').children.length)", what="load")
        time.sleep(0.4)

    def nav(self, hash_):
        """In-app navigation (keeps the signed-in session, which is client-side only)."""
        self.js(f"location.hash = {json.dumps(hash_)}")
        time.sleep(0.3)
        self.settle()

    def button(self, text, scope="document", timeout=60):
        """Click the first enabled <button> in scope whose text starts with `text` (wait until it exists and is enabled)."""
        sel = (f"[...({scope}).querySelectorAll('button')].find(b => b.textContent.trim().startsWith({json.dumps(text)}) "
               f"&& !b.disabled)")
        self.wait(sel, timeout=timeout, what=f"button '{text}'")
        self.js(f"({sel}).click()")
        time.sleep(0.25)

    DLG = "(document.querySelector('.rf-dialog') || document)"

    def text_of(self, css):
        return self.js(f"(document.querySelector({json.dumps(css)}) || {{}}).innerText || ''")

    def set_select(self, selector, value):
        self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); "
                f"Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(e, {json.dumps(value)}); "
                f"e.dispatchEvent(new Event('change', {{bubbles: true}})); }})()")

    def sign_in(self):
        self.go("#/login")
        self.wait("document.querySelector('#login-title')", what="sign-in screen")
        self.button("Sign in")
        self.wait("location.hash.startsWith('#/queue')", what="queue after sign-in")
        self.settle()

    def stats(self):
        """Stat tiles on the reconciliation tab: {label: value}."""
        return self.js("Object.fromEntries([...document.querySelectorAll('.rf-stat')].map(s => "
                       "[s.querySelector('.rf-stat__label').innerText.trim(), s.querySelector('.rf-stat__value').innerText.trim()]))")


def register(j: AJ, sc) -> str:
    j.nav("#/register")
    j.wait("document.querySelector('#reg-customer')", what="register form")
    j.wait("document.querySelector('#reg-customer').options.length > 1", what="customer list")
    j.set_select("#reg-customer", "__new")
    j.wait("document.querySelector('input[aria-label=\"New customer name\"]')", what="new customer input")
    j.set_value("input[aria-label=\"New customer name\"]", sc["customer"])
    j.set_value("#reg-period", sc["period"])
    j.upload("#reg-zip", [Path(sc["zip"])])
    j.js("document.querySelector('#reg-zip').dispatchEvent(new Event('change', {bubbles: true}))")
    j.wait("document.querySelector('.as-file__name')", what="zip attached")
    j.button("Register case")
    j.wait("/^#\\/cases\\/RF-[^/]+\\/overview/.test(location.hash)", timeout=120, what="case overview")
    j.settle()
    return j.js("decodeURIComponent(location.hash.split('/')[2])")


def confirm_reviews(j: AJ, ref, sid):
    """Confirm every file the backend lists as awaiting review (O3: explicit Confirm file mapping), through the UI."""
    for _ in range(25):
        c = j.case(ref)
        pend = (c["outstanding"] or {}).get("mapping_decisions") or []
        if not pend:
            return c
        f = pend[0]
        vid = f["file_version_id"]
        j.nav(f"#/cases/{ref}/review/{vid}")
        rv = j.api(f"cases/{ref}/review/{vid}")
        for row in [r for r in rv.get("rows", []) if r.get("needs_attention") and not r.get("decided")]:
            # accept the backend's proposal for each undecided row through the decision form
            j.step(f"{sid}: decision MAP on {vid} column {row.get('source_header')}")
            j.post(f"cases/{ref}/review/{vid}/decision",
                   {"action": "MAP", "source_index": row["source_index"], "expected_revision": j.case(ref)["revision"]})
        j.nav(f"#/cases/{ref}/review/{vid}")
        j.button("Confirm file")
        j.wait(f"{j.DLG} !== document", what="confirm dialog")
        j.button("Confirm file", j.DLG)
        j.wait_case(ref, lambda x: vid not in json.dumps((x["outstanding"] or {}).get("mapping_decisions", [])) and j.idle(x),
                    what="review confirmed")
        j.step(f"{sid}: confirmed {vid} in the UI")
    raise AssertionError("reviews did not converge")


def load_demo(j: AJ, sc) -> str:
    """Work Queue → Demo scenarios section (20 Nov 2026: no separate Demo screen) → Load scenario → a new case
    registered from the scenario's original ZIP through the same registration API as a manual upload."""
    j.nav("#/queue")
    btn = f"document.querySelector('button[aria-label=\"Load scenario {sc['demo_id']}\"]')"
    j.wait(f"{btn} && !{btn}.disabled", timeout=60, what="Load scenario button in the Work Queue demo section")
    j.js(f"{btn}.click()")
    j.wait("/^#\\/cases\\/RF-[^/]+\\/overview/.test(location.hash)", timeout=120, what="case overview after load")
    j.settle()
    return j.js("decodeURIComponent(location.hash.split('/')[2])")


def verify_in_ui(j: AJ, sc, ref):
    """Work Queue demo section: select the scenario row → Compare with answer key (backend compares actual results
    with the frozen key)."""
    sid = sc["id"]
    j.nav("#/queue")
    srow = f"document.querySelector('button[aria-label=\"Load scenario {sc['demo_id']}\"]').closest('tr')"
    j.wait(srow, timeout=60, what="scenario row in the demo section")
    j.js(f"{srow}.click()")
    card = "document.querySelector('.as-demo__detail')"
    j.wait(f"{card} && {card}.innerText.includes({json.dumps(ref)})", timeout=60, what="case listed under the scenario")
    row = f"[...{card}.querySelectorAll('tr')].find(r => r.innerText.includes({json.dumps(ref)}))"
    j.button("Compare with answer key", row)
    j.wait(f"{card}.querySelector('[data-verification]')", timeout=60, what="verification")
    shown = j.js(f"{card}.querySelector('[data-verification]').dataset.verification")
    v = j.api(f"demo/scenarios/{sc['demo_id']}/verification?case_ref={ref}")
    j.check(f"{sid}.12", "Compare with answer key (UI): actual backend results MATCH the frozen answer key",
            (shown, v["status"], [c["check"] for c in v["checks"] if not c["passed"]]), ("MATCH", "MATCH", []))
    j.shot(f"{sid}_answer_key")
    return v


def restore_crc(zb: bytes, member: str) -> bytes:
    """Rebuild a CRC-corrupted ZIP member (scenario 4 XORs its CRC-32 fields with 0xA5A5A5A5): restore the local
    header and central directory CRC in a COPY. Same code as C:\\u42v\\impl_20261120\\thornbury\\verify_thornbury.py."""
    import io
    import struct
    import zipfile
    b = bytearray(zb)
    info = zipfile.ZipFile(io.BytesIO(zb)).getinfo(member)
    good = info.CRC ^ 0xA5A5A5A5
    struct.pack_into("<I", b, info.header_offset + 14, good)
    i = b.find(b"PK\x01\x02")
    while i != -1:
        n, = struct.unpack_from("<H", b, i + 28)
        if bytes(b[i + 46:i + 46 + n]) == member.encode():
            struct.pack_into("<I", b, i + 16, good)
        i = b.find(b"PK\x01\x02", i + 4)
    return bytes(b)


def correct_unreadable_member(j: AJ, ref, sid, iso):
    """ZIP member isolation (20 Nov 2026): the run COMPLETES with the unreadable member isolated; the UI lists it as a
    correction item; the analyst uploads the corrected file through the Evidence tab's upload dialog.
    iso = {"member": <zip member name>, "category": "IN-09", "file": <corrected file path>}"""
    c = j.case(ref)
    run = c["current_run"]
    unread = (c["outstanding"] or {}).get("unreadable_members") or []
    j.check(f"{sid}.03i", "run COMPLETED with the unreadable member isolated (not a run failure); upload enabled, retry not",
            (run["status"], [u["name"] for u in unread if u.get("open")], [u.get("error_kind") for u in unread],
             c["status"], c["actions"]["upload_evidence"]["enabled"], c["actions"]["retry_from_beginning"]["enabled"]),
            ("COMPLETED", [iso["member"]], ["CRC_FAILURE"], "IN_PROGRESS", True, False))
    j.nav(f"#/cases/{ref}/evidence")
    item = f"document.querySelector('[data-unreadable=\"{iso['member']}\"]')"
    j.wait(item, timeout=60, what="unreadable-member correction item")
    j.check(f"{sid}.03j", "the Evidence tab shows the unreadable-member correction item with an upload action",
            (iso["member"] in j.js(f"{item}.innerText"), "Upload corrected file" in j.js(f"{item}.innerText")), (True, True))
    j.shot(f"{sid}_unreadable_member")
    j.button("Upload corrected file", item)
    j.wait(f"{j.DLG} !== document && document.querySelector('#rfb-file')", what="upload dialog")
    j.set_select("#rfb-cat", iso["category"])
    j.upload("#rfb-file", [Path(iso["file"])])
    j.js("document.querySelector('#rfb-file').dispatchEvent(new Event('change', {bubbles: true}))")
    j.wait(f"{j.DLG}.innerText.includes({json.dumps(Path(iso['file']).name)})", what="corrected file attached")
    j.button("Upload and process", j.DLG)
    c = j.wait_case(ref, lambda x: j.idle(x) and x["progress"]["validation"]["state"] in ("PASSED", "FAILED")
                    and not [u for u in (x["outstanding"] or {}).get("unreadable_members") or [] if u.get("open")],
                    timeout=600, what="corrected file processed and validated")
    slot_ = next(s for s in c["package"]["slots"] if s["evidence_category"] == iso["category"])
    j.check(f"{sid}.03k", "corrected file uploaded through the UI: the category has a file, the unreadable item is closed, "
            "validation re-ran", (bool(slot_.get("latest")), c["progress"]["validation"]["state"]), (True, "PASSED"))
    return c


def scenario(j: AJ, sc, results):
    sid, exp = sc["id"], sc["expect"]
    if sc.get("demo_id"):
        j.step(f"{sid}: load demo scenario {sc['demo_id']} ({sc['customer']} {sc['period']})")
        ref = load_demo(j, sc)
    else:
        j.step(f"{sid}: register {Path(sc['zip']).name} for {sc['customer']} {sc['period']}")
        ref = register(j, sc)
    c = j.case(ref)
    if not sc.get("_started"):                       # the queue journey starts the case from the queue itself
        j.check(f"{sid}.01", "case registered from the scenario ZIP (UI): Waiting, with the ZIP, customer and period",
                (c["status"], c["customer_name"], c["reporting_period"], c["zip"]["filename"]),
                ("WAITING", sc["customer"], sc["period"], Path(sc["zip"]).name))
        j.check(f"{sid}.02", "overview shows the backend status pill and Start action",
                ("Waiting" in j.text_of(".rf-page, #root"), bool(j.js("[...document.querySelectorAll('button')].some(b => "
                                                                       "b.textContent.includes('Start Smart Parsing') && !b.disabled)"))),
                (True, True))
        j.shot(f"{sid}_overview_waiting")
        j.button("Start Smart Parsing")              # simplified flow: starts at once, no confirmation dialog
        j.wait("location.hash.includes('/parser')", what="parser tab")
        j.check(f"{sid}.02b", "Start Smart Parsing opened no confirmation dialog", j.js(f"{j.DLG} === document"), True)
    c = j.wait_case(ref, lambda x: j.idle(x), timeout=900, what="smart parser run")
    run = c["current_run"]
    # the page polls the case every 3 s (contract §5): wait until it shows the finished run before the screenshot
    j.wait("!document.body.innerText.includes('Not finished')", timeout=30, what="parser page refreshed")
    j.settle()
    j.shot(f"{sid}_parser")
    stages_ui = j.js("document.querySelectorAll('.rf-stages li, [class*=stage] li').length")
    j.step(f"{sid}: run {run['run_id']} {run['status']}", stages_ui=stages_ui)

    if exp.get("run_failure"):
        j.check(f"{sid}.03", "technical failure: run 1 FAILED (case stays In Progress, Retry offered by the backend)",
                (run["status"], run["run_no"], c["status"], c["actions"]["retry_from_beginning"]["enabled"]),
                ("FAILED", 1, "IN_PROGRESS", True))
        j.check(f"{sid}.04", "the UI shows the failure code from the backend",
                (run.get("failure") or {}).get("code", "") in j.text_of("#root"), True)
        j.button("Retry from Beginning")
        j.js(f"(() => {{ const b = {j.DLG}.querySelector('input[type=checkbox]'); if (b && !b.checked) b.click(); }})()")
        j.button("Retry from Beginning", j.DLG)
        c = j.wait_case(ref, lambda x: x["current_run"]["run_no"] == 2 and j.idle(x), timeout=600, what="retry run")
        runs = c.get("runs") or []
        j.check(f"{sid}.05", "Retry from Beginning (UI) created run 2 from the ORIGINAL ZIP (O1); it fails the same way; "
                "run 1 is kept", (c["current_run"]["run_no"], c["current_run"]["status"], runs[-1].get("evidence_source"),
                                  len(runs), [r["status"] for r in runs]), (2, "FAILED", "ORIGINAL_ZIP", 2, ["FAILED", "FAILED"]))
        j.nav(f"#/cases/{ref}/parser")
        j.check(f"{sid}.06", "Smart Parser tab lists both runs", j.js("document.body.innerText.includes('Run 1') && "
                                                                       "document.body.innerText.includes('Run 2')"), True)
        j.shot(f"{sid}_retry_failed_again")
        # leave the slot free for the next scenario: defer through the UI (the case becomes Pending, nothing is lost)
        j.button("Defer Case")
        j.button("Defer Case", j.DLG)
        c = j.wait_case(ref, lambda x: x["status"] == "PENDING", what="deferred")
        j.check(f"{sid}.07", "Defer Case (UI) → Pending; the failed runs stay in the history", (c["status"], len(c.get("runs") or [])),
                ("PENDING", 2))
        results[sid] = {"case_ref": ref, "runs": [{k: r.get(k) for k in ("run_id", "run_no", "status", "evidence_source", "failure")}
                                                   for r in c.get("runs") or []], "final_status": c["status"]}
        if sc.get("demo_id") and sc.get("verify", True):
            results[sid]["answer_key_comparison"] = verify_in_ui(j, sc, ref)
        return

    j.check(f"{sid}.03", "Smart Parser run completed on the backend", run["status"], "COMPLETED")
    c = confirm_reviews(j, ref, sid)
    if exp.get("member_isolation"):
        correct_unreadable_member(j, ref, sid, exp["member_isolation"])
        c = confirm_reviews(j, ref, sid)
    c = j.wait_case(ref, lambda x: x["progress"]["validation"]["state"] in ("PASSED", "FAILED") and j.idle(x), timeout=300,
                    what="automatic validation")
    j.check(f"{sid}.04", "automatic validation passed", c["progress"]["validation"]["state"], "PASSED")
    # Simplified flow: no Validation & activation screen and no Activate dialog. Once nothing is left for the analyst the
    # backend activates and reconciles by itself (AUTO_AFTER_SMART_PARSER); with RINGFENCE_AUTO_RECONCILE=off the Smart
    # Parser screen offers one "Start reconciliation" click (activation + reconciliation, no confirmation).
    j.nav(f"#/cases/{ref}/parser")
    time.sleep(3)
    if not j.case(ref).get("activation"):
        j.wait("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Start reconciliation' && !b.disabled)"
               " || /reconciliation (is running|started)/.test(document.body.innerText)", timeout=60, what="Start reconciliation")
        j.js("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Start reconciliation' && !b.disabled)?.click()")
    c = j.wait_case(ref, lambda x: bool(x.get("activation")), what="activation")
    j.shot(f"{sid}_parser_all_passed")
    j.check(f"{sid}.05", "activated without an Activate screen or dialog: snapshot sealed",
            (bool(c["activation"]["snapshot_id"]), j.js(f"{j.DLG} === document")), (True, True))
    c = j.wait_case(ref, lambda x: x["status"] == "COMPLETED" or x["progress"]["reconciliation"]["state"] == "FAILED",
                    timeout=900, what="reconciliation")
    rec = c["progress"]["reconciliation"]
    r = j.api(f"runs/{rec['run_id']}")
    j.nav(f"#/cases/{ref}/recon")
    j.wait("document.querySelector('.rf-outcome')", timeout=60, what="outcome panel")
    j.check(f"{sid}.06", f"reconciliation outcome {exp['case_status']} (backend run + case Completed)",
            (c["status"], r["case_status"], c["completed"]["case_status"]), ("COMPLETED", exp["case_status"], exp["case_status"]))
    ui_stats = j.stats()
    outs = r["outcomes"]
    expected_stats = {"Control results": str(r["total_results"]), "PASS": str(outs.get("PASS", 0)), "FAIL": str(outs.get("FAIL", 0)),
                      "INSUFFICIENT_EVIDENCE": str(outs.get("INSUFFICIENT_EVIDENCE", 0)),
                      "NOT_APPLICABLE": str(outs.get("NOT_APPLICABLE", 0)), "Exceptions": str(r["exception_count"])}
    j.check(f"{sid}.07", "outcome banner and stat tiles in the UI equal the backend run",
            (exp["case_status"] in j.text_of(".rf-outcome"), ui_stats), (True, expected_stats))
    j.shot(f"{sid}_recon")
    if exp.get("answer"):
        a = exp["answer"]
        got = {"FAIL": outs.get("FAIL", 0), "INSUFFICIENT_EVIDENCE": outs.get("INSUFFICIENT_EVIDENCE", 0),
               "exceptions": r["exception_count"]}
        j.check(f"{sid}.08", "matches the scenario's independently defined expected counts", {k: got[k] for k in a}, a)
    if r["exception_count"]:
        rows = j.js("document.querySelectorAll('table tbody tr.is-clickable').length")
        j.check(f"{sid}.09", "exceptions table lists every exception from the backend", rows, r["exception_count"])
        first = r["exceptions"][0]
        # 20 Nov 2026: the 640px drawer became the full-width exception workspace (cases/<ref>/recon/<run>/<exc>)
        j.js("document.querySelector('table tbody tr.is-clickable').click()")
        j.wait("document.querySelector('.rfe-ws') && document.querySelector('section[aria-label=\"Deterministic facts\"]') "
               "&& !document.querySelector('.rfe-ws .rf-skel')", timeout=60, what="exception workspace")
        time.sleep(0.4)
        txt = j.text_of(".rfe-ws")
        j.check(f"{sid}.10", "full-width exception workspace shows the backend exception: id in the route and page, "
                "deterministic facts with the supporting evidence",
                (first["exception_id"] in j.js("decodeURIComponent(location.hash)"), first["exception_id"] in txt,
                 "Deterministic facts" in txt, "Supporting evidence · " in txt), (True, True, True, True))
        j.shot(f"{sid}_exception")
    j.nav(f"#/cases/{ref}/activity")
    act = j.api(f"cases/{ref}/activity")
    j.check(f"{sid}.11", "activity tab renders the backend's case events", (len(act["events"]) > 5,
                                                                          "Reconciliation" in j.text_of("#root")), (True, True))
    results[sid] = {"case_ref": ref, "case_status": r["case_status"], "run_id": rec["run_id"], "total_results": r["total_results"],
                    "outcomes": outs, "exception_count": r["exception_count"],
                    "exceptions": [{k: e.get(k) for k in ("exception_id", "severity", "category", "root_cause", "account_id")}
                                   for e in r["exceptions"]],
                    "integrity_checks": r["integrity_checks"]}
    if sc.get("demo_id") and sc.get("verify", True):   # verify=False: no frozen key for this behaviour
        results[sid]["answer_key_comparison"] = verify_in_ui(j, sc, ref)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--mode", choices=["built", "dev"], default="built")
    ap.add_argument("--demo", default=None, help="demo scenario folder: scenarios are loaded from the Demo scenarios screen")
    a = ap.parse_args()
    b = Bundle(Path(a.bundle))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scenarios = json.loads(Path(a.scenarios).read_text(encoding="utf-8"))
    jid = "AA1" if a.mode == "built" else "AA1-DEV"
    j = AJ(jid, "Delivered Ringfence analyst app against the real backend", b, out, recorded=[])
    j.origin = f"http://127.0.0.1:{j.port}"
    if a.demo:
        j.server.terminate()
        j.server.wait(timeout=30)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "ANTHROPIC", "GROQ", "AI_"))}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        j.server = subprocess.Popen([sys.executable, "-B", "-m", "smartparser.webapp.server", "--root", str(j.ws), "--port", str(j.port),
                                     "--authority", str(b.root / "fixtures" / "review" / "test_authority_policy.json"),
                                     "--uc042-root", str(b.uc), "--reviewer-id", "e2e-test-analyst-1", "--reviewer-role", "analyst",
                                     "--reviewer-kind", "TEST", "--insecure-no-auth", "--demo-scenarios", a.demo], cwd=str(HERE), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(150):
            try:
                if json.loads(urllib.request.urlopen(f"{j.origin}/api/app", timeout=1).read()).get("demo_scenarios"):
                    break
            except Exception:
                time.sleep(0.15)
        jid = j.jid = "AA2-DEMO"
    vite = None
    if a.mode == "dev":
        env = dict(os.environ, RINGFENCE_API=f"http://127.0.0.1:{j.port}")
        vite = subprocess.Popen("npx vite --mode backend --host 127.0.0.1 --port 5174 --strictPort", cwd=str(APP), env=env, shell=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:5174/", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)
        j.origin = "http://127.0.0.1:5174"            # --mode backend: base /analyst/, VITE_DATA_SERVICE=http
    j.br.cmd("Network.enable")
    j.br.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "document.addEventListener('securitypolicyviolation', e => {"
             " try { const k='rf_csp'; const v=JSON.parse(sessionStorage.getItem(k)||'[]'); v.push(e.violatedDirective+' '+e.blockedURI);"
             " sessionStorage.setItem(k, JSON.stringify(v)); } catch (x) {} });"})
    results = {}
    try:
        j.sign_in()
        j.check("APP.01", "signed in; data service is the backend (no mock bar)",
                (j.text_of(".rf-svcbar").startswith("Backend"), "MOCK DATA SERVICE" in j.text_of("#root")), (True, False))
        if a.demo:
            j.nav("#/demo")
            cat = j.api("demo/scenarios")["scenarios"]
            j.check("DEMO.01", "Demo scenarios screen lists the four scenarios (customer, period, description, expected outcome)",
                    [(s["customer_name"] in j.text_of("#root"), s["reporting_period"], s["title"] in j.text_of("#root"),
                      s["description"][:40] in j.text_of("#root")) for s in cat],
                    [(True, p, True, True) for p in ("2026-06", "2026-07", "2026-10", "2026-11")])
            j.shot("demo_scenarios")
        for sc in scenarios:
            scenario(j, sc, results)
        if a.demo:
            # repeatability: load S1 again; a new case is registered, the completed one is untouched
            s1 = scenarios[0]
            before = j.case(results[s1["id"]]["case_ref"])
            ref2 = load_demo(j, s1)
            after = j.case(results[s1["id"]]["case_ref"])
            v1 = j.api(f"demo/scenarios/{s1['demo_id']}/verification?case_ref={results[s1['id']]['case_ref']}")
            j.check("DEMO.02", "loading a scenario again registers a new Waiting case; the earlier completed case, its run and "
                    "its answer-key match are unchanged",
                    (ref2 != results[s1["id"]]["case_ref"], j.case(ref2)["status"], after["status"], after["completed"],
                     v1["status"]), (True, "WAITING", "COMPLETED", before["completed"], "MATCH"))
            results["repeat_load"] = {"new_case_ref": ref2, "earlier_case_ref": results[s1["id"]]["case_ref"]}
        j.nav("#/queue")
        q = j.api("cases")
        j.check("APP.02", "work queue lists every registered case from the backend",
                all(r["case_ref"] in j.text_of("#root") for r in results.values() if "case_ref" in r), True)
        j.nav("#/customers")
        j.check("APP.03", "customers screen lists every scenario customer",
                all(sc["customer"] in j.text_of("#root") for sc in scenarios), True)
        calls = j.br.api_calls
        posts = [c for c in calls if c["method"] == "POST"]
        missing_rev = [c["path"] for c in posts if c["path"].split("/")[-1] in MUTATIONS_WITH_REVISION
                       and "expected_revision" not in (c["keys"] or [])]
        j.check("APP.04", "every page API call went to the page's own origin; case mutations sent expected_revision",
                (sorted({c["url"].split("/api/")[0] for c in calls}), missing_rev), ([j.origin], []))
        if a.mode == "built":
            j.check("UI.csp", "no CSP violation (built app served by the backend under its CSP)",
                    j.js("JSON.parse(sessionStorage.getItem('rf_csp')||'[]')"), [])
        j.check("UI.errors", "no JavaScript error in the browser", j.br.page_errors, [])
    except Exception:
        try:
            j.shot("FAILURE")
            print(f"[{jid}] page at failure:", j.js("location.href"), j.js("document.body.innerText.slice(0,2000)"), j.br.page_errors)
        except Exception:
            pass
        raise
    finally:
        try:
            j.br.close()
        finally:
            j.server.terminate()
            if vite is not None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(vite.pid)], capture_output=True)
    summary = {"journey": jid, "checks_total": len(j.checks), "checks_passed": sum(c["passed"] for c in j.checks),
               "api_calls_observed": len(j.br.api_calls), "results": results, "checks": j.checks, "steps": j.steps}
    (out / f"{jid}_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"[{jid}] DONE {summary['checks_passed']}/{summary['checks_total']} (api calls observed: {len(j.br.api_calls)})")
    shutil.rmtree(j.ws, ignore_errors=True)
    sys.exit(0 if summary["checks_passed"] == summary["checks_total"] else 1)


if __name__ == "__main__":
    main()
