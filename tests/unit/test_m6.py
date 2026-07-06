"""M6 单元测试 — ReportBuilder + Notifier"""

from __future__ import annotations

import os

import pytest

from src.diting.enums import Rating
from src.diting.notify.base import Notifier
from src.diting.notify.email import EmailNotifier
from src.diting.notify.feishu import FeishuNotifier
from src.diting.notify.local import LocalNotifier
from src.diting.report.builder import ReportBuilder
from src.diting.schema import AnalysisResult, PipelineResult


def _make_result(
    symbol: str = "002475",
    engine_name: str = "wyckoff",
    score: float = 65.0,
    rating: Rating = Rating.BUY,
    **kwargs,
) -> AnalysisResult:
    """快速创建 AnalysisResult。"""
    return AnalysisResult(
        engine_name=engine_name,
        engine_version="1.0.0",
        symbol=symbol,
        score=score,
        rating=rating,
        **kwargs,
    )


def _make_pipeline(
    symbols: tuple = ("002475",),
    results: dict | None = None,
) -> PipelineResult:
    """快速创建 PipelineResult。"""
    return PipelineResult(
        symbols=symbols,
        results=results or {},
        metrics={"duration_ms": 100, "engines": 1, "symbols": len(symbols)},
    )


# ═══════════════════════════════════════════════════════
# ReportBuilder 测试
# ═══════════════════════════════════════════════════════


class TestReportBuilder:
    """ReportBuilder 单元测试"""

    def test_builder_creates_html_l1(self):
        """L1 报告生成包含 HTML 结构。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "wyckoff", 65.0, Rating.BUY,
                                 narrative="测试信号"),
                ],
            },
        )
        builder = ReportBuilder(level="L1")
        html = builder.build(result)

        assert "<!DOCTYPE html>" in html
        assert "002475" in html
        assert "谛听" in html
        assert "echarts" in html

    def test_builder_creates_html_l2(self):
        """L2 报告生成包含详细分析区。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "wyckoff", 65.0, Rating.BUY,
                                 narrative="测试"),
                ],
            },
        )
        chart_data = {
            "002475": {
                "name": "立讯精密",
                "dates": ["2026-01-02", "2026-01-03", "2026-01-04"],
                "prices": [70.0, 70.5, 71.0],
                "rsi_values": [45.0, 48.0, 50.0],
                "realtime_price": 71.0,
                "change_pct": 2.1,
            },
        }
        builder = ReportBuilder(level="L2")
        html = builder.build(result, chart_data=chart_data)

        assert "<!DOCTYPE html>" in html
        assert "深度分析" in html
        assert "002475" in html
        assert "立讯精密" in html

    def test_builder_creates_html_with_charts(self):
        """图表数据正确时渲染图表。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "wyckoff", 80.0, Rating.STRONG_BUY),
                    _make_result("002475", "vmd_rsi", 70.0, Rating.BUY),
                ],
            },
        )
        chart_data = {
            "002475": {
                "name": "立讯精密",
                "dates": ["2026-01-02", "2026-01-03"],
                "prices": [70.0, 70.5],
                "rsi_values": [45.0, 48.0],
                "ma_5": [69.0, 69.5],
                "ma_20": [68.0, 68.5],
                "boll_upper": [72.0, 72.5],
                "boll_lower": [66.0, 66.5],
                "realtime_price": 70.5,
                "change_pct": 0.7,
                "market_value": 100000.0,
            },
        }
        builder = ReportBuilder(level="L2")
        html = builder.build(result, chart_data=chart_data)

        assert "echarts.init" in html
        assert "price_002475" in html
        assert "rsi_002475" in html
        assert "radar_002475" in html
        assert "bar_002475" in html

    def test_builder_empty_pipeline(self):
        """空管道不崩溃。"""
        result = _make_pipeline(symbols=())
        builder = ReportBuilder(level="L1")
        html = builder.build(result)

        assert "<!DOCTYPE html>" in html
        assert "谛听" in html

    def test_builder_invalid_level(self):
        """无效级别抛异常。"""
        with pytest.raises(ValueError, match="不支持的报告级别"):
            ReportBuilder(level="L3")

    def test_builder_save(self, tmp_path):
        """save() 写入文件。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "wyckoff", 65.0, Rating.BUY),
                ],
            },
        )
        builder = ReportBuilder(level="L1")
        html = builder.build(result)
        path = os.path.join(str(tmp_path), "report.html")
        builder.save(html, path)

        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            saved = f.read()
        assert "谛听" in saved

    def test_builder_l2_empty_chart_data(self):
        """L2 无图表数据时不崩溃。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "wyckoff", 50.0, Rating.ACCUMULATE),
                ],
            },
        )
        builder = ReportBuilder(level="L2")
        html = builder.build(result)

        assert "<!DOCTYPE html>" in html
        assert "深度分析" in html

    def test_builder_with_error_results(self):
        """含错误的引擎结果不崩溃。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "wyckoff", 65.0, Rating.BUY),
                    _make_result("002475", "buffett", 0, Rating.HOLD,
                                 error="数据源不可用"),
                ],
            },
        )
        builder = ReportBuilder(level="L1")
        html = builder.build(result)

        assert "<!DOCTYPE html>" in html
        # 有错误的引擎不应计入评分
        assert "65" in html  # wyckoff's score

    def test_builder_with_risks(self):
        """风险信息正确渲染。"""
        result = _make_pipeline(
            symbols=("002475",),
            results={
                "002475": [
                    _make_result("002475", "vmd_rsi", 30.0, Rating.REDUCE,
                                 risks=("RSI=78 超买", "VMD 接近峰顶")),
                ],
            },
        )
        builder = ReportBuilder(level="L1")
        html = builder.build(result)

        assert "RSI=78 超买" in html
        assert "VMD 接近峰顶" in html


