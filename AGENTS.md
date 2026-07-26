# AGENTS.md — 谛听 开发手册

> **给 AI 开发者的施工规范。开始任何工作前，先读完这个文件。**

---

## 0. 项目速览

| 项目 | 谛听 (Diting) |
|------|-------------|
| 定位 | A股多模型AI投资分析工具 · 开源 Python 库 |
| 许可 | MIT |
| Python | 3.12+ |
| 包管理 | uv + pyproject.toml |
| 工作目录 | `~/workspace/diting` |
| 设计文档 | `docs/01-design/` |

### 关键外部依赖

| 包 | 用途 | 安装方式 |
|---|------|---------|
| `litellm` | 统一 100+ LLM provider 接口 | pip |
| `mcpaisuite-sandboxmcp` | Python 沙箱（seccomp+namespace） | pip |
| `click` | CLI 框架 | pip |
| `structlog` | 结构化日志 | pip |
| `vmdpy` | VMD 分解 | pip |
| `PyWavelets` | 小波去噪 | pip |
| `PyEMD` | CEEMDAN | pip |
| `openpyxl` | Excel 读取（mx-data 返回 xlsx） | pip |

---

## 0.5 提交前硬性约束（强制，人与 AI 同样适用）

> 以下检查由 pre-commit 钩子和 CI 强制执行。**任何一项不通过，禁止提交/合并。**

1. **安装钩子**（首次克隆后执行一次）：
   ```bash
   uv sync --extra dev
   pre-commit install
   ```
2. **提交前自动运行**：`git commit` 时 pre-commit 会自动跑：
   - `ruff check --fix`（lint：未使用导入、import 排序、错误检查）
   - `ruff format`（统一格式）
   - 基础检查（去尾空格、文件末尾换行、YAML/TOML 合法性、合并冲突标记）
3. **手动全量验证**（推送前）：
   ```bash
   pre-commit run --all-files      # lint + format + 基础检查
   uv run pytest tests/ -m "not network" -q   # 核心测试必须全过
   ```
4. **CI 门禁**：push/PR 触发 CI，`lint`（ruff check + format check）与核心测试（非网络）为必过门禁；网络测试单独跑、允许偶发失败。
5. **约束对象包含 AI**：AI 开发者（CodeWhale 等）提交代码同样受这些钩子约束，不得绕过未通过 lint/测试的提交。

---

## 1. 设计铁律（不可违反）

### 1.1 依赖方向

```
config ──→ 所有层
Layer 0 (infra) ──→ 不依赖任何业务层
Layer 1 (data)  ──→ L0
Layer 2 (signals)──→ L1 + L0
Layer 3 (engines)──→ L2 + L1
Layer 4 (pipeline)──→ L3 + L2 + L1
Layer 5 (cli/report/notify)──→ L4
```

**铁律：下层永远不 import 上层。** 违反 = 架构腐化。

### 1.2 数据协议

所有跨模块数据必须用 `@dataclass`，定义在 `src/diting/schema.py`。禁止裸传 dict/DataFrame。

```python
# ✅ 正确
result: AnalysisResult = engine.analyze(ctx)

# ❌ 错误
result = engine.analyze(ctx)  # 返回 dict，字段靠猜
```

### 1.3 引擎开发

- 所有分析引擎继承 `AnalysisEngine` ABC
- 用 `@register_engine("name")` 注册
- 新引擎 = 新建文件 + 继承 ABC + 加装饰器。**绝不改已有代码。**
- AI 驱动的引擎：LiteLLM 生成计算代码 → sandboxmcp 执行 → 返回结果

### 1.4 错误处理

```python
# ✅ 正确
logger.error("analysis.failed", engine="wyckoff", reason="ai_timeout")

# ❌ 错误
print("分析失败了")  # 绝对禁止 print
```

- 用 `structlog`，不用 `print`
- 一个引擎失败不阻塞其他引擎
- 数据源不可用时自动降级（mx-data → akshare → SQLite）

---

## 2. 目录结构

