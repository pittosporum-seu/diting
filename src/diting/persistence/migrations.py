"""Versioned, transactional migrations for durable and disposable SQLite stores."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..infra.errors import MigrationError


@dataclass(frozen=True)
class MigrationStep:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\n".join(self.statements).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class DatabaseMigrationReport:
    database: Path
    target_version: int
    applied_versions: tuple[int, ...]
    backup_path: Path | None
    backup_sha256: str | None
    ready: bool


_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


BUSINESS_MIGRATIONS = (
    MigrationStep(
        version=1,
        name="v080_business_foundation",
        statements=(
            """CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                market TEXT NOT NULL DEFAULT 'sz',
                tags TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code, user_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)",
            """CREATE TABLE IF NOT EXISTS preferences (
                owner_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(owner_id, key)
            )""",
            """CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                dedupe_key TEXT,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                request_json TEXT NOT NULL,
                result_ref TEXT,
                error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                deadline_at TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe "
            "ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL",
            """CREATE TABLE IF NOT EXISTS data_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                completeness REAL NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                profile TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                analysis_score REAL,
                confidence REAL,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS engine_runs (
                run_id TEXT NOT NULL,
                engine_name TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                status TEXT NOT NULL,
                deterministic INTEGER NOT NULL,
                score REAL,
                confidence REAL,
                result_json TEXT,
                error_code TEXT,
                error_detail TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                PRIMARY KEY(run_id, engine_name),
                FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id)
            )""",
            """CREATE TABLE IF NOT EXISTS strategies (
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                state TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                activated_at TEXT,
                PRIMARY KEY(name, version)
            )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_strategy "
            "ON strategies(name) WHERE state = 'active'",
            """CREATE TABLE IF NOT EXISTS experiment_manifests (
                manifest_hash TEXT PRIMARY KEY,
                strategy_name TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS audit_log (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                request_id TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )""",
        ),
    ),
    MigrationStep(
        version=2,
        name="v080_analysis_run_contract",
        statements=(
            "ALTER TABLE analysis_runs ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE analysis_runs ADD COLUMN snapshot_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE analysis_runs ADD COLUMN consensus_json TEXT",
            "ALTER TABLE analysis_runs ADD COLUMN verdict_json TEXT",
            "ALTER TABLE analysis_runs ADD COLUMN code_version TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE analysis_runs ADD COLUMN started_at TEXT",
            "ALTER TABLE engine_runs ADD COLUMN prompt_version TEXT",
            "ALTER TABLE engine_runs ADD COLUMN model TEXT",
            "ALTER TABLE engine_runs ADD COLUMN duration_ms INTEGER NOT NULL DEFAULT 0",
            """CREATE TABLE IF NOT EXISTS scan_results (
                scan_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
        ),
    ),
    MigrationStep(
        version=3,
        name="v080_active_job_deduplication",
        statements=(
            "DROP INDEX IF EXISTS idx_jobs_dedupe",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_dedupe
               ON jobs(dedupe_key)
               WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running')""",
        ),
    ),
    MigrationStep(
        version=4,
        name="v080_owner_sessions",
        statements=(
            """CREATE TABLE IF NOT EXISTS owner_sessions (
                session_id TEXT PRIMARY KEY,
                csrf_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_owner_sessions_expiry ON owner_sessions(expires_at)",
        ),
    ),
    MigrationStep(
        version=5,
        name="v080_scan_strategy_index",
        statements=(
            "ALTER TABLE scan_results ADD COLUMN strategy_version TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE scan_results ADD COLUMN data_date TEXT",
            "CREATE INDEX IF NOT EXISTS idx_scan_results_strategy_date "
            "ON scan_results(strategy_version, data_date, created_at)",
        ),
    ),
)


CACHE_MIGRATIONS = (
    MigrationStep(
        version=1,
        name="v080_cache_foundation",
        statements=(
            """CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                data_type TEXT NOT NULL,
                payload BLOB NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                stale_until TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                negative INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )""",
            "CREATE INDEX IF NOT EXISTS idx_cache_entries_type ON cache_entries(data_type)",
            "CREATE INDEX IF NOT EXISTS idx_cache_entries_stale ON cache_entries(stale_until)",
            """CREATE TABLE IF NOT EXISTS provider_health (
                provider TEXT PRIMARY KEY,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                circuit_open_until TEXT,
                last_failure_at TEXT,
                last_success_at TEXT,
                last_error_code TEXT
            )""",
        ),
    ),
)


class SQLiteMigrator:
    def __init__(
        self,
        database: Path | str,
        migrations: tuple[MigrationStep, ...],
        *,
        backup_dir: Path | str | None = None,
    ) -> None:
        self.database = Path(database)
        self.migrations = tuple(sorted(migrations, key=lambda item: item.version))
        self.backup_dir = Path(backup_dir) if backup_dir else self.database.parent / "backups"

    @property
    def target_version(self) -> int:
        return self.migrations[-1].version if self.migrations else 0

    def _existing_versions(self) -> dict[int, str]:
        if not self.database.exists():
            return {}
        try:
            with sqlite3.connect(self.database) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                if table is None:
                    return {}
                rows = connection.execute(
                    "SELECT version, checksum FROM schema_migrations"
                ).fetchall()
                return {int(version): str(checksum) for version, checksum in rows}
        except sqlite3.DatabaseError as exc:
            raise MigrationError(str(self.database), f"无法读取现有 schema: {exc}") from exc

    def _backup(self) -> tuple[Path | None, str | None]:
        if not self.database.exists() or self.database.stat().st_size == 0:
            return None, None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.backup_dir / f"{self.database.name}.pre-v080.{timestamp}.bak"
        shutil.copy2(self.database, backup_path)
        original_hash = _sha256(self.database)
        backup_hash = _sha256(backup_path)
        if backup_hash != original_hash:
            backup_path.unlink(missing_ok=True)
            raise MigrationError(str(self.database), "数据库备份 SHA256 校验失败")
        backup_path.with_suffix(backup_path.suffix + ".sha256").write_text(
            f"{backup_hash}  {backup_path.name}\n",
            encoding="utf-8",
        )
        return backup_path, backup_hash

    def migrate(self) -> DatabaseMigrationReport:
        existing = self._existing_versions()
        pending = [item for item in self.migrations if item.version not in existing]
        for step in self.migrations:
            recorded = existing.get(step.version)
            if recorded is not None and recorded != step.checksum:
                raise MigrationError(
                    str(self.database),
                    f"迁移 {step.version} checksum 与已应用记录不一致",
                )

        backup_path = None
        backup_sha256 = None
        if pending and not existing:
            backup_path, backup_sha256 = self._backup()

        self.database.parent.mkdir(parents=True, exist_ok=True)
        applied: list[int] = []
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(_MIGRATION_TABLE)
            for step in pending:
                for statement in step.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
                    "VALUES(?,?,?,?)",
                    (step.version, step.name, step.checksum, datetime.now(UTC).isoformat()),
                )
                applied.append(step.version)
            connection.commit()
        except (OSError, sqlite3.DatabaseError) as exc:
            connection.rollback()
            raise MigrationError(str(self.database), str(exc)) from exc
        finally:
            connection.close()

        return DatabaseMigrationReport(
            database=self.database,
            target_version=self.target_version,
            applied_versions=tuple(applied),
            backup_path=backup_path,
            backup_sha256=backup_sha256,
            ready=self.is_ready(),
        )

    def is_ready(self) -> bool:
        if not self.database.exists():
            return False
        try:
            versions = self._existing_versions()
            if any(versions.get(step.version) != step.checksum for step in self.migrations):
                return False
            with sqlite3.connect(self.database) as connection:
                return connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        except (MigrationError, sqlite3.DatabaseError):
            return False


def migrate_databases(
    business_path: Path | str,
    cache_path: Path | str,
    *,
    backup_dir: Path | str | None = None,
) -> tuple[DatabaseMigrationReport, DatabaseMigrationReport]:
    """Migrate the durable database first, then the disposable cache database."""

    business = SQLiteMigrator(
        business_path,
        BUSINESS_MIGRATIONS,
        backup_dir=backup_dir,
    ).migrate()
    cache = SQLiteMigrator(
        cache_path,
        CACHE_MIGRATIONS,
        backup_dir=backup_dir,
    ).migrate()
    return business, cache


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
