"""数据源降级链测试 — 验证 provider 降级和容错。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from src.diting.data.providers.ashare import AshareProvider
from src.diting.data.providers.base import DataProvider
from src.diting.data.repository import MarketDataRepository
from src.diting.infra.errors import AllProvidersFailedError, DataUnavailableError


class TestAshareProvider:
    """Ashare（新浪/腾讯免费接口）基础功能。"""

    def test_realtime_returns_data(self):
        p = AshareProvider()
        results = p.fetch_realtime(["002475"])
        assert "002475" in results
        q = results["002475"]
        assert q.symbol == "002475"
        assert q.price > 0
        assert q.name

    def test_historical_returns_data(self):
        p = AshareProvider()
        h = p.fetch_historical("002475", date(2026, 6, 1), date(2026, 7, 25))
        assert h.df is not None
        assert len(h.df) > 0
        assert "close" in h.df.columns

    def test_empty_symbols(self):
        p = AshareProvider()
        assert p.fetch_realtime([]) == {}

    def test_health_check(self):
        p = AshareProvider()
        assert p.health_check() is True


class TestProviderFallback:
    """降级链：主源失败时自动切换到备源。"""

    def _make_repo(self, providers):
        """创建带空缓存的 Repository。"""
        from src.diting.data.cache import CacheLayer

        empty_cache = CacheLayer(max_size=10, default_ttl=0)
        return MarketDataRepository(providers=providers, cache=empty_cache)

    def test_fallback_on_primary_failure(self):
        """主源抛异常时，备源正常返回。"""
        failing = MagicMock(spec=DataProvider)
        failing.name = "failing"
        failing.priority = 10
        failing.health_check.return_value = True
        failing.fetch_realtime.side_effect = DataUnavailableError("connection refused")

        working = MagicMock(spec=DataProvider)
        working.name = "working"
        working.priority = 20
        working.health_check.return_value = True
        mock_quote = MagicMock()
        mock_quote.symbol = "002475"
        working.fetch_realtime.return_value = {"002475": mock_quote}

        repo = self._make_repo([failing, working])
        results = repo.get_realtime(["002475"])
        assert "002475" in results

    def test_all_providers_fail_raises(self):
        """所有数据源失败时抛 AllProvidersFailedError。"""
        failing1 = MagicMock(spec=DataProvider)
        failing1.name = "fail1"
        failing1.priority = 10
        failing1.health_check.return_value = True
        failing1.fetch_realtime.side_effect = DataUnavailableError("down")

        failing2 = MagicMock(spec=DataProvider)
        failing2.name = "fail2"
        failing2.priority = 20
        failing2.health_check.return_value = True
        failing2.fetch_realtime.side_effect = DataUnavailableError("also down")

        repo = self._make_repo([failing1, failing2])
        with pytest.raises(AllProvidersFailedError):
            repo.get_realtime(["002475"])

    def test_provider_priority_ordering(self):
        """providers 按 priority 排序，数字小的先尝试。"""
        p1 = MagicMock(spec=DataProvider)
        p1.name = "low_priority"
        p1.priority = 50

        p2 = MagicMock(spec=DataProvider)
        p2.name = "high_priority"
        p2.priority = 10

        repo = self._make_repo([p1, p2])
        assert repo._providers[0].name == "high_priority"


class TestGracefulDegradation:
    """容错：部分数据缺失时不崩溃。"""

    def test_partial_realtime_results(self):
        """provider 返回部分结果时，已获取的写入缓存，缺失的抛异常。"""
        from src.diting.data.cache import CacheLayer

        provider = MagicMock(spec=DataProvider)
        provider.name = "partial"
        provider.priority = 10
        provider.health_check.return_value = True
        mock_quote = MagicMock()
        mock_quote.symbol = "002475"
        provider.fetch_realtime.return_value = {"002475": mock_quote}

        empty_cache = CacheLayer(max_size=10, default_ttl=0)
        repo = MarketDataRepository(providers=[provider], cache=empty_cache)
        # 查询 provider 能返回的股票 — 应成功
        results = repo.get_realtime(["002475"])
        assert "002475" in results

    def test_missing_symbol_raises(self):
        """所有 provider 都无法返回某只股票时抛 AllProvidersFailedError。"""
        from src.diting.data.cache import CacheLayer

        provider = MagicMock(spec=DataProvider)
        provider.name = "limited"
        provider.priority = 10
        provider.health_check.return_value = True
        provider.fetch_realtime.return_value = {}  # 返回空

        empty_cache = CacheLayer(max_size=10, default_ttl=0)
        repo = MarketDataRepository(providers=[provider], cache=empty_cache)
        with pytest.raises(AllProvidersFailedError):
            repo.get_realtime(["600519"])
