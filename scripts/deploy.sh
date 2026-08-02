#!/usr/bin/env bash
: <<'DOC'
谛听 v0.8 release controller.

Run this script from WSL/Linux after the exact commit has merged to origin/verify.
It never modifies a VPS checkout and never weakens SSH host-key verification.
DOC
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE_DRIVER="$PROJECT_DIR/scripts/vps-deploy-v080.sh"
SERVICE_FILE="$PROJECT_DIR/config/diting-v080.service"
DEFAULT_LOCAL_PORT=18101

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy.sh package [--commit SHA]
  scripts/deploy.sh stage --host HOST --bundle FILE --caddy-config FILE [--dry-run]
  scripts/deploy.sh verify --host HOST --commit SHA [--local-port PORT] [--dry-run]
  scripts/deploy.sh rehearse --host HOST --commit SHA [--dry-run]
  scripts/deploy.sh promote --host HOST --commit SHA [--observe-seconds N] [--dry-run]
  scripts/deploy.sh rollback --host HOST --commit SHA [--dry-run]

Required for `verify` (not logged or transmitted to the VPS):
  DITING_OWNER_TOKEN     raw token used only by the local tunnel smoke test

Optional for `verify`:
  DITING_SMOKE_ORIGIN    allowed production Origin header (default: https://pittosporum.cloud)
EOF
}

die() {
  printf '[release] ERROR: %s\n' "$*" >&2
  exit 1
}

say() {
  printf '[release] %s\n' "$*"
}

require_file() {
  [[ -f "$1" ]] || die "required file does not exist: $1"
}

