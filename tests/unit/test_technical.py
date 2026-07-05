"""#10 技术指标测试"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.diting.infra.errors import DataUnavailableError
from src.diting.schema import HistoricalData
from src.diting.signals.technical import TechnicalCalculator


def make_historical(symbol="002475", close=None, high=None, low=None, volume=None, n=60):
    """构造测试用历史数据"""
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n),
        "close": close if close is not None else np.linspace(60, 70, n),
        "high": high if high is not None else np.linspace(61, 72, n),
        "low": low if low is not None else np.linspace(58, 68, n),
        "volume": volume if volume is not None else np.full(n, 10000),
    })
    return HistoricalData(
        symbol=symbol, df=df, columns=list(df.columns),
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 1),
    )


class TestRSI:
    def test_rsi_normal(self):
        calc = TechnicalCalculator
        rsi = calc._rsi(np.linspace(60, 70, 30))
        assert 0 <= rsi <= 100

    def test_rsi_all_gains(self):
        """纯涨 → RSI ≈ 100"""
        close = np.array([10 + i for i in range(20)])
        rsi = TechnicalCalculator._rsi(close, 14)
        assert rsi > 90

    def test_rsi_all_losses(self):
        """纯跌 → RSI ≈ 0"""
        close = np.array([100 - i for i in range(20)])
        rsi = TechnicalCalculator._rsi(close, 14)
        assert rsi < 10


class TestMACD:
    def test_macd_output_range(self):
        macd, sig, hist = TechnicalCalculator._macd(np.linspace(60, 70, 60))
        assert isinstance(macd, float)
        assert isinstance(hist, float)
        # hist = macd - signal, 所以 macd - sig ≈ hist
        assert abs(macd - sig - hist) < 0.001


class TestKDJ:
    def test_kdj_output_range(self):
        close = np.linspace(60, 70, 30)
        high = close + 2
        low = close - 2
        k, d, j = TechnicalCalculator._kdj(high, low, close)
        assert 0 <= k <= 100
        assert 0 <= d <= 100


class TestBollinger:
    def test_bollinger_position_range(self):
        close = np.linspace(60, 70, 30)
        upper, mid, lower, pos = TechnicalCalculator._bollinger(close)
        assert upper > mid > lower
        assert 0 <= pos <= 1


class TestVWAP:
    def test_vwap_near_close(self):
        close = np.array([65.0] * 20)
        volume = np.array([10000] * 20)
        vwap, dev = TechnicalCalculator._vwap(close, volume)
        assert abs(vwap - 65.0) < 0.01
        assert abs(dev) < 0.01


class TestVolumeRatio:
    def test_flat_volume(self):
        """成交量不变 → 量比 ≈ 1"""
        vol = np.full(20, 10000)
        ratio = TechnicalCalculator._volume_ratio(vol)
        assert abs(ratio - 1.0) < 0.01


class TestCalculate:
    """完整的 calculate 方法"""

    def test_calculate_returns_technicals(self):
        data = make_historical(n=30)
        signals = TechnicalCalculator.calculate(data)
        assert signals.symbol == "002475"
        assert 0 <= signals.rsi_14 <= 100
        assert signals.ma_5 > 0
        assert signals.ma_20 > 0

    def test_insufficient_data(self):
        """数据不足 20 行 → DataUnavailableError"""
        data = make_historical(n=10)
        with pytest.raises(DataUnavailableError, match="Need >=20"):
            TechnicalCalculator.calculate(data)

    def test_chinese_column_names(self):
        """兼容中文列名（mx-data 格式）"""
        df = pd.DataFrame({
            "收盘价": np.linspace(60, 70, 30),
            "最高价": np.linspace(62, 72, 30),
            "最低价": np.linspace(58, 68, 30),
            "成交量": np.full(30, 10000),
        })
        data = HistoricalData(
            symbol="002475", df=df, columns=list(df.columns),
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 1),
        )
        signals = TechnicalCalculator.calculate(data)
        assert signals.symbol == "002475"
        assert signals.rsi_14 > 0

    def test_real_data_simulation(self):
        """模拟真实行情：先跌后涨"""
        close = np.concatenate([
            np.linspace(70, 60, 15),  # 下跌
            np.linspace(60, 75, 15),  # 反弹
        ])
        data = make_historical(close=close, n=30)
        signals = TechnicalCalculator.calculate(data)
        # 反弹后 RSI 应该偏高
        assert signals.rsi_14 > 60
