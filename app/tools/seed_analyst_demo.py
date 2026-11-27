"""The Ringfence analyst application with its demo cases: ONE server, ONE workspace, ONE email sign-in.

Canonical preload and startup tool (consolidated 19 Nov 2026). Supersedes tools/preload_demo_cases.py.

Step 1 - the analyst creates their account with the EXISTING password mechanism (hidden prompt, typed twice;
         only a PBKDF2 hash is stored):

    py -3.11 -m smartparser.webapp.auth set-password --file C:\\u42v\\ringfence_demo_final\\auth.json --username <email>

Step 2 - the single startup command (port 8780):

    py -3.11 -B tools/seed_analyst_demo.py --home C:\\u42v\\ringfence_demo_final

On the FIRST start the workspace is new: the command asks for the analyst's password (hidden prompt, used only to sign
in), starts the server, signs in through POST /api/auth/login and registers the scenario ZIPs (SCENARIO_IDS) through
POST /api/cases, all assigned to the analyst, then keeps serving. On later starts it only serves.
The Work Queue also shows the demo scenarios as a separate section (Load scenario = the same POST /api/cases
registration as a manual upload; there is no separate Demo menu). Closure (audit pack, automatic AI investigations,
closing review, final PDF) is enabled with --closure-python and, for AI, --ai-env-file (exact key allowlist).
The cases stay WAITING: Smart Parsing, review, activation and reconciliation run only when the analyst presses Start,
on the real Smart Parser and UC-042 engine. No result is preloaded and no answer key is read.

Rules enforced here:
* auth.json must hold exactly ONE user and that user must be an email address; the password is never written by this
  tool, never logged and never passed on a command line (getpass, or $RF_DEMO_PASSWORD for test harnesses only).
* sign-in is always on (the server is never started with --insecure-no-auth); there is no separate Demo menu.
* an existing workspace is never re-seeded; known older demo workspaces are refused outright.

SINGLE-ANALYST LIMITATION (owner decision, 19 Nov 2026): the server records every action under ONE reviewer identity
fixed at start-up (--reviewer-id). It is set to the analyst's sign-in email, which holds ONLY because the credentials
file has exactly one user. Identity is NOT linked to the session per request; per-session reviewer attribution is a
separate, unimplemented change.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smartparser.webapp import auth as auth_mod  # noqa: E402

REPO = ROOT.parent
DEFAULT_HOME = REPO / ".runtime" / "demo_home"
DEFAULT_PORT = 8780
DEFAULT_SCENARIOS = REPO / "demo_datasets" / "ringfence_demo_scenarios"
DEFAULT_UC042 = REPO / "uc042"
TEST_POLICY = ROOT / "tests" / "fixtures" / "review" / "test_authority_policy.json"
# Registered in this order (reporting periods Jun, Jul, Oct, Nov, Sep 2026). The Work Queue keeps its existing
# date-based order (WAITING oldest received first, ties within the same second by case reference). No priority exists.
SCENARIO_IDS = ("RF-DEMO-01", "RF-DEMO-02", "RF-DEMO-03", "RF-DEMO-04", "RF-DEMO-05")
# Closure library interpreter and AI credentials file (read-only use; the server reads the key with an exact allowlist)
DEFAULT_CLOSURE_PYTHON = Path(sys.executable)
DEFAULT_AI_ENV = REPO / ".runtime" / ".env"
# Earlier demo workspaces, kept as backups: never used or modified by this tool.
PROTECTED = [Path(p) for p in (r"C:\u42v\rf_demo_ws", r"C:\u42v\ringfence_demo_ws", r"C:\u42v\ringfence_analyst_demo",
                               r"C:\u42v\analyst_demo", r"C:\u42v\analyst_demo_journey")]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_ENV = "RF_DEMO_PASSWORD"


def analyst_of(home: Path) -> str:
    """The single analyst: exactly one user in <home>/auth.json, and it must be an email address."""
    path = home / "auth.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found. Create the analyst account first (hidden password prompt):\n"
                         f"  py -3.11 -m smartparser.webapp.auth set-password --file {path} --username <email>")
    users = list(auth_mod.load_users(path))
    if len(users) != 1:
        raise SystemExit(f"{path} must hold exactly one user for the single-analyst setup (found {len(users)})")
    if not EMAIL_RE.match(users[0]):
        raise SystemExit(f"the sign-in identifier in {path} must be an email address")
    return users[0]


def server_cmd(home: Path, username: str, port: int, uc042_root: Path, scenarios_dir: Path | None = None,
               closure_python: Path | None = None, ai_env_file: Path | None = None,
               extra_args: list[str] | None = None) -> list[str]:
    cmd = [sys.executable, "-B", "-m", "smartparser.webapp.server", "--root", str(home / "ws"),
           "--authority", str(TEST_POLICY), "--uc042-root", str(uc042_root),
           "--reviewer-id", username, "--reviewer-role", "analyst", "--reviewer-kind", "TEST",
           "--auth-file", str(home / "auth.json"), "--port", str(port)]
    if scenarios_dir:
        cmd += ["--demo-scenarios", str(scenarios_dir)]
    if closure_python:
        cmd += ["--closure-python", str(closure_python)]
    if ai_env_file:
        cmd += ["--ai-env-file", str(ai_env_file)]
    return cmd + list(extra_args or [])        # e.g. ["--ai-max-requests-per-operation", "3"] (test harnesses)


def start_server(home: Path, username: str, port: int, uc042_root: Path, log_name: str | None,
                 scenarios_dir: Path | None = None, closure_python: Path | None = None,
                 ai_env_file: Path | None = None, extra_args: list[str] | None = None) -> subprocess.Popen:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop(PASSWORD_ENV, None)                                       # the server never needs the password
    out = open(home / log_name, "ab") if log_name else None
    p = subprocess.Popen(server_cmd(home, username, port, uc042_root, scenarios_dir, closure_python, ai_env_file,
                                    extra_args),
                         cwd=str(ROOT), env=env,
                         stdout=out, stderr=subprocess.STDOUT if out else None)
    url = f"http://127.0.0.1:{port}/api/auth/session"
    for _ in range(150):
        if p.poll() is not None:
            raise SystemExit(f"server exited early (code {p.returncode}); is port {port} already in use?")
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return p
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.2)
    p.terminate()
    raise SystemExit("server did not become ready")


class Client:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if method == "POST":
            req.add_header("X-Smartparser-Client", "webapp")
            req.add_header("Content-Type", "application/json")
        try:
            with self.op.open(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # bodies of auth calls are never echoed (they could only contain an error code, but stay safe)
            raise SystemExit(f"{method} {path} -> HTTP {e.code}") from None


def scenarios(folder: Path) -> list[dict]:
    out = []
    for d in sorted(p for p in folder.iterdir() if p.is_dir() and (p / "scenario.json").is_file()):
        m = json.loads((d / "scenario.json").read_text(encoding="utf-8"))
        if m["scenario_id"] in SCENARIO_IDS:
            out.append(m | {"_zip": d / m["zip"]["file"]})
    if sorted(x["scenario_id"] for x in out) != sorted(SCENARIO_IDS):
        raise SystemExit(f"expected scenarios {sorted(SCENARIO_IDS)} in {folder}")
    for m in out:
        if hashlib.sha256(m["_zip"].read_bytes()).hexdigest() != m["zip"]["sha256"]:
            raise SystemExit(f"{m['_zip']} does not match the sha256 in its scenario.json")
    return sorted(out, key=lambda m: m["scenario_id"])


def check_home(home: Path) -> None:
    if any(home == p.resolve() or p.resolve() in home.parents or home in p.resolve().parents for p in PROTECTED):
        raise SystemExit(f"{home} is (or contains) an earlier demo workspace kept as a backup; use another --home")


def seeded(home: Path) -> bool:
    return (home / "seed_record.json").is_file()


def seed(home: Path, username: str, password: str, port: int, scenarios_dir: Path, uc042_root: Path) -> list[dict]:
    """Register the scenario cases through the authenticated API of the server already running on `port`."""
    # the server creates the empty workspace layout on start-up; refuse only if a case already exists in it
    if any((home / "ws" / "cases").glob("RF-*.json")):
        raise SystemExit(f"{home / 'ws'} already has cases but no seed record; refusing to seed into it")
    items = scenarios(scenarios_dir)
    cl = Client(port)
    s = cl.call("POST", "/api/auth/login", {"username": username, "password": password})
    if not (s.get("authenticated") and s["user"]["username"] == username):
        raise SystemExit("sign-in failed")
    app = cl.call("GET", "/api/app")
    if app["reviewer"]["reviewer_id"] != username:
        raise SystemExit("server is not configured for the single-analyst demo")
    made = []
    for m in items:
        c = cl.call("POST", "/api/cases", {
            "customer_name": m["customer_name"], "reporting_period": m["reporting_period"],
            "zip_name": m["_zip"].name, "zip_b64": base64.b64encode(m["_zip"].read_bytes()).decode(),
            "assigned_to": username})
        made.append({"scenario_id": m["scenario_id"], "case_ref": c["case_ref"], "customer_name": c["customer_name"],
                     "reporting_period": c["reporting_period"], "status": c["status"],
                     "assigned_to": c["assigned_to"], "zip_file": m["_zip"].name, "zip_sha256": c["zip"]["sha256"]})
        print(f"registered {c['case_ref']}  {c['customer_name']:<28} {c['reporting_period']}  "
              f"[{c['status']}]", flush=True)
    q = cl.call("GET", "/api/cases?assigned=me")
    # Compare as a set: the queue's order is the backend's (WAITING oldest first by created_at, then case_ref), and
    # registrations made within the same second tie-break by case_ref, which is not the registration order (with
    # RF-DEMO-05, period 2026-09 sorts before 2026-10/2026-11). Fixed 20 Nov 2026 (final E2E round).
    if sorted(x["case_ref"] for x in q["items"]) != sorted(x["case_ref"] for x in made):
        raise SystemExit("Work Queue (My cases) does not list exactly the registered cases")
    cl.call("POST", "/api/auth/logout", {})
    rec = {"home": str(home), "workspace": str(home / "ws"), "analyst_is_single_user": True,
           "single_analyst_limitation": "actions are recorded under the reviewer identity fixed at server start-up "
                                        "(--reviewer-id = the analyst's sign-in email); not linked per session",
           "scenarios_folder": str(scenarios_dir.resolve()), "uc042_root": str(uc042_root), "cases": made,
           "seeded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (home / "seed_record.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return made


def password_for(username: str) -> str:
    pw = os.environ.get(PASSWORD_ENV)
    if pw is None:
        pw = getpass.getpass(f"Password for {username} (used only to sign in and register the demo cases): ")
    if not pw:
        raise SystemExit("no password given")
    return pw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", default=str(DEFAULT_HOME), help="folder holding auth.json (step 1), ws\\ and the seed record")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    ap.add_argument("--uc042-root", default=str(DEFAULT_UC042), type=Path)
    ap.add_argument("--seed-only", action="store_true", help="register the cases, then stop (test harnesses)")
    ap.add_argument("--closure-python", default=str(DEFAULT_CLOSURE_PYTHON),
                    help="interpreter for audit pack / investigation / final PDF ('' = closure disabled)")
    ap.add_argument("--ai-env-file", default=str(DEFAULT_AI_ENV), help="AI credentials file ('' = AI unavailable)")
    a = ap.parse_args(argv)
    home = Path(a.home).resolve()
    check_home(home)
    username = analyst_of(home)
    pw = None if seeded(home) else password_for(username)
    cp = Path(a.closure_python) if a.closure_python and Path(a.closure_python).is_file() else None
    ai = Path(a.ai_env_file) if a.ai_env_file and Path(a.ai_env_file).is_file() else None
    proc = start_server(home, username, a.port, a.uc042_root, "server_seed.log" if a.seed_only else None,
                        Path(a.scenarios), cp, ai)
    try:
        if pw is not None:
            seed(home, username, pw, a.port, Path(a.scenarios), a.uc042_root)
            pw = None
            print(f"seeded the demo cases in {home / 'ws'}", flush=True)
        if a.seed_only:
            return 0
        print(f"Ringfence analyst application: http://127.0.0.1:{a.port}/analyst/   (Ctrl+C to stop)", flush=True)
        return proc.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=30)


if __name__ == "__main__":
    sys.exit(main())
