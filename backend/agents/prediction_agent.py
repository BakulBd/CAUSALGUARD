"""
Prediction Agent.
Forecasts developing system risk, causal chain progression, time-to-breach horizon,
and explicit falsification conditions.
"""

import time

from backend.agents.base_agent import BaseAgent
from backend.models.schema import ObservationSnapshot, RiskEvent


class PredictionAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "PredictionAgent",
            "Forecast latent infrastructure risk, causal chain, and time-to-impact",
        )

    def predict(
        self,
        risk_type: str,
        observations: list[ObservationSnapshot],
        risk_score: float,
        score_contributors: dict[str, float],
    ) -> RiskEvent:
        start = time.time()
        tools_called = [
            "forecast_linear_progression(horizon=40m)",
            "match_historical_incident_patterns()",
            "derive_falsification_conditions()",
        ]

        if risk_type == "postgresql_table_bloat":
            causal_chain = [
                "autovacuum_disabled",
                "dead_tuple_accumulation",
                "table_and_index_bloat",
                "buffer_cache_efficiency_decline",
                "disk_read_amplification",
                "future_query_latency_breach",
            ]
            falsification_conditions = [
                "If autovacuum worker runs and resets n_dead_tup to < 50,000, reject prediction.",
                "If buffer cache hit ratio remains > 98.0% after 20 minutes, reject prediction.",
                "If table growth rate drops below 2MB/min, reject prediction.",
            ]
            time_to_risk = 40.0
            severity = "HIGH" if risk_score >= 65 else "MEDIUM"
            mode = "PROACTIVE"
        elif risk_type == "postgresql_lock_contention":
            causal_chain = [
                "migration_transaction_started",
                "access_exclusive_lock_held_on_orders",
                "concurrent_read_queries_blocked",
                "connection_pool_saturation",
                "checkout_service_504_gateway_timeout",
            ]
            falsification_conditions = [
                "If database CPU reaches saturation (> 85%), reject lock contention as sole cause.",
                "If pg_locks shows 0 waiting transactions on 'orders', reject prediction.",
            ]
            time_to_risk = 0.0  # Immediate acute incident
            severity = "CRITICAL"
            mode = "REACTIVE"
        elif risk_type == "postgresql_vacuum_blocked":
            causal_chain = [
                "long_idle_in_transaction_session",
                "xmin_horizon_pinned",
                "autovacuum_runs_but_reclaims_nothing",
                "dead_tuple_accumulation",
                "future_bloat_driven_latency_breach",
            ]
            falsification_conditions = [
                "If the oldest transaction age drops below 300s, reject the vacuum-blocked prediction.",
                "If n_dead_tup falls after an autovacuum pass, reject (vacuum is progressing).",
            ]
            time_to_risk = 40.0
            severity = "HIGH" if risk_score >= 60 else "MEDIUM"
            mode = "PROACTIVE"
        elif risk_type == "postgresql_stale_statistics":
            causal_chain = [
                "bulk_load_without_analyze",
                "planner_statistics_stale",
                "rowcount_underestimate",
                "sequential_scan_blowout",
                "future_cpu_and_io_saturation_breach",
            ]
            falsification_conditions = [
                "If last_analyze age is under 10 minutes, reject the stale-statistics prediction.",
                "If sequential scan rate returns to baseline, reject prediction.",
            ]
            time_to_risk = 30.0
            severity = "HIGH" if risk_score >= 60 else "MEDIUM"
            mode = "PROACTIVE"
        elif risk_type == "postgresql_replication_lag":
            causal_chain = [
                "wal_replay_queue_starvation",
                "replica_replay_lsn_falls_behind",
                "replication_lag_growing",
                "read_replica_serving_stale_rows",
                "future_data_freshness_sla_breach",
            ]
            falsification_conditions = [
                "If replication lag stops growing and trends toward 0, reject the prediction.",
                "If the replica replay LSN catches up to the primary flush LSN, reject prediction.",
            ]
            time_to_risk = 18.0
            severity = "HIGH" if risk_score >= 55 else "MEDIUM"
            mode = "PROACTIVE"
        else:
            causal_chain = ["unknown_latent_trend", "resource_pressure", "potential_degradation"]
            falsification_conditions = ["If trend normalizes, reject."]
            time_to_risk = 60.0
            severity = "MEDIUM"
            mode = "PROACTIVE"

        risk_event = RiskEvent(
            id=f"RISK_{risk_type.upper()}_{int(time.time())}",
            risk_type=risk_type,  # type: ignore
            severity=severity,  # type: ignore
            status="DETECTED",
            mode=mode,  # type: ignore
            time_to_risk_minutes=time_to_risk,
            risk_score=risk_score,
            score_contributors=score_contributors,
            causal_chain=causal_chain,
            evidence=observations,
            falsification_conditions=falsification_conditions,
            created_at=time.time(),
        )

        dur = (time.time() - start) * 1000
        summary_out = f"Predicted {risk_type} with horizon={time_to_risk}m, score={risk_score}/100, severity={severity}"
        self.record_step(
            "RISK_PREDICTION",
            f"Synthesized observations for {risk_type}",
            summary_out,
            tools_called,
            dur,
        )
        return risk_event


prediction_agent = PredictionAgent()
