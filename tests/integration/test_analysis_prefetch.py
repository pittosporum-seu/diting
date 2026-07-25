"""AnalysisPrefetchWorker 测试 — 优先级队列、调度、分批限流。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.diting.cache.analysis_prefetch import AnalysisPrefetchWorker
from src.diting.cache.cache_manager import CacheManager


@pytest.fixture
def cache_mgr(tmp_path) -> CacheManager:
    return CacheManager(db_path=str(tmp_path / "test_cache.db"))


def _make_worker(cache_mgr, **cfg_overrides) -> AnalysisPrefetchWorker:
    cfg = {
        "enabled": True,
        "idle_hour": 18,
        "batch_size": 3,
        "stock_delay": 0,   # 测试中不等待
        "batch_delay": 0,
        "max_stocks": 30,
        "signal_threshold": 65,
    }
    cfg.update(cfg_overrides)
    stock_service = MagicMock()
    scan_service = MagicMock()
    return AnalysisPrefetchWorker(
        stock_service, scan_service, cache_mgr=cache_mgr, cfg=cfg
    )


# ═══════════════════════════════════════════
# 优先级队列
# ═══════════════════════════════════════════


class TestPriorityQueue:
    def test_watchlist_before_signal(self, cache_mgr):
        """自选股排在信号股前面。"""
        w = _make_worker(cache_mgr)
        with patch.object(w, "_get_watchlist_codes", return_value=["000001", "000002"]):
            with patch.object(w, "_get_signal_codes", return_value=["600000", "600001"]):
                q = w._build_priority_queue()
        assert q == ["000001", "000002", "600000", "600001"]

    def test_dedup_watchlist_priority(self, cache_mgr):
        """重复代码去重，自选股优先保留。"""
        w = _make_worker(cache_mgr)
        with patch.object(w, "_get_watchlist_codes", return_value=["000001", "000002"]):
            with patch.object(w, "_get_signal_codes", return_value=["000002", "600000"]):
                q = w._build_priority_queue()
        # 000002 已在自选股中，信号股的 000002 被跳过
        assert q == ["000001", "000002", "600000"]

    def test_cap_at_max_stocks(self, cache_mgr):
        """总数封顶 max_stocks。"""
        w = _make_worker(cache_mgr, max_stocks=3)
        codes = [f"00000{i}" for i in range(10)]
        with patch.object(w, "_get_watchlist_codes", return_value=codes):
            with patch.object(w, "_get_signal_codes", return_value=[]):
                q = w._build_priority_queue()
        assert len(q) == 3
        assert q == codes[:3]

    def test_signal_threshold_filter(self, cache_mgr):
        """信号股按 score >= threshold 过滤。"""
        w = _make_worker(cache_mgr, signal_threshold=65)
        scan_items = [
            {"code": "600000", "score": 80},
            {"code": "600001", "score": 50},  # 低于阈值
            {"code": "600002", "score": 70},
        ]
        w._stock_service = MagicMock()
        w._scan_service = MagicMock()
        w._scan_service.get_opportunities.return_value = {"items": scan_items}
        with patch.object(w._cache_mgr, "mem_get", return_value=None):
            codes = w._get_signal_codes()
        assert codes == ["600000", "600002"]


# ═══════════════════════════════════════════
# 调度判断
# ═══════════════════════════════════════════


class TestScheduling:
    def test_not_run_before_idle_hour(self, cache_mgr):
        w = _make_worker(cache_mgr, idle_hour=18)
        assert w._should_run_now(datetime(2026, 7, 25, 10, 0)) is False
        assert w._should_run_now(datetime(2026, 7, 25, 17, 59)) is False

    def test_run_after_idle_hour_if_not_run_today(self, cache_mgr):
        w = _make_worker(cache_mgr, idle_hour=18)
        # 今天没跑过
        assert w._should_run_now(datetime(2026, 7, 25, 18, 0)) is True
        assert w._should_run_now(datetime(2026, 7, 25, 23, 0)) is True

    def test_not_run_if_already_run_today(self, cache_mgr):
        w = _make_worker(cache_mgr, idle_hour=18)
        # 标记今天已跑
        w._mark_run_today(date(2026, 7, 25))
        assert w._should_run_now(datetime(2026, 7, 25, 20, 0)) is False

    def test_run_next_day(self, cache_mgr):
        """昨天跑过，今天到点仍可跑。"""
        w = _make_worker(cache_mgr, idle_hour=18)
        w._mark_run_today(date(2026, 7, 24))
        assert w._should_run_now(datetime(2026, 7, 25, 18, 0)) is True

    def test_last_date_persistence(self, cache_mgr):
        """last_date 持久化到 SQLite。"""
        w = _make_worker(cache_mgr, idle_hour=18)
        assert w._last_run_date() is None
        w._mark_run_today(date(2026, 7, 25))
        assert w._last_run_date() == date(2026, 7, 25)


# ═══════════════════════════════════════════
# 分批执行
# ═══════════════════════════════════════════


class TestBatchExecution:
    def test_analyze_called_for_all(self, cache_mgr):
        """队列中每只股票都调用 analyze_stock。"""
        w = _make_worker(cache_mgr, batch_size=2)
        codes = ["000001", "000002", "000003", "000004", "000005"]
        with patch.object(w, "_build_priority_queue", return_value=codes):
            w._run_once()
        called = [c.args[0] for c in w._stock_service.analyze_stock.call_args_list]
        assert called == codes

    def test_marks_run_today_after_run(self, cache_mgr):
        w = _make_worker(cache_mgr)
        with patch.object(w, "_build_priority_queue", return_value=["000001"]):
            w._run_once()
        assert w._last_run_date() == date.today()

    def test_empty_queue_marks_done(self, cache_mgr):
        """空队列也标记今天已跑，避免反复检查。"""
        w = _make_worker(cache_mgr)
        with patch.object(w, "_build_priority_queue", return_value=[]):
            w._run_once()
        assert w._last_run_date() == date.today()
        w._stock_service.analyze_stock.assert_not_called()

    def test_failure_does_not_stop_batch(self, cache_mgr):
        """单只失败不中断后续抓取。"""
        w = _make_worker(cache_mgr, batch_size=3)
        w._stock_service.analyze_stock.side_effect = [
            Exception("boom"), None, None,
        ]
        with patch.object(w, "_build_priority_queue", return_value=["a", "b", "c"]):
            w._run_once()
        assert w._stock_service.analyze_stock.call_count == 3

    def test_disabled_worker_does_not_start(self, cache_mgr):
        w = _make_worker(cache_mgr, enabled=False)
        w.start()
        assert w.is_running is False
