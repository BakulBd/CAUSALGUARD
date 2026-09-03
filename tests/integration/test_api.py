import pytest

pytestmark = pytest.mark.integration


def test_health_ready_metrics(client):
    assert client.get("/health").json()["status"] == "ok"

    ready = client.get("/ready").json()
    assert ready["status"] in ("ok", "degraded")
    names = {c["name"] for c in ready["checks"]}
    assert {"telemetry_source", "database", "sandbox"} <= names

    metrics = client.get("/metrics").text
    assert "causalguard_http_requests_total" in metrics
    assert "causalguard_build_info" in metrics


def test_request_id_header_roundtrip(client):
    r = client.get("/health", headers={"x-request-id": "trace-123"})
    assert r.headers["x-request-id"] == "trace-123"


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
def test_versioned_and_legacy_prefixes(client, prefix):
    assert client.get(f"{prefix}/system/state").status_code == 200
    assert client.get(f"{prefix}/benchmarks").json()["baselines"]
    assert "device_name" in client.get(f"{prefix}/system/amd-metrics").json()


def test_full_closed_loop_flow(client):
    assert client.post("/api/v1/scenarios/pg-lock-contention/start").json()["status"] == "started"

    state = client.get("/api/v1/system/state").json()
    assert state["scenario"] == "pg-lock-contention"
    assert state["active_risks_count"] == 1

    risks = client.get("/api/v1/risks").json()
    assert risks and risks[0]["risk_type"] == "postgresql_lock_contention"

    dossier = client.post("/api/v1/investigations").json()
    assert dossier["risk_type"] == "postgresql_lock_contention"
    assert dossier["causal_graph"]["nodes"]
    did = dossier["incident_id"]

    got = client.get(f"/api/v1/investigations/{did}").json()
    assert got["incident_id"] == did

    graph = client.get("/api/v1/risks/current/causal-graph").json()
    assert graph["nodes"]

    sim = client.post("/api/v1/risks/current/simulate").json()
    assert sim["expected_risk_reduction_pct"] > 0

    verify = client.post("/api/v1/risks/current/verify-intervention").json()
    assert verify["verified"] is True

    md = client.get(f"/api/v1/dossier/{did}/markdown").text
    assert "CausalGuard Incident Prevention Dossier" in md

    page = client.get("/api/v1/investigations?limit=5").json()
    assert page["meta"]["total"] >= 1

    traces = client.get("/api/v1/agents/traces").json()
    assert isinstance(traces, list) and traces

    client.post("/api/v1/scenarios/pg-lock-contention/stop")


def test_unknown_scenario_returns_structured_error(client):
    r = client.post("/api/v1/scenarios/not-a-scenario/start")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert "request_id" in body["error"]


def test_validation_error_shape(client):
    r = client.post("/api/v1/system/amd-benchmark?concurrency=9999")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_auth_gate_when_keys_configured(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SECURITY__API_KEYS", "secret-key")
    from backend.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from backend.api.app import create_app

    with TestClient(create_app()) as c:
        assert c.get("/api/v1/system/state").status_code == 200  # read: open
        assert c.post("/api/v1/investigations").status_code == 401  # mutation: gated
        ok = c.post("/api/v1/investigations", headers={"Authorization": "Bearer secret-key"})
        assert ok.status_code == 200
    get_settings.cache_clear()


def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SECURITY__RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CAUSALGUARD_SECURITY__RATE_LIMIT_PER_MINUTE", "3")
    from backend.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from backend.api.app import create_app

    with TestClient(create_app()) as c:
        codes = [c.get("/api/v1/system/state").status_code for _ in range(6)]
    assert 429 in codes
    get_settings.cache_clear()
