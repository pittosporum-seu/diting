"""Adapters that normalize legacy provider payloads behind the v0.8 provider port."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from ..enums import DataSource
from ..infra.errors import DataUnavailableError, ProviderTransientError
from ..schema import (
    FinancialRequest,
    Financials,
    FundFlow,
    FundFlowRequest,
    HistoricalBar,
    HistoricalRequest,
    HistoricalSeries,
    InstrumentPage,
    InstrumentSearchRequest,
    QuoteRequest,
    RealtimeQuote,
    TradingCalendar,
    TradingCalendarRequest,
)
from .providers.base import DataProvider

_COLUMN_ALIASES = {
    "date": ("date", "日期", "交易日期", "时间"),
    "open": ("open", "开盘", "开盘价", "今开"),
    "high": ("high", "最高", "最高价"),
    "low": ("low", "最低", "最低价"),
    "close": ("close", "收盘", "收盘价", "最新价"),
    "volume": ("volume", "成交量"),
    "turnover": ("turnover", "amount", "成交额"),
}


class LegacyProviderAdapter:
    """Expose one existing ``DataProvider`` as a typed, cache-free v0.8 provider."""

    def __init__(self, provider: DataProvider, *, max_batch_size: int = 100) -> None:
        self._provider = provider
        if provider.name == "mx_data":
            self.max_batch_size = min(4, max_batch_size)
        else:
            self.max_batch_size = max_batch_size

    @property
    def name(self) -> str:
        return self._provider.name

    def get_quotes(self, request: QuoteRequest) -> tuple[RealtimeQuote, ...]:
        try:
            quotes = self._provider.fetch_realtime(list(request.symbols))
        except DataUnavailableError as exc:
            raise ProviderTransientError(str(exc), detail=exc.detail) from exc
        source = _provider_source(self.name)
        return tuple(
            replace(quote, source=source)
            for symbol in request.symbols
            if (quote := quotes.get(symbol)) is not None
        )

    def get_historical(self, request: HistoricalRequest) -> HistoricalSeries:
        if request.period != "1d":
            raise NotImplementedError(f"{self.name} only exposes daily history")
        try:
            payload = self._provider.fetch_historical(
                request.symbol,
                request.start_date,
                request.end_date,
            )
        except DataUnavailableError as exc:
            raise ProviderTransientError(str(exc), detail=exc.detail) from exc
        bars = tuple(_historical_bars(payload.df))
        if not bars:
            raise ProviderTransientError(f"{self.name} returned no normalized bars")
        return HistoricalSeries(
            symbol=request.symbol,
            bars=bars,
            period=request.period,
            adjustment=request.adjustment,
        )

    def get_financials(self, request: FinancialRequest) -> Financials:
        try:
            payload = self._provider.fetch_financials(request.symbol)
        except DataUnavailableError as exc:
            raise ProviderTransientError(str(exc), detail=exc.detail) from exc
        if isinstance(payload, Financials):
            return replace(payload, source=_provider_source(self.name))
        if not isinstance(payload, dict):
            raise ProviderTransientError(f"{self.name} returned invalid financials")
        return _financials(request, payload, _provider_source(self.name))

    def get_fund_flow(self, request: FundFlowRequest) -> FundFlow:
        day = request.trading_date or date.today()
        try:
            return self._provider.fetch_fund_flow(request.symbol, day)
        except DataUnavailableError as exc:
            raise ProviderTransientError(str(exc), detail=exc.detail) from exc

    def search_instruments(self, request: InstrumentSearchRequest) -> InstrumentPage:
        try:
            return self._provider.fetch_instruments(
                request.query,
                request.market,
                request.limit,
                request.cursor,
            )
        except DataUnavailableError as exc:
            raise ProviderTransientError(str(exc), detail=exc.detail) from exc

    def get_trading_calendar(self, request: TradingCalendarRequest) -> TradingCalendar:
        try:
            return self._provider.fetch_trading_calendar(
                request.market,
                request.start_date,
                request.end_date,
            )
        except DataUnavailableError as exc:
            raise ProviderTransientError(str(exc), detail=exc.detail) from exc


def _provider_source(name: str) -> DataSource:
    aliases = {
        "mx_data": DataSource.MX_DATA,
        "akshare": DataSource.AKSHARE,
        "ashare": DataSource.ASHARE,
        "east_money": DataSource.EAST_MONEY,
    }
    return aliases.get(name, DataSource.UNKNOWN)


def _historical_bars(frame: Any) -> list[HistoricalBar]:
    if frame is None or not hasattr(frame, "iterrows"):
        return []
    columns = {str(column): column for column in frame.columns}
    resolved = {
        name: next((columns[item] for item in aliases if item in columns), None)
        for name, aliases in _COLUMN_ALIASES.items()
    }
    required = {"date", "open", "high", "low", "close", "volume"}
    if any(resolved[name] is None for name in required):
        return []
    bars: list[HistoricalBar] = []
    for _, row in frame.iterrows():
        try:
            trading_date = _date(row[resolved["date"]])
            bars.append(
                HistoricalBar(
                    trading_date=trading_date,
                    open=_number(row[resolved["open"]]),
                    high=_number(row[resolved["high"]]),
                    low=_number(row[resolved["low"]]),
                    close=_number(row[resolved["close"]]),
                    volume=_number(row[resolved["volume"]]),
                    turnover=(
                        _number(row[resolved["turnover"]])
                        if resolved["turnover"] is not None
                        else None
                    ),
                )
            )
        except (TypeError, ValueError, KeyError):
            continue
    return sorted(bars, key=lambda item: item.trading_date)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _number(value: Any) -> float:
    cleaned = str(value).replace(",", "").replace("元", "").strip()
    number = float(cleaned)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _financials(
    request: FinancialRequest,
    raw: dict[str, Any],
    source: DataSource,
) -> Financials:
    def number(key: str, default: float = 0.0) -> float:
        return _number(raw.get(key, default))

    report_date = _date(raw.get("report_date") or request.as_of or date.today())
    return Financials(
        symbol=request.symbol,
        report_date=report_date,
        revenue=number("revenue"),
        revenue_yoy=number("revenue_yoy"),
        net_profit=number("net_profit"),
        profit_yoy=number("profit_yoy"),
        gross_margin=number("gross_margin"),
        net_margin=number("net_margin"),
        roe=number("roe"),
        debt_ratio=number("debt_ratio"),
        current_ratio=number("current_ratio"),
        quick_ratio=number("quick_ratio"),
        fcf=number("fcf") if raw.get("fcf") is not None else None,
        op_cash_flow=(number("op_cash_flow") if raw.get("op_cash_flow") is not None else None),
        source=source,
    )
