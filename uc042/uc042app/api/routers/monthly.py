"""Monthly document management: reconciliation periods, uploads, source documents, processing runs and activity.
Requires the database (503 DATABASE_REQUIRED otherwise). Responses never contain file-system paths or storage references."""
import calendar
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from uc042lib import schema

from ...errors import AppError
from ...ingest.analysis import evidence_label
from ...services.monthly import MAX_FILE_BYTES, ZIP_ORIGIN, processing_limitation, processing_supported
from ...services.packages import PackageService
from ..deps import services
from ..schemas import (SubmissionPackage, ActivityEvent, BatchDetail, CreatePeriodRequest, DashboardSummary, DocumentReviewRequest, PackLineage, Period,
                       PeriodDetail, ProcessingRun, ReassessmentPlan, ProcessRequest, ReconcileRequest, SourceDocument, UpdatePeriodRequest,
                       PackageItem, SubmissionDetail, UpdatePackageRequest)

router = APIRouter(prefix="/api/v1", tags=["monthly documents"])


def evidence_types(period_id):
    return {fid: evidence_label(fid, period_id) for fid in list(schema.CSV_FILES) + list(schema.PDF_FILES)}


def document_view(d):
    out = {k: v for k, v in d.items() if k != "storage_ref"}
    out["storage_kind"] = "POC_DATASET" if d["storage_ref"].startswith("dataset:") else "UPLOADED_ORIGINAL"
    return out


def _finals_by_pack(svc):
    """{pack_id: [final pack list items, oldest first]} of the published final audit packs."""
    out = {}
    for f in svc.final_packs.list():
        out.setdefault(f["pack_id"], []).append(f)
    return out


def _counted(row):
    """A published investigation counts as published when it is in the publication registry and its authorisation is not
    an AUTHORIZATION_DISCREPANCY. Unregistered artefacts and discrepancies are kept and listed, but counted separately."""
    return row.get("registry") is not None and (row.get("authorization") or {}).get("status") != "AUTHORIZATION_DISCREPANCY"


INVESTIGATION_COUNT_KEYS = ("published", "eligible", "running", "rejected_attempts", "unregistered", "authorization_discrepancy",
                           "ineligible_other")


def _investigation_counts(svc, pack_id, pack=None):
    """Investigation counts of a pack from the authoritative records (read-only): published = registered and not an
    authorisation discrepancy; eligible = usable in a final pack; running = active jobs; rejected_attempts = failed or
    rejected attempts kept unpublished; unregistered / authorization_discrepancy = artefacts kept but excluded;
    ineligible_other = registered artefacts failing another rule (for example the current validation rules).
    Also eligible_exceptions: exceptions with at least one eligible investigation."""
    out = dict.fromkeys(INVESTIGATION_COUNT_KEYS, 0)
    out["eligible_exceptions"] = 0
    try:
        rows = svc.investigations.for_pack(pack_id, pack)
    except AppError:
        return out
    for r in rows:
        out["running"] += len(r["active_jobs"])
        out["rejected_attempts"] += len(r["not_published"])
        out["eligible_exceptions"] += any(i["eligible"] for i in r["published"])
        for i in r["published"]:
            discrepancy = (i.get("authorization") or {}).get("status") == "AUTHORIZATION_DISCREPANCY"
            out["published"] += _counted(i)
            out["eligible"] += bool(i["eligible"])
            out["unregistered"] += i.get("registry") is None and not discrepancy
            out["authorization_discrepancy"] += discrepancy
            out["ineligible_other"] += _counted(i) and not i["eligible"]
    return out


def display_title(p):
    """(title, source): the stored report title, or the default derived from the month when none was ever set (records
    are not rewritten to add one)."""
    if p.get("title"):
        return p["title"], "STORED"
    return f"{calendar.month_name[p['month']]} {p['year']} Reconciliation Audit", "DERIVED"


def _after(a, b):
    return datetime.fromisoformat(a) > datetime.fromisoformat(b)


