"""谛听 · Web 服务层 — 按职责拆分为 5 个独立模块。

替代原先 1400+ 行的巨型 services.py。

AnalysisService 是向后兼容的复合类，聚合所有子服务。
新代码推荐直接引用各独立 Service 类。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ...cache import CacheManager
from ...data.repository import MarketDataRepository
from ...schema import StockAnalysisResponse
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
        repo_factory: Callable[[], MarketDataRepository] | None = None,
    ):
        super().__init__(
            cache_mgr=cache_mgr,
            watchlist_db=watchlist_db,
            settings=settings,
            repo_factory=repo_factory,
        )
        shared = {
            "cache_mgr": cache_mgr,
            "watchlist_db": watchlist_db,
            "settings": self._settings,
            "repo_factory": repo_factory,
        }
        self._stock = StockService(**shared)
        self._dashboard = DashboardService(**shared)
        self._watchlist = WatchlistService(**shared)
        self._scan = ScanService(**shared)

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

    def analyze_stock(self, code: str) -> StockAnalysisResponse:
        return self._stock.analyze_stock(code)

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

    def get_dashboard_data(self) -> dict:
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

    # ── Settings（内置，无独立 service） ──

    def get_settings(self) -> dict:
        """获取配置信息。"""
        from diting.config import Config

        cfg = Config()
        saved = self._load_saved_settings()
        mx_key = cfg.get("MX_APIKEY")

        provider_toggles = []
        for pk in (
            "provider_eltdx", "provider_ashare",
            "provider_mxdata", "provider_akshare",
        ):
            label_map = {
                "eltdx": "eltdx (通达信直连)",
                "ashare": "ashare (新浪/腾讯)",
                "mxdata": "mx-data (东方财富)",
                "akshare": "akshare (免费兜底)",
            }
            short = pk.replace("provider_", "").replace("mxdata", "mx-data").upper()
            provider_toggles.append({
                "key": pk,
                "label": label_map.get(pk.replace("provider_", ""), short),
                "enabled": saved.get(pk, "1") == "1",
                "requires_api_key": pk in ("provider_eltdx", "provider_mxdata"),
                "api_key_available": bool(mx_key),
            })

        engine_names = ["wyckoff", "buffett", "can_slim", "volume_profile", "vmd_rsi", "verdict"]
        engine_toggles = []
        for en in engine_names:
            engine_toggles.append({
                "key": f"engine_{en}",
                "label": en.replace("_", " ").title(),
                "enabled": saved.get(f"engine_{en}", "1") == "1",
            })

        ai_model = saved.get("ai_model", "")

        return {
            "provider_toggles": provider_toggles,
            "engine_toggles": engine_toggles,
            "ai_model_available": bool(ai_model) or bool(mx_key),
            "ai_model": ai_model,
            "mx_api_key_available": bool(mx_key),
            "watchlist_size": len(self._watchlist.get_watchlist()),
        }

    def save_settings(self, data: dict) -> dict:
        """保存设置。"""
        db = self._db()
        accepted = 0
        for key, val in (data or {}).items():
            if key.startswith("_") or key == "status":
                continue
            try:
                db.set_setting(key, str(val))
                accepted += 1
            except Exception:
                pass
        return {"status": "ok", "saved": accepted}

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
