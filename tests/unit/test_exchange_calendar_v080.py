"""Exchange market phases derived from provider calendar sessions."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.diting.data.calendar_v080 import ExchangeCalendarState
from src.diting.schema import TradingCalendar, TradingCalendarRequest, TradingSession


def _calendar() -> TradingCalendar:
    return TradingCalendar(
        market="XSHG",
        sessions=(
            TradingSession(
                trading_date=date(2026, 10, 9),
                market="XSHG",
                is_open=True,
                open_at=datetime(2026, 10, 9, 9, 30, tzinfo=UTC),
                close_at=datetime(2026, 10, 9, 15, 0, tzinfo=UTC),
            ),
            TradingSession(
                trading_date=date(2026, 10, 12),
                market="XSHG",
                is_open=True,
                open_at=datetime(2026, 10, 12, 9, 30, tzinfo=UTC),
                close_at=datetime(2026, 10, 12, 15, 0, tzinfo=UTC),
            ),
        ),
        timezone="UTC",
    )


def test_unknown_state_does_not_infer_from_civil_weekdays() -> None:
    state = ExchangeCalendarState()
    assert state.market_phase("XSHG", datetime(2026, 10, 9, 10, tzinfo=UTC)) == "unknown"


def test_weekend_and_next_open_come_from_provider_sessions() -> None:
    state = ExchangeCalendarState()
    state.update(_calendar())
    saturday = datetime(2026, 10, 10, 10, tzinfo=UTC)

    assert state.market_phase("XSHG", saturday) == "closed"
    assert state.next_open("XSHG", saturday) == datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def test_post_close_settling_is_a_distinct_phase() -> None:
    state = ExchangeCalendarState(settling_minutes=30)
    state.update(_calendar())

    assert (
        state.market_phase("XSHG", datetime(2026, 10, 9, 15, 15, tzinfo=UTC))
        == "post_close_settling"
    )
    assert state.market_phase("XSHG", datetime(2026, 10, 9, 16, 0, tzinfo=UTC)) == "closed"


def test_calendar_reads_are_range_filtered() -> None:
    state = ExchangeCalendarState()
    state.update(_calendar())
    result = state.get_calendar(
        TradingCalendarRequest("XSHG", date(2026, 10, 12), date(2026, 10, 12))
    )

    assert [item.trading_date for item in result.sessions] == [date(2026, 10, 12)]
