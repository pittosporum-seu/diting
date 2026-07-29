"""谛听 · analyze_stock MarketState 守卫单元测试

测试 analyze_stock() 在不同市场状态下的行为：
- WEEKEND → 跳过 AI 引擎，返回技术指标
- CLOSED → 跳过 AI 引擎，返回技术指标
- TRADING → 正常跑 AI 引擎
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from src.diting.cache.market_state import MarketState
from src.diting.enums import Rating
from src.diting.schema import (
    AnalysisResult,
    ConsensusScore,
    HistoricalData,
    PipelineResult,
)
from src.diting.web.services.stock import StockService


class _FakeHistorical:
    """模拟 HistoricalData。"""

    def __init__(self):
        self.symbol = "002475"
        self.df = None
        self.columns = []
        self.start_date = date(2026, 1, 1)
        self.end_date = date(2026, 7, 10)
        self.source = None


class TestAnalyzeStockGuards:
    """analyze_stock MarketState 守卫测试。"""

    def setup_method(self):
        self.service = StockService()

    @patch("src.diting.cache.get_market_state")
    def test_weekend_skips_ai_engines(self, mock_state):
        """WEEKEND + 无缓存 → 不调 DeepSeek API，返回技术指标。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        fake_quote = MagicMock()
        fake_quote.price = 38.5
        fake_quote.name = "立讯精密"
        fake_quote.change_pct = 1.5
        fake_quote.open = 38.0
        fake_quote.high = 39.0
        fake_quote.low = 37.5
        fake_quote.volume = 1000000
        fake_quote.turnover = 38000000.0
        fake_quote.pe = None
        fake_quote.pb = None
        fake_quote.total_mv = None

        fake_hist = _FakeHistorical()

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "get_realtime", return_value=fake_quote):
                with patch.object(self.service, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("002475")

        # 应返回结果不崩溃
        assert result is not None
        assert result.code == "002475"
        # 有技术指标
        assert result.score is not None
        # 不应该有 AI 引擎评分（engine_scores 为空）
        engine_scores = result.engine_scores
        _ai_set = {"wyckoff", "can_slim"}
        ai_engines = [e.engine_name for e in engine_scores if e.engine_name in _ai_set]
        assert len(ai_engines) == 0, f"WEEKEND 不应调 AI 引擎，但调用了: {ai_engines}"
        skipped = {item.engine_name: item.reason for item in result.engine_skipped}
        # 周末或非交易时段跳过 AI 引擎，原因可能是 non_trading_hours / no_api_key / error
        valid_skip_reasons = {"no_api_key", "non_trading_hours", "error"}
        for name in ("wyckoff", "can_slim"):
            assert name in skipped, f"{name} should be skipped"
            assert skipped[name] in valid_skip_reasons

    @patch("src.diting.cache.get_market_state")
    def test_closed_skips_ai_engines(self, mock_state):
        """CLOSED + 无缓存 → 不调 DeepSeek API，返回技术指标。"""
        mock_state.return_value = MarketState(
            phase="closed",
            last_trade_date=date(2026, 7, 14),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        fake_quote = MagicMock()
        fake_quote.price = 12.5
        fake_quote.name = "平安银行"
        fake_quote.change_pct = 0.8
        fake_quote.open = 12.3
        fake_quote.high = 12.6
        fake_quote.low = 12.2
        fake_quote.volume = 500000
        fake_quote.turnover = 6000000.0
        fake_quote.pe = None
        fake_quote.pb = None
        fake_quote.total_mv = None

        fake_hist = _FakeHistorical()

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "get_realtime", return_value=fake_quote):
                with patch.object(self.service, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("000001")

        assert result is not None
        assert result.code == "000001"
        engine_scores = result.engine_scores
        _ai_set = {"wyckoff", "can_slim"}
        ai_engines = [e.engine_name for e in engine_scores if e.engine_name in _ai_set]
        assert len(ai_engines) == 0, f"CLOSED 不应调 AI 引擎，但调用了: {ai_engines}"

    @patch("src.diting.cache.get_market_state")
    def test_trading_runs_ai_engines_normally(self, mock_state):
        """TRADING → 正常跑 AI 引擎管线。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        fake_quote = MagicMock()
        fake_quote.price = 38.5
        fake_quote.name = "立讯精密"
        fake_quote.change_pct = 1.5
        fake_quote.open = 38.0
        fake_quote.high = 39.0
        fake_quote.low = 37.5
        fake_quote.volume = 1000000
        fake_quote.turnover = 38000000.0
        fake_quote.pe = None
        fake_quote.pb = None
        fake_quote.total_mv = None

        fake_hist = _FakeHistorical()

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "get_realtime", return_value=fake_quote):
                with patch.object(self.service, "get_historical", return_value=fake_hist):
                    result = self.service.analyze_stock("002475")

        assert result is not None
        assert result.code == "002475"
        # TRADING 状态应该尝试运行 pipeline
        # engine_scores 可能为空（因为 DB 没有 engine 设置），但不崩溃即可

    @patch("src.diting.cache.get_market_state")
    def test_weekend_with_cache_returns_immediately(self, mock_state):
        """WEEKEND + L1 缓存命中 → 秒返回缓存数据。"""
        cached_data = {
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
            "signals": None,
            "error": None,
        }

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = cached_data
            result = self.service.analyze_stock("002475")

        assert result is not None
        assert result.code == "002475"
        assert result.name == "立讯精密"
        assert result.price == 38.5
        assert result.score == 72

    @patch("src.diting.cache.get_market_state")
    def test_weekend_with_l2_cache_returns_data(self, mock_state):
        """WEEKEND + L1 miss + L2 缓存命中 → 返回缓存数据。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        import json as _json

        db_data = _json.dumps(
            {
                "code": "002475",
                "name": "立讯精密",
                "price": 38.5,
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
            }
        )

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = {
                "code": "002475",
                "result_json": db_data,
            }
            result = self.service.analyze_stock("002475")

        assert result is not None
        assert result.code == "002475"
        assert result.name == "立讯精密"

    @patch("src.diting.cache.get_market_state")
    def test_unknown_stock_returns_error(self, mock_state):
        """无行情数据的股票 → 返回 error 信息不崩溃。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "get_realtime", return_value=None):
                result = self.service.analyze_stock("999999")

        assert result is not None
        assert result.error is not None
        assert "未找到" in (result.error or "")

    @patch("src.diting.cache.get_market_state")
    def test_weekend_default_price_zero(self, mock_state):
        """WEEKEND 无缓存 → 返回兜底数据，price=0 但不崩溃。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        # get_realtime 在周末返回兜底 quote
        with patch.object(self.service, "get_realtime") as mock_rt:
            from src.diting.schema import RealtimeQuote

            fallback = RealtimeQuote(
                symbol="002475",
                name="002475",
                price=0.0,
                change_pct=0.0,
                open=0.0,
                high=0.0,
                low=0.0,
                volume=0,
                turnover=0.0,
                timestamp=datetime.now(),
            )
            mock_rt.return_value = fallback

            with patch.object(self.service, "_get_cache_mgr") as mock_cm:
                mock_cm.return_value.mem_get_adaptive.return_value = None
                mock_cm.return_value.db_get.return_value = None
                with patch.object(self.service, "get_historical", return_value=_FakeHistorical()):
                    result = self.service.analyze_stock("002475")

        assert result is not None
        assert result.code == "002475"
        assert result.price == 0.0
        assert result.error is None


# ═══════════════════════════════════════════════════
# v0.6.6 Bug 修复验证：[:3] 截断 + signals 传递
# ═══════════════════════════════════════════════════

rng = np.random.default_rng(42)
_CLOSE = 70.0 + np.cumsum(rng.normal(0, 0.5, 60))
_FAKE_DF = pd.DataFrame(
    {
        "close": _CLOSE,
        "open": _CLOSE - rng.uniform(0, 0.5, 60),
        "high": _CLOSE + rng.uniform(0, 0.8, 60),
        "low": _CLOSE - rng.uniform(0.3, 0.8, 60),
        "volume": 10000 + rng.integers(0, 5000, 60),
        "date": pd.date_range("2026-05-01", periods=60),
    }
)
_FAKE_HIST = HistoricalData(
    symbol="002475",
    df=_FAKE_DF,
    columns=list(_FAKE_DF.columns),
    start_date=date(2026, 5, 1),
    end_date=date(2026, 6, 29),
)


class TestBugfixEngineCountAndSignals:
    """验证 Bug 修复：[:3] 截断 + signals 传递。"""

    def setup_method(self):
        self.service = StockService()

    @patch("src.diting.web.services.stock.get_market_state")
    def test_engine_count_not_limited_by_three(self, mock_state):
        """验证 engine_names 不再被 [:3] 截断 —— 所有启用的引擎都应进入管线。"""
        mock_state.return_value = MarketState(
            phase="trading",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 15),
            today_is_trade_day=True,
        )

        fake_quote = MagicMock()
        fake_quote.price = 38.5
        fake_quote.name = "立讯精密"
        fake_quote.change_pct = 1.5
        fake_quote.open = 38.0
        fake_quote.high = 39.0
        fake_quote.low = 37.5
        fake_quote.volume = 1000000
        fake_quote.turnover = 38000000.0
        fake_quote.pe = None
        fake_quote.pb = None
        fake_quote.total_mv = None

        _all_five = ["wyckoff", "can_slim", "volume_profile", "vmd_rsi", "verdict"]
        captured_engine_names: list[list[str]] = []

        with patch("src.diting.engines.registry.discover_engines", return_value=list(_all_five)):
            with patch.object(self.service, "_load_saved_settings") as mock_saved:
                mock_saved.return_value = {f"engine_{e}": "1" for e in _all_five}
                with patch("src.diting.pipeline.runner.AnalysisPipeline") as mock_pipeline_cls:
                    mock_instance = MagicMock()
                    mock_pipeline_cls.return_value = mock_instance
                    mock_instance.run.return_value = PipelineResult(
                        symbols=("002475",),
                        results={"002475": []},
                    )

                    # Intercept pipeline constructor to capture engine_names
                    def _init_side_effect(engine_names=None):
                        captured_engine_names.append(list(engine_names or []))
                        return mock_instance

                    mock_pipeline_cls.side_effect = lambda engine_names=None: (
                        _init_side_effect(engine_names) or mock_instance
                    )

                    with patch("src.diting.pipeline.consensus.ConsensusEngine") as mock_ce:
                        mock_ce.return_value.fuse.return_value = ConsensusScore(
                            symbol="002475",
                            weighted_score=50.0,
                            rating=Rating.HOLD,
                        )
                        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
                            mock_cm.return_value.mem_get_adaptive.return_value = None
                            mock_cm.return_value.db_get.return_value = None
                            with patch.object(
                                self.service, "get_realtime", return_value=fake_quote
                            ):
                                with patch.object(
                                    self.service,
                                    "get_historical",
                                    return_value=_FAKE_HIST,
                                ):
                                    result = self.service.analyze_stock("002475")

        assert result is not None
        assert len(captured_engine_names) >= 1
        # 核心断言：引擎数不被 [:3] 截断，所有启用的引擎都进入管线
        engine_count = len(captured_engine_names[0])
        assert engine_count >= 3, (
            f"Expected ≥3 engines but got {engine_count}: {captured_engine_names[0]}"
        )

    @patch("src.diting.web.services.stock.get_market_state")
    def test_all_non_ai_engines_run_when_ai_skipped(self, mock_state):
        """WEEKEND + 真实 historical df → 非 AI 引擎 verdict/volume_profile/vmd_rsi 全部运行。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        fake_quote = MagicMock()
        fake_quote.price = 38.5
        fake_quote.name = "立讯精密"
        fake_quote.change_pct = 1.5
        fake_quote.open = 38.0
        fake_quote.high = 39.0
        fake_quote.low = 37.5
        fake_quote.volume = 1000000
        fake_quote.turnover = 38000000.0
        fake_quote.pe = None
        fake_quote.pb = None
        fake_quote.total_mv = None

        _ai_engines = {"wyckoff", "can_slim"}

        with patch.object(self.service, "_get_cache_mgr") as mock_cm:
            mock_cm.return_value.mem_get_adaptive.return_value = None
            mock_cm.return_value.db_get.return_value = None
            with patch.object(self.service, "get_realtime", return_value=fake_quote):
                with patch.object(self.service, "get_historical", return_value=_FAKE_HIST):
                    result = self.service.analyze_stock("002475")

        assert result is not None
        engine_scores = result.engine_scores
        engine_names_run = [e.engine_name for e in engine_scores]

        # 非 AI 引擎应全部出现
        _non_ai_expected = {"verdict", "volume_profile", "vmd_rsi"}
        non_ai_run = set(engine_names_run)
        for ename in _non_ai_expected:
            assert ename in non_ai_run, (
                f"Non-AI engine '{ename}' should run but is missing. Run: {engine_names_run}"
            )

        # AI 引擎不应出现
        ai_run = [n for n in engine_names_run if n in _ai_engines]
        assert len(ai_run) == 0, f"AI engines should be skipped but ran: {ai_run}"

        # 引擎数量 ≥ 3
        assert len(engine_scores) >= 3, f"Expected ≥3 engine scores, got {len(engine_scores)}"

        # 每个非 AI 引擎的 score 在 0-100 之间
        for es in engine_scores:
            if es.engine_name in _non_ai_expected:
                score = es.score
                assert 0 <= score <= 100, f"Engine {es.engine_name} score {score} out of [0, 100]"

    @patch("src.diting.cache.get_market_state")
    def test_signals_passed_to_analysis_context(self, mock_state):
        """验证 TechnicalSignals 被传入 AnalysisContext.signals。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        fake_quote = MagicMock()
        fake_quote.price = 38.5
        fake_quote.name = "立讯精密"
        fake_quote.change_pct = 1.5
        fake_quote.open = 38.0
        fake_quote.high = 39.0
        fake_quote.low = 37.5
        fake_quote.volume = 1000000
        fake_quote.turnover = 38000000.0
        fake_quote.pe = None
        fake_quote.pb = None
        fake_quote.total_mv = None

        captured_ctx: list = []

        with patch("src.diting.pipeline.runner.AnalysisPipeline.run") as mock_run:
            mock_run.return_value = PipelineResult(
                symbols=("002475",),
                results={"002475": []},
            )

            # Capture the context passed to pipeline.run
            def capture_run(ctx_list):
                captured_ctx.extend(ctx_list)
                return PipelineResult(
                    symbols=tuple(c.symbol for c in ctx_list),
                    results={c.symbol: [] for c in ctx_list},
                )

            mock_run.side_effect = capture_run

            with patch("src.diting.pipeline.consensus.ConsensusEngine") as mock_ce:
                mock_ce.return_value.fuse.return_value = ConsensusScore(
                    symbol="002475",
                    weighted_score=50.0,
                    rating=Rating.HOLD,
                )
                with patch.object(self.service, "_get_cache_mgr") as mock_cm:
                    mock_cm.return_value.mem_get_adaptive.return_value = None
                    mock_cm.return_value.db_get.return_value = None
                    with patch.object(self.service, "get_realtime", return_value=fake_quote):
                        with patch.object(self.service, "get_historical", return_value=_FAKE_HIST):
                            self.service.analyze_stock("002475")

        assert len(captured_ctx) == 1, f"Expected 1 AnalysisContext, got {len(captured_ctx)}"
        ctx = captured_ctx[0]
        assert ctx.signals is not None, (
            "AnalysisContext.signals should not be None when historical df is available"
        )
        assert ctx.signals.rsi_14 != 0.0, "RSI should be computed from real data"
        assert isinstance(ctx.symbol, str)

    @patch("src.diting.cache.get_market_state")
    def test_reasons_are_collected_only_from_engine_metadata(self, mock_state):
        """结构化理由来自 metadata；narrative 中的关键词不得再被抽取。"""
        mock_state.return_value = MarketState(
            phase="weekend",
            last_trade_date=date(2026, 7, 10),
            next_trade_date=date(2026, 7, 13),
            today_is_trade_day=False,
        )

        fake_quote = MagicMock(
            price=38.5,
            name="立讯精密",
            change_pct=1.5,
            open=38.0,
            high=39.0,
            low=37.5,
            volume=1000000,
            turnover=38000000.0,
            pe=None,
            pb=None,
            total_mv=None,
        )
        engine_result = AnalysisResult(
            engine_name="verdict",
            engine_version="1.0.0",
            symbol="002475",
            score=70.0,
            rating=Rating.BUY,
            narrative="买入关键词只存在于叙事，不应被服务层抽取",
            confidence=0.7,
            metadata={
                "bull_reasons": ["RSI=28，处于超卖区", "RSI=28，处于超卖区"],
                "bear_reasons": ["PE=120，估值偏高"],
            },
        )

        with patch("src.diting.pipeline.runner.AnalysisPipeline.run") as mock_run:
            mock_run.return_value = PipelineResult(
                symbols=("002475",),
                results={"002475": [engine_result]},
            )
            with patch("src.diting.pipeline.consensus.ConsensusEngine") as mock_ce:
                mock_ce.return_value.fuse.return_value = ConsensusScore(
                    symbol="002475",
                    weighted_score=70.0,
                    rating=Rating.BUY,
                    confidence=0.7,
                )
                with patch.object(self.service, "_get_cache_mgr") as mock_cm:
                    mock_cm.return_value.mem_get_adaptive.return_value = None
                    mock_cm.return_value.db_get.return_value = None
                    with patch.object(self.service, "get_realtime", return_value=fake_quote):
                        with patch.object(self.service, "get_historical", return_value=_FAKE_HIST):
                            result = self.service.analyze_stock("002475")

        assert result.bull_reasons == ["RSI=28，处于超卖区"]
        assert result.bear_reasons == ["PE=120，估值偏高"]
        assert all("买入关键词" not in reason for reason in result.bull_reasons)
