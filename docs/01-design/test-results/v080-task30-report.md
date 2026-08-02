# Task 30 completion report

Status: passed for release tooling; production execution is correctly gated.

- Removed the mutable root-checkout deployment that disabled SSH host verification, reset the VPS
  worktree, created VPS commits and exposed a test-skipping path.
- Added a deterministic checksummed release controller that packages only a clean commit exactly
  equal to locally fetched `origin/verify` and first runs every core/contract/browser gate.
- Added explicit stage → tunnel verify → rollback rehearse → promote → rollback states. All remote
  commands support read-only dry-run and normal SSH known-host verification.
- Prepare archives old-repository untracked files, databases, Caddy and systemd with SHA256
  verification. SQLite state uses the Online Backup API plus `PRAGMA integrity_check`, including
  candidate copies and promotion-time backups.
- Added isolated `/opt/diting/releases/<sha>` installs using pinned uv 0.11.32/Python 3.12, a
  non-root single-worker hardened systemd service, `/var/lib/diting` state and explicit report path.
- Candidate port 8101 must pass public smoke and the raw-token Owner/CSRF smoke through a local SSH
  tunnel. The raw token is redacted and is never uploaded or stored remotely.
- Promotion requires both verification and non-production rollback-rehearsal markers, validates
  Caddy/systemd, atomically switches the release/Caddy configuration and observes readiness for 30
  minutes by default. Readiness failure automatically restores database/service/Caddy backups.
- Replaced the v0.7 smoke and deployment documentation with the v0.8 API and exact operational
  workflow. The supplied Caddyfile is an explicit review template; production must preserve other
  sites in a complete operator-reviewed file.

Focused deployment/config verification: `23 passed` across policy/config and live candidate browser
tests. Shell syntax passed for all three release scripts; dry-run covered every remote state.

Real candidate smoke: `11 passed, 0 failed`; Chromium: `3 passed`, zero console/page errors.

Full non-network regression: `629 passed, 12 deselected`.

No VPS was contacted or changed. That is required behavior until merge to `verify` and remote CI are
green; actual candidate/promotion evidence belongs to the release checkpoint, not this code commit.
