"""谛听 · WatchlistService — 自选股 CRUD + 列表查询"""

from __future__ import annotations

from ...cache import get_market_state
from ._utils import _BaseService, _get_logger

logger = _get_logger()


class WatchlistService(_BaseService):
    """自选股管理服务。"""

    def add_watchlist(self, code: str, name: str = "", market: str = "sz") -> bool:
        """添加自选股。"""
        try:
            return self._db().add(code, name, market)
        except Exception:
            logger.warning("services.watchlist_add.failed", code=code)
            return False

    def remove_watchlist(self, code: str) -> bool:
        """删除自选股。"""
        try:
            return self._db().remove(code)
        except Exception:
            logger.warning("services.watchlist_remove.failed", code=code)
            return False

    def get_watchlist(self, force_refresh: bool = False) -> list[dict]:
        """获取自选股列表（含实时行情）。

        v0.6.5: 支持 force_refresh；盘后/周末不调 API。
        """
        from ...config import Config

        # v0.6.5-bugfix: 非交易时段返回本地自选股 + 缓存最新价格
        state = get_market_state()
        if not state.should_call_api and not force_refresh:
            try:
                stocks = self._db().list()
                if not stocks:
                    cfg = Config()
                    stocks = cfg.load_watchlist(validate=False)
                cm = self._get_cache_mgr()
                results = []
                for s in stocks:
                    code = s.get("code") or s.get("symbol", "")
                    if not code:
                        continue
                    cached = cm.db_get("market_snapshot", code) if cm else None
                    results.append(
                        {
                            "code": code,
                            "name": (cached.get("name") if cached else None) or s.get("name", code),
                            "price": cached.get("price") if cached else None,
                            "change_pct": cached.get("change_pct") if cached else None,
                            "volume": cached.get("volume") if cached else None,
                        }
                    )
                return results
            except Exception:
                return []

        try:
            # 优先从自选股 DB（用户通过 UI 维护）读取，空则回退配置文件的静态列表
            stocks = self._db().list()
            if not stocks:
                cfg = Config()
                stocks = cfg.load_watchlist(validate=False)
            codes = [
                s.get("code") or s.get("symbol", "")
                for s in stocks
                if (s.get("code") or s.get("symbol"))
            ]

            repo = self._build_repo()
            all_quotes: dict = {}
            for i in range(0, len(codes), 4):
                batch = codes[i : i + 4]
                try:
                    all_quotes.update(repo.get_realtime(batch))
                except Exception:
                    logger.warning("watchlist.batch_failed", batch=batch)

            results = []
            for s in stocks:
                code = s.get("code") or s.get("symbol", "")
                if not code:
                    continue
                q = all_quotes.get(code)
                results.append(
                    {
                        "code": code,
                        "name": q.name if q else s.get("name", code),
                        "price": q.price if q else None,
                        "change_pct": q.change_pct if q else None,
                        "volume": q.volume if q else None,
                        "pe": q.pe if q else None,
                    }
                )
            return results
        except Exception:
            logger.warning("services.watchlist.failed")
            return []
