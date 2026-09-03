"""Live PostgreSQL telemetry source test.

Runs only when ``CAUSALGUARD_TEST_PG_DSN`` points at a reachable database
(the CI ``postgres`` service container sets it).
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


async def test_postgres_source_reads_catalog(pg_dsn):
    dsn = pg_dsn
    asyncpg = pytest.importorskip("asyncpg")

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DROP TABLE IF EXISTS orders")
        await conn.execute(
            "CREATE TABLE orders (id serial primary key, status text, payload jsonb default '{}')"
        )
        await conn.execute(
            "INSERT INTO orders (status) SELECT 'paid' FROM generate_series(1, 5000)"
        )
        await conn.execute("UPDATE orders SET status = 'shipped' WHERE id % 2 = 0")
        await conn.execute("ANALYZE orders")
    finally:
        await conn.close()

    from backend.config import PostgresTargetConfig
    from backend.telemetry.sources.base import ScenarioContext
    from backend.telemetry.sources.postgres import PostgresTelemetrySource

    src = PostgresTelemetrySource(PostgresTargetConfig(dsn=dsn, monitored_table="orders"))
    try:
        snap = await src.postgres_snapshot(ScenarioContext(scenario="healthy"))
        health = await src.health()
    finally:
        await src.aclose()

    assert snap.source_mode == "postgres"
    assert snap.n_live_tuples > 0
    assert snap.table_size_mb >= 0
    assert health.healthy is True
