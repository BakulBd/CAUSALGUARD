import time

import pytest

from backend.models.schema import PostgresTelemetrySnapshot
from backend.services.pipeline import build_dossier, classify_risk, resolve_risk, status_label
from backend.telemetry.sources.base import ScenarioContext
from backend.telemetry.sources.simulated import SimulatedTelemetrySource

SCENARIO_TO_RISK = {
    "pg-table-bloat": "postgresql_table_bloat",
    "pg-lock-contention": "postgresql_lock_contention",
    "pg-vacuum-blocked": "postgresql_vacuum_blocked",
    "pg-stale-statistics": "postgresql_stale_statistics",
    "pg-replication-lag": "postgresql_replication_lag",
}


def _snapshot(scenario: str, age: float = 58.0) -> PostgresTelemetrySnapshot:
    ctx = ScenarioContext(scenario=scenario, started_at=time.time() - age)
    return SimulatedTelemetrySource().snapshot(ctx)


@pytest.mark.parametrize("scenario,risk", list(SCENARIO_TO_RISK.items()))
def test_classification_matches_scenario(scenario, risk):
    snap = _snapshot(scenario)
    detected, _mode = classify_risk(snap)
    assert detected == risk, f"{scenario}: expected {risk}, got {detected}"


def test_healthy_snapshot_classifies_as_no_risk():
    assert classify_risk(_snapshot("healthy"))[0] is None


def test_resolve_risk_uses_declared_scenario_when_ambiguous():
    # a "healthy"-looking snapshot but operator declared a scenario
    snap = _snapshot("healthy")
    ctx = ScenarioContext(scenario="pg-stale-statistics")
    risk, _mode = resolve_risk(snap, ctx)
    assert risk == "postgresql_stale_statistics"


@pytest.mark.parametrize("scenario,risk", list(SCENARIO_TO_RISK.items()))
def test_build_dossier_shape_and_falsification(scenario, risk):
    ctx = ScenarioContext(scenario=scenario, started_at=time.time() - 58)
    snap = SimulatedTelemetrySource().snapshot(ctx)
    dossier = build_dossier(snap, ctx)

    assert dossier.risk_type == risk
    assert dossier.incident_id.startswith("DOSSIER_")
    assert dossier.causal_graph.nodes and dossier.causal_graph.edges
    assert dossier.evidence, "expected agent evidence"
    assert dossier.counterfactual.expected_risk_reduction_pct > 0
    # every scenario carries a naive hypothesis that must be REJECTED and a
    # true hypothesis that must be VERIFIED
    statuses = {h.verification_status for h in dossier.hypotheses_evaluated}
    assert "REJECTED" in statuses
    assert "VERIFIED" in statuses
    assert dossier.rejected_hypotheses


def test_lock_contention_cpu_hypothesis_is_rejected():
    ctx = ScenarioContext(scenario="pg-lock-contention")
    snap = SimulatedTelemetrySource().snapshot(ctx)
    dossier = build_dossier(snap, ctx)
    cpu_hypos = [h for h in dossier.hypotheses_evaluated if "CPU" in h.claim]
    assert cpu_hypos and all(h.verification_status == "REJECTED" for h in cpu_hypos)
    assert any("11.4" in (h.contradiction_reason or "") for h in cpu_hypos)


def test_status_label_thresholds():
    ctx = ScenarioContext(scenario="healthy")
    assert status_label(None, 2.0, ctx) == "HEALTHY"
    assert status_label("postgresql_table_bloat", 55.0, ctx) == "PRE_INCIDENT_RISK_DETECTED"
    assert status_label("postgresql_lock_contention", 80.0, ctx) == "ACUTE_INCIDENT_ACTIVE"
    ctx.intervention_applied = True
    assert status_label("postgresql_table_bloat", 80.0, ctx) == "RECOVERED (VERIFIED)"
