"""谛听 · `_quick_score` 单元测试

覆盖 v0.6.5 连续评分 + 量比因子。
"""
from dataclasses import dataclass

from src.diting.web.services._utils import quick_score


@dataclass
class _MockQuote:
    """模拟 RealtimeQuote，只包含 _quick_score 用到的字段"""
    symbol: str = "000001"
    name: str = "测试"
    price: float = 10.0
    change_pct: float = 0.0
    open: float = 10.0
    high: float = 10.0
    low: float = 10.0
    volume: int = 0
    turnover: float = 0.0


class TestQuickScore:
    """_quick_score() 连续评分 + 量比因子测试"""

    def test_large_gain(self):
        """大涨 >4% → 分数 65+，信号"强势上涨" """
        q = _MockQuote(change_pct=5.2, volume=1000000, turnover=5000000)
        score, signals = quick_score(q)
        # 50 + 5.2*3 = 65.6 → round 66 + 放量5 = 71
        assert 65 <= score <= 75, f"大涨得分应在 65-75，实际 {score}"
        assert "强势上涨" in signals

    def test_moderate_gain(self):
        """上涨 2-4% → 分数 56-62，信号"温和上涨" """
        q = _MockQuote(change_pct=3.0, volume=1000000, turnover=3000000)
        score, signals = quick_score(q)
        assert 56 <= score <= 65, f"温和上涨得分应在 56-65，实际 {score}"
        assert "温和上涨" in signals

    def test_slight_gain(self):
        """微涨 0.5% → 分数 51-52，无信号"""
        q = _MockQuote(change_pct=0.5)
        score, signals = quick_score(q)
        assert score == 52 or score == 51, f"微涨得分应在 51-52，实际 {score}"
        assert signals == []

    def test_flat(self):
        """平盘 0% → 分数 50，无信号"""
        q = _MockQuote(change_pct=0.0)
        score, signals = quick_score(q)
        assert score == 50, f"平盘得分应为 50，实际 {score}"
        assert signals == []

    def test_slight_drop(self):
        """微跌 -0.8% → 分数 47-48，无信号"""
        q = _MockQuote(change_pct=-0.8)
        score, signals = quick_score(q)
        assert 47 <= score <= 48, f"微跌得分应在 47-48，实际 {score}"
        assert signals == []

    def test_moderate_drop(self):
        """下跌 2-4% → 分数 38-44，信号"小幅下跌" """
        q = _MockQuote(change_pct=-2.5)
        score, signals = quick_score(q)
        assert 38 <= score <= 45, f"下跌得分应在 38-45，实际 {score}"
        assert "小幅下跌" in signals

    def test_large_drop(self):
        """大跌 >4% → 分数 35-38，信号"大幅下跌" """
        q = _MockQuote(change_pct=-5.0)
        score, signals = quick_score(q)
        assert 30 <= score <= 40, f"大跌得分应在 30-40，实际 {score}"
        assert "大幅下跌" in signals

    def test_clamp_max(self):
        """极端大涨 +20% → clamp 到 100"""
        q = _MockQuote(change_pct=20.0)
        score, signals = quick_score(q)
        assert score == 100, f"clamp max 应得 100，实际 {score}"
        assert "强势上涨" in signals

    def test_clamp_min(self):
        """极端大跌 -20% → clamp 到 0"""
        q = _MockQuote(change_pct=-20.0)
        score, signals = quick_score(q)
        assert score == 0, f"clamp min 应得 0，实际 {score}"
        assert "大幅下跌" in signals

    def test_no_change_pct(self):
        """change_pct=None → 50 分，无信号"""
        q = _MockQuote(change_pct=None)
        score, signals = quick_score(q)
        assert score == 50, f"无涨跌幅应得 50，实际 {score}"
        assert signals == []

    def test_high_volume_ratio(self):
        """量比 >2（放量）→ 加 5 分，"放量"信号"""
        # 量比 = turnover / volume，假设 volume=10000, turnover=30000 → 量比 3
        q = _MockQuote(change_pct=2.0, volume=10000, turnover=30000)
        score, signals = quick_score(q)
        # base=50 + 2*3=56 + 5(放量) = 61
        assert score == 61, f"放量应得 61，实际 {score}"
        assert "放量" in signals

    def test_medium_volume_ratio(self):
        """量比 1.5-2 → 加 3 分"""
        # 量比 = turnover / volume，volume=10000, turnover=18000 → 量比 1.8
        q = _MockQuote(change_pct=1.0, volume=10000, turnover=18000)
        score, signals = quick_score(q)
        # base=50 + 1*3=53 + 3(量比) = 56
        assert score == 56, f"量比 1.8 应得 56，实际 {score}"

    def test_low_volume_ratio(self):
        """量比 <1.5 → 不加分"""
        q = _MockQuote(change_pct=0.0, volume=10000, turnover=12000)
        score, signals = quick_score(q)
        assert score == 50, f"低量比不应加分，实际 {score}"
        assert signals == []

    def test_zero_volume(self):
        """成交量为 0 → 跳过量比计算"""
        q = _MockQuote(change_pct=1.0, volume=0, turnover=0)
        score, signals = quick_score(q)
        assert score == 53  # 只有涨跌幅加分
        assert "放量" not in signals
