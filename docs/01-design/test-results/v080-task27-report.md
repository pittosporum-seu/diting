# Task 27 completion report

Status: passed.

- Added an active-strategy-only `ScanOrchestrator` over the unified Data Gateway.
- Calendar, point-in-time stock catalog and every historical series use typed fresh-required
  requests; no provider or legacy cache path is reachable from the scanner.
- Missing active strategy, manifest, definition, eligible universe or runtime coverage fails closed
  with an explicit code and no fabricated opportunity ranking.
- Factor ranking is driven by the active typed definition and preserves strategy, manifest,
  factor, data-date and config identity in durable results and cache metadata.
- The cache stores the complete governed Top20; per-call limits only slice the returned view and
  cannot contaminate later requests.
- Owner scan creation runs through the bounded `JobService` with deduplication, progress and
  cooperative cancellation. Public opportunity reads never trigger computation and only expose the
  latest successful result for the exact active strategy version.
- Added the business migration and SQLite round-trip/latest-version lookup for traceable scan
  results.
- No strategy was fabricated or activated. Until research evidence is approved and an owner
  activates a version, production continues to return `NO_ACTIVE_STRATEGY`.

Focused scanner, job, API, persistence, migration and Python facade verification: `44 passed`.

Full non-network regression: `617 passed, 12 deselected`.
