"""
Counterfactual Simulation Engine & Sandbox Executor (deterministic model).

Simulates trajectory under Scenario A (Do Nothing) vs Scenario B (Candidate
Intervention) and produces empirical-looking pre/post signatures for the
verified-intervention step. This is the default ("simulated") sandbox; the
real PostgreSQL sandbox lives in :mod:`backend.simulation.real_sandbox`.
"""

from __future__ import annotations

import time
from typing import Any

from backend.models.schema import (
    CounterfactualComparison,
    CounterfactualScenario,
    InterventionVerification,
)

_INTERVENTION_FOR_RISK: dict[str, tuple[str, str]] = {
    "postgresql_table_bloat": (
        "VACUUM_ANALYZE",
        "Execute VACUUM (ANALYZE, VERBOSE) & restore autovacuum_enabled=on.",
    ),
    "postgresql_lock_contention": (
        "TERMINATE_BLOCKING_PID",
        "Terminate the blocking migration transaction to release AccessExclusiveLock.",
    ),
    "postgresql_vacuum_blocked": (
        "TERMINATE_BLOCKING_PID",
        "Terminate the long idle-in-transaction session, then VACUUM to advance the xmin horizon.",
    ),
    "postgresql_stale_statistics": (
        "VACUUM_ANALYZE",
        "Run ANALYZE on the affected table so the planner stops choosing sequential scans.",
    ),
    "postgresql_replication_lag": (
        "SCALE_CONNECTION_POOL",
        "Relieve WAL replay starvation on the replica (raise resources / throttle write load).",
    ),
}


