"""JSON API of the browser application. Every handler either calls an EXISTING service operation (PackageService,
review_api, run_reconciliation via a job) or reads state those services already persisted. No business rule is
re-implemented here; derived values are counts over stored records, labelled as such."""
from __future__ import annotations

import base64
import json
from collections import Counter

from ..packages import review_api
from ..packages.models import NEEDS_NEW_VERSION
from ..packages.service import PackageError
from ..packages.store import PackageStoreError
from ..review.audit import AuditError
from . import auth as auth_mod
from . import authz
from . import closure as closure_mod
from . import demo as demo_mod
from . import identity
from . import results
from .cases import CaseError
from .context import AppContext

PACKAGE_STATUS_TEXT = {
    "RECEIVED": "Package created - no evidence received yet",
    "RESUBMISSION_REQUIRED": "At least one evidence file needs a corrected version",
    "REVIEW_REQUIRED": "At least one evidence file is waiting for an analyst review",
    "INCOMPLETE": "At least one required evidence category has no file",
    "READY_FOR_VALIDATION": "Every required category has a validated file - run package validation and activate",
    "RECONCILIATION_READY": "The active snapshot is the current selection - reconciliation can be run",
}


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.extra = extra                      # additional JSON fields of the error body (e.g. current_revision)


def to_http(exc: Exception) -> HttpError:
    if isinstance(exc, HttpError):
        return exc
    if isinstance(exc, review_api.ApiError):
        return HttpError(exc.status, exc.code, exc.message)
    if isinstance(exc, demo_mod.DemoError):
        return HttpError(exc.status, exc.code, exc.message)
    if isinstance(exc, CaseError):
        return HttpError(exc.status, exc.code, exc.message)
    if isinstance(exc, closure_mod.ClosureError):
        return HttpError(exc.status, exc.code, exc.message, **exc.extra)
    if isinstance(exc, (PackageStoreError, LookupError, results.RunNotFound, KeyError)):
        return HttpError(404, "NOT_FOUND", str(exc).strip("'"))
    if isinstance(exc, PackageError):
        return HttpError(409, "PACKAGE_STATE", str(exc))
    if isinstance(exc, ValueError):
        msg = str(exc)
        head = msg.split(":", 1)[0].strip()
        return HttpError(400, head if head.replace("_", "").isalpha() and head.isupper() else "INVALID", msg)
    t = review_api.translate(exc)
    return HttpError(t.status, t.code, t.message)


# ================================================================================================ helpers
def _title(ctx: AppContext, cat: str | None) -> str | None:
    s = ctx.reg.get(cat) if cat else None
    return s.title if s else None


def _version_brief(ctx, v) -> dict:
    return {"file_version_id": v.file_version_id, "evidence_category": v.evidence_category,
            "category_title": _title(ctx, v.evidence_category), "version_number": v.version_number,
            "original_filename": v.original_filename, "version_status": v.version_status,
            "processing_status": v.processing_status, "uploaded_at": v.uploaded_at, "intake_id": v.intake_id,
            "source_sha256": v.source_sha256, "content_category": v.content_category,
            "identified_by_content": v.content_category == v.evidence_category,
            "reason": (v.reasons or [""])[0], "missing_fields": v.missing_fields,
            "previous_version_id": v.previous_version_id, "replacement_reason": v.replacement_reason,
            "review": "case" if v.review_case_id else "proposal" if v.review_session_id else None,
            "handoff_basis": v.handoff.basis if v.handoff else None,
            "handoff_eligible": v.handoff.eligible if v.handoff else None,
            "failed_checks": v.handoff.failed_checks if v.handoff else [],
            "preview": bool(v.handoff and v.handoff.preview_csv)}


def package_summary(ctx: AppContext, pid: str, light: bool = False) -> dict:
    svc = ctx.svc
    pkg = svc.load(pid)
    cats = list(pkg.evidence_files)
    latest = {c: pkg.latest(c) for c in cats}
    slots = []
    for c in sorted(cats):
        slot, lv = pkg.evidence_files[c], latest[c]
        slots.append({"evidence_category": c, "category_title": _title(ctx, c), "required": slot.required,
                      "format": ctx.reg.get(c).evidence_format, "versions": len(slot.version_ids),
                      "active_version_id": slot.active_version_id,
                      "latest": _version_brief(ctx, lv) if lv else None,
                      "state": lv.version_status if lv else "MISSING"})
    st = Counter(s["state"] for s in slots)
    counts = {
        "files_received": len(pkg.versions) + len(pkg.unassigned_uploads),
        "versions": len(pkg.versions),
        "identified_by_content": sum(1 for v in pkg.versions.values() if v.content_category == v.evidence_category),
        "refused_uploads": len(pkg.unassigned_uploads),
        "validated_or_active": st["VALIDATED"] + st["ACTIVE"],
        "review_required": st["REVIEW_REQUIRED"],
        "needs_new_version": sum(st[x] for x in NEEDS_NEW_VERSION),
        "missing_required": sum(1 for s in slots if s["required"] and s["state"] == "MISSING"),
        "required_categories": len(pkg.required_evidence_categories),
        "by_state": dict(st),
    }
    lval = pkg.validation_results[-1] if pkg.validation_results else None
    runs = results.list_runs(ctx.runs, pid)
    out = {"package_id": pid, "reporting_period": pkg.reporting_period, "created_at": pkg.created_at,
           "updated_at": pkg.updated_at, "package_status": pkg.package_status,
           "package_status_text": PACKAGE_STATUS_TEXT.get(pkg.package_status, ""),
           "active_snapshot_id": pkg.active_snapshot_id, "snapshot_ids": pkg.snapshot_ids, "counts": counts,
           "latest_validation": None if lval is None else {
               "validation_id": lval.validation_id, "at": lval.at, "passed": lval.passed,
               "failed": [c.check_id for c in lval.checks if not c.passed]},
           "latest_run": runs[0] if runs else None}
    if light:
        return out
    out.update(slots=slots, unassigned_uploads=pkg.unassigned_uploads,
               pending_resubmissions=svc.pending_resubmissions(pid),
               required_evidence_categories=pkg.required_evidence_categories, runs=runs,
               jobs=sorted([_job_brief(j) for j in ctx.jobs.values() if j["package_id"] == pid],
                           key=lambda j: j["created_at"], reverse=True))
    return out


