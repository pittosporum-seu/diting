"""谛听 · 统一评分→评级映射

P0-2: 全局唯一的 score_to_rating() 函数，消除 8 处重复的 _to_rating/_score_to_rating。

6 档阈值：STRONG_BUY(≥80) / BUY(≥65) / ACCUMULATE(≥50) / HOLD(≥35) / REDUCE(≥20) / SELL(<20)
"""

from __future__ import annotations

from ..enums import Rating

# 6 档阈值常量（从高到低排列）
_THRESHOLDS = (80, 65, 50, 35, 20)


def score_to_rating(score: float) -> Rating:
    """评分 → 评级映射（6 档）。

    全局唯一映射函数，所有引擎和 Web 层统一使用。

    Args:
        score: 0-100 的评分（调用方负责钳制）

    Returns:
        对应的 Rating 枚举值
    """
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
