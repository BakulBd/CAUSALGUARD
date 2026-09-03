"""Typed application errors and their HTTP representation."""

from __future__ import annotations

from typing import Any


class CausalGuardError(Exception):
    """Base class for all deliberate application errors.

    Carries an HTTP status, a stable machine-readable ``code`` and optional
    structured ``details`` that are safe to expose to API clients.
    """

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self, request_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.details:
            body["error"]["details"] = self.details
        if request_id:
            body["error"]["request_id"] = request_id
        return body


class NotFoundError(CausalGuardError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ValidationFailure(CausalGuardError):
    status_code = 422
    code = "validation_failed"
    message = "The request failed validation."


class ConflictError(CausalGuardError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class AuthError(CausalGuardError):
    status_code = 401
    code = "unauthorized"
    message = "Missing or invalid credentials."


class RateLimitedError(CausalGuardError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests."


class TelemetrySourceError(CausalGuardError):
    status_code = 503
    code = "telemetry_source_unavailable"
    message = "The configured telemetry source is unavailable."


class SandboxSafetyError(CausalGuardError):
    status_code = 400
    code = "sandbox_safety_violation"
    message = "The requested intervention violates a sandbox safety guard."


class DependencyUnavailableError(CausalGuardError):
    status_code = 503
    code = "dependency_unavailable"
    message = "A required downstream dependency is unavailable."
