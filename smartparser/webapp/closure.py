"""Ringfence closure: audit pack -> automatic AI investigations -> analyst ACCEPT / REJECT -> closing review (selections,
readiness, preview with the closing summary, HOLD / GENERATE) -> final audit pack (published, verified, frozen).

A port of the old UC-042 application's orchestration (uc042app/services: investigations, auto_investigations,
investigation_reviews, reviews, final_packs, ai_authorization, registry) onto FILES, scoped by the folder
(case_ref, recon_run_id) instead of a submission. All library work (uc042lib.pack / investigation / final_pack) runs in the
isolated subprocess of smartparser.reconciliation.closure_runner; nothing here re-implements a library rule.

Owner decisions (CONTRACT.md, 20 Nov 2026):
  * D-A: a COMPLETED case and its activated snapshot stay immutable; closure is a separate record per
    (case_ref, recon_run_id), allowed while the case is COMPLETED, frozen once its final pack is GENERATED and verified.
  * D-B / O4: no free text anywhere. Where the library needs a reason or comment, FIXED wording below is supplied.
  * D-C: the authenticated user is the actor of every closure action and the "Authorised by" of the final pack; the
    server's fixed reviewer ID is recorded as `system_reviewer_id`.
  * AI investigations start automatically after a reconciliation completes (any reconciliation job: one pipeline for
    manual uploads and demo ZIPs; no scenario-specific code), for every exception, when the server's AI is configured,
    under an AUTO_INVESTIGATION authorisation recorded first (authorized_by = the user who started reconciliation).
  * A pack the library refuses (e.g. its validation rule V6) is UNAVAILABLE with the library's exact reason; closure is
    blocked and no PDF is produced. A case without exceptions gets a NOT_REQUIRED closing summary: no AI request.

Storage: <ws>/closure/<case_ref>/<recon_run_id>/ (see CONTRACT.md). Writes are atomic (temp file + replace); JSONL files
are append-only; audit events are appended AFTER the state write. Concurrency: one lock per closure (never ctx.lock), one
AI lane (BoundedSemaphore(1)) for every AI request, work in background threads registered as ordinary jobs (ctx._new_job).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import traceback
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..packages.store import _retry_sharing
from ..reconciliation.closure_runner import ClosureRunner, ClosureRunnerError
from . import identity, results

CLOSURE_JOB_KINDS = ("audit_pack", "investigation", "closing_preview", "final_pack")
ACTIVE = ("queued", "running")
SYSTEM_ACTOR = "ringfence-closure-service"
FIXED = {
    "REJECT": "Rejected by the analyst in Ringfence (fixed wording; no free-text reason is captured by design, "
              "owner decision O4)",
    "HOLD": "Held by the analyst in Ringfence (fixed wording, O4)",
    "EXCLUDED_BY_ANALYST": "Excluded by the analyst in Ringfence (fixed wording, O4)",
}
INCLUSIONS = ("INCLUDED", "NOT_INVESTIGATED", "EXCLUDED_BY_ANALYST")
EXPLANATION_MAX = 2000


def _explanation(value) -> str:
    """The analyst's optional explanation on an AI-finding decision: trimmed text, at most EXPLANATION_MAX characters, no
    control characters other than line breaks and tabs, and only characters the audit PDF fonts can print (Latin, Greek,
    Cyrillic, general punctuation and currency signs) - so a decision can never make the final pack unprintable."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ClosureError(400, "INVALID", "explanation must be text")
    text = value.strip()
    if len(text) > EXPLANATION_MAX:
        raise ClosureError(400, "INVALID", f"explanation is longer than {EXPLANATION_MAX} characters")
    for ch in text:
        cat, o = unicodedata.category(ch), ord(ch)
        printable = ch in "\n\t" or (not cat.startswith("C") and (o < 0x0530 or 0x2000 <= o <= 0x20CF))
        if not printable:
            raise ClosureError(400, "INVALID", f"explanation contains a character the audit PDF cannot print: U+{o:04X}")
    return text
REF_RE = re.compile(r"^RF-\d{4}-\d{2}-\d{3}$")
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
FINAL_FILES = {"pdf": ("report.pdf", "application/pdf"), "html": ("report.html", "text/html; charset=utf-8"),
               "json": ("final_pack.json", "application/json; charset=utf-8"),
               "manifest": ("manifest.json", "application/json; charset=utf-8"),
               "provenance.pdf": (None, "application/pdf"), "provenance.json": (None, "application/json; charset=utf-8"),
               # 23 Nov 2026: the analyst edition (renderer 4.0-analyst), written beside the provenance record; not part of
               # the final pack or its manifest. The technical report (pdf) stays the default.
               "analyst.pdf": (None, "application/pdf")}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _new_id(prefix: str) -> str:
    # short: the IDs name folders (reviews/RS-.../previews/PV-...) and Windows paths are limited to 260 characters
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class ClosureError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


# Windows: replacing a file that another thread has open (reading it) fails with a sharing violation (PermissionError,
# WinError 5). Retrying alone can starve a writer when several readers poll the same file. So every closure JSON / JSONL
# file is read and written under ONE in-process lock per path (readers and writers of the same file serialise; the lock
# is only ever held for the file operation itself, never while taking another lock). _retry_sharing stays as the
# second line of defence for access from outside this process.
_PATH_LOCKS: dict = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(p: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(str(p)))
    with _PATH_LOCKS_GUARD:
        lk = _PATH_LOCKS.get(key)
        if lk is None:
            lk = _PATH_LOCKS[key] = threading.Lock()
        return lk


def _write_json(p: Path, doc) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp-{uuid.uuid4().hex[:6]}")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    with _path_lock(p):
        _retry_sharing(lambda: tmp.replace(p))


def _read_text(p: Path) -> str:
    with _path_lock(p):
        return _retry_sharing(lambda: p.read_text(encoding="utf-8"))


def _read_json(p: Path, default=None):
    """`default` only when the file does not exist (or is not JSON). A sharing violation is retried and, when it
    persists, RAISED: it is never mistaken for a missing record."""
    try:
        return json.loads(_read_text(p))
    except (FileNotFoundError, NotADirectoryError, ValueError):
        return default


def ai_closing_summary() -> bool:
    """23 Nov 2026 owner decision: no AI closing summary (each exception carries its AI investigation and the analyst's
    decision and note). RINGFENCE_AI_CLOSING_SUMMARY=on restores it; the UC-042 engine must then also enable it
    (uc042lib.final_pack.summary.AI_CLOSING_SUMMARY_ENABLED), otherwise the engine records NOT_REQUIRED anyway."""
    return os.environ.get("RINGFENCE_AI_CLOSING_SUMMARY", "off").strip().lower() in ("on", "1", "true", "yes")


def ai_parallel() -> int:
    """How many AI operations may run at once: RINGFENCE_AI_PARALLEL (1..8), default 3."""
    try:
        return max(1, min(8, int(os.environ.get("RINGFENCE_AI_PARALLEL", "3"))))
    except ValueError:
        return 3


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"

    def write():
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
    with _path_lock(p):
        _retry_sharing(write)


def _jsonl(p: Path) -> list[dict]:
    out = []
    try:
        text = _read_text(p)
    except FileNotFoundError:
        return out
    if text:
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                break
    return out


def job_view(j: dict) -> dict:
    """api.job_view for the closure job kinds."""
    return {k: j.get(k) for k in ("job_id", "kind", "state", "created_at", "started_at", "finished_at", "error",
                                  "case_ref", "recon_run_id", "exception_id", "review_id", "result")}


# ======================================================================================= mapping provenance (contract I-3)
MAPPING_PROVENANCE_SCHEMA = "ringfence-mapping-provenance/1.0"
MAPPING_DISPOSITIONS = ("MAPPED", "IGNORED", "UNRESOLVED")
MAPPING_METHODS = ("DETERMINISTIC_EXACT", "DETERMINISTIC_POLICY", "AI_PROPOSED", "ANALYST_DEFINED", "ANALYST_IGNORED", "RULE")
MAPPING_VALIDATION = ("PASS", "FAIL", "NOT_RECORDED")
_MAPPING_FILE_KEYS = ("evidence_category", "file_version_id", "version_number", "original_filename", "source_sha256",
                      "intake_id", "version_status", "review_kind", "columns")
_MAPPING_COLUMN_KEYS = ("source_position", "source_header", "canonical_field", "disposition", "method", "rule_id",
                        "rule_version", "proposal_id", "proposal_class", "decided_by", "decided_at", "confirmed_by",
                        "confirmed_at", "validation", "audit_event_seqs")


def _mapping_unavailable(reason: str) -> dict:
    return {"schema": MAPPING_PROVENANCE_SCHEMA, "status": "UNAVAILABLE", "reason": reason, "files": [], "notes": []}


def mapping_provenance_problems(doc, package_id: str, snapshot_id: str) -> list[str]:
    """Contract I-3 checks on what the mapping provenance service returned (rendered only when this is empty)."""
    if not isinstance(doc, dict):
        return ["not an object"]
    out = []
    if doc.get("schema") != MAPPING_PROVENANCE_SCHEMA:
        out.append(f"schema {doc.get('schema')!r} is not {MAPPING_PROVENANCE_SCHEMA}")
    if doc.get("package_id") != package_id or doc.get("snapshot_id") != snapshot_id:
        out.append(f"it describes {doc.get('package_id')}/{doc.get('snapshot_id')}, not {package_id}/{snapshot_id}")
    if not isinstance(doc.get("files"), list) or not isinstance(doc.get("notes", []), list):
        return out + ["files / notes must be lists"]
    for i, f in enumerate(doc["files"]):
        if not isinstance(f, dict) or any(k not in f for k in _MAPPING_FILE_KEYS) or not isinstance(f.get("columns"), list):
            out.append(f"files[{i}] lacks a contract field")
            continue
        for j, col in enumerate(f["columns"]):
            if not isinstance(col, dict) or any(k not in col for k in _MAPPING_COLUMN_KEYS):
                out.append(f"files[{i}].columns[{j}] lacks a contract field")
            elif col["disposition"] not in MAPPING_DISPOSITIONS or col["method"] not in MAPPING_METHODS \
                    or col["validation"] not in MAPPING_VALIDATION:
                out.append(f"files[{i}].columns[{j}] has a value outside the contract enumerations")
    return out


def mapping_provenance_sentence(mp: dict) -> str:
    """Fixed-format sentence for the GENERATE comment (system text, not analyst free text)."""
    if mp.get("status") != "AVAILABLE":
        return (f"Column mapping provenance: UNAVAILABLE ({mp.get('reason')}); the supplement records this "
                "(ringfence_provenance.json, mapping_provenance).")
    cols = [col for f in mp["files"] for col in f["columns"]]
    by = Counter(col["disposition"] for col in cols)
    methods = Counter(col["method"] for col in cols)
    return (f"Column mapping provenance: {len(mp['files'])} file(s), {len(cols)} column(s) ("
            + ", ".join(f"{by[d]} {d}" for d in MAPPING_DISPOSITIONS) + "; methods: "
            + (", ".join(f"{n} {m}" for m, n in sorted(methods.items())) or "none") + "); per-column source, rule or "
            "proposal, decision and confirmation in the Ringfence provenance supplement (ringfence_provenance.json, "
            "mapping_provenance).")


