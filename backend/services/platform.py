"""PlatformService: async orchestration over telemetry, pipeline, sandbox, storage."""

from __future__ import annotations

import time
from typing import Any

from backend.agents.counterfactual_agent import counterfactual_agent
from backend.agents.log_agent import log_agent
from backend.agents.metric_agent import metric_agent
from backend.agents.prediction_agent import prediction_agent
from backend.agents.topology_agent import topology_agent
from backend.agents.trace_agent import trace_agent
from backend.agents.verifier_agent import verifier_agent
from backend.config import CausalGuardSettings, get_settings
from backend.errors import NotFoundError
from backend.models.schema import (
    ComponentHealth,
    CounterfactualComparison,
    IncidentDossier,
    InterventionVerification,
    PostgresTelemetrySnapshot,
    TelemetrySourceStatus,
)
from backend.observability import get_logger, observe_investigation
from backend.observability.metrics import set_risk_score
from backend.persistence.repository import DossierRepository
from backend.scenarios.state import (
    KNOWN_SCENARIOS,
    mark_intervention_applied,
    reset_scenario,
    scenario_context,
    set_scenario,
)
from backend.services.pipeline import (
    _RECOMMENDATION,
    build_dossier,
    resolve_risk,
    status_label,
)
from backend.simulation.base import Sandbox
from backend.telemetry.sources.base import ScenarioContext, TelemetrySource

log = get_logger("causalguard.platform")

_ACTION_FOR_RISK: dict[str, str] = {
    "postgresql_table_bloat": "VACUUM_ANALYZE",
    "postgresql_lock_contention": "TERMINATE_BLOCKING_PID",
    "postgresql_vacuum_blocked": "TERMINATE_BLOCKING_PID",
    "postgresql_stale_statistics": "VACUUM_ANALYZE",
    "postgresql_replication_lag": "SCALE_CONNECTION_POOL",
}

_AGENTS = (
    metric_agent,
    trace_agent,
    log_agent,
    topology_agent,
    prediction_agent,
    counterfactual_agent,
    verifier_agent,
)


