"""谛听 · MarketState — 市场状态判断模块

判断当前 A 股市场状态：交易中 / 已收盘 / 非交易日。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from ..infra.logging_config import get_logger

logger = get_logger(__name__)

# ── 2026 年 A 股法定假日白名单（全年）──
# 格式: date(年, 月, 日)
_HOLIDAYS: set[date] = {
    # 元旦 2026-01-01 ~ 2026-01-03
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    # 春节 2026-02-15 ~ 2026-02-21
    date(2026, 2, 15), date(2026, 2, 16), date(2026, 2, 17),
    date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20), date(2026, 2, 21),
    # 清明节 2026-04-04 ~ 2026-04-06
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    # 劳动节 2026-05-01 ~ 2026-05-05
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 5, 4), date(2026, 5, 5),
    # 端午节 2026-06-25 ~ 2026-06-27
    date(2026, 6, 25), date(2026, 6, 26), date(2026, 6, 27),
    # 中秋节 2026-09-25 ~ 2026-09-27
    date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27),
    # 国庆节 2026-10-01 ~ 2026-10-07
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
}

# 调休上班日（周末但上班）
_WORK_WEEKENDS: set[date] = {
    # 春节调休: 2026-02-14(六), 2026-02-22(日)
    date(2026, 2, 14), date(2026, 2, 22),
    # 劳动节调休: 2026-04-26(日), 2026-05-09(六)
    date(2026, 4, 26), date(2026, 5, 9),
    # 国庆调休: 2026-09-19(六), 2026-10-10(六)
    date(2026, 9, 19), date(2026, 10, 10),
}

# ── A 股交易时段 ──
_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 0)
_AFTERNOON_END = time(15, 0)


@dataclass(frozen=True)
class MarketState:
    """市场状态。

    Attributes:
        phase: 当前阶段 — "trading" / "closed" / "weekend"
        last_trade_date: 上一个交易日
        next_trade_date: 下一个交易日
        today_is_trade_day: 今天是不是交易日
    """

    phase: Literal["trading", "closed", "weekend"]
    last_trade_date: date
    next_trade_date: date
    today_is_trade_day: bool

    @property
    def should_call_api(self) -> bool:
        """是否应该调用外部 API 获取数据。"""
        return self.phase == "trading"

    @property
    def is_weekend(self) -> bool:
        """是否为周末/节假日。"""
        return self.phase == "weekend"

    @property
    def is_closed(self) -> bool:
        """是否已收盘（今日是交易日但已过交易时间）。"""
        return self.phase == "closed"

    @property
    def is_trading(self) -> bool:
        """是否正在交易时段。"""
        return self.phase == "trading"


def _is_trade_day(d: date) -> bool:
    """判断指定日期是否为 A 股交易日。"""
    # 周末
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        # 调休上班日
        if d in _WORK_WEEKENDS:
            return True
        return False
    # 法定假日
    if d in _HOLIDAYS:
        return False
    return True


def _find_last_trade_day(d: date) -> date:
    """从 d 往前找最近一个交易日。"""
    cursor = d - timedelta(days=1)
    # 最多回推 30 天
    for _ in range(30):
        if _is_trade_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    # 兜底返回前一天
    return d - timedelta(days=1)


def _find_next_trade_day(d: date) -> date:
    """从 d 往后找最近一个交易日。"""
    cursor = d + timedelta(days=1)
    for _ in range(30):
        if _is_trade_day(cursor):
            return cursor
        cursor += timedelta(days=1)
    return d + timedelta(days=1)


def _check_stock_dict_refresh() -> bool:
    """检查 stock_dict 表是否有今天的刷新记录。

    有则说明今天已经交易过/数据已刷新，可以直接返回 DB 数据。
    返回 True 表示今天有刷新记录。
    """
    try:
        from .cache_manager import CacheManager
        cm = CacheManager()
        row = cm.db_get("stock_dict", "__last_refresh__")
        if row and row.get("updated_at"):
            updated = row["updated_at"]
            if isinstance(updated, datetime):
                return updated.date() == date.today()
            if isinstance(updated, str):
                return updated[:10] == str(date.today())
        return False
    except Exception:
        return False


def _update_stock_dict_refresh() -> None:
    """更新 stock_dict 刷新记录。"""
    try:
        from .cache_manager import CacheManager
        cm = CacheManager()
        cm.db_set("stock_dict", "__last_refresh__", {
            "name": "__last_refresh__",
            "pinyin": "",
            "market": "",
            "status": "ok",
            "updated_at": datetime.now(),
        })
    except Exception:
        pass


def get_market_state(now: datetime | None = None) -> MarketState:
    """获取当前 A 股市场状态。

    Args:
        now: 当前时间（测试时可注入固定时间）。

    Returns:
        MarketState 实例。
    """
    if now is None:
        now = datetime.now()

    today = now.date()
    today_is_trade = _is_trade_day(today)

    # 非交易日
    if not today_is_trade:
        last_trade = _find_last_trade_day(today)
        next_trade = _find_next_trade_day(today)
        return MarketState(
            phase="weekend",
            last_trade_date=last_trade,
            next_trade_date=next_trade,
            today_is_trade_day=False,
        )

    # 交易日 — 判断交易时段
    current_time = now.time()
    is_morning = _MORNING_START <= current_time <= _MORNING_END
    is_afternoon = _AFTERNOON_START <= current_time <= _AFTERNOON_END

    if is_morning or is_afternoon:
        last_trade = _find_last_trade_day(today)
        next_trade = _find_next_trade_day(today)
        return MarketState(
            phase="trading",
            last_trade_date=last_trade,
            next_trade_date=next_trade,
            today_is_trade_day=True,
        )

    # 交易日但不在交易时段 — 盘后/盘前
    last_trade = today if current_time > _AFTERNOON_END else _find_last_trade_day(today)
    next_trade = _find_next_trade_day(today)

    return MarketState(
        phase="closed",
        last_trade_date=last_trade,
        next_trade_date=next_trade,
        today_is_trade_day=True,
    )


def record_refresh() -> None:
    """记录一次数据刷新（用于 stock_dict 表标记）。"""
    _update_stock_dict_refresh()
