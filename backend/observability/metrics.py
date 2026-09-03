"""Prometheus instrumentation for CausalGuard.

A dedicated :class:`CollectorRegistry` is used so tests can import this module
repeatedly without hitting duplicate-timeseries errors on the global default
registry, and so ``/metrics`` output stays scoped to the application.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST

REGISTRY = CollectorRegistry(auto_describe=True)

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

http_requests_total = Counter(
    "causalguard_http_requests_total",
    "Total HTTP requests processed.",
    ["method", "path", "status"],
    registry=REGISTRY,
)
http_request_duration_seconds = Histogram(
    "causalguard_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)
http_requests_in_progress = Gauge(
    "causalguard_http_requests_in_progress",
    "In-flight HTTP requests.",
    ["method", "path"],
    registry=REGISTRY,
)

investigations_total = Counter(
    "causalguard_investigations_total",
    "Closed-loop investigations executed.",
    ["risk_type", "mode"],
    registry=REGISTRY,
)
investigation_duration_seconds = Histogram(
    "causalguard_investigation_duration_seconds",
    "End-to-end investigation pipeline latency.",
    ["risk_type"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

agent_runs_total = Counter(
    "causalguard_agent_runs_total",
    "Individual agent executions.",
    ["agent", "outcome"],
    registry=REGISTRY,
)
agent_run_duration_seconds = Histogram(
    "causalguard_agent_run_duration_seconds",
    "Per-agent execution latency.",
    ["agent"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

telemetry_fetch_total = Counter(
    "causalguard_telemetry_fetch_total",
    "Telemetry source fetches.",
    ["source", "outcome"],
    registry=REGISTRY,
)
telemetry_fetch_duration_seconds = Histogram(
    "causalguard_telemetry_fetch_duration_seconds",
    "Telemetry source fetch latency.",
    ["source"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

active_risk_score = Gauge(
    "causalguard_active_risk_score",
    "Most recent composite risk score (0-100).",
    registry=REGISTRY,
)
telemetry_source_info = Gauge(
    "causalguard_telemetry_source_mode",
    "Active telemetry source mode (1 for the live mode label).",
    ["mode"],
    registry=REGISTRY,
)
build_info = Gauge(
    "causalguard_build_info",
    "Build metadata.",
    ["version", "environment"],
    registry=REGISTRY,
)


def set_build_info(version: str, environment: str) -> None:
    build_info.labels(version=version, environment=environment).set(1)


def set_source_mode(mode: str) -> None:
    for label in ("simulated", "prometheus", "postgres", "auto"):
        telemetry_source_info.labels(mode=label).set(1.0 if label == mode else 0.0)


def set_risk_score(score: float) -> None:
    active_risk_score.set(score)


@contextmanager
def track_request(method: str, path: str) -> Iterator[dict[str, str]]:
    holder = {"status": "500"}
    http_requests_in_progress.labels(method=method, path=path).inc()
    start = time.perf_counter()
    try:
        yield holder
    finally:
        elapsed = time.perf_counter() - start
        http_requests_in_progress.labels(method=method, path=path).dec()
        http_request_duration_seconds.labels(method=method, path=path).observe(elapsed)
        http_requests_total.labels(method=method, path=path, status=holder["status"]).inc()


@contextmanager
def observe_investigation(risk_type: str, mode: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        investigation_duration_seconds.labels(risk_type=risk_type).observe(
            time.perf_counter() - start
        )
        investigations_total.labels(risk_type=risk_type, mode=mode).inc()


@contextmanager
def observe_agent_run(agent: str) -> Iterator[None]:
    start = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        agent_run_duration_seconds.labels(agent=agent).observe(time.perf_counter() - start)
        agent_runs_total.labels(agent=agent, outcome=outcome).inc()


@contextmanager
def observe_telemetry_fetch(source: str) -> Iterator[None]:
    start = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        telemetry_fetch_duration_seconds.labels(source=source).observe(time.perf_counter() - start)
        telemetry_fetch_total.labels(source=source, outcome=outcome).inc()


def render_latest_metrics() -> bytes:
    return generate_latest(REGISTRY)
