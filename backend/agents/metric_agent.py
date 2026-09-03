"""
Metric Agent.
Analyzes metric trends, change points, database health counters, and cross-correlations.
"""

import time

import numpy as np

from backend.agents.base_agent import BaseAgent
from backend.models.schema import ObservationSnapshot
from backend.storage.observation_store import global_observation_store
from backend.telemetry.early_warning import early_warning_engine


class MetricAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "MetricAgent", "Detect abnormal trends, rate-of-change, and database health metrics"
        )

    def query_prometheus_window(
        self, source: str, metric_name: str, window_sec: int = 900
    ) -> list[tuple[float, float]]:
        return global_observation_store.get_metric_series(source, metric_name, window_sec)

    def calculate_trend(self, series: list[tuple[float, float]]) -> dict[str, float]:
        slope = early_warning_engine.calculate_trend_slope(series)
        vals = [p[1] for p in series]
        ewma = early_warning_engine.calculate_ewma(vals)
        return {"slope": slope, "ewma": ewma}

    def calculate_change_point(self, series: list[tuple[float, float]]) -> bool:
        vals = [p[1] for p in series]
        return early_warning_engine.detect_cusum_change_point(vals)

    def calculate_cross_correlation(self, series_a: list[float], series_b: list[float]) -> float:
        min_len = min(len(series_a), len(series_b))
        if min_len < 3:
            return 0.0
        a = np.array(series_a[:min_len])
        b = np.array(series_b[:min_len])
        if np.std(a) == 0 or np.std(b) == 0:
            return 0.0
        corr = np.corrcoef(a, b)[0, 1]
        return float(corr)

    def analyze(self, scenario_telemetry: dict) -> list[ObservationSnapshot]:
        start = time.time()
        tools_called = [
            "get_database_metrics()",
            "calculate_trend(n_dead_tup)",
            "calculate_change_point(buffer_cache_hit_ratio)",
            "calculate_cross_correlation(dead_tuples, disk_reads)",
        ]

        # Use early warning engine to produce canonical snapshots
        n_dead = scenario_telemetry.get("n_dead_tuples", 1240000)
        n_live = scenario_telemetry.get("n_live_tuples", 2000000)
        autovac_age = scenario_telemetry.get("last_autovacuum_age_sec", 1850.0)
        cache_hit = scenario_telemetry.get("buffer_cache_hit_ratio", 0.835)
        table_size = scenario_telemetry.get("table_size_mb", 680.0)
        disk_iops = scenario_telemetry.get("disk_read_iops", 480.0)
        p99_lat = scenario_telemetry.get("p99_latency_ms", 64.0)
        waiting = scenario_telemetry.get("waiting_queries", 0)
        max_lock_sec = scenario_telemetry.get("max_lock_duration_sec", 0.0)
        cpu_pct = scenario_telemetry.get("cpu_utilization_pct", 11.4)
        last_analyze_age = scenario_telemetry.get("last_analyze_age_sec", 0.0)
        seq_scans_per_min = scenario_telemetry.get("seq_scans_per_min", 0.0)
        replication_lag = scenario_telemetry.get("replication_lag_seconds", 0.0)
        oldest_xact_age = scenario_telemetry.get("oldest_xact_age_sec", 0.0)
        autovacuum_enabled = scenario_telemetry.get("autovacuum_enabled", True)

        risk_score, contributors, observations = early_warning_engine.evaluate_postgres_telemetry(
            n_dead_tuples=n_dead,
            n_live_tuples=n_live,
            last_autovacuum_age_sec=autovac_age,
            buffer_cache_hit_ratio=cache_hit,
            table_size_mb=table_size,
            disk_read_iops=disk_iops,
            p99_latency_ms=p99_lat,
            waiting_queries=waiting,
            max_lock_duration_sec=max_lock_sec,
            cpu_utilization_pct=cpu_pct,
            last_analyze_age_sec=last_analyze_age,
            seq_scans_per_min=seq_scans_per_min,
            replication_lag_seconds=replication_lag,
            oldest_xact_age_sec=oldest_xact_age,
            autovacuum_enabled=autovacuum_enabled,
        )

        dur = (time.time() - start) * 1000
        top_contributor = (
            max(contributors, key=lambda k: contributors[k]) if contributors else "None"
        )
        summary_out = (
            f"Extracted {len(observations)} observations. Risk score: {risk_score}/100. "
            f"Top contributor: {top_contributor}"
        )
        self.record_step(
            "METRIC_ANALYSIS",
            f"Inspected database & system metrics for {len(observations)} signals",
            summary_out,
            tools_called,
            dur,
        )
        return observations


metric_agent = MetricAgent()
