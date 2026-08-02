# Task 23 — Remove the legacy HTTP and Jinja flow

## Goal

Make the v1 API and dependency-free SPA the only HTTP production path. The v0.8 process must not
construct legacy web services, cache managers, background prefetch workers or Jinja pages.

## Contract

- Internal API routes live under `/api/v1/*`.
- Every unversioned `/api` request returns HTTP 410 with `API_VERSION_REMOVED` in a v1 envelope.
- Unknown `/api/v1/*` endpoints return `NOT_FOUND`, never the legacy-removal code.
- SPA deep links serve `frontend/index.html`; known assets are served from the frontend directory and
  missing assets return 404.
- The route graph is assembled from an injected `ApplicationContainer` and creates no legacy
  business services.
- Application shutdown closes the composition root. There are no implicit prefetch threads.
- Obsolete Jinja templates, duplicate web assets and the unused Jinja dependency are removed.

## Verification

- HTTP integration tests cover v1 health, the 410 matrix, v1 404 behavior and SPA delivery.
- Architecture assertions reject legacy services, `CacheManager`, Jinja and prefetch references in
  the production application graph.
- Full non-network tests, Ruff, formatting and pre-commit.
