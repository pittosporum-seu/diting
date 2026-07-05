"""谛听 · CANSLIM 成长股评分引擎（AI + 沙箱）"""

import json

from ..ai.client import AIClient
from ..enums import DataType, Rating
from ..sandbox.executor import SandboxExecutor
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .registry import register_engine

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
    "narrative": "中文分析"
}
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
                engine_name=self.name, engine_version=self.version,
                symbol=context.symbol, score=0, rating=Rating.HOLD,
                error="No data",
            )

        info = f"Stock: {context.symbol}\nPrice: {context.realtime.price}\n"
        if context.financials:
            f = context.financials
            info += f"Profit YoY: {f.profit_yoy}%\nRevenue YoY: {f.revenue_yoy}%\nROE: {f.roe}%\n"

        code = self._llm.complete(system=CANSLIM_SYSTEM, user=info)
        if "```" in code:
            if "```python" in code:
                code = code.split("```python")[1].split("```")[0]
            else:
                code = code.split("```")[1].split("```")[0]

        result = self._sandbox.run(code)
        output = result.get("output", "")
        try:
            if "{" in output:
                parsed = json.loads(output[output.index("{"):output.rindex("}") + 1])
            else:
                parsed = {}
        except (json.JSONDecodeError, ValueError):
            parsed = {}

        score = float(parsed.get("score", 50))
        return AnalysisResult(
            engine_name=self.name, engine_version=self.version,
            symbol=context.symbol, score=score,
            rating=self._to_rating(score),
            narrative=parsed.get("narrative", ""),
            confidence=0.6,
            metadata=parsed,
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
