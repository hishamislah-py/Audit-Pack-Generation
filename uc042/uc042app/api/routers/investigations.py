"""Investigations (V2 tools mode), their jobs, findings, evidence and verification."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ... import ids
from ...errors import NotFound
from ..deps import services
from ..schemas import (AiAuthorization, AiConfiguration, ExceptionInvestigations, InvestigationDetail, InvestigationVerification, Job,
                       StartInvestigationRequest)

router = APIRouter(prefix="/api/v1", tags=["investigations"])


@router.get("/packs/{pack_id}/investigations", response_model=list[ExceptionInvestigations],
            summary="Investigations of every exception in a pack, with eligibility")
def pack_investigations(pack_id: str, svc=Depends(services)):
    return svc.investigations.for_pack(pack_id)


@router.get("/packs/{pack_id}/exceptions/{exception_id}/investigations", response_model=ExceptionInvestigations,
            summary="Published investigations (with eligibility), failed attempts and active jobs for one exception")
def exception_investigations(pack_id: str, exception_id: str, svc=Depends(services)):
    return svc.investigations.for_exception(pack_id, exception_id)


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
            summary="Investigation summary, model metadata, eligibility and registry entry")
def get_investigation(investigation_id: str, svc=Depends(services)):
    return svc.investigations.detail(investigation_id)


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
