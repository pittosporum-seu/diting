# Task 27 — Active-strategy `ScanOrchestrator`

## Goal

Make opportunity ranking a single typed application path that requires an active governed strategy,
uses only the Data Gateway and isolates every cached/durable result by its reproducibility identity.

## Contract

- No active strategy returns an empty failed `ScanResult` with `NO_ACTIVE_STRATEGY` before any data
  call. Missing manifest/definition also fails closed.
- The point-in-time stock catalog, exchange calendar and every historical series come through the
  Data Gateway using fresh-required semantics for an explicit scan.
- Runtime coverage is at least 90% and at least 500 eligible securities; lower coverage produces no
  ranking. Tests may inject a smaller minimum fixture.
- Factor values follow the active typed definition. Cross-sectional ranks apply signed training
  directions and approved weights; missing factors exclude that period/asset.
- Cache identity includes strategy name/version, manifest, factor version, exchange data date and
  frozen config hash. Cache metadata exposes the same dimensions.
- Successful results persist the exact manifest/factor/config/date identity and are reused only for
  the same cache key.
- Owner scan creation uses the single-worker bounded JobService, dedupes by active identity, reports
  progress and supports cooperative cancellation.
- Public opportunities read only the latest completed result for the exact active version; they
  never compute or fall back during a GET.

## Verification

- Inactive, evidence-missing, active ranking, persistence, cache reuse/isolation, coverage and
  cancellation tests.
- Owner job and public latest-result API contract tests.
- Migration, full non-network tests, Ruff, formatting and pre-commit.
