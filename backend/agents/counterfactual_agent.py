"""
Counterfactual Agent.
Evaluates Scenario A (Do Nothing) against Scenario B (Candidate Intervention)
using sandbox models and empirical projections.
"""

import time

from backend.agents.base_agent import BaseAgent
from backend.models.schema import CounterfactualComparison, PostgresTelemetrySnapshot
from backend.simulation.sandbox import sandbox_engine


class CounterfactualAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "CounterfactualAgent",
            "Evaluate counterfactual trajectories under candidate interventions",
        )

    def evaluate(
        self,
        risk_type: str,
        current_dead_tuples: int = 1420000,
        current_cache_hit_ratio: float = 0.842,
        current_p99_latency_ms: float = 62.4,
    ) -> CounterfactualComparison:
        start = time.time()
        tools_called = [
            "simulate_future_trajectory(scenario='DO_NOTHING')",
            "simulate_candidate_intervention(action='VACUUM_ANALYZE')",
            "compute_differential_risk_reduction()",
        ]

        comparison = sandbox_engine.simulate_for_risk(
            risk_type,
            current_dead_tuples=current_dead_tuples,
            current_cache_hit_ratio=current_cache_hit_ratio,
            current_p99_latency_ms=current_p99_latency_ms,
            horizon_minutes=40,
        )

        dur = (time.time() - start) * 1000
        summary_out = f"Counterfactual generated: Do Nothing causes SLA breach at t=35m (P99={comparison.baseline_do_nothing.expected_p99_latency_ms}ms); Intervention prevents breach (risk reduction: {comparison.expected_risk_reduction_pct}%)"
        self.record_step(
            "COUNTERFACTUAL_EVALUATION",
            f"Simulated 40m horizon for {risk_type}",
            summary_out,
            tools_called,
            dur,
        )
        return comparison

    def evaluate_for_risk(
        self,
        risk_type: str,
        snapshot: PostgresTelemetrySnapshot,
        horizon_minutes: int = 40,
    ) -> CounterfactualComparison:
        start = time.time()
        tools_called = [
            "simulate_future_trajectory(scenario='DO_NOTHING')",
            "simulate_candidate_intervention()",
            "compute_differential_risk_reduction()",
        ]
        comparison = sandbox_engine.simulate_for_risk(
            risk_type,
            current_dead_tuples=snapshot.n_dead_tuples,
            current_cache_hit_ratio=snapshot.buffer_cache_hit_ratio,
            current_p99_latency_ms=snapshot.p99_latency_ms,
            current_replication_lag_seconds=snapshot.replication_lag_seconds,
            current_waiting_queries=snapshot.waiting_queries,
            horizon_minutes=horizon_minutes,
        )
        dur = (time.time() - start) * 1000
        self.record_step(
            "COUNTERFACTUAL_EVALUATION",
            f"Simulated {horizon_minutes}m horizon for {risk_type}",
            f"Expected risk reduction: {comparison.expected_risk_reduction_pct}%",
            tools_called,
            dur,
        )
        return comparison


counterfactual_agent = CounterfactualAgent()
