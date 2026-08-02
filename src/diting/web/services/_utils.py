"""谛听 · Web 服务层 — 公共工具函数与基类

提供无状态的纯工具函数以及共享的服务基类。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...cache import CacheManager
    from ...ports import DataGateway
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
        repo_factory: Callable[[], Any] | None = None,
        data_gateway: DataGateway | None = None,
    ) -> None:
        self._settings = settings if settings is not None else {}
        self._watchlist_db = watchlist_db
        self._stock_list_cache: list[dict] | None = None
        self._cache_mgr = cache_mgr
        self._repo_factory = repo_factory
        self._data_gateway = data_gateway

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

    def _build_repo(self) -> Any:
        """Return the injected gateway view; concrete Providers belong to bootstrap only."""
        if self._repo_factory is not None:
            return self._repo_factory()
        if self._data_gateway is None:
            raise RuntimeError("DataGateway was not injected at the composition root")
        from ...adapters.gateway_legacy_view import GatewayLegacyView

        return GatewayLegacyView(self._data_gateway)


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
    """快速评分：多因子轻量筛选（用于全市场初筛，非最终评分）。

    因子（都不需 AI/历史数据，仅用实时行情）：
    1. 涨跌幅（主因子）
    2. 日内位置（收在日内高/低位）
    3. 开盘强度（收盘相对开盘）
    4. 估值（PE，若可得）

    注意：这只是初筛分，排行榜最终用全量引擎分析分（与详情页一致）。
    """
    signals: list[str] = []
    score = 50.0

    # 1. 涨跌幅（主因子）
    if q.change_pct is not None:
        score += q.change_pct * 2.5
        if q.change_pct > 4:
            signals.append("强势上涨")
        elif q.change_pct > 2:
            signals.append("温和上涨")
        elif q.change_pct < -4:
            signals.append("大幅下跌")
        elif q.change_pct < -2:
            signals.append("小幅下跌")

    # 2. 日内位置：收在日内高位更强（0~1）
    try:
        if q.high and q.low and q.high > q.low and q.price is not None:
            pos = (q.price - q.low) / (q.high - q.low)
            score += (pos - 0.5) * 8  # ±4
            if pos > 0.8:
                signals.append("收于日内高位")
            elif pos < 0.2:
                signals.append("收于日内低位")
    except (TypeError, ZeroDivisionError):
        pass

    # 3. 开盘强度：收盘高于开盘 = 尾盘走强
    try:
        if q.open and q.price is not None and q.open > 0:
            open_strength = (q.price - q.open) / q.open * 100
            score += max(-5, min(5, open_strength)) * 0.8  # ±4
            if open_strength > 2:
                signals.append("尾盘走强")
            elif open_strength < -2:
                signals.append("尾盘走弱")
    except (TypeError, ZeroDivisionError):
        pass

    # 4. 估值（PE，若可得）
    if q.pe is not None and q.pe > 0:
        if q.pe < 20:
            score += 3
            signals.append("低估值")
        elif q.pe > 60:
            score -= 3

    score = max(0, min(100, round(score)))
    return score, signals


def coarse_score(q: RealtimeQuote) -> float:
    """粗筛分（方向中性）：执筛全市场选出“值得精筛”的活跃可交易股。

    设计要点：**不以今日涨跌排序**（实验证今日涨幅与最终分负相关），
    避免“形态好但今日横盘/微跌”的股票被挡在精筛池外。
    仅用实时行情，按流动性 + 日内活跃度（方向中性）选池，精筛交给数据驱动技术因子。
    """
    import math

    score = 0.0
    # 1. 流动性（成交额 turnover，元）——主因子，log 缩放，选可交易的
    if q.turnover and q.turnover > 0:
        score += min(50.0, math.log10(q.turnover) * 6.0)  # 1亿≈8→48分
    # 2. 日内振幅（方向中性活跃度）
    try:
        if q.high and q.low and q.open and q.open > 0 and q.high > q.low:
            amp = (q.high - q.low) / q.open * 100
            score += min(25.0, amp * 2.5)
    except (TypeError, ZeroDivisionError):
        pass
    # 3. 今日动能（轻微：强势略优先，但不排除微跌）
    if q.change_pct is not None:
        score += max(-3.0, min(5.0, q.change_pct * 0.5))
    # 4. 估值兑底
    if q.pe is not None and 0 < q.pe < 20:
        score += 3.0
    return max(0.0, min(100.0, round(score, 1)))


# ── 数据驱动初筛（基于缓存历史的技术因子）──────────────
#
# 因子网格搜索结论（详 scripts/factor_search.py）：
# - 今日涨跌幅与最终共识分负相关（-0.23），不能作主因子
# - 有效因子均为多日趋势/位置类：dist_high_20(+0.62) > ret_20d(+0.57)
#   > price_vs_ma20(+0.57) > rsi_14(+0.50) > boll_pos(+0.49) > dist_high_60(+0.46)
# - 成交量类（量比/量趋势）几乎无用
# 回归权重有过拟合（样本外 Spearman 仅 0.28），故采用结构稳健的
# “池内百分位排名 × 相关系数权重”公式（样本 Spearman 0.57，正权重无多共线性）。

# 单因子相关系数（来自网格搜索）+ 微调（tune_weights.py 确认 dist_high_20 主导）
FACTOR_CORR_WEIGHTS: dict[str, float] = {
    "dist_high_20": 0.85,  # 距20日高点，两次实验均 #1，上调
    "ret_20d": 0.45,
    "price_vs_ma20": 0.45,
    "rsi_14": 0.40,
    "boll_pos": 0.40,
    "dist_high_60": 0.45,
}


def _rsi(close, period: int = 14) -> float:
    """RSI(14)。close 为 numpy 数组。"""
    import numpy as np

    if len(close) < period + 1:
        return 50.0
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = gain[-period:].mean()
    avg_loss = loss[-period:].mean()
    if avg_loss == 0:
        return 100.0
    return float(100 - 100 / (1 + avg_gain / avg_loss))


def technical_factors(hist) -> dict | None:
    """从缓存历史数据计算技术因子（需 >=60 根 K 线）。

    返回因子字典；数据不足返回 None。仅用缓存历史，无网络/AI 开销。
    """
    import numpy as np

    if hist is None or hist.df is None or len(hist.df) < 60:
        return None
    df = hist.df
    close = df.get("close", df.get("收盘价"))
    high = df.get("high", df.get("最高价"))
    if close is None:
        return None
    c = np.asarray(close, dtype=float)
    h = np.asarray(high, dtype=float) if high is not None else c
    if len(c) < 60:
        return None
    ma20 = c[-20:].mean()
    std20 = c[-20:].std()
    upper, lower = ma20 + 2 * std20, ma20 - 2 * std20
    h20_max = h[-20:].max()
    h60_max = h[-60:].max()
    return {
        "dist_high_20": float(c[-1] / h20_max) if h20_max > 0 else 0.0,
        "ret_20d": float(c[-1] / c[-21] - 1) if c[-21] > 0 else 0.0,
        "price_vs_ma20": float((c[-1] - ma20) / ma20) if ma20 > 0 else 0.0,
        "rsi_14": _rsi(c, 14),
        "boll_pos": float((c[-1] - lower) / (upper - lower)) if upper > lower else 0.5,
        "dist_high_60": float(c[-1] / h60_max) if h60_max > 0 else 0.0,
    }


def rank_score_pool(factor_map: dict[str, dict]) -> dict[str, float]:
    """数据驱动初筛打分：池内各因子百分位排名 × 相关系数权重，归一到 0-100。

    Args:
        factor_map: {code: technical_factors 字典}
    Returns:
        {code: 初筛分 0-100}（池内相对排名，用于排序选 Top N）
    """
    import numpy as np

    codes = list(factor_map.keys())
    n = len(codes)
    if n == 0:
        return {}
    scores = {c: 0.0 for c in codes}
    total_w = sum(FACTOR_CORR_WEIGHTS.values())
    for fn, w in FACTOR_CORR_WEIGHTS.items():
        vals = np.array([factor_map[c].get(fn, 0.0) for c in codes])
        ranks = np.argsort(np.argsort(vals)).astype(float) / max(1, n - 1)
        for i, c in enumerate(codes):
            scores[c] += w * float(ranks[i])
    return {c: round(s / total_w * 100, 1) for c, s in scores.items()}


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
            with open(path, encoding="utf-8") as f:
                _stock_list_cache = _json.load(f)
            return _stock_list_cache
    except Exception:
        _get_logger().warning("services.stock_list.load_failed")
    _stock_list_cache = []
    return _stock_list_cache
