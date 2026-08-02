"""v0.8 immutable domain-contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from src.diting.enums import (
    AnalysisProfile,
    CacheState,
    CacheTier,
    EngineRunStatus,
    FetchMode,
    RunStatus,
    StrategyState,
    TraceOutcome,
)
from src.diting.schema import (
    AnalysisRequest,
    AnalysisRun,
    CacheInfo,
    DataResult,
    EngineRun,
    HistoricalBar,
    HistoricalRequest,
    HistoricalSeries,
    ProviderTrace,
    QuoteRequest,
    RealtimeQuote,
    StrategyVersion,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def test_data_result_carries_trace_cache_and_request_identity() -> None:
    quote = RealtimeQuote(
        symbol="002475",
        name="立讯精密",
        price=42.0,
        change_pct=1.5,
        open=41.0,
        high=42.5,
        low=40.8,
        volume=100,
        turnover=4200.0,
        timestamp=NOW,
    )
    trace = ProviderTrace(
        provider="fake",
        operation="quotes",
        outcome=TraceOutcome.SUCCESS,
        started_at=NOW,
        finished_at=NOW,
    )
    result = DataResult(
        data=quote,
        data_time=NOW,
        cache_info=CacheInfo(
            state=CacheState.FRESH,
            tier=CacheTier.L1,
            cache_key="quote:002475",
        ),
        provider_traces=(trace,),
        request_hash="sha256:request",
    )

    assert result.succeeded is True
    assert result.cache_info.hit is True
    assert result.provider_traces == (trace,)
    assert result.request_hash == "sha256:request"
    with pytest.raises(FrozenInstanceError):
        result.request_hash = "changed"


def test_failure_is_not_a_neutral_score() -> None:
    failed = EngineRun(
        engine_name="wyckoff",
        engine_version="2.0.0",
        status=EngineRunStatus.FAILED,
        deterministic=False,
        started_at=NOW,
        finished_at=NOW,
        error_code="INVALID_STRUCTURED_OUTPUT",
    )
    run = AnalysisRun(
        run_id="run-1",
        request=AnalysisRequest(symbol="002475", profile=AnalysisProfile.STANDARD),
        status=RunStatus.FAILED,
        snapshot_id="snapshot-id",
        snapshot_hash="snapshot",
        config_hash="config",
        strategy_version="analysis-v1",
        code_version="0.8.0",
        started_at=NOW,
        engine_runs=(failed,),
    )

    assert failed.score is None
    assert run.analysis_score is None


def test_historical_contract_has_typed_bars_not_dataframe() -> None:
    series = HistoricalSeries(
        symbol="002475",
        bars=(
            HistoricalBar(
                trading_date=date(2026, 7, 31),
                open=40,
                high=42,
                low=39,
                close=41,
                volume=1000,
            ),
        ),
    )

    assert series.bars[0].close == 41
    assert not hasattr(series, "df")


def test_fetch_requests_are_explicit_and_immutable() -> None:
    quote_request = QuoteRequest(symbols=("002475",))
    history_request = HistoricalRequest(
        symbol="002475",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 31),
        mode=FetchMode.FRESH_REQUIRED,
        force_refresh=True,
    )

    assert quote_request.mode is FetchMode.CACHE_PREFERRED
    assert history_request.mode is FetchMode.FRESH_REQUIRED
    assert history_request.force_refresh is True


def test_strategy_lifecycle_is_explicit() -> None:
    strategy = StrategyVersion(
        name="mean_reversion_v1",
        version="1.0.0-draft.1",
        state=StrategyState.VALIDATED,
        manifest_hash="manifest",
        created_at=NOW,
    )
    assert strategy.state is StrategyState.VALIDATED
    (EngineRunStatus,)
