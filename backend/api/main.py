"""ASGI entrypoint: ``uvicorn backend.api.main:app`` / ``gunicorn backend.api.main:app``."""

from __future__ import annotations

from backend.api.app import create_app

app = create_app()
