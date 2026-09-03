# Deployment

## Topologies

| # | Telemetry source | Sandbox | Use |
|---|---|---|---|
| A | `simulated` | `simulated` | demo, CI, local dev, competition narrative |
| B | `prometheus` | `simulated` | drop-in over an existing Prometheus + exporters; no DB credentials needed |
| C | `postgres` | `real` (separate DB) | full closed loop against a real PostgreSQL, empirical verification on a clone |
| D | `auto` | `real` | production: real source with automatic simulated fallback on outage |

## Images

Both images are multi-stage, run as **non-root**, ship a `HEALTHCHECK`, and are
published to GHCR by `release.yml` on `v*` tags:

- `ghcr.io/<owner>/causalguard-backend` — gunicorn + `uvicorn.workers.UvicornWorker`, `tini` PID 1
- `ghcr.io/<owner>/causalguard-frontend` — `nginxinc/nginx-unprivileged`, SPA + `/api` reverse proxy

```bash
docker build -t causalguard/backend .
docker build -t causalguard/frontend ./frontend
```

## Single-host stack (`docker-compose.yml`)

```bash
make env                       # materialise deploy/env/*.env from *.example
make up                        # backend, frontend, postgres, prometheus, postgres-exporter, node-exporter
make smoke                     # curl health + a full investigation
```

`docker-compose.override.yml` is auto-merged and adds dev conveniences
(source bind-mount, `--reload`, console logs, exposed `:8000/:5432/:9090`).
Every service has a healthcheck; `depends_on` uses `condition: service_healthy`.
Resource limits, `restart: unless-stopped` and 10MB×3 log rotation are set.

### Switching to real telemetry

Edit `deploy/env/backend.env`:
```ini
CAUSALGUARD_TELEMETRY__SOURCE_MODE=postgres      # or prometheus / auto
CAUSALGUARD_SANDBOX__MODE=real
CAUSALGUARD_SANDBOX__ALLOW_DESTRUCTIVE=true      # only if you want live VACUUM / terminate
```
The bundled `postgres-primary` init scripts create the `production_db.orders`
table, a least-privilege `causalguard_monitor` role, and a separate `sandbox_db`.

## Production profile (TLS edge, `docker-compose.prod.yml`)

Not auto-merged — pass it explicitly (so the dev override is ignored):

```bash
./scripts/gen_self_signed_certs.sh                       # or real certs -> deploy/nginx/certs/{fullchain,privkey}.pem
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Adds an `nginx` **edge** service: terminates TLS (`:443`), redirects `:80`,
proxies to the frontend (which proxies `/api` to the backend), sets HSTS.
`CAUSALGUARD_BACKEND_REPLICAS` (default 2) scales the API; `TRUSTED_HOSTS` and
`CORS_ORIGINS` should be narrowed via env.

## Health & shutdown

| Endpoint | Semantics |
|---|---|
| `GET /health` | process liveness — always `200` while serving |
| `GET /ready` | readiness — checks telemetry source, database, sandbox; `503` if any is `down`, `degraded` if a real source fell back |
| `GET /metrics` | Prometheus exposition (request, investigation, agent, telemetry-fetch, risk-score, build-info) |

The app runs a lifespan handler: connects the DB (continues without persistence
if it fails), wires the `PlatformService`, and on `SIGTERM` closes pools within
`SHUTDOWN_GRACE_SECONDS`.

## Observability

- **Logs** — newline-delimited JSON on stdout with `request_id`, `method`, `path`, `status`, `duration_ms`. `LOG_FORMAT=console` for local dev.
- **Metrics** — scrape `causalguard-backend:8000/metrics` (already in `infrastructure/prometheus/prometheus.yml`).
- **Tracing header** — inbound `x-request-id` is honoured and echoed.

## Kubernetes

Not shipped as a first-class chart in this release (compose is the supported
target). The images are 12-factor and stateless apart from the SQLite file —
point `CAUSALGUARD_DATABASE__URL` at managed Postgres and run the backend as a
`Deployment` with `readinessProbe: /ready`, `livenessProbe: /health`,
`ServiceMonitor` on `/metrics`, and the AMD device plugin (`amd.com/gpu`) for
ROCm nodes.
