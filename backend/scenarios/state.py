"""Process-wide operator-declared scenario state.

Shared by :class:`~backend.services.platform.PlatformService` (async API path)
and :class:`~backend.scenarios.scenario_manager.ScenarioManager` (sync script /
legacy path) so ``start_scenario`` and ``get_system_state`` always agree.
"""

from __future__ import annotations

import time

from backend.telemetry.sources.base import KNOWN_SCENARIOS, ScenarioContext

scenario_context = ScenarioContext()


def set_scenario(name: str) -> ScenarioContext:
    scenario_context.scenario = name
    scenario_context.started_at = time.time()
    scenario_context.intervention_applied = False
    return scenario_context


def reset_scenario() -> ScenarioContext:
    scenario_context.scenario = "healthy"
    scenario_context.started_at = time.time()
    scenario_context.intervention_applied = False
    return scenario_context


def mark_intervention_applied() -> None:
    scenario_context.intervention_applied = True


__all__ = [
    "KNOWN_SCENARIOS",
    "mark_intervention_applied",
    "reset_scenario",
    "scenario_context",
    "set_scenario",
]
