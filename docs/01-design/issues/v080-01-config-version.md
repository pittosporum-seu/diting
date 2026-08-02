# v0.8.0 Task 01 — Version and strict configuration foundation

## Design references

- `docs/01-design/v0.8.0-system-design.md` sections 9 and 17
- `tasks/plan.md` Task 01

## Scope

Expected files: `pyproject.toml`, `src/diting/config.py`, `src/diting/__init__.py`,
`tests/unit/test_config_v080.py`, and optionally `config/diting.yaml`. Do not edit design docs or
`AGENTS.md`.

## Requirements

- Set the project version to `0.8.0`; read it via package metadata, with one test-only fallback for
  an uninstalled source checkout. Remove hard-coded public version constants from touched paths.
- Define an immutable, strictly validated application configuration with the precedence
  CLI overrides > environment > YAML > defaults.
- Unknown keys must raise a typed configuration error containing the full key path.
- Secrets must come only from environment variables; YAML/DB preferences cannot override secrets,
  provider base URLs or production strategy selection.
- Preserve only compatibility needed by untouched modules until their migration task; mark it
  internal and do not add a second source of truth.

## Acceptance and verification

- `uv run pytest tests/unit/test_config.py tests/unit/test_config_v080.py -q`
- `uv run ruff check src/diting/config.py src/diting/__init__.py tests/unit/test_config_v080.py`
- `uv run diting --version` prints `0.8.0` once the existing CLI imports the package version.

## Completion protocol

Write `docs/01-design/test-results/v080-task01-report.md`, append status JSONL and notify through
`scripts/notify-diting.ps1`.
