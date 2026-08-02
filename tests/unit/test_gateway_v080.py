"""CachedMarketDataGateway behavior tests with deterministic fake providers."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

from src.diting.cache.store_v080 import MemoryCacheStore
from src.diting.data.gateway_v080 import CachedMarketDataGateway, CachePolicy
from src.diting.enums import CacheState, CacheTier, FetchMode, TraceOutcome
from src.diting.infra.errors import ProviderNotFoundError, ProviderTransientError
from src.diting.schema import (
    FinancialRequest,
    Financials,
    FundFlow,
    FundFlowRequest,
    HistoricalBar,
    HistoricalRequest,
    HistoricalSeries,
    Instrument,
    InstrumentPage,
    InstrumentSearchRequest,
    QuoteRequest,
    RealtimeQuote,
    TradingCalendar,
    TradingCalendarRequest,
    TradingSession,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def today(self):
        return self.value.date()

    def monotonic(self) -> float:
        return self.value.timestamp()


class FakeCalendar:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.phase = "trading"
        self.open_at = clock.now() + timedelta(days=2)

    def market_phase(self, market, at):
        return self.phase

    def next_open(self, market, at):
        return self.open_at

    def get_calendar(self, request):
        raise NotImplementedError


class FakeProvider:
    def __init__(self, clock: MutableClock, name: str = "fake") -> None:
        self.clock = clock
        self.name = name
        self.max_batch_size = 100
        self.quote_calls: list[tuple[str, ...]] = []
        self.history_calls = 0
        self.financial_calls = 0
        self.fund_flow_calls = 0
        self.catalog_calls = 0
        self.calendar_calls = 0
        self.failures_remaining = 0
        self.not_found = False
        self.delay = 0.0
        self._lock = threading.Lock()

    def get_quotes(self, request):
        with self._lock:
            self.quote_calls.append(request.symbols)
        if self.delay:
            time.sleep(self.delay)
        if self.not_found:
            raise ProviderNotFoundError()
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise ProviderTransientError("temporary")
        return tuple(
            RealtimeQuote(
                symbol=symbol,
                name=symbol,
                price=10.0,
                change_pct=1.0,
                open=9.8,
                high=10.2,
                low=9.7,
                volume=100,
                turnover=1000,
                timestamp=self.clock.now(),
            )
            for symbol in request.symbols
        )

    def get_historical(self, request):
        self.history_calls += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise ProviderTransientError("temporary")
        return HistoricalSeries(
            symbol=request.symbol,
            bars=(
                HistoricalBar(
                    trading_date=request.end_date,
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=1000,
                ),
            ),
            period=request.period,
            adjustment=request.adjustment,
        )

    def get_financials(self, request):
        self.financial_calls += 1
        return Financials(
            symbol=request.symbol,
            report_date=request.as_of or date(2026, 6, 30),
            revenue=100,
            revenue_yoy=5,
            net_profit=10,
            profit_yoy=4,
            gross_margin=30,
            net_margin=10,
            roe=12,
            debt_ratio=20,
            current_ratio=2,
            quick_ratio=1.5,
        )

    def get_fund_flow(self, request):
        self.fund_flow_calls += 1
        return FundFlow(
            symbol=request.symbol,
            date=request.trading_date or date(2026, 7, 31),
            main_net_inflow=1,
            super_large_net=2,
            large_net=3,
            medium_net=-1,
            small_net=-2,
            ddx=0.1,
            ddy=0.2,
            ddz=0.3,
        )

    def search_instruments(self, request):
        self.catalog_calls += 1
        return InstrumentPage(
            items=(Instrument("002475", "立讯精密", "XSHE", "stock"),),
            total=1,
        )

    def get_trading_calendar(self, request):
        self.calendar_calls += 1
        return TradingCalendar(
            market=request.market,
            sessions=(
                TradingSession(
                    trading_date=request.start_date,
                    market=request.market,
                    is_open=True,
                    open_at=self.clock.now(),
                    close_at=self.clock.now() + timedelta(hours=5),
                ),
            ),
        )


def _gateway(clock, provider, **kwargs):
    return CachedMarketDataGateway(
        (provider,),
        MemoryCacheStore(clock, max_size=100),
        clock,
        background_refresh=False,
        sleeper=lambda _: None,
        jitter=lambda: 0,
        **kwargs,
    )


def test_quote_cache_modes_and_force_refresh() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(clock, provider)
    request = QuoteRequest(symbols=("002475",))

    first = gateway.get_quotes(request)["002475"]
    second = gateway.get_quotes(request)["002475"]
    forced = gateway.get_quotes(replace_quote(request, force_refresh=True))["002475"]

    assert first.cache_info.tier is CacheTier.UPSTREAM
    assert second.cache_info.tier is CacheTier.L1
    assert forced.cache_info.tier is CacheTier.UPSTREAM
    assert len(provider.quote_calls) == 2


def test_cache_only_never_calls_provider() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(clock, provider)
    result = gateway.get_quotes(QuoteRequest(symbols=("600519",), mode=FetchMode.CACHE_ONLY))[
        "600519"
    ]

    assert result.error_code == "CACHE_MISS"
    assert provider.quote_calls == []


def test_expired_deadline_never_calls_provider() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(clock, provider)
    request = QuoteRequest(
        symbols=("600519",),
        deadline=clock.now() - timedelta(microseconds=1),
    )

    result = gateway.get_quotes(request)["600519"]

    assert result.error_code == "DEADLINE_EXCEEDED"
    assert provider.quote_calls == []


def test_same_key_concurrency_calls_upstream_once() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    provider.delay = 0.05
    gateway = _gateway(clock, provider)
    request = QuoteRequest(symbols=("002475",))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: gateway.get_quotes(request), range(8)))

    assert len(provider.quote_calls) == 1
    assert all(item["002475"].succeeded for item in results)


def test_retries_transient_error_twice_then_succeeds() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    provider.failures_remaining = 2
    gateway = _gateway(clock, provider, retry_count=2)

    result = gateway.get_quotes(QuoteRequest(symbols=("002475",)))["002475"]

    assert result.succeeded is True
    assert len(provider.quote_calls) == 3
    assert [trace.outcome for trace in result.provider_traces] == [
        TraceOutcome.FAILURE,
        TraceOutcome.FAILURE,
        TraceOutcome.SUCCESS,
    ]


def test_provider_fallback_records_trace() -> None:
    clock = MutableClock()
    first = FakeProvider(clock, "first")
    first.failures_remaining = 1
    second = FakeProvider(clock, "second")
    gateway = CachedMarketDataGateway(
        (first, second),
        MemoryCacheStore(clock),
        clock,
        retry_count=0,
        background_refresh=False,
    )

    result = gateway.get_quotes(QuoteRequest(symbols=("002475",)))["002475"]

    assert result.succeeded is True
    assert [trace.provider for trace in result.provider_traces] == ["first", "second"]


def test_stale_if_error_returns_data_with_warning() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(
        clock,
        provider,
        retry_count=0,
        policies={"quote": CachePolicy(1, 100)},
    )
    request = QuoteRequest(symbols=("002475",))
    gateway.get_quotes(request)
    clock.value += timedelta(seconds=2)
    provider.failures_remaining = 1

    result = gateway.get_quotes(replace_quote(request, mode=FetchMode.FRESH_REQUIRED))["002475"]

    assert result.data is not None
    assert result.cache_info.state is CacheState.STALE
    assert {warning.code for warning in result.warnings} == {"STALE_CACHE", "STALE_IF_ERROR"}


def test_not_found_is_negative_cached_for_five_minutes() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    provider.not_found = True
    gateway = _gateway(clock, provider, retry_count=0)
    request = QuoteRequest(symbols=("999998",))

    first = gateway.get_quotes(request)["999998"]
    second = gateway.get_quotes(request)["999998"]

    assert first.error_code == "NOT_FOUND"
    assert second.error_code == "NOT_FOUND"
    assert len(provider.quote_calls) == 1


def test_circuit_opens_after_three_provider_failures() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    provider.failures_remaining = 10
    gateway = _gateway(clock, provider, retry_count=0)
    outcomes = []
    for symbol in ("000001", "000002", "000003", "000004"):
        result = gateway.get_quotes(QuoteRequest(symbols=(symbol,), force_refresh=True))[symbol]
        outcomes.extend(trace.outcome for trace in result.provider_traces)

    assert len(provider.quote_calls) == 3
    assert TraceOutcome.CIRCUIT_OPEN in outcomes


def test_circuit_state_is_reused_by_a_new_gateway() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    provider.failures_remaining = 10
    cache = MemoryCacheStore(clock)
    first = CachedMarketDataGateway(
        (provider,), cache, clock, retry_count=0, background_refresh=False
    )
    for symbol in ("000001", "000002", "000003"):
        first.get_quotes(QuoteRequest(symbols=(symbol,), force_refresh=True))

    restarted = CachedMarketDataGateway(
        (provider,), cache, clock, retry_count=0, background_refresh=False
    )
    result = restarted.get_quotes(QuoteRequest(symbols=("000004",), force_refresh=True))["000004"]

    assert len(provider.quote_calls) == 3
    assert result.provider_traces[-1].outcome is TraceOutcome.CIRCUIT_OPEN


def test_mx_data_batches_at_most_four_symbols() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock, "mx_data")
    provider.max_batch_size = 4
    gateway = _gateway(clock, provider)
    symbols = tuple(f"00000{index}" for index in range(1, 10))

    results = gateway.get_quotes(QuoteRequest(symbols=symbols))

    assert len(results) == 9
    assert [len(batch) for batch in provider.quote_calls] == [4, 4, 1]


def test_historical_payload_round_trips_through_cache() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(clock, provider)
    request = HistoricalRequest(
        symbol="002475",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 31),
    )

    first = gateway.get_historical(request)
    second = gateway.get_historical(request)

    assert first.data == second.data
    assert second.cache_info.tier is CacheTier.L1
    assert provider.history_calls == 1


def test_financials_and_fund_flow_share_cache_semantics() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(clock, provider)
    financial_request = FinancialRequest("002475", as_of=date(2026, 6, 30))
    flow_request = FundFlowRequest("002475", trading_date=date(2026, 7, 31))

    assert gateway.get_financials(financial_request).data is not None
    assert gateway.get_financials(financial_request).cache_info.tier is CacheTier.L1
    assert gateway.get_fund_flow(flow_request).data is not None
    assert gateway.get_fund_flow(flow_request).cache_info.tier is CacheTier.L1
    assert provider.financial_calls == 1
    assert provider.fund_flow_calls == 1


def test_catalog_and_calendar_are_cached_through_the_gateway() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    gateway = _gateway(clock, provider)
    catalog_request = InstrumentSearchRequest(query="立讯")
    calendar_request = TradingCalendarRequest(
        market="XSHG",
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 7),
    )

    assert gateway.search_instruments(catalog_request).data is not None
    assert gateway.search_instruments(catalog_request).cache_info.tier is CacheTier.L1
    assert gateway.get_trading_calendar(calendar_request).data is not None
    assert gateway.get_trading_calendar(calendar_request).cache_info.tier is CacheTier.L1
    assert provider.catalog_calls == 1
    assert provider.calendar_calls == 1


def test_post_close_settling_forces_one_final_refresh() -> None:
    clock = MutableClock()
    provider = FakeProvider(clock)
    calendar = FakeCalendar(clock)
    gateway = CachedMarketDataGateway(
        (provider,),
        MemoryCacheStore(clock),
        clock,
        calendar=calendar,
        background_refresh=False,
    )
    request = QuoteRequest(symbols=("002475",))
    gateway.get_quotes(request)
    calendar.phase = "post_close_settling"

    gateway.get_quotes(replace_quote(request, mode=FetchMode.FRESH_REQUIRED))
    gateway.get_quotes(request)

    assert len(provider.quote_calls) == 2


def replace_quote(request: QuoteRequest, **changes) -> QuoteRequest:
    values = {
        "symbols": request.symbols,
        "mode": request.mode,
        "force_refresh": request.force_refresh,
        "deadline": request.deadline,
    }
    values.update(changes)
    return QuoteRequest(**values)
