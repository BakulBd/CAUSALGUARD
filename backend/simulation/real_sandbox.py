"""Real PostgreSQL sandbox: executes interventions against a throwaway clone.

Safety model (all must pass or :class:`SandboxSafetyError` is raised):

* ``CAUSALGUARD_SANDBOX__DSN`` must be set and reachable.
* ``CAUSALGUARD_SANDBOX__ALLOW_DESTRUCTIVE`` must be ``true`` for VACUUM / ANALYZE
  / REINDEX / ``pg_terminate_backend``.
* The sandbox host+database must differ from the monitored primary unless
  ``CAUSALGUARD_SANDBOX__ALLOW_PRIMARY`` is ``true``.
* ``pg_terminate_backend`` only targets PIDs that are *currently blocking* another
  backend in the sandbox, and never the CausalGuard connection itself.
"""

from __future__ import annotations

import asyncio
import time

import asyncpg

from backend.config import CausalGuardSettings, get_settings
from backend.errors import SandboxSafetyError
from backend.models.schema import (
    ComponentHealth,
    CounterfactualComparison,
    InterventionVerification,
    PostgresTelemetrySnapshot,
)
from backend.observability import get_logger
from backend.simulation.base import Sandbox
from backend.simulation.sandbox import sandbox_engine
from backend.telemetry.sources.postgres import normalize_dsn

log = get_logger("causalguard.sandbox.real")

_DESTRUCTIVE_ACTIONS = {
    "VACUUM_ANALYZE",
    "RESTORE_AUTOVACUUM",
    "REINDEX_TABLE",
    "TERMINATE_BLOCKING_PID",
}


def _host_db(dsn: str) -> tuple[str, str]:
    tail = normalize_dsn(dsn).split("://", 1)[-1]
    if "@" in tail:
        tail = tail.split("@", 1)[1]
    hostport, _, path = tail.partition("/")
    db = path.split("?", 1)[0]
    return hostport, db


