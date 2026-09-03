from backend.config import CausalGuardSettings
from backend.telemetry.normalizer import TelemetryNormalizer
from backend.telemetry.sources.composite import CompositeTelemetrySource
from backend.telemetry.sources.factory import build_telemetry_source
from backend.telemetry.sources.simulated import SimulatedTelemetrySource


def test_factory_simulated(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_TELEMETRY__SOURCE_MODE", "simulated")
    src = build_telemetry_source(CausalGuardSettings())
    assert isinstance(src, SimulatedTelemetrySource)


def test_factory_prometheus_wraps_in_composite(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_TELEMETRY__SOURCE_MODE", "prometheus")
    monkeypatch.setenv("CAUSALGUARD_TELEMETRY__FALLBACK_TO_SIMULATED", "true")
    src = build_telemetry_source(CausalGuardSettings())
    assert isinstance(src, CompositeTelemetrySource)
    assert src.mode == "prometheus"


def test_factory_postgres_without_dsn_falls_back(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_TELEMETRY__SOURCE_MODE", "postgres")
    monkeypatch.delenv("CAUSALGUARD_POSTGRES__DSN", raising=False)
    src = build_telemetry_source(CausalGuardSettings())
    # no DSN -> PostgresTelemetrySource init raises -> simulated fallback
    assert isinstance(src, SimulatedTelemetrySource)


def test_normalizer_prometheus_sample():
    s = TelemetryNormalizer.normalize_prometheus(
        "pg_stat_user_tables_n_dead_tup", 1234.0, {"job": "postgres", "relname": "orders"}
    )
    assert s.name == "pg_stat_user_tables_n_dead_tup"
    assert s.value == 1234.0
    assert s.source == "postgres"


def test_normalizer_otel_span_and_log():
    span = TelemetryNormalizer.normalize_otel_span(
        {
            "traceId": "t1",
            "spanId": "s1",
            "service": "checkout",
            "name": "SELECT",
            "duration_ms": 12.0,
        }
    )
    assert span.trace_id == "t1" and span.service_name == "checkout"

    log = TelemetryNormalizer.normalize_log("postgres", "warning", "lock wait")
    assert log.level == "WARNING"
