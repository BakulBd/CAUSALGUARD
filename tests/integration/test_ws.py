import json

import pytest

pytestmark = pytest.mark.integration


def test_ws_telemetry_stream_tick(client):
    client.post("/api/v1/scenarios/pg-table-bloat/start")
    with client.websocket_connect("/api/v1/ws/telemetry") as ws:
        first = ws.receive_json()
        assert first["type"] == "tick"
        assert first["scenario"] == "pg-table-bloat"
        assert "state" in first and "p99_latency_ms" in first["state"]
        assert first["telemetry_source"]["mode"] == "simulated"

        ws.send_text("refresh")
        forced = ws.receive_json()
        assert forced["type"] == "tick"
    client.post("/api/v1/scenarios/pg-table-bloat/stop")


def test_ws_legacy_prefix(client):
    with client.websocket_connect("/api/ws/telemetry") as ws:
        payload = json.loads(ws.receive_text())
        assert payload["type"] == "tick"
