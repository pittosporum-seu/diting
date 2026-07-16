"""谛听 · VerdictEngine 测试 — 覆盖所有翻译规则"""

from __future__ import annotations

from datetime import date

from src.diting.engines.registry import discover_engines, get_engine
from src.diting.engines.verdict import VerdictEngine
from src.diting.enums import DataSource, Rating, Signal
from src.diting.schema import (
    AnalysisContext,
    FundFlow,
    RealtimeQuote,
    TechnicalSignals,
    VMDResult,
)

# ── 工厂函数 ────────────────────────────────────────────


def _make_signals(
    rsi: float = 50.0,
    macd: float = 0.0,
    macd_signal: float = 0.0,
    boll_pos: float = 0.5,
) -> TechnicalSignals:
    return TechnicalSignals(
        symbol="000001",
        rsi_14=rsi,
        macd=macd,
        macd_signal_line=macd_signal,
        macd_histogram=macd - macd_signal,
        kdj_k=50.0,
        kdj_d=50.0,
        kdj_j=50.0,
        bollinger_upper=20.0,
        bollinger_middle=15.0,
        bollinger_lower=10.0,
        bollinger_position=boll_pos,
        ma_5=14.0,
        ma_20=15.0,
        ma_60=16.0,
        vwap=14.5,
        vwap_deviation=0.0,
        volume_ratio=1.0,
    )


def _make_vmd(
    cycle_position: float = 0.5,
    trend_broken: bool = False,
) -> VMDResult:
    return VMDResult(
        symbol="000001",
        cycle_position=cycle_position,
        trend_slope=0.0,
        dominant_period=20,
        trend_broken=trend_broken,
        params={"k": 6, "alpha": 2000},
    )


def _make_fund_flow(
    main_net_inflow: float = 0.0,
    ddx: float = 0.0,
) -> FundFlow:
    return FundFlow(
        symbol="000001",
        date=date.today(),
        main_net_inflow=main_net_inflow,
        super_large_net=0.0,
        large_net=0.0,
        medium_net=0.0,
        small_net=0.0,
        ddx=ddx,
        ddy=0.0,
        ddz=0.0,
    )


def _make_realtime(pe: float | None = None) -> RealtimeQuote:
    return RealtimeQuote(
        symbol="000001",
        name="测试股",
        price=15.0,
        change_pct=0.0,
        open=15.0,
        high=15.5,
        low=14.5,
        volume=1000000,
        turnover=15000000.0,
        pe=pe,
        source=DataSource.UNKNOWN,
    )


# ── 评分阈值测试 ────────────────────────────────────────


def test_score_buy_threshold():
    """评分 ≥ 80 → STRONG_BUY + '强烈买入'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        signals=_make_signals(rsi=25.0),  # RSI<30 → +20
        vmd=_make_vmd(cycle_position=0.1),  # VMD<0.3 → +25
        fund_flow=_make_fund_flow(main_net_inflow=2e8, ddx=0.5),  # +10 +10
        # total: 50 + 20 + 25 + 10 + 10 + 5(macd默认=0, 平) = 115 → clamp 100
    )
    result = engine.analyze(ctx)
    assert result.rating == Rating.STRONG_BUY
    assert result.score >= 80
    assert "强烈买入" in result.narrative


def test_score_accumulate_threshold():
    """评分 50-64 → ACCUMULATE + '建议关注'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        # 无信号，基线 50 → ACCUMULATE
    )
    result = engine.analyze(ctx)
    assert result.rating == Rating.ACCUMULATE
    assert 50 <= result.score < 65
    assert "建议关注" in result.narrative


def test_score_hold_threshold():
    """评分 35-54 → HOLD + '建议观望'"""
    engine = VerdictEngine()
    # 50 base, MACD dead → -5 = 45
    ctx = AnalysisContext(
        symbol="000001",
        signals=_make_signals(rsi=50.0, macd=-1.0, macd_signal=0.0),
    )
    result = engine.analyze(ctx)
    assert result.rating == Rating.HOLD
    assert 35 <= result.score < 50
    assert "建议观望" in result.narrative


