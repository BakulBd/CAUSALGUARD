"""Telemetry source interface."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from backend.models.schema import PostgresTelemetrySnapshot, TelemetrySourceStatus

# Scenarios the platform understands. Real sources report whichever of these
# best matches the live database state; the simulated source drives them.
KNOWN_SCENARIOS = (
    "healthy",
    "pg-table-bloat",
    "pg-lock-contention",
    "pg-vacuum-blocked",
    "pg-stale-statistics",
    "pg-replication-lag",
)


@dataclass
class ScenarioContext:
    """Operator-declared scenario state, owned by the ScenarioManager."""

    scenario: str = "healthy"
    started_at: float = field(default_factory=time.time)
    intervention_applied: bool = False

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)


class TelemetrySource(ABC):
    """Abstract provider of PostgreSQL health telemetry."""

    #: one of "simulated" | "prometheus" | "postgres"
    mode: str = "simulated"

    @abstractmethod
    async def postgres_snapshot(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        """Return the current PostgreSQL health snapshot."""

    @abstractmethod
    async def health(self) -> TelemetrySourceStatus:
        """Return connectivity / freshness status for readiness checks."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        """Release any held resources (pools, clients)."""
        return None

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def derive_system_state(
        snap: PostgresTelemetrySnapshot,
        *,
        risk_score: float,
        active_risks_count: int,
        status_label: str,
    ) -> dict[str, object]:
        """Project a snapshot into the dashboard `system state` dict shape."""
        return {
            "scenario": snap.scenario,
            "status": status_label,
            "p99_latency_ms": round(snap.p99_latency_ms, 1),
            "error_rate_pct": round(snap.error_rate_pct, 3),
            "throughput_rps": round(snap.throughput_rps, 1),
            "db_cpu_pct": round(snap.cpu_utilization_pct, 1),
            "db_memory_pct": round(snap.memory_utilization_pct, 1),
            "buffer_cache_hit_ratio": round(snap.buffer_cache_hit_ratio, 4),
            "dead_tuples": int(snap.n_dead_tuples),
            "live_tuples": int(snap.n_live_tuples),
            "table_size_mb": round(snap.table_size_mb, 1),
            "disk_read_iops": round(snap.disk_read_iops, 1),
            "waiting_queries": int(snap.waiting_queries),
            "max_lock_duration_sec": round(snap.max_lock_duration_sec, 1),
            "replication_lag_seconds": round(snap.replication_lag_seconds, 1),
            "blocking_pids": list(snap.blocking_pids),
            "risk_score": round(risk_score, 1),
            "active_risks_count": active_risks_count,
            "source_mode": snap.source_mode,
        }