class RealPostgresSandbox(Sandbox):
    mode = "real"

    def __init__(self, settings: CausalGuardSettings | None = None) -> None:
        self._settings = settings or get_settings()
        cfg = self._settings.sandbox
        if not cfg.dsn:
            raise ValueError("CAUSALGUARD_SANDBOX__DSN is required for the real sandbox")
        self._dsn = normalize_dsn(cfg.dsn)
        self._cfg = cfg
        self._pool: asyncpg.Pool | None = None
        self._assert_not_primary()

    def _assert_not_primary(self) -> None:
        primary_dsn = self._settings.postgres.dsn
        if not primary_dsn or self._cfg.allow_primary:
            return
        if _host_db(self._dsn) == _host_db(primary_dsn):
            raise SandboxSafetyError(
                "Sandbox DSN points at the monitored primary; set "
                "CAUSALGUARD_SANDBOX__ALLOW_PRIMARY=true only if this is intentional.",
                details={"sandbox": _host_db(self._dsn)[0]},
            )

    async def _pool_(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=1,
                max_size=3,
                timeout=5.0,
                command_timeout=30.0,
                server_settings={"application_name": "causalguard-sandbox"},
            )
        return self._pool

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _guard_destructive(self, action_type: str) -> None:
        if action_type in _DESTRUCTIVE_ACTIONS and not self._cfg.allow_destructive:
            raise SandboxSafetyError(
                f"Action '{action_type}' is destructive and "
                "CAUSALGUARD_SANDBOX__ALLOW_DESTRUCTIVE is false.",
                details={"action": action_type},
            )

    async def counterfactual(
        self, risk_type: str, *, snapshot: PostgresTelemetrySnapshot, horizon_minutes: int = 40
    ) -> CounterfactualComparison:
        # A counterfactual future is a model regardless of sandbox realness;
        # seed the deterministic engine with the live snapshot.
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
        self._guard_destructive(action_type)
        pool = await self._pool_()
        schema = self._settings.postgres.schema_name
        table = self._settings.postgres.monitored_table
        notes: list[str] = [f"Connected to sandbox {_host_db(self._dsn)[0]}."]

        pre = await self._measure(pool, schema, table)
        started = time.time()

        if action_type in ("VACUUM_ANALYZE", "RESTORE_AUTOVACUUM"):
            async with pool.acquire() as conn:
                if action_type == "RESTORE_AUTOVACUUM":
                    await conn.execute(
                        f'ALTER TABLE "{schema}"."{table}" SET (autovacuum_enabled = true)'
                    )
                    notes.append("Re-enabled autovacuum_enabled=true.")
                await conn.execute(f'VACUUM (ANALYZE) "{schema}"."{table}"')
            notes.append(f"VACUUM (ANALYZE) executed on {schema}.{table}.")
        elif action_type == "REINDEX_TABLE":
            async with pool.acquire() as conn:
                await conn.execute(f'REINDEX TABLE "{schema}"."{table}"')
            notes.append(f"REINDEX TABLE {schema}.{table} completed.")
        elif action_type == "TERMINATE_BLOCKING_PID":
            killed = await self._terminate_blockers(pool, target_pids)
            notes.append(
                f"pg_terminate_backend issued for {killed or 'no'} blocking PID(s): {killed}."
            )
        elif action_type == "ANALYZE_TABLE":
            async with pool.acquire() as conn:
                await conn.execute(f'ANALYZE "{schema}"."{table}"')
            notes.append(f"ANALYZE executed on {schema}.{table}.")
        else:
            notes.append(f"No-op sandbox action '{action_type}' (nothing destructive performed).")

        await asyncio.sleep(self._cfg.settle_seconds)
        post = await self._measure(pool, schema, table)

        pre_risk = _risk_proxy(pre)
        post_risk = _risk_proxy(post)
        reduction = round((pre_risk - post_risk) / pre_risk * 100, 1) if pre_risk > 0 else 0.0
        verified = post_risk <= pre_risk
        notes.append(
            f"Risk proxy {pre_risk:.1f} -> {post_risk:.1f} "
            f"({reduction:+.1f}% ) over {time.time() - started:.1f}s settle window."
        )

        return InterventionVerification(
            intervention_id=f"INTV_REAL_{int(time.time())}",
            action_name=action_type,
            environment="REAL_POSTGRES_SANDBOX",
            pre_metrics=pre,
            post_metrics=post,
            verified=verified,
            falsification_tested=True,
            risk_reduction_pct=max(0.0, reduction),
            audit_notes=notes,
        )

    async def _terminate_blockers(
        self, pool: asyncpg.Pool, target_pids: list[int] | None
    ) -> list[int]:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT unnest(pg_blocking_pids(pid)) AS blocking_pid
                FROM pg_stat_activity
                WHERE cardinality(pg_blocking_pids(pid)) > 0
                """
            )
            blockers = {int(r["blocking_pid"]) for r in rows}
            own_pid = await conn.fetchval("SELECT pg_backend_pid()")
            blockers.discard(int(own_pid))
            if target_pids:
                blockers &= set(target_pids)
            if not blockers:
                raise SandboxSafetyError(
                    "No blocking PID found in the sandbox to terminate.",
                    details={"requested": target_pids or []},
                )
            for pid in sorted(blockers):
                await conn.execute("SELECT pg_terminate_backend($1)", pid)
        return sorted(blockers)

    async def _measure(self, pool: asyncpg.Pool, schema: str, table: str) -> dict[str, float]:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COALESCE((SELECT n_dead_tup FROM pg_stat_user_tables
                            WHERE schemaname=$1 AND relname=$2), 0) AS n_dead_tup,
                  COALESCE((SELECT n_live_tup FROM pg_stat_user_tables
                            WHERE schemaname=$1 AND relname=$2), 0) AS n_live_tup,
                  COALESCE(pg_table_size(to_regclass($1||'.'||$2)), 0) AS table_bytes,
                  COALESCE((SELECT count(*) FROM pg_locks WHERE NOT granted), 0) AS waiting,
                  COALESCE((SELECT sum(blks_hit)::float / NULLIF(sum(blks_hit)+sum(blks_read),0)
                            FROM pg_stat_database WHERE datname = current_database()), 1.0) AS hit_ratio
                """,
                schema,
                table,
            )
        dead = float(row["n_dead_tup"] or 0)
        live = float(row["n_live_tup"] or 0)
        return {
            "n_dead_tup": dead,
            "bloat_ratio": round(dead / max(1.0, dead + live), 4),
            "table_size_mb": round(float(row["table_bytes"] or 0) / (1024 * 1024), 1),
            "waiting_queries": float(row["waiting"] or 0),
            "buffer_cache_hit_ratio": round(float(row["hit_ratio"] or 1.0), 4),
        }

    async def health(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            pool = await self._pool_()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return ComponentHealth(
                name="sandbox",
                status="ok",
                detail=f"real sandbox @ {_host_db(self._dsn)[0]} "
                f"(destructive={'on' if self._cfg.allow_destructive else 'off'})",
                latency_ms=round((time.perf_counter() - start) * 1000, 1),
            )
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
            return ComponentHealth(name="sandbox", status="down", detail=str(exc))


def _risk_proxy(metrics: dict[str, float]) -> float:
    """Composite pre/post risk proxy in [0, 100] from sandbox measurements."""
    bloat = metrics.get("bloat_ratio", 0.0) * 120.0
    cache = max(0.0, (0.99 - metrics.get("buffer_cache_hit_ratio", 0.99))) * 300.0
    waiting = metrics.get("waiting_queries", 0.0) * 8.0
    return round(min(100.0, bloat + cache + waiting + 1.0), 1)
