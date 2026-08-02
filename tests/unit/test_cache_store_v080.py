"""v0.8 L1/L2 cache-store tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.diting.cache.store_v080 import MemoryCacheStore, SQLiteCacheStore, TieredCacheStore
from src.diting.enums import CacheTier
from src.diting.persistence.migrations import CACHE_MIGRATIONS, SQLiteMigrator
from src.diting.schema import CacheRecord, ProviderHealthRecord


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def today(self):
        return self.value.date()

    def monotonic(self) -> float:
        return self.value.timestamp()


def _record(clock: MutableClock, key: str, payload: bytes = b"payload") -> CacheRecord:
    return CacheRecord(
        key=key,
        data_type="quote",
        payload=payload,
        created_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=30),
        stale_until=clock.now() + timedelta(days=1),
        schema_version="quote-v1",
    )


def _persistent(tmp_path: Path, clock: MutableClock) -> SQLiteCacheStore:
    database = tmp_path / "diting_cache.db"
    SQLiteMigrator(database, CACHE_MIGRATIONS).migrate()
    return SQLiteCacheStore(database, clock)


def test_tiered_cache_hits_l1_after_write(tmp_path: Path) -> None:
    clock = MutableClock()
    cache = TieredCacheStore(MemoryCacheStore(clock, max_size=2), _persistent(tmp_path, clock))
    cache.set(_record(clock, "quote:002475"))

    lookup = cache.lookup("quote:002475")
    assert lookup.tier is CacheTier.L1
    assert lookup.record is not None
    assert lookup.record.payload == b"payload"


def test_restart_recovers_from_l2_and_promotes_to_l1(tmp_path: Path) -> None:
    clock = MutableClock()
    persistent = _persistent(tmp_path, clock)
    first = TieredCacheStore(MemoryCacheStore(clock), persistent)
    first.set(_record(clock, "quote:600519", b"binary\x00payload"))

    restarted = TieredCacheStore(
        MemoryCacheStore(clock), SQLiteCacheStore(persistent._database, clock)
    )
    assert restarted.lookup("quote:600519").tier is CacheTier.L2
    assert restarted.lookup("quote:600519").tier is CacheTier.L1


def test_l1_is_bounded_and_evicts_least_recently_used() -> None:
    clock = MutableClock()
    memory = MemoryCacheStore(clock, max_size=2)
    memory.set(_record(clock, "a"))
    memory.set(_record(clock, "b"))
    assert memory.lookup("a").record is not None
    memory.set(_record(clock, "c"))

    assert memory.lookup("b").record is None
    assert memory.lookup("a").record is not None
    assert memory.lookup("c").record is not None


def test_entries_past_stale_limit_are_removed(tmp_path: Path) -> None:
    clock = MutableClock()
    cache = TieredCacheStore(MemoryCacheStore(clock), _persistent(tmp_path, clock))
    cache.set(_record(clock, "expired"))
    clock.value += timedelta(days=2)

    assert cache.lookup("expired").record is None


def test_prefix_clear_affects_both_tiers(tmp_path: Path) -> None:
    clock = MutableClock()
    cache = TieredCacheStore(MemoryCacheStore(clock), _persistent(tmp_path, clock))
    cache.set(_record(clock, "quote:a"))
    cache.set(_record(clock, "quote:b"))
    cache.set(_record(clock, "history:a"))

    assert cache.clear("quote:") == 2
    assert cache.lookup("quote:a").record is None
    assert cache.lookup("history:a").record is not None


def test_provider_health_survives_process_restart(tmp_path: Path) -> None:
    clock = MutableClock()
    persistent = _persistent(tmp_path, clock)
    cache = TieredCacheStore(MemoryCacheStore(clock), persistent)
    record = ProviderHealthRecord(
        provider="mx_data",
        consecutive_failures=3,
        circuit_open_until=clock.now() + timedelta(seconds=60),
        last_failure_at=clock.now(),
        last_error_code="UPSTREAM_FAILURE",
    )
    cache.set_provider_health(record)

    restarted = TieredCacheStore(
        MemoryCacheStore(clock), SQLiteCacheStore(persistent._database, clock)
    )
    assert restarted.get_provider_health("mx_data") == record
