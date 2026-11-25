"""Exception investigation cases: opened explicitly by an analyst for one exception; AI assistance requested per case.
Requires the database (503 DATABASE_REQUIRED otherwise). Nothing here changes a pack or an exception's status."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response

from ..deps import services
from ..schemas import CaseAiRequest, CaseDetail, CaseEntry, CaseEntryRequest, CaseSummary, Job

router = APIRouter(prefix="/api/v1", tags=["exception investigation cases"])


@router.post("/packs/{pack_id}/exceptions/{exception_id}/case", response_model=CaseDetail, status_code=201,
             summary="Open the investigation case for one exception (200 with the existing case if it is already open)")
def open_case(pack_id: str, exception_id: str, response: Response, svc=Depends(services)):
    case, created = svc.cases.open(pack_id, exception_id)
    if not created:
        response.status_code = 200
    return case


@router.get("/cases", response_model=list[CaseSummary], summary="Investigation cases, optionally of one period or pack")
def list_cases(period_id: Optional[str] = Query(None, max_length=16), pack_id: Optional[str] = Query(None, max_length=64),
               svc=Depends(services)):
    return svc.cases.list(period_id=period_id, pack_id=pack_id)


@router.get("/cases/{case_id}", response_model=CaseDetail, summary="One case with its history and the exception as recorded")
def get_case(case_id: str, svc=Depends(services)):
    return svc.cases.view(case_id)


@router.post("/cases/{case_id}/entries", response_model=CaseEntry, status_code=201,
             responses={409: {"description": "CASE_CHANGED, CASE_CLOSED"}},
             summary="Append a note, evidence, evidence gap, confirmed observation, hypothesis or human decision")
def add_entry(case_id: str, body: CaseEntryRequest, svc=Depends(services)):
    return svc.cases.add_entry(case_id, body.kind, body.text, body.evidence_refs, body.expected_revision, body.resolution, body.close)


@router.post("/cases/{case_id}/ai-investigation", response_model=Job, status_code=202,
             responses={409: {"description": "INVESTIGATION_ACTIVE, CASE_CLOSED"}, 503: {"description": "PROVIDER_NOT_CONFIGURED"}},
             summary="Request AI assistance for this case: one V2 tools-mode investigation of its exception (background job)")
def request_ai(case_id: str, body: CaseAiRequest, svc=Depends(services)):
    confirmation = body.authorization.model_dump() if body.authorization else None
    return svc.investigations.job_view(svc.cases.request_ai(case_id, retry_of=body.retry_of, note=body.note, confirmation=confirmation))
