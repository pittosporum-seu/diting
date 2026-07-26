"""谛听 · 后台深度分析管理器

对候选股批量跑全量分析（analyze_stock），带进度跟踪。
用于"quick 初筛 → 候选跑全量 → 优中选优"的分层分析流程。
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ...infra.logging_config import get_logger

if TYPE_CHECKING:
    from .stock import StockService

logger = get_logger(__name__)


class DeepAnalysisManager:
    """后台对候选股批量跑全量分析，带进度跟踪。

    用法:
        mgr = DeepAnalysisManager(stock_service)
        mgr.start(["002475", "603667"], force=False)   # 后台启动
        mgr.get_progress()                              # 查询进度
    """

    def __init__(self, stock_service: StockService):
        self._stock_service = stock_service
        self._lock = threading.Lock()
        self._state: dict = self._idle_state()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "status": "idle",  # idle / running / done / error
            "total": 0,
            "done": 0,
            "current_code": None,
            "started_at": None,
            "finished_at": None,
        }

    def get_progress(self) -> dict:
        """返回当前进度快照。"""
        with self._lock:
            return dict(self._state)

    def is_running(self) -> bool:
        with self._lock:
            return self._state["status"] == "running"

    def start(self, codes: list[str], force: bool = False) -> dict:
        """启动后台深度分析。若已在运行则返回当前进度（不重复启动）。"""
        with self._lock:
            if self._state["status"] == "running":
                return dict(self._state)
            self._state = {
                "status": "running",
                "total": len(codes),
                "done": 0,
                "current_code": None,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
            }
            self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run,
            args=(list(codes), force),
            daemon=True,
            name="diting-deep-analysis",
        )
        self._thread.start()
        logger.info("deep_analysis.started", total=len(codes), force=force)
        return self.get_progress()

    def stop(self) -> None:
        """请求停止后台分析。"""
        self._stop_event.set()

    def _run(self, codes: list[str], force: bool) -> None:
        done = 0
        for i, code in enumerate(codes):
            if self._stop_event.is_set():
                break
            with self._lock:
                self._state["current_code"] = code
            try:
                self._stock_service.analyze_stock(code, force=force)
                done += 1
            except Exception:
                logger.warning("deep_analysis.stock_failed", code=code)
            with self._lock:
                self._state["done"] = i + 1

        with self._lock:
            self._state["status"] = "done"
            self._state["current_code"] = None
            self._state["finished_at"] = datetime.now(UTC).isoformat()
        logger.info("deep_analysis.done", total=len(codes), analyzed=done)
