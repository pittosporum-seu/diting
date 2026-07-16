#!/usr/bin/env bash
# deploy.sh — 谛听一键部署
# 用法: ./scripts/deploy.sh [--skip-tests]
#
# 流程:
#   1. 本地跑 pytest + ruff（除非 --skip-tests）
#   2. 推到 GitHub
#   3. SSH 到 VPS git pull + restart
#   4. 验证前端
#
# 前提：本地 SSH key 已添加到 VPS ~/.ssh/authorized_keys
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VPS_HOST="240d:c000:f07f:9100:6054:658c:4adc:0"
VPS_USER="root"
VPS_REPO="/root/diting-repo"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
say()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }
die()  { echo -e "${RED}[deploy]${NC} $*"; exit 1; }

SKIP_TESTS=false
[[ "${1:-}" == "--skip-tests" ]] && SKIP_TESTS=true

cd "$PROJECT_DIR"

# ─── 1. 工作区检查 ───
say "Step 1/4: 检查工作区"
if [ -n "$(git status --porcelain)" ]; then
    warn "未提交改动:"
    git status --short
    die "请先提交再部署。"
fi

# ─── 2. 本地测试 ───
if [ "$SKIP_TESTS" = false ]; then
    say "Step 2/4: 本地测试"
    uv run pytest tests/ -q        || die "测试失败"
    uv run ruff check src/         || die "Ruff 失败"
else
    say "Step 2/4: 跳过测试 (--skip-tests)"
fi

# ─── 3. 推送 + VPS 部署 ───
say "Step 3/4: 推送 & VPS 部署"
git push origin verify || die "Push 失败"

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 \
    "${VPS_USER}@${VPS_HOST}" bash -s << 'VPS_SCRIPT'
set -e
echo "[vps] pulling..."
cd /root/diting-repo
git fetch origin
git reset --hard origin/verify
echo "[vps] commit: $(git log --oneline -1)"
echo "[vps] restarting diting..."
systemctl restart diting
sleep 2
echo "[vps] health check..."
curl -sf http://127.0.0.1:8100/api/health > /dev/null \
  && echo "[vps] ✓ diting OK" \
  || { echo "[vps] ✗ diting FAIL"; systemctl status diting --no-pager | head -10; exit 1; }
VPS_SCRIPT

# ─── 4. 前端验证 ───
say "Step 4/4: 验证前端"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true
if curl -sfI --max-time 10 "https://pittosporum.cloud/api/diting/health" > /dev/null 2>&1; then
    echo -e "${GREEN}[deploy] ✓ 部署成功${NC}"
else
    warn "前端验证未通过（可能网络问题，VPS 后端已确认正常）"
fi
