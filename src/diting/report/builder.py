"""谛听 · HTML 报告构建器

输入 PipelineResult，输出单页 HTML 报告。
支持 L1（简洁）和 L2（深度）两种模板。
"""

from __future__ import annotations

import os
from datetime import datetime

from ..infra.config_loader import ConfigLoader
from ..infra.logging_config import get_logger
from ..pipeline.consensus import ConsensusEngine
from ..schema import AnalysisResult, PipelineResult, Rating
from .echarts import EChartsBuilder

logger = get_logger(__name__)

RATING_LABELS: dict[Rating, str] = {
    Rating.STRONG_BUY: "强烈买入",
    Rating.BUY: "买入",
    Rating.ACCUMULATE: "增持",
    Rating.HOLD: "持有",
    Rating.REDUCE: "减持",
    Rating.SELL: "卖出",
}


class ReportBuilder:
    """HTML 报告构建器。

    从 PipelineResult 提取分析结果，结合可选的图表数据，
    生成 L1 或 L2 级单页 HTML 报告。

    用法:
        builder = ReportBuilder(level="L2")
        html = builder.build(pipeline_result, chart_data=chart_data)
        builder.save(html, "output/report.html")
    """

    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
    ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
    ECHARTS_FILE = os.path.join(ASSETS_DIR, "echarts.min.js")

    def __init__(self, level: str | None = None) -> None:
        report_cfg = ConfigLoader.get_section("report")
        self._level = level or report_cfg.get("level", "L1")
        self._theme = report_cfg.get("theme", "light")
        if self._level not in ("L1", "L2"):
            raise ValueError(f"不支持的报告级别: {self._level}，请使用 L1 或 L2")
        self._consensus = ConsensusEngine()

    # ── 公开 API ──────────────────────────────────────

    def build(
        self,
        result: PipelineResult,
        chart_data: dict | None = None,
    ) -> str:
        """构建完整 HTML 报告。

        Args:
            result: 管道执行结果
            chart_data: 可选图表数据，格式为
                {symbol: {name, dates, prices, rsi_values, ma_5, ma_20,
                          boll_upper, boll_lower, realtime_price, change_pct}}

        Returns:
            完整的 HTML 字符串
        """
        if chart_data is None:
            chart_data = {}

        template = self._load_template(self._level)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        if self._level == "L1":
            html = self._build_l1(result, chart_data, template, timestamp)
        else:
            html = self._build_l2(result, chart_data, template, timestamp)

        logger.info(
            "report.built",
            level=self._level,
            symbols=len(result.symbols),
            size_bytes=len(html),
        )
        return html

    def save(self, html: str, path: str) -> None:
        """保存 HTML 报告到文件。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("report.saved", path=path)

    # ── L1 构建 ───────────────────────────────────────

    def _build_l1(
        self,
        result: PipelineResult,
        chart_data: dict,
        template: str,
        timestamp: str,
    ) -> str:
        symbols_cards = ""
        all_engine_results: list[AnalysisResult] = []

        for symbol in result.symbols:
            results_list = result.results.get(symbol, [])
            all_engine_results.extend(results_list)
            cd = chart_data.get(symbol, {})
            symbols_cards += self._build_symbol_card(symbol, results_list, cd)

        consensus_chart = self._build_consensus_chart(result, all_engine_results)

        return (
            template.replace("{{TITLE}}", "标准分析报告")
            .replace("{{TIMESTAMP}}", timestamp)
            .replace("{{SYMBOLS_CARDS}}", symbols_cards)
            .replace("{{CONSENSUS_CHART}}", consensus_chart)
        )

    # ── L2 构建 ───────────────────────────────────────

    def _build_l2(
        self,
        result: PipelineResult,
        chart_data: dict,
        template: str,
        timestamp: str,
    ) -> str:
        overview = self._build_overview_stats(result)
        symbols_detail = ""
        all_risks: list[tuple[str, str]] = []
        all_engine_results: list[AnalysisResult] = []

        for symbol in result.symbols:
            results_list = result.results.get(symbol, [])
            all_engine_results.extend(results_list)
            cd = chart_data.get(symbol, {})
            symbols_detail += self._build_symbol_detail(symbol, results_list, cd)

            # 收集风险
            for r in results_list:
                for risk in r.risks:
                    all_risks.append((symbol, str(risk)))

        holdings_chart = self._build_holdings_chart(chart_data)
        risk_list = self._build_risk_list(all_risks)
        conclusion = self._build_conclusion(all_engine_results)

        return (
            template.replace("{{TITLE}}", "深度分析报告")
            .replace("{{TIMESTAMP}}", timestamp)
            .replace("{{OVERVIEW_STATS}}", overview)
            .replace("{{SYMBOLS_DETAIL}}", symbols_detail)
            .replace("{{HOLDINGS_CHART}}", holdings_chart)
            .replace("{{RISK_LIST}}", risk_list)
            .replace("{{CONCLUSION}}", conclusion)
        )

    # ── 组件构建 ──────────────────────────────────────

    def _build_symbol_card(
        self,
        symbol: str,
        results: list[AnalysisResult],
        cd: dict,
    ) -> str:
        """L1 股票摘要卡片。"""
        name = cd.get("name", symbol)
        price = cd.get("realtime_price")
        change_pct = cd.get("change_pct")

        # 平均评分
        scores = [r.score for r in results if not r.error]
        avg_score = sum(scores) / len(scores) if scores else 0
        avg_rating = self._score_to_rating(avg_score)

        # 收集风险和解读
        all_risks: list[str] = []
        narratives: list[str] = []
        for r in results:
            if r.error:
                continue
            all_risks.extend(str(risk) for risk in r.risks)
            if r.narrative:
                narratives.append(f"[{r.engine_name}] {r.narrative}")

        price_html = ""
        if price is not None:
            change_str = ""
            if change_pct is not None:
                sign = "+" if change_pct >= 0 else ""
                color = "#22c55e" if change_pct >= 0 else "#ef4444"
                change_str = (
                    f' <span style="color:{color}">{sign}{change_pct:.2f}%</span>'
                )
            price_html = (
                f'<div class="meta-row">'
                f"<span>价格: ¥{price:.2f}{change_str}</span>"
                f"</div>"
            )

        risk_html = ""
        if all_risks:
            unique = list(dict.fromkeys(all_risks))[:5]
            risk_html = (
                '<div class="risks">风险: ' + " | ".join(unique) + "</div>"
            )

        narrative_html = ""
        if narratives:
            narrative_html = (
                '<div class="narrative">'
                + "<br>".join(narratives[:3])
                + "</div>"
            )

        rating_val = avg_rating.value
        rating_label = RATING_LABELS.get(avg_rating, rating_val)

        return (
            f'<div class="card">'
            f'<div class="symbol-header">'
            f'<span class="symbol-name">{symbol} {name}</span>'
            f'<span class="badge badge-{rating_val}">{rating_label}</span>'
            f"</div>"
            f"{price_html}"
            f'<div class="score">{avg_score:.0f}分</div>'
            f"{narrative_html}"
            f"{risk_html}"
            f"</div>"
        )

    def _build_symbol_detail(
        self,
        symbol: str,
        results: list[AnalysisResult],
        cd: dict,
    ) -> str:
        """L2 股票详细分析区。"""
        name = cd.get("name", symbol)
        price = cd.get("realtime_price")
        change_pct = cd.get("change_pct")

        # 平均评分
        scores_list = [r.score for r in results if not r.error]
        avg_score = sum(scores_list) / len(scores_list) if scores_list else 0
        avg_rating = self._score_to_rating(avg_score)

        # 价格元信息
        price_html = ""
        if price is not None:
            change_str = ""
            if change_pct is not None:
                sign = "+" if change_pct >= 0 else ""
                color = "#22c55e" if change_pct >= 0 else "#ef4444"
                change_str = (
                    f' <span style="color:{color}">{sign}{change_pct:.2f}%</span>'
                )
            price_html = f"<span>¥{price:.2f}{change_str}</span>"

        rating_val = avg_rating.value
        rating_label = RATING_LABELS.get(avg_rating, rating_val)

        # 价格图
        price_chart = ""
        dates = cd.get("dates", [])
        prices = cd.get("prices", [])
        if dates and prices:
            sid = symbol.replace(".", "_")
            price_chart = EChartsBuilder.render_price_chart(
                f"price_{sid}",
                [str(d) for d in dates[-60:]],
                prices[-60:],
                ma_5=cd.get("ma_5", [])[-60:] if cd.get("ma_5") else None,
                ma_20=cd.get("ma_20", [])[-60:] if cd.get("ma_20") else None,
                boll_upper=cd.get("boll_upper", [])[-60:] if cd.get("boll_upper") else None,
                boll_lower=cd.get("boll_lower", [])[-60:] if cd.get("boll_lower") else None,
            )

        # RSI 图
        rsi_chart = ""
        rsi_vals = cd.get("rsi_values", [])
        if dates and rsi_vals:
            sid = symbol.replace(".", "_")
            rsi_chart = EChartsBuilder.render_rsi_chart(
                f"rsi_{sid}",
                [str(d) for d in dates[-60:]],
                rsi_vals[-60:],
            )

        # 引擎图
        engine_chart = ""
        valid = [r for r in results if not r.error]
        if valid:
            sid = symbol.replace(".", "_")
            engine_chart = EChartsBuilder.render_engine_charts(
                f"radar_{sid}",
                f"bar_{sid}",
                [r.engine_name for r in valid],
                [r.score for r in valid],
                [r.rating.value for r in valid],
            )

        # 风险
        all_risks: list[str] = []
        for r in results:
            all_risks.extend(str(risk) for risk in r.risks)
        risk_html = ""
        if all_risks:
            unique = list(dict.fromkeys(all_risks))[:5]
            risk_html = '<div class="section-title">⚠ 风险</div>'
            for risk in unique:
                risk_html += f'<div class="risk-item">{risk}</div>'

        return (
            f'<div class="card">'
            f'<div class="symbol-header">'
            f'<span class="symbol-name">{symbol} {name}</span>'
            f'<span class="badge badge-{rating_val}">{rating_label}</span>'
            f"</div>"
            f'<div class="meta-row">'
            f"<span>综合评分: {avg_score:.0f}分</span>"
            f"{price_html}"
            f"</div>"
            f"{price_chart}"
            f"{rsi_chart}"
            f"{engine_chart}"
            f"{risk_html}"
            f"</div>"
        )

    def _build_consensus_chart(
        self,
        result: PipelineResult,
        all_results: list[AnalysisResult],
    ) -> str:
        """多引擎共识图表。"""
        valid = [r for r in all_results if not r.error]
        if not valid:
            return "<p style='color:#6b7280;text-align:center;'>无有效引擎结果</p>"

        # 按引擎名聚合评分
        engine_scores: dict[str, list[float]] = {}
        engine_ratings: dict[str, str] = {}
        for r in valid:
            engine_scores.setdefault(r.engine_name, []).append(r.score)
            engine_ratings[r.engine_name] = r.rating.value

        names = list(engine_scores.keys())
        avg_scores = [sum(v) / len(v) for v in engine_scores.values()]
        ratings = [engine_ratings[n] for n in names]

        return EChartsBuilder.render_engine_charts(
            "consensus_radar",
            "consensus_bar",
            names,
            [round(s, 1) for s in avg_scores],
            ratings,
        )

    def _build_holdings_chart(self, chart_data: dict) -> str:
        """持仓概览饼图。"""
        names: list[str] = []
        values: list[float] = []
        pcts: list[float] = []

        for symbol, cd in chart_data.items():
            names.append(f"{symbol} {cd.get('name', symbol)}")
            values.append(cd.get("market_value", 1.0))
            pcts.append(cd.get("change_pct", 0.0))

        if not names:
            return "<p style='color:#6b7280;text-align:center;'>无持仓数据</p>"

        return EChartsBuilder.render_holdings_chart(
            "holdings_pie", names, values, pcts
        )

    def _build_overview_stats(self, result: PipelineResult) -> str:
        """L2 概览统计盒。"""
        total_symbols = len(result.symbols)
        total_engines = 0
        all_results: list[AnalysisResult] = []
        for rlist in result.results.values():
            total_engines += len(rlist)
            all_results.extend(rlist)

        valid = [r for r in all_results if not r.error]
        avg_score = (
            sum(r.score for r in valid) / len(valid) if valid else 0
        )
        strong_buy = sum(1 for r in valid if r.rating == Rating.STRONG_BUY)
        buy = sum(1 for r in valid if r.rating == Rating.BUY)

        return (
            f'<div class="stat-box">'
            f'<div class="num">{total_symbols}</div>'
            f'<div class="label">标的数量</div>'
            f"</div>"
            f'<div class="stat-box">'
            f'<div class="num">{total_engines}</div>'
            f'<div class="label">引擎执行</div>'
            f"</div>"
            f'<div class="stat-box">'
            f'<div class="num">{avg_score:.0f}</div>'
            f'<div class="label">平均评分</div>'
            f"</div>"
            f'<div class="stat-box">'
            f'<div class="num">{strong_buy + buy}</div>'
            f'<div class="label">买入信号</div>'
            f"</div>"
        )

    def _build_risk_list(self, risks: list[tuple[str, str]]) -> str:
        """风险清单 HTML。"""
        if not risks:
            return "<p style='color:#6b7280;'>暂无显著风险</p>"
        seen = set()
        html = ""
        for symbol, risk in risks:
            key = f"{symbol}:{risk}"
            if key in seen:
                continue
            seen.add(key)
            html += f'<div class="risk-item">{symbol} — {risk}</div>'
        return html

    def _build_conclusion(self, all_results: list[AnalysisResult]) -> str:
        """生成结论文本。"""
        valid = [r for r in all_results if not r.error]
        if not valid:
            return "暂无有效分析结果。"

        avg = sum(r.score for r in valid) / len(valid)
        if avg >= 80:
            grade = "整体评分很高，多个引擎发出强烈买入信号，建议重点关注。"
        elif avg >= 65:
            grade = "整体评分良好，多数引擎看多，可适当配置。"
        elif avg >= 50:
            grade = "整体评分中等，市场方向不明朗，建议观望或轻仓参与。"
        elif avg >= 35:
            grade = "整体评分偏低，多数引擎偏谨慎，建议减仓或回避。"
        else:
            grade = "整体评分较低，多个引擎发出卖出信号，建议离场观望。"

        return f"谛听共运行 {len(valid)} 个引擎，综合评分 {avg:.0f} 分。" + grade

    # ── 工具方法 ──────────────────────────────────────

    def _load_template(self, level: str) -> str:
        """加载 HTML 模板，内联 ECharts 库。"""
        path = os.path.join(self.TEMPLATE_DIR, f"{level.lower()}.html")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"模板文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            html = f.read()

        # 内联 ECharts：用本地文件替换 CDN 引用
        if os.path.isfile(self.ECHARTS_FILE):
            with open(self.ECHARTS_FILE, encoding="utf-8") as f:
                echarts_js = f.read()
            cdn_tag = '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>'
            inline_tag = f"<script>\n{echarts_js}\n</script>"
            html = html.replace(cdn_tag, inline_tag)

        return html

    @staticmethod
    def _score_to_rating(score: float) -> Rating:
        if score >= 80:
            return Rating.STRONG_BUY
        if score >= 65:
            return Rating.BUY
        if score >= 50:
            return Rating.ACCUMULATE
        if score >= 35:
            return Rating.HOLD
        if score >= 20:
            return Rating.REDUCE
        return Rating.SELL
