"""
Configuration for CausalGuard.

Environment-driven, 12-factor style. Every setting can be overridden with an
environment variable (prefix ``CAUSALGUARD_``) or an ``.env`` file. Nested
settings use a double-underscore delimiter, e.g.::

    CAUSALGUARD_SERVER__PORT=9000
    CAUSALGUARD_TELEMETRY__SOURCE_MODE=postgres
    CAUSALGUARD_POSTGRES__DSN=postgresql://user:pass@db:5432/production_db

The legacy import surface (``settings.thresholds``, ``settings.rocm``,
``settings.server``, ``settings.telemetry``, ``settings.data_dir``) is preserved
so existing modules keep working unchanged.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# A list[str] populated from an env var as a plain comma-separated string
# (NoDecode stops pydantic-settings from attempting json.loads first).
CsvList = Annotated[list[str], NoDecode]

BASE_DIR = Path(__file__).resolve().parent.parent

Environment = Literal["development", "staging", "production", "test"]
SourceMode = Literal["simulated", "prometheus", "postgres", "auto"]


def _as_str_list(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return value  # let pydantic parse JSON
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_SERVER__", extra="ignore", env_ignore_empty=True
    )

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    root_path: str = ""
    request_timeout_seconds: float = 30.0
    shutdown_grace_seconds: float = 10.0
    cors_origins: CsvList = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]
    cors_allow_credentials: bool = True
    trusted_hosts: CsvList = ["*"]
    gzip_min_size: int = 1024

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        return _as_str_list(value)

    @model_validator(mode="after")
    def _wildcard_disables_credentials(self) -> ServerConfig:
        # `Access-Control-Allow-Origin: *` with credentials is invalid per spec.
        if "*" in self.cors_origins:
            object.__setattr__(self, "cors_allow_credentials", False)
        return self


class TelemetryConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_TELEMETRY__", extra="ignore", env_ignore_empty=True
    )

    source_mode: SourceMode = "simulated"
    # `auto` tries the real sources below and falls back to `simulated` when the
    # backing system is unreachable.
    fallback_to_simulated: bool = True

    prometheus_url: str = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    prometheus_timeout_seconds: float = 5.0
    prometheus_job_postgres: str = "postgres"
    prometheus_job_node: str = "node"
    prometheus_relname: str = "orders"
    prometheus_datname: str = "production_db"
    prometheus_rate_window: str = "5m"
    # Optional PromQL overrides merged over the built-in query set. Keys are
    # snapshot field names, values are PromQL expressions returning a scalar.
    prometheus_queries: dict[str, str] = {}

    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    metrics_window_seconds: int = 900  # 15 minute sliding window
    sample_interval_seconds: int = 5
    stream_interval_seconds: float = 2.0  # websocket push cadence


class DatabaseConfig(BaseSettings):
    """Persistence for CausalGuard's own dossiers / observation history."""

    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_DATABASE__", extra="ignore", env_ignore_empty=True
    )

    url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'causalguard.db'}"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True
    create_all_on_startup: bool = True
    retention_dossiers: int = 500


class PostgresTargetConfig(BaseSettings):
    """The *monitored* PostgreSQL instance (read-only catalog introspection)."""

    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_POSTGRES__", extra="ignore", env_ignore_empty=True
    )

    dsn: str | None = None
    schema_name: str = "public"
    monitored_table: str = "orders"
    connect_timeout_seconds: float = 5.0
    statement_timeout_ms: int = 4000
    pool_min_size: int = 1
    pool_max_size: int = 4

    @field_validator("dsn", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SandboxConfig(BaseSettings):
    """Throwaway PostgreSQL clone used for empirical intervention verification."""

    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_SANDBOX__", extra="ignore", env_ignore_empty=True
    )

    dsn: str | None = None
    mode: Literal["simulated", "real"] = "simulated"
    allow_destructive: bool = False  # VACUUM / REINDEX / pg_terminate_backend
    allow_primary: bool = False  # hard guard: never touch prod unless explicit
    settle_seconds: float = 1.0

    @field_validator("dsn", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SecurityConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_SECURITY__", extra="ignore", env_ignore_empty=True
    )

    api_keys: CsvList = []
    require_auth_for_mutations: bool = False
    rate_limit_per_minute: int = 240
    rate_limit_enabled: bool = True
    security_headers_enabled: bool = True
    hsts_enabled: bool = False  # enable when served over TLS

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        return _as_str_list(value)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)