def _pack_refs(svc, period_id, finals_by_pack):
    lineage = {r["pack_id"]: r for r in svc.monthly.repos.lineage.list(period_id=period_id)} if svc.monthly.repos.lineage else {}
    out = []
    for rec in svc.monthly.repos.periods.packs(period_id):
        finals = finals_by_pack.get(rec["pack_id"], [])
        link = lineage.get(rec["pack_id"]) or {}
        ref = dict(rec, final_packs=len(finals), final_pack_ids=[f["final_pack_id"] for f in finals],
                   predecessor_pack_id=link.get("predecessor_pack_id"), lineage_root_pack_id=link.get("lineage_root_pack_id"))
        try:
            pack = svc.packs.peek(rec["pack_id"])  # read-only, not copied: the summary and the investigation counts only read it
            s = svc.packs.summary(pack)
            counts = _investigation_counts(svc, rec["pack_id"], pack)
            ref.update(verified=True, engine_case_status=s["engine_case_status"], evidence_completeness=s["evidence_completeness"],
                       exceptions_total=s["exceptions"]["total"], exceptions_open=s["exceptions"]["open"], pack_kind=s["pack_kind"],
                       scenario_name=s["scenario_name"], published_investigations=counts["published"],
                       eligible_investigations=counts["eligible"],
                       excluded_investigations=counts["unregistered"] + counts["authorization_discrepancy"],
                       investigation_counts=counts)
        except AppError:
            ref.update(verified=False)
        out.append(ref)
    return out


def period_view(svc, p, finals_by_pack=None):
    repos = svc.monthly.repos
    batches = repos.uploads.batches(p["period_id"])
    documents = repos.uploads.documents(period_id=p["period_id"])
    runs = repos.runs.list(period_id=p["period_id"])
    finals_by_pack = finals_by_pack if finals_by_pack is not None else _finals_by_pack(svc)
    packs = _pack_refs(svc, p["period_id"], finals_by_pack)
    finals = sum(x["final_packs"] for x in packs)
    uploads = [b for b in batches if b["origin"] == "UPLOAD"]
    state = ("RESULTS_AND_FINAL_PACK" if packs and finals else "RESULTS_NO_FINAL_PACK" if packs else
             "DOCUMENTS_NO_RESULTS" if documents else "AWAITING_UPLOAD")
    published = [f for x in packs for f in finals_by_pack.get(x["pack_id"], [])]
    latest_final = max((f["generated_at"] for f in published), default=None)
    # Legacy "evidence received after publication" (pending reassessment): only legacy documents after a LEGACY final pack.
    # A ZIP submission is an independent audit: its documents and final packs never make the period pending reassessment.
    legacy_final = max((f["generated_at"] for f in published if not f.get("submission_id")), default=None)
    zip_batches = {b["batch_id"] for b in batches if b.get("origin") == ZIP_ORIGIN}
    after = [d for d in documents if legacy_final and d["batch_id"] not in zip_batches and _after(d["created_at"], legacy_final)]
    title, title_source = display_title(p)
    reassessments = [r for r in runs if (r.get("result") or {}).get("purpose") == "REASSESSMENT"]
    return dict(p, title=title, title_source=title_source, storage_profile=p.get("storage_profile") or "",
                reporting_status=_reporting_status(packs, documents, uploads, finals, after),
                published_investigations=sum(x.get("published_investigations", 0) for x in packs),
                eligible_investigations=sum(x.get("eligible_investigations", 0) for x in packs),
                excluded_investigations=sum(x.get("excluded_investigations", 0) for x in packs),
                reassessment_runs=len(reassessments),
                latest_reassessment_status=reassessments[-1]["status"] if reassessments else None,
                latest_final_pack_at=latest_final, documents_after_publication=len(after), pending_reassessment=bool(after),
                archive_state=state, batch_count=len(batches), document_count=len(documents),
                latest_batch_status=uploads[-1]["status"] if uploads else None,
                latest_validation_status=uploads[-1]["validation_status"] if uploads else None,
                latest_run_status=runs[-1]["status"] if runs else None, pack_count=len(packs),
                scenario_packs=any(x["origin"] == "POC_SCENARIO" for x in packs),
                exceptions_total=sum(x["exceptions_total"] for x in packs), exceptions_open=sum(x["exceptions_open"] for x in packs),
                final_pack_count=finals, processing_supported=processing_supported(p["period_id"]),
                processing_limitation=processing_limitation(p["period_id"]), investigation_counts=_sum_counts(packs),
                packs=packs)


def _sum_counts(packs):
    keys = INVESTIGATION_COUNT_KEYS + ("eligible_exceptions",)
    return {k: sum((x.get("investigation_counts") or {}).get(k, 0) for x in packs) for k in keys}


def _reporting_status(packs, documents, uploads, finals, after_publication):
    """The period's reporting status, from its records only (never from the month name)."""
    if finals:
        return "ADDITIONAL_EVIDENCE_RECEIVED" if after_publication else "FINAL_PACK_PUBLISHED"
    if packs:
        return "INVESTIGATION_AVAILABLE" if any(x.get("published_investigations") for x in packs) else "DETERMINISTIC_PACK_AVAILABLE"
    if documents:
        return "VALIDATION_REQUIRED" if uploads and uploads[-1]["status"] == "VALIDATED" else "DOCUMENTS_UPLOADED"
    return "NO_DATA"


