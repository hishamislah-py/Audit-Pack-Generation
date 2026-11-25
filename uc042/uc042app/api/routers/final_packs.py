"""Published final audit packs (immutable; read-only access)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response

from ..deps import services
from ..schemas import FinalPackDetail, FinalPackListItem, FinalPackVerification
from .reviews import HTML_CSP

router = APIRouter(prefix="/api/v1/final-packs", tags=["final packs"])


@router.get("", response_model=list[FinalPackListItem], summary="Published final packs, oldest version first. With pack_id and "
                                                                  "lineage=true: every version of the pack's reassessment lineage")
def list_final_packs(pack_id: Optional[str] = Query(None), lineage: bool = Query(False), svc=Depends(services)):
    return svc.final_packs.list(pack_id, lineage=lineage)


@router.get("/{final_pack_id}", response_model=FinalPackDetail, summary="Metadata, manifest files and generation record")
def get_final_pack(final_pack_id: str, svc=Depends(services)):
    return svc.final_packs.detail(final_pack_id)


@router.get("/{final_pack_id}/verify", response_model=FinalPackVerification, summary="Manifest, content hash and rendering checks")
def verify_final_pack(final_pack_id: str, svc=Depends(services)):
    return svc.final_packs.verify(final_pack_id)


def _file(svc, final_pack_id, kind):
    data, media, digest = svc.final_packs.file(final_pack_id, kind)
    headers = {"ETag": f'"{digest}"', "Cache-Control": "private, max-age=0"}
    if kind == "html":
        headers["Content-Security-Policy"] = HTML_CSP
    if kind == "pdf":
        headers["Content-Disposition"] = f'inline; filename="{final_pack_id}.pdf"'
    return Response(data, media_type=media, headers=headers)


@router.get("/{final_pack_id}/html", summary="report.html (verified against the manifest)", responses={200: {"content": {"text/html": {}}}})
def final_html(final_pack_id: str, svc=Depends(services)):
    return _file(svc, final_pack_id, "html")


@router.get("/{final_pack_id}/pdf", summary="report.pdf (verified against the manifest)", responses={200: {"content": {"application/pdf": {}}}})
def final_pdf(final_pack_id: str, svc=Depends(services)):
    return _file(svc, final_pack_id, "pdf")


@router.get("/{final_pack_id}/json", summary="final_pack.json, the canonical source (verified against the manifest)",
            responses={200: {"content": {"application/json": {}}}})
def final_json(final_pack_id: str, svc=Depends(services)):
    return _file(svc, final_pack_id, "json")
