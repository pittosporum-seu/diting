"""Deterministic training-statistic builder for the mean-reversion candidate."""

from __future__ import annotations

import math

from ..enums import FactorFamily
from ..infra.errors import AnalysisError
from ..schema import (
    ExperimentFactor,
    FactorCorrelation,
    FactorTrainingStatistic,
    RankingStrategyDefinition,
)

MAX_FACTOR_WEIGHT = 0.35
CORRELATION_LIMIT = 0.70

_FAMILIES = tuple(family.value for family in FactorFamily)
_SPECS = {
    FactorFamily.PRICE_VS_MA.value: ("close / mean(close, 20) - 1",),
    FactorFamily.RETURN.value: ("close / lag(close, 20) - 1",),
    FactorFamily.VOLATILITY.value: ("std(pct_change(close), 20)",),
    FactorFamily.RSI.value: ("RSI(close, 14)",),
    FactorFamily.VOLUME_RATIO.value: ("volume / mean(volume, 20)",),
    FactorFamily.BOLLINGER.value: ("(close - mean(close, 20)) / (2 * std(close, 20))",),
}


class MeanReversionCandidateBuilder:
    """Prune correlated factors and derive bounded weights from training IC_IR only."""

    def build(
        self,
        statistics: tuple[FactorTrainingStatistic, ...],
        correlations: tuple[FactorCorrelation, ...],
        *,
        factor_version: str,
    ) -> RankingStrategyDefinition:
        if not factor_version:
            raise AnalysisError(
                "factor version is required",
                error_code="FACTOR_VERSION_REQUIRED",
                http_status_code=422,
            )
        stats = self._validate_statistics(statistics)
        matrix = self._validate_correlations(correlations)
        retained = set(_FAMILIES)
        ordered_pairs = sorted(
            matrix.items(),
            key=lambda item: (-abs(item[1]), item[0]),
        )
        family_order = {name: index for index, name in enumerate(_FAMILIES)}
        for (left, right), correlation in ordered_pairs:
            if (
                abs(correlation) <= CORRELATION_LIMIT
                or left not in retained
                or right not in retained
            ):
                continue
            left_strength = abs(stats[left].ic_ir)
            right_strength = abs(stats[right].ic_ir)
            if left_strength == right_strength:
                loser = right if family_order[left] < family_order[right] else left
            else:
                loser = left if left_strength < right_strength else right
            retained.remove(loser)

        if len(retained) < 3:
            raise AnalysisError(
                "correlation pruning left fewer than three production factors",
                error_code="INSUFFICIENT_INDEPENDENT_FACTORS",
                http_status_code=422,
            )
        weights = _bounded_weights({name: abs(stats[name].ic_ir) for name in retained})
        factors = tuple(
            ExperimentFactor(
                name=name,
                formula=_SPECS[name][0],
                direction=1 if stats[name].ic_ir > 0 else -1,
                normalization="cross_sectional_rank",
                missing_value_policy="exclude_period_asset",
                training_ic_ir=stats[name].ic_ir,
                weight=weights[name],
            )
            for name in _FAMILIES
            if name in retained
        )
        return RankingStrategyDefinition(factor_version=factor_version, factors=factors)

    @staticmethod
    def _validate_statistics(
        statistics: tuple[FactorTrainingStatistic, ...],
    ) -> dict[str, FactorTrainingStatistic]:
        stats = {item.name: item for item in statistics}
        if set(stats) != set(_FAMILIES) or len(stats) != len(statistics):
            raise AnalysisError(
                "training statistics must contain each approved factor family exactly once",
                error_code="INVALID_FACTOR_POOL",
                http_status_code=422,
            )
        if any(
            not math.isfinite(item.rank_ic) or not math.isfinite(item.ic_ir) or item.ic_ir == 0
            for item in statistics
        ):
            raise AnalysisError(
                "training factor statistics must be finite with non-zero IC_IR",
                error_code="INVALID_TRAINING_STATISTICS",
                http_status_code=422,
            )
        return stats

    @staticmethod
    def _validate_correlations(
        correlations: tuple[FactorCorrelation, ...],
    ) -> dict[tuple[str, str], float]:
        expected = {
            tuple(sorted((left, right)))
            for index, left in enumerate(_FAMILIES)
            for right in _FAMILIES[index + 1 :]
        }
        matrix: dict[tuple[str, str], float] = {}
        for item in correlations:
            pair = tuple(sorted((item.left, item.right)))
            if (
                item.left == item.right
                or item.left not in _FAMILIES
                or item.right not in _FAMILIES
                or pair in matrix
                or not math.isfinite(item.correlation)
                or abs(item.correlation) > 1
            ):
                raise AnalysisError(
                    "training correlation matrix is invalid",
                    error_code="INVALID_FACTOR_CORRELATION",
                    http_status_code=422,
                )
            matrix[pair] = item.correlation
        if set(matrix) != expected:
            raise AnalysisError(
                "training correlation matrix is incomplete",
                error_code="INCOMPLETE_FACTOR_CORRELATION",
                http_status_code=422,
            )
        return matrix


def _bounded_weights(raw: dict[str, float]) -> dict[str, float]:
    remaining = set(raw)
    weights: dict[str, float] = {}
    remaining_mass = 1.0
    while remaining:
        total = sum(raw[name] for name in remaining)
        proposed = {name: remaining_mass * raw[name] / total for name in sorted(remaining)}
        capped = {name for name, value in proposed.items() if value > MAX_FACTOR_WEIGHT}
        if not capped:
            weights.update(proposed)
            break
        for name in capped:
            weights[name] = MAX_FACTOR_WEIGHT
            remaining.remove(name)
            remaining_mass -= MAX_FACTOR_WEIGHT
        if remaining_mass < 0 or not remaining:
            raise AnalysisError(
                "factor weights cannot satisfy the production cap",
                error_code="FACTOR_WEIGHT_CAP_UNSATISFIABLE",
                http_status_code=422,
            )
    residual = 1.0 - sum(weights.values())
    if abs(residual) > 1e-12:
        adjustable = max(
            (name for name, value in weights.items() if value < MAX_FACTOR_WEIGHT),
            key=lambda name: weights[name],
        )
        weights[adjustable] += residual
    return weights
