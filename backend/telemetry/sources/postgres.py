"""Live PostgreSQL catalog / statistics telemetry source (asyncpg).

Read-only introspection of ``pg_stat_user_tables``, ``pg_statio_*``, ``pg_locks``,
``pg_stat_activity``, ``pg_stat_replication`` and ``pg_settings``. Every probe is
individually guarded so a restricted monitoring role or an older server still
produces a best-effort snapshot rather than an error.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import asyncpg

from backend.config import PostgresTargetConfig
from backend.models.schema import PostgresTelemetrySnapshot, TelemetrySourceStatus
from backend.observability import get_logger, observe_telemetry_fetch
from backend.telemetry.sources.base import ScenarioContext, TelemetrySource

log = get_logger("causalguard.telemetry.postgres")

_UNKNOWN_CPU_PCT = 12.0  # node CPU is not visible from inside PostgreSQL


def normalize_dsn(dsn: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix) :]
    return dsn


class PostgresTelemetrySource(TelemetrySource):
    mode = "postgres"

    def __init__(self, cfg: PostgresTargetConfig) -> None:
        if not cfg.dsn:
            raise ValueError("CAUSALGUARD_POSTGRES__DSN is required for the postgres source")
        self._cfg = cfg
        self._dsn = normalize_dsn(cfg.dsn)
        self._pool: asyncpg.Pool | None = None
        self._prev: dict[str, tuple[float, float]] = {}  # metric -> (ts, value) for rates

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._cfg.pool_min_size,
                max_size=self._cfg.pool_max_size,
                timeout=self._cfg.connect_timeout_seconds,
                command_timeout=self._cfg.statement_timeout_ms / 1000.0,
                server_settings={"application_name": "causalguard-monitor"},
            )
        return self._pool

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _rate(self, key: str, value: float, now: float) -> float:
        prev = self._prev.get(key)
        self._prev[key] = (now, value)
        if prev is None:
            return 0.0
        dt = now - prev[0]
        if dt <= 0:
            return 0.0
        return max(0.0, (value - prev[1]) / dt)

    async def _fetchrow(self, pool: asyncpg.Pool, sql: str, *args: Any) -> asyncpg.Record | None:
        try:
            async with pool.acquire() as conn:
                return await conn.fetchrow(sql, *args)
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
            log.debug("pg probe failed", extra={"sql": sql.split()[0:6], "error": str(exc)})
            return None

    async def _fetch(self, pool: asyncpg.Pool, sql: str, *args: Any) -> list[asyncpg.Record]:
        try:
            async with pool.acquire() as conn:
                return list(await conn.fetch(sql, *args))
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
            log.debug("pg probe failed", extra={"sql": sql.split()[0:6], "error": str(exc)})
            return []

    async def postgres_snapshot(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        with observe_telemetry_fetch("postgres"):
            return await self._collect(ctx)

    async def _collect(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        pool = await self._get_pool()
        now = time.time()
        schema = self._cfg.schema_name
        table = self._cfg.monitored_table
        qualified = f"{schema}.{table}"

        snap = PostgresTelemetrySnapshot(
            captured_at=now,
            source_mode="postgres",
            scenario=ctx.scenario,
            cpu_utilization_pct=_UNKNOWN_CPU_PCT,
        )

        table_stats = await self._fetchrow(
            pool,
            """
            SELECT n_dead_tup, n_live_tup, seq_scan, idx_scan,
                   EXTRACT(EPOCH FROM (now() - COALESCE(last_autovacuum, last_vacuum))) AS autovac_age,
                   EXTRACT(EPOCH FROM (now() - COALESCE(last_analyze, last_autoanalyze))) AS analyze_age
            FROM pg_stat_user_tables
            WHERE schemaname = $1 AND relname = $2
            """,
            schema,
            table,
        )
        if table_stats:
            snap.n_dead_tuples = int(table_stats["n_dead_tup"] or 0)
            snap.n_live_tuples = int(table_stats["n_live_tup"] or 0)
            snap.seq_scans = int(table_stats["seq_scan"] or 0)
            snap.idx_scans = int(table_stats["idx_scan"] or 0)
            snap.last_autovacuum_age_sec = float(table_stats["autovac_age"] or 0.0)
            snap.last_analyze_age_sec = float(table_stats["analyze_age"] or 0.0)
        snap.bloat_ratio = round(
            snap.n_dead_tuples / max(1, snap.n_dead_tuples + snap.n_live_tuples), 4
        )

        reloptions = await self._fetchrow(
            pool,
            "SELECT reloptions FROM pg_class WHERE oid = to_regclass($1)",
            qualified,
        )
        if reloptions and reloptions["reloptions"]:
            opts = {
                kv.split("=", 1)[0]: kv.split("=", 1)[1]
                for kv in reloptions["reloptions"]
                if "=" in kv
            }
            snap.autovacuum_enabled = opts.get("autovacuum_enabled", "true").lower() != "false"

        sizes = await self._fetchrow(
            pool,
            """
            SELECT pg_table_size(to_regclass($1)) AS table_bytes,
                   pg_indexes_size(to_regclass($1)) AS index_bytes
            """,
            qualified,
        )
        if sizes:
            snap.table_size_mb = round(float(sizes["table_bytes"] or 0) / (1024 * 1024), 1)
            snap.index_size_mb = round(float(sizes["index_bytes"] or 0) / (1024 * 1024), 1)

        dbstats = await self._fetchrow(
            pool,
            """
            SELECT sum(blks_hit) AS hit, sum(blks_read) AS read,
                   sum(xact_commit) AS commits
            FROM pg_stat_database WHERE datname = current_database()
            """,
        )
        if dbstats:
            hit = float(dbstats["hit"] or 0.0)
            read = float(dbstats["read"] or 0.0)
            hit_rate = self._rate("blks_hit", hit, now)
            read_rate = self._rate("blks_read", read, now)
            if hit_rate + read_rate > 0:
                snap.buffer_cache_hit_ratio = round(hit_rate / (hit_rate + read_rate), 4)
            elif hit + read > 0:
                snap.buffer_cache_hit_ratio = round(hit / (hit + read), 4)
            snap.disk_read_iops = round(read_rate, 1)
            snap.throughput_rps = round(
                self._rate("commits", float(dbstats["commits"] or 0.0), now), 1
            )

        locks = await self._fetchrow(
            pool,
            """
            SELECT count(*) FILTER (WHERE NOT granted) AS waiting,
                   count(*) FILTER (WHERE mode = 'AccessExclusiveLock' AND granted) AS access_excl
            FROM pg_locks
            """,
        )
        if locks:
            snap.waiting_queries = int(locks["waiting"] or 0)

        blockers = await self._fetch(
            pool,
            """
            SELECT DISTINCT unnest(pg_blocking_pids(pid)) AS blocking_pid,
                   EXTRACT(EPOCH FROM (now() - query_start)) AS wait_sec
            FROM pg_stat_activity
            WHERE cardinality(pg_blocking_pids(pid)) > 0
            """,
        )
        if blockers:
            snap.blocking_pids = sorted({int(r["blocking_pid"]) for r in blockers})
            snap.max_lock_duration_sec = round(
                max(float(r["wait_sec"] or 0.0) for r in blockers), 1
            )

        conns = await self._fetchrow(
            pool,
            """
            SELECT
              (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS active,
              (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_conn,
              (SELECT EXTRACT(EPOCH FROM max(now() - state_change))
                 FROM pg_stat_activity WHERE state = 'idle in transaction') AS idle_in_txn_age,
              (SELECT EXTRACT(EPOCH FROM (now() - min(xact_start)))
                 FROM pg_stat_activity WHERE xact_start IS NOT NULL) AS oldest_xact_age
            """,
        )
        if conns:
            snap.active_connections = int(conns["active"] or 0)
            snap.max_connections = int(conns["max_conn"] or 100)
            idle_age = float(conns["idle_in_txn_age"] or 0.0)
            oldest = float(conns["oldest_xact_age"] or 0.0)
            snap.oldest_xact_age_sec = round(max(idle_age, oldest), 1)

        repl = await self._fetchrow(
            pool,
            """
            SELECT COALESCE(EXTRACT(EPOCH FROM max(replay_lag)), 0) AS lag_primary
            FROM pg_stat_replication
            """,
        )
        lag = float(repl["lag_primary"]) if repl and repl["lag_primary"] is not None else 0.0
        if lag == 0.0:
            replica = await self._fetchrow(
                pool,
                "SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) AS lag_replica",
            )
            if replica and replica["lag_replica"] is not None:
                lag = max(0.0, float(replica["lag_replica"]))
        snap.replication_lag_seconds = round(lag, 1)

        stmt = await self._fetchrow(
            pool,
            """
            SELECT max(mean_exec_time) AS worst_mean, sum(calls) AS calls
            FROM pg_stat_statements
            """,
        )
        if stmt and stmt["worst_mean"] is not None:
            snap.p99_latency_ms = round(float(stmt["worst_mean"]) * 1.8, 1)
        else:
            snap.p99_latency_ms = round(_estimate_p99(snap), 1)

        return snap

    async def health(self) -> TelemetrySourceStatus:
        start = time.perf_counter()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
            ok, detail = True, str(version).split(" on ")[0]
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
            ok, detail = False, f"PostgreSQL unreachable: {exc}"
        return TelemetrySourceStatus(
            mode="postgres",
            active_mode="postgres" if ok else "simulated",
            healthy=ok,
            degraded=not ok,
            detail=detail,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            endpoint=self._dsn.rsplit("@", 1)[-1] if "@" in self._dsn else self._dsn,
        )


def _estimate_p99(snap: PostgresTelemetrySnapshot) -> float:
    base = 18.0 + max(0.0, (0.99 - snap.buffer_cache_hit_ratio)) * 400.0
    base += snap.disk_read_iops * 0.04 + snap.seq_scans * 0.02
    if snap.waiting_queries > 0:
        base += snap.waiting_queries * 260.0
    return base
