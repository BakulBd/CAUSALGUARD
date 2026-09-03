"""Liveness, readiness and Prometheus metrics endpoints (unversioned, top level)."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, Response

from backend.api.deps import get_platform
from backend.config import get_settings
from backend.models.schema import HealthReport, ReadinessReport
from backend.observability.metrics import METRICS_CONTENT_TYPE, render_latest_metrics
from backend.services.platform import PlatformService

router = APIRouter(tags=["health"])

_BOOT = time.time()


@router.get("/health", response_model=HealthReport)
def health() -> HealthReport:
    s = get_settings()
    return HealthReport(
        status="ok",
        service=s.app_name.lower(),
        version=s.version,
        environment=s.environment,
        uptime_seconds=round(time.time() - _BOOT, 1),
    )


@router.get("/ready", response_model=ReadinessReport)
async def ready(
    response: Response, platform: PlatformService = Depends(get_platform)
) -> ReadinessReport:
    s = get_settings()
    checks = await platform.readiness()
    worst: Literal["ok", "degraded", "down"] = "ok"
    for c in checks:
        if c.status == "down":
            worst = "down"
            break
        if c.status == "degraded" and worst == "ok":
            worst = "degraded"
    if worst == "down":
        response.status_code = 503
    return ReadinessReport(
        status=worst, service=s.app_name.lower(), version=s.version, checks=checks
    )


@router.get("/metrics")
def metrics() -> Response:
    if not get_settings().observability.metrics_enabled:
        return Response(status_code=404)
    return Response(content=render_latest_metrics(), media_type=METRICS_CONTENT_TYPE)
