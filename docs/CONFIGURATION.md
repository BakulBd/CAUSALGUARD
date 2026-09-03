# Configuration reference

All configuration is environment-driven (`pydantic-settings`). Values may be set
as environment variables or in a `.env` / `.env.local` file at the repo root.
Nested keys use a **double underscore**: `CAUSALGUARD_<SECTION>__<KEY>`.

`GET /api/v1/system/config` returns the **redacted** effective configuration;
`causalguard config` prints the same from the CLI.

## Core

| Variable | Default | Notes |
|---|---|---|
| `CAUSALGUARD_ENVIRONMENT` | `development` | `development` \| `staging` \| `production` \| `test` |
| `CAUSALGUARD_LOG_LEVEL` | `INFO` | standard logging levels |
| `CAUSALGUARD_LOG_FORMAT` | `json` | `json` (prod) \| `console` (dev) |

## Server (`CAUSALGUARD_SERVER__`)

| Key | Default | Notes |
|---|---|---|
| `HOST` / `PORT` / `WORKERS` | `0.0.0.0` / `8000` / `1` | gunicorn reads `WORKERS` |
| `ROOT_PATH` | `""` | when behind a path-stripping proxy |
| `CORS_ORIGINS` | `http://localhost:5173,…` | comma-separated; `*` forces `cors_allow_credentials=false` |
| `TRUSTED_HOSTS` | `*` | comma-separated Host allowlist (`TrustedHostMiddleware`) |
| `SHUTDOWN_GRACE_SECONDS` | `10` | graceful drain window |

## Telemetry (`CAUSALGUARD_TELEMETRY__`)

| Key | Default | Notes |
|---|---|---|
| `SOURCE_MODE` | `simulated` | `simulated` \| `prometheus` \| `postgres` \| `auto` |
| `FALLBACK_TO_SIMULATED` | `true` | wrap real sources in a fallback composite |
| `PROMETHEUS_URL` | `http://localhost:9090` | |
| `PROMETHEUS_RELNAME` / `PROMETHEUS_DATNAME` | `orders` / `production_db` | label filters baked into default PromQL |
| `PROMETHEUS_RATE_WINDOW` | `5m` | rate() window |
| `PROMETHEUS_QUERIES` | `{}` | JSON object of `{snapshot_field: promql}` overrides |
| `STREAM_INTERVAL_SECONDS` | `2.0` | WebSocket push cadence |

## Monitored PostgreSQL (`CAUSALGUARD_POSTGRES__`) — `SOURCE_MODE=postgres`

| Key | Default | Notes |
|---|---|---|
| `DSN` | *(unset)* | `postgresql://user:pass@host:5432/db` (read-only monitor role recommended) |
| `SCHEMA_NAME` / `MONITORED_TABLE` | `public` / `orders` | |
| `STATEMENT_TIMEOUT_MS` | `4000` | per-probe timeout |
| `POOL_MIN_SIZE` / `POOL_MAX_SIZE` | `1` / `4` | asyncpg pool |

## Real sandbox (`CAUSALGUARD_SANDBOX__`)

| Key | Default | Notes |
|---|---|---|
| `MODE` | `simulated` | `simulated` \| `real` |
| `DSN` | *(unset)* | throwaway clone; **must differ from the primary** |
| `ALLOW_DESTRUCTIVE` | `false` | required for `VACUUM` / `ANALYZE` / `REINDEX` / `pg_terminate_backend` |
| `ALLOW_PRIMARY` | `false` | hard guard; refuses if sandbox host+db == primary host+db |
| `SETTLE_SECONDS` | `1.0` | wait between action and post-measurement |

## Persistence (`CAUSALGUARD_DATABASE__`)

| Key | Default | Notes |
|---|---|---|
| `URL` | `sqlite+aiosqlite:///./data/causalguard.db` | or `postgresql+asyncpg://…` |
| `RETENTION_DOSSIERS` | `500` | oldest dossiers + their observations are pruned |
| `CREATE_ALL_ON_STARTUP` | `true` | auto `create_all` (use migrations for prod Postgres) |
| `ECHO` | `false` | SQL echo |

## Security (`CAUSALGUARD_SECURITY__`)

| Key | Default | Notes |
|---|---|---|
| `API_KEYS` | *(empty → auth disabled)* | comma-separated; sent as `Authorization: Bearer` or `x-api-key` on mutating routes |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_PER_MINUTE` | `true` / `240` | per client-id sliding window |
| `SECURITY_HEADERS_ENABLED` | `true` | nosniff / DENY / referrer-policy / COOP / permissions-policy |
| `HSTS_ENABLED` | `false` | set `true` when TLS-terminated |

## Early-warning thresholds (`CAUSALGUARD_THRESHOLDS__`)

`DEAD_TUPLE_BLOAT_THRESHOLD` `0.15` · `AUTOVACUUM_STALE_SECONDS` `600` ·
`CACHE_HIT_RATIO_WARNING` `0.90` · `LOCK_WAIT_SECONDS_THRESHOLD` `5.0` ·
`FORECAST_HORIZON_MINUTES` `40` · `REPLICATION_LAG_WARNING_SECONDS` `30` ·
`EWMA_ALPHA` `0.25` · `CUSUM_THRESHOLD` `3.5`

## AMD ROCm (`CAUSALGUARD_ROCM__`)

`ENABLED` `true` · `DEVICE_ID` `0` · `PRECISION` `BF16` (`FP16`/`FP8`/`INT8`) ·
`USE_AITER` `false` · `BATCH_CONCURRENCY` `4` · `MODEL_NAME` · `INFERENCE_ENDPOINT`
(OpenAI-compatible fallback).

## Observability (`CAUSALGUARD_OBS__`)

`METRICS_ENABLED` `true` · `REQUEST_LOG_ENABLED` `true` · `SLOW_REQUEST_MS` `1000`.
