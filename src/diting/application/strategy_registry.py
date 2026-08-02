"""Strict lifecycle service for versioned production strategies."""

from __future__ import annotations

import math

from ..enums import FactorFamily, StrategyState
from ..infra.errors import AnalysisError
from ..ports import Clock, DurableStore
from ..schema import StrategyVersion


class StrategyRegistry:
    """Enforce immutable versions and the production activation state machine."""

    def __init__(self, store: DurableStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def register(self, strategy: StrategyVersion) -> StrategyVersion:
        if strategy.state is not StrategyState.DRAFT or strategy.activated_at is not None:
            raise AnalysisError(
                "new strategy versions must start in draft",
                error_code="STRATEGY_REGISTRATION_INVALID",
                http_status_code=422,
            )
        if not self._store.save_strategy(strategy):
            raise AnalysisError(
                "strategy version already exists",
                error_code="STRATEGY_VERSION_EXISTS",
                http_status_code=409,
            )
        return strategy

    def mark_validated(self, name: str, version: str) -> StrategyVersion:
        current = self._require(name, version)
        manifest = self._store.get_experiment_manifest(current.manifest_hash)
        if (
            manifest is None
            or manifest.strategy_name != name
            or manifest.strategy_version != version
        ):
            raise AnalysisError(
                "strategy is not bound to a persisted experiment manifest",
                error_code="STRATEGY_MANIFEST_REQUIRED",
                http_status_code=409,
            )
        return self._transition(name, version, StrategyState.DRAFT, StrategyState.VALIDATED)

    def approve(self, name: str, version: str) -> StrategyVersion:
        return self._transition(name, version, StrategyState.VALIDATED, StrategyState.APPROVED)

    def activate(self, name: str, version: str) -> StrategyVersion:
        current = self._require(name, version)
        if current.state is not StrategyState.APPROVED:
            self._state_conflict(current, StrategyState.APPROVED)
        self._validate_definition(current)
        if not self._store.activate_strategy(name, version, self._clock.now()):
            raise AnalysisError(
                "strategy state changed during activation",
                error_code="STRATEGY_STATE_CONFLICT",
                http_status_code=409,
            )
        return self._require(name, version)

    def retire(self, name: str, version: str) -> StrategyVersion:
        return self._transition(name, version, StrategyState.ACTIVE, StrategyState.RETIRED)

    def get(self, name: str, version: str) -> StrategyVersion | None:
        return self._store.get_strategy(name, version)

    def list(self, name: str | None = None) -> tuple[StrategyVersion, ...]:
        return self._store.list_strategies(name)

    def _transition(
        self,
        name: str,
        version: str,
        expected: StrategyState,
        target: StrategyState,
    ) -> StrategyVersion:
        current = self._require(name, version)
        if current.state is not expected:
            self._state_conflict(current, expected)
        if not self._store.transition_strategy(name, version, expected, target):
            raise AnalysisError(
                "strategy state changed during transition",
                error_code="STRATEGY_STATE_CONFLICT",
                http_status_code=409,
            )
        return self._require(name, version)

    def _require(self, name: str, version: str) -> StrategyVersion:
        strategy = self._store.get_strategy(name, version)
        if strategy is None:
            raise AnalysisError(
                "strategy version not found",
                error_code="STRATEGY_NOT_FOUND",
                http_status_code=404,
            )
        return strategy

    @staticmethod
    def _state_conflict(strategy: StrategyVersion, expected: StrategyState) -> None:
        raise AnalysisError(
            f"strategy is {strategy.state.value}; expected {expected.value}",
            error_code="STRATEGY_STATE_CONFLICT",
            http_status_code=409,
        )

    @staticmethod
    def _validate_definition(strategy: StrategyVersion) -> None:
        definition = strategy.definition
        allowed = {family.value for family in FactorFamily}
        if definition is None:
            _invalid_definition("production factor definition is missing")
        factors = definition.factors
        names = [factor.name for factor in factors]
        weights = [factor.weight for factor in factors]
        valid = (
            bool(definition.factor_version)
            and len(factors) >= 3
            and len(names) == len(set(names))
            and set(names) <= allowed
            and definition.top_n == 20
            and definition.holding_days == 20
            and definition.round_trip_cost_bps == 40
            and all(0 < weight <= 0.35 for weight in weights)
            and math.isclose(sum(weights), 1.0, abs_tol=1e-9)
            and all(
                factor.training_ic_ir != 0
                and factor.direction == (1 if factor.training_ic_ir > 0 else -1)
                and factor.normalization == "cross_sectional_rank"
                and factor.missing_value_policy == "exclude_period_asset"
                for factor in factors
            )
        )
        if not valid:
            _invalid_definition("production factor definition violates mean_reversion_v1 policy")


def _invalid_definition(message: str) -> None:
    raise AnalysisError(
        message,
        error_code="STRATEGY_DEFINITION_INVALID",
        http_status_code=409,
    )