def _job_brief(j: dict) -> dict:
    return {k: j.get(k) for k in ("job_id", "kind", "state", "created_at", "started_at", "finished_at", "run_id")} | {
        "files": len(j.get("files") or [])}


# ================================================================================================ jobs (progress)
STAGES = [
    ("init", "Initialising evidence package", "Creating the package record and its evidence slots"),
    ("read", "Reading uploaded files", "Receiving the uploaded bytes and recording their SHA-256"),
    ("identify", "Identifying evidence categories", "Classifying each file by its content (headers / PDF labels)"),
    ("structure", "Checking incoming column structures", "Comparing each file's columns with its category contract"),
    ("mapping", "Mapping recognised fields", "Deterministic mapping of source columns to canonical fields"),
    ("proposals", "Generating proposals for unresolved columns", "Asking the configured proposer about columns the "
                                                                  "deterministic layer could not map"),
    ("review", "Preparing analyst review cases", "Routing ambiguous or structurally different files to a person"),
    ("previews", "Generating canonical evidence previews", "Writing canonical previews + provenance for eligible files"),
    ("validation", "Running package validation", "PV-01 to PV-09 over the current selection"),
]


def job_view(ctx: AppContext, j: dict) -> dict:
    if j["kind"] == "reconciliation":
        return _recon_job_view(ctx, j)
    if j["kind"] in closure_mod.CLOSURE_JOB_KINDS:
        return closure_mod.job_view(j)
    ev = [e for e in ctx.events() if e["seq"] >= j["audit_seq_start"] and
          (j["audit_seq_end"] is None or e["seq"] <= j["audit_seq_end"])]
    files = j["files"]
    n = len(files)
    done = [f for f in files if f["state"] in ("done", "error")]
    running = j["state"] == "running"
    out_ok = [f["outcome"] for f in done if f["state"] == "done"]
    by_type = lambda t: [e for e in ev if e["event_type"] == t]   # noqa: E731
    first_start = min((f["started_at"] for f in files if f["started_at"]), default=None)
    last_end = max((f["finished_at"] for f in files if f["finished_at"]), default=None)
    files_finished = len(done) == n
    per_file_state = "completed" if files_finished else ("running" if running and first_start else "pending")
    created = next((e for e in ctx.events() if e["event_type"] == "PACKAGE_CREATED"
                    and e["details"].get("package_id") == j["package_id"]), None)
    pdf = [o for o in out_ok if (o.get("processing_status") or "").startswith("PDF:")]
    csvs = [o for o in out_ok if o.get("version_status") and not (o.get("processing_status") or "").startswith("PDF:")]
    refused = [f for f in done if f["state"] == "error" or (f["outcome"] or {}).get("refused_reason")]
    gate = [o for o in csvs if (o["processing_status"] or "").startswith("HEADER_COUNT_GATE")]
    det = [o for o in csvs if (o["processing_status"] or "").startswith("DETERMINISTIC")]
    prov = by_type("PROVIDER_CALL")
    rev_ev = by_type("FILE_VERSION_REVIEW_REQUIRED")
    prev_ev = by_type("HANDOFF_PREVIEW_WRITTEN")
    val_ev = [e for e in ev if e["event_type"] in ("PACKAGE_VALIDATION_STARTED", "PACKAGE_VALIDATED",
                                                     "PACKAGE_VALIDATION_FAILED")]
    t = lambda es: (es[0]["at"], es[-1]["at"]) if es else (None, None)   # noqa: E731

    def stage(key, status, detail, start=None, end=None, evidence=None):
        k, title, expl = next(s for s in STAGES if s[0] == key)
        return {"key": key, "title": title, "explanation": expl, "status": status, "detail": detail,
                "started_at": start, "finished_at": end, "evidence": evidence or []}
    stages = [
        stage("init", "completed" if created else "pending", f"package {j['package_id']}",
              created["at"] if created else None, created["at"] if created else None,
              ["audit: PACKAGE_CREATED"] if created else []),
        stage("read", "completed", f"{n} file(s), {sum(f['size'] for f in files):,} bytes, SHA-256 recorded",
              j["created_at"], j["created_at"], ["job record (staged uploads)"]),
        stage("identify", "requires_attention" if files_finished and refused else per_file_state,
              f"{len(done)} of {n} processed; {len(refused)} not accepted" if refused else f"{len(done)} of {n} processed",
              first_start, last_end if files_finished else None, ["service result per file"]),
        stage("structure", "requires_review" if files_finished and gate else per_file_state,
              f"{len(gate)} file(s) with a different column count (routed to a person)" if gate else
              (f"{len(csvs)} CSV file(s) checked; {len(pdf)} PDF(s) classified" if done else "waiting"),
              first_start, last_end if files_finished else None, ["service result: processing route"]),
        stage("mapping", per_file_state, f"{len(det)} of {len(csvs)} CSV file(s) mapped deterministically" if csvs
              else ("no CSV file" if files_finished else "waiting"), first_start, last_end if files_finished else None,
              ["service result: processing route"]),
        stage("proposals", ("completed" if prov else "not_required") if files_finished else per_file_state,
              (f"{len(prov)} proposal call(s) recorded ({', '.join(sorted({e['details'].get('status', '?') for e in prov}))})"
               f" - {ctx.llm_mode['label']}") if prov else f"no proposal needed - {ctx.llm_mode['label']}",
              *t(prov), [f"audit: PROVIDER_CALL x{len(prov)}"] if prov else []),
        stage("review", ("requires_review" if rev_ev else "not_required") if files_finished else per_file_state,
              f"{len(rev_ev)} file(s) waiting for an analyst" if rev_ev else "no file needs a review",
              *t(rev_ev), [f"audit: FILE_VERSION_REVIEW_REQUIRED x{len(rev_ev)}"] if rev_ev else []),
        stage("previews", per_file_state if not files_finished else "completed",
              f"{len(prev_ev)} canonical preview(s) written", *t(prev_ev),
              [f"audit: HANDOFF_PREVIEW_WRITTEN x{len(prev_ev)}"] if prev_ev else []),
    ]
    v = j.get("validation")
    if v is not None:
        stages.append(stage("validation", "completed" if v["passed"] else "blocked",
                            "all package checks pass - ready for activation" if v["passed"] else
                            f"activation blocked by {', '.join(v['failed'])}", *t(val_ev),
                            [f"audit: {e['event_type']}" for e in val_ev]))
    else:
        stages.append(stage("validation", "running" if j.get("validation_started_at") and running else
                            ("failed" if j["state"] == "failed" else "pending"), "waiting for the files to finish",
                            j.get("validation_started_at")))
    return {**{k: j.get(k) for k in ("job_id", "kind", "package_id", "state", "created_at", "started_at",
                                     "finished_at", "error", "resubmission", "validation")},
            "progress": {"files_total": n, "files_processed": len(done)}, "stages": stages,
            "files": [{k: f[k] for k in ("name", "size", "kind", "declared_category", "state", "started_at",
                                         "finished_at", "outcome")} for f in files],
            "events": [{k: e[k] for k in ("seq", "event_type", "at", "actor_id")} | {
                "category": e["details"].get("evidence_category") or e["details"].get("category"),
                "file": e["details"].get("filename")} for e in ev][-60:],
            "llm_mode": ctx.llm_mode}


