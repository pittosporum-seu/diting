# v0.8.0 Task 06 — Quote gateway vertical slice

## References

- `docs/01-design/v0.8.0-system-design.md` sections 7–8
- `tasks/plan.md` Task 06

## Scope and acceptance

Implement quote retrieval through `CachedMarketDataGateway` with all fetch modes, force refresh,
canonical keys, single-flight, explicit traces, two jittered retries, fallback, 3-failure/60-second
circuit breaking, 10-second transient and 5-minute not-found negative caches. mx-data batches may
never exceed four symbols.

Verify concurrency and every failure/freshness branch with deterministic fake providers.
