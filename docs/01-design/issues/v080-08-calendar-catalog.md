# v0.8.0 Task 08 — Catalog, exchange calendar and market phases

## References

- `docs/01-design/v0.8.0-system-design.md` market phase rules
- `tasks/plan.md` Task 08

## Scope and acceptance

Expose AkShare security-directory and exchange-calendar data behind the Provider port and gateway.
Derive trading/closed/post-close-settling phases only from Provider sessions; never infer Chinese
exchange holidays from civil workdays. Unknown calendars retain conservative short TTL behavior.

Verify catalog/calendar caching, unknown state, non-session days, next open, range filtering and
the final-refresh settling transition.
