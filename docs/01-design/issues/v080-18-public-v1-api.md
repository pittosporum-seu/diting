# Task 18 — Versioned envelope and public v1 API

## Goal

Expose non-mutating resources under `/api/v1` without triggering hidden analysis or legacy scoring.

## Contract

- Every v1 success and error uses `ApiEnvelope[T]` with API version, request id, server time, typed
  data, result/cache/freshness/warning metadata and one structured error.
- Health and readiness are always anonymous and do not call external providers.
- Search, quote, completed analysis, dashboard and active opportunities are anonymous only when
  `public_readonly=true`; otherwise an owner session is required.
- Quote/search read only through `DataGateway`; completed runs read only through `DurableStore`.
- `GET /stocks/{code}` never starts AI analysis.
- No active strategy returns empty opportunities plus `NO_ACTIVE_STRATEGY` and cannot invoke the
  legacy ranking path.
- Validation and production failures never expose stack traces, secret values or raw provider data.
