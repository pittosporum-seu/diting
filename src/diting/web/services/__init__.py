"""谛听 · Web 服务层 — 按职责拆分为 5 个独立模块。

替代原先 1400+ 行的巨型 services.py。

AnalysisService 是向后兼容的复合类，聚合所有子服务。
新代码推荐直接引用各独立 Service 类。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ...cache import CacheManager
from ...ports import DataGateway
from ...schema import FreshnessInfo, StockAnalysisResponse
from ...storage import WatchlistDB
from ._utils import _BaseService
from .dashboard import DashboardService
from .scan import ScanService
from .stock import StockService
from .watchlist import WatchlistService

__all__ = [
    "AnalysisService",
    "StockService",
    "DashboardService",
    "WatchlistService",
    "ScanService",
]


class AnalysisService(_BaseService):
    """向后兼容的复合服务类。

    聚合所有子服务的接口，保持与旧 services.py 相同的调用方式。
    新代码推荐直接引用各独立 Service 类。
    """

    def __init__(
        self,
        *,
        cache_mgr: CacheManager | None = None,
        watchlist_db: WatchlistDB | None = None,
        settings: dict | None = None,
        repo_factory: Callable[[], Any] | None = None,
        data_gateway: DataGateway | None = None,
    ):
        super().__init__(
            cache_mgr=cache_mgr,
            watchlist_db=watchlist_db,
            settings=settings,
            repo_factory=repo_factory,
            data_gateway=data_gateway,
        )
        shared = {
            "cache_mgr": cache_mgr,
            "watchlist_db": watchlist_db,
            "settings": self._settings,
            "repo_factory": repo_factory,
            "data_gateway": data_gateway,
        }
        self._stock = StockService(**shared)
        self._dashboard = DashboardService(**shared)
        self._watchlist = WatchlistService(**shared)
        self._scan = ScanService(**shared)
        # 注入 StockService 给 ScanService，支持候选股深度分析
        self._scan.set_stock_service(self._stock)

    @property
    def _cache_mgr(self):
        return self.__cache_mgr

    @_cache_mgr.setter
    def _cache_mgr(self, value):
        self.__cache_mgr = value
        for service in self._children():
            service._cache_mgr = value

    @property
    def _watchlist_db(self):
        return self.__watchlist_db

    @_watchlist_db.setter
    def _watchlist_db(self, value):
        self.__watchlist_db = value
        for service in self._children():
            service._watchlist_db = value

    def _children(self):
        return tuple(
            service
            for name in ("_stock", "_dashboard", "_watchlist", "_scan")
            if (service := getattr(self, name, None)) is not None
        )

    # ── StockService 代理 ──

    def analyze_stock(self, code: str, force: bool = False) -> StockAnalysisResponse:
        return self._stock.analyze_stock(code, force=force)

    def get_realtime(self, code: str, force_refresh: bool = False):
        return self._stock.get_realtime(code, force_refresh)

    def get_historical(self, code: str, days: int = 250):
        return self._stock.get_historical(code, days)

    def get_stock_name(self, code: str) -> str | None:
        return self._stock.get_stock_name(code)

    def search_stock(self, keyword: str) -> list[dict]:
        return self._stock.search_stock(keyword)

    def get_stock_list(self) -> list[dict]:
        return self._stock.get_stock_list()

    # ── DashboardService 代理 ──

    def get_dashboard_data(self) -> tuple[dict, FreshnessInfo]:
        return self._dashboard.get_dashboard_data()

    def get_market_sentiment(self) -> dict:
        return self._dashboard.get_market_sentiment()

    # ── WatchlistService 代理 ──

    def get_watchlist(self, force_refresh: bool = False) -> list[dict]:
        return self._watchlist.get_watchlist(force_refresh)

    def add_watchlist(self, code: str, name: str = "", market: str = "sz") -> bool:
        return self._watchlist.add_watchlist(code, name, market)

    def remove_watchlist(self, code: str) -> bool:
        return self._watchlist.remove_watchlist(code)

    # ── ScanService 代理 ──

    def get_opportunities(self) -> dict:
        return self._scan.get_opportunities()

    def market_scan(self):
        return self._scan.market_scan()

    def refresh_market_scan(self) -> dict:
        return self._scan.refresh_market_scan()

    # ── Settings（委托给 DashboardService） ──

    def get_settings(self) -> dict:
        return self._dashboard.get_settings()

    def save_settings(self, data: dict) -> dict:
        return self._dashboard.save_settings(data)

    # ── 系统管理 ──

    def health_check(self) -> dict:
        return {"status": "ok", "service": "diting-web"}

    def get_cache_stats(self) -> dict:
        cm = self._get_cache_mgr()
        return {
            "memory_cache": cm.mem_stats(),
            "sqlite_cache": cm.db_stats(),
            "updated_at": str(datetime.now()),
        }

    def clear_cache(self) -> dict:
        cm = self._get_cache_mgr()
        cm.clear_all()
        return {"status": "ok", "message": "所有缓存已清除"}
