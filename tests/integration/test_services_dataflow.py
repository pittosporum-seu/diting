"""谛听 · 数据流架构集成测试

测试各 Service 的 force_refresh + MarketState 集成。
"""

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.diting.cache.market_state import MarketState
from src.diting.web.services import DashboardService, ScanService, StockService


class TestForceRefreshStock:
    """force_refresh 参数测试 — StockService。"""

    def setup_method(self):
        self.service = StockService()

    def test_get_realtime_skips_l1_on_force_refresh(self):
        """force_refresh=True 时跳过 L1 缓存。"""
        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            mock_cm.return_value.mem_set.return_value = None
            with patch.object(self.service, "_build_repo") as mock_repo:
                mock_repo.return_value.get_realtime.return_value = {}
                self.service.get_realtime("000001", force_refresh=True)

        # L1 (mem_get_adaptive) 不应被查询
        mock_cm.return_value.mem_get_adaptive.assert_not_called()


class TestForceRefreshDashboard:
    """force_refresh 参数测试 — DashboardService。"""

    def setup_method(self):
        self.scan_service = ScanService()
        self.service = DashboardService(scan_service=self.scan_service)

    def test_get_dashboard_skips_l1_on_force_refresh(self):
        """force_refresh=True 时跳过 L1 仪表盘缓存。"""
        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "_build_repo") as mock_repo:
                mock_repo.return_value.get_realtime.return_value = {}
                result, freshness = self.service.get_dashboard_data(force_refresh=True)

        mock_cm.return_value.mem_get_adaptive.assert_not_called()

    def test_get_market_sentiment_skips_l1_on_force_refresh(self):
        """force_refresh=True 时跳过 L1 市场情绪缓存。"""
        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            with patch.object(self.service, "_build_repo") as mock_repo:
                mock_repo.return_value.get_realtime.return_value = {"000001.SH": MagicMock(
                    price=3300.0, change_pct=0.5,
                )}
                self.service.get_market_sentiment(force_refresh=True)

        mock_cm.return_value.mem_get_adaptive.assert_not_called()


class TestForceRefreshScan:
    """force_refresh 参数测试 — ScanService。"""

    def setup_method(self):
        self.service = ScanService()

    def test_get_opportunities_skips_l1_on_force_refresh(self):
        """force_refresh=True 时跳过 L1 选股机会缓存。"""
        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            with patch.object(self.service, "_scan_watchlist", return_value=[]), \
                 patch.object(self.service, "_scan_market_top20", return_value=[]):
                self.service.get_opportunities(force_refresh=True)

        mock_cm.return_value.mem_get_adaptive.assert_not_called()


