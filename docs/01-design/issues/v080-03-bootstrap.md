# v0.8.0 Task 03 — Single bootstrap composition root

## Design references

- `docs/01-design/v0.8.0-system-design.md` sections 6 and 17
- `tasks/plan.md` Task 03

## Scope

Expected files: `src/diting/bootstrap.py`, `src/diting/ports.py`,
`tests/unit/test_bootstrap.py`, `tests/unit/test_architecture_boundaries.py`, and at most one small
adapter helper. Do not migrate Web/CLI behavior in this task and do not edit design docs.

## Requirements

- Introduce an `ApplicationContainer`/equivalent immutable dependency container.
- Production bootstrap is the only composition root allowed to construct concrete providers,
  caches, repositories, LLM or sandbox implementations.
- Tests can build a container entirely from injected fakes without optional/network imports.
- Add an AST/import guard that rejects concrete provider imports outside provider adapters and
  bootstrap. Initially allow an explicit, documented legacy exception list; later tasks must shrink
  it to zero.

## Acceptance and verification

- `uv run pytest tests/unit/test_bootstrap.py tests/unit/test_architecture_boundaries.py -q`
- `uv run ruff check src/diting/bootstrap.py tests/unit/test_bootstrap.py tests/unit/test_architecture_boundaries.py`
- Import/build of the fake container performs no network or database writes.

## Completion protocol

Write `docs/01-design/test-results/v080-task03-report.md`, append status JSONL and notify through
the Windows/WSL wrapper.
