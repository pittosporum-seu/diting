"""Cached market-data gateway implementing the v0.8 data-access contract."""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from enum import Enum
from typing import Any

from ..enums import CacheState, CacheTier, FetchMode, TraceOutcome
from ..infra.errors import ProviderNotFoundError, ProviderTransientError
from ..ports import CacheStore, CalendarPort, Clock, MarketDataProvider
from ..schema import (
    CacheInfo,
    CacheRecord,
    DataResult,
    DataWarning,
    FinancialRequest,
    Financials,
    FundFlow,
    FundFlowRequest,
    HistoricalRequest,
    HistoricalSeries,
    InstrumentPage,
    InstrumentSearchRequest,
    ProviderHealthRecord,
    ProviderTrace,
    QuoteRequest,
    RealtimeQuote,
    TradingCalendar,
    TradingCalendarRequest,
)
from .codec_v080 import SCHEMA_VERSIONS, decode_payload, encode_payload


@dataclass(frozen=True)
class CachePolicy:
    ttl_seconds: int
    stale_if_error_seconds: int


DEFAULT_POLICIES = {
    "quote": CachePolicy(30, 24 * 60 * 60),
    "historical": CachePolicy(5 * 60, 7 * 24 * 60 * 60),
    "fund_flow": CachePolicy(5 * 60, 3 * 24 * 60 * 60),
    "financials": CachePolicy(6 * 60 * 60, 30 * 24 * 60 * 60),
    "instrument_page": CachePolicy(24 * 60 * 60, 30 * 24 * 60 * 60),
    "trading_calendar": CachePolicy(7 * 24 * 60 * 60, 30 * 24 * 60 * 60),
}


@dataclass
class _CircuitState:
    failures: int = 0
    open_until: datetime | None = None
    half_open_inflight: bool = False


class _DeadlineExceededError(Exception):
    """Internal control flow used to stop retries after a request deadline."""


