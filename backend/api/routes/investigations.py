"""Closed-loop multi-agent investigations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_platform, require_api_key
from backend.models.schema import DossierPage, IncidentDossier, PageMeta
from backend.services.platform import PlatformService

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post("", response_model=IncidentDossier, dependencies=[Depends(require_api_key)])
async def run_investigation(
    platform: PlatformService = Depends(get_platform),
) -> IncidentDossier:
    return await platform.run_investigation()


@router.get("", response_model=DossierPage)
async def list_investigations(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    risk_type: str | None = Query(None),
    platform: PlatformService = Depends(get_platform),
) -> DossierPage:
    items, total = await platform.list_dossiers(limit=limit, offset=offset, risk_type=risk_type)
    return DossierPage(items=items, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.get("/{dossier_id}", response_model=IncidentDossier)
async def get_investigation(
    dossier_id: str, platform: PlatformService = Depends(get_platform)
) -> IncidentDossier:
    if dossier_id in ("latest", "current"):
        return await platform.latest_dossier()
    try:
        return await platform.get_dossier(dossier_id)
    except Exception:
        # Legacy behaviour: fall back to the most recent dossier rather than 404.
        return await platform.latest_dossier()