def test_score_reduce_threshold():
    """评分 < 20 → SELL + '建议回避'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        signals=_make_signals(rsi=80.0),  # RSI>75 → -20
        vmd=_make_vmd(cycle_position=0.9),  # VMD>0.7 → -25
        fund_flow=_make_fund_flow(main_net_inflow=-3e8),  # -10
        realtime=_make_realtime(pe=150.0),  # -10
        # total: 50 - 20 - 25 - 10 - 10 - 5(macd死叉) = -20 → clamp 0
    )
    result = engine.analyze(ctx)
    assert result.rating == Rating.SELL
    assert result.score < 20
    assert "建议回避" in result.narrative


# ── 信号→理由翻译测试 ──────────────────────────────────


def test_rsi_oversold_generates_bull_reason():
    """RSI < 30 → 看多理由 'RSI 超卖，短期有修复动力'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        signals=_make_signals(rsi=22.0),
    )
    result = engine.analyze(ctx)
    assert any("RSI 超卖" in r for r in result.metadata["bull_reasons"])
    assert Signal.RSI_OVERSOLD in result.signals


def test_rsi_overbought_generates_bear_reason():
    """RSI > 75 → 看空理由 'RSI 超买，高位追涨需谨慎'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        signals=_make_signals(rsi=80.0),
    )
    result = engine.analyze(ctx)
    assert any("RSI 超买" in r for r in result.risks)
    assert Signal.RSI_OVERBOUGHT in result.signals


def test_vmd_trough_generates_bull_reason():
    """VMD cycle_position < 0.3 → 看多理由"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        vmd=_make_vmd(cycle_position=0.15),
    )
    result = engine.analyze(ctx)
    assert any("VMD 周期触底" in r for r in result.metadata["bull_reasons"])
    assert Signal.VMD_TROUGH in result.signals


def test_vmd_peak_generates_bear_reason():
    """VMD cycle_position > 0.7 → 看空理由"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        vmd=_make_vmd(cycle_position=0.85),
    )
    result = engine.analyze(ctx)
    assert any("VMD 周期见顶" in r for r in result.risks)
    assert Signal.VMD_PEAK in result.signals


def test_vmd_trend_broken_generates_bear_reason():
    """VMD trend_broken → 看空理由"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        vmd=_make_vmd(cycle_position=0.5, trend_broken=True),
    )
    result = engine.analyze(ctx)
    assert any("趋势已打破" in r for r in result.risks)


def test_fund_inflow_generates_bull_reason():
    """主力净流入 > 1亿 → 看多理由"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        fund_flow=_make_fund_flow(main_net_inflow=5e8),
    )
    result = engine.analyze(ctx)
    assert any("主力资金持续流入" in r for r in result.metadata["bull_reasons"])
    assert Signal.FUND_INFLOW in result.signals


def test_fund_outflow_generates_bear_reason():
    """主力净流出 > 1亿 → 看空理由"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        fund_flow=_make_fund_flow(main_net_inflow=-5e8),
    )
    result = engine.analyze(ctx)
    assert any("主力资金持续流出" in r for r in result.risks)
    assert Signal.FUND_OUTFLOW in result.signals


def test_ddx_generates_bull_reason():
    """DDX > 0.3 → 看多理由 '大单资金连续异动'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        fund_flow=_make_fund_flow(ddx=0.5),
    )
    result = engine.analyze(ctx)
    assert any("大单资金连续异动" in r for r in result.metadata["bull_reasons"])


def test_pe_high_generates_bear_reason():
    """PE > 100 → 看空理由 '估值偏高'"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        realtime=_make_realtime(pe=150.0),
    )
    result = engine.analyze(ctx)
    assert any("估值偏高" in r for r in result.risks)


# ── 综合测试 ───────────────────────────────────────────


def test_empty_context_returns_default():
    """空上下文 → 默认评分 50 + HOLD"""
    engine = VerdictEngine()
    ctx = AnalysisContext(symbol="000001")
    result = engine.analyze(ctx)
    assert result.score == 50.0
    assert result.rating == Rating.ACCUMULATE
    assert "建议关注" in result.narrative


def test_mixed_signals_produces_both_reasons():
    """混合信号 → 同时有看多和看空理由"""
    engine = VerdictEngine()
    ctx = AnalysisContext(
        symbol="000001",
        signals=_make_signals(rsi=22.0),       # 看多
        vmd=_make_vmd(cycle_position=0.85),     # 看空
    )
    result = engine.analyze(ctx)
    assert len(result.metadata["bull_reasons"]) >= 1
    assert len(result.risks) >= 1


def test_registry_includes_verdict():
    """注册表包含 'verdict' 引擎"""
    engines = discover_engines()
    assert "verdict" in engines
    engine_cls = get_engine("verdict")
    assert engine_cls is VerdictEngine


def test_required_data():
    """VerdictEngine 声明需要 REALTIME 数据"""
    engine = VerdictEngine()
    from src.diting.enums import DataType
    assert DataType.REALTIME in engine.required_data()
