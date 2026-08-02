"""DataSnapshotBuilder contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from src.diting.application.snapshot import DataSnapshotBuilder
from src.diting.enums import AnalysisProfile, FetchMode, TraceOutcome
from src.diting.schema import (
    AnalysisRequest,
    DataResult,
    Financials,
    FundFlow,
    HistoricalBar,
    HistoricalSeries,
    ProviderTrace,
    RealtimeQuote,
)

NOW = datetime(2026, 8, 2, 10, 30, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return 1.0


class FakeGateway:
    def __init__(self) -> None:
        trace = ProviderTrace(
            provider="fake",
            operation="read",
            outcome=TraceOutcome.SUCCESS,
            started_at=NOW,
            finished_at=NOW,
        )
        self.quote = DataResult(
            data=RealtimeQuote(
                symbol="002475",
                name="立讯精密",
                price=42,
                change_pct=1,
                open=41,
                high=43,
                low=40,
                volume=100,
                turnover=4200,
                timestamp=NOW,
            ),
            data_time=NOW,
            provider_traces=(trace,),
            request_hash="quote-request",
        )
        self.historical = DataResult(
            data=HistoricalSeries(
                symbol="002475",
                bars=(HistoricalBar(date(2026, 8, 1), 40, 43, 39, 42, 100),),
            ),
            data_time=NOW,
            provider_traces=(trace,),
            request_hash="history-request",
        )
        self.financials = DataResult(
            data=Financials(
                symbol="002475",
                report_date=date(2026, 6, 30),
                revenue=1,
                revenue_yoy=2,
                net_profit=3,
                profit_yoy=4,
                gross_margin=5,
                net_margin=6,
                roe=7,
                debt_ratio=8,
                current_ratio=9,
                quick_ratio=10,
            ),
            data_time=NOW,
            request_hash="financial-request",
        )
        self.fund_flow = DataResult(
            data=FundFlow("002475", NOW.date(), 1, 2, 3, 4, 5, 0.1, 0.2, 0.3),
            data_time=NOW,
            request_hash="fund-flow-request",
        )
        self.requests = []

    def get_quotes(self, request):
        self.requests.append(request)
        return {"002475": self.quote}

    def get_historical(self, request):
        self.requests.append(request)
        return self.historical

    def get_financials(self, request):
        self.requests.append(request)
        return self.financials

    def get_fund_flow(self, request):
        self.requests.append(request)
        return self.fund_flow


def test_builder_uses_one_fresh_required_snapshot_and_aggregates_trace() -> None:
    gateway = FakeGateway()
    deadline = datetime(2026, 8, 2, 10, 31, tzinfo=UTC)
    snapshot = DataSnapshotBuilder(gateway, FakeClock()).build(
        AnalysisRequest(
            symbol="sz.002475",
            profile=AnalysisProfile.STANDARD,
            as_of=NOW,
            force_refresh=True,
            deadline=deadline,
        )
    )

    assert snapshot.symbol == "002475"
    assert snapshot.completeness == 1.0
    assert len(snapshot.provider_traces) == 2
    assert snapshot.snapshot_id == f"snap_{snapshot.snapshot_hash[:24]}"
    assert all(request.mode is FetchMode.FRESH_REQUIRED for request in gateway.requests)
    assert all(request.force_refresh is True for request in gateway.requests)
    assert all(request.deadline == deadline for request in gateway.requests)


def test_snapshot_hash_is_stable_across_cache_and_trace_noise() -> None:
    gateway = FakeGateway()
    builder = DataSnapshotBuilder(gateway, FakeClock())
    request = AnalysisRequest(symbol="002475", as_of=NOW)
    first = builder.build(request)

    gateway.quote = replace(gateway.quote, provider_traces=(), warnings=())
    second = builder.build(request)

    assert first.snapshot_hash == second.snapshot_hash


def test_missing_data_is_not_replaced_with_zero() -> None:
    gateway = FakeGateway()
    gateway.financials = DataResult(
        data=None,
        data_time=None,
        error_code="UPSTREAM_UNAVAILABLE",
    )

    snapshot = DataSnapshotBuilder(gateway, FakeClock()).build(
        AnalysisRequest(symbol="002475", as_of=NOW)
    )

    assert snapshot.financials is not None
    assert snapshot.financials.data is None
    assert snapshot.completeness == 0.75


@pytest.mark.parametrize("symbol", ["", "2475", "not-a-stock", "0024750"])
def test_invalid_symbol_is_rejected(symbol: str) -> None:
    with pytest.raises(ValueError, match="six-digit"):
        DataSnapshotBuilder(FakeGateway(), FakeClock()).build(AnalysisRequest(symbol=symbol))
