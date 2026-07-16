"""谛听 · AI 引擎输出统一解析器

从 buffett/wyckoff/can_slim 的 _parse_output 提取，统一处理：
1. 从 markdown 代码块或裸文本提取 JSON/Python dict
2. numpy 类型清洗（np.float64 → float, np.int64 → int 等）
3. 构建 AiEngineOutput dataclass

提供 parse() 实例方法和 parse_static() 静态方法。
"""

from __future__ import annotations

import json
import re

from ..engines.rating import score_to_rating
from ..infra.logging_config import get_logger
from .output_schema import AiEngineOutput

logger = get_logger(__name__)


class AiOutputParser:
    """AI 引擎沙箱输出的统一解析器。

    处理三步：
    1. 提取 JSON（从 markdown 代码块或裸文本）
    2. numpy 类型清洗（np.float64 → float, np.int64 → int 等）
    3. 构建 AiEngineOutput dataclass
    """

    # 已知的顶层字段，其余放入 metadata
    _KNOWN_FIELDS = frozenset({
        "score", "narrative", "signals", "risks", "bull_reasons", "bear_reasons",
        "confidence", "rating", "warnings",
    })

    @staticmethod
    def parse(raw: str) -> AiEngineOutput:
        """解析 AI/沙箱输出的结构化结果。

        支持多种格式：
        - 标准 JSON（双引号）
        - Python dict 字面量（单引号）
        - 嵌入在 markdown 或文本中的 JSON/Python dict
        - 含 numpy 类型的输出（np.float64, np.int64 等）

        Args:
            raw: 沙箱原始输出文本

        Returns:
            AiEngineOutput 实例（解析失败时返回默认值 score=50）
        """
        parsed = AiOutputParser._parse_to_dict(raw)
        if not parsed:
            logger.debug("ai_output_parser.empty", raw_preview=raw[:200] if raw else "<empty>")
            return AiEngineOutput(
                score=50.0,
                rating=score_to_rating(50.0),
            )

        return AiOutputParser._dict_to_output(parsed)

    @staticmethod
    def parse_static(raw: str) -> AiEngineOutput:
        """静态方法版本的 parse()，兼容无沙箱场景。

        与 parse() 功能完全一致，供不需要实例化解析器的场景使用。
        """
        return AiOutputParser.parse(raw)

    # ---- 内部方法 ----

    @staticmethod
    def _parse_to_dict(raw: str) -> dict:
        """从原始输出文本中提取并解析为 Python dict。

        处理流程：
        1. 提取 { ... } 块
        2. numpy 类型清洗
        3. json.loads（标准 JSON）
        4. ast.literal_eval 回退（Python dict 字面量）
        """
        if not raw or "{" not in raw:
            return {}

        try:
            json_str = raw[raw.index("{"):raw.rindex("}") + 1]
            # 清洗 numpy 类型：np.float64(44.57) → 44.57, np.False_ → false 等
            json_str = AiOutputParser._clean_numpy(json_str, target="json")
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass

        # 回退：尝试 ast.literal_eval（处理单引号 Python dict）
        try:
            import ast
            json_str = raw[raw.index("{"):raw.rindex("}") + 1]
            # 清洗 numpy 类型：ast.literal_eval 也不识别这些
            json_str = AiOutputParser._clean_numpy(json_str, target="python")
            return ast.literal_eval(json_str)
        except (ValueError, SyntaxError):
            pass

        return {}

    @staticmethod
    def _clean_numpy(text: str, target: str = "json") -> str:
        """清洗文本中的 numpy 类型表示。

        Args:
            text: 含 numpy 类型表示的文本
            target: "json" 替换为 JSON 兼容值，"python" 替换为 Python 字面量

        Returns:
            清洗后的文本
        """
        # np.float64(44.57) → 44.57  (json 和 python 都适用)
        text = re.sub(r'np\.float\d*\(([^)]+)\)', r'\1', text)
        # np.int64(10) → 10
        text = re.sub(r'np\.int\d*\(([^)]+)\)', r'\1', text)
        # np.bool_(True) / np.bool_(False)
        text = re.sub(r'np\.bool_\(([^)]+)\)', r'\1', text)

        if target == "json":
            text = re.sub(r'np\.False_', 'false', text)
            text = re.sub(r'np\.True_', 'true', text)
        else:  # python
            text = re.sub(r'np\.False_', 'False', text)
            text = re.sub(r'np\.True_', 'True', text)

        return text

    @staticmethod
    def _dict_to_output(parsed: dict) -> AiEngineOutput:
        """将解析后的 dict 映射为 AiEngineOutput。

        已知字段映射到对应属性，剩余字段放入 metadata。
        """
        # 提取已知字段（用 pop 避免重复出现在 metadata 中）
        score = max(0.0, min(100.0, float(parsed.pop("score", 50))))
        narrative = str(parsed.pop("narrative", ""))
        confidence = float(parsed.pop("confidence", 0.5))

        # signals: 统一转为 list[str]
        signals = parsed.pop("signals", [])
        if isinstance(signals, str):
            signals = [signals]
        elif not isinstance(signals, list):
            signals = []
        signals = [str(s) for s in signals]

        # risks: 统一转为 list[str]，同时处理 buffett 的 "warnings" 兼容
        risks = parsed.pop("risks", [])
        if not risks and "warnings" in parsed:
            risks = parsed.pop("warnings", [])
        if isinstance(risks, str):
            risks = [risks]
        elif not isinstance(risks, list):
            risks = []
        risks = [str(r) for r in risks]

        def _reason_list(field_name: str) -> list[str]:
            reasons = parsed.pop(field_name, [])
            if isinstance(reasons, str):
                reasons = [reasons]
            elif not isinstance(reasons, list):
                reasons = []
            return [str(reason) for reason in reasons]

        bull_reasons = _reason_list("bull_reasons")
        bear_reasons = _reason_list("bear_reasons")

        # 已消费的字段从剩余中移除
        parsed.pop("rating", None)

        # 计算评级
        rating = score_to_rating(score)

        return AiEngineOutput(
            score=score,
            rating=rating,
            narrative=narrative,
            signals=signals,
            risks=risks,
            bull_reasons=bull_reasons,
            bear_reasons=bear_reasons,
            confidence=confidence,
            metadata=parsed,  # 引擎特有字段
        )