```
src/diting/
├── __init__.py
├── main.py              ← CLI 入口（click）
├── config.py            ← .env + watchlist.csv 解析
├── schema.py            ← 所有 @dataclass 协议
├── enums.py             ← Rating, DataSource, DataType, Signal
├── data/                ← Layer 1：数据访问
│   ├── repository.py    ← MarketDataRepository（降级链）
│   ├── cache.py         ← TTL 缓存
│   └── providers/
│       ├── base.py      ← DataProvider ABC
│       ├── mx_data.py   ← 东方财富
│       └── akshare.py   ← akshare 兜底
├── signals/             ← Layer 2：信号处理
│   ├── technical.py     ← RSI/MACD/KDJ/布林/VWAP
│   ├── vmd.py           ← VMD 分解
│   ├── wavelet.py       ← 小波去噪
│   └── ceemdan.py       ← CEEMDAN
├── engines/             ← Layer 3：分析引擎
│   ├── base.py          ← AnalysisEngine ABC
│   ├── registry.py      ← @register_engine 插件机制
│   ├── wyckoff.py       ← 威克夫（AI + 沙箱）
│   ├── buffett.py       ← 巴菲特/芒格（AI + 沙箱）
│   ├── can_slim.py      ← CANSLIM（AI + 沙箱）
│   ├── volume_profile.py← Volume Profile（纯计算）
│   └── vmd_rsi.py       ← VMD+RSI 择时（纯计算）
├── pipeline/            ← Layer 4：编排
│   ├── runner.py        ← AnalysisPipeline
│   ├── consensus.py     ← 多引擎评分融合
│   └── pipeline.yaml    ← 管道配置
├── report/              ← Layer 5：报告
│   ├── builder.py       ← ReportBuilder
│   ├── echarts.py       ← ECharts 图表
│   └── templates/       ← HTML 模板
├── notify/              ← Layer 5：推送
│   ├── base.py          ← Notifier ABC
│   ├── feishu.py
│   ├── email.py
│   └── local.py
├── sandbox/             ← Python 沙箱
│   └── executor.py      ← sandboxmcp 封装
├── ai/                  ← AI Provider
│   └── client.py        ← LiteLLM 封装
├── infra/               ← Layer 0：基础设施
│   ├── logging_config.py← structlog 配置
│   ├── errors.py        ← 异常层次结构
│   └── decorators.py    ← @cached @retry @log_latency
config/
├── .env.example         ← 环境变量模板（无真实值）
├── watchlist.example.csv
└── pipeline.yaml
tests/
├── unit/
├── integration/
└── fixtures/
output/                  ← 报告输出（.gitignore）
```

---

## 3. 开发流程

### 3.0 分工铁律

| 角色 | 干什么 | 不干什么 |
|------|--------|---------|
| **小爪** | 设计文档、架构、Issue 拆分、写 prompt | 不写代码、不改 .py、不跑测试 |
| **CodeWhale** | 所有代码实现 + 写测试 + 验证 + 通知海桐 | 不改设计、不改 AGENTS.md（本文件除外） |

**所有编码工作必须通过 CodeWhale 执行**。小爪只做规划和审核，不直接写代码。

### 3.1 CodeWhale CLI 集成

CodeWhale 是本地 CLI 编码代理（`codewhale`，v0.8.66），配置：
- 默认模型: `deepseek-v4-pro`（provider: deepseek）
- API key: 已配置（`~/.codewhale/config.toml`）
- 工作目录: `~/workspace/diting`

**小爪 → CodeWhale 派活方式：**

```bash
# 非交互式执行（推荐，工具自动审批）
codewhale exec --auto "根据 Issue #N 的描述，实现 xxx 功能"

# 代码审查
codewhale review  # 审查 git diff
```

**信息传递铁律：小爪 ↔ CodeWhale 必须通过文档沟通。**

禁止口头/隐式传递。所有信息必须落盘到文件：

```
小爪 → CodeWhale:
  └─ Issue 文档（docs/01-design/issues/step1-xxx.md）
       ├── 引用设计文档路径
       ├── 列出要修改的文件
       ├── 验收标准
       └── 约束条件

CodeWhale → 小爪:
  └─ 完成报告（docs/01-design/test-results/step1-report.md）
       ├── 改动文件清单
       ├── pytest 结果
       ├── ruff 结果
       └── 手动验证记录
```

**原因：** 小爪和 CodeWhale 是不同 session，没有共同记忆。文档是唯一的通信介质。

**CodeWhale → 小爪 唤醒机制：**

CodeWhale 完成后，必须在状态文件中追加一行标记：

```bash
# CodeWhale 在完成所有工作后执行
echo '{"step":"step1","status":"done","time":"'$(date -Iseconds)'","commit":"'$(git rev-parse --short HEAD)'"}' >> docs/01-design/test-results/codewhale-status.jsonl

# 通知海桐
bash scripts/notify-diting.sh "✅ Step N 完成" "改动: N 文件\npytest: X passed\nruff: clean"
```

小爪在每次 heartbeat 时检查 `codewhale-status.jsonl`，发现新完成的 Step 后自动审查代码。

**CodeWhale 必须执行（不可跳过）：**
1. 写完成报告到 `docs/01-design/test-results/stepN-report.md`
2. 追加状态行到 `docs/01-design/test-results/codewhale-status.jsonl`
3. 运行 `scripts/notify-diting.sh` 通知海桐

**每次派活的 prompt 规范：**
1. 引用设计文档路径
2. 列出要修改/新建的文件
3. 列出验收标准（pytest + ruff + 手动验证）
4. 明确约束（不改设计、不改 AGENTS.md）

