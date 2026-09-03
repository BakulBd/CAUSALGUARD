"""Multi-agent execution traces."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.deps import get_platform
from backend.services.platform import PlatformService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/traces")
async def agent_traces(
    platform: PlatformService = Depends(get_platform),
) -> list[dict[str, Any]]:
    """Combined step-by-step trace from every specialised agent, time ordered."""
    return platform.agent_traces()
