"""Active-strategy-only opportunity scanner over the unified Data Gateway."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

from ..enums import FactorFamily, FetchMode, RunStatus
from ..ports import CacheStore, Clock, DataGateway, DurableStore
from ..schema import (
    CacheRecord,
    DataWarning,
    HistoricalBar,
    HistoricalRequest,
    Instrument,
    InstrumentSearchRequest,
    RankingStrategyDefinition,
    ScanItem,
    ScanResult,
    StrategyVersion,
    TradingCalendarRequest,
)


class ActiveStrategyScanOrchestrator:
    """Rank a point-in-time universe only with a validated active definition."""

    def __init__(
        self,
        gateway: DataGateway,
        store: DurableStore,
        cache: CacheStore,
        clock: Clock,
        *,
        selected_strategy: str,
        config_hash: str,
        minimum_universe: int = 500,
        minimum_coverage: float = 0.90,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._cache = cache
        self._clock = clock
        self._selected_strategy = selected_strategy
        self._config_hash = config_hash
        self._minimum_universe = minimum_universe
        self._minimum_coverage = minimum_coverage

    def scan(
        self,
        *,
        limit: int = 20,
        progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ScanResult:
        report_progress = progress or (lambda _value: None)
        is_cancelled = cancelled or (lambda: False)
        if limit < 1:
            return self._failure("INVALID_SCAN_LIMIT")
        active = self._store.get_active_strategy(self._selected_strategy)
        if active is None:
            return self._failure("NO_ACTIVE_STRATEGY")
        definition = active.definition
        manifest = self._store.get_experiment_manifest(active.manifest_hash)
        if (
            definition is None
            or manifest is None
            or manifest.strategy_name != active.name
            or manifest.strategy_version != active.version
        ):
            return self._failure(
                "STRATEGY_EVIDENCE_UNAVAILABLE",
                strategy=active,
            )

        data_date = self._latest_trading_date()
        if data_date is None:
            return self._failure("TRADING_CALENDAR_UNAVAILABLE", strategy=active)
        cache_key = self._scan_cache_key(active, definition, data_date)
        cached = self._cached_result(cache_key)
        if cached is not None:
            report_progress(1.0)
            return _limited(cached, limit)

        instruments = self._instruments(data_date)
        if len(instruments) < self._minimum_universe:
            return self._failure(
                "SCAN_UNIVERSE_INSUFFICIENT",
                strategy=active,
                data_date=data_date,
            )
        report_progress(0.15)
        factor_values: dict[str, dict[str, float]] = {}
        by_symbol = {instrument.symbol: instrument for instrument in instruments}
        adjustment = {"qfq": "forward", "hfq": "backward", "none": "none"}.get(
            manifest.adjustment_method,
            manifest.adjustment_method,
        )
        for index, instrument in enumerate(instruments, start=1):
            if is_cancelled():
                return self._failure("SCAN_CANCELLED", strategy=active, data_date=data_date)
            historical = self._gateway.get_historical(
                HistoricalRequest(
                    symbol=instrument.symbol,
                    start_date=data_date - timedelta(days=120),
                    end_date=data_date,
                    adjustment=adjustment,
                    mode=FetchMode.FRESH_REQUIRED,
                )
            )
            if historical.data is None:
                continue
            values = _factor_values(historical.data.bars, definition)
            if values is not None:
                factor_values[instrument.symbol] = values
            report_progress(0.15 + 0.75 * index / len(instruments))

        coverage = len(factor_values) / len(instruments)
        if len(factor_values) < self._minimum_universe or coverage < self._minimum_coverage:
            return self._failure(
                "SCAN_DATA_COVERAGE_INSUFFICIENT",
                strategy=active,
                data_date=data_date,
            )

        ranked = _rank(factor_values, definition)
        strategy_version = f"{active.name}:{active.version}"
        selected = sorted(ranked.items(), key=lambda item: (-item[1][0], item[0]))[
            : definition.top_n
        ]
        items = tuple(
            ScanItem(
                symbol=symbol,
                name=by_symbol[symbol].name,
                rank=index,
                score=round(score * 100, 4),
                strategy_version=strategy_version,
                data_date=data_date,
                evidence=evidence,
            )
            for index, (symbol, (score, evidence)) in enumerate(selected, start=1)
        )
        warnings = ()
        if coverage < 1:
            warnings = (
                DataWarning(
                    code="PARTIAL_DATA_COVERAGE",
                    message=f"factor coverage {coverage:.1%}",
                    recoverable=True,
                ),
            )
        result = ScanResult(
            scan_id=f"scan_{uuid4().hex}",
            status=RunStatus.SUCCEEDED,
            strategy_version=strategy_version,
            data_date=data_date,
            items=items,
            warnings=warnings,
            manifest_hash=active.manifest_hash,
            factor_version=definition.factor_version,
            config_hash=self._config_hash,
            cache_key=cache_key,
        )
        self._store.save_scan_result(result)
        self._cache_result(result)
        report_progress(1.0)
        return _limited(result, limit)

    def _latest_trading_date(self) -> date | None:
        today = self._clock.today()
        result = self._gateway.get_trading_calendar(
            TradingCalendarRequest(
                market="SH",
                start_date=today - timedelta(days=14),
                end_date=today,
                mode=FetchMode.FRESH_REQUIRED,
            )
        )
        if result.data is None:
            return None
        dates = [
            session.trading_date
            for session in result.data.sessions
            if session.is_open and session.trading_date <= today
        ]
        return max(dates) if dates else None

    def _instruments(self, data_date: date) -> tuple[Instrument, ...]:
        items: dict[str, Instrument] = {}
        cursor = None
        seen_cursors: set[str] = set()
        for _page in range(100):
            result = self._gateway.search_instruments(
                InstrumentSearchRequest(
                    query="",
                    limit=1000,
                    cursor=cursor,
                    mode=FetchMode.FRESH_REQUIRED,
                )
            )
            if result.data is None:
                return ()
            for instrument in result.data.items:
                if (
                    instrument.instrument_type.lower() == "stock"
                    and (instrument.listed_on is None or instrument.listed_on <= data_date)
                    and (instrument.delisted_on is None or instrument.delisted_on >= data_date)
                ):
                    items[instrument.symbol] = instrument
            next_cursor = result.data.next_cursor
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                return ()
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return tuple(items[symbol] for symbol in sorted(items))

    def _scan_cache_key(
        self,
        strategy: StrategyVersion,
        definition: RankingStrategyDefinition,
        data_date: date,
    ) -> str:
        dimensions = {
            "strategy": strategy.name,
            "strategy_version": strategy.version,
            "manifest_hash": strategy.manifest_hash,
            "factor_version": definition.factor_version,
            "data_date": data_date.isoformat(),
            "config_hash": self._config_hash,
        }
        digest = hashlib.sha256(
            json.dumps(dimensions, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"scan:v1:{digest}"

    def _cached_result(self, cache_key: str) -> ScanResult | None:
        lookup = self._cache.lookup(cache_key)
        if lookup.record is None:
            return None
        scan_id = lookup.record.payload.decode(errors="ignore")
        result = self._store.get_scan_result(scan_id)
        if result is None or result.cache_key != cache_key:
            self._cache.delete(cache_key)
            return None
        return result

    def _cache_result(self, result: ScanResult) -> None:
        assert result.cache_key is not None
        assert result.strategy_version is not None
        assert result.data_date is not None
        now = self._clock.now()
        self._cache.set(
            CacheRecord(
                key=result.cache_key,
                data_type="scan_result",
                payload=result.scan_id.encode(),
                created_at=now,
                expires_at=now + timedelta(minutes=5),
                stale_until=now + timedelta(days=3),
                schema_version="scan-v1",
                metadata=(
                    ("config_hash", result.config_hash or ""),
                    ("data_date", result.data_date.isoformat()),
                    ("factor_version", result.factor_version or ""),
                    ("manifest_hash", result.manifest_hash or ""),
                    ("strategy_version", result.strategy_version),
                ),
            )
        )

    def _failure(
        self,
        error_code: str,
        *,
        strategy: StrategyVersion | None = None,
        data_date: date | None = None,
    ) -> ScanResult:
        return ScanResult(
            scan_id=f"scan_{uuid4().hex}",
            status=RunStatus.FAILED,
            strategy_version=(f"{strategy.name}:{strategy.version}" if strategy else None),
            data_date=data_date or self._clock.today(),
            warnings=(
                DataWarning(
                    code=error_code,
                    message=error_code.replace("_", " ").lower(),
                    recoverable=True,
                ),
            ),
            error_code=error_code,
            manifest_hash=strategy.manifest_hash if strategy else None,
            factor_version=(
                strategy.definition.factor_version
                if strategy is not None and strategy.definition is not None
                else None
            ),
            config_hash=self._config_hash,
        )


def _factor_values(
    bars: tuple[HistoricalBar, ...],
    definition: RankingStrategyDefinition,
) -> dict[str, float] | None:
    ordered = sorted(bars, key=lambda bar: bar.trading_date)
    if len(ordered) < 21:
        return None
    closes = [bar.close for bar in ordered]
    volumes = [bar.volume for bar in ordered]
    if any(value <= 0 or not math.isfinite(value) for value in closes):
        return None
    returns = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    ma20 = statistics.fmean(closes[-20:])
    std20 = statistics.pstdev(closes[-20:])
    mean_volume = statistics.fmean(volumes[-20:])
    available = {
        FactorFamily.PRICE_VS_MA.value: closes[-1] / ma20 - 1,
        FactorFamily.RETURN.value: closes[-1] / closes[-21] - 1,
        FactorFamily.VOLATILITY.value: statistics.pstdev(returns[-20:]),
        FactorFamily.RSI.value: _rsi(closes),
        FactorFamily.VOLUME_RATIO.value: volumes[-1] / mean_volume if mean_volume > 0 else math.nan,
        FactorFamily.BOLLINGER.value: (closes[-1] - ma20) / (2 * std20) if std20 else 0.0,
    }
    selected = {factor.name: available[factor.name] for factor in definition.factors}
    return selected if all(math.isfinite(value) for value in selected.values()) else None


def _limited(result: ScanResult, limit: int) -> ScanResult:
    return replace(result, items=result.items[:limit])


def _rsi(closes: list[float], period: int = 14) -> float:
    deltas = [closes[index] - closes[index - 1] for index in range(1, len(closes))][-period:]
    gain = statistics.fmean(max(delta, 0) for delta in deltas)
    loss = statistics.fmean(max(-delta, 0) for delta in deltas)
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def _rank(
    values: dict[str, dict[str, float]],
    definition: RankingStrategyDefinition,
) -> dict[str, tuple[float, tuple[str, ...]]]:
    factor_ranks: dict[str, dict[str, float]] = {}
    for factor in definition.factors:
        ordered = sorted((row[factor.name], symbol) for symbol, row in values.items())
        ranks: dict[str, float] = {}
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and ordered[end][0] == ordered[index][0]:
                end += 1
            percentile = ((index + end - 1) / 2) / max(1, len(ordered) - 1)
            for _, symbol in ordered[index:end]:
                ranks[symbol] = percentile if factor.direction > 0 else 1 - percentile
            index = end
        factor_ranks[factor.name] = ranks

    output = {}
    for symbol, row in values.items():
        score = sum(
            factor.weight * factor_ranks[factor.name][symbol] for factor in definition.factors
        )
        evidence = tuple(
            f"{factor.name}={row[factor.name]:.6g};rank={factor_ranks[factor.name][symbol]:.4f};weight={factor.weight:.4f}"
            for factor in definition.factors
        )
        output[symbol] = (score, evidence)
    return output