def _monthly(svc):
    svc.monthly._require()
    return svc.monthly


def _batch(d):
    batch = d["batch"]
    if batch.get("origin") == ZIP_ORIGIN:  # the package's display name (stored, or derived from the ZIP file name)
        batch = dict(batch, display_name=PackageService.display_name(batch)[0])
    return dict(d, batch=batch, documents=[document_view(x) for x in d["documents"]])


@router.get("/periods", response_model=list[Period], summary="Monthly archive: every reconciliation period with its status")
def list_periods(svc=Depends(services)):
    m = _monthly(svc)
    finals = _finals_by_pack(svc)
    return [period_view(svc, p, finals) for p in m.periods()]


@router.post("/periods", response_model=Period, status_code=201,
             summary="Open a month for upload (current or past month only; creates no data)")
def create_period(body: CreatePeriodRequest, response: Response, svc=Depends(services)):
    p, created = _monthly(svc).create_period(body.year, body.month, body.title)
    if not created:
        response.status_code = 200  # the month already exists: returned unchanged (never a second period, title not altered)
    return period_view(svc, p)


@router.patch("/periods/{period_id}", response_model=Period,
              summary="Change a period's report title (the period ID and its pack references never change)")
def update_period(period_id: str, body: UpdatePeriodRequest, svc=Depends(services)):
    return period_view(svc, _monthly(svc).rename_period(period_id, body.title))


@router.get("/periods/{period_id}", response_model=PeriodDetail,
            summary="One period: batches, documents, the current processing document set, runs and packs")
def get_period(period_id: str, svc=Depends(services)):
    d = _monthly(svc).period_detail(period_id)
    return dict(d, period=period_view(svc, d["period"]), documents=[document_view(x) for x in d["documents"]],
                evidence_types=evidence_types(period_id))


@router.post("/periods/{period_id}/uploads", response_model=BatchDetail, status_code=201,
             summary="Upload a batch of source documents (multipart field 'files'); stored, identified and validated, "
                     "not processed")
async def upload(period_id: str, files: list[UploadFile] = File(...), submission_kind: str = Form("INITIAL"),
                 reason: str = Form(""), replaces_document_id: str = Form(""), svc=Depends(services)):
    m = _monthly(svc)
    received = []
    for f in files:
        received.append((f.filename or "unnamed", await f.read(MAX_FILE_BYTES + 1)))
    published = [f["final_pack_id"] for f in m.published_final_packs(period_id)] if m.repos.periods.get(period_id) else []
    return _batch(m.upload(period_id, received, submission_kind, reason, replaces_document_id or None, published))


# ---------------------------------------------------------------- independent ZIP submissions (17 Nov 2026)
@router.post("/periods/{period_id}/packages", response_model=BatchDetail, status_code=201,
             responses={413: {"description": "PACKAGE_TOO_LARGE"}},
             summary="Upload ONE ZIP holding one complete, independent document set for the period (multipart field 'file'). "
                     "It is read safely, mapped through the central UC-042 schema, analysed and checked for completeness; "
                     "nothing is processed (Submit for Audit is a separate action). A rejected or incomplete package is "
                     "recorded with its report and can never be submitted.")
async def upload_package(period_id: str, file: UploadFile = File(...), display_name: str = Form(""), svc=Depends(services)):
    """display_name (optional form field): the package's name (trimmed, at most 200 characters; empty: not set, a name
    derived from the ZIP file name is shown). Kept for rejected packages too."""
    from ...ingest.zip_package import ZipLimits
    m = _monthly(svc)
    limits = ZipLimits.from_env()
    data = await file.read(limits.max_archive_bytes + 1)
    if len(data) > limits.max_archive_bytes:
        raise AppError(f"the ZIP exceeds the {limits.max_archive_bytes} byte limit", code="PACKAGE_TOO_LARGE", status=413)
    return _batch(m.upload_package(period_id, data, file.filename or "package.zip", limits, display_name=display_name))


@router.get("/packages", response_model=list[PackageItem],
            summary="Read-only: every ZIP submission package of every period (newest first) with its completeness gate, its "
                    "display name and its latest submission's status and stage (legacy uploads and scenario imports excluded)")
def list_packages(svc=Depends(services)):
    return svc.packages.list()


@router.get("/packages/{batch_id}", response_model=PackageItem, responses={409: {"description": "NOT_A_PACKAGE"}},
            summary="Read-only: one ZIP submission package (the same item as in GET /packages)")
