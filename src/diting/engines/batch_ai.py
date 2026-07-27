"""谛听 · 批量 AI 分析层

wyckoff + can_slim 引擎的批量直出 JSON 范式：一次 AI 调用分析整批股票
（替代旧的"逐只代码生成 + 沙箱执行"），大幅提速并去除沙箱脆弱性。

- 深度分析：batch-of-N（N 只一次调用，提速核心）
- 单股详情：batch-of-1（同样走直出 JSON，不再写代码跑沙箱）

关键：mimo-v2.5 是推理模型，reasoning_content 与 content 共用 max_tokens，
必须给足额度（131072），否则思考耗尽额度导致 content 为空。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from ..ai.client import AIClient, get_llm
from ..enums import Signal
from ..infra.logging_config import get_logger
from ..schema import AnalysisResult
from .rating import score_to_rating

if TYPE_CHECKING:
    from ..web.services.stock import StockService

logger = get_logger(__name__)

# 推理模型需大 max_tokens（reasoning_content 与 content 共用额度）
MAX_TOKENS = 131072
VERSION = "2.0.0"
_MAX_RETRIES = 2  # 空响应/解析失败重试次数

# ── 验证过的提示词（v1，质量达标：narrative 含数字、分数有区分、子分数齐全）──
PROMPTS = {
    "wyckoff": (
        "你是威克夫(Wyckoff)市场周期分析专家。根据每只股票的价格与成交量数据判断其所处周期阶段并评分。\n"
        "评分基准：吸筹A停止下跌=25|B横盘筑底=40|C弹簧Spring=60|D突破上涨=78|E上升趋势=88；"
        "派发A停止上涨=30|B横盘滞涨=24|C上冲回落=18|D破位下跌=12|E下降趋势=8。\n"
        "判断要点：现价在区间中的位置、近20日走势方向、是否放量突破/跌破。Spring=短暂跌破支撑后快速收回。\n"
        '每只输出 {"code","phase","score":整数,"support":数字,"resistance":数字,'
        '"spring":bool,"narrative":"30-50字,必须引用具体价位和走势"}\n'
        'narrative示例:"现价102.5处区间上沿,近20日+8%放量突破前高101,支撑94.5,Phase D突破确立"。\n'
        "只输出JSON数组,顺序与输入一致,不写代码不解释。"
    ),
    "can_slim": (
        "你是欧奈尔CANSLIM成长股专家。7维度各0-15分,总分0-100：\n"
        "c当季盈利(价格动能推断)|a年度盈利(长期走势推断)|n新高(现价接近区间高点=高分)|"
        "s供需(小市值放量=高分)|l龙头(大市值=高分)|i机构(大市值机构持仓高)|m大盘方向。\n"
        "score=七维之和(0-100)。\n"
        '每只输出 {"code","score","c","a","n","s","l","i","m",'
        '"narrative":"30-50字,必须引用具体数据"}\n'
        "只输出JSON数组,顺序与输入一致,不写代码不解释。"
    ),
}
_CAN_SLIM_SUBKEYS = ["c", "a", "n", "s", "l", "i", "m"]


class BatchAIAnalyzer:
    """批量 AI 分析器：wyckoff + can_slim 直出 JSON。

    用法:
        analyzer = BatchAIAnalyzer(stock_service)
        results = analyzer.analyze(["000001", "600519"], ["wyckoff", "can_slim"])
        # results: {code: [AnalysisResult, ...]}
    """

    def __init__(self, stock_service: StockService, llm: AIClient | None = None):
        self._ss = stock_service
        self._llm = llm or get_llm()

    # ── 富数据摘要 ──────────────────────────────────
    def build_summary(self, code: str) -> str | None:
        """构建单只股票的富数据摘要（价格/估值/量价/趋势）。"""
        try:
            q = self._ss.get_realtime(code)
            hist = self._ss.get_historical(code)
            if hist is None or hist.df is None or len(hist.df) < 30:
                return None
            df = hist.df
            close = df.get("close", df.get("收盘价"))
            if close is None or len(close) < 30:
                return None
            recent = [round(x, 2) for x in close.iloc[-5:].tolist()]
            vol_col = "volume" if "volume" in df.columns else "成交量"
            avg_vol = df[vol_col].mean() if vol_col in df.columns else 0
            chg20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0
            pe = f"{q.pe:.1f}" if q and q.pe else "N/A"
            pb = f"{q.pb:.2f}" if q and q.pb else "N/A"
            mv = f"{q.total_mv / 1e8:.0f}亿" if q and q.total_mv else "N/A"
            name = q.name if q else code
            chg = q.change_pct if q else 0
            return (
                f"[{code} {name}] 现价{close.iloc[-1]:.2f} 涨跌{chg:.1f}% "
                f"PE={pe} PB={pb} 总市值{mv} | {len(close)}日 区间{close.min():.2f}-{close.max():.2f} "
                f"近20日{chg20:+.1f}% 近5日{recent} 均量{avg_vol:.0f}"
            )
        except Exception as e:
            logger.debug("batch_ai.summary_failed", code=code, error=str(e))
            return None

    # ── 核心：批量分析 ──────────────────────────────
    def analyze(
        self, codes: list[str], engine_names: list[str]
    ) -> dict[str, list[AnalysisResult]]:
        """对一批股票批量跑指定 AI 引擎，返回 {code: [AnalysisResult, ...]}。

        每个引擎对整批只做一次 AI 调用。缺摘要的股票跳过。
        """
        summaries: dict[str, str] = {}
        for c in codes:
            s = self.build_summary(c)
            if s:
                summaries[c] = s
        ordered = [summaries[c] for c in codes if c in summaries]
        results: dict[str, list[AnalysisResult]] = {c: [] for c in codes}
        if not ordered:
            return results

        for engine in engine_names:
            if engine not in PROMPTS:
                continue
            items = self._call_batch(engine, ordered)
            for it in items:
                code = str(it.get("code", "")).strip()
                if code in results:
                    results[code].append(self._to_result(engine, code, it))
        return results

    # ── 单次批量调用（带重试）────────────────────────
    def _call_batch(self, engine: str, summaries: list[str]) -> list[dict]:
        prompt = (
            f"下面是{len(summaries)}只股票数据,逐只分析。\n\n"
            + "\n".join(summaries)
            + "\n\n"
            + PROMPTS[engine]
        )
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._llm.complete(
                    system="你只输出合法JSON数组。",
                    user=prompt,
                    max_tokens=MAX_TOKENS,
                )
                arr = self._extract_json_array(resp)
                if isinstance(arr, list) and arr:
                    return [it for it in arr if isinstance(it, dict)]
                logger.warning(
                    "batch_ai.empty", engine=engine, attempt=attempt, n=len(summaries)
                )
            except Exception as e:
                logger.warning(
                    "batch_ai.call_failed", engine=engine, attempt=attempt, error=str(e)
                )
        return []

    @staticmethod
    def _extract_json_array(text: str):
        """从输出提取 JSON 数组（兼容 ```json 代码块与裸数组）。"""
        if not text:
            return None
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        s, e = text.find("["), text.rfind("]")
        if s != -1 and e != -1:
            return json.loads(text[s : e + 1])
        return None

    # ── JSON 项 → AnalysisResult ────────────────────
    def _to_result(self, engine: str, code: str, it: dict) -> AnalysisResult:
        score = it.get("score")
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 50.0
        score = max(0.0, min(100.0, score))
        narrative = str(it.get("narrative", "") or "")
        confidence = 0.7 if score > 60 or score < 40 else 0.5

        signals: list = []
        metadata: dict = {}
        if engine == "wyckoff":
            metadata = {
                "phase": it.get("phase", "unknown"),
                "support": it.get("support"),
                "resistance": it.get("resistance"),
                "spring": bool(it.get("spring", False)),
            }
            if it.get("spring"):
                signals.append(Signal.WYCKOFF_SPRING)
        elif engine == "can_slim":
            for k in _CAN_SLIM_SUBKEYS:
                if isinstance(it.get(k), (int, float)):
                    metadata[k] = it[k]

        return AnalysisResult(
            engine_name=engine,
            engine_version=VERSION,
            symbol=code,
            score=score,
            rating=score_to_rating(score),
            signals=tuple(signals),
            narrative=narrative,
            confidence=confidence,
            metadata=metadata,
        )