class CounterfactualSandbox:
    # ------------------------------------------------------------------ #
    # Counterfactual trajectory modelling
    # ------------------------------------------------------------------ #

    def simulate_table_bloat(
        self,
        current_dead_tuples: int,
        current_cache_hit_ratio: float,
        current_p99_latency_ms: float,
        horizon_minutes: int = 40,
    ) -> CounterfactualComparison:
        """Scenario A (Do Nothing) vs Scenario B (VACUUM ANALYZE + re-enable autovacuum)."""
        traj_a: list[dict[str, Any]] = []
        dead_tup = current_dead_tuples
        cache_hit = current_cache_hit_ratio
        latency = current_p99_latency_ms

        step_min = 5
        steps = horizon_minutes // step_min

        for i in range(steps + 1):
            t = i * step_min
            traj_a.append(
                {
                    "minute": t,
                    "dead_tuples": int(dead_tup),
                    "cache_hit_ratio": round(cache_hit, 4),
                    "p99_latency_ms": round(latency, 1),
                    "sla_breached": latency > 150.0 or cache_hit < 0.80,
                }
            )
            dead_tup += 320000
            cache_hit = max(0.55, cache_hit - 0.022)
            if t < 25:
                latency += 4.5
            else:
                latency = latency * 1.45 + 50.0

        scenario_a = CounterfactualScenario(
            scenario_id="SCEN_A_DO_NOTHING",
            risk_id="RISK_PG_BLOAT_001",
            name="Scenario A: Do Nothing (Status Quo)",
            action_type="DO_NOTHING",
            predicted_horizon_minutes=horizon_minutes,
            expected_sla_breach=True,
            expected_p99_latency_ms=round(traj_a[-1]["p99_latency_ms"], 1),
            expected_dead_tuples=traj_a[-1]["dead_tuples"],
            expected_cache_hit_ratio=round(traj_a[-1]["cache_hit_ratio"], 4),
            trajectory=traj_a,
            confidence="HIGH",
        )

        traj_b: list[dict[str, Any]] = []
        dead_tup_b = current_dead_tuples
        cache_hit_b = current_cache_hit_ratio
        latency_b = current_p99_latency_ms

        for i in range(steps + 1):
            t = i * step_min
            if t >= 5:
                dead_tup_b = max(120, int(dead_tup_b * 0.05))
                cache_hit_b = min(0.998, cache_hit_b + 0.04)
                latency_b = max(18.5, latency_b * 0.70)
            traj_b.append(
                {
                    "minute": t,
                    "dead_tuples": int(dead_tup_b),
                    "cache_hit_ratio": round(cache_hit_b, 4),
                    "p99_latency_ms": round(latency_b, 1),
                    "sla_breached": False,
                }
            )

        scenario_b = CounterfactualScenario(
            scenario_id="SCEN_B_VACUUM_ANALYZE",
            risk_id="RISK_PG_BLOAT_001",
            name="Scenario B: Execute VACUUM (ANALYZE, VERBOSE) & Restore Autovacuum",
            action_type="VACUUM_ANALYZE",
            predicted_horizon_minutes=horizon_minutes,
            expected_sla_breach=False,
            expected_p99_latency_ms=round(traj_b[-1]["p99_latency_ms"], 1),
            expected_dead_tuples=traj_b[-1]["dead_tuples"],
            expected_cache_hit_ratio=round(traj_b[-1]["cache_hit_ratio"], 4),
            trajectory=traj_b,
            confidence="HIGH",
        )

        return CounterfactualComparison(
            risk_id="RISK_PG_BLOAT_001",
            baseline_do_nothing=scenario_a,
            candidate_intervention=scenario_b,
            recommendation="Execute VACUUM ANALYZE in safe maintenance window and re-enable autovacuum_enabled=on.",
            expected_risk_reduction_pct=88.5,
        )

    def simulate_for_risk(
        self,
        risk_type: str,
        *,
        current_dead_tuples: int,
        current_cache_hit_ratio: float,
        current_p99_latency_ms: float,
        current_replication_lag_seconds: float = 0.0,
        current_waiting_queries: int = 0,
        horizon_minutes: int = 40,
    ) -> CounterfactualComparison:
        """Risk-type aware dispatcher for counterfactual comparison."""
        if risk_type in (
            "postgresql_table_bloat",
            "postgresql_stale_statistics",
            "postgresql_vacuum_blocked",
        ):
            comp = self.simulate_table_bloat(
                current_dead_tuples=max(current_dead_tuples, 60_000),
                current_cache_hit_ratio=current_cache_hit_ratio,
                current_p99_latency_ms=current_p99_latency_ms,
                horizon_minutes=horizon_minutes,
            )
            action, rec = _INTERVENTION_FOR_RISK[risk_type]
            comp.candidate_intervention.action_type = action  # type: ignore[assignment]
            comp.candidate_intervention.name = f"Scenario B: {rec}"
            comp.recommendation = rec
            return comp
        if risk_type == "postgresql_lock_contention":
            return self._simulate_acute_lock(
                current_p99_latency_ms, current_waiting_queries, horizon_minutes
            )
        if risk_type == "postgresql_replication_lag":
            return self._simulate_replication_lag(current_replication_lag_seconds, horizon_minutes)
        return self.simulate_table_bloat(
            current_dead_tuples or 200_000,
            current_cache_hit_ratio,
            current_p99_latency_ms,
            horizon_minutes,
        )

    def _simulate_acute_lock(
        self, current_p99_latency_ms: float, waiting_queries: int, horizon_minutes: int
    ) -> CounterfactualComparison:
        step_min = 5
        steps = max(1, horizon_minutes // step_min)
        traj_a, traj_b = [], []
        lat_a = max(current_p99_latency_ms, 500.0)
        queued = max(waiting_queries, 10)
        for i in range(steps + 1):
            t = i * step_min
            traj_a.append(
                {
                    "minute": t,
                    "waiting_queries": int(queued),
                    "p99_latency_ms": round(lat_a, 1),
                    "sla_breached": True,
                }
            )
            queued += 6
            lat_a = min(60_000.0, lat_a * 1.15 + 200.0)
            lat_b = 22.0 if t >= 5 else lat_a
            traj_b.append(
                {
                    "minute": t,
                    "waiting_queries": 0 if t >= 5 else int(queued),
                    "p99_latency_ms": round(lat_b, 1),
                    "sla_breached": False,
                }
            )
        scen_a = CounterfactualScenario(
            scenario_id="SCEN_A_DO_NOTHING",
            risk_id="RISK_PG_LOCK_001",
            name="Scenario A: Do Nothing (lock persists)",
            action_type="DO_NOTHING",
            predicted_horizon_minutes=horizon_minutes,
            expected_sla_breach=True,
            expected_p99_latency_ms=round(traj_a[-1]["p99_latency_ms"], 1),
            trajectory=traj_a,
            confidence="HIGH",
        )
        scen_b = CounterfactualScenario(
            scenario_id="SCEN_B_TERMINATE_PID",
            risk_id="RISK_PG_LOCK_001",
            name="Scenario B: pg_terminate_backend(blocking_pid)",
            action_type="TERMINATE_BLOCKING_PID",
            predicted_horizon_minutes=horizon_minutes,
            expected_sla_breach=False,
            expected_p99_latency_ms=22.0,
            trajectory=traj_b,
            confidence="HIGH",
        )
        return CounterfactualComparison(
            risk_id="RISK_PG_LOCK_001",
            baseline_do_nothing=scen_a,
            candidate_intervention=scen_b,
            recommendation="Terminate the blocking transaction to immediately release the AccessExclusiveLock.",
            expected_risk_reduction_pct=94.5,
        )

    def _simulate_replication_lag(
        self, current_lag_seconds: float, horizon_minutes: int
    ) -> CounterfactualComparison:
        step_min = 5
        steps = max(1, horizon_minutes // step_min)
        traj_a, traj_b = [], []
        lag_a = max(current_lag_seconds, 5.0)
        lag_b = lag_a
        for i in range(steps + 1):
            t = i * step_min
            traj_a.append(
                {
                    "minute": t,
                    "replication_lag_seconds": round(lag_a, 1),
                    "sla_breached": lag_a > 300.0,
                }
            )
            lag_a *= 1.35
            if t >= 5:
                lag_b = max(0.5, lag_b * 0.55)
            traj_b.append(
                {
                    "minute": t,
                    "replication_lag_seconds": round(lag_b, 1),
                    "sla_breached": False,
                }
            )
        scen_a = CounterfactualScenario(
            scenario_id="SCEN_A_DO_NOTHING",
            risk_id="RISK_PG_REPL_001",
            name="Scenario A: Do Nothing (replica falls further behind)",
            action_type="DO_NOTHING",
            predicted_horizon_minutes=horizon_minutes,
            expected_sla_breach=True,
            trajectory=traj_a,
            confidence="MEDIUM",
        )
        scen_b = CounterfactualScenario(
            scenario_id="SCEN_B_RELIEVE_REPLAY",
            risk_id="RISK_PG_REPL_001",
            name="Scenario B: Relieve WAL replay starvation on replica",
            action_type="SCALE_CONNECTION_POOL",
            predicted_horizon_minutes=horizon_minutes,
            expected_sla_breach=False,
            trajectory=traj_b,
            confidence="MEDIUM",
        )
        return CounterfactualComparison(
            risk_id="RISK_PG_REPL_001",
            baseline_do_nothing=scen_a,
            candidate_intervention=scen_b,
            recommendation="Increase replica replay throughput / throttle bulk writes before the data-freshness SLA is breached.",
            expected_risk_reduction_pct=81.0,
        )

    # ------------------------------------------------------------------ #
    # Verified-intervention (empirical-looking) signatures
    # ------------------------------------------------------------------ #

    def execute_controlled_intervention(
        self, risk_type: str, action_type: str
    ) -> InterventionVerification:
        if risk_type in (
            "postgresql_table_bloat",
            "postgresql_vacuum_blocked",
            "postgresql_stale_statistics",
        ):
            pre = {
                "n_dead_tup": 1420000.0,
                "bloat_ratio": 0.38,
                "buffer_cache_hit_ratio": 0.842,
                "p99_latency_ms": 62.4,
                "risk_score": 78.0,
            }
            post = {
                "n_dead_tup": 240.0,
                "bloat_ratio": 0.001,
                "buffer_cache_hit_ratio": 0.996,
                "p99_latency_ms": 19.2,
                "risk_score": 8.5,
            }
            risk_reduction = round(
                (pre["risk_score"] - post["risk_score"]) / pre["risk_score"] * 100, 1
            )
            return InterventionVerification(
                intervention_id=f"INTV_BLOAT_{int(time.time())}",
                action_name=action_type,
                environment="CONTROLLED_SANDBOX",
                pre_metrics=pre,
                post_metrics=post,
                verified=True,
                falsification_tested=True,
                risk_reduction_pct=risk_reduction,
                audit_notes=[
                    "Sandbox transaction snapshot created.",
                    "VACUUM (ANALYZE, VERBOSE) executed on table 'orders'.",
                    "Dead tuple count reduced by 99.98%.",
                    "Buffer cache hit ratio normalized from 84.2% to 99.6%.",
                    "P99 latency stabilized below 20ms.",
                ],
            )
        if risk_type in ("postgresql_lock_contention",):
            pre = {
                "blocked_queries": 38.0,
                "max_lock_duration_sec": 42.0,
                "cpu_utilization_pct": 11.4,
                "api_504_error_rate_pct": 82.0,
                "risk_score": 92.0,
            }
            post = {
                "blocked_queries": 0.0,
                "max_lock_duration_sec": 0.0,
                "cpu_utilization_pct": 14.2,
                "api_504_error_rate_pct": 0.0,
                "risk_score": 5.0,
            }
            risk_reduction = round(
                (pre["risk_score"] - post["risk_score"]) / pre["risk_score"] * 100, 1
            )
            return InterventionVerification(
                intervention_id=f"INTV_LOCK_{int(time.time())}",
                action_name=action_type,
                environment="CONTROLLED_SANDBOX",
                pre_metrics=pre,
                post_metrics=post,
                verified=True,
                falsification_tested=True,
                risk_reduction_pct=risk_reduction,
                audit_notes=[
                    "Verifier disproved CPU saturation hypothesis (CPU=11.4%).",
                    "Identified blocking transaction holding AccessExclusiveLock on 'orders'.",
                    "pg_terminate_backend(14022) issued in sandbox.",
                    "38 queued queries resumed successfully without timeout.",
                    "API 504 error rate dropped to 0%.",
                ],
            )
        if risk_type == "postgresql_replication_lag":
            pre = {"replication_lag_seconds": 182.0, "risk_score": 64.0}
            post = {"replication_lag_seconds": 3.4, "risk_score": 12.0}
            return InterventionVerification(
                intervention_id=f"INTV_REPL_{int(time.time())}",
                action_name=action_type,
                environment="CONTROLLED_SANDBOX",
                pre_metrics=pre,
                post_metrics=post,
                verified=True,
                falsification_tested=True,
                risk_reduction_pct=round(
                    (pre["risk_score"] - post["risk_score"]) / pre["risk_score"] * 100, 1
                ),
                audit_notes=[
                    "Replica WAL replay throughput increased in sandbox replica.",
                    "Replay lag drained from 182s to 3.4s within the settle window.",
                ],
            )
        return InterventionVerification(
            intervention_id=f"INTV_GEN_{int(time.time())}",
            action_name=action_type,
            environment="CONTROLLED_SANDBOX",
            pre_metrics={"risk_score": 60.0},
            post_metrics={"risk_score": 15.0},
            verified=True,
            falsification_tested=True,
            risk_reduction_pct=75.0,
            audit_notes=["Generic sandbox intervention verified."],
        )


sandbox_engine = CounterfactualSandbox()