def get_package(batch_id: str, svc=Depends(services)):
    return svc.packages.item(batch_id)


@router.patch("/packages/{batch_id}", response_model=PackageItem,
              responses={404: {"description": "upload batch not found"}, 409: {"description": "NOT_A_PACKAGE"},
                         422: {"description": "INVALID_DISPLAY_NAME, INVALID_ID"}},
              summary="Set the display name of a ZIP submission package (empty clears it); records an activity event")
def rename_package(batch_id: str, body: UpdatePackageRequest, svc=Depends(services)):
    return svc.packages.rename(batch_id, body.display_name)


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail,
            responses={404: {"description": "submission not found"}, 422: {"description": "INVALID_ID"}},
            summary="Read-only: one ZIP submission's status (audit run, investigations, decisions, review, final pack, stage) "
                    "and its package")
def get_submission(submission_id: str, svc=Depends(services)):
    return svc.packages.submission(submission_id)


@router.post("/uploads/{batch_id}/submit", response_model=ProcessingRun, status_code=202,
             responses={409: {"description": "PACKAGE_NOT_COMPLETE, RUN_IN_PROGRESS"}},
             summary="Submit for Audit: a NEW submission ID and a NEW audit run over this package's documents only, every "
                     "time (an identical package submitted again is a separate submission)")
def submit_package(batch_id: str, body: Optional[ProcessRequest] = None, svc=Depends(services)):
    auth = body.ai_authorization.model_dump() if body and body.ai_authorization else None
    return _monthly(svc).submit_for_audit(batch_id, ai_authorization=auth)


@router.get("/periods/{period_id}/submissions", response_model=list[SubmissionPackage],
            summary="Read-only submission history of the period: every ZIP package (newest first) with its completeness "
                    "report and its submissions (submission ID, audit run, status, pack, outcome, final packs)")
def list_submissions(period_id: str, svc=Depends(services)):
    out = _monthly(svc).submissions(period_id)
    finals = [f for f in svc.final_packs.list() if f.get("submission_id")]
    for pkg in out:
        for s in pkg["submissions"]:
            s["final_packs"] = sorted(({k: f[k] for k in ("final_pack_id", "generated_at", "final_content_sha256")}
                                       for f in finals if f["submission_id"] == s["submission_id"]), key=lambda f: f["generated_at"])
    return out


@router.get("/uploads/{batch_id}", response_model=BatchDetail, summary="An upload batch with its documents and runs")
def get_batch(batch_id: str, svc=Depends(services)):
    return _batch(_monthly(svc).batch_detail(batch_id))


@router.post("/uploads/{batch_id}/confirm", response_model=BatchDetail,
             summary="Confirm a validated batch (every flagged document needs a decision first)")
def confirm(batch_id: str, svc=Depends(services)):
    return _batch(_monthly(svc).confirm(batch_id))


@router.post("/uploads/{batch_id}/process", response_model=ProcessingRun, status_code=202,
             summary="Start a processing run for the period's current document set (a retry is a new run)")
def process(batch_id: str, body: Optional[ProcessRequest] = None, svc=Depends(services)):
    auth = body.ai_authorization.model_dump() if body and body.ai_authorization else None
    return _monthly(svc).process(batch_id, ai_authorization=auth)


@router.post("/periods/{period_id}/reconciliation", response_model=ProcessingRun, status_code=202,
             responses={409: {"description": "NO_CONFIRMED_DOCUMENTS, NOTHING_TO_REASSESS, RUN_IN_PROGRESS, INCOMPLETE"}},
             summary="Analyst-initiated reconciliation of one period: the deterministic engine over the period's current "
                     "confirmed document set. REASSESSMENT re-runs it for evidence received after a final pack was published "
                     "(published packs are never changed; a new final-pack version needs the normal review)")
def reconcile(period_id: str, body: ReconcileRequest, svc=Depends(services)):
    m = _monthly(svc)
    pending = period_view(svc, m.period(period_id))["pending_reassessment"]
    return m.reconcile(period_id, body.purpose, body.reason, pending_reassessment=pending,
                       ai_authorization=body.ai_authorization.model_dump() if body.ai_authorization else None)


@router.get("/periods/{period_id}/reassessment", response_model=ReassessmentPlan,
            summary="Read-only: what a reassessment of the period would use (pack reassessed, new documents, verified original "
                    "source documents, uploaded documents superseding them, what is missing) and whether it can start")
def reassessment_plan(period_id: str, svc=Depends(services)):
    m = _monthly(svc)
    return m.reassessment_plan(period_id, pending_reassessment=period_view(svc, m.period(period_id))["pending_reassessment"])


