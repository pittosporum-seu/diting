"""谛听 · 结论引擎 — 把技术指标翻译成人话（纯计算，无需 AI）"""

from __future__ import annotations

from ..enums import DataType, Rating, Signal
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .registry import register_engine


@register_engine("verdict")
class VerdictEngine(AnalysisEngine):
    """评分翻译层：把技术指标变成人话结论。

    综合 RSI、VMD、资金流向、估值等信号，生成买/卖/持有结论
    和对应的多空理由。
    """

    name = "verdict"
    version = "1.0.0"

    def required_data(self) -> list[DataType]:
        return [DataType.REALTIME]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        signals = context.signals
        vmd = context.vmd
        fund_flow = context.fund_flow
        realtime = context.realtime

        score = 50.0
        bull_reasons: list[str] = []
        bear_reasons: list[str] = []
        result_signals: list[Signal] = []

        # ── VMD 周期信号 ──
        if vmd is not None:
            if vmd.cycle_position < 0.3:
                score += 20
                bull_reasons.append("VMD 周期触底，反弹概率较大")
                result_signals.append(Signal.VMD_TROUGH)
            elif vmd.cycle_position > 0.7:
                score -= 20
                bear_reasons.append("VMD 周期见顶，回调风险较大")
                result_signals.append(Signal.VMD_PEAK)
            if vmd.trend_broken:
                bear_reasons.append("VMD 趋势已打破，方向不明")
                result_signals.append(Signal.VMD_TREND_BROKEN)

        # ── RSI 信号 ──
        if signals is not None:
            rsi = signals.rsi_14
            if rsi < 30:
                score += 15
                bull_reasons.append("RSI 超卖，短期有修复动力")
                result_signals.append(Signal.RSI_OVERSOLD)
            elif rsi > 75:
                score -= 15
                bear_reasons.append("RSI 超买，高位追涨需谨慎")
                result_signals.append(Signal.RSI_OVERBOUGHT)

            # MACD 金叉/死叉
            if signals.macd > signals.macd_signal_line:
                score += 5
            else:
                score -= 5

            # 布林带位置
            if signals.bollinger_position < 0.1:
                score += 5
            elif signals.bollinger_position > 0.9:
                score -= 5

        # ── 资金流向信号 ──
        if fund_flow is not None:
            if fund_flow.main_net_inflow > 1e8:
                score += 10
                bull_reasons.append("主力资金持续流入")
                result_signals.append(Signal.FUND_INFLOW)
            elif fund_flow.main_net_inflow < -1e8:
                score -= 10
                bear_reasons.append("主力资金持续流出")
                result_signals.append(Signal.FUND_OUTFLOW)

            if fund_flow.ddx > 0.3:
                score += 10
                bull_reasons.append("大单资金连续异动")

        # ── 估值信号 ──
        if realtime is not None and realtime.pe is not None:
            if realtime.pe > 100:
                score -= 10
                bear_reasons.append("估值偏高")

        # ── 钳制 + 评级映射 ──
        score = max(0.0, min(100.0, score))
        rating = self._score_to_rating(score)
        verdict_cn = self._verdict_cn(score)

        # ── 构建 narrative ──
        parts = [f"综合评分 {score:.0f}/100 — {verdict_cn}"]
        if bull_reasons:
            parts.append("看多: " + "; ".join(bull_reasons[:3]))
        if bear_reasons:
            parts.append("看空: " + "; ".join(bear_reasons[:3]))
        narrative = "。".join(parts)

        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=context.symbol,
            score=score,
            rating=rating,
            signals=tuple(result_signals),
            narrative=narrative,
            risks=tuple(bear_reasons[:3]),
            confidence=0.7,
            metadata={
                "bull_reasons": bull_reasons[:3],
                "bear_reasons": bear_reasons[:3],
                "verdict": verdict_cn,
            },
        )

    # ── 评分映射 ──

    @staticmethod
    def _score_to_rating(score: float) -> Rating:
        if score >= 75:
            return Rating.BUY
        if score >= 55:
            return Rating.ACCUMULATE
        if score >= 35:
            return Rating.HOLD
        return Rating.REDUCE

    @staticmethod
    def _verdict_cn(score: float) -> str:
        if score >= 75:
            return "建议买入"
        if score >= 55:
            return "建议关注"
        if score >= 35:
            return "建议观望"
        return "建议回避"
