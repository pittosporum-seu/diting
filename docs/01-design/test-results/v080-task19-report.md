# Task 19 completion report

Status: passed.

- Added owner-only v1 analysis jobs, job status/cancellation, watchlist CRUD, preferences, cache
  clearing, strategy status and sanitized diagnostics.
- Enforced owner session checks on sensitive reads and session + Origin + CSRF checks on every
  mutation.
- Added bounded one-worker sliding-window limits for public reads, login, analysis and scan calls,
  with stable `429` error codes.
- Added durable watchlist, preference and audit ports/adapters. Legacy comma-separated watchlist tags
  remain readable while all new writes use versioned JSON representation.
- Removed `request_id` and execution `deadline` from the semantic analysis deduplication hash while
  retaining both in the persisted request for correlation and execution control.
- Prevented scan creation from reaching the legacy opportunity path: no active strategy returns
  `NO_ACTIVE_STRATEGY`; active execution remains intentionally unavailable until Task 27.
- Audit actor values use a truncated SHA-256 digest of the session identifier and never persist the
  owner token, cookie or CSRF value.

Verification:

- Focused owner/auth/job/rate-limit/public v1 suite: `32 passed`.
- Full non-network suite: `601 passed, 79 deselected`.
- Ruff checks passed for all changed Python source and tests.
- Runtime OpenAPI generation contains all owner v1 paths.

Known follow-up: Task 27 must replace `SCAN_SERVICE_UNAVAILABLE` with active-strategy scan jobs; it
must preserve the Task 19 authentication, rate-limit and no-fallback boundary.
