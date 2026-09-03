"""FastAPI application factory for CausalGuard."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.deps import build_platform_service
from backend.api.middleware import ObservabilityMiddleware, RateLimitMiddleware
from backend.api.routes import feature_router
from backend.api.routes import health as health_routes
from backend.api.routes import ws as ws_routes
from backend.config import get_settings
from backend.errors import CausalGuardError
from backend.observability import configure_logging, get_logger
from backend.observability.context import get_request_id
from backend.observability.metrics import set_build_info, set_source_mode
from backend.persistence.database import get_database

log = get_logger("causalguard.app")

API_V1 = "/api/v1"
API_LEGACY = "/api"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        fmt=settings.log_format,
        service=settings.app_name.lower(),
        version=settings.version,
        environment=settings.environment,
        force=True,
    )
    set_build_info(settings.version, settings.environment)
    set_source_mode(settings.telemetry.source_mode)
    log.info(
        "starting CausalGuard",
        extra={
            "version": settings.version,
            "environment": settings.environment,
            "source_mode": settings.telemetry.source_mode,
            "sandbox_mode": settings.sandbox.mode,
        },
    )

    db = get_database()
    try:
        await db.connect()
    except Exception as exc:
        log.error("database connect failed; running without persistence", extra={"error": str(exc)})

    platform = build_platform_service()
    app.state.platform = platform

    # Surface the resolved telemetry source once at boot.
    with contextlib.suppress(Exception):
        status = await platform.telemetry_status()
        log.info(
            "telemetry source ready",
            extra={"mode": status.mode, "active": status.active_mode, "healthy": status.healthy},
        )

    try:
        yield
    finally:
        log.info("shutting down CausalGuard")
        with contextlib.suppress(Exception):
            await platform.aclose()
        with contextlib.suppress(Exception):
            await db.disconnect()


def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CausalGuardError)
    async def _handle_app_error(_: Request, exc: CausalGuardError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("application error", extra={"code": exc.code, "message": exc.message})
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload(get_request_id()))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "Request validation failed.",
                    "details": {"errors": exc.errors()},
                    "request_id": get_request_id(),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(exc.detail),
                    "request_id": get_request_id(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled exception")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "request_id": get_request_id(),
                }
            },
        )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        fmt=settings.log_format,
        service=settings.app_name.lower(),
        version=settings.version,
        environment=settings.environment,
    )

    app = FastAPI(
        title="CausalGuard API",
        version=settings.version,
        description=(
            "Closed-loop pre-incident reliability and causal verification engine "
            "for AMD ROCm. Predict. Simulate. Verify. Prevent."
        ),
        lifespan=lifespan,
        root_path=settings.server.root_path,
    )

    # Middleware: added inner-to-outer (CORS ends up outermost).
    app.add_middleware(ObservabilityMiddleware)
    if settings.security.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware)
    if settings.server.trusted_hosts and settings.server.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.server.trusted_hosts)
    app.add_middleware(GZipMiddleware, minimum_size=settings.server.gzip_min_size)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=settings.server.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    _install_exception_handlers(app)

    # Routers
    app.include_router(health_routes.router)
    app.include_router(feature_router, prefix=API_V1)
    app.include_router(feature_router, prefix=API_LEGACY, include_in_schema=False)
    app.include_router(ws_routes.router, prefix=API_V1)
    app.include_router(ws_routes.router, prefix=API_LEGACY, include_in_schema=False)

    @app.get("/", tags=["meta"])
    def root() -> dict[str, object]:
        return {
            "system": settings.app_name,
            "tagline": "Predict. Simulate. Verify. Prevent.",
            "status": "ONLINE",
            "version": settings.version,
            "environment": settings.environment,
            "telemetry_source": settings.telemetry.source_mode,
            "rocm_accelerated": settings.rocm.enabled,
            "docs_url": "/docs",
            "api_base": API_V1,
        }

    return app
