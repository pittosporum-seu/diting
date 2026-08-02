"""Typed deterministic volume-profile engine for the v0.8 snapshot kernel."""

from __future__ import annotations

import numpy as np

from ..enums import EngineMode
from ..infra.errors import DataUnavailableError
from ..schema import (
    DataSnapshot,
    EngineCapabilities,
    EngineContext,
    EngineResult,
    Evidence,
    Risk,
)
from .kernel import SnapshotAnalysisEngine
from .rating import score_to_rating


class SnapshotVolumeProfileEngine(SnapshotAnalysisEngine):
    name = "volume_profile"
    version = "2.0.0"
    mode = EngineMode.DETERMINISTIC

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            required_data=("historical",),
            min_history_bars=30,
            deterministic=True,
            timeout_seconds=5,
        )

    def analyze(self, snapshot: DataSnapshot, context: EngineContext) -> EngineResult:
        del context
        historical = snapshot.historical
        if historical is None or not historical.succeeded or historical.data is None:
            raise DataUnavailableError(f"historical data is unavailable for {snapshot.symbol}")
        bars = historical.data.bars
        if len(bars) < 30:
            raise DataUnavailableError(f"need >=30 historical bars for {snapshot.symbol}")
        closes = np.asarray([bar.close for bar in bars], dtype=float)
        volumes = np.asarray([max(bar.volume, 0) for bar in bars], dtype=float)
        if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
            raise DataUnavailableError(f"invalid closes for {snapshot.symbol}")

        counts, edges = np.histogram(closes, bins=12, weights=volumes)
        poc_index = int(np.argmax(counts))
        poc = float((edges[poc_index] + edges[poc_index + 1]) / 2)
        current = float(closes[-1])
        deviation = (current - poc) / poc
        if abs(deviation) <= 0.03:
            score = 60.0
            evidence = (Evidence("AT_POC", "价格位于主要成交密集区", round(poc, 4)),)
            risks = ()
        elif deviation < -0.03:
            score = 55.0
            evidence = (Evidence("BELOW_POC", "价格低于主要成交密集区", round(poc, 4)),)
            risks = (Risk("SUPPORT_UNCONFIRMED", "回归密集区前仍需确认支撑"),)
        else:
            score = 42.0
            evidence = ()
            risks = (Risk("ABOVE_POC", "价格显著高于成交密集区，存在回归风险"),)

        confidence = round(min(0.9, 0.6 + len(bars) / 1000), 2)
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=snapshot.symbol,
            engine_score=score,
            rating=score_to_rating(score),
            confidence=confidence,
            narrative=f"现价 {current:.2f}，成交密集区 POC {poc:.2f}，偏离 {deviation:.1%}。",
            evidence=evidence,
            risks=risks,
            metadata=(("poc", f"{poc:.6f}"), ("deviation", f"{deviation:.6f}")),
        )
