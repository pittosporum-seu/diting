# DEPRECATED: use CacheManager (cache/cache_manager.py) instead.
# This module is kept for backward compatibility only.
# All new code should use CacheManager.mem_get_adaptive() / mem_set().
"""Web 层 TTL 内存缓存 — 零依赖、线程安全

v0.6.5: TTL 统一调整为 300s (5min)，与后台预刷新间隔一致。
v0.7.0: MarketState-aware TTL —— 交易时段高频刷新，盘后/周末到下次开盘。
v0.7.1: DEPRECATED — 缓存实例已迁移至 CacheManager。
"""

import threading
import time
from datetime import datetime, timedelta


class TTLCache:
    """简单 TTL 缓存，线程安全。"""

    def __init__(self, ttl_seconds: int, max_size: int = 128):
        self._ttl = ttl_seconds
        self._max = max_size
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if time.time() - ts > self._ttl:
                del self._data[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value: object) -> None:
        with self._lock:
            if len(self._data) >= self._max:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                del self._data[oldest]
            self._data[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "max_size": self._max,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            }


def _get_ttl(trading_ttl: int) -> int:
    """Resolve the effective TTL based on current MarketState.

    During TRADING, use the trading_ttl (e.g. 30s for realtime quotes).
    Outside trading hours, return a very large TTL (24h+) so data stays
    cached until the next market open.
    """
    try:
        from ..cache.market_state import get_market_state

        state = get_market_state()
        if state.is_trading:
            return trading_ttl
        # CLOSED / WEEKEND: keep cached until next open
        now = datetime.now()
        next_open = datetime.combine(
            state.next_trade_date,
            datetime.strptime("09:30", "%H:%M").time(),
        )
        if next_open <= now:
            next_open += timedelta(days=1)
        seconds_until_open = int((next_open - now).total_seconds())
        return max(seconds_until_open, 3600)  # at least 1h
    except Exception:
        return trading_ttl  # fallback: use trading TTL


class AdaptiveTTLCache(TTLCache):
    """TTLCache with MarketState-aware TTL.

    Adjusts the effective TTL based on whether the market is trading.
    During trading hours, uses the short ttl; outside, keeps data until next open.
    """

    def __init__(self, trading_ttl: int, max_size: int = 128):
        super().__init__(ttl_seconds=trading_ttl, max_size=max_size)
        self._trading_ttl = trading_ttl

    def _effective_ttl(self) -> int:
        return _get_ttl(self._trading_ttl)

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if time.time() - ts > self._effective_ttl():
                del self._data[key]
                self._misses += 1
                return None
            self._hits += 1
            return value


# ── v0.7.0 MarketState-aware cache instances ────

# TRADING: 30s | CLOSED/WEEKEND: to next open
_realtime_cache = AdaptiveTTLCache(trading_ttl=30, max_size=64)

# TRADING: 60s | CLOSED/WEEKEND: to next open
_stock_analysis_cache = AdaptiveTTLCache(trading_ttl=60, max_size=32)

# TRADING: 60s | CLOSED/WEEKEND: to next open
_dashboard_cache = AdaptiveTTLCache(trading_ttl=60, max_size=4)

# TRADING: 120s | CLOSED/WEEKEND: to next open
_opportunities_cache = AdaptiveTTLCache(trading_ttl=120, max_size=4)

# TRADING: 300s | CLOSED/WEEKEND: to next open
_market_sentiment_cache = AdaptiveTTLCache(trading_ttl=300, max_size=4)

# Historical K-line: 600s in trading, longer otherwise
_historical_cache = AdaptiveTTLCache(trading_ttl=600, max_size=64)

# Full market scan: 1h always (already conservative)
_market_scan_cache = TTLCache(ttl_seconds=3600, max_size=4)
