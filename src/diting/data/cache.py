"""谛听 · TTL 缓存层

为数据提供者提供内存缓存，减少重复 API 调用。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from ..infra.config_loader import ConfigLoader
from ..infra.logging_config import get_logger

logger = get_logger(__name__)


class CacheLayer:
    """内存 TTL 缓存，带 LRU 淘汰。

    使用 OrderedDict 实现，达到 max_size 时淘汰最早插入的条目。
    每个条目在 ttl_seconds 后自动过期。
    """

    def __init__(
        self,
        max_size: int | None = None,
        default_ttl: int | None = None,
    ):
        cache_cfg = ConfigLoader.get_section("pipeline").get("cache", {})
        self._max_size = max_size or cache_cfg.get("max_size", 256)
        self._default_ttl = default_ttl or cache_cfg.get("historical_ttl", 3600)
        self._store: OrderedDict[str, tuple[float, int, Any]] = OrderedDict()

    # ── 公共接口 ──────────────────────────────────

    def get(self, key: str) -> Any | None:
        """获取缓存值，过期返回 None"""
        entry = self._store.get(key)
        if entry is None:
            return None

        ts, ttl, value = entry
        if time.time() - ts > ttl:
            del self._store[key]
            logger.debug("cache.expired", key=key[:80])
            return None

        # LRU: 移到末尾
        self._store.move_to_end(key)
        logger.debug("cache.hit", key=key[:80])
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """写入缓存，自动触发 LRU 淘汰"""
        if len(self._store) >= self._max_size:
            oldest_key, _ = self._store.popitem(last=False)
            logger.debug("cache.evicted", key=oldest_key[:80])

        actual_ttl = ttl if ttl is not None else self._default_ttl
        self._store[key] = (time.time(), actual_ttl, value)
        logger.debug("cache.set", key=key[:80])

    def clear(self) -> None:
        """清空所有缓存"""
        self._store.clear()
        logger.info("cache.cleared")


# ── 模块级单例（供 @cached 装饰器和 Repository 共享）───

_default_cache = CacheLayer()


def get_cache() -> CacheLayer:
    """获取默认缓存实例"""
    return _default_cache
