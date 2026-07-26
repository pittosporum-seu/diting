"""谛听 · 自选股流程 E2E 测试

测试添加→查DB→查列表→删除→重复添加 完整用户链路。
"""

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.diting.cache.market_state import MarketState
from src.diting.storage import WatchlistDB
from src.diting.web.services import AnalysisService


class TestWatchlistFlow:
    """自选股 CRUD 完整流程。"""

    def setup_method(self):
        # 使用临时数据库
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_wl.db"
        self.db = WatchlistDB(db_path=str(self.db_path))
        self.service = AnalysisService(watchlist_db=self.db)

    def teardown_method(self):
        self.tmpdir.cleanup()

    def test_add_watchlist_then_check_db(self):
        """添加 002475 → 查 DB watchlist 表确认有记录。"""
        result = self.service.add_watchlist("002475", "立讯精密", "sz")
        assert result is True, "添加应成功"

        # 查 DB 确认
        assert self.db.has("002475"), "DB 中应有 002475"
        items = self.db.list()
        codes = [r["code"] for r in items]
        assert "002475" in codes, "列表中应包含 002475"

    def test_get_watchlist_includes_added_stock(self):
        """添加后调 get_watchlist() → 返回包含 002475。"""
        self.db.add("002475", "立讯精密", "sz")

        with patch("src.diting.web.services.watchlist.get_market_state") as mock_ms:
            mock_ms.return_value = MarketState(
                phase="trading",
                last_trade_date=date(2026, 7, 10),
                next_trade_date=date(2026, 7, 15),
                today_is_trade_day=True,
            )

            with patch.object(self.service._watchlist, "_build_repo") as mock_repo:
                mock_quote = MagicMock()
                mock_quote.price = 38.5
                mock_quote.name = "立讯精密"
                mock_quote.change_pct = 1.5
                mock_quote.volume = 1000000
                mock_quote.pe = None
                mock_repo.return_value.get_realtime.return_value = {
                    "002475": mock_quote,
                }

                results = self.service.get_watchlist()
                codes = [r["code"] for r in results]
                assert "002475" in codes

    def test_weekend_get_watchlist_has_price_from_cache(self):
        """周末调 get_watchlist() → 有 code+name+price（price 来自缓存 DB）。"""
        self.db.add("002475", "立讯精密", "sz")

        with patch("src.diting.web.services.watchlist.get_market_state") as mock_ms:
            mock_ms.return_value = MarketState(
                phase="weekend",
                last_trade_date=date(2026, 7, 10),
                next_trade_date=date(2026, 7, 13),
                today_is_trade_day=False,
            )

            with patch.object(self.service._watchlist, "_get_cache_mgr") as mock_cm:
                mock_cm.return_value.db_get.return_value = {
                    "code": "002475",
                    "name": "",
                    "price": 38.5,
                    "change_pct": 1.5,
                    "volume": 1000000,
                }

                results = self.service.get_watchlist()
                assert len(results) >= 1
                stock = [r for r in results if r["code"] == "002475"][0]
                assert stock["name"] == "立讯精密"
                assert stock["price"] == 38.5, "周末应从 DB 缓存获取价格"
                mock_cm.return_value.db_get.assert_called_once_with("market_snapshot", "002475")

    def test_remove_watchlist_then_check_db(self):
        """删除 002475 → 查 DB 确认已删除。"""
        self.db.add("002475", "立讯精密", "sz")
        assert self.db.has("002475")

        result = self.service.remove_watchlist("002475")
        assert result is True, "删除应成功"
        assert not self.db.has("002475"), "DB 中不应再有 002475"

    def test_duplicate_add_no_duplicate_rows(self):
        """重复添加 → DB 无重复行。"""
        # 第一次
        self.db.add("002475", "立讯精密", "sz")
        count1 = self.db.count()
        # 第二次
        self.db.add("002475", "立讯精密", "sz")
        count2 = self.db.count()

        assert count1 == count2, f"重复添加不应增加行数: {count1} → {count2}"
        assert self.db.has("002475"), "仍应有该记录"

    def test_add_multiple_stocks(self):
        """添加多只股票 → DB 每只都有。"""
        self.db.add("002475", "立讯精密", "sz")
        self.db.add("000001", "平安银行", "sz")
        self.db.add("603667", "五洲新春", "sh")

        items = self.db.list()
        codes = [r["code"] for r in items]
        assert "002475" in codes
        assert "000001" in codes
        assert "603667" in codes
        assert len(codes) == 3

    def test_remove_nonexistent_returns_false(self):
        """删除不存在的股票 → 返回 False。"""
        result = self.service.remove_watchlist("999999")
        assert result is False, "删除不存在的股票应返回 False"

    def test_remove_then_re_add(self):
        """删除后再添加 → 重新出现在列表中。"""
        self.db.add("002475", "立讯精密", "sz")
        self.db.remove("002475")
        assert not self.db.has("002475")

        # 重新添加
        self.db.add("002475", "立讯精密", "sz")
        assert self.db.has("002475")
        assert self.db.count() == 1

    def test_add_with_empty_name(self):
        """添加时 name 为空 → 仍能添加成功。"""
        result = self.service.add_watchlist("002475", "", "sz")
        assert result is True
        assert self.db.has("002475")

    def test_watchlist_count_after_ops(self):
        """多次操作后计数正确。"""
        assert self.db.count() == 0

        self.db.add("002475", "立讯精密", "sz")
        assert self.db.count() == 1

        self.db.add("000001", "平安银行", "sz")
        assert self.db.count() == 2

        self.db.remove("002475")
        assert self.db.count() == 1

        self.db.add("002475", "立讯精密", "sz")
        assert self.db.count() == 2
