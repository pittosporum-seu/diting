# Task 29 — Real Chromium journeys

## Goal

Turn the v0.8 frontend acceptance flows into a repeatable real-browser gate over live HTTP and the
actual FastAPI route, security, persistence and static-file boundaries.

## Contract

- Playwright launches real headless Chromium against a live local uvicorn server.
- The anonymous journey renders dashboard, stock, opportunities, watchlist and settings with their
  correct ready, empty and auth-required states.
- The Owner journey exercises token login, HttpOnly session cookie, CSRF writes, preferences,
  watchlist add/remove, quote read, accepted analysis job, visible running progress, persisted result
  rendering, inactive strategy diagnostics and logout.
- Every console warning/error and uncaught page error fails the test.
- Failure captures a full-page PNG and Playwright trace under ignored `browser-artifacts/`.
- CI installs pinned Playwright Chromium and executes browser tests separately from the core
  non-network suite.

## Verification

- Both Chromium journeys pass with no console/page errors.
- Existing frontend static architecture tests and full non-network backend suite remain green.
