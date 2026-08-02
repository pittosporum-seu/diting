"""Dispatch report and notification work only after an analysis run is durable."""

from __future__ import annotations

import json

from ..enums import AnalysisProfile, JobType
from ..ports import DurableStore, Notifier, ReportPort
from ..schema import AnalysisRun, JobRecord, Notification
from .jobs import JobService


class PostAnalysisDispatcher:
    """Create independently retryable side-effect jobs for one immutable run id."""

    def __init__(
        self,
        jobs: JobService,
        store: DurableStore,
        *,
        report: ReportPort | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self._jobs = jobs
        self._store = store
        self._report = report
        self._notifier = notifier

    def dispatch(self, run: AnalysisRun) -> tuple[JobRecord, ...]:
        created: list[JobRecord] = []
        if self._report is not None and run.profile is AnalysisProfile.DEEP:
            created.append(self.dispatch_report(run.run_id))
        if self._notifier is not None:
            created.append(self.dispatch_notification(run.run_id))
        return tuple(created)

    def dispatch_report(self, run_id: str) -> JobRecord:
        if self._report is None:
            raise RuntimeError("report adapter is not configured")

        def build(_control) -> str:
            run = self._require_run(run_id)
            artifact = self._report.build(run)
            return str(artifact.path)

        return self._jobs.submit(
            JobType.REPORT,
            _request_json(run_id, "report"),
            build,
            dedupe_key=f"report:{run_id}",
        )

    def dispatch_notification(self, run_id: str) -> JobRecord:
        if self._notifier is None:
            raise RuntimeError("notification adapter is not configured")

        def notify(_control) -> str:
            run = self._require_run(run_id)
            score = "insufficient" if run.analysis_score is None else f"{run.analysis_score:.1f}"
            self._notifier.send(
                Notification(
                    title=f"谛听分析完成 · {run.symbol}",
                    body=(
                        f"run_id={run.run_id}\nstatus={run.status.value}\n"
                        f"analysis_score={score}\nstrategy={run.strategy_version}"
                    ),
                )
            )
            return run.run_id

        return self._jobs.submit(
            JobType.NOTIFICATION,
            _request_json(run_id, "notification"),
            notify,
            dedupe_key=f"notification:{run_id}",
        )

    def _require_run(self, run_id: str) -> AnalysisRun:
        run = self._store.get_analysis_run(run_id)
        if run is None:
            raise KeyError(f"analysis run not found: {run_id}")
        return run


def _request_json(run_id: str, side_effect: str) -> str:
    return json.dumps(
        {"run_id": run_id, "side_effect": side_effect},
        sort_keys=True,
        separators=(",", ":"),
    )
