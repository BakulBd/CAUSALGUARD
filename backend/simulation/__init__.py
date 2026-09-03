"""Sandbox: counterfactual modelling and empirical intervention verification."""

from __future__ import annotations

from backend.config import CausalGuardSettings, get_settings
from backend.observability import get_logger
from backend.simulation.base import Sandbox
from backend.simulation.sandbox import CounterfactualSandbox, sandbox_engine
from backend.simulation.simulated_sandbox import SimulatedSandbox

log = get_logger("causalguard.sandbox")

__all__ = [
    "CounterfactualSandbox",
    "Sandbox",
    "SimulatedSandbox",
    "build_sandbox",
    "sandbox_engine",
]


def build_sandbox(settings: CausalGuardSettings | None = None) -> Sandbox:
    settings = settings or get_settings()
    if settings.sandbox.mode == "real":
        try:
            from backend.simulation.real_sandbox import RealPostgresSandbox

            sandbox = RealPostgresSandbox(settings)
            log.info("sandbox: real PostgreSQL sandbox")
            return sandbox
        except Exception as exc:
            log.error(
                "real sandbox init failed; using simulated sandbox",
                extra={"error": str(exc)},
            )
    log.info("sandbox: simulated")
    return SimulatedSandbox()
