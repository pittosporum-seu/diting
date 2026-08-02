#!/usr/bin/env bash
: <<'DOC'
Root-side v0.8 release driver. It is uploaded by scripts/deploy.sh and accepts only an exact SHA.
DOC
set -euo pipefail
umask 077

RELEASE_ROOT=/opt/diting/releases
CURRENT_LINK=/opt/diting/current
STATE_ROOT=/var/lib/diting
DEPLOYMENT_ROOT=/var/lib/diting/deployments
ARCHIVE_ROOT=/root/diting-archive
OLD_REPOSITORY=/root/diting-repo
ENV_FILE=/etc/diting/env
UV_BIN=/usr/local/bin/uv
UV_VERSION=0.11.32
CANDIDATE_UNIT=diting-candidate.service

die() {
  printf '[vps-release] ERROR: %s\n' "$*" >&2
  exit 1
}

say() {
  printf '[vps-release] %s\n' "$*"
}

require_root() {
  [[ "$(id -u)" == 0 ]] || die "this command must run as root"
}

validate_commit() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || die "invalid full commit SHA"
}

require_file() {
  [[ -f "$1" ]] || die "required file does not exist: $1"
}

safe_release_path() {
  [[ "$1" == "$RELEASE_ROOT/"* ]] || die "path escaped release root: $1"
}