class EarlyWarningThresholds(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_THRESHOLDS__", extra="ignore", env_ignore_empty=True
    )

    ewma_alpha: float = 0.25
    cusum_threshold: float = 3.5
    dead_tuple_bloat_threshold: float = 0.15  # 15% dead tuples of total
    autovacuum_stale_seconds: int = 600  # 10 minutes without vacuum
    cache_hit_ratio_warning: float = 0.90  # alert if hit ratio drops below 90%
    lock_wait_seconds_threshold: float = 5.0
    forecast_horizon_minutes: int = 40
    replication_lag_warning_seconds: float = 30.0


class ROCmConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_ROCM__", extra="ignore", env_ignore_empty=True
    )

    enabled: bool = True
    device_id: int = 0
    precision: str = "BF16"  # BF16, FP8, FP16, INT8
    use_aiter: bool = False
    batch_concurrency: int = 4
    model_name: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"
    inference_endpoint: str | None = None  # OpenAI-compatible fallback


class ObservabilityConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_OBS__", extra="ignore", env_ignore_empty=True
    )

    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    request_log_enabled: bool = True
    slow_request_ms: float = 1000.0


class CausalGuardSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALGUARD_",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "CausalGuard"
    version: str = "1.1.0"
    environment: Environment = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    data_dir: Path = BASE_DIR / "data"

    server: ServerConfig = Field(default_factory=ServerConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    postgres: PostgresTargetConfig = Field(default_factory=PostgresTargetConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    thresholds: EarlyWarningThresholds = Field(default_factory=EarlyWarningThresholds)
    rocm: ROCmConfig = Field(default_factory=ROCmConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @model_validator(mode="after")
    def _ensure_data_dir(self) -> CausalGuardSettings:
        # A wide-open trusted_hosts / CORS in production is surfaced through the
        # readiness report rather than failing hard, so a first deploy still boots.
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def redacted(self) -> dict[str, object]:
        """Config snapshot safe for logs / the /api/v1/system/config endpoint."""

        def _hide(value: str | None) -> str | None:
            if not value:
                return value
            return "***redacted***"

        return {
            "app_name": self.app_name,
            "version": self.version,
            "environment": self.environment,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "workers": self.server.workers,
                "cors_origins": self.server.cors_origins,
            },
            "telemetry": {
                "source_mode": self.telemetry.source_mode,
                "prometheus_url": self.telemetry.prometheus_url,
                "fallback_to_simulated": self.telemetry.fallback_to_simulated,
            },
            "database": {"url": _redact_dsn(self.database.url)},
            "postgres": {
                "dsn": _hide(self.postgres.dsn),
                "monitored_table": self.postgres.monitored_table,
            },
            "sandbox": {
                "mode": self.sandbox.mode,
                "dsn": _hide(self.sandbox.dsn),
                "allow_destructive": self.sandbox.allow_destructive,
                "allow_primary": self.sandbox.allow_primary,
            },
            "security": {
                "auth_enabled": self.security.auth_enabled,
                "require_auth_for_mutations": self.security.require_auth_for_mutations,
                "rate_limit_per_minute": self.security.rate_limit_per_minute,
            },
            "rocm": {
                "enabled": self.rocm.enabled,
                "precision": self.rocm.precision,
                "use_aiter": self.rocm.use_aiter,
            },
        }


def _redact_dsn(dsn: str) -> str:
    """Strip credentials from a DSN for safe display."""
    if "@" not in dsn:
        return dsn
    scheme, _, rest = dsn.partition("://")
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    return f"{scheme}://***@{rest}"


@lru_cache(maxsize=1)
def get_settings() -> CausalGuardSettings:
    return CausalGuardSettings()


# Backwards-compatible module-level singleton.
settings = get_settings()

__all__ = [
    "BASE_DIR",
    "CausalGuardSettings",
    "_redact_dsn",
    "get_settings",
    "settings",
]
