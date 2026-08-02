"""v0.8 durable analysis-run roundtrip tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.diting.enums import AnalysisProfile, EngineRunStatus, Rating, RunStatus, VerdictLabel
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.schema import (
    AnalysisRequest,
    AnalysisRun,
    ConsensusResult,
    DataSnapshot,
    EngineResult,
    EngineRun,
    Evidence,
    Verdict,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def test_analysis_run_roundtrips_all_reproducibility_metadata(tmp_path: Path) -> None:
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    snapshot = DataSnapshot(
        snapshot_id="snap-1",
        symbol="002475",
        created_at=NOW,
        as_of=NOW,
        completeness=1,
        snapshot_hash="snapshot-hash",
    )
    result = EngineResult(
        engine_name="technical",
        engine_version="1",
        symbol="002475",
        engine_score=70,
        rating=Rating.BUY,
        confidence=0.8,
        narrative="typed result",
        evidence=(Evidence("FACT", "evidence", 70),),
    )
    engine_run = EngineRun(
        engine_name="technical",
        engine_version="1",
        status=EngineRunStatus.SUCCEEDED,
        deterministic=True,
        started_at=NOW,
        finished_at=NOW,
        engine_score=70,
        confidence=0.8,
        result=result,
        duration_ms=12,
    )
    consensus = ConsensusResult(
        symbol="002475",
        analysis_score=70,
        confidence=0.8,
        weight_coverage=1,
        engines_used=("technical",),
        weight_snapshot=(("technical", 1.0),),
    )
    run = AnalysisRun(
        run_id="run-1",
        request=AnalysisRequest(
            "002475",
            AnalysisProfile.STANDARD,
            as_of=NOW,
            request_id="request-1",
            deadline=NOW,
        ),
        status=RunStatus.SUCCEEDED,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        config_hash="config-hash",
        strategy_version="analysis-v1",
        code_version="0.8.0",
        started_at=NOW,
        engine_runs=(engine_run,),
        consensus=consensus,
        verdict=Verdict(VerdictLabel.POSITIVE, "5-20 days", "positive", confidence=0.8),
        completed_at=NOW,
    )

    store.save_data_snapshot(snapshot)
    store.save_analysis_run(run)
    restored = store.get_analysis_run("run-1")

    assert restored == run
    assert restored.analysis_score == 70
    assert restored.engine_runs[0].result.evidence[0].code == "FACT"
