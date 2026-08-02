"""谛听 · ScanService — 选股机会扫描 + 全市场扫描"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from ...cache.market_state import get_market_state
from . import _utils
from ._utils import _BaseService, _get_logger, coarse_score, quick_score

logger = _get_logger()


class ScanService(_BaseService):
    """选股扫描服务。"""

    # 深度分析候选池大小：quick 初筛后取前 N 名跑全量分析
    CANDIDATE_POOL_SIZE = 100
    # 两段式初筛粗筛池：实时快筛取前 N 只，再取历史精算技术因子
    COARSE_POOL_SIZE = 1200

    def _get_historical(self, code: str, days: int = 120):
        """取历史日线（三级缓存：内存→SQLite→网络）。

        日线数据一天只变一次（收盘后），用 SQLite 持久缓存大幅减少网络请求。
        首次扫描后，后续扫描 1200 只全命中 DB（ms 级）。
        """
        try:
            repo = self._build_repo()
            end = date.today()
            start = end - timedelta(days=days)
            return repo.get_historical(code, start, end)
        except Exception:
            return None

    # ── 因子缓存（避免每次扫描重复解析 DataFrame）───────────

    def _get_cached_factors(self, cm, code: str) -> dict | None:
        """从 DB 读取缓存因子（当天有效）。"""
        import json as _json

        try:
            with cm._lock:
                conn = cm._connect()
                try:
                    row = conn.execute(
                        "SELECT factors_json, cached_date FROM factors_cache WHERE code=?",
                        (code,),
                    ).fetchone()
                finally:
                    conn.close()
            if row is None:
                return None
            fj, cd = row
            # 当天缓存有效（日线一天一变）
            if cd != date.today().isoformat():
                return None
            return _json.loads(fj)
        except Exception:
            return None

    def _set_cached_factors(self, cm, code: str, factors: dict) -> None:
        """将因子缓存到 DB。"""
        import json as _json

        try:
            with cm._lock:
                conn = cm._connect()
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO factors_cache "
                        "(code, factors_json, cached_date) VALUES (?,?,?)",
                        (code, _json.dumps(factors), date.today().isoformat()),
                    )
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

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
                market_candidates = self._get_valid_market_top20(state.last_trade_date)
            watchlist_items = self._scan_watchlist()

            # 2. 候选集（去重，自选股优先）
            candidates = self._merge_candidates(market_candidates, watchlist_items)

            # 3. 触发后台深度分析（对候选跑全量 analyze_stock）
            if self._deep_analysis_mgr is not None and candidates:
                self._deep_analysis_mgr.start([c["code"] for c in candidates], force=force_refresh)

            # 4. 收集已有全量分析结果的候选（引擎共识分）
            analyzed = self._collect_analyzed(candidates)

            # 5. 分离已分析/未分析，主榜只用引擎分（保证里外一致）
            confirmed = [r for r in analyzed if r["analyzed"]]
            confirmed.sort(key=lambda x: x["score"], reverse=True)

            # 主榜只展示已完成分析的结果；禁止用 quick_score 补位。
            top20 = confirmed[:20]

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
                analysis and analysis.get("score") is not None and not analysis.get("error")
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

            # 价格只来自已分析结果或当前网关候选数据。
            price = (analysis.get("price") if has_analysis else None) or cand.get("price")

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
        """扫描自选股评分；行情缓存和降级由 Data Gateway 负责。"""
        from ...config import Config
        from ...engines.rating import score_to_rating

        try:
            cfg = Config()
            stocks = cfg.load_watchlist(validate=False)
            if not stocks:
                return []

            codes = [s.get("code") for s in stocks if s.get("code")]

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
        否则（缺失或过期）→ 全量重扫；网关无数据则返回空结果。
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

        # 网关已经负责 stale-if-error；不得回退旧数据表。
        return []

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

        每 1h 重新扫描；原始行情统一由 Data Gateway 缓存。
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

            for code, q in all_quotes.items():
                if q is None or q.price is None or q.price <= 0:
                    continue

                # 过滤价格 <2 元
                if q.price < 2.0:
                    continue

                # 粗筛分（方向中性，仅用于选精筛池）；quick_score 只取信号标签供展示
                coarse = coarse_score(q)
                _, signals = quick_score(q)
                item = {
                    "code": code,
                    "name": q.name or code,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "score": coarse,
                    "signals": signals,
                    "rating": score_to_rating(coarse),
                    "source": "market",
                }
                all_results.append(item)

            # ── 两段式数据驱动初筛 ──
            # Stage 1: 实时粗筛，按 quick_score 取前 COARSE_POOL_SIZE
            all_results.sort(key=lambda x: x["score"], reverse=True)
            coarse = all_results[: self.COARSE_POOL_SIZE]

            # Stage 2: 并发取粗筛池的技术因子（优先用 DB 缓存因子，避免重复解析 DataFrame）
            from concurrent.futures import ThreadPoolExecutor

            cm = self._get_cache_mgr()

            def _factors_for(code: str):
                # 先查因子缓存（极快，纯 JSON）
                f = self._get_cached_factors(cm, code)
                if f is not None:
                    return code, f if f else None  # 空 dict = 已知失败
                # 未命中：取历史算因子 + 回写因子缓存
                hist = self._get_historical(code)
                f = _utils.technical_factors(hist)
                # 无论成功失败都缓存（失败存空 dict，当天不重试）
                self._set_cached_factors(cm, code, f or {})
                return code, f

            factor_map: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix="scan_hist") as pool:
                for code, f in pool.map(_factors_for, [it["code"] for it in coarse]):
                    if f:
                        factor_map[code] = f
            if factor_map:
                dd_scores = _utils.rank_score_pool(factor_map)
                ranked = []
                for item in coarse:
                    if item["code"] in dd_scores:
                        item["score"] = dd_scores[item["code"]]
                        item["source"] = "market_dd"
                        ranked.append(item)
                ranked.sort(key=lambda x: x["score"], reverse=True)
                top20 = ranked[:top_n]
            else:
                logger.warning("services.scan_market.dd_fallback")
                top20 = coarse[:top_n]

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
