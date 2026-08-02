# v0.8.0 Task 04 — Idempotent database migrations

## References

- `docs/01-design/v0.8.0-system-design.md`
- `tasks/plan.md` Task 04

## Scope and acceptance

Implement checksummed, transactional migrations for `diting.db` and `diting_cache.db`. Preserve
legacy tables, create a SHA256-verified backup before the first migration of an existing database,
make repeated runs no-ops, and fail readiness on SQL or checksum errors.

Verify empty, legacy, repeated and rollback paths in `tests/unit/test_migrations_v080.py`.
