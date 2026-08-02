# v0.8.0 Task 02 — Domain contracts and ports

## Design references

- `docs/01-design/v0.8.0-system-design.md` sections 6–8 and 10
- `tasks/plan.md` Task 02

## Scope

Expected files: `src/diting/schema.py`, `src/diting/enums.py`, `src/diting/ports.py`,
`tests/unit/test_schema_v080.py`, `tests/unit/test_ports.py`. Do not edit design docs or
`AGENTS.md`.

## Requirements

- Add frozen, typed contracts for FetchMode, CacheInfo, FreshnessInfo, ProviderTrace,
  `DataResult[T]`, gateway request/response payloads, DataSnapshot, EngineRun, AnalysisRun,
  ScanResult, warnings and strategy state.
- Keep HTTP Pydantic models out of core contracts; core cross-module values are dataclasses.
- Define runtime-checkable Protocols/ABCs for data gateway/provider, cache/store, LLM, sandbox,
  clock/calendar, report and notifier dependencies. Ports must not import concrete adapters.
- Existing contracts may be evolved compatibly until later tasks remove old entry points, but no
  raw business dict/DataFrame may be added.

## Acceptance and verification

- `uv run pytest tests/unit/test_schema.py tests/unit/test_schema_v080.py tests/unit/test_ports.py -q`
- `uv run ruff check src/diting/schema.py src/diting/enums.py src/diting/ports.py tests/unit/test_schema_v080.py tests/unit/test_ports.py`
- Importing `diting.ports` must not import `akshare`, `litellm`, FastAPI or provider modules.

## Completion protocol

Write `docs/01-design/test-results/v080-task02-report.md`, append status JSONL and notify through
the Windows/WSL wrapper.
