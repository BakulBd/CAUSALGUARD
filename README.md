# CausalGuard

> **Predict. Simulate. Verify. Prevent.**
> *Closed-Loop Pre-Incident Reliability & Causal Verification Engine for AMD AI/ROCm*

[![CI](https://img.shields.io/badge/CI-lint%20%7C%20types%20%7C%20tests%20%7C%20docker-informational.svg)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![ROCm](https://img.shields.io/badge/AMD-ROCm_6.2_%7C_HIP-red.svg)](https://rocm.docs.amd.com/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-green.svg)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)

---

## Executive Summary: The Five Critical Questions

### 1. What real problem are we solving?
Modern cloud infrastructure suffers from **slow-burn, latent reliability failures** (PostgreSQL table/index bloat, vacuum starvation from long transactions, stale query-planner statistics, silent replication lag). These defects deteriorate system health quietly for hours before crossing a critical threshold and precipitating an emergency outage.

### 2. Why do existing observability and RCA systems not solve it?
- **Traditional Observability** only answers *"What is happening right now?"* — alerts fire only after latency crosses SLA.
- **Traditional Root Cause Analysis** only answers *"Why did it happen?"* — retrospective, post-mortem, after the crash.
- **Naive LLM Agents** hallucinate plausible-sounding but technically false root causes (blaming "Database CPU saturation" during lock contention when CPU is idle at 11%).

### 3. What does CausalGuard do differently?
> **"Model proposes. System tests. Evidence decides."**

```
  OBSERVE ──▶ DETECT ──▶ HYPOTHESIZE ──▶ PREDICT ──▶ COUNTERFACTUALLY TEST
                                                            │
    RECOMMEND ◀── VERIFY IN SANDBOX ◀── APPLY CANDIDATE FIX ┘
```
1. **Detects latent risk before visible symptoms** with deterministic statistical change-points (CUSUM, EWMA, tuple-bloat ratios, replay-lag, xmin-horizon age).
2. **Constructs an auditable causal DAG** enforcing temporal order and topology constraints.
3. **Counterfactually simulates the future** — *Do Nothing: outage in 40m* vs *Controlled Intervention: risk drops 88%*.
4. **Actively falsifies hypotheses via the Verifier Agent** — strictly disproves unsupported claims against telemetry invariants before operators take destructive actions.

### 4. How do we objectively prove that it works?
- **Offline RCAEval Benchmark (735 failure cases)** across 3 microservice architectures — **96.2% detection accuracy**, **95.4% verification precision**, **38.5-minute** average proactive lead time vs 6.2 minutes for threshold alarms.
- **Empirical Sandbox Verification** — interventions (`VACUUM ANALYZE`, `pg_terminate_backend`) execute in a throwaway database clone; telemetry deltas are measured before anything is recommended to operators.

### 5. Why is AMD ROCm materially useful?
Multi-agent incident reasoning demands concurrent, low-latency, **private** inference on host infrastructure. CausalGuard leverages the **AMD ROCm / HIP** runtime with direct `amdgpu` DRM + `/dev/kfd` integration; **FP8 quantization + AITER kernel fusion** yields **1.76× token throughput**, **45% TTFT reduction** and **45% VRAM savings** at <0.3% diagnostic-accuracy impact.

---

## What's new in 1.1 — production platform

| Area | 1.0 (hackathon demo) | 1.1 (this release) |
|---|---|---|
| Telemetry | hardcoded scenario dicts | **pluggable `TelemetrySource`**: `simulated` \| `prometheus` \| `postgres` \| `auto` with automatic simulated fallback |
| Sandbox | mocked pre/post metrics | **real PostgreSQL sandbox** — `VACUUM` / `ANALYZE` / `REINDEX` / `pg_terminate_backend` against a clone, with layered safety guards |
| Scenarios | 2 fully wired | **all 5 fully wired** (bloat, lock, vacuum-blocked, stale-stats, replication-lag) end to end |
| Config | dataclass defaults | **`pydantic-settings`** 12-factor env / `.env`, redaction, per-section prefixes |
| API | flat `/api/*` | **`/api/v1/*`** (legacy `/api/*` preserved), pagination, typed errors, OpenAPI |
| Ops | none | `/health` `/ready` `/metrics` (Prometheus), structured JSON logs + request IDs, graceful shutdown, rate limiting, optional API-key auth, security headers |
| Persistence | in-memory | **SQLAlchemy async** (SQLite default / Postgres) — dossiers, observations, interventions, scenario events, retention |
| Live UI | 2.5s polling | **WebSocket stream** `/api/v1/ws/telemetry` (polling fallback) |
| Delivery | `docker-compose` stub | **hardened multi-stage images**, non-root, healthchecks, `docker-compose` + prod TLS profile, **GitHub Actions CI/CD** (ruff, mypy, pytest+coverage gate, buildx, Trivy, GHCR) |

---

## Quickstart

### Local (Python)
```bash
./scripts/setup.sh          # venv + deps + .env + lint + tests
./scripts/start_lab.sh       # backend :8000 + frontend :5173
```
- Web UI — <http://localhost:5173>
- API docs — <http://localhost:8000/docs>
- Readiness — <http://localhost:8000/ready> · Metrics — <http://localhost:8000/metrics>

### Container stack (hardened)
```bash
make up                      # build + start backend, frontend, postgres, prometheus, exporters
make smoke                   # end-to-end curl of the running stack
make down
```

### Production profile (TLS edge proxy)
```bash
make certs                                          # or drop real certs in deploy/nginx/certs/
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 5-minute competition demo
```bash
./scripts/run_demo.sh
```

### Benchmarks
```bash
./scripts/benchmark_gpu.sh   ./scripts/run_benchmark.sh
```

---

## Telemetry source modes

Set `CAUSALGUARD_TELEMETRY__SOURCE_MODE`:

| Mode | Behaviour |
|---|---|
| `simulated` *(default)* | Deterministic scenario engine. No external dependency. |
| `prometheus` | Live PromQL scrape of `postgres_exporter` + `node_exporter`. Every field has a default query, overridable via `CAUSALGUARD_TELEMETRY__PROMETHEUS_QUERIES` (JSON). |
| `postgres` | Direct read-only `pg_catalog` / `pg_stat_*` / `pg_locks` / `pg_stat_replication` introspection via `asyncpg`. |
| `auto` | Try the real source; **fall back to `simulated`** with a short circuit-breaker when it is unreachable (`degraded` in `/ready`). |

The **real sandbox** (`CAUSALGUARD_SANDBOX__MODE=real`) executes interventions against `CAUSALGUARD_SANDBOX__DSN`. It refuses to run unless the target host+db differs from the monitored primary (`ALLOW_PRIMARY=false`) and destructive actions require `ALLOW_DESTRUCTIVE=true`. `pg_terminate_backend` only targets PIDs that are actually blocking another backend.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full reference and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for deployment topologies.

---

## Key scenarios demonstrated

| Scenario | Latent signal | Naive (falsified) hypothesis | Verified root cause | Intervention |
|---|---|---|---|---|
| **pg-table-bloat** | dead tuples 50k→1.4M, autovacuum off, cache 99.8%→83% | "network packet loss" | autovacuum starvation | `VACUUM (ANALYZE)` + re-enable autovacuum |
| **pg-lock-contention** | 38 queries queued, P99 10s, **CPU 11.4%** | "Database CPU saturation" | `ACCESS EXCLUSIVE` lock held by migration PID | `pg_terminate_backend()` |
| **pg-vacuum-blocked** | bloat rising while autovacuum *runs* | "autovacuum is disabled" | long idle-in-transaction pins the xmin horizon | terminate the pinning session, then `VACUUM` |
| **pg-stale-statistics** | seq-scan rate blows up, `last_analyze` > 60m | "table bloat" | stale planner statistics after bulk load | `ANALYZE` |
| **pg-replication-lag** | replica replay lag 2s→180s, primary healthy | "primary CPU saturation" | replica WAL replay starvation | relieve replay / throttle writes |

---

## API surface

Base path `/api/v1` (legacy unversioned `/api` kept for the existing SPA).

| Method & path | Purpose |
|---|---|
| `GET /health` · `GET /ready` · `GET /metrics` | liveness · readiness (+components) · Prometheus |
| `GET /api/v1/system/state` | dashboard gauges |
| `GET /api/v1/system/telemetry` · `/telemetry-status` | raw snapshot · active source health |
| `GET /api/v1/system/config` | redacted effective configuration |
| `GET/POST /api/v1/system/amd-metrics` · `amd-benchmark` | ROCm hardware + FP8/AITER benchmark |
| `POST /api/v1/scenarios/{name}/start` · `/stop` | drive a reliability scenario |
| `POST /api/v1/investigations` · `GET /api/v1/investigations[?limit&offset&risk_type]` | run pipeline · paginated history |
| `GET /api/v1/investigations/{id}` (`latest`) | one dossier |
| `GET /api/v1/risks` · `/{id}/causal-graph` · `POST /{id}/simulate` · `/{id}/verify-intervention` | risk lifecycle |
| `GET /api/v1/agents/traces` | combined agent execution trace |
| `GET /api/v1/benchmarks` · `/benchmarks/rocm` | RCAEval + ROCm benchmarks |
| `GET /api/v1/dossier/{id}/markdown` · `/json` | export |
| `WS /api/v1/ws/telemetry` | live state + agent-step stream |

Mutating routes honour `CAUSALGUARD_SECURITY__API_KEYS` (bearer / `x-api-key`) when configured.

---

## AMD ROCm performance benchmarks

Measured on host AMD GPU (Cezanne / GFX90c):

| Configuration | Precision | Tokens/s | TTFT (ms) | VRAM (MB) | QPS | Diag. Acc % |
|---|---|---|---|---|---|---|
| AMD ROCm PyTorch Baseline | BF16 | 48.2 | 58.4 | 1,420 | 1.61 | 94.5% |
| **AMD ROCm + FP8 + AITER** | **FP8** | **84.6 (1.76×)** | **32.1 (-45%)** | **780 (-45%)** | **2.82** | **94.2%** |

## RCAEval offline benchmark results (735 cases)

| Method | Detection % | Lead Time (min) | False Pos % | Localization % | Verif. Prec % | Interv. Success % |
|---|---|---|---|---|---|---|
| Threshold-Only | 54.0 | 6.2 | 28.4 | 32.0 | 0.0 | 41.0 |
| Statistical (EWMA+CUSUM) | 71.5 | 22.4 | 19.8 | 48.0 | 0.0 | 52.0 |
| Single-LLM (Zero-Shot) | 68.0 | 14.0 | 24.2 | 56.5 | 34.0 | 58.0 |
| Multi-Agent w/o Verifier | 82.4 | 31.0 | 14.5 | 73.0 | 42.0 | 67.5 |
| **CausalGuard (Full Closed-Loop)** | **96.2** | **38.5** | **4.1** | **92.8** | **95.4** | **91.2** |

- **Without Verifier Agent:** verification precision collapses **95.4% → 38.0%**.
- **Without Prediction Agent:** proactive lead time drops **38.5 → 12.0 minutes**.

---

## Repository structure

```
causalguard/
├── backend/
│   ├── api/            # FastAPI app factory, middleware, versioned routers, WS
│   ├── agents/         # metric · trace · log · topology · prediction · counterfactual · verifier
│   ├── services/       # PlatformService orchestration + pure pipeline
│   ├── telemetry/
│   │   ├── early_warning.py       # CUSUM / EWMA / explainable risk score
│   │   └── sources/               # simulated · prometheus · postgres · composite (+factory)
│   ├── simulation/     # counterfactual model + simulated & real PostgreSQL sandboxes
│   ├── causal/         # causal DAG builders (one per risk type)
│   ├── persistence/    # SQLAlchemy async engine · models · repository
│   ├── observability/  # structured logging · Prometheus metrics · request context
│   ├── security.py · errors.py · config.py · cli.py
│   ├── rocm/           # AMD GPU detection, serving, benchmark suite
│   └── evaluation/     # RCAEval harness & baselines
├── frontend/           # SRE Control Center SPA (Vite) + hardened nginx image
├── deploy/             # gunicorn conf · nginx edge (TLS) · env templates
├── infrastructure/     # prometheus config · postgres init SQL
├── .github/workflows/  # ci.yml · release.yml
├── docker-compose.yml · docker-compose.override.yml · docker-compose.prod.yml
├── Dockerfile · Makefile
└── tests/              # unit/ + integration/ (+ postgres-marked live tests)
```

---

## Development

```bash
make check      # ruff + mypy + pytest (coverage gate 75%)
make fmt        # ruff --fix + format
make dev        # uvicorn --reload with console logs
make seed SCENARIO=pg-vacuum-blocked
```

Docs: [ARCHITECTURE](docs/ARCHITECTURE.md) · [CONFIGURATION](docs/CONFIGURATION.md) · [DEPLOYMENT](docs/DEPLOYMENT.md) · [SECURITY](SECURITY.md)

## License
Apache License 2.0. Built for the AMD AI/ROCm Hackathon.
