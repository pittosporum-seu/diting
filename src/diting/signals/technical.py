"""谛听 · 技术指标计算

RSI / MACD / KDJ / 布林带 / 均线 / VWAP / 量比。
输入 HistoricalData → 输出 TechnicalSignals。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy import ndarray

from ..infra.config_loader import ConfigLoader
from ..infra.errors import DataUnavailableError
from ..schema import HistoricalData, TechnicalSignals


class TechnicalCalculator:
    """技术指标计算器。

    所有计算为纯函数，输入 DataFrame，输出 TechnicalSignals。
    """

    # ── 公开接口 ──────────────────────────────────

    @classmethod
    def _indicator_config(cls) -> dict:
        return ConfigLoader.get_section("indicators")

    @classmethod
    def calculate(cls, data: HistoricalData) -> TechnicalSignals:
        """从历史数据计算所有技术指标。

        Args:
            data: 历史行情数据，需包含 close, high, low, volume 列

        Returns:
            TechnicalSignals @dataclass

        Raises:
            DataUnavailableError: 数据不足
        """
        df = cls._to_dataframe(data)
        close = cls._get_column(df, "close")
        high = cls._get_column(df, "high")
        low = cls._get_column(df, "low")
        volume = cls._get_column(df, "volume")

        if len(close) < 20:
            raise DataUnavailableError(f"Need >=20 rows for {data.symbol}, got {len(close)}")

        ind = cls._indicator_config()
        rsi_period = ind.get("rsi", {}).get("period", 14)
        rsi_14 = cls._rsi(close, rsi_period)
        macd, signal_line, histogram = cls._macd(close)
        k, d, j = cls._kdj(high, low, close)
        upper, middle, lower, boll_pos = cls._bollinger(close)
        ma_5 = float(np.mean(close[-5:]))
        ma_20 = float(np.mean(close[-20:]))
        ma_60 = float(np.mean(close[-60:])) if len(close) >= 60 else ma_20
        vwap, vwap_dev = cls._vwap(close, volume)
        vol_ratio = cls._volume_ratio(volume)

        return TechnicalSignals(
            symbol=data.symbol,
            rsi_14=rsi_14,
            macd=macd,
            macd_signal_line=signal_line,
            macd_histogram=histogram,
            kdj_k=k,
            kdj_d=d,
            kdj_j=j,
            bollinger_upper=upper,
            bollinger_middle=middle,
            bollinger_lower=lower,
            bollinger_position=boll_pos,
            ma_5=ma_5,
            ma_20=ma_20,
            ma_60=ma_60,
            vwap=vwap,
            vwap_deviation=vwap_dev,
            volume_ratio=vol_ratio,
        )

    # ── 指标计算 ──────────────────────────────────

    @staticmethod
    def _rsi(close: ndarray, period: int | None = None) -> float:
        """RSI 相对强弱指标"""
        if period is None:
            ind = ConfigLoader.get_section("indicators")
            period = ind.get("rsi", {}).get("period", 14)
        if len(close) < period + 1:
            return 50.0
        diff = np.diff(close)
        gain = np.maximum(diff, 0)
        loss = np.maximum(-diff, 0)
        avg_gain = np.mean(gain[-period:])
        avg_loss = np.mean(loss[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - 100.0 / (1.0 + rs))

    @staticmethod
    def _macd(
        close: ndarray,
        fast: int | None = None,
        slow: int | None = None,
        signal: int | None = None,
    ) -> tuple[float, float, float]:
        """MACD (默认 12, 26, 9)"""
        if fast is None:
            ind = ConfigLoader.get_section("indicators")
            fast = ind.get("macd", {}).get("fast", 12)
            slow = ind.get("macd", {}).get("slow", 26)
            signal = ind.get("macd", {}).get("signal", 9)
        ema_fast = TechnicalCalculator._ema_series(close, fast)
        ema_slow = TechnicalCalculator._ema_series(close, slow)
        macd_series = ema_fast - ema_slow
        sig_series = TechnicalCalculator._ema_series(macd_series, signal)
        return float(macd_series[-1]), float(sig_series[-1]), float(macd_series[-1] - sig_series[-1])

    @staticmethod
    def _kdj(
        high: ndarray,
        low: ndarray,
        close: ndarray,
        period: int | None = None,
        k_smooth: int | None = None,
        d_smooth: int | None = None,
    ) -> tuple[float, float, float]:
        """KDJ (默认 9, 3, 3)"""
        if period is None:
            ind = ConfigLoader.get_section("indicators")
            period = ind.get("kdj", {}).get("period", 9)
        n = period
        if len(close) < n:
            return 50.0, 50.0, 50.0
        # 最近 9 个周期的最高最低
        hh = np.max(high[-n:])
        ll = np.min(low[-n:])
        rsv = 50.0 if hh == ll else float((close[-1] - ll) / (hh - ll) * 100)
        # K/D 初始值取 RSV
        k = (2 / 3) * 50 + (1 / 3) * rsv  # 简化为平滑处理
        d = (2 / 3) * 50 + (1 / 3) * k
        j = 3 * k - 2 * d
        return round(k, 2), round(d, 2), round(j, 2)

    @staticmethod
    def _bollinger(
        close: ndarray,
        period: int | None = None,
        std_dev: float | None = None,
    ) -> tuple[float, float, float, float]:
        """布林带 (默认 20, 2.0)"""
        if period is None:
            ind = ConfigLoader.get_section("indicators")
            period = ind.get("bollinger", {}).get("period", 20)
            std_dev = ind.get("bollinger", {}).get("std_dev", 2.0)
        n = period
        middle = float(np.mean(close[-n:]))
        std = float(np.std(close[-n:], ddof=1))
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        # 当前位置 0=下轨, 1=上轨
        if upper == lower:
            pos = 0.5
        else:
            pos = (close[-1] - lower) / (upper - lower)
        return round(upper, 2), round(middle, 2), round(lower, 2), round(pos, 4)

    @staticmethod
    def _vwap(close: ndarray, volume: ndarray) -> tuple[float, float]:
        """VWAP 成交量加权平均价（最近 20 周期）"""
        n = min(20, len(close))
        recent_price = close[-n:]
        recent_vol = volume[-n:]
        total_vol = np.sum(recent_vol)
        if total_vol == 0:
            return float(close[-1]), 0.0
        vwap_val = float(np.sum(recent_price * recent_vol) / total_vol)
        dev = round((close[-1] - vwap_val) / vwap_val * 100, 2)
        return round(vwap_val, 2), dev

    @staticmethod
    def _volume_ratio(volume: ndarray) -> float:
        """量比 = 当日量 / 5日均量"""
        if len(volume) < 6:
            return 1.0
        ma5_vol = np.mean(volume[-6:-1])
        if ma5_vol == 0:
            return 1.0
        return round(float(volume[-1] / ma5_vol), 2)

    @staticmethod
    def _ema(data: ndarray, period: int) -> float:
        """指数移动平均（返回最终值）"""
        if len(data) < period:
            return float(np.mean(data))
        alpha = 2 / (period + 1)
        ema = np.mean(data[:period])
        for val in data[period:]:
            ema = alpha * val + (1 - alpha) * ema
        return float(ema)

    @staticmethod
    def _ema_series(data: ndarray, period: int) -> ndarray:
        """指数移动平均（返回完整序列）"""
        n = len(data)
        if n == 0:
            return np.array([])
        if n < period:
            return np.full(n, float(np.mean(data)))
        alpha = 2 / (period + 1)
        out = np.zeros(n)
        out[period - 1] = np.mean(data[:period])
        for i in range(period, n):
            out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
        # 前 period-1 个点用初始值填充
        out[:period - 1] = out[period - 1]
        return out

    # ── 辅助 ──────────────────────────────────────

    @staticmethod
    def _to_dataframe(data: HistoricalData) -> Any:
        """从 HistoricalData 提取 DataFrame"""
        df = data.df
        if df is None:
            raise DataUnavailableError(f"No data for {data.symbol}")
        return df

    @staticmethod
    def _get_column(df: Any, col_name: str) -> ndarray:
        """安全提取列数据，兼容大小写和中文名"""
        col_map = {
            "close": ["close", "收盘", "收盘价"],
            "high": ["high", "最高", "最高价"],
            "low": ["low", "最低", "最低价"],
            "volume": ["volume", "成交量"],
        }
        candidates = col_map.get(col_name, [col_name])
        for c in candidates:
            if c in df.columns:
                arr = df[c].values
                # 转换 object → float
                if arr.dtype == object:
                    arr = arr.astype(float)
                return arr
        raise DataUnavailableError(f"Column '{col_name}' not found in {df.columns.tolist()}")