def _recon_job_view(ctx, j):
    ev = [e for e in ctx.events() if e["seq"] >= j["audit_seq_start"] and
          (j["audit_seq_end"] is None or e["seq"] <= j["audit_seq_end"])
          and e["details"].get("package_id") == j["package_id"]]
    staged = next((e for e in ev if e["event_type"] == "RECONCILIATION_INPUT_STAGED"), None)
    done = next((e for e in ev if e["event_type"] in ("RECONCILIATION_EXECUTED", "RECONCILIATION_FAILED")), None)
    st = j["state"]
    stages = [
        {"key": "verify", "title": "Verifying the active snapshot", "explanation": "SV-1..SV-5, original and preview "
         "hashes re-checked", "status": "completed" if staged else ("failed" if st == "failed" else "running"),
         "started_at": j["started_at"], "finished_at": staged["at"] if staged else None, "detail": ""},
        {"key": "stage", "title": "Staging the selected evidence versions", "explanation": "exactly the snapshot's "
         "versions are copied into an isolated run folder", "status": "completed" if staged else
         ("failed" if st == "failed" else "pending"), "started_at": staged["at"] if staged else None,
         "finished_at": staged["at"] if staged else None,
         "detail": f"{len(staged['details'].get('files', []))} file(s) staged" if staged else ""},
        {"key": "engine", "title": "Running the UC-042 reconciliation engine", "explanation": "prepare_case + "
         "Validator.run in a separate process (read-only engine)", "status": "completed" if done and
         done["event_type"] == "RECONCILIATION_EXECUTED" else ("failed" if st == "failed" and staged else
                                                               ("running" if staged else "pending")),
         "started_at": staged["at"] if staged else None, "finished_at": done["at"] if done else None, "detail": ""},
        {"key": "verify_out", "title": "Verifying engine intake and tracing results", "explanation": "the engine "
         "received exactly the staged bytes; results traced to file versions", "status": "completed" if
         st == "completed" else ("failed" if st == "failed" else "pending"), "started_at": done["at"] if done else None,
         "finished_at": j["finished_at"] if st == "completed" else None,
         "detail": "; ".join(f"{k}={v}" for k, v in (j.get("result") or {}).get("checks", {}).items())},
    ]
    return {**{k: j.get(k) for k in ("job_id", "kind", "package_id", "state", "created_at", "started_at",
                                     "finished_at", "error", "snapshot_id", "run_id", "result")},
            "stages": stages, "events": [{k: e[k] for k in ("seq", "event_type", "at", "actor_id")} for e in ev]}


# ================================================================================================ identity (I-1) + authorisation (I-2)
def user_profile(ctx, user: str | None) -> dict:
    """Access roles of a signed-in user, from the credentials file loaded by the server (auth.py)."""
    a = getattr(ctx, "authenticator", None)
    return a.profile(user) if a is not None else auth_mod.registered_profile(user)


def acting(ctx, user: str | None):
    """The identity a request runs under. `user` comes ONLY from the server-side session validated by server.py
    (never from a request field). Without authentication the server reviewer acts and nothing is enforced."""
    if user:
        prof = user_profile(ctx, user)
        return identity.acting_as(user, roles=prof.get("roles") or (), reviewer_role=prof.get("reviewer_role"))
    srv = ctx.server_reviewer
    return identity.acting_as(srv.reviewer_id, role=srv.role, authenticated=False)


CASE_MUTATIONS = ("start", "defer", "resume", "retry", "evidence", "validate", "activate", "reconcile")
PACKAGE_MUTATIONS = ("intake", "resubmit", "validate", "activate", "reconcile")
REVIEW_MUTATIONS = ("decision", "reject", "complete")


