"""Lightweight security primitives: API-key auth, rate limiting, response headers."""

from __future__ import annotations

import time
from collections import deque

from fastapi import Request

from backend.config import SecurityConfig, get_settings
from backend.errors import AuthError, RateLimitedError


def extract_api_key(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("x-api-key")


def require_api_key(request: Request) -> None:
    """FastAPI dependency: enforce a valid key when auth is enabled."""
    cfg = get_settings().security
    if not cfg.auth_enabled:
        return
    key = extract_api_key(request)
    if not key or key not in cfg.api_keys:
        raise AuthError()


class SlidingWindowRateLimiter:
    """Per-client fixed-cost sliding window limiter (in-process)."""

    def __init__(self, cfg: SecurityConfig) -> None:
        self._cfg = cfg
        self._hits: dict[str, deque[float]] = {}

    def check(self, client_id: str) -> None:
        if not self._cfg.rate_limit_enabled or self._cfg.rate_limit_per_minute <= 0:
            return
        now = time.monotonic()
        window_start = now - 60.0
        bucket = self._hits.setdefault(client_id, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= self._cfg.rate_limit_per_minute:
            retry_after = max(1, int(60 - (now - bucket[0])))
            raise RateLimitedError(
                "Rate limit exceeded.",
                details={
                    "limit_per_minute": self._cfg.rate_limit_per_minute,
                    "retry_after_s": retry_after,
                },
            )
        bucket.append(now)

    def sweep(self, max_idle: float = 300.0) -> None:
        cutoff = time.monotonic() - max_idle
        for cid in list(self._hits):
            bucket = self._hits[cid]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                self._hits.pop(cid, None)


def security_headers(is_hsts: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
    if is_hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers
