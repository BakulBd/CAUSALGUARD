"""System state, AMD ROCm metrics, live config and telemetry source status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_platform
from backend.config import get_settings
from backend.models.schema import AMDHardwareMetrics, TelemetrySourceStatus
from backend.rocm.benchmarks.benchmark_engine import rocm_benchmark_suite
from backend.rocm.serving.rocm_engine import rocm_engine
from backend.services.platform import PlatformService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/state")
async def system_state(platform: PlatformService = Depends(get_platform)) -> dict[str, Any]:
    """Live telemetry stream for the dashboard gauges."""
    return await platform.get_system_state()


@router.get("/telemetry", tags=["telemetry"])
async def telemetry_snapshot(platform: PlatformService = Depends(get_platform)) -> dict[str, Any]:
    """The raw unified PostgreSQL telemetry snapshot from the active source."""
    return (await platform.snapshot()).model_dump()


@router.get("/telemetry-status", response_model=TelemetrySourceStatus, tags=["telemetry"])
async def telemetry_status(
    platform: PlatformService = Depends(get_platform),
) -> TelemetrySourceStatus:
    return await platform.telemetry_status()


@router.get("/amd-metrics", response_model=AMDHardwareMetrics)
def amd_metrics() -> AMDHardwareMetrics:
    return rocm_engine.get_hardware_metrics()


@router.post("/amd-benchmark")
def amd_benchmark(concurrency: int = Query(4, ge=1, le=64)) -> dict[str, Any]:
    return rocm_benchmark_suite.run_benchmark(concurrency=concurrency)


@router.get("/config")
def system_config() -> dict[str, Any]:
    """Redacted runtime configuration (safe for operators / support)."""
    return get_settings().redacted()
