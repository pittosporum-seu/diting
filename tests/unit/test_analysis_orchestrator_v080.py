"""Unified v0.8 analysis-orchestrator tests."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from src.diting.application.analysis import AnalysisOrchestrator
from src.diting.config import AppConfig
from src.diting.engines.kernel import EngineRegistry, SnapshotAnalysisEngine
from src.diting.enums import (
    AnalysisProfile,
    EngineMode,
    EngineRunStatus,
    Rating,
    RunStatus,
)
from src.diting.infra.errors import StructuredOutputError
from src.diting.pipeline.consensus_v080 import ConsensusPolicy
from src.diting.schema import (
    AnalysisRequest,
    DataResult,
    DataSnapshot,
    EngineCapabilities,
    EngineContext,
    EngineResult,
    Evidence,
    Financials,
    HistoricalBar,
    HistoricalSeries,
    RealtimeQuote,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return time.monotonic()


class StubSnapshotBuilder:
    def __init__(self, snapshot: DataSnapshot) -> None:
        self.snapshot = snapshot
        self.requests = []

    def build(self, request: AnalysisRequest) -> DataSnapshot:
        self.requests.append(request)
        return self.snapshot


class MemoryStore:
    def __init__(self) -> None:
        self.events = []
        self.run = None

    def save_data_snapshot(self, snapshot):
        self.events.append(("snapshot", snapshot.snapshot_id))

    def save_analysis_run(self, run):
        self.events.append(("run", run.run_id))
        self.run = run


class StubEngine(SnapshotAnalysisEngine):
    version = "1"

    def __init__(
        self,
        name: str,
        score: float,
        *,
        deterministic: bool,
        failure: Exception | None = None,
    ) -> None:
        self.name = name
        self.score = score
        self.failure = failure
        self.mode = EngineMode.DETERMINISTIC if deterministic else EngineMode.LLM_STRUCTURED
        self._deterministic = deterministic
        self.contexts = []

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            deterministic=self._deterministic,
            requires_llm=not self._deterministic,
            timeout_seconds=5,
        )

    def analyze(self, snapshot: DataSnapshot, context: EngineContext) -> EngineResult:
        self.contexts.append(context)
        if self.failure:
            raise self.failure
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=snapshot.symbol,
            engine_score=self.score,
            rating=Rating.HOLD,
            confidence=0.8,
            narrative=f"{self.name} result",
            evidence=(Evidence("FACT", self.name, self.score),),
        )


def _snapshot(*, financials: bool = True) -> DataSnapshot:
    bars = tuple(
        HistoricalBar(
            date(2026, 1, 1) + timedelta(days=index),
            20,
            21,
            19,
            20 + index / 10,
            1000,
        )
        for index in range(80)
    )
    quote = RealtimeQuote("002475", "立讯精密", 42, 1, 41, 43, 40, 100, 4200, timestamp=NOW)
    financial_result = None
    if financials:
        financial_result = DataResult(
            data=Financials("002475", NOW.date(), 1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            data_time=NOW,
        )
    return DataSnapshot(
        snapshot_id="snap-1",
        symbol="002475",
        created_at=NOW,
        as_of=NOW,
        quote=DataResult(data=quote, data_time=NOW),
        historical=DataResult(data=HistoricalSeries(symbol="002475", bars=bars), data_time=NOW),
        financials=financial_result,
        completeness=1.0 if financials else 0.75,
        snapshot_hash="snapshot-hash",
    )


def _orchestrator(snapshot: DataSnapshot, *, failed_wyckoff: bool = False):
    engines = [
        StubEngine("technical", 70, deterministic=True),
        StubEngine("volume_profile", 60, deterministic=True),
        StubEngine(
            "wyckoff",
            75,
            deterministic=False,
            failure=(
                StructuredOutputError("wyckoff", "002475", "bad json") if failed_wyckoff else None
            ),
        ),
        StubEngine("can_slim", 68, deterministic=False),
        StubEngine("buffett", 62, deterministic=False),
    ]
    settings = AppConfig()
    store = MemoryStore()
    builder = StubSnapshotBuilder(snapshot)
    orchestrator = AnalysisOrchestrator(
        settings,
        FakeClock(),
        builder,
        EngineRegistry(engines),
        ConsensusPolicy(settings.engines.weights),
        store,
        code_version="0.8.0-test",
    )
    return orchestrator, store, builder, engines


def test_standard_and_deep_profiles_have_locked_plans() -> None:
    orchestrator, _, _, _ = _orchestrator(_snapshot())

    standard = orchestrator.plan_for(
        AnalysisRequest("002475", AnalysisProfile.STANDARD), _snapshot()
    )
    deep = orchestrator.plan_for(AnalysisRequest("002475", AnalysisProfile.DEEP), _snapshot())

    assert standard == ("technical", "volume_profile", "wyckoff", "can_slim")
    assert deep == ("technical", "volume_profile", "wyckoff", "can_slim", "buffett")


def test_financial_engines_are_omitted_when_financials_are_missing() -> None:
    snapshot = _snapshot(financials=False)
    orchestrator, _, _, _ = _orchestrator(snapshot)

    assert orchestrator.plan_for(AnalysisRequest("002475"), snapshot) == (
        "technical",
        "volume_profile",
        "wyckoff",
    )


def test_analysis_freezes_deadline_persists_in_order_and_returns_consensus() -> None:
    orchestrator, store, builder, engines = _orchestrator(_snapshot())

    run = orchestrator.analyze(AnalysisRequest("sz.002475"))

    assert run.status is RunStatus.SUCCEEDED
    assert run.analysis_score is not None
    assert run.request.symbol == "002475"
    assert run.request.deadline == NOW + timedelta(seconds=15)
    assert run.config_hash == orchestrator.config_hash
    assert run.strategy_version == "analysis-v1"
    assert run.code_version == "0.8.0-test"
    assert store.events[0] == ("snapshot", "snap-1")
    assert store.events[1][0] == "run"
    assert store.run is run
    assert builder.requests == [run.request]
    assert all(engine.contexts[0].deadline <= run.request.deadline for engine in engines[:4])


def test_invalid_ai_output_is_failed_run_but_deterministic_consensus_survives() -> None:
    orchestrator, _, _, _ = _orchestrator(_snapshot(), failed_wyckoff=True)

    run = orchestrator.analyze(AnalysisRequest("002475"))

    wyckoff = next(item for item in run.engine_runs if item.engine_name == "wyckoff")
    assert wyckoff.status is EngineRunStatus.FAILED
    assert wyckoff.engine_score is None
    assert wyckoff.error_code == "INVALID_STRUCTURED_OUTPUT"
    assert run.status is RunStatus.PARTIAL
    assert run.analysis_score is not None


def test_requested_engine_must_belong_to_profile() -> None:
    orchestrator, _, builder, _ = _orchestrator(_snapshot())

    with pytest.raises(ValueError, match="not allowed"):
        orchestrator.analyze(AnalysisRequest("002475", requested_engines=("technical", "buffett")))
    assert builder.requests == []


def test_same_orchestrator_result_is_interface_independent() -> None:
    orchestrator, _, _, _ = _orchestrator(_snapshot())
    request = AnalysisRequest("002475", as_of=NOW, request_id="same")

    cli_result = orchestrator.analyze(request)
    web_result = orchestrator.analyze(replace(request))

    assert cli_result.snapshot_hash == web_result.snapshot_hash
    assert cli_result.config_hash == web_result.config_hash
    assert cli_result.strategy_version == web_result.strategy_version
    assert cli_result.analysis_score == web_result.analysis_score
    assert tuple(item.engine_name for item in cli_result.engine_runs) == tuple(
        item.engine_name for item in web_result.engine_runs
    )
