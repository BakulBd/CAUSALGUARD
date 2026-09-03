import time

import httpx
import pytest
import respx

from backend.config import TelemetryConfig
from backend.telemetry.sources.base import ScenarioContext
from backend.telemetry.sources.prometheus import PrometheusTelemetrySource

pytestmark = pytest.mark.asyncio

PROM = "http://prom.test:9090"


def _instant(value):
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [time.time(), str(value)]}],
        },
    }


def _empty():
    return {"status": "success", "data": {"resultType": "vector", "result": []}}


@respx.mock
async def test_prometheus_maps_series_to_snapshot():
    values = {
        "n_dead_tup": 900000,
        "n_live_tup": 2100000,
        "blks_hit": 0.8,
        "seq_scan": 3,
        "node_cpu": 0.85,
        "pg_replication_lag": 12.0,
        "max_connections": 200,
    }

    def responder(request):
        q = request.url.params["query"]
        if "n_dead_tup" in q:
            return httpx.Response(200, json=_instant(values["n_dead_tup"]))
        if "n_live_tup" in q:
            return httpx.Response(200, json=_instant(values["n_live_tup"]))
        if "blks_hit" in q and "/" in q:
            return httpx.Response(200, json=_instant(0.94))
        if "max_connections" in q:
            return httpx.Response(200, json=_instant(values["max_connections"]))
        if "replication_lag" in q:
            return httpx.Response(200, json=_instant(values["pg_replication_lag"]))
        return httpx.Response(200, json=_empty())

    respx.get(f"{PROM}/api/v1/query").mock(side_effect=responder)

    cfg = TelemetryConfig(prometheus_url=PROM)
    src = PrometheusTelemetrySource(cfg)
    snap = await src.postgres_snapshot(ScenarioContext(scenario="healthy"))
    await src.aclose()

    assert snap.source_mode == "prometheus"
    assert snap.n_dead_tuples == 900000
    assert snap.n_live_tuples == 2100000
    assert abs(snap.buffer_cache_hit_ratio - 0.94) < 1e-6
    assert snap.replication_lag_seconds == 12.0
    assert snap.max_connections == 200
    # bloat ratio derived
    assert 0.29 < snap.bloat_ratio < 0.31


@respx.mock
async def test_prometheus_degrades_gracefully_when_all_series_missing():
    respx.get(f"{PROM}/api/v1/query").mock(return_value=httpx.Response(200, json=_empty()))
    src = PrometheusTelemetrySource(TelemetryConfig(prometheus_url=PROM))
    snap = await src.postgres_snapshot(ScenarioContext(scenario="healthy"))
    await src.aclose()
    # No series -> conservative defaults, still a valid snapshot.
    assert snap.n_dead_tuples == 0
    assert snap.p99_latency_ms >= 0.0


@respx.mock
async def test_prometheus_health_reports_unreachable():
    respx.get(f"{PROM}/-/ready").mock(side_effect=httpx.ConnectError("refused"))
    src = PrometheusTelemetrySource(TelemetryConfig(prometheus_url=PROM))
    status = await src.health()
    await src.aclose()
    assert status.healthy is False
    assert status.degraded is True
