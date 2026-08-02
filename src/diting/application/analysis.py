"""The single v0.8 analysis use case shared by every interface."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from .. import __version__
from ..config import AppConfig
from ..engines.kernel import EngineRegistry, SnapshotAnalysisEngine
from ..engines.verdict_v080 import VerdictInterpreter
from ..enums import AnalysisProfile, EngineRunStatus, RunStatus
from ..infra.errors import AnalysisError, DataUnavailableError, StructuredOutputError
from ..infra.logging_config import get_logger
from ..pipeline.consensus_v080 import ConsensusPolicy
from ..ports import Clock, DurableStore
from ..schema import (
    AnalysisRequest,
    AnalysisRun,
    DataSnapshot,
    DataWarning,
    EngineContext,
    EngineRun,
)
from .snapshot import DataSnapshotBuilder

logger = get_logger(__name__)


class PostPersistHook(Protocol):
    def dispatch(self, run: AnalysisRun) -> object: ...


class AnalysisOrchestrator:
    """Freeze inputs, execute a profile plan, reach consensus and persist once."""

    def __init__(
        self,
        settings: AppConfig,
        clock: Clock,
        snapshot_builder: DataSnapshotBuilder,
        registry: EngineRegistry,
        consensus: ConsensusPolicy,
        store: DurableStore,
        *,
        strategy_version: str = "analysis-v1",
        code_version: str = __version__,
        post_persist: PostPersistHook | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._snapshot_builder = snapshot_builder
        self._registry = registry
        self._consensus = consensus
        self._store = store
        self._strategy_version = strategy_version
        self._code_version = code_version
        self._config_hash = self._hash_config(settings)
        self._verdict = VerdictInterpreter()
        self._post_persist = post_persist

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def analyze(self, request: AnalysisRequest) -> AnalysisRun:
        started_at = self._clock.now()
        frozen_request = self._freeze_request(request, started_at)
        self._validate_request(frozen_request)
        snapshot = self._snapshot_builder.build(frozen_request)
        self._store.save_data_snapshot(snapshot)
        plan = self.plan_for(frozen_request, snapshot)
        engine_runs = self._execute_plan(plan, snapshot, frozen_request)
        consensus = self._consensus.combine(
            snapshot.symbol,
            engine_runs,
            planned_engines=plan,
        )
        verdict = self._verdict.interpret(consensus, engine_runs)
        completed_at = self._clock.now()

        has_engine_failure = any(
            run.status
            in {EngineRunStatus.FAILED, EngineRunStatus.TIMED_OUT, EngineRunStatus.SKIPPED}
            for run in engine_runs
        )
        if consensus.analysis_score is None:
            status = RunStatus.FAILED
        elif has_engine_failure:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.SUCCEEDED

        warnings = list(snapshot.warnings)
        if consensus.insufficient_reason:
            warnings.append(
                DataWarning(
                    code="INSUFFICIENT_EVIDENCE",
                    message=consensus.insufficient_reason,
                    recoverable=True,
                )
            )
        run = AnalysisRun(
            run_id=f"run_{uuid4().hex}",
            request=frozen_request,
            status=status,
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            config_hash=self._config_hash,
            strategy_version=self._strategy_version,
            code_version=self._code_version,
            started_at=started_at,
            engine_runs=engine_runs,
            consensus=consensus,
            verdict=verdict,
            completed_at=completed_at,
            warnings=tuple(warnings),
        )
        self._store.save_analysis_run(run)
        if self._post_persist is not None:
            try:
                self._post_persist.dispatch(run)
            except Exception as exc:
                logger.warning(
                    "analysis.post_persist_submission_failed",
                    run_id=run.run_id,
                    reason=type(exc).__name__,
                )
        return run

    def plan_for(self, request: AnalysisRequest, snapshot: DataSnapshot) -> tuple[str, ...]:
        self._validate_request(request)
        configured = (
            self._settings.engines.deep
            if request.profile is AnalysisProfile.DEEP
            else self._settings.engines.default
        )
        if request.requested_engines is not None:
            configured = request.requested_engines

        has_financials = bool(snapshot.financials and snapshot.financials.succeeded)
        plan = tuple(
            name for name in configured if name not in {"can_slim", "buffett"} or has_financials
        )
        if any(name == "vmd_rsi" for name in plan):
            raise ValueError("vmd_rsi is context-only and cannot enter the production engine plan")
        return plan

    def _validate_request(self, request: AnalysisRequest) -> None:
        configured = (
            self._settings.engines.deep
            if request.profile is AnalysisProfile.DEEP
            else self._settings.engines.default
        )
        if request.requested_engines is not None:
            unknown = tuple(name for name in request.requested_engines if name not in configured)
            if unknown:
                raise ValueError(
                    f"engines are not allowed by {request.profile.value}: {', '.join(unknown)}"
                )
        if request.enable_sandbox and not self._settings.ai.sandbox_enabled:
            raise ValueError("sandbox analysis requires ai.sandbox_enabled=true")

    def _execute_plan(
        self,
        plan: tuple[str, ...],
        snapshot: DataSnapshot,
        request: AnalysisRequest,
    ) -> tuple[EngineRun, ...]:
        if not plan:
            return ()
        deadline = request.deadline
        assert deadline is not None
        now = self._clock.now()
        if deadline <= now:
            return tuple(self._deadline_run(name, snapshot, now) for name in plan)

        runs: dict[str, EngineRun] = {}
        executor = ThreadPoolExecutor(
            max_workers=min(self._settings.pipeline.max_workers, len(plan)),
            thread_name_prefix="diting-analysis",
        )
        pending: dict[Future[EngineRun], tuple[str, float, datetime]] = {}
        for name in plan:
            engine = self._registry.get(name)
            if engine is None:
                runs[name] = self._skipped_run(name, now, "ENGINE_UNAVAILABLE")
                continue
            capabilities = engine.capabilities()
            remaining = max(0.0, (deadline - now).total_seconds())
            budget = min(float(capabilities.timeout_seconds), remaining)
            engine_deadline = now + timedelta(seconds=budget)
            context = EngineContext(
                deadline=engine_deadline,
                config_hash=self._config_hash,
                strategy_version=self._strategy_version,
                prompt_version=getattr(engine, "prompt_version", None),
                model=self._settings.ai.model if capabilities.requires_llm else None,
            )
            submitted_at = self._clock.now()
            future = executor.submit(self._execute_one, engine, snapshot, context)
            pending[future] = (name, self._clock.monotonic() + budget, submitted_at)

        try:
            while pending:
                monotonic_now = self._clock.monotonic()
                next_timeout = max(
                    0.0,
                    min(expiry for _, expiry, _ in pending.values()) - monotonic_now,
                )
                done, _ = wait(tuple(pending), timeout=next_timeout, return_when=FIRST_COMPLETED)
                for future in done:
                    name, _, _ = pending.pop(future)
                    runs[name] = future.result()

                monotonic_now = self._clock.monotonic()
                expired = [
                    future for future, (_, expiry, _) in pending.items() if expiry <= monotonic_now
                ]
                for future in expired:
                    name, _, submitted_at = pending.pop(future)
                    future.cancel()
                    finished_at = self._clock.now()
                    engine = self._registry.require(name)
                    runs[name] = EngineRun(
                        engine_name=name,
                        engine_version=engine.version,
                        status=EngineRunStatus.TIMED_OUT,
                        deterministic=engine.capabilities().deterministic,
                        started_at=submitted_at,
                        finished_at=finished_at,
                        error_code="ENGINE_TIMEOUT",
                        prompt_version=getattr(engine, "prompt_version", None),
                        model=(
                            self._settings.ai.model if engine.capabilities().requires_llm else None
                        ),
                        duration_ms=max(
                            0, int((finished_at - submitted_at).total_seconds() * 1000)
                        ),
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return tuple(runs[name] for name in plan)

    def _execute_one(
        self,
        engine: SnapshotAnalysisEngine,
        snapshot: DataSnapshot,
        context: EngineContext,
    ) -> EngineRun:
        started_at = self._clock.now()
        started_tick = self._clock.monotonic()
        capabilities = engine.capabilities()
        try:
            result = engine.analyze(snapshot, context)
        except DataUnavailableError as exc:
            return self._failed_execution(
                engine,
                capabilities.deterministic,
                started_at,
                started_tick,
                EngineRunStatus.SKIPPED,
                exc.error_code,
                str(exc),
                context,
            )
        except StructuredOutputError as exc:
            return self._failed_execution(
                engine,
                capabilities.deterministic,
                started_at,
                started_tick,
                EngineRunStatus.FAILED,
                exc.error_code,
                str(exc),
                context,
            )
        except AnalysisError as exc:
            return self._failed_execution(
                engine,
                capabilities.deterministic,
                started_at,
                started_tick,
                EngineRunStatus.FAILED,
                exc.error_code,
                str(exc),
                context,
            )
        except Exception as exc:
            return self._failed_execution(
                engine,
                capabilities.deterministic,
                started_at,
                started_tick,
                EngineRunStatus.FAILED,
                "ENGINE_FAILED",
                f"{type(exc).__name__}: {exc}",
                context,
            )

        finished_at = self._clock.now()
        return EngineRun(
            engine_name=engine.name,
            engine_version=engine.version,
            status=EngineRunStatus.SUCCEEDED,
            deterministic=capabilities.deterministic,
            started_at=started_at,
            finished_at=finished_at,
            engine_score=result.engine_score,
            confidence=result.confidence,
            result=result,
            prompt_version=context.prompt_version,
            model=context.model,
            duration_ms=max(0, int((self._clock.monotonic() - started_tick) * 1000)),
        )

    def _failed_execution(
        self,
        engine: SnapshotAnalysisEngine,
        deterministic: bool,
        started_at: datetime,
        started_tick: float,
        status: EngineRunStatus,
        error_code: str,
        detail: str,
        context: EngineContext,
    ) -> EngineRun:
        return EngineRun(
            engine_name=engine.name,
            engine_version=engine.version,
            status=status,
            deterministic=deterministic,
            started_at=started_at,
            finished_at=self._clock.now(),
            error_code=error_code,
            error_detail=detail[:500],
            prompt_version=context.prompt_version,
            model=context.model,
            duration_ms=max(0, int((self._clock.monotonic() - started_tick) * 1000)),
        )

    def _skipped_run(self, name: str, at: datetime, error_code: str) -> EngineRun:
        return EngineRun(
            engine_name=name,
            engine_version="unavailable",
            status=EngineRunStatus.SKIPPED,
            deterministic=False,
            started_at=at,
            finished_at=at,
            error_code=error_code,
        )

    def _deadline_run(self, name: str, snapshot: DataSnapshot, at: datetime) -> EngineRun:
        del snapshot
        engine = self._registry.get(name)
        return EngineRun(
            engine_name=name,
            engine_version=engine.version if engine else "unavailable",
            status=EngineRunStatus.TIMED_OUT,
            deterministic=engine.capabilities().deterministic if engine else False,
            started_at=at,
            finished_at=at,
            error_code="ANALYSIS_DEADLINE_EXCEEDED",
        )

    @staticmethod
    def _hash_config(settings: AppConfig) -> str:
        payload = json.dumps(
            settings.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _freeze_request(request: AnalysisRequest, now: datetime) -> AnalysisRequest:
        timeout = 60 if request.profile is AnalysisProfile.DEEP else 15
        deadline = request.deadline or now + timedelta(seconds=timeout)
        if (deadline.tzinfo is None) != (now.tzinfo is None):
            raise ValueError("analysis deadline timezone must match the application clock")
        return replace(
            request,
            symbol=DataSnapshotBuilder.normalize_symbol(request.symbol),
            request_id=request.request_id or f"req_{uuid4().hex}",
            deadline=deadline,
        )
