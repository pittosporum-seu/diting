"""谛听 · Wyckoff 威克夫分析引擎（AI + 沙箱）

Phase A-E 阶段识别 + Spring/SOS 信号检测。
AI 生成分析代码 → 沙箱执行 → 结构化输出。
"""

from __future__ import annotations

from datetime import datetime

from ..ai.client import AIClient
from ..enums import DataType, Rating, Signal
from ..infra.logging_config import get_logger
from ..sandbox.executor import SandboxExecutor
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .rating import score_to_rating
from .registry import register_engine

logger = get_logger(__name__)

WYCKOFF_SYSTEM_PROMPT = """你是一个威克夫方法分析专家。你的任务是分析给定的股票价格数据，
识别当前处于威克夫市场周期的哪个阶段。

威克夫阶段：
- Phase A (Accumulation): 停止下跌，初步支撑形成
- Phase B (Accumulation): 在支撑区上方横盘整理
- Phase C (Accumulation): Spring（假跌破）或测试，吸筹完成
- Phase D (Accumulation): 突破上涨，趋势确立
- Phase E (Accumulation): 上升趋势运行中

对应的：
- Phase A (Distribution): 停止上涨，初步阻力形成
- Phase B (Distribution): 在阻力区下方横盘整理
- Phase C (Distribution): Upthrust（假突破）或测试，派发完成
- Phase D (Distribution): 跌破支撑，下跌趋势确立
- Phase E (Distribution): 下降趋势运行中

请生成 Python 代码来分析数据。代码必须包含：
1. 一个 `analyze(close, high, low, volume)` 函数
2. 返回一个 dict:
{
    "phase": "Phase C (Accumulation)",
    "score": 65,
    "spring_detected": true/false,
    "sos_detected": true/false,
    "support_level": 45.0,
    "resistance_level": 52.0,
    "volume_confirmation": true/false,
    "narrative": "基于阶段、价格和成交量证据的中文分析说明",
    "bull_reasons": ["看多理由1", "看多理由2", "看多理由3"],
    "bear_reasons": ["看空理由1", "看空理由2", "看空理由3"]
}
每条理由必须具体、可验证并引用输入中的阶段、价位或成交量指标；证据不足时返回空数组，禁止编造。

评分规则：Accumulation 阶段靠后的分数更高（A=20, B=40, C=60, D=80, E=90）
Distribution 阶段分数更低（A=30, B=25, C=20, D=15, E=10）
"""


@register_engine("wyckoff")
class WyckoffEngine(AnalysisEngine):
    """Wyckoff 市场周期分析引擎。

    AI 驱动：LiteLLM 生成分析代码 → sandboxmcp 沙箱执行 → 结构化输出。
    """

    name = "wyckoff"
    version = "1.0.0"

    def __init__(
        self,
        llm: AIClient | None = None,
        sandbox: SandboxExecutor | None = None,
    ):
        self._llm = llm or AIClient()
        self._sandbox = sandbox or SandboxExecutor()

    def required_data(self) -> list[DataType]:
        return [DataType.HISTORICAL]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        start = datetime.now()

        # 准备数据摘要（不传原始数据，让 AI 规划算法）
        hist = context.historical
        if hist is None or hist.df is None:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=0,
                rating=Rating.HOLD,
                error="No historical data",
                duration_ms=0,
            )

        close = hist.df.get("close", hist.df.get("收盘价"))
        if close is None:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=0,
                rating=Rating.HOLD,
                error="No close price data",
            )

        n = len(close)
        data_summary = (
            f"Stock: {context.symbol}\n"
            f"Period: {n} days\n"
            f"Close range: {close.min():.2f} - {close.max():.2f}\n"
            f"Current close: {close.iloc[-1]:.2f}\n"
            f"Recent 5 closes: {[round(x, 2) for x in close.iloc[-5:].tolist()]}\n"
        )
        if "high" in hist.df.columns:
            hi = hist.df["high"].min()
            hm = hist.df["high"].max()
            data_summary += f"High range: {hi:.2f} - {hm:.2f}\n"
        if "low" in hist.df.columns:
            lo = hist.df["low"].min()
            lm = hist.df["low"].max()
            data_summary += f"Low range: {lo:.2f} - {lm:.2f}\n"
        if "volume" in hist.df.columns or "成交量" in hist.df.columns:
            vol_col = "volume" if "volume" in hist.df.columns else "成交量"
            data_summary += f"Avg volume: {hist.df[vol_col].mean():.0f}\n"

        # 统一流程：调 AI → 跑沙箱 → 解析输出
        output = self._run_ai(WYCKOFF_SYSTEM_PROMPT, data_summary)

        score = output.score
        rating = score_to_rating(score)

        # 从 metadata 提取引擎特有信号
        metadata = output.metadata
        signals = []
        if metadata.get("spring_detected"):
            signals.append(Signal.WYCKOFF_SPRING)
        if metadata.get("sos_detected"):
            signals.append(Signal.WYCKOFF_SOS)

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)

        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=context.symbol,
            score=score,
            rating=rating,
            signals=tuple(signals),
            narrative=output.narrative,
            confidence=0.7 if score > 60 or score < 40 else 0.5,
            metadata={
                "phase": metadata.get("phase", "unknown"),
                "support": metadata.get("support_level"),
                "resistance": metadata.get("resistance_level"),
                "volume_confirmation": metadata.get("volume_confirmation", False),
                "bull_reasons": output.bull_reasons[:3],
                "bear_reasons": output.bear_reasons[:3],
            },
            duration_ms=duration_ms,
        )
