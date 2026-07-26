"""非交易时段选股机会测试 — 缓存有效则复用，过期则重扫，任何时刻都有结果。"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

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


class TestTieredOpportunities:
    """分层分析：排行榜只收录有全量分析结果的候选，用引擎共识分。"""

    def _seed_analysis(self, cache_mgr, code, score, name="测试"):
        """预置某只股票的全量分析缓存。"""
        cache_mgr.db_set(
            "stock_analysis_cache",
            code,
            {
                "result_json": json.dumps(
                    {
                        "code": code,
                        "name": name,
                        "price": 10.0,
                        "change_pct": 1.0,
                        "score": score,
                        "rating": "hold",
                        "rating_label": "建议观望",
                        "error": None,
                    },
                    ensure_ascii=False,
                )
            },
        )

    def test_ranking_uses_engine_score(self, scan, cache_mgr):
        """排行榜用全量引擎分（非 quick 分），与详情页一致。"""
        # 候选：quick 分 600000 高，但全量引擎分 600000 低、000002 高
        market = [
            {"code": "600000", "name": "浦发银行", "score": 90, "signals": []},
            {"code": "000002", "name": "万科A", "score": 50, "signals": []},
        ]
        # 全量分析缓存：600000 引擎分 40，000002 引擎分 80
        self._seed_analysis(cache_mgr, "600000", 40)
        self._seed_analysis(cache_mgr, "000002", 80)

        with patch.object(scan, "_scan_market_top20", return_value=market):
            with patch.object(scan, "_scan_watchlist", return_value=[]):
                result = scan.get_opportunities()

        # 按引擎分排序：000002(80) 在前，600000(40) 在后
        assert result["items"][0]["code"] == "000002"
        assert result["items"][0]["score"] == 80
        assert result["items"][1]["code"] == "600000"
        assert result["items"][1]["score"] == 40

    def test_only_analyzed_stocks_ranked(self, scan, cache_mgr):
        """未完成全量分析的候选不入榜。"""
        market = [
            {"code": "600000", "name": "浦发银行", "score": 90, "signals": []},
            {"code": "000002", "name": "万科A", "score": 50, "signals": []},
        ]
        # 只有 600000 有全量分析缓存，000002 没有
        self._seed_analysis(cache_mgr, "600000", 70)

        with patch.object(scan, "_scan_market_top20", return_value=market):
            with patch.object(scan, "_scan_watchlist", return_value=[]):
                result = scan.get_opportunities()

        codes = [it["code"] for it in result["items"]]
        assert "600000" in codes
        assert "000002" not in codes  # 未全量分析，不入榜

    def test_watchlist_included_when_analyzed(self, scan, cache_mgr):
        """自选股完成全量分析后入榜。"""
        market = [{"code": "600000", "name": "浦发银行", "score": 90, "signals": []}]
        watchlist = [{"code": "002475", "name": "立讯精密", "score": 55, "signals": []}]
        self._seed_analysis(cache_mgr, "600000", 60)
        self._seed_analysis(cache_mgr, "002475", 88, name="立讯精密")

        with patch.object(scan, "_scan_market_top20", return_value=market):
            with patch.object(scan, "_scan_watchlist", return_value=watchlist):
                result = scan.get_opportunities()

        # 002475 引擎分 88 最高，排第一
        assert result["items"][0]["code"] == "002475"
        assert result["items"][0]["source"] == "watchlist"
