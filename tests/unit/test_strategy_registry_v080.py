"""Strategy registry lifecycle and atomic activation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.diting.application.strategy_registry import StrategyRegistry
from src.diting.enums import StrategyState
from src.diting.infra.errors import AnalysisError
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.schema import ExperimentFactor, RankingStrategyDefinition, StrategyVersion

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW


def _registry(tmp_path: Path) -> tuple[StrategyRegistry, SQLiteDurableStore]:
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    return StrategyRegistry(store, FakeClock()), store


def _draft(version: str) -> StrategyVersion:
    return StrategyVersion(
        name="mean_reversion_v1",
        version=version,
        state=StrategyState.DRAFT,
        manifest_hash=f"manifest-{version}",
        created_at=NOW,
        definition=_definition(),
    )


def _definition() -> RankingStrategyDefinition:
    factors = (
        ExperimentFactor(
            name="ret",
            formula="return",
            direction=-1,
            normalization="cross_sectional_rank",
            missing_value_policy="exclude_period_asset",
            training_ic_ir=-0.6,
            weight=0.34,
        ),
        ExperimentFactor(
            name="rsi",
            formula="rsi",
            direction=-1,
            normalization="cross_sectional_rank",
            missing_value_policy="exclude_period_asset",
            training_ic_ir=-0.5,
            weight=0.33,
        ),
        ExperimentFactor(
            name="bollinger",
            formula="bollinger",
            direction=-1,
            normalization="cross_sectional_rank",
            missing_value_policy="exclude_period_asset",
            training_ic_ir=-0.4,
            weight=0.33,
        ),
    )
    return RankingStrategyDefinition("factor-v1", factors)


def test_lifecycle_is_strict_and_activation_retires_previous_version(tmp_path: Path) -> None:
    registry, store = _registry(tmp_path)
    registry.register(_draft("1.0.0"))
    assert store.transition_strategy(
        "mean_reversion_v1",
        "1.0.0",
        StrategyState.DRAFT,
        StrategyState.VALIDATED,
    )
    assert registry.approve("mean_reversion_v1", "1.0.0").state is StrategyState.APPROVED
    assert registry.activate("mean_reversion_v1", "1.0.0").state is StrategyState.ACTIVE

    registry.register(_draft("1.1.0"))
    assert store.transition_strategy(
        "mean_reversion_v1",
        "1.1.0",
        StrategyState.DRAFT,
        StrategyState.VALIDATED,
    )
    registry.approve("mean_reversion_v1", "1.1.0")
    active = registry.activate("mean_reversion_v1", "1.1.0")

    assert active.activated_at == NOW
    assert store.get_active_strategy("mean_reversion_v1") == active
    first = registry.get("mean_reversion_v1", "1.0.0")
    assert first is not None and first.state is StrategyState.RETIRED
    assert [item.state for item in registry.list("mean_reversion_v1")] == [
        StrategyState.RETIRED,
        StrategyState.ACTIVE,
    ]


def test_versions_cannot_skip_or_reverse_lifecycle_states(tmp_path: Path) -> None:
    registry, store = _registry(tmp_path)
    registry.register(_draft("1.0.0"))

    with pytest.raises(AnalysisError, match="expected validated") as exc_info:
        registry.approve("mean_reversion_v1", "1.0.0")
    assert exc_info.value.error_code == "STRATEGY_STATE_CONFLICT"

    assert registry.get("mean_reversion_v1", "1.0.0").state is StrategyState.DRAFT
    store.transition_strategy(
        "mean_reversion_v1",
        "1.0.0",
        StrategyState.DRAFT,
        StrategyState.VALIDATED,
    )
    registry.approve("mean_reversion_v1", "1.0.0")
    registry.activate("mean_reversion_v1", "1.0.0")
    retired = registry.retire("mean_reversion_v1", "1.0.0")
    assert retired.state is StrategyState.RETIRED

    with pytest.raises(AnalysisError) as reverse:
        registry.activate("mean_reversion_v1", "1.0.0")
    assert reverse.value.error_code == "STRATEGY_STATE_CONFLICT"


def test_registration_is_draft_only_and_version_immutable(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    registry.register(_draft("1.0.0"))

    with pytest.raises(AnalysisError) as duplicate:
        registry.register(_draft("1.0.0"))
    assert duplicate.value.error_code == "STRATEGY_VERSION_EXISTS"

    invalid = StrategyVersion(
        name="mean_reversion_v1",
        version="2.0.0",
        state=StrategyState.APPROVED,
        manifest_hash="manifest-2",
        created_at=NOW,
    )
    with pytest.raises(AnalysisError) as non_draft:
        registry.register(invalid)
    assert non_draft.value.error_code == "STRATEGY_REGISTRATION_INVALID"


def test_draft_cannot_be_validated_without_its_persisted_manifest(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    registry.register(_draft("1.0.0"))

    with pytest.raises(AnalysisError) as missing_manifest:
        registry.mark_validated("mean_reversion_v1", "1.0.0")

    assert missing_manifest.value.error_code == "STRATEGY_MANIFEST_REQUIRED"


def test_approved_strategy_with_invalid_factor_definition_cannot_activate(tmp_path: Path) -> None:
    registry, store = _registry(tmp_path)
    registry.register(replace(_draft("1.0.0"), definition=None))
    assert store.transition_strategy(
        "mean_reversion_v1",
        "1.0.0",
        StrategyState.DRAFT,
        StrategyState.VALIDATED,
    )
    registry.approve("mean_reversion_v1", "1.0.0")

    with pytest.raises(AnalysisError) as invalid:
        registry.activate("mean_reversion_v1", "1.0.0")

    assert invalid.value.error_code == "STRATEGY_DEFINITION_INVALID"
