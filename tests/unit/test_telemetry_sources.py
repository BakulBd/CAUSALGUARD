import time

from backend.telemetry.sources.base import ScenarioContext
from backend.telemetry.sources.composite import CompositeTelemetrySource
from backend.telemetry.sources.simulated import SimulatedTelemetrySource, status_label_for

ALL = [
    "healthy",
    "pg-table-bloat",
    "pg-lock-contention",
    "pg-vacuum-blocked",
    "pg-stale-statistics",
    "pg-replication-lag",
]


def _ctx(scenario: str, age: float = 55.0) -> ScenarioContext:
    return ScenarioContext(scenario=scenario, started_at=time.time() - age)


async def test_all_scenarios_yield_snapshot():
    src = SimulatedTelemetrySource()
    for sc in ALL:
        snap = await src.postgres_snapshot(_ctx(sc))
        assert snap.scenario == sc
        assert snap.source_mode == "simulated"
        assert 0.0 <= snap.bloat_ratio <= 1.0
        assert snap.n_live_tuples > 0


async def test_bloat_scenario_escalates_with_time():
    src = SimulatedTelemetrySource()
    early = await src.postgres_snapshot(_ctx("pg-table-bloat", age=2))
    late = await src.postgres_snapshot(_ctx("pg-table-bloat", age=60))
    assert late.n_dead_tuples > early.n_dead_tuples
    assert late.buffer_cache_hit_ratio <= early.buffer_cache_hit_ratio
    assert late.p99_latency_ms >= early.p99_latency_ms


async def test_lock_contention_has_low_cpu_high_wait():
    src = SimulatedTelemetrySource()
    snap = await src.postgres_snapshot(_ctx("pg-lock-contention"))
    assert snap.cpu_utilization_pct < 20.0
    assert snap.waiting_queries >= 10
    assert snap.blocking_pids


async def test_replication_lag_grows():
    src = SimulatedTelemetrySource()
    snap = await src.postgres_snapshot(_ctx("pg-replication-lag", age=60))
    assert snap.replication_lag_seconds > 30.0
    assert snap.waiting_queries == 0


async def test_vacuum_blocked_has_long_xact_and_autovac_on():
    src = SimulatedTelemetrySource()
    snap = await src.postgres_snapshot(_ctx("pg-vacuum-blocked", age=60))
    assert snap.autovacuum_enabled is True
    assert snap.oldest_xact_age_sec > 300.0
    assert snap.bloat_ratio > 0.1


async def test_intervention_applied_returns_recovered():
    src = SimulatedTelemetrySource()
    ctx = _ctx("pg-table-bloat")
    ctx.intervention_applied = True
    snap = await src.postgres_snapshot(ctx)
    assert snap.n_dead_tuples < 1000
    assert snap.buffer_cache_hit_ratio > 0.99


def test_status_labels():
    assert status_label_for("pg-lock-contention", False) == "ACUTE_INCIDENT_ACTIVE"
    assert status_label_for("healthy", False) == "HEALTHY"
    assert status_label_for("pg-table-bloat", True) == "RECOVERED (VERIFIED)"


async def test_simulated_health_ok():
    status = await SimulatedTelemetrySource().health()
    assert status.healthy is True
    assert status.active_mode == "simulated"


class _Boom(SimulatedTelemetrySource):
    mode = "postgres"

    async def postgres_snapshot(self, ctx):  # type: ignore[override]
        raise RuntimeError("primary down")

    async def health(self):  # type: ignore[override]
        status = await super().health()
        status.mode = "postgres"
        status.healthy = False
        return status


async def test_composite_falls_back_and_marks_degraded():
    comp = CompositeTelemetrySource(_Boom(), SimulatedTelemetrySource(), recheck_after=999)
    snap = await comp.postgres_snapshot(_ctx("pg-table-bloat"))
    assert snap.source_mode == "postgres:degraded"
    status = await comp.health()
    assert status.degraded is True
    assert "primary down" in status.detail
