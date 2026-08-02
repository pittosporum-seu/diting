"""谛听 · 上下文提供者插件包

每个 provider 负责生成一段文本，由 ContextBuilder 按配置顺序拼接。
新增 provider = 新建文件 + 实现 ContextProvider + 配置中启用。
"""

from .base import ContextProvider
from .price_basic import PriceBasicProvider
from .vmd_cycle import VmdCycleProvider

# 注册表：名称 → 类
PROVIDER_REGISTRY: dict[str, type[ContextProvider]] = {
    "price_basic": PriceBasicProvider,
    "vmd_cycle_state": VmdCycleProvider,
}


def get_provider(name: str) -> type[ContextProvider] | None:
    return PROVIDER_REGISTRY.get(name)


def all_providers() -> list[str]:
    return list(PROVIDER_REGISTRY.keys())
