"""schema.py 数据协议测试"""

import json
from dataclasses import asdict
from datetime import datetime

import pytest

from src.diting.ai.output_schema import AiEngineOutput
from src.diting.enums import DataSource, Rating
from src.diting.schema import (
    AnalysisContext,
    AnalysisResult,
    ConsensusScore,
    EngineScoreItem,
    EngineSkipInfo,
    PipelineResult,
    RealtimeQuote,
    StockAnalysisResponse,
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

    def test_json_roundtrip_restores_datetime_and_source(self):
        timestamp = datetime(2026, 7, 15, 10, 30)
        quote = RealtimeQuote(
            symbol="002475", name="立讯精密", price=70.4, change_pct=2.1,
            open=69.0, high=71.0, low=68.5, volume=10000, turnover=700000,
            timestamp=timestamp, source=DataSource.MX_DATA,
        )
        payload = asdict(quote)
        payload["timestamp"] = payload["timestamp"].isoformat()
        payload["source"] = payload["source"].value

        decoded = json.loads(json.dumps(payload))
        assert decoded["timestamp"] == "2026-07-15T10:30:00"
        assert decoded["source"] == "mx_data"
        decoded["timestamp"] = datetime.fromisoformat(decoded["timestamp"])
        decoded["source"] = DataSource(decoded["source"])

        restored = RealtimeQuote(**decoded)
        assert restored == quote
        assert isinstance(restored.timestamp, datetime)
        assert restored.source is DataSource.MX_DATA


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
        assert r.risks == ()
        assert r.error is None

    def test_empty_signals_and_risks_json_roundtrip(self):
        result = AnalysisResult(
            engine_name="wyckoff", engine_version="1.0.0",
            symbol="002475", score=65.0, rating=Rating.BUY,
        )
        payload = asdict(result)
        payload["rating"] = payload["rating"].value
        decoded = json.loads(json.dumps(payload))
        decoded["rating"] = Rating(decoded["rating"])
        decoded["signals"] = tuple(decoded["signals"])
        decoded["charts"] = tuple(decoded["charts"])
        decoded["risks"] = tuple(decoded["risks"])

        restored = AnalysisResult(**decoded)
        assert restored == result
        assert restored.signals == ()
        assert restored.risks == ()


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

    def test_errors_json_roundtrip(self):
        result = PipelineResult(
            symbols=("002475",),
            errors=("wyckoff: timeout", "buffett: unavailable"),
            metrics={"duration_ms": 125},
        )
        decoded = json.loads(json.dumps(asdict(result)))
        decoded["symbols"] = tuple(decoded["symbols"])
        decoded["errors"] = tuple(decoded["errors"])

        restored = PipelineResult(**decoded)
        assert restored.errors == ("wyckoff: timeout", "buffett: unavailable")
        assert restored.metrics["duration_ms"] == 125


class TestAiEngineOutput:
    def test_json_roundtrip_all_fields(self):
        output = AiEngineOutput(
            score=85.0,
            rating=Rating.STRONG_BUY,
            narrative="强势买入",
            signals=["signal1"],
            risks=["risk1"],
            bull_reasons=["bull1"],
            bear_reasons=["bear1"],
            confidence=0.9,
            metadata={"moat_score": 18},
        )
        payload = asdict(output)
        payload["rating"] = payload["rating"].value
        decoded = json.loads(json.dumps(payload))
        decoded["rating"] = Rating(decoded["rating"])

        restored = AiEngineOutput(**decoded)
        assert restored == output
        assert restored.rating is Rating.STRONG_BUY
        assert restored.signals == ["signal1"]
        assert restored.risks == ["risk1"]
        assert restored.bull_reasons == ["bull1"]
        assert restored.bear_reasons == ["bear1"]
        assert restored.metadata == {"moat_score": 18}


class TestStockAnalysisResponse:
    def test_nested_web_schema_json_roundtrip(self):
        response = StockAnalysisResponse(
            code="002475",
            name="立讯精密",
            price=70.4,
            change_pct=2.1,
            score=82.0,
            engine_scores=[EngineScoreItem(
                engine_name="wyckoff",
                score=85.0,
                rating="strong_buy",
                rating_label="强烈买入",
                confidence=0.9,
                duration_ms=120,
            )],
            engine_skipped=[EngineSkipInfo(
                engine_name="buffett", reason="no_api_key",
            )],
            bull_reasons=["Spring确认"],
            signals_summary={"rsi_14": 45.0},
            _cache_state="cached",
        )
        decoded = json.loads(json.dumps(asdict(response)))
        assert decoded["engine_scores"][0] == {
            "engine_name": "wyckoff",
            "score": 85.0,
            "rating": "strong_buy",
            "rating_label": "强烈买入",
            "confidence": 0.9,
            "duration_ms": 120,
        }
        decoded["engine_scores"] = [
            EngineScoreItem(**item) for item in decoded["engine_scores"]
        ]
        decoded["engine_skipped"] = [
            EngineSkipInfo(**item) for item in decoded["engine_skipped"]
        ]

        restored = StockAnalysisResponse(**decoded)
        assert restored.engine_scores[0].engine_name == "wyckoff"
        assert restored.engine_skipped[0].reason == "no_api_key"
        assert restored.signals_summary == {"rsi_14": 45.0}
