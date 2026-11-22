"""Phase 3B-11 - minimal POC mapping-review server (Python standard library only; no new dependency).

    py -3.11 -m smartparser.review_ui.server --root <workspace> --authority <authority policy json>
                                              [--reviewer-id ID --reviewer-role ROLE --reviewer-kind TEST|BUSINESS]

<workspace> holds the stores of one Smart Parser workspace: rules/ (RuleStore), evidence/ (EvidenceStore),
audit.jsonl (AuditLog) and pk/ (PackageStore). The server binds to 127.0.0.1 only, is single-threaded (single-user
POC) and has NO authentication: the reviewer identity is fixed at start-up and every action still goes through the
AuthorityPolicy given with --authority (the shipped production policy authorises nobody, so with it every action is
refused with 403). No LLM is used by a review (the gateway is built disabled).

JSON API (all bodies JSON):
    GET  /api/reviews                                   review queue (versions in REVIEW_REQUIRED)
    GET  /api/review/<package_id>/<file_version_id>     review detail (header info, mapping table, summary, outcome)
    POST /api/review/<pid>/<vid>/decision               {action, source_index, reason, canonical_field?, others_reason?}
    POST /api/review/<pid>/<vid>/reject                 {reason}
    POST /api/review/<pid>/<vid>/complete               {basis}
    GET  /api/review/<pid>/<vid>/outcome                outcome only
    GET  /api/review/<pid>/<vid>/preview                the canonical preview CSV (only when generated)
    GET  /api/identity                                  the configured reviewer + authority policy id (display)
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote

from ..ai.config import AIConfig
from ..ai.gateway import DisabledLiveProvider, ProposalGateway
from ..intake.store import EvidenceStore
from ..mapping.rule_store import RuleStore
from ..orchestration.orchestrator import MappingOrchestrator
from ..orchestration.policy import PocAutoAcceptPolicy
from ..packages import review_api as api
from ..packages.service import PackageService
from ..packages.store import PackageStore
from ..review.audit import AuditLog
from ..review.authority import AuthorityPolicy, Reviewer
from ..schemas import SchemaRegistry

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def build_service(root: str | Path, authority_path: str | Path | None) -> PackageService:
    root = Path(root)
    reg = SchemaRegistry.from_directory()
    log = AuditLog(root / "audit.jsonl")
    gw = ProposalGateway(proposer=DisabledLiveProvider(), config=AIConfig(), log=log)     # reviews never call an LLM
    orch = MappingOrchestrator(reg, RuleStore(root / "rules", reg), EvidenceStore(root / "evidence"), gw,
                               PocAutoAcceptPolicy.load(), log)
    authority = AuthorityPolicy.load(authority_path) if authority_path else AuthorityPolicy.load()
    return PackageService(PackageStore(root / "pk"), orch, authority)


class App:
    def __init__(self, svc: PackageService, reviewer: Reviewer):
        self.svc, self.reviewer = svc, reviewer

    def handle(self, method: str, path: str, body: dict) -> tuple[int, str, bytes]:
        parts = [unquote(p) for p in path.split("?", 1)[0].strip("/").split("/") if p]
        try:
            if method == "GET" and not parts:
                return self._static("index.html")
            if method == "GET" and len(parts) == 1 and parts[0] in ("app.js", "style.css"):
                return self._static(parts[0])
            if parts[:1] != ["api"]:
                raise api.ApiError(404, "NOT_FOUND", path)
            if method == "GET" and parts == ["api", "identity"]:
                return self._json({"reviewer_id": self.reviewer.reviewer_id, "role": self.reviewer.role,
                                   "kind": self.reviewer.kind, "authority_policy": self.svc.authority.policy_id,
                                   "authority_status": self.svc.authority.status,
                                   "note": "POC: no authentication; identity fixed at server start"})
            if method == "GET" and parts == ["api", "reviews"]:
                return self._json(api.list_reviews(self.svc))
            if len(parts) >= 4 and parts[1] == "review":
                pid, vid, rest = parts[2], parts[3], parts[4:]
                if method == "GET" and not rest:
                    return self._json(api.review_detail(self.svc, pid, vid))
                if method == "GET" and rest == ["outcome"]:
                    return self._json(api.outcome(self.svc, pid, vid))
                if method == "GET" and rest == ["preview"]:
                    o = api.outcome(self.svc, pid, vid)
                    if not o["preview_generated"]:
                        raise api.ApiError(404, "NO_PREVIEW", "no canonical preview has been generated")
                    return 200, "text/csv; charset=utf-8", (self.svc.store.root / o["handoff"]["preview_csv"]).read_bytes()
                if method == "POST" and rest == ["decision"]:
                    return self._json(api.decide(self.svc, self.reviewer, pid, vid, body.get("action", ""),
                                                 body.get("source_index", -1), body.get("reason", ""),
                                                 body.get("canonical_field"), body.get("others_reason")))
                if method == "POST" and rest == ["reject"]:
                    return self._json(api.reject(self.svc, self.reviewer, pid, vid, body.get("reason", "")))
                if method == "POST" and rest == ["complete"]:
                    return self._json(api.complete(self.svc, self.reviewer, pid, vid, body.get("basis", "")))
            raise api.ApiError(404, "NOT_FOUND", path)
        except api.ApiError as e:
            return self._json({"error": e.code, "message": e.message}, e.status)
        except Exception as exc:                            # never leak internals beyond a translated message
            e = api.translate(exc)
            return self._json({"error": e.code, "message": e.message}, e.status)

    @staticmethod
    def _json(doc, status=200):
        return status, "application/json; charset=utf-8", json.dumps(doc, ensure_ascii=False, default=str).encode()

    @staticmethod
    def _static(name):
        p = STATIC / name
        return 200, TYPES[p.suffix], p.read_bytes()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, method):
            body = {}
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except json.JSONDecodeError:
                    body = {}
            status, ctype, data = app.handle(method, self.path, body)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send("GET")

        def do_POST(self):
            self._send("POST")

        def log_message(self, *a):
            pass
    return Handler


def serve(root, authority, reviewer: Reviewer, port: int = 8765) -> HTTPServer:
    app = App(build_service(root, authority), reviewer)
    return HTTPServer(("127.0.0.1", port), make_handler(app))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--authority", default=None, help="authority policy JSON (default: the shipped production policy)")
    ap.add_argument("--reviewer-id", default="poc-analyst")
    ap.add_argument("--reviewer-role", default="analyst")
    ap.add_argument("--reviewer-kind", default="TEST", choices=["TEST", "BUSINESS"])
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    httpd = serve(a.root, a.authority, Reviewer(reviewer_id=a.reviewer_id, role=a.reviewer_role, kind=a.reviewer_kind),
                  a.port)
    print(f"Smart Parser mapping review (POC) on http://127.0.0.1:{a.port}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
