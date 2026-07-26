"""谛听 · AI 引擎超时保护单元测试

测试 pipeline runner 在 AI 引擎超时时的行为：
- 单个引擎超时 → 跳过该引擎，其他继续
- 全部引擎超时 → 返回技术分析
"""

from datetime import date
from unittest.mock import MagicMock, patch

from src.diting.enums import Rating
from src.diting.pipeline.runner import AnalysisPipeline
from src.diting.schema import AnalysisContext, AnalysisResult


class _LongRunningEngine:
    """模拟超时的引擎。"""

    name = "slow_engine"
    version = "1.0.0"

    def __init__(self, delay: float = 30.0):
        self._delay = delay

    def analyze(self, ctx):
        import time

        time.sleep(self._delay)
        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=ctx.symbol,
            score=50.0,
            rating=Rating.HOLD,
        )

    def validate_context(self, ctx):
        return True


class _QuickEngine:
    """正常快速的引擎。"""

    name = "fast_engine"
    version = "1.0.0"

    def analyze(self, ctx):
        return AnalysisResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=ctx.symbol,
            score=75.0,
            rating=Rating.BUY,
            narrative="看好",
        )

    def validate_context(self, ctx):
        return True


class TestAITimeout:
    """AI 引擎超时保护测试。"""

    def test_single_timeout_skips_engine_others_continue(self):
        """单个引擎超时 → 跳过该引擎，其他正常引擎继续。"""

        ctx = AnalysisContext(
            symbol="002475",
            realtime=None,
            historical=None,
        )

        # Mock registry to return our mock engines
        with patch("src.diting.pipeline.runner.get_engine") as mock_get_engine:
            mock_get_engine.side_effect = lambda name: {
                "slow_engine": _LongRunningEngine,
                "fast_engine": _QuickEngine,
            }.get(name)

            pipeline = AnalysisPipeline(engine_names=["slow_engine", "fast_engine"])

            # Patch ThreadPoolExecutor to enforce timeout
            with patch("src.diting.pipeline.runner.ThreadPoolExecutor") as mock_pool_cls:
                from concurrent.futures import Future

                # fast_engine finishes quickly
                fast_future = Future()
                fast_engine = _QuickEngine()
                fast_future.set_result(fast_engine.analyze(ctx))

                # slow_engine never completes (simulate timeout)
                slow_future = Future()
                slow_future.set_exception(TimeoutError("Engine slow_engine timed out after 25s"))

                mock_executor = MagicMock()
                mock_pool_cls.return_value.__enter__.return_value = mock_executor

                # Simulate futures being submitted and completed
                def _fake_submit(fn, name, ctx):
                    fut = Future()
                    if name == "slow_engine":
                        fut = slow_future
                    elif name == "fast_engine":
                        fut = fast_future
                    return fut

                mock_executor.submit.side_effect = _fake_submit

                # Use as_completed-like behavior

                with patch("src.diting.pipeline.runner.as_completed") as mock_ac:
                    # as_completed returns futures in any order
                    mock_ac.return_value = [slow_future, fast_future]

                    result = pipeline.run([ctx])

        # 验证结果
        assert result is not None
        results_for_symbol = result.results.get("002475", [])
        engine_names = [r.engine_name for r in results_for_symbol]
        assert "fast_engine" in engine_names, "快速引擎应完成"
        assert "slow_engine" not in engine_names, "超时引擎不应在结果中"
        assert len(result.errors) == 1, "应有 1 个错误记录"
        assert result.errors[0]["engine"] == "slow_engine"

    def test_all_engines_timeout_returns_empty_results(self):
        """全部引擎超时 → 返回空引擎结果，但不崩溃。"""
        ctx = AnalysisContext(
            symbol="002475",
            realtime=None,
            historical=None,
        )

        with patch("src.diting.pipeline.runner.get_engine") as mock_get_engine:
            mock_get_engine.side_effect = lambda name: {
                "slow_1": _LongRunningEngine,
                "slow_2": _LongRunningEngine,
            }.get(name)

            pipeline = AnalysisPipeline(engine_names=["slow_1", "slow_2"])

            with patch("src.diting.pipeline.runner.ThreadPoolExecutor") as mock_pool_cls:
                from concurrent.futures import Future

                f1 = Future()
                f1.set_exception(TimeoutError("Engine slow_1 timed out"))
                f2 = Future()
                f2.set_exception(TimeoutError("Engine slow_2 timed out"))

                mock_executor = MagicMock()
                mock_pool_cls.return_value.__enter__.return_value = mock_executor
                mock_executor.submit.return_value = Future()

                with patch("src.diting.pipeline.runner.as_completed") as mock_ac:
                    # Return the pre-set futures
                    # Need to capture submit calls and match
                    submitted = {}

                    def _fake_submit(fn, ename, ctx_arg):
                        fut = Future()
                        if ename == "slow_1":
                            fut = f1
                        elif ename == "slow_2":
                            fut = f2
                        submitted[ename] = fut
                        return fut

                    mock_executor.submit.side_effect = _fake_submit
                    mock_ac.return_value = [f1, f2]

                    result = pipeline.run([ctx])

        # 全部超时不应崩溃
        assert result is not None
        results_for_symbol = result.results.get("002475", [])
        assert len(results_for_symbol) == 0, "全部超时应无引擎结果"
        assert len(result.errors) == 2, "应有 2 个错误记录"

    def test_pipeline_error_does_not_block_consensus(self):
        """Pipeline 异常时，services 层应能安全降至 quick_score。"""
        from src.diting.web.services.stock import StockService

        service = StockService()

        with patch("src.diting.web.services.stock.get_market_state") as mock_ms:
            mock_ms.return_value = MagicMock()
            mock_ms.return_value.phase = "trading"
            mock_ms.return_value.should_call_api = True
            mock_ms.return_value.is_trading = True

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

            class _FakeHist:
                symbol = "002475"
                df = None
                columns = []
                start_date = date(2026, 1, 1)
                end_date = date(2026, 7, 10)

            with patch.object(service, "_get_cache_mgr") as mock_cm:
                mock_cm.return_value.mem_get_adaptive.return_value = None
                mock_cm.return_value.db_get.return_value = None
                with patch.object(service, "get_realtime", return_value=fake_quote):
                    with patch.object(service, "get_historical", return_value=_FakeHist()):
                        # Mock pipeline to raise an exception
                        with patch("src.diting.pipeline.runner.AnalysisPipeline") as mock_pl:
                            mock_pl.return_value.run.side_effect = Exception("Pipeline failed")
                            result = service.analyze_stock("002475")

        # 不应崩溃，应返回降级结果
        assert result is not None
        assert result.get("code") == "002475"
        assert result.get("score") is not None
        # 引擎评分列表应为空（pipeline 失败）
        assert result.get("engine_scores", []) == []
