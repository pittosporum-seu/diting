"""Explicit registry and deterministic technical-engine tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.diting.engines.kernel import EngineRegistry
from src.diting.engines.technical_v080 import TechnicalEngine
from src.diting.enums import EngineMode
from src.diting.infra.errors import DataUnavailableError
from src.diting.schema import (
    DataResult,
    DataSnapshot,
    EngineContext,
    HistoricalBar,
    HistoricalSeries,
    RealtimeQuote,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
CONTEXT = EngineContext(deadline=None, config_hash="config", strategy_version="analysis-v1")


def _snapshot(*, bars: int = 80, rising: bool = True) -> DataSnapshot:
    values = [20 + index * (0.1 if rising else -0.1) for index in range(bars)]
    history = HistoricalSeries(
        symbol="002475",
        bars=tuple(
            HistoricalBar(
                trading_date=date(2026, 1, 1) + timedelta(days=index),
                open=value,
                high=value + 0.5,
                low=value - 0.5,
                close=value,
                volume=1000 + index * 10,
            )
            for index, value in enumerate(values)
        ),
    )
    quote = RealtimeQuote(
        symbol="002475",
        name="立讯精密",
        price=values[-1],
        change_pct=1 if rising else -1,
        open=values[-1],
        high=values[-1],
        low=values[-1],
        volume=2000,
        turnover=1,
        timestamp=NOW,
    )
    return DataSnapshot(
        snapshot_id="snapshot",
        symbol="002475",
        created_at=NOW,
        as_of=NOW,
        quote=DataResult(data=quote, data_time=NOW),
        historical=DataResult(data=history, data_time=NOW),
        snapshot_hash="hash",
    )


def test_registry_is_explicit_and_rejects_duplicates() -> None:
    technical = TechnicalEngine()
    registry = EngineRegistry((technical,))

    assert registry.names == ("technical",)
    assert registry.require("technical") is technical
    with pytest.raises(KeyError, match="not registered"):
        registry.require("wyckoff")
    with pytest.raises(ValueError, match="duplicate"):
        EngineRegistry((TechnicalEngine(), TechnicalEngine()))


def test_technical_engine_declares_deterministic_capabilities() -> None:
    engine = TechnicalEngine()
    capabilities = engine.capabilities()

    assert engine.mode is EngineMode.DETERMINISTIC
    assert capabilities.deterministic is True
    assert capabilities.requires_llm is False
    assert capabilities.requires_sandbox is False
    assert capabilities.min_history_bars == 60


def test_technical_engine_produces_typed_valid_analysis() -> None:
    result = TechnicalEngine().analyze(_snapshot(), CONTEXT)

    assert result.engine_name == "technical"
    assert 0 <= result.engine_score <= 100
    assert result.symbol == "002475"
    assert result.narrative
    assert result.evidence
    assert result.risks
    assert dict(result.metadata)["rsi_14"]


def test_technical_engine_fails_instead_of_returning_50_for_missing_data() -> None:
    with pytest.raises(DataUnavailableError, match="need >=60"):
        TechnicalEngine().analyze(_snapshot(bars=20), CONTEXT)
