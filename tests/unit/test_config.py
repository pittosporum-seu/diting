"""#9 watchlist 解析测试"""

import tempfile
from pathlib import Path

import pytest

from src.diting.config import Config
from src.diting.infra.errors import ConfigError


class TestWatchlistLoading:
    """watchlist 加载测试"""

    def test_load_valid_watchlist(self):
        cfg = Config()
        rows = cfg.load_watchlist("config/watchlist.example.csv")
        assert len(rows) == 3
        assert rows[0]["code"] == "002475"
        assert rows[0]["name"] == "立讯精密"
        assert rows[0]["market"] == "sz"

    def test_load_nonexistent_file(self):
        cfg = Config()
        with pytest.raises(ConfigError, match="not found"):
            cfg.load_watchlist("/nonexistent/watchlist.csv")

    def test_empty_watchlist(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("code,name,market\n")

        try:
            cfg = Config()
            rows = cfg.load_watchlist(f.name)
            assert rows == []
        finally:
            Path(f.name).unlink()


class TestWatchlistValidation:
    """验证逻辑测试"""

    def test_valid_codes_accepted(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\n002475,立讯精密,sz\n603659,璞泰来,sh\n")

        try:
            cfg = Config()
            rows = cfg.load_watchlist(f.name, validate=True)
            assert len(rows) == 2
        finally:
            Path(f.name).unlink()

    def test_invalid_code_format(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\nabc,坏代码,sz\n")

        try:
            cfg = Config()
            with pytest.raises(ConfigError, match="格式错误"):
                cfg.load_watchlist(f.name, validate=True)
        finally:
            Path(f.name).unlink()

    def test_invalid_market(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\n002475,立讯精密,nyse\n")

        try:
            cfg = Config()
            with pytest.raises(ConfigError, match="无效"):
                cfg.load_watchlist(f.name, validate=True)
        finally:
            Path(f.name).unlink()

    def test_missing_required_column(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name\n002475,立讯精密\n")

        try:
            cfg = Config()
            with pytest.raises(ConfigError, match="缺少必填列"):
                cfg.load_watchlist(f.name, validate=True)
        finally:
            Path(f.name).unlink()

    def test_skip_validation(self):
        """validate=False 跳过验证"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\nabc,坏代码,nyse\n")

        try:
            cfg = Config()
            rows = cfg.load_watchlist(f.name, validate=False)
            assert len(rows) == 1
        finally:
            Path(f.name).unlink()

    def test_deduplication(self):
        """重复代码自动去重"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("code,name,market\n")
            f.write("002475,立讯精密,sz\n")
            f.write("002475,重复的,sz\n")

        try:
            cfg = Config()
            rows = cfg.load_watchlist(f.name, validate=True)
            assert len(rows) == 1
        finally:
            Path(f.name).unlink()
