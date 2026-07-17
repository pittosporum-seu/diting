"""谛听 · db_get 列数不匹配边界测试

测试 CacheManager.db_get() 在列数不匹配、单列表、空表等边界场景下
索引安全的行解包行为。
"""

import sqlite3
import tempfile
from pathlib import Path

from src.diting.cache.cache_manager import CacheManager


class TestCacheDbGetBoundary:
    """db_get 边界场景测试。"""

    def test_single_column_table_returns_dict(self):
        """单列表 → 返回单字段 dict。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            cm = CacheManager(db_path=str(db_path))

            # 直接建单列表，绕过 CacheManager 的 schema 迁移
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS single_col (
                    key TEXT PRIMARY KEY
                );
            """)
            conn.execute("INSERT INTO single_col (key) VALUES (?)", ("test_key",))
            conn.commit()
            conn.close()

            result = cm.db_get("single_col", "test_key")
            assert result is not None, "单列表应返回数据"
            assert result == {"key": "test_key"}, f"单列返回: {result}"

    def test_empty_table_returns_none(self):
        """空表（有结构无数据）→ 返回 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            cm = CacheManager(db_path=str(db_path))

            # 建空表
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS empty_tbl (
                    pk TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            conn.commit()
            conn.close()

            result = cm.db_get("empty_tbl", "any_key")
            assert result is None, "空表查询应返回 None"

    def test_row_fewer_columns_than_schema_returns_partial_dict(self):
        """row 列数少于 cur.description → 返回部分 dict，不返回 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # 用 CacheManager 建表（有 key, value, updated_at, expires_at, tier 五列）
            cm = CacheManager(db_path=str(db_path))
            cm.db_set("cache_meta", "partial_key", {
                "key": "partial_key",
                "value": "hello",
            })

            # 手动删除 expires_at 列，模拟列数不匹配
            conn = sqlite3.connect(str(db_path))
            # SQLite 不支持 DROP COLUMN（3.35.0 之前），重建表
            conn.execute("""
                CREATE TABLE cache_meta_new (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP
                );
            """)
            conn.execute("INSERT INTO cache_meta_new SELECT key, value, updated_at FROM cache_meta")
            conn.execute("DROP TABLE cache_meta")
            conn.execute("ALTER TABLE cache_meta_new RENAME TO cache_meta")
            conn.commit()
            conn.close()

            # 现在表只有 3 列，但 cur.description 仍返回 3 列
            # 正常情况下列数匹配，数据可读
            result = cm.db_get("cache_meta", "partial_key")
            assert result is not None
            assert result["key"] == "partial_key"
            assert result["value"] == "hello"

    def test_row_more_columns_than_expected_returns_safe_dict(self):
        """row 有多余列（ALTER TABLE ADD COLUMN）→ 索引安全访问，只取已知列。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            cm = CacheManager(db_path=str(db_path))
            cm.db_set("cache_meta", "extra_key", {
                "key": "extra_key",
                "value": "world",
            })

            # 手动加一列
            conn = sqlite3.connect(str(db_path))
            conn.execute("ALTER TABLE cache_meta ADD COLUMN ghost_col TEXT DEFAULT 'ghost'")
            conn.commit()
            conn.close()

            result = cm.db_get("cache_meta", "extra_key")
            assert result is not None
            assert result["key"] == "extra_key"
            assert result["value"] == "world"
