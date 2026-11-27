"""UC-042 Smart Parser browser application server (single-user POC; Python standard library only).

    py -3.11 -m smartparser.webapp.server --root <workspace> --authority <TEST authority policy json>
         --uc042-root <read-only UC-042 tree> [--recorded-llm fixture.json ...] [--port 8780]
         [--reviewer-id ID --reviewer-role analyst --reviewer-kind TEST]
         --auth-file <credentials JSON> | env SMARTPARSER_AUTH_FILE   (or --insecure-no-auth for test harnesses)

Binds to 127.0.0.1 only. Authentication (auth.py): username/password checked server-side against a local credentials
file of PBKDF2 hashes; a server-side session is held in an HttpOnly SameSite=Strict cookie. Every /api route except
/api/auth/login, /api/auth/session and /api/ui/config answers 401 UNAUTHENTICATED without a valid session. The server refuses to
start without credentials unless --insecure-no-auth is given. Identity (Fix8 D6, identity.py): every authenticated
request runs as the SIGNED-IN user, who is the actor recorded on its actions; case mutations are limited to the case
owner or a supervisor (authz.py). The server reviewer (--reviewer-id/--reviewer-role/--reviewer-kind) acts only for
system work (job threads without a request, closure auto jobs) and, with --insecure-no-auth, for every request
(harness mode: no user, authorisation not enforced). Every review action still
goes through the AuthorityPolicy (the shipped production policy authorises nobody). Every POST must carry the header
`X-Smartparser-Client: webapp` (a custom header cannot be sent cross-site without a CORS preflight, which this server
never grants). Mapping proposals: disabled (default), recorded fixtures (--recorded-llm), or LIVE (--mapping-ai on with
--ai-env-file; Fix8 D1) - deterministic mapping first, only unresolved headers sent, every proposal decided by a person.
"""
from __future__ import annotations

import argparse
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ..review.authority import Reviewer
from . import api
from . import auth as auth_mod
from .context import AppContext

STATIC = Path(__file__).parent / "static"
STATIC_FILES = {"index.html", "app.css", "app.js", "design.html", "favicon.svg"}
MAX_BODY = 120 * 1024 * 1024
RF_DIR = Path(__file__).parent / "ringfence"
RF_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


def _build_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.suffix in RF_TYPES} \
        if root.is_dir() else set()


RF_FILES = _build_files(RF_DIR)
# The delivered Ringfence analyst application (ringfence-analyst-app, `npm run build:backend`), served same-origin.
ANALYST_DIR = Path(__file__).parent / "analyst"
ANALYST_FILES = _build_files(ANALYST_DIR)
BUILDS = {"rf": (RF_DIR, RF_FILES), "analyst": (ANALYST_DIR, ANALYST_FILES)}
# Colour themes the analyst app offers. The server decides the default (--default-theme / $SMARTPARSER_DEFAULT_THEME);
# a user's own Light/Dark choice is kept in their browser and overrides it.
THEMES = ("light", "dark")
DEFAULT_THEME = "light"


