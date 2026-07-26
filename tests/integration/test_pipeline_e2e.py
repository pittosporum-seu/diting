"""谛听 · 端到端管道集成测试

模拟完整分析链路：RealtimeQuote + HistoricalData 获取 →
TechnicalSignals → 多引擎分析 → Consensus → Report。
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

# 触发引擎注册
import src.diting.engines.vmd_rsi  # noqa: F401
import src.diting.engines.volume_profile  # noqa: F401
from src.diting.enums import DataSource, Rating
from src.diting.pipeline.consensus import ConsensusEngine
from src.diting.pipeline.runner import AnalysisPipeline
from src.diting.report.builder import ReportBuilder
from src.diting.schema import (
    AnalysisContext,
    AnalysisResult,
    HistoricalData,
    PipelineResult,
    RealtimeQuote,
    TechnicalSignals,
    VMDResult,
)

# ═══════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════


def _make_quote(symbol: str = "002475", price: float = 70.4) -> RealtimeQuote:
    return RealtimeQuote(
        symbol=symbol,
        name="立讯精密",
        price=price,
        change_pct=2.1,
        open=69.0,
        high=71.0,
        low=68.5,
        volume=10000,
        turnover=700000,
        source=DataSource.MX_DATA,
    )


def _make_historical(symbol: str = "002475") -> HistoricalData:
    """生成模拟历史数据（60 天）。"""
    rng = np.random.default_rng(42)
    base = 70.0
    prices = base + np.cumsum(rng.normal(0, 0.5, 60))
    df = pd.DataFrame(
        {
            "close": prices,
            "open": prices - rng.uniform(0, 0.5, 60),
            "high": prices + rng.uniform(0, 0.8, 60),
            "low": prices - rng.uniform(0, 0.8, 60),
            "volume": (10000 + rng.integers(0, 5000, 60)),
        }
    )
    return HistoricalData(
        symbol=symbol,
        df=df,
        columns=["close", "open", "high", "low", "volume"],
        start_date=date(2026, 5, 1),
        end_date=date(2026, 7, 1),
        source=DataSource.MX_DATA,
    )


def _make_signals(symbol: str = "002475") -> TechnicalSignals:
    return TechnicalSignals(
        symbol=symbol,
        rsi_14=45.0,
        macd=0.5,
        macd_signal_line=0.3,
        macd_histogram=0.2,
        kdj_k=50.0,
        kdj_d=48.0,
        kdj_j=54.0,
        bollinger_upper=75.0,
        bollinger_middle=70.0,
        bollinger_lower=65.0,
        bollinger_position=0.5,
        ma_5=71.0,
        ma_20=70.0,
        ma_60=68.0,
        vwap=70.5,
        vwap_deviation=-0.1,
        volume_ratio=0.85,
    )


def _make_context(
    symbol: str = "002475",
    with_historical: bool = True,
    with_signals: bool = True,
    with_vmd: bool = False,
) -> AnalysisContext:
    return AnalysisContext(
        symbol=symbol,
        realtime=_make_quote(symbol),
        historical=_make_historical(symbol) if with_historical else None,
        signals=_make_signals(symbol) if with_signals else None,
        vmd=VMDResult(
            symbol=symbol,
            cycle_position=0.15,
            trend_slope=0.02,
            dominant_period=20,
            trend_broken=False,
        )
        if with_vmd
        else None,
    )


# ═══════════════════════════════════════════════════════
# E2E 管道测试
# ═══════════════════════════════════════════════════════


class TestPipelineE2E:
    """端到端管道测试 —— 模拟完整分析链路。"""

    def test_full_pipeline_single_symbol(self):
        """单只标的完整管道：数据 → 引擎 → 共识 → 报告。"""
        ctx = _make_context("002475", with_vmd=True)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "volume_profile"])
        result = pipeline.run([ctx])

        assert isinstance(result, PipelineResult)
        assert result.symbols == ("002475",)
        assert "002475" in result.results
        assert len(result.results["002475"]) == 2

        # 共识
        consensus = ConsensusEngine()
        cs = consensus.fuse("002475", result.results["002475"])
        assert hasattr(cs, "weighted_score")
        assert cs.rating is not None

        # 报告
        builder = ReportBuilder(level="L1")
        html = builder.build(result)
        assert "<!DOCTYPE html>" in html
        assert "002475" in html
        assert "谛听" in html

    def test_pipeline_multiple_symbols(self):
        """多只标的并行分析。"""
        ctx_1 = _make_context("002475", with_vmd=True)
        ctx_2 = _make_context("603659", with_vmd=True)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "volume_profile"])
        result = pipeline.run([ctx_1, ctx_2])

        assert len(result.symbols) == 2
        assert "002475" in result.results
        assert "603659" in result.results
        assert len(result.results["002475"]) == 2
        assert len(result.results["603659"]) == 2

    def test_all_engine_results_valid(self):
        """所有引擎结果包含必要字段。"""
        ctx = _make_context("002475", with_vmd=True)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "volume_profile"])
        result = pipeline.run([ctx])

        for r in result.results["002475"]:
            assert isinstance(r, AnalysisResult)
            assert r.engine_name
            assert r.engine_version
            assert r.symbol == "002475"
            assert 0 <= r.score <= 100
            assert isinstance(r.rating, Rating)
            assert r.error is None

    def test_pipeline_result_all_fields(self):
        """PipelineResult 所有字段正常填充。"""
        ctx = _make_context("002475", with_vmd=True)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "volume_profile"])
        result = pipeline.run([ctx])

        assert isinstance(result.symbols, tuple)
        assert len(result.symbols) == 1
        assert isinstance(result.results, dict)
        assert isinstance(result.consensus, dict)
        assert isinstance(result.reports, dict)
        assert isinstance(result.errors, tuple)
        assert isinstance(result.metrics, dict)
        assert "duration_ms" in result.metrics
        assert result.metrics["engines"] == 2
        assert result.metrics["symbols"] == 1

    def test_l2_report_with_chart_data(self):
        """L2 报告生成含图表数据。"""
        ctx = _make_context("002475", with_vmd=True)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "volume_profile"])
        result = pipeline.run([ctx])

        chart_data = {
            "002475": {
                "name": "立讯精密",
                "dates": pd.date_range("2026-05-01", periods=60).tolist(),
                "prices": [70.0 + i * 0.05 for i in range(60)],
                "rsi_values": [45.0 + i * 0.1 for i in range(60)],
                "ma_5": [69.5 + i * 0.05 for i in range(60)],
                "ma_20": [68.0 + i * 0.05 for i in range(60)],
                "boll_upper": [72.0 + i * 0.05 for i in range(60)],
                "boll_lower": [66.0 + i * 0.05 for i in range(60)],
                "realtime_price": 73.0,
                "change_pct": 4.3,
            },
        }
        builder = ReportBuilder(level="L2")
        html = builder.build(result, chart_data=chart_data)

        assert "echarts.init" in html
        assert "price_002475" in html
        assert "rsi_002475" in html

    def test_engine_failure_does_not_block_pipeline(self):
        """单个引擎失败不阻塞其他引擎。"""
        ctx = _make_context("002475", with_historical=False, with_vmd=False)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "volume_profile"])
        result = pipeline.run([ctx])

        # vmd_rsi 无历史数据仍然运行（VMD+RSI 只用 signals）
        # volume_profile 无历史数据会返回 HOLD + error
        assert len(result.results["002475"]) == 2

        volume_results = [r for r in result.results["002475"] if r.engine_name == "volume_profile"]
        assert len(volume_results) == 1
        # 无历史数据时 volume_profile 返回 error
        assert volume_results[0].rating == Rating.HOLD

        # vmd_rsi 仍然正常运行
        vmd_results = [r for r in result.results["002475"] if r.engine_name == "vmd_rsi"]
        assert len(vmd_results) == 1
        assert vmd_results[0].error is None

    def test_nonexistent_engine_does_not_block(self):
        """不存在的引擎名不阻塞管道。"""
        ctx = _make_context("002475", with_vmd=True)
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi", "ghost"])
        result = pipeline.run([ctx])

        assert len(result.results["002475"]) == 1
        assert result.results["002475"][0].engine_name == "vmd_rsi"
        assert any("ghost" in str(e) for e in result.errors)


class TestEmptyWorkload:
    """空持仓 / 边界条件测试。"""

    def test_empty_symbols(self):
        """空标的集合不崩溃。"""
        pipeline = AnalysisPipeline(engine_names=["vmd_rsi"])
        result = pipeline.run([])
        assert result.symbols == ()
        assert result.results == {}

    def test_report_with_empty_pipeline(self):
        """空管道结果生成报告不崩溃。"""
        result = PipelineResult(symbols=(), results={})
        builder = ReportBuilder(level="L1")
        html = builder.build(result)
        assert "<!DOCTYPE html>" in html

    def test_consensus_with_empty_results(self):
        """空结果共识返回 HOLD。"""
        engine = ConsensusEngine()
        cs = engine.fuse("test", [])
        assert cs.rating == Rating.HOLD
        assert cs.weighted_score == 50


class TestDataProtocols:
    """数据协议正确性。"""

    def test_realtime_quote_serialization(self):
        """RealtimeQuote 可通过 dataclass 序列化。"""
        q = _make_quote("002475")
        assert q.symbol == "002475"
        assert q.source == DataSource.MX_DATA
        assert isinstance(q.timestamp, datetime)

    def test_historical_data_has_df(self):
        """HistoricalData 包含 DataFrame。"""
        h = _make_historical("002475")
        assert h.df is not None
        assert len(h.df) == 60
        assert h.source == DataSource.MX_DATA

    def test_context_assembles_all_layers(self):
        """AnalysisContext 完整组装所有数据层。"""
        ctx = _make_context("002475", with_vmd=True)
        assert ctx.realtime is not None
        assert ctx.historical is not None
        assert ctx.signals is not None
        assert ctx.vmd is not None
