"""谛听 · 上下文构建器（可拆卸架构）

读配置中的 context_providers 列表，按顺序调用各 provider 拼接摘要。
任何引擎（batch_ai / wyckoff 单股 / 未来新引擎）共用此构建器。

用法:
    builder = ContextBuilder()  # 从 config 读 provider 列表
    summary = builder.build("002475", close_array, quote_obj)
"""

from __future__ import annotations

import numpy as np

from ..infra.config_loader import ConfigLoader
from ..infra.logging_config import get_logger
from .providers import PROVIDER_REGISTRY, ContextProvider

logger = get_logger(__name__)

# 默认启用的 providers（配置缺失时的兜底）
DEFAULT_PROVIDERS = ["price_basic"]


class ContextBuilder:
    """可拆卸的上下文构建器。

    按配置的 provider 列表顺序调用，拼接各段文本。
    """

    def __init__(self, provider_names: list[str] | None = None):
        if provider_names is None:
            cfg = ConfigLoader.get_section("context")
            provider_names = cfg.get("providers", DEFAULT_PROVIDERS)

        self._providers: list[ContextProvider] = []
        for name in provider_names:
            cls = PROVIDER_REGISTRY.get(name)
            if cls:
                self._providers.append(cls())
            else:
                logger.warning("context_builder.unknown_provider", name=name)

    @property
    def active_providers(self) -> list[str]:
        return [p.name for p in self._providers]

    def build(self, code: str, close: np.ndarray, quote=None) -> str | None:
        """组装完整摘要 = 各 provider 输出拼接。

        Args:
            code: 股票代码
            close: 收盘价数组
            quote: 实时行情（可选）

        Returns:
            拼接后的文本，全部失败返回 None
        """
        parts: list[str] = []
        for provider in self._providers:
            try:
                text = provider.provide(code, close, quote)
                if text:
                    parts.append(text)
            except Exception as e:
                logger.debug(
                    "context_builder.provider_failed",
                    provider=provider.name,
                    code=code,
                    error=str(e),
                )

        if not parts:
            return None
        return "\n".join(parts)
