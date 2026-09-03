"""Shared test fixtures.

Environment is pinned *before* any backend import so the cached settings
singleton picks up test-safe defaults (quiet logs, throwaway sqlite db,
simulated telemetry, rate limiting off).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP_DB = Path(tempfile.gettempdir()) / "causalguard-test.db"
os.environ.setdefault("CAUSALGUARD_ENVIRONMENT", "test")
os.environ.setdefault("CAUSALGUARD_LOG_LEVEL", "WARNING")
os.environ.setdefault("CAUSALGUARD_LOG_FORMAT", "console")
os.environ.setdefault("CAUSALGUARD_TELEMETRY__SOURCE_MODE", "simulated")
os.environ.setdefault("CAUSALGUARD_SANDBOX__MODE", "simulated")
os.environ.setdefault("CAUSALGUARD_SECURITY__RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("CAUSALGUARD_SECURITY__API_KEYS", "")
os.environ.setdefault("CAUSALGUARD_DATABASE__URL", f"sqlite+aiosqlite:///{_TMP_DB}")


@pytest.fixture(autouse=True)
def _isolate_scenario() -> Iterator[None]:
    from backend.scenarios.state import reset_scenario

    reset_scenario()
    yield
    reset_scenario()


@pytest.fixture(autouse=True)
def _fresh_db() -> Iterator[None]:
    if _TMP_DB.exists():
        _TMP_DB.unlink()
    from backend.persistence.database import reset_database_singleton

    reset_database_singleton()
    yield
    if _TMP_DB.exists():
        _TMP_DB.unlink()


@pytest.fixture
def settings():
    from backend.config import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client() -> Iterator[object]:
    """TestClient that runs the app lifespan (db connect, platform wiring)."""
    from fastapi.testclient import TestClient

    from backend.api.deps import _fallback_platform  # noqa: F401
    from backend.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
async def platform():
    """A standalone PlatformService (simulated) with a live sqlite repository."""
    from backend.api.deps import build_platform_service
    from backend.persistence.database import get_database

    db = get_database()
    await db.connect()
    svc = build_platform_service()
    try:
        yield svc
    finally:
        await svc.aclose()
        await db.disconnect()


@pytest.fixture
def pg_dsn() -> str:
    dsn = os.environ.get("CAUSALGUARD_TEST_PG_DSN")
    if not dsn:
        pytest.skip("CAUSALGUARD_TEST_PG_DSN not set; skipping live PostgreSQL test")
    return dsn
