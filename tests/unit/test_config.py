from backend.config import CausalGuardSettings, _redact_dsn


def test_nested_env_override(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SERVER__PORT", "9123")
    monkeypatch.setenv("CAUSALGUARD_TELEMETRY__SOURCE_MODE", "prometheus")
    s = CausalGuardSettings()
    assert s.server.port == 9123
    assert s.telemetry.source_mode == "prometheus"


def test_csv_list_parsing(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SERVER__CORS_ORIGINS", "https://a.example, https://b.example")
    s = CausalGuardSettings()
    assert s.server.cors_origins == ["https://a.example", "https://b.example"]


def test_wildcard_cors_disables_credentials(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SERVER__CORS_ORIGINS", "*")
    s = CausalGuardSettings()
    assert s.server.cors_allow_credentials is False


def test_api_keys_csv_and_auth_flag(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_SECURITY__API_KEYS", "k1, k2 ,k3")
    s = CausalGuardSettings()
    assert s.security.api_keys == ["k1", "k2", "k3"]
    assert s.security.auth_enabled is True


def test_redacted_hides_secrets(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_POSTGRES__DSN", "postgresql://user:supersecret@db:5432/prod")
    monkeypatch.setenv("CAUSALGUARD_SECURITY__API_KEYS", "topsecret")
    s = CausalGuardSettings()
    blob = str(s.redacted())
    assert "supersecret" not in blob
    assert "topsecret" not in blob
    assert s.redacted()["security"]["auth_enabled"] is True


def test_redact_dsn_helper():
    assert _redact_dsn("postgresql://u:p@host:5432/db") == "postgresql://***@host:5432/db"
    assert _redact_dsn("sqlite+aiosqlite:///x.db") == "sqlite+aiosqlite:///x.db"


def test_empty_dsn_becomes_none(monkeypatch):
    monkeypatch.setenv("CAUSALGUARD_POSTGRES__DSN", "   ")
    s = CausalGuardSettings()
    assert s.postgres.dsn is None
