# Task 20 — Stable Python facade

## Goal

Provide one intentionally exported synchronous Python API whose behavior matches HTTP/CLI because it
uses the same bootstrap, cached data gateway, analysis orchestrator and active-strategy boundary.

## Contract

- `Diting.from_config(path=None, overrides=None)` constructs and owns one runtime container.
- `get_quote(symbol, freshness=...)` returns `DataResult[RealtimeQuote]` from `DataGateway`.
- `analyze(symbol, profile=...)` returns the persisted `AnalysisRun` from `AnalysisOrchestrator`.
- `scan(limit=20)` returns `ScanResult`; no active strategy produces `NO_ACTIVE_STRATEGY` without
  invoking a legacy ranker.
- A `ScanOrchestratorPort` keeps the public method stable before Task 27 supplies the production
  implementation.
- `close()` is idempotent, context manager exit closes owned resources, and calls after close fail.
- The package root intentionally exports only the facade, version and stable domain result types.

## Verification

- Config path/override forwarding with an injected composition root.
- Quote fetch-mode and force-refresh parity.
- Analysis profile/request propagation.
- Inactive and active-strategy scan behavior.
- Context manager/idempotent close and validation errors.
- Installed-package import smoke test, Ruff and full non-network tests.
