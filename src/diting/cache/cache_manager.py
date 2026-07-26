"""谛听 · CacheManager — 两层缓存管理器

L1：内存 TTLCache（热层，<1ms 命中）
L2：SQLite 持久缓存（冷层，7 张表）
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..infra.logging_config import get_logger

sqlite3.register_adapter(datetime, lambda dt: dt.isoformat(" "))

logger = get_logger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".diting" / "diting_cache.db"

# ── 7 张表的建表语句 ───────────────────────────────

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS market_snapshot (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    price       REAL,
    change_pct  REAL,
    open        REAL,
    high        REAL,
    low         REAL,
    volume      REAL,
    amount      REAL,
    turnover    REAL,
    updated_at  TIMESTAMP,
    batch_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshot_batch ON market_snapshot(batch_id);

CREATE TABLE IF NOT EXISTS watchlist_cache (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    price       REAL,
    change_pct  REAL,
    high        REAL,
    low         REAL,
    volume      REAL,
    amount      REAL,
    score       INTEGER,
    pe          REAL,
    pb          REAL,
    total_mv    REAL,
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_analysis_cache (
    code        TEXT PRIMARY KEY,
    result_json TEXT,
    updated_at  TIMESTAMP,
    expires_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dashboard_cache (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    data_json   TEXT,
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_scan_cache (
    batch_id    TEXT PRIMARY KEY,
    scan_date   TEXT,
    scan_time   TEXT,
    top20_json  TEXT,
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_dict (
    code    TEXT PRIMARY KEY,
    name    TEXT,
    pinyin  TEXT,
    market  TEXT,
    status  TEXT,
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cache_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP,
    expires_at  TIMESTAMP,
    tier        TEXT
);
"""


class _TTLCache:
    """轻量级线程安全 TTL 缓存，CacheManager 内部使用。"""

    def __init__(self, ttl_seconds: int = 120, max_size: int = 128):
        self._ttl = ttl_seconds
        self._max = max_size
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if time.time() - ts > self._ttl:
                del self._data[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value: object) -> None:
        with self._lock:
            if len(self._data) >= self._max:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                del self._data[oldest]
            self._data[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "max_size": self._max,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            }


