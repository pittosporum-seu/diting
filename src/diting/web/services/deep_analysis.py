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

    def __init__(self, stock_service: StockService, max_concurrent: int | None = None):
        self._stock_service = stock_service
        self._lock = threading.Lock()
        self._state: dict = self._idle_state()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # 股票间并发数（默认 4，避免打爆 mimo 限流）
        if max_concurrent is None:
            from ...infra.config_loader import ConfigLoader

            max_concurrent = ConfigLoader.get_section("pipeline").get("deep_concurrent", 4)
        self._max_concurrent = max(1, int(max_concurrent))

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
        from ...engines.batch_ai import BatchAIAnalyzer
        from ...infra.config_loader import ConfigLoader

        ai_engines = {"wyckoff", "can_slim"}
        batch_size = max(1, int(ConfigLoader.get_section("pipeline").get("ai_batch_size", 15)))
        analyzer = BatchAIAnalyzer(self._stock_service)
        analyzed = 0
        completed = 0

        logger.info("deep_analysis.batch", batch_size=batch_size, total=len(codes))
        # 按 batch_size 分批：每批先一次性批量取 AI 结果（wyckoff+can_slim 各 1 次调用），
        # 再逐只跑 quick 引擎 + 共识融合 + 写缓存（复用预取的 AI 结果）
        for batch_start in range(0, len(codes), batch_size):
            if self._stop_event.is_set():
                break
            batch = codes[batch_start : batch_start + batch_size]

            # 过滤已完整的（非 force）
            to_analyze: list[str] = []
            for code in batch:
                if not force and self._has_complete_analysis(code, ai_engines):
                    with self._lock:
                        completed += 1
                        analyzed += 1
                        self._state["done"] = completed
                else:
                    to_analyze.append(code)
            if not to_analyze:
                continue

            # 批量 AI：整批一次 wyckoff + 一次 can_slim
            try:
                ai_results = analyzer.analyze(to_analyze, list(ai_engines))
            except Exception as e:
                logger.warning("deep_analysis.batch_ai_failed", error=str(e))
                ai_results = {}

            # 逐只：quick 引擎 + 融合 + 缓存（传入预取 AI 结果）
            for code in to_analyze:
                if self._stop_event.is_set():
                    break
                with self._lock:
                    self._state["current_code"] = code
                try:
                    self._stock_service.analyze_stock(
                        code,
                        force=True,
                        run_ai=True,
                        ai_results_override=ai_results.get(code, []),
                    )
                    analyzed += 1
                except Exception:
                    logger.warning("deep_analysis.stock_failed", code=code)
                with self._lock:
                    completed += 1
                    self._state["done"] = completed

        with self._lock:
            self._state["status"] = "done"
            self._state["current_code"] = None
            self._state["finished_at"] = datetime.now(UTC).isoformat()
        logger.info("deep_analysis.done", total=len(codes), analyzed=analyzed)

    def _has_complete_analysis(self, code: str, ai_engines: set) -> bool:
        """检查某只股票是否已有含全部 AI 引擎的完整分析缓存。"""
        try:
            cm = self._stock_service._get_cache_mgr()
            cached = cm.mem_get(f"analysis:{code}")
            result = None
            if cached is not None:
                from dataclasses import asdict, is_dataclass

                result = asdict(cached) if is_dataclass(cached) else cached
            if not result:
                import json as _json

                row = cm.db_get("stock_analysis_cache", code)
                if row and row.get("result_json"):
                    result = _json.loads(row["result_json"])
            if not result:
                return False
            names = {
                (e.get("engine_name") or e.get("name")) for e in result.get("engine_scores", [])
            }
            return ai_engines.issubset(names)
        except Exception:
            return False
