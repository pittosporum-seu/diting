# Checkpoint C2 — unified analysis kernel

Status: passed on 2026-08-02.

## Delivered

- One immutable data snapshot per analysis.
- Explicit deterministic and strict structured-output engines.
- Versioned evidence thresholds with no synthetic neutral score.
- One profile-aware `AnalysisOrchestrator` and transactional durable records.
- Bounded persistent jobs with LLM concurrency control.
- Reports and notifications isolated as post-persist side effects.

## Gates

- `uv run ruff check src/ tests/`: passed.
- `uv run ruff format --check src/ tests/`: 159 files formatted.
- `uv run pytest tests/ -m "not network" -q`: 575 passed, 79 deselected.
- Focused concurrency/failure/persistence/profile suites: passed.

## Remaining risk carried to C3

- Existing public HTTP and CLI presentation flows still use the legacy contract until Tasks 17–23
  perform the intentional breaking cutover.
- FastAPI `on_event` and legacy SQLite timestamp converters emit deprecation warnings; C3 lifespan
  replacement removes the first class, while legacy persistence exits with Task 23.
