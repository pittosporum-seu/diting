# Task 22 — Frontend v1 client, authentication and page state machine

## Goal

Replace the v0.7 browser bundle with a dependency-free v0.8 application shell that consumes only
typed v1 envelopes and makes loading, empty, unavailable, permission and failure states explicit.

## Contract

- `frontend/js/api.js` is the only module allowed to call `fetch`.
- Local FastAPI uses `/api/v1`; the `/app/diting` production path uses `/api/diting/v1` without
  endpoint probing.
- Mutations send same-origin credentials and the login-issued CSRF token from per-tab
  `sessionStorage`; owner token values are never persisted.
- `frontend/js/app.js` owns one route/page state machine for dashboard, stock, opportunities,
  watchlist and settings.
- Stock quote reads never start analysis. Explicit standard/deep actions create a job, poll progress,
  support cancellation and load the persisted run.
- No active strategy, no owner session and owner auth not configured are distinct user-visible states.
- All API-derived text is inserted through `textContent`; no `innerHTML` or `insertAdjacentHTML` is
  used.
- The shell uses one restrained icon system, four-layer light/dark color tokens, semantic status
  colors, keyboard focus, responsive layout, reduced-motion support, skeletons and toasts.
- Legacy client cache, direct page fetches, debug markers, ECharts CDN and v0.7 page modules are
  removed.

## Verification

- Static architecture tests enforce the single fetch boundary, five-page inventory, v1 endpoints,
  CSRF handling and safe DOM rendering.
- Every JavaScript file passes `node --check`.
- A real local Chromium session verifies all five routes, explicit inactive/auth states, login UI,
  responsive shell rendering and zero console warning/error entries.
- Full non-network tests, Ruff, formatting and pre-commit.
