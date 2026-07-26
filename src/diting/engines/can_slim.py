"""谛听 · CANSLIM 成长股评分引擎（AI + 沙箱）"""

from ..ai.client import AIClient
from ..enums import DataType, Rating
from ..infra.logging_config import get_logger
from ..sandbox.executor import SandboxExecutor
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .rating import score_to_rating
from .registry import register_engine

logger = get_logger(__name__)

CANSLIM_SYSTEM = """你是 CANSLIM 成长股分析专家。7维度评分。

C - Current earnings (当季利润增长)
A - Annual earnings (年度利润增长)
N - New (新产品/新管理层/新高)
S - Supply & Demand (供需/成交量)
L - Leader (行业龙头)
I - Institutional sponsorship (机构持仓)
M - Market direction (大盘方向)

生成Python代码 `analyze(data)` 返回:
{
    "score": 60,
    "c_score": 15, "a_score": 12, "n_score": 10,
    "s_score": 8, "l_score": 14, "i_score": 6, "m_score": 5,
    "narrative": "基于 CANSLIM 七维评分的中文分析，引用关键指标",
    "bull_reasons": ["看多理由1", "看多理由2", "看多理由3"],
    "bear_reasons": ["看空理由1", "看空理由2", "看空理由3"]
}
每条理由必须具体、可验证并引用输入中的成长、盈利或市场指标；证据不足时返回空数组，禁止编造。
"""


@register_engine("can_slim")
class CANSLIMEngine(AnalysisEngine):
    name = "can_slim"
    version = "1.0.0"

    def __init__(self, llm=None, sandbox=None):
        self._llm = llm or AIClient()
        self._sandbox = sandbox or SandboxExecutor()

    def required_data(self):
        return [DataType.REALTIME, DataType.FUNDAMENTALS]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        if not context.realtime:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=0,
                rating=Rating.HOLD,
                error="No data",
            )

        info = f"Stock: {context.symbol}\nPrice: {context.realtime.price}\n"
        if context.financials:
            f = context.financials
            info += f"Profit YoY: {f.profit_yoy}%\nRevenue YoY: {f.revenue_yoy}%\nROE: {f.roe}%\n"

        output = self._run_ai(CANSLIM_SYSTEM, info)

        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=context.symbol,
            score=output.score,
            rating=score_to_rating(output.score),
            narrative=output.narrative,
            confidence=0.6,
            metadata={
                **output.metadata,
                "bull_reasons": output.bull_reasons[:3],
                "bear_reasons": output.bear_reasons[:3],
            },
        )
