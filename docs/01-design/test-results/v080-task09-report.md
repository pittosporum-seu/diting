# v0.8.0 Task 09 implementation report

Date: 2026-08-02

Branch: `codex/v0.8.0`

Base commit: `f1a8040`

## Delivered

- CLI and Web runtime interfaces receive the same `CachedMarketDataGateway` from bootstrap.
- Stock quote/history and fund-flow reads no longer construct Providers or read legacy raw cache
  tables.
- Scan history and market quote paths no longer read/write `historical_cache` or
  `market_snapshot`; stale fallback belongs to the gateway.
- Watchlist no longer uses civil market-state inference or the old snapshot table for prices.
- The init connectivity check also uses an isolated gateway rather than `MarketDataRepository`.
- Concrete-Provider AST exceptions are empty; new tests reject legacy raw-table references and
  legacy repository imports from interfaces.
- CLI adapter and Web StockService preserve identical `DataResult` cache, trace, warning and
  request semantics.

## Verification

- Focused architecture/interface/service suite: `57 passed, 13 deselected`.
- Full non-network suite after interface cutover: `535 passed, 79 deselected`.
- Pre-commit and Ruff: passed.
- Frontend JavaScript syntax: 12 files passed.

## Compatibility note

`GatewayLegacyView` is an internal presentation adapter only. It does not restore removed public
v0.8 contracts and is scheduled to disappear as the orchestrator and v1 API replace legacy
consumers in Tasks 14 and 23.
