"""Gunicorn configuration for the CausalGuard API (production)."""
from __future__ import annotations

import multiprocessing
import os

_default_workers = min(4, (multiprocessing.cpu_count() * 2) + 1)

bind = f"0.0.0.0:{os.getenv('CAUSALGUARD_SERVER__PORT', '8000')}"
workers = int(os.getenv("CAUSALGUARD_SERVER__WORKERS", str(_default_workers)))

# `uvicorn.workers` was removed in modern uvicorn; prefer the split-out package.
try:  # pragma: no cover - import-time selection
    import uvicorn_worker  # noqa: F401

    worker_class = "uvicorn_worker.UvicornWorker"
except ModuleNotFoundError:  # pragma: no cover
    worker_class = "uvicorn.workers.UvicornWorker"
timeout = int(float(os.getenv("CAUSALGUARD_SERVER__REQUEST_TIMEOUT_SECONDS", "30")))
graceful_timeout = int(float(os.getenv("CAUSALGUARD_SERVER__SHUTDOWN_GRACE_SECONDS", "10")))
keepalive = 5
max_requests = 2000
max_requests_jitter = 200

# Our application owns stdout with structured JSON logging.
accesslog = None
errorlog = "-"
loglevel = os.getenv("CAUSALGUARD_LOG_LEVEL", "info").lower()
capture_output = True
preload_app = False


def when_ready(server):  # noqa: ANN001, ANN201
    server.log.info("CausalGuard gunicorn master ready (%d workers)", workers)
