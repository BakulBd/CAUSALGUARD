"""
Unit and integration tests for CausalGuard.
Validates early warning scoring, verifier hypothesis falsification,
causal DAG construction, and API routes.
"""

from fastapi.testclient import TestClient

from backend.agents.verifier_agent import verifier_agent
from backend.api.main import app
from backend.causal.graph import CausalGraphEngine
from backend.simulation.sandbox import sandbox_engine
from backend.telemetry.early_warning import early_warning_engine

client = TestClient(app)


def test_early_warning_bloat_detection():
    score, contributors, observations = early_warning_engine.evaluate_postgres_telemetry(
        n_dead_tuples=1500000,
        n_live_tuples=2000000,
        last_autovacuum_age_sec=2000.0,
        buffer_cache_hit_ratio=0.82,
        table_size_mb=750.0,
        disk_read_iops=600.0,
        p99_latency_ms=75.0,
    )
    assert score > 60.0
    assert "dead_tuple_growth" in contributors
    assert contributors["dead_tuple_growth"] > 15.0
    assert any(obs.id == "OBSK_METRIC_POSTGRES_NDEAD_TUPLES_001" for obs in observations)


def test_verifier_falsification_cpu_vs_lock():
    # In lock contention, CPU is low (11.4%). A CPU saturation claim must be REJECTED.
    hypo_cpu = verifier_agent.verify_hypothesis(
        claim="Database CPU saturation caused latency",
        target_entity="postgres-db.cpu",
        expected_signature={"cpu_saturation_min": 85.0},
        actual_telemetry={"cpu": 11.4},
    )
    assert hypo_cpu.verification_status == "REJECTED"
    assert hypo_cpu.contradiction_reason is not None
    assert "Expected cpu_saturation >= 85.0%" in hypo_cpu.contradiction_reason

    # The actual lock contention hypothesis must be VERIFIED
    hypo_lock = verifier_agent.verify_hypothesis(
        claim="AccessExclusiveLock held by uncommitted migration blocks queries",
        target_entity="postgres-db.locks",
        expected_signature={"waiting_queries_min": 1.0},
        actual_telemetry={"waiting_queries": 38.0},
    )
    assert hypo_lock.verification_status == "VERIFIED"
    assert hypo_lock.contradiction_reason is None


def test_causal_graph_structure():
    cg = CausalGraphEngine.build_table_bloat_graph(
        dead_tuples=1200000,
        bloat_ratio=0.35,
        cache_hit_ratio=0.84,
        p99_latency_ms=65.0,
        last_autovacuum_age_sec=1900.0,
    )
    model = cg.to_model()
    node_ids = {n.id for n in model.nodes}
    assert "node_autovac_disabled" in node_ids
    assert "node_dead_tuples" in node_ids
    assert "node_predicted_outage" in node_ids
    assert len(model.edges) >= 5


def test_counterfactual_simulation():
    comp = sandbox_engine.simulate_table_bloat(
        current_dead_tuples=1200000,
        current_cache_hit_ratio=0.85,
        current_p99_latency_ms=55.0,
        horizon_minutes=40,
    )
    assert comp.baseline_do_nothing.expected_sla_breach is True
    assert comp.candidate_intervention.expected_sla_breach is False
    assert comp.expected_risk_reduction_pct > 70.0


def test_api_routes():
    res_state = client.get("/api/system/state")
    assert res_state.status_code == 200
    assert "status" in res_state.json()

    res_amd = client.get("/api/system/amd-metrics")
    assert res_amd.status_code == 200
    assert "device_name" in res_amd.json()

    res_bench = client.get("/api/benchmarks")
    assert res_bench.status_code == 200
    assert "baselines" in res_bench.json()
    assert "CausalGuard (Full Closed-Loop)" in res_bench.json()["baselines"]

    res_inv = client.post("/api/investigations")
    assert res_inv.status_code == 200
    dossier = res_inv.json()
    assert "incident_id" in dossier
    assert "causal_graph" in dossier
