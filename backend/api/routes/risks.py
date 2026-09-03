"""Risk listing, causal graph, counterfactual simulation and verified interventions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.deps import get_platform, require_api_key
from backend.models.schema import (
    CausalGraphModel,
    CounterfactualComparison,
    InterventionVerification,
)
from backend.services.platform import PlatformService

router = APIRouter(prefix="/risks", tags=["risks"])


@router.get("")
async def list_risks(platform: PlatformService = Depends(get_platform)) -> list[dict[str, Any]]:
    return await platform.list_risks()


@router.get("/{risk_id}/causal-graph", response_model=CausalGraphModel)
async def causal_graph(
    risk_id: str, platform: PlatformService = Depends(get_platform)
) -> CausalGraphModel:
    dossier = await platform.latest_dossier()
    return dossier.causal_graph


@router.post("/{risk_id}/simulate", response_model=CounterfactualComparison)
async def simulate(
    risk_id: str, platform: PlatformService = Depends(get_platform)
) -> CounterfactualComparison:
    return await platform.simulate_counterfactual(risk_id)


@router.post(
    "/{risk_id}/verify-intervention",
    response_model=InterventionVerification,
    dependencies=[Depends(require_api_key)],
)
async def verify_intervention(
    risk_id: str, platform: PlatformService = Depends(get_platform)
) -> InterventionVerification:
    return await platform.apply_intervention()
