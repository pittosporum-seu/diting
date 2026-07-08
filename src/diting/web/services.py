"""谛听 · Web 服务层 — 业务编排

封装数据获取、分析管道、辅助计算。
路由层只做请求/响应转换，不直接访问数据源或引擎。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..config import Config
from ..data.providers.akshare import AkShareProvider
from ..data.providers.mx_data import MxDataProvider
from ..data.repository import MarketDataRepository
from ..engines.registry import discover_engines
from ..infra.logging_config import get_logger
from ..pipeline.consensus import ConsensusEngine
from ..pipeline.runner import AnalysisPipeline
from ..schema import (
    AnalysisContext,
    ConsensusScore,
    HistoricalData,
    PipelineResult,
    RealtimeQuote,
    TechnicalSignals,
)

logger = get_logger(__name__)

# ── Rating display labels ──────────────────────────

_RATING_CN: dict[str, str] = {
    "strong_buy": "强烈买入",
    "buy": "建议买入",
    "accumulate": "建议关注",
    "hold": "建议观望",
    "reduce": "建议回避",
    "sell": "建议回避",
}
_RATING_EMOJI: dict[str, str] = {
    "strong_buy": "🟢",
    "buy": "🟢",
    "accumulate": "🟡",
    "hold": "⚪",
    "reduce": "🔴",
    "sell": "🔴",
}


class AnalysisService:
    """Web 层业务编排。不 import 任何 CLI 层代码。"""

    def __init__(self) -> None:
        self._settings: dict = {}

    # ── 内部工厂 ───────────────────────────────────

    @staticmethod
    def _build_repo() -> MarketDataRepository:
        cfg = Config()
        providers = []
        mx_key = cfg.get("MX_APIKEY")
        if mx_key:
            providers.append(MxDataProvider(api_key=mx_key))
        providers.append(AkShareProvider())
        return MarketDataRepository(providers=providers)

    @staticmethod
    def _extract_chart_arrays(df) -> dict:
        """从历史 DataFrame 提取图表数据（OHLC / Volume / MA / Boll / RSI 序列）。"""
        import numpy as np

        # 列名探测
        col_map: dict[str, str] = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ("date", "日期", "trade_date"):
                col_map["date"] = c
            elif cl in ("close", "收盘", "收盘价"):
                col_map["close"] = c
            elif cl in ("open", "开盘", "开盘价"):
                col_map["open"] = c
            elif cl in ("high", "最高", "最高价"):
                col_map["high"] = c
            elif cl in ("low", "最低", "最低价"):
                col_map["low"] = c
            elif cl in ("volume", "成交量", "vol"):
                col_map["volume"] = c

        if "date" not in col_map or "close" not in col_map:
            return {}

        dates = [str(d) for d in df[col_map["date"]].tolist()]
        close = df[col_map["close"]].values
        if close.dtype == object:
            close = close.astype(float)
        n = len(close)

        result: dict = {"dates": dates, "prices": close.tolist()}

        # OHLC — 新版前端优先使用 ohlc 字段绘制真蜡烛
        if all(k in col_map for k in ("open", "high", "low")):
            opens = df[col_map["open"]].values
            highs = df[col_map["high"]].values
            lows = df[col_map["low"]].values
            if opens.dtype == object:
                opens = opens.astype(float)
            if highs.dtype == object:
                highs = highs.astype(float)
            if lows.dtype == object:
                lows = lows.astype(float)
            result["ohlc"] = [
                [float(o), float(c), float(lo), float(h)]
                for o, c, lo, h in zip(opens, close, lows, highs)
            ]

        # 成交量
        if "volume" in col_map:
            volumes = df[col_map["volume"]].values
            if volumes.dtype == object:
                volumes = volumes.astype(float)
            result["volumes"] = volumes.tolist()

        if n >= 5:
            result["ma_5"] = (
                df[col_map["close"]].astype(float).rolling(window=5).mean().tolist()
            )
        if n >= 20:
            result["ma_20"] = (
                df[col_map["close"]].astype(float).rolling(window=20).mean().tolist()
            )
            roll = df[col_map["close"]].astype(float).rolling(window=20)
            middle = roll.mean()
            std = roll.std(ddof=1)
            result["boll_upper"] = (middle + 2 * std).tolist()
            result["boll_lower"] = (middle - 2 * std).tolist()

        if n >= 15:
            diff = np.diff(close)
            gain = np.maximum(diff, 0)
            loss = np.maximum(-diff, 0)
            rsi = np.full(n, np.nan)
            avg_gain = float(np.mean(gain[:14]))
            avg_loss = float(np.mean(loss[:14]))
            rsi[14] = (
                100.0 if avg_loss == 0
                else float(100 - 100 / (1 + avg_gain / avg_loss))
            )
            for i in range(15, n):
                avg_gain = (avg_gain * 13 + gain[i - 1]) / 14
                avg_loss = (avg_loss * 13 + loss[i - 1]) / 14
                if avg_loss == 0:
                    rsi[i] = 100.0
                else:
                    rsi[i] = float(100 - 100 / (1 + avg_gain / avg_loss))
            result["rsi_values"] = rsi.tolist()

        return result

    # ── 公开方法 ───────────────────────────────────

    def get_realtime(self, code: str) -> RealtimeQuote | None:
        """获取单只股票实时行情。"""
        try:
            repo = self._build_repo()
            quotes = repo.get_realtime([code])
            return quotes.get(code)
        except Exception:
            logger.warning("services.realtime.failed", code=code)
            return None

    def get_historical(self, code: str, days: int = 250) -> HistoricalData | None:
        """获取历史日线行情。"""
        try:
            repo = self._build_repo()
            end = date.today()
            start = end - timedelta(days=days)
            return repo.get_historical(code, start, end)
        except Exception:
            logger.warning("services.historical.failed", code=code)
            return None

    def analyze_stock(self, code: str) -> dict:
        """个股全流程分析，返回模板/API 通用数据结构。

        Returns:
            dict with keys: code, name, price, change_pct, pe, pb, total_mv,
            volume, turnover, score, rating, rating_label, rating_emoji,
            confidence, engine_scores, bull_reasons, bear_reasons,
            rsi_display, macd_display, chart_data (raw arrays dict),
            signals, error.
        """
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
            "bull_reasons": [],
            "bear_reasons": [],
            "rsi_display": "-",
            "macd_display": "-",
            "chart_data": {},
            "signals": None,
            "error": None,
        }

        # ── realtime ──
        quote = self.get_realtime(code)
        if quote is None:
            result["error"] = f"未找到股票 {code}"
            return result

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
        result["_historical"] = historical  # internal, stripped before JSON

        # ── chart arrays ──
        chart_data: dict = {}
        if historical and historical.df is not None:
            try:
                chart_data = self._extract_chart_arrays(historical.df)
            except Exception:
                pass
        result["chart_data"] = chart_data

        # ── technical signals ──
        sig: TechnicalSignals | None = None
        if historical and historical.df is not None:
            try:
                from ..signals.technical import TechnicalCalculator
                sig = TechnicalCalculator.calculate(historical)
            except Exception:
                pass
        result["signals"] = sig

        if sig:
            result["rsi_display"] = f"{sig.rsi_14:.1f}"
            result["macd_display"] = f"{sig.macd:.3f}"

        # ── analysis pipeline ──
        engine_names = discover_engines()[:3]
        ctx_obj = AnalysisContext(
            symbol=code, realtime=quote, historical=historical,
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
                    continue
                engine_scores.append({
                    "name": r.engine_name,
                    "score": r.score,
                    "rating": r.rating.value,
                    "rating_cn": _RATING_CN.get(r.rating.value, r.rating.value),
                    "confidence": r.confidence,
                })
                if r.narrative:
                    for line in r.narrative.split("\n"):
                        line = line.strip("-• ").strip()
                        if not line:
                            continue
                        if any(
                            kw in line
                            for kw in [
                                "买入", "看多", "低估", "超卖", "支撑", "利好",
                            ]
                        ):
                            bull_reasons.append(line[:60])
                        elif any(
                            kw in line
                            for kw in [
                                "卖出", "看空", "高估", "超买", "阻力", "风险", "利空",
                            ]
                        ):
                            bear_reasons.append(line[:60])
        except Exception:
            logger.warning("services.pipeline.failed", code=code)
            consensus = None

        if consensus is None:
            consensus = ConsensusEngine().fuse(code, [])

        # ── quick score fallback ──
        quick_score = 50
        if sig:
            rsi_val = sig.rsi_14
            if rsi_val < 25:
                quick_score += 20
            elif rsi_val < 35:
                quick_score += 10
            elif rsi_val > 75:
                quick_score -= 20
            elif rsi_val > 65:
                quick_score -= 10

        final_score = consensus.weighted_score if engine_scores else quick_score

        result["engine_scores"] = engine_scores
        result["bull_reasons"] = bull_reasons
        result["bear_reasons"] = bear_reasons
        result["score"] = final_score
        result["rating"] = consensus.rating.value
        result["rating_label"] = _RATING_CN.get(consensus.rating.value, consensus.rating.value)
        result["rating_emoji"] = _RATING_EMOJI.get(consensus.rating.value, "")
        result["confidence"] = consensus.confidence

        return result

    def get_dashboard_data(self) -> dict:
        """大盘/仪表盘概览数据。"""
        try:
            cfg = Config()
            stocks = cfg.load_watchlist(validate=False)
            repo = self._build_repo()

            sentiment = self.get_market_sentiment()
            opportunities = self.get_opportunities()
            buy_count = sum(1 for o in opportunities if o["score"] >= 75)
            watch_count = sum(1 for o in opportunities if 55 <= o["score"] < 75)
            hold_count = sum(1 for o in opportunities if 35 <= o["score"] < 55)
            avoid_count = sum(1 for o in opportunities if o["score"] < 35)

            return {
                "status": "ok",
                "watchlist_count": len(stocks),
                "buy_signals": buy_count,
                "watch_signals": watch_count,
                "hold_signals": hold_count,
                "avoid_signals": avoid_count,
                "providers": repo.available_providers,
                "market_sentiment": sentiment,
            }
        except Exception:
            logger.warning("services.dashboard.failed")
            return {
                "status": "error",
                "watchlist_count": 0,
                "buy_signals": 0,
                "watch_signals": 0,
                "hold_signals": 0,
                "avoid_signals": 0,
            }

    def get_watchlist(self) -> list[dict]:
        """获取自选股列表（含实时行情）。"""
        try:
            cfg = Config()
            stocks = cfg.load_watchlist(validate=False)
            codes = [s["code"] for s in stocks if s.get("code")]

            repo = self._build_repo()
            all_quotes: dict = {}
            for i in range(0, len(codes), 4):
                batch = codes[i:i + 4]
                try:
                    all_quotes.update(repo.get_realtime(batch))
                except Exception:
                    logger.warning("watchlist.batch_failed", batch=batch)

            results = []
            for s in stocks:
                code = s.get("code", "")
                q = all_quotes.get(code)
                results.append({
                    "code": code,
                    "name": q.name if q else s.get("name", code),
                    "price": q.price if q else None,
                    "change_pct": q.change_pct if q else None,
                    "volume": q.volume if q else None,
                    "pe": q.pe if q else None,
                })
            return results
        except Exception:
            logger.warning("services.watchlist.failed")
            return []

    def get_opportunities(self) -> list[dict]:
        """选股机会扫描（价格驱动的快速评分，不调 AI 引擎）。"""
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

                score = 50
                signals = []

                if q.change_pct is not None:
                    if q.change_pct > 3:
                        score += 10
                        signals.append("强势上涨")
                    elif q.change_pct > 1:
                        score += 5
                        signals.append("温和上涨")
                    elif q.change_pct < -3:
                        score -= 10
                        signals.append("大幅下跌")
                    elif q.change_pct < -1:
                        score -= 5
                        signals.append("小幅下跌")

                score = max(0, min(100, score))

                results.append({
                    "code": code,
                    "name": q.name or code,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "score": score,
                    "signals": signals,
                    "rating": (
                        "buy" if score >= 75
                        else "accumulate" if score >= 55
                        else "hold" if score >= 35
                        else "reduce"
                    ),
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results
        except Exception:
            logger.warning("services.opportunities.failed")
            return []

    def get_market_sentiment(self) -> dict:
        """市场情绪指标（基于上证指数实时行情）。"""
        try:
            repo = self._build_repo()
            quotes = repo.get_realtime(["000001"])  # 上证指数
            sh = quotes.get("000001")
            if sh:
                score = 50 + (sh.change_pct * 5 if sh.change_pct else 0)
                score = max(0, min(100, score))
                return {
                    "sentiment": "bullish" if (sh.change_pct or 0) > 0 else "bearish",
                    "sh_index": sh.price,
                    "sh_change": sh.change_pct,
                    "score": round(score, 1),
                    "source": "realtime",
                    "timestamp": str(datetime.now()),
                }
        except Exception:
            logger.warning("market_sentiment.failed")
        return {
            "sentiment": "neutral",
            "sh_index": None,
            "sh_change": None,
            "score": 50,
            "source": "unavailable",
        }

    def save_settings(self, data: dict) -> dict:
        """保存设置（v0.3.1：内存保存，不写磁盘）。"""
        self._settings = data
        logger.info("settings.saved", settings=data)
        return {"status": "ok", "message": "设置已保存（重启后恢复默认）"}

    def health_check(self) -> dict:
        """服务健康检查。"""
        return {"status": "ok", "service": "diting-web"}
