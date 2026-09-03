# Architecture

```
                         ┌────────────────────────────────────────────┐
                         │              TELEMETRY SOURCE              │
     simulated  ─────────┤  SimulatedTelemetrySource                  │
     prometheus ─────────┤  PrometheusTelemetrySource (PromQL)        │──▶ PostgresTelemetrySnapshot
     postgres   ─────────┤  PostgresTelemetrySource   (asyncpg)       │        (unified model)
     auto       ─────────┤  CompositeTelemetrySource  (+ fallback)    │
                         └──────────────────────┬─────────────────────┘
                                                │
                                     ┌──────────▼───────────┐
                                     │  EarlyWarningEngine   │  CUSUM · EWMA · trend slope
                                     │  explainable score    │  → contributors {…}
                                     └──────────┬───────────┘
                                                │
   ┌────────────────────────────────────────────▼─────────────────────────────────────────┐
   │                         PlatformService.run_investigation()                           │
   │                            (services/pipeline.build_dossier)                          │
   │                                                                                      │
   │  classify_risk(snapshot) ── resolves ──▶ risk_type  (declared scenario as prior)     │
   │                                                                                      │
   │   MetricAgent   TraceAgent   LogAgent   TopologyAgent      → ObservationSnapshot[]    │
   │        └──────────────┬──────────────────────┘                                        │
   │                 PredictionAgent            → RiskEvent (causal chain, falsifiers)     │
   │                 CausalGraphEngine.build_<risk>_graph()  → CausalGraphModel            │
   │                 CounterfactualAgent → Sandbox.counterfactual()  (A: do-nothing /      │
   │                                                                  B: intervention)     │
   │                 VerifierAgent.run_falsification_suite()  → naive hypo REJECTED,       │
   │                                                            real cause VERIFIED        │
   │                 ROCmEngine.get_hardware_metrics()                                      │
   │                                    │                                                  │
   │                                    ▼                                                  │
   │                            IncidentDossier ──▶ DossierRepository (SQLAlchemy async)   │
   └──────────────────────────────────────┬───────────────────────────────────────────────┘
                                          │
             ┌────────────────────────────▼─────────────────────────────┐
             │  FastAPI app  (/api/v1 + legacy /api)                     │
             │  ObservabilityMiddleware · RateLimitMiddleware · CORS     │
             │  /health /ready /metrics · WS /api/v1/ws/telemetry        │
             └────────────────────────────┬─────────────────────────────┘
                                          │
                                   SRE Control Center SPA
```

## Modules

| Package | Responsibility |
|---|---|
| `backend/config.py` | `pydantic-settings` sections; `get_settings()` (cached); `redacted()` |
| `backend/observability/` | JSON/console logging, `contextvars` request context, Prometheus registry + helpers |
| `backend/errors.py` | typed `CausalGuardError` hierarchy → structured `{error:{code,message,details,request_id}}` |
| `backend/telemetry/sources/` | `TelemetrySource` ABC + 4 implementations + `build_telemetry_source()` factory |
| `backend/telemetry/early_warning.py` | deterministic statistical scoring → `(score, contributors, observations)` |
| `backend/agents/` | 7 specialist agents; each records an `AgentTraceStep` history |
| `backend/causal/graph.py` | one DAG builder per risk type (networkx → `CausalGraphModel`) |
| `backend/simulation/` | `Sandbox` ABC · `SimulatedSandbox` (model) · `RealPostgresSandbox` (asyncpg + guards) |
| `backend/services/pipeline.py` | **pure** synchronous investigation pipeline (`classify_risk`, `build_dossier`) |
| `backend/services/platform.py` | async orchestration: telemetry fetch → pipeline → persist; scenario state; readiness |
| `backend/persistence/` | async engine lifecycle, ORM models, `DossierRepository` (degrades to no-op if DB down) |
| `backend/scenarios/` | shared `ScenarioContext` singleton + sync `ScenarioManager` (scripts / legacy) |
| `backend/api/` | app factory, middleware, versioned routers, WebSocket, dependency providers |

## Design choices

- **Pure pipeline, async shell.** `build_dossier()` is deterministic and
  side-effect-free so the async API path and the sync script path share one
  implementation; only telemetry acquisition and persistence are async.
- **Source-agnostic classification.** `classify_risk()` works from a
  `PostgresTelemetrySnapshot` alone, so a real database that develops bloat is
  detected even when the operator declared no scenario. The declared scenario is
  only a tie-breaker prior.
- **Fallback is first-class.** `CompositeTelemetrySource` serves the simulated
  engine (marked `…:degraded`) when the real source throws, with a circuit
  breaker so a down primary is retried, not hammered.
- **Safety guards on the real sandbox.** host+db identity check vs the primary,
  an explicit destructive-action flag, and `pg_terminate_backend` restricted to
  verified blocking PIDs.
- **Backward compatibility.** `/api/*` routes, the module singletons
  (`scenario_manager`, `*_agent`, `early_warning_engine`, `sandbox_engine`) and
  the demo scripts are preserved.
