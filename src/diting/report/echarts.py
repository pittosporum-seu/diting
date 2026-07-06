"""谛听 · ECharts 图表生成

将分析结果转换为 ECharts 图表配置，支持：
- 价格+技术指标叠加图
- RSI 信号图
- 多引擎雷达图
- 持仓概览图

设计要求：iPad 兼容、浅色主题、响应式。
"""

from __future__ import annotations

import json
from typing import Any


class EChartsBuilder:
    """ECharts 图表构建器。

    按需生成各类型图表的 option 字典，调用方负责嵌入 HTML 或渲染。
    """

    # ── 调色盘（浅色主题） ─────────────────────────

    PALETTE = [
        "#3b82f6",  # 蓝
        "#ef4444",  # 红
        "#22c55e",  # 绿
        "#f59e0b",  # 橙
        "#8b5cf6",  # 紫
        "#06b6d4",  # 青
        "#ec4899",  # 粉
        "#84cc16",  # 黄绿
    ]

    GRID_COLOR = "#e5e7eb"
    TEXT_COLOR = "#374151"

    # ── 公共 option 片段 ────────────────────────────

    @staticmethod
    def _tooltip() -> dict:
        return {"trigger": "axis"}

    @staticmethod
    def _legend(bottom: bool = True) -> dict:
        return {
            "bottom": 0 if bottom else None,
            "textStyle": {"fontSize": 11, "color": EChartsBuilder.TEXT_COLOR},
        }

    @staticmethod
    def _xaxis(data: list[str], rotate: int = 0) -> dict:
        return {
            "type": "category",
            "data": data,
            "axisLabel": {
                "rotate": rotate,
                "fontSize": 9,
                "color": EChartsBuilder.TEXT_COLOR,
            },
            "axisLine": {"lineStyle": {"color": EChartsBuilder.GRID_COLOR}},
        }

    @staticmethod
    def _yaxis(
        name: str = "",
        min_val: float | None = None,
        max_val: float | None = None,
        split_line: bool = True,
    ) -> dict:
        axis: dict[str, Any] = {
            "type": "value",
            "name": name,
            "nameTextStyle": {"fontSize": 10, "color": EChartsBuilder.TEXT_COLOR},
        }
        if min_val is not None:
            axis["min"] = min_val
        if max_val is not None:
            axis["max"] = max_val
        if split_line:
            axis["splitLine"] = {"lineStyle": {"color": EChartsBuilder.GRID_COLOR}}
        return axis

    # ── 图表构建 ────────────────────────────────────

    @staticmethod
    def price_with_signals(
        dates: list[str],
        prices: list[float],
        ma_5: list[float] | None = None,
        ma_20: list[float] | None = None,
        boll_upper: list[float] | None = None,
        boll_lower: list[float] | None = None,
    ) -> dict:
        """价格走势 + 均线 + 布林带"""
        series: list[dict] = [
            {
                "name": "收盘价",
                "type": "line",
                "data": prices,
                "lineStyle": {"width": 2, "color": EChartsBuilder.PALETTE[0]},
                "symbol": "none",
            },
        ]
        if ma_5:
            series.append({
                "name": "MA5",
                "type": "line",
                "data": ma_5,
                "lineStyle": {"width": 1, "color": EChartsBuilder.PALETTE[3], "type": "dashed"},
                "symbol": "none",
            })
        if ma_20:
            series.append({
                "name": "MA20",
                "type": "line",
                "data": ma_20,
                "lineStyle": {"width": 1, "color": EChartsBuilder.PALETTE[5], "type": "dashed"},
                "symbol": "none",
            })
        if boll_upper:
            series.append({
                "name": "布林上轨",
                "type": "line",
                "data": boll_upper,
                "lineStyle": {"width": 0.5, "color": "#9ca3af", "type": "dotted"},
                "symbol": "none",
            })
        if boll_lower:
            series.append({
                "name": "布林下轨",
                "type": "line",
                "data": boll_lower,
                "lineStyle": {"width": 0.5, "color": "#9ca3af", "type": "dotted"},
                "symbol": "none",
            })

        return {
            "tooltip": EChartsBuilder._tooltip(),
            "legend": EChartsBuilder._legend(),
            "grid": {"left": 60, "right": 20, "top": 15, "bottom": 35},
            "xAxis": EChartsBuilder._xaxis(dates, rotate=30),
            "yAxis": EChartsBuilder._yaxis("价格"),
            "series": series,
        }

    @staticmethod
    def rsi(
        dates: list[str],
        rsi_values: list[float],
    ) -> dict:
        """RSI 指标图，标注超买/超卖线"""
        return {
            "tooltip": EChartsBuilder._tooltip(),
            "legend": EChartsBuilder._legend(),
            "grid": {"left": 55, "right": 20, "top": 15, "bottom": 35},
            "xAxis": EChartsBuilder._xaxis(dates, rotate=30),
            "yAxis": EChartsBuilder._yaxis("RSI", min_val=0, max_val=100),
            "series": [
                {
                    "name": "RSI(14)",
                    "type": "line",
                    "data": rsi_values,
                    "lineStyle": {"width": 2, "color": EChartsBuilder.PALETTE[3]},
                    "symbol": "none",
                    "markLine": {
                        "silent": True,
                        "symbol": "none",
                        "data": [
                            {
                                "yAxis": 30,
                                "label": {"formatter": "超卖 30", "fontSize": 10},
                                "lineStyle": {"color": "#22c55e", "type": "dashed", "width": 1},
                            },
                            {
                                "yAxis": 70,
                                "label": {"formatter": "超买 70", "fontSize": 10},
                                "lineStyle": {"color": "#ef4444", "type": "dashed", "width": 1},
                            },
                        ],
                    },
                },
            ],
        }

    @staticmethod
    def engine_radar(
        engine_names: list[str],
        scores: list[float],
        max_score: float = 100,
    ) -> dict:
        """多引擎评分雷达图"""
        return {
            "tooltip": {},
            "legend": {"show": False},
            "radar": {
                "indicator": [{"name": n, "max": max_score} for n in engine_names],
                "radius": "65%",
                "axisName": {"fontSize": 11, "color": EChartsBuilder.TEXT_COLOR},
            },
            "series": [
                {
                    "type": "radar",
                    "data": [
                        {
                            "value": scores,
                            "name": "引擎评分",
                            "areaStyle": {"color": "rgba(59, 130, 246, 0.15)"},
                            "lineStyle": {"color": EChartsBuilder.PALETTE[0], "width": 2},
                            "itemStyle": {"color": EChartsBuilder.PALETTE[0]},
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def consensus_bar(
        engines: list[str],
        scores: list[float],
        ratings: list[str],
    ) -> dict:
        """多引擎评分柱状图，按评分着色"""
        color_map = {
            "strong_buy": "#22c55e",
            "buy": "#84cc16",
            "accumulate": "#f59e0b",
            "hold": "#9ca3af",
            "reduce": "#f97316",
            "sell": "#ef4444",
        }

        bar_colors = [color_map.get(r, "#9ca3af") for r in ratings]
        avg = sum(scores) / len(scores) if scores else 0

        return {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 100, "right": 40, "top": 10, "bottom": 20},
            "xAxis": {"type": "value", "max": 100, "axisLabel": {"fontSize": 10}},
            "yAxis": {
                "type": "category",
                "data": engines,
                "axisLabel": {"fontSize": 11, "color": EChartsBuilder.TEXT_COLOR},
            },
            "series": [
                {
                    "name": "评分",
                    "type": "bar",
                    "data": [
                        {"value": scores[i], "itemStyle": {"color": bar_colors[i]}}
                        for i in range(len(scores))
                    ],
                    "label": {
                        "show": True,
                        "position": "right",
                        "fontSize": 10,
                        "formatter": "{c}",
                    },
                    "markLine": {
                        "silent": True,
                        "symbol": "none",
                        "lineStyle": {"color": "#6b7280", "type": "dashed", "width": 1},
                        "label": {"formatter": f"均值 {avg:.0f}", "fontSize": 10},
                        "data": [{"xAxis": avg}],
                    },
                },
            ],
        }

    @staticmethod
    def holdings_summary(
        names: list[str],
        market_values: list[float],
        profit_pcts: list[float],
    ) -> dict:
        """持仓概览：市值占比饼图 + 盈亏瀑布图"""
        pie_colors = [
            "#22c55e" if p >= 0 else "#ef4444" for p in profit_pcts
        ]
        return {
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": EChartsBuilder._legend(),
            "series": [
                {
                    "name": "市值分布",
                    "type": "pie",
                    "radius": ["40%", "70%"],
                    "center": ["50%", "50%"],
                    "data": [
                        {
                            "value": market_values[i],
                            "name": f"{names[i]} ({profit_pcts[i]:+.1f}%)",
                            "itemStyle": {"color": pie_colors[i]},
                        }
                        for i in range(len(names))
                    ],
                    "label": {"fontSize": 10, "color": EChartsBuilder.TEXT_COLOR},
                }
            ],
        }

    # ── HTML 片段生成 ───────────────────────────────

    @staticmethod
    def _wrap_chart(chart_id: str, option: dict, height: str = "320px") -> str:
        """将 ECharts option 包装为独立 JS 代码块"""
        option_js = json.dumps(option, ensure_ascii=False)
        return f"""<div id="{chart_id}" style="width:100%;height:{height};"></div>
<script>
(function() {{
    var chart = echarts.init(document.getElementById('{chart_id}'));
    chart.setOption({option_js});
}})();
</script>"""

    @classmethod
    def render_price_chart(
        cls,
        chart_id: str,
        dates: list[str],
        prices: list[float],
        ma_5: list[float] | None = None,
        ma_20: list[float] | None = None,
        boll_upper: list[float] | None = None,
        boll_lower: list[float] | None = None,
    ) -> str:
        option = cls.price_with_signals(dates, prices, ma_5, ma_20, boll_upper, boll_lower)
        return cls._wrap_chart(chart_id, option)

    @classmethod
    def render_rsi_chart(cls, chart_id: str, dates: list[str], rsi_values: list[float]) -> str:
        option = cls.rsi(dates, rsi_values)
        return cls._wrap_chart(chart_id, option, height="240px")

    @classmethod
    def render_engine_charts(
        cls,
        radar_id: str,
        bar_id: str,
        engine_names: list[str],
        scores: list[float],
        ratings: list[str],
    ) -> str:
        """同时渲染雷达图 + 柱状图"""
        radar = cls._wrap_chart(
            radar_id,
            cls.engine_radar(engine_names, scores),
            height="300px",
        )
        bar = cls._wrap_chart(
            bar_id,
            cls.consensus_bar(engine_names, scores, ratings),
            height=str(max(160, 40 * len(engine_names))) + "px",
        )
        return radar + "\n" + bar

    @classmethod
    def render_holdings_chart(
        cls, chart_id: str, names: list[str], values: list[float], pcts: list[float]
    ) -> str:
        option = cls.holdings_summary(names, values, pcts)
        return cls._wrap_chart(chart_id, option, height="360px")
