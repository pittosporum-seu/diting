#!/usr/bin/env bash
: "Diting v0.8 public/security/owner candidate smoke test."
set -euo pipefail

API_BASE="${1:-http://127.0.0.1:8101/api/v1}"
ORIGIN="${DITING_SMOKE_ORIGIN:-https://pittosporum.cloud}"
PYTHON_BIN="${DITING_SMOKE_PYTHON:-python3}"
WORK_DIR="$(mktemp -d)"
COOKIE_JAR="$WORK_DIR/cookies"
RESPONSE="$WORK_DIR/response.json"
HEADERS="$WORK_DIR/headers"
trap 'rm -rf -- "$WORK_DIR"' EXIT INT TERM
chmod 700 "$WORK_DIR"

pass=0
fail=0

check_envelope() {
  "$PYTHON_BIN" - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    body = json.load(stream)
required = {"api_version", "request_id", "server_time", "data", "meta", "error"}
if set(body) != required or body["api_version"] != "1.0":
    raise SystemExit("invalid v1 envelope")
PY
}

request() {
  local label="$1" expected="$2" method="$3" url="$4"
  shift 4
  local status
  status="$(curl --silent --show-error --max-time 15 \
    --output "$RESPONSE" --write-out '%{http_code}' --request "$method" "$url" "$@" \
    || printf '000')"
  if [[ "$status" == "$expected" ]]; then
    if [[ "$url" == *'/v1/'* ]]; then
      check_envelope "$RESPONSE"
    fi
    printf 'PASS %-28s %s\n' "$label" "$status"
    pass=$((pass + 1))
  else
    printf 'FAIL %-28s got=%s expected=%s\n' "$label" "$status" "$expected" >&2
    fail=$((fail + 1))
  fi
}

request health 200 GET "$API_BASE/health"
request readiness 200 GET "$API_BASE/ready"
request dashboard 200 GET "$API_BASE/dashboard"
request opportunities 200 GET "$API_BASE/opportunities"
request anonymous-owner-boundary 401 GET "$API_BASE/watchlist"

case "$API_BASE" in
  */api/diting/v1) LEGACY_URL="${API_BASE%/v1}/health" ;;
  */api/v1) LEGACY_URL="${API_BASE%/api/v1}/api/health" ;;
  *) printf 'Unsupported API base: %s\n' "$API_BASE" >&2; exit 2 ;;
esac
request removed-v0.7-contract 410 GET "$LEGACY_URL"

if [[ -n "${DITING_OWNER_TOKEN:-}" ]]; then
  chmod 600 "$COOKIE_JAR" "$RESPONSE" "$HEADERS" 2>/dev/null || true
  "$PYTHON_BIN" - "$WORK_DIR/login.json" <<'PY'
import json
import os
import sys

with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({"token": os.environ["DITING_OWNER_TOKEN"]}, stream)
PY
  request owner-login 200 POST "$API_BASE/auth/session" \
    --header "Origin: $ORIGIN" --header 'Content-Type: application/json' \
    --cookie-jar "$COOKIE_JAR" --dump-header "$HEADERS" \
    --data-binary "@$WORK_DIR/login.json"
  csrf="$("$PYTHON_BIN" - "$RESPONSE" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["data"]["csrf_token"])
PY
)"
  [[ -n "$csrf" ]] || { printf 'FAIL missing CSRF token\n' >&2; exit 1; }
  request owner-watchlist 200 GET "$API_BASE/watchlist" --cookie "$COOKIE_JAR"
  request owner-preference-write 200 PUT "$API_BASE/preferences" \
    --header "Origin: $ORIGIN" --header "X-CSRF-Token: $csrf" \
    --header 'Content-Type: application/json' --cookie "$COOKIE_JAR" \
    --data '{"key":"page_size","value":20}'
  request owner-diagnostics 200 GET "$API_BASE/admin/diagnostics" --cookie "$COOKIE_JAR"
  request owner-logout 200 DELETE "$API_BASE/auth/session" \
    --header "Origin: $ORIGIN" --header "X-CSRF-Token: $csrf" --cookie "$COOKIE_JAR"
elif [[ "${DITING_SMOKE_PUBLIC_ONLY:-false}" == "true" ]]; then
  printf 'SKIP owner flow (public-only candidate precheck)\n'
else
  printf 'FAIL DITING_OWNER_TOKEN is required for the full candidate smoke test\n' >&2
  fail=$((fail + 1))
fi

printf 'Smoke summary: %d passed, %d failed\n' "$pass" "$fail"
((fail == 0))
