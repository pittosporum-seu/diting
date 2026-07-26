"""非交易时段选股机会测试 — 缓存有效则复用，过期则重扫，任何时刻都有结果。"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.diting.cache.cache_manager import CacheManager
from src.diting.web.services.scan import ScanService


@pytest.fixture
def cache_mgr(tmp_path) -> CacheManager:
    return CacheManager(db_path=str(tmp_path / "test_cache.db"))


@pytest.fixture
def scan(cache_mgr) -> ScanService:
    return ScanService(cache_mgr=cache_mgr)


def _seed_scan_db(cache_mgr, scan_date: str, items: list[dict]) -> None:
    """向 market_scan_cache 预置一条扫描记录。"""
    cache_mgr.db_set(
        "market_scan_cache",
        f"{scan_date}-1500",
        {
            "scan_date": scan_date,
            "scan_time": "afternoon",
            "top20_json": json.dumps(items, ensure_ascii=False),
        },
    )


MARKET_ITEMS = [
    {"code": "600000", "name": "浦发银行", "score": 70, "signals": []},
    {"code": "000002", "name": "万科A", "score": 66, "signals": []},
]


class TestGetValidMarketTop20:
    def test_reuse_cache_when_no_new_trading(self, scan, cache_mgr):
        """扫描日 == 最近交易日（周五扫的，周末没再开盘）→ 复用缓存，不重扫。"""
        _seed_scan_db(cache_mgr, "2026-07-24", MARKET_ITEMS)
        with patch.object(scan, "_scan_market_top20") as mock_scan:
            result = scan._get_valid_market_top20(date(2026, 7, 24))
        assert result == MARKET_ITEMS
        mock_scan.assert_not_called()  # 没有重扫

    def test_rescan_when_cache_stale(self, scan, cache_mgr):
        """扫描日早于最近交易日（周四扫的，周五又开盘了）→ 重扫。"""
        _seed_scan_db(cache_mgr, "2026-07-23", MARKET_ITEMS)
        fresh = [{"code": "600001", "name": "邯郸钢铁", "score": 80, "signals": []}]
        with patch.object(scan, "_scan_market_top20", return_value=fresh) as mock_scan:
            result = scan._get_valid_market_top20(date(2026, 7, 24))
        assert result == fresh
        mock_scan.assert_called_once_with(force=True)

    def test_rescan_when_no_cache(self, scan, cache_mgr):
        """无任何缓存 → 重扫。"""
        fresh = [{"code": "600001", "name": "邯郸钢铁", "score": 80, "signals": []}]
        with patch.object(scan, "_scan_market_top20", return_value=fresh) as mock_scan:
            result = scan._get_valid_market_top20(date(2026, 7, 24))
        assert result == fresh
        mock_scan.assert_called_once_with(force=True)

    def test_memory_cache_used_when_db_empty(self, scan, cache_mgr):
        """DB 空但内存有扫描结果（日期未知）→ 触发重扫以保证数据有效。"""
        cache_mgr.mem_set("market_scan", MARKET_ITEMS)
        fresh = [{"code": "600001", "name": "邯郸钢铁", "score": 80, "signals": []}]
        with patch.object(scan, "_scan_market_top20", return_value=fresh):
            result = scan._get_valid_market_top20(date(2026, 7, 24))
        # 内存缓存无日期，无法验证有效性 → 重扫
        assert result == fresh


class TestReadLatestScan:
    def test_read_from_db_with_date(self, scan, cache_mgr):
        _seed_scan_db(cache_mgr, "2026-07-24", MARKET_ITEMS)
        items, scan_date = scan._read_latest_scan()
        assert items == MARKET_ITEMS
        assert scan_date == date(2026, 7, 24)

    def test_read_latest_batch(self, scan, cache_mgr):
        """多批次时读最新（batch_id 字典序最大）。"""
        _seed_scan_db(cache_mgr, "2026-07-23", MARKET_ITEMS)
        newer = [{"code": "000001", "name": "平安银行", "score": 75, "signals": []}]
        _seed_scan_db(cache_mgr, "2026-07-24", newer)
        items, scan_date = scan._read_latest_scan()
        assert items == newer
        assert scan_date == date(2026, 7, 24)

    def test_empty_returns_none(self, scan, cache_mgr):
        items, scan_date = scan._read_latest_scan()
        assert items == []
        assert scan_date is None


class TestOffhoursOpportunities:
    def test_weekend_returns_nonempty(self, scan, cache_mgr):
        """周末有有效扫描缓存时，返回非空机会（不返回空）。"""
        _seed_scan_db(cache_mgr, "2026-07-24", MARKET_ITEMS)
        with patch.object(scan, "_scan_watchlist", return_value=[]):
            with patch("src.diting.cache.get_market_state") as mock_state:
                mock_state.return_value = MagicMock(
                    should_call_api=False,
                    phase="weekend",
                    last_trade_date=date(2026, 7, 24),
                )
                result = scan.get_opportunities()
        assert result["total"] == 2
        assert len(result["from_market"]) == 2
        assert result["items"][0]["score"] >= result["items"][-1]["score"]

    def test_offhours_includes_watchlist(self, scan, cache_mgr):
        """非交易时段结果包含自选股。"""
        _seed_scan_db(cache_mgr, "2026-07-24", MARKET_ITEMS)
        watchlist = [{"code": "002475", "name": "立讯精密", "score": 88, "signals": []}]
        with patch.object(scan, "_scan_watchlist", return_value=watchlist):
            with patch("src.diting.cache.get_market_state") as mock_state:
                mock_state.return_value = MagicMock(
                    should_call_api=False,
                    phase="weekend",
                    last_trade_date=date(2026, 7, 24),
                )
                result = scan.get_opportunities()
        assert result["total"] == 3  # 1 自选 + 2 市场
        assert result["from_watchlist"] == watchlist
        # 自选股 88 分排最前
        assert result["items"][0]["code"] == "002475"