# ═══════════════════════════════════════════════════════
# Notifier 测试
# ═══════════════════════════════════════════════════════


class TestNotifierABC:
    """Notifier ABC 测试"""

    def test_cannot_instantiate_abc(self):
        """抽象基类不可直接实例化。"""
        with pytest.raises(TypeError):
            Notifier()  # type: ignore[abstract]

    def test_subclass_must_implement_abstract(self):
        """未实现抽象方法的子类无法实例化。"""
        with pytest.raises(TypeError):

            class BadNotifier(Notifier):
                pass

            BadNotifier()  # type: ignore[abstract]


class TestLocalNotifier:
    """LocalNotifier 测试"""

    def test_sends_saves_file(self, tmp_path):
        """send() 将内容保存到文件。"""
        notifier = LocalNotifier(output_dir=str(tmp_path))
        result = notifier.send("<html>测试报告</html>")

        assert result is True
        files = os.listdir(str(tmp_path))
        assert len(files) == 1
        assert files[0].startswith("report_")
        assert files[0].endswith(".html")

        with open(os.path.join(str(tmp_path), files[0]), encoding="utf-8") as f:
            content = f.read()
        assert "测试报告" in content

    def test_channel_name(self):
        """channel_name 正确。"""
        notifier = LocalNotifier()
        assert notifier.channel_name == "local"

    def test_health_check(self):
        """health_check 默认返回 True。"""
        notifier = LocalNotifier()
        assert notifier.health_check() is True


class TestFeishuNotifier:
    """FeishuNotifier 桩测试"""

    def test_send_logs(self):
        """send() 返回 True（桩通过 structlog 记录）。"""
        notifier = FeishuNotifier()
        result = notifier.send("测试推送内容")

        assert result is True

    def test_channel_name(self):
        """channel_name 正确。"""
        notifier = FeishuNotifier()
        assert notifier.channel_name == "feishu"

    def test_health_check(self):
        """health_check 默认返回 True。"""
        notifier = FeishuNotifier()
        assert notifier.health_check() is True


class TestEmailNotifier:
    """EmailNotifier 桩测试"""

    def test_send_logs(self):
        """send() 返回 True（桩通过 structlog 记录）。"""
        notifier = EmailNotifier()
        result = notifier.send("邮件内容")

        assert result is True

    def test_channel_name(self):
        """channel_name 正确。"""
        notifier = EmailNotifier()
        assert notifier.channel_name == "email"

    def test_health_check(self):
        """health_check 默认返回 True。"""
        notifier = EmailNotifier()
        assert notifier.health_check() is True