def restricted_target(ctx, method: str, P: list[str]):
    """(case, action name) when this request is a restricted mutation of a case (I-2), else None. Every case,
    closure, review and upload mutation is restricted - including the generic /api/packages and /api/review
    mutations of a package that belongs to a case. Reads, registration, staging and claim are not."""
    if method != "POST":
        return None
    if P[:1] == ["cases"] and len(P) >= 3:
        rest = P[2:]
        if len(rest) == 1 and rest[0] in CASE_MUTATIONS:
            return ctx.cases.load(P[1]), "case/" + rest[0]
        if rest[:1] == ["closure"]:
            return ctx.cases.load(P[1]), "case/" + "/".join(rest)
        if rest[:1] == ["review"] and len(rest) == 3 and rest[2] in ("decision", "confirm", "reject"):
            return ctx.cases.load(P[1]), "case/review/" + rest[2]
        if rest == ["claim"]:                       # claim has its own audited ownership rules (api.claim)
            return None
        # Lead hardening (fail closed): any other POST under a case is restricted as well, so a mutation route added
        # later can never be reachable by a non-owner merely because it is missing from the lists above.
        return ctx.cases.load(P[1]), "case/" + "/".join(rest)
    pid = action = None
    if P[:1] == ["packages"] and len(P) == 3 and P[2] in PACKAGE_MUTATIONS:
        pid, action = P[1], "package/" + P[2]
    elif P[:1] == ["review"] and len(P) == 4 and P[3] in REVIEW_MUTATIONS:
        pid, action = P[1], "review/" + P[3]
    if pid is None:
        return None
    own = ctx.cases.owner_of(pid)
    return (own[0], action) if own else None


def route(ctx: AppContext, method: str, parts: list[str], q: dict, body: dict, *, user: str | None = None):
    """`user` is the signed-in username of the validated server-side session (None when the server runs without
    authentication). Every request runs under that identity (identity.py, I-1): it is the actor of every action and
    audit event. Every restricted mutation is authorised first (authz.py, I-2): the case owner, or a supervisor as an
    audited override; anyone else gets 403 NOT_CASE_OWNER + ACCESS_DENIED and nothing is delegated."""
    with acting(ctx, user):
        target = restricted_target(ctx, method, parts) if authz.enforced() else None
        if target is None:
            out = _route(ctx, method, parts, q, body, user=user)
        else:
            out = authz.guarded(ctx, target[0], target[1], lambda: _route(ctx, method, parts, q, body, user=user),
                                to_code=lambda e: to_http(e).code)
        if authz.enforced() and method == "GET" and parts[:1] == ["cases"] and len(parts) >= 3 \
                and parts[2] == "closure" and isinstance(out, dict):
            acc = authz.case_access(ctx.cases.load(parts[1]))      # reads stay open; closure actions mirror I-2
            out["access"] = acc
            if not acc["can_act"]:
                authz.restrict_actions(out, acc["reason"])
        return out


