# Changelog

## 1.1.0 — Production platform

### Added
- **Pluggable telemetry sources** — `TelemetrySource` interface with `simulated`,
  `prometheus` (PromQL), `postgres` (asyncpg catalog introspection) and `auto`
  (real source + automatic simulated fallback with circuit breaker).
- **Real PostgreSQL sandbox** — executes `VACUUM` / `ANALYZE` / `REINDEX` /
  `pg_terminate_backend` against a throwaway clone with layered safety guards;
  measures real pre/post risk deltas.
- **All five reliability scenarios** wired end to end (added `pg-vacuum-blocked`,
  `pg-stale-statistics`, `pg-replication-lag` causal graphs, prediction branches,
  falsification suites and early-warning contributors).
- **`pydantic-settings` configuration** — 12-factor env / `.env`, per-section
  prefixes, secret redaction, `GET /api/v1/system/config`, `causalguard config`.
- **Observability** — structured JSON logging with request IDs, Prometheus
  `/metrics` (HTTP, investigation, agent, telemetry-fetch, risk-score, build),
  `/health` and `/ready` (component checks), graceful shutdown via lifespan.
- **Persistence** — SQLAlchemy async (SQLite default / Postgres); dossiers,
  observations, interventions, scenario events, retention pruning.
- **Versioned API** `/api/v1/*` with pagination and typed error envelope; legacy
  `/api/*` retained. New: telemetry snapshot/status, dossier list, dossier JSON
  export, ROCm benchmark route.
- **WebSocket** `/api/v1/ws/telemetry` live stream; SPA uses it with polling
  fallback.
- **Security** — optional API-key auth on mutating routes, per-client rate
  limiting, security headers, TrustedHost allowlist, `SECURITY.md`.
- **Delivery** — hardened multi-stage non-root images with healthchecks,
  `docker-compose` (+ dev override + prod TLS profile), gunicorn config,
  `Makefile`, `causalguard` CLI, GitHub Actions CI (ruff, mypy, pytest+coverage
  gate, buildx, Trivy) and release workflow (multi-arch GHCR + GH release).
- Docs: `ARCHITECTURE.md`, `CONFIGURATION.md`, `DEPLOYMENT.md`; `LICENSE`.

### Changed
- `ScenarioManager` is now a thin synchronous shim over the shared pipeline and
  scenario context; investigations flow through `PlatformService`.
- Early-warning score is authoritative for `system/state` and risk listing
  (was hardcoded per scenario).
- `Dockerfile` / `frontend/Dockerfile` rebuilt (multi-stage, non-root, gunicorn /
  nginx-unprivileged).

### Preserved
- `/api/*` routes, module singletons (`scenario_manager`, `*_agent`,
  `early_warning_engine`, `sandbox_engine`), all `scripts/*.sh`, benchmark
  numbers and the 5-minute demo narrative.

## 1.0.0
- Initial hackathon release.
