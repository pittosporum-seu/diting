"""谛听 · AI 引擎输出协议 — AiEngineOutput dataclass

所有 AI 驱动引擎（buffett, wyckoff, can_slim）的沙箱输出统一为此协议。
AiOutputParser 解析后返回此类型的实例。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..enums import Rating


@dataclass
class AiEngineOutput:
    """AI 引擎沙箱输出标准协议。

    所有 AI 引擎的沙箱输出经 AiOutputParser 解析后统一为此格式。
    引擎特有的字段（如 moat_score, phase, c_score 等）放入 metadata。
    """

    score: float
    """综合评分，0-100"""

    rating: Rating = Rating.HOLD
    """统一评级，由 score_to_rating 计算"""

    narrative: str = ""
    """中文分析解读"""

    signals: list[str] = field(default_factory=list)
    """检测到的技术信号（如 spring_detected, sos_detected）"""

    risks: list[str] = field(default_factory=list)
    """风险/警告列表"""

    bull_reasons: list[str] = field(default_factory=list)
    """结构化看多理由"""

    bear_reasons: list[str] = field(default_factory=list)
    """结构化看空理由"""

    confidence: float = 0.5
    """分析置信度，0-1"""

    metadata: dict = field(default_factory=dict)
    """引擎特有字段（如 moat_score, phase, c_score, support_level 等）"""
