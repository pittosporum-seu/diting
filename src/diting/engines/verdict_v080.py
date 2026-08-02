"""Deterministic interpretation of an already-computed v0.8 consensus."""

from __future__ import annotations

from collections.abc import Sequence

from ..enums import EngineRunStatus, VerdictLabel
from ..schema import ConsensusResult, EngineRun, Evidence, Verdict


class VerdictInterpreter:
    """Explain consensus without changing or replacing its score."""

    def interpret(
        self,
        consensus: ConsensusResult,
        runs: Sequence[EngineRun],
        *,
        horizon: str = "5-20 trading days",
    ) -> Verdict:
        if consensus.analysis_score is None:
            return Verdict(
                label=VerdictLabel.INSUFFICIENT,
                horizon=horizon,
                summary="证据不足，无法形成有效分析结论。",
                risks=tuple(
                    run.result.risks
                    for run in runs
                    if run.status == EngineRunStatus.SUCCEEDED and run.result
                )[0]
                if any(
                    run.status == EngineRunStatus.SUCCEEDED and run.result and run.result.risks
                    for run in runs
                )
                else (),
                confidence=0.0,
            )

        score = consensus.analysis_score
        if score >= 65:
            label = VerdictLabel.POSITIVE
            summary = f"综合证据偏积极，分析分为 {score:.1f}。"
        elif score >= 50:
            label = VerdictLabel.NEUTRAL
            summary = f"综合证据中性偏积极，分析分为 {score:.1f}。"
        else:
            label = VerdictLabel.CAUTIOUS
            summary = f"综合证据偏谨慎，分析分为 {score:.1f}。"

        successful = tuple(
            run
            for run in runs
            if run.status == EngineRunStatus.SUCCEEDED and run.result is not None
        )
        evidence = tuple(item for run in successful for item in run.result.evidence)
        risks = tuple(item for run in successful for item in run.result.risks)
        bull = evidence if score >= 50 else ()
        bear = tuple(Evidence(item.code, item.summary) for item in risks) if score < 65 else ()
        return Verdict(
            label=label,
            horizon=horizon,
            summary=summary,
            bull_evidence=bull[:8],
            bear_evidence=bear[:8],
            risks=risks[:8],
            invalidation_conditions=tuple(item.summary for item in risks[:5]),
            confidence=consensus.confidence,
        )
