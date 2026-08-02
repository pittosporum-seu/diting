"""谛听 · 数据协议 — 所有跨模块通信的 @dataclass 定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .enums import (
    AnalysisProfile,
    CacheState,
    CacheTier,
    DataSource,
    EngineRunStatus,
    FetchMode,
    JobType,
    Rating,
    RunStatus,
    StrategyState,
    TraceOutcome,
    VerdictLabel,
)

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


# ============================================================
# Web 响应协议
# ============================================================


@dataclass
class EngineScoreItem:
    """单个分析引擎的评分结果。"""

    engine_name: str
    score: float
    rating: str
    rating_label: str
    confidence: float
    duration_ms: int = 0


@dataclass
class EngineSkipInfo:
    """被跳过的分析引擎信息。"""

    engine_name: str
    reason: str  # "no_api_key", "non_trading_hours", "timeout", "error"


@dataclass
class StockAnalysisResponse:
    """analyze_stock 的返回协议 — 个股全流程分析结果。"""

    def get(self, key: str, default=None):
        """Provide mapping-compatible reads during the response migration."""
        aliases = {"signals": self.signals_summary}
        return aliases.get(key, getattr(self, key, default))

    def __contains__(self, key: object) -> bool:
        """Support legacy membership checks at API boundaries."""
        return isinstance(key, str) and self.get(key) is not None

    def __getitem__(self, key: str):
        """Support legacy indexing at API boundaries."""
        value = self.get(key)
        if value is None and not hasattr(self, key):
            raise KeyError(key)
        return value

    code: str
    name: str
    price: float
    change_pct: float
    pe: float | None = None
    pb: float | None = None
    total_mv: float | None = None
    score: float = 50.0
    rating: str = "hold"
    rating_label: str = "建议观望"
    rating_emoji: str = "⚪"
    confidence: float = 0.5
    engine_scores: list[EngineScoreItem] = field(default_factory=list)
    engine_skipped: list[EngineSkipInfo] = field(default_factory=list)
    bull_reasons: list[str] = field(default_factory=list)
    bear_reasons: list[str] = field(default_factory=list)
    rsi_display: str = ""
    macd_display: str = ""
    chart_data: dict = field(default_factory=dict)
    signals_summary: dict | None = None
    error: str | None = None
    _cache_state: str = "fresh"  # 内部字段，序列化时排除


# ============================================================
# 基础设施协议
# ============================================================


@dataclass(frozen=True)
class FreshnessInfo:
    """数据新鲜度信息，在所有 API 响应中透传。"""

    data_time: datetime | None  # 数据产生时间（provider 返回的时间戳）
    source: str  # 来源标识（mx-data / eastmoney / cache）
    is_fresh: bool  # 是否在有效期内
    age_seconds: float  # 数据年龄（秒）
    ttl_seconds: int  # 有效期（秒）


# ============================================================
# v0.8 immutable data-access contracts
# ============================================================


@dataclass(frozen=True)
class DataWarning:
    code: str
    message: str
    provider: str | None = None
    recoverable: bool = True


@dataclass(frozen=True)
class ProviderTrace:
    provider: str
    operation: str
    outcome: TraceOutcome
    started_at: datetime
    finished_at: datetime
    attempt: int = 1
    error_code: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class CacheInfo:
    state: CacheState = CacheState.MISS
    tier: CacheTier = CacheTier.NONE
    cache_key: str = ""
    cached_at: datetime | None = None
    expires_at: datetime | None = None
    stale_until: datetime | None = None
    schema_version: str = "v1"
    single_flight_shared: bool = False

    @property
    def hit(self) -> bool:
        return self.state in {CacheState.FRESH, CacheState.STALE, CacheState.NEGATIVE}


@dataclass(frozen=True)
class DataResult[T]:
    data: T | None
    data_time: datetime | None
    cache_info: CacheInfo = field(default_factory=CacheInfo)
    provider_traces: tuple[ProviderTrace, ...] = ()
    warnings: tuple[DataWarning, ...] = ()
    request_hash: str = ""
    error_code: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_code is None and self.data is not None


@dataclass(frozen=True)
class HistoricalBar:
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float | None = None


@dataclass(frozen=True)
class HistoricalSeries:
    symbol: str
    bars: tuple[HistoricalBar, ...]
    period: str = "1d"
    adjustment: str = "forward"
    schema_version: str = "bars-v1"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    market: str
    instrument_type: str
    listed_on: date | None = None
    delisted_on: date | None = None


@dataclass(frozen=True)
class InstrumentPage:
    items: tuple[Instrument, ...]
    total: int
    next_cursor: str | None = None


@dataclass(frozen=True)
class TradingSession:
    trading_date: date
    market: str
    is_open: bool
    open_at: datetime | None = None
    close_at: datetime | None = None


@dataclass(frozen=True)
class TradingCalendar:
    market: str
    sessions: tuple[TradingSession, ...]
    timezone: str = "Asia/Shanghai"


@dataclass(frozen=True)
class QuoteRequest:
    symbols: tuple[str, ...]
    mode: FetchMode = FetchMode.CACHE_PREFERRED
    force_refresh: bool = False
    deadline: datetime | None = None


@dataclass(frozen=True)
class HistoricalRequest:
    symbol: str
    start_date: date
    end_date: date
    period: str = "1d"
    adjustment: str = "forward"
    mode: FetchMode = FetchMode.CACHE_PREFERRED
    force_refresh: bool = False
    deadline: datetime | None = None


@dataclass(frozen=True)
class FinancialRequest:
    symbol: str
    as_of: date | None = None
    mode: FetchMode = FetchMode.CACHE_PREFERRED
    force_refresh: bool = False
    deadline: datetime | None = None


@dataclass(frozen=True)
class FundFlowRequest:
    symbol: str
    trading_date: date | None = None
    mode: FetchMode = FetchMode.CACHE_PREFERRED
    force_refresh: bool = False
    deadline: datetime | None = None


@dataclass(frozen=True)
class InstrumentSearchRequest:
    query: str
    market: str | None = None
    limit: int = 20
    cursor: str | None = None
    mode: FetchMode = FetchMode.CACHE_PREFERRED
    force_refresh: bool = False


@dataclass(frozen=True)
class TradingCalendarRequest:
    market: str
    start_date: date
    end_date: date
    mode: FetchMode = FetchMode.CACHE_PREFERRED
    force_refresh: bool = False


# ============================================================
# v0.8 immutable analysis and strategy contracts
# ============================================================


@dataclass(frozen=True)
class AnalysisRequest:
    """Frozen input for every CLI, HTTP, Python and worker analysis."""

    symbol: str
    profile: AnalysisProfile = AnalysisProfile.STANDARD
    as_of: datetime | None = None
    force_refresh: bool = False
    requested_engines: tuple[str, ...] | None = None
    request_id: str = ""
    deadline: datetime | None = None
    enable_sandbox: bool = False


@dataclass(frozen=True)
class DataSnapshot:
    snapshot_id: str
    symbol: str
    created_at: datetime
    as_of: datetime
    quote: DataResult[RealtimeQuote] | None = None
    historical: DataResult[HistoricalSeries] | None = None
    financials: DataResult[Financials] | None = None
    fund_flow: DataResult[FundFlow] | None = None
    provider_traces: tuple[ProviderTrace, ...] = ()
    completeness: float = 0.0
    snapshot_hash: str = ""
    warnings: tuple[DataWarning, ...] = ()


@dataclass(frozen=True)
class EngineCapabilities:
    asset_types: tuple[str, ...] = ("stock", "etf")
    required_data: tuple[str, ...] = ()
    min_history_bars: int = 0
    requires_llm: bool = False
    requires_sandbox: bool = False
    requires_network: bool = False
    supports_batch: bool = False
    deterministic: bool = True
    timeout_seconds: int = 15


@dataclass(frozen=True)
class EngineContext:
    deadline: datetime | None
    config_hash: str
    strategy_version: str
    prompt_version: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class Evidence:
    code: str
    summary: str
    value: float | str | None = None


@dataclass(frozen=True)
class Risk:
    code: str
    summary: str


@dataclass(frozen=True)
class EngineResult:
    engine_name: str
    engine_version: str
    symbol: str
    engine_score: float
    rating: Rating
    confidence: float
    narrative: str
    evidence: tuple[Evidence, ...] = ()
    risks: tuple[Risk, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EngineRun:
    engine_name: str
    engine_version: str
    status: EngineRunStatus
    deterministic: bool
    started_at: datetime
    finished_at: datetime | None = None
    engine_score: float | None = None
    confidence: float | None = None
    result: EngineResult | None = None
    error_code: str | None = None
    error_detail: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    duration_ms: int = 0

    @property
    def score(self) -> float | None:
        """Compatibility read for persisted pre-v0.8 rows; new contracts use engine_score."""

        return self.engine_score


@dataclass(frozen=True)
class ConsensusConflict:
    engine_a: str
    engine_b: str
    score_a: float
    score_b: float
    severity: str


@dataclass(frozen=True)
class ConsensusResult:
    symbol: str
    analysis_score: float | None
    confidence: float
    weight_coverage: float
    engines_used: tuple[str, ...] = ()
    engines_failed: tuple[str, ...] = ()
    conflicts: tuple[ConsensusConflict, ...] = ()
    weight_snapshot: tuple[tuple[str, float], ...] = ()
    insufficient_reason: str | None = None


@dataclass(frozen=True)
class Verdict:
    label: VerdictLabel
    horizon: str
    summary: str
    bull_evidence: tuple[Evidence, ...] = ()
    bear_evidence: tuple[Evidence, ...] = ()
    risks: tuple[Risk, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class AnalysisRun:
    run_id: str
    request: AnalysisRequest
    status: RunStatus
    snapshot_id: str
    snapshot_hash: str
    config_hash: str
    strategy_version: str
    code_version: str
    started_at: datetime
    engine_runs: tuple[EngineRun, ...] = ()
    consensus: ConsensusResult | None = None
    verdict: Verdict | None = None
    completed_at: datetime | None = None
    warnings: tuple[DataWarning, ...] = ()

    @property
    def symbol(self) -> str:
        return self.request.symbol

    @property
    def profile(self) -> AnalysisProfile:
        return self.request.profile

    @property
    def analysis_score(self) -> float | None:
        return self.consensus.analysis_score if self.consensus is not None else None

    @property
    def confidence(self) -> float | None:
        return self.consensus.confidence if self.consensus is not None else None


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    job_type: JobType
    status: RunStatus
    progress: float
    request_json: str
    created_at: datetime
    dedupe_key: str | None = None
    result_ref: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deadline_at: datetime | None = None
    cancel_requested: bool = False


@dataclass(frozen=True)
class ScanItem:
    symbol: str
    name: str
    rank: int
    score: float
    strategy_version: str
    data_date: date
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    scan_id: str
    status: RunStatus
    strategy_version: str | None
    data_date: date | None
    items: tuple[ScanItem, ...] = ()
    warnings: tuple[DataWarning, ...] = ()
    error_code: str | None = None


@dataclass(frozen=True)
class StrategyVersion:
    name: str
    version: str
    state: StrategyState
    manifest_hash: str
    created_at: datetime
    activated_at: datetime | None = None


# ============================================================
# v0.8 port payloads
# ============================================================


@dataclass(frozen=True)
class CacheRecord:
    key: str
    data_type: str
    payload: bytes
    created_at: datetime
    expires_at: datetime
    stale_until: datetime
    schema_version: str
    negative: bool = False
    error_code: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProviderHealthRecord:
    provider: str
    consecutive_failures: int = 0
    circuit_open_until: datetime | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None


@dataclass(frozen=True)
class CacheLookup:
    record: CacheRecord | None
    tier: CacheTier = CacheTier.NONE


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[tuple[str, str], ...]
    response_schema: str
    model: str
    max_tokens: int = 4000
    deadline: datetime | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    request_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class SandboxRequest:
    code: str
    timeout_seconds: int = 60
    memory_mb: int = 512


@dataclass(frozen=True)
class SandboxResponse:
    output: str
    audit_id: str
    execution_time_ms: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportArtifact:
    run_id: str
    path: Path
    media_type: str
    sha256: str


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    severity: str = "info"
