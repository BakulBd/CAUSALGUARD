"""A real telemetry source with automatic fallback to the simulated engine."""

from __future__ import annotations

import time

from backend.models.schema import PostgresTelemetrySnapshot, TelemetrySourceStatus
from backend.observability import get_logger
from backend.telemetry.sources.base import ScenarioContext, TelemetrySource
from backend.telemetry.sources.simulated import SimulatedTelemetrySource

log = get_logger("causalguard.telemetry.composite")


class CompositeTelemetrySource(TelemetrySource):
    """Try ``primary``; on failure serve ``fallback`` and mark the result degraded.

    A short circuit-breaker (``recheck_after``) avoids hammering a down primary on
    every request while still recovering automatically once it returns.
    """

    def __init__(
        self,
        primary: TelemetrySource,
        fallback: SimulatedTelemetrySource | None = None,
        *,
        recheck_after: float = 15.0,
    ) -> None:
        self._primary = primary
        self._fallback = fallback or SimulatedTelemetrySource()
        self._recheck_after = recheck_after
        self._primary_down_since: float | None = None
        self._last_error: str = ""
        self.mode = primary.mode

    def _should_try_primary(self) -> bool:
        if self._primary_down_since is None:
            return True
        return (time.time() - self._primary_down_since) >= self._recheck_after

    async def postgres_snapshot(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        if self._should_try_primary():
            try:
                snap = await self._primary.postgres_snapshot(ctx)
                if self._primary_down_since is not None:
                    log.info("telemetry primary recovered", extra={"mode": self._primary.mode})
                self._primary_down_since = None
                self._last_error = ""
                return snap
            except Exception as exc:
                self._last_error = str(exc)
                if self._primary_down_since is None:
                    log.warning(
                        "telemetry primary failed, falling back to simulated",
                        extra={"mode": self._primary.mode, "error": self._last_error},
                    )
                self._primary_down_since = time.time()
        snap = await self._fallback.postgres_snapshot(ctx)
        snap.source_mode = f"{self._primary.mode}:degraded"
        return snap

    async def health(self) -> TelemetrySourceStatus:
        status = await self._primary.health()
        if not status.healthy:
            status.degraded = True
            status.active_mode = "simulated"
            if self._last_error:
                status.detail = f"{status.detail} | last error: {self._last_error}"
        return status

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._fallback.aclose()
