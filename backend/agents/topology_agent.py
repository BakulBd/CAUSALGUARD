"""
Topology Agent.
Constructs service dependency graphs, inspects Kubernetes deployment events,
and associates configuration changes with system risk.
"""

import time

from backend.agents.base_agent import BaseAgent
from backend.models.schema import ObservationSnapshot
from backend.storage.observation_store import global_observation_store


class TopologyAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "TopologyAgent",
            "Construct service dependency graph and correlate deployments/config mutations",
        )

    def get_service_dependency_graph(self) -> dict[str, list[str]]:
        return {
            "frontend-api": ["checkout-service", "catalog-service"],
            "checkout-service": ["postgres-db", "payment-service"],
            "catalog-service": ["postgres-db"],
            "postgres-db": [],
        }

    def get_kubernetes_events(self) -> list[dict]:
        return [
            {
                "type": "Normal",
                "reason": "ConfigMapUpdated",
                "message": "Updated postgres-config with maintenance settings",
            },
            {
                "type": "Normal",
                "reason": "Scheduled",
                "message": "Batch migration job started on node worker-02",
            },
        ]

    def get_recent_deployments(self) -> list[dict]:
        return [
            {
                "service": "postgres-db",
                "change": "ALTER TABLE orders SET (autovacuum_enabled = false)",
                "ago_minutes": 32,
            }
        ]

    def get_git_changes(self) -> list[dict]:
        return [
            {
                "commit": "a82f01c",
                "author": "devops@company.org",
                "message": "Disable autovacuum during bulk import",
            }
        ]

    _RISK_MUTATION = {
        "postgresql_table_bloat": "ALTER TABLE orders SET (autovacuum_enabled = false)",
        "postgresql_vacuum_blocked": "batch job opened a transaction and never committed (idle in transaction)",
        "postgresql_stale_statistics": "bulk COPY import of 3.1M rows with no subsequent ANALYZE",
        "postgresql_lock_contention": "online schema migration acquired ACCESS EXCLUSIVE lock on orders",
        "postgresql_replication_lag": "replica instance resized down / heavy write batch deployed to primary",
    }

    def analyze(self, risk_type: str | None = None) -> list[ObservationSnapshot]:
        start = time.time()
        tools_called = [
            "get_service_dependency_graph()",
            "get_kubernetes_events()",
            "get_recent_deployments()",
            "get_git_changes()",
        ]

        mutation = self._RISK_MUTATION.get(risk_type or "", "autovacuum_enabled = false")
        obs = ObservationSnapshot(
            id="OBSK_TOPO_CONFIG_MUTATION_001",
            category="topology",
            source="kubernetes/postgres-db",
            name="topology.config_mutation",
            window="60m",
            current_value=1.0,
            baseline_value=0.0,
            trend="stable",
            slope=0.0,
            change_point=True,
            z_score=1.0,
            details={
                "mutation": mutation,
                "affected_service": "postgres-db",
                "upstream_blast_radius": ["checkout-service", "catalog-service", "frontend-api"],
            },
        )
        global_observation_store.put_observation(obs)

        dur = (time.time() - start) * 1000
        summary_out = "Mapped upstream blast radius: postgres-db -> [checkout-service, catalog-service, frontend-api]"
        self.record_step(
            "TOPOLOGY_MAPPING",
            "Resolved service dependency graph and deployment changes",
            summary_out,
            tools_called,
            dur,
        )
        return [obs]


topology_agent = TopologyAgent()
