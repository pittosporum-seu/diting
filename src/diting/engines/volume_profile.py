"""谛听 · Volume Profile 引擎（纯计算）"""

import numpy as np

from ..enums import DataType, Rating
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .rating import score_to_rating
from .registry import register_engine


@register_engine("volume_profile")
class VolumeProfileEngine(AnalysisEngine):
    """Volume Profile — VAH/POC/VAL + 支撑压力（纯计算，无需 AI）"""

    name = "volume_profile"
    version = "1.0.0"

    def required_data(self):
        return [DataType.HISTORICAL]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        hist = context.historical
        if hist is None or hist.df is None:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=50,
                rating=Rating.HOLD,
                error="No historical data",
            )

        df = hist.df
        if df.empty:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=50,
                rating=Rating.HOLD,
                error="No historical data",
            )
        if "close" not in df.columns and "收盘价" not in df.columns:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=50,
                rating=Rating.HOLD,
                error="No close price data",
            )
        close_col = "close" if "close" in df.columns else "收盘价"
        close = df[close_col].values
        current = close[-1]

        # 简单 Volume Profile: 价格分 10 档
        bins = 10
        hist_counts, bin_edges = np.histogram(close, bins=bins)
        poc_idx = np.argmax(hist_counts)
        poc = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

        # VAH/VAL: 上下 30% 区域
        total = len(close)
        cumsum = 0
        vah = poc
        val = poc
        for i in range(poc_idx, bins):
            cumsum += hist_counts[i]
            if cumsum >= total * 0.3:
                vah = bin_edges[min(i + 1, bins)]
                break
        cumsum = 0
        for i in range(poc_idx, -1, -1):
            cumsum += hist_counts[i]
            if cumsum >= total * 0.3:
                val = bin_edges[i]
                break

        # 评分及可验证的多空证据
        bull_reasons: list[str] = []
        bear_reasons: list[str] = []
        if val <= current <= vah:
            score = 70.0
            narrative = f"现价 ¥{current:.1f} 在价值区 [{val:.1f}, {vah:.1f}] 内，POC=¥{poc:.1f}"
            bull_reasons.append(
                f"现价 ¥{current:.1f} 位于价值区 [{val:.1f}, {vah:.1f}] 内，筹码接受度较高"
            )
        elif current > vah:
            score = 35.0
            narrative = f"现价 ¥{current:.1f} 高于价值区上沿 ¥{vah:.1f}"
            bear_reasons.append(f"现价 ¥{current:.1f} 高于 VAH ¥{vah:.1f}，偏离价值区存在回归风险")
        else:
            score = 45.0
            narrative = f"现价 ¥{current:.1f} 低于价值区下沿 ¥{val:.1f}"
            bull_reasons.append(
                f"现价 ¥{current:.1f} 低于 VAL ¥{val:.1f}，回归价值区可形成修复空间"
            )
            bear_reasons.append(f"现价 ¥{current:.1f} 跌破 VAL ¥{val:.1f}，价值区支撑尚未确认")

        rating = score_to_rating(score)

        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=context.symbol,
            score=score,
            rating=rating,
            narrative=narrative,
            risks=tuple(bear_reasons),
            metadata={
                "poc": poc,
                "vah": vah,
                "val": val,
                "bull_reasons": bull_reasons[:3],
                "bear_reasons": bear_reasons[:3],
            },
        )
