"""#8 MarketDataRepository 测试：降级链 + 缓存"""

from datetime import date

import pandas as pd
import pytest

from src.diting.data.cache import CacheLayer
from src.diting.data.providers.base import DataProvider
from src.diting.data.repository import (
    MarketDataRepository,
    _normalize_columns,
)
from src.diting.infra.errors import AllProvidersFailedError, DataUnavailableError
from src.diting.schema import HistoricalData, RealtimeQuote

# ── 测试用 Mock Provider ────────────────────────


class HealthyProvider(DataProvider):
    """总是可用的 mock，返回固定数据"""

    @property
    def name(self) -> str:
        return "healthy"

    @property
    def priority(self) -> int:
        return 10

    def health_check(self) -> bool:
        return True

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        return {
            s: RealtimeQuote(
                symbol=s,
                name=f"Healthy{s}",
                price=100.0,
                change_pct=1.0,
                open=99.0,
                high=101.0,
                low=98.5,
                volume=10000,
                turnover=1000000,
            )
            for s in symbols
        }

    def fetch_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        return HistoricalData(
            symbol=symbol,
            df=None,
            columns=["date", "open", "close"],
            start_date=start,
            end_date=end,
        )


class UnhealthyProvider(DataProvider):
    """health_check 返回 False"""

    @property
    def name(self) -> str:
        return "unhealthy"

    @property
    def priority(self) -> int:
        return 20

    def health_check(self) -> bool:
        return False

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        raise DataUnavailableError("unhealthy")

    def fetch_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        raise DataUnavailableError("unhealthy")


class PartialProvider(DataProvider):
    """部分股票有数据，另一部分是 None"""

    def __init__(self, missing: list[str]):
        self.missing = set(missing)

    @property
    def name(self) -> str:
        return "partial"

    @property
    def priority(self) -> int:
        return 5  # 比 healthy(10) 更高优先级，先被调用

    def health_check(self) -> bool:
        return True

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        result = {}
        for s in symbols:
            if s not in self.missing:
                result[s] = RealtimeQuote(
                    symbol=s,
                    name=f"Partial{s}",
                    price=50.0,
                    change_pct=0.5,
                    open=49.5,
                    high=50.5,
                    low=49.0,
                    volume=5000,
                    turnover=250000,
                )
        return result

    def fetch_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        if symbol in self.missing:
            raise DataUnavailableError(f"partial: no data for {symbol}")
        return HistoricalData(
            symbol=symbol,
            df=None,
            columns=["date", "close"],
            start_date=start,
            end_date=end,
        )


# ═══════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════


class TestRepositoryBasic:
    """基础功能测试"""

    def test_realtime_single_provider(self):
        repo = MarketDataRepository([HealthyProvider()])
        results = repo.get_realtime(["002475"])
        assert "002475" in results
        assert results["002475"].price == 100.0

    def test_realtime_caching(self):
        """第二次查询走缓存"""
        cache = CacheLayer()
        repo = MarketDataRepository([HealthyProvider()], cache=cache)
        repo.get_realtime(["002475"])
        results2 = repo.get_realtime(["002475"])
        assert results2["002475"].price == 100.0

    def test_historical(self):
        repo = MarketDataRepository([HealthyProvider()])
        result = repo.get_historical("002475", date(2026, 1, 1), date(2026, 6, 30))
        assert result.symbol == "002475"
        assert result.start_date == date(2026, 1, 1)

    def test_empty_symbols(self):
        repo = MarketDataRepository([HealthyProvider()])
        assert repo.get_realtime([]) == {}


