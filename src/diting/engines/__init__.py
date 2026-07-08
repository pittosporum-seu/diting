# 谛听 · 分析引擎 — 自动注册所有引擎
# import 触发 @register_engine 装饰器填充注册表

from . import (
    buffett,  # noqa: F401
    can_slim,  # noqa: F401
    verdict,  # noqa: F401
    vmd_rsi,  # noqa: F401
    volume_profile,  # noqa: F401
    wyckoff,  # noqa: F401
)
