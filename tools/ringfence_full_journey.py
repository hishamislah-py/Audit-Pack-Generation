"""FINAL end-to-end journey of the Ringfence analyst application: the ONE pipeline, from a manual ZIP upload (or a demo
scenario loaded from the Work Queue) to a verified, downloaded final PDF, driven in headless Edge through the real UI
against the real server, real Smart Parser, real UC-042 engine and real closure library (20 Nov 2026).

    set RF_DEMO_EMAIL=<analyst email> & set RF_DEMO_PASSWORD=<password>      (never printed or written)
    py -3.11 -B tools/ringfence_full_journey.py --out C:\\u42v\\e2e\\out --home-a C:\\u42v\\e2e\\a1 --home-b C:\\u42v\\e2e\\b1
    (options: --run A|B|AB, --ai-budget 40, --bundle, --scenarios, --closure-python, --ai-env-file, --manual-inputs)

Setup (each run): a NEW short home folder with auth.json holding ONE email user (smartparser.webapp.auth.set_password,
PBKDF2 hash only); the server is started through seed_analyst_demo.start_server with --auth-file, --demo-scenarios and
--closure-python (never --insecure-no-auth). No case is seeded: every case is registered through the UI.

Run A (live AI: --ai-env-file, --ai-max-requests-per-operation 3; total OpenAI calls must stay <= --ai-budget):
  login checks; MANUAL upload of a copy of s05_unexplained_difference_2026-09.zip through Register case (customer and
  period typed) -> Start -> Smart Parser -> review only if required -> validation & activation -> reconcile
  (EXCEPTIONS_OPEN, 2 exceptions) -> audit pack GENERATED -> automatic AI investigations -> full-width exception
  workspace (3 sections, "AI-generated") -> ACCEPT one / REJECT one -> Closing tab: readiness, selections, preview with
  the AI confirm dialog, preview reuse -> acknowledgements -> GENERATE -> verified -> PDF downloaded through the UI link
  (SHA-256 = manifest; text checks with pypdf). Then Marlow (RF-DEMO-02) loaded with the Work Queue's Load scenario
  button, through the same steps. Then a server restart (closure, decisions and final pack survive; verify OK) and logout.
Run B (AI OFF: no --ai-env-file): Halden (CLEAN, NOT_REQUIRED summary), Corvane (EVIDENCE_INCOMPLETE, audit pack
  UNAVAILABLE, no PDF), Thornbury (IN-09 isolated, corrected IN-09 uploaded through the UI, CLEAN), Pellworth (17/17,
  NOT_INVESTIGATED, summary UNAVAILABLE + acknowledgement) and a MANUAL upload of clean_submission_2026-09.zip.
  Thornbury reconciles CLEAN but its audit pack is UNAVAILABLE (uc042lib.pack V6: a header-only unallocated register
  yields no C09-ALLOCATION result; same reason as Corvane); the journey asserts that honest outcome.
Throughout: audit chain verified, no JS errors, no CSP violations. Nothing here is scenario-specific in the product;
expected outcomes are compared only after the backend produced them."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE))
import analyst_app_journey as aaj  # noqa: E402
import analyst_queue_journey as aqj  # noqa: E402
import seed_analyst_demo as seed_mod  # noqa: E402
from smartparser.webapp import auth as auth_mod  # noqa: E402
from webapp_journeys import Bundle, free_port  # noqa: E402

DEFAULT_BUNDLE = Path(r"C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE")
MANUAL_INPUTS = Path(r"C:\Users\artlptp263user\Downloads\RINGFENCE_DEMO_INPUTS")
# Renderer 3.x section titles (uc042lib.final_pack.report_v3.build_report_v3); "Exceptions and investigations" only
# when the exception register is not empty (9 sections with exceptions, 8 without).
SECTIONS = ["Executive outcome", "Reconciliation overview", "Account-level results", "Financial and daily details",
            "Evidence completeness and source inventory", "Exceptions and investigations",
            "Analyst review and decision record", "Limitations and disclosures", "Technical appendix"]
FINAL_AI = ("PUBLISHED", "NOT_PUBLISHED", "FAILED", "UNAVAILABLE")
PDF_TEXT = ("import pypdf, sys\n"
            "r = pypdf.PdfReader(sys.argv[1])\n"
            "open(sys.argv[2], 'w', encoding='utf-8').write('\\n'.join((p.extract_text() or '') for p in r.pages))\n")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FJ(aqj.QJ):
    """Signed-in journey with its own server lifecycle (sign-in always on) and closure helpers."""

    def setup(self, home: Path, email: str, scenarios: Path, closure_python: Path, ai_env: Path | None, extra: list):
        self.home, self.email, self.scen, self.cp, self.ai_env, self.extra = home, email, scenarios, closure_python, ai_env, extra
        self.port = free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.dl = self.out / "downloads"
        self.dl.mkdir(parents=True, exist_ok=True)
        self.start()

    def start(self):
        self.server = seed_mod.start_server(self.home, self.email, self.port, self.b.uc, "server.log",
                                            scenarios_dir=self.scen, closure_python=self.cp, ai_env_file=self.ai_env,
                                            extra_args=self.extra)
        cmd = " ".join(seed_mod.server_cmd(self.home, self.email, self.port, self.b.uc, self.scen, self.cp,
                                           self.ai_env, self.extra))
        assert "--insecure-no-auth" not in cmd and "--auth-file" in cmd
        self.step("server started (sign-in on)", flags=[x for x in cmd.split() if x.startswith("--")])

    def stop(self):
        if self.server is not None and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.server.kill()

    def get_status(self, path):
        try:
            self.op.open(f"{self.origin}/api/{path}", timeout=30).read()
            return 200
        except urllib.error.HTTPError as e:
            return e.code

    def raw(self, path) -> bytes:
        return self.op.open(f"{self.origin}/api/{path}", timeout=120).read()

    def cl(self, ref):
        try:
            return self.api(f"cases/{ref}/closure")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def wait_cl(self, ref, cond, timeout=900, what=""):
        end, last = time.time() + timeout, 0
        while time.time() < end:
            c = self.cl(ref)
            if c is not None and cond(c):
                return c
            if c is not None and time.time() - last > 60:
                last = time.time()
                self.step(f"  waiting for {what}: state {c['state']}",
                          ai=[e["ai_state"] for e in c["exceptions"]], calls=c["usage"]["calls"])
            time.sleep(1.5)
        raise AssertionError(f"timeout waiting for {what}")

    def enable_downloads(self):
        params = {"behavior": "allow", "downloadPath": str(self.dl)}
        try:
            self.br.cmd("Browser.setDownloadBehavior", dict(params, eventsEnabled=False))
        except RuntimeError:
            self.br.cmd("Page.setDownloadBehavior", params)

    def ui_download(self, label) -> Path:
        """Click the Download link of a final-pack file in the Closing tab (a real browser download)."""
        before = {p.name for p in self.dl.iterdir()}
        ok = self.js("(() => { const li = [...document.querySelectorAll('.rfe-downloads li')].find(l => "
                     f"l.innerText.includes({json.dumps(label)})); if (!li) return false; "
                     "const a = li.querySelector('a[download]'); if (!a) return false; a.click(); return true; })()")
        assert ok, f"no Download link for {label}"
        end = time.time() + 90
        while time.time() < end:
            new = [p for p in self.dl.iterdir() if p.name not in before and not p.name.endswith((".crdownload", ".tmp"))]
            if new and new[0].stat().st_size > 0:
                time.sleep(0.5)
                return new[0]
            time.sleep(0.3)
        raise AssertionError(f"download of {label} did not complete")

    def pdf_text(self, pdf: Path) -> str:
        out = pdf.with_suffix(".txt")
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "UC042_", "GROQ"))}
        subprocess.run([str(self.cp), "-I", "-B", "-c", PDF_TEXT, str(pdf), str(out)], check=True, env=env, timeout=120)
        return out.read_text(encoding="utf-8")

    def sign_in_ui(self, email, pw):
        self.username, self.password = email, pw
        self.sign_in()

    def ws_url(self, ref, run, exc):
        return f"#/cases/{ref}/recon/{run}/{exc}"

    def open_ws(self, ref, run, exc):
        self.nav(self.ws_url(ref, run, exc))
        self.wait("document.querySelector('.rfe-ws') && document.querySelector('section[aria-label=\"AI investigation\"]') "
                  "&& document.querySelector('section[aria-label=\"Analyst decision\"]') "
                  "&& document.querySelector('section[aria-label=\"Deterministic facts\"]') "
                  "&& !document.querySelector('.rfe-ws .rf-skel')", timeout=60, what=f"exception workspace {exc}")
        time.sleep(0.4)


SEC = lambda name: f"document.querySelector('section[aria-label=\"{name}\"]')"  # noqa: E731


# ================================================================================================ steps
def auth_checks(j: FJ, email, pw, customer_hint):
    def unauth(path):
        try:
            urllib.request.urlopen(f"{j.origin}/api/{path}", timeout=10)
            return 200
        except urllib.error.HTTPError as e:
            return e.code
    j.check("AUTH.01", "an unauthenticated API call is refused (401)",
            [unauth(p) for p in ("cases", "app", "ai/configuration", "demo/scenarios")], [401] * 4)
    j.go("#/login")
    j.wait("document.querySelector('input[autocomplete=\"username\"]')", what="sign-in form")
    j.set_value("input[autocomplete=\"username\"]", email)
    j.set_value("input[autocomplete=\"current-password\"]", "wrong-" + "x" * 10)
    j.button("Sign in")
    j.wait("document.querySelector('[role=alert]') && document.querySelector('[role=alert]').innerText.length > 0",
           what="wrong-password message")
    msg = j.text_of("[role=alert]")
    j.check("AUTH.02", "a wrong password shows a clear error and creates no session",
            ("Sign-in failed" in msg, "Incorrect username or password" in msg, j.page_api_status("cases")), (True, True, 401))
    j.shot("login_wrong_password")
    j.sign_in_ui(email, pw)
    j.check("AUTH.03", "a correct email + password sign-in lands on the Work Queue",
            (j.js("location.hash.split('?')[0]"), "Work queue" in j.text_of("#root")), ("#/queue", True))
    j.go("#/queue")                                                      # full page reload
    j.wait("location.hash.startsWith('#/queue') && document.querySelector('.rf-page')", what="queue after reload")
    j.check("AUTH.04", "the session survives a page refresh",
            (j.page_api_status("cases"), "Work queue" in j.text_of("#root"), bool(j.js("!!document.querySelector('input[autocomplete=\"current-password\"]')"))),
            (200, True, False))
    j.attach(email, pw)
    app = j.api("app")
    j.check("AUTH.05", "signed-in identity = recorded reviewer identity = the email; demo section on, no Demo nav item",
            (j.api("auth/session")["user"]["username"], app["reviewer"]["reviewer_id"], app.get("demo_scenarios"),
             "Demo" in j.text_of(".rf-nav"), bool(j.js("!!document.querySelector('#demo-scenarios')"))),
            (email, email, True, False, True))


def recon_run_id(j: FJ, ref):
    return j.case(ref)["progress"]["reconciliation"]["run_id"]


def closing(j: FJ, sid, ref, mode, report):
    """Closure through the UI. mode = {ai: bool, decisions: [ACCEPT|REJECT...] applied to published findings in order,
    ws_ui: max exceptions opened in the workspace, expect_pack: GENERATED|UNAVAILABLE, summary: expected status}"""
    run = recon_run_id(j, ref)
    cl = j.wait_cl(ref, lambda x: x["pack"]["status"] in ("GENERATED", "UNAVAILABLE"), 900, "audit pack")
    report.update(recon_run_id=run, pack=cl["pack"])
    j.check(f"{sid}.C01", f"audit pack {mode['expect_pack']} after reconciliation (closure record for the run)",
            (cl["pack"]["status"], cl["recon_run_id"]), (mode["expect_pack"], run))
    if mode["expect_pack"] == "UNAVAILABLE":
        return closing_unavailable(j, sid, ref, cl, report)
    excs = [e["exception_id"] for e in cl["exceptions"]]
    report["exceptions"] = excs
    if excs and mode["ai"]:
        cl = j.wait_cl(ref, lambda x: x["state"] != "INVESTIGATING" and all(e["ai_state"] in FINAL_AI for e in x["exceptions"]),
                       3000, "automatic AI investigations")
        auths = [e for e in j.api(f"cases/{ref}/closure/history")["events"] if e.get("event_type") == "AI_AUTHORIZED"]
        j.check(f"{sid}.C02", "automatic AI investigations ran for every exception: each PUBLISHED, or NOT_PUBLISHED / "
                "FAILED with a reason; AUTO_INVESTIGATION authorised by the user who reconciled",
                (all(e["ai_state"] in ("PUBLISHED", "NOT_PUBLISHED", "FAILED") for e in cl["exceptions"]),
                 [ex for ex in cl["exceptions"] if ex["ai_state"] != "PUBLISHED" and not no_pub_reason(j, ref, ex["exception_id"])],
                 bool(auths) and auths[0].get("actor_id") == j.email), (True, [], True))
    elif excs:
        j.check(f"{sid}.C02", "AI off: every exception's AI state is UNAVAILABLE (honest, nothing mocked); "
                "the closure shows the AI problem", (sorted({e["ai_state"] for e in cl["exceptions"]}), cl["ai"]["available"],
                                                     bool(cl["ai"]["problem"])), (["UNAVAILABLE"], False, True))
    report["ai_states"] = {e["exception_id"]: e["ai_state"] for e in cl["exceptions"]}
    for e in cl["exceptions"]:
        if e["ai_state"] != "PUBLISHED":
            report.setdefault("not_published_reasons", {})[e["exception_id"]] = no_pub_reason(j, ref, e["exception_id"])
    # ---- the full-width workspace: three sections, the AI label
    shown = cl["exceptions"][:mode.get("ws_ui", len(excs))]
    sec_ok = []
    for e in shown:
        j.open_ws(ref, run, e["exception_id"])
        ai_txt = j.js(f"{SEC('AI investigation')}.innerText")
        ok = (e["exception_id"] in j.text_of(".rfe-ws"), "AI-generated" in ai_txt,
              "Deterministic facts" in j.text_of(".rfe-ws"), "Analyst decision" in j.text_of(".rfe-ws"))
        ok += ('{"' not in ai_txt,)                    # no raw JSON object rendered in section B
        if e["ai_state"] == "PUBLISHED":
            inv = j.api(f"cases/{ref}/closure/exceptions/{e['exception_id']}")["investigation"] or {}
            hyps = [h for h in inv.get("hypotheses") or [] if isinstance(h, dict)]
            if hyps:                                     # hypotheses rendered field by field, chips resolved
                hyp_txt = j.js(f"(([...{SEC('AI investigation')}.querySelectorAll('.rfe-cards--hyp')].pop()) || {{}}).innerText || ''")
                ok += ("HYPOTHESIS – NOT ESTABLISHED" in hyp_txt, (hyps[0].get("possible_explanation") or "")[:40] in hyp_txt,
                       "unresolved" not in hyp_txt)
        if e["ai_state"] == "UNAVAILABLE":
            ok += ("AI is not available on this server" in ai_txt,)
        elif e["ai_state"] != "PUBLISHED":
            ok += ((report["not_published_reasons"][e["exception_id"]] or "") [:40] in ai_txt,)
        sec_ok.append(all(ok))
        if len(sec_ok) <= 2:
            j.shot(f"{sid}_workspace_{e['exception_id']}")
    j.check(f"{sid}.C03", f"full-width exception workspace renders A facts / B AI investigation / C decision with the "
            f"'AI-generated' label, no raw JSON, hypotheses as fields with resolved citation chips "
            f"({len(shown)} exception(s) opened)", sec_ok, [True] * len(shown))
    # ---- analyst decisions through the UI
    elig = {e["exception_id"]: e["ai_state"] == "PUBLISHED" and bool(e["investigation_id"]) and
            j.api(f"cases/{ref}/closure/exceptions/{e['exception_id']}")["decision"]["actions"]["accept"]["enabled"] or
            bool(e["analyst_decision"]) for e in cl["exceptions"]}
    report["not_eligible"] = [e["exception_id"] for e in cl["exceptions"] if e["ai_state"] == "PUBLISHED" and not elig[e["exception_id"]]]
    pub = [e for e in cl["exceptions"] if e["ai_state"] == "PUBLISHED" and elig[e["exception_id"]]]
    plan = list(zip(pub, mode.get("decisions") or []))
    for e, d in plan:
        if e["analyst_decision"] == d:                              # --resume: already decided
            continue
        decide_ui(j, ref, run, e["exception_id"], d)
    cl = j.cl(ref)
    if plan:
        j.check(f"{sid}.C04", "ACCEPT / REJECT of AI findings recorded through the UI, by the signed-in user",
                [(x["exception_id"], x["analyst_decision"], x["decided_by"]) for x in cl["exceptions"] if x["analyst_decision"]],
                [(e["exception_id"], d, j.email) for e, d in plan])
    report["decisions"] = [(e["exception_id"], d) for e, d in plan]
    if mode.get("require_decisions"):
        # Changed 20 Nov 2026 (coordinator): an investigation that is legitimately NOT_PUBLISHED / FAILED (e.g. the
        # 3-requests-per-operation cost cap, or deterministic validation refusing it) cannot be decided. The per-case
        # check is therefore ">= 1 decision recorded and every undecided exception is non-published WITH a reason";
        # ACCEPT and REJECT must both be covered across the run (check A.DEC).
        undecided = [e["exception_id"] for e in cl["exceptions"] if not e["analyst_decision"]]
        j.check(f"{sid}.C04b", ">= 1 AI finding decided; every undecided exception is NOT_PUBLISHED/FAILED with a reason",
                (len(plan) >= 1, [x for x in undecided if not (report.get("not_published_reasons") or {}).get(x)]), (True, []))
    # ---- Closing tab
    j.nav(f"#/cases/{ref}/closing")
    j.wait("document.querySelector('.rfe-closing')", what="Closing tab")
    txt = j.text_of(".rfe-closing")
    j.check(f"{sid}.C05", "Closing tab shows the deterministic summary (System-generated, not AI), readiness and the AI "
            "configuration from the backend", ("System-generated, not AI" in txt, "Readiness" in txt,
                                               ("Available" in txt)), (True, True, True))
    done = bool(cl.get("final_pack") and cl["final_pack"].get("verified"))       # --resume: already generated
    if not j.cl(ref)["review"]["review_id"]:
        j.button("Open closing review")
    cl = j.wait_cl(ref, lambda x: bool(x["review"]["review_id"]), 60, "closing review opened")
    # failed / not-published / not-eligible investigations need a disposition: exclude them (fixed choice, no free text)
    to_exclude = [e["exception_id"] for e in cl["exceptions"] if e["ai_state"] in ("NOT_PUBLISHED", "FAILED")
                  or e["exception_id"] in report["not_eligible"]]
    for exc in to_exclude:
        if done or any(x["exception_id"] == exc and x["inclusion"] == "EXCLUDED_BY_ANALYST" for x in j.cl(ref)["review"]["selections"]):
            continue
        j.wait("!document.querySelector('.rf-btn.is-loading')", what="idle")
        ok = j.js("(() => { const t = [...document.querySelectorAll('table')].find(t => (t.querySelector('caption') || {}).textContent === 'Selections');"
                  f" if (!t) return false; const r = [...t.querySelectorAll('tbody tr')].find(r => r.textContent.includes({json.dumps(exc)}));"
                  " if (!r) return false; const b = [...r.querySelectorAll('button[role=radio]')].find(b => b.textContent === 'Excluded');"
                  " if (!b) return false; b.click(); return true; })()")
        assert ok, f"no Excluded choice for {exc}"
        j.wait_cl(ref, lambda x: any(s["exception_id"] == exc and s["inclusion"] == "EXCLUDED_BY_ANALYST"
                                     for s in x["review"]["selections"]), 60, f"{exc} excluded")
        time.sleep(0.6)
    cl = j.cl(ref)
    sels = {s["exception_id"]: s["inclusion"] for s in cl["review"]["selections"]}
    report["selections"] = sels
    if excs:
        want = mode.get("selections") or {e["exception_id"]: ("EXCLUDED_BY_ANALYST" if e["exception_id"] in to_exclude else
                                                             "INCLUDED" if e["ai_state"] == "PUBLISHED" else "NOT_INVESTIGATED")
                                          for e in cl["exceptions"]}
        if callable(want):
            want = want(cl)
        j.check(f"{sid}.C06", "selections from the backend (published → INCLUDED, failed → EXCLUDED_BY_ANALYST, "
                "AI unavailable → NOT_INVESTIGATED)", sels, want)
    if not done:
        j.check(f"{sid}.C07", "readiness: only the preview blocks closure now", [b for b in cl["review"]["readiness"]["blockers"]
                                                                             if not b.startswith(("Preview required", "Preview stale"))], [])
        preview_and_generate(j, sid, ref, cl, excs, mode, report)
    cl = j.cl(ref)
    fp = j.api(f"cases/{ref}/closure/final-pack")
    j.check(f"{sid}.C12", "GENERATE: final pack generated, verified, closure frozen, authorised by the signed-in email",
            (cl["state"], cl["frozen"], fp["status"], fp["verified"], fp["problems"], fp["authorised_by"]),
            ("GENERATED", True, "GENERATED", True, [], j.email))
    j.nav(f"#/cases/{ref}/closing")
    j.wait("document.querySelector('.rfe-verified')", timeout=60, what="Verified badge")
    fp_txt = j.js("[...document.querySelectorAll('section')].find(s => s.innerText.includes('Final audit pack')).innerText")
    j.check(f"{sid}.C13", "the Closing tab shows the verified final pack with Authorised by = the email and download links",
            ("Verified" in fp_txt, j.email in fp_txt, fp["final_pack_id"] in fp_txt,
             j.js("document.querySelectorAll('.rfe-downloads a[download]').length")), (True, True, True, 6))
    j.shot(f"{sid}_final_pack")
    report.update(final_pack_id=fp["final_pack_id"], usage=cl["usage"], closure_revision=cl["revision"])
    pdf_evidence(j, sid, ref, cl, fp, mode, report)
    return cl


def preview_and_generate(j: FJ, sid, ref, cl, excs, mode, report):
    """Generate preview (with the AI confirm dialog when needed), reuse it, acknowledge and GENERATE, through the UI."""
    calls0 = cl["usage"]["calls"]
    j.button("Generate preview")
    dlg = None
    if excs:
        j.wait(f"{j.DLG} !== document && {j.DLG}.innerText.includes('Generate the preview with an AI closing summary?')",
               what="AI confirm dialog")
        dlg = j.js(f"{j.DLG}.innerText")
        label = "Confirm and generate" if mode["ai"] else "Generate without AI summary"
        j.check(f"{sid}.C08", "preview asks for AI confirmation (provider, store:false data notice)" if mode["ai"] else
                "preview dialog states that AI is unavailable and the summary will be shown as unavailable",
                (label in dlg, "store: false" in dlg or "store:false" in dlg, ("AI unavailable" in dlg) != mode["ai"]),
                (True, True, True))
        j.shot(f"{sid}_preview_dialog")
        j.button(label, j.DLG)
    cl = j.wait_cl(ref, lambda x: bool(x["review"]["current_preview"]) and not x["review"]["current_preview"]["stale"]
                   and x["state"] in ("PREVIEW_READY", "READY", "DECIDING"), 1200, "preview")
    pv = cl["review"]["current_preview"]
    j.wait("document.querySelector('iframe.rfe-frame')", timeout=60, what="preview frame")
    j.check(f"{sid}.C09", f"preview ready; closing summary {mode['summary']}; Generate enabled once acknowledged",
            (pv["closing_summary_status"], cl["state"], cl["actions"]["generate"]["enabled"]), (mode["summary"], "PREVIEW_READY", True))
    j.shot(f"{sid}_preview")
    calls1 = j.cl(ref)["usage"]["calls"]
    report["preview"] = {"preview_id": pv["preview_id"], "closing_summary": pv["closing_summary_status"],
                         "unavailable_reason": pv.get("closing_summary_unavailable_reason"), "ai_calls": calls1 - calls0}
    if mode["ai"] and pv["closing_summary_status"] != "GENERATED":
        # a FAILED AI summary is never reused (closure.request_preview): a second click would spend new AI calls
        j.step(f"{sid}: AI closing summary not generated; reuse step skipped", reason=pv.get("closing_summary_unavailable_reason"))
    else:
        j.button("Generate preview again")
        if excs:
            j.wait(f"{j.DLG} !== document", what="AI confirm dialog (second)")
            j.button("Confirm and generate" if mode["ai"] else "Generate without AI summary", j.DLG)
        j.wait("document.body.innerText.includes('Preview reused')", timeout=60, what="reuse toast")
        cl = j.cl(ref)
        pv2 = cl["review"]["current_preview"]
        j.check(f"{sid}.C10", "a second preview request with unchanged inputs reuses the preview (no new AI call)",
                (pv2["preview_id"], pv2["reused"], cl["usage"]["calls"]), (pv["preview_id"], True, calls1))
    # ---- acknowledgements and GENERATE
    j.wait("document.querySelectorAll('.rfe-acks input[type=checkbox]').length > 0", what="acknowledgements")
    n_ack = j.js("document.querySelectorAll('.rfe-acks input[type=checkbox]').length")
    j.js("[...document.querySelectorAll('.rfe-acks input[type=checkbox]')].forEach(b => { if (!b.checked) b.click(); })")
    j.check(f"{sid}.C11", "acknowledgements shown (a second one only when the closing summary is UNAVAILABLE)",
            n_ack, 2 if pv["closing_summary_status"] == "UNAVAILABLE" else 1)
    j.button("Generate final pack")
    j.wait(f"{j.DLG} !== document && {j.DLG}.innerText.includes('Generate the final audit pack?')", what="generate dialog")
    j.button("Generate final pack", j.DLG)
    j.wait_cl(ref, lambda x: x["state"] in ("GENERATED", "GENERATION_FAILED"), 1200, "final pack")


def no_pub_reason(j: FJ, ref, exc):
    w = j.api(f"cases/{ref}/closure/exceptions/{exc}")
    inv = w.get("investigation") or {}
    att = inv.get("attempts") or []
    return (att[-1].get("reason") or att[-1].get("error")) if att else None


def decide_ui(j: FJ, ref, run, exc, decision):
    label = "Accept AI finding" if decision == "ACCEPT" else "Reject AI finding"
    j.open_ws(ref, run, exc)
    j.button(label, SEC("Analyst decision"))
    j.wait(f"{j.DLG} !== document", what=f"{label} dialog")
    j.button(label, j.DLG)
    j.wait_cl(ref, lambda x: any(e["exception_id"] == exc and e["analyst_decision"] == decision for e in x["exceptions"]),
              60, f"{decision} {exc}")
    j.wait(f"{SEC('Analyst decision')}.innerText.includes({json.dumps('AI finding accepted' if decision == 'ACCEPT' else 'AI finding rejected')})",
           timeout=30, what="decision shown")
    j.shot(f"decision_{decision}_{exc}")


def closing_unavailable(j: FJ, sid, ref, cl, report):
    j.nav(f"#/cases/{ref}/closing")
    j.wait("document.querySelector('.rfe-closing')", what="Closing tab")
    txt = j.text_of(".rfe-closing")
    reason = cl["pack"]["reason"] or ""
    acts = cl["actions"]
    disabled = j.js("['Open closing review', 'Generate preview', 'Hold', 'Generate final pack'].map(t => { const b = "
                    "[...document.querySelectorAll('.rfe-closing button')].find(b => b.textContent.trim().startsWith(t)); "
                    "return b ? b.disabled : null; })")
    j.check(f"{sid}.C02", "Closing tab: 'Audit pack unavailable' with the backend's V6 reason; every closure action "
            "disabled (backend and UI); no final pack",
            ("Audit pack unavailable" in txt, "V6" in reason, reason[:60] in txt, cl["state"],
             sorted(k for k, v in acts.items() if v["enabled"]), disabled, j.get_status(f"cases/{ref}/closure/final-pack")),
            (True, True, True, "PACK_UNAVAILABLE", [], [True, True, True, True], 404))
    j.shot(f"{sid}_closing_unavailable")
    report["pack_unavailable_reason"] = reason
    return cl


def pdf_evidence(j: FJ, sid, ref, cl, fp, mode, report):
    """Download the final PDF through the UI link; SHA-256 = manifest; text checks (pypdf in the closure python)."""
    pdf = j.ui_download("Final report (PDF)")
    data = pdf.read_bytes()
    manifest = json.loads(j.raw(f"cases/{ref}/closure/final-pack/manifest"))
    name = next(f["name"] for f in fp["files"] if f["key"] == "pdf")
    j.check(f"{sid}.P01", "PDF downloaded through the UI link; its SHA-256 equals the manifest entry",
            (data[:5], sha(data), pdf.name.endswith(".pdf")), (b"%PDF-", manifest["files"][name]["sha256"], True))
    keep = j.out / f"{sid}_{pdf.name}"
    shutil.copyfile(pdf, keep)
    text = j.pdf_text(keep)
    norm, squash = " ".join(text.split()), "".join(text.split())
    case = j.case(ref)
    prov = json.loads(j.raw(f"cases/{ref}/closure/final-pack/provenance.json"))
    names, fvs = set(), set()

    def walk(x):
        if isinstance(x, dict):
            if x.get("original_filename"):
                names.add(x["original_filename"])
            if x.get("file_version_id"):
                fvs.add(x["file_version_id"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(prov)
    found_names = sorted(n for n in names if "".join(n.split()) in squash)
    found_fvs = sorted(f for f in fvs if f in squash)
    want_sections = [s for s in SECTIONS if s != "Exceptions and investigations" or report.get("exceptions")]
    prov_pdf = j.out / f"{sid}_provenance.pdf"
    prov_pdf.write_bytes(j.raw(f"cases/{ref}/closure/final-pack/provenance.pdf"))
    ptext = " ".join(j.pdf_text(prov_pdf).split())
    checks = {
        "sections": [s for s in SECTIONS if s in norm],
        "case_ref": ref in squash,
        "recon_run_id": report["recon_run_id"] in squash,
        "original_zip_sha256": case["zip"]["sha256"] in squash,
        "provenance_files_in_pdf": bool(found_names or found_fvs),
        "rejected_by_analyst": "REJECTED BY ANALYST" in norm,
        "reviewer_is_email": f"Reviewer {j.email} ({j.email})" in norm and f"generated by {j.email}" in norm,
        "authorised_by_in_provenance_pdf": f"Authorised by {j.email}" in ptext,
        "not_independent_audit_opinion": "not an independent audit opinion" in norm,
    }
    want = {"sections": want_sections, "case_ref": True, "recon_run_id": True, "original_zip_sha256": True,
            "provenance_files_in_pdf": True, "rejected_by_analyst": "REJECT" in [d for _, d in report.get("decisions", [])],
            "reviewer_is_email": True, "authorised_by_in_provenance_pdf": True,
            # the library prints this notice with the AI closing summary only (report_v3._closing_summary_blocks)
            "not_independent_audit_opinion": mode["summary"] == "GENERATED"}
    if mode.get("unresolved_disclosed"):
        checks["unresolved_disclosed"] = ("UNRESOLVED" in norm, [e for e in report["exceptions"] if e not in squash])
        want["unresolved_disclosed"] = (True, [])
    if mode["summary"] == "NOT_REQUIRED":
        checks["summary_not_required"] = "NOT_REQUIRED" in norm or "not required" in norm.lower()
        want["summary_not_required"] = True
    j.check(f"{sid}.P02", f"PDF text ({len(want_sections)} sections, case, run, ZIP SHA-256, provenance, analyst decision, "
            "reviewer, disclaimer)", checks, want)
    report["pdf"] = {"path": str(keep), "sha256": sha(data), "bytes": len(data), "pages_text_chars": len(text),
                     "provenance_pdf": str(prov_pdf), "provenance_files_found_in_pdf": {"names": found_names, "fv_ids": found_fvs,
                                                                                        "of_names": len(names), "of_fv": len(fvs)},
                     "checks": checks}


def chain_ok(j: FJ, ref=None):
    a = j.api(f"cases/{ref}/activity" if ref else "activity")
    return a["chain"]["verified"]


def compare_key(j: FJ, sid, res, key):
    got = {"case_status": res["case_status"], "FAIL": res["outcomes"].get("FAIL", 0),
           "INSUFFICIENT_EVIDENCE": res["outcomes"].get("INSUFFICIENT_EVIDENCE", 0), "exceptions": res["exception_count"]}
    want = {"case_status": key["expected_case_status"], "FAIL": key["expected_counts"].get("FAIL", 0),
            "INSUFFICIENT_EVIDENCE": key["expected_counts"].get("INSUFFICIENT_EVIDENCE", 0),
            "exceptions": key.get("expected_exception_count", res["exception_count"] if "expected_exception_count" not in key else None)}
    j.check(f"{sid}.K", "backend result equals the scenario's frozen expected_outcome.json (compared after the run)", got, want)


def run_or_resume(j: FJ, sc, results, resume):
    """--resume (Run A only, to stay within the AI budget after a journey-side failure): reuse a COMPLETED case of the
    same customer and period instead of registering a new one; otherwise the full UI pipeline (aaj.scenario)."""
    if resume:
        for x in j.api("cases")["items"]:
            if x["customer_name"] == sc["customer"] and x["reporting_period"] == sc["period"] and x["status"] == "COMPLETED":
                c = j.case(x["case_ref"])
                rid = c["progress"]["reconciliation"]["run_id"]
                r = j.api(f"runs/{rid}")
                results[sc["id"]] = {"case_ref": x["case_ref"], "case_status": r["case_status"], "run_id": rid,
                                     "total_results": r["total_results"], "outcomes": r["outcomes"],
                                     "exception_count": r["exception_count"], "resumed": True}
                j.step(f"{sc['id']}: resumed completed case {x['case_ref']}")
                return
    aaj.scenario(j, sc, results)


def scenario_meta(scen_dir: Path):
    return {m["scenario_id"]: m for m in seed_mod.scenarios(scen_dir)}


def finish_checks(j: FJ, tag):
    j.check(f"{tag}.UI.csp", "no CSP violation in the browser", j.js("JSON.parse(sessionStorage.getItem('rf_csp')||'[]')"), [])
    j.check(f"{tag}.UI.errors", "no JavaScript error in the browser", [e for e in j.br.page_errors if "401" not in str(e)], [])


def install_csp_probe(j: FJ):
    j.br.cmd("Network.enable")
    j.br.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "document.addEventListener('securitypolicyviolation', e => {"
             " try { const k='rf_csp'; const v=JSON.parse(sessionStorage.getItem(k)||'[]'); v.push(e.violatedDirective+' '+e.blockedURI);"
             " sessionStorage.setItem(k, JSON.stringify(v)); } catch (x) {} });"})


def new_home(path: Path, email, pw, resume=False) -> Path:
    home = path.resolve()
    seed_mod.check_home(home)
    if resume and (home / "auth.json").is_file():
        auth_mod.set_password(home / "auth.json", email, pw)             # same single user; hash refreshed
        assert seed_mod.analyst_of(home) == email
        return home
    if home.exists():
        raise SystemExit(f"{home} exists; each run needs a NEW short home folder")
    home.mkdir(parents=True)
    auth_mod.set_password(home / "auth.json", email, pw)                 # PBKDF2 hash only; one email user
    assert seed_mod.analyst_of(home) == email
    return home


# ================================================================================================ runs
def run_a(a, b, email, pw, out) -> dict:
    home = new_home(Path(a.home_a), email, pw, resume=a.resume)
    j = FJ("RUN_A", "Run A: live AI, manual s05 upload + Marlow demo, restart, logout", b, out)
    res = {"home": str(home), "cases": {}}
    work = j.inputs
    s05 = work / "s05_unexplained_difference_2026-09.zip"
    shutil.copyfile(Path(a.manual_inputs) / s05.name, s05)               # a copy; the original is only read
    orig_sha = sha((Path(a.manual_inputs) / s05.name).read_bytes())
    try:
        j.setup(home, email, Path(a.scenarios), Path(a.closure_python), Path(a.ai_env_file),
                ["--ai-max-requests-per-operation", "3"])
        install_csp_probe(j)
        j.enable_downloads()
        auth_checks(j, email, pw, "")
        aic = j.api("ai/configuration")
        j.check("A.AI", "live AI configured (OpenAI, store:false, max 3 requests per operation); the key is never returned",
                (aic["available"], aic["provider"], aic["store"], aic.get("max_requests_per_operation"),
                 "sk-" in json.dumps(aic)), (True, "openai", False, 3, False))
        res["ai_configuration"] = {k: aic.get(k) for k in ("provider", "model", "reasoning_effort", "available")}
        # ---- 1. MANUAL upload (not a predefined scenario)
        scr = {}
        sc = {"id": "S05M", "zip": str(s05), "customer": "Ashcombe Payments Ltd", "period": "2026-09",
              "expect": {"case_status": "EXCEPTIONS_OPEN", "answer": {"exceptions": 2}}}
        run_or_resume(j, sc, scr, a.resume)
        r = scr["S05M"]
        res["cases"]["S05M"] = rep = {"case_ref": r["case_ref"], "case_status": r["case_status"], "outcomes": r["outcomes"],
                                      "exception_count": r["exception_count"], "manual_upload": True}
        closing(j, "S05M", r["case_ref"], {"ai": True, "decisions": ["ACCEPT", "REJECT"], "require_decisions": True,
                                           "expect_pack": "GENERATED", "summary": "GENERATED"}, rep)
        j.check("S05M.Z", "the original manual ZIP is unchanged and the case stores its SHA-256",
                (sha((Path(a.manual_inputs) / s05.name).read_bytes()), j.case(r["case_ref"])["zip"]["sha256"]), (orig_sha, orig_sha))
        used = rep["usage"]["calls"]
        j.step("AI usage after the manual case", calls=used)
        # ---- 2. Marlow demo scenario through the Work Queue's Load scenario button
        metas = scenario_meta(Path(a.scenarios))
        m = metas["RF-DEMO-02"]
        key = json.loads((m["_zip"].parent / "expected_outcome.json").read_text(encoding="utf-8"))
        sc = {"id": "MARLOW", "demo_id": "RF-DEMO-02", "zip": str(m["_zip"]), "customer": m["customer_name"],
              "period": m["reporting_period"], "expect": {"case_status": key["expected_case_status"]}}
        run_or_resume(j, sc, scr, a.resume)
        r = scr["MARLOW"]
        compare_key(j, "MARLOW", r, key)
        j.check("MARLOW.N", "Marlow: EXCEPTIONS_OPEN, 12 FAIL, 7 exceptions",
                (r["case_status"], r["outcomes"].get("FAIL"), r["exception_count"]), ("EXCEPTIONS_OPEN", 12, 7))
        res["cases"]["MARLOW"] = rep = {"case_ref": r["case_ref"], "case_status": r["case_status"], "outcomes": r["outcomes"],
                                        "exception_count": r["exception_count"], "answer_key": r.get("answer_key_comparison", {}).get("status")}
        if used > a.ai_budget - 7 * 3 - 3:
            raise SystemExit(f"AI budget: {used} calls used; Marlow could exceed {a.ai_budget}")
        closing(j, "MARLOW", r["case_ref"], {"ai": True, "decisions": ["ACCEPT", "REJECT", "ACCEPT", "REJECT", "ACCEPT", "REJECT", "ACCEPT"],
                                             "ws_ui": 7, "expect_pack": "GENERATED", "summary": "GENERATED",
                                             "unresolved_disclosed": True}, rep)
        j.check("A.DEC", "ACCEPT and REJECT of AI findings both recorded through the UI across Run A",
                sorted({d for c in res["cases"].values() for _, d in c.get("decisions", [])}), ["ACCEPT", "REJECT"])
        total_calls = sum(c.get("usage", {}).get("calls", 0) for c in res["cases"].values())
        j.check("A.BUDGET", f"total OpenAI calls within the budget ({a.ai_budget})", total_calls <= a.ai_budget, True)
        j.check("A.CHAIN", "audit chain verified (global and per case)",
                [chain_ok(j)] + [chain_ok(j, c["case_ref"]) for c in res["cases"].values()], [True] * 3)
        # ---- 3. restart: closure records, decisions and final packs survive; verify still OK
        before = {k: j.cl(c["case_ref"]) for k, c in res["cases"].items()}
        fps = {k: j.api(f"cases/{c['case_ref']}/closure/final-pack") for k, c in res["cases"].items()}
        j.stop()
        j.step("server stopped; restarting with the same flags")
        j.start()
        j.check("A.R01", "after restart the old session is gone (401) until the analyst signs in again",
                j.get_status("cases"), 401)
        j.sign_in_ui(email, pw)
        j.attach(email, pw)
        after = {k: j.cl(c["case_ref"]) for k, c in res["cases"].items()}
        fps2 = {k: j.api(f"cases/{c['case_ref']}/closure/final-pack") for k, c in res["cases"].items()}
        sig = lambda c: (c["state"], c["frozen"], c["revision"], c["final_pack"]["final_pack_id"],  # noqa: E731
                         [(e["exception_id"], e["ai_state"], e["analyst_decision"], e["decided_by"]) for e in c["exceptions"]])
        j.check("A.R02", "after a server restart the closure records, AI states, decisions and final packs are unchanged",
                {k: sig(v) for k, v in after.items()}, {k: sig(v) for k, v in before.items()})
        j.check("A.R03", "after restart every final pack still verifies (manifest + provenance hashes) and the PDF bytes "
                "are unchanged", {k: (v["verified"], v["problems"], [f["sha256"] for f in v["files"]]) for k, v in fps2.items()},
                {k: (True, [], [f["sha256"] for f in v["files"]]) for k, v in fps.items()})
        j.check("A.R04", "audit chain still verified after restart", chain_ok(j), True)
        ref = res["cases"]["S05M"]["case_ref"]
        j.nav(f"#/cases/{ref}/closing")
        j.wait("document.querySelector('.rfe-verified')", timeout=60, what="Verified after restart")
        j.shot("A_after_restart_closing")
        # ---- 4. logout
        j.js("document.querySelector('.rf-avatar').closest('button').click()")
        j.button("Sign out", timeout=20)
        j.wait("location.hash.startsWith('#/login')", what="sign-in screen after sign-out")
        j.check("A.L01", "sign out: the browser session is invalidated and the API returns 401",
                (j.page_api_status("cases"), j.page_api_status(f"cases/{ref}/closure")), (401, 401))
        j.post("auth/logout", {})
        j.check("A.L02", "the API client's session is invalidated by its logout (401 afterwards)", j.get_status("cases"), 401)
        finish_checks(j, "A")
        res["ai_total"] = {"calls": total_calls, **{t: sum(c["usage"][t] for c in res["cases"].values())
                                                   for t in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")}}
    except Exception:
        fail_dump(j)
        raise
    finally:
        cleanup(j)
    return summarise(j, res, out)


def run_b(a, b, email, pw, out) -> dict:
    home = new_home(Path(a.home_b), email, pw)
    j = FJ("RUN_B", "Run B: AI off; Halden, Corvane, Thornbury (isolation), Pellworth, manual clean upload", b, out)
    res = {"home": str(home), "cases": {}}
    metas = scenario_meta(Path(a.scenarios))
    orig_shas = {sid: sha(m["_zip"].read_bytes()) for sid, m in metas.items()}
    try:
        j.setup(home, email, Path(a.scenarios), Path(a.closure_python), None, [])
        install_csp_probe(j)
        j.enable_downloads()
        auth_checks(j, email, pw, "")
        aic = j.api("ai/configuration")
        j.check("B.AI", "AI is honestly UNAVAILABLE (server started without --ai-env-file)",
                (aic["available"], "without --ai-env-file" in (aic["problem"] or "")), (False, True))
        scr = {}

        def demo(sid, tag, expect, verify=True):
            m = metas[sid]
            sc = {"id": tag, "demo_id": sid, "zip": str(m["_zip"]), "customer": m["customer_name"],
                  "period": m["reporting_period"], "expect": expect, "verify": verify}
            aaj.scenario(j, sc, scr)
            r = scr[tag]
            res["cases"][tag] = {"case_ref": r["case_ref"], "case_status": r["case_status"], "outcomes": r["outcomes"],
                                 "exception_count": r["exception_count"],
                                 "answer_key": (r.get("answer_key_comparison") or {}).get("status")}
            return r, m
        # Halden: CLEAN
        r, m = demo("RF-DEMO-01", "HALDEN", {"case_status": "CLEAN"})
        compare_key(j, "HALDEN", r, json.loads((m["_zip"].parent / "expected_outcome.json").read_text(encoding="utf-8")))
        closing(j, "HALDEN", r["case_ref"], {"ai": False, "expect_pack": "GENERATED", "summary": "NOT_REQUIRED"},
                res["cases"]["HALDEN"])
        # Corvane: EVIDENCE_INCOMPLETE → audit pack UNAVAILABLE
        r, m = demo("RF-DEMO-03", "CORVANE", {"case_status": "EVIDENCE_INCOMPLETE"})
        compare_key(j, "CORVANE", r, json.loads((m["_zip"].parent / "expected_outcome.json").read_text(encoding="utf-8")))
        closing(j, "CORVANE", r["case_ref"], {"ai": False, "expect_pack": "UNAVAILABLE"}, res["cases"]["CORVANE"])
        # Thornbury: IN-09 isolated → corrected IN-09 uploaded through the UI → CLEAN
        m = metas["RF-DEMO-04"]
        cur = json.loads((m["_zip"].parent / "expected_outcome_current.json").read_text(encoding="utf-8"))
        iso = aqj.thornbury_correction(m, cur, j.inputs)
        r, m = demo("RF-DEMO-04", "THORNBURY", {"case_status": cur["expected_after_corrected_in09"]["case_status"],
                                               "member_isolation": iso}, verify=False)
        j.check("THORNBURY.K", "result equals expected_outcome_current.json (after the corrected IN-09)",
                (r["case_status"], r["exception_count"]),
                (cur["expected_after_corrected_in09"]["case_status"], cur["expected_after_corrected_in09"]["exceptions"]))
        # Library limitation found 20 Nov 2026 (not a Ringfence defect; the library is read-only): Thornbury's unallocated
        # register is header-only, so the engine emits no C09-ALLOCATION result and uc042lib.pack V6 refuses the pack
        # ("no result for check C09-ALLOCATION"), exactly as for Corvane. Closure must show that honestly; no PDF.
        closing(j, "THORNBURY", r["case_ref"], {"ai": False, "expect_pack": "UNAVAILABLE"}, res["cases"]["THORNBURY"])
        j.check("THORNBURY.Z", "the original scenario ZIP is unchanged; the case stores that ZIP's SHA-256",
                (sha(m["_zip"].read_bytes()), j.case(r["case_ref"])["zip"]["sha256"]), (orig_shas["RF-DEMO-04"],) * 2)
        res["cases"]["THORNBURY"]["corrected_member"] = {"file": iso["file"], "sha256": sha(Path(iso["file"]).read_bytes())}
        # Pellworth duplicate: EXCEPTIONS_OPEN 17/17, AI unavailable → NOT_INVESTIGATED, summary UNAVAILABLE
        r, m = demo("RF-DEMO-05", "PELLWORTH", {"case_status": "EXCEPTIONS_OPEN"})
        compare_key(j, "PELLWORTH", r, json.loads((m["_zip"].parent / "expected_outcome.json").read_text(encoding="utf-8")))
        j.check("PELLWORTH.N", "Pellworth: EXCEPTIONS_OPEN, 17 FAIL, 17 exceptions",
                (r["case_status"], r["outcomes"].get("FAIL"), r["exception_count"]), ("EXCEPTIONS_OPEN", 17, 17))
        closing(j, "PELLWORTH", r["case_ref"], {"ai": False, "expect_pack": "GENERATED", "summary": "UNAVAILABLE", "ws_ui": 2,
                                                "unresolved_disclosed": True}, res["cases"]["PELLWORTH"])
        # MANUAL upload of a copy of clean_submission_2026-09.zip
        src = Path(a.manual_inputs) / "clean_submission_2026-09.zip"
        cz = j.inputs / src.name
        shutil.copyfile(src, cz)
        sc = {"id": "CLEANM", "zip": str(cz), "customer": "Brightwater Pay Ltd", "period": "2026-09",
              "expect": {"case_status": "CLEAN"}}
        aaj.scenario(j, sc, scr)
        r = scr["CLEANM"]
        res["cases"]["CLEANM"] = {"case_ref": r["case_ref"], "case_status": r["case_status"], "outcomes": r["outcomes"],
                                  "exception_count": r["exception_count"], "manual_upload": True}
        closing(j, "CLEANM", r["case_ref"], {"ai": False, "expect_pack": "GENERATED", "summary": "NOT_REQUIRED"},
                res["cases"]["CLEANM"])
        j.check("B.ZIPS", "scenario ZIPs unchanged", {s: sha(m["_zip"].read_bytes()) for s, m in metas.items()}, orig_shas)
        j.check("B.CHAIN", "audit chain verified (global and per case)",
                [chain_ok(j)] + [chain_ok(j, c["case_ref"]) for c in res["cases"].values()], [True] * 6)
        j.check("B.NOAI", "no AI call was made in Run B", sum(j.cl(c["case_ref"])["usage"]["calls"]
                                                               for c in res["cases"].values()), 0)
        finish_checks(j, "B")
    except Exception:
        fail_dump(j)
        raise
    finally:
        cleanup(j)
    return summarise(j, res, out)


def fail_dump(j: FJ):
    try:
        j.shot("FAILURE")
        print(f"[{j.jid}] page at failure:", j.js("location.href"), j.js("document.body.innerText.slice(0,2000)"),
              j.br.page_errors, flush=True)
    except Exception:
        pass


def cleanup(j: FJ):
    try:
        j.br.close()
    finally:
        j.stop()


def summarise(j: FJ, res, out: Path) -> dict:
    s = {"journey": j.jid, "checks_total": len(j.checks), "checks_passed": sum(c["passed"] for c in j.checks),
         "failed": [c for c in j.checks if not c["passed"]], "api_calls_observed": len(j.br.api_calls),
         "results": res, "checks": j.checks, "steps": j.steps}
    (out / f"{j.jid}_summary.json").write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    print(f"[{j.jid}] DONE {s['checks_passed']}/{s['checks_total']}", flush=True)
    shutil.rmtree(j.ws, ignore_errors=True)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--out", required=True)
    ap.add_argument("--home-a", default=r"C:\u42v\e2e\a1")
    ap.add_argument("--home-b", default=r"C:\u42v\e2e\b1")
    ap.add_argument("--run", choices=["A", "B", "AB"], default="AB")
    ap.add_argument("--scenarios", default=str(seed_mod.DEFAULT_SCENARIOS))
    ap.add_argument("--closure-python", default=str(seed_mod.DEFAULT_CLOSURE_PYTHON))
    ap.add_argument("--ai-env-file", default=str(seed_mod.DEFAULT_AI_ENV))
    ap.add_argument("--manual-inputs", default=str(MANUAL_INPUTS))
    ap.add_argument("--ai-budget", type=int, default=40)
    ap.add_argument("--resume", action="store_true", help="Run A: reuse --home-a and its completed cases (AI budget)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")          # check texts contain non-cp1252 characters
    email, pw = os.environ.get("RF_DEMO_EMAIL") or "", os.environ.get(seed_mod.PASSWORD_ENV) or ""
    if not (seed_mod.EMAIL_RE.match(email) and pw):
        raise SystemExit("set RF_DEMO_EMAIL (an email address) and RF_DEMO_PASSWORD")
    b = Bundle(Path(a.bundle))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sums = []
    if "B" in a.run:
        sums.append(run_b(a, b, email, pw, out))
    if "A" in a.run:
        sums.append(run_a(a, b, email, pw, out))
    ok = all(s["checks_passed"] == s["checks_total"] for s in sums)
    print("ALL PASS" if ok else "FAILURES", [(s["journey"], s["checks_passed"], s["checks_total"]) for s in sums])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