class CachedMarketDataGateway:
    """The only v0.8 business path for market-data acquisition."""

    def __init__(
        self,
        providers: tuple[MarketDataProvider, ...],
        cache: CacheStore,
        clock: Clock,
        *,
        calendar: CalendarPort | None = None,
        policies: Mapping[str, CachePolicy] | None = None,
        retry_count: int = 2,
        circuit_threshold: int = 3,
        circuit_seconds: int = 60,
        background_refresh: bool = True,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._providers = providers
        self._cache = cache
        self._clock = clock
        self._calendar = calendar
        self._policies = {**DEFAULT_POLICIES, **(policies or {})}
        self._retry_count = retry_count
        self._circuit_threshold = circuit_threshold
        self._circuit_seconds = circuit_seconds
        self._sleeper = sleeper
        self._jitter = jitter
        self._circuits: dict[str, _CircuitState] = {}
        self._circuit_lock = threading.RLock()
        self._flights: dict[str, Future[Any]] = {}
        self._flight_lock = threading.RLock()
        self._executor = (
            ThreadPoolExecutor(max_workers=2, thread_name_prefix="diting-cache-refresh")
            if background_refresh
            else None
        )

    def get_quotes(self, request: QuoteRequest) -> dict[str, DataResult[RealtimeQuote]]:
        symbols = tuple(dict.fromkeys(request.symbols))
        request_hash = _hash_payload(asdict(request))
        if self._deadline_exceeded(request.deadline):
            return {symbol: self._deadline_result(request_hash) for symbol in symbols}
        results: dict[str, DataResult[RealtimeQuote]] = {}
        fetch_symbols: list[str] = []
        refresh_symbols: list[str] = []

        for symbol in symbols:
            key = self._cache_key("quote", {"symbol": symbol})
            if request.force_refresh:
                fetch_symbols.append(symbol)
                continue
            result, stale = self._read_cached("quote", key, request_hash)
            if result is not None and result.cache_info.state in {
                CacheState.FRESH,
                CacheState.NEGATIVE,
            }:
                results[symbol] = result
            elif request.mode is FetchMode.CACHE_ONLY:
                results[symbol] = result or self._cache_miss(request_hash)
            elif request.mode is FetchMode.CACHE_PREFERRED and result is not None:
                results[symbol] = result
                refresh_symbols.append(symbol)
            else:
                fetch_symbols.append(symbol)
                if stale is not None:
                    results[symbol] = stale

        if fetch_symbols:
            flight_key = "quotes:" + _hash_payload(tuple(sorted(fetch_symbols)))
            fetched = self._single_flight(
                flight_key,
                lambda: self._load_quotes(tuple(fetch_symbols), request, request_hash),
            )
            for symbol in fetch_symbols:
                current = fetched[symbol]
                stale = results.get(symbol)
                results[symbol] = self._stale_if_error(stale, current)

        if refresh_symbols:
            self._schedule_quotes(tuple(refresh_symbols), request)
        return {symbol: results[symbol] for symbol in symbols}

    def get_historical(self, request: HistoricalRequest) -> DataResult[HistoricalSeries]:
        return self._get_one("historical", request, "get_historical")

    def get_financials(self, request: FinancialRequest) -> DataResult[Financials]:
        return self._get_one("financials", request, "get_financials")

    def get_fund_flow(self, request: FundFlowRequest) -> DataResult[FundFlow]:
        return self._get_one("fund_flow", request, "get_fund_flow")

    def search_instruments(self, request: InstrumentSearchRequest) -> DataResult[InstrumentPage]:
        return self._get_one("instrument_page", request, "search_instruments")

    def get_trading_calendar(self, request: TradingCalendarRequest) -> DataResult[TradingCalendar]:
        return self._get_one("trading_calendar", request, "get_trading_calendar")

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
        self._cache.close()

    def _get_one(self, data_type: str, request: Any, method_name: str) -> DataResult[Any]:
        request_hash = _hash_payload(asdict(request))
        if self._deadline_exceeded(getattr(request, "deadline", None)):
            return self._deadline_result(request_hash)
        key = self._cache_key(data_type, _cache_dimensions(request))
        force_refresh = bool(getattr(request, "force_refresh", False))
        mode = getattr(request, "mode", FetchMode.CACHE_PREFERRED)
        cached, stale = (
            (None, None) if force_refresh else self._read_cached(data_type, key, request_hash)
        )
        if not force_refresh and cached is not None:
            if cached.cache_info.state in {CacheState.FRESH, CacheState.NEGATIVE}:
                return cached
            if mode is FetchMode.CACHE_ONLY:
                return cached
            if mode is FetchMode.CACHE_PREFERRED:
                self._schedule_one(data_type, request, method_name)
                return cached
        if mode is FetchMode.CACHE_ONLY:
            return self._cache_miss(request_hash)

        loaded = self._single_flight(
            "fetch:" + key,
            lambda: self._load_one(data_type, request, method_name, key, request_hash),
        )
        return self._stale_if_error(stale, loaded)

    def _load_quotes(
        self,
        symbols: tuple[str, ...],
        request: QuoteRequest,
        request_hash: str,
    ) -> dict[str, DataResult[RealtimeQuote]]:
        remaining = list(symbols)
        quotes: dict[str, RealtimeQuote] = {}
        traces: list[ProviderTrace] = []
        not_found: set[str] = set()
        deadline_exceeded = False
        for provider in self._providers:
            if not remaining:
                break
            if not self._allow_provider(provider.name, "quotes", traces):
                continue
            provider_failed = False
            default_batch = 4 if provider.name == "mx_data" else 100
            max_batch = int(getattr(provider, "max_batch_size", default_batch))
            for offset in range(0, len(remaining), max_batch):
                chunk = tuple(remaining[offset : offset + max_batch])
                provider_request = replace(
                    request,
                    symbols=chunk,
                    mode=FetchMode.FRESH_REQUIRED,
                    force_refresh=True,
                )
                try:
                    values = self._call_provider(
                        provider,
                        "quotes",
                        lambda: provider.get_quotes(provider_request),
                        traces,
                        deadline=request.deadline,
                    )
                    quotes.update({item.symbol: item for item in values})
                except ProviderNotFoundError:
                    not_found.update(chunk)
                except _DeadlineExceededError:
                    deadline_exceeded = True
                    break
                except Exception:
                    provider_failed = True
            if deadline_exceeded:
                break
            if provider_failed:
                self._record_provider_failure(provider.name)
            else:
                self._record_provider_success(provider.name)
            remaining = [symbol for symbol in remaining if symbol not in quotes]

        results: dict[str, DataResult[RealtimeQuote]] = {}
        for symbol in symbols:
            key = self._cache_key("quote", {"symbol": symbol})
            quote = quotes.get(symbol)
            if quote is not None:
                result = DataResult(
                    data=quote,
                    data_time=quote.timestamp,
                    cache_info=self._write_cache("quote", key, quote),
                    provider_traces=tuple(traces),
                    request_hash=request_hash,
                )
            else:
                if deadline_exceeded:
                    error_code = "DEADLINE_EXCEEDED"
                else:
                    error_code = "NOT_FOUND" if symbol in not_found else "DATA_UNAVAILABLE"
                    self._write_negative("quote", key, error_code)
                result = DataResult(
                    data=None,
                    data_time=None,
                    cache_info=CacheInfo(state=CacheState.NEGATIVE, cache_key=key),
                    provider_traces=tuple(traces),
                    request_hash=request_hash,
                    error_code=error_code,
                )
            results[symbol] = result
        return results

    def _load_one(
        self,
        data_type: str,
        request: Any,
        method_name: str,
        key: str,
        request_hash: str,
    ) -> DataResult[Any]:
        traces: list[ProviderTrace] = []
        not_found = False
        for provider in self._providers:
            if not self._allow_provider(provider.name, method_name, traces):
                continue
            try:
                method = getattr(provider, method_name)
                value = self._call_provider(
                    provider,
                    method_name,
                    lambda: method(request),
                    traces,
                    deadline=getattr(request, "deadline", None),
                )
                if isinstance(value, TradingCalendar) and self._calendar is not None:
                    update = getattr(self._calendar, "update", None)
                    if callable(update):
                        update(value)
                self._record_provider_success(provider.name)
                return DataResult(
                    data=value,
                    data_time=_data_time(value, self._clock.now()),
                    cache_info=self._write_cache(data_type, key, value),
                    provider_traces=tuple(traces),
                    request_hash=request_hash,
                )
            except NotImplementedError:
                continue
            except _DeadlineExceededError:
                return self._deadline_result(request_hash, tuple(traces))
            except ProviderNotFoundError:
                not_found = True
            except Exception:
                self._record_provider_failure(provider.name)

        error_code = "NOT_FOUND" if not_found else "DATA_UNAVAILABLE"
        self._write_negative(data_type, key, error_code)
        return DataResult(
            data=None,
            data_time=None,
            cache_info=CacheInfo(state=CacheState.NEGATIVE, cache_key=key),
            provider_traces=tuple(traces),
            request_hash=request_hash,
            error_code=error_code,
        )

    def _call_provider(
        self,
        provider: MarketDataProvider,
        operation: str,
        call: Callable[[], Any],
        traces: list[ProviderTrace],
        *,
        deadline: datetime | None,
    ) -> Any:
        for attempt in range(1, self._retry_count + 2):
            if self._deadline_exceeded(deadline):
                raise _DeadlineExceededError
            started = self._clock.now()
            try:
                value = call()
                traces.append(
                    ProviderTrace(
                        provider=provider.name,
                        operation=operation,
                        outcome=TraceOutcome.SUCCESS,
                        started_at=started,
                        finished_at=self._clock.now(),
                        attempt=attempt,
                    )
                )
                return value
            except ProviderNotFoundError as exc:
                traces.append(self._failure_trace(provider.name, operation, started, attempt, exc))
                raise
            except NotImplementedError as exc:
                traces.append(
                    ProviderTrace(
                        provider=provider.name,
                        operation=operation,
                        outcome=TraceOutcome.SKIPPED,
                        started_at=started,
                        finished_at=self._clock.now(),
                        attempt=attempt,
                        error_code="NOT_SUPPORTED",
                        detail=type(exc).__name__,
                    )
                )
                raise
            except Exception as exc:
                traces.append(self._failure_trace(provider.name, operation, started, attempt, exc))
                if attempt > self._retry_count or not _is_transient(exc):
                    raise
                self._sleeper(0.05 * (2 ** (attempt - 1)) + 0.05 * self._jitter())
        raise AssertionError("retry loop exhausted")

    def _failure_trace(
        self,
        provider: str,
        operation: str,
        started: datetime,
        attempt: int,
        exc: Exception,
    ) -> ProviderTrace:
        return ProviderTrace(
            provider=provider,
            operation=operation,
            outcome=TraceOutcome.FAILURE,
            started_at=started,
            finished_at=self._clock.now(),
            attempt=attempt,
            error_code=getattr(exc, "error_code", type(exc).__name__.upper()),
            detail=type(exc).__name__,
        )

    def _read_cached(
        self,
        data_type: str,
        key: str,
        request_hash: str,
    ) -> tuple[DataResult[Any] | None, DataResult[Any] | None]:
        lookup = self._cache.lookup(key)
        record = lookup.record
        if record is None:
            return None, None
        if record.schema_version != SCHEMA_VERSIONS[data_type]:
            self._cache.delete(key)
            return None, None
        now = self._clock.now()
        metadata = dict(record.metadata)
        settling_refresh = (
            self._market_phase() == "post_close_settling"
            and metadata.get("market_phase") != "post_close_settling"
        )
        if record.negative:
            state = CacheState.NEGATIVE
            data = None
        else:
            state = CacheState.FRESH if now <= record.expires_at else CacheState.STALE
            try:
                data = decode_payload(data_type, record.payload)
            except (ValueError, TypeError, json.JSONDecodeError, OSError):
                self._cache.delete(key)
                return None, None
        if settling_refresh and state is CacheState.FRESH:
            state = CacheState.STALE
        warnings = ()
        if state is CacheState.STALE:
            warnings = (DataWarning(code="STALE_CACHE", message="返回允许范围内的过期缓存"),)
        result = DataResult(
            data=data,
            data_time=_data_time(data, record.created_at) if data is not None else None,
            cache_info=CacheInfo(
                state=state,
                tier=lookup.tier,
                cache_key=key,
                cached_at=record.created_at,
                expires_at=record.expires_at,
                stale_until=record.stale_until,
                schema_version=record.schema_version,
            ),
            warnings=warnings,
            request_hash=request_hash,
            error_code=record.error_code if record.negative else None,
        )
        return result, result if state is CacheState.STALE and not record.negative else None

    def _write_cache(self, data_type: str, key: str, value: Any) -> CacheInfo:
        now = self._clock.now()
        policy = self._policies[data_type]
        ttl = self._ttl_for_phase(data_type, policy.ttl_seconds)
        phase = self._market_phase()
        record = CacheRecord(
            key=key,
            data_type=data_type,
            payload=encode_payload(value),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            stale_until=now + timedelta(seconds=ttl + policy.stale_if_error_seconds),
            schema_version=SCHEMA_VERSIONS[data_type],
            metadata=(("market_phase", phase),),
        )
        self._cache.set(record)
        return CacheInfo(
            state=CacheState.FRESH,
            tier=CacheTier.UPSTREAM,
            cache_key=key,
            cached_at=record.created_at,
            expires_at=record.expires_at,
            stale_until=record.stale_until,
            schema_version=record.schema_version,
        )

    def _write_negative(self, data_type: str, key: str, error_code: str) -> None:
        now = self._clock.now()
        ttl = 300 if error_code == "NOT_FOUND" else 10
        self._cache.set(
            CacheRecord(
                key=key,
                data_type=data_type,
                payload=b"",
                created_at=now,
                expires_at=now + timedelta(seconds=ttl),
                stale_until=now + timedelta(seconds=ttl),
                schema_version=SCHEMA_VERSIONS[data_type],
                negative=True,
                error_code=error_code,
            )
        )

    def _ttl_for_phase(self, data_type: str, trading_ttl: int) -> int:
        if self._calendar is None or data_type not in {"quote", "historical", "fund_flow"}:
            return trading_ttl
        phase = self._market_phase()
        if phase == "trading":
            return trading_ttl
        next_open = self._calendar.next_open("XSHG", self._clock.now())
        if next_open is None:
            return trading_ttl
        return max(trading_ttl, int((next_open - self._clock.now()).total_seconds()))

    def _market_phase(self) -> str:
        if self._calendar is None:
            return "trading"
        return self._calendar.market_phase("XSHG", self._clock.now())

    def _allow_provider(
        self,
        provider: str,
        operation: str,
        traces: list[ProviderTrace],
    ) -> bool:
        with self._circuit_lock:
            state = self._circuit_state(provider)
            now = self._clock.now()
            if state.open_until is None:
                return True
            if now < state.open_until:
                traces.append(
                    ProviderTrace(
                        provider=provider,
                        operation=operation,
                        outcome=TraceOutcome.CIRCUIT_OPEN,
                        started_at=now,
                        finished_at=now,
                        error_code="CIRCUIT_OPEN",
                    )
                )
                return False
            if state.half_open_inflight:
                return False
            state.half_open_inflight = True
            return True

    def _record_provider_success(self, provider: str) -> None:
        with self._circuit_lock:
            self._circuits[provider] = _CircuitState()
            self._cache.set_provider_health(
                ProviderHealthRecord(
                    provider=provider,
                    last_success_at=self._clock.now(),
                )
            )

    def _record_provider_failure(self, provider: str) -> None:
        with self._circuit_lock:
            state = self._circuit_state(provider)
            state.failures += 1
            state.half_open_inflight = False
            if state.failures >= self._circuit_threshold:
                state.open_until = self._clock.now() + timedelta(seconds=self._circuit_seconds)
            self._cache.set_provider_health(
                ProviderHealthRecord(
                    provider=provider,
                    consecutive_failures=state.failures,
                    circuit_open_until=state.open_until,
                    last_failure_at=self._clock.now(),
                    last_error_code="UPSTREAM_FAILURE",
                )
            )

    def _circuit_state(self, provider: str) -> _CircuitState:
        state = self._circuits.get(provider)
        if state is not None:
            return state
        persisted = self._cache.get_provider_health(provider)
        state = _CircuitState(
            failures=persisted.consecutive_failures if persisted else 0,
            open_until=persisted.circuit_open_until if persisted else None,
        )
        self._circuits[provider] = state
        return state

    def _single_flight(self, key: str, loader: Callable[[], Any]) -> Any:
        with self._flight_lock:
            future = self._flights.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._flights[key] = future
        assert future is not None
        if not owner:
            return future.result()
        try:
            value = loader()
            future.set_result(value)
            return value
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._flight_lock:
                self._flights.pop(key, None)

    def _schedule_quotes(self, symbols: tuple[str, ...], request: QuoteRequest) -> None:
        if self._executor is None:
            return
        refresh = replace(
            request,
            symbols=symbols,
            mode=FetchMode.FRESH_REQUIRED,
            force_refresh=True,
        )
        self._executor.submit(self.get_quotes, refresh)

    def _schedule_one(self, data_type: str, request: Any, method_name: str) -> None:
        if self._executor is None:
            return
        refresh = replace(request, mode=FetchMode.FRESH_REQUIRED, force_refresh=True)
        self._executor.submit(self._get_one, data_type, refresh, method_name)

    @staticmethod
    def _stale_if_error(
        stale: DataResult[Any] | None,
        loaded: DataResult[Any],
    ) -> DataResult[Any]:
        if loaded.succeeded or stale is None:
            return loaded
        return replace(
            stale,
            provider_traces=loaded.provider_traces,
            warnings=stale.warnings
            + (
                DataWarning(
                    code="STALE_IF_ERROR",
                    message="上游失败，返回 stale-if-error 数据",
                ),
            ),
        )

    @staticmethod
    def _cache_miss(request_hash: str) -> DataResult[Any]:
        return DataResult(
            data=None,
            data_time=None,
            request_hash=request_hash,
            error_code="CACHE_MISS",
        )

    @staticmethod
    def _deadline_result(
        request_hash: str,
        traces: tuple[ProviderTrace, ...] = (),
    ) -> DataResult[Any]:
        return DataResult(
            data=None,
            data_time=None,
            provider_traces=traces,
            request_hash=request_hash,
            error_code="DEADLINE_EXCEEDED",
        )

    def _deadline_exceeded(self, deadline: datetime | None) -> bool:
        return deadline is not None and self._clock.now() >= deadline

    @staticmethod
    def _cache_key(data_type: str, dimensions: Mapping[str, Any]) -> str:
        schema = SCHEMA_VERSIONS[data_type]
        return f"{schema}:{data_type}:{_hash_payload(dimensions)}"


def _cache_dimensions(request: Any) -> dict[str, Any]:
    dimensions = asdict(request)
    for key in ("mode", "force_refresh", "deadline"):
        dimensions.pop(key, None)
    return dimensions


def _hash_payload(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _data_time(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, RealtimeQuote):
        return value.timestamp
    raw_date = None
    if isinstance(value, HistoricalSeries) and value.bars:
        raw_date = value.bars[-1].trading_date
    elif isinstance(value, Financials):
        raw_date = value.report_date
    elif isinstance(value, FundFlow):
        raw_date = value.date
    if raw_date is not None:
        return datetime.combine(raw_date, datetime_time.min, tzinfo=fallback.tzinfo)
    return fallback


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, (ProviderTransientError, TimeoutError, ConnectionError, OSError))
