"""谛听 · MarketState 单元测试"""

from datetime import date, datetime

import pytest

from src.diting.cache.market_state import (
    MarketState,
    _find_last_trade_day,
    _find_next_trade_day,
    _is_trade_day,
    get_market_state,
)


class TestIsTradeDay:
    """交易日判断测试。"""

    def test_weekday_is_trade_day(self):
        """周一至周五默认为交易日。"""
        # 2026-07-13 是周一
        assert _is_trade_day(date(2026, 7, 13)) is True
        # 2026-07-14 是周二
        assert _is_trade_day(date(2026, 7, 14)) is True
        # 2026-07-17 是周五
        assert _is_trade_day(date(2026, 7, 17)) is True

    def test_weekend_is_not_trade_day(self):
        """周六日默认为非交易日。"""
        # 2026-07-11 是周六
        assert _is_trade_day(date(2026, 7, 11)) is False
        # 2026-07-12 是周日
        assert _is_trade_day(date(2026, 7, 12)) is False

    def test_holiday_is_not_trade_day(self):
        """法定假日为非交易日。"""
        # 国庆节 2026-10-01
        assert _is_trade_day(date(2026, 10, 1)) is False
        # 中秋节 2026-09-25（周五但是假日）
        assert _is_trade_day(date(2026, 9, 25)) is False

    def test_work_weekend_is_trade_day(self):
        """调休上班的周末为交易日。"""
        # 2026-09-19（周六但调休上班）
        assert _is_trade_day(date(2026, 9, 19)) is True
        # 2026-10-10（周六但调休上班）
        assert _is_trade_day(date(2026, 10, 10)) is True


class TestMarketState:
    """MarketState 获取测试。"""

    def test_trading_morning(self):
        """盘中上午时段返回 trading。"""
        now = datetime(2026, 7, 14, 10, 0, 0)  # 周二 10:00
        state = get_market_state(now)
        assert state.phase == "trading"
        assert state.today_is_trade_day is True
        assert state.should_call_api is True
        assert state.is_trading is True

    def test_trading_afternoon(self):
        """盘中下午时段返回 trading。"""
        now = datetime(2026, 7, 14, 14, 0, 0)  # 周二 14:00
        state = get_market_state(now)
        assert state.phase == "trading"
        assert state.today_is_trade_day is True

    def test_closed_after_market(self):
        """收盘后返回 closed。"""
        now = datetime(2026, 7, 14, 16, 0, 0)  # 周二 16:00
        state = get_market_state(now)
        assert state.phase == "closed"
        assert state.today_is_trade_day is True
        assert state.should_call_api is False
        assert state.is_closed is True

    def test_closed_before_market(self):
        """盘前返回 closed。"""
        now = datetime(2026, 7, 14, 8, 0, 0)  # 周二 8:00
        state = get_market_state(now)
        assert state.phase == "closed"
        assert state.today_is_trade_day is True

    def test_closed_lunch_break(self):
        """午休时段返回 closed。"""
        now = datetime(2026, 7, 14, 12, 0, 0)  # 周二 12:00
        state = get_market_state(now)
        assert state.phase == "closed"

    def test_weekend_saturday(self):
        """周六返回 weekend。"""
        now = datetime(2026, 7, 11, 10, 0, 0)  # 周六
        state = get_market_state(now)
        assert state.phase == "weekend"
        assert state.today_is_trade_day is False
        assert state.should_call_api is False
        assert state.is_weekend is True

    def test_weekend_sunday(self):
        """周日返回 weekend。"""
        now = datetime(2026, 7, 12, 14, 0, 0)  # 周日
        state = get_market_state(now)
        assert state.phase == "weekend"

    def test_holiday_returns_weekend(self):
        """法定假日返回 weekend。"""
        now = datetime(2026, 10, 1, 10, 0, 0)  # 国庆节（周四）
        state = get_market_state(now)
        assert state.phase == "weekend"

    def test_work_weekend_returns_trade_day(self):
        """调休上班的周末按交易日处理。"""
        now = datetime(2026, 9, 19, 10, 0, 0)  # 周六但调休
        state = get_market_state(now)
        assert state.today_is_trade_day is True
        assert state.phase == "trading"  # 上午10点

    def test_last_trade_date_monday(self):
        """周一的上个交易日是上周五。"""
        now = datetime(2026, 7, 13, 10, 0, 0)  # 周一
        state = get_market_state(now)
        assert state.last_trade_date == date(2026, 7, 10)  # 上周五

    def test_next_trade_date_friday(self):
        """周五的下个交易日是下周一。"""
        now = datetime(2026, 7, 17, 10, 0, 0)  # 周五
        state = get_market_state(now)
        assert state.next_trade_date == date(2026, 7, 20)  # 下周一

    def test_closed_last_trade_is_today(self):
        """盘后 last_trade_date 是今天。"""
        now = datetime(2026, 7, 14, 16, 0, 0)
        state = get_market_state(now)
        assert state.last_trade_date == date(2026, 7, 14)

    def test_closed_before_market_last_trade(self):
        """盘前 last_trade_date 是上一个交易日。"""
        now = datetime(2026, 7, 14, 8, 0, 0)
        state = get_market_state(now)
        # 上个交易日是周一 7/13
        assert state.last_trade_date == date(2026, 7, 13)


