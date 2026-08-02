# v0.8.0 Checkpoint C5 release report

Status: passed and promoted to production on 2026-08-02.

## Released identity

- Production commit: `b92e270134573eb34a5be65653ac0cd027e238b2` (merge of PR #8 into
  `verify`).
- Deterministic bundle: `diting-b92e270134573eb34a5be65653ac0cd027e238b2.tar.gz`.
- Bundle SHA256: `12aaf316a820fdfece55b9e156d939eab538f350fedd1dc5480db4856724197b`.
- Runtime release: `/opt/diting/releases/b92e270134573eb34a5be65653ac0cd027e238b2`.
- Pre-promotion archive:
  `/root/diting-archive/20260802T092106Z-pre-b92e270134573eb34a5be65653ac0cd027e238b2`.
  Its Caddy, systemd, business/cache database, untracked-file and promotion backup checksums all
  passed after promotion.

The evidence in this report is committed after the production SHA by design. It is an audit-only
documentation change and does not require restarting the already verified application artifact.

## Pull requests and remote gates

- PR #4 delivered the complete v0.8 implementation and documentation baseline.
- PRs #5-#7 fixed issues found only by the real candidate host: deployment-directory traversal,
  empty-database migration ownership and SSH tunnel readiness.
- The first promotion attempt for `8fde3d5` exposed a semantically invalid Caddy rewrite and an
  invalid first-isolated-release rollback pointer. The new service was stopped and the legacy
  service, Caddyfile and databases were restored from the verified archive without data loss.
- PR #8 added direct gateway-path replacement, public smoke through the real gateway, dual
  readiness monitoring, safe first-isolated-release rollback and rollback on service/Caddy
  activation failure.
- PR #8 completed all seven required GitHub checks: lint, core pytest, network pytest, OpenAPI and
  syntax contracts, Playwright Chromium, lockfile and aggregate all-checks-pass.

No production promotion was accepted from an unmerged branch or from a commit other than the then
current `origin/verify`.

## Exact-commit verification

- `pre-commit run --all-files`: passed.
- Ruff check and format check: passed; 184 files formatted.
- Core test suite: 636 passed, 12 network tests deselected.
- Runtime OpenAPI matched the checked-in OpenAPI 3.1 contract.
- Every frontend JavaScript and production shell script passed syntax validation.
- Checked-in Playwright suite: 3 passed in real Chromium.
- Candidate public smoke: 6 passed, 0 failed.
- Candidate Owner smoke through an SSH tunnel: 11 passed, 0 failed.
- Candidate Chromium: dashboard, stock, opportunities, watchlist, settings and login dialog passed
  with zero console/page errors.
- Rollback rehearsal passed without modifying production state.

The raw Owner token remained in a WSL file with mode 0600. It was used only by local smoke clients
over SSH tunnels and was never written to Git, VPS files, logs or notifications.

## Promotion evidence

- Promotion migrated the live SQLite databases as the non-root `diting` identity and atomically
  switched the release symlink, systemd unit and validated Caddyfile.
- The real gateway public smoke passed 6/0 immediately after Caddy reload.
- The mandatory 1800-second observation completed with
  `errors=0 stale=0 provider=0 queue=0 analysis_failed=0`.
- Post-promotion production Owner smoke passed 11/0.
- Public production Chromium passed all five pages plus the login dialog with zero console/page
  errors.
- Public endpoints returned 200 for v1 health/readiness and the SPA, while the removed unversioned
  gateway contract returned 410.
- systemd runs one `diting` worker with zero restarts; the candidate unit is inactive.
- `/etc/diting/env` is `root:diting 0640`; both live SQLite files are `diting:diting 0600`.
- Only the current and immediately preceding isolated release directories are retained.

## Intentional production state and residual debt

There is no fabricated active opportunity strategy. Production returns an empty list, null strategy
identity and `NO_ACTIVE_STRATEGY` in the v1 envelope until real research passes every validation gate
and an Owner explicitly activates the version.

Known non-blocking debt remains unchanged: legacy SQLite timestamp converters emit Python 3.12
deprecation warnings, high wavelet levels can emit boundary warnings, synchronous Provider calls can
occupy the single ASGI worker, and custom cookie/CSRF authentication is documented but is not an
OpenAPI security scheme. None caused a release error or altered fail-closed scoring/strategy
semantics.
