"""谛听 · 数据协议 — 所有跨模块通信的 @dataclass 定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .enums import DataSource, Rating

# ============================================================
# 数据层协议
# ============================================================

@dataclass(frozen=True)
class RealtimeQuote:
    """实时行情"""
    symbol: str
    name: str
    price: float
    change_pct: float
    open: float
    high: float
    low: float
    volume: int
    turnover: float
    pe: float | None = None
    pb: float | None = None
    total_mv: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: DataSource = DataSource.UNKNOWN


@dataclass(frozen=True)
class HistoricalData:
    """历史行情"""
    symbol: str
    df: Any
    columns: list[str]
    start_date: date
    end_date: date
    source: DataSource = DataSource.UNKNOWN


@dataclass(frozen=True)
class Financials:
    """财务数据"""
    symbol: str
    report_date: date
    revenue: float
    revenue_yoy: float
    net_profit: float
    profit_yoy: float
    gross_margin: float
    net_margin: float
    roe: float
    debt_ratio: float
    current_ratio: float
    quick_ratio: float
    fcf: float | None = None
    op_cash_flow: float | None = None
    source: DataSource = DataSource.UNKNOWN


@dataclass(frozen=True)
class FundFlow:
    """资金流向"""
    symbol: str
    date: date
    main_net_inflow: float
    super_large_net: float
    large_net: float
    medium_net: float
    small_net: float
    ddx: float
    ddy: float
    ddz: float
    margin_balance: float | None = None
    margin_buy: float | None = None


# ============================================================
# 信号层协议
# ============================================================

@dataclass(frozen=True)
class VMDResult:
    """VMD 分解结果"""
    symbol: str
    cycle_position: float
    trend_slope: float
    dominant_period: int
    trend_broken: bool
    timestamp: datetime = field(default_factory=datetime.now)
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TechnicalSignals:
    """技术指标信号"""
    symbol: str
    rsi_14: float
    macd: float
    macd_signal_line: float
    macd_histogram: float
    kdj_k: float
    kdj_d: float
    kdj_j: float
    bollinger_upper: float
    bollinger_middle: float
    bollinger_lower: float
    bollinger_position: float
    ma_5: float
    ma_20: float
    ma_60: float
    vwap: float
    vwap_deviation: float
    volume_ratio: float
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================
# 分析层协议
# ============================================================

@dataclass(frozen=True)
class AnalysisContext:
    """传给分析引擎的完整上下文"""
    symbol: str
    realtime: RealtimeQuote | None = None
    historical: HistoricalData | None = None
    signals: TechnicalSignals | None = None
    vmd: VMDResult | None = None
    financials: Financials | None = None
    fund_flow: FundFlow | None = None


@dataclass(frozen=True)
class AnalysisResult:
    """所有分析引擎的统一输出"""
    engine_name: str
    engine_version: str
    symbol: str
    score: float
    rating: Rating
    signals: tuple = ()
    narrative: str = ""
    charts: tuple = ()
    risks: tuple = ()
    confidence: float = 0.5
    computation_log: str = ""
    metadata: dict = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0


# ============================================================
# 管道层协议
# ============================================================

@dataclass(frozen=True)
class ConsensusScore:
    """多引擎共识评分"""
    symbol: str
    weighted_score: float
    rating: Rating
    engines_used: tuple = ()
    engines_failed: tuple = ()
    confidence: float = 0.5


@dataclass(frozen=True)
class Conflict:
    """引擎间的评级冲突"""
    engine_a: str
    engine_b: str
    a_rating: Rating
    b_rating: Rating
    severity: str  # "mild" | "moderate" | "severe"


@dataclass(frozen=True)
class PipelineResult:
    """管道完整执行结果"""
    symbols: tuple = ()
    results: dict = field(default_factory=dict)
    consensus: dict = field(default_factory=dict)
    reports: dict = field(default_factory=dict)
    errors: tuple = ()
    metrics: dict = field(default_factory=dict)
