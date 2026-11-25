"""Deterministic packs and exceptions (read-only; there is no endpoint that changes an exception status)."""
from fastapi import APIRouter, Depends

from ...errors import AppError
from ..deps import services
from ..schemas import ExceptionDetail, ExceptionView, PackDetail, PackListItem, PackReconciliation, PackSources

router = APIRouter(prefix="/api/v1/packs", tags=["packs"])


@router.get("", response_model=list[PackListItem], summary="Available deterministic packs, each verified")
def list_packs(svc=Depends(services)):
    out = []
    for pack_id in svc.packs.pack_ids():
        try:
            out.append({"pack_id": pack_id, "verified": True, "summary": svc.packs.summary_of(pack_id)})
        except AppError as e:
            out.append({"pack_id": pack_id, "verified": False, "problem": e.detail})
    return out


@router.get("/{pack_id}", response_model=PackDetail, summary="Pack metadata, executive summary and verification")
def get_pack(pack_id: str, svc=Depends(services)):
    pack = svc.packs.load(pack_id)
    return {"summary": svc.packs.summary(pack), "metadata": pack["metadata"], "executive_summary": pack["executive_summary"],
            "statements": pack["statements"],
            "verification": {"verified": True, "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"]}}


@router.get("/{pack_id}/reconciliation", response_model=PackReconciliation,
            summary="Internal (by currency and day) and external (by account and day) reconciliation results, as reported")
def get_reconciliation(pack_id: str, svc=Depends(services)):
    return svc.packs.reconciliation(svc.packs.load(pack_id))


@router.get("/{pack_id}/sources", response_model=PackSources, summary="Source-file register (SHA-256) and missing evidence")
def get_sources(pack_id: str, svc=Depends(services)):
    return svc.packs.sources(svc.packs.load(pack_id))


@router.get("/{pack_id}/exceptions", response_model=list[ExceptionView], summary="The pack's exception register")
def list_exceptions(pack_id: str, svc=Depends(services)):
    pack = svc.packs.load(pack_id)
    return [svc.packs.exception_view(x) for x in pack["exception_register"]["exceptions"]]


@router.get("/{pack_id}/exceptions/{exception_id}", response_model=ExceptionDetail,
            summary="One exception, its affected engine results and its investigations")
def get_exception(pack_id: str, exception_id: str, svc=Depends(services)):
    pack = svc.packs.load(pack_id)
    x = svc.packs.exception(pack, exception_id)
    return {"exception": svc.packs.exception_view(x), "affected_results": svc.packs.affected_results(pack, x),
            "investigations": svc.investigations.for_exception(pack_id, exception_id)}
