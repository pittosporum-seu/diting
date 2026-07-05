"""M4 测试: AI 客户端 + 沙箱 + 引擎注册 + Wyckoff"""

from unittest.mock import MagicMock, patch

from src.diting.ai.client import AIClient
from src.diting.engines.base import AnalysisEngine
from src.diting.engines.registry import discover_engines, get_engine, register_engine
from src.diting.engines.wyckoff import WYCKOFF_SYSTEM_PROMPT, WyckoffEngine
from src.diting.enums import DataType, Rating
from src.diting.sandbox.executor import SandboxExecutor

# ═══════════════════════════════════════════
# AI Client
# ═══════════════════════════════════════════


class TestAIClient:
    def test_init_defaults(self):
        client = AIClient()
        assert client.model == "deepseek/deepseek-v4-pro"
        assert client.temperature == 0.3

    def test_init_custom(self):
        client = AIClient(model="openai/gpt-4o", temperature=0.5)
        assert client.model == "openai/gpt-4o"
        assert client.temperature == 0.5

    @patch("src.diting.ai.client.completion")
    def test_complete_returns_content(self, mock_completion):
        mock_completion.return_value.choices = [
            MagicMock(message=MagicMock(content="分析结果: 买入"))
        ]
        client = AIClient(model="test/model", api_key="fake")
        result = client.complete(system="你是一个分析师", user="分析这只股票")
        assert result == "分析结果: 买入"


# ═══════════════════════════════════════════
# Sandbox (mock)
# ═══════════════════════════════════════════


class TestSandbox:
    def test_init(self):
        sb = SandboxExecutor(memory_limit_mb=256, timeout_seconds=30)
        assert sb._memory_limit_mb == 256
        assert sb._timeout_seconds == 30


# ═══════════════════════════════════════════
# Engine Base + Registry
# ═══════════════════════════════════════════


class TestEngineABC:
    def test_cannot_instantiate_abc(self):
        import pytest
        with pytest.raises(TypeError):
            AnalysisEngine()


class TestRegistry:
    def test_register_engine(self):
        @register_engine("test_engine")
        class TestEngine(AnalysisEngine):
            name = "test_engine"
            version = "0.0.1"

            def required_data(self):
                return [DataType.REALTIME]

            def analyze(self, ctx):
                return None

        assert "test_engine" in discover_engines()
        assert get_engine("test_engine") is TestEngine

    def test_wyckoff_is_registered(self):
        # Wyckoff 在 import 时自动注册
        assert "wyckoff" in discover_engines()


# ═══════════════════════════════════════════
# Wyckoff Engine
# ═══════════════════════════════════════════


class TestWyckoffEngine:
    def test_name_and_version(self):
        engine = WyckoffEngine()
        assert engine.name == "wyckoff"
        assert engine.version == "1.0.0"

    def test_required_data(self):
        engine = WyckoffEngine()
        assert DataType.HISTORICAL in engine.required_data()

    def test_to_rating(self):
        assert WyckoffEngine._to_rating(85) == Rating.STRONG_BUY
        assert WyckoffEngine._to_rating(70) == Rating.BUY
        assert WyckoffEngine._to_rating(55) == Rating.ACCUMULATE
        assert WyckoffEngine._to_rating(40) == Rating.HOLD
        assert WyckoffEngine._to_rating(25) == Rating.REDUCE
        assert WyckoffEngine._to_rating(10) == Rating.SELL

    def test_analyze_no_data(self):
        """无历史数据返回 HOLD"""
        engine = WyckoffEngine()
        from src.diting.schema import AnalysisContext
        ctx = AnalysisContext(symbol="002475")
        result = engine.analyze(ctx)
        assert result.rating == Rating.HOLD
        assert result.error is not None

    def test_system_prompt_not_empty(self):
        assert len(WYCKOFF_SYSTEM_PROMPT) > 100
        assert "Phase" in WYCKOFF_SYSTEM_PROMPT

    def test_context_validation(self):
        """validate_context 检查数据"""
        from src.diting.schema import AnalysisContext, RealtimeQuote
        engine = WyckoffEngine()
        # 只有 realtime 没有 historical → 应该 False
        ctx = AnalysisContext(
            symbol="002475",
            realtime=RealtimeQuote(
                symbol="002475", name="test", price=10, change_pct=0,
                open=10, high=10, low=10, volume=1000, turnover=10000,
            )
        )
        assert engine.validate_context(ctx) is False