def _route(ctx: AppContext, method: str, parts: list[str], q: dict, body: dict, *, user: str | None = None):
    svc = ctx.svc
    P = parts
    if P == ["app"] and method == "GET":
        a = identity.current()
        return {"reviewer": {"reviewer_id": ctx.reviewer.reviewer_id, "role": ctx.reviewer.role, "kind": ctx.reviewer.kind},
                "user": {"username": user, "roles": sorted(a.roles), "supervisor": a.supervisor, "role": a.role}
                if user else None,
                "system_reviewer": {"reviewer_id": ctx.server_reviewer.reviewer_id, "role": ctx.server_reviewer.role,
                                    "kind": ctx.server_reviewer.kind},
                "authorization": {"enforced": bool(user), "model": "case owner (assigned_to) or audited supervisor "
                                  "override; reads open to signed-in users" if user else
                                  "not enforced (server runs without authentication)"},
                "authority_policy": ctx.authority.policy_id, "authority_status": ctx.authority.status,
                "llm": ctx.llm_mode, "engine_configured": ctx.uc042_root is not None,
                "demo_scenarios": getattr(ctx, "demo", None) is not None,
                "workspace": str(ctx.root), "submission": "disabled (no UC-042 submission, no audit pack)",
                "categories": [{"category": s.category, "title": s.title, "required": s.requirement == "REQUIRED",
                                "format": s.evidence_format} for s in ctx.reg.defined()]}
    if P == ["packages"]:
        if method == "GET":
            return [package_summary(ctx, pid, light=True) for pid in
                    sorted(svc.store.list(), key=lambda p: svc.load(p).created_at, reverse=True)]
        if method == "POST":
            with ctx.lock:
                pkg = svc.create_package(str(body.get("reporting_period", "")).strip())
            return package_summary(ctx, pkg.package_id)
    if P[:1] == ["staging"] and method == "POST" and len(P) == 1:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HttpError(400, "INVALID", "a file name is required")
        try:
            data = base64.b64decode(body.get("data_b64") or "", validate=True)
        except Exception as exc:
            raise HttpError(400, "INVALID", "file content is not valid base64") from exc
        return {"entries": ctx.stage(name, data)}
    if len(P) >= 2 and P[0] == "packages":
        pid = P[1]
        rest = P[2:]
        if not rest and method == "GET":
            return package_summary(ctx, pid)
        if rest == ["intake"] and method == "POST":
            ctx.cases.guard_package(pid, "intake")
            items = body.get("items") or []
            if not items:
                raise HttpError(400, "NO_FILES", "select at least one file to submit")
            return job_view(ctx, ctx.start_intake(pid, items))
        if rest == ["resubmit"] and method == "POST":
            ctx.cases.guard_package(pid, "resubmit")
            cat, reason, sid = body.get("category"), (body.get("reason") or "").strip(), body.get("staging_id")
            if not reason:
                raise HttpError(400, "REASON_REQUIRED", "a resubmission needs a replacement reason")
            pending = svc.pending_resubmissions(pid)
            if cat not in pending:
                raise HttpError(409, "PACKAGE_STATE", f"{cat} does not await a corrected file "
                                                      f"(awaiting: {sorted(pending) or 'none'})")
            return job_view(ctx, ctx.start_intake(pid, [{"staging_id": sid}], resubmission={"category": cat,
                                                                                             "reason": reason}))
        if rest == ["validate"] and method == "POST":
            ctx.cases.guard_package(pid, "validate")
            with ctx.lock:
                res = svc.validate(pid)
            return validation_view(ctx, pid, res)
        if rest == ["validation"] and method == "GET":
            pkg = svc.load(pid)
            return validation_view(ctx, pid, pkg.validation_results[-1] if pkg.validation_results else None)
        if rest == ["activate"] and method == "POST":
            if body.get("confirm") is not True:
                raise HttpError(400, "CONFIRMATION_REQUIRED", "activation needs an explicit confirmation")
            ctx.cases.guard_package(pid, "activate")
            with ctx.lock:
                a = svc.activate(pid)
            return {"activated": a.activated, "reason": a.reason,
                    "snapshot_id": a.snapshot.snapshot_id if a.snapshot else None,
                    "validation": validation_view(ctx, pid, a.validation), "package": package_summary(ctx, pid)}
        if rest[:1] == ["snapshots"] and len(rest) == 2 and method == "GET":
            return snapshot_view(ctx, pid, rest[1])
        if rest[:1] == ["versions"] and len(rest) >= 2 and method == "GET":
            vid = rest[1]
            if len(rest) == 2:
                return version_view(ctx, pid, vid)
            if rest[2:] == ["columns"]:
                return ctx.column_profile(pid, vid)
            if rest[2:] == ["preview"]:
                v = svc.load(pid).versions[vid]
                if not (v.handoff and v.handoff.preview_csv):
                    raise HttpError(404, "NO_PREVIEW", "no canonical preview has been generated for this version")
                return ("text/csv; charset=utf-8", svc.store.abs(v.handoff.preview_csv).read_bytes())
        if rest == ["reconcile"] and method == "POST":
            ctx.cases.guard_package(pid, "reconcile")
            return job_view(ctx, ctx.start_reconciliation(pid, str(body.get("snapshot_id") or "")))
        if rest == ["history"] and method == "GET":
            return history_view(ctx, pid)
    if P[:1] == ["jobs"] and len(P) == 2 and method == "GET":
        j = ctx.jobs.get(P[1])
        if j is None:
            raise HttpError(404, "NOT_FOUND", f"job {P[1]}")
        return job_view(ctx, j)
    if P == ["reviews"] and method == "GET":
        rows = review_api.list_reviews(svc)
        for r in rows:
            r["category_title"] = _title(ctx, r["evidence_category"])
        return rows
    if len(P) >= 3 and P[0] == "review":
        pid, vid, rest = P[1], P[2], P[3:]
        if not rest and method == "GET":
            return review_view(ctx, pid, vid)
        if method == "POST":
            ctx.cases.guard_package(pid, "review")
        with ctx.lock:
            if rest == ["decision"] and method == "POST":
                review_api.decide(svc, ctx.reviewer, pid, vid, body.get("action", ""), body.get("source_index", -1),
                                  body.get("reason", ""), body.get("canonical_field"), body.get("others_reason"))
                return review_view(ctx, pid, vid)
            if rest == ["reject"] and method == "POST":
                review_api.reject(svc, ctx.reviewer, pid, vid, body.get("reason", ""))
                return review_view(ctx, pid, vid)
            if rest == ["complete"] and method == "POST":
                review_api.complete(svc, ctx.reviewer, pid, vid, body.get("basis", ""))
                return review_view(ctx, pid, vid)
    if P[:1] == ["runs"]:
        if len(P) == 1 and method == "GET":
            return results.list_runs(ctx.runs, q.get("package_id"))
        d = results.run_dir(ctx.runs, P[1])
        rest = P[2:]
        if not rest:
            return results.summary(d) | {"exceptions": results.exceptions(d)}
        if rest == ["controls"]:
            rows = results.controls(d)
            if q.get("outcome"):
                rows = [r for r in rows if r["outcome"] == q["outcome"]]
            if q.get("check"):
                rows = [r for r in rows if q["check"].lower() in r["check_id"].lower()]
            return {"total": len(rows), "rows": rows[:2000], "truncated": len(rows) > 2000}
        if rest == ["report"]:
            return ("text/markdown; charset=utf-8", results.report(d).encode("utf-8"))
        if rest[:1] == ["exceptions"] and len(rest) == 2:
            return results.exception_detail(d, rest[1])
    if P[:1] == ["cases"]:
        return case_route(ctx, method, P[1:], q, body, user=user)
    if P == ["ai", "configuration"] and method == "GET":
        cl = getattr(ctx, "closure", None)
        if cl is None:
            return {"available": False, "provider": None, "model": None, "reasoning_effort": None,
                    "problem": "the closure service is not configured on this server", "pricing_configured": False,
                    "store": False, "data_notice": None}
        return cl.ai_configuration()
    if P[:1] == ["demo"]:
        return demo_mod.route(ctx, method, P[1:], q, body, user=user)
    if P == ["customers"] and method == "GET":
        return ctx.cases.customers()
    if P[:1] == ["customers"] and len(P) == 2 and method == "GET":
        return ctx.cases.customer(P[1])
    if P == ["activity"] and method == "GET":
        return activity_view(ctx, q.get("package_id"))
    raise HttpError(404, "NOT_FOUND", "/api/" + "/".join(P))


