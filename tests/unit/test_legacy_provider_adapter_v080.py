"""Legacy provider normalization tests for the v0.8 provider adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from src.diting.data.legacy_adapter_v080 import LegacyProviderAdapter
from src.diting.enums import DataSource
from src.diting.schema import (
    FinancialRequest,
    HistoricalData,
    HistoricalRequest,
    QuoteRequest,
    RealtimeQuote,
)


class FakeLegacyProvider:
    name = "ashare"
    priority = 1

    def health_check(self):
        return True

    def fetch_realtime(self, symbols):
        return {
            symbol: RealtimeQuote(
                symbol=symbol,
                name=symbol,
                price=10,
                change_pct=1,
                open=9,
                high=11,
                low=8,
                volume=100,
                turnover=1000,
                timestamp=datetime(2026, 8, 2, tzinfo=UTC),
            )
            for symbol in symbols
        }

    def fetch_historical(self, symbol, start, end):
        frame = pd.DataFrame(
            [
                {
                    "date": "2026-07-31",
                    "open": 9,
                    "high": 11,
                    "low": 8,
                    "close": 10,
                    "volume": 100,
                    "turnover": 1000,
                }
            ]
        )
        return HistoricalData(symbol, frame, list(frame.columns), start, end)

    def fetch_financials(self, symbol):
        return {"report_date": "2026-06-30", "revenue": 100, "roe": 12}

    def fetch_fund_flow(self, symbol, day):
        raise NotImplementedError


def test_quote_source_is_normalized() -> None:
    adapter = LegacyProviderAdapter(FakeLegacyProvider())
    quote = adapter.get_quotes(QuoteRequest(symbols=("002475",)))[0]

    assert quote.source is DataSource.ASHARE


def test_dataframe_is_normalized_to_immutable_bars() -> None:
    adapter = LegacyProviderAdapter(FakeLegacyProvider())
    result = adapter.get_historical(
        HistoricalRequest("002475", date(2026, 7, 1), date(2026, 7, 31))
    )

    assert result.bars[0].trading_date == date(2026, 7, 31)
    assert result.bars[0].close == 10


def test_financial_dict_is_normalized_to_contract() -> None:
    adapter = LegacyProviderAdapter(FakeLegacyProvider())
    result = adapter.get_financials(FinancialRequest("002475"))

    assert result.report_date == date(2026, 6, 30)
    assert result.revenue == 100
    assert result.roe == 12
    assert result.source is DataSource.ASHARE
