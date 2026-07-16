"""谛听 · StockService — 个股分析、实时行情、历史数据"""

# ruff: noqa: E501

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta

from ...cache import get_market_state
from ...data.providers.east_money import EastMoneyProvider
from ...schema import StockAnalysisResponse
from ._utils import (
    _RATING_CN,
    _RATING_EMOJI,
    _BaseService,
    _get_logger,
    clean_numpy,
    extract_chart_arrays,
)

logger = _get_logger()


class StockService(_BaseService):
    """个股分析服务。"""

    # ── Realtime ────────────────────────────────────

    def get_stock_name(self, code: str) -> str | None:
        """根据股票代码获取股票名称。"""
        try:
            quote = self.get_realtime(code)
            return quote.name if quote else None
        except Exception:
            logger.warning("services.stock_name.failed", code=code)
            return None

    def get_realtime(self, code: str, force_refresh: bool = False):
        """获取单只股票实时行情（L1 内存 → L2 SQLite → API）。

        v0.6.5: 整合 MarketState，盘后/周末不调 API；支持 force_refresh。
        """
        from ...schema import RealtimeQuote

        state = get_market_state()

        # L1: 内存 TTL
        if not force_refresh:
            cm = self._get_cache_mgr()
            cached = cm.mem_get_adaptive(f"realtime:{code}", trading_ttl=30)
            if cached is not None:
                return cached

        # L2: SQLite watchlist_cache
        try:
            cm = self._get_cache_mgr()
            db_row = cm.db_get("watchlist_cache", code)
            if db_row:
                quote = RealtimeQuote(
                    symbol=code,
                    name=db_row.get("name", code),
                    price=db_row.get("price") or 0.0,
                    change_pct=db_row.get("change_pct") or 0.0,
                    open=db_row.get("open") or 0.0,
                    high=db_row.get("high") or 0.0,
                    low=db_row.get("low") or 0.0,
                    volume=int(db_row.get("volume") or 0),
                    turnover=db_row.get("amount") or 0.0,
                    pe=db_row.get("pe"),
                    pb=db_row.get("pb"),
                    total_mv=db_row.get("total_mv"),
                    timestamp=datetime.now(),
                )
                cm.mem_set(f"realtime:{code}", quote)
                # v0.6.5: L2 命中后后台异步刷新 API（仅 TRADING 状态）
                if state.is_trading and not force_refresh:
                    self._async_refresh_realtime(code)
                return quote
        except Exception:
            pass

        # v0.6.5: CLOSED/WEEKEND → 不调 API，返回兜底 RealtimeQuote
        if not state.should_call_api and not force_refresh:
            logger.debug(
                "services.realtime.api_skipped",
                code=code,
                phase=state.phase,
            )
            return RealtimeQuote(
                symbol=code,
                name=code,
                price=0.0,
                change_pct=0.0,
                open=0.0,
                high=0.0,
                low=0.0,
                volume=0,
                turnover=0.0,
                timestamp=datetime.now(),
            )

        # L3: API
        try:
            repo = self._build_repo()
            quotes = repo.get_realtime([code])
            result = quotes.get(code)
            if result:
                self._get_cache_mgr().mem_set(f"realtime:{code}", result)
                # 写入 SQLite
                try:
                    cm = self._get_cache_mgr()
                    cm.db_set("watchlist_cache", code, {
                        "code": code,
                        "name": result.name,
                        "price": result.price,
                        "change_pct": result.change_pct,
                        "high": result.high,
                        "low": result.low,
                        "volume": result.volume,
                        "amount": result.turnover,
                        "pe": result.pe,
                        "pb": result.pb,
                        "total_mv": result.total_mv,
                        "score": 0,
                    })
                except Exception:
                    pass
            return result
        except Exception:
            logger.warning("services.realtime.failed", code=code)
            return None

    def _async_refresh_realtime(self, code: str) -> None:
        """后台异步刷新单只股票实时行情。"""
        def _refresh():
            try:
                self.get_realtime(code, force_refresh=True)
            except Exception:
                pass
        t = threading.Thread(target=_refresh, daemon=True, name=f"async-realtime-{code}")
        t.start()

    # ── Historical ──────────────────────────────────

    def get_historical(self, code: str, days: int = 250):
        """获取历史日线行情。"""
        cache_key = f"{code}:{days}"
        cm = self._get_cache_mgr()
        cached = cm.mem_get_adaptive(f"historical:{cache_key}", trading_ttl=600)
        if cached is not None:
            return cached
        try:
            repo = self._build_repo()
            end = date.today()
            start = end - timedelta(days=days)
            result = repo.get_historical(code, start, end)
            cm.mem_set(f"historical:{cache_key}", result)
            return result
        except Exception:
            logger.warning("services.historical.failed", code=code)
            return None

    # ── Full Analysis ───────────────────────────────

    def analyze_stock(self, code: str) -> StockAnalysisResponse:
        """个股全流程分析，返回模板/API 通用数据结构。

        Returns:
            StockAnalysisResponse dataclass（非裸 dict）。
        """
        from ...schema import (
            AnalysisContext,
            ConsensusScore,
            PipelineResult,
            StockAnalysisResponse,
            TechnicalSignals,
        )

        # L1: 内存 TTL
        cm = self._get_cache_mgr()
        cached = cm.mem_get_adaptive(f"analysis:{code}", trading_ttl=60)
        if cached is not None:
            if isinstance(cached, StockAnalysisResponse):
                cached._cache_state = "stale"
                return cached
            # 兼容旧 dict 缓存
            if isinstance(cached, dict):
                cached["_cache_state"] = "stale"
                return _dict_to_response(cached)
        # L2: SQLite stock_analysis_cache
        try:
            db_row = cm.db_get("stock_analysis_cache", code)
            if db_row and db_row.get("result_json"):
                import json as _json
                result = _json.loads(db_row["result_json"])
                result.setdefault("chart_data", {})
                result.setdefault("signals", None)
                result.setdefault("_historical", None)
                result["_cache_state"] = "stale"
                cm.mem_set(f"analysis:{code}", result)
                return _dict_to_response(result)
        except Exception:
            pass

        result: dict = {
            "code": code,
            "name": code,
            "price": 0.0,
            "change_pct": 0.0,
            "pe": None,
            "pb": None,
            "total_mv": None,
            "volume": 0,
            "turnover": 0.0,
            "score": 50,
            "rating": "hold",
            "rating_label": "建议观望",
            "rating_emoji": "⚪",
            "confidence": 0.5,
            "engine_scores": [],
            "engine_skipped": [],
            "bull_reasons": [],
            "bear_reasons": [],
            "rsi_display": "-",
            "macd_display": "-",
            "chart_data": {},
            "signals": None,
            "error": None,
            "_cache_state": "fresh",
        }

        # ── realtime ──
        quote = self.get_realtime(code)
        if quote is None:
            result["error"] = f"未找到股票 {code}"
            return _dict_to_response(result)

        if quote.price == 0.0:
            result["name"] = code
            result["data_source"] = "historical_only"
        else:
            result["name"] = quote.name or code
            result["price"] = quote.price
            result["change_pct"] = quote.change_pct or 0
            result["pe"] = quote.pe
            result["pb"] = quote.pb
            result["total_mv"] = quote.total_mv
            result["volume"] = quote.volume
            result["turnover"] = quote.turnover

        # ── historical ──
        historical = self.get_historical(code)
        result["_historical"] = historical

        # ── chart arrays ──
        chart_data: dict = {}
        if historical and historical.df is not None:
            try:
                chart_data = extract_chart_arrays(historical.df)
            except Exception:
                pass
        result["chart_data"] = chart_data

        # ── technical signals ──
        sig: TechnicalSignals | None = None
        if historical and historical.df is not None:
            try:
                from ...signals.technical import TechnicalCalculator
                sig = TechnicalCalculator.calculate(historical)
            except Exception:
                pass
        result["signals"] = sig

        if sig:
            result["rsi_display"] = f"{sig.rsi_14:.1f}"
            result["macd_display"] = f"{sig.macd:.3f}"

        # ── analysis pipeline ──
        from ...engines.registry import discover_engines
        from ...pipeline.consensus import ConsensusEngine
        from ...pipeline.runner import AnalysisPipeline

        saved = self._load_saved_settings()
        all_engines = ["wyckoff", "buffett", "can_slim", "volume_profile", "vmd_rsi", "verdict"]
        discovered = discover_engines()
        available_engines = set(discovered or all_engines)
        engine_names = [
            en for en in all_engines
            if en in available_engines and saved.get(f"engine_{en}", "1") == "1"
        ]
        enabled_engine_names = list(engine_names)
        engine_skipped: list[dict[str, str]] = []

        def record_skipped(names: list[str], reason: str) -> None:
            """按启用顺序记录一次跳过原因，避免同一引擎重复归类。"""
            existing = {item["engine_name"]: item for item in engine_skipped}
            for engine_name in enabled_engine_names:
                if engine_name not in names:
                    continue
                if engine_name in existing:
                    if reason == "timeout":
                        existing[engine_name]["reason"] = reason
                    continue
                item = {"engine_name": engine_name, "reason": reason}
                engine_skipped.append(item)
                existing[engine_name] = item

        # AI 引擎降级：无 API key 时跳过 AI 引擎
        _ai_engines = {"wyckoff", "buffett", "can_slim"}
        api_key = os.environ.get("AI_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            skipped = [en for en in engine_names if en in _ai_engines]
            engine_names = [en for en in engine_names if en not in _ai_engines]
            record_skipped(skipped, "no_api_key")
            if skipped:
                logger.info(
                    "services.ai_fallback",
                    code=code,
                    skipped=skipped,
                    remaining=engine_names,
                )

        # v0.6.6: 非交易时段跳过 AI 引擎
        state = get_market_state()
        if not state.should_call_api:
            _skipped_ai = [en for en in engine_names if en in _ai_engines]
            engine_names = [en for en in engine_names if en not in _ai_engines]
            record_skipped(_skipped_ai, "non_trading_hours")
            if _skipped_ai:
                logger.info(
                    "services.ai_market_skip",
                    code=code,
                    phase=state.phase,
                    skipped=_skipped_ai,
                    remaining=engine_names,
                )

        # ── VMD 分解 ──
        vmd = None
        if historical and historical.df is not None and not historical.df.empty:
            try:
                from ...signals.vmd import VMDDecomposer
                close_col = "close" if "close" in historical.df.columns else "收盘价"
                if close_col in historical.df.columns:
                    close_vals = historical.df[close_col].dropna().values
                    if len(close_vals) >= 60:
                        vmd = VMDDecomposer.decompose(close_vals, symbol=code)
            except Exception:
                logger.debug("services.vmd.skip", code=code)

        # ── 资金流向（优先用 EastMoney 直连）──
        fund_flow = None
        try:
            em = EastMoneyProvider()
            fund_flow = em.fetch_fund_flow(code)
        except Exception:
            logger.debug("services.fund_flow.skip", code=code)

        ctx_obj = AnalysisContext(
            symbol=code, realtime=quote, historical=historical,
            signals=sig, vmd=vmd, fund_flow=fund_flow,
        )

        consensus: ConsensusScore | None = None
        engine_scores: list[dict] = []
        bull_reasons: list[str] = []
        bear_reasons: list[str] = []

        try:
            pipeline = AnalysisPipeline(engine_names=engine_names)
            pipe_result: PipelineResult = pipeline.run([ctx_obj])
            ce = ConsensusEngine()
            consensus = ce.fuse(code, pipe_result.results.get(code, []))

            for r in pipe_result.results.get(code, []):
                if r.error:
                    record_skipped([r.engine_name], "error")
                    continue
                engine_scores.append({
                    "name": r.engine_name,
                    "score": r.score,
                    "rating": r.rating.value,
                    "rating_cn": _RATING_CN.get(r.rating.value, r.rating.value),
                    "confidence": r.confidence,
                })
                metadata = r.metadata if isinstance(r.metadata, dict) else {}
                for reason in metadata.get("bull_reasons", []) or []:
                    text = str(reason).strip()
                    if text and text not in bull_reasons:
                        bull_reasons.append(text)
                for reason in metadata.get("bear_reasons", []) or []:
                    text = str(reason).strip()
                    if text and text not in bear_reasons:
                        bear_reasons.append(text)
            for error in pipe_result.errors:
                engine_name = str(error.get("engine", ""))
                error_text = str(error.get("error", "")).lower()
                reason = "timeout" if "timeout" in error_text or "timed out" in error_text else "error"
                record_skipped([engine_name], reason)
        except Exception as exc:
            record_skipped(engine_names, "error")
            logger.warning("services.pipeline.failed", code=code, error=str(exc))
            consensus = None

        if consensus is None:
            consensus = ConsensusEngine().fuse(code, [])

        # ── quick score fallback ──
        quick_score_val = 50
        if sig:
            rsi_val = sig.rsi_14
            if rsi_val < 25:
                quick_score_val += 20
            elif rsi_val < 35:
                quick_score_val += 10
            elif rsi_val > 75:
                quick_score_val -= 20
            elif rsi_val > 65:
                quick_score_val -= 10

        final_score = consensus.weighted_score if engine_scores else quick_score_val

        successful_engines = {item["name"] for item in engine_scores}
        engine_skipped = [
            item for item in engine_skipped
            if item["engine_name"] not in successful_engines
        ]
        engine_order = {name: index for index, name in enumerate(enabled_engine_names)}
        engine_scores.sort(key=lambda item: engine_order.get(item["name"], len(engine_order)))
        engine_skipped.sort(
            key=lambda item: engine_order.get(item["engine_name"], len(engine_order))
        )
        result["engine_scores"] = engine_scores
        result["engine_skipped"] = engine_skipped
        result["bull_reasons"] = bull_reasons
        result["bear_reasons"] = bear_reasons
        result["score"] = final_score
        result["rating"] = consensus.rating.value
        result["rating_label"] = _RATING_CN.get(consensus.rating.value, consensus.rating.value)
        result["rating_emoji"] = _RATING_EMOJI.get(consensus.rating.value, "")
        result["confidence"] = consensus.confidence

        # signals 保留原始 dataclass（routes.py 处理序列化）
        _sig = result.pop("signals", None)
        result = clean_numpy(result)
        if _sig is not None:
            result["signals"] = _sig
        cm = self._get_cache_mgr()
        response = _dict_to_response(result)
        cm.mem_set(f"analysis:{code}", response)
        # 写入 SQLite
        try:
            import json as _json
            serializable = clean_numpy(result)
            l2_ttl = 30 if (state and state.should_call_api) else 1440
            cm.db_set("stock_analysis_cache", code, {
                "code": code,
                "result_json": _json.dumps(serializable, default=str, ensure_ascii=False),
                "expires_at": (datetime.now() + timedelta(minutes=l2_ttl)).isoformat(),
            })
        except Exception:
            pass
        return response


    # ── Search & List ───────────────────────────────

    def search_stock(self, keyword: str) -> list[dict]:
        """搜索全市场股票，支持代码、名称、拼音和首字母匹配。"""
        keyword = keyword.strip().lower()
        if not keyword:
            return []

        matches: list[tuple[int, int, dict]] = []
        for stock in self.get_stock_list():
            code = str(stock.get("code", ""))
            name = str(stock.get("name", ""))
            pinyin = str(stock.get("pinyin", "")).lower()
            initial = str(stock.get("initial", "")).lower()

            if keyword == code:
                rank = 0
            elif code.startswith(keyword):
                rank = 1
            elif keyword == name.lower():
                rank = 2
            elif keyword in name.lower():
                rank = 3
            elif pinyin.startswith(keyword):
                rank = 4
            elif initial.startswith(keyword):
                rank = 5
            else:
                continue

            result = dict(stock)
            result.setdefault("market", self._market_for_code(code))
            matches.append((rank, len(name), result))

        matches.sort(key=lambda item: (item[0], item[1], item[2]["code"]))
        return [item[2] for item in matches[:10]]

    @staticmethod
    def _market_for_code(code: str) -> str:
        """Infer the exchange used by existing API search results."""
        return "sh" if code.startswith(("5", "6", "9")) else "sz"

    def get_stock_list(self) -> list[dict]:
        """返回全市场 A 股股票列表 [{code, name, pinyin, initial}]。"""
        from ._utils import load_stock_list

        return load_stock_list()


# ── Module-level helper ──────────────────────────

def _dict_to_response(d: dict) -> StockAnalysisResponse:
    """将内部 dict 转换为 StockAnalysisResponse dataclass。"""
    from ...schema import EngineScoreItem, EngineSkipInfo, StockAnalysisResponse

    # 处理 engine_scores：dict 键名 → EngineScoreItem
    engine_scores = [
        EngineScoreItem(
            engine_name=es.get("engine_name", es.get("name", "")),
            score=es.get("score", 50.0),
            rating=es.get("rating", "hold"),
            rating_label=es.get("rating_cn", es.get("rating", "hold")),
            confidence=es.get("confidence", 0.5),
        )
        for es in d.get("engine_scores", []) or []
    ]
    engine_skipped = [
        EngineSkipInfo(
            engine_name=item.get("engine_name", ""),
            reason=item.get("reason", "error"),
        )
        for item in d.get("engine_skipped", []) or []
    ]

    # 处理 signals → signals_summary
    sig = d.get("signals")
    signals_summary: dict | None = None
    if sig is not None and not isinstance(sig, dict):
        signals_summary = {
            "rsi_14": sig.rsi_14,
            "macd": sig.macd,
            "macd_signal_line": sig.macd_signal_line,
            "macd_histogram": sig.macd_histogram,
            "kdj_k": sig.kdj_k,
            "kdj_d": sig.kdj_d,
            "kdj_j": sig.kdj_j,
            "bollinger_upper": sig.bollinger_upper,
            "bollinger_middle": sig.bollinger_middle,
            "bollinger_lower": sig.bollinger_lower,
            "bollinger_position": sig.bollinger_position,
            "ma_5": sig.ma_5,
            "ma_20": sig.ma_20,
            "ma_60": sig.ma_60,
            "vwap": sig.vwap,
            "vwap_deviation": sig.vwap_deviation,
            "volume_ratio": sig.volume_ratio,
        }
    elif isinstance(sig, dict):
        signals_summary = sig

    return StockAnalysisResponse(
        code=d.get("code", ""),
        name=d.get("name", ""),
        price=d.get("price", 0.0),
        change_pct=d.get("change_pct", 0.0),
        pe=d.get("pe"),
        pb=d.get("pb"),
        total_mv=d.get("total_mv"),
        score=d.get("score", 50.0),
        rating=d.get("rating", "hold"),
        rating_label=d.get("rating_label", "建议观望"),
        rating_emoji=d.get("rating_emoji", "⚪"),
        confidence=d.get("confidence", 0.5),
        engine_scores=engine_scores,
        engine_skipped=engine_skipped,
        bull_reasons=d.get("bull_reasons", []) or [],
        bear_reasons=d.get("bear_reasons", []) or [],
        rsi_display=d.get("rsi_display", ""),
        macd_display=d.get("macd_display", ""),
        chart_data=d.get("chart_data", {}),
        signals_summary=signals_summary,
        error=d.get("error"),
        _cache_state=d.get("_cache_state", "fresh"),
    )
