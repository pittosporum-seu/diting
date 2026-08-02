# Deploying Diting v0.8 safely

This is the production deployment how-to. The release controller is intentionally unusable from an
unmerged feature commit and has no `--skip-tests` escape hatch.

## Prerequisites

- The exact release commit is merged to `verify`, locally fetched as `origin/verify`, and its GitHub
  CI is green.
- Run from WSL/Linux with `git`, `uv 0.11.32`, Node.js, Playwright Chromium, `ssh`, `scp`, `curl`,
  `tar`, `gzip` and `sha256sum`.
- The target SSH host is already present in the operator's `known_hosts`; never bypass that check.
- VPS `/usr/local/bin/uv` is exactly 0.11.32. The deploy driver uses it to install Python 3.12 and
  sync `uv.lock` with `--frozen --no-dev`.
- `/etc/diting/env` exists as root:diting mode 0640. At minimum it contains real values for
  `DITING_OWNER_TOKEN_HASH`, `DITING_SESSION_SECRET` and `DITING_ALLOWED_ORIGINS`. Do not put the raw
  Owner token in this file.
- Prepare a complete candidate Caddyfile based on `config/Caddyfile.v080.example`, preserving all
  unrelated production sites and routes. The deployer validates and atomically installs the file;
  it does not attempt a risky textual merge.

## 1. Package the exact verified commit

```bash
git fetch origin verify
bash scripts/deploy.sh package --commit "$(git rev-parse origin/verify)"
```

This reruns pre-commit, Ruff, formatting, non-network pytest, OpenAPI drift, every JavaScript and
shell syntax check, and real Chromium. Output is:

```text
dist/diting-<sha>.tar.gz
dist/diting-<sha>.tar.gz.sha256
```

`git archive` plus `gzip -n` makes repeated packaging of the same commit deterministic.

## 2. Stage and start the candidate

```bash
SHA="$(git rev-parse origin/verify)"
bash scripts/deploy.sh stage \
  --host root@your-vps \
  --bundle "dist/diting-$SHA.tar.gz" \
  --caddy-config "/secure/reviewed/Caddyfile"
```

Prepare creates `/root/diting-archive/<timestamp>-pre-<sha>/`, verifies its `SHA256SUMS`, creates the
non-root runtime identity and isolated release, migrates database copies, validates systemd/Caddy
and starts the candidate on loopback port 8101. It does not change port 8100 or public Caddy state.

## 3. Verify through an SSH tunnel

Keep the raw token only in the local shell environment:

```bash
read -rsp "Owner token: " DITING_OWNER_TOKEN; export DITING_OWNER_TOKEN; echo
export DITING_SMOKE_ORIGIN="https://pittosporum.cloud"
bash scripts/deploy.sh verify --host root@your-vps --commit "$SHA"
unset DITING_OWNER_TOKEN
```

The smoke checks health/readiness/dashboard/opportunities, anonymous Owner rejection, v0.7 `410`,
Owner login, cookie session, CSRF preference write, diagnostics and logout. The token is used only
over the local SSH tunnel and is never logged, archived, uploaded or stored remotely.

Run the browser journey against the tunnel if the candidate changes rendering or deployment
headers. The same application flow is already a required CI gate in `browser_tests/`.

## 4. Rehearse rollback without production writes

```bash
bash scripts/deploy.sh rehearse --host root@your-vps --commit "$SHA"
```

This restores a database backup into a separate rehearsal file and compares hashes, exercises the
release symlink, and revalidates systemd and Caddy. It writes a release-scoped marker; promotion is
rejected if either tunnel verification or this rehearsal is missing.

## 5. Promote and observe

```bash
bash scripts/deploy.sh promote --host root@your-vps --commit "$SHA"
```

Promotion stops the old service, takes fresh database backups, migrates live state, switches
`/opt/diting/current` and the validated Caddyfile atomically, starts one non-root worker on 8100 and
immediately runs the public-only smoke through the real Caddy gateway. It then observes both the
internal and gateway readiness endpoints for 1800 seconds and summarizes error, stale, Provider,
queue and analysis-failure log signals. Either readiness path or the gateway smoke failing triggers
automatic rollback. The default gateway base is
`http://127.0.0.1:8443/api/diting/v1`; use `--gateway-api-base` only when the reviewed production
Caddyfile deliberately listens on a different loopback port.

For a time-bounded rehearsal environment only, `--observe-seconds 30` shortens observation. Do not
shorten the production window.

## Roll back explicitly

```bash
bash scripts/deploy.sh rollback --host root@your-vps --commit "$SHA"
```

Rollback restores the promotion-time database copies and archived systemd/Caddy configuration,
switches to the previous isolated release when one exists, validates/reloads Caddy and accepts either
the v0.8 or old health path. It does not delete the failed release or archive.

## Read-only dry runs

Every remote action supports `--dry-run`, for example:

```bash
bash scripts/deploy.sh promote --host root@your-vps --commit "$SHA" --dry-run
bash scripts/deploy.sh rollback --host root@your-vps --commit "$SHA" --dry-run
```

Dry-run output redacts the token placeholder and never opens SSH or changes files.
