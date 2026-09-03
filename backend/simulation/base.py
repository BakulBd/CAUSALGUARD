"""Sandbox interface: counterfactual modelling + empirical intervention verification."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models.schema import (
    ComponentHealth,
    CounterfactualComparison,
    InterventionVerification,
    PostgresTelemetrySnapshot,
)


class Sandbox(ABC):
    #: "simulated" | "real"
    mode: str = "simulated"

    @abstractmethod
    async def counterfactual(
        self, risk_type: str, *, snapshot: PostgresTelemetrySnapshot, horizon_minutes: int = 40
    ) -> CounterfactualComparison: ...

    @abstractmethod
    async def execute_intervention(
        self,
        risk_type: str,
        *,
        action_type: str,
        snapshot: PostgresTelemetrySnapshot,
        target_pids: list[int] | None = None,
    ) -> InterventionVerification: ...

    async def health(self) -> ComponentHealth:  # pragma: no cover - trivial default
        return ComponentHealth(name="sandbox", status="ok", detail=f"{self.mode} sandbox")

    async def aclose(self) -> None:  # pragma: no cover
        return None
