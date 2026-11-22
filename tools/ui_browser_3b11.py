"""Phase 3B-11 - REAL-BROWSER check of the mapping review screen (Microsoft Edge headless, DevTools protocol).

    py -3.11 tools/ui_browser_3b11.py --out <dir>

Builds a fresh demo workspace (tools/demo_3b11.py: recorded responses, no LLM), starts the review server on 127.0.0.1,
opens the page in headless Edge and drives it ONLY through the page's own controls (select a field, type a reason,
click Map / Change / Ignore / Leave unresolved / Map all / Complete). Every step asserts the rendered DOM, and the
final state is cross-checked against the package store. Full-page screenshots are written to <dir>. Loopback only.
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import websocket  # noqa: E402  (websocket-client; already installed)

import demo_3b11  # noqa: E402
from smartparser.review.authority import Reviewer  # noqa: E402
from smartparser.review_ui.server import serve  # noqa: E402

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TEST_AUTHORITY = HERE / "tests" / "fixtures" / "review" / "test_authority_policy.json"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Browser:
    def __init__(self, profile: Path):
        self.port = free_port()
        self.proc = subprocess.Popen([str(EDGE), "--headless=new", f"--remote-debugging-port={self.port}",
                                      "--remote-allow-origins=*", f"--user-data-dir={profile}", "--no-first-run",
                                      "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
                                      "--window-size=1400,1000", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = None
        for _ in range(100):
            try:
                targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2).read())
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not url:
            raise RuntimeError("Edge DevTools endpoint not available")
        self.ws = websocket.create_connection(url, timeout=30, suppress_origin=True)
        self.n = 0
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(f"JS error: {r['exceptionDetails'].get('text')} in {expr[:120]}")
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=20, what=""):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.js(expr):
                    return
            except RuntimeError:
                pass
            time.sleep(0.15)
        raise AssertionError(f"timed out waiting for {what or expr}")

    def goto(self, url):
        self.cmd("Page.navigate", {"url": url})

    def shot(self, path: Path):
        h = self.js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)") or 1000
        self.cmd("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": int(h), "deviceScaleFactor": 1,
                                                        "mobile": False})
        data = self.cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})["data"]
        path.write_bytes(base64.b64decode(data))
        self.cmd("Emulation.clearDeviceMetricsOverride")

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def txt(sel):
    return f"(document.querySelector({json.dumps(sel)})||{{}}).textContent||''"


def run(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sp11ui_"))
    steps = []
    try:
        idx = demo_3b11.build(work / "ws")
        reviewer = Reviewer(reviewer_id="ui-analyst-1", role="analyst", kind="TEST")
        port = free_port()
        httpd = serve(work / "ws", TEST_AUTHORITY, reviewer, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}/"
        b = Browser(work / "profile")
        try:
            def step(name, ok, detail=""):
                steps.append({"step": name, "ok": bool(ok), "detail": detail})
                if not ok:
                    raise AssertionError(f"{name}: {detail}")

            def open_review(k):
                b.js(f"location.hash = '#/review/{idx[k]['package_id']}/{idx[k]['file_version_id']}'")
                b.wait(f"document.querySelector('#info') && {txt('#info')}.includes('{idx[k]['package_id']}') && "
                       "document.querySelectorAll('#mapping tbody tr').length > 0", what=f"review {k}")

            def row(i, sel):
                return f"document.querySelector('#mapping tr[data-idx=\"{i}\"] {sel}')"

            def decided(i):
                return f"!{row(i, '.decision')} ? false : true"

            def complete():
                before = b.js("+document.body.dataset.renders || 0")
                b.js("document.querySelector('#complete').click()")
                b.wait(f"(+document.body.dataset.renders || 0) > {before} || !document.querySelector('#error').hidden",
                       timeout=60, what="completion re-render")
                time.sleep(0.2)

            # 1 queue
            b.goto(base)
            b.wait("document.querySelectorAll('#queue tbody tr').length === 4", what="queue rows")
            q = b.js(txt("#queue"))
            step("queue lists the 4 review tasks from the backend", all(s in q for s in (
                "UNMAPPABLE_PROPOSAL", "PROPOSAL_REVIEW", "HEADER_COUNT_MISMATCH")), q[:300])
            b.shot(out / "01_review_queue.png")

            # 2 C: unmappable, before
            open_review("C")
            r7 = b.js(txt('#mapping tr[data-idx="7"]'))
            step("UNMAPPABLE column shown unmapped with the LLM finding", "ref_code" in r7 and "Unmapped" in r7 and
                 "NO_MATCH" in r7 and "UNMAPPABLE" in r7, r7)
            step("review reason and counts shown", "no defensible canonical field" in b.js(txt("#info")) and
                 "8 / 8" in b.js(txt("#info")), b.js(txt("#info"))[:300])
            b.shot(out / "02_unmappable_review_before.png")

            # 3 invalid manual mapping refused by the backend
            b.js(f"{row(7, 'select.field')}.value = 'amount'")
            b.js(f"{row(7, 'button[data-action=CHANGE]')}.click()")
            b.wait("!document.querySelector('#error').hidden", what="error")
            step("invalid manual mapping refused (VALUE_INCOMPATIBLE)", "VALUE_INCOMPATIBLE" in b.js(txt("#error")),
                 b.js(txt("#error")))
            b.shot(out / "03_invalid_mapping_refused.png")

            # 4 resolve: map all suggested + manual CHANGE of ref_code -> payment_reference, complete
            b.js("document.querySelector('#map-all').click()")
            b.wait(" && ".join(decided(i) for i in range(7)), what="7 MAP decisions")
            b.js(f"{row(7, 'select.field')}.value = 'payment_reference'")
            b.js(f"{row(7, 'input.reason')}.value = 'ref_code carries the payment reference (checked with the bank)'")
            b.js(f"{row(7, 'button[data-action=CHANGE]')}.click()")
            b.wait(decided(7), what="manual mapping")
            step("summary: no required field left uncovered", "Required fields not covered" in b.js(txt("#summary"))
                 and "none" in b.js(txt("#summary")), b.js(txt("#summary")))
            b.shot(out / "04_unmappable_decisions_made.png")
            complete()
            o = b.js(txt("#outcome"))
            n_pass = b.js("[...document.querySelectorAll('#checks tbody tr')].filter(r => r.textContent.includes('PASS')).length")
            step("C completed: VALIDATED, reprocessed, 14/14 checks, preview, activation-eligible",
                 "VALIDATED" in o and "completed" in o and n_pass == 14 and "generated" in o, f"{n_pass} PASS; {o[:300]}")
            b.shot(out / "05_unmappable_resolved_outcome.png")

            # 5 B: ambiguous proposal session
            open_review("B")
            step("ambiguous proposals shown (AMBIGUOUS + PLAUSIBLE), no Ignore action offered",
                 "AMBIGUOUS" in b.js(txt("#mapping")) and "PLAUSIBLE" in b.js(txt("#mapping")) and
                 not b.js("!!document.querySelector('#mapping button[data-action=IGNORE_COLUMN]')"), "")
            b.shot(out / "06_ambiguous_review_before.png")
            for i in (4, 7):
                b.js(f"{row(i, 'button[data-action=MAP]')}.click()")
                b.wait(decided(i), what=f"session decision {i}")
            complete()
            o = b.js(txt("#outcome"))
            step("B completed through the proposal session: VALIDATED with 14 checks", "VALIDATED" in o and
                 b.js("document.querySelectorAll('#checks tbody tr').length") == 14, o[:300])
            b.shot(out / "07_ambiguous_resolved_outcome.png")

            # 6 D: unmappable left unresolved
            open_review("D")
            b.js("document.querySelector('#map-all').click()")
            b.wait(" && ".join(decided(i) for i in range(7)), what="D maps")
            b.js(f"{row(7, 'input.reason')}.value = 'cannot tell what the colour code means'")
            b.js(f"{row(7, 'button[data-action=LEAVE_UNRESOLVED]')}.click()")
            b.wait(decided(7), what="leave unresolved")
            complete()
            o = b.js(txt("#outcome"))
            step("D held: still REVIEW_REQUIRED, no reprocessing, no preview, not activation-eligible",
                 "REVIEW_REQUIRED" in o and "not run" in o and "none" in o and
                 b.js("document.querySelectorAll('#checks').length") == 0, o[:400])
            b.shot(out / "08_unmappable_left_unresolved_held.png")

            # 7 E: extra column ignored with a mandatory reason
            open_review("E")
            b.js(f"{row(8, 'button[data-action=IGNORE_COLUMN]')}.click()")
            b.wait("!document.querySelector('#error').hidden", what="reason required")
            step("Ignore without a reason is blocked", "REASON_REQUIRED" in b.js(txt("#error")), b.js(txt("#error")))
            b.js(f"{row(8, 'input.reason')}.value = 'operator memo, not evidence'")
            b.js(f"{row(8, 'button[data-action=IGNORE_COLUMN]')}.click()")
            b.wait(decided(8), what="ignore")
            b.js("document.querySelector('#map-all').click()")
            b.wait(" && ".join(decided(i) for i in range(8)), what="E maps")
            complete()
            o = b.js(txt("#outcome"))
            step("E completed: VALIDATED, ignored column in provenance", "VALIDATED" in o and ".provenance.json" in o,
                 o[:300])
            b.shot(out / "09_extra_column_ignored_outcome.png")

            # 8 queue afterwards
            b.js("location.hash = '#/'")
            b.wait("document.querySelectorAll('#queue tbody tr').length === 1", what="queue after")
            step("only the held file (D) remains in the queue", idx["D"]["file_version_id"] in b.js(
                "document.querySelector('#queue tbody tr').getAttribute('data-vid')"))
            b.shot(out / "10_review_queue_after.png")
        finally:
            b.close()
            httpd.shutdown()
        # cross-check with the package store (the UI showed backend state, not its own)
        svc = demo_3b11.build_service(work / "ws")
        st = {k: svc.load(idx[k]["package_id"]).versions[idx[k]["file_version_id"]].version_status for k in "BCDE"}
        steps.append({"step": "store state matches the screen", "ok": st == {"B": "VALIDATED", "C": "VALIDATED",
                                                                           "D": "REVIEW_REQUIRED", "E": "VALIDATED"},
                      "detail": st})
        svc.log.verify()
    except Exception as exc:
        steps.append({"step": "runner", "ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:500]}"})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    res = {"browser": f"Microsoft Edge headless ({EDGE.name})", "steps": steps, "all_ok": all(s["ok"] for s in steps)}
    (out / "ui_browser_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    r = run(Path(ap.parse_args().out))
    print(json.dumps({"all_ok": r["all_ok"], "steps": len(r["steps"])}))
    sys.exit(0 if r["all_ok"] else 1)
