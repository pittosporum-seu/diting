# Task 31 completion report

Status: passed locally; remote CI and production release remain C5 gates.

## Documentation outcome

- Replaced the public README and contributor guide with the implemented v0.8 contract: versioned
  CLI/Python/API entry points, owner security, cache-mediated data access, explicit engines and
  fail-closed strategy semantics.
- Added a Diátaxis documentation index, current-design status index, first-analysis tutorial,
  configuration reference and engine/strategy extension How-to guides.
- Rewrote the active API and development workflow references so they no longer advertise legacy
  `/api/*`, L0/L1/L2 CLI aliases, decorator discovery or mutable VPS checkout deployment.
- Marked all pre-v0.8 design families as Superseded while retaining them as historical records.
- Updated research status truthfully: governance and the `mean_reversion_v1` candidate exist, but
  no real experiment has yet been validated, approved or activated.
- Added documentation contract tests that derive version, CLI and OpenAPI facts from the runtime,
  validate every active relative link and reject obsolete release/API/registration claims.

## Release review

- Architecture: no concrete Provider imports outside adapters/bootstrap; v1 production requests use
  the typed gateway, orchestrators and strategy registry.
- Security: anonymous and owner routes remain separated; session/Origin/CSRF and rate-limit browser
  flows pass; tracked secret-name scan found only `config/.env.example`.
- Migration and rollback: idempotent migration tests pass; release tooling requires checked SQLite
  backups, candidate-copy migration and rollback rehearsal before promotion.
- Score semantics: engine failures remain failures and consensus cannot synthesize a neutral 50;
  insufficient evidence keeps `analysis_score` null.
- Strategy governance: obsolete `dist_high_20: 0.85` is absent from the production ranking path;
  no active strategy returns `NO_ACTIVE_STRATEGY` rather than legacy fallback results.
- Browser: five anonymous pages and the complete Owner journey run in real Chromium with zero
  console/page errors.
- Deployment: destructive operations are limited to resolved release/temp targets; no disabled SSH
  host verification, working-tree reset or test-skipping mode remains.

No P0 or P1 release finding was identified. Remaining non-blocking debt is recorded rather than
hidden: synchronous provider work can occupy the single ASGI worker, custom cookie/CSRF dependencies
are documented but not represented as an OpenAPI security scheme, legacy SQLite timestamp adapters
emit Python 3.12 deprecation warnings, and Caddy validation must run against the operator-complete
production configuration during C5.

## Verification

- `uv run pre-commit run --all-files`: passed.
- `uv run ruff check src/ tests/ browser_tests/ scripts/validate-api.py`: passed.
- `uv run ruff format --check src/ tests/ browser_tests/ scripts/validate-api.py`: 184 files clean.
- `uv run pytest tests/ -m "not network" -q`: 635 passed, 12 deselected, 36 warnings.
- `uv run pytest browser_tests/ -q`: 3 passed.
- `uv run python scripts/validate-api.py --check`: runtime and checked-in OpenAPI match.
- All frontend JavaScript passed `node --check`; both production shell scripts passed `bash -n`.
- `uv lock --check`: 118 packages resolved with no lock drift.

## C5 boundary

Task 31 does not claim remote evidence. C5 still requires pushing this exact commit, opening the PR
against `verify`, observing the Linux CI result, merging only after green checks, then staging and
verifying the candidate on port 8101 before any production promotion.
