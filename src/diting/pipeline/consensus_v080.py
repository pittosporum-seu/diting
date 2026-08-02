"""Versioned v0.8 consensus policy with explicit evidence thresholds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..enums import EngineRunStatus
from ..schema import ConsensusConflict, ConsensusResult, EngineRun


class ConsensusPolicy:
    """Combine successful engine runs without manufacturing fallback scores."""

    version = "consensus-v1"

    def __init__(
        self,
        weights: Mapping[str, float],
        *,
        min_successes: int = 2,
        min_weight_coverage: float = 0.5,
    ) -> None:
        if min_successes < 1:
            raise ValueError("min_successes must be positive")
        if not 0 < min_weight_coverage <= 1:
            raise ValueError("min_weight_coverage must be in (0, 1]")
        if any(weight < 0 for weight in weights.values()):
            raise ValueError("engine weights cannot be negative")
        self._weights = dict(weights)
        self._min_successes = min_successes
        self._min_weight_coverage = min_weight_coverage

    def combine(
        self,
        symbol: str,
        runs: Sequence[EngineRun],
        *,
        planned_engines: Sequence[str],
    ) -> ConsensusResult:
        planned = tuple(dict.fromkeys(planned_engines))
        positive_plan = tuple(name for name in planned if self._weights.get(name, 0) > 0)
        configured_weight = sum(self._weights[name] for name in positive_plan)
        weight_snapshot = tuple((name, self._weights.get(name, 0.0)) for name in planned)

        valid: list[EngineRun] = []
        failed: list[str] = []
        for run in runs:
            if run.engine_name not in planned:
                continue
            if not self._valid_success(run):
                failed.append(run.engine_name)
                continue
            if self._weights.get(run.engine_name, 0) <= 0:
                continue
            valid.append(run)

        effective_weight = sum(self._weights[run.engine_name] for run in valid)
        coverage = effective_weight / configured_weight if configured_weight > 0 else 0.0
        conflicts = self._detect_conflicts(valid)

        reason = self._insufficient_reason(valid, coverage)
        if reason is not None:
            return ConsensusResult(
                symbol=symbol,
                analysis_score=None,
                confidence=0.0,
                weight_coverage=round(coverage, 4),
                engines_used=tuple(run.engine_name for run in valid),
                engines_failed=tuple(dict.fromkeys(failed)),
                conflicts=conflicts,
                weight_snapshot=weight_snapshot,
                insufficient_reason=reason,
            )

        weighted_score = sum(
            run.result.engine_score * self._weights[run.engine_name] for run in valid
        )
        analysis_score = weighted_score / effective_weight
        weighted_confidence = (
            sum(run.result.confidence * self._weights[run.engine_name] for run in valid)
            / effective_weight
        )
        scores = [run.result.engine_score for run in valid]
        spread = max(scores) - min(scores)
        agreement = max(0.2, 1.0 - spread / 100.0)
        confidence = min(1.0, weighted_confidence * coverage * agreement)

        return ConsensusResult(
            symbol=symbol,
            analysis_score=round(analysis_score, 1),
            confidence=round(confidence, 3),
            weight_coverage=round(coverage, 4),
            engines_used=tuple(run.engine_name for run in valid),
            engines_failed=tuple(dict.fromkeys(failed)),
            conflicts=conflicts,
            weight_snapshot=weight_snapshot,
        )

    @staticmethod
    def _valid_success(run: EngineRun) -> bool:
        result = run.result
        return (
            run.status == EngineRunStatus.SUCCEEDED
            and result is not None
            and run.engine_name == result.engine_name
            and run.engine_version == result.engine_version
            and 0 <= result.engine_score <= 100
            and run.engine_score == result.engine_score
        )

    def _insufficient_reason(self, valid: Sequence[EngineRun], coverage: float) -> str | None:
        if len(valid) < self._min_successes:
            return "MIN_SUCCESSFUL_ENGINES_NOT_MET"
        if not any(run.deterministic for run in valid):
            return "DETERMINISTIC_ENGINE_REQUIRED"
        if coverage < self._min_weight_coverage:
            return "WEIGHT_COVERAGE_BELOW_THRESHOLD"
        return None

    @staticmethod
    def _detect_conflicts(runs: Sequence[EngineRun]) -> tuple[ConsensusConflict, ...]:
        conflicts: list[ConsensusConflict] = []
        for index, left in enumerate(runs):
            for right in runs[index + 1 :]:
                delta = abs(left.result.engine_score - right.result.engine_score)
                if delta < 30:
                    continue
                conflicts.append(
                    ConsensusConflict(
                        engine_a=left.engine_name,
                        engine_b=right.engine_name,
                        score_a=left.result.engine_score,
                        score_b=right.result.engine_score,
                        severity="severe" if delta >= 50 else "moderate",
                    )
                )
        return tuple(conflicts)