wait_ready() {
  local port="$1"
  for _attempt in $(seq 1 60); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:$port/api/v1/ready" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

backup_if_present() {
  local source="$1" target="$2"
  if [[ -f "$source" ]]; then
    install -m 0600 "$source" "$target"
  fi
}

sqlite_backup_if_present() {
  local source="$1" target="$2"
  if [[ ! -f "$source" ]]; then
    return 0
  fi
  python3 - "$source" "$target" <<'PY'
import sqlite3
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
target.unlink(missing_ok=True)
with sqlite3.connect(source) as incoming, sqlite3.connect(target) as outgoing:
    incoming.backup(outgoing)
    result = outgoing.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    raise SystemExit(f"SQLite backup integrity failed: {result}")
PY
  chmod 0600 "$target"
}

archive_existing_state() {
  local archive_dir="$1" untracked_list
  mkdir -p "$archive_dir"
  chmod 700 "$archive_dir"
  if [[ -d "$OLD_REPOSITORY/.git" ]]; then
    untracked_list="$archive_dir/untracked-files.list0"
    git -C "$OLD_REPOSITORY" ls-files --others --exclude-standard -z >"$untracked_list"
    if [[ -s "$untracked_list" ]]; then
      tar --null --verbatim-files-from --create --gzip \
        --file "$archive_dir/old-repository-untracked.tar.gz" \
        --directory "$OLD_REPOSITORY" --files-from "$untracked_list"
    fi
  fi
  sqlite_backup_if_present "$STATE_ROOT/diting.db" "$archive_dir/state-diting.db"
  sqlite_backup_if_present "$STATE_ROOT/diting_cache.db" "$archive_dir/state-diting_cache.db"
  sqlite_backup_if_present "$OLD_REPOSITORY/diting.db" "$archive_dir/legacy-diting.db"
  sqlite_backup_if_present \
    "$OLD_REPOSITORY/diting_cache.db" "$archive_dir/legacy-diting_cache.db"
  backup_if_present /etc/caddy/Caddyfile "$archive_dir/Caddyfile"
  backup_if_present /etc/systemd/system/diting.service "$archive_dir/diting.service"
  (
    cd "$archive_dir"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z | xargs -0 -r sha256sum >SHA256SUMS
    sha256sum --check SHA256SUMS
  )
}

ensure_runtime_identity() {
  if ! getent passwd diting >/dev/null; then
    useradd --system --home-dir "$STATE_ROOT" --shell /usr/sbin/nologin diting
  fi
  install -d -m 0755 -o root -g root /opt/diting "$RELEASE_ROOT"
  install -d -m 0700 -o diting -g diting "$STATE_ROOT" "$STATE_ROOT/reports"
  # The candidate runs as `diting` and must be able to traverse the two
  # root-owned deployment directories to reach its own 0700 data directory.
  # Group execute grants traversal only; it does not permit listing or writes.
  install -d -m 0710 -o root -g diting "$DEPLOYMENT_ROOT"
  install -d -m 0700 -o root -g root "$ARCHIVE_ROOT" /etc/diting
  require_file "$ENV_FILE"
  chown root:diting "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
}

verify_uv() {
  require_file "$UV_BIN"
  local actual
  actual="$($UV_BIN --version | awk '{print $2}')"
  [[ "$actual" == "$UV_VERSION" ]] \
    || die "expected uv $UV_VERSION at $UV_BIN, found ${actual:-unknown}"
}

verify_service() {
  local service="$1" release="$2" temporary
  temporary="/tmp/diting-v080-service-verify-$(basename "$release").service"
  sed "s#/opt/diting/current#$release#g" "$service" >"$temporary"
  systemd-analyze verify "$temporary"
  rm -f -- "$temporary"
}

migrate_copy() {
  local release="$1" business="$2" cache="$3"
  DITING_DB_PATH="$business" DITING_CACHE_DB_PATH="$cache" DITING_AI_ENABLED=false \
    "$release/.venv/bin/python" - "$business" "$cache" <<'PY'
import sys
from pathlib import Path

from diting.persistence.migrations import migrate_databases

reports = migrate_databases(Path(sys.argv[1]), Path(sys.argv[2]))
if not all(report.ready for report in reports):
    raise SystemExit("database-copy migration readiness failed")
PY
}

prepare() {
  local commit="$1" bundle="$2" checksum="$3" service="$4" caddy="$5"
  local release incoming archive_dir deployment candidate_data previous_release
  validate_commit "$commit"
  require_file "$bundle"
  require_file "$checksum"
  require_file "$service"
  require_file "$caddy"
  [[ "$bundle" == /tmp/diting-v080-*/* ]] || die "bundle must be staged under /tmp/diting-v080-*"
  (
    cd "$(dirname "$bundle")"
    sha256sum --check "$(basename "$checksum")"
  )
  ensure_runtime_identity
  verify_uv
  caddy validate --config "$caddy" --adapter caddyfile

  archive_dir="$ARCHIVE_ROOT/$(date -u +%Y%m%dT%H%M%SZ)-pre-$commit"
  archive_existing_state "$archive_dir"
  release="$RELEASE_ROOT/$commit"
  safe_release_path "$release"
  if [[ ! -d "$release" ]]; then
    incoming="$RELEASE_ROOT/.incoming-$commit"
    safe_release_path "$incoming"
    rm -rf -- "$incoming"
    install -d -m 0755 -o diting -g diting "$incoming"
    tar --extract --gzip --file "$bundle" --directory "$incoming" --strip-components=1
    chown -R diting:diting "$incoming"
    mv -- "$incoming" "$release"
  fi
  sudo -u diting env UV_CACHE_DIR="$STATE_ROOT/.uv-cache" \
    "$UV_BIN" python install 3.12
  sudo -u diting env UV_CACHE_DIR="$STATE_ROOT/.uv-cache" \
    "$UV_BIN" sync --frozen --no-dev --python 3.12 --directory "$release"
  verify_service "$service" "$release"

  if [[ ! -f "$STATE_ROOT/diting.db" && -f "$OLD_REPOSITORY/diting.db" ]]; then
    sqlite_backup_if_present "$OLD_REPOSITORY/diting.db" "$STATE_ROOT/diting.db"
    chown diting:diting "$STATE_ROOT/diting.db"
  fi
  if [[ ! -f "$STATE_ROOT/diting_cache.db" && -f "$OLD_REPOSITORY/diting_cache.db" ]]; then
    sqlite_backup_if_present "$OLD_REPOSITORY/diting_cache.db" "$STATE_ROOT/diting_cache.db"
    chown diting:diting "$STATE_ROOT/diting_cache.db"
  fi

  deployment="$DEPLOYMENT_ROOT/$commit"
  install -d -m 0710 -o root -g diting "$deployment"
  install -m 0644 "$service" "$deployment/diting.service"
  install -m 0600 "$caddy" "$deployment/Caddyfile"
  candidate_data="$deployment/candidate-data"
  install -d -m 0700 -o diting -g diting "$candidate_data"
  if [[ -f "$STATE_ROOT/diting.db" ]]; then
    sqlite_backup_if_present "$STATE_ROOT/diting.db" "$candidate_data/diting.db"
  fi
  if [[ -f "$STATE_ROOT/diting_cache.db" ]]; then
    sqlite_backup_if_present "$STATE_ROOT/diting_cache.db" "$candidate_data/diting_cache.db"
  fi
  chown -R diting:diting "$candidate_data"
  migrate_copy "$release" "$candidate_data/diting.db" "$candidate_data/diting_cache.db"

  systemctl stop "$CANDIDATE_UNIT" 2>/dev/null || true
  systemctl reset-failed "$CANDIDATE_UNIT" 2>/dev/null || true
  systemd-run --unit="${CANDIDATE_UNIT%.service}" --service-type=simple \
    --uid=diting --gid=diting --working-directory="$release" \
    --property="EnvironmentFile=$ENV_FILE" \
    --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
    /usr/bin/env \
      DITING_ENVIRONMENT=production DITING_PUBLIC_READONLY=true DITING_AI_ENABLED=false \
      DITING_DB_PATH="$candidate_data/diting.db" \
      DITING_CACHE_DB_PATH="$candidate_data/diting_cache.db" \
      "$release/.venv/bin/python" -m uvicorn diting.web.app:app \
      --host 127.0.0.1 --port 8101 --workers 1 --no-access-log
  wait_ready 8101 || {
    journalctl -u "$CANDIDATE_UNIT" --no-pager -n 80 >&2
    die "candidate readiness failed"
  }
  (
    cd "$release"
    DITING_SMOKE_PUBLIC_ONLY=true bash scripts/smoke_test.sh \
      http://127.0.0.1:8101/api/v1
  )

  previous_release="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
  printf 'ARCHIVE_DIR=%q\nPREVIOUS_RELEASE=%q\nRELEASE=%q\n' \
    "$archive_dir" "$previous_release" "$release" >"$deployment/state.env"
  chmod 0600 "$deployment/state.env"
  say "candidate ready on 127.0.0.1:8101 for commit $commit"
  say "verify through an SSH tunnel before promotion"
}

mark_verified() {
  local commit="$1" deployment
  validate_commit "$commit"
  deployment="$DEPLOYMENT_ROOT/$commit"
  [[ -f "$deployment/state.env" ]] || die "candidate was not prepared"
  wait_ready 8101 || die "candidate is not ready"
  printf '%s %s\n' "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$deployment/verified"
  chmod 0600 "$deployment/verified"
  say "candidate verification recorded"
}

rehearse_rollback() {
  local commit="$1" deployment release rehearsal source_hash restored_hash
  validate_commit "$commit"
  deployment="$DEPLOYMENT_ROOT/$commit"
  require_file "$deployment/verified"
  require_file "$deployment/state.env"
  # shellcheck disable=SC1090
  source "$deployment/state.env"
  release="$RELEASE"
  safe_release_path "$release"
  rehearsal="$deployment/rollback-rehearsal"
  rm -rf -- "$rehearsal"
  install -d -m 0700 -o root -g root "$rehearsal"
  if [[ -f "$deployment/candidate-data/diting.db" ]]; then
    cp "$deployment/candidate-data/diting.db" "$rehearsal/backup.db"
    source_hash="$(sha256sum "$rehearsal/backup.db" | awk '{print $1}')"
    cp "$rehearsal/backup.db" "$rehearsal/restored.db"
    restored_hash="$(sha256sum "$rehearsal/restored.db" | awk '{print $1}')"
    [[ "$source_hash" == "$restored_hash" ]] || die "database restore rehearsal mismatch"
  fi
  ln -s "$release" "$rehearsal/current"
  [[ "$(readlink -f "$rehearsal/current")" == "$release" ]] \
    || die "release symlink rehearsal failed"
  verify_service "$deployment/diting.service" "$release"
  caddy validate --config "$deployment/Caddyfile" --adapter caddyfile
  printf '%s %s\n' "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >"$deployment/rollback-rehearsed"
  chmod 0600 "$deployment/rollback-rehearsed"
  say "rollback rehearsal passed without changing production state"
}

restore_backup() {
  local backup="$1" destination="$2"
  if [[ -f "$backup" ]]; then
    sqlite_backup_if_present "$backup" "$destination"
    chown diting:diting "$destination"
  fi
}

rollback() {
  local commit="$1" deployment archive_dir previous_release release
  validate_commit "$commit"
  deployment="$DEPLOYMENT_ROOT/$commit"
  require_file "$deployment/state.env"
  # shellcheck disable=SC1090
  source "$deployment/state.env"
  archive_dir="$ARCHIVE_DIR"
  previous_release="$PREVIOUS_RELEASE"
  release="$RELEASE"
  safe_release_path "$release"
  systemctl stop diting.service 2>/dev/null || true
  restore_backup "$archive_dir/promote-diting.db" "$STATE_ROOT/diting.db"
  restore_backup "$archive_dir/promote-diting_cache.db" "$STATE_ROOT/diting_cache.db"
  if [[ -n "$previous_release" && -d "$previous_release" ]]; then
    safe_release_path "$previous_release"
    ln -sfn "$previous_release" "$CURRENT_LINK.next"
    mv -Tf "$CURRENT_LINK.next" "$CURRENT_LINK"
  fi
  if [[ -f "$archive_dir/diting.service" ]]; then
    install -m 0644 "$archive_dir/diting.service" /etc/systemd/system/diting.service
  fi
  if [[ -f "$archive_dir/Caddyfile" ]]; then
    install -m 0644 "$archive_dir/Caddyfile" /etc/caddy/Caddyfile.rollback
    caddy validate --config /etc/caddy/Caddyfile.rollback --adapter caddyfile
    mv -f /etc/caddy/Caddyfile.rollback /etc/caddy/Caddyfile
  fi
  systemctl daemon-reload
  systemctl start diting.service
  caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  if ! curl --silent --fail --max-time 5 http://127.0.0.1:8100/api/v1/health >/dev/null \
    && ! curl --silent --fail --max-time 5 http://127.0.0.1:8100/api/health >/dev/null; then
    die "rollback service health failed"
  fi
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$deployment/rolled-back"
  say "rollback completed; release files were retained"
}

prune_releases() {
  local current previous candidate resolved kept=0
  current="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
  previous="$1"
  while IFS= read -r candidate; do
    resolved="$(readlink -f "$candidate")"
    safe_release_path "$resolved"
    if [[ "$resolved" == "$current" || "$resolved" == "$previous" || $kept -lt 2 ]]; then
      kept=$((kept + 1))
      continue
    fi
    [[ "$(basename "$resolved")" =~ ^[0-9a-f]{40}$ ]] \
      || die "refusing to prune unexpected release path: $resolved"
    rm -rf -- "$resolved"
  done < <(find "$RELEASE_ROOT" -mindepth 1 -maxdepth 1 -type d -name '[0-9a-f]*' \
    -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
}

promote() {
  local commit="$1" observe_seconds="$2" deployment archive_dir previous_release release
  local started errors stale provider queue analysis_failed elapsed=0
  validate_commit "$commit"
  [[ "$observe_seconds" =~ ^[0-9]+$ ]] || die "invalid observation duration"
  deployment="$DEPLOYMENT_ROOT/$commit"
  require_file "$deployment/verified"
  require_file "$deployment/rollback-rehearsed"
  require_file "$deployment/state.env"
  # shellcheck disable=SC1090
  source "$deployment/state.env"
  archive_dir="$ARCHIVE_DIR"
  previous_release="$PREVIOUS_RELEASE"
  release="$RELEASE"
  safe_release_path "$release"
  wait_ready 8101 || die "verified candidate is no longer ready"
  caddy validate --config "$deployment/Caddyfile" --adapter caddyfile
  verify_service "$deployment/diting.service" "$release"

  sqlite_backup_if_present "$STATE_ROOT/diting.db" "$archive_dir/promote-diting.db"
  sqlite_backup_if_present \
    "$STATE_ROOT/diting_cache.db" "$archive_dir/promote-diting_cache.db"
  (
    cd "$archive_dir"
    for backup in promote-diting.db promote-diting_cache.db; do
      [[ -f "$backup" ]] && sha256sum "$backup" >>SHA256SUMS
    done
    sha256sum --check SHA256SUMS
  )
  systemctl stop diting.service 2>/dev/null || true
  if ! migrate_copy "$release" "$STATE_ROOT/diting.db" "$STATE_ROOT/diting_cache.db"; then
    systemctl start diting.service 2>/dev/null || true
    die "live migration failed; old service restart attempted"
  fi
  chown diting:diting "$STATE_ROOT/diting.db" "$STATE_ROOT/diting_cache.db"
  ln -sfn "$release" "$CURRENT_LINK.next"
  mv -Tf "$CURRENT_LINK.next" "$CURRENT_LINK"
  install -m 0644 "$deployment/diting.service" /etc/systemd/system/diting.service
  install -m 0644 "$deployment/Caddyfile" "/etc/caddy/Caddyfile.next-$commit"
  caddy validate --config "/etc/caddy/Caddyfile.next-$commit" --adapter caddyfile
  mv -f "/etc/caddy/Caddyfile.next-$commit" /etc/caddy/Caddyfile
  systemctl daemon-reload
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  systemctl start diting.service
  if ! wait_ready 8100; then
    rollback "$commit"
    die "new service readiness failed; rollback completed"
  fi
  caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

  while ((elapsed < observe_seconds)); do
    sleep_for=10
    if ((observe_seconds - elapsed < sleep_for)); then
      sleep_for=$((observe_seconds - elapsed))
    fi
    ((sleep_for > 0)) && sleep "$sleep_for"
    elapsed=$((elapsed + sleep_for))
    if ! curl --silent --fail --max-time 3 http://127.0.0.1:8100/api/v1/ready >/dev/null; then
      rollback "$commit"
      die "readiness failed during observation; rollback completed"
    fi
  done
  errors="$(journalctl -u diting.service --since "$started" --no-pager | grep -ci 'error' || true)"
  stale="$(journalctl -u diting.service --since "$started" --no-pager | grep -ci 'stale' || true)"
  provider="$(journalctl -u diting.service --since "$started" --no-pager | grep -ci 'provider' || true)"
  queue="$(journalctl -u diting.service --since "$started" --no-pager | grep -ci 'queue' || true)"
  analysis_failed="$(journalctl -u diting.service --since "$started" --no-pager \
    | grep -ci 'analysis.failed' || true)"
  printf 'observation errors=%s stale=%s provider=%s queue=%s analysis_failed=%s\n' \
    "$errors" "$stale" "$provider" "$queue" "$analysis_failed"
  systemctl stop "$CANDIDATE_UNIT" 2>/dev/null || true
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$deployment/promoted"
  prune_releases "$previous_release"
  say "promotion and ${observe_seconds}s observation completed"
}

require_root
COMMAND="${1:-}"
shift || true
COMMIT=""
BUNDLE=""
CHECKSUM=""
SERVICE=""
CADDY=""
OBSERVE_SECONDS=1800
while (($#)); do
  case "$1" in
    --commit) COMMIT="${2:-}"; shift 2 ;;
    --bundle) BUNDLE="${2:-}"; shift 2 ;;
    --checksum) CHECKSUM="${2:-}"; shift 2 ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    --caddy) CADDY="${2:-}"; shift 2 ;;
    --observe-seconds) OBSERVE_SECONDS="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$COMMAND" in
  prepare) prepare "$COMMIT" "$BUNDLE" "$CHECKSUM" "$SERVICE" "$CADDY" ;;
  verify) mark_verified "$COMMIT" ;;
  rehearse) rehearse_rollback "$COMMIT" ;;
  promote) promote "$COMMIT" "$OBSERVE_SECONDS" ;;
  rollback) rollback "$COMMIT" ;;
  *) die "command must be prepare, verify, rehearse, promote or rollback" ;;
esac
