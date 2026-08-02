# Task 19 — Owner v1 API and rate limiting

## Goal

Expose every v0.8 mutation and sensitive operational read through an authenticated owner boundary,
without reusing legacy service paths or weakening the public API contract.

## Contract

- Owner writes require a valid server-side session, trusted `Origin` and matching CSRF token.
- Owner-only reads include jobs, watchlist, preferences, strategy state and sanitized diagnostics.
- Analysis creation is asynchronous and returns `202` with a durable job resource; equivalent active
  requests deduplicate independently of correlation `request_id` and execution `deadline`.
- Scan creation checks the active strategy first. Until Task 27 provides `ScanOrchestrator`, an
  inactive strategy returns `NO_ACTIVE_STRATEGY` and an active strategy cannot fall back to legacy
  scanning.
- Watchlist and preference writes use typed durable-store contracts and append audit events whose
  actor identifier is a one-way session digest.
- Cache administration calls the injected cache port, never legacy cache tables.
- One-worker sliding-window limits are 60 public reads/minute/IP, 5 login attempts/15 minutes/IP,
  10 analyses/hour/session and 2 scans/hour/session. Every limit has a stable error code.
- In-memory rate-limit identity state is bounded to prevent unbounded cardinality growth.

## Verification

- Permission matrix for anonymous, authenticated-read and protected-write access.
- Origin/CSRF rejection and accepted analysis job flow.
- Persistent watchlist, preference and audit records against a migrated SQLite database.
- Cache, strategy, diagnostics and inactive-scan behavior.
- Deterministic sliding-window boundaries, per-key isolation and business error codes.
- Full non-network test suite, Ruff, formatting, frontend syntax and pre-commit gates.
