"""CLI adapter and Web service preserve identical gateway DataResult semantics."""

from __future__ import annotations

from datetime import UTC, datetime

from src.diting.adapters.gateway_legacy_view import GatewayLegacyView
from src.diting.enums import CacheState, CacheTier, FetchMode, TraceOutcome
from src.diting.schema import (
    CacheInfo,
    DataResult,
    DataWarning,
    ProviderTrace,
    RealtimeQuote,
)
from src.diting.web.services.stock import StockService


class RecordingGateway:
    def __init__(self) -> None:
        now = datetime(2026, 8, 2, tzinfo=UTC)
        self.result = DataResult(
            data=RealtimeQuote(
                symbol="002475",
                name="立讯精密",
                price=51.2,
                change_pct=1.2,
                open=50,
                high=52,
                low=49.8,
                volume=100,
                turnover=1000,
                timestamp=now,
            ),
            data_time=now,
            cache_info=CacheInfo(state=CacheState.STALE, tier=CacheTier.L2),
            provider_traces=(
                ProviderTrace(
                    provider="ashare",
                    operation="quotes",
                    outcome=TraceOutcome.FAILURE,
                    started_at=now,
                    finished_at=now,
                    error_code="TIMEOUT",
                ),
            ),
            warnings=(DataWarning("STALE_IF_ERROR", "upstream unavailable"),),
            request_hash="same-request",
        )
        self.requests = []

    def get_quotes(self, request):
        self.requests.append(request)
        return {request.symbols[0]: self.result}


def test_cli_and_web_keep_the_same_data_result() -> None:
    gateway = RecordingGateway()
    cli_view = GatewayLegacyView(gateway)
    web_service = StockService(data_gateway=gateway)

    cli_result = cli_view.get_realtime_results(["002475"])["002475"]
    web_result = web_service.get_realtime_result("002475")

    assert cli_result is gateway.result
    assert web_result is gateway.result
    assert [request.mode for request in gateway.requests] == [
        FetchMode.CACHE_PREFERRED,
        FetchMode.CACHE_PREFERRED,
    ]
    assert cli_result.cache_info == web_result.cache_info
    assert cli_result.provider_traces == web_result.provider_traces
    assert cli_result.warnings == web_result.warnings
