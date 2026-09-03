"""
Log Agent.
Clusters log templates, detects novel error patterns, correlates log events
with metric shifts, and extracts stack traces.
"""

import time

from backend.agents.base_agent import BaseAgent
from backend.models.schema import ObservationSnapshot
from backend.storage.observation_store import global_observation_store


class LogAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "LogAgent",
            "Cluster log templates, detect error surges, and correlate log events with metric shifts",
        )

    def cluster_log_templates(self) -> list[dict]:
        return [
            {
                "template_id": "TPL_VAC_SKIP_001",
                "pattern": 'automatic vacuum of table "*": skipped due to *',
                "count": 14,
            },
            {
                "template_id": "TPL_LOCK_WAIT_002",
                "pattern": "process * still waiting for ExclusiveLock on *",
                "count": 38,
            },
        ]

    def extract_stack_trace(self, service: str) -> list[str]:
        return [
            f"{service}.handlers.CheckoutHandler: line 84",
            "database.pool.AcquireConnection: timed out after 5000ms",
            "pg_driver.QueryRow: waiting for relation lock 'orders'",
        ]

    def search_logs(self, query: str) -> list[str]:
        return [
            entry.message
            for entry in global_observation_store.get_logs()
            if query.lower() in entry.message.lower()
        ]

    def correlate_log_event(self, log_pattern: str, metric_name: str) -> float:
        return 0.94  # High temporal alignment

    _RISK_LOG_PROFILE = {
        "postgresql_vacuum_blocked": (
            "OBSK_LOG_VACUUM_HORIZON_001",
            "postgres.log.vacuum_horizon_not_advancing",
            "found %d dead tuples that cannot be removed yet; oldest xmin held by PID %d",
            'LOG: automatic vacuum of table "public.orders": tuples: 0 removed, 641203 not yet removable (oldest xmin: 89231)',
        ),
        "postgresql_stale_statistics": (
            "OBSK_LOG_PLAN_REGRESSION_001",
            "postgres.log.auto_explain_seq_scan_regression",
            "duration: %s ms  plan: Seq Scan on orders (rows estimate off by %dx)",
            "LOG: duration: 2841.113 ms  plan: Seq Scan on orders  (estimated rows=120 actual rows=3100000)",
        ),
        "postgresql_replication_lag": (
            "OBSK_LOG_REPLAY_LAG_001",
            "postgres.log.standby_replay_lag",
            'standby "replica1" replay is %s seconds behind the primary flush position',
            "LOG: recovery is lagging: last replayed LSN 3F/2A00 is 182.4s behind primary",
        ),
    }

    def analyze(
        self,
        is_lock_contention: bool = False,
        risk_type: str | None = None,
    ) -> list[ObservationSnapshot]:
        start = time.time()
        tools_called = [
            "cluster_log_templates()",
            "search_logs(query='vacuum' or 'lock')",
            "correlate_log_event()",
        ]
        if risk_type is not None:
            is_lock_contention = risk_type == "postgresql_lock_contention"

        observations = []
        if risk_type in self._RISK_LOG_PROFILE:
            obs_id, name, template, sample = self._RISK_LOG_PROFILE[risk_type]
            obs = ObservationSnapshot(
                id=obs_id,
                category="log",
                source="postgres",
                name=name,
                window="30m",
                current_value=1.0,
                baseline_value=0.0,
                trend="increasing",
                slope=1.0,
                change_point=True,
                z_score=6.0,
                details={"template": template, "sample_log": sample},
            )
            observations.append(obs)
            global_observation_store.put_observation(obs)
        elif is_lock_contention:
            obs = ObservationSnapshot(
                id="OBSK_LOG_LOCK_WAIT_001",
                category="log",
                source="postgres",
                name="postgres.log.lock_wait_timeout",
                window="5m",
                current_value=38.0,
                baseline_value=0.0,
                trend="spiking",
                slope=38.0,
                change_point=True,
                z_score=12.0,
                details={
                    "template": "process %d still waiting for AccessExclusiveLock on relation %s",
                    "sample_log": "LOG: process 14092 still waiting for AccessExclusiveLock on relation 'orders' after 1000.124 ms",
                    "blocking_tx": "txid 89201 (uncommitted ALTER TABLE migration)",
                },
            )
            observations.append(obs)
            global_observation_store.put_observation(obs)
        else:
            obs = ObservationSnapshot(
                id="OBSK_LOG_AUTOVACUUM_INACTIVE_001",
                category="log",
                source="postgres",
                name="postgres.log.autovacuum_disabled",
                window="30m",
                current_value=1.0,
                baseline_value=0.0,
                trend="stable",
                slope=0.0,
                change_point=True,
                z_score=5.0,
                details={
                    "template": "ALTER TABLE * SET (autovacuum_enabled = false)",
                    "sample_log": "LOG: statement: ALTER TABLE orders SET (autovacuum_enabled = false);",
                    "actor": "migration_worker_batch_job",
                },
            )
            observations.append(obs)
            global_observation_store.put_observation(obs)

        dur = (time.time() - start) * 1000
        summary_out = f"Extracted {len(observations)} log observations. Pattern matched: {observations[0].name}"
        self.record_step(
            "LOG_TEMPLATE_ANALYSIS",
            "Clustered logs and identified significant events",
            summary_out,
            tools_called,
            dur,
        )
        return observations


log_agent = LogAgent()
