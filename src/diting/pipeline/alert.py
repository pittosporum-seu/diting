"""谛听 · 事件告警（Observer 模式）"""

from ..infra.logging_config import get_logger
from ..schema import TechnicalSignals, VMDResult

logger = get_logger(__name__)


class AlertManager:
    """事件告警——RSI<20 / VMD谷底 / 大盘暴跌3%"""

    THRESHOLDS = {
        "rsi_oversold": 25,
        "rsi_overbought": 75,
        "vmd_trough": 0.15,
        "vmd_peak": 0.85,
        "market_crash_pct": -3.0,
    }

    @classmethod
    def check(
        cls,
        symbol: str,
        signals: TechnicalSignals | None = None,
        vmd: VMDResult | None = None,
        market_change: float | None = None,
    ) -> list[str]:
        """检查是否触发告警条件。

        Returns:
            告警消息列表，空列表表示无事
        """
        alerts = []

        if signals:
            if signals.rsi_14 < cls.THRESHOLDS["rsi_oversold"]:
                alerts.append(f"🚨 {symbol} RSI={signals.rsi_14:.0f} 超卖")
            elif signals.rsi_14 > cls.THRESHOLDS["rsi_overbought"]:
                alerts.append(f"⚠️ {symbol} RSI={signals.rsi_14:.0f} 超买")

        if vmd:
            if vmd.cycle_position < cls.THRESHOLDS["vmd_trough"]:
                alerts.append(f"📉 {symbol} VMD 接近谷底 (pos={vmd.cycle_position:.3f})")
            elif vmd.cycle_position > cls.THRESHOLDS["vmd_peak"]:
                alerts.append(f"📈 {symbol} VMD 接近峰顶 (pos={vmd.cycle_position:.3f})")

        if market_change is not None and market_change <= cls.THRESHOLDS["market_crash_pct"]:
            alerts.append(f"🔴 大盘暴跌 {market_change:.1f}%")

        if alerts:
            logger.info("alert.triggered", symbol=symbol, count=len(alerts))

        return alerts
