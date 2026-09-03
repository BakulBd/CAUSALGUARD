"""Structured logging for CausalGuard.

Emits newline-delimited JSON in production (``log_format=json``) and a compact
human-readable line in development (``log_format=console``). Request context
(request id, method, path) is merged into every record automatically.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from backend.observability.context import get_request_extra, get_request_id

_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, version: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.version = version
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": self.service,
            "version": self.version,
            "env": self.environment,
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        extra_ctx = get_request_extra()
        if extra_ctx:
            payload.update(extra_ctx)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    _COLORS = {
        "DEBUG": "\033[38;5;244m",
        "INFO": "\033[38;5;39m",
        "WARNING": "\033[38;5;214m",
        "ERROR": "\033[38;5;196m",
        "CRITICAL": "\033[48;5;196m\033[38;5;231m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        ts = time.strftime("%H:%M:%S", time.gmtime(record.created))
        rid = get_request_id()
        rid_str = f" [{rid[:8]}]" if rid else ""
        base = f"{color}{ts} {record.levelname:<8}{self._RESET} {record.name}{rid_str} — {record.getMessage()}"
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        }
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


def configure_logging(
    *,
    level: str = "INFO",
    fmt: str = "json",
    service: str = "causalguard",
    version: str = "0.0.0",
    environment: str = "development",
    force: bool = False,
) -> None:
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "console":
        handler.setFormatter(ConsoleFormatter())
    else:
        handler.setFormatter(JsonFormatter(service, version, environment))
    root.addHandler(handler)

    # Tame noisy third-party loggers; let ours flow at the configured level.
    for noisy, lvl in {
        "uvicorn.access": "WARNING",
        "uvicorn.error": "INFO",
        "watchfiles": "WARNING",
        "httpx": "WARNING",
        "httpcore": "WARNING",
        "asyncio": "WARNING",
        "sqlalchemy.engine": "WARNING",
    }.items():
        logging.getLogger(noisy).setLevel(lvl)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
