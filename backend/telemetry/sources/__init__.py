"""Pluggable telemetry sources.

``SimulatedTelemetrySource``  - deterministic scenario engine (default / demo)
``PrometheusTelemetrySource`` - live PromQL scrape of postgres/node exporters
``PostgresTelemetrySource``   - live pg_catalog / pg_stat_* introspection
``CompositeTelemetrySource``  - a real source with automatic simulated fallback

Use :func:`build_telemetry_source` to construct the configured stack.
"""

from backend.telemetry.sources.base import ScenarioContext, TelemetrySource
from backend.telemetry.sources.factory import build_telemetry_source
from backend.telemetry.sources.simulated import SimulatedTelemetrySource

__all__ = [
    "ScenarioContext",
    "SimulatedTelemetrySource",
    "TelemetrySource",
    "build_telemetry_source",
]
