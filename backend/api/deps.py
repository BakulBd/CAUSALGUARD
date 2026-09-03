"""FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Request

from backend.config import get_settings
from backend.persistence.database import get_database
from backend.persistence.repository import DossierRepository
from backend.security import require_api_key  # re-exported for routers
from backend.services.platform import PlatformService
from backend.simulation import build_sandbox
from backend.telemetry.sources import build_telemetry_source

__all__ = ["build_platform_service", "get_platform", "require_api_key"]

_fallback_platform: PlatformService | None = None


def build_platform_service() -> PlatformService:
    """Construct a PlatformService from current settings (no async I/O yet)."""
    settings = get_settings()
    repository = DossierRepository(get_database(), retention=settings.database.retention_dossiers)
    return PlatformService(
        telemetry_source=build_telemetry_source(settings),
        sandbox=build_sandbox(settings),
        repository=repository,
        settings=settings,
    )


def get_platform(request: Request) -> PlatformService:
    """Return the app-scoped PlatformService.

    Uses the instance wired up by the lifespan handler when present; otherwise
    lazily builds a process-wide fallback so routes work under a bare
    ``TestClient(app)`` (no lifespan) too.
    """
    platform = getattr(request.app.state, "platform", None)
    if platform is not None:
        return platform
    global _fallback_platform
    if _fallback_platform is None:
        _fallback_platform = build_platform_service()
    return _fallback_platform
