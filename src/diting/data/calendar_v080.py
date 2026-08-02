"""Thread-safe exchange-calendar state derived only from provider sessions."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from ..schema import TradingCalendar, TradingCalendarRequest


class ExchangeCalendarState:
    """Keep provider-supplied sessions for TTL and market-phase decisions."""

    def __init__(self, settling_minutes: int = 30) -> None:
        self._settling = timedelta(minutes=settling_minutes)
        self._calendars: dict[str, TradingCalendar] = {}
        self._lock = threading.RLock()

    def update(self, calendar: TradingCalendar) -> None:
        with self._lock:
            self._calendars[calendar.market] = calendar

    def get_calendar(self, request: TradingCalendarRequest) -> TradingCalendar:
        with self._lock:
            calendar = self._calendars.get(request.market)
        if calendar is None:
            return TradingCalendar(market=request.market, sessions=())
        sessions = tuple(
            item
            for item in calendar.sessions
            if request.start_date <= item.trading_date <= request.end_date
        )
        return TradingCalendar(
            market=calendar.market,
            sessions=sessions,
            timezone=calendar.timezone,
        )

    def market_phase(self, market: str, at: datetime) -> str:
        with self._lock:
            calendar = self._calendars.get(market)
        if calendar is None:
            return "unknown"
        matching = next(
            (session for session in calendar.sessions if session.trading_date == at.date()),
            None,
        )
        if matching is None or not matching.is_open:
            return "closed"
        if matching.open_at is None or matching.close_at is None:
            return "unknown"
        comparable = _compatible_datetime(at, matching.open_at)
        if matching.open_at <= comparable <= matching.close_at:
            return "trading"
        if matching.close_at < comparable <= matching.close_at + self._settling:
            return "post_close_settling"
        return "closed"

    def next_open(self, market: str, at: datetime) -> datetime | None:
        with self._lock:
            calendar = self._calendars.get(market)
        if calendar is None:
            return None
        opens = [
            session.open_at
            for session in calendar.sessions
            if session.is_open
            and session.open_at is not None
            and session.open_at > _compatible_datetime(at, session.open_at)
        ]
        return min(opens) if opens else None


def _compatible_datetime(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value.astimezone(reference.tzinfo) if reference.tzinfo is not None else value
