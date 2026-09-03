"""
Telemetry Normalizer.
Converts raw Prometheus scrapes, OpenTelemetry JSON spans, and structured logs
into uniform internal MetricSample, TraceSpan, and LogEntry objects.
"""

import time
from typing import Any

from backend.models.schema import LogEntry, MetricSample, TraceSpan
from backend.storage.observation_store import global_observation_store


class TelemetryNormalizer:
    @staticmethod
    def normalize_prometheus(
        metric_name: str, value: float, labels: dict[str, str], timestamp: float | None = None
    ) -> MetricSample:
        ts = timestamp or time.time()
        source = labels.get("job") or labels.get("service") or labels.get("instance") or "postgres"
        sample = MetricSample(
            name=metric_name, timestamp=ts, value=float(value), labels=labels, source=source
        )
        global_observation_store.record_metric(sample)
        return sample

    @staticmethod
    def normalize_otel_span(raw_span: dict[str, Any]) -> TraceSpan:
        trace_id = raw_span.get("trace_id") or raw_span.get("traceId", "unknown-trace")
        span_id = raw_span.get("span_id") or raw_span.get("spanId", "unknown-span")
        parent_id = raw_span.get("parent_span_id") or raw_span.get("parentSpanId")
        service = raw_span.get("service_name") or raw_span.get("service", "unknown-service")
        op = raw_span.get("operation") or raw_span.get("name", "unknown-op")
        duration = float(raw_span.get("duration_ms", 0.0))
        status = raw_span.get("status_code", "OK")
        is_err = status not in ("OK", "200") or bool(raw_span.get("error", False))

        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_id,
            service_name=service,
            operation=op,
            start_time=raw_span.get("start_time", time.time()),
            duration_ms=duration,
            status_code=str(status),
            attributes=raw_span.get("attributes", {}),
            error=is_err,
        )
        global_observation_store.record_trace(span)
        return span

    @staticmethod
    def normalize_log(
        service_name: str, level: str, message: str, attributes: dict[str, Any] | None = None
    ) -> LogEntry:
        entry = LogEntry(
            timestamp=time.time(),
            service_name=service_name,
            level=level.upper(),
            message=message,
            attributes=attributes or {},
        )
        global_observation_store.record_log(entry)
        return entry
