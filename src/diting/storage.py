"""谛听 · 自选股数据库 — SQLite 持久化，线程安全"""

from __future__ import annotations

import csv
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .infra.logging_config import get_logger

# 注册 datetime 适配器，消除 Python 3.12+ 弃用警告
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat(" "))

logger = get_logger(__name__)

_DEFAULT_DB_DIR = Path.home() / ".diting"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "diting.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    market     TEXT NOT NULL DEFAULT 'sz',
    tags       TEXT NOT NULL DEFAULT '',
    user_id    TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, user_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    user_id    TEXT NOT NULL DEFAULT 'default',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class WatchlistDB:
    """自选股数据库。自动建表，线程安全（connection-per-operation）。

    用法:
        db = WatchlistDB()                     # 默认 ~/.diting/diting.db
        db.add("002475", "立讯精密", "sz")      # 添加自选股
        db.list()                               # → [{"code":"002475",...},...]
        db.remove("002475")                     # 删除
        db.has("002475")                        # → True
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self._path = Path(db_path)
        else:
            self._path = _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._ensure_db()

    # ── 公开接口 ──────────────────────────────────

    def list(self, user_id: str = "default") -> list[dict]:
        """返回指定用户的自选股列表。

        Returns:
            [{"code":"002475","name":"立讯精密","market":"sz","tags":"","created_at":"..."}, ...]
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT code, name, market, tags, created_at "
                    "FROM watchlist WHERE user_id = ? "
                    "ORDER BY code",
                    (user_id,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "code": r[0],
                        "name": r[1],
                        "market": r[2],
                        "tags": r[3],
                        "created_at": r[4],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def add(
        self,
        code: str,
        name: str = "",
        market: str = "sz",
        tags: str = "",
        user_id: str = "default",
    ) -> bool:
        """添加自选股。已存在则更新 name/market/tags。

        Returns:
            True 成功，False 失败。
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO watchlist "
                    "(code, name, market, tags, user_id, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (code, name, market, tags, user_id, datetime.now()),
                )
                conn.commit()
                logger.info("watchlist.added", code=code, user_id=user_id)
                return True
            except Exception:
                logger.warning("watchlist.add_failed", code=code)
                return False
            finally:
                conn.close()

    def remove(self, code: str, user_id: str = "default") -> bool:
        """删除自选股。

        Returns:
            True 成功删除，False 不存在或失败。
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM watchlist WHERE code = ? AND user_id = ?",
                    (code, user_id),
                )
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info("watchlist.removed", code=code, user_id=user_id)
                return deleted
            except Exception:
                logger.warning("watchlist.remove_failed", code=code)
                return False
            finally:
                conn.close()

    def has(self, code: str, user_id: str = "default") -> bool:
        """检查自选股是否存在。"""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT 1 FROM watchlist WHERE code = ? AND user_id = ?",
                    (code, user_id),
                )
                return cur.fetchone() is not None
            finally:
                conn.close()

    def count(self, user_id: str = "default") -> int:
        """返回自选股数量。"""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM watchlist WHERE user_id = ?",
                    (user_id,),
                )
                return cur.fetchone()[0]
            finally:
                conn.close()

    # ── 设置 ──────────────────────────────────────

    def get_settings(self, user_id: str = "default") -> dict[str, str]:
        """读取所有设置项。

        Returns:
            {"key": "value", ...}
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT key, value FROM settings WHERE user_id = ?",
                    (user_id,),
                )
                return {row[0]: row[1] for row in cur.fetchall()}
            finally:
                conn.close()

    def get_setting(self, key: str, user_id: str = "default") -> str | None:
        """读取单个设置项的值。

        Returns:
            值字符串，不存在时返回 None。
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT value FROM settings WHERE key = ? AND user_id = ?",
                    (key, user_id),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                conn.close()

    def set_setting(self, key: str, value: str, user_id: str = "default") -> None:
        """保存单个设置项（upsert），同时更新 updated_at 时间戳。"""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM settings WHERE key = ? AND user_id = ?",
                    (key, user_id),
                )
                conn.execute(
                    "INSERT INTO settings (key, value, user_id, updated_at) VALUES (?, ?, ?, ?)",
                    (key, value, user_id, datetime.now()),
                )
                conn.commit()
            finally:
                conn.close()

    # ── 迁移 ──────────────────────────────────────

    def migrate_from_csv(self, csv_path: Path) -> int:
        """从 CSV 导入自选股到 DB。跳过已存在的 code。

        Returns:
            导入的条数。
        """
        if not csv_path.exists():
            logger.info("watchlist.migrate_csv_not_found", path=str(csv_path))
            return 0

        count = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("code", "").strip()
                if not code:
                    continue
                if self.has(code):
                    continue
                name = row.get("name", code).strip()
                market = row.get("market", "sz").strip().lower()
                if self.add(code, name, market):
                    count += 1

        logger.info(
            "watchlist.migrated_from_csv",
            path=str(csv_path),
            imported=count,
        )
        return count

    # ── 内部方法 ──────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._path), detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            # v0.5.3 migration: add updated_at column to settings if missing
            self._migrate_settings_schema(conn)
        finally:
            conn.close()

    @staticmethod
    def _migrate_settings_schema(conn: sqlite3.Connection) -> None:
        """Add updated_at column to settings table if it doesn't exist (v0.5.3).

        SQLite ALTER TABLE ADD COLUMN does not support CURRENT_TIMESTAMP as
        a default value, so we add the column with no default and rely on the
        application code (set_setting) to always supply the value.
        """
        cur = conn.execute("PRAGMA table_info(settings)")
        cols = {row[1] for row in cur.fetchall()}
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE settings ADD COLUMN updated_at TIMESTAMP")
            conn.commit()
            logger.info("storage.settings_migrated", added="updated_at")
