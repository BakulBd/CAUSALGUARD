"""Reliability scenario control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.deps import get_platform, require_api_key
from backend.scenarios.state import KNOWN_SCENARIOS
from backend.services.platform import PlatformService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
def list_scenarios() -> dict[str, Any]:
    return {"scenarios": [s for s in KNOWN_SCENARIOS if s != "healthy"], "baseline": "healthy"}


@router.post("/{scenario}/start", dependencies=[Depends(require_api_key)])
async def start_scenario(
    scenario: str, platform: PlatformService = Depends(get_platform)
) -> dict[str, Any]:
    result = platform.start_scenario(scenario)
    await platform.repository.record_scenario_event(
        scenario=scenario, action="start", source_mode=platform.telemetry_source.mode
    )
    return result


@router.post("/{scenario}/stop", dependencies=[Depends(require_api_key)])
async def stop_scenario(
    scenario: str, platform: PlatformService = Depends(get_platform)
) -> dict[str, Any]:
    result = platform.stop_scenario()
    await platform.repository.record_scenario_event(
        scenario=scenario, action="stop", source_mode=platform.telemetry_source.mode
    )
    return result
