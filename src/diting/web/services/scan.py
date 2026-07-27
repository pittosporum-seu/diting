"""谛听 · ScanService — 选股机会扫描 + 全市场扫描"""

from __future__ import annotations

import json
from datetime import date, datetime

from . import _utils
from ._utils import _BaseService, _get_logger, quick_score
from ...cache.market_state import get_market_state

logger = _get_logger()


class ScanService(_BaseService):
    """选股扫描服务。"""

    # 深度分析候选池大小：quick 初筛后取前 N 名跑全量分析
    CANDIDATE_POOL_SIZE = 100

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
        """选股机会：两层防击穿缓存模型。

        L1: 有全量分析结果 → 用引擎共识分（与详情页一致）
        L2: 无分析结果 → 用 quick_score 占位（页面永不空）
        后台渐进式升级：深度分析完成后自动替换为引擎分。
        """
        # L1 缓存
        if not force_refresh:
            cm = self._get_cache_mgr()
            cached = cm.mem_get_adaptive("opportunities", trading_ttl=120)
            if cached is not None:
                cached["_cache_state"] = "stale"
                return cached

        try:
            state = get_market_state()

            # 1. quick 初筛：全市场 Top N + 自选股
            if state.should_call_api or force_refresh:
                # 交易时段或强制刷新：实时扫描 Top N
                market_candidates = self._scan_market_top20(
                    force=force_refresh, top_n=self.CANDIDATE_POOL_SIZE
                )
            else:
                # 非交易时段：复用上次扫描缓存（含上个交易日收盘价）
                market_candidates = self._get_valid_market_top20(
                    state.last_trade_date
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

            # 5. 分离已分析/未分析，主榜只用引擎分（保证里外一致）
            confirmed = [r for r in analyzed if r["analyzed"]]
            pending = [r for r in analyzed if not r["analyzed"]]
            confirmed.sort(key=lambda x: x["score"], reverse=True)
            pending.sort(key=lambda x: x["quick_score"] or 0, reverse=True)

            # 主榜：已分析的排前面，不足 20 时用 pending 补位
            top20 = confirmed[:20]
            if len(top20) < 20:
                top20 += pending[: 20 - len(top20)]

            from_watchlist = [it for it in top20 if it.get("source") == "watchlist"]
            from_market = [it for it in top20 if it.get("source") != "watchlist"]

            # 统计卡片只统计已分析的（引擎分才有评级意义）
            result = {
                "total": len(analyzed),
                "analyzed_count": len(confirmed),
                "strong_buy": sum(1 for r in confirmed if r["score"] >= 80),
                "buy": sum(1 for r in confirmed if 65 <= r["score"] < 80),
                "watch": sum(1 for r in confirmed if 50 <= r["score"] < 65),
                "avoid": sum(1 for r in confirmed if r["score"] < 35),
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
                "buy": 0,
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
        """两层防击穿：有全量分析用引擎分，没有的用 quick_score 占位。

        页面永远不会空——数据渐进式填充。
        """
        from ...engines.rating import score_to_rating

        results: list[dict] = []
        for cand in candidates:
            code = cand.get("code")
            if not code:
                continue

            analysis = self._get_cached_analysis(code)
            has_analysis = (
                analysis
                and analysis.get("score") is not None
                and not analysis.get("error")
            )

            # 名称：分析缓存 → 候选 → code
            name = code
            if has_analysis:
                for n in (analysis.get("name"), cand.get("name")):
                    if n and n != code:
                        name = n
                        break
            else:
                name = cand.get("name") or code

            # 价格：分析缓存 → 候选 → market_snapshot
            price = (analysis.get("price") if has_analysis else None) or cand.get("price")
            if not price:
                try:
                    snap = self._get_cache_mgr().db_get("market_snapshot", code)
                    if snap and snap.get("price"):
                        price = snap["price"]
                except Exception:
                    pass

            # 评分：有分析用引擎共识分，否则用 quick_score 占位
            if has_analysis:
                score = analysis["score"]
                rating = analysis.get("rating")
                rating_label = analysis.get("rating_label")
                rating_emoji = analysis.get("rating_emoji")
                confidence = analysis.get("confidence")
            else:
                score = cand.get("score") or 0.0
                rating_obj = score_to_rating(score)
                rating = rating_obj.value if hasattr(rating_obj, "value") else str(rating_obj)
                from ._utils import _RATING_CN, _RATING_EMOJI
                rating_label = _RATING_CN.get(rating, rating)
                rating_emoji = _RATING_EMOJI.get(rating, "")
                confidence = 0.3  # 低置信度标记“未全量分析”

            results.append(
                {
                    "code": code,
                    "name": name,
                    "price": price,
                    "change_pct": (analysis.get("change_pct") if has_analysis else None)
                    or cand.get("change_pct")
                    or 0.0,
                    "score": score,
                    "rating": rating,
                    "rating_label": rating_label,
                    "rating_emoji": rating_emoji,
                    "confidence": confidence,
                    "signals": cand.get("signals", []),
                    "quick_score": cand.get("score"),
                    "source": cand.get("source", "market"),
                    "analyzed": has_analysis,
                }
            )
        return results

    def _scan_watchlist(self) -> list[dict]:
        """扫描自选股评分。非交易时段回退 market_snapshot 收盘价。"""
        from ...config import Config
        from ...engines.rating import score_to_rating

        try:
            cfg = Config()
            stocks = cfg.load_watchlist(validate=False)
            if not stocks:
                return []

            state = get_market_state()
            codes = [s.get("code") for s in stocks if s.get("code")]

            # 非交易时段：从 market_snapshot 取上个交易日收盘价
            if not state.should_call_api:
                cm = self._get_cache_mgr()
                results = []
                for s in stocks:
                    code = s.get("code")
                    if not code:
                        continue
                    cached = cm.db_get("market_snapshot", code)
                    if not cached or not cached.get("price"):
                        continue
                    price = cached["price"]
                    change_pct = cached.get("change_pct") or 0.0
                    # 用 snapshot 数据构造简易 quote 进行 quick_score
                    score, signals = quick_score(type("Q", (), {
                        "price": price,
                        "change_pct": change_pct,
                        "open": cached.get("open") or price,
                        "high": cached.get("high") or price,
                        "low": cached.get("low") or price,
                        "volume": cached.get("volume") or 0,
                        "turnover": cached.get("amount") or 0,
                        "pe": None,
                        "name": cached.get("name") or code,
                    })())
                    results.append(
                        {
                            "code": code,
                            "name": cached.get("name") or s.get("name") or code,
                            "price": price,
                            "change_pct": change_pct,
                            "score": score,
                            "signals": signals,
                            "rating": score_to_rating(score),
                            "source": "watchlist",
                        }
                    )
                results.sort(key=lambda x: x["score"], reverse=True)
                return results

            # 交易时段：实时抓取
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
        否则（缺失或过期）→ 全量重扫；重扫失败→ market_snapshot 兜底。
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

        # 缓存缺失或过期 → 尝试全量重扫
        logger.info(
            "services.offhours.rescan",
            scan_date=str(scan_date),
            last_trade=str(last_trade_date),
        )
        result = self._scan_market_top20(force=True)
        if result:
            return result

        # 重扫失败（非交易时段 API 无数据）→ 从 market_snapshot 兜底
        return self._fallback_from_snapshot()

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

    def _fallback_from_snapshot(self, top_n: int = 30) -> list[dict]:
        """非交易时段兜底：从 market_snapshot 读取上个交易日数据，计算 quick_score 并返回 Top N。"""
        import sqlite3

        from ...engines.rating import score_to_rating

        try:
            cm = self._get_cache_mgr()
            conn = sqlite3.connect(str(cm._path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT code, name, price, change_pct, open, high, low, volume, amount "
                "FROM market_snapshot WHERE price > 2 ORDER BY price DESC LIMIT 200"
            ).fetchall()
            conn.close()

            if not rows:
                return []

            results: list[dict] = []
            for r in rows:
                code = r["code"]
                if not code or code[0] not in "0236":
                    continue
                price = r["price"]
                change_pct = r["change_pct"] or 0.0
                # 构造简易 quote 对象给 quick_score
                q = type("Q", (), {
                    "price": price,
                    "change_pct": change_pct,
                    "open": r["open"] or price,
                    "high": r["high"] or price,
                    "low": r["low"] or price,
                    "volume": r["volume"] or 0,
                    "turnover": r["amount"] or 0,
                    "pe": None,
                    "name": r["name"] or code,
                })()
                score, signals = quick_score(q)
                results.append({
                    "code": code,
                    "name": r["name"] or code,
                    "price": price,
                    "change_pct": change_pct,
                    "score": score,
                    "signals": signals,
                    "rating": score_to_rating(score),
                    "source": "market",
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            logger.info("services.offhours.snapshot_fallback", count=len(results))
            return results[:top_n]
        except Exception:
            logger.warning("services.offhours.snapshot_fallback_failed")
            return []

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
