# Task 23 completion report

Status: passed.

- Replaced the import-time legacy route graph with an injected v0.8 router factory.
- Kept `/api/v1/*` as the sole internal API and made every unversioned `/api/*` request return
  `410 API_VERSION_REMOVED` in the standard envelope.
- Distinguished unknown v1 endpoints as `404 NOT_FOUND`.
- Removed legacy Stock/Scan/Dashboard/Watchlist service construction, duplicate `CacheManager`
  creation, implicit prefetch workers and Jinja rendering from the production process.
- Removed two Jinja pages, duplicate CSS/ECharts assets and the direct Jinja dependency.
- Replaced obsolete legacy HTTP suites with a v0.8 integration contract. Existing service-level
  tests remain until their source modules are retired separately.

Focused HTTP/security verification: `27 passed`.

Full non-network regression: `583 passed, 12 deselected`.
