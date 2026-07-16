"""谛听 · 分析引擎抽象基类

所有分析引擎必须实现此接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..ai.output_schema import AiEngineOutput
from ..enums import DataType
from ..infra.logging_config import get_logger
from ..schema import AnalysisContext, AnalysisResult

logger = get_logger(__name__)


class AnalysisEngine(ABC):
    """分析引擎抽象基类。

    定义所有引擎的统一契约。新引擎 = 新建文件 + 继承此 ABC + @register_engine。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎唯一标识，如 'wyckoff', 'buffett'"""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """引擎版本号"""
        ...

    @abstractmethod
    def required_data(self) -> list[DataType]:
        """声明需要的数据类型，管道据此获取数据"""
        ...

    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        """执行分析。

        Args:
            context: 完整的分析上下文（行情 + 信号 + 财务）

        Returns:
            AnalysisResult 包含评分、评级、信号、解读
        """
        ...

    def validate_context(self, context: AnalysisContext) -> bool:
        """验证上下文是否满足引擎要求（可选覆写）"""
        required = self.required_data()
        if DataType.HISTORICAL in required and context.historical is None:
            return False
        if DataType.REALTIME in required and context.realtime is None:
            return False
        return True

    # ---- AI 引擎共享方法 ----

    @staticmethod
    def _extract_code_block(code: str) -> str:
        """从 AI 响应中提取 Python 代码块。

        处理 markdown 代码块（```python ... ``` 或 ``` ... ```），
        如果没有代码块标记则返回原始文本。
        """
        if "```python" in code:
            return code.split("```python")[1].split("```")[0].strip()
        if "```" in code:
            return code.split("```")[1].split("```")[0].strip()
        return code

    def _run_ai(self, system_prompt: str, user_prompt: str) -> AiEngineOutput:
        """执行 AI 分析的标准流程：调 AI → 跑沙箱 → 解析输出。

        封装了 AI 引擎的完整执行流程，失败时自动重试 1 次。
        各 AI 引擎只需提供差异化的 system_prompt 和 user_prompt 即可。

        Args:
            system_prompt: AI 的 system prompt（定义输出格式和分析方法）
            user_prompt: 用户消息（包含具体数据摘要）

        Returns:
            解析后的 AiEngineOutput（解析失败时返回 score=50 的默认输出）
        """
        from ..ai.output_parser import AiOutputParser

        # Step 1: AI 生成计算代码
        code = self._llm.complete(system=system_prompt, user=user_prompt)
        code = self._extract_code_block(code)

        # Step 2: 沙箱执行
        result = self._sandbox.run(code)

        # Step 3: 如果沙箱出错，AI 修复后重试 1 次
        if result.get("errors"):
            logger.warning(
                "engine.sandbox_error.retrying",
                engine=self.name,
                errors=str(result["errors"])[:200],
            )
            fix_code = self._llm.complete(
                system=(
                    "You are a Python code fixer. Fix the following code that had errors "
                    "when executed. Return ONLY the corrected Python code, no explanation."
                ),
                user=(
                    f"Code that failed:\n```python\n{code}\n```\n\n"
                    f"Errors:\n{result['errors']}\n\n"
                    f"Return the fixed Python code only."
                ),
            )
            fix_code = self._extract_code_block(fix_code)
            result = self._sandbox.run(fix_code)

        # Step 4: 解析输出
        raw_output = result.get("output", "")
        ai_output = AiOutputParser.parse(raw_output)

        if ai_output.score == 50.0 and not ai_output.narrative:
            logger.warning(
                "engine.parse_failed",
                engine=self.name,
                raw_preview=raw_output[:200],
            )

        return ai_output
