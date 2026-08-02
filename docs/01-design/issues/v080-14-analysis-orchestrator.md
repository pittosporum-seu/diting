# Task 14 — AnalysisOrchestrator profiles

## Goal

Provide one application use case that freezes request/config/strategy/data/deadline, executes an
explicit engine plan, reaches consensus, creates a verdict and persists the immutable run.

## Profile rules

- `standard`: technical, volume profile, structured Wyckoff; CANSLIM only with financials.
- `deep`: standard plus Buffett when financials exist.
- Requested engines must be a subset of the selected profile.
- VMD cannot enter the production plan; sandbox execution is never selected implicitly.
- Default absolute deadlines are 15 seconds for standard and 60 seconds for deep; each engine gets
  the smaller of its declared budget and remaining run budget.

## Result rules

- Every engine is recorded as succeeded/skipped/timed_out/failed.
- Snapshot is stored before execution and AnalysisRun is inserted only after consensus/verdict.
- Insufficient consensus produces a failed run with `analysis_score=None`.
- The durable record contains config, strategy, code, prompt/model and weight versions.
