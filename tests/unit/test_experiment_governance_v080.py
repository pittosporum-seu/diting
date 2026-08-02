"""Fixture-based experiment manifest and promotion gate tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.diting.application.strategy_registry import StrategyRegistry
from src.diting.enums import StrategyState
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.research.governance import ExperimentGovernance, seal_manifest
from src.diting.schema import (
    ExperimentFactor,
    ExperimentManifest,
    ExperimentWindow,
    ValidationMetrics,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
SHA = "a" * 64


class FakeClock:
    def now(self) -> datetime:
        return NOW


def _governance(tmp_path: Path):
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    registry = StrategyRegistry(store, FakeClock())
    return ExperimentGovernance(store, registry), registry, store


def _manifest() -> ExperimentManifest:
    manifest = ExperimentManifest(
        manifest_hash="",
        experiment_id="exp-mean-reversion-001",
        title="A-share medium-horizon mean reversion",
        hypothesis="oversold liquid equities mean-revert over twenty trading days",
        strategy_name="mean_reversion_v1",
        strategy_version="1.0.0",
        code_commit="b3bf737",
        config_hash=SHA,
        universe="point-in-time A-share tradable common stocks",
        asset_types=("stock",),
        exclusion_rules=("ST", "suspended", "listed_under_120_days"),
        includes_listing_dates=True,
        includes_delisting_dates=True,
        survivorship_bias_checked=True,
        data_start=date(2022, 1, 1),
        data_end=date(2026, 7, 31),
        providers=("akshare",),
        provider_trace_hash=SHA,
        gateway_request_hashes=(SHA,),
        adjustment_method="qfq",
        data_snapshot_hash=SHA,
        training_window=ExperimentWindow(date(2022, 1, 1), date(2024, 12, 31)),
        validation_window=ExperimentWindow(date(2025, 1, 1), date(2025, 12, 31)),
        oos_window=ExperimentWindow(date(2026, 1, 1), date(2026, 7, 31)),
        factor_version="mean-reversion-factors-v1",
        factors=(
            ExperimentFactor(
                name="ret",
                formula="close / lag(close, 20) - 1",
                direction=-1,
                normalization="cross_sectional_rank",
                missing_value_policy="exclude_period_asset",
                training_ic_ir=-0.6,
                weight=0.34,
            ),
            ExperimentFactor(
                name="rsi",
                formula="RSI(close, 14)",
                direction=-1,
                normalization="cross_sectional_rank",
                missing_value_policy="exclude_period_asset",
                training_ic_ir=-0.5,
                weight=0.33,
            ),
            ExperimentFactor(
                name="bollinger",
                formula="(close - mean(close, 20)) / (2 * std(close, 20))",
                direction=-1,
                normalization="cross_sectional_rank",
                missing_value_policy="exclude_period_asset",
                training_ic_ir=-0.4,
                weight=0.33,
            ),
        ),
        metrics=ValidationMetrics(
            oos_rank_ic=0.05,
            oos_ic_ir=0.5,
            bootstrap_ic_lower_95=0.001,
            net_excess_return_20d=0.005,
            parameter_sensitivity=0.29,
            data_coverage=0.90,
            minimum_cross_section=500,
            top_n=20,
            holding_days=20,
            round_trip_cost_bps=40,
            annualized_turnover=4.2,
            max_drawdown=-0.12,
            future_data_leakage=False,
        ),
        result_hashes=(("summary.json", SHA),),
        reproduce_command=(
            "uv run python scripts/validate_mean_reversion.py --manifest manifest.json"
        ),
        created_at=NOW,
    )
    return seal_manifest(manifest)


def test_passing_manifest_is_persisted_and_only_promoted_to_validated(tmp_path: Path) -> None:
    governance, registry, store = _governance(tmp_path)
    manifest = _manifest()

    decision = governance.promote_validated(manifest)
    strategy = registry.get("mean_reversion_v1", "1.0.0")

    assert decision.passed is True
    assert all(check.passed for check in decision.checks)
    assert store.get_experiment_manifest(manifest.manifest_hash) == manifest
    assert strategy is not None and strategy.state is StrategyState.VALIDATED
    assert strategy.manifest_hash == manifest.manifest_hash
    assert store.get_active_strategy("mean_reversion_v1") is None


@pytest.mark.parametrize(
    ("field", "value", "failed_code"),
    (
        ("oos_rank_ic", 0.049, "OOS_RANK_IC"),
        ("oos_ic_ir", 0.49, "OOS_IC_IR"),
        ("bootstrap_ic_lower_95", 0.0, "BOOTSTRAP_IC_LOWER"),
        ("net_excess_return_20d", 0.0049, "NET_EXCESS_20D"),
        ("parameter_sensitivity", 0.30, "PARAMETER_SENSITIVITY"),
        ("data_coverage", 0.899, "DATA_COVERAGE"),
        ("minimum_cross_section", 499, "CROSS_SECTION"),
        ("round_trip_cost_bps", 39, "TRADING_COST"),
        ("future_data_leakage", True, "NO_FUTURE_LEAKAGE"),
    ),
)
def test_each_numeric_or_leakage_gate_blocks_promotion(
    tmp_path: Path,
    field: str,
    value,
    failed_code: str,
) -> None:
    governance, registry, store = _governance(tmp_path)
    base = _manifest()
    manifest = seal_manifest(replace(base, metrics=replace(base.metrics, **{field: value})))

    decision = governance.promote_validated(manifest)

    assert decision.passed is False
    assert failed_code in {check.code for check in decision.checks if not check.passed}
    assert store.get_experiment_manifest(manifest.manifest_hash) is None
    assert registry.get("mean_reversion_v1", "1.0.0") is None


def test_fixed_windows_and_canonical_hash_are_mandatory(tmp_path: Path) -> None:
    governance, _, _ = _governance(tmp_path)
    base = _manifest()
    wrong_window = seal_manifest(
        replace(base, oos_window=ExperimentWindow(date(2026, 1, 2), date(2026, 7, 31)))
    )
    tampered = replace(base, hypothesis="changed after sealing")

    window_decision = governance.evaluate(wrong_window)
    tamper_decision = governance.evaluate(tampered)

    assert "OOS_WINDOW" in {check.code for check in window_decision.checks if not check.passed}
    assert "MANIFEST_HASH" in {check.code for check in tamper_decision.checks if not check.passed}


def test_point_in_time_and_gateway_provenance_are_mandatory(tmp_path: Path) -> None:
    governance, _, _ = _governance(tmp_path)
    base = _manifest()
    manifest = seal_manifest(
        replace(
            base,
            includes_delisting_dates=False,
            provider_trace_hash="",
            gateway_request_hashes=(),
        )
    )

    decision = governance.evaluate(manifest)
    failures = {check.code for check in decision.checks if not check.passed}

    assert failures >= {"POINT_IN_TIME_UNIVERSE", "PROVIDER_TRACE", "GATEWAY_REQUESTS"}


def test_invalid_production_factor_weights_block_validation(tmp_path: Path) -> None:
    governance, _, _ = _governance(tmp_path)
    base = _manifest()
    invalid = replace(base.factors[0], weight=0.36)
    manifest = seal_manifest(replace(base, factors=(invalid, *base.factors[1:])))

    decision = governance.evaluate(manifest)

    assert "PRODUCTION_FACTOR_DEFINITION" in {
        check.code for check in decision.checks if not check.passed
    }
