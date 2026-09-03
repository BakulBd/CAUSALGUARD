"""Async database engine lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import DatabaseConfig, get_settings
from backend.observability import get_logger
from backend.persistence.models import Base

log = get_logger("causalguard.persistence")


class Database:
    """Owns the async engine and session factory for a process."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._ready = False

    @property
    def is_sqlite(self) -> bool:
        return self._config.url.startswith("sqlite")

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database.connect() has not been called")
        return self._engine

    async def connect(self) -> None:
        if self._engine is not None:
            return
        kwargs: dict[str, object] = {
            "echo": self._config.echo,
            "pool_pre_ping": self._config.pool_pre_ping,
            "future": True,
        }
        if not self.is_sqlite:
            kwargs["pool_size"] = self._config.pool_size
            kwargs["max_overflow"] = self._config.max_overflow
        self._engine = create_async_engine(self._config.url, **kwargs)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        if self._config.create_all_on_startup:
            await self.create_all()
        self._ready = True
        log.info("database connected", extra={"backend": self._config.url.split("://", 1)[0]})

    async def create_all(self) -> None:
        assert self._engine is not None
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def disconnect(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            log.info("database disconnected")
        self._engine = None
        self._sessionmaker = None
        self._ready = False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._sessionmaker is None:
            raise RuntimeError("Database.connect() has not been called")
        session = self._sessionmaker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def ping(self, timeout: float = 3.0) -> bool:
        if self._engine is None:
            return False
        try:
            async with asyncio.timeout(timeout):
                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return True
        except (SQLAlchemyError, OSError, asyncio.TimeoutError) as exc:
            log.warning("database ping failed", extra={"error": str(exc)})
            return False


_database: Database | None = None


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database(get_settings().database)
    return _database


def reset_database_singleton() -> None:
    """Testing hook."""
    global _database
    _database = None