# ================================================================================================ views
def validation_view(ctx, pid, res) -> dict:
    svc = ctx.svc
    pkg = svc.load(pid)
    cand = svc.candidate(pkg)
    BLOCK = {"PV-01": "Add the missing required evidence", "PV-02": "Every required category needs one validated "
             "version", "PV-03": "Upload corrected files for the categories awaiting resubmission", "PV-04":
             "Complete or reject the open reviews", "PV-05": "A selected file failed its file-level re-check",
             "PV-06": "Reporting periods must match the package", "PV-07": "A selected version does not belong to "
             "this package slot", "PV-08": "A stored original no longer matches its SHA-256", "PV-09":
             "The selection must reference validated versions only"}
    slots = package_summary(ctx, pid)["slots"]
    return {
        "package_id": pid, "package_status": pkg.package_status,
        "result": None if res is None else {"validation_id": res.validation_id, "at": res.at, "passed": res.passed,
                                            "checks": [c.model_dump() | {"blocks_activation": not c.passed,
                                                                         "action": None if c.passed else BLOCK.get(c.check_id)}
                                                       for c in res.checks], "selection": res.selection},
        "summary": {
            "required_present": [s["evidence_category"] for s in slots if s["required"] and s["state"] != "MISSING"],
            "missing": [s["evidence_category"] for s in slots if s["required"] and s["state"] == "MISSING"],
            "optional": [s["evidence_category"] for s in slots if not s["required"]],
            "rejected": [s["evidence_category"] for s in slots if s["state"] == "REJECTED"],
            "failed_validation": [s["evidence_category"] for s in slots if s["state"] == "FAILED_VALIDATION"],
            "resubmission_required": [s["evidence_category"] for s in slots if s["state"] == "RESUBMISSION_REQUIRED"],
            "review_required": [s["evidence_category"] for s in slots if s["state"] == "REVIEW_REQUIRED"],
            "validated": [s["evidence_category"] for s in slots if s["state"] == "VALIDATED"],
            "active": [s["evidence_category"] for s in slots if s["state"] == "ACTIVE"],
            "refused_uploads": len(pkg.unassigned_uploads)},
        "candidate": [{"evidence_category": c, "file_version_id": x,
                       **({"version_number": pkg.versions[x].version_number, "original_filename":
                           pkg.versions[x].original_filename, "source_sha256": pkg.versions[x].source_sha256,
                           "version_status": pkg.versions[x].version_status} if x else {})}
                      for c, x in sorted(cand.items())],
        "active_snapshot_id": pkg.active_snapshot_id,
        "activation_permitted": bool(res is not None and res.passed),
        "activation_note": "activation re-runs PV-01..PV-09 and creates an immutable snapshot + manifest marked NOT "
                           "submitted; no audit pack is generated or published",
        "slots": slots}


def snapshot_view(ctx, pid, sid) -> dict:
    svc = ctx.svc
    snap = svc.store.load_snapshot(pid, sid)
    mp = svc.store.manifest_path(pid, sid)
    man = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else None
    pkg = svc.load(pid)
    return {"snapshot": snap.model_dump(), "manifest": man, "is_active": pkg.active_snapshot_id == sid,
            "verification": [c.model_dump() for c in svc.verify_snapshot(pid, sid)],
            "reconciliation_eligible": pkg.active_snapshot_id == sid and ctx.uc042_root is not None,
            "runs": [r for r in results.list_runs(ctx.runs, pid) if r["snapshot_id"] == sid]}


def version_view(ctx, pid, vid) -> dict:
    svc = ctx.svc
    pkg = svc.load(pid)
    v = pkg.versions[vid]
    detail = review_api.review_detail(svc, pid, vid) if (v.review_case_id or v.review_session_id) else None
    ev = [e for e in ctx.events() if e["details"].get("file_version_id") == vid or
          (e.get("intake_id") and e.get("intake_id") == v.intake_id)]
    return {"version": v.model_dump(), "brief": _version_brief(ctx, v),
            "history": [_version_brief(ctx, x) for x in pkg.history(v.evidence_category)],
            "decisions": [r for r in (detail or {}).get("rows", []) if r.get("decision")],
            "review_kind": (detail or {}).get("review_kind"), "events": ev}


def history_view(ctx, pid) -> dict:
    pkg = ctx.svc.load(pid)
    return {"package_id": pid, "categories": [{"evidence_category": c, "category_title": _title(ctx, c),
                                               "required": s.required, "active_version_id": s.active_version_id,
                                               "versions": [_version_brief(ctx, pkg.versions[x]) | {
                                                   "status_history": [h.model_dump() for h in
                                                                      pkg.versions[x].status_history]}
                                                   for x in s.version_ids]}
                                              for c, s in sorted(pkg.evidence_files.items())],
            "snapshots": [ctx.svc.store.load_snapshot(pid, s).model_dump() for s in pkg.snapshot_ids],
            "active_snapshot_id": pkg.active_snapshot_id,
            "validations": [{"validation_id": r.validation_id, "at": r.at, "passed": r.passed,
                             "failed": [c.check_id for c in r.checks if not c.passed]} for r in pkg.validation_results],
            "unassigned_uploads": pkg.unassigned_uploads}


