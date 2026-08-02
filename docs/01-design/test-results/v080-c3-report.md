# Checkpoint C3 — Interface and security boundary

Status: passed.

## Included commits

- `24f59d1`: owner session, CSRF and origin protection.
- `130c33b`: typed public v1 envelopes and read-only endpoints.
- `2794156`: owner v1 API, audit records and bounded rate limits.
- `556b5a7`: stable context-managed Python facade.
- `a7d0af9`: breaking v0.8 CLI command surface.
- `1427acd`: five-page v1 frontend and browser state machine.
- `d4973c2`: v1-only HTTP graph and permanent legacy removal.

## Decision record

- Anonymous access is limited by `public_readonly`; owner writes require a valid session and all
  browser write requests require same-origin plus CSRF.
- Quote reads never start analysis. Analysis and scans use persistent bounded jobs.
- The frontend has one fetch boundary and displays inactive strategy/auth/unavailable states
  explicitly. Real Chromium inspection produced zero console warnings or errors.
- Unversioned `/api/*` contracts are permanently gone and return 410. Jinja and legacy business
  services are not reachable from the production route graph.

## Gate evidence

- Latest focused HTTP/security suite: `27 passed`.
- Latest full non-network suite: `583 passed, 12 deselected`.
- Pre-commit, Ruff check, Ruff format, JavaScript syntax and diff checks passed for the constituent
  tasks.

No P0/P1 issue remains in the C3 scope. Configured-owner browser automation is intentionally part
of Task 29, after strategy and OpenAPI contracts stabilize.
