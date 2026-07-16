#!/usr/bin/env bash
# deploy.sh — 谛听一键部署
# 用法: ./scripts/deploy.sh [--skip-tests]
#
# 流程:
#   1. 本地跑 pytest + ruff（除非 --skip-tests）
#   2. 推到 GitHub
#   3. SSH 到 VPS git pull + restart
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VPS_HOST="240d:c000:f07f:9100:6054:658c:4adc:0"
VPS_USER="root"
VPS_REPO="/root/diting-repo"
CRED_FILE="$HOME/.hermes/credentials/haitong-server.pass"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
say() { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }
die() { echo -e "${RED}[deploy]${NC} $*"; exit 1; }

SKIP_TESTS=false
[[ "${1:-}" == "--skip-tests" ]] && SKIP_TESTS=true

cd "$PROJECT_DIR"

# ─── 1. 本地验证 ───
say "Step 1/5: 检查工作区状态"
if [ -n "$(git status --porcelain)" ]; then
    warn "工作区有未提交改动:"
    git status --short
    warn "请先提交再部署。"
    exit 1
fi

if [ "$SKIP_TESTS" = false ]; then
    say "Step 2/5: 本地测试"
    uv run pytest tests/ -q || die "测试失败，拒绝部署"
    uv run ruff check src/ || die "Ruff 检查失败，拒绝部署"
else
    say "Step 2/5: 跳过测试 (--skip-tests)"
fi

# ─── 2. 推送 GitHub ───
say "Step 3/5: 推送至 GitHub"
git push origin verify || die "Git push 失败"

# ─── 3. VPS 部署 ───
say "Step 4/5: VPS 拉取代码"

VPS_SCRIPT='
set -e
echo "[vps] pulling..."
cd '"$VPS_REPO"'
git fetch origin
git reset --hard origin/verify
echo "[vps] commit: $(git log --oneline -1)"
echo "[vps] restarting diting..."
systemctl restart diting
sleep 2
echo "[vps] health check..."
curl -sf http://127.0.0.1:8100/api/health > /dev/null \
  && echo "[vps] ✓ diting OK" \
  || { echo "[vps] ✗ health check failed"; systemctl status diting --no-pager | head -10; exit 1; }
'

SSH_PASS=$(cat "$CRED_FILE" 2>/dev/null) || die "找不到密码文件: $CRED_FILE"

python3 - "$VPS_HOST" "$VPS_USER" "$SSH_PASS" "$VPS_SCRIPT" << 'PYEOF'
import pexpect, sys
host, user, password, script = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
child = pexpect.spawn('ssh', [
    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
    f'{user}@{host}', script
], timeout=60)
child.expect('password:', timeout=15)
child.sendline(password)
child.expect(pexpect.EOF, timeout=45)
print(child.before.decode())
PYEOF

# ─── 4. 验证前端 ───
say "Step 5/5: 验证前端"

curl -sfI --max-time 10 "https://pittosporum.cloud/api/diting/health" > /dev/null \
  && echo -e "${GREEN}[deploy] ✓ 部署成功${NC}" \
  || warn "前端验证未通过（可能是网络问题）"
