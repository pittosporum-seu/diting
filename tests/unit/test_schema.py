"""schema.py 数据协议测试"""

from dataclasses import asdict
from datetime import datetime

import pytest

from src.diting.enums import DataSource, Rating
from src.diting.schema import (
    AnalysisContext,
    AnalysisResult,
    ConsensusScore,
    PipelineResult,
    RealtimeQuote,
    TechnicalSignals,
    VMDResult,
)


class TestRealtimeQuote:
    def test_create_and_asdict(self):
        q = RealtimeQuote(
            symbol="002475", name="立讯精密", price=70.4, change_pct=2.1,
            open=69.0, high=71.0, low=68.5, volume=10000, turnover=700000,
        )
        d = asdict(q)
        assert d["symbol"] == "002475"
        assert d["price"] == 70.4
        assert d["source"] == DataSource.UNKNOWN

    def test_optional_fields_default_none(self):
        q = RealtimeQuote(
            symbol="002475", name="立讯精密", price=70.4, change_pct=2.1,
            open=69.0, high=71.0, low=68.5, volume=10000, turnover=700000,
        )
        assert q.pe is None
        assert q.pb is None

    def test_frozen_prevents_mutation(self):
        q = RealtimeQuote(
            symbol="002475", name="立讯精密", price=70.4, change_pct=2.1,
            open=69.0, high=71.0, low=68.5, volume=10000, turnover=700000,
        )
        with pytest.raises(Exception):
            q.price = 80.0  # type: ignore


class TestVMDResult:
    def test_create(self):
        v = VMDResult(
            symbol="002475", cycle_position=0.3, trend_slope=0.15,
            dominant_period=14, trend_broken=False,
        )
        assert v.cycle_position == 0.3
        assert not v.trend_broken
        assert v.params == {}


class TestTechnicalSignals:
    def test_create_minimal(self):
        ts = TechnicalSignals(
            symbol="002475",
            rsi_14=45.0, macd=0.5, macd_signal_line=0.3, macd_histogram=0.2,
            kdj_k=50.0, kdj_d=48.0, kdj_j=54.0,
            bollinger_upper=75.0, bollinger_middle=70.0, bollinger_lower=65.0,
            bollinger_position=0.5,
            ma_5=71.0, ma_20=70.0, ma_60=68.0,
            vwap=70.5, vwap_deviation=-0.1, volume_ratio=0.85,
        )
        assert ts.rsi_14 == 45.0
        assert isinstance(ts.timestamp, datetime)


class TestAnalysisContext:
    def test_minimal(self):
        ctx = AnalysisContext(symbol="002475")
        assert ctx.symbol == "002475"
        assert ctx.realtime is None

    def test_with_data(self):
        q = RealtimeQuote(
            symbol="002475", name="立讯精密", price=70.4, change_pct=2.1,
            open=69.0, high=71.0, low=68.5, volume=10000, turnover=700000,
        )
        ctx = AnalysisContext(symbol="002475", realtime=q)
        assert ctx.realtime.price == 70.4


class TestAnalysisResult:
    def test_minimal(self):
        r = AnalysisResult(
            engine_name="wyckoff", engine_version="1.0.0",
            symbol="002475", score=65.0, rating=Rating.BUY,
        )
        assert r.score == 65.0
        assert r.rating == Rating.BUY
        assert r.signals == ()
        assert r.error is None


class TestConsensusScore:
    def test_create(self):
        cs = ConsensusScore(
            symbol="002475", weighted_score=72.5, rating=Rating.ACCUMULATE,
        )
        assert cs.weighted_score == 72.5
        assert cs.engines_used == ()


class TestPipelineResult:
    def test_create_minimal(self):
        pr = PipelineResult(symbols=("002475",))
        assert len(pr.symbols) == 1
        assert pr.results == {}