def review_view(ctx, pid, vid) -> dict:
    d = review_api.review_detail(ctx.svc, pid, vid)
    fields = {f["name"]: f for f in d["canonical_fields"]}
    try:
        prof = ctx.column_profile(pid, vid)
    except Exception as exc:                                  # shown, never hidden
        prof = {"kind": None, "columns": [], "error": str(exc)}
    by_idx = {c["source_index"]: c for c in prof.get("columns", [])}
    for r in d["rows"]:
        f = fields.get((r.get("decision") or {}).get("canonical_field") or r.get("suggested_field") or "")
        r["profile"] = by_idx.get(r["source_index"])
        r["field_type"] = f["type"] if f else None
        r["field_required"] = f["required"] if f else None
        r["financial"] = bool(f and f["type"] in ("amount", "signed"))
        r["sign_sensitive"] = bool(f and f["type"] in ("amount", "signed")) or "sign" in (r.get("note") or "")
        alt = []
        if r.get("note") and "other valid candidates" in r["note"]:
            alt.append(r["note"])
        r["alternatives_note"] = alt
    d["profile"] = {k: prof.get(k) for k in ("kind", "encoding", "delimiter", "rows", "error")}
    d["reviewer"] = {"reviewer_id": ctx.reviewer.reviewer_id, "role": ctx.reviewer.role, "kind": ctx.reviewer.kind,
                     "authority_policy": ctx.authority.policy_id}
    pkg = ctx.svc.load(pid)
    v = pkg.versions[vid]
    d["why_review"] = d.get("review_reason")
    d["status_history"] = [h.model_dump() for h in v.status_history]
    d["current_outcome_reason"] = v.reasons[-1] if v.reasons and v.version_status != "REVIEW_REQUIRED" else None
    return d


def activity_view(ctx, pid: str | None) -> dict:
    ev = ctx.events()
    try:
        n = ctx.log.verify()
        chain = {"verified": True, "events": n}
    except AuditError as exc:
        chain = {"verified": False, "error": str(exc)}
    if pid:
        pkg = ctx.svc.load(pid)
        intakes = {v.intake_id for v in pkg.versions.values()}
        ev = [e for e in ev if e["details"].get("package_id") == pid or e.get("intake_id") in intakes]
    return {"chain": chain, "events": [{k: e.get(k) for k in ("seq", "event_id", "event_type", "at", "actor_id",
                                                              "actor_role", "intake_id", "source_sha256", "hash")}
                                       | {"details": e.get("details", {})} for e in ev][::-1][:1500]}


# ================================================================================================ Ringfence cases
def case_route(ctx: AppContext, method: str, P: list[str], q: dict, body: dict, *, user: str | None = None):
    """/api/cases... Every lifecycle rule lives in CaseService; these handlers only parse and delegate."""
    cs = ctx.cases
    if not P:
        if method == "GET":
            assigned = q.get("assigned") or None
            if assigned not in (None, "me"):
                raise HttpError(400, "INVALID", "assigned must be 'me'")
            if assigned == "me" and not user:
                raise HttpError(400, "NO_SIGNED_IN_USER", "assigned=me needs a signed-in user "
                                "(this server runs without authentication)")
            return cs.queue(q.get("status") or None, assigned_to=user if assigned == "me" else None)
        if method == "POST":
            try:
                data = base64.b64decode(body.get("zip_b64") or "", validate=True)
            except (ValueError, TypeError):
                raise HttpError(400, "INVALID", "zip_b64 is not valid base64") from None
            assignee = body.get("assigned_to") or None
            if authz.enforced():                                # R-P0-1: registration assigns the signed-in user
                a = identity.current()
                if assignee is None:
                    assignee = a.user
                elif assignee != a.user and not a.supervisor:
                    raise authz.deny(ctx, None, "case/register", "only a supervisor can register a case for another "
                                     "user", code="ASSIGNMENT_NOT_PERMITTED", requested_assignee=str(assignee)[:256])
                elif assignee != a.user and not _known_user(ctx, assignee):
                    raise HttpError(400, "UNKNOWN_USER", f"{assignee!r} is not a user of this server")
            c = cs.create(body.get("customer_name", ""), body.get("reporting_period", ""), body.get("zip_name", ""),
                          data, body.get("customer_id") or None, assigned_to=assignee)
            return cs.detail(c["case_ref"])
    ref, rest = P[0], P[1:]
    if rest == ["claim"] and method == "POST":
        return claim(ctx, ref, body)
    if not rest and method == "GET":
        return cs.detail(ref)                                   # opening a case never changes its status
    if rest[:1] == ["closure"]:                                 # closure has its OWN revision (expected_revision)
        return closure_route(ctx, method, ref, rest[1:], q, body, user=user)
    if rest == ["activity"] and method == "GET":
        return cs.activity(ref)
    if method == "POST":
        cs.check_revision(ref, body.get("expected_revision"))   # optional stale-action guard (409 CASE_CHANGED)
    if method == "POST" and rest == ["start"]:
        return cs.start(ref)
    if method == "POST" and rest == ["defer"]:
        return cs.defer(ref)
    if method == "POST" and rest == ["resume"]:
        return cs.resume(ref)
    if method == "POST" and rest == ["retry"]:
        return cs.retry(ref, body.get("confirm"))
    if method == "POST" and rest == ["evidence"]:
        return cs.upload_evidence(ref, str(body.get("staging_id") or ""), body.get("category") or None)
    if method == "POST" and rest == ["validate"]:
        return cs.validate(ref)
    if method == "POST" and rest == ["activate"]:
        return cs.activate(ref, body.get("confirm"))
    if method == "POST" and rest == ["reconcile"]:
        out = cs.reconcile(ref)
        j = ctx.jobs.get(out.get("job_id") or "")
        if j is not None:                                       # who started it: AUTO_INVESTIGATION authorised_by
            j["requested_by"] = user or ctx.reviewer.reviewer_id
            try:
                ctx._save_job(j)
            except OSError:
                pass                                            # the job thread saves the same record again
        return out
    if rest[:1] == ["review"] and len(rest) >= 2:
        vid, act = rest[1], rest[2:]
        if not act and method == "GET":
            return cs.review(ref, vid)
        if act == ["decision"] and method == "POST":
            try:
                idx = int(body.get("source_index"))
            except (TypeError, ValueError):
                raise HttpError(400, "INVALID", "source_index must be an integer") from None
            action = {"IGNORE_COLUMN": "IGNORE"}.get(str(body.get("action") or ""), str(body.get("action") or ""))
            if action == "REJECT":                              # Reject / Request correction is file-level
                return cs.reject_file(ref, vid)
            return cs.decide(ref, vid, action, idx, body.get("canonical_field") or None)
        if act == ["confirm"] and method == "POST":
            return cs.confirm_review(ref, vid)
        if act == ["reject"] and method == "POST":
            return cs.reject_file(ref, vid)
    if rest[:1] == ["runs"] and len(rest) == 2 and method == "GET":
        return cs.run(ref, rest[1])
    raise HttpError(404, "NOT_FOUND", "/api/cases/" + "/".join(P))


