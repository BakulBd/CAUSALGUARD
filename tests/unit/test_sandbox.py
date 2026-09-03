import pytest

from backend.errors import SandboxSafetyError
from backend.models.schema import PostgresTelemetrySnapshot
from backend.simulation import build_sandbox
from backend.simulation.sandbox import sandbox_engine
from backend.simulation.simulated_sandbox import SimulatedSandbox


def test_simulate_for_risk_dispatch():
    for risk in [
        "postgresql_table_bloat",
        "postgresql_lock_contention",
        "postgresql_vacuum_blocked",
        "postgresql_stale_statistics",
        "postgresql_replication_lag",
    ]:
        comp = sandbox_engine.simulate_for_risk(
            risk,
            current_dead_tuples=800_000,
            current_cache_hit_ratio=0.86,
            current_p99_latency_ms=62.0,
            current_replication_lag_seconds=90.0,
            current_waiting_queries=20,
        )
        assert comp.baseline_do_nothing.action_type == "DO_NOTHING"
        assert comp.candidate_intervention.action_type != "DO_NOTHING"
        assert comp.expected_risk_reduction_pct > 0


async def test_simulated_sandbox_intervention_verifies():
    snap = PostgresTelemetrySnapshot(n_dead_tuples=1_000_000, n_live_tuples=2_000_000)
    v = await SimulatedSandbox().execute_intervention(
        "postgresql_table_bloat", action_type="VACUUM_ANALYZE", snapshot=snap
    )
    assert v.verified is True
    assert v.risk_reduction_pct > 0
    assert v.environment == "CONTROLLED_SANDBOX"


def test_build_sandbox_defaults_to_simulated():
    assert build_sandbox().mode == "simulated"


def test_real_sandbox_rejects_primary_dsn(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__MODE", "real")
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__DSN", "postgresql://u:p@db:5432/prod")
    monkeypatch.setenv("CAUSALGUARD_POSTGRES__DSN", "postgresql://u:p@db:5432/prod")
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__ALLOW_PRIMARY", "false")

    from backend.config import CausalGuardSettings
    from backend.simulation.real_sandbox import RealPostgresSandbox

    with pytest.raises(SandboxSafetyError):
        RealPostgresSandbox(CausalGuardSettings())


def test_real_sandbox_allows_distinct_db(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__MODE", "real")
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__DSN", "postgresql://u:p@db:5432/sandbox_db")
    monkeypatch.setenv("CAUSALGUARD_POSTGRES__DSN", "postgresql://u:p@db:5432/prod")

    from backend.config import CausalGuardSettings
    from backend.simulation.real_sandbox import RealPostgresSandbox

    sb = RealPostgresSandbox(CausalGuardSettings())  # constructs without connecting
    assert sb.mode == "real"


async def test_real_sandbox_guards_destructive_without_flag(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__MODE", "real")
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__DSN", "postgresql://u:p@db:5432/sandbox_db")
    monkeypatch.setenv("CAUSALGUARD_SANDBOX__ALLOW_DESTRUCTIVE", "false")

    from backend.config import CausalGuardSettings
    from backend.simulation.real_sandbox import RealPostgresSandbox

    sb = RealPostgresSandbox(CausalGuardSettings())
    with pytest.raises(SandboxSafetyError):
        await sb.execute_intervention(
            "postgresql_table_bloat",
            action_type="VACUUM_ANALYZE",
            snapshot=PostgresTelemetrySnapshot(),
        )
