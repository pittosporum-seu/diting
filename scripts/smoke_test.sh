#!/usr/bin/env bash
# 谛听 · 全页面端到端拨测
# 测试所有 API 端点是否正常返回
set -euo pipefail

API_BASE="${1:-http://localhost:8100/api}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
  local method="$1" url="$2" expected_code="${3:-200}" body="${4:-}"
  local code
  if [ -z "$body" ]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${API_BASE}${url}" 2>/dev/null || echo "000")
  else
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" -H "Content-Type: application/json" -d "$body" "${API_BASE}${url}" 2>/dev/null || echo "000")
  fi
  if [ "$code" = "$expected_code" ]; then
    printf "${GREEN}PASS${NC} %s %s → %s\n" "$method" "$url" "$code"
    PASS=$((PASS + 1))
  else
    printf "${RED}FAIL${NC} %s %s → %s (expected %s)\n" "$method" "$url" "$code" "$expected_code"
    FAIL=$((FAIL + 1))
  fi
}

echo "═══════════════════════════════════════"
echo "  谛听 拨测 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  API Base: ${API_BASE}"
echo "═══════════════════════════════════════"
echo ""

# ── Health ──
echo "📋 Health Check"
check GET "/health" 200

# ── Dashboard ──
echo ""
echo "📋 Dashboard"
check GET "/dashboard" 200

# ── Market Sentiment ──
echo ""
echo "📋 Market Sentiment"
check GET "/market-sentiment" 200

# ── Opportunities ──
echo ""
echo "📋 Opportunities"
check GET "/opportunities" 200

# ── Settings ──
echo ""
echo "📋 Settings"
check GET "/settings" 200
check POST "/settings" 200 '{"provider_ashare":"1"}'

# ── Watchlist ──
echo ""
echo "📋 Watchlist"
check GET "/watchlist" 200
check POST "/watchlist" 200 '{"code":"000001","name":"平安银行","market":"sz"}'
check DELETE "/watchlist/000001" 200

# ── Stock ──
echo ""
echo "📋 Stock"
check GET "/stock/000001" 200
check GET "/stock-name/000001" 200

# ── Stock Search ──
echo ""
echo "📋 Stock Search"
check GET "/stock-search?q=000001" 200
check GET "/stock-search?q=%E5%B9%B3%E5%AE%89" 200

# ── Summary ──
echo ""
echo "═══════════════════════════════════════"
printf "  ${GREEN}Passed:${NC} %d  ${RED}Failed:${NC} %d\n" "$PASS" "$FAIL"
echo "═══════════════════════════════════════"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