def _known_user(ctx, username) -> bool:
    a = getattr(ctx, "authenticator", None)
    if a is not None:
        return a.known(username)
    return username in auth_mod._ROLE_REGISTRY


def claim(ctx, ref: str, body: dict) -> dict:
    """POST /api/cases/{ref}/claim {assigned_to?, expected_revision?} - the explicit, audited ownership change
    (CASE_ASSIGNED).

    * Any signed-in analyst may claim an UNASSIGNED case for themselves.
    * Claiming a case you already own changes nothing.
    * A case owned by someone else can be claimed or reassigned (assigned_to = any known user) only by a supervisor;
      that is audited SUPERVISOR_OVERRIDE as well as CASE_ASSIGNED. An analyst gets 403 NOT_CASE_OWNER + ACCESS_DENIED.
    * An analyst may not assign a case to someone else (403 ASSIGNMENT_NOT_PERMITTED + ACCESS_DENIED).
    * Without authentication there is no user to claim for: 400 NO_SIGNED_IN_USER."""
    if not authz.enforced():
        raise HttpError(400, "NO_SIGNED_IN_USER", "claiming a case needs a signed-in user "
                        "(this server runs without authentication)")
    a = identity.current()
    c = ctx.cases.load(ref)
    owner = c.get("assigned_to")
    target = body.get("assigned_to") or a.user
    if not isinstance(target, str) or not _known_user(ctx, target):
        raise HttpError(400, "UNKNOWN_USER", f"{target!r} is not a user of this server")
    if target != a.user and not a.supervisor:
        raise authz.deny(ctx, c, "case/claim", "only a supervisor can assign a case to another user",
                         code="ASSIGNMENT_NOT_PERMITTED", requested_assignee=target)
    if owner == target:
        return ctx.cases.detail(ref)
    if owner is None and target == a.user:
        return ctx.cases.assign(ref, target, "CLAIM", body.get("expected_revision"))
    if not a.supervisor:                                   # owned by someone else
        raise authz.deny(ctx, c, "case/claim", authz.case_access(c)["reason"])
    return authz.guarded(ctx, c, "case/reassign",
                         lambda: ctx.cases.assign(ref, target, "REASSIGN", body.get("expected_revision")),
                         to_code=lambda e: to_http(e).code)


# ================================================================================================ Ringfence closure
def closure_route(ctx: AppContext, method: str, ref: str, R: list[str], q: dict, body: dict, *, user: str | None = None):
    """/api/cases/{ref}/closure... Every rule lives in ClosureService; these handlers only parse and delegate. Mutations
    carry the CLOSURE revision (expected_revision, required; 409 CLOSURE_CHANGED with current_revision)."""
    cl = getattr(ctx, "closure", None)
    if cl is None:
        raise HttpError(404, "CLOSURE_DISABLED", "the closure service is not configured on this server")
    if method == "GET":
        if not R:
            return cl.view(ref)
        if R == ["pack"]:
            return cl.pack_view(ref)
        if R == ["pack.html"]:
            return cl.pack_html(ref)
        if R == ["history"]:
            return cl.history(ref)
        if R[:1] == ["exceptions"] and len(R) == 2:
            return cl.exception_workspace(ref, R[1])
        if R[:1] == ["exceptions"] and len(R) == 3 and R[2] == "history":
            return cl.exception_history(ref, R[1])
        if R[:1] == ["investigations"] and len(R) == 2:
            return cl.investigation(ref, R[1])
        if R[:2] in (["review", "preview.pdf"], ["review", "preview.html"], ["review", "preview.json"], ["review", "preview.technical.pdf"]):
            return cl.preview_file(ref, R[1].split(".", 1)[1])
        if R == ["final-pack"]:
            return cl.final_pack(ref)
        if R[:1] == ["final-pack"] and len(R) == 2:
            return cl.final_file(ref, R[1], q.get("download") in ("1", "true"))
    if method == "POST":
        rev = body.get("expected_revision")
        if R[:1] == ["exceptions"] and len(R) == 3 and R[2] == "investigations":
            return cl.start_investigation(ref, R[1], rev, user)
        if R[:1] == ["investigations"] and len(R) == 3 and R[2] == "decision":
            return cl.decide_investigation(ref, R[1], str(body.get("decision") or ""), rev, user, body.get("explanation"))
        if R == ["review"]:
            return cl.open_review(ref, rev, user)
        if R == ["review", "selections"]:
            return cl.set_selections(ref, body.get("selections"), rev, user)
        if R == ["review", "preview"]:
            return cl.request_preview(ref, body.get("confirm_ai"), rev, user)
        if R == ["review", "decision"]:
            return cl.decide_review(ref, body, user)
    raise HttpError(404, "NOT_FOUND", f"/api/cases/{ref}/closure/" + "/".join(R))