```
示例 prompt:
根据 docs/01-design/v0.1.0-backend-design.md Step 1，
新增 FreshnessInfo dataclass 到 src/diting/schema.py，
修复 CacheManager.db_get 的列数安全问题。
完成后运行 pytest 和 ruff check。
不要修改 AGENTS.md 或设计文档。
```

### 3.2 完整测试流程（开发→测试→部署）

```
┌─ 开发 ──────────────────────────────────────────────────┐
│  CodeWhale 写代码 + 单元测试                              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─ 本地测试（必须全部通过） ────────────────────────────────┐
│  1. uv run pytest tests/ -q          # 后端 379+ 测试     │
│  2. uv run ruff check src/           # Python 代码规范    │
│  3. node --check frontend/js/*.js    # 前端 JS 语法       │
│     node --check frontend/js/pages/*.js                   │
│  4. uv run uvicorn src.diting.web.app:app --port 8100 &   │
│     → 浏览器打开 http://localhost:8100/api/health         │
│     → 检查: 仪表盘/个股/自选股/设置 四个页面均正常渲染     │
│     → 检查: 搜索股票、添加自选、切换页面 不报错            │
│     → kill %1 关闭服务                                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─ 部署 ──────────────────────────────────────────────────┐
│  ./scripts/deploy.sh                                      │
│  → 自动执行步骤 1-3 的验证                                │
│  → 推送到 GitHub                                          │
│  → VPS git pull + restart                                 │
│  → 验证所有 JS 文件和 API                                  │
└─────────────────────────────────────────────────────────┘
```

**关键：第 4 步（浏览器 UI 测试）是必须的，不可跳过。** curl API 200 不代表页面能正常渲染——前端 JS 加载、模块依赖、浏览器兼容性都需要真实浏览器验证。

### 3.2 测试检查清单

每次提交前确认：

- [ ] `pytest` 全绿（379+）
- [ ] `ruff check src/` 无问题
- [ ] 所有 `.js` 文件 `node --check` 通过
- [ ] **本地启动 uvicorn，浏览器验证至少 3 个页面正常**
- [ ] 交互: 搜索、点击、切换页面无 console 报错
- [ ] API 信封格式 `{server_time, data, cache_state}` 正确

### 3.3 历史教训

| 问题 | 原因 | 如何防止 |
|------|------|---------|
| 页面白屏（v0.7.2） | 前端循环依赖 + DOMContentLoaded 竞态 | 第 4 步浏览器验证必须做 |
| 前端文件未部署 | 只传了后端，漏了前端 | 部署脚本逐文件验证 |
| quick_score 量比错误 | turnover/volume 是均价不是量比 | 代码审查时检查公式语义 |

---

## 4. AI 引擎开发规范

### 4.1 引擎结构模板

```python
@register_engine("engine_name")
class MyEngine(AnalysisEngine):
    name = "engine_name"
    version = "1.0.0"

    def required_data(self) -> list[DataType]:
        return [DataType.REALTIME, DataType.HISTORICAL]

    def analyze(self, ctx: AnalysisContext) -> AnalysisResult:
        # Step 1: AI 规划计算代码
        code = self._plan_computation(ctx)

        # Step 2: 沙箱执行
        result = sandbox.run(code)

        # Step 3: 如果失败，traceback 喂给 AI 重试 1 次
        if result.errors:
            code = self._fix_code(code, result.errors)
            result = sandbox.run(code)

        # Step 4: 构建结果
        return AnalysisResult(
            engine_name=self.name,
            symbol=ctx.symbol,
            score=result["score"],
            rating=self._to_rating(result["score"]),
            signals=result.get("signals", []),
            narrative=result.get("narrative", ""),
            charts=[],
            risks=result.get("risks", []),
            confidence=result.get("confidence", 0.5),
            computation_log=result.audit_id,
            metadata={},
        )
```

### 4.2 LiteLLM 调用规范

```python
from diting.ai.client import llm

# 所有 AI 调用走这个统一接口
response = llm.completion(
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ],
    max_tokens=4000,
)
```

### 4.3 沙箱调用规范

```python
from diting.sandbox.executor import sandbox

result = sandbox.run(code)
# → SandboxResult(output=..., errors=[...], execution_time_ms=123, audit_id="abc")
```

沙箱配置（在 `config/.env` 中）：
- `SANDBOX_BACKEND=process`（零额外依赖）
- `SANDBOX_MEMORY_MB=512`
- `SANDBOX_TIMEOUT=60`
- 允许的 import：numpy, pandas, scipy, vmdpy, PyWavelets, PyEMD, openpyxl

---

## 5. 关键避坑指南

### 5.1 数据源

