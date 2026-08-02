# Task 28 — Runtime OpenAPI and unskippable CI gates

## Goal

Make the FastAPI/Pydantic runtime graph the source of the checked-in v0.8 contract and ensure every
repository change executes the relevant quality gates.

## Contract

- `scripts/validate-api.py --write` produces the checked-in OpenAPI document from the production
  route factories and boundary models without starting databases, Providers, workers or AI clients.
- `--check` compares semantic documents and fails on any runtime/contract drift.
- The contract contains only `/api/v1/*` paths, identifies version `0.8.0` and documents the
  `/api/diting/v1` production gateway prefix.
- Importing the engine package has no auto-discovery or external side effect.
- CI runs for every repository change. It checks Ruff, formatting, non-network tests, lockfile,
  OpenAPI drift, every frontend JavaScript file and shell script syntax.
- The aggregate job fails on skipped, cancelled or failed required jobs.

## Verification

- Contract regeneration/check and focused OpenAPI tests.
- Local JavaScript and shell syntax checks.
- Full non-network pytest, Ruff, formatting and pre-commit.
