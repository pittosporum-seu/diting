# Task 29 completion report

Status: passed.

- Added two real Chromium journeys over a live local uvicorn server and the production v0.8 route,
  authentication, persistence and static-file boundaries.
- Anonymous Chromium verified all five pages and their ready, empty, inactive-strategy and
  auth-required states.
- Owner Chromium verified token login, HttpOnly session, CSRF writes, preference persistence,
  watchlist add/remove, quote display, accepted analysis job, visible 45% running progress,
  persisted analysis rendering, inactive strategy diagnostics and logout.
- Console warnings/errors and uncaught page errors are hard failures. Both completed journeys
  produced zero issues.
- The first browser run exposed owner pages sending predictable anonymous requests that returned
  HTTP 401 and polluted the console. The frontend state machine now short-circuits known anonymous
  watchlist/settings routes while the server-side 401 boundary remains enforced.
- CI installs Playwright 1.61's pinned Chromium with OS dependencies, runs the journeys separately
  and uploads PNG/trace evidence on failure.

Real Chromium verification: `2 passed`; five pages; full Owner journey; zero console/page errors.

Focused frontend verification: `6 passed`; all JavaScript syntax checks passed.

Full non-network regression: `621 passed, 12 deselected`.
