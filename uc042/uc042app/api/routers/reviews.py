"""Human review sessions: selections, closing summary + preview, HOLD / GENERATE decisions and history."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response

from uc042lib.final_pack import render_html, render_pdf
from uc042lib.final_pack.model import ACKNOWLEDGEMENT_TEXT
from uc042lib.final_pack.render_pdf import PdfGlyphError
from uc042lib.pack.model import canonical

from ...errors import Conflict, InvalidInput
from ..deps import services
from ..schemas import (DecisionRequest, DecisionResponse, Job, OpenReviewRequest, PreviewMeta, PreviewRequest, ReviewHistory,
                       ReviewListItem, ReviewSession, SelectionsRequest)

router = APIRouter(prefix="/api/v1", tags=["reviews"])
HTML_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
PREVIEW_FIELDS = ("preview_id", "selections_version", "snapshot_sha256", "inputs_fingerprint", "preview_final_pack_id",
                  "preview_content_sha256", "closing_summary", "created_at")


def _view(svc, session):
    meta = svc.reviews.preview_meta(session)
    job = svc.runner.repo.get(session["preview_job_id"]) if session.get("preview_job_id") else None
    return dict(session, current_preview={k: meta[k] for k in PREVIEW_FIELDS} if meta else None,
                preview_job=svc.investigations.job_view(job) if job else None, readiness=svc.reviews.readiness(session),
                acknowledgement_text=ACKNOWLEDGEMENT_TEXT)


@router.get("/reviews", response_model=list[ReviewListItem], summary="Review sessions, newest first (read-only)")
def list_reviews(pack_id: Optional[str] = Query(None), status: Optional[Literal["OPEN", "ON_HOLD", "GENERATING", "GENERATED",
                                                                               "GENERATION_FAILED"]] = Query(None), svc=Depends(services)):
    return svc.reviews.list(pack_id, status)


@router.post("/packs/{pack_id}/reviews", response_model=ReviewSession, status_code=201,
             summary="Open a review session for a pack (returns the existing active session with 200). With submission_id: "
                     "the review of one ZIP submission's audit result (its own investigations and decisions only)")
def open_review(pack_id: str, response: Response, body: Optional[OpenReviewRequest] = None, svc=Depends(services)):
    session, created = svc.reviews.open(pack_id, body.submission_id if body else None)
    response.status_code = 201 if created else 200
    return _view(svc, session)


@router.get("/reviews/{review_id}", response_model=ReviewSession, summary="Session, selections, readiness and current preview")
def get_review(review_id: str, svc=Depends(services)):
    return _view(svc, svc.reviews.get(review_id))


@router.patch("/reviews/{review_id}/selections", response_model=ReviewSession,
              summary="Replace every exception's selection (invalidates the closing summary and preview)")
def set_selections(review_id: str, body: SelectionsRequest, svc=Depends(services)):
    session = svc.reviews.set_selections(review_id, [s.model_dump() for s in body.selections], body.expected_revision)
    return _view(svc, session)


@router.post("/reviews/{review_id}/preview", status_code=202, response_model=Job,
             summary="Generate the AI closing summary and the preview from the current selections (background job)")
def request_preview(review_id: str, body: Optional[PreviewRequest] = None, svc=Depends(services)):
    confirmation = body.authorization.model_dump() if body and body.authorization else None
    return svc.investigations.job_view(svc.reviews.request_preview(review_id, confirmation=confirmation))


@router.get("/reviews/{review_id}/preview", response_model=PreviewMeta, summary="The current preview's metadata")
def get_preview(review_id: str, svc=Depends(services)):
    meta, _ = svc.reviews.preview(review_id)
    return {k: meta[k] for k in PREVIEW_FIELDS}


@router.get("/reviews/{review_id}/preview/{kind}", summary="The current preview rendered as HTML, PDF or JSON",
            responses={200: {"content": {"text/html": {}, "application/pdf": {}, "application/json": {}}}})
def get_preview_file(review_id: str, kind: Literal["html", "pdf", "json"],
                     snapshot: Optional[str] = Query(None, pattern=r"^[0-9a-f]{64}$"), svc=Depends(services)):
    meta, document = svc.reviews.preview(review_id)
    if snapshot and snapshot != meta["snapshot_sha256"]:
        raise Conflict("this preview is no longer current", code="PREVIEW_STALE")
    headers = {"X-Snapshot-SHA256": meta["snapshot_sha256"], "ETag": f'"{meta["preview_content_sha256"]}"', "Cache-Control": "no-store"}
    if kind == "html":
        return Response(render_html(document), media_type="text/html; charset=utf-8", headers=dict(headers, **{"Content-Security-Policy": HTML_CSP}))
    if kind == "pdf":
        try:
            pdf = render_pdf(document)
        except PdfGlyphError as e:  # never a PDF with substituted characters
            raise InvalidInput(str(e), code="PDF_GLYPHS_UNSUPPORTED") from None
        return Response(pdf, media_type="application/pdf",
                        headers=dict(headers, **{"Content-Disposition": f'inline; filename="{meta["preview_final_pack_id"]}.pdf"'}))
    return Response(canonical(document), media_type="application/json", headers=headers)


@router.post("/reviews/{review_id}/decision", response_model=DecisionResponse, status_code=201,
             responses={409: {"description": "PREVIEW_STALE, BLOCKED, GENERATION_IN_PROGRESS, SESSION_CLOSED"},
                        422: {"description": "ACKNOWLEDGEMENT_REQUIRED, COMMENT_REQUIRED, SUMMARY_UNAVAILABLE_ACK_REQUIRED"},
                        500: {"description": "GENERATION_FAILED (nothing published)"}},
             summary="Record HOLD or GENERATE. GENERATE assembles, publishes and verifies the final pack.")
def decide(review_id: str, body: DecisionRequest, svc=Depends(services)):
    return svc.reviews.decide(review_id, body.model_dump())


@router.get("/reviews/{review_id}/history", response_model=ReviewHistory, summary="Append-only decisions and final-pack generation records")
def history(review_id: str, svc=Depends(services)):
    return svc.reviews.history(review_id)
