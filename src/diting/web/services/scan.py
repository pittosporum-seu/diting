"""谛听 · ScanService — 选股机会扫描 + 全市场扫描"""

from __future__ import annotations

import json
from datetime import date, datetime

from . import _utils
from ._utils import _BaseService, _get_logger, quick_score

logger = _get_logger()


class ScanService(_BaseService):
    """选股扫描服务。"""

    # 深度分析候选池大小：quick 初筛后取前 N 名跑全量分析
    CANDIDATE_POOL_SIZE = 30

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stock_service = None
        self._deep_analysis_mgr = None

    def set_stock_service(self, stock_service) -> None:
        """注入 StockService 以支持候选股深度分析。"""
        from .deep_analysis import DeepAnalysisManager

        self._stock_service = stock_service
        self._deep_analysis_mgr = DeepAnalysisManager(stock_service)

    def get_deep_progress(self) -> dict | None:
        """返回后台深度分析进度（未注入 stock_service 时为 None）。"""
        if self._deep_analysis_mgr is None:
            return None
        return self._deep_analysis_mgr.get_progress()

    def get_opportunities(self, force_refresh: bool = False) -> dict:
        """选股机会：quick 初筛 → 候选跑全量分析 → 优中选优 Top20。

        排行榜上的每一只都经过全量引擎分析，评分与详情页一致。
        流程：
        1. quick_score 初筛全市场 + 自选股 → 候选池
        2. 后台对候选跑全量 analyze_stock（带进度）
        3. 取已有全量分析结果的候选，按引擎共识分排序取 Top20
        """
        # L1 缓存
        if not force_refresh:
            cm = self._get_cache_mgr()
            cached = cm.mem_get_adaptive("opportunities", trading_ttl=120)
            if cached is not None:
                cached["_cache_state"] = "stale"
                return cached

        try:
            # 1. quick 初筛：全市场 Top N + 自选股
            market_candidates = self._scan_market_top20(
                force=force_refresh, top_n=self.CANDIDATE_POOL_SIZE
            )
            watchlist_items = self._scan_watchlist()

            # 2. 候选集（去重，自选股优先）
            candidates = self._merge_candidates(market_candidates, watchlist_items)

            # 3. 触发后台深度分析（对候选跑全量 analyze_stock）
            if self._deep_analysis_mgr is not None and candidates:
                self._deep_analysis_mgr.start(
                    [c["code"] for c in candidates], force=force_refresh
                )

            # 4. 收集已有全量分析结果的候选（引擎共识分）
            analyzed = self._collect_analyzed(candidates)

            # 5. 优中选优：按引擎分排序取 Top20
            analyzed.sort(key=lambda x: x["score"], reverse=True)
            top20 = analyzed[:20]

            from_watchlist = [it for it in top20 if it.get("source") == "watchlist"]
            from_market = [it for it in top20 if it.get("source") != "watchlist"]

            result = {
                "total": len(analyzed),
                "strong_buy": sum(1 for r in analyzed if r["score"] >= 80),
                "watch": sum(1 for r in analyzed if 65 <= r["score"] < 80),
                "avoid": sum(1 for r in analyzed if r["score"] < 20),
                "items": top20,
                "from_watchlist": from_watchlist,
                "from_market": from_market,
            }
            progress = self.get_deep_progress()
            if progress is not None:
                result["deep_analysis_progress"] = progress
            self._get_cache_mgr().mem_set("opportunities", result)
            return result
        except Exception:
            logger.warning("services.opportunities.failed")
            return {
                "total": 0,
                "strong_buy": 0,
                "watch": 0,
                "avoid": 0,
                "items": [],
                "from_watchlist": [],
                "from_market": [],
            }

    def _merge_candidates(
        self, market_items: list[dict], watchlist_items: list[dict]
    ) -> list[dict]:
        """合并市场候选与自选股，去重（自选股优先保留）。"""
        seen: set[str] = set()
        candidates: list[dict] = []
        # 自选股优先
        for it in watchlist_items:
            code = it.get("code")
            if code and code not in seen:
                seen.add(code)
                it = dict(it)
                it["source"] = "watchlist"
                candidates.append(it)
        for it in market_items:
            code = it.get("code")
            if code and code not in seen:
                seen.add(code)
                it = dict(it)
                it.setdefault("source", "market")
                candidates.append(it)
        return candidates

    def _get_cached_analysis(self, code: str) -> dict | None:
        """读取某只股票的全量分析缓存（内存 → SQLite），无则 None。"""
        import json as _json

        cm = self._get_cache_mgr()
        try:
            cached = cm.mem_get(f"analysis:{code}")
            if cached:
                if isinstance(cached, dict):
                    return cached
                # StockAnalysisResponse dataclass
                from dataclasses import asdict

                return asdict(cached)
        except Exception:
            pass
        try:
            db_row = cm.db_get("stock_analysis_cache", code)
            if db_row and db_row.get("result_json"):
                return _json.loads(db_row["result_json"])
        except Exception:
            pass
        return None

    def _collect_analyzed(self, candidates: list[dict]) -> list[dict]:
        """收集已有全量分析结果的候选，用引擎共识分替换 quick 分。"""
        analyzed: list[dict] = []
        for cand in candidates:
            code = cand.get("code")
            if not code:
                continue
            analysis = self._get_cached_analysis(code)
            if not analysis or analysis.get("score") is None:
                continue  # 尚未完成全量分析，不入榜
            if analysis.get("error"):
                continue
            analyzed.append(
                {
                    "code": code,
                    "name": analysis.get("name") or cand.get("name") or code,
                    "price": analysis.get("price") or cand.get("price"),
                    "change_pct": analysis.get("change_pct", cand.get("change_pct")),
                    "score": analysis["score"],  # 引擎共识分（与详情页同源）
                    "rating": analysis.get("rating"),
                    "rating_label": analysis.get("rating_label"),
                    "rating_emoji": analysis.get("rating_emoji"),
                    "confidence": analysis.get("confidence"),
                    "signals": cand.get("signals", []),  # quick 信号标签
                    "quick_score": cand.get("score"),  # 保留初筛分供参考
                    "source": cand.get("source", "market"),
                    "analyzed": True,
                }
            )
        return analyzed

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
                batch = codes[i : i + 4]
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
                results.append(
                    {
                        "code": code,
                        "name": q.name or code,
                        "price": q.price,
                        "change_pct": q.change_pct,
                        "score": score,
                        "signals": signals,
                        "rating": score_to_rating(score),
                        "source": "watchlist",
                    }
                )

            results.sort(key=lambda x: x["score"], reverse=True)
            return results
        except Exception:
            logger.warning("services.scan_watchlist.failed")
            return []

    def _get_valid_market_top20(self, last_trade_date) -> list[dict]:
        """获取有效的市场 Top20。

        缓存扫描结果不早于最近交易日（即之后没有新开盘）→ 复用；
        否则（缺失或过期）→ 全量重扫。
        """
        items, scan_date = self._read_latest_scan()

        # 缓存有效：扫描日 >= 最近交易日（没有更新的交易发生）
        if (
            items
            and scan_date is not None
            and last_trade_date is not None
            and scan_date >= last_trade_date
        ):
            logger.debug(
                "services.offhours.scan_reused",
                scan_date=str(scan_date),
                last_trade=str(last_trade_date),
            )
            return items

        # 缓存缺失或过期 → 全量重扫
        logger.info(
            "services.offhours.rescan",
            scan_date=str(scan_date),
            last_trade=str(last_trade_date),
        )
        return self._scan_market_top20(force=True)

    def _read_latest_scan(self) -> tuple[list[dict], date | None]:
        """读最近一次扫描结果及其扫描日期（SQLite 优先，内存兑底）。"""
        import json as _json
        from datetime import date as _date

        cm = self._get_cache_mgr()
        # 1. SQLite 持久化（带 scan_date）
        try:
            row = cm.db_get_latest("market_scan_cache")
            if row and row.get("top20_json"):
                items = _json.loads(row["top20_json"])
                scan_date = None
                if row.get("scan_date"):
                    try:
                        scan_date = _date.fromisoformat(str(row["scan_date"])[:10])
                    except (ValueError, TypeError):
                        pass
                if isinstance(items, list):
                    return items, scan_date
        except Exception:
            logger.warning("services.offhours.scan_db_failed")
        # 2. 内存缓存（无日期，视为未知）
        try:
            cached = cm.mem_get("market_scan")
            if cached and isinstance(cached, list):
                return cached, None
        except Exception:
            pass
        return [], None

    def _scan_market_top20(self, force: bool = False, top_n: int = 20) -> list[dict]:
        """全市场扫描：ashare 分批获取行情 → 过滤 → quick_score 评分 → 写入 SQLite + 内存。

        每 1h 重新扫描，使用 CacheManager 持久化 market_snapshot + market_scan_cache。
        force=True 时跳过内存缓存检查，强制重扫。
        top_n: 返回 quick_score 排名前 top_n 名（作为深度分析候选池）。
        """
        from ...engines.rating import score_to_rating

        if not force:
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
            filtered_codes = [c for c in codes if not any(kw in c for kw in _st_patterns)]

            # 仅保留沪深 A 股（免费源可抓），排除北交所（4/8/9 开头）
            # 否则抓不到北交所股票会触发 AllProvidersFailedError 导致整个扫描失败
            filtered_codes = [c for c in filtered_codes if c and c[0] in "0236"]

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
                snapshot_rows.append(
                    {
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
                    }
                )

                # 写入 stock_dict
                _market = (
                    "SZ"
                    if code.startswith(("0", "2", "3"))
                    else ("SH" if code.startswith("6") else "BJ")
                )
                stock_dict_rows.append(
                    {
                        "code": code,
                        "name": q.name or code,
                        "pinyin": "",
                        "market": _market,
                        "status": "normal",
                    }
                )

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

            # 评分排序，取前 top_n 名作为深度分析候选池
            all_results.sort(key=lambda x: x["score"], reverse=True)
            top20 = all_results[:top_n]

            # 写入 market_scan_cache
            try:
                scan_date = datetime.now().strftime("%Y-%m-%d")
                scan_time = "morning" if datetime.now().hour < 13 else "afternoon"
                cm.db_set(
                    "market_scan_cache",
                    batch_id,
                    {
                        "scan_date": scan_date,
                        "scan_time": scan_time,
                        "top20_json": json.dumps(top20, ensure_ascii=False, default=str),
                    },
                )
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
