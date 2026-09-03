"""Construct the configured telemetry source stack."""

from __future__ import annotations

from backend.config import CausalGuardSettings, get_settings
from backend.observability import get_logger, set_source_mode
from backend.telemetry.sources.base import TelemetrySource
from backend.telemetry.sources.composite import CompositeTelemetrySource
from backend.telemetry.sources.simulated import SimulatedTelemetrySource

log = get_logger("causalguard.telemetry.factory")


def build_telemetry_source(settings: CausalGuardSettings | None = None) -> TelemetrySource:
    settings = settings or get_settings()
    mode = settings.telemetry.source_mode
    set_source_mode(mode)

    if mode == "simulated":
        log.info("telemetry source: simulated")
        return SimulatedTelemetrySource()

    real: TelemetrySource
    if mode in ("prometheus", "auto"):
        try:
            from backend.telemetry.sources.prometheus import PrometheusTelemetrySource

            real = PrometheusTelemetrySource(settings.telemetry)
            log.info(
                "telemetry source: prometheus", extra={"url": settings.telemetry.prometheus_url}
            )
        except Exception as exc:
            log.error("prometheus source init failed; using simulated", extra={"error": str(exc)})
            return SimulatedTelemetrySource()
    elif mode == "postgres":
        try:
            from backend.telemetry.sources.postgres import PostgresTelemetrySource

            real = PostgresTelemetrySource(settings.postgres)
            log.info("telemetry source: postgres")
        except Exception as exc:
            log.error("postgres source init failed; using simulated", extra={"error": str(exc)})
            return SimulatedTelemetrySource()
    else:  # pragma: no cover - Literal guards this
        return SimulatedTelemetrySource()

    if settings.telemetry.fallback_to_simulated:
        return CompositeTelemetrySource(real, SimulatedTelemetrySource())
    return real
