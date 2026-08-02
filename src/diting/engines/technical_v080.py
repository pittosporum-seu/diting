"""Deterministic technical engine for the v0.8 analysis kernel."""

from __future__ import annotations

import math

import numpy as np

from ..enums import EngineMode
from ..infra.errors import DataUnavailableError
from ..schema import (
    DataSnapshot,
    EngineCapabilities,
    EngineContext,
    EngineResult,
    Evidence,
    Risk,
)
from .kernel import SnapshotAnalysisEngine
from .rating import score_to_rating


class TechnicalEngine(SnapshotAnalysisEngine):
    """Score RSI, MACD, trend, Bollinger position and volume deterministically."""

    name = "technical"
    version = "1.0.0"
    mode = EngineMode.DETERMINISTIC

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            required_data=("historical",),
            min_history_bars=60,
            deterministic=True,
            timeout_seconds=5,
        )

    def analyze(self, snapshot: DataSnapshot, context: EngineContext) -> EngineResult:
        del context
        historical = snapshot.historical
        if historical is None or not historical.succeeded or historical.data is None:
            raise DataUnavailableError(f"historical data is unavailable for {snapshot.symbol}")
        bars = historical.data.bars
        if len(bars) < self.capabilities().min_history_bars:
            raise DataUnavailableError(
                f"need >=60 historical bars for {snapshot.symbol}, got {len(bars)}"
            )

        close = np.asarray([bar.close for bar in bars], dtype=float)
        volume = np.asarray([bar.volume for bar in bars], dtype=float)
        if not np.all(np.isfinite(close)) or np.any(close <= 0):
            raise DataUnavailableError(f"invalid close prices for {snapshot.symbol}")

        rsi = self._rsi(close)
        macd, signal, histogram = self._macd(close)
        ma5 = float(np.mean(close[-5:]))
        ma20 = float(np.mean(close[-20:]))
        ma60 = float(np.mean(close[-60:]))
        bollinger_position = self._bollinger_position(close)
        volume_ratio = self._volume_ratio(volume)

        engine_score = 50.0
        evidence: list[Evidence] = []
        risks: list[Risk] = []

        if rsi < 30:
            engine_score += 15
            evidence.append(Evidence("RSI_OVERSOLD", f"RSI {rsi:.1f} 处于超卖区", rsi))
        elif rsi > 70:
            engine_score -= 15
            risks.append(Risk("RSI_OVERBOUGHT", f"RSI {rsi:.1f} 处于超买区"))

        if histogram > 0:
            engine_score += 10
            evidence.append(Evidence("MACD_POSITIVE", "MACD 柱线为正", round(histogram, 4)))
        else:
            engine_score -= 10
            risks.append(Risk("MACD_NEGATIVE", "MACD 柱线为负"))

        if ma5 > ma20 > ma60:
            engine_score += 15
            evidence.append(Evidence("MA_BULLISH", "均线呈多头排列"))
        elif ma5 < ma20 < ma60:
            engine_score -= 15
            risks.append(Risk("MA_BEARISH", "均线呈空头排列"))

        if bollinger_position < 0.1:
            engine_score += 10
            evidence.append(
                Evidence("BOLLINGER_LOW", "价格接近布林下轨", round(bollinger_position, 4))
            )
        elif bollinger_position > 0.9:
            engine_score -= 10
            risks.append(Risk("BOLLINGER_HIGH", "价格接近或突破布林上轨"))

        quote = snapshot.quote.data if snapshot.quote and snapshot.quote.succeeded else None
        if volume_ratio > 1.5 and quote is not None:
            if quote.change_pct > 0:
                engine_score += 5
                evidence.append(Evidence("UP_VOLUME", "上涨伴随放量", volume_ratio))
            elif quote.change_pct < 0:
                engine_score -= 5
                risks.append(Risk("DOWN_VOLUME", "下跌伴随放量"))

        engine_score = round(max(0.0, min(100.0, engine_score)), 1)
        confidence = round(min(1.0, 0.75 + min(len(bars), 250) / 1000), 2)
        narrative = (
            f"RSI {rsi:.1f}，MACD柱 {histogram:.3f}，"
            f"MA5/20/60 {ma5:.2f}/{ma20:.2f}/{ma60:.2f}，"
            f"布林位置 {bollinger_position:.2f}。"
        )
        metadata = (
            ("rsi_14", f"{rsi:.6f}"),
            ("macd", f"{macd:.6f}"),
            ("macd_signal", f"{signal:.6f}"),
            ("macd_histogram", f"{histogram:.6f}"),
            ("ma_5", f"{ma5:.6f}"),
            ("ma_20", f"{ma20:.6f}"),
            ("ma_60", f"{ma60:.6f}"),
            ("bollinger_position", f"{bollinger_position:.6f}"),
            ("volume_ratio", f"{volume_ratio:.6f}"),
        )
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=snapshot.symbol,
            engine_score=engine_score,
            rating=score_to_rating(engine_score),
            confidence=confidence,
            narrative=narrative,
            evidence=tuple(evidence),
            risks=tuple(risks),
            metadata=metadata,
        )

    @staticmethod
    def _rsi(close: np.ndarray, period: int = 14) -> float:
        changes = np.diff(close[-(period + 1) :])
        gains = np.maximum(changes, 0)
        losses = np.maximum(-changes, 0)
        average_gain = float(np.mean(gains))
        average_loss = float(np.mean(losses))
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + average_gain / average_loss)

    @classmethod
    def _macd(cls, close: np.ndarray) -> tuple[float, float, float]:
        fast = cls._ema_series(close, 12)
        slow = cls._ema_series(close, 26)
        line = fast - slow
        signal = cls._ema_series(line, 9)
        return float(line[-1]), float(signal[-1]), float(line[-1] - signal[-1])

    @staticmethod
    def _ema_series(values: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        output = np.empty(len(values), dtype=float)
        output[0] = values[0]
        for index in range(1, len(values)):
            output[index] = alpha * values[index] + (1 - alpha) * output[index - 1]
        return output

    @staticmethod
    def _bollinger_position(close: np.ndarray) -> float:
        recent = close[-20:]
        middle = float(np.mean(recent))
        deviation = float(np.std(recent, ddof=1))
        if math.isclose(deviation, 0.0):
            return 0.5
        lower = middle - 2 * deviation
        upper = middle + 2 * deviation
        return float((close[-1] - lower) / (upper - lower))

    @staticmethod
    def _volume_ratio(volume: np.ndarray) -> float:
        baseline = float(np.mean(volume[-6:-1]))
        return 1.0 if baseline <= 0 else float(volume[-1] / baseline)
