"""谛听 · L2 缓存防御单元测试

测试 CacheManager.db_get() 在表结构不匹配时安全返回 None，
不抛异常、不崩溃。
"""

import sqlite3
import tempfile
from pathlib import Path

from src.diting.cache.cache_manager import CacheManager


class TestCacheDefense:
    """L2 缓存解包失败不崩溃测试。"""

    def test_old_table_two_columns_migrated_and_readable(self):
        """旧结构 stock_analysis_cache 表（只有 code + result_json 两列）
        → schema 自动迁移后可读。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # 手动建旧结构表（模拟 v0.6.4 之前的表结构）
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE stock_analysis_cache (
                    code TEXT PRIMARY KEY,
                    result_json TEXT
                );
            """)
            conn.execute(
                "INSERT INTO stock_analysis_cache (code, result_json) VALUES (?, ?)",
                ("002475", '{"score": 75}'),
            )
            conn.commit()
            conn.close()

            # CacheManager 应该自动迁移 schema（加 updated_at/expires_at 列）
            cm = CacheManager(db_path=str(db_path))
            result = cm.db_get("stock_analysis_cache", "002475")
            # 迁移后列数匹配，数据可读
            assert result is not None, "迁移后数据应可读"
            assert result["code"] == "002475"
            assert result["result_json"] == '{"score": 75}'
            # updated_at 和 expires_at 为迁移时添加的 NULL 列
            assert "updated_at" in result
            assert "expires_at" in result

    def test_missing_table_returns_none(self):
        """查询不存在的表 → 返回 None 不抛异常。"""
        cm = CacheManager()
        result = cm.db_get("nonexistent_table", "000001")
        assert result is None, "不存在的表应返回 None"

    def test_nonexistent_key_returns_none(self):
        """查询存在的表但不存在的 key → 返回 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            cm = CacheManager(db_path=str(db_path))
            result = cm.db_get("stock_analysis_cache", "999999")
            assert result is None, "不存在的 key 应返回 None"

    def test_valid_table_valid_key_returns_data(self):
        """正常表结构 + 正常 key → 返回数据 dict。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            cm = CacheManager(db_path=str(db_path))

            # 通过 CacheManager 写入正确结构的数据
            cm.db_set(
                "stock_analysis_cache",
                "002475",
                {
                    "code": "002475",
                    "result_json": '{"score": 80}',
                },
            )

            result = cm.db_get("stock_analysis_cache", "002475")
            assert result is not None, "正常数据应能读取"
            assert result["code"] == "002475"
            assert result["result_json"] == '{"score": 80}'

    def test_column_mismatch_still_returns_safely(self):
        """手动构造列数不匹配场景 → db_get 返回 None 不抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # 先通过 CacheManager 创建正常表
            cm = CacheManager(db_path=str(db_path))
            cm.db_set(
                "cache_meta",
                "test_key",
                {
                    "key": "test_key",
                    "value": "test_value",
                },
            )

            # 直接在 SQLite 加一列额外字段（schema 中没有的列）
            conn = sqlite3.connect(str(db_path))
            conn.execute("ALTER TABLE cache_meta ADD COLUMN old_extra_col TEXT")
            conn.commit()
            conn.close()

            # 查询时，SELECT * 返回的列数比 schema 描述多一列
            # 但这仍能工作（dict(zip(cols, row)) 会截断）
            result = cm.db_get("cache_meta", "test_key")
            assert result is not None, "有额外列时数据应仍可读"
            assert result["key"] == "test_key"
            assert result["value"] == "test_value"

    def test_db_get_on_truly_broken_table_returns_none(self):
        """表存在但查询语句本身会失败 → 返回 None 不抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            cm = CacheManager(db_path=str(db_path))

            # 创建一张表，然后用 SQLite 损坏它
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bad_table (
                    pk TEXT,
                    value TEXT
                );
            """)
            conn.commit()
            conn.close()

            # 现在把表删掉但 CacheManager 不知道
            conn2 = sqlite3.connect(str(db_path))
            conn2.execute("DROP TABLE bad_table")
            conn2.commit()
            conn2.close()

            # 查询已不存在的表 → 返回 None（被 except 捕获）
            result = cm.db_get("bad_table", "test")
            assert result is None, "损坏的表应安全返回 None"
