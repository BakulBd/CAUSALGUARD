"""
Scenario Manager (synchronous, simulated).

Kept for scripts (``scripts/run_demo.sh``, ``scripts/reset_environment.sh``) and
backwards compatibility. It always drives the deterministic
:class:`SimulatedTelemetrySource` and shares the process-wide scenario context
with the async :class:`~backend.services.platform.PlatformService`, so starting a
scenario here is visible to the API and vice versa.

Supported scenarios:
1. pg-table-bloat          - autovacuum disabled, dead tuples climb, cache drops
2. pg-lock-contention      - ACCESS EXCLUSIVE lock; naive CPU hypothesis falsified
3. pg-vacuum-blocked       - long idle-in-transaction pins the xmin horizon
4. pg-stale-statistics     - missing ANALYZE -> sequential scan blowout
5. pg-replication-lag      - WAL replay starvation on the replica
"""

from __future__ import annotations

from typing import Any

from backend.models.schema import IncidentDossier, InterventionVerification
from backend.scenarios.state import (
    KNOWN_SCENARIOS,
    mark_intervention_applied,
    reset_scenario,
    scenario_context,
    set_scenario,
)
from backend.services.pipeline import build_dossier, resolve_risk, status_label
from backend.simulation.sandbox import sandbox_engine
from backend.telemetry.early_warning import early_warning_engine
from backend.telemetry.sources.base import TelemetrySource
from backend.telemetry.sources.simulated import SimulatedTelemetrySource

_ACTION_FOR_RISK = {
    "postgresql_table_bloat": "VACUUM_ANALYZE",
    "postgresql_lock_contention": "pg_terminate_backend(14022)",
    "postgresql_vacuum_blocked": "pg_terminate_backend(idle_in_tx)",
    "postgresql_stale_statistics": "ANALYZE",
    "postgresql_replication_lag": "relieve_replay_starvation",
}


class ScenarioManager:
    def __init__(self) -> None:
        self._source = SimulatedTelemetrySource()
        self._ctx = scenario_context
        self.dossiers: dict[str, IncidentDossier] = {}

    # -- scenario state ------------------------------------------------ #

    @property
    def active_scenario(self) -> str:
        return self._ctx.scenario

    @property
    def intervention_applied(self) -> bool:
        return self._ctx.intervention_applied

    def start_scenario(self, scenario_name: str) -> dict[str, Any]:
        if scenario_name not in KNOWN_SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario_name}'")
        set_scenario(scenario_name)
        return {"status": "started", "scenario": scenario_name, "started_at": self._ctx.started_at}

    def stop_scenario(self) -> dict[str, Any]:
        prev = self._ctx.scenario
        reset_scenario()
        return {"status": "stopped", "previous_scenario": prev}

    # -- telemetry / state ------------------------------------------- #

    def get_current_system_state(self) -> dict[str, Any]:
        snap = self._source.snapshot(self._ctx)
        score, _c, _o = early_warning_engine.evaluate_postgres_telemetry(
            **snap.as_early_warning_kwargs()
        )
        risk_type, _mode = resolve_risk(snap, self._ctx)
        healthy = score < 15.0
        active = 0 if (self._ctx.intervention_applied or healthy) else 1
        label = status_label(None if healthy else risk_type, score, self._ctx)
        return TelemetrySource.derive_system_state(
            snap, risk_score=score, active_risks_count=active, status_label=label
        )

    # -- pipeline -------------------------------------------------- #

    def run_investigation(self) -> IncidentDossier:
        snap = self._source.snapshot(self._ctx)
        dossier = build_dossier(snap, self._ctx)
        self.dossiers[dossier.incident_id] = dossier
        return dossier

    def apply_verified_intervention(self, dossier_id: str) -> InterventionVerification:
        snap = self._source.snapshot(self._ctx)
        risk_type, _mode = resolve_risk(snap, self._ctx)
        action = _ACTION_FOR_RISK.get(risk_type, "VACUUM_ANALYZE")
        verification = sandbox_engine.execute_controlled_intervention(risk_type, action)
        mark_intervention_applied()
        if dossier_id in self.dossiers:
            self.dossiers[dossier_id].verification = verification
        return verification


scenario_manager = ScenarioManager()
