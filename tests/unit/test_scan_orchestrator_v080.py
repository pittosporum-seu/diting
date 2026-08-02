"""Active strategy scanning, ranking and cache isolation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.diting.application.scan import ActiveStrategyScanOrchestrator
from src.diting.enums import CacheTier, RunStatus, StrategyState
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.schema import (
    CacheLookup,
    DataResult,
    ExperimentFactor,
    HistoricalBar,
    HistoricalSeries,
    Instrument,
    InstrumentPage,
    RankingStrategyDefinition,
    ScanItem,
    ScanResult,
    StrategyVersion,
    TradingCalendar,
    TradingSession,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
DATA_DATE = date(2026, 7, 31)


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()


class FakeCache:
    def __init__(self) -> None:
        self.records = {}
        self.lookups: list[str] = []

    def lookup(self, key):
        self.lookups.append(key)
        record = self.records.get(key)
        return CacheLookup(record=record, tier=CacheTier.L1 if record else CacheTier.NONE)

    def set(self, record):
        self.records[record.key] = record

    def delete(self, key):
        self.records.pop(key, None)


class FakeStore:
    def __init__(self, active=None) -> None:
        self.active = active
        self.results: dict[str, ScanResult] = {}

    def get_active_strategy(self, _name):
        return self.active

    def get_experiment_manifest(self, _manifest_hash):
        if self.active is None:
            return None
        return SimpleNamespace(
            strategy_name=self.active.name,
            strategy_version=self.active.version,
            adjustment_method="qfq",
        )

    def save_scan_result(self, result):
        self.results[result.scan_id] = result

    def get_scan_result(self, scan_id):
        return self.results.get(scan_id)


class FakeGateway:
    def __init__(self) -> None:
        self.historical_calls = 0
        self.search_calls = 0
        self.instruments = tuple(
            Instrument(f"00000{index}", f"Stock {index}", "SZ", "stock", date(2020, 1, 1))
            for index in range(1, 4)
        )

    def get_trading_calendar(self, _request):
        return DataResult(
            data=TradingCalendar(
                market="SH",
                sessions=(TradingSession(DATA_DATE, "SH", True),),
            ),
            data_time=NOW,
            request_hash="calendar",
        )

    def search_instruments(self, _request):
        self.search_calls += 1
        return DataResult(
            data=InstrumentPage(self.instruments, len(self.instruments)),
            data_time=NOW,
            request_hash="catalog",
        )

    def get_historical(self, request):
        self.historical_calls += 1
        slope = int(request.symbol[-1]) * 0.2
        bars = tuple(
            HistoricalBar(
                DATA_DATE - timedelta(days=29 - index),
                10 + slope * index,
                10.2 + slope * index,
                9.8 + slope * index,
                10 + slope * index,
                1000 + index * int(request.symbol[-1]),
            )
            for index in range(30)
        )
        return DataResult(
            data=HistoricalSeries(request.symbol, bars),
            data_time=NOW,
            request_hash=f"history-{request.symbol}",
        )


def _definition() -> RankingStrategyDefinition:
    return RankingStrategyDefinition(
        factor_version="factor-v1",
        factors=(
            ExperimentFactor(
                "ret",
                "return",
                -1,
                "cross_sectional_rank",
                "exclude_period_asset",
                -0.6,
                0.34,
            ),
            ExperimentFactor(
                "rsi",
                "rsi",
                -1,
                "cross_sectional_rank",
                "exclude_period_asset",
                -0.5,
                0.33,
            ),
            ExperimentFactor(
                "bollinger",
                "bollinger",
                -1,
                "cross_sectional_rank",
                "exclude_period_asset",
                -0.4,
                0.33,
            ),
        ),
    )


def _active() -> StrategyVersion:
    return StrategyVersion(
        name="mean_reversion_v1",
        version="1.0.0",
        state=StrategyState.ACTIVE,
        manifest_hash="a" * 64,
        created_at=NOW,
        activated_at=NOW,
        definition=_definition(),
    )


def _scanner(gateway, store, cache, config_hash="config-a"):
    return ActiveStrategyScanOrchestrator(
        gateway,
        store,
        cache,
        FakeClock(),
        selected_strategy="mean_reversion_v1",
        config_hash=config_hash,
        minimum_universe=3,
    )


def test_no_active_strategy_returns_explicit_empty_failure_without_data_access() -> None:
    gateway = FakeGateway()
    result = _scanner(gateway, FakeStore(), FakeCache()).scan()

    assert result.status is RunStatus.FAILED
    assert result.error_code == "NO_ACTIVE_STRATEGY"
    assert result.items == ()
    assert gateway.search_calls == gateway.historical_calls == 0


def test_active_scan_ranks_typed_history_and_persists_traceable_result() -> None:
    gateway = FakeGateway()
    store = FakeStore(_active())
    cache = FakeCache()

    result = _scanner(gateway, store, cache).scan(limit=2)

    assert result.status is RunStatus.SUCCEEDED
    assert len(result.items) == 2
    assert [item.rank for item in result.items] == [1, 2]
    assert result.strategy_version == "mean_reversion_v1:1.0.0"
    assert result.manifest_hash == "a" * 64
    assert result.factor_version == "factor-v1"
    assert result.data_date == DATA_DATE
    assert result.scan_id in store.results
    assert len(store.results[result.scan_id].items) == 3
    record = cache.records[result.cache_key]
    assert dict(record.metadata) == {
        "config_hash": "config-a",
        "data_date": DATA_DATE.isoformat(),
        "factor_version": "factor-v1",
        "manifest_hash": "a" * 64,
        "strategy_version": "mean_reversion_v1:1.0.0",
    }
    assert all(item.evidence for item in result.items)


def test_active_version_without_bound_manifest_fails_closed() -> None:
    gateway = FakeGateway()
    store = FakeStore(_active())
    store.get_experiment_manifest = lambda _hash: None

    result = _scanner(gateway, store, FakeCache()).scan()

    assert result.error_code == "STRATEGY_EVIDENCE_UNAVAILABLE"
    assert gateway.search_calls == gateway.historical_calls == 0


def test_same_identity_reuses_cache_but_config_change_is_isolated() -> None:
    gateway = FakeGateway()
    store = FakeStore(_active())
    cache = FakeCache()
    first = _scanner(gateway, store, cache, "config-a").scan()
    calls_after_first = gateway.historical_calls
    second = _scanner(gateway, store, cache, "config-a").scan()
    third = _scanner(gateway, store, cache, "config-b").scan()

    assert second == first
    assert gateway.historical_calls == calls_after_first + 3
    assert third.cache_key != first.cache_key


def test_response_limit_does_not_change_cached_strategy_result() -> None:
    gateway = FakeGateway()
    store = FakeStore(_active())
    cache = FakeCache()

    first = _scanner(gateway, store, cache).scan(limit=2)
    calls_after_first = gateway.historical_calls
    second = _scanner(gateway, store, cache).scan(limit=3)

    assert len(first.items) == 2
    assert len(second.items) == 3
    assert second.scan_id == first.scan_id
    assert gateway.historical_calls == calls_after_first


def test_scan_cancellation_stops_before_historical_fanout() -> None:
    gateway = FakeGateway()
    result = _scanner(gateway, FakeStore(_active()), FakeCache()).scan(cancelled=lambda: True)

    assert result.status is RunStatus.FAILED
    assert result.error_code == "SCAN_CANCELLED"
    assert gateway.historical_calls == 0


def test_insufficient_runtime_coverage_produces_no_ranking_or_cache() -> None:
    gateway = FakeGateway()
    original = gateway.get_historical

    def missing_one(request):
        if request.symbol == "000003":
            gateway.historical_calls += 1
            return DataResult(
                data=None,
                data_time=NOW,
                request_hash="missing",
                error_code="DATA_UNAVAILABLE",
            )
        return original(request)

    gateway.get_historical = missing_one
    cache = FakeCache()
    result = _scanner(gateway, FakeStore(_active()), cache).scan()

    assert result.error_code == "SCAN_DATA_COVERAGE_INSUFFICIENT"
    assert result.items == ()
    assert cache.records == {}


def test_scan_result_roundtrips_and_latest_query_is_strategy_isolated(tmp_path: Path) -> None:
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    result = ScanResult(
        scan_id="scan-one",
        status=RunStatus.SUCCEEDED,
        strategy_version="mean_reversion_v1:1.0.0",
        data_date=DATA_DATE,
        items=(
            ScanItem(
                "000001",
                "Stock 1",
                1,
                88.5,
                "mean_reversion_v1:1.0.0",
                DATA_DATE,
                ("ret=0.1",),
            ),
        ),
        manifest_hash="a" * 64,
        factor_version="factor-v1",
        config_hash="config-a",
        cache_key="scan:v1:key",
    )

    store.save_scan_result(result)

    assert store.get_scan_result("scan-one") == result
    assert store.get_latest_scan_result("mean_reversion_v1:1.0.0") == result
    assert store.get_latest_scan_result("mean_reversion_v1:2.0.0") is None
