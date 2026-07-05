"""谛听 · 分析引擎抽象基类

所有分析引擎必须实现此接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..enums import DataType
from ..schema import AnalysisContext, AnalysisResult


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
