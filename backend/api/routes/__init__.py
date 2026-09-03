"""API routers."""

from fastapi import APIRouter

from backend.api.routes import (
    agents,
    benchmarks,
    dossier,
    investigations,
    risks,
    scenarios,
    system,
)

# Feature routers mounted under a version prefix (and, for compatibility, under
# the legacy unversioned prefix).
feature_router = APIRouter()
feature_router.include_router(system.router)
feature_router.include_router(scenarios.router)
feature_router.include_router(investigations.router)
feature_router.include_router(risks.router)
feature_router.include_router(agents.router)
feature_router.include_router(benchmarks.router)
feature_router.include_router(dossier.router)

__all__ = ["feature_router"]
