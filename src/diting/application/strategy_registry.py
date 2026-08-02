"""Strict lifecycle service for versioned production strategies."""

from __future__ import annotations

from ..enums import StrategyState
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