class TestMarketStateProperties:
    """MarketState 属性测试。"""

    def test_trading_properties(self):
        """trading 状态的布尔属性。"""
        state = MarketState(
            phase="trading",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )
        assert state.should_call_api is True
        assert state.is_trading is True
        assert state.is_closed is False
        assert state.is_weekend is False

    def test_closed_properties(self):
        """closed 状态的布尔属性。"""
        state = MarketState(
            phase="closed",
            last_trade_date=date(2026, 7, 14),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )
        assert state.should_call_api is False
        assert state.is_trading is False
        assert state.is_closed is True
        assert state.is_weekend is False

    def test_weekend_properties(self):
        """weekend 状态的布尔属性。"""
        state = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )
        assert state.should_call_api is False
        assert state.is_trading is False
        assert state.is_closed is False
        assert state.is_weekend is True

    def test_frozen_dataclass(self):
        """MarketState 是不可变的。"""
        state = get_market_state(datetime(2026, 7, 14, 10, 0, 0))
        with pytest.raises(Exception):
            state.phase = "weekend"  # type: ignore[misc]


class TestEdgeCases:
    """边界情况测试。"""

    def test_market_open_exactly(self):
        """9:30 整是 trading。"""
        now = datetime(2026, 7, 14, 9, 30, 0)
        state = get_market_state(now)
        assert state.phase == "trading"

    def test_market_close_exactly(self):
        """15:00 整是 trading（收盘瞬间仍在交易）。"""
        now = datetime(2026, 7, 14, 15, 0, 0)
        state = get_market_state(now)
        assert state.phase == "trading"

    def test_market_close_one_second_after(self):
        """15:00:01 是 closed。"""
        now = datetime(2026, 7, 14, 15, 0, 1)
        state = get_market_state(now)
        assert state.phase == "closed"

    def test_no_arg_uses_current_time(self):
        """不传 now 参数时使用当前时间。"""
        state = get_market_state()
        assert state.phase in ("trading", "closed", "weekend")
        assert isinstance(state.today_is_trade_day, bool)


class TestFindTradeDay:
    """交易日查找测试。"""

    def test_find_last_from_monday(self):
        """从周一开始找上一个交易日。"""
        result = _find_last_trade_day(date(2026, 7, 13))  # 周一
        assert result == date(2026, 7, 10)  # 上周五

    def test_find_next_from_friday(self):
        """从周五开始找下一个交易日。"""
        result = _find_next_trade_day(date(2026, 7, 17))  # 周五
        assert result == date(2026, 7, 20)  # 下周一

    def test_find_last_from_holiday(self):
        """从假日开始找上一个交易日。"""
        result = _find_last_trade_day(date(2026, 10, 2))  # 国庆节第二天
        assert result == date(2026, 9, 30)  # 9月30日（周三）

    def test_find_next_from_holiday(self):
        """从假日开始找下一个交易日。"""
        result = _find_next_trade_day(date(2026, 10, 2))
        # 国庆到 10/7，10/8 是周四
        assert result == date(2026, 10, 8)