validate_commit() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || die "commit must be a full 40-character lowercase SHA"
}

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((1 <= 10#$1 && 10#$1 <= 65535)) \
    || die "invalid local port: $1"
}

print_command() {
  printf '[dry-run]'
  printf ' %q' "$@"
  printf '\n'
}

run_or_print() {
  if [[ "$DRY_RUN" == true ]]; then
    print_command "$@"
  else
    "$@"
  fi
}

release_gates() {
  say "running release gates"
  uv run pre-commit run --all-files
  uv run ruff check src/ tests/ browser_tests/ scripts/validate-api.py
  uv run ruff format --check src/ tests/ browser_tests/ scripts/validate-api.py
  uv run pytest tests/ -m "not network" -q
  uv run python scripts/validate-api.py --check
  find frontend -type f -name '*.js' -print0 | xargs -0 -n1 node --check
  find scripts -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
  uv run pytest browser_tests/ -q
}

package_release() {
  local requested_commit="$1" commit verify_commit bundle checksum
  cd "$PROJECT_DIR"
  [[ -z "$(git status --porcelain)" ]] || die "worktree must be clean before packaging"
  commit="$(git rev-parse "${requested_commit:-HEAD}^{commit}")"
  validate_commit "$commit"
  verify_commit="$(git rev-parse 'refs/remotes/origin/verify^{commit}' 2>/dev/null)" \
    || die "origin/verify is unavailable; fetch it before packaging"
  [[ "$commit" == "$verify_commit" ]] \
    || die "release commit must exactly equal the locally fetched origin/verify"
  release_gates
  mkdir -p dist
  bundle="$PROJECT_DIR/dist/diting-$commit.tar.gz"
  checksum="$bundle.sha256"
  git archive --format=tar --prefix="diting-$commit/" "$commit" | gzip -n >"$bundle"
  (cd "$(dirname "$bundle")" && sha256sum "$(basename "$bundle")") >"$checksum"
  (cd "$(dirname "$bundle")" && sha256sum --check "$(basename "$checksum")")
  say "deterministic release: $bundle"
  say "checksum: $checksum"
}

ssh_args=(-o BatchMode=yes -o ConnectTimeout=10)
DRY_RUN=false
COMMAND="${1:-}"
[[ -n "$COMMAND" ]] || { usage; exit 2; }
shift
HOST=""
COMMIT=""
BUNDLE=""
CADDY_CONFIG=""
LOCAL_PORT="$DEFAULT_LOCAL_PORT"
OBSERVE_SECONDS=1800

while (($#)); do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --commit) COMMIT="${2:-}"; shift 2 ;;
    --bundle) BUNDLE="${2:-}"; shift 2 ;;
    --caddy-config) CADDY_CONFIG="${2:-}"; shift 2 ;;
    --local-port) LOCAL_PORT="${2:-}"; shift 2 ;;
    --observe-seconds) OBSERVE_SECONDS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$COMMAND" in
  package)
    [[ "$DRY_RUN" == false ]] || die "package does not support dry-run"
    package_release "$COMMIT"
    ;;
  stage)
    [[ -n "$HOST" ]] || die "--host is required"
    require_file "$BUNDLE"
    require_file "$BUNDLE.sha256"
    require_file "$CADDY_CONFIG"
    require_file "$REMOTE_DRIVER"
    require_file "$SERVICE_FILE"
    COMMIT="$(basename "$BUNDLE")"
    COMMIT="${COMMIT#diting-}"
    COMMIT="${COMMIT%.tar.gz}"
    validate_commit "$COMMIT"
    if [[ "$DRY_RUN" == false ]]; then
      (cd "$(dirname "$BUNDLE")" && sha256sum --check "$(basename "$BUNDLE.sha256")")
    fi
    remote_prefix="/tmp/diting-v080-$COMMIT"
    run_or_print ssh "${ssh_args[@]}" "$HOST" mkdir -p "$remote_prefix"
    run_or_print scp "${ssh_args[@]}" \
      "$BUNDLE" "$BUNDLE.sha256" "$REMOTE_DRIVER" "$SERVICE_FILE" "$CADDY_CONFIG" \
      "$HOST:$remote_prefix/"
    run_or_print ssh "${ssh_args[@]}" "$HOST" sudo bash \
      "$remote_prefix/vps-deploy-v080.sh" prepare \
      --commit "$COMMIT" \
      --bundle "$remote_prefix/$(basename "$BUNDLE")" \
      --checksum "$remote_prefix/$(basename "$BUNDLE.sha256")" \
      --service "$remote_prefix/$(basename "$SERVICE_FILE")" \
      --caddy "$remote_prefix/$(basename "$CADDY_CONFIG")"
    ;;
  verify)
    [[ -n "$HOST" ]] || die "--host is required"
    validate_commit "$COMMIT"
    validate_port "$LOCAL_PORT"
    if [[ "$DRY_RUN" == true ]]; then
      print_command ssh "${ssh_args[@]}" -L \
        "$LOCAL_PORT:127.0.0.1:8101" -N "$HOST"
      print_command env DITING_OWNER_TOKEN='***REDACTED***' \
        DITING_SMOKE_ORIGIN="${DITING_SMOKE_ORIGIN:-https://pittosporum.cloud}" \
        bash "$SCRIPT_DIR/smoke_test.sh" "http://127.0.0.1:$LOCAL_PORT/api/v1"
      print_command ssh "${ssh_args[@]}" "$HOST" sudo bash \
        "/tmp/diting-v080-$COMMIT/vps-deploy-v080.sh" verify --commit "$COMMIT"
      exit 0
    fi
    [[ -n "${DITING_OWNER_TOKEN:-}" ]] || die "DITING_OWNER_TOKEN is required for verification"
    ssh "${ssh_args[@]}" -o ExitOnForwardFailure=yes \
      -L "$LOCAL_PORT:127.0.0.1:8101" -N "$HOST" &
    tunnel_pid=$!
    trap 'kill "$tunnel_pid" 2>/dev/null || true' EXIT INT TERM
    tunnel_ready=false
    for _attempt in $(seq 1 30); do
      if ! kill -0 "$tunnel_pid" 2>/dev/null; then
        wait "$tunnel_pid" 2>/dev/null || true
        die "SSH tunnel exited before becoming ready"
      fi
      if curl --silent --fail --max-time 1 \
        "http://127.0.0.1:$LOCAL_PORT/api/v1/health" >/dev/null; then
        tunnel_ready=true
        break
      fi
      sleep 1
    done
    [[ "$tunnel_ready" == true ]] || die "SSH tunnel did not become ready within 30 seconds"
    DITING_SMOKE_ORIGIN="${DITING_SMOKE_ORIGIN:-https://pittosporum.cloud}" \
      bash "$SCRIPT_DIR/smoke_test.sh" "http://127.0.0.1:$LOCAL_PORT/api/v1"
    ssh "${ssh_args[@]}" "$HOST" sudo bash \
      "/tmp/diting-v080-$COMMIT/vps-deploy-v080.sh" verify --commit "$COMMIT"
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
    trap - EXIT INT TERM
    ;;
  rehearse)
    [[ -n "$HOST" ]] || die "--host is required"
    validate_commit "$COMMIT"
    run_or_print ssh "${ssh_args[@]}" "$HOST" sudo bash \
      "/tmp/diting-v080-$COMMIT/vps-deploy-v080.sh" rehearse --commit "$COMMIT"
    ;;
  promote)
    [[ -n "$HOST" ]] || die "--host is required"
    validate_commit "$COMMIT"
    [[ "$OBSERVE_SECONDS" =~ ^[0-9]+$ ]] || die "invalid --observe-seconds"
    run_or_print ssh "${ssh_args[@]}" "$HOST" sudo bash \
      "/tmp/diting-v080-$COMMIT/vps-deploy-v080.sh" promote \
      --commit "$COMMIT" --observe-seconds "$OBSERVE_SECONDS"
    ;;
  rollback)
    [[ -n "$HOST" ]] || die "--host is required"
    validate_commit "$COMMIT"
    run_or_print ssh "${ssh_args[@]}" "$HOST" sudo bash \
      "/tmp/diting-v080-$COMMIT/vps-deploy-v080.sh" rollback --commit "$COMMIT"
    ;;
  *) usage; die "unknown command: $COMMAND" ;;
esac