class ClosureService:
    def __init__(self, ctx, runner: ClosureRunner):
        self.ctx = ctx
        self.runner = runner
        self.root = ctx.root / "closure"
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict = {}
        self._auto_done: dict = {}                             # (ref, run) -> final automatic-investigation status
        self._guard = threading.Lock()
        # Up to ai_parallel() AI request streams at once (investigations + summary). 23 Nov 2026 demo feedback: one at a
        # time made a six-exception case wait for six investigations back to back. Each stream is its own subprocess with
        # its own request files; the engine writes investigations atomically; case files are written under _lock.
        self.ai_lane = threading.BoundedSemaphore(ai_parallel())
        ctx.job_listeners.append(self._on_job_finished)
        self.recover()

    # ============================================================================================ paths / persistence
    def _dir(self, ref: str, run: str) -> Path:
        if not REF_RE.match(ref or "") or not results.RUN_ID.match(run or ""):
            raise ClosureError(404, "NOT_FOUND", f"unknown closure {ref}/{run}")
        return self.root / ref / run

    def _lock(self, ref: str, run: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault((ref, run), threading.RLock())

    def _load(self, ref: str, run: str) -> dict:
        c = _read_json(self._dir(ref, run) / "closure.json")
        if c is None:
            raise ClosureError(404, "NO_CLOSURE", f"no closure record for {ref} / {run}")
        return c

    def _save(self, c: dict) -> dict:
        c["revision"] = int(c.get("revision", 0)) + 1
        c["updated_at"] = now()
        _write_json(self._dir(c["case_ref"], c["recon_run_id"]) / "closure.json", c)
        return c

    def _bump(self, ref: str, run: str, **changes) -> dict:
        with self._lock(ref, run):
            c = self._load(ref, run)
            c.update(changes)
            return self._save(c)

    def _run_dir(self, run: str) -> Path:
        return results.run_dir(self.ctx.runs, run)

    def _paths(self, c: dict) -> dict:
        d = self._dir(c["case_ref"], c["recon_run_id"])
        return {"dir": d, "packs": d / "packs", "investigations": d / "investigations", "final_packs": d / "final_packs",
                "provenance": d / "provenance", "reviews": d / "reviews", "scratch": d / "scratch",
                "datasets_root": self.ctx.runs / c["recon_run_id"], "case_dir": self.ctx.runs / c["recon_run_id"] / "case"}

    # ============================================================================================ audit / identity
    def _actor(self, user: str | None) -> str:
        return user or self._system_reviewer_id()

    def _audit(self, event_type: str, c: dict, actor: str | None, system: bool = False, **details) -> None:
        """Appended only AFTER the corresponding state write succeeded."""
        d = {"case_ref": c["case_ref"], "recon_run_id": c["recon_run_id"], "snapshot_id": c.get("snapshot_id"),
             "package_id": c.get("package_id"), "pack_id": (c.get("pack") or {}).get("pack_id"),
             "system_reviewer_id": self._system_reviewer_id()}
        d.update({k: v for k, v in details.items() if v is not None})
        if system or not actor:                      # automatic closure work: the system, with the human in details
            actor_id, role = SYSTEM_ACTOR, identity.SYSTEM_ROLE
        else:
            actor_id, role = actor, self._role_of(actor)
        self.ctx.log.append(event_type, actor_id=actor_id, actor_role=role, details=d)

    def _system_reviewer_id(self) -> str:
        """The server's fixed reviewer identity (--reviewer-id). After I-1 `ctx.reviewer` is the signed-in user inside a
        request; the SYSTEM reviewer is always `ctx.server_reviewer` (older contexts without it: ctx.reviewer)."""
        return getattr(self.ctx, "server_reviewer", self.ctx.reviewer).reviewer_id

    @staticmethod
    def _role_of(actor: str) -> str:
        """The access role of `actor` when it is the acting identity (supervisor shows as supervisor), else analyst."""
        user, role = identity.current_actor()
        return role if user == actor and role and role != identity.SYSTEM_ROLE else identity.ANALYST

    # ============================================================================================ jobs
    def _job(self, kind: str, c: dict, **extra) -> dict:
        # package_id=None: closure jobs never count as a case's Smart Parser operation (cases._running / package jobs)
        return self.ctx._new_job(kind, None, case_ref=c["case_ref"], recon_run_id=c["recon_run_id"],
                                 closure_package_id=c.get("package_id"), result=None, **extra)

    def _job_start(self, j: dict) -> None:
        j["state"], j["started_at"] = "running", now()
        self.ctx._save_job(j)

    def _job_end(self, j: dict, state: str, result=None, error: str | None = None) -> None:
        j["state"], j["result"], j["error"] = state, result, (error or None) and str(error)[:800]
        j["finished_at"], j["audit_seq_end"] = now(), self.ctx.last_seq()
        self.ctx._save_job(j)

    def _jobs(self, c: dict, kind: str | None = None, exception_id: str | None = None) -> list[dict]:
        out = [j for j in list(self.ctx.jobs.values()) if j.get("kind") in CLOSURE_JOB_KINDS
               and j.get("case_ref") == c["case_ref"] and j.get("recon_run_id") == c["recon_run_id"]
               and (kind is None or j["kind"] == kind) and (exception_id is None or j.get("exception_id") == exception_id)]
        return sorted(out, key=lambda j: (j.get("created_at") or "", j["job_id"]))

    def _thread(self, fn, *args) -> None:
        threading.Thread(target=identity.bind(self._safe), args=(fn, *args), daemon=True).start()

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:                               # a background failure is kept on its job, never raised
            traceback.print_exc()
            j = args[0] if args and isinstance(args[0], dict) and args[0].get("job_id") else None
            if j is not None:
                self._fail_unexpected(j, f"unexpected error: {type(e).__name__}: {str(e)[:500]}")

    def _fail_unexpected(self, j: dict, err: str) -> None:
        """A job whose code raised unexpectedly ends FAILED (never stuck 'running'), and the closure state it owned is
        released: a pending audit pack becomes UNAVAILABLE, a generating review GENERATION_FAILED. Best effort."""
        try:
            if j.get("state") in ACTIVE:
                self._job_end(j, "failed", None, err)
            ref, run = j.get("case_ref"), j.get("recon_run_id")
            if not ref or not run:
                return
            with self._lock(ref, run):
                c = self._load(ref, run)
                changed = False
                if j.get("kind") == "audit_pack" and (c.get("pack") or {}).get("status") == "PENDING":
                    c["pack"].update(status="UNAVAILABLE", reason=err)
                    changed = True
                if c.get("auto_investigation") == "STARTING" and j.get("kind") == "audit_pack":
                    c["auto_investigation"] = "FAILED"
                    changed = True
                s = self._session(c)
                if j.get("kind") == "final_pack" and s and s["status"] == "GENERATING":
                    s["status"] = "GENERATION_FAILED"
                    self._save_session(c, s)
                    c["last_generation_failure"] = {"at": now(), "error": err[:1500], "job_id": j["job_id"],
                                                    "final_pack_id": None}
                    changed = True
                if changed:
                    self._save(c)
        except Exception:
            traceback.print_exc()

    # ============================================================================================ creation / auto start
    def _on_job_finished(self, j: dict) -> None:
        """ctx.job_listeners hook: ANY completed reconciliation job starts closure (in a new thread; never blocks)."""
        if j.get("kind") == "reconciliation" and j.get("state") == "completed" and j.get("run_id"):
            self._thread(self._auto_start, j)

    def _auto_start(self, j: dict) -> None:
        own = self.ctx.cases.owner_of(j.get("package_id"))
        if own is None:
            return                                           # a package without a Ringfence case: no closure
        c, _ = own
        self.ensure(c["case_ref"], j["run_id"], requested_by=j.get("requested_by"), trigger="RECONCILIATION_COMPLETED")

    def ensure(self, ref: str, run: str, requested_by: str | None = None, trigger: str = "RECONCILIATION_COMPLETED") -> dict:
        """Create the closure record of (case, reconciliation run) once and start its audit-pack job."""
        with self._lock(ref, run):
            d = self._dir(ref, run)
            existing = _read_json(d / "closure.json")
            if existing is not None:
                return existing
            rec = results.load_record(self._run_dir(run))
            case = self.ctx.cases.load(ref)
            c = {"case_ref": ref, "recon_run_id": run, "snapshot_id": rec["input"]["snapshot_id"],
                 "package_id": rec["input"]["package_id"], "period": rec["engine"]["period"],
                 "engine_case_status": rec["result"]["case_status"],
                 "zip": {k: (case.get("zip") or {}).get(k) for k in ("filename", "sha256")},
                 "created_at": now(), "trigger": trigger, "reconciliation_requested_by": requested_by,
                 "pack": {"status": "PENDING", "pack_id": None, "reason": None, "findings": [], "job_id": None},
                 "review_id": None, "final_pack": None, "frozen": False, "revision": 0}
            for k in ("packs", "investigations", "final_packs", "provenance", "reviews", "scratch"):
                (d / k).mkdir(parents=True, exist_ok=True)
            j = self._job("audit_pack", c, requested_by=requested_by)
            c["pack"]["job_id"] = j["job_id"]
            self._save(c)
        self._thread(self._run_pack, j)
        return c

    def _run_pack(self, j: dict) -> None:
        ref, run = j["case_ref"], j["recon_run_id"]
        c = self._load(ref, run)
        P = self._paths(c)
        self._job_start(j)
        state, err = "completed", None
        try:
            rec = self.runner.generate_pack(P["case_dir"], P["packs"], c["period"], P["scratch"])
            if rec.get("status") == "GENERATED":
                pack = {"status": "GENERATED", "pack_id": rec["pack_id"], "reason": None, "findings": [],
                        "outcome": rec.get("outcome"), "pack_content_sha256": rec.get("pack_content_sha256")}
            else:
                findings = [str(f) for f in rec.get("validation_findings") or []]
                pack = {"status": "UNAVAILABLE", "pack_id": None, "findings": findings,
                        "reason": "; ".join(findings) or f"the audit pack was not published ({rec.get('outcome')})",
                        "outcome": rec.get("outcome")}
        except ClosureRunnerError as e:
            pack = {"status": "UNAVAILABLE", "pack_id": None, "findings": [], "reason": str(e)}
            state, err = "failed", str(e)
        plan, excs, cfg = None, [], {}
        with self._lock(ref, run):
            c = self._load(ref, run)
            c["pack"] = dict(pack, job_id=j["job_id"])
            if pack["status"] == "GENERATED":
                # One atomic save decides what happens next, so the view never shows a transient state (QA E-15: a
                # clean case showed INVESTIGATING and bumped the revision twice). STARTING (shown as INVESTIGATING) only
                # when investigations will actually be queued.
                plan, excs, cfg = self._auto_plan(c, j.get("requested_by"))
                c["auto_investigation"] = plan
            self._save(c)
        actor = j.get("requested_by")
        if pack["status"] == "GENERATED":
            self._audit("AUDIT_PACK_GENERATED", c, None, system=True, requested_by=actor, job_id=j["job_id"],
                        outcome=pack.get("outcome"), auto_investigation=c.get("auto_investigation"))
        else:
            self._audit("AUDIT_PACK_UNAVAILABLE", c, None, system=True, requested_by=actor, job_id=j["job_id"],
                        reason=pack["reason"][:1000])
        self._job_end(j, state, {"status": pack["status"], "pack_id": pack["pack_id"], "reason": pack["reason"]}, err)
        if plan == "REFUSED":
            self._refuse_auto_investigation(c, actor, excs, cfg)
        elif plan == "STARTING":
            self._auto_investigations(ref, run, actor)

    @staticmethod
    def _auto_details(j: dict) -> dict:
        """An automatic investigation's outcome is system work; the human who started reconciliation stays recorded."""
        return {"system": True, "requested_by": j.get("requested_by")} if j.get("automatic") else {}

    def _auto_plan(self, c: dict, requested_by: str | None) -> tuple[str, list, dict]:
        """NOT_REQUIRED (no exception in the published pack: no AI at all), REFUSED (AI unavailable or no recorded
        requester) or STARTING (investigations will be queued)."""
        try:
            excs = [x["exception_id"] for x in self._pack(c)["exception_register"]["exceptions"]]
        except ClosureError:
            return "STARTING", [], {}                       # unreadable here: the queueing step decides and records it
        if not excs:
            return "NOT_REQUIRED", [], {}
        cfg = self.runner.ai_configuration()
        if not cfg["available"] or not requested_by:
            return "REFUSED", excs, cfg
        return "STARTING", excs, cfg

    def _refuse_auto_investigation(self, c: dict, requested_by: str | None, excs: list, cfg: dict) -> None:
        reason = cfg.get("problem") or "the user who started the reconciliation is not recorded"
        auth = self._record_authorization(c, "AUTO_INVESTIGATION", "REFUSED", requested_by, cfg, reason=reason,
                                          exceptions=excs)
        self._audit("AI_AUTHORIZATION_REFUSED", c, None, system=True, authorized_by=requested_by,
                    authorization_id=auth["authorization_id"], kind="AUTO_INVESTIGATION", reason=reason)

    def _auto_investigations(self, ref: str, run: str, requested_by: str | None) -> None:
        status = "FAILED"
        try:
            status = self._auto_investigations_inner(ref, run, requested_by)
        finally:
            for i in range(3):
                try:
                    self._bump(ref, run, auto_investigation=status)
                    break
                except Exception:
                    if i == 2:
                        # The record could not be written: remember the outcome in memory so the view never shows
                        # STARTING (INVESTIGATING) for a step that has ended; recover() turns a persisted STARTING
                        # into INTERRUPTED at the next start.
                        self._auto_done[(ref, run)] = status
                        traceback.print_exc()

    def _auto_investigations_inner(self, ref: str, run: str, requested_by: str | None) -> str:
        c = self._load(ref, run)
        excs = [x["exception_id"] for x in self._pack(c)["exception_register"]["exceptions"]]
        if not excs:
            return "NOT_REQUIRED"                            # a clean case: no AI at all
        cfg = self.runner.ai_configuration()
        if not cfg["available"] or not requested_by:
            self._refuse_auto_investigation(c, requested_by, excs, cfg)
            return "REFUSED"
        auth = self._record_authorization(c, "AUTO_INVESTIGATION", "AUTHORIZED", requested_by, cfg, exceptions=excs)
        self._audit("AI_AUTHORIZED", c, None, system=True, authorized_by=requested_by,
                    authorization_id=auth["authorization_id"], kind="AUTO_INVESTIGATION", provider=cfg["provider"],
                    model=cfg["model"], exceptions=excs)
        for e in excs:
            self._queue_investigation(ref, run, e, auth["authorization_id"], requested_by, None, auto=True)
        return "QUEUED"

    def _record_authorization(self, c: dict, kind: str, status: str, user: str | None, cfg: dict, **extra) -> dict:
        rec = {"authorization_id": _new_id("AIA"), "kind": kind, "status": status, "authorized_by": user,
               "recorded_at": now(), "provider": cfg.get("provider"), "model": cfg.get("model"),
               "reasoning_effort": cfg.get("reasoning_effort"), "store": False, "data_notice": cfg.get("data_notice"),
               "system_reviewer_id": self._system_reviewer_id(), **extra}
        with self._lock(c["case_ref"], c["recon_run_id"]):
            _append(self._dir(c["case_ref"], c["recon_run_id"]) / "ai_authorizations.jsonl", rec)
            self._save(self._load(c["case_ref"], c["recon_run_id"]))
        return rec

    # ============================================================================================ investigations
    def _queue_investigation(self, ref: str, run: str, exc: str, authorization_id: str, user: str | None,
                             retry_of: str | None, auto: bool = False) -> dict:
        with self._lock(ref, run):
            c = self._load(ref, run)
            attempt = len(self._jobs(c, "investigation", exc)) + 1
            j = self._job("investigation", c, exception_id=exc, authorization_id=authorization_id, retry_of=retry_of,
                          attempt=attempt, requested_by=user, automatic=auto)
            self._save(c)
        self._audit("AI_INVESTIGATION_QUEUED", c, None if auto else user, system=auto,
                    **({"requested_by": user} if auto else {}), exception_id=exc, job_id=j["job_id"],
                    authorization_id=authorization_id, retry_of=retry_of, attempt=attempt)
        self._thread(self._run_investigation, j)
        return j

    def _registry(self, c: dict) -> dict:
        """The registry of published investigations. Missing = empty (nothing published yet). Any other problem (a
        persistent sharing violation, unreadable or invalid JSON) RAISES: the registry is read and written back, so an
        empty default would wipe every published investigation."""
        p = self._dir(c["case_ref"], c["recon_run_id"]) / "registry.json"
        try:
            text = _read_text(p)
        except FileNotFoundError:
            return {"investigations": {}, "attempts": []}
        doc = json.loads(text)                                  # ValueError propagates
        if not isinstance(doc, dict) or not isinstance(doc.get("investigations"), dict) \
                or not isinstance(doc.get("attempts"), list):
            raise ValueError(f"{p.name} is not a valid investigation registry")
        return doc

    def _run_investigation(self, j: dict) -> None:
        ref, run, exc = j["case_ref"], j["recon_run_id"], j["exception_id"]
        with self.ai_lane:
            c = self._load(ref, run)
            if c.get("frozen"):
                self._job_end(j, "failed", None, "closure is frozen (final pack generated); nothing was run")
                return
            P = self._paths(c)
            self._job_start(j)
            out, err = None, None
            try:
                out = self.runner.investigate(
                    pack_id=c["pack"]["pack_id"], exception_id=exc, packs_root=P["packs"],
                    datasets_root=P["datasets_root"], investigations_root=P["investigations"], scratch=P["scratch"],
                    execution={"case_ref": ref, "recon_run_id": run, "authorization_id": j.get("authorization_id"),
                               "job_id": j["job_id"]})
                calls = out.pop("ai_requests", [])
            except ClosureRunnerError as e:
                err, calls = str(e), e.ai_requests
        model = (out or {}).get("model") or {}
        self._record_usage(c, calls, "investigation", j["job_id"], exc, model.get("prompt_version"))
        outcome = (out or {}).get("persist_outcome")
        published = outcome in ("PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL") and out.get("investigation_id")
        if out is not None and not published and outcome != "NOT_PUBLISHED":     # e.g. PERSIST_FAILED: technical
            err = f"the investigation result could not be stored ({outcome}): {out.get('persist_error') or ''}"
            out = None
        attempt = {"job_id": j["job_id"], "exception_id": exc, "attempt": j.get("attempt"), "retry_of": j.get("retry_of"),
                   "authorization_id": j.get("authorization_id"), "at": now(),
                   "outcome": "PUBLISHED" if published else ("NOT_PUBLISHED" if out else "FAILED"),
                   "investigation_id": out.get("investigation_id") if published else None,
                   "not_published_record": (out or {}).get("not_published_record"),
                   "investigation_status": (out or {}).get("investigation_status"),
                   "validation_status": (out or {}).get("validation_status"),
                   "reason": err or (out or {}).get("failure_reason") or "; ".join((out or {}).get("validation_findings") or []),
                   "requests": len(calls)}
        with self._lock(ref, run):
            c = self._load(ref, run)
            reg = self._registry(c)
            reg["attempts"].append(attempt)
            if published:
                reasons = out.get("eligibility_reasons") or []
                reg["investigations"][out["investigation_id"]] = {
                    "investigation_id": out["investigation_id"], "exception_id": exc, "pack_id": c["pack"]["pack_id"],
                    "findings_sha256": out["findings_sha256"], "eligible": not reasons, "eligibility_reasons": reasons,
                    "job_id": j["job_id"], "authorization_id": j.get("authorization_id"), "registered_at": now(),
                    "investigation_mode": out.get("investigation_mode"), "provider": model.get("provider"),
                    "model": model.get("model"), "prompt_version": model.get("prompt_version"),
                    "workflow_version": model.get("workflow_version"), "simulated": model.get("simulated")}
            _write_json(self._dir(ref, run) / "registry.json", reg)
            self._save(c)
        common = dict(exception_id=exc, job_id=j["job_id"], authorization_id=j.get("authorization_id"))
        if published:
            self._audit("AI_INVESTIGATION_PUBLISHED", c, j.get("requested_by"), **self._auto_details(j), investigation_id=out["investigation_id"],
                        eligible=not (out.get("eligibility_reasons") or []), requests=len(calls), **common)
            self._job_end(j, "completed", {"outcome": "PUBLISHED", "investigation_id": out["investigation_id"]})
        elif out is not None:
            self._audit("AI_INVESTIGATION_NOT_PUBLISHED", c, j.get("requested_by"), **self._auto_details(j), reason=attempt["reason"][:800],
                        record=attempt["not_published_record"], requests=len(calls), **common)
            self._job_end(j, "completed", {"outcome": "NOT_PUBLISHED", "reason": attempt["reason"][:800]})
        else:
            self._audit("AI_INVESTIGATION_FAILED", c, j.get("requested_by"), **self._auto_details(j), reason=err[:800], requests=len(calls),
                        **common)
            self._job_end(j, "failed", {"outcome": "FAILED"}, err)

    def _record_usage(self, c: dict, calls: list, operation: str, job_id: str, exc: str | None,
                      prompt_version: str | None) -> None:
        if not calls:
            return
        p = self._dir(c["case_ref"], c["recon_run_id"]) / "usage.jsonl"
        for r in calls:
            u = r.get("usage") or {}
            model = r.get("model")
            _append(p, {"at": now(), "operation": operation, "job_id": job_id, "exception_id": exc, "provider": "openai",
                        "model": model, "resolved_model": r.get("resolved_model"), "prompt_version": prompt_version,
                        "request_id": r.get("request_id"), "response_id": r.get("response_id"),
                        "status": r.get("status"), "error_kind": r.get("error_kind"),
                        "input_tokens": u.get("input_tokens"), "cached_input_tokens": u.get("cached_input_tokens"),
                        "output_tokens": u.get("output_tokens"), "reasoning_tokens": u.get("reasoning_tokens"),
                        "total_tokens": u.get("total_tokens"), "latency_seconds": r.get("latency_seconds"),
                        "cost": self.runner.cost(model, u)})

    def _usage(self, c: dict) -> dict:
        rows = _jsonl(self._dir(c["case_ref"], c["recon_run_id"]) / "usage.jsonl")
        tot = lambda k: sum(int(r.get(k) or 0) for r in rows)  # noqa: E731
        costs = [r.get("cost") for r in rows]
        priced = bool(rows) and all(x is not None for x in costs)
        return {"calls": len(rows), "input_tokens": tot("input_tokens"), "cached_input_tokens": tot("cached_input_tokens"),
                "output_tokens": tot("output_tokens"), "reasoning_tokens": tot("reasoning_tokens"),
                "cost": round(sum(costs), 6) if priced else None,
                "cost_note": None if priced else ("no AI request made" if not rows else
                                                  "cost unavailable (no price configured)"),
                "by_operation": dict(Counter(r["operation"] for r in rows)),
                "requests": [{k: r.get(k) for k in ("at", "operation", "exception_id", "model", "resolved_model",
                                                    "prompt_version", "request_id", "response_id", "input_tokens",
                                                    "cached_input_tokens", "output_tokens", "reasoning_tokens", "cost")}
                             for r in rows]}

    # ============================================================================================ reads (pack / trace)
    def _pack(self, c: dict) -> dict:
        if (c.get("pack") or {}).get("status") != "GENERATED":
            raise ClosureError(409, "PACK_UNAVAILABLE", f"audit pack unavailable: {(c.get('pack') or {}).get('reason')}")
        d = self._paths(c)["packs"] / c["pack"]["pack_id"]
        doc = _read_json(d / "pack.json")
        if doc is None:
            raise ClosureError(409, "PACK_UNAVAILABLE", "the published pack.json cannot be read")
        return doc

    def _trace(self, c: dict) -> dict:
        """engine canonical file name -> the customer's evidence (original filename, file version ID, SHA-256)."""
        rec = results.load_record(self._run_dir(c["recon_run_id"]))
        staged = {s["file_version_id"]: s for s in rec["input"]["staged"]}
        out = {}
        for name, t in (rec.get("traceability") or {}).get("by_engine_file", {}).items():
            s = staged.get(t.get("file_version_id"), {})
            out[name] = {"evidence_category": t.get("evidence_category"), "file_version_id": t.get("file_version_id"),
                         "source_sha256": t.get("source_sha256"), "original_filename": s.get("original_filename"),
                         "intake_id": t.get("intake_id"), "canonical_name": name}
        return out

    def _ref_for(self, trace: dict, source_file: str | None, line=None, reference: str | None = None) -> dict:
        name = (source_file or "").split("/")[-1]
        t = trace.get(name, {})
        return {"reference": reference or (f"{source_file}#L{line}" if line else source_file),
                "original_filename": t.get("original_filename"), "file_version_id": t.get("file_version_id"),
                "source_sha256": t.get("source_sha256"), "line": line, "canonical_name": name or None}

    def _exceptions(self, c: dict) -> list[dict]:
        if (c.get("pack") or {}).get("status") == "GENERATED":
            return list(self._pack(c)["exception_register"]["exceptions"])
        return results.exceptions(self._run_dir(c["recon_run_id"]))

    def _missing_items(self, c: dict) -> list[dict]:
        if (c.get("pack") or {}).get("status") != "GENERATED":
            return []
        return list(self._pack(c)["missing_evidence_register"]["items"])

    # ============================================================================================ analyst decisions
    def _reviews(self, c: dict) -> list[dict]:
        return _jsonl(self._dir(c["case_ref"], c["recon_run_id"]) / "investigation_reviews.jsonl")

    def _active_reviews(self, c: dict) -> dict:
        out = {}
        for r in self._reviews(c):
            out[r["investigation_id"]] = r
        return out

    @staticmethod
    def library_review(r: dict) -> dict:
        return {k: r[k] for k in ("analyst_review_id", "investigation_id", "exception_id", "decision", "findings_sha256",
                                  "findings_schema_version", "comment", "rejection_reason", "reviewer", "decided_at",
                                  "revision")}

    def _inv_dir(self, c: dict, exc: str, inv: str) -> Path:
        if not ID_RE.match(exc or "") or not ID_RE.match(inv or ""):
            raise ClosureError(404, "NOT_FOUND", f"unknown investigation {inv}")
        return self._paths(c)["investigations"] / c["pack"]["pack_id"] / exc / inv

    def _verify_inv(self, c: dict, entry: dict) -> list[str]:
        """Registry + artefact hashes (fast, read-only). The library's own check_eligibility ran at publication."""
        d = self._inv_dir(c, entry["exception_id"], entry["investigation_id"])
        problems = []
        f = d / "findings.json"
        if not f.is_file() or _sha(f.read_bytes()) != entry["findings_sha256"]:
            return ["findings.json does not match the registered SHA-256"]
        for runrec in sorted((d / "runs").glob("[0-9][0-9][0-9][0-9].json")):
            for name, digest in ((_read_json(runrec, {}) or {}).get("artefact_sha256") or {}).items():
                p = d / name
                if not p.is_file() or _sha(p.read_bytes()) != digest:
                    problems.append(f"{name} does not match its run record SHA-256")
        return problems + [f"library eligibility at publication: {r}" for r in entry.get("eligibility_reasons") or []]

    def decide_investigation(self, ref: str, inv: str, decision: str, expected_revision, user: str | None,
                             explanation=None) -> dict:
        """ACCEPT / REJECT an AI finding. `explanation` (optional, 23 Nov 2026 owner requirement, supersedes O4 for this
        decision only): the analyst's own words - stored verbatim as the REJECT reason (else the fixed wording) or as the
        ACCEPT comment. A decision never changes the engine's reconciliation result or relationship statuses."""
        if decision not in ("ACCEPT", "REJECT"):
            raise ClosureError(400, "INVALID", "decision must be ACCEPT or REJECT")
        explanation = _explanation(explanation)
        c0, run = self._locate(ref)
        actor = self._actor(user)
        with self._lock(ref, run):
            c = self._load(ref, run)
            self._check_revision(c, expected_revision)
            self._check_open(c)
            entry = self._registry(c)["investigations"].get(inv)
            if entry is None:
                raise ClosureError(404, "NOT_FOUND", f"{inv} is not a published investigation of this closure")
            problems = self._verify_inv(c, entry)
            if problems:
                raise ClosureError(409, "INVESTIGATION_NOT_ELIGIBLE", f"{inv} cannot be decided: " + "; ".join(problems))
            findings = _read_json(self._inv_dir(c, entry["exception_id"], inv) / "findings.json", {})
            prev = self._active_reviews(c).get(inv)
            rec = {"analyst_review_id": _new_id("AR"), "investigation_id": inv, "exception_id": entry["exception_id"],
                   "decision": decision, "findings_sha256": entry["findings_sha256"],
                   "findings_schema_version": (findings.get("model_metadata") or {}).get("findings_schema_version", ""),
                   "comment": explanation if decision == "ACCEPT" else "",
                   "rejection_reason": (explanation or FIXED["REJECT"]) if decision == "REJECT" else "",
                   "explanation_supplied": bool(explanation),
                   "reviewer": {"user_id": actor, "display_name": actor}, "decided_at": now(),
                   "revision": (prev["revision"] + 1) if prev else 1, "decided_by": actor,
                   "system_reviewer_id": self._system_reviewer_id(), "supersedes": prev["analyst_review_id"] if prev else None}
            _append(self._dir(ref, run) / "investigation_reviews.jsonl", rec)
            c = self._save(c)
        self._audit("ANALYST_INVESTIGATION_ACCEPTED" if decision == "ACCEPT" else "ANALYST_INVESTIGATION_REJECTED", c,
                    actor, exception_id=entry["exception_id"], investigation_id=inv,
                    analyst_review_id=rec["analyst_review_id"], decision=decision, revision=rec["revision"],
                    rejection_reason=rec["rejection_reason"] or None, comment=rec["comment"] or None)
        return {"analyst_review": rec, "closure": self.view(ref)}

    def start_investigation(self, ref: str, exc: str, expected_revision, user: str | None) -> dict:
        c0, run = self._locate(ref)
        actor = self._actor(user)
        with self._lock(ref, run):
            c = self._load(ref, run)
            self._check_revision(c, expected_revision)
            self._check_open(c)
            pack = self._pack(c)
            if exc not in {x["exception_id"] for x in pack["exception_register"]["exceptions"]}:
                raise ClosureError(404, "NOT_FOUND", f"{exc} is not an exception of this audit pack")
            jobs = self._jobs(c, "investigation", exc)
            if any(j["state"] in ACTIVE for j in jobs):
                raise ClosureError(409, "INVESTIGATION_ACTIVE", f"an investigation of {exc} is already queued or running")
            cfg = self.runner.ai_configuration()
            if not cfg["available"]:
                auth = self._record_authorization(c, "INVESTIGATION", "REFUSED", actor, cfg, reason=cfg["problem"],
                                                  exception_id=exc)
                self._audit("AI_AUTHORIZATION_REFUSED", c, actor, authorization_id=auth["authorization_id"],
                            kind="INVESTIGATION", exception_id=exc, reason=cfg["problem"])
                raise ClosureError(409, "AI_UNAVAILABLE", cfg["problem"])
            auth = self._record_authorization(c, "INVESTIGATION", "AUTHORIZED", actor, cfg, exception_id=exc)
        self._audit("AI_AUTHORIZED", c, actor, authorization_id=auth["authorization_id"], kind="INVESTIGATION",
                    exception_id=exc, provider=cfg["provider"], model=cfg["model"])
        j = self._queue_investigation(ref, run, exc, auth["authorization_id"], actor, jobs[-1]["job_id"] if jobs else None)
        return {"job_id": j["job_id"], "closure": self.view(ref)}

    # ============================================================================================ locate / guards
    def _locate(self, ref: str) -> tuple[dict, str]:
        """The closure of the case's completed reconciliation run (created on first sight if the listener never ran)."""
        if not REF_RE.match(ref or ""):
            raise ClosureError(404, "NOT_FOUND", f"unknown case {ref!r}")
        case = self.ctx.cases.load(ref)
        if not case.get("completed"):
            case = self.ctx.cases.detail(ref)
        comp = case.get("completed") or {}
        run = comp.get("reconciliation_run_id")
        if case.get("status") != "COMPLETED" or not run:
            raise ClosureError(404, "NO_CLOSURE", f"{ref} has no completed reconciliation yet")
        p = self._dir(ref, run) / "closure.json"
        if not p.is_file():
            j = next((x for x in self.ctx.jobs.values() if x.get("kind") == "reconciliation" and x.get("run_id") == run),
                     {})
            self.ensure(ref, run, requested_by=j.get("requested_by"), trigger="FIRST_VIEW")
        return self._load(ref, run), run

    def _check_revision(self, c: dict, expected) -> None:
        if expected is None:
            raise ClosureError(400, "REVISION_REQUIRED", "expected_revision (the closure revision) is required",
                               current_revision=c["revision"])
        try:
            exp = int(expected)
        except (TypeError, ValueError):
            raise ClosureError(400, "INVALID", "expected_revision must be an integer") from None
        if exp != int(c["revision"]):
            raise ClosureError(409, "CLOSURE_CHANGED", f"The closure changed (revision {c['revision']}, request based on "
                               f"{exp}). Reload to see the latest state.", current_revision=c["revision"])

    def _check_open(self, c: dict) -> None:
        if c.get("frozen"):
            raise ClosureError(409, "CLOSURE_FROZEN", f"closure is frozen: final pack "
                               f"{(c.get('final_pack') or {}).get('final_pack_id')} was generated and verified")
        s = self._session(c)
        if s and s["status"] == "GENERATING":
            raise ClosureError(409, "GENERATION_IN_PROGRESS", "a final pack is being generated")
        if (c.get("pack") or {}).get("status") != "GENERATED":
            raise ClosureError(409, "PACK_UNAVAILABLE", "closure is blocked: audit pack unavailable: "
                               f"{(c.get('pack') or {}).get('reason') or 'still being generated'}")

    # ============================================================================================ review session
    def _session_dir(self, c: dict, review_id: str) -> Path:
        return self._paths(c)["reviews"] / review_id

    def _session(self, c: dict) -> dict | None:
        if not c.get("review_id"):
            return None
        return _read_json(self._session_dir(c, c["review_id"]) / "session.json")

    def _save_session(self, c: dict, s: dict) -> None:
        s["updated_at"] = now()
        _write_json(self._session_dir(c, s["review_id"]) / "session.json", s)

    def _open_session(self, c: dict, actor: str) -> tuple[dict, bool]:
        s = self._session(c)
        if s is not None:
            return s, False
        s = {"review_id": _new_id("RS"), "status": "OPEN", "selections": [], "current_preview_id": None,
             "opened_by": actor, "opened_at": now()}
        self._save_session(c, s)
        c["review_id"] = s["review_id"]
        return s, True

    def open_review(self, ref: str, expected_revision, user: str | None) -> dict:
        _, run = self._locate(ref)
        actor = self._actor(user)
        with self._lock(ref, run):
            c = self._load(ref, run)
            self._check_revision(c, expected_revision)
            self._check_open(c)
            s, created = self._open_session(c, actor)
            if created:
                c = self._save(c)
        if created:
            self._audit("CLOSING_REVIEW_OPENED", c, actor, review_id=s["review_id"])
        return self.review_view(ref)

    def _published_for(self, c: dict, reg: dict, exc: str) -> list[dict]:
        return sorted([e for e in reg["investigations"].values() if e["exception_id"] == exc],
                      key=lambda e: e["registered_at"], reverse=True)

    def _effective_selections(self, c: dict, s: dict | None, reg: dict, excs: list[str]) -> list[dict]:
        explicit = {x["exception_id"]: x for x in (s or {}).get("selections", [])}
        out = []
        for e in excs:
            if e in explicit:
                out.append(dict(explicit[e], explicit=True))
                continue
            pub = [x for x in self._published_for(c, reg, e) if x["eligible"]]
            out.append({"exception_id": e, "inclusion": "INCLUDED", "investigation_id": pub[0]["investigation_id"],
                        "reason": "", "explicit": False} if pub else
                       {"exception_id": e, "inclusion": "NOT_INVESTIGATED", "investigation_id": None, "reason": "",
                        "explicit": False})
        return out

    def set_selections(self, ref: str, selections, expected_revision, user: str | None) -> dict:
        if not isinstance(selections, list) or not selections:
            raise ClosureError(400, "INVALID", "selections must be a non-empty list")
        _, run = self._locate(ref)
        actor = self._actor(user)
        with self._lock(ref, run):
            c = self._load(ref, run)
            self._check_revision(c, expected_revision)
            self._check_open(c)
            excs = [x["exception_id"] for x in self._pack(c)["exception_register"]["exceptions"]]
            reg = self._registry(c)
            clean = []
            for x in selections:
                if not isinstance(x, dict):
                    raise ClosureError(400, "INVALID", "each selection must be an object")
                e, inc = x.get("exception_id"), x.get("inclusion")
                if e not in excs:
                    raise ClosureError(400, "SELECTION_INVALID", f"{e!r} is not an exception of this audit pack")
                if inc not in INCLUSIONS:
                    raise ClosureError(400, "SELECTION_INVALID", f"{e}: inclusion must be one of {', '.join(INCLUSIONS)}")
                inv = x.get("investigation_id") if inc == "INCLUDED" else None
                if inc == "INCLUDED":
                    entry = reg["investigations"].get(inv or "")
                    if entry is None or entry["exception_id"] != e:
                        raise ClosureError(400, "SELECTION_INVALID", f"{e}: {inv!r} is not a published investigation of "
                                           "this exception")
                    if not entry["eligible"]:
                        raise ClosureError(400, "SELECTION_INVALID", f"{e}: {inv} is not eligible: "
                                           + "; ".join(entry["eligibility_reasons"]))
                clean.append({"exception_id": e, "inclusion": inc, "investigation_id": inv,
                              "reason": FIXED["EXCLUDED_BY_ANALYST"] if inc == "EXCLUDED_BY_ANALYST" else ""})
            s, created = self._open_session(c, actor)
            merged = {x["exception_id"]: x for x in s["selections"]}
            merged.update({x["exception_id"]: x for x in clean})
            s["selections"] = [merged[e] for e in excs if e in merged]
            if s["status"] in ("ON_HOLD", "GENERATION_FAILED"):
                s["status"] = "OPEN"
            self._save_session(c, s)
            c = self._save(c)
        if created:
            self._audit("CLOSING_REVIEW_OPENED", c, actor, review_id=s["review_id"])
        self._audit("CLOSING_SELECTIONS_CHANGED", c, actor, review_id=s["review_id"],
                    selections=[{k: x[k] for k in ("exception_id", "inclusion", "investigation_id")} for x in clean])
        return self.review_view(ref)

    def _inputs(self, c: dict, s: dict | None) -> dict:
        """Everything a preview depends on, and its fingerprint (a changed input makes a preview stale)."""
        reg = self._registry(c)
        excs = [x["exception_id"] for x in self._exceptions(c)]
        sels = self._effective_selections(c, s, reg, excs)
        active = self._active_reviews(c)
        included = [x["investigation_id"] for x in sels if x["inclusion"] == "INCLUDED"]
        reviews = [self.library_review(active[i]) for i in included if i in active]
        lib_sels = [{k: x[k] for k in ("exception_id", "inclusion", "investigation_id", "reason")} for x in sels]
        fp = _sha(_canon({"pack_id": c["pack"].get("pack_id"), "selections": lib_sels, "reviews": reviews,
                          "findings": {i: (reg["investigations"].get(i) or {}).get("findings_sha256") for i in included},
                          "ai_available": self.runner.ai_configuration()["available"] if excs else None}).encode())
        return {"selections": sels, "library_selections": lib_sels, "reviews": reviews, "fingerprint": fp,
                "registry": reg, "active": active, "exceptions": excs}

    def _preview_meta(self, c: dict, s: dict | None, preview_id: str | None) -> dict | None:
        if not s or not preview_id:
            return None
        return _read_json(self._session_dir(c, s["review_id"]) / "previews" / preview_id / "meta.json")

    def readiness(self, c: dict, s: dict | None, inputs: dict | None = None) -> dict:
        blockers, warnings, checklist = [], [], []
        pack = c.get("pack") or {}
        if pack.get("status") == "PENDING":
            return {"blockers": ["The audit pack is still being generated."], "warnings": [], "checklist": [],
                    "ready": False}
        if pack.get("status") != "GENERATED":
            return {"blockers": [f"Audit pack unavailable: {pack.get('reason')}. Closure is blocked and no PDF is produced."],
                    "warnings": [], "checklist": [], "ready": False}
        inputs = inputs or self._inputs(c, s)
        reg, active = inputs["registry"], inputs["active"]
        for j in self._jobs(c, "investigation"):
            if j["state"] in ACTIVE:
                blockers.append(f"AI investigation in progress for {j['exception_id']}.")
        attempts = {}
        for a in reg["attempts"]:
            attempts[a["exception_id"]] = a
        for x in inputs["selections"]:
            e, row = x["exception_id"], {"exception_id": x["exception_id"], "inclusion": x["inclusion"],
                                         "investigation_id": x["investigation_id"], "decision": None}
            if x["inclusion"] == "INCLUDED":
                entry = reg["investigations"].get(x["investigation_id"]) or {}
                dec = active.get(x["investigation_id"])
                row["decision"] = dec["decision"] if dec else None
                if not entry.get("eligible"):
                    blockers.append(f"{e}: investigation {x['investigation_id']} is not eligible.")
                    row["disposition"] = "NOT_ELIGIBLE"
                elif dec is None:
                    blockers.append(f"AI review pending for {e}: accept or reject the AI finding.")
                    row["disposition"] = "AWAITING_DECISION"
                else:
                    row["disposition"] = "ACCEPTED" if dec["decision"] == "ACCEPT" else "REJECTED"
            elif x["inclusion"] == "EXCLUDED_BY_ANALYST":
                row["disposition"] = "EXCLUDED"
            else:
                last = attempts.get(e)
                running = any(j["state"] in ACTIVE for j in self._jobs(c, "investigation", e))
                if running:
                    row["disposition"] = "IN_PROGRESS"
                elif last and last["outcome"] != "PUBLISHED":
                    blockers.append(f"Investigation failed with no disposition for {e}: retry it or exclude it from the "
                                    "final pack.")
                    row["disposition"] = "FAILED_ACTION_NEEDED"
                else:
                    warnings.append(f"{e} will be reported as not investigated.")
                    row["disposition"] = "NOT_INVESTIGATED"
            row["done"] = row["disposition"] in ("ACCEPTED", "REJECTED", "EXCLUDED", "NOT_INVESTIGATED")
            row["exception_resolution"] = "UNRESOLVED"
            checklist.append(row)
        if s and s["status"] == "GENERATING":
            blockers.append("A final pack is being generated.")
        if any(j["state"] in ACTIVE for j in self._jobs(c, "closing_preview")):
            blockers.append("A preview is being generated.")
        meta = self._preview_meta(c, s, (s or {}).get("current_preview_id"))
        if meta is None:
            blockers.append("Preview required: generate the preview" + (" (with the AI closing summary)"
                                                                          if inputs["exceptions"] and ai_closing_summary() else "") +
                            " before deciding.")
        elif meta["inputs_fingerprint"] != inputs["fingerprint"]:
            blockers.append("Preview stale: the selections, investigations or analyst decisions changed after the "
                            "preview; generate a new preview.")
        elif meta["closing_summary"]["status"] == "UNAVAILABLE":
            warnings.append("The AI closing summary is unavailable: "
                            f"{meta['closing_summary'].get('unavailable_reason')}. GENERATE requires acknowledging this.")
        if inputs["exceptions"]:
            warnings.append(f"{len(inputs['exceptions'])} exception(s) remain UNRESOLVED in the final pack; an analyst "
                            "decision on an AI finding does not resolve an exception.")
        return {"blockers": blockers, "warnings": warnings, "checklist": checklist, "ready": not blockers}

    @staticmethod
    def _preview_blocker(b: str) -> bool:
        return b.startswith(("Preview required", "Preview stale"))

    def review_view(self, ref: str) -> dict:
        c, _ = self._locate(ref)
        return self._review_view(c)

    def _review_view(self, c: dict, inputs: dict | None = None) -> dict:
        s = self._session(c)
        if (c.get("pack") or {}).get("status") != "GENERATED":
            return {"review_id": None, "status": None, "revision": c["revision"], "readiness": self.readiness(c, s),
                    "selections": [], "current_preview": None, "decisions": []}
        inputs = inputs or self._inputs(c, s)
        meta = self._preview_meta(c, s, (s or {}).get("current_preview_id"))
        return {"review_id": (s or {}).get("review_id"), "status": (s or {}).get("status"), "revision": c["revision"],
                "readiness": self.readiness(c, s, inputs),
                "selections": [{k: x[k] for k in ("exception_id", "inclusion", "investigation_id", "reason", "explicit")}
                               for x in inputs["selections"]],
                "current_preview": None if meta is None else {
                    "preview_id": meta["preview_id"], "snapshot_sha256": meta["snapshot_sha256"],
                    "closing_summary_status": meta["closing_summary"]["status"],
                    "closing_summary_unavailable_reason": meta["closing_summary"].get("unavailable_reason") or None,
                    "reused": bool(meta.get("reused")), "created_at": meta["created_at"],
                    "stale": meta["inputs_fingerprint"] != inputs["fingerprint"]},
                "last_preview_failure": self._last_preview_failure(c, s),
                "decisions": _jsonl(self._session_dir(c, s["review_id"]) / "decisions.jsonl") if s else []}

    def _last_preview_failure(self, c: dict, s: dict | None) -> dict | None:
        """The most recent failed preview of this review (Fix8 D5): what failed and why, kept for the analyst and audit."""
        if not s:
            return None
        recs = [r for r in (_read_json(p) for p in (self._session_dir(c, s["review_id"]) / "preview_failures")
                            .glob("PVF-*.json")) if r]
        if not recs:
            return None
        r = max(recs, key=lambda x: x.get("at") or "")
        return {"failure_id": r["failure_id"], "at": r["at"], "job_id": r.get("job_id"), "error": (r.get("error") or "")[:800],
                "error_kind": r.get("error_kind"), "rejected_text_leaks": r.get("rejected_text_leaks") or []}

    # ============================================================================================ preview
    def request_preview(self, ref: str, confirm_ai: bool, expected_revision, user: str | None) -> dict:
        _, run = self._locate(ref)
        actor = self._actor(user)
        auth = None
        with self._lock(ref, run):
            c = self._load(ref, run)
            self._check_revision(c, expected_revision)
            self._check_open(c)
            s, created = self._session(c), False          # opened only once the request is accepted
            inputs = self._inputs(c, s)
            blockers = [b for b in self.readiness(c, s, inputs)["blockers"] if not self._preview_blocker(b)]
            if blockers:
                raise ClosureError(409, "BLOCKED", "the preview is blocked: " + " ".join(blockers), blockers=blockers)
            # fingerprint unchanged and a preview exists for it: reuse (no new AI request)
            prev_dir = self._session_dir(c, s["review_id"]) / "previews" if s else None
            # a summary that FAILED (provider / validation) is never reused: a new request may succeed
            cached = [] if prev_dir is None else sorted([m for m in (_read_json(p / "meta.json") for p in prev_dir.glob("PV-*")) if m
                             and m.get("inputs_fingerprint") == inputs["fingerprint"]
                             and not (m["closing_summary"]["status"] == "UNAVAILABLE" and m["closing_summary"].get("failure"))],
                            key=lambda m: m["created_at"])
            if cached:
                meta = cached[-1]
                meta["reused"] = True
                _write_json(prev_dir / meta["preview_id"] / "meta.json", meta)
                s["current_preview_id"], s["status"] = meta["preview_id"], "OPEN"
                self._save_session(c, s)
                c = self._save(c)
                reused = meta
            else:
                reused = None
                cfg = self.runner.ai_configuration()
                need_ai = bool(inputs["exceptions"]) and ai_closing_summary()   # 23 Nov 2026: off by owner decision
                if need_ai and cfg["available"] and confirm_ai is not True:
                    raise ClosureError(400, "AI_CONFIRMATION_REQUIRED", "the closing summary is generated by AI: "
                                       "confirm_ai must be true (" + cfg["data_notice"] + ")")
                if s is None:
                    s, created = self._open_session(c, actor)
                    c = self._save(c)
                if need_ai and cfg["available"]:
                    auth = self._record_authorization(c, "CLOSING_SUMMARY", "AUTHORIZED", actor, cfg,
                                                      review_id=s["review_id"])
                    mode, why = "AI", ""
                elif need_ai:
                    mode, why = "UNAVAILABLE", f"AI unavailable: {cfg['problem']}"
                else:
                    mode, why = "NOT_REQUIRED", ""
                s["status"] = "OPEN"
                self._save_session(c, s)
                c = self._load(ref, run)
                j = self._job("closing_preview", c, review_id=s["review_id"], requested_by=actor, summary_mode=mode,
                              unavailable_reason=why, inputs_fingerprint=inputs["fingerprint"],
                              authorization_id=auth["authorization_id"] if auth else None)
                c = self._save(c)
        if created:
            self._audit("CLOSING_REVIEW_OPENED", c, actor, review_id=s["review_id"])
        if reused is not None:
            self._audit("CLOSING_PREVIEW_READY", c, actor, review_id=s["review_id"], preview_id=reused["preview_id"],
                        reused=True, snapshot_sha256=reused["snapshot_sha256"])
            return {"job_id": None, "reused": True, "preview_id": reused["preview_id"], "closure": self.view(ref)}
        if auth:
            self._audit("AI_AUTHORIZED", c, actor, authorization_id=auth["authorization_id"], kind="CLOSING_SUMMARY",
                        review_id=s["review_id"], job_id=j["job_id"])
        self._audit("CLOSING_PREVIEW_REQUESTED", c, actor, review_id=s["review_id"], job_id=j["job_id"],
                    summary_mode=j["summary_mode"])
        self._thread(self._run_preview, j)
        return {"job_id": j["job_id"], "reused": False, "preview_id": None, "closure": self.view(ref)}

    def _run_preview(self, j: dict) -> None:
        ref, run = j["case_ref"], j["recon_run_id"]
        lane = self.ai_lane if j["summary_mode"] == "AI" else None
        if lane:
            lane.acquire()
        try:
            self._job_start(j)
            c = self._load(ref, run)
            s = self._session(c)
            P = self._paths(c)
            inputs = self._inputs(c, s)
            pv = _new_id("PV")
            out_dir = self._session_dir(c, s["review_id"]) / "previews" / pv
            calls, err, res, err_kind, diag = [], None, None, None, {}
            try:
                res = self.runner.preview(pack_id=c["pack"]["pack_id"], packs_root=P["packs"],
                                          investigations_root=P["investigations"],
                                          selections=inputs["library_selections"], analyst_reviews=inputs["reviews"],
                                          summary=j["summary_mode"], unavailable_reason=j["unavailable_reason"],
                                          out_dir=out_dir, scratch=P["scratch"])
                calls = res.pop("ai_requests", [])
            except ClosureRunnerError as e:
                err, calls, err_kind, diag = str(e), e.ai_requests, e.kind, e.diagnostics or {}
        finally:
            if lane:
                lane.release()
        self._record_usage(c, calls, "closing_summary", j["job_id"], None,
                           ((res or {}).get("closing_summary") or {}).get("prompt_version")
                           or (((diag.get("closing_summary") or {}).get("model_metadata")) or {}).get("prompt_version"))
        if res is None:
            failure = self._record_preview_failure(c, s, j, inputs, err, err_kind, diag)
            leaks = [{"investigation_id": k.get("investigation_id"), "text": (k.get("text") or "")[:240],
                      "rejected_source": k.get("rejected_source"), "found_at": (k.get("found_at") or [])[:5]}
                     for k in failure["rejected_text_leaks"][:5]]
            self._audit("CLOSING_PREVIEW_FAILED", c, j.get("requested_by"), review_id=s["review_id"], job_id=j["job_id"],
                        reason=err[:800], failure_id=failure["failure_id"], error_kind=err_kind,
                        **({"rejected_text_leaks": leaks} if leaks else {}))
            self._job_end(j, "failed", {"failure_id": failure["failure_id"]}, err)
            return
        meta = {"preview_id": pv, "review_id": s["review_id"], "created_at": now(), "created_by": j.get("requested_by"),
                "job_id": j["job_id"], "inputs_fingerprint": inputs["fingerprint"],
                "selections": inputs["library_selections"],
                "analyst_review_ids": [r["analyst_review_id"] for r in inputs["reviews"]], "reused": False,
                "authorization_id": j.get("authorization_id"), **res}
        _write_json(out_dir / "meta.json", meta)
        with self._lock(ref, run):
            c = self._load(ref, run)
            s = self._session(c)
            current = s["status"] == "OPEN" and self._inputs(c, s)["fingerprint"] == inputs["fingerprint"]
            if current:
                s["current_preview_id"] = pv
                self._save_session(c, s)
            c = self._save(c)
        self._audit("CLOSING_PREVIEW_READY", c, j.get("requested_by"), review_id=s["review_id"], preview_id=pv,
                    job_id=j["job_id"], snapshot_sha256=res["snapshot_sha256"],
                    closing_summary_status=res["closing_summary"]["status"], current=current)
        self._job_end(j, "completed", {"preview_id": pv, "snapshot_sha256": res["snapshot_sha256"],
                                       "closing_summary_status": res["closing_summary"]["status"], "current": current})

    def _record_preview_failure(self, c: dict, s: dict, j: dict, inputs: dict, err: str, kind, diag: dict) -> dict:
        """Write-once diagnostics of a failed preview (Fix8 D5): the error, the library's structured reasons (e.g. which
        rejected text was found where), the refused closing summary and the inputs. Never reused as a preview."""
        rec = {"failure_id": _new_id("PVF"), "at": now(), "job_id": j["job_id"], "review_id": s["review_id"],
               "requested_by": j.get("requested_by"), "summary_mode": j.get("summary_mode"),
               "authorization_id": j.get("authorization_id"), "inputs_fingerprint": inputs["fingerprint"],
               "selections": inputs["library_selections"],
               "analyst_review_ids": [r["analyst_review_id"] for r in inputs["reviews"]],
               "error": err, "error_kind": kind, "stage": diag.get("stage"),
               "validation_errors": diag.get("errors") or [],
               "rejected_text_leaks": diag.get("rejected_text_leaks") or [],
               "closing_summary": diag.get("closing_summary")}
        try:
            _write_json(self._session_dir(c, s["review_id"]) / "preview_failures" / f"{rec['failure_id']}.json", rec)
        except OSError:                                              # diagnostics never mask the failure itself
            traceback.print_exc()
        return rec

    def preview_file(self, ref: str, fmt: str) -> tuple:
        c, _ = self._locate(ref)
        s = self._session(c)
        meta = self._preview_meta(c, s, (s or {}).get("current_preview_id"))
        if meta is None:
            raise ClosureError(404, "NO_PREVIEW", "there is no current preview; request one")
        d = self._session_dir(c, s["review_id"]) / "previews" / meta["preview_id"]
        # 23 Nov 2026 (owner): the preview PDF shows the analyst edition (renderer 4.0-analyst); the full technical report
        # stays available as "technical.pdf". The analyst edition of a preview is drawn on first request (no AI) and kept.
        if fmt == "pdf":
            ap = d / "preview_analyst.pdf"
            if not ap.is_file():
                try:
                    pj = d / "preview_provenance.json"
                    if not pj.is_file():
                        _write_json(pj, {"schema": "ringfence-preview-provenance/1.0", "case_ref": c["case_ref"],
                                         "recon_run_id": c["recon_run_id"], "snapshot_id": c["snapshot_id"],
                                         "zip": c.get("zip"), "source_files": self._source_files(c),
                                         "mapping_provenance": self._mapping_provenance(c)})
                    self.runner.analyst_pdf(d / "preview.json", pj, self._paths(c)["packs"], ap, self._paths(c)["scratch"])
                except Exception:                            # the technical preview is still served; nothing is hidden
                    traceback.print_exc()
            if ap.is_file():
                return "application/pdf", ap.read_bytes(), {"X-Snapshot-SHA256": meta["snapshot_sha256"], "X-Report-Edition": "analyst",
                                                             "Content-Disposition": f'inline; filename="{meta["preview_id"]}-analyst.pdf"'}
        name, ctype = {"pdf": ("preview.pdf", "application/pdf"), "technical.pdf": ("preview.pdf", "application/pdf"),
                       "html": ("preview.html", "text/html; charset=utf-8"),
                       "json": ("preview.json", "application/json; charset=utf-8")}[fmt]
        data = (d / name).read_bytes()
        return ctype, data, {"X-Snapshot-SHA256": meta["snapshot_sha256"],
                             "Content-Disposition": f'inline; filename="{meta["preview_id"]}.{fmt}"'}

    # ============================================================================================ HOLD / GENERATE
    def decide_review(self, ref: str, body: dict, user: str | None) -> dict:
        decision = body.get("decision")
        if decision not in ("HOLD", "GENERATE"):
            raise ClosureError(400, "INVALID", "decision must be HOLD or GENERATE")
        _, run = self._locate(ref)
        actor = self._actor(user)
        with self._lock(ref, run):
            c = self._load(ref, run)
            self._check_revision(c, body.get("expected_revision"))
            self._check_open(c)
            s = self._session(c)
            if s is None:
                raise ClosureError(409, "NO_REVIEW", "open the closing review first")
            meta = self._preview_meta(c, s, s.get("current_preview_id"))
            sha = body.get("snapshot_sha256")
            if decision == "HOLD":
                if sha and (meta is None or sha != meta["snapshot_sha256"]):
                    raise ClosureError(409, "PREVIEW_STALE", "the preview has changed; reload it")
                rec = self._decision_record(c, s, "HOLD", actor, meta, body, FIXED["HOLD"])
                _append(self._session_dir(c, s["review_id"]) / "decisions.jsonl", rec)
                s["status"], s["current_preview_id"] = "ON_HOLD", None
                self._save_session(c, s)
                c = self._save(c)
                job = None
            else:
                if meta is None:
                    raise ClosureError(409, "PREVIEW_REQUIRED", "no current preview; generate and read a preview first")
                if sha != meta["snapshot_sha256"]:
                    raise ClosureError(409, "PREVIEW_STALE", "the decision does not match the current preview; reload it")
                if body.get("acknowledgement_accepted") is not True:
                    raise ClosureError(400, "ACKNOWLEDGEMENT_REQUIRED", "GENERATE requires accepting the acknowledgement")
                if meta["closing_summary"]["status"] == "UNAVAILABLE" and body.get("acknowledged_summary_unavailable") is not True:
                    raise ClosureError(400, "SUMMARY_UNAVAILABLE_ACK_REQUIRED", "the AI closing summary is unavailable; "
                                       "GENERATE requires acknowledging that")
                rd = self.readiness(c, s)
                if rd["blockers"]:
                    raise ClosureError(409, "BLOCKED", "generation is blocked: " + " ".join(rd["blockers"]),
                                       blockers=rd["blockers"])
                comment, comment_ascii = self._provenance_comment(c, actor)
                rec = self._decision_record(c, s, "GENERATE", actor, meta, body, comment)
                rec["comment_ascii"] = comment_ascii
                _append(self._session_dir(c, s["review_id"]) / "decisions.jsonl", rec)
                job = None
                try:
                    job = self._job("final_pack", c, review_id=s["review_id"], requested_by=actor,
                                    review_decision_id=rec["review_decision_id"], preview_id=meta["preview_id"])
                    s["status"] = "GENERATING"
                    self._save_session(c, s)
                    c = self._save(self._load(ref, run))
                except Exception as e:                           # never GENERATING without a running job
                    self._generation_not_started(ref, run, s, job, f"{type(e).__name__}: {str(e)[:500]}")
                    raise
        if decision == "HOLD":
            self._audit("CLOSING_REVIEW_HELD", c, actor, review_id=s["review_id"],
                        review_decision_id=rec["review_decision_id"], comment=rec["comment"])
            return {"decision": rec, "job_id": None, "closure": self.view(ref)}
        try:
            self._thread(self._run_final, job)
        except Exception as e:
            with self._lock(ref, run):
                self._generation_not_started(ref, run, self._session(self._load(ref, run)), job,
                                             f"{type(e).__name__}: {str(e)[:500]}")
            raise
        return {"decision": {k: v for k, v in rec.items() if k != "comment_ascii"}, "job_id": job["job_id"],
                "closure": self.view(ref)}

    def _generation_not_started(self, ref: str, run: str, s: dict, job: dict | None, err: str) -> None:
        """GENERATE was recorded but its job could not be started: the job (if any) ends FAILED and the review is
        GENERATION_FAILED with the reason, so it is never stuck GENERATING. Best effort (the caller re-raises)."""
        try:
            if job is not None and job.get("state") in ACTIVE:
                self._job_end(job, "failed", None, "final-pack generation could not be started: " + err)
            c = self._load(ref, run)
            s = self._session(c) or s
            s["status"] = "GENERATION_FAILED"
            self._save_session(c, s)
            c["last_generation_failure"] = {"at": now(), "error": "final-pack generation could not be started: " + err,
                                            "job_id": (job or {}).get("job_id"), "final_pack_id": None}
            self._save(c)
        except Exception:
            traceback.print_exc()

    def _decision_record(self, c, s, decision, actor, meta, body, comment) -> dict:
        return {"review_decision_id": _new_id("RD"), "review_id": s["review_id"], "decision": decision,
                "decided_at": now(), "reviewer": {"user_id": actor, "display_name": actor}, "decided_by": actor,
                "system_reviewer_id": self._system_reviewer_id(), "comment": comment,
                "acknowledgement_accepted": bool(body.get("acknowledgement_accepted")) if decision == "GENERATE" else False,
                "acknowledged_summary_unavailable": bool(body.get("acknowledged_summary_unavailable")),
                "snapshot_sha256": (meta or {}).get("snapshot_sha256", ""), "preview_id": (meta or {}).get("preview_id", ""),
                "closing_summary_sha256": ((meta or {}).get("closing_summary") or {}).get("sha256", "")}

    def _source_files(self, c: dict) -> list[dict]:
        rec = results.load_record(self._run_dir(c["recon_run_id"]))
        return [{"evidence_category": s["evidence_category"], "canonical_name": s.get("engine_canonical_name"),
                 "original_filename": s.get("original_filename"), "file_version_id": s["file_version_id"],
                 "source_sha256": s["source_sha256"]} for s in rec["input"]["staged"]]

    def _provenance_comment(self, c: dict, actor: str) -> tuple[str, str]:
        """System-generated, fixed-template provenance text for the GENERATE decision (NOT analyst free text)."""
        files = self._source_files(c)
        z = c.get("zip") or {}

        def text(dash, arrow):
            head = (f"Ringfence provenance {dash} case {c['case_ref']}; reconciliation run {c['recon_run_id']}; snapshot "
                    f"{c['snapshot_id']}; original ZIP {z.get('filename')} sha256 {z.get('sha256')}; generated by {actor} "
                    f"(system reviewer {self._system_reviewer_id()}); source files: ")
            body = "; ".join(f"{f['evidence_category']} {f['canonical_name']} {arrow} {f['original_filename']} "
                             f"({f['file_version_id']}, {f['source_sha256']})" for f in files)
            return (head + body + ". Full list also in the Ringfence provenance supplement (ringfence_provenance.json). "
                    + mapping_sentence)
        mapping_sentence = mapping_provenance_sentence(self._mapping_provenance(c))
        return text("—", "→"), text("-", "->")

    def _mapping_provenance(self, c: dict) -> dict:
        """Column-mapping provenance of the case's package (contract I-3, provided by
        smartparser/webapp/mapping_provenance.py). Guarded: when the module is absent, fails or breaks the contract, the
        supplement says so visibly (status UNAVAILABLE with the reason); nothing is ever invented or back-filled."""
        try:
            from . import mapping_provenance as mp_mod
        except ImportError as e:                                   # no local paths in text that reaches the pack
            return _mapping_unavailable(f"the mapping provenance module is not installed ({type(e).__name__})")
        try:
            doc = mp_mod.build_mapping_provenance(self.ctx, c["package_id"], c["snapshot_id"])
        except Exception as e:                                     # recorded, never hidden; generation is not blocked
            msg = re.sub(r"(?:[A-Za-z]:)?[\\/][^\s'\"]*[\\/][^\s'\"]*", "<path>", str(e))[:300]
            return _mapping_unavailable(f"mapping provenance could not be built: {type(e).__name__}: {msg}")
        problems = mapping_provenance_problems(doc, c["package_id"], c["snapshot_id"])
        if problems:
            return _mapping_unavailable("mapping provenance does not satisfy contract I-3: " + "; ".join(problems[:5]))
        return dict(doc, status="AVAILABLE", reason=None)

    def _run_final(self, j: dict) -> None:
        ref, run = j["case_ref"], j["recon_run_id"]
        self._job_start(j)
        c = self._load(ref, run)
        s = self._session(c)
        P = self._paths(c)
        decisions = _jsonl(self._session_dir(c, s["review_id"]) / "decisions.jsonl")
        rec = next(d for d in decisions if d["review_decision_id"] == j["review_decision_id"])
        meta = self._preview_meta(c, s, j["preview_id"])
        prior = [{"review_decision_id": d["review_decision_id"], "decision": "HOLD", "decided_at": d["decided_at"],
                  "comment": d["comment"]} for d in decisions if d["decision"] == "HOLD"]
        review = {"review_decision_id": rec["review_decision_id"], "review_session_id": s["review_id"],
                  "reviewer": rec["reviewer"], "decided_at": rec["decided_at"], "comment": rec["comment"],
                  "comment_ascii": rec.get("comment_ascii") or rec["comment"],
                  "acknowledged_summary_unavailable": rec["acknowledged_summary_unavailable"], "prior_decisions": prior}
        res, err = None, None
        try:
            res = self.runner.generate_final(
                pack_id=c["pack"]["pack_id"], packs_root=P["packs"], investigations_root=P["investigations"],
                final_packs_root=P["final_packs"], selections=meta["selections"],
                analyst_reviews=[self.library_review(r) for r in self._reviews(c)
                                 if r["analyst_review_id"] in set(meta["analyst_review_ids"])],
                closing_summary_path=self._session_dir(c, s["review_id"]) / "previews" / meta["preview_id"]
                / "closing_summary.json", review=review, expected_snapshot_sha256=meta["snapshot_sha256"],
                scratch=P["scratch"])
            if res["verify_problems"]:
                err = "final pack verification failed: " + "; ".join(res["verify_problems"])
        except ClosureRunnerError as e:
            err = str(e)
        prov = None
        if err is None:
            try:
                prov = self._write_provenance(c, s, res, rec, decisions)
            except Exception as e:                                       # the supplement is required: never half-done
                err = f"provenance supplement could not be written: {type(e).__name__}: {e}"
        with self._lock(ref, run):
            c = self._load(ref, run)
            s = self._session(c)
            if err is None:
                c["final_pack"] = {"final_pack_id": res["final_pack_id"], "status": "GENERATED", "verified": True,
                                   "problems": [], "path": res["path"], "version": res["version"],
                                   "supersedes_final_pack_id": res["supersedes_final_pack_id"],
                                   "generated_at": res["generated_at"], "authorised_by": rec["reviewer"]["user_id"],
                                   "review_decision_id": rec["review_decision_id"], "review_id": s["review_id"],
                                   "final_content_sha256": res["final_content_sha256"],
                                   "manifest_sha256": _sha((Path(res["path"]) / "manifest.json").read_bytes()),
                                   "provenance": prov, "job_id": j["job_id"]}
                c["frozen"], c["final_pack_id"] = True, res["final_pack_id"]
                s["status"], s["final_pack_id"] = "GENERATED", res["final_pack_id"]
            else:
                c["last_generation_failure"] = {"at": now(), "error": err[:1500], "job_id": j["job_id"],
                                                "final_pack_id": (res or {}).get("final_pack_id")}
                s["status"] = "GENERATION_FAILED"
            self._save_session(c, s)
            c = self._save(c)
        if err is None:
            self._audit("FINAL_PACK_GENERATED", c, j.get("requested_by"), review_id=s["review_id"], job_id=j["job_id"],
                        final_pack_id=res["final_pack_id"], review_decision_id=rec["review_decision_id"],
                        authorised_by=rec["reviewer"]["user_id"], verified=True,
                        final_content_sha256=res["final_content_sha256"])
            self._job_end(j, "completed", {"final_pack_id": res["final_pack_id"], "verified": True})
        else:
            self._audit("FINAL_PACK_GENERATION_FAILED", c, j.get("requested_by"), review_id=s["review_id"],
                        job_id=j["job_id"], review_decision_id=rec["review_decision_id"], reason=err[:1000],
                        final_pack_id=(res or {}).get("final_pack_id"))
            self._job_end(j, "failed", {"final_pack_id": (res or {}).get("final_pack_id"), "verified": False}, err)

    def _write_provenance(self, c: dict, s: dict, res: dict, rec: dict, decisions: list) -> dict:
        d = self._paths(c)["provenance"] / res["final_pack_id"]
        if d.exists():
            raise FileExistsError(f"{d} exists (the provenance supplement is write-once)")
        d.mkdir(parents=True)
        hist = []
        for r in self._reviews(c):
            hist.append({"at": r["decided_at"], "what": f"{r['decision']} AI finding {r['investigation_id']} "
                         f"({r['exception_id']}, revision {r['revision']})", "by": r["decided_by"]})
        for x in decisions:
            hist.append({"at": x["decided_at"], "what": f"closing review {x['decision']} ({x['review_decision_id']})",
                         "by": x["decided_by"]})
        for a in _jsonl(self._dir(c["case_ref"], c["recon_run_id"]) / "ai_authorizations.jsonl"):
            hist.append({"at": a["recorded_at"], "what": f"AI authorisation {a['kind']} {a['status']} "
                         f"({a['authorization_id']})", "by": a.get("authorized_by") or SYSTEM_ACTOR})
        hist.sort(key=lambda h: h["at"] or "")
        doc = {"schema": "ringfence-provenance/1.0", "final_pack_id": res["final_pack_id"], "case_ref": c["case_ref"],
               "recon_run_id": c["recon_run_id"], "snapshot_id": c["snapshot_id"], "package_id": c["package_id"],
               "pack_id": c["pack"]["pack_id"], "period": c["period"], "zip": c.get("zip"),
               "authorised_by": rec["reviewer"]["user_id"], "system_reviewer_id": self._system_reviewer_id(),
               "generated_at": res["generated_at"], "review_id": s["review_id"],
               "review_decision_id": rec["review_decision_id"], "final_content_sha256": res["final_content_sha256"],
               "source_files": self._source_files(c), "decisions": hist,
               "mapping_provenance": self._mapping_provenance(c),
               "statement": "System-generated Ringfence provenance supplement (write-once). It maps the engine's "
                            "canonical evidence files back to the customer's uploaded files, records how each source "
                            "column was mapped to a canonical field (method, rule or AI proposal, who decided and "
                            "confirmed it, validation; values not recorded at the time are shown as not recorded, never "
                            "inferred) and who took each closure decision. It is not part of the library's final pack "
                            "and does not change it."}
        pj = d / "ringfence_provenance.json"
        pj.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        pp = d / "ringfence_provenance.pdf"
        self.runner.provenance_pdf(pj, pp, self._paths(c)["scratch"])
        out = {"json": str(pj), "pdf": str(pp), "json_sha256": _sha(pj.read_bytes()), "pdf_sha256": _sha(pp.read_bytes())}
        # Analyst edition (no AI). A failure never fails the generation: the technical report is the record; the reason
        # is kept so the screen can say why the shorter edition is missing.
        ap = d / "report_analyst.pdf"
        try:
            r = self.runner.analyst_pdf(Path(res["path"]) / "final_pack.json", pj, self._paths(c)["packs"], ap,
                                        self._paths(c)["scratch"])
            out.update(analyst_pdf=str(ap), analyst_pdf_sha256=_sha(ap.read_bytes()), analyst_renderer=r.get("renderer"),
                       analyst_omitted=r.get("omitted") or [], analyst_source_pack_verified=r.get("source_pack_verified"))
        except Exception as e:                                   # recorded, never hidden
            out.update(analyst_error=f"{type(e).__name__}: {e}"[:500])
        return out

    # ============================================================================================ final pack reads
    def final_pack(self, ref: str) -> dict:
        c, _ = self._locate(ref)
        fp = c.get("final_pack")
        if not fp:
            fail = c.get("last_generation_failure")
            if fail:
                return {"final_pack_id": fail.get("final_pack_id"), "status": "GENERATION_FAILED", "verified": False,
                        "problems": [fail["error"]], "files": [], "authorised_by": None, "generated_at": None}
            raise ClosureError(404, "NO_FINAL_PACK", "no final pack has been generated for this closure")
        integ = self._integrity(fp)
        files = []
        keys = ("pdf", "html", "json", "manifest", "provenance.pdf", "provenance.json") +             (("analyst.pdf",) if (fp.get("provenance") or {}).get("analyst_pdf") else ())
        for key in keys:
            try:
                p = self._final_path(fp, key)
                files.append({"key": key, "name": p.name, "size_bytes": p.stat().st_size if p.is_file() else None,
                              "sha256": _sha(p.read_bytes()) if p.is_file() else None,
                              "url": f"/api/cases/{ref}/closure/final-pack/{key}"})
            except (OSError, KeyError, TypeError):
                files.append({"key": key, "name": None, "size_bytes": None, "sha256": None,
                              "url": f"/api/cases/{ref}/closure/final-pack/{key}"})
        return {"final_pack_id": fp["final_pack_id"], "status": fp["status"], "verified": integ["verified"],
                "integrity": integ["status"], "integrity_checked_at": integ["checked_at"],
                "problems": integ["problems"], "files": files, "authorised_by": fp["authorised_by"],
                "generated_at": fp["generated_at"], "version": fp.get("version"),
                "final_content_sha256": fp.get("final_content_sha256")}

    def _final_path(self, fp: dict, key: str) -> Path:
        if key == "provenance.pdf":
            return Path(fp["provenance"]["pdf"])
        if key == "provenance.json":
            return Path(fp["provenance"]["json"])
        if key == "analyst.pdf":
            return Path(fp["provenance"]["analyst_pdf"])
        return Path(fp["path"]) / FINAL_FILES[key][0]

    def _check_files(self, fp: dict) -> list[str]:
        """Integrity of a generated final pack, from the files on disk NOW (never from a stored flag): the manifest is
        the one recorded at generation, every manifest file matches its SHA-256, the report files are listed, and the
        provenance supplement matches the hashes recorded at generation. Read-only: nothing is repaired or re-signed.
        Any unexpected content (a tampered, malformed manifest) is a problem, never an exception."""
        problems = []
        try:
            d = Path(fp["path"])
            mb = (d / "manifest.json").read_bytes()
        except (OSError, KeyError, TypeError) as e:
            return [f"manifest unreadable: {e}"]
        if _sha(mb) != fp.get("manifest_sha256"):
            problems.append("manifest.json differs from the manifest recorded at generation")
        try:
            manifest = json.loads(mb)
            listed = manifest["files"]
            if not isinstance(listed, dict):
                raise TypeError("'files' is not an object")
        except (ValueError, KeyError, TypeError) as e:
            return problems + [f"manifest unreadable: {type(e).__name__}: {e}"]
        for name, info in listed.items():
            p = d / str(name)
            try:
                ok = (Path(str(name)).name == str(name) and p.is_file() and isinstance(info, dict)
                      and _sha(p.read_bytes()) == info.get("sha256"))
            except OSError:
                ok = False
            if not ok:
                problems.append(f"{name} does not match its manifest SHA-256")
        for key in ("pdf", "html", "json"):
            if FINAL_FILES[key][0] not in listed:
                problems.append(f"{FINAL_FILES[key][0]} is not listed in the manifest")
        prov = fp.get("provenance") or {}
        for k in ("json", "pdf"):
            try:
                p = Path(prov[k])
                ok = p.is_file() and _sha(p.read_bytes()) == prov[f"{k}_sha256"]
            except (OSError, KeyError, TypeError):
                ok = False
            if not ok:
                problems.append(f"provenance {k} does not match the SHA-256 recorded at generation")
        if prov.get("analyst_pdf"):
            try:
                p = Path(prov["analyst_pdf"])
                ok = p.is_file() and _sha(p.read_bytes()) == prov.get("analyst_pdf_sha256")
            except (OSError, TypeError):
                ok = False
            if not ok:
                problems.append("analyst edition PDF does not match the SHA-256 recorded at generation")
        return problems

    def _integrity(self, fp: dict) -> dict:
        """Current integrity of a generated final pack (Fix8 D8): recomputed from the files on every read. The flag stored
        at generation is only an upper bound (a pack that failed then never verifies later)."""
        problems = self._check_files(fp)
        verified = bool(fp.get("verified")) and not problems
        return {"verified": verified, "status": "VERIFIED" if verified else "FAILED", "problems": problems,
                "checked_at": now()}

    def final_file(self, ref: str, key: str, download: bool) -> tuple:
        c, _ = self._locate(ref)
        fp = c.get("final_pack")
        if not fp or key not in FINAL_FILES:
            raise ClosureError(404, "NO_FINAL_PACK", "no such final-pack file")
        problems = self._check_files(fp)
        if problems:
            raise ClosureError(409, "INTEGRITY", "the final pack does not verify: " + "; ".join(problems))
        p = self._final_path(fp, key)
        name = f"{fp['final_pack_id']}-{p.name}"
        return FINAL_FILES[key][1], p.read_bytes(), {
            "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"',
            "X-Final-Pack-Id": fp["final_pack_id"]}

    # ============================================================================================ pack reads
    def pack_view(self, ref: str) -> dict:
        c, _ = self._locate(ref)
        pk = c.get("pack") or {}
        out = {"status": pk.get("status"), "pack_id": pk.get("pack_id"), "reason": pk.get("reason"),
               "findings": pk.get("findings") or [], "executive_summary": None, "exception_register": [],
               "missing_evidence_register": [], "source_register": []}
        if pk.get("status") != "GENERATED":
            return out
        pack = self._pack(c)
        trace = self._trace(c)
        out.update(executive_summary=pack["executive_summary"],
                   exception_register=pack["exception_register"]["exceptions"],
                   exception_statement=pack["exception_register"].get("statement"),
                   missing_evidence_register=pack["missing_evidence_register"]["items"],
                   missing_evidence_statement=pack["missing_evidence_register"].get("statement"),
                   source_register=[dict(f, **{k: v for k, v in self._ref_for(trace, f.get("source_file")).items()
                                               if k in ("original_filename", "file_version_id", "source_sha256")})
                                    for f in pack["evidence_register"]["files"]],
                   html_url=f"/api/cases/{ref}/closure/pack.html")
        return out

    def pack_html(self, ref: str) -> tuple:
        c, _ = self._locate(ref)
        self._pack(c)
        data = (self._paths(c)["packs"] / c["pack"]["pack_id"] / "pack.html").read_bytes()
        return "text/html; charset=utf-8", data, {"Content-Disposition": f'inline; filename="{c["pack"]["pack_id"]}.html"'}

    # ============================================================================================ exception workspace
    def _ai_state(self, c: dict, exc: str, reg: dict, cfg: dict) -> tuple[str, list]:
        jobs = self._jobs(c, "investigation", exc)
        if (c.get("pack") or {}).get("status") != "GENERATED":
            return "UNAVAILABLE", jobs
        if not jobs:
            return ("NOT_STARTED" if cfg["available"] else "UNAVAILABLE"), jobs
        last = jobs[-1]
        if last["state"] == "queued":
            return "QUEUED", jobs
        if last["state"] == "running":
            return "RUNNING", jobs
        outcome = (last.get("result") or {}).get("outcome")
        if last["state"] == "completed" and outcome in ("PUBLISHED", "NOT_PUBLISHED"):
            return outcome, jobs
        return "FAILED", jobs

    def _exception_row(self, c: dict, x: dict, reg: dict, active: dict, cfg: dict, missing: list) -> dict:
        e = x["exception_id"]
        state, jobs = self._ai_state(c, e, reg, cfg)
        pub = self._published_for(c, reg, e)
        inv = pub[0]["investigation_id"] if pub else None
        dec = active.get(inv) if inv else None
        aff = x.get("affected") or ""
        return {"exception_id": e, "severity": x.get("severity"), "category": x.get("category"),
                "root_cause": x.get("root_cause"), "account_id": x.get("account_id"), "currency": x.get("currency"),
                "amount": x.get("amount"), "status": x.get("status") or "OPEN",
                "missing_evidence": any(m.get("related_exception_id") == e for m in missing)
                or "[INSUFFICIENT_EVIDENCE]" in aff,
                "ai_state": state, "investigation_id": inv, "attempts": len(jobs),
                "analyst_decision": dec["decision"] if dec else None, "decision_revision": dec["revision"] if dec else None,
                "decided_by": dec["decided_by"] if dec else None, "decided_at": dec["decided_at"] if dec else None,
                # PENDING_REVIEW: a published AI finding with no analyst decision yet (never treated as accepted)
                "review_state": "PENDING_REVIEW" if inv and not dec else ("REVIEWED" if dec else None)}

    def exception_workspace(self, ref: str, exc: str) -> dict:
        c, _ = self._locate(ref)
        if not ID_RE.match(exc or ""):
            raise ClosureError(404, "NOT_FOUND", f"unknown exception {exc!r}")
        rd = self._run_dir(c["recon_run_id"])
        cfg = self.runner.ai_configuration()
        reg, active = self._registry(c), self._active_reviews(c)
        missing = self._missing_items(c)
        pack_row = next((x for x in self._exceptions(c) if x["exception_id"] == exc), None)
        try:
            engine = results.exception_detail(rd, exc)
        except results.RunNotFound:
            engine = None
        if pack_row is None and engine is None:
            raise ClosureError(404, "NOT_FOUND", f"{exc} is not an exception of this reconciliation")
        row = self._exception_row(c, pack_row or engine["exception"], reg, active, cfg, missing)
        supporting = [{"reference": ev["reference"], "original_filename": ev.get("original_filename"),
                       "file_version_id": ev.get("file_version_id"), "line": ev.get("line"), "row": ev.get("row"),
                       "source_sha256": ev.get("source_sha256"), "evidence_category": ev.get("evidence_category")}
                      for ev in (engine or {}).get("evidence", [])]
        miss = []
        for m in missing:
            if m.get("related_exception_id") != exc:
                continue
            parts = (m.get("expected_evidence") or "").split("|")
            miss.append({"category": parts[0] if parts else None, "account": parts[1] if len(parts) > 1 else None,
                         "date": parts[2] if len(parts) > 2 else None, "what": m.get("expected_evidence"),
                         "why_required": m.get("completeness_impact"), "item_id": m.get("item_id"),
                         "related_controls": m.get("related_controls")})
        src = pack_row or (engine or {}).get("exception") or {}
        facts = {"label": "System-generated, not AI",
                 "control_results": (engine or {}).get("affected_control_results", []),
                 "supporting_evidence": supporting, "missing_evidence": miss,
                 "impact": "; ".join(v for v in (f"{src.get('amount')} {src.get('currency')}".strip()
                                                 if src.get("amount") else "", src.get("flags") or "") if v) or None,
                 "suggested_next_action": ("Obtain the missing evidence listed above; the exception stays UNRESOLVED "
                                           "until it is supplied in a new submission." if row["missing_evidence"] else
                                           "Review the cited records" + (" and the AI finding (accept or reject it)."
                                                                         if row["investigation_id"] else "."))}
        workspace = {"exception": {"engine": (engine or {}).get("exception"), "pack": pack_row,
                                   "investigation_group": (engine or {}).get("investigation_group")},
                     "summary": row, "facts": facts, "investigation": self._investigation_block(c, exc, reg, cfg),
                     "decision": self._decision_block(c, exc, row, reg, active), "revision": c["revision"],
                     "note": "Engine values are shown exactly as written by the UC-042 engine. AI content is labelled "
                             "AI-generated; an analyst decision on an AI finding never resolves the exception."}
        return workspace

    def _citations(self, c: dict, d: Path, f: dict) -> dict:
        """evidence ID cited by the findings -> the customer's file (original filename, file version, line)."""
        ledger = _read_json(d / "evidence_ledger.json") or _read_json(d / "evidence_packet.json", {})
        trace = self._trace(c)
        recs = {r.get("evidence_id"): r for r in ledger.get("source_records") or []}
        cited = set(f.get("evidence_references") or [])
        for x in f.get("confirmed_findings") or []:
            cited |= set(x.get("evidence_ids") or []) | set(x.get("supporting_records") or [])
        # hypotheses cite evidence too (supporting / contradictory); their chips must resolve like the findings'
        for h in f.get("hypotheses") or []:
            if isinstance(h, dict):
                cited |= {e for k in ("supporting_evidence", "contradictory_evidence", "evidence_ids")
                          for e in (h.get(k) or []) if isinstance(e, str)}
        out = {}
        for eid in sorted(cited):
            r = recs.get(eid)
            out[eid] = self._ref_for(trace, r.get("source_file"), r.get("source_line"), reference=eid) if r else                 {"reference": eid, "original_filename": None, "file_version_id": None, "line": None}
        return out

    def _investigation_block(self, c: dict, exc: str, reg: dict, cfg: dict) -> dict | None:
        state, jobs = self._ai_state(c, exc, reg, cfg)
        attempts = [{"job_id": j["job_id"], "attempt": j.get("attempt"), "state": j["state"],
                     "outcome": (j.get("result") or {}).get("outcome"), "error": j.get("error"),
                     "reason": (j.get("result") or {}).get("reason"), "created_at": j["created_at"],
                     "finished_at": j.get("finished_at"), "retry_of": j.get("retry_of"),
                     "investigation_id": (j.get("result") or {}).get("investigation_id")} for j in jobs]
        pub = self._published_for(c, reg, exc)
        if not pub:
            return None if not jobs else {"state": state, "investigation_id": None, "attempts": attempts,
                                          "label": "AI-generated", "provider": None, "model": None}
        entry = pub[0]
        d = self._inv_dir(c, exc, entry["investigation_id"])
        f = _read_json(d / "findings.json", {})
        citations = self._citations(c, d, f)
        problems = self._verify_inv(c, entry)
        return {"state": state, "investigation_id": entry["investigation_id"], "attempts": attempts,
                "label": "AI-generated", "provider": entry.get("provider"), "model": entry.get("model"),
                "prompt_version": entry.get("prompt_version"), "created_at": f.get("investigated_at"),
                "sufficiency": f.get("overall_evidence_assessment"), "conclusion": f.get("investigation_summary"),
                "confirmed_findings": [{"id": x.get("finding_id"), "title": x.get("title"), "claim": x.get("claim"),
                                        "explanation": x.get("explanation"), "evidence_ids": x.get("evidence_ids") or [],
                                        "establishes": x.get("establishes"),
                                        "does_not_establish": x.get("does_not_establish")}
                                       for x in f.get("confirmed_findings") or []],
                "hypotheses": f.get("hypotheses") or [], "missing_evidence": f.get("missing_evidence") or [],
                "next_steps": f.get("recommended_next_steps") or [], "open_questions": f.get("open_questions") or [],
                "citations": citations,
                "validation": {"status": f.get("validation_status"), "problems": problems,
                               "eligible": entry["eligible"] and not problems}}

    def _decision_block(self, c: dict, exc: str, row: dict, reg: dict, active: dict) -> dict:
        inv = row["investigation_id"]
        hist = [r for r in self._reviews(c) if r["exception_id"] == exc]
        cur = active.get(inv) if inv else None
        entry = reg["investigations"].get(inv) if inv else None

        def act(label):
            if c.get("frozen"):
                return {"enabled": False, "reason": "closure is frozen (final pack generated)", "label": label}
            s = self._session(c)
            if s and s["status"] == "GENERATING":
                return {"enabled": False, "reason": "a final pack is being generated", "label": label}
            if not inv:
                return {"enabled": False, "reason": "there is no published AI finding to decide on", "label": label}
            if not (entry or {}).get("eligible"):
                return {"enabled": False, "reason": "the AI finding is not eligible", "label": label}
            return {"enabled": True, "reason": None, "label": label}
        def explained(r):   # the analyst's own explanation (None when only the fixed wording was recorded)
            return r.get("comment") or (r.get("rejection_reason") if r.get("rejection_reason") != FIXED["REJECT"] else "") or None
        return {"current": None if cur is None else dict({k: cur[k] for k in ("decision", "revision", "decided_by",
                                                                              "decided_at", "analyst_review_id")},
                                                         explanation=explained(cur)),
                "review_state": "PENDING_REVIEW" if cur is None and inv else ("REVIEWED" if cur else None),
                "history": [dict({k: r[k] for k in ("analyst_review_id", "investigation_id", "decision", "revision",
                                                    "decided_by", "decided_at", "rejection_reason")},
                                 explanation=explained(r)) for r in hist],
                "actions": {"accept": act("Accept AI finding"), "reject": act("Reject AI finding")},
                "rejection_wording": FIXED["REJECT"]}

    def investigation(self, ref: str, inv: str) -> dict:
        c, _ = self._locate(ref)
        reg = self._registry(c)
        entry = reg["investigations"].get(inv)
        if entry is None:
            raise ClosureError(404, "NOT_FOUND", f"{inv} is not a published investigation of this closure")
        d = self._inv_dir(c, entry["exception_id"], inv)
        f = _read_json(d / "findings.json", {})
        ledger = _read_json(d / "evidence_ledger.json") or _read_json(d / "evidence_packet.json", {})
        tools = _read_json(d / "tool_calls.json", {}) or {}
        trace = self._trace(c)
        records = [dict(r, customer_reference=self._ref_for(trace, r.get("source_file"), r.get("source_line")))
                   for r in ledger.get("source_records") or []]
        problems = self._verify_inv(c, entry)
        return {"investigation": dict(entry, label="AI-generated", investigated_at=f.get("investigated_at"),
                                      validation_status=f.get("validation_status"),
                                      investigation_status=f.get("investigation_status"),
                                      tool_summary=f.get("tool_summary")),
                "findings": f, "evidence_ledger": {"records": records,
                                                   "allowed_citation_ids": ledger.get("allowed_citation_ids", []),
                                                   "citations": self._citations(c, d, f)},
                "tool_calls": tools.get("tool_calls") or [], "verify": {"ok": not problems, "problems": problems}}

    # ============================================================================================ history
    def _closure_events(self, c: dict) -> list[dict]:
        return [e for e in self.ctx.events() if e["details"].get("case_ref") == c["case_ref"]
                and e["details"].get("recon_run_id") == c["recon_run_id"]]

    def exception_history(self, ref: str, exc: str) -> dict:
        c, _ = self._locate(ref)
        ev = [e for e in self._closure_events(c) if e["details"].get("exception_id") == exc
              or exc in (e["details"].get("exceptions") or [])]
        return {"exception_id": exc, "events": [{k: e.get(k) for k in ("seq", "event_type", "at", "actor_id")}
                                                | {"details": e["details"]} for e in ev]}

    def history(self, ref: str) -> dict:
        c, _ = self._locate(ref)
        s = self._session(c)
        try:
            chain = {"verified": True, "events": self.ctx.log.verify()}
        except Exception as exc:
            chain = {"verified": False, "error": str(exc)[:300]}
        d = self._dir(c["case_ref"], c["recon_run_id"])
        return {"case_ref": ref, "recon_run_id": c["recon_run_id"], "chain": chain,
                "events": [{k: e.get(k) for k in ("seq", "event_type", "at", "actor_id", "actor_role")}
                           | {"details": e["details"]} for e in self._closure_events(c)],
                "analyst_decisions": self._reviews(c),
                "review_decisions": _jsonl(self._session_dir(c, s["review_id"]) / "decisions.jsonl") if s else [],
                "ai_authorizations": _jsonl(d / "ai_authorizations.jsonl"),
                "investigation_attempts": self._registry(c)["attempts"]}

    # ============================================================================================ ClosureView
    def view(self, ref: str) -> dict:
        """A consistent snapshot: the closure record is read first and job states (in memory) later, so a job that
        saved the closure and then ended in between would make the view look settled with the PREVIOUS revision (the
        next action then gets 409 CLOSURE_CHANGED). The view is rebuilt until the record's revision did not move while
        it was being built (bounded; no lock is held, so no deadlock with job threads)."""
        v = None
        for _ in range(20):
            c, run = self._locate(ref)
            v = self._view(c)
            if self._load(ref, run)["revision"] == c["revision"]:
                return v
        return v

    def _view(self, c: dict) -> dict:
        cfg = self.runner.ai_configuration()
        pack = c.get("pack") or {}
        s = self._session(c)
        reg, active = self._registry(c), self._active_reviews(c)
        missing = self._missing_items(c)
        excs = self._exceptions(c)
        rows = [self._exception_row(c, x, reg, active, cfg, missing) for x in excs]
        rec = results.load_record(self._run_dir(c["recon_run_id"]))
        outcomes = rec["result"].get("outcomes") or {}
        by_sev = dict(Counter(x.get("severity") for x in excs))
        text = [f"The UC-042 engine reported case status {rec['result']['case_status']}.",
                f"{sum(outcomes.values())} control results: " + ", ".join(f"{v} {k}" for k, v in sorted(outcomes.items()))
                + "." if outcomes else "No control results were recorded.",
                f"{len(excs)} exception(s) raised" + (": " + ", ".join(f"{v} {k}" for k, v in sorted(by_sev.items())) + "."
                                                       if excs else "; no AI investigation is needed.")]
        if pack.get("status") == "UNAVAILABLE":
            text.append(f"The audit pack is UNAVAILABLE: {pack.get('reason')}.")
        inputs = self._inputs(c, s) if pack.get("status") == "GENERATED" else None
        review = self._review_view(c, inputs)
        rd = review["readiness"]
        active_inv = any(j["state"] in ACTIVE for j in self._jobs(c, "investigation")) \
            or (c.get("auto_investigation") == "STARTING" and (c["case_ref"], c["recon_run_id"]) not in self._auto_done)
        fp = c.get("final_pack")
        integ = self._integrity(fp) if fp else None          # D8: from the files now, never the stored flag
        cur = review.get("current_preview")
        if pack.get("status") == "PENDING":
            state = "PACK_PENDING"
        elif pack.get("status") != "GENERATED":
            state = "PACK_UNAVAILABLE"
        elif fp and fp.get("status") == "GENERATED":
            state = "GENERATED" if integ["verified"] else "INTEGRITY_FAILED"
        elif s and s["status"] == "GENERATING":
            state = "GENERATING"
        elif s and s["status"] == "GENERATION_FAILED":
            state = "GENERATION_FAILED"
        elif active_inv:
            state = "INVESTIGATING"
        elif s and s["status"] == "ON_HOLD":
            state = "ON_HOLD"
        elif cur and not cur["stale"] and not rd["blockers"]:
            state = "PREVIEW_READY"
        elif not [b for b in rd["blockers"] if not self._preview_blocker(b)]:
            state = "READY"
        else:
            state = "DECIDING"
        frozen = bool(c.get("frozen"))
        generating = bool(s and s["status"] == "GENERATING")
        open_ok = pack.get("status") == "GENERATED" and not frozen and not generating

        def a(ok, why):
            return {"enabled": bool(ok), "reason": None if ok else why}
        frozen_why = "closure is frozen (final pack generated)" if frozen else (
            "a final pack is being generated" if generating else
            f"audit pack unavailable: {pack.get('reason') or 'still being generated'}")
        non_preview = [b for b in rd["blockers"] if not self._preview_blocker(b)]
        actions = {
            "retry_investigation": a(open_ok and cfg["available"] and bool(excs),
                                     frozen_why if not open_ok else (cfg["problem"] or "no exceptions")),
            "decide": a(open_ok and any(r["investigation_id"] for r in rows),
                        frozen_why if not open_ok else "no published AI finding to decide on"),
            "open_review": a(open_ok and s is None, frozen_why if not open_ok else "the review is already open"),
            "set_selections": a(open_ok and bool(excs), frozen_why if not open_ok else "no exceptions to select"),
            "preview": dict(a(open_ok and not non_preview, frozen_why if not open_ok else " ".join(non_preview)),
                            requires_confirm_ai=bool(excs) and ai_closing_summary() and bool(cfg["available"])),
            "hold": a(open_ok and s is not None, frozen_why if not open_ok else "open the review first"),
            "generate": a(open_ok and bool(cur) and not cur["stale"] and not rd["blockers"],
                          frozen_why if not open_ok else (" ".join(rd["blockers"]) or "preview required")),
        }
        return {"case_ref": c["case_ref"], "recon_run_id": c["recon_run_id"], "snapshot_id": c["snapshot_id"],
                "package_id": c["package_id"], "period": c["period"], "revision": c["revision"], "state": state,
                "frozen": frozen,
                "pack": {"status": pack.get("status"), "pack_id": pack.get("pack_id"), "reason": pack.get("reason")},
                "deterministic_summary": {"label": "System-generated, not AI", "case_status": rec["result"]["case_status"],
                                          "totals": outcomes, "exceptions_by_severity": by_sev, "text": text},
                "ai": {"available": cfg["available"], "provider": cfg["provider"], "model": cfg["model"],
                       "problem": cfg["problem"]},
                "usage": self._usage(c), "exceptions": rows, "review": review,
                "final_pack": None if not fp else {"final_pack_id": fp["final_pack_id"], "status": fp["status"],
                                                   "verified": integ["verified"], "integrity": integ["status"],
                                                   "problems": integ["problems"],
                                                   "integrity_checked_at": integ["checked_at"],
                                                   "authorised_by": fp["authorised_by"],
                                                   "generated_at": fp["generated_at"]},
                "last_generation_failure": c.get("last_generation_failure"), "actions": actions}

    # ============================================================================================ recovery
    def recover(self) -> None:
        """On server start: queued / running closure jobs are already `interrupted` (AppContext); closure state is
        recomputed from files. Nothing re-runs automatically."""
        for p in sorted(self.root.glob("RF-*/*/closure.json")):
            c = _read_json(p)
            if c is None:
                continue
            ref, run = c["case_ref"], c["recon_run_id"]
            changed = False
            pj = self.ctx.jobs.get((c.get("pack") or {}).get("job_id") or "")
            if c["pack"]["status"] == "PENDING" and (pj is None or pj["state"] not in ACTIVE):
                c["pack"].update(status="UNAVAILABLE", reason="interrupted: the server stopped while the audit pack was "
                                 "being generated; nothing re-runs automatically")
                changed = True
            if c.get("auto_investigation") == "STARTING":
                c["auto_investigation"] = "INTERRUPTED"
                changed = True
            s = self._session(c)
            if s and s["status"] == "GENERATING":
                jobs = [j for j in self._jobs(c, "final_pack") if j.get("review_id") == s["review_id"]]
                if not jobs or jobs[-1]["state"] not in ACTIVE:
                    s["status"] = "GENERATION_FAILED"
                    self._save_session(c, s)
                    c["last_generation_failure"] = {"at": now(), "job_id": jobs[-1]["job_id"] if jobs else None,
                                                    "error": "interrupted: the server stopped during final-pack "
                                                             "generation; nothing re-runs automatically"}
                    changed = True
            if changed:
                with self._lock(ref, run):
                    self._save(c)

    # ============================================================================================ AI configuration
    def ai_configuration(self) -> dict:
        return self.runner.ai_configuration()
