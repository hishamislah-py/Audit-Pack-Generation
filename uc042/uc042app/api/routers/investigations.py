"""Investigations (V2 tools mode), their jobs, findings, evidence and verification."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ... import ids
from ...errors import InvalidInput, NotFound
from ...services.monthly import SUBMISSION_ID_RE
from ..deps import services
from ..schemas import (SubmissionRetryRequest, AiAuthorization, AiConfiguration, AnalystReview, AnalystReviewRequest, AutoInvestigationRequest, ExceptionInvestigations,
                       ExceptionReviewHistory, InvestigationDetail, InvestigationVerification, Job, StartInvestigationRequest)

router = APIRouter(prefix="/api/v1", tags=["investigations"])


SUBMISSION_SCOPE = Query(None, max_length=40, description="Optional ZIP submission (SUB-...): only that submission's own "
                         "investigations, attempts and jobs, with that submission's analyst decisions")
SCOPED_RESPONSES = {404: {"description": "submission not found"}, 409: {"description": "SUBMISSION_PACK_MISMATCH"},
                    422: {"description": "INVALID_ID"}}


@router.get("/packs/{pack_id}/investigations", response_model=list[ExceptionInvestigations], responses=SCOPED_RESPONSES,
            summary="Investigations of every exception in a pack, with eligibility (optionally of one ZIP submission)")
def pack_investigations(pack_id: str, submission_id: Optional[str] = SUBMISSION_SCOPE, svc=Depends(services)):
    return svc.investigations.for_pack(pack_id, submission_id=submission_id)


@router.post("/submissions/{submission_id}/investigations/retry", status_code=202, response_model=dict,
             responses={404: {"description": "submission not found"}, 409: {"description": "NOTHING_TO_RETRY, SUBMISSION_NOT_AUDITED"},
                        422: {"description": "AUTHORIZATION_REQUIRED, UNKNOWN_EXCEPTION, INVALID_ID"}},
             summary="Retry, within its own ZIP submission, every exception whose investigation failed, was interrupted or was "
                     "never queued: a new recorded authorisation, fresh jobs in the submission's execution context")
def retry_submission_investigations(submission_id: str, body: SubmissionRetryRequest, svc=Depends(services)):
    if not SUBMISSION_ID_RE.match(submission_id):
        raise InvalidInput("invalid submission id", code="INVALID_ID")
    confirmation = body.authorization.model_dump() if body.authorization else None
    return svc.auto_investigations.retry_submission(submission_id, confirmation, body.exception_ids)


@router.get("/packs/{pack_id}/auto-investigations", response_model=dict, responses=SCOPED_RESPONSES,
            summary="Investigation processing status of every exception in a pack (queued, in progress, findings ready, "
                    "failed with reason, accepted / rejected by the analyst, not investigated) and its automatic authorisations. "
                    "With submission_id: the state in that ZIP submission only")
def auto_investigation_status(pack_id: str, submission_id: Optional[str] = SUBMISSION_SCOPE, svc=Depends(services)):
    return svc.auto_investigations.pack_status(pack_id, submission_id=submission_id)


@router.post("/packs/{pack_id}/auto-investigations", status_code=202, response_model=dict,
             responses={422: {"description": "AUTHORIZATION_REQUIRED"}, 409: {"description": "AI_CONFIGURATION_CHANGED"},
                        503: {"description": "PROVIDER_NOT_CONFIGURED"}},
             summary="Authorise once and queue AI investigations of every applicable exception of the pack (or, with retry, of "
                     "the exceptions whose latest attempt failed). Every exception gets a recorded outcome")
def start_auto_investigations(pack_id: str, body: AutoInvestigationRequest, svc=Depends(services)):
    confirmation = body.authorization.model_dump() if body.authorization else None
    return svc.auto_investigations.start_for_pack(pack_id, confirmation, retry=body.retry)


@router.get("/packs/{pack_id}/exceptions/{exception_id}/investigations", response_model=ExceptionInvestigations,
            responses=SCOPED_RESPONSES,
            summary="Published investigations (with eligibility), failed attempts and active jobs for one exception "
                    "(optionally of one ZIP submission)")
def exception_investigations(pack_id: str, exception_id: str, submission_id: Optional[str] = SUBMISSION_SCOPE, svc=Depends(services)):
    return svc.investigations.for_exception(pack_id, exception_id, submission_id=submission_id)


@router.post("/packs/{pack_id}/exceptions/{exception_id}/investigations", status_code=202, response_model=Job,
             responses={409: {"description": "INVESTIGATION_ACTIVE"}, 503: {"description": "PROVIDER_NOT_CONFIGURED"}},
             summary="Start a V2 tools-mode AI investigation (background job); poll GET /jobs/{job_id}")
def start_investigation(pack_id: str, exception_id: str, body: StartInvestigationRequest, svc=Depends(services)):
    confirmation = body.authorization.model_dump() if body.authorization else None
    return svc.investigations.job_view(svc.investigations.start(pack_id, exception_id, retry_of=body.retry_of,
                                                                confirmation=confirmation))


@router.get("/packs/{pack_id}/exceptions/{exception_id}/source-evidence", response_model=dict,
            summary="The exception's supporting source records, retrieved deterministically from the pack's verified sources "
                    "(the same approved retrieval an AI investigation starts from; no AI involved, nothing written)")
def source_evidence(pack_id: str, exception_id: str, svc=Depends(services)):
    return svc.investigations.source_evidence(pack_id, exception_id)


@router.get("/ai/configuration", response_model=AiConfiguration,
            summary="The configured AI provider and model an authorisation would apply to (no secrets)")
def ai_configuration(svc=Depends(services)):
    return svc.ai_authorizations.configuration()


@router.get("/ai/confirmations", response_model=list[AiAuthorization],
            summary="Pre-execution AI authorisations (append-only), optionally of one pack, exception, review or job. "
                    "(The path avoids 'auth', which this API reserves for the authentication it deliberately does not have.)")
def ai_authorizations(pack_id: Optional[str] = Query(None, max_length=64), exception_id: Optional[str] = Query(None, max_length=48),
                      review_id: Optional[str] = Query(None, max_length=40), job_id: Optional[str] = Query(None, max_length=40),
                      period_id: Optional[str] = Query(None, max_length=16), svc=Depends(services)):
    return svc.ai_authorizations.list(pack_id=pack_id, exception_id=exception_id, review_id=review_id, job_id=job_id,
                                      period_id=period_id)


@router.get("/ai/confirmations/{confirmation_id}", response_model=AiAuthorization, summary="One pre-execution AI authorisation (AIA-...)")
def ai_authorization(confirmation_id: str, svc=Depends(services)):
    return svc.ai_authorizations.get(confirmation_id)


@router.get("/jobs/{job_id}", response_model=Job, summary="Poll a background job")
def get_job(job_id: str, svc=Depends(services)):
    job = svc.runner.repo.get(ids.check("job_id", job_id))
    if job is None:
        raise NotFound("job not found")
    return svc.investigations.job_view(job)


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail,
            responses={404: {"description": "investigation or submission not found"},
                       422: {"description": "INVALID_ID, INVESTIGATION_NOT_IN_SUBMISSION"}},
            summary="Investigation summary, model metadata, eligibility and registry entry. With submission_id: the analyst "
                    "decision of that ZIP submission")
def get_investigation(investigation_id: str, submission_id: Optional[str] = SUBMISSION_SCOPE, svc=Depends(services)):
    return svc.investigations.detail(investigation_id, submission_id=submission_id)


@router.get("/investigations/{investigation_id}/findings", response_model=dict, summary="The findings exactly as stored")
def get_findings(investigation_id: str, svc=Depends(services)):
    return svc.investigations.findings(investigation_id)


@router.get("/investigations/{investigation_id}/evidence", response_model=dict,
            summary="Evidence the findings were validated against (ledger or packet), paged; no source-file search")
def get_evidence(investigation_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                 evidence_id: Optional[str] = Query(None, max_length=200), svc=Depends(services)):
    return svc.investigations.evidence(investigation_id, offset, limit, evidence_id)


@router.get("/investigations/{investigation_id}/tool-calls", response_model=dict,
            summary="The investigation's recorded tool calls (tool, arguments, status, evidence IDs; no record contents)")
def get_tool_calls(investigation_id: str, svc=Depends(services)):
    return svc.investigations.tool_calls(investigation_id)


@router.get("/investigations/{investigation_id}/verify", response_model=InvestigationVerification,
            summary="verify_published plus publication-registry verification (read-only)")
def verify_investigation(investigation_id: str, svc=Depends(services)):
    return svc.investigations.verify(investigation_id)


# ---------------------------------------------------------------- analyst review of AI investigations
@router.post("/investigations/{investigation_id}/analyst-review", response_model=AnalystReview, status_code=201,
             responses={409: {"description": "REVIEW_DECISION_CONFLICT, ARTEFACT_UNVERIFIED, PACK_BUSY, DECISION_LOCKED_FINAL_PACK_GENERATED"},
                        422: {"description": "REJECTION_REASON_REQUIRED, COMMENT_NOT_ALLOWED, REASON_NOT_ALLOWED, REVISION_REQUIRED"}},
             summary="Record the analyst's ACCEPT or REJECT decision on a published investigation (append-only; REJECT needs a "
                     "reason, kept exactly as written). Never changes the investigation or the exception's status.")
def record_analyst_review(investigation_id: str, body: AnalystReviewRequest, svc=Depends(services)):
    return svc.investigation_reviews.record(investigation_id, body.decision, body.comment, body.rejection_reason,
                                            body.expected_revision, submission_id=body.submission_id)


@router.get("/investigations/{investigation_id}/analyst-reviews", response_model=list[AnalystReview],
            summary="Every analyst decision on the investigation, oldest first (the latest is active)")
def analyst_reviews(investigation_id: str, submission_id: Optional[str] = Query(None, max_length=40), svc=Depends(services)):
    if submission_id is not None:  # validated like every other submission_id input: format (422), then existence (404)
        if not SUBMISSION_ID_RE.match(submission_id):
            raise InvalidInput("invalid submission id", code="INVALID_ID")
        if svc.submission_investigations(submission_id) is None:
            raise NotFound("submission not found")
    return svc.investigation_reviews.history(investigation_id, submission_id)


@router.get("/packs/{pack_id}/exceptions/{exception_id}/review-history", response_model=ExceptionReviewHistory,
            summary="The exception's read-only review history: AI investigation requests, completions and failures, published "
                    "investigations and the analyst's decisions, in time order (application data; not in the final pack)")
def exception_review_history(pack_id: str, exception_id: str, svc=Depends(services)):
    return svc.investigation_reviews.exception_history(pack_id, exception_id)
