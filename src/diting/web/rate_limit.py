"""Single-process sliding-window business rate limits for HTTP v1."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from threading import RLock

from fastapi import Request

from ..infra.errors import RateLimitError
from ..schema import OwnerSession


class SlidingWindowRateLimiter:
    """Bounded in-memory counters suitable for the v0.8 one-worker deployment."""

    _MAX_IDENTITIES = 10_000

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._lock = RLock()

    def check(
        self,
        bucket: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        error_code: str,
    ) -> None:
        now = self._monotonic()
        cutoff = now - window_seconds
        identity = (bucket, key)
        with self._lock:
            events = self._events.get(identity)
            if events is None:
                self._make_capacity()
                events = deque()
                self._events[identity] = events
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise RateLimitError(error_code=error_code)
            events.append(now)

    def _make_capacity(self) -> None:
        if len(self._events) < self._MAX_IDENTITIES:
            return
        empty = [identity for identity, events in self._events.items() if not events]
        for identity in empty:
            self._events.pop(identity, None)
        if len(self._events) < self._MAX_IDENTITIES:
            return
        oldest = min(self._events, key=lambda identity: self._events[identity][-1])
        self._events.pop(oldest, None)

    def check_public_read(self, request: Request) -> None:
        self.check(
            "public_read",
            _client_ip(request),
            limit=60,
            window_seconds=60,
            error_code="PUBLIC_READ_RATE_LIMITED",
        )

    def check_login(self, request: Request) -> None:
        self.check(
            "login",
            _client_ip(request),
            limit=5,
            window_seconds=15 * 60,
            error_code="LOGIN_RATE_LIMITED",
        )

    def check_analysis(self, session: OwnerSession) -> None:
        self.check(
            "analysis",
            session.session_id,
            limit=10,
            window_seconds=60 * 60,
            error_code="ANALYSIS_RATE_LIMITED",
        )

    def check_scan(self, session: OwnerSession) -> None:
        self.check(
            "scan",
            session.session_id,
            limit=2,
            window_seconds=60 * 60,
            error_code="SCAN_RATE_LIMITED",
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"
