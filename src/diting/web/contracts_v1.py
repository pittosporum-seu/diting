"""Typed HTTP v1 envelopes and public read response models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict

from ..schema import CacheInfo, DataResult, DataWarning


class _HttpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorInfo(_HttpModel):
    code: str
    message: str
    retryable: bool = False


class WarningInfo(_HttpModel):
    code: str
    message: str
    provider: str | None = None
    recoverable: bool = True


class CacheMeta(_HttpModel):
    state: str
    level: str
    stored_at: datetime | None = None
    expires_at: datetime | None = None
    stale_until: datetime | None = None
    schema_version: str


class FreshnessMeta(_HttpModel):
    data_time: datetime | None = None
    sources: tuple[str, ...] = ()
    age_seconds: float | None = None


class ResponseMeta(_HttpModel):
    result_status: str = "succeeded"
    cache: CacheMeta | None = None
    freshness: FreshnessMeta | None = None
    warnings: tuple[WarningInfo, ...] = ()


class ApiEnvelope[T](_HttpModel):
    api_version: Literal["1.0"] = "1.0"
    request_id: str
    server_time: datetime
    data: T | None
    meta: ResponseMeta
    error: ErrorInfo | None = None


class HealthData(_HttpModel):
    status: Literal["ok", "ready"]
    version: str


class AuthSessionData(_HttpModel):
    authenticated: bool
    configured: bool = True
    csrf_token: str | None = None
    expires_at: datetime | None = None


class InstrumentView(_HttpModel):
    symbol: str
    name: str
    market: str
    instrument_type: str
    listed_on: str | None = None
    delisted_on: str | None = None


class InstrumentSearchData(_HttpModel):
    items: tuple[InstrumentView, ...]
    total: int
    next_cursor: str | None = None


class QuoteData(_HttpModel):
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
    timestamp: datetime
    source: str


class EngineRunView(_HttpModel):
    engine_name: str
    engine_version: str
    status: str
    deterministic: bool
    engine_score: float | None = None
    confidence: float | None = None
    error_code: str | None = None
    duration_ms: int


class ConsensusView(_HttpModel):
    analysis_score: float | None
    confidence: float
    weight_coverage: float
    engines_used: tuple[str, ...]
    engines_failed: tuple[str, ...]
    insufficient_reason: str | None = None


class VerdictView(_HttpModel):
    label: str
    horizon: str
    summary: str
    confidence: float


class AnalysisRunView(_HttpModel):
    run_id: str
    symbol: str
    profile: str
    status: str
    snapshot_id: str
    snapshot_hash: str
    config_hash: str
    strategy_version: str
    code_version: str
    started_at: datetime
    completed_at: datetime | None
    engine_runs: tuple[EngineRunView, ...]
    consensus: ConsensusView | None = None
    verdict: VerdictView | None = None


class DashboardData(_HttpModel):
    version: str
    analysis_available: bool
    active_strategy: str | None
    public_readonly: bool


class OpportunityView(_HttpModel):
    symbol: str
    name: str
    rank: int
    screening_score: float
    strategy_version: str
    data_date: str
    evidence: tuple[str, ...] = ()


class OpportunitiesData(_HttpModel):
    items: tuple[OpportunityView, ...] = ()
    total: int = 0
    strategy_version: str | None = None


class JobView(_HttpModel):
    job_id: str
    job_type: str
    status: str
    progress: float
    result_ref: str | None = None
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deadline_at: datetime | None = None
    cancel_requested: bool = False


class WatchlistView(_HttpModel):
    symbol: str
    name: str
    market: str
    tags: tuple[str, ...] = ()
    created_at: datetime
    updated_at: datetime


class WatchlistData(_HttpModel):
    items: tuple[WatchlistView, ...]
    total: int


class PreferenceView(_HttpModel):
    key: str
    value: str | int | bool
    updated_at: datetime


class PreferencesData(_HttpModel):
    items: tuple[PreferenceView, ...]


class CacheClearData(_HttpModel):
    cleared: int
    prefix: str | None = None


class StrategyStatusData(_HttpModel):
    selected: str
    active: bool
    version: str | None = None
    state: str | None = None
    manifest_hash: str | None = None
    activated_at: datetime | None = None


class DiagnosticsData(_HttpModel):
    version: str
    environment: str
    public_readonly: bool
    owner_auth_configured: bool
    analysis_available: bool
    jobs_available: bool
    cache_available: bool
    strategy_selected: str
    strategy_active: bool


def success_envelope[T](
    request: Request,
    data: T,
    *,
    result_status: str = "succeeded",
    cache: CacheMeta | None = None,
    freshness: FreshnessMeta | None = None,
    warnings: tuple[WarningInfo, ...] = (),
) -> ApiEnvelope[T]:
    return ApiEnvelope(
        request_id=request_id(request),
        server_time=datetime.now(UTC),
        data=data,
        meta=ResponseMeta(
            result_status=result_status,
            cache=cache,
            freshness=freshness,
            warnings=warnings,
        ),
    )


def error_envelope(
    request: Request,
    *,
    code: str,
    message: str,
    retryable: bool = False,
) -> ApiEnvelope[object]:
    return ApiEnvelope(
        request_id=request_id(request),
        server_time=datetime.now(UTC),
        data=None,
        meta=ResponseMeta(result_status="failed"),
        error=ErrorInfo(code=code, message=message, retryable=retryable),
    )


def data_result_meta(
    result: DataResult[object],
) -> tuple[CacheMeta, FreshnessMeta, tuple[WarningInfo, ...]]:
    cache = _cache_meta(result.cache_info)
    sources = tuple(dict.fromkeys(trace.provider for trace in result.provider_traces))
    age = None
    if result.data_time is not None:
        data_time = result.data_time
        if data_time.tzinfo is None:
            data_time = data_time.replace(tzinfo=UTC)
        age = max(0.0, (datetime.now(UTC) - data_time).total_seconds())
    freshness = FreshnessMeta(data_time=result.data_time, sources=sources, age_seconds=age)
    warnings = tuple(_warning(item) for item in result.warnings)
    return cache, freshness, warnings


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    value = f"req_{uuid4().hex}"
    request.state.request_id = value
    return value


def _cache_meta(info: CacheInfo) -> CacheMeta:
    return CacheMeta(
        state=info.state.value,
        level=info.tier.value,
        stored_at=info.cached_at,
        expires_at=info.expires_at,
        stale_until=info.stale_until,
        schema_version=info.schema_version,
    )


def _warning(warning: DataWarning) -> WarningInfo:
    return WarningInfo(
        code=warning.code,
        message=warning.message,
        provider=warning.provider,
        recoverable=warning.recoverable,
    )
