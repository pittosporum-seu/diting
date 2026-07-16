"""谛听 · VMD+RSI 择时引擎（纯计算）"""


from ..enums import DataType, Rating, Signal
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .registry import register_engine


@register_engine("vmd_rsi")
class VMDRSIEngine(AnalysisEngine):
    """VMD+RSI 三维择时：大盘 × 行业 × 个股"""

    name = "vmd_rsi"
    version = "1.0.0"

    def required_data(self):
        return [DataType.HISTORICAL]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        signals = []
        risks = []

        # RSI 信号
        rsi = None
        if context.signals and context.signals.rsi_14:
            rsi = context.signals.rsi_14

        # VMD 周期位置
        vmd = context.vmd

        # 综合评分
        score = 50.0
        factors = []

        if rsi is not None:
            if rsi < 25:
                score += 20
                signals.append(Signal.RSI_OVERSOLD)
                factors.append(f"RSI={rsi:.0f} 超卖，短期具备修复动力")
            elif rsi < 35:
                score += 10
                factors.append(f"RSI={rsi:.0f} 偏低，处于相对低位")
            elif rsi > 75:
                score -= 20
                signals.append(Signal.RSI_OVERBOUGHT)
                risks.append(f"RSI={rsi:.0f} 超买")
            elif rsi > 65:
                score -= 10
                risks.append(f"RSI={rsi:.0f} 偏高，追涨空间受限")

        if vmd is not None:
            if vmd.cycle_position < 0.2:
                score += 15
                signals.append(Signal.VMD_TROUGH)
                factors.append(f"VMD 接近谷底 (pos={vmd.cycle_position:.2f})")
            elif vmd.cycle_position > 0.8:
                score -= 15
                signals.append(Signal.VMD_PEAK)
                risks.append(f"VMD 接近峰顶 (pos={vmd.cycle_position:.2f})")
            if vmd.trend_broken:
                risks.append("VMD 趋势已打破")

        score = max(0, min(100, score))
        rating = self._to_rating(score)
        narrative = "; ".join(factors) if factors else "无明显择时信号"

        return AnalysisResult(
            engine_name=self.name, engine_version=self.version,
            symbol=context.symbol, score=score, rating=rating,
            signals=tuple(signals),
            narrative=narrative,
            risks=tuple(risks),
            metadata={
                "rsi": rsi,
                "vmd_position": vmd.cycle_position if vmd else None,
                "bull_reasons": factors[:3],
                "bear_reasons": risks[:3],
            },
        )

    @staticmethod
    def _to_rating(s: float) -> Rating:
        if s >= 80:
            return Rating.STRONG_BUY
        if s >= 65:
            return Rating.BUY
        if s >= 50:
            return Rating.ACCUMULATE
        if s >= 35:
            return Rating.HOLD
        if s >= 20:
            return Rating.REDUCE
        return Rating.SELL
