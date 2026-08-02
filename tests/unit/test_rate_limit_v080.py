"""Deterministic sliding-window rate-limit tests for HTTP v1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from src.diting.infra.errors import RateLimitError
from src.diting.schema import OwnerSession
from src.diting.web.rate_limit import SlidingWindowRateLimiter


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def test_exact_limit_is_enforced_and_window_resets() -> None:
    clock = FakeMonotonic()
    limiter = SlidingWindowRateLimiter(clock)

    for _ in range(3):
        limiter.check("analysis", "session-a", limit=3, window_seconds=60, error_code="LIMITED")

    with pytest.raises(RateLimitError) as raised:
        limiter.check("analysis", "session-a", limit=3, window_seconds=60, error_code="LIMITED")
    assert raised.value.error_code == "LIMITED"

    clock.value += 60
    limiter.check("analysis", "session-a", limit=3, window_seconds=60, error_code="LIMITED")


def test_rate_limit_keys_are_isolated() -> None:
    limiter = SlidingWindowRateLimiter(lambda: 1.0)
    limiter.check("scan", "session-a", limit=1, window_seconds=60, error_code="SCAN_LIMITED")
    limiter.check("scan", "session-b", limit=1, window_seconds=60, error_code="SCAN_LIMITED")
    limiter.check("login", "session-a", limit=1, window_seconds=60, error_code="LOGIN_LIMITED")

    with pytest.raises(RateLimitError) as raised:
        limiter.check("scan", "session-a", limit=1, window_seconds=60, error_code="SCAN_LIMITED")
    assert raised.value.error_code == "SCAN_LIMITED"


@pytest.mark.parametrize(
    ("check", "limit", "error_code"),
    (
        ("public", 60, "PUBLIC_READ_RATE_LIMITED"),
        ("login", 5, "LOGIN_RATE_LIMITED"),
        ("analysis", 10, "ANALYSIS_RATE_LIMITED"),
        ("scan", 2, "SCAN_RATE_LIMITED"),
    ),
)
def test_configured_business_limits_have_stable_error_codes(
    check: str,
    limit: int,
    error_code: str,
) -> None:
    limiter = SlidingWindowRateLimiter(lambda: 1.0)
    request = Request({"type": "http", "client": ("203.0.113.10", 1234)})
    now = datetime(2026, 8, 2, tzinfo=UTC)
    session = OwnerSession("session", "csrf", now, now + timedelta(hours=1))
    checks = {
        "public": lambda: limiter.check_public_read(request),
        "login": lambda: limiter.check_login(request),
        "analysis": lambda: limiter.check_analysis(session),
        "scan": lambda: limiter.check_scan(session),
    }

    for _ in range(limit):
        checks[check]()
    with pytest.raises(RateLimitError) as raised:
        checks[check]()
    assert raised.value.error_code == error_code
