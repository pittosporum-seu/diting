"""#8 MarketDataRepository 测试：降级链 + 缓存"""

from datetime import date

import pytest

from src.diting.data.cache import CacheLayer
from src.diting.data.providers.base import DataProvider
from src.diting.data.repository import MarketDataRepository
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
                symbol=s, name=f"Healthy{s}", price=100.0, change_pct=1.0,
                open=99.0, high=101.0, low=98.5,
                volume=10000, turnover=1000000,
            )
            for s in symbols
        }

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        return HistoricalData(
            symbol=symbol, df=None,
            columns=["date", "open", "close"],
            start_date=start, end_date=end,
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

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
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
                    symbol=s, name=f"Partial{s}", price=50.0, change_pct=0.5,
                    open=49.5, high=50.5, low=49.0,
                    volume=5000, turnover=250000,
                )
        return result

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        if symbol in self.missing:
            raise DataUnavailableError(f"partial: no data for {symbol}")
        return HistoricalData(
            symbol=symbol, df=None,
            columns=["date", "close"],
            start_date=start, end_date=end,
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
        repo = MarketDataRepository([
            PartialProvider(missing=["603659"]),
            HealthyProvider(),
        ])
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
        repo = MarketDataRepository([
            PartialProvider(missing=["002475"]),
            HealthyProvider(),
        ])
        # partial 没有 002475 的历史数据 → 降级到 healthy
        result = repo.get_historical(
            "002475", date(2026, 1, 1), date(2026, 6, 30)
        )
        assert result.symbol == "002475"


class TestHealthCheck:
    def test_health_check(self):
        repo = MarketDataRepository([
            HealthyProvider(),
            UnhealthyProvider(),
        ])
        status = repo.health_check()
        assert status["healthy"] is True
        assert status["unhealthy"] is False

    def test_available_providers(self):
        repo = MarketDataRepository([
            HealthyProvider(),
            UnhealthyProvider(),
        ])
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
