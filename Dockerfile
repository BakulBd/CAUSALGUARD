# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CausalGuard backend — multi-stage, non-root, gunicorn/uvicorn workers.
# ---------------------------------------------------------------------------
ARG PYTHON_VERSION=3.12

# ---- builder -------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build a self-contained virtualenv we can copy into the runtime image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY backend ./backend
# Install the project with the live-telemetry extra (asyncpg) baked in.
RUN pip install --upgrade pip setuptools wheel \
    && pip install ".[postgres]" gunicorn

# ---- runtime ----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="CausalGuard" \
      org.opencontainers.image.description="Closed-loop pre-incident reliability & causal verification engine for AMD ROCm" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/causalguard/causalguard"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    CAUSALGUARD_ENVIRONMENT=production \
    CAUSALGUARD_LOG_FORMAT=json \
    CAUSALGUARD_DATABASE__URL=sqlite+aiosqlite:////app/data/causalguard.db

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 causalguard \
    && useradd --system --uid 1001 --gid causalguard --home /app --shell /usr/sbin/nologin causalguard

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=causalguard:causalguard backend ./backend
COPY --chown=causalguard:causalguard pyproject.toml README.md ./
COPY --chown=causalguard:causalguard deploy/gunicorn.conf.py ./deploy/gunicorn.conf.py

RUN mkdir -p /app/data && chown -R causalguard:causalguard /app/data

USER causalguard
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "backend.api.main:app", "-c", "deploy/gunicorn.conf.py"]