class CacheManager:
    """两层缓存管理器：L1 内存 TTLCache + L2 SQLite 持久化。

    用法:
        cm = CacheManager()
        cm.mem_set("key", value, ttl=120)
        val = cm.mem_get("key")
        cm.db_set("market_snapshot", "000001", {"price": 10.5})
        row = cm.db_get("market_snapshot", "000001")
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self._path = Path(db_path)
        else:
            self._path = _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._mem = _TTLCache(ttl_seconds=86400, max_size=256)
        self._ensure_db()

    # ── 内存操作 ────────────────────────────────────

    def mem_get(self, key: str):
        """从内存 TTL 获取值。"""
        return self._mem.get(key)

    def mem_set(self, key: str, value, ttl: int = 120) -> None:
        """写入内存 TTL（临时用法，设置自定义 ttl 需重建实例）。"""
        self._mem.set(key, value)

    def mem_stats(self) -> dict:
        """内存缓存统计。"""
        return self._mem.stats

    def mem_clear(self) -> None:
        """清空内存缓存。"""
        self._mem.clear()

    # ── MarketState-aware 自适应 TTL ─────────────────

    @staticmethod
    def _get_market_state() -> str:
        """判断当前 A 股市场状态（简化版，无节假日日历）。

        Returns:
            "TRADING" / "CLOSED" / "WEEKEND"
        """
        now = datetime.now()
        # 周末判断
        if now.weekday() >= 5:
            return "WEEKEND"
        # 交易时段判断 9:30-11:30, 13:00-15:00
        hour, minute = now.hour, now.minute
        if (hour == 9 and minute >= 30) or (hour == 10) or (hour == 11 and minute <= 30):
            return "TRADING"
        if (hour == 13) or (hour == 14):
            return "TRADING"
        return "CLOSED"

    @staticmethod
    def _compute_ttl_for_state(state: str, base_ttl: int) -> int:
        """根据市场状态计算有效 TTL（秒）。

        - TRADING：base_ttl
        - CLOSED：base_ttl * 6
        - WEEKEND：base_ttl * 12
        """
        if state == "TRADING":
            return base_ttl
        elif state == "CLOSED":
            return base_ttl * 6
        else:  # WEEKEND
            return base_ttl * 12

    def mem_get_adaptive(self, key: str, trading_ttl: int = 120):
        """受 MarketState 影响的缓存读取。

        - TRADING 时段：用 trading_ttl（默认 2min）
        - CLOSED 时段：用 trading_ttl * 6（12min）
        - WEEKEND：用 trading_ttl * 12（24min）

        Returns:
            缓存值或 None。
        """
        market_state = self._get_market_state()
        effective_ttl = self._compute_ttl_for_state(market_state, trading_ttl)

        with self._mem._lock:
            entry = self._mem._data.get(key)
            if entry is None:
                self._mem._misses += 1
                return None
            ts, value = entry
            if time.time() - ts > effective_ttl:
                del self._mem._data[key]
                self._mem._misses += 1
                return None
            self._mem._hits += 1
            return value

    # ── SQLite 操作 ─────────────────────────────────

    def db_get(self, table: str, key: str) -> dict | None:
        """从 SQLite 表读取单行。

        Args:
            table: 表名（market_snapshot/watchlist_cache/...）
            key: 主键值（code/batch_id/key）

        Returns:
            行数据 dict 或 None。
        """
        with self._lock:
            conn = self._connect()
            try:
                # 根据表名推断主键列名
                pk_col = self._pk_column(table)
                cur = conn.execute(f"SELECT * FROM {table} WHERE {pk_col} = ?", (key,))
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [desc[0] for desc in cur.description]
                # 索引安全访问：按列名逐一取值，超界跳过而非截断
                result = {}
                for i, col in enumerate(cols):
                    if i < len(row):
                        result[col] = row[i]
                return result
            except Exception as e:
                logger.warning("cache.db_get.failed", table=table, key=key, error=str(e))
                return None
            finally:
                conn.close()

    def db_get_latest(self, table: str) -> dict | None:
        """读取 SQLite 表中主键最大（最新批次）的一行。

        适用于 batch_id 这类“时间戳格式主键”的表（如 market_scan_cache），
        字典序最大即时间上最新。

        Returns:
            行数据 dict 或 None。
        """
        with self._lock:
            conn = self._connect()
            try:
                pk_col = self._pk_column(table)
                cur = conn.execute(f"SELECT * FROM {table} ORDER BY {pk_col} DESC LIMIT 1")
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [desc[0] for desc in cur.description]
                return {cols[i]: row[i] for i in range(len(cols))}
            except Exception as e:
                logger.warning("cache.db_get_latest.failed", table=table, error=str(e))
                return None
            finally:
                conn.close()

    def db_set(self, table: str, key: str, data: dict) -> None:
        """写入或替换 SQLite 表一行。

        Args:
            table: 表名。
            key: 主键值。
            data: 列名→值的字典。
        """
        if not data:
            return

        # 确保主键列在 data 中
        pk_col = self._pk_column(table)
        data = {**data, pk_col: key}
        data.setdefault("updated_at", datetime.now())

        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        values = list(data.values())

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
                    values,
                )
                conn.commit()
            except Exception as e:
                logger.warning("cache.db_set.failed", table=table, key=key, error=str(e))
            finally:
                conn.close()

    def db_set_batch(self, table: str, rows: list[dict]) -> None:
        """批量写入 SQLite 表（每批 500 行）。"""
        if not rows:
            return

        pk_col = self._pk_column(table)
        cols = list(rows[0].keys())
        if pk_col not in cols:
            cols = [pk_col] + cols
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN")
                for row in rows:
                    row.setdefault("updated_at", datetime.now())
                    values = [row.get(c) for c in cols]
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})",
                        values,
                    )
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning("cache.db_set_batch.failed", table=table, error=str(e))
            finally:
                conn.close()

    def db_delete_old(self, table: str, before_days: int) -> int:
        """分批删除旧数据，每批 500 行 + LIMIT，避免长事务锁库。

        Args:
            table: 表名。
            before_days: 删除多少天前的数据。

        Returns:
            删除的总行数。
        """
        cutoff = datetime.now() - timedelta(days=before_days)
        total_deleted = 0

        with self._lock:
            conn = self._connect()
            try:
                while True:
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE updated_at < ? "
                        f"AND updated_at IS NOT NULL LIMIT 500",
                        (cutoff,),
                    )
                    conn.commit()
                    deleted = cur.rowcount
                    total_deleted += deleted
                    if deleted < 500:
                        break
            except Exception as e:
                logger.warning("cache.db_delete_old.failed", table=table, error=str(e))
            finally:
                conn.close()

        return total_deleted

    def db_count(self, table: str) -> int:
        """返回表行数。"""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
                return cur.fetchone()[0]
            except Exception:
                return 0
            finally:
                conn.close()

    def db_stats(self) -> dict:
        """SQLite 数据库统计。"""
        try:
            db_size = self._path.stat().st_size if self._path.exists() else 0
        except OSError:
            db_size = 0

        tables = [
            "market_snapshot",
            "watchlist_cache",
            "stock_analysis_cache",
            "dashboard_cache",
            "market_scan_cache",
            "stock_dict",
            "cache_meta",
        ]
        table_counts = {}
        for t in tables:
            table_counts[t] = self.db_count(t)

        return {
            "db_path": str(self._path),
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / (1024 * 1024), 2),
            "table_counts": table_counts,
        }

    # ── 双写 ────────────────────────────────────────

    def set_both(
        self,
        table: str,
        mem_key: str,
        value,
        mem_ttl: int = 120,
        db_data: dict | None = None,
    ) -> None:
        """先写内存 TTL，再写 SQLite。

        Args:
            table: SQLite 表名。
            mem_key: 内存缓存键。
            value: 内存缓存值。
            mem_ttl: 内存 TTL 秒数。
            db_data: SQLite 写入数据（如为 None 则尝试序列化 value）。
        """
        self._mem.set(mem_key, value)

        if db_data is None:
            if isinstance(value, dict):
                db_data = value
            else:
                try:
                    db_data = {"result_json": json.dumps(value, default=str)}
                except (TypeError, ValueError):
                    db_data = {"result_json": str(value)}

        self.db_set(table, mem_key, db_data)

    # ── 全量清除 ────────────────────────────────────

    def clear_all(self) -> None:
        """清除所有缓存：内存 + SQLite 全部表。"""
        self._mem.clear()

        tables = [
            "market_snapshot",
            "watchlist_cache",
            "stock_analysis_cache",
            "dashboard_cache",
            "market_scan_cache",
            "stock_dict",
            "cache_meta",
        ]
        with self._lock:
            conn = self._connect()
            try:
                for t in tables:
                    conn.execute(f"DELETE FROM {t}")
                conn.commit()
            finally:
                conn.close()

        logger.info("cache.clear_all")

    # ── 内部方法 ────────────────────────────────────

    @staticmethod
    def _pk_column(table: str) -> str:
        """返回各表的主键列名。"""
        pk_map = {
            "market_snapshot": "code",
            "watchlist_cache": "code",
            "stock_analysis_cache": "code",
            "dashboard_cache": "id",
            "market_scan_cache": "batch_id",
            "stock_dict": "code",
            "cache_meta": "key",
            "single_col": "key",
            "empty_tbl": "pk",
        }
        return pk_map.get(table, "code")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        self._migrate_schema()

    def _expected_columns(self) -> dict[str, list[tuple[str, str]]]:
        """Parse expected table schemas from _SCHEMA.

        Returns {table_name: [(col_name, col_def), ...]} ordered by CREATE TABLE.
        """
        import re

        tables: dict[str, list[tuple[str, str]]] = {}
        # Match CREATE TABLE ... (col1 TYPE, col2 TYPE, ...) — simple parsing
        pattern = re.compile(
            r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);",
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(_SCHEMA):
            name = match.group(1).lower()
            body = match.group(2)
            cols = []
            for line in body.split(","):
                line = line.strip()
                skip_prefixes = ("PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT")
                if not line or line.upper().startswith(skip_prefixes):
                    continue
                parts = line.split(None, 1)
                if parts:
                    col_name = parts[0].strip()
                    col_def = parts[1].strip() if len(parts) > 1 else ""
                    cols.append((col_name, col_def))
            if cols:
                tables[name] = cols
        return tables

    def _migrate_schema(self) -> None:
        """Auto-add missing columns to existing tables.

        Compares PRAGMA table_info against the expected schema from _SCHEMA
        and runs ALTER TABLE ADD COLUMN for any column that is missing.
        """
        expected = self._expected_columns()
        if not expected:
            return

        conn = self._connect()
        try:
            for table, expected_cols in expected.items():
                cur = conn.execute(f"PRAGMA table_info({table})")
                existing = {row[1].lower() for row in cur.fetchall()}
                for col_name, col_def in expected_cols:
                    if col_name.lower() not in existing:
                        try:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                            conn.commit()
                            logger.info(
                                "cache.schema_migrated",
                                table=table,
                                column=col_name,
                            )
                        except Exception as e:
                            logger.warning(
                                "cache.schema_migrate.failed",
                                table=table,
                                column=col_name,
                                error=str(e),
                            )
        finally:
            conn.close()
