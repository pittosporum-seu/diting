"""谛听 · 枚举定义"""

from enum import Enum, StrEnum


class Rating(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    ACCUMULATE = "accumulate"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"


class DataSource(Enum):
    MX_DATA = "mx_data"
    AKSHARE = "akshare"
    ASHARE = "ashare"
    EAST_MONEY = "east_money"
    SQLITE = "sqlite"
    CSV = "csv"
    CACHE = "cache"
    UNKNOWN = "unknown"


class DataType(Enum):
    REALTIME = "realtime"
    HISTORICAL = "historical"
    FUNDAMENTALS = "fundamentals"
    FUND_FLOW = "fund_flow"
    MINUTE = "minute"


class Signal(Enum):
    VMD_TROUGH = "vmd_trough"
    VMD_PEAK = "vmd_peak"
    VMD_TREND_BROKEN = "vmd_trend_broken"
    RSI_OVERSOLD = "rsi_oversold"
    RSI_OVERBOUGHT = "rsi_overbought"
    WYCKOFF_SPRING = "wyckoff_spring"
    WYCKOFF_SOS = "wyckoff_sos"
    VOLUME_SURGE = "volume_surge"
    VOLUME_DRIED = "volume_dried"
    FUND_INFLOW = "fund_inflow"
    FUND_OUTFLOW = "fund_outflow"


class FetchMode(StrEnum):
    """How the data gateway may use caches and upstream providers."""

    CACHE_PREFERRED = "cache_preferred"
    FRESH_REQUIRED = "fresh_required"
    CACHE_ONLY = "cache_only"


class CacheTier(StrEnum):
    NONE = "none"
    L1 = "l1"
    L2 = "l2"
    UPSTREAM = "upstream"


class CacheState(StrEnum):
    MISS = "miss"
    FRESH = "fresh"
    STALE = "stale"
    NEGATIVE = "negative"


class TraceOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    CIRCUIT_OPEN = "circuit_open"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class EngineRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class EngineMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_STRUCTURED = "llm_structured"
    LLM_CODE_SANDBOX = "llm_code_sandbox"


class AnalysisProfile(StrEnum):
    STANDARD = "standard"
    DEEP = "deep"


class VerdictLabel(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    CAUTIOUS = "cautious"
    INSUFFICIENT = "insufficient"


class JobType(StrEnum):
    ANALYSIS = "analysis"
    SCAN = "scan"
    REPORT = "report"
    NOTIFICATION = "notification"


class StrategyState(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    ACTIVE = "active"
    RETIRED = "retired"
