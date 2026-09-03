"""Deterministic sandbox: wraps the counterfactual model in the async interface."""

from __future__ import annotations

from backend.models.schema import (
    ComponentHealth,
    CounterfactualComparison,
    InterventionVerification,
    PostgresTelemetrySnapshot,
)
from backend.simulation.base import Sandbox
from backend.simulation.sandbox import sandbox_engine


class SimulatedSandbox(Sandbox):
    mode = "simulated"

    async def counterfactual(
        self, risk_type: str, *, snapshot: PostgresTelemetrySnapshot, horizon_minutes: int = 40
    ) -> CounterfactualComparison:
        return sandbox_engine.simulate_for_risk(
            risk_type,
            current_dead_tuples=snapshot.n_dead_tuples,
            current_cache_hit_ratio=snapshot.buffer_cache_hit_ratio,
            current_p99_latency_ms=snapshot.p99_latency_ms,
            current_replication_lag_seconds=snapshot.replication_lag_seconds,
            current_waiting_queries=snapshot.waiting_queries,
            horizon_minutes=horizon_minutes,
        )

    async def execute_intervention(
        self,
        risk_type: str,
        *,
        action_type: str,
        snapshot: PostgresTelemetrySnapshot,
        target_pids: list[int] | None = None,
    ) -> InterventionVerification:
        return sandbox_engine.execute_controlled_intervention(risk_type, action_type)

    async def health(self) -> ComponentHealth:
        return ComponentHealth(
            name="sandbox", status="ok", detail="deterministic counterfactual sandbox"
        )
