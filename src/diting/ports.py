"""Dependency-inversion ports for the v0.8 application core."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from .enums import StrategyState
from .schema import (
    AnalysisRun,
    AuditEvent,
    CacheLookup,
    CacheRecord,
    DataResult,
    DataSnapshot,
    ExperimentManifest,
    FinancialRequest,
    Financials,
    FundFlow,
    FundFlowRequest,
    HistoricalRequest,
    HistoricalSeries,
    InstrumentPage,
    InstrumentSearchRequest,
    JobRecord,
    LLMRequest,
    LLMResponse,
    Notification,
    OwnerSession,
    PreferenceRecord,
    ProviderHealthRecord,
    QuoteRequest,
    RealtimeQuote,
    ReportArtifact,
    SandboxRequest,
    SandboxResponse,
    ScanResult,
    StrategyVersion,
    TradingCalendar,
    TradingCalendarRequest,
    WatchlistEntry,
)


@runtime_checkable
class DataGateway(Protocol):
    def get_quotes(self, request: QuoteRequest) -> Mapping[str, DataResult[RealtimeQuote]]: ...

    def get_historical(self, request: HistoricalRequest) -> DataResult[HistoricalSeries]: ...

    def get_financials(self, request: FinancialRequest) -> DataResult[Financials]: ...

    def get_fund_flow(self, request: FundFlowRequest) -> DataResult[FundFlow]: ...

    def search_instruments(
        self, request: InstrumentSearchRequest
    ) -> DataResult[InstrumentPage]: ...

    def get_trading_calendar(
        self, request: TradingCalendarRequest
    ) -> DataResult[TradingCalendar]: ...


@runtime_checkable
class MarketDataProvider(Protocol):
    @property
    def name(self) -> str: ...

    def get_quotes(self, request: QuoteRequest) -> tuple[RealtimeQuote, ...]: ...

    def get_historical(self, request: HistoricalRequest) -> HistoricalSeries: ...

    def get_financials(self, request: FinancialRequest) -> Financials: ...

    def get_fund_flow(self, request: FundFlowRequest) -> FundFlow: ...

    def search_instruments(self, request: InstrumentSearchRequest) -> InstrumentPage: ...

    def get_trading_calendar(self, request: TradingCalendarRequest) -> TradingCalendar: ...


@runtime_checkable
class CacheStore(Protocol):
    def lookup(self, key: str) -> CacheLookup: ...

    def set(self, record: CacheRecord) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear(self, prefix: str | None = None) -> int: ...

    def get_provider_health(self, provider: str) -> ProviderHealthRecord | None: ...

    def set_provider_health(self, record: ProviderHealthRecord) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class DurableStore(Protocol):
    def save_data_snapshot(self, snapshot: DataSnapshot) -> None: ...

    def save_analysis_run(self, run: AnalysisRun) -> None: ...

    def get_analysis_run(self, run_id: str) -> AnalysisRun | None: ...

    def create_job(self, job: JobRecord) -> None: ...

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def get_active_job_by_dedupe(self, dedupe_key: str) -> JobRecord | None: ...

    def update_job(self, job: JobRecord) -> None: ...

    def interrupt_running_jobs(self, finished_at: datetime) -> int: ...

    def create_owner_session(self, session: OwnerSession) -> None: ...

    def get_owner_session(self, session_id: str) -> OwnerSession | None: ...

    def revoke_owner_session(self, session_id: str, revoked_at: datetime) -> bool: ...

    def upsert_watchlist(self, entry: WatchlistEntry) -> None: ...

    def list_watchlist(self, owner_id: str) -> tuple[WatchlistEntry, ...]: ...

    def delete_watchlist(self, owner_id: str, symbol: str) -> bool: ...

    def save_preference(self, preference: PreferenceRecord) -> None: ...

    def list_preferences(self, owner_id: str) -> tuple[PreferenceRecord, ...]: ...

    def append_audit(self, event: AuditEvent) -> None: ...

    def save_scan_result(self, result: ScanResult) -> None: ...

    def get_scan_result(self, scan_id: str) -> ScanResult | None: ...

    def get_latest_scan_result(self, strategy_version: str) -> ScanResult | None: ...

    def save_strategy(self, strategy: StrategyVersion) -> bool: ...

    def save_experiment_manifest(self, manifest: ExperimentManifest) -> bool: ...

    def get_experiment_manifest(self, manifest_hash: str) -> ExperimentManifest | None: ...

    def get_strategy(self, name: str, version: str) -> StrategyVersion | None: ...

    def list_strategies(self, name: str | None = None) -> tuple[StrategyVersion, ...]: ...

    def transition_strategy(
        self,
        name: str,
        version: str,
        expected: StrategyState,
        target: StrategyState,
    ) -> bool: ...

    def activate_strategy(self, name: str, version: str, activated_at: datetime) -> bool: ...

    def get_active_strategy(self, name: str) -> StrategyVersion | None: ...

    def close(self) -> None: ...


@runtime_checkable
class ScanOrchestratorPort(Protocol):
    def scan(
        self,
        *,
        limit: int = 20,
        progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ScanResult: ...


@runtime_checkable
class LLMPort(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


@runtime_checkable
class SandboxPort(Protocol):
    def execute(self, request: SandboxRequest) -> SandboxResponse: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class CalendarPort(Protocol):
    def get_calendar(self, request: TradingCalendarRequest) -> TradingCalendar: ...

    def market_phase(self, market: str, at: datetime) -> str: ...

    def next_open(self, market: str, at: datetime) -> datetime | None: ...


@runtime_checkable
class ReportPort(Protocol):
    def build(self, run: AnalysisRun) -> ReportArtifact: ...


@runtime_checkable
class Notifier(Protocol):
    def send(self, notification: Notification) -> None: ...
