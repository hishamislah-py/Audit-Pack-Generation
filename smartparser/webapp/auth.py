"""Username/password authentication for the Ringfence web application (Python standard library only).

* Credentials live in a local JSON file outside the source tree (``--auth-file`` or ``SMARTPARSER_AUTH_FILE``).
  Passwords are stored only as salted PBKDF2-HMAC-SHA256 hashes; nothing is hard-coded and no password is logged.
* Sessions are server-side: a random 256-bit token in an ``HttpOnly; SameSite=Strict`` cookie maps to an in-memory
  record. Logout deletes the record, so the cookie is useless afterwards. No JWT, OAuth or external provider.
* Sessions expire after an idle timeout and an absolute lifetime; a server restart ends all sessions.

Create or change a user (prompts for the password; never pass it on the command line):

    py -3.11 -m smartparser.webapp.auth set-password --file %USERPROFILE%\\.ringfence\\auth.json --username alice

Non-interactive (test harnesses): ``--password-env NAME`` reads the password from that environment variable.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

ENV_FILE = "SMARTPARSER_AUTH_FILE"
COOKIE = "rf_session"
SCHEME = "pbkdf2_sha256"
ITERATIONS = 600_000
MAX_FIELD = 256                      # longest accepted username / password (bounds hashing cost)
FAIL_LIMIT, FAIL_WINDOW, LOCK_SECONDS = 5, 300.0, 60.0


class AuthConfigError(Exception):
    pass


# ---------------------------------------------------------------- password hashing

def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"{SCHEME}${iterations}${b64(salt)}${b64(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, it, salt, dk = encoded.split("$")
        if scheme != SCHEME:
            return False
        want = base64.b64decode(dk)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(it))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


# ---------------------------------------------------------------- credential file

def load_users(path: Path) -> dict[str, str]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AuthConfigError(f"credentials file not found: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthConfigError(f"credentials file unreadable: {path} ({type(exc).__name__})")
    users = {}
    for u in (doc.get("users") if isinstance(doc, dict) else None) or []:
        name, h = (u or {}).get("username"), (u or {}).get("password_hash")
        if not (isinstance(name, str) and name and isinstance(h, str) and h.startswith(SCHEME + "$")):
            raise AuthConfigError(f"credentials file {path}: every user needs 'username' and a "
                                  f"'{SCHEME}$...' password_hash (use: python -m smartparser.webapp.auth set-password)")
        users[name] = h
    if not users:
        raise AuthConfigError(f"credentials file {path} defines no users")
    return users


def set_password(path: Path, username: str, password: str) -> None:
    path = Path(path)
    doc = {"users": []}
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
    users = [u for u in doc.get("users", []) if u.get("username") != username]
    users.append({"username": username, "password_hash": hash_password(password)})
    doc["users"] = users
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- sessions

@dataclass
class Session:
    username: str
    created: float
    last_seen: float


class Authenticator:
    """Credential check + in-memory session store. Thread-safe (the server is a ThreadingHTTPServer)."""

    def __init__(self, users: dict[str, str], idle_seconds: float = 30 * 60, max_seconds: float = 8 * 3600,
                 cookie_secure: bool = False, clock=time.time):
        self._users = dict(users)
        self.idle, self.max_age, self.secure, self._clock = idle_seconds, max_seconds, cookie_secure, clock
        self._sessions: dict[str, Session] = {}
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        # Unknown usernames are verified against a dummy hash so timing does not reveal which usernames exist.
        try:
            iters = int(next(iter(self._users.values())).split("$")[1])
        except (StopIteration, IndexError, ValueError):
            iters = ITERATIONS
        self._dummy = hash_password(secrets.token_urlsafe(16), iters)

    @classmethod
    def from_file(cls, path: Path, **kw) -> "Authenticator":
        return cls(load_users(path), **kw)

    # -- login / logout
    def locked_out(self, username: str) -> bool:
        now = self._clock()
        with self._lock:
            fails = [t for t in self._fails.get(username, []) if now - t < FAIL_WINDOW]
            self._fails[username] = fails
            return len(fails) >= FAIL_LIMIT and now - fails[-1] < LOCK_SECONDS

    def login(self, username, password) -> str | None:
        """Return a new session token, or None for invalid credentials."""
        if not (isinstance(username, str) and isinstance(password, str)) or not username or not password \
                or len(username) > MAX_FIELD or len(password) > MAX_FIELD:
            return None
        encoded = self._users.get(username)
        ok = verify_password(password, encoded if encoded else self._dummy) and encoded is not None
        now = self._clock()
        with self._lock:
            if not ok:
                self._fails.setdefault(username, []).append(now)
                return None
            self._fails.pop(username, None)
            self._purge(now)
            token = secrets.token_urlsafe(32)
            self._sessions[token] = Session(username, now, now)
            return token

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def session(self, token: str | None) -> Session | None:
        """Validate a token and refresh its idle timer. Expired sessions are removed."""
        if not token:
            return None
        now = self._clock()
        with self._lock:
            s = self._sessions.get(token)
            if s is None:
                return None
            if now - s.last_seen > self.idle or now - s.created > self.max_age:
                del self._sessions[token]
                return None
            s.last_seen = now
            return s

    def _purge(self, now):
        for t in [t for t, s in self._sessions.items() if now - s.last_seen > self.idle or now - s.created > self.max_age]:
            del self._sessions[t]

    # -- cookies
    @staticmethod
    def token_from(headers) -> str | None:
        raw = headers.get("Cookie") if headers is not None else None
        if not raw:
            return None
        try:
            c = SimpleCookie()
            c.load(raw)
        except CookieError:
            return None
        m = c.get(COOKIE)
        return m.value if m and m.value else None

    def set_cookie(self, token: str) -> str:
        return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if self.secure else "")

    def clear_cookie(self) -> str:
        return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if self.secure else "")


def resolve_auth_file(cli_value: str | None) -> Path | None:
    v = cli_value or os.environ.get(ENV_FILE)
    return Path(v).expanduser() if v else None


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m smartparser.webapp.auth", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("set-password", help="create a user or change their password")
    sp.add_argument("--file", default=None, help=f"credentials JSON (default: ${ENV_FILE})")
    sp.add_argument("--username", required=True)
    sp.add_argument("--password-env", default=None, help="read the password from this environment variable")
    a = ap.parse_args(argv)
    path = resolve_auth_file(a.file)
    if path is None:
        ap.error(f"--file or ${ENV_FILE} is required")
    if a.password_env:
        pw = os.environ.get(a.password_env) or ""
    else:
        pw = getpass.getpass(f"New password for {a.username}: ")
        if pw != getpass.getpass("Repeat password: "):
            print("Passwords do not match; nothing changed.", file=sys.stderr)
            return 2
    if len(pw) < 8 or len(pw) > MAX_FIELD:
        print(f"The password must be 8 to {MAX_FIELD} characters; nothing changed.", file=sys.stderr)
        return 2
    set_password(path, a.username, pw)
    print(f"Password set for {a.username} in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
