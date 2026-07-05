"""DataProvider ABC 测试"""

from datetime import date

import pytest

from src.diting.data.providers.base import DataProvider
from src.diting.infra.errors import DataUnavailableError
from src.diting.schema import HistoricalData, RealtimeQuote


class FakeProvider(DataProvider):
    """测试用 mock 实现"""

    @property
    def name(self) -> str:
        return "fake"

    @property
    def priority(self) -> int:
        return 99

    def health_check(self) -> bool:
        return True

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        return {
            s: RealtimeQuote(
                symbol=s,
                name=f"测试{s}",
                price=10.0,
                change_pct=1.0,
                open=9.9,
                high=10.1,
                low=9.8,
                volume=10000,
                turnover=100000,
            )
            for s in symbols
        }

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        return HistoricalData(
            symbol=symbol,
            df=None,
            columns=["date", "open", "close"],
            start_date=start,
            end_date=end,
        )


class FailingProvider(DataProvider):
    """测试用 —— 永远不可用"""

    @property
    def name(self) -> str:
        return "failing"

    @property
    def priority(self) -> int:
        return 50

    def health_check(self) -> bool:
        return False

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        raise DataUnavailableError("failing provider always fails")

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        raise DataUnavailableError("failing provider always fails")


# ═══════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════


class TestDataProviderABC:
    """验证 ABC 接口约束"""

    def test_cannot_instantiate_abc_directly(self):
        with pytest.raises(TypeError):
            DataProvider()  # type: ignore

    def test_concrete_implementation_works(self):
        p = FakeProvider()
        assert p.name == "fake"
        assert p.priority == 99


class TestFakeProvider:
    def test_health_check(self):
        p = FakeProvider()
        assert p.health_check() is True

    def test_fetch_realtime_single(self):
        p = FakeProvider()
        results = p.fetch_realtime(["002475"])
        assert "002475" in results
        q = results["002475"]
        assert q.symbol == "002475"
        assert q.price == 10.0
        assert q.name == "测试002475"

    def test_fetch_realtime_multiple(self):
        p = FakeProvider()
        results = p.fetch_realtime(["002475", "603659"])
        assert len(results) == 2
        assert results["603659"].symbol == "603659"

    def test_fetch_historical(self):
        p = FakeProvider()
        result = p.fetch_historical(
            "002475", date(2026, 1, 1), date(2026, 6, 30)
        )
        assert result.symbol == "002475"
        assert result.start_date == date(2026, 1, 1)
        assert "close" in result.columns

    def test_optional_methods_raise_not_implemented(self):
        p = FakeProvider()
        with pytest.raises(NotImplementedError):
            p.fetch_financials("002475")
        with pytest.raises(NotImplementedError):
            p.fetch_fund_flow("002475", date.today())
        with pytest.raises(NotImplementedError):
            p.fetch_minute("002475", date.today())


class TestFailingProvider:
    def test_health_check_returns_false(self):
        p = FailingProvider()
        assert p.health_check() is False

    def test_fetch_realtime_raises(self):
        p = FailingProvider()
        with pytest.raises(DataUnavailableError):
            p.fetch_realtime(["002475"])

    def test_fetch_historical_raises(self):
        p = FailingProvider()
        with pytest.raises(DataUnavailableError):
            p.fetch_historical("002475", date(2026, 1, 1), date(2026, 6, 30))
