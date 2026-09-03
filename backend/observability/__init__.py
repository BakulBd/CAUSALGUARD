"""Observability primitives: structured logging, Prometheus metrics, request context."""

from backend.observability.context import (
    bind_request_context,
    clear_request_context,
    get_request_id,
)
from backend.observability.logging_config import configure_logging, get_logger
from backend.observability.metrics import (
    METRICS_CONTENT_TYPE,
    observe_agent_run,
    observe_investigation,
    observe_telemetry_fetch,
    render_latest_metrics,
    set_source_mode,
    track_request,
)

__all__ = [
    "METRICS_CONTENT_TYPE",
    "bind_request_context",
    "clear_request_context",
    "configure_logging",
    "get_logger",
    "get_request_id",
    "observe_agent_run",
    "observe_investigation",
    "observe_telemetry_fetch",
    "render_latest_metrics",
    "set_source_mode",
    "track_request",
]
