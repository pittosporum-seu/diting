"""Persistent bounded JobService concurrency and lifecycle tests."""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.diting.application.jobs import BoundedLLMPort, JobService
from src.diting.enums import JobType, RunStatus
from src.diting.infra.errors import JobQueueFullError
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.schema import JobRecord, LLMRequest, LLMResponse

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    def today(self) -> date:
        return self.current.date()

    def monotonic(self) -> float:
        return time.monotonic()


def _store(tmp_path: Path) -> SQLiteDurableStore:
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    return SQLiteDurableStore(business)


def _wait_for(store: SQLiteDurableStore, job_id: str, statuses: set[RunStatus]) -> JobRecord:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = store.get_job(job_id)
        if record is not None and record.status in statuses:
            return record
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def test_queue_is_bounded_and_active_dedupe_returns_same_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = JobService(store, FakeClock(), analysis_workers=1, queue_limit=1)
    release = threading.Event()
    try:
        first = service.submit(
            JobType.ANALYSIS,
            "{}",
            lambda _control: release.wait(2) or "run-1",
            dedupe_key="same",
        )
        duplicate = service.submit(
            JobType.ANALYSIS,
            "{}",
            lambda _control: "must-not-run",
            dedupe_key="same",
        )

        assert duplicate.job_id == first.job_id
        with pytest.raises(JobQueueFullError):
            service.submit(JobType.ANALYSIS, "{}", lambda _control: "other")
    finally:
        release.set()
        service.close()


def test_analysis_concurrency_and_progress_are_bounded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = JobService(store, FakeClock(), analysis_workers=2, queue_limit=6)
    lock = threading.Lock()
    release = threading.Event()
    active = 0
    maximum = 0

    def handler(control):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        control.set_progress(0.5)
        release.wait(2)
        with lock:
            active -= 1
        return f"run-{control.job_id}"

    try:
        jobs = [service.submit(JobType.ANALYSIS, "{}", handler) for _ in range(4)]
        deadline = time.monotonic() + 2
        while maximum < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert maximum == 2
        assert (
            sum((store.get_job(job.job_id) or job).status is RunStatus.RUNNING for job in jobs) == 2
        )
        release.set()
        completed = [_wait_for(store, job.job_id, {RunStatus.SUCCEEDED}) for job in jobs]
        assert all(item.progress == 1 for item in completed)
        assert all(item.result_ref.startswith("run-") for item in completed)
    finally:
        release.set()
        service.close()


def test_running_job_cancellation_is_cooperative(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = JobService(store, FakeClock(), analysis_workers=1, queue_limit=2)

    def handler(control):
        while not control.cancel_requested:
            time.sleep(0.01)
        return "ignored"

    try:
        job = service.submit(JobType.ANALYSIS, "{}", handler)
        _wait_for(store, job.job_id, {RunStatus.RUNNING})
        service.cancel(job.job_id)
        cancelled = _wait_for(store, job.job_id, {RunStatus.CANCELLED})
        assert cancelled.cancel_requested is True
        assert cancelled.error_code == "JOB_CANCELLED"
    finally:
        service.close()


def test_restart_marks_running_jobs_interrupted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_job(
        JobRecord(
            job_id="orphan",
            job_type=JobType.ANALYSIS,
            status=RunStatus.RUNNING,
            progress=0.5,
            request_json="{}",
            created_at=NOW,
            started_at=NOW,
        )
    )

    service = JobService(store, FakeClock(), queue_limit=2)
    try:
        orphan = store.get_job("orphan")
        assert service.interrupted_on_start == 1
        assert orphan.status is RunStatus.INTERRUPTED
        assert orphan.error_code == "WORKER_RESTARTED"
    finally:
        service.close()


def test_expired_job_never_executes_handler(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = JobService(store, FakeClock(), queue_limit=2)
    called = False

    def handler(_control):
        nonlocal called
        called = True
        return None

    try:
        job = service.submit(
            JobType.ANALYSIS,
            "{}",
            handler,
            deadline=NOW - timedelta(seconds=1),
        )
        failed = _wait_for(store, job.job_id, {RunStatus.FAILED})
        assert called is False
        assert failed.error_code == "JOB_DEADLINE_EXCEEDED"
    finally:
        service.close()


def test_llm_port_never_exceeds_global_concurrency() -> None:
    lock = threading.Lock()
    release = threading.Event()
    active = 0
    maximum = 0

    class Delegate:
        def complete(self, request):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            release.wait(2)
            with lock:
                active -= 1
            return LLMResponse("{}", request.model, "id")

    port = BoundedLLMPort(Delegate(), max_concurrent=2)
    request = LLMRequest((), "{}", "fake", deadline=NOW + timedelta(days=1))
    threads = [threading.Thread(target=port.complete, args=(request,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 2
    while maximum < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert maximum == 2
    release.set()
    for thread in threads:
        thread.join(timeout=2)
    assert all(not thread.is_alive() for thread in threads)
