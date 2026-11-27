"""Minimal client for the Ringfence analyst API (same calls the React app makes, services/httpService.js)."""
import base64
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


class ApiError(RuntimeError):
    def __init__(self, status, payload):
        super().__init__(f"HTTP {status}: {payload}")
        self.status, self.payload = status, payload


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _req(self, method, path, body=None, raw=False, timeout=300):
        data = None
        headers = {"Accept": "application/json"}
        if method == "POST":
            data = json.dumps(body or {}).encode()
            headers.update({"Content-Type": "application/json", "X-Smartparser-Client": "webapp"})
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(r, timeout=timeout) as resp:
                b = resp.read()
                if raw:
                    return b
                ct = resp.headers.get("Content-Type", "")
                return json.loads(b) if "json" in ct else b.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                p = json.loads(b)
            except ValueError:
                p = b.decode("utf-8", "replace")[:500]
            raise ApiError(e.code, p) from None

    def get(self, path, **kw):
        return self._req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self._req("POST", path, body, **kw)

    def login(self, user, pw):
        return self.post("/api/auth/login", {"username": user, "password": pw})

    @staticmethod
    def b64(p):
        return base64.b64encode(Path(p).read_bytes()).decode()

    def wait(self, fn, pred, what, timeout=600, every=1.5):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if pred(last):
                return last
            time.sleep(every)
        raise TimeoutError(f"{what}: timed out; last={json.dumps(last)[:800] if last else None}")
