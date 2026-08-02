"""Transactional dual-database migration tests."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.diting.infra.errors import MigrationError
from src.diting.persistence.migrations import (
    BUSINESS_MIGRATIONS,
    CACHE_MIGRATIONS,
    MigrationStep,
    SQLiteMigrator,
    migrate_databases,
)


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def test_empty_databases_migrate_and_are_ready(tmp_path: Path) -> None:
    business_path = tmp_path / "diting.db"
    cache_path = tmp_path / "diting_cache.db"

    business, cache = migrate_databases(business_path, cache_path)

    assert business.applied_versions == (1, 2, 3)
    assert cache.applied_versions == (1,)
    assert business.ready is True
    assert cache.ready is True
    assert {"analysis_runs", "engine_runs", "strategies", "scan_results"} <= _tables(business_path)
    assert {"cache_entries", "provider_health"} <= _tables(cache_path)


def test_existing_database_is_backed_up_and_verified(tmp_path: Path) -> None:
    database = tmp_path / "diting.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
        connection.execute("INSERT INTO legacy VALUES('preserved')")

    report = SQLiteMigrator(
        database,
        BUSINESS_MIGRATIONS,
        backup_dir=tmp_path / "archive",
    ).migrate()

    assert report.backup_path is not None
    assert report.backup_path.exists()
    expected_hash = hashlib.sha256(report.backup_path.read_bytes()).hexdigest()
    assert report.backup_sha256 == expected_hash
    assert report.backup_path.with_suffix(report.backup_path.suffix + ".sha256").exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM legacy").fetchone() == ("preserved",)


def test_repeated_migration_is_idempotent_without_second_backup(tmp_path: Path) -> None:
    database = tmp_path / "diting_cache.db"
    migrator = SQLiteMigrator(database, CACHE_MIGRATIONS)
    first = migrator.migrate()
    second = migrator.migrate()

    assert first.applied_versions == (1,)
    assert second.applied_versions == ()
    assert second.backup_path is None
    assert second.ready is True


def test_failed_migration_rolls_back_version_and_readiness(tmp_path: Path) -> None:
    database = tmp_path / "broken.db"
    migrations = (
        MigrationStep(
            version=1,
            name="broken",
            statements=("CREATE TABLE should_rollback(value TEXT)", "INVALID SQL"),
        ),
    )
    migrator = SQLiteMigrator(database, migrations)

    with pytest.raises(MigrationError):
        migrator.migrate()

    assert migrator.is_ready() is False
    if database.exists():
        assert "should_rollback" not in _tables(database)
