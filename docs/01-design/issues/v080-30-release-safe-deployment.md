# Task 30 — Release-safe VPS deployment

## Goal

Replace the mutable root checkout deployment with an exact, checksummed, non-root release process
whose candidate, verification, promotion and rollback states are explicit and recoverable.

## Contract

- Packaging is allowed only from a clean commit exactly equal to locally fetched `origin/verify`.
  It runs every local release gate, produces deterministic `git archive | gzip -n` output and writes
  a SHA256 check file.
- SSH uses the operator's normal known-host verification. The release process never resets, commits
  or pushes from the VPS and has no test-skipping mode.
- Prepare archives old-repository untracked files, business/cache databases, Caddy and systemd with
  verified checksums before touching release state.
- Each release is isolated under `/opt/diting/releases/<sha>`, built by pinned uv 0.11.32/Python
  3.12 and served by a non-root, single-worker hardened systemd service.
- Migrations run first on candidate database copies. Candidate port 8101 must pass public smoke and
  a local SSH-tunnel Owner smoke; the raw token never reaches the VPS.
- A non-production rollback rehearsal verifies database copy restoration, release symlink, systemd
  and Caddy candidates. Promotion refuses to run without both verification markers.
- Promotion backs up the current live databases again, migrates live state while the old service is
  stopped, atomically switches the release symlink and validated Caddyfile, then observes readiness
  for 1800 seconds by default.
- Any readiness failure invokes rollback. Explicit rollback restores database, Caddy and systemd
  backups, switches to the previous release when available and retains release files for audit.

## Verification

- Shell syntax and static safety-policy tests.
- Controller dry-run for verify/rehearse/promote/rollback.
- Candidate smoke over a live v0.8 FastAPI server, including anonymous boundary, Owner login/CSRF
  write/diagnostics/logout and removed-v0.7 410 behavior.
- Full non-network and Playwright gates.

Actual VPS preparation/promotion remains forbidden until this branch is merged to `verify` and the
remote CI result is green.
