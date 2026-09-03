"""Live Prometheus (PromQL) telemetry source.

Targets the de-facto standard exporters:
  * ``postgres_exporter``  - pg_stat_user_tables_*, pg_stat_database_*, pg_locks_*
  * ``node_exporter``      - node_cpu_*, node_disk_*, node_memory_*

Every field is backed by a PromQL expression that can be overridden via
``CAUSALGUARD_TELEMETRY__PROMETHEUS_QUERIES`` (a JSON object keyed by snapshot
field name). Missing / erroring series fall back to a conservative default so a
partial exporter set still yields a usable snapshot.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from backend.config import TelemetryConfig
from backend.models.schema import PostgresTelemetrySnapshot, TelemetrySourceStatus
from backend.observability import get_logger, observe_telemetry_fetch
from backend.telemetry.sources.base import ScenarioContext, TelemetrySource

log = get_logger("causalguard.telemetry.prometheus")


def _default_queries(cfg: TelemetryConfig) -> dict[str, str]:
    rel = cfg.prometheus_relname
    dat = cfg.prometheus_datname
    win = cfg.prometheus_rate_window
    return {
        "n_dead_tuples": f'max(pg_stat_user_tables_n_dead_tup{{relname="{rel}"}})',
        "n_live_tuples": f'max(pg_stat_user_tables_n_live_tup{{relname="{rel}"}})',
        "last_autovacuum_ts": f'max(pg_stat_user_tables_last_autovacuum{{relname="{rel}"}})',
        "last_analyze_ts": f'max(pg_stat_user_tables_last_analyze{{relname="{rel}"}})',
        "cache_hit_ratio": (
            f'sum(rate(pg_stat_database_blks_hit{{datname="{dat}"}}[{win}])) / '
            f'clamp_min(sum(rate(pg_stat_database_blks_hit{{datname="{dat}"}}[{win}])) + '
            f'sum(rate(pg_stat_database_blks_read{{datname="{dat}"}}[{win}])), 1)'
        ),
        "table_size_bytes": f'max(pg_table_size_bytes{{relname="{rel}"}}) or max(pg_relation_size_bytes{{relname="{rel}"}})',
        "index_size_bytes": f'max(pg_indexes_size_bytes{{relname="{rel}"}})',
        "disk_read_iops": f"sum(rate(node_disk_reads_completed_total[{win}]))",
        "seq_scans": f'max(rate(pg_stat_user_tables_seq_scan{{relname="{rel}"}}[{win}])) * 60',
        "idx_scans": f'max(rate(pg_stat_user_tables_idx_scan{{relname="{rel}"}}[{win}])) * 60',
        "waiting_queries": (
            'sum(pg_stat_activity_count{state="active",wait_event_type="Lock"}) or '
            'sum(pg_locks_count{mode="AccessExclusiveLock"})'
        ),
        "access_exclusive_locks": 'sum(pg_locks_count{mode="AccessExclusiveLock"})',
        "max_lock_age_seconds": "max(pg_stat_activity_max_tx_duration) or vector(0)",
        "active_connections": f'sum(pg_stat_activity_count{{datname="{dat}"}})',
        "max_connections": "max(pg_settings_max_connections)",
        "cpu_utilization_pct": (
            f'100 * (1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}[{win}])))'
        ),
        "memory_utilization_pct": (
            "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))"
        ),
        "replication_lag_seconds": "max(pg_replication_lag) or max(pg_replication_lag_seconds) or vector(0)",
        "p99_latency_ms": (
            "1000 * histogram_quantile(0.99, sum(rate("
            f"pg_stat_statements_seconds_bucket[{win}])) by (le))"
        ),
        "error_rate_pct": "vector(0)",
        "throughput_rps": f'sum(rate(pg_stat_database_xact_commit{{datname="{dat}"}}[{win}]))',
    }


class PrometheusTelemetrySource(TelemetrySource):
    mode = "prometheus"

    def __init__(self, cfg: TelemetryConfig) -> None:
        self._cfg = cfg
        self._base = cfg.prometheus_url.rstrip("/")
        self._queries = {**_default_queries(cfg), **(cfg.prometheus_queries or {})}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base,
                timeout=httpx.Timeout(self._cfg.prometheus_timeout_seconds),
                headers={"Accept": "application/json"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _instant(self, expr: str) -> float | None:
        client = await self._get_client()
        try:
            resp = await client.get("/api/v1/query", params={"query": expr})
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("promql query failed", extra={"expr": expr, "error": str(exc)})
            return None
        if body.get("status") != "success":
            return None
        result = body.get("data", {}).get("result", [])
        if not result:
            return None
        try:
            return float(result[0]["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    async def _query_all(self) -> dict[str, float | None]:
        keys = list(self._queries)
        values = await asyncio.gather(*(self._instant(self._queries[k]) for k in keys))
        return dict(zip(keys, values, strict=False))

    async def postgres_snapshot(self, ctx: ScenarioContext) -> PostgresTelemetrySnapshot:
        with observe_telemetry_fetch("prometheus"):
            raw = await self._query_all()
        now = time.time()

        def val(key: str, default: float) -> float:
            v = raw.get(key)
            return float(v) if v is not None else default

        dead = int(val("n_dead_tuples", 0.0))
        live = int(val("n_live_tuples", 1.0))
        last_vac_ts = raw.get("last_autovacuum_ts")
        last_ana_ts = raw.get("last_analyze_ts")
        autovac_age = (now - last_vac_ts) if last_vac_ts else 0.0
        analyze_age = (now - last_ana_ts) if last_ana_ts else 0.0

        table_mb = val("table_size_bytes", 0.0) / (1024 * 1024)
        index_mb = val("index_size_bytes", 0.0) / (1024 * 1024)
        access_excl = val("access_exclusive_locks", 0.0)
        waiting = int(val("waiting_queries", 0.0))
        p99 = raw.get("p99_latency_ms")

        snap = PostgresTelemetrySnapshot(
            captured_at=now,
            source_mode="prometheus",
            scenario=ctx.scenario,
            n_dead_tuples=dead,
            n_live_tuples=live,
            bloat_ratio=round(dead / max(1, dead + live), 4),
            last_autovacuum_age_sec=round(autovac_age, 1),
            last_analyze_age_sec=round(analyze_age, 1),
            autovacuum_enabled=autovac_age < 1800.0 if last_vac_ts else True,
            buffer_cache_hit_ratio=round(val("cache_hit_ratio", 0.99), 4),
            table_size_mb=round(table_mb, 1),
            index_size_mb=round(index_mb, 1),
            disk_read_iops=round(val("disk_read_iops", 0.0), 1),
            seq_scans=int(val("seq_scans", 0.0)),
            idx_scans=int(val("idx_scans", 0.0)),
            p99_latency_ms=round(float(p99), 1) if p99 else round(_estimate_p99(raw), 1),
            error_rate_pct=round(val("error_rate_pct", 0.0), 3),
            throughput_rps=round(val("throughput_rps", 0.0), 1),
            waiting_queries=waiting,
            max_lock_duration_sec=round(val("max_lock_age_seconds", 0.0), 1),
            blocking_pids=[],
            active_connections=int(val("active_connections", 0.0)),
            max_connections=int(val("max_connections", 100.0)),
            cpu_utilization_pct=round(val("cpu_utilization_pct", 0.0), 1),
            memory_utilization_pct=round(val("memory_utilization_pct", 0.0), 1),
            replication_lag_seconds=round(val("replication_lag_seconds", 0.0), 1),
        )
        if access_excl > 0 and snap.waiting_queries == 0:
            snap.waiting_queries = int(access_excl)
        return snap

    async def health(self) -> TelemetrySourceStatus:
        start = time.perf_counter()
        client = await self._get_client()
        try:
            resp = await client.get("/-/ready")
            ok = resp.status_code == 200
            detail = f"Prometheus /-/ready -> {resp.status_code}"
        except httpx.HTTPError as exc:
            ok = False
            detail = f"Prometheus unreachable: {exc}"
        return TelemetrySourceStatus(
            mode="prometheus",
            active_mode="prometheus" if ok else "simulated",
            healthy=ok,
            degraded=not ok,
            detail=detail,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            endpoint=self._base,
        )


def _estimate_p99(raw: dict[str, float | None]) -> float:
    """Heuristic p99 when no app/statement histogram is available."""
    cache = raw.get("cache_hit_ratio") or 0.99
    iops = raw.get("disk_read_iops") or 0.0
    waiting = raw.get("waiting_queries") or 0.0
    base = 18.0 + max(0.0, (0.99 - cache)) * 400.0 + iops * 0.04
    if waiting > 0:
        base += waiting * 250.0
    return base
