"""M5 测试: 引擎 + 管道 + 共识 + 告警"""

from datetime import date

import numpy as np
import pandas as pd

# Ensure all engines are imported so they register
import src.diting.engines.buffett  # noqa: F401
import src.diting.engines.can_slim  # noqa: F401
import src.diting.engines.wyckoff  # noqa: F401
from src.diting.engines.registry import discover_engines
from src.diting.engines.vmd_rsi import VMDRSIEngine
from src.diting.engines.volume_profile import VolumeProfileEngine
from src.diting.enums import Signal
from src.diting.pipeline.alert import AlertManager
from src.diting.pipeline.consensus import ConsensusEngine
from src.diting.schema import (
    AnalysisContext,
    AnalysisResult,
    HistoricalData,
    Rating,
    TechnicalSignals,
    VMDResult,
)

# ═══════════════════════════════════════════
# Engine discovery
# ═══════════════════════════════════════════


class TestAllEnginesRegistered:
    def test_five_engines_registered(self):
        engines = discover_engines()
        assert "wyckoff" in engines
        assert "buffett" in engines
        assert "can_slim" in engines
        assert "volume_profile" in engines
        assert "vmd_rsi" in engines


# ═══════════════════════════════════════════
# Volume Profile (pure calculation, easy to test)
# ═══════════════════════════════════════════


class TestVolumeProfile:
    def test_price_in_value_area(self):
        df = pd.DataFrame({"close": np.linspace(60, 60, 100)})  # 恒定价格，全部在价值区
        ctx = AnalysisContext(
            symbol="test",
            historical=HistoricalData(
                symbol="test", df=df, columns=["close"],
                start_date=date.today(), end_date=date.today(),
            )
        )
        engine = VolumeProfileEngine()
        result = engine.analyze(ctx)
        assert result.error is None
        assert 0 <= result.score <= 100
        assert "POC" in result.narrative

    def test_no_data_returns_hold(self):
        engine = VolumeProfileEngine()
        ctx = AnalysisContext(symbol="test")
        result = engine.analyze(ctx)
        assert result.rating == Rating.HOLD
        assert result.error is not None


# ═══════════════════════════════════════════
# VMD+RSI
# ═══════════════════════════════════════════


class TestVMDRSI:
    def test_oversold_rsi(self):
        ctx = AnalysisContext(
            symbol="test",
            signals=TechnicalSignals(
                symbol="test", rsi_14=20, macd=0, macd_signal_line=0, macd_histogram=0,
                kdj_k=50, kdj_d=50, kdj_j=50,
                bollinger_upper=70, bollinger_middle=65, bollinger_lower=60,
                bollinger_position=0.5, ma_5=65, ma_20=65, ma_60=65,
                vwap=65, vwap_deviation=0, volume_ratio=1,
            )
        )
        engine = VMDRSIEngine()
        result = engine.analyze(ctx)
        assert result.rating in (Rating.BUY, Rating.STRONG_BUY)
        assert Signal.RSI_OVERSOLD in result.signals

    def test_vmd_trough(self):
        ctx = AnalysisContext(
            symbol="test",
            signals=TechnicalSignals(
                symbol="test", rsi_14=50, macd=0, macd_signal_line=0, macd_histogram=0,
                kdj_k=50, kdj_d=50, kdj_j=50,
                bollinger_upper=70, bollinger_middle=65, bollinger_lower=60,
                bollinger_position=0.5, ma_5=65, ma_20=65, ma_60=65,
                vwap=65, vwap_deviation=0, volume_ratio=1,
            ),
            vmd=VMDResult(
                symbol="test", cycle_position=0.05, trend_slope=0.001,
                dominant_period=20, trend_broken=False,
            ),
        )
        engine = VMDRSIEngine()
        result = engine.analyze(ctx)
        assert Signal.VMD_TROUGH in result.signals


# ═══════════════════════════════════════════
# Consensus
# ═══════════════════════════════════════════


class TestConsensus:
    def test_weighted_average(self):
        engine = ConsensusEngine(weights={"wyckoff": 0.3, "vmd_rsi": 0.7})
        results = [
            AnalysisResult(
                engine_name="wyckoff", engine_version="1.0", symbol="test",
                score=60, rating=Rating.BUY,
            ),
            AnalysisResult(
                engine_name="vmd_rsi", engine_version="1.0", symbol="test",
                score=40, rating=Rating.HOLD,
            ),
        ]
        cs = engine.fuse("test", results)
        # (60*0.3 + 40*0.7) / 1.0 = 46
        assert 44 <= cs.weighted_score <= 48

    def test_empty_results(self):
        engine = ConsensusEngine()
        cs = engine.fuse("test", [])
        assert cs.rating == Rating.HOLD
        assert cs.weighted_score == 50

    def test_engine_failure_tracked(self):
        engine = ConsensusEngine()
        results = [
            AnalysisResult(
                engine_name="wyckoff", engine_version="1.0", symbol="test",
                score=70, rating=Rating.BUY,
            ),
            AnalysisResult(
                engine_name="buffett", engine_version="1.0", symbol="test",
                score=0, rating=Rating.HOLD, error="timeout",
            ),
        ]
        cs = engine.fuse("test", results)
        assert "buffett" in cs.engines_failed
        assert "wyckoff" in cs.engines_used


# ═══════════════════════════════════════════
# Alert
# ═══════════════════════════════════════════


class TestAlert:
    def test_rsi_oversold_triggers(self):
        signals = TechnicalSignals(
            symbol="002475", rsi_14=18, macd=0, macd_signal_line=0, macd_histogram=0,
            kdj_k=50, kdj_d=50, kdj_j=50,
            bollinger_upper=70, bollinger_middle=65, bollinger_lower=60,
            bollinger_position=0.5, ma_5=65, ma_20=65, ma_60=65,
            vwap=65, vwap_deviation=0, volume_ratio=1,
        )
        alerts = AlertManager.check("002475", signals=signals)
        assert len(alerts) > 0
        assert "RSI" in alerts[0]

    def test_no_alert_when_normal(self):
        signals = TechnicalSignals(
            symbol="002475", rsi_14=50, macd=0, macd_signal_line=0, macd_histogram=0,
            kdj_k=50, kdj_d=50, kdj_j=50,
            bollinger_upper=70, bollinger_middle=65, bollinger_lower=60,
            bollinger_position=0.5, ma_5=65, ma_20=65, ma_60=65,
            vwap=65, vwap_deviation=0, volume_ratio=1,
        )
        alerts = AlertManager.check("002475", signals=signals)
        assert len(alerts) == 0

    def test_market_crash(self):
        alerts = AlertManager.check("000001", market_change=-4.0)
        assert len(alerts) > 0
        assert "暴跌" in alerts[0]
