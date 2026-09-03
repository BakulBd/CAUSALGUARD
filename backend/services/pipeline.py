"""The closed-loop investigation pipeline (pure, synchronous, side-effect free).

    OBSERVE -> DETECT -> HYPOTHESIZE -> PREDICT -> COUNTERFACTUALLY TEST -> VERIFY

Telemetry acquisition (async) and persistence (async) live in
:class:`~backend.services.platform.PlatformService`; everything CPU-bound and
deterministic lives here so both the async API path and the sync script path
share one implementation.
"""

from __future__ import annotations

import time

from backend.agents.counterfactual_agent import counterfactual_agent
from backend.agents.log_agent import log_agent
from backend.agents.metric_agent import metric_agent
from backend.agents.prediction_agent import prediction_agent
from backend.agents.topology_agent import topology_agent
from backend.agents.trace_agent import trace_agent
from backend.agents.verifier_agent import verifier_agent
from backend.causal.graph import CausalGraphEngine
from backend.config import get_settings
from backend.models.schema import IncidentDossier, PostgresTelemetrySnapshot
from backend.telemetry.early_warning import early_warning_engine
from backend.telemetry.sources.base import ScenarioContext

_SCENARIO_RISK: dict[str, tuple[str, str]] = {
    "pg-table-bloat": ("postgresql_table_bloat", "PROACTIVE"),
    "pg-lock-contention": ("postgresql_lock_contention", "REACTIVE"),
    "pg-vacuum-blocked": ("postgresql_vacuum_blocked", "PROACTIVE"),
    "pg-stale-statistics": ("postgresql_stale_statistics", "PROACTIVE"),
    "pg-replication-lag": ("postgresql_replication_lag", "PROACTIVE"),
}

_RECOMMENDATION: dict[str, str] = {
    "postgresql_table_bloat": (
        "EXECUTE INTERVENTION: Apply VACUUM (ANALYZE, VERBOSE) in a maintenance "
        "window and re-enable autovacuum_enabled=on for the affected table."
    ),
    "postgresql_lock_contention": (
        "EXECUTE INTERVENTION: Terminate the blocking migration transaction to "
        "release the AccessExclusiveLock immediately, then retry the migration "
        "with lock_timeout set."
    ),
    "postgresql_vacuum_blocked": (
        "EXECUTE INTERVENTION: Terminate the long idle-in-transaction session "
        "pinning the xmin horizon, then run VACUUM so dead tuples become "
        "removable again."
    ),
    "postgresql_stale_statistics": (
        "EXECUTE INTERVENTION: Run ANALYZE on the affected table so the planner "
        "stops choosing sequential scans; schedule autoanalyze tuning."
    ),
    "postgresql_replication_lag": (
        "EXECUTE INTERVENTION: Relieve WAL replay starvation on the replica "
        "(increase replay resources / throttle bulk writes) before the "
        "data-freshness SLA is breached."
    ),
}


def classify_risk(snap: PostgresTelemetrySnapshot) -> tuple[str | None, str]:
    """Infer the risk type from a telemetry snapshot alone (source-agnostic)."""
    th = get_settings().thresholds
    bloat_th = th.dead_tuple_bloat_threshold

    if (
        snap.waiting_queries >= 3
        and snap.bloat_ratio < 0.10
        and snap.max_lock_duration_sec >= th.lock_wait_seconds_threshold
    ):
        return "postgresql_lock_contention", "REACTIVE"

    if snap.replication_lag_seconds >= th.replication_lag_warning_seconds:
        return "postgresql_replication_lag", "PROACTIVE"

    if (
        snap.bloat_ratio >= bloat_th
        and snap.autovacuum_enabled
        and snap.last_autovacuum_age_sec < th.autovacuum_stale_seconds
        and snap.oldest_xact_age_sec >= 300.0
    ):
        return "postgresql_vacuum_blocked", "PROACTIVE"

    if snap.bloat_ratio >= bloat_th and not snap.autovacuum_enabled:
        return "postgresql_table_bloat", "PROACTIVE"

    if snap.last_analyze_age_sec >= 1800.0 and snap.seq_scans >= 200 and snap.bloat_ratio < 0.10:
        return "postgresql_stale_statistics", "PROACTIVE"

    if snap.bloat_ratio >= bloat_th:
        return "postgresql_table_bloat", "PROACTIVE"

    return None, "PROACTIVE"


def resolve_risk(snap: PostgresTelemetrySnapshot, ctx: ScenarioContext) -> tuple[str, str]:
    """Resolve to a concrete risk type: snapshot evidence first, declared scenario as prior."""
    risk_type, mode = classify_risk(snap)
    if risk_type is None:
        risk_type, mode = _SCENARIO_RISK.get(ctx.scenario, ("postgresql_table_bloat", "PROACTIVE"))
    return risk_type, mode


def status_label(risk_type: str | None, score: float, ctx: ScenarioContext) -> str:
    if ctx.intervention_applied:
        return "RECOVERED (VERIFIED)"
    if risk_type == "postgresql_lock_contention":
        return "ACUTE_INCIDENT_ACTIVE"
    if risk_type is not None and score >= 40.0:
        return "PRE_INCIDENT_RISK_DETECTED"
    if score >= 15.0:
        return "ANOMALY_DETECTED"
    return "HEALTHY"


def _verifier_telemetry(snap: PostgresTelemetrySnapshot) -> dict[str, float]:
    total = max(1, snap.n_dead_tuples + snap.n_live_tuples)
    return {
        "cpu": snap.cpu_utilization_pct,
        "cpu_saturation": snap.cpu_utilization_pct,
        "waiting_queries": float(snap.waiting_queries),
        "bloat_ratio": snap.n_dead_tuples / total,
        "autovacuum_disabled": not snap.autovacuum_enabled,
        "oldest_xact_age_sec": snap.oldest_xact_age_sec,
        "last_analyze_age_sec": snap.last_analyze_age_sec,
        "seq_scans_per_min": float(snap.seq_scans),
        "replication_lag_seconds": snap.replication_lag_seconds,
    }


