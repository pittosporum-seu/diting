"""谛听 · 巴菲特/芒格价值评分引擎（AI + 沙箱）"""

from ..ai.client import AIClient, get_llm
from ..enums import DataType, Rating
from ..infra.logging_config import get_logger
from ..sandbox.executor import SandboxExecutor
from ..schema import AnalysisContext, AnalysisResult
from .base import AnalysisEngine
from .rating import score_to_rating
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
    "narrative": "基于护城河、财务质量、管理层、估值和成长性的中文分析，引用关键指标",
    "bull_reasons": ["看多理由1", "看多理由2", "看多理由3"],
    "bear_reasons": ["看空理由1", "看空理由2", "看空理由3"]
}
每条理由必须具体、可验证并引用输入中的财务或估值指标；证据不足时返回空数组，禁止编造。

重要：代码必须自含所需数据（从上述摘要中取值），最后调用 analyze() 并用 print() 将返回的 dict 打印到标准输出（这是结果被捕获的唯一方式，不 print 则视为无输出）。
"""


@register_engine("buffett")
class BuffettEngine(AnalysisEngine):
    name = "buffett"
    version = "1.0.0"

    def __init__(self, llm=None, sandbox=None):
        self._llm = llm or get_llm()
        self._sandbox = sandbox or SandboxExecutor()

    def required_data(self):
        return [DataType.FUNDAMENTALS, DataType.REALTIME]

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        if not context.realtime:
            return AnalysisResult(
                engine_name=self.name,
                engine_version=self.version,
                symbol=context.symbol,
                score=0,
                rating=Rating.HOLD,
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

        output = self._run_ai(BUFFETT_SYSTEM, summary)

        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=context.symbol,
            score=output.score,
            rating=score_to_rating(output.score),
            narrative=output.narrative,
            risks=tuple(output.risks),
            confidence=0.65,
            metadata={
                **output.metadata,
                "bull_reasons": output.bull_reasons[:3],
                "bear_reasons": output.bear_reasons[:3],
            },
        )
