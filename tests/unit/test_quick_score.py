"""谛听 · `quick_score` 单元测试

覆盖 v0.7.6 多因子快速评分：涨跌幅 + 日内位置 + 开盘强度 + 估值。
注意：quick_score 仅用于全市场初筛，排行榜最终用全量引擎分析分。
"""

from dataclasses import dataclass

from src.diting.web.services._utils import quick_score


@dataclass
class _MockQuote:
    """模拟 RealtimeQuote，只包含 quick_score 用到的字段。"""

    symbol: str = "000001"
    name: str = "测试"
    price: float = 10.0
    change_pct: float = 0.0
    open: float = 10.0
    high: float = 10.0
    low: float = 10.0
    volume: int = 0
    turnover: float = 0.0
    pe: float | None = None


class TestQuickScoreChangePct:
    """涨跌幅主因子（high=low=open=price 时其余因子不生效）。"""

    def test_large_gain(self):
        """大涨 >4% → 50+5.2*2.5=63，信号"强势上涨"。"""
        q = _MockQuote(change_pct=5.2)
        score, signals = quick_score(q)
        assert 60 <= score <= 66, f"大涨得分应在 60-66，实际 {score}"
        assert "强势上涨" in signals

    def test_moderate_gain(self):
        """上涨 2-4% → 50+3*2.5=57.5≈58，信号"温和上涨"。"""
        q = _MockQuote(change_pct=3.0)
        score, signals = quick_score(q)
        assert 56 <= score <= 60, f"温和上涨得分应在 56-60，实际 {score}"
        assert "温和上涨" in signals

    def test_slight_gain(self):
        """微涨 0.5% → 50+1.25≈51，无信号。"""
        q = _MockQuote(change_pct=0.5)
        score, signals = quick_score(q)
        assert score in (51, 52), f"微涨得分应在 51-52，实际 {score}"
        assert signals == []

    def test_flat(self):
        """平盘 0% → 50，无信号。"""
        q = _MockQuote(change_pct=0.0)
        score, signals = quick_score(q)
        assert score == 50, f"平盘得分应为 50，实际 {score}"
        assert signals == []

    def test_slight_drop(self):
        """微跌 -0.8% → 50-2=48，无信号。"""
        q = _MockQuote(change_pct=-0.8)
        score, signals = quick_score(q)
        assert 47 <= score <= 49, f"微跌得分应在 47-49，实际 {score}"
        assert signals == []

    def test_moderate_drop(self):
        """下跌 2-4% → 50-6.25≈44，信号"小幅下跌"。"""
        q = _MockQuote(change_pct=-2.5)
        score, signals = quick_score(q)
        assert 42 <= score <= 45, f"下跌得分应在 42-45，实际 {score}"
        assert "小幅下跌" in signals

    def test_large_drop(self):
        """大跌 >4% → 50-12.5≈38，信号"大幅下跌"。"""
        q = _MockQuote(change_pct=-5.0)
        score, signals = quick_score(q)
        assert 35 <= score <= 40, f"大跌得分应在 35-40，实际 {score}"
        assert "大幅下跌" in signals

    def test_clamp_max(self):
        """极端大涨 +20% → clamp 到 100。"""
        q = _MockQuote(change_pct=20.0)
        score, signals = quick_score(q)
        assert score == 100, f"clamp max 应得 100，实际 {score}"
        assert "强势上涨" in signals

    def test_clamp_min(self):
        """极端大跌 -20% → clamp 到 0。"""
        q = _MockQuote(change_pct=-20.0)
        score, signals = quick_score(q)
        assert score == 0, f"clamp min 应得 0，实际 {score}"
        assert "大幅下跌" in signals

    def test_no_change_pct(self):
        """change_pct=None → 50 分，无信号。"""
        q = _MockQuote(change_pct=None)
        score, signals = quick_score(q)
        assert score == 50, f"无涨跌幅应得 50，实际 {score}"
        assert signals == []


class TestQuickScoreIntradayPosition:
    """日内位置因子：收在日内高位更强。"""

    def test_close_near_high(self):
        """收在日内高位（pos>0.8）→ 加分 + "收于日内高位"。"""
        # high=11, low=9, price=10.8 → pos=(10.8-9)/2=0.9 → +3.2
        q = _MockQuote(change_pct=0.0, price=10.8, high=11.0, low=9.0, open=10.0)
        score, signals = quick_score(q)
        assert score > 50, f"收高位应加分，实际 {score}"
        assert "收于日内高位" in signals

    def test_close_near_low(self):
        """收在日内低位（pos<0.2）→ 减分 + "收于日内低位"。"""
        # high=11, low=9, price=9.2 → pos=0.1 → -3.2
        q = _MockQuote(change_pct=0.0, price=9.2, high=11.0, low=9.0, open=10.0)
        score, signals = quick_score(q)
        assert score < 50, f"收低位应减分，实际 {score}"
        assert "收于日内低位" in signals


class TestQuickScoreOpenStrength:
    """开盘强度因子：收盘高于开盘 = 尾盘走强。"""

    def test_close_above_open(self):
        """收盘高于开盘 >2% → "尾盘走强" + 加分。"""
        # open=10, price=10.5 → open_strength=5% → +4
        q = _MockQuote(change_pct=0.0, price=10.5, open=10.0, high=10.5, low=10.0)
        score, signals = quick_score(q)
        assert "尾盘走强" in signals

    def test_close_below_open(self):
        """收盘低于开盘 <-2% → "尾盘走弱"。"""
        # open=10, price=9.5 → open_strength=-5% → -4
        q = _MockQuote(change_pct=0.0, price=9.5, open=10.0, high=10.0, low=9.5)
        score, signals = quick_score(q)
        assert "尾盘走弱" in signals


class TestQuickScoreValuation:
    """估值因子（PE）。"""

    def test_low_pe(self):
        """低 PE (<20) → +3 + "低估值"。"""
        q = _MockQuote(change_pct=0.0, pe=15.0)
        score, signals = quick_score(q)
        assert score == 53, f"低估值应+3得 53，实际 {score}"
        assert "低估值" in signals

    def test_high_pe(self):
        """高 PE (>60) → -3。"""
        q = _MockQuote(change_pct=0.0, pe=80.0)
        score, signals = quick_score(q)
        assert score == 47, f"高估值应-3得 47，实际 {score}"

    def test_no_pe(self):
        """PE=None → 不影响评分。"""
        q = _MockQuote(change_pct=0.0, pe=None)
        score, signals = quick_score(q)
        assert score == 50
        assert "低估值" not in signals
