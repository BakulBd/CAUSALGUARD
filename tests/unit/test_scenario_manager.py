"""The synchronous legacy ScenarioManager path used by scripts."""

import time

import pytest

from backend.scenarios.scenario_manager import ScenarioManager

SCENARIOS = [
    "pg-table-bloat",
    "pg-lock-contention",
    "pg-vacuum-blocked",
    "pg-stale-statistics",
    "pg-replication-lag",
]


@pytest.fixture
def sm():
    return ScenarioManager()


def test_healthy_baseline(sm):
    sm.stop_scenario()
    state = sm.get_current_system_state()
    assert state["status"] == "HEALTHY"
    assert state["active_risks_count"] == 0


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_full_sync_flow(sm, scenario):
    started = sm.start_scenario(scenario)
    assert started["scenario"] == scenario
    # age the scenario so signals have ramped
    sm._ctx.started_at = time.time() - 58

    state = sm.get_current_system_state()
    assert state["scenario"] == scenario
    assert state["active_risks_count"] == 1

    dossier = sm.run_investigation()
    assert dossier.incident_id in sm.dossiers
    assert dossier.risk_type.startswith("postgresql_")
    assert dossier.causal_graph.nodes

    verification = sm.apply_verified_intervention(dossier.incident_id)
    assert verification.verified is True
    assert sm.intervention_applied is True
    assert sm.dossiers[dossier.incident_id].verification is not None

    # after intervention the state reports recovered
    assert sm.get_current_system_state()["status"] == "RECOVERED (VERIFIED)"

    sm.stop_scenario()
    assert sm.active_scenario == "healthy"


def test_unknown_scenario_raises(sm):
    with pytest.raises(ValueError):
        sm.start_scenario("does-not-exist")
