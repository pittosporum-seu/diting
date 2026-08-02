"""Bounded L1 and SQLite L2 implementations of the v0.8 cache port."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from ..enums import CacheTier
from ..infra.errors import MigrationError
from ..ports import Clock
from ..schema import CacheLookup, CacheRecord, ProviderHealthRecord


class MemoryCacheStore:
    """A thread-safe, bounded process-local LRU cache."""

    def __init__(self, clock: Clock, max_size: int = 512) -> None:
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self._clock = clock
        self._max_size = max_size
        self._records: OrderedDict[str, CacheRecord] = OrderedDict()
        self._provider_health: dict[str, ProviderHealthRecord] = {}
        self._lock = threading.RLock()

    def lookup(self, key: str) -> CacheLookup:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return CacheLookup(record=None)
            if self._clock.now() > record.stale_until:
                del self._records[key]
                return CacheLookup(record=None)
            self._records.move_to_end(key)
            return CacheLookup(record=record, tier=CacheTier.L1)

    def set(self, record: CacheRecord) -> None:
        with self._lock:
            self._records[record.key] = record
            self._records.move_to_end(record.key)
            while len(self._records) > self._max_size:
                self._records.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._records.pop(key, None)

    def clear(self, prefix: str | None = None) -> int:
        with self._lock:
            if prefix is None:
                count = len(self._records)
                self._records.clear()
                return count
            keys = [key for key in self._records if key.startswith(prefix)]
            for key in keys:
                del self._records[key]
            return len(keys)

    def close(self) -> None:
        self.clear()

    def get_provider_health(self, provider: str) -> ProviderHealthRecord | None:
        with self._lock:
            return self._provider_health.get(provider)

    def set_provider_health(self, record: ProviderHealthRecord) -> None:
        with self._lock:
            self._provider_health[record.provider] = record


class SQLiteCacheStore:
    """Persistent L2 cache backed by the migrated ``cache_entries`` table."""

    def __init__(self, database: Path | str, clock: Clock) -> None:
        self._database = Path(database)
        self._clock = clock
        self._lock = threading.RLock()
        if not self._is_migrated():
            raise MigrationError(str(self._database), "cache_entries table is not ready")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _is_migrated(self) -> bool:
        if not self._database.exists():
            return False
        try:
            with sqlite3.connect(self._database) as connection:
                row = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache_entries'"
                ).fetchone()
                return row is not None
        except sqlite3.DatabaseError:
            return False

    def lookup(self, key: str) -> CacheLookup:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT cache_key, data_type, payload, created_at, expires_at, stale_until, "
                "schema_version, negative, error_code, metadata_json "
                "FROM cache_entries WHERE cache_key=?",
                (key,),
            ).fetchone()
            if row is None:
                return CacheLookup(record=None)
            record = _record_from_row(row)
            if self._clock.now() > record.stale_until:
                connection.execute("DELETE FROM cache_entries WHERE cache_key=?", (key,))
                connection.commit()
                return CacheLookup(record=None)
            return CacheLookup(record=record, tier=CacheTier.L2)

    def set(self, record: CacheRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO cache_entries(
                    cache_key, data_type, payload, created_at, expires_at, stale_until,
                    schema_version, negative, error_code, metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    data_type=excluded.data_type,
                    payload=excluded.payload,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    stale_until=excluded.stale_until,
                    schema_version=excluded.schema_version,
                    negative=excluded.negative,
                    error_code=excluded.error_code,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.key,
                    record.data_type,
                    record.payload,
                    record.created_at.isoformat(),
                    record.expires_at.isoformat(),
                    record.stale_until.isoformat(),
                    record.schema_version,
                    int(record.negative),
                    record.error_code,
                    json.dumps(dict(record.metadata), ensure_ascii=False, sort_keys=True),
                ),
            )
            connection.commit()

    def delete(self, key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM cache_entries WHERE cache_key=?", (key,))
            connection.commit()

    def clear(self, prefix: str | None = None) -> int:
        with self._lock, self._connect() as connection:
            if prefix is None:
                cursor = connection.execute("DELETE FROM cache_entries")
            else:
                escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                cursor = connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key LIKE ? ESCAPE '\\'",
                    (escaped + "%",),
                )
            connection.commit()
            return max(cursor.rowcount, 0)

    def close(self) -> None:
        return None

    def get_provider_health(self, provider: str) -> ProviderHealthRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT provider, consecutive_failures, circuit_open_until, "
                "last_failure_at, last_success_at, last_error_code "
                "FROM provider_health WHERE provider=?",
                (provider,),
            ).fetchone()
        if row is None:
            return None
        return ProviderHealthRecord(
            provider=str(row["provider"]),
            consecutive_failures=int(row["consecutive_failures"]),
            circuit_open_until=_optional_datetime(row["circuit_open_until"]),
            last_failure_at=_optional_datetime(row["last_failure_at"]),
            last_success_at=_optional_datetime(row["last_success_at"]),
            last_error_code=(
                str(row["last_error_code"]) if row["last_error_code"] is not None else None
            ),
        )

    def set_provider_health(self, record: ProviderHealthRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO provider_health(
                    provider, consecutive_failures, circuit_open_until,
                    last_failure_at, last_success_at, last_error_code
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(provider) DO UPDATE SET
                    consecutive_failures=excluded.consecutive_failures,
                    circuit_open_until=excluded.circuit_open_until,
                    last_failure_at=excluded.last_failure_at,
                    last_success_at=excluded.last_success_at,
                    last_error_code=excluded.last_error_code
                """,
                (
                    record.provider,
                    record.consecutive_failures,
                    _optional_isoformat(record.circuit_open_until),
                    _optional_isoformat(record.last_failure_at),
                    _optional_isoformat(record.last_success_at),
                    record.last_error_code,
                ),
            )
            connection.commit()


class TieredCacheStore:
    """Read-through L1/L2 cache; every successful write reaches both tiers."""

    def __init__(self, memory: MemoryCacheStore, persistent: SQLiteCacheStore) -> None:
        self._memory = memory
        self._persistent = persistent

    def lookup(self, key: str) -> CacheLookup:
        lookup = self._memory.lookup(key)
        if lookup.record is not None:
            return lookup
        lookup = self._persistent.lookup(key)
        if lookup.record is not None:
            self._memory.set(lookup.record)
        return lookup

    def set(self, record: CacheRecord) -> None:
        self._persistent.set(record)
        self._memory.set(record)

    def delete(self, key: str) -> None:
        self._memory.delete(key)
        self._persistent.delete(key)

    def clear(self, prefix: str | None = None) -> int:
        self._memory.clear(prefix)
        return self._persistent.clear(prefix)

    def close(self) -> None:
        self._memory.close()
        self._persistent.close()

    def get_provider_health(self, provider: str) -> ProviderHealthRecord | None:
        return self._persistent.get_provider_health(provider)

    def set_provider_health(self, record: ProviderHealthRecord) -> None:
        self._persistent.set_provider_health(record)
        self._memory.set_provider_health(record)


def _record_from_row(row: sqlite3.Row) -> CacheRecord:
    return CacheRecord(
        key=str(row["cache_key"]),
        data_type=str(row["data_type"]),
        payload=bytes(row["payload"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        expires_at=datetime.fromisoformat(str(row["expires_at"])),
        stale_until=datetime.fromisoformat(str(row["stale_until"])),
        schema_version=str(row["schema_version"]),
        negative=bool(row["negative"]),
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        metadata=tuple(sorted(json.loads(str(row["metadata_json"])).items())),
    )


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _optional_isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
