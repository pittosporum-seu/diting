"""谛听 · 多引擎共识融合"""


from ..engines.rating import score_to_rating
from ..infra.config_loader import ConfigLoader
from ..infra.logging_config import get_logger
from ..schema import AnalysisResult, Conflict, ConsensusScore, Rating

logger = get_logger(__name__)


class ConsensusEngine:
    """多引擎评分融合 —— 加权平均 + 冲突检测"""

    def __init__(self, weights: dict[str, float] | None = None):
        cfg = ConfigLoader.get_section("engines")
        self._weights = weights or cfg.get("weights", {})

    def fuse(self, symbol: str, results: list[AnalysisResult]) -> ConsensusScore:
        """融合多个引擎的评分。

        Args:
            symbol: 股票代码
            results: 各引擎的分析结果

        Returns:
            共识评分
        """
        if not results:
            logger.warning(
                "consensus.default_fallback",
                symbol=symbol,
                reason="no_results",
                default_score=50,
            )
            return ConsensusScore(symbol=symbol, weighted_score=50, rating=Rating.HOLD)

        engine_names = []
        failed_names = []
        total_weight = 0.0
        weighted_sum = 0.0

        for r in results:
            if r.error:
                failed_names.append(r.engine_name)
                continue
            w = self._weights.get(r.engine_name, 1.0)
            weighted_sum += r.score * w
            total_weight += w
            engine_names.append(r.engine_name)

        if total_weight == 0:
            logger.warning(
                "consensus.default_fallback",
                symbol=symbol,
                reason="no_successful_results",
                failed_engines=failed_names,
                default_score=50,
            )
            return ConsensusScore(
                symbol=symbol, weighted_score=50, rating=Rating.HOLD,
                engines_used=tuple(engine_names), engines_failed=tuple(failed_names),
            )

        score = weighted_sum / total_weight
        rating = self._score_to_rating(score)
        confidence = min(1.0, len(engine_names) / max(1, len(results)))

        # 冲突检测
        self._detect_conflicts(results)

        return ConsensusScore(
            symbol=symbol,
            weighted_score=round(score, 1),
            rating=rating,
            engines_used=tuple(engine_names),
            engines_failed=tuple(failed_names),
            confidence=round(confidence, 2),
        )

    @staticmethod
    def _detect_conflicts(results: list[AnalysisResult]) -> list[Conflict]:
        """检测引擎间的评级冲突"""
        rank = {"strong_buy": 5, "buy": 4, "accumulate": 3, "hold": 2, "reduce": 1, "sell": 0}
        conflicts = []
        ratings = {r.engine_name: r.rating for r in results if not r.error}
        names = list(ratings.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                ra, rb = ratings[a], ratings[b]
                diff = abs(rank.get(ra.value, 3) - rank.get(rb.value, 3))
                if diff >= 3:
                    severity = "severe" if diff >= 4 else "moderate"
                    conflicts.append(
                        Conflict(
                            engine_a=a, engine_b=b,
                            a_rating=ra, b_rating=rb,
                            severity=severity,
                        )
                    )
        return conflicts

    @staticmethod
    def _score_to_rating(score: float) -> Rating:
        try:
            cfg = ConfigLoader.get_section("engines")
            thresholds = cfg.get("scoring", {}).get("threshold", [80, 65, 50, 35, 20])
        except Exception:
            # 配置不可用时回退到统一函数
            return score_to_rating(score)
        s0, s1, s2, s3, s4 = (
            thresholds[0], thresholds[1], thresholds[2], thresholds[3], thresholds[4]
        )
        if score >= s0:
            return Rating.STRONG_BUY
        if score >= s1:
            return Rating.BUY
        if score >= s2:
            return Rating.ACCUMULATE
        if score >= s3:
            return Rating.HOLD
        if score >= s4:
            return Rating.REDUCE
        return Rating.SELL
