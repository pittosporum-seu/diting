"""Deterministic factor selection and weight construction tests."""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest

from src.diting.enums import FactorFamily
from src.diting.infra.errors import AnalysisError
from src.diting.research.mean_reversion_v1 import MeanReversionCandidateBuilder
from src.diting.schema import FactorCorrelation, FactorTrainingStatistic

FAMILIES = tuple(family.value for family in FactorFamily)


def _statistics(**overrides: float) -> tuple[FactorTrainingStatistic, ...]:
    defaults = {
        "price_vs_ma": -0.60,
        "ret": -0.50,
        "volatility": -0.40,
        "rsi": -0.80,
        "volume_ratio": -0.30,
        "bollinger": -0.20,
    }
    defaults.update(overrides)
    return tuple(
        FactorTrainingStatistic(name=name, rank_ic=value / 10, ic_ir=value)
        for name, value in defaults.items()
    )


def _correlations(**overrides: float) -> tuple[FactorCorrelation, ...]:
    values = {tuple(sorted(pair)): 0.1 for pair in itertools.combinations(FAMILIES, 2)}
    for key, value in overrides.items():
        left, right = key.split("__")
        values[tuple(sorted((left, right)))] = value
    return tuple(
        FactorCorrelation(left=left, right=right, correlation=value)
        for (left, right), value in sorted(values.items())
    )


def test_candidate_uses_only_approved_training_factors_and_bounded_weights() -> None:
    definition = MeanReversionCandidateBuilder().build(
        _statistics(rsi=-10.0),
        _correlations(),
        factor_version="mean-reversion-factors-v1",
    )

    assert tuple(factor.name for factor in definition.factors) == FAMILIES
    assert all(factor.direction == -1 for factor in definition.factors)
    assert all(factor.normalization == "cross_sectional_rank" for factor in definition.factors)
    assert all(
        factor.missing_value_policy == "exclude_period_asset" for factor in definition.factors
    )
    assert math.isclose(sum(factor.weight for factor in definition.factors), 1.0)
    assert max(factor.weight for factor in definition.factors) == 0.35


def test_high_correlation_removes_the_lower_training_ic_ir_factor() -> None:
    definition = MeanReversionCandidateBuilder().build(
        _statistics(price_vs_ma=-0.60, rsi=-0.80),
        _correlations(price_vs_ma__rsi=0.71),
        factor_version="mean-reversion-factors-v1",
    )
    names = {factor.name for factor in definition.factors}

    assert "rsi" in names
    assert "price_vs_ma" not in names
    assert len(names) == 5
    assert math.isclose(sum(factor.weight for factor in definition.factors), 1.0)


def test_correlation_boundary_is_strictly_greater_than_point_seven() -> None:
    definition = MeanReversionCandidateBuilder().build(
        _statistics(),
        _correlations(price_vs_ma__rsi=-0.70),
        factor_version="mean-reversion-factors-v1",
    )

    assert {factor.name for factor in definition.factors} == set(FAMILIES)


def test_incomplete_factor_pool_or_correlation_matrix_is_rejected() -> None:
    builder = MeanReversionCandidateBuilder()
    with pytest.raises(AnalysisError) as missing_factor:
        builder.build(
            _statistics()[:-1],
            _correlations(),
            factor_version="mean-reversion-factors-v1",
        )
    with pytest.raises(AnalysisError) as missing_correlation:
        builder.build(
            _statistics(),
            _correlations()[:-1],
            factor_version="mean-reversion-factors-v1",
        )

    assert missing_factor.value.error_code == "INVALID_FACTOR_POOL"
    assert missing_correlation.value.error_code == "INCOMPLETE_FACTOR_CORRELATION"


def test_candidate_source_has_no_legacy_or_context_only_ranking_factor() -> None:
    import src.diting.research.mean_reversion_v1 as module

    module_path = Path(module.__file__)
    source = module_path.read_text(encoding="utf-8").lower()
    production_source = "\n".join(
        path.read_text(encoding="utf-8") for path in module_path.parents[1].rglob("*.py")
    )

    assert "dist_high_20" not in production_source
    assert "vmd" not in source
