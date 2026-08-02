"""谛听 · StockService — 个股分析、实时行情、历史数据"""

# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from ...cache import get_market_state
from ...enums import FetchMode
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
        """Get one quote exclusively through the v0.8 Data Gateway."""
        try:
            if self._data_gateway is not None:
                return self.get_realtime_result(code, force_refresh).data
            return self._build_repo().get_realtime([code]).get(code)
        except Exception:
            logger.warning("services.realtime.failed", code=code)
            return None

    def get_realtime_result(self, code: str, force_refresh: bool = False):
        """Return the gateway DataResult without changing cache or trace metadata."""

        if self._data_gateway is None:
            raise RuntimeError("DataGateway was not injected")
        from ...schema import QuoteRequest

        return self._data_gateway.get_quotes(
            QuoteRequest(
                symbols=(code,),
                mode=(FetchMode.FRESH_REQUIRED if force_refresh else FetchMode.CACHE_PREFERRED),
                force_refresh=force_refresh,
            )
        )[code]

    # ── Historical ──────────────────────────────────

    def get_historical(self, code: str, days: int = 250):
        """Get normalized history exclusively through the v0.8 Data Gateway."""
        try:
            end = date.today()
            start = end - timedelta(days=days)
            return self._build_repo().get_historical(code, start, end)
        except Exception:
            logger.warning("services.historical.failed", code=code)
            return None

    # ── Full Analysis ───────────────────────────────

    def analyze_stock(
        self,
        code: str,
        force: bool = False,
        run_ai: bool = False,
        ai_results_override: list | None = None,
    ) -> StockAnalysisResponse:
        """个股全流程分析，返回模板/API 通用数据结构。

        Args:
            code: 股票代码。
            force: True 时跳过缓存、且休市也跑全量引擎（显式重跑）。
            run_ai: True 时休市也跑 AI 引擎（用于候选深度分析，保证引擎完整）。
            ai_results_override: 预取的 AI 引擎结果（AnalysisResult 列表）。
                深度分析批量预取后传入，避免逐只重复调 AI；None 时走 batch-of-1。

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

        # L1: 内存 TTL（force=True 时跳过缓存，强制重算）
        cm = self._get_cache_mgr()
        cached = None if force else cm.mem_get_adaptive(f"analysis:{code}", trading_ttl=60)
        if cached is not None:
            if isinstance(cached, StockAnalysisResponse):
                cached._cache_state = "stale"
                return cached
            # 兼容旧 dict 缓存
            if isinstance(cached, dict):
                cached["_cache_state"] = "stale"
                return _dict_to_response(cached)
        # L2: SQLite stock_analysis_cache（force=True 时跳过）
        try:
            db_row = None if force else cm.db_get("stock_analysis_cache", code)
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
        all_engines = ["wyckoff", "can_slim", "volume_profile", "vmd_rsi", "verdict"]
        discovered = discover_engines()
        available_engines = set(discovered or all_engines)
        engine_names = [
            en
            for en in all_engines
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
        _ai_engines = {"wyckoff", "can_slim"}
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

        # v0.6.6: 非交易时段跳过 AI 引擎（force=True 或 run_ai=True 时休市也跑全量）
        state = get_market_state()
        if not state.should_call_api and not force and not run_ai:
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

        # ── 资金流向（统一通过 Data Gateway）──
        fund_flow = None
        try:
            fund_flow = self._build_repo().get_fund_flow(code)
        except Exception:
            logger.debug("services.fund_flow.skip", code=code)

        ctx_obj = AnalysisContext(
            symbol=code,
            realtime=quote,
            historical=historical,
            signals=sig,
            vmd=vmd,
            fund_flow=fund_flow,
        )

        consensus: ConsensusScore | None = None
        engine_scores: list[dict] = []
        bull_reasons: list[str] = []
        bear_reasons: list[str] = []

        # 拆分 quick 引擎（走 pipeline 并行）与 AI 引擎（走批量直出 JSON）
        quick_engine_names = [en for en in engine_names if en not in _ai_engines]
        ai_engine_names = [en for en in engine_names if en in _ai_engines]
        all_results: list = []

        # ── quick 引擎：pipeline ──
        try:
            if quick_engine_names:
                pipeline = AnalysisPipeline(engine_names=quick_engine_names)
                pipe_result: PipelineResult = pipeline.run([ctx_obj])
                all_results.extend(pipe_result.results.get(code, []))
                for error in pipe_result.errors:
                    engine_name = str(error.get("engine", ""))
                    error_text = str(error.get("error", "")).lower()
                    reason = (
                        "timeout"
                        if "timeout" in error_text or "timed out" in error_text
                        else "error"
                    )
                    record_skipped([engine_name], reason)
        except Exception as exc:
            record_skipped(quick_engine_names, "error")
            logger.warning("services.pipeline.failed", code=code, error=str(exc))

        # ── AI 引擎：批量直出 JSON（单股即 batch-of-1，去沙箱脆弱）──
        if ai_engine_names:
            if ai_results_override is not None:
                # 深度分析已批量预取，直接复用
                got = [r for r in ai_results_override if r.engine_name in ai_engine_names]
                all_results.extend(got)
                got_names = {r.engine_name for r in got}
                missing = [en for en in ai_engine_names if en not in got_names]
                if missing:
                    record_skipped(missing, "error")
            else:
                try:
                    from ...engines.batch_ai import BatchAIAnalyzer

                    batch_results = BatchAIAnalyzer(self).analyze([code], ai_engine_names)
                    got = batch_results.get(code, [])
                    all_results.extend(got)
                    got_names = {r.engine_name for r in got}
                    missing = [en for en in ai_engine_names if en not in got_names]
                    if missing:
                        record_skipped(missing, "error")
                except Exception as exc:
                    record_skipped(ai_engine_names, "error")
                    logger.warning("services.batch_ai.failed", code=code, error=str(exc))

        # ── 共识融合 + 组装 engine_scores ──
        try:
            ce = ConsensusEngine()
            consensus = ce.fuse(code, all_results)
            for r in all_results:
                if r.error:
                    record_skipped([r.engine_name], "error")
                    continue
                engine_scores.append(
                    {
                        "name": r.engine_name,
                        "score": r.score,
                        "rating": r.rating.value,
                        "rating_cn": _RATING_CN.get(r.rating.value, r.rating.value),
                        "confidence": r.confidence,
                    }
                )
                metadata = r.metadata if isinstance(r.metadata, dict) else {}
                for reason in metadata.get("bull_reasons", []) or []:
                    text = str(reason).strip()
                    if text and text not in bull_reasons:
                        bull_reasons.append(text)
                for reason in metadata.get("bear_reasons", []) or []:
                    text = str(reason).strip()
                    if text and text not in bear_reasons:
                        bear_reasons.append(text)
        except Exception as exc:
            record_skipped(engine_names, "error")
            logger.warning("services.consensus.failed", code=code, error=str(exc))
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
            item for item in engine_skipped if item["engine_name"] not in successful_engines
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
        # 写入 SQLite（signals 转 dict，避免 dataclass 被 default=str 序列化为字符串）
        try:
            import json as _json
            from dataclasses import asdict as _asdict

            serializable = clean_numpy(result)
            if _sig is not None:
                serializable["signals"] = (
                    _asdict(_sig) if hasattr(_sig, "__dataclass_fields__") else _sig
                )
            l2_ttl = 30 if (state and state.should_call_api) else 1440
            cm.db_set(
                "stock_analysis_cache",
                code,
                {
                    "code": code,
                    "result_json": _json.dumps(serializable, default=str, ensure_ascii=False),
                    "expires_at": datetime.now() + timedelta(minutes=l2_ttl),
                },
            )
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
    if isinstance(sig, dict):
        signals_summary = sig
    elif sig is not None and hasattr(sig, "rsi_14"):
        # dataclass 对象（新鲜分析）
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
    # 其他情况（字符串/None）: signals_summary 保持 None，前端显示“暂无”

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
