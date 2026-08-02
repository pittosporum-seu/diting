# v0.8.0 Task 07 — Historical, financial and fund-flow slices

## References

- `docs/01-design/v0.8.0-system-design.md` data contracts
- `tasks/plan.md` Task 07

## Scope and acceptance

Normalize legacy DataFrame history into immutable `HistoricalBar` tuples before it crosses the
Provider port. Store normalized history and typed fundamentals/fund flow as compressed,
schema-versioned JSON. Apply the same fetch, fallback, deadline and stale-if-error rules as quotes.

Verify adapter normalization plus gateway/cache round trips for all three data types.
