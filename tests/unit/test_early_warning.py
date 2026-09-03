from backend.telemetry.early_warning import early_warning_engine as ew


def test_bloat_and_autovacuum_contributors():
    score, contrib, obs = ew.evaluate_postgres_telemetry(
        n_dead_tuples=1_500_000,
        n_live_tuples=2_000_000,
        last_autovacuum_age_sec=2000.0,
        buffer_cache_hit_ratio=0.82,
        table_size_mb=750.0,
        disk_read_iops=600.0,
        p99_latency_ms=75.0,
    )
    assert score > 60
    assert contrib["dead_tuple_growth"] > 15
    assert contrib["autovacuum_inactivity"] > 0
    assert any(o.id == "OBSK_METRIC_POSTGRES_NDEAD_TUPLES_001" for o in obs)


def test_stale_statistics_contributor():
    score, contrib, _ = ew.evaluate_postgres_telemetry(
        n_dead_tuples=40_000,
        n_live_tuples=3_000_000,
        last_autovacuum_age_sec=200.0,
        buffer_cache_hit_ratio=0.95,
        table_size_mb=520.0,
        disk_read_iops=400.0,
        p99_latency_ms=45.0,
        last_analyze_age_sec=5400.0,
        seq_scans_per_min=650.0,
    )
    assert contrib["stale_statistics"] > 10
    assert score > contrib["stale_statistics"]


def test_replication_lag_contributor():
    _score, contrib, obs = ew.evaluate_postgres_telemetry(
        n_dead_tuples=30_000,
        n_live_tuples=2_600_000,
        last_autovacuum_age_sec=110.0,
        buffer_cache_hit_ratio=0.98,
        table_size_mb=420.0,
        disk_read_iops=90.0,
        p99_latency_ms=32.0,
        replication_lag_seconds=180.0,
    )
    assert contrib["replication_lag"] > 10
    assert any(o.id == "OBSK_METRIC_POSTGRES_REPLICATION_LAG_001" for o in obs)


def test_vacuum_blocked_contributor_requires_long_xact_and_autovac_on():
    _score, contrib, _ = ew.evaluate_postgres_telemetry(
        n_dead_tuples=900_000,
        n_live_tuples=1_900_000,
        last_autovacuum_age_sec=90.0,
        buffer_cache_hit_ratio=0.93,
        table_size_mb=560.0,
        disk_read_iops=250.0,
        p99_latency_ms=42.0,
        oldest_xact_age_sec=1500.0,
        autovacuum_enabled=True,
    )
    assert contrib["vacuum_blocked"] > 10


def test_acute_latency_pressure_only_on_high_p99():
    _s1, c1, _ = ew.evaluate_postgres_telemetry(
        n_dead_tuples=1,
        n_live_tuples=1_000_000,
        last_autovacuum_age_sec=1.0,
        buffer_cache_hit_ratio=0.99,
        table_size_mb=10.0,
        disk_read_iops=1.0,
        p99_latency_ms=20.0,
    )
    _s2, c2, _ = ew.evaluate_postgres_telemetry(
        n_dead_tuples=1,
        n_live_tuples=1_000_000,
        last_autovacuum_age_sec=1.0,
        buffer_cache_hit_ratio=0.99,
        table_size_mb=10.0,
        disk_read_iops=1.0,
        p99_latency_ms=9000.0,
    )
    assert c1["acute_latency_pressure"] == 0.0
    assert c2["acute_latency_pressure"] > 10.0
