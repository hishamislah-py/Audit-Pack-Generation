"""Ringfence case workflow: a file-based case registry and the case lifecycle, layered on the EXISTING services.

A case is one customer's submission for one reporting period: the original ZIP (stored content-addressed with its
SHA-256), and one or more Smart Parser *runs*. Each run owns one evidence package (PackageService). Everything about
evidence, review, validation, activation and reconciliation stays in the existing services; this module only

  * keeps the case record and its status: WAITING -> IN_PROGRESS <-> PENDING ... -> COMPLETED;
  * enforces ONE active (IN_PROGRESS) case at a time, explicit start / defer / resume, and safe deferral (a running
    operation is allowed to finish and persist before the case becomes PENDING);
  * records failed runs and starts a fresh run (new run ID, new package, the stored ZIP processed from stage one)
    while keeping the failed run and its package inspectable;
  * computes queue progress summaries and the actions available, so the frontend never derives lifecycle state;
  * records analyst-initiated actions in the hash-chained audit log, immediately before the existing service call.

Owner decisions O1-O10 (approved 19 Nov 2026) are implemented here: a retry processes the ORIGINAL ZIP only (O1);
recognised review columns need an exactly equal header (O2); file confirmation is explicit (O3); no free-text reasons (O4);
an activated package is immutable (O5); only technical failures fail a run (O6: an unreadable, unopenable or empty ZIP;
ONE unreadable member of a readable ZIP is isolated instead - recorded on the run as `unreadable_entries` and listed as
outstanding work - and every other member is processed, so the run completes; runs recorded before this change keep their
history, including FAILED runs, and new runs follow it); a declared category is a routing hint
the content checks still decide (O7); a deferral never interrupts reconciliation (O9); a PENDING case must be resumed
before a retry (O10).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..mapping import financial
from ..packages import review_api
from ..packages.models import NEEDS_NEW_VERSION
from ..packages.store import _retry_sharing
from . import identity

STATUSES = ("WAITING", "IN_PROGRESS", "PENDING", "COMPLETED")
MAX_ZIP_BYTES = 50 * 1024 * 1024
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def detect_period(data: bytes) -> dict | None:
    """The reporting period of a submission, worked out from the files themselves (23 Nov 2026, owner request), so the
    analyst only names the customer. Read-only; nothing is stored.
    1. the reconciliation-day calendar (a CSV whose header has calendar_date or recon_date): the month most of its dates
       fall in - the most reliable source, because it lists the days being reconciled;
    2. otherwise the period written in the file names (..._2026-09.csv, ..._Sep2026.pdf), when they agree.
    Returns {"period": "YYYY-MM", "basis": ...} or None when the files do not show one period."""
    import csv
    import io
    import zipfile
    from collections import Counter
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    names = [n for n in z.namelist() if not n.endswith("/")]
    for n in names:
        if not n.lower().endswith(".csv"):
            continue
        try:
            with z.open(n) as fh:
                head = fh.read(512 * 1024).decode("utf-8-sig", errors="replace")
        except Exception:
            continue
        rows = list(csv.reader(io.StringIO(head)))
        if not rows:
            continue
        hdr = [h.strip().lower() for h in rows[0]]
        col = next((hdr.index(k) for k in ("calendar_date", "recon_date") if k in hdr), None)
        if col is None or "calendar" not in n.lower() and "calendar_date" not in hdr:
            continue
        months = Counter(r[col][:7] for r in rows[1:] if len(r) > col and re.match(r"\d{4}-\d{2}-\d{2}", r[col].strip()))
        if months:
            period, _ = months.most_common(1)[0]
            if PERIOD_RE.match(period):
                return {"period": period, "basis": f"reconciliation calendar ({Path(n).name})"}
    found = Counter()
    for n in names:
        b = Path(n).name
        for y, m in re.findall(r"(20\d{2})-(0[1-9]|1[0-2])(?!\d)", b):
            found[f"{y}-{m}"] += 1
        for mon, y in re.findall(r"(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ _-]?(20\d{2})", b):
            found[f"{y}-{_MONTHS[mon.lower()]:02d}"] += 1
    if found:
        (period, n1), *rest = found.most_common(2) + [(None, 0)]
        if n1 and (not rest or rest[0][1] < n1):
            return {"period": period, "basis": "file names"}
    return None
# Case assignment: `assigned_to` is the sign-in username of the case OWNER, recorded at registration (the registering
# user by default) or by an audited claim / supervisor reassignment (CASE_ASSIGNED). It filters the Work Queue ("My
# cases") without changing its date-based order and, since Fix8 D7, decides who may act on the case (authz.py: the
# owner, or a supervisor as an audited override). Actions are recorded under the signed-in user (identity.py).
USERNAME_MAX = 256
REF_RE = re.compile(r"^RF-\d{4}-\d{2}-\d{3}$")
RUNNING = ("queued", "running")
# Fixed, generated rationale: the Ringfence UI has no free-text reason field (owner decision); the backend still
# requires a reason, so the action itself is recorded with this explicit wording - never an invented explanation.
REASON = "Ringfence analyst action {action} (no free-text reason is captured by design)"
READ_ERROR_TEXT = {"CRC_FAILURE": "CRC failure", "DECOMPRESSION_ERROR": "decompression error",
                   "UNSUPPORTED_COMPRESSION": "unsupported compression", "ENCRYPTED": "encrypted", "READ_ERROR": "read error"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(p: Path) -> threading.Lock:
    """Fix8 D-recon-io: one in-process lock per case file, shared by readers and the replace (Windows refuses to
    replace a file another thread has open, and a reader can be refused while the replace runs)."""
    key = str(p).lower()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


class CaseError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def needs_attention(row: dict, mechanism: str | None) -> bool:
    """Only columns that need an analyst are sent to manual review. A proposal-session row is always a decision; a
    column-review-case row needs one unless it is an exact canonical (deterministic) match that no other column claims."""
    if row.get("read_only"):
        return False
    if mechanism == "proposal_session":
        return True
    # Owner decision O2 (APPROVED): recognised ONLY when the header is EXACTLY the canonical field name (whatever rule
    # matched it) and no other column claims that field. Case / whitespace variants, alternative names, duplicates and
    # AI proposals always need a per-column analyst decision. Recognised columns are confirmed with the file by the
    # analyst's explicit Confirm file mapping (O3).
    exact = bool(row.get("suggested_field")) and row.get("source_header") == row.get("suggested_field")         and row.get("suggestion_basis") in ("deterministic", "diagnostic_name_match")
    return not (exact and not row.get("duplicate_claim") and not row.get("same_header_positions"))


class CaseService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.root = ctx.root / "cases"
        self.zips = self.root / "zips"
        self.zips.mkdir(parents=True, exist_ok=True)
        # The case registry has its OWN lock. It must not wait for ctx.lock: a reconciliation holds ctx.lock for the
        # whole engine run, and a deferral (or simply opening the queue) must not block on it (O9). Lock order is always
        # case lock -> ctx.lock (service calls); jobs never take the case lock while holding ctx.lock. Package files
        # tolerate concurrent reads (store retries transient Windows sharing violations); the audit log serialises
        # its own appends.
        self.lock = threading.RLock()
        ctx.job_listeners.append(self._on_job_finished)

    # ============================================================================================ persistence
    def _path(self, ref: str) -> Path:
        if not REF_RE.match(ref or ""):
            raise CaseError(404, "NOT_FOUND", f"unknown case {ref!r}")
        return self.root / f"{ref}.json"

    def load(self, ref: str) -> dict:
        """Fix8 D-recon-io: read under the case file's in-process lock (never concurrently with this process's own
        replace of it) and retry a transient Windows sharing violation (another process: indexer, antivirus). A
        persistent violation raises PermissionError - it is never reported as a missing case."""
        p = self._path(ref)
        with _path_lock(p):
            if not p.is_file():
                raise CaseError(404, "NOT_FOUND", f"unknown case {ref}")
            text = _retry_sharing(lambda: p.read_text(encoding="utf-8"))
        return json.loads(text)

    def _save(self, c: dict) -> None:
        """Fix8 D-recon-io: serialise, write a PRIVATE temporary file (unique name: two writers never share or clobber
        one), then replace the record under the case file's lock, retrying transient sharing violations. A failure
        leaves the previous complete record and no temporary file; it propagates."""
        c["revision"] = int(c.get("revision", 0)) + 1                 # optimistic-concurrency token for the frontend
        p = self._path(c["case_ref"])
        text = json.dumps(c, indent=1)
        tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            _retry_sharing(lambda: tmp.write_text(text, encoding="utf-8"))
            with _path_lock(p):
                _retry_sharing(lambda: tmp.replace(p))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def refs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("RF-*.json"))

    def _audit(self, event_type: str, c: dict, **details) -> None:
        # Fix8 D6 (I-1): the acting identity - the signed-in user of this request (or of the request that started the
        # job), the system actor for system-detected events, else the server reviewer (no request context).
        a = identity.current()
        if a is not None:
            actor_id, role = a.user, a.role
        else:
            r = self.ctx.reviewer
            actor_id, role = r.reviewer_id, r.role
        self.ctx.log.append(event_type, actor_id=actor_id, actor_role=role,                        # appends serialised
                            details={"case_ref": c["case_ref"], "package_id": self._pid(c), **details})

    def _history(self, c: dict, status: str, note: str) -> None:
        c["status"] = status
        c["status_history"].append({"status": status, "at": now(), "note": note})
        c["last_activity_at"] = now()

    @staticmethod
    def _pid(c: dict) -> str | None:
        return c["runs"][-1]["package_id"] if c["runs"] else None

    # ============================================================================================ creation
    def create(self, customer_name: str, reporting_period: str, zip_name: str, data: bytes,
               customer_id: str | None = None, assigned_to: str | None = None) -> dict:
        customer_name = (customer_name or "").strip()
        if not customer_name:
            raise CaseError(400, "INVALID", "a customer name is required")
        if assigned_to is not None and not (isinstance(assigned_to, str) and assigned_to.strip()
                                            and len(assigned_to) <= USERNAME_MAX):
            raise CaseError(400, "INVALID", "assigned_to must be a non-empty username")
        assigned_to = assigned_to.strip() if assigned_to else None
        detected = None
        if not (reporting_period or "").strip():           # worked out from the files (owner request, 23 Nov 2026)
            detected = detect_period(data) if data[:4] == b"PK\x03\x04" else None
            if detected is None:
                raise CaseError(400, "PERIOD_NOT_DETECTED", "the reporting period could not be worked out from the files; "
                                "enter it (YYYY-MM)")
            reporting_period = detected["period"]
        if not PERIOD_RE.match(reporting_period or ""):
            raise CaseError(400, "INVALID", "the reporting period must be YYYY-MM")
        if not (zip_name or "").lower().endswith(".zip") or data[:4] != b"PK\x03\x04":
            raise CaseError(400, "NOT_A_ZIP", "the original submission must be a ZIP archive")
        if len(data) > MAX_ZIP_BYTES:
            raise CaseError(400, "FILE_TOO_LARGE", f"the ZIP exceeds {MAX_ZIP_BYTES // (1024 * 1024)} MB")
        sha = hashlib.sha256(data).hexdigest()
        target = self.zips / f"{sha}.zip"
        if not target.exists():                           # content-addressed; never overwritten
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        with self.lock:
            seq = 1 + sum(1 for r in self.refs() if r.startswith(f"RF-{reporting_period}-"))
            ref = f"RF-{reporting_period}-{seq:03d}"
            c = {"case_ref": ref, "customer_id": customer_id or f"CUST-{hashlib.sha256(customer_name.encode()).hexdigest()[:8]}",
                 "customer_name": customer_name, "reporting_period": reporting_period, "created_at": now(),
                 "zip": {"filename": Path(zip_name).name, "size": len(data), "sha256": sha},
                 "assigned_to": assigned_to,
                 "status": "WAITING", "status_history": [], "deferral": None, "runs": [], "completed": None,
                 "last_activity_at": now()}
            self._history(c, "WAITING", "original ZIP attached; Smart Parser not started")
            self._save(c)
        self._audit("CASE_CREATED", c, customer_name=customer_name, reporting_period=reporting_period,
                    **({"reporting_period_detected_from": detected["basis"]} if detected else {}),
                    zip_filename=c["zip"]["filename"], zip_sha256=sha, zip_size=len(data),
                    assigned_to=assigned_to)
        return c

    # ============================================================================================ state refresh
    def _jobs(self, pid: str | None) -> list[dict]:
        return [j for j in self.ctx.jobs.values() if pid and j.get("package_id") == pid]

    def _running(self, c: dict) -> list[dict]:
        return [j for j in self._jobs(self._pid(c)) if j["state"] in RUNNING]

    def _run_state(self, run: dict) -> tuple[str, dict | None]:
        """PROCESSING | COMPLETED | FAILED, from the run's own record and its intake job (never from timers)."""
        if run.get("failure") and not run.get("intake_job_id"):
            return "FAILED", run["failure"]
        if not run.get("intake_job_id"):
            return "PROCESSING", None                   # the run is being started (package created, ZIP staging)
        j = self.ctx.jobs.get(run["intake_job_id"])
        if j is None:
            return "FAILED", {"code": "JOB_RECORD_MISSING", "message": "the intake job record is missing", "at": now()}
        if j["state"] in RUNNING:
            return "PROCESSING", None
        if j["state"] == "failed":
            return "FAILED", {"code": "INTAKE_JOB_FAILED", "message": j.get("error"), "at": j.get("finished_at"),
                              "job_id": j["job_id"]}
        if j["state"] == "interrupted":
            return "FAILED", {"code": "INTAKE_JOB_INTERRUPTED", "message": j.get("error"), "at": j.get("finished_at"),
                              "job_id": j["job_id"]}
        errors = [f for f in j.get("files", []) if f["state"] == "error"]
        if errors:
            return "FAILED", {"code": "FILE_PROCESSING_ERROR", "at": j.get("finished_at"), "job_id": j["job_id"],
                              "message": f"{len(errors)} file(s) raised an unexpected processing error: " +
                              "; ".join(f"{f['name']}: {(f['outcome'] or {}).get('error')}" for f in errors[:5])}
        return "COMPLETED", None

    def _refresh(self, c: dict) -> dict:
        """Bring the stored case up to date with what the services and jobs actually recorded. The events recorded
        here (run failed, case completed, a requested deferral taking effect) are detected by the system, whoever
        happens to be viewing the case, so they are recorded under the system actor (Fix8 D6)."""
        with identity.acting_as_system():
            return self._refresh_inner(c)

    def _refresh_inner(self, c: dict) -> dict:
        changed = False
        for run in c["runs"]:
            st, failure = self._run_state(run)
            if st != run.get("status"):
                run["status"], run["finished_at"] = st, (failure or {}).get("at") or (now() if st != "PROCESSING" else None)
                if failure:
                    run["failure"] = failure
                changed = True
                if st == "FAILED":
                    self._audit("CASE_RUN_FAILED", c, run_id=run["run_id"], code=failure["code"],
                                message=(failure.get("message") or "")[:500])
        pid = self._pid(c)
        if c["status"] in ("IN_PROGRESS", "PENDING") and pid:
            pkg = self.ctx.svc.load(pid)
            done = [j for j in self._jobs(pid) if j["kind"] == "reconciliation" and j["state"] == "completed"
                    and j.get("snapshot_id") == pkg.active_snapshot_id and j.get("run_id")]
            if done:
                j = sorted(done, key=lambda x: x["finished_at"])[-1]
                c["completed"] = {"at": j["finished_at"], "reconciliation_run_id": j["run_id"],
                                  "snapshot_id": j["snapshot_id"], "case_status": (j.get("result") or {}).get("case_status")}
                note = "reconciliation finished" + ("; a pending deferral was superseded" if c.get("deferral") else "")
                c["deferral"] = None
                self._history(c, "COMPLETED", note)
                self._audit("CASE_COMPLETED", c, reconciliation_run_id=j["run_id"], snapshot_id=j["snapshot_id"])
                changed = True
        if c["status"] == "IN_PROGRESS" and c.get("deferral") and not self._running(c):
            self._finalise_deferral(c)
            changed = True
        if changed:
            self._save(c)
        return c

    def _on_job_finished(self, j: dict) -> None:
        with self.lock:
            for ref in self.refs():
                c = self.load(ref)
                if any(r["package_id"] == j.get("package_id") for r in c["runs"]):
                    c["last_activity_at"] = now()
                    self._save(c)
                    self._refresh(c)
        self._maybe_auto_reconcile(j)

    # 23 Nov 2026 demo feedback: once Smart Parsing passes validation with nothing left for the analyst, activation and
    # reconciliation start by themselves (no extra click), so the automatic AI investigations start as early as possible.
    # The gates are unchanged: activate() and reconcile() run exactly as for the buttons, under the identity of the
    # analyst whose action started the Smart Parser job, and their audit events carry trigger=AUTO_AFTER_SMART_PARSER.
    # RINGFENCE_AUTO_RECONCILE=off restores the manual step.
    AUTO_TRIGGER = "AUTO_AFTER_SMART_PARSER"

    def _maybe_auto_reconcile(self, j: dict) -> None:
        if os.environ.get("RINGFENCE_AUTO_RECONCILE", "on").strip().lower() in ("off", "0", "false", "no"):
            return
        if j.get("kind") not in ("intake", "resubmission") or j.get("state") != "completed":
            return
        if not (j.get("validation") or {}).get("passed"):
            return
        a = identity.current()
        if a is None or a.system:
            return                                      # only an analyst's own Smart Parser action continues by itself
        identity.start_thread(self._auto_reconcile, j["package_id"])

    def _auto_reconcile(self, package_id: str) -> None:
        try:
            with self.lock:
                own = self.owner_of(package_id)
                if own is None or not own[1]:
                    return                              # not a case package, or no longer the case's current package
                c = self._refresh(self.load(own[0]["case_ref"]))
                ref = c["case_ref"]
                if c["status"] != "IN_PROGRESS" or c.get("deferral") or self._running(c):
                    return
                if self.ctx.svc.load(package_id).active_snapshot_id:
                    return                              # already activated (by the analyst or an earlier trigger)
                p = self._progress(c)
                if p["missing_required"] or p["correction_required"] or p["awaiting_review"]                         or p["files_awaiting_review"] or p["decisions_outstanding"]:
                    return                              # something still needs the analyst: keep the manual step
                act = self.activate(ref, True, trigger=self.AUTO_TRIGGER)
                if not act.get("activated"):
                    return
                out = self.reconcile(ref, trigger=self.AUTO_TRIGGER)
            rj = self.ctx.jobs.get(out.get("job_id") or "")
            a = identity.current()
            if rj is not None and a is not None:        # who started it: AUTO_INVESTIGATION authorised_by (as api.py)
                rj["requested_by"] = a.user
                try:
                    self.ctx._save_job(rj)
                except OSError:
                    pass
        except Exception:                               # never breaks the job; the manual button still works
            import traceback
            traceback.print_exc()

    # ============================================================================================ lifecycle
    def _active(self, exclude: str | None = None) -> dict | None:
        for ref in self.refs():
            if ref == exclude:
                continue
            c = self._refresh(self.load(ref))
            if c["status"] == "IN_PROGRESS":
                return c
        return None

    def _claim_slot(self, c: dict) -> None:
        other = self._active(exclude=c["case_ref"])
        if other is not None:
            extra = " (its deferral is waiting for a running operation to finish)" if other.get("deferral") else ""
            raise CaseError(409, "ACTIVE_CASE_EXISTS", f"case {other['case_ref']} ({other['customer_name']}) is in "
                            f"progress{extra}; defer it before starting or resuming another case")

    def start(self, ref: str) -> dict:
        with self.lock:
            c = self._refresh(self.load(ref))
            if c["status"] != "WAITING":
                raise CaseError(409, "CASE_STATE", f"{ref} is {c['status']}: only a WAITING case can be started "
                                "(a PENDING case is resumed)")
            self._claim_slot(c)
            self._history(c, "IN_PROGRESS", "Smart Parsing started by the analyst")
            c["started"] = {"by": self.ctx.reviewer.reviewer_id, "at": now()}
            self._save(c)
            self._audit("CASE_STARTED", c)
            self._begin_run(c, retry_of=None)
            return self.detail(ref)

    def _begin_run(self, c: dict, retry_of: str | None) -> dict:
        """A run from stage one: a NEW package, the stored original ZIP staged again, one intake job over every entry."""
        n = len(c["runs"]) + 1
        run = {"run_id": f"RUN-{c['case_ref'][3:]}-{n:02d}-{uuid.uuid4().hex[:6]}", "run_no": n, "package_id": None,
               "started_at": now(), "started_by": self.ctx.reviewer.reviewer_id, "intake_job_id": None,
               "status": "PROCESSING", "finished_at": None, "failure": None, "retry_of": retry_of,
               "evidence_source": "ORIGINAL_ZIP", "staged_entries": 0, "skipped_entries": [],
               "unreadable_entries": []}
        with self.ctx.lock:
            pkg = self.ctx.svc.create_package(c["reporting_period"])
        run["package_id"] = pkg.package_id
        c["runs"].append(run)
        self._save(c)
        started = False
        try:
            data = (self.zips / f"{c['zip']['sha256']}.zip").read_bytes()
            if hashlib.sha256(data).hexdigest() != c["zip"]["sha256"]:
                raise ValueError("ZIP_INTEGRITY: the stored original ZIP no longer matches its SHA-256")
            # Whole-archive problems raise here (O6: technical failure, nothing staged). A single unreadable member is
            # isolated by stage(): never staged, recorded on the run, and every other member is processed normally.
            entries = self.ctx.stage(c["zip"]["filename"], data)
            items = [{"staging_id": e["staging_id"]} for e in entries if e.get("staging_id")]
            run["skipped_entries"] = [e["name"] for e in entries if e.get("skipped")]
            run["unreadable_entries"] = [{k: e.get(k) for k in ("name", "size", "compressed_size", "error_kind", "error")}
                                         for e in entries if e.get("unreadable")]
            run["staged_entries"] = len(items)
            self._save(c)
            started = True
            self._audit("CASE_RUN_STARTED", c, **self._run_started_details(c, run, retry_of))
            if not items and run["unreadable_entries"]:
                raise ValueError(f"ZIP_UNREADABLE: none of the {len(run['unreadable_entries'])} file(s) in the ZIP "
                                 "could be read: " + "; ".join(u["error"] for u in run["unreadable_entries"][:5]))
            if not items:
                raise ValueError("EMPTY_ZIP: the ZIP contains no processable files")
            j = self.ctx.start_intake(pkg.package_id, items)
            run["intake_job_id"] = j["job_id"]
        except Exception as exc:                                    # a failed run is kept, never hidden
            if not started:
                self._audit("CASE_RUN_STARTED", c, **self._run_started_details(c, run, retry_of))
            msg = str(exc)
            head = msg.split(":", 1)[0].strip()
            run["status"], run["finished_at"] = "FAILED", now()
            run["failure"] = {"code": head if head.replace("_", "").isalpha() and head.isupper() else "RUN_FAILED",
                              "message": msg[:800], "at": now(), "stage": "read"}
            self._audit("CASE_RUN_FAILED", c, run_id=run["run_id"], code=run["failure"]["code"], message=msg[:500])
        c["last_activity_at"] = now()
        self._save(c)
        return run

    @staticmethod
    def _run_started_details(c: dict, run: dict, retry_of: str | None) -> dict:
        """CASE_RUN_STARTED details. The read result of the original ZIP is included: staged / skipped counts and every
        isolated unreadable member (name, central-directory size, exact error, original ZIP SHA-256). There is no
        dedicated ZIP_MEMBER_UNREADABLE event type, so the isolation is recorded here (review/audit.py unchanged)."""
        return {"run_id": run["run_id"], "run_no": run["run_no"], "retry_of": retry_of,
                "evidence_source": "ORIGINAL_ZIP", "zip_sha256": c["zip"]["sha256"],
                "staged_entries": run.get("staged_entries", 0), "skipped_entries": len(run.get("skipped_entries") or []),
                "unreadable_members": [{"name": u["name"], "size": u.get("size"), "error_kind": u.get("error_kind"),
                                        "error": u.get("error"), "original_zip_sha256": c["zip"]["sha256"]}
                                       for u in run.get("unreadable_entries") or []]}

    def defer(self, ref: str) -> dict:
        with self.lock:
            c = self._refresh(self.load(ref))
            if c["status"] != "IN_PROGRESS":
                raise CaseError(409, "CASE_STATE", f"{ref} is {c['status']}: only the case in progress can be deferred")
            if c.get("deferral"):
                return self.detail(ref)
            running = self._running(c)
            if running:                           # never interrupted: completed when the last job ends (O9: a finished
                c["deferral"] = {"requested_at": now(), "requested_by": self.ctx.reviewer.reviewer_id,
                                 "waiting_for": [                            # reconciliation supersedes it)
                    {"job_id": j["job_id"], "kind": j["kind"], "state": j["state"]} for j in running]}
                c["last_activity_at"] = now()
                self._save(c)
                self._audit("CASE_DEFERRAL_REQUESTED", c, waiting_for=[j["job_id"] for j in running])
            else:
                with self.ctx.lock:               # no job: a synchronous service call in progress finishes first
                    self._finalise_deferral(c)
                    self._save(c)
            return self.detail(ref)

    def _finalise_deferral(self, c: dict) -> None:
        requested = (c.get("deferral") or {}).get("requested_at")
        c["deferral_requested_by"] = (c.get("deferral") or {}).get("requested_by")
        c["deferral"] = None
        c["deferred_at"] = now()
        self._history(c, "PENDING", "deferred by the analyst" + (f" (requested {requested}; the running operation "
                                                                  "finished first)" if requested else ""))
        snap = self._progress(c)
        self._audit("CASE_DEFERRED", c, requested_at=requested,
                    requested_by=(c.get("deferral_requested_by") or None),
                    progress={k: snap.get(k) for k in ("decisions_outstanding", "decisions_made", "files_awaiting_review")})

    def resume(self, ref: str) -> dict:
        with self.lock:
            c = self._refresh(self.load(ref))
            if c["status"] != "PENDING":
                raise CaseError(409, "CASE_STATE", f"{ref} is {c['status']}: only a PENDING case can be resumed")
            self._claim_slot(c)
            self._history(c, "IN_PROGRESS", "resumed by the analyst")
            self._save(c)
            self._audit("CASE_RESUMED", c)
            return self.detail(ref)

    def retry(self, ref: str, confirm: bool) -> dict:
        with self.lock:
            c = self._refresh(self.load(ref))
            self._require_active(c, allow_failed_run=True)
            run = c["runs"][-1] if c["runs"] else None
            if run is None or run["status"] != "FAILED":
                raise CaseError(409, "RUN_NOT_FAILED", "Retry from beginning is only available when the latest Smart "
                                "Parser run has failed")
            if confirm is not True:
                raise CaseError(400, "CONFIRMATION_REQUIRED", "a fresh retry needs an explicit confirmation")
            # Owner decision O1 (APPROVED, option A): the retry processes the ORIGINAL stored ZIP only. Evidence uploaded
            # into the failed run is NOT carried forward (it stays in the failed run's read-only history) and must be
            # uploaded again into the new run; it is listed here so the analyst knows what to re-upload.
            not_carried = [{"job_id": j["job_id"], "kind": j["kind"],
                            "files": [{"name": f["name"], "category": (f.get("outcome") or {}).get("evidence_category")
                                       or (j.get("resubmission") or {}).get("category") or f.get("declared_category")}
                                      for f in j.get("files", [])]}
                           for j in self._jobs(run["package_id"])
                           if j["kind"] in ("intake", "resubmission") and j["job_id"] != run.get("intake_job_id")]
            self._audit("CASE_RETRY_REQUESTED", c, failed_run_id=run["run_id"], evidence_source="ORIGINAL_ZIP",
                        not_carried_forward=not_carried)
            new = self._begin_run(c, retry_of=run["run_id"])
            new["not_carried_forward"] = not_carried
            self._save(c)
            return self.detail(ref)

    # ============================================================================================ guards
    def _require_active(self, c: dict, allow_failed_run: bool = False, allow_running: bool = False) -> None:
        if c["status"] == "COMPLETED":
            raise CaseError(409, "CASE_COMPLETED", f"{c['case_ref']} is COMPLETED: no further changes, correction or "
                            "reactivation are possible after reconciliation")
        if c["status"] != "IN_PROGRESS":
            raise CaseError(409, "CASE_NOT_ACTIVE", f"{c['case_ref']} is {c['status']}: "
                            + ("start Smart Parsing first" if c["status"] == "WAITING" else "resume the case first"))
        if c.get("deferral"):
            raise CaseError(409, "CASE_DEFERRING", f"{c['case_ref']} is being deferred; no new operation can start")
        run = c["runs"][-1] if c["runs"] else None
        if run and run["status"] == "FAILED" and not allow_failed_run:
            raise CaseError(409, "RUN_FAILED", f"the latest Smart Parser run {run['run_id']} failed: retry it from the "
                            "beginning")
        if not allow_running and self._running(c):
            raise CaseError(409, "OPERATION_RUNNING", "an operation is still running on this case; wait for it")

    def owner_of(self, package_id: str) -> tuple[dict, bool] | None:
        """(case, is_current_package) for a package that belongs to a case, else None."""
        for ref in self.refs():
            c = self.load(ref)
            for i, r in enumerate(c["runs"]):
                if r["package_id"] == package_id:
                    return c, i == len(c["runs"]) - 1
        return None

    def guard_package(self, package_id: str, op: str) -> None:
        """Guard for the generic /api/packages and /api/review mutations: a package owned by a case may only change
        through an active case, on its current run, before reconciliation. Packages without a case are unaffected."""
        with self.lock:
            own = self.owner_of(package_id)
            if own is None:
                return
            c, current = own
            self._guard_owned(c, current, package_id, op)

    def _guard_owned(self, c: dict, current: bool, package_id: str, op: str) -> None:
        if not current:
            raise CaseError(409, "PACKAGE_SUPERSEDED", f"{package_id} belongs to an earlier run of {c['case_ref']} and "
                            "is kept read-only as history")
        self._require_active(self._refresh(c), allow_running=op in ("review",))
        if op in ("intake", "resubmit") and self.ctx.svc.load(package_id).active_snapshot_id:
            raise CaseError(409, "PACKAGE_LOCKED", "the package is activated: no further evidence can be added")

    # ============================================================================================ analyst actions
    def _current(self, ref: str, **kw) -> tuple[dict, str]:
        c = self._refresh(self.load(ref))
        self._require_active(c, **kw)
        return c, self._pid(c)

    def upload_evidence(self, ref: str, staging_id: str, category: str | None) -> dict:
        with self.lock:
            c, pid = self._current(ref)
            pkg = self.ctx.svc.load(pid)
            if pkg.active_snapshot_id:
                raise CaseError(409, "PACKAGE_LOCKED", "the package is activated: no further evidence can be added")
            if category is not None and self.ctx.reg.get(category) is None:
                raise CaseError(400, "INVALID", f"unknown evidence category {category}")
            latest = pkg.latest(category) if category else None
            if category and latest is not None:
                if latest.version_status not in NEEDS_NEW_VERSION:
                    raise CaseError(409, "EVIDENCE_NOT_ACCEPTED", f"{category} v{latest.version_number} is "
                                    f"{latest.version_status}: it does not await a corrected file")
                reason = REASON.format(action="UPLOAD_CORRECTED_FILE")
                self._audit("ANALYST_EVIDENCE_UPLOADED", c, staging_id=staging_id, evidence_category=category,
                            kind="correction", replaces=latest.file_version_id)
                j = self.ctx.start_intake(pid, [{"staging_id": staging_id}], {"category": category, "reason": reason})
            else:
                self._audit("ANALYST_EVIDENCE_UPLOADED", c, staging_id=staging_id, evidence_category=category,
                            kind="missing")
                j = self.ctx.start_intake(pid, [{"staging_id": staging_id, "declared_category": category}])
            c["last_activity_at"] = now()
            self._save(c)
            return {"job_id": j["job_id"], "case": self.detail(ref)}

    def review(self, ref: str, vid: str) -> dict:
        with self.lock:
            return self._review(self._refresh(self.load(ref)), vid)

    def _review(self, c: dict, vid: str) -> dict:
        ref = c["case_ref"]
        pid = self._pid(c)
        if pid is None or vid not in self.ctx.svc.load(pid).versions:
            raise CaseError(404, "NOT_FOUND", f"{vid} is not a file version of {ref}'s current run")
        d = review_api.review_detail(self.ctx.svc, pid, vid)
        prof = {}
        try:
            prof = {x["source_index"]: x for x in self.ctx.column_profile(pid, vid).get("columns", [])}
        except Exception:
            pass
        fields = {f["name"]: f for f in d["canonical_fields"]}
        mech = d.get("mechanism")
        schema = self.ctx.reg.get(d["evidence_category"])
        values = self._map_values(pid, vid)
        rows = []
        for r in d["rows"]:
            att = needs_attention(r, mech)
            f = fields.get((r.get("decision") or {}).get("canonical_field") or r.get("suggested_field") or "")
            dup = bool(r.get("duplicate_claim") or r.get("same_header_positions"))
            # Fix8 D4: an AI proposal onto an ambiguous / interchangeable financial field needs an explicit choice
            clar = financial.clarification(schema, r) if att else None
            acts = []
            if att and d["editable"]:
                if clar:
                    acts.append("CLARIFY")
                else:
                    if r.get("suggested_field"):
                        acts.append("MAP")
                    # a column whose header deterministically matches a field (canonical name or case/whitespace/alias
                    # variant) can only be mapped to that field, ignored, or the file rejected (RULE_CONTRADICTION)
                    if not (mech == "column_review_case" and r.get("suggested_field")
                            and r.get("suggestion_basis") in ("deterministic", "diagnostic_name_match")):
                        acts.append("CHANGE")
                if mech == "column_review_case":
                    acts.append("IGNORE")
            dec = r.get("decision")
            rows.append({**{k: r.get(k) for k in ("source_index", "source_position", "source_header", "suggested_field",
                                                   "suggestion_basis", "proposal_assessment", "validation", "note")},
                         "needs_attention": att, "duplicate": dup,
                         "decided": bool(dec) and dec.get("action") not in (None, "DETERMINISTIC"),
                         "decision": None if not dec or dec.get("action") == "DETERMINISTIC" else
                         {"action": {"CHOOSE_DUPLICATE_SOURCE": "MAP", "APPROVE": "MAP", "IGNORE_COLUMN": "IGNORE",
                                     "LEAVE_UNMAPPED": "LEAVE_UNRESOLVED"}.get(dec["action"], dec["action"]),
                          "backend_action": dec["action"], "canonical_field": dec.get("canonical_field"),
                          "at": dec.get("at"), "reviewer": dec.get("reviewer")},
                         "field_type": f["type"] if f else None, "field_required": f["required"] if f else None,
                         "financial": bool(f and f["type"] in ("amount", "signed")),
                         "samples": (prof.get(r["source_index"]) or {}).get("samples", []),
                         "available_actions": acts,
                         # Fix8 D1/D4: where the suggestion comes from, what the validator said, why, and checks
                         "proposal_source": self._map_source(r, d), "proposal_class": r.get("validation"),
                         "proposal_explanation": r.get("proposal_explanation"),
                         "proposal_alternatives": r.get("proposal_alternatives") or [],
                         "decision_source": None if not dec or dec.get("action") == "DETERMINISTIC" else
                         ("analyst" if dec.get("action") == "CHANGE" else self._map_source(r, d)),
                         "clarification_required": bool(clar), "clarification_reason": clar,
                         "value_check": self._map_value_check(schema, r, values) if att else None})
        attention = [r for r in rows if r["needs_attention"]]
        remaining = [r for r in attention if not r["decided"]]
        try:
            fin = review_api.financial_view(self.ctx.svc, pid, vid)
        except Exception as exc:                                   # shown, never hidden
            fin = {"relationships_defined": None, "error": f"{type(exc).__name__}: {exc}"[:300]}
        extra = {"proposal_id": d.get("proposal_id"), "proposal_provider_id": d.get("proposal_provider_id"),
                 "unresolved_headers": d.get("unresolved_headers") or [], "financial_checks": fin,
                 "clarifications_required": sum(1 for r in remaining if r["clarification_required"])}
        return {"case_ref": ref, "package_id": pid, "file_version_id": vid, "evidence_category": d["evidence_category"],
                "category_title": d["category_title"], "original_filename": d["original_filename"],
                "version_number": d["version_number"], "version_status": d["version_status"],
                "review_kind": d.get("review_kind"), "review_reason": d.get("review_reason"),
                "editable": d["editable"], "canonical_fields": d["canonical_fields"],
                "rows": rows, "counts": {"attention": len(attention), "decided": len(attention) - len(remaining),
                                         "remaining": len(remaining), "recognised": len(rows) - len(attention)},
                "required_not_covered": d.get("summary", {}).get("required_not_covered", []),
                "can_confirm": d["editable"] and not remaining,
                "file_actions": ["CONFIRM", "REJECT"] if d["editable"] else [], **extra}

    # ---------------------------------------------------------------------------------------- Fix8 mapping helpers
    def _map_values(self, pid: str, vid: str) -> dict[int, list[str]]:
        """Every cell value per source column of the stored original (SHA-256 verified); local only."""
        v = self.ctx.svc.load(pid).versions[vid]
        try:
            data = self.ctx.svc.evidence.read_original(v.source_sha256)
            if data is None or hashlib.sha256(data).hexdigest() != v.source_sha256 or data[:5] == b"%PDF-":
                return {}
            return financial.read_columns(data, v.original_filename)[1]
        except Exception:
            return {}

    @staticmethod
    def _map_source(r: dict, d: dict) -> str | None:
        b = r.get("suggestion_basis")
        if b == "proposal":
            prov = d.get("proposal_provider_id") or ""
            return "AI (recorded test fixture)" if prov.startswith("recorded_stub") or not prov and \
                d.get("review_kind") == "PROPOSAL_REVIEW" else "AI"
        if b in ("deterministic", "diagnostic_name_match"):
            return "deterministic"
        return None

    @staticmethod
    def _map_value_check(schema, r: dict, values: dict[int, list[str]]) -> dict | None:
        """The field rule of the column's current target (decision, else suggestion) over EVERY value of the column."""
        from ..classify.content_check import _value_error
        fld = (r.get("decision") or {}).get("canonical_field") or r.get("suggested_field")
        f = schema.field(fld) if fld else None
        vals = values.get(r["source_index"])
        if f is None or vals is None:
            return None
        bad = [x for x in vals if x != "" and _value_error(f.source_type, f.constraints.pattern,
                                                            f.constraints.allowed_values, x)]
        return {"field": fld, "rows": len(vals), "failed": len(bad), "empty": sum(1 for x in vals if x == ""),
                "status": "PASS" if not bad else "FAIL", "examples": bad[:3]}

    def decide(self, ref: str, vid: str, action: str, source_index: int, canonical_field: str | None) -> dict:
        with self.lock:
            c, pid = self._current(ref, allow_running=False)
            d = self.review(ref, vid)
            row = next((r for r in d["rows"] if r["source_index"] == source_index), None)
            if row is None:
                raise CaseError(400, "INVALID", f"column index {source_index} is not in this file")
            if action not in row["available_actions"]:
                raise CaseError(400, "UNSUPPORTED_ACTION", f"{action} is not available for column "
                                f"#{source_index + 1} ({', '.join(row['available_actions']) or 'no decision needed'})")
            reason = REASON.format(action=action)
            if action == "MAP" and row["duplicate"] and d["review_kind"] != "PROPOSAL_REVIEW":
                backend, field, others = "CHOOSE_DUPLICATE_SOURCE", None, REASON.format(action="MAP (other claimants "
                                                                                             "ignored)")
            elif action == "MAP":
                backend, field, others = "MAP", None, None
            elif action in ("CHANGE", "CLARIFY"):
                if not canonical_field:
                    raise CaseError(400, "INVALID", f"{action} needs the canonical field (an explicit choice)")
                backend, field, others = "CHANGE", canonical_field, None
            else:
                backend, field, others = "IGNORE_COLUMN", None, None
            with self.ctx.lock:
                review_api.decide(self.ctx.svc, self.ctx.reviewer, pid, vid, backend, source_index, reason, field, others)
                if action == "CLARIFY":
                    # Fix8 D4: recorded after the decision succeeded (the explicit choice and what was proposed)
                    after = self._review(c, vid)
                    self._audit("ANALYST_MAPPING_CLARIFIED", c, file_version_id=vid, source_index=source_index,
                                source_header=row["source_header"], proposed_field=row["suggested_field"],
                                proposal_class=row.get("proposal_class"), chosen_field=canonical_field,
                                clarification_reason=row.get("clarification_reason"),
                                accepted_as_proposed=canonical_field == row["suggested_field"],
                                financial_checks=[{k: r.get(k) for k in ("relationship", "status", "detail")}
                                                  for r in (after.get("financial_checks") or {}).get("current", [])])
            c["last_activity_at"] = now()
            self._save(c)
            return self.review(ref, vid)

    def confirm_review(self, ref: str, vid: str) -> dict:
        """File-level confirmation: the recognised (exact canonical) columns of a column-review case are confirmed with
        the file, the review is completed through the existing endpoint, and package validation runs."""
        with self.lock:
            c, pid = self._current(ref)
            d = self.review(ref, vid)
            if not d["editable"]:
                raise CaseError(409, "REVIEW_STATE", f"{vid} is {d['version_status']}: nothing to confirm")
            if d["counts"]["remaining"]:
                raise CaseError(409, "DECISIONS_OUTSTANDING", f"{d['counts']['remaining']} column(s) still need a "
                                "decision")
            with self.ctx.lock:
                # Fix8 D2: pre-validate the whole effective mapping, then apply atomically (review_api.confirm restores
                # the review state on any failure); ANALYST_REVIEW_CONFIRMED is recorded only after it took effect.
                try:
                    res = review_api.confirm(self.ctx.svc, self.ctx.reviewer, pid, vid,
                                             REASON.format(action="CONFIRM_FILE"),
                                             REASON.format(action="CONFIRM_FILE (recognised column)"))
                except review_api.ApiError as exc:
                    self._audit("ANALYST_REVIEW_CONFIRMATION_FAILED", c, file_version_id=vid, error=exc.code,
                                reason=exc.message[:1500], problems=exc.problems[:20],
                                recognised_columns=d["counts"]["recognised"], decisions_left_unchanged=True)
                    raise CaseError(exc.status, exc.code, exc.message) from None
                self._audit("ANALYST_REVIEW_CONFIRMED", c, file_version_id=vid,
                            recognised_columns_confirmed=len(res["recognised_mapped"]),
                            recognised_positions=[i + 1 for i in res["recognised_mapped"]],
                            version_status=res["version_status"])
                self.ctx.svc.validate(pid)
            c["last_activity_at"] = now()
            self._save(c)
            return self.detail(ref)

    def reject_file(self, ref: str, vid: str) -> dict:
        with self.lock:
            c, pid = self._current(ref)
            with self.ctx.lock:
                self._audit("ANALYST_CORRECTION_REQUESTED", c, file_version_id=vid)
                review_api.reject(self.ctx.svc, self.ctx.reviewer, pid, vid,
                                  REASON.format(action="REJECT_FILE_REQUEST_CORRECTION"))
                self.ctx.svc.validate(pid)
            c["last_activity_at"] = now()
            self._save(c)
            return self.detail(ref)

    def validate(self, ref: str) -> dict:
        with self.lock:
            c, pid = self._current(ref)
            if self.ctx.svc.load(pid).active_snapshot_id:     # O5: the activated package is immutable
                raise CaseError(409, "PACKAGE_LOCKED", "the package is activated and immutable")
            with self.ctx.lock:
                self._audit("ANALYST_VALIDATION_REQUESTED", c)
                self.ctx.svc.validate(pid)
            c["last_activity_at"] = now()
            self._save(c)
            return self.detail(ref)

    def activate(self, ref: str, confirm: bool, trigger: str | None = None) -> dict:
        with self.lock:
            c, pid = self._current(ref)
            if confirm is not True:
                raise CaseError(400, "CONFIRMATION_REQUIRED", "activation needs an explicit confirmation")
            if self.ctx.svc.load(pid).active_snapshot_id:
                raise CaseError(409, "ALREADY_ACTIVATED", "the package is already activated (one activation per case)")
            with self.ctx.lock:
                self._audit("ANALYST_ACTIVATION_REQUESTED", c, **({"trigger": trigger} if trigger else {}))
                a = self.ctx.svc.activate(pid)
            c["last_activity_at"] = now()
            self._save(c)
            return {"activated": a.activated, "reason": a.reason,
                    "snapshot_id": a.snapshot.snapshot_id if a.snapshot else None, "case": self.detail(ref)}

    def reconcile(self, ref: str, trigger: str | None = None) -> dict:
        with self.lock:
            c, pid = self._current(ref)
            sid = self.ctx.svc.load(pid).active_snapshot_id
            if not sid:
                raise CaseError(409, "NOT_ACTIVATED", "activate the package before reconciliation")
            self._audit("ANALYST_RECONCILIATION_REQUESTED", c, snapshot_id=sid, **({"trigger": trigger} if trigger else {}))
            j = self.ctx.start_reconciliation(pid, sid)
            c["last_activity_at"] = now()
            self._save(c)
            return {"job_id": j["job_id"], "case": self.detail(ref)}

    # ============================================================================================ views
    def _progress(self, c: dict) -> dict:
        reg = self.ctx.reg
        cats = reg.defined()
        out = {"categories_total": len(cats), "required_total": sum(1 for s in cats if s.requirement == "REQUIRED"),
               "categories_processed": 0, "categories_validated": 0, "files_awaiting_review": 0,
               "decisions_outstanding": 0, "decisions_made": 0, "missing_required": [], "correction_required": [],
               "awaiting_review": [], "refused_uploads": [], "validation": {"state": "NOT_RUN"}, "activation": None,
               "reconciliation": {"state": "NOT_RUN"}, "current_operation": None, "unreadable_members": [],
               "last_activity_at": c.get("last_activity_at"), "summary": []}
        pid = self._pid(c)
        if pid is None:
            out["summary"] = ["Smart Parser not started"]
            return out
        svc = self.ctx.svc
        pkg = svc.load(pid)
        for s in cats:
            slot = pkg.evidence_files.get(s.category)
            v = pkg.latest(s.category) if slot and slot.version_ids else None
            if v is None:
                if s.requirement == "REQUIRED":
                    out["missing_required"].append({"category": s.category, "title": s.title})
                continue
            out["categories_processed"] += 1
            if v.version_status in ("VALIDATED", "ACTIVE"):
                out["categories_validated"] += 1
            elif v.version_status in NEEDS_NEW_VERSION:
                out["correction_required"].append({"category": s.category, "title": s.title,
                                                   "file_version_id": v.file_version_id, "version_status": v.version_status,
                                                   "version_number": v.version_number,
                                                   "reason": self._failure_reason(v)[:300],
                                                   "required": s.requirement == "REQUIRED"})
            elif v.version_status == "REVIEW_REQUIRED":
                out["files_awaiting_review"] += 1
                try:
                    rv = self._review(c, v.file_version_id)
                    out["decisions_outstanding"] += rv["counts"]["remaining"]
                    out["decisions_made"] += rv["counts"]["decided"]
                    remaining = rv["counts"]["remaining"]
                    total, cols = rv["counts"]["attention"], [r["source_header"] for r in rv["rows"]
                                                              if r["needs_attention"] and not r["decided"]]
                except Exception:
                    remaining, total, cols = None, None, []
                out["awaiting_review"].append({"category": s.category, "title": s.title,
                                               "file_version_id": v.file_version_id, "remaining": remaining,
                                               "total": total, "remaining_columns": cols,
                                               "version_number": v.version_number,
                                               "original_filename": v.original_filename})
        # uploads the service refused before assigning a slot (e.g. a ZIP entry whose category could not be identified):
        # never counted as processed; the analyst re-uploads them with a declared category
        out["refused_uploads"] = [{k: u.get(k) for k in ("filename", "source_sha256", "evidence_category", "reason", "at")}
                                  for u in pkg.unassigned_uploads]
        running = self._running(c)
        if running:
            j = running[0]
            files = j.get("files") or []
            out["current_operation"] = {"kind": j["kind"], "job_id": j["job_id"], "state": j["state"],
                                        "files_total": len(files),
                                        "files_processed": sum(1 for f in files if f["state"] in ("done", "error")),
                                        "validation_running": bool(j.get("validation_started_at")) and not j.get("validation")}
        if pkg.validation_results:
            res = pkg.validation_results[-1]
            last_change = max((h.at for v in pkg.versions.values() for h in v.status_history), default="")
            out["validation"] = {"state": "PASSED" if res.passed else "FAILED", "at": res.at,
                                 "failed_checks": [ch.check_id for ch in res.checks if not ch.passed],
                                 "current": res.at >= last_change}
        if out["current_operation"] and out["current_operation"]["validation_running"]:
            out["validation"] = {**out["validation"], "state": "RUNNING"}
        if pkg.active_snapshot_id:
            out["activation"] = {"snapshot_id": pkg.active_snapshot_id}
        # Members of the original ZIP that could not be read in the current run (isolated; never staged). The corrected
        # file is uploaded through the normal upload path and its category is decided by its content (O7); the missing
        # required categories are shown only as a hint. Open while required evidence is missing and before activation.
        missing_hint = ", ".join(f"{m['category']} {m['title']}" for m in out["missing_required"])
        open_ = bool(out["missing_required"]) and not out["activation"]
        out["unreadable_members"] = [
            {"name": u["name"], "size": u.get("size"), "error_kind": u.get("error_kind"), "error": u.get("error"),
             "original_zip_sha256": c["zip"]["sha256"], "open": open_,
             "hint": (f"Hint only (not used to accept the file): required evidence now missing: {missing_hint}"
                      if missing_hint else None)}
            for u in (c["runs"][-1].get("unreadable_entries") or [])]
        rj = sorted([j for j in self._jobs(pid) if j["kind"] == "reconciliation"], key=lambda x: x["created_at"])
        if rj:
            j = rj[-1]
            out["reconciliation"] = {"state": {"queued": "RUNNING", "running": "RUNNING", "completed": "COMPLETED"}
                                     .get(j["state"], "FAILED"), "job_id": j["job_id"], "run_id": j.get("run_id"),
                                     "case_status": (j.get("result") or {}).get("case_status"),
                                     "exceptions": (j.get("result") or {}).get("exceptions"), "error": j.get("error")}
        s = out["summary"]
        s.append(f"{out['categories_processed']} of {out['categories_total']} evidence categories processed")
        if out["current_operation"]:
            op = out["current_operation"]
            s.append("Validation running" if op["validation_running"] else
                     f"{op['kind'].capitalize()} running: {op['files_processed']} of {op['files_total']} files")
        if out["files_awaiting_review"]:
            s.append(f"{out['files_awaiting_review']} file(s) awaiting mapping review, {out['decisions_outstanding']} "
                     "decision(s) outstanding")
        um = out["unreadable_members"]
        if um:
            kinds = ", ".join(sorted({READ_ERROR_TEXT.get(u["error_kind"], "read error") for u in um}))
            n = len(um)
            s.append(f"{n} file{'' if n == 1 else 's'} in the original ZIP could not be read ({kinds})" +
                     (": upload a corrected file" if um[0]["open"] else
                      "; the package is activated" if out["activation"] else "; no required evidence is missing now"))
        if out["missing_required"]:
            s.append(f"{len(out['missing_required'])} required evidence categor{'y' if len(out['missing_required']) == 1 else 'ies'} missing")
        if out["refused_uploads"] and out["missing_required"]:      # history stays listed in the evidence view
            s.append(f"{len(out['refused_uploads'])} uploaded file(s) not accepted (see the reasons)")
        if out["correction_required"]:
            s.append(f"{len(out['correction_required'])} file(s) need a corrected version")
        v = out["validation"]
        if v["state"] in ("PASSED", "FAILED") and not out["current_operation"]:
            s.append(f"Validation {'passed' if v['state'] == 'PASSED' else 'failed: ' + ', '.join(v['failed_checks'])}"
                     + ("" if v.get("current", True) else " (out of date)"))
        if out["activation"]:
            s.append(f"Activated as {out['activation']['snapshot_id']}")
        r = out["reconciliation"]
        if r["state"] != "NOT_RUN":
            s.append(f"Reconciliation {r['state'].lower()}" + (f": {r['case_status']}" if r.get("case_status") else ""))
        return out

    @staticmethod
    def _failure_reason(v) -> str:
        """Why a file needs a corrected version: the failed hand-off checks when they exist (e.g. a malformed row),
        otherwise the most recent recorded reason. Recorded text only; nothing is inferred."""
        failed = [ch for ch in ((v.handoff.checks if v.handoff else None) or []) if not ch.get("passed")]
        if failed:
            return "; ".join(f"{ch.get('name')}: {ch.get('detail')}" for ch in failed)
        return (v.reasons or [""])[-1]

    def _actions(self, c: dict, p: dict) -> dict:
        """Which analyst actions are available now, with the reason when not - computed here, never in the browser."""
        st = c["status"]
        run = c["runs"][-1] if c["runs"] else None
        deferring = bool(c.get("deferral"))
        running = bool(p.get("current_operation"))
        active = st == "IN_PROGRESS" and not deferring
        failed = bool(run and run["status"] == "FAILED")
        other = self._active(exclude=c["case_ref"]) if st in ("WAITING", "PENDING") else None

        from . import authz
        denied = authz.case_access(c)["reason"]          # Fix8 D7: not the owner (reads stay open)

        def a(ok, why):
            if denied:
                return {"enabled": False, "reason": denied}
            return {"enabled": bool(ok), "reason": None if ok else why}
        idle_reason = ("a case action needs the case IN_PROGRESS" if not active else
                       "the latest run failed: retry it from the beginning" if failed else
                       "an operation is running" if running else None)
        idle = active and not failed and not running
        pv = p.get("validation") or {}
        return {
            "start": a(st == "WAITING" and other is None, f"case {other['case_ref']} is in progress" if other else
                       f"case is {st}"),
            "defer": a(st == "IN_PROGRESS" and not deferring, "deferral already requested" if deferring else f"case is {st}"),
            "resume": a(st == "PENDING" and other is None, f"case {other['case_ref']} is in progress" if other else
                        f"case is {st}"),
            "retry_from_beginning": a(active and failed, "only after a failed Smart Parser run" if active else idle_reason),
            "upload_evidence": a(idle and not p.get("activation"), idle_reason or "the package is activated"),
            "review": a(idle and p.get("files_awaiting_review", 0) > 0, idle_reason or "no file awaits review"),
            "validate": a(idle and not p.get("activation"), idle_reason or "the package is activated"),
            "activate": a(idle and not p.get("activation") and pv.get("state") == "PASSED" and pv.get("current"),
                          idle_reason or ("already activated" if p.get("activation") else
                                          "the latest validation must pass and be current")),
            "reconcile": a(idle and p.get("activation") and self.ctx.uc042_root is not None,
                           idle_reason or ("activate the package first" if not p.get("activation") else
                                           "the reconciliation engine is not configured")),
        }

    def summary(self, c: dict) -> dict:
        p = self._progress(c)
        run = c["runs"][-1] if c["runs"] else None
        return {k: c[k] for k in ("case_ref", "customer_id", "customer_name", "reporting_period", "created_at",
                                   "status", "last_activity_at", "zip")} | {
            "assigned_to": c.get("assigned_to"),          # None for cases registered before assignment existed
            "assignment_history": c.get("assignment_history") or [],
            "access": self._access(c),                    # Fix8 D7: the viewer's access (owner / supervisor / reason)
            "deferring": bool(c.get("deferral")), "deferral": c.get("deferral"), "deferred_at": c.get("deferred_at"),
            "started": c.get("started"), "completed": c.get("completed"),
            "current_run": None if run is None else {k: run.get(k) for k in ("run_id", "run_no", "status", "package_id",
                                                                            "started_at", "finished_at", "failure")},
            "runs_total": len(c["runs"]), "failed_runs": sum(1 for r in c["runs"] if r["status"] == "FAILED"),
            "revision": c.get("revision", 0), "status_since": (c["status_history"] or [{}])[-1].get("at"),
            "other_cases_for_period": sum(1 for r in self.refs() if r != c["case_ref"]
                                          and r.startswith(f"RF-{c['reporting_period']}-")),
            "steps": self._steps(c, p), "progress": p}

    STEP_KEYS = ("smart_parser", "review", "validation", "activation", "reconciliation")

    def _steps(self, c: dict, p: dict) -> list[dict]:
        """The five case steps the frontend shows (Smart Parser, Review, Validation, Activation, Reconciliation), each
        done | current | attention | failed | paused | todo - derived here from recorded state, never in the browser."""
        run = c["runs"][-1] if c["runs"] else None
        rs = run["status"] if run else None
        v, rec = p.get("validation") or {}, p.get("reconciliation") or {}
        sp = {"PROCESSING": "current", "FAILED": "failed", "COMPLETED": "done"}.get(rs, "todo")
        parsed = rs == "COMPLETED"
        review = "todo" if not parsed else ("attention" if p.get("files_awaiting_review") else "done")
        if not parsed:
            val = "todo"
        elif v.get("state") == "RUNNING":
            val = "current"
        elif v.get("state") == "PASSED" and v.get("current", True):
            val = "done"
        elif v.get("state") in ("FAILED", "PASSED"):
            val = "attention"
        else:
            val = "todo"
        act = "done" if p.get("activation") else ("current" if val == "done" else "todo")
        recon = {"COMPLETED": "done", "RUNNING": "current", "FAILED": "failed"}.get(
            rec.get("state"), "current" if p.get("activation") else "todo")
        states = [sp, review, val, act, recon]
        if c["status"] == "PENDING":                     # deferred: the first unfinished step is shown as paused
            for i, st in enumerate(states):
                if st != "done":
                    states[i] = "paused"
                    break
        return [{"key": k, "state": st} for k, st in zip(self.STEP_KEYS, states)]

    def detail(self, ref: str) -> dict:
        with self.lock:
            return self._detail(self._refresh(self.load(ref)))

    def _detail(self, c: dict) -> dict:
        s = self.summary(c)
        pid = self._pid(c)
        pkg = self.ctx.svc.load(pid) if pid else None
        runs = []
        for r in c["runs"]:
            j = self.ctx.jobs.get(r.get("intake_job_id") or "")
            runs.append({**r, "intake_job": None if j is None else {
                "job_id": j["job_id"], "state": j["state"], "error": j.get("error"), "trace": j.get("trace"),
                "files": [{"name": f["name"], "state": f["state"], "outcome": f.get("outcome")} for f in j.get("files", [])],
                "created_at": j["created_at"], "finished_at": j.get("finished_at")}})
        p = s["progress"]
        acts = self._actions(c, p)
        other = self._active(exclude=c["case_ref"]) if c["status"] in ("WAITING", "PENDING") else None
        outstanding = {
            "mapping_decisions": [{"file_version_id": a["file_version_id"], "category": a["category"],
                                   "file_name": a["original_filename"], "version": a.get("version_number"),
                                   "outstanding": a["remaining"], "total": a.get("total"),
                                   "columns": a.get("remaining_columns", [])} for a in p["awaiting_review"]],
            "missing_categories": [{"category": m["category"], "title": m["title"],
                                    "format": (self.ctx.reg.get(m["category"]).evidence_format or "").upper()}
                                   for m in p["missing_required"]],
            "files_requiring_replacement": [{"category": x["category"], "file_version_id": x["file_version_id"],
                                             "version": x["version_number"], "version_status": x["version_status"],
                                             "cause": "COLUMN_REJECTED" if x["version_status"] == "REJECTED"
                                             else "STRUCTURE_FAILED", "detail": x["reason"]}
                                            for x in p["correction_required"]],
            "refused_uploads": p["refused_uploads"],
            "unreadable_members": [] if p["activation"] else p["unreadable_members"],   # nothing to add after O5
            "other": [{"kind": k, "detail": d} for k, d, on in (
                ("RETRY_FROM_BEGINNING", "the latest Smart Parser run failed", acts["retry_from_beginning"]["enabled"]),
                ("ACTIVATE", "validation passed: the package can be activated", acts["activate"]["enabled"]),
                ("RUN_RECONCILIATION", "the activated snapshot can be reconciled", acts["reconcile"]["enabled"]))
                if on]}
        kept = [f"{p['categories_processed']} of {p['categories_total']} evidence categories processed and kept"]
        if p["decisions_made"]:
            kept.append(f"{p['decisions_made']} mapping decision(s) saved")
        if len(c["runs"]) > 1:
            kept.append(f"{len(c['runs'])} Smart Parser runs in history ({s['failed_runs']} failed)")
        activation = None
        if pkg is not None and pkg.active_snapshot_id:
            ev = [e for e in self.ctx.events() if e["event_type"] == "ANALYST_ACTIVATION_REQUESTED"
                  and e["details"].get("case_ref") == c["case_ref"]]
            mp = self.ctx.svc.store.manifest_path(pkg.package_id, pkg.active_snapshot_id)
            activation = {"snapshot_id": pkg.active_snapshot_id,
                          "activated_by": ev[-1]["actor_id"] if ev else None, "activated_at": ev[-1]["at"] if ev else None,
                          "manifest_sha256": hashlib.sha256(mp.read_bytes()).hexdigest() if mp.is_file() else None}
        return s | {"status_history": c["status_history"], "runs": runs, "actions": acts,
                    "outstanding": outstanding, "kept": kept, "activation": activation,
                    "blocked_by": None if other is None else {k: other[k] for k in ("case_ref", "customer_name",
                                                                                      "reporting_period")},
                    "package": None if pkg is None else {
                        "package_id": pkg.package_id, "package_status": pkg.package_status,
                        "active_snapshot_id": pkg.active_snapshot_id,
                        "slots": [{"evidence_category": cat, "required": slot.required,
                                   "latest": None if not slot.version_ids else {
                                       k: getattr(pkg.versions[slot.version_ids[-1]], k) for k in (
                                           "file_version_id", "version_number", "version_status", "original_filename",
                                           "processing_status")},
                                   "versions": len(slot.version_ids)}
                                  for cat, slot in sorted(pkg.evidence_files.items())],
                        "latest_validation": None if not pkg.validation_results else {
                            "at": pkg.validation_results[-1].at, "passed": pkg.validation_results[-1].passed,
                            "checks": [ch.model_dump() for ch in pkg.validation_results[-1].checks]},
                        "jobs": [{k: j.get(k) for k in ("job_id", "kind", "state", "created_at", "finished_at", "error",
                                                        "run_id")} for j in sorted(self._jobs(pid),
                                                                                    key=lambda x: x["created_at"])]}}

    def run(self, ref: str, run_id: str) -> dict:
        from . import api as _api                          # job_view: the real 9 stages and recorded events
        with self.lock:
            d = self._detail(self._refresh(self.load(ref)))
        run = next((r for r in d["runs"] if r["run_id"] == run_id), None)
        if run is None:
            raise CaseError(404, "NOT_FOUND", f"run {run_id} of {ref}")
        j = self.ctx.jobs.get(run.get("intake_job_id") or "")
        view = _api.job_view(self.ctx, j) if j else None
        return {**run, "stages": view["stages"] if view else [], "events": view.get("events", []) if view else [],
                "llm_mode": self.ctx.llm_mode}

    def activity(self, ref: str) -> dict:
        """Every recorded event of this case: case lifecycle events and all events of every run's package (by package
        or by intake), newest first, with the chain verification of the whole log."""
        c = self.load(ref)
        pids = {r["package_id"] for r in c["runs"] if r["package_id"]}
        intakes = set()
        for pid in pids:
            intakes |= {v.intake_id for v in self.ctx.svc.load(pid).versions.values()}
        ev = [e for e in self.ctx.events() if e["details"].get("case_ref") == ref
              or e["details"].get("package_id") in pids or e.get("intake_id") in intakes]
        try:
            chain = {"verified": True, "events": self.ctx.log.verify()}
        except Exception as exc:
            chain = {"verified": False, "error": str(exc)[:300]}
        return {"case_ref": ref, "chain": chain, "status_history": c["status_history"],
                "events": [{k: e.get(k) for k in ("seq", "event_id", "event_type", "at", "actor_id", "actor_role",
                                                   "intake_id", "source_sha256")} | {"details": e.get("details", {})}
                           for e in ev][::-1]}

    def customers(self) -> list[dict]:
        out: dict = {}
        for ref in self.refs():
            c = self.load(ref)
            x = out.setdefault(c["customer_id"], {"customer_id": c["customer_id"], "customer_name": c["customer_name"],
                                                  "cases": 0, "by_status": {st: 0 for st in STATUSES}})
            x["cases"] += 1
            x["by_status"][c["status"]] += 1
        return sorted(out.values(), key=lambda x: x["customer_name"].lower())

    def customer(self, customer_id: str) -> dict:
        with self.lock:
            cases = [self.summary(self._refresh(self.load(r))) for r in self.refs()]
        mine = [x for x in cases if x["customer_id"] == customer_id]
        if not mine:
            raise CaseError(404, "NOT_FOUND", f"unknown customer {customer_id}")
        return {"customer_id": customer_id, "customer_name": mine[0]["customer_name"],
                "cases": sorted(mine, key=lambda x: (x["reporting_period"], x["created_at"]), reverse=True),
                "reconciliation_history": [{"case_ref": x["case_ref"], "reporting_period": x["reporting_period"],
                                            **(x["completed"] or {})} for x in mine if x["completed"]]}

    @staticmethod
    def _access(c: dict) -> dict:
        from . import authz
        return authz.case_access(c)

    def assign(self, ref: str, assignee: str, how: str, expected_revision=None) -> dict:
        """Record a new owner (CLAIM of an unassigned case, or a supervisor REASSIGN / supervisor claim). Who may do
        which is decided by api.py (authz); this only validates, persists and audits CASE_ASSIGNED."""
        if not (isinstance(assignee, str) and assignee.strip() and len(assignee) <= USERNAME_MAX):
            raise CaseError(400, "INVALID", "assigned_to must be a non-empty username")
        assignee = assignee.strip()
        with self.lock:
            self.check_revision(ref, expected_revision)
            c = self.load(ref)
            previous = c.get("assigned_to")
            if previous == assignee:
                return self.detail(ref)                     # idempotent: nothing recorded
            c["assigned_to"] = assignee
            c.setdefault("assignment_history", []).append({"assigned_to": assignee, "previous": previous,
                                                           "how": how, "by": identity.current_actor()[0], "at": now()})
            c["last_activity_at"] = now()
            self._save(c)
            self._audit("CASE_ASSIGNED", c, assigned_to=assignee, previous_assigned_to=previous, how=how)
            return self.detail(ref)

    def check_revision(self, ref: str, expected) -> None:
        """Stale-action guard: a mutation that names the revision it was based on is refused if the case changed."""
        if expected is None:
            return
        c = self.load(ref)
        if int(expected) != int(c.get("revision", 0)):
            raise CaseError(409, "CASE_CHANGED", "This case changed. Reload to see the latest state "
                            f"(revision {c.get('revision', 0)}, request based on {expected}).")

    def queue(self, status: str | None = None, assigned_to: str | None = None) -> dict:
        """Default order: the case in progress first, then WAITING and PENDING oldest first (by the time the original
        ZIP was attached), then COMPLETED newest first. The analyst may open and act on any case.

        `assigned_to` (optional) narrows the list and the counts to cases assigned to that username ("My cases"). The
        In Progress slot is shared by every case, so `active_case` always reports the case holding it, assigned to
        anyone or not."""
        with self.lock:
            items = [self.summary(self._refresh(self.load(r))) for r in self.refs()]
        rank = {"IN_PROGRESS": 0, "WAITING": 1, "PENDING": 1}
        open_ = sorted([x for x in items if x["status"] != "COMPLETED"],
                       key=lambda x: (rank[x["status"]], x["created_at"], x["case_ref"]))
        done = sorted([x for x in items if x["status"] == "COMPLETED"],
                      key=lambda x: ((x["completed"] or {}).get("at", ""), x["case_ref"]), reverse=True)
        items = open_ + done
        active_item = next((x for x in items if x["status"] == "IN_PROGRESS"), None)
        if assigned_to is not None:
            items = [x for x in items if x.get("assigned_to") == assigned_to]
        counts = {s: sum(1 for x in items if x["status"] == s) for s in STATUSES}
        if status:
            if status not in STATUSES:
                raise CaseError(400, "INVALID", f"status must be one of {STATUSES}")
            items = [x for x in items if x["status"] == status]
        return {"items": items, "counts": counts, "active_case_ref": active_item["case_ref"] if active_item else None,
                "active_case": None if not active_item else {k: active_item[k] for k in (
                    "case_ref", "customer_name", "reporting_period", "deferring")},
                "assigned_to_filter": assigned_to,
                "ordering": "in progress first; then WAITING and PENDING oldest first; then COMPLETED newest first"}
