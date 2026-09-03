"""Per-request context propagated via :mod:`contextvars` (async-safe)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("causalguard_request_id", default=None)
_request_extra: ContextVar[dict[str, Any] | None] = ContextVar(
    "causalguard_request_extra", default=None
)


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request_context(request_id: str | None = None, **extra: Any) -> str:
    rid = request_id or new_request_id()
    _request_id.set(rid)
    if extra:
        merged = {**(_request_extra.get() or {}), **extra}
        _request_extra.set(merged)
    return rid


def get_request_id() -> str | None:
    return _request_id.get()


def get_request_extra() -> dict[str, Any]:
    return dict(_request_extra.get() or {})


def clear_request_context() -> None:
    _request_id.set(None)
    _request_extra.set(None)
