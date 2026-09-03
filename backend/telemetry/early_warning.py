"""
Deterministic Early-Warning Engine.
Calculates statistical signals:
- Rolling mean, rolling std dev, z-scores
- EWMA (Exponentially Weighted Moving Average)
- Trend slope (linear regression)
- CUSUM (Cumulative Sum change-point detector)
- Invariant & database health constraint checks
Combines signals into an explainable, auditable risk score (0-100).
"""

import numpy as np

from backend.config import settings
from backend.models.schema import ObservationSnapshot
from backend.storage.observation_store import global_observation_store


class EarlyWarningEngine:
    def __init__(self, ewma_alpha: float = 0.25, cusum_threshold: float = 3.5):
        self.alpha = ewma_alpha
        self.cusum_threshold = cusum_threshold

    def calculate_trend_slope(self, series: list[tuple[float, float]]) -> float:
        """Calculates linear slope (rate of change per minute)."""
        if len(series) < 2:
            return 0.0
        times = np.array([pt[0] for pt in series])
        values = np.array([pt[1] for pt in series])
        # Normalize time to minutes from start
        t_min = (times - times[0]) / 60.0
        if np.all(t_min == t_min[0]):
            return 0.0
        # Linear fit: y = m*x + c
        slope, _ = np.polyfit(t_min, values, 1)
        return float(slope)

    def calculate_ewma(self, values: list[float]) -> float:
        """Calculates Exponentially Weighted Moving Average."""
        if not values:
            return 0.0
        ewma = values[0]
        for val in values[1:]:
            ewma = self.alpha * val + (1.0 - self.alpha) * ewma
        return float(ewma)

    def detect_cusum_change_point(self, values: list[float], drift: float = 0.5) -> bool:
        """Two-sided CUSUM change point detector."""
        if len(values) < 5:
            return False
        arr = np.array(values, dtype=float)
        mean = np.mean(arr[: max(3, len(arr) // 3)])
        std = np.std(arr[: max(3, len(arr) // 3)])
        if std == 0:
            std = np.float64(1e-5)

        s_pos = 0.0
        s_neg = 0.0
        for x in arr:
            z = (x - mean) / std
            s_pos = max(0.0, s_pos + z - drift)
            s_neg = max(0.0, s_neg - z - drift)
            if s_pos > self.cusum_threshold or s_neg > self.cusum_threshold:
                return True
        return False

    def evaluate_postgres_telemetry(
        self,
        n_dead_tuples: int,
        n_live_tuples: int,
        last_autovacuum_age_sec: float,
        buffer_cache_hit_ratio: float,
        table_size_mb: float,
        disk_read_iops: float,
        p99_latency_ms: float,
        waiting_queries: int = 0,
        max_lock_duration_sec: float = 0.0,
        cpu_utilization_pct: float = 12.0,
        last_analyze_age_sec: float = 0.0,
        seq_scans_per_min: float = 0.0,
        replication_lag_seconds: float = 0.0,
        oldest_xact_age_sec: float = 0.0,
        autovacuum_enabled: bool = True,
    ) -> tuple[float, dict[str, float], list[ObservationSnapshot]]:
        """
        Calculates explainable risk score (0-100) and produces structured ObservationSnapshots.
        """
        contributors: dict[str, float] = {}
        observations: list[ObservationSnapshot] = []

        total_tuples = max(1, n_dead_tuples + n_live_tuples)
        bloat_ratio = n_dead_tuples / total_tuples

        # 1. Dead tuple bloat check
        dead_tup_score = 0.0
        if bloat_ratio > settings.thresholds.dead_tuple_bloat_threshold:
            # Scaled contribution up to 30 pts
            dead_tup_score = min(30.0, (bloat_ratio / 0.50) * 30.0)
        contributors["dead_tuple_growth"] = round(dead_tup_score, 1)

        obs_dead_tup = ObservationSnapshot(
            id="OBSK_METRIC_POSTGRES_NDEAD_TUPLES_001",
            category="metric",
            source="postgres",
            name="pg_stat_user_tables.n_dead_tup",
            window="15m",
            current_value=float(n_dead_tuples),
            baseline_value=float(n_live_tuples * 0.02),
            trend="increasing" if bloat_ratio > 0.05 else "stable",
            slope=round(bloat_ratio, 3),
            change_point=bloat_ratio > 0.10,
            z_score=round((bloat_ratio - 0.02) / 0.03, 2),
            details={
                "bloat_ratio": round(bloat_ratio, 4),
                "dead_tuples": n_dead_tuples,
                "live_tuples": n_live_tuples,
            },
        )
        observations.append(obs_dead_tup)
        global_observation_store.put_observation(obs_dead_tup)

        # 2. Autovacuum staleness check
        autovac_score = 0.0
        if last_autovacuum_age_sec > settings.thresholds.autovacuum_stale_seconds:
            # Scaled up to 25 pts
            autovac_score = min(25.0, (last_autovacuum_age_sec / 1800.0) * 25.0)
        contributors["autovacuum_inactivity"] = round(autovac_score, 1)

        obs_autovac = ObservationSnapshot(
            id="OBSK_METRIC_POSTGRES_AUTOVAC_STALE_001",
            category="metric",
            source="postgres",
            name="pg_stat_user_tables.last_autovacuum_age",
            window="30m",
            current_value=float(last_autovacuum_age_sec),
            baseline_value=120.0,
            trend="increasing" if last_autovacuum_age_sec > 300 else "stable",
            slope=1.0 if last_autovacuum_age_sec > 300 else 0.0,
            change_point=last_autovacuum_age_sec > 600,
            z_score=round(last_autovacuum_age_sec / 300.0, 2),
            details={
                "age_seconds": last_autovacuum_age_sec,
                "autovacuum_enabled": last_autovacuum_age_sec < 1800,
            },
        )
        observations.append(obs_autovac)
        global_observation_store.put_observation(obs_autovac)

        # 3. Buffer cache degradation check
        cache_score = 0.0
        if buffer_cache_hit_ratio < settings.thresholds.cache_hit_ratio_warning:
            # e.g., drops from 0.99 to 0.80 -> 20 pts
            cache_score = min(
                20.0,
                ((settings.thresholds.cache_hit_ratio_warning - buffer_cache_hit_ratio) / 0.20)
                * 20.0,
            )
        contributors["cache_degradation"] = round(cache_score, 1)

        obs_cache = ObservationSnapshot(
            id="OBSK_METRIC_POSTGRES_CACHE_HIT_001",
            category="metric",
            source="postgres",
            name="buffer_cache_hit_ratio",
            window="15m",
            current_value=float(buffer_cache_hit_ratio),
            baseline_value=0.995,
            trend="decreasing" if buffer_cache_hit_ratio < 0.95 else "stable",
            slope=-round(1.0 - buffer_cache_hit_ratio, 3),
            change_point=buffer_cache_hit_ratio < 0.92,
            z_score=round((0.995 - buffer_cache_hit_ratio) / 0.02, 2),
            details={
                "cache_hit_ratio": round(buffer_cache_hit_ratio, 4),
                "disk_read_iops": disk_read_iops,
            },
        )
        observations.append(obs_cache)
        global_observation_store.put_observation(obs_cache)

        # 4. Table physical growth check
        table_growth_score = 0.0
        if table_size_mb > 500:
            table_growth_score = min(15.0, (table_size_mb / 2000.0) * 15.0)
        contributors["table_growth"] = round(table_growth_score, 1)

        obs_size = ObservationSnapshot(
            id="OBSK_METRIC_POSTGRES_TABLE_SIZE_001",
            category="metric",
            source="postgres",
            name="pg_relation_size_mb",
            window="15m",
            current_value=float(table_size_mb),
            baseline_value=320.0,
            trend="increasing" if table_size_mb > 400 else "stable",
            slope=round((table_size_mb - 320.0) / 15.0, 2),
            change_point=table_size_mb > 600,
            z_score=round((table_size_mb - 320.0) / 50.0, 2),
            details={"size_mb": table_size_mb},
        )
        observations.append(obs_size)
        global_observation_store.put_observation(obs_size)

        # 5. Lock contention check (Acute scenario)
        lock_score = 0.0
        if (
            waiting_queries > 0
            or max_lock_duration_sec > settings.thresholds.lock_wait_seconds_threshold
        ):
            lock_score = min(45.0, max(15.0, waiting_queries * 5.0 + max_lock_duration_sec * 2.0))
        contributors["lock_contention"] = round(lock_score, 1)

        obs_lock = ObservationSnapshot(
            id="OBSK_METRIC_POSTGRES_LOCK_WAIT_001",
            category="metric",
            source="postgres",
            name="pg_stat_activity.lock_wait_events",
            window="5m",
            current_value=float(waiting_queries),
            baseline_value=0.0,
            trend="spiking" if waiting_queries > 0 else "stable",
            slope=float(waiting_queries),
            change_point=waiting_queries > 2,
            z_score=float(waiting_queries * 3.0),
            details={
                "waiting_queries": waiting_queries,
                "max_lock_duration_sec": max_lock_duration_sec,
                "cpu_utilization_pct": cpu_utilization_pct,
            },
        )
        observations.append(obs_lock)
        global_observation_store.put_observation(obs_lock)

        # 6. Stale planner statistics (missing ANALYZE -> sequential scan blowout)
        stale_stats_score = 0.0
        if last_analyze_age_sec > 1800.0 and seq_scans_per_min > 100.0:
            age_factor = min(1.0, last_analyze_age_sec / 5400.0)
            scan_factor = min(1.0, seq_scans_per_min / 800.0)
            stale_stats_score = min(25.0, 25.0 * 0.5 * (age_factor + scan_factor))
        contributors["stale_statistics"] = round(stale_stats_score, 1)
        if stale_stats_score > 0:
            obs_stats = ObservationSnapshot(
                id="OBSK_METRIC_POSTGRES_STALE_STATS_001",
                category="metric",
                source="postgres",
                name="pg_stat_user_tables.last_analyze_age",
                window="30m",
                current_value=float(last_analyze_age_sec),
                baseline_value=300.0,
                trend="increasing",
                slope=round(last_analyze_age_sec / 600.0, 2),
                change_point=last_analyze_age_sec > 1800.0,
                z_score=round(last_analyze_age_sec / 900.0, 2),
                details={
                    "last_analyze_age_sec": last_analyze_age_sec,
                    "seq_scans_per_min": seq_scans_per_min,
                },
            )
            observations.append(obs_stats)
            global_observation_store.put_observation(obs_stats)

        # 6b. Vacuum blocked (bloat rising while autovacuum keeps running because a
        #     long transaction pins the xmin horizon).
        vacuum_blocked_score = 0.0
        if (
            bloat_ratio > settings.thresholds.dead_tuple_bloat_threshold
            and autovacuum_enabled
            and last_autovacuum_age_sec < settings.thresholds.autovacuum_stale_seconds
            and oldest_xact_age_sec > 300.0
        ):
            age_factor = min(1.0, oldest_xact_age_sec / 1800.0)
            vacuum_blocked_score = min(25.0, 10.0 + 15.0 * age_factor)
        contributors["vacuum_blocked"] = round(vacuum_blocked_score, 1)
        if vacuum_blocked_score > 0:
            obs_vac_block = ObservationSnapshot(
                id="OBSK_METRIC_POSTGRES_XMIN_HORIZON_001",
                category="metric",
                source="postgres",
                name="pg_stat_activity.oldest_xact_age",
                window="30m",
                current_value=float(oldest_xact_age_sec),
                baseline_value=30.0,
                trend="increasing",
                slope=round(oldest_xact_age_sec / 300.0, 2),
                change_point=oldest_xact_age_sec > 600.0,
                z_score=round(oldest_xact_age_sec / 300.0, 2),
                details={
                    "oldest_xact_age_sec": oldest_xact_age_sec,
                    "autovacuum_running": autovacuum_enabled,
                    "not_yet_removable": True,
                },
            )
            observations.append(obs_vac_block)
            global_observation_store.put_observation(obs_vac_block)

        # 7. Replication lag (WAL replay starvation -> data-freshness SLA risk)
        repl_score = 0.0
        if replication_lag_seconds > settings.thresholds.replication_lag_warning_seconds:
            repl_score = min(
                30.0,
                (replication_lag_seconds / 300.0) * 30.0,
            )
        contributors["replication_lag"] = round(repl_score, 1)
        if repl_score > 0:
            obs_repl = ObservationSnapshot(
                id="OBSK_METRIC_POSTGRES_REPLICATION_LAG_001",
                category="metric",
                source="postgres",
                name="pg_stat_replication.replay_lag",
                window="15m",
                current_value=float(replication_lag_seconds),
                baseline_value=1.0,
                trend="increasing",
                slope=round(replication_lag_seconds / 60.0, 2),
                change_point=replication_lag_seconds > 30.0,
                z_score=round(replication_lag_seconds / 20.0, 2),
                details={"replication_lag_seconds": replication_lag_seconds},
            )
            observations.append(obs_repl)
            global_observation_store.put_observation(obs_repl)

        # 8. Acute latency pressure (query queueing already visible)
        acute_latency_score = 0.0
        if p99_latency_ms > 500.0:
            acute_latency_score = min(20.0, (p99_latency_ms / 1000.0) * 10.0 + 5.0)
        elif p99_latency_ms > 120.0:
            acute_latency_score = min(8.0, (p99_latency_ms - 120.0) / 40.0)
        contributors["acute_latency_pressure"] = round(acute_latency_score, 1)

        # 9. Historical pattern similarity
        sim_score = 0.0
        if dead_tup_score > 10 and autovac_score > 10:
            sim_score = 8.0
        elif lock_score > 15:
            sim_score = 10.0
        elif stale_stats_score > 8 or repl_score > 8 or vacuum_blocked_score > 8:
            sim_score = 7.0
        contributors["historical_pattern_similarity"] = round(sim_score, 1)

        # Calculate final composite score
        total_risk = sum(contributors.values())
        total_risk = min(100.0, max(0.0, total_risk))

        return round(total_risk, 1), contributors, observations


early_warning_engine = EarlyWarningEngine()