class App:
    def __init__(self, ctx: AppContext, auth: "auth_mod.Authenticator | None" = None, default_theme: str = DEFAULT_THEME):
        # auth=None means no authentication (unit tests that drive App directly, or --insecure-no-auth).
        if default_theme not in THEMES:
            raise ValueError(f"default_theme must be one of {THEMES}, not {default_theme!r}")
        self.ctx = ctx
        self.auth = auth
        self.default_theme = default_theme
        # Fix8 D6/D7: user roles (api.user_profile) come from THIS authenticator instance, not a module registry
        ctx.authenticator = auth

    def handle(self, method: str, raw_path: str, headers, body: bytes) -> tuple[int, str, bytes]:
        return self.handle_ex(method, raw_path, headers, body)[:3]

    def handle_ex(self, method: str, raw_path: str, headers, body: bytes) -> tuple[int, str, bytes, list]:
        """Like handle(), plus extra response headers (Set-Cookie) as a list of (name, value)."""
        u = urlsplit(raw_path)
        parts = [unquote(p) for p in u.path.strip("/").split("/") if p]
        if parts[:2] == ["api", "auth"]:
            return self._auth_route(method, parts[2:], headers, body)
        if parts[:2] == ["api", "ui"]:
            # Public (the sign-in screen needs it before a session exists); carries no case or user data.
            if method == "GET" and parts[2:] == ["config"]:
                return (*self._json({"default_theme": self.default_theme, "themes": list(THEMES)}), [])
            return (*self._json({"error": "NOT_FOUND", "message": u.path}, 404), [])
        sess = None
        if parts[:1] == ["api"] and self.auth is not None:
            sess = self.auth.session(self.auth.token_from(headers))      # validated once (refreshes the idle timer)
            if sess is None:
                return (*self._json({"error": "UNAUTHENTICATED", "message": "Sign in to continue."}, 401), [])
        # The signed-in username is the request's identity (api.acting / identity.py): it is the recorded actor of every
        # action and is checked against case ownership. Without a session (--insecure-no-auth) the server reviewer acts.
        r = self._handle(method, raw_path, headers, body, user=sess.username if sess else None)
        return (r[0], r[1], r[2], list(r[3]) if len(r) > 3 else [])

    def _auth_route(self, method, P, headers, body):
        """/api/auth/session (GET), /api/auth/login and /api/auth/logout (POST). Bodies are never logged."""
        a = self.auth
        if method == "GET" and P == ["session"]:
            if a is None:
                return (*self._json({"auth_enabled": False, "authenticated": True, "user": None}), [])
            s = a.session(a.token_from(headers))
            if s is None:
                return (*self._json({"auth_enabled": True, "authenticated": False, "user": None}), [])
            return (*self._json({"auth_enabled": True, "authenticated": True, "user": {"username": s.username}}), [])
        if method != "POST" or P not in (["login"], ["logout"]):
            return (*self._json({"error": "NOT_FOUND", "message": "/api/auth/" + "/".join(P)}, 404), [])
        if headers.get("X-Smartparser-Client") != "webapp":
            return (*self._json({"error": "FORBIDDEN", "message": "missing client header"}, 403), [])
        if P == ["logout"]:
            if a is None:
                return (*self._json({"authenticated": False}), [])
            a.logout(a.token_from(headers))
            return (*self._json({"authenticated": False}), [("Set-Cookie", a.clear_cookie())])
        if a is None:
            return (*self._json({"auth_enabled": False, "authenticated": True, "user": None}), [])
        try:
            doc = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            doc = None
        if not isinstance(doc, dict):
            return (*self._json({"error": "INVALID", "message": "the request body must be a JSON object"}, 400), [])
        username, password = doc.get("username"), doc.get("password")
        if isinstance(username, str) and a.locked_out(username):
            return (*self._json({"error": "TOO_MANY_ATTEMPTS",
                                 "message": "Too many failed sign-in attempts. Wait a minute and try again."}, 429), [])
        token = a.login(username, password)
        if token is None:
            return (*self._json({"error": "INVALID_CREDENTIALS", "message": "Incorrect username or password."}, 401), [])
        a.logout(a.token_from(headers))  # a fresh token on every sign-in (no session fixation)
        return (*self._json({"auth_enabled": True, "authenticated": True, "user": {"username": username}}),
                [("Set-Cookie", a.set_cookie(token))])

    def _handle(self, method: str, raw_path: str, headers, body: bytes, user: str | None = None) -> tuple[int, str, bytes]:
        u = urlsplit(raw_path)
        parts = [unquote(p) for p in u.path.strip("/").split("/") if p]
        if method == "GET" and (not parts or (len(parts) == 1 and parts[0] in STATIC_FILES)):
            name = parts[0] if parts else "index.html"
            p = STATIC / name
            ctype = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
                     ".svg": "image/svg+xml"}[p.suffix] + "; charset=utf-8"
            return 200, ctype, p.read_bytes()
        if method == "GET" and parts[:1] and parts[0] in BUILDS:
            # React build output (/rf/, /analyst/). Only files that exist in the build folder at startup are served.
            root, files = BUILDS[parts[0]]
            rel = "/".join(parts[1:]) or "index.html"
            if rel not in files:
                return self._json({"error": "NOT_FOUND", "message": u.path}, 404)
            p = root / rel
            return 200, RF_TYPES[p.suffix], p.read_bytes()
        if parts[:1] != ["api"]:
            return self._json({"error": "NOT_FOUND", "message": u.path}, 404)
        if method == "POST" and headers.get("X-Smartparser-Client") != "webapp":
            return self._json({"error": "FORBIDDEN", "message": "missing client header"}, 403)
        try:
            doc = json.loads(body or b"{}") if method == "POST" else {}
            if not isinstance(doc, dict):
                raise api.HttpError(400, "INVALID", "the request body must be a JSON object")
        except json.JSONDecodeError:
            return self._json({"error": "INVALID", "message": "the request body is not valid JSON"}, 400)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            out = api.route(self.ctx, method, parts[1:], q, doc, user=user)
        except Exception as exc:
            e = api.to_http(exc)
            if e.status >= 500:
                traceback.print_exc()
            return self._json({**getattr(e, "extra", {}), "error": e.code, "message": e.message}, e.status)
        if isinstance(out, tuple):
            if len(out) > 2:                                       # (ctype, bytes, headers): closure reports
                return 200, out[0], out[1], self._report_headers(out[0], out[2])
            return 200, out[0], out[1]
        return self._json(out)

    @staticmethod
    def _report_headers(ctype: str, headers: dict) -> list:
        """Per-route headers for the audit-pack / preview / final-pack reports. They may be framed by this origin only
        (frame-ancestors 'self'); report HTML is sandboxed (no script, no same-origin access, no forms); a PDF cannot
        be sandboxed (browsers refuse to run the PDF viewer in a sandboxed document) and is served with no
        script / connect permissions."""
        out = [(k, v) for k, v in headers.items()]
        if ctype.startswith("text/html"):
            csp = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; sandbox; "
                   "frame-ancestors 'self'")
        elif ctype.startswith("application/pdf"):
            csp = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'"
        else:
            csp = "default-src 'none'; frame-ancestors 'self'; sandbox"
        return out + [("Content-Security-Policy", csp), ("X-Frame-Options", "SAMEORIGIN")]

    @staticmethod
    def _json(doc, status=200):
        return status, "application/json; charset=utf-8", json.dumps(doc, ensure_ascii=False, default=str).encode()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                status, ctype, data, extra = 413, "application/json", b'{"error":"TOO_LARGE","message":"request too large"}', []
            else:
                status, ctype, data, extra = app.handle_ex(method, self.path, self.headers, self.rfile.read(n) if n else b"")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            own_csp = False
            for k, v in extra:
                own_csp = own_csp or k.lower() == "content-security-policy"
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if not own_csp:
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                                                        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send("GET")

        def do_POST(self):
            self._send("POST")

        def log_message(self, *a):
            pass
    return Handler