@router.get("/periods/{period_id}/exception-overview", response_model=list[dict],
            summary="Every deterministic pack of the period with its exceptions (as recorded) and their investigations "
                    "(eligibility included), in one read-only response")
def period_exception_overview(period_id: str, svc=Depends(services)):
    m = _monthly(svc)
    m.period(period_id)
    out = []
    for rec in m.repos.periods.packs(period_id):
        try:
            pack = svc.packs.peek(rec["pack_id"])  # read-only, not copied
        except AppError:
            continue  # a pack that does not verify is reported by the period view, never here
        out.append({"pack_id": rec["pack_id"],
                    "exceptions": [svc.packs.exception_view(x) for x in pack["exception_register"]["exceptions"]],
                    "investigations": svc.investigations.for_pack(rec["pack_id"], pack)})
    return out


@router.get("/periods/{period_id}/lineage", response_model=list[PackLineage],
            summary="Reassessment lineage of the period's deterministic packs (which pack reassesses which, and what changed)")
def period_lineage(period_id: str, svc=Depends(services)):
    m = _monthly(svc)
    m.period(period_id)
    return m.repos.lineage.list(period_id=period_id) if m.repos.lineage is not None else []


@router.get("/dashboard", response_model=DashboardSummary,
            summary="Dashboard counts from the authoritative records: the selected period's packs, exceptions, investigations "
                    "(by status), final packs and reviews, with the global final-pack and review totals labelled as global")
def dashboard(period_id: str | None = Query(None, max_length=16), svc=Depends(services)):
    m = _monthly(svc)
    finals = _finals_by_pack(svc)
    all_finals = [f for fs in finals.values() for f in fs]
    reviews = svc.reviews.list()
    pending = [r for r in reviews if r["status"] in ("OPEN", "ON_HOLD", "GENERATING", "GENERATION_FAILED")]
    if period_id:
        views = [period_view(svc, m.period(period_id), finals)]
    else:
        views = []
    packs = [x for v in views for x in v["packs"]]
    pack_ids = {x["pack_id"] for x in packs}
    period_finals = [f for f in all_finals if f["pack_id"] in pack_ids]
    counts = _sum_counts(packs)
    return {"period_id": period_id, "packs": len(packs), "exceptions": sum(x.get("exceptions_total", 0) for x in packs),
            "exceptions_open": sum(x.get("exceptions_open", 0) for x in packs),
            "exceptions_with_eligible_investigation": counts.pop("eligible_exceptions"), "investigations": counts,
            "final_packs_period": len(period_finals),
            "latest_final_pack_period_at": max((f["generated_at"] for f in period_finals), default=None),
            "final_packs_global": len(all_finals), "latest_final_pack_global_at": max((f["generated_at"] for f in all_finals), default=None),
            "pending_reviews_period": sum(1 for r in pending if r["pack_id"] in pack_ids), "pending_reviews_global": len(pending),
            "per_pack": [{k: x.get(k) for k in ("pack_id", "pack_kind", "exceptions_total", "exceptions_open", "final_packs",
                                                 "investigation_counts", "predecessor_pack_id")} for x in packs]}


@router.get("/documents/{document_id}", response_model=SourceDocument, summary="One source document's metadata and checks")
def get_document(document_id: str, svc=Depends(services)):
    return document_view(_monthly(svc).document(document_id))


@router.get("/documents/{document_id}/content", summary="The stored original (SHA-256 re-verified before it is returned)")
def get_document_content(document_id: str, svc=Depends(services)):
    d, data = _monthly(svc).document_content(document_id)
    media = {"PDF": "application/pdf", "CSV": "text/csv"}.get(d["file_format"], "application/octet-stream")
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in d["original_filename"])[:120] or "document"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}"',
                                                     "X-Content-SHA256": d["sha256"]})


@router.post("/documents/{document_id}/review", response_model=SourceDocument,
             summary="Record an INCLUDE / EXCLUDE decision on a document of an unconfirmed batch (never deletes)")
def review_document(document_id: str, body: DocumentReviewRequest, svc=Depends(services)):
    return document_view(_monthly(svc).review_document(document_id, body.decision, body.comment))


@router.get("/processing-runs/{run_id}", response_model=ProcessingRun, summary="One processing run")
def get_run(run_id: str, svc=Depends(services)):
    return _monthly(svc).run(run_id)


@router.get("/activity", response_model=list[ActivityEvent], summary="Recent activity (newest first)")
def activity(limit: int = Query(50, ge=1, le=500), svc=Depends(services)):
    return _monthly(svc).repos.activity.recent(limit=limit)
