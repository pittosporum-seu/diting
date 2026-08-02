# v0.8.0 Task 05 — L1/L2 cache store

## References

- `docs/01-design/v0.8.0-system-design.md` data middleware section
- `tasks/plan.md` Task 05

## Scope and acceptance

Implement a bounded thread-safe L1, SQLite L2, read-through promotion, schema-versioned records,
TTL/stale eviction, prefix deletion, metadata, and persistent Provider health/circuit state. L2 is
available only after a successful cache migration.

Verify eviction, restart, binary payload, stale bounds, clear and Provider-health restart behavior.
