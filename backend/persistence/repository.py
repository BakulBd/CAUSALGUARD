"""Repository operations over the persistence layer."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import delete, func, select

from backend.observability import get_logger
from backend.persistence.database import Database
from backend.persistence.models import (
    DossierRecord,
    InterventionRecord,
    ObservationRecord,
    ScenarioEventRecord,
)

log = get_logger("causalguard.repository")


class DossierRepository:
    """Persists investigation dossiers, interventions, observations and events.

    All methods degrade gracefully: if the database is not ready they log and
    return sensible empties so the API keeps serving from in-memory state.
    """

    def __init__(self, database: Database, *, retention: int = 500) -> None:
        self._db = database
        self._retention = retention

    @property
    def enabled(self) -> bool:
        return self._db.ready

    async def save_dossier(
        self,
        dossier: dict[str, Any],
        *,
        scenario: str,
        source_mode: str,
    ) -> None:
        if not self.enabled:
            return
        now = time.time()
        record = DossierRecord(
            id=dossier["incident_id"],
            risk_type=dossier.get("risk_type", "unknown"),
            mode=dossier.get("mode", "unknown"),
            severity=dossier.get("severity", "unknown"),
            risk_score=float(dossier.get("risk_score", 0.0)),
            scenario=scenario,
            source_mode=source_mode,
            verified=1 if dossier.get("verification") else 0,
            payload=dossier,
            created_at=dossier.get("generated_at", now),
            updated_at=now,
        )
        try:
            async with self._db.session() as session:
                await session.merge(record)
                for obs in dossier.get("evidence", []):
                    session.add(
                        ObservationRecord(
                            obs_key=obs.get("id", "unknown"),
                            dossier_id=record.id,
                            category=obs.get("category", "system"),
                            source=obs.get("source", "unknown"),
                            name=obs.get("name", ""),
                            current_value=float(obs.get("current_value", 0.0)),
                            baseline_value=float(obs.get("baseline_value", 0.0)),
                            trend=obs.get("trend", "stable"),
                            z_score=float(obs.get("z_score", 0.0)),
                            payload=obs,
                            created_at=obs.get("timestamp", now),
                        )
                    )
            await self._enforce_retention()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("save_dossier failed", extra={"error": str(exc)})

    async def update_dossier_verification(
        self, dossier_id: str, verification: dict[str, Any]
    ) -> None:
        if not self.enabled:
            return
        try:
            async with self._db.session() as session:
                row = await session.get(DossierRecord, dossier_id)
                if row is None:
                    return
                payload = dict(row.payload)
                payload["verification"] = verification
                row.payload = payload
                row.verified = 1
                row.updated_at = time.time()
                session.add(
                    InterventionRecord(
                        id=verification["intervention_id"],
                        dossier_id=dossier_id,
                        action_name=verification.get("action_name", "unknown"),
                        environment=verification.get("environment", "CONTROLLED_SANDBOX"),
                        verified=1 if verification.get("verified") else 0,
                        risk_reduction_pct=float(verification.get("risk_reduction_pct", 0.0)),
                        notes="\n".join(verification.get("audit_notes", [])),
                        payload=verification,
                        created_at=verification.get("executed_at", time.time()),
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("update_dossier_verification failed", extra={"error": str(exc)})

    async def get_dossier(self, dossier_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._db.session() as session:
            row = await session.get(DossierRecord, dossier_id)
            return dict(row.payload) if row else None

    async def latest_dossier(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._db.session() as session:
            stmt = select(DossierRecord).order_by(DossierRecord.created_at.desc()).limit(1)
            row = (await session.execute(stmt)).scalars().first()
            return dict(row.payload) if row else None

    async def list_dossiers(
        self, *, limit: int = 50, offset: int = 0, risk_type: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        async with self._db.session() as session:
            stmt = select(DossierRecord).order_by(DossierRecord.created_at.desc())
            if risk_type:
                stmt = stmt.where(DossierRecord.risk_type == risk_type)
            stmt = stmt.limit(limit).offset(offset)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "incident_id": r.id,
                    "risk_type": r.risk_type,
                    "mode": r.mode,
                    "severity": r.severity,
                    "risk_score": r.risk_score,
                    "scenario": r.scenario,
                    "source_mode": r.source_mode,
                    "verified": bool(r.verified),
                    "generated_at": r.created_at,
                }
                for r in rows
            ]

    async def count_dossiers(self) -> int:
        if not self.enabled:
            return 0
        async with self._db.session() as session:
            return int((await session.execute(select(func.count(DossierRecord.id)))).scalar() or 0)

    async def record_scenario_event(
        self, *, scenario: str, action: str, source_mode: str, detail: dict[str, Any] | None = None
    ) -> None:
        if not self.enabled:
            return
        try:
            async with self._db.session() as session:
                session.add(
                    ScenarioEventRecord(
                        scenario=scenario,
                        action=action,
                        source_mode=source_mode,
                        detail=detail or {},
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("record_scenario_event failed", extra={"error": str(exc)})

    async def observation_history(
        self, *, obs_key: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        async with self._db.session() as session:
            stmt = select(ObservationRecord).order_by(ObservationRecord.created_at.desc())
            if obs_key:
                stmt = stmt.where(ObservationRecord.obs_key == obs_key)
            stmt = stmt.limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [dict(r.payload) for r in rows]

    async def _enforce_retention(self) -> None:
        if self._retention <= 0:
            return
        async with self._db.session() as session:
            total = int((await session.execute(select(func.count(DossierRecord.id)))).scalar() or 0)
            if total <= self._retention:
                return
            cutoff_stmt = (
                select(DossierRecord.created_at)
                .order_by(DossierRecord.created_at.desc())
                .limit(1)
                .offset(self._retention - 1)
            )
            cutoff = (await session.execute(cutoff_stmt)).scalar()
            if cutoff is None:
                return
            await session.execute(delete(DossierRecord).where(DossierRecord.created_at < cutoff))
            await session.execute(
                delete(ObservationRecord).where(ObservationRecord.created_at < cutoff)
            )