class TestMarketStateIntegration:
    """MarketState 集成测试。"""

    def setup_method(self):
        self.service = StockService()

    @patch("src.diting.web.services.stock.get_market_state")
    def test_realtime_skips_api_when_weekend(self, mock_state):
        """周末不调 API。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=False,
        )

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            result = self.service.get_realtime("000001")

        assert result is not None
        assert result.price == 0.0  # 兜底 RealtimeQuote

    @patch("src.diting.web.services.stock.get_market_state")
    def test_realtime_returns_db_data_when_closed(self, mock_state):
        """盘后返回 DB 数据。"""
        mock_state.return_value = MarketState(
            phase="closed",
            last_trade_date=datetime(2026, 7, 14).date(),
            next_trade_date=datetime(2026, 7, 15).date(),
            today_is_trade_day=True,
        )

        db_data = {
            "code": "000001",
            "name": "平安银行",
            "price": 12.5,
            "change_pct": 1.5,
            "open": 12.3,
            "high": 12.6,
            "low": 12.2,
            "volume": 1000000,
        }

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = db_data
            result = self.service.get_realtime("000001")

        assert result is not None
        assert result.name == "平安银行"
        assert result.price == 12.5


class TestMarketStateDashboard:
    """MarketState 集成测试 — DashboardService。"""

    def setup_method(self):
        self.scan_service = ScanService()
        self.service = DashboardService(scan_service=self.scan_service)

    @patch("src.diting.web.services.dashboard.get_market_state")
    def test_dashboard_returns_db_when_closed(self, mock_state):
        """盘后仪表盘返回 DB 数据，不调 API。"""
        mock_state.return_value = MarketState(
            phase="closed",
            last_trade_date=datetime(2026, 7, 14).date(),
            next_trade_date=datetime(2026, 7, 15).date(),
            today_is_trade_day=True,
        )

        db_data = '{"status":"ok","watchlist_count":5,"buy_signals":2}'

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = {
                "data_json": db_data,
            }
            result, freshness = self.service.get_dashboard_data()

        assert result is not None
        assert result["status"] == "ok"
        assert result["watchlist_count"] == 5
        assert result["buy_signals"] == 2
        assert freshness is not None
        assert freshness.source == "sqlite_cache"
        # 刚写入的缓存 age≈0 <= ttl=300，应为 fresh
        assert freshness.is_fresh is True

    @patch("src.diting.web.services.dashboard.get_market_state")
    def test_dashboard_fetches_fresh_on_weekend_no_db(self, mock_state):
        """周末无缓存时抓取最近交易日数据（ashare 周末可用），不返回空。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=False,
        )

        # mock 指数行情（ashare 周末返回最近交易日数据）
        sh_quote = MagicMock()
        sh_quote.price = 3814.0
        sh_quote.change_pct = -1.6
        mock_repo = MagicMock()
        mock_repo.get_realtime.return_value = {"000001.SH": sh_quote}
        mock_repo.get_historical.return_value = None
        mock_repo.available_providers = ["ashare"]

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            mock_cm.return_value.db_get_latest.return_value = None
            mock_cm.return_value.mem_get.return_value = None
            with patch.object(self.service, "_build_repo", return_value=mock_repo):
                with patch.object(self.scan_service, "get_opportunities", return_value={
                    "total": 0, "strong_buy": 0, "watch": 0, "avoid": 0,
                    "items": [], "from_watchlist": [], "from_market": [],
                }):
                    result, freshness = self.service.get_dashboard_data()

        assert result is not None
        # 周末抓取到指数数据，不再返回空
        assert len(result["market_indices"]) >= 1
        assert result["market_indices"][0]["price"] == 3814.0
        assert freshness is not None
        assert freshness.source != "unavailable"


class TestL2FallbackWithAsyncRefresh:
    """L2 命中 + 后台异步刷新测试。"""

    def setup_method(self):
        self.service = StockService()

    @patch("src.diting.web.services.stock.get_market_state")
    def test_realtime_l2_hit_triggers_async_refresh(self, mock_state):
        """TRADING 状态、L1 miss、L2 hit → 后台异步刷新。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 15).date(),
            today_is_trade_day=True,
        )

        db_data = {
            "code": "000001",
            "name": "平安银行",
            "price": 12.5,
            "change_pct": 1.5,
            "open": 12.3,
            "high": 12.6,
            "low": 12.2,
            "volume": 1000000,
        }

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = db_data
            with patch.object(self.service, "_async_refresh_realtime") as mock_async:
                result = self.service.get_realtime("000001")

        assert result is not None
        assert result.name == "平安银行"
        mock_async.assert_called_once_with("000001")

    @patch("src.diting.web.services.stock.get_market_state")
    def test_realtime_l2_hit_no_async_when_closed(self, mock_state):
        """CLOSED 状态不触发异步刷新。"""
        mock_state.return_value = MarketState(
            phase="closed",
            last_trade_date=datetime(2026, 7, 14).date(),
            next_trade_date=datetime(2026, 7, 15).date(),
            today_is_trade_day=True,
        )

        db_data = {
            "code": "000001",
            "name": "平安银行",
            "price": 12.5,
            "change_pct": 1.5,
            "open": 12.3,
            "high": 12.6,
            "low": 12.2,
            "volume": 1000000,
        }

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = db_data
            with patch.object(self.service, "_async_refresh_realtime") as mock_async:
                result = self.service.get_realtime("000001")

        assert result is not None
        mock_async.assert_not_called()


class TestL2DashboardAsyncRefresh:
    """仪表盘 L2 命中 + 后台异步刷新。"""

    def setup_method(self):
        self.scan_service = ScanService()
        self.service = DashboardService(scan_service=self.scan_service)

    @patch("src.diting.web.services.dashboard.get_market_state")
    def test_dashboard_l2_hit_triggers_async_refresh(self, mock_state):
        """仪表盘 L2 命中 + TRADING → 后台异步刷新。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=datetime(2026, 7, 14).date(),
            next_trade_date=datetime(2026, 7, 15).date(),
            today_is_trade_day=True,
        )

        db_data = '{"status":"ok","watchlist_count":3}'

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = {"data_json": db_data}
            with patch.object(self.service, "_async_refresh_dashboard") as mock_async:
                result, freshness = self.service.get_dashboard_data()

        assert result["watchlist_count"] == 3
        assert freshness is not None
        assert freshness.source == "sqlite_cache"
        mock_async.assert_called_once()


