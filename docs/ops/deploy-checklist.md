# 谛听 · 服务器部署规范

> 部署检查清单 | 推代码/更新服务前必读
> v0.4.0 — 微服务架构

---

## 一、URL 约定

```
访问入口:  https://pittosporum.cloud/app/diting/
SPA 前端:  /app/diting/（Caddy file_server → /root/frontend/）
API 路径:  /api/diting/*（Caddy 网关 → strip /diting → uvicorn:8100 /api/*）
证书:      Let's Encrypt（Caddy 自动签发）
```

## 二、服务拓扑

```
用户 → https://pittosporum.cloud
  ├── /app/diting/          → Caddy file_server → /root/frontend/
  ├── /api/diting/*                → Caddy strip /diting → uvicorn:8100 /api/*
  └── 证书                         → Caddy auto HTTPS (Let's Encrypt)

内部服务:
  uvicorn:8100  ← 谛听 API
  trojan:443    ← 代理
```

## 三、部署前检查清单

### 0. 每次变更必验（不可跳过）

每次修改/部署后，必须验证全链路可用：

```bash
# 内网验证（SSH 到服务器执行）
curl -s http://127.0.0.1:8443/api/diting/health                    # API → {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8443/app/diting/  # SPA → 200
curl -s 'http://127.0.0.1:8443/api/diting/stock/002475' | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["name"])'  # 个股 → 立讯精密

# 外网验证（从浏览器/外部 curl）
curl -sk https://pittosporum.cloud/api/diting/health
curl -sk -o /dev/null -w '%{http_code}' https://pittosporum.cloud/app/diting/
```

三条全部通过才算部署成功。**任何一条失败 → 回滚 → 修好再部署。**

### 1. 代码变更检查
- [ ] `uv run pytest -q` — 全部通过
- [ ] `uv run ruff check src/` — 无 lint 错误
- [ ] `.gitignore` 排除了含凭据的文件（`scripts/notify-diting.sh`、`.env`）
- [ ] 推送前排除本地凭据（`config/diting.yaml` 不含真实 key）

### 2. 前端检查
- [ ] `api.js` 中 `API_BASE` 硬编码为 `/api/diting`
- [ ] 搜索栏 placeholder 提示股票代码格式
- [ ] 每个 API 调用前后有 `console.log('[谛听]', ...)` 日志
- [ ] 加载中有状态提示条

### 3. 数据源检查
- [ ] 服务器有 `config/watchlist.csv`
- [ ] 服务器有 `.env` 含 `MX_APIKEY`
- [ ] AshareProvider 优先级正确（priority: 5，最快源）
- [ ] 所有 provider 有 try/except 包裹

### 4. 服务检查
```
systemctl is-active diting caddy   # 都应返回 active
ss -tlnp | grep ':443'            # Caddy
ss -tlnp | grep ':8100'           # uvicorn
ss -tlnp | grep ':9443'           # trojan
```

### 5. 功能检查
- [ ] `curl https://pittosporum.cloud/api/diting/health` → 200
- [ ] `curl https://pittosporum.cloud/app/diting/` → SPA 首页 200
- [ ] `curl https://pittosporum.cloud/api/diting/stock/002475` → 有名称有价格

## 四、API 端点一览（v0.4.0）

| 端点 | 方法 | 说明 |
|------|:----:|------|
| `/api/diting/health` | GET | 健康检查 |
| `/api/diting/stock/{code}` | GET | 个股多引擎分析 |
| `/api/diting/dashboard` | GET | 仪表盘概览 |
| `/api/diting/watchlist` | GET | 自选股列表 |
| `/api/diting/opportunities` | GET | 选股机会 |
| `/api/diting/market-sentiment` | GET | 市场情绪 |
| `/api/diting/settings` | GET/POST | 用户设置 |

完整契约见 `docs/api/diting-openapi.yaml`。

## 五、部署命令速查

```bash
# 推送代码到服务器
cat file.py | ssh haitong-server "cat > /root/src/diting/xxx/xxx.py"

# 重启服务
ssh haitong-server "systemctl restart diting"

# 查看日志
ssh haitong-server "journalctl -u diting --no-pager -n 50"
ssh haitong-server "journalctl -u caddy --no-pager -n 50"
```

## 六、回滚

```bash
# 回滚 diting 到上次提交
cd /root && git stash
systemctl restart diting
```
