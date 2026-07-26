"""谛听 · AnalysisPrefetchWorker — 后台优先级个股抓取

收盘后数据即固定，在闲时（idle_hour）后台按优先级分批抓取个股完整分析并写入缓存：
  Tier 1: 自选股（最高优先级）
  Tier 2: 信号股（最新全市场扫描中 score >= signal_threshold 的个股）

规避 API 限流：分批抓取，单只之间 stock_delay、批次之间 batch_delay。
每日仅跑一次（用 SQLite cache_meta 记录 last_date），服务器中途重启可自动补跑。
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import TYPE_CHECKING

from ..infra.logging_config import get_logger
from .cache_manager import CacheManager

if TYPE_CHECKING:
    from ..web.services import DashboardService, ScanService, StockService

logger = get_logger(__name__)

_LAST_DATE_KEY = "analysis_prefetch_last_date"
_CHECK_INTERVAL = 300  # 每 5 分钟检查一次是否该跑


class AnalysisPrefetchWorker:
    """后台优先级个股抓取 Worker。

    用法:
        worker = AnalysisPrefetchWorker(stock_service, scan_service)
        worker.start()
    """

    def __init__(
        self,
        stock_service: StockService,
        scan_service: ScanService | None = None,
        cache_mgr: CacheManager | None = None,
        cfg: dict | None = None,
        dashboard_service: DashboardService | None = None,
    ) -> None:
        from ..infra.config_loader import ConfigLoader

        self._stock_service = stock_service
        self._scan_service = scan_service
        self._dashboard_service = dashboard_service
        self._cache_mgr = cache_mgr or CacheManager()

        # 读取 prefetch.analysis 配置段
        if cfg is None:
            cfg = ConfigLoader.get_section("prefetch").get("analysis", {})
        self._enabled = bool(cfg.get("enabled", True))
        self._idle_hour = int(cfg.get("idle_hour", 18))
        self._batch_size = max(1, int(cfg.get("batch_size", 3)))
        self._stock_delay = float(cfg.get("stock_delay", 3))
        self._batch_delay = float(cfg.get("batch_delay", 20))
        self._max_stocks = int(cfg.get("max_stocks", 30))
        self._signal_threshold = float(cfg.get("signal_threshold", 65))

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._run_lock = threading.Lock()
        self._running = False

    # ── 生命周期 ──────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if not self._enabled:
            logger.info("analysis_prefetch.disabled")
            return
        if self._running:
            logger.warning("analysis_prefetch.already_running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="diting-analysis-prefetch"
        )
        self._thread.start()
        self._running = True
        logger.info(
            "analysis_prefetch.started",
            idle_hour=self._idle_hour,
            batch_size=self._batch_size,
            max_stocks=self._max_stocks,
        )

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._running = False
        logger.info("analysis_prefetch.stopped")

    # ── 主循环 ──────────────────────────────────

    def _loop(self) -> None:
        logger.info("analysis_prefetch.loop.start")
        while not self._stop_event.is_set():
            if self._stop_event.wait(_CHECK_INTERVAL):
                break
            if not self._run_lock.acquire(blocking=False):
                continue
            try:
                if self._should_run_now():
                    self._run_once()
            except Exception:
                logger.exception("analysis_prefetch.loop.error")
            finally:
                self._run_lock.release()
        logger.info("analysis_prefetch.loop.exit")

    # ── 调度判断 ──────────────────────────────────

    def _should_run_now(self, now: datetime | None = None) -> bool:
        """是否该跑：当前时间 >= idle_hour 且今天尚未跑过。"""
        now = now or datetime.now()
        if now.hour < self._idle_hour:
            return False
        return self._last_run_date() != now.date()

    def _last_run_date(self) -> date | None:
        """从 SQLite 读取上次运行日期。"""
        try:
            row = self._cache_mgr.db_get("cache_meta", _LAST_DATE_KEY)
            if row and row.get("value"):
                return date.fromisoformat(str(row["value"])[:10])
        except Exception:
            logger.warning("analysis_prefetch.read_last_date_failed")
        return None

    def _mark_run_today(self, today: date | None = None) -> None:
        """记录今天已跑过。"""
        today = today or date.today()
        try:
            self._cache_mgr.db_set(
                "cache_meta",
                _LAST_DATE_KEY,
                {
                    "key": _LAST_DATE_KEY,
                    "value": today.isoformat(),
                },
            )
        except Exception:
            logger.warning("analysis_prefetch.mark_failed")

    # ── 优先级队列 ──────────────────────────────────

    def _build_priority_queue(self) -> list[str]:
        """构建优先级股票代码队列：自选股优先，信号股次之，去重封顶。"""
        queue: list[str] = []
        seen: set[str] = set()

        # Tier 1: 自选股
        for code in self._get_watchlist_codes():
            if code and code not in seen:
                seen.add(code)
                queue.append(code)

        # Tier 2: 信号股
        for code in self._get_signal_codes():
            if code and code not in seen:
                seen.add(code)
                queue.append(code)

        return queue[: self._max_stocks]

    def _get_watchlist_codes(self) -> list[str]:
        try:
            from ..config import Config

            stocks = Config().load_watchlist(validate=False)
            return [s.get("code") for s in stocks if s.get("code")]
        except Exception:
            logger.warning("analysis_prefetch.watchlist_failed")
            return []

    def _get_signal_codes(self) -> list[str]:
        """从最新全市场扫描中提取高分信号股。"""
        items = self._latest_scan_items()
        codes = []
        for it in items:
            try:
                if float(it.get("score", 0)) >= self._signal_threshold and it.get("code"):
                    codes.append(it["code"])
            except (TypeError, ValueError):
                continue
        return codes

    def _latest_scan_items(self) -> list[dict]:
        """读取最新扫描结果：优先内存 market_scan，其次 scan_service。"""
        try:
            cached = self._cache_mgr.mem_get("market_scan")
            if cached:
                return cached if isinstance(cached, list) else []
        except Exception:
            pass
        # 回退：通过 scan_service 读取（含 DB 兜底）
        if self._scan_service is not None:
            try:
                opp = self._scan_service.get_opportunities()
                return opp.get("items", []) if isinstance(opp, dict) else []
            except Exception:
                logger.warning("analysis_prefetch.scan_failed")
        return []

    # ── 执行抓取 ──────────────────────────────────

    def _refresh_aggregates(self) -> None:
        """强制刷新仪表盘聚合数据（大盘指数/市场情绪/全市场扫描）。

        使用 force_refresh 绕过“非交易时段不调 API”的限制，
        让周末/盘后也能拿到最近交易日的最新数据（每日仅一次，API 开销可控）。
        """
        # 1. 先刷新全市场扫描（信号股来源）
        if self._scan_service is not None:
            try:
                self._scan_service.get_opportunities(force_refresh=True)
                logger.debug("analysis_prefetch.scan_refreshed")
            except Exception:
                logger.warning("analysis_prefetch.scan_refresh_failed")
        # 2. 刷新仪表盘（内部会带动 market_sentiment 一起刷新）
        if self._dashboard_service is not None:
            try:
                self._dashboard_service.get_dashboard_data(force_refresh=True)
                logger.debug("analysis_prefetch.dashboard_refreshed")
            except Exception:
                logger.warning("analysis_prefetch.dashboard_refresh_failed")

    def _run_once(self) -> None:
        """执行一次完整的优先级抓取。"""
        # 先刷新聚合数据，保证后续信号股列表和仪表盘都是最新的
        self._refresh_aggregates()

        queue = self._build_priority_queue()
        if not queue:
            logger.info("analysis_prefetch.empty_queue")
            self._mark_run_today()
            return

        total = len(queue)
        logger.info("analysis_prefetch.run.start", total=total)

        done = 0
        failed = 0
        # 分批
        for batch_start in range(0, total, self._batch_size):
            if self._stop_event.is_set():
                logger.info("analysis_prefetch.interrupted")
                break
            batch = queue[batch_start : batch_start + self._batch_size]
            for code in batch:
                if self._stop_event.is_set():
                    break
                try:
                    self._stock_service.analyze_stock(code)
                    done += 1
                    logger.debug("analysis_prefetch.stock_done", code=code)
                except Exception:
                    failed += 1
                    logger.warning("analysis_prefetch.stock_failed", code=code)
                # 单只间隔
                if self._stock_delay > 0:
                    self._stop_event.wait(self._stock_delay)
            # 批次间隔（最后一批不等待）
            if batch_start + self._batch_size < total and self._batch_delay > 0:
                self._stop_event.wait(self._batch_delay)

        self._mark_run_today()
        logger.info(
            "analysis_prefetch.run.done",
            total=total,
            done=done,
            failed=failed,
        )
