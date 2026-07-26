"""谛听 · score_to_rating 统一评分映射测试

P0-2: 全档位参数化测试，覆盖所有 Rating 枚举值和边界。
"""

from __future__ import annotations

import pytest

from src.diting.engines.rating import score_to_rating
from src.diting.enums import Rating

# ── 参数化测试用例 ────────────────────────────────────────
# 格式: (score, expected_rating)
_TEST_CASES = [
    # STRONG_BUY: ≥80
    (100, Rating.STRONG_BUY),
    (80, Rating.STRONG_BUY),
    (80.1, Rating.STRONG_BUY),
    # BUY: [65, 80)
    (79.9, Rating.BUY),
    (70, Rating.BUY),
    (65, Rating.BUY),
    # ACCUMULATE: [50, 65)
    (64.9, Rating.ACCUMULATE),
    (57, Rating.ACCUMULATE),
    (50, Rating.ACCUMULATE),
    # HOLD: [35, 50)
    (49.9, Rating.HOLD),
    (42, Rating.HOLD),
    (35, Rating.HOLD),
    # REDUCE: [20, 35)
    (34.9, Rating.REDUCE),
    (27, Rating.REDUCE),
    (20, Rating.REDUCE),
    # SELL: <20
    (19.9, Rating.SELL),
    (10, Rating.SELL),
    (0, Rating.SELL),
    (-5, Rating.SELL),  # 负分也归为 SELL
]


@pytest.mark.parametrize("score,expected", _TEST_CASES)
def test_score_to_rating(score: float, expected: Rating):
    """评分映射：各档位边界正确。"""
    assert score_to_rating(score) == expected, f"score={score} should map to {expected.value}"


def test_all_ratings_covered():
    """确认 6 种 Rating 全部被测试覆盖。"""
    covered = {tc[1] for tc in _TEST_CASES}
    all_ratings = {
        Rating.STRONG_BUY,
        Rating.BUY,
        Rating.ACCUMULATE,
        Rating.HOLD,
        Rating.REDUCE,
        Rating.SELL,
    }
    assert covered == all_ratings, f"Missing ratings: {all_ratings - covered}"