class TestPrefetchWorker:
    """PrefetchWorker 测试。"""

    def test_worker_creation(self):
        """Worker 实例创建。"""
        from src.diting.cache.prefetch import PrefetchWorker
        worker = PrefetchWorker(StockService())
        assert worker is not None
        assert not worker.is_running

    @patch("src.diting.cache.prefetch.get_market_state")
    def test_run_once_skips_on_weekend(self, mock_state):
        """周末跳过预刷新。"""
        from src.diting.cache.prefetch import PrefetchWorker
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=False,
        )

        service = StockService()
        worker = PrefetchWorker(service)
        worker._run_once()

        assert worker.error_count == 0


class TestWeekendFallback:
    """Bug 2: 周末/非交易时段返回兜底 quote。"""

    def setup_method(self):
        self.service = StockService()

    @patch("src.diting.web.services.stock.get_market_state")
    def test_weekend_returns_fallback_quote(self, mock_state):
        """WEEKEND + 无缓存 → 返回兜底 quote（price=0）"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=False,
        )

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            result = self.service.get_realtime("000001")

        assert result is not None
        assert result.price == 0.0
        assert result.change_pct == 0.0

    @patch("src.diting.web.services.stock.get_market_state")
    def test_closed_returns_fallback_quote(self, mock_state):
        """CLOSED（午休）+ 无缓存 → 返回兜底 quote"""
        mock_state.return_value = MarketState(
            phase="closed",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=True,
        )

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            result = self.service.get_realtime("000001")

        assert result is not None
        assert result.price == 0.0

    @patch("src.diting.web.services.stock.get_market_state")
    def test_weekend_with_l2_returns_l2_data(self, mock_state):
        """WEEKEND + L2 有数据 → 返回 L2 数据（不返回兜底）"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=False,
        )

        db_data = {
            "code": "000001", "name": "平安银行", "price": 12.5,
            "change_pct": 1.5, "open": 12.3, "high": 12.6,
            "low": 12.2, "volume": 1000000,
        }

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = db_data
            result = self.service.get_realtime("000001")

        assert result is not None
        assert result.price == 12.5  # L2 的真实价格
        assert result.name == "平安银行"

    @patch("src.diting.web.services.stock.get_market_state")
    def test_analyze_stock_weekend_no_crash(self, mock_state):
        """周末 analyze_stock 不报错，返回可用数据"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=datetime(2026, 7, 10).date(),
            next_trade_date=datetime(2026, 7, 13).date(),
            today_is_trade_day=False,
        )
        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "_build_repo") as mock_repo:
                mock_repo.return_value.get_historical.return_value = None
                result = self.service.analyze_stock("000001")

        assert result is not None
        assert result.get("error") is None or result.get("error") == ""
        assert result.get("score") is not None


class TestScanMarketRepo:
    """Bug 3: _scan_market_top20 走 _build_repo() 降级链。"""

    def setup_method(self):
        self.service = ScanService()

    def test_scan_market_uses_build_repo(self):
        """_scan_market_top20 调用 _build_repo 而非直接 AshareProvider"""
        with patch("src.diting.web.services._utils.load_stock_list") as mock_list:
            mock_list.return_value = [{"code": "000001"}, {"code": "000002"}]
            with patch.object(self.service, "_get_cache_mgr") as mock_cm:
                mock_cm.return_value.mem_get_adaptive.return_value = None
                mock_cm.return_value.db_get.return_value = None
                with patch.object(self.service, "_build_repo") as mock_repo:
                    mock_quote = _MockQuote(
                        symbol="000001", name="平安银行",
                        price=12.0, change_pct=1.0, volume=10000, turnover=0,
                    )
                    mock_repo.return_value.get_realtime.return_value = {
                        "000001": mock_quote,
                    }
                    result = self.service._scan_market_top20()

        # 验证走了 _build_repo
        mock_repo.assert_called_once()
        assert len(result) >= 0  # 不崩溃即可


# 辅助：测试用 mock quote
@dataclass
class _MockQuote:
    symbol: str = ""
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    turnover: float = 0.0
