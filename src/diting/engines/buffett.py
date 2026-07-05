"""谛听 · 巴菲特/芒格价值评分引擎（AI + 沙箱）"""

import json

from ..ai.client import AIClient
from ..enums import DataType, Rating
from ..infra.logging_config import get_logger
from ..sandbox.executor import SandboxExecutor
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .registry import register_engine

logger = get_logger(__name__)

BUFFETT_SYSTEM = """你是巴菲特/芒格价值投资分析专家。分析给定股票，用100分制评分。

评分维度（每项0-20分）：
1. 护城河深度 - 品牌/技术/网络效应/转换成本
2. 财务健康 - ROE/负债率/现金流
3. 管理层质量 - 资本配置能力/诚信记录
4. 估值合理性 - PE/市净率/股息率
5. 成长性 - 营收/利润增长率

生成Python代码，函数 `analyze(financials)` 返回:
{
    "score": 65,
    "moat_score": 15,
    "financial_score": 12,
    "management_score": 10,
    "valuation_score": 13,
    "growth_score": 15,
    "warnings": ["高负债率", "ROE下降"],
    "narrative": "中文分析"
}
"""


@register_engine("buffett")
class BuffettEngine(AnalysisEngine):
    name = "buffett"
    version = "1.0.0"

    def __init__(self, llm=None, sandbox=None):
        self._llm = llm or AIClient()
        self._sandbox = sandbox or SandboxExecutor()

    def required_data(self):
        return [DataType.FUNDAMENTALS, DataType.REALTIME]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        if not context.realtime:
            return AnalysisResult(
                engine_name=self.name, engine_version=self.version,
                symbol=context.symbol, score=0, rating=Rating.HOLD,
                error="No realtime data",
            )

        summary = (
            f"Stock: {context.symbol}\n"
            f"Price: {context.realtime.price}\n"
            f"PE: {context.realtime.pe}\n"
            f"PB: {context.realtime.pb}\n"
        )
        if context.financials:
            f = context.financials
            summary += (
                f"ROE: {f.roe}%\n"
                f"Debt ratio: {f.debt_ratio}%\n"
                f"Revenue YoY: {f.revenue_yoy}%\n"
                f"Profit YoY: {f.profit_yoy}%\n"
                f"Gross margin: {f.gross_margin}%\n"
            )

        code = self._llm.complete(system=BUFFETT_SYSTEM, user=summary)
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
            risks=list(parsed.get("warnings", [])),
            confidence=0.65,
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
