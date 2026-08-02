"""Persistent bounded background jobs and global LLM concurrency control."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from threading import BoundedSemaphore, RLock, Semaphore
from uuid import uuid4

from ..enums import JobType, RunStatus
from ..infra.errors import AnalysisError, EngineTimeoutError, JobQueueFullError
from ..ports import Clock, DurableStore, LLMPort
from ..schema import AnalysisRequest, JobRecord, LLMRequest, LLMResponse
from .analysis import AnalysisOrchestrator

JobHandler = Callable[["JobControl"], str | None]


@dataclass(frozen=True)
class JobControl:
    """Cooperative progress and cancellation handle passed to a running job."""

    job_id: str
    _service: JobService

    def set_progress(self, progress: float) -> None:
        self._service._set_progress(self.job_id, progress)

    @property
    def cancel_requested(self) -> bool:
        job = self._service.get(self.job_id)
        return bool(job and job.cancel_requested)


class BoundedLLMPort:
    """Limit concurrent LLM calls across all analysis jobs in this process."""

    def __init__(self, delegate: LLMPort, max_concurrent: int = 2) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self._delegate = delegate
        self._semaphore = Semaphore(max_concurrent)

    def complete(self, request: LLMRequest) -> LLMResponse:
        timeout = None
        if request.deadline is not None:
            now = datetime.now(request.deadline.tzinfo)
            timeout = max(0.0, (request.deadline - now).total_seconds())
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            raise EngineTimeoutError("llm", "LLM concurrency deadline exceeded")
        try:
            return self._delegate.complete(request)
        finally:
            self._semaphore.release()


class JobService:
    """Bounded in-process scheduler backed by durable job records."""

    def __init__(
        self,
        store: DurableStore,
        clock: Clock,
        *,
        analysis_workers: int = 4,
        scan_workers: int = 1,
        side_effect_workers: int = 2,
        queue_limit: int = 100,
    ) -> None:
        if min(analysis_workers, scan_workers, side_effect_workers, queue_limit) < 1:
            raise ValueError("worker and queue limits must be positive")
        self._store = store
        self._clock = clock
        self._slots = BoundedSemaphore(queue_limit)
        self._executors = {
            JobType.ANALYSIS: ThreadPoolExecutor(
                max_workers=analysis_workers, thread_name_prefix="diting-analysis-job"
            ),
            JobType.SCAN: ThreadPoolExecutor(
                max_workers=scan_workers, thread_name_prefix="diting-scan-job"
            ),
        }
        side_effects = ThreadPoolExecutor(
            max_workers=side_effect_workers,
            thread_name_prefix="diting-side-effect-job",
        )
        self._executors[JobType.REPORT] = side_effects
        self._executors[JobType.NOTIFICATION] = side_effects
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()
        self._closed = False
        self.interrupted_on_start = self._store.interrupt_running_jobs(self._clock.now())

    def submit(
        self,
        job_type: JobType,
        request_json: str,
        handler: JobHandler,
        *,
        dedupe_key: str | None = None,
        deadline: datetime | None = None,
    ) -> JobRecord:
        if self._closed:
            raise RuntimeError("job service is closed")
        if dedupe_key:
            active = self._store.get_active_job_by_dedupe(dedupe_key)
            if active is not None:
                return active
        if not self._slots.acquire(blocking=False):
            raise JobQueueFullError()

        record = JobRecord(
            job_id=f"job_{uuid4().hex}",
            job_type=job_type,
            status=RunStatus.QUEUED,
            progress=0.0,
            request_json=request_json,
            created_at=self._clock.now(),
            dedupe_key=dedupe_key,
            deadline_at=deadline,
        )
        try:
            self._store.create_job(record)
        except Exception:
            self._slots.release()
            if dedupe_key:
                active = self._store.get_active_job_by_dedupe(dedupe_key)
                if active is not None:
                    return active
            raise

        try:
            future = self._executors[job_type].submit(self._run_job, record.job_id, handler)
        except Exception:
            self._slots.release()
            failed = replace(
                record,
                status=RunStatus.FAILED,
                error_code="JOB_SUBMISSION_FAILED",
                finished_at=self._clock.now(),
            )
            self._store.update_job(failed)
            raise
        with self._lock:
            self._futures[record.job_id] = future
        future.add_done_callback(lambda _future, job_id=record.job_id: self._job_finished(job_id))
        return record

    def submit_analysis(
        self,
        orchestrator: AnalysisOrchestrator,
        request: AnalysisRequest,
        *,
        dedupe_key: str | None = None,
    ) -> JobRecord:
        request_json = _analysis_request_json(request)
        key = dedupe_key or "analysis:" + hashlib.sha256(request_json.encode()).hexdigest()

        def run(control: JobControl) -> str:
            control.set_progress(0.1)
            result = orchestrator.analyze(request)
            control.set_progress(0.95)
            return result.run_id

        return self.submit(
            JobType.ANALYSIS,
            request_json,
            run,
            dedupe_key=key,
            deadline=request.deadline,
        )

    def get(self, job_id: str) -> JobRecord | None:
        return self._store.get_job(job_id)

    def cancel(self, job_id: str) -> JobRecord | None:
        record = self._store.get_job(job_id)
        if record is None or record.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            return record
        requested = replace(record, cancel_requested=True)
        with self._lock:
            future = self._futures.get(job_id)
        if record.status is RunStatus.QUEUED and future is not None and future.cancel():
            requested = replace(
                requested,
                status=RunStatus.CANCELLED,
                finished_at=self._clock.now(),
                error_code="JOB_CANCELLED",
            )
        self._store.update_job(requested)
        return requested

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        unique = {id(executor): executor for executor in self._executors.values()}
        for executor in unique.values():
            executor.shutdown(wait=True, cancel_futures=False)

    def _run_job(self, job_id: str, handler: JobHandler) -> None:
        record = self._store.get_job(job_id)
        if record is None:
            return
        now = self._clock.now()
        if record.cancel_requested:
            self._store.update_job(
                replace(
                    record,
                    status=RunStatus.CANCELLED,
                    error_code="JOB_CANCELLED",
                    finished_at=now,
                )
            )
            return
        if record.deadline_at is not None and record.deadline_at <= now:
            self._store.update_job(
                replace(
                    record,
                    status=RunStatus.FAILED,
                    error_code="JOB_DEADLINE_EXCEEDED",
                    finished_at=now,
                )
            )
            return

        running = replace(record, status=RunStatus.RUNNING, started_at=now)
        self._store.update_job(running)
        try:
            result_ref = handler(JobControl(job_id, self))
        except Exception as exc:
            current = self._store.get_job(job_id) or running
            error_code = exc.error_code if isinstance(exc, AnalysisError) else "JOB_FAILED"
            self._store.update_job(
                replace(
                    current,
                    status=RunStatus.FAILED,
                    error_code=error_code,
                    finished_at=self._clock.now(),
                )
            )
            return

        current = self._store.get_job(job_id) or running
        finished_at = self._clock.now()
        if current.cancel_requested:
            status = RunStatus.CANCELLED
            error_code = "JOB_CANCELLED"
        elif current.deadline_at is not None and current.deadline_at < finished_at:
            status = RunStatus.FAILED
            error_code = "JOB_DEADLINE_EXCEEDED"
        else:
            status = RunStatus.SUCCEEDED
            error_code = None
        self._store.update_job(
            replace(
                current,
                status=status,
                progress=1.0 if status is RunStatus.SUCCEEDED else current.progress,
                result_ref=result_ref,
                error_code=error_code,
                finished_at=finished_at,
            )
        )

    def _set_progress(self, job_id: str, progress: float) -> None:
        if not 0 <= progress <= 1:
            raise ValueError("progress must be in [0, 1]")
        current = self._store.get_job(job_id)
        if current is None or current.status is not RunStatus.RUNNING:
            return
        self._store.update_job(replace(current, progress=max(current.progress, progress)))

    def _job_finished(self, job_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)
        self._slots.release()


def _analysis_request_json(request: AnalysisRequest) -> str:
    payload = {
        "symbol": request.symbol,
        "profile": request.profile.value,
        "as_of": request.as_of.isoformat() if request.as_of else None,
        "force_refresh": request.force_refresh,
        "requested_engines": request.requested_engines,
        "request_id": request.request_id,
        "deadline": request.deadline.isoformat() if request.deadline else None,
        "enable_sandbox": request.enable_sandbox,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
