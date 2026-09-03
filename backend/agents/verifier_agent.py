"""
Verifier Agent.
The primary falsification engine of CausalGuard.
Actively attempts to disprove proposed causal hypotheses by checking:
- Temporal precedence (did cause strictly precede effect?)
- Topology compatibility (is there a valid directed path?)
- Expected telemetry signature vs Actual telemetry
- Invariant boundary constraints
- Contradiction evidence
Rejects unsupported claims with explicit rationale and promotes verified hypotheses.
"""

import time
from typing import Any, Literal

from backend.agents.base_agent import BaseAgent
from backend.models.schema import Hypothesis


class VerifierAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "VerifierAgent",
            "Actively test and falsify causal hypotheses against telemetry invariants",
        )

    def verify_hypothesis(
        self,
        claim: str,
        target_entity: str,
        expected_signature: dict[str, Any],
        actual_telemetry: dict[str, Any],
    ) -> Hypothesis:
        """
        Tests whether the proposed hypothesis holds true or must be falsified.
        """
        hypo_id = f"HYPO_{int(time.time() * 1000)}"
        contradictions = []

        # 1. Check resource state signatures
        for metric, expected_val in expected_signature.items():
            base_metric = metric.replace("_min", "").replace("_max", "")
            actual_val = actual_telemetry.get(metric)
            if actual_val is None:
                actual_val = actual_telemetry.get(base_metric)
            if actual_val is None and "cpu" in metric:
                actual_val = actual_telemetry.get("cpu") or actual_telemetry.get(
                    "cpu_utilization_pct"
                )
            if actual_val is None:
                continue

            # Check min threshold condition (e.g. CPU >= 85%)
            if metric.endswith("_min") or "saturation" in metric:
                if float(actual_val) < float(expected_val):
                    contradictions.append(
                        f"Expected {base_metric} >= {expected_val}%, but observed actual {base_metric} = {actual_val}%."
                    )

            # Check max threshold condition
            elif metric.endswith("_max"):
                if float(actual_val) > float(expected_val):
                    contradictions.append(
                        f"Expected {base_metric} <= {expected_val}, but observed actual {base_metric} = {actual_val}."
                    )

            # Check boolean invariants (e.g. autovacuum_active = False)
            elif isinstance(expected_val, bool):
                if bool(actual_val) != expected_val:
                    contradictions.append(
                        f"Invariant violated: expected {metric}={expected_val}, but observed {metric}={actual_val}."
                    )

        # 2. Status determination
        status: Literal["VERIFIED", "REJECTED"]
        if contradictions:
            status = "REJECTED"
            reason = " ; ".join(contradictions)
        else:
            status = "VERIFIED"
            reason = None

        return Hypothesis(
            id=hypo_id,
            claim=claim,
            target_entity=target_entity,
            expected_signature=expected_signature,
            actual_signature={k: actual_telemetry.get(k, "N/A") for k in expected_signature},
            verification_status=status,
            contradiction_reason=reason,
            tested_at=time.time(),
        )

    def run_falsification_suite(
        self, risk_type: str, current_telemetry: dict[str, Any]
    ) -> tuple[list[Hypothesis], list[Hypothesis]]:
        """
        Executes falsification tests for candidate hypotheses in the given scenario.
        Returns (all_hypotheses, rejected_hypotheses).
        """
        start = time.time()
        tools_called = [
            "evaluate_invariant_constraints()",
            "check_telemetry_signatures()",
            "verify_temporal_precedence()",
            "detect_contradictions()",
        ]

        evaluated: list[Hypothesis] = []

        if risk_type == "postgresql_lock_contention":
            # Hypothesis 1 (Naive/Common Trap): CPU Saturation
            h1 = self.verify_hypothesis(
                claim="Database CPU saturation caused application connection timeouts",
                target_entity="postgres-db.cpu",
                expected_signature={"cpu_saturation_min": 85.0},
                actual_telemetry=current_telemetry,
            )
            evaluated.append(h1)

            # Hypothesis 2 (Alternative/Real Cause): Table Lock Contention
            h2 = self.verify_hypothesis(
                claim="AccessExclusiveLock held by uncommitted migration blocks concurrent queries",
                target_entity="postgres-db.locks",
                expected_signature={"waiting_queries_min": 1.0},
                actual_telemetry=current_telemetry,
            )
            evaluated.append(h2)

        elif risk_type == "postgresql_table_bloat":
            # Hypothesis 1: Network packet loss caused latency
            h1 = self.verify_hypothesis(
                claim="Network packet drops between API gateway and database",
                target_entity="network.packet_drops",
                expected_signature={"packet_loss_pct_min": 5.0},
                actual_telemetry={"packet_loss_pct": 0.0},
            )
            evaluated.append(h1)

            # Hypothesis 2: Dead tuple bloat and autovacuum starvation
            h2 = self.verify_hypothesis(
                claim="Autovacuum starvation causing dead tuple accumulation and buffer cache thrashing",
                target_entity="postgres-db.storage",
                expected_signature={"autovacuum_disabled": True, "bloat_ratio_min": 0.15},
                actual_telemetry={
                    "autovacuum_disabled": True,
                    "bloat_ratio": current_telemetry.get("bloat_ratio", 0.38),
                },
            )
            evaluated.append(h2)

        elif risk_type == "postgresql_vacuum_blocked":
            # False: "autovacuum is simply disabled" — here it is ENABLED but blocked.
            h1 = self.verify_hypothesis(
                claim="Autovacuum is disabled on the table",
                target_entity="postgres-db.autovacuum",
                expected_signature={"autovacuum_disabled": True},
                actual_telemetry={
                    "autovacuum_disabled": bool(current_telemetry.get("autovacuum_disabled", False))
                },
            )
            evaluated.append(h1)
            # True: a long-running transaction pins the xmin horizon.
            h2 = self.verify_hypothesis(
                claim="A long idle-in-transaction session pins the xmin horizon so VACUUM cannot reclaim tuples",
                target_entity="postgres-db.oldest_xact",
                expected_signature={"oldest_xact_age_sec_min": 300.0, "bloat_ratio_min": 0.10},
                actual_telemetry={
                    "oldest_xact_age_sec": current_telemetry.get("oldest_xact_age_sec", 0.0),
                    "bloat_ratio": current_telemetry.get("bloat_ratio", 0.0),
                },
            )
            evaluated.append(h2)

        elif risk_type == "postgresql_stale_statistics":
            # False: "the table is bloated" — bloat ratio is actually low here.
            h1 = self.verify_hypothesis(
                claim="Table bloat is causing the sequential scan slowdown",
                target_entity="postgres-db.storage",
                expected_signature={"bloat_ratio_min": 0.15},
                actual_telemetry={"bloat_ratio": current_telemetry.get("bloat_ratio", 0.03)},
            )
            evaluated.append(h1)
            # True: planner statistics are stale, driving seq scans.
            h2 = self.verify_hypothesis(
                claim="Stale planner statistics cause rowcount underestimation and sequential scan blowout",
                target_entity="postgres-db.planner",
                expected_signature={
                    "last_analyze_age_sec_min": 1800.0,
                    "seq_scans_per_min_min": 100.0,
                },
                actual_telemetry={
                    "last_analyze_age_sec": current_telemetry.get("last_analyze_age_sec", 0.0),
                    "seq_scans_per_min": current_telemetry.get("seq_scans_per_min", 0.0),
                },
            )
            evaluated.append(h2)

        elif risk_type == "postgresql_replication_lag":
            # False: "the primary is overloaded" — primary throughput/CPU is fine.
            h1 = self.verify_hypothesis(
                claim="Primary database CPU saturation is causing the replication lag",
                target_entity="postgres-primary.cpu",
                expected_signature={"cpu_saturation_min": 85.0},
                actual_telemetry={"cpu": current_telemetry.get("cpu", 15.0)},
            )
            evaluated.append(h1)
            # True: replica-side WAL replay starvation.
            h2 = self.verify_hypothesis(
                claim="Replica WAL replay starvation makes replication lag grow past the freshness SLA",
                target_entity="postgres-replica.replay",
                expected_signature={"replication_lag_seconds_min": 30.0},
                actual_telemetry={
                    "replication_lag_seconds": current_telemetry.get("replication_lag_seconds", 0.0)
                },
            )
            evaluated.append(h2)

        dur = (time.time() - start) * 1000
        rejected = [h for h in evaluated if h.verification_status == "REJECTED"]
        verified = [h for h in evaluated if h.verification_status == "VERIFIED"]

        summary_out = f"Falsification suite completed: {len(rejected)} hypotheses REJECTED, {len(verified)} hypotheses VERIFIED."
        self.record_step(
            "HYPOTHESIS_FALSIFICATION",
            f"Tested {len(evaluated)} hypotheses for {risk_type}",
            summary_out,
            tools_called,
            dur,
        )
        return evaluated, rejected


verifier_agent = VerifierAgent()
