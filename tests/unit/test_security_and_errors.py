import pytest

from backend.config import SecurityConfig
from backend.errors import CausalGuardError, NotFoundError, RateLimitedError
from backend.security import SlidingWindowRateLimiter, extract_api_key, security_headers


class _Req:
    def __init__(self, headers):
        self.headers = headers


def test_extract_api_key_bearer_and_header():
    assert extract_api_key(_Req({"authorization": "Bearer abc"})) == "abc"
    assert extract_api_key(_Req({"x-api-key": "xyz"})) == "xyz"
    assert extract_api_key(_Req({})) is None


def test_rate_limiter_allows_then_blocks():
    limiter = SlidingWindowRateLimiter(
        SecurityConfig(rate_limit_per_minute=3, rate_limit_enabled=True)
    )
    for _ in range(3):
        limiter.check("client-a")
    with pytest.raises(RateLimitedError) as ei:
        limiter.check("client-a")
    assert ei.value.status_code == 429
    assert "retry_after_s" in ei.value.details
    # a different client is unaffected
    limiter.check("client-b")


def test_rate_limiter_disabled_is_noop():
    limiter = SlidingWindowRateLimiter(SecurityConfig(rate_limit_enabled=False))
    for _ in range(1000):
        limiter.check("c")


def test_security_headers_hsts_toggle():
    assert "Strict-Transport-Security" not in security_headers(False)
    assert "Strict-Transport-Security" in security_headers(True)


def test_error_payload_shape():
    err = NotFoundError("nope", details={"id": "x"})
    body = err.to_payload("req-1")
    assert body["error"]["code"] == "not_found"
    assert body["error"]["details"] == {"id": "x"}
    assert body["error"]["request_id"] == "req-1"


def test_base_error_defaults():
    err = CausalGuardError()
    assert err.status_code == 500
    assert err.to_payload()["error"]["code"] == "internal_error"