def serve(ctx: AppContext, port: int = 8780, auth: "auth_mod.Authenticator | None" = None,
          default_theme: str = DEFAULT_THEME) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(App(ctx, auth, default_theme)))
    httpd.daemon_threads = True
    return httpd


def _mapping_ai_settings(a):
    from ..ai.live_config import MappingAISettings
    pricing = json.loads(Path(a.ai_pricing_file).read_text(encoding="utf-8")) if a.ai_pricing_file else None
    return MappingAISettings(enabled=a.mapping_ai == "on", env_file=a.ai_env_file,
                             max_calls_per_day=a.mapping_ai_max_calls_per_day,
                             max_output_tokens=a.mapping_ai_max_output_tokens,
                             max_cost_per_day=a.mapping_ai_max_cost_per_day,
                             timeout_seconds=a.mapping_ai_timeout_seconds, max_retries=max(0, a.mapping_ai_max_retries),
                             send_value_shapes=a.mapping_ai_send_value_shapes, pricing=pricing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="workspace folder (created if missing)")
    ap.add_argument("--authority", default=None, help="authority policy JSON (default: the shipped production policy, "
                                                      "which authorises nobody)")
    ap.add_argument("--uc042-root", default=None, help="read-only UC-042 tree for reconciliation")
    ap.add_argument("--recorded-llm", nargs="*", default=[], help="recorded LLM response fixtures (offline)")
    ap.add_argument("--reviewer-id", default="poc-analyst")
    ap.add_argument("--reviewer-role", default="analyst")
    ap.add_argument("--reviewer-kind", default="TEST", choices=["TEST", "BUSINESS"])
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--default-theme", choices=THEMES,
                    default=os.environ.get("SMARTPARSER_DEFAULT_THEME", DEFAULT_THEME).strip().lower(),
                    help="colour theme the analyst app opens in until a user picks Light or Dark "
                         "(default: $SMARTPARSER_DEFAULT_THEME, else light)")
    ap.add_argument("--demo-scenarios", default=None, help="folder of Ringfence demo scenarios (p10/RINGFENCE_DEMO_TEST_DATA); "
                                                           "enables /api/demo/... Use a dedicated demo workspace (--root)")
    ap.add_argument("--auth-file", default=None, help="credentials JSON of PBKDF2 hashes (default: $SMARTPARSER_AUTH_FILE); "
                                                      "create with: python -m smartparser.webapp.auth set-password")
    ap.add_argument("--session-idle-minutes", type=float, default=30)
    ap.add_argument("--session-max-hours", type=float, default=8)
    ap.add_argument("--cookie-secure", action="store_true", help="add Secure to the session cookie (HTTPS front end)")
    ap.add_argument("--insecure-no-auth", action="store_true", help="disable sign-in (local test harnesses only)")
    ap.add_argument("--closure-python", default=None, help="interpreter for the closure library operations (audit pack, "
                                                          "AI investigations, final pack); without it closure is UNAVAILABLE")
    ap.add_argument("--ai-env-file", default=None, help="env file read with an exact key allowlist (OPENAI_API_KEY, "
                                                        "UC042_LLM_PROVIDER/MODEL/TIMEOUT_SECONDS/MAX_TOKENS, "
                                                        "UC042_OPENAI_REASONING_EFFORT); without it AI is UNAVAILABLE")
    ap.add_argument("--ai-pricing-file", default=None, help='JSON {model: {input_per_m, cached_input_per_m, output_per_m}}; '
                                                            "without it cost is null")
    ap.add_argument("--ai-max-requests-per-operation", type=int, default=None,
                    help="hard cap of AI requests per investigation / closing summary (default: the library's own limits)")
    # Fix8 D1: live AI mapping proposals (deterministic mapping always runs first; a person decides every proposal)
    ap.add_argument("--mapping-ai", choices=["on", "off"], default="off",
                    help="live AI proposals for columns the deterministic rules leave unresolved (needs --ai-env-file; "
                         "default off)")
    ap.add_argument("--mapping-ai-max-calls-per-day", type=int, default=20,
                    help="hard daily cap of mapping provider calls (ledger kept in the workspace)")
    ap.add_argument("--mapping-ai-max-output-tokens", type=int, default=4000)
    ap.add_argument("--mapping-ai-max-cost-per-day", type=float, default=1.0,
                    help="daily cost cap (enforced only when --ai-pricing-file prices the model)")
    ap.add_argument("--mapping-ai-timeout-seconds", type=float, default=None,
                    help="per-call timeout (default UC042_LLM_TIMEOUT_SECONDS from the env file, else 60)")
    ap.add_argument("--mapping-ai-max-retries", type=int, default=1)
    ap.add_argument("--mapping-ai-send-value-shapes", action="store_true",
                    help="also send character-class value shapes (never values); owner default: off")
    a = ap.parse_args()
    if a.default_theme not in THEMES:
        ap.error(f"SMARTPARSER_DEFAULT_THEME must be one of {', '.join(THEMES)}")
    if a.mapping_ai == "on" and a.recorded_llm:
        ap.error("--mapping-ai on and --recorded-llm are mutually exclusive")
    for n in ("mapping_ai_max_calls_per_day", "mapping_ai_max_output_tokens"):
        if getattr(a, n) < 1:
            ap.error(f"--{n.replace('_', '-')} must be at least 1")
    auth = None
    if not a.insecure_no_auth:
        path = auth_mod.resolve_auth_file(a.auth_file)
        if path is None:
            ap.error("no credentials configured: pass --auth-file or set SMARTPARSER_AUTH_FILE "
                     "(or --insecure-no-auth for local test harnesses)")
        try:
            auth = auth_mod.Authenticator.from_file(path, idle_seconds=a.session_idle_minutes * 60,
                                                    max_seconds=a.session_max_hours * 3600, cookie_secure=a.cookie_secure)
        except auth_mod.AuthConfigError as exc:
            ap.error(str(exc))
    ctx = AppContext(root=Path(a.root), authority_path=Path(a.authority) if a.authority else None,
                     reviewer=Reviewer(reviewer_id=a.reviewer_id, role=a.reviewer_role, kind=a.reviewer_kind),
                     uc042_root=Path(a.uc042_root).resolve() if a.uc042_root else None,
                     recorded=[Path(p) for p in a.recorded_llm], mapping_ai=_mapping_ai_settings(a))
    if a.demo_scenarios:
        from .demo import DemoScenarios
        ctx.demo = DemoScenarios(Path(a.demo_scenarios))
    from ..reconciliation.closure_runner import ClosureRunner
    from .closure import ClosureService
    ctx.closure = ClosureService(ctx, ClosureRunner(ctx.uc042_root, a.closure_python, a.ai_env_file, a.ai_pricing_file,
                                                    a.ai_max_requests_per_operation))
    httpd = serve(ctx, a.port, auth, a.default_theme)
    print(f"UC-042 Smart Parser application on http://127.0.0.1:{a.port}/  (workspace {ctx.root}; "
          f"{'sign-in required' if auth else 'AUTHENTICATION DISABLED (--insecure-no-auth)'})", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
