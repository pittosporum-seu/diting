"""谛听 · Web 服务层 — 公共工具函数与基类

提供无状态的纯工具函数以及共享的服务基类。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...cache import CacheManager
    from ...data.repository import MarketDataRepository
    from ...schema import RealtimeQuote

logger = None  # 延迟导入，避免循环


def _get_logger():
    global logger
    if logger is None:
        from ...infra.logging_config import get_logger

        logger = get_logger(__name__)
    return logger


# ── Rating display labels ──────────────────────────

_RATING_CN: dict[str, str] = {
    "strong_buy": "强烈买入",
    "buy": "建议买入",
    "accumulate": "建议关注",
    "hold": "建议观望",
    "reduce": "建议回避",
    "sell": "建议回避",
}
_RATING_EMOJI: dict[str, str] = {
    "strong_buy": "🟢",
    "buy": "🟢",
    "accumulate": "🟡",
    "hold": "⚪",
    "reduce": "🔴",
    "sell": "🔴",
}


# ── Shared base class ──────────────────────────────


class _BaseService:
    """所有 service 类的共享基类，提供 CacheManager / WatchlistDB / repo 构建。"""

    def __init__(
        self,
        *,
        cache_mgr: CacheManager | None = None,
        watchlist_db=None,
        settings: dict | None = None,
        repo_factory: Callable[[], MarketDataRepository] | None = None,
    ) -> None:
        self._settings = settings if settings is not None else {}
        self._watchlist_db = watchlist_db
        self._stock_list_cache: list[dict] | None = None
        self._cache_mgr = cache_mgr
        self._repo_factory = repo_factory

    def _get_cache_mgr(self) -> CacheManager:
        """获取缓存管理器实例（延迟初始化）。"""
        if self._cache_mgr is None:
            from ...cache import CacheManager

            self._cache_mgr = CacheManager()
        return self._cache_mgr

    def _db(self):
        """获取 WatchlistDB 实例（用于读写 watchlist + settings）。"""
        if self._watchlist_db is None:
            from ...storage import WatchlistDB

            self._watchlist_db = WatchlistDB()
        return self._watchlist_db

    def _load_saved_settings(self) -> dict[str, str]:
        """从 DB 读取已保存的设置。"""
        try:
            return self._db().get_settings()
        except Exception:
            return {}

    def _build_repo(self) -> MarketDataRepository:
        """构建数据仓库，尊重数据源开关设置。

        降级链: east_money → ashare → mx_data → akshare
        每个 provider 有 try/except 保护，单个失败不阻塞整体。
        """
        if self._repo_factory is not None:
            return self._repo_factory()

        from ...data.providers.akshare import AkShareProvider
        from ...data.providers.ashare import AshareProvider
        from ...data.providers.east_money import EastMoneyProvider

        # MxDataProvider — 已全局关闭 (v0.7.2)，需要时取消注释
        # from ...data.providers.mx_data import MxDataProvider
        from ...data.repository import MarketDataRepository

        saved = self._load_saved_settings()
        log = _get_logger()

        providers: list = []
        # mx_key = cfg.get("MX_APIKEY")  # mx-data 已全局关闭 (v0.7.2)

        # ashare（默认启用，新浪/腾讯免费接口）
        if saved.get("provider_ashare", "1") == "1":
            try:
                providers.append(AshareProvider())
            except Exception:
                log.warning("services.build_repo.ashare_failed")

        # east_money（默认启用，免费直连，提供 PE/PB/市值/资金流向）
        if saved.get("provider_eastmoney", "1") == "1":
            try:
                providers.append(EastMoneyProvider())
            except Exception:
                log.warning("services.build_repo.east_money_failed")

        # mx-data — 已全局关闭 (v0.7.2, 2026-07-16)
        # 东方财富 mx-data 免费版每日仅 150 次配额，极易在 cron job 的
        # 批量查询中耗尽。需要时手动取消注释下面这段：
        # if saved.get("provider_mxdata", "1") == "1" and mx_key:
        #     try:
        #         providers.append(MxDataProvider(api_key=mx_key))
        #     except Exception:
        #         log.warning("services.build_repo.mx_data_failed")

        # akshare（默认启用，免费兜底）
        if saved.get("provider_akshare", "1") == "1":
            try:
                providers.append(AkShareProvider())
            except Exception:
                log.warning("services.build_repo.akshare_failed")

        # 兜底：如果全部关闭/失败，至少保留 east_money（免费直连最可靠）
        if not providers:
            providers.append(EastMoneyProvider())

        return MarketDataRepository(providers=providers)


# ── Pure utility functions ─────────────────────────


def extract_chart_arrays(df) -> dict:
    """从历史 DataFrame 提取图表数据（OHLC / Volume / MA / Boll / RSI 序列）。"""
    import numpy as np

    def _safe(v):
        """Convert numpy types to Python native for JSON safety."""
        if v is None:
            return None
        if isinstance(v, (np.floating, float)):
            if np.isnan(v) or np.isinf(v):
                return None
            return float(v)
        if isinstance(v, (np.integer, int)):
            return int(v)
        return v

    # 列名探测
    col_map: dict[str, str] = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("date", "日期", "trade_date"):
            col_map["date"] = c
        elif cl in ("close", "收盘", "收盘价"):
            col_map["close"] = c
        elif cl in ("open", "开盘", "开盘价"):
            col_map["open"] = c
        elif cl in ("high", "最高", "最高价"):
            col_map["high"] = c
        elif cl in ("low", "最低", "最低价"):
            col_map["low"] = c
        elif cl in ("volume", "成交量", "vol"):
            col_map["volume"] = c

    if "date" not in col_map or "close" not in col_map:
        return {}

    dates = [str(d) for d in df[col_map["date"]].tolist()]
    close = df[col_map["close"]].values
    if close.dtype == object:
        close = close.astype(float)
    n = len(close)

    result: dict = {"dates": dates, "prices": [_safe(c) for c in close]}

    # OHLC — 新版前端优先使用 ohlc 字段绘制真蜡烛
    if all(k in col_map for k in ("open", "high", "low")):
        opens = df[col_map["open"]].values
        highs = df[col_map["high"]].values
        lows = df[col_map["low"]].values
        if opens.dtype == object:
            opens = opens.astype(float)
        if highs.dtype == object:
            highs = highs.astype(float)
        if lows.dtype == object:
            lows = lows.astype(float)
        result["ohlc"] = [
            [_safe(o), _safe(c), _safe(lo), _safe(h)]
            for o, c, lo, h in zip(opens, close, lows, highs)
        ]

    # 成交量
    if "volume" in col_map:
        volumes = df[col_map["volume"]].values
        if volumes.dtype == object:
            volumes = volumes.astype(float)
        result["volumes"] = [_safe(v) for v in volumes]

    if n >= 5:
        result["ma_5"] = [
            _safe(v) for v in df[col_map["close"]].astype(float).rolling(window=5).mean()
        ]
    if n >= 20:
        ma20 = df[col_map["close"]].astype(float).rolling(window=20).mean()
        roll = df[col_map["close"]].astype(float).rolling(window=20)
        middle = roll.mean()
        std = roll.std(ddof=1)
        result["ma_20"] = [_safe(v) for v in ma20]
        result["boll_upper"] = [_safe(v) for v in (middle + 2 * std)]
        result["boll_lower"] = [_safe(v) for v in (middle - 2 * std)]

    if n >= 15:
        diff = np.diff(close)
        gain = np.maximum(diff, 0)
        loss = np.maximum(-diff, 0)
        rsi = np.full(n, np.nan)
        avg_gain = float(np.mean(gain[:14]))
        avg_loss = float(np.mean(loss[:14]))
        rsi[14] = 100.0 if avg_loss == 0 else float(100 - 100 / (1 + avg_gain / avg_loss))
        for i in range(15, n):
            avg_gain = (avg_gain * 13 + gain[i - 1]) / 14
            avg_loss = (avg_loss * 13 + loss[i - 1]) / 14
            if avg_loss == 0:
                rsi[i] = 100.0
            else:
                rsi[i] = float(100 - 100 / (1 + avg_gain / avg_loss))
        result["rsi_values"] = [_safe(v) for v in rsi]

    return result


def clean_numpy(obj):
    """Recursively convert numpy/dataclass types to Python natives."""
    from dataclasses import asdict, is_dataclass
    from datetime import datetime as dt

    import numpy as np

    if is_dataclass(obj):
        return clean_numpy(asdict(obj))
    if isinstance(obj, dt):
        return str(obj)
    if isinstance(obj, dict):
        return {k: clean_numpy(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [clean_numpy(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    return obj


def quick_score(q: RealtimeQuote) -> tuple[int, list[str]]:
    """快速评分：涨跌幅连续映射。"""
    signals: list[str] = []
    score = 50.0

    if q.change_pct is not None:
        score += q.change_pct * 3
        if q.change_pct > 4:
            signals.append("强势上涨")
        elif q.change_pct > 2:
            signals.append("温和上涨")
        elif q.change_pct < -4:
            signals.append("大幅下跌")
        elif q.change_pct < -2:
            signals.append("小幅下跌")

    # TODO: 量比需要历史日均成交量，RealtimeQuote 没有此字段
    # 原 turnover/volume 算的是成交均价而非量比，已移除

    score = max(0, min(100, round(score)))
    return score, signals


# ── Stock list cache ───────────────────────────────

_stock_list_cache: list[dict] | None = None


def load_stock_list() -> list[dict]:
    """返回全市场 A 股股票列表 [{code, name}]（模块级缓存）。"""
    global _stock_list_cache
    if _stock_list_cache is not None:
        return _stock_list_cache
    try:
        import json as _json
        from pathlib import Path as _Path

        path = _Path(__file__).resolve().parents[4] / "frontend" / "data" / "stock-list.json"
        if path.exists():
            with open(path) as f:
                _stock_list_cache = _json.load(f)
            return _stock_list_cache
    except Exception:
        _get_logger().warning("services.stock_list.load_failed")
    _stock_list_cache = []
    return _stock_list_cache