- **个股和 ETF 分开查**：mx-data 混合查询会截断 ETF 数据
- **每批不超过 4 只**：批量查询可能静默丢失部分标的
- **ETF 用代码不用简称**：`159770` 而非 "机器人业"，简称可能匹配到行业板块
- **ETF 复权单位净值 ≠ 涨跌幅**：用收盘价直接算

### 5.2 VMD

- **参数顺序**：`VMD(signal, alpha, tau, K, DC, init, tol)` — tau 和 K 互换会报错
- **输出比输入短 1**：`len(u[0]) = len(input) - 1`
- **内存泄漏**：每次调用后 `del u, _, om` + `gc.collect()`
- **窗口约束**：数据必须 ≥ `K * 10` 天

### 5.3 mx-data 查询措辞

- `"股票名 历史收盘价 2026-01-01 至 2026-06-30"` → 日线（正确）
- `"股票名 近一年收盘价"` → 只返回 2 行（错误！）
- 返回的收盘价格式 `66.24元`，需要清理 "元" 字后转 float

### 5.4 cron job 模型必须 Pin

如果用 cron job，必须显式传 model 参数，否则全局模型切换后静默失败。

### 5.5 文件创建

- 所有新文件包含模块 docstring
- 用 `uv run` 运行命令，不用裸 `python`
- 配置模板不含真实值：`.env.example` 而非 `.env`

---

## 6. 开始工作前必读

**优先级顺序：**

1. 本文档（AGENTS.md）
2. `docs/01-design/architecture-overview.md` — 完整架构
3. `src/diting/schema.py` — 所有 @dataclass 定义
4. `docs/01-design/api-contracts.md` — CLI + Python API + 配置
5. `docs/01-design/development-workflow.md` — 开发流程
6. `docs/01-design/issue-plan.md` — Issue 拆分（当前任务清单）

**调研参考（需要背景知识时读）：**
7. `docs/02-research/wyckoff-method.md`
8. `docs/02-research/buffett-munger-a-share.md`
9. `docs/02-research/signal-processing-methods.md`

---

*文档维护：小爪 | 谛听项目组 | 2026-07-08*

## 7. 通知海桐

每次任务完成后，向海桐报告进展。用小爪 bot 身份发到飞书私聊。

### 7.1 命令

```bash
./scripts/notify-diting.sh "Mx 标题" "完成/失败摘要（可多行）"
```

用小爪 bot 的飞书 API 凭据直接发消息到海桐私聊。不需要 lark-cli，纯 Python + urllib。

### 7.2 流程

```
CodeWhale 执行完任务
  → 跑 scripts/notify-diting.sh
    → Python 调用飞书 API（小爪 bot app_id + app_secret）
      → 海桐飞书私聊收到（发件人：小爪）
```

---

## 8. 微服务架构规范（v0.4.0）

### 8.1 网关路由规则

Caddy 作为统一 API 网关，按路径前缀分发：

```
/api/{service}/* → strip /{service} → 对应后端
```

| 路径前缀 | 后端 | 端口 |
|----------|------|:----:|
| `/api/diting` | diting FastAPI | 8100 |
| `/api/xxx` | 未来服务 | 8200 |
| `/app/diting/` | SPA file_server | — |

**规则：**
- Caddy 处理 `/api/diting/xxx` → strip `/diting` → `/api/xxx` → uvicorn
- 后端 FastAPI 路由保持 `/api/health` 不变，不做任何路径修改
- 新服务接入必须先在 `docs/api/diting-openapi.yaml` 注册端点

### 8.2 新服务接入流程

1. 在 `docs/api/diting-openapi.yaml` 新增 paths
2. 运行 `scripts/gen-caddy-from-openapi.py` 重新生成 Caddy 路由段
3. 新服务实现对应的 `/api/xxx` 路由
4. 在 `config/diting.yaml` 的 `services` 块注册新服务（host:port 映射）
5. 运行 `scripts/validate-api.py` 校验 OpenAPI 与路由实现一致性
6. 部署后运行全链路验证（见 `docs/ops/deploy-checklist.md`）

### 8.3 网关功能

| 功能 | 配置 |
|------|------|
| 路径路由 | `handle_path /api/{service}/*` |
| 限流 | 10 rps/服务，burst 2 |
| access log | 结构化 JSON，stdout 输出 |
| 健康检查 | 透传后端 `/api/health` |

### 8.4 前端 API 调用

```javascript
// frontend/js/api.js — v0.4.0 硬编码，不再动态探测
const API_BASE = '/api/diting';
```

### 8.5 契约工具

| 脚本 | 用途 |
|------|------|
| `scripts/gen-caddy-from-openapi.py` | 从 openapi.yaml 生成 Caddy 路由 |
| `scripts/validate-api.py` | 校验 YAML paths vs routes.py 一致性 |
