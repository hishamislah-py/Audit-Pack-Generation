"""CANONICAL browser journey for the Ringfence analyst application (consolidated 19 Nov 2026).
Supersedes tools/live_server_journey.py once this journey passes.

    set RF_DEMO_EMAIL=<analyst email> & set RF_DEMO_PASSWORD=<password>
    py -3.11 -B tools/analyst_queue_journey.py --bundle <E2E bundle> --home <NEW test folder> --out <dir>

Runs on an ISOLATED test copy, never on the final demo home:
1. Creates <home>/auth.json with the existing password mechanism (auth.set_password: PBKDF2 hash only) for the email.
2. Starts the server exactly as tools/seed_analyst_demo.py does (sign-in on, --reviewer-id = the email, never
   --insecure-no-auth) WITH --demo-scenarios, so app.demo_scenarios is true and the Work Queue shows the demo section
   (there is no "Demo scenarios" nav item). Closure is NOT enabled here (no --closure-python): this journey covers
   sign-in, the queue and the pipeline up to reconciliation; tools/ringfence_full_journey.py covers closure and the PDF.
   It registers the five scenario ZIPs (seed_analyst_demo.SCENARIO_IDS) through the authenticated POST /api/cases.
3. In headless Edge: protected API refuses without a session -> sign in with email + password -> Work Queue (My cases)
   lists the five assigned cases in the existing date-based order (registration order; no priority) -> the session
   survives a page reload -> for each case press Start in the queue -> the normal Start confirmation -> the existing
   workflow runs to reconciliation (Thornbury, 20 Nov 2026 behaviour: the run COMPLETES with the CRC-corrupted IN-09
   member isolated; the corrected IN-09, rebuilt from a COPY of the ZIP, is uploaded through the Evidence tab; the case
   then reconciles CLEAN) -> audit identity = the email -> sign out invalidates the session.
Updated 20 Nov 2026 (final E2E round): 5 cases, Thornbury isolation instead of failure, demo section on, the server is
never started with --insecure-no-auth (QJ no longer builds the base Journey's harness server).
Every assertion reads the backend through the API (its own signed-in session) and compares it with the page.
Outcomes are compared with each scenario's expected_outcome.json only after the backend produced them.
The password is read from the environment and never printed or written."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE))
import analyst_app_journey as aaj  # noqa: E402
import seed_analyst_demo as seed_mod  # noqa: E402
from smartparser.webapp import auth as auth_mod  # noqa: E402
from webapp_journeys import Bundle  # noqa: E402


class QJ(aaj.AJ):
    """AJ with a signed-in API client (the server answers 401 without a session).

    Unlike Journey.__init__, this constructor starts NO server (the base class starts an --insecure-no-auth harness
    server); the caller starts the signed-in server (seed_analyst_demo.start_server) and sets port/origin/server."""

    def __init__(self, jid, title, bundle, out):
        import tempfile
        self.jid, self.title, self.b = jid, title, bundle
        self.out = Path(out) / jid
        self.inputs = Path(out) / "inputs" / jid
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self.inputs.mkdir(parents=True, exist_ok=True)
        self.ws = Path(tempfile.mkdtemp(prefix=f"u42q_{jid}_"))         # browser profile only
        self.steps, self.checks, self.shots = [], [], 0
        self.port, self.origin, self.server = None, None, None
        self.br = aaj.rfj.webapp_journeys.Edge(self.ws / "edge_profile")
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1,
                                                           "mobile": False})

    def attach(self, username, password):
        self.username, self.password = username, password
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/auth/login", method="POST",
                                     data=json.dumps({"username": username, "password": password}).encode(),
                                     headers={"Content-Type": "application/json", "X-Smartparser-Client": "webapp"})
        assert json.loads(self.op.open(req, timeout=30).read())["authenticated"]

    def api(self, path):
        return json.loads(self.op.open(f"http://127.0.0.1:{self.port}/api/{path}", timeout=30).read())

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Smartparser-Client": "webapp"})
        return json.loads(self.op.open(req, timeout=60).read())

    def page_api_status(self, path):
        """Status of a same-origin request sent by the PAGE (with the browser's own session cookie)."""
        return self.js(f"(() => {{ const x = new XMLHttpRequest(); x.open('GET', '/api/{path}', false); x.send(); "
                       "return x.status; })()")

    def sign_in(self):
        self.go("#/login")
        self.wait("document.querySelector('input[autocomplete=\"username\"]')", what="sign-in form")
        self.set_value("input[autocomplete=\"username\"]", self.username)
        self.set_value("input[autocomplete=\"current-password\"]", self.password)
        self.button("Sign in")
        self.wait("location.hash.startsWith('#/queue')", what="queue after sign-in")
        self.settle()


def start_from_queue(j: QJ, sc) -> str:
    """Replaces registration: the case already exists. Work Queue (My cases) -> Start -> the Start confirmation opens."""
    ref = sc["case_ref"]
    j.nav("#/queue")
    sel = f"document.querySelector('button[aria-label=\"Start {ref}\"]')"
    j.wait(f"{sel} && !{sel}.disabled", timeout=60, what=f"Start button for {ref} in the queue")
    j.js(f"{sel}.click()")
    j.wait(f"location.hash.startsWith('#/cases/{ref}/overview')", what="case opened from the queue")
    j.wait(f"{j.DLG} !== document && {j.DLG}.innerText.includes('Start Smart Parsing for this case?')", timeout=30,
           what="Start confirmation opened by the queue Start")
    j.check(f"{sc['id']}.00", "queue Start opened the case with the normal Start confirmation (nothing started yet)",
            (j.case(ref)["status"], j.js("location.hash")), ("WAITING", f"#/cases/{ref}/overview"))
    j.shot(f"{sc['id']}_start_confirmation")
    return ref


def thornbury_correction(meta, cur, folder: Path) -> dict:
    """Corrected IN-09 for the Thornbury scenario: restore the XORed CRC fields in a COPY of the scenario ZIP (the
    original is only read) and extract the member. Returns aaj.correct_unreadable_member's `iso` argument."""
    import hashlib
    import io
    import zipfile
    member = cur["expected_member_isolation"]["unreadable_member"]
    zb = Path(meta["_zip"]).read_bytes()
    fixed = aaj.restore_crc(zb, member)
    data = zipfile.ZipFile(io.BytesIO(fixed)).read(member)                  # full CRC check passes on the copy
    assert hashlib.sha256(data).hexdigest().startswith(cur["expected_after_corrected_in09"]["corrected_member_sha256"])
    folder = Path(folder) / "thornbury_correction"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / Path(member).name
    f.write_bytes(data)
    return {"member": member, "category": cur["expected_member_isolation"]["missing_required_before_correction"][0],
            "file": str(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--home", required=True, help="NEW folder for the journey's own isolated test copy")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", default=str(seed_mod.DEFAULT_SCENARIOS))
    a = ap.parse_args()
    email, pw = os.environ.get("RF_DEMO_EMAIL") or "", os.environ.get(seed_mod.PASSWORD_ENV) or ""
    if not (seed_mod.EMAIL_RE.match(email) and pw):
        raise SystemExit("set RF_DEMO_EMAIL (an email address) and RF_DEMO_PASSWORD")
    b = Bundle(Path(a.bundle))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    home = Path(a.home).resolve()
    seed_mod.check_home(home)
    if home.exists():
        raise SystemExit(f"{home} exists; the journey needs a NEW folder")
    home.mkdir(parents=True)
    auth_mod.set_password(home / "auth.json", email, pw)                 # the existing mechanism (hash only)
    port = aaj.rfj.webapp_journeys.free_port()

    j = QJ("AQ1", "Ringfence analyst app: email sign-in, assigned Work Queue, Start, Smart Parser, reconciliation",
           b, out)
    j.port = port
    j.origin = f"http://127.0.0.1:{port}"
    j.server = seed_mod.start_server(home, seed_mod.analyst_of(home), port, b.uc, "server_journey.log",
                                     scenarios_dir=Path(a.scenarios))      # demo section on; closure off
    try:
        made = seed_mod.seed(home, email, pw, port, Path(a.scenarios), b.uc)  # 5 cases via the authenticated API
        j.attach(email, pw)
    except BaseException:                                  # never leave the server or the browser running
        j.br.close()
        j.server.terminate()
        j.server.wait(timeout=30)
        raise
    aaj.register = lambda jj, sc: start_from_queue(jj, sc)             # the scenario flow starts from the queue

    metas = {m["scenario_id"]: m for m in seed_mod.scenarios(Path(a.scenarios))}
    keys = {sid: json.loads((m["_zip"].parent / "expected_outcome.json").read_text(encoding="utf-8")) for sid, m in metas.items()}
    by_sid = {c["scenario_id"]: c for c in made}
    plan = []
    for sid in seed_mod.SCENARIO_IDS:
        m, c, k = metas[sid], by_sid[sid], keys[sid]
        if sid == "RF-DEMO-04":       # 20 Nov 2026: member isolation (expected_outcome_current.json), not a run failure
            cur = json.loads((m["_zip"].parent / "expected_outcome_current.json").read_text(encoding="utf-8"))
            keys[sid] = {"expected_case_status": cur["expected_after_corrected_in09"]["case_status"],
                         "expected_counts": {"FAIL": 0, "INSUFFICIENT_EVIDENCE": 0},
                         "expected_exception_count": cur["expected_after_corrected_in09"]["exceptions"]}
            exp = {"case_status": keys[sid]["expected_case_status"],
                   "member_isolation": thornbury_correction(m, cur, j.inputs)}
        else:
            exp = {"case_status": k["expected_case_status"]}
        plan.append({"id": sid, "case_ref": c["case_ref"], "zip": str(m["_zip"]), "customer": m["customer_name"],
                     "period": m["reporting_period"], "expect": exp})

    j.br.cmd("Network.enable")
    j.br.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "document.addEventListener('securitypolicyviolation', e => {"
             " try { const k='rf_csp'; const v=JSON.parse(sessionStorage.getItem(k)||'[]'); v.push(e.violatedDirective+' '+e.blockedURI);"
             " sessionStorage.setItem(k, JSON.stringify(v)); } catch (x) {} });"})
    results = {}
    try:
        # ---- authentication
        def unauth_status(path):
            try:
                urllib.request.urlopen(f"{j.origin}/api/{path}", timeout=10)
                return 200
            except urllib.error.HTTPError as e:
                return e.code
        j.check("AUTH.01", "protected API routes answer 401 without a session",
                [unauth_status(p) for p in ("cases", "app", "customers", f"cases/{plan[0]['case_ref']}")], [401] * 4)
        j.go("#/queue")
        j.check("AUTH.02", "opening the app without a session shows the sign-in form, no case data",
                (bool(j.js("!!document.querySelector('input[autocomplete=\"current-password\"]')")),
                 plan[0]["customer"] in j.text_of("#root")), (True, False))
        j.username, j.password = email, "wrong-" + "x" * 8
        j.go("#/login")
        j.wait("document.querySelector('input[autocomplete=\"username\"]')", what="sign-in form")
        j.set_value("input[autocomplete=\"username\"]", email)
        j.set_value("input[autocomplete=\"current-password\"]", j.password)
        j.button("Sign in")
        j.wait("document.body.innerText.includes('Incorrect username or password')", what="wrong-password message")
        j.check("AUTH.03", "a wrong password is refused and no session is created", j.page_api_status("cases"), 401)
        j.username, j.password = email, pw
        j.sign_in()
        j.check("AUTH.04", "email + password sign-in lands on the Work Queue", j.js("location.hash.split('?')[0]"), "#/queue")
        cookie = j.br.cmd("Network.getCookies", {"urls": [j.origin]})["cookies"]
        rf = [c for c in cookie if c["name"] == "rf_session"]
        j.check("AUTH.05", "session cookie is HttpOnly and SameSite=Strict", [(c["httpOnly"], c.get("sameSite")) for c in rf],
                [(True, "Strict")])
        app = j.api("app")
        j.check("AUTH.06", "the email is both the sign-in identity and the recorded reviewer identity; demo scenarios on",
                (j.api("auth/session")["user"]["username"], app["reviewer"]["reviewer_id"], app.get("demo_scenarios")),
                (email, email, True))
        # ---- Work Queue
        loads = "document.querySelectorAll('#demo-scenarios button[aria-label^=\"Load scenario\"]').length"
        j.wait(f"document.querySelector('#demo-scenarios') && {loads}", what="demo section in the Work Queue")
        j.check("Q.01", "no Demo nav item; the demo scenarios are a section of the Work Queue (5 scenarios); no priority",
                ("Demo" in j.text_of(".rf-nav"), j.js(loads), "Priority" in j.text_of("#root")),
                (False, len(seed_mod.SCENARIO_IDS), False))
        q = j.api("cases?assigned=me")
        every = j.api("cases")
        txt = j.text_of("#root")
        n = len(seed_mod.SCENARIO_IDS)
        j.check("Q.02", "My cases lists the five assigned cases from the backend (customer, period, Waiting, assignee)",
                [(x["case_ref"] in txt, x["customer_name"] in txt, x["status"], x["assigned_to"], "priority" in x)
                 for x in q["items"]], [(True, True, "WAITING", email, False)] * n)
        j.check("Q.03", "existing date-based order unchanged: the filter keeps the unfiltered order, which here is "
                "WAITING oldest received first (created_at, ties by case reference); no priority",
                ([x["case_ref"] for x in q["items"]] == [x["case_ref"] for x in every["items"] if x["assigned_to"] == email],
                 [x["case_ref"] for x in q["items"]], q["ordering"]),
                (True, [x["case_ref"] for x in sorted(q["items"], key=lambda x: (x["created_at"], x["case_ref"]))],
                 "in progress first; then WAITING and PENDING oldest first; then COMPLETED newest first"))
        rows_ui = j.js("[...document.querySelectorAll('table tbody tr')].map(r => r.innerText).filter(t => /RF-\\d{4}-\\d{2}-\\d{3}/.test(t))"
                       ".map(t => t.match(/RF-\\d{4}-\\d{2}-\\d{3}/)[0])")
        j.check("Q.04", "the page shows the rows in the backend's order (never re-sorted)", rows_ui, [x["case_ref"] for x in q["items"]])
        j.check("Q.05", "each Waiting row offers Start",
                [bool(j.js(f"!!document.querySelector('button[aria-label=\"Start {s['case_ref']}\"]')")) for s in plan], [True] * n)
        j.shot("queue_my_cases")
        j.go("#/queue")                                                  # full page reload: the session survives
        j.wait("location.hash.startsWith('#/queue') && document.querySelector('table')", what="queue after reload")
        j.check("AUTH.07", "session persists across a page reload (no new sign-in)",
                (plan[0]["customer"] in j.text_of("#root"), j.page_api_status("cases")), (True, 200))
        # ---- each case through the existing workflow
        for sc in plan:
            aaj.scenario(j, sc, results)
            k = keys[sc["id"]]
            if True:
                r = results[sc["id"]]
                got = {"case_status": r["case_status"], "FAIL": r["outcomes"].get("FAIL", 0),
                       "INSUFFICIENT_EVIDENCE": r["outcomes"].get("INSUFFICIENT_EVIDENCE", 0), "exceptions": r["exception_count"]}
                want = {"case_status": k["expected_case_status"], "FAIL": k["expected_counts"].get("FAIL", 0),
                        "INSUFFICIENT_EVIDENCE": k["expected_counts"].get("INSUFFICIENT_EVIDENCE", 0),
                        "exceptions": k.get("expected_exception_count", 0)}
                j.check(f"{sc['id']}.K", "backend result equals the scenario's frozen expected_outcome.json (compared after the run)",
                        got, want)
        # ---- audit identity and queue afterwards
        act = j.api("activity")
        ev = [e for e in act.get("events", []) if e.get("event_type", "").startswith(("ANALYST_", "CASE_STARTED", "CASE_CREATED"))]
        j.check("AUD.01", "audit chain verified; analyst actions and registrations are attributed to the email",
                (act["chain"]["verified"], len(ev) > 0, sorted({e.get("actor_id") for e in ev})), (True, True, [email]))
        created = [e["details"].get("assigned_to") for e in act["events"] if e["event_type"] == "CASE_CREATED"]
        j.check("AUD.02", "each CASE_CREATED audit event records the assignment to the email", created, [email] * n)
        j.nav("#/queue")
        q = j.api("cases?assigned=me")
        j.check("Q.06", "queue afterwards: all five cases Completed (Thornbury after its isolated member was corrected)",
                sorted((x["customer_name"], x["status"]) for x in q["items"]),
                sorted((p["customer"], "COMPLETED") for p in plan))
        j.shot("queue_after")
        calls = j.br.api_calls
        posts = [c for c in calls if c["method"] == "POST"]
        missing_rev = [c["path"] for c in posts if c["path"].split("/")[-1] in aaj.MUTATIONS_WITH_REVISION
                       and "expected_revision" not in (c["keys"] or [])]
        j.check("APP.04", "every page API call went to the page's own origin; case mutations sent expected_revision",
                (sorted({c["url"].split("/api/")[0] for c in calls}), missing_rev), ([j.origin], []))
        j.check("APP.05", "the page requested the queue with assigned=me",
                any(c["path"].startswith("cases?") and "assigned=me" in c["path"] for c in calls), True)
        # ---- sign out
        j.js("document.querySelector('.rf-avatar').closest('button').click()")          # analyst menu
        j.button("Sign out", timeout=20)
        j.wait("location.hash.startsWith('#/login')", what="sign-in screen after sign-out")
        j.check("AUTH.08", "sign out returns to the sign-in screen and the old session no longer works",
                (j.page_api_status("cases"), plan[0]["customer"] in j.text_of("#root")), (401, False))
        j.check("UI.csp", "no CSP violation", j.js("JSON.parse(sessionStorage.getItem('rf_csp')||'[]')"), [])
        j.check("UI.errors", "no JavaScript error in the browser",
                [e for e in j.br.page_errors if "401" not in str(e)], [])
    except Exception:
        try:
            j.shot("FAILURE")
            print("[AQ1] page at failure:", j.js("location.href"), j.js("document.body.innerText.slice(0,1500)"), j.br.page_errors)
        except Exception:
            pass
        raise
    finally:
        try:
            j.br.close()
        finally:
            j.server.terminate()
            j.server.wait(timeout=30)
    summary = {"journey": "AQ1", "home": str(home), "checks_total": len(j.checks),
               "checks_passed": sum(c["passed"] for c in j.checks), "api_calls_observed": len(j.br.api_calls),
               "results": results, "checks": j.checks, "steps": j.steps}
    (out / "AQ1_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"[AQ1] DONE {summary['checks_passed']}/{summary['checks_total']}")
    shutil.rmtree(j.ws, ignore_errors=True)
    sys.exit(0 if summary["checks_passed"] == summary["checks_total"] else 1)


if __name__ == "__main__":
    main()
