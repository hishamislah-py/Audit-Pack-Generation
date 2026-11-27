"""Username/password authentication for the webapp server (smartparser.webapp.auth + server.App).

Pins: credentials are checked server-side against PBKDF2 hashes from a local file; a valid login sets an HttpOnly
SameSite=Strict session cookie and invalid credentials answer 401 INVALID_CREDENTIALS without a cookie; the session
survives further requests (a browser refresh is just another request with the cookie); logout invalidates the session
server-side so the old cookie is refused; every /api route except /api/auth/login and /api/auth/session answers 401
without a session; repeated failures are throttled; the server refuses to start without credentials unless
--insecure-no-auth is given; the password never appears in any response or server output."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from smartparser.webapp import auth
from smartparser.webapp import server as server_mod
from smartparser.webapp.server import App, serve

from .test_webapp_api import ctx_for

PW = "correct horse battery"
POST_H = {"X-Smartparser-Client": "webapp"}


def make_auth(**kw):
    return auth.Authenticator({"alice": auth.hash_password(PW, 1000)}, **kw)


def H(app, method, path, body=None, cookie=None, client=True):
    h = dict(POST_H) if (method == "POST" and client) else {}
    if cookie:
        h["Cookie"] = cookie
    s, ctype, data, extra = app.handle_ex(method, path, h, json.dumps(body or {}).encode() if method == "POST" else b"")
    return s, (json.loads(data) if ctype.startswith("application/json") else data), dict(extra)


def login(app, username="alice", password=PW):
    s, b, extra = H(app, "POST", "/api/auth/login", {"username": username, "password": password})
    cookie = extra.get("Set-Cookie", "").split(";")[0] if s == 200 else None
    return s, b, extra, cookie


# ---------------------------------------------------------------- hashing and credential file

def test_hash_roundtrip_and_salting():
    h1, h2 = auth.hash_password("pw-123456", 1000), auth.hash_password("pw-123456", 1000)
    assert h1 != h2 and h1.startswith("pbkdf2_sha256$1000$")
    assert auth.verify_password("pw-123456", h1) and not auth.verify_password("pw-123457", h1)
    assert not auth.verify_password("x", "garbage") and not auth.verify_password("x", "md5$1$a$b")


def test_credentials_file_cli_and_validation(tmp_path, monkeypatch, capsys):
    f = tmp_path / "creds" / "auth.json"
    monkeypatch.setenv("RF_TEST_PW", PW)
    assert auth.main(["set-password", "--file", str(f), "--username", "alice", "--password-env", "RF_TEST_PW"]) == 0
    out = capsys.readouterr()
    assert PW not in out.out + out.err
    text = f.read_text()
    assert PW not in text and "pbkdf2_sha256$" in text
    users = auth.load_users(f)
    assert set(users) == {"alice"} and auth.verify_password(PW, users["alice"])
    monkeypatch.setenv("RF_TEST_PW", "short")
    assert auth.main(["set-password", "--file", str(f), "--username", "bob", "--password-env", "RF_TEST_PW"]) == 2
    assert set(auth.load_users(f)) == {"alice"}
    (tmp_path / "bad.json").write_text(json.dumps({"users": [{"username": "x", "password": "plain"}]}))
    with pytest.raises(auth.AuthConfigError):
        auth.load_users(tmp_path / "bad.json")
    with pytest.raises(auth.AuthConfigError):
        auth.load_users(tmp_path / "missing.json")


# ---------------------------------------------------------------- the HTTP contract (App)

def test_api_requires_session(tmp_path):
    app = App(ctx_for(tmp_path), make_auth())
    for m, p in [("GET", "/api/app"), ("GET", "/api/cases"), ("GET", "/api/customers"), ("POST", "/api/cases"),
                 ("GET", "/api/packages"), ("GET", "/api/demo/scenarios")]:
        s, b, _ = H(app, m, p)
        assert (s, b["error"]) == (401, "UNAUTHENTICATED"), p
    s, b, _ = H(app, "GET", "/api/auth/session")
    assert s == 200 and b == {"auth_enabled": True, "authenticated": False, "user": None}
    # A forged / unknown cookie is refused.
    assert H(app, "GET", "/api/app", cookie="rf_session=forged")[0] == 401
    # Static assets stay public (they hold no case data).
    assert H(app, "GET", "/")[0] == 200


def test_invalid_credentials(tmp_path):
    app = App(ctx_for(tmp_path), make_auth())
    for u, p in [("alice", "wrong"), ("nobody", PW), ("", ""), ("alice", ""), (None, PW), ("alice", 123)]:
        s, b, extra = H(app, "POST", "/api/auth/login", {"username": u, "password": p})
        assert (s, b["error"]) == (401, "INVALID_CREDENTIALS") and "Set-Cookie" not in extra
        assert b["message"] == "Incorrect username or password."   # same text for unknown user and bad password
    assert H(app, "POST", "/api/auth/login", {"username": "alice", "password": PW}, client=False)[0] == 403
    s, ctype, data, _ = app.handle_ex("POST", "/api/auth/login", POST_H, b"not json")
    assert s == 400


def test_login_session_persists_and_logout_invalidates(tmp_path):
    app = App(ctx_for(tmp_path), make_auth())
    s, b, extra, cookie = login(app)
    assert s == 200 and b["user"] == {"username": "alice"}
    sc = extra["Set-Cookie"]
    assert sc.startswith("rf_session=") and "HttpOnly" in sc and "SameSite=Strict" in sc and "Path=/" in sc
    assert "Secure" not in sc and PW not in json.dumps(b) + sc
    # "Refresh": the same cookie keeps working for the session check and the protected API.
    for _ in range(3):
        s, b, _ = H(app, "GET", "/api/auth/session", cookie=cookie)
        assert b == {"auth_enabled": True, "authenticated": True, "user": {"username": "alice"}}
        s, b, _ = H(app, "GET", "/api/app", cookie=cookie)
        assert s == 200 and "reviewer" in b
    # Logout clears the cookie and kills the session server-side: replaying the old cookie fails.
    s, b, extra = H(app, "POST", "/api/auth/logout", cookie=cookie)
    assert s == 200 and "Max-Age=0" in extra["Set-Cookie"]
    assert H(app, "GET", "/api/app", cookie=cookie)[0] == 401
    assert H(app, "GET", "/api/auth/session", cookie=cookie)[1]["authenticated"] is False


def test_new_token_per_login_and_old_one_revoked(tmp_path):
    app = App(ctx_for(tmp_path), make_auth())
    c1 = login(app)[3]
    s, b, extra = H(app, "POST", "/api/auth/login", {"username": "alice", "password": PW}, cookie=c1)
    c2 = extra["Set-Cookie"].split(";")[0]
    assert c1 != c2
    assert H(app, "GET", "/api/app", cookie=c1)[0] == 401 and H(app, "GET", "/api/app", cookie=c2)[0] == 200


def test_idle_and_absolute_expiry():
    now = [1000.0]
    a = auth.Authenticator({"alice": auth.hash_password(PW, 1000)}, idle_seconds=60, max_seconds=300,
                           clock=lambda: now[0])
    t = a.login("alice", PW)
    now[0] += 59
    assert a.session(t) is not None             # activity refreshes the idle timer
    now[0] += 59
    assert a.session(t) is not None
    now[0] += 61
    assert a.session(t) is None                 # idle timeout
    t = a.login("alice", PW)
    for _ in range(7):
        now[0] += 50
        a.session(t)
    assert a.session(t) is None                 # absolute lifetime (300 s) despite activity


def test_failed_attempts_are_throttled(tmp_path):
    now = [0.0]
    a = auth.Authenticator({"alice": auth.hash_password(PW, 1000)}, clock=lambda: now[0])
    app = App(ctx_for(tmp_path), a)
    for _ in range(auth.FAIL_LIMIT):
        assert login(app, password="nope")[0] == 401
    s, b, _, _ = login(app)
    assert (s, b["error"]) == (429, "TOO_MANY_ATTEMPTS")
    now[0] += auth.LOCK_SECONDS + 1
    assert login(app)[0] == 200


def test_no_auth_mode_keeps_previous_behaviour(tmp_path):
    app = App(ctx_for(tmp_path))  # auth=None: unit tests / --insecure-no-auth
    assert H(app, "GET", "/api/app")[0] == 200
    assert H(app, "GET", "/api/auth/session")[1] == {"auth_enabled": False, "authenticated": True, "user": None}
    assert app.handle("GET", "/api/app", {}, b"")[0] == 200   # the 3-tuple handle() API is unchanged


# ---------------------------------------------------------------- real HTTP server + startup

def test_real_http_cookie_roundtrip(tmp_path):
    httpd = serve(ctx_for(tmp_path), 0, make_auth())
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def req(method, path, body=None, cookie=None):
        h = dict(POST_H, **{"Content-Type": "application/json"}) if method == "POST" else {}
        if cookie:
            h["Cookie"] = cookie
        r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers=h, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.headers, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, e.headers, json.loads(e.read())
    try:
        assert req("GET", "/api/cases")[0] == 401
        s, hdrs, b = req("POST", "/api/auth/login", {"username": "alice", "password": "bad"})
        assert s == 401 and hdrs.get("Set-Cookie") is None
        s, hdrs, b = req("POST", "/api/auth/login", {"username": "alice", "password": PW})
        assert s == 200 and "HttpOnly" in hdrs["Set-Cookie"]
        cookie = hdrs["Set-Cookie"].split(";")[0]
        assert req("GET", "/api/cases", cookie=cookie)[0] == 200
        assert req("POST", "/api/auth/logout", {}, cookie=cookie)[0] == 200
        assert req("GET", "/api/cases", cookie=cookie)[0] == 401
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_refuses_to_start_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(auth.ENV_FILE, raising=False)
    monkeypatch.setattr("sys.argv", ["server", "--root", str(tmp_path / "ws")])
    with pytest.raises(SystemExit) as e:
        server_mod.main()
    assert e.value.code == 2 and "no credentials configured" in capsys.readouterr().err
    monkeypatch.setattr("sys.argv", ["server", "--root", str(tmp_path / "ws"), "--auth-file", str(tmp_path / "x.json")])
    with pytest.raises(SystemExit):
        server_mod.main()
    assert "credentials file not found" in capsys.readouterr().err