def _build_causal_graph(risk_type: str, snap: PostgresTelemetrySnapshot) -> CausalGraphEngine:
    if risk_type == "postgresql_lock_contention":
        return CausalGraphEngine.build_lock_contention_graph(
            blocking_pid=snap.blocking_pids[0] if snap.blocking_pids else 14022,
            blocked_queries=snap.waiting_queries or 38,
            cpu_utilization_pct=snap.cpu_utilization_pct,
        )
    if risk_type == "postgresql_vacuum_blocked":
        return CausalGraphEngine.build_vacuum_blocked_graph(
            dead_tuples=snap.n_dead_tuples,
            bloat_ratio=snap.bloat_ratio,
            oldest_xact_age_sec=snap.oldest_xact_age_sec or 1200.0,
            blocking_pid=snap.blocking_pids[0] if snap.blocking_pids else None,
        )
    if risk_type == "postgresql_stale_statistics":
        return CausalGraphEngine.build_stale_statistics_graph(
            last_analyze_age_sec=snap.last_analyze_age_sec or 3600.0,
            seq_scans_per_min=float(snap.seq_scans or 400),
            p99_latency_ms=snap.p99_latency_ms,
        )
    if risk_type == "postgresql_replication_lag":
        return CausalGraphEngine.build_replication_lag_graph(
            replication_lag_seconds=snap.replication_lag_seconds or 120.0,
            p99_latency_ms=snap.p99_latency_ms,
        )
    return CausalGraphEngine.build_table_bloat_graph(
        dead_tuples=snap.n_dead_tuples,
        bloat_ratio=snap.bloat_ratio,
        cache_hit_ratio=snap.buffer_cache_hit_ratio,
        p99_latency_ms=snap.p99_latency_ms,
        last_autovacuum_age_sec=snap.last_autovacuum_age_sec or 1850.0,
    )


def build_dossier(
    snap: PostgresTelemetrySnapshot,
    ctx: ScenarioContext,
    *,
    risk_type: str | None = None,
    mode: str | None = None,
) -> IncidentDossier:
    """Run the full deterministic pipeline and return an :class:`IncidentDossier`."""
    from backend.rocm.serving.rocm_engine import rocm_engine

    if risk_type is None:
        risk_type, mode = resolve_risk(snap, ctx)
    if mode is None:
        _, mode = resolve_risk(snap, ctx)

    horizon = get_settings().thresholds.forecast_horizon_minutes

    ew_kwargs = snap.as_early_warning_kwargs()
    score, contributors, _ = early_warning_engine.evaluate_postgres_telemetry(**ew_kwargs)

    metric_obs = metric_agent.analyze(
        {
            "n_dead_tuples": snap.n_dead_tuples,
            "n_live_tuples": snap.n_live_tuples,
            "last_autovacuum_age_sec": snap.last_autovacuum_age_sec,
            "buffer_cache_hit_ratio": snap.buffer_cache_hit_ratio,
            "table_size_mb": snap.table_size_mb,
            "disk_read_iops": snap.disk_read_iops,
            "p99_latency_ms": snap.p99_latency_ms,
            "waiting_queries": snap.waiting_queries,
            "max_lock_duration_sec": snap.max_lock_duration_sec,
            "cpu_utilization_pct": snap.cpu_utilization_pct,
            "last_analyze_age_sec": snap.last_analyze_age_sec,
            "seq_scans_per_min": float(snap.seq_scans),
            "replication_lag_seconds": snap.replication_lag_seconds,
            "oldest_xact_age_sec": snap.oldest_xact_age_sec,
            "autovacuum_enabled": snap.autovacuum_enabled,
        }
    )
    trace_obs = trace_agent.analyze(p99_latency_ms=snap.p99_latency_ms, risk_type=risk_type)
    log_obs = log_agent.analyze(risk_type=risk_type)
    topo_obs = topology_agent.analyze(risk_type=risk_type)
    all_evidence = metric_obs + trace_obs + log_obs + topo_obs

    prediction = prediction_agent.predict(
        risk_type=risk_type,
        observations=all_evidence,
        risk_score=score,
        score_contributors=contributors,
    )

    causal_graph = _build_causal_graph(risk_type, snap).to_model()

    counterfactual = counterfactual_agent.evaluate_for_risk(
        risk_type=risk_type,
        snapshot=snap,
        horizon_minutes=horizon,
    )

    eval_hypos, rej_hypos = verifier_agent.run_falsification_suite(
        risk_type=risk_type,
        current_telemetry=_verifier_telemetry(snap),
    )

    amd_hw = rocm_engine.get_hardware_metrics()

    dossier_id = f"DOSSIER_{risk_type.upper()}_{int(time.time() * 1000)}"
    dossier = IncidentDossier(
        incident_id=dossier_id,
        mode=prediction.mode,
        risk_type=risk_type,
        severity=prediction.severity,
        risk_score=prediction.risk_score,
        score_contributors=prediction.score_contributors,
        causal_graph=causal_graph,
        evidence=all_evidence,
        hypotheses_evaluated=eval_hypos,
        rejected_hypotheses=rej_hypos,
        counterfactual=counterfactual,
        verification=None,
        amd_metrics=amd_hw,
        final_recommendation=_RECOMMENDATION.get(
            risk_type, _RECOMMENDATION["postgresql_table_bloat"]
        ),
        scenario=ctx.scenario,
        source_mode=snap.source_mode,
        generated_at=time.time(),
    )
    return dossier
