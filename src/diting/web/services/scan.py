"""谛听 · ScanService — 选股机会扫描 + 全市场扫描"""

from __future__ import annotations

import json
from datetime import datetime

from . import _utils
from ._utils import _BaseService, _get_logger, quick_score

logger = _get_logger()


class ScanService(_BaseService):
    """选股扫描服务。"""

    def get_opportunities(self, force_refresh: bool = False) -> dict:
        """选股机会扫描：自选股 + 全市场 Top 20。

        v0.6.5: 支持 force_refresh 绕过 L1 缓存。
        v0.6.5-bugfix: 非交易时段返回空，不触发阻塞扫描。
        """
        from ...cache import get_market_state

        if not force_refresh:
            cm = self._get_cache_mgr()
            cached = cm.mem_get_adaptive("opportunities", trading_ttl=120)
            if cached is not None:
                cached["_cache_state"] = "stale"
                return cached

        # v0.6.5-bugfix: 非交易时段不扫描，避免阻塞事件循环
        state = get_market_state()
        if not state.should_call_api and not force_refresh:
            logger.debug(
                "services.opportunities.api_skipped",
                phase=state.phase,
            )
            empty = {
                "total": 0, "strong_buy": 0, "watch": 0, "avoid": 0,
                "items": [], "from_watchlist": [], "from_market": [],
            }
            self._get_cache_mgr().mem_set("opportunities", empty)
            return empty

        try:
            # Layer 1: 自选股扫描
            watchlist_items = self._scan_watchlist()

            # Layer 2: 全市场扫描 Top 20（缓存 1h）
            market_items = self._scan_market_top20()

            # 合并统计
            all_items = watchlist_items + market_items
            all_items.sort(key=lambda x: x["score"], reverse=True)

            result = {
                "total": len(all_items),
                "strong_buy": sum(1 for r in all_items if r["score"] >= 80),
                "watch": sum(1 for r in all_items if 65 <= r["score"] < 80),
                "avoid": sum(1 for r in all_items if r["score"] < 20),
                "items": all_items,
                "from_watchlist": watchlist_items,
                "from_market": market_items,
            }
            self._get_cache_mgr().mem_set("opportunities", result)
            return result
        except Exception:
            logger.warning("services.opportunities.failed")
            return {
                "total": 0, "strong_buy": 0, "watch": 0, "avoid": 0,
                "items": [], "from_watchlist": [], "from_market": [],
            }

    def _scan_watchlist(self) -> list[dict]:
        """扫描自选股评分。"""
        from ...config import Config
        from ...engines.rating import score_to_rating

        try:
            cfg = Config()
            stocks = cfg.load_watchlist(validate=False)
            if not stocks:
                return []

            codes = [s.get("code") for s in stocks if s.get("code")]
            repo = self._build_repo()
            all_quotes: dict = {}
            for i in range(0, len(codes), 4):
                batch = codes[i:i + 4]
                try:
                    all_quotes.update(repo.get_realtime(batch))
                except Exception:
                    logger.warning("opportunities.batch_failed", batch=batch)

            results = []
            for s in stocks:
                code = s.get("code")
                if not code:
                    continue
                q = all_quotes.get(code)
                if q is None:
                    continue
                score, signals = quick_score(q)
                results.append({
                    "code": code,
                    "name": q.name or code,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "score": score,
                    "signals": signals,
                    "rating": score_to_rating(score),
                    "source": "watchlist",
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results
        except Exception:
            logger.warning("services.scan_watchlist.failed")
            return []

    def _scan_market_top20(self) -> list[dict]:
        """全市场扫描 Top 20：ashare 分批获取行情 → 过滤 → 评分 → 写入 SQLite + 内存。

        每 1h 重新扫描，使用 CacheManager 持久化 market_snapshot + market_scan_cache。
        """
        from ...engines.rating import score_to_rating

        cached = self._get_cache_mgr().mem_get_adaptive("market_scan", trading_ttl=3600)
        if cached is not None:
            return cached

        try:
            stock_list = _utils.load_stock_list()
            if not stock_list:
                return []

            cm = self._get_cache_mgr()
            codes = [s["code"] for s in stock_list if s.get("code")]

            # 过滤：排除 ST/*ST/退/N 股
            _st_patterns = ("ST", "*ST", "退", "N")
            filtered_codes = [
                c for c in codes
                if not any(kw in c for kw in _st_patterns)
            ]

            # 仅保留沪深 A 股（免费源可抓），排除北交所（4/8/9 开头）
            # 否则抓不到北交所股票会触发 AllProvidersFailedError 导致整个扫描失败
            filtered_codes = [
                c for c in filtered_codes
                if c and c[0] in "0236"
            ]

            if not filtered_codes:
                return []

            # 走降级链获取全市场行情
            repo = self._build_repo()
            try:
                all_quotes = repo.get_realtime(filtered_codes)
            except Exception as e:
                logger.warning("services.scan_market.repo_failed", error=str(e))
                return []

            if not all_quotes:
                return []

            batch_id = datetime.now().strftime("%Y-%m-%d-%H%M")
            all_results: list[dict] = []
            snapshot_rows: list[dict] = []
            stock_dict_rows: list[dict] = []

            for code, q in all_quotes.items():
                if q is None or q.price is None or q.price <= 0:
                    continue

                # 过滤价格 <2 元
                if q.price < 2.0:
                    continue

                score, signals = quick_score(q)
                item = {
                    "code": code,
                    "name": q.name or code,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "score": score,
                    "signals": signals,
                    "rating": score_to_rating(score),
                    "source": "market",
                }
                all_results.append(item)

                # 写入 market_snapshot
                snapshot_rows.append({
                    "code": code,
                    "name": q.name or code,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "open": q.open,
                    "high": q.high,
                    "low": q.low,
                    "volume": q.volume,
                    "amount": q.turnover,
                    "turnover": 0.0,
                    "batch_id": batch_id,
                })

                # 写入 stock_dict
                _market = "SZ" if code.startswith(("0", "2", "3")) else (
                    "SH" if code.startswith("6") else "BJ"
                )
                stock_dict_rows.append({
                    "code": code,
                    "name": q.name or code,
                    "pinyin": "",
                    "market": _market,
                    "status": "normal",
                })

            # 写入 SQLite
            if snapshot_rows:
                try:
                    cm.db_set_batch("market_snapshot", snapshot_rows)
                except Exception:
                    logger.warning("services.scan_market.snapshot_write_failed")

            if stock_dict_rows:
                try:
                    cm.db_set_batch("stock_dict", stock_dict_rows)
                except Exception:
                    logger.warning("services.scan_market.stock_dict_write_failed")

            # 评分排序 Top 20
            all_results.sort(key=lambda x: x["score"], reverse=True)
            top20 = all_results[:20]

            # 写入 market_scan_cache
            try:
                scan_date = datetime.now().strftime("%Y-%m-%d")
                scan_time = "morning" if datetime.now().hour < 13 else "afternoon"
                cm.db_set("market_scan_cache", batch_id, {
                    "scan_date": scan_date,
                    "scan_time": scan_time,
                    "top20_json": json.dumps(top20, ensure_ascii=False, default=str),
                })
            except Exception:
                logger.warning("services.scan_market.scan_cache_write_failed")

            cm.mem_set("market_scan", top20)
            logger.info(
                "services.scan_market.done",
                total_scanned=len(all_results),
                snapshot_rows=len(snapshot_rows),
                top20_count=len(top20),
            )
            return top20
        except Exception:
            logger.warning("services.scan_market.failed")
            return []

    def refresh_market_scan(self) -> dict:
        """强制刷新全市场扫描。"""
        self._get_cache_mgr().mem_set("market_scan", None)
        top20 = self._scan_market_top20()
        return {"status": "ok", "top20_count": len(top20)}
