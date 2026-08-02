"""Internal view of the v0.8 gateway for legacy analysis/presentation consumers."""

from __future__ import annotations

import threading
from datetime import date

import pandas as pd

from ..enums import DataSource, FetchMode
from ..infra.errors import AllProvidersFailedError
from ..ports import DataGateway
from ..schema import (
    FundFlowRequest,
    HistoricalData,
    HistoricalRequest,
    QuoteRequest,
)


class GatewayLegacyView:
    """Convert typed gateway data only at the old interface boundary.

    This is not a public compatibility API. It exists until the Phase 2/3 consumers accept
    ``DataResult`` and ``HistoricalSeries`` directly.
    """

    def __init__(self, gateway: DataGateway) -> None:
        self._gateway = gateway
        self._seen_providers: set[str] = set()
        self._lock = threading.RLock()

    @property
    def available_providers(self) -> list[str]:
        with self._lock:
            return sorted(self._seen_providers)

    def get_realtime(self, symbols: list[str], *, force_refresh: bool = False):
        results = self.get_realtime_results(symbols, force_refresh=force_refresh)
        quotes = {
            symbol: result.data for symbol, result in results.items() if result.data is not None
        }
        if symbols and not quotes:
            errors = sorted({result.error_code or "UNKNOWN" for result in results.values()})
            raise AllProvidersFailedError(
                f"Gateway returned no quote for {symbols}: {', '.join(errors)}"
            )
        return quotes

    def get_realtime_results(
        self,
        symbols: list[str],
        *,
        force_refresh: bool = False,
    ):
        """Return the unchanged DataResult mapping for parity-sensitive consumers."""

        results = self._gateway.get_quotes(
            QuoteRequest(
                symbols=tuple(symbols),
                mode=(FetchMode.FRESH_REQUIRED if force_refresh else FetchMode.CACHE_PREFERRED),
                force_refresh=force_refresh,
            )
        )
        self._remember(results.values())
        return results

    def get_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        result = self._gateway.get_historical(
            HistoricalRequest(
                symbol=symbol,
                start_date=start,
                end_date=end,
            )
        )
        self._remember((result,))
        if result.data is None:
            raise AllProvidersFailedError(
                f"Gateway returned no history for {symbol}: {result.error_code}"
            )
        frame = pd.DataFrame(
            {
                "date": [item.trading_date for item in result.data.bars],
                "open": [item.open for item in result.data.bars],
                "high": [item.high for item in result.data.bars],
                "low": [item.low for item in result.data.bars],
                "close": [item.close for item in result.data.bars],
                "volume": [item.volume for item in result.data.bars],
                "turnover": [item.turnover for item in result.data.bars],
            }
        )
        return HistoricalData(
            symbol=symbol,
            df=frame,
            columns=list(frame.columns),
            start_date=start,
            end_date=end,
            source=DataSource.CACHE,
        )

    def get_fund_flow(self, symbol: str, day: date | None = None):
        result = self._gateway.get_fund_flow(FundFlowRequest(symbol=symbol, trading_date=day))
        self._remember((result,))
        if result.data is None:
            raise AllProvidersFailedError(
                f"Gateway returned no fund flow for {symbol}: {result.error_code}"
            )
        return result.data

    def _remember(self, results) -> None:
        with self._lock:
            for result in results:
                self._seen_providers.update(
                    trace.provider for trace in result.provider_traces if trace.provider
                )
