"""
Pydantic schemas for CausalGuard.
Defines telemetry structures, compact observations, causal graphs, hypotheses,
counterfactual states, and AMD ROCm hardware specs.
"""

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    name: str
    timestamp: float = Field(default_factory=time.time)
    value: float
    labels: dict[str, str] = Field(default_factory=dict)
    source: str = "system"


class TraceSpan(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    service_name: str
    operation: str
    start_time: float
    duration_ms: float
    status_code: str = "OK"
    attributes: dict[str, Any] = Field(default_factory=dict)
    error: bool = False


class LogEntry(BaseModel):
    timestamp: float = Field(default_factory=time.time)
    service_name: str
    level: str = "INFO"
    message: str
    template_id: str | None = None
    stack_trace: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ObservationSnapshot(BaseModel):
    id: str  # e.g., OBSK_METRIC_POSTGRES_NDEAD_TUPLES_001
    category: Literal["metric", "trace", "log", "topology", "system"]
    source: str  # e.g., "postgres", "frontend-api"
    name: str
    window: str = "15m"
    current_value: float
    baseline_value: float
    trend: Literal["increasing", "decreasing", "stable", "spiking", "critical"]
    slope: float
    change_point: bool = False
    z_score: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class AnomalyEvent(BaseModel):
    id: str
    source: str
    metric_name: str
    severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"]
    detected_at: float = Field(default_factory=time.time)
    description: str
    z_score: float
    observation_id: str


class CausalNode(BaseModel):
    id: str
    label: str
    node_type: Literal[
        "OBSERVATION",
        "ANOMALY",
        "CANDIDATE_CAUSE",
        "PREDICTED_STATE",
        "FALSIFIED_HYPOTHESIS",
        "VERIFIED_INTERVENTION",
        "SERVICE",
        "DATABASE",
    ]
    status: Literal["OBSERVED", "HYPOTHESIZED", "VERIFIED", "REJECTED", "PREDICTED"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CausalEdge(BaseModel):
    source: str
    target: str
    relation: Literal[
        "depends_on",
        "precedes",
        "correlates_with",
        "caused_by_candidate",
        "propagates_to",
        "verified_by",
        "mitigated_by",
        "contradicts",
    ]
    confidence: float = 1.0
    evidence: str = ""


class CausalGraphModel(BaseModel):
    nodes: list[CausalNode] = Field(default_factory=list)
    edges: list[CausalEdge] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    id: str
    claim: str
    target_entity: str
    expected_signature: dict[str, Any]
    actual_signature: dict[str, Any]
    verification_status: Literal["PENDING", "VERIFIED", "REJECTED"]
    contradiction_reason: str | None = None
    tested_at: float = Field(default_factory=time.time)


class CounterfactualScenario(BaseModel):
    scenario_id: str
    risk_id: str
    name: str  # "Scenario A: Do Nothing" or "Scenario B: Controlled Intervention"
    action_type: Literal[
        "DO_NOTHING",
        "VACUUM_ANALYZE",
        "RESTORE_AUTOVACUUM",
        "TERMINATE_BLOCKING_PID",
        "REINDEX_TABLE",
        "SCALE_CONNECTION_POOL",
    ]
    predicted_horizon_minutes: int = 40
    expected_sla_breach: bool = False
    expected_p99_latency_ms: float = 0.0
    expected_dead_tuples: int = 0
    expected_cache_hit_ratio: float = 1.0
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "HIGH"


class CounterfactualComparison(BaseModel):
    risk_id: str
    baseline_do_nothing: CounterfactualScenario
    candidate_intervention: CounterfactualScenario
    recommendation: str
    expected_risk_reduction_pct: float


class InterventionVerification(BaseModel):
    intervention_id: str
    action_name: str
    environment: str = "CONTROLLED_SANDBOX"
    pre_metrics: dict[str, float]
    post_metrics: dict[str, float]
    verified: bool
    falsification_tested: bool
    risk_reduction_pct: float
    audit_notes: list[str] = Field(default_factory=list)
    executed_at: float = Field(default_factory=time.time)


class RiskEvent(BaseModel):
    id: str
    risk_type: Literal[
        "postgresql_table_bloat",
        "postgresql_lock_contention",
        "postgresql_vacuum_blocked",
        "postgresql_stale_statistics",
        "postgresql_replication_lag",
    ]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    status: Literal["DETECTED", "SIMULATING", "INTERVENING", "VERIFIED", "RESOLVED"]
    mode: Literal["PROACTIVE", "REACTIVE"] = "PROACTIVE"
    time_to_risk_minutes: float | None = None
    risk_score: float = 0.0  # 0 to 100
    score_contributors: dict[str, float] = Field(default_factory=dict)
    causal_chain: list[str] = Field(default_factory=list)
    evidence: list[ObservationSnapshot] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class AgentTraceStep(BaseModel):
    agent_name: str
    step_type: str
    input_summary: str
    output_summary: str
    tool_calls: list[str] = Field(default_factory=list)
    duration_ms: float
    timestamp: float = Field(default_factory=time.time)


class AMDHardwareMetrics(BaseModel):
    device_name: str = "AMD Radeon Graphics (Cezanne / GFX90c)"
    architecture: str = "AMD ROCm / HIP GFX90c"
    driver_version: str = "ROCm 6.2 / amdgpu 25.0"
    kfd_available: bool = True
    vram_total_mb: float = 2048.0
    vram_used_mb: float = 512.0
    gpu_utilization_pct: float = 34.5
    temperature_c: float = 46.0
    power_watts: float = 14.2
    tokens_per_second: float = 68.4
    time_to_first_token_ms: float = 42.1
    precision_mode: str = "BF16"
    aiter_acceleration: bool = True
    concurrency_capacity: int = 8


class AMDBenchmarkResult(BaseModel):
    config_name: str
    precision: str
    tokens_per_second: float
    time_to_first_token_ms: float
    vram_used_mb: float
    concurrency: int
    throughput_queries_per_sec: float
    diagnostic_accuracy_pct: float


class IncidentDossier(BaseModel):
    incident_id: str
    mode: str
    risk_type: str
    severity: str
    risk_score: float
    score_contributors: dict[str, float]
    causal_graph: CausalGraphModel
    evidence: list[ObservationSnapshot]
    hypotheses_evaluated: list[Hypothesis]
    rejected_hypotheses: list[Hypothesis]
    counterfactual: CounterfactualComparison
    verification: InterventionVerification | None = None
    amd_metrics: AMDHardwareMetrics
    final_recommendation: str
    scenario: str = "unknown"
    source_mode: str = "simulated"
    generated_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Telemetry-source contracts (shared by simulated + real adapters)
# ---------------------------------------------------------------------------


class PostgresTelemetrySnapshot(BaseModel):
    """Unified PostgreSQL health snapshot regardless of the backing source."""

    captured_at: float = Field(default_factory=time.time)
    source_mode: str = "simulated"
    scenario: str = "healthy"

    n_dead_tuples: int = 0
    n_live_tuples: int = 0
    bloat_ratio: float = 0.0
    last_autovacuum_age_sec: float = 0.0
    last_analyze_age_sec: float = 0.0
    autovacuum_enabled: bool = True

    buffer_cache_hit_ratio: float = 0.999
    table_size_mb: float = 0.0
    index_size_mb: float = 0.0
    disk_read_iops: float = 0.0
    seq_scans: int = 0
    idx_scans: int = 0

    p99_latency_ms: float = 0.0
    error_rate_pct: float = 0.0
    throughput_rps: float = 0.0

    waiting_queries: int = 0
    max_lock_duration_sec: float = 0.0
    oldest_xact_age_sec: float = 0.0
    blocking_pids: list[int] = Field(default_factory=list)
    active_connections: int = 0
    max_connections: int = 100

    cpu_utilization_pct: float = 0.0
    memory_utilization_pct: float = 0.0
    replication_lag_seconds: float = 0.0

    def as_early_warning_kwargs(self) -> dict[str, Any]:
        return {
            "n_dead_tuples": self.n_dead_tuples,
            "n_live_tuples": self.n_live_tuples,
            "last_autovacuum_age_sec": self.last_autovacuum_age_sec,
            "buffer_cache_hit_ratio": self.buffer_cache_hit_ratio,
            "table_size_mb": self.table_size_mb,
            "disk_read_iops": self.disk_read_iops,
            "p99_latency_ms": self.p99_latency_ms,
            "waiting_queries": self.waiting_queries,
            "max_lock_duration_sec": self.max_lock_duration_sec,
            "cpu_utilization_pct": self.cpu_utilization_pct,
            "last_analyze_age_sec": self.last_analyze_age_sec,
            "seq_scans_per_min": float(self.seq_scans),
            "replication_lag_seconds": self.replication_lag_seconds,
            "oldest_xact_age_sec": self.oldest_xact_age_sec,
            "autovacuum_enabled": self.autovacuum_enabled,
        }


class TelemetrySourceStatus(BaseModel):
    mode: Literal["simulated", "prometheus", "postgres", "auto"]
    active_mode: Literal["simulated", "prometheus", "postgres"] = "simulated"
    healthy: bool = True
    degraded: bool = False  # real source configured but currently falling back
    detail: str = ""
    latency_ms: float | None = None
    endpoint: str | None = None
    checked_at: float = Field(default_factory=time.time)


class ComponentHealth(BaseModel):
    name: str
    status: Literal["ok", "degraded", "down", "skipped"]
    detail: str = ""
    latency_ms: float | None = None


class HealthReport(BaseModel):
    status: Literal["ok", "degraded", "down"]
    service: str = "causalguard"
    version: str = "0.0.0"
    environment: str = "development"
    uptime_seconds: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class ReadinessReport(BaseModel):
    status: Literal["ok", "degraded", "down"]
    service: str = "causalguard"
    version: str = "0.0.0"
    checks: list[ComponentHealth] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class DossierPage(BaseModel):
    items: list[dict[str, Any]]
    meta: PageMeta
