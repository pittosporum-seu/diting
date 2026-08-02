# v0.8.0 Tasks 04–08 implementation report

Date: 2026-08-02

Branch: `codex/v0.8.0`

Base checkpoint: `d93d10b`

## Delivered

- Checksummed dual-SQLite migrations, verified pre-migration backups and readiness checks.
- Bounded L1 plus persistent L2 with compressed schema-versioned payloads and persistent Provider
  health/circuit state.
- Typed gateway slices for quotes, daily history, fundamentals, fund flow, instrument catalog and
  trading calendar.
- Cache modes, force refresh, deadline rejection, single-flight, retry/fallback/circuit breaker,
  negative cache, stale-if-error, Provider traces and mx-data batch limiting.
- Legacy Provider normalization at the adapter boundary; no DataFrame crosses the v0.8 Provider
  port.
- Provider-derived exchange-calendar state with an explicit `post_close_settling` phase.

## Verification

- Focused C1 suite: `44 passed`.
- Ruff: clean for all changed implementation and test files after formatting.
- Full non-network suite: `532 passed, 79 deselected`.
- `uv run pre-commit run --all-files`: all hooks passed.

## Remaining C1 work

Task 09 remains open: the legacy CLI and Web services still need to stop constructing repositories
and using their historical data-cache paths. C1 is not accepted until the architecture exception
set is empty and interface parity tests pass.
