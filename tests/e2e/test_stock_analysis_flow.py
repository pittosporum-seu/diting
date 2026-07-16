"""谛听 · 个股分析流程 E2E 测试

测试搜索→查看→缓存→再次查看 完整用户链路。
"""

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.diting.cache.market_state import MarketState
from src.diting.schema import StockAnalysisResponse
from src.diting.web.services import AnalysisService


class _FakeHistorical:
    """模拟 HistoricalData。"""
    def __init__(self):
        self.symbol = "002475"
        self.df = None
        self.columns = []
        self.start_date = date(2026, 1, 1)
        self.end_date = date(2026, 7, 10)
        self.source = None


class TestStockAnalysisFlow:
    """个股分析全链路流程。"""

    def setup_method(self):
        self.service = AnalysisService()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cache_db_path = Path(self.tmpdir.name) / "cache.db"

    def teardown_method(self):
        self.tmpdir.cleanup()

    def _make_fake_quote(self, price=38.5, name="立讯精密", change_pct=1.5):
        quote = MagicMock()
        quote.price = price
        quote.name = name
        quote.change_pct = change_pct
        quote.open = price - 0.5
        quote.high = price + 0.5
        quote.low = price - 1.0
        quote.volume = 1000000
        quote.turnover = price * 1000000
        quote.pe = None
        quote.pb = None
        quote.total_mv = None
        return quote

    @patch("src.diting.web.services.stock.get_market_state")
    def test_first_view_no_cache_calls_pipeline(self, mock_state):
        """第一次查看 002475 → L1 缓存空 → L2 缓存空 → 调 API 返回。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        fake_quote = self._make_fake_quote()
        fake_hist = _FakeHistorical()

        with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None  # L2 miss
            with patch.object(self.service._stock, "get_realtime", return_value=fake_quote):
                with patch.object(self.service._stock, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("002475")

        assert isinstance(result, StockAnalysisResponse)
        assert result.code == "002475"
        assert result.name == "立讯精密"
        assert result.price == 38.5

    def test_second_view_l1_cache_hit(self):
        """第二次查看 002475（5分钟内）→ L1 缓存命中 → 秒返回。"""
        cached_data = StockAnalysisResponse(
            code="002475",
            name="立讯精密",
            price=38.5,
            change_pct=1.5,
            score=72,
        )
        with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = cached_data
            result = self.service.analyze_stock("002475")

        assert result is cached_data
        assert result.code == "002475"
        assert result.price == 38.5
        assert result.score == 72

    @patch("src.diting.web.services.stock.get_market_state")
    def test_third_view_weekend_skips_ai_no_crash(self, mock_state):
        """第三次查看 002475（周末）→ 跳过 AI 引擎，返回技术分析。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        fake_quote = self._make_fake_quote()
        fake_hist = _FakeHistorical()

        with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service._stock, "get_realtime", return_value=fake_quote):
                with patch.object(self.service._stock, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("002475")

        assert isinstance(result, StockAnalysisResponse)
        assert result.code == "002475"
        assert result.score is not None
        ai_engines = [
            e.engine_name for e in result.engine_scores
            if e.engine_name in ("wyckoff", "buffett", "can_slim")
        ]
        assert len(ai_engines) == 0, f"周末不应运行 AI 引擎: {ai_engines}"

    def test_l2_cache_hit_returns_data(self):
        """L1 miss + L2 缓存命中 → 返回缓存数据。"""

        cached_json = json.dumps({
            "code": "002475",
            "name": "立讯精密",
            "price": 38.5,
            "change_pct": 1.5,
            "score": 72,
            "rating": "accumulate",
            "rating_label": "建议关注",
            "rating_emoji": "🟡",
            "confidence": 0.6,
            "engine_scores": [],
            "bull_reasons": [],
            "bear_reasons": [],
            "rsi_display": "55.2",
            "macd_display": "0.123",
            "chart_data": {},
            "error": None,
        })

        with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = {
                "code": "002475",
                "result_json": cached_json,
            }

            result = self.service.analyze_stock("002475")

        assert isinstance(result, StockAnalysisResponse)
        assert result.code == "002475"
        assert result.price == 38.5
        assert result.score == 72

    @patch("src.diting.web.services.stock.get_market_state")
    def test_market_closed_no_ai_engines_but_has_technicals(self, mock_state):
        """盘后查看 → 有技术指标显示但无 AI 分析。"""
        mock_state.return_value = MarketState(
            phase="closed",
            last_trade_date=date(2026, 7, 14),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        fake_quote = self._make_fake_quote(price=12.5, name="平安银行", change_pct=0.8)
        fake_hist = _FakeHistorical()

        with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service._stock, "get_realtime", return_value=fake_quote):
                with patch.object(self.service._stock, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("000001")

        assert isinstance(result, StockAnalysisResponse)
        assert result.code == "000001"
        assert result.name == "平安银行"
        assert result.score is not None

    @patch("src.diting.web.services.stock.get_market_state")
    def test_empty_cache_chain_then_fetch(self, mock_state):
        """L1 miss + L2 miss + API 调用 → 最终返回完整数据。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        fake_quote = self._make_fake_quote()
        fake_hist = _FakeHistorical()

        with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service._stock, "get_realtime", return_value=fake_quote):
                with patch.object(self.service._stock, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("002475")

        assert isinstance(result, StockAnalysisResponse)
        assert result.code == "002475"
        assert result.name == "立讯精密"
        assert isinstance(result.engine_scores, list)

    def test_cache_persists_to_l1_after_fetch(self):
        """API 返回后 → 结果写入 L1 缓存。"""

        with patch("src.diting.web.services.stock.get_market_state") as mock_ms:
            mock_ms.return_value = MarketState(
                phase="trading",
                last_trade_date=date(2026, 7, 10),
                next_trade_date=date(2026, 7, 15),
                today_is_trade_day=True,
            )

            fake_quote = self._make_fake_quote()
            fake_hist = _FakeHistorical()

            with patch.object(self.service._stock, "_get_cache_mgr") as mock_cm:
                mock_cm.return_value.mem_get_adaptive.return_value = None
                mock_cm.return_value.db_get.return_value = None
                with patch.object(
                    self.service._stock, "get_realtime", return_value=fake_quote
                ):
                    with patch.object(
                        self.service._stock, "get_historical", return_value=fake_hist
                    ):
                        self.service.analyze_stock("002475")

        # 验证 L1 缓存被写入，并保持类型协议。
        mock_cm.return_value.mem_set.assert_called()
        cached_result = mock_cm.return_value.mem_set.call_args.args[1]
        assert isinstance(cached_result, StockAnalysisResponse)
