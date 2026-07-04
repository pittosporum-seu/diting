"""谛听 · 通用装饰器"""

import functools
import hashlib
import json
import time
from typing import Callable

from .logging_config import get_logger

logger = get_logger(__name__)


def cached(ttl_seconds: int = 3600):
    """内存缓存装饰器，key 基于函数名+参数哈希"""

    cache: dict[str, tuple[float, object]] = {}

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key_parts = [func.__name__, json.dumps(args, default=str), json.dumps(kwargs, default=str, sort_keys=True)]
            key = hashlib.sha256("|".join(key_parts).encode()).hexdigest()

            now = time.time()
            if key in cache:
                ts, value = cache[key]
                if now - ts < ttl_seconds:
                    logger.debug("cache.hit", func=func.__name__)
                    return value
                logger.debug("cache.expired", func=func.__name__)

            value = func(*args, **kwargs)
            cache[key] = (now, value)
            logger.debug("cache.miss", func=func.__name__)
            return value

        return wrapper

    return decorator


def retry(max_attempts: int = 3, backoff: float = 2.0, on: tuple = (TimeoutError, ConnectionError)):
    """指数退避重试装饰器"""

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except on as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        wait = backoff**attempt
                        logger.warning("retry.waiting", func=func.__name__, attempt=attempt + 1, wait_seconds=wait)
                        time.sleep(wait)
            logger.error("retry.exhausted", func=func.__name__, attempts=max_attempts)
            raise last_exc  # type: ignore

        return wrapper

    return decorator


def log_latency(func: Callable):
    """记录函数执行时间的装饰器"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("call.latency", func=func.__name__, duration_ms=round(elapsed_ms, 2))

    return wrapper
