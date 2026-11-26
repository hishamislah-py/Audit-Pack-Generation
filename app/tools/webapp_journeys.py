"""Browser E2E journeys for the UC-042 Smart Parser application (smartparser.webapp).

    py -3.11 tools/webapp_journeys.py --bundle <E2E bundle root> --out <evidence dir> [--journeys J1,J2,...]

Each journey starts the REAL application server (its own temporary workspace, TEST-ONLY authority, recorded LLM
fixtures, the bundle's read-only UC-042 engine copy) and drives headless Microsoft Edge ONLY through the page's own
controls: file inputs (real uploads), selects, text inputs and buttons. Every step asserts what the page shows; final
results are compared with the bundle's ORIGINAL answer keys (UC-042 compare_answer_key on the run's case folder) and
reference exception rows. No backend shortcut is used for any user action.

Input files are prepared from the bundle's synthetic datasets with the bundle harness transforms (renamed headers, extra
columns, constructed PDF variants) and written to <out>/inputs/<journey>/ before they are uploaded through the browser.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
from ui_browser_3b11 import EDGE, Browser, free_port  # noqa: E402

ANSWER_RUNNER = r'''
import json, sys
sys.dont_write_bytecode = True
uc042_root, case_dir, period = sys.argv[1:4]
sys.path.insert(0, uc042_root)
from uc042lib.validate import Validator, compare_answer_key
v = Validator(case_dir, period)
results = v.run()
matched, lines = compare_answer_key(case_dir, results, v.exceptions, v.candidates)
print(json.dumps({"matched": matched, "differences": lines}))
'''
IN10_RENAME = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt", "amount": "txn_amt"}


# ================================================================================================ data preparation
def rows_of(b: bytes):
    return list(csv.reader(io.StringIO(b.decode("utf-8"))))


def dump(rows) -> bytes:
    s = io.StringIO()
    csv.writer(s, lineterminator="\n").writerows(rows)
    return s.getvalue().encode("utf-8")


def rename(b, m):
    r = rows_of(b)
    return dump([[m.get(c, c) for c in r[0]]] + r[1:])


def add_col(b, h, v):
    r = rows_of(b)
    return dump([r[0] + [h]] + [x + [v] for x in r[1:]])


class Bundle:
    def __init__(self, root: Path):
        self.root = root
        self.uc = root / "src" / "uc042"
        self.ds = self.uc / "uc042_dataset"
        self.gt = root / "ground_truth" / "uc042_scenarios"

    def dataset(self, name):
        with open(self.ds / name / "manifest.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        return [(Path(r["relative_path"]).name, (self.ds / name / r["relative_path"]).read_bytes(), r["file_id"]) for r in rows]

    def zip_files(self, name):
        with zipfile.ZipFile(self.root / "fixtures" / "datasets" / name) as z:
            return [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir()]

    def answer_key(self, run_dir: Path, dataset: str) -> dict:
        chk = Path(tempfile.mkdtemp(prefix="u42ak_")) / "case"
        shutil.copytree(run_dir / "case", chk)
        for meta in ("answer_key.json", "scenario.json"):
            src = self.gt / dataset / meta
            if src.is_file():
                shutil.copyfile(src, chk / meta)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("UC042_", "OPENAI", "ANTHROPIC", "GROQ"))}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        p = subprocess.run([sys.executable, "-B", "-c", ANSWER_RUNNER, str(self.uc), str(chk), "PER-2026-09"],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
        shutil.rmtree(chk.parent, ignore_errors=True)
        if p.returncode:
            return {"matched": False, "differences": [p.stderr[-800:]]}
        return json.loads(p.stdout.strip().splitlines()[-1])


# ================================================================================================ browser driver
class Edge(Browser):
    """Browser + collection of page errors (uncaught exceptions / console errors)."""
    def __init__(self, profile):
        self.page_errors = []
        super().__init__(profile)

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.page_errors.append((d.get("exception") or {}).get("description") or d.get("text"))
            elif msg.get("method") == "Runtime.consoleAPICalled" and msg["params"].get("type") == "error":
                self.page_errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"]))
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


class Journey:
    def __init__(self, jid: str, title: str, bundle: Bundle, out: Path, recorded: list[Path]):
        self.jid, self.title, self.b = jid, title, bundle
        self.out = out / jid
        self.inputs = out / "inputs" / jid
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self.inputs.mkdir(parents=True, exist_ok=True)
        self.ws = Path(tempfile.mkdtemp(prefix=f"u42web_{jid}_"))
        self.steps, self.checks, self.shots = [], [], 0
        self.port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "ANTHROPIC", "GROQ", "AI_"))}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, "-B", "-m", "smartparser.webapp.server", "--root", str(self.ws), "--port", str(self.port),
               "--authority", str(bundle.root / "fixtures" / "review" / "test_authority_policy.json"),
               "--uc042-root", str(bundle.uc), "--reviewer-id", "e2e-test-analyst-1", "--reviewer-role", "analyst",
               "--reviewer-kind", "TEST", "--insecure-no-auth", "--recorded-llm", *map(str, recorded)]
        self.server = subprocess.Popen(cmd, cwd=str(HERE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(150):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/app", timeout=1).read()
                break
            except Exception:
                time.sleep(0.15)
        self.br = Edge(self.ws / "edge_profile")
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})

    # ---------------------------------------------------------------------------------------------- recording
    def step(self, text, **data):
        self.steps.append({"step": text, **data})
        print(f"[{self.jid}] {text} " + (json.dumps(data, default=str)[:300] if data else ""), flush=True)

    def check(self, cid, desc, actual, expected=True):
        ok = actual == expected
        self.checks.append({"id": cid, "check": desc, "passed": ok, "actual": actual, "expected": expected})
        print(f"[{self.jid}] CHECK {cid} {'PASS' if ok else 'FAIL'} {desc}: {json.dumps(actual, default=str)[:300]}", flush=True)
        return ok

    def shot(self, label):
        self.shots += 1
        name = f"{self.shots:02d}_{label}.png"
        h = self.br.js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)") or 1000
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": int(min(h, 6000)), "deviceScaleFactor": 1, "mobile": False})
        data = self.br.cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})["data"]
        (self.out / name).write_bytes(base64.b64decode(data))
        self.br.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        return name

    # ---------------------------------------------------------------------------------------------- page helpers
    def go(self, hash_):
        self.br.goto("about:blank")
        self.br.wait("location.href === 'about:blank'")
        self.br.goto(f"http://127.0.0.1:{self.port}/{hash_}")
        self.settle()

    def settle(self, timeout=30):
        self.br.wait("document.readyState === 'complete' && document.querySelector('#main') && "
                     "!document.querySelector('#main [aria-busy=\"true\"]')", timeout=timeout, what="page render")
        time.sleep(0.25)

    def wait(self, expr, timeout=60, what=""):
        self.br.wait(expr, timeout=timeout, what=what or expr[:80])

    def js(self, expr):
        return self.br.js(expr)

    def click(self, selector):
        ok = self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e || e.disabled) return false; e.click(); return true; }})()")
        if not ok:
            raise AssertionError(f"cannot click {selector}")

    def set_value(self, selector, value, event="input"):
        self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.value = {json.dumps(value)}; "
                f"e.dispatchEvent(new Event({json.dumps(event)}, {{bubbles: true}})); }})()")

    def upload(self, selector, paths):
        doc = self.br.cmd("DOM.getDocument", {"depth": 1})
        node = self.br.cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": selector})["nodeId"]
        self.br.cmd("DOM.setFileInputFiles", {"nodeId": node, "files": [str(p) for p in paths]})

    def toast_errors(self):
        return self.js("[...document.querySelectorAll('#toasts .toast.bad')].map(t => t.textContent)")

    def text(self, selector):
        return self.js(f"(document.querySelector({json.dumps(selector)}) || {{}}).textContent || ''")

    def api(self, path):
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/{path}", timeout=30).read())

    # ---------------------------------------------------------------------------------------------- flows
    def intake(self, files: list[Path], declared: dict[str, str] | None = None, period="2026-09", label="intake"):
        self.go("#/intake")
        self.set_value("#period", period)
        self.upload("#file-input", files)
        n = len(files)
        self.wait(f"document.querySelectorAll('select.decl').length >= {n} || document.querySelectorAll('select.decl').length > 0 && "
                  f"![...document.querySelectorAll('#main td')].some(td => td.textContent.includes('Uploading'))", 120, "staging")
        self.wait("![...document.querySelectorAll('#main td')].some(td => td.textContent.includes('Uploading'))", 120, "uploads done")
        staged = self.js("document.querySelectorAll('select.decl').length")
        for name, cat in (declared or {}).items():
            self.js(f"(() => {{ const s = document.querySelector('select[aria-label=\"Category for {name}\"]'); s.value = {json.dumps(cat)}; s.dispatchEvent(new Event('change')); }})()")
        self.step("files staged in the intake screen", staged=staged, declared=declared or {})
        self.shot(f"{label}_staged")
        self.click("#submit-intake")
        self.wait("location.hash.startsWith('#/processing/JOB-')", 60, "processing page")
        self.settle()
        self.shot(f"{label}_processing_running")
        self.wait("document.querySelector('#stages [data-stage=\"validation\"]') && "
                  "!['pending','running'].includes(document.querySelector('#stages [data-stage=\"validation\"]').dataset.status)", 600, "processing complete")
        time.sleep(0.4)
        job = self.js("location.hash.split('/').pop()")
        view = self.api(f"jobs/{job}")
        self.step("processing finished", job=job, state=view["state"],
                  stages={s["key"]: s["status"] for s in view["stages"]},
                  files={f["name"]: (f["outcome"] or {}).get("version_status") or (f["outcome"] or {}).get("refused_reason") for f in view["files"]})
        self.shot(f"{label}_processing_complete")
        return view

    def package_id(self):
        return self.js("(document.querySelector('#pkg-switch') || {}).value")

    def open_review(self, category):
        self.go("#/review")
        pid = self.package_id()
        rows = self.api("reviews")
        r = next(x for x in rows if x["evidence_category"] == category and x["package_id"] == pid)
        self.go(f"#/review/{pid}/{r['file_version_id']}")
        return pid, r["file_version_id"]

    def decide(self, idx, action, reason, field=None):
        before = self.js(f"(document.querySelector('#mapping tr[data-idx=\"{idx}\"] td:last-child') || {{}}).textContent")
        if not self.js(f"!!document.querySelector('tr[data-detail-for=\"{idx}\"]')"):
            self.click(f"#mapping tr[data-idx=\"{idx}\"] .twisty")
            self.wait(f"!!document.querySelector('tr[data-detail-for=\"{idx}\"]')", 10)
        if field:
            self.js(f"(() => {{ const s = document.querySelector('tr[data-detail-for=\"{idx}\"] select.field-sel'); s.value = {json.dumps(field)}; s.dispatchEvent(new Event('change')); }})()")
        self.set_value(f"tr[data-detail-for=\"{idx}\"] input.reason", reason)
        n_err = len(self.toast_errors())
        self.click(f"tr[data-detail-for=\"{idx}\"] button[data-action=\"{action}\"]")
        self.wait(f"(document.querySelector('#mapping tr[data-idx=\"{idx}\"] td:last-child') || {{}}).textContent !== {json.dumps(before)} "
                  f"|| document.querySelectorAll('#toasts .toast.bad').length > {n_err}", 60, f"decision {action} #{idx + 1}")
        errs = self.toast_errors()[n_err:]
        return errs

    def complete(self, basis):
        self.set_value("#basis", basis)
        self.click("#complete")
        self.wait("!document.querySelector('#complete') || document.querySelectorAll('#toasts .toast.bad').length > 0", 120, "complete")
        time.sleep(0.3)
        return self.js("(document.querySelector('#outcome') || {}).textContent || ''")

    def reject(self, reason):
        self.click("#reject")
        self.wait("document.querySelector('#dlg').open", 10)
        self.shot("reject_dialog")
        self.set_value("#dlg-reason", reason)
        self.click("#dlg-ok")
        self.wait("!document.querySelector('#reject')", 60, "reject")
        time.sleep(0.3)

    def validate_and_activate(self, expect_ok=True, label="validation"):
        pid = self.package_id()
        self.go(f"#/validation/{pid}")
        self.click("#run-validation")
        self.wait("document.querySelector('#run-validation') && !document.querySelector('#run-validation').disabled && "
                  "document.querySelector('#run-validation').textContent.includes('Run validation')", 120)
        time.sleep(0.3)
        pv = self.js("[...document.querySelectorAll('#main table.t')].find(t => t.textContent.includes('PV-01'))"
                     " ? [...[...document.querySelectorAll('#main table.t')].find(t => t.textContent.includes('PV-01')).querySelectorAll('tbody tr')]"
                     ".map(tr => [tr.children[0].textContent, tr.children[2].textContent]) : []")
        enabled = self.js("!document.querySelector('#activate').disabled")
        self.step("package validation in the UI", checks=pv, activate_enabled=enabled)
        self.shot(f"{label}_checks")
        if not expect_ok:
            return pv, enabled, None
        self.click("#activate")
        self.wait("document.querySelector('#dlg').open", 10)
        self.shot(f"{label}_activation_dialog")
        self.click("#dlg-ok")
        self.wait("!!document.querySelector('#activation-result') || document.querySelectorAll('#toasts .toast.bad').length > 0", 180, "activation")
        time.sleep(0.3)
        snap = self.js("(document.querySelector('#activation-result .mono') || {}).textContent || null")
        self.shot(f"{label}_activated")
        return pv, enabled, snap

    def reconcile(self, label="reconciliation"):
        pid = self.package_id()
        self.go(f"#/reconciliation/{pid}")
        self.shot(f"{label}_eligibility")
        self.click("#run-recon")
        self.wait("!!document.querySelector('#recon-job')", 30)
        time.sleep(0.6)
        self.shot(f"{label}_running")
        self.wait("!!document.querySelector('#open-results') || (document.querySelector('#recon-job') && document.querySelector('#recon-job').textContent.includes('Reconciliation failed'))", 900, "reconciliation")
        self.shot(f"{label}_complete")
        self.click("#open-results")
        self.wait("location.hash.startsWith('#/runs/')", 20)
        self.settle()
        rid = self.js("location.hash.split('/')[2]")
        facts = self.js("Object.fromEntries([...document.querySelectorAll('.facts .fact')].map(f => [f.querySelector('.k').textContent, f.querySelector('.v').textContent]))")
        rows = self.js("[...document.querySelectorAll('#main table.t tbody tr.click')].map(tr => [...tr.children].map(td => td.textContent.trim()))")
        self.shot(f"{label}_results")
        return rid, facts, rows

    def run_dir(self, rid):
        return self.ws / "runs" / rid

    def finish(self, extra=None):
        errs = self.br.page_errors
        self.check("UI.errors", "no JavaScript error in the browser during the journey", errs, [])
        try:
            self.br.close()
        except Exception:
            pass
        self.server.terminate()
        try:
            out = self.server.communicate(timeout=10)[0].decode("utf-8", "replace")
        except Exception:
            out = ""
        (self.out / "server_log.txt").write_text(out, encoding="utf-8")
        res = {"journey": self.jid, "title": self.title, "workspace": str(self.ws),
               "checks_total": len(self.checks), "checks_passed": sum(c["passed"] for c in self.checks),
               "failed": [c for c in self.checks if not c["passed"]], "screenshots": self.shots,
               "steps": self.steps, "checks": self.checks, **(extra or {})}
        (self.out / "journey_result.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(f"[{self.jid}] DONE {res['checks_passed']}/{res['checks_total']}", flush=True)
        return res


# ================================================================================================ journeys
def write_inputs(j: Journey, files: list[tuple[str, bytes]]) -> list[Path]:
    out = []
    for n, d in files:
        p = j.inputs / n
        p.write_bytes(d)
        out.append(p)
    return out


def exception_rows_from_ui(j: Journey, rid):
    j.go(f"#/runs/{rid}")
    return j.js("[...document.querySelectorAll('#main table.t tbody tr.click')].map(tr => [...tr.children].map(td => td.textContent.trim()))")


def j1_clean(b: Bundle, out: Path, rec) -> dict:
    j = Journey("J1", "Clean package: ZIP upload -> process -> validate -> activate -> reconcile -> CLEAN", b, out, rec)
    exp = json.loads((b.root / "expected_results" / "E2E-01.json").read_text(encoding="utf-8"))
    z = j.inputs / exp["dataset"]
    shutil.copyfile(b.root / "fixtures" / "datasets" / exp["dataset"], z)
    j.go("#/overview")
    j.shot("overview_empty")
    view = j.intake([z], label="J1_intake")
    j.check("J1.01", "19 files from the ZIP processed, all VALIDATED",
            sorted({(f["outcome"] or {}).get("version_status") for f in view["files"]}) + [len(view["files"])], ["VALIDATED", 19])
    j.check("J1.02", "pipeline stages from real results/events",
            {s["key"]: s["status"] for s in view["stages"]},
            {"init": "completed", "read": "completed", "identify": "completed", "structure": "completed",
             "mapping": "completed", "proposals": "not_required", "review": "not_required", "previews": "completed",
             "validation": "completed"})
    pid = j.package_id()
    j.go(f"#/packages/{pid}")
    j.shot("J1_evidence_files")
    j.go("#/overview")
    j.shot("J1_overview_ready")
    pv, enabled, snap = j.validate_and_activate(label="J1_validation")
    j.check("J1.03", "PV-01..PV-09 all PASS in the UI", pv, [[f"PV-0{i}", "PASS"] for i in range(1, 10)])
    j.check("J1.04", "activation produced a snapshot", bool(snap and snap.startswith("SNAP-")))
    rid, facts, rows = j.reconcile(label="J1_reconciliation")
    j.check("J1.05", "reconciliation status / totals shown", (facts.get("Reconciliation status"), facts.get("Total controls"),
                                                              facts.get("Passed"), facts.get("Exceptions")),
            ("Clean", "1,886", "1,886", "0"))
    j.check("J1.06", "engine result = expected E2E-01", json.loads((j.run_dir(rid) / "reconciliation_run.json").read_text(encoding="utf-8"))["result"]["outcomes"], exp["outcomes"])
    for tab in ("controls", "report", "inputs"):
        j.go(f"#/runs/{rid}/{tab}")
        j.shot(f"J1_results_{tab}")
    j.go(f"#/activity/{pid}")
    j.check("J1.07", "audit chain verified badge", "Hash chain verified" in j.text("#main .page-head"), True)
    j.shot("J1_activity")
    j.go(f"#/history/{pid}")
    j.shot("J1_history")
    snap_id = j.api(f"packages/{pid}")["active_snapshot_id"]
    j.go(f"#/snapshot/{pid}/{snap_id}")
    j.shot("J1_snapshot")
    return j.finish({"package_id": pid, "run_id": rid})


def j2_hitl(b: Bundle, out: Path, rec) -> dict:
    j = Journey("J2", "S05: HITL review of ambiguous mappings -> activate -> reconcile -> expected exceptions", b, out, rec)
    exp = json.loads((b.root / "expected_results" / "E2E-02.json").read_text(encoding="utf-8"))
    ref = {n: fid for n, _, fid in b.dataset(exp["answer_key_dataset"])}
    files = b.zip_files(exp["dataset"])
    up = [(n, rename(d, IN10_RENAME) if ref[n] == "IN-10" else add_col(d, "analyst_memo", "checked") if ref[n] == "IN-05" else d) for n, d in files]
    paths = write_inputs(j, up)
    names = {ref[n]: n for n, _ in files}
    view = j.intake(paths, declared={names["IN-10"]: "IN-10", names["IN-05"]: "IN-05"}, label="J2_intake")
    st = {(f["outcome"] or {}).get("evidence_category"): (f["outcome"] or {}).get("version_status") for f in view["files"]}
    j.check("J2.01", "IN-10 and IN-05 routed to review, others VALIDATED",
            (st["IN-10"], st["IN-05"], sorted({v for c, v in st.items() if c not in ("IN-10", "IN-05")})),
            ("REVIEW_REQUIRED", "REVIEW_REQUIRED", ["VALIDATED"]))
    j.check("J2.02", "proposal stage shows the recorded proposal call", next(s for s in view["stages"] if s["key"] == "proposals")["status"], "completed")
    pid = j.package_id()
    pv, enabled, _ = j.validate_and_activate(expect_ok=False, label="J2_blocked")
    j.check("J2.03", "activation disabled while reviews are open", enabled, False)
    j.go("#/review")
    j.shot("J2_review_queue")
    pid, v10 = j.open_review("IN-10")
    j.shot("J2_IN10_review_initial")
    samples = j.js("[...document.querySelectorAll('#mapping tr[data-idx]')].map(tr => [tr.children[2].textContent, tr.children[3].textContent])")
    j.check("J2.04", "sample source values shown in the review grid", all(s[1] and s[1] != "–" for s in samples), True)
    j.check("J2.05", "sign-sensitive financial column flagged", "Sign-sensitive" in j.text("#mapping tr[data-idx=\"4\"]"), True)
    j.click("#mapping tr[data-idx=\"0\"] .twisty")
    j.wait("!!document.querySelector('tr[data-detail-for=\"0\"]')", 10)
    j.shot("J2_IN10_column_detail")
    errs = j.decide(0, "MAP", "")
    j.check("J2.06", "decision without a reason refused by the backend (shown as error toast)", any("REASON_REQUIRED" in e for e in errs), True)
    reasons = {0: "TEST-ONLY: entry_ref values are LE-<ccy>-<mmdd>-nnnn ledger entry ids (sample values); payment_reference is mapped deterministically",
               1: "TEST-ONLY: acct_no values are SGA-GBP-01 / SGA-EUR-01 safeguarding account ids",
               2: "TEST-ONLY: posting_dt values are ISO-8601 timestamps with UTC offset",
               4: "TEST-ONLY: txn_amt has 0 negative values (column statistics); direction is in dc_indicator"}
    for idx, why in reasons.items():
        e = j.decide(idx, "MAP", why)
        j.check(f"J2.07.{idx}", f"column #{idx + 1} mapped", e, [])
    j.shot("J2_IN10_decided")
    outc = j.complete("TEST-ONLY: every proposal checked against the sample values shown")
    j.check("J2.08", "IN-10 VALIDATED after completion", "Validated" in outc and "Yes" in outc, True)
    j.check("J2.09", "no stale 'ready to complete' text after completion", j.js("!!document.querySelector('#finalisation')"), False)
    j.shot("J2_IN10_completed")
    pid, v05 = j.open_review("IN-05")
    j.shot("J2_IN05_review_initial")
    n = j.js("document.querySelectorAll('#mapping tr[data-idx]').length")
    j.check("J2.10", "IN-05 shows 20 incoming columns", n, 20)
    e = j.decide(19, "IGNORE_COLUMN", "TEST-ONLY: analyst working note ('checked' on every row), not an IN-05 field")
    j.check("J2.11", "analyst_memo ignored", e, [])
    for idx in range(19):
        e = j.decide(idx, "MAP", "TEST-ONLY: header is the exact IN-05 canonical field name")
        if e:
            j.check(f"J2.12.{idx}", "IN-05 column mapped", e, [])
    outc = j.complete("TEST-ONLY: 19 canonical headers mapped, 1 working-note column ignored")
    j.check("J2.13", "IN-05 VALIDATED", "Validated" in outc, True)
    j.shot("J2_IN05_completed")
    pv, enabled, snap = j.validate_and_activate(label="J2_validation")
    j.check("J2.14", "all PV pass after review", pv, [[f"PV-0{i}", "PASS"] for i in range(1, 10)])
    rid, facts, rows = j.reconcile(label="J2_reconciliation")
    j.check("J2.15", "status Exceptions open, 2 exceptions", (facts.get("Reconciliation status"), facts.get("Exceptions")), ("Exceptions open", "2"))
    run = json.loads((j.run_dir(rid) / "reconciliation_run.json").read_text(encoding="utf-8"))
    got = [[x["severity"], x["root_cause"], x["affected_results"]] for x in run["result"]["exceptions"]]
    j.check("J2.16", "exceptions = expected E2E-02", got, exp["exceptions"])
    j.check("J2.17", "UC-042 compare_answer_key vs ORIGINAL S05 answer key", b.answer_key(j.run_dir(rid), exp["answer_key_dataset"]), {"matched": True, "differences": []})
    j.check("J2.18", "exception table rows in the UI", [[r[0], r[1]] for r in rows], [["EXC-CASE-01", "Critical"], ["EXC-CASE-02", "High"]])
    j.go(f"#/runs/{rid}/exceptions/EXC-CASE-01")
    j.check("J2.19", "exception detail shows impact and account", ("-812.40" in j.text("#main .facts"), "SGA-GBP-01" in j.text("#main .facts")), (True, True))
    j.check("J2.20", "evidence references resolved to file versions + rows", j.js("[...document.querySelectorAll('#main table.t')][0].querySelectorAll('tbody tr').length") >= 20, True)
    j.shot("J2_exception_detail")
    j.go(f"#/history/{pid}/{v10}")
    j.shot("J2_IN10_version_history")
    j.go(f"#/activity/{pid}")
    j.shot("J2_activity")
    return j.finish({"package_id": pid, "run_id": rid})


def j3_resubmission(b: Bundle, out: Path, rec) -> dict:
    j = Journey("J3", "Baseline: missing column + rejection -> corrected versions -> fresh review -> CLEAN", b, out, rec)
    files = b.dataset("set_01_clean_baseline")
    orig = {fid: d for _, d, fid in files}
    names = {fid: n for n, _, fid in files}
    r = rows_of(orig["IN-03"])
    bi = r[0].index("balance")
    in03_v1 = dump([[c for k, c in enumerate(x) if k != bi] + ex for x, ex in zip(r, [["memo", "note"]] + [["a", "b"]] * (len(r) - 1))])
    up = [(n, in03_v1 if fid == "IN-03" else rename(d, IN10_RENAME) if fid == "IN-10" else d) for n, d, fid in files]
    paths = write_inputs(j, up)
    view = j.intake(paths, declared={names["IN-03"]: "IN-03", names["IN-10"]: "IN-10"}, label="J3_intake")
    pid, v03 = j.open_review("IN-03")
    j.shot("J3_IN03_v1_review")
    for idx in (6, 7):
        j.decide(idx, "IGNORE_COLUMN", "TEST-ONLY: working column (constant value), not an IN-03 field")
    for idx in range(6):
        j.decide(idx, "MAP", "TEST-ONLY: header is the exact IN-03 canonical field name")
    j.check("J3.01", "UI warns that completing will HOLD (balance not covered)", "HOLD" in j.text("#finalisation"), True)
    j.shot("J3_IN03_v1_hold_warning")
    outc = j.complete("TEST-ONLY: balance is absent from the file and is not inferred")
    j.check("J3.02", "IN-03 v1 RESUBMISSION_REQUIRED, balance missing", ("Resubmission required" in outc, "balance" in outc), (True, True))
    j.shot("J3_IN03_v1_held")
    pid, v10 = j.open_review("IN-10")
    j.decide(1, "MAP", "TEST-ONLY: acct_no holds SGA account ids")
    j.reject("TEST-ONLY: export does not match the agreed cashbook layout (scenario instruction: obtain the canonical export)")
    j.check("J3.03", "IN-10 v1 REJECTED", "Rejected" in j.text("#main .page-head"), True)
    j.shot("J3_IN10_v1_rejected")
    pv, enabled, _ = j.validate_and_activate(expect_ok=False, label="J3_blocked")
    j.check("J3.04", "activation blocked (PV-02, PV-03) and button disabled", ([x[0] for x in pv if x[1] == "FAIL"], enabled), (["PV-02", "PV-03"], False))
    j.go(f"#/resubmit/{pid}")
    j.shot("J3_resubmission_page")
    in03_v2 = add_col(orig["IN-03"], "memo", "a")
    p2 = j.inputs / "client_balances_corrected.csv"
    p2.write_bytes(in03_v2)
    j.upload("#file-IN-03", [p2])
    j.wait("!document.querySelector('#send-IN-03').disabled", 60)
    j.set_value("#reason-IN-03", "balance column restored")
    j.click("#send-IN-03")
    j.wait("location.hash.startsWith('#/processing/')", 60)
    j.wait("document.querySelector('#stages [data-stage=\"validation\"]') && !['pending','running'].includes(document.querySelector('#stages [data-stage=\"validation\"]').dataset.status)", 300)
    j.shot("J3_IN03_v2_processing")
    pid, v03b = j.open_review("IN-03")
    j.check("J3.05", "fresh review: v2 starts with zero decisions", j.js("[...document.querySelectorAll('#mapping tr[data-idx] td:last-child')].every(td => td.textContent.includes('Undecided'))"), True)
    j.check("J3.06", "v2 is a new version", "version 2" in j.text("#main .page-head"), True)
    j.shot("J3_IN03_v2_fresh_review")
    j.decide(7, "IGNORE_COLUMN", "TEST-ONLY: working column (constant 'a'), not an IN-03 field")
    for idx in range(7):
        j.decide(idx, "MAP", "TEST-ONLY: header is the exact IN-03 canonical field name")
    outc = j.complete("TEST-ONLY: reviewed again from scratch for v2")
    j.check("J3.07", "IN-03 v2 VALIDATED", "Validated" in outc, True)
    j.go(f"#/resubmit/{pid}")
    p3 = j.inputs / "sga_cashbook_canonical.csv"
    p3.write_bytes(orig["IN-10"])
    j.upload("#file-IN-10", [p3])
    j.wait("!document.querySelector('#send-IN-10').disabled", 60)
    j.set_value("#reason-IN-10", "canonical export from the ledger")
    j.click("#send-IN-10")
    j.wait("location.hash.startsWith('#/processing/')", 60)
    j.wait("document.querySelector('#stages [data-stage=\"validation\"]') && !['pending','running'].includes(document.querySelector('#stages [data-stage=\"validation\"]').dataset.status)", 300)
    j.shot("J3_IN10_v2_processing")
    pv, enabled, snap = j.validate_and_activate(label="J3_validation")
    j.check("J3.08", "all PV pass after corrections", pv, [[f"PV-0{i}", "PASS"] for i in range(1, 10)])
    j.go(f"#/history/{pid}")
    hist = j.api(f"packages/{pid}/history")
    states = {c["evidence_category"]: [v["version_status"] for v in c["versions"]] for c in hist["categories"] if c["evidence_category"] in ("IN-03", "IN-10")}
    j.check("J3.09", "version states after activation", states, {"IN-03": ["SUPERSEDED", "ACTIVE"], "IN-10": ["REJECTED", "ACTIVE"]})
    j.shot("J3_history")
    rid, facts, rows = j.reconcile(label="J3_reconciliation")
    j.check("J3.10", "CLEAN after corrections", facts.get("Reconciliation status"), "Clean")
    j.check("J3.11", "compare_answer_key vs ORIGINAL baseline answer key", b.answer_key(j.run_dir(rid), "set_01_clean_baseline"), {"matched": True, "differences": []})
    return j.finish({"package_id": pid, "run_id": rid})


def j4_mixed(b: Bundle, out: Path, rec) -> dict:
    j = Journey("J4", "Mixed quality: missing / unsupported PDFs / unknown file -> blocked -> recovery -> CLEAN", b, out, rec)
    files = b.dataset("set_01_clean_baseline")
    orig = {fid: d for _, d, fid in files}
    names = {fid: n for n, _, fid in files}
    var = b.root / "fixtures" / "pdf_experiment" / "constructed"
    up = []
    for n, d, fid in files:
        if fid in ("IN-08", "IN-18", "IN-19"):
            continue
        if fid == "IN-05":
            d = add_col(d, "reviewer_note", "ok")
        elif fid == "IN-15":
            n, d = "V02_table_layout_letter_GBP.pdf", (var / "V02_table_layout_letter_GBP.pdf").read_bytes()
        elif fid == "IN-16":
            n, d = "V06_image_only_letter.pdf", (var / "V06_image_only_letter.pdf").read_bytes()
        up.append((n, d))
    up.append(("mystery_export.csv", b"col_a,col_b,col_c\n1,2,3\n"))
    paths = write_inputs(j, up)
    view = j.intake(paths, declared={names["IN-05"]: "IN-05", "V02_table_layout_letter_GBP.pdf": "IN-15", "V06_image_only_letter.pdf": "IN-16"}, label="J4_intake")
    out_ = {f["name"]: f["outcome"] for f in view["files"]}
    j.check("J4.01", "unsupported PDFs FAILED_VALIDATION; unknown CSV not accepted; IN-05 review",
            (out_["V02_table_layout_letter_GBP.pdf"]["version_status"], out_["V06_image_only_letter.pdf"]["version_status"],
             out_["mystery_export.csv"]["version_status"], out_[names["IN-05"]]["version_status"]),
            ("FAILED_VALIDATION", "FAILED_VALIDATION", None, "REVIEW_REQUIRED"))
    scanned = " ".join(out_["V06_image_only_letter.pdf"]["reasons"])
    j.check("J4.02", "scanned PDF reported honestly: no OCR, category not determined", ("OCR is not supported" in scanned, "Image-only" in scanned), (True, True))
    j.check("J4.03", "processing page shows the scanned-PDF reason", "OCR is not supported" in j.text("#main"), True)
    pid = j.package_id()
    j.go(f"#/packages/{pid}")
    j.shot("J4_evidence_files_mixed")
    j.check("J4.04", "evidence-file screen lists missing IN-08 and the refused upload", ("Missing" in j.text("#main"), "mystery_export.csv" in j.text("#main")), (True, True))
    pv, enabled, _ = j.validate_and_activate(expect_ok=False, label="J4_blocked")
    j.check("J4.05", "activation blocked with PV-01..PV-04, button disabled", ([x[0] for x in pv if x[1] == "FAIL"], enabled), (["PV-01", "PV-02", "PV-03", "PV-04"], False))
    j.check("J4.06", "blocked explanation names IN-08", "IN-08" in j.text("#main .callout.bad"), True)
    pid, v05 = j.open_review("IN-05")
    j.decide(19, "IGNORE_COLUMN", "TEST-ONLY: reviewer note column ('ok' on every row), not an IN-05 field")
    for idx in range(19):
        j.decide(idx, "MAP", "TEST-ONLY: header is the exact IN-05 canonical field name")
    j.check("J4.07", "IN-05 VALIDATED", "Validated" in j.complete("TEST-ONLY: canonical headers mapped, reviewer note ignored"), True)
    j.go(f"#/resubmit/{pid}")
    j.shot("J4_resubmission_page")
    for cat, fn, mode in (("IN-08", names["IN-08"], "first"), ("IN-15", names["IN-15"], "resubmit"), ("IN-16", names["IN-16"], "resubmit")):
        j.go(f"#/resubmit/{pid}")
        p = j.inputs / f"corrected_{fn}"
        p.write_bytes(orig[cat])
        j.upload(f"#file-{cat}", [p])
        j.wait(f"!document.querySelector('#send-{cat}').disabled", 60)
        j.set_value(f"#reason-{cat}", "the bank's original key-details letter" if mode == "resubmit" else "missing evidence supplied")
        j.click(f"#send-{cat}")
        j.wait("location.hash.startsWith('#/processing/')", 60)
        j.wait("document.querySelector('#stages [data-stage=\"validation\"]') && !['pending','running'].includes(document.querySelector('#stages [data-stage=\"validation\"]').dataset.status)", 300)
        st = j.api(f"packages/{pid}")
        j.check(f"J4.08.{cat}", f"{cat} now VALIDATED", next(s for s in st["slots"] if s["evidence_category"] == cat)["state"], "VALIDATED")
    j.shot("J4_recovered_processing")
    pv, enabled, snap = j.validate_and_activate(label="J4_validation")
    j.check("J4.09", "all PV pass after recovery", pv, [[f"PV-0{i}", "PASS"] for i in range(1, 10)])
    rid, facts, rows = j.reconcile(label="J4_reconciliation")
    j.check("J4.10", "CLEAN after recovery", facts.get("Reconciliation status"), "Clean")
    return j.finish({"package_id": pid, "run_id": rid})


def j5_exceptions(b: Bundle, out: Path, rec) -> dict:
    j = Journey("J5", "Exception analysis: every discrepancy dataset vs its answer key (ZIP upload per dataset)", b, out, rec)
    exp = json.loads((b.root / "expected_results" / "E2E-06.json").read_text(encoding="utf-8"))
    table = []
    for ds in exp["datasets"]:
        name = ds["dataset"]
        files = b.zip_files(ds["source"][4:]) if ds["source"].startswith("zip:") else [(n, d) for n, d, _ in b.dataset(name)]
        zp = j.inputs / f"{name}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for n, d in files:
                z.writestr(n, d)
        view = j.intake([zp], label=f"J5_{name[:12]}")
        j.check(f"J5.{name}.01", "19 files VALIDATED", sorted({(f["outcome"] or {}).get("version_status") for f in view["files"]}), ["VALIDATED"])
        pv, enabled, snap = j.validate_and_activate(label=f"J5_{name[:12]}")
        rid, facts, rows = j.reconcile(label=f"J5_{name[:12]}")
        st = {"Clean": "CLEAN", "Exceptions open": "EXCEPTIONS_OPEN", "Evidence incomplete": "EVIDENCE_INCOMPLETE"}.get(facts.get("Reconciliation status"))
        j.check(f"J5.{name}.02", "status shown = expected", st, ds["case_status"])
        j.check(f"J5.{name}.03", "exception count shown = expected", facts.get("Exceptions"), str(ds["exception_count"]))
        ref = ds["reference_exceptions"]
        ui = [[r[0], r[1], r[3] if r[3] != "–" else "", r[6].replace(",", "") if r[6] != "–" else "", r[7]] for r in rows]
        want = [[x["exception_id"], x["severity"], x["account_id"], x["amount"], str(x["affected_results"])] for x in ref]
        j.check(f"J5.{name}.04", "UI exception rows (id, severity, account, amount, affected) = reference", ui, want)
        with open(j.run_dir(rid) / "case" / "validation" / "exceptions.csv", encoding="utf-8") as f:
            got = [{c: r[c] for c in exp["compared_columns"]} for r in csv.DictReader(f)]
        j.check(f"J5.{name}.05", "every engine exception row = reference (all compared columns)", got, ref)
        ak = b.answer_key(j.run_dir(rid), name)
        j.check(f"J5.{name}.06", "compare_answer_key vs ORIGINAL answer key", ak, {"matched": True, "differences": []})
        if rows:
            j.go(f"#/runs/{rid}/exceptions/{rows[0][0]}")
            ev_rows = j.js("[...document.querySelectorAll('#main table.t')][0].querySelectorAll('tbody tr').length")
            j.check(f"J5.{name}.07", "first exception detail opens with its evidence", ev_rows >= 1, True)
            j.shot(f"J5_{name[:12]}_exception_detail")
        table.append({"dataset": name, "status": st, "exceptions": len(rows), "expected": ds["exception_count"], "answer_key": ak["matched"]})
    return j.finish({"datasets": table})


def j6_defects(b: Bundle, out: Path, rec) -> dict:
    j = Journey("J6", "CSV defects: short row and header-only file are FAILED_VALIDATION; the rest of the upload is processed", b, out, rec)
    files = b.dataset("set_01_clean_baseline")
    orig = {fid: d for _, d, fid in files}
    names = {fid: n for n, _, fid in files}
    lines = orig["IN-01"].split(b"\n")
    short = b"\n".join(lines[:2] + [lines[2][: lines[2].rfind(b",")]] + lines[3:])
    hdr_only = orig["IN-11"].split(b"\n")[0] + b"\n"
    up = [(names["IN-01"], short), (names["IN-11"], hdr_only), (names["IN-02"], orig["IN-02"]), (names["IN-03"], orig["IN-03"])]
    paths = write_inputs(j, up)
    view = j.intake(paths, declared={names["IN-01"]: "IN-01", names["IN-11"]: "IN-11"}, label="J6_intake")
    st = {f["name"]: (f["outcome"] or {}).get("version_status") for f in view["files"]}
    j.check("J6.01", "short row -> FAILED_VALIDATION; header-only -> FAILED_VALIDATION; others VALIDATED",
            st, {names["IN-01"]: "FAILED_VALIDATION", names["IN-11"]: "FAILED_VALIDATION", names["IN-02"]: "VALIDATED", names["IN-03"]: "VALIDATED"})
    pid = j.package_id()
    v01 = next(f["outcome"]["file_version_id"] for f in view["files"] if f["name"] == names["IN-01"])
    v11 = next(f["outcome"]["file_version_id"] for f in view["files"] if f["name"] == names["IN-11"])
    j.go(f"#/history/{pid}/{v01}")
    j.check("J6.02", "handoff check 12 explains the short row", "the header has" in j.text("#main"), True)
    j.shot("J6_short_row_version")
    j.go(f"#/history/{pid}/{v11}")
    j.check("J6.03", "handoff check 11 explains the empty file", "EMPTY_FILE" in j.text("#main"), True)
    j.shot("J6_header_only_version")
    return j.finish({"package_id": pid})


JOURNEYS = {"J1": j1_clean, "J2": j2_hitl, "J3": j3_resubmission, "J4": j4_mixed, "J5": j5_exceptions, "J6": j6_defects}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--journeys", default=",".join(JOURNEYS))
    a = ap.parse_args()
    if not EDGE.exists():
        print("Microsoft Edge not installed")
        return 2
    b = Bundle(Path(a.bundle))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rec = [b.root / "fixtures" / "recorded_llm" / f for f in ("in10_ambiguous.json",)]
    summary = []
    for k in a.journeys.split(","):
        try:
            r = JOURNEYS[k](b, out, rec)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            r = {"journey": k, "checks_total": 0, "checks_passed": 0, "failed": [{"error": f"{type(exc).__name__}: {exc}"}]}
        summary.append({k_: r.get(k_) for k_ in ("journey", "title", "checks_total", "checks_passed", "failed", "screenshots")})
    (out / "journeys_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    ok = all(not s["failed"] for s in summary)
    print("ALL JOURNEYS PASS" if ok else "SOME JOURNEYS FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