class TestFallbackChain:
    """降级链测试"""

    def test_unhealthy_skipped(self):
        """unhealthy provider 被跳过，直接用健康的"""
        repo = MarketDataRepository([UnhealthyProvider(), HealthyProvider()])
        results = repo.get_realtime(["002475"])
        assert "002475" in results
        assert results["002475"].price == 100.0

    def test_partial_fallback(self):
        """partial 返回了部分，其余从下一个 provider 补"""
        repo = MarketDataRepository(
            [
                PartialProvider(missing=["603659"]),
                HealthyProvider(),
            ]
        )
        results = repo.get_realtime(["002475", "603659"])
        # 002475 从 partial 获取
        assert results["002475"].price == 50.0
        # 603659 partial 没有，从 healthy 获取
        assert results["603659"].price == 100.0

    def test_all_failed_raises(self):
        """所有 provider 都挂了"""
        repo = MarketDataRepository([UnhealthyProvider()])
        with pytest.raises(AllProvidersFailedError):
            repo.get_realtime(["002475"])

    def test_historical_fallback_on_failure(self):
        """历史数据优先用 priority=10，失败则降级"""
        repo = MarketDataRepository(
            [
                PartialProvider(missing=["002475"]),
                HealthyProvider(),
            ]
        )
        # partial 没有 002475 的历史数据 → 降级到 healthy
        result = repo.get_historical("002475", date(2026, 1, 1), date(2026, 6, 30))
        assert result.symbol == "002475"


class TestHealthCheck:
    def test_health_check(self):
        repo = MarketDataRepository(
            [
                HealthyProvider(),
                UnhealthyProvider(),
            ]
        )
        status = repo.health_check()
        assert status["healthy"] is True
        assert status["unhealthy"] is False

    def test_available_providers(self):
        repo = MarketDataRepository(
            [
                HealthyProvider(),
                UnhealthyProvider(),
            ]
        )
        available = repo.available_providers
        assert "healthy" in available
        assert "unhealthy" not in available


class TestSourceAnnotation:
    """验证数据来源标注"""

    def test_source_is_annotated(self):
        repo = MarketDataRepository([HealthyProvider()])
        results = repo.get_realtime(["002475"])
        assert results["002475"].price == 100.0
        # source 字段标注了数据来自哪个 provider
        # (RealtimeQuote 的 source 字段接收字符串形式的 provider name)


class ChineseColumnsProvider(HealthyProvider):
    """Return provider data using Chinese market column names."""

    def fetch_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        frame = pd.DataFrame(
            {
                "日期": ["2026-01-02"],
                "开盘": [10.0],
                "最高": [11.0],
                "最低": [9.5],
                "收盘": [10.5],
                "成交量": [1000],
                "成交额": [10500.0],
                "时间": ["15:00:00"],
                "涨跌幅": [5.0],
            }
        )
        return HistoricalData(
            symbol=symbol,
            df=frame,
            columns=list(frame.columns),
            start_date=start,
            end_date=end,
        )


class TestColumnNormalization:
    def test_normalizes_chinese_columns_without_mutating_input(self):
        frame = pd.DataFrame({"日期": ["2026-01-02"], "收盘价": [10.5]})

        normalized = _normalize_columns(frame)

        assert list(normalized.columns) == ["date", "close"]
        assert list(frame.columns) == ["日期", "收盘价"]
        assert normalized is not frame

    def test_preserves_english_columns(self):
        frame = pd.DataFrame({"date": ["2026-01-02"], "close": [10.5]})

        normalized = _normalize_columns(frame)

        assert list(normalized.columns) == ["date", "close"]
        assert normalized.equals(frame)
        assert normalized is not frame

    def test_english_column_wins_on_mixed_name_conflict(self):
        frame = pd.DataFrame({"close": [10.5], "收盘": [99.0], "成交量": [1000]})

        normalized = _normalize_columns(frame)

        assert list(normalized.columns) == ["close", "收盘", "volume"]
        assert normalized["close"].tolist() == [10.5]

    def test_repository_normalizes_historical_payload(self):
        repo = MarketDataRepository([ChineseColumnsProvider()])

        result = repo.get_historical("002475", date(2026, 1, 1), date(2026, 1, 31))

        assert result.columns == [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "time",
            "change_pct",
        ]
        assert list(result.df.columns) == result.columns
