"""谛听 · 上下文提供者抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class ContextProvider(ABC):
    """上下文提供者接口。

    每个 provider 负责生成一段文本，拼入 AI 引擎的输入摘要。
    实现此接口 + 在 providers/__init__.py 注册 + 配置中启用。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """提供者唯一标识"""
        ...

    @abstractmethod
    def provide(self, code: str, close: np.ndarray, quote=None) -> str | None:
        """生成一段上下文文本。

        Args:
            code: 股票代码
            close: 收盘价数组（从旧到新）
            quote: 实时行情对象（可选，有则用）

        Returns:
            文本片段，None 表示跳过（数据不足等）
        """
        ...
