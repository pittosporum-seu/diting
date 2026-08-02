"""Post-persist report and notification isolation tests."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, date, datetime
from pathlib import Path

from src.diting.application.jobs import JobService
from src.diting.application.post_analysis import PostAnalysisDispatcher
from src.diting.enums import AnalysisProfile, RunStatus, VerdictLabel
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.report.v080 import AnalysisRunReportBuilder
from src.diting.schema import (
    AnalysisRequest,
    AnalysisRun,
    ConsensusResult,
    Notification,
    ReportArtifact,
    Verdict,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return time.monotonic()


def _setup(tmp_path: Path):
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    jobs = JobService(store, FakeClock(), queue_limit=10)
    return store, jobs


def _run() -> AnalysisRun:
    consensus = ConsensusResult(
        symbol="002475",
        analysis_score=68,
        confidence=0.75,
        weight_coverage=1,
        engines_used=("technical", "volume_profile"),
    )
    return AnalysisRun(
        run_id="run-side-effect",
        request=AnalysisRequest("002475", AnalysisProfile.DEEP, request_id="request"),
        status=RunStatus.SUCCEEDED,
        snapshot_id="snapshot",
        snapshot_hash="snapshot-hash",
        config_hash="config",
        strategy_version="analysis-v1",
        code_version="0.8.0",
        started_at=NOW,
        consensus=consensus,
        verdict=Verdict(VerdictLabel.POSITIVE, "5-20 days", "positive", confidence=0.75),
        completed_at=NOW,
    )


def _wait(store: SQLiteDurableStore, job_id: str):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = store.get_job(job_id)
        if job and job.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            return job
        time.sleep(0.01)
    raise AssertionError("side-effect job did not finish")


def test_successful_side_effects_reload_same_durable_run(tmp_path: Path) -> None:
    store, jobs = _setup(tmp_path)
    run = _run()
    store.save_analysis_run(run)
    reports = []
    notifications: list[Notification] = []

    class Report:
        def build(self, loaded):
            reports.append(loaded)
            path = tmp_path / "report.html"
            return ReportArtifact(loaded.run_id, path, "text/html", "hash")

    class Notifier:
        def send(self, notification):
            notifications.append(notification)

    dispatcher = PostAnalysisDispatcher(jobs, store, report=Report(), notifier=Notifier())
    try:
        created = dispatcher.dispatch(run)
        completed = [_wait(store, item.job_id) for item in created]

        assert [item.status for item in completed] == [RunStatus.SUCCEEDED] * 2
        assert reports == [run]
        assert notifications[0].title.endswith("002475")
        assert "run-side-effect" in notifications[0].body
        assert completed[0].result_ref.endswith("report.html")
    finally:
        jobs.close()


def test_side_effect_failures_do_not_rewrite_analysis_and_can_retry(tmp_path: Path) -> None:
    store, jobs = _setup(tmp_path)
    run = _run()
    store.save_analysis_run(run)

    class BrokenReport:
        def build(self, _loaded):
            raise RuntimeError("report unavailable")

    class BrokenNotifier:
        def send(self, _notification):
            raise RuntimeError("notify unavailable")

    dispatcher = PostAnalysisDispatcher(
        jobs,
        store,
        report=BrokenReport(),
        notifier=BrokenNotifier(),
    )
    try:
        first = dispatcher.dispatch(run)
        failed = [_wait(store, item.job_id) for item in first]
        retry = dispatcher.dispatch_report(run.run_id)
        retried = _wait(store, retry.job_id)

        assert all(item.status is RunStatus.FAILED for item in failed)
        assert all(item.error_code == "JOB_FAILED" for item in failed)
        assert retried.status is RunStatus.FAILED
        assert retry.job_id != first[0].job_id
        restored = store.get_analysis_run(run.run_id)
        assert restored == run
        assert restored.status is RunStatus.SUCCEEDED
        assert restored.analysis_score == 68
    finally:
        jobs.close()


def test_v080_report_is_atomic_escaped_and_checksummed(tmp_path: Path) -> None:
    builder = AnalysisRunReportBuilder(tmp_path / "reports")
    artifact = builder.build(_run())

    content = artifact.path.read_bytes()
    assert artifact.path.exists()
    assert artifact.sha256 == hashlib.sha256(content).hexdigest()
    assert b"run-side-effect" in content
    assert list((tmp_path / "reports").glob("*.tmp")) == []
