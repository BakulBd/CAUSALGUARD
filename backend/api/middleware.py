"""Cross-cutting HTTP middleware: request id, access log, metrics, rate limit, headers."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from backend.config import get_settings
from backend.errors import CausalGuardError
from backend.observability import bind_request_context, clear_request_context, get_logger
from backend.observability.context import new_request_id
from backend.observability.metrics import track_request
from backend.security import SlidingWindowRateLimiter, security_headers

log = get_logger("causalguard.http")

_REQUEST_ID_HEADER = "x-request-id"


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Assign a request id, emit a structured access log, record Prometheus metrics."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._settings = get_settings()

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(_REQUEST_ID_HEADER)
        request_id = incoming or new_request_id()
        bind_request_context(
            request_id,
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else "-",
        )
        start = time.perf_counter()
        path_tmpl = request.url.path
        status_code = 500
        try:
            with track_request(request.method, path_tmpl) as m:
                response = await call_next(request)
                status_code = response.status_code
                m["status"] = str(status_code)
                # refine metric label to the matched route template if available
                tmpl = _route_template(request)
                if tmpl != path_tmpl:
                    m["path"] = tmpl
            response.headers[_REQUEST_ID_HEADER] = request_id
            if self._settings.security.security_headers_enabled:
                for k, v in security_headers(self._settings.security.hsts_enabled).items():
                    response.headers.setdefault(k, v)
            return response
        except Exception:
            log.exception("unhandled error in request pipeline")
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if self._settings.observability.request_log_enabled and not request.url.path.startswith(
                ("/metrics", "/health", "/ready")
            ):
                level = (
                    log.warning
                    if elapsed_ms >= self._settings.observability.slow_request_ms
                    else log.info
                )
                level(
                    "request",
                    extra={
                        "status": status_code,
                        "duration_ms": round(elapsed_ms, 1),
                        "route": _route_template(request),
                    },
                )
            clear_request_context()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._settings = get_settings()
        self._limiter = SlidingWindowRateLimiter(self._settings.security)
        self._counter = 0

    async def dispatch(self, request: Request, call_next):
        if (
            request.url.path.startswith(("/metrics", "/health", "/ready"))
            or request.method == "OPTIONS"
        ):
            return await call_next(request)
        client_id = request.headers.get("x-api-key") or (
            request.client.host if request.client else "anonymous"
        )
        try:
            self._limiter.check(client_id)
        except CausalGuardError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.to_payload(),
                headers={"Retry-After": str(exc.details.get("retry_after_s", 30))},
            )
        self._counter += 1
        if self._counter % 512 == 0:
            self._limiter.sweep()
        return await call_next(request)
