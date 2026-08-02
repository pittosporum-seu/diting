"""Table-driven v0.8 consensus and verdict tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.diting.engines.verdict_v080 import VerdictInterpreter
from src.diting.enums import EngineRunStatus, Rating, VerdictLabel
from src.diting.pipeline.consensus_v080 import ConsensusPolicy
from src.diting.schema import EngineResult, EngineRun, Evidence, Risk

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
WEIGHTS = {
    "technical": 1.0,
    "volume_profile": 0.8,
    "wyckoff": 0.8,
    "can_slim": 0.7,
    "buffett": 0.7,
    "vmd_rsi": 0.0,
}


def _run(
    name: str,
    score: float | None,
    *,
    deterministic: bool,
    status: EngineRunStatus = EngineRunStatus.SUCCEEDED,
) -> EngineRun:
    result = None
    if score is not None:
        result = EngineResult(
            engine_name=name,
            engine_version="1",
            symbol="002475",
            engine_score=score,
            rating=Rating.HOLD,
            confidence=0.8,
            narrative="evidence",
            evidence=(Evidence("FACT", f"{name} fact", score),),
            risks=(Risk("RISK", f"{name} risk"),),
        )
    return EngineRun(
        engine_name=name,
        engine_version="1",
        status=status,
        deterministic=deterministic,
        started_at=NOW,
        finished_at=NOW,
        engine_score=score,
        confidence=result.confidence if result else None,
        result=result,
        error_code=None if result else "FAILED",
    )


@pytest.mark.parametrize(
    ("runs", "plan", "reason"),
    [
        (
            [_run("technical", 70, deterministic=True)],
            ["technical", "wyckoff"],
            "MIN_SUCCESSFUL_ENGINES_NOT_MET",
        ),
        (
            [_run("wyckoff", 70, deterministic=False), _run("can_slim", 60, deterministic=False)],
            ["wyckoff", "can_slim"],
            "DETERMINISTIC_ENGINE_REQUIRED",
        ),
        (
            [_run("technical", 70, deterministic=True), _run("can_slim", 60, deterministic=False)],
            ["technical", "volume_profile", "wyckoff", "can_slim", "buffett"],
            "WEIGHT_COVERAGE_BELOW_THRESHOLD",
        ),
    ],
)
def test_insufficient_consensus_has_no_analysis_score(runs, plan, reason) -> None:
    result = ConsensusPolicy(WEIGHTS).combine("002475", runs, planned_engines=plan)

    assert result.analysis_score is None
    assert result.insufficient_reason == reason


def test_consensus_uses_only_valid_successes_and_records_weight_snapshot() -> None:
    runs = [
        _run("technical", 80, deterministic=True),
        _run("volume_profile", 60, deterministic=True),
        _run("wyckoff", None, deterministic=False, status=EngineRunStatus.FAILED),
    ]
    result = ConsensusPolicy(WEIGHTS).combine(
        "002475",
        runs,
        planned_engines=["technical", "volume_profile", "wyckoff"],
    )

    assert result.analysis_score == pytest.approx(71.1, abs=0.1)
    assert result.engines_used == ("technical", "volume_profile")
    assert result.engines_failed == ("wyckoff",)
    assert result.weight_coverage == pytest.approx(1.8 / 2.6, abs=0.001)
    assert dict(result.weight_snapshot)["wyckoff"] == 0.8


def test_conflict_and_verdict_are_deterministic_and_do_not_change_score() -> None:
    runs = [_run("technical", 90, deterministic=True), _run("wyckoff", 35, deterministic=False)]
    consensus = ConsensusPolicy(WEIGHTS).combine(
        "002475", runs, planned_engines=["technical", "wyckoff"]
    )
    verdict = VerdictInterpreter().interpret(consensus, runs)

    assert consensus.analysis_score == pytest.approx(65.6, abs=0.1)
    assert consensus.conflicts[0].severity == "severe"
    assert verdict.label is VerdictLabel.POSITIVE
    assert "65.6" in verdict.summary
    assert verdict.confidence == consensus.confidence


def test_insufficient_verdict_never_becomes_positive() -> None:
    runs = [_run("technical", 90, deterministic=True)]
    consensus = ConsensusPolicy(WEIGHTS).combine(
        "002475", runs, planned_engines=["technical", "wyckoff"]
    )

    verdict = VerdictInterpreter().interpret(consensus, runs)

    assert verdict.label is VerdictLabel.INSUFFICIENT
    assert "证据不足" in verdict.summary
