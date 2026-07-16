"""谛听 · 统一数据仓储层

实现三级降级链：mx-data → akshare → SQLite cache。
所有上层模块通过此接口获取数据，不直接依赖具体数据源。
"""

from __future__ import annotations

from datetime import date, datetime

from ..infra.errors import AllProvidersFailedError, DataUnavailableError
from ..infra.logging_config import get_logger
from ..schema import HistoricalData, RealtimeQuote
from .cache import CacheLayer
from .providers.base import DataProvider

logger = get_logger(__name__)

_COLUMN_MAP = {
    "收盘": "close",
    "收盘价": "close",
    "开盘": "open",
    "开盘价": "open",
    "最高": "high",
    "最高价": "high",
    "最低": "low",
    "最低价": "low",
    "成交量": "volume",
    "成交额": "turnover",
    "日期": "date",
    "交易日期": "date",
    "时间": "time",
    "涨跌幅": "change_pct",
}


def _normalize_columns(df):
    """Return a copy with Chinese market-data columns normalized to English."""
    if df is None or not hasattr(df, "columns"):
        return df

    existing = set(df.columns)
    rename_map = {
        column: normalized
        for column, normalized in _COLUMN_MAP.items()
        if column in existing and normalized not in existing
    }
    return df.rename(columns=rename_map).copy()


def _normalize_historical(data: HistoricalData) -> HistoricalData:
    """Normalize one historical payload without mutating provider-owned data."""
    normalized_df = _normalize_columns(data.df)
    columns = list(normalized_df.columns) if hasattr(normalized_df, "columns") else [
        _COLUMN_MAP.get(column, column) for column in data.columns
    ]
    return HistoricalData(
        symbol=data.symbol,
        df=normalized_df,
        columns=columns,
        start_date=data.start_date,
        end_date=data.end_date,
        source=data.source,
    )


class MarketDataRepository:
    """统一数据访问层。

    接收一组 DataProvider（按 priority 排序），
    对每个请求按优先级尝试，自动降级。

    用法:
        repo = MarketDataRepository([MxDataProvider(), AkShareProvider()])
        quotes = repo.get_realtime(["002475"])
        hist = repo.get_historical("002475", start, end)
    """

    def __init__(
        self,
        providers: list[DataProvider],
        cache: CacheLayer | None = None,
    ):
        """初始化仓储。

        Args:
            providers: 数据源列表，按 priority 由低到高排序。
                       优先级最高的排最前面。
            cache: 缓存层，默认为模块级单例。
        """
        self._providers = sorted(providers, key=lambda p: p.priority)
        self._cache = cache or CacheLayer()

    @property
    def available_providers(self) -> list[str]:
        """返回当前可用的数据源名称列表"""
        return [p.name for p in self._providers if p.health_check()]

    # ── 公共接口 ──────────────────────────────────

    def get_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        """获取实时行情，自动降级。

        先查缓存，未命中则按优先级尝试各数据源。
        成功获取的数据写入缓存。

        Raises:
            AllProvidersFailedError: 所有数据源均不可用
        """
        if not symbols:
            return {}

        results: dict[str, RealtimeQuote] = {}
        uncached: list[str] = []

        # 先查缓存
        for sym in symbols:
            cached = self._cache.get(f"realtime:{sym}")
            if cached is not None:
                results[sym] = cached
                logger.debug("repository.realtime.cache_hit", symbol=sym)
            else:
                uncached.append(sym)

        if not uncached:
            return results

        # 从数据源获取
        errors: list[str] = []
        for provider in self._providers:
            if not provider.health_check():
                logger.debug(
                    "repository.provider.unhealthy",
                    provider=provider.name,
                )
                continue

            try:
                logger.info(
                    "repository.realtime.fetching",
                    provider=provider.name,
                    count=len(uncached),
                )
                fresh = provider.fetch_realtime(uncached)
            except DataUnavailableError as e:
                logger.warning(
                    "repository.realtime.failed",
                    provider=provider.name,
                    error=str(e),
                )
                errors.append(f"{provider.name}: {e}")
                continue

            # 写入缓存 + 标注来源
            now = datetime.now()
            for sym, quote in fresh.items():
                cached_quote = RealtimeQuote(
                    symbol=quote.symbol,
                    name=quote.name,
                    price=quote.price,
                    change_pct=quote.change_pct,
                    open=quote.open,
                    high=quote.high,
                    low=quote.low,
                    volume=quote.volume,
                    turnover=quote.turnover,
                    pe=quote.pe,
                    pb=quote.pb,
                    total_mv=quote.total_mv,
                    timestamp=now,
                    source=provider.name,  # 标注数据来源
                )
                self._cache.set(f"realtime:{sym}", cached_quote)
                results[sym] = cached_quote

            # 检查是否还有未获取的
            still_missing = [s for s in uncached if s not in results]
            if still_missing:
                logger.debug(
                    "repository.realtime.partial",
                    provider=provider.name,
                    missing=still_missing,
                    # 继续用下一个 provider
                )
                uncached = still_missing
                continue

            # 全部获取成功
            break
        else:
            # 所有 provider 都试过了
            if uncached:
                msg = "; ".join(errors) if errors else "all providers exhausted"
                raise AllProvidersFailedError(
                    f"Failed to get realtime data for {uncached}: {msg}"
                )

        return results

    def get_historical(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> HistoricalData:
        """获取历史日线行情，自动降级。

        Raises:
            AllProvidersFailedError: 所有数据源均不可用
        """
        cache_key = f"historical:{symbol}:{start}:{end}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("repository.historical.cache_hit", symbol=symbol)
            return _normalize_historical(cached)

        errors: list[str] = []
        for provider in self._providers:
            if not provider.health_check():
                continue

            try:
                logger.info(
                    "repository.historical.fetching",
                    provider=provider.name,
                    symbol=symbol,
                )
                data = _normalize_historical(provider.fetch_historical(symbol, start, end))
                self._cache.set(cache_key, data)
                return data
            except DataUnavailableError as e:
                logger.warning(
                    "repository.historical.failed",
                    provider=provider.name,
                    symbol=symbol,
                    error=str(e),
                )
                errors.append(f"{provider.name}: {e}")
                continue

        msg = "; ".join(errors) if errors else "no providers available"
        raise AllProvidersFailedError(
            f"Failed to get historical data for {symbol}: {msg}"
        )

    def health_check(self) -> dict[str, bool]:
        """检查所有数据源的可达性"""
        return {p.name: p.health_check() for p in self._providers}
