"""#9 watchlist 解析测试"""

import tempfile
from pathlib import Path

import pytest

from src.diting.config import Config
from src.diting.infra.errors import ConfigError

# ── 夹具：临时 SQLite DB ───────────────────────

@pytest.fixture
def temp_db_path():
    """创建临时 SQLite DB 路径，测试结束后清理。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


# ── 加载测试 ────────────────────────────────────

class TestWatchlistLoading:
    """watchlist 加载测试"""

    def test_load_valid_watchlist(self, temp_db_path):
        cfg = Config(db_path=temp_db_path)
        rows = cfg.load_watchlist("config/watchlist.example.csv")
        assert len(rows) == 3
        assert rows[0]["code"] == "002475"
        assert rows[0]["name"] == "立讯精密"
        assert rows[0]["market"] == "sz"

    def test_load_nonexistent_file(self, temp_db_path):
        cfg = Config(db_path=temp_db_path)
        rows = cfg.load_watchlist("/nonexistent/watchlist.csv")
        assert rows == []

    def test_empty_watchlist(self, temp_db_path):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("code,name,market\n")

        try:
            cfg = Config(db_path=temp_db_path)
            rows = cfg.load_watchlist(f.name)
            assert rows == []
        finally:
            Path(f.name).unlink(missing_ok=True)


class TestWatchlistValidation:
    """验证逻辑测试"""

    def test_valid_codes_accepted(self, temp_db_path):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\n002475,立讯精密,sz\n603659,璞泰来,sh\n")

        try:
            cfg = Config(db_path=temp_db_path)
            rows = cfg.load_watchlist(f.name, validate=True)
            assert len(rows) == 2
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_invalid_code_format(self, temp_db_path):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\nabc,坏代码,sz\n")

        try:
            cfg = Config(db_path=temp_db_path)
            with pytest.raises(ConfigError, match="格式错误"):
                cfg.load_watchlist(f.name, validate=True)
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_invalid_market(self, temp_db_path):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\n002475,立讯精密,nyse\n")

        try:
            cfg = Config(db_path=temp_db_path)
            with pytest.raises(ConfigError, match="无效"):
                cfg.load_watchlist(f.name, validate=True)
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_missing_required_column(self, temp_db_path):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name\n002475,立讯精密\n")

        try:
            cfg = Config(db_path=temp_db_path)
            with pytest.raises(ConfigError, match="缺少必填列"):
                cfg.load_watchlist(f.name, validate=True)
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_skip_validation(self, temp_db_path):
        """validate=False 跳过验证"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\nabc,坏代码,nyse\n")

        try:
            cfg = Config(db_path=temp_db_path)
            rows = cfg.load_watchlist(f.name, validate=False)
            assert len(rows) == 1
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_deduplication(self, temp_db_path):
        """重复代码自动去重"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\n")
            f.write("002475,立讯精密,sz\n")
            f.write("002475,重复的,sz\n")

        try:
            cfg = Config(db_path=temp_db_path)
            rows = cfg.load_watchlist(f.name, validate=True)
            assert len(rows) == 1
        finally:
            Path(f.name).unlink(missing_ok=True)
