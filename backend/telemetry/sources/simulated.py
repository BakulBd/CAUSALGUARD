"""Deterministic scenario engine (default telemetry source).

Reproduces the five Coroot rca-lab compatible PostgreSQL reliability scenarios as
smooth, time-progressing signals so the closed-loop pipeline, dashboard and
benchmarks are fully exercisable without a live database.
"""

from __future__ import annotations

from backend.models.schema import PostgresTelemetrySnapshot, TelemetrySourceStatus
from backend.telemetry.sources.base import ScenarioContext, TelemetrySource


def _stage(elapsed_seconds: float, ramp_seconds: float = 60.0) -> float:
    return max(0.0, min(elapsed_seconds / ramp_seconds, 1.0))


class SimulatedTelemetrySource(TelemetrySource):
    mode = "simulated"

    async def postgres_snapshot(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        return self.snapshot(ctx)

    def snapshot(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        scenario = ctx.scenario
        if ctx.intervention_applied:
            return self._recovered(scenario)
        builder = {
            "healthy": self._healthy,
            "pg-table-bloat": self._table_bloat,
            "pg-lock-contention": self._lock_contention,
            "pg-vacuum-blocked": self._vacuum_blocked,
            "pg-stale-statistics": self._stale_statistics,
            "pg-replication-lag": self._replication_lag,
        }.get(scenario, self._generic_anomaly)
        snap = builder(ctx.elapsed_seconds)
        snap.scenario = scenario
        snap.source_mode = "simulated"
        total = max(1, snap.n_dead_tuples + snap.n_live_tuples)
        snap.bloat_ratio = round(snap.n_dead_tuples / total, 4)
        return snap

    async def health(self) -> TelemetrySourceStatus:
        return TelemetrySourceStatus(
            mode="simulated",
            active_mode="simulated",
            healthy=True,
            degraded=False,
            detail="Deterministic scenario engine (no external dependency).",
            latency_ms=0.0,
        )

    # -- scenario builders ------------------------------------------------

    def _healthy(self, _elapsed: float) -> PostgresTelemetrySnapshot:
        return PostgresTelemetrySnapshot(
            n_dead_tuples=450,
            n_live_tuples=2_400_000,
            last_autovacuum_age_sec=95.0,
            last_analyze_age_sec=120.0,
            autovacuum_enabled=True,
            buffer_cache_hit_ratio=0.996,
            table_size_mb=340.0,
            index_size_mb=88.0,
            disk_read_iops=45.0,
            seq_scans=12,
            idx_scans=142_000,
            p99_latency_ms=18.4,
            error_rate_pct=0.02,
            throughput_rps=1240.0,
            waiting_queries=0,
            active_connections=24,
            cpu_utilization_pct=11.8,
            memory_utilization_pct=42.0,
            replication_lag_seconds=0.4,
        )

    def _recovered(self, scenario: str) -> PostgresTelemetrySnapshot:
        snap = self._healthy(0.0)
        snap.scenario = scenario
        snap.source_mode = "simulated"
        snap.last_autovacuum_age_sec = 20.0
        snap.last_analyze_age_sec = 25.0
        total = max(1, snap.n_dead_tuples + snap.n_live_tuples)
        snap.bloat_ratio = round(snap.n_dead_tuples / total, 4)
        return snap

    def _table_bloat(self, elapsed: float) -> PostgresTelemetrySnapshot:
        s = _stage(elapsed)
        return PostgresTelemetrySnapshot(
            n_dead_tuples=int(50_000 + s * 1_370_000),
            n_live_tuples=2_400_000,
            last_autovacuum_age_sec=1850.0 + s * 900.0,
            last_analyze_age_sec=1600.0 + s * 800.0,
            autovacuum_enabled=False,
            buffer_cache_hit_ratio=round(max(0.82, 0.995 - s * 0.16), 4),
            table_size_mb=round(340.0 + s * 360.0, 1),
            index_size_mb=round(88.0 + s * 120.0, 1),
            disk_read_iops=round(45.0 + s * 420.0, 1),
            seq_scans=int(12 + s * 40),
            idx_scans=int(142_000 * (1.0 - 0.2 * s)),
            p99_latency_ms=round(18.4 + s * 46.0, 1),
            error_rate_pct=0.04,
            throughput_rps=1180.0,
            waiting_queries=0,
            active_connections=int(24 + s * 20),
            cpu_utilization_pct=13.5,
            memory_utilization_pct=round(58.0 + s * 8.0, 1),
            replication_lag_seconds=0.6,
        )

    def _lock_contention(self, _elapsed: float) -> PostgresTelemetrySnapshot:
        return PostgresTelemetrySnapshot(
            n_dead_tuples=2400,
            n_live_tuples=2_400_000,
            last_autovacuum_age_sec=120.0,
            last_analyze_age_sec=140.0,
            autovacuum_enabled=True,
            buffer_cache_hit_ratio=0.988,
            table_size_mb=345.0,
            index_size_mb=90.0,
            disk_read_iops=32.0,
            seq_scans=8,
            idx_scans=90_000,
            p99_latency_ms=10250.0,
            error_rate_pct=84.5,
            throughput_rps=180.0,
            waiting_queries=38,
            max_lock_duration_sec=48.0,
            blocking_pids=[14022],
            active_connections=100,
            max_connections=100,
            cpu_utilization_pct=11.4,  # deliberately low: falsifies "CPU saturation"
            memory_utilization_pct=46.0,
            replication_lag_seconds=0.5,
        )

    def _vacuum_blocked(self, elapsed: float) -> PostgresTelemetrySnapshot:
        s = _stage(elapsed, ramp_seconds=75.0)
        # Autovacuum *runs* but cannot advance because a long idle-in-transaction
        # session pins the xmin horizon; dead tuples accumulate regardless.
        return PostgresTelemetrySnapshot(
            n_dead_tuples=int(120_000 + s * 900_000),
            n_live_tuples=1_900_000,
            last_autovacuum_age_sec=90.0,  # it keeps trying
            last_analyze_age_sec=300.0 + s * 400.0,
            autovacuum_enabled=True,
            buffer_cache_hit_ratio=round(max(0.88, 0.994 - s * 0.10), 4),
            table_size_mb=round(360.0 + s * 210.0, 1),
            index_size_mb=round(92.0 + s * 70.0, 1),
            disk_read_iops=round(60.0 + s * 240.0, 1),
            seq_scans=int(15 + s * 25),
            idx_scans=120_000,
            p99_latency_ms=round(21.0 + s * 34.0, 1),
            error_rate_pct=0.06,
            throughput_rps=1080.0,
            waiting_queries=0,
            max_lock_duration_sec=0.0,
            oldest_xact_age_sec=round(360.0 + s * 1800.0, 1),  # long idle-in-transaction
            blocking_pids=[20515] if s > 0.15 else [],
            active_connections=int(30 + s * 18),
            cpu_utilization_pct=round(14.0 + s * 6.0, 1),
            memory_utilization_pct=round(52.0 + s * 9.0, 1),
            replication_lag_seconds=round(0.8 + s * 4.0, 1),
        )

    def _stale_statistics(self, elapsed: float) -> PostgresTelemetrySnapshot:
        s = _stage(elapsed, ramp_seconds=70.0)
        # ANALYZE never ran after a bulk load -> planner underestimates rows ->
        # sequential scans explode, disk reads climb, latency creeps.
        return PostgresTelemetrySnapshot(
            n_dead_tuples=int(40_000 + s * 90_000),
            n_live_tuples=3_100_000,
            last_autovacuum_age_sec=200.0 + s * 300.0,
            last_analyze_age_sec=2400.0 + s * 3000.0,
            autovacuum_enabled=True,
            buffer_cache_hit_ratio=round(max(0.90, 0.995 - s * 0.09), 4),
            table_size_mb=round(520.0 + s * 120.0, 1),
            index_size_mb=round(150.0 + s * 30.0, 1),
            disk_read_iops=round(70.0 + s * 520.0, 1),
            seq_scans=int(20 + s * 900),  # runaway seq scans
            idx_scans=int(210_000 * (1.0 - 0.6 * s)),
            p99_latency_ms=round(22.0 + s * 40.0, 1),
            error_rate_pct=0.05,
            throughput_rps=round(1150.0 - s * 250.0, 1),
            waiting_queries=0,
            active_connections=int(26 + s * 22),
            cpu_utilization_pct=round(18.0 + s * 22.0, 1),  # seq scans burn CPU
            memory_utilization_pct=round(50.0 + s * 10.0, 1),
            replication_lag_seconds=round(0.7 + s * 2.0, 1),
        )

    def _replication_lag(self, elapsed: float) -> PostgresTelemetrySnapshot:
        s = _stage(elapsed, ramp_seconds=60.0)
        # WAL replay on the replica starves; primary looks fine, read-replica
        # staleness grows toward a data-freshness SLA breach.
        return PostgresTelemetrySnapshot(
            n_dead_tuples=int(30_000 + s * 20_000),
            n_live_tuples=2_600_000,
            last_autovacuum_age_sec=110.0,
            last_analyze_age_sec=180.0,
            autovacuum_enabled=True,
            buffer_cache_hit_ratio=round(0.994 - s * 0.02, 4),
            table_size_mb=round(400.0 + s * 30.0, 1),
            index_size_mb=110.0,
            disk_read_iops=round(50.0 + s * 60.0, 1),
            seq_scans=14,
            idx_scans=160_000,
            p99_latency_ms=round(19.0 + s * 22.0, 1),
            error_rate_pct=round(0.03 + s * 0.4, 3),
            throughput_rps=round(1200.0 - s * 120.0, 1),
            waiting_queries=0,
            active_connections=int(24 + s * 10),
            cpu_utilization_pct=round(12.0 + s * 5.0, 1),
            memory_utilization_pct=round(44.0 + s * 6.0, 1),
            replication_lag_seconds=round(2.0 + s * 240.0, 1),  # up to ~4 minutes
        )

    def _generic_anomaly(self, elapsed: float) -> PostgresTelemetrySnapshot:
        s = _stage(elapsed)
        return PostgresTelemetrySnapshot(
            n_dead_tuples=int(80_000 + s * 200_000),
            n_live_tuples=2_400_000,
            last_autovacuum_age_sec=400.0 + s * 600.0,
            last_analyze_age_sec=500.0,
            autovacuum_enabled=True,
            buffer_cache_hit_ratio=round(0.98 - s * 0.05, 4),
            table_size_mb=round(400.0 + s * 60.0, 1),
            index_size_mb=110.0,
            disk_read_iops=round(120.0 + s * 120.0, 1),
            seq_scans=int(30 + s * 60),
            idx_scans=140_000,
            p99_latency_ms=round(30.0 + s * 30.0, 1),
            error_rate_pct=1.2,
            throughput_rps=950.0,
            waiting_queries=2,
            active_connections=40,
            cpu_utilization_pct=24.0,
            memory_utilization_pct=52.0,
            replication_lag_seconds=1.5,
        )


def status_label_for(scenario: str, intervention_applied: bool) -> str:
    if intervention_applied:
        return "RECOVERED (VERIFIED)"
    return {
        "healthy": "HEALTHY",
        "pg-table-bloat": "PRE_INCIDENT_RISK_DETECTED",
        "pg-lock-contention": "ACUTE_INCIDENT_ACTIVE",
        "pg-vacuum-blocked": "PRE_INCIDENT_RISK_DETECTED",
        "pg-stale-statistics": "PRE_INCIDENT_RISK_DETECTED",
        "pg-replication-lag": "PRE_INCIDENT_RISK_DETECTED",
    }.get(scenario, "ANOMALY_DETECTED")
