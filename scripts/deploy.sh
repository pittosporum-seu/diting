#!/usr/bin/env bash
# deploy.sh — 谛听一键部署
# 用法: ./scripts/deploy.sh [--skip-tests]
#
# 流程:
#   1. 本地 pytest + ruff（除非 --skip-tests）
#   2. git push（本地失败→通过 VPS 中继）
#   3. VPS git pull + restart
#   4. 验证所有前端文件 + API
#
# 前提：本地 SSH key 已添加到 VPS ~/.ssh/authorized_keys
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VPS="root@240d:c000:f07f:9100:6054:658c:4adc:0"
VPS_REPO="/root/diting-repo"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

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
    warn "未提交改动:"; git status --short; die "请先提交再部署。"
fi

# ─── 2. 本地测试 ───
if [ "$SKIP_TESTS" = false ]; then
    say "Step 2/4: 本地测试"
    uv run pytest tests/ -q    || die "测试失败"
    uv run ruff check src/     || die "Ruff 失败"
    # JS 语法 (如果 node 可用)
    if command -v node &>/dev/null; then
        for f in frontend/js/*.js frontend/js/pages/*.js; do
            node --check "$f" || die "JS 语法错误: $f"
        done
    fi
else
    say "Step 2/4: 跳过测试 (--skip-tests)"
fi

# ─── 3. 推送 + VPS 部署 ───
say "Step 3/4: 推送 & 部署"

# 3a. 尝试本地 push；失败则通过 VPS 中继
if git push origin verify 2>/dev/null; then
    say "  本地 push ✓"
else
    warn "  本地 push 失败，通过 VPS 中继..."
    BRANCH=$(git branch --show-current)
    # 打包当前 HEAD 的所有文件
    git archive -o /tmp/diting-push.tar.gz HEAD
    scp -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        /tmp/diting-push.tar.gz "${VPS}:/tmp/"
    # VPS 上解包 → 提交 → push
    $SSH "$VPS" bash -s << VPS_PUSH
set -e
cd $VPS_REPO
git fetch origin
tar -xzf /tmp/diting-push.tar.gz
git add -A
if git diff --cached --quiet; then
    echo "[vps] no changes to push"
else
    git commit -m "deploy: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push origin verify
    echo "[vps] push ✓"
fi
rm /tmp/diting-push.tar.gz
VPS_PUSH
    rm -f /tmp/diting-push.tar.gz
fi

# 3b. VPS pull + restart（无论 push 走哪条路，最终都要 pull）
$SSH "$VPS" bash -s << 'VPS_SCRIPT'
set -e
echo "[vps] pulling..."
cd /root/diting-repo
git fetch origin
git reset --hard origin/verify
echo "[vps] commit: $(git log --oneline -1)"
echo "[vps] restarting..."
systemctl restart diting
sleep 2
curl -sf http://127.0.0.1:8100/api/health > /dev/null \
  && echo "[vps] ✓ diting OK" \
  || { echo "[vps] ✗ diting FAIL"; systemctl status diting --no-pager | head -10; exit 1; }
VPS_SCRIPT

# ─── 4. 前端验证 ───
say "Step 4/4: 验证前端"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true

PASS=true
FILES=(js/core.js js/cache.js js/api.js js/ui.js js/app.js js/router.js js/charts.js
       js/pages/dashboard.js js/pages/stock.js js/pages/opportunities.js
       js/pages/watchlist.js js/pages/settings.js)

for f in "${FILES[@]}"; do
    SIZE=$(curl -sf --max-time 5 -o /dev/null -w '%{size_download}' \
        "https://pittosporum.cloud/app/diting/$f" 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 100 ]; then
        echo -e "  ${GREEN}✓${NC} $f (${SIZE}B)"
    else
        echo -e "  ${RED}✗${NC} $f (${SIZE}B)"
        PASS=false
    fi
done

# 验证 HTML 含 core.js（证明是新版）
if curl -sf --max-time 5 https://pittosporum.cloud/app/diting/ 2>/dev/null | grep -q 'core.js'; then
    echo -e "  ${GREEN}✓${NC} index.html (core.js present)"
else
    echo -e "  ${RED}✗${NC} index.html (core.js missing)"
    PASS=false
fi

if [ "$PASS" = true ]; then
    echo -e "${GREEN}[deploy] ✓ 部署成功${NC}"
else
    die "前端验证失败，检查 VPS"
fi