class PlatformService:
    def __init__(
        self,
        *,
        telemetry_source: TelemetrySource,
        sandbox: Sandbox,
        repository: DossierRepository,
        settings: CausalGuardSettings | None = None,
        context: ScenarioContext | None = None,
    ) -> None:
        self.telemetry_source = telemetry_source
        self.sandbox = sandbox
        self.repository = repository
        self.settings = settings or get_settings()
        self.context = context or scenario_context
        self._dossiers: dict[str, IncidentDossier] = {}
        self._started_at = time.time()

    # -- scenario state machine ---------------------------------------- #

    @property
    def scenario(self) -> str:
        return self.context.scenario

    def start_scenario(self, name: str) -> dict[str, Any]:
        if name not in KNOWN_SCENARIOS:
            raise NotFoundError(
                f"Unknown scenario '{name}'.",
                details={"valid": [s for s in KNOWN_SCENARIOS if s != "healthy"]},
            )
        set_scenario(name)
        log.info("scenario started", extra={"scenario": name})
        return {"status": "started", "scenario": name, "started_at": self.context.started_at}

    def stop_scenario(self) -> dict[str, Any]:
        prev = self.context.scenario
        reset_scenario()
        log.info("scenario stopped", extra={"previous": prev})
        return {"status": "stopped", "previous_scenario": prev}

    # -- telemetry --------------------------------------------------- #

    async def snapshot(self) -> PostgresTelemetrySnapshot:
        return await self.telemetry_source.postgres_snapshot(self.context)

    async def telemetry_status(self) -> TelemetrySourceStatus:
        return await self.telemetry_source.health()

    async def get_system_state(self) -> dict[str, Any]:
        from backend.telemetry.early_warning import early_warning_engine

        snap = await self.snapshot()
        score, _c, _o = early_warning_engine.evaluate_postgres_telemetry(
            **snap.as_early_warning_kwargs()
        )
        risk_type, _mode = resolve_risk(snap, self.context)
        healthy_score = score < 15.0
        active = 0 if (self.context.intervention_applied or healthy_score) else 1
        label = status_label(None if healthy_score else risk_type, score, self.context)
        set_risk_score(score)
        state = TelemetrySource.derive_system_state(
            snap, risk_score=score, active_risks_count=active, status_label=label
        )
        state["degraded"] = ":" in snap.source_mode  # e.g. "postgres:degraded"
        return state

    # -- risks ------------------------------------------------------ #

    async def list_risks(self) -> list[dict[str, Any]]:
        from backend.telemetry.early_warning import early_warning_engine

        snap = await self.snapshot()
        score, _c, _o = early_warning_engine.evaluate_postgres_telemetry(
            **snap.as_early_warning_kwargs()
        )
        if self.context.intervention_applied or score < 15.0:
            return []
        risk_type, mode = resolve_risk(snap, self.context)
        titles = {
            "postgresql_table_bloat": "PostgreSQL Table Bloat (Latent Risk)",
            "postgresql_lock_contention": "PostgreSQL Lock Contention (Active Contention)",
            "postgresql_vacuum_blocked": "PostgreSQL Vacuum Blocked (xmin Horizon Pinned)",
            "postgresql_stale_statistics": "PostgreSQL Stale Planner Statistics",
            "postgresql_replication_lag": "PostgreSQL Replication Lag (Freshness Risk)",
        }
        is_acute = risk_type == "postgresql_lock_contention"
        severity = "CRITICAL" if is_acute else ("HIGH" if score >= 60 else "MEDIUM")
        return [
            {
                "id": f"RISK_{risk_type.upper()}_001",
                "risk_type": risk_type,
                "title": titles.get(risk_type, risk_type),
                "severity": severity,
                "mode": mode,
                "time_to_risk": "Immediate" if is_acute else "~40 min",
                "risk_score": round(score, 1),
                "evidence_count": 5,
                "source_mode": snap.source_mode,
            }
        ]

    # -- investigation -------------------------------------------- #

    async def run_investigation(self) -> IncidentDossier:
        snap = await self.snapshot()
        risk_type, mode = resolve_risk(snap, self.context)
        with observe_investigation(risk_type, mode):
            dossier = build_dossier(snap, self.context, risk_type=risk_type, mode=mode)
        self._dossiers[dossier.incident_id] = dossier
        set_risk_score(dossier.risk_score)
        await self.repository.save_dossier(
            dossier.model_dump(), scenario=self.context.scenario, source_mode=snap.source_mode
        )
        log.info(
            "investigation complete",
            extra={
                "dossier_id": dossier.incident_id,
                "risk_type": dossier.risk_type,
                "risk_score": dossier.risk_score,
                "source_mode": snap.source_mode,
            },
        )
        return dossier

    async def get_dossier(self, dossier_id: str) -> IncidentDossier:
        if dossier_id in self._dossiers:
            return self._dossiers[dossier_id]
        stored = await self.repository.get_dossier(dossier_id)
        if stored:
            return IncidentDossier.model_validate(stored)
        raise NotFoundError(f"Dossier '{dossier_id}' not found.")

    async def latest_dossier(self, *, run_if_missing: bool = True) -> IncidentDossier:
        if self._dossiers:
            return next(reversed(self._dossiers.values()))
        stored = await self.repository.latest_dossier()
        if stored:
            return IncidentDossier.model_validate(stored)
        if run_if_missing:
            return await self.run_investigation()
        raise NotFoundError("No dossiers available.")

    async def list_dossiers(
        self, *, limit: int, offset: int, risk_type: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        items = await self.repository.list_dossiers(limit=limit, offset=offset, risk_type=risk_type)
        if items:
            return items, await self.repository.count_dossiers()
        # in-memory fallback
        mem = [
            {
                "incident_id": d.incident_id,
                "risk_type": d.risk_type,
                "mode": d.mode,
                "severity": d.severity,
                "risk_score": d.risk_score,
                "scenario": d.scenario,
                "source_mode": d.source_mode,
                "verified": d.verification is not None,
                "generated_at": d.generated_at,
            }
            for d in reversed(list(self._dossiers.values()))
        ]
        if risk_type:
            mem = [m for m in mem if m["risk_type"] == risk_type]
        return mem[offset : offset + limit], len(mem)

    async def simulate_counterfactual(self, risk_id: str) -> CounterfactualComparison:
        snap = await self.snapshot()
        risk_type, _mode = resolve_risk(snap, self.context)
        return counterfactual_agent.evaluate_for_risk(
            risk_type=risk_type,
            snapshot=snap,
            horizon_minutes=self.settings.thresholds.forecast_horizon_minutes,
        )

    async def apply_intervention(self, dossier_id: str | None = None) -> InterventionVerification:
        snap = await self.snapshot()
        risk_type, _mode = resolve_risk(snap, self.context)
        action = _ACTION_FOR_RISK.get(risk_type, "VACUUM_ANALYZE")
        verification = await self.sandbox.execute_intervention(
            risk_type,
            action_type=action,
            snapshot=snap,
            target_pids=snap.blocking_pids or None,
        )
        mark_intervention_applied()

        target_id = dossier_id
        if target_id is None and self._dossiers:
            target_id = next(reversed(self._dossiers))
        if target_id and target_id in self._dossiers:
            self._dossiers[target_id].verification = verification
        if target_id:
            await self.repository.update_dossier_verification(target_id, verification.model_dump())
        log.info(
            "intervention applied",
            extra={
                "risk_type": risk_type,
                "action": action,
                "verified": verification.verified,
                "risk_reduction_pct": verification.risk_reduction_pct,
                "environment": verification.environment,
            },
        )
        return verification

    def agent_traces(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for agent in _AGENTS:
            for s in agent.history:
                steps.append(s.model_dump())
        steps.sort(key=lambda x: x["timestamp"])
        return steps

    # -- health ---------------------------------------------------- #

    async def readiness(self) -> list[ComponentHealth]:
        checks: list[ComponentHealth] = []

        tstatus = await self.telemetry_status()
        checks.append(
            ComponentHealth(
                name="telemetry_source",
                status="ok" if tstatus.healthy else ("degraded" if tstatus.degraded else "down"),
                detail=f"{tstatus.mode} ({tstatus.active_mode}): {tstatus.detail}",
                latency_ms=tstatus.latency_ms,
            )
        )

        if self.repository.enabled:
            ok = await self.repository._db.ping()
            checks.append(
                ComponentHealth(
                    name="database",
                    status="ok" if ok else "down",
                    detail="persistence reachable" if ok else "persistence unreachable",
                )
            )
        else:
            checks.append(
                ComponentHealth(name="database", status="skipped", detail="persistence disabled")
            )

        checks.append(await self.sandbox.health())
        return checks

    async def aclose(self) -> None:
        await self.telemetry_source.aclose()
        await self.sandbox.aclose()


def build_recommendation(risk_type: str) -> str:
    return _RECOMMENDATION.get(risk_type, _RECOMMENDATION["postgresql_table_bloat"])
