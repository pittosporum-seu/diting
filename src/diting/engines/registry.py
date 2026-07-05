"""谛听 · 分析引擎插件注册机制

@register_engine 装饰器实现开闭原则——加新引擎不改已有代码。
"""

from __future__ import annotations

from .base import AnalysisEngine

_engine_registry: dict[str, type[AnalysisEngine]] = {}


def register_engine(name: str):
    """将分析引擎注册到全局注册表。

    用法:
        @register_engine("my_engine")
        class MyEngine(AnalysisEngine):
            ...
    """

    def decorator(cls: type[AnalysisEngine]):
        _engine_registry[name] = cls
        return cls

    return decorator


def discover_engines() -> list[str]:
    """返回所有已注册的引擎名称"""
    return list(_engine_registry.keys())


def get_engine(name: str) -> type[AnalysisEngine] | None:
    """按名称获取引擎类"""
    return _engine_registry.get(name)
