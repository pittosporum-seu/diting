# Task 16 — Post-persist report and notification jobs

## Goal

Keep reports and notifications outside analysis truth. They may run only after an immutable
`AnalysisRun` has committed and must always reload that same `run_id`.

## Semantics

- Deep analysis schedules a report when a report adapter is configured.
- Notifications are independently scheduled when a notifier is configured.
- Active dedupe keys prevent duplicate side effects; a failed/completed job may be explicitly
  retried using the same run id.
- Submission or execution failure never rewrites analysis status, score, consensus or verdict.
- Durable job records provide request, status, timestamps, result reference and error audit data.
- HTML report writes are atomic and return a SHA256-addressed `ReportArtifact`.
