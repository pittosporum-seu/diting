"""谛听 · Background Prefetch — 后台预刷新线程

每 30 秒自动刷新高频数据（dashboard/watchlist），每 120 秒刷新中频数据。
只在交易日运行，周末/节假日自动跳过以节省 API 配额。
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from ..infra.logging_config import get_logger
from .market_state import get_market_state, record_refresh

if TYPE_CHECKING:
    from ..web.services import StockService

logger = get_logger(__name__)

# v0.7.0: shorter interval during TRADING for fresher data
_PREFETCH_INTERVAL = 30  # 30 秒（高频刷新）

# 高频端点：每轮都刷新
_PREFETCH_HIGH_FREQ = [
    "get_dashboard_data",
    "get_watchlist",
]

# 中频端点：每 4 轮刷新一次（每 120s）
_PREFETCH_MID_FREQ = [
    "get_opportunities",
    "get_market_sentiment",
]


class PrefetchWorker:
    """后台预刷新 Worker。

    在独立 daemon 线程中运行，高频 30s，中频 120s。
    用法:
        worker = PrefetchWorker(service)
        worker.start()
    """

    def __init__(self, service: StockService) -> None:
        self._service = service
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._run_lock = threading.Lock()
        self._running = False
        self._last_run: float = 0.0
        self._error_count: int = 0
        self._run_count: int = 0  # v0.7.0: track runs for mid-freq scheduling

    @property
    def is_running(self) -> bool:
        """Worker 是否正在运行。"""
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def last_run_time(self) -> float:
        """上次运行时间戳。"""
        return self._last_run

    @property
    def error_count(self) -> int:
        """累计错误次数。"""
        return self._error_count

    def start(self) -> None:
        """启动后台预刷新线程。"""
        if self._running:
            logger.warning("prefetch.already_running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="diting-prefetch",
        )
        self._thread.start()
        self._running = True
        logger.info("prefetch.started", interval_s=_PREFETCH_INTERVAL)

    def stop(self) -> None:
        """停止后台预刷新线程（优雅退出）。"""
        if not self._running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._running = False
        logger.info("prefetch.stopped")

    def _loop(self) -> None:
        """主循环：休眠 → 检查市场状态 → 刷新数据。"""
        logger.info("prefetch.loop.start")
        while not self._stop_event.is_set():
            # 等待间隔（支持优雅退出）
            if self._stop_event.wait(_PREFETCH_INTERVAL):
                break

            # 防重叠：上一轮未完成则跳过本轮
            if not self._run_lock.acquire(blocking=False):
                continue
            try:
                self._run_once()
            except Exception:
                self._error_count += 1
                logger.exception("prefetch.loop.error")
            finally:
                self._run_lock.release()

        logger.info("prefetch.loop.exit")

    def _run_once(self) -> None:
        """执行一次预刷新。"""
        state = get_market_state()

        if not state.is_trading:
            # v0.7.0: skip silently (reduced log noise)
            return

        self._run_count += 1
        run_mid_freq = self._run_count % 4 == 0  # every 4th run (120s)

        logger.info(
            "prefetch.run",
            phase=state.phase,
            today_is_trade=state.today_is_trade_day,
            run_count=self._run_count,
        )

        # High-frequency: every run
        for method_name in _PREFETCH_HIGH_FREQ:
            if self._stop_event.is_set():
                break
            try:
                method = getattr(self._service, method_name, None)
                if method is None:
                    logger.warning("prefetch.method_not_found", method=method_name)
                    continue
                method(force_refresh=True)
                logger.debug("prefetch.method_done", method=method_name)
            except Exception:
                self._error_count += 1
                logger.warning(
                    "prefetch.method_failed",
                    method=method_name,
                    error_count=self._error_count,
                )

        # Mid-frequency: every 4th run (120s)
        if not run_mid_freq:
            record_refresh()
            self._last_run = time.time()
            return

        for method_name in _PREFETCH_MID_FREQ:
            if self._stop_event.is_set():
                break
            try:
                method = getattr(self._service, method_name, None)
                if method is None:
                    logger.warning("prefetch.method_not_found", method=method_name)
                    continue
                method(force_refresh=True)
                logger.debug("prefetch.method_done", method=method_name)
            except Exception:
                self._error_count += 1
                logger.warning(
                    "prefetch.method_failed",
                    method=method_name,
                    error_count=self._error_count,
                )

        # 标记刷新记录
        record_refresh()
        self._last_run = time.time()

        logger.info(
            "prefetch.done",
            phase=state.phase,
            error_count=self._error_count,
        )
