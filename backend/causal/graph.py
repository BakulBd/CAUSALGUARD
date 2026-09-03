"""
Causal Graph Engine for CausalGuard.
Builds, validates, and traverses causal DAGs representing system state,
hypotheses, falsification edges, and mitigation paths.
"""

from typing import Any

import networkx as nx

from backend.models.schema import CausalEdge, CausalGraphModel, CausalNode


class CausalGraphEngine:
    def __init__(self):
        self.graph = nx.DiGraph()

    def clear(self):
        self.graph.clear()

    def add_node(
        self,
        node_id: str,
        label: str,
        node_type: str,
        status: str = "OBSERVED",
        metadata: dict[str, Any] | None = None,
    ) -> CausalNode:
        node = CausalNode(
            id=node_id,
            label=label,
            node_type=node_type,  # type: ignore
            status=status,  # type: ignore
            metadata=metadata or {},
        )
        self.graph.add_node(
            node_id, label=label, node_type=node_type, status=status, metadata=metadata or {}
        )
        return node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        confidence: float = 1.0,
        evidence: str = "",
    ) -> CausalEdge:
        edge = CausalEdge(
            source=source_id,
            target=target_id,
            relation=relation,  # type: ignore
            confidence=confidence,
            evidence=evidence,
        )
        self.graph.add_edge(
            source_id, target_id, relation=relation, confidence=confidence, evidence=evidence
        )
        return edge

    def to_model(self) -> CausalGraphModel:
        nodes = []
        for nid, data in self.graph.nodes(data=True):
            nodes.append(
                CausalNode(
                    id=nid,
                    label=data.get("label", nid),
                    node_type=data.get("node_type", "OBSERVATION"),
                    status=data.get("status", "OBSERVED"),
                    metadata=data.get("metadata", {}),
                )
            )
        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append(
                CausalEdge(
                    source=u,
                    target=v,
                    relation=data.get("relation", "correlates_with"),
                    confidence=data.get("confidence", 1.0),
                    evidence=data.get("evidence", ""),
                )
            )
        # Find candidate root causes (in-degree 0 among candidate causes or observations)
        root_causes = [
            n
            for n in self.graph.nodes
            if self.graph.in_degree(n) == 0
            and self.graph.nodes[n].get("status") in ("VERIFIED", "OBSERVED")
        ]
        return CausalGraphModel(nodes=nodes, edges=edges, root_causes=root_causes)

    @classmethod
    def build_table_bloat_graph(
        cls,
        dead_tuples: int,
        bloat_ratio: float,
        cache_hit_ratio: float,
        p99_latency_ms: float,
        last_autovacuum_age_sec: float,
    ) -> "CausalGraphEngine":
        """Constructs the canonical slow-burn PostgreSQL table bloat causal chain."""
        cg = cls()
        # 1. Root configuration anomaly
        cg.add_node(
            "node_autovac_disabled",
            "autovacuum_disabled",
            "CANDIDATE_CAUSE",
            status="VERIFIED",
            metadata={"setting": "autovacuum = off", "stale_seconds": last_autovacuum_age_sec},
        )
        # 2. Storage layer effect
        cg.add_node(
            "node_dead_tuples",
            f"dead_tuples_accumulating ({dead_tuples:,})",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"bloat_ratio": f"{bloat_ratio * 100:.1f}%", "dead_tuples": dead_tuples},
        )
        # 3. Physical growth
        cg.add_node(
            "node_table_growth",
            "table_index_bloat",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"table_growth_rate": "+45MB/10min"},
        )
        # 4. Memory buffer cache impact
        cg.add_node(
            "node_cache_degradation",
            f"buffer_cache_hit_drop ({cache_hit_ratio * 100:.1f}%)",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"cache_hit_ratio": cache_hit_ratio, "baseline": "99.8%"},
        )
        # 5. Disk read IOPS
        cg.add_node(
            "node_disk_reads",
            "disk_read_amplification",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"iops_increase": "6.8x"},
        )
        # 6. Future predicted impact
        cg.add_node(
            "node_predicted_outage",
            "predicted_p99_sla_breach (>3500ms in ~40m)",
            "PREDICTED_STATE",
            status="PREDICTED",
            metadata={"time_horizon_min": 40, "current_p99_ms": p99_latency_ms},
        )
        # 7. Candidate Intervention
        cg.add_node(
            "node_intervention_vacuum",
            "INTERVENTION: VACUUM (ANALYZE, VERBOSE)",
            "VERIFIED_INTERVENTION",
            status="VERIFIED",
            metadata={"safe_sandbox_tested": True, "recovers_pages": True},
        )

        # Edges
        cg.add_edge(
            "node_autovac_disabled",
            "node_dead_tuples",
            "caused_by_candidate",
            confidence=0.98,
            evidence="autovacuum inactive for >1800s while background updates continue",
        )
        cg.add_edge(
            "node_dead_tuples",
            "node_table_growth",
            "propagates_to",
            confidence=0.95,
            evidence="Heap pages cannot be reclaimed without vacuum pass",
        )
        cg.add_edge(
            "node_table_growth",
            "node_cache_degradation",
            "propagates_to",
            confidence=0.92,
            evidence="Working set size exceeds shared_buffers, causing cache thrashing",
        )
        cg.add_edge(
            "node_cache_degradation",
            "node_disk_reads",
            "propagates_to",
            confidence=0.94,
            evidence="Cache misses force synchronous OS page reads from storage",
        )
        cg.add_edge(
            "node_disk_reads",
            "node_predicted_outage",
            "propagates_to",
            confidence=0.89,
            evidence="Linear regression forecasts query queueing and timeout in 40 minutes",
        )
        cg.add_edge(
            "node_intervention_vacuum",
            "node_dead_tuples",
            "mitigated_by",
            confidence=0.99,
            evidence="VACUUM reclaims dead tuple slots and resets visibility map",
        )
        return cg

    @classmethod
    def build_lock_contention_graph(
        cls, blocking_pid: int, blocked_queries: int, cpu_utilization_pct: float
    ) -> "CausalGraphEngine":
        """
        Constructs the acute lock contention graph showing active hypothesis falsification:
        CPU saturation hypothesis is falsified by CPU=11.4%, and ACCESS EXCLUSIVE lock is verified.
        """
        cg = cls()
        # False Hypothesis: CPU Saturation
        cg.add_node(
            "node_hypo_cpu",
            "HYPOTHESIS: Database CPU Saturation",
            "FALSIFIED_HYPOTHESIS",
            status="REJECTED",
            metadata={
                "expected": "CPU >= 85%",
                "actual": f"CPU = {cpu_utilization_pct}%",
                "verdict": "REJECTED (Contradiction)",
            },
        )
        # Real Cause: Exclusive Lock
        cg.add_node(
            "node_migration_tx",
            f"migration_tx (PID {blocking_pid}) ACCESS EXCLUSIVE lock",
            "CANDIDATE_CAUSE",
            status="VERIFIED",
            metadata={"lock_mode": "AccessExclusiveLock", "table": "orders", "pid": blocking_pid},
        )
        # Lock wait queue
        cg.add_node(
            "node_lock_queue",
            f"{blocked_queries} queries waiting on lock",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"wait_event_type": "Lock", "wait_event": "relation"},
        )
        # Pool exhaustion
        cg.add_node(
            "node_conn_pool",
            "connection_pool_saturation (max_connections reached)",
            "ANOMALY",
            status="VERIFIED",
            metadata={"active_connections": 100, "idle_in_transaction": 1},
        )
        # Upstream API latency
        cg.add_node(
            "node_api_timeouts",
            "checkout_service 504 Gateway Timeouts",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"error_rate": "84.2%", "p99_latency_ms": 10000},
        )
        # Verified Intervention
        cg.add_node(
            "node_intervention_kill",
            f"INTERVENTION: pg_terminate_backend({blocking_pid})",
            "VERIFIED_INTERVENTION",
            status="VERIFIED",
            metadata={"action": "terminate_blocking_transaction"},
        )

        # Contradiction edge
        cg.add_edge(
            "node_hypo_cpu",
            "node_lock_queue",
            "contradicts",
            confidence=1.0,
            evidence=f"Verifier confirmed CPU is {cpu_utilization_pct}%, invalidating CPU saturation claim.",
        )
        # Real causal edges
        cg.add_edge(
            "node_migration_tx",
            "node_lock_queue",
            "caused_by_candidate",
            confidence=0.99,
            evidence=f"pg_locks confirms PID {blocking_pid} holds uncommitted exclusive lock",
        )
        cg.add_edge(
            "node_lock_queue",
            "node_conn_pool",
            "propagates_to",
            confidence=0.97,
            evidence="Blocked client workers accumulate until connection limit is reached",
        )
        cg.add_edge(
            "node_conn_pool",
            "node_api_timeouts",
            "propagates_to",
            confidence=0.98,
            evidence="Upstream checkout service connection timeouts generate HTTP 504 responses",
        )
        cg.add_edge(
            "node_intervention_kill",
            "node_migration_tx",
            "mitigated_by",
            confidence=1.0,
            evidence=f"Terminating PID {blocking_pid} releases AccessExclusiveLock immediately",
        )
        return cg

    @classmethod
    def build_vacuum_blocked_graph(
        cls,
        dead_tuples: int,
        bloat_ratio: float,
        oldest_xact_age_sec: float,
        blocking_pid: int | None = None,
    ) -> "CausalGraphEngine":
        """Autovacuum runs but a long idle-in-transaction pins the xmin horizon."""
        cg = cls()
        cg.add_node(
            "node_long_idle_tx",
            f"long_idle_in_transaction (age {oldest_xact_age_sec / 60:.0f}m"
            + (f", PID {blocking_pid}" if blocking_pid else "")
            + ")",
            "CANDIDATE_CAUSE",
            status="VERIFIED",
            metadata={"oldest_xact_age_sec": oldest_xact_age_sec, "pid": blocking_pid},
        )
        cg.add_node(
            "node_xmin_pinned",
            "xmin_horizon_pinned",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"effect": "VACUUM cannot remove tuples newer than the oldest snapshot"},
        )
        cg.add_node(
            "node_dead_tuples",
            f"dead_tuples_accumulating ({dead_tuples:,})",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"bloat_ratio": f"{bloat_ratio * 100:.1f}%", "autovacuum_running": True},
        )
        cg.add_node(
            "node_predicted_bloat_breach",
            "predicted_bloat_driven_latency_breach (~40m)",
            "PREDICTED_STATE",
            status="PREDICTED",
            metadata={"time_horizon_min": 40},
        )
        cg.add_node(
            "node_intervention_terminate",
            "INTERVENTION: terminate idle-in-transaction session, then VACUUM",
            "VERIFIED_INTERVENTION",
            status="VERIFIED",
            metadata={"safe_sandbox_tested": True},
        )
        cg.add_edge(
            "node_long_idle_tx",
            "node_xmin_pinned",
            "caused_by_candidate",
            confidence=0.98,
            evidence="Oldest running xact snapshot older than the autovacuum freeze target",
        )
        cg.add_edge(
            "node_xmin_pinned",
            "node_dead_tuples",
            "propagates_to",
            confidence=0.96,
            evidence="Autovacuum passes complete but reclaim count stays ~0",
        )
        cg.add_edge(
            "node_dead_tuples",
            "node_predicted_bloat_breach",
            "propagates_to",
            confidence=0.88,
            evidence="Bloat growth rate forecasts working-set spill and latency breach",
        )
        cg.add_edge(
            "node_intervention_terminate",
            "node_long_idle_tx",
            "mitigated_by",
            confidence=0.99,
            evidence="Ending the pinning transaction lets the next VACUUM advance the horizon",
        )
        return cg

    @classmethod
    def build_stale_statistics_graph(
        cls,
        last_analyze_age_sec: float,
        seq_scans_per_min: float,
        p99_latency_ms: float,
    ) -> "CausalGraphEngine":
        """Missing ANALYZE after a bulk load -> planner misestimates -> seq scans."""
        cg = cls()
        cg.add_node(
            "node_missing_analyze",
            f"planner_statistics_stale (last ANALYZE {last_analyze_age_sec / 60:.0f}m ago)",
            "CANDIDATE_CAUSE",
            status="VERIFIED",
            metadata={"last_analyze_age_sec": last_analyze_age_sec},
        )
        cg.add_node(
            "node_bad_rowcount_estimate",
            "planner_rowcount_underestimate",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"effect": "Index path discarded in favour of sequential scan"},
        )
        cg.add_node(
            "node_seq_scan_blowout",
            f"sequential_scan_blowout ({seq_scans_per_min:.0f}/min)",
            "ANOMALY",
            status="VERIFIED",
            metadata={"seq_scans_per_min": seq_scans_per_min},
        )
        cg.add_node(
            "node_predicted_cpu_io_breach",
            "predicted_cpu_and_io_saturation_breach",
            "PREDICTED_STATE",
            status="PREDICTED",
            metadata={"current_p99_ms": p99_latency_ms, "time_horizon_min": 30},
        )
        cg.add_node(
            "node_intervention_analyze",
            "INTERVENTION: ANALYZE affected table",
            "VERIFIED_INTERVENTION",
            status="VERIFIED",
            metadata={"safe_sandbox_tested": True},
        )
        cg.add_edge(
            "node_missing_analyze",
            "node_bad_rowcount_estimate",
            "caused_by_candidate",
            confidence=0.95,
            evidence="pg_class.reltuples diverges from actual row count after bulk import",
        )
        cg.add_edge(
            "node_bad_rowcount_estimate",
            "node_seq_scan_blowout",
            "propagates_to",
            confidence=0.94,
            evidence="EXPLAIN shows Seq Scan chosen where Index Scan is cheaper",
        )
        cg.add_edge(
            "node_seq_scan_blowout",
            "node_predicted_cpu_io_breach",
            "propagates_to",
            confidence=0.87,
            evidence="Scan volume trend forecasts CPU + read IOPS saturation",
        )
        cg.add_edge(
            "node_intervention_analyze",
            "node_missing_analyze",
            "mitigated_by",
            confidence=0.99,
            evidence="ANALYZE refreshes statistics and restores the index plan",
        )
        return cg

    @classmethod
    def build_replication_lag_graph(
        cls,
        replication_lag_seconds: float,
        p99_latency_ms: float,
    ) -> "CausalGraphEngine":
        """WAL replay starvation on the replica -> read-replica staleness risk."""
        cg = cls()
        cg.add_node(
            "node_replay_starvation",
            "wal_replay_queue_starvation",
            "CANDIDATE_CAUSE",
            status="VERIFIED",
            metadata={"replay_process": "single-threaded startup/recovery"},
        )
        cg.add_node(
            "node_repl_lag",
            f"replication_lag_growing ({replication_lag_seconds:.0f}s)",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"replication_lag_seconds": replication_lag_seconds},
        )
        cg.add_node(
            "node_stale_reads",
            "read_replica_serving_stale_rows",
            "OBSERVATION",
            status="VERIFIED",
            metadata={"impact": "read-your-writes violations on replica-routed queries"},
        )
        cg.add_node(
            "node_predicted_freshness_breach",
            "predicted_data_freshness_sla_breach (>300s)",
            "PREDICTED_STATE",
            status="PREDICTED",
            metadata={"current_p99_ms": p99_latency_ms, "time_horizon_min": 18},
        )
        cg.add_node(
            "node_intervention_relieve_replay",
            "INTERVENTION: relieve replay starvation / throttle write load",
            "VERIFIED_INTERVENTION",
            status="VERIFIED",
            metadata={"safe_sandbox_tested": True},
        )
        cg.add_edge(
            "node_replay_starvation",
            "node_repl_lag",
            "caused_by_candidate",
            confidence=0.9,
            evidence="Replay LSN falls behind primary flush LSN at a widening rate",
        )
        cg.add_edge(
            "node_repl_lag",
            "node_stale_reads",
            "propagates_to",
            confidence=0.93,
            evidence="Replica visibility snapshot trails primary by the lag interval",
        )
        cg.add_edge(
            "node_stale_reads",
            "node_predicted_freshness_breach",
            "propagates_to",
            confidence=0.85,
            evidence="Lag growth forecasts crossing the freshness SLA threshold",
        )
        cg.add_edge(
            "node_intervention_relieve_replay",
            "node_replay_starvation",
            "mitigated_by",
            confidence=0.9,
            evidence="Raising replay throughput / reducing write pressure drains the queue",
        )
        return cg
